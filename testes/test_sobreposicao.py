"""A regra de sobreposição, e o ponto onde a esteira a chama.

Decisão da casa, de 09/10/2026: nunca encostar por erro, só se a arte-mãe já
fizer assim. A régua custou três tentativas erradas e ficou implementada no
motor — e a plataforma nunca a chamava. Os testes do ponto de chamada existem
por isso: regra escrita e não chamada já passou duas vezes aqui (o lettering
fantasma e esta).
"""
import json
from pathlib import Path

import pytest
from PIL import Image


def recorte(caminho, w, h, cor=(0, 0, 0, 255)):
    Image.new("RGBA", (w, h), cor).save(caminho)


def fundo_liso(caminho, w=600, h=600):
    Image.new("RGB", (w, h), (20, 90, 200)).save(caminho)


def fundo_agitado(caminho, w=600, h=600):
    """Listras finas: é o que o desenho de uma foto faz com o desvio padrão."""
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (250, 250, 250) if (x // 3) % 2 else (10, 10, 10)
    im.save(caminho)


class TestUmCobrindoOOutro:
    def _peca(self, pasta, caixa_do_recorte):
        recorte(pasta / "mascote.png", 200, 200)
        fundo_liso(pasta / "fundo.png")
        return {
            "formato": "x", "fundo": {"tipo": "imagem", "src": "fundo.png"},
            "elementos": [
                {"tipo": "texto", "papel": "cta", "texto": "Candidate-se",
                 "box": {"x": 100, "y": 300, "w": 300, "h": 60}},
                {"tipo": "imagem", "papel": "mascote", "src": "mascote.png",
                 "box": caixa_do_recorte},
            ],
        }

    def test_recorte_por_cima_do_texto_e_acusado(self, tmp_path):
        from api.sobreposicao import conferir
        peca = self._peca(tmp_path, {"x": 250, "y": 250, "w": 200, "h": 200})
        avisos = conferir(peca, tmp_path)
        assert avisos and "cobre" in avisos[0]

    def test_recorte_ao_lado_do_texto_passa(self, tmp_path):
        from api.sobreposicao import conferir
        peca = self._peca(tmp_path, {"x": 420, "y": 250, "w": 150, "h": 200})
        assert conferir(peca, tmp_path) == []

    def test_encosto_de_borda_nao_conta(self, tmp_path):
        """Dois por cento é encosto, não sobreposição: sem o piso a entrega
        vira um muro de avisos por um pixel de folga."""
        from api.sobreposicao import conferir
        peca = self._peca(tmp_path, {"x": 396, "y": 250, "w": 150, "h": 200})
        assert conferir(peca, tmp_path) == []

    def test_o_que_veio_da_arte_mae_nao_e_discutido(self, tmp_path):
        """No KV da Consigaz o braço do mascote cobre o fim do CANDIDATE-SE de
        propósito. Elemento com `camada` saiu do PSD: é decisão de quem
        desenhou a peça."""
        from api.sobreposicao import conferir
        peca = self._peca(tmp_path, {"x": 250, "y": 250, "w": 200, "h": 200})
        peca["elementos"][0] = {"tipo": "imagem", "papel": "cta",
                                "camada": "CANDIDATE-SE", "src": "letra.png",
                                "box": {"x": 100, "y": 300, "w": 300, "h": 60}}
        recorte(tmp_path / "letra.png", 300, 60)
        # o recorte ainda cobre, mas quem está embaixo veio da mãe: só o que
        # está POR CIMA é cobrado, e isso a mãe já fazia
        avisos = conferir(peca, tmp_path)
        assert all("fica debaixo" not in a for a in avisos)


class TestTextoSobreODesenho:
    def test_chamada_em_cima_do_desenho_e_acusada(self, tmp_path):
        """O caso que a Ligia cobrou: o braço do mascote por trás da chamada.
        Ele não é elemento nenhum, vem assado no fundo — comparar elemento com
        elemento nunca o acharia."""
        from api.sobreposicao import conferir
        fundo_agitado(tmp_path / "fundo.png")
        peca = {"formato": "x", "fundo": {"tipo": "imagem", "src": "fundo.png"},
                "elementos": [{"tipo": "texto", "papel": "headline",
                               "texto": "Chegamos a Porto Belo",
                               "box": {"x": 50, "y": 200, "w": 500, "h": 80}}]}
        avisos = conferir(peca, tmp_path)
        assert avisos and "não se lê" in avisos[0]

    def test_sobre_fundo_liso_passa(self, tmp_path):
        from api.sobreposicao import conferir
        fundo_liso(tmp_path / "fundo.png")
        peca = {"formato": "x", "fundo": {"tipo": "imagem", "src": "fundo.png"},
                "elementos": [{"tipo": "texto", "papel": "headline", "texto": "Oi",
                               "box": {"x": 50, "y": 200, "w": 500, "h": 80}}]}
        assert conferir(peca, tmp_path) == []

    def test_texto_que_veio_da_mae_nao_e_discutido(self, tmp_path):
        """Se a arte-mãe pôs a frase sobre a foto, é assim que ela é."""
        from api.sobreposicao import conferir
        fundo_agitado(tmp_path / "fundo.png")
        peca = {"formato": "x", "fundo": {"tipo": "imagem", "src": "fundo.png"},
                "elementos": [{"tipo": "texto", "papel": "headline", "camada": "Chegamos",
                               "texto": "Chegamos", "box": {"x": 50, "y": 200, "w": 500, "h": 80}}]}
        assert conferir(peca, tmp_path) == []


class TestAEsteiraChamaARegra:
    """Regra escrita e não chamada já passou duas vezes neste projeto. Estes
    testes são do ponto de chamada, não da função."""

    def test_o_caminho_da_imagem_achatada_chama(self, tmp_path, monkeypatch):
        from api import pipeline
        chamadas = []
        monkeypatch.setattr(pipeline.sobreposicao, "conferir",
                            lambda peca, pasta, *a, **k: chamadas.append(pasta) or [])
        fundo_liso(tmp_path / "base.png")
        pipeline.conferir_peca({"elementos": []}, tmp_path, tmp_path / "base.png")
        assert chamadas, "conferir_peca não chama a regra de sobreposição"

    def test_o_caminho_do_psd_chama(self):
        """O PSD não passa por `conferir_peca` — foi por aí que a peça com a
        chamada escrita em cima da foto saiu."""
        import inspect

        from api import pipeline
        fonte = inspect.getsource(pipeline._psd_e_render)
        assert "sobreposicao.conferir" in fonte

    def test_o_aviso_chega_na_entrega(self, tmp_path, monkeypatch):
        from api import pipeline
        monkeypatch.setattr(pipeline.sobreposicao, "conferir",
                            lambda *a, **k: ["encostou onde não devia"])
        fundo_liso(tmp_path / "base.png")
        avisos = pipeline.conferir_peca({"elementos": []}, tmp_path, tmp_path / "base.png")
        assert "encostou onde não devia" in avisos
