"""Cortar lettering de imagem em letras.

A camada de texto do PSD chega rasterizada: animar a imagem inteira entrando é
transição de slide, não motion. E com lettering desenhado não há como
retipografar — a fonte é da marca e quase nunca está na máquina.
"""
import numpy as np
import pytest
from PIL import Image, ImageDraw

from api.letras import fatiar, letras, linhas


def tela(blocos, w=300, h=100):
    """Imagem transparente com retângulos opacos nos lugares pedidos."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for x0, y0, x1, y1 in blocos:
        d.rectangle((x0, y0, x1, y1), fill=(255, 255, 255, 255))
    return im


def alfa_de(im):
    return np.asarray(im)[..., 3].astype("int32")


class TestLinhas:
    def test_uma_linha_so(self):
        assert linhas(alfa_de(tela([(10, 20, 290, 60)]))) == [(20, 61)]

    def test_tres_linhas_separadas(self):
        im = tela([(0, 0, 100, 20), (0, 40, 100, 60), (0, 80, 100, 99)])
        assert len(linhas(alfa_de(im))) == 3

    def test_imagem_vazia_nao_tem_linha(self):
        assert linhas(alfa_de(tela([]))) == []


class TestLetras:
    def test_separa_pelo_vazio_entre_elas(self):
        im = tela([(0, 10, 40, 90), (60, 10, 100, 90), (120, 10, 160, 90)])
        assert len(letras(alfa_de(im), 0, 100)) == 3

    def test_acento_vai_junto_da_letra(self):
        """Pingo do i e acento viram letra solta se cada bloco contar."""
        im = tela([(0, 40, 30, 90), (10, 10, 20, 20)])   # haste e pingo colados
        assert len(letras(alfa_de(im), 0, 100)) == 1

    def test_linha_sem_tinta_nao_tem_letra(self):
        assert letras(alfa_de(tela([(0, 0, 50, 10)])), 50, 90) == []


class TestFatiar:
    def test_cada_letra_vira_arquivo_com_deslocamento(self, tmp_path):
        tela([(0, 10, 40, 90), (60, 10, 100, 90), (120, 10, 160, 90)]).save(tmp_path / "p.png")
        pedacos = fatiar(tmp_path / "p.png", tmp_path)
        assert len(pedacos) == 3
        assert [p["dx"] for p in pedacos] == [0, 60, 120]
        assert all((tmp_path / p["src"]).exists() for p in pedacos)

    def test_o_recorte_tem_o_tamanho_da_letra(self, tmp_path):
        tela([(0, 10, 40, 90), (60, 10, 100, 90)]).save(tmp_path / "p.png")
        p = fatiar(tmp_path / "p.png", tmp_path)[0]
        assert Image.open(tmp_path / p["src"]).size == (p["w"], p["h"])

    def test_uma_letra_so_nao_vale_fatiar(self, tmp_path):
        """Nada a ganhar: quem chamou segue com a camada inteira."""
        tela([(10, 10, 60, 90)]).save(tmp_path / "p.png")
        assert fatiar(tmp_path / "p.png", tmp_path) == []

    def test_imagem_sem_tinta_nao_quebra(self, tmp_path):
        tela([]).save(tmp_path / "p.png")
        assert fatiar(tmp_path / "p.png", tmp_path) == []

    def test_tres_linhas_viram_letras_por_linha(self, tmp_path):
        im = tela([(0, 0, 20, 20), (30, 0, 50, 20),
                   (0, 40, 20, 60), (30, 40, 50, 60),
                   (0, 80, 20, 99)])
        im.save(tmp_path / "p.png")
        pedacos = fatiar(tmp_path / "p.png", tmp_path)
        assert len(pedacos) == 5
        assert sorted({p["dy"] for p in pedacos}) == [0, 40, 80]
