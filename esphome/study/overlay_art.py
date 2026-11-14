"""Pack palette-specific Architectural overlay artwork from matched text captures."""
import argparse
import hashlib
import json
import re
import zlib
from pathlib import Path
import numpy as np

from palette_art import PALETTES


def initializer(header, name):
    match = re.search(r"\b" + re.escape(name) + r"(?:\[[^]]*\])*\s*=\s*", header)
    if match is None:
        raise ValueError(f"Missing artwork declaration {name}")
    start = match.end()
    depth = 0
    for end in range(start, len(header)):
        if header[end] == "{":
            depth += 1
        elif header[end] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(header[start:end + 1].replace("{", "[").replace("}", "]"))
    raise ValueError(f"Incomplete artwork declaration {name}")


def build(base, captures, destination, controls=None):
    headers = [(base / "text_art.h").read_text()]
    banks = [zlib.decompress((base / "text-art.bin").read_bytes())]
    for palette in PALETTES[1:]:
        directory = captures / palette
        headers.append((directory / "text_art.h").read_text())
        banks.append(zlib.decompress((directory / "text-art.bin").read_bytes()))
    payload = bytearray()
    packed = {}
    images = {}
    colours = {}
    control_images = {}
    volume_bases = []
    volume_levels = []
    volume_rectangles = []
    wifi_rows = []

    def store(raw):
        data = zlib.compress(raw, 9)
        if data not in packed:
            packed[data] = (len(payload), len(data))
            payload.extend(data)
        return packed[data]

    def image(records):
        original = tuple(records[0][:2])
        variants = []
        count = None
        for bank, record in zip(banks, records):
            offset, size = record[:2]
            raw = zlib.decompress(bank[offset:offset + size])
            if count is None:
                count = len(raw)
            if len(raw) != count:
                raise ValueError("Overlay dimensions differ between palettes")
            variants.append(store(raw))
        entry = (count, variants)
        if original in images and images[original] != entry:
            raise ValueError("One source image has conflicting palette variants")
        images[original] = entry

    def array(records):
        if len({len(record) for record in records}) != 1:
            raise ValueError("Overlay array dimensions differ")
        if isinstance(records[0][0], int):
            if any(record[2:] != records[0][2:] for record in records):
                raise ValueError("Overlay row dimensions differ")
            image(records)
        else:
            for row in zip(*records):
                array(row)

    for name in ("library_bases", "library_art", "library_notes", "speaker_base",
                 "speaker_rows", "speaker_arrows", "queue_pages", "wifi_empty",
                 "wifi_row_art", "wifi_keyboard", "seek_art"):
        array([initializer(header, name) for header in headers])
    for name in ("library_tiles", "library_note_rects", "library_steps", "queue_patches",
                 "speaker_rects", "wifi_rows"):
        values = [initializer(header, name) for header in headers]
        if any(value != values[0] for value in values):
            raise ValueError(f"Overlay geometry differs for {name}")
    names = re.findall(r"constexpr TextArea (\w+)=", headers[0])
    for name in names:
        if not name.startswith(("library_", "queue_", "wifi_", "song_", "home_")) and name not in (
                "speaker_now", "elapsed_time", "total_time"):
            continue
        fields = [initializer(header, name) for header in headers]
        if any(field[0] != fields[0][0] or field[4:] != fields[0][4:] for field in fields):
            raise ValueError(f"Overlay typography differs for {name}")
        image([field[1:3] for field in fields])
        key = tuple(fields[0][1:5])
        values = [field[3] for field in fields]
        if key in colours and colours[key] != values:
            raise ValueError(f"Ambiguous text colour for {name}")
        colours[key] = values

    if controls:
        source_header = (base / 'control_art.h').read_text()
        control_headers = [(controls / name / 'advanced_art.h').read_text() for name in PALETTES]
        control_banks = [(controls / name / 'advanced-art.bin').read_bytes() for name in PALETTES]

        def control_rows(original, targets):
            if isinstance(original[0], int):
                if not original[1]:
                    return
                if any(target[2:] != original[2:] for target in targets):
                    raise ValueError('Light sheet image dimensions differ')
                raw = 2 * original[2] * original[3]
                variants = []
                for bank, target in zip(control_banks, targets):
                    data = zlib.decompress(bank[target[0]:target[0] + target[1]])
                    if len(data) != raw:
                        raise ValueError('Invalid light sheet image')
                    variants.append(store(data))
                key = tuple(original[:2])
                record = (raw, variants)
                if key in control_images and control_images[key] != record:
                    raise ValueError('Ambiguous light sheet image')
                control_images[key] = record
                return
            if any(len(target) != len(original) for target in targets):
                raise ValueError('Light sheet arrays differ')
            for index, record in enumerate(original):
                control_rows(record, [target[index] for target in targets])

        for name in re.findall(r'constexpr Sprite (\w+)', control_headers[0]):
            control_rows(initializer(source_header, name),
                         [initializer(header, name) for header in control_headers])
        for name in re.findall(r'constexpr Rect (\w+)', control_headers[0]):
            original = initializer(source_header, name)
            if any(initializer(header, name) != original for header in control_headers):
                raise ValueError(f'Light sheet hit area differs for {name}')
        for palette in PALETTES:
            directory = controls / palette
            header = (directory / 'media_art.h').read_text()
            bank = (directory / 'volume-art.bin').read_bytes()

            def expand(record):
                offset, size = record
                return zlib.decompress(bank[offset:offset + size])

            dictionary = np.frombuffer(expand(initializer(header, 'volume_dictionary')), '<u2').reshape(-1, 8)
            tiles = initializer(header, 'volume_tiles')
            bases = initializer(header, 'volume_bases')
            palette_bases = []
            palette_levels = []
            rectangles = []
            for index, name in enumerate(('button', 'popup')):
                rectangle = initializer(header, 'volume_' + name)
                rectangles.append(rectangle)
                _, _, width, height = rectangle
                original = np.frombuffer(expand(bases[index]), '<u2').reshape(height, width)
                palette_bases.append(store(original.tobytes()))
                levels = []
                for references in initializer(header, 'volume_' + name + '_tiles'):
                    delta = np.zeros_like(original)
                    for column, reference in enumerate(references):
                        x = 16 * column
                        count = min(16, width - x)
                        codes = np.frombuffer(expand(tiles[reference]), '<u2')
                        pixels = dictionary[codes].reshape(-1)[:height * count].reshape(height, count)
                        delta[:, x:x + count] = pixels
                    levels.append(store(delta.tobytes()))
                if len(levels) != 101:
                    raise ValueError('Missing volume positions')
                palette_levels.append(levels)
            if volume_rectangles and volume_rectangles != rectangles:
                raise ValueError('Volume geometry differs between palettes')
            volume_rectangles = rectangles
            volume_bases.append(palette_bases)
            volume_levels.append(palette_levels)
        original_header = (base / 'media_art.h').read_text()
        for name, rectangle in zip(('button', 'popup'), volume_rectangles):
            if initializer(original_header, 'volume_' + name) != rectangle:
                raise ValueError('Volume geometry differs from the native hit areas')
        wifi_captures = [(controls / palette / 'wifi_rows.json').is_file() for palette in PALETTES]
        if any(wifi_captures) and not all(wifi_captures):
            raise ValueError('Wi-Fi row captures are required for all six palettes')
        if all(wifi_captures):
            native_row = initializer(headers[0], 'wifi_rows')[0]
            for palette in PALETTES:
                directory = controls / palette
                rows = json.loads((directory / 'wifi_rows.json').read_text())
                bank = (directory / 'wifi-rows.bin').read_bytes()
                if len(rows) != 24:
                    raise ValueError('Missing Wi-Fi row variants')
                variants = []
                for row in rows:
                    if row['row'] != native_row:
                        raise ValueError('Wi-Fi row geometry differs from the native layout')
                    offset, size = row['offset'], row['size']
                    pixels = zlib.decompress(bank[offset:offset+size])
                    if len(pixels) != 2*native_row[2]*native_row[3]:
                        raise ValueError('Invalid Wi-Fi row image')
                    variants.append((*store(pixels), row['name'], row['signal'], row['colour']))
                wifi_rows.append(variants)

    def literal(value):
        if isinstance(value, (tuple, list, bytes)):
            return "{" + ",".join(literal(item) for item in value) + "}"
        return str(value)

    destination.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(payload).digest()
    filename = digest.hex() + ".bin"
    (destination / filename).write_bytes(payload)
    records = [(offset, size, count, variants) for (offset, size), (count, variants) in sorted(images.items())]
    fields = [(*key, values) for key, values in sorted(colours.items())]
    header = ["#pragma once", '#include "../study_assets.h"', "namespace study {",
              f'constexpr char overlay_path[]="/sd/pi-panel/{filename}";',
              f"constexpr unsigned overlay_size={len(payload)};",
              "constexpr unsigned char overlay_sha[]=" + literal(digest) + ";",
              "constexpr unsigned char overlay_text_sha[]=" + literal(hashlib.sha256((base / "text-art.bin").read_bytes()).digest()) + ";",
              "struct OverlayImage {unsigned source,size,raw;unsigned variants[6][2];};",
              "constexpr OverlayImage overlay_images[]=" + literal(records) + ";",
              "struct OverlayColour {unsigned source,size,colour,font;unsigned variants[6];};",
              "constexpr OverlayColour overlay_colours[]=" + literal(fields) + ";"]
    if controls:
        control_records = [(offset, size, count, variants)
                           for (offset, size), (count, variants) in sorted(control_images.items())]
        header.extend(["#define STUDY_OVERLAY_CONTROLS",
                       "constexpr OverlayImage overlay_controls[]="+literal(control_records)+";",
                       "constexpr unsigned overlay_volume_bases[6][2][2]="+literal(volume_bases)+";",
                       "constexpr unsigned overlay_volume_levels[6][2][101][2]="+literal(volume_levels)+";"])
    if wifi_rows:
        header.extend([
            '#define STUDY_OVERLAY_WIFI',
            'struct OverlayWifiRow {unsigned offset,size;Rect name,signal;uint16_t colour;};',
            'constexpr OverlayWifiRow overlay_wifi_rows[6][24]=' + literal(wifi_rows) + ';'])
    header.append("}")
    (destination / "overlay_assets.h").write_text("\n".join(header) + "\n", encoding="ascii")
    print(f"Packed {len(records)} text images, {len(control_images)} control images and {len(fields)} text colours, {len(payload)} bytes", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("base", "captures", "destination"):
        parser.add_argument(argument, type=Path)
    parser.add_argument('--controls', type=Path)
    arguments = parser.parse_args()
    build(arguments.base, arguments.captures, arguments.destination, arguments.controls)
