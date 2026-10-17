"""O fundo é montado antes do texto, e o texto só entra onde sobrou espaço.

Tudo aqui vem da primeira rodada real com modelo: a peça saiu com o texto novo
em cima do texto que a arte já tinha impresso, a marca virou um quadro vazio, e
o formato de mesma proporção levou texto que não cabia em lugar nenhum.
"""
import json

import pytest
from PIL import Image

from api.composicao import RespostaInvalida, _aparar, _faixas, conferir
from api.compositor import ComposicaoImpossivel, CompositorSimples, Terreno
from api.fundo import escolher_estrategia, preparar
from api.pipeline import tirar_imagem_fantasma
from motor.replica import formato_by_id


@pytest.fixture
def arte(tmp_path):
    p = tmp_path / "arte.png"
    Image.new("RGB", (1920, 1080), "#0a1a55").save(p)
    return p


class TestEnquadramento:
    def test_mesma_proporcao_nao_estende_nem_corta(self, arte, tmp_path):
        r = preparar(arte, formato_by_id("li-feed-16x9"), (900, 430, 1790, 770),
                     tmp_path / "f.png", modo="solid")
        assert r["cortou"] is False
        assert r["areas_livres"] == {}        # a peça é a arte: nada a acrescentar

    def test_preserva_tudo_enquanto_a_faixa_nao_domina(self, arte, tmp_path):
        r = preparar(arte, formato_by_id("ig-feed-1x1"), (900, 430, 1790, 770),
                     tmp_path / "f.png", modo="solid")
        assert r["enquadramento"] == "contain"
        assert r["cortou"] is False
        assert set(r["areas_livres"]) == {"top", "bottom"}

    def test_reenquadra_quando_preservar_tudo_vira_moldura(self, arte, tmp_path):
        r = preparar(arte, formato_by_id("ig-stories"), (900, 430, 1790, 770),
                     tmp_path / "f.png", modo="solid")
        assert r["enquadramento"] == "smart"
        assert "faixa vazia" in r["porque"]

    def test_a_tinta_nunca_e_cortada(self, arte, tmp_path):
        tinta = (900, 430, 1790, 770)
        for fid in ("ig-stories", "ig-feed-1x1", "gdn-300x600", "a4-retrato"):
            f = formato_by_id(fid)
            r = preparar(arte, f, tinta, tmp_path / f"{fid}.png", modo="solid")
            x0, y0, x1, y1 = r["protect_box"]
            assert x0 >= 0 and y0 >= 0 and x1 <= f["w"] and y1 <= f["h"], fid

    def test_a_tinta_cai_com_respiro_dentro_da_area_segura(self, arte, tmp_path):
        """Caber na área segura não basta: encostada na borda, o app recorta."""
        f = formato_by_id("ig-stories")
        r = preparar(arte, f, (900, 430, 1790, 770), tmp_path / "f.png", modo="solid")
        s = f["safe"]
        x0, y0, x1, y1 = r["protect_box"]
        assert x0 > s["left"] and y0 > s["top"]
        assert x1 < f["w"] - s["right"] and y1 < f["h"] - s["bottom"]

    def test_sem_tinta_nao_quebra(self, arte, tmp_path):
        r = preparar(arte, formato_by_id("ig-feed-1x1"), None, tmp_path / "f.png", modo="solid")
        assert r["protect_box"] is None

    def test_a_escolha_e_pela_faixa_que_sobraria(self):
        qual, porque = escolher_estrategia(1920, 1080, 1080, 1080, (900, 430, 1790, 770))
        assert qual == "contain" and "%" in porque
        qual, _ = escolher_estrategia(1920, 1080, 1080, 1920, (900, 430, 1790, 770))
        assert qual == "smart"


class TestOndeCabeTexto:
    def test_sem_faixa_livre_nada_e_posicionado(self):
        assert _faixas(formato_by_id("li-feed-16x9"), {}) == {}

    def test_faixa_fina_demais_nao_conta(self):
        """No Stories a faixa de cima cai quase toda na margem que o app cobre:
        sobravam 80px úteis e o texto saía com 14px."""
        f = formato_by_id("ig-stories")
        assert _aparar(f, [0, 0, 1080, 464]) is None
        assert _aparar(f, [0, 1176, 1080, 1920]) is not None

    def test_a_zona_sem_faixa_propria_cai_na_que_existe(self):
        """Recusar custaria uma rodada de modelo; empilhar é correto."""
        faixas = _faixas(formato_by_id("ig-feed-1x1"), {"bottom": [0, 700, 1080, 1080]})
        assert faixas["topo-centro"] == faixas["baixo-centro"] == faixas["meio-centro"]

    def test_sem_livres_divide_a_peca_em_tres(self):
        faixas = _faixas(formato_by_id("ig-feed-1x1"))
        assert faixas["topo-centro"][3] <= faixas["meio-centro"][1]
        assert faixas["meio-centro"][3] <= faixas["baixo-centro"][1]

    def test_as_duas_colunas_sao_aproveitadas(self):
        """Ficar só com a maior jogava a outra fora: no leaderboard a direita
        vazia era descartada e o botão acabava espremido no meio do desenho."""
        f = formato_by_id("gdn-728x90")
        faixas = _faixas(f, {"left": [12, 8, 288, 82], "right": [532, 8, 716, 82]})
        assert faixas["meio-esquerda"][0] < 288
        assert faixas["meio-direita"][0] >= 532

    def test_coluna_unica_serve_as_tres_posicoes(self):
        f = formato_by_id("gdn-728x90")
        faixas = _faixas(f, {"left": [12, 8, 288, 82]})
        assert faixas["meio-direita"] == faixas["meio-esquerda"]


class TestNaoRepetirAArte:
    def test_recusa_o_que_ja_esta_impresso(self):
        bruto = {"elementos": [{"papel": "headline", "zona": "baixo-centro",
                                "texto": "Energia que impulsiona o futuro."}],
                 "descartados": {}}
        with pytest.raises(RespostaInvalida, match="já está impresso"):
            conferir(bruto, formato_by_id("ig-feed-1x1"),
                     ["Energia que impulsiona o futuro."])

    def test_a_comparacao_ignora_acento_caixa_e_pontuacao(self):
        bruto = {"elementos": [{"papel": "headline", "zona": "baixo-centro",
                                "texto": "ENERGIA QUE IMPULSIONA O FUTURO"}],
                 "descartados": {}}
        with pytest.raises(RespostaInvalida, match="já está impresso"):
            conferir(bruto, formato_by_id("ig-feed-1x1"),
                     ["Energia que impulsiona o futuro."])

    def test_texto_novo_passa(self):
        bruto = {"elementos": [{"papel": "headline", "zona": "baixo-centro",
                                "texto": "Garanta sua presença"}], "descartados": {}}
        assert conferir(bruto, formato_by_id("ig-feed-1x1"), ["energiza"]).elementos

    def test_marca_e_recusada_quando_a_arte_ja_a_traz(self):
        """Não existe recorte em arquivo: o elemento viraria um quadro vazio."""
        bruto = {"elementos": [
            {"papel": "marca", "zona": "topo-esquerda", "texto": "", "origem": "o lockup da arte"},
            {"papel": "headline", "zona": "baixo-centro", "texto": "Garanta sua presença"}],
            "descartados": {}}
        with pytest.raises(RespostaInvalida, match="já está impressa"):
            conferir(bruto, formato_by_id("ig-stories"), ["CONSIGAZ"])

    def test_resposta_vazia_vale_quando_a_arte_ja_preenche(self):
        """A instrução pede elementos vazios quando não há espaço. Recusar isso
        era contradizer o que foi pedido, e derrubava o formato para a régua."""
        esq = conferir({"elementos": [], "descartados": {"cta": "sem espaço livre"}},
                       formato_by_id("li-feed-16x9"), ["energiza"])
        assert esq.elementos == []

    def test_resposta_vazia_sem_arte_lida_continua_recusada(self):
        with pytest.raises(RespostaInvalida):
            conferir({"elementos": [], "descartados": {}}, formato_by_id("li-feed-16x9"))


class TestAReguaTambemRespeita:
    def test_nao_escreve_quando_nao_sobrou_faixa(self):
        c = CompositorSimples(headline="Energiza", cta="Inscreva-se")
        with pytest.raises(ComposicaoImpossivel, match="reenquadrada"):
            c.compor("base.png", "li-feed-16x9", terreno=Terreno(fundo={}, livres={}))

    def test_usa_a_faixa_quando_ela_existe(self):
        c = CompositorSimples(headline="Energiza")
        t = Terreno(fundo={"tipo": "imagem", "src": "f.png"},
                    livres={"bottom": [0, 700, 1080, 1080]})
        peca = c.compor("base.png", "ig-feed-1x1", terreno=t)
        assert peca["fundo"]["src"] == "f.png"
        assert peca["elementos"][0]["box"]["y"] >= 700

    def test_sem_terreno_compoe_como_antes(self):
        peca = CompositorSimples(headline="Energiza").compor("base.png", "ig-feed-1x1")
        assert peca["elementos"][0]["texto"] == "Energiza"


class TestImagemFantasma:
    def test_tira_a_imagem_que_nao_abre(self, tmp_path):
        peca = {"elementos": [
            {"tipo": "imagem", "papel": "marca", "src": "recorte do lockup da arte"},
            {"tipo": "texto", "papel": "headline", "texto": "oi"}]}
        avisos = tirar_imagem_fantasma(peca, tmp_path)
        assert [e["tipo"] for e in peca["elementos"]] == ["texto"]
        assert "quadro vazio" in avisos[0]

    def test_mantem_a_imagem_que_existe(self, tmp_path):
        (tmp_path / "logo.png").write_bytes(b"x")
        peca = {"elementos": [{"tipo": "imagem", "papel": "marca", "src": "logo.png"}]}
        assert tirar_imagem_fantasma(peca, tmp_path) == []
        assert len(peca["elementos"]) == 1


class TestEspacoLivre:
    def test_o_proibido_e_a_tinta_e_nao_a_arte(self):
        """Texto sobre gradiente é desenho; texto sobre texto é defeito. A
        primeira versão proibia a arte inteira e o Stories saiu mudo."""
        from api.fundo import espaco_livre
        f = formato_by_id("ig-stories")
        faixas = espaco_livre(f, [132, 859, 964, 1176])
        assert set(faixas) == {"top", "bottom"}
        assert faixas["top"][3] < 859 and faixas["bottom"][1] > 1176

    def test_as_faixas_ficam_dentro_da_area_segura(self):
        from api.fundo import espaco_livre
        f = formato_by_id("ig-stories")
        s = f["safe"]
        for r in espaco_livre(f, [132, 859, 964, 1176]).values():
            assert r[0] >= s["left"] and r[1] >= s["top"]
            assert r[2] <= f["w"] - s["right"] and r[3] <= f["h"] - s["bottom"]

    def test_sem_tinta_a_peca_toda_vale(self):
        from api.fundo import espaco_livre
        assert set(espaco_livre(formato_by_id("ig-feed-1x1"), None)) == {"bottom"}

    def test_tinta_atravessando_sobra_a_lateral(self):
        from api.fundo import espaco_livre
        f = formato_by_id("ig-feed-1x1")
        faixas = espaco_livre(f, [600, 0, 1080, 1080])
        assert "left" in faixas and faixas["left"][2] < 600


class TestNaoInventarTexto:
    def test_frase_que_ninguem_pediu_e_recusada(self):
        bruto = {"elementos": [{"papel": "headline", "zona": "baixo-centro",
                                "texto": "Vem aí o grande encontro do ano"}],
                 "descartados": {}}
        with pytest.raises(RespostaInvalida, match="não invente|Não invente"):
            conferir(bruto, formato_by_id("ig-feed-1x1"), (),
                     material="Energiza Inscreva-se")

    def test_encurtar_o_que_foi_dado_continua_valendo(self):
        bruto = {"elementos": [{"papel": "cta", "zona": "baixo-centro",
                                "texto": "Inscreva-se"}],
                 "descartados": {}}
        esq = conferir(bruto, formato_by_id("ig-feed-1x1"), ["energiza"],
                       material="Energiza Inscreva-se agora no site")
        assert esq.elementos[0].texto == "Inscreva-se"

    def test_sem_material_declarado_nao_barra_nada(self):
        """Trabalho antigo, sem material: a conferência não pode travar."""
        bruto = {"elementos": [{"papel": "headline", "zona": "baixo-centro",
                                "texto": "qualquer coisa"}], "descartados": {}}
        assert conferir(bruto, formato_by_id("ig-feed-1x1")).elementos


class TestHierarquia:
    def test_o_cta_sai_como_botao_com_fundo(self):
        """Sem contraste o CTA some: foi o 'cta minúsculo com zero destaque'."""
        from api.composicao import Esquema, Elemento, montar
        esq = Esquema([Elemento("cta", "baixo-centro", "Inscreva-se")], {})
        peca = montar(esq, formato_by_id("ig-feed-1x1"), {"tipo": "cor", "cor": "#000"},
                      [{"familia": "PecaSans", "arquivo": "f.ttf"}])
        cta = peca["elementos"][0]
        assert cta["tipo"] == "botao"
        assert cta["fundo"] == "#ffffff" and cta["raio"] > 0
        assert cta["fonte"] == "PecaSans"

    def test_o_texto_usa_a_fonte_declarada(self):
        from api.composicao import Esquema, Elemento, montar
        esq = Esquema([Elemento("headline", "baixo-centro", "Energiza")], {})
        peca = montar(esq, formato_by_id("ig-feed-1x1"), {"tipo": "cor", "cor": "#000"},
                      [{"familia": "PecaSans", "arquivo": "f.ttf"}])
        assert peca["elementos"][0]["fonte"] == "PecaSans"

    def test_sem_fonte_declarada_nao_inventa_familia(self):
        from api.composicao import Esquema, Elemento, montar
        esq = Esquema([Elemento("headline", "baixo-centro", "Energiza")], {})
        peca = montar(esq, formato_by_id("ig-feed-1x1"), {"tipo": "cor", "cor": "#000"})
        assert "fonte" not in peca["elementos"][0]


class TestBotao:
    def _cta(self, fid, zona, texto="Inscreva-se"):
        from api.composicao import Elemento, Esquema, montar
        esq = Esquema([Elemento("cta", zona, texto)], {})
        peca = montar(esq, formato_by_id(fid), {"tipo": "cor", "cor": "#000"})
        return peca["elementos"][0], formato_by_id(fid)

    def test_abraca_o_texto_em_vez_de_atravessar_a_peca(self):
        """Herdando a caixa da coluna, o botão saía como barra branca de ponta
        a ponta com a letra minúscula no meio."""
        cta, f = self._cta("li-feed-16x9", "baixo-centro")
        assert cta["box"]["w"] < f["w"] * 0.5
        assert cta["box"]["h"] >= cta["tamanho"] * 2

    def test_texto_mais_longo_pede_botao_mais_largo(self):
        curto, _ = self._cta("ig-feed-1x1", "baixo-centro", "Vem")
        longo, _ = self._cta("ig-feed-1x1", "baixo-centro", "Inscreva-se agora")
        assert longo["box"]["w"] > curto["box"]["w"]

    def test_o_raio_acompanha_a_altura(self):
        cta, _ = self._cta("ig-feed-1x1", "baixo-centro")
        assert cta["raio"] == round(cta["box"]["h"] / 2)

    def test_centraliza_na_zona_centro_e_encosta_na_direita(self):
        meio, f = self._cta("ig-feed-1x1", "baixo-centro")
        dir_, _ = self._cta("ig-feed-1x1", "baixo-direita")
        assert dir_["box"]["x"] > meio["box"]["x"]


class TestOcupacaoDaFaixa:
    def test_um_elemento_sozinho_nao_boia_na_faixa(self):
        """Os pesos valem para a peça inteira. Numa faixa com um elemento só,
        o CTA saía com 27px de corpo numa faixa de 366."""
        from api.composicao import PESO, _alturas
        alt = _alturas(["cta"], 366, 20)[0]
        assert alt > 366 * PESO["cta"][0] * 1.5

    def test_quando_nao_cabe_continua_encolhendo(self):
        """Encolhe até o piso de 14px, que é onde o texto ainda se lê. Abaixo
        disso não há o que fazer: a faixa não comporta tantos papéis."""
        from api.composicao import PESO, _alturas
        papeis = ["headline", "apoio", "cta", "selo", "marca"]
        alt = _alturas(papeis, 200, 20)
        assert all(a >= 14 for a in alt)
        assert all(a <= round(200 * PESO[p][0]) for p, a in zip(papeis, alt))

    def test_o_crescimento_para_na_ocupacao_da_faixa(self):
        """Quem segura o tamanho do texto é o `max` de cada papel, não a caixa."""
        from api.composicao import OCUPACAO, _alturas
        assert _alturas(["selo"], 2000, 20)[0] <= round(2000 * OCUPACAO)

    def test_o_botao_fica_legivel_numa_faixa_estreita(self):
        from api.composicao import Elemento, Esquema, montar
        esq = Esquema([Elemento("cta", "baixo-centro", "Inscreva-se")], {})
        f = formato_by_id("ig-stories")
        peca = montar(esq, f, {"tipo": "cor", "cor": "#000"},
                      livres={"bottom": [64, 1214, 1016, 1580]})
        cta = peca["elementos"][0]
        assert cta["tamanho"] >= round(f["h"] * 0.020)


class TestModoDoFundo:
    def test_o_ambiente_escolhe_o_modo(self, arte, tmp_path, monkeypatch):
        """Generativo custa e demora. Quem roda decide se vale nesta peça."""
        monkeypatch.setenv("REPLICAI_FUNDO", "stretch")
        r = preparar(arte, formato_by_id("ig-feed-1x1"), (900, 430, 1790, 770),
                     tmp_path / "f.png")
        assert r["modo"] == "stretch"

    def test_o_modo_pedido_na_chamada_vence_o_ambiente(self, arte, tmp_path, monkeypatch):
        monkeypatch.setenv("REPLICAI_FUNDO", "stretch")
        r = preparar(arte, formato_by_id("ig-feed-1x1"), (900, 430, 1790, 770),
                     tmp_path / "f.png", modo="solid")
        assert r["modo"] == "solid"


class TestOQueFicouDeFora:
    def test_o_descartado_chega_na_entrega(self, tmp_path, monkeypatch):
        """O modelo explica cada coisa que deixou de fora, e é por aí que se
        descobre que o brief não deu material para a headline. Guardar sem
        mostrar é o erro de sempre."""
        import api.pipeline as pl
        from api.pipeline import desdobrar
        monkeypatch.setattr(pl, "render_peca", lambda a, d: d.write_bytes(b"x"))
        base = tmp_path / "base.png"
        Image.new("RGB", (64, 64), "red").save(base)

        class Diz:
            def compor(self, base, formato_id, brief="", terreno=None):
                return {"w": 10, "h": 10, "fundo": {"tipo": "cor", "cor": "#000"},
                        "elementos": [], "saida": f"{formato_id}.png",
                        "descartados": {"apoio": "o brief não deu material"}}

        r = desdobrar(base, ["ig-stories"], Diz(), tmp_path / "job")
        assert r.descartados["ig-stories"]["apoio"] == "o brief não deu material"
        assert "descartados" in r.para_json()


class TestQuandoOGenerativoNaoVem:
    def test_a_peca_sai_dizendo_que_o_fundo_caiu(self, arte, tmp_path, monkeypatch):
        """O motor esperava 30 minutos pelo generativo sem dar sinal de vida.
        Agora tem prazo — e a queda aparece, porque queda calada foi o defeito
        que entregou peça de régua com cara de peça do modelo."""
        import api.fundo as fu
        monkeypatch.setattr(fu, "_continuar", lambda base, ex, espera: (None, "não respondeu em 180s"))
        r = preparar(arte, formato_by_id("ig-feed-1x1"), (900, 430, 1790, 770),
                     tmp_path / "f.png", modo="outpaint")
        assert r["modo"] == "solid"
        assert "não respondeu" in r["caiu_para"]
        assert r["caminho"].exists()           # a peça sai mesmo assim

    def test_quando_vem_nao_ha_queda(self, arte, tmp_path, monkeypatch):
        from PIL import Image as Im
        import api.fundo as fu
        monkeypatch.setattr(fu, "_continuar",
                            lambda base, ex, espera: (Im.new("RGB", (
                                base.width + ex["left"] + ex["right"],
                                base.height + ex["top"] + ex["bottom"]), "#123456"), ""))
        r = preparar(arte, formato_by_id("ig-feed-1x1"), (900, 430, 1790, 770),
                     tmp_path / "f.png", modo="outpaint")
        assert r["modo"] == "outpaint" and r["caiu_para"] == ""

    def test_a_queda_chega_na_entrega(self, arte, tmp_path, monkeypatch):
        monkeypatch.setenv("REPLICAI_FUNDO", "outpaint")   # `_continuar` está trocado
        import api.fundo as fu
        import api.pipeline as pl
        from api.leitura import Leitura
        from api.pipeline import desdobrar
        monkeypatch.setattr(fu, "_continuar", lambda base, ex, espera: (None, "não respondeu em 180s"))
        monkeypatch.setattr(pl, "render_peca", lambda a, d: d.write_bytes(b"x"))

        class Serve:
            def compor(self, base, formato_id, brief="", terreno=None):
                return {"canvas": {"w": 1080, "h": 1080}, "fundo": terreno.fundo,
                        "elementos": [], "saida": f"{formato_id}.png"}

        r = desdobrar(arte, ["ig-feed-1x1"], Serve(), tmp_path / "job",
                      leitor=lambda a: Leitura(True, (0.47, 0.4, 0.46, 0.31), []))
        assert any("bloco de cor" in a for a in r.avisos["ig-feed-1x1"])


class TestAlinharPelaArte:
    """A régua é a borda da arte, não a margem da peça. Alinhar pela margem
    deixava o botão 22px adiante do "2027" — perto o bastante para parecer
    erro, longe o bastante para não ser alinhamento."""

    def peca(self, zona, tinta, papel="cta", texto="Inscreva-se"):
        from api.composicao import Elemento, Esquema, montar
        esq = Esquema([Elemento(papel, zona, texto)], {})
        return montar(esq, formato_by_id("ig-feed-1x1"), {"tipo": "cor", "cor": "#000"},
                      livres={"bottom": [0, 700, 1080, 1080]}, tinta=tinta)

    def test_o_botao_fecha_com_a_borda_da_tinta(self):
        tinta = [507, 479, 1010, 670]
        b = self.peca("baixo-direita", tinta)["elementos"][0]["box"]
        assert b["x"] + b["w"] == 1010

    def test_sem_tinta_fecha_na_margem_da_peca(self):
        f = formato_by_id("ig-feed-1x1")
        b = self.peca("baixo-direita", None)["elementos"][0]["box"]
        assert b["x"] + b["w"] > f["w"] - f["safe"]["right"] - 60

    def test_a_esquerda_abre_na_borda_da_tinta(self):
        el = self.peca("baixo-esquerda", [300, 479, 1010, 670], papel="headline",
                       texto="Oi")["elementos"][0]
        assert el["box"]["x"] == 300

    def test_nao_encosta_se_sobrar_coluna_estreita_demais(self):
        """Coluna de jornal não é alinhamento."""
        el = self.peca("baixo-direita", [0, 479, 180, 670], papel="headline",
                       texto="Oi")["elementos"][0]
        assert el["box"]["x"] + el["box"]["w"] > 180

    def test_a_zona_direita_alinha_o_texto_a_direita(self):
        """A caixa ia para a direita e o texto ficava encostado na borda
        errada dela."""
        el = self.peca("baixo-direita", None, papel="headline", texto="Oi")["elementos"][0]
        assert el["align"] == "right"

    def test_a_zona_esquerda_alinha_a_esquerda(self):
        el = self.peca("baixo-esquerda", None, papel="headline", texto="Oi")["elementos"][0]
        assert el["align"] == "left"


class TestOGenerativoInventando:
    """O generativo continua bem gradiente, grade e pontilhado. O que ele às
    vezes faz de errado é repetir um elemento marcante — numa peça real criou
    um segundo risco de luz, que não existe no KV e lê como erro."""

    def fundo_com(self, tmp_path, risco_em=None, nome="f.png"):
        from PIL import ImageDraw
        im = Image.new("RGB", (400, 600), "#0a1a55")
        d = ImageDraw.Draw(im)
        # o risco da arte fica dentro da faixa vizinha do rodapé: é com ela que
        # a extensão é comparada, e sem nada com que comparar a conferência
        # pula, que é o certo
        d.rectangle((0, 380, 400, 386), fill="#66ccff")
        if risco_em is not None:
            d.rectangle((0, risco_em, 400, risco_em + 10), fill="#ffffff")
        im.save(tmp_path / nome)
        return tmp_path / nome

    def test_acusa_traco_que_a_arte_nao_tem(self, tmp_path):
        from api.fundo import inventou_estrutura
        f = self.fundo_com(tmp_path, risco_em=520)
        avisos = inventou_estrutura(f, [0, 150, 400, 450])
        assert avisos and "rodapé" in avisos[0], "não diz onde olhar"
        assert "Refaça o fundo desta peça" in avisos[0], "não diz o que fazer"

    def test_extensao_calma_passa(self, tmp_path):
        from api.fundo import inventou_estrutura
        f = self.fundo_com(tmp_path)
        assert inventou_estrutura(f, [0, 150, 400, 450]) == []

    def test_nao_despeja_a_medicao_na_ressalva(self, tmp_path):
        """"Linha 520, 4.1x mais marcado que a arte ao lado" é a conta da
        régua, não informação para quem publica: ela não abre a peça num
        editor de pixel para ir até a linha 520. A ressalva diz onde e o que
        fazer; o número fica no log."""
        from api.fundo import inventou_estrutura
        f = self.fundo_com(tmp_path, risco_em=520)
        aviso = inventou_estrutura(f, [0, 150, 400, 450])[0]
        assert "linha" not in aviso and "x mais" not in aviso
        assert len(aviso) < 110, f"ressalva de {len(aviso)} caracteres: {aviso}"

    def test_sem_arte_com_que_comparar_nao_acusa(self, tmp_path):
        """Faixa vizinha lisa não dá régua: acusar ali seria chute."""
        from PIL import ImageDraw
        from api.fundo import inventou_estrutura
        im = Image.new("RGB", (400, 600), "#0a1a55")
        ImageDraw.Draw(im).rectangle((0, 520, 400, 530), fill="#ffffff")
        im.save(tmp_path / "liso.png")
        assert inventou_estrutura(tmp_path / "liso.png", [0, 150, 400, 450]) == []

    def test_sem_extensao_nao_ha_o_que_conferir(self, tmp_path):
        from api.fundo import inventou_estrutura
        f = self.fundo_com(tmp_path)
        assert inventou_estrutura(f, [0, 0, 400, 600]) == []

    def test_arquivo_que_nao_existe_nao_quebra(self, tmp_path):
        from api.fundo import inventou_estrutura
        assert inventou_estrutura(tmp_path / "nao-existe.png", [0, 10, 100, 90]) == []

    def test_o_aviso_chega_na_entrega(self, arte, tmp_path, monkeypatch):
        """Escrever a conferência e não mostrar é o erro de sempre."""
        import api.fundo as fu
        import api.pipeline as pl
        from api.leitura import Leitura as L
        from api.pipeline import desdobrar
        monkeypatch.setattr(fu, "inventou_estrutura", lambda *a: ["inventou um traço forte"])
        monkeypatch.setattr(pl, "render_peca", lambda a, d: d.write_bytes(b"x"))

        class Serve:
            def compor(self, base, formato_id, brief="", terreno=None):
                return {"canvas": {"w": 1080, "h": 1080}, "fundo": terreno.fundo,
                        "elementos": [], "saida": f"{formato_id}.png"}

        r = desdobrar(arte, ["ig-feed-1x1"], Serve(), tmp_path / "job",
                      leitor=lambda a: L(True, (0.47, 0.4, 0.46, 0.31), []))
        assert any("traço forte" in a for a in r.avisos["ig-feed-1x1"])


class TestInsistirComOGenerativo:
    """Acusar o traço inventado não conserta a peça. Como o generativo é
    estocástico, insistir resolve na maior parte das vezes — mas custa uma
    chamada a mais do item mais caro, então só vale na exportação final."""

    def test_repete_ate_sair_limpo(self, arte, tmp_path, monkeypatch):
        from PIL import Image as Im
        import api.fundo as fu
        tentativas = []

        def continua(base, ex, espera):
            tentativas.append(1)
            alvo = (base.width + ex["left"] + ex["right"],
                    base.height + ex["top"] + ex["bottom"])
            return Im.new("RGB", alvo, "#0a1a55"), ""

        monkeypatch.setattr(fu, "_continuar", continua)
        sujas = [1]

        def confere(caminho, caixa):
            return ["inventou"] if sujas and sujas.pop() else []

        monkeypatch.setattr(fu, "inventou_estrutura", confere)
        r = fu.preparar(arte, formato_by_id("ig-feed-1x1"), (900, 430, 1790, 770),
                        tmp_path / "f.png", modo="outpaint", insistir=True)
        assert len(tentativas) == 2            # insistiu e a segunda saiu limpa
        assert r["avisos"] == []

    def test_desiste_depois_do_limite_e_avisa(self, arte, tmp_path, monkeypatch):
        from PIL import Image as Im
        import api.fundo as fu
        tentativas = []

        def continua(base, ex, espera):
            tentativas.append(1)
            alvo = (base.width + ex["left"] + ex["right"],
                    base.height + ex["top"] + ex["bottom"])
            return Im.new("RGB", alvo, "#0a1a55"), ""

        monkeypatch.setattr(fu, "_continuar", continua)
        monkeypatch.setattr(fu, "inventou_estrutura", lambda *a: ["inventou"])
        r = fu.preparar(arte, formato_by_id("ig-feed-1x1"), (900, 430, 1790, 770),
                        tmp_path / "f.png", modo="outpaint", insistir=True)
        assert len(tentativas) == fu.TENTATIVAS
        assert r["avisos"]                     # a peça sai, com a ressalva

    def test_generativo_que_nao_responde_nao_vira_duas_esperas(self, arte, tmp_path,
                                                               monkeypatch):
        """Insistir é para quando ele responde mal, não para quando não
        responde: repetir o tempo de espera dobraria a fila."""
        import api.fundo as fu
        tentativas = []
        monkeypatch.setattr(fu, "_continuar",
                            lambda *a: (tentativas.append(1), (None, "não respondeu"))[1])
        r = fu.preparar(arte, formato_by_id("ig-feed-1x1"), (900, 430, 1790, 770),
                        tmp_path / "f.png", modo="outpaint")
        assert len(tentativas) == 1 and r["modo"] == "solid"


class TestCentralizarPelaArte:
    def test_o_centro_e_o_da_arte_e_nao_o_da_peca(self):
        """CTA centralizado no canvas fica solto ao lado do lockup em vez de
        pendurado nele."""
        from api.composicao import Elemento, Esquema, montar
        f = formato_by_id("ig-feed-1x1")
        tinta = [120, 400, 620, 600]          # lockup à esquerda do centro
        esq = Esquema([Elemento("cta", "baixo-centro", "Inscreva-se")], {})
        peca = montar(esq, f, {"tipo": "cor", "cor": "#000"},
                      livres={"bottom": [0, 700, 1080, 1080]}, tinta=tinta)
        b = peca["elementos"][0]["box"]
        meio_do_botao = b["x"] + b["w"] / 2
        assert abs(meio_do_botao - 370) < 30   # centro do lockup, não 540

    def test_sem_tinta_centraliza_na_peca(self):
        from api.composicao import Elemento, Esquema, montar
        f = formato_by_id("ig-feed-1x1")
        esq = Esquema([Elemento("cta", "baixo-centro", "Inscreva-se")], {})
        peca = montar(esq, f, {"tipo": "cor", "cor": "#000"},
                      livres={"bottom": [0, 700, 1080, 1080]})
        b = peca["elementos"][0]["box"]
        assert abs((b["x"] + b["w"] / 2) - 540) < 30


class TestRascunhoEFinal:
    """Chamada de generativo é o item mais caro da peça. Refazer a cada
    rascunho é queimar margem numa versão que ainda vai mudar."""

    def caro(self, monkeypatch, sujo=True):
        from PIL import Image as Im
        import api.fundo as fu
        gastos = []

        def continua(base, ex, espera):
            gastos.append(1)
            alvo = (base.width + ex["left"] + ex["right"],
                    base.height + ex["top"] + ex["bottom"])
            return Im.new("RGB", alvo, "#0a1a55"), ""

        monkeypatch.setattr(fu, "_continuar", continua)
        monkeypatch.setattr(fu, "inventou_estrutura",
                            lambda *a: ["inventou"] if sujo else [])
        return gastos

    def test_rascunho_pede_uma_vez_so(self, arte, tmp_path, monkeypatch):
        import api.fundo as fu
        gastos = self.caro(monkeypatch)
        r = fu.preparar(arte, formato_by_id("ig-feed-1x1"), (900, 430, 1790, 770),
                        tmp_path / "f.png", modo="outpaint")
        assert len(gastos) == 1 and r["generativo"] == 1
        assert r["avisos"]                      # sai com o defeito e com o aviso

    def test_final_insiste(self, arte, tmp_path, monkeypatch):
        import api.fundo as fu
        gastos = self.caro(monkeypatch)
        fu.preparar(arte, formato_by_id("ig-feed-1x1"), (900, 430, 1790, 770),
                    tmp_path / "f.png", modo="outpaint", insistir=True)
        assert len(gastos) == fu.TENTATIVAS

    def test_o_fundo_limpo_e_reaproveitado_na_final(self, arte, tmp_path, monkeypatch):
        """Só o que saiu com defeito é refeito: o resto já serve."""
        import api.fundo as fu
        gastos = self.caro(monkeypatch, sujo=False)
        alvo = tmp_path / "f.png"
        fu.preparar(arte, formato_by_id("ig-feed-1x1"), (900, 430, 1790, 770), alvo,
                    modo="outpaint")
        assert len(gastos) == 1
        r = fu.preparar(arte, formato_by_id("ig-feed-1x1"), (900, 430, 1790, 770), alvo,
                        modo="outpaint", insistir=True, reaproveitar=True)
        assert len(gastos) == 1                 # não pediu de novo
        assert r["reaproveitado"] is True and r["generativo"] == 0
        assert r["base_box"] and r["areas_livres"] is not None

    def test_o_fundo_sujo_e_refeito_na_final(self, arte, tmp_path, monkeypatch):
        import api.fundo as fu
        gastos = self.caro(monkeypatch, sujo=True)
        alvo = tmp_path / "f.png"
        fu.preparar(arte, formato_by_id("ig-feed-1x1"), (900, 430, 1790, 770), alvo,
                    modo="outpaint")
        fu.preparar(arte, formato_by_id("ig-feed-1x1"), (900, 430, 1790, 770), alvo,
                    modo="outpaint", insistir=True, reaproveitar=True)
        assert len(gastos) > 1

    def test_plano_diferente_nao_reaproveita(self, arte, tmp_path, monkeypatch):
        """Outro formato é outro recorte: reaproveitar daria a peça errada."""
        import api.fundo as fu
        gastos = self.caro(monkeypatch, sujo=False)
        alvo = tmp_path / "f.png"
        fu.preparar(arte, formato_by_id("ig-feed-1x1"), (900, 430, 1790, 770), alvo,
                    modo="outpaint")
        fu.preparar(arte, formato_by_id("ig-stories"), (900, 430, 1790, 770), alvo,
                    modo="outpaint", insistir=True, reaproveitar=True)
        assert len(gastos) == 2

    def test_o_rascunho_avisa_que_a_final_refaz(self, arte, tmp_path, monkeypatch):
        import api.fundo as fu
        import api.pipeline as pl
        from api.leitura import Leitura as L
        from api.pipeline import desdobrar
        self.caro(monkeypatch)
        monkeypatch.setenv("REPLICAI_FUNDO", "outpaint")
        monkeypatch.setattr(pl, "render_peca", lambda a, d: d.write_bytes(b"x"))

        class Serve:
            def compor(self, base, formato_id, brief="", terreno=None):
                return {"canvas": {"w": 1080, "h": 1080}, "fundo": terreno.fundo,
                        "elementos": [], "saida": f"{formato_id}.png"}

        r = desdobrar(arte, ["ig-feed-1x1"], Serve(), tmp_path / "job",
                      leitor=lambda a: L(True, (0.47, 0.4, 0.46, 0.31), []))
        assert any("exportação final" in a for a in r.avisos["ig-feed-1x1"])


class TestCorAbsurdaEDescartada:
    """O generativo devolveu uma faixa magenta a 230 da paleta de um KV azul e
    a peça foi entregue "com ressalva". Ninguém publica isso: entregar com
    aviso é só empurrar o problema para quem está com pressa.

    Daqui para cima o fundo generativo é jogado fora e o determinístico assume
    — ele erra para o lado da arte, que é o lado certo de errar.
    """

    def _arte(self, tmp_path):
        from PIL import Image
        a = tmp_path / "arte.png"
        Image.new("RGB", (1200, 1200), (0, 90, 200)).save(a)
        return a

    def _formato(self, w=1080, h=1920):
        return {"id": "ig-stories", "w": w, "h": h,
                "safe": {"top": 250, "bottom": 340, "left": 60, "right": 60}}

    def test_a_faixa_magenta_nao_e_entregue(self, tmp_path, monkeypatch):
        from PIL import Image

        from api import fundo as pf

        def generativo_ruim(base, ex, *a, **k):
            """O que o serviço devolveu de verdade: a arte no meio, magenta em
            volta."""
            tela = Image.new("RGB", (base.width + ex["left"] + ex["right"],
                                     base.height + ex["top"] + ex["bottom"]),
                             (230, 0, 140))
            tela.paste(base, (ex["left"], ex["top"]))
            return tela, "", 1

        monkeypatch.setattr(pf, "_melhor_continuacao", generativo_ruim)
        arte = self._arte(tmp_path)
        info = pf.preparar(arte, self._formato(), [0, 0, 1200, 1200],
                           tmp_path / "fundo-ig-stories.png", modo="outpaint")
        assert info["modo"] == "stretch", "o fundo magenta foi entregue"
        assert "descartado" in info["caiu_para"]

    def test_o_que_sobrou_e_a_cor_da_arte(self, tmp_path, monkeypatch):
        import numpy as np
        from PIL import Image

        from api import fundo as pf
        monkeypatch.setattr(pf, "_melhor_continuacao", lambda base, ex, *a, **k: (
            (lambda tela: (tela.paste(base, (ex["left"], ex["top"])), tela)[1])(
                Image.new("RGB", (base.width + ex["left"] + ex["right"],
                                  base.height + ex["top"] + ex["bottom"]), (230, 0, 140))),
            "", 1))
        arte = self._arte(tmp_path)
        pf.preparar(arte, self._formato(), [0, 0, 1200, 1200],
                    tmp_path / "f.png", modo="outpaint")
        with Image.open(tmp_path / "f.png") as im:
            topo = np.asarray(im.convert("RGB").crop((0, 0, im.width, 40)), dtype=float)
        assert topo[..., 2].mean() > topo[..., 0].mean(), "o topo não ficou azul"

    def test_cor_so_um_pouco_fora_segue_entregue_com_aviso(self, tmp_path, monkeypatch):
        """A régua de recusa é alta de propósito: fundo generativo quase certo
        continua valendo mais do que esticar a arte."""
        from PIL import Image

        from api import fundo as pf

        def quase(base, ex, *a, **k):
            tela = Image.new("RGB", (base.width + ex["left"] + ex["right"],
                                     base.height + ex["top"] + ex["bottom"]),
                             (0, 120, 160))      # azul vizinho, não outra peça
            tela.paste(base, (ex["left"], ex["top"]))
            return tela, "", 1

        monkeypatch.setattr(pf, "_melhor_continuacao", quase)
        info = pf.preparar(self._arte(tmp_path), self._formato(), [0, 0, 1200, 1200],
                           tmp_path / "f.png", modo="outpaint")
        assert info["modo"] == "outpaint"

    def test_a_regua_do_aviso_continua_valendo(self, tmp_path):
        """Recusar é o segundo degrau; o primeiro, de avisar, não sai."""
        from api.fundo import COR_ESTRANHA, COR_RECUSADA
        assert COR_RECUSADA > COR_ESTRANHA


class TestAManchaQueAMedianaEscondia:
    """O 970x250 do Energiza saiu com faixa magenta nas laterais, e a régua de
    cor mediu 25 — abaixo até do limite de aviso. Um quarto da faixa estava a
    180 da paleta.

    A mediana diz o pixel típico, e o defeito do generativo não é típico: ele
    devolve um canto inteiro noutra cor. Perguntar só "como é a faixa em geral"
    deixa passar exatamente o caso que a régua existe para pegar.
    """

    def _arte(self, tmp_path):
        a = tmp_path / "arte.png"
        Image.new("RGB", (1200, 1200), (0, 90, 200)).save(a)
        return a

    def _formato(self):
        return {"id": "gdn-970x250", "w": 970, "h": 250,
                "safe": {"top": 10, "bottom": 10, "left": 12, "right": 12}}

    def _generativo(self, quanto: float):
        """Devolve a arte com um canto da faixa em magenta — `quanto` dela."""
        def fazer(base, ex, *a, **k):
            tela = Image.new("RGB", (base.width + ex["left"] + ex["right"],
                                     base.height + ex["top"] + ex["bottom"]),
                             (0, 90, 200))
            if ex["left"]:
                mancha = Image.new("RGB", (max(1, round(ex["left"] * quanto)),
                                           tela.height), (230, 0, 140))
                tela.paste(mancha, (0, 0))
            tela.paste(base, (ex["left"], ex["top"]))
            return tela, "", 1
        return fazer

    def test_um_quarto_da_faixa_manchado_e_descartado(self, tmp_path, monkeypatch):
        from api import fundo as pf
        monkeypatch.setattr(pf, "_melhor_continuacao", self._generativo(0.30))
        info = pf.preparar(self._arte(tmp_path), self._formato(), [0, 0, 1200, 1200],
                           tmp_path / "f.png", modo="outpaint")
        assert info["modo"] == "stretch", "a mancha foi entregue"
        assert "mancha de cor estranha" in info["caiu_para"]

    def test_a_mediana_sozinha_nao_pegava(self, tmp_path, monkeypatch):
        """O buraco, medido: na mesma faixa o número antigo fica abaixo até do
        limite de AVISO, e o novo passa do de descarte."""
        from api import fundo as pf
        arte = self._arte(tmp_path)
        f = self._formato()
        manchado = tmp_path / "manchado.png"
        with Image.open(arte) as im:
            base = im.convert("RGB").resize((444, 250))
        tela = Image.new("RGB", (f["w"], f["h"]), (0, 90, 200))
        tela.paste(Image.new("RGB", (80, f["h"]), (230, 0, 140)), (0, 0))
        tela.paste(base, (263, 0))
        tela.save(manchado)
        with Image.open(arte) as im:
            medidas = pf.medidas_de_cor(manchado, [263, 0, 707, 250], im)
        tipico, mancha = medidas["esquerda"]
        assert tipico < pf.COR_ESTRANHA, "a mediana teria avisado, e não avisava"
        assert mancha >= pf.MANCHA, "a mancha não foi vista"

    def test_um_respingo_nao_derruba_o_fundo(self, tmp_path, monkeypatch):
        """A régua é alta de propósito: fundo generativo quase certo vale mais
        do que esticar a arte. Respingo vira aviso, não descarte."""
        from api import fundo as pf
        monkeypatch.setattr(pf, "_melhor_continuacao", self._generativo(0.04))
        info = pf.preparar(self._arte(tmp_path), self._formato(), [0, 0, 1200, 1200],
                           tmp_path / "f.png", modo="outpaint")
        assert info["modo"] == "outpaint"

    def test_a_medida_do_tipico_continua_existindo(self, tmp_path, monkeypatch):
        """Ela é o número que vira aviso, e não some por causa da mancha."""
        from api import fundo as pf
        monkeypatch.setattr(pf, "_melhor_continuacao", self._generativo(0.04))
        pf.preparar(self._arte(tmp_path), self._formato(), [0, 0, 1200, 1200],
                    tmp_path / "f.png", modo="outpaint")
        with Image.open(self._arte(tmp_path)) as arte:
            d = pf.distancias_de_cor(tmp_path / "f.png", [0, 0, 970, 250], arte)
        assert all(isinstance(v, float) for v in d.values())


class TestNaoPedirOQueNaoPrecisa:
    """O recorte que já enche a peça não tem o que estender — e ainda assim
    gastava uma chamada do generativo. Quando ela falhava, a peça saía com uma
    ressalva sobre um fundo que ninguém tinha pedido."""

    def test_sem_extensao_o_generativo_nao_e_chamado(self, arte, tmp_path, monkeypatch):
        from api import fundo as pf

        def explode(*a, **k):
            raise AssertionError("pediu continuação sem ter o que continuar")

        monkeypatch.setattr(pf, "_melhor_continuacao", explode)
        info = pf.preparar(arte, formato_by_id("gdn-728x90"), None,
                           tmp_path / "f.png", estrategia="cover", modo="outpaint")
        assert info["generativo"] == 0
        assert info["caiu_para"] == ""

    def test_com_extensao_ele_continua_sendo_chamado(self, arte, tmp_path, monkeypatch):
        from PIL import Image

        from api import fundo as pf
        chamou = []

        def continuou(base, ex, *a, **k):
            chamou.append(ex)
            tela = Image.new("RGB", (base.width + ex["left"] + ex["right"],
                                     base.height + ex["top"] + ex["bottom"]),
                             (10, 26, 85))
            tela.paste(base, (ex["left"], ex["top"]))
            return tela, "", 1

        monkeypatch.setattr(pf, "_melhor_continuacao", continuou)
        pf.preparar(arte, formato_by_id("ig-feed-1x1"), (0, 0, 1920, 1080),
                    tmp_path / "f.png", modo="outpaint")
        assert chamou and any(chamou[0].values())
