"""O fundo de cada formato, antes de qualquer texto.

A plataforma vinha mandando a arte crua para o render com `fit: cover`. Cover
corta: numa peça 1:1 vinda de uma 16:9, o "energiza" virou "energ". E como o
fundo é a arte inteira, com lettering e marca dentro, o texto novo caía em
cima do texto antigo.

Aqui o fundo é montado primeiro, com duas garantias:

- **nada é cortado** — o quadro cresce em vez de aparar, que é a regra da casa;
- **sobra lugar** — a extensão cria faixa vazia, e é só nela que o texto novo
  entra. Sem sobreposição por construção, sem precisar apagar nada da arte.

Apagar o texto do fundo seria o outro caminho, e é o que o Studio faz. Nesta
família de arte ele cobra caro: o `clean` leva a grade e o pontilhado junto com
as letras. Fundo intacto e texto ao lado sai melhor.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from PIL import ImageOps

from motor.replica import (_blur_canvas, _mirror_side, _outpaint_higgsfield, _solid_canvas,
                           _stretch_side, _to_target_coords, higgsfield_status, open_rgb,
                           plan_fit)

MODOS = ("outpaint", "stretch", "mirror", "blur", "solid", "none")

# acima disto a peça vira moldura: arte no meio e tapume em volta. Medido na
# família Energiza — 44% de faixa (1:1) ainda lê como bloco de cor de propósito,
# 68% (9:16) lê como erro.
FAIXA_DEMAIS = 0.50

# quanto da área segura a tinta pode ocupar. Caber na área segura não basta:
# encostada na borda ela lê como erro de margem, e num aparelho menor a
# interface do app come o canto.
RESPIRO = 0.86


def escolher_estrategia(W: int, H: int, w: int, h: int, protegido=None) -> tuple[str, str]:
    """Preservar tudo (`contain`) enquanto a faixa vazia não dominar a peça;
    depois disso, reenquadrar protegendo a tinta (`smart`).

    Nenhuma das duas corta tinta. A diferença é o que se sacrifica quando a
    proporção muda muito: `contain` sacrifica área de peça, `smart` sacrifica
    imagem que está fora da região protegida.
    """
    plano = plan_fit(W, H, w, h, protegido, "contain", (0.5, 0.5), 0.0)
    caixa = _to_target_coords(plano, W, H, w, h, protegido)["base_box"]
    vazio = 1 - ((caixa[2] - caixa[0]) * (caixa[3] - caixa[1])) / (w * h)
    if vazio <= FAIXA_DEMAIS:
        return "contain", f"a arte inteira cabe deixando {round(vazio * 100)}% de faixa"
    return "smart", f"a arte inteira deixaria {round(vazio * 100)}% de faixa vazia"


class FundoImpossivel(RuntimeError):
    """O fundo pedido não saiu. Melhor dizer do que entregar outro no lugar."""


def _com_respiro(protegido, formato: dict, W: int, H: int):
    """Infla a região protegida para que, no enquadramento, a tinta caia dentro
    da área segura — e não encostada na borda.

    Proteger só contra o corte não basta: o lockup ficava rente às laterais, e
    num aparelho menor a interface come a borda. Inflar na proporção da área
    segura faz o enquadramento afastar na medida exata, sem precisar de número
    mágico. Preso ao limite da arte, o que faltar vira extensão.
    """
    if not protegido:
        return None
    s = formato["safe"]
    larg = max(1, formato["w"] - s["left"] - s["right"])
    alt = max(1, formato["h"] - s["top"] - s["bottom"])
    fx, fy = formato["w"] / (larg * RESPIRO), formato["h"] / (alt * RESPIRO)
    x0, y0, x1, y1 = protegido
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    nw, nh = (x1 - x0) * fx / 2, (y1 - y0) * fy / 2
    return (max(0, round(cx - nw)), max(0, round(cy - nh)),
            min(W, round(cx + nw)), min(H, round(cy + nh)))


def preparar(arte: Path, formato: dict, protegido=None, destino: Path | None = None,
             estrategia: str = "auto", folga: float = 0.0, modo: str = "auto",
             cor: str | None = None) -> dict:
    """Monta o fundo de `formato` a partir de `arte` e diz onde sobrou espaço.

    `protegido` é a caixa (x0,y0,x1,y1, em pixels da arte) que não pode ser
    cortada — a tinta que a peça já carrega. Devolve o caminho do fundo e, em
    coordenadas da peça final, onde a arte caiu (`base_box`), onde a tinta caiu
    (`protect_box`) e as faixas livres (`areas_livres`).
    """
    img = open_rgb(arte)
    W, H = img.size
    w, h = formato["w"], formato["h"]

    margem = _com_respiro(protegido, formato, W, H)
    porque = ""
    if modo == "auto":
        # continuar o desenho do fundo é a única coisa que bloco de cor não
        # faz. Sem generativo, faixa chapada tirada da paleta — nunca borrão,
        # nunca espelho: um some com a textura, o outro devolve o texto ao
        # contrário.
        modo = "outpaint" if higgsfield_status().get("available") else "solid"
    if estrategia == "auto":
        estrategia, porque = escolher_estrategia(W, H, w, h, margem)
    # o enquadramento olha a caixa inflada (para sobrar margem); o relatório
    # volta com a caixa real, que é onde a tinta de fato caiu
    plano = plan_fit(W, H, w, h, margem, estrategia, (0.5, 0.5), folga)
    crop, ex = plano["crop"], plano["expand"]
    base = img.crop(tuple(crop))

    if plano["estrategia"] == "crop" or modo == "none" or not any(ex.values()):
        tela = base
        modo = "none"
    elif modo in ("stretch", "mirror"):
        espalhar = _stretch_side if modo == "stretch" else _mirror_side
        tela = base
        for lado in ("left", "right", "top", "bottom"):
            tela = espalhar(tela, lado, ex[lado])
    elif modo == "blur":
        tela = _blur_canvas(base, base.width + ex["left"] + ex["right"],
                            base.height + ex["top"] + ex["bottom"], ex["left"], ex["top"])
    elif modo == "solid":
        tela = _solid_canvas(base, base.width + ex["left"] + ex["right"],
                             base.height + ex["top"] + ex["bottom"], ex["left"], ex["top"], cor)
    elif modo == "outpaint":
        # continuar o desenho do fundo — grade, pontilhado, gradiente — é a
        # única coisa que faixa chapada não faz. Falhou, não inventa: quem
        # chamou decide, porque cair para borrão calado é o defeito antigo.
        import tempfile
        tmp = Path(tempfile.mkstemp(suffix=".png", prefix="replicai-fundo-")[1])
        base.save(tmp)
        feito, log = _outpaint_higgsfield(tmp, ex, None)
        tmp.unlink(missing_ok=True)
        if feito is None:
            raise FundoImpossivel(f"o outpaint não rodou: {log.get('erro')}")
        alvo = (base.width + ex["left"] + ex["right"], base.height + ex["top"] + ex["bottom"])
        tela = feito if feito.size == alvo else ImageOps.fit(feito, alvo, Image.Resampling.LANCZOS)
    else:
        raise ValueError(f"modo de fundo desconhecido: {modo}. Use {', '.join(MODOS)}")

    final = tela.resize((w, h), Image.Resampling.LANCZOS) if tela.size != (w, h) else tela
    destino = Path(destino) if destino else Path(arte).with_name(f"fundo-{formato['id']}.png")
    destino.parent.mkdir(parents=True, exist_ok=True)
    final.save(destino)

    plano.update(_to_target_coords(plano, W, H, w, h, protegido))
    # a mesma assinatura que o motor grava: diz de onde o fundo saiu, para a
    # tela poder mostrar quando não veio da arte inteira
    destino.with_suffix(destino.suffix + ".origem.json").write_text(
        json.dumps({"origem": "extend", "modo": modo, "base": str(Path(arte).resolve()),
                    "crop": crop, "expand": ex}, ensure_ascii=False, indent=1), encoding="utf-8")

    return {"src": destino.name, "caminho": destino, "modo": modo,
            "estrategia": plano["estrategia"], "enquadramento": estrategia, "porque": porque, "cortou": bool(plano.get("cortou_fundo")),
            "base_box": plano["base_box"], "protect_box": plano.get("protect_box"),
            "areas_livres": plano.get("areas_livres") or {}}


def espaco_livre(formato: dict, tinta) -> dict:
    """Onde dá para escrever sem cobrir o que a arte já diz.

    Primeira versão desta função só oferecia a faixa que a extensão criou — e
    no Stories, onde a extensão cai justo na margem que o app cobre, não
    sobrava nada e a peça saiu muda. O erro era de leitura: a regra é não
    escrever sobre o **texto** da arte, não sobre a arte. Texto sobre gradiente
    é desenho; texto sobre texto é defeito.

    Então o proibido é a tinta que a arte já carrega, mais um respiro. O resto
    da área segura está disponível.
    """
    W, H = formato["w"], formato["h"]
    s = formato["safe"]
    sx0, sy0, sx1, sy1 = s["left"], s["top"], W - s["right"], H - s["bottom"]
    if not tinta:
        return {"bottom": [sx0, sy0, sx1, sy1]}

    respiro = max(12, round(H * 0.025))
    faixas = {}
    cima = [sx0, sy0, sx1, min(sy1, tinta[1] - respiro)]
    baixo = [sx0, max(sy0, tinta[3] + respiro), sx1, sy1]
    if cima[3] - cima[1] > 0:
        faixas["top"] = cima
    if baixo[3] - baixo[1] > 0:
        faixas["bottom"] = baixo
    if faixas:
        return faixas
    # tinta atravessando a peça de cima a baixo: sobra o que estiver ao lado
    esq = [sx0, sy0, min(sx1, tinta[0] - respiro), sy1]
    dir_ = [max(sx0, tinta[2] + respiro), sy0, sx1, sy1]
    if esq[2] - esq[0] > 0:
        faixas["left"] = esq
    if dir_[2] - dir_[0] > 0:
        faixas["right"] = dir_
    return faixas


def maior_faixa(areas: dict) -> tuple[str, list[int]] | None:
    """A faixa livre com mais área. É onde o texto novo cabe melhor; sem faixa
    nenhuma, a peça é a arte reenquadrada e não entra texto novo."""
    if not areas:
        return None
    nome = max(areas, key=lambda k: (areas[k][2] - areas[k][0]) * (areas[k][3] - areas[k][1]))
    return nome, areas[nome]
