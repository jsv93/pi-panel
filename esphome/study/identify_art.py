"""Capture the released kiosk's Identify overlay for the native renderer."""
import hashlib
import io
import json
from pathlib import Path
import zlib

from PIL import Image
from render import fixture_page, rgb565, UI


def generate(config, destination):
    palettes = ("linen", "midnight", "ember", "slate", "heath", "mono")
    digest = hashlib.sha256((UI / "panel.html").read_bytes() + config.get("room_label", "Room").encode()).hexdigest()
    output = destination / "identify_assets.h"
    if output.exists() and output.read_text("ascii").startswith("// " + digest):
        return
    bank = bytearray()
    frames = []
    config = {**config, "display": {**config["display"], "theme": "architectural"}}
    with fixture_page(config, []) as page:
        page.add_style_tag(content="#identify.on{animation:none!important;opacity:1!important}")
        for palette in palettes:
            page.evaluate("([names,name,label])=>{document.body.classList.remove(...names.map(n=>'pal-'+n));document.body.classList.add('pal-'+name);document.querySelector('#identifyName').textContent=label;document.querySelector('#identify').classList.add('on')}", [palettes, palette, config.get("room_label") or "Room"])
            raw = rgb565(Image.open(io.BytesIO(page.screenshot())))
            compressed = zlib.compress(raw, 9)
            frames.append((len(bank), len(compressed)))
            bank.extend(compressed)
    with output.open("w", encoding="ascii") as stream:
        stream.write("// " + digest + "\n#pragma once\nnamespace study {\n")
        stream.write("constexpr unsigned identify_frames[][2]={" + ",".join("{"+str(o)+","+str(n)+"}" for o,n in frames) + "};\n")
        stream.write("constexpr unsigned char identify_pixels[]=\n")
        for start in range(0, len(bank), 64):
            stream.write('"'+"".join("\\x%02x" % value for value in bank[start:start+64])+'"\n')
        stream.write(";\n}\n")
