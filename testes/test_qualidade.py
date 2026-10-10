"""O fundo da peça tem que ser o fundo da arte.

Numa peça de marca o fundo é grafismo, não enchimento. Trocar a trama por um
degradê liso passa em qualquer conferência de cor ou de corte, e só aparece
quando alguém olha a peça — que é tarde.
"""
import numpy as np
import pytest
from PIL import Image

from api.qualidade import MINIMO_FUNDO, conferir_fundo, estrutura, fidelidade_do_fundo


def arte_com_trama(w=400, h=300):
    """Fundo azul com grade e um arco: imita a linguagem gráfica de uma peça."""
    a = np.full((h, w, 3), (12, 30, 110), dtype=np.uint8)
    a[::20, :] = (40, 70, 160)                       # linhas horizontais
    a[:, ::20] = (40, 70, 160)                       # linhas verticais
    yy, xx = np.mgrid[0:h, 0:w]
    arco = np.abs(np.hypot(xx - w * 0.2, yy - h * 0.5) - h * 0.4) < 3
    a[arco] = (120, 180, 255)
    return Image.fromarray(a)


def chapado(w=400, h=300):
    return Image.fromarray(np.full((h, w, 3), (12, 30, 110), dtype=np.uint8))


def ruidoso(w=400, h=300, seed=7):
    """Liso com grão. O olho lê como vazio; uma medida ingênua lê como detalhe."""
    r = np.random.default_rng(seed)
    base = np.full((h, w, 3), (12, 30, 110), dtype=float)
    return Image.fromarray(np.clip(base + r.normal(0, 9, (h, w, 3)), 0, 255).astype(np.uint8))


class TestEstrutura:
    def test_trama_pontua_mais_que_chapado(self):
        assert estrutura(arte_com_trama()) > estrutura(chapado()) * 3

    def test_grao_nao_conta_como_grafismo(self):
        """Foi o erro da primeira medição: sem o borrão, o ruidoso pontuava
        acima de um fundo com trama de verdade, e a conta aprovava o errado."""
        assert estrutura(ruidoso()) < estrutura(arte_com_trama())


class TestFidelidade:
    def test_fundo_igual_a_arte_preserva_tudo(self):
        a = arte_com_trama()
        assert fidelidade_do_fundo(a, a) == pytest.approx(1.0, abs=0.01)

    def test_recorte_que_mantem_a_trama_passa(self):
        a = arte_com_trama()
        pedaco = a.crop((40, 40, 360, 260))           # mesma trama, área menor
        ok, msg = conferir_fundo(a, pedaco)
        assert ok, msg

    def test_degrade_liso_no_lugar_da_trama_reprova(self):
        ok, msg = conferir_fundo(arte_com_trama(), chapado())
        assert not ok
        assert "grafismo" in msg and "estenda" in msg

    def test_liso_com_grao_tambem_reprova(self):
        """O caso traiçoeiro: parece ter detalhe, não tem desenho."""
        ok, _ = conferir_fundo(arte_com_trama(), ruidoso())
        assert not ok

    def test_arte_sem_grafismo_nao_e_cobrada(self):
        """Arte lisa não tem o que preservar; cobrar seria reprovar o correto."""
        ok, _ = conferir_fundo(chapado(), chapado())
        assert ok


class TestLimite:
    def test_o_limite_fica_entre_os_dois_casos_reais(self):
        """0.65 foi o fundo que o agente compôs para o banner do Energiza;
        0.34 foi um recorte de área lisa, que a olho nu tinha perdido a grade."""
        assert 0.34 < MINIMO_FUNDO < 0.65


class TestFundoNaoPodePegarMarca:
    """Estrutura não distingue textura de texto. Esta regra existe porque a
    outra, sozinha, aprovou um fundo com lettering fantasma — com 211%."""

    MARCAS = {"logo": (555, 20, 1010, 242), "lettering": (110, 265, 545, 895)}

    def test_acusa_a_faixa_que_pegou_o_lettering(self):
        from api.qualidade import fundo_invade_marca
        assert fundo_invade_marca((620, 120, 1600, 240), self.MARCAS) == "logo"

    def test_aprova_faixa_em_area_livre(self):
        from api.qualidade import fundo_invade_marca
        assert fundo_invade_marca((1010, 250, 1600, 324), self.MARCAS) is None

    def test_encosto_de_borda_nao_conta_como_invasao(self):
        from api.qualidade import fundo_invade_marca
        # começa exatamente onde o logo termina: não há sobreposição
        assert fundo_invade_marca((1010, 242, 1600, 320), self.MARCAS) is None


class TestRecorteComAlfa:
    """Marca colada como retângulo aparece com moldura na peça — é o que se lê
    como texto carimbado."""

    def test_bloco_opaco_e_acusado(self):
        from api.qualidade import recorte_e_retangulo
        bloco = Image.new("RGBA", (120, 60), (255, 255, 255, 255))
        assert recorte_e_retangulo(bloco) is True

    def test_imagem_sem_canal_alfa_e_acusada(self):
        from api.qualidade import recorte_e_retangulo
        assert recorte_e_retangulo(Image.new("RGB", (120, 60), (255, 255, 255))) is True

    def test_elemento_recortado_passa(self):
        from api.qualidade import recorte_e_retangulo
        im = Image.new("RGBA", (120, 60), (0, 0, 0, 0))
        im.paste((255, 255, 255, 255), (30, 15, 90, 45))     # só o miolo é opaco
        assert recorte_e_retangulo(im) is False
