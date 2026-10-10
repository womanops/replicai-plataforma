"""Higiene de linha.

Vem de uma peça real: no Stories a frase quebrou em "25 de março" e
"· São Paulo", com o separador abrindo a segunda linha.
"""
from api.tipografia import NBSP, ajeitar


class TestSeparador:
    def test_o_ponto_nao_abre_linha(self):
        assert ajeitar("25 de março · São Paulo") == f"25 de março{NBSP}· São Paulo"

    def test_vale_para_os_outros_separadores(self):
        for s in "•|–—":
            assert ajeitar(f"a {s} b") == f"a{NBSP}{s} b"

    def test_ponto_sem_espaco_em_volta_nao_e_separador(self):
        assert ajeitar("3·4") == "3·4"


class TestPalavraDeUmaLetra:
    def test_nao_fecha_linha(self):
        assert ajeitar("Energia e futuro") == f"Energia e{NBSP}futuro"

    def test_com_acento_tambem(self):
        assert ajeitar("vem à festa") == f"vem à{NBSP}festa"

    def test_palavra_de_duas_letras_pode_fechar(self):
        assert ajeitar("vem de longe") == "vem de longe"


class TestNaoMexeNoTexto:
    def test_nenhuma_letra_muda(self):
        t = "25 de março · São Paulo e região"
        assert ajeitar(t).replace(NBSP, " ") == t

    def test_vazio_e_none_nao_quebram(self):
        assert ajeitar("") == ""
        assert ajeitar(None) is None

    def test_texto_sem_nada_a_prender_passa_igual(self):
        assert ajeitar("Inscreva-se") == "Inscreva-se"


class TestNaComposicao:
    """Escrever a regra e não chamá-la é o erro recorrente deste projeto."""

    def _texto(self, papel, texto, zona="baixo-centro"):
        from api.composicao import Elemento, Esquema, montar
        from motor.replica import formato_by_id
        esq = Esquema([Elemento(papel, zona, texto)], {})
        peca = montar(esq, formato_by_id("ig-stories"), {"tipo": "cor", "cor": "#000"})
        return peca["elementos"][0]["texto"]

    def test_a_headline_sai_com_a_quebra_presa(self):
        assert self._texto("headline", "25 de março · São Paulo") == \
            f"25 de março{NBSP}· São Paulo"

    def test_o_botao_tambem(self):
        assert self._texto("cta", "vem e veja") == f"vem e{NBSP}veja"
