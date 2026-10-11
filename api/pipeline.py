"""A esteira de um job: arte aprovada entra, peças saem.

Não depende de quem compõe. O compositor é recebido de fora, então esta esteira
já vale para os três caminhos em aberto no `docs/DECISAO-quem-compoe.md`.

Um formato que falha não derruba os outros: o job entrega o que deu e diz o que
não deu. Entregar seis de oito peças com a lista do que faltou é melhor do que
não entregar nada, e muito melhor do que entregar oito com duas erradas.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from api import contraste, custo, fundo as prep_fundo, psd as leitor_psd, sossego
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
        avisos.append(f"`{e.get('papel') or 'imagem'}` saiu da peça: não existe recorte "
                      f"em arquivo para ela, e o motor desenharia um quadro vazio")
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
    return avisos


def desdobrar(base: Path, formatos: list[str], compositor: Compositor,
              pasta: Path, brief: str = "", leitor=None, prancheta: str = "",
              progresso=None, final: bool = False) -> Resultado:
    """Compõe e renderiza cada formato pedido dentro de `pasta`.

    `final` liga a insistência com o fundo generativo e reaproveita o que já
    saiu limpo. Chamada de generativo é o item mais caro da peça, e refazer a
    cada rascunho é queimar margem numa versão que vai mudar.

    `progresso(dict)` é chamado a cada passo. Sem ele o trabalho fica minutos
    em "rodando" sem dizer nada, e quem está do outro lado não distingue um
    render demorado de um travamento.

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
        shutil.copy2(base, copia)

    r = Resultado(pasta=pasta)
    if copia.suffix.lower() in PSD:
        # PSD tem caminho próprio: as camadas vêm separadas do arquivo, então
        # não há o que perguntar ao modelo sobre onde está a tinta nem o que
        # assar. Entrava achatado antes, e a peça inteira não animava.
        with custo.medir() as conta:
            _psd_e_render(r, formatos, copia, pasta, brief, compositor, prancheta,
                          _passo(progresso, len(formatos)), final)
        r.custo = conta.resumo()
        (pasta / "resultado.json").write_text(
            json.dumps(r.para_json(), ensure_ascii=False, indent=1), encoding="utf-8")
        return r

    with custo.medir() as conta:
        # a leitura é uma chamada por trabalho, não por formato: é a arte que
        # está sendo lida, e ela é a mesma para todos
        aviso = _passo(progresso, len(formatos))
        aviso("lendo a arte", 0)
        leitura = leitor(copia) if leitor else None
        _compor_e_render(r, formatos, compositor, copia, pasta, brief, leitura, aviso,
                         final)
    # o custo entra mesmo quando o job falha: a chamada que não deu peça
    # foi cobrada igual, e é ela que explica a fatura no fim do mês
    r.custo = conta.resumo()

    (pasta / "resultado.json").write_text(
        json.dumps(r.para_json(), ensure_ascii=False, indent=1), encoding="utf-8")
    return r


FONTE_PADRAO = Path(__file__).resolve().parent.parent / "motor/assets/fontes/grotesk.ttf"


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
                  compositor, prancheta: str, avisar=None, final: bool = False) -> None:
    """A esteira do PSD: abre em camadas e desdobra cada formato.

    O fundo vem assado pelo próprio Photoshop, as camadas soltas vêm com
    posição, e o lockup acompanha ou se solta do fundo conforme a proporção
    mude pouco ou muito. O que o modelo ainda faz é o texto novo — data,
    local, CTA — no espaço que sobrou.
    """
    avisar = avisar or (lambda *a, **k: None)
    avisar("abrindo o PSD em camadas", 0)
    try:
        leitura = leitor_psd.extrair(copia, pasta, nome_prancheta=prancheta)
    except Exception as e:
        for fid in formatos:
            r.falhas[fid] = f"o PSD não abriu: {e}"
        return

    r.psd = {"prancheta": leitura.escolhida,
             "pranchetas": [p.nome for p in leitura.pranchetas],
             "camadas": [c.nome for c in leitura.camadas],
             "notas": leitura.ignoradas}
    base_els = leitor_psd.como_elementos(leitura, pasta)

    for i, fid in enumerate(formatos):
        f = formato_by_id(fid)
        if not f:
            r.falhas[fid] = f"formato desconhecido: {fid}"
            continue
        avisar("preparando o fundo", i, fid)
        try:
            peca = leitor_psd.desdobrar(leitura, f, pasta, final=final)
        except Exception as e:
            r.falhas[fid] = f"o fundo não saiu: {e}"
            continue
        info = peca.pop("_fundo", {})
        r.generativo += int(info.get("generativo") or 0)
        for a in info.get("avisos") or []:
            r.avisos.setdefault(fid, []).append(a)
            if not final:
                r.avisos.setdefault(fid, []).append(
                    "na exportação final este fundo é refeito")
        if info.get("caiu_para"):
            r.avisos.setdefault(fid, []).append(
                f"{info['caiu_para']} — o fundo saiu em bloco de cor")

        avisar("compondo", i, fid)
        for a in _texto_novo(peca, f, pasta, leitura, brief, compositor, info):
            r.avisos.setdefault(fid, []).append(a)

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
    if compositor is None:
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
    terreno = Terreno(fundo=peca["fundo"], livres=livres,
                      ja_escrito=[c.texto for c in leitura.camadas if c.texto],
                      fontes=_fonte_do_trabalho(pasta), tinta=tinta)
    try:
        # o que o modelo olha é o fundo assado: é a arte de verdade da peça, e
        # o arquivo original é PSD, que ele não abre
        extra = compositor.compor(pasta / leitura.fundo, formato["id"], brief, terreno)
    except ComposicaoImpossivel as e:
        return [f"nada foi acrescentado à peça: {e}"]

    # queda calada já entregou peça de régua com cara de peça do modelo uma
    # vez; aqui ela voltou no caminho novo, e o CTA saiu sem botão
    avisos = [f"o texto novo saiu pela régua, não pelo modelo — {d}"
              for d in extra.pop("_desvios", [])]
    novos = [e for e in extra.get("elementos", []) if e.get("tipo") in ("texto", "botao")]
    peca["elementos"].extend(novos)
    peca["fontes"] = extra.get("fontes") or peca.get("fontes") or []
    if extra.get("descartados"):
        peca["descartados"] = extra["descartados"]
    return avisos


def _terreno(copia: Path, fid: str, pasta: Path, leitura,
             final: bool = False) -> tuple[Terreno | None, list[str], int]:
    """O fundo do formato e o espaço que ele deixou. Sem leitura, sem terreno:
    quem compõe volta ao comportamento antigo em vez de receber meia verdade.

    Devolve lista de avisos, não um só: fundo que caiu e tinta encostando na
    margem são problemas independentes, e com uma variável só o segundo
    apagava o primeiro.
    """
    f = formato_by_id(fid)
    if not f or leitura is None:
        return None, [], 0
    from PIL import Image
    with Image.open(copia) as im:
        tinta = leitura.em_pixels(*im.size)
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
            avisos.append("o texto da arte encosta na área que o app recorta: num "
                          "aparelho menor pode aparecer cortado")

    return Terreno(fundo={"tipo": "imagem", "src": info["src"], "fit": "cover"},
                   livres=livres,
                   ja_escrito=list(leitura.frases),
                   fontes=_fonte_do_trabalho(pasta),
                   tinta=info["protect_box"]), avisos, int(info.get("generativo") or 0)


def _passo(progresso, total: int):
    """Avisa quem está esperando. Sem callback, não faz nada — a esteira não
    pode depender de ter alguém ouvindo."""
    def avisar(o_que: str, feito: int = 0, formato: str = "") -> None:
        if progresso:
            progresso({"etapa": o_que, "feito": feito, "total": total,
                       "formato": formato})
    return avisar


def _compor_e_render(r: Resultado, formatos, compositor, copia: Path, pasta: Path,
                     brief: str, leitura=None, avisar=None, final: bool = False) -> None:
    avisar = avisar or (lambda *a, **k: None)
    for i, fid in enumerate(formatos):
        avisar("preparando o fundo", i, fid)
        try:
            terreno, avisos_do_fundo, gastou = _terreno(copia, fid, pasta, leitura, final)
            r.generativo += gastou
        except Exception as e:
            # fundo que não sai é falha do formato, não do trabalho inteiro
            r.falhas[fid] = f"o fundo não saiu: {e}"
            continue
        for a in avisos_do_fundo:
            r.avisos.setdefault(fid, []).append(a)
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

        for a in tirar_imagem_fantasma(peca, pasta):
            r.avisos.setdefault(fid, []).append(a)

        # a cor do texto se decide contra o fundo que a peça vai usar, não
        # contra o que alguém supôs: branco some no brilho da gota de vidro
        src = (peca.get("fundo") or {}).get("src")
        if src:
            for a in contraste.ajustar(peca, pasta / src):
                r.avisos.setdefault(fid, []).append(a)

        for d in peca.pop("_desvios", []):
            r.avisos.setdefault(fid, []).append(
                f"composto pela régua, não pelo modelo — {d}")

        for a in conferir_peca(peca, pasta, copia):
            r.avisos.setdefault(fid, []).append(a)

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
