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
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:                                  # POSIX: a tranca vale entre processos
    import fcntl
except ImportError:                   # pragma: no cover - a plataforma roda em Linux
    fcntl = None


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


QUEBRADO = "o estado do trabalho está corrompido"


@contextmanager
def _tranca(p: Path):
    """Uma escrita de cada vez neste trabalho, entre threads E entre processos.

    `gravar` é ler-mudar-escrever. Duas delas ao mesmo tempo — a esteira
    gravando o passo do vídeo e a API gravando outra coisa — e uma escreve por
    cima do que a outra acabou de ler.
    """
    p.mkdir(parents=True, exist_ok=True)
    f = open(p / "trabalho.json.tranca", "w")
    try:
        if fcntl is not None:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        f.close()


def _do_disco(f: Path) -> dict | None:
    """O estado como está no arquivo. `None` se não existe; levanta se não dá
    para ler. Quem GRAVA usa esta, e não `ler`: `ler` devolve um estado de
    mentira quando o arquivo está ilegível, e gravar por cima dele apaga o
    trabalho de verdade."""
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def gravar(conta: str, job: str, dados: dict) -> None:
    p = pasta_do(conta, job)
    f = p / "trabalho.json"
    with _tranca(p):
        try:
            atual = _do_disco(f) or {}
        except json.JSONDecodeError:
            # não se escreve estado por cima de lixo: o arquivo ilegível fica
            # guardado para quem for olhar, e o que chega agora começa limpo
            f.replace(p / "trabalho.quebrado.json")
            atual = {}
        atual.update(dados, atualizado=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        # troca atômica: quem estiver lendo pega o arquivo inteiro, velho ou
        # novo, nunca a metade de um. Era daí que vinha o "corrompido" —
        # `write_text` zera o arquivo antes de escrever, e qualquer leitura
        # naquele instante via um JSON pela metade
        tmp = p / f"trabalho.{os.getpid()}.parcial"
        tmp.write_text(json.dumps(atual, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, f)


def ler(conta: str, job: str) -> dict | None:
    f = pasta_do(conta, job) / "trabalho.json"
    try:
        return _do_disco(f)
    except json.JSONDecodeError:
        return {"status": "erro", "erro": QUEBRADO}


def entregas(conta: str, job: str) -> list[dict]:
    p = pasta_do(conta, job)
    if not p.exists():
        return []
    fora = {"trabalho.json", "resultado.json", "trabalho.json.tranca",
            "trabalho.quebrado.json"}
    itens = []
    for f in sorted(p.rglob("*")):
        if (f.is_file() and f.name not in fora and "pecas" not in f.parts
                and not f.name.endswith(".parcial")):
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
