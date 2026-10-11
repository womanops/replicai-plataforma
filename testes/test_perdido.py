"""Trabalho que a fila perdeu não fica esperando para sempre.

O worker pode morrer entre tirar o trabalho da fila e começar a gravar estado.
O arquivo fica em "na fila" e, de fora, isso é indistinguível de uma fila
comprida — aconteceu duas vezes durante o desenvolvimento e levou meia hora
para ficar claro que não era lentidão.
"""
import fakeredis
import pytest

from api import trabalhos


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.delenv("REDIS_URL", raising=False)
    import importlib
    from api import main
    importlib.reload(trabalhos)
    importlib.reload(main)
    return main


CONTA = "conta-de-teste"


@pytest.fixture
def fila(api):
    from api.fila import FilaRQ
    f = FilaRQ(conexao=fakeredis.FakeStrictRedis())
    api.FILA = f
    return f


def nada():
    return None


def explode():
    """No nível do módulo: o que vai para a fila precisa ser importável do
    outro lado, e função aninhada não é."""
    raise RuntimeError("o Chrome não abriu")


class TestPerdido:
    def test_na_fila_com_a_vaga_viva_continua_esperando(self, api, fila):
        job = trabalhos.novo_id("x")
        ident = fila.enfileirar(nada)
        trabalhos.gravar(CONTA, job, {"status": "na fila", "id_na_fila": ident})
        assert api.perdido(CONTA, job, trabalhos.ler(CONTA, job))["status"] == "na fila"

    def test_vaga_que_sumiu_vira_erro(self, api, fila):
        job = trabalhos.novo_id("x")
        trabalhos.gravar(CONTA, job, {"status": "na fila", "id_na_fila": "nao-existe"})
        novo = api.perdido(CONTA, job, trabalhos.ler(CONTA, job))
        assert novo["status"] == "erro" and "sumiu da fila" in novo["erro"]
        assert trabalhos.ler(CONTA, job)["status"] == "erro"      # fica gravado

    def test_vaga_que_falhou_traz_o_motivo(self, api, fila):
        from rq import SimpleWorker

        job = trabalhos.novo_id("x")
        ident = fila.enfileirar(explode)
        trabalhos.gravar(CONTA, job, {"status": "rodando", "id_na_fila": ident})
        q = fila.filas["replicai"]
        SimpleWorker([q], connection=q.connection).work(burst=True)
        novo = api.perdido(CONTA, job, trabalhos.ler(CONTA, job))
        assert novo["status"] == "erro" and "Chrome" in novo["erro"]

    def test_trabalho_pronto_nao_e_tocado(self, api, fila):
        job = trabalhos.novo_id("x")
        trabalhos.gravar(CONTA, job, {"status": "pronto", "id_na_fila": "nao-existe"})
        assert api.perdido(CONTA, job, trabalhos.ler(CONTA, job))["status"] == "pronto"

    def test_sem_id_na_fila_nao_chuta(self, api, fila):
        """Trabalho antigo, de antes do id ser guardado: não vira erro à toa."""
        job = trabalhos.novo_id("x")
        trabalhos.gravar(CONTA, job, {"status": "na fila"})
        assert api.perdido(CONTA, job, trabalhos.ler(CONTA, job))["status"] == "na fila"

    def test_sem_fila_de_verdade_nao_chuta(self, api):
        """Rodando sem Redis, não há vaga para consultar."""
        job = trabalhos.novo_id("x")
        trabalhos.gravar(CONTA, job, {"status": "na fila", "id_na_fila": "qualquer"})
        assert api.perdido(CONTA, job, trabalhos.ler(CONTA, job))["status"] == "na fila"

    def test_o_progresso_e_limpo_junto(self, api, fila):
        """Progresso parado num trabalho que morreu faz a tela mentir."""
        job = trabalhos.novo_id("x")
        trabalhos.gravar(CONTA, job, {"status": "rodando", "id_na_fila": "nao-existe",
                               "progresso": {"etapa": "desenhando"}})
        assert api.perdido(CONTA, job, trabalhos.ler(CONTA, job))["progresso"] is None
