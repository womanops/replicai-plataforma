"""O PSD aberto em camadas, para a peça inteira se mexer.

Com PNG, a arte chega achatada: o lettering, a marca e a assinatura estão
grudados no fundo, e a animação só consegue tratar tudo como um bloco. É por
isso que o desdobramento em PNG anima só o que a plataforma acrescenta.

Com PSD cada camada vira um arquivo com a posição dela, e aí o CONSIGAZ pode
entrar antes, o lettering subir atrás de um corte e o ano assentar depois.

Duas coisas que o arquivo real ensinou, e que um leitor ingênuo erra:

- **um PSD pode ter várias pranchetas.** O Key Visual do Energiza tem seis
  versões lado a lado, num quadro de 7942x2256, e só a quarta é a arte que
  estava sendo adaptada. Ler o arquivo inteiro daria uma colagem.
- **camada de ajuste não tem pixel próprio.** Matiz/Saturação e Brilho/Contraste
  modificam o que está abaixo; extrair como imagem devolve nada ou um quadrado
  vazio.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# não têm pixel próprio: modificam o que está abaixo
AJUSTES = {"huesaturation", "brightnesscontrast", "curves", "levels", "gradientmap",
           "colorbalance", "photofilter", "invert", "posterize", "threshold",
           "selectivecolor", "channelmixer", "exposure", "vibrance", "blackandwhite"}

# acima disso a peça vira um enxame e o render não aguenta
LIMITE_CAMADAS = 60


@dataclass
class Prancheta:
    nome: str
    x: int
    y: int
    w: int
    h: int

    @property
    def proporcao(self) -> float:
        return self.w / max(1, self.h)


# Photoshop e CSS chamam quase tudo pelo mesmo nome, o que é sorte: a peça
# renderiza num navegador. O que não tem equivalente vira o parente mais
# próximo, e o que é normal nem entra no elemento.
MESCLAGEM = {
    "NORMAL": "", "PASS_THROUGH": "",
    "MULTIPLY": "multiply", "SCREEN": "screen", "OVERLAY": "overlay",
    "DARKEN": "darken", "LIGHTEN": "lighten",
    "COLOR_DODGE": "color-dodge", "COLOR_BURN": "color-burn",
    "HARD_LIGHT": "hard-light", "SOFT_LIGHT": "soft-light",
    "DIFFERENCE": "difference", "EXCLUSION": "exclusion",
    "HUE": "hue", "SATURATION": "saturation", "COLOR": "color",
    "LUMINOSITY": "luminosity",
    "LINEAR_DODGE": "screen",     # sem equivalente no CSS; screen é o vizinho
    "LINEAR_BURN": "color-burn",
    "VIVID_LIGHT": "hard-light", "LINEAR_LIGHT": "hard-light",
    "PIN_LIGHT": "hard-light", "HARD_MIX": "hard-light",
}


@dataclass
class Camada:
    nome: str
    tipo: str                      # "texto" ou "imagem"
    src: str
    box: dict
    texto: str = ""
    fonte: str = ""
    mesclagem: str = ""            # valor de CSS, vazio quando é normal
    opacidade: float = 1.0


@dataclass
class Leitura:
    pranchetas: list[Prancheta] = field(default_factory=list)
    escolhida: str = ""
    ambigua: bool = False          # havia mais de uma e ninguém escolheu
    canvas: dict = field(default_factory=dict)
    fundo: str = ""                # tudo que não anima, assado numa imagem só
    camadas: list[Camada] = field(default_factory=list)
    ignoradas: list[str] = field(default_factory=list)


def _abrir(caminho: Path):
    from psd_tools import PSDImage
    return PSDImage.open(Path(caminho))


def pranchetas(caminho: Path) -> list[Prancheta]:
    """As pranchetas do arquivo, ou uma só com o quadro inteiro.

    PSD sem prancheta é o caso comum; tratar os dois pelo mesmo caminho evita
    um ramo a mais em tudo que vem depois.
    """
    psd = _abrir(caminho)
    achadas = []
    for g in psd:
        if not getattr(g, "is_group", lambda: False)():
            continue
        try:
            dados = g.tagged_blocks.get_data(b"artb")
        except Exception:
            dados = None
        if not dados:
            continue
        r = dados[b"artboardRect"]
        achadas.append(Prancheta(g.name, int(r[b"Left"]), int(r[b"Top "]),
                                 int(r[b"Rght"]) - int(r[b"Left"]),
                                 int(r[b"Btom"]) - int(r[b"Top "])))
    if achadas:
        return achadas
    return [Prancheta("", 0, 0, psd.width, psd.height)]


def escolher(lista: list[Prancheta], nome: str = "",
             proporcao: float | None = None) -> tuple[Prancheta, bool]:
    """Qual prancheta usar, e se a escolha foi um chute.

    Por nome, quando quem pediu sabe. Senão pela proporção da arte de
    referência — mas no arquivo real as seis pranchetas têm a mesma proporção,
    então isso não desempata nada e escolheria a errada calada. Quando sobra
    mais de uma candidata, o segundo valor volta `True` e quem chamou pergunta
    em vez de fingir que sabe.
    """
    if nome:
        achada = next((p for p in lista if p.nome == nome), None)
        if achada is None:
            raise ValueError(f"não existe prancheta `{nome}`. "
                             f"Tem: {', '.join(p.nome for p in lista) or '(nenhuma nomeada)'}")
        return achada, False
    if len(lista) == 1:
        return lista[0], False
    if proporcao:
        por_proporcao = sorted(lista, key=lambda p: abs(p.proporcao - proporcao))
        melhor = por_proporcao[0]
        empatadas = [p for p in lista if abs(p.proporcao - melhor.proporcao) < 0.02]
        return melhor, len(empatadas) > 1
    return max(lista, key=lambda p: p.w * p.h), True


def _plano(camadas, prefixo: str = ""):
    """Desce nos grupos. O lockup vive num grupo e precisa vir separado: é a
    diferença entre a marca entrar junto com o lettering e cada um no seu tempo."""
    for i, c in enumerate(camadas):
        chave = f"{prefixo}{i:02d}"
        if c.is_group():
            yield from _plano(c, f"{chave}-")
        else:
            yield chave, c


def _nome_limpo(nome: str) -> str:
    """O PSD guarda o nome com enchimento: vem `fundo\x00`. Sem limpar, o nulo
    vai para o nome do arquivo e para o texto que o modelo lê."""
    return (nome or "").replace("\x00", "").strip()


def _apelido(nome: str) -> str:
    import re
    base = re.sub(r"[^a-z0-9]+", "-", (nome or "camada").lower()).strip("-")
    return base[:40] or "camada"


def _tem_texto(camada) -> bool:
    if camada.kind == "type":
        return True
    if camada.is_group():
        return any(_tem_texto(f) for f in camada)
    return False


def separaveis(raiz) -> list:
    """Quais camadas valem separar para animar.

    A regra é o texto: onde há palavra há hierarquia, e hierarquia é o que a
    animação revela. Então o grupo que contém texto é aberto, e o resto do
    arquivo — fundo, textura, grade, grain — vira uma imagem só.

    Assar o resto não é preguiça, é fidelidade. Remontar a pilha inteira de
    mesclagens e camadas de ajuste no navegador deu 11,6 de diferença média
    contra o composite do Photoshop; assar o que não anima deu 0,06.
    """
    escolhidas = []
    for c in raiz:
        if not c.visible or c.kind in AJUSTES or not _tem_texto(c):
            continue
        escolhidas.extend(list(_plano(c)) if c.is_group() else [(None, c)])
    return [c for _, c in escolhidas]


def extrair(caminho: Path, destino: Path, nome_prancheta: str = "",
            proporcao: float | None = None, limite: int = LIMITE_CAMADAS,
            nomes_separados: list[str] | None = None) -> Leitura:
    """Abre uma prancheta: o fundo assado e as camadas que vão animar."""
    caminho, destino = Path(caminho), Path(destino)
    lista = pranchetas(caminho)
    alvo, ambigua = escolher(lista, nome_prancheta, proporcao)

    psd = _abrir(caminho)
    raiz = psd
    if alvo.nome:
        raiz = next((g for g in psd if getattr(g, "is_group", lambda: False)()
                     and g.name == alvo.nome), None)
        if raiz is None:
            raise ValueError(f"a prancheta `{alvo.nome}` sumiu do arquivo")

    todas = [c for _, c in _plano(raiz)]
    if nomes_separados is None:
        soltas = separaveis(raiz)
    else:
        pedidos = {n for n in nomes_separados}
        soltas = [c for c in todas if _nome_limpo(c.name) in pedidos]
    soltas = soltas[:limite]

    destino.mkdir(parents=True, exist_ok=True)
    ignoradas = []

    # o fundo é a prancheta composta pelo próprio Photoshop com as camadas
    # soltas desligadas: assim mesclagem, opacidade e camada de ajuste saem
    # exatas, sem o navegador precisar reproduzir nenhuma delas
    antes = [(c, c.visible) for c in soltas]
    for c in soltas:
        c.visible = False
    try:
        chapado = raiz.composite()
    finally:
        for c, v in antes:
            c.visible = v
    fundo_nome = ""
    if chapado is not None:
        fundo_nome = "fundo.png"
        chapado.convert("RGB").save(destino / fundo_nome)

    camadas = []
    for i, c in enumerate(soltas):
        nome = _nome_limpo(c.name)
        try:
            im = c.composite()
        except Exception as e:
            ignoradas.append(f"`{nome}` não abriu: {type(e).__name__}")
            continue
        if im is None or not im.getbbox():
            ignoradas.append(f"`{nome}` saiu vazia")
            continue
        arq = destino / f"{i:02d}-{_apelido(nome)}.png"
        im.save(arq)
        x0, y0, x1, y1 = c.bbox
        camadas.append(Camada(
            nome=nome,
            tipo="texto" if c.kind == "type" else "imagem",
            src=arq.name,
            box={"x": x0 - alvo.x, "y": y0 - alvo.y, "w": x1 - x0, "h": y1 - y0},
            texto=(c.text or "").replace("\r", " ").strip() if c.kind == "type" else "",
            fonte=_primeira_fonte(c) if c.kind == "type" else "",
            mesclagem=_mesclagem(c),
            opacidade=_opacidade(c),
        ))

    assadas = len(todas) - len(soltas)
    if assadas:
        ignoradas.append(f"{assadas} camadas foram assadas no fundo: não animam, mas "
                         f"saem exatas como o Photoshop as mostra")

    return Leitura(pranchetas=lista, escolhida=alvo.nome, ambigua=ambigua,
                   canvas={"w": alvo.w, "h": alvo.h}, fundo=fundo_nome,
                   camadas=camadas, ignoradas=ignoradas)


def _mesclagem(c) -> str:
    nome = getattr(getattr(c, "blend_mode", None), "name", "NORMAL")
    return MESCLAGEM.get(nome, "")


def _opacidade(c) -> float:
    """Opacidade da camada vezes a do preenchimento.

    Em camada sem efeito as duas se multiplicam, e ignorar a segunda deixa a
    peça com o dobro da força em quem foi desenhado para ficar discreto.
    """
    o = getattr(c, "opacity", 255) or 0
    f = getattr(c, "fill_opacity", 255)
    f = 255 if f is None else f
    return round((o / 255) * (f / 255), 4)


def _primeira_fonte(c) -> str:
    """O nome da fonte que o PSD pede. Não é enfeite: quando ela não está
    instalada, o texto sai noutra letra e ninguém avisa."""
    try:
        fontes = c.resource_dict.get("FontSet") or []
    except Exception:
        return ""
    for f in fontes:
        # cada item é um descritor do psd-tools, não um dicionário, e o valor
        # não é str: é um objeto cujo texto sai entre aspas. Sem converter, o
        # `in` levantava dentro do try e o nome da fonte sumia calado
        try:
            nome = str(dict(f).get("Name") or "").strip("'\"")
        except Exception:
            continue
        if nome and "AdobeInvis" not in nome and nome != "MyriadPro-Regular":
            return nome
    return ""


# acima disto a frase leva mais tempo do que a peça tem, e letra de 20px solta
# não se lê: a assinatura entra linha a linha em vez de letra a letra
LETRAS_DEMAIS = 14

# a ordem em que o lockup se monta. Veio de uma revisão: marca, depois o nome
# com o ano, depois a assinatura — é a ordem em que se lê, não a ordem em que
# as camadas estão empilhadas no arquivo.
ORDEM = {"marca": 0, "headline": 1, "selo": 1, "apoio": 2, "cta": 3}


def _papel_de(c: Camada, maior: Camada | None) -> str:
    if c.tipo != "texto":
        return "marca"
    if c is maior:
        return "headline"
    if c.texto.strip().isdigit():
        return "selo"
    return "apoio"


def como_elementos(leitura: Leitura, pasta: Path | None = None) -> list[dict]:
    """As camadas soltas viram elementos da peça, com papel e ordem de motion.

    O papel decide **como** cada coisa entra; a ordem decide **quando**. Sem
    ordem, o ano entra junto da marca porque o vocabulário de motion trata selo
    e marca como a mesma família — e o lockup se monta fora de ordem.

    Camada de texto grande é cortada em letras, para o preset de lettering
    animar uma a uma. Sem isso a camada entra inteira, que é transição de
    slide e não motion.
    """
    from api.letras import fatiar

    textos = [c for c in leitura.camadas if c.tipo == "texto"]
    maior = max(textos, key=lambda c: c.box["w"] * c.box["h"], default=None)

    elementos = []
    for c in leitura.camadas:
        papel = _papel_de(c, maior)
        ordem = ORDEM.get(papel, 9)
        comum = {"tipo": "imagem", "papel": papel, "fit": "fill", "ancorado": True,
                 "camada": c.nome, "ordem": ordem}
        if c.mesclagem:
            comum["mesclagem"] = c.mesclagem
        if c.opacidade < 1:
            comum["opacidade"] = c.opacidade

        pedacos = []
        if c.tipo == "texto" and pasta is not None:
            alvo = Path(pasta)
            pedacos = fatiar(alvo / c.src, alvo, prefixo=Path(c.src).stem)
            if len(pedacos) > LETRAS_DEMAIS:
                pedacos = fatiar(alvo / c.src, alvo, prefixo=Path(c.src).stem,
                                 modo="linha")

        if not pedacos:
            e = dict(comum, src=c.src, box=dict(c.box))
            if c.texto:
                e["conteudo"] = c.texto
            elementos.append(e)
            continue

        for i, pe in enumerate(pedacos):
            elementos.append(dict(comum, src=pe["src"], letra=i, de=c.nome, box={
                "x": c.box["x"] + pe["dx"], "y": c.box["y"] + pe["dy"],
                "w": pe["w"], "h": pe["h"]}))
    return elementos


def como_peca(leitura: Leitura, formato_id: str, safe: dict | None = None,
              pasta: Path | None = None) -> dict:
    """A peça pronta para o motor, no tamanho nativo da prancheta."""
    return {
        "formato": formato_id,
        "canvas": dict(leitura.canvas),
        "safe": safe or {"top": 0, "bottom": 0, "left": 0, "right": 0},
        "saida": f"{formato_id}.png",
        "via": "psd-camadas",
        "fundo": {"tipo": "imagem", "src": leitura.fundo, "fit": "cover"},
        "fontes": [],
        "elementos": como_elementos(leitura, pasta),
    }
