"""Capture the Default and Ambient preset highlight states from CM5 Chromium."""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import zlib
from PIL import Image
from render import fixture_page, rgb565
from palette_art import PALETTES


def build(config, states, destination, chromium_cdp=None):
    data = bytearray()
    positions = {}
    buttons = []
    for theme in ("default", "ambient"):
        for palette in PALETTES:
            cfg = {**config, "display": {**config["display"], "theme": theme, "palette": palette}}
            with fixture_page(cfg, states, chromium_cdp=chromium_cdp) as page:
                page.add_style_tag(content="*,*::before,*::after{animation:none!important;transition:none!important}")
                for screen in ("home", "scenes"):
                    if screen == "scenes":
                        page.locator('.nav [data-sheet="scenes"]').click()
                        page.wait_for_timeout(400)
                    preset = page.locator(("#room" if screen=="home" else "#s-scenes") + " [data-preset]")
                    count = preset.count()
                    if count != (2 if screen=="home" else 3):
                        raise ValueError(f"Unexpected preset count on {screen}")
                    rects = []
                    for i in range(count):
                        r = preset.nth(i).bounding_box()
                        x,y=math.floor(r["x"]),math.floor(r["y"])
                        rects.append((x,y,math.ceil(r["x"]+r["width"])-x,math.ceil(r["y"]+r["height"])-y))
                    for active in (False,True):
                        preset.evaluate_all("(buttons,on)=>buttons.forEach(b=>b.classList.toggle('active',on))",active)
                        shot = Image.open(io.BytesIO(page.screenshot()))
                        for i,(x,y,w,h) in enumerate(rects):
                            encoded = zlib.compress(rgb565(shot.crop((x,y,x+w,y+h)),x,y),6)
                            if encoded not in positions:
                                positions[encoded]=len(data)
                                data.extend(encoded)
                            key=preset.nth(i).get_attribute("data-preset")
                            buttons.append((theme,palette,screen,key,active,(x,y,w,h),positions[encoded],len(encoded)))
    digest=hashlib.sha256(data).hexdigest()
    root=destination/"pi-panel"
    root.mkdir(parents=True,exist_ok=True)
    file=root/(digest+".bin")
    if file.exists():
        if file.read_bytes()!=data:raise ValueError("Existing preset file failed its hash")
    else:
        with file.open("xb") as stream:stream.write(data)
    index = dict(file=file.name,bytes=len(data),buttons=buttons)
    (destination/"scene-controls.json").write_text(json.dumps(index,separators=(",",":")),encoding="utf8")
    emit_header(destination,index)
    print("Captured",len(buttons),"CM5 preset states,",len(data),"bytes",flush=True)

def emit_header(destination,index):
    digest=Path(index["file"]).stem
    header=['#pragma once','namespace study {',f'constexpr char card_presets_path[]="/sd/pi-panel/{index["file"]}";',
            f'constexpr unsigned card_presets_size={index["bytes"]};',
            'constexpr unsigned char card_presets_sha[]={'+','.join(map(str,bytes.fromhex(digest)))+'};',
            'struct CardPresetPatch {int theme,palette,page,mask;bool active;int x,y,w,h;unsigned offset,size;};',
            'constexpr CardPresetPatch card_preset_patches[]={']
    for theme,palette,screen,key,on,rect,offset,size in index["buttons"]:
        fields=[("default","ambient").index(theme),PALETTES.index(palette),int(screen=="scenes"),
                1<<("soft","off","bright").index(key),int(on),*rect,offset,size]
        header.append("  {"+",".join(map(str,fields))+"},")
    (destination/"card_presets.h").write_text("\n".join(header+["};","}",""]),encoding="ascii")

if __name__=="__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("config","states","destination"):p.add_argument(arg,type=Path)
    p.add_argument("--chromium-cdp")
    args=p.parse_args()
    build(json.loads(args.config.read_bytes())["config"],json.loads(args.states.read_bytes()),args.destination,args.chromium_cdp)
