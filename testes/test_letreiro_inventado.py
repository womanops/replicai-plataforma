"""O generativo escrevendo palavra que ninguém escreveu.

Numa rodada real da Torra, gravando o vídeo da landing: as duas pontas de um
site-hero voltaram com letreiro falso — "CAFIDAHILD LIO'A", "ITOЯ UIÉNI",
"Torrabutõnrulo Vra" —, um segundo botão laranja e blocos de texto ilegível.
As ressalvas falavam de faixa encolhida e de texto encostando na borda. Nada
sobre conteúdo inventado.

A casa não inventa. A extensão continua o desenho do fundo; ela não escreve.
"""
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from api.fundo import inventou_letreiro

TORRA = Path("/Users/ligia/Desktop/OPERAÇÃO CLAUDE CODE/ReplicAI/demo/plataforma"
             "/defeitos-2026-10-22/torra-png-teste-f270bf/fundo-site-hero.png")


# As provas são recortes, em tamanho real, do fundo que saiu naquela rodada:
# a mesma ponta esquerda com e sem o letreiro que o generativo escreveu. Caso
# sintético não serve aqui — o que a régua procura é a cara da letra, e barra
# desenhada à mão não tem cara de letra.
COM = Path(__file__).parent / "fundo-com-letreiro.png"
SEM = Path(__file__).parent / "fundo-sem-letreiro.png"
# a arte ocupa a metade direita do recorte; a esquerda é extensão
CAIXA = (384, 0, 768, 300)


class TestARegua:
    def test_acusa_o_letreiro(self):
        avisos = inventou_letreiro(COM, CAIXA)
        assert avisos and "escreveu texto que a arte não tem" in avisos[0]

    def test_diz_em_que_ponta(self):
        assert "à esquerda" in inventou_letreiro(COM, CAIXA)[0]

    def test_nao_acusa_continuacao_limpa(self):
        """O mesmo fundo, a mesma ponta, mais acima: ali ele continuou o
        desenho sem escrever. Acusar isso devolveria peça boa."""
        assert inventou_letreiro(SEM, CAIXA) == []

    def test_a_foto_nao_e_acusada_de_escrever(self):
        """Com a arte inteira dentro da "faixa", a densidade é de foto e a
        régua se cala: ela não sabe distinguir letra de grão, e chutar seria
        acusar toda peça com fundo rico."""
        assert inventou_letreiro(COM, (760, 0, 768, 300)) == []

    def test_faixa_estreita_demais_nao_e_acusada(self):
        """Em 36 px não cabe palavra nenhuma: acusar ali é acusar o brilho de
        um dedo. Foi o único falso positivo em quarenta fundos reais."""
        assert inventou_letreiro(COM, (36, 0, 768, 300)) == []

    def test_sem_extensao_nao_ha_o_que_conferir(self):
        assert inventou_letreiro(COM, None) == []

    def test_arquivo_que_nao_existe_nao_derruba_a_entrega(self):
        assert inventou_letreiro(Path("nao-existe.png"), CAIXA) == []


@pytest.mark.lento
class TestNoCasoDeVerdade:
    def test_o_site_hero_da_torra_e_acusado(self):
        if not TORRA.exists():
            pytest.skip("a prova da rodada não está nesta máquina")
        avisos = inventou_letreiro(TORRA, (384, 0, 1536, 700))
        assert avisos, "o letreiro falso das duas pontas passou limpo"
        assert "à esquerda" in avisos[0] and "à direita" in avisos[0]


class TestAPecaNaoSaiComLetreiro:
    """Texto inventado é da mesma família da cor absurda: não é ressalva, é
    outra peça. Ninguém publica um fundo com palavra que ninguém escreveu."""

    def test_o_generativo_que_escreve_e_descartado(self):
        import inspect

        from api import fundo
        corpo = inspect.getsource(fundo.preparar)
        assert "or escreveu" in corpo, "o letreiro não derruba o fundo generativo"
        assert "peça não ganha palavra que ninguém escreveu" in corpo

    def test_a_insistencia_conta_o_letreiro_como_erro(self):
        """Senão a segunda chamada repete o mesmo letreiro e paga de novo."""
        import inspect

        from api import fundo
        assert "inventou_letreiro(prova, caixa)" in inspect.getsource(fundo._melhor_continuacao)
