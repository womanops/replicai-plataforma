"""Os e-mails que o sistema manda sozinho.

São três, e todos nascem de um fato, nunca de um clique: o acesso quando o
pagamento é aprovado, o convite quando alguém é chamado para a conta, e o aviso
quando a cobrança atrasa. Cliente que perde acesso sem aviso liga bravo, e com
razão.

**Nenhum deles leva senha.** O que vai é um endereço de uso único com prazo, e
a senha nasce escolhida por quem recebeu. Senha mandada por e-mail fica
guardada para sempre na caixa de entrada, no telefone e no backup de quem
recebeu — vazar o e-mail passa a vazar a conta.

O envio entra de fora, como a cobrança e o modelo: aqui só se monta a carta. O
provedor é o Resend, escolhido por ser transacional (e-mail de sistema saindo
de caixa comum cai em spam). **Sem chave configurada o e-mail é gravado em
arquivo** e `/saude` diz que o correio está desligado — assim o caminho inteiro
é testável antes de existir domínio, e um e-mail que não saiu nunca passa por
e-mail que saiu.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RESEND = "https://api.resend.com/emails"
TEMPO = 15


class CorreioIndisponivel(RuntimeError):
    """O provedor não respondeu. Quem chamou decide o que dizer."""


def chave() -> str:
    return os.environ.get("RESEND_API_KEY", "").strip()


def remetente() -> str:
    """De quem o e-mail sai. Precisa ser um endereço do domínio verificado."""
    return os.environ.get("REPLICAI_EMAIL_DE", "").strip()


def configurado() -> bool:
    return bool(chave() and remetente())


def pasta() -> Path:
    """Onde os e-mails ficam quando não há provedor configurado."""
    from api.contas import pasta as das_contas
    p = das_contas().parent / "_correio"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _chamar(corpo: dict) -> dict:
    """A chamada HTTP, separada para o teste trocar sem rede e sem chave."""
    pedido = urllib.request.Request(
        RESEND, data=json.dumps(corpo).encode(),
        headers={"Authorization": f"Bearer {chave()}",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(pedido, timeout=TEMPO) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode(errors="replace")[:300]
        raise CorreioIndisponivel(f"o Resend recusou: {e.code} {detalhe}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise CorreioIndisponivel(f"não falei com o Resend: {e}") from e


def _guardar(para: str, assunto: str, texto: str) -> Path:
    marca = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    seguro = "".join(ch if ch.isalnum() or ch in "@.-_" else "_" for ch in para)
    f = pasta() / f"{marca}-{seguro}.txt"
    f.write_text(f"Para: {para}\nAssunto: {assunto}\n\n{texto}\n", encoding="utf-8")
    return f


def enviar(para: str, assunto: str, texto: str) -> dict:
    """Manda a carta, ou grava em arquivo se não houver provedor.

    Nunca levanta por falta de configuração: a aprovação de um pagamento não
    pode falhar porque o e-mail não está pronto. O que ela não pode é mentir —
    daí o `enviado: False` e o arquivo no disco.
    """
    if not configurado():
        return {"enviado": False, "porque": "correio não configurado",
                "arquivo": str(_guardar(para, assunto, texto))}
    try:
        r = _chamar({"from": remetente(), "to": [para],
                     "subject": assunto, "text": texto})
    except CorreioIndisponivel as e:
        # o provedor fora do ar não pode engolir o acesso de um cliente que
        # acabou de pagar: fica no disco para ser reenviado à mão
        return {"enviado": False, "porque": str(e),
                "arquivo": str(_guardar(para, assunto, texto))}
    return {"enviado": True, "id": r.get("id", "")}


# ------------------------------------------------------------- as cartas

def painel() -> str:
    """O endereço do painel. Sem ele configurado, o e-mail diria 'entre em ' e
    mais nada — melhor falhar na configuração que mandar carta torta."""
    return os.environ.get("REPLICAI_PAINEL", "").strip()


def _endereco_do_convite(convite: str) -> str:
    base = painel().rstrip("/")
    return f"{base}/senha?convite={convite}" if base else f"/senha?convite={convite}"


def _onde_entrar(email: str) -> str:
    """A frase do "depois disso". Sem endereço configurado ela não finge ter
    um: "você entra em no painel" é carta torta chegando no cliente."""
    base = painel().rstrip("/")
    if base:
        return f"Depois disso, você entra em {base} com o e-mail {email}."
    return f"Depois disso, seu login é o e-mail {email}."


def acesso_liberado(conta, convite: str, plano_nome: str) -> dict:
    """O e-mail que chega quando o pagamento é aprovado."""
    texto = (
        f"{conta.nome}, seu acesso à ReplicAI está pronto.\n\n"
        f"Plano {plano_nome}, já ativo.\n\n"
        f"Crie sua senha neste endereço (vale por 48 horas):\n"
        f"{_endereco_do_convite(convite)}\n\n"
        f"{_onde_entrar(conta.email)}\n\n"
        "Qualquer coisa, responda este e-mail.")
    return enviar(conta.email, "Seu acesso à ReplicAI", texto)


def convite_de_pessoa(conta, pessoa: dict, convite: str) -> dict:
    """O e-mail de quem foi chamado para a conta da agência."""
    texto = (
        f"{pessoa['nome']}, você foi incluída no acesso da {conta.nome} à ReplicAI.\n\n"
        f"Crie sua senha neste endereço (vale por 48 horas):\n"
        f"{_endereco_do_convite(convite)}\n\n"
        f"{_onde_entrar(pessoa['email'])}\n\n"
        "As campanhas e o saldo de peças são os mesmos da agência.")
    return enviar(pessoa["email"], f"Seu acesso à ReplicAI — {conta.nome}", texto)


def cobranca_atrasada(conta, quando: str = "") -> dict:
    """O aviso de atraso. Vai para o financeiro, se houver, e para o dono."""
    texto = (
        f"{conta.nome}, a cobrança da ReplicAI não foi confirmada"
        f"{f' (vencimento {quando})' if quando else ''}.\n\n"
        "A produção de peças novas fica suspensa até a confirmação. O que já "
        "foi produzido continua disponível para download.\n\n"
        "Se o pagamento já foi feito, pode ignorar: a confirmação às vezes "
        "leva um dia útil.")
    para = conta.email_financeiro or conta.email
    return enviar(para, "Cobrança da ReplicAI não confirmada", texto)
