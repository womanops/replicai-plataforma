"""Onde o fundo é quieto o bastante para o texto se ler.

Ter espaço não é ter lugar. No 1:1 a faixa de cima ia de ponta a ponta, e a
chama de vidro ocupa metade dela: a data entrava enorme, atravessava o
desenho e sumia dentro dele. Ao lado da chama o fundo é liso, e é ali que a
informação se lê.

A medida é o desvio padrão da luminância por coluna. Na peça que motivou isto,
a chama marcava de 46 a 72 e o gradiente ao lado, de 1 a 26 — não é uma
diferença sutil, é um degrau.

Isto não substitui o aviso de `api/contraste.py`: aquele diz que a peça saiu
com texto sobre desenho; este evita que ela saia assim.
"""
from __future__ import annotations

# acima disto a coluna tem desenho demais para receber texto. Mais exigente
# que o limite do aviso, de propósito: escolher lugar é decisão prévia, avisar
# é constatação depois do fato.
AGITADO = 30

# uma faixa aparada abaixo disto deixa de ser faixa e vira coluna de jornal.
# No leaderboard sobravam 80px ao lado da chama: espaço, sim; lugar, não.
RESTO_MINIMO = 0.45

PASSO = 40


def perfil(imagem, rect, passo: int = PASSO) -> list[tuple[int, int, float]]:
    """Agitação do fundo fatia a fatia, da esquerda para a direita."""
    from PIL import ImageStat
    x0, y0, x1, y1 = (int(v) for v in rect)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(imagem.width, x1), min(imagem.height, y1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return []
    cinza = imagem.convert("L")
    fatias = []
    for x in range(x0, x1, passo):
        fim = min(x1, x + passo)
        if fim - x < 2:
            break
        fatias.append((x, fim, ImageStat.Stat(cinza.crop((x, y0, fim, y1))).stddev[0]))
    return fatias


def trecho_calmo(imagem, rect, limiar: float = AGITADO,
                 resto_minimo: float = RESTO_MINIMO) -> list[int] | None:
    """O maior pedaço seguido de fundo quieto dentro de `rect`.

    Devolve o retângulo aparado, o próprio `rect` quando ele já é todo quieto,
    ou None quando não sobra pedaço que preste — e aí quem chamou decide se
    usa o espaço agitado mesmo ou desiste dele.
    """
    fatias = perfil(imagem, rect)
    if not fatias:
        return list(rect)
    largura = rect[2] - rect[0]

    melhor = atual = None
    for ini, fim, agitacao in fatias:
        if agitacao <= limiar:
            atual = (ini, fim) if atual is None else (atual[0], fim)
            if melhor is None or (atual[1] - atual[0]) > (melhor[1] - melhor[0]):
                melhor = atual
        else:
            atual = None

    if melhor is None:
        return None
    if (melhor[1] - melhor[0]) >= largura * 0.98:
        return list(rect)
    if (melhor[1] - melhor[0]) < largura * resto_minimo:
        return None
    return [melhor[0], rect[1], melhor[1], rect[3]]


def acalmar(imagem, livres: dict) -> tuple[dict, list[str]]:
    """Apara cada faixa livre ao pedaço quieto dela.

    Faixa que não tem pedaço quieto sai da lista: é melhor não oferecer o lugar
    do que oferecer um lugar onde a letra some. Se sobrar nenhuma, devolve as
    originais — peça sem texto é pior do que peça com texto em lugar difícil, e
    o aviso de contraste ainda aparece.
    """
    aparadas, notas = {}, []
    for nome, r in livres.items():
        novo = trecho_calmo(imagem, r)
        if novo is None:
            notas.append(f"a faixa `{nome}` é desenho de ponta a ponta: não cabe texto "
                         f"legível nela")
            continue
        if novo != list(r):
            notas.append(f"a faixa `{nome}` foi encolhida para a parte lisa do fundo")
        aparadas[nome] = novo
    if not aparadas:
        return dict(livres), notas
    return aparadas, notas
