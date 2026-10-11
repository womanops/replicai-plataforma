"""A API da plataforma.

Caminho mínimo que já tem valor: sobe a arte, escolhe formatos, baixa as peças.

A API não renderiza. Ela recebe, guarda, enfileira e responde — porque
renderizar leva minutos e requisição não espera. Quem trabalha é o worker.
"""
from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from api import ambiente, trabalhos
from api.tarefas import processar, processar_video
from api.fila import FILA_VIDEO, fila_do_ambiente
from motor.replica import formato_by_id, load_formatos

ambiente.carregar()          # antes de qualquer coisa ler os.environ

app = FastAPI(title="ReplicAI", version="0.1.0")
WEB = Path(__file__).resolve().parent.parent / "web"
FILA = fila_do_ambiente()

ACEITOS = {".png", ".jpg", ".jpeg", ".webp", ".psd", ".psb", ".pdf"}


@app.get("/", response_class=HTMLResponse)
def tela():
    pagina = WEB / "index.html"
    if not pagina.exists():
        raise HTTPException(404, "a interface não foi instalada nesta imagem")
    return pagina.read_text(encoding="utf-8")


VERSOES = Path("/app-versoes.json")


def desenhando_com() -> dict:
    """Com que Chromium e que fontes esta instância desenha.

    Vale expor: o motor mede o texto perguntando ao navegador, então duas
    máquinas com Chromium diferente entregam peças com tipografia diferente —
    sem erro nenhum para avisar. Aqui a diferença aparece.
    """
    if VERSOES.exists():
        try:
            return json.loads(VERSOES.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    from motor.replica import find_chrome
    return {"chromium": "fora de contêiner", "navegador": find_chrome() or "nenhum"}


@app.get("/saude")
def saude():
    from api import modelo
    return {"ok": True, "fila": type(FILA).__name__,
            "fila_porque": getattr(FILA, "porque", ""),
            "compositor": "modelo+regra" if modelo.disponivel() else "regra",
            "desenhando_com": desenhando_com()}


@app.get("/presets")
def presets():
    from api import animacao
    return {"presets": list(animacao.PRESETS), "padrao": animacao.PRESET_PADRAO,
            "disponivel": animacao.instalado()}


@app.get("/formatos")
def formatos():
    return load_formatos()["formatos"]


@app.post("/jobs", status_code=202)
async def criar(
    arte: UploadFile = File(...),
    formatos: str = Form(..., description="ids separados por vírgula"),
    headline: str = Form(...),
    cta: str = Form(""),
    titulo: str = Form(""),
    brief: str = Form(""),
    prancheta: str = Form(""),
):
    ext = Path(arte.filename or "").suffix.lower()
    if ext not in ACEITOS:
        raise HTTPException(415, f"não trabalho com `{ext or 'arquivo sem extensão'}`. "
                                 f"Mande {', '.join(sorted(ACEITOS))}")
    pedidos = [f.strip() for f in formatos.split(",") if f.strip()]
    if not pedidos:
        raise HTTPException(422, "escolha ao menos um formato")
    desconhecidos = [f for f in pedidos if not formato_by_id(f)]
    if desconhecidos:
        raise HTTPException(422, f"formato desconhecido: {', '.join(desconhecidos)}. "
                                 f"Veja /formatos")

    job = trabalhos.novo_id(titulo or Path(arte.filename or "peca").stem)
    pasta = trabalhos.pasta_do(job)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"arte{ext}"
    with destino.open("wb") as f:
        shutil.copyfileobj(arte.file, f)

    comum = {"formatos": pedidos, "titulo": titulo, "arte": destino.name,
             "headline": headline, "cta": cta, "brief": brief}

    # PSD com várias pranchetas é vários trabalhos num arquivo só. Escolher a
    # maior ou a primeira pega a errada e fica calado: no Key Visual real as
    # seis têm a mesma proporção e só a quarta era a arte em uso.
    if ext in {".psd", ".psb"}:
        from api import psd
        try:
            achadas = psd.pranchetas(destino)
        except Exception as e:
            raise HTTPException(422, f"não consegui abrir o PSD: {e}")
        if len(achadas) > 1 and not prancheta:
            lista = [{"nome": p.nome, "w": p.w, "h": p.h} for p in achadas]
            trabalhos.gravar(job, {**comum, "status": "escolha a prancheta",
                                   "pranchetas": lista})
            return {"job": job, "status": "escolha a prancheta", "pranchetas": lista,
                    "como": f"POST /jobs/{job}/prancheta com o nome"}
        if prancheta and prancheta not in {p.nome for p in achadas}:
            raise HTTPException(422, f"não existe prancheta `{prancheta}` nesse arquivo. "
                                     f"Tem: {', '.join(p.nome for p in achadas)}")

    trabalhos.gravar(job, {**comum, "status": "na fila", "prancheta": prancheta})
    FILA.enfileirar(processar, job, str(destino), pedidos, headline, cta, brief, prancheta)
    return {"job": job, "status": trabalhos.ler(job)["status"]}


@app.post("/jobs/{job}/prancheta", status_code=202)
def escolher_prancheta(job: str, nome: str = Form(...)):
    """Escolhe a prancheta de um PSD e põe o trabalho na fila."""
    try:
        estado = trabalhos.ler(job)
    except ValueError:
        raise HTTPException(400, "identificador inválido")
    if estado is None:
        raise HTTPException(404, "trabalho não existe")
    nomes = {p["nome"] for p in (estado.get("pranchetas") or [])}
    if not nomes:
        raise HTTPException(409, "este trabalho não está esperando escolha de prancheta")
    if nome not in nomes:
        raise HTTPException(422, f"não existe prancheta `{nome}`. "
                                 f"Tem: {', '.join(sorted(nomes))}")

    arte = trabalhos.pasta_do(job) / estado["arte"]
    trabalhos.gravar(job, {"status": "na fila", "prancheta": nome})
    FILA.enfileirar(processar, job, str(arte), estado["formatos"],
                    estado.get("headline", ""), estado.get("cta", ""),
                    estado.get("brief", ""), nome)
    return {"job": job, "status": trabalhos.ler(job)["status"], "prancheta": nome}


@app.post("/jobs/{job}/animar", status_code=202)
def animar(job: str, formatos: str = Form(""), preset: str = Form("editorial"),
           segundos: float = Form(5.0)):
    """Anima formatos que já viraram peça. Só esses: animar o que não foi
    composto não é pedido válido, é engano."""
    from api import animacao
    try:
        estado = trabalhos.ler(job)
    except ValueError:
        raise HTTPException(400, "identificador inválido")
    if estado is None:
        raise HTTPException(404, "trabalho não existe")
    if not animacao.instalado():
        raise HTTPException(503, "o projeto de vídeo não está instalado nesta máquina: "
                                 "rode `npm install` em video/")

    prontas = list(estado.get("prontas") or [])
    if not prontas:
        raise HTTPException(409, "este trabalho ainda não tem peça pronta para animar")
    pedidos = [f.strip() for f in formatos.split(",") if f.strip()] or prontas
    fora = [f for f in pedidos if f not in prontas]
    if fora:
        raise HTTPException(422, f"sem peça pronta para: {', '.join(fora)}")
    if preset not in animacao.PRESETS:
        raise HTTPException(422, f"preset desconhecido: `{preset}`. "
                                 f"Use {', '.join(animacao.PRESETS)}")
    if not 1.0 <= segundos <= 20.0:
        raise HTTPException(422, "a duração vai de 1 a 20 segundos")

    trabalhos.gravar(job, {"video": {"status": "na fila", "preset": preset,
                                     "formatos": pedidos}})
    FILA.enfileirar(processar_video, job, pedidos, preset, float(segundos),
                    fila=FILA_VIDEO)
    return {"job": job, "video": trabalhos.ler(job)["video"]}


@app.get("/jobs/{job}")
def ver(job: str):
    try:
        estado = trabalhos.ler(job)
    except ValueError:
        raise HTTPException(400, "identificador inválido")
    if estado is None:
        raise HTTPException(404, "trabalho não existe")
    return {"job": job, **estado, "entregas": trabalhos.entregas(job)}


@app.get("/jobs/{job}/zip")
def zip_do_trabalho(job: str):
    """Tudo num arquivo só. Baixar peça por peça é o que mais irrita quem
    entrega para cliente, e são oito, dez arquivos por campanha."""
    try:
        pasta = trabalhos.pasta_do(job)
    except ValueError:
        raise HTTPException(400, "identificador inválido")
    itens = trabalhos.entregas(job)
    if not itens:
        raise HTTPException(404, "este trabalho ainda não tem entregas")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for it in itens:
            z.write(pasta / it["nome"], Path(it["nome"]).name)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{job}.zip"'})


@app.get("/jobs/{job}/arquivos/{nome:path}")
def baixar(job: str, nome: str):
    try:
        pasta = trabalhos.pasta_do(job)
    except ValueError:
        raise HTTPException(400, "identificador inválido")
    alvo = (pasta / nome).resolve()
    if not str(alvo).startswith(str(pasta)) or not alvo.is_file():
        raise HTTPException(404, "arquivo não existe neste trabalho")
    return FileResponse(alvo, filename=alvo.name)
