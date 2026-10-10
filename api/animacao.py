"""A peça parada vira vídeo.

O layout não é tocado aqui: ele já foi decidido por formato lá atrás, com o
fundo preparado, o texto no lugar quieto e o CTA fechando na borda da arte. A
animação só diz **quando** e **como** cada coisa entra — é por isso que trocar
de preset não mexe em nenhuma caixa.

Quem desenha é o Remotion, que é Node. Esta camada é a ponte: leva os arquivos
que a peça usa para dentro do projeto de vídeo, escreve os props e chama o
render. Tudo por caminho relativo ao projeto, para o mesmo job renderizar em
qualquer máquina.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
VIDEO = RAIZ / "video"

PRESETS = ("editorial", "lettering", "energia", "seco")
PRESET_PADRAO = "editorial"
SEGUNDOS_PADRAO = 5.0

# cada formato vira um render do Chrome: 9 minutos cobre uma peça grande sem
# prender a fila a um travamento
ESPERA = int(os.environ.get("REPLICAI_VIDEO_ESPERA", 540))


class VideoImpossivel(RuntimeError):
    """O vídeo não saiu. Melhor dizer do que entregar outra coisa no lugar."""


def instalado() -> bool:
    """Há projeto de vídeo com dependências? Sem isto a plataforma segue
    entregando peça parada, em vez de recusar a subir."""
    return (VIDEO / "node_modules" / ".bin" / "remotion").exists()


def _levar(src: str, cantos: list[Path], destino: Path) -> str | None:
    """Copia um arquivo que a peça usa para dentro do projeto de vídeo.

    O `src` da peça é relativo à pasta do job; dentro do Remotion tudo tem que
    estar em `public/`, e referido pelo nome. Caminho absoluto aqui prenderia o
    vídeo à máquina que o renderizou.
    """
    p = Path(src)
    achado = p if (p.is_absolute() and p.exists()) else next(
        (c / src for c in cantos if (c / src).exists()), None)
    if achado is None:
        return None
    shutil.copy2(achado, destino / achado.name)
    return achado.name


def preparar(pasta: Path, formato: str, preset: str = PRESET_PADRAO,
             segundos: float = SEGUNDOS_PADRAO) -> tuple[Path, str]:
    """Monta `public/peca/<slug>/` e o props.json. Devolve (props, slug)."""
    pasta = Path(pasta)
    arq = pasta / "pecas" / f"{formato}.json"
    if not arq.exists():
        raise VideoImpossivel(f"não existe peça composta para `{formato}`")
    peca = json.loads(arq.read_text(encoding="utf-8"))
    canvas = peca.get("canvas")
    if not canvas:
        raise VideoImpossivel(f"a peça `{formato}` não diz o tamanho do canvas")

    slug = f"{pasta.name}-{formato}"
    destino = VIDEO / "public" / "peca" / slug
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    cantos = [pasta, pasta / "pecas"]

    fundo = dict(peca.get("fundo") or {})
    if fundo.get("src"):
        fundo["src"] = _levar(fundo["src"], cantos, destino) or ""

    elementos = []
    for e in peca.get("elementos", []):
        e = dict(e)
        if e.get("src"):
            nome = _levar(e["src"], cantos, destino)
            if not nome:
                continue          # imagem que não existe não vira quadro vazio
            e["src"] = nome
        elementos.append(e)

    fontes = []
    for f in peca.get("fontes", []):
        nome = _levar(f.get("arquivo", ""), cantos, destino)
        if nome:
            fontes.append({"familia": f["familia"], "arquivo": nome,
                           "peso": f.get("peso", 400)})

    props = {"base": f"peca/{slug}", "canvas": canvas, "fundo": fundo,
             "elementos": elementos, "fontes": fontes,
             "preset": preset if preset in PRESETS else PRESET_PADRAO,
             "segundos": float(segundos)}
    alvo = VIDEO / "props" / f"{slug}.json"
    alvo.parent.mkdir(exist_ok=True)
    alvo.write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
    return alvo, slug


def renderizar(props: Path, destino: Path, espera: int = ESPERA) -> Path:
    """Chama o Remotion. Uma aba só, sempre.

    Com mais de uma, cada aba mede a fonte por conta e o texto alterna de
    posição entre quadros. O tremor custou cinco hipóteses erradas até a
    medição mostrar 0,447px de diferença entre abas paralelas.
    """
    if not instalado():
        raise VideoImpossivel(
            "o projeto de vídeo não está instalado: rode `npm install` em video/")
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(VIDEO / "node_modules" / ".bin" / "remotion"), "render",
           "src/Root.tsx", "Peca", str(destino.resolve()),
           f"--props={props.resolve()}", "--concurrency=1", "--log=error"]
    try:
        r = subprocess.run(cmd, cwd=VIDEO, capture_output=True, text=True, timeout=espera)
    except subprocess.TimeoutExpired:
        raise VideoImpossivel(f"o render passou de {espera}s e foi interrompido") from None
    if r.returncode != 0 or not destino.exists():
        erro = (r.stderr or r.stdout or "").strip().splitlines()
        raise VideoImpossivel(f"o render falhou: {erro[-1] if erro else 'sem mensagem'}")
    return destino


def animar(pasta: Path, formatos: list[str], preset: str = PRESET_PADRAO,
           segundos: float = SEGUNDOS_PADRAO) -> tuple[dict, dict]:
    """Anima os formatos pedidos. Devolve (prontos, falhas).

    Um formato que falha não derruba os outros — mesma regra da esteira de
    peça parada: entregar quatro de seis com a lista do que faltou é melhor do
    que não entregar nada.
    """
    pasta = Path(pasta)
    prontos, falhas = {}, {}
    for fid in formatos:
        try:
            props, slug = preparar(pasta, fid, preset, segundos)
            saida = renderizar(props, pasta / "video" / f"{fid}-{preset}.mp4")
            prontos[fid] = saida
        except VideoImpossivel as e:
            falhas[fid] = str(e)
        except Exception as e:
            falhas[fid] = f"erro inesperado no vídeo: {e}"
    return prontos, falhas
