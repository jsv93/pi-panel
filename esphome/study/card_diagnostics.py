"""Measure the CM5 diagnostic text for the P4's two card-backed layouts."""
import argparse
import json
import io
import zlib
from pathlib import Path
from PIL import Image
from card_fields import MEASURE
from palette_art import PALETTES
from render import fixture_page,rgb565


def build(config, states, destination, chromium_cdp=None):
    result=[];bank=bytearray();offsets={}
    for theme in ("default","ambient"):
        for palette in PALETTES:
            cfg={**config,"display":{**config["display"],"diagnostics":True,"theme":theme,"palette":palette}}
            with fixture_page(cfg,states,chromium_cdp=chromium_cdp) as page:
                def measure(selector):
                    m=page.locator(selector).evaluate(MEASURE)
                    r,g,b=m["color"]
                    return [m[k] for k in ("x","y","w","h","baseline","spacing")]+[(r>>3)<<11|(g>>2)<<5|(b>>3)]
                values=[]
                for status,css in (("connected","ok"),("disconnected — retrying","bad")):
                    page.locator("#conn").evaluate("(e,values)=>{e.textContent=values[0];e.className=values[1]}",[status,css])
                    values.append(measure("#conn"))
                page.locator("#fps").evaluate("e=>{e.style.width='80px';e.style.textAlign='right';e.textContent='55 fps'}")
                values.append(measure("#fps"))
                page.locator("#pDiag").evaluate("e=>{e.textContent='touch';}")
                values.append(measure("#pDiag"))
                page.locator("#archMenu").evaluate("e=>e.click()")
                page.wait_for_timeout(500)
                labels=[]
                for enabled in (False,True):
                    page.locator("body").evaluate("(e,v)=>e.classList.toggle('diag',v)",enabled)
                    group=[]
                    for selector in ("#sUp","#stGL","#archMiniArt .v","#wifiV","#diagV","#stHA","#stNet"):
                        element=page.locator(selector)
                        if not element.is_visible():
                            group.append((([0]*7),0,0));continue
                        sheet=page.locator("#s-settings")
                        sheet.evaluate("e=>e.scrollTop=0")
                        element.evaluate("e=>{e.style.minWidth='260px';e.style.textAlign='right';}")
                        if selector=="#stHA":element.evaluate("e=>e.textContent='connected'")
                        element.scroll_into_view_if_needed()
                        measured=measure(selector)
                        x,y,w,h=measured[:4]
                        element.evaluate("e=>e.style.visibility='hidden'")
                        raw=Image.open(io.BytesIO(page.screenshot(clip=dict(x=x,y=y,width=w,height=h))))
                        offset=sheet.evaluate("e=>Math.round(e.scrollTop)")
                        packed=zlib.compress(rgb565(raw,x,y+offset),7)
                        if packed not in offsets:
                            offsets[packed]=len(bank);bank.extend(packed)
                        measured[1]+=offset
                        group.append((measured,offsets[packed],len(packed)))
                        element.evaluate("e=>e.style.visibility=''")
                    labels.append(group)
                result.append((values,labels))
    def array(v):
        return "{"+",".join(array(x) if isinstance(x,(list,tuple)) else str(int(x)) for x in v)+"}"
    destination.mkdir(exist_ok=True,parents=True)
    (destination/"card_diagnostics.h").write_text(
        '#pragma once\n#include "../study_assets.h"\nnamespace study {\n'
        'struct DiagLabel {int x,y,w,h,baseline,spacing;unsigned colour;};\n'
        'struct DiagSetting {DiagLabel label;unsigned offset,size;};\n'
        'struct DiagView {DiagLabel badges[4];DiagSetting settings[2][7];};\n'
        'constexpr unsigned char diag_settings_art[]='+array(bank)+';\n'
        'constexpr DiagView card_diagnostics_views[]='+array(result)+';\n}\n',encoding="ascii")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("config","states","destination"):parser.add_argument(key,type=Path)
    parser.add_argument("--chromium-cdp")
    args=parser.parse_args()
    build(json.loads(args.config.read_bytes())["config"],json.loads(args.states.read_bytes()),args.destination,args.chromium_cdp)
