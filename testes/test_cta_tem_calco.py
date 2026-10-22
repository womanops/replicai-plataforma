"""O CTA é botão, componha quem compuser.

"Quando gero peça na terceira opção com texto e CTA, ele funcionou, mas as
peças menores ficaram sem o calço do botão Saiba Mais, como ficou a maior
peça."

A régua sempre desenhou o CTA como botão. O modelo às vezes devolvia o mesmo
CTA como linha de texto solta — e a mesma campanha saía com botão numa medida
e sem botão na outra. Um CTA sem calço não lê como chamada para ação: lê como
legenda.
"""
from api.composicao import BOTAO_FUNDO, como_botao


def cta(**extra):
    base = {"tipo": "texto", "papel": "cta", "texto": "Saiba Mais",
            "box": {"x": 605, "y": 147, "w": 300, "h": 29}, "cor": "#ffffff"}
    base.update(extra)
    return base


class TestOCtaViraBotao:
    def test_texto_solto_ganha_o_calco(self):
        b = como_botao(cta(), 250)
        assert b["tipo"] == "botao"
        assert b["fundo"] == BOTAO_FUNDO
        assert b["raio"] > 0, "sem raio é um retângulo branco, não uma pílula"

    def test_a_letra_nao_herda_a_cor_do_texto_solto(self):
        """Ela vinha de texto sobre arte escura, então era branca — e branca
        dentro de uma pílula branca é uma pílula vazia. Foi o que o render
        mostrou na primeira tentativa."""
        assert como_botao(cta(cor="#ffffff"), 250)["cor"] != "#ffffff"

    def test_o_botao_abraca_o_texto(self):
        """Herdando a caixa da coluna ele sai como uma barra branca
        atravessando a peça, com a letra minúscula no meio."""
        b = como_botao(cta(box={"x": 439, "y": 62, "w": 646, "h": 8}), 90)
        assert b["box"]["w"] < 300, f"largura herdada da coluna: {b['box']['w']}"

    def test_a_pilula_tem_a_altura_que_a_letra_pede(self):
        """Espremida na caixa que veio — oito pixels, numa faixa — ela sairia
        como um risco branco com a letra saindo por cima."""
        b = como_botao(cta(box={"x": 439, "y": 62, "w": 646, "h": 8}), 90)
        assert b["box"]["h"] >= b["tamanho"] * 2

    def test_e_continua_dentro_da_peca(self):
        b = como_botao(cta(box={"x": 10, "y": 86, "w": 300, "h": 4}), 90)
        assert b["box"]["y"] >= 0 and b["box"]["y"] + b["box"]["h"] <= 90

    def test_fica_no_lugar_em_que_o_cta_estava(self):
        """Centrado na caixa que veio: quem escolheu a zona foi quem compôs,
        e a conversão não é hora de mudar a diagramação."""
        b = como_botao(cta(box={"x": 600, "y": 100, "w": 300, "h": 40}), 250)
        antes_meio = 600 + 300 / 2
        assert abs((b["box"]["x"] + b["box"]["w"] / 2) - antes_meio) <= 1

    def test_quem_ja_era_botao_nao_e_mexido(self):
        b = {"tipo": "botao", "papel": "cta", "texto": "x", "fundo": "#abcdef",
             "box": {"x": 1, "y": 1, "w": 9, "h": 9}}
        assert como_botao(dict(b), 600) == b

    def test_so_o_cta(self):
        """Chamada e apoio são texto: virar botão poria um calço branco no
        meio da arte."""
        for papel in ("headline", "apoio", "selo", "marca"):
            assert como_botao(cta(papel=papel), 250)["tipo"] == "texto"


class TestAEsteiraNormaliza:
    def test_o_texto_novo_passa_pelo_calco(self):
        import inspect

        from api import pipeline
        fonte = inspect.getsource(pipeline._texto_novo)
        assert "como_botao(e, formato[\"h\"])" in fonte
