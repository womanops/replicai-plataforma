"""O texto precisa se ler contra o que está atrás dele.

Posicionar bem não basta: branco sobre o brilho da gota de vidro some igual.
Aqui a peça é conferida contra o fundo que ela vai usar — não contra a cor
que alguém supôs — e a cor do texto é corrigida quando dá, com aviso quando
não dá.

A régua é a da acessibilidade (WCAG): 4,5 para texto, 3 para elemento
gráfico. Não é gosto, é o mínimo para alguém conseguir ler no celular, na
rua, com o sol batendo.
"""
from __future__ import annotations

from pathlib import Path

CLARO = "#ffffff"
ESCURO = "#101828"
TEXTO_MINIMO = 4.5
GRAFICO_MINIMO = 3.0
# acima disto o fundo sob a caixa é agitado demais: trocar a cor não resolve,
# porque metade da área continua parecida com a letra
AGITADO = 46


def _rgb(cor: str) -> tuple[int, int, int]:
    c = (cor or "").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return (255, 255, 255)
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def luminancia(cor) -> float:
    """Luminância relativa, a da fórmula do WCAG."""
    r, g, b = _rgb(cor) if isinstance(cor, str) else cor

    def canal(v):
        v = v / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def razao(a, b) -> float:
    la, lb = luminancia(a), luminancia(b)
    claro, escuro = max(la, lb), min(la, lb)
    return (claro + 0.05) / (escuro + 0.05)


def melhor(fundo) -> str:
    """A cor de texto que mais se destaca deste fundo."""
    return ESCURO if razao(ESCURO, fundo) >= razao(CLARO, fundo) else CLARO


def sob_a_caixa(imagem, box: dict) -> tuple[tuple[int, int, int], float]:
    """Cor média e agitação do fundo sob uma caixa."""
    from PIL import ImageStat
    x0 = max(0, int(box["x"])); y0 = max(0, int(box["y"]))
    x1 = min(imagem.width, x0 + int(box["w"])); y1 = min(imagem.height, y0 + int(box["h"]))
    if x1 <= x0 or y1 <= y0:
        return (0, 0, 0), 0.0
    st = ImageStat.Stat(imagem.crop((x0, y0, x1, y1)).convert("RGB"))
    media = tuple(int(v) for v in st.mean)
    agitacao = sum(st.stddev) / 3
    return media, agitacao


def ajustar(peca: dict, fundo: Path) -> list[str]:
    """Corrige a cor do que não se lê e avisa o que a cor não resolve."""
    from PIL import Image

    caminho = Path(fundo)
    if not caminho.exists():
        return []
    avisos = []
    with Image.open(caminho) as im:
        im = im.convert("RGB")
        if (im.width, im.height) != (peca["canvas"]["w"], peca["canvas"]["h"]):
            im = im.resize((peca["canvas"]["w"], peca["canvas"]["h"]))
        for e in peca.get("elementos", []):
            box = e.get("box")
            if not box or e.get("tipo") not in ("texto", "botao"):
                continue
            atras, agitacao = sob_a_caixa(im, box)

            if e["tipo"] == "botao":
                # o que precisa se destacar do fundo é o corpo do botão; o
                # texto se resolve contra o corpo, que é cor chapada
                if razao(e.get("fundo", CLARO), atras) < GRAFICO_MINIMO:
                    e["fundo"] = melhor(atras)
                e["cor"] = melhor(e["fundo"])
                continue

            if razao(e.get("cor", CLARO), atras) < TEXTO_MINIMO:
                e["cor"] = melhor(atras)
                if razao(e["cor"], atras) < TEXTO_MINIMO:
                    avisos.append(
                        f"`{e.get('papel')}` fica em cima de um fundo de contraste baixo "
                        f"e não há cor de texto que resolva: mova o bloco ou escureça a "
                        f"área atrás dele")
            if agitacao > AGITADO:
                avisos.append(
                    f"`{e.get('papel')}` cai sobre uma parte agitada da imagem: a letra "
                    f"vai brigar com o desenho atrás, mesmo com a cor certa")
    return avisos

# ---------------------------------------------------------------------------
# a letra que veio no arquivo

def tom_da_tinta(caminho) -> tuple[int, int, int] | None:
    """A cor da tinta de uma camada: a média dos pixels opacos dela.

    Pela média do PNG inteiro não dá: a camada é quase toda transparente, e o
    fundo transparente puxaria a cor para o preto.
    """
    from PIL import Image

    caminho = Path(caminho)
    if not caminho.exists():
        return None
    try:
        with Image.open(caminho) as im:
            px = im.convert("RGBA")
    except Exception:
        return None
    import numpy as np
    a = np.asarray(px, dtype=float)
    opaco = a[..., 3] > 128
    if not opaco.any():
        return None
    return tuple(int(v) for v in a[..., :3][opaco].mean(axis=0))


# o lockup é texto grande — o piso do WCAG para texto grande é 3, não 4,5.
# Exigir 4,5 reprovaria arte legítima: muito KV põe branco sobre azul médio e
# se lê perfeitamente no tamanho em que a peça é vista.
LOCKUP_MINIMO = GRAFICO_MINIMO


# quanto da letra pode ficar sem contraste antes de a linha deixar de ser lida.
# Pela média da caixa não dá: um lockup largo atravessa fundo escuro e fundo
# claro, a média diz "ótimo" e a palavra some no meio. É o mesmo erro da
# mediana na régua de cor do fundo — média esconde mancha.
TINTA_NO_ESCURO = 0.25


def le_sobre(imagem, box: dict, tinta, camada=None) -> float:
    """A razão de contraste entre a tinta e o que ficou atrás dela.

    Com `camada` a conta é feita **onde a letra está**, pixel a pixel da máscara
    dela, e não na média do retângulo.
    """
    if camada is None:
        atras, _ = sob_a_caixa(imagem, box)
        return razao(tinta, atras)
    medida = sob_a_tinta(imagem, box, camada, tinta)
    return medida[0] if medida else razao(tinta, sob_a_caixa(imagem, box)[0])


def sob_a_tinta(imagem, box: dict, camada, tinta=None):
    """(razão típica, quanto da letra está sem contraste) — pela máscara dela.

    Devolve `None` quando a camada não abre ou não tem pixel opaco.
    """
    from PIL import Image

    import numpy as np
    if isinstance(camada, Image.Image):
        arte = camada.convert("RGBA")
        if arte.size != (max(1, int(box["w"])), max(1, int(box["h"]))):
            arte = arte.resize((max(1, int(box["w"])), max(1, int(box["h"]))),
                               Image.Resampling.LANCZOS)
    else:
        camada = Path(camada)
        if not camada.exists():
            return None
        try:
            with Image.open(camada) as im:
                arte = im.convert("RGBA").resize(
                    (max(1, int(box["w"])), max(1, int(box["h"]))),
                    Image.Resampling.LANCZOS)
        except Exception:
            return None
    a = np.asarray(arte, dtype=float)
    mascara = a[..., 3] > 128
    if not mascara.any():
        return None

    x0, y0 = max(0, int(box["x"])), max(0, int(box["y"]))
    x1 = min(imagem.width, x0 + int(box["w"]))
    y1 = min(imagem.height, y0 + int(box["h"]))
    if x1 <= x0 or y1 <= y0:
        return None
    atras = np.asarray(imagem.crop((x0, y0, x1, y1)).convert("RGB"), dtype=float)
    mascara = mascara[:atras.shape[0], :atras.shape[1]]
    if not mascara.any():
        return None

    def lum(px):
        c = px / 255
        c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]

    lf = lum(atras)[mascara]
    lt = (lum(np.asarray(_rgb(tinta) if isinstance(tinta, str) else tinta,
                         dtype=float)[None, None, :])[0, 0]
          if tinta is not None else lum(a[..., :3][:atras.shape[0], :atras.shape[1]])[
              mascara])
    claro, escuro = np.maximum(lf, lt), np.minimum(lf, lt)
    r = (claro + 0.05) / (escuro + 0.05)
    return float(np.median(r)), float((r < LOCKUP_MINIMO).mean())


# como se chama, na tela, o que cada papel é. Nome de camada do Photoshop é
# lixo de arquivo ("04-energia-que-impulsiona-o-futuro-copiar") e não ajuda
# ninguém a achar o bloco na peça.
NA_PECA = {"headline": "o título", "apoio": "a linha de apoio", "selo": "o selo",
           "marca": "a marca", "cta": "a chamada"}


def _atras_da_tinta(peca: dict, fundo: Path, pasta: Path):
    """Vai empilhando a peça e, antes de cada bloco de texto, entrega o que
    ficou ATRÁS dele: a prancheta mais todas as camadas de baixo.

    Medir contra o arquivo de fundo sozinho foi o erro que encheu a peça de
    ressalva falsa: num PSD a prancheta costuma ser branca e a arte vem em
    camada por cima. A letra branca era medida contra o branco da prancheta,
    dava contraste 1.0, e a régua acusava treze vezes uma peça impecável.
    """
    from PIL import Image

    larg, alt = peca["canvas"]["w"], peca["canvas"]["h"]
    with Image.open(fundo) as im:
        tela = im.convert("RGBA")
    if tela.size != (larg, alt):
        tela = tela.resize((larg, alt), Image.Resampling.LANCZOS)

    for e in peca.get("elementos", []):
        if e.get("tipo") != "imagem" or not e.get("src") or not e.get("box"):
            continue
        if e.get("papel") in NA_PECA:
            yield e, tela.convert("RGB")
        b = e["box"]
        arq = Path(pasta) / e["src"]
        if not arq.exists():
            continue
        try:
            with Image.open(arq) as im:
                parte = im.convert("RGBA").resize(
                    (max(1, int(b["w"])), max(1, int(b["h"]))),
                    Image.Resampling.LANCZOS)
        except Exception:
            continue
        # mistura de camada a régua não refaz: o que ela precisa saber é se a
        # área atrás é clara ou escura, e para isso a opacidade já basta
        op = float(e.get("opacidade") or 1)
        if op < 1:
            canal = parte.getchannel("A").point(lambda v: int(v * op))
            parte.putalpha(canal)
        tela.alpha_composite(parte, (int(b["x"]), int(b["y"])))


def do_lockup(peca: dict, fundo: Path, pasta: Path) -> list[str]:
    """Confere a letra que veio em camada contra o que ficou atrás dela.

    `ajustar` cuida do texto que a plataforma escreve, e cuida trocando a cor.
    O lockup do arquivo é imagem: a cor dele é do cliente e não se troca. Então
    aqui só dá para medir e dizer — e quem escolhe zona (recompor) usa a mesma
    conta ANTES, para não cair num lugar onde a letra some.

    Foi o lockup branco em cima da faixa branca do 970x250: a régua de sossego
    aprovou, porque fundo liso ela mede; contraste ela não media.

    Uma linha por BLOCO, não por letra. O texto do PSD é fatiado em letras para
    o lettering animar uma a uma, e a régua rodava em cada pedaço: treze linhas
    idênticas na mesma peça, dizendo a mesma coisa.
    """
    caminho = Path(fundo)
    if not caminho.exists():
        return []

    pior: dict[str, tuple] = {}
    for e, atras in _atras_da_tinta(peca, caminho, pasta):
        tinta = tom_da_tinta(Path(pasta) / e["src"])
        if tinta is None:
            continue
        medida = sob_a_tinta(atras, e["box"], Path(pasta) / e["src"], tinta)
        if medida is None:
            continue
        tipico, no_escuro = medida
        if tipico >= LOCKUP_MINIMO and no_escuro < TINTA_NO_ESCURO:
            continue
        bloco = e.get("de") or e.get("camada") or e.get("papel") or ""
        # a nota do bloco é a do pior pedaço dele: é a letra que some que
        # estraga a palavra, não a média das letras
        if bloco not in pior or tipico < pior[bloco][1]:
            pior[bloco] = (e.get("papel"), tipico, no_escuro)

    avisos = []
    for papel, tipico, no_escuro in pior.values():
        quanto = (f"contraste {tipico:.1f}, o mínimo é {LOCKUP_MINIMO:.0f}"
                  if tipico < LOCKUP_MINIMO else
                  f"{round(no_escuro * 100)}% da letra sem contraste")
        avisos.append(f"{NA_PECA.get(papel, papel)} não se lê sobre o fundo "
                      f"({quanto}). Mova o bloco no ajuste")
    return avisos
