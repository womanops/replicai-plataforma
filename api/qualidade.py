"""Verificações de qualidade da composição.

A regra da casa é não cortar conteúdo. Há uma irmã dela, que custou caro
descobrir: **o fundo da peça tem que ser o fundo da arte.** Numa peça de marca o
fundo não é enchimento — é grafismo. A arte do Energiza tem grade quadriculada,
arcos de esfera e textura pontilhada, e eles carregam a identidade tanto quanto
o logo.

Um compositor que escolhe "uma área limpa" da arte para esticar entrega um
degradê liso: tecnicamente a mesma cor, visualmente outra marca. Isso passa em
qualquer validação de cor ou de corte, e só aparece quando alguém olha.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


def estrutura(img: Image.Image | Path | str) -> float:
    """Quanto de desenho estruturado existe na imagem.

    Um borrão leve antes de medir é o que separa grafismo de ruído: grão de
    compressão morre no borrão, grade e arco sobrevivem. Sem ele a conta se
    inverte — um recorte liso e ruidoso pontua mais que um fundo com trama, que
    foi exatamente o que me enganou na primeira medição.
    """
    if not isinstance(img, Image.Image):
        img = Image.open(img)
    a = np.asarray(img.convert("L").filter(ImageFilter.GaussianBlur(1.2)), dtype=float)
    if a.shape[0] < 3 or a.shape[1] < 3:
        return 0.0
    gx = np.abs(np.diff(a, axis=1))[:-1, :]
    gy = np.abs(np.diff(a, axis=0))[:, :-1]
    return float(np.hypot(gx, gy).mean())


def fidelidade_do_fundo(arte: Image.Image | Path | str,
                        fundo: Image.Image | Path | str) -> float:
    """Fração do grafismo da arte que sobrou no fundo da peça. 1.0 = tudo.

    É relativo à arte de propósito: arte lisa pontua baixo nos dois lados e a
    razão continua alta, como deve ser. Quem tem grafismo é cobrado por ele.
    """
    base = estrutura(arte)
    if base <= 0.01:
        return 1.0                      # arte sem grafismo: não há o que perder
    return estrutura(fundo) / base


# Abaixo disto o fundo virou outra coisa. O limite saiu de medir os dois lados
# do mesmo caso: o fundo que o agente compôs ficou em 0.65 e passa; um recorte
# de área lisa ficou em 0.34 e tinha perdido a grade e os arcos a olho nu.
MINIMO_FUNDO = 0.50


def conferir_fundo(arte, fundo) -> tuple[bool, str]:
    f = fidelidade_do_fundo(arte, fundo)
    if f >= MINIMO_FUNDO:
        return True, f"fundo preserva {f*100:.0f}% do grafismo da arte"
    return False, (
        f"o fundo preserva só {f*100:.0f}% do grafismo da arte (mínimo {MINIMO_FUNDO*100:.0f}%). "
        f"Grade, arcos e textura são identidade: estenda o fundo da arte em vez de "
        f"recortar uma área lisa")


# --------------------------------------------------------------------- marca no fundo

def fundo_invade_marca(caixa_fundo, marcas: dict[str, tuple]) -> str | None:
    """O recorte de fundo não pode pegar logo nem lettering.

    Custou uma peça: escolhi uma faixa com bastante grafismo, a conferência de
    estrutura aprovou com 211%, e o banner saiu com o rabo do lettering
    "energiza" fantasma atrás de tudo. Estrutura não distingue textura de texto —
    por isso esta regra existe separada, e as duas têm que valer juntas.
    """
    x0, y0, x1, y1 = caixa_fundo
    for nome, (a, b, c, d) in marcas.items():
        if x0 < c and x1 > a and y0 < d and y1 > b:
            return nome
    return None


# -------------------------------------------------------------- recorte com alfa

def recorte_e_retangulo(img: Image.Image | Path | str, borda: int = 2) -> bool:
    """Diz se o recorte é um bloco opaco em vez de elemento com transparência.

    Marca colada como retângulo aparece na peça com moldura: o fundo que veio
    junto no recorte não bate com o fundo da peça. É o que se vê como "texto
    carimbado". Elemento de marca tem que vir com alfa.
    """
    if not isinstance(img, Image.Image):
        img = Image.open(img)
    if img.mode != "RGBA":
        return True                                  # sem canal alfa: é bloco
    a = np.asarray(img)[:, :, 3]
    if a.size == 0:
        return True
    moldura = np.concatenate([
        a[:borda, :].ravel(), a[-borda:, :].ravel(),
        a[:, :borda].ravel(), a[:, -borda:].ravel(),
    ])
    # se a borda inteira é opaca, o recorte carrega fundo junto
    return bool((moldura > 240).mean() > 0.95)
