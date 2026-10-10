"""O que já está escrito na arte-mãe, e onde.

A plataforma compunha texto novo por cima do texto que já existia na peça: o
fundo é a arte crua, e a arte crua tem lettering, marca e assinatura dentro.
Para não escrever em cima é preciso saber onde a tinta está — e detectar isso
por pixel não funciona nesta família de arte: o reflexo das gotas de vidro é
tão branco quanto o lettering, e a caixa dá a imagem inteira.

Quem sabe diferenciar lettering de reflexo é o modelo, que já está olhando a
arte. Então a leitura é uma chamada por trabalho — não por formato — e o
resultado serve para as duas coisas que faltavam: proteger essa região do
corte, e não repetir texto que a peça já carrega.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ESQUEMA = {
    "type": "object",
    "properties": {
        "tem_texto": {"type": "boolean"},
        "caixa": {
            "type": "object",
            "properties": {
                "x": {"type": "number"}, "y": {"type": "number"},
                "w": {"type": "number"}, "h": {"type": "number"},
            },
            "required": ["x", "y", "w", "h"],
            "additionalProperties": False,
        },
        "textos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"papel": {"type": "string"}, "texto": {"type": "string"}},
                "required": ["papel", "texto"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["tem_texto", "caixa", "textos"],
    "additionalProperties": False,
}

INSTRUCAO = """Esta é uma peça gráfica pronta. Vou reenquadrá-la para outros formatos, e
preciso saber onde a arte já tem tinta de comunicação, para não escrever por cima.

Responda duas coisas.

1. `caixa`: um retângulo que contém TUDO que é texto, logotipo, assinatura, selo ou
   lettering na peça — em fração da imagem, onde x e y são o canto superior esquerdo e
   w e h são largura e altura (0 a 1). Um retângulo só, envolvendo todos eles juntos.
   Seja generoso nas bordas: é melhor proteger um pouco a mais do que cortar uma letra.
   NÃO inclua elementos que são imagem e não comunicação — reflexo, brilho, gota,
   produto, textura, grade de fundo. Se não houver texto nenhum, `tem_texto` falso e a
   caixa com zeros.

2. `textos`: o que está escrito ali, linha por linha, com o papel de cada um
   (marca, headline, apoio, cta, selo). Transcreva o que está na imagem, exatamente,
   sem inventar e sem completar o que não dá para ler."""


@dataclass
class Leitura:
    tem_texto: bool = False
    caixa: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    textos: list[dict] = field(default_factory=list)

    def em_pixels(self, w: int, h: int) -> tuple[int, int, int, int] | None:
        """A caixa em pixels da arte, já aparada ao quadro."""
        if not self.tem_texto:
            return None
        x, y, cw, ch = self.caixa
        x0, y0 = max(0, round(x * w)), max(0, round(y * h))
        x1, y1 = min(w, round((x + cw) * w)), min(h, round((y + ch) * h))
        if x1 <= x0 or y1 <= y0:
            return None
        return (x0, y0, x1, y1)

    @property
    def frases(self) -> list[str]:
        return [t["texto"] for t in self.textos if t.get("texto")]


def entender(bruto: dict) -> Leitura:
    """Lê a resposta do modelo. Caixa fora de 0..1 ou invertida não vira exceção:
    vira caixa vazia, e a peça segue sem proteção em vez de não sair."""
    if not isinstance(bruto, dict):
        return Leitura()
    c = bruto.get("caixa") or {}
    try:
        x, y, w, h = (float(c.get(k, 0)) for k in ("x", "y", "w", "h"))
    except (TypeError, ValueError):
        return Leitura()
    if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
        return Leitura()
    textos = [{"papel": str(t.get("papel", "")).strip().lower(),
               "texto": str(t.get("texto", "")).strip()}
              for t in (bruto.get("textos") or []) if isinstance(t, dict)]
    return Leitura(bool(bruto.get("tem_texto")), (x, y, w, h),
                   [t for t in textos if t["texto"]])
