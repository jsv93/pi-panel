"""Capture Architectural text, light sheets and volume controls in six palettes."""
import argparse
import io
import json
from pathlib import Path
import zlib

from advanced_art import capture_advanced
from control_art import box
from media_art import capture as capture_volume
from palette_art import PALETTES
from render import rgb565
from render import fixture_page
from text_art import capture as capture_text
from PIL import Image


def capture_wifi(config, states, destination, *, chromium_cdp=None):
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    bank = bytearray()
    with fixture_page(config, states, chromium_cdp=chromium_cdp) as page:
        page.route('**/wifi*', lambda route: route.fulfill(json={
            'status': {'available': True},
            'networks': [{'ssid': 'Network', 'signal': 80, 'secure': True}]}))
        for selector in ('#archMenu', '#archRoomLinks [data-sheet=settings]', '#wifiRow'):
            page.locator(selector).first.evaluate('e=>e.click()')
            page.wait_for_timeout(350)
        page.add_style_tag(content='#wifiList *{transition:none!important}')
        for selected in (False, True):
            for secure in (False, True):
                for signal in (5, 15, 30, 60, 80, 100):
                    page.evaluate("""([selected,secure,signal])=>{
                      const row=document.querySelector('#wifiList .wnet');
                      row.classList.toggle('on',selected);
                      row.querySelector('.lock').style.display=secure?'':'none';
                      row.querySelector('.g').textContent=
                        (signal>=75?'▂▄▆█':signal>=50?'▂▄▆':signal>=25?'▂▄':'▂')+' '+signal+'%';
                    }""", [selected, secure, signal])
                    geometry = page.locator('#wifiList .wnet').evaluate("""row=>{
                      function rect(e){const r=e.getBoundingClientRect(),x=Math.floor(r.x),y=Math.floor(r.y);
                        return [x,y,Math.ceil(r.right)-x,Math.ceil(r.bottom)-y]}
                      const name=row.querySelector('.s'),signal=row.querySelector('.g');
                      return {row:rect(row),name:rect(name),signal:rect(signal),
                        colour:getComputedStyle(name).color.match(/[\\d.]+/g).slice(0,3).map(Number)}}
                    """)
                    page.locator('#wifiList .s,#wifiList .g').evaluate_all(
                        "items=>items.forEach(e=>e.style.visibility='hidden')")
                    frame = Image.open(io.BytesIO(page.screenshot()))
                    x, y, width, height = geometry['row']
                    pixels = rgb565(frame.crop((x, y, x+width, y+height)), x, y)
                    packed = zlib.compress(pixels, 9)
                    red, green, blue = geometry.pop('colour')
                    geometry['colour'] = ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
                    geometry.update(offset=len(bank), size=len(packed))
                    records.append(geometry)
                    bank.extend(packed)
                    page.locator('#wifiList .s,#wifiList .g').evaluate_all(
                        "items=>items.forEach(e=>e.style.visibility='')")
    (destination / 'wifi_rows.json').write_text(json.dumps(records))
    (destination / 'wifi-rows.bin').write_bytes(bank)
    print('Wi-Fi rows', config['display']['palette'], len(bank), 'bytes', flush=True)


def capture(config, states, destination, *, chromium_cdp=None):
    destination.mkdir(parents=True, exist_ok=True)
    bank = bytearray()
    offsets = {}
    tables = []

    def literal(value):
        if isinstance(value, (list, tuple)):
            return '{' + ','.join(literal(item) for item in value) + '}'
        return str(value)

    def table(kind, name, rows):
        tables.append(f'constexpr {kind} {name}={literal(rows)};')

    def sprite(frame, rectangle):
        x, y, width, height = rectangle
        pixels = rgb565(frame.crop((x, y, x + width, y + height)), x, y)
        packed = zlib.compress(pixels, 9)
        if packed not in offsets:
            offsets[packed] = len(bank)
            bank.extend(packed)
        return offsets[packed], len(packed), width, height

    capture_advanced(config, states, table, sprite, box, chromium_cdp=chromium_cdp)
    (destination / 'advanced_art.h').write_text('\n'.join(tables) + '\n', encoding='ascii')
    (destination / 'advanced-art.bin').write_bytes(bank)
    print('Light sheet palette', config['display']['palette'], len(bank), 'bytes', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('config', 'states', 'destination'):
        parser.add_argument(argument, type=Path)
    parser.add_argument('--chromium-cdp')
    arguments = parser.parse_args()
    config = json.loads(arguments.config.read_bytes())['config']
    states = json.loads(arguments.states.read_bytes())
    config['display'].update(theme='architectural', browse_view='tiles')
    for palette in PALETTES:
        config['display']['palette'] = palette
        destination = arguments.destination / palette
        destination.mkdir(parents=True, exist_ok=True)
        capture_text(config, states, destination, architectural_only=True,
                     chromium_cdp=arguments.chromium_cdp)
        capture(config, states, destination, chromium_cdp=arguments.chromium_cdp)
        capture_volume(config, states, destination, chromium_cdp=arguments.chromium_cdp)
        capture_wifi(config, states, destination, chromium_cdp=arguments.chromium_cdp)
