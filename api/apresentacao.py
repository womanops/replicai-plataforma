"""O PDF de apresentação: a capa, a arte-mãe e uma página por formato.

É o que se manda para o cliente aprovar. Mandar oito PNGs soltos obriga quem
recebe a abrir oito arquivos e adivinhar qual é qual; o Studio já entregava
uma apresentação e a plataforma tinha perdido isso.

Página de 1600×900 porque é a proporção de projeção, e o PDF é impresso pelo
mesmo Chrome que desenha as peças — sem dependência nova, e com a mesma
tipografia.
"""
from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path

from motor.replica import _img_data_uri, chrome_run, formato_by_id

# a apresentação é a última coisa do trabalho e não pode segurá-lo: passou
# disto, a entrega sai sem ela e dizendo que saiu
ESPERA = 180

FOLHA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>{titulo}</title>
<style>
  @page {{ size: 1600px 900px; margin: 0; }}
  *{{box-sizing:border-box}}
  body {{ margin:0; font-family:-apple-system,'Helvetica Neue',Helvetica,Arial,sans-serif;
          background:#0E0A0C; color:#F5ECE9; }}
  .folha {{ width:1600px; height:900px; page-break-after:always; display:flex;
            padding:64px 80px; }}
  .capa {{ flex-direction:column; justify-content:flex-end; background:#741B47; }}
  .capa h1 {{ font-size:84px; line-height:.95; margin:0 0 18px; letter-spacing:-.02em; }}
  .capa p {{ font-size:22px; margin:0; color:rgba(245,236,233,.72); }}
  .capa .marca {{ margin-top:40px; font-size:15px; letter-spacing:.3em;
                  text-transform:uppercase; color:rgba(245,236,233,.5); }}
  .peca {{ flex-direction:row; gap:56px; align-items:center; }}
  .peca.mae {{ background:#160F12; }}
  .meta {{ width:320px; flex:none; }}
  .canal {{ font-size:13px; letter-spacing:.2em; text-transform:uppercase;
            color:#E8B4C8; font-weight:700; margin-bottom:14px; }}
  .meta h2 {{ font-size:40px; line-height:1.03; margin:0 0 14px; letter-spacing:-.01em; }}
  .dim {{ font-size:16px; color:rgba(245,236,233,.55); font-variant-numeric:tabular-nums; }}
  .fig {{ flex:1; display:flex; align-items:center; justify-content:center; min-width:0;
          height:100%; }}
  /* o banner de 300×250 aparecia do tamanho natural no meio de uma folha de
     1600px e parecia defeito; ampliado até 3× ele se lê e ainda não borra */
  .fig img {{ width:auto; height:auto; max-width:100%; max-height:772px;
              box-shadow:0 24px 70px rgba(0,0,0,.5); }}
</style></head><body>
<section class="folha capa"><h1>{titulo}</h1><p>{linha}</p>
  <div class="marca">ReplicAI</div></section>
{paginas}
</body></html>"""

PAGINA = """<section class="folha peca{classe}">
  <div class="meta"><div class="canal">{canal}</div><h2>{nome}</h2>
    <div class="dim">{w} × {h}</div></div>
  <div class="fig"><img src="{imagem}" style="{escala}"></div>
</section>"""


# a figura ocupa 1100×772 na folha. Ampliar até 3× deixa o banner pequeno
# legível sem virar borrão; acima disso o pixel aparece
AMPLIA_ATE = 3.0
FIG = (1100, 772)


def _escala(w: int, h: int) -> str:
    """Quanto a peça pode crescer para ocupar a folha."""
    cabe = min(FIG[0] / max(1, w), FIG[1] / max(1, h))
    if cabe <= 1:
        return ""                       # já é maior que a folha: o CSS reduz
    k = min(cabe, AMPLIA_ATE)
    return f"width:{round(w * k)}px;height:{round(h * k)}px"


def _capa_da_mae(pasta: Path, estado: dict) -> Path | None:
    """A arte que entrou. Num PSD o arquivo não abre em navegador nenhum, e o
    que representa a peça original é o fundo assado pelo próprio Photoshop."""
    arte = estado.get("arte") or ""
    if arte and Path(arte).suffix.lower() not in (".psd", ".psb"):
        alvo = pasta / arte
        if alvo.exists():
            return alvo
    # a prancheta inteira, não o `fundo.png`: aquele tem as camadas de texto
    # desligadas, e a página "Peça original" saía sem a chamada
    for nome in ("arte-mae.png", "fundo.png"):
        alvo = pasta / nome
        if alvo.exists():
            return alvo
    return None


def montar(pasta: Path, estado: dict) -> Path:
    """Escreve `apresentacao.pdf` na pasta do trabalho e devolve o caminho."""
    # resolvido: `file://` + caminho relativo faz o Chrome ler a primeira pasta
    # como se fosse o servidor, e ele responde ERR_INVALID_URL
    pasta = Path(pasta).resolve()
    prontas = list(estado.get("prontas") or [])
    paginas = []

    mae = _capa_da_mae(pasta, estado)
    if mae is not None:
        from PIL import Image
        with Image.open(mae) as im:
            w, h = im.size
        paginas.append(PAGINA.format(
            classe=" mae", canal="Arte aprovada", nome="Peça original",
            w=w, h=h, imagem=_img_data_uri(mae, 1400), escala=_escala(w, h)))

    for fid in prontas:
        png = pasta / f"{fid}.png"
        if not png.exists():
            continue
        f = formato_by_id(fid) or {}
        from PIL import Image
        with Image.open(png) as im:
            w, h = im.size
        paginas.append(PAGINA.format(
            classe="", canal=html.escape(f.get("canal") or "Medida livre"),
            nome=html.escape(f.get("nome") or fid), w=w, h=h,
            imagem=_img_data_uri(png, 1400), escala=_escala(w, h)))

    if not paginas:
        raise ValueError("não há peça pronta para montar a apresentação")

    quantas = len(prontas)
    titulo = html.escape(estado.get("titulo") or pasta.name)
    linha = (f"{quantas} peça{'s' if quantas > 1 else ''} · "
             f"{date.today().strftime('%d/%m/%Y')}")
    folha = pasta / "apresentacao.html"
    folha.write_text(FOLHA.format(titulo=titulo, linha=linha, paginas="".join(paginas)),
                     encoding="utf-8")
    pdf = pasta / "apresentacao.pdf"
    if pdf.exists():
        pdf.unlink()
    r = chrome_run(folha.as_uri(),
                   ["--no-pdf-header-footer", f"--print-to-pdf={pdf}"], timeout=ESPERA)
    # o HTML fica: é dele que sai o PDF, e quando o Chrome falha é a única
    # coisa que permite ver o que ele tentou imprimir
    if not pdf.exists():
        raise RuntimeError("o Chrome não gerou o PDF: "
                           + ((r.stderr or r.stdout or "sem mensagem")[-300:]))
    return pdf
