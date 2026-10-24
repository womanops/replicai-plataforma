"""Cortar lettering de imagem em letras.

A camada de texto do PSD chega rasterizada: animar a imagem inteira entrando é
transição de slide, não motion. E com lettering desenhado não há como
retipografar — a fonte é da marca e quase nunca está na máquina.
"""
import numpy as np
import pytest
from PIL import Image, ImageDraw

from api.letras import LIMIAR, fatiar, letras, linhas


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


class TestOQueDesceAbaixoDaBase:
    """Em 24/10/2026 a peça da Consigaz saiu com "solucão" no lugar de
    "solução", e com o pé do "p" de `prefere` e do "g" de `Consigaz` cortados
    rente. O corte vinha do piso de `_blocos`: 2% da fileira mais cheia.

    A cedilha pertence a UMA letra — quanto mais palavras na linha, menor a
    fração dela no total, e mais certo que o rabo fique abaixo do piso e seja
    lido como fileira vazia. Na peça real faltaram 22 pontos de tinta.

    Era silencioso: a peça saía, nenhuma ressalva aparecia, e o erro só
    aparecia ampliando a palavra. Por isso a prova é larga: é a LARGURA da
    linha que afunda o rabo no piso, e uma prova estreita passaria sozinha.
    """
    LARGA = 800          # 770 colunas de corpo contra 10 de rabo: 1,3%

    def linha_com_rabo(self, desce_ate=86):
        return tela([(10, 20, 780, 60), (150, 60, 160, desce_ate)],
                    w=self.LARGA, h=140)

    def test_o_rabo_cai_abaixo_do_piso(self):
        """A prova só prova se reproduzir a condição: sem isto, um teste
        verde não diria nada sobre o defeito."""
        alfa = alfa_de(self.linha_com_rabo())
        soma = alfa.sum(1)
        assert soma[70] < soma.max() * LIMIAR, (
            "nesta prova o rabo passa no piso sozinho — ela não reproduz o "
            "defeito e não serve de prova")

    def test_a_faixa_vai_ate_o_fim_do_rabo(self):
        (a, b), = linhas(alfa_de(self.linha_com_rabo()))
        assert a == 20
        assert b >= 86, (f"a faixa acabou em {b}: parou na base e o rabo da "
                         f"letra, que vai até 86, ficou de fora")

    def test_o_rabo_nao_funde_a_linha_de_baixo(self):
        """O conserto ingênuo — baixar o piso — faz o rabo encostar na linha
        seguinte e as duas viram uma faixa só. Na camada real da Consigaz a
        cedilha desce até a altura da próxima linha."""
        im = tela([(10, 20, 780, 60),          # linha de cima
                   (150, 60, 160, 86),          # o rabo, até encostar
                   (10, 86, 780, 126)],         # linha de baixo
                  w=self.LARGA, h=140)
        achadas = linhas(alfa_de(im))
        assert len(achadas) == 2, f"as duas linhas viraram {len(achadas)}"
        assert achadas[0][1] >= 80, "o rabo ficou de fora de novo"
        assert achadas[1][0] >= 86, "a linha de baixo começou cedo demais"

    def test_linha_sem_rabo_fica_como_estava(self):
        """Caixa alta não desce: `ENERGIZA 2027` não pode mudar de faixa por
        causa deste conserto."""
        im = tela([(10, 20, 780, 60)], w=self.LARGA, h=140)
        assert linhas(alfa_de(im)) == [(20, 61)]
