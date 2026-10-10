"""A esteira de um job: arte aprovada entra, peças saem.

Não depende de quem compõe. O compositor é recebido de fora, então esta esteira
já vale para os três caminhos em aberto no `docs/DECISAO-quem-compoe.md`.

Um formato que falha não derruba os outros: o job entrega o que deu e diz o que
não deu. Entregar seis de oito peças com a lista do que faltou é melhor do que
não entregar nada, e muito melhor do que entregar oito com duas erradas.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from api.compositor import ComposicaoImpossivel, Compositor
from api.qualidade import conferir_fundo, recorte_e_retangulo
from motor.replica import render_peca


@dataclass
class Resultado:
    pasta: Path
    prontas: dict[str, Path] = field(default_factory=dict)
    falhas: dict[str, str] = field(default_factory=dict)
    avisos: dict[str, list[str]] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.prontas and not self.falhas:
            return "pronto"
        if self.prontas:
            return "parcial"
        return "erro"

    def para_json(self) -> dict:
        return {
            "status": self.status,
            "prontas": {k: str(v) for k, v in self.prontas.items()},
            "falhas": self.falhas,
            "avisos": self.avisos,
        }


def conferir_peca(peca: dict, pasta: Path, arte: Path) -> list[str]:
    """As regras de qualidade que esta sessão descobriu, aplicadas a cada peça.

    Escrever a verificação e não chamá-la foi o erro que deixou o lettering
    fantasma passar: a regra existia em `api/qualidade.py` e ninguém a usava.
    Por isso ela roda aqui, na esteira, e não à parte.

    Devolve avisos, não erros. A peça é entregue com a ressalva em vez de ser
    barrada: quem decide se o fundo está bom o bastante é quem vai publicar.
    """
    avisos = []
    fundo = (peca.get("fundo") or {}).get("src")
    if fundo:
        caminho = pasta / fundo if not Path(fundo).is_absolute() else Path(fundo)
        if caminho.exists() and caminho.resolve() != Path(arte).resolve():
            try:
                ok, msg = conferir_fundo(arte, caminho)
                if not ok:
                    avisos.append(msg)
            except Exception:
                pass                      # conferência não pode derrubar entrega

    for e in peca.get("elementos", []):
        if e.get("tipo") != "imagem" or (e.get("papel") or "") not in ("marca", "logo", "selo"):
            continue
        src = e.get("src")
        if not src:
            continue
        caminho = pasta / src if not Path(src).is_absolute() else Path(src)
        if not caminho.exists():
            continue
        try:
            if recorte_e_retangulo(caminho):
                avisos.append(
                    f"a marca `{e.get('papel')}` é um bloco opaco: vai aparecer com moldura "
                    f"em volta, porque o fundo que veio no recorte não bate com o da peça. "
                    f"Recorte com transparência")
        except Exception:
            pass
    return avisos


def desdobrar(base: Path, formatos: list[str], compositor: Compositor,
              pasta: Path, brief: str = "") -> Resultado:
    """Compõe e renderiza cada formato pedido dentro de `pasta`."""
    base = Path(base)
    pasta = Path(pasta)
    (pasta / "pecas").mkdir(parents=True, exist_ok=True)

    # a arte vira `base.<ext>` na raiz do job: o motor resolve o `src` da peça
    # olhando a pasta dela e a pasta acima, então o caminho na peça é relativo
    # e o job inteiro pode ser movido de máquina sem quebrar
    copia = pasta / f"base{base.suffix.lower()}"
    if base.resolve() != copia.resolve():
        shutil.copy2(base, copia)

    r = Resultado(pasta=pasta)
    for fid in formatos:
        try:
            peca = compositor.compor(Path(copia.name), fid, brief)
        except ComposicaoImpossivel as e:
            r.falhas[fid] = str(e)
            continue

        for a in conferir_peca(peca, pasta, copia):
            r.avisos.setdefault(fid, []).append(a)

        arq = pasta / "pecas" / f"{fid}.json"
        arq.write_text(json.dumps(peca, ensure_ascii=False, indent=1), encoding="utf-8")
        destino = pasta / (peca.get("saida") or f"{fid}.png")
        try:
            render_peca(arq, destino)
        except Exception as e:
            # o motor levanta RuntimeError quando o Chrome não gera o PNG; vale
            # guardar o texto, que costuma trazer o erro do próprio navegador
            r.falhas[fid] = f"não renderizou: {e}"
            continue
        r.prontas[fid] = destino

    (pasta / "resultado.json").write_text(
        json.dumps(r.para_json(), ensure_ascii=False, indent=1), encoding="utf-8")
    return r
