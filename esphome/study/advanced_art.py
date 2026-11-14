"""Capture the Study light detail sheets and their native interaction geometry."""
import io
import json
from PIL import Image
from render import fixture_page


def capture_advanced(config,states,table,sprite,box,*,chromium_cdp=None):
    pages=[];backs=[];members=[];member_modes=[];selectors=[];effects=[];keys=[];starts=[0]
    popups=[];rows=[];menu_rects=[];ct_hit=[];ct_paint=[];ct_labels=[];temperatures=[]
    colours=[];colour_pages=[];colour_backs=[];swatches=[];swatch_highlights=[]
    hues=[];hue_paint=[];hue_labels=[];hue_levels=[]
    blank=(0,0,0,0);empty=(0,0,0,0)
    state={s["entity_id"]:s.get("attributes",{}) for s in states}
    with fixture_page(config,states,chromium_cdp=chromium_cdp) as page:
        def click(s):
            page.locator(s).first.evaluate("e=>e.click()");page.wait_for_timeout(320)
        def snap():
            return Image.open(io.BytesIO(page.screenshot()))
        def slider(selector,label,values,fmt):
            hit=box(page,selector);x,y,w,h=hit
            rail=(x-14,y,w+28,h)
            x,y,w,h=box(page,label);number=(x+w-126,y,126,h)
            modes=[]
            for pct,value in enumerate(values):
                page.locator(selector).evaluate("""(e,v)=>{
                  e.querySelector('.fill').style.transform='scaleX('+v/100+')';
                  e.querySelector('.knob').style.transform='translate(calc('+v/100*e.clientWidth+'px - 50%),-50%)';
                }""",pct)
                page.locator(label).evaluate("(e,s)=>e.textContent=s",fmt(value))
                frame=snap();modes.append([sprite(frame,r) for r in (rail,number)])
            return hit,rail,number,modes
        for index,l in enumerate(config["lights"]):
            click('.nav [data-sheet="lights"]');click(f'[data-arch-light="{index}"]')
            if not index:table("Rect","more_open",box(page,"#archLightMore"))
            click("#archLightMore")
            frame=snap();pages.append(sprite(frame,(0,0,720,1280)))
            backs.append(box(page,"#ovLight [data-ov-back]"))
            member="#lightBody .act:has(.chk)"
            mr=box(page,member);members.append(mr)
            variants=[]
            for on,failed in ((False,False),(True,False),(False,True),(True,True)):
                page.locator(member).evaluate("""(e,[on,fail])=>{
                  e.querySelector('.chk').classList.toggle('on',on);
                  e.querySelector('.v').textContent=fail?'not saved':'';
                }""",[on,failed])
                page.wait_for_timeout(250)
                variants.append(sprite(snap(),mr))
            member_modes.append(variants)
            # Kiosk standard select, with its option labels rendered by Chromium.
            sel=page.locator("#archEffect")
            if sel.count():
                hit=box(page,"#archEffect");selectors.append(hit)
                options=sel.locator("option").evaluate_all("es=>es.map(e=>[e.value,e.textContent])")
                for value,_ in options:
                    sel.evaluate("(e,s)=>e.value=s",value);effects.append(sprite(snap(),hit));keys.append(json.dumps(value))
                page.evaluate("""names=>{
                  let el=document.querySelector('#archEffect'),r=el.getBoundingClientRect(),p=document.createElement('div');
                  p.id='p4EffectOptions';Object.assign(p.style,{position:'fixed',left:r.x+'px',width:r.width+'px',
                    top:Math.min(r.bottom,innerHeight-names.length*42-8)+'px',zIndex:99999,background:'#fff',color:'#111',
                    font:getComputedStyle(el).font,border:'1px solid #666',boxSizing:'border-box'});
                  for(const n of names){const o=document.createElement('div');o.textContent=n;
                    Object.assign(o.style,{height:'42px',lineHeight:'42px',paddingLeft:'12px'});p.append(o);}document.body.append(p);
                }""",[o[1] for o in options])
                rect=box(page,"#p4EffectOptions");menu_rects.append(rect);popups.append(sprite(snap(),rect))
                rows.extend(box(page,f"#p4EffectOptions>div:nth-child({j+1})") for j in range(len(options)))
                page.locator("#p4EffectOptions").evaluate("e=>e.remove()")
            else:selectors.append(blank);menu_rects.append(blank);popups.append(empty)
            starts.append(len(keys))
            ct=page.locator("#ctSlider")
            if ct.count():
                a=state[l["entity_id"]];lo=a.get("min_color_temp_kelvin") or 2000;hi=a.get("max_color_temp_kelvin") or 6500
                hit,rail,number,levels=slider("#ctSlider","#ctV",[int(lo+(hi-lo)*p/100+.5) for p in range(101)],lambda k:f"{k}K")
            else:hit=rail=number=blank;levels=[[empty,empty]]*101
            ct_hit.append(hit);ct_paint.append(rail);ct_labels.append(number);temperatures.append(levels)
            button='#lightBody button:has-text("Colour")'
            if page.locator(button).count():
                colours.append(box(page,button));click(button)
                colour_pages.append(sprite(snap(),(0,0,720,1280)));colour_backs.append(box(page,"#ovColour [data-ov-back]"))
                options=page.locator("#archColourSwatches .sw")
                centres=[box(page,f"#archColourSwatches .sw:nth-child({j+1})") for j in range(options.count())]
                swatches.append(centres)
                variants=[]
                for on in (False,True):
                    options.evaluate_all("(els,on)=>els.forEach(e=>e.classList.toggle('on',on))",on)
                    frame=snap();variants.append([sprite(frame,r) for r in centres])
                swatch_highlights.append(variants)
                hit,rail,number,levels=slider("#archHue","#archHueValue",[int(p*3.6+.5) for p in range(101)],lambda v:f"{v}°")
                click("#ovColour [data-ov-back]")
            else:
                colours.append(blank);colour_pages.append(empty);colour_backs.append(blank)
                swatches.append([blank]*12);swatch_highlights.append([[empty]*12,[empty]*12])
                hit=rail=number=blank;levels=[[empty,empty]]*101
            hues.append(hit);hue_paint.append(rail);hue_labels.append(number);hue_levels.append(levels)
            click("#ovLight [data-ov-back]")
    for name,values in (("more_back",backs),("more_member",members),("effect_open",selectors),("effect_menus",menu_rects),
                        ("warmth_slider",ct_hit),("warmth_rail",ct_paint),("warmth_label",ct_labels),
                        ("colour_open",colours),("colour_back",colour_backs),("hue_slider",hues),("hue_rail",hue_paint),("hue_label",hue_labels)):
        table("Rect",name+"[]",values)
    table("Rect","effect_rows[]",rows or [blank]);table("Rect","colour_swatches[][12]",swatches)
    for name,values in (("more_pages[]",pages),("more_checks[][4]",member_modes),("effect_selected[]",effects or [empty]),
                        ("effect_menu_art[]",popups),("warmth_modes[][101][2]",temperatures),("colour_sheets[]",colour_pages),
                        ("swatch_modes[][2][12]",swatch_highlights),("hue_modes[][101][2]",hue_levels)):
        table("Sprite",name,values)
    table("const char *","effect_names[]",keys or ['""']);table("int","effect_starts[]",starts)
