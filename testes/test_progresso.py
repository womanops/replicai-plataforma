"""O trabalho diz onde está.

Com fila, a requisição volta em 0,1s e o trabalho roda noutro processo. Sem
progresso, o estado fica minutos em "rodando" e quem está do outro lado não
distingue um render demorado de um travamento.
"""
import json

import pytest
from PIL import Image

from api.pipeline import desdobrar


class Serve:
    def compor(self, base, formato_id, brief="", terreno=None):
        return {"canvas": {"w": 100, "h": 100}, "fundo": {"tipo": "cor", "cor": "#000"},
                "elementos": [], "saida": f"{formato_id}.png"}


@pytest.fixture
def arte(tmp_path):
    p = tmp_path / "arte.png"
    Image.new("RGB", (1920, 1080), "#0a1a55").save(p)
    return p


@pytest.fixture
def sem_chrome(monkeypatch):
    import api.pipeline as pl
    monkeypatch.setattr(pl, "render_peca", lambda a, d: d.write_bytes(b"x"))


class TestProgresso:
    def test_avisa_cada_passo_de_cada_formato(self, arte, tmp_path, sem_chrome):
        passos = []
        desdobrar(arte, ["ig-feed-1x1", "ig-stories"], Serve(), tmp_path / "job",
                  progresso=passos.append)
        etapas = [p["etapa"] for p in passos]
        assert "compondo" in etapas and "desenhando" in etapas and "pronta" in etapas
        # os dois formatos aparecem, e cada um chega ao fim
        assert {p["formato"] for p in passos if p["etapa"] == "pronta"} == \
            {"ig-feed-1x1", "ig-stories"}

    def test_o_total_e_quantos_formatos_foram_pedidos(self, arte, tmp_path, sem_chrome):
        passos = []
        desdobrar(arte, ["ig-feed-1x1", "ig-stories", "li-feed-16x9"], Serve(),
                  tmp_path / "job", progresso=passos.append)
        assert all(p["total"] == 3 for p in passos)

    def test_o_feito_so_anda_quando_a_peca_fica_pronta(self, arte, tmp_path, sem_chrome):
        passos = []
        desdobrar(arte, ["ig-feed-1x1", "ig-stories"], Serve(), tmp_path / "job",
                  progresso=passos.append)
        feitos = [p["feito"] for p in passos]
        assert feitos == sorted(feitos)          # nunca anda para trás
        assert max(feitos) == 2

    def test_sem_callback_a_esteira_roda_igual(self, arte, tmp_path, sem_chrome):
        """A esteira não pode depender de ter alguém ouvindo."""
        r = desdobrar(arte, ["ig-feed-1x1"], Serve(), tmp_path / "job")
        assert r.status == "pronto"


class TestNoEstadoDoTrabalho:
    def test_o_progresso_chega_ao_trabalho_e_some_no_fim(self, arte, tmp_path,
                                                         monkeypatch, sem_chrome):
        """Guardar e não mostrar é o erro de sempre; e deixar o progresso
        parado depois de pronto faz a tela mentir."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        import importlib

        from api import tarefas, trabalhos
        importlib.reload(trabalhos)
        monkeypatch.setattr(tarefas, "trabalhos", trabalhos)
        monkeypatch.setattr(tarefas, "compositor", lambda *a: Serve())
        monkeypatch.setattr(tarefas, "leitor", lambda: None)

        conta, job = "conta-de-teste", trabalhos.novo_id("teste")
        tarefas.processar(conta, job, str(arte), ["ig-feed-1x1"], "Oi", "", "")
        estado = trabalhos.ler(conta, job)
        assert estado["status"] == "pronto"
        assert estado["progresso"] is None
