"""O compositor decide a peça. Enquanto a composição automática não existe
(ver docs/DECISAO-quem-compoe.md), o que precisa estar garantido é o contrato:
ou devolve peça que o motor renderiza, ou recusa dizendo por quê. Nunca entrega
peça torta calada.
"""
import json

import pytest

from api.compositor import ComposicaoImpossivel, CompositorArquivo, CompositorSimples
from motor.replica import formato_by_id

BASE = "base.png"


class TestCompositorSimples:
    def test_devolve_peca_que_o_motor_entende(self):
        p = CompositorSimples("Chegamos a Porto Belo").compor(BASE, "ig-feed-4x5")
        for campo in ("formato", "canvas", "fundo", "elementos"):
            assert campo in p
        assert p["canvas"] == {"w": 1080, "h": 1350}
        assert p["fundo"]["src"] == BASE

    @pytest.mark.parametrize("fid", ["ig-feed-4x5", "ig-stories", "gdn-300x250", "li-banner"])
    def test_todo_texto_cabe_dentro_da_peca(self, fid):
        f = formato_by_id(fid)
        p = CompositorSimples("Uma chamada curta").compor(BASE, fid)
        for e in p["elementos"]:
            b = e["box"]
            assert b["x"] >= 0 and b["y"] >= 0, f"{fid}: caixa começa fora da peça"
            assert b["x"] + b["w"] <= f["w"], f"{fid}: caixa passa da largura"
            assert b["y"] + b["h"] <= f["h"], f"{fid}: caixa passa da altura"

    @pytest.mark.parametrize("fid", ["ig-feed-4x5", "ig-stories", "gdn-300x250"])
    def test_respeita_a_area_segura(self, fid):
        """Fora da área segura a rede corta: texto ali some no feed de alguém."""
        f = formato_by_id(fid)
        s = f["safe"]
        p = CompositorSimples("Uma chamada curta", cta="Clique").compor(BASE, fid)
        for e in p["elementos"]:
            b = e["box"]
            assert b["x"] >= s["left"], f"{fid}: {e['papel']} invade a margem esquerda"
            assert b["x"] + b["w"] <= f["w"] - s["right"], f"{fid}: {e['papel']} invade a direita"
            assert b["y"] >= s["top"] and b["y"] + b["h"] <= f["h"] - s["bottom"]

    def test_recusa_headline_maior_que_o_formato_aguenta(self):
        limite = formato_by_id("gdn-320x50")["texto"]["headline_max"]
        with pytest.raises(ComposicaoImpossivel, match="caracteres"):
            CompositorSimples("x" * (limite + 1)).compor(BASE, "gdn-320x50")

    def test_recusa_cta_em_formato_que_nao_leva_cta(self):
        """`cta_max: 0` quer dizer que o formato não comporta chamada para ação.
        Entregar sem avisar seria perder a chamada caladamente."""
        with pytest.raises(ComposicaoImpossivel, match="não leva CTA"):
            CompositorSimples("Chamada", cta="Clique aqui").compor(BASE, "yt-thumb")

    def test_recusa_sem_headline(self):
        with pytest.raises(ComposicaoImpossivel):
            CompositorSimples("   ").compor(BASE, "ig-feed-4x5")

    def test_recusa_formato_inventado(self):
        with pytest.raises(ComposicaoImpossivel, match="desconhecido"):
            CompositorSimples("Chamada").compor(BASE, "nao-existe")


class TestCompositorArquivo:
    def test_le_a_peca_pronta(self, tmp_path):
        (tmp_path / "ig-feed-4x5.json").write_text(
            json.dumps({"formato": "ig-feed-4x5", "elementos": []}), encoding="utf-8")
        p = CompositorArquivo(tmp_path).compor(BASE, "ig-feed-4x5")
        assert p["formato"] == "ig-feed-4x5"

    def test_avisa_quando_nao_tem_peca_para_o_formato(self, tmp_path):
        with pytest.raises(ComposicaoImpossivel, match="não existe peça pronta"):
            CompositorArquivo(tmp_path).compor(BASE, "ig-stories")
