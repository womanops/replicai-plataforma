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
import os
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

# quanto esperar pelo generativo, por formato. O motor esperava 30 minutos sem
# dar sinal de vida; ninguém paga para olhar uma tela parada meia hora. Passou
# do prazo, a peça sai com o fundo determinístico e dizendo que saiu.
ESPERA_PADRAO = 180


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


# quantas vezes insistir quando o generativo inventa traço que a arte não tem.
# Ele é estocástico: a segunda tentativa costuma sair limpa, e repetir custa
# menos do que entregar peça com um risco de luz que não existe no KV.
TENTATIVAS = 2


def _melhor_continuacao(base, ex: dict, espera: int, plano: dict, w: int, h: int,
                        insistir: bool = False):
    """Continua o fundo, repetindo enquanto inventar estrutura.

    Devolve também quantas tentativas foram gastas: cada uma é cobrada pelo
    serviço, inclusive a que foi refeita.

    A conferência já sabia acusar o traço inventado, mas acusar não conserta.
    Como o generativo é estocástico, insistir resolve na maior parte das
    vezes; quando não resolve, fica a tentativa menos ruim e o aviso vai junto.
    """
    import tempfile

    from PIL import Image as Im

    melhor, melhor_nota, motivo = None, None, ""
    gastas = 0
    for _ in range(TENTATIVAS if insistir else 1):
        gastas += 1
        tela, motivo = _continuar(base, ex, espera)
        if tela is None:
            return None, motivo, gastas
        prova = Path(tempfile.mkstemp(suffix=".png", prefix="replicai-prova-")[1])
        try:
            pronta = tela.resize((w, h), Im.Resampling.LANCZOS) if tela.size != (w, h) else tela
            pronta.save(prova)
            caixa = _to_target_coords(plano, 0, 0, w, h)["base_box"]
            # cor fora da paleta pesa como traço inventado: as duas tornam a
            # tentativa inútil, e insistir é mais barato do que entregar
            nota = len(inventou_estrutura(prova, caixa)) + len(cor_estranha(prova, caixa, base))
        finally:
            prova.unlink(missing_ok=True)
        if nota == 0:
            return tela, "", gastas
        if melhor_nota is None or nota < melhor_nota:
            melhor, melhor_nota = tela, nota
    return melhor, motivo, gastas


def _continuar(base, ex: dict, espera: int):
    """Continua o desenho do fundo no espaço novo, com prazo.

    Devolve (imagem, "") quando deu, (None, motivo) quando não. O motivo sobe
    até a entrega: fundo que caiu para o determinístico tem que aparecer.
    """
    import tempfile

    from time import monotonic

    tmp = Path(tempfile.mkstemp(suffix=".png", prefix="replicai-fundo-")[1])
    base.save(tmp)
    comecou = monotonic()
    try:
        feito, log = _outpaint_higgsfield(tmp, ex, None, timeout=espera)
    except Exception as e:
        return None, f"o fundo generativo falhou: {e}"
    finally:
        tmp.unlink(missing_ok=True)
    if feito is None:
        # dizer "não respondeu em 180s" quando a recusa voltou em dois
        # segundos manda quem lê procurar lentidão onde o problema é conta,
        # credencial ou crédito. Custou meia hora de busca errada uma vez.
        levou = monotonic() - comecou
        porque = log.get("erro") or "sem resposta"
        if levou >= espera * 0.9:
            return None, f"o fundo generativo não respondeu em {espera}s ({porque})"
        return None, (f"o fundo generativo recusou em {round(levou)}s: {porque}. "
                      f"Não foi demora — confira a credencial e o crédito do serviço")
    alvo = (base.width + ex["left"] + ex["right"], base.height + ex["top"] + ex["bottom"])
    return (feito if feito.size == alvo
            else ImageOps.fit(feito, alvo, Image.Resampling.LANCZOS)), ""


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
             cor: str | None = None, ancora: tuple[float, float] = (0.5, 0.5),
             insistir: bool = False, reaproveitar: bool = False) -> dict:
    """Monta o fundo de `formato` a partir de `arte` e diz onde sobrou espaço.

    `protegido` é a caixa (x0,y0,x1,y1, em pixels da arte) que não pode ser
    cortada — a tinta que a peça já carrega. `ancora` diz onde a arte encosta
    quando sobra espaço: (0.5, 0) joga a extensão toda para baixo, que é o que
    deixa o assunto no topo e abre o rodapé para o texto. Devolve o caminho do fundo e, em
    coordenadas da peça final, onde a arte caiu (`base_box`), onde a tinta caiu
    (`protect_box`) e as faixas livres (`areas_livres`).
    """
    img = open_rgb(arte)
    W, H = img.size
    w, h = formato["w"], formato["h"]

    margem = _com_respiro(protegido, formato, W, H)
    porque = ""
    if modo == "auto":
        modo = os.environ.get("REPLICAI_FUNDO", "auto").strip().lower() or "auto"
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
    plano = plan_fit(W, H, w, h, margem, estrategia, ancora, folga)
    crop, ex = plano["crop"], plano["expand"]
    base = img.crop(tuple(crop))

    pronto = _ja_feito(destino, plano, modo) if reaproveitar else None
    if pronto is not None:
        plano.update(_to_target_coords(plano, W, H, w, h, protegido))
        return {**pronto, "caminho": Path(destino), "generativo": 0, "avisos": [],
                "plano": {"crop": crop, "expand": ex, "escala": plano["escala"]},
                "estrategia": plano["estrategia"], "enquadramento": estrategia,
                "porque": "o fundo anterior serviu e foi reaproveitado",
                "cortou": bool(plano.get("cortou_fundo")),
                "base_box": plano["base_box"], "protect_box": plano.get("protect_box"),
                "areas_livres": plano.get("areas_livres") or {}}

    caiu_para, generativo = "", 0
    # nada a estender, nada a pedir: sem esta conta o recorte que já enche a
    # peça ainda gastava uma chamada do generativo — e, quando ela falhava,
    # a peça saía com uma ressalva sobre um fundo que ninguém tinha pedido
    if modo == "outpaint" and any(ex.values()):
        espera = max(30, int(os.environ.get("REPLICAI_FUNDO_ESPERA", ESPERA_PADRAO)))
        tela, motivo, generativo = _melhor_continuacao(base, ex, espera, plano, w, h,
                                                       insistir)
        if tela is None:
            # o generativo é o único que continua o desenho do fundo, mas não
            # pode prender a entrega. Passou do prazo, a peça sai com o fundo
            # determinístico — e dizendo que saiu, porque queda calada foi o
            # defeito que entregou peça de régua com cara de peça do modelo.
            caiu_para, modo = motivo, "solid"

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
    elif modo != "outpaint":
        raise ValueError(f"modo de fundo desconhecido: {modo}. Use {', '.join(MODOS)}")

    final = tela.resize((w, h), Image.Resampling.LANCZOS) if tela.size != (w, h) else tela
    destino = Path(destino) if destino else Path(arte).with_name(f"fundo-{formato['id']}.png")
    destino.parent.mkdir(parents=True, exist_ok=True)
    final.save(destino)

    plano.update(_to_target_coords(plano, W, H, w, h, protegido))

    # a conferência vale para qualquer extensão, não só a generativa: amarrá-la
    # ao modo deixava o teste da entrega dependendo de serviço externo, e a
    # regra em si não é sobre quem desenhou, é sobre o que apareceu. Vem antes
    # da assinatura porque é ela que diz se o fundo pode ser reaproveitado.
    avisos = []
    if any(ex.values()):
        avisos = (inventou_estrutura(destino, plano["base_box"])
                  # e a pergunta oposta: um bloco chapado não inventa traço
                  # nenhum e passava, mesmo sendo magenta num KV azul
                  + cor_estranha(destino, plano["base_box"], img))

    # cor absurda não é ressalva: o generativo devolveu faixa magenta num KV
    # azul e a peça saiu "com ressalva" — ninguém publica isso, e entregar é só
    # empurrar o problema. Aqui o fundo generativo é descartado e o
    # determinístico assume, que erra para o lado da arte
    if modo == "outpaint" and any(ex.values()):
        medidas = medidas_de_cor(destino, plano["base_box"], img)
        pior = max((m[0] for m in medidas.values()), default=0.0)
        mancha = max((m[1] for m in medidas.values()), default=0.0)
        if pior >= COR_RECUSADA or mancha >= MANCHA:
            tela = base
            for lado in ("left", "right", "top", "bottom"):
                tela = _stretch_side(tela, lado, ex[lado])
            final = tela.resize((w, h), Image.Resampling.LANCZOS) if tela.size != (w, h) else tela
            final.save(destino)
            modo = "stretch"
            caiu_para = ((f"o fundo generativo saiu numa cor que não existe na arte "
                          f"(distância {pior:.0f} da paleta dela) e foi descartado")
                         if pior >= COR_RECUSADA else
                         (f"{round(mancha * 100)}% da faixa continuada saiu numa cor "
                          f"que não existe na arte e foi descartada: mancha de cor "
                          f"estranha na peça não é continuação"))
            avisos = (inventou_estrutura(destino, plano["base_box"])
                      + cor_estranha(destino, plano["base_box"], img))

    # a assinatura guarda o plano e se a conferência passou: é com ela que a
    # exportação final sabe o que reaproveitar e o que precisa refazer
    destino.with_suffix(destino.suffix + ".origem.json").write_text(
        json.dumps({"origem": "extend", "modo": modo, "base": str(Path(arte).resolve()),
                    "crop": crop, "expand": ex, "escala": plano["escala"],
                    "limpo": not avisos, "src": destino.name},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return {"src": destino.name, "caminho": destino, "modo": modo, "caiu_para": caiu_para,
            # cada tentativa do generativo é cobrada, inclusive a que foi
            # refeita por ter inventado traço: quem paga é quem roda
            "generativo": generativo, "avisos": avisos,
            # crop, expand e escala descrevem a transformação inteira: é com
            # eles que as camadas do PSD acompanham o fundo no reenquadramento
            "plano": {"crop": crop, "expand": ex, "escala": plano["escala"]},
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


# acima disto a extensão tem estrutura mais forte do que a arte que ela
# continua — ou seja, o generativo inventou. Medido numa peça real: onde ele
# criou um segundo risco de luz deu 2,33x; onde se comportou, 0,75x e 0,43x.
INVENTOU = 1.5


def _borda_por_linha(a):
    import numpy as np
    return np.abs(np.diff(a, axis=0)).mean(1)


def inventou_estrutura(caminho, base_box) -> list[str]:
    """A extensão criou desenho que a arte não tinha?

    O generativo continua bem gradiente, grade e pontilhado. O que ele às
    vezes faz de errado é repetir um elemento marcante — numa peça real criou
    um segundo risco de luz, que não existe no KV e dá a impressão de erro.

    A medida é borda horizontal linha a linha: risco de luz é exatamente isso.
    Comparada com a faixa de arte vizinha do mesmo tamanho, porque a pergunta
    não é "há estrutura", e sim "há mais estrutura do que no que ela continua".
    """
    import numpy as np
    from PIL import Image

    caminho = Path(caminho)
    if not caminho.exists() or not base_box:
        return []
    with Image.open(caminho) as im:
        a = np.asarray(im.convert("L"), dtype=float)
    H = a.shape[0]
    y0, y1 = int(base_box[1]), int(base_box[3])
    avisos = []
    for nome, (ea, eb, va, vb) in {
        "topo": (0, y0, y0, min(H, y0 + y0)),
        "rodapé": (y1, H, max(0, y1 - (H - y1)), y1),
    }.items():
        if eb - ea < 8 or vb - va < 8:
            continue
        ext, viz = _borda_por_linha(a[ea:eb]), _borda_por_linha(a[va:vb])
        if not len(ext) or not len(viz) or viz.max() <= 0:
            continue
        razao = ext.max() / viz.max()
        if razao >= INVENTOU:
            linha = ea + int(ext.argmax())
            avisos.append(
                f"a continuação do fundo no {nome} inventou um traço forte que a arte "
                f"não tem (linha {linha}, {razao:.1f}x mais marcado que a arte ao lado). "
                f"Vale rodar de novo ou escolher outro enquadramento")
    return avisos


# quanto a cor da faixa pode se afastar da paleta da arte, em distância RGB
# ponderada. Medido nos dois lados: a continuação boa de um degradê azul ficou
# em 12, o bloco de cor tirado da própria paleta em 7, e a faixa magenta que o
# generativo devolveu num KV azul ficou em 193.
COR_ESTRANHA = 45

# acima disto não é ressalva, é outra peça. O generativo devolveu uma faixa
# magenta a 230 da paleta de um KV azul, e a peça foi entregue "com ressalva":
# ninguém publica isso, então entregar é só empurrar o problema. Daqui para
# cima o fundo generativo é jogado fora e o determinístico assume — ele erra
# para o lado da arte, que é o lado certo de errar.
COR_RECUSADA = 90


def _paleta(img, quantas: int = 48):
    """As cores que a arte usa, poucas e representativas."""
    from PIL import Image
    pequena = img.convert("RGB").resize((96, 96), Image.Resampling.BILINEAR)
    reduzida = pequena.quantize(colors=quantas, method=Image.Quantize.FASTOCTREE)
    tabela = reduzida.getpalette() or []
    import numpy as np
    usadas = {i for _, i in reduzida.convert("P").getcolors(96 * 96) or []}
    cores = [tabela[i * 3:i * 3 + 3] for i in sorted(usadas) if tabela[i * 3:i * 3 + 3]]
    return np.asarray(cores, dtype=float) if cores else None


# o olho pesa verde mais que azul; distância crua em RGB chama de perto um
# magenta que ninguém confundiria com o azul ao lado
PESO = (0.30, 0.59, 0.11)


def _longe_da_paleta(cores, paleta) -> tuple[float, float]:
    """Quanto a faixa se afasta da paleta: o pixel típico e quanto dela está
    fora de vez.

    Dois números porque um só mente. A mediana diz o típico — e o defeito do
    generativo não é típico: ele devolve um CANTO inteiro noutra cor, e a
    mediana continua baixa porque o resto da faixa está certo. Foi assim que
    uma faixa com um quarto dela a 180 da paleta mediu 25 e passou.
    """
    import numpy as np
    pesos = np.asarray(PESO) * 3
    d = ((cores[:, None, :] - paleta[None, :, :]) ** 2 * pesos).sum(axis=2) ** 0.5
    perto = d.min(axis=1)
    return float(np.median(perto)), float((perto >= COR_RECUSADA).mean())


# quanto da faixa pode estar em cor que a arte não tem antes de a faixa deixar
# de ser continuação. Um sexto dela já se vê de longe — e o que se vê é uma
# mancha de cor estranha na peça, não uma tolerância.
MANCHA = 0.15


def medidas_de_cor(caminho, base_box, arte=None) -> dict[str, tuple[float, float]]:
    """Quanto cada faixa continuada se afasta da paleta da arte.

    `inventou_estrutura` pergunta se apareceu desenho demais. Esta pergunta é a
    oposta e faltava: um bloco chapado não inventa traço nenhum e passa — mesmo
    quando é magenta num KV azul. Foi o que o generativo devolveu numa peça
    real, com `limpo: true` e sem aviso, e só apareceu quando alguém olhou.
    """
    import numpy as np
    from PIL import Image

    caminho = Path(caminho)
    if not caminho.exists() or not base_box:
        return {}
    with Image.open(caminho) as im:
        peca = im.convert("RGB")
        W, H = peca.size
        dentro = peca.crop(tuple(int(v) for v in base_box))
        paleta = _paleta(arte if arte is not None else dentro)
        if paleta is None or not len(paleta):
            return {}
        x0, y0, x1, y1 = (int(v) for v in base_box)
        faixas = {"topo": (0, 0, W, y0), "rodapé": (0, y1, W, H),
                  "esquerda": (0, y0, x0, y1), "direita": (x1, y0, W, y1)}
        achadas = {}
        for nome, caixa in faixas.items():
            if caixa[2] - caixa[0] < 8 or caixa[3] - caixa[1] < 8:
                continue
            amostra = peca.crop(caixa).resize((24, 24), Image.Resampling.BILINEAR)
            cores = np.asarray(amostra, dtype=float).reshape(-1, 3)
            achadas[nome] = _longe_da_paleta(cores, paleta)
        return achadas


def distancias_de_cor(caminho, base_box, arte=None) -> dict[str, float]:
    """Só o pixel típico de cada faixa. É o número que vira aviso."""
    return {n: m[0] for n, m in medidas_de_cor(caminho, base_box, arte).items()}


def cor_estranha(caminho, base_box, arte=None) -> list[str]:
    """O aviso de cada faixa que saiu fora da paleta da arte.

    Os dois degraus — avisar e recusar — valem para as duas medidas. Metade da
    régua de mancha porque avisar é constatação depois do fato, e um respingo
    que já se vê merece ser dito mesmo quando ainda não derruba o fundo.
    """
    avisos = []
    for nome, (tipico, mancha) in medidas_de_cor(caminho, base_box, arte).items():
        if tipico >= COR_ESTRANHA:
            avisos.append(f"a continuação do fundo no {nome} saiu numa cor que não "
                          f"existe na arte (distância {tipico:.0f} da paleta dela). "
                          f"Isso não é continuação, é outra peça: vale rodar de novo")
        elif mancha >= MANCHA / 2:
            avisos.append(f"{round(mancha * 100)}% da faixa do {nome} saiu numa cor "
                          f"que não existe na arte: é uma mancha, e aparece. "
                          f"Vale rodar de novo")
    return avisos


def _ja_feito(destino, plano: dict, modo: str) -> dict | None:
    """O fundo que já está em disco serve?

    Serve quando saiu do mesmo recorte e da mesma escala e passou na
    conferência. Fundo com traço inventado não é reaproveitado: refazer esse é
    justamente o motivo de existir a exportação final.
    """
    destino = Path(destino)
    assinatura = destino.with_suffix(destino.suffix + ".origem.json")
    if not destino.exists() or not assinatura.exists():
        return None
    try:
        d = json.loads(assinatura.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not d.get("limpo") or d.get("modo") != modo:
        return None
    if d.get("crop") != plano["crop"] or d.get("expand") != plano["expand"]:
        return None
    return {"src": destino.name, "modo": modo, "caiu_para": "", "reaproveitado": True}


def mover(caixa: dict, plano: dict) -> dict:
    """Leva uma caixa da arte para as coordenadas da peça reenquadrada.

    É a mesma conta que o fundo sofreu. Sem ela as camadas do PSD ficariam
    onde estavam no arquivo e o lockup descolaria do desenho — que é o
    contrário de desdobrar.
    """
    crop, ex, s = plano["crop"], plano["expand"], plano["escala"]
    return {"x": round((caixa["x"] - crop[0] + ex["left"]) * s),
            "y": round((caixa["y"] - crop[1] + ex["top"]) * s),
            "w": round(caixa["w"] * s),
            "h": round(caixa["h"] * s)}


def maior_faixa(areas: dict) -> tuple[str, list[int]] | None:
    """A faixa livre com mais área. É onde o texto novo cabe melhor; sem faixa
    nenhuma, a peça é a arte reenquadrada e não entra texto novo."""
    if not areas:
        return None
    nome = max(areas, key=lambda k: (areas[k][2] - areas[k][0]) * (areas[k][3] - areas[k][1]))
    return nome, areas[nome]
