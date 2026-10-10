"""As regras de diagramação que valem para qualquer peça.

As convenções de cada formato já existiam em prosa, no campo `notas`, e iam
no prompt. Mas conselho sem conferência é conselho ignorado — foi o que
aconteceu com o recorte da marca e com a frase inventada. Aqui elas viram
regra, com o motivo escrito, para o modelo corrigir na segunda volta em vez
de a peça sair torta.

Três regras, e nenhuma é gosto:

- **ordem de leitura** — a chamada vem antes do apoio, que vem antes do CTA.
  CTA acima da headline inverte o sentido da peça;
- **o CTA fecha** — é o último elemento no caminho do olho: embaixo na peça
  de pé ou quadrada, à direita na faixa horizontal;
- **um alinhamento por faixa** — lado a lado com alinhamentos diferentes lê
  como descuido. Entre faixas pode variar: chamada em cima à esquerda e botão
  embaixo fechando com a borda da arte é alinhamento pela arte, e foi o que uma
  revisão pediu. A faixa horizontal é exceção inteira, porque ali as três
  posições são o próprio desenho do formato.
"""
from __future__ import annotations

# marca e selo são mobília de canto: não entram na coluna de leitura
NA_LEITURA = ("headline", "apoio", "cta")
ORDEM_LEITURA = {p: i for i, p in enumerate(NA_LEITURA)}
ALTURA = {"topo": 0, "meio": 1, "baixo": 2}

# a partir daqui a peça é uma faixa: o olho corre na horizontal e a convenção
# vira logo à esquerda, frase no centro, botão à direita
FAIXA = 2.5


def e_faixa(formato: dict) -> bool:
    return formato["w"] / max(1, formato["h"]) >= FAIXA


def convencao(formato: dict) -> str:
    """O que dizer ao modelo antes de ele escolher. Dito antes, sai certo na
    primeira; dito só na recusa, custa uma rodada."""
    if e_faixa(formato):
        return ("Esta peça é uma faixa horizontal: o olho corre da esquerda para a "
                "direita. Marca à esquerda, chamada no centro, CTA à direita.")
    return ("A leitura desce: chamada, depois apoio, depois CTA — nessa ordem, de cima "
            "para baixo. O CTA fecha a peça, nunca abre. E tudo alinhado do mesmo "
            "jeito: chamada centralizada com botão à esquerda é descuido, não desenho.")


def conferir(elementos, formato: dict) -> str:
    """Devolve o que está errado na diagramação, ou vazio se estiver certa.

    `elementos` são os do esquema: cada um com `papel` e `zona`.
    """
    por_papel = {e.papel: e.zona for e in elementos}
    faixa = e_faixa(formato)

    if faixa:
        cta = por_papel.get("cta")
        if cta and not cta.endswith("direita"):
            return (f"numa faixa horizontal o CTA fecha à direita, e veio em `{cta}`. "
                    f"A convenção do formato é marca à esquerda, chamada no centro, "
                    f"botão à direita")
        marca = por_papel.get("marca")
        if marca and not marca.endswith("esquerda"):
            return f"numa faixa horizontal a marca abre à esquerda, e veio em `{marca}`"
        return ""

    # ordem de leitura: cada papel não pode estar acima do anterior
    na_peca = [(ORDEM_LEITURA[p], p, z) for p, z in por_papel.items() if p in ORDEM_LEITURA]
    na_peca.sort()
    for (_, pa, za), (_, pb, zb) in zip(na_peca, na_peca[1:]):
        if ALTURA[zb.split("-")[0]] < ALTURA[za.split("-")[0]]:
            return (f"`{pb}` está acima de `{pa}` (`{zb}` contra `{za}`), e isso inverte "
                    f"a leitura: a chamada vem primeiro, o CTA fecha")

    cta = por_papel.get("cta")
    if cta and cta.split("-")[0] == "topo":
        return "o CTA abre a peça em vez de fechar: ele é o último no caminho do olho"

    # a regra vale dentro da faixa, não entre faixas. Chamada em cima à
    # esquerda e botão embaixo fechando com a borda da arte é alinhamento pela
    # arte, não descuido — exigir uma coluna só proibia a composição certa.
    por_faixa: dict[str, set[str]] = {}
    for p, z in por_papel.items():
        if p in ORDEM_LEITURA:
            vert, horz = z.split("-")
            por_faixa.setdefault(vert, set()).add(horz)
    for vert, lados in por_faixa.items():
        if len(lados) > 1:
            return (f"na faixa `{vert}` a peça mistura alinhamentos "
                    f"({', '.join(sorted(lados))}). Dentro de uma faixa, um só: lado a "
                    f"lado com alinhamentos diferentes lê como descuido")
    return ""
