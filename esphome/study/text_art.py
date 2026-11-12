"""Capture text backgrounds, metrics and glyph masks from the Study kiosk."""
import io,json,sys,zlib
from pathlib import Path
from PIL import Image
from render import fixture_page,rgb565
from control_art import box


def capture(config,states,dest):
    # Include the punctuation used by the HA player and the dashboard.
    chars="".join(chr(i) for i in range(32,127))+" °éèëàáäöóñüß–—‘’“”…•"
    bank=bytearray();offsets={};fonts={};fields=[]
    def put(data):
        if data not in offsets:offsets[data]=len(bank);bank.extend(data)
        return offsets[data],len(data)
    with fixture_page(config,states) as page:
        def click(sel):page.locator(sel).first.evaluate("e=>e.click()");page.wait_for_timeout(350)
        def field(name,sel,kind="full",alignment=None,subset=chars):
            el=page.locator(sel)
            meta=el.evaluate("""(e,kind)=>{
              const s=getComputedStyle(e),r=e.getBoundingClientRect(),p=e.parentElement.getBoundingClientRect(),
                x=kind==='right'?Math.floor(p.x+p.width*.48):kind==='time-right'?Math.floor(p.right-130):Math.floor(r.x),
                right=kind==='right'||kind==='time-right'?p.right:kind==='time-left'?x+130:r.right, y=Math.floor(r.y),h=Math.ceil(r.bottom)-y,
                c=document.createElement('canvas').getContext('2d');
              c.font=s.fontWeight+' '+s.fontSize+' '+s.fontFamily;
              let m=c.measureText('Mg');return {x,y,w:Math.ceil(right)-x,h,font:c.font,spacing:parseFloat(s.letterSpacing)||0,
                align:s.textAlign,color:s.color.match(/[\d.]+/g).slice(0,3).map(Number),
                baseline:Math.round((r.height-m.fontBoundingBoxAscent-m.fontBoundingBoxDescent)/2+m.fontBoundingBoxAscent+r.y-y)};
            }""",kind)
            x,y,w,h=(meta[k] for k in ("x","y","w","h"))
            if min(w,h)<=0:raise ValueError(f"Missing text area {name}")
            el.evaluate("e=>e.style.visibility='hidden'")
            img=Image.open(io.BytesIO(page.screenshot())).crop((x,y,x+w,y+h))
            el.evaluate("e=>e.style.visibility=''")
            bg=put(zlib.compress(rgb565(img,x,y),9))
            font=meta["font"]
            key=(font,subset)
            if key not in fonts:
                glyphs=page.evaluate("""([font,chars])=>{let c=document.createElement('canvas'),ctx=c.getContext('2d',{willReadFrequently:true});
                  c.width=220;c.height=220;ctx.font=font;ctx.fillStyle='white';
                  return Array.from(chars,ch=>{ctx.clearRect(0,0,220,220);let m=ctx.measureText(ch);
                    let x=-Math.ceil(m.actualBoundingBoxLeft),y=-Math.ceil(m.actualBoundingBoxAscent),
                      w=Math.max(0,Math.ceil(m.actualBoundingBoxRight)-x),h=Math.max(0,Math.ceil(m.actualBoundingBoxDescent)-y);
                    ctx.fillText(ch,10-x,10-y);
                    let alpha=w&&h?Array.from(ctx.getImageData(10,10,w,h).data).filter((_,i)=>i%4===3):[];
                    return [ch.codePointAt(0),Math.round(m.width*64),x,y,w,h,alpha];});
                }""",[font,subset])
                records=[]
                for code,adv,gx,gy,gw,gh,alpha in glyphs:
                    pos,n=put(zlib.compress(bytes(alpha),9)) if alpha else (0,0)
                    records.append(tuple(map(int,(code,adv,gx,gy,gw,gh,pos,n))))
                fonts[key]=sorted(records)
            r,g,b=meta["color"];col=(r>>3)<<11|(g>>2)<<5|(b>>3)
            align=alignment or meta["align"]
            fields.append((name,(x,y,w,h),bg,col,list(fonts).index(key),meta["baseline"],round(meta["spacing"]*64),{"center":1,"right":2,"end":2}.get(align,0)))
        page.locator("#roomMedia").evaluate("e=>{e.hidden=false;e.classList.add('playing');e.classList.remove('idle')}")
        strip=box(page,"#roomMedia");strip_play=box(page,"#rmPP")
        page.locator("#rmArtist").evaluate("e=>e.textContent='Artist'")
        def region(rect):
            x,y,w,h=rect
            img=Image.open(io.BytesIO(page.screenshot())).crop((x,y,x+w,y+h))
            return put(zlib.compress(rgb565(img,x,y),9))
        strip_shown=region(strip)
        field("home_title","#rmTitle");field("home_artist","#rmArtist")
        page.locator("#roomMedia").evaluate("e=>e.hidden=true")
        strip_hidden=region(strip)
        click('.nav [data-sheet="media"]')
        field("song_title","#mTitle");field("song_artist","#mArtist")
        digits="0123456789:?"
        field("elapsed_time","#mElapsed","time-left","left",digits)
        field("total_time","#mDur","time-right","right",digits)
        seek=box(page,"#mBar");x,y,w,h=seek
        rail=(x-6,y,w+12,h)
        page.add_style_tag(content=".mp-wave svg{animation:none!important}")
        page.evaluate("document.querySelector('#s-media').classList.remove('mp-playing');document.querySelector('#archSeekThumb').style.visibility='hidden';document.querySelector('#mFill').style.transform='scaleX(0)'")
        empty=region(rail)
        page.evaluate("document.querySelector('#mFill').style.transform='scaleX(1)'")
        filled=region((x+44,y,1,h))
        page.evaluate("document.querySelector('#s-media').classList.add('mp-playing');document.querySelector('.mp-wave').style.width='100%'")
        wave=region((x+44,y,44,h))
        page.evaluate("document.querySelector('#s-media').classList.remove('mp-playing');document.querySelector('#archSeekThumb').style.cssText='transform:translateX(50%)';document.querySelector('#mFill').style.transform='scaleX(.5)'")
        thumb=region((x+w//2-5,y+h//2-4,10,10))
        click("#archMenu")
        field("menu_date","#archDate")
        click('#archRoomLinks [data-sheet="settings"]');click('#archSettingsLinks [data-sheet="diagnostics"]')
        for name,sel in (("ha_status","#stHA"),("backlight_status","#stBL"),("net_status","#stNet"),("up_status","#sUp")):
            field(name,sel,"right","right")
    def c(v):return "{"+",".join(c(x) if isinstance(x,(list,tuple)) else str(x) for x in v)+"}"
    with (dest/"text_art.h").open("w",encoding="ascii") as f:
        f.write('#pragma once\n#include "study_assets.h"\nnamespace study {\nstatic const uint8_t text_art[]=\n')
        for o in range(0,len(bank),256):f.write('"'+''.join(f'\\x{b:02x}' for b in bank[o:o+256])+'"\n')
        f.write(';\nstruct TextGlyph{uint16_t code,advance;int16_t x,y;uint16_t w,h;uint32_t offset,size;};\n')
        starts=[0];flat=[]
        for records in fonts.values():flat.extend(records);starts.append(len(flat))
        f.write("constexpr TextGlyph text_glyphs[]="+c(flat)+";\nconstexpr int text_starts[]="+c(starts)+";\n")
        f.write("struct TextArea{Rect rect;uint32_t bg,size;uint16_t colour;int font,baseline,spacing,align;};\n")
        f.write("constexpr Rect home_strip="+c(strip)+",home_play="+c(strip_play)+";\n")
        f.write("constexpr unsigned home_strip_art[][2]="+c([strip_hidden,strip_shown])+";\n")
        f.write("constexpr Rect seek_slider="+c(seek)+",seek_background="+c(rail)+";\n")
        f.write("constexpr unsigned seek_art[][2]="+c([empty,filled,wave,thumb])+";\n")
        for name,rect,bg,col,font,baseline,spacing,align in fields:
            f.write("constexpr TextArea "+name+"="+c((rect,*bg,col,font,baseline,spacing,align))+";\n")
        f.write("}\n")
    print("Kiosk text bank",len(bank),"bytes")


if __name__=="__main__":
    cfg,states,dest=map(Path,sys.argv[1:])
    capture(json.loads(cfg.read_bytes())["config"],json.loads(states.read_bytes()),dest)
