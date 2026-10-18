"""A peça que não saiu, e a saída para ela.

"Tentei adaptar 3 peças agora e uma não foi, sem explicação/ressalva. Numa
situação como esta, que não deveria acontecer mas pode, deveria ter um botão
de gerar novamente para resolver a peça."

Explicação havia — era esta, gravada no trabalho dela:

    "não renderizou: Command '['/Applications/Google Chrome.app/Contents/
    MacOS/Google Chrome', '--headless=new', ...]' timed out after 120 seconds"

Ou seja: o navegador demorou demais porque a máquina estava ocupada. O motivo
existia e não servia para nada — e não havia nada a fazer com a peça a não ser
refazer o trabalho inteiro, com as outras duas já prontas.
"""
import json

import pytest

from testes.test_api import FilaEspia, arte_png, cliente, enviar      # noqa: F401


class TestOMotivoEmPortugues:
    def test_o_estouro_do_navegador_nao_vira_traceback_na_tela(self):
        """O recado da peça era a linha de comando do subprocesso inteira."""
        import subprocess
        from unittest.mock import patch

        from motor.replica import chrome_run
        with patch("motor.replica.find_chrome", return_value="/bin/chrome"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("c", 120)):
            with pytest.raises(RuntimeError) as e:
                chrome_run("file:///x.html", [])
        msg = str(e.value)
        assert "Command" not in msg and "subprocess" not in msg
        assert "passou de 120 segundos" in msg
        assert "gerar de novo" in msg.lower(), "o motivo tem que dizer a saída"


def _trabalho(cliente, monkeypatch, falhou="gdn-320x50"):
    """Um trabalho entregue pela metade: duas peças prontas, uma que não saiu."""
    from api import trabalhos
    r = cliente.post("/jobs", files={"arte": ("arte.png", arte_png(), "image/png")},
                     data={"formatos": "gdn-300x600,gdn-728x90,gdn-320x50"})
    job = r.json()["job"]
    cliente.post(f"/jobs/{job}/rodar",
                 data={"formatos": "gdn-300x600,gdn-728x90,gdn-320x50"})
    trabalhos.gravar(cliente.conta.id, job, {
        "status": "parcial", "prontas": ["gdn-300x600", "gdn-728x90"],
        "falhas": {falhou: "não renderizou: o desenho passou de 120 segundos"},
        "formatos": ["gdn-300x600", "gdn-728x90", "gdn-320x50"]})
    return job


class TestGerarDeNovo:
    def test_a_peca_que_nao_saiu_pode_ser_refeita(self, cliente, monkeypatch):
        job = _trabalho(cliente, monkeypatch)
        r = cliente.post(f"/jobs/{job}/pecas/gdn-320x50/refazer")
        assert r.status_code == 202
        nome, args = cliente.fila.pedidos[-1]
        assert nome == "refazer_peca" and args[-1] == "gdn-320x50"

    def test_formato_que_nao_foi_pedido_e_recusado(self, cliente, monkeypatch):
        job = _trabalho(cliente, monkeypatch)
        r = cliente.post(f"/jobs/{job}/pecas/ig-stories/refazer")
        assert r.status_code == 409

    def test_formato_inventado_e_recusado(self, cliente, monkeypatch):
        job = _trabalho(cliente, monkeypatch)
        assert cliente.post(f"/jobs/{job}/pecas/turbo-9x9/refazer").status_code == 422

    def test_trabalho_rodando_nao_aceita(self, cliente, monkeypatch):
        """Duas esteiras na mesma pasta escrevem uma por cima da outra."""
        from api import trabalhos
        job = _trabalho(cliente, monkeypatch)
        trabalhos.gravar(cliente.conta.id, job, {"status": "rodando"})
        assert cliente.post(f"/jobs/{job}/pecas/gdn-320x50/refazer").status_code == 409

    def test_uma_peca_de_cada_vez(self, cliente, monkeypatch):
        from api import trabalhos
        job = _trabalho(cliente, monkeypatch)
        trabalhos.gravar(cliente.conta.id, job,
                         {"ajuste": {"status": "rodando", "formato": "gdn-300x600"}})
        assert cliente.post(f"/jobs/{job}/pecas/gdn-320x50/refazer").status_code == 409

    def test_sem_a_arte_nao_ha_o_que_refazer(self, cliente, monkeypatch):
        from api import trabalhos
        job = _trabalho(cliente, monkeypatch)
        trabalhos.gravar(cliente.conta.id, job, {"arquivado": True})
        r = cliente.post(f"/jobs/{job}/pecas/gdn-320x50/refazer")
        assert r.status_code == 409 and "arte" in r.json()["detail"]


class TestOQueJaEstavaProntoFica:
    """Refazer UMA peça não pode reescrever o trabalho: as outras duas já
    estavam prontas, e perdê-las para recuperar a terceira seria pior do que
    o defeito."""

    def _resultado(self, prontas, falhas=None):
        from api.pipeline import Resultado
        from pathlib import Path
        r = Resultado(pasta=Path("."))
        r.prontas = {f: Path(f"{f}.png") for f in prontas}
        r.falhas = falhas or {}
        return r

    def test_a_peca_nova_soma_as_que_ja_estavam(self, cliente, monkeypatch, tmp_path):
        from api import tarefas, trabalhos
        job = _trabalho(cliente, monkeypatch)
        monkeypatch.setattr(tarefas, "desdobrar",
                            lambda *a, **k: self._resultado(["gdn-320x50"]))
        monkeypatch.setattr(tarefas, "_apresentar", lambda *a, **k: "")
        monkeypatch.setattr(tarefas.uso, "registrar", lambda *a, **k: {"gravado": True})
        (trabalhos.pasta_do(cliente.conta.id, job) / "arte.png").write_bytes(arte_png().read())
        trabalhos.gravar(cliente.conta.id, job, {"arte": "arte.png"})

        tarefas.refazer_peca(cliente.conta.id, job, "gdn-320x50")
        d = trabalhos.ler(cliente.conta.id, job)
        assert d["prontas"] == ["gdn-300x600", "gdn-320x50", "gdn-728x90"]
        assert d["falhas"] == {}
        assert d["status"] == "pronto"
        assert d["ajuste"]["saiu"] is True

    def test_falhar_de_novo_nao_mente_que_saiu(self, cliente, monkeypatch):
        from api import tarefas, trabalhos
        job = _trabalho(cliente, monkeypatch)
        monkeypatch.setattr(tarefas, "desdobrar", lambda *a, **k: self._resultado(
            [], {"gdn-320x50": "não renderizou de novo"}))
        monkeypatch.setattr(tarefas, "_apresentar", lambda *a, **k: "")
        (trabalhos.pasta_do(cliente.conta.id, job) / "arte.png").write_bytes(arte_png().read())
        trabalhos.gravar(cliente.conta.id, job, {"arte": "arte.png"})

        tarefas.refazer_peca(cliente.conta.id, job, "gdn-320x50")
        d = trabalhos.ler(cliente.conta.id, job)
        assert d["status"] == "parcial"
        assert d["prontas"] == ["gdn-300x600", "gdn-728x90"]
        assert d["falhas"]["gdn-320x50"] == "não renderizou de novo"
        assert d["ajuste"]["saiu"] is False

    def test_o_registro_do_trabalho_continua_sendo_o_trabalho_inteiro(
            self, cliente, monkeypatch):
        """`desdobrar` deixa um `resultado.json` só do formato refeito. Foi
        desse arquivo que saiu a recuperação de um estado perdido uma vez."""
        from api import tarefas, trabalhos
        job = _trabalho(cliente, monkeypatch)
        monkeypatch.setattr(tarefas, "desdobrar",
                            lambda *a, **k: self._resultado(["gdn-320x50"]))
        monkeypatch.setattr(tarefas, "_apresentar", lambda *a, **k: "")
        monkeypatch.setattr(tarefas.uso, "registrar", lambda *a, **k: {"gravado": True})
        pasta = trabalhos.pasta_do(cliente.conta.id, job)
        (pasta / "arte.png").write_bytes(arte_png().read())
        trabalhos.gravar(cliente.conta.id, job, {"arte": "arte.png"})

        tarefas.refazer_peca(cliente.conta.id, job, "gdn-320x50")
        guardado = json.loads((pasta / "resultado.json").read_text(encoding="utf-8"))
        assert sorted(guardado["prontas"]) == ["gdn-300x600", "gdn-320x50", "gdn-728x90"]

    def test_so_a_peca_que_saiu_e_cobrada(self, cliente, monkeypatch):
        """Peça que falhou nunca foi cobrada; a que sai agora é uma peça
        entregue, e conta."""
        from api import tarefas, trabalhos
        job = _trabalho(cliente, monkeypatch)
        anotados = []
        monkeypatch.setattr(tarefas, "desdobrar",
                            lambda *a, **k: self._resultado(["gdn-320x50"]))
        monkeypatch.setattr(tarefas, "_apresentar", lambda *a, **k: "")
        monkeypatch.setattr(tarefas.uso, "registrar",
                            lambda conta, o_que, **k: anotados.append((o_que, k.get("formato")))
                            or {"gravado": True})
        (trabalhos.pasta_do(cliente.conta.id, job) / "arte.png").write_bytes(arte_png().read())
        trabalhos.gravar(cliente.conta.id, job, {"arte": "arte.png"})

        tarefas.refazer_peca(cliente.conta.id, job, "gdn-320x50")
        assert anotados == [(tarefas.uso.PECA, "gdn-320x50")]
