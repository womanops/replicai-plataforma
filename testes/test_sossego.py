"""O texto vai onde o fundo é quieto.

Vem de uma revisão de duas peças: no 1:1 a data entrava enorme atravessando a
chama de vidro, e no leaderboard ela sumia dentro dela. Nas duas havia espaço
geométrico de sobra — o que faltava era lugar.
"""
import pytest
from PIL import Image, ImageDraw

from api.sossego import AGITADO, acalmar, perfil, trecho_calmo


@pytest.fixture
def metade_agitada():
    """Esquerda com listras, direita lisa: o degrau que a peça real tinha."""
    im = Image.new("RGB", (400, 200), "#0a1a55")
    d = ImageDraw.Draw(im)
    for x in range(0, 200, 12):
        d.rectangle((x, 0, x + 6, 200), fill="#ffffff")
    return im


class TestMedida:
    def test_fundo_liso_nao_tem_agitacao(self):
        im = Image.new("RGB", (200, 100), "#0a1a55")
        assert all(a < 1 for _, _, a in perfil(im, [0, 0, 200, 100]))

    def test_o_desenho_aparece_na_medida(self, metade_agitada):
        fatias = perfil(metade_agitada, [0, 0, 400, 200])
        esquerda = [a for i, _, a in fatias if i < 180]
        direita = [a for i, _, a in fatias if i > 220]
        assert min(esquerda) > AGITADO
        assert max(direita) < AGITADO

    def test_retangulo_degenerado_nao_quebra(self):
        im = Image.new("RGB", (100, 100), "#000")
        assert perfil(im, [50, 50, 50, 50]) == []


class TestAparar:
    def test_fica_com_o_lado_liso(self, metade_agitada):
        r = trecho_calmo(metade_agitada, [0, 0, 400, 200])
        assert r[0] >= 180 and r[2] == 400

    def test_fundo_todo_liso_nao_e_aparado(self):
        im = Image.new("RGB", (400, 200), "#0a1a55")
        assert trecho_calmo(im, [0, 0, 400, 200]) == [0, 0, 400, 200]

    def test_fundo_todo_agitado_nao_tem_lugar(self):
        im = Image.new("RGB", (400, 200), "#000")
        d = ImageDraw.Draw(im)
        for x in range(0, 400, 12):
            d.rectangle((x, 0, x + 6, 200), fill="#fff")
        assert trecho_calmo(im, [0, 0, 400, 200]) is None

    def test_sobra_estreita_demais_nao_vale(self, metade_agitada):
        """80px ao lado da chama é espaço, não lugar: viraria coluna de jornal."""
        d = ImageDraw.Draw(metade_agitada)
        for x in range(240, 400, 12):
            d.rectangle((x, 0, x + 6, 200), fill="#fff")
        assert trecho_calmo(metade_agitada, [0, 0, 400, 200]) is None


class TestAcalmar:
    def test_apara_e_conta_o_que_fez(self, metade_agitada):
        livres, notas = acalmar(metade_agitada, {"top": [0, 0, 400, 200]})
        assert livres["top"][0] >= 180
        assert "encolhida" in notas[0]

    def test_faixa_sem_lugar_sai_da_lista(self):
        im = Image.new("RGB", (400, 200), "#000")
        d = ImageDraw.Draw(im)
        for x in range(0, 200, 12):
            d.rectangle((x, 0, x + 6, 200), fill="#fff")
        livres, notas = acalmar(im, {"left": [0, 0, 200, 200], "right": [200, 0, 400, 200]})
        assert set(livres) == {"right"}
        assert any("ponta a ponta" in n for n in notas)

    def test_se_nenhuma_sobrar_devolve_as_originais(self):
        """Peça sem texto é pior do que peça com texto em lugar difícil — e o
        aviso de contraste ainda aparece depois."""
        im = Image.new("RGB", (400, 200), "#000")
        d = ImageDraw.Draw(im)
        for x in range(0, 400, 12):
            d.rectangle((x, 0, x + 6, 200), fill="#fff")
        originais = {"top": [0, 0, 400, 200]}
        livres, notas = acalmar(im, originais)
        assert livres == originais and notas
