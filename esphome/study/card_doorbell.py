"""Capture the doorbell chrome and actual video bounds for each kiosk theme."""
import argparse
import hashlib
import io
import json
import zlib
from pathlib import Path
from PIL import Image
from control_art import box
from palette_art import PALETTES
from render import fixture_page,rgb565


def build(config,states,destination,chromium_cdp=None):
    data=bytearray();offsets={};views=[]
    bell=config["doorbell"]
    for theme in ("default","ambient","architectural"):
        for palette in PALETTES:
            cfg={**config,"display":{**config["display"],"theme":theme,"palette":palette}}
            with fixture_page(cfg,states,chromium_cdp=chromium_cdp) as page:
                def capture(r):
                    x,y,w,h=r
                    im=Image.open(io.BytesIO(page.screenshot(clip=dict(x=x,y=y,width=w,height=h))))
                    blob=zlib.compress(rgb565(im,x,y),7)
                    if blob not in offsets:offsets[blob]=len(data);data.extend(blob)
                    return (*r,offsets[blob],len(blob))
                page.evaluate("""([title,seconds])=>{
                  document.querySelector('#doorbellPopup').hidden=false;
                  document.querySelector('#doorbellTitle').textContent=title;
                  document.querySelector('#doorbellState').textContent='Connecting to live camera…';
                  document.querySelector('#doorbellDuration').textContent='Closes automatically after '+seconds+' seconds · Muted';
                  document.querySelector('#doorbellClose').focus({preventScroll:true});
                }""",[bell.get("title") or "Someone at the door",bell["duration_s"]])
                video=box(page,"#doorbellVideo")
                top=video[1];bottom=top+video[3]
                headers=[];footers=[]
                for value in ("DOORBELL","DOORBELL TEST"):
                    page.locator("#doorbellLabel").evaluate("(e,v)=>e.textContent=v",value)
                    headers.append(capture((0,0,720,top)))
                base=capture((0,0,720,1280))
                for value in ("Connecting to live camera…","Live camera","Live camera unavailable"):
                    page.locator("#doorbellState").evaluate("(e,v)=>e.textContent=v",value)
                    footers.append(capture((0,bottom,720,1280-bottom)))
                views.append((video,box(page,"#doorbellClose"),base,capture(video),headers,footers))
    def array(x):
        return "{"+",".join(array(v) if isinstance(v,(tuple,list,bytes)) else str(int(v)) for v in x)+"}"
    folder=destination/"pi-panel";folder.mkdir(exist_ok=True,parents=True)
    digest=hashlib.sha256(data).digest();path=folder/(digest.hex()+".bin")
    if path.exists():
        if path.read_bytes()!=data:raise ValueError("Doorbell artwork digest mismatch")
    else:
        with path.open("xb") as f:f.write(data)
    (destination/"card_bell.h").write_text('#pragma once\n#include "card_player.h"\nnamespace study {\n'
        f'constexpr char card_bell_path[]="/sd/pi-panel/{path.name}";\nconstexpr unsigned card_bell_size={len(data)};\n'
        'constexpr unsigned char card_bell_sha[]='+array(digest)+';\n'
        'struct BellView {Rect video,close;CardPlayerPatch base,empty,headers[2],footers[3];};\n'
        'constexpr BellView card_bell_views[]='+array(views)+';\n}\n',encoding="ascii")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("config","states","destination"):p.add_argument(key,type=Path)
    p.add_argument("--chromium-cdp");a=p.parse_args()
    build(json.loads(a.config.read_bytes())["config"],json.loads(a.states.read_bytes()),a.destination,a.chromium_cdp)
