"""Trava quem fica tentando senha.

Senha de dez caracteres não resiste a um robô tentando sem parar: o que faz
resistir é a tentativa custar tempo. O `scrypt` já cobra uns 60 ms de quem
confere, e isto cobra o resto — depois de algumas tentativas erradas seguidas,
a porta para de responder por um tempo.

Conta por **endereço de internet e por e-mail ao mesmo tempo**, e por um motivo
cada: pelo endereço, para um robô não varrer mil contas da mesma máquina; pelo
e-mail, para mil máquinas não varrerem a senha de uma conta só. A resposta é a
mesma nos dois casos, e igual à de senha errada: dizer "esta conta está
trancada" conta quais e-mails existem.

Fica na memória do processo, de propósito. Em disco seria mais um arquivo a
escrever a cada tentativa errada — e reiniciar a api para destrancar é um
preço justo, porque reiniciar não é o que um robô consegue fazer.
"""
from __future__ import annotations

import time

JANELA = 15 * 60          # em que prazo as tentativas contam
LIMITE = 8                # quantas erradas antes de trancar
ESPERA = 15 * 60          # quanto tempo a porta fica fechada

_falhas: dict[str, list[float]] = {}
_trancas: dict[str, float] = {}


def _agora() -> float:
    return time.monotonic()


def chaves(ip: str, email: str) -> list[str]:
    """As duas contagens de uma tentativa."""
    saida = []
    if ip:
        saida.append(f"ip:{ip}")
    if email:
        saida.append(f"email:{(email or '').strip().lower()}")
    return saida


def trancada(ip: str = "", email: str = "") -> int:
    """Quantos segundos ainda faltam. Zero quer dizer que pode tentar."""
    agora = _agora()
    falta = 0
    for chave in chaves(ip, email):
        ate = _trancas.get(chave, 0)
        if ate > agora:
            falta = max(falta, int(ate - agora))
        elif chave in _trancas:
            del _trancas[chave]
    return falta


def errou(ip: str = "", email: str = "") -> int:
    """Marca uma tentativa errada. Devolve a espera, se esta foi a que trancou."""
    agora = _agora()
    falta = 0
    for chave in chaves(ip, email):
        tentativas = [t for t in _falhas.get(chave, []) if agora - t < JANELA]
        tentativas.append(agora)
        _falhas[chave] = tentativas
        if len(tentativas) >= LIMITE:
            _trancas[chave] = agora + ESPERA
            _falhas[chave] = []
            falta = max(falta, ESPERA)
    return falta


def acertou(ip: str = "", email: str = "") -> None:
    """Entrou: a contagem zera. Quem sabe a senha não paga pelo robô."""
    for chave in chaves(ip, email):
        _falhas.pop(chave, None)
        _trancas.pop(chave, None)


def esquecer_tudo() -> None:
    """Para os testes, e para quem reinicia a api de propósito."""
    _falhas.clear()
    _trancas.clear()
