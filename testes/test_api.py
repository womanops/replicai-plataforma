"""Os endpoints: subir a arte, acompanhar, baixar.

A API não renderiza — ela recebe, guarda, enfileira e responde. O que se testa
aqui é isso, e principalmente o que ela faz com entrada torta: formato que não
existe, arquivo que não serve, identificador que tenta sair da pasta.
"""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from testes.conftest import assinatura_valendo


class FilaEspia:
    """Anota o que foi enfileirado em vez de executar.

    A API não renderiza — ela enfileira. Deixar a fila executar de verdade
    fazia cada teste abrir o Chrome: a suíte ia a 103 segundos e deixaria de
    ser rodada. O render tem testes próprios, no pipeline."""

    def __init__(self):
        self.pedidos = []

    def enfileirar(self, fn, *args, **kwargs):
        self.pedidos.append((fn.__name__, args))
        return f"espiado-{len(self.pedidos)}"


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    """Um cliente já autenticado: desde que a plataforma tem contas, nenhum
    endereço de trabalho responde sem conta."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("REPLICAI_SEGREDO", "segredo-de-teste")
    monkeypatch.delenv("REDIS_URL", raising=False)
    import importlib
    from api import contas, main, trabalhos
    # `contas` não é recarregado de propósito: recarregar troca a classe da
    # exceção, e outro teste que a importou passa a comparar com a antiga
    importlib.reload(trabalhos)
    importlib.reload(main)
    main.FILA = FilaEspia()
    conta = assinatura_valendo(
        contas.criar("Teste", "teste@exemplo.com", "senha-bem-comprida"))
    chave = contas.nova_chave(conta, "testes")
    c = TestClient(main.app, headers={"Authorization": f"Bearer {chave}"})
    c.fila = main.FILA
    c.conta = conta
    return c


@pytest.fixture
def anonimo(cliente):
    """O mesmo servidor, sem credencial nenhuma."""
    from api import main
    return TestClient(main.app)


def arte_png(w=1200, h=1200):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (12, 42, 102)).save(buf, "PNG")
    buf.seek(0)
    return buf


def enviar(cliente, **extra):
    campos = {"formatos": "gdn-300x250", "headline": "Chegamos a Porto Belo"}
    campos.update(extra)
    return cliente.post("/jobs", files={"arte": ("arte.png", arte_png(), "image/png")},
                        data=campos)


class TestSaude:
    def test_diz_qual_fila_esta_mesmo_em_uso(self, cliente):
        """Serve para o operador saber se o Redis conectou ou se a plataforma
        caiu para execução direta — a diferença some sem este aviso."""
        r = cliente.get("/saude")
        assert r.status_code == 200
        assert r.json()["fila"] == "FilaEspia"


class TestCatalogo:
    def test_lista_os_formatos_para_o_front_montar_a_tela(self, cliente):
        r = cliente.get("/formatos")
        assert r.status_code == 200
        fs = r.json()
        assert len(fs) >= 20
        assert {"id", "nome", "w", "h"} <= set(fs[0])


class TestEnvioComEntradaTorta:
    def test_recusa_arquivo_que_nao_serve(self, cliente):
        r = cliente.post("/jobs", files={"arte": ("planilha.xlsx", b"x", "application/octet-stream")},
                         data={"formatos": "gdn-300x250", "headline": "Oi"})
        assert r.status_code == 415
        assert ".xlsx" in r.json()["detail"]

    def test_recusa_formato_inventado(self, cliente):
        r = enviar(cliente, formatos="nao-existe")
        assert r.status_code == 422
        assert "/formatos" in r.json()["detail"]

    def test_sem_formato_o_envio_vira_rascunho(self, cliente):
        """Deixou de ser erro: a arte sobe primeiro e os formatos vêm depois,
        que é a ordem em que a pessoa decide. Quem manda rodar sem formato aí
        sim é recusado — está em `test_rascunho.py`."""
        r = enviar(cliente, formatos="  ")
        assert r.status_code == 200
        assert r.json()["status"] == "rascunho"
        assert cliente.fila.pedidos == []

    def test_a_mensagem_diz_qual_formato_esta_errado(self, cliente):
        r = enviar(cliente, formatos="ig-stories,inventado-99")
        assert "inventado-99" in r.json()["detail"]


class TestEnvio:
    def test_aceita_e_devolve_o_identificador(self, cliente):
        r = enviar(cliente, titulo="Save the Date Energiza")
        assert r.status_code == 202
        assert r.json()["job"].startswith("save-the-date-energiza-")

    def test_dois_envios_com_o_mesmo_titulo_nao_se_sobrescrevem(self, cliente):
        a = enviar(cliente, titulo="Campanha").json()["job"]
        b = enviar(cliente, titulo="Campanha").json()["job"]
        assert a != b

    def test_a_arte_fica_guardada_no_trabalho(self, cliente, tmp_path):
        """Dentro da pasta da conta: isolar por pasta é o que impede um
        cliente de alcançar o arquivo do outro."""
        job = enviar(cliente).json()["job"]
        assert (tmp_path / cliente.conta.id / job / "arte.png").is_file()


class TestAcompanhar:
    def test_trabalho_que_nao_existe_devolve_404(self, cliente):
        assert cliente.get("/jobs/nunca-existiu").status_code == 404

    def test_mostra_estado_e_entregas(self, cliente):
        job = enviar(cliente).json()["job"]
        d = cliente.get(f"/jobs/{job}").json()
        assert d["job"] == job
        assert d["formatos"] == ["gdn-300x250"]
        assert "entregas" in d


class TestBaixar:
    def test_arquivo_que_nao_existe_devolve_404(self, cliente):
        job = enviar(cliente).json()["job"]
        assert cliente.get(f"/jobs/{job}/arquivos/nao-existe.png").status_code == 404

    def test_nao_deixa_sair_da_pasta_do_trabalho(self, cliente):
        """Sem isto, `../` no nome serviria qualquer arquivo da máquina."""
        job = enviar(cliente).json()["job"]
        r = cliente.get(f"/jobs/{job}/arquivos/../../etc/passwd")
        assert r.status_code in (400, 404)

    def test_identificador_com_travessia_e_barrado(self, cliente):
        r = cliente.get("/jobs/..%2F..%2Fetc")
        assert r.status_code in (400, 404)

    def test_entrega_a_arte_que_foi_subida(self, cliente):
        job = enviar(cliente).json()["job"]
        r = cliente.get(f"/jobs/{job}/arquivos/arte.png")
        assert r.status_code == 200
        assert r.content[:4] == b"\x89PNG"


class TestOQueVaiParaAFila:
    def test_enfileira_o_trabalho_com_o_que_foi_pedido(self, cliente):
        job = enviar(cliente, formatos="ig-stories,gdn-300x250",
                     headline="Chegamos", cta="Vem").json()["job"]
        assert len(cliente.fila.pedidos) == 1
        nome, args = cliente.fila.pedidos[0]
        assert nome == "processar"
        assert args[0] == cliente.conta.id      # de quem é o trabalho vem primeiro
        assert args[1] == job
        assert args[3] == ["ig-stories", "gdn-300x250"]
        assert args[4] == "Chegamos" and args[5] == "Vem"

    def test_pedido_recusado_nao_enfileira_nada(self, cliente):
        enviar(cliente, formatos="nao-existe")
        assert cliente.fila.pedidos == []


@pytest.mark.lento
class TestDePontaAPonta:
    """Uma vez só, com a fila de verdade: sobe, processa e baixa a peça.

    Entra com credencial, como qualquer cliente entra. Escrito antes de a
    plataforma ter contas, este teste postava sem nenhuma — levava 401 desde
    então, e só a esteira rodava os lentos para perceber.
    """

    def test_sobe_processa_e_entrega(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.setenv("REPLICAI_SEGREDO", "segredo-de-teste")
        monkeypatch.delenv("REDIS_URL", raising=False)
        import importlib
        from api import contas, main, trabalhos
        importlib.reload(trabalhos)
        importlib.reload(main)
        conta = assinatura_valendo(
            contas.criar("Ponta a ponta", "ponta@exemplo.com", "senha-bem-comprida"))
        chave = contas.nova_chave(conta, "ponta a ponta")
        c = TestClient(main.app, headers={"Authorization": f"Bearer {chave}"})
        job = c.post("/jobs", files={"arte": ("arte.png", arte_png(), "image/png")},
                     data={"formatos": "gdn-300x250", "headline": "Chegamos a Porto Belo"}
                     ).json()["job"]
        # sem Redis a plataforma roda num FIO, e não dentro da requisição: a
        # resposta sai na hora e o trabalho continua. É o que dá à tela o
        # intervalo em que existe progresso para mostrar — e aqui obriga a
        # esperar, como quem está olhando a tela espera
        import time
        for _ in range(600):
            estado = c.get(f"/jobs/{job}").json()
            if estado["status"] in ("pronto", "parcial", "erro"):
                break
            time.sleep(0.1)
        assert estado["status"] == "pronto", estado
        assert "gdn-300x250" in estado["prontas"]
        nome = next(e["nome"] for e in estado["entregas"] if e["nome"].endswith(".png")
                    and e["nome"] != "arte.png")
        r = c.get(f"/jobs/{job}/arquivos/{nome}")
        assert r.status_code == 200 and r.content[:4] == b"\x89PNG"


class TestBaixarTudo:
    def test_trabalho_sem_entregas_avisa(self, cliente):
        job = enviar(cliente).json()["job"]
        # a fila é espiã: nada foi processado, mas a arte subiu
        r = cliente.get(f"/jobs/{job}/zip")
        assert r.status_code == 200          # a arte já é uma entrega
        assert r.headers["content-type"] == "application/zip"

    def test_trabalho_que_nao_existe(self, cliente):
        assert cliente.get("/jobs/nao-existe/zip").status_code == 404

    def test_o_zip_leva_as_entregas(self, cliente):
        import io as _io, zipfile as _zip
        job = enviar(cliente).json()["job"]
        r = cliente.get(f"/jobs/{job}/zip")
        nomes = _zip.ZipFile(_io.BytesIO(r.content)).namelist()
        assert "arte.png" in nomes


class TestQuemCompoe:
    def test_sem_credencial_usa_so_a_regra(self, cliente, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        from api.tarefas import compositor
        assert type(compositor("arte.png", "Oi", "", "novo")).__name__ == "CompositorSimples"

    def test_quem_nao_pediu_texto_novo_nao_recebe_texto_nenhum(self, cliente, monkeypatch):
        """Os dois modos conservadores não escrevem — nem com credencial.

        Foi assim que o Stories real saiu com a chamada e o CTA duplicados por
        cima do lettering que a arte já trazia: ninguém tinha pedido texto."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
        from api.tarefas import compositor
        for modo in ("sem", "com"):
            c = compositor("arte.png", "Oi", "Clique", modo)
            assert type(c).__name__ == "CompositorPreserva"
            assert c.preserva is True

    def test_com_credencial_o_modelo_vem_primeiro_e_a_regra_atras(self, cliente, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
        from api.tarefas import compositor
        c = compositor("arte.png", "Oi", "", "novo")
        assert type(c).__name__ == "CompositorEmCadeia"
        assert [type(x).__name__ for x in c.compositores] == ["CompositorModelo", "CompositorSimples"]

    def test_a_saude_diz_quem_esta_compondo(self, cliente, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        assert cliente.get("/saude").json()["compositor"] == "regra"


class TestComOQueDesenha:
    """Duas máquinas com Chromium diferente entregam tipografia diferente, sem
    erro para avisar. A saúde precisa dizer com o que está desenhando."""

    def test_fora_do_conteiner_diz_qual_navegador_achou(self, cliente, monkeypatch):
        from api import main
        monkeypatch.setattr(main, "VERSOES", main.Path("/nao-existe.json"))
        d = cliente.get("/saude").json()["desenhando_com"]
        assert d["chromium"] == "fora de contêiner"
        assert "navegador" in d

    def test_dentro_do_conteiner_le_as_versoes_gravadas(self, cliente, tmp_path, monkeypatch):
        from api import main
        f = tmp_path / "versoes.json"
        f.write_text('{"chromium":"154.0.8037.92-1~deb13u1","fontes_dejavu":"2.37-8"}')
        monkeypatch.setattr(main, "VERSOES", f)
        d = cliente.get("/saude").json()["desenhando_com"]
        assert d["chromium"].startswith("154.")

    def test_arquivo_corrompido_nao_derruba_a_saude(self, cliente, tmp_path, monkeypatch):
        from api import main
        f = tmp_path / "versoes.json"
        f.write_text("isto não é json")
        monkeypatch.setattr(main, "VERSOES", f)
        assert cliente.get("/saude").status_code == 200

    def test_a_saude_diz_quando_o_preco_ficou_abaixo_do_custo(self, cliente, monkeypatch):
        """Câmbio sobe, preço fica, margem some calada. O preço não se corrige
        sozinho — mas tem que dar para ver sem abrir planilha."""
        from api import precos
        assert cliente.get("/saude").json()["precos"] == "valendo"
        monkeypatch.setattr(precos, "DOLAR", precos.DOLAR * 5)
        assert "abaixo do piso" in cliente.get("/saude").json()["precos"]


class TestPranchetasNaResposta:
    def test_a_lista_traz_onde_cada_prancheta_fica(self, cliente, monkeypatch):
        """A tela recorta a miniatura do PSD por prancheta: sem x e y, a
        escolha vira adivinhar entre "Prancheta 1" e "Prancheta 7"."""
        from api import main, psd
        monkeypatch.setattr(psd, "pranchetas", lambda a: [
            psd.Prancheta("Prancheta 1", 0, 0, 1920, 1080),
            psd.Prancheta("Prancheta 4", 4040, 0, 1920, 1080)])
        r = cliente.post("/jobs", files={"arte": ("a.psd", b"8BPS" + b"\0" * 60,
                                                  "application/octet-stream")},
                         data={"formatos": "ig-feed-1x1", "headline": "Oi"})
        assert r.status_code == 200
        lista = r.json()["pranchetas"]
        assert lista[1] == {"nome": "Prancheta 4", "x": 4040, "y": 0,
                            "w": 1920, "h": 1080}


class TestRespostaDaEscolha:
    def _mandar(self, cliente, monkeypatch):
        from api import psd
        monkeypatch.setattr(psd, "pranchetas", lambda a: [
            psd.Prancheta("Prancheta 1", 0, 0, 1920, 1080),
            psd.Prancheta("Prancheta 4", 4040, 0, 1920, 1080)])
        return cliente.post("/jobs", files={"arte": ("a.psd", b"8BPS" + b"\0" * 60,
                                                     "application/octet-stream")},
                            data={"formatos": "ig-feed-1x1", "headline": "Oi"})

    def test_esperar_escolha_nao_e_aceito(self, cliente, monkeypatch):
        """202 diz "entrou na fila". Esperando escolha, nenhuma peça entrou."""
        r = self._mandar(cliente, monkeypatch)
        assert r.status_code == 200
        assert [n for n, _ in cliente.fila.pedidos if n == "processar"] == []

    def test_a_previa_de_cada_prancheta_e_pedida(self, cliente, monkeypatch):
        """A miniatura embutida no PSD tem 256 px para o documento inteiro:
        recortada numa prancheta, não dá para reconhecer qual peça é. A prévia
        composta vai para a fila para a lista não ficar esperando por ela."""
        self._mandar(cliente, monkeypatch)
        assert [n for n, _ in cliente.fila.pedidos] == ["previas"]


class TestMinhasMedidas:
    """A medida fora do catálogo fica guardada na conta. O motor resolve
    qualquer `livre-LARGxALT` sozinho — o que está em jogo aqui é só o atalho,
    e que ele seja de quem pediu."""

    def test_guardar_e_listar(self, cliente):
        r = cliente.post("/eu/medidas", data={"largura": 1200, "altura": 1600})
        assert r.status_code == 201
        assert cliente.get("/eu/medidas").json()["medidas"][0]["id"] == "livre-1200x1600"

    def test_a_medida_guardada_serve_como_formato(self, cliente):
        """De nada adianta lembrar a medida se ela não puder ser pedida."""
        cliente.post("/eu/medidas", data={"largura": 1200, "altura": 1600})
        assert enviar(cliente, formatos="livre-1200x1600", modo="sem").status_code == 202

    def test_medida_impossivel_volta_com_o_motivo(self, cliente):
        r = cliente.post("/eu/medidas", data={"largura": 10, "altura": 10})
        assert r.status_code == 400
        assert "pixels" in r.json()["detail"]

    def test_esquecer(self, cliente):
        cliente.post("/eu/medidas", data={"largura": 1200, "altura": 1600})
        assert cliente.delete("/eu/medidas/livre-1200x1600").json()["medidas"] == []

    def test_sem_conta_nao_lista_nem_guarda(self, anonimo):
        assert anonimo.get("/eu/medidas").status_code == 401
        assert anonimo.post("/eu/medidas", data={"largura": 100, "altura": 100}).status_code == 401


class TestTrocarOTextoDaPeca:
    """A linha da arte chega como uma imagem POR LETRA: "a Porto Belo!" são
    onze PNGs recortados do PSD. Trocar a cidade não é editar PNG — é desenhar
    a frase nova no lugar da linha inteira. O `src` continua fora do que a tela
    pode mandar: quem decide o arquivo é o servidor."""

    def _peca_de_letras(self, cliente, tmp_path):
        import json

        from PIL import Image
        pasta = tmp_path / cliente.conta.id / "trab" / "pecas"
        pasta.mkdir(parents=True)
        for n, cor in ((0, (255, 255, 255, 255)), (1, (1, 78, 163, 255)),
                       (2, (1, 78, 163, 255))):
            # a segunda e a terceira são maiores: é delas a cor da linha
            tam = (6, 10) if n == 0 else (40, 30)
            Image.new("RGBA", tam, cor).save(pasta.parent / f"l{n}.png")
        (pasta / "ig-feed-1x1.json").write_text(json.dumps({
            "formato": "ig-feed-1x1", "canvas": {"w": 1080, "h": 1080},
            "fundo": {"tipo": "cor", "cor": "#000"}, "via": "psd-reenquadra",
            "elementos": [
                {"tipo": "imagem", "papel": "headline", "camada": "a Porto Belo!",
                 "src": f"l{n}.png", "de": "a Porto Belo!",
                 "box": {"x": 10 + n * 50, "y": 100, "w": 40, "h": 60}}
                for n in range(3)],
        }, ensure_ascii=False))
        from api import trabalhos
        trabalhos.gravar(cliente.conta.id, "trab", {"status": "pronto",
                                                    "prontas": ["ig-feed-1x1"]})
        return pasta / "ig-feed-1x1.json"

    def _trocar(self, cliente, tmp_path, texto="a São Paulo!"):
        import json
        arq = self._peca_de_letras(cliente, tmp_path)
        r = cliente.post("/jobs/trab/pecas/ig-feed-1x1", json={"elementos": [
            {"i": 0, "box": {"x": 10, "y": 100, "w": 150, "h": 60},
             "texto": texto, "tipografar": True}]})
        return r, json.loads(arq.read_text())

    def test_a_linha_inteira_vira_um_texto_so(self, cliente, tmp_path):
        r, peca = self._trocar(cliente, tmp_path)
        assert r.status_code == 202
        assert len(peca["elementos"]) == 1
        assert peca["elementos"][0]["tipo"] == "texto"
        assert peca["elementos"][0]["texto"] == "a São Paulo!"

    def test_herda_a_cor_da_letra_de_mais_tinta(self, cliente, tmp_path):
        """Não é a média: em "A PORTO BELO!" o A é branco e o resto azul, e a
        média dá um azul lavado que não existe na peça."""
        _, peca = self._trocar(cliente, tmp_path)
        assert peca["elementos"][0]["cor"] == "#014EA3"

    def test_declara_a_fonte_do_trabalho(self, cliente, tmp_path):
        """Sem fonte declarada o navegador cai na letra do sistema."""
        _, peca = self._trocar(cliente, tmp_path)
        assert peca["fontes"] and peca["fontes"][0]["familia"] == "PecaSans"

    def test_a_tela_nao_escolhe_arquivo_nenhum(self, cliente, tmp_path):
        """`src` fora da lista do que a tela pode mexer: um pedido forjado
        faria o motor desenhar — e devolver no PNG — qualquer arquivo."""
        import json
        self._peca_de_letras(cliente, tmp_path)
        r = cliente.post("/jobs/trab/pecas/ig-feed-1x1", json={"elementos": [
            {"i": 0, "box": {"x": 0, "y": 0, "w": 10, "h": 10},
             "src": "../../../etc/passwd"}]})
        assert r.status_code == 202
        from api import trabalhos
        peca = json.loads((trabalhos.pasta_do(cliente.conta.id, "trab")
                           / "pecas" / "ig-feed-1x1.json").read_text())
        assert peca["elementos"][0]["src"] == "l0.png"

    def test_a_peca_fica_marcada_como_remontada_a_mao(self, cliente, tmp_path):
        """É a marca que faz a exportação final devolver esta montagem em vez
        de recompor por cima dela."""
        _, peca = self._trocar(cliente, tmp_path)
        assert "+mao" in peca["via"]


class TestATrocaPreservaAFonte:
    """"Ao trocar o texto, preciso preservar a fonte: a usada para escrever
    São Paulo tem que ser igual à de Porto Belo."

    O PSD diz qual fonte a linha usa e não leva o arquivo dentro. Com a fonte
    guardada na conta, a troca sai na MESMA letra; sem ela, sai na letra da
    casa — e isso tem que ser dito, porque família declarada sem arquivo faz o
    navegador cair numa fonte do sistema sem avisar.
    """

    def _peca(self, cliente, tmp_path, fonte_mae="FuturaICG-Bold"):
        import json

        from PIL import Image
        pasta = tmp_path / cliente.conta.id / "trab" / "pecas"
        pasta.mkdir(parents=True)
        Image.new("RGBA", (40, 30), (1, 78, 163, 255)).save(pasta.parent / "l0.png")
        (pasta / "ig-feed-1x1.json").write_text(json.dumps({
            "formato": "ig-feed-1x1", "canvas": {"w": 1080, "h": 1080},
            "fundo": {"tipo": "cor", "cor": "#000"}, "via": "psd-reenquadra",
            "elementos": [{"tipo": "imagem", "papel": "headline",
                           "camada": "a Porto Belo!", "src": "l0.png",
                           "fonte_mae": fonte_mae, "de": "a Porto Belo!",
                           "box": {"x": 10, "y": 100, "w": 150, "h": 60}}],
        }, ensure_ascii=False))
        from api import trabalhos
        trabalhos.gravar(cliente.conta.id, "trab", {"status": "pronto"})
        return pasta / "ig-feed-1x1.json"

    def _trocar(self, cliente, arq):
        import json
        r = cliente.post("/jobs/trab/pecas/ig-feed-1x1", json={"elementos": [
            {"i": 0, "box": {"x": 10, "y": 100, "w": 150, "h": 60},
             "texto": "a São Paulo!", "tipografar": True}]})
        return r, json.loads(arq.read_text())

    def _enviar_fonte(self, cliente, nome="FuturaICG-Bold"):
        """Guarda a fonte do projeto na conta e devolve como o PSD a pediria."""
        from pathlib import Path

        from api import contas
        item = contas.guardar_fonte(cliente.conta, "f.ttf",
                                    Path("motor/assets/fontes/grotesk.ttf").read_bytes())
        return f"{item['familia'].replace(' ', '')}-{item['estilo']}", item

    def test_sem_a_fonte_avisa_qual_esta_faltando(self, cliente, tmp_path):
        arq = self._peca(cliente, tmp_path)
        r, peca = self._trocar(cliente, arq)
        avisos = " ".join(r.json()["avisos"])
        assert "FuturaICG-Bold" in avisos
        assert peca["elementos"][0]["fonte"] == "PecaSans"

    def test_com_a_fonte_na_conta_a_letra_e_a_mesma(self, cliente, tmp_path):
        pedida, item = self._enviar_fonte(cliente)
        arq = self._peca(cliente, tmp_path, fonte_mae=pedida)
        r, peca = self._trocar(cliente, arq)
        assert r.json()["avisos"] == []
        assert peca["elementos"][0]["fonte"] == pedida

    def test_a_fonte_vai_declarada_COM_arquivo(self, cliente, tmp_path):
        """Declarar a família sem o arquivo é o erro que a peça não denuncia:
        o Chrome cai numa fonte do sistema e a tipografia troca calada."""
        pedida, item = self._enviar_fonte(cliente)
        arq = self._peca(cliente, tmp_path, fonte_mae=pedida)
        _, peca = self._trocar(cliente, arq)
        declarada = next(f for f in peca["fontes"] if f["familia"] == pedida)
        assert declarada["arquivo"] == item["nome"]
        from api import trabalhos
        assert (trabalhos.pasta_do(cliente.conta.id, "trab") / item["nome"]).exists()

    def test_linha_sem_fonte_declarada_no_psd_usa_a_da_casa(self, cliente, tmp_path):
        arq = self._peca(cliente, tmp_path, fonte_mae="")
        r, peca = self._trocar(cliente, arq)
        assert r.json()["avisos"] == []
        assert peca["elementos"][0]["fonte"] == "PecaSans"

    def test_o_aviso_da_fonte_cola_na_peca(self, cliente, tmp_path):
        """Ele aparecia uma vez, como recado que some sozinho, e a peça ia
        para a exportação sem nada dizendo que aquela linha mudou de letra.
        Agora ele fica com a peça, como qualquer outra ressalva."""
        arq = self._peca(cliente, tmp_path)
        self._trocar(cliente, arq)
        avisos = cliente.get("/jobs/trab").json()["avisos"]["ig-feed-1x1"]
        assert any("FuturaICG-Bold" in a for a in avisos)

    def test_com_a_fonte_na_conta_a_peca_nao_ganha_ressalva(self, cliente, tmp_path):
        pedida, _ = self._enviar_fonte(cliente)
        arq = self._peca(cliente, tmp_path, fonte_mae=pedida)
        self._trocar(cliente, arq)
        assert not (cliente.get("/jobs/trab").json().get("avisos") or {}).get("ig-feed-1x1")


class TestRefazerOFundoDeUmaPeca:
    """A ressalva do fundo dizia "vale rodar de novo" e a única saída era
    "Refazer fundos", que mexe no trabalho inteiro e só existe no rodapé.
    Quem viu o problema está olhando UMA peça — e quando a saída resolve, a
    ressalva tem que sumir."""

    def _pronto(self, cliente, tmp_path, avisos=None):
        from api import trabalhos
        pasta = trabalhos.pasta_do(cliente.conta.id, "trab")
        (pasta / "pecas").mkdir(parents=True, exist_ok=True)
        (pasta / "arte.psd").write_bytes(b"8BPS")
        trabalhos.gravar(cliente.conta.id, "trab", {
            "status": "pronto", "arte": "arte.psd", "formatos": ["ig-feed-1x1"],
            "prontas": ["ig-feed-1x1"],
            "avisos": avisos if avisos is not None else {"ig-feed-1x1": ["a continuação do fundo inventou traço"]}})

    def test_pede_o_fundo_so_daquele_formato(self, cliente, tmp_path):
        self._pronto(cliente, tmp_path)
        r = cliente.post("/jobs/trab/pecas/ig-feed-1x1/fundo")
        assert r.status_code == 202
        assert [n for n, _ in cliente.fila.pedidos] == ["refazer_fundo"]

    def test_formato_que_nao_saiu_nao_tem_fundo_a_refazer(self, cliente, tmp_path):
        self._pronto(cliente, tmp_path)
        assert cliente.post("/jobs/trab/pecas/ig-stories/fundo").status_code == 409

    def test_trabalho_arquivado_diz_por_que_nao_da(self, cliente, tmp_path):
        from api import trabalhos
        self._pronto(cliente, tmp_path)
        trabalhos.gravar(cliente.conta.id, "trab", {"arquivado": {"quando": "x"}})
        r = cliente.post("/jobs/trab/pecas/ig-feed-1x1/fundo")
        assert r.status_code == 409 and "arte" in r.json()["detail"]

    def test_sem_conta_ninguem_refaz_fundo_dos_outros(self, cliente, tmp_path, anonimo):
        self._pronto(cliente, tmp_path)
        assert anonimo.post("/jobs/trab/pecas/ig-feed-1x1/fundo").status_code == 401


class TestTrabalhoQueParouDeDarSinal:
    """Sem fila de verdade o trabalho roda DENTRO da api: se o processo cai —
    um reinício —, o estado fica "rodando" para sempre e a tela diz
    "Replicando" com nada acontecendo. Aconteceu hoje, e levou um tempo até
    alguém entender que não era lentidão."""

    def _rodando(self, cliente, quando):
        from api import trabalhos
        trabalhos.gravar(cliente.conta.id, "trab", {"status": "rodando",
                                                    "progresso": {"etapa": "desenhando",
                                                                  "formato": "ig-stories"}})
        import json
        f = trabalhos.pasta_do(cliente.conta.id, "trab") / "trabalho.json"
        d = json.loads(f.read_text())
        d["atualizado"] = quando
        f.write_text(json.dumps(d))

    def test_silencio_longo_vira_erro_com_motivo(self, cliente):
        from datetime import datetime, timedelta, timezone
        self._rodando(cliente, (datetime.now(timezone.utc)
                                - timedelta(hours=2)).isoformat(timespec="seconds"))
        d = cliente.get("/jobs/trab").json()
        assert d["status"] == "erro"
        assert "parou de dar sinal" in d["erro"]
        assert "desenhando" in d["erro"] and "ig-stories" in d["erro"]

    def test_trabalho_recente_continua_rodando(self, cliente):
        """Render demorado não pode ser confundido com queda."""
        from datetime import datetime, timezone
        self._rodando(cliente, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        assert cliente.get("/jobs/trab").json()["status"] == "rodando"


class TestSemPlanoNaoEntra:
    """A conta existe porque alguém assinou um plano. Sem plano ativo não é
    "sem franquia": é sem sistema. Quem quer ver antes de assinar fala com a
    gente, e isso acontece fora daqui."""

    def _sem_plano(self, cliente, monkeypatch):
        from api import contas, uso
        monkeypatch.delenv("REPLICAI_SEM_LIMITE", raising=False)
        c = cliente.conta
        c.plano = uso.PLANO_PADRAO
        contas._gravar(c)

    def test_produzir_fecha(self, cliente, monkeypatch):
        self._sem_plano(cliente, monkeypatch)
        r = cliente.post("/jobs")
        assert r.status_code == 402
        assert "não tem plano ativo" in r.json()["detail"]

    def test_o_que_ja_e_dele_continua_baixavel(self, cliente, monkeypatch, tmp_path):
        """A peça foi paga quando foi feita; servir arquivo não custa por
        unidade. O que o pagamento abre é PRODUZIR."""
        from api import trabalhos
        trabalhos.gravar(cliente.conta.id, "antigo", {"status": "pronto",
                                                      "prontas": ["ig-feed-1x1"]})
        self._sem_plano(cliente, monkeypatch)
        assert cliente.get("/jobs/antigo").status_code == 200
        assert cliente.get("/jobs/antigo/zip").status_code in (200, 404)

    def test_a_recusa_convida_a_assinar_e_cita_a_demonstracao(self, cliente, monkeypatch):
        self._sem_plano(cliente, monkeypatch)
        texto = cliente.post("/jobs").json()["detail"]
        assert "Assine um plano" in texto and "demonstração" in texto

    def test_a_propria_conta_continua_respondendo(self, cliente, monkeypatch):
        """Senão a pessoa não consegue nem ver por que está trancada, nem
        escolher um plano, nem sair."""
        self._sem_plano(cliente, monkeypatch)
        for caminho in ("/eu", "/eu/uso", "/planos", "/saude"):
            assert cliente.get(caminho).status_code == 200, caminho

    def test_endereco_novo_nasce_protegido(self):
        """O padrão é exigir plano, e abrir exceção é ato deliberado de quem
        escreve o endereço: proteger um a um deixa passar o que se esquece.
        As exceções são poucas e todas de LEITURA ou de conta."""
        import inspect

        from api import main
        fonte = inspect.getsource(main)
        assert "def conta_atual(c: contas.Conta = Depends(quem_e))" in fonte
        livres = [l for l in fonte.splitlines() if "Depends(quem_e)" in l]
        assert len(livres) <= 14, livres
        # nenhum POST de produção entre as exceções
        for proibido in ("def criar(", "def ajustar_peca(", "def animar(",
                         "def refazer_o_fundo(", "def finalizar("):
            dentro = fonte.split(proibido)[1].split(")")[0] if proibido in fonte else ""
            assert "quem_e" not in dentro, proibido

    def test_a_instalacao_de_teste_nao_tranca_ninguem(self, cliente, monkeypatch):
        monkeypatch.setenv("REPLICAI_SEM_LIMITE", "1")
        from api import contas, uso
        c = cliente.conta
        c.plano = uso.PLANO_PADRAO
        contas._gravar(c)
        assert cliente.get("/jobs").status_code == 200


class TestAPortaFalaComQuemNaoTemConta:
    """Antes de entrar não há conta, então o que a porta mostra tem que vir de
    um endereço aberto. E não pode inventar domínio: até existir, vazio."""

    def test_responde_sem_credencial(self, anonimo):
        r = anonimo.get("/porta")
        assert r.status_code == 200
        assert set(r.json()) == {"site_planos", "contato_demo"}

    def test_sem_dominio_nao_promete_pagina_de_planos(self, anonimo):
        d = anonimo.get("/porta").json()
        # sem domínio a página de planos fica vazia; o contato de demonstração
        # já existe e é o mesmo da landing
        assert d["site_planos"] == ""
        assert d["contato_demo"] == "contato@operandi.com.br"

    def test_configurado_e_o_que_a_porta_diz(self, anonimo, monkeypatch):
        from api import main
        monkeypatch.setattr(main, "SITE_PLANOS", "https://exemplo.teste/#precos")
        monkeypatch.setattr(main, "CONTATO_DEMO", "oi@exemplo.teste")
        assert anonimo.get("/porta").json() == {
            "site_planos": "https://exemplo.teste/#precos",
            "contato_demo": "oi@exemplo.teste"}

    def test_os_dois_vem_do_ambiente(self):
        """Trocar o endereço é configuração do servidor, não edição de código."""
        from pathlib import Path
        fonte = Path("api/main.py").read_text(encoding="utf-8")
        assert 'os.environ.get("REPLICAI_SITE_PLANOS"' in fonte
        assert 'os.environ.get("REPLICAI_CONTATO_DEMO"' in fonte
