"""A cópia diária do que é dos clientes, guardada fora do servidor.

O backup do provedor é **semanal** e salva a MÁQUINA. O que precisa de proteção
diária é outra coisa: o trabalho entregue. Numa agência que produz 250 peças por
mês, perder o que foi feito desde domingo é uma semana de trabalho que ninguém
tem como devolver — e o cliente pagou por ela.

**Fora do servidor, e não nele.** Cópia no mesmo disco protege contra engano
(alguém apagou uma pasta) e não protege contra o que realmente acontece: a
máquina morrer. Por isso daqui ela sai para um armazenamento de objetos.

**É espelho, não pacote diário.** A primeira versão empacotava tudo todo dia e
guardava as últimas catorze — e isso custaria **catorze vezes** o tamanho dos
dados, porque peça entregue nunca muda. Medido na tabela da Magalu, a R$ 0,10
por GB: com dez clientes por um ano, R$ 102 por mês de pacotes contra **R$ 7,29
de espelho**. Então cada arquivo sobe uma vez e fica; o que já está lá não sobe
de novo.

**O que muda ganha versão.** As contas mudam (plano, senha, medidas, fontes), e
para elas um espelho não basta: um arquivo corrompido hoje apagaria o bom. Elas
sobem também como pacote datado, que é minúsculo e guarda as últimas catorze.

**O que vai é o que a faxina guarda**: as contas e, de cada trabalho, as peças
entregues, os vídeos, a apresentação e os JSONs da montagem. O material bruto
fica de fora de propósito — ele já tem prazo de validade de 30 dias e é 85% do
disco. Copiar o que vai ser apagado é pagar armazenamento para guardar lixo.

**Nada é apagado de lá porque sumiu daqui.** Backup que apaga o que foi apagado
não protege do engano, que é metade do motivo de existir.

Sem armazenamento configurado nada acontece, e `/saude` diz isso em letras: uma
cópia que ninguém sabe que não está acontecendo é pior do que nenhuma.
"""
from __future__ import annotations

import hashlib
import json
import os
import tarfile
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

GUARDA_CONTAS = int(os.environ.get("REPLICAI_COPIAS", "14"))   # versões das contas
ATRASO_DEMAIS = 2                                              # dias sem cópia = defeito
ARQUIVOS = "arquivos/"                                         # o espelho
CONTAS = "contas/"                                             # as versões datadas


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
    d = _tudo()
    return d.get("ultima") or {}


def _tudo() -> dict:
    f = _registro()
    if not f.exists():
        return {}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return d if isinstance(d, dict) else {}


def _anotar(ultima: dict, enviados: dict | None = None) -> None:
    d = _tudo()
    d["ultima"] = ultima
    if enviados is not None:
        d["enviados"] = enviados
    _registro().write_text(json.dumps(d, ensure_ascii=False, indent=1),
                           encoding="utf-8")


def _marca(f: Path) -> str:
    """Como saber que o arquivo mudou. Tamanho basta para peça entregue, que
    nunca muda; as contas são pequenas e ganham resumo de verdade."""
    st = f.stat()
    if f.suffix == ".json" and st.st_size < 2_000_000:
        return hashlib.sha256(f.read_bytes()).hexdigest()[:16]
    return f"{st.st_size}"


def o_que_vai(base: Path) -> list[Path]:
    """Os arquivos que entram na cópia: o mesmo que a faxina guarda.

    Uma regra só, nos dois lugares. Se um dia a faxina passar a guardar mais
    coisa, a cópia leva junto sem ninguém precisar lembrar.
    """
    from api import faxina

    vai: list[Path] = []
    contas = base / "_contas"
    if contas.exists():
        vai += [f for f in sorted(contas.rglob("*")) if f.is_file()]
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


def espelhar(mandar: bool = True) -> dict:
    """Sobe o que ainda não está lá. Devolve o que subiu e o que já estava."""
    from api.trabalhos import pasta_base

    base = pasta_base()
    enviados = _tudo().get("enviados") or {}
    c = _cliente() if mandar else None
    novos, bytes_novos = [], 0
    try:
        for f in o_que_vai(base):
            rel = str(f.relative_to(base))
            marca = _marca(f)
            if enviados.get(rel) == marca:
                continue                  # já está lá, igualzinho
            if c:
                c.upload_file(str(f), _balde(), f"{_prefixo()}{ARQUIVOS}{rel}")
            # anotado DEPOIS de subir: marcar antes faria o arquivo que falhou
            # nunca mais ser tentado, e o buraco só apareceria na restauração
            enviados[rel] = marca
            novos.append(rel)
            bytes_novos += f.stat().st_size
            # de cinquenta em cinquenta o progresso vai para o disco: a
            # primeira cópia de uma carteira grande leva horas, e uma queda no
            # fim não pode mandar tudo de volta para o começo
            if len(novos) % 50 == 0:
                _anotar(ultima(), enviados)
    finally:
        _anotar(ultima(), enviados)
    return {"novos": len(novos), "ja_estavam": len(enviados) - len(novos),
            "mb_novos": round(bytes_novos / 1e6, 2)}


def versionar_contas(mandar: bool = True) -> dict:
    """As contas, datadas. Elas MUDAM: espelho sozinho apagaria o bom com o
    corrompido, e conta perdida é cliente perdido."""
    from api.trabalhos import pasta_base

    base = pasta_base() / "_contas"
    if not base.exists():
        return {"versao": None, "porque": "ainda não há contas"}
    pasta = Path(tempfile.mkdtemp(prefix="replicai-contas-"))
    nome = f"contas-{date.today().isoformat()}.tar.gz"
    alvo = pasta / nome
    try:
        with tarfile.open(alvo, "w:gz") as tar:
            tar.add(base, arcname="_contas")
        tamanho = round(alvo.stat().st_size / 1e6, 3)
        if mandar:
            _cliente().upload_file(str(alvo), _balde(), f"{_prefixo()}{CONTAS}{nome}")
    finally:
        if alvo.exists():
            alvo.unlink()
        try:
            pasta.rmdir()
        except OSError:
            pass
    return {"versao": nome, "mb": tamanho,
            "apagadas": len(girar_contas()) if mandar else 0}


def girar_contas(manter: int = GUARDA_CONTAS) -> list[str]:
    """Só as versões das contas giram. O espelho das peças não gira: nada é
    apagado de lá porque sumiu daqui."""
    c = _cliente()
    resposta = c.list_objects_v2(Bucket=_balde(), Prefix=f"{_prefixo()}{CONTAS}") or {}
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
        _anotar(d)
        return d
    try:
        espelho = espelhar(mandar)
        contas = versionar_contas(mandar)
        d = {"quando": agora, "ok": True, **espelho,
             "contas": contas.get("versao"), "contas_mb": contas.get("mb")}
    except Exception as e:                  # rede, credencial, balde errado
        d = {"quando": agora, "ok": False, "porque": f"{type(e).__name__}: {e}"}
    _anotar(d)
    _avisar(antes, d)
    return d


def _avisar(antes: dict, agora: dict) -> dict:
    """Fala quando o estado MUDA: quebrou, ou voltou a funcionar.

    Carta diária dizendo "a cópia falhou de novo" vira carta que ninguém lê —
    e a que avisa que voltou evita alguém mexer no que já está consertado.
    """
    from api import correio

    if antes.get("ok") == agora.get("ok"):
        return {"enviado": False, "porque": "nada mudou"}
    carta = correio.copia_mudou(agora)
    agora["carta"] = carta
    _anotar(agora)
    return carta


def atrasada() -> int | None:
    """Há quantos dias não sai uma cópia boa. Nenhuma cópia jamais é `None`."""
    d = ultima()
    if not d:
        return None
    if not d.get("ok"):
        return ATRASO_DEMAIS + 1
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(d["quando"])).days
    except (KeyError, ValueError):
        return None


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
    return {"estado": "em dia" if (dias is not None and dias <= ATRASO_DEMAIS)
                      else "ATRASADA",
            "quando": d.get("quando"), "novos": d.get("novos"),
            "guardados": d.get("ja_estavam", 0) + d.get("novos", 0),
            "contas": d.get("contas")}


def main(argv: list[str] | None = None) -> int:
    """`python -m api.copia [--sem-enviar]`

    Sem enviar, ele percorre o que subiria e diz quanto é: serve para conferir
    antes de ligar o armazenamento.
    """
    from api import ambiente

    ambiente.carregar()
    argv = argv if argv is not None else []
    d = fazer(mandar="--sem-enviar" not in argv)
    if d.get("ok"):
        print(f"cópia: {d['novos']} arquivos novos ({d['mb_novos']} MB), "
              f"{d['ja_estavam']} já estavam lá · contas em {d.get('contas')}")
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
