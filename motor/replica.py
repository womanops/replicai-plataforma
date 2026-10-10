#!/usr/bin/env python3
"""
replica.py — infraestrutura do ReplicAI (replicação e desdobramento de peças).

Só Pillow (pip3 install pillow). A inteligência — ler a peça, decidir o que é
assunto, texto e logo, escrever a copy de cada canal e compor o layout — é do
Claude que invoca a skill. Este script faz o trabalho determinístico:

    check                                     dependências e motores
    formatos [--grupo G] [--canal C]          catálogo de destinos
    prep <pasta>                              cria replicas/, acha base e brief
    grid <img> [--passo 100]                  grade com coordenadas pra estimar boxes
    analyze <img>                             dimensões, paleta, bordas, cobertura
    crop <img> --bbox x0,y0,x1,y1 --out f     recorta elemento (logo, produto)
    clean <img> --regions "x0,y0,x1,y1;..."   apaga texto/elemento reconstruindo o fundo
    fit <img> --formato ID|--to WxH [...]     plano: cortar o que pode, estender o resto
    extend <img> --formato ID|--to WxH ...    aplica o plano e gera o fundo no tamanho final
    render <peca.json> [--out f.png]          compõe texto real por cima via Chrome
    validate <pasta>                          confere dimensões, safe zones, estouros
    sheet <pasta>                             PDF de apresentação + output/ + manifest
    save-external <pasta> --url|--file ...    importa peça gerada fora (MCP) com log

Tudo imprime JSON no stdout; erro humano no stderr com exit != 0.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.request
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageMath, ImageOps, ImageStat
except ImportError:  # pragma: no cover
    print("ERRO: Pillow não está instalado. Rode: pip3 install pillow", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
# Na skill os assets ficam um nível acima do script; aqui o motor é um pacote e
# eles vivem ao lado dele. Procura os dois para a mesma cópia servir nos dois
# lugares — sem isto o render morre com "formatos.json não existe", que não diz
# nada sobre a causa.
ASSETS = next((c for c in (Path(__file__).resolve().parent / "assets", ROOT / "assets") if c.is_dir()),
              ROOT / "assets")
TEMPLATE = ASSETS / "template.html"
FORMATOS_JSON = ASSETS / "formatos.json"
IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}
TEXT_EXTS = {".txt", ".md"}
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
URL_RE = re.compile(r"https://[^ \"'\\]+\.(?:png|jpg|jpeg|webp)(?:\?[^ \"'\\]*)?", re.I)


# ----------------------------------------------------------------------------- util

def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def out(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def die(msg: str, code: int = 1) -> int:
    print(f"ERRO: {msg}", file=sys.stderr)
    return code


def run_cmd(args: list[str], timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def baixar(url: str, dest: Path) -> None:
    """Python do Homebrew costuma vir sem certificados; se o urllib falhar no SSL, usa o curl."""
    try:
        with urllib.request.urlopen(url, timeout=180) as resp:
            dest.write_bytes(resp.read())
        return
    except Exception as exc:  # SSL, rede etc.
        if not shutil.which("curl"):
            raise RuntimeError(f"não consegui baixar {url}: {exc}")
    r = subprocess.run(["curl", "-L", "-sS", "--fail", "-o", str(dest), url], capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not dest.exists():
        raise RuntimeError(f"curl falhou ao baixar {url}: {r.stderr[-300:]}")


def parse_bbox(s: str) -> tuple[int, int, int, int]:
    parts = [int(round(float(p))) for p in re.split(r"[,\s]+", s.strip()) if p]
    if len(parts) != 4:
        raise ValueError(f"bbox precisa de 4 números: '{s}'")
    x0, y0, x1, y1 = parts
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def parse_size(s: str) -> tuple[int, int]:
    m = re.match(r"^\s*(\d+)\s*[xX×]\s*(\d+)\s*$", s)
    if not m:
        raise ValueError(f"tamanho precisa ser LxA, ex. 1080x1350: '{s}'")
    return int(m.group(1)), int(m.group(2))


def load_formatos() -> dict:
    return json.loads(FORMATOS_JSON.read_text(encoding="utf-8"))


def formato_by_id(fid: str) -> dict | None:
    for f in load_formatos()["formatos"]:
        if f["id"] == fid:
            return f
    return None


def resolve_target(args) -> tuple[int, int, dict | None]:
    if getattr(args, "formato", None):
        f = formato_by_id(args.formato)
        if not f:
            raise ValueError(f"formato desconhecido: {args.formato}. Veja `formatos`.")
        return f["w"], f["h"], f
    if getattr(args, "to", None):
        w, h = parse_size(args.to)
        return w, h, None
    raise ValueError("informe --formato ID ou --to LxA")


VENV_PY = ROOT / ".venv" / "bin" / "python"
VENV_FIX = "python3 -m venv ~/.claude/skills/replicai/.venv && ~/.claude/skills/replicai/.venv/bin/pip install psd-tools pytoshop packbits six numpy pillow"


def venv_python() -> str | None:
    return str(VENV_PY) if VENV_PY.exists() else None


def rasterizar_vetor(src: Path, out: Path) -> Path:
    """`.ai`/`.pdf` → PNG com alfa. No Mac usa o QuickLook (qlmanage); sem ele, tenta o sips."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("qlmanage"):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["qlmanage", "-t", "-s", "4000", "-o", tmp, str(src)], capture_output=True, text=True, timeout=180)
            feitos = list(Path(tmp).glob("*.png"))
            if feitos:
                Image.open(feitos[0]).convert("RGBA").save(out)
                return out
    r = subprocess.run(["sips", "-s", "format", "png", str(src), "--out", str(out)], capture_output=True, text=True, timeout=180)
    if out.exists():
        return out
    raise RuntimeError(f"não consegui rasterizar {src.name}: exporte um PNG/PDF do Illustrator e use ele como base.")


def find_chrome() -> str | None:
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    return None


def chrome_run(url: str, extra: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("Chrome não encontrado. Instale o Google Chrome para renderizar as peças.")
    # sem --user-data-dir: com ele o Chrome 153 escreve o PNG e nunca fecha.
    args = [
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
        "--disable-extensions", "--allow-file-access-from-files", "--force-device-scale-factor=1",
        "--virtual-time-budget=6000", "--default-background-color=00000000",
    # Dentro de um contêiner o processo roda como root e o Chromium se recusa a
    # abrir sem --no-sandbox. A bandeira vem do ambiente em vez de ficar fixa
    # aqui: no Mac ela não existe, e no servidor o Dockerfile a define.
    ] + os.environ.get("CHROME_FLAGS", "").split() + extra + [url]
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def higgsfield_status() -> dict:
    if not shutil.which("higgsfield"):
        return {"available": False, "status": "missing", "fix": "npm install -g @higgsfield/cli"}
    try:
        r = run_cmd(["higgsfield", "account", "status"], timeout=60)
    except Exception as exc:  # pragma: no cover
        return {"available": False, "status": "error", "detail": str(exc)[:200]}
    if r.returncode == 0:
        return {"available": True, "status": "ok"}
    return {"available": False, "status": "login_required", "fix": "higgsfield auth login", "detail": (r.stdout + r.stderr).strip()[:300]}


def open_rgb(path: str | Path) -> Image.Image:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"imagem não existe: {p}")
    img = Image.open(p)
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return img.convert("RGB")


def replicas_root(pasta: str) -> Path:
    p = Path(pasta).expanduser().resolve()
    if p.name == "replicas":
        return p
    return p / "replicas"


# ----------------------------------------------------------------------------- check / formatos

def cmd_check(_args) -> int:
    chrome = find_chrome()
    higgs = higgsfield_status()
    payload = {
        "python": platform.python_version(),
        "pillow": Image.__version__ if hasattr(Image, "__version__") else "ok",
        "chrome": {"available": bool(chrome), "path": chrome, "fix": None if chrome else "Instale o Google Chrome (usado para renderizar texto real nas peças)."},
        "higgsfield_cli": higgs,
        "outpaint_generativo": "disponível via Higgsfield CLI (flux_2_pro_outpaint)" if higgs.get("available") else "indisponível — extensões de fundo saem só pelos modos determinísticos (stretch/mirror/blur/solid) ou por MCP (outpaint_image/reframe) + save-external",
        "camadas_psd": {"available": bool(venv_python()), "fix": None if venv_python() else VENV_FIX},
        "catalogo": {"formatos": len(load_formatos()["formatos"]), "grupos": list(load_formatos()["grupos"].keys())},
    }
    out(payload)
    return 0


def cmd_formatos(args) -> int:
    cat = load_formatos()
    lista = cat["formatos"]
    if args.grupo:
        ids = cat["grupos"].get(args.grupo)
        if ids is None:
            return die(f"grupo desconhecido: {args.grupo}. Grupos: {list(cat['grupos'].keys())}")
        lista = [f for f in lista if f["id"] in ids]
    if args.canal:
        lista = [f for f in lista if args.canal.lower() in f["canal"].lower()]
    if args.completo:
        out({"grupos": cat["grupos"], "formatos": lista})
    else:
        out([{"id": f["id"], "canal": f["canal"], "nome": f["nome"], "w": f["w"], "h": f["h"], "safe": f["safe"], "texto": f["texto"]} for f in lista])
    return 0


# ----------------------------------------------------------------------------- prep

def cmd_prep(args) -> int:
    pasta = Path(args.pasta).expanduser().resolve()
    if not pasta.is_dir():
        return die(f"pasta não existe: {pasta}")
    imagens = sorted(p for p in pasta.iterdir() if p.suffix.lower() in IMG_EXTS and not p.name.startswith("."))
    pdfs = sorted(p for p in pasta.iterdir() if p.suffix.lower() == ".pdf")
    origem_camadas = None
    # PSD: abre em camadas (separação perfeita, sem clean). AI/PDF: rasteriza (achatado).
    for arte in sorted(p for p in pasta.iterdir() if p.suffix.lower() in (".psd", ".ai", ".pdf") and not p.name.startswith(".")):
        alvo = pasta / (arte.stem + "-base.png")
        if alvo.exists():
            imagens = sorted(set(imagens) | {alvo}); continue
        raiz_w = pasta / "replicas" / "_work"; raiz_w.mkdir(parents=True, exist_ok=True)
        if arte.suffix.lower() == ".psd":
            if not venv_python():
                print(f"AVISO: {arte.name} é PSD, mas o ambiente de camadas não está instalado. Rode: {VENV_FIX}", file=sys.stderr); continue
            # PSD grande leva minutos: se a leitura já foi feita, reaproveita em vez de refazer
            cam_json = raiz_w / "camadas-psd" / "camadas.json"
            if cam_json.exists():
                meta = json.loads(cam_json.read_text(encoding="utf-8"))
            else:
                r = run_cmd([venv_python(), str(ROOT / "scripts" / "psd_io.py"), "read", str(arte), str(raiz_w / "camadas-psd")], timeout=1800)
                if r.returncode != 0:
                    print(f"AVISO: não consegui ler {arte.name}: {r.stderr[-300:]}", file=sys.stderr); continue
                meta = json.loads(r.stdout)
            Image.open(meta["composite"]).convert("RGB").save(alvo)
            origem_camadas = {"arquivo": str(arte), "camadas_json": str(raiz_w / "camadas-psd" / "camadas.json"), "n": len(meta["camadas"]), "camadas": [{k: c.get(k) for k in ("n", "nome", "tipo", "visivel", "bbox", "png", "texto")} for c in meta["camadas"]]}
        else:
            try:
                png = rasterizar_vetor(arte, raiz_w / (arte.stem + "-raster.png"))
                Image.open(png).convert("RGB").save(alvo)
            except RuntimeError as exc:
                print(f"AVISO: {exc}", file=sys.stderr); continue
        imagens = sorted(set(imagens) | {alvo})
    textos = sorted(p for p in pasta.iterdir() if p.suffix.lower() in TEXT_EXTS and not p.name.startswith("."))
    fontes = sorted(p for p in pasta.rglob("*") if p.suffix.lower() in {".ttf", ".otf", ".woff2", ".woff"})
    videos = sorted(p for p in pasta.iterdir() if p.suffix.lower() in VIDEO_EXTS and not p.name.startswith("."))
    video_info = None
    if videos and shutil.which("ffmpeg"):
        v = videos[0]
        raiz_w = pasta / "replicas" / "_work"; raiz_w.mkdir(parents=True, exist_ok=True)
        info = _ffprobe(v)
        dur = info.get("dur") or 0
        poster = pasta / (v.stem + "-poster.png")
        if not poster.exists():
            run_cmd(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{min(1.0, dur / 2):.2f}", "-i", str(v), "-frames:v", "1", str(poster)], timeout=120)
        quadros = []
        qdir = raiz_w / "quadros"; qdir.mkdir(exist_ok=True)
        for k in range(6):
            t = dur * (k + 0.5) / 6 if dur else k
            q = qdir / f"quadro-{k + 1:02d}.png"
            if not q.exists():
                run_cmd(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(v), "-frames:v", "1", "-vf", "scale=640:-2", str(q)], timeout=120)
            if q.exists():
                quadros.append(str(q))
        # tira de quadros: uma imagem só para o Read ver o movimento
        try:
            tiles = [Image.open(q).convert("RGB") for q in quadros]
            if tiles:
                w0, h0 = tiles[0].size
                tira = Image.new("RGB", (w0 * 3, h0 * ((len(tiles) + 2) // 3)), (20, 20, 20))
                for i, t_ in enumerate(tiles):
                    tira.paste(t_, ((i % 3) * w0, (i // 3) * h0))
                tira.save(raiz_w / "quadros-tira.png")
        except Exception:
            pass
        video_info = {"arquivo": str(v), **info, "poster": str(poster) if poster.exists() else None, "quadros": quadros, "tira": str(raiz_w / "quadros-tira.png")}
        if poster.exists():
            imagens = sorted(set(imagens) | {poster})
    elif videos:
        print("AVISO: vídeo na pasta, mas ffmpeg não está instalado (brew install ffmpeg).", file=sys.stderr)
    if not imagens and not pdfs:
        return die("não achei nenhuma imagem (.png/.jpg/.webp), PDF nem vídeo na pasta. A base precisa estar aqui.")

    raiz = pasta / "replicas"
    for sub in ("_work", "_prompts", "_logs", "pecas", "output"):
        (raiz / sub).mkdir(parents=True, exist_ok=True)

    brief = ""
    for t in textos:
        brief += f"\n\n### {t.name}\n" + t.read_text(encoding="utf-8", errors="replace")

    info_imgs = []
    for p in imagens:
        try:
            im = Image.open(p)
            info_imgs.append({"path": str(p), "w": im.width, "h": im.height, "ratio": round(im.width / im.height, 3)})
        except Exception as exc:
            info_imgs.append({"path": str(p), "erro": str(exc)})

    manifest_p = raiz / "manifest.json"
    manifest = {}
    if manifest_p.exists():
        try:
            manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    manifest.update({
        "pasta": str(pasta),
        "criado": manifest.get("criado", now_iso()),
        "atualizado": now_iso(),
        "imagens": info_imgs,
        "pdfs": [str(p) for p in pdfs],
        "textos": [str(t) for t in textos],
        "fontes": [str(f) for f in fontes],
        "camadas_origem": origem_camadas,
        "video_origem": video_info,
        "base": manifest.get("base"),
        "objetivo": manifest.get("objetivo"),
        "destinos": manifest.get("destinos", []),
        "outputs": manifest.get("outputs", {}),
        "status": manifest.get("status", "preparado"),
    })
    manifest_p.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    out({
        "status": "ok",
        "raiz": str(raiz),
        "imagens": info_imgs,
        "pdfs": [str(p) for p in pdfs],
        "textos": [str(t) for t in textos],
        "brief": brief.strip()[:6000],
        "fontes_locais": [str(f) for f in fontes],
        "camadas": origem_camadas,
        "video": video_info,
        "manifest": str(manifest_p),
        "dica": "PDF como base: converta a página com `sips -s format png arquivo.pdf --out base.png` (Mac) ou exporte PNG antes.",
    })
    return 0


# ----------------------------------------------------------------------------- grid / analyze

def cmd_grid(args) -> int:
    img = open_rgb(args.img)
    passo = args.passo
    W, H = img.size
    over = img.copy()
    d = ImageDraw.Draw(over, "RGBA")
    for x in range(0, W, passo):
        forte = (x % (passo * 5) == 0)
        d.line([(x, 0), (x, H)], fill=(255, 0, 0, 200 if forte else 90), width=2 if forte else 1)
        if forte:
            d.rectangle([x + 2, 2, x + 2 + 12 * len(str(x)), 24], fill=(0, 0, 0, 170))
            d.text((x + 4, 4), str(x), fill=(255, 255, 255, 255))
    for y in range(0, H, passo):
        forte = (y % (passo * 5) == 0)
        d.line([(0, y), (W, y)], fill=(0, 200, 255, 200 if forte else 90), width=2 if forte else 1)
        if forte:
            d.rectangle([2, y + 2, 2 + 12 * len(str(y)), y + 24], fill=(0, 0, 0, 170))
            d.text((4, y + 4), str(y), fill=(255, 255, 255, 255))
    d.rectangle([W - 150, H - 28, W - 2, H - 2], fill=(0, 0, 0, 170))
    d.text((W - 146, H - 24), f"{W}x{H}", fill=(255, 255, 255, 255))
    outp = Path(args.out).expanduser().resolve() if args.out else Path(args.img).expanduser().resolve().with_name(Path(args.img).stem + "-grid.png")
    outp.parent.mkdir(parents=True, exist_ok=True)
    over.save(outp)
    out({"status": "ok", "grid": str(outp), "w": W, "h": H, "passo": passo, "dica": "Abra com o Read e leia as coordenadas nas linhas fortes (a cada 5 passos)."})
    return 0


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(round(c)) for c in rgb[:3])


def _edge_stats(img: Image.Image, frac: float = 0.04) -> dict:
    W, H = img.size
    t = max(2, int(H * frac)); s = max(2, int(W * frac))
    strips = {
        "top": img.crop((0, 0, W, t)), "bottom": img.crop((0, H - t, W, H)),
        "left": img.crop((0, 0, s, H)), "right": img.crop((W - s, 0, W, H)),
    }
    res = {}
    for k, im in strips.items():
        st = ImageStat.Stat(im)
        # "uniforme" aqui = esticar a borda seria invisível: compara a faixa com a
        # versão dela achatada a 1px e re-esticada (gradiente ao longo da borda passa;
        # textura/foto atravessando a borda não passa).
        if k in ("left", "right"):
            flat = im.resize((1, im.height), Image.Resampling.BOX).resize(im.size, Image.Resampling.BILINEAR)
        else:
            flat = im.resize((im.width, 1), Image.Resampling.BOX).resize(im.size, Image.Resampling.BILINEAR)
        dif = ImageStat.Stat(ImageChops.difference(im, flat)).mean
        d = sum(dif) / 3
        res[k] = {"cor": _hex(st.mean), "desvio": round(d, 1), "uniforme": d < 6}
    return res


def _palette(img: Image.Image, n: int = 6) -> list[dict]:
    small = img.copy(); small.thumbnail((200, 200))
    q = small.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[: n * 3]
    counts = sorted(q.getcolors(), reverse=True)
    total = sum(c for c, _ in counts)
    res = []
    for c, idx in counts:
        rgb = pal[idx * 3: idx * 3 + 3]
        res.append({"cor": _hex(rgb), "pct": round(100 * c / total, 1)})
    return res


def cmd_analyze(args) -> int:
    img = open_rgb(args.img)
    W, H = img.size
    edges = _edge_stats(img)
    pal = _palette(img)
    lum = ImageStat.Stat(img.convert("L")).mean[0]
    # Cobertura: fração de pixels distantes da cor de fundo estimada (moda das bordas).
    bg = max(edges.values(), key=lambda e: (e["uniforme"], -e["desvio"]))["cor"]
    bgc = tuple(int(bg[i:i + 2], 16) for i in (1, 3, 5))
    small = img.copy(); small.thumbnail((256, 256))
    diff = ImageChops.difference(small, Image.new("RGB", small.size, bgc)).convert("L")
    binar = diff.point(lambda v: 255 if v > 40 else 0)
    cov = binar.histogram()[255] / (small.width * small.height)
    # Terços: onde está a massa (útil pra saber se o assunto está à esquerda/direita/centro).
    g = small.convert("L")
    thirds = {}
    for name, box in (("esq", (0, 0, small.width // 3, small.height)), ("centro", (small.width // 3, 0, 2 * small.width // 3, small.height)), ("dir", (2 * small.width // 3, 0, small.width, small.height))):
        thirds[name] = round(binar.crop(box).histogram()[255] / (box[2] - box[0]) / small.height, 2)
    out({
        "status": "ok", "path": str(Path(args.img).resolve()), "w": W, "h": H, "ratio": round(W / H, 3),
        "luminancia_media": round(lum, 1), "escura": lum < 100,
        "paleta": pal, "fundo_estimado": bg, "cobertura": round(cov, 2),
        "bordas": edges, "massa_por_tercos": thirds,
        "leitura": (
            "Bordas uniformes: extensão por `stretch` deve ficar invisível. " if all(e["uniforme"] for e in edges.values()) else
            "Bordas com textura/foto: extensões pequenas por `mirror`, grandes por `outpaint`. "
        ) + ("Cobertura alta: a peça é sangria/colagem — apagar texto vai exigir regiões bem justas." if cov > 0.85 else ""),
    })
    return 0


# ----------------------------------------------------------------------------- crop / clean

def cmd_crop(args) -> int:
    img = Image.open(Path(args.img).expanduser().resolve())
    img = ImageOps.exif_transpose(img).convert("RGBA")
    x0, y0, x1, y1 = parse_bbox(args.bbox)
    pad = args.pad
    box = (max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad))
    rec = img.crop(box)
    if args.alpha_key:
        key = args.alpha_key
        if key == "auto":
            # cor mais comum na borda do recorte
            border = ImageOps.expand(rec, border=0)
            edge = [rec.getpixel((x, 0)) for x in range(rec.width)] + [rec.getpixel((x, rec.height - 1)) for x in range(rec.width)] + \
                   [rec.getpixel((0, y)) for y in range(rec.height)] + [rec.getpixel((rec.width - 1, y)) for y in range(rec.height)]
            keyc = max(set(p[:3] for p in edge), key=[p[:3] for p in edge].count)
        else:
            keyc = tuple(int(key.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        tol = args.tol
        rgb = rec.convert("RGB")
        diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, keyc)).convert("L")
        # alfa suave: 0 na cor-chave, 255 fora da tolerância
        alpha = diff.point(lambda v: 0 if v <= tol else (255 if v >= tol * 2 else int(255 * (v - tol) / tol)))
        rec.putalpha(alpha)
    outp = Path(args.out).expanduser().resolve()
    outp.parent.mkdir(parents=True, exist_ok=True)
    rec.save(outp)
    out({"status": "ok", "out": str(outp), "box": list(box), "w": rec.width, "h": rec.height, "alpha_key": bool(args.alpha_key)})
    return 0


def preencher(img: Image.Image, buraco: Image.Image, raios=(3, 6, 12, 24, 48, 96, 192, 384, 768), excluir: Image.Image | None = None) -> Image.Image:
    """Reconstrói o fundo dentro de `buraco` (L, 255 = apagar) por convolução
    normalizada multi-escala: cada pixel do buraco recebe a média ponderada dos
    pixels CONHECIDOS ao redor, na menor escala em que há apoio suficiente.
    Pixels já preenchidos nunca viram fonte (evita as faixas do "onion peel"),
    e a tinta do texto apagado nunca vaza de volta. Pillow puro."""
    img = img.convert("RGB")
    W, H = img.size
    conhecido = ImageChops.invert(buraco)  # 255 = conhecido
    if excluir is not None:
        # assunto protegido: não é apagado, mas também não serve de fonte (senão a cor dele vaza pro fundo)
        conhecido = ImageChops.multiply(conhecido, ImageChops.invert(excluir))
    canais = list(img.split())
    mascarados = [ImageChops.multiply(c, conhecido) for c in canais]
    restante = buraco.copy()
    ultimo_est = None
    for r in raios:
        if not restante.getbbox():
            break
        den = conhecido.filter(ImageFilter.GaussianBlur(r))
        den_f = den.convert("F")
        ests = []
        for m in mascarados:
            num = m.filter(ImageFilter.GaussianBlur(r)).convert("F")
            est = ImageMath.lambda_eval(lambda a: a["n"] * 255.0 / (a["d"] + 0.01), n=num, d=den_f)
            ests.append(est.convert("L"))
        ultimo_est = ests
        # apoio suficiente: pelo menos ~12% do peso vem de pixel conhecido
        apoio = den.point(lambda v: 255 if v > 30 else 0)
        preenche = ImageChops.multiply(restante, apoio)
        if not preenche.getbbox():
            continue
        canais = [Image.composite(ests[i], canais[i], preenche) for i in range(3)]
        restante = ImageChops.subtract(restante, preenche)
    if restante.getbbox():
        if ultimo_est is not None:
            canais = [Image.composite(ultimo_est[i], canais[i], restante) for i in range(3)]
        else:
            media = tuple(int(v) for v in ImageStat.Stat(img).mean)
            canais = [Image.composite(Image.new("L", (W, H), media[i]), canais[i], restante) for i in range(3)]
    res = Image.merge("RGB", canais)
    # as escalas trocam em degraus; um blur médio só dentro do buraco apaga as bandas
    interior = buraco.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(3))
    res = Image.composite(res.filter(ImageFilter.GaussianBlur(10)), res, interior)
    # e um leve blur na emenda com o que é conhecido
    borda = ImageChops.subtract(buraco.filter(ImageFilter.MaxFilter(7)), buraco.filter(ImageFilter.MinFilter(7)))
    return Image.composite(res.filter(ImageFilter.GaussianBlur(1.5)), res, borda)


def nitidez(im: Image.Image) -> float:
    """Variância do laplaciano (em L): alto = detalhe/textura, baixo = liso/borrado."""
    g = im.convert("L")
    lap = g.filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128))
    return ImageStat.Stat(lap).var[0]


def nitidez_local(im: Image.Image, mask: Image.Image, janela: int = 32) -> float:
    """Mediana da nitidez em janelas cobertas pela máscara: robusta a uma borda muito nítida
    (a fita, o produto) que puxaria a média para cima."""
    g = im.convert("L")
    lap = g.filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128))
    vals = []
    W, H = im.size
    for y in range(0, H - janela + 1, janela):
        for x in range(0, W - janela + 1, janela):
            box = (x, y, x + janela, y + janela)
            if mask.crop(box).histogram()[255] < janela * janela * 0.6:
                continue
            vals.append(ImageStat.Stat(lap.crop(box)).var[0])
    if not vals:
        return 0.0
    vals.sort()
    return vals[len(vals) // 2]


def preencher_doador(img: Image.Image, buraco: Image.Image, proibido: Image.Image | None = None, tile: int = 128, passo: int = 24, anel: int = 16, sobre: int = 28, raio_luz: int = 14) -> tuple[Image.Image, dict]:
    """Reconstrói o fundo em duas camadas: a LUZ (baixa frequência: gradiente, halo, vinheta) vem do
    preenchimento suave, que acerta exatamente isso; o DETALHE (alta frequência: malha, grão, textura)
    vem de um doador copiado de outra área da própria peça ("carimbo"), escolhido pela textura do anel
    conhecido ao redor do bloco, com preferência por doadores próximos. Blocos sobrepostos com borda em
    degradê, preenchidos de fora para dentro. Nunca copia do buraco nem da região protegida."""
    img = img.convert("RGB")
    W, H = img.size
    diag = (W * W + H * H) ** 0.5
    fonte_invalida = buraco.copy()
    if proibido is not None:
        fonte_invalida = ImageChops.lighter(fonte_invalida, proibido)
    fonte_invalida = fonte_invalida.filter(ImageFilter.MaxFilter(5))
    # luz: preenchimento suave do buraco (só pixels conhecidos, sem o protegido)
    luz = preencher(img, buraco, excluir=proibido)
    # detalhe da imagem inteira (alta frequência, offset 128)
    hp = ImageChops.subtract(img, img.filter(ImageFilter.GaussianBlur(raio_luz)), scale=1.0, offset=128)
    res = luz.copy()
    conhecido = ImageChops.invert(buraco)
    bbox = buraco.getbbox()
    if not bbox:
        return res, {"blocos": 0}
    x0, y0, x1, y1 = bbox
    stride = tile - sobre
    pend = []
    for ty in range(y0, y1, stride):
        for tx in range(x0, x1, stride):
            b = (tx, ty, min(tx + tile, x1 + sobre, W), min(ty + tile, y1 + sobre, H))
            if buraco.crop(b).getbbox() is not None:
                pend.append(b)
    def pena(bw, bh):
        m = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(m).rectangle((sobre // 2, sobre // 2, bw - sobre // 2 - 1, bh - sobre // 2 - 1), fill=255)
        return m.filter(ImageFilter.GaussianBlur(sobre / 3))
    blocos = 0; falhas = 0
    hp_res = hp.copy()  # detalhe do resultado (atualizado conforme preenche)
    while pend:
        def apoio(b):
            tx, ty, bx1, by1 = b
            return conhecido.crop((max(0, tx - anel), max(0, ty - anel), min(W, bx1 + anel), min(H, by1 + anel))).histogram()[255]
        pend.sort(key=apoio, reverse=True)
        tx, ty, bx1, by1 = pend.pop(0)
        bw, bh = bx1 - tx, by1 - ty
        rx0, ry0, rx1, ry1 = max(0, tx - anel), max(0, ty - anel), min(W, bx1 + anel), min(H, by1 + anel)
        ref = hp_res.crop((rx0, ry0, rx1, ry1))
        ref_ok = conhecido.crop((rx0, ry0, rx1, ry1))
        n_ok = ref_ok.histogram()[255]
        if n_ok < 60:
            falhas += 1; continue
        rw, rh = ref.size
        cx, cy = tx + bw / 2, ty + bh / 2

        def score(dx, dy):
            if dx < 0 or dy < 0 or dx + rw > W or dy + rh > H:
                return None
            if fonte_invalida.crop((dx, dy, dx + rw, dy + rh)).getbbox() is not None:
                return None
            d = ImageChops.multiply(ImageChops.difference(hp.crop((dx, dy, dx + rw, dy + rh)), ref).convert("L"), ref_ok)
            dist = ((dx + rw / 2 - cx) ** 2 + (dy + rh / 2 - cy) ** 2) ** 0.5
            return ImageStat.Stat(d).sum[0] / n_ok + 4.0 * dist / diag

        melhor = None
        for dy in range(0, H - rh + 1, passo):
            for dx in range(0, W - rw + 1, passo):
                sc = score(dx, dy)
                if sc is not None and (melhor is None or sc < melhor[0]):
                    melhor = (sc, dx, dy)
        if melhor is None:
            falhas += 1; continue
        _, mx, my = melhor
        for dy in range(my - passo, my + passo + 1, 3):
            for dx in range(mx - passo, mx + passo + 1, 3):
                sc = score(dx, dy)
                if sc is not None and sc < melhor[0]:
                    melhor = (sc, dx, dy)
        _, dx, dy = melhor
        det = hp.crop((dx + (tx - rx0), dy + (ty - ry0), dx + (tx - rx0) + bw, dy + (ty - ry0) + bh))
        bloco = ImageChops.add(luz.crop((tx, ty, bx1, by1)), det, scale=1.0, offset=-128)
        m = ImageChops.multiply(buraco.crop((tx, ty, bx1, by1)).filter(ImageFilter.GaussianBlur(2)), pena(bw, bh))
        ainda = ImageChops.invert(conhecido.crop((tx, ty, bx1, by1)))
        m = ImageChops.lighter(m, ImageChops.multiply(ainda, buraco.crop((tx, ty, bx1, by1))).filter(ImageFilter.GaussianBlur(1)))
        res.paste(Image.composite(bloco, res.crop((tx, ty, bx1, by1)), m), (tx, ty))
        hp_res.paste(Image.composite(det, hp_res.crop((tx, ty, bx1, by1)), m), (tx, ty))
        ImageDraw.Draw(conhecido).rectangle((tx, ty, bx1 - 1, by1 - 1), fill=255)
        blocos += 1
    return res, {"blocos": blocos, "sem_doador": falhas}


def cmd_clean(args) -> int:
    img = open_rgb(args.img)
    W, H = img.size
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    regs = []
    for r in [s for s in re.split(r"[;|]", args.regions) if s.strip()]:
        x0, y0, x1, y1 = parse_bbox(r)
        p = args.pad
        box = (max(0, x0 - p), max(0, y0 - p), min(W, x1 + p), min(H, y1 + p))
        d.rectangle(box, fill=255)
        regs.append(list(box))
    if args.mask:
        m = Image.open(args.mask).convert("L").resize((W, H))
        mask = ImageChops.lighter(mask, m.point(lambda v: 255 if v > 127 else 0))
    excluir = None
    if args.protect:
        # o assunto nunca é apagado, mesmo que o texto passe por cima dele
        prot = Image.new("L", (W, H), 255)
        dp = ImageDraw.Draw(prot)
        for r in [s for s in re.split(r"[;|]", args.protect) if s.strip()]:
            dp.rectangle(parse_bbox(r), fill=0)
        mask = ImageChops.multiply(mask, prot)
        excluir = ImageChops.invert(prot).filter(ImageFilter.MaxFilter(9))
    cov = mask.histogram()[255] / (W * H)
    # modo: `suave` (média dos vizinhos) só serve para fundo liso/gradiente; sobre textura vira borrão.
    # `doador` copia textura real da própria peça. `auto` decide pela nitidez do entorno.
    modo = args.mode
    anel = ImageChops.subtract(mask.filter(ImageFilter.MaxFilter(61)), mask)
    if excluir is not None:
        anel = ImageChops.multiply(anel, ImageChops.invert(excluir))
    nit_entorno = nitidez_local(img, anel) if anel.getbbox() else 0
    if modo == "auto":
        modo = "doador" if nit_entorno > 8 else "suave"
    info = {}
    if modo == "doador":
        res, info = preencher_doador(img, mask, proibido=excluir)
    else:
        res = preencher(img, mask, excluir=excluir)
    outp = Path(args.out).expanduser().resolve()
    outp.parent.mkdir(parents=True, exist_ok=True)
    res.save(outp)
    maskp = outp.with_name(outp.stem + "-mask.png")
    mask.save(maskp)
    # nitidez da região reconstruída vs entorno: < 0,5 é borrão visível
    nit_regiao = nitidez_local(res, mask) if mask.getbbox() else 0
    razao = round(nit_regiao / nit_entorno, 2) if nit_entorno else None
    veredito = "ok" if (razao is None or razao >= 0.5) else ("suavizado" if razao >= 0.2 else "borrado")
    outp.with_suffix(outp.suffix + ".origem.json").write_text(json.dumps({"origem": "clean", "modo": modo, "mask": str(maskp), "nitidez_entorno": round(nit_entorno, 1), "nitidez_regiao": round(nit_regiao, 1), "razao": razao, "veredito": veredito, **info, "quando": now_iso()}, ensure_ascii=False, indent=2), encoding="utf-8")
    out({"status": "ok" if veredito != "borrado" else "borrado", "out": str(outp), "mask": str(maskp), "modo": modo, "regioes": regs, "area_apagada_pct": round(100 * cov, 1),
         "nitidez": {"entorno": round(nit_entorno, 1), "regiao": round(nit_regiao, 1), "razao": razao, "veredito": veredito}, **info,
         "dica": ("Região ficou BORRADA em relação ao entorno: não use este fundo. Tente --mode doador, regiões menores, ou inpaint generativo. Ou não apague: mantenha o texto original onde está." if veredito == "borrado" else
                  "Textura reconstruída um pouco mais suave que o entorno: abra com o Read e decida. Se notar, use regiões menores ou inpaint generativo." if veredito == "suavizado" else
                  "Abra o resultado com o Read. Fantasma de letra ou mancha: aumente --pad ou ajuste as regiões.")})
    return 0 if veredito != "borrado" else 2


# ----------------------------------------------------------------------------- fit / extend

def plan_fit(W: int, H: int, w: int, h: int, protect=None, strategy: str = "smart", anchor=(0.5, 0.5), folga: float = 0.0) -> dict:
    ta = w / h
    P = list(protect) if protect else [0, 0, W, H]
    P = [max(0, P[0]), max(0, P[1]), min(W, P[2]), min(H, P[3])]
    pw, ph = P[2] - P[0], P[3] - P[1]
    base_mais_larga = (W / H) > ta
    if base_mais_larga:
        ch, cw = H, H * ta
    else:
        cw, ch = W, W / ta
    cabe = (pw <= cw + 0.5) and (ph <= ch + 0.5)
    ax, ay = anchor

    if strategy == "cover" or (strategy == "smart" and cabe and folga <= 0):
        cx = (P[0] + P[2]) / 2 if protect else W * ax
        cy = (P[1] + P[3]) / 2 if protect else H * ay
        x0 = min(max(cx - cw / 2, 0), W - cw)
        y0 = min(max(cy - ch / 2, 0), H - ch)
        crop = [int(round(x0)), int(round(y0)), int(round(x0 + cw)), int(round(y0 + ch))]
        cortou = crop != [0, 0, W, H]
        return {"estrategia": "crop", "crop": crop, "expand": {"left": 0, "right": 0, "top": 0, "bottom": 0},
                "canvas_base": [crop[2] - crop[0], crop[3] - crop[1]], "escala": round(w / cw, 4),
                "protegido_intacto": True, "cortou_fundo": cortou,
                "nota": "Alvo cabe cortando só área fora da região protegida." if cortou else "Mesma proporção: só redimensiona."}

    if strategy == "contain" or not protect:
        keep = [0, 0, W, H]
    else:
        # smart: no eixo que precisa encolher, corta até a região protegida; o outro fica inteiro
        keep = [P[0], 0, P[2], H] if base_mais_larga else [0, P[1], W, P[3]]
    kw, kh = keep[2] - keep[0], keep[3] - keep[1]
    # folga: área extra (fração do canvas final) pra texto — sempre estende
    if kw / kh > ta or (folga > 0 and not base_mais_larga and kw / kh >= ta):
        Hn = kw / ta
        Hn = max(Hn, kh * (1 + folga))
        Wn = Hn * ta
    else:
        Wn = kh * ta
        Wn = max(Wn, kw * (1 + folga))
        Hn = Wn / ta
    ex_w = max(0.0, Wn - kw); ex_h = max(0.0, Hn - kh)
    left = int(round(ex_w * ax)); right = int(round(ex_w)) - left
    top = int(round(ex_h * ay)); bottom = int(round(ex_h)) - top
    return {"estrategia": "extend", "crop": keep,
            "expand": {"left": left, "right": right, "top": top, "bottom": bottom},
            "canvas_base": [kw + left + right, kh + top + bottom], "escala": round(w / (kw + left + right), 4),
            "protegido_intacto": True, "cortou_fundo": keep != [0, 0, W, H],
            "nota": "Sem cortes no conteúdo: o fundo é estendido (px em coordenadas da base)."}


def _to_target_coords(plan: dict, W: int, H: int, w: int, h: int, protect=None) -> dict:
    """Onde a base (e a região protegida) caem no canvas final."""
    crop = plan["crop"]; ex = plan["expand"]; s = plan["escala"]
    bx0 = ex["left"] * s; by0 = ex["top"] * s
    base_box = [int(round(bx0)), int(round(by0)), int(round(bx0 + (crop[2] - crop[0]) * s)), int(round(by0 + (crop[3] - crop[1]) * s))]
    res = {"base_box": base_box}
    if protect:
        px0 = (protect[0] - crop[0]) * s + bx0; py0 = (protect[1] - crop[1]) * s + by0
        res["protect_box"] = [int(round(px0)), int(round(py0)), int(round(px0 + (protect[2] - protect[0]) * s)), int(round(py0 + (protect[3] - protect[1]) * s))]
    # áreas livres (faixas de extensão) — onde texto pode entrar sem cobrir a base
    livres = {}
    if base_box[1] > 0: livres["top"] = [0, 0, w, base_box[1]]
    if base_box[3] < h: livres["bottom"] = [0, base_box[3], w, h]
    if base_box[0] > 0: livres["left"] = [0, 0, base_box[0], h]
    if base_box[2] < w: livres["right"] = [base_box[2], 0, w, h]
    res["areas_livres"] = livres
    return res


def _parse_anchor(s: str | None) -> tuple[float, float]:
    if not s:
        return (0.5, 0.5)
    named = {"center": (0.5, 0.5), "centro": (0.5, 0.5), "top": (0.5, 0.0), "topo": (0.5, 0.0), "bottom": (0.5, 1.0), "base": (0.5, 1.0),
             "left": (0.0, 0.5), "esquerda": (0.0, 0.5), "right": (1.0, 0.5), "direita": (1.0, 0.5)}
    if s.lower() in named:
        return named[s.lower()]
    parts = [float(p) for p in s.split(",")]
    return (parts[0], parts[1] if len(parts) > 1 else 0.5)


def cmd_fit(args) -> int:
    img = open_rgb(args.img)
    W, H = img.size
    w, h, f = resolve_target(args)
    protect = parse_bbox(args.protect) if args.protect else None
    plan = plan_fit(W, H, w, h, protect, args.strategy, _parse_anchor(args.anchor), args.folga)
    plan.update(_to_target_coords(plan, W, H, w, h, protect))
    plan.update({"base": [W, H], "alvo": [w, h], "formato": f["id"] if f else None, "safe": f["safe"] if f else None})
    ex = plan["expand"]; total = ex["left"] + ex["right"] + ex["top"] + ex["bottom"]
    edges = _edge_stats(img)
    if plan["estrategia"] == "extend":
        plan["modo_sugerido"], plan["razao"] = escolher_modo(img.crop(tuple(plan["crop"])), ex, protect, plan["crop"])
    out(plan)
    return 0


def _stretch_side(img: Image.Image, side: str, n: int, amostra: int = 6) -> Image.Image:
    if n <= 0:
        return img
    W, H = img.size
    if side in ("left", "right"):
        strip = img.crop((0, 0, amostra, H)) if side == "left" else img.crop((W - amostra, 0, W, H))
        strip = strip.resize((1, H), Image.Resampling.BOX).resize((n, H), Image.Resampling.BILINEAR)
        strip = strip.filter(ImageFilter.GaussianBlur(3))
        novo = Image.new("RGB", (W + n, H))
        if side == "left":
            novo.paste(strip, (0, 0)); novo.paste(img, (n, 0))
        else:
            novo.paste(img, (0, 0)); novo.paste(strip, (W, 0))
    else:
        strip = img.crop((0, 0, W, amostra)) if side == "top" else img.crop((0, H - amostra, W, H))
        strip = strip.resize((W, 1), Image.Resampling.BOX).resize((W, n), Image.Resampling.BILINEAR)
        strip = strip.filter(ImageFilter.GaussianBlur(3))
        novo = Image.new("RGB", (W, H + n))
        if side == "top":
            novo.paste(strip, (0, 0)); novo.paste(img, (0, n))
        else:
            novo.paste(img, (0, 0)); novo.paste(strip, (0, H))
    return novo


def _mirror_side(img: Image.Image, side: str, n: int) -> Image.Image:
    if n <= 0:
        return img
    W, H = img.size
    horizontal = side in ("left", "right")
    novo = Image.new("RGB", (W + n, H) if horizontal else (W, H + n))
    if horizontal:
        novo.paste(img, (n, 0) if side == "left" else (0, 0))
        restante, pos, flip = n, (n if side == "left" else W), True
        while restante > 0:
            take = min(restante, W)
            tile = img.crop((0, 0, take, H)) if side == "left" else img.crop((W - take, 0, W, H))
            if flip:
                tile = ImageOps.mirror(tile)
            if side == "left":
                pos -= take; novo.paste(tile, (pos, 0))
            else:
                novo.paste(tile, (pos, 0)); pos += take
            restante -= take; flip = not flip
    else:
        novo.paste(img, (0, n) if side == "top" else (0, 0))
        restante, pos, flip = n, (n if side == "top" else H), True
        while restante > 0:
            take = min(restante, H)
            tile = img.crop((0, 0, W, take)) if side == "top" else img.crop((0, H - take, W, H))
            if flip:
                tile = ImageOps.flip(tile)
            if side == "top":
                pos -= take; novo.paste(tile, (0, pos))
            else:
                novo.paste(tile, (0, pos)); pos += take
            restante -= take; flip = not flip
    return novo


def _blur_canvas(img: Image.Image, Wn: int, Hn: int, left: int, top: int, escurece: float = 0.82) -> Image.Image:
    W, H = img.size
    fundo = ImageOps.fit(img, (Wn, Hn), Image.Resampling.LANCZOS)
    fundo = fundo.filter(ImageFilter.GaussianBlur(max(Wn, Hn) * 0.03))
    fundo = fundo.point(lambda v: int(v * escurece))
    fundo.paste(img, (left, top))
    return fundo


def _solid_canvas(img: Image.Image, Wn: int, Hn: int, left: int, top: int, cor: str | None) -> Image.Image:
    if cor:
        c = tuple(int(cor.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    else:
        e = _edge_stats(img)
        best = min(e.values(), key=lambda x: x["desvio"])["cor"]
        c = tuple(int(best[i:i + 2], 16) for i in (1, 3, 5))
    fundo = Image.new("RGB", (Wn, Hn), c)
    fundo.paste(img, (left, top))
    return fundo


def _job_result_url(raw: str) -> str | None:
    """Prefere `result_url` do JSON; a primeira URL do texto costuma ser a miniatura."""
    try:
        d = json.loads(raw)
        if isinstance(d, dict) and d.get("result_url"):
            return d["result_url"]
    except Exception:
        pass
    urls = [u for u in URL_RE.findall(raw) if "_min." not in u]
    return urls[-1] if urls else None


def _higgsfield_job_por_params(model: str, params: dict) -> str | None:
    """Acha no `generate list` o job desse modelo cujos params batem (ex.: expand_*)."""
    ls = run_cmd(["higgsfield", "generate", "list", "--json"], timeout=60)
    try:
        d = json.loads(ls.stdout)
        items = d if isinstance(d, list) else (d.get("items") or d.get("jobs") or d.get("data") or [])
        for j in items:
            if j.get("job_type") != model:
                continue
            pj = j.get("params") or {}
            if all(pj.get(k) == v for k, v in params.items()):
                return j.get("id")
    except Exception:
        pass
    return None


def _higgsfield_gerar(args: list[str], model: str, params: dict, timeout: int = 1800) -> tuple[str | None, str]:
    """`generate create --wait`: bloqueia até o job terminar e imprime o resultado.
    Se a chamada travar além do timeout, recupera o job pelos params e faz `wait` nele."""
    espera = f"{max(1, round(timeout / 60))}m"
    try:
        cr = run_cmd(args + ["--wait", "--wait-timeout", espera], timeout=timeout)
        url = _job_result_url(cr.stdout)
        m = UUID_RE.search(cr.stdout)
        if url:
            return (m.group(0) if m else None), cr.stdout
    except subprocess.TimeoutExpired:
        pass
    job = _higgsfield_job_por_params(model, params)
    if not job:
        return None, ""
    wt = run_cmd(["higgsfield", "generate", "wait", job, "--timeout", "30m", "--json"], timeout=2100)
    return job, wt.stdout


def _outpaint_higgsfield(src: Path, ex: dict, log_dir: Path | None, timeout: int = 1800) -> tuple[Image.Image | None, dict]:
    st = higgsfield_status()
    if not st.get("available"):
        return None, {"erro": "Higgsfield CLI indisponível", **st}
    # limite do modelo: canvas final ≤ 2560px por lado. Reduz a fonte (e as margens) para caber e
    # devolve o resultado no tamanho pretendido; quem chamou redimensiona ao destino.
    im0 = Image.open(src).convert("RGB")
    W0, H0 = im0.size
    Wf, Hf = W0 + ex.get("left", 0) + ex.get("right", 0), H0 + ex.get("top", 0) + ex.get("bottom", 0)
    fator = min(1.0, 2560 / max(Wf, Hf))
    ex_orig = dict(ex)
    if fator < 1.0:
        im_s = im0.resize((max(1, int(W0 * fator)), max(1, int(H0 * fator))), Image.Resampling.LANCZOS)
        tmp_s = Path(tempfile.mkstemp(suffix=".png", prefix="replicai-outpaint-src-")[1]); im_s.save(tmp_s); src = tmp_s
        ex = {k: int(round(v * fator)) for k, v in ex.items()}
    up = run_cmd(["higgsfield", "upload", "create", str(src)], timeout=300)
    uuid = (UUID_RE.search(up.stdout) or UUID_RE.search(up.stderr))
    if not uuid:
        return None, {"erro": "upload não devolveu UUID", "stdout": (up.stdout + up.stderr)[:500]}
    args = ["higgsfield", "generate", "create", "flux_2_pro_outpaint", "--image", uuid.group(0), "--json"]
    for k in ("left", "right", "top", "bottom"):
        if ex.get(k, 0) > 0:
            args += [f"--expand_{k}", str(int(ex[k]))]
    params = {f"expand_{k}": int(ex.get(k, 0)) for k in ("left", "right", "top", "bottom")}
    job, raw = _higgsfield_gerar(args, "flux_2_pro_outpaint", params, timeout=timeout)
    url = _job_result_url(raw)
    if not url:
        return None, {"erro": "sem URL de resultado", "stdout": raw[-800:]}
    job = job or "?"
    tmp = Path(tempfile.mkstemp(suffix=".png", prefix="replicai-outpaint-")[1])
    baixar(url, tmp)
    log = {"provider": "higgsfield_cli", "model": "flux_2_pro_outpaint", "job_id": job, "upload": uuid.group(0), "expand": ex_orig, "expand_enviado": ex, "fator_reducao": round(fator, 3), "url": url}
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / f"outpaint-{str(job)[:8]}.json").write_text(json.dumps({**log, "stdout": raw[-3000:]}, indent=2, ensure_ascii=False), encoding="utf-8")
    res = Image.open(tmp).convert("RGB")
    if fator < 1.0 and res.size != (Wf, Hf):
        res = res.resize((Wf, Hf), Image.Resampling.LANCZOS)
    return res, log


def escolher_modo(base: Image.Image, ex: dict, protect, crop) -> tuple[str, str]:
    """Regra do `--mode auto`, aprendida em render:
    - stretch só quando a borda é uniforme E a extensão é curta (≤35% do lado); estender
      muito uma borda com faixa/fita vira listra;
    - mirror só quando a faixa espelhada não contém conteúdo protegido (senão o assunto
      aparece refletido) e a extensão é pequena (≤22%);
    - o resto é outpaint (se o Higgsfield estiver conectado), senão solid em borda uniforme
      ou blur."""
    edges = _edge_stats(base)
    lados = [k for k, v in ex.items() if v > 0]
    maior = max(ex[k] / (base.width if k in ("left", "right") else base.height) for k in lados)
    uniforme = all(edges[k]["uniforme"] for k in lados)
    # região protegida em coordenadas do crop
    toca = False
    if protect:
        px0, py0, px1, py1 = protect[0] - crop[0], protect[1] - crop[1], protect[2] - crop[0], protect[3] - crop[1]
        toca = any([
            ex["left"] > 0 and px0 < ex["left"],
            ex["right"] > 0 and px1 > base.width - ex["right"],
            ex["top"] > 0 and py0 < ex["top"],
            ex["bottom"] > 0 and py1 > base.height - ex["bottom"],
        ])
    if uniforme and maior <= 0.35:
        return "stretch", f"bordas uniformes e extensão curta ({int(maior*100)}%)"
    if not toca and maior <= 0.22 and not uniforme:
        return "mirror", f"extensão pequena ({int(maior*100)}%) sobre textura, sem conteúdo protegido na faixa"
    if higgsfield_status().get("available"):
        return "outpaint", ("assunto encosta na borda a estender" if toca else f"extensão grande ({int(maior*100)}%)") + " → outpaint generativo"
    return ("solid" if uniforme else "blur"), "sem Higgsfield: fallback determinístico"


def cmd_extend(args) -> int:
    img = open_rgb(args.img)
    W, H = img.size
    w, h, f = resolve_target(args)
    protect = parse_bbox(args.protect) if args.protect else None
    plan = plan_fit(W, H, w, h, protect, args.strategy, _parse_anchor(args.anchor), args.folga)
    crop = plan["crop"]; ex = plan["expand"]
    base = img.crop(tuple(crop))
    modo = args.mode
    razao = None
    if modo == "auto":
        if plan["estrategia"] == "crop":
            modo = "none"
        else:
            modo, razao = escolher_modo(base, ex, protect, crop)
    log: dict = {}
    if plan["estrategia"] == "crop" or modo == "none":
        canvas = base
        modo = "none"
    elif modo in ("stretch", "mirror"):
        canvas = base
        fn = _stretch_side if modo == "stretch" else _mirror_side
        for side in ("left", "right", "top", "bottom"):
            canvas = fn(canvas, side, ex[side])
    elif modo == "blur":
        canvas = _blur_canvas(base, base.width + ex["left"] + ex["right"], base.height + ex["top"] + ex["bottom"], ex["left"], ex["top"])
    elif modo == "solid":
        canvas = _solid_canvas(base, base.width + ex["left"] + ex["right"], base.height + ex["top"] + ex["bottom"], ex["left"], ex["top"], args.cor)
    elif modo == "outpaint":
        tmp_base = Path(tempfile.mkstemp(suffix=".png", prefix="replicai-base-")[1])
        base.save(tmp_base)
        log_dir = Path(args.out).expanduser().resolve().parent.parent / "_logs" if args.out else None
        res, log = _outpaint_higgsfield(tmp_base, ex, log_dir)
        if res is None:
            # sem fallback silencioso: desfoque não é adaptação. Quem chamou decide (stretch/solid/reframe/tentar de novo).
            return die(f"outpaint não rodou ({log.get('erro')}). Não vou cair para desfoque. Opções: rodar de novo (Higgsfield conectado?), --mode stretch/mirror se a borda permitir, --mode solid --cor da marca, ou reframe no caso de vídeo.", 2)
        else:
            # garante proporção exata antes de escalar
            Wn, Hn = base.width + ex["left"] + ex["right"], base.height + ex["top"] + ex["bottom"]
            canvas = ImageOps.fit(res, (Wn, Hn), Image.Resampling.LANCZOS) if res.size != (Wn, Hn) else res
    else:
        return die(f"modo desconhecido: {modo}")

    final = canvas.resize((w, h), Image.Resampling.LANCZOS) if canvas.size != (w, h) else canvas
    outp = Path(args.out).expanduser().resolve() if args.out else Path(args.img).expanduser().resolve().with_name(f"{Path(args.img).stem}-{(f['id'] if f else f'{w}x{h}')}.png")
    outp.parent.mkdir(parents=True, exist_ok=True)
    final.save(outp, quality=95)
    plan.update(_to_target_coords(plan, W, H, w, h, protect))
    # assinatura: o validate só aceita fundo que saiu daqui (ou do save-external). Fundo sintetizado reprova.
    outp.with_suffix(outp.suffix + ".origem.json").write_text(json.dumps({"origem": "extend", "modo": modo, "base": str(Path(args.img).resolve()), "crop": crop, "expand": ex, "quando": now_iso()}, ensure_ascii=False, indent=2), encoding="utf-8")
    plan.update({"status": "ok", "out": str(outp), "modo": modo, "razao_modo": razao, "base": [W, H], "alvo": [w, h], "formato": f["id"] if f else None, "safe": f["safe"] if f else None, "outpaint": log or None})
    out(plan)
    return 0


# ----------------------------------------------------------------------------- render

def _resolve_asset(p: str | None, bases: list[Path]) -> str | None:
    if not p or re.match(r"^(https?:|file:|data:)", p) or Path(p).is_absolute():
        return p
    for b in bases:
        cand = (b / p).resolve()
        if cand.exists():
            return str(cand)
    return str((bases[0] / p).resolve())


def _fontes_html(fontes: list[dict], bases: list[Path]) -> str:
    partes = []
    google = []
    for f in fontes or []:
        if f.get("arquivo"):
            arq = _resolve_asset(f["arquivo"], bases)
            fmt = {"ttf": "truetype", "otf": "opentype", "woff2": "woff2", "woff": "woff"}.get(Path(arq).suffix.lower().lstrip("."), "truetype")
            partes.append(f"<style>@font-face{{font-family:\"{f['familia']}\";src:url(\"file://{arq}\") format(\"{fmt}\");font-weight:{f.get('peso', '100 900')};font-style:{f.get('estilo', 'normal')};}}</style>")
        elif f.get("google"):
            fam = f["familia"].replace(" ", "+")
            pesos = f.get("pesos", "400;700;900")
            google.append(f"family={fam}:wght@{pesos}")
    if google:
        partes.append(f"<link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?{'&'.join(google)}&display=block\">")
    return "\n".join(partes)


def build_html(peca: dict, peca_dir: Path) -> str:
    bases = [peca_dir, peca_dir.parent]
    p = json.loads(json.dumps(peca))
    p["_dir"] = str(peca_dir)
    if p.get("fundo", {}).get("src"):
        p["fundo"]["src"] = _resolve_asset(p["fundo"]["src"], bases)
    for e in p.get("elementos", []):
        if e.get("src"):
            e["src"] = _resolve_asset(e["src"], bases)
    tpl = TEMPLATE.read_text(encoding="utf-8")
    tpl = tpl.replace("<!--FONTES-->", _fontes_html(p.get("fontes", []), bases))
    return tpl.replace("/*PECA*/{}/*PECA*/", json.dumps(p, ensure_ascii=False))


def _dom_report(dom: str) -> dict:
    els = []
    for m in re.finditer(r"<div class=\"el ([a-z]+)\"([^>]*)>", dom):
        attrs = {k: html.unescape(v) for k, v in re.findall(r"data-([a-z]+)=\"([^\"]*)\"", m.group(2))}
        els.append({"classe": m.group(1), **attrs})
    ready = 'data-ready="1"' in dom
    return {"ready": ready, "elementos": els}


def render_peca(peca_path: Path, out_path: Path | None, debug: bool = False, somente=None) -> dict:
    peca = json.loads(peca_path.read_text(encoding="utf-8"))
    if debug:
        peca["debug"] = True
    if somente is not None:
        peca["somente"] = somente
    if "canvas" not in peca:
        f = formato_by_id(peca.get("formato", ""))
        if not f:
            raise ValueError("peça sem `canvas` e sem `formato` conhecido")
        peca["canvas"] = {"w": f["w"], "h": f["h"]}
        peca.setdefault("safe", f["safe"])
    elif "safe" not in peca and peca.get("formato"):
        f = formato_by_id(peca["formato"])
        if f:
            peca["safe"] = f["safe"]
    w, h = int(peca["canvas"]["w"]), int(peca["canvas"]["h"])
    html_p = peca_path.with_suffix(".html") if not debug else peca_path.with_name(peca_path.stem + "-debug.html")
    if somente is not None:
        html_p = peca_path.with_name(f"{peca_path.stem}-camada-{somente}.html")
    html_p.write_text(build_html(peca, peca_path.parent), encoding="utf-8")
    url = "file://" + str(html_p)
    if out_path is None:
        out_path = peca_path.parent.parent / (peca.get("saida") or (peca_path.stem + ".png"))
        if debug:
            out_path = out_path.with_name(out_path.stem + "-debug.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    r = chrome_run(url, [f"--window-size={w},{h}", f"--screenshot={out_path}"])
    if not out_path.exists():
        raise RuntimeError("Chrome não gerou o PNG: " + (r.stderr or r.stdout)[-600:])
    im = Image.open(out_path)
    if im.size != (w, h):
        im = im.crop((0, 0, w, h)) if im.width >= w and im.height >= h else im.resize((w, h))
        im.save(out_path)
    if somente is not None:
        return {"out": str(out_path), "w": w, "h": h, "somente": somente, "ready": True, "elementos": []}
    if peca.get("jpg"):
        Image.open(out_path).convert("RGB").save(out_path.with_suffix(".jpg"), quality=int(peca.get("jpg_qualidade", 88)), optimize=True)
    d = chrome_run(url, [f"--window-size={w},{h}", "--dump-dom"])
    rep = _dom_report(d.stdout)
    rep.update({"out": str(out_path), "html": str(html_p), "w": w, "h": h, "formato": peca.get("formato"), "kb": out_path.stat().st_size // 1024})
    rep_p = peca_path.with_suffix(".report.json")
    rep_p.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    return rep


def cmd_render(args) -> int:
    peca_path = Path(args.peca).expanduser().resolve()
    if not peca_path.exists():
        return die(f"peça não existe: {peca_path}")
    outp = Path(args.out).expanduser().resolve() if args.out else None
    rep = render_peca(peca_path, outp, args.debug)
    estouros = [e for e in rep["elementos"] if e.get("overflow") == "1"]
    rep["status"] = "ok" if rep["ready"] and not estouros else ("estourou" if estouros else "incompleto")
    rep["estouros"] = [e.get("papel") for e in estouros]
    out(rep)
    return 0 if rep["status"] == "ok" else 2


# ----------------------------------------------------------------------------- export em camadas (PSD + SVG)

def _peca_com_canvas(peca_path: Path) -> dict:
    peca = json.loads(peca_path.read_text(encoding="utf-8"))
    f = formato_by_id(peca.get("formato", "")) if peca.get("formato") else None
    if "canvas" not in peca and f:
        peca["canvas"] = {"w": f["w"], "h": f["h"]}
    return peca


def cmd_export_psd(args) -> int:
    """PSD em camadas: fundo, scrims, cada elemento rasterizado numa camada própria (texto vira pixel,
    mas separado e móvel; o SVG é o caminho para texto editável)."""
    if not venv_python():
        return die(f"ambiente de camadas não instalado. Rode: {VENV_FIX}")
    peca_path = Path(args.peca).expanduser().resolve()
    peca = _peca_com_canvas(peca_path)
    w, h = int(peca["canvas"]["w"]), int(peca["canvas"]["h"])
    raiz = peca_path.parent.parent
    cam_dir = raiz / "_work" / "camadas" / peca_path.stem
    cam_dir.mkdir(parents=True, exist_ok=True)
    camadas = []
    # fundo
    fundo = peca.get("fundo") or {}
    fp = cam_dir / "00-fundo.png"
    if fundo.get("tipo") == "imagem" and fundo.get("src"):
        src = _resolve_asset(fundo["src"], [peca_path.parent, raiz])
        im = Image.open(src).convert("RGBA")
        fit = fundo.get("fit", "cover")
        im = ImageOps.fit(im, (w, h), Image.Resampling.LANCZOS) if fit == "cover" else (im.resize((w, h)) if fit == "stretch" else ImageOps.pad(im, (w, h), color=(0, 0, 0, 0)))
        im.save(fp)
    else:
        cor = fundo.get("cor", "#111111").lstrip("#")
        Image.new("RGBA", (w, h), tuple(int(cor[i:i + 2], 16) for i in (0, 2, 4)) + (255,)).save(fp)
    camadas.append({"nome": "Fundo", "png": str(fp), "x": 0, "y": 0})
    # scrims
    if peca.get("scrims") or peca.get("scrim"):
        rep = render_peca(peca_path, cam_dir / "01-scrims.png", somente="scrims")
        camadas.append({"nome": "Scrim", "png": rep["out"], "x": 0, "y": 0})
    # elementos, cada um isolado
    for i, e in enumerate(peca.get("elementos", [])):
        nome = f"{e.get('papel') or e.get('tipo')}"
        cam_png = cam_dir / f"{i + 2:02d}-{re.sub(r'[^a-z0-9]+', '-', nome.lower())}.png"
        rep = render_peca(peca_path, cam_png, somente=i)
        # recorta ao box para a camada ficar leve e posicionada
        b = e.get("box") or {"x": 0, "y": 0, "w": w, "h": h}
        im = Image.open(rep["out"]).convert("RGBA")
        x0, y0 = max(0, int(b["x"]) - 4), max(0, int(b["y"]) - 4)
        x1, y1 = min(w, int(b["x"] + b["w"]) + 4), min(h, int(b["y"] + b["h"]) + 4)
        im.crop((x0, y0, x1, y1)).save(cam_png)
        camadas.append({"nome": f"{nome} — {e.get('texto', '')[:40]}" if e.get("texto") else nome, "png": str(cam_png), "x": x0, "y": y0})
    spec = cam_dir / "camadas.json"
    spec.write_text(json.dumps({"w": w, "h": h, "camadas": camadas}, ensure_ascii=False, indent=2), encoding="utf-8")
    psd_out = Path(args.out).expanduser().resolve() if args.out else raiz / (peca.get("saida", peca_path.stem + ".png")).replace(".png", ".psd")
    r = run_cmd([venv_python(), str(ROOT / "scripts" / "psd_io.py"), "write", str(psd_out), str(spec)], timeout=600)
    if r.returncode != 0:
        return die("falha ao gravar PSD: " + r.stderr[-400:])
    out({"status": "ok", "psd": str(psd_out), "camadas": [c["nome"] for c in camadas]})
    return 0


def _svg_escape(t: str) -> str:
    return html.escape(t, quote=True)


def cmd_export_svg(args) -> int:
    """SVG com texto editável (abre no Illustrator/Figma). Tamanhos de fonte vêm do report do render,
    então o SVG bate com o PNG. Fundo e imagens vão embutidos em base64."""
    import base64, io
    peca_path = Path(args.peca).expanduser().resolve()
    peca = _peca_com_canvas(peca_path)
    w, h = int(peca["canvas"]["w"]), int(peca["canvas"]["h"])
    raiz = peca_path.parent.parent
    rep_p = peca_path.with_suffix(".report.json")
    sizes, lines = {}, {}
    if rep_p.exists():
        rep = json.loads(rep_p.read_text(encoding="utf-8"))
        # report lista elementos na ordem dos elementos da peça
        for i, e in enumerate(rep.get("elementos", [])):
            sizes[i] = float(e["size"]) if e.get("size") else None
            if e.get("lines"):
                try:
                    lines[i] = json.loads(e["lines"])
                except Exception:
                    pass

    def data_uri(path: str) -> str:
        p = _resolve_asset(path, [peca_path.parent, raiz])
        im = Image.open(p)
        buf = io.BytesIO()
        if im.mode in ("RGBA", "LA", "P"):
            im.convert("RGBA").save(buf, "PNG"); mime = "image/png"
        else:
            im.convert("RGB").save(buf, "JPEG", quality=92); mime = "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()

    partes = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    google = [f["familia"].replace(" ", "+") + ":wght@" + f.get("pesos", "400;700;900") for f in peca.get("fontes", []) if f.get("google")]
    if google:
        partes.append("<style>@import url('https://fonts.googleapis.com/css2?" + "&amp;".join("family=" + g for g in google) + "&amp;display=block');</style>")
    fundo = peca.get("fundo") or {}
    if fundo.get("tipo") == "imagem" and fundo.get("src"):
        pres = {"cover": "xMidYMid slice", "contain": "xMidYMid meet", "stretch": "none"}.get(fundo.get("fit", "cover"), "xMidYMid slice")
        partes.append(f'<image id="fundo" x="0" y="0" width="{w}" height="{h}" preserveAspectRatio="{pres}" xlink:href="{data_uri(fundo["src"])}"/>')
    else:
        partes.append(f'<rect id="fundo" x="0" y="0" width="{w}" height="{h}" fill="{fundo.get("cor", "#111")}"/>')
    defs = []
    for k, sc in enumerate(peca.get("scrims") or ([peca["scrim"]] if peca.get("scrim") else [])):
        if sc.get("tipo") == "gradiente":
            d = sc.get("direcao", "to bottom")
            x1, y1, x2, y2 = {"to bottom": (0, 0, 0, 1), "to top": (0, 1, 0, 0), "to right": (0, 0, 1, 0), "to left": (1, 0, 0, 0)}.get(d, (0, 0, 0, 1))
            defs.append(f'<linearGradient id="scrim{k}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"><stop offset="{sc.get("inicio", "0%")}" stop-color="{sc.get("de", "rgba(0,0,0,0)")}"/><stop offset="{sc.get("fim", "100%")}" stop-color="{sc.get("para", "rgba(0,0,0,.6)")}"/></linearGradient>')
            partes.append(f'<rect x="0" y="0" width="{w}" height="{h}" fill="url(#scrim{k})"/>')
        else:
            partes.append(f'<rect x="0" y="0" width="{w}" height="{h}" fill="{sc.get("cor", "rgba(0,0,0,.35)")}"/>')
    if defs:
        partes.insert(1, "<defs>" + "".join(defs) + "</defs>")
    for i, e in enumerate(peca.get("elementos", [])):
        b = e.get("box") or {}
        x, y, bw, bh = float(b.get("x", 0)), float(b.get("y", 0)), float(b.get("w", 0)), float(b.get("h", 0))
        papel = _svg_escape(e.get("papel") or e.get("tipo") or "")
        if e.get("tipo") == "imagem" and e.get("src"):
            pres = {"contain": "xMidYMid meet", "cover": "xMidYMid slice"}.get(e.get("fit", "contain"), "xMidYMid meet")
            al = {"left": "xMin", "center": "xMid", "right": "xMax"}.get(e.get("align", "left"), "xMin") + {"top": "YMin", "middle": "YMid", "bottom": "YMax"}.get(e.get("valign", "top"), "YMin")
            pres = pres.replace("xMidYMid", al)
            partes.append(f'<image id="{papel}" x="{x}" y="{y}" width="{bw}" height="{bh}" preserveAspectRatio="{pres}" xlink:href="{data_uri(e["src"])}"/>')
        elif e.get("tipo") == "forma":
            partes.append(f'<rect id="{papel}" x="{x}" y="{y}" width="{bw}" height="{bh}" rx="{e.get("raio", 0)}" fill="{e.get("cor", "#fff")}" opacity="{e.get("opacidade", 1)}"/>')
        elif e.get("tipo") == "botao":
            fs = e.get("tamanho") or round(bh * 0.42)
            partes.append(f'<g id="{papel}"><rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="{e.get("raio", bh / 2)}" fill="{e.get("fundo", "#fff")}"/>'
                          f'<text x="{x + bw / 2}" y="{y + bh / 2}" text-anchor="middle" dominant-baseline="central" font-family="{_svg_escape(e.get("fonte", "sans-serif"))}" font-weight="{e.get("peso", 800)}" font-size="{fs}" fill="{e.get("cor", "#111")}">{_svg_escape(e.get("texto", "").upper() if e.get("caixa") == "upper" else e.get("texto", ""))}</text></g>')
        elif e.get("tipo") == "texto":
            fs = sizes.get(i) or e.get("tamanho") or e.get("max") or 40
            lh = float(e.get("lineHeight", 1.05)) * fs
            texto = e.get("texto", "")
            if e.get("caixa") == "upper": texto = texto.upper()
            linhas = lines.get(i) or re.sub(r"\*\*|//|\{\{|\}\}", "", texto).split("\n")
            total = lh * len(linhas)
            va = e.get("valign", "top")
            y0 = y + (0 if va == "top" else (bh - total) / 2 if va == "middle" else bh - total)
            anchor = {"left": "start", "center": "middle", "right": "end"}.get(e.get("align", "left"), "start")
            tx = x if anchor == "start" else (x + bw / 2 if anchor == "middle" else x + bw)
            fam = _svg_escape(e.get("fonte", "sans-serif"))
            acentos = [a.upper() if e.get("caixa") == "upper" else a for a in re.findall(r"\{\{(.+?)\}\}", e.get("texto", ""))]
            spans = []
            for n, ln in enumerate(linhas):
                ln_html = _svg_escape(ln)
                for a in acentos:  # {{acento}} vira tspan colorido, onde a palavra aparecer na linha
                    if a and a in ln:
                        ln_html = ln_html.replace(_svg_escape(a), f'<tspan fill="{e.get("acento", "inherit")}">{_svg_escape(a)}</tspan>')
                spans.append(f'<tspan x="{tx}" y="{y0 + lh * n + fs * 0.8}">{ln_html}</tspan>')
            partes.append(f'<text id="{papel}" font-family="{fam}" font-weight="{e.get("peso", 700)}" font-size="{fs}" fill="{e.get("cor", "#fff")}" text-anchor="{anchor}" letter-spacing="{e.get("letterSpacing", "0")}">{"".join(spans)}</text>')
    partes.append("</svg>")
    svg_out = Path(args.out).expanduser().resolve() if args.out else raiz / (peca.get("saida", peca_path.stem + ".png")).replace(".png", ".svg")
    svg_out.write_text("\n".join(partes), encoding="utf-8")
    out({"status": "ok", "svg": str(svg_out), "kb": svg_out.stat().st_size // 1024, "nota": "Texto editável; as fontes precisam estar instaladas na máquina que abrir o SVG."})
    return 0


# ----------------------------------------------------------------------------- vídeo

def _ffprobe(path: Path) -> dict:
    r = run_cmd(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,duration,r_frame_rate", "-of", "json", str(path)], timeout=60)
    try:
        st = json.loads(r.stdout)["streams"][0]
        return {"w": int(st["width"]), "h": int(st["height"]), "dur": float(st.get("duration") or 0)}
    except Exception:
        return {}


def _higgs_video_job(model: str, args_extra: list[str], params_match: dict, log_dir: Path | None, rotulo: str) -> tuple[Path | None, dict]:
    """Roda um job de vídeo no Higgsfield CLI (`--wait`), baixa o resultado e registra o log."""
    st = higgsfield_status()
    if not st.get("available"):
        return None, {"erro": "Higgsfield CLI indisponível", **st}
    args = ["higgsfield", "generate", "create", model, *args_extra, "--json"]
    job, raw = _higgsfield_gerar(args, model, params_match, timeout=3600)
    url = None
    try:
        d = json.loads(raw)
        url = d.get("result_url") or d.get("video_url")
    except Exception:
        pass
    if not url:
        urls = [u for u in re.findall(r"https://[^\s\"'\\]+\.(?:mp4|mov|webm)[^\s\"'\\]*", raw) if "_min." not in u]
        url = urls[-1] if urls else None
    if not url:
        return None, {"erro": f"{rotulo}: sem URL de resultado", "stdout": raw[-600:]}
    tmp = Path(tempfile.mkstemp(suffix=".mp4", prefix=f"replicai-{rotulo}-")[1])
    baixar(url, tmp)
    log = {"provider": "higgsfield_cli", "model": model, "job_id": job, "url": url, "params": params_match}
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / f"{rotulo}-{str(job)[:8]}.json").write_text(json.dumps({**log, "stdout": raw[-3000:]}, indent=2, ensure_ascii=False), encoding="utf-8")
    return tmp, log


def _faixas_de_corte_vazias(src: Path, dur: float, w: int, h: int, sw: int, sh: int, limite: float = 0.10, n: int = 4) -> tuple[bool, dict]:
    """Para encher o quadro sem faixas (cover), quanto seria cortado — e o que está lá?
    Mede a densidade de detalhe (bordas) nas faixas que sairiam, comparada ao miolo.
    Faixa só de fundo (fração pequena e sem tipografia/logo) pode sair; conteúdo, não."""
    if not sw or not sh:
        return False, {}
    fator = max(w / sw, h / sh)
    ew, eh = sw * fator, sh * fator
    dx = max(0.0, (ew - w) / fator / 2)   # px de fonte cortados de cada lado
    dy = max(0.0, (eh - h) / fator / 2)
    frac = max(dx / sw, dy / sh)
    info = {"corte_px": [round(dx), round(dy)], "fracao": round(frac, 3)}
    if frac > limite:
        info["motivo"] = f"corte de {int(frac*100)}% passa do limite de {int(limite*100)}%"
        return False, info
    if frac <= 0.001:
        info["motivo"] = "mesma proporção"
        return True, info
    with tempfile.TemporaryDirectory() as tmp:
        densidades = []
        for k in range(n):
            t = (dur * (k + 0.5) / n) if dur else k
            f = Path(tmp) / f"c{k}.png"
            run_cmd(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", str(f)], timeout=120)
            if not f.exists():
                continue
            im = Image.open(f).convert("L")
            bordas = im.filter(ImageFilter.FIND_EDGES)
            W, H = im.size
            ax, ay = int(round(dx * W / sw)), int(round(dy * H / sh))
            faixas, miolo = [], bordas.crop((ax, ay, W - ax, H - ay))
            if ax > 2:
                faixas += [bordas.crop((0, 0, ax, H)), bordas.crop((W - ax, 0, W, H))]
            if ay > 2:
                faixas += [bordas.crop((0, 0, W, ay)), bordas.crop((0, H - ay, W, H))]
            if not faixas:
                continue
            e_faixa = max(ImageStat.Stat(x).mean[0] for x in faixas)
            e_miolo = max(1e-6, ImageStat.Stat(miolo).mean[0])
            densidades.append(e_faixa / e_miolo)
        if not densidades:
            return False, {**info, "motivo": "não consegui amostrar quadros"}
        razao = max(densidades)
        info["detalhe_faixa_vs_miolo"] = round(razao, 2)
        # faixa com até 35% do detalhe do miolo = fundo (gradiente, textura); acima disso tem conteúdo
        ok = razao <= 0.35
        info["motivo"] = "faixas são fundo, corte seguro" if ok else "há conteúdo (texto/logo/assunto) nas faixas que sairiam"
        return ok, info


def _bordas_estendiveis(src: Path, dur: float, eixo: str, banda_frac: float = 0.05, n: int = 3, faixa: int = 8) -> tuple[bool, float]:
    """A borda que vai ser esticada é uniforme ao longo dela (cor chapada, gradiente perpendicular)?
    Mesma pergunta que o `extend` faz nas estáticas, agora amostrando quadros do vídeo."""
    piores = []
    with tempfile.TemporaryDirectory() as tmp:
        for k in range(n):
            t = (dur * (k + 0.5) / n) if dur else k
            f = Path(tmp) / f"e{k}.png"
            run_cmd(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", str(f)], timeout=120)
            if not f.exists():
                continue
            im = Image.open(f).convert("RGB"); W, H = im.size
            # a borda é esticada NA DIREÇÃO da faixa: o que precisa ser estável é a variação nessa direção,
            # não ao longo da borda (uma linha cheia de logos estica para baixo sem problema).
            if eixo == "vertical":   # faixa em cima/embaixo: achata na vertical, preserva o desenho horizontal
                tiras = [im.crop((0, 0, W, faixa)), im.crop((0, H - faixa, W, H))]
                achatar = lambda t_: t_.resize((t_.width, 1), Image.Resampling.BOX).resize(t_.size, Image.Resampling.BILINEAR)
            else:                    # faixa nas laterais: achata na horizontal
                tiras = [im.crop((0, 0, faixa, H)), im.crop((W - faixa, 0, W, H))]
                achatar = lambda t_: t_.resize((1, t_.height), Image.Resampling.BOX).resize(t_.size, Image.Resampling.BILINEAR)
            for t_ in tiras:
                d = ImageStat.Stat(ImageChops.difference(t_, achatar(t_))).mean
                piores.append(sum(d) / 3)
    if not piores:
        return False, 0.0
    pior = max(piores)
    # faixa pequena perdoa mais variação: 5% do lado estica de 6px sem denunciar; 20% não
    limite = 20.0 if banda_frac <= 0.08 else (12.0 if banda_frac <= 0.15 else 6.0)
    return pior < limite, round(pior, 2)


def _bordas_estaticas(src: Path, dur: float, n: int = 6, faixa: float = 0.08) -> tuple[bool, float]:
    """As bordas do vídeo mudam ao longo do tempo? Mede a diferença média das faixas laterais
    entre quadros amostrados. Bordas paradas → a placa estática (mesmo motor das estáticas) serve."""
    with tempfile.TemporaryDirectory() as tmp:
        frames = []
        for k in range(n):
            t = (dur * (k + 0.5) / n) if dur else k
            f = Path(tmp) / f"f{k}.png"
            run_cmd(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", "-vf", "scale=320:-2", str(f)], timeout=120)
            if f.exists():
                frames.append(Image.open(f).convert("L"))
        if len(frames) < 2:
            return True, 0.0
        W, H = frames[0].size
        s_ = max(2, int(W * faixa)); t_ = max(2, int(H * faixa))
        maior = 0.0
        for a, b in zip(frames, frames[1:]):
            for box in ((0, 0, s_, H), (W - s_, 0, W, H), (0, 0, W, t_), (0, H - t_, W, H)):
                d = ImageStat.Stat(ImageChops.difference(a.crop(box), b.crop(box))).mean[0]
                maior = max(maior, d)
        return maior < 4.0, round(maior, 2)


def cmd_video(args) -> int:
    """Adapta um vídeo a outro formato com a mesma régua das estáticas: o vídeo inteiro cabe no
    quadro novo (sem cortes) e a sobra é o FUNDO CONTINUADO, nunca desfoque.
      plate   — o quadro-chave passa pelo motor das estáticas (`extend`: stretch/mirror/doador/outpaint)
                e vira a placa atrás do vídeo. Certo quando as bordas do vídeo são paradas. Sem crédito de vídeo.
      reframe — continuação generativa do próprio vídeo (Higgsfield `reframe`), ancorada na placa do
                quadro-chave para bater com a adaptação estática. Para bordas em movimento. Custa crédito.
      solid   — campo chapado na cor da marca (quando o brief pede).
      blur    — só se pedido explicitamente; o validate reprova.
    Upscale (`bytedance_video_upscale`) entra sozinho quando a resolução da fonte não sustenta o destino.
    Por cima, a camada de texto/logo da peça JSON (`somente: elementos`)."""
    if not shutil.which("ffmpeg"):
        return die("ffmpeg não encontrado. Instale com: brew install ffmpeg")
    src = Path(args.video).expanduser().resolve()
    if not src.exists():
        return die(f"vídeo não existe: {src}")
    w, h, f = resolve_target(args)
    info = _ffprobe(src)
    sw, sh, dur = info.get("w", 0), info.get("h", 0), info.get("dur", 0.0)
    ax, ay = _parse_anchor(args.anchor)
    peca_path = Path(args.peca).expanduser().resolve() if args.peca else None
    raiz = peca_path.parent.parent if peca_path else src.parent
    work = raiz / "_work"; work.mkdir(parents=True, exist_ok=True)
    log_dir = raiz / "_logs"
    logs: dict = {}
    protect = parse_bbox(args.protect) if args.protect else None

    # 1) enquadramento primeiro: ele decide o quanto a fonte precisa crescer
    fonte = src
    modo = args.mode
    estaticas, mov = _bordas_estaticas(src, dur)
    corte_ok, corte_info = _faixas_de_corte_vazias(src, dur, w, h, sw, sh, limite=args.corte_max)
    eixo_ext = "vertical" if (w / h) < (sw / sh) else "horizontal"   # contain: só um eixo ganha faixa
    # quanto do lado final a faixa ocupa (as duas somadas)
    _prov = plan_fit(sw, sh, w, h, protect, "contain", (ax, ay), 0.0); _prov.update(_to_target_coords(_prov, sw, sh, w, h, protect))
    _bb = _prov["base_box"]
    banda_frac = ((h - (_bb[3] - _bb[1])) / h) if eixo_ext == "vertical" else ((w - (_bb[2] - _bb[0])) / w)
    estendiveis, unif = _bordas_estendiveis(src, dur, eixo_ext, banda_frac)
    # o reframe só entrega proporções fixas; longe delas ele cortaria a peça
    _ARS = {"21:9": 21 / 9, "16:9": 16 / 9, "4:3": 4 / 3, "1:1": 1.0, "3:4": 3 / 4, "9:16": 9 / 16}
    alvo_ar = min(_ARS, key=lambda k: abs(_ARS[k] - w / h))
    reframe_serve = abs(_ARS[alvo_ar] - w / h) / (w / h) <= 0.06
    if modo == "auto":
        if abs((sw / sh) - (w / h)) < 0.005:
            modo = "none"          # mesma proporção: só escala
        elif corte_ok:
            modo = "cover"         # a faixa que sairia é fundo: enche o quadro, zero faixas
        elif estendiveis:
            modo = "edge"          # borda uniforme: estica quadro a quadro (acompanha a animação, custo zero)
        elif estaticas:
            modo = "plate"         # bordas paradas no tempo: placa contínua do quadro-chave
        elif reframe_serve and higgsfield_status().get("available"):
            modo = "reframe"       # cena em movimento nas bordas: continuação generativa
        else:
            modo = "plate"

    # 2) upscale: cobrir o quadro inteiro (cover/none/reframe) pede max; dentro da placa, min
    if sw and sh:
        escala_necessaria = (max(w / sw, h / sh) if modo in ("cover", "none", "reframe", "blur") else min(w / sw, h / sh))  # edge/plate: o vídeo ocupa a base_box
    else:
        escala_necessaria = 1.0
    if args.upscale != "no" and escala_necessaria > 1.15:
        alvo_res = args.upscale if args.upscale != "auto" else ("4k" if max(w, h) > 2200 else ("2k" if max(w, h) > 1300 else "1080p"))
        # reaproveita um upscale já feito nesta pasta (o mesmo vídeo serve todos os formatos)
        precisa_w = int(sw * escala_necessaria)
        prontos = []
        for cand in sorted(work.glob(f"{src.stem}-upscale-*.mp4")):
            vi = _ffprobe(cand)
            if vi.get("w", 0) >= precisa_w * 0.98:
                prontos.append((vi["w"], cand, vi))
        if prontos:
            prontos.sort()
            _, cand, vi = prontos[0]
            fonte = cand; sw, sh, info = vi["w"], vi["h"], vi
            logs["upscale"] = {"reaproveitado": str(cand), "w": sw, "h": sh}
            args_upscale_feito = True
        else:
            args_upscale_feito = False
    else:
        args_upscale_feito = True   # nada a fazer
    if args.upscale != "no" and escala_necessaria > 1.15 and not args_upscale_feito:
        up, lg = _higgs_video_job("bytedance_video_upscale", ["--video", str(src), "--resolution", alvo_res, "--preset", args.preset, "--fps", "30"],
                                  {"resolution": alvo_res}, log_dir, "upscale")
        if up:
            fonte = work / f"{src.stem}-upscale-{alvo_res}.mp4"; shutil.move(str(up), fonte)
            info = _ffprobe(fonte); sw, sh = info.get("w", sw), info.get("h", sh)
            logs["upscale"] = lg
        else:
            # sem o modelo, sobe localmente (lanczos + leve nitidez): melhor que escalar na hora do overlay,
            # e fica registrado que foi upscale local, não modelo
            destino_w = int(round(sw * escala_necessaria / 2) * 2); destino_h = int(round(sh * escala_necessaria / 2) * 2)
            local = work / f"{src.stem}-upscale-local-{destino_w}x{destino_h}.mp4"
            r_ = run_cmd(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf",
                          f"scale={destino_w}:{destino_h}:flags=lanczos,unsharp=5:5:0.6:5:5:0.0", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "medium", "-c:a", "copy", str(local)], timeout=3600)
            if local.exists():
                fonte = local; info = _ffprobe(fonte); sw, sh = info.get("w", sw), info.get("h", sh)
                logs["upscale"] = {**lg, "fallback": "ffmpeg_lanczos", "saida": f"{sw}x{sh}"}
                print(f"AVISO: upscale por modelo não rodou ({lg.get('erro')}); usei upscale local lanczos para {sw}x{sh}.", file=sys.stderr)
            else:
                logs["upscale"] = lg
                print(f"AVISO: upscale não rodou ({lg.get('erro')}); seguindo com a fonte original ({sw}x{sh}).", file=sys.stderr)

    # 3) placa: quadro-chave estendido pelo motor das estáticas
    poster = work / f"{src.stem}-quadro.png"
    run_cmd(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, dur / 2):.2f}", "-i", str(fonte), "-frames:v", "1", str(poster)], timeout=120)
    if not poster.exists():
        return die("não consegui extrair o quadro-chave do vídeo")
    plano = plan_fit(sw, sh, w, h, protect, "contain", (ax, ay), 0.0)
    plano_cover = corte_info
    plano.update(_to_target_coords(plano, sw, sh, w, h, protect))
    bb = plano["base_box"]  # onde o vídeo cai no canvas final
    placa = work / f"{peca_path.stem if peca_path else src.stem}-placa.png"
    if modo in ("plate", "reframe") and placa.exists() and placa.with_suffix(placa.suffix + ".origem.json").exists() and not args.refazer_placa:
        try:
            logs["placa"] = json.loads(placa.with_suffix(placa.suffix + ".origem.json").read_text(encoding="utf-8")); logs["placa"]["reaproveitada"] = True
        except Exception:
            pass
    elif modo in ("plate", "reframe"):
        # estende o quadro-chave com o motor das estáticas (modo do extend: auto → stretch/mirror/outpaint)
        class A: pass
        a = A(); a.img = str(poster); a.formato = args.formato; a.to = args.to; a.protect = args.protect; a.strategy = "contain"
        a.anchor = args.anchor; a.folga = 0.0; a.mode = args.plate_mode; a.cor = args.cor; a.out = str(placa)
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_extend(a)
        if rc != 0 or not placa.exists():
            return die("não consegui montar a placa a partir do quadro-chave: " + buf.getvalue()[-300:])
        try:
            logs["placa"] = json.loads(buf.getvalue())
            logs["placa"].pop("outpaint", None)
        except Exception:
            pass

    inputs = ["-i", str(fonte)]
    if modo == "none":
        graph = f"[0:v]scale={w}:{h}[v0]"
    elif modo == "edge":
        # estica a borda do próprio vídeo, quadro a quadro: o fundo continua e continua animando
        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
        if eixo_ext == "vertical":
            faixas = [("tp", bb[1], "crop=iw:6:0:0"), ("bt", h - bb[3], "crop=iw:6:0:ih-6")]
            escala = lambda n: f"scale={bw}:{n}:flags=lanczos"
            empilha = "vstack"
        else:
            faixas = [("eq", bb[0], "crop=6:ih:0:0"), ("dr", w - bb[2], "crop=6:ih:iw-6:0")]
            escala = lambda n: f"scale={n}:{bh}:flags=lanczos"
            empilha = "hstack"
        ativas = [(nome, n, corte) for nome, n, corte in faixas if n > 0]
        saidas = [f"[s{k}]" for k in range(1 + len(ativas))]
        partes = [f"[0:v]split={len(saidas)}" + "".join(saidas)]
        partes.append(f"{saidas[0]}scale={bw}:{bh}:flags=lanczos[fg]")
        for k, (nome, n, corte) in enumerate(ativas, start=1):
            partes.append(f"{saidas[k]}{corte},{escala(n)}[{nome}]")
        ordem = []
        if ativas and ativas[0][0] in ("tp", "eq"):
            ordem.append(f"[{ativas[0][0]}]")
        ordem.append("[fg]")
        for nome, _, _ in ativas:
            if nome in ("bt", "dr"):
                ordem.append(f"[{nome}]")
        graph = ";".join(partes) + f";{''.join(ordem)}{empilha}=inputs={len(ordem)}[v0]"
    elif modo == "cover":
        # enche o quadro inteiro; o corte sai só do fundo, ancorado onde a pessoa pediu
        graph = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
                 f"crop={w}:{h}:(iw-{w})*{ax:.3f}:(ih-{h})*{ay:.3f}[v0]")
    elif modo == "plate":
        inputs = ["-loop", "1", "-i", str(placa), "-i", str(fonte)]
        graph = f"[0:v]scale={w}:{h}[bg];[1:v]scale={bb[2]-bb[0]}:{bb[3]-bb[1]}[fg];[bg][fg]overlay={bb[0]}:{bb[1]}:shortest=1:format=auto[v0]"
    elif modo == "reframe":
        if not reframe_serve:
            return die(f"reframe não serve para {w}x{h}: o modelo só entrega {list(_ARS)}, e a proporção mais próxima ({alvo_ar}) cortaria a peça. Use --mode edge, plate ou solid.")
        res = "1080p" if max(w, h) >= 1080 else "720p"
        fonte_rf = fonte
        if 0 < dur < 5.5:  # o reframe recusa vídeo curto (< ~5 s): repete até 6 s e corta de volta depois
            fonte_rf = work / f"{src.stem}-loop6s.mp4"
            run_cmd(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", str(int(6 / dur) + 1), "-i", str(fonte), "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-an", str(fonte_rf)], timeout=600)
        extra = ["--video", str(fonte_rf), "--aspect_ratio", alvo_ar, "--resolution", res, "--start-image", str(placa)]
        if dur > 15:  # o modelo só aceita duration acima de 15 s (máx. 60)
            extra += ["--duration", f"{min(dur, 60):.1f}"]
        rf, lg = _higgs_video_job("reframe", extra, {"aspect_ratio": alvo_ar}, log_dir, "reframe")
        logs["reframe"] = lg
        if not rf:
            print(f"AVISO: reframe não rodou ({lg.get('erro')}); usando placa estática.", file=sys.stderr)
            modo = "plate"
            inputs = ["-loop", "1", "-i", str(placa), "-i", str(fonte)]
            graph = f"[0:v]scale={w}:{h}[bg];[1:v]scale={bb[2]-bb[0]}:{bb[3]-bb[1]}[fg];[bg][fg]overlay={bb[0]}:{bb[1]}:shortest=1:format=auto[v0]"
        else:
            rfp = work / f"{src.stem}-reframe-{alvo_ar.replace(':', 'x')}.mp4"; shutil.move(str(rf), rfp)
            inputs = ["-i", str(rfp), "-i", str(fonte)]  # [1] = áudio original
            graph = f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}[v0]"
    elif modo == "solid":
        cor = (args.cor or "#000000").lstrip("#")
        inputs = ["-f", "lavfi", "-i", f"color=c=0x{cor}:s={w}x{h}:r=30", "-i", str(fonte)]
        graph = f"[1:v]scale={bb[2]-bb[0]}:{bb[3]-bb[1]}[fg];[0:v][fg]overlay={bb[0]}:{bb[1]}:shortest=1:format=auto[v0]"
    elif modo == "blur":
        raio = max(8, min(w, h) // 25)
        graph = (f"[0:v]split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=luma_radius={raio}:luma_power=2,eq=brightness=-0.06[bg];"
                 f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)*{ax:.3f}:(H-h)*{ay:.3f}:format=auto[v0]")
    else:
        return die(f"modo desconhecido: {modo}")

    overlay = None
    if peca_path:
        rep = render_peca(peca_path, work / f"{peca_path.stem}-overlay.png", somente="elementos")
        overlay = Path(rep["out"])
        n_in = len([x for x in inputs if x == "-i"])
        inputs += ["-i", str(overlay)]
        graph += f";[v0][{n_in}:v]overlay=0:0:format=auto[v]"
    else:
        graph += ";[v0]copy[v]"
    if args.out:
        outp = Path(args.out).expanduser().resolve()
    elif peca_path:
        outp = raiz / f"{peca_path.stem}.mp4"
    else:
        outp = src.with_name(f"{src.stem}-{(f['id'] if f else f'{w}x{h}')}.mp4")
    outp.parent.mkdir(parents=True, exist_ok=True)
    audio_idx = {"plate": "1", "solid": "1", "reframe": "1"}.get(modo, "0")  # cover/none/blur: a própria fonte
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", graph, "-map", "[v]", "-map", f"{audio_idx}:a?", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "160k"]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]  # corta de volta na duração original (reframe de vídeo curto é feito em loop)
    cmd += ["-shortest", str(outp)]
    r = run_cmd(cmd, timeout=3600)
    if r.returncode != 0 or not outp.exists():
        return die("ffmpeg falhou: " + r.stderr[-600:])
    outp.with_suffix(outp.suffix + ".origem.json").write_text(json.dumps({"origem": "video", "modo": modo, "fonte": str(src), "fonte_usada": str(fonte), "upscale": bool(logs.get("upscale", {}).get("job_id")), "enquadramento": {"cover_possivel": corte_ok, **corte_info, "bordas_estendiveis": estendiveis, "eixo": eixo_ext}, "bordas_estaticas": estaticas, "movimento_bordas": mov, "placa": str(placa) if placa.exists() else None, "anchor": [ax, ay], "overlay": str(overlay) if overlay else None, "logs": logs, "quando": now_iso()}, ensure_ascii=False, indent=2), encoding="utf-8")
    poster_out = outp.with_suffix(".png")
    run_cmd(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, dur / 2):.2f}", "-i", str(outp), "-frames:v", "1", str(poster_out)], timeout=120)
    out({"status": "ok", "out": str(outp), "alvo": [w, h], "formato": f["id"] if f else None, "fonte": {"w": sw, "h": sh, "dur": dur}, "modo": modo,
         "enquadramento": {"cover_possivel": corte_ok, **corte_info, "bordas_estendiveis": estendiveis, "variacao_borda": unif, "faixa_do_lado": round(banda_frac, 3), "eixo": eixo_ext},
         "bordas_estaticas": estaticas, "movimento_bordas": mov, "upscale": logs.get("upscale"), "placa": logs.get("placa", {}).get("modo") if isinstance(logs.get("placa"), dict) else None,
         "reframe": logs.get("reframe"), "overlay": str(overlay) if overlay else None, "base_box": bb,
         "nota": "Vídeo inteiro preservado; sobra preenchida com o fundo continuado (placa do motor das estáticas ou reframe generativo). Texto queimado no original permanece."})
    return 0


# ----------------------------------------------------------------------------- validate

def _nums(text: str) -> set[str]:
    return set(re.findall(r"(?<![\w])\d[\d.,]*%?(?![\w])", text or ""))


# --------------------------------------------------------------------------- sobreposição
# A arte-mãe às vezes encosta de propósito: no KV da Consigaz o braço do mascote
# cobre o fim do "CANDIDATE-SE", e isso é gesto de apresentar, não defeito. O que
# não pode é a adaptação INVENTAR sobreposição, ou aumentar a que existia. Então a
# régua não é "zero", é "não mais do que a arte-mãe já fazia naquele mesmo par".

SOBREP_TOLERANCIA = 0.03      # 3 pontos de largura de folga sobre o que a mãe fazia
SOBREP_PISO = 0.02            # abaixo disso é encosto de borda, não sobreposição


def _chave_texto(s: str) -> str:
    """Compara textos entre a arte-mãe e a peça: a adaptação reescreve em caixa
    alta e marca realce com {{}} e **, então nada disso pode contar."""
    s = re.sub(r"\{\{|\}\}|\*\*", " ", s or "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _alfa(png: Path, w: int = 0, h: int = 0):
    import numpy as np
    from PIL import Image
    im = Image.open(png).convert("RGBA")
    if w and h and (im.width != w or im.height != h):
        im = im.resize((max(1, int(w)), max(1, int(h))))
    return np.asarray(im)[:, :, 3] > 24


def invasao_ret(ret, cima_mask, cima_xy) -> float:
    """Que fatia da LARGURA de um retângulo de tinta fica tapada por quem está
    por cima. Retângulo justo das letras dos dois lados — e por largura, não por
    área. Três réguas erradas até chegar nesta: área diz 2% quando um braço corta
    o topo das últimas letras; a caixa do texto conta o ar depois da última letra
    e inventa sobreposição na arte-mãe; e redesenhar o texto por fora com métrica
    de fonte não bate com o navegador (letter-spacing, kerning)."""
    rx, ry, rw, rh = [float(v) for v in ret]
    if rw < 1 or rh < 1:
        return 0.0
    cx, cy = cima_xy
    ch, cw = cima_mask.shape
    x0 = int(max(rx, cx)); x1 = int(min(rx + rw, cx + cw))
    y0 = int(max(ry, cy)); y1 = int(min(ry + rh, cy + ch))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    sub = cima_mask[y0 - int(cy):y1 - int(cy), x0 - int(cx):x1 - int(cx)]
    return int((sub.any(axis=0)).sum()) / rw


def _ret_da_tinta(mask, offx, offy):
    """Retângulo justo em volta do que é opaco."""
    import numpy as np
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return (offx + int(xs.min()), offy + int(ys.min()),
            int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))


def cobertura_da_mae(raiz: Path) -> dict:
    """Quanto cada camada de texto da arte-mãe já era coberta, e por quem.
    Devolve {chave_do_texto: {nome_do_png_de_cima: fração}}."""
    cj = raiz / "_work" / "camadas-psd" / "camadas.json"
    if not cj.exists():
        return {}
    try:
        d = json.loads(cj.read_text(encoding="utf-8"))
    except Exception:
        return {}
    cams = [c for c in d.get("camadas", []) if c.get("visivel") and c.get("png")]
    out: dict = {}
    for i, t in enumerate(cams):
        if t.get("tipo") != "type" or not (t.get("texto") or "").strip():
            continue
        p = Path(t["png"])
        bb = t.get("bbox") or [0, 0, 0, 0]
        if not p.exists():
            continue
        try:
            tm = _alfa(p)
        except Exception:
            continue
        ret = _ret_da_tinta(tm, bb[0], bb[1])
        if not ret:
            continue
        alvo = out.setdefault(_chave_texto(t["texto"]), {})
        for c in cams[i + 1:]:                       # só o que é desenhado DEPOIS cobre
            if c.get("tipo") == "type":
                continue
            q = Path(c["png"])
            cb = c.get("bbox") or [0, 0, 0, 0]
            if not q.exists():
                continue
            try:
                cm = _alfa(q)
            except Exception:
                continue
            f = invasao_ret(ret, cm, (cb[0], cb[1]))
            if f > 0:
                alvo[q.name] = max(alvo.get(q.name, 0.0), f)
    return out


def _caixa_da_tinta(el: dict, rep: dict | None, raiz: Path):
    """Onde a tinta do texto realmente está dentro da caixa. Medir a caixa inteira
    acusa sobreposição onde só há respiro: foi o que me enganou da primeira vez."""
    bx = el.get("box") or {}
    x, y, w, h = float(bx.get("x", 0)), float(bx.get("y", 0)), float(bx.get("w", 0)), float(bx.get("h", 0))
    if not rep:
        return x, y, w, h
    try:
        corpo = float(rep.get("size") or 0)
        linhas = json.loads(rep.get("lines") or "[]") or [el.get("texto") or ""]
    except Exception:
        return x, y, w, h
    if corpo <= 0:
        return x, y, w, h
    lh = float(el.get("lineHeight") or 1.1)
    alt = min(h, corpo * lh * max(1, len(linhas)))
    larg = 0.0
    arq = None
    for fo in (el.get("_fontes") or []):
        if (fo.get("familia") or "").lower() == (el.get("fonte") or "").lower() and fo.get("arquivo"):
            arq = raiz / fo["arquivo"]
    try:
        from PIL import ImageFont
        if arq and arq.exists():
            fnt = ImageFont.truetype(str(arq), int(round(corpo)))
            larg = max(fnt.getbbox(re.sub(r"\{\{|\}\}|\*\*", "", l))[2] for l in linhas if l)
    except Exception:
        larg = 0.0
    if not larg:
        larg = w                                    # sem a fonte, fica a caixa
    larg = min(w, larg * 1.02)                      # folga do letter-spacing
    al = (el.get("align") or "left").lower()
    va = (el.get("valign") or "top").lower()
    ix = x + (w - larg) / 2 if al == "center" else (x + w - larg if al == "right" else x)
    iy = y + (h - alt) / 2 if va == "middle" else (y + h - alt if va == "bottom" else y)
    return ix, iy, larg, alt


def cmd_validate(args) -> int:
    raiz = replicas_root(args.pasta)
    pecas_dir = raiz / "pecas"
    if not pecas_dir.exists():
        return die(f"não achei {pecas_dir}. Rode `prep` e crie as peças em replicas/pecas/*.json.")
    brief = ""
    for t in Path(raiz.parent).glob("*"):
        if t.suffix.lower() in TEXT_EXTS:
            brief += t.read_text(encoding="utf-8", errors="replace") + "\n"
    resultados = []
    erros = 0
    coberturas_mae = cobertura_da_mae(raiz)
    for pj in sorted(pecas_dir.glob("*.json")):
        if pj.name.endswith(".report.json"):
            continue
        peca = json.loads(pj.read_text(encoding="utf-8"))
        f = formato_by_id(peca.get("formato", "")) if peca.get("formato") else None
        w = int(peca.get("canvas", {}).get("w") or (f["w"] if f else 0)); h = int(peca.get("canvas", {}).get("h") or (f["h"] if f else 0))
        safe = peca.get("safe") or (f["safe"] if f else {"top": 0, "bottom": 0, "left": 0, "right": 0})
        png = raiz / (peca.get("saida") or (pj.stem + ".png"))
        mp4 = png.with_suffix(".mp4")
        item = {"peca": pj.name, "formato": peca.get("formato"), "png": str(png), "problemas": [], "avisos": []}
        # limites de fonte invertidos e texto picado em letras soltas: dois erros de
        # composição que passavam calados e só apareciam no olho de quem revisa
        # fonte declarada sem arquivo = o Chrome caiu numa fonte do sistema e a peça
        # saiu com outra tipografia, calada. É o erro mais difícil de ver no olho.
        SISTEMA = {"system-ui", "sans-serif", "serif", "monospace", "arial", "helvetica",
                   "helvetica neue", "times", "times new roman", "courier", "georgia", "verdana"}
        carregadas = set()
        for fo in (peca.get("fontes") or []):
            fam = (fo.get("familia") or "").strip().lower()
            if fam and (fo.get("arquivo") or fo.get("google")):
                carregadas.add(fam)
        vistas = set()
        for el in peca.get("elementos", []):
            if el.get("tipo") != "texto":
                continue
            fam = (el.get("fonte") or "").strip()
            if not fam or fam.lower() in SISTEMA or fam.lower() in carregadas or fam.lower() in vistas:
                continue
            vistas.add(fam.lower())
            item["problemas"].append(
                f"a fonte `{fam}` não foi carregada (sem arquivo e sem Google Fonts): "
                f"o render caiu numa fonte do sistema e a peça saiu com outra tipografia. "
                f"Envie o arquivo da fonte ou declare a família certa em `fontes`")

        # sobreposição: a adaptação não pode cobrir texto mais do que a arte-mãe
        # já cobria naquele mesmo par. Sem camadas do PSD não dá para saber o que
        # a mãe fazia, então ali vira aviso e não reprovação.
        try:
            rep_f = pj.with_suffix("").with_suffix(".report.json")
            rep = json.loads(rep_f.read_text(encoding="utf-8")) if rep_f.exists() else {}
            por_papel = {r.get("papel"): r for r in (rep.get("elementos") or []) if r.get("classe") == "txt"}
            els = peca.get("elementos", [])
            for ti, el in enumerate(els):
                if el.get("tipo") != "texto" or not (el.get("texto") or "").strip():
                    continue
                r = por_papel.get(el.get("papel")) or {}
                crua = (r.get("tinta") or "").strip()
                if crua:
                    ix, iy, iw, ih = [float(v) for v in crua.split(",")]
                else:
                    b = el.get("box") or {}
                    ix, iy, iw, ih = (float(b.get("x", 0)), float(b.get("y", 0)),
                                      float(b.get("w", 0)), float(b.get("h", 0)))
                if iw <= 1 or ih <= 1:
                    continue
                mae = coberturas_mae.get(_chave_texto(el.get("texto") or ""), {})
                for im_el in els[ti + 1:]:
                    if im_el.get("tipo") not in ("imagem", "video") or not im_el.get("src"):
                        continue
                    cam = raiz / im_el["src"] if not Path(im_el["src"]).is_absolute() else Path(im_el["src"])
                    if not cam.exists():
                        continue
                    ib = im_el.get("box") or {}
                    try:
                        m = _alfa(cam, int(ib.get("w", 0)), int(ib.get("h", 0)))
                    except Exception:
                        continue
                    frac = invasao_ret((ix, iy, iw, ih), m, (ib.get("x", 0), ib.get("y", 0)))
                    permitido = max(SOBREP_PISO, mae.get(Path(im_el["src"]).name, 0.0) + SOBREP_TOLERANCIA)
                    if frac <= permitido:
                        continue
                    na_mae = mae.get(Path(im_el["src"]).name, 0.0)
                    recado = (
                        f"`{im_el.get('papel') or Path(im_el['src']).stem}` invade "
                        f"{frac*100:.0f}% da largura do texto `{el.get('papel') or 'texto'}` "
                        f"(\"{(el.get('texto') or '')[:28]}\"); na arte-mãe era {na_mae*100:.0f}%. "
                        f"Recue a caixa do texto (e baixe `min`/`max` junto) até a imagem não alcançar a tinta")
                    if coberturas_mae:
                        item["problemas"].append(recado)
                    else:
                        item["avisos"].append(recado + " — sem camadas do PSD eu não sei o que a arte-mãe fazia, confira no olho")
        except Exception as ex:
            item["avisos"].append(f"não consegui conferir sobreposição: {ex}")

        letras = {}
        for el in peca.get("elementos", []):
            mn, mx = el.get("min"), el.get("max")
            if isinstance(mn, (int, float)) and isinstance(mx, (int, float)) and mn > mx:
                item["problemas"].append(
                    f"camada `{el.get('papel') or el.get('tipo')}`: fonte mínima ({mn}) maior que a máxima ({mx})")
            if el.get("tipo") == "texto" and len((el.get("texto") or "").strip()) <= 2:
                letras[el.get("papel") or "?"] = letras.get(el.get("papel") or "?", 0) + 1
        for papel_, n in letras.items():
            if n >= 4:
                item["problemas"].append(
                    f"`{papel_}` foi partido em {n} camadas de uma ou duas letras. "
                    f"Use UMA camada por linha e `tarja` para o realce: letra solta desalinha e não dá para editar")
        if mp4.exists():
            vi = _ffprobe(mp4)
            item["mp4"] = str(mp4)
            if (vi.get("w"), vi.get("h")) != (w, h):
                item["problemas"].append(f"vídeo {vi.get('w')}x{vi.get('h')}, esperado {w}x{h}")
            if not mp4.with_suffix(mp4.suffix + ".origem.json").exists():
                item["problemas"].append("vídeo não veio do comando `video` (sem assinatura)")
            else:
                try:
                    ov = json.loads(mp4.with_suffix(mp4.suffix + ".origem.json").read_text(encoding="utf-8"))
                    if ov.get("modo") == "blur" or (isinstance(ov.get("logs"), dict) and (ov["logs"].get("placa") or {}).get("modo") == "blur"):
                        item["problemas"].append("vídeo adaptado por desfoque (no vídeo ou na placa): não é adaptação. Use plate com stretch/outpaint, ou reframe")
                    if ov.get("modo") == "plate" and not ov.get("bordas_estaticas", True):
                        item["avisos"].append(f"placa estática sobre vídeo com bordas em movimento ({ov.get('movimento_bordas')}): confira se a emenda não aparece; se aparecer, use reframe")
                except Exception:
                    pass
        if not png.exists() and not mp4.exists():
            item["problemas"].append("PNG não existe — rode render")
        elif png.exists():
            im = Image.open(png)
            if im.size != (w, h):
                item["problemas"].append(f"dimensão {im.width}x{im.height}, esperado {w}x{h}")
            kb = png.stat().st_size // 1024
            item["kb"] = kb
            if f and f["canal"] in ("Google Display", "E-mail") and kb > 150:
                item["avisos"].append(f"arquivo com {kb}KB; para {f['canal']} mantenha < 150KB (use `jpg: true`)")
        # fundo: precisa ter saído do extend/save-external (assinatura .origem.json) — fundo sintetizado é redesign
        fundo = peca.get("fundo") or {}
        if fundo.get("tipo") == "imagem" and fundo.get("src"):
            fsrc = Path(fundo["src"])
            cand = [fsrc] if fsrc.is_absolute() else [pj.parent / fsrc, raiz / fsrc]
            fpath = next((c for c in cand if c.exists()), None)
            if fpath is None:
                item["problemas"].append(f"fundo '{fundo['src']}' não existe")
            elif not fpath.with_suffix(fpath.suffix + ".origem.json").exists():
                item["problemas"].append(f"fundo '{fundo['src']}' não veio do `extend` nem do `save-external` (sem assinatura .origem.json): fundo sintetizado ou montado à mão é redesign, não replicação")
            else:
                # rastreia a cadeia: extend → base → clean; se o clean saiu borrado, o fundo reprova
                try:
                    orig = json.loads(fpath.with_suffix(fpath.suffix + ".origem.json").read_text(encoding="utf-8"))
                    base_p = Path(orig.get("base") or "")
                    cadeia = [orig]
                    if base_p.exists() and base_p.with_suffix(base_p.suffix + ".origem.json").exists():
                        cadeia.append(json.loads(base_p.with_suffix(base_p.suffix + ".origem.json").read_text(encoding="utf-8")))
                    for o in cadeia:
                        if o.get("origem") == "clean" and o.get("veredito") == "borrado":
                            item["problemas"].append(f"fundo '{fundo['src']}' vem de um `clean` que ficou BORRADO (nitidez {o.get('razao')} do entorno). Refaça com --mode doador, regiões menores, inpaint generativo, ou mantenha o texto original no lugar")
                        if o.get("origem") == "extend" and o.get("modo") == "blur":
                            item["avisos"].append(f"fundo '{fundo['src']}' foi estendido por `blur` (moldura desfocada). Aceitável só como último recurso; prefira outpaint ou solid")
                except Exception:
                    pass
        rep_p = pj.with_suffix(".report.json")
        if rep_p.exists():
            rep = json.loads(rep_p.read_text(encoding="utf-8"))
            # grafismo/foto que sangra de propósito (papel rasgado, retícula, foto de borda a borda)
            # declara "sangria": true na peça; texto e logo nunca podem
            sangria = {el.get("papel") for el in peca.get("elementos", []) if el.get("sangria") and el.get("tipo") == "imagem" and el.get("papel") != "logo"}
            for e in rep.get("elementos", []):
                papel = e.get("papel", "?")
                if e.get("overflow") == "1":
                    item["problemas"].append(f"'{papel}' não coube no box nem no tamanho mínimo")
                if e.get("box") and papel not in sangria:
                    x, y, bw, bh = [float(v) for v in e["box"].split(",")]
                    if x < safe["left"] - 0.5 or y < safe["top"] - 0.5 or x + bw > w - safe["right"] + 0.5 or y + bh > h - safe["bottom"] + 0.5:
                        item["problemas"].append(f"'{papel}' fora da safe zone (box {e['box']}, safe {safe})")
                if e.get("classe") == "txt" and e.get("size"):
                    sz = float(e["size"])
                    minimo = max(14, round(min(w, h) * 0.022))
                    if sz < minimo:
                        item["avisos"].append(f"'{papel}' com {sz}px — abaixo de {minimo}px fica ilegível neste formato")
                if papel == "headline" and e.get("linhas") and int(e["linhas"]) > 4:
                    item["avisos"].append(f"headline em {e['linhas']} linhas — virou parágrafo; encurte")
            # equilíbrio: respiro esquerdo vs direito do conjunto de elementos sobrepostos
            caixas = [[float(v) for v in e["box"].split(",")] for e in rep.get("elementos", []) if e.get("box") and e.get("classe") in ("txt", "img", "botao") and e.get("papel") not in sangria]
            if caixas and w > 0:
                x0 = min(c[0] for c in caixas); x1 = max(c[0] + c[2] for c in caixas)
                L, Rm = x0 - safe["left"], (w - safe["right"]) - x1
                alin = peca.get("alinhamento")
                if not alin and min(L, Rm) < 0.45 * max(L, Rm) and abs(L - Rm) > w * 0.06:
                    item["avisos"].append(f"composição desequilibrada: respiro esquerdo {int(L)}px vs direito {int(Rm)}px. Centralize o conjunto ou declare `alinhamento` na peça (esquerda/direita/centro) se for intencional")
                if alin == "centro" and abs(L - Rm) > w * 0.04:
                    item["problemas"].append(f"alinhamento 'centro' declarado, mas respiro esquerdo {int(L)}px vs direito {int(Rm)}px")
        else:
            item["avisos"].append("sem report.json (render não rodou por aqui)")
        # texto vs limites do formato e vs brief
        for e in peca.get("elementos", []):
            if e.get("tipo") in ("texto", "botao") and f:
                papel = e.get("papel", "")
                lim = f["texto"].get({"headline": "headline_max", "apoio": "apoio_max", "cta": "cta_max"}.get(papel, ""), None)
                n = len(e.get("texto", ""))
                if lim is not None and lim > 0 and n > lim * 1.25:
                    item["avisos"].append(f"'{papel}' com {n} caracteres; o formato pede até ~{lim}")
                if lim == 0 and n > 0:
                    item["avisos"].append(f"'{papel}' não é recomendado em {f['id']} (formato pede sem {papel})")
            if brief and e.get("tipo") == "texto":
                faltam = [t for t in _nums(e.get("texto", "")) if t not in brief]
                if faltam:
                    item["avisos"].append(f"números que não estão no brief: {faltam} — confirme que não foram inventados")
        if item["problemas"]:
            erros += 1
        resultados.append(item)
    out({"status": "ok" if erros == 0 else "com_problemas", "pecas": len(resultados), "com_problemas": erros, "resultados": resultados})
    return 0 if erros == 0 else 2


# ----------------------------------------------------------------------------- sheet / manifest / output

def _img_data_uri(p: Path, max_side: int = 900) -> str:
    im = Image.open(p).convert("RGB")
    im.thumbnail((max_side, max_side))
    import base64, io
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def cmd_sheet(args) -> int:
    raiz = replicas_root(args.pasta)
    manifest_p = raiz / "manifest.json"
    manifest = json.loads(manifest_p.read_text(encoding="utf-8")) if manifest_p.exists() else {}
    pecas = []
    for pj in sorted((raiz / "pecas").glob("*.json")):
        if pj.name.endswith(".report.json"):
            continue
        peca = json.loads(pj.read_text(encoding="utf-8"))
        png = raiz / (peca.get("saida") or (pj.stem + ".png"))
        if not png.exists():
            continue

        f = formato_by_id(peca.get("formato", "")) or {}
        copy_p = png.with_suffix(".txt")
        pecas.append({"json": pj, "png": png, "formato": peca.get("formato"), "canal": f.get("canal", ""), "nome": f.get("nome", ""), "w": png and Image.open(png).width, "h": Image.open(png).height,
                      "copy": copy_p.read_text(encoding="utf-8") if copy_p.exists() else "", "objetivo": peca.get("objetivo", manifest.get("objetivo") or "")})
    if not pecas:
        return die("nenhuma peça renderizada em replicas/. Rode render antes.")

    base = manifest.get("base")
    base_p = Path(base) if base else None
    titulo = html.escape(manifest.get("titulo") or Path(manifest.get("pasta", raiz.parent)).name)
    cards = []
    for p in pecas:
        cards.append(f"""
        <section class="peca">
          <div class="meta"><span class="canal">{html.escape(p['canal'])}</span><h2>{html.escape(p['nome'] or p['formato'] or '')}</h2><span class="dim">{p['w']}×{p['h']}{(' · ' + html.escape(p['objetivo'])) if p['objetivo'] else ''}</span></div>
          <div class="fig"><img src="{_img_data_uri(p['png'], 1400)}"></div>

        </section>""")
    base_html = f'<section class="peca base"><div class="meta"><span class="canal">Base</span><h2>Peça original</h2><span class="dim">{Image.open(base_p).width}×{Image.open(base_p).height}</span></div><div class="fig"><img src="{_img_data_uri(base_p, 1400)}"></div></section>' if base_p and base_p.exists() else ""
    doc = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>{titulo}</title>
    <style>
      @page {{ size: 1600px 900px; margin: 0; }}
      body {{ margin:0; font-family: -apple-system, Inter, Helvetica, Arial, sans-serif; background:#f4f1ea; color:#1a1917; }}
      .capa, .peca {{ width:1600px; height:900px; box-sizing:border-box; page-break-after: always; display:flex; flex-direction:column; padding:56px 72px; }}
      .capa {{ justify-content:flex-end; background:#1a1917; color:#f4f1ea; }}
      .capa h1 {{ font-size:72px; margin:0 0 12px; letter-spacing:-.02em; }}
      .capa p {{ font-size:22px; opacity:.7; margin:0; }}
      .peca {{ flex-direction:row; gap:48px; }}
      .peca.base {{ background:#e9e4d8; }}
      .meta {{ width:300px; flex:none; display:flex; flex-direction:column; gap:10px; }}
      .canal {{ font-size:14px; letter-spacing:.14em; text-transform:uppercase; color:#8a5a2b; font-weight:700; }}
      .meta h2 {{ font-size:34px; line-height:1.05; margin:0; letter-spacing:-.01em; }}
      .dim {{ font-size:15px; color:#6b665e; }}
      .fig {{ flex:1; display:flex; align-items:center; justify-content:center; min-width:0; }}
      .fig img {{ max-width:100%; max-height:788px; box-shadow:0 20px 60px rgba(0,0,0,.18); }}
      .copy {{ width:380px; flex:none; font: 14px/1.5 -apple-system, Inter, sans-serif; white-space:pre-wrap; background:#fff; padding:20px; border-radius:8px; overflow:hidden; max-height:788px; margin:0; }}
    </style></head><body>
    <section class="capa"><h1>{titulo}</h1><p>Replicação e desdobramento · {len(pecas)} peças · {dt.date.today().strftime('%d/%m/%Y')}{(' · objetivo: ' + html.escape(manifest['objetivo'])) if manifest.get('objetivo') else ''}</p></section>
    {base_html}
    {''.join(cards)}
    </body></html>"""
    sheet_html = raiz / "_work" / "apresentacao.html"
    sheet_html.parent.mkdir(parents=True, exist_ok=True)
    sheet_html.write_text(doc, encoding="utf-8")
    pdf = raiz / "apresentacao.pdf"
    r = chrome_run("file://" + str(sheet_html), ["--no-pdf-header-footer", f"--print-to-pdf={pdf}"], timeout=240)
    if not pdf.exists():
        return die("Chrome não gerou o PDF: " + (r.stderr or r.stdout)[-400:])

    # output/ limpo
    outdir = raiz / "output"
    outdir.mkdir(exist_ok=True)
    for old in outdir.iterdir():
        if old.is_file():
            old.unlink()
    copiados = []
    for p in pecas:
        canal = unicodedata.normalize("NFKD", (p["canal"] or "geral")).encode("ascii", "ignore").decode().lower()
        canal = re.sub(r"[^a-z0-9]+", "-", canal).strip("-")
        nome = f"{canal}__{p['formato'] or p['png'].stem}__{p['w']}x{p['h']}"
        # Peça de vídeo entrega o vídeo. O PNG é só o quadro de composição: não é
        # peça, não é thumbnail pedida por ninguém, e só polui a pasta. Fica em
        # replicas/ para quem precisar, mas não vai para a entrega.
        filme = p["png"].with_suffix(".mp4")
        if not filme.exists():
            dst = outdir / (nome + ".png")
            shutil.copy2(p["png"], dst); copiados.append(str(dst))
        for ext in (".jpg", ".psd", ".svg", ".mp4"):
            extra = p["png"].with_suffix(ext)
            if extra.exists() and not (filme.exists() and ext in (".jpg",)):
                shutil.copy2(extra, outdir / (nome + ext)); copiados.append(str(outdir / (nome + ext)))

    for rot in sorted(raiz.glob("*-roteiro.txt")):
        shutil.copy2(rot, outdir / rot.name); copiados.append(str(outdir / rot.name))
    shutil.copy2(pdf, outdir / pdf.name); copiados.append(str(outdir / pdf.name))

    manifest.update({
        "atualizado": now_iso(),
        "outputs": {p["formato"] or p["png"].stem: {"png": str(p["png"]), "w": p["w"], "h": p["h"], "canal": p["canal"]} for p in pecas},
        "pdf": str(pdf), "output_dir": str(outdir), "status": manifest.get("status") or "pronto",
    })
    manifest_p.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    out({"status": "ok", "pdf": str(pdf), "output": str(outdir), "arquivos": copiados, "pecas": len(pecas)})
    return 0


def cmd_manifest(args) -> int:
    raiz = replicas_root(args.pasta)
    manifest_p = raiz / "manifest.json"
    manifest = json.loads(manifest_p.read_text(encoding="utf-8")) if manifest_p.exists() else {}
    for k in ("base", "objetivo", "titulo", "status"):
        v = getattr(args, k, None)
        if v:
            manifest[k] = v
    if args.destinos:
        manifest["destinos"] = [d.strip() for d in args.destinos.split(",") if d.strip()]
    manifest["atualizado"] = now_iso()
    manifest_p.parent.mkdir(parents=True, exist_ok=True)
    manifest_p.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    out({"status": "ok", "manifest": str(manifest_p), **{k: manifest.get(k) for k in ("base", "objetivo", "titulo", "destinos", "status")}})
    return 0


def cmd_save_external(args) -> int:
    raiz = replicas_root(args.pasta)
    outp = raiz / args.out if not Path(args.out).is_absolute() else Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    if args.url:
        baixar(args.url, outp)
    elif args.file:
        shutil.copy2(Path(args.file).expanduser().resolve(), outp)
    else:
        return die("informe --url ou --file")
    if args.to:
        w, h = parse_size(args.to)
        im = Image.open(outp).convert("RGB")
        if im.size != (w, h):
            ImageOps.fit(im, (w, h), Image.Resampling.LANCZOS).save(outp)
    im = Image.open(outp)
    prompt = args.prompt
    if args.prompt_file:
        pf = Path(args.prompt_file)
        pf = pf if pf.is_absolute() else raiz / pf
        prompt = pf.read_text(encoding="utf-8") if pf.exists() else prompt
    log = {"provider": args.provider, "model": args.model, "url": args.url, "file": args.file, "prompt": prompt, "salvo": str(outp), "w": im.width, "h": im.height, "quando": now_iso()}
    (raiz / "_logs").mkdir(parents=True, exist_ok=True)
    (raiz / "_logs" / f"{outp.stem}.json").write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    outp.with_suffix(outp.suffix + ".origem.json").write_text(json.dumps({"origem": "save-external", "provider": args.provider, "model": args.model, "quando": now_iso()}, ensure_ascii=False, indent=2), encoding="utf-8")
    out({"status": "ok", **log})
    return 0


# ----------------------------------------------------------------------------- main

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="replica.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check").set_defaults(fn=cmd_check)

    p = sub.add_parser("formatos"); p.add_argument("--grupo"); p.add_argument("--canal"); p.add_argument("--completo", action="store_true"); p.set_defaults(fn=cmd_formatos)
    p = sub.add_parser("prep"); p.add_argument("pasta"); p.set_defaults(fn=cmd_prep)
    p = sub.add_parser("grid"); p.add_argument("img"); p.add_argument("--passo", type=int, default=100); p.add_argument("--out"); p.set_defaults(fn=cmd_grid)
    p = sub.add_parser("analyze"); p.add_argument("img"); p.set_defaults(fn=cmd_analyze)
    p = sub.add_parser("crop"); p.add_argument("img"); p.add_argument("--bbox", required=True); p.add_argument("--out", required=True); p.add_argument("--pad", type=int, default=0)
    p.add_argument("--alpha-key", dest="alpha_key", help="auto ou #hex: cor que vira transparente"); p.add_argument("--tol", type=int, default=28); p.set_defaults(fn=cmd_crop)
    p = sub.add_parser("clean"); p.add_argument("img"); p.add_argument("--regions", required=True); p.add_argument("--out", required=True); p.add_argument("--pad", type=int, default=6); p.add_argument("--mask")
    p.add_argument("--protect", help="x0,y0,x1,y1;... — regiões que nunca são apagadas (assunto/produto)")
    p.add_argument("--mode", choices=["auto", "suave", "doador"], default="auto", help="suave = média (fundo liso); doador = copia textura real da peça (foto/malha/3D)"); p.set_defaults(fn=cmd_clean)

    for name, fn in (("fit", cmd_fit), ("extend", cmd_extend)):
        p = sub.add_parser(name); p.add_argument("img"); p.add_argument("--formato"); p.add_argument("--to")
        p.add_argument("--protect", help="x0,y0,x1,y1 — região que não pode ser cortada"); p.add_argument("--strategy", choices=["smart", "contain", "cover"], default="smart")
        p.add_argument("--anchor", help="center|top|bottom|left|right ou ax,ay (fração da extensão que vai antes da base)")
        p.add_argument("--folga", type=float, default=0.0, help="fração extra de canvas pra texto (ex.: 0.35 = 35%% a mais no eixo estendido)")
        if name == "extend":
            p.add_argument("--mode", choices=["auto", "none", "stretch", "mirror", "blur", "solid", "outpaint"], default="auto"); p.add_argument("--cor"); p.add_argument("--out")
        p.set_defaults(fn=fn)

    p = sub.add_parser("render"); p.add_argument("peca"); p.add_argument("--out"); p.add_argument("--debug", action="store_true"); p.set_defaults(fn=cmd_render)
    p = sub.add_parser("video"); p.add_argument("video"); p.add_argument("--formato"); p.add_argument("--to")
    p.add_argument("--mode", choices=["auto", "cover", "edge", "plate", "reframe", "solid", "blur", "none"], default="auto", help="auto: cover (corta só fundo) > edge (estica a borda quadro a quadro) > plate (placa contínua) > reframe (generativo)")
    p.add_argument("--corte-max", dest="corte_max", type=float, default=0.10, help="fração máxima do lado que o modo cover pode cortar (padrão 10%%)")
    p.add_argument("--plate-mode", dest="plate_mode", choices=["auto", "stretch", "mirror", "solid", "outpaint", "blur"], default="auto", help="como estender o quadro-chave para a placa (mesmo motor do extend)")
    p.add_argument("--upscale", choices=["auto", "no", "1080p", "2k", "4k"], default="auto"); p.add_argument("--preset", choices=["common", "aigc", "short_series", "ugc", "old_film"], default="common")
    p.add_argument("--protect", help="x0,y0,x1,y1 no quadro do vídeo — assunto que não pode ser cortado"); p.add_argument("--cor")
    p.add_argument("--anchor", help="center|top|bottom|left|right ou ax,ay"); p.add_argument("--peca", help="peça JSON cujos elementos viram a camada por cima"); p.add_argument("--out")
    p.add_argument("--refazer-placa", dest="refazer_placa", action="store_true", help="ignora a placa já existente e gera outra"); p.set_defaults(fn=cmd_video)
    p = sub.add_parser("export-psd"); p.add_argument("peca"); p.add_argument("--out"); p.set_defaults(fn=cmd_export_psd)
    p = sub.add_parser("export-svg"); p.add_argument("peca"); p.add_argument("--out"); p.set_defaults(fn=cmd_export_svg)
    p = sub.add_parser("validate"); p.add_argument("pasta"); p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("sheet"); p.add_argument("pasta"); p.set_defaults(fn=cmd_sheet)
    p = sub.add_parser("manifest"); p.add_argument("pasta"); p.add_argument("--base"); p.add_argument("--objetivo"); p.add_argument("--titulo"); p.add_argument("--destinos"); p.add_argument("--status"); p.set_defaults(fn=cmd_manifest)
    p = sub.add_parser("save-external"); p.add_argument("pasta"); p.add_argument("--url"); p.add_argument("--file"); p.add_argument("--out", required=True); p.add_argument("--to")
    p.add_argument("--provider", default="mcp"); p.add_argument("--model", default=""); p.add_argument("--prompt", default=""); p.add_argument("--prompt-file", dest="prompt_file"); p.set_defaults(fn=cmd_save_external)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        return die(str(exc))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
