"""O que cada cliente consumiu.

O custo desta plataforma é por peça, não por cliente: uma conta que roda mil
peças no mês custa cem vezes mais do que uma que roda dez. Plano com uso
ilimitado, nesse desenho, é prejuízo escondido — e para cobrar por volume é
preciso contar.

Guardado como registro de eventos, uma linha por peça, e não como um contador
que se incrementa. Contador perde a história: quando o cliente perguntar por
que a fatura subiu, a resposta tem que ser uma lista, não um número. E linha
escrita no fim do arquivo não se perde se dois processos gravarem juntos.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

PECA = "peca"
VIDEO = "video"
FUNDO = "fundo-generativo"


def _mes(quando: datetime | None = None) -> str:
    return (quando or datetime.now(timezone.utc)).strftime("%Y-%m")


def pasta(conta: str) -> Path:
    from api.trabalhos import pasta_da_conta
    p = pasta_da_conta(conta) / "_uso"
    p.mkdir(parents=True, exist_ok=True)
    return p


def arquivo(conta: str, mes: str = "") -> Path:
    return pasta(conta) / f"{mes or _mes()}.jsonl"


def registrar(conta: str, tipo: str, **detalhes) -> dict:
    """Anota um consumo.

    Não levanta: contar não pode derrubar uma entrega já feita. Mas também não
    some calado — devolve se gravou, e quem chamou põe isso na entrega.
    Faturamento que desaparece em silêncio é a pior das quedas caladas: o
    cliente usa, ninguém cobra, e nada no sistema denuncia.
    """
    evento = {"quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "tipo": tipo, **detalhes}
    try:
        alvo = arquivo(conta)
        # abre em modo de acréscimo: duas gravações concorrentes não se
        # sobrescrevem, cada uma cai no fim do arquivo
        with open(alvo, "a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")
    except Exception as e:
        return {**evento, "gravado": False, "porque": f"{type(e).__name__}: {e}"}
    return {**evento, "gravado": True}


def eventos(conta: str, mes: str = "") -> list[dict]:
    f = arquivo(conta, mes)
    if not f.exists():
        return []
    saida = []
    for linha in f.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            saida.append(json.loads(linha))
        except json.JSONDecodeError:
            continue            # linha truncada não derruba o relatório inteiro
    return saida


def resumo(conta: str, mes: str = "") -> dict:
    """Quanto a conta consumiu no mês, e quanto isso custou de verdade."""
    conta_de = {PECA: 0, VIDEO: 0, FUNDO: 0}
    dolares = 0.0
    por_trabalho: dict[str, int] = {}
    for e in eventos(conta, mes):
        tipo = e.get("tipo")
        if tipo in conta_de:
            conta_de[tipo] += int(e.get("quantas", 1))
        dolares += float(e.get("dolares") or 0)
        if tipo == PECA and e.get("job"):
            por_trabalho[e["job"]] = por_trabalho.get(e["job"], 0) + 1
    return {"mes": mes or _mes(), "pecas": conta_de[PECA], "videos": conta_de[VIDEO],
            "fundos_generativos": conta_de[FUNDO],
            "custo_dolares": round(dolares, 6),
            "trabalhos": len(por_trabalho)}


def meses(conta: str) -> list[str]:
    return sorted(f.stem for f in pasta(conta).glob("*.jsonl"))


# ----------------------------------------------------------------- planos

# O que cada plano permite por mês. Número grande não é "ilimitado": é o teto
# que protege de um cliente sozinho consumir o lucro de todos.
PLANOS = {
    "teste":   {"pecas": 30,    "videos": 5,    "nome": "Teste"},
    "estudio": {"pecas": 300,   "videos": 60,   "nome": "Estúdio"},
    "agencia": {"pecas": 1500,  "videos": 300,  "nome": "Agência"},
}
PLANO_PADRAO = "teste"


def limites(plano: str) -> dict:
    return PLANOS.get(plano, PLANOS[PLANO_PADRAO])


def cabe(conta: str, plano: str, pecas: int = 0, videos: int = 0) -> tuple[bool, str]:
    """Ainda cabe no plano? Devolve também o motivo, para dizer à pessoa.

    Conferido antes de enfileirar, não depois de renderizar: recusar um
    trabalho já feito é gastar o custo e não poder cobrar.
    """
    lim = limites(plano)
    r = resumo(conta)
    if pecas and r["pecas"] + pecas > lim["pecas"]:
        return False, (f"o plano {lim['nome']} vai até {lim['pecas']} peças por mês, "
                       f"e este trabalho chegaria a {r['pecas'] + pecas}")
    if videos and r["videos"] + videos > lim["videos"]:
        return False, (f"o plano {lim['nome']} vai até {lim['videos']} vídeos por mês, "
                       f"e este pedido chegaria a {r['videos'] + videos}")
    return True, ""
