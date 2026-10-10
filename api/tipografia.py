"""Higiene de linha: o que nunca pode sobrar sozinho numa quebra.

O texto da peça é quebrado pelo navegador, que quebra em qualquer espaço. Daí
saiu "25 de março" numa linha e "· São Paulo" na outra, com o ponto separador
abrindo a segunda — coisa que nenhum diagramador deixa passar.

A correção é o espaço inseparável: ele impede a quebra naquele ponto sem mudar
uma letra do que foi escrito. Nada aqui reescreve texto; só decide onde a linha
pode ou não partir.
"""
from __future__ import annotations

import re

NBSP = " "

# separador nunca abre linha: ele pertence ao que veio antes
SEPARADORES = "·•|–—"

# palavra de uma letra nunca fecha linha: em português são artigos e
# preposições, e sozinhas no fim da linha deixam a mancha picotada
UMA_LETRA = re.compile(r"(?<![^\s])([aeoàáéíóúEAOÀÉ])\s+", re.IGNORECASE)


def ajeitar(texto: str) -> str:
    """Prende o que não pode ficar sozinho na virada da linha."""
    if not texto:
        return texto
    t = texto
    # "março · São" -> "março·(inseparável) São": o ponto desce junto com a
    # palavra anterior, e a quebra passa a acontecer depois dele
    t = re.sub(rf"\s+([{re.escape(SEPARADORES)}])\s+", rf"{NBSP}\1 ", t)
    t = UMA_LETRA.sub(rf"\1{NBSP}", t)
    return t


def quebras(texto: str) -> int:
    """Quantos pontos de quebra sobraram. Serve para teste e para diagnóstico."""
    return len(re.findall(r"[ \t]", ajeitar(texto)))
