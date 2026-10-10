"""A arte-mãe tem que chegar no modelo.

Vem de um caso real: a esteira passava o nome curto `base.jpg`, que serve para
a régua montar o `src` da peça mas não existe a partir de onde o processo roda.
O modelo compunha às cegas, só com o brief, e nada denunciava — as peças saíam,
o custo era menor, e só a contagem de tokens entregava (2.886 para três
chamadas, quando uma imagem 1920x1080 sozinha vale perto de 2.800).
"""
import json

from PIL import Image

from api.modelo import _imagem
from api.pipeline import desdobrar


class Espiao:
    """Guarda o que recebeu, devolve peça válida."""

    def __init__(self):
        self.bases = []

    def compor(self, base, formato_id, brief="", terreno=None):
        self.bases.append(base)
        return {"w": 100, "h": 100, "fundo": {"tipo": "cor", "cor": "#000"},
                "elementos": [], "saida": f"{formato_id}.png"}


def test_a_esteira_passa_caminho_que_abre(tmp_path, monkeypatch):
    import api.pipeline as pl
    monkeypatch.setattr(pl, "render_peca", lambda a, d: d.write_bytes(b"x"))
    base = tmp_path / "arte.png"
    Image.new("RGB", (64, 64), "red").save(base)

    espiao = Espiao()
    desdobrar(base, ["ig-stories"], espiao, tmp_path / "job")

    recebido = espiao.bases[0]
    from pathlib import Path
    assert Path(recebido).exists(), "o compositor recebeu caminho que não abre"
    assert _imagem(Path(recebido)) is not None, "a arte não vira anexo para o modelo"


def test_a_regra_ainda_grava_src_relativo(tmp_path, monkeypatch):
    """O caminho que vai para o modelo é completo; o que fica gravado na peça,
    não — senão a peça só renderiza na máquina que a compôs."""
    import api.pipeline as pl
    from api.compositor import CompositorSimples
    monkeypatch.setattr(pl, "render_peca", lambda a, d: d.write_bytes(b"x"))
    base = tmp_path / "arte.png"
    Image.new("RGB", (64, 64), "red").save(base)
    pasta = tmp_path / "job"

    desdobrar(base, ["ig-stories"], CompositorSimples(headline="Oi"), pasta)
    peca = json.loads((pasta / "pecas" / "ig-stories.json").read_text())
    src = peca["fundo"]["src"]
    assert src == "base.png"
    assert "/" not in src and not src.startswith(str(tmp_path))


def test_imagem_so_vira_anexo_se_o_arquivo_existe():
    from pathlib import Path
    assert _imagem(Path("nao-existe.png")) is None
