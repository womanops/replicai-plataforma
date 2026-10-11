#!/usr/bin/env python3
"""Um Redis de mentira que fala Redis de verdade, para testar a fila aqui.

    python redis-de-teste.py            # escuta em 127.0.0.1:6379

Serve para ver a fila funcionando sem instalar serviço nenhum: o `fakeredis`
abre uma porta TCP e responde o protocolo, então a API e o worker falam com
ele como falariam com o Redis.

Não é para produção, e não finge que é: guarda tudo na memória do processo e
some quando ele morre. Em produção é o Redis do contêiner.
"""
from __future__ import annotations

import sys
import threading


def main(argv: list[str]) -> int:
    porta = int(argv[1]) if len(argv) > 1 else 6379
    try:
        from fakeredis import TcpFakeServer
    except ImportError:
        print("falta o fakeredis: pip install -r requirements-dev.txt", file=sys.stderr)
        return 2

    endereco = ("127.0.0.1", porta)
    TcpFakeServer.allow_reuse_address = True
    servidor = TcpFakeServer(endereco, server_type="redis")
    print(f"Redis de teste em redis://{endereco[0]}:{endereco[1]}/0 — ctrl+c para parar")
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nparando")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
