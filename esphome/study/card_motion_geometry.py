"""Measure display geometry shared by animated Home controls and the Wi-Fi sheet."""
import argparse
import json
from pathlib import Path

from card_fields import MEASURE
from control_art import box
from palette_art import PALETTES
from render import fixture_page

def build(config, states, output, chromium_cdp):
    def array(values):
        return "{" + ",".join(array(v) if isinstance(v,(tuple,list)) else str(v) for v in values) + "}"
    bars, accents, empty = [], [], []
    for theme in ("default","ambient","architectural"):
        with fixture_page({**config,"display":{**config["display"],"theme":theme}},
                          states,chromium_cdp=chromium_cdp) as page:
            page.evaluate("""() => {
              const strip=document.querySelector('#roomMedia');
              strip.hidden=false;strip.classList.remove('idle');strip.classList.add('playing');
              document.querySelector('#rmTitle').textContent='Playing';
            }""")
            page.add_style_tag(content="#rmEq i{animation:none!important;transform:none!important}")
            sizes=[]
            for cover in (False,True):
                page.evaluate("v=>document.body.classList.toggle('no-mini-art',!v)",cover is False)
                sizes.append([box(page,f"#rmEq i:nth-child({i+1})") for i in range(4)])
            bars.append(sizes)
            colours=[]
            for palette in PALETTES:
                page.evaluate("v=>{document.body.classList.remove(...Array.from(document.body.classList).filter(x=>x.startsWith('pal-')));document.body.classList.add('pal-'+v);document.documentElement.dataset.palette=v;document.body.dataset.palette=v;}",palette)
                rgb=page.locator("#rmEq i").first.evaluate("e=>getComputedStyle(e).backgroundColor.match(/\\d+/g).map(Number)")
                colours.append((rgb[0]>>3)<<11|(rgb[1]>>2)<<5|(rgb[2]>>3))
            accents.append(colours)
            if theme!="architectural":
                page.route("**/wifi*",lambda r:r.fulfill(json={"status":{"available":True},"networks":[]}))
                for selector in ("#archMenu","#wifiRow"):
                    page.locator(selector).first.evaluate("e=>e.click()")
                    page.wait_for_timeout(400)
                note=page.locator("#wifiList .note")
                note.wait_for(state="visible")
                field=note.evaluate(MEASURE)
                top=box(page,"#ovWifi .ov-card")[1]
                empty.append([field["x"],field["y"],field["w"],field["h"],field["baseline"],top])
    output.write_text("#pragma once\nnamespace study {\nconstexpr Rect eq_bars[3][2][4]="+array(bars)+";\n"
                      +"constexpr uint16_t eq_accent[3][6]="+array(accents)+";\n"
                      +"constexpr int wifi_empty_note[2][6]="+array(empty)+";\n}\n",encoding="ascii")

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("config","states","output"):p.add_argument(name,type=Path)
    p.add_argument("--chromium-cdp")
    a=p.parse_args()
    build(json.loads(a.config.read_bytes())["config"],json.loads(a.states.read_bytes()),a.output,a.chromium_cdp)
