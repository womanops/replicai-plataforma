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

from api import contraste, custo, fundo as prep_fundo
from api.compositor import ComposicaoImpossivel, Compositor, Terreno
from motor.replica import formato_by_id
from api.qualidade import conferir_fundo, recorte_e_retangulo
from motor.replica import render_peca


@dataclass
class Resultado:
    pasta: Path
    prontas: dict[str, Path] = field(default_factory=dict)
    falhas: dict[str, str] = field(default_factory=dict)
    avisos: dict[str, list[str]] = field(default_factory=dict)
    descartados: dict[str, dict] = field(default_factory=dict)
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
              pasta: Path, brief: str = "", leitor=None) -> Resultado:
    """Compõe e renderiza cada formato pedido dentro de `pasta`.

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
    with custo.medir() as conta:
        # a leitura é uma chamada por trabalho, não por formato: é a arte que
        # está sendo lida, e ela é a mesma para todos
        leitura = leitor(copia) if leitor else None
        _compor_e_render(r, formatos, compositor, copia, pasta, brief, leitura)
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


def _terreno(copia: Path, fid: str, pasta: Path, leitura) -> tuple[Terreno | None, str]:
    """O fundo do formato e o espaço que ele deixou. Sem leitura, sem terreno:
    quem compõe volta ao comportamento antigo em vez de receber meia verdade."""
    f = formato_by_id(fid)
    if not f or leitura is None:
        return None, ""
    from PIL import Image
    with Image.open(copia) as im:
        tinta = leitura.em_pixels(*im.size)
    info = prep_fundo.preparar(copia, f, tinta, pasta / f"fundo-{fid}.png")
    aviso = ""
    if info["protect_box"]:
        s, x0, y0, x1, y1 = f["safe"], *info["protect_box"]
        if (x0 < s["left"] or y0 < s["top"]
                or x1 > f["w"] - s["right"] or y1 > f["h"] - s["bottom"]):
            aviso = ("o texto da arte encosta na área que o app recorta: num aparelho "
                     "menor pode aparecer cortado")
    return Terreno(fundo={"tipo": "imagem", "src": info["src"], "fit": "cover"},
                   livres=prep_fundo.espaco_livre(f, info["protect_box"]),
                   ja_escrito=list(leitura.frases),
                   fontes=_fonte_do_trabalho(pasta)), aviso


def _compor_e_render(r: Resultado, formatos, compositor, copia: Path, pasta: Path,
                     brief: str, leitura=None) -> None:
    for fid in formatos:
        try:
            terreno, aviso = _terreno(copia, fid, pasta, leitura)
        except Exception as e:
            # fundo que não sai é falha do formato, não do trabalho inteiro
            r.falhas[fid] = f"o fundo não saiu: {e}"
            continue
        if aviso:
            r.avisos.setdefault(fid, []).append(aviso)
        try:
            # caminho completo, não o nome: o compositor do modelo precisa
            # abrir o arquivo para mandar a arte junto. Com o nome curto ele
            # compunha às cegas, só pelo brief, e nada denunciava isso.
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
        try:
            render_peca(arq, destino)
        except Exception as e:
            # o motor levanta RuntimeError quando o Chrome não gera o PNG; vale
            # guardar o texto, que costuma trazer o erro do próprio navegador
            r.falhas[fid] = f"não renderizou: {e}"
            continue
        r.prontas[fid] = destino
