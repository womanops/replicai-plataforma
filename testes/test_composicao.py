"""O contrato entre o modelo e o motor.

O modelo responde papéis e zonas; a máquina calcula as caixas. A divisão veio
do experimento de 10/10/2026: julgamento transfere para uma passada, coordenada
exata não.

O que mais importa testar aqui não é o caminho feliz: é que **resposta de modelo
nunca chega ao render sem passar pela conferência**. Modelo erra, inventa campo,
estoura limite e corta conteúdo calado — e peça torta entregue é pior do que
peça não entregue.
"""
import pytest

from api.composicao import PAPEIS, ZONAS, Esquema, RespostaInvalida, conferir, montar
from api.compositor import (ComposicaoImpossivel, CompositorEmCadeia, CompositorModelo,
                            CompositorSimples, instrucao)
from motor.replica import formato_by_id

STORIES = formato_by_id("ig-stories")
BANNER = formato_by_id("gdn-728x90")
THUMB = formato_by_id("yt-thumb")

BOA = {
    "elementos": [
        {"papel": "headline", "zona": "meio-esquerda", "texto": "Chegamos a Porto Belo"},
        {"papel": "cta", "zona": "baixo-esquerda", "texto": "Candidate-se"},
    ],
    "descartados": {"apoio": "competiria com a chamada"},
}


class TestConferencia:
    def test_aceita_resposta_bem_formada(self):
        e = conferir(BOA, STORIES)
        assert [x.papel for x in e.elementos] == ["headline", "cta"]
        assert e.descartados["apoio"]

    @pytest.mark.parametrize("ruim,erro", [
        ({"elementos": []}, "não trouxe elementos"),
        ({"elementos": [{"papel": "rodape", "zona": "topo-centro", "texto": "x"}]}, "papel desconhecido"),
        ({"elementos": [{"papel": "headline", "zona": "canto", "texto": "x"}]}, "zona desconhecida"),
        ({"elementos": [{"papel": "cta", "zona": "topo-centro", "texto": "x"}]}, "sem headline"),
        ({"elementos": [{"papel": "headline", "zona": "topo-centro", "texto": ""}]}, "sem texto"),
        ({"elementos": [{"papel": "marca", "zona": "topo-centro"},
                        {"papel": "headline", "zona": "meio-centro", "texto": "x"}]}, "de onde sai"),
    ])
    def test_recusa_resposta_torta(self, ruim, erro):
        with pytest.raises(RespostaInvalida, match=erro):
            conferir(ruim, STORIES)

    def test_recusa_papel_repetido(self):
        r = {"elementos": [{"papel": "headline", "zona": "topo-centro", "texto": "a"},
                           {"papel": "headline", "zona": "baixo-centro", "texto": "b"}]}
        with pytest.raises(RespostaInvalida, match="dois elementos"):
            conferir(r, STORIES)

    def test_recusa_texto_maior_que_o_formato_aguenta(self):
        r = {"elementos": [{"papel": "headline", "zona": "meio-centro",
                            "texto": "x" * (BANNER["texto"]["headline_max"] + 1)}]}
        with pytest.raises(RespostaInvalida, match="caracteres"):
            conferir(r, BANNER)

    def test_recusa_papel_que_o_formato_nao_leva(self):
        """`cta_max: 0` quer dizer que não cabe chamada para ação."""
        r = {"elementos": [{"papel": "headline", "zona": "meio-centro", "texto": "Oi"},
                           {"papel": "cta", "zona": "baixo-centro", "texto": "Clique"}]}
        with pytest.raises(RespostaInvalida, match="não leva cta"):
            conferir(r, THUMB)

    def test_descartados_tem_que_ser_dicionario_com_motivo(self):
        r = dict(BOA, descartados=["apoio"])
        with pytest.raises(RespostaInvalida, match="o que saiu e por quê"):
            conferir(r, STORIES)


class TestCaixas:
    """A coordenada é calculada aqui, longe do modelo — que é onde ele erra."""

    @pytest.mark.parametrize("fid", ["ig-stories", "ig-feed-4x5", "gdn-728x90", "yt-thumb"])
    def test_tudo_cai_dentro_da_area_segura(self, fid):
        f = formato_by_id(fid)
        r = {"elementos": [{"papel": "headline", "zona": "meio-esquerda", "texto": "Oi"}]}
        p = montar(conferir(r, f), f, {"tipo": "imagem", "src": "base.png"})
        s = f["safe"]
        for e in p["elementos"]:
            b = e["box"]
            assert b["x"] >= s["left"] and b["y"] >= s["top"]
            assert b["x"] + b["w"] <= f["w"] - s["right"]
            assert b["y"] + b["h"] <= f["h"] - s["bottom"]

    def test_elementos_na_mesma_zona_nao_se_sobrepoem(self):
        r = {"elementos": [{"papel": "headline", "zona": "baixo-esquerda", "texto": "Chegamos"},
                           {"papel": "cta", "zona": "baixo-esquerda", "texto": "Vem"}]}
        p = montar(conferir(r, STORIES), STORIES, {"tipo": "imagem", "src": "base.png"})
        a, b = [e["box"] for e in p["elementos"]]
        assert a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"]

    def test_zona_muda_a_posicao(self):
        def y_de(zona):
            r = {"elementos": [{"papel": "headline", "zona": zona, "texto": "Oi"}]}
            return montar(conferir(r, STORIES), STORIES, {})["elementos"][0]["box"]["y"]
        assert y_de("topo-centro") < y_de("meio-centro") < y_de("baixo-centro")

    def test_o_que_foi_descartado_viaja_com_a_peca(self):
        """Senão a entrega não tem como dizer o que ficou de fora."""
        p = montar(conferir(BOA, STORIES), STORIES, {})
        assert p["descartados"]["apoio"]


class TestCompositorModelo:
    def test_usa_o_que_o_modelo_respondeu(self):
        c = CompositorModelo(lambda instr, arte: BOA, fundo={"tipo": "imagem", "src": "base.png"})
        p = c.compor("base.png", "ig-stories")
        assert [e["papel"] for e in p["elementos"]] == ["headline", "cta"]
        assert p["via"] == "modelo+regra"

    def test_modelo_mudo_nao_derruba_o_job(self):
        def cai(instr, arte):
            raise TimeoutError("o modelo demorou demais")
        c = CompositorModelo(cai, fundo={})
        with pytest.raises(ComposicaoImpossivel, match="não respondeu"):
            c.compor("base.png", "ig-stories")

    def test_resposta_torta_nao_chega_ao_render(self):
        """Insistindo no erro, o compositor recusa a peça em vez de renderizar
        o que o modelo mandou."""
        c = CompositorModelo(lambda i, a: {"elementos": [{"papel": "xpto", "zona": "topo-centro"}]},
                             fundo={})
        with pytest.raises(ComposicaoImpossivel, match="papel desconhecido"):
            c.compor("base.png", "ig-stories")

    def test_a_instrucao_leva_os_limites_do_formato(self):
        t = instrucao(BANNER)
        assert "728x90" in t and "30 caracteres" in t
        assert "apoio não cabe" in t
        assert "descartados" in t


class TestCadeia:
    def test_cai_para_o_proximo_quando_o_primeiro_nao_da_conta(self):
        def recusa(i, a):
            raise RuntimeError("fora do ar")
        cadeia = CompositorEmCadeia(CompositorModelo(recusa, fundo={}),
                                    CompositorSimples("Chegamos a Porto Belo"))
        p = cadeia.compor("base.png", "ig-stories")
        assert p["via"] == "regra-simples"

    def test_quando_nenhum_da_conta_diz_o_motivo_de_cada_um(self):
        def recusa(i, a):
            raise RuntimeError("fora do ar")
        cadeia = CompositorEmCadeia(CompositorModelo(recusa, fundo={}),
                                    CompositorSimples(""))
        with pytest.raises(ComposicaoImpossivel) as e:
            cadeia.compor("base.png", "ig-stories")
        assert "CompositorModelo" in str(e.value) and "CompositorSimples" in str(e.value)


class TestGrupoQueNaoCabe:
    """A faixa nominal nem sempre comporta o grupo. Subir o grupo inteiro é
    certo; espremer cada elemento no limite põe um por cima do outro, e isso só
    apareceria na peça pronta."""

    def test_grupo_grande_na_faixa_de_baixo_sobe_e_nao_sobrepoe(self):
        r = {"elementos": [
            {"papel": "headline", "zona": "baixo-esquerda", "texto": "Chegamos a Porto Belo"},
            {"papel": "apoio", "zona": "baixo-esquerda", "texto": "Faça parte da nossa equipe"},
            {"papel": "cta", "zona": "baixo-esquerda", "texto": "Candidate-se"}]}
        p = montar(conferir(r, STORIES), STORIES, {})
        caixas = sorted((e["box"] for e in p["elementos"]), key=lambda b: b["y"])
        for a, b in zip(caixas, caixas[1:]):
            assert a["y"] + a["h"] <= b["y"], f"{a} sobrepõe {b}"
        s = STORIES["safe"]
        assert caixas[-1]["y"] + caixas[-1]["h"] <= STORIES["h"] - s["bottom"]

    def test_em_formato_baixo_encolhe_em_vez_de_estourar(self):
        # as zonas seguem a convenção da faixa — marca à esquerda, frase no
        # centro, botão à direita — que é o que a diagramação agora exige
        r = {"elementos": [
            {"papel": "marca", "zona": "meio-esquerda", "origem": "logo.png"},
            {"papel": "headline", "zona": "meio-centro", "texto": "Save the date"},
            {"papel": "cta", "zona": "meio-direita", "texto": "Inscreva-se"}]}
        p = montar(conferir(r, BANNER), BANNER, {})
        s = BANNER["safe"]
        for e in p["elementos"]:
            b = e["box"]
            assert b["y"] >= s["top"]
            assert b["y"] + b["h"] <= BANNER["h"] - s["bottom"], f"{e['papel']} estourou"


class TestSegundaChance:
    """Recusar a resposta é certo; desistir na primeira é desperdício. Dizer o
    erro e pedir de novo é o que uma pessoa faria."""

    def test_diz_o_erro_e_aceita_a_correcao(self):
        vistas = []

        def modelo(instr, arte):
            vistas.append(instr)
            if len(vistas) == 1:
                return {"elementos": [{"papel": "headline", "zona": "meio-centro",
                                       "texto": "x" * 200}]}
            return {"elementos": [{"papel": "headline", "zona": "meio-centro",
                                   "texto": "Chegamos"}]}

        c = CompositorModelo(modelo, fundo={})
        p = c.compor("base.png", "ig-stories")
        assert p["elementos"][0]["texto"] == "Chegamos"
        assert "recusada" in vistas[1] and "caracteres" in vistas[1]

    def test_desiste_depois_das_tentativas_e_diz_o_motivo(self):
        c = CompositorModelo(lambda i, a: {"elementos": [{"papel": "headline",
                             "zona": "meio-centro", "texto": "x" * 200}]},
                             fundo={}, tentativas=2)
        with pytest.raises(ComposicaoImpossivel, match="não corrigiu em 2"):
            c.compor("base.png", "ig-stories")

    def test_modelo_mudo_nao_ganha_segunda_chance(self):
        """Erro de transporte não se resolve repetindo o mesmo pedido."""
        chamadas = []

        def cai(i, a):
            chamadas.append(1)
            raise TimeoutError("sem resposta")

        with pytest.raises(ComposicaoImpossivel, match="não respondeu"):
            CompositorModelo(cai, fundo={}, tentativas=3).compor("base.png", "ig-stories")
        assert len(chamadas) == 1


class TestNadaSeSobrepoe:
    """Duas sobreposições passaram pelos testes e só apareceram no render:
    zonas da mesma faixa dividindo a largura, e texto grande demais para a
    caixa que recebeu. Agora as duas têm teste."""

    def caixas(self, peca):
        return [e["box"] for e in peca["elementos"]]

    def cruzam(self, a, b):
        return (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
                and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])

    def test_zonas_da_mesma_faixa_dividem_a_largura(self):
        """"meio-centro" pegava a largura toda e o botão em "meio-direita"
        caía em cima. O banner saiu com os dois escritos um sobre o outro."""
        r = {"elementos": [{"papel": "headline", "zona": "meio-centro", "texto": "Save the date"},
                           {"papel": "cta", "zona": "meio-direita", "texto": "Inscreva-se"}]}
        p = montar(conferir(r, BANNER), BANNER, {})
        a, b = self.caixas(p)
        assert not self.cruzam(a, b), f"{a} cruza {b}"

    @pytest.mark.parametrize("fid", ["ig-stories", "ig-feed-4x5", "gdn-728x90"])
    def test_peca_cheia_nao_tem_elemento_cruzando(self, fid):
        """Em cada formato, a peça cheia na diagramação que o formato pede: a
        faixa espalha na horizontal, as outras descem numa coluna só."""
        from api.diagramacao import e_faixa
        f = formato_by_id(fid)
        if e_faixa(f):
            elems = [{"papel": "headline", "zona": "meio-centro", "texto": "Save the date"},
                     {"papel": "cta", "zona": "meio-direita", "texto": "Quero ir"}]
        else:
            elems = [{"papel": "headline", "zona": "topo-esquerda", "texto": "Save the date"},
                     {"papel": "cta", "zona": "baixo-esquerda", "texto": "Quero ir"}]
            if f["texto"].get("apoio_max"):
                elems.insert(1, {"papel": "apoio", "zona": "meio-esquerda",
                                 "texto": "25 a 27 de novembro"})
        p = montar(conferir({"elementos": elems}, f), f, {})
        cs = self.caixas(p)
        for i, a in enumerate(cs):
            for b in cs[i + 1:]:
                assert not self.cruzam(a, b), f"{fid}: {a} cruza {b}"

    def test_o_corpo_do_texto_cabe_na_caixa(self):
        """Mínimo vindo só do canvas impedia o apoio de encolher: ele
        estourava a caixa e escrevia por cima do vizinho."""
        r = {"elementos": [{"papel": "headline", "zona": "meio-esquerda", "texto": "Save the date"},
                           {"papel": "apoio", "zona": "meio-esquerda",
                            "texto": "25 a 27 de novembro · Guarujá/SP"}]}
        p = montar(conferir(r, STORIES), STORIES, {})
        for e in p["elementos"]:
            assert e["min"] <= e["box"]["h"] * 0.5, f"{e['papel']} não consegue encolher"
            assert e["max"] <= e["box"]["h"] * 0.9, f"{e['papel']} pode estourar a caixa"


class TestFaixasDiferentes:
    """Faixa a faixa, o grupo do meio descia até 80% da altura e o de baixo
    começava em 68% — colidiam. Só apareceu no render; agora tem teste."""

    def cruzam(self, a, b):
        return (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
                and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])

    @pytest.mark.parametrize("fid", ["ig-stories", "ig-feed-4x5", "fb-feed-4x5", "tt-video-capa"])
    def test_grupo_alto_no_meio_nao_invade_o_de_baixo(self, fid):
        f = formato_by_id(fid)
        if not f:
            pytest.skip(f"{fid} não está no catálogo")
        r = {"elementos": [
            {"papel": "headline", "zona": "meio-esquerda", "texto": "Save the date"},
            {"papel": "apoio", "zona": "meio-esquerda", "texto": "25 a 27 de novembro"},
            {"papel": "cta", "zona": "baixo-esquerda", "texto": "Quero ir"}]}
        try:
            p = montar(conferir(r, f), f, {})
        except RespostaInvalida:
            pytest.skip(f"{fid} não comporta esses papéis")
        cs = [e["box"] for e in p["elementos"]]
        for i, a in enumerate(cs):
            for b in cs[i + 1:]:
                assert not self.cruzam(a, b), f"{fid}: {a} cruza {b}"

    def test_tudo_continua_dentro_da_area_segura(self):
        f = formato_by_id("ig-stories")
        r = {"elementos": [
            {"papel": "marca", "zona": "topo-esquerda", "origem": "logo.png"},
            {"papel": "headline", "zona": "meio-esquerda", "texto": "Save the date"},
            {"papel": "apoio", "zona": "meio-esquerda", "texto": "25 a 27 de novembro"},
            {"papel": "cta", "zona": "baixo-esquerda", "texto": "Quero ir"}]}
        p = montar(conferir(r, f), f, {})
        s = f["safe"]
        for e in p["elementos"]:
            b = e["box"]
            assert b["y"] >= s["top"] and b["y"] + b["h"] <= f["h"] - s["bottom"], e["papel"]
