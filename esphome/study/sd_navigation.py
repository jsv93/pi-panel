"""Build full-resolution Architectural motion artwork for local SD playback."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import struct
import zlib

import numpy as np
from PIL import Image

from jpeg_motion import motion_image, panel_jpeg
from page_motion import H, W, routes
from palette_art import PALETTES, load_pages


def encode_route(job):
    directory, source, target, travel, clip = job
    with Image.open(Path(directory) / (source + "-rgb.png")) as image:
        background = image.convert("RGB")
    with Image.open(Path(directory) / (target + "-rgb.png")) as image:
        foreground = image.convert("RGB")
    if background.size != (W, H) or foreground.size != (W, H):
        raise ValueError("Navigation artwork must be 720 by 1280")
    return [
        panel_jpeg(motion_image(background, foreground, phase, travel, clip),
                   quality=94, subsampling=2)
        for phase in range(10)
    ]


def build(root, destination, workers):
    destination.mkdir(parents=True, exist_ok=True)
    views = json.loads((root / "linen/screens.json").read_bytes())["views"]
    names = [view["name"] for view in views]
    paths = routes(views)
    frame_count = len(PALETTES) * len(paths) * 10
    index_offset = 16
    hashes_offset = index_offset + frame_count * 8
    tiles_per_page = (W // 16) * (H // 8)
    frames_offset = hashes_offset + len(PALETTES) * len(views) * tiles_per_page * 4
    temporary = destination / "navigation.bin.part"
    index = []
    jobs = []
    with temporary.open("w+b") as output:
        output.write(struct.pack("<8sHHHH", b"PNAV1\0\0\0", W, H, len(paths), len(views)))
        output.seek(hashes_offset)
        for palette in PALETTES:
            directory = root / palette
            current = json.loads((directory / "screens.json").read_bytes())["views"]
            page_names, pages = load_pages(root, palette)
            if page_names != names or routes(current) != paths:
                raise ValueError(f"Navigation geometry differs in {palette}")
            for pixels in pages:
                tiles = pixels.reshape(H // 8, 8, W // 16, 16).transpose(0, 2, 1, 3)
                hashes = [zlib.crc32(tile.astype("<u2").tobytes())
                          for row in tiles for tile in row]
                output.write(np.asarray(hashes, dtype="<u4").tobytes())
            for source, target, travel in paths:
                clip = min([link["y"] for link in current[target]["links"] if link["root"]] + [H])
                jobs.append((str(directory), names[source], names[target], travel, clip))
        assert output.tell() == frames_offset
        maximum = 0
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for number, frames in enumerate(pool.map(encode_route, jobs)):
                for frame in frames:
                    index.append((output.tell(), len(frame)))
                    output.write(frame)
                    maximum = max(maximum, len(frame))
                if number % 20 == 0 or number + 1 == len(jobs):
                    print(f"Encoded {number + 1}/{len(jobs)} routes", flush=True)
        size = output.tell()
        if size >= 2**32:
            raise ValueError("Navigation bank exceeds its 32-bit index")
        output.seek(index_offset)
        for offset, length in index:
            output.write(struct.pack("<II", offset, length))
    with temporary.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").digest()
    name = digest.hex() + ".bin"
    temporary.replace(destination / name)
    metadata = dict(palettes=list(PALETTES), pages=names, routes=paths, bytes=size,
                    sha256=digest.hex(), index_offset=index_offset,
                    hashes_offset=hashes_offset, max_frame=maximum)
    (destination / "navigation.json").write_text(json.dumps(metadata, indent=2))
    header = ["#pragma once", "namespace study {",
              f'constexpr char sd_navigation_path[]="/sd/pi-panel/{name}";',
              "constexpr unsigned char sd_navigation_sha[]={" + ",".join(map(str, digest)) + "};",
              f"constexpr unsigned sd_navigation_size={size}, sd_navigation_index={index_offset};",
              f"constexpr unsigned sd_navigation_hashes={hashes_offset}, sd_navigation_max_frame={maximum};",
              f"constexpr unsigned sd_navigation_routes={len(paths)}, sd_navigation_pages={len(views)};",
              "}"]
    (destination / "navigation_art_assets.h").write_text("\n".join(header) + "\n", encoding="ascii")
    print(f"Built {size:,} bytes, largest frame {maximum:,} bytes", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("palette_directory", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    build(args.palette_directory, args.destination, args.workers)
