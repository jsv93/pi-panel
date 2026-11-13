"""Capture the legacy speaker picker from the CM5 with all its HA row states."""
import argparse,hashlib,io,json,math,zlib
from pathlib import Path
from PIL import Image
from palette_art import PALETTES
from render import fixture_page,rgb565


def emit(destination, index):
    digest=index["file"].split(".")[0]
    rows=index["rows"]; headings=index["headings"]
    count=len(headings)//12
    def record(r):return "{"+",".join(map(str,r))+"}"
    def table(records,dimension):
        return "constexpr CardSpeakerPatch "+dimension+"={\n"+",\n".join(record(r[-6:]) for r in records)+"};\n"
    # The capture order is theme, palette, state, device.
    ordered=sorted(rows,key=lambda r:(r[0],r[1],r[3],r[2]))
    ordered_heads=sorted(headings,key=lambda r:(r[0],r[1],r[2]))
    head="#pragma once\n#include <cstdint>\nnamespace study {\n"
    head+=f'constexpr char card_speakers_path[]="/sd/pi-panel/{index["file"]}";\nconstexpr unsigned card_speakers_size={index["size"]},card_speaker_count={count};\n'
    head+="constexpr uint8_t card_speakers_sha[]="+record(bytes.fromhex(digest))+";\n"
    head+="struct CardSpeakerPatch {uint16_t x,y,w,h;uint32_t offset,size;};\n"
    head+=table(ordered,"card_speaker_rows[]")+table(ordered_heads,"card_speaker_heads[]")
    (destination/"card_speakers.h").write_text(head+"}\n",encoding="ascii")


def build(config,states,destination,chromium_cdp=None):
    bank=bytearray()
    offsets={}
    rows=[]
    headings=[]
    def capture(image,rect):
        x,y,w,h=rect
        encoded=zlib.compress(rgb565(image.crop((x,y,x+w,y+h)),x,y),6)
        if encoded not in offsets:
            offsets[encoded]=len(bank)
            bank.extend(encoded)
        return (*rect,offsets[encoded],len(encoded))
    def rect(el):
        b=el.bounding_box()
        x,y=math.floor(b["x"]),math.floor(b["y"])
        return (x,y,math.ceil(b["x"]+b["width"])-x,math.ceil(b["y"]+b["height"])-y)
    for theme_id,theme in enumerate(("default","ambient")):
        for pal_id,pal in enumerate(PALETTES):
            cfg={**config,"display":{**config["display"],"theme":theme,"palette":pal}}
            with fixture_page(cfg,states,chromium_cdp=chromium_cdp) as page:
                page.locator(".nav [data-sheet=media]").click()
                page.wait_for_timeout(400)
                page.locator("#icoSpk").click()
                page.wait_for_timeout(650)
                page.add_style_tag(content="*,*::before,*::after{animation:none!important;transition:none!important}")
                devices=page.locator("#spkList .dev")
                boxes=[rect(devices.nth(i)) for i in range(devices.count())]
                if not boxes or any(x<0 or y<0 or x+w>720 or y+h>1280 for x,y,w,h in boxes):
                    raise ValueError("The measured speaker list needs scrolling at this viewport")
                heading=page.locator("#spkNow");heading_rect=rect(heading)
                names=devices.locator(".spk-name").all_text_contents()
                variants=(("Current speaker",True,False),("Unavailable",False,False),
                          ("Control only · transfer unavailable",False,False),("",False,False),("",False,True))
                for mode,(subtitle,selected,enabled) in enumerate(variants):
                    devices.evaluate_all("""(rows,[sub,selected,enabled])=>rows.forEach(e=>{
                        e.classList.toggle('sel',selected);
                        e.querySelector('.sub').textContent=sub;
                        e.querySelector('.spk-transfer').disabled=!enabled;
                    })""",[subtitle,selected,enabled])
                    image=Image.open(io.BytesIO(page.screenshot()))
                    for i,b in enumerate(boxes):
                        if rect(devices.nth(i))!=b:raise ValueError("Speaker geometry changed with state")
                        rows.append((theme_id,pal_id,i,mode,*capture(image,b)))
                for i,name in enumerate(names):
                    heading.evaluate("(e,v)=>e.textContent=v",name)
                    if rect(heading)!=heading_rect:raise ValueError("Speaker heading geometry changed")
                    headings.append((theme_id,pal_id,i,*capture(Image.open(io.BytesIO(page.screenshot())),heading_rect)))
                print("Speaker controls",theme,pal,len(boxes),flush=True)
    digest=hashlib.sha256(bank).hexdigest()
    root=destination/"pi-panel";root.mkdir(parents=True,exist_ok=True)
    path=root/(digest+".bin")
    if path.exists():
        if path.read_bytes()!=bank:raise ValueError("Existing speaker bank differs")
    else:
        with path.open("xb") as f:f.write(bank)
    index=dict(file=path.name,size=len(bank),rows=rows,headings=headings)
    (destination/"speaker-states.json").write_text(json.dumps(index),encoding="utf8")
    emit(destination,index)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("config","states","destination"):p.add_argument(n,type=Path)
    p.add_argument("--chromium-cdp")
    opts=p.parse_args()
    build(json.loads(opts.config.read_bytes())["config"],json.loads(opts.states.read_bytes()),opts.destination,opts.chromium_cdp)
