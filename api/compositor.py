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
from typing import Protocol

from motor.replica import formato_by_id


class Compositor(Protocol):
    """Recebe a arte aprovada e um formato; devolve a peça pronta para render."""

    def compor(self, base: Path, formato_id: str, brief: str = "") -> dict:
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

    def compor(self, base: Path, formato_id: str, brief: str = "") -> dict:
        arq = self.pasta / f"{formato_id}.json"
        if not arq.exists():
            raise ComposicaoImpossivel(
                f"não existe peça pronta para `{formato_id}` em {self.pasta}")
        return json.loads(arq.read_text(encoding="utf-8"))


# ----------------------------------------------------------------- regra simples

class CompositorSimples:
    """Regra determinística: a arte vira fundo, o texto entra na área segura.

    Serve o caso fácil — uma chamada, um CTA, sem recorte nem camada. Custa zero
    por peça e responde em milissegundos. Não tenta nada além disso: peça com
    mascote recortado e lettering ilustrado levanta `ComposicaoImpossivel` em vez
    de entregar algo torto.
    """

    def __init__(self, headline: str, cta: str = "", cor_texto: str = "#ffffff",
                 fonte: str = "DejaVu Sans"):
        self.headline = headline.strip()
        self.cta = cta.strip()
        self.cor_texto = cor_texto
        self.fonte = fonte

    def compor(self, base: Path, formato_id: str, brief: str = "") -> dict:
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

        elementos = [{
            "tipo": "texto", "papel": "headline", "texto": self.headline,
            "box": {"x": x, "y": s["top"] + round(alt_util * 0.30),
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
                "box": {"x": x, "y": H - s["bottom"] - round(alt_util * 0.20),
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
            "fundo": {"tipo": "imagem", "src": Path(base).name, "fit": "cover"},
            "fontes": [],
            "elementos": elementos,
        }


# ----------------------------------------------------------------- modelo + regra

def instrucao(formato: dict, brief: str = "", marcas: list[str] | None = None) -> str:
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
Convenção: {formato.get('notas', '—')}

Regras:
- Um papel só aparece uma vez.
- Headline é obrigatória.
- Texto que não cabe no limite deve ser encurtado por você, não truncado depois.
- Tudo que você deixar de fora entra em `descartados`, com o motivo. Cortar
  conteúdo calado não é aceito.
- A marca sai de um recorte da arte: informe `origem` com o arquivo.
{('- Marcas disponíveis: ' + ', '.join(marcas)) if marcas else ''}
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
                 tentativas: int = 2):
        self.responder = responder
        self.fundo = fundo
        self.marcas = marcas or []
        self.fontes = fontes
        self.cor_texto = cor_texto
        self.acento = acento
        self.tentativas = max(1, tentativas)

    def compor(self, base, formato_id: str, brief: str = "") -> dict:
        from api.composicao import RespostaInvalida, conferir, montar
        f = formato_by_id(formato_id)
        if not f:
            raise ComposicaoImpossivel(f"formato desconhecido: {formato_id}")
        texto = instrucao(f, brief, self.marcas)
        ultimo = ""
        for tentativa in range(self.tentativas):
            try:
                bruto = self.responder(texto, base)
            except Exception as e:
                raise ComposicaoImpossivel(f"o modelo não respondeu: {e}") from e
            try:
                esq = conferir(bruto, f)
            except RespostaInvalida as e:
                # resposta de modelo nunca vai direto para o render. Mas desistir
                # na primeira também é desperdício: dizer o erro e pedir de novo
                # é o que uma pessoa faria, e costuma resolver em uma volta.
                ultimo = str(e)
                texto = (f"{instrucao(f, brief, self.marcas)}\n\n"
                         f"A resposta anterior foi recusada: {ultimo}\n"
                         f"Corrija isso e responda de novo.")
                continue
            return montar(esq, f, self.fundo, self.fontes, self.cor_texto, self.acento)
        raise ComposicaoImpossivel(
            f"o modelo não corrigiu em {self.tentativas} tentativas: {ultimo}")


class CompositorEmCadeia:
    """Tenta um, depois o outro. Serve para a política do
    `docs/DECISAO-quem-compoe.md`: regra onde ela dá conta, modelo onde precisa
    de julgamento — ou o contrário, que é escolha de quem monta a cadeia."""

    def __init__(self, *compositores):
        self.compositores = compositores

    def compor(self, base, formato_id: str, brief: str = "") -> dict:
        motivos = []
        for c in self.compositores:
            try:
                peca = c.compor(base, formato_id, brief)
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
