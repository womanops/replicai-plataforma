"""De um quadrado para uma faixa larga: quem vai para onde.

Direcional da Ligia, e a regra da casa para esse salto: o topo da peça base
começa na ESQUERDA da peça maior, e dali a leitura corre do começo para o fim.
Na capa de página da Consigaz (1200×1200 para 1640×624) isso dá a chamada à
esquerda com a logo em cima, as fotos ao centro, o apoio onde ele já estava em
relação às fotos e o CTA à direita, com o mascote plantado no chão e a barriga
encostada no fim do CANDIDATE-SE.

As caixas aqui são as da arte-mãe de verdade, lidas do PSD. Elas são o motivo
de cada número: o vão de 30 px entre "Chegamos" e "a Porto Belo!" contra os
336 px até o apoio é o que separa um bloco do outro, e o CANDIDATE-SE
terminando a 7 px do corpo do Nino é o que "encostado" quer dizer.
"""
from pathlib import Path

import pytest

# a arte-mãe, como o PSD a descreve (x0, y0, x1, y1 em 1200×1200)
MAE = {
    "Chegamos": (90, 84, 1111, 145),
    "a Porto Belo!": (77, 175, 1111, 273),
    "E estamos  com vagas abertas!": (874, 609, 1172, 750),
    "Faça parte da nossa equipe.": (84, 954, 593, 988),
    "CANDIDATE-SE": (71, 996, 968, 1086),
}
NINO = (718, 748, 1240, 1586)          # cortado pelo rodapé da prancheta
MANGA = (1145, 983, 1186, 1001)        # a logo na manga dele
LOCKUP = (81, 1124, 291, 1156)
FOTO = (367, 591, 850, 913)

CAPA = {"w": 1640, "h": 624,
        "safe": {"top": 60, "bottom": 60, "left": 200, "right": 200},
        "id": "fb-capa"}


def el(nome, caixa, papel="apoio", **extra):
    x0, y0, x1, y1 = caixa
    return dict(camada=nome, papel=papel, tipo="texto" if papel != "figura" else "imagem",
                box={"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}, **extra)


def arte_mae():
    base = [el(n, c) for n, c in MAE.items()]
    base[-1]["papel"] = "apoio"
    base += [el("foto", FOTO, "figura"),
             el("Nino", NINO, "figura", plantado=["baixo"], src="nino.png"),
             el("logo-manga", MANGA, "marca"),
             el("logo", LOCKUP, "marca")]
    return base


# a arte quadrada reenquadrada no meio da capa: 1200 × 0,52 = 624 de altura,
# centrada na largura
PLANO = {"crop": [0, 0, 1200, 1200], "expand": {"left": 977, "top": 0},
         "escala": 0.52}
INFO = {"plano": PLANO, "base_box": [508, 0, 1132, 624], "src": "fundo.png"}


@pytest.fixture
def capa():
    from api.psd import _remontar_largo
    return _remontar_largo(arte_mae(), INFO, CAPA)


def caixa_de(saida, nome):
    from api.psd import _caixa
    achados = [e for e in saida if e.get("camada") == nome]
    assert achados, f"{nome} sumiu da peça"
    return _caixa(achados)


class TestAOrdemDeLeitura:
    def test_o_topo_da_mae_vai_para_a_esquerda(self, capa):
        """A regra: peça quadrada para peça larga, começa na esquerda."""
        x0, _, x1, _ = caixa_de(capa, "Chegamos")
        assert x1 < INFO["base_box"][0], "a chamada não está na faixa esquerda"

    def test_o_fim_da_mae_vai_para_a_direita(self, capa):
        x0, _, _, _ = caixa_de(capa, "CANDIDATE-SE")
        assert x0 >= INFO["base_box"][2], "o CTA não está na faixa direita"

    def test_o_bloco_do_meio_acompanha_a_arte(self, capa):
        """"E estamos com vagas" vale pela relação com a foto da boca do fogão:
        levado para uma faixa, vira uma frase solta."""
        x0, _, x1, _ = caixa_de(capa, "E estamos  com vagas abertas!")
        assert INFO["base_box"][0] <= x0 and x1 <= INFO["base_box"][2] + 60

    def test_a_logo_fica_em_cima_da_chamada(self, capa):
        _, ly0, _, ly1 = caixa_de(capa, "logo")
        _, cy0, _, _ = caixa_de(capa, "Chegamos")
        assert ly1 < cy0, "a assinatura não está acima da chamada"

    def test_os_tres_blocos_da_mae(self):
        from api.psd import _blocos_de_texto
        blocos = _blocos_de_texto([e for e in arte_mae() if e["papel"] == "apoio"])
        assert [[e["camada"] for e in b] for b in blocos] == [
            ["Chegamos", "a Porto Belo!"],
            ["E estamos  com vagas abertas!"],
            ["Faça parte da nossa equipe.", "CANDIDATE-SE"]]


class TestOMascote:
    def test_desenhado_uma_vez_so(self, capa):
        """Ele entra na lista do que é figura e na do que está plantado. Nas
        duas, saía dois Ninos — um no meio da arte e outro no lugar certo."""
        assert sum(1 for e in capa if e.get("camada") == "Nino") == 1

    def test_plantado_no_chao(self, capa):
        _, _, _, y1 = caixa_de(capa, "Nino")
        assert y1 == CAPA["h"], "o mascote ficou flutuando"

    def test_a_logo_da_manga_vai_junto(self, capa):
        """Ela é camada separada. Sem viajar com ele, ficava para trás como
        uma sujeirinha branca no meio do azul."""
        nx0, ny0, nx1, ny1 = caixa_de(capa, "Nino")
        mx0, my0, mx1, my1 = caixa_de(capa, "logo-manga")
        assert nx0 <= mx0 and mx1 <= nx1 and ny0 <= my0 and my1 <= ny1


class TestOCTAEncostaSemSerCoberto:
    """O braço do Nino está aberto para a esquerda. Medir onde ele "começa"
    pela caixa — ou pela tinta — põe o texto embaixo do braço, que foi a
    reclamação. O que o texto encosta é o CORPO."""

    def test_o_texto_para_antes_do_corpo(self, capa, monkeypatch):
        from api import psd
        monkeypatch.setattr(psd, "_comeco_do_corpo", lambda *a, **k: 0.533)
        saida = psd._remontar_largo(arte_mae(), INFO, CAPA, pasta=Path("."))
        _, _, tx1, _ = caixa_de(saida, "CANDIDATE-SE")
        nx0, _, nx1, _ = caixa_de(saida, "Nino")
        corpo = nx0 + (nx1 - nx0) * 0.533
        assert tx1 <= corpo, "o texto entrou embaixo do braço"

    def test_e_encosta_nele(self, capa, monkeypatch):
        from api import psd
        monkeypatch.setattr(psd, "_comeco_do_corpo", lambda *a, **k: 0.533)
        saida = psd._remontar_largo(arte_mae(), INFO, CAPA, pasta=Path("."))
        _, _, tx1, _ = caixa_de(saida, "CANDIDATE-SE")
        nx0, _, nx1, _ = caixa_de(saida, "Nino")
        corpo = nx0 + (nx1 - nx0) * 0.533
        assert corpo - tx1 < CAPA["w"] * 0.05, "ficou um vão: não encostou"

    def test_na_altura_da_barriga(self, capa):
        """Centrado na barriga, não no meio da peça: é o que tira o mascote da
        sensação de voando.

        A medida vem da arte-mãe e não da constante do código: a faixa branca
        do peito do Nino vai de 0,54 a 0,67 da altura dele, e é ali que o
        bloco do CTA está centrado. Mais acima o texto bate no braço aberto,
        mais abaixo ele cruza a perna.
        """
        _, by0, _, by1 = caixa_de(capa, "Nino")
        _, ty0, _, _ = caixa_de(capa, "Faça parte da nossa equipe.")
        _, _, _, cy1 = caixa_de(capa, "CANDIDATE-SE")
        centro = ((ty0 + cy1) / 2 - by0) / (by1 - by0)
        assert 0.54 <= centro <= 0.67, f"o CTA caiu em {centro:.2f} da altura dele"

    def test_o_texto_respeita_a_margem_segura(self, capa):
        """A figura pode sangrar; o texto, não — numa capa de Facebook os
        200 px da direita somem no celular."""
        for nome in ("CANDIDATE-SE", "Faça parte da nossa equipe.", "Chegamos"):
            x0, _, x1, _ = caixa_de(capa, nome)
            assert x0 >= CAPA["safe"]["left"] - 1
            assert x1 <= CAPA["w"] - CAPA["safe"]["right"] + 1, f"{nome} passou da margem"


class TestOndeOCorpoComeca:
    def _figura(self, tmp_path):
        """Um boneco de teste: braço fino à esquerda, corpo cheio à direita."""
        from PIL import Image
        im = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        for y in range(40, 48):                      # o braço
            for x in range(5, 60):
                im.putpixel((x, y), (255, 255, 255, 255))
        for y in range(20, 100):                     # o corpo
            for x in range(60, 95):
                im.putpixel((x, y), (255, 255, 255, 255))
        alvo = tmp_path / "boneco.png"
        im.save(alvo)
        return alvo

    def test_o_braco_nao_conta(self, tmp_path):
        from api.psd import _comeco_do_corpo
        assert _comeco_do_corpo(self._figura(tmp_path)) == pytest.approx(0.60, abs=0.02)

    def test_sem_arquivo_nao_explode(self, tmp_path):
        """Sem medida o texto para na caixa: pior diagramação, peça entregue."""
        from api.psd import _comeco_do_corpo
        assert _comeco_do_corpo(tmp_path / "nao-existe.png") == 0.0


class TestDuasLinhasNaMesmaAltura:
    """Num KV largo é normal ter texto ao lado de texto, começando e
    terminando na mesma altura. O agrupamento ordenava as linhas e, no empate,
    o desempate caía nos próprios elementos — dois dicionários, que o Python
    não compara. Os banners de 728×90 e 970×250 de um trabalho real morreram
    assim, com "o fundo não saiu: '<' not supported between dict and dict"."""

    def _linha(self, camada, x, y, papel="apoio"):
        return {"papel": papel, "camada": camada, "texto": camada,
                "box": {"x": x, "y": y, "w": 100, "h": 40}}

    def test_empate_de_altura_nao_derruba(self):
        from api.psd import _blocos_de_texto
        els = [self._linha("esquerda", 0, 10, "headline"),
               self._linha("direita", 300, 10)]
        assert len(_blocos_de_texto(els)) == 1

    def test_tres_linhas_empatadas_tambem_nao(self):
        from api.psd import _blocos_de_texto
        els = [self._linha(f"t{i}", i * 200, 10) for i in range(3)]
        assert sum(len(b) for b in _blocos_de_texto(els)) == 3

    def test_o_que_esta_longe_continua_sendo_outro_bloco(self):
        """O conserto não pode colar tudo num bloco só."""
        from api.psd import _blocos_de_texto
        els = [self._linha("alto", 0, 10, "headline"),
               self._linha("ao lado", 300, 10),
               self._linha("longe", 0, 400, "cta")]
        blocos = _blocos_de_texto(els)
        assert len(blocos) == 2
        assert {p["texto"] for p in blocos[0]} == {"alto", "ao lado"}
        assert [p["texto"] for p in blocos[1]] == ["longe"]

    def test_a_ordenacao_nao_olha_os_elementos(self):
        import inspect
        from api import psd
        fonte = inspect.getsource(psd._blocos_de_texto)
        assert "caixas.sort(key=lambda c: (c[0], c[1]))" in fonte
