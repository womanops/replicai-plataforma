"""Cortar lettering de imagem em letras, para elas animarem uma a uma.

A camada de texto do PSD chega rasterizada: é imagem, não palavra. Animar
imagem inteira entrando é transição de slide, não motion — e com lettering
desenhado, que é o caso de quase todo Key Visual, não há como retipografar:
a fonte é da marca e quase nunca está na máquina.

A saída é cortar o próprio desenho. O alfa já separa as letras: onde não há
tinta, há coluna vazia. No lettering do Energiza isso dá oito blocos para oito
letras, e quatro para "2027" — e cada pedaço continua sendo o desenho
original, não uma aproximação retipografada.

Primeiro as linhas, depois as colunas dentro de cada linha: numa assinatura de
três linhas, projetar colunas direto misturaria as três.
"""
from __future__ import annotations

# abaixo disto a coluna conta como vazia. Não é zero porque anti-serrilhado
# deixa um fio de alfa entre letras que se tocam
LIMIAR = 0.02

# pedaço cuja tinta termina acima disto da faixa é acento solto — til, crase,
# circunflexo — e vai junto da letra. Largura não serve de régua: o "i" é tão
# estreito quanto um acento e é letra inteira, e foi assim que "energiza"
# perdeu uma letra na primeira versão.
ACENTO_ATE = 0.55

# faixa de linha mais baixa que isto da maior é acento ou pingo, não linha de
# texto: o pingo do "i" fica acima da altura-x e formava uma linha só dele,
# virando uma nona letra em "energiza"
LINHA_BAIXA = 0.35


def _blocos(soma, limite: float, minimo: int = 1) -> list[tuple[int, int]]:
    """Trechos seguidos em que há tinta."""
    blocos, ini = [], None
    for i, v in enumerate(soma):
        cheio = v > limite
        if cheio and ini is None:
            ini = i
        elif not cheio and ini is not None:
            if i - ini >= minimo:
                blocos.append((ini, i))
            ini = None
    if ini is not None and len(soma) - ini >= minimo:
        blocos.append((ini, len(soma)))
    return blocos


def linhas(alfa) -> list[tuple[int, int]]:
    """As faixas horizontais com tinta, com acento junto da linha dele."""
    soma = alfa.sum(1)
    achadas = _blocos(soma, soma.max() * LIMIAR if soma.max() else 0)
    if len(achadas) < 2:
        return achadas
    alta = max(b - a for a, b in achadas)
    juntas: list[list[int]] = []
    for a, b in achadas:
        if (b - a) < alta * LINHA_BAIXA and not juntas:
            juntas.append([a, b])      # começa baixa: espera a próxima para fundir
            continue
        if juntas and (juntas[-1][1] - juntas[-1][0]) < alta * LINHA_BAIXA:
            juntas[-1][1] = b          # a faixa baixa era acento da que vem abaixo
        else:
            juntas.append([a, b])
    return [(a, b) for a, b in juntas]


def _so_no_alto(faixa, a: int, b: int) -> bool:
    """A tinta deste trecho acaba na parte de cima da faixa? Então é acento."""
    import numpy as np
    pedaco = faixa[:, a:b]
    linhas_com_tinta = np.nonzero(pedaco.sum(1) > 0)[0]
    if not len(linhas_com_tinta):
        return False
    return linhas_com_tinta[-1] < faixa.shape[0] * ACENTO_ATE


def letras(alfa, y0: int, y1: int) -> list[tuple[int, int]]:
    """As colunas com tinta dentro de uma linha, com acento junto da letra."""
    faixa = alfa[y0:y1]
    soma = faixa.sum(0)
    if not soma.max():
        return []
    achados = _blocos(soma, soma.max() * LIMIAR)
    if not achados:
        return []
    juntos: list[list[int]] = []
    for a, b in achados:
        if _so_no_alto(faixa, a, b) and juntos:
            juntos[-1][1] = b          # acento à direita da letra
        elif _so_no_alto(faixa, a, b) and len(achados) > 1:
            juntos.append([a, b])      # acento antes de tudo: espera a letra
        else:
            if juntos and _so_no_alto(faixa, *juntos[-1]):
                juntos[-1][1] = b      # a anterior era acento desta letra
            else:
                juntos.append([a, b])
    return [(a, b) for a, b in juntos]


def fatiar(caminho, destino, prefixo: str = "letra", modo: str = "letra") -> list[dict]:
    """Corta a imagem. Devolve [{src, dx, dy, w, h}] relativo à peça.

    `modo="letra"` corta letra a letra; `modo="linha"` corta só as linhas, que
    é o que serve para assinatura miúda: trinta letras entrando uma a uma
    levam mais tempo do que a peça tem, e ninguém lê letra de 20px solta.

    Sem nada para cortar — uma letra só, ou imagem que não é lettering —
    devolve lista vazia, e quem chamou segue com a camada inteira.
    """
    import numpy as np
    from PIL import Image
    from pathlib import Path

    caminho, destino = Path(caminho), Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    with Image.open(caminho) as im:
        im = im.convert("RGBA")
        alfa = np.asarray(im)[..., 3].astype("int32")
        pedacos = []
        for li, (y0, y1) in enumerate(linhas(alfa)):
            if modo == "linha":
                faixa = alfa[y0:y1].sum(0)
                cheias = np.nonzero(faixa > 0)[0]
                cortes = [(int(cheias[0]), int(cheias[-1]) + 1)] if len(cheias) else []
            else:
                cortes = letras(alfa, y0, y1)
            for ci, (x0, x1) in enumerate(cortes):
                nome = f"{prefixo}-{li:02d}{ci:02d}.png"
                im.crop((x0, y0, x1, y1)).save(destino / nome)
                pedacos.append({"src": nome, "dx": int(x0), "dy": int(y0),
                                "w": int(x1 - x0), "h": int(y1 - y0)})
    return pedacos if len(pedacos) > 1 else []
