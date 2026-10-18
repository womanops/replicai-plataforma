"""A esteira de um job: arte aprovada entra, peças saem.

Não depende de quem compõe. O compositor é recebido de fora, então esta esteira
já vale para os três caminhos em aberto no `docs/DECISAO-quem-compoe.md`.

Um formato que falha não derruba os outros: o job entrega o que deu e diz o que
não deu. Entregar seis de oito peças com a lista do que faltou é melhor do que
não entregar nada, e muito melhor do que entregar oito com duas erradas.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from api import (contraste, custo, fundo as prep_fundo, psd as leitor_psd,
                 sobreposicao, sossego)
from api.compositor import ComposicaoImpossivel, Compositor, Terreno
from PIL import Image

from motor.replica import formato_by_id
from api.qualidade import conferir_fundo, recorte_e_retangulo
from motor.replica import render_peca


PSD = {".psd", ".psb"}


@dataclass
class Resultado:
    pasta: Path
    prontas: dict[str, Path] = field(default_factory=dict)
    falhas: dict[str, str] = field(default_factory=dict)
    avisos: dict[str, list[str]] = field(default_factory=dict)
    descartados: dict[str, dict] = field(default_factory=dict)
    psd: dict = field(default_factory=dict)       # prancheta usada e camadas soltas
    generativo: int = 0                           # chamadas ao fundo generativo
    custo: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.prontas and not self.falhas:
            return "pronto"
        if self.prontas:
            return "parcial"
        return "erro"

    def avisar(self, fid: str, msg: str) -> None:
        """Guarda a ressalva, uma vez.

        A esteira passa por várias réguas e mais de uma chega à mesma conclusão
        sobre a mesma peça. Repetida, a ressalva vira parede de texto e some o
        que de fato tem que ser olhado.
        """
        linhas = self.avisos.setdefault(fid, [])
        if msg not in linhas:
            linhas.append(msg)

    def para_json(self) -> dict:
        return {
            "status": self.status,
            "prontas": {k: str(v) for k, v in self.prontas.items()},
            "falhas": self.falhas,
            "avisos": self.avisos,
            "descartados": self.descartados,
            "psd": self.psd,
            "generativo": self.generativo,
            "custo": self.custo,
        }


def tirar_imagem_fantasma(peca: dict, pasta: Path) -> list[str]:
    """Remove elemento de imagem cujo `src` não abre.

    O modelo descreve de onde a marca sairia — "recorte do lockup da arte" — e
    isso ia direto para o `src`. O motor então desenhava o quadro vazio do
    arquivo que falta, com borda, no meio da peça. Entregar a peça sem o
    elemento é pior do que com; entregar com o quadro quebrado é pior que as
    duas, porque parece pronto.
    """
    avisos, ficam = [], []
    for e in peca.get("elementos", []):
        if e.get("tipo") != "imagem":
            ficam.append(e)
            continue
        src = (e.get("src") or "").strip()
        caminho = Path(src) if Path(src).is_absolute() else pasta / src
        if src and caminho.exists():
            ficam.append(e)
            continue
        avisos.append(f"`{e.get('papel') or 'imagem'}` não veio recortada no arquivo e "
                      f"saiu da peça, para não virar um quadro vazio")
    peca["elementos"] = ficam
    return avisos


def conferir_peca(peca: dict, pasta: Path, arte: Path) -> list[str]:
    """As regras de qualidade que esta sessão descobriu, aplicadas a cada peça.

    Escrever a verificação e não chamá-la foi o erro que deixou o lettering
    fantasma passar: a regra existia em `api/qualidade.py` e ninguém a usava.
    Por isso ela roda aqui, na esteira, e não à parte.

    Devolve avisos, não erros. A peça é entregue com a ressalva em vez de ser
    barrada: quem decide se o fundo está bom o bastante é quem vai publicar.
    """
    avisos = []
    fundo = (peca.get("fundo") or {}).get("src")
    if fundo:
        caminho = pasta / fundo if not Path(fundo).is_absolute() else Path(fundo)
        if caminho.exists() and caminho.resolve() != Path(arte).resolve():
            try:
                ok, msg = conferir_fundo(arte, caminho)
                if not ok:
                    avisos.append(msg)
            except Exception:
                pass                      # conferência não pode derrubar entrega

    for e in peca.get("elementos", []):
        if e.get("tipo") != "imagem" or (e.get("papel") or "") not in ("marca", "logo", "selo"):
            continue
        src = e.get("src")
        if not src:
            continue
        caminho = pasta / src if not Path(src).is_absolute() else Path(src)
        if not caminho.exists():
            continue
        try:
            if recorte_e_retangulo(caminho):
                avisos.append(
                    f"a marca `{e.get('papel')}` é um bloco opaco: vai aparecer com moldura "
                    f"em volta, porque o fundo que veio no recorte não bate com o da peça. "
                    f"Recorte com transparência")
        except Exception:
            pass

    # a regra de sobreposição: a adaptação não inventa encosto que a arte-mãe
    # não fazia, e texto novo não cai sobre o desenho. Estava escrita no motor
    # desde 09/10/2026 e a esteira nunca a chamava — o mesmo defeito do
    # lettering fantasma, que é o que este arquivo inteiro existe para evitar
    try:
        avisos += sobreposicao.conferir(peca, pasta)
    except Exception:
        pass                          # conferência não pode derrubar entrega
    return avisos


MARCA_DA_MAO = "+mao"


def manter_a_mao(peca: dict, pasta: Path, fid: str) -> list[str]:
    """Devolve à peça recomposta a montagem que a pessoa fez na mão.

    A exportação final refaz o trabalho inteiro — é assim que ela consegue
    insistir no fundo generativo. Refazendo, ela reescrevia a peça por cima do
    ajuste manual: a pessoa movia o CTA, clicava em exportar e o CTA voltava
    para onde o motor o tinha posto, sem nada dizendo por quê.

    O que volta é só a lista de elementos. O fundo é o novo, que é justamente
    o que a exportação final foi buscar.
    """
    arq = pasta / "pecas" / f"{fid}.json"
    if not arq.exists():
        return []
    try:
        antes = json.loads(arq.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if MARCA_DA_MAO not in (antes.get("via") or ""):
        return []
    peca["elementos"] = antes.get("elementos", [])
    peca["via"] = (peca.get("via") or "") + MARCA_DA_MAO
    return ["a montagem que você fez à mão foi mantida; só o fundo foi refeito"]


def desdobrar(base: Path, formatos: list[str], compositor: Compositor,
              pasta: Path, brief: str = "", leitor=None, prancheta: str = "",
              progresso=None, final: bool = False, fonte_de=None) -> Resultado:
    """Compõe e renderiza cada formato pedido dentro de `pasta`.

    `final` liga a insistência com o fundo generativo e reaproveita o que já
    saiu limpo. Chamada de generativo é o item mais caro da peça, e refazer a
    cada rascunho é queimar margem numa versão que vai mudar.

    `progresso(dict)` é chamado a cada passo. Sem ele o trabalho fica minutos
    em "rodando" sem dizer nada, e quem está do outro lado não distingue um
    render demorado de um travamento.

    `fonte_de(nome) -> (familia, aviso)` resolve a fonte que o PSD pede contra
    as fontes da conta. A esteira não conhece conta: quem sabe disso é a
    tarefa, que entrega esta função pronta.

    `leitor(arte) -> Leitura` diz onde a arte já tem tinta e o que ela diz. Com
    ele, o fundo de cada formato é montado antes de qualquer texto: a arte é
    reenquadrada sem cortar a tinta, o que falta de quadro é continuado, e o
    texto novo só entra na faixa que sobrou. Sem ele a esteira segue como
    antes, com a arte crua de fundo — e o texto volta a poder cair em cima.
    """
    base = Path(base)
    pasta = Path(pasta)
    (pasta / "pecas").mkdir(parents=True, exist_ok=True)

    # a arte vira `base.<ext>` na raiz do job: o motor resolve o `src` da peça
    # olhando a pasta dela e a pasta acima, então o caminho na peça é relativo
    # e o job inteiro pode ser movido de máquina sem quebrar
    copia = pasta / f"base{base.suffix.lower()}"
    if base.resolve() != copia.resolve():
        # ligação, não cópia: os dois nomes apontam para o mesmo arquivo em
        # disco. Num PSD de 60 MB a cópia dobrava o trabalho inteiro — 120 dos
        # 131 MB guardados eram a mesma arte duas vezes. Ninguém escreve
        # nesses arquivos depois, então ligar é seguro; apagar um não leva o
        # outro. Entre volumes diferentes `os.link` não funciona, e aí copia.
        copia.unlink(missing_ok=True)
        try:
            os.link(base, copia)
        except OSError:
            shutil.copy2(base, copia)

    r = Resultado(pasta=pasta)
    if copia.suffix.lower() in PSD:
        # PSD tem caminho próprio: as camadas vêm separadas do arquivo, então
        # não há o que perguntar ao modelo sobre onde está a tinta nem o que
        # assar. Entrava achatado antes, e a peça inteira não animava.
        with custo.medir() as conta:
            _psd_e_render(r, formatos, copia, pasta, brief, compositor, prancheta,
                          _passo(progresso, len(formatos), r), final, fonte_de)
        r.custo = conta.resumo()
        (pasta / "resultado.json").write_text(
            json.dumps(r.para_json(), ensure_ascii=False, indent=1), encoding="utf-8")
        return r

    with custo.medir() as conta:
        # a leitura é uma chamada por trabalho, não por formato: é a arte que
        # está sendo lida, e ela é a mesma para todos
        aviso = _passo(progresso, len(formatos), r)
        preserva = getattr(compositor, "preserva", False)
        leitura = None
        if leitor and not preserva:
            # quem só reenquadra não pergunta nada ao modelo: a arte inteira é
            # protegida e nada é escrito por cima
            aviso("lendo a arte", 0)
            leitura = leitor(copia)
        _compor_e_render(r, formatos, compositor, copia, pasta, brief, leitura, aviso,
                         final)
    # o custo entra mesmo quando o job falha: a chamada que não deu peça
    # foi cobrada igual, e é ela que explica a fatura no fim do mês
    r.custo = conta.resumo()

    (pasta / "resultado.json").write_text(
        json.dumps(r.para_json(), ensure_ascii=False, indent=1), encoding="utf-8")
    return r


FONTE_PADRAO = Path(__file__).resolve().parent.parent / "motor/assets/fontes/grotesk.ttf"
# a família que o trabalho declara: quem desenha é o navegador, e declarar uma
# família sem ter o arquivo faz ele cair numa fonte do sistema, calado
FAMILIA_PADRAO = "PecaSans"


def _fonte_do_trabalho(pasta: Path) -> list[dict]:
    """A fonte vai junto na pasta do trabalho, não por caminho da máquina.

    Sem fonte declarada o navegador cai no padrão dele e a peça sai com a letra
    de sistema — foi o "título com fonte aleatória" da primeira rodada. Google
    Fonts por URL trava o render, então é arquivo local, copiado para o
    trabalho, que assim renderiza em qualquer máquina.
    """
    if not FONTE_PADRAO.exists():
        return []
    destino = pasta / FONTE_PADRAO.name
    if not destino.exists():
        shutil.copy2(FONTE_PADRAO, destino)
    return [{"familia": "PecaSans", "arquivo": destino.name, "peso": "100 900"}]


def _psd_e_render(r: Resultado, formatos, copia: Path, pasta: Path, brief: str,
                  compositor, prancheta: str, avisar=None, final: bool = False,
                  fonte_de=None) -> None:
    """A esteira do PSD: abre em camadas e desdobra cada formato.

    O fundo vem assado pelo próprio Photoshop, as camadas soltas vêm com
    posição, e o lockup acompanha ou se solta do fundo conforme a proporção
    mude pouco ou muito. O que o modelo ainda faz é o texto novo — data,
    local, CTA — no espaço que sobrou.
    """
    avisar = avisar or (lambda *a, **k: None)
    avisar("abrindo o PSD em camadas", 0)
    try:
        leitura = leitor_psd.como_o_arquivo_pede(
            leitor_psd.extrair(copia, pasta, nome_prancheta=prancheta))
    except Exception as e:
        for fid in formatos:
            r.falhas[fid] = f"o PSD não abriu: {e}"
        return

    # as fontes que ESTA arte pede, que não são as da conta: cada peça é de um
    # cliente e pede a fonte dele. Sai de graça da leitura — cada camada de
    # texto já traz o nome que o PSD pediu — e é o que diz, na tela, qual
    # arquivo falta para um texto trocado sair na letra certa
    r.psd = {"prancheta": leitura.escolhida,
             "pranchetas": [p.nome for p in leitura.pranchetas],
             "camadas": [c.nome for c in leitura.camadas],
             "fontes": sorted({c.fonte for c in leitura.camadas if c.fonte}),
             "notas": leitura.ignoradas}
    base_els = leitor_psd.como_elementos(leitura, pasta)
    try:
        na_mae = leitor_psd.cobertura_na_mae(leitura, pasta)
    except Exception:
        na_mae = {}

    for i, fid in enumerate(formatos):
        f = formato_by_id(fid)
        if not f:
            r.falhas[fid] = f"formato desconhecido: {fid}"
            continue
        avisar("preparando o fundo", i, fid)
        try:
            peca = leitor_psd.desdobrar(leitura, f, pasta, final=final)
        except Exception as e:
            r.falhas[fid] = f"não consegui montar esta medida: {e}"
            continue
        info = peca.pop("_fundo", {})
        r.generativo += int(info.get("generativo") or 0)
        for a in info.get("avisos") or []:
            r.avisar(fid, a)
            if not final:
                r.avisar(fid, "na exportação final este fundo é refeito")
        if info.get("caiu_para"):
            r.avisar(fid, f"{info['caiu_para']} — o fundo saiu em bloco de cor")
        # a direção de arte que não veio, ou veio e não passou na régua: a peça
        # sai pela regra e diz que saiu, em vez de parecer decidida
        for d in info.get("desvios") or []:
            r.avisar(fid, d)

        avisar("compondo", i, fid)
        # A CHAMADA QUE ELA ESCREVEU TROCA A DA ARTE. Antes ela era entregue
        # ao modelo como texto a ACRESCENTAR, e numa arte que ocupa a peça
        # inteira não há onde acrescentar: ele recusava dizendo que já havia
        # um texto ali — o texto que era para ser trocado.
        pedida = (getattr(compositor, "headline", "") or "").strip()
        if pedida and not getattr(compositor, "preserva", False):
            for a in trocar_a_chamada(peca, pasta, pedida, fonte_de):
                r.avisar(fid, a)
        for a in _texto_novo(peca, f, pasta, leitura, brief, compositor, info):
            r.avisar(fid, a)
        # A LISTA DO MODELO NÃO VAI PARA A TELA NESTE CAMINHO. Aqui ele não
        # compõe a peça: ele só acrescenta o que falta por cima da arte, e
        # tudo o que ele "deixou de fora" é coisa que JÁ ESTÁ na peça — o
        # nome da campanha, o ano, a frase. Mostrar isso como "ficou de fora"
        # eram cinco linhas dizendo que o que está lá não está. A prosa dele
        # continua servindo de MOTIVO para o que ela pediu e não entrou, que
        # é o que `ficou_de_fora` confere contra a peça de verdade.
        for a in ficou_de_fora(peca, compositor, brief):
            r.avisar(fid, a)
        if final:
            for a in manter_a_mao(peca, pasta, fid):
                r.avisar(fid, a)

        # A LETRA QUE VEIO NO ARQUIVO, contra o fundo que ela pegou. Esta
        # conferência morava só no outro caminho — e é neste que o lockup
        # existe, então ela nunca disparava. Ela MEDE e avisa: o que resolve é
        # o lugar. Pôr uma sombra atrás da letra resolveria a leitura e seria
        # inventar um elemento que a arte-mãe não tem, e isso a casa não faz.
        src_fundo = (peca.get("fundo") or {}).get("src")
        if src_fundo:
            for a in contraste.do_lockup(peca, pasta / src_fundo, pasta):
                r.avisar(fid, a)

        # a mesma régua do outro caminho: o PSD não passa por `conferir_peca`,
        # e foi por aí que a peça com a chamada escrita em cima da foto saiu.
        # Com PSD dá para saber o que a arte-mãe já cobria, e aí a régua é a
        # da casa: não mais do que ela fazia naquele mesmo par
        for a in sobreposicao.conferir(peca, pasta, permitido=na_mae):
            r.avisar(fid, a)

        peca.pop("_chamada_explicada", None)
        arq = pasta / "pecas" / f"{fid}.json"
        arq.write_text(json.dumps(peca, ensure_ascii=False, indent=1), encoding="utf-8")
        destino = pasta / (peca.get("saida") or f"{fid}.png")
        avisar("desenhando", i, fid)
        try:
            render_peca(arq, destino)
        except Exception as e:
            r.falhas[fid] = f"não renderizou: {e}"
            continue
        r.prontas[fid] = destino
        avisar("pronta", i + 1, fid)


def _letras(texto: str) -> str:
    """Só as letras e os números, sem acento nem caixa: é o que permite dizer
    se a frase pedida está na peça sem tropeçar em pontuação."""
    import unicodedata
    cru = unicodedata.normalize("NFD", texto or "").lower()
    return "".join(c for c in cru if c.isalnum())


def _porque(descartados: dict, pedido: str) -> str:
    """A explicação do modelo para ter deixado `pedido` de fora."""
    palavras = [w for w in (pedido or "").split() if len(w) >= 4]
    chave = _letras(max(palavras, key=len)) if palavras else ""
    if not chave:
        return ""
    for o_que, por_que in (descartados or {}).items():
        if chave in _letras(f"{o_que} {por_que}"):
            return por_que
    return ""


def ficou_de_fora(peca: dict, compositor, brief: str) -> list[str]:
    """O que a pessoa escreveu e a peça não trouxe.

    O modelo explica em `descartados` cada coisa que deixou de fora, e essa
    explicação é metade da entrega. Ela ficava gravada no JSON da montagem e
    não chegava a lugar nenhum: a peça saiu com "Chegamos a Porto Belo", que é
    o que está impresso na arte, enquanto a chamada pedida dizia "São Paulo" —
    e o pedido de tirar o mascote nem podia ser atendido por aqui. Nada disso
    apareceu na tela. Entregar diferente do que foi pedido sem dizer é o pior
    jeito de errar: parece que funcionou.
    """
    descartados = peca.get("descartados") or {}
    escrito = " ".join(_letras(e.get("texto") or "")
                       for e in peca.get("elementos", []))
    avisos = []
    for rotulo, pedido in (("A chamada que você escreveu", getattr(compositor, "headline", "")),
                           ("O botão que você escreveu", getattr(compositor, "cta", ""))):
        pedido = (pedido or "").strip()
        if not pedido or _letras(pedido) in escrito:
            continue
        # a troca da linha da arte já explicou, e com mais precisão: duas
        # frases diferentes para o mesmo fato é a folha deixando de ser lida
        if rotulo.startswith("A chamada") and peca.get("_chamada_explicada"):
            continue
        porque = _porque(descartados, pedido)
        avisos.append(f"{rotulo} — \"{pedido}\" — não entrou na peça"
                      + (f": {porque}" if porque else "."))
    if (brief or "").strip():
        porque = _porque(descartados, brief)
        if porque:
            avisos.append(f"O ajuste que você pediu não foi aplicado: {porque}")
    return avisos


def cor_da_linha(caminhos: list[Path]) -> str:
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
        if not px or len(px) <= quanto:
            continue
        quanto, n = len(px), len(px)
        melhor = "#%02X%02X%02X" % (sum(p[0] for p in px) // n,
                                    sum(p[1] for p in px) // n,
                                    sum(p[2] for p in px) // n)
    return melhor or "#FFFFFF"


# o sufixo que o Photoshop gruda na camada duplicada, e que não é palavra da
# frase: "Energia que impulsiona o futuro. copiar"
_DO_PHOTOSHOP = ("copiar", "copia", "cópia", "copy")


def _palavras(nome: str) -> int:
    return len([p for p in (nome or "").split()
                if p.strip().lower().strip(".") not in _DO_PHOTOSHOP])


def linha_da_mensagem(elementos: list[dict]):
    """Qual linha da arte a chamada nova substitui.

    "A logo de energiza deveria permanecer e a frase energia que impulsiona o
    futuro sair."

    O nome da campanha é LETTERING: ele se repete em toda a campanha, é
    identidade e não mensagem — numa arte de PSD ele chega como camada de
    texto igual às outras, e por ser a maior virava `headline`. O que muda de
    peça para peça é a FRASE. Entre uma palavra e uma frase, a frase é a
    mensagem; empatando, a maior.

    Devolve os pedaços da linha escolhida, ou `[]` quando a arte não tem
    frase nenhuma — aí não há o que trocar, e inventar seria cobrir a
    assinatura da campanha.
    """
    grupos: dict = {}
    for e in elementos:
        if e.get("papel") not in ("headline", "apoio"):
            continue
        grupos.setdefault(e.get("camada") or e.get("de") or id(e), []).append(e)
    if not grupos:
        return []

    def nota(pedacos):
        nome = next((p.get("conteudo") for p in pedacos if p.get("conteudo")), "") \
            or pedacos[0].get("camada") or pedacos[0].get("de") or ""
        area = sum(p["box"]["w"] * p["box"]["h"] for p in pedacos)
        return (_palavras(nome), area)

    melhor = max(grupos.values(), key=nota)
    return melhor if nota(melhor)[0] > 1 else []


def trocar_a_chamada(peca: dict, pasta: Path, texto: str, fonte_de=None) -> list[str]:
    """A chamada que ela escreveu SUBSTITUI a da arte.

    "Adaptação + Novos Textos" é a opção de TROCAR o texto. O que acontecia
    era outra coisa: a chamada nova era entregue ao modelo para ACRESCENTAR
    num espaço livre, e numa arte que ocupa a peça inteira não há espaço
    livre. Ele recusava dizendo que já havia um texto ali — que é exatamente
    o texto que era para ser trocado. De fora, a opção não fazia nada.

    A linha da arte é uma imagem por letra, então trocar não é editar PNG: é
    desenhar a frase nova na caixa da linha inteira, com a cor que ela tinha.
    A mesma mecânica do ✎ da tela de ajuste.
    """
    if not (texto or "").strip():
        return []
    alvos = linha_da_mensagem(peca.get("elementos", []))
    if not alvos:
        peca["_chamada_explicada"] = True
        return ["a chamada que você escreveu não entrou: nesta medida a arte não "
                "tem linha de frase para trocar, só a assinatura da campanha"]
    papel = alvos[0].get("papel") or "apoio"
    onde = peca["elementos"].index(alvos[0])
    caixa = {"x": min(e["box"]["x"] for e in alvos),
             "y": min(e["box"]["y"] for e in alvos),
             "w": max(e["box"]["x"] + e["box"]["w"] for e in alvos)
                  - min(e["box"]["x"] for e in alvos),
             "h": max(e["box"]["y"] + e["box"]["h"] for e in alvos)
                  - min(e["box"]["y"] for e in alvos)}
    # QUANTAS LINHAS A CHAMADA DA ARTE TINHA. Uma linha continua uma linha: a
    # frase nova quebrando em duas desceu por cima da tagline, porque a caixa
    # da chamada é a do lettering inteiro — alta o bastante para caber o
    # descendente do "g" — e o que mora logo abaixo dela está a poucos pixels.
    # Encolher a letra para caber numa linha preserva a diagramação da mãe;
    # quebrar em duas inventa uma composição que ela não tem.
    miudo = min(e["box"]["h"] for e in alvos) or 1
    linhas: list[list[dict]] = []
    for e in sorted(alvos, key=lambda e: e["box"]["y"]):
        if linhas and e["box"]["y"] - linhas[-1][0]["box"]["y"] <= miudo * 0.6:
            linhas[-1].append(e)
        else:
            linhas.append([e])

    # COMO A LINHA ESTAVA ALINHADA, medido nas linhas dela: duas que começam
    # no mesmo x são alinhadas à esquerda; que terminam no mesmo x, à
    # direita. A frase da arte dela começava as duas linhas em x=35 e a troca
    # saía centrada — o bloco inteiro mudava de lugar. Com uma linha só não
    # há com que comparar, e centrar na própria caixa mantém o bloco onde ele
    # estava.
    if len(linhas) < 2:
        alinha = "center"
    else:
        cantos = [(min(e["box"]["x"] for e in l),
                   max(e["box"]["x"] + e["box"]["w"] for e in l),
                   (min(e["box"]["x"] for e in l)
                    + max(e["box"]["x"] + e["box"]["w"] for e in l)) / 2) for l in linhas]
        espalha = lambda i: max(c[i] for c in cantos) - min(c[i] for c in cantos)
        alinha = min((("left", 0), ("right", 1), ("center", 2)),
                     key=lambda a: espalha(a[1]))[0]
    pedida = next((e.get("fonte_mae") for e in alvos if e.get("fonte_mae")), "")
    familia, arquivo, aviso = (fonte_de or (lambda _: (FAMILIA_PADRAO, "", "")))(pedida)
    alto = max(8, int(caixa["h"]))
    novo = {"tipo": "texto", "papel": papel, "texto": texto.strip(),
            "camada": alvos[0].get("camada"), "box": caixa,
            "fonte": familia, "peso": 600,
            "cor": cor_da_linha([pasta / e["src"] for e in alvos if e.get("src")]),
            "min": 8, "max": alto, "lineHeight": 1.05,
            # sem quebra quando a mãe tinha uma linha só: o motor encolhe a
            # letra até a frase caber na largura, em vez de descer para a
            # linha de baixo e cobrir o que estava lá
            "quebra": len(linhas) > 1,
            "align": alinha, "valign": "middle", "trocado": True}
    fora = {id(e) for e in alvos}
    peca["elementos"] = ([e for e in peca["elementos"][:onde] if id(e) not in fora]
                         + [novo]
                         + [e for e in peca["elementos"][onde:] if id(e) not in fora])
    # a família tem que ir DECLARADA COM ARQUIVO: declarar sem o arquivo faz o
    # navegador cair numa fonte do sistema sem dizer nada, e a peça sai com
    # outra tipografia — o erro mais difícil de ver no olho
    declaradas = {f["familia"]: f for f in (peca.get("fontes") or [])}
    for f in _fonte_do_trabalho(pasta):
        declaradas.setdefault(f["familia"], f)
    if arquivo:
        declaradas[familia] = {"familia": familia, "arquivo": arquivo, "peso": "100 900"}
    peca["fontes"] = list(declaradas.values())
    return [aviso] if aviso else []


def _texto_novo(peca: dict, formato: dict, pasta: Path, leitura, brief: str,
                compositor, info: dict) -> list[str]:
    """Acrescenta à peça do PSD o que o brief pede e a arte não diz.

    O lockup já está na peça, vindo do arquivo. O que falta é o que muda de
    campanha para campanha — data, local, CTA — e isso entra no espaço livre.

    Numa peça recomposta, livre não é só "fora do lockup": a arte ocupa uma
    faixa própria, e escrever ali cobre o assunto. Sem essa conta a data caiu
    em cima da chama — e a rede de segurança do sossego, ao descartar as duas
    faixas, devolveu a peça inteira e piorou.
    """
    if compositor is None or getattr(compositor, "preserva", False):
        return []
    caixas = [e["box"] for e in peca["elementos"]]
    if not caixas:
        return []
    tinta = [min(b["x"] for b in caixas), min(b["y"] for b in caixas),
             max(b["x"] + b["w"] for b in caixas), max(b["y"] + b["h"] for b in caixas)]
    if peca.get("via") == "psd-recompor" and info.get("base_box"):
        arte = info["base_box"]
        tinta = [min(tinta[0], arte[0]), min(tinta[1], arte[1]),
                 max(tinta[2], arte[2]), max(tinta[3], arte[3])]
    livres = prep_fundo.espaco_livre(formato, tinta)
    with Image.open(pasta / peca["fundo"]["src"]) as pronto:
        livres, _ = sossego.acalmar(pronto.convert("RGB"), livres)
    # o que a peça já diz AGORA: a chamada trocada entra aqui, senão o modelo
    # acrescentaria de novo a frase que acabou de substituir a da arte
    ja = [c.texto for c in leitura.camadas if c.texto]
    ja += [e["texto"] for e in peca.get("elementos", [])
           if e.get("trocado") and e.get("texto")]
    terreno = Terreno(fundo=peca["fundo"], livres=livres,
                      ja_escrito=ja,
                      fontes=_fonte_do_trabalho(pasta), tinta=tinta)
    # o que o modelo OLHA. Era o fundo assado — e num PSD cujas camadas vêm
    # todas soltas esse fundo é a prancheta vazia: ele recebia uma imagem
    # branca e decidia em cima dela ("a imagem recebida aparece totalmente
    # branca, sem texto nem logo visível", escreveu ele mesmo). A arte-mãe é
    # a prancheta composta, com texto e logo: é o que a pessoa aprovou.
    olha = pasta / "arte-mae.png"
    if not olha.exists():
        olha = pasta / leitura.fundo
    try:
        extra = compositor.compor(olha, formato["id"], brief, terreno)
    except ComposicaoImpossivel as e:
        # Com a chamada já trocada na arte e nada mais a escrever, "nada foi
        # acrescentado à peça" não é notícia — é o modelo concordando que não
        # havia o que acrescentar. Dito assim, logo abaixo de uma troca que
        # deu certo, lê-se como "ignorei o seu texto".
        pendente = ((getattr(compositor, "cta", "") or "").strip()
                    or (brief or "").strip()
                    or not any(e.get("trocado") for e in peca.get("elementos", [])))
        return [f"nada foi acrescentado à peça: {e}"] if pendente else []

    # queda calada já entregou peça de régua com cara de peça do modelo uma
    # vez; aqui ela voltou no caminho novo, e o CTA saiu sem botão
    avisos = [f"o texto novo saiu pela régua, não pelo modelo — {d}"
              for d in extra.pop("_desvios", [])]
    novos = [e for e in extra.get("elementos", []) if e.get("tipo") in ("texto", "botao")]
    peca["elementos"].extend(novos)
    # junta, não substitui: a chamada trocada já declarou a fonte da marca, e
    # sobrescrever aqui faria aquela linha sair na letra errada
    declaradas = {f["familia"]: f for f in (peca.get("fontes") or [])}
    for f in extra.get("fontes") or []:
        declaradas.setdefault(f["familia"], f)
    peca["fontes"] = list(declaradas.values())
    if extra.get("descartados"):
        peca["descartados"] = extra["descartados"]
    return avisos


def _terreno(copia: Path, fid: str, pasta: Path, leitura,
             final: bool = False, preserva: bool = False) -> tuple[Terreno | None, list[str], int]:
    """O fundo do formato e o espaço que ele deixou. Sem leitura, sem terreno:
    quem compõe volta ao comportamento antigo em vez de receber meia verdade.

    Devolve lista de avisos, não um só: fundo que caiu e tinta encostando na
    margem são problemas independentes, e com uma variável só o segundo
    apagava o primeiro.
    """
    f = formato_by_id(fid)
    if not f or (leitura is None and not preserva):
        return None, [], 0
    from PIL import Image
    with Image.open(copia) as im:
        # quem só reenquadra protege a arte inteira: não há o que perguntar ao
        # modelo sobre onde está a tinta quando nada vai ser escrito por cima.
        # É o que torna esse modo de graça, e certo por construção.
        tinta = leitura.em_pixels(*im.size) if leitura is not None else [0, 0, *im.size]
    info = prep_fundo.preparar(copia, f, tinta, pasta / f"fundo-{fid}.png",
                               insistir=final, reaproveitar=final)

    livres = prep_fundo.espaco_livre(f, info["protect_box"])
    with Image.open(info["caminho"]) as pronto:
        # ter espaço não é ter lugar: a faixa é aparada ao pedaço de fundo
        # quieto, senão o texto entra por cima do desenho e some nele
        livres, notas = sossego.acalmar(pronto.convert("RGB"), livres)

    avisos = list(notas) + list(info.get("avisos") or [])
    if info.get("avisos") and not final:
        avisos.append("na exportação final este fundo é refeito")
    if info.get("caiu_para"):
        avisos.append(f"{info['caiu_para']} — o fundo saiu em bloco de cor, que não "
                      f"continua a grade nem a textura da arte. Vale rodar de novo")
    if info["protect_box"]:
        s, x0, y0, x1, y1 = f["safe"], *info["protect_box"]
        if (x0 < s["left"] or y0 < s["top"]
                or x1 > f["w"] - s["right"] or y1 > f["h"] - s["bottom"]):
            avisos.append("o texto encosta na área que o app recorta e pode sair "
                          "cortado. Mova o bloco no ajuste")

    return Terreno(fundo={"tipo": "imagem", "src": info["src"], "fit": "cover"},
                   livres=livres,
                   ja_escrito=list(leitura.frases) if leitura is not None else [],
                   fontes=_fonte_do_trabalho(pasta),
                   tinta=info["protect_box"]), avisos, int(info.get("generativo") or 0)


# o que acontece uma vez só, antes do primeiro formato. Abrir um PSD de 60 MB
# em camadas leva quase um minuto, e esse minuto não se repete por formato
PRELUDIO = ("lendo a arte", "abrindo o PSD em camadas")


def _passo(progresso, total: int, r: "Resultado | None" = None):
    """Avisa quem está esperando. Sem callback, não faz nada — a esteira não
    pode depender de ter alguém ouvindo.

    `desde` marca quando o trabalho por formato começou de verdade. Sem ele a
    tela dividia o tempo de abrir o PSD pelo primeiro pedaço do primeiro
    formato e anunciava catorze minutos num trabalho de um.

    A lista do que já ficou pronto vai junto a cada passo. Sem ela o estado só
    ganhava `prontas` no fim, e as peças apareciam todas de uma vez: quem pediu
    oito formatos ficava minutos olhando quadro vazio com a primeira peça já
    desenhada no disco.
    """
    from time import time
    quando = {"desde": None}

    def avisar(o_que: str, feito: int = 0, formato: str = "") -> None:
        if not progresso:
            return
        if quando["desde"] is None and o_que not in PRELUDIO:
            quando["desde"] = time()
        progresso({"etapa": o_que, "feito": feito, "total": total,
                   "formato": formato, "desde": quando["desde"],
                   "prontas": sorted(r.prontas) if r is not None else []})
    return avisar


def _compor_e_render(r: Resultado, formatos, compositor, copia: Path, pasta: Path,
                     brief: str, leitura=None, avisar=None, final: bool = False) -> None:
    avisar = avisar or (lambda *a, **k: None)
    for i, fid in enumerate(formatos):
        avisar("preparando o fundo", i, fid)
        try:
            terreno, avisos_do_fundo, gastou = _terreno(
                copia, fid, pasta, leitura, final,
                preserva=getattr(compositor, "preserva", False))
            r.generativo += gastou
        except Exception as e:
            # fundo que não sai é falha do formato, não do trabalho inteiro
            r.falhas[fid] = f"não consegui montar esta medida: {e}"
            continue
        for a in avisos_do_fundo:
            r.avisar(fid, a)
        try:
            # caminho completo, não o nome: o compositor do modelo precisa
            # abrir o arquivo para mandar a arte junto. Com o nome curto ele
            # compunha às cegas, só pelo brief, e nada denunciava isso.
            avisar("compondo", i, fid)
            peca = compositor.compor(copia, fid, brief, terreno)
        except ComposicaoImpossivel as e:
            r.falhas[fid] = str(e)
            continue

        # o modelo explica cada coisa que deixou de fora, e essa explicação é
        # metade da entrega: é por ela que se descobre que o brief não deu
        # material para a headline. Guardar e não mostrar foi o erro antigo.
        if peca.get("descartados"):
            r.descartados[fid] = peca["descartados"]
        for a in ficou_de_fora(peca, compositor, brief):
            r.avisar(fid, a)

        for a in tirar_imagem_fantasma(peca, pasta):
            r.avisar(fid, a)

        # a cor do texto se decide contra o fundo que a peça vai usar, não
        # contra o que alguém supôs: branco some no brilho da gota de vidro
        src = (peca.get("fundo") or {}).get("src")
        if src:
            for a in contraste.ajustar(peca, pasta / src):
                r.avisar(fid, a)
            # e a letra que veio no arquivo, que `ajustar` não vê porque é
            # imagem — e cuja cor é do cliente e não se troca
            for a in contraste.do_lockup(peca, pasta / src, pasta):
                r.avisar(fid, a)

        for d in peca.pop("_desvios", []):
            r.avisar(fid, f"composto pela régua, não pelo modelo — {d}")

        for a in conferir_peca(peca, pasta, copia):
            r.avisar(fid, a)
        if final:
            for a in manter_a_mao(peca, pasta, fid):
                r.avisar(fid, a)

        peca.pop("_chamada_explicada", None)
        arq = pasta / "pecas" / f"{fid}.json"
        arq.write_text(json.dumps(peca, ensure_ascii=False, indent=1), encoding="utf-8")
        destino = pasta / (peca.get("saida") or f"{fid}.png")
        avisar("desenhando", i, fid)
        try:
            render_peca(arq, destino)
        except Exception as e:
            # o motor levanta RuntimeError quando o Chrome não gera o PNG; vale
            # guardar o texto, que costuma trazer o erro do próprio navegador
            r.falhas[fid] = f"não renderizou: {e}"
            continue
        r.prontas[fid] = destino
        avisar("pronta", i + 1, fid)
