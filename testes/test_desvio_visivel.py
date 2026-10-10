"""O desvio para a régua não pode ser silencioso.

Isto vem de um caso real: a chave estava válida, a conta sem crédito, e o
trabalho voltou "pronto" sem aviso nenhum — peças feitas pela régua com cara de
peças feitas pelo modelo. Quem fosse entregar não teria como saber.
"""
import json

import pytest

from api.compositor import ComposicaoImpossivel, CompositorEmCadeia
from api.pipeline import desdobrar


class Quebrado:
    def __init__(self, motivo="sem crédito"):
        self.motivo = motivo

    def compor(self, base, formato_id, brief=""):
        raise ComposicaoImpossivel(self.motivo)


class Serve:
    def __init__(self):
        self.chamadas = 0

    def compor(self, base, formato_id, brief=""):
        self.chamadas += 1
        return {"w": 100, "h": 100, "fundo": {"tipo": "cor", "cor": "#000"},
                "elementos": [], "saida": f"{formato_id}.png"}


def test_a_peca_do_segundo_vem_marcada():
    p = CompositorEmCadeia(Quebrado("sem crédito"), Serve()).compor("b.png", "x")
    assert p["_desvios"] == ["Quebrado: sem crédito"]


def test_sem_desvio_a_peca_sai_limpa():
    """Marca só quando houve desvio: aviso que aparece sempre não é aviso."""
    assert "_desvios" not in CompositorEmCadeia(Serve()).compor("b.png", "x")


def test_todos_quebrados_ainda_levanta():
    with pytest.raises(ComposicaoImpossivel) as e:
        CompositorEmCadeia(Quebrado("um"), Quebrado("dois")).compor("b.png", "x")
    assert "um" in str(e.value) and "dois" in str(e.value)


def test_o_desvio_chega_ao_resultado_do_trabalho(tmp_path, monkeypatch):
    import api.pipeline as pl
    monkeypatch.setattr(pl, "render_peca", lambda arq, destino: destino.write_bytes(b"x"))
    base = tmp_path / "base.png"; base.write_bytes(b"x")

    r = desdobrar(base, ["ig-stories"], CompositorEmCadeia(Quebrado(), Serve()),
                  tmp_path / "job")
    assert r.status == "pronto"                     # a peça saiu
    aviso = r.avisos["ig-stories"][0]
    assert "régua" in aviso and "sem crédito" in aviso


def test_a_marca_nao_vaza_para_o_json_da_peca(tmp_path, monkeypatch):
    """`_desvios` é recado interno: no arquivo que vai para o motor, não entra."""
    import api.pipeline as pl
    monkeypatch.setattr(pl, "render_peca", lambda arq, destino: destino.write_bytes(b"x"))
    base = tmp_path / "base.png"; base.write_bytes(b"x")
    pasta = tmp_path / "job"

    desdobrar(base, ["ig-stories"], CompositorEmCadeia(Quebrado(), Serve()), pasta)
    peca = json.loads((pasta / "pecas" / "ig-stories.json").read_text())
    assert "_desvios" not in peca
