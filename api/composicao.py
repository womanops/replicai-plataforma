"""O contrato entre o modelo e o motor.

O experimento de 10/10/2026 (ver `docs/DECISAO-quem-compoe.md`) separou a
composição em duas naturezas:

- **julgamento** — o que entra, o que sai, o que se encurta, qual a hierarquia.
  Transferiu inteiro para uma passada de modelo.
- **coordenada exata** — onde começa e termina cada caixa. É onde a passada
  única erra, e é trabalho determinístico.

Então o modelo não responde pixels. Ele responde em **papéis e zonas**, e a
máquina converte em caixas usando a área segura e as convenções do formato.
Isso tira do modelo a parte que ele faz mal e mantém a que ele faz bem.

Nada aqui chama modelo nenhum: é o idioma, a conferência e a conversão. Quem
chama é o `CompositorModelo`, que recebe o modelo de fora.
"""
from __future__ import annotations

from dataclasses import dataclass

PAPEIS = ("marca", "headline", "apoio", "cta", "selo")

# 3x3 dentro da área segura. Vocabulário pequeno de propósito: zona demais vira
# pixel disfarçado, e aí o modelo volta a errar coordenada.
ZONAS = tuple(f"{v}-{h}" for v in ("topo", "meio", "baixo")
              for h in ("esquerda", "centro", "direita"))

# quanto da altura útil cada papel ocupa, e os limites de corpo
PESO = {
    "headline": (0.30, 0.040, 0.150),
    "apoio":    (0.16, 0.022, 0.055),
    "cta":      (0.12, 0.022, 0.060),
    "selo":     (0.08, 0.018, 0.040),
    "marca":    (0.14, 0.000, 0.000),
}


class RespostaInvalida(ValueError):
    """O modelo respondeu algo que não dá para compor. Melhor recusar do que
    renderizar: peça torta entregue é pior do que peça não entregue."""


@dataclass
class Elemento:
    papel: str
    zona: str
    texto: str = ""
    origem: str = ""          # para marca: o arquivo recortado da arte


@dataclass
class Esquema:
    elementos: list[Elemento]
    descartados: dict[str, str]     # o que ficou de fora e por quê


def conferir(bruto: dict, formato: dict) -> Esquema:
    """Lê e confere a resposta do modelo contra o formato pedido."""
    if not isinstance(bruto, dict):
        raise RespostaInvalida("a resposta não é um objeto")
    crus = bruto.get("elementos")
    if not isinstance(crus, list) or not crus:
        raise RespostaInvalida("a resposta não trouxe elementos")

    limites = formato.get("texto", {})
    vistos, elementos = set(), []
    for i, e in enumerate(crus):
        if not isinstance(e, dict):
            raise RespostaInvalida(f"elemento {i} não é um objeto")
        papel = (e.get("papel") or "").strip().lower()
        zona = (e.get("zona") or "").strip().lower()
        texto = (e.get("texto") or "").strip()
        if papel not in PAPEIS:
            raise RespostaInvalida(f"papel desconhecido: `{papel}`. Use {', '.join(PAPEIS)}")
        if zona not in ZONAS:
            raise RespostaInvalida(f"zona desconhecida: `{zona}`. Use {', '.join(ZONAS[:3])}…")
        if papel in vistos:
            raise RespostaInvalida(f"dois elementos com o papel `{papel}`")
        vistos.add(papel)

        if papel == "marca":
            if not (e.get("origem") or "").strip():
                raise RespostaInvalida("a marca precisa dizer de onde sai (`origem`)")
        else:
            if not texto:
                raise RespostaInvalida(f"`{papel}` sem texto")
            cabe = limites.get(f"{papel}_max")
            if cabe == 0:
                raise RespostaInvalida(
                    f"`{formato['id']}` não leva {papel}, e veio um: \"{texto[:30]}\"")
            if cabe and len(texto) > cabe:
                raise RespostaInvalida(
                    f"o {papel} tem {len(texto)} caracteres e `{formato['id']}` comporta "
                    f"{cabe}. Encurtar é decisão de quem escreve")
        elementos.append(Elemento(papel, zona, texto, (e.get("origem") or "").strip()))

    if "headline" not in vistos:
        raise RespostaInvalida("sem headline não há peça")

    desc = bruto.get("descartados") or {}
    if not isinstance(desc, dict):
        raise RespostaInvalida("`descartados` precisa dizer o que saiu e por quê")
    # cortar conteúdo calado é o que a casa não aceita: se o modelo largou algo,
    # tem que estar escrito, para aparecer na entrega
    return Esquema(elementos, {str(k): str(v) for k, v in desc.items()})


def _util(formato: dict) -> tuple[int, int, int, int]:
    """A área onde se pode compor: dentro da zona segura, com respiro."""
    W, H = formato["w"], formato["h"]
    s = formato["safe"]
    fx, fy = max(8, round(W * 0.035)), max(6, round(H * 0.035))
    return (s["left"] + fx, s["top"] + fy, W - s["right"] - fx, H - s["bottom"] - fy)


def _largura(zona: str, x0: int, x1: int, vizinhas: set[str]) -> tuple[int, int]:
    """Largura de uma zona, dividindo com quem ocupa a mesma faixa vertical.

    Sem isso, "meio-centro" pegava a largura inteira e o botão em
    "meio-direita" caía em cima — o banner saiu com a chamada e o CTA
    escritos um sobre o outro.
    """
    horz = zona.split("-")[1]
    util = x1 - x0
    outras = {z.split("-")[1] for z in vizinhas} - {horz}
    if not outras:
        larg = util if horz == "centro" else round(util * 0.62)
        return ({"esquerda": x0, "centro": x0, "direita": x1 - larg}[horz], larg)

    ordem = [h for h in ("esquerda", "centro", "direita") if h == horz or h in outras]
    fatia = util // len(ordem)
    folga = max(6, round(util * 0.02))
    i = ordem.index(horz)
    return (x0 + i * fatia, fatia - folga)


def _alturas(papeis: list[str], util_h: int, respiro: int) -> list[int]:
    alt = [max(14, round(util_h * PESO[p][0])) for p in papeis]
    total = sum(alt) + respiro * (len(alt) - 1)
    if total > util_h:                       # encolhe proporcional em vez de estourar
        sobra = util_h - respiro * (len(alt) - 1)
        f = sobra / max(1, sum(alt))
        alt = [max(14, int(a * f)) for a in alt]
    return alt


def _posicionar(formato: dict, por_zona: dict) -> dict[str, list[dict]]:
    """Resolve a coluna inteira de uma vez, não faixa a faixa.

    Faixa a faixa, o grupo do meio descia até 80% da altura e o grupo de baixo
    começava em 68% — colidiam. Resolver por coluna deixa cada grupo empurrar o
    seguinte para baixo, e só então tudo é puxado para dentro da área segura.
    """
    x0, y0, x1, y1 = _util(formato)
    util_h = y1 - y0
    respiro = max(4, round(formato["h"] * 0.012))
    faixa = {"topo": 0.0, "meio": 0.34, "baixo": 0.68}

    colunas: dict[str, list[str]] = {}
    for z in por_zona:
        colunas.setdefault(z.split("-")[1], []).append(z)

    saida: dict[str, list[dict]] = {}
    for horz, zonas in colunas.items():
        zonas.sort(key=lambda z: faixa[z.split("-")[0]])
        vizinhas = set(por_zona)
        cx, larg = _largura(zonas[0], x0, x1, vizinhas)
        piso = y0
        blocos = []
        for z in zonas:
            alt = _alturas([e.papel for e in por_zona[z]], util_h, respiro)
            topo = max(piso, y0 + round(util_h * faixa[z.split("-")[0]]))
            blocos.append((z, topo, alt))
            piso = topo + sum(alt) + respiro * len(alt)

        # se o último passou do limite, sobe tudo junto mantendo a ordem
        excesso = max(0, piso - respiro - y1)
        for z, topo, alt in blocos:
            y = max(y0, topo - excesso)
            caixas = []
            for a in alt:
                caixas.append({"x": int(cx), "y": int(min(y, y1 - a)), "w": int(larg), "h": int(a)})
                y += a + respiro
            saida[z] = caixas
    return saida


def montar(esq: Esquema, formato: dict, fundo: dict, fontes: list | None = None,
           cor_texto: str = "#ffffff", acento: str = "") -> dict:
    """Esquema + formato -> peça JSON pronta para o motor renderizar."""
    W, H = formato["w"], formato["h"]
    por_zona: dict[str, list[Elemento]] = {}
    ordem_papel = {p: i for i, p in enumerate(("marca", "selo", "headline", "apoio", "cta"))}
    for e in sorted(esq.elementos, key=lambda e: ordem_papel.get(e.papel, 9)):
        por_zona.setdefault(e.zona, []).append(e)

    elementos = []
    posicoes = _posicionar(formato, por_zona)
    for zona, lista in por_zona.items():
        for e, box in zip(lista, posicoes[zona]):
            if e.papel == "marca":
                elementos.append({"tipo": "imagem", "papel": "marca", "src": e.origem,
                                  "box": box, "fit": "contain"})
                continue
            _, mn, mx = PESO[e.papel]
            # o mínimo também olha a caixa: vindo só do canvas, o apoio no
            # Stories não conseguia encolher o bastante, estourava a caixa e
            # escrevia por cima do CTA
            teto = max(12, int(box["h"] * 0.82))
            piso = min(max(11, round(H * mn)), max(11, int(box["h"] * 0.34)))
            el = {"tipo": "texto", "papel": e.papel, "texto": e.texto, "box": box,
                  "peso": 800 if e.papel in ("headline", "cta") else 500,
                  "cor": cor_texto, "min": piso, "max": min(round(H * mx), teto),
                  "lineHeight": 1.05 if e.papel == "headline" else 1.25,
                  "align": "center" if zona.endswith("centro") else "left",
                  "valign": "middle"}
            if acento:
                el["acento"] = acento
            elementos.append(el)

    return {
        "formato": formato["id"],
        "canvas": {"w": W, "h": H},
        "safe": formato["safe"],
        "saida": f"{formato['id']}.png",
        "via": "modelo+regra",
        "fundo": fundo,
        "fontes": fontes or [],
        "elementos": elementos,
        "descartados": esq.descartados,
    }
