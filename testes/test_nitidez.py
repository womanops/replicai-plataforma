"""A peça olhada de perto.

"As peças aparecem em baixa resolução dentro da ferramenta e na exportação."

Elas nunca estiveram em baixa resolução: o arquivo sai com o tamanho exato
que o formato pede, e 300x600 é 300x600 — rede nenhuma aceita outra coisa. O
problema é que esse arquivo é sempre olhado AMPLIADO: na lupa da tela, numa
tela retina que tem o dobro dos pixels, e na apresentação, onde um banner
pequeno cresce até três vezes para ocupar a folha. A 1x isso vira mingau.

A peça passa a ser desenhada em dobro. O arquivo do formato sai da redução
dessa imagem — o que de quebra tira o serrilhado das bordas — e a cópia
grande fica ao lado, para a lupa, para o PDF e para o pacote.
"""
import json

import pytest
from PIL import Image

from motor.replica import ESCALA_DO_RENDER, find_chrome, render_peca

precisa_de_chrome = pytest.mark.skipif(
    find_chrome() is None, reason="sem navegador nesta máquina")


def _peca(tmp_path, w=300, h=250):
    (tmp_path / "pecas").mkdir(exist_ok=True)
    Image.new("RGB", (w * 4, h * 4), "#0b1030").save(tmp_path / "fundo.png")
    arq = tmp_path / "pecas" / "x.json"
    arq.write_text(json.dumps({
        "canvas": {"w": w, "h": h}, "safe": {"left": 8, "right": 8, "top": 8, "bottom": 8},
        "fundo": {"tipo": "imagem", "src": "fundo.png", "fit": "cover"},
        "elementos": [{"tipo": "texto", "papel": "headline", "texto": "Energia",
                       "box": {"x": 20, "y": 90, "w": w - 40, "h": 60},
                       "cor": "#ffffff", "min": 20, "max": 60}]}), encoding="utf-8")
    return arq


class TestODesenhoEmDobro:
    def test_a_escala_e_uma_so_e_esta_dita(self):
        """O número aparece no nome do arquivo, no PDF e no pacote: três
        lugares que não podem divergir."""
        assert ESCALA_DO_RENDER == 2

    @precisa_de_chrome
    def test_o_arquivo_entregue_tem_o_tamanho_do_formato(self, tmp_path):
        """O que a rede exige. Entregar o dobro aqui seria quebrar a peça."""
        arq = _peca(tmp_path)
        render_peca(arq, tmp_path / "x.png")
        assert Image.open(tmp_path / "x.png").size == (300, 250)

    @precisa_de_chrome
    def test_a_copia_grande_fica_ao_lado(self, tmp_path):
        arq = _peca(tmp_path)
        render_peca(arq, tmp_path / "x.png")
        grande = tmp_path / f"x@{ESCALA_DO_RENDER}x.png"
        assert grande.exists()
        assert Image.open(grande).size == (300 * 2, 250 * 2)

    @precisa_de_chrome
    def test_a_borda_da_letra_e_fina_e_nao_borrada(self, tmp_path):
        """Não basta ter o dobro dos pixels: o 1x ampliado também tem. O que
        separa é a BORDA. Letra branca sobre fundo escuro desenhada em dobro
        passa de escuro a claro em um ou dois pixels; ampliada, passa numa
        faixa de meio-tom — que é o que o olho lê como borrão."""
        arq = _peca(tmp_path)
        render_peca(arq, tmp_path / "x.png")
        grande = Image.open(tmp_path / f"x@{ESCALA_DO_RENDER}x.png").convert("L")
        esticada = Image.open(tmp_path / "x.png").convert("L").resize(
            grande.size, Image.Resampling.LANCZOS)

        def meio_tom(im):
            px = list(im.getdata())
            return sum(1 for v in px if 51 < v < 204) / len(px)

        assert meio_tom(grande) < meio_tom(esticada) * 0.8, (
            f"desenhada {meio_tom(grande):.4f} x ampliada {meio_tom(esticada):.4f}")


class TestOndeACopiaGrandeEUsada:
    def test_a_apresentacao_prefere_a_copia_grande(self):
        import inspect

        from api import apresentacao
        fonte = inspect.getsource(apresentacao.montar)
        assert 'f"{png.stem}@{ESCALA_DO_RENDER}x.png"' in fonte
        assert "grande if grande.exists() else png" in fonte, \
            "trabalho antigo não tem a cópia: o PDF não pode quebrar por isso"

    def test_a_folha_do_pdf_cabe_a_peca_em_dobro(self):
        """Com 1400 o PDF já tinha menos pixels do que a folha mostra."""
        from api.apresentacao import LADO_NA_FOLHA
        assert LADO_NA_FOLHA >= 2000

    def test_a_imagem_do_pdf_nao_vai_em_jpeg_ruim(self):
        """JPEG 80 em letra branca sobre fundo chapado deixa halo em volta de
        cada letra, e é o tipo de peça que esta casa faz."""
        import inspect

        from motor.replica import _img_data_uri
        fonte = inspect.getsource(_img_data_uri)
        assert "qualidade: int = 92" in fonte and "subsampling=0" in fonte

    def test_o_pacote_leva_as_duas(self):
        """O arquivo do formato é o que a rede exige; o grande é o que se
        olha de perto, aprova e imprime."""
        from api.main import para_entregar
        itens = [{"nome": "gdn-300x600.png", "kb": 1},
                 {"nome": "gdn-300x600@2x.png", "kb": 4},
                 {"nome": "apresentacao.pdf", "kb": 9},
                 {"nome": "fundo-gdn-300x600.png", "kb": 2}]
        nomes = {i["nome"] for i in para_entregar({"prontas": ["gdn-300x600"]}, itens)}
        assert nomes == {"gdn-300x600.png", "gdn-300x600@2x.png", "apresentacao.pdf"}

    def test_a_lupa_da_tela_mostra_a_copia_grande(self):
        from pathlib import Path
        tela = Path("web/index.html").read_text(encoding="utf-8")
        assert "e.nome === id + '@2x.png'" in tela
        # e a medida na tela continua sendo a do formato
        assert "#lupa img.dobro{zoom:.5}" in tela
