#!/usr/bin/env python3
"""Prova que o contêiner renderiza uma peça.

Este é o teste que decide a arquitetura. Se o Chromium desenhar a peça aqui
dentro, está provado que o ReplicAI roda em qualquer servidor — e aí vale
construir API, fila e cobrança em cima. Se não desenhar, tudo acima muda.

    docker compose -f infra/docker-compose.yml run --rm api python testes/prova_container.py
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from motor import replica  # noqa: E402


def main() -> int:
    versoes = Path("/app-versoes.json")
    if versoes.exists():
        print(f"0. desenhando com: {versoes.read_text().strip()}")

    print("1. o motor acha um navegador?")
    chrome = replica.find_chrome()
    if not chrome:
        print("   NÃO. Sem navegador na imagem, nada renderiza.")
        return 1
    print(f"   sim: {chrome}")

    import os
    como_root = hasattr(os, "geteuid") and os.geteuid() == 0
    onde = "contêiner" if como_root else "máquina local"
    print(f"2. rodando na {onde} · bandeiras: {os.environ.get('CHROME_FLAGS') or '(nenhuma)'}")
    if como_root and "--no-sandbox" not in os.environ.get("CHROME_FLAGS", ""):
        print("   aviso: como root e sem --no-sandbox, o Chromium não vai abrir")

    peca = RAIZ / "testes" / "peca-prova.json"
    saida = RAIZ / "testes" / "saida" / "prova.png"
    saida.parent.mkdir(parents=True, exist_ok=True)
    print("3. renderizando a peça de prova…")
    try:
        rep = replica.render_peca(peca, saida)
    except Exception as e:
        print(f"   FALHOU: {e}")
        return 2

    if not saida.exists():
        print("   FALHOU: o PNG não foi criado.")
        return 3

    from PIL import Image
    im = Image.open(saida)
    cores = im.convert("RGB").getcolors(maxcolors=1_000_000) or []
    print(f"   PNG criado: {im.width}x{im.height}, {saida.stat().st_size // 1024} KB, {len(cores)} cores")

    # Uma peça só com fundo chapado significa que o texto não desenhou — o que
    # normalmente quer dizer que falta fonte na imagem. Vale reprovar: entregar
    # peça sem tipografia é pior do que falhar.
    if len(cores) < 5:
        print("   FALHOU: a peça saiu lisa. O texto não desenhou (fonte ausente?).")
        return 4

    txt = [e for e in rep.get("elementos", []) if e.get("classe") == "txt"]
    print(f"4. texto medido pelo navegador: {len(txt)} bloco(s)")
    for e in txt:
        print(f"   {e.get('papel')}: corpo {e.get('size')}px, tinta {e.get('tinta') or '—'}")
    if not txt:
        print("   FALHOU: o navegador não reportou nenhum texto.")
        return 5

    # A MESMA peça, de novo. Travar a medida do texto numa amostra só é
    # escolher um número no escuro: se ele oscila sozinho, a trava passa a
    # reprovar trabalho bom; se a folga for grande "por garantia", ela deixa
    # passar justamente a mudança de navegador que deveria pegar. Duas
    # medidas na mesma máquina dizem se a régua é firme.
    print("5. medindo de novo, para saber se a régua repete…")
    de_novo = replica.render_peca(peca, saida.with_name("prova-2.png"))
    txt2 = [e for e in de_novo.get("elementos", []) if e.get("classe") == "txt"]
    iguais = True
    for a, b in zip(txt, txt2):
        bate = a.get("size") == b.get("size") and a.get("tinta") == b.get("tinta")
        iguais = iguais and bate
        print(f"   {a.get('papel')}: corpo {b.get('size')}px, tinta {b.get('tinta') or '—'}"
              f" · {'igual' if bate else 'DIFERENTE da primeira'}")
    print(f"   régua {'firme: as duas medidas batem' if iguais else 'OSCILOU entre duas medidas'}")

    print(f"\nPASSOU na {onde}. A peça está em {saida.relative_to(RAIZ)}")
    if como_root:
        print("O ReplicAI renderiza dentro do contêiner: roda em qualquer servidor.")
        print("Pode seguir para a Fase 1.")
    else:
        print("Isto prova o teste, não a portabilidade — rode de novo dentro do contêiner.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
