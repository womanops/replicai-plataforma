"""Apaga o material bruto de trabalhos antigos.

Medido nos planos: uma carteira de quarenta clientes gera 94 GB de disco novo
por mês. Quase tudo é material de trabalho — o PSD, os recortes de camada, os
fundos preparados. A peça entregue, que é o que alguém vai querer de volta
daqui a seis meses, são 3,5 MB.

Sem faxina nenhum disco serve: 640 GB enchem em quatro meses. Com ela, o
acúmulo permanente cai para 8 GB por mês.

O que fica é decidido pelo estado do trabalho, não por lista de extensões: as
peças que ele diz ter entregue, os vídeos, o PDF de apresentação e os JSONs
que descrevem a montagem. O resto do que está na pasta é bruto.

O trabalho varrido continua existindo e continua baixável. O que ele perde é
a possibilidade de **refazer**: sem a arte não há como reexportar nem
remontar à mão. Por isso ele é marcado, e a tela para de oferecer o que não
funciona mais — em vez de oferecer e falhar.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api import trabalhos

# depois de quantos dias o bruto vai embora. Trinta porque é o ciclo de
# faturamento: dentro do mês em que pagou, a pessoa ainda pode refazer.
DIAS = int(os.environ.get("REPLICAI_FAXINA_DIAS", "30"))

# estados em que o trabalho ainda pode estar mexendo nos próprios arquivos
EM_ANDAMENTO = {"na fila", "rodando", "escolha a prancheta"}


def _guardar(estado: dict) -> set[str]:
    """Os caminhos, relativos à pasta do trabalho, que não se apaga."""
    fica = {"trabalho.json", "resultado.json", "apresentacao.pdf"}
    for fid in estado.get("prontas") or []:
        fica.add(f"{fid}.png")
    return fica


def _quando(estado: dict) -> datetime | None:
    bruto = estado.get("atualizado")
    if not bruto:
        return None
    try:
        return datetime.fromisoformat(bruto)
    except ValueError:
        return None


def varrer_trabalho(conta: str, job: str, agora: datetime | None = None,
                    dias: int = DIAS, de_verdade: bool = True) -> dict:
    """Apaga o bruto de um trabalho. Devolve o que achou e o que liberou."""
    estado = trabalhos.ler(conta, job)
    if estado is None:
        return {"job": job, "pulou": "não existe"}
    if estado.get("status") in EM_ANDAMENTO:
        return {"job": job, "pulou": "ainda está rodando"}
    if estado.get("arquivado"):
        return {"job": job, "pulou": "já foi varrido"}

    quando = _quando(estado)
    agora = agora or datetime.now(timezone.utc)
    if quando is None:
        return {"job": job, "pulou": "sem data"}
    idade = (agora - quando).days
    if idade < dias:
        return {"job": job, "pulou": f"tem {idade} dias, ainda não"}

    pasta = trabalhos.pasta_do(conta, job)
    if not pasta.exists():
        return {"job": job, "pulou": "pasta sumiu"}
    fica = _guardar(estado)

    # `arte.psd` e `base.psd` apontam para o mesmo arquivo em disco: apagar um
    # não libera nada. O tamanho é contado uma vez por inode, e os dois nomes
    # caem na mesma varredura — por isso a conta aqui bate com a do disco.
    vistos: set[tuple[int, int]] = set()
    liberado, apagados = 0, []
    for alvo in sorted(pasta.rglob("*")):
        if not alvo.is_file():
            continue
        rel = str(alvo.relative_to(pasta))
        if rel in fica or rel.startswith("pecas/") or rel.startswith("video/"):
            continue
        st = alvo.stat()
        chave = (st.st_dev, st.st_ino)
        if chave not in vistos:
            vistos.add(chave)
            liberado += st.st_size
        apagados.append(rel)
        if de_verdade:
            alvo.unlink(missing_ok=True)

    if de_verdade and apagados:
        trabalhos.gravar(conta, job, {"arquivado": {
            "quando": agora.isoformat(timespec="seconds"),
            "liberou_mb": round(liberado / 1e6, 1),
            "porque": f"material bruto de mais de {dias} dias",
        }})
    return {"job": job, "idade": idade, "apagados": len(apagados),
            # em bytes também: arredondado para MB, contar a ligação uma ou
            # duas vezes dá o mesmo número, e o teste deixaria passar o erro
            "liberou": liberado, "liberou_mb": round(liberado / 1e6, 1),
            "arquivos": apagados}


def varrer(dias: int = DIAS, de_verdade: bool = True,
           agora: datetime | None = None) -> dict:
    """Varre todas as contas. Devolve o resumo para o registro do servidor."""
    from api import contas
    base = trabalhos.pasta_base()
    feitos, liberado, pulados = [], 0.0, 0
    for c in contas.todas():
        pasta = base / c.id
        if not pasta.exists():
            continue
        for alvo in sorted(pasta.glob("*/trabalho.json")):
            r = varrer_trabalho(c.id, alvo.parent.name, agora, dias, de_verdade)
            if r.get("pulou"):
                pulados += 1
                continue
            feitos.append(r)
            liberado += r.get("liberou_mb", 0)
    return {"varridos": len(feitos), "pulados": pulados,
            "liberou_mb": round(liberado, 1), "dias": dias,
            "de_verdade": de_verdade}


def main(argv: list[str]) -> int:
    """`python -m api.faxina [--de-mentira] [--dias N]`

    De mentira primeiro, sempre que mudar alguma coisa: o resumo diz quanto
    sairia sem tirar nada.
    """
    from api import ambiente
    ambiente.carregar()
    dias = DIAS
    de_verdade = "--de-mentira" not in argv
    if "--dias" in argv:
        dias = int(argv[argv.index("--dias") + 1])
    r = varrer(dias=dias, de_verdade=de_verdade)
    como = "apagou" if de_verdade else "apagaria"
    print(f"faxina: {como} o bruto de {r['varridos']} trabalhos com mais de "
          f"{dias} dias, liberando {r['liberou_mb']} MB "
          f"({r['pulados']} fora da conta)")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
