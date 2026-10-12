"""A fila de trabalhos.

Renderizar uma peça abre o Chromium e leva minutos. Sem fila, a requisição
estoura por timeout e o cliente vê erro num trabalho que está indo bem. Com
fila, ele recebe um identificador na hora e acompanha.

Duas implementações atrás da mesma interface:

- `FilaRQ` é a de produção: Redis guarda, o worker executa em outro processo, e
  derrubar a API não perde trabalho. São duas filas — peça e vídeo — porque a
  peça sai em segundos e o vídeo leva minutos: numa fila só, o vídeo de um
  cliente segura a peça do outro.
- `FilaDireta` roda na hora, no mesmo processo. É o que os testes usam — montar
  Redis para testar endpoint é atrito que faz ninguém rodar teste.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Protocol


class Fila(Protocol):
    def enfileirar(self, fn: Callable[..., Any], *args, fila: str = "", **kwargs) -> str:
        """Devolve o identificador do trabalho na fila."""


class FilaDireta:
    """Executa na hora. Para teste e para rodar a plataforma sem Redis."""

    def __init__(self, porque: str = ""):
        self.feitos: list[str] = []
        self.porque = porque          # aparece em /saude: queda calada engana

    def enfileirar(self, fn, *args, fila: str = "", **kwargs) -> str:
        fn(*args, **kwargs)
        nome = getattr(fn, "__name__", "trabalho")
        self.feitos.append(nome)
        return f"direto-{len(self.feitos)}"


# a peça sai em segundos, o vídeo leva minutos. Numa fila só, o vídeo de um
# cliente segura a peça do outro — e peça é o que a pessoa está esperando
# para ver.
FILA_PECA = "replicai"
FILA_VIDEO = "replicai-video"

LIMITES = {FILA_PECA: 1800, FILA_VIDEO: 3600}


# quanto custa cada coisa, medido no PSD de 60 MB da Consigaz. Serve para
# dizer a quem espera quanto falta — e esperar sem saber quanto é a diferença
# entre uma fila e um travamento.
ABRIR_ARTE = 7        # segundos, uma vez por trabalho
POR_FORMATO = 7
POR_VIDEO = 21


def _custo(nome: str, args) -> int:
    """Quanto tempo um trabalho parado na fila vai tomar quando começar."""
    try:
        if nome.endswith("processar_video"):
            return POR_VIDEO * max(1, len(args[2]))
        if nome.endswith("processar"):
            return ABRIR_ARTE + POR_FORMATO * max(1, len(args[3]))
    except Exception:
        pass
    return ABRIR_ARTE + POR_FORMATO


class FilaRQ:
    """Redis + RQ. O worker é outro processo: `rq worker replicai`."""

    def __init__(self, url: str | None = None, conexao=None):
        from redis import Redis
        from rq import Queue
        conn = conexao or Redis.from_url(url or os.environ["REDIS_URL"])
        conn.ping()                   # falhar aqui é melhor do que na primeira peça
        self.filas = {nome: Queue(nome, connection=conn, default_timeout=limite)
                      for nome, limite in LIMITES.items()}

    def enfileirar(self, fn, *args, fila: str = FILA_PECA, **kwargs) -> str:
        return self.filas.get(fila, self.filas[FILA_PECA]).enqueue(fn, *args, **kwargs).id

    def espera(self, ident: str) -> dict | None:
        """Quantos trabalhos estão na frente deste, e quanto tempo somam.

        A tela dizia "Replicando" para quem só estava esperando: indistinguível
        de trabalho em andamento, com nada acontecendo na frente. Esperar sem
        saber quanto é o que faz a pessoa recarregar a página e subir de novo.
        """
        for q in self.filas.values():
            try:
                ids = q.get_job_ids()
            except Exception:
                continue
            if ident not in ids:
                continue
            antes = ids[:ids.index(ident)]
            segundos = 0
            for outro in antes:
                try:
                    from rq.job import Job
                    j = Job.fetch(outro, connection=q.connection)
                    segundos += _custo(j.func_name or "", j.args)
                except Exception:
                    segundos += ABRIR_ARTE + POR_FORMATO
            return {"a_frente": len(antes), "segundos": segundos}
        return None


def fila_do_ambiente() -> Fila:
    """Redis quando há REDIS_URL configurado; senão roda na hora.

    Cair para execução direta é melhor do que recusar a subir: em máquina de
    desenvolvimento a plataforma funciona inteira, só sem paralelismo.
    """
    url = os.environ.get("REDIS_URL")
    if not url:
        return FilaDireta("sem REDIS_URL configurado")
    try:
        return FilaRQ(url)
    except Exception as e:
        # cair é melhor do que recusar a subir, mas cair calado é o defeito que
        # já entregou peça de régua com cara de peça do modelo. O motivo sobe
        # até /saude, onde quem opera consegue ver.
        return FilaDireta(f"o Redis em {url} não respondeu: {type(e).__name__}")
