"""Capture text backgrounds, metrics and glyph masks from the Study kiosk."""
import io,json,sys,zlib
import copy
import numpy as np
from pathlib import Path
from PIL import Image,ImageChops
from render import fixture_page,rgb565
from control_art import box


def capture(config,states,dest,architectural_only=False,chromium_cdp=None):
    # Include the punctuation used by the HA player and the dashboard.
    chars="".join(chr(i) for i in range(32,127))+" °·éèëàáäöóñüß–—‘’“”…•←›✓✗▂▄▆█"
    bank=bytearray();offsets={};fonts={};fields=[]
    def put(data):
        if data not in offsets:offsets[data]=len(bank);bank.extend(data)
        return offsets[data],len(data)
    samples=copy.deepcopy(states)
    for state in samples:
        if state["entity_id"]==config["media"].get("default_speaker"):
            state["state"]="playing"
            attrs=state.setdefault("attributes",{})
            attrs.update(media_title="Track",media_artist="Artist");attrs.pop("entity_picture",None)
    library_fixture=[dict(title=f"Folder {i}",media_class="directory" if i%2==0 else "track",
                          can_expand=i%2==0,can_play=i%2!=0,media_content_id=str(i),media_content_type="music") for i in range(8)]
    with fixture_page(config,samples,library_fixture,chromium_cdp=chromium_cdp) as page:
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
        page.locator("#roomMedia .art").evaluate("e=>{const i=document.createElement('img');i.style.opacity='0';e.replaceChildren(i)}")
        mini_art=box(page,"#roomMedia .art")
        strip_cover=region(strip)
        field("home_cover_title","#rmTitle");field("home_cover_artist","#rmArtist")
        page.locator("#roomMedia").evaluate("e=>e.hidden=true")
        strip_hidden=region(strip)
        click('.nav [data-sheet="media"]')
        album_rect=box(page,"#mpArt")
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
        queue_open=box(page,"#icoMore");click("#icoMore")
        queue_back=box(page,"#ovQueue [data-ov-back]");queue_images=[]
        for mask in range(4):
            page.evaluate("""m=>{
              const q=document.querySelector('#queueList');q.replaceChildren();
              function row(id,now){const d=document.createElement('div');d.className='qrow'+(now?' now':'');
                const s=document.createElement('span');s.id=id;s.textContent='Example';s.style.flex='1';
                d.append(s);q.append(d);}
              if(m&1)row('captureQueueTrack',true);if(m&2)row('capturePlaylist',false);
              if(!(m&2)){const n=document.createElement('p');n.className='note';
                n.textContent=(m&1)?'This player doesn’t report a queue':'Nothing playing';q.append(n);}
            }""",mask)
            if mask==1:field("queue_track","#captureQueueTrack")
            if mask&2:field("queue_playlist_"+str(mask),"#capturePlaylist")
            page.locator("#queueList span").evaluate_all("es=>es.forEach(e=>e.style.visibility='hidden')")
            queue_images.append(Image.open(io.BytesIO(page.screenshot())).convert("RGB"))
        queue_frames=[];queue_rects=[]
        for i,pic in enumerate(queue_images):
            bounds=ImageChops.difference(queue_images[0],pic).getbbox() if i else (0,0,720,1280)
            if bounds is None:bounds=(0,0,1,1)
            x,y,r,b=bounds;queue_rects.append((x,y,r-x,b-y))
            queue_frames.append(put(zlib.compress(rgb565(pic.crop(bounds),x,y),9)))
        click("#ovQueue [data-ov-back]")
        speaker_button=box(page,"#icoSpk")
        click("#icoSpk")
        speaker_back=box(page,"#ovSpk [data-ov-back]")
        # A fixed chrome image, followed by scrollable device rows. Paint row
        # contents from live HA state using the kiosk's own pixels.
        card=page.locator("#ovSpk .ov-card")
        card.evaluate("e=>e.scrollTop=0")
        speaker_top=box(page,"#spkList")[1]
        speaker_end=box(page,".nav")[1]
        speaker_rows=[];speaker_rects=[];speaker_arrows=[]
        rows=page.locator("#spkList .dev")
        for i in range(rows.count()):
            row=rows.nth(i)
            scroll=card.evaluate("(e,i)=>{e.scrollTop=Math.max(0,e.querySelectorAll('.dev')[i].getBoundingClientRect().y+e.scrollTop-400);return e.scrollTop}",i)
            def row_box():
                b=row.bounding_box();return (int(b["x"]),round(b["y"]),round(b["width"]),round(b["height"]))
            variants=[]
            for sub in ("Current speaker","Unavailable","Control only · transfer unavailable",""):
                row.locator(".sub").evaluate("(e,t)=>e.textContent=t",sub)
                row.locator(".spk-transfer").evaluate("e=>e.disabled=true")
                x,y,w,h=row_box()
                variants.append((*region((x,y,w,h)),h))
            ax=box(page,f"#spkList .dev:nth-child({i+1}) .spk-transfer")[0]-x
            row.locator(".spk-transfer").evaluate("e=>e.disabled=false")
            speaker_arrows.append(region((x+ax,y,w-ax,h)))
            speaker_rows.append(variants);speaker_rects.append((x,w,ax))
        card.evaluate("e=>e.scrollTop=0")
        field("speaker_now","#spkNow")
        page.locator("#spkList").evaluate("e=>e.style.visibility='hidden'")
        speaker_base=region((0,0,720,1280))
        click("#ovSpk [data-ov-back]")
        browse_button=box(page,"#icoSearch");click("#icoSearch")
        browse_back=box(page,"#bBack");browse_switch=box(page,"#bView")
        field("library_title","#bTitle");field("library_crumb","#bCrumb")
        list_area=box(page,"#bList")
        lib_templates=[];lib_regions=[];lib_steps=[];lib_bases=[];note_icons=[];note_rects=[]
        for mode in range(2):
            if mode:click("#bView")
            items=page.locator("#bList .bitem")
            cols=2 if page.locator("#bList").evaluate("e=>e.classList.contains('tiles')") else 1
            tile_areas=[box(page,f"#bList .bitem:nth-child({i+1})") for i in range(3)]
            lib_steps.append((cols,tile_areas[cols][1]-tile_areas[0][1],tile_areas[1][0]-tile_areas[0][0]))
            for i in range(2):
                base=f"#bList .bitem:nth-child({i+1})"
                for suffix,selector in (("name",".n"),("type",".s")):
                    field(f"library_{suffix}_{mode}_{i}",base+" "+selector)
                if i==0:
                    folder_icon=items.nth(0).locator(".bthumb")
                    note=items.nth(1).locator(".bthumb").inner_html()
                    original=folder_icon.inner_html()
                    folder_icon.evaluate("(e,html)=>e.innerHTML=html",note)
                    icon_rect=box(page,base+" .bthumb")
                    note_icons.append(region(icon_rect));note_rects.append(icon_rect)
                    folder_icon.evaluate("(e,html)=>e.innerHTML=html",original)
                items.nth(i).locator(".bmeta").evaluate("e=>e.style.visibility='hidden'")
                lib_templates.append(region(tile_areas[i]));lib_regions.append(tile_areas[i])
            page.locator("#bList").evaluate("e=>e.style.visibility='hidden'")
            lib_bases.append(region((0,0,720,1280)))
            page.locator("#bList").evaluate("e=>e.style.visibility=''")
            page.locator("#bList .bmeta").evaluate_all("xs=>xs.forEach(e=>e.style.visibility='')")
        click("#bBack")
        click("#archMenu")
        field("menu_date","#archDate")
        click('#archRoomLinks [data-sheet="settings"]')
        mini_button=box(page,"#archMiniArt");reload_button=box(page,"#reload")
        field("mini_choice","#archMiniArt .v","right","right")
        wifi_button=box(page,"#wifiRow")
        field("wifi_choice","#wifiV","right","right")
        net_rows=[dict(ssid="Network",signal=80,secure=flag) for flag in (True,False)]
        page.route("**/wifi*",lambda route:route.fulfill(json={"status":{"available":True,"type":"ethernet"},"networks":net_rows}))
        click("#wifiRow")
        wifi_back=box(page,"#ovWifi [data-ov-back]")
        wifi_rows=[box(page,f"#wifiList .wnet:nth-child({i+1})") for i in range(2)]
        field("wifi_now","#wifiNow")
        wifi_list_art=[]
        for i in range(2):
            sel=f"#wifiList .wnet:nth-child({i+1})"
            page.locator(sel+" .s").evaluate("e=>{e.style.flex='1';e.textContent='Network'}")
            if not i:
                field("wifi_name",sel+" .s")
                field("wifi_signal",sel+" .g",alignment="right")
            page.locator(sel+" .s,"+sel+" .g").evaluate_all("els=>els.forEach(e=>e.style.visibility='hidden')")
            wifi_list_art.append(region(wifi_rows[i]))
        page.locator("#wifiList").evaluate("e=>e.style.visibility='hidden'")
        page.locator("#wifiNow").evaluate("e=>e.style.visibility='hidden'")
        wifi_empty=region((0,0,720,1280))
        page.locator("#wifiList,#wifiNow").evaluate_all("els=>els.forEach(e=>e.style.visibility='')")
        click("#wifiList .wnet:first-child")
        page.locator("#wifiJoinSsid").evaluate("e=>{e.style.flex='1';e.textContent='Network'}")
        page.locator("#wifiJoinMsg").evaluate("e=>e.textContent='Connecting…'")
        field("wifi_join_name","#wifiJoinSsid")
        field("wifi_message","#wifiJoinMsg")
        page.locator("#wifiPw").evaluate("e=>e.textContent='••••'")
        field("wifi_password","#wifiPw")
        wifi_cancel=box(page,"#wifiCancel");wifi_go=box(page,"#wifiGo")
        wifi_keys=[];wifi_keyboard=[]
        for shift in (False,True):
            if shift:click('#wifiKeys [data-k="__shift"]')
            wifi_keys.append(page.locator("#wifiKeys [data-k]").evaluate_all("els=>els.map(e=>{const b=e.getBoundingClientRect();return [e.dataset.k,[Math.floor(b.x),Math.floor(b.y),Math.ceil(b.right)-Math.floor(b.x),Math.ceil(b.bottom)-Math.floor(b.y)]]})"))
            page.locator("#wifiJoinSsid,#wifiJoinMsg,#wifiPw,#wifiNow").evaluate_all("els=>els.forEach(e=>e.style.color='transparent')")
            wifi_keyboard.append(region((0,0,720,1280)))
        click("#ovWifi [data-ov-back]")
        click('#archSettingsLinks [data-sheet="diagnostics"]')
        for name,sel in (("ha_status","#stHA"),("backlight_status","#stBL"),("net_status","#stNet"),("up_status","#sUp")):
            field(name,sel,"right","right")
        diagnostic_button=box(page,"#diagRow")
        if not page.locator("body").evaluate("e=>e.classList.contains('diag')"):click("#diagRow")
        diagnostic_on_button=box(page,"#diagRow");scroll_button=box(page,"#scrollTestRow")
        if architectural_only:
            page.locator("#scrollTestRow").evaluate("e=>e.style.visibility='hidden'")
        page.locator("#stGL").evaluate("e=>e.textContent='ESP32-P4 · MIPI DSI'")
        page.locator("#fps").evaluate("e=>e.textContent='55 fps'")
        field("diag_fps","#fps",subset="0123456789 fps?")
        field("diag_connection","#conn")
        page.locator("#conn").evaluate("e=>{e.className='bad';e.textContent='disconnected — retrying'}")
        field("diag_disconnected","#conn")
        page.locator("#conn,#fps").evaluate_all("els=>els.forEach(e=>e.style.visibility='hidden')")
        diagnostic_on=region((0,0,720,1280))
        for name,sel in (("diag_ha","#stHA"),("diag_backlight","#stBL"),("diag_net","#stNet"),("diag_uptime","#sUp")):
            field(name,sel,"right","right")
        if not architectural_only:
            click("#scrollTestRow")
            page.wait_for_function("document.querySelector('#bCrumb').textContent.includes('reopen')",timeout=35000)
            diagnostic_results=[]
            for mode in range(2):
                tiles=lib_steps[mode][0]>1
                page.locator("#bList").evaluate("(e,b)=>e.classList.toggle('tiles',b)",tiles)
                page.locator("#bList .bitem").evaluate_all("xs=>xs.forEach((e,i)=>{e.querySelector('.n').textContent='Case';e.querySelector('.s').textContent='00 fps · baseline'})")
                for i in range(6):
                    for kind in ("n","s"):field(f"diagnostic_result_{mode}_{i}_{kind}",f"#bList .bitem:nth-child({i+1}) .{kind}")
                page.locator("#bList .bmeta").evaluate_all("xs=>xs.forEach(el=>el.style.visibility='hidden')")
                bg_offset,bg_len=lib_bases[mode]
                baseline=zlib.decompress(bank[bg_offset:bg_offset+bg_len])
                current=rgb565(Image.open(io.BytesIO(page.screenshot())))
                diagnostic_results.append(put(zlib.compress(np.bitwise_xor(np.frombuffer(baseline,np.uint8),np.frombuffer(current,np.uint8)).tobytes(),9)))
                page.locator("#bList .bmeta").evaluate_all("xs=>xs.forEach(el=>el.style.visibility='')")
            click("#bBack")
        page.locator("#conn,#fps").evaluate_all("els=>els.forEach(e=>e.style.visibility='')")
        page.reload()
        page.wait_for_function("document.body.classList.contains('diag') && document.querySelector('#pDiag').textContent.includes('config v')")
        page.evaluate("document.fonts.ready")
        home_diag=page.locator("#pDiag")
        home_diag.evaluate("e=>e.textContent='touch: reports 5 points'")
        field("diag_home_line","#pDiag")
        diag_line_height=home_diag.evaluate("e=>parseFloat(getComputedStyle(e).lineHeight)")
        click("#archMenu");click('#archRoomLinks [data-sheet="settings"]');click('#archSettingsLinks [data-sheet="diagnostics"]')
        click("#diagRow")
        bell=config.get("doorbell") or {}
        page.evaluate("""([title,seconds])=>{
          document.querySelector('#doorbellPopup').hidden=false;
          document.querySelector('#doorbellTitle').textContent=title;
          document.querySelector('#doorbellLabel').textContent='DOORBELL TEST';
          document.querySelector('#doorbellState').textContent='Live camera';
          document.querySelector('#doorbellDuration').textContent='Closes automatically after '+seconds+' seconds · Muted';
        }""",[bell.get("title") or "Someone at the door",bell.get("duration_s",30)])
        viewport=box(page,"#doorbellVideo")
        header=(0,0,720,viewport[1])
        foot_y=viewport[1]+viewport[3]
        footer=(0,foot_y,720,1280-foot_y)
        video_bg=region(viewport);bell_head=[];bell_foot=[]
        for value in ("DOORBELL","DOORBELL TEST"):
            page.locator("#doorbellLabel").evaluate("(e,t)=>e.textContent=t",value)
            bell_head.append(region(header))
        for value in ("Connecting to live camera…","Live camera","Live camera unavailable"):
            page.locator("#doorbellState").evaluate("(e,t)=>e.textContent=t",value)
            if box(page,"#doorbellVideo")!=viewport:raise ValueError("Variable doorbell state height")
            bell_foot.append(region(footer))
    def c(v):return "{"+",".join(c(x) if isinstance(x,(list,tuple)) else str(x) for x in v)+"}"
    with (dest/"text_art.h").open("w",encoding="ascii") as f:
        f.write('#pragma once\n#include "study_assets.h"\nnamespace study {\n')
        f.write(f'constexpr size_t text_bytes={len(bank)};\nstatic uint8_t *text_art;\n#ifndef STUDY_EXTERNAL_TEXT\nstatic const uint8_t packed_text[]=\n')
        compressed=zlib.compress(bank,9)
        (dest/"text-art.bin").write_bytes(compressed)
        for o in range(0,len(compressed),256):f.write('"'+''.join(f'\\x{b:02x}' for b in compressed[o:o+256])+'"\n')
        f.write(';\n#endif\nstruct TextGlyph{uint16_t code,advance;int16_t x,y;uint16_t w,h;uint32_t offset,size;};\n')
        starts=[0];flat=[]
        for records in fonts.values():flat.extend(records);starts.append(len(flat))
        f.write("constexpr TextGlyph text_glyphs[]="+c(flat)+";\nconstexpr int text_starts[]="+c(starts)+";\n")
        f.write("struct TextArea{Rect rect;uint32_t bg,size;uint16_t colour;int font,baseline,spacing,align;};\n")
        f.write("constexpr Rect home_strip="+c(strip)+",home_play="+c(strip_play)+";\n")
        f.write("constexpr Rect album_rect="+c(album_rect)+",mini_album_rect="+c(mini_art)+";\n")
        f.write("constexpr Rect mini_button="+c(mini_button)+",reload_button="+c(reload_button)+";\n")
        f.write("constexpr unsigned home_strip_art[][2]="+c([strip_hidden,strip_shown,strip_cover])+";\n")
        f.write("constexpr Rect seek_slider="+c(seek)+",seek_background="+c(rail)+";\n")
        f.write("constexpr unsigned seek_art[][2]="+c([empty,filled,wave,thumb])+";\n")
        f.write("constexpr Rect queue_button="+c(queue_open)+",queue_back="+c(queue_back)+";\n")
        f.write("constexpr unsigned queue_pages[][2]="+c(queue_frames)+";\n")
        f.write("constexpr Rect queue_patches[]="+c(queue_rects)+";\n")
        f.write("constexpr Rect speaker_button="+c(speaker_button)+",speaker_back="+c(speaker_back)+";\n")
        f.write(f"constexpr int speaker_top={speaker_top},speaker_end={speaker_end};\n")
        f.write("constexpr unsigned speaker_base[]="+c(speaker_base)+";\n")
        f.write("constexpr unsigned speaker_rows[][4][3]="+c(speaker_rows or [[[0,0,0]]*4])+",speaker_rects[][3]="+c(speaker_rects or [[0,0,0]])+",speaker_arrows[][2]="+c(speaker_arrows or [[0,0]])+";\n")
        f.write("constexpr Rect bell_viewport="+c(viewport)+",bell_header="+c(header)+",bell_footer="+c(footer)+";\n")
        f.write("constexpr Rect diagnostic_button="+c(diagnostic_button)+",diagnostic_on_button="+c(diagnostic_on_button)+",scroll_button="+c(scroll_button)+";\n")
        f.write("constexpr unsigned diagnostic_on[]="+c(diagnostic_on)+";\n")
        f.write("constexpr Rect wifi_button="+c(wifi_button)+",wifi_back="+c(wifi_back)+",wifi_cancel="+c(wifi_cancel)+",wifi_go="+c(wifi_go)+";\n")
        f.write("constexpr Rect wifi_rows[]="+c(wifi_rows)+";\n")
        f.write("constexpr unsigned wifi_empty[]="+c(wifi_empty)+",wifi_row_art[][2]="+c(wifi_list_art)+",wifi_keyboard[][2]="+c(wifi_keyboard)+";\n")
        for mode,keys in enumerate(wifi_keys):
            f.write(f"constexpr Rect wifi_keys_{mode}[]="+c([r for key,r in keys])+";\n")
            f.write(f"constexpr const char *wifi_values_{mode}[]={{"+",".join(json.dumps(key) for key,r in keys)+"};\n")
        f.write(f"constexpr int diag_line_height_64={round(diag_line_height*64)};\n")
        f.write("constexpr unsigned bell_empty_video[]="+c(video_bg)+",bell_headers[][2]="+c(bell_head)+",bell_footers[][2]="+c(bell_foot)+";\n")
        for name,rect,bg,col,font,baseline,spacing,align in fields:
            f.write("constexpr TextArea "+name+"="+c((rect,*bg,col,font,baseline,spacing,align))+";\n")
        f.write("constexpr Rect browse_button="+c(browse_button)+",browse_back="+c(browse_back)+",browse_switch="+c(browse_switch)+",library_list="+c(list_area)+";\n")
        f.write("constexpr unsigned library_bases[][2]="+c(lib_bases)+",library_art[][2]="+c(lib_templates)+",library_steps[][3]="+c(lib_steps)+";\n")
        f.write("constexpr Rect library_note_rects[]="+c(note_rects)+";\n")
        f.write("constexpr unsigned library_notes[][2]="+c(note_icons)+";\n")
        if not architectural_only:
            f.write("constexpr unsigned diagnostic_results[][2]="+c(diagnostic_results)+";\n")
            for kind in ("n","s"):
                f.write("constexpr TextArea diagnostic_result_"+kind+"[][6]={"+",".join("{"+",".join(f"diagnostic_result_{m}_{i}_{kind}" for i in range(6))+"}" for m in range(2))+"};\n")
        f.write("constexpr Rect library_tiles[]="+c(lib_regions)+";\n")
        for kind in ("name","type"):
            f.write("constexpr TextArea library_"+kind+"[]={"+",".join(f"library_{kind}_{m}_{i}" for m in range(2) for i in range(2))+"};\n")
        f.write("}\n")
    print("Kiosk text bank",len(bank),"bytes")


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ("snapshot","states","dest"):parser.add_argument(arg,type=Path)
    parser.add_argument("--architectural-only",action="store_true")
    parser.add_argument("--chromium-cdp")
    args=parser.parse_args()
    capture(json.loads(args.snapshot.read_bytes())["config"],json.loads(args.states.read_bytes()),args.dest,args.architectural_only,args.chromium_cdp)
