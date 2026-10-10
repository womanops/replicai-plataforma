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
from api.compositor import CompositorEmCadeia, CompositorModelo, CompositorSimples
from api.fila import fila_do_ambiente
from api.pipeline import desdobrar
from motor.replica import formato_by_id, load_formatos

ambiente.carregar()          # antes de qualquer coisa ler os.environ

app = FastAPI(title="ReplicAI", version="0.1.0")
WEB = Path(__file__).resolve().parent.parent / "web"
FILA = fila_do_ambiente()

ACEITOS = {".png", ".jpg", ".jpeg", ".webp", ".psd", ".psb", ".pdf"}


def compositor(arte: str, headline: str, cta: str):
    """Quem compõe. Com credencial, o modelo decide a estrutura e a máquina
    calcula as caixas; a regra determinística fica atrás como rede. Sem
    credencial, só a regra — a plataforma funciona, com menos qualidade, em vez
    de recusar o trabalho.

    A ordem é essa e não o contrário: a regra dá conta do caso fácil, mas não
    sabe o que sacrificar quando o formato aperta, que é o que decide a peça.
    """
    from api import modelo
    simples = CompositorSimples(headline=headline, cta=cta)
    if not modelo.disponivel():
        return simples
    pelo_modelo = CompositorModelo(
        modelo.responder_anthropic,
        fundo={"tipo": "imagem", "src": Path(arte).name, "fit": "cover"})
    return CompositorEmCadeia(pelo_modelo, simples)


def processar(job: str, arte: str, formatos: list[str], headline: str,
              cta: str, brief: str) -> None:
    """O que o worker executa. Fora da API de propósito: é o pedaço pesado."""
    trabalhos.gravar(job, {"status": "rodando"})
    try:
        r = desdobrar(Path(arte), formatos, compositor(arte, headline, cta),
                      trabalhos.pasta_do(job), brief)
        trabalhos.gravar(job, {"status": r.status,
                               "prontas": sorted(r.prontas),
                               "falhas": r.falhas,
                               "avisos": r.avisos,
                               "custo": r.custo})
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
            "compositor": "modelo+regra" if modelo.disponivel() else "regra",
            "desenhando_com": desenhando_com()}


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
