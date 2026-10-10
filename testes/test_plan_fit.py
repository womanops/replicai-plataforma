"""O `plan_fit` decide entre cortar e estender a arte para caber no formato.

É a promessa do produto: desdobrar sem cortar conteúdo. Um erro aqui não quebra
nada visível — entrega peças com o logo pela metade, caladamente.

O desenho é este, e os testes giram em volta dele:

- **Sem região protegida, nunca corta.** Estende o fundo, porque não há como
  saber o que pode ser perdido.
- **Com região protegida, pode cortar** — mas só fora dela, e só quando cortar
  evita inventar fundo. Fundo inventado custa caro (outpaint) e é o que mais sai
  errado.
"""
import pytest

from motor.replica import load_formatos, plan_fit

# Casos em que cortar é melhor que estender: a base tem sobra fora do protegido.
# Cada um já foi conferido na mão; se o motor mudar de ideia aqui, é regressão.
CORTA = [
    ("base alta -> feed, protegido embaixo",  1080, 1920, 1080, 1350, [100, 1480, 980, 1880]),
    ("base alta -> feed, protegido em cima",  1080, 1920, 1080, 1350, [100,   40, 980,  440]),
    ("base larga -> quadrado, à direita",     1920, 1080, 1080, 1080, [1500, 100, 1880, 980]),
    ("base larga -> quadrado, à esquerda",    1920, 1080, 1080, 1080, [40,   100,  420, 980]),
]


def contem(crop, protect):
    return (crop[0] <= protect[0] and crop[1] <= protect[1]
            and crop[2] >= protect[2] and crop[3] >= protect[3])


class TestSemProtecaoNaoCorta:
    """Sem saber o que proteger, cortar é apostar. O motor estende."""

    @pytest.mark.parametrize("alvo", [(1080, 1920), (1080, 1350), (728, 90), (300, 250)])
    def test_crop_e_a_base_inteira(self, alvo):
        W, H = 1080, 1080
        r = plan_fit(W, H, alvo[0], alvo[1])
        assert r["crop"] == [0, 0, W, H], "cortou sem saber o que estava protegendo"
        assert r["cortou_fundo"] is False


class TestComProtecaoCorta:
    """Cortar fora do protegido evita inventar fundo, que é caro e arriscado."""

    @pytest.mark.parametrize("nome,W,H,w,h,prot", CORTA, ids=[c[0] for c in CORTA])
    def test_prefere_cortar_a_estender(self, nome, W, H, w, h, prot):
        r = plan_fit(W, H, w, h, protect=prot)
        assert r["estrategia"] == "crop", \
            f"estendeu quando dava para cortar fora do protegido: {r['crop']}"
        assert r["expand"] == {"left": 0, "right": 0, "top": 0, "bottom": 0}

    @pytest.mark.parametrize("nome,W,H,w,h,prot", CORTA, ids=[c[0] for c in CORTA])
    def test_o_corte_nao_encosta_no_protegido(self, nome, W, H, w, h, prot):
        r = plan_fit(W, H, w, h, protect=prot)
        assert contem(r["crop"], prot), \
            f"o corte comeu parte da região protegida: crop {r['crop']}, protegido {prot}"

    def test_protegido_ocupando_tudo_obriga_a_estender(self):
        r = plan_fit(1080, 1080, 728, 90, protect=[0, 0, 1080, 1080])
        assert r["estrategia"] == "extend"
        assert r["crop"] == [0, 0, 1080, 1080]
        assert r["expand"]["left"] > 0 and r["expand"]["right"] > 0


class TestCanvasFechaAConta:
    @pytest.mark.parametrize("alvo", [(1080, 1920), (1080, 1350), (1080, 1080), (728, 90)])
    def test_canvas_e_crop_mais_extensao(self, alvo):
        r = plan_fit(1200, 800, alvo[0], alvo[1], protect=[300, 200, 900, 600])
        c, e, cb = r["crop"], r["expand"], r["canvas_base"]
        assert cb[0] == (c[2] - c[0]) + e["left"] + e["right"]
        assert cb[1] == (c[3] - c[1]) + e["top"] + e["bottom"]

    @pytest.mark.parametrize("alvo", [(1080, 1920), (1080, 1350), (300, 250), (1920, 1080)])
    def test_sai_na_proporcao_do_alvo(self, alvo):
        """Proporção errada é peça esticada ou com barra preta."""
        r = plan_fit(1080, 1080, alvo[0], alvo[1], protect=[100, 100, 980, 980])
        assert r["canvas_base"][0] / r["canvas_base"][1] == pytest.approx(alvo[0] / alvo[1], rel=0.01)


class TestMesmaProporcao:
    def test_nao_mexe_em_nada(self):
        r = plan_fit(1080, 1080, 540, 540)
        assert r["estrategia"] == "crop"
        assert r["crop"] == [0, 0, 1080, 1080]
        assert r["cortou_fundo"] is False


class TestFolga:
    def test_abre_espaco_alem_do_necessario(self):
        """Folga é espaço extra pedido para o texto respirar."""
        sem = plan_fit(1080, 1080, 1080, 1080, protect=[200, 200, 880, 880])
        com = plan_fit(1080, 1080, 1080, 1080, protect=[200, 200, 880, 880], folga=0.3)
        assert com["canvas_base"][1] >= sem["canvas_base"][1]


class TestCatalogoInteiro:
    """Varre os 38 formatos publicados: barato, e pega regressão em massa."""

    @pytest.mark.parametrize("base", [(1080, 1080), (1920, 1080), (1080, 1920), (2000, 3000)])
    def test_nenhum_formato_corta_o_protegido(self, base):
        W, H = base
        prot = [int(W * 0.15), int(H * 0.2), int(W * 0.85), int(H * 0.7)]
        for f in load_formatos()["formatos"]:
            r = plan_fit(W, H, f["w"], f["h"], protect=prot)
            assert contem(r["crop"], prot), f"{f['id']}: crop {r['crop']} cortou {prot}"
            cb = r["canvas_base"]
            assert cb[0] / cb[1] == pytest.approx(f["w"] / f["h"], rel=0.02), \
                f"{f['id']}: proporção saiu {cb[0]/cb[1]:.4f}, esperado {f['w']/f['h']:.4f}"
