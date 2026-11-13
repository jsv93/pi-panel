"""Capture the CM5 music controls and Architectural theme picker at panel resolution."""
import argparse
import hashlib
import io
import json
import zlib
from pathlib import Path

from PIL import Image
from control_art import box
from palette_art import PALETTES
from render import fixture_page, rgb565


def build(config, states, dest, chromium_cdp=None):
    bank = bytearray()
    offsets = {}
    player = []
    choices = []
    speaker_top = []
    picker_hits = []

    def capture(page, rect):
        x, y, w, h = rect
        image = Image.open(io.BytesIO(page.screenshot(clip=dict(x=x,y=y,width=w,height=h))))
        block = zlib.compress(rgb565(image, x, y), 8)
        if block not in offsets:
            offsets[block] = len(bank)
            bank.extend(block)
        return (*rect, offsets[block], len(block))

    for theme in ("default", "ambient", "architectural"):
        for palette in PALETTES:
            cfg = {**config, "display": {**config["display"], "theme": theme, "palette": palette}}
            with fixture_page(cfg, states, chromium_cdp=chromium_cdp) as page:
                def click(selector):
                    page.locator(selector).first.evaluate("e=>e.click()")
                    page.wait_for_timeout(350)
                page.add_style_tag(content="*,*::before,*::after{transition:none!important;animation:none!important}")
                page.locator("#fps,#conn,#pDiag").evaluate_all("els=>els.forEach(e=>e.style.visibility='hidden')")
                if theme == "architectural":
                    click("#archMenu")
                    click("#s-room-menu [data-sheet=settings]")
                    click("#s-settings [data-sheet=display]")
                    theme_button = box(page,"#themeRow")
                    click("#themeRow")
                    rows = page.locator("#archChoices button")
                    hits = [theme_button, box(page,"#s-choices [data-close]")]
                    for i in range(rows.count()):
                        hits.append(box(page,f"#archChoices button:nth-child({i+1})"))
                    if not picker_hits:
                        picker_hits = hits
                    if hits != picker_hits or len(hits) != 5:
                        raise ValueError("Architectural theme picker geometry changed")
                    choices.append(capture(page, (0,0,720,1280)))
                    continue
                click(".nav [data-sheet=media]")
                chunks = []
                for selector, attr, labels in (("#shuf","aria-pressed",("false","true")),
                                               ("#pp","aria-label",("Play","Pause")),
                                               ("#rep","aria-label",("Repeat off","Repeat all","Repeat one"))):
                    el = page.locator(selector)
                    rect = box(page, selector)
                    modes = [None]*len(labels)
                    for _ in labels:
                        index = labels.index(el.get_attribute(attr))
                        modes[index] = capture(page, rect)
                        el.evaluate("e=>e.click()")
                    if None in modes:
                        raise ValueError(f"Missing {selector} control state")
                    chunks.extend(modes)
                bar = box(page,"#mBar")
                x,y,w,h = bar
                def progress(pct,playing,thumb):
                    page.evaluate("""([p,playing,thumb])=>{
                      const q=s=>document.querySelector(s);
                      q('#s-media').classList.toggle('mp-playing',playing);
                      q('#mFill').style.transform='scaleX('+p+')';
                      q('.mp-wave').style.width=(p*100)+'%';
                      q('#archSeekThumb').style.cssText='visibility:'+(thumb?'visible':'hidden')+';transform:translateX('+p*100+'%)';
                    }""",[pct,playing,thumb])
                progress(0,False,False)
                chunks.append(capture(page,(x-6,y,w+12,h)))
                progress(1,False,False)
                chunks.append(capture(page,(x+44,y,4,h)))
                progress(1,True,False)
                chunks.append(capture(page,(x+44,y,44,h)))
                progress(.5,False,True)
                chunks.append(capture(page,(x+w//2-5,y+h//2-4,10,10)))
                click("#icoSpk")
                speaker_top.append(box(page,"#ovSpk .ov-card")[1])
                player.append(chunks)
            print("Player controls",theme,palette,flush=True)
    def array(items):
        return "{"+",".join(array(i) if isinstance(i,(list,tuple,bytes)) else str(i) for i in items)+"}"
    dest.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(bank).digest()
    path=dest/"pi-panel"/(digest.hex()+".bin")
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        if path.read_bytes()!=bank:raise ValueError("Player artwork file differs")
    else:
        with path.open("xb") as f:f.write(bank)
    header=("#pragma once\n#include <cstdint>\n#include \"../study_assets.h\"\nnamespace study {\n"
            f'constexpr char card_player_path[]="/sd/pi-panel/{path.name}";\n'
            f"constexpr unsigned card_player_size={len(bank)};\n"
            "constexpr unsigned char card_player_sha[]="+array(digest)+";\n"
            "struct CardPlayerPatch {uint16_t x,y,w,h;uint32_t offset,size;};\n"
            "constexpr CardPlayerPatch card_transport[12][11]="+array(player)+";\n"
            "constexpr CardPlayerPatch card_theme_choices[6]="+array(choices)+";\n"
            "constexpr Rect card_choice_hits[]="+array(picker_hits)+";\n"
            "constexpr int card_speaker_top[]="+array(speaker_top)+";\n}\n")
    (dest/"card_player.h").write_text(header,encoding="ascii")
    print("Captured",len(bank),"bytes for theme selection and Music",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("config","states","destination"):parser.add_argument(name,type=Path)
    parser.add_argument("--chromium-cdp")
    args=parser.parse_args()
    build(json.loads(args.config.read_bytes())["config"],json.loads(args.states.read_bytes()),args.destination,args.chromium_cdp)
