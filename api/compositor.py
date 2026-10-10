"""Quem decide como a peça fica.

O motor não compõe: seus comandos executam uma ordem já dada. Alguém tem que
decidir a caixa de cada elemento, o papel de cada um, a ordem de empilhamento e
como o texto é reescrito para caber naquele formato. Hoje quem faz isso é o
Claude lendo o PIPELINE.md.

Isso ainda não está resolvido para a plataforma — ver `docs/DECISAO-quem-compoe.md`.
Por isso a composição vive atrás desta interface: o resto da esteira (upload,
fila, render, validação, entrega) se constrói em volta sem depender da escolha,
e no dia em que ela for feita só entra um implementador novo aqui.
"""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Protocol

from api.diagramacao import convencao, onde_acaba_a_arte
from motor.replica import formato_by_id


class Compositor(Protocol):
    """Recebe a arte aprovada e um formato; devolve a peça pronta para render."""

    def compor(self, base: Path, formato_id: str, brief: str = "",
               terreno: "Terreno | None" = None) -> dict:
        ...


class ComposicaoImpossivel(RuntimeError):
    """O compositor não dá conta desta peça. Quem chama decide: tenta outro
    compositor, ou devolve para o humano. Nunca entrega peça errada calada."""


# ----------------------------------------------------------------- arquivo pronto

class CompositorArquivo:
    """Lê uma peça JSON que alguém já escreveu.

    É o que destrava a esteira hoje: as peças que o agente compôs continuam
    valendo, e dá para rodar a plataforma inteira de ponta a ponta com elas
    enquanto a composição automática não existe.
    """

    def __init__(self, pasta: Path):
        self.pasta = Path(pasta)

    def compor(self, base: Path, formato_id: str, brief: str = "",
               terreno: "Terreno | None" = None) -> dict:
        arq = self.pasta / f"{formato_id}.json"
        if not arq.exists():
            raise ComposicaoImpossivel(
                f"não existe peça pronta para `{formato_id}` em {self.pasta}")
        return json.loads(arq.read_text(encoding="utf-8"))


# ----------------------------------------------------------------- regra simples

@dataclass
class Terreno:
    """O chão onde a peça vai ser composta, pronto antes de qualquer texto.

    `fundo` é o que entra no campo `fundo` da peça. `livres` são as faixas que a
    extensão criou — é só nelas que texto novo entra, e é isso que impede a
    sobreposição sobre o que a arte já carrega. `ja_escrito` é o que a arte já
    diz, para não ser dito duas vezes.
    """
    fundo: dict
    livres: dict = field(default_factory=dict)
    ja_escrito: list[str] = field(default_factory=list)
    fontes: list[dict] = field(default_factory=list)
    tinta: list[int] | None = None      # onde a arte já tem texto, na peça final


class CompositorSimples:
    """Regra determinística: a arte vira fundo, o texto entra na área segura.

    Serve o caso fácil — uma chamada, um CTA, sem recorte nem camada. Custa zero
    por peça e responde em milissegundos. Não tenta nada além disso: peça com
    mascote recortado e lettering ilustrado levanta `ComposicaoImpossivel` em vez
    de entregar algo torto.
    """

    def __init__(self, headline: str, cta: str = "", cor_texto: str = "#ffffff",
                 fonte: str = "PecaSans"):
        self.headline = headline.strip()
        self.cta = cta.strip()
        self.cor_texto = cor_texto
        self.fonte = fonte

    def compor(self, base: Path, formato_id: str, brief: str = "",
               terreno: "Terreno | None" = None) -> dict:
        f = formato_by_id(formato_id)
        if not f:
            raise ComposicaoImpossivel(f"formato desconhecido: {formato_id}")
        if not self.headline:
            raise ComposicaoImpossivel("sem headline não há peça")

        limite = f["texto"].get("headline_max", 0)
        if limite and len(self.headline) > limite:
            raise ComposicaoImpossivel(
                f"a headline tem {len(self.headline)} caracteres e `{formato_id}` "
                f"comporta {limite}. Encurtar é decisão de quem escreve, não minha")

        W, H = f["w"], f["h"]
        s = f["safe"]
        # a área segura é o que sobra depois das margens que a rede recorta
        x = s["left"] + round(W * 0.04)
        larg = W - x - s["right"] - round(W * 0.04)
        alt_util = H - s["top"] - s["bottom"]

        if terreno is not None and not terreno.livres:
            raise ComposicaoImpossivel(
                "a arte preenche este formato e já traz o texto dela: escrever por cima "
                "cobriria o que ela mostra. Esta peça é a arte reenquadrada")
        caixas = _caixas_na_faixa(f, terreno, ["headline"] + (["cta"] if self.cta else []))
        elementos = [{
            "tipo": "texto", "papel": "headline", "texto": self.headline,
            "box": caixas[0] if caixas else {"x": x, "y": s["top"] + round(alt_util * 0.30),
                                             "w": larg, "h": round(alt_util * 0.34)},
            "fonte": self.fonte, "peso": 700, "cor": self.cor_texto,
            "min": max(14, round(H * 0.045)), "max": round(H * 0.14),
            "lineHeight": 1.05, "align": "left", "valign": "middle",
        }]

        if self.cta:
            limite_cta = f["texto"].get("cta_max", 0)
            if limite_cta == 0:
                raise ComposicaoImpossivel(
                    f"`{formato_id}` não leva CTA, e veio um: \"{self.cta}\"")
            if len(self.cta) > limite_cta:
                raise ComposicaoImpossivel(
                    f"o CTA tem {len(self.cta)} caracteres e `{formato_id}` comporta {limite_cta}")
            elementos.append({
                "tipo": "texto", "papel": "cta", "texto": self.cta,
                "box": caixas[1] if len(caixas) > 1 else
                       {"x": x, "y": H - s["bottom"] - round(alt_util * 0.20),
                        "w": larg, "h": round(alt_util * 0.11)},
                "fonte": self.fonte, "peso": 700, "cor": self.cor_texto,
                "min": max(11, round(H * 0.022)), "max": round(H * 0.055),
                "lineHeight": 1.1, "align": "left", "valign": "middle",
            })

        return {
            "formato": formato_id,
            "canvas": {"w": W, "h": H},
            "safe": s,
            "saida": f"{formato_id}.png",
            "via": "regra-simples",
            # só o nome: o `src` da peça é relativo à pasta do job, e o motor
            # o resolve a partir dela. Caminho absoluto aqui prenderia a peça
            # à máquina que a compôs.
            "fundo": terreno.fundo if terreno else
                     {"tipo": "imagem", "src": Path(base).name, "fit": "cover"},
            "fontes": terreno.fontes if terreno else [],
            "elementos": elementos,
        }


def _caixas_na_faixa(formato: dict, terreno, papeis: list[str]) -> list[dict]:
    """As caixas da régua, quando o fundo deixou faixa livre.

    Sem terreno a régua compõe como sempre, no meio da peça. Com terreno ela
    usa a mesma geometria do compositor do modelo — não há razão para a régua
    escrever sobre a arte quando o modelo não escreve.
    """
    if not terreno or not terreno.livres:
        return []
    from api.composicao import Elemento, _posicionar
    zona = "baixo-esquerda"
    pos = _posicionar(formato, {zona: [Elemento(p, zona) for p in papeis]},
                      terreno.livres, terreno.tinta)
    return pos.get(zona, [])


# ----------------------------------------------------------------- modelo + regra

def _onde_cabe(livres: dict | None) -> str:
    """Traduz as faixas livres do fundo para o vocabulário de zonas.

    O modelo não precisa saber que houve extensão: precisa saber onde pode
    escrever. Dizer isso aqui evita a rodada de correção que a recusa custaria.
    """
    if livres is None:
        return ""
    if not livres:
        return ("A arte preenche o formato inteiro e já traz o texto dela. Não há espaço "
                "livre: não componha nada por cima. Responda com `elementos` vazio e "
                "explique em `descartados` o que ficou de fora.")
    faixas = []
    if "top" in livres:
        faixas.append("topo-*")
    if "bottom" in livres:
        faixas.append("baixo-*")
    if "left" in livres or "right" in livres:
        faixas.append("as laterais")
    return (f"Só há espaço livre em {', '.join(faixas)} — o resto é a arte, e escrever "
            f"ali cobriria o que ela já mostra. Use só essas zonas.")


def instrucao(formato: dict, brief: str = "", marcas: list[str] | None = None,
              ja_escrito: list[str] | None = None, livres: dict | None = None,
              material: str | None = None, tinta=None) -> str:
    """O que o modelo precisa saber para compor este formato.

    Leva as regras da casa como restrição, não como texto de apoio: o
    experimento mostrou que um modelo com o pipeline no prompt ainda escolhe o
    caminho errado quando nada confere depois.
    """
    t = formato.get("texto", {})
    limites = ", ".join(f"{k.replace('_max','')} até {v} caracteres" if v else
                        f"{k.replace('_max','')} não cabe neste formato"
                        for k, v in t.items())
    return f"""Você compõe uma peça de {formato['w']}x{formato['h']} ({formato['nome']}, {formato['canal']}).

Responda em papéis e zonas, nunca em pixels. A posição exata é calculada depois.

Papéis: marca, headline, apoio, cta, selo. Zonas: topo/meio/baixo combinado com
esquerda/centro/direita, por exemplo "meio-esquerda".

Limites deste formato: {limites}.
Convenção do formato: {formato.get('notas', '—')}
Diagramação: {convencao(formato)} {onde_acaba_a_arte(tinta, formato)}

Regras:
- Um papel só aparece uma vez.
- Headline é obrigatória.
- Texto que não cabe no limite deve ser encurtado por você, não truncado depois.
- Não escreva frase nova. Use só o que está no material abaixo, encurtando se
  precisar. Papel sem material é papel que fica de fora, e vai em `descartados`.
- Encurtar é tirar palavra que sobra, não é deixar um pedaço solto. Se o que
  restar não se sustentar sozinho — uma palavra avulsa, uma frase pela metade —
  deixe o papel de fora e diga o motivo. Peça com a arte e só o CTA é melhor do
  que peça com um pedaço de frase no topo.
- Tudo que você deixar de fora entra em `descartados`, com o motivo. Cortar
  conteúdo calado não é aceito.
- A marca sai de um recorte da arte: informe `origem` com o arquivo.
{('- Marcas disponíveis: ' + ', '.join(marcas)) if marcas else ''}

{_onde_cabe(livres)}
{('Material da peça, o único texto que pode aparecer: ' + material) if material else ''}
{('A arte já traz impresso, e não pode ser repetido: ' + '; '.join(f'"{t}"' for t in ja_escrito)) if ja_escrito else ''}
{('Ajustes pedidos: ' + brief) if brief else ''}

Responda só com JSON:
{{"elementos": [{{"papel": "...", "zona": "...", "texto": "..."}}],
  "descartados": {{"o que saiu": "por quê"}}}}"""


class CompositorModelo:
    """Pergunta a estrutura ao modelo e calcula as caixas aqui.

    O modelo entra de fora — `responder(instrucao, arte) -> dict`. Assim o
    compositor inteiro é testável com um modelo falso, e trocar de provedor não
    mexe em nada aqui.
    """

    def __init__(self, responder, fundo: dict, marcas: list[str] | None = None,
                 fontes: list | None = None, cor_texto: str = "#ffffff", acento: str = "",
                 tentativas: int = 2, material: str = ""):
        self.responder = responder
        self.material = material
        self.fundo = fundo
        self.marcas = marcas or []
        self.fontes = fontes
        self.cor_texto = cor_texto
        self.acento = acento
        self.tentativas = max(1, tentativas)

    def compor(self, base, formato_id: str, brief: str = "",
               terreno: "Terreno | None" = None) -> dict:
        from api.composicao import RespostaInvalida, conferir, montar
        f = formato_by_id(formato_id)
        if not f:
            raise ComposicaoImpossivel(f"formato desconhecido: {formato_id}")
        ja = terreno.ja_escrito if terreno else []
        livres = terreno.livres if terreno else None
        fundo = terreno.fundo if terreno else self.fundo
        material = " ".join(x for x in (self.material, brief, *ja) if x) or None
        tinta = terreno.tinta if terreno else None
        texto = instrucao(f, brief, self.marcas, ja, livres, material, tinta)
        ultimo = ""
        for tentativa in range(self.tentativas):
            try:
                bruto = self.responder(texto, base)
            except Exception as e:
                raise ComposicaoImpossivel(f"o modelo não respondeu: {e}") from e
            try:
                esq = conferir(bruto, f, ja, material)
            except RespostaInvalida as e:
                # resposta de modelo nunca vai direto para o render. Mas desistir
                # na primeira também é desperdício: dizer o erro e pedir de novo
                # é o que uma pessoa faria, e costuma resolver em uma volta.
                ultimo = str(e)
                texto = (f"{instrucao(f, brief, self.marcas, ja, livres, material, tinta)}\n\n"
                         f"A resposta anterior foi recusada: {ultimo}\n"
                         f"Corrija isso e responda de novo.")
                continue
            fontes = (terreno.fontes if terreno and terreno.fontes else self.fontes)
            return montar(esq, f, fundo, fontes, self.cor_texto, self.acento, livres,
                          terreno.tinta if terreno else None)
        raise ComposicaoImpossivel(
            f"o modelo não corrigiu em {self.tentativas} tentativas: {ultimo}")


class CompositorEmCadeia:
    """Tenta um, depois o outro. Serve para a política do
    `docs/DECISAO-quem-compoe.md`: regra onde ela dá conta, modelo onde precisa
    de julgamento — ou o contrário, que é escolha de quem monta a cadeia."""

    def __init__(self, *compositores):
        self.compositores = compositores

    def compor(self, base, formato_id: str, brief: str = "",
               terreno: "Terreno | None" = None) -> dict:
        motivos = []
        for c in self.compositores:
            try:
                peca = c.compor(base, formato_id, brief, terreno)
            except ComposicaoImpossivel as e:
                motivos.append(f"{type(c).__name__}: {e}")
                continue
            # quem compôs não foi o primeiro da fila: a peça sai, mas sai
            # dizendo por quê. Cair em silêncio para a regra foi o defeito que
            # entregou peça de régua com cara de peça do modelo.
            if motivos:
                peca["_desvios"] = list(motivos)
            return peca
        raise ComposicaoImpossivel(" | ".join(motivos) or "nenhum compositor configurado")
