"""Build the native P4 colour tables, exception maps and colour picker from matched captures."""
import argparse
import io
import json
from pathlib import Path
import struct
import zlib

import numpy as np
from PIL import Image
from palette_art import HEADER, PALETTES, SECTION, load_pages
from render import fixture_page, rgb565
from control_art import box


def build(root, bank, states, destination):
    import hashlib
    data = bank.read_bytes()
    if hashlib.sha256(data[32:]).digest() != data[:32]:
        raise ValueError("Palette source digest mismatch")
    data = data[32:]
    magic, width, height, pages, sections, meta_len = HEADER.unpack_from(data)
    if (magic, width, height, sections) != (b"PAL1", 720, 1280, pages + 16):
        raise ValueError("Unsupported palette source")
    meta = json.loads(data[HEADER.size:HEADER.size + meta_len])
    directory = HEADER.size + meta_len
    def read(index):
        at, size, raw = SECTION.unpack_from(data, directory + SECTION.size * index)
        start = directory + sections * SECTION.size + at
        block = zlib.decompress(data[start:start + size])
        if len(block) != raw:
            raise ValueError("Invalid palette section")
        return block
    payload = bytearray()
    def put(raw):
        packed = zlib.compress(raw, 9)
        at = len(payload)
        payload.extend(packed)
        return (at, len(packed), len(raw))
    tables, decoded_tables = [], []
    for index in range(16):
        table = read(index)
        count, = struct.unpack_from("<I", table)
        keys = np.frombuffer(table, "<u2", count * 2, 4).reshape(-1, 2)
        values = np.frombuffer(table, "<u2", offset=4 + 4 * count).reshape(-1, 5)
        starts = np.r_[0, np.cumsum(keys[:-1, 1], dtype=np.uint32)]
        if starts[-1] + keys[-1, 1] > 65535:
            raise ValueError("Colour table too large")
        entries = np.column_stack((keys[:, 0], starts)).astype("<u2")
        tables.append(put(struct.pack("<HH", count, len(values)) + entries.tobytes() + values.tobytes()))
        decoded_tables.append((keys[:,0],starts,values))
    ranks, maps = [], []
    for index, parent in enumerate(meta["parents"]):
        layer = np.frombuffer(read(index + 16), "<u2")
        if parent >= index or parent < -1:
            raise ValueError("Invalid palette parent")
        rank = layer ^ ranks[parent] if parent >= 0 else layer
        if rank.max() > 255:
            raise ValueError("Invalid palette rank")
        ranks.append(rank)
        maps.append(put(rank.astype(np.uint8).tobytes()))
    names,base=load_pages(root,"linen")
    if meta["screens"]!=names or meta["palettes"]!=list(PALETTES):
        raise ValueError("Palette bank does not match the Study screen order")
    for mode,name in enumerate(PALETTES[1:]):
        _,expected=load_pages(root,name)
        for index,source in enumerate(base):
            for bayer,(keys,starts,colours) in enumerate(decoded_tables):
                y,x=divmod(bayer,4)
                pixels=source[y::4,x::4]
                keys_used=np.searchsorted(keys,pixels)
                variant=ranks[index].reshape(height,width)[y::4,x::4].astype(np.uint8)
                actual=colours[starts[keys_used]+variant,mode]
                if not np.array_equal(actual,expected[index][y::4,x::4]):
                    raise ValueError(f"Native table mismatch on {name}/{names[index]}")
    def capture_picker(name):
        config = json.loads((root / name / "config.json").read_bytes())["config"]
        with fixture_page(config, states) as page:
            def click(selector):
                page.locator(selector).evaluate("e=>e.click()")
                page.wait_for_timeout(330)
            click("#archMenu")
            click('#archRoomLinks [data-sheet="settings"]')
            click('#archSettingsLinks [data-sheet="display"]')
            button = box(page, "#paletteRow")
            display = np.frombuffer(rgb565(Image.open(io.BytesIO(page.screenshot()))), "<u2").reshape(1280, 720)
            click("#paletteRow")
            rows = page.locator("#archChoices button")
            hit = {rows.nth(i).locator(".t").inner_text().lower():box(page, f"#archChoices button:nth-child({i+1})") for i in range(rows.count())}
            rects = [button, box(page, "#s-choices [data-close]")] + [hit[p] for p in PALETTES]
            image = np.frombuffer(rgb565(Image.open(io.BytesIO(page.screenshot()))), "<u2").reshape(1280, 720)
        x,y,w,h=button
        return rects, image, display[y:y+h,x:x+w].tobytes()
    geometry = None
    choices, labels = [], []
    for name in PALETTES:
        rects, image, label = capture_picker(name)
        if geometry is None:
            geometry = rects
        if rects != geometry:
            raise ValueError("Palette picker hit regions differ")
        choices.append(put(image.tobytes()))
        labels.append(put(label))
    def c(items):
        return "{" + ",".join(c(x) if isinstance(x,(list,tuple)) else str(x) for x in items) + "}"
    with (destination/"palette_assets.h").open("w", encoding="ascii") as f:
        f.write("#pragma once\n#include \"study_assets.h\"\nnamespace study {\n")
        f.write("struct PaletteSection {unsigned offset,size,raw;};\n")
        for name, items in (("palette_tables",tables),("palette_maps",maps),("palette_choices",choices),("palette_labels",labels)):
            f.write("constexpr PaletteSection "+name+"[]="+c(items)+";\n")
        f.write("constexpr Rect palette_buttons[]="+c(geometry)+";\n}\n")
    (destination/"palette-art.bin").write_bytes(payload)
    print("Native colour tables, page maps and six pickers:",len(payload),"bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("palette_directory","source_bank","states","destination"):
        parser.add_argument(arg,type=Path)
    args=parser.parse_args()
    build(args.palette_directory,args.source_bank,json.loads(args.states.read_bytes()),args.destination)
