"""Capture the native level and slider patches for the Default and Ambient Lights pages."""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import zlib

from PIL import Image
from palette_art import PALETTES
from render import fixture_page, rgb565


def build(config,states,destination,chromium_cdp=None):
    bank=bytearray()
    offsets={}
    def store(raw):
        data=zlib.compress(raw,6)
        if data not in offsets:
            offsets[data]=len(bank)
            bank.extend(data)
        return offsets[data],len(data)
    count=len(config["lights"])
    if not count:raise ValueError("Study has no lights")
    geometry=[]
    tables=[]
    for theme in ("default","ambient"):
        modes=[]
        for palette in PALETTES:
            cfg={**config,"display":{**config["display"],"theme":theme,"palette":palette}}
            with fixture_page(cfg,states,chromium_cdp=chromium_cdp) as page:
                page.locator(".nav [data-sheet=lights]").click()
                page.wait_for_timeout(850)
                page.add_style_tag(content="*,*::before,*::after{transition:none!important;animation:none!important}")
                rects=[]
                for i in range(count):
                    label=page.locator(f"#lv{i}")
                    slider=page.locator(f"#ls{i}").bounding_box()
                    label.evaluate("e=>e.textContent='100%'")
                    value=label.bounding_box()
                    def bounds(box,padding=0):
                        x=max(0,math.floor(box["x"])-padding)
                        y=max(0,math.floor(box["y"])-padding)
                        right=min(720,math.ceil(box["x"]+box["width"])+padding)
                        bottom=min(1280,math.ceil(box["y"]+box["height"])+padding)
                        if x>=right or y>=bottom:raise ValueError("Light outside viewport")
                        return x,y,right-x,bottom-y
                    rects.append([bounds(slider),bounds(slider,12),bounds(value,3)])
                if palette==PALETTES[0]:geometry.append(rects)
                elif geometry[-1]!=rects:raise ValueError("Palette moved a light control")
                rows=[]
                for value in range(101):
                    # Exercise the released kiosk painter. The fixture is disconnected from HA.
                    page.evaluate("""v=>document.querySelectorAll('#lightRows .lamp').forEach((lamp,i)=>{
                      const el=lamp.querySelector('.slider'),fill=el.querySelector('.fill'),knob=el.querySelector('.knob');
                      fill.dataset.to=v;fill.style.transform='scaleX('+v/100+')';
                      knob.style.transform='translate(calc('+(v/100*el.clientWidth)+'px - 50%),-50%)';
                      lamp.querySelector('.v').textContent=v?v+'%':'Off';
                    })""",value)
                    image=Image.open(io.BytesIO(page.screenshot()))
                    records=[]
                    for _,bar,label in rects:
                        pair=[]
                        for x,y,width,height in (bar,label):
                            crop=image.crop((x,y,x+width,y+height))
                            pair.append(store(rgb565(crop,x,y)))
                        records.append(pair)
                    rows.append(records)
                # Index records stay on the card, so firmware size is independent of the room's light count.
                position=len(bank)
                for row in rows:
                    for pair in row:
                        for at,size in pair:bank.extend(struct.pack("<II",at,size))
                modes.append(position)
            print(theme,palette,"light controls captured",flush=True)
        tables.append(modes)
    digest=hashlib.sha256(bank).digest()
    path=destination/"pi-panel"/(digest.hex()+".bin")
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=bank:raise ValueError("Existing light bank has different contents")
    else:
        with path.open("xb") as out:out.write(bank)
    def c(seq):return "{"+",".join(c(v) if isinstance(v,(list,tuple)) else str(v) for v in seq)+"}"
    (destination/"card_lights.h").write_text(
        '#pragma once\nnamespace study {\n'
        +f'constexpr char card_lights_path[]="/sd/pi-panel/{path.name}";\n'
        +f"constexpr unsigned card_lights_size={len(bank)},card_light_count={count};\n"
        +"constexpr unsigned char card_lights_sha[]="+c(list(digest))+";\n"
        +"constexpr unsigned card_light_tables[][6]="+c(tables)+";\n"
        +"struct CardRect {int x,y,w,h;};\n"
        +f"constexpr CardRect card_light_rects[][{count}][3]="+c(geometry)+";\n}\n",encoding="ascii")
    print("Light patch bank",len(bank),"bytes",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("config","states","destination"):parser.add_argument(name,type=Path)
    parser.add_argument("--chromium-cdp",help="Endpoint of the isolated CM5 reference browser through a loopback SSH tunnel")
    args=parser.parse_args()
    build(json.loads(args.config.read_bytes())["config"],json.loads(args.states.read_bytes()),args.destination,args.chromium_cdp)
