"""O texto tem que se ler contra o que está atrás dele.

Posicionar bem não basta: branco sobre o brilho da gota de vidro some igual.
A régua é a da acessibilidade — 4,5 para texto, 3 para elemento gráfico.
"""
import pytest
from PIL import Image, ImageDraw

from api.contraste import CLARO, ESCURO, ajustar, melhor, razao, sob_a_caixa


class TestRegua:
    def test_preto_no_branco_e_o_extremo(self):
        assert razao("#000000", "#ffffff") == pytest.approx(21, abs=0.1)

    def test_cor_igual_nao_tem_contraste(self):
        assert razao("#336699", "#336699") == pytest.approx(1.0)

    def test_a_razao_nao_depende_da_ordem(self):
        assert razao("#101828", "#dddddd") == pytest.approx(razao("#dddddd", "#101828"))

    def test_escolhe_claro_no_escuro_e_escuro_no_claro(self):
        assert melhor("#0a1a55") == CLARO
        assert melhor("#f2f2f2") == ESCURO

    def test_hex_curto_e_hex_torto(self):
        assert razao("#fff", "#000") == pytest.approx(21, abs=0.1)
        assert razao("nao-e-cor", "#000") == pytest.approx(21, abs=0.1)


@pytest.fixture
def peca_em(tmp_path):
    def faz(cor_fundo, box=None, tipo="texto"):
        f = tmp_path / "fundo.png"
        Image.new("RGB", (400, 400), cor_fundo).save(f)
        el = {"tipo": tipo, "papel": "headline", "texto": "oi",
              "box": box or {"x": 0, "y": 0, "w": 400, "h": 400}, "cor": CLARO}
        if tipo == "botao":
            el.update({"papel": "cta", "fundo": CLARO})
        peca = {"canvas": {"w": 400, "h": 400}, "elementos": [el]}
        return peca, f
    return faz


class TestAjuste:
    def test_texto_claro_em_fundo_claro_vira_escuro(self, peca_em):
        peca, f = peca_em("#f4f4f4")
        ajustar(peca, f)
        assert peca["elementos"][0]["cor"] == ESCURO

    def test_texto_claro_em_fundo_escuro_fica_como_esta(self, peca_em):
        peca, f = peca_em("#0a1a55")
        ajustar(peca, f)
        assert peca["elementos"][0]["cor"] == CLARO

    def test_o_corpo_do_botao_se_separa_do_fundo(self, peca_em):
        """Botão branco em peça branca é um retângulo invisível."""
        peca, f = peca_em("#ffffff", tipo="botao")
        ajustar(peca, f)
        b = peca["elementos"][0]
        assert b["fundo"] == ESCURO and b["cor"] == CLARO

    def test_o_texto_do_botao_se_le_contra_o_corpo(self, peca_em):
        peca, f = peca_em("#0a1a55", tipo="botao")
        ajustar(peca, f)
        b = peca["elementos"][0]
        assert razao(b["cor"], b["fundo"]) >= 4.5

    def test_fundo_agitado_vira_aviso(self, tmp_path):
        """Cor nenhuma resolve letra sobre xadrez: é lugar errado, não cor errada."""
        f = tmp_path / "fundo.png"
        im = Image.new("RGB", (400, 400), "#000000"); d = ImageDraw.Draw(im)
        for i in range(0, 400, 20):
            d.rectangle((i, 0, i + 10, 400), fill="#ffffff")
        im.save(f)
        peca = {"canvas": {"w": 400, "h": 400},
                "elementos": [{"tipo": "texto", "papel": "headline", "texto": "oi",
                               "cor": CLARO, "box": {"x": 0, "y": 0, "w": 400, "h": 400}}]}
        assert any("agitada" in a for a in ajustar(peca, f))

    def test_so_olha_debaixo_da_caixa(self, tmp_path):
        """Metade clara, metade escura: quem manda é o que está sob o texto."""
        f = tmp_path / "fundo.png"
        im = Image.new("RGB", (400, 400), "#0a1a55")
        ImageDraw.Draw(im).rectangle((0, 0, 400, 200), fill="#fafafa")
        im.save(f)
        peca = {"canvas": {"w": 400, "h": 400}, "elementos": [
            {"tipo": "texto", "papel": "headline", "texto": "a", "cor": CLARO,
             "box": {"x": 0, "y": 0, "w": 400, "h": 180}},
            {"tipo": "texto", "papel": "apoio", "texto": "b", "cor": CLARO,
             "box": {"x": 0, "y": 220, "w": 400, "h": 180}}]}
        ajustar(peca, f)
        assert peca["elementos"][0]["cor"] == ESCURO
        assert peca["elementos"][1]["cor"] == CLARO

    def test_fundo_que_nao_existe_nao_quebra(self, tmp_path):
        peca = {"canvas": {"w": 400, "h": 400}, "elementos": []}
        assert ajustar(peca, tmp_path / "nao-existe.png") == []

    def test_fundo_de_outro_tamanho_e_redimensionado(self, tmp_path):
        f = tmp_path / "fundo.png"
        Image.new("RGB", (100, 100), "#f4f4f4").save(f)
        peca = {"canvas": {"w": 400, "h": 400}, "elementos": [
            {"tipo": "texto", "papel": "headline", "texto": "oi", "cor": CLARO,
             "box": {"x": 0, "y": 0, "w": 400, "h": 400}}]}
        ajustar(peca, f)
        assert peca["elementos"][0]["cor"] == ESCURO


class TestMedicao:
    def test_a_caixa_fora_do_quadro_nao_explode(self):
        im = Image.new("RGB", (100, 100), "#808080")
        assert sob_a_caixa(im, {"x": 500, "y": 500, "w": 10, "h": 10}) == ((0, 0, 0), 0.0)

    def test_cor_chapada_nao_tem_agitacao(self):
        im = Image.new("RGB", (100, 100), "#0a1a55")
        _, agitacao = sob_a_caixa(im, {"x": 0, "y": 0, "w": 100, "h": 100})
        assert agitacao == pytest.approx(0, abs=0.01)


class TestNaEsteira:
    def test_a_esteira_corrige_a_cor_antes_de_renderizar(self, tmp_path, monkeypatch):
        """Escrever a regra e não chamá-la é o erro que já aconteceu duas vezes
        neste projeto. Este teste existe para ela continuar sendo chamada."""
        import json

        import api.pipeline as pl
        from api.pipeline import desdobrar

        monkeypatch.setattr(pl, "render_peca", lambda a, d: d.write_bytes(b"x"))
        base = tmp_path / "base.png"
        Image.new("RGB", (1080, 1080), "#fafafa").save(base)

        class Claro:
            def compor(self, base, formato_id, brief="", terreno=None):
                return {"canvas": {"w": 1080, "h": 1080},
                        "fundo": {"tipo": "imagem", "src": "base.png"},
                        "saida": f"{formato_id}.png",
                        "elementos": [{"tipo": "texto", "papel": "headline", "texto": "oi",
                                       "cor": CLARO,
                                       "box": {"x": 0, "y": 0, "w": 1080, "h": 1080}}]}

        pasta = tmp_path / "job"
        desdobrar(base, ["ig-feed-1x1"], Claro(), pasta)
        peca = json.loads((pasta / "pecas" / "ig-feed-1x1.json").read_text())
        assert peca["elementos"][0]["cor"] == ESCURO


class TestALetraQueVeioNoArquivo:
    """`ajustar` cuida do texto que a plataforma escreve, e cuida trocando a
    cor. O lockup que vem do PSD é IMAGEM: passava batido, e a cor dele é do
    cliente — não se troca.

    Foi o lockup branco em cima da faixa branca do 970x250: a régua de sossego
    aprovou, porque fundo liso ela mede; contraste ela não media.
    """

    def _camada(self, tmp_path, nome="letra.png", cor=(255, 255, 255)):
        """Uma camada quase toda transparente, com tinta no meio."""
        from PIL import Image, ImageDraw
        im = Image.new("RGBA", (200, 60), (0, 0, 0, 0))
        ImageDraw.Draw(im).rectangle((10, 20, 190, 40), fill=(*cor, 255))
        im.save(tmp_path / nome)
        return tmp_path / nome

    def test_a_cor_da_tinta_ignora_o_transparente(self, tmp_path):
        """Pela média do PNG inteiro a letra branca daria quase preta: a
        camada é quase toda vazia."""
        from api.contraste import tom_da_tinta
        assert tom_da_tinta(self._camada(tmp_path)) == (255, 255, 255)

    def test_camada_vazia_nao_tem_tinta(self, tmp_path):
        from PIL import Image

        from api.contraste import tom_da_tinta
        p = tmp_path / "vazia.png"
        Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(p)
        assert tom_da_tinta(p) is None

    def test_mede_onde_a_letra_esta_e_nao_na_media_da_caixa(self, tmp_path):
        """Metade escura, metade clara: a média da caixa aprova e a palavra
        some na metade clara. É o mesmo erro da mediana na régua de cor."""
        from PIL import Image

        from api.contraste import le_sobre, sob_a_tinta
        camada = self._camada(tmp_path)
        fundo = Image.new("RGB", (200, 60), (10, 10, 20))
        fundo.paste(Image.new("RGB", (100, 60), (245, 245, 250)), (100, 0))
        box = {"x": 0, "y": 0, "w": 200, "h": 60}

        pela_media = le_sobre(fundo, box, (255, 255, 255))
        tipico, no_escuro = sob_a_tinta(fundo, box, camada, (255, 255, 255))
        assert pela_media > 3, "a média da caixa reprovaria, e ela não reprova"
        assert no_escuro >= 0.25, "não viu a metade em que a letra some"

    def test_letra_sobre_fundo_escuro_passa_inteira(self, tmp_path):
        from PIL import Image

        from api.contraste import sob_a_tinta
        camada = self._camada(tmp_path)
        fundo = Image.new("RGB", (200, 60), (10, 10, 20))
        tipico, no_escuro = sob_a_tinta(fundo, {"x": 0, "y": 0, "w": 200, "h": 60},
                                        camada, (255, 255, 255))
        assert tipico > 10 and no_escuro == 0.0

    def test_a_peca_avisa_e_diz_o_que_resolve(self, tmp_path):
        """Avisar é o que sobra quando a cor não resolve — e o aviso precisa
        dizer o que resolve, que é mover ou escurecer."""
        from PIL import Image

        from api.contraste import do_lockup
        self._camada(tmp_path)
        Image.new("RGB", (200, 60), (250, 250, 250)).save(tmp_path / "fundo.png")
        peca = {"canvas": {"w": 200, "h": 60},
                "elementos": [{"tipo": "imagem", "papel": "headline",
                               "src": "letra.png",
                               "box": {"x": 0, "y": 0, "w": 200, "h": 60}}]}
        avisos = do_lockup(peca, tmp_path / "fundo.png", tmp_path)
        assert avisos and "mover o bloco ou escurecer" in avisos[0]

    def test_nao_avisa_quando_a_letra_se_le(self, tmp_path):
        from PIL import Image

        from api.contraste import do_lockup
        self._camada(tmp_path)
        Image.new("RGB", (200, 60), (8, 10, 24)).save(tmp_path / "fundo.png")
        peca = {"canvas": {"w": 200, "h": 60},
                "elementos": [{"tipo": "imagem", "papel": "headline",
                               "src": "letra.png",
                               "box": {"x": 0, "y": 0, "w": 200, "h": 60}}]}
        assert do_lockup(peca, tmp_path / "fundo.png", tmp_path) == []

    def test_o_texto_escrito_continua_com_o_outro_dono(self, tmp_path):
        """Elemento de texto é de `ajustar`, que troca a cor. Conferir duas
        vezes daria dois avisos para o mesmo problema."""
        from PIL import Image

        from api.contraste import do_lockup
        Image.new("RGB", (200, 60), (250, 250, 250)).save(tmp_path / "fundo.png")
        peca = {"canvas": {"w": 200, "h": 60},
                "elementos": [{"tipo": "texto", "papel": "headline", "cor": "#ffffff",
                               "box": {"x": 0, "y": 0, "w": 200, "h": 60}}]}
        assert do_lockup(peca, tmp_path / "fundo.png", tmp_path) == []
