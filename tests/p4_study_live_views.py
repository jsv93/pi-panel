"""Generate a read-only touch replay using the real ESPHome state subscriptions."""
from collections import deque
from pathlib import Path
import json
import re
import shutil
import sys


def generate(build):
    qa=build/"qa_runtime";dest=build/"capture_runtime"
    shutil.copytree(qa,dest,dirs_exist_ok=True)
    for p in dest.glob("*.h"):
        p.write_text(p.read_text().replace("#define STUDY_BENCH_TEST","#define STUDY_LIVE_CAPTURE"))
    if '"panel-qa-cache"' not in (dest/"config_store.h").read_text():
        raise ValueError("A separate test fleet cache is required")
    for name in ("study","navigation"):
        h=(build/f"qa_{name}.h").read_text().replace("qa_runtime/","capture_runtime/").replace("qa_navigation.h","capture_navigation.h")
        (build/f"capture_{name}.h").write_text(h)
    views=json.loads((build/"screens.json").read_text())["views"]
    names=[v["name"] for v in views];paths={"home":[]};queue=deque(["home"])
    while queue:
        name=queue.popleft()
        for link in views[names.index(name)]["links"]:
            target=link["to"]
            if target not in names or target in paths:continue
            paths[target]=paths[name]+[(link["x"]+link["w"]//2,link["y"]+link["h"]//2)]
            queue.append(target)
    steps=[];labels=[]
    def capture(name):
        labels.append(name);steps.append(f'snapshot("{name}");')
    for i,view in enumerate(views):
        name=view["name"]
        steps.append("depth=0;blanked=false;last_activity=clock_ms();show(home,0);")
        if name=="doorbell":
            steps+=["camera_ring(true);","if(bell_frames<3){if(clock_ms()-last_activity<18000){--step;return;}ESP_LOGE(\"study\",\"LIVE_WRONG_SCREEN no camera frames\");return;}"]
        else:
            for x,y in paths[name]:steps.append(f"tap({x},{y});")
        steps.append(f'if(current!={i}){{ESP_LOGE("study","LIVE_WRONG_SCREEN {name}");return;}}')
        capture(name)
        if name=="diagnostics":
            steps.append("tap_box(diagnostics_enabled?diagnostic_on_button:diagnostic_button);")
            steps.append("if(!diagnostics_enabled)tap_box(diagnostic_button);")
            capture("diagnostics-on")
            steps.append("tap_box(scroll_button);")
            steps.append('if(diagnostic_pass>=0 && diagnostic_pass<6){--step;return;}if(diagnostic_pass!=6)ESP_LOGE("study","LIVE_WRONG_SCREEN diagnostics scroll");')
            capture("diagnostics-scroll")
            steps.append("tap_box(browse_back);")
            steps.append("tap_box(diagnostic_on_button);")
        if re.fullmatch(r"light\d+",name):
            light=int(name[5:]);steps.append("tap_box(more_open);");capture("more"+str(light))
            if light==2:
                steps.append("tap_box(colour_open[2]);");capture("colour");steps.append("tap_box(colour_back[2]);")
            steps.append(f"tap_box(more_back[{light}]);")
        if name=="media":
            steps.append("tap_box(speaker_button);")
            capture("speakers")
            steps.append("if(speaker_count>1){tap(speaker_rects[1][0]+30,speaker_top+speaker_rows[0][speaker_variant(0)][2]+35);}")
            steps.append('if(speaker_count>1 && selected_speaker!=1)ESP_LOGE("study","LIVE_WRONG_SCREEN speaker selection");')
            steps.append("if(speaker_count>1){tap_box(speaker_button);tap(speaker_rects[0][0]+30,speaker_top+35);}else tap_box(speaker_back);")
            steps.append('if(selected_speaker!=0 || speakers_open)ESP_LOGE("study","LIVE_WRONG_SCREEN speaker return");')
            steps.append("tap_box(browse_button);")
            steps.append('if(library.waiting){--step;return;}if(library.items.empty())ESP_LOGE("study","LIVE_WRONG_SCREEN library unavailable");')
            capture("library")
            steps.append("tap_box(browse_switch);")
            capture("library-alternate")
            steps.append("tap_box(browse_switch);tap(library_list.x+32,library_list.y+32);")
            steps.append('if(library.waiting){--step;return;}if(library.folders.empty())ESP_LOGE("study","LIVE_WRONG_SCREEN library folder");')
            steps.append('static int64_t entered=0;if(!entered)entered=clock_ms();if(clock_ms()-entered<3000){--step;return;}')
            capture("library-folder")
            steps.append("tap_box(browse_back);")
            steps.append("if(library.waiting){--step;return;}tap_box(browse_back);")
            steps.append("tap_box(volume_button);");capture("volume");steps.append("tap_box(volume_close);")
            steps.append("tap_box(queue_button);");capture("queue");steps.append("tap_box(queue_back);")
    steps.append('close_ring();depth=0;show(home,0);ESP_LOGI("study","LIVE_VIEWS_DONE");')
    header=r'''#pragma once
#include "esp_rom_crc.h"
namespace study {
static int capturing_index=-1;
static const char *capture_name;
static size_t compressed_size,position;
static uint32_t capture_crc;
// RGB565 runs and literal spans avoid a deflater heap on the microcontroller.
static size_t pack_capture(const uint16_t *src){
  auto *dst=reinterpret_cast<uint16_t*>(previous_pixels);
  const size_t count=page_bytes/2;
  size_t in=0,out=0;
  while(in<count){
    const size_t first=in++;
    while(in<count && src[in]==src[first] && in-first<32768)++in;
    if(in-first>=3){
      if(out+2>=count)return 0;
      dst[out++]=0x8000|(in-first-1);dst[out++]=src[first];
    }else{
      while(in<count && in-first<32768){
        if(in+2<count && src[in]==src[in+1] && src[in]==src[in+2])break;
        ++in;
      }
      if(out+1+in-first>=count)return 0;
      dst[out++]=in-first-1;memcpy(dst+out,src+first,2*(in-first));out+=in-first;
    }
  }
  return 2*out;
}
static void snapshot(const char *name){
  if(!previous_pixels || !page_pixels)return;
  capture_name=name;capture_crc=esp_rom_crc32_le(0,page_pixels,page_bytes);
  if(!unpack(pages[current],scratch)){ESP_LOGE("study","LIVE_COMPRESS_FAIL %s",name);return;}
  auto *delta=reinterpret_cast<uint16_t*>(scratch);
  const auto *pixels=reinterpret_cast<const uint16_t*>(page_pixels);
  for(size_t i=0;i<page_bytes/2;i++)delta[i]^=pixels[i];
  compressed_size=pack_capture(delta);
  if(!compressed_size || compressed_size==page_bytes){memcpy(previous_pixels,page_pixels,page_bytes);compressed_size=page_bytes;}
  position=0;capturing_index=1;
  ESP_LOGI("study","LIVE_BEGIN %s %u %08x %s %d",name,unsigned(compressed_size),capture_crc,compressed_size==page_bytes?"raw":"delta",current);
}
static void capture_chunk(){
  for(int lines=0;lines<4 && position<compressed_size;lines++){
    unsigned char encoded[200];size_t n=0,chunk=std::min<size_t>(144,compressed_size-position);
    if(mbedtls_base64_encode(encoded,sizeof(encoded),&n,previous_pixels+position,chunk)!=0)return;
    ESP_LOGI("study","LIVE_PIX %u %.*s",unsigned(position),int(n),encoded);position+=chunk;
  }
  if(position==compressed_size){ESP_LOGI("study","LIVE_END %s",capture_name);capturing_index=-1;}
}
static void tap(int x,int y){touch(x,y);release();}
static void tap_box(const Rect &r){tap(r.x+r.w/2,r.y+r.h/2);}
static void bench_step(){
  static unsigned step=0;
  if(clock_ms()<16000 || !ha_lights.receiving() || moving || down || !page_pixels)return;
  switch(step++){
'''
    header+='\n'.join(f"case {i}: {{{s}}}break;" for i,s in enumerate(steps))+"\ndefault:return;}\n}\n}\n"
    (build/"live_views.h").write_text(header)
    (build/"live_views.json").write_text(json.dumps(labels))
    yaml=(build/"study-qa.yaml").read_text().replace("qa_runtime","capture_runtime").replace("qa_study.h","capture_study.h").replace("qa_navigation.h","capture_navigation.h").replace("bench_touch.h","live_views.h")
    yaml=yaml.replace("logger:\n", "logger:\n  baud_rate: 1500000\n")
    (build/"study-views.yaml").write_text(yaml)
    print("Live screen capture routes",len(labels))


if __name__=="__main__":generate(Path(sys.argv[1]))
