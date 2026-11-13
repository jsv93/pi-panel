"""Capture CM5 text metrics, glyph masks and unobscured backgrounds for live fields."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zlib
from PIL import Image
from render import fixture_page,rgb565
from palette_art import PALETTES

SCREENS={
    "home":("clock","datestr","navTemp","spTemp"),
    "climate":("cTemp","cHum","navTemp"),
    "media":("mTitle","mArtist","mElapsed","mDur","mpVolumeValue"),
    "settings":("wifiV","diagV","stHA","stNet","sUp"),
}
CHARS="".join(chr(c) for c in range(32,127))+"°–—…·éÉàäöü’"
MEASURE="""e=>{
  const style=getComputedStyle(e),pad=k=>parseFloat(style[k])||0,r=e.getBoundingClientRect();
  const x=Math.max(0,Math.floor(r.left+pad('paddingLeft'))),y=Math.max(0,Math.floor(r.top+pad('paddingTop')));
  const w=Math.min(720,Math.ceil(r.right-pad('paddingRight')))-x,h=Math.min(1280,Math.ceil(r.bottom-pad('paddingBottom')))-y;
  if(w<=0||h<=0)return null;
  let ctx=document.createElement('canvas').getContext('2d');ctx.font=style.fontWeight+' '+style.fontSize+' '+style.fontFamily;
  const m=ctx.measureText('Mg');
  return {x,y,w,h,font:ctx.font,spacing:Math.round((parseFloat(style.letterSpacing)||0)*64),
    align:style.textAlign,baseline:Math.round((h-m.fontBoundingBoxAscent-m.fontBoundingBoxDescent)/2+m.fontBoundingBoxAscent),
    color:style.color.match(/[\d.]+/g).slice(0,3).map(Number)};
}"""
GLYPHS="""([font,chars])=>{
  let c=document.createElement('canvas');c.width=c.height=512;
  let g=c.getContext('2d',{willReadFrequently:true});g.font=font;g.fillStyle='white';
  return Array.from(chars,ch=>{
    const m=g.measureText(ch),x=-Math.ceil(m.actualBoundingBoxLeft),y=-Math.ceil(m.actualBoundingBoxAscent),
      w=Math.max(0,Math.ceil(m.actualBoundingBoxRight)-x),h=Math.max(0,Math.ceil(m.actualBoundingBoxDescent)-y);
    g.clearRect(0,0,c.width,c.height);g.fillText(ch,10-x,10-y);
    const mask=w&&h?Array.from(g.getImageData(10,10,w,h).data).filter((_,i)=>i%4===3):[];
    return [ch.codePointAt(0),Math.round(m.width*64),x,y,w,h,mask];
  });
}"""

def build(config,states,destination,chromium_cdp=None):
    bank=bytearray()
    seen={}
    fonts={}
    glyphs=[]
    fields=[]
    def store(raw):
        packed=zlib.compress(raw,6)
        if packed not in seen:
            seen[packed]=len(bank)
            bank.extend(packed)
        return seen[packed],len(packed)
    for theme in ("default","ambient"):
        for palette in PALETTES:
            cfg={**config,"display":{**config["display"],"theme":theme,"palette":palette}}
            with fixture_page(cfg,states,chromium_cdp=chromium_cdp) as page:
                page.locator("#fps,#conn,#pDiag").evaluate_all("els=>els.forEach(e=>e.style.visibility='hidden')")
                for screen,ids in SCREENS.items():
                    if screen!="home":
                        menu="#archMenu" if screen=="settings" else f".nav [data-sheet={screen}]"
                        page.locator(menu).evaluate("e=>e.click()")
                        page.wait_for_timeout(650)
                    selected=[]
                    for field in ids:
                        el=page.locator("#"+field)
                        if not el.count() or not el.is_visible():continue
                        m=el.evaluate(MEASURE)
                        if not m:continue
                        selected.append((field,m))
                        el.evaluate("e=>e.style.visibility='hidden'")
                    image=Image.open(io.BytesIO(page.screenshot()))
                    for field,m in selected:
                        x,y,w,h=(m[k] for k in ("x","y","w","h"))
                        bg=store(rgb565(image.crop((x,y,x+w,y+h)),x,y))
                        font=m["font"]
                        if font not in fonts:
                            fonts[font]=len(fonts)
                            for code,advance,gx,gy,gw,gh,alpha in page.evaluate(GLYPHS,[font,CHARS]):
                                pos,size=store(bytes(alpha)) if alpha else (0,0)
                                glyphs.append([fonts[font],code,advance,gx,gy,gw,gh,pos,size])
                        r,g,b=m["color"]
                        color=(r>>3)<<11|(g>>2)<<5|(b>>3)
                        fields.append([theme,palette,screen,field,x,y,w,h,*bg,color,fonts[font],m["baseline"],m["spacing"],{"center":1,"right":2,"end":2}.get(m["align"],0)])
                        page.locator("#"+field).evaluate("e=>e.style.visibility=''")
            print("Captured live text fields",theme,palette,flush=True)
    digest=hashlib.sha256(bank).hexdigest()
    path=destination/"pi-panel"/(digest+".bin")
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=bank:raise ValueError("Existing field bank failed its hash")
    else:
        with path.open("xb") as output:output.write(bank)
    (destination/"card-fields.json").write_text(json.dumps(dict(file=path.name,bytes=len(bank),fields=fields,glyphs=glyphs),separators=(",",":")),encoding="utf8")
    emit_header(destination,dict(file=path.name,bytes=len(bank),fields=fields,glyphs=glyphs))
    print(len(fields),"live fields,",len(bank),"bytes",flush=True)

def emit_header(destination,index):
    digest=Path(index["file"]).stem
    header=["#pragma once",'#include "card_assets.h"',"namespace study {",
            f'constexpr char card_fields_path[]="/sd/pi-panel/{index["file"]}";',
            f'constexpr unsigned card_fields_size={index["bytes"]};',
            "constexpr unsigned char card_fields_sha[]={"+",".join(map(str,bytes.fromhex(digest)))+"};",
            "enum class FieldId {"+",".join(sorted({f[3] for f in index["fields"]}))+"};",
            "struct CardField {int theme,palette;CardPage page;FieldId id;int x,y,w,h;unsigned bg,size,colour;int font,baseline,spacing,align;};",
            "constexpr CardField card_fields[]={"]
    for theme,palette,page,key,*numbers in index["fields"]:
        fields=[("default","ambient").index(theme),PALETTES.index(palette),"CardPage::"+page,"FieldId::"+key,*numbers]
        header.append("{"+",".join(map(str,fields))+"},")
    header.extend(["};","struct CardGlyph {int font;unsigned code;int advance,x,y,w,h;unsigned offset,size;};",
                   "constexpr CardGlyph card_glyphs[]={"])
    for glyph in sorted(index["glyphs"],key=lambda g:(g[0],g[1])):
        header.append("{"+",".join(str(int(value)) for value in glyph)+"},")
    (destination/"card_fields.h").write_text("\n".join(header+["};","}",""]),encoding="ascii")

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("config","states","destination"):parser.add_argument(name,type=Path)
    parser.add_argument("--chromium-cdp")
    args=parser.parse_args()
    build(json.loads(args.config.read_bytes())["config"],json.loads(args.states.read_bytes()),args.destination,args.chromium_cdp)
