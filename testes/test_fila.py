"""A fila.

Renderizar abre o Chromium e leva minutos. Sem fila a requisição estoura por
timeout e o cliente vê erro num trabalho que está indo bem. Estes testes usam
um Redis de mentira: montar serviço para testar fila é atrito que faz ninguém
rodar teste — e o Redis de verdade é provado na integração contínua.
"""
import fakeredis
import pytest

from api.fila import FILA_PECA, FILA_VIDEO, FilaDireta, FilaRQ, fila_do_ambiente

marcas = []


def anota(*args):
    marcas.append(args)


@pytest.fixture(autouse=True)
def limpa():
    marcas.clear()


class TestFilaDireta:
    def test_roda_na_hora(self):
        FilaDireta().enfileirar(anota, "a", "b")
        assert marcas == [("a", "b")]

    def test_devolve_identificador(self):
        f = FilaDireta()
        assert f.enfileirar(anota, 1) != f.enfileirar(anota, 2)

    def test_aceita_o_nome_da_fila_e_ignora(self):
        """A interface é a mesma das duas: quem chama não escolhe implementação."""
        FilaDireta().enfileirar(anota, 1, fila=FILA_VIDEO)
        assert marcas == [(1,)]

    def test_guarda_o_motivo_da_queda(self):
        """Queda calada é o defeito recorrente deste projeto: o motivo sobe
        até /saude, onde quem opera consegue ver."""
        assert FilaDireta("o Redis não respondeu").porque == "o Redis não respondeu"


class TestFilaRQ:
    @pytest.fixture
    def redis(self):
        return fakeredis.FakeStrictRedis()

    def test_enfileira_sem_executar(self, redis):
        f = FilaRQ(conexao=redis)
        f.enfileirar(anota, "x")
        assert marcas == []                      # quem executa é o worker
        assert f.filas[FILA_PECA].count == 1

    def test_peca_e_video_vao_para_filas_diferentes(self, redis):
        """Numa fila só, o vídeo de um cliente segura a peça do outro — e peça
        é o que a pessoa está esperando para ver."""
        f = FilaRQ(conexao=redis)
        f.enfileirar(anota, "peca")
        f.enfileirar(anota, "video", fila=FILA_VIDEO)
        assert f.filas[FILA_PECA].count == 1
        assert f.filas[FILA_VIDEO].count == 1

    def test_o_video_tem_prazo_maior(self, redis):
        f = FilaRQ(conexao=redis)
        assert f.filas[FILA_VIDEO]._default_timeout > f.filas[FILA_PECA]._default_timeout

    def test_fila_desconhecida_cai_na_de_peca(self, redis):
        f = FilaRQ(conexao=redis)
        f.enfileirar(anota, "x", fila="inventada")
        assert f.filas[FILA_PECA].count == 1

    def test_o_trabalho_guardado_executa_igual(self, redis):
        """O que vai para o Redis tem que voltar executável: função e
        argumentos, não um resumo."""
        from rq import SimpleWorker
        f = FilaRQ(conexao=redis)
        f.enfileirar(anota, "guardado")
        SimpleWorker([f.filas[FILA_PECA]], connection=redis).work(burst=True)
        assert marcas == [("guardado",)]

    def test_redis_que_nao_responde_falha_na_hora(self):
        """Falhar ao montar é melhor do que falhar na primeira peça."""
        with pytest.raises(Exception):
            FilaRQ("redis://127.0.0.1:6399/0")


class TestEscolha:
    def test_sem_redis_roda_na_hora(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        f = fila_do_ambiente()
        assert isinstance(f, FilaDireta) and "sem REDIS_URL" in f.porque

    def test_redis_quebrado_cai_mas_conta(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/0")
        f = fila_do_ambiente()
        assert isinstance(f, FilaDireta)
        assert "6399" in f.porque and "não respondeu" in f.porque
