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
    def test_o_chromium_vai_preso_na_versao(self, receita):
        """Ele mede o texto: outra versão muda o corpo da fonte em toda peça,
        caladamente."""
        assert re.search(r'chromium=\$\{CHROMIUM_VERSAO\}', receita)

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

    def test_exige_o_segredo_da_sessao(self, compose):
        """Sorteado a cada subida, ele desloga todo mundo no reinício — e com
        duas réplicas da api, cada uma recusa o selo da outra."""
        assert re.search(r"REPLICAI_SEGREDO:\s*\$\{REPLICAI_SEGREDO:\?", compose)

    def test_guarda_o_login_do_generativo(self, compose):
        """Sem volume, cada subida pede login de novo e o fundo cai para
        bloco de cor sem ninguém perceber."""
        assert "higgsfield:" in compose

    def test_os_dados_ficam_em_volume(self, compose):
        """Trabalho entregue não pode morrer com o contêiner."""
        assert "STORAGE_DIR: /dados" in compose and "dados:/dados" in compose


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
