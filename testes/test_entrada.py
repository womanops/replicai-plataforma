"""Leitura de bbox e tamanho. A API vai receber isso de fora, então entrada
torta precisa virar erro claro, e não canvas de 0 pixel ou coordenada negativa.
"""
import pytest

from motor.replica import parse_bbox, parse_size


class TestBbox:
    @pytest.mark.parametrize("texto,esperado", [
        ("10,20,110,220",      (10, 20, 110, 220)),
        ("10 20 110 220",      (10, 20, 110, 220)),
        ("10, 20,  110 , 220", (10, 20, 110, 220)),
        ("10.4,20.6,110,220",  (10, 21, 110, 220)),      # arredonda
    ])
    def test_le_os_formatos_aceitos(self, texto, esperado):
        assert parse_bbox(texto) == esperado

    def test_endireita_cantos_invertidos(self):
        """Quem marca a área arrastando da direita para a esquerda manda x1 < x0.
        Sem normalizar, a largura sai negativa e o recorte vem vazio."""
        assert parse_bbox("110,220,10,20") == (10, 20, 110, 220)

    @pytest.mark.parametrize("ruim", ["10,20,30", "", "a,b,c,d", "10,20,30,40,50"])
    def test_recusa_entrada_torta(self, ruim):
        with pytest.raises(ValueError):
            parse_bbox(ruim)


class TestTamanho:
    @pytest.mark.parametrize("texto,esperado", [
        ("1080x1350", (1080, 1350)),
        ("1080X1350", (1080, 1350)),
        ("1080×1350", (1080, 1350)),      # o × que vem de copiar e colar
        (" 300 x 250 ", (300, 250)),
    ])
    def test_le_os_formatos_aceitos(self, texto, esperado):
        assert parse_size(texto) == esperado

    @pytest.mark.parametrize("ruim", ["1080", "1080x", "x250", "1080*250", "", "-100x200"])
    def test_recusa_entrada_torta(self, ruim):
        with pytest.raises(ValueError):
            parse_size(ruim)
