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

# só PSD entrega camadas. JPEG, PNG e PDF chegam achatados: uma imagem só
EM_CAMADAS = {".psd", ".psb"}


def modo_possivel(modo: str, ext: str) -> str:
    """O modo que ESTA arte comporta. Sem camadas, só adaptação de formato.

    "Ajustes" promete mover a foto, o logo e o texto separados. Numa imagem
    achatada não há o que mover: a peça sai idêntica à do primeiro modo e o
    editor abre sem nada dentro.

    "Novos Textos" ainda caberia — ele escreve na faixa que o reenquadramento
    abriu ao lado, sem tocar na arte. Mas é justamente nessa peça que não há
    como corrigir o que foi escrito: sem camadas o editor não abre, e a chamada
    sai onde a régua pôs, na fonte que ela escolheu, para sempre. Texto que não
    dá para ajustar depois é pior do que texto nenhum.

    Então a arte achatada tem um modo só, e ele é 100% dela: o quadro muda, o
    conteúdo não.
    """
    if (ext or "").lower() in EM_CAMADAS:
        return modo
    return SO_FORMATO


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


def previas(conta: str, job: str, arte: str) -> None:
    """Compõe a prévia de cada prancheta de um PSD que tem várias.

    Vai para a fila em vez de entrar na resposta do envio: a lista de
    pranchetas tem que aparecer na hora, e as imagens chegam atrás, uma por
    uma. São segundos por prancheta, contra os minutos da extração.
    """
    from api import psd
    try:
        feitas = psd.previa_das_pranchetas(Path(arte), trabalhos.pasta_do(conta, job))
    except Exception:
        return                        # sem prévia a escolha ainda acontece
    estado = trabalhos.ler(conta, job) or {}
    lista = estado.get("pranchetas") or []
    por_nome = {f["nome"]: f["previa"] for f in feitas}
    # pelo nome, e não pela ordem: se a pessoa já escolheu, o estado mudou
    # embaixo e sobrescrever a lista inteira apagaria a escolha
    trabalhos.gravar(conta, job, {"pranchetas": [
        {**p, "previa": por_nome.get(p.get("nome"), p.get("previa", ""))}
        for p in lista]})


def _fonte_da_conta(conta: str, pasta):
    """Como a esteira resolve a fonte que o PSD pede.

    O PSD diz o nome — "FuturaICG-Bold" — e não leva o arquivo dentro. Se a
    conta já enviou essa fonte, ela é copiada para o trabalho e o texto
    trocado sai na MESMA letra. Se não, sai na letra da casa, e isso tem que
    ser dito: declarar uma família sem ter o arquivo faz o navegador cair numa
    fonte do sistema, calado, e a peça sai com outra tipografia.

    A esteira não conhece conta de propósito — quem sabe disso é esta camada.
    """
    import shutil
    from pathlib import Path

    from api import contas
    from api.pipeline import FAMILIA_PADRAO

    def resolver(pedida: str):
        pedida = (pedida or "").strip()
        if not pedida:
            return FAMILIA_PADRAO, "", ""
        try:
            c = contas.por_id(conta)
            achada = contas.fonte_de(c, pedida) if c else None
        except Exception:
            achada = None
        if not achada:
            return (FAMILIA_PADRAO, "",
                    f"a chamada da arte é {pedida}, e essa fonte não está na sua "
                    f"conta: o texto novo saiu na letra da casa. Envie o arquivo "
                    f"dela em Fontes da marca e replique de novo para sair igual")
        destino = Path(pasta) / achada["nome"]
        if not destino.exists():
            shutil.copy2(contas.pasta_das_fontes(c) / achada["nome"], destino)
        return pedida, achada["nome"], ""

    return resolver


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
                      progresso=contar, final=final,
                      fonte_de=_fonte_da_conta(conta, trabalhos.pasta_do(conta, job)))
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
    from time import time

    from api import animacao
    # `desde` é o relógio do vídeo, e não o da peça parada: a tela estimava o
    # que falta a partir do início da replicação, que às vezes foi ontem
    comecou = time()
    estado = {"status": "rodando", "preset": preset, "formatos": formatos,
              "desde": comecou, "prontos": [], "feito": 0, "total": len(formatos)}
    trabalhos.gravar(conta, job, {"video": estado})

    def andando(p: dict) -> None:
        # a cada passo, como na esteira da peça: sem isto a barra do vídeo
        # ficava em zero do começo ao fim e parecia travamento
        trabalhos.gravar(conta, job, {"video": {**estado, **p, "status": "rodando"}})

    try:
        prontos, falhas = animacao.animar(trabalhos.pasta_do(conta, job), formatos,
                                          preset, segundos, progresso=andando)
        acabou = "pronto" if prontos and not falhas else ("parcial" if prontos else "erro")
        for fid in sorted(prontos):
            uso.registrar(conta, uso.VIDEO, job=job, formato=fid, preset=preset)
        trabalhos.gravar(conta, job, {"video": {**estado, "status": acabou,
                                                "prontos": sorted(prontos),
                                                "feito": len(formatos),
                                                "falhas": falhas}})
    except Exception as e:
        trabalhos.gravar(conta, job, {"video": {**estado, "status": "erro", "erro": str(e)}})
        raise



def refazer_fundo(conta: str, job: str, formato: str) -> None:
    """Refaz o fundo de UM formato, insistindo no generativo, e redesenha.

    A ressalva do fundo dizia "vale rodar de novo" e a única saída era
    "Refazer fundos", que mexe no trabalho inteiro e só existe no rodapé
    depois da entrega. Quem viu o problema estava olhando UMA peça: a saída
    tem que estar ali, e valer só para ela.

    O que não dá para consertar aqui é o generativo recusando por credencial
    ou crédito — refazer devolve o mesmo bloco de cor. Por isso a tela só
    oferece este caminho quando a ressalva é de desenho, não de serviço.
    """
    import json

    from api import psd as leitor_psd
    from api.pipeline import _texto_novo, manter_a_mao
    from api.compositor import Compositor
    from motor.replica import formato_by_id, render_peca

    pasta = trabalhos.pasta_do(conta, job)
    estado = trabalhos.ler(conta, job) or {}
    f = formato_by_id(formato)
    if not f:
        raise ValueError(f"formato desconhecido: {formato}")
    arte = pasta / estado.get("arte", "")
    if not arte.exists():
        raise ValueError("a arte deste trabalho não está mais aqui")

    trabalhos.gravar(conta, job, {"ajuste": {"status": "rodando", "formato": formato,
                                             "oque": "fundo"}})
    try:
        leitura = leitor_psd.extrair(arte, pasta,
                                     nome_prancheta=estado.get("prancheta", ""))
        peca = leitor_psd.desdobrar(leitura, f, pasta, final=True)
        info = peca.pop("_fundo", {})
        avisos = list(info.get("avisos") or [])
        if info.get("caiu_para"):
            avisos.append(f"{info['caiu_para']} — o fundo saiu em bloco de cor")
        # a diagramação que a pessoa ajustou à mão não se perde por refazer o
        # fundo: é a mesma regra da exportação final
        avisos += manter_a_mao(peca, pasta, formato)
        arq = pasta / "pecas" / f"{formato}.json"
        arq.write_text(json.dumps(peca, ensure_ascii=False, indent=1), encoding="utf-8")
        render_peca(arq, pasta / (peca.get("saida") or f"{formato}.png"))
    except Exception as e:
        trabalhos.gravar(conta, job, {"ajuste": {"status": "erro", "formato": formato,
                                                 "erro": str(e)}})
        raise

    # os avisos DESTE formato são substituídos, não somados: se o fundo novo
    # saiu limpo, a ressalva tem que sumir — foi o que ela cobrou
    guardados = dict(estado.get("avisos") or {})
    if avisos:
        guardados[formato] = avisos
    else:
        guardados.pop(formato, None)
    trabalhos.gravar(conta, job, {"avisos": guardados})
    _apresentar(conta, job, list((trabalhos.ler(conta, job) or {}).get("prontas") or []))
    trabalhos.gravar(conta, job, {"ajuste": {"status": "pronto", "formato": formato,
                                             "oque": "fundo",
                                             "limpo": not avisos}})


def refazer_peca(conta: str, job: str, formato: str) -> None:
    """Tenta de novo UM formato que não saiu.

    "Tentei adaptar 3 peças e uma não foi. Numa situação como esta, que não
    deveria acontecer mas pode, deveria ter um botão de gerar novamente."

    Falha de peça quase nunca é da peça: é o navegador que demorou demais
    porque a máquina estava ocupada, ou um passo que não respondeu. Refazer o
    trabalho inteiro para recuperar uma peça é pagar o PSD de novo e esperar
    tudo outra vez — e as outras duas já estavam prontas.

    O que sai daqui é somado ao trabalho, não escrito por cima: as peças que
    já tinham saído continuam onde estão.
    """
    pasta = trabalhos.pasta_do(conta, job)
    estado = trabalhos.ler(conta, job) or {}
    arte = pasta / estado.get("arte", "")
    if not arte.exists():
        raise ValueError("a arte deste trabalho não está mais aqui")

    trabalhos.gravar(conta, job, {"ajuste": {"status": "rodando", "formato": formato,
                                             "oque": "peça"}})
    try:
        r = desdobrar(arte, [formato],
                      compositor(str(arte), estado.get("headline", ""),
                                 estado.get("cta", ""), estado.get("modo", MODO_PADRAO)),
                      pasta, estado.get("brief", ""), leitor(),
                      estado.get("prancheta", ""), final=bool(estado.get("final")),
                      fonte_de=_fonte_da_conta(conta, pasta))
    except Exception as e:
        trabalhos.gravar(conta, job, {"ajuste": {"status": "erro", "formato": formato,
                                                 "oque": "peça", "erro": str(e)}})
        raise

    prontas = sorted(set(estado.get("prontas") or []) | set(r.prontas))
    falhas = {k: v for k, v in (estado.get("falhas") or {}).items() if k != formato}
    falhas.update(r.falhas)
    avisos = dict(estado.get("avisos") or {})
    avisos.pop(formato, None)
    avisos.update(r.avisos)
    avisos.update(_contar(conta, job, r))
    descartados = dict(estado.get("descartados") or {})
    descartados.pop(formato, None)
    descartados.update(r.descartados)
    if r.prontas:
        _apresentar(conta, job, prontas)
    trabalhos.gravar(conta, job, {
        "status": "pronto" if not falhas else "parcial",
        "prontas": prontas, "falhas": falhas, "avisos": avisos,
        "descartados": descartados})
    # `desdobrar` deixou um `resultado.json` só deste formato: o registro do
    # trabalho é o trabalho inteiro, e foi dele que saiu a recuperação de um
    # estado perdido uma vez
    import json
    (pasta / "resultado.json").write_text(json.dumps({
        "status": "pronto" if not falhas else "parcial",
        "prontas": {k: str(pasta / f"{k}.png") for k in prontas},
        "falhas": falhas, "avisos": avisos, "descartados": descartados,
        "psd": estado.get("psd") or r.psd, "generativo": r.generativo,
        "custo": r.custo}, ensure_ascii=False, indent=1), encoding="utf-8")
    trabalhos.gravar(conta, job, {"ajuste": {"status": "pronto", "formato": formato,
                                             "oque": "peça",
                                             "saiu": formato in r.prontas}})


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
