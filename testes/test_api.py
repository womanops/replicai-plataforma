"""Os endpoints: subir a arte, acompanhar, baixar.

A API não renderiza — ela recebe, guarda, enfileira e responde. O que se testa
aqui é isso, e principalmente o que ela faz com entrada torta: formato que não
existe, arquivo que não serve, identificador que tenta sair da pasta.
"""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image


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
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.delenv("REDIS_URL", raising=False)
    import importlib
    from api import main
    importlib.reload(main)
    main.FILA = FilaEspia()
    c = TestClient(main.app)
    c.fila = main.FILA
    return c


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

    def test_recusa_pedido_sem_formato(self, cliente):
        r = enviar(cliente, formatos="  ")
        assert r.status_code == 422

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
        job = enviar(cliente).json()["job"]
        assert (tmp_path / job / "arte.png").is_file()


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
        assert args[0] == job
        assert args[2] == ["ig-stories", "gdn-300x250"]
        assert args[3] == "Chegamos" and args[4] == "Vem"

    def test_pedido_recusado_nao_enfileira_nada(self, cliente):
        enviar(cliente, formatos="nao-existe")
        assert cliente.fila.pedidos == []


@pytest.mark.lento
class TestDePontaAPonta:
    """Uma vez só, com a fila de verdade: sobe, processa e baixa a peça."""

    def test_sobe_processa_e_entrega(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.delenv("REDIS_URL", raising=False)
        import importlib
        from api import main
        importlib.reload(main)
        c = TestClient(main.app)
        job = c.post("/jobs", files={"arte": ("arte.png", arte_png(), "image/png")},
                     data={"formatos": "gdn-300x250", "headline": "Chegamos a Porto Belo"}
                     ).json()["job"]
        estado = c.get(f"/jobs/{job}").json()
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
        from api.main import compositor
        assert type(compositor("arte.png", "Oi", "")).__name__ == "CompositorSimples"

    def test_com_credencial_o_modelo_vem_primeiro_e_a_regra_atras(self, cliente, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
        from api.main import compositor
        c = compositor("arte.png", "Oi", "")
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
