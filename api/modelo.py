"""O modelo que compõe, atrás de uma função.

`CompositorModelo` recebe um `responder(instrucao, arte) -> dict` de fora. Isto
aqui é a implementação que fala com a API da Anthropic; trocar de provedor é
trocar este arquivo, e nada mais.

A saída é forçada por esquema (`output_config.format`): o modelo não tem como
devolver prosa, markdown ou JSON quebrado. Ainda assim a resposta passa pela
conferência de `api/composicao.py` antes de virar peça — esquema garante forma,
não garante que a composição faça sentido.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from api import custo

MODELO = "claude-opus-5-5"

TIPOS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp", ".gif": "image/gif"}

# `descartados` vai como lista, e não como objeto de chaves livres: esquema
# estrito não aceita chave arbitrária. A conversão para o formato que a
# conferência espera acontece aqui, não no prompt.
ESQUEMA = {
    "type": "object",
    "properties": {
        "elementos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "papel": {"type": "string"},
                    "zona": {"type": "string"},
                    "texto": {"type": "string"},
                    "origem": {"type": "string"},
                },
                "required": ["papel", "zona", "texto", "origem"],
                "additionalProperties": False,
            },
        },
        "descartados": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"o_que": {"type": "string"}, "por_que": {"type": "string"}},
                "required": ["o_que", "por_que"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["elementos", "descartados"],
    "additionalProperties": False,
}


def _imagem(caminho: Path) -> dict | None:
    """A arte vai junto quando é imagem que o modelo abre. PSD e PDF não são
    legíveis por ele; nesses casos a composição vai só pelo brief, que é pior
    mas honesto — melhor do que mandar bytes que ele não entende."""
    p = Path(caminho)
    tipo = TIPOS.get(p.suffix.lower())
    if not tipo or not p.exists():
        return None
    return {"type": "image",
            "source": {"type": "base64", "media_type": tipo,
                       "data": base64.standard_b64encode(p.read_bytes()).decode()}}


def responder_anthropic(instrucao: str, arte, cliente=None, modelo: str = MODELO) -> dict:
    """Manda a instrução e a arte; devolve a resposta já no formato da conferência."""
    import anthropic

    cliente = cliente or anthropic.Anthropic()
    conteudo = []
    img = _imagem(arte)
    if img:
        conteudo.append(img)
    conteudo.append({"type": "text", "text": instrucao})

    r = cliente.messages.create(
        model=modelo,
        max_tokens=16000,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": ESQUEMA}},
        messages=[{"role": "user", "content": conteudo}],
    )
    # antes da recusa: recusa também é cobrada
    custo.registrar(modelo, getattr(r, "usage", None))

    # o modelo pode recusar: nesse caso não há texto para ler
    if getattr(r, "stop_reason", None) == "refusal":
        det = getattr(r, "stop_details", None)
        raise RuntimeError(f"o modelo recusou a composição ({getattr(det, 'category', 'sem categoria')})")

    texto = next((b.text for b in r.content if b.type == "text"), "")
    bruto = json.loads(texto)
    return {
        "elementos": bruto.get("elementos") or [],
        "descartados": {d["o_que"]: d["por_que"] for d in (bruto.get("descartados") or [])},
    }


def ler_arte(arte, cliente=None, modelo: str = MODELO) -> dict:
    """Uma chamada por trabalho: onde está a tinta da arte e o que ela diz.

    Esquema próprio, prompt próprio. Sem a arte anexada não há o que ler — e
    PSD/PDF o modelo não abre, então devolve leitura vazia em vez de inventar.
    """
    import anthropic

    from api.leitura import ESQUEMA as ESQ_LEITURA, INSTRUCAO

    img = _imagem(arte)
    if not img:
        return {}
    cliente = cliente or anthropic.Anthropic()
    r = cliente.messages.create(
        model=modelo,
        max_tokens=4000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": ESQ_LEITURA}},
        messages=[{"role": "user", "content": [img, {"type": "text", "text": INSTRUCAO}]}],
    )
    custo.registrar(modelo, getattr(r, "usage", None))
    if getattr(r, "stop_reason", None) == "refusal":
        return {}
    return json.loads(next((b.text for b in r.content if b.type == "text"), "{}"))


def disponivel() -> bool:
    """Há credencial para falar com o modelo? Sem ela a plataforma cai para a
    regra determinística em vez de recusar a subir."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True
