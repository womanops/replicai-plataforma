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
