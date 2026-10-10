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
            "fundo": {"tipo": "imagem", "src": str(base), "fit": "cover"},
            "fontes": [],
            "elementos": elementos,
        }
