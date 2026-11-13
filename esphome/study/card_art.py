"""Pack lossless kiosk artwork for the P4 microSD reader, in a private build directory."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zlib

from palette_art import PALETTES
from card_routes import emit as emit_routes


def build(captures, destination):
    payload = bytearray()
    sections = []
    seen = {}
    names = None
    for theme in ("default", "ambient"):
        layouts = []
        for palette in PALETTES:
            directory = captures / theme / palette
            views = json.loads((directory / "screens.json").read_bytes())["views"]
            source = (directory / "screens.bin").read_bytes()
            order = [v["name"] for v in views]
            if names is None:
                names = order
            if names != order or len(set(order)) != len(order):
                raise ValueError("The theme captures must use the same unique page names")
            entries = []
            for view in views:
                start, size = view["offset"], view["size"]
                if (view["w"], view["h"]) != (720, 1280) or start < 0 or size <= 0 or start + size > len(source):
                    raise ValueError(f"Invalid frame {view['name']}")
                chunk = source[start:start+size]
                if len(zlib.decompress(chunk)) != 720*1280*2:
                    raise ValueError(f"Incomplete frame {view['name']}")
                if chunk not in seen:
                    seen[chunk] = len(payload)
                    payload.extend(chunk)
                entries.append((seen[chunk], size))
            layouts.append(entries)
        sections.append(layouts)
    digest = hashlib.sha256(payload).digest()
    # Content-addressed filenames let the old and new firmware share a card.
    path = destination / "pi-panel" / (digest.hex() + ".bin")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("Existing file at content-addressed path does not match")
    else:
        with path.open("xb") as f:
            f.write(payload)
    def initializer(seq):
        return "{" + ",".join(initializer(v) if isinstance(v,(tuple,list)) else str(v) for v in seq) + "}"
    keys = [re.sub(r"[^A-Za-z0-9_]", "_", name) for name in names]
    if len(set(keys)) != len(keys):
        raise ValueError("Page names generate duplicate identifiers")
    (destination / "card_assets.h").write_text(
        "#pragma once\nnamespace study {\n"
        + 'constexpr char card_pack_path[]="/sd/pi-panel/' + path.name + '";\n'
        + f"constexpr unsigned card_pack_size={len(payload)};\n"
        + "constexpr unsigned char card_pack_sha[]=" + initializer(list(digest)) + ";\n"
        + "enum class CardPage {" + ",".join(keys) + "};\n"
        + "struct CardFrame {unsigned offset,size;};\n"
        + f"constexpr CardFrame card_frames[2][6][{len(names)}]=" + initializer(sections) + ";\n}\n",
        encoding="ascii")
    emit_routes(destination,[json.loads((captures/theme/"geometry.json").read_bytes()) for theme in ("default","ambient")])
    print(f"{len(names)} views × 2 layouts × 6 palettes, {len(payload):,} bytes, SHA-256 {digest.hex()}")
    return path


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build(args.captures,args.destination)
