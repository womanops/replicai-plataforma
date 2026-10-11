"""O PDF que se manda para o cliente aprovar.

Mandar oito PNGs soltos obriga quem recebe a abrir oito arquivos e adivinhar
qual é qual. O Studio já entregava uma apresentação; a plataforma tinha
perdido isso.
"""
import json
from pathlib import Path

import pytest
from PIL import Image


def peca_png(caminho, w, h, cor=(20, 90, 200)):
    Image.new("RGB", (w, h), cor).save(caminho)


@pytest.fixture
def trabalho(tmp_path):
    peca_png(tmp_path / "arte-mae.png", 1200, 1200)
    peca_png(tmp_path / "fundo.png", 1200, 1200, (0, 0, 0))
    peca_png(tmp_path / "ig-stories.png", 1080, 1920)
    peca_png(tmp_path / "gdn-300x250.png", 300, 250)
    return tmp_path, {"titulo": "Consigaz Porto Belo", "arte": "arte.psd",
                      "prontas": ["gdn-300x250", "ig-stories"]}


class TestQualPecaEhAOriginal:
    def test_prefere_a_prancheta_inteira_ao_fundo_assado(self, trabalho):
        """`fundo.png` tem as camadas de texto desligadas: a página "Peça
        original" saía sem a chamada."""
        from api.apresentacao import _capa_da_mae
        pasta, estado = trabalho
        assert _capa_da_mae(pasta, estado).name == "arte-mae.png"

    def test_imagem_achatada_e_ela_mesma(self, tmp_path):
        from api.apresentacao import _capa_da_mae
        peca_png(tmp_path / "arte.png", 800, 800)
        assert _capa_da_mae(tmp_path, {"arte": "arte.png"}).name == "arte.png"

    def test_sem_nada_nao_inventa_capa(self, tmp_path):
        from api.apresentacao import _capa_da_mae
        assert _capa_da_mae(tmp_path, {"arte": "arte.psd"}) is None


class TestOTamanhoNaFolha:
    def test_banner_pequeno_e_ampliado(self):
        """300×250 no meio de uma folha de 1600px parecia defeito."""
        from api.apresentacao import _escala
        assert "width:900px" in _escala(300, 250)

    def test_nao_amplia_alem_do_que_aguenta(self):
        from api.apresentacao import _escala, AMPLIA_ATE
        largura = int(_escala(100, 100).split("width:")[1].split("px")[0])
        assert largura == 100 * AMPLIA_ATE

    def test_peca_grande_o_css_reduz(self):
        from api.apresentacao import _escala
        assert _escala(1080, 1920) == ""


class TestOPdf:
    def test_monta_a_apresentacao_inteira(self, trabalho):
        from api.apresentacao import montar
        pasta, estado = trabalho
        pdf = montar(pasta, estado)
        assert pdf.exists() and pdf.stat().st_size > 10_000
        folha = (pasta / "apresentacao.html").read_text(encoding="utf-8")
        assert folha.count("<section") == 4        # capa + mãe + duas peças
        assert "Consigaz Porto Belo" in folha
        assert "Stories / Reels 9:16" in folha

    def test_sem_peca_pronta_nao_monta(self, tmp_path):
        from api.apresentacao import montar
        with pytest.raises(ValueError):
            montar(tmp_path, {"prontas": []})


class TestAEsteiraMontaEEntrega:
    def test_o_trabalho_monta_a_apresentacao_no_fim(self):
        import inspect

        from api import tarefas
        assert "_apresentar" in inspect.getsource(tarefas.processar)

    def test_o_ajuste_a_mao_refaz_o_pdf(self):
        """Sem isso o PDF mostra a peça de antes do ajuste, e é esse PDF que
        vai para o cliente."""
        import inspect

        from api import tarefas
        assert "_apresentar" in inspect.getsource(tarefas.redesenhar)

    def test_o_pdf_vai_no_pacote(self):
        from api.main import para_entregar
        itens = [{"nome": "ig-stories.png"}, {"nome": "apresentacao.pdf"},
                 {"nome": "apresentacao.html"}, {"nome": "arte.psd"}]
        fica = {i["nome"] for i in para_entregar({"prontas": ["ig-stories"]}, itens)}
        assert fica == {"ig-stories.png", "apresentacao.pdf"}

    def test_pdf_que_nao_sai_vira_aviso_e_nao_derruba_a_entrega(self, tmp_path, monkeypatch):
        from api import tarefas, trabalhos
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        import importlib
        importlib.reload(trabalhos)
        monkeypatch.setattr(tarefas, "trabalhos", trabalhos)
        trabalhos.gravar("conta-de-teste", "job-de-teste", {"titulo": "x"})
        from api import apresentacao
        monkeypatch.setattr(apresentacao, "montar",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Chrome travou")))
        aviso = tarefas._apresentar("conta-de-teste", "job-de-teste", ["ig-stories"])
        assert "Chrome travou" in aviso
