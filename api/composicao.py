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


def _mesma_frase(a: str, b: str) -> bool:
    return _so_letras(a) == _so_letras(b) and bool(_so_letras(a))


def _so_letras(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if c.isalnum())


def conferir(bruto: dict, formato: dict, ja_escrito=(), material: str | None = None) -> Esquema:
    """Lê e confere a resposta do modelo contra o formato pedido.

    `ja_escrito` é o que a arte-mãe já carrega. Repetir isso é o defeito que
    saiu na primeira rodada real: "Energia que impulsiona o futuro." composta
    por cima da mesma frase que já estava impressa no fundo.

    `material` é tudo que a peça pode dizer — o que a pessoa escreveu e o que
    o brief traz. Texto fora disso é invenção, e a casa não aceita: na primeira
    rodada apareceu "Vem aí o grande encontro do ano", que ninguém pediu e
    ninguém pode assinar. Encurtar o que foi dado continua valendo.
    """
    permitido = _so_letras(material) if material else None
    if not isinstance(bruto, dict):
        raise RespostaInvalida("a resposta não é um objeto")
    crus = bruto.get("elementos")
    if not isinstance(crus, list):
        raise RespostaInvalida("a resposta não trouxe elementos")
    # lista vazia é resposta legítima quando a arte já preenche o formato: foi
    # o que esta instrução pediu, e recusar aqui contradiz o que foi pedido
    if not crus and not ja_escrito:
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
        if permitido is not None and texto and _so_letras(texto) not in permitido:
            raise RespostaInvalida(
                f"\"{texto}\" não está no que foi dado nem no brief. Não invente "
                f"frase: use o material, encurtando se precisar, ou deixe o papel "
                f"de fora e explique em `descartados`")
        repetido = next((j for j in ja_escrito if _mesma_frase(texto, j)), None)
        if repetido:
            raise RespostaInvalida(
                f"\"{repetido}\" já está impresso na arte: compor de novo escreve "
                f"duas vezes a mesma coisa. Use o espaço para o que falta")
        vistos.add(papel)

        if papel == "marca":
            if ja_escrito:
                raise RespostaInvalida(
                    "a marca já está impressa na arte, que é o fundo desta peça. "
                    "Não existe recorte dela em arquivo: pôr `marca` aqui deixa um "
                    "quadro vazio. Use o espaço para o que a arte não diz")
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

    # headline obrigatória só quando a arte não traz uma: numa adaptação, o
    # título já está no fundo, e exigir outro é exigir repetição
    if "headline" not in vistos and not ja_escrito:
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


# faixa com menos que isto da altura da peça não comporta hierarquia: o texto
# sai com 14px num canvas de 1920. Veio do Stories, onde a faixa de cima cai
# quase toda dentro da margem que o app cobre e sobravam 80px úteis.
FAIXA_MINIMA = 0.09


def _aparar(formato: dict, r) -> list[int] | None:
    """Encaixa um retângulo da peça na área segura, com o mesmo respiro de
    `_util`. Devolve None se o que sobrou não comporta hierarquia."""
    W, H = formato["w"], formato["h"]
    s = formato["safe"]
    fx, fy = max(8, round(W * 0.035)), max(6, round(H * 0.035))
    x0 = max(r[0] + fx, s["left"] + fx)
    y0 = max(r[1] + fy, s["top"] + fy)
    x1 = min(r[2] - fx, W - s["right"] - fx)
    y1 = min(r[3] - fy, H - s["bottom"] - fy)
    piso = max(60, round(formato["h"] * FAIXA_MINIMA))
    return [x0, y0, x1, y1] if (x1 - x0) > 24 and (y1 - y0) >= piso else None


def _tercos(r) -> dict[str, list[int]]:
    x0, y0, x1, y1 = r
    h = y1 - y0
    return {"topo":  [x0, y0, x1, y0 + round(h * 0.34)],
            "meio":  [x0, y0 + round(h * 0.34), x1, y0 + round(h * 0.68)],
            "baixo": [x0, y0 + round(h * 0.68), x1, y1]}


def _faixas(formato: dict, livres: dict | None = None) -> dict[str, list[int]]:
    """Onde cada faixa vertical pode compor.

    Sem `livres`, a peça inteira se divide em três — é o comportamento de
    sempre, para quem compõe sobre fundo que não tem nada dentro.

    Com `livres` (as faixas que a extensão do fundo criou), a composição só
    acontece nelas. É o que impede o texto novo de cair sobre o texto que a
    arte já carrega: não por medir distância, mas porque não existe caixa
    disponível em cima da arte.
    """
    # None é "não sei onde dá para escrever"; {} é "não dá em lugar nenhum".
    # Tratar os dois igual devolvia a peça inteira ao texto e era a
    # sobreposição de volta no formato de mesma proporção.
    if livres is None:
        return _tercos(_util(formato))

    cima = _aparar(formato, livres["top"]) if "top" in livres else None
    baixo = _aparar(formato, livres["bottom"]) if "bottom" in livres else None
    lados = [a for a in (_aparar(formato, livres[k]) for k in ("left", "right") if k in livres) if a]

    disp: dict[str, list[int]] = {}
    if cima:
        disp["topo"] = cima
    if baixo:
        disp["baixo"] = baixo
    if not disp:
        if not lados:
            return {}
        # faixa só nas laterais (banner largo): a maior coluna vira a peça
        return _tercos(max(lados, key=lambda r: (r[2] - r[0]) * (r[3] - r[1])))

    # a zona que não tem faixa própria cai na maior que existe, em vez de ser
    # recusada: recusa custa uma rodada de modelo, e empilhar é correto
    maior = max(disp.values(), key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
    for v in ("topo", "meio", "baixo"):
        disp.setdefault(v, maior)
    return disp


ORDEM_FAIXA = {"topo": 0, "meio": 1, "baixo": 2}


def _posicionar(formato: dict, por_zona: dict, livres: dict | None = None) -> dict[str, list[dict]]:
    """Resolve cada retângulo disponível de uma vez, não zona a zona.

    Zona a zona, o grupo do meio descia até 80% da altura e o de baixo começava
    em 68% — colidiam. Resolvendo o retângulo inteiro, cada grupo empurra o
    seguinte e o conjunto encolhe junto se não couber.
    """
    faixas = _faixas(formato, livres)
    if not faixas:
        return {}                     # sem espaço livre, nada é posicionado

    respiro = max(4, round(formato["h"] * 0.012))
    grupos: dict[tuple, list[str]] = {}
    for z in por_zona:
        vert, horz = z.split("-")
        r = faixas.get(vert)
        if r is None:
            continue
        grupos.setdefault((tuple(r), horz), []).append(z)

    por_retangulo: dict[tuple, set[str]] = {}
    for (r, _horz), zonas in grupos.items():
        por_retangulo.setdefault(r, set()).update(zonas)

    saida: dict[str, list[dict]] = {}
    for (r, horz), zonas in grupos.items():
        x0, y0, x1, y1 = r
        util_h = y1 - y0
        cx, larg = _largura(zonas[0], x0, x1, por_retangulo[r])
        zonas.sort(key=lambda z: ORDEM_FAIXA[z.split("-")[0]])

        papeis = [e.papel for z in zonas for e in por_zona[z]]
        alturas = _alturas(papeis, util_h, respiro)

        y, i = y0, 0
        for z in zonas:
            caixas = []
            for _ in por_zona[z]:
                a = alturas[i]; i += 1
                caixas.append({"x": int(cx), "y": int(min(y, y1 - a)),
                               "w": int(larg), "h": int(a)})
                y += a + respiro
            saida[z] = caixas
    return saida


# o CTA é o único elemento que pede ação: sem contraste de fundo ele some no
# meio da peça, que foi o "cta minúsculo com zero destaque" da primeira rodada
BOTAO_FUNDO = "#ffffff"


def montar(esq: Esquema, formato: dict, fundo: dict, fontes: list | None = None,
           cor_texto: str = "#ffffff", acento: str = "", livres: dict | None = None) -> dict:
    """Esquema + formato -> peça JSON pronta para o motor renderizar."""
    familia = (fontes or [{}])[0].get("familia", "")
    W, H = formato["w"], formato["h"]
    por_zona: dict[str, list[Elemento]] = {}
    ordem_papel = {p: i for i, p in enumerate(("marca", "selo", "headline", "apoio", "cta"))}
    for e in sorted(esq.elementos, key=lambda e: ordem_papel.get(e.papel, 9)):
        por_zona.setdefault(e.zona, []).append(e)

    elementos = []
    posicoes = _posicionar(formato, por_zona, livres)
    for zona, lista in por_zona.items():
        # zona sem caixa é zona sem espaço livre: o elemento não entra, em vez
        # de ser empurrado para cima da arte
        for e, box in zip(lista, posicoes.get(zona, [])):
            if e.papel == "marca":
                elementos.append({"tipo": "imagem", "papel": "marca", "src": e.origem,
                                  "box": box, "fit": "contain"})
                continue
            if e.papel == "cta":
                # o botão abraça o texto. Herdando a caixa da coluna ele saía
                # como uma barra branca atravessando a peça com a letra
                # minúscula no meio — larga demais e baixa demais ao mesmo tempo
                corpo = max(14, min(round(box["h"] * 0.42), round(H * 0.030)))
                alt = min(box["h"], round(corpo * 2.4))
                larg = min(box["w"], round(len(e.texto) * corpo * 0.60) + corpo * 3)
                x = box["x"]
                if zona.endswith("centro"):
                    x = box["x"] + (box["w"] - larg) // 2
                elif zona.endswith("direita"):
                    x = box["x"] + box["w"] - larg
                caixa = {"x": int(x), "y": int(box["y"]), "w": int(larg), "h": int(alt)}
                el = {"tipo": "botao", "papel": "cta", "texto": e.texto, "box": caixa,
                      "peso": 700, "cor": acento or "#101828", "fundo": BOTAO_FUNDO,
                      "tamanho": corpo, "raio": round(alt / 2),
                      "letterSpacing": "0.03em"}
                if familia:
                    el["fonte"] = familia
                elementos.append(el)
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
            if familia:
                el["fonte"] = familia
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
