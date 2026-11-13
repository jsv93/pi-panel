"""Capture the CM5 preset editor, membership rows and save feedback."""
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
    payload=bytearray();positions={};views=[]
    for theme in ("default","ambient"):
        for palette in PALETTES:
            cfg={**config,"display":{**config["display"],"theme":theme,"palette":palette}}
            with fixture_page(cfg,states,chromium_cdp=chromium_cdp) as page:
                def click(selector):
                    page.locator(selector).first.evaluate("e=>e.click()")
                    page.wait_for_timeout(400)
                def capture(rect):
                    x,y,w,h=rect
                    im=Image.open(io.BytesIO(page.screenshot(clip=dict(x=x,y=y,width=w,height=h))))
                    block=zlib.compress(rgb565(im,x,y),7)
                    if block not in positions:
                        positions[block]=len(payload);payload.extend(block)
                    return (*rect,positions[block],len(block))
                click(".nav [data-sheet=scenes]")
                click('#s-scenes [data-sheet="scene-edit"]')
                page.add_style_tag(content="*,*:before,*:after{transition:none!important;animation:none!important}#fps,#conn,#pDiag{visibility:hidden!important}")
                editor=capture((0,0,720,1280))
                back=box(page,"#s-scene-edit [data-close]")
                members=box(page,'#s-scene-edit [data-sheet="scene-members"]')
                saves=[]
                for sel in ("#saveSoftRow","#saveBrightRow"):
                    area=box(page,sel)
                    messages=["","saving…","failed: server unavailable","no lights"]
                    messages += [f"saved {n} light"+("s" if n!=1 else "") for n in range(1,len(config["lights"])+1)]
                    entries=[]
                    for msg in messages:
                        page.locator(sel+" .v").evaluate("(e,v)=>e.textContent=v",msg)
                        entries.append(capture(area))
                    idx=len(payload)
                    for item in entries:payload.extend(struct.pack("<4H2I",*item))
                    saves.append((area,idx))
                click('#s-scene-edit [data-sheet="scene-members"]')
                membership=capture((0,0,720,1280))
                members_back=box(page,"#s-scene-members [data-close]")
                rows=[]
                for i in range(len(config["lights"])):
                    row=page.locator("#archMembers button").nth(i)
                    area=box(page,f"#archMembers button:nth-child({i+1})")
                    entries=[]
                    for failed in (False,True):
                        for active in (False,True):
                            row.evaluate("""(e,[failed,active])=>{
                              e.querySelector('.chk').classList.toggle('on',active);
                              e.querySelector('.v').textContent=failed?'not saved':'';
                            }""",[failed,active])
                            entries.append(capture(area))
                    idx=len(payload)
                    for item in entries:payload.extend(struct.pack("<4H2I",*item))
                    rows.append((area,idx))
                views.append((editor,membership,back,members_back,members,saves,rows))
            print("CM5 scene editor",theme,palette,flush=True)
    def array(v):
        return "{"+",".join(array(x) if isinstance(x,(tuple,list,bytes)) else str(int(x)) for x in v)+"}"
    digest=hashlib.sha256(payload).digest()
    folder=destination/"pi-panel";folder.mkdir(exist_ok=True,parents=True)
    out=folder/(digest.hex()+".bin")
    if out.exists():
        if out.read_bytes()!=payload:raise ValueError("Scene editor digest mismatch")
    else:
        with out.open("xb") as f:f.write(payload)
    (destination/"card_editor.h").write_text(
        '#pragma once\n#include "card_player.h"\nnamespace study {\n'
        f'constexpr char card_editor_path[]="/sd/pi-panel/{out.name}";\n'
        f'constexpr unsigned card_editor_size={len(payload)};\n'
        'constexpr unsigned char card_editor_sha[]='+array(digest)+';\n'
        'struct EditButton {Rect area;unsigned table;};\n'
        'struct EditView {CardPlayerPatch edit,members;Rect back,members_back,list;EditButton saves[2],lights['+
        str(len(config["lights"]))+'];};\nconstexpr EditView card_edit_views[]='+array(views)+';\n}\n',encoding="ascii")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("config","states","destination"):parser.add_argument(key,type=Path)
    parser.add_argument("--chromium-cdp")
    a=parser.parse_args()
    build(json.loads(a.config.read_bytes())["config"],json.loads(a.states.read_bytes()),a.destination,a.chromium_cdp)
