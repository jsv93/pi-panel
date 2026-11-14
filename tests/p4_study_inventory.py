"""List every visible CM5 Study touch target and the P4 hit region at its center."""
import json
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/"esphome/study"))
from render import fixture_page


def main():
    config,states,manifest,destination=map(Path,sys.argv[1:])
    views=json.loads(manifest.read_bytes())["views"]
    by_name={v["name"]:v for v in views}
    results={}
    with fixture_page(json.loads(config.read_bytes())["config"],json.loads(states.read_bytes())) as page:
        def click(selector):
            page.locator(selector).first.evaluate("e=>e.click()")
            page.wait_for_timeout(320)
        def capture(name):
            # Only count hittable targets; a background sheet behind a modal is inert.
            targets=page.evaluate("""()=>[...document.querySelectorAll('button,select,input,[role=button],.press,.slider,[data-close],[data-ovclose]')].flatMap(e=>{
              const b=e.getBoundingClientRect(),x=b.x+b.width/2,y=b.y+b.height/2;
              if(!b.width||!b.height||!e.contains(document.elementFromPoint(x,y)))return [];
              const id=e.id||e.getAttribute('aria-label')||e.dataset.sheet||e.getAttribute('data-arch-light')||e.innerText?.trim()||e.className;
              return [{label:id,x:Math.round(x),y:Math.round(y)}];
            })""")
            def wiring(t):
                if name=="lights" and (t["label"].startswith("archLightPower") or t["label"]=="archAllLights"):return "light power"
                if name=="climate" and t["label"] in {"archTargetSlider","spUp","spDown"}:return "thermostat"
                if name=="display" and t["label"]=="bl":return "local backlight"
                if name=="media" and t["label"] in {"shuf","prev","pp","next","rep"}:return "media transport"
                if name=="scene-edit" and t["label"] in {"saveSoftRow","saveBrightRow"}:return "save preset"
                if name=="scene-members" and t["label"] in member_names:return "save membership"
                if name in {"light0","light1","light2"} and t["label"]=="archBrightness":return "brightness slider"
                for l in by_name.get(name,{}).get("links",[]):
                    if l["x"]<=t["x"]<l["x"]+l["w"] and l["y"]<=t["y"]<l["y"]+l["h"]:
                        return l["to"]
                return None
            for t in targets:t["p4_hit"]=wiring(t)
            results[name]=targets
        member_names={l.get("name") or l.get("entity_id") for l in json.loads(config.read_bytes())["config"]["lights"]}
        capture("home")
        for name in ("scenes","lights","climate","blinds","media"):
            click(f'.nav [data-sheet="{name}"]');capture(name)
        for i in range(len(json.loads(config.read_bytes())["config"]["lights"])):
            click('.nav [data-sheet="lights"]');click(f'[data-arch-light="{i}"]')
            capture(f"light{i}")
            click("#archLightMore");capture(f"more-{i}");click("#ovLight [data-ov-back]")
        click("#archMenu");capture("room-menu")
        click('#archRoomLinks [data-sheet="settings"]');capture("settings")
        for name in ("display","diagnostics","scene-edit","scene-members"):
            click(f'[data-sheet="{name}"]');capture(name)
        click("#archRoomStandby");capture("idle")
        page.evaluate("document.querySelector('#doorbellPopup').hidden=false");capture("doorbell")
    destination.write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding="utf-8")
    for name,entries in results.items():
        missing=[t["label"] for t in entries if t["p4_hit"] is None]
        print(f"{name:14} {len(entries):3} visible targets; {len(missing):2} without a mapped center")

if __name__=="__main__":main()
