"""Capture the kiosk Wi-Fi sheet, password keyboard and network rows for the P4."""
import argparse
import hashlib
import io
import json
import struct
import zlib
from pathlib import Path

from PIL import Image
from card_fields import CHARS, GLYPHS, MEASURE
from control_art import box
from palette_art import PALETTES
from render import fixture_page, rgb565


def build(config, states, destination, chromium_cdp=None):
    bank = bytearray()
    offsets, fonts = {}, {}
    glyphs, layouts, keyboards = [], [], []
    def store(data):
        packed = zlib.compress(data, 7)
        if packed not in offsets:
            offsets[packed] = len(bank)
            bank.extend(packed)
        return offsets[packed], len(packed)

    for theme in ("default", "ambient"):
        for palette in PALETTES:
            cfg = {**config, "display": {**config["display"], "theme": theme, "palette": palette}}
            with fixture_page(cfg, states, chromium_cdp=chromium_cdp) as page:
                nets = [dict(ssid="Network "+str(i), signal=86, secure=i%2==0) for i in range(20)]
                page.route("**/wifi*", lambda route: route.fulfill(json={"status":{"type":"ethernet","available":True},"networks":nets}))
                def click(sel):
                    page.locator(sel).first.evaluate("e=>e.click()")
                click("#archMenu")
                page.wait_for_timeout(650)
                click("#wifiRow")
                page.locator("#wifiList .wnet").first.wait_for(state="visible")
                page.wait_for_timeout(350)
                page.add_style_tag(content="*,*:before,*:after{transition:none!important;animation:none!important}#conn,#fps,#pDiag{visibility:hidden!important}")
                def field(selector):
                    m = page.locator(selector).evaluate(MEASURE)
                    font = m["font"]
                    if font not in fonts:
                        fonts[font] = len(fonts)
                        for code, adv, x, y, w, h, mask in page.evaluate(GLYPHS, [font, CHARS+"•▂▄▆█"]):
                            location = store(bytes(mask)) if mask else (0, 0)
                            glyphs.append((fonts[font],code,adv,x,y,w,h,*location))
                    r,g,b = m["color"]
                    return (*[m[k] for k in ("x","y","w","h")], fonts[font], m["baseline"], m["spacing"],
                            {"center":1,"right":2,"end":2}.get(m["align"],0), (r>>3)<<11|(g>>2)<<5|(b>>3))
                def patch(rect):
                    x,y,w,h = rect
                    img = Image.open(io.BytesIO(page.screenshot(clip=dict(x=x,y=y,width=w,height=h))))
                    return (*rect,*store(rgb565(img,x,y)))
                sheet="#ovWifi .ov-card"
                row="#wifiList .wnet:first-child"
                # At maximum height only the list scrolls in the embedded renderer.
                # Capture all shorter heights at their true, bottom-anchored positions.
                page.locator(sheet).evaluate("e=>e.scrollTop=0")
                track = box(page,row)
                step = box(page,"#wifiList .wnet:nth-child(2)")[1]-track[1]
                shapes = []
                for n in range(21):
                    page.evaluate("n=>document.querySelectorAll('#wifiList .wnet').forEach((e,i)=>e.style.display=i<n?'':'none')",n)
                    top=box(page,sheet)[1]
                    if shapes and shapes[-1][0]==top:break
                    page.locator("#wifiNow,#wifiList").evaluate_all("es=>es.forEach(e=>e.style.visibility='hidden')")
                    shapes.append((top,patch((0,0,720,1280))))
                    page.locator("#wifiNow,#wifiList").evaluate_all("es=>es.forEach(e=>e.style.visibility='')")
                page.evaluate("()=>document.querySelectorAll('#wifiList .wnet').forEach(e=>e.style.display='')")
                fields=[field("#wifiNow"),field(row+" .s"),field(row+" .g")]
                origin=box(page,sheet)[1]
                if shapes[-1][0]!=origin:raise ValueError("Wi-Fi list height did not settle")
                rows=[]
                for secure in (False,True):
                    for active in (False,True):
                        page.locator(row).evaluate("""(e,[secure,active])=>{
                          e.classList.toggle('on',active);e.querySelector('.lock').style.display=secure?'':'none';
                          e.querySelectorAll('.s,.g').forEach(n=>n.style.visibility='hidden');
                        }""",[secure,active])
                        rows.append(patch(track))
                click(row)
                page.locator("#wifiJoinMsg").evaluate("e=>e.textContent='Connecting…'")
                page.locator("#wifiJoinSsid").evaluate("e=>e.style.flex='1'")
                fields.extend(field(sel) for sel in ("#wifiNow","#wifiJoinSsid","#wifiJoinMsg","#wifiPw"))
                page.locator("#wifiNow,#wifiJoinSsid,#wifiJoinMsg,#wifiPw").evaluate_all("es=>es.forEach(e=>e.style.color='transparent')")
                key_top=box(page,sheet)[1]
                cancel,go=box(page,"#wifiCancel"),box(page,"#wifiGo")
                keys=page.locator("#wifiKeys [data-k]").count()
                rects=page.locator("#wifiKeys [data-k]").evaluate_all("es=>es.map(e=>{const r=e.getBoundingClientRect();return [Math.floor(r.x),Math.floor(r.y),Math.ceil(r.right)-Math.floor(r.x),Math.ceil(r.bottom)-Math.floor(r.y)]})")
                if keys!=39:raise ValueError(f"Unexpected keyboard length {keys}")
                first=patch((0,0,720,1280))
                click('#wifiKeys [data-k="__shift"]')
                second=patch((0,0,720,1280))
                if palette==PALETTES[0]:keyboards.append(rects)
                elif rects!=keyboards[-1]:raise ValueError("Palette moved the keyboard")
                layouts.append((shapes,rows,first,second,fields,track,step,origin,key_top,cancel,go))
                print("Wi-Fi",theme,palette,len(shapes),"list heights",flush=True)
    def array(values):
        return "{"+",".join(array(v) if isinstance(v,(list,tuple,bytes)) else str(int(v)) for v in values)+"}"
    while len(bank)%4:bank.append(0)
    table=len(bank)
    for glyph in sorted(glyphs):bank.extend(struct.pack("<iIiiiiiII",*map(int,glyph)))
    digest=hashlib.sha256(bank).digest()
    folder=destination/"pi-panel"
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/(digest.hex()+".bin")
    if path.exists():
        if path.read_bytes()!=bank:raise ValueError("Wi-Fi bank digest mismatch")
    else:
        with path.open("xb") as f:f.write(bank)
    shapes=[shape for row in layouts for shape in row[0]]
    records=[]
    start=0
    for heights,rows,a,b,fields,*other in layouts:
        records.append((start,len(heights),rows,(a,b),fields,*other))
        start+=len(heights)
    header=('#pragma once\n#include "card_library.h"\nnamespace study {\n'
            f'constexpr char card_wifi_path[]="/sd/pi-panel/{path.name}";\n'
            f'constexpr unsigned card_wifi_size={len(bank)};\n'
            "constexpr unsigned char card_wifi_sha[]="+array(digest)+";\n"
            f"constexpr unsigned wifi_glyph_offset={table},wifi_glyph_count={len(glyphs)};\n"
            "struct WifiSheet {int top;CardPlayerPatch image;};\n"
            "struct WifiLayout {int start,count;CardPlayerPatch rows[4],keyboard[2];LibraryField fields[7];Rect row;int step,top,join_top;Rect cancel,go;};\n"
            "constexpr WifiSheet card_wifi_sheets[]="+array(shapes)+";\n"
            "constexpr WifiLayout card_wifi_layouts[]="+array(records)+";\n"
            "constexpr Rect card_wifi_keys[][39]="+array(keyboards)+";\n}\n")
    (destination/"card_wifi.h").write_text(header,encoding="ascii")
    print(len(bank),"bytes of Wi-Fi artwork",flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("config","states","destination"):p.add_argument(name,type=Path)
    p.add_argument("--chromium-cdp")
    a=p.parse_args()
    build(json.loads(a.config.read_bytes())["config"],json.loads(a.states.read_bytes()),a.destination,a.chromium_cdp)
