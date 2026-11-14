"""Generate the test firmware config next to the local, private bench assets."""
import base64
import json
import os
from pathlib import Path
import re
import struct
import shutil
import sys
import esphome.components.mipi_dsi as mipi
from motion_regions import lamp_regions
from jpeg_motion import ensure, panel_jpeg, motion_sources, motion_image
from motion_chunks import emit as emit_chunks
import io
import numpy as np
import zlib
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
D = Path(sys.argv[1]).resolve()
ensure(D)
emit_chunks(D)
# Keep the installed ESPHome driver untouched. The trial needs access to
# three IDF-owned scanout buffers and the refresh counter.
driver=D/"bench_components/mipi_dsi"
shutil.copytree(Path(mipi.__file__).parent,driver,dirs_exist_ok=True,ignore=shutil.ignore_patterns("__pycache__"))
def amend(file,old_text,new_text):
    source=file.read_text(encoding="utf8")
    if source.count(old_text)!=1:raise ValueError(f"Unsupported ESPHome driver layout: {file.name}")
    file.write_text(source.replace(old_text,new_text),encoding="utf8")
amend(driver/"mipi_dsi.cpp",".num_fbs = 1",".num_fbs = 3")
amend(driver/"mipi_dsi.cpp",".on_color_trans_done = notify_refresh_ready,",
      ".on_color_trans_done = notify_refresh_ready,\n      .on_refresh_done = count_refresh,")
amend(driver/"mipi_dsi.h","class MipiDsi : public display::Display {\n public:",
      """class MipiDsi : public display::Display {
 public:
  esp_lcd_panel_handle_t native_panel() const {return handle_;}
  inline static volatile uint32_t refresh_epoch{};
  static bool IRAM_ATTR count_refresh(esp_lcd_panel_handle_t,esp_lcd_dpi_panel_event_data_t*,void*) {
    refresh_epoch=refresh_epoch+1;
    return false;
  }""")
old = (ROOT.parent/"panel-poc.yaml").read_text(encoding="utf8")
def section(name):
    return re.search(r"(?ms)^"+name+r":.*?(?=^[A-Za-z_][A-Za-z_0-9]*:|\Z)",old)[0].rstrip()

data=(D/"screens.bin").read_bytes()
m=json.loads((D/"screens.json").read_text())
names=[v["name"] for v in m["views"]]
def values(items):
    return "{"+",".join(str(a) for a in items)+"}"
def sprite(v):
    return values(v[k] for k in ("offset","size","w","h"))
def rect(v):
    return values(v[k] for k in ("x","y","width","height"))

# Store each ordinary sprite once. The three full scene captures are authoring
# references: only the buttons differ, and each can highlight independently.
packed=bytearray()
offsets={}
def pack(content,w,h):
    if content not in offsets:
        offsets[content]=len(packed)
        packed.extend(content)
    return dict(offset=offsets[content],size=len(content),w=w,h=h)
def pack_sprite(v):
    return pack(data[v["offset"]:v["offset"]+v["size"]],v["w"],v["h"])
pages=[pack_sprite(v) for v in m["views"]]
# The large percentage digits share identical vertical strips across levels.
# Store each strip once, keeping Chromium's RGB565 pixels exactly.
digit_strips=[]
digit_ids={}
def pack_digits(v):
    pixels=np.frombuffer(zlib.decompress(data[v["offset"]:v["offset"]+v["size"]]),"<u2").reshape(v["h"],v["w"])
    ids=[]
    for x in range(0,v["w"],16):
        tile=pixels[:,x:x+16]
        raw=zlib.compress(tile.tobytes(),9)
        if raw not in digit_ids:
            digit_ids[raw]=len(digit_strips)
            digit_strips.append(pack(raw,tile.shape[1],tile.shape[0]))
        ids.append(digit_ids[raw])
    entry=pack(struct.pack("<"+"H"*len(ids),*ids),v["w"],v["h"])
    entry["size"]|=1<<31
    return entry
patches=[[pack_digits(digits),pack_sprite(rail)] for digits,rail in m["patches"]]
scene_view=m["views"][names.index("scenes")]
def pixels(v):
    raw=zlib.decompress(data[v["offset"]:v["offset"]+v["size"]])
    return np.frombuffer(raw,dtype="<u2").reshape(v["h"],v["w"])
captures=[pixels(v) for v in m["scene_sprites"]]
scene_buttons=[]
scene_modes=[]
for i,name in enumerate(("soft","off","bright")):
    link=next(v for v in scene_view["links"] if v["to"]==name)
    x,y,w,h=(link[k] for k in ("x","y","w","h"))
    scene_buttons.append(values((x,y,w,h)))
    modes=[]
    for capture in (captures[(i+1)%3],captures[i]):
        modes.append(pack(zlib.compress(capture[y:y+h,x:x+w].tobytes(),9),w,h))
    scene_modes.append(modes)
for selected,reference in enumerate(captures):
    reconstructed=pixels(scene_view).copy()
    for i,mode in enumerate(scene_modes):
        l=next(l for l in scene_view["links"] if l["to"]==m["scene_sprites"][i]["name"])
        x,y,w,h=(l[k] for k in ("x","y","w","h"))
        s=mode[int(i==selected)]
        buf=zlib.decompress(packed[s["offset"]:s["offset"]+s["size"]])
        reconstructed[y:y+h,x:x+w]=np.frombuffer(buf,dtype="<u2").reshape(h,w)
    if not np.array_equal(reconstructed,reference):
        raise ValueError("Scene patches do not reproduce the captured screen")
with (D/"study_assets.h").open("w",encoding="ascii") as h:
    h.write("#pragma once\n#include <cstdint>\nnamespace study {\n")
    h.write(f"constexpr unsigned artwork_bytes={len(packed)};\nstatic uint8_t *artwork;\n")
    h.write("static const unsigned char packed_pages[] =\n")
    compressed=zlib.compress(packed,9)
    for start in range(0,len(compressed),256):
        h.write('"'+''.join('\\x%02x'%n for n in compressed[start:start+256])+'"\n')
    h.write(";\nstruct Sprite {unsigned offset,size; int w,h;};\n")
    h.write("constexpr Sprite digit_strips[]={"+",".join(map(sprite,digit_strips))+"};\n")
    h.write("struct Rect {int x,y,w,h; bool contains(int a,int b) const {return a>=x&&a<x+w&&b>=y&&b<y+h;}};\n")
    h.write("struct Link {int page; Rect area; int dest; bool root;};\n")
    regions=lamp_regions(m,data)
    h.write("struct Span {uint16_t x,y,w;};\nconstexpr Span lamp_spans[] = {"+",".join(values(r) for r in regions)+"};\n")
    h.write(f"constexpr unsigned lamp_stride={sum(r[2] for r in regions)};\n")
    h.write("constexpr int lamp_clip[]={"+",".join(str(min([l["y"] for l in m["views"][names.index(n)]["links"] if l["root"]]+[1280])) for n in ("light0","lights"))+"};\n")
    h.write("constexpr Sprite pages[] = {"+",".join(map(sprite,pages))+"};\n")
    h.write("constexpr Link links[] = {\n")
    for i,v in enumerate(m["views"]):
        for l in v["links"]:
            target=l["to"]
            commands={"back":-1,"up":-3,"down":-4,"toggle":-5,"soft":-6,"off":-7,"bright":-8}
            if target in commands or target in names:
                dest=commands[target] if target in commands else names.index(target)
                h.write(values((i,values(l[k] for k in ("x","y","w","h")),dest,int(l["root"])))+",\n")
    h.write("};\nconstexpr Sprite patches[][2] = {"+",".join(values(map(sprite,pair)) for pair in patches)+"};\n")
    for name in ("reading","slider"):
        h.write("constexpr Rect "+name+"="+rect(m[name])+";\n")
    h.write("constexpr Rect slider_paint="+rect(m.get("slider_paint",m["slider"]))+";\n")
    for name in ("home","idle","doorbell","scenes","lights","media","light0"):
        h.write(f"constexpr int {name}={names.index(name)};\n")
    for key in ("room-menu","diagnostics","settings"):
        h.write(f"constexpr int {key.replace('-','_')}_page={names.index(key)};\n")
    h.write("constexpr int light_count="+str(sum(bool(re.fullmatch(r"light\d+",n)) for n in names))+";\n")
    h.write("constexpr int initial[]="+values(m["initial"])+";\n")
    h.write("constexpr int presets[][light_count]="+values(values(p) for p in m["presets"])+";\n")
    h.write("constexpr Rect preset_buttons[]="+values(scene_buttons)+";\n")
    h.write("constexpr Sprite preset_modes[][2]="+values(values(map(sprite,p)) for p in scene_modes)+";\n")
    h.write("constexpr int video_y="+str(round(m["video"]["y"]+(m["video"]["height"]-400)/2))+";\n}\n")
    pattern=Image.new("RGB",(640,400),"black")
    painter=ImageDraw.Draw(pattern)
    for n,c in enumerate(("white","yellow","cyan","green","magenta","red","blue","black")):
        painter.rectangle((80*n,0,80*n+79,399),fill=c)
    shadows=(0,8,16,24,32,48,80,128)
    for n,value in enumerate(shadows):
        painter.rectangle((80*n,240,80*n+79,399),fill=(value,)*3)
    photo=io.BytesIO();pattern.save(photo,"JPEG",quality=85)
    bars=[pattern.getpixel((80*n+40,200)) for n in range(8)]
    h.write("namespace study {constexpr uint16_t test_colors[]="+values(
        ((r>>3)<<11)|((g>>2)<<5)|(b>>3) for r,g,b in bars)+";}\n")
    for name,encoded in (("legacy_test_frame",photo.getvalue()),("test_frame",panel_jpeg(pattern,quality=85))):
        h.write('namespace study {constexpr char '+name+'[]="'+base64.b64encode(encoded).decode()+'";}\n')
    h.write("namespace study {constexpr int shadow_levels[]="+values(shadows)+";}\n")
    _,_,_,routes=json.loads((D/"jpeg_meta.json").read_text())
    route=next(i for i,(a,b,t,_) in enumerate(routes) if a==names.index("home") and b==names.index("lights") and t==14)
    phase=3
    a,b,travel,_=routes[route]
    clip=min([l["y"] for l in m["views"][b]["links"] if l["root"]]+[1280])
    sources=motion_sources(D,m["views"])
    sample=motion_image(sources[a],sources[b],phase,travel,clip)
    refs=[]
    for y in range(31,1280,157):
        for x in range(23,720,107):
            r,g,b=sample.getpixel((x,y))
            refs.append(values((x,y,((r>>3)<<11)|((g>>2)<<5)|(b>>3))))
    h.write("namespace study {struct ColorSample {int x,y;uint16_t pixel;};")
    h.write(f"constexpr int probe_route={route},probe_phase={phase};\n")
    h.write("constexpr ColorSample frame_colors[]={"+",".join(refs)+"};}\n")
shutil.copyfile(ROOT/"study.h",D/"study.h")
shutil.copyfile(ROOT/"scanout.h",D/"scanout.h")
shutil.copyfile(ROOT/"navigation.h",D/"navigation.h")
secret=D/"bench.key"
if not secret.exists():
    secret.write_text(base64.b64encode(os.urandom(32)).decode(),encoding="ascii")
base=section("esphome").replace("name: panel-poc","name: p4-study-bench").replace("friendly_name: Wall Panel PoC","friendly_name: Study P4 Bench\n  includes: [scanout.h, navigation_assets.h, motion_chunks.h, study_assets.h, study.h, navigation.h]")
base=base.replace("id(backlight_ctrl).write_byte(0x95, 0x11);","""if (!id(backlight_ctrl).write_byte(0x95, 0x11)) {
            id(panel_display).mark_failed();
            id(panel_touch).mark_failed();
            ESP_LOGI("study","Display controller absent; USB bench mode");
            return;
          }""")
base+="\n    - priority: 400\n      then:\n        - lambda: 'study::begin(id(panel_display).is_failed() ? nullptr : id(panel_display)); study::headless_test();'\n"
# The original on_boot is a single mapping. Convert it into the first list entry.
start=base.index("    priority: 800")
stop=base.index("    - priority: 400")
base=base[:start]+"    - priority: 800\n"+"\n".join("  "+s for s in base[start:stop].splitlines()[1:])+"\n"+base[stop:]
# The P4 ROM inflater uses ~11 KB of stack before application call frames.
esp=section("esp32").replace("    advanced:","    advanced:\n      loop_task_stack_size: 24576\n      include_builtin_idf_components: [esp_driver_jpeg, esp_driver_ppa]")
esp=esp.replace("  variant:","  partitions: study-partitions.csv\n  variant:")
(D/"study-partitions.csv").write_text(
    "otadata,data,ota,0x9000,0x2000\nphy_init,data,phy,0xb000,0x1000\n"
    "app0,app,ota_0,0x10000,0x300000\napp1,app,ota_1,0x310000,0x300000\n"
    "motion,data,0x40,0x610000,0x1980000\nnvs,data,nvs,0x1f90000,0x70000\n")
touch=section("touchscreen")+"\n    update_interval: 8ms\n"+"""
    on_update:
      - lambda: |-
          for (const auto &p : touches) {
            if (p.state == 1 || p.state == 2) { study::touch(p.x,p.y); break; }
          }
    on_release:
      - lambda: 'study::release();'
"""
api="""
api:
  batch_delay: 0ms
  reboot_timeout: 0s
  encryption:
    key: KEY
  actions:
    - action: navigation_demo
      then:
        - api.respond:
            success: !lambda 'return study::start_navigation_demo();'
    - action: lamp_demo
      then:
        - api.respond:
            success: !lambda 'return study::start_demo();'
    - action: ring
      then:
        - lambda: 'study::ring();'
        - api.respond:
    - action: frame
      variables:
        jpeg: string
      then:
        - api.respond:
            success: !lambda 'return study::frame(jpeg);'
    - action: close
      then:
        - lambda: 'study::close_ring();'
        - api.respond:
interval:
  - interval: 2ms
    then:
      - lambda: 'study::animate();'
  - interval: 200ms
    then:
      - lambda: 'study::tick();'
""".replace("KEY",secret.read_text().strip())
local_driver="external_components:\n  - source: {type: local, path: bench_components}\n    components: [mipi_dsi]"
(D/"study.yaml").write_text("\n\n".join((local_driver,base,esp,section("logger"),section("ethernet"),section("psram"),section("esp_ldo"),section("i2c"),section("i2c_device"),section("display")+"\n    update_interval: never",touch,api)),encoding="utf8")
