"""Pack six matched Architectural captures into one lossless, offline RGB565 bank."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib

import numpy as np


PALETTES = ("linen", "midnight", "ember", "slate", "heath", "mono")
WIDTH, HEIGHT = 720, 1280
HEADER = struct.Struct("<4sHHHHH")
SECTION = struct.Struct("<III")


def load_pages(root, palette):
    path = root / palette
    exports = json.loads((path / "screens.json").read_bytes())["views"]
    data = (path / "screens.bin").read_bytes()
    pages = []
    for view in exports:
        if (view["w"], view["h"]) != (WIDTH, HEIGHT):
            raise ValueError(f"Unsupported dimensions for {view['name']}")
        start = view["offset"]
        raw = zlib.decompress(data[start:start + view["size"]])
        pages.append(np.frombuffer(raw, "<u2").reshape(HEIGHT, WIDTH))
    return [view["name"] for view in exports], pages


def encode(root, output):
    names, linen = load_pages(root, PALETTES[0])
    pages = [linen]
    for palette in PALETTES[1:]:
        other_names, images = load_pages(root, palette)
        if names != other_names:
            raise ValueError(f"Different screen order for {palette}")
        pages.append(images)
    ranks = np.empty((len(names), HEIGHT, WIDTH), dtype="<u2")
    tables = []
    for row in range(4):
        for column in range(4):
            # RGB565 quantization varies by Bayer position. A single linen
            # colour may have several exact counterparts even at one position.
            colours = np.stack([np.stack([p[row::4, column::4] for p in screens]).ravel()
                                for screens in pages], axis=1)
            unique, inverse, counts = np.unique(colours.view("V12").ravel(), return_inverse=True, return_counts=True)
            records = unique.view("<u2").reshape(-1, 6)
            order = np.lexsort((-counts, records[:, 0]))
            sorted_records = records[order]
            starts = np.flatnonzero(np.r_[True, sorted_records[1:, 0] != sorted_records[:-1, 0]])
            sizes = np.diff(np.r_[starts, len(sorted_records)])
            if sizes.max() > 65535:
                raise ValueError("Too many palette choices for one colour")
            variant = np.empty(len(order), "<u2")
            variant[order] = np.arange(len(order)) - np.repeat(starts, sizes)
            ranks[:, row::4, column::4] = variant[inverse].reshape(len(names), HEIGHT // 4, WIDTH // 4)
            keys = np.stack([sorted_records[starts, 0], sizes], axis=1).astype("<u2")
            tables.append(struct.pack("<I", len(keys)) + keys.tobytes() + sorted_records[:, 1:].tobytes())
    blocks = tables.copy()
    parents = []
    for i, rank in enumerate(ranks):
        candidates = [(zlib.compress(rank.tobytes(), 9), -1)]
        for j in range(i):
            candidates.append((zlib.compress((rank ^ ranks[j]).tobytes(), 9), j))
        packed, parent = min(candidates, key=lambda v: len(v[0]))
        blocks.append(zlib.decompress(packed))
        parents.append(parent)
    meta = json.dumps(dict(palettes=PALETTES, screens=names, parents=parents), separators=(",", ":")).encode()
    payload = bytearray()
    directory = bytearray()
    for block in blocks:
        packed = zlib.compress(block, 9)
        directory.extend(SECTION.pack(len(payload), len(packed), len(block)))
        payload.extend(packed)
    blob = HEADER.pack(b"PAL1", WIDTH, HEIGHT, len(names), len(blocks), len(meta)) + meta + directory + payload
    image = hashlib.sha256(blob).digest() + blob
    verify(image, names, pages)
    output.write_bytes(image)
    print(f"Verified {len(names)} screens in {len(PALETTES)} palettes, {len(image):,} bytes")


def verify(image, names, pages):
    digest, blob = image[:32], image[32:]
    if digest != hashlib.sha256(blob).digest():
        raise ValueError("Palette bank digest mismatch")
    magic, width, height, count, sections, length = HEADER.unpack_from(blob)
    meta = json.loads(blob[HEADER.size:HEADER.size + length])
    if (magic, width, height, count, sections) != (b"PAL1", WIDTH, HEIGHT, len(names), 16 + len(names)):
        raise ValueError("Palette bank dimensions mismatch")
    if meta["screens"] != names or meta["palettes"] != list(PALETTES):
        raise ValueError("Palette bank manifest mismatch")
    directory = HEADER.size + length
    payload = directory + sections * SECTION.size
    def read(index):
        offset, size, raw = SECTION.unpack_from(blob, directory + index * SECTION.size)
        data = zlib.decompress(blob[payload + offset:payload + offset + size])
        if len(data) != raw:
            raise ValueError(f"Bad palette section {index}")
        return data
    ranks = []
    for i, parent in enumerate(meta["parents"]):
        layer = np.frombuffer(read(16 + i), "<u2").reshape(HEIGHT, WIDTH)
        if not -1 <= parent < i:
            raise ValueError("Invalid palette map dependency")
        ranks.append(layer if parent == -1 else layer ^ ranks[parent])
    for index in range(16):
        table = read(index)
        count, = struct.unpack_from("<I", table)
        keys = np.frombuffer(table, "<u2", 2 * count, 4).reshape(-1, 2)
        alternatives = np.frombuffer(table, "<u2", offset=4 + 4 * count).reshape(-1, 5)
        starts = np.r_[0, np.cumsum(keys[:-1, 1], dtype=np.uint32)]
        y, x = divmod(index, 4)
        for i, source in enumerate(pages[0]):
            idx = np.searchsorted(keys[:, 0], source[y::4, x::4])
            variants = ranks[i][y::4, x::4]
            if np.any(variants >= keys[idx, 1]):
                raise ValueError("Invalid palette pixel rank")
            actual = alternatives[starts[idx] + variants]
            for p, target in enumerate(pages[1:]):
                if not np.array_equal(actual[:, :, p], target[i][y::4, x::4]):
                    raise ValueError(f"Palette reconstruction failed on {names[i]}, {PALETTES[p + 1]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("palette_render_directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    encode(args.palette_render_directory, args.output)
