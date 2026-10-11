"""O estado de um trabalho, em disco.

Em disco de propósito: a API e o worker são processos diferentes, e a API pode
cair e voltar. Estado em memória sumiria com ela, e o cliente perderia o
trabalho que já tinha sido pago e processado.

Cada conta tem a própria pasta. Isolar por pasta, e não por verificação de
dono na leitura, é escolha deliberada: verificação esquecida num endpoint
vaza; pasta errada não existe. O caminho é conferido contra travessia nos dois
pedaços, porque identificador vem de fora.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


def pasta_base() -> Path:
    return Path(os.environ.get("STORAGE_DIR", "dados")).resolve()


def apelido(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return (t or "peca")[:48]


def novo_id(titulo: str) -> str:
    """Nome legível com sufixo curto: duas campanhas com o mesmo nome não
    se sobrescrevem, e a pasta continua reconhecível para quem abre o disco."""
    return f"{apelido(titulo)}-{os.urandom(3).hex()}"


NOME = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")


def pasta_da_conta(conta: str) -> Path:
    if not NOME.fullmatch(conta or ""):
        raise ValueError("identificador de conta inválido")
    return pasta_base() / conta


def pasta_do(conta: str, job: str) -> Path:
    if not NOME.fullmatch(job or ""):
        raise ValueError("identificador inválido")
    base = pasta_da_conta(conta)
    p = (base / job).resolve()
    if not str(p).startswith(str(base.resolve())):
        raise ValueError("identificador inválido")      # barra travessia de caminho
    return p


def gravar(conta: str, job: str, dados: dict) -> None:
    p = pasta_do(conta, job)
    p.mkdir(parents=True, exist_ok=True)
    atual = ler(conta, job) or {}
    atual.update(dados, atualizado=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    (p / "trabalho.json").write_text(json.dumps(atual, ensure_ascii=False, indent=1),
                                     encoding="utf-8")


def ler(conta: str, job: str) -> dict | None:
    f = pasta_do(conta, job) / "trabalho.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "erro", "erro": "o estado do trabalho está corrompido"}


def entregas(conta: str, job: str) -> list[dict]:
    p = pasta_do(conta, job)
    if not p.exists():
        return []
    fora = {"trabalho.json", "resultado.json"}
    itens = []
    for f in sorted(p.rglob("*")):
        if f.is_file() and f.name not in fora and "pecas" not in f.parts:
            itens.append({"nome": str(f.relative_to(p)), "kb": f.stat().st_size // 1024})
    return itens


def do_cliente(conta: str) -> list[dict]:
    """Os trabalhos de uma conta, do mais novo para o mais velho."""
    base = pasta_da_conta(conta)
    if not base.exists():
        return []
    saida = []
    for f in base.glob("*/trabalho.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        saida.append({"job": f.parent.name, "status": d.get("status"),
                      "titulo": d.get("titulo", ""), "formatos": d.get("formatos", []),
                      "atualizado": d.get("atualizado", "")})
    return sorted(saida, key=lambda x: x["atualizado"], reverse=True)
