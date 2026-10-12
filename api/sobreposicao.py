"""A regra de sobreposição, dentro da plataforma.

Decisão da casa, de 09/10/2026: **nunca encostar por erro, só se a arte-mãe já
fizer assim**. No KV da Consigaz o braço do mascote cobre o fim do
"CANDIDATE-SE" de propósito, e isso é gesto de apresentar. O que não pode é a
adaptação inventar sobreposição.

A régua custou três tentativas erradas, todas plausíveis e todas falsas: área
da caixa (um braço que corta o topo das letras ocupa 2% e passa), caixa da
camada do PSD (tem ar depois da última letra e inventa sobreposição na mãe) e
redesenhar o texto por fora com PIL (não bate com o navegador). A que vale é
**fatia da largura do retângulo justo de tinta**, tinta contra tinta — e é a
que o motor já implementa em `invasao_ret`. Aqui ela é reusada, não refeita.

O que faltava era isto: a regra estava escrita no motor e a esteira da
plataforma nunca a chamava. É o mesmo defeito do lettering fantasma — escrever
a verificação e não chamá-la. Por isso existe teste do ponto de chamada, e não
só da função.
"""
from __future__ import annotations

import json
from pathlib import Path

from motor.replica import invasao_ret

# abaixo disto é encosto de borda, não sobreposição. Mesmo piso do motor.
PISO = 0.02

# folga sobre o que a arte-mãe já fazia, igual à do motor: medir é aproximado
# e acusar por um ponto de diferença vira ruído
TOLERANCIA = 0.03

# papéis que carregam leitura: no caminho do PSD o texto chega como recorte de
# letra, então olhar só `tipo == "texto"` deixaria passar justamente a peça
# reconstruída, que é a maioria
PAPEIS_DE_TEXTO = {"headline", "apoio", "cta", "selo", "legenda", "titulo"}


def _caminho(src: str, pasta: Path) -> Path | None:
    if not src:
        return None
    p = Path(src)
    return p if p.is_absolute() else pasta / src


def _mascara(el: dict, pasta: Path):
    """O alfa do recorte, no tamanho em que ele foi desenhado."""
    from motor.replica import _alfa
    cam = _caminho(el.get("src", ""), pasta)
    if cam is None or not cam.exists():
        return None
    b = el.get("box") or {}
    try:
        return _alfa(cam, int(b.get("w", 0)), int(b.get("h", 0)))
    except Exception:
        return None


def _tinta(el: dict, pasta: Path, report: dict) -> tuple[float, float, float, float] | None:
    """O retângulo justo da tinta do elemento, não a caixa dele.

    Para texto quem sabe é o navegador: `tinta` vem do render, medido com
    `Range.getClientRects()`. Para recorte, o alfa do próprio PNG.
    """
    b = el.get("box") or {}
    caixa = (float(b.get("x", 0)), float(b.get("y", 0)),
             float(b.get("w", 0)), float(b.get("h", 0)))
    if el.get("tipo") in ("texto", "botao"):
        crua = (report.get(id(el)) or "").strip() if report else ""
        if crua:
            try:
                return tuple(float(v) for v in crua.split(","))    # type: ignore[return-value]
            except ValueError:
                pass
        return caixa
    from motor.replica import _ret_da_tinta
    m = _mascara(el, pasta)
    if m is None:
        return None
    r = _ret_da_tinta(m, caixa[0], caixa[1])
    return tuple(float(v) for v in r) if r else None


def _por_papel(pasta: Path, formato: str) -> dict:
    """O `tinta` que o navegador mediu, por papel, quando o render deixou."""
    arq = pasta / "pecas" / f"{formato}.report.json"
    if not arq.exists():
        return {}
    try:
        d = json.loads(arq.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    saida = {}
    for e in d.get("elementos") or []:
        if e.get("classe") == "txt" and e.get("tinta"):
            saida[e.get("papel")] = e["tinta"]
    return saida


# acima disto o fundo embaixo do texto tem desenho demais para o texto se ler.
# Mesmo degrau que o `sossego` usa para escolher lugar: lá é decisão prévia,
# aqui é constatação depois do fato, sobre o PNG que saiu
AGITADO = 30


def _veio_da_mae(el: dict) -> bool:
    """Elemento que saiu do PSD traz a camada de origem. O que a arte-mãe
    arranjou é decisão de quem desenhou a peça, e não se discute aqui."""
    return bool(el.get("camada"))


def sobre_desenho(peca: dict, pasta: Path) -> list[str]:
    """Texto novo que caiu em cima do desenho do fundo.

    O caso que a Ligia cobrou: o braço do mascote por trás da chamada. Ele não
    é elemento nenhum — vem assado no fundo —, então comparar elemento com
    elemento nunca o acharia. O que dá para medir é o fundo embaixo da tinta.
    """
    from PIL import Image

    from api.sossego import perfil

    src = (peca.get("fundo") or {}).get("src")
    alvo = _caminho(src or "", pasta)
    if alvo is None or not alvo.exists():
        return []
    medido = _por_papel(pasta, peca.get("formato", ""))
    avisos = []
    with Image.open(alvo) as fundo:
        fundo = fundo.convert("RGB")
        for el in peca.get("elementos") or []:
            if el.get("tipo") not in ("texto", "botao") or _veio_da_mae(el):
                continue
            ret = _tinta_de(el, medido)
            if not ret or ret[2] < 8 or ret[3] < 8:
                continue
            x, y, w, h = ret
            fatias = perfil(fundo, (x, y, x + w, y + h))
            if not fatias:
                continue
            agitadas = sum(1 for _, _, d in fatias if d >= AGITADO)
            if agitadas / len(fatias) < 0.5:
                continue
            oque = (el.get("texto") or el.get("papel") or "texto")[:28]
            avisos.append(
                f"\"{oque}\" caiu sobre o desenho do fundo em "
                f"{agitadas * 100 // len(fatias)}% da largura: ali o texto não se lê. "
                f"Mova em Ajustar, ou rode de novo")
    return avisos


def _tinta_de(el: dict, medido: dict):
    crua = (medido.get(el.get("papel") or "") or "").strip()
    if crua:
        try:
            return tuple(float(v) for v in crua.split(","))
        except ValueError:
            pass
    b = el.get("box") or {}
    return (float(b.get("x", 0)), float(b.get("y", 0)),
            float(b.get("w", 0)), float(b.get("h", 0)))


def _linhas(els: list[dict], pasta: Path) -> dict:
    """A tinta de cada linha de texto, somando os recortes de letra dela."""
    linhas: dict = {}
    for i, el in enumerate(els):
        camada = el.get("camada")
        if not camada:
            continue
        r = _tinta(el, pasta, {})
        if not r:
            continue
        atual = linhas.get(camada)
        if atual is None:
            linhas[camada] = {"em": i, "ret": r}
            continue
        a, b = atual["ret"], r
        x0, y0 = min(a[0], b[0]), min(a[1], b[1])
        x1 = max(a[0] + a[2], b[0] + b[2])
        y1 = max(a[1] + a[3], b[1] + b[3])
        atual["ret"] = (x0, y0, x1 - x0, y1 - y0)
    return linhas


def conferir(peca: dict, pasta: Path, permitido: dict | None = None) -> list[str]:
    """O que, na peça montada, cobre o texto mais do que devia — e o texto que
    caiu em cima do desenho.

    `permitido` é o que a arte-mãe já fazia, por papel. Sem ele a régua é o
    piso: na reconstrução do PSD o fundo vem assado e nada da mãe sobra como
    camada, então o que cobre texto aqui foi a adaptação que pôs.
    """
    pasta = Path(pasta)
    permitido = permitido or {}
    els = peca.get("elementos") or []
    if len(els) < 2:
        # um elemento não encosta em outro, mas ainda pode estar em cima do
        # desenho do fundo — que é justamente o caso do braço do mascote
        return sobre_desenho(peca, pasta)
    medido = _por_papel(pasta, peca.get("formato", ""))
    # numa peça REMONTADA o empilhamento não é mais o da arte-mãe: quem decidiu
    # o que fica perto do quê foi a adaptação. Sem isto o mascote cobriu metade
    # do CANDIDATE-SE na capa de página e a régua ficou calada — ele entrou na
    # lista antes do texto, e o que vem antes só era olhado quando o texto era
    # novo. `permitido` continua guardando o que a mãe já fazia
    remontada = str(peca.get("via") or "").startswith("psd-recompor")
    avisos: list[str] = []
    pior: dict[tuple, float] = {}
    # a linha é a unidade, não a letra: um lettering do PSD vira trinta e cinco
    # recortes, e medir letra a letra dá 100% para a letra que ficou atrás da
    # figura e 0% para a vizinha. A régua da casa é a largura da linha inteira
    por_camada = _linhas(els, pasta)
    for i, el in enumerate(els):
        papel = el.get("papel") or ""
        ehtexto = el.get("tipo") in ("texto", "botao") or papel in PAPEIS_DE_TEXTO
        if not ehtexto:
            continue
        camada = el.get("camada")
        if camada:
            # só uma vez por linha, no primeiro recorte dela
            if por_camada.get(camada, {}).get("em") != i:
                continue
            ret = por_camada[camada]["ret"]
        else:
            crua = medido.get(papel, "")
            ret = None
            if el.get("tipo") in ("texto", "botao") and crua:
                try:
                    ret = tuple(float(v) for v in crua.split(","))
                except ValueError:
                    ret = None
            if ret is None:
                ret = _tinta(el, pasta, {})
        if not ret or ret[2] < 1 or ret[3] < 1:
            continue
        # os dois sentidos: o que está por cima do texto, e — quando o texto é
        # novo — o recorte que ele próprio foi cobrir. Olhar só um lado deixava
        # passar justamente a chamada escrita em cima da foto
        acima = els[i + 1:]
        abaixo = [] if _veio_da_mae(el) and not remontada else els[:i]
        for cima in acima + abaixo:
            if cima.get("tipo") not in ("imagem", "video") or not cima.get("src"):
                continue
            if cima.get("camada") and cima.get("camada") == el.get("camada"):
                continue              # letras da mesma linha não se cobrem
            m = _mascara(cima, pasta)
            if m is None:
                continue
            cb = cima.get("box") or {}
            fatia = invasao_ret(ret, m, (cb.get("x", 0), cb.get("y", 0)))
            # a linha de base é por camada quando ela existe: é o nome que a
            # arte-mãe conhece. `papel` repete entre camadas e misturaria duas
            na_mae = float(permitido.get(el.get("camada") or papel, 0.0))
            folga = max(PISO, na_mae + TOLERANCIA)
            if fatia <= folga:
                continue
            quem = cima.get("camada") or cima.get("papel") or Path(cima["src"]).stem
            oque = (el.get("texto") or el.get("camada") or papel or "texto")[:28]
            encostou = ("cobre" if cima in acima
                        else "encosta em" if remontada else "fica debaixo de")
            # uma linha por par, e não por letra: um lettering do PSD vira
            # trinta e cinco recortes e a entrega saía com trinta e cinco
            # avisos do mesmo problema
            chave = (quem, oque, encostou)
            if fatia > pior.get(chave, (0.0, 0.0))[0]:
                pior[chave] = (fatia, na_mae)
    for (quem, oque, encostou), (fatia, na_mae) in sorted(pior.items(),
                                                          key=lambda kv: -kv[1][0]):
        antes = (f"na arte-mãe eram {na_mae*100:.0f}%" if na_mae
                 else "a arte-mãe não encostava")
        avisos.append(
            f"`{quem}` {encostou} {fatia*100:.0f}% da largura de \"{oque}\"; {antes}. "
            f"Em Ajustar dá para diminuir o corpo do texto até ele sair de perto")
    return avisos + sobre_desenho(peca, pasta)
