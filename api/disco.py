"""Quanto disco ainda há, e em quanto tempo acaba.

O disco é o único recurso que a plataforma gasta e não devolve. Medido nos
trabalhos reais: cada peça entregue ocupa 2,41 MB **para sempre**, e o material
bruto de cada trabalho — PSD e recortes de camada — ocupa de 15 MB a 420 MB
durante os 30 dias até a faxina passar. Processador e memória sobram: uma
carteira de dez clientes usa 2,5 horas de máquina no mês inteiro.

Disco cheio não degrada: **para**. A peça não grava, o trabalho morre no meio e
o cliente vê erro. E chega sem avisar, porque ninguém abre `/saude` todo dia.

Por isso aqui não há só a medida de hoje: há o histórico e a **previsão**. Saber
que o disco está em 72% não diz nada; saber que nesse ritmo ele enche em cinco
semanas é o que dá tempo de agir — aumentar o disco, ou baixar a retenção do
bruto de 30 para 15 dias.

O aviso sai por e-mail e **só quando a situação piora**. Aviso que chega todo
dia vira aviso que ninguém lê.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

# onde a folga deixa de ser folga. 70% porque, no ritmo medido, é a distância
# que ainda dá para resolver sem pressa; 85% porque abaixo disso já não cabe
# um trabalho com PSD pesado
ATENCAO = 0.70
APERTO = 0.85

NIVEIS = ("folga", "atenção", "aperto")
GUARDA_DIAS = 90          # histórico suficiente para ver tendência de um mês


def _arquivo() -> Path:
    from api.trabalhos import pasta_base
    return pasta_base() / "_disco.json"


def medir(caminho: Path | None = None) -> dict:
    """O espaço do disco onde os trabalhos moram."""
    from api.trabalhos import pasta_base
    alvo = Path(caminho) if caminho else pasta_base()
    alvo.mkdir(parents=True, exist_ok=True)
    total, usado, livre = shutil.disk_usage(alvo)
    return {"quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "total_gb": round(total / 1e9, 2),
            "usado_gb": round(usado / 1e9, 2),
            "livre_gb": round(livre / 1e9, 2),
            "cheio": round(usado / total, 4) if total else 0.0}


def nivel(cheio: float) -> str:
    if cheio >= APERTO:
        return "aperto"
    if cheio >= ATENCAO:
        return "atenção"
    return "folga"


def _historico() -> list[dict]:
    f = _arquivo()
    if not f.exists():
        return []
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return d.get("medidas") or [] if isinstance(d, dict) else []


def _gravar(medidas: list[dict], avisado: str) -> None:
    _arquivo().write_text(
        json.dumps({"medidas": medidas[-GUARDA_DIAS:], "avisado": avisado},
                   ensure_ascii=False, indent=1), encoding="utf-8")


def _avisado() -> str:
    f = _arquivo()
    if not f.exists():
        return "folga"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return d.get("avisado") or "folga"
    except (json.JSONDecodeError, OSError):
        return "folga"


def registrar(medida: dict) -> list[dict]:
    """Guarda a medida do dia. Uma por dia: a faxina pode rodar duas vezes."""
    medidas = [m for m in _historico() if m.get("quando", "")[:10] != medida["quando"][:10]]
    medidas.append(medida)
    medidas.sort(key=lambda m: m.get("quando", ""))
    _gravar(medidas, _avisado())
    return medidas


def previsao(medidas: list[dict]) -> dict:
    """Em quantos dias o disco enche, no ritmo dos últimos dias.

    Duas medidas bastam para uma reta, e reta é o que se consegue honestamente:
    o crescimento é a soma de peças entregues (constante por cliente) com bruto
    em trânsito (que oscila). Por isso o número sai como "cerca de", e some
    quando o disco não está crescendo.
    """
    uteis = [m for m in medidas if m.get("total_gb")]
    if len(uteis) < 2:
        return {"sabe": False, "porque": "ainda não há histórico suficiente"}
    primeiro, ultimo = uteis[0], uteis[-1]
    try:
        d0 = date.fromisoformat(primeiro["quando"][:10])
        d1 = date.fromisoformat(ultimo["quando"][:10])
    except ValueError:
        return {"sabe": False, "porque": "histórico com data torta"}
    dias = (d1 - d0).days
    if dias < 1:
        return {"sabe": False, "porque": "ainda não há histórico suficiente"}
    cresceu = ultimo["usado_gb"] - primeiro["usado_gb"]
    por_dia = cresceu / dias
    if por_dia <= 0:
        return {"sabe": True, "por_dia_gb": round(por_dia, 3), "enche_em_dias": None,
                "porque": "o disco não está crescendo"}
    return {"sabe": True, "por_dia_gb": round(por_dia, 3),
            "enche_em_dias": int(ultimo["livre_gb"] / por_dia),
            "medido_em_dias": dias}


def conferir(enviar: bool = True, caminho: Path | None = None) -> dict:
    """Mede, guarda, e avisa quando piora. Chamado pela faxina, todo dia."""
    medida = medir(caminho)
    medidas = registrar(medida)
    agora = nivel(medida["cheio"])
    antes = _avisado()
    prev = previsao(medidas)
    relatorio = {**medida, "nivel": agora, "antes": antes, "previsao": prev}

    # só sobe de nível avisa. Melhorou (a faxina liberou espaço) também se
    # registra, para o próximo aperto voltar a avisar
    piorou = NIVEIS.index(agora) > NIVEIS.index(antes)
    if agora != antes:
        _gravar(medidas, agora)
    if not piorou:
        relatorio["carta"] = {"enviado": False, "porque": "nada piorou"}
        return relatorio
    if not enviar:
        relatorio["carta"] = {"enviado": False, "porque": "envio desligado"}
        return relatorio

    from api import correio
    relatorio["carta"] = correio.disco_apertando(medida, agora, prev)
    return relatorio


def para_quem() -> str:
    """Quem recebe o aviso. É de operação, não de cliente."""
    return os.environ.get("REPLICAI_AVISO_PARA", "").strip()
