"""A fila de trabalhos.

Renderizar uma peça abre o Chromium e leva minutos. Sem fila, a requisição
estoura por timeout e o cliente vê erro num trabalho que está indo bem. Com
fila, ele recebe um identificador na hora e acompanha.

Duas implementações atrás da mesma interface:

- `FilaRQ` é a de produção: Redis guarda, o worker executa em outro processo, e
  derrubar a API não perde trabalho.
- `FilaDireta` roda na hora, no mesmo processo. É o que os testes usam — montar
  Redis para testar endpoint é atrito que faz ninguém rodar teste.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Protocol


class Fila(Protocol):
    def enfileirar(self, fn: Callable[..., Any], *args, **kwargs) -> str:
        """Devolve o identificador do trabalho na fila."""


class FilaDireta:
    """Executa na hora. Para teste e para rodar a plataforma sem Redis."""

    def __init__(self):
        self.feitos: list[str] = []

    def enfileirar(self, fn, *args, **kwargs) -> str:
        fn(*args, **kwargs)
        nome = getattr(fn, "__name__", "trabalho")
        self.feitos.append(nome)
        return f"direto-{len(self.feitos)}"


class FilaRQ:
    """Redis + RQ. O worker é outro processo: `rq worker replicai`."""

    def __init__(self, url: str | None = None, nome: str = "replicai",
                 limite_segundos: int = 1800):
        from redis import Redis
        from rq import Queue
        self.q = Queue(nome, connection=Redis.from_url(url or os.environ["REDIS_URL"]),
                       default_timeout=limite_segundos)

    def enfileirar(self, fn, *args, **kwargs) -> str:
        return self.q.enqueue(fn, *args, **kwargs).id


def fila_do_ambiente() -> Fila:
    """Redis quando há REDIS_URL configurado; senão roda na hora.

    Cair para execução direta é melhor do que recusar a subir: em máquina de
    desenvolvimento a plataforma funciona inteira, só sem paralelismo.
    """
    url = os.environ.get("REDIS_URL")
    if not url:
        return FilaDireta()
    try:
        return FilaRQ(url)
    except Exception:
        return FilaDireta()
