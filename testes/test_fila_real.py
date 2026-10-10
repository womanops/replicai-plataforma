"""A fila contra um Redis de verdade.

O Redis de mentira prova a lógica; este prova que o trabalho atravessa o
processo. É a diferença entre "a função foi chamada" e "o worker pegou, rodou
e a peça apareceu no disco".

Roda na integração contínua, onde há serviço Redis. Na máquina de
desenvolvimento é pulado, porque montar serviço para rodar teste é atrito que
faz ninguém rodar teste.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

URL = os.environ.get("REDIS_URL")
pytestmark = [
    pytest.mark.lento,
    pytest.mark.skipif(not URL, reason="sem REDIS_URL: este é o teste do Redis de verdade"),
]


@pytest.fixture
def conn():
    from redis import Redis
    c = Redis.from_url(URL)
    c.flushdb()
    yield c
    c.flushdb()


def escrever(caminho: str, texto: str) -> None:
    """Função de módulo, não lambda: o que vai para o Redis precisa ser
    importável do outro lado, e é esse o ponto do teste."""
    Path(caminho).write_text(texto, encoding="utf-8")


class TestAtravessaOProcesso:
    def test_o_worker_pega_e_executa(self, conn, tmp_path):
        from rq import SimpleWorker

        from api.fila import FILA_PECA, FilaRQ
        alvo = tmp_path / "feito.txt"
        f = FilaRQ(conexao=conn)
        f.enfileirar(escrever, str(alvo), "passou pelo Redis")
        assert not alvo.exists()           # ainda ninguém executou

        SimpleWorker([f.filas[FILA_PECA]], connection=conn).work(burst=True)
        assert alvo.read_text() == "passou pelo Redis"

    def test_o_worker_de_video_nao_toca_na_fila_de_peca(self, conn, tmp_path):
        """Fila separada só serve se o worker respeitar a separação."""
        from rq import SimpleWorker

        from api.fila import FILA_PECA, FILA_VIDEO, FilaRQ
        peca, video = tmp_path / "peca.txt", tmp_path / "video.txt"
        f = FilaRQ(conexao=conn)
        f.enfileirar(escrever, str(peca), "peça")
        f.enfileirar(escrever, str(video), "vídeo", fila=FILA_VIDEO)

        SimpleWorker([f.filas[FILA_VIDEO]], connection=conn).work(burst=True)
        assert video.exists() and not peca.exists()

    def test_a_api_escolhe_a_fila_de_verdade(self, conn, monkeypatch):
        monkeypatch.setenv("REDIS_URL", URL)
        from api.fila import FilaRQ, fila_do_ambiente
        assert isinstance(fila_do_ambiente(), FilaRQ)

    def test_o_trabalho_sobrevive_a_queda_de_quem_enfileirou(self, conn, tmp_path):
        """O ponto da fila: derrubar a API não perde trabalho."""
        from rq import SimpleWorker

        from api.fila import FILA_PECA, FilaRQ
        alvo = tmp_path / "sobreviveu.txt"
        código = (
            "import sys; sys.path.insert(0, %r)\n"
            "from api.fila import FilaRQ\n"
            "from testes.test_fila_real import escrever\n"
            "FilaRQ(%r).enfileirar(escrever, %r, 'sobreviveu')\n"
            % (str(Path(__file__).resolve().parent.parent), URL, str(alvo))
        )
        subprocess.run([sys.executable, "-c", código], check=True,
                       cwd=Path(__file__).resolve().parent.parent)
        # quem enfileirou já morreu; o trabalho continua no Redis
        f = FilaRQ(conexao=conn)
        assert f.filas[FILA_PECA].count == 1
        SimpleWorker([f.filas[FILA_PECA]], connection=conn).work(burst=True)
        assert alvo.read_text() == "sobreviveu"
