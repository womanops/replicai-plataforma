"""O que o worker executa.

Separado do servidor web de propósito: o worker não precisa de FastAPI nem de
rotas para renderizar uma peça, e carregar o aplicativo inteiro num processo
que só desenha é peso sem motivo. Aqui ficam as funções que a fila guarda —
e o que vai para o Redis precisa ser importável do outro lado.
"""
from __future__ import annotations

from pathlib import Path

from api import trabalhos, uso
from api.compositor import (CompositorEmCadeia, CompositorModelo, CompositorPreserva,
                            CompositorSimples)
from api.pipeline import desdobrar

# os três modos de desdobrar, do mais conservador ao mais livre
SO_FORMATO = "sem"       # preserva 100% da peça, só reenquadra
DIAGRAMAR = "com"        # preserva o conteúdo, e a pessoa remonta depois
TEXTO_NOVO = "novo"      # o modelo escreve chamada e CTA no espaço que sobrou
MODOS = (SO_FORMATO, DIAGRAMAR, TEXTO_NOVO)
MODO_PADRAO = DIAGRAMAR


def compositor(arte: str, headline: str, cta: str, modo: str = MODO_PADRAO):
    """Quem compõe, conforme o que foi pedido.

    Nos dois primeiros modos ninguém escreve: a peça é a arte reenquadrada, e
    quem quiser mexer mexe depois, na mão. Escrever sem ser pedido foi como o
    Stories saiu com a chamada duplicada por cima do lettering da arte.

    No terceiro, com credencial, o modelo decide a estrutura e a máquina
    calcula as caixas; a regra determinística fica atrás como rede. Sem
    credencial, só a regra — a plataforma funciona, com menos qualidade, em vez
    de recusar o trabalho.

    A ordem é essa e não o contrário: a regra dá conta do caso fácil, mas não
    sabe o que sacrificar quando o formato aperta, que é o que decide a peça.
    """
    if modo != TEXTO_NOVO:
        return CompositorPreserva()
    from api import modelo
    simples = CompositorSimples(headline=headline, cta=cta)
    if not modelo.disponivel():
        return simples
    pelo_modelo = CompositorModelo(
        modelo.responder_anthropic,
        fundo={"tipo": "imagem", "src": Path(arte).name, "fit": "cover"},
        material=" ".join(x for x in (headline, cta) if x))
    return CompositorEmCadeia(pelo_modelo, simples)


def leitor():
    """Quem lê a arte antes de compor. Sem credencial não há leitura, e a
    esteira cai no comportamento antigo — com a arte crua de fundo.

    Quem só reenquadra nem chega a usar: a esteira pula a leitura quando o
    compositor preserva a peça."""
    from api import modelo
    if not modelo.disponivel():
        return None

    def ler(arte):
        from api.leitura import entender
        return entender(modelo.ler_arte(arte))
    return ler


def _contar(conta: str, job: str, r) -> dict:
    """Anota o que foi entregue, para a fatura.

    Depois de pronto, e não antes: cobrar por peça que falhou é cobrar por
    nada. O que não conseguir ser gravado vira aviso na entrega, porque
    faturamento que some calado é pior do que entrega que falha alto.
    """
    perdidos = []
    for fid in sorted(r.prontas):
        e = uso.registrar(conta, uso.PECA, job=job, formato=fid)
        if not e.get("gravado"):
            perdidos.append(fid)
    if r.custo.get("dolares"):
        uso.registrar(conta, "modelo", job=job, dolares=r.custo["dolares"],
                      chamadas=r.custo.get("chamadas", 0))
    if getattr(r, "generativo", 0):
        uso.registrar(conta, uso.FUNDO, job=job, quantas=r.generativo)
    if not perdidos:
        return {}
    return {"_uso": [f"o consumo de {', '.join(perdidos)} não foi anotado: "
                     f"confira antes de faturar"]}


def _apresentar(conta: str, job: str, prontas: list[str]) -> str:
    """Monta o PDF de apresentação. Devolve o motivo quando não dá.

    Nunca derruba a entrega: as peças já estão no disco e valem sozinhas. Mas
    também não some calado — mandar oito PNGs soltos para o cliente é o que a
    apresentação existe para evitar, e descobrir que ela não saiu só na hora
    de enviar é tarde.
    """
    from api import apresentacao
    estado = trabalhos.ler(conta, job) or {}
    try:
        apresentacao.montar(trabalhos.pasta_do(conta, job),
                            {**estado, "prontas": prontas})
    except Exception as e:
        return f"as peças saíram, mas o PDF de apresentação não: {e}"
    return ""


def processar(conta: str, job: str, arte: str, formatos: list[str], headline: str,
              cta: str, brief: str, prancheta: str = "", final: bool = False,
              modo: str = MODO_PADRAO) -> None:
    """O que o worker executa. Fora da API de propósito: é o pedaço pesado."""
    from time import time
    # o relógio começa aqui, e não quando o trabalho entrou na fila: é com ele
    # que a tela estima quanto falta, e esperar na fila não é progresso
    trabalhos.gravar(conta, job, {"status": "rodando", "final": final,
                                  "modo": modo, "inicio": time()})

    def contar(p: dict) -> None:
        # grava a cada passo: é o que distingue, de fora, um render demorado
        # de um travamento. E a lista do que já saiu vai junto, senão as peças
        # só aparecem na tela quando a última terminar
        trabalhos.gravar(conta, job, {"progresso": p,
                                      "prontas": p.get("prontas") or []})

    try:
        r = desdobrar(Path(arte), formatos, compositor(arte, headline, cta, modo),
                      trabalhos.pasta_do(conta, job), brief, leitor(), prancheta,
                      progresso=contar, final=final)
        avisos = {**r.avisos, **_contar(conta, job, r)}
        if r.prontas:
            contar({"etapa": "montando a apresentação", "feito": len(formatos),
                    "total": len(formatos), "formato": "",
                    "prontas": sorted(r.prontas)})
            falhou = _apresentar(conta, job, sorted(r.prontas))
            if falhou:
                avisos.setdefault("_apresentacao", []).append(falhou)
        trabalhos.gravar(conta, job, {"status": r.status, "progresso": None,
                               "prontas": sorted(r.prontas),
                               "falhas": r.falhas,
                               "avisos": avisos,
                               "descartados": r.descartados,
                               "psd": r.psd,
                               "custo": r.custo})
    except Exception as e:
        # sem isto o trabalho fica "rodando" para sempre e ninguém sabe por quê
        trabalhos.gravar(conta, job, {"status": "erro", "erro": str(e)})
        raise


def processar_video(conta: str, job: str, formatos: list[str], preset: str,
                    segundos: float) -> None:
    """O que o worker executa para animar. Separado de `processar` porque é
    outra ferramenta e outro tempo: a peça parada leva segundos, o vídeo leva
    minutos, e quem quer só a peça não deve esperar pelo vídeo."""
    from api import animacao
    trabalhos.gravar(conta, job, {"video": {"status": "rodando", "preset": preset,
                                            "formatos": formatos}})
    try:
        prontos, falhas = animacao.animar(trabalhos.pasta_do(conta, job), formatos,
                                          preset, segundos)
        estado = "pronto" if prontos and not falhas else ("parcial" if prontos else "erro")
        for fid in sorted(prontos):
            uso.registrar(conta, uso.VIDEO, job=job, formato=fid, preset=preset)
        trabalhos.gravar(conta, job, {"video": {"status": estado, "preset": preset,
                                                "prontos": sorted(prontos),
                                                "falhas": falhas}})
    except Exception as e:
        trabalhos.gravar(conta, job, {"video": {"status": "erro", "erro": str(e)}})
        raise



def redesenhar(conta: str, job: str, formato: str) -> None:
    """Desenha de novo um formato cuja peça foi remontada na mão.

    Não conta consumo: a peça é a mesma, e cobrar duas vezes por mover um
    título seria cobrar a pessoa por discordar da diagramação. O que ela paga
    é a peça produzida, não cada tentativa de deixá-la boa.

    Vai para a fila como qualquer render porque é o Chrome que desenha, e isso
    leva segundos — tempo demais para uma requisição esperar.
    """
    from motor.replica import render_peca
    pasta = trabalhos.pasta_do(conta, job)
    arq = pasta / "pecas" / f"{formato}.json"
    if not arq.exists():
        raise ValueError(f"não existe peça montada para `{formato}`")
    import json
    peca = json.loads(arq.read_text(encoding="utf-8"))
    destino = pasta / (peca.get("saida") or f"{formato}.png")
    trabalhos.gravar(conta, job, {"ajuste": {"status": "rodando", "formato": formato}})
    try:
        render_peca(arq, destino)
    except Exception as e:
        trabalhos.gravar(conta, job, {"ajuste": {"status": "erro", "formato": formato,
                                                 "erro": str(e)}})
        raise
    # o PDF mostrava a peça de antes do ajuste: refazê-lo é o que impede de
    # mandar ao cliente a versão que ela acabou de corrigir
    falhou = _apresentar(conta, job, list((trabalhos.ler(conta, job) or {}).get("prontas") or []))
    trabalhos.gravar(conta, job, {"ajuste": {"status": "pronto", "formato": formato,
                                             **({"aviso": falhou} if falhou else {})}})
