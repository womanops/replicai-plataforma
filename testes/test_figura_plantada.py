"""Para que lado a faixa nova vai quando o quadro cresce.

Melhor prática de diagramação, e não preferência: o que está plantado numa
borda continua plantado nela. No KV da Consigaz o mascote é cortado pelo
rodapé da prancheta — ele está em pé no chão da peça. Centrar a arte no quadro
novo abriu faixa embaixo dele, e o Stories saiu com o Nino amputado flutuando
sobre um rodapé vazio.

Não é régua de pixel: o arquivo diz. Camada com bbox que passa da borda é
figura cortada pelo quadro.
"""
import pytest


class Falsa:
    """Uma camada, com o mínimo que a regra olha."""

    def __init__(self, bbox):
        self.bbox = bbox

    def is_group(self):
        return False


class Prancheta:
    def __init__(self, w=1200, h=1200, x=0, y=0):
        self.x, self.y, self.w, self.h = x, y, w, h


def bordas(camadas, prancheta=None):
    from api.psd import _bordas_com_figura
    return _bordas_com_figura([Falsa(b) for b in camadas], prancheta or Prancheta())


class TestOndeAFiguraEstaPlantada:
    def test_mascote_cortado_pelo_rodape(self):
        """O bbox real do Nino na prancheta de 1200×1200."""
        assert "baixo" in bordas([(718, 748, 1240, 1586)])

    def test_e_tambem_pela_direita(self):
        assert "direita" in bordas([(718, 748, 1240, 1586)])

    def test_fundo_que_sangra_dos_quatro_lados_nao_e_figura(self):
        assert bordas([(0, -335, 1200, 1463)]) == set()

    def test_faixa_larga_cortada_em_cima_nao_e_figura(self):
        """`Camada 5 copiar` atravessa 91% da largura: é textura de fundo, e
        tratá-la como figura prenderia a arte no topo sem motivo."""
        assert "cima" not in bordas([(147, -66, 1240, 589)])

    def test_camada_inteira_dentro_nao_prende_nada(self):
        assert bordas([(100, 100, 400, 400)]) == set()


class TestParaOndeAFaixaVai:
    def test_figura_embaixo_joga_a_faixa_para_cima(self):
        from api.psd import ancora_das_bordas
        assert ancora_das_bordas({"baixo"}) == (0.5, 1.0)

    def test_figura_em_cima_joga_a_faixa_para_baixo(self):
        from api.psd import ancora_das_bordas
        assert ancora_das_bordas({"cima"}) == (0.5, 0.0)

    def test_figura_nos_dois_lados_volta_ao_centro(self):
        """Sem lado melhor, o comportamento antigo: dividir a faixa."""
        from api.psd import ancora_das_bordas
        assert ancora_das_bordas({"cima", "baixo"}) == (0.5, 0.5)

    def test_sem_figura_nenhuma_volta_ao_centro(self):
        from api.psd import ancora_das_bordas
        assert ancora_das_bordas(set()) == (0.5, 0.5)

    def test_o_caso_real_da_consigaz(self):
        """Figura cortada embaixo, à direita e à esquerda: o eixo horizontal
        empata e o vertical encosta embaixo."""
        from api.psd import ancora_das_bordas
        assert ancora_das_bordas({"baixo", "direita", "esquerda"}) == (0.5, 1.0)


class TestAEsteiraUsaAAncora:
    def test_reenquadrar_passa_a_ancora(self):
        import inspect

        from api import psd
        assert "ancora_das_bordas" in inspect.getsource(psd.reenquadrar)

    def test_recompor_nao_abre_rodape_sob_figura_plantada(self):
        """`recompor` desce a arte para abrir rodapé ao texto novo. Embaixo de
        uma figura plantada, descer é cortar o corpo dela no meio."""
        import inspect

        from api import psd
        assert "ancora_das_bordas" in inspect.getsource(psd.recompor)

    def test_a_leitura_carrega_as_bordas(self):
        from api.psd import Leitura
        assert Leitura().plantada_em == []
