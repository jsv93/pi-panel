"""Capture the actual kiosk controls for native, state-driven repainting."""
import io
import json
import math
import struct
from pathlib import Path
import sys
import zlib
import numpy as np

from PIL import Image
from render import fixture_page, rgb565
from advanced_art import capture_advanced
from control_palette import pack


def box(page, selector, width=None):
    b = page.locator(selector).bounding_box()
    x, y = math.floor(b["x"]), math.floor(b["y"])
    return (x, y, width or math.ceil(b["x"] + b["width"]) - x, math.ceil(b["y"] + b["height"]) - y)


def capture(config, states, dest):
    bank = bytearray()
    seen = {}
    backgrounds = {}
    tables = []

    def table(kind, name, rows):
        def c(value):
            if isinstance(value, (list, tuple)):
                return "{" + ",".join(map(c, value)) + "}"
            return str(value)
        tables.append("constexpr " + kind + " " + name + "=" + c(rows) + ";")

    def sprite(pic, rect):
        rect=tuple(rect)
        x, y, w, h = rect
        raw = rgb565(pic.crop((x, y, x+w, y+h)), x, y)
        data = zlib.compress(raw, 9)
        if data in seen:return (seen[data],len(data),w,h)
        if rect in backgrounds:
            base,offset,size=backgrounds[rect]
            changed=np.frombuffer(raw,"<u2").reshape(h,w)!=base
            ys,xs=np.nonzero(changed)
            if len(xs):
                x0,y0,x1,y1=int(xs.min()),int(ys.min()),int(xs.max())+1,int(ys.max())+1
                pixels=np.frombuffer(raw,"<u2").reshape(h,w)
                crop=zlib.compress(pixels[y0:y1,x0:x1].tobytes(),9)
                patch=struct.pack("<IIHHHH",offset,size,x0,y0,x1-x0,y1-y0)+crop
                if len(patch)<len(data)*.75:
                    key=(offset,patch)
                    if key not in seen:seen[key]=len(bank);bank.extend(patch)
                    return (seen[key],len(patch)|(1<<31),w,h)
        if data not in seen:
            seen[data] = len(bank)
            bank.extend(data)
        if rect not in backgrounds:
            backgrounds[rect]=np.frombuffer(raw,"<u2").reshape(h,w),seen[data],len(data)
        return (seen[data], len(data), w, h)

    def numeric_field(page, selector, width, main, unit, unit_text):
        el=page.locator(selector)
        original=el.evaluate("e=>[e.innerHTML,e.style.cssText]")
        rect=box(page,selector,width)
        x,y,w,h=rect
        style=el.evaluate("""(e,main)=>{const n=main?e.querySelector(main):e;
          return getComputedStyle(n).color.match(/\d+/g).slice(0,3).map(Number)}""",main)
        def set_char(text, suffix, mask=False):
            return el.evaluate("""(e,[main,unit,text,suffix,mask])=>{
                const n=main?e.querySelector(main):e;
                let node=[...n.childNodes].find(t=>t.nodeType===3);
                if(!node){node=document.createTextNode('');n.prepend(node);}
                node.data=text;
                const sup=unit?e.querySelector(unit):null;
                if(sup)sup.textContent=suffix;
                if(mask){
                  e.style.setProperty('background','black','important');
                  for(const s of [e,n,sup].filter(Boolean))s.style.setProperty('color','white','important');
                }
                const r=document.createRange();r.selectNodeContents(suffix&&sup?sup:node);
                return r.getBoundingClientRect().width;
            }""",[main,unit,text,suffix,mask])
        # Capture the untouched page background, separately from antialiased ink.
        el.evaluate("e=>e.style.visibility='hidden'")
        blank=sprite(Image.open(io.BytesIO(page.screenshot())),rect)
        el.evaluate("e=>e.style.visibility=''")
        # Extract coverage before opacity compositing onto the brown wallpaper.
        # The native renderer applies the thermostat's off opacity at paint time.
        el.evaluate("""e=>{for(let p=e;p;p=p.parentElement)if(getComputedStyle(p).opacity!=='1'){
          p.dataset.restoreOpacity=p.style.opacity;p.style.setProperty('opacity','1','important');
        }}""")
        glyphs=[]
        for char in '0123456789.-–@':
            suffix=unit_text if char=='@' and unit else ''
            text=(unit_text if not unit else '') if char=='@' else char
            advance=set_char(text,suffix,True)
            im=Image.open(io.BytesIO(page.screenshot())).convert("RGB")
            # Blacken the area beyond the actual element, which may shrink for a
            # single digit. Its siblings and the wallpaper are not glyph ink.
            b=el.bounding_box()
            patch=im.crop((x,y,min(x+w,math.ceil(b['x']+b['width'])),y+h))
            a=np.asarray(patch,dtype=np.int16)
            gray=np.where(a.max(axis=2)-a.min(axis=2)<=2,a[:,:,0],0).astype('uint8')
            ys,xs=np.nonzero(gray)
            if not len(xs):
                glyphs.append((0,0,0,0,0,0,round(advance*64)))
                continue
            left,top,right,bottom=int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)
            ink=zlib.compress(gray[top:bottom,left:right].tobytes(),9)
            offset=len(bank);bank.extend(ink)
            glyphs.append((offset,len(ink),left,top,right-left,bottom-top,round(advance*64)))
        r,g,b=style
        colour=(r>>3)<<11|(g>>2)<<5|b>>3
        el.evaluate("(e,[html,css])=>{e.innerHTML=html;e.style.cssText=css}",original)
        page.locator("[data-restore-opacity]").evaluate_all("""els=>els.forEach(p=>{
            p.style.opacity=p.dataset.restoreOpacity;delete p.dataset.restoreOpacity;
        })""")
        return rect,blank,colour,glyphs

    with fixture_page(config, states) as page:
        fields=[numeric_field(page,"#archTemp",160,None,None,"°")]
        page.locator('.nav [data-sheet="climate"]').evaluate("e=>e.click()")
        page.wait_for_timeout(350)
        for selector,width,main,unit,text in [("#cTemp",190,None,"sup","°"),("#cHum",180,None,"sup","%"),
                                              ("#archClimateTarget .sp-val",550,"#spTemp","sup","°C")]:
            fields.append(numeric_field(page,selector,width,main,unit,text))
        table("Rect","number_rects[]",[f[0] for f in fields])
        table("Sprite","number_backgrounds[]",[f[1] for f in fields])
        table("uint16_t","number_colours[]",[f[2] for f in fields])
        table("NumberGlyph","number_glyphs[][14]",[f[3] for f in fields])
        for name,sel in [("climate_down","#spDown"),("climate_up","#spUp"),("climate_slider","#archTargetSlider")]:
            table("Rect",name,box(page,sel))
        bar=box(page,"#archTargetSlider")
        scales,steppers=[],[]
        for active in [False,True]:
            page.locator("#archClimateTarget .setpoint").evaluate("(e,on)=>e.classList.toggle('off',!on)",active)
            pic=Image.open(io.BytesIO(page.screenshot()))
            steppers.append([sprite(pic,box(page,k)) for k in ("#spDown","#spUp")])
            scale=[]
            for level in range(101):
                page.locator("#archTargetSlider").evaluate("""(e,v)=>{
                    e.querySelector('.fill').style.transform='scaleX('+v/100+')';
                    e.querySelector('.knob').style.transform='translate(calc('+v/100*e.clientWidth+'px - 50%),-50%)';
                }""",level)
                scale.append(sprite(Image.open(io.BytesIO(page.screenshot())),bar))
            scales.append(scale)
        table("Sprite","climate_positions[][101]",scales)
        table("Sprite","climate_buttons[][2]",steppers)
        pages=json.loads((dest/"screens.json").read_text())["views"]
        table("int","climate_page",next(i for i,v in enumerate(pages) if v["name"]=="climate"))
        page.reload();page.locator("#archMenu").wait_for();page.evaluate("document.fonts.ready")
        page.locator('.nav [data-sheet="lights"]').evaluate("e=>e.click()")
        page.wait_for_timeout(350)
        n = len(config["lights"])
        values = [box(page, f"#archLightValue{i}", 105) for i in range(n)]
        powers = [box(page, f"#archLightPower{i}") for i in range(n)]
        group = box(page, "#archAllLights")
        table("Rect", "row_values[]", values)
        table("Rect", "row_powers[]", powers)
        table("Rect", "all_lights_button", group)
        levels, modes, group_modes = [], [], []
        for level in range(-1, 101):
            page.evaluate("""v=>{
                document.querySelectorAll('[id^=archLightValue]').forEach(e=>e.textContent=v<0?'–':v===0?'Off':v+'%');
                document.querySelectorAll('[id^=archLightPower]').forEach(e=>{
                    e.textContent=v<0?'–':v===0?'Off':'On';e.setAttribute('aria-pressed',String(v>0));
                });
                document.querySelector('#archAllLights').textContent=v<0?'–':v===0?'Turn all on':'Turn all off';
            }""", level)
            im = Image.open(io.BytesIO(page.screenshot()))
            levels.append([sprite(im, r) for r in values])
            if level < 2:
                modes.append([sprite(im, r) for r in powers])
                group_modes.append(sprite(im, group))
        table("Sprite", "row_labels[][light_count]", levels)
        table("Sprite", "row_modes[][light_count]", modes)
        table("Sprite", "group_modes[]", group_modes)
        page.locator('[data-arch-light="0"]').evaluate("e=>e.click()")
        page.wait_for_timeout(350)
        toggle = box(page, "#archLightToggle")
        table("Rect", "detail_power_button", toggle)
        labels = []
        for label in ["–", "Turn on", "Turn off"]:
            page.locator("#archLightToggle").evaluate("(e,v)=>e.textContent=v", label)
            labels.append(sprite(Image.open(io.BytesIO(page.screenshot())), toggle))
        table("Sprite", "detail_modes[]", labels)
        for selector in ("#archMenu",'#archRoomLinks [data-sheet=settings]',
                         '#archSettingsLinks [data-sheet=scene-edit]'):
            page.locator(selector).evaluate("e=>e.click()");page.wait_for_timeout(320)
        view_names=[v["name"] for v in pages]
        table("int","edit_page",view_names.index("scene-edit"))
        table("int","members_page",view_names.index("scene-members"))
        keys=["#saveSoftRow","#saveBrightRow"]
        saves=[box(page,k) for k in keys]
        table("Rect","save_buttons[]",saves)
        # Capture feedback at its actual right-aligned position inside each row.
        save_text=[(x+w-290,y,290,h) for x,y,w,h in saves]
        table("Rect","save_messages[]",save_text)
        variants=[]
        for message in ["Save","saving…","not saved","no lights"]+[f"saved {i} light"+("s" if i!=1 else "") for i in range(1,n+1)]:
            for k in keys:page.locator(k+" .v").evaluate("(e,s)=>e.textContent=s",message)
            im=Image.open(io.BytesIO(page.screenshot()))
            variants.append([sprite(im,rect) for rect in save_text])
        table("Sprite","save_feedback[][2]",variants)
        page.locator('#s-scene-edit [data-sheet=scene-members]').evaluate("e=>e.click()")
        page.wait_for_timeout(320)
        rows=[box(page,f"#archMembers button:nth-child({i+1})") for i in range(n)]
        table("Rect","member_buttons[]",rows)
        areas=[(x+w-190,y,190,h) for x,y,w,h in rows]
        table("Rect","member_status[]",areas)
        choices=[]
        for state in range(4):
            page.locator('#archMembers button').evaluate_all("""(rows,s)=>rows.forEach(row=>{
              row.querySelector('.chk').classList.toggle('on',Boolean(s%2));
              row.setAttribute('aria-pressed',String(Boolean(s%2)));
              row.querySelector('.v').textContent=s>=2?'not saved':'';
            })""",state)
            im=Image.open(io.BytesIO(page.screenshot()))
            choices.append([sprite(im,r) for r in areas])
        table("Sprite","membership_modes[][light_count]",choices)
        page.evaluate("""()=>{
          const overlay=document.querySelector('#idle');
          overlay.classList.add('on');overlay.classList.remove('blanked');
          document.body.classList.add('panel-idle');
          document.querySelector('#idleClock').textContent='00:00';
        }""")
        page.wait_for_timeout(550)
        def clock_boxes():
            return page.locator("#idleClock").evaluate("""e=>{
                const bounds=[];
                for(let i=0;i<5;i++){
                    const r=document.createRange();r.setStart(e.firstChild,i);r.setEnd(e.firstChild,i+1);
                    bounds.push(r.getBoundingClientRect());
                }
                return bounds.map((b,i)=>[Math.floor(b.x),Math.floor(b.y),
                    (i<4?Math.floor(bounds[i+1].x):Math.ceil(b.right))-Math.floor(b.x),
                    Math.ceil(b.bottom)-Math.floor(b.y)]);
            }""")
        slots=clock_boxes()
        table("Rect", "clock_slots[]", slots)
        glyphs=[]
        for ch in "0123456789-":
            page.locator("#idleClock").evaluate("(e,c)=>e.textContent=c+c+':'+c+c",ch)
            if ch!="-" and clock_boxes()!=slots:
                raise ValueError("Clock needs proportional layout for this theme")
            im=Image.open(io.BytesIO(page.screenshot()))
            glyphs.append([sprite(im,r) for r in slots])
        table("Sprite", "clock_glyphs[][5]", glyphs)
    display_config={**config,"display":{**config["display"],"adaptive_brightness":False}}
    with fixture_page(display_config,states) as page:
        for sel in ("#archMenu",'#archRoomLinks [data-sheet=settings]','#archSettingsLinks [data-sheet=display]'):
            page.locator(sel).evaluate("e=>e.click()")
            page.wait_for_timeout(320)
        table("int","display_page",view_names.index("display"))
        x,y,w,h=box(page,"#bl")
        table("Rect","backlight_slider",(x,y,w,h))
        rail=(x-16,y,w+32,h)
        table("Rect","backlight_rail",rail)
        x,y,w,h=box(page,"#blV")
        label=(x+w-116,y,116,h)
        table("Rect","backlight_value",label)
        variants=[]
        page.add_style_tag(content="#bl *{transition:none!important}")
        for level in range(101):
            page.locator("#bl").evaluate("""(e,v)=>{
              e.querySelector('.fill').style.transform='scaleX('+v/100+')';
              e.querySelector('.knob').style.transform='translate(calc('+v/100*e.clientWidth+'px - 50%),-50%)';
              document.querySelector('#blV').textContent=v+'%';
            }""",level)
            im=Image.open(io.BytesIO(page.screenshot()))
            variants.append([sprite(im,r) for r in (rail,label)])
        table("Sprite","backlight_modes[][2]",variants)
        page.locator('.nav [data-sheet=media]').evaluate("e=>e.click()")
        page.wait_for_timeout(350)
        selectors=["#shuf","#prev","#pp","#next","#rep"]
        bounds=[box(page,k) for k in selectors]
        table("Rect","transport_buttons[]",bounds)
        page.add_style_tag(content="#s-media button{transition:none!important}")
        for key,modes,name in [(0,2,"shuffle_modes"),(2,2,"play_modes"),(4,3,"repeat_modes")]:
            el=page.locator(selectors[key])
            images=[None]*modes
            for _ in range(modes):
                if key==2:state=int(el.get_attribute("aria-label")=="Pause")
                elif key==0:state=int(el.get_attribute("aria-pressed")=="true")
                else:state=["Repeat off","Repeat all","Repeat one"].index(el.get_attribute("aria-label"))
                images[state]=sprite(Image.open(io.BytesIO(page.screenshot())),bounds[key])
                el.evaluate("e=>e.click()")
            if any(img is None for img in images):
                raise ValueError(f"Missing {name} artwork; verify that the Study fixture has a speaker")
            table("Sprite",name+"[]",images)
        page.evaluate("document.querySelector('#doorbellPopup').hidden=false")
        page.wait_for_timeout(320)
        for selector,key,strings in (
            ("#doorbellState","bell_state",["Connecting to live camera…","Live camera","Live camera unavailable"]),
            ("#doorbellLabel","bell_label",["DOORBELL","DOORBELL TEST"]),
            ("#doorbellDuration","bell_duration",[f"Closes automatically after {config.get('doorbell',{}).get('duration_s',30)} seconds · Muted"])):
            areas=[]
            for label in strings:
                page.locator(selector).evaluate("(e,t)=>e.textContent=t",label)
                areas.append(box(page,selector))
            x=min(r[0] for r in areas);y=min(r[1] for r in areas)
            rect=(x,y,max(r[0]+r[2] for r in areas)-x,max(r[1]+r[3] for r in areas)-y)
            table("Rect",key+"_rect",rect)
            images=[]
            for label in strings:
                page.locator(selector).evaluate("(e,t)=>e.textContent=t",label)
                images.append(sprite(Image.open(io.BytesIO(page.screenshot())),rect))
            table("Sprite",key+"_art[]",images)
    capture_advanced(config,states,table,sprite,box)
    bank=pack(bank,tables)
    lines = ['#pragma once', '#include "study_assets.h"', 'namespace study {',
             'static const unsigned char control_art[]=']
    for off in range(0, len(bank), 256):
        lines.append('"' + "".join(f"\\x{x:02x}" for x in bank[off:off+256]) + '"')
    (dest / "control_art.h").write_text("\n".join(lines + [";", "struct NumberGlyph {unsigned pos,size;int x,y,w,h,advance;};", *tables, "}"]), encoding="ascii")
    print(f"Captured {n} light rows, 102 levels, {len(bank):,} bytes")


if __name__ == "__main__":
    config, states, dest = map(Path, sys.argv[1:])
    capture(json.loads(config.read_bytes())["config"], json.loads(states.read_bytes()), dest)
