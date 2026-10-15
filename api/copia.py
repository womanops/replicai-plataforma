"""A cópia diária do que é dos clientes, guardada fora do servidor.

O backup do provedor é **semanal** e salva a MÁQUINA. O que precisa de proteção
diária é outra coisa: o trabalho entregue. Numa agência que produz 250 peças por
mês, perder o que foi feito desde domingo é uma semana de trabalho que ninguém
tem como devolver — e o cliente pagou por ela.

**Fora do servidor, e não nele.** Cópia no mesmo disco protege contra engano
(alguém apagou uma pasta) e não protege contra o que realmente acontece: a
máquina morrer. Por isso daqui ela sai para um armazenamento de objetos, e por
isso o arquivo local é apagado assim que sobe.

**O que vai é o que a faxina guarda**: as contas e, de cada trabalho, as peças
entregues, os vídeos, a apresentação e os JSONs da montagem. O material bruto
fica de fora de propósito — ele já tem prazo de validade de 30 dias, e é 85% do
disco. Copiar o que vai ser apagado é pagar armazenamento para guardar lixo.

Sem armazenamento configurado nada acontece, e `/saude` diz isso em letras: uma
cópia que ninguém sabe que não está acontecendo é pior do que nenhuma.
"""
from __future__ import annotations

import json
import os
import tarfile
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

GUARDA = int(os.environ.get("REPLICAI_COPIAS", "14"))   # quantas cópias ficam lá
ATRASO_DEMAIS = 2                                       # dias sem cópia que já é defeito


def configurado() -> bool:
    return bool(os.environ.get("REPLICAI_COPIA_BUCKET")
                and os.environ.get("REPLICAI_COPIA_CHAVE")
                and os.environ.get("REPLICAI_COPIA_SEGREDO"))


def _cliente():
    """O cliente do armazenamento. Trocado nos testes, como o Asaas e o modelo."""
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("REPLICAI_COPIA_ENDPOINT") or None,
        aws_access_key_id=os.environ["REPLICAI_COPIA_CHAVE"],
        aws_secret_access_key=os.environ["REPLICAI_COPIA_SEGREDO"],
        region_name=os.environ.get("REPLICAI_COPIA_REGIAO", "us-east-1"))


def _balde() -> str:
    return os.environ.get("REPLICAI_COPIA_BUCKET", "")


def _prefixo() -> str:
    p = os.environ.get("REPLICAI_COPIA_PREFIXO", "replicai").strip("/")
    return f"{p}/" if p else ""


def _registro() -> Path:
    from api.trabalhos import pasta_base
    return pasta_base() / "_copia.json"


def ultima() -> dict:
    f = _registro()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _anotar(d: dict) -> None:
    _registro().write_text(json.dumps(d, ensure_ascii=False, indent=1),
                           encoding="utf-8")


def o_que_vai(base: Path) -> list[Path]:
    """Os arquivos que entram na cópia: o mesmo que a faxina guarda.

    Uma regra só, nos dois lugares. Se um dia a faxina passar a guardar mais
    coisa, a cópia leva junto sem ninguém precisar lembrar.
    """
    from api import faxina, trabalhos

    vai: list[Path] = []
    contas = base / "_contas"
    if contas.exists():
        vai += [f for f in contas.rglob("*") if f.is_file()]
    for conta in sorted(base.iterdir()):
        if not conta.is_dir() or conta.name.startswith("_"):
            continue
        for estado_json in sorted(conta.glob("*/trabalho.json")):
            pasta = estado_json.parent
            try:
                estado = json.loads(estado_json.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                estado = {}
            fica = faxina._guardar(estado)
            for alvo in sorted(pasta.rglob("*")):
                if not alvo.is_file():
                    continue
                rel = str(alvo.relative_to(pasta))
                if rel in fica or rel.startswith("pecas/") or rel.startswith("video/"):
                    vai.append(alvo)
    return vai


def montar(destino: Path | None = None) -> dict:
    """Empacota a cópia num .tar.gz. Caminhos relativos à pasta de dados, para
    restaurar ser `tar xzf` em cima dela — sem adivinhação na pior hora."""
    from api.trabalhos import pasta_base

    base = pasta_base()
    arquivos = o_que_vai(base)
    pasta = Path(destino) if destino else Path(tempfile.mkdtemp(prefix="replicai-copia-"))
    pasta.mkdir(parents=True, exist_ok=True)
    nome = f"replicai-{date.today().isoformat()}.tar.gz"
    alvo = pasta / nome
    with tarfile.open(alvo, "w:gz") as tar:
        for f in arquivos:
            tar.add(f, arcname=str(f.relative_to(base)))
    return {"arquivo": alvo, "nome": nome, "arquivos": len(arquivos),
            "tamanho_mb": round(alvo.stat().st_size / 1e6, 2)}


def enviar(arquivo: Path, nome: str) -> str:
    """Manda para o armazenamento e devolve a chave lá dentro."""
    chave = f"{_prefixo()}{nome}"
    _cliente().upload_file(str(arquivo), _balde(), chave)
    return chave


def girar(manter: int = GUARDA) -> list[str]:
    """Apaga as cópias mais velhas. Sem isto o armazenamento cresce para
    sempre, e cópia velha de um sistema que muda todo dia vale pouco."""
    c = _cliente()
    resposta = c.list_objects_v2(Bucket=_balde(), Prefix=_prefixo()) or {}
    chaves = sorted(o["Key"] for o in (resposta.get("Contents") or []))
    sobrando = chaves[:-manter] if manter > 0 else []
    for chave in sobrando:
        c.delete_object(Bucket=_balde(), Key=chave)
    return sobrando


def fazer(mandar: bool = True) -> dict:
    """A cópia do dia, ponta a ponta. Chamada uma vez por dia pelo contêiner."""
    antes = ultima()
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not configurado():
        d = {"quando": agora, "ok": False,
             "porque": "armazenamento não configurado: nenhuma cópia está sendo feita"}
        _anotar({**d, "antes_ok": antes.get("ok")})
        return d

    pacote = None
    try:
        pacote = montar()
        chave = enviar(pacote["arquivo"], pacote["nome"]) if mandar else "(não enviado)"
        apagadas = girar() if mandar else []
        d = {"quando": agora, "ok": True, "chave": chave,
             "arquivos": pacote["arquivos"], "tamanho_mb": pacote["tamanho_mb"],
             "apagadas": len(apagadas)}
    except Exception as e:                      # rede, credencial, disco cheio
        d = {"quando": agora, "ok": False, "porque": f"{type(e).__name__}: {e}"}
    finally:
        # o pacote local morre aqui: cópia que fica no mesmo disco ocupa espaço
        # e não protege contra a máquina morrer, que é o caso que importa
        if pacote and pacote["arquivo"].exists():
            pacote["arquivo"].unlink()
            try:
                pacote["arquivo"].parent.rmdir()
            except OSError:
                pass

    _anotar(d)
    _avisar(antes, d)
    return d


def _avisar(antes: dict, agora: dict) -> dict:
    """Fala quando o estado MUDA: quebrou, ou voltou a funcionar.

    Carta diária dizendo "a cópia falhou de novo" vira carta que ninguém lê —
    e a que avisa que voltou evita alguém mexer no que já está consertado.
    """
    from api import correio

    era, e = antes.get("ok"), agora.get("ok")
    if era == e:
        return {"enviado": False, "porque": "nada mudou"}
    carta = correio.copia_mudou(agora)
    agora["carta"] = carta
    _anotar(agora)
    return carta


def atrasada() -> int | None:
    """Há quantos dias não sai uma cópia boa. Nenhuma cópia jamais é `None`."""
    d = ultima()
    if not d.get("ok"):
        return None if not d else ATRASO_DEMAIS + 1
    try:
        quando = datetime.fromisoformat(d["quando"])
    except (KeyError, ValueError):
        return None
    return (datetime.now(timezone.utc) - quando).days


def em_json() -> dict:
    """O que `/saude` mostra. Cópia que não acontece tem que aparecer."""
    if not configurado():
        return {"estado": "desligada: REPLICAI_COPIA_* não configurado"}
    d = ultima()
    if not d:
        return {"estado": "configurada, mas nenhuma cópia foi feita ainda"}
    if not d.get("ok"):
        return {"estado": "FALHOU", "quando": d.get("quando"),
                "porque": d.get("porque")}
    dias = atrasada()
    estado = "em dia" if (dias is not None and dias <= ATRASO_DEMAIS) else "ATRASADA"
    return {"estado": estado, "quando": d.get("quando"),
            "tamanho_mb": d.get("tamanho_mb"), "arquivos": d.get("arquivos")}


def main(argv: list[str] | None = None) -> int:
    """`python -m api.copia [--sem-enviar]`

    Sem enviar, ele monta o pacote e diz o tamanho: serve para conferir o que
    entraria na cópia antes de ligar o armazenamento.
    """
    from api import ambiente

    ambiente.carregar()
    argv = argv if argv is not None else []
    d = fazer(mandar="--sem-enviar" not in argv)
    if d.get("ok"):
        print(f"cópia: {d['arquivos']} arquivos, {d['tamanho_mb']} MB → {d['chave']}"
              + (f" (apagou {d['apagadas']} antigas)" if d.get("apagadas") else ""))
        return 0
    print(f"cópia: NÃO foi feita — {d.get('porque')}")
    carta = d.get("carta") or {}
    if carta.get("enviado"):
        print("cópia: aviso enviado por e-mail")
    elif carta.get("porque"):
        print(f"cópia: aviso NÃO saiu — {carta['porque']}")
    return 1


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
