#!/usr/bin/env python3
"""O worker: tira trabalhos da fila e executa.

    python worker.py                 # as duas filas, peça primeiro
    python worker.py replicai        # só peça
    python worker.py replicai-video  # só vídeo

A ordem das filas importa: o RQ esvazia a primeira antes de olhar a segunda.
Peça vem primeiro porque é o que a pessoa está esperando para ver; vídeo leva
minutos e pode aguardar.

Dois workers na mesma fila atendem dois clientes ao mesmo tempo — é só subir
este arquivo duas vezes.
"""
from __future__ import annotations

import platform
import sys

from api import ambiente
from api.fila import FILA_PECA, FILA_VIDEO


def main(argv: list[str]) -> int:
    ambiente.carregar()               # a chave do modelo vem do .env também aqui

    import os

    from redis import Redis
    from rq import Queue, Worker

    url = os.environ.get("REDIS_URL")
    if not url:
        print("sem REDIS_URL: não há fila para atender. Configure no .env ou no "
              "ambiente — sem ela a API executa na hora, um trabalho por vez.",
              file=sys.stderr)
        return 2

    nomes = [a for a in argv[1:] if not a.startswith("--")] or [FILA_PECA, FILA_VIDEO]
    conexao = Redis.from_url(url)
    try:
        conexao.ping()
    except Exception as e:
        print(f"o Redis em {url} não respondeu: {e}", file=sys.stderr)
        return 2

    # No macOS o worker normal morre com signal 6 ao executar: ele bifurca um
    # processo para cada trabalho, e o sistema proíbe fork() depois que certas
    # bibliotecas foram carregadas. O trabalho some da fila sem explicação.
    # Em Linux, que é onde isto roda em produção, a bifurcação fica — é ela que
    # isola um render que trave do worker que o atende.
    from rq import SimpleWorker
    bifurca = platform.system() != "Darwin" and "--sem-fork" not in argv
    classe = Worker if bifurca else SimpleWorker
    if not bifurca:
        print("sem bifurcação: no macOS ela morre com signal 6. Em Linux o worker "
              "bifurca e um render travado não derruba o atendimento.")

    print(f"atendendo {', '.join(nomes)} em {url}")
    classe([Queue(n, connection=conexao) for n in nomes], connection=conexao).work()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
