"""As regras de diagramação.

Vêm de uma revisão: as convenções de cada formato existiam em prosa no campo
`notas` e iam no prompt, mas nada conferia depois — e conselho sem conferência
é conselho ignorado.
"""
import pytest

from api.composicao import Elemento, RespostaInvalida, conferir as conferir_resposta
from api.diagramacao import conferir, convencao, e_faixa
from motor.replica import formato_by_id


def els(**papel_zona):
    return [Elemento(p, z) for p, z in papel_zona.items()]


class TestOrdemDeLeitura:
    def test_a_ordem_que_desce_passa(self):
        assert conferir(els(headline="topo-centro", apoio="meio-centro",
                            cta="baixo-centro"), formato_by_id("ig-stories")) == ""

    def test_cta_acima_da_headline_e_recusado(self):
        erro = conferir(els(headline="baixo-centro", cta="topo-centro"),
                        formato_by_id("ig-stories"))
        assert "inverte a leitura" in erro or "abre a peça" in erro

    def test_apoio_acima_da_headline_e_recusado(self):
        assert "inverte a leitura" in conferir(
            els(headline="meio-centro", apoio="topo-centro"), formato_by_id("ig-feed-1x1"))

    def test_mesma_faixa_para_todos_passa(self):
        assert conferir(els(headline="baixo-centro", cta="baixo-centro"),
                        formato_by_id("ig-feed-1x1")) == ""

    def test_marca_e_selo_nao_entram_na_ordem(self):
        """São mobília de canto: a marca no rodapé não inverte leitura nenhuma."""
        assert conferir(els(marca="baixo-esquerda", headline="topo-esquerda",
                            cta="baixo-esquerda"), formato_by_id("ig-feed-1x1")) == ""


class TestAlinhamento:
    def test_misturar_alinhamento_e_recusado(self):
        assert "mistura alinhamentos" in conferir(
            els(headline="topo-centro", cta="baixo-esquerda"), formato_by_id("ig-feed-1x1"))

    def test_um_alinhamento_so_passa(self):
        assert conferir(els(headline="topo-esquerda", cta="baixo-esquerda"),
                        formato_by_id("ig-feed-1x1")) == ""


class TestFaixaHorizontal:
    def test_o_leaderboard_e_faixa(self):
        assert e_faixa(formato_by_id("gdn-728x90"))
        assert not e_faixa(formato_by_id("li-feed-16x9"))

    def test_na_faixa_o_cta_fecha_a_direita(self):
        f = formato_by_id("gdn-728x90")
        assert conferir(els(marca="meio-esquerda", headline="meio-centro",
                            cta="meio-direita"), f) == ""
        assert "fecha à direita" in conferir(
            els(headline="meio-centro", cta="meio-esquerda"), f)

    def test_na_faixa_a_marca_abre_a_esquerda(self):
        assert "abre à esquerda" in conferir(
            els(marca="meio-direita", headline="meio-centro"), formato_by_id("gdn-728x90"))

    def test_na_faixa_o_alinhamento_misto_e_o_desenho(self):
        """Fora da faixa isso seria descuido; aqui é a convenção do formato."""
        assert conferir(els(marca="meio-esquerda", headline="meio-centro",
                            cta="meio-direita"), formato_by_id("gdn-728x90")) == ""


class TestAConvencaoVaiNoPrompt:
    def test_a_faixa_tem_texto_proprio(self):
        assert "esquerda" in convencao(formato_by_id("gdn-728x90"))

    def test_a_peca_em_pe_fala_de_ordem(self):
        assert "CTA fecha" in convencao(formato_by_id("ig-stories"))


class TestAConferenciaUsaARegra:
    """Testar a regra direto não prova que alguém a chama. Foi o erro que
    deixou passar o lettering fantasma, e a sabotagem o pegou de novo aqui:
    desligar a diagramação em `conferir` não quebrava teste nenhum."""

    def peca(self, **papel_zona):
        return {"elementos": [{"papel": p, "zona": z, "texto": f"texto de {p}"}
                              for p, z in papel_zona.items()],
                "descartados": {}}

    def test_cta_acima_da_headline_nao_passa_pela_conferencia(self):
        with pytest.raises(RespostaInvalida, match="inverte a leitura|abre a peça"):
            conferir_resposta(self.peca(cta="topo-centro", headline="baixo-centro"),
                              formato_by_id("ig-stories"))

    def test_alinhamento_misto_nao_passa_pela_conferencia(self):
        with pytest.raises(RespostaInvalida, match="mistura alinhamentos"):
            conferir_resposta(self.peca(headline="topo-centro", cta="baixo-esquerda"),
                              formato_by_id("ig-feed-1x1"))

    def test_na_faixa_o_cta_a_esquerda_nao_passa(self):
        with pytest.raises(RespostaInvalida, match="fecha à direita"):
            conferir_resposta(self.peca(headline="meio-centro", cta="meio-esquerda"),
                              formato_by_id("gdn-728x90"))

    def test_diagramacao_certa_passa(self):
        esq = conferir_resposta(self.peca(headline="topo-centro", cta="baixo-centro"),
                                formato_by_id("ig-stories"))
        assert len(esq.elementos) == 2

    def test_faltar_headline_e_dito_antes_do_lugar_errado(self):
        """Dizer o erro certo é o que faz o modelo corrigir numa volta só."""
        with pytest.raises(RespostaInvalida, match="sem headline"):
            conferir_resposta(self.peca(cta="topo-centro"), formato_by_id("ig-stories"))
