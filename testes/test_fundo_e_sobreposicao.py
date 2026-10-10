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
        assert faixas["topo"] == faixas["baixo"] == faixas["meio"]

    def test_sem_livres_divide_a_peca_em_tres(self):
        faixas = _faixas(formato_by_id("ig-feed-1x1"))
        assert faixas["topo"][3] <= faixas["meio"][1]
        assert faixas["meio"][3] <= faixas["baixo"][1]


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
