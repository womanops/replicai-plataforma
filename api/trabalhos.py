"""O estado de um trabalho, em disco.

Em disco de propósito: a API e o worker são processos diferentes, e a API pode
cair e voltar. Estado em memória sumiria com ela, e o cliente perderia o
trabalho que já tinha sido pago e processado.
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


def pasta_do(job: str) -> Path:
    p = (pasta_base() / job).resolve()
    if not str(p).startswith(str(pasta_base())):
        raise ValueError("identificador inválido")      # barra travessia de caminho
    return p


def gravar(job: str, dados: dict) -> None:
    p = pasta_do(job)
    p.mkdir(parents=True, exist_ok=True)
    atual = ler(job) or {}
    atual.update(dados, atualizado=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    (p / "trabalho.json").write_text(json.dumps(atual, ensure_ascii=False, indent=1),
                                     encoding="utf-8")


def ler(job: str) -> dict | None:
    f = pasta_do(job) / "trabalho.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "erro", "erro": "o estado do trabalho está corrompido"}


def entregas(job: str) -> list[dict]:
    p = pasta_do(job)
    if not p.exists():
        return []
    fora = {"trabalho.json", "resultado.json"}
    itens = []
    for f in sorted(p.rglob("*")):
        if f.is_file() and f.name not in fora and "pecas" not in f.parts:
            itens.append({"nome": str(f.relative_to(p)), "kb": f.stat().st_size // 1024})
    return itens
