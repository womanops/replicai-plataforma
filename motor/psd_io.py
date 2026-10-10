#!/usr/bin/env python3
"""
psd_io.py — leitura e escrita de PSD em camadas. Roda no venv da skill
(.venv/bin/python), porque depende de psd-tools, pytoshop e numpy.

    read  <arquivo.psd> <pasta-saida>     composite.png + camadas/NN-nome.png + camadas.json
    write <saida.psd> <camadas.json>      camadas.json: {"w":..,"h":..,"camadas":[{"nome","png","x","y"}]} (de baixo para cima)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def slug(s: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", s.strip()).strip().replace(" ", "-").lower()
    return s[:40] or "camada"


def texto_puro(v):
    """O psd-tools devolve tipos próprios (String, Name...). Vira texto limpo,
    sem os nulos que o Photoshop deixa no fim das strings."""
    if v is None:
        return None
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace")
    t = str(v).replace("\x00", "").strip()
    # o repr do psd-tools vem com aspas coladas: 'CeraPro-Light' -> CeraPro-Light
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        t = t[1:-1].strip()
    return t or None


def cmd_read(psd_path: str, out_dir: str) -> int:
    from psd_tools import PSDImage
    psd = PSDImage.open(psd_path)
    out = Path(out_dir); (out / "camadas").mkdir(parents=True, exist_ok=True)
    W, H = psd.size
    comp = psd.composite()
    comp_p = out / "composite.png"
    comp.convert("RGBA").save(comp_p)
    camadas = []
    n = 0
    for layer in psd.descendants():
        if layer.is_group():
            continue
        n += 1
        info = {"n": n, "nome": layer.name.strip("\x00"), "tipo": layer.kind, "visivel": bool(layer.visible), "bbox": list(layer.bbox), "grupo": layer.parent.name.strip("\x00") if layer.parent is not None and layer.parent is not psd else None}
        if layer.kind == "type":
            try:
                info["texto"] = texto_puro(layer.text)
                eng = layer.engine_dict if hasattr(layer, "engine_dict") else None
                info["fonte"] = None
                rd = layer.resource_dict if hasattr(layer, "resource_dict") else None
                if rd and "FontSet" in rd:
                    nomes = [texto_puro(f.get("Name")) for f in rd["FontSet"]]
                    info["fonte"] = [x for x in nomes if x] or None
            except Exception:
                pass
        try:
            im = layer.composite()  # respeita máscaras/efeitos quando possível
            if im is not None and im.width > 0 and im.height > 0:
                p = out / "camadas" / f"{n:02d}-{slug(info['nome'])}.png"
                im.convert("RGBA").save(p)
                info["png"] = str(p)
        except Exception as exc:
            info["erro"] = str(exc)[:200]
        camadas.append(info)
    meta = {"arquivo": str(Path(psd_path).resolve()), "w": W, "h": H, "composite": str(comp_p), "camadas": camadas}
    # default=str: um campo exótico numa camada não pode custar a leitura inteira
    bruto = json.dumps(meta, ensure_ascii=False, indent=2, default=str)
    (out / "camadas.json").write_text(bruto, encoding="utf-8")
    print(bruto)
    return 0


def cmd_write(out_psd: str, spec_path: str) -> int:
    from pytoshop.user import nested_layers as nl
    from pytoshop import enums
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    W, H = int(spec["w"]), int(spec["h"])
    layers = []
    for c in reversed(spec["camadas"]):  # pytoshop: primeira da lista = topo
        im = Image.open(c["png"]).convert("RGBA")
        x, y = int(c.get("x", 0)), int(c.get("y", 0))
        # recorta ao canvas
        if x < 0 or y < 0 or x + im.width > W or y + im.height > H:
            canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0)); canvas.paste(im, (x, y)); im = canvas; x = y = 0
        a = np.asarray(im)
        layers.append(nl.Image(name=c["nome"][:120], top=y, left=x, channels={0: a[:, :, 0], 1: a[:, :, 1], 2: a[:, :, 2], -1: a[:, :, 3]}))
    # pytoshop: `size` é (largura, altura) — a doc sugere o contrário e um teste quadrado esconde o erro
    psd = nl.nested_layers_to_psd(layers, color_mode=enums.ColorMode.rgb, size=(W, H), compression=enums.Compression.raw)
    # imagem achatada (preview/merged): sem ela, visualizadores que não compõem camadas mostram preto
    flat = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for c in spec["camadas"]:
        im = Image.open(c["png"]).convert("RGBA")
        flat.alpha_composite(im, (max(0, int(c.get("x", 0))), max(0, int(c.get("y", 0)))))
    fa = np.asarray(flat.convert("RGB"))
    from pytoshop import image_data
    psd.image_data = image_data.ImageData(channels=np.stack([fa[:, :, 0], fa[:, :, 1], fa[:, :, 2]]), compression=enums.Compression.raw)
    with open(out_psd, "wb") as f:
        psd.write(f)
    print(json.dumps({"status": "ok", "psd": str(Path(out_psd).resolve()), "camadas": len(layers), "w": W, "h": H}))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__); sys.exit(1)
    if sys.argv[1] == "read":
        sys.exit(cmd_read(sys.argv[2], sys.argv[3]))
    if sys.argv[1] == "write":
        sys.exit(cmd_write(sys.argv[2], sys.argv[3]))
    print(__doc__); sys.exit(1)
