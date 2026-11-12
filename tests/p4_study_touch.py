"""Generate a USB-bench-only touch replay from the CM5 kiosk hit rectangles.

The test firmware uses light fixtures and an unreachable fleet endpoint. No
room action is forwarded. Keep the generated header and YAML outside the repo.
"""
import argparse
from collections import deque
import json
from pathlib import Path
import shutil
import zlib


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build",type=Path)
    parser.add_argument("--capture",action="store_true",help="Export lossless framebuffer changes over USB at each resting screen")
    parser.add_argument("--fixture-identity",type=Path,help="Separate disposable server enrollment for online write tests")
    args=parser.parse_args()
    build=args.build
    views=json.loads((build/"screens.json").read_text())["views"]
    art=(build/"screens.bin").read_bytes()
    names=[v["name"] for v in views]
    paths={"home":[]}
    queue=deque(["home"])
    while queue:
        name=queue.popleft()
        for link in views[names.index(name)]["links"]:
            target=link["to"]
            if target not in names or target in paths:continue
            paths[target]=[*paths[name],(link["x"]+link["w"]//2,link["y"]+link["h"]//2,target)]
            queue.append(target)
    steps=[]
    def step(code):
        steps.append("case "+str(len(steps))+": {"+code+"}break;")
    for index,view in enumerate(views):
        name=view["name"]
        step("depth=0;blanked=false;show(home,0);")
        if name=="doorbell":
            step("ring();")
        else:
            for x,y,target in paths[name]:
                step(f"tap({x},{y});")
        expected=zlib.crc32(zlib.decompress(art[view["offset"]:view["offset"]+view["size"]]))
        step(f'ESP_LOGI("study","QA_VIEW {name} page=%d expected={index} crc=%08x artwork={expected:08x}",current,esp_rom_crc32_le(0,page_pixels,page_bytes));')
        if args.capture:step(f'capture_view({index});')
    step('show(lights,0); depth=0;')
    step('tap_rect(row_powers[0]);')
    step('check("row off",ha_lights.confirmed(0)==0 && ha_lights.confirmed(1)==28);')
    step('tap_rect(row_powers[0]);')
    step('check("row restored",ha_lights.confirmed(0)==17);')
    step('tap_rect(all_lights_button);')
    step('check("group off",ha_lights.confirmed(0)==0 && ha_lights.confirmed(1)==0 && ha_lights.confirmed(2)==0);')
    step('tap_rect(all_lights_button);')
    step('check("group restored",ha_lights.confirmed(0)==17 && ha_lights.confirmed(1)==28 && ha_lights.confirmed(2)==39);')
    step('show(light0,0);tap_rect(detail_power_button);')
    step('check("detail off",ha_lights.confirmed(0)==0);')
    step('tap_rect(detail_power_button);')
    step('check("detail restored",ha_lights.confirmed(0)==17);')
    for light,original in enumerate((17,28,39)):
        step(f'show(light0+{light},0);touch(slider.x+slider.w/4,slider.y+slider.h/2);touch(slider.x+slider.w*3/4,slider.y+slider.h/2);release();check("light {light+1} brightness drag",std::abs(ha_lights.confirmed({light})-75)<=1);')
        step(f'tap_rect(detail_power_button);check("light {light+1} detail off",ha_lights.confirmed({light})==0);ha_lights.request({light},{original});')
    for i in range(3):
        step(f'show(light0+{i},0);tap_rect(more_open);check("light {i+1} More",light_sheet==LightSheet::more);')
        step(f'if(effect_open[{i}].w){{tap_rect(effect_open[{i}]);check("light {i+1} effect menu",light_sheet==LightSheet::effects);int effect=effect_starts[{i}+1]-1;tap_rect(effect_rows[effect]);check("light {i+1} effect selection",light_sheet==LightSheet::more && ha_lights.detail({i}).effect==effect_names[effect]);}}')
        step(f'if(warmth_slider[{i}].w){{tap_rect(warmth_slider[{i}]);const auto &d=ha_lights.detail({i});check("light {i+1} warmth",d.kelvin==(d.minimum+d.maximum)/2);}}')
        step(f'if(colour_open[{i}].w){{tap_rect(colour_open[{i}]);tap_rect(colour_swatches[{i}][5]);check("light {i+1} swatch",ha_lights.detail({i}).hue==180);tap_rect(hue_slider[{i}]);check("light {i+1} hue",ha_lights.detail({i}).hue==180);tap_rect(colour_back[{i}]);}}')
        step(f'tap_rect(more_back[{i}]);check("light {i+1} back to brightness",light_sheet==LightSheet::closed && current==light0+{i});')
    step('show(media,0);tap_rect(volume_button);check("volume opens",volume_open);tap_rect(volume_slider);check("volume slider",player.volume==50);tap_rect(volume_close);check("volume closes",!volume_open);')
    step('player.duration=200;player.can_seek=true;tap_rect(seek_slider);check("seek midpoint",int(player.position())==100);player.can_seek=false;check("unsupported seek rejected",!player.seek(22));player.duration=0;player.can_seek=true;')
    step('player.title="Study track";player.artist="Study artist";player.playing=true;show(home,0);tap(home_strip.x+4,home_strip.y+4);check("now playing opens Music",current==media);')
    step('const auto before=esp_rom_crc32_le(0,page_pixels,page_bytes);player.title="Different title";transport_fields();check("track text updates pixels",before!=esp_rom_crc32_le(0,page_pixels,page_bytes));player.title.clear();player.artist.clear();player.playing=false;')
    step('show(scenes,0);tap_rect(preset_buttons[2]);check("bright preset confirmed",scene_matches()&4);')
    step('tap_rect(preset_buttons[1]);check("off preset confirmed",scene_matches()&2);')
    step('ha_lights.request(0,17);ha_lights.request(1,28);ha_lights.request(2,39);')
    step('check("external light clears off highlight",!(scene_matches()&2));')
    step('show(display_page,0);tap_rect(backlight_slider);check("manual backlight",applied_brightness==50 && screen_level()==50);')
    step('tap(backlight_slider.x,backlight_slider.y+backlight_slider.h/2);check("manual backlight minimum",applied_brightness==int(backlight_min));')
    step('manual_brightness=backlight_default;override_until=0;apply_brightness();')
    step('show(media,0);tap_rect(transport_buttons[2]);check("play",player.playing && player.last_service=="media_player.media_play");')
    step('tap_rect(transport_buttons[2]);check("pause",!player.playing && player.last_service=="media_player.media_pause");')
    step('tap_rect(transport_buttons[1]);check("previous track",player.last_service=="media_player.media_previous_track");')
    step('tap_rect(transport_buttons[3]);check("next track",player.last_service=="media_player.media_next_track");')
    step('tap_rect(transport_buttons[0]);check("shuffle",player.shuffled);')
    step('tap_rect(transport_buttons[4]);tap_rect(transport_buttons[4]);check("repeat one",player.repeat_mode==2);')
    step('player.available=false;tap_rect(transport_buttons[2]);check("offline speaker guards playback",!player.playing);player.available=true;')
    step('show(climate_page,0);tap_rect(climate_up);check("unavailable thermostat guarded",!thermostat.can_adjust() && !std::isfinite(thermostat.target));')
    step('thermostat.minimum=18;thermostat.maximum=30;thermostat.step=.5;thermostat.target=22;thermostat.available=true;thermostat.dirty=true;')
    step('tap_rect(climate_up);check("thermostat increase",thermostat.target==22.5f);')
    step('tap_rect(climate_down);check("thermostat decrease",thermostat.target==22.f);')
    step('tap_rect(climate_slider);check("thermostat slider",thermostat.target==24.f);')
    step('thermostat.target=30;tap_rect(climate_up);check("thermostat upper limit",thermostat.target==30.f);')
    step('test_online=fleet.online();show(members_page,0);tap_rect(member_buttons[0]);')
    if args.fixture_identity:
        step('if(test_online){check("membership excluded",!fleet.active().members[0] && edit_feedback==0);tap_rect(member_buttons[0]);}else check("offline membership retained",fleet.active().members[0] && edit_feedback==2);')
        step('if(test_online)check("membership restored",fleet.active().members[0] && edit_feedback==0);show(edit_page,0);tap_rect(save_buttons[0]);')
        step('if(test_online)check("soft preset confirmed",fleet.active().soft[0]==17 && fleet.active().soft[1]==28 && fleet.active().soft[2]==39 && edit_feedback==6);else check("offline preset reports failure",edit_feedback==2 && !edit_waiting);')
        step('tap_rect(save_buttons[1]);')
        step('if(test_online)check("bright preset saved",fleet.active().bright[0]==17 && fleet.active().bright[1]==28 && fleet.active().bright[2]==39 && edit_feedback==6);else check("offline bright save rejected",edit_feedback==2 && !edit_waiting);')
    else:
        step('check("offline membership retained",fleet.active().members[0] && edit_feedback==2);show(edit_page,0);tap_rect(save_buttons[0]);')
        step('check("offline preset reports failure",edit_feedback==2 && !edit_waiting);')
    step('show(lights,0);last_activity=clock_ms()-int64_t(idle_timeout_s*1000)-1;')
    step('check("timed standby",current==idle && !blanked);')
    step('tap(620,392);check("wake consumes tap",current==lights && ha_lights.confirmed(0)==17);')
    step('last_activity=clock_ms()-int64_t(idle_timeout_s*1000)-1;')
    step('dim_since=clock_ms()-int64_t(backlight_off_s*1000)-1;')
    step('check("blanked",current==idle && blanked && applied_brightness==0);tap(620,392);')
    step('check("blank wakes Home",current==home && !blanked && applied_brightness>0);')
    step('check("cached profile",fleet.active().version>0);ESP_LOGI("study","QA_COMPLETE");')
    src='''#pragma once
#include "esp_rom_crc.h"
namespace study {
static int capturing_index=-1,capture_position=0;
static void capture_view(int index){
 // Diff against the original CM5-derived page to keep a 720x1280 USB capture
 // small. The host checks the reconstructed image against the board's CRC.
 if(current!=index || !unpack(pages[index],scratch))return;
 capturing_index=index;capture_position=0;
}
static void capture_chunk(){
 const int index=capturing_index;
 if(index<0)return;
 const auto *actual=reinterpret_cast<const uint16_t*>(page_pixels);
 const auto *reference=reinterpret_cast<const uint16_t*>(scratch);
 const int64_t stop=esp_timer_get_time()+6000;
 int &i=capture_position;
 while(i<width*height){
   if((i%1024==0 || actual[i]!=reference[i]) && esp_timer_get_time()>=stop)return;
   if(actual[i]==reference[i]){++i;continue;}
   int start=i++,end=i;
   while(i<width*height && i-start<72 && i-end<8){
     if(actual[i]!=reference[i])end=i+1;
     ++i;
   }
   unsigned char encoded[200];size_t size=0;
   if(mbedtls_base64_encode(encoded,sizeof(encoded),&size,page_pixels+2*start,2*(end-start))!=0)return;
   ESP_LOGI("study","QA_PIX %d %d %.*s",index,start,int(size),encoded);
 }
 ESP_LOGI("study","QA_FRAME %d %08x",index,esp_rom_crc32_le(0,page_pixels,page_bytes));
 capturing_index=-1;
}
static void tap(int x,int y){touch(x,y);release();}
static void tap_rect(const Rect &r){tap(r.x+r.w/2,r.y+r.h/2);}
static void check(const char *name,bool ok){ESP_LOGI("study","QA_CONTROL %s %s",name,ok?"PASS":"FAIL");}
static void bench_step(){
 static unsigned step=0;
 static bool test_online=false;
 if(clock_ms()<4000 || moving || down || edit_waiting || !page_pixels)return;
 switch(step++){
'''+"\n".join(steps)+"\ndefault: return;}\n}\n}\n"
    (build/"bench_touch.h").write_text(src)
    private=build/"live_runtime"
    shutil.copytree(private,build/"qa_runtime",dirs_exist_ok=True)
    hdr=build/"qa_runtime/live_settings.h"
    settings=hdr.read_text()
    import re
    if args.fixture_identity:
        ident=json.loads(args.fixture_identity.read_text())
        if ident["token"] in settings or ident["sign_key"] in settings or json.dumps(ident["server"]) in settings:
            raise ValueError("Online test requires a separate server and credentials")
        fields=[ident["server"],ident["id"],ident["mac"],ident["id"],ident["token"],ident["sign_key"]]
        settings,count=re.subn(r'fleet_settings=\{[^}]+\}',lambda m:'fleet_settings={'+','.join(map(json.dumps,fields))+'}',settings)
        store=build/"qa_runtime/config_store.h"
        store.write_text(store.read_text().replace('"panel-config"','"panel-qa-cache"'))
    else:
        settings,count=re.subn(r'(fleet_settings=\{)"[^"]+"',r'\1"http://127.0.0.1:1"',settings)
    assert count==1
    hdr.write_text(settings)
    for name in ("light_client.h","climate_client.h","media_client.h"):
        (build/"qa_runtime"/name).write_text("#define STUDY_BENCH_TEST\n"+(private/name).read_text())
    (build/"qa_study.h").write_text((build/"study.h").read_text().replace('live_runtime/study_profile.h','qa_runtime/study_profile.h'))
    (build/"qa_navigation.h").write_text((build/"navigation.h").read_text().replace("live_runtime/motion_tail.h","qa_runtime/motion_tail.h"))
    hdr=build/"qa_study.h"
    hdr.write_text(hdr.read_text().replace('"navigation.h"','"qa_navigation.h"'))
    yaml=(build/"study-live.yaml").read_text().replace("includes: [live_runtime,", "includes: [qa_runtime,").replace(
        "study.h, navigation.h]", "qa_study.h, qa_navigation.h, bench_touch.h]").replace(
        "study::tick();","if(study::capturing_index<0){study::tick(); study::bench_step();}").replace(
        "study::animate();","if(study::capturing_index>=0)study::capture_chunk();else study::animate();")
    (build/"study-qa.yaml").write_text(yaml)
    print(f"{len(views)} screen routes; {len(steps)} steps")

if __name__=="__main__":
    main()
