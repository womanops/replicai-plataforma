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

import re

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
    plantada: tuple[str, ...] = ()     # bordas da prancheta que cortam a figura


@dataclass
class Leitura:
    pranchetas: list[Prancheta] = field(default_factory=list)
    escolhida: str = ""
    ambigua: bool = False          # havia mais de uma e ninguém escolheu
    canvas: dict = field(default_factory=dict)
    fundo: str = ""                # tudo que não anima, assado numa imagem só
    camadas: list[Camada] = field(default_factory=list)
    ignoradas: list[str] = field(default_factory=list)
    plantada_em: list[str] = field(default_factory=list)   # bordas com figura cortada


def _abrir(caminho: Path):
    from psd_tools import PSDImage
    return PSDImage.open(Path(caminho))


# largura da prévia de cada prancheta. Em 720 px dá para LER a peça — qual
# chamada, qual foto —, que é a decisão que está sendo tomada ali
PREVIA_LARGURA = 720


def previa_das_pranchetas(caminho: Path, destino: Path,
                          largura: int = PREVIA_LARGURA) -> list[dict]:
    """Uma imagem de verdade de cada prancheta, para escolher vendo.

    A tela recortava a MINIATURA embutida do PSD, que o Photoshop grava com
    256 px para o documento inteiro. Recortada numa prancheta, ela vira um
    borrão de sessenta pixels: dá para ver que tem algo azul, não para
    reconhecer qual é a peça — e escolher a prancheta errada é refazer tudo.

    Compor é barato perto de extrair: 0,5 a 3 segundos por prancheta no PSD de
    144 MB, contra os minutos da extração em camadas. Por isso dá para fazer
    enquanto a pessoa olha a lista.
    """
    caminho, destino = Path(caminho), Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    psd = _abrir(caminho)
    por_nome = {g.name: g for g in psd
                if getattr(g, "is_group", lambda: False)()}
    feitas = []
    for i, pr in enumerate(pranchetas(caminho)):
        arq = destino / f"prancheta-{i}.png"
        grupo = por_nome.get(pr.nome)
        try:
            caixa = (pr.x, pr.y, pr.x + pr.w, pr.y + pr.h)
            im = (grupo or psd).composite(viewport=caixa)
            if im is None:
                continue
            im = im.convert("RGB")
            if im.width > largura:
                im = im.resize((largura, max(1, round(im.height * largura / im.width))))
            im.save(arq)
        except Exception:
            continue          # prévia é conforto: sem ela a escolha ainda dá
        feitas.append({"nome": pr.nome, "previa": arq.name})
    return feitas


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


def _clipes_de(raiz) -> dict:
    """Quais camadas estão recortadas sobre cada base.

    No Photoshop, a camada com `clipping` aparece só onde a de baixo é opaca.
    Composta sozinha ela sai **vazia**, porque não há base para recortar —
    foi o que fez três fotos deste KV virarem PNG em branco. A unidade é
    base + recortadas, e é ela que se compõe.
    """
    unidades: dict = {}
    base = None
    for _, c in _plano(raiz):
        if getattr(c, "clipping", False):
            if base is not None:
                unidades.setdefault(id(base), []).append(c)
        else:
            base = c
    return unidades


def _e_foto(c, prancheta) -> bool:
    """Imagem que é conteúdo da peça, e não o fundo dela.

    O fundo sangra pelos quatro lados; foto de colagem ocupa um pedaço. A
    régua é a mesma que separa figura de textura em `_figuras_plantadas`.
    """
    if getattr(c, "kind", "") in AJUSTES or getattr(c, "kind", "") == "type":
        return False
    if not getattr(c, "visible", True) or getattr(c, "clipping", False):
        return False
    try:
        bb = c.bbox
    except Exception:
        return False
    if not bb or bb == (0, 0, 0, 0):
        return False
    x0, y0, x1, y1 = bb
    cheio = (x1 - x0) >= prancheta.w * 0.98 and (y1 - y0) >= prancheta.h * 0.98
    return not cheio


def separaveis(raiz, prancheta=None) -> list:
    """Quais camadas valem separar.

    Duas razões para soltar uma camada. A primeira é o texto: onde há palavra
    há hierarquia, e hierarquia é o que a animação revela. Então o grupo que
    contém texto é aberto, e o resto do arquivo — fundo, textura, grade,
    grain — vira uma imagem só.

    A segunda é a figura que a prancheta corta. Ela está plantada numa borda,
    e num quadro mais alto precisa continuar plantada **sem arrastar o
    conteúdo junto**: assada no fundo, ou o boneco flutua cortado no meio, ou
    a peça inteira desce atrás dele. Solta, o conteúdo centra e ele fica no
    chão — que foi o que a Ligia pediu, e é o que o arquivo permite, porque o
    corpo inteiro está lá.

    Assar o resto não é preguiça, é fidelidade. Remontar a pilha inteira de
    mesclagens e camadas de ajuste no navegador deu 11,6 de diferença média
    contra o composite do Photoshop; assar o que não anima deu 0,06.
    """
    escolhidas = []
    for c in raiz:
        if not c.visible or c.kind in AJUSTES or not _tem_texto(c):
            continue
        escolhidas.extend(list(_plano(c)) if c.is_group() else [(None, c)])
    soltas = [c for _, c in escolhidas]
    if prancheta is not None:
        for figura, lados in _figuras_plantadas(raiz, prancheta):
            # só o eixo vertical solta a camada. Amputar é o que acontece
            # quando se abre faixa sob quem está em pé; foto que sangra pela
            # lateral é grade de colagem, e soltá-la trouxe de volta o caso da
            # máscara de recorte, em que o PNG sai vazio
            if "baixo" not in lados and "cima" not in lados:
                continue
            if figura not in soltas:
                soltas.append(figura)
        # as fotos da colagem saem do fundo para poderem entrar na animação.
        # Assadas, elas são um PNG parado atrás do texto: metade da peça não
        # anima. A camada de fundo, que sangra pelos quatro lados, fica.
        for _, c in _plano(raiz):
            if c not in soltas and _e_foto(c, prancheta):
                soltas.append(c)
        # a assinatura também sai do fundo: é ela que fecha o vídeo no centro,
        # e assada no fundo nunca chegava lá. A logo bordada na manga do
        # personagem fica onde está — ela é arte dele, não assinatura da peça
        dentro = [c.bbox for c, _ in _figuras_plantadas(raiz, prancheta)]
        for _, c in _plano(raiz):
            if c in soltas or not getattr(c, "visible", True):
                continue
            if getattr(c, "kind", "") in AJUSTES or not MARCA.search(c.name or ""):
                continue
            try:
                bb = c.bbox
            except Exception:
                continue
            if not bb or bb == (0, 0, 0, 0):
                continue
            if any(bb[0] >= f[0] and bb[1] >= f[1] and bb[2] <= f[2] and bb[3] <= f[3]
                   for f in dentro):
                continue
            soltas.append(c)
    # na ordem da pilha do arquivo: é ela que diz quem cobre quem, e o braço
    # do mascote passa por cima do CTA porque no PSD ele está acima do texto
    pilha = {id(c): i for i, (_, c) in enumerate(_plano(raiz))}
    return sorted(soltas, key=lambda c: pilha.get(id(c), 0))


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
    plantadas = {id(c): lados for c, lados in _figuras_plantadas(raiz, alvo)}
    if nomes_separados is None:
        soltas = separaveis(raiz, alvo)
    else:
        pedidos = {n for n in nomes_separados}
        soltas = [c for c in todas if _nome_limpo(c.name) in pedidos]
    soltas = soltas[:limite]

    destino.mkdir(parents=True, exist_ok=True)
    ignoradas = []

    # o fundo é a prancheta composta pelo próprio Photoshop com as camadas
    # soltas desligadas: assim mesclagem, opacidade e camada de ajuste saem
    # exatas, sem o navegador precisar reproduzir nenhuma delas
    clipes = _clipes_de(raiz)
    # as recortadas acompanham a base: escondendo só a base, elas ficariam no
    # fundo sem o recorte e apareceriam espalhadas
    esconder = list(soltas) + [f for c in soltas for f in clipes.get(id(c), [])]
    antes = [(c, c.visible) for c in esconder]
    for c in esconder:
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

    # a prancheta inteira, com texto e tudo: é a peça que foi aprovada. O
    # `fundo.png` tem as camadas de texto desligadas, e mostrá-lo como "peça
    # original" na apresentação entregava ao cliente a arte sem a chamada
    try:
        inteira = raiz.composite()
        if inteira is not None:
            inteira.convert("RGB").save(destino / "arte-mae.png")
    except Exception as e:
        ignoradas.append(f"a composição da arte-mãe não saiu: {type(e).__name__}")

    camadas = []
    for i, c in enumerate(soltas):
        nome = _nome_limpo(c.name)
        meus = clipes.get(id(c), [])
        try:
            if meus:
                # base + recortadas, compostas juntas e aparadas na base: a
                # recortada sozinha sai vazia, porque não há o que recortar
                unidade = [c] + meus
                guardado = [(x, x.visible) for x in todas]
                for x in todas:
                    x.visible = x in unidade
                try:
                    inteira = raiz.composite()
                finally:
                    for x, v in guardado:
                        x.visible = v
                bb = c.bbox
                im = inteira.crop(tuple(bb)) if inteira is not None else None
            else:
                im = c.composite()
        except Exception as e:
            ignoradas.append(f"`{nome}` não abriu: {type(e).__name__}")
            continue
        if im is None or not im.getbbox():
            ignoradas.append(f"`{nome}` saiu vazia")
            continue
        # aparado na prancheta: o que ela corta não foi aprovado. O mascote da
        # Consigaz tem, na perna que a prancheta esconde, uma logo espelhada
        # ao contrário — mostrar isso num formato mais alto não é desdobrar a
        # peça, é publicar o que o designer tinha escondido
        x0, y0, x1, y1 = c.bbox
        cx0, cy0 = max(x0, alvo.x), max(y0, alvo.y)
        cx1, cy1 = min(x1, alvo.x + alvo.w), min(y1, alvo.y + alvo.h)
        if (cx0, cy0, cx1, cy1) != (x0, y0, x1, y1):
            if cx1 <= cx0 or cy1 <= cy0:
                ignoradas.append(f"`{nome}` está toda fora da prancheta")
                continue
            im = im.crop((cx0 - x0, cy0 - y0, cx1 - x0, cy1 - y0))
            x0, y0, x1, y1 = cx0, cy0, cx1, cy1
        arq = destino / f"{i:02d}-{_apelido(nome)}.png"
        im.save(arq)
        camadas.append(Camada(
            nome=nome,
            tipo="texto" if c.kind == "type" else "imagem",
            src=arq.name,
            box={"x": x0 - alvo.x, "y": y0 - alvo.y, "w": x1 - x0, "h": y1 - y0},
            texto=(c.text or "").replace("\r", " ").strip() if c.kind == "type" else "",
            fonte=_primeira_fonte(c) if c.kind == "type" else "",
            mesclagem=_mesclagem(c),
            opacidade=_opacidade(c),
            # só o eixo vertical: estar plantada é apoiar-se no chão (ou pender
            # do topo). Foto de colagem que sangra pela lateral é só foto
            # cortada pelo quadro — tratá-la como plantada grudava cada uma
            # numa borda e espatifava a colagem na capa do Facebook
            plantada=tuple(l for l in plantadas.get(id(c), ())
                           if l in ("baixo", "cima")),
        ))

    assadas = len(todas) - len(soltas)
    if assadas:
        ignoradas.append(f"{assadas} camadas foram assadas no fundo: não animam, mas "
                         f"saem exatas como o Photoshop as mostra")

    # só o que ficou assado prende o quadro. Figura solta é reposicionada
    # sozinha, e prender o quadro por causa dela arrastaria o conteúdo junto
    soltos = {id(c) for c in soltas}
    assadas_plantadas = sorted({lado for c, lados in _figuras_plantadas(raiz, alvo)
                                if id(c) not in soltos for lado in lados})
    plantada = assadas_plantadas
    livres = sorted({lado for c in camadas for lado in c.plantada})
    if livres:
        ignoradas.append(
            f"figura encostada em {', '.join(livres)}: ela sai do fundo e vai plantada "
            f"na borda do quadro novo, com o conteúdo centrado")
    if plantada:
        ignoradas.append(
            f"figura assada encostada em {', '.join(plantada)}: a faixa nova vai para o "
            f"outro lado, senão ela solta no ar e o corpo sai cortado no meio")

    return Leitura(pranchetas=lista, escolhida=alvo.nome, ambigua=ambigua,
                   canvas={"w": alvo.w, "h": alvo.h}, fundo=fundo_nome,
                   camadas=camadas, ignoradas=ignoradas, plantada_em=plantada)


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
ORDEM = {"figura": 0, "marca": 0, "headline": 1, "selo": 1, "apoio": 2, "cta": 3}


# o que, pelo nome da camada, é assinatura de marca
MARCA = re.compile(r"logo|marca|assinatura|lockup|wordmark", re.I)


def _papel_de(c: Camada, maior: Camada | None) -> str:
    if c.tipo != "texto":
        # nem toda imagem é marca. Chamar o mascote de `marca` fez o vídeo
        # tratá-lo como assinatura da peça: ele voava para o centro da tela,
        # cortado pela borda, enquanto a logo de verdade ficava assada no
        # fundo e nunca aparecia no fecho
        return "marca" if MARCA.search(c.nome or "") else "figura"
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
        # a fonte que o PSD pede viaja com a linha: é por ela que trocar o
        # texto depois pode sair na MESMA letra, em vez de na fonte da casa
        if c.tipo == "texto" and c.fonte:
            comum["fonte_mae"] = c.fonte
        if c.plantada:
            comum["plantado"] = list(c.plantada)
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


def tinta_de(leitura: Leitura) -> tuple[int, int, int, int] | None:
    """A caixa que envolve tudo que foi separado — o texto que a arte carrega.

    Com PNG isso é uma pergunta ao modelo, porque detectar por pixel confunde
    lettering com reflexo. Com PSD é conta: as camadas soltas são exatamente a
    tinta, e as caixas delas vêm do arquivo.
    """
    # a figura plantada fica de fora: a caixa dela passa da prancheta de
    # propósito (o corpo inteiro está no arquivo), e somá-la à tinta inflaria
    # a área protegida para além do próprio quadro
    # a figura plantada fica de fora; a foto da colagem também. A tinta é o
    # que a assinatura ocupa, e é por ela que o lockup é escalado na faixa
    camadas = [c for c in leitura.camadas
               if not c.plantada and (c.tipo == "texto" or MARCA.search(c.nome or ""))]
    camadas = camadas or [c for c in leitura.camadas if not c.plantada] or leitura.camadas
    if not camadas:
        return None
    xs0 = min(c.box["x"] for c in camadas)
    ys0 = min(c.box["y"] for c in camadas)
    xs1 = max(c.box["x"] + c.box["w"] for c in camadas)
    ys1 = max(c.box["y"] + c.box["h"] for c in camadas)
    return (xs0, ys0, xs1, ys1)


# quanto da largura segura o lockup ocupa quando é recomposto. Mais do que
# isso ele encosta na margem; menos, e some no meio do vazio.
LOCKUP_NA_LARGURA = 0.82

# o lockup não centraliza no espaço que sobrou: fica no alto dele, para deixar
# faixa abaixo. É ali que o CTA entra, centralizado sob a marca — pedido numa
# revisão, e o certo: botão pendurado no lockup lê como um conjunto só.
# Em 0,62 a faixa de baixo ficava com 158px para três elementos e o botão saía
# espremido; em 0,50 sobram 400 e a hierarquia cabe.
LOCKUP_NO_ALTO = 0.50


# a faixa precisa comportar o lockup: abaixo disto não é faixa, é borda
FAIXA_MINIMA = 40


def _ancora_do_recompor(leitura: Leitura, formato: dict, arte: Path) -> tuple[float, float]:
    """Para que lado a arte encosta, para a sobra virar uma faixa só.

    A sobra espalhada nos quatro lados não comporta lockup nenhum; encostada
    num canto, vira uma faixa usável. Qual lado depende da proporção: num
    destino mais largo que a arte a sobra é lateral, num mais alto ela é
    horizontal. E nunca do lado onde há figura plantada — abrir faixa ali
    descola a figura da borda em que ela se apoia.
    """
    from motor.replica import open_rgb

    with open_rgb(arte) as im:
        W, H = im.size
    plantada = set(leitura.plantada_em)
    if (formato["w"] / formato["h"]) > (W / H):
        # destino mais largo: a arte ao centro, e as duas faixas recebem os
        # blocos de texto. Encostá-la num lado deixava uma faixa só, larga
        # demais, com o lockup espalhado nela
        return (0.5, 0.5)
    # destino mais alto: a sobra é horizontal. O padrão é a arte no topo e o
    # lockup no rodapé, que é como se lê uma peça
    if "baixo" in plantada and "cima" not in plantada:
        return (0.5, 1.0)
    return (0.5, 0.0)


def _faixa_livre(base_box, formato: dict, fundo: Path | None = None,
                 tinta=None) -> tuple[int, int, int, int] | None:
    """A maior faixa que sobrou ao lado da arte, dentro da área segura.

    Quatro candidatas, e a maior vence. Antes só se olhava embaixo: numa capa
    de Facebook (1640×624 vinda de um quadrado) a arte ocupa a altura inteira
    e a sobra é lateral, então não havia rodapé nenhum e a peça não saía.
    """
    W, H, s = formato["w"], formato["h"], formato["safe"]
    ax0, ay0, ax1, ay1 = (int(v) for v in base_box)
    sx0, sy0 = s["left"], s["top"]
    sx1, sy1 = W - s["right"], H - s["bottom"]
    candidatas = {
        "baixo": (sx0, max(ay1, sy0), sx1, sy1),
        "cima": (sx0, sy0, sx1, min(ay0, sy1)),
        "esquerda": (sx0, sy0, min(ax0, sx1), sy1),
        "direita": (max(ax1, sx0), sy0, sx1, sy1),
    }
    cabem = [c for c in candidatas.values()
             if c[2] - c[0] >= FAIXA_MINIMA and c[3] - c[1] >= FAIXA_MINIMA]
    if not cabem:
        return None
    # a maior faixa era o único critério, e foi assim que o lockup branco do
    # 970x250 pousou na faixa branca: ela era a maior. Entre as que servem,
    # ganha a que LÊ; entre as que leem, a maior. Sem fundo para medir, a
    # conta antiga continua valendo.
    if fundo is not None and tinta is not None:
        from api.contraste import LOCKUP_MINIMO
        leem = [c for c in cabem if _le_na_zona(fundo, c, tinta) >= LOCKUP_MINIMO]
        if leem:
            cabem = leem
    return max(cabem, key=lambda c: (c[2] - c[0]) * (c[3] - c[1]))


# a barriga do mascote, em fração da altura visível dele. Medida na arte-mãe
# da Consigaz: a faixa branca do peito vai de 0,54 a 0,67 da altura dele e o
# bloco do CTA está centrado em 0,60 — bem no meio dela. Mais acima o texto
# bate no braço aberto, mais abaixo ele cruza a perna
BARRIGA = 0.60

# o vão entre o fim do texto e o corpo da figura, em fração da faixa. Na
# arte-mãe o CANDIDATE-SE termina a 7 px do corpo do Nino: é "encostado"
RESPIRO_NO_CORPO = 0.012

# um vão maior que isto, em fração da linha mais alta ao redor, separa blocos
VAO_ENTRE_BLOCOS = 0.8


def _blocos_de_texto(elementos: list[dict]) -> list[list[dict]]:
    """Agrupa as linhas de texto em blocos, pela distância entre elas.

    Na arte-mãe da Consigaz: "Chegamos" e "a Porto Belo!" ficam a 30 px um do
    outro e são um bloco; o próximo texto está 336 px abaixo e é outro. É como
    se lê a peça, e é a unidade que faz sentido mover junto.
    """
    linhas: dict[str, list[dict]] = {}
    for e in elementos:
        if e.get("papel") in ("headline", "apoio", "cta", "selo") and e.get("camada"):
            linhas.setdefault(e["camada"], []).append(e)
    if not linhas:
        return []
    caixas = []
    for nome, pedacos in linhas.items():
        y0 = min(p["box"]["y"] for p in pedacos)
        y1 = max(p["box"]["y"] + p["box"]["h"] for p in pedacos)
        caixas.append((y0, y1, pedacos))
    # pelo alto e pela base, NUNCA pelo terceiro item: duas linhas na mesma
    # altura — texto ao lado de texto, que é o normal num KV largo — faziam o
    # desempate cair nos próprios elementos, e dois dicionários não se comparam.
    # O banner de 728×90 morria aqui com "'<' not supported between dict"
    caixas.sort(key=lambda c: (c[0], c[1]))

    blocos, atual = [], [caixas[0]]
    for anterior, linha in zip(caixas, caixas[1:]):
        vao = linha[0] - anterior[1]
        altura = max(anterior[1] - anterior[0], linha[1] - linha[0])
        if vao > altura * VAO_ENTRE_BLOCOS:
            blocos.append(atual)
            atual = [linha]
        else:
            atual.append(linha)
    blocos.append(atual)
    return [[p for _, _, pedacos in b for p in pedacos] for b in blocos]


def _caixa(elementos: list[dict]) -> tuple[int, int, int, int]:
    xs0 = min(e["box"]["x"] for e in elementos)
    ys0 = min(e["box"]["y"] for e in elementos)
    xs1 = max(e["box"]["x"] + e["box"]["w"] for e in elementos)
    ys1 = max(e["box"]["y"] + e["box"]["h"] for e in elementos)
    return xs0, ys0, xs1, ys1


def _comeco_do_corpo(src: Path, abaixo: float = BARRIGA) -> float:
    """Em que fração da largura o CORPO da figura começa.

    O Nino está de braço aberto para a esquerda: medido pela tinta ele ocupa a
    caixa inteira, e encostar o texto na caixa é enfiá-lo embaixo do braço —
    que foi exatamente a reclamação. O corpo é onde a tinta é ALTA: da barriga
    ao pé ela não falha. No PNG dele o perfil pula de 0,13 para 0,89 na coluna
    0,533, e na arte-mãe o CANDIDATE-SE termina a 7 px dessa coluna.
    """
    try:
        import numpy as np
        from PIL import Image
        a = np.array(Image.open(src).convert("RGBA"))[..., 3] > 16
    except Exception:
        return 0.0                      # sem medida, o texto para na caixa
    faixa = a[int(a.shape[0] * abaixo):]
    if not faixa.size:
        return 0.0
    cheias = np.flatnonzero(faixa.mean(0) >= 0.5)
    return float(cheias.min() / a.shape[1]) if cheias.size else 0.0


def _faixa_limpa(src: Path, corpo: float, alto: float,
                 de: float = BARRIGA, ate: float = 0.85) -> float | None:
    """Onde cabe uma faixa de altura `alto` sem nada da figura à frente do
    corpo dela. Devolve o CENTRO da faixa, em fração da altura.

    O braço do Nino desce à frente do corpo até 0,59 da altura dele e só
    recolhe em 0,60. Centrar o CTA na barriga punha o canto de cima do bloco
    embaixo do cotovelo — não encostava em letra nenhuma, mas a régua de
    sobreposição mede o retângulo de tinta e acusava 6%. Descer o bloco até a
    primeira faixa limpa custa uns pixels e tira o aviso de vez.

    Tudo em fração da figura: `alto` é a altura do bloco dividida pela dela.
    """
    try:
        import numpy as np
        from PIL import Image
        a = np.array(Image.open(src).convert("RGBA"))[..., 3] > 16
    except Exception:
        return None                     # sem medida, fica na barriga
    h, w = a.shape
    cheia = np.where(a.any(1), a.argmax(1), w)      # primeira coluna com tinta
    passo = max(1, int(h * alto))
    limite = corpo * w - 2
    for topo in range(int(h * de - passo / 2), int(h * ate) - passo):
        if topo >= 0 and cheia[topo:topo + passo].min() >= limite:
            return (topo + passo / 2) / h
    return None


def _junto(e: dict, de: dict, para: dict) -> dict:
    """Leva um elemento que viajava dentro de `de` para o mesmo lugar em `para`.

    É a logo da manga do mascote: ela é uma camada de marca separada, e sem
    isto ficava para trás como uma sujeirinha branca no meio do nada quando
    ele mudava de tamanho e de lugar.
    """
    kx = para["w"] / max(1, de["w"])
    ky = para["h"] / max(1, de["h"])
    b = e["box"]
    return dict(e, box={"x": round(para["x"] + (b["x"] - de["x"]) * kx),
                        "y": round(para["y"] + (b["y"] - de["y"]) * ky),
                        "w": max(1, round(b["w"] * kx)),
                        "h": max(1, round(b["h"] * ky))})


def _dentro(e: dict, caixa: dict) -> bool:
    b = e["box"]
    return (caixa["x"] <= b["x"] + b["w"] / 2 <= caixa["x"] + caixa["w"]
            and caixa["y"] <= b["y"] + b["h"] / 2 <= caixa["y"] + caixa["h"])


def _assentar(elementos: list[dict], destino: tuple[float, float, float, float],
              largura_util: float, encostar: str = "centro") -> list[dict]:
    """Leva um bloco para `destino` (x0, y_centro, x1, —), escalado para caber.

    Escala uma vez, pelo bloco inteiro: linha a linha a relação entre elas se
    perde, e o que era um lockup vira texto solto.
    """
    x0, cy, x1, _ = destino
    bx0, by0, bx1, by1 = _caixa(elementos)
    k = min((x1 - x0) * largura_util / max(1, bx1 - bx0), 1.0)
    sobra = (x1 - x0) - (bx1 - bx0) * k
    alvo_x = x0 + (sobra if encostar == "direita" else sobra / 2)
    alvo_y = cy - (by1 - by0) * k / 2
    return [dict(e, box={
        "x": round(alvo_x + (e["box"]["x"] - bx0) * k),
        "y": round(alvo_y + (e["box"]["y"] - by0) * k),
        "w": max(1, round(e["box"]["w"] * k)),
        "h": max(1, round(e["box"]["h"] * k))}) for e in elementos]


def _remontar_largo(base: list[dict], info: dict, formato: dict,
                    pasta: Path | None = None) -> list[dict] | None:
    """A diagramação do destino bem mais largo que a arte.

    Direcional da Ligia: de uma peça quadrada para uma larga, o topo da peça
    base começa SEMPRE na esquerda da peça maior, e dali a leitura corre do
    começo para o fim. Na capa de página isso dá: a chamada centrada na faixa
    da esquerda com a logo em cima dela; as fotos ao centro; a linha de apoio
    onde ela já está em relação às fotos — que é embaixo da boca do fogão; o
    CTA à direita; e o mascote com a barriga encostada no fim do CANDIDATE-SE,
    para não ficar flutuando no vazio.

    O que vai para as faixas são os blocos das pontas, na ordem de leitura. O
    que está no meio acompanha a arte: ali a relação com a foto é o conteúdo.
    """
    from api import fundo as pf

    W, H, s = formato["w"], formato["h"], formato["safe"]
    ax0, ay0, ax1, ay1 = (int(v) for v in info["base_box"])
    esq = (s["left"], ax0)
    dir_ = (ax1, W - s["right"])
    if esq[1] - esq[0] < 120 or dir_[1] - dir_[0] < 120:
        return None                       # faixa estreita demais: outra rota

    movidos = [dict(e, box=pf.mover(e["box"], info["plano"])) for e in base]
    blocos = _blocos_de_texto(movidos)
    if len(blocos) < 2:
        return None

    de_bloco = {id(e) for b in blocos for e in b}
    marca = [e for e in movidos if e.get("papel") == "marca"]
    figura = [e for e in movidos if e.get("plantado") or e.get("papel") == "figura"]
    acompanham = [e for e in movidos
                  if id(e) not in de_bloco and e not in marca and e not in figura]
    # os blocos do meio ficam onde estão em relação à arte
    acompanham += [e for b in blocos[1:-1] for e in b]

    meio = H / 2
    # o que acompanha a arte: as fotos. O plantado é reposicionado adiante, e
    # entrar nas duas listas o desenhava duas vezes
    saida = list(acompanham) + [e for e in figura if not e.get("plantado")]

    # --- esquerda: a chamada, com a assinatura em cima dela ------------------
    primeira = _assentar(blocos[0], (esq[0], meio, esq[1], 0), LOCKUP_NA_LARGURA)
    topo = min(e["box"]["y"] for e in primeira)
    sobrando = list(marca)
    if marca:
        alta = max(marca, key=lambda e: e["box"]["w"] * e["box"]["h"])
        mx0, my0, mx1, my1 = _caixa([alta])
        k = min((esq[1] - esq[0]) * 0.34 / max(1, mx1 - mx0), 1.0)
        larg, alt = (mx1 - mx0) * k, (my1 - my0) * k
        respiro = round(alt * 0.9)
        saida.append(dict(alta, box={
            "x": round(esq[0] + ((esq[1] - esq[0]) - larg) / 2),
            "y": round(topo - respiro - alt),
            "w": round(larg), "h": round(alt)}))
        sobrando = [e for e in marca if e is not alta]
    saida += primeira

    # --- direita: o mascote plantado, e o CTA encostado na barriga dele ------
    plantados = [e for e in figura if e.get("plantado")]
    cy, ate = meio, W - s["right"]
    if plantados:
        boneco = max(plantados, key=lambda e: e["box"]["w"] * e["box"]["h"])
        antigo = boneco["box"]
        corpo = _comeco_do_corpo(pasta / boneco["src"]) if pasta and boneco.get("src") else 0.0
        folga = round((dir_[1] - dir_[0]) * RESPIRO_NO_CORPO)
        # o tamanho que faz o CORPO dele parar logo depois do fim do texto.
        # Ele mesmo encosta na borda direita, como na arte-mãe — figura pode
        # sangrar, texto não
        querida = (W - ate - folga) / max(0.1, 1 - corpo)
        k = min(querida / antigo["w"], H * 0.95 / antigo["h"],
                (W - dir_[0]) / antigo["w"])
        bw, bh = round(antigo["w"] * k), round(antigo["h"] * k)
        novo = {"x": W - bw, "y": H - bh, "w": bw, "h": bh}
        saida.append(dict(boneco, box=novo))
        saida += [_junto(e, antigo, novo) if _dentro(e, antigo) else e
                  for e in plantados if e is not boneco]
        sobrando = [_junto(e, antigo, novo) if _dentro(e, antigo) else e
                    for e in sobrando]
        cy = novo["y"] + bh * BARRIGA          # a linha da barriga
        if pasta and boneco.get("src"):
            _, by0, _, by1 = _caixa(blocos[-1])
            limpa = _faixa_limpa(pasta / boneco["src"], corpo, (by1 - by0) / bh)
            if limpa is not None:
                cy = novo["y"] + bh * limpa
        ate = min(ate, novo["x"] + round(bw * corpo) - folga)
    saida += sobrando
    saida += _assentar(blocos[-1], (dir_[0], cy, ate, 0), 1.0, encostar="direita")
    return saida


# quanto da peça a zona da assinatura toma quando o fundo enche o quadro.
# Pouco menos da metade: o assunto da imagem pede mais espaço que a assinatura,
# e a leitura corre do texto para a imagem, não o contrário.
ZONA_DA_ASSINATURA = 0.46

# as quatro zonas em que a assinatura pode pousar, na ordem em que valem quando
# a escolhida não lê
ZONAS_DA_PECA = ("esquerda", "direita", "rodape", "topo")

# abaixo disto a zona deixou de ser lugar e virou sobra. Mesma ideia do
# RESTO_MINIMO do sossego, aplicada à peça inteira.
ZONA_MINIMA = 0.22


def _maior_vao(ini: int, fim: int, ocupados: list[tuple[float, float]]) -> tuple[int, int]:
    """O maior pedaço de [ini, fim] que nenhum ocupado cobre."""
    livres, pos = [], ini
    for a, b in sorted(ocupados):
        if b <= pos:
            continue
        if a > pos:
            livres.append((pos, min(a, fim)))
        pos = max(pos, b)
        if pos >= fim:
            break
    if pos < fim:
        livres.append((pos, fim))
    a, b = max(livres, key=lambda p: p[1] - p[0], default=(ini, ini))
    return round(a), round(b)


def _tinta_do_lockup(base: list[dict], pasta: Path):
    """A cor da letra que veio no arquivo, para medir contraste contra o fundo.

    Média das camadas de assinatura, pelos pixels opacos delas. Sem isto a
    conta de contraste não existe: a plataforma só sabia a cor do texto que ela
    mesma escreve.
    """
    from api import contraste

    tons = [contraste.tom_da_tinta(pasta / e["src"])
            for e in base
            if e.get("src") and e.get("papel") in ("headline", "apoio", "cta",
                                                   "selo", "marca")]
    tons = [t for t in tons if t]
    if not tons:
        return None
    return tuple(round(sum(t[i] for t in tons) / len(tons)) for i in range(3))


def _le_na_zona(fundo: Path, zona, tinta) -> float:
    """O contraste que a tinta teria se o lockup pousasse nesta zona."""
    from PIL import Image

    from api import contraste

    if tinta is None or zona is None:
        return 0.0
    caixa = {"x": zona[0], "y": zona[1], "w": zona[2] - zona[0], "h": zona[3] - zona[1]}
    with Image.open(fundo) as im:
        return contraste.le_sobre(im.convert("RGB"), caixa, tinta)


def _zona_da_assinatura(fundo: Path, formato: dict, figuras: list[dict],
                        zona: str, tinta=None) -> list[int] | None:
    """Onde a assinatura se apoia quando o fundo enche a peça.

    Três cortes, nesta ordem: a zona que a direção escolheu, o que as figuras
    que acompanham o fundo não ocupam, e o pedaço quieto do que sobrou. Texto
    sobre o ponto agitado do desenho some, e texto em cima da figura é a
    sobreposição que a régua recusa em toda a casa — foi exatamente assim que
    o logo do cliente caiu em cima da chamada na primeira tentativa.
    """
    from PIL import Image

    from api import sossego

    W, H, s = formato["w"], formato["h"], formato["safe"]
    sx0, sy0, sx1, sy1 = s["left"], s["top"], W - s["right"], H - s["bottom"]
    caixas = {
        "esquerda": [sx0, sy0, round(W * ZONA_DA_ASSINATURA), sy1],
        "direita": [round(W * (1 - ZONA_DA_ASSINATURA)), sy0, sx1, sy1],
        "topo": [sx0, sy0, sx1, round(H * ZONA_DA_ASSINATURA)],
        "rodape": [sx0, round(H * (1 - ZONA_DA_ASSINATURA)), sx1, sy1],
    }
    # a zona que a direção escolheu vem primeiro; se a letra não se ler nela, a
    # peça prefere a zona que lê. Lugar bonito onde o texto some não é lugar —
    # e a letra do arquivo não muda de cor para resolver depois.
    if tinta is not None:
        from api.contraste import LOCKUP_MINIMO
        preferidas = [zona] + [z for z in ZONAS_DA_PECA if z != zona]
        melhor, nota = None, 0.0
        for cand in preferidas:
            achada = _zona_da_assinatura(fundo, formato, figuras, cand)
            if achada is None:
                continue
            r = _le_na_zona(fundo, achada, tinta)
            if r >= LOCKUP_MINIMO:
                return achada
            if r > nota:
                melhor, nota = achada, r
        return melhor

    r = list(caixas.get(zona) or caixas["esquerda"])
    deitada = zona in ("esquerda", "direita")

    # Figura que CABE na peça é coisa posta ali — um logotipo, um selo, um
    # mascote — e assinatura por cima dela é sobreposição. Figura que não cabe
    # é cenário: o brilho do KV atravessa a peça inteira e escrever sobre ele é
    # o normal, quem decide se dá para ler é o sossego, logo abaixo.
    # O maior vão, e não a primeira borda: uma coisa que entra pela lateral
    # empurra a zona para o outro lado dela em vez de zerá-la.
    ocupados = []
    for f in figuras:
        b = f["box"]
        if b["w"] > W or b["h"] > H:
            continue
        fx0, fy0, fx1, fy1 = b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
        if deitada and fy1 > r[1] and fy0 < r[3]:
            ocupados.append((fx0, fx1))
        elif not deitada and fx1 > r[0] and fx0 < r[2]:
            ocupados.append((fy0, fy1))
    if deitada:
        r[0], r[2] = _maior_vao(r[0], r[2], ocupados)
    else:
        r[1], r[3] = _maior_vao(r[1], r[3], ocupados)

    if (r[2] - r[0]) < W * ZONA_MINIMA or (r[3] - r[1]) < H * ZONA_MINIMA:
        return None
    with Image.open(fundo) as im:
        calmo = sossego.trecho_calmo(im.convert("RGB"), r)
    if calmo is None:
        return None
    if (calmo[2] - calmo[0]) < W * ZONA_MINIMA:
        return None
    return calmo


def _inteiras(figuras: list[dict], formato: dict) -> list[dict]:
    """Empurra para dentro do quadro a figura que a arte-mãe não cortava.

    Recortar o fundo é recortar cenário, e cenário cortado pela borda é como a
    peça já era. Uma figura que a mãe mostrava inteira é outra coisa: sair
    cortada ali não é enquadramento, é defeito — foi o logotipo do cliente
    saindo pela metade no alto do banner.
    """
    W, H = formato["w"], formato["h"]
    saida = []
    for f in figuras:
        b = dict(f["box"])
        # `plantado` é a figura que a mãe já cortava de propósito — o mascote
        # apoiado no rodapé. Essa continua plantada; mexer nela é que a
        # descolaria da borda
        if not f.get("plantado") and b["w"] <= W and b["h"] <= H:
            b["x"] = min(max(b["x"], 0), W - b["w"])
            b["y"] = min(max(b["y"], 0), H - b["h"])
        saida.append(dict(f, box=b))
    return saida


def _sobre_a_arte(base: list[dict], tinta, info: dict, formato: dict,
                  fundo: Path, escolhida: dict, desvios: list[str]) -> dict | None:
    """A composição quando o fundo enche a peça: o desenho acompanha o fundo e
    a assinatura vai por cima, na zona quieta.

    É a composição que faltava para a faixa extrema. Nas outras a arte cabe
    inteira e a assinatura mora na sobra; aqui não há sobra — a imagem é a
    peça, e o texto se apoia nela, que é como se monta um leaderboard.

    Devolve `None` quando a zona não dá lugar: nenhuma composição é melhor do
    que uma com a chamada em cima do assunto.
    """
    from api import fundo as pf

    W, H, s = formato["w"], formato["h"], formato["safe"]
    # a marca que a direção apontou sobe de desenho para assinatura. O arquivo
    # não diz qual camada é o logotipo do cliente — elas vêm com nome genérico
    # do Photoshop — e tratado como desenho ele acompanha o recorte e sai
    # cortado pela borda, que é o que não se faz com a marca de ninguém
    i_marca = escolhida.get("marca", -1)
    da_marca = {id(base[i_marca])} if isinstance(i_marca, int) and 0 <= i_marca < len(base) else set()

    def e_desenho(e: dict) -> bool:
        return (id(e) not in da_marca
                and (e.get("plantado") or e.get("papel") == "figura"))

    figuras = [dict(e, box=pf.mover(e["box"], info["plano"]))
               for e in base if e_desenho(e)]
    assinatura = [e for e in base if not e_desenho(e)]
    sai = set(escolhida.get("sai") or [])
    assinatura = [e for e in assinatura if (e.get("papel") or "") not in sai]
    if not assinatura:
        return None

    zona = _zona_da_assinatura(fundo, formato, figuras, escolhida["assinatura"],
                               _tinta_do_lockup(base, Path(fundo).parent))
    if zona is None:
        return None
    x0, y0, x1, y1 = zona

    lx0, ly0, lx1, ly1 = _caixa(assinatura) if sai else tinta
    k = min(((x1 - x0) * LOCKUP_NA_LARGURA) / max(1, lx1 - lx0),
            ((y1 - y0) * 0.70) / max(1, ly1 - ly0))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    meio_x, meio_y = (lx0 + lx1) / 2, (ly0 + ly1) / 2

    postos = [dict(e, box={
        "x": round(cx + (e["box"]["x"] - meio_x) * k),
        "y": round(cy + (e["box"]["y"] - meio_y) * k),
        "w": round(e["box"]["w"] * k), "h": round(e["box"]["h"] * k)})
        for e in assinatura]

    return {
        "formato": formato["id"],
        "canvas": {"w": W, "h": H},
        "safe": s,
        "saida": f"{formato['id']}.png",
        "via": "psd-sobre-a-arte",
        "fundo": {"tipo": "imagem", "src": info["src"], "fit": "cover"},
        "fontes": [],
        "elementos": _plantar(_inteiras(figuras, formato), formato) + postos,
        "descartados": {p: "não cabe nesta medida" for p in sorted(sai)},
        "_fundo": {**info, "direcao": escolhida, "desvios": desvios},
    }


def _mascara_do_lockup(assinatura: list[dict], pasta: Path, caixa, k: float):
    """O lockup inteiro numa máscara só, no tamanho que vai ter na peça.

    Serve para escolher o lugar medindo o contraste ONDE A LETRA ESTÁ. Pela
    média do retângulo um lockup largo atravessa fundo escuro e fundo claro, a
    média diz "ótimo" e a palavra some no meio — foi o que aconteceu no stories.
    """
    from PIL import Image

    larg = max(1, round((caixa[2] - caixa[0]) * k))
    alt = max(1, round((caixa[3] - caixa[1]) * k))
    tela = Image.new("RGBA", (larg, alt), (0, 0, 0, 0))
    for e in assinatura:
        arq = pasta / e["src"] if e.get("src") else None
        if arq is None or not arq.exists():
            continue
        b = e["box"]
        try:
            with Image.open(arq) as im:
                parte = im.convert("RGBA").resize(
                    (max(1, round(b["w"] * k)), max(1, round(b["h"] * k))),
                    Image.Resampling.LANCZOS)
        except Exception:
            continue
        tela.alpha_composite(parte, (round((b["x"] - caixa[0]) * k),
                                     round((b["y"] - caixa[1]) * k)))
    return tela


def _onde_le_na_faixa(fundo: Path, faixa, alto: float, tinta, convencao: float,
                      assinatura=None, pasta: Path | None = None,
                      caixa=None, k: float = 1.0) -> float:
    """Dentro da faixa, a altura em que o lockup se lê.

    A convenção manda o bloco para o alto da faixa (`LOCKUP_NO_ALTO`) e ela
    vale enquanto a letra se ler ali. Quando não se lê — faixa clara e letra
    branca, que foi o stories — o bloco desce ou sobe dentro da própria faixa
    até achar onde lê, em vez de sair da composição.
    """
    from api.contraste import LOCKUP_MINIMO

    if tinta is None:
        return convencao
    x0, y0, x1, y1 = faixa
    espaco = (y1 - y0) - alto
    if espaco <= 0:
        return convencao
    from PIL import Image

    meio_x = (x0 + x1) / 2
    with Image.open(fundo) as im:
        pronto = im.convert("RGB")
        notas = []
        for i in range(9):
            meio = y0 + alto / 2 + espaco * i / 8
            notas.append((meio, _nota_da_posicao(pronto, assinatura or [], pasta,
                                                 caixa, k, meio_x, meio)))

    melhor, nota = None, 0.0
    for meio, r in notas:
        if r >= LOCKUP_MINIMO:
            # entre as alturas que leem, a mais perto da convenção
            if melhor is None or abs(meio - convencao) < abs(melhor - convencao):
                melhor, nota = meio, r
        elif melhor is None and r > nota:
            nota, melhor = r, meio
    return melhor if melhor is not None else convencao


def _razao_na_caixa(fundo: Path, caixa: dict, tinta=None, mascara=None):
    """O contraste do lockup se ele pousasse nesta caixa — pela média do
    retângulo. Serve para zona; para altura dentro da faixa quem vale é
    `_nota_da_posicao`, que mede bloco a bloco."""
    from PIL import Image

    from api import contraste

    if tinta is None:
        return 1.0
    with Image.open(fundo) as im:
        return contraste.le_sobre(im.convert("RGB"), caixa, tinta, mascara)


def _nota_da_posicao(pronto, assinatura: list[dict], pasta: Path, caixa,
                     k: float, cx: float, cy: float) -> float:
    """O contraste da posição, medido no PIOR bloco do lockup.

    Pela média do lockup inteiro a conta volta a mentir num nível acima: dois
    blocos de letra com 72% e 25% da tinta sem contraste viram poucos por cento
    do total e a posição passa. Quem some é a PALAVRA, então a nota da posição
    é a do pior pedaço dela.
    """
    from api import contraste

    mx, my = (caixa[0] + caixa[2]) / 2, (caixa[1] + caixa[3]) / 2
    pior = None
    for e in assinatura:
        arq = pasta / e["src"] if e.get("src") else None
        if arq is None or not arq.exists():
            continue
        b = e["box"]
        onde = {"x": round(cx + (b["x"] - mx) * k), "y": round(cy + (b["y"] - my) * k),
                "w": max(1, round(b["w"] * k)), "h": max(1, round(b["h"] * k))}
        tom = contraste.tom_da_tinta(arq)
        medida = contraste.sob_a_tinta(pronto, onde, arq, tom)
        if medida is None:
            continue
        tipico, no_escuro = medida
        nota = 0.0 if no_escuro >= contraste.TINTA_NO_ESCURO else tipico
        pior = nota if pior is None else min(pior, nota)
    return 1.0 if pior is None else pior


def recompor(leitura: Leitura, formato: dict, pasta: Path,
             elementos: list[dict] | None = None, final: bool = False) -> dict:
    """Desdobra soltando o lockup do fundo.

    Reenquadrar preserva a relação entre a arte e o lockup, e é o certo quando
    a proporção muda pouco. Quando muda muito — 16:9 para 9:16 — preservar essa
    relação deixa o assunto fora do quadro e o lockup pequeno no meio do vazio.

    Aqui a arte encosta no topo, inteira, e o lockup desce para o espaço que
    sobrou, no tamanho que esse espaço comporta. Só dá para fazer isso porque
    as camadas vieram separadas: num PNG o lockup está grudado no fundo.
    """
    from api import fundo as pf

    pasta = Path(pasta)
    base = elementos if elementos is not None else como_elementos(leitura, pasta)
    tinta = tinta_de(leitura)
    if not base or not tinta:
        raise ValueError("não há lockup separado para recompor")

    from api import direcao
    from motor.replica import open_rgb

    arte = pasta / leitura.fundo
    destino = pasta / f"fundo-{formato['id']}.png"
    with open_rgb(arte) as im:
        W0, H0 = im.size

    # A DIREÇÃO DE ARTE, antes de qualquer pixel: cada proporção pede
    # composição própria. Conter a arte inteira num 728x90 a encolhe a 22% da
    # peça — o KV vira carimbo e o logo do cliente fica com 30 px — e aí não há
    # tratamento do "resto" que salve, porque o erro foi encolher.
    escala, inventaria, comprido = direcao.medir(W0, H0, formato)
    bruta, calou = direcao.decidir(arte, formato, base, True, escala, inventaria)
    escolhida, desvios = direcao.conferir(bruta, True, base)
    if calou:
        desvios.append(calou)
    if escolhida is None:
        escolhida = direcao.na_regua(True, escala, inventaria, comprido)

    if escolhida["fundo"] == "encher-recortando":
        # recortar o fundo não corta conteúdo: a tinta veio em camada separada
        # e é remontada por cima. A regra "nada é cortado" protege a TINTA, e
        # ela continua inteira
        info = pf.preparar(arte, formato, None, destino, estrategia="cover",
                           insistir=final, reaproveitar=final)
        peca = _sobre_a_arte(base, tinta, info, formato, destino,
                             escolhida, desvios)
        if peca is not None:
            return peca
        # a zona não deu lugar para a assinatura: volta para o caminho de
        # sempre, e o fundo é refeito junto
        desvios.append("não sobrou zona quieta para a assinatura por cima da "
                       "arte: a peça voltou para o enquadramento de sempre")

    ancora = _ancora_do_recompor(leitura, formato, arte)
    info = pf.preparar(arte, formato, None, destino,
                       estrategia="contain", ancora=ancora,
                       modo="solid" if escolhida["fundo"] == "campo" else "auto",
                       insistir=final, reaproveitar=final)
    info = {**info, "direcao": escolhida, "desvios": desvios}

    # destino bem mais largo: a arte vai ao centro e os blocos de texto ocupam
    # as duas faixas. Preservar a relação da arte-mãe numa faixa larga espalha
    # a chamada pelo vazio; aqui ela é rediagramada de propósito.
    largo = _remontar_largo(base, info, formato, pasta)
    if largo is not None:
        return {
            "formato": formato["id"],
            "canvas": {"w": formato["w"], "h": formato["h"]},
            "safe": formato["safe"],
            "saida": f"{formato['id']}.png",
            "via": "psd-recompor-largo",
            "fundo": {"tipo": "imagem", "src": info["src"], "fit": "cover"},
            "fontes": [],
            "elementos": largo,
            "_fundo": info,
        }

    W, H, s = formato["w"], formato["h"], formato["safe"]
    faixa = _faixa_livre(info["base_box"], formato, info["caminho"],
                         _tinta_do_lockup(base, pasta))
    if faixa is None:
        raise ValueError("a arte não deixou faixa livre para o lockup")
    x0, y0, x1, y1 = faixa

    lx0, ly0, lx1, ly1 = tinta
    k = min(((x1 - x0) * LOCKUP_NA_LARGURA) / max(1, lx1 - lx0),
            ((y1 - y0) * 0.70) / max(1, ly1 - ly0))
    cx = (x0 + x1) / 2
    assinatura = [e for e in base
                  if not (e.get("plantado") or e.get("papel") == "figura")]
    cy = _onde_le_na_faixa(info["caminho"], faixa, (ly1 - ly0) * k,
                           _tinta_do_lockup(base, pasta),
                           y0 + (y1 - y0) * LOCKUP_NO_ALTO / 2,
                           assinatura, pasta, tinta, k)
    meio_x, meio_y = (lx0 + lx1) / 2, (ly0 + ly1) / 2

    # O que é DESENHO acompanha a arte; só o que é ASSINATURA entra na faixa.
    # Foto e figura são desenho: escaladas pela medida do lockup, a colagem se
    # espatifa — as fotos saem voando para cantos diferentes, cada uma num
    # tamanho. Foi o que aconteceu quando elas passaram a ser camadas soltas
    # para poderem animar, e a capa do Facebook saiu irreconhecível.
    elementos_novos = []
    figuras = []
    for e in base:
        if e.get("plantado") or e.get("papel") == "figura":
            figuras.append(dict(e, box=pf.mover(e["box"], info["plano"])))
            continue
        b = e["box"]
        elementos_novos.append(dict(e, box={
            "x": round(cx + (b["x"] - meio_x) * k),
            "y": round(cy + (b["y"] - meio_y) * k),
            "w": round(b["w"] * k), "h": round(b["h"] * k)}))
    elementos_novos = _plantar(figuras, formato) + elementos_novos

    return {
        "formato": formato["id"],
        "canvas": {"w": W, "h": H},
        "safe": s,
        "saida": f"{formato['id']}.png",
        "via": "psd-recompor",
        "fundo": {"tipo": "imagem", "src": info["src"], "fit": "cover"},
        "fontes": [],
        "elementos": elementos_novos,
        "_fundo": info,
    }


# uma camada cortada pela borda que ocupa mais do que isso da largura dela é
# faixa ou textura de fundo, não figura. O KV da Consigaz tem as duas: o
# mascote corta 40% da borda de baixo (figura) e uma textura corta 91% da de
# cima (faixa)
FIGURA_ATE = 0.70


def _figuras_plantadas(raiz, prancheta) -> list[tuple[object, tuple[str, ...]]]:
    """As figuras que a prancheta corta, e em que bordas.

    Quem desenhou a peça encostou a figura ali de propósito: o mascote está
    plantado no rodapé e sai pela direita. O arquivo tem o corpo inteiro —
    na Consigaz a prancheta o corta no joelho, e os pés estão lá.
    """
    x0p, y0p = prancheta.x, prancheta.y
    x1p, y1p = x0p + prancheta.w, y0p + prancheta.h
    achadas: list[tuple[object, tuple[str, ...]]] = []

    def olhar(no):
        for c in no:
            if getattr(c, "is_group", lambda: False)():
                olhar(c)
                continue
            if not getattr(c, "visible", True) or getattr(c, "kind", "") in AJUSTES:
                continue
            try:
                bb = c.bbox
            except Exception:
                continue
            if not bb or bb == (0, 0, 0, 0):
                continue
            x0, y0, x1, y1 = bb
            larg, alt = x1 - x0, y1 - y0
            if larg <= 0 or alt <= 0:
                continue
            bordas = []
            if y1 > y1p and larg <= prancheta.w * FIGURA_ATE:
                bordas.append("baixo")
            if y0 < y0p and larg <= prancheta.w * FIGURA_ATE:
                bordas.append("cima")
            if x1 > x1p and alt <= prancheta.h * FIGURA_ATE:
                bordas.append("direita")
            if x0 < x0p and alt <= prancheta.h * FIGURA_ATE:
                bordas.append("esquerda")
            if bordas:
                achadas.append((c, tuple(bordas)))

    olhar(raiz)
    return achadas


def _bordas_com_figura(raiz, prancheta) -> set[str]:
    """Só as bordas, sem as camadas. Usada pela âncora do quadro."""
    bordas: set[str] = set()
    for _, lados in _figuras_plantadas(raiz, prancheta):
        bordas.update(lados)
    return bordas


def ancora_das_bordas(bordas: set[str]) -> tuple[float, float]:
    """Para que lado a arte encosta quando sobra quadro.

    Melhor prática de diagramação, e não preferência: o que está plantado numa
    borda continua plantado nela. A faixa nova vai para o lado onde a
    composição tem ar. Empate — figura cortada nos dois lados, ou em nenhum —
    volta ao centro, que é o comportamento antigo.
    """
    def eixo(a: str, b: str) -> float:
        if a in bordas and b not in bordas:
            return 0.0                 # encosta no começo do eixo
        if b in bordas and a not in bordas:
            return 1.0
        return 0.5

    return (eixo("esquerda", "direita"), eixo("cima", "baixo"))


# quanto o lockup pode encolher e a peça ainda ser "a mesma peça noutro
# tamanho". Olhado lado a lado no 728x90 do Energiza: a 39% o lockup inteiro,
# com o logotipo em cima do nome, lê melhor do que qualquer rediagramação —
# continua sendo a peça da marca, só menor. Acima de 40% ele vira legenda do
# desenho, e aí vale rediagramar de propósito em vez de espremer.
ENCOLHER_ATE = 0.40


# uma figura PEQUENA e ENCOSTADA no lockup foi posta ali em relação a ele — o
# logotipo do cliente em cima do nome da campanha é o caso, e no arquivo ele
# chega com nome genérico do Photoshop, sem dizer que é marca. Separá-lo do
# lockup no reenquadramento é o que o deixava fora do corte, ou empurrado para
# cima do nome. Grande demais é cenário: o brilho do KV também encosta.
MARCA_ATE = 0.02          # da área da arte
MARCA_PERTO = 0.05        # da menor dimensão da arte


def _da_assinatura(e: dict, tinta, W: int, H: int) -> bool:
    """Esta parte acompanha o lockup, ou acompanha o fundo?"""
    if e.get("plantado"):
        return False                      # plantada na borda: é do fundo
    if e.get("papel") != "figura":
        return True                       # texto, marca, selo: lockup
    b = e["box"]
    if not tinta or b["w"] * b["h"] > W * H * MARCA_ATE:
        return False
    perto = min(W, H) * MARCA_PERTO
    return not (b["x"] - perto > tinta[2] or b["x"] + b["w"] + perto < tinta[0]
                or b["y"] - perto > tinta[3] or b["y"] + b["h"] + perto < tinta[1])


def tinta_com_a_marca(leitura: "Leitura", base: list[dict], W: int, H: int):
    """A caixa do lockup somada às partes que andam com ele."""
    tinta = tinta_de(leitura)
    if not tinta:
        return None
    caixas = [e["box"] for e in base if _da_assinatura(e, tinta, W, H)]
    if not caixas:
        return tinta
    return (min(tinta[0], min(b["x"] for b in caixas)),
            min(tinta[1], min(b["y"] for b in caixas)),
            max(tinta[2], max(b["x"] + b["w"] for b in caixas)),
            max(tinta[3], max(b["y"] + b["h"] for b in caixas)))


def cabe_cortando(leitura: "Leitura", formato: dict, W: int, H: int,
                  base: list[dict] | None = None) -> float | None:
    """Quanto o lockup teria de encolher para caber inteiro no corte seco.

    O corte seco é o que a prévia da tela mostra desde sempre: a arte-mãe
    enchendo o formato, com o que passa da borda ficando de fora. Para vários
    destinos ele é a peça certa — e é a única rota que não encolhe o desenho,
    não inventa fundo e não custa nada.

    A conta diz se a tinta sobrevive a ele. `1.0` é cabe inteira sem tocar em
    nada; `0.95` é encolher 5%; `None` é não há tinta para conferir.
    """
    from api import fundo as pf
    from motor.replica import plan_fit

    tinta = (tinta_com_a_marca(leitura, base, W, H) if base is not None
             else tinta_de(leitura))
    if not tinta:
        return None
    plano = plan_fit(W, H, formato["w"], formato["h"], tinta, "cover", (0.5, 0.5), 0.0)
    caixa = pf.mover({"x": tinta[0], "y": tinta[1],
                      "w": tinta[2] - tinta[0], "h": tinta[3] - tinta[1]}, plano)
    s = formato["safe"]
    larg = max(1, formato["w"] - s["left"] - s["right"])
    alt = max(1, formato["h"] - s["top"] - s["bottom"])
    return min(1.0, larg / max(1, caixa["w"]), alt / max(1, caixa["h"]))


def _caber(elementos: list[dict], formato: dict, k: float) -> list[dict]:
    """Encolhe o lockup em `k` em torno do meio dele e o traz para dentro da
    área segura. O que é desenho não entra: ele acompanha o fundo, e escalá-lo
    junto desmontaria a colagem.
    """
    assinatura = [i for i, e in enumerate(elementos) if _e_assinatura(e)]
    if not assinatura:
        return elementos
    caixa = _caixa([elementos[i] for i in assinatura])
    cx, cy = (caixa[0] + caixa[2]) / 2, (caixa[1] + caixa[3]) / 2
    saida = list(elementos)
    for i in assinatura:
        b = elementos[i]["box"]
        saida[i] = dict(elementos[i], box={
            "x": round(cx + (b["x"] - cx) * k), "y": round(cy + (b["y"] - cy) * k),
            "w": max(1, round(b["w"] * k)), "h": max(1, round(b["h"] * k))})

    # depois de encolher, trazer o bloco inteiro para dentro da área segura —
    # de nada adianta caber e continuar com metade fora do quadro
    s, W, H = formato["safe"], formato["w"], formato["h"]
    x0, y0, x1, y1 = _caixa([saida[i] for i in assinatura])
    dx = max(0, s["left"] - x0) - max(0, x1 - (W - s["right"]))
    dy = max(0, s["top"] - y0) - max(0, y1 - (H - s["bottom"]))
    if dx or dy:
        for i in assinatura:
            b = saida[i]["box"]
            saida[i] = dict(saida[i], box={**b, "x": b["x"] + dx, "y": b["y"] + dy})
    return saida


# abaixo disto uma linha de texto deixa de ser lida na peça em tamanho real.
# O catálogo já dizia isso em prosa, pelo outro lado: o 728x90 e o 320x50 têm
# `apoio_max: 0` justamente porque ali não cabe linha de apoio. Levar a linha
# assim mesmo não preserva nada — entrega 7 px de sujeira em cima da arte e
# ainda obriga o resto do lockup a encolher para abrir espaço para ela.
LETRA_MINIMA = 12

# o que pode sair quando não é lido. A chamada e a marca nunca: peça sem elas
# não é a peça, é outra coisa — se a chamada não couber, o caminho é outro.
PODE_SAIR = ("apoio", "selo")


def _na_linha(b: dict, linha) -> bool:
    """Esta parte está deitada na mesma linha da chamada?

    O "20" e o "27" do Energiza ficam um de cada lado do nome, longe dele na
    horizontal e exatamente na altura dele. São o nome, não acessório: tirá-los
    por serem pequenos deixa a campanha sem o ano. Quem divide o lockup é a
    LINHA, como no resto da casa — não a distância nem o papel.
    """
    if not linha:
        return False
    alto = min(b["h"], linha[3] - linha[1]) or 1
    junto = min(b["y"] + b["h"], linha[3]) - max(b["y"], linha[1])
    return junto > alto * 0.5


def _ilegivel(e: dict, escala: float, linha=None) -> bool:
    """Esta linha vai ser lida no tamanho real da peça?"""
    return (e.get("papel") in PODE_SAIR
            and not _na_linha(e["box"], linha)
            and e["box"]["h"] * escala < LETRA_MINIMA)


def _so_o_que_se_le(elementos: list[dict], escala: float) -> tuple[list[dict], dict]:
    """Tira da peça a linha que não vai ser lida, e diz qual saiu."""
    chamada = [e for e in elementos if e.get("papel") == "headline"]
    linha = _caixa(chamada) if chamada else None
    fica = [e for e in elementos if not _ilegivel(e, escala, linha)]
    if len(fica) == len(elementos):
        return elementos, {}
    papeis = sorted({e.get("papel") or "?" for e in elementos
                     if _ilegivel(e, escala, linha)})
    return fica, {p: (f"sairia com menos de {LETRA_MINIMA} px de altura nesta medida "
                      f"e não seria lida") for p in papeis}


def _e_assinatura(e: dict) -> bool:
    return (e["assinatura"] if "assinatura" in e
            else not (e.get("plantado") or e.get("papel") == "figura"))


def _quanto_cabe(elementos: list[dict], formato: dict) -> float:
    """Quanto o lockup ainda precisa encolher, já nas coordenadas da peça."""
    assinatura = [e for e in elementos if _e_assinatura(e)]
    if not assinatura:
        return 1.0
    x0, y0, x1, y1 = _caixa(assinatura)
    s = formato["safe"]
    larg = max(1, formato["w"] - s["left"] - s["right"])
    alt = max(1, formato["h"] - s["top"] - s["bottom"])
    return min(1.0, larg / max(1, x1 - x0), alt / max(1, y1 - y0))


def reenquadrar(leitura: Leitura, formato: dict, pasta: Path,
                elementos: list[dict] | None = None, final: bool = False,
                cortando: float | None = None) -> dict:
    """Desdobra mantendo o lockup colado no fundo.

    O lockup sofre a mesma transformação que o fundo, então a relação entre
    ele e o desenho fica igual à do arquivo. É o certo quando a proporção muda
    pouco: a peça vira a mesma peça noutro tamanho.

    `cortando` é a mãe reenquadrada: em vez de caber a arte inteira e estender
    o que falta, a arte ENCHE o formato e o que passa da borda fica de fora —
    exatamente o corte que a prévia da tela mostra. É a melhor peça possível
    quando a tinta sobrevive ao corte, porque não encolhe o desenho, não
    inventa fundo e não custa nada. O valor é o quanto o lockup precisa
    encolher para nada dele ser cortado (`1.0` é nada).
    """
    from api import fundo as pf

    pasta = Path(pasta)
    base = elementos if elementos is not None else como_elementos(leitura, pasta)
    arte = pasta / leitura.fundo
    if cortando is not None:
        # quem anda com o lockup é decidido nas coordenadas da MÃE, antes de
        # qualquer movimento: depois de movido não dá mais para saber o que
        # estava encostado em quê
        from motor.replica import open_rgb
        with open_rgb(arte) as im:
            W0, H0 = im.size
        tinta0 = tinta_de(leitura)
        base = [dict(e, assinatura=_da_assinatura(e, tinta0, W0, H0)) for e in base]
    ancora = _ancora_centrada(leitura, formato, arte,
                              ancora_das_bordas(set(leitura.plantada_em)))
    protegido = (tinta_com_a_marca(leitura, base, W0, H0) if cortando is not None
                 else tinta_de(leitura))
    info = pf.preparar(arte, formato, protegido,
                       pasta / f"fundo-{formato['id']}.png", ancora=ancora,
                       estrategia="cover" if cortando is not None else "auto",
                       insistir=final, reaproveitar=final)
    movidos = _plantar([dict(e, box=pf.mover(e["box"], info["plano"])) for e in base],
                       formato)
    descartados: dict[str, str] = {}
    if cortando is not None:
        # o que não vai ser lido sai ANTES de encolher: sem a linha de apoio a
        # caixa do lockup é menor, e o que fica cabe maior
        movidos, descartados = _so_o_que_se_le(movidos, cortando)
        if descartados:
            cortando = _quanto_cabe(movidos, formato)
        # sempre, e não só quando encolhe: o lockup pode caber inteiro e ainda
        # assim estar dois pixels fora do quadro, que foi o logotipo do cliente
        # saindo cortado no alto do 320x50
        movidos = _caber(movidos, formato, min(1.0, cortando))
    elementos_finais, encolheu = _afastar(movidos, leitura, pasta, formato)
    return {
        "formato": formato["id"],
        "canvas": {"w": formato["w"], "h": formato["h"]},
        "safe": formato["safe"],
        "saida": f"{formato['id']}.png",
        "via": "psd-reenquadra-cortando" if cortando is not None else "psd-reenquadra",
        "fundo": {"tipo": "imagem", "src": info["src"], "fit": "cover"},
        "fontes": [],
        "elementos": elementos_finais,
        **({"descartados": descartados} if descartados else {}),
        "_fundo": {**info, "avisos": list(info.get("avisos") or []) + encolheu},
    }


def _cobertura(textos: list[tuple], figura: tuple) -> float:
    """Quanto a figura cobre do texto, pela régua da casa: fatia da largura do
    retângulo justo de tinta, tinta contra tinta."""
    from motor.replica import _ret_da_tinta, invasao_ret
    fm, fx, fy = figura
    pior = 0.0
    for tm, tx, ty in textos:
        ret = _ret_da_tinta(tm, tx, ty)
        if not ret:
            continue
        pior = max(pior, invasao_ret(ret, fm, (fx, fy)))
    return pior


def _mascaras(camadas, pasta: Path, escala: float = 1.0):
    """Alfa de cada camada, no tamanho em que ela vai aparecer."""
    from motor.replica import _alfa
    saida = []
    for c in camadas:
        arq = Path(pasta) / c.src
        if not arq.exists():
            continue
        w = max(1, round(c.box["w"] * escala))
        h = max(1, round(c.box["h"] * escala))
        try:
            saida.append((_alfa(arq, w, h), c))
        except Exception:
            continue
    return saida


def cobertura_na_mae(leitura: Leitura, pasta: Path) -> dict[str, float]:
    """Quanto a figura já cobria cada linha de texto no arquivo.

    É a linha de base da regra da casa: a adaptação não pode cobrir mais do
    que a arte-mãe cobria naquele mesmo par. No KV da Consigaz o braço do
    mascote cobre 16% do CANDIDATE-SE de propósito — é gesto de apresentar, e
    acusar isso como defeito seria acusar o desenho.
    """
    figuras = [c for c in leitura.camadas if c.plantada]
    textos = [c for c in leitura.camadas if c.tipo == "texto"]
    if not figuras or not textos:
        return {}
    mascaras = {c.nome: m for m, c in _mascaras(figuras + textos, pasta)}
    saida: dict[str, float] = {}
    for fig in figuras:
        if fig.nome not in mascaras:
            continue
        for t in textos:
            if t.nome not in mascaras:
                continue
            f = _cobertura([(mascaras[t.nome], t.box["x"], t.box["y"])],
                           (mascaras[fig.nome], fig.box["x"], fig.box["y"]))
            if f > 0:
                saida[t.nome] = max(saida.get(t.nome, 0.0), f)
    return saida


def _ancora_centrada(leitura: Leitura, formato: dict, arte: Path,
                     ancora: tuple[float, float]) -> tuple[float, float]:
    """Centra o bloco de conteúdo na altura útil da peça.

    Útil, e não o quadro cru: o Stories tem 250 px no topo e 340 no rodapé que
    o aplicativo cobre. Centrar no quadro inteiro joga o conteúdo para dentro
    da faixa que ninguém vê.

    Só vale quando há figura plantada no chão — é ela que ocupa o rodapé e
    sustenta a peça. Sem figura, centrar deixaria a arte boiando, e a âncora
    continua a de antes.
    """
    from api import fundo as pf
    from motor.replica import open_rgb, plan_fit

    if not any("baixo" in c.plantada for c in leitura.camadas):
        return ancora

    with open_rgb(arte) as img:
        W, H = img.size
    w, h = formato["w"], formato["h"]
    margem = pf._com_respiro(tinta_de(leitura), formato, W, H)
    estrategia, _ = pf.escolher_estrategia(W, H, w, h, margem)
    plano = plan_fit(W, H, w, h, margem, estrategia, (ancora[0], 0.5), 0.0)
    ex = plano["expand"]
    faixa = round((ex["top"] + ex["bottom"]) * plano["escala"])
    if faixa <= 0:
        return ancora

    sv = formato["safe"]
    bloco = h - faixa
    util = h - sv["top"] - sv["bottom"]
    topo = sv["top"] + max(0, (util - bloco)) / 2
    return (ancora[0], min(1.0, max(0.0, topo / faixa)))


# até onde vale encolher uma linha para ela sair de perto da figura. Abaixo
# disto o texto deixa de ser o que foi aprovado e vira outra tipografia
ENCOLHE_ATE = 0.78


def _afastar(elementos: list[dict], leitura: Leitura, pasta: Path,
             formato: dict) -> tuple[list[dict], list[str]]:
    """Diminui o corpo da linha que a figura passou a cobrir.

    Plantar a figura no chão e centrar o conteúdo afasta um do outro, e um
    pedaço mais largo do corpo dela cai sobre o fim da linha. Entregar assim
    seria entregar de qualquer jeito: a regra da casa é que a adaptação não
    cobre texto mais do que a arte-mãe cobria.

    Então a linha encolhe — ancorada na esquerda e na base, que é como ela
    está alinhada — até a conta voltar para dentro da regra. Encolher é a
    mexida menos invasiva disponível: não troca palavra, não muda de lugar e
    não corta nada.
    """
    from api.sobreposicao import PISO, TOLERANCIA
    from motor.replica import _ret_da_tinta, invasao_ret

    figuras = [e for e in elementos if e.get("plantado")]
    if not figuras:
        return elementos, []
    permitido = cobertura_na_mae(leitura, pasta)

    linhas: dict[str, list[int]] = {}
    for i, e in enumerate(elementos):
        if e.get("plantado") or not e.get("camada"):
            continue
        if e.get("papel") not in ("headline", "apoio", "cta", "selo"):
            continue
        linhas.setdefault(e["camada"], []).append(i)

    mascaras: dict[int, object] = {}

    def mascara(i: int, escala: float = 1.0):
        from motor.replica import _alfa
        e = elementos[i]
        arq = pasta / e["src"] if e.get("src") else None
        if arq is None or not arq.exists():
            return None
        try:
            return _alfa(arq, max(1, round(e["box"]["w"] * escala)),
                         max(1, round(e["box"]["h"] * escala)))
        except Exception:
            return None

    def cobertura(indices, k):
        """Quanto a figura cobre da linha, com ela encolhida em `k`."""
        caixas = [_caixa_encolhida(elementos, indices, i, k) for i in indices]
        x0 = min(b["x"] for b in caixas); y0 = min(b["y"] for b in caixas)
        x1 = max(b["x"] + b["w"] for b in caixas)
        y1 = max(b["y"] + b["h"] for b in caixas)
        pior = 0.0
        for fig in figuras:
            m = mascaras.get(id(fig))
            if m is None:
                continue
            fb = fig["box"]
            pior = max(pior, invasao_ret((x0, y0, x1 - x0, y1 - y0), m, (fb["x"], fb["y"])))
        return pior

    for fig in figuras:
        from motor.replica import _alfa
        arq = pasta / fig["src"] if fig.get("src") else None
        if arq is None or not arq.exists():
            continue
        try:
            mascaras[id(fig)] = _alfa(arq, int(fig["box"]["w"]), int(fig["box"]["h"]))
        except Exception:
            pass

    avisos = []
    saida = list(elementos)
    for camada, indices in linhas.items():
        teto = max(PISO, permitido.get(camada, 0.0) + TOLERANCIA)
        if cobertura(indices, 1.0) <= teto:
            continue
        escolhido = None
        for passo in range(1, 23):
            k = 1.0 - passo * (1.0 - ENCOLHE_ATE) / 22
            if cobertura(indices, k) <= teto:
                escolhido = k
                break
        k = escolhido or ENCOLHE_ATE
        for i in indices:
            saida[i] = dict(elementos[i], box=_caixa_encolhida(elementos, indices, i, k))
        if escolhido is None:
            avisos.append(
                f"`{camada}` encolheu {round((1-k)*100)}% e ainda encosta na figura: "
                f"diminua mais em Ajustar ou mova a linha")
        else:
            avisos.append(
                f"`{camada}` saiu {round((1-k)*100)}% menor para não encostar na figura "
                f"que ficou plantada no rodapé")
    return saida, avisos


def _caixa_encolhida(elementos, indices, i, k) -> dict:
    """A caixa do recorte com a linha reduzida em `k`, ancorada na esquerda e
    na base: é como o texto está alinhado, e é o que puxa a ponta direita
    para longe da figura sem mexer no começo da frase."""
    caixas = [elementos[j]["box"] for j in indices]
    x0 = min(b["x"] for b in caixas)
    y1 = max(b["y"] + b["h"] for b in caixas)
    b = elementos[i]["box"]
    return {"x": round(x0 + (b["x"] - x0) * k),
            "y": round(y1 - (y1 - b["y"]) * k),
            "w": max(1, round(b["w"] * k)),
            "h": max(1, round(b["h"] * k))}


def _plantar(elementos: list[dict], formato: dict) -> list[dict]:
    """Encosta na borda do quadro a figura que a prancheta cortava.

    O conteúdo fica onde o reenquadramento o pôs — centrado, quando sobra
    quadro dos dois lados. Só a figura desce até o chão. Era o pedido: "no
    rodapé só o boneco, o conteúdo centralizado".

    Ela não é esticada nem reposicionada no eixo em que não estava plantada:
    só o lado que o quadro cortava encosta de novo.
    """
    W, H = formato["w"], formato["h"]
    saida = []
    for e in elementos:
        lados = e.get("plantado") or []
        if not lados:
            saida.append(e)
            continue
        b = dict(e["box"])
        if "baixo" in lados:
            b["y"] = H - b["h"]
        if "cima" in lados:
            b["y"] = 0
        if "direita" in lados:
            b["x"] = W - b["w"]
        if "esquerda" in lados:
            b["x"] = 0
        saida.append(dict(e, box=b))
    return saida


def desdobrar(leitura: Leitura, formato: dict, pasta: Path,
              modo: str = "auto", final: bool = False) -> dict:
    """Escolhe entre manter o lockup colado no fundo ou soltá-lo.

    A régua é a mesma do fundo: enquanto preservar a arte inteira não deixa a
    peça virar moldura, reenquadrar é melhor, porque mantém o desenho como ele
    foi feito. Passando disso, o assunto sai do quadro e o lockup fica pequeno
    no meio do vazio — e aí vale soltar.
    """
    from api import fundo as pf
    from PIL import Image

    pasta = Path(pasta)
    corte = None
    if modo == "auto":
        with Image.open(pasta / leitura.fundo) as im:
            W, H = im.size
        qual, _ = pf.escolher_estrategia(W, H, formato["w"], formato["h"],
                                         tinta_de(leitura))
        modo = "reenquadra" if qual == "contain" else "recompoe"

        # A MÃE REENQUADRADA vem antes das duas: a arte enche o formato, o que
        # passa da borda fica de fora e o lockup encolhe só o necessário para
        # nada dele ser cortado. É o corte que a prévia da tela mostra desde
        # sempre — e a Ligia estava certa ao perguntar por que a peça não sai
        # igual a ele. Não sai porque a regra de não cortar era lida sobre a
        # arte inteira; ela protege a TINTA, e aqui a tinta está medida e
        # salva. Sem encolher desenho, sem inventar fundo, sem custo.
        k = cabe_cortando(leitura, formato, W, H, como_elementos(leitura, pasta))
        if k is not None and k >= 1 - ENCOLHER_ATE and leitura.camadas:
            corte, modo = k, "reenquadra"
    if modo == "recompoe" and leitura.camadas:
        return recompor(leitura, formato, pasta, final=final)
    return reenquadrar(leitura, formato, pasta, final=final, cortando=corte)
