"""A receita da imagem bate com o que a plataforma precisa em tempo de execução.

Não substitui subir o contêiner — substitui descobrir, depois de subir, que a
tela responde 404 porque ninguém copiou `web/`. Era exatamente o estado da
receita: ela carregava o motor e a api, e mais nada do que foi construído
desde então.

Teste de receita, não de imagem: roda em dois segundos e sem Docker.
"""
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
DOCKERFILE = RAIZ / "infra" / "Dockerfile"
COMPOSE = RAIZ / "infra" / "docker-compose.yml"


@pytest.fixture(scope="module")
def receita():
    return DOCKERFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def compose():
    return COMPOSE.read_text(encoding="utf-8")


def copiados(receita: str) -> set[str]:
    """O que a imagem leva de dentro do projeto."""
    alvos = set()
    for linha in receita.splitlines():
        m = re.match(r"\s*COPY\s+(.+)", linha)
        if not m:
            continue
        partes = [p for p in m.group(1).split() if not p.startswith("--")]
        for p in partes[:-1]:
            alvos.add(p.rstrip("/").split("/")[0])
    return alvos


class TestAImagemLevaOQuePrecisa:
    def test_leva_o_motor_e_a_api(self, receita):
        assert {"motor", "api"} <= copiados(receita)

    def test_leva_a_tela(self, receita):
        """`GET /` lê `web/index.html` do disco. Sem a pasta, a plataforma sobe
        e responde 404 dizendo que a interface não foi instalada."""
        assert "web" in copiados(receita)

    def test_leva_o_worker(self, receita):
        assert "worker.py" in copiados(receita)

    def test_leva_o_projeto_de_video(self, receita):
        """Sem ele, `animar` responde 503 para sempre: a plataforma entrega
        metade do produto e nada na imagem explica por quê."""
        assert "video" in copiados(receita)

    def test_instala_as_dependencias_do_video(self, receita):
        assert "npm ci" in receita or "npm install" in receita

    def test_instala_a_cli_do_generativo(self, receita):
        """Sem ela o fundo cai para bloco de cor em toda peça."""
        assert "@higgsfield/cli" in receita


class TestOQueODesenhoPrecisa:
    def test_o_chromium_vai_preso_na_serie(self, receita):
        """Ele mede o texto: outra SÉRIE muda o corpo da fonte em toda peça,
        caladamente. O patch de segurança pode entrar — ele é obrigado a
        entrar, porque o arquivo de segurança apaga a versão anterior e um
        pino exato vence sozinho — e quem confere se a medida mudou é a peça
        de prova, a cada empurrão."""
        assert "ARG CHROMIUM_SERIE=" in receita
        assert 'chromium=$versao' in receita
        assert "apt-cache madison chromium" in receita

    def test_a_serie_presa_e_a_da_regua_aceita(self, receita):
        """Série no Dockerfile e régua gravada têm que falar do mesmo
        navegador: separadas, uma troca silenciosa passa."""
        import json
        serie = re.search(r"ARG CHROMIUM_SERIE=([\d.]+)", receita).group(1)
        aceita = json.loads((RAIZ / "testes" / "tipografia-aceita.json")
                            .read_text(encoding="utf-8"))
        assert aceita["desenhado_com"]["chromium"].startswith(serie)

    def test_as_bandeiras_do_chrome_vem_por_ambiente(self, receita):
        """Dentro do contêiner o processo é root e o Chromium não abre sem
        `--no-sandbox`; no Mac a bandeira não existe."""
        assert "--no-sandbox" in receita and "CHROME_FLAGS" in receita

    def test_o_remotion_usa_o_chromium_da_imagem(self, receita):
        """Sem `CHROME_BIN` o Remotion baixa um navegador próprio na primeira
        peça — minutos de espera e outra métrica de texto."""
        assert "CHROME_BIN" in receita
        from api import animacao
        import inspect
        assert "browser-executable" in inspect.getsource(animacao.renderizar)


class TestOCompose:
    def test_o_worker_sobe_pelo_worker_py(self, compose):
        """Dois jeitos de subir o mesmo worker é um jeito a mais de eles
        divergirem: é o `worker.py` que escolhe a classe por sistema."""
        assert "python worker.py" in compose

    def test_repassa_a_chave_do_modelo(self, compose):
        assert "ANTHROPIC_API_KEY" in compose

    def test_le_as_credenciais_do_env_do_projeto(self, compose):
        """Um lugar só para a chave e o segredo: o mesmo `.env` que a
        plataforma usa fora do contêiner. Cópia em dois lugares é cópia que
        diverge."""
        # um por serviço que roda a plataforma: api, worker e faxina
        assert compose.count("- ../.env") == compose.count("dockerfile: infra/Dockerfile")

    def test_a_saude_denuncia_segredo_sorteado(self):
        """A garantia saiu do compose e foi para a aplicação, onde também vale
        no Mac: sorteado a cada subida, o selo desloga todo mundo no reinício,
        e com duas réplicas cada uma recusa o selo da outra."""
        import inspect

        from api import main
        fonte = inspect.getsource(main.saude)
        assert "segredo_configurado" in fonte

    def test_guarda_o_login_do_generativo(self, compose):
        """Sem volume, cada subida pede login de novo e o fundo cai para
        bloco de cor sem ninguém perceber."""
        assert "higgsfield:" in compose

    def test_os_dados_ficam_em_volume(self, compose):
        """Trabalho entregue não pode morrer com o contêiner."""
        assert "STORAGE_DIR: /dados" in compose and "dados:/dados" in compose


class TestAFaxinaRoda:
    """Código que apaga disco e ninguém chama é disco que não é apagado. A
    plataforma já teve regra escrita e nunca chamada duas vezes."""

    def test_o_compose_sobe_a_faxina(self, compose):
        assert "python -m api.faxina" in compose

    def test_ela_enxerga_o_disco_dos_trabalhos(self, compose):
        # fatia pelo recuo do serviço: "redis:" aparece antes dentro da URL
        # da fila, e cortar ali devolvia um bloco vazio que passava em tudo
        bloco = compose[compose.index("\n  faxina:"):compose.index("\n  redis:")]
        assert "dados:/dados" in bloco and "STORAGE_DIR: /dados" in bloco

    def test_da_para_mudar_o_prazo_sem_tocar_na_imagem(self, compose):
        assert "REPLICAI_FAXINA_DIAS" in compose


class TestNadaDeDependenciaDeCarona:
    """`anthropic` era importado dentro das funções e não estava em
    requirements nenhum. A ausência não derruba nada: `disponivel()` devolve
    False e a plataforma inteira passa a compor pela régua, em silêncio. No
    contêiner, nenhuma peça teria saído do modelo."""

    def _declaradas(self) -> set[str]:
        nomes = set()
        for arq in ("requirements.txt", "requirements-api.txt"):
            for linha in (RAIZ / arq).read_text(encoding="utf-8").splitlines():
                m = re.match(r"([A-Za-z0-9_.\-]+)\s*[=<>]", linha.strip())
                if m:
                    nomes.add(m.group(1).lower().replace("-", "_"))
        return nomes

    def _importados(self) -> set[str]:
        """Todo módulo de terceiro importado em api/ e motor/, inclusive os
        importados dentro de função — que são justamente os que escapam."""
        padrao = re.compile(r"^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)")
        de_casa = {"api", "motor", "testes"}
        achados = set()
        for pasta in ("api", "motor"):
            for arq in (RAIZ / pasta).rglob("*.py"):
                for linha in arq.read_text(encoding="utf-8").splitlines():
                    m = padrao.match(linha)
                    if m:
                        achados.add(m.group(1))
        padroes = set(__import__("sys").stdlib_module_names)
        return {n for n in achados if n not in padroes and n not in de_casa}

    def test_todo_import_de_terceiro_esta_declarado(self):
        apelidos = {"pil": "pillow", "psd_tools": "psd_tools", "yaml": "pyyaml",
                    "fitz": "pymupdf", "dateutil": "python_dateutil"}
        faltando = set()
        for mod in self._importados():
            nome = apelidos.get(mod.lower(), mod.lower())
            if nome not in self._declaradas():
                faltando.add(mod)
        assert not faltando, f"importado e não declarado: {sorted(faltando)}"


class TestODiscoPorTrabalho:
    """Num PSD de 60 MB, 120 dos 131 MB guardados eram a mesma arte duas
    vezes. Com os volumes dos planos, isso é a diferença entre um disco de
    80 GB durar três meses ou seis."""

    def test_a_arte_nao_e_guardada_duas_vezes(self, tmp_path):
        from api.compositor import CompositorPreserva
        from api.pipeline import desdobrar
        from PIL import Image
        arte = tmp_path / "arte.png"
        Image.new("RGB", (1200, 1200), (12, 42, 102)).save(arte)
        saida = tmp_path / "trabalho"
        desdobrar(arte, ["gdn-300x250"], CompositorPreserva(), saida)
        base = saida / "base.png"
        assert base.exists()
        assert base.stat().st_ino == arte.stat().st_ino, \
            "a arte foi copiada em vez de ligada"

    def test_apagar_uma_ponta_nao_leva_a_outra(self, tmp_path):
        """Ligação não é atalho: cada nome vale sozinho."""
        from api.compositor import CompositorPreserva
        from api.pipeline import desdobrar
        from PIL import Image
        arte = tmp_path / "arte.png"
        Image.new("RGB", (600, 600), (12, 42, 102)).save(arte)
        saida = tmp_path / "trabalho"
        desdobrar(arte, ["gdn-300x250"], CompositorPreserva(), saida)
        arte.unlink()
        assert (saida / "base.png").exists()
        Image.open(saida / "base.png").verify()


class TestAPortaPublica:
    """Sem certificado, a senha de quem entra atravessa a internet legível e
    o navegador marca o site como não seguro."""

    def test_existe_porta_com_certificado(self, compose):
        assert "caddy" in compose.lower()

    def test_a_api_nao_fica_exposta_direto(self, compose):
        """Expor a api ao lado da porta segura deixa uma entrada em HTTP puro
        aberta — e quem souber a porta entra por ela."""
        bloco = compose[compose.index("\n  api:"):compose.index("\n  worker:")]
        assert "ports:" not in bloco, "a api está publicando porta própria"

    def test_o_dominio_vem_do_ambiente(self, compose):
        assert "DOMINIO" in compose

    def test_o_caddyfile_existe_e_aponta_para_a_api(self):
        caddy = (RAIZ / "infra" / "Caddyfile").read_text(encoding="utf-8")
        assert "reverse_proxy api:8000" in caddy


class TestOEnvDeExemplo:
    """Configuração que não existe é pior do que configuração faltando:
    parece resolvida. O arquivo prometia HIGGSFIELD_API_KEY e S3_*, que nada
    no código jamais leu."""

    def _exemplo(self) -> set[str]:
        nomes = set()
        for linha in (RAIZ / ".env.example").read_text(encoding="utf-8").splitlines():
            m = re.match(r"#?\s*([A-Z][A-Z0-9_]+)=", linha.strip())
            if m:
                nomes.add(m.group(1))
        return nomes

    def _lidas(self) -> set[str]:
        nomes = set()
        for pasta in ("api", "motor"):
            for arq in (RAIZ / pasta).rglob("*.py"):
                nomes.update(re.findall(r'os\.environ(?:\.get)?[\[(]"([A-Z_]+)"',
                                        arq.read_text(encoding="utf-8")))
        return nomes

    # lidas pelo compose, não pelo código: o Caddy pega o domínio e o compose
    # decide quantos workers sobem. Ficam de fora da conta, mas têm que estar
    # escritas em algum lugar — por isso o teste seguinte
    DO_COMPOSE = {"DOMINIO", "REPLICAI_WORKERS"}

    def test_o_exemplo_nao_promete_o_que_ninguem_le(self):
        fora = self._exemplo() - self._lidas() - self.DO_COMPOSE
        assert not fora, f"prometido no .env.example e nunca lido: {sorted(fora)}"

    def test_as_do_compose_existem_mesmo_no_compose(self, compose):
        """A exceção não pode virar porta dos fundos: o que entra nela tem que
        ser lido pelo compose de verdade."""
        from pathlib import Path
        caddy = (RAIZ / "infra" / "Caddyfile").read_text(encoding="utf-8")
        for nome in self.DO_COMPOSE:
            assert f"${{{nome}" in compose or f"${{{nome}" in caddy, nome

    def test_as_obrigatorias_estao_no_exemplo(self):
        assert {"ANTHROPIC_API_KEY", "REPLICAI_SEGREDO", "ASAAS_API_KEY",
                "ASAAS_AVISO_TOKEN"} <= self._exemplo()


class TestVideoNaoTravaPeca:
    """Um worker só atendendo as duas filas faz um vídeo de dois minutos
    travar todas as peças atrás dele — e peça é o que a pessoa está olhando a
    tela esperando."""

    def test_sao_dois_workers_com_filas_proprias(self, compose):
        assert "python worker.py replicai\n" in compose
        assert "python worker.py replicai-video" in compose

    def test_nenhum_worker_atende_as_duas(self, compose):
        """`worker.py` sem argumento pega as duas filas: é o padrão que a
        separação existe para evitar."""
        import re
        # só as linhas de comando: o comentário acima delas também cita o
        # arquivo, e cobrá-lo pela regra reprovava a explicação
        for linha in compose.splitlines():
            if "command:" in linha and "worker.py" in linha:
                assert re.search(r"worker\.py\s+replicai", linha), linha

    def test_o_video_roda_um_por_vez(self, compose):
        """O render já usa o navegador inteiro; dois na mesma máquina disputam
        CPU sem entregar mais rápido."""
        bloco = compose[compose.index("\n  worker-video:"):compose.index("\n  faxina:")]
        assert "replicas: 1" in bloco


class TestOEditorAlcancaTodoMundo:
    """As caixas do editor se sobrepõem — a logo fica debaixo do CTA, o
    mascote atrás do texto. Sem ordem por tamanho, o manípulo de quem está
    embaixo fica coberto pelo vizinho e o arrasto pega a camada errada."""

    def _tela(self) -> str:
        return (RAIZ / "web" / "index.html").read_text(encoding="utf-8")

    def test_o_menor_fica_por_cima(self):
        tela = self._tela()
        assert "200 - Math.round(Math.sqrt(c.w * c.h) / 12)" in tela
        assert "z-index:${ed.sel === g.chave ? 300 : ordem}" in tela

    def test_o_manipulo_se_acha_sobre_a_arte(self):
        """Onze pixels sem contorno somem sobre uma foto."""
        tela = self._tela()
        bloco = tela[tela.index(".pe-el .puxa{"):tela.index(".pe-el .letra{")]
        assert "box-shadow" in bloco and "z-index" in bloco


class TestATravaDaRegua:
    """O navegador é quem mede o texto. Trocar a versão dele muda o corpo da
    fonte em toda peça, sem erro nenhum para avisar — foi por isso que a
    versão vive presa no Dockerfile. A trava da régua é a outra metade: ela
    confere, a cada rodada, se a medida continua a mesma.

    A comparação é exata porque a medida foi testada antes de ser gravada:
    três amostras, duas máquinas do GitHub, o mesmo valor até a casa decimal.
    Folga inventada deixaria passar justamente o que a trava existe para pegar.
    """

    def _prova(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "prova", RAIZ / "testes" / "prova_container.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def _medido(self, corpo="69.8"):
        return [{"classe": "txt", "papel": "headline", "size": corpo,
                 "tinta": "75,178,450,154"},
                {"classe": "txt", "papel": "apoio", "size": "25.6",
                 "tinta": "74,352,460,65"}]

    AMBIENTE = {"chromium": "155.0.8059.39-1~deb13u1", "fontes_dejavu": "2.37-8"}

    def test_a_medida_de_hoje_passa(self):
        assert self._prova().conferir_medida(self._medido(), self.AMBIENTE) == 0

    def test_meio_pixel_a_mais_reprova(self):
        """Sem folga: um décimo de pixel é o navegador medindo de outro jeito,
        e o que vem depois é toda peça com outro tamanho de letra."""
        assert self._prova().conferir_medida(self._medido("69.9"), self.AMBIENTE) != 0

    def test_tinta_fora_do_lugar_reprova(self):
        """O corpo pode bater e a letra ocupar outro espaço: é o mesmo
        problema com outra cara."""
        medido = self._medido()
        medido[0]["tinta"] = "75,178,452,154"
        assert self._prova().conferir_medida(medido, self.AMBIENTE) != 0

    def test_bloco_que_sumiu_reprova(self):
        assert self._prova().conferir_medida(self._medido()[:1], self.AMBIENTE) != 0

    def test_fora_do_conteiner_nao_confere(self):
        """No Mac não há DejaVu: o navegador cai numa fonte do sistema e mede
        15% menor. Reprovar ali seria reprovar por outro motivo."""
        assert self._prova().conferir_medida(self._medido("58.0"), None) == 0

    def test_o_numero_gravado_e_o_que_a_esteira_mediu(self):
        """Se alguém editar o arquivo da medida, é aqui que aparece."""
        import json
        d = json.loads((RAIZ / "testes" / "tipografia-aceita.json").read_text())
        assert str(d["blocos"]["headline"]["size"]) == "69.8"
        assert str(d["blocos"]["apoio"]["size"]) == "25.6"
        assert d["desenhado_com"]["chromium"].startswith("155.")

    def test_a_medida_aceita_diz_como_se_atualiza(self):
        """Arquivo de trava sem instrução vira arquivo que alguém apaga."""
        texto = (RAIZ / "testes" / "tipografia-aceita.json").read_text(encoding="utf-8")
        assert "de propósito" in texto and "peça de prova" in texto
