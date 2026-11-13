"""Measure scrollable CM5 Settings for both diagnostic states and every palette."""
import argparse
import hashlib
import io
import json
import struct
import zlib
from pathlib import Path
from PIL import Image
from control_art import box
from palette_art import PALETTES
from render import fixture_page,rgb565


def build(config,states,destination,chromium_cdp=None):
    bank=bytearray()
    offsets={}
    screens=[]
    routes=[]
    sliders=[]
    ids=("archMiniArt","wifiRow","themeRow","paletteRow","diagRow","saveSoftRow","saveBrightRow","scrollTestRow","reload","bl")
    def save(image,x,y):
        data=zlib.compress(rgb565(image,x,y),8)
        if data not in offsets:
            offsets[data]=len(bank)
            bank.extend(data)
        return (offsets[data],len(data))
    for theme in ("default","ambient"):
        for palette in PALETTES:
            cfg={**config,"display":{**config["display"],"theme":theme,"palette":palette,"diagnostics":False}}
            with fixture_page(cfg,states,chromium_cdp=chromium_cdp) as page:
                page.locator("#archMenu").evaluate("e=>e.click()")
                page.wait_for_timeout(650)
                page.add_style_tag(content="*,*:before,*:after{animation:none!important;transition:none!important}#fps,#conn,#pDiag{visibility:hidden!important}")
                sheet=page.locator("#s-settings")
                x,y,width,height=box(page,"#bl")
                page.locator("#blV").evaluate("e=>e.textContent='100%'")
                lx,ly,lw,lh=box(page,"#blV")
                # The moving thumb extends past the track on Ambient. The
                # percentage is right aligned and has its widest box at 100.
                patches=((x-14,y-14,width+28,height+28),(lx-3,ly-3,lw+6,lh+6))
                records=[]
                for level in range(101):
                    page.evaluate("""n=>{
                      const bar=document.getElementById('bl');
                      bar.querySelector('.fill').style.transform='scaleX('+n/100+')';
                      bar.querySelector('.knob').style.transform='translate(calc('+(n/100*bar.clientWidth)+'px - 50%),-50%)';
                      document.getElementById('blV').textContent=n+'%';
                    }""",level)
                    top=min(r[1] for r in patches)
                    bottom=max(r[1]+r[3] for r in patches)
                    image=Image.open(io.BytesIO(page.screenshot(clip=dict(x=0,y=top,width=720,height=bottom-top))))
                    records.append([save(image.crop((a,b-top,a+c,b+d-top)),a,b) for a,b,c,d in patches])
                table=len(bank)
                for pair in records:
                    for position,length in pair:bank.extend(struct.pack("<II",position,length))
                sliders.append((patches,table))
                for diag in (0,1):
                    if diag:
                        page.locator("#diagRow").evaluate("e=>e.click()")
                        page.wait_for_timeout(300)
                    sheet.evaluate("e=>e.scrollTop=0")
                    if page.locator("body").evaluate("e=>e.classList.contains('diag')")!=bool(diag):
                        raise ValueError("Unexpected diagnostic switch state")
                    h=sheet.evaluate("e=>Math.round(e.getBoundingClientRect().bottom)")
                    def capture_frame():
                        page.evaluate("""()=>{
                          for(const [id,value] of Object.entries({sUp:'5m',sFPS:'55 fps'})){
                            const e=document.getElementById(id);if(e)e.textContent=value;
                          }
                        }""")
                        return Image.open(io.BytesIO(page.screenshot())).convert("RGB")
                    hits=[]
                    for i,name in enumerate(ids):
                        target=page.locator("#"+name)
                        if target.is_visible():
                            hits.append((i,*box(page,"#"+name)))
                    if palette==PALETTES[0]:routes.append(hits)
                    top=capture_frame()
                    distance=sheet.evaluate("e=>{e.scrollTop=e.scrollHeight;return Math.round(e.scrollTop)}")
                    if not 0<distance<h:raise ValueError("Expected two overlapping Settings views")
                    bottom=capture_frame()
                    # Page 0 carries the fixed navigation and its scroll origin.
                    # Page 1 carries the newly exposed rows above the navbar.
                    screens.append((h,distance,*save(top,0,0),*save(bottom.crop((0,h-distance,720,h)),0,h-distance)))
            print("Settings scroll region",theme,palette,flush=True)
    def array(v):
        return "{"+",".join(array(i) if isinstance(i,(list,tuple,bytes)) else str(int(i)) for i in v)+"}"
    digest=hashlib.sha256(bank).digest()
    folder=destination/"pi-panel";folder.mkdir(parents=True,exist_ok=True)
    path=folder/(digest.hex()+".bin")
    if path.exists():
        if path.read_bytes()!=bank:raise ValueError("Settings bank differs")
    else:
        with path.open("xb") as f:f.write(bank)
    hits=[(i,*r) for i,items in enumerate(routes) for r in items]
    header=('#pragma once\n#define STUDY_CARD_BACKLIGHT\n#include "../study_assets.h"\nnamespace study {\n'
            f'constexpr char card_settings_path[]="/sd/pi-panel/{path.name}";\n'
            f'constexpr unsigned card_settings_size={len(bank)};\n'
            "constexpr unsigned char card_settings_sha[]="+array(digest)+";\n"
            "enum class SettingRow {"+",".join(ids)+"};\n"
            "struct SettingSlider {Rect patches[2];unsigned table;};\n"
            "constexpr SettingSlider card_setting_sliders[]="+array(sliders)+";\n"
            "struct SettingView {int height,scroll;unsigned top,top_bytes,tail,tail_bytes;};\n"
            "constexpr SettingView card_settings_views[]="+array(screens)+";\n"
            "struct SettingHit {int state,action,x,y,w,h;};\n"
            "constexpr SettingHit card_settings_hits[]="+array(hits)+";\n}\n")
    (destination/"card_settings.h").write_text(header,encoding="ascii")
    print(len(screens),"scrollable Settings states,",len(bank),"bytes",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("config","states","destination"):parser.add_argument(name,type=Path)
    parser.add_argument("--chromium-cdp")
    args=parser.parse_args()
    build(json.loads(args.config.read_bytes())["config"],json.loads(args.states.read_bytes()),args.destination,args.chromium_cdp)
