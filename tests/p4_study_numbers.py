"""Compare the native numeric compositor with Chromium at several live values."""
import io
import json
from pathlib import Path
import re
import sys
import zlib

import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"esphome/study"))
from render import fixture_page,rgb565

def main():
    config,states,build=map(Path,sys.argv[1:])
    header=(build/"control_art.h").read_text()
    data=bytes.fromhex("".join(re.findall(r"\\x([0-9a-f]{2})",header)))
    def table(name):
        row=next(s for s in header.splitlines() if s.startswith("constexpr ") and " "+name+"[" in s)
        return json.loads(row.split("=",1)[1][:-1].replace("{","[").replace("}","]"))
    def rgb(p):
        v=p.astype(np.int32)
        return np.stack([((v>>11)*255+15)//31,(((v>>5)&63)*255+31)//63,((v&31)*255+15)//31],axis=-1)
    fields=table("number_rects")
    glyphs=table("number_glyphs")
    backgrounds=table("number_backgrounds")
    colours=table("number_colours")
    with fixture_page(json.loads(config.read_bytes())["config"],json.loads(states.read_bytes())) as page:
        for f,sel,examples in [(0,"#archTemp",["12.7","23.8","–"]),(1,"#cTemp",["12.7","23.8","–"]),
                               (2,"#cHum",["57","100","–"]),(3,"#spTemp",["18.0","23.5","–"])]:
            if f==1:
                page.locator('.nav [data-sheet="climate"]').evaluate("e=>e.click()");page.wait_for_timeout(350)
            for text in examples:
                page.locator(sel).evaluate("""(e,[f,t])=>{
                    if(f===0)e.textContent=t+'°';
                    else if(f===3)e.textContent=t;
                    else e.firstChild.textContent=t;
                }""",[f,text])
                x,y,w,h=fields[f]
                reference=Image.open(io.BytesIO(page.screenshot())).crop((x,y,x+w,y+h))
                expected=np.frombuffer(rgb565(reference,x,y),"<u2").reshape(h,w)
                off,size,*_=backgrounds[f]
                actual=np.frombuffer(zlib.decompress(data[off:off+size]),"<u2").copy().reshape(h,w)
                pen=0;color=colours[f]
                for c in text+"@":
                    off,size,gx,gy,gw,gh,advance=glyphs[f]["0123456789.-–@".index(c)]
                    if size:
                        xx=(pen+32)//64+gx
                        ink=np.frombuffer(zlib.decompress(data[off:off+size]),"u1").reshape(gh,gw).astype(np.int32)
                        if f==3:ink=(ink*115+127)//255
                        dest=actual[gy:gy+gh,xx:xx+gw]
                        if dest.shape!=ink.shape:raise ValueError("numeric field clips glyph")
                        result=np.zeros_like(ink)
                        for shift,mask in [(11,31),(5,63),(0,31)]:
                            part=(dest.astype(np.int32)>>shift)&mask
                            result|=((part*(255-ink)+((color>>shift)&mask)*ink+127)//255)<<shift
                        dest[:]=result
                    pen+=advance
                err=np.abs(rgb(expected)-rgb(actual))
                print(sel,text,"mean channel error",round(err.mean(),2),"different pixels",round(100*np.any(err,axis=2).mean(),2))
                if f==3 and text=="23.5":
                    sample=np.concatenate((rgb(expected),rgb(actual)),axis=0).astype("uint8")
                    Image.fromarray(sample).save(build/"target-comparison.png")

if __name__=="__main__":main()
