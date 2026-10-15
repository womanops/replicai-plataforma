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

import hmac
import os

from fastapi import (Cookie, Depends, FastAPI, File, Form, Header, HTTPException,
                     Request, UploadFile)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from api import ambiente, cobranca, contas, trabalhos, uso
from api.pipeline import MARCA_DA_MAO
from api.tarefas import (MODOS, MODO_PADRAO, TEXTO_NOVO, previas, processar,
                         processar_video, redesenhar, refazer_fundo)
from api.fila import FILA_VIDEO, fila_do_ambiente
from motor.replica import formato_by_id, load_formatos

ambiente.carregar()          # antes de qualquer coisa ler os.environ

app = FastAPI(title="ReplicAI", version="0.1.0")
WEB = Path(__file__).resolve().parent.parent / "web"
FILA = fila_do_ambiente()

ACEITOS = {".png", ".jpg", ".jpeg", ".webp", ".psd", ".psb", ".pdf"}

# Teto da arte que entra. O PSD é 85% do disco de um trabalho: 60 dos 71 MB
# no arquivo que serviu de medida. Sem teto, uma arte de 2 GB enche o disco do
# servidor antes de qualquer conferência, e nada a impede.
#
# 250 MB é quatro vezes o maior arquivo real que passou por aqui. Não é número
# medido num arquivo grande de verdade — é julgamento a partir do que foi
# medido, e vale rever quando aparecer um KV pesado.
LIMITE_ARTE = int(os.environ.get("REPLICAI_MAX_ARTE_MB", "250")) * 1_000_000

# a página de planos e o endereço para pedir demonstração moram fora do
# sistema e ainda não têm domínio. Enquanto não estiverem configurados a porta
# diz a frase sem link — endereço inventado manda quem não assinou para o nada.
SITE_PLANOS = os.environ.get("REPLICAI_SITE_PLANOS", "").strip()
# o contato já existe: é o mesmo que a landing usa no "agendar demonstração"
CONTATO_DEMO = os.environ.get("REPLICAI_CONTATO_DEMO", "contato@operandi.com.br").strip()

# lido em pedaços: a conferência tem que acontecer enquanto o arquivo chega,
# não depois. Esperar o fim para medir é deixar o disco encher primeiro.
PEDACO = 1024 * 1024


def gravar_arte(entrada, destino: Path, limite: int = LIMITE_ARTE) -> int:
    """Grava a arte que subiu, parando no limite. Devolve o tamanho.

    O que passou do teto é apagado antes de levantar: um upload recusado não
    pode deixar meio arquivo ocupando lugar.
    """
    total = 0
    try:
        with destino.open("wb") as f:
            while pedaco := entrada.read(PEDACO):
                total += len(pedaco)
                if total > limite:
                    raise HTTPException(
                        413, f"a arte passa de {limite // 1_000_000} MB. "
                             f"Achate o PSD, ou mande só a prancheta que vai ser "
                             f"adaptada")
                f.write(pedaco)
    except Exception:
        destino.unlink(missing_ok=True)
        raise
    return total


BISCOITO = "replicai_sessao"


# a conta existe porque alguém assinou um plano: sem plano ativo não há
# sistema. Quem quer ver antes de assinar fala com a gente — isso acontece
# fora daqui, e é por isso que esta mensagem convida a assinar, não a esperar
SEM_PLANO = ("esta conta não tem plano ativo. Assine um plano para usar — ou "
             "fale com a gente se quiser ver uma demonstração antes")


def quem_e(authorization: str | None = Header(default=None),
           replicai_sessao: str | None = Cookie(default=None)) -> contas.Conta:
    """De quem é a requisição, tendo plano ou não.

    Dois caminhos: chave de API, para quem integra pelo programa, e selo de
    sessão, para quem usa a tela. Sem um dos dois não há conta, e sem conta
    não há trabalho — antes disto, quem alcançasse a porta criava peça.

    Só os endereços que precisam responder a quem ainda não contratou usam
    este: ver a própria conta, ver os planos, sair. O resto usa `conta_atual`,
    que exige plano.
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


def conta_atual(c: contas.Conta = Depends(quem_e)) -> contas.Conta:
    """A conta de quem PODE produzir.

    Baixar o que já foi feito não passa por aqui: a peça é dela, já foi paga, e
    servir arquivo não custa por unidade. O que o pagamento abre é produzir —
    gerar, ajustar, animar, refazer.

    Sem plano não é "sem franquia": é sem acesso. A demonstração é feita por
    nós, a conta nasce ligada ao plano contratado, e quem deixa de pagar para
    de entrar — as peças que já saíram continuam baixáveis pelos endereços de
    conta, que não exigem plano.

    O padrão é exigir: endereço novo nasce protegido, e abrir exceção é um ato
    deliberado de quem escreve o endereço. O contrário — proteger um a um —
    deixa passar o que se esquece.
    """
    if not uso.limites(cobranca.plano_valendo(c))["pecas"] and not uso.sem_limite():
        raise HTTPException(402, SEM_PLANO)
    return c


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
def eu(c: contas.Conta = Depends(quem_e)):
    return c.em_json()


@app.get("/eu/medidas")
def minhas_medidas(c: contas.Conta = Depends(quem_e)):
    """As medidas fora do catálogo que a pessoa já usou.

    Elas não mudam nada em como a peça é feita — o motor resolve qualquer
    `livre-LARGxALT`. O que elas evitam é digitar a mesma medida toda vez.
    """
    return {"medidas": c.medidas}


@app.post("/eu/medidas", status_code=201)
def guardar_medida(largura: int = Form(...), altura: int = Form(...),
                   nome: str = Form(""), c: contas.Conta = Depends(conta_atual)):
    try:
        return {"medidas": contas.guardar_medida(c, largura, altura, nome)}
    except contas.ContaInvalida as e:
        raise HTTPException(400, str(e))


@app.delete("/eu/medidas/{ident}")
def esquecer_medida(ident: str, c: contas.Conta = Depends(conta_atual)):
    return {"medidas": contas.esquecer_medida(c, ident)}


@app.get("/eu/fontes")
def minhas_fontes(c: contas.Conta = Depends(quem_e)):
    """As fontes da marca que a conta já enviou."""
    return {"fontes": c.em_json()["fontes"]}


@app.post("/eu/fontes", status_code=201)
async def guardar_fonte(fonte: UploadFile = File(...),
                        c: contas.Conta = Depends(conta_atual)):
    """Guarda um arquivo de fonte na conta.

    É o que permite trocar o texto de uma peça do PSD sem trocar a letra: o
    PSD diz qual fonte a linha usa, mas não leva o arquivo dentro dele.
    """
    dados = await fonte.read()
    try:
        item = contas.guardar_fonte(c, fonte.filename or "", dados)
    except contas.ContaInvalida as e:
        raise HTTPException(400, str(e))
    return {"fonte": {k: item[k] for k in ("id", "familia", "estilo", "nome")},
            "fontes": c.em_json()["fontes"]}


@app.delete("/eu/fontes/{ident}")
def esquecer_fonte(ident: str, c: contas.Conta = Depends(conta_atual)):
    contas.esquecer_fonte(c, ident)
    return {"fontes": c.em_json()["fontes"]}


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
def meus_trabalhos(c: contas.Conta = Depends(quem_e)):
    return {"trabalhos": trabalhos.do_cliente(c.id)}


@app.get("/planos")
def planos():
    """O que cada plano permite e quanto custa."""
    from api import precos
    # só os que se contrata: "sem plano" é estado de quem ainda não falou com a
    # gente, não um degrau da escada
    return {"planos": [{"id": i, **uso.PLANOS[i],
                        "preco": cobranca.PRECO(i),
                        **precos.conta(uso.PLANOS[i]["pecas"], cobranca.PRECO(i))}
                       for i in uso.A_VENDA],
            "margem_alvo": precos.MARGEM_ALVO,
            "custo_por_peca": round(precos.custo_peca(), 4),
            # o que o preço de um plano NÃO cobre sozinho: servidor e
            # ferramentas existem com zero cliente, e são pagos pela margem.
            # Margem de 80% com um cliente só não paga servidor nenhum
            **precos.ponto_de_equilibrio(uso.PLANOS),
            "cobranca": cobranca.configurada()}


@app.post("/eu/assinar")
def assinar(plano: str = Form(...), forma: str = Form("PIX"),
            cpf_cnpj: str = Form(""), c: contas.Conta = Depends(conta_atual)):
    """Contrata um plano. Não libera nada: quem libera é o aviso de pagamento."""
    try:
        return cobranca.assinar(c, plano, forma, cpf_cnpj)
    except cobranca.CobrancaIndisponivel as e:
        raise HTTPException(502, str(e))


@app.delete("/eu/assinar")
def cancelar_assinatura(c: contas.Conta = Depends(quem_e)):
    try:
        if not cobranca.cancelar(c):
            raise HTTPException(404, "não há assinatura para cancelar")
    except cobranca.CobrancaIndisponivel as e:
        raise HTTPException(502, str(e))
    return {"ok": True, "aviso": "o plano vale até o fim do período já pago"}


@app.post("/cobranca/aviso")
async def aviso_de_cobranca(request: Request,
                            asaas_access_token: str | None = Header(default=None)):
    """O que o Asaas avisa quando alguém paga ou atrasa.

    Autenticado por segredo combinado: sem isso, qualquer um na internet
    libera plano mandando um JSON. Responde 200 mesmo para evento que não é
    nosso — senão o Asaas reenvia para sempre.
    """
    esperado = os.environ.get("ASAAS_AVISO_TOKEN")
    if not esperado:
        raise HTTPException(503, "ASAAS_AVISO_TOKEN não está configurado")
    if not asaas_access_token or not hmac.compare_digest(asaas_access_token, esperado):
        raise HTTPException(401, "aviso sem credencial")
    return cobranca.aplicar_evento(await request.json())


@app.get("/eu/uso")
def meu_uso(mes: str = "", c: contas.Conta = Depends(quem_e)):
    """Quanto a conta consumiu, e quanto o plano permite."""
    valendo = cobranca.plano_valendo(c)
    lim = uso.limites(valendo)
    r = uso.resumo(c.id, mes, dia_do_ciclo=cobranca.dia_do_ciclo(c))
    return {**r, "plano": {"id": valendo, "contratado": c.plano, **lim},
            "em_atraso": c.em_atraso, "pago_ate": c.pago_ate,
            "resta": {"pecas": max(0, lim["pecas"] - r["pecas"]),
                      "videos": max(0, lim["videos"] - r["videos"])},
            "meses": uso.meses(c.id)}


@app.get("/eu/uso/eventos")
def meus_eventos(mes: str = "", c: contas.Conta = Depends(quem_e)):
    """A lista, não o número: quando a fatura subir, a resposta é esta."""
    return {"mes": mes or uso._mes(), "eventos": uso.eventos(c.id, mes)}


@app.get("/assets/{nome}")
def arquivo_da_marca(nome: str):
    """A marca e o ícone. Servidos daqui porque a tela é um arquivo só e a
    logomarca não cabe nela em linha sem virar ruído no meio do CSS."""
    alvo = (WEB / "assets" / nome).resolve()
    if alvo.parent != (WEB / "assets").resolve() or not alvo.is_file():
        raise HTTPException(404, "não existe")
    return FileResponse(alvo, media_type="image/svg+xml" if alvo.suffix == ".svg" else None)


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


@app.get("/porta")
def porta():
    """O que a tela de entrada pode dizer antes de alguém entrar.

    Só os dois endereços de fora: a página onde se assina e o contato de
    demonstração. Vazio quando não há domínio configurado — a porta mostra a
    frase sem link em vez de prometer um endereço que não existe.
    """
    return {"site_planos": SITE_PLANOS, "contato_demo": CONTATO_DEMO}


@app.get("/saude")
def saude():
    from api import modelo
    from api import precos as precos_
    return {"ok": True, "fila": type(FILA).__name__,
            "fila_porque": getattr(FILA, "porque", ""),
            "fila_tamanho": {n: q.count for n, q in getattr(FILA, "filas", {}).items()},
            "compositor": "modelo+regra" if modelo.disponivel() else "regra",
            "limite_arte_mb": LIMITE_ARTE // 1_000_000,
            # ambiente que não cobra precisa dizer que não cobra
            "franquia": "desligada (REPLICAI_SEM_LIMITE)" if uso.sem_limite() else "valendo",
            # sem segredo configurado o selo é sorteado ao subir: reiniciar
            # desloga todo mundo, e duas réplicas atrás do mesmo endereço não
            # reconhecem a sessão uma da outra. Serve para desenvolver, e em
            # produção é defeito — que só aparece quando o cliente reclama
            "sessao": "segredo configurado" if contas.segredo_configurado()
                      else "segredo sorteado ao subir: reiniciar desloga todo mundo",
            # preço de tabela que já não cobre a margem pretendida: o câmbio
            # subiu e ninguém mexeu no preço. Não se corrige sozinho — aparece
            # aqui e na esteira, para alguém decidir
            "precos": "tabela abaixo do piso: " + ", ".join(furados)
                      if (furados := precos_.abaixo_do_piso(uso.PLANOS)) else "valendo",
            "desenhando_com": desenhando_com()}


@app.get("/presets")
def presets():
    """Os presets com nome, descrição e o exemplo em vídeo de cada um.

    Escolher movimento por uma palavra solta é adivinhar: o exemplo mostra o
    que vai acontecer com a peça antes de gastar um render em cada formato.
    """
    from api import animacao
    lista = []
    for pid in animacao.PRESETS:
        sobre = animacao.SOBRE.get(pid, {})
        # WebP animado, e não mp4: vídeo em elemento criado por script fica
        # parado quando o navegador exige gesto para tocar, e um exemplo de
        # movimento congelado não explica nada. Imagem sempre anda
        amostra = WEB / "assets" / f"exemplo-{pid}.webp"
        lista.append({"id": pid, "nome": sobre.get("nome", pid),
                      "diz": sobre.get("diz", ""),
                      # sem o arquivo, a tela mostra só o texto: prometer um
                      # vídeo que não abre é pior do que não prometer
                      "exemplo": f"/assets/{amostra.name}" if amostra.exists() else None})
    return {"presets": lista, "padrao": animacao.PRESET_PADRAO,
            "disponivel": animacao.instalado()}


@app.get("/formatos")
def formatos():
    return load_formatos()["formatos"]


@app.post("/jobs", status_code=202)
async def criar(
    arte: UploadFile = File(...),
    formatos: str = Form(..., description="ids separados por vírgula"),
    headline: str = Form(""),
    cta: str = Form(""),
    titulo: str = Form(""),
    brief: str = Form(""),
    prancheta: str = Form(""),
    modo: str = Form(MODO_PADRAO, description="sem | com | novo"),
    c: contas.Conta = Depends(conta_atual),
):
    if modo not in MODOS:
        raise HTTPException(422, f"modo desconhecido: `{modo}`. Use {', '.join(MODOS)}")
    # a chamada só é exigida de quem pediu texto novo. Exigir sempre travava o
    # pedido de quem queria apenas a mesma peça noutros formatos — e não há
    # chamada a escrever quando nada vai ser escrito
    if modo == TEXTO_NOVO and not headline.strip():
        raise HTTPException(422, "para escrever texto novo preciso da chamada")
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

    pode, porque = uso.cabe(c.id, cobranca.plano_valendo(c), pecas=len(pedidos),
                            dia_do_ciclo=cobranca.dia_do_ciclo(c))
    if not pode:
        # conferido antes de enfileirar: recusar um trabalho já renderizado é
        # gastar o custo e não poder cobrar
        raise HTTPException(402, porque)

    job = trabalhos.novo_id(titulo or Path(arte.filename or "peca").stem)
    pasta = trabalhos.pasta_do(c.id, job)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"arte{ext}"
    gravar_arte(arte.file, destino)

    comum = {"formatos": pedidos, "titulo": titulo, "arte": destino.name,
             "headline": headline, "cta": cta, "brief": brief, "modo": modo}

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
            # a prévia de cada prancheta vai para a fila: a lista aparece na
            # hora e as imagens chegam atrás. A miniatura embutida no PSD tem
            # 256 px para o documento inteiro — recortada numa prancheta, não
            # dá para reconhecer qual peça é
            FILA.enfileirar(previas, c.id, job, str(destino))
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
                              brief, prancheta, False, modo)
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
        estado.get("cta", ""), estado.get("brief", ""), nome, False,
        estado.get("modo", MODO_PADRAO))})
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
    pode, porque = uso.cabe(c.id, cobranca.plano_valendo(c), videos=len(pedidos),
                            dia_do_ciclo=cobranca.dia_do_ciclo(c))
    if not pode:
        raise HTTPException(402, porque)

    trabalhos.gravar(c.id, job, {"video": {"status": "na fila", "preset": preset,
                                     "formatos": pedidos}})
    trabalhos.gravar(c.id, job, {"id_na_fila": FILA.enfileirar(
        processar_video, c.id, job, pedidos, preset, float(segundos), fila=FILA_VIDEO)})
    return {"job": job, "video": trabalhos.ler(c.id, job)["video"]}


@app.post("/jobs/{job}/pecas/{formato}/fundo", status_code=202)
def refazer_o_fundo(job: str, formato: str, c: contas.Conta = Depends(conta_atual)):
    """Refaz o fundo de uma peça só, insistindo no generativo.

    A ressalva do fundo dizia "vale rodar de novo" e a única saída era refazer
    o trabalho inteiro pelo rodapé. Quem viu o problema está olhando uma peça:
    a saída tem que valer para ela.
    """
    try:
        estado = trabalhos.ler(c.id, job)
    except ValueError:
        raise HTTPException(400, "identificador inválido")
    if estado is None:
        raise HTTPException(404, "trabalho não existe")
    if formato not in (estado.get("prontas") or []):
        raise HTTPException(409, f"não há peça pronta em `{formato}`")
    if estado.get("arquivado"):
        raise HTTPException(409, "o material bruto deste trabalho já foi apagado por "
                                 "idade: sem a arte não dá para refazer o fundo")
    if estado.get("status") in ("na fila", "rodando"):
        raise HTTPException(409, "este trabalho ainda está rodando")

    trabalhos.gravar(c.id, job, {"ajuste": {"status": "na fila", "formato": formato,
                                            "oque": "fundo"}})
    trabalhos.gravar(c.id, job, {"id_na_fila": FILA.enfileirar(
        refazer_fundo, c.id, job, formato)})
    return {"job": job, "formato": formato, "ajuste": "na fila"}


@app.post("/jobs/{job}/finalizar", status_code=202)
def finalizar(job: str, c: contas.Conta = Depends(conta_atual)):
    """Refaz o trabalho em modo final.

    A diferença é o fundo generativo: no rascunho ele é pedido uma vez só, e
    se inventar traço que a arte não tem a peça sai assim mesmo, com o aviso.
    Aqui ele insiste até sair limpo — e só nos formatos que precisaram, porque
    o que passou na conferência é reaproveitado. Chamada de generativo é o
    item mais caro da peça; refazer a cada rascunho é queimar margem numa
    versão que ainda vai mudar.
    """
    try:
        estado = trabalhos.ler(c.id, job)
    except ValueError:
        raise HTTPException(400, "identificador inválido")
    if estado is None:
        raise HTTPException(404, "trabalho não existe")
    if estado.get("status") in ("na fila", "rodando"):
        raise HTTPException(409, "este trabalho ainda está rodando")
    if not estado.get("prontas"):
        raise HTTPException(409, "não há peça pronta para finalizar")
    if estado.get("arquivado"):
        raise HTTPException(409, "o material bruto deste trabalho já foi apagado "
                                 "por idade: as peças continuam para baixar, mas "
                                 "refazer os fundos exigiria a arte. Suba de novo")

    arte = trabalhos.pasta_do(c.id, job) / estado["arte"]
    trabalhos.gravar(c.id, job, {"status": "na fila", "final": True})
    trabalhos.gravar(c.id, job, {"id_na_fila": FILA.enfileirar(
        processar, c.id, job, str(arte), estado["formatos"], estado.get("headline", ""),
        estado.get("cta", ""), estado.get("brief", ""), estado.get("prancheta", ""),
        True, estado.get("modo", MODO_PADRAO))})
    return {"job": job, "status": "na fila", "final": True}


# o que a tela pode mexer numa peça já montada. Lista curta de propósito: o
# `src` fica de fora, senão um pedido forjado faria o motor desenhar — e
# devolver no PNG — qualquer arquivo da máquina
AJUSTAVEL = {"box", "texto", "align", "valign", "cor", "peso", "min", "max",
             "lineHeight", "opacidade"}

# a família que o trabalho declara em `fontes`. Quem desenha é o navegador, e
# ele só conhece a que foi copiada para a pasta do trabalho
FAMILIA_DO_TRABALHO = "PecaSans"


def _cor_da_linha(caminhos: list[Path]) -> str:
    """A cor da linha, pela letra que tem mais tinta.

    Não é a média: em "A PORTO BELO!" o A é branco e o resto azul-escuro, e a
    média dos dois dá um azul lavado que não existe na peça. A letra de maior
    área manda, que é o que o olho lê como a cor da linha.
    """
    from PIL import Image
    melhor, quanto = "", -1
    for caminho in caminhos:
        try:
            with Image.open(caminho) as im:
                px = [p for p in im.convert("RGBA").getdata() if p[3] > 128]
        except Exception:
            continue
        if len(px) <= quanto:
            continue
        quanto = len(px)
        n = len(px)
        melhor = "#%02X%02X%02X" % (sum(p[0] for p in px) // n,
                                    sum(p[1] for p in px) // n,
                                    sum(p[2] for p in px) // n)
    return melhor or "#FFFFFF"


def _fonte_da_linha(conta: contas.Conta, base: dict, pasta: Path) -> tuple[str, str]:
    """A fonte em que a linha vai ser escrita, e o que avisar sobre ela.

    O PSD diz qual fonte a linha usa — "FuturaICG-Bold" — mas não leva o
    arquivo dentro. Se a conta já enviou essa fonte, ela é copiada para o
    trabalho e a troca sai na MESMA letra. Se não, o texto sai na letra da
    casa, e isso tem que ser dito: declarar uma família sem ter o arquivo faz
    o navegador cair numa fonte do sistema e a peça sai com outra tipografia,
    calada. É o erro mais difícil de ver no olho.
    """
    pedida = (base.get("fonte_mae") or "").strip()
    if not pedida:
        return FAMILIA_DO_TRABALHO, ""
    achada = contas.fonte_de(conta, pedida)
    if not achada:
        return (FAMILIA_DO_TRABALHO,
                f"esta linha é {pedida}, e essa fonte não está na sua conta: o texto "
                f"novo saiu na letra da casa. Envie o arquivo dela em Fontes da marca "
                f"e troque de novo para sair igual")
    origem = contas.pasta_das_fontes(conta) / achada["nome"]
    destino = Path(pasta) / achada["nome"]
    if not destino.exists():
        shutil.copy2(origem, destino)
    return pedida, ""


def _virar_texto(base: dict, pasta: Path, texto: str, familia: str,
                 irmas: list[dict] | None = None) -> dict:
    """Troca um recorte de letra do PSD por texto de verdade.

    A linha da arte chega como uma imagem por letra: "a Porto Belo!" são onze
    PNGs recortados do arquivo. Para trocar a cidade não dá para editar PNG —
    o jeito é desenhar a frase nova no lugar da linha inteira, com a cor que a
    linha tinha e a fonte do trabalho.

    A letra MUDA de desenho: a fonte da marca não vem dentro do PSD. É por
    isso que a tela avisa antes, e não depois.
    """
    caixa = base.get("box") or {}
    alto = int(caixa.get("h") or 40)
    recortes = [pasta / e["src"] for e in (irmas or [base]) if e.get("src")]
    return {"tipo": "texto", "papel": base.get("papel") or "apoio",
            "camada": base.get("camada"), "texto": texto,
            "box": caixa, "fonte": familia, "peso": 600,
            "cor": _cor_da_linha(recortes),
            "min": max(8, round(alto * 0.35)), "max": max(10, alto),
            "lineHeight": 1.05, "align": "left", "valign": "middle",
            "trocado": True}


def _peca_do(conta: str, job: str, formato: str) -> Path:
    if not formato_by_id(formato):
        raise HTTPException(422, f"formato desconhecido: {formato}")
    arq = trabalhos.pasta_do(conta, job) / "pecas" / f"{formato}.json"
    if not arq.exists():
        raise HTTPException(404, f"não existe peça montada para `{formato}`")
    return arq


@app.get("/jobs/{job}/pecas/{formato}")
def ver_peca(job: str, formato: str, c: contas.Conta = Depends(quem_e)):
    """A montagem da peça: é o que o editor abre para mover os elementos."""
    try:
        arq = _peca_do(c.id, job, formato)
    except ValueError:
        raise HTTPException(400, "identificador inválido")
    return json.loads(arq.read_text(encoding="utf-8"))


@app.post("/jobs/{job}/pecas/{formato}", status_code=202)
async def ajustar_peca(job: str, formato: str, request: Request,
                       c: contas.Conta = Depends(conta_atual)):
    """Grava a peça remontada na mão e manda desenhar de novo.

    Só a geometria e o texto de cada elemento mudam, e cada um é casado com o
    que já estava gravado em vez de substituí-lo: o que a tela manda é onde a
    pessoa pôs a caixa, não uma peça nova. Elemento que a tela não mandou de
    volta foi tirado de propósito.
    """
    try:
        arq = _peca_do(c.id, job, formato)
    except ValueError:
        raise HTTPException(400, "identificador inválido")
    estado = trabalhos.ler(c.id, job) or {}
    if estado.get("arquivado"):
        raise HTTPException(409, "o material bruto deste trabalho já foi apagado "
                                 "por idade: não há recorte de camada para remontar. "
                                 "Suba a arte de novo")
    corpo = await request.json()
    pedidos = corpo.get("elementos")
    if not isinstance(pedidos, list):
        raise HTTPException(422, "mande `elementos` com a lista remontada")

    peca = json.loads(arq.read_text(encoding="utf-8"))
    antigos = peca.get("elementos", [])
    novos, avisos, fontes_novas = [], [], {}
    for e in pedidos:
        if not isinstance(e, dict):
            raise HTTPException(422, "cada elemento é um objeto")
        i = e.get("i")
        if not isinstance(i, int) or not 0 <= i < len(antigos):
            raise HTTPException(422, "cada elemento precisa do índice `i` que veio na peça")
        base = dict(antigos[i])
        base.update({k: v for k, v in e.items() if k in AJUSTAVEL})
        # trocar o texto de uma linha que veio do PSD: ela é uma imagem por
        # letra, então o que acontece é a linha inteira virar texto desenhado.
        # `src` continua fora do que a tela manda — quem decide o arquivo é o
        # servidor, pelo elemento que já estava gravado
        if e.get("tipografar") and base.get("tipo") == "imagem":
            # as outras letras da mesma linha dizem a cor dela, e elas não
            # voltam no pedido: quem as tem é a peça gravada
            irmas = [a for a in antigos
                     if a.get("camada") and a.get("camada") == base.get("camada")]
            pasta_job = trabalhos.pasta_do(c.id, job)
            familia, aviso = _fonte_da_linha(c, base, pasta_job)
            if aviso:
                avisos.append(aviso)
            base = _virar_texto(base, pasta_job, str(e.get("texto") or ""),
                                familia, irmas)
            if familia != FAMILIA_DO_TRABALHO:
                arq_fonte = contas.fonte_de(c, familia)
                fontes_novas[familia] = {"familia": familia,
                                         "arquivo": arq_fonte["nome"],
                                         "peso": "100 900"}
        novos.append(base)
    peca["elementos"] = novos
    if any(e.get("trocado") for e in novos):
        from api.pipeline import _fonte_do_trabalho
        declaradas = {f.get("familia"): f for f in (peca.get("fontes") or [])}
        for f in _fonte_do_trabalho(trabalhos.pasta_do(c.id, job)):
            declaradas.setdefault(f["familia"], f)
        # a fonte da marca entra declarada COM arquivo: família declarada sem
        # arquivo é o navegador caindo numa fonte do sistema sem avisar
        declaradas.update(fontes_novas)
        peca["fontes"] = list(declaradas.values())
    # a marca é o que faz a exportação final devolver esta montagem em vez de
    # recompor por cima dela
    via = peca.get("via") or ""
    peca["via"] = via if MARCA_DA_MAO in via else via + MARCA_DA_MAO
    arq.write_text(json.dumps(peca, ensure_ascii=False, indent=1), encoding="utf-8")

    # o aviso da fonte fica COLADO na peça, e não só no retorno desta chamada:
    # ele aparecia uma vez, como recado que some sozinho, e depois a peça ia
    # para a exportação sem nada dizendo que aquela linha mudou de letra
    if avisos:
        guardados = (trabalhos.ler(c.id, job) or {}).get("avisos") or {}
        deste = list(guardados.get(formato) or [])
        deste += [a for a in avisos if a not in deste]
        trabalhos.gravar(c.id, job, {"avisos": {**guardados, formato: deste}})

    trabalhos.gravar(c.id, job, {"ajuste": {"status": "na fila", "formato": formato}})
    trabalhos.gravar(c.id, job, {"id_na_fila": FILA.enfileirar(
        redesenhar, c.id, job, formato)})
    return {"job": job, "formato": formato, "ajuste": "na fila", "avisos": avisos}


@app.get("/jobs/{job}")
def ver(job: str, c: contas.Conta = Depends(quem_e)):
    try:
        estado = trabalhos.ler(c.id, job)
    except ValueError:
        raise HTTPException(400, "identificador inválido")
    if estado is None:
        raise HTTPException(404, "trabalho não existe")
    estado = perdido(c.id, job, estado)
    # quem está esperando precisa saber que está esperando, e quanto
    if estado.get("status") == "na fila" and hasattr(FILA, "espera"):
        fila = FILA.espera(estado.get("id_na_fila") or "")
        if fila:
            estado = {**estado, "fila": fila}
    # o relógio do servidor vai junto: a tela estima o que falta comparando com
    # `inicio`, e sem isso a conta erra pelo tanto que os dois relógios diferem
    from time import time
    return {"job": job, **estado, "agora": time(),
            "entregas": trabalhos.entregas(c.id, job)}


# quanto tempo de silêncio conta como queda. O passo mais longo medido é o
# fundo generativo, que espera o serviço responder; o dobro dele dá folga sem
# deixar ninguém olhando para uma tela parada por meia hora
SILENCIO_DEMAIS = int(os.environ.get("REPLICAI_SILENCIO_SEG", 900))


def _parou_no_relogio(estado: dict) -> str:
    """O trabalho parou de dar sinal? Devolve o motivo, ou vazio."""
    from datetime import datetime, timezone
    bruto = estado.get("atualizado")
    if not bruto:
        return ""
    try:
        quando = datetime.fromisoformat(bruto)
    except ValueError:
        return ""
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    quieto = (datetime.now(timezone.utc) - quando).total_seconds()
    if quieto < SILENCIO_DEMAIS:
        return ""
    p = estado.get("progresso") or {}
    onde = f" em \"{p.get('etapa')}\"" if p.get("etapa") else ""
    onde += f", no formato {p['formato']}" if p.get("formato") else ""
    return (f"o trabalho parou de dar sinal{onde} há {int(quieto // 60)} minutos. "
            f"Provavelmente o servidor reiniciou no meio. As peças que já saíram "
            f"continuam aqui; mande de novo para refazer o resto")


def perdido(conta: str, job: str, estado: dict) -> dict:
    """Trabalho que a fila perdeu não pode ficar esperando para sempre.

    O worker pode morrer entre tirar o trabalho da fila e começar a gravar
    estado — num desligamento, num estouro de memória. O arquivo fica em "na
    fila" e, de fora, isso é indistinguível de uma fila comprida. Aconteceu
    duas vezes aqui, e levou meia hora para eu entender que não era lentidão.
    """
    if estado.get("status") not in ("na fila", "rodando"):
        return estado

    # Sem fila de verdade o trabalho roda DENTRO da api, e aí não há vaga para
    # perguntar: se o processo cai — um reinício, um erro fatal —, o estado
    # fica "rodando" para sempre e a tela diz "Replicando" com nada
    # acontecendo. Aqui o relógio é a testemunha: o passo a passo grava a cada
    # etapa, então silêncio longo é queda, não lentidão.
    parado = _parou_no_relogio(estado)
    if parado:
        novo = {"status": "erro", "erro": parado, "progresso": None}
        trabalhos.gravar(conta, job, novo)
        return {**estado, **novo}

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


def para_entregar(estado: dict, itens: list[dict]) -> list[dict]:
    """Só as peças, não a oficina.

    A pasta do trabalho guarda a arte original, o fundo preparado, cada recorte
    de letra do PSD e as assinaturas de cada fundo. Isso é material de
    trabalho: num PSD de 60 MB o pacote saía com 118 MB e 88 arquivos, e quem
    pediu duas peças tinha de garimpar as duas no meio.
    """
    prontas = list(estado.get("prontas") or [])
    # o PDF entra: é ele que se manda para o cliente aprovar, e sem ele o
    # pacote volta a ser oito arquivos soltos para quem recebe adivinhar
    quero = {f"{fid}.png" for fid in prontas} | {"apresentacao.pdf"}
    fica = []
    for it in itens:
        nome = it["nome"]
        if nome in quero or (nome.startswith("video/") and nome.endswith((".mp4", ".webm"))):
            fica.append(it)
    return fica or itens          # nada reconhecido: melhor tudo do que nada


@app.get("/jobs/{job}/zip")
def zip_do_trabalho(job: str, c: contas.Conta = Depends(quem_e)):
    """As peças num arquivo só. Baixar peça por peça é o que mais irrita quem
    entrega para cliente, e são oito, dez arquivos por campanha."""
    try:
        pasta = trabalhos.pasta_do(c.id, job)
        estado = trabalhos.ler(c.id, job) or {}
    except ValueError:
        raise HTTPException(400, "identificador inválido")
    itens = para_entregar(estado, trabalhos.entregas(c.id, job))
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
def baixar(job: str, nome: str, c: contas.Conta = Depends(quem_e)):
    try:
        pasta = trabalhos.pasta_do(c.id, job)
    except ValueError:
        raise HTTPException(400, "identificador inválido")
    alvo = (pasta / nome).resolve()
    if not str(alvo).startswith(str(pasta)) or not alvo.is_file():
        raise HTTPException(404, "arquivo não existe neste trabalho")
    return FileResponse(alvo, filename=alvo.name)
