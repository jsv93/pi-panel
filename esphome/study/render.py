"""Build local 720x1280 RGB565 artwork and hit areas from the released kiosk."""
from contextlib import contextmanager
import argparse
import io
import json
import math
from pathlib import Path
import zlib

from PIL import Image
import numpy as np
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
UI = ROOT.parents[1] / "panel-ui"
ORIGIN = "http://study-bench.invalid"
W, H = 720, 1280


def rgb565(im, x=0, y=0):
    # Distribute the two surrounding display levels over a 4x4 cell. Using
    # one threshold for all channels keeps fine neutral textures correlated.
    bayer = np.array([[0,8,2,10],[12,4,14,6],[3,11,1,9],[15,7,13,5]])
    rows = (np.arange(im.height) + y) % 4
    cols = (np.arange(im.width) + x) % 4
    threshold = ((2*bayer[rows[:,None],cols]+1)*255//32).astype(np.uint16)
    rgb = np.asarray(im.convert("RGB"),dtype=np.uint16)
    r,g,b = ((rgb[...,i]*levels+threshold)//255 for i,levels in enumerate((31,63,31)))
    return ((r<<11)|(g<<5)|b).astype("<u2").tobytes()


@contextmanager
def fixture_page(cfg, states, browse_children=None, *, chromium_cdp=None):
    cfg={**cfg, "display": {**cfg["display"], "idle_timeout_s":3600}}
    # Only fixture sockets exist in this context. Buttons cannot operate the house.
    fake = """
    window.WebSocket = class {
      constructor(url) {this.ha=url.includes('/api/websocket');this.readyState=1;
        setTimeout(()=>{this.onopen?.();if(this.ha)this.emit({type:'auth_required'})},0);}
      emit(m){this.onmessage?.({data:JSON.stringify(m)})}
      send(raw){if(!this.ha)return;const m=JSON.parse(raw);
        queueMicrotask(()=>this.emit(m.type==='auth'?{type:'auth_ok'}:
          {type:'result',id:m.id,success:true,result:m.type==='get_states'?window.fixtureStates:
           m.type==='media_player/browse_media'?{children:window.fixtureLibrary}: {}}));}
      close(){this.readyState=3}
    };"""
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(chromium_cdp) if chromium_cdp else pw.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1,
                                locale="en-AU", timezone_id="Australia/Brisbane")
        page.add_init_script("window.fixtureStates="+json.dumps(states)+";window.fixtureLibrary="+json.dumps(browse_children or [])+";"+fake)
        def route(r):
            url = r.request.url
            if not url.startswith(ORIGIN+"/"):
                return r.abort()
            name = url[len(ORIGIN)+1:].split("?")[0]
            if name in ("panel.html","abstract-room.webp") or name in {p.name for p in UI.glob("*.woff2")}:
                return r.fulfill(path=UI/name)
            if name == "config.json":
                return r.fulfill(json=cfg)
            if name == "secrets.json":
                return r.fulfill(json={"ha_token":"offline-fixture"})
            return r.fulfill(json={})
        page.route("**/*", route)
        page.goto(ORIGIN+"/panel.html")
        page.wait_for_function("theme=>document.body.classList.contains('theme-'+theme)",arg=cfg["display"].get("theme","default"))
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(400)
        try:
            yield page
        finally:
            if chromium_cdp:
                page.context.close()
            else:
                browser.close()

def generate(cfg, states, dest):
    dest.mkdir(parents=True, exist_ok=True)
    with fixture_page(cfg, states) as page:
        views, data = [], bytearray()
        def store(name, rect=None, motion_source=False):
            b=page.screenshot(clip=rect) if rect else page.screenshot()
            im=Image.open(io.BytesIO(b))
            if motion_source:
                (dest/(name+"-rgb.png")).write_bytes(b)
            packed=rgb565(im,rect["x"],rect["y"]) if rect else rgb565(im)
            encoded=zlib.compress(packed, 9)
            offset=len(data)
            data.extend(encoded)
            return dict(name=name,offset=offset,size=len(encoded),w=im.width,h=im.height)
        def capture(name):
            page.wait_for_timeout(320)
            view=store(name,motion_source=True)
            view["links"]=page.evaluate("""() => Array.from(document.querySelectorAll('[data-sheet],[data-close],[data-arch-light],#doorbellClose,#archRoomStandby,#archDimUp,#archDimDown,#archLightToggle,[data-preset]')).flatMap(e=>{
              const b=e.getBoundingClientRect(), x=Math.round(b.x),y=Math.round(b.y),w=Math.round(b.width),h=Math.round(b.height);
              if(!w||!h||!e.contains(document.elementFromPoint(x+w/2,y+h/2)))return [];
              const to=e.id==='doorbellClose'||e.hasAttribute('data-close')?'back':
                e.id==='archRoomStandby'?'idle':e.dataset.preset||({'archDimUp':'up','archDimDown':'down','archLightToggle':'toggle'}[e.id])||
                (e.hasAttribute('data-arch-light')?'light'+e.dataset.archLight:e.dataset.sheet);
              return [{x,y,w,h,to,root:!!e.closest('.nav')}];})""")
            views.append(view)
            if name in ("home","doorbell"):
                page.screenshot(path=dest/(name+".png"))
            return view
        def nav(name):
            page.locator('.nav [data-sheet="'+name+'"]').evaluate("e=>e.click()")
        capture("home")
        for name in ("scenes","lights","climate","blinds","media"):
            nav(name)
            capture(name)
            if name=="scenes":
                scene_sprites=[]
                for preset in ("soft","off","bright"):
                    page.locator('#s-scenes [data-preset="'+preset+'"]').evaluate("e=>e.click()")
                    page.wait_for_timeout(300)
                    scene_sprites.append(store(preset))
                # Restore the real Study baseline after simulating scene presses.
                page.reload()
                page.wait_for_function("document.querySelector('#archRoom').textContent==='Study'")
                page.evaluate("document.fonts.ready")
        initial=[]
        for i in range(len(cfg["lights"])):
            nav("lights")
            page.locator('[data-arch-light="'+str(i)+'"]').evaluate("e=>e.click()")
            view=capture("light"+str(i))
            initial.append(int(page.locator("#archBrightnessValue").inner_text()))
            # Build the actual value and slider artwork at each percent. Keep only
            # the portion that changes. Native touch chooses the matching patch.
            if i==0:
                def rect(sel):
                    return page.locator(sel).bounding_box()
                bar=rect("#archBrightness")
                def whole(box):
                    x,y=math.floor(box["x"]),math.floor(box["y"])
                    return dict(x=x,y=y,width=math.ceil(box["x"]+box["width"])-x,height=math.ceil(box["y"]+box["height"])-y)
                slider=whole(bar)
                knob=rect("#archBrightness .knob")
                margin=math.ceil(knob["width"]/2)
                slider_paint={**slider,"x":slider["x"]-margin,"width":slider["width"]+2*margin}
                patches=[]
                full=whole(rect(".arch-reading:visible"))
                for value in range(101):
                    page.locator("#archBrightnessValue").evaluate("(e,v)=>e.textContent=v",value)
                    page.locator("#archBrightness").evaluate("""(e,v)=>{
                      e.querySelector('.fill').style.transform='scaleX('+v/100+')';
                      e.querySelector('.knob').style.transform='translate(calc('+v/100*e.clientWidth+'px - 50%),-50%)';
                    }""",value)
                    patches.append([store(str(value),full),store(str(value),slider_paint)])
        page.locator("#archMenu").evaluate("e=>e.click()")
        capture("room-menu")
        page.locator('#archRoomLinks [data-sheet=settings]').evaluate("e=>e.click()")
        capture("settings")
        for name in ("display","diagnostics","scene-edit","scene-members"):
            if name in ("diagnostics","scene-edit"):
                page.locator('#s-'+("display" if name=="diagnostics" else "diagnostics")+' [data-close]').evaluate("e=>e.click()")
            page.locator('[data-sheet="'+name+'"]').first.evaluate("e=>e.click()")
            capture(name)
        page.locator('#archRoomStandby').evaluate("e=>e.click()")
        capture("idle")
        page.evaluate("""title=>{document.querySelector('#doorbellPopup').hidden=false;
          document.querySelector('#doorbellTitle').textContent=title;
          document.querySelector('#doorbellLabel').textContent='DOORBELL TEST';
          document.querySelector('#doorbellDuration').textContent='Closes automatically after 60 seconds · Muted';
          document.querySelector('#doorbellState').textContent='Live';}""",cfg["doorbell"]["title"])
        capture("doorbell")
        video=page.locator("#doorbellVideo").bounding_box()
    presets=[[(-1 if light.get("include_presets") is False else
               0 if name=="off" else light.get(name,30 if name=="soft" else 100)) for light in cfg["lights"]]
             for name in ("soft","off","bright")]
    manifest=dict(views=views,slider=slider,slider_paint=slider_paint,reading=full,patches=patches,video=video,initial=initial,
                  scene_sprites=scene_sprites,presets=presets)
    (dest/"screens.json").write_text(json.dumps(manifest),encoding="utf8")
    (dest/"screens.bin").write_bytes(data)
    print(f"{len(views)} Study views, {len(patches)} slider positions, {len(data):,} bytes of compressed artwork")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("config",type=Path);p.add_argument("states",type=Path);p.add_argument("destination",type=Path)
    a=p.parse_args()
    cfg=json.loads(a.config.read_bytes())["config"]
    if cfg["display"]["theme"]!="architectural":
        p.error("this native layout uses the Architectural screen geometry")
    if cfg["display"].get("palette","linen") not in ("midnight","ember","slate","heath","mono","linen"):
        p.error("unknown kiosk palette")
    assert cfg["display"]["screen_width"]==W and cfg["display"]["screen_height"]==H
    generate(cfg,json.loads(a.states.read_bytes()),a.destination)
