"""Capture both local library layouts, templates and typography on the CM5."""
import argparse
import hashlib
import io
import json
import struct
import zlib
from pathlib import Path
from PIL import Image
from card_fields import MEASURE, GLYPHS, CHARS
from control_art import box
from palette_art import PALETTES
from render import fixture_page, rgb565


def build(config, states, destination, chromium_cdp=None):
    bank=bytearray()
    offsets={}
    fonts={}
    glyphs=[]
    layouts=[]
    def store(raw):
        chunk=zlib.compress(raw,7)
        if chunk not in offsets:
            offsets[chunk]=len(bank)
            bank.extend(chunk)
        return offsets[chunk],len(chunk)
    items=[dict(title="Folder" if i%2==0 else "Track",media_class="directory" if i%2==0 else "track",
                can_expand=i%2==0,can_play=i%2!=0,media_content_id=str(i),media_content_type="music") for i in range(8)]
    for theme in ("default","ambient"):
        for palette in PALETTES:
            cfg={**config,"display":{**config["display"],"theme":theme,"palette":palette,"browse_view":"tiles"}}
            with fixture_page(cfg,states,items,chromium_cdp=chromium_cdp) as page:
                for selector in (".nav [data-sheet=media]","#icoSearch"):
                    page.locator(selector).evaluate("e=>e.click()")
                    page.wait_for_timeout(400)
                page.add_style_tag(content="*,*:before,*:after{transition:none!important;animation:none!important}#fps,#conn,#pDiag{visibility:hidden!important}.bitem{content-visibility:visible!important}")
                def patch(r):
                    x,y,w,h=r
                    img=Image.open(io.BytesIO(page.screenshot(clip=dict(x=x,y=y,width=w,height=h))))
                    return (*r,*store(rgb565(img,x,y)))
                def text(selector):
                    el=page.locator(selector)
                    m=el.evaluate(MEASURE)
                    font=m["font"]
                    if font not in fonts:
                        fonts[font]=len(fonts)
                        for c,advance,x,y,w,h,alphas in page.evaluate(GLYPHS,[font,CHARS+"›"]):
                            pos=store(bytes(alphas)) if alphas else (0,0)
                            glyphs.append((fonts[font],c,advance,x,y,w,h,*pos))
                    r,g,b=m["color"]
                    return tuple(m[k] for k in ("x","y","w","h"))+(fonts[font],m["baseline"],m["spacing"],
                                {"center":1,"right":2,"end":2}.get(m["align"],0),(r>>3)<<11|(g>>2)<<5|(b>>3))
                for mode in (0,1):
                    if mode:
                        page.locator("#bView").click()
                        page.wait_for_timeout(250)
                    cols=2 if page.locator("#bList").evaluate("e=>e.classList.contains('tiles')") else 1
                    if cols!=2-mode:raise ValueError("Unexpected library layout order")
                    tiles=[box(page,f"#bList .bitem:nth-child({i+1})") for i in range(3)]
                    viewport=box(page,"#bList")
                    fields=[text("#bTitle"),text("#bCrumb")]
                    patches=[]
                    icons=[]
                    for i in range(2):
                        sel=f"#bList .bitem:nth-child({i+1})"
                        fields.extend(text(sel+" "+f) for f in (".n",".s"))
                        icons.append(box(page,sel+" .bthumb"))
                        page.locator(sel+" .bmeta").evaluate("e=>e.style.visibility='hidden'")
                        patches.append(patch(tiles[i]))
                    page.locator("#bTitle,#bCrumb,#bList").evaluate_all("es=>es.forEach(e=>e.style.visibility='hidden')")
                    base=patch((0,0,720,1280))
                    page.locator("#bTitle,#bCrumb,#bList,#bList .bmeta").evaluate_all("es=>es.forEach(e=>e.style.visibility='')")
                    layouts.append((base,patches,icons,fields,viewport,cols,tiles[cols][1]-tiles[0][1],
                                    tiles[1][0]-tiles[0][0],box(page,"#bBack"),box(page,"#bView")))
                print("Library templates",theme,palette,flush=True)
    def array(v):
        return "{"+",".join(array(i) if isinstance(i,(list,tuple,bytes)) else str(int(i)) for i in v)+"}"
    # The lookup table belongs with the glyph masks. Loading it from the card
    # once leaves both existing OTA application slots at their original size.
    while len(bank)%4:bank.append(0)
    glyph_offset=len(bank)
    for glyph in sorted(glyphs):
        bank.extend(struct.pack("<iIiiiiiII",*(int(v) for v in glyph)))
    digest=hashlib.sha256(bank).digest()
    directory=destination/"pi-panel"
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/(digest.hex()+".bin")
    if path.exists():
        if path.read_bytes()!=bank:raise ValueError("Existing library bank differs")
    else:
        with path.open("xb") as f:f.write(bank)
    header=('#pragma once\n#include "../study_assets.h"\n#include "card_player.h"\n#include "card_fields.h"\nnamespace study {\n'
            f'constexpr char card_library_path[]="/sd/pi-panel/{path.name}";\n'
            f'constexpr unsigned card_library_size={len(bank)};\n'
            "constexpr unsigned char card_library_sha[]="+array(digest)+";\n"
            "struct LibraryField {int x,y,w,h,font,baseline,spacing,align;unsigned colour;};\n"
            "struct LibraryLayout {CardPlayerPatch base,tiles[2];Rect icons[2];LibraryField fields[6];Rect viewport;int cols,step,spacing;Rect back,toggle;};\n"
            "constexpr LibraryLayout card_library_layouts[]="+array(layouts)+";\n"
            f"constexpr unsigned library_glyph_offset={glyph_offset},library_glyph_count={len(glyphs)};\n}}\n")
    (destination/"card_library.h").write_text(header,encoding="ascii")
    print("Captured",len(layouts),"library layouts and",len(bank),"bytes",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("config","states","destination"):parser.add_argument(name,type=Path)
    parser.add_argument("--chromium-cdp")
    args=parser.parse_args()
    build(json.loads(args.config.read_bytes())["config"],json.loads(args.states.read_bytes()),args.destination,args.chromium_cdp)
