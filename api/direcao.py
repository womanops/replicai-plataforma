"""A direção de arte do desdobramento: quem decide a composição de cada peça.

Até aqui ninguém decidia. A plataforma tinha réguas — não cortar, não escrever
por cima, não encostar na margem, não inventar cor — e régua sabe **não
errar**; ela não sabe **fazer uma peça**. O resultado aparecia inteiro na faixa
extrema: para caber num 728x90 o KV de 1920x1080 era encolhido a 12%, virava um
carimbo de 160 px com o logo do cliente ilegível, e o que sobrava da peça era
tratado como "resto" — continuado, esticado ou chapado. Qualquer tratamento do
resto é maquiagem: o erro aconteceu antes, na decisão de encolher.

O princípio que faltava é um só, e é o do diretor de arte:

> **Cada proporção pede composição própria.** 9:16, 4:5 e 728x90 não são cortes
> do mesmo layout — são peças com hierarquia e área segura próprias.

Daí vêm as quatro decisões que este módulo toma, nesta ordem:

1. **O que acontece com o fundo** — encher recortando, continuar o desenho ou
   virar campo de cor. Recortar o fundo era proibido por uma regra larga
   demais ("nada é cortado"); a regra existe para proteger a TINTA, e num PSD a
   tinta vem em camada separada. Cortar o fundo ali não corta conteúdo nenhum.
2. **Onde a assinatura se apoia** — a faixa quieta em que marca, chamada e
   apoio se leem. Zona, não pixel.
3. **Qual parte é a marca do cliente** — porque o arquivo não diz: as camadas
   vêm com nome genérico do Photoshop, e o logotipo tratado como desenho de
   fundo acompanha o recorte e sai cortado pela borda.
4. **O que sai** quando não cabe tudo, na ordem da hierarquia.

Quem decide é o modelo, que está olhando a arte. Quem calcula as caixas é a
máquina, e quem confere são as réguas que já existem — mesma divisão do resto
da casa. Decisão que não passa na régua é recusada e a peça volta para o
comportamento determinístico, dizendo que voltou: queda calada já entregou peça
de régua com cara de peça do modelo.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# o contrato

FUNDOS = ("encher-recortando", "continuar", "campo")
ZONAS = ("esquerda", "direita", "topo", "rodape")

ESQUEMA = {
    "type": "object",
    "properties": {
        "fundo": {"type": "string", "enum": list(FUNDOS)},
        "assinatura": {"type": "string", "enum": list(ZONAS)},
        "marca": {"type": "integer"},
        "sai": {"type": "array", "items": {"type": "string"}},
        "porque": {"type": "string"},
    },
    "required": ["fundo", "assinatura", "marca", "sai", "porque"],
    "additionalProperties": False,
}

# a hierarquia da assinatura, do que fica por último ao que sai primeiro. Serve
# de rede quando o modelo não responde: sem ela "o que sai" vira sorteio.
HIERARQUIA = ("marca", "headline", "apoio", "selo", "cta")

INSTRUCAO = """Você é o diretor de arte de um desdobramento.

Uma peça aprovada vai virar outra medida. Você NÃO cria arte nova: decide a
composição desta medida, a partir do que a peça-mãe já tem.

O princípio que manda: cada proporção pede composição própria. A peça nova não
é um corte nem uma redução do layout da mãe — é uma peça com hierarquia e área
segura próprias.

Decida quatro coisas.

1. O FUNDO desta medida:
   - "encher-recortando": o fundo da mãe é recortado e enche a peça de ponta a
     ponta. É o certo quando a medida é muito mais comprida ou mais alta que a
     mãe e conter a arte inteira a encolheria a ponto de ela virar um carimbo.
     Só pode quando a tinta (marca, chamada, apoio) vem em camada separada,
     porque aí recortar o fundo não corta conteúdo nenhum.
   - "continuar": o desenho do fundo segue para além da borda da mãe. É o certo
     quando falta pouco — até cerca de uma vez e meia a arte no eixo que
     cresce. Mais que isso o desenho não continua, ele se repete.
   - "campo": o fundo vira um campo de cor liso da paleta da arte, com a arte
     apoiada nele. É o último recurso: um bloco liso com a arte pequena no meio
     lê como peça mal montada, não como escolha.

2. A ASSINATURA — "esquerda", "direita", "topo" ou "rodape": a zona em que
   marca, chamada e apoio vão se ler. Numa medida comprida a leitura corre da
   esquerda para a direita, então a assinatura à esquerda e o assunto da imagem
   à direita é a composição que funciona. Numa medida alta, assunto em cima e
   assinatura embaixo. Escolha a zona mais quieta do fundo: texto sobre o ponto
   agitado do desenho some.

3. A MARCA: o número da parte da lista que carrega o logotipo do cliente, ou
   -1 se nenhuma carregar. Isto importa porque o arquivo não diz: as camadas
   costumam vir com nome genérico do Photoshop, e o logotipo do cliente tratado
   como desenho de fundo acompanha o recorte e sai cortado pela borda. Marca é
   assinatura: vai junto da chamada e nunca é cortada.

4. O QUE SAI: as partes que não cabem nesta medida, pelo nome que veio na
   lista. Numa faixa de 90 px de altura cabem duas linhas, não cinco. Sair é
   decisão de hierarquia, não desistência: o que sai primeiro é o acessório
   (selo, data, ornamento), o que fica por último é a marca. Não tendo o que
   tirar, devolva lista vazia.

Responda só o JSON do contrato, com um "porque" de uma frase, em português, que
diga a decisão de composição — não o procedimento."""


def _pedido(formato: dict, partes: list[dict], em_camadas: bool,
            escala: float, inventaria: float) -> str:
    """O que o modelo precisa saber além da imagem: a medida, as partes e as
    duas contas que a máquina já sabe fazer melhor que ele — quanto a arte
    encolheria e quanto de cenário teria de ser inventado."""
    lista = "\n".join(
        f"[{i}] {p.get('papel') or 'sem papel'}: "
        f"{round(p['box']['w'])}x{round(p['box']['h'])} px "
        f"em ({round(p['box']['x'])}, {round(p['box']['y'])}) da mãe"
        for i, p in enumerate(partes)) or "- (nenhuma parte separada)"
    return (
        f"MEDIDA DE DESTINO: {formato['w']}x{formato['h']} px"
        f" (área segura: {formato['safe']}).\n"
        f"A TINTA VEM EM CAMADA SEPARADA: {'sim' if em_camadas else 'não'}.\n"
        f"CABENDO A ARTE INTEIRA, ela entraria a {round(escala * 100)}% do "
        f"tamanho que tem hoje — tudo nela encolhe nessa proporção, inclusive "
        f"o logotipo.\n"
        f"CONTINUANDO O DESENHO, seria preciso inventar {inventaria:.1f}x a "
        f"arte no eixo que mais cresce.\n\n"
        f"PARTES DA PEÇA-MÃE:\n{lista}")


def disponivel() -> bool:
    """Há com quem decidir? Sem credencial a esteira segue na régua."""
    from api import modelo
    return modelo.disponivel() and os.environ.get("REPLICAI_SEM_DIRECAO", "0") != "1"


def decidir(arte, formato: dict, partes: list[dict], em_camadas: bool,
            escala: float, inventaria: float, cliente=None) -> tuple[dict | None, str]:
    """A composição desta medida, decidida por quem está olhando a arte.

    Uma chamada por formato — e não por trabalho, como a leitura: é justamente
    a medida que muda a decisão.

    Devolve `(decisão, motivo de não ter vindo)`. Nada aqui derruba a peça:
    sem credencial, sem imagem que o modelo abra, com recusa, com resposta
    torta, com a chave sem crédito ou com a rede fora, a régua assume. Mas o
    motivo volta junto e vira ressalva na peça — queda calada já entregou peça
    de régua com cara de peça do modelo uma vez, e foi assim que ninguém
    percebeu durante dias.
    """
    from api import modelo

    if not disponivel():
        return None, ""
    img = modelo._imagem(arte)
    if not img:
        return None, ""

    try:
        import anthropic
        cliente = cliente or anthropic.Anthropic()
        r = cliente.messages.create(
            model=modelo.MODELO,
            max_tokens=2000,
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": ESQUEMA}},
            messages=[{"role": "user", "content": [
                img,
                {"type": "text", "text": INSTRUCAO},
                {"type": "text", "text": _pedido(formato, partes, em_camadas,
                                                 escala, inventaria)},
            ]}],
        )
    except Exception as e:
        return None, (f"a direção de arte não respondeu ({type(e).__name__}): "
                      f"a composição desta peça saiu pela régua")
    from api import custo
    custo.registrar(modelo.MODELO, getattr(r, "usage", None))
    if getattr(r, "stop_reason", None) == "refusal":
        return None, "a direção de arte se recusou a decidir esta peça"
    try:
        return json.loads(next((b.text for b in r.content if b.type == "text"),
                               "null")), ""
    except (json.JSONDecodeError, StopIteration):
        return None, "a direção de arte respondeu fora do contrato"


def conferir(decisao: dict | None, em_camadas: bool, partes: list[dict]) -> tuple[dict | None, list[str]]:
    """A decisão passa? Devolve (decisão válida ou None, desvios).

    Confere só o que a régua sabe conferir sozinha, antes de qualquer pixel
    ser desenhado: o resto — cor fora da paleta, traço inventado, texto em cima
    do desenho — continua sendo conferido na peça pronta, onde já era.

    Recusar inteiro e não em parte é de propósito: meia decisão de composição
    não é composição, e remendar a escolha do modelo com a régua foi o que
    entregou peça de régua com cara de peça do modelo.
    """
    if not decisao:
        return None, []
    desvios = []
    if decisao.get("fundo") not in FUNDOS:
        desvios.append(f"fundo desconhecido: {decisao.get('fundo')!r}")
    if decisao.get("assinatura") not in ZONAS:
        desvios.append(f"zona desconhecida: {decisao.get('assinatura')!r}")
    # recortar o fundo só não corta conteúdo quando a tinta está em camada
    # separada. Num arquivo achatado ela está dentro do fundo, e o corte comeria
    # a marca — que é a regra da casa que isto NÃO afrouxa
    if decisao.get("fundo") == "encher-recortando" and not em_camadas:
        desvios.append("mandou recortar o fundo de uma arte sem camadas: "
                       "a tinta está dentro dele e o corte comeria a marca")
    marca = decisao.get("marca")
    if not isinstance(marca, int) or marca < -1 or marca >= len(partes):
        desvios.append(f"apontou uma parte que não existe como marca: {marca!r}")
    papeis = {(p.get("papel") or "") for p in partes}
    sai = set(decisao.get("sai") or [])
    fora = sai - papeis
    if fora:
        desvios.append(f"mandou tirar o que a peça não tem: {', '.join(sorted(fora))}")

    # sair é hierarquia, não desistência: o acessório sai primeiro e a marca
    # fica por último. Tirar o que vale mais e deixar o que vale menos é a
    # decisão invertida, e nenhuma régua conserta isso depois
    def posto(papel: str) -> int:
        return HIERARQUIA.index(papel) if papel in HIERARQUIA else len(HIERARQUIA)

    invertido = sorted({f"tirou `{a}` e deixou `{b}`"
                        for a in sai & papeis for b in papeis - sai
                        if posto(a) < posto(b)})
    if invertido:
        desvios.append("a hierarquia saiu ao contrário — "
                       + "; ".join(invertido)
                       + f". A ordem é {', '.join(HIERARQUIA)}")
    return (None if desvios else decisao), desvios


def na_regua(em_camadas: bool, escala: float, inventaria: float,
             comprido: bool) -> dict:
    """A mesma decisão, sem modelo. É a rede, e ela erra para o lado seguro.

    Sem credencial a plataforma continua funcionando com menos qualidade, em
    vez de recusar o trabalho — como em todo o resto da casa.
    """
    # "campo" não sai da régua de propósito. Ela não olha a peça, e bloco de
    # cor é a decisão mais fácil de tomar errado: arte pequena num campo liso
    # lê como peça mal montada, e continuar o desenho — mesmo esticando a
    # conversa da arte — ainda entrega uma peça da marca. Campo de cor é
    # escolha de quem está vendo, e quem está vendo é o modelo.
    fundo = ("encher-recortando" if (em_camadas and escala < ESCALA_MINIMA)
             else "continuar")
    return {"fundo": fundo,
            "assinatura": "esquerda" if comprido else "rodape",
            # a régua não sabe qual parte é o logotipo do cliente: o arquivo não
            # diz e ela não olha. Sem modelo, nenhuma é promovida a marca — e o
            # que segura a figura é a regra de não cortar o que a mãe não corta
            "marca": -1,
            "sai": [],
            "porque": "composição pela régua: não havia com quem decidir"}


# abaixo disto a arte-mãe deixa de se ler: não é mais arte na peça, é carimbo.
# A régua é a ESCALA e não a área que ela ocupa, porque o que decide é
# legibilidade, não proporção. Medido no Energiza: numa story a arte entra a
# 56% e tudo nela se lê — arte em cima, assinatura embaixo, composição clássica
# e nada é cortado. Num 728x90 ela entraria a 8%, e aí o logo do cliente fica
# com 30 px: nessa altura preservar a arte inteira não preserva nada.
ESCALA_MINIMA = 0.20

# acima disto o generativo não continua o desenho, repete. Medido na mesma
# família: a 1,2x a continuação ainda lê como cenário, a 2,2x volta o mesmo
# borrão. É o número que a instrução cita para o modelo; a régua não decide
# campo de cor sozinha (ver `na_regua`).
REPETE = 1.5


def medir(W: int, H: int, formato: dict) -> tuple[float, float, bool]:
    """As duas contas que decidem, e se o destino é comprido.

    `escala`: a que tamanho a arte inteira entraria na peça. É o que decide o
    carimbo, porque o que importa é se a mãe ainda se lê — e tudo nela encolhe
    junto, inclusive o logotipo do cliente.

    `inventaria`: quantas vezes a arte teria de ser inventada para continuar o
    desenho, no eixo que mais cresce. Por eixo porque o que faz o generativo
    repetir é a distância que ele tem de preencher numa direção só.
    """
    w, h = formato["w"], formato["h"]
    escala = min(w / W, h / H)
    comprido = (w / h) > (W / H)
    if comprido:                                # cresce na largura
        inventaria = (w / escala - W) / W
    else:                                       # cresce na altura
        inventaria = (h / escala - H) / H
    return escala, inventaria, comprido
