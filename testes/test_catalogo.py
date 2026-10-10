"""O catálogo de formatos é o contrato com quem usa: a API vai expor esses ids,
o front vai listar esses nomes, e o motor vai compor dentro dessas medidas. Um
`safe` maior que o canvas, ou dois formatos com o mesmo id, é erro que só
aparece na peça pronta.
"""
import pytest

from motor.replica import formato_by_id, load_formatos

FORMATOS = load_formatos()["formatos"]
IDS = [f["id"] for f in FORMATOS]


def test_catalogo_nao_esta_vazio():
    assert len(FORMATOS) >= 20


def test_ids_sao_unicos():
    repetidos = {i for i in IDS if IDS.count(i) > 1}
    assert not repetidos, f"id repetido no catálogo: {repetidos}"


@pytest.mark.parametrize("f", FORMATOS, ids=IDS)
class TestCadaFormato:
    def test_tem_os_campos_que_a_api_vai_expor(self, f):
        for campo in ("id", "canal", "nome", "w", "h", "ratio", "safe", "texto"):
            assert campo in f, f"{f.get('id')} sem `{campo}`"

    def test_medidas_fazem_sentido(self, f):
        assert isinstance(f["w"], int) and isinstance(f["h"], int)
        assert f["w"] > 0 and f["h"] > 0
        assert f["w"] <= 20000 and f["h"] <= 20000, "medida absurda, provável erro de digitação"

    def test_area_segura_cabe_dentro_do_canvas(self, f):
        """Safe zone maior que a peça empurra todo o texto para fora."""
        s = f["safe"]
        assert s["left"] + s["right"] < f["w"], f"{f['id']}: margens laterais somam mais que a largura"
        assert s["top"] + s["bottom"] < f["h"], f"{f['id']}: margens verticais somam mais que a altura"
        assert all(v >= 0 for v in s.values()), f"{f['id']}: margem negativa"

    def test_limites_de_texto(self, f):
        """`0` não é erro: quer dizer que o formato não leva aquele texto. Thumb
        de YouTube não tem CTA, banner 728x90 não tem apoio. Headline, porém,
        toda peça tem — se vier 0, nenhum texto cabe e a peça sai muda."""
        t = f["texto"]
        assert t.get("headline_max", 0) > 0, f"{f['id']}: sem limite de headline"
        for k, v in t.items():
            assert isinstance(v, int) and v >= 0, f"{f['id']}: `{k}` inválido ({v})"


class TestBuscaPorId:
    def test_acha_o_que_existe(self):
        f = formato_by_id("ig-feed-4x5")
        assert f is not None and f["w"] == 1080 and f["h"] == 1350

    def test_devolve_nada_para_id_inventado(self):
        """Tem que ser None, não exceção: a API precisa responder 404, não 500."""
        assert formato_by_id("formato-que-nao-existe") is None

    def test_nao_confunde_id_parecido(self):
        assert formato_by_id("ig-feed") is None
