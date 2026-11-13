"""Measure the CM5 Climate digits and raised units for the two card layouts."""
import argparse
import io
import json
from pathlib import Path
import zlib

import numpy as np
from PIL import Image
from card_fields import MEASURE
from render import fixture_page


def build(config, states, destination, chromium_cdp=None):
    data = bytearray()
    offsets = {}
    tables = []
    for theme in ("default", "ambient"):
        cfg = {**config, "display": {**config["display"], "theme": theme, "palette": "linen"}}
        with fixture_page(cfg, states, chromium_cdp=chromium_cdp) as page:
            page.locator(".nav [data-sheet=climate]").click()
            page.wait_for_timeout(650)
            for field, unit in (("cTemp", "°C"), ("cHum", "%")):
                el = page.locator("#"+field)
                area = el.evaluate(MEASURE)
                if not area or area["align"] not in ("start","left"):
                    raise ValueError("Unexpected Climate readout geometry")
                x, y, w, h = (area[k] for k in ("x","y","w","h"))
                glyphs = []
                for char in "0123456789.-–@":
                    advance = el.evaluate("""(e,[txt,suffix])=>{
                       const text=e.firstChild,sup=e.querySelector('sup');
                       text.data=txt;sup.textContent=suffix;
                       for(const n of [e,sup]){n.style.setProperty('color','white','important');}
                       e.style.setProperty('background','black','important');
                       const r=document.createRange();r.selectNodeContents(suffix?sup:text);
                       return Math.round(r.getBoundingClientRect().width*64);
                    }""", ["" if char=="@" else char, unit if char=="@" else ""])
                    shot = page.screenshot(clip=dict(x=x,y=y,width=w,height=h))
                    alpha = np.asarray(Image.open(io.BytesIO(shot)).convert("L"))
                    yy, xx = np.nonzero(alpha)
                    if not len(xx):
                        raise ValueError("No visible ink for "+field+"/"+char)
                    left,top=int(xx.min()),int(yy.min())
                    right,bottom=int(xx.max())+1,int(yy.max())+1
                    packed=zlib.compress(alpha[top:bottom,left:right].tobytes(),9)
                    if packed not in offsets:
                        offsets[packed]=len(data)
                        data.extend(packed)
                    glyphs.append((left,top,right-left,bottom-top,advance,offsets[packed],len(packed)))
                tables.append(glyphs)
    def array(items):
        return "{"+",".join(array(v) if isinstance(v,(tuple,list)) else str(v) for v in items)+"}"
    destination.mkdir(parents=True,exist_ok=True)
    (destination/"card_numbers.h").write_text(
        "#pragma once\nnamespace study {\n"
        "struct CardDigit {int x,y,w,h,advance;unsigned offset,size;};\n"
        "constexpr unsigned char card_digit_alpha[]="+array(list(data))+";\n"
        "constexpr CardDigit card_digits[2][2][14]="+array([tables[:2],tables[2:]])+";\n}\n",
        encoding="ascii")
    print("Captured",len(tables)*14,"Climate digits and units,",len(data),"compressed bytes",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ("config","states","destination"):parser.add_argument(n,type=Path)
    parser.add_argument("--chromium-cdp")
    args=parser.parse_args()
    build(json.loads(args.config.read_bytes())["config"],json.loads(args.states.read_bytes()),args.destination,args.chromium_cdp)
