"""Lê o `.env` da raiz do projeto ao subir.

Sem isto, a chave precisa estar exportada no mesmo terminal que iniciou o
servidor — e exportar depois, noutra aba, não alcança o processo já em pé.
É confusão garantida: a pessoa põe a chave, nada muda, e não há erro para
explicar.

Não usa biblioteca: são dez linhas, e uma dependência a mais na imagem por isso
não se paga. Variável já definida no ambiente vence o arquivo, que é o que
permite o Docker repassar a chave por cima.
"""
from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def carregar(arquivo: Path | None = None) -> list[str]:
    """Põe no ambiente o que estiver no `.env`. Devolve o que leu — só os
    nomes, nunca os valores."""
    f = Path(arquivo) if arquivo else RAIZ / ".env"
    if not f.exists():
        return []
    lidas = []
    for linha in f.read_text(encoding="utf-8", errors="replace").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        nome, _, valor = linha.partition("=")
        nome = nome.strip()
        valor = valor.strip().strip('"').strip("\'")
        if not nome or not valor:
            continue
        if nome not in os.environ:          # o ambiente real manda
            os.environ[nome] = valor
        lidas.append(nome)
    return lidas
