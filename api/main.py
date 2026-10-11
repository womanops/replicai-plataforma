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

from fastapi import Cookie, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from api import ambiente, contas, trabalhos, uso
from api.tarefas import processar, processar_video
from api.fila import FILA_VIDEO, fila_do_ambiente
from motor.replica import formato_by_id, load_formatos

ambiente.carregar()          # antes de qualquer coisa ler os.environ

app = FastAPI(title="ReplicAI", version="0.1.0")
WEB = Path(__file__).resolve().parent.parent / "web"
FILA = fila_do_ambiente()

ACEITOS = {".png", ".jpg", ".jpeg", ".webp", ".psd", ".psb", ".pdf"}


BISCOITO = "replicai_sessao"


def conta_atual(authorization: str | None = Header(default=None),
                replicai_sessao: str | None = Cookie(default=None)) -> contas.Conta:
    """De quem é a requisição.

    Dois caminhos: chave de API, para quem integra pelo programa, e selo de
    sessão, para quem usa a tela. Sem um dos dois não há conta, e sem conta
    não há trabalho — antes disto, quem alcançasse a porta criava peça.
    """
    if authorization and authorization.lower().startswith("bearer "):
        c = contas.da_chave(authorization.split(None, 1)[1].strip())
        if c:
            return c
    if replicai_sessao:
        ident = contas.abrir_selo(replicai_sessao)
        c = contas.por_id(ident) if ident else None
        if c and c.ativa:
            return c
    raise HTTPException(401, "entre com a sua chave ou faça login",
                        headers={"WWW-Authenticate": "Bearer"})


@app.post("/contas", status_code=201)
def abrir_conta(nome: str = Form(""), email: str = Form(...), senha: str = Form(...)):
    try:
        c = contas.criar(nome, email, senha)
    except contas.ContaInvalida as e:
        raise HTTPException(422, str(e))
    return c.em_json()


@app.post("/entrar")
def entrar(email: str = Form(...), senha: str = Form(...)):
    c = contas.autenticar(email, senha)
    if c is None:
        # a mesma resposta para e-mail que não existe e senha errada: dizer
        # qual dos dois errou conta quais e-mails têm conta
        raise HTTPException(401, "e-mail ou senha não conferem")
    r = JSONResponse(c.em_json())
    r.set_cookie(BISCOITO, contas.selar(c.id), httponly=True, samesite="lax",
                 max_age=contas.SELO_VALE)
    return r


@app.post("/sair")
def sair():
    r = JSONResponse({"ok": True})
    r.delete_cookie(BISCOITO)
    return r


@app.get("/eu")
def eu(c: contas.Conta = Depends(conta_atual)):
    return c.em_json()


@app.post("/eu/chaves", status_code=201)
def criar_chave(apelido: str = Form(""), c: contas.Conta = Depends(conta_atual)):
    """A chave aparece aqui e nunca mais: do lado de cá fica só o resumo."""
    return {"chave": contas.nova_chave(c, apelido),
            "aviso": "guarde agora: esta é a única vez que ela aparece"}


@app.delete("/eu/chaves/{ident}")
def revogar_chave(ident: str, c: contas.Conta = Depends(conta_atual)):
    if not contas.revogar(c, ident):
        raise HTTPException(404, "não existe chave ativa com esse identificador")
    return {"ok": True}


@app.get("/jobs")
def meus_trabalhos(c: contas.Conta = Depends(conta_atual)):
    return {"trabalhos": trabalhos.do_cliente(c.id)}


@app.get("/eu/uso")
def meu_uso(mes: str = "", c: contas.Conta = Depends(conta_atual)):
    """Quanto a conta consumiu, e quanto o plano permite."""
    lim = uso.limites(c.plano)
    r = uso.resumo(c.id, mes)
    return {**r, "plano": {"id": c.plano, **lim},
            "resta": {"pecas": max(0, lim["pecas"] - r["pecas"]),
                      "videos": max(0, lim["videos"] - r["videos"])},
            "meses": uso.meses(c.id)}


@app.get("/eu/uso/eventos")
def meus_eventos(mes: str = "", c: contas.Conta = Depends(conta_atual)):
    """A lista, não o número: quando a fatura subir, a resposta é esta."""
    return {"mes": mes or uso._mes(), "eventos": uso.eventos(c.id, mes)}


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
            "fila_tamanho": {n: q.count for n, q in getattr(FILA, "filas", {}).items()},
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
    c: contas.Conta = Depends(conta_atual),
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

    pode, porque = uso.cabe(c.id, c.plano, pecas=len(pedidos))
    if not pode:
        # conferido antes de enfileirar: recusar um trabalho já renderizado é
        # gastar o custo e não poder cobrar
        raise HTTPException(402, porque)

    job = trabalhos.novo_id(titulo or Path(arte.filename or "peca").stem)
    pasta = trabalhos.pasta_do(c.id, job)
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
            # x e y vão junto: a tela recorta a miniatura do PSD por prancheta
            # e a pessoa escolhe vendo, em vez de adivinhar por "Prancheta 4"
            lista = [{"nome": p.nome, "x": p.x, "y": p.y, "w": p.w, "h": p.h}
                     for p in achadas]
            trabalhos.gravar(c.id, job, {**comum, "status": "escolha a prancheta",
                                   "pranchetas": lista})
            # 200, e não o 202 da rota: nada entrou na fila, o trabalho está
            # parado esperando uma escolha
            return JSONResponse(status_code=200, content={
                "job": job, "status": "escolha a prancheta", "pranchetas": lista,
                "como": f"POST /jobs/{job}/prancheta com o nome"})
        if prancheta and prancheta not in {p.nome for p in achadas}:
            raise HTTPException(422, f"não existe prancheta `{prancheta}` nesse arquivo. "
                                     f"Tem: {', '.join(p.nome for p in achadas)}")

    trabalhos.gravar(c.id, job, {**comum, "status": "na fila", "prancheta": prancheta})
    na_fila = FILA.enfileirar(processar, c.id, job, str(destino), pedidos, headline, cta,
                              brief, prancheta)
    trabalhos.gravar(c.id, job, {"id_na_fila": na_fila})
    return {"job": job, "status": trabalhos.ler(c.id, job)["status"]}


@app.post("/jobs/{job}/prancheta", status_code=202)
def escolher_prancheta(job: str, nome: str = Form(...),
                       c: contas.Conta = Depends(conta_atual)):
    """Escolhe a prancheta de um PSD e põe o trabalho na fila."""
    try:
        estado = trabalhos.ler(c.id, job)
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

    arte = trabalhos.pasta_do(c.id, job) / estado["arte"]
    trabalhos.gravar(c.id, job, {"status": "na fila", "prancheta": nome})
    trabalhos.gravar(c.id, job, {"id_na_fila": FILA.enfileirar(
        processar, c.id, job, str(arte), estado["formatos"], estado.get("headline", ""),
        estado.get("cta", ""), estado.get("brief", ""), nome)})
    return {"job": job, "status": trabalhos.ler(c.id, job)["status"], "prancheta": nome}


@app.post("/jobs/{job}/animar", status_code=202)
def animar(job: str, formatos: str = Form(""), preset: str = Form("editorial"),
           segundos: float = Form(5.0), c: contas.Conta = Depends(conta_atual)):
    """Anima formatos que já viraram peça. Só esses: animar o que não foi
    composto não é pedido válido, é engano."""
    from api import animacao
    try:
        estado = trabalhos.ler(c.id, job)
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
    pode, porque = uso.cabe(c.id, c.plano, videos=len(pedidos))
    if not pode:
        raise HTTPException(402, porque)

    trabalhos.gravar(c.id, job, {"video": {"status": "na fila", "preset": preset,
                                     "formatos": pedidos}})
    trabalhos.gravar(c.id, job, {"id_na_fila": FILA.enfileirar(
        processar_video, c.id, job, pedidos, preset, float(segundos), fila=FILA_VIDEO)})
    return {"job": job, "video": trabalhos.ler(c.id, job)["video"]}


@app.get("/jobs/{job}")
def ver(job: str, c: contas.Conta = Depends(conta_atual)):
    try:
        estado = trabalhos.ler(c.id, job)
    except ValueError:
        raise HTTPException(400, "identificador inválido")
    if estado is None:
        raise HTTPException(404, "trabalho não existe")
    estado = perdido(c.id, job, estado)
    return {"job": job, **estado, "entregas": trabalhos.entregas(c.id, job)}


def perdido(conta: str, job: str, estado: dict) -> dict:
    """Trabalho que a fila perdeu não pode ficar esperando para sempre.

    O worker pode morrer entre tirar o trabalho da fila e começar a gravar
    estado — num desligamento, num estouro de memória. O arquivo fica em "na
    fila" e, de fora, isso é indistinguível de uma fila comprida. Aconteceu
    duas vezes aqui, e levou meia hora para eu entender que não era lentidão.
    """
    if estado.get("status") not in ("na fila", "rodando"):
        return estado
    ident = estado.get("id_na_fila")
    if not ident or not hasattr(FILA, "filas"):
        return estado
    try:
        from rq.job import Job
        conexao = next(iter(FILA.filas.values())).connection
        try:
            vaga = Job.fetch(ident, connection=conexao)
        except Exception:
            vaga = None
        if vaga is None:
            motivo = "o trabalho sumiu da fila sem ser executado"
        elif vaga.is_failed:
            motivo = (vaga.latest_result().exc_string if vaga.latest_result()
                      else "falhou sem deixar mensagem")
        else:
            return estado
    except Exception:
        return estado                 # diagnóstico nunca derruba a consulta
    novo = {"status": "erro", "erro": motivo.strip().splitlines()[-1][:300],
            "progresso": None}
    trabalhos.gravar(conta, job, novo)
    return {**estado, **novo}


@app.get("/jobs/{job}/zip")
def zip_do_trabalho(job: str, c: contas.Conta = Depends(conta_atual)):
    """Tudo num arquivo só. Baixar peça por peça é o que mais irrita quem
    entrega para cliente, e são oito, dez arquivos por campanha."""
    try:
        pasta = trabalhos.pasta_do(c.id, job)
    except ValueError:
        raise HTTPException(400, "identificador inválido")
    itens = trabalhos.entregas(c.id, job)
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
def baixar(job: str, nome: str, c: contas.Conta = Depends(conta_atual)):
    try:
        pasta = trabalhos.pasta_do(c.id, job)
    except ValueError:
        raise HTTPException(400, "identificador inválido")
    alvo = (pasta / nome).resolve()
    if not str(alvo).startswith(str(pasta)) or not alvo.is_file():
        raise HTTPException(404, "arquivo não existe neste trabalho")
    return FileResponse(alvo, filename=alvo.name)
