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

from api import trabalhos
from api.compositor import CompositorSimples
from api.fila import fila_do_ambiente
from api.pipeline import desdobrar
from motor.replica import formato_by_id, load_formatos

app = FastAPI(title="ReplicAI", version="0.1.0")
WEB = Path(__file__).resolve().parent.parent / "web"
FILA = fila_do_ambiente()

ACEITOS = {".png", ".jpg", ".jpeg", ".webp", ".psd", ".psb", ".pdf"}


def processar(job: str, arte: str, formatos: list[str], headline: str,
              cta: str, brief: str) -> None:
    """O que o worker executa. Fora da API de propósito: é o pedaço pesado."""
    trabalhos.gravar(job, {"status": "rodando"})
    try:
        r = desdobrar(Path(arte), formatos,
                      CompositorSimples(headline=headline, cta=cta),
                      trabalhos.pasta_do(job), brief)
        trabalhos.gravar(job, {"status": r.status,
                               "prontas": sorted(r.prontas),
                               "falhas": r.falhas})
    except Exception as e:
        # sem isto o trabalho fica "rodando" para sempre e ninguém sabe por quê
        trabalhos.gravar(job, {"status": "erro", "erro": str(e)})
        raise


@app.get("/", response_class=HTMLResponse)
def tela():
    pagina = WEB / "index.html"
    if not pagina.exists():
        raise HTTPException(404, "a interface não foi instalada nesta imagem")
    return pagina.read_text(encoding="utf-8")


@app.get("/saude")
def saude():
    return {"ok": True, "fila": type(FILA).__name__}


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

    trabalhos.gravar(job, {"status": "na fila", "formatos": pedidos,
                           "titulo": titulo, "arte": destino.name})
    FILA.enfileirar(processar, job, str(destino), pedidos, headline, cta, brief)
    return {"job": job, "status": trabalhos.ler(job)["status"]}


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
