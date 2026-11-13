"""Capture CM5 light details, playback overlays and the Home music strip."""
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
    data = bytearray()
    offsets, fonts = {}, {}
    glyphs, details, music = [], [], []

    def store(raw):
        packed = zlib.compress(raw, 7)
        if packed not in offsets:
            offsets[packed] = len(data)
            data.extend(packed)
        return offsets[packed], len(packed)

    for theme in ("default", "ambient"):
        for palette in PALETTES:
            cfg = {**config, "display": {**config["display"], "theme": theme, "palette": palette}}
            with fixture_page(cfg, states, chromium_cdp=chromium_cdp) as page:
                def click(selector):
                    page.locator(selector).first.evaluate("e=>e.click()")
                    page.wait_for_timeout(320)

                def grab():
                    return Image.open(io.BytesIO(page.screenshot())).convert("RGB")

                def patch(image, rect):
                    x,y,w,h = rect
                    if x < 0 or y < 0 or x+w > 720 or y+h > 1280 or min(w,h) < 1:
                        raise ValueError(f"Invalid CM5 rectangle {rect}")
                    return (*rect, *store(rgb565(image.crop((x,y,x+w,y+h)),x,y)))

                def clipped(rect):
                    x,y,w,h=rect
                    pic=Image.open(io.BytesIO(page.screenshot(clip=dict(x=x,y=y,width=w,height=h))))
                    return (*rect,*store(rgb565(pic,x,y)))

                def field(sel):
                    m=page.locator(sel).evaluate(MEASURE)
                    font=m["font"]
                    if font not in fonts:
                        fonts[font]=len(fonts)
                        for c,a,x,y,w,h,mask in page.evaluate(GLYPHS,[font,CHARS]):
                            position=store(bytes(mask)) if mask else (0,0)
                            glyphs.append((fonts[font],c,a,x,y,w,h,*position))
                    r,g,b=m["color"]
                    return tuple(m[k] for k in ("x","y","w","h"))+(fonts[font],m["baseline"],m["spacing"],
                            {"right":2,"end":2,"center":1}.get(m["align"],0),(r>>3)<<11|(g>>2)<<5|(b>>3))

                page.add_style_tag(content="*,*:before,*:after{transition:none!important;animation:none!important}#conn,#fps,#pDiag{visibility:hidden!important}")
                click(".nav [data-sheet=lights]")
                for i in range(len(config["lights"])):
                    click(f"#lightRows [data-light='{i}']")
                    top=box(page,"#ovLight .ov-card")[1]
                    member=box(page,"#lightBody .act")
                    checks=[]
                    for failed in (False, True):
                        for checked in (False, True):
                            page.locator("#lightBody .act").evaluate("""(e,[on,failed])=>{
                              e.querySelector('.chk').classList.toggle('on',on);
                              e.querySelector('.v').textContent=failed?'not saved':'';
                            }""",[checked,failed])
                            checks.append(patch(grab(),member))
                    sel="#lightBody .sw,#lightBody .fx .tile"
                    controls=page.locator(sel)
                    bounds=controls.evaluate_all("""es=>es.map(e=>{const r=e.getBoundingClientRect();
                      return [Math.floor(r.x),Math.floor(r.y),Math.ceil(r.right)-Math.floor(r.x),Math.ceil(r.bottom)-Math.floor(r.y)]})""")
                    states_by_control=[[] for _ in bounds]
                    for on in (False,True):
                        controls.evaluate_all("(es,v)=>es.forEach(e=>e.classList.toggle('on',v))",on)
                        image=grab()
                        for slots,r in zip(states_by_control,bounds):slots.append(patch(image,r))
                    offset=len(data)
                    for slots in states_by_control:
                        for rec in slots:data.extend(struct.pack("<4H2I",*rec))
                    colours=page.locator("#lightBody .sw").count()
                    warm=(0,)*4
                    warm_offset=0
                    readout=(0,)*9
                    if page.locator("#ctSlider").is_visible():
                        warm=box(page,"#ctSlider")
                        page.locator("#ctV").evaluate("e=>{e.textContent='6500K';e.style.flex='1';e.style.textAlign='right'}")
                        readout=field("#ctV")
                        page.locator("#ctV").evaluate("e=>e.style.visibility='hidden'")
                        knob=page.locator("#ctSlider .knob")
                        knob.evaluate("e=>e.style.visibility='hidden'")
                        base=patch(grab(),(0,top,720,1280-top))
                        knob.evaluate("e=>e.style.visibility=''")
                        positions=[]
                        for value in range(101):
                            knob.evaluate("(e,v)=>e.style.transform='translate(calc('+v/100*e.parentElement.clientWidth+'px - 50%),-50%)'",value)
                            x,y,w,h=box(page,"#ctSlider .knob")
                            positions.append(clipped((x-9,y-8,w+18,h+20)))
                        warm_offset=len(data)
                        for rec in positions:data.extend(struct.pack("<4H2I",*rec))
                    else:
                        base=patch(grab(),(0,top,720,1280-top))
                    # The sheet overlays live Lights. Save its actual bottom section
                    # and preserve the kiosk's dimmed room in the reference base.
                    details.append((top,checks,offset,colours,len(bounds),warm,warm_offset,readout,base))
                    click("#ovLight [data-ovclose]")
                click(".nav [data-sheet=media]")
                if page.locator("#pp").get_attribute("aria-label")!="Pause":click("#pp")
                page.evaluate("window.fixturePause=document.querySelector('#rmPP').innerHTML")
                click("#mpVolumeButton")
                volbox=box(page,"#mpVolumePopup")
                voltrack=box(page,"#mVol")
                volclose=box(page,"#mpVolumeClose")
                page.locator("#mpVolumeReadout").evaluate("e=>{e.textContent='100%';e.style.minWidth='80px';e.style.textAlign='right'}")
                voltext=field("#mpVolumeReadout")
                page.locator("#mpVolumeReadout").evaluate("e=>e.style.visibility='hidden'")
                volstates=[]
                for value in range(101):
                    page.locator("#mVol").evaluate("""(e,v)=>{
                      e.querySelector('.fill').style.transform='scaleX('+v/100+')';
                      e.querySelector('.knob').style.transform='translate(calc('+v/100*e.clientWidth+'px - 50%), -50%)';
                    }""",value)
                    volstates.append(clipped(volbox))
                voloffset=len(data)
                for rec in volstates:data.extend(struct.pack("<4H2I",*rec))
                click("#mpVolumeClose")
                click("#icoMore")
                queue=[]
                for variant in range(4):
                    page.locator("#queueList").evaluate("""(e,v)=>{
                      e.replaceChildren();
                      const add=(tag,cl,s)=>{const n=document.createElement(tag);n.className=cl;n.textContent=s;e.appendChild(n);};
                      if(v&1)add('div','qrow now','Track');
                      if(v&2)add('div','qrow','Playlist');
                      if(!(v&2))add('p','note',v?'This player doesn’t report a queue':'Nothing playing');
                    }""",variant)
                    rows=page.locator("#queueList .qrow")
                    fields=[field(f"#queueList .qrow:nth-child({n+1})") for n in range(rows.count())]
                    rows.evaluate_all("es=>es.forEach(e=>e.style.color='transparent')")
                    queue.append((box(page,"#ovQueue .ov-card")[1],patch(grab(),(0,0,720,1280)),(fields+[(0,)*9]*2)[:2]))
                click("#ovQueue [data-ovclose]")
                click("#s-media [data-close]")
                strip=[]
                for art in (False,True):
                    page.evaluate("""a=>{
                      const e=document.getElementById('roomMedia');e.hidden=false;e.classList.add('playing');e.classList.remove('idle');
                      document.body.classList.toggle('no-mini-art',!a);
                      for(const id of ['rmArtist','rmTitle']){const t=document.getElementById(id);t.textContent='Playing';t.style.color='';}
                      document.getElementById('rmPP').innerHTML=window.fixturePause;
                    }""",art)
                    fields=[field("#rmTitle"),field("#rmArtist")]
                    page.locator("#rmTitle,#rmArtist").evaluate_all("es=>es.forEach(e=>e.style.color='transparent')")
                    strip.append((patch(grab(),box(page,"#roomMedia")),fields,box(page,"#rmPP"),
                                  box(page,"#roomMedia .art") if art and page.locator("#roomMedia .art").is_visible() else (0,)*4,
                                  box(page,"#roomMedia .prog") if page.locator("#roomMedia .prog").is_visible() else (0,)*4))
                music.append((voloffset,volbox,voltrack,volclose,voltext,queue,strip))
            print("Light and playback overlays",theme,palette,flush=True)
    while len(data)%4:data.append(0)
    table=len(data)
    for rec in sorted(glyphs):data.extend(struct.pack("<iIiiiiiII",*map(int,rec)))
    digest=hashlib.sha256(data).digest()
    folder=destination/"pi-panel"
    folder.mkdir(parents=True,exist_ok=True)
    out=folder/(digest.hex()+".bin")
    if out.exists():
        if out.read_bytes()!=data:raise ValueError("Overlay digest mismatch")
    else:
        with out.open("xb") as fh:fh.write(data)
    def arr(seq):
        return "{"+",".join(arr(x) if isinstance(x,(tuple,list,bytes)) else str(int(x)) for x in seq)+"}"
    header=('#pragma once\n#include "card_library.h"\nnamespace study {\n'
            f'constexpr char card_overlay_path[]="/sd/pi-panel/{out.name}";\n'
            f'constexpr unsigned card_overlay_size={len(data)};\n'
            "constexpr unsigned char card_overlay_sha[]="+arr(digest)+";\n"
            f"constexpr unsigned overlay_glyph_offset={table},overlay_glyph_count={len(glyphs)};\n"
            "struct CardDetail {int top;CardPlayerPatch check[4];unsigned offset;int colours,total;Rect warmth;unsigned knob;LibraryField text;CardPlayerPatch sheet;};\n"
            "struct CardQueue {int top;CardPlayerPatch base;LibraryField text[2];};\n"
            "struct CardStrip {CardPlayerPatch tile;LibraryField text[2];Rect play,cover,progress;};\n"
            "struct CardMusicOverlay {unsigned volume;Rect panel,slider,close;LibraryField level;CardQueue queue[4];CardStrip strip[2];};\n"
            "constexpr CardDetail card_detail_views[]="+arr(details)+";\n"
            "constexpr CardMusicOverlay card_music_views[]="+arr(music)+";\n}\n")
    (destination/"card_overlay.h").write_text(header,encoding="ascii")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("config","states","destination"):p.add_argument(name,type=Path)
    p.add_argument("--chromium-cdp")
    a=p.parse_args()
    build(json.loads(a.config.read_bytes())["config"],json.loads(a.states.read_bytes()),a.destination,a.chromium_cdp)
