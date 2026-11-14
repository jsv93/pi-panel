"""Prepare a private Study candidate from an already rendered ESPHome build."""
import argparse
import hashlib
import json
import re
import secrets
import shutil
from pathlib import Path
from urllib.parse import urlsplit


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("build", type=Path)
    p.add_argument("snapshot", type=Path)
    p.add_argument("--id", required=True)
    p.add_argument("--mac", required=True)
    p.add_argument("--server", required=True)
    p.add_argument("--identity-file", type=Path)
    p.add_argument("--production", action="store_true", help="Omit touchscreen demonstration actions from the paired build")
    p.add_argument("--architectural-only", action="store_true", help="Use the onboard Architectural layout and its six palettes")
    p.add_argument("--hosted-wifi",action="store_true",help="Include the Waveshare C6 radio and external text artwork")
    p.add_argument("--card-assets",type=Path,help="Directory containing the generated card_assets.h and card_lights.h for this room")
    args = p.parse_args()
    if args.architectural_only and (args.card_assets or not args.hosted_wifi):
        p.error("Architectural-only builds use the onboard artwork and hosted Wi-Fi")
    if not re.fullmatch(r"[a-z0-9-]{1,60}", args.id):
        p.error("invalid panel id")
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", args.mac):
        p.error("invalid MAC")
    url = urlsplit(args.server)
    if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password or url.query or url.fragment:
        p.error("invalid server URL")
    identity_path = args.identity_file or args.build / "fleet-identity.json"
    if identity_path.exists():
        identity = json.loads(identity_path.read_text())
        if (identity["id"], identity["server"], identity["mac"]) != (args.id, args.server, args.mac):
            p.error("existing enrollment belongs to a different device or server")
    else:
        identity = dict(id=args.id, server=args.server, mac=args.mac,
                        token=secrets.token_urlsafe(32), sign_key=secrets.token_urlsafe(32))
        with identity_path.open("x") as f:
            json.dump(identity, f)
    config = json.loads(args.snapshot.read_text(encoding="utf-8"))["config"]
    contract = {k: v for k, v in config.items() if not k.startswith("_")}
    lights = contract["lights"]
    if not lights or any(not re.fullmatch(r"light\.[a-z0-9_]+", light.get("entity_id", "")) for light in lights):
        p.error("this candidate requires native Home Assistant lights")
    header = ["#pragma once", "namespace study {"]

    def array(kind, name, values):
        header.append(f"constexpr {kind} {name}[]={{" + ",".join(map(json.dumps, values)) + "};")

    array("const char *", "room_entities", [l["entity_id"] for l in lights])
    array("const char *", "room_light_names", [l.get("name") or l["entity_id"] for l in lights])
    for key, name, default in [("soft", "soft", 30), ("bright", "bright", 100), ("include_presets", "members", True)]:
        array("bool" if key == "include_presets" else "int", "seed_" + name, [l.pop(key, default) for l in lights])
    header.append("constexpr char layout_contract[]=" + json.dumps(json.dumps(contract, separators=(",", ":"))) + ";")
    fields = [args.server.rstrip("/"), args.id, args.mac, args.id, identity["token"], identity["sign_key"]]
    display=config["display"]
    header.append("constexpr char card_room_label[]="+json.dumps(config.get("room_label") or "Room")+";")
    points=min(5,max(2,int(display.get("touch_points",3))))
    hold=min(1500,max(600,int(display.get("touch_hold_ms",600))))
    header.append(f"constexpr int gesture_points={points if display.get('touch_gesture','off') != 'off' else 0},gesture_hold_ms={hold};")
    header.append("constexpr bool gesture_remember="+json.dumps(bool(display.get("remember_last_state",True)))+";")
    header.append("constexpr bool diagnostic_default="+json.dumps(bool(display.get("diagnostics",False)))+";")
    header.append("constexpr bool default_mini_art="+json.dumps(bool(display.get("mini_art",True)))+";")
    for name,default in [("idle_timeout_s",45),("backlight_off_s",0),("backlight_default",100),("backlight_min",5),
                         ("adaptive_min_pct",10),("adaptive_max_pct",100),("adaptive_dark_lux",5),
                         ("adaptive_bright_lux",300),("adaptive_transition_s",5)]:
        value=display.get(name,default)
        if not isinstance(value,(int,float)) or value<0 or (name in ("backlight_default","backlight_min","adaptive_min_pct","adaptive_max_pct") and value>100):
            p.error(f"invalid display setting {name}")
        header.append(f"constexpr double {name}={value};")
    sensor=display.get("adaptive_sensor","") if display.get("adaptive_brightness") else ""
    header.append("constexpr char lux_entity[]="+json.dumps(sensor)+";")
    bell=config.get("doorbell") or {}
    header.append("constexpr bool bell_enabled="+json.dumps(bool(bell.get("enabled") and bell.get("camera")))+";")
    header.append("constexpr char bell_trigger[]="+json.dumps(bell.get("trigger") or "")+";")
    camera=bell.get("camera") or ""
    if camera and not re.fullmatch(r"camera\.[a-z0-9_]+",camera):p.error("invalid doorbell camera")
    ha_origin=(config.get("connection",{}).get("ha_url") or "").rstrip("/")
    if ha_origin:
        address=urlsplit(ha_origin)
        if address.scheme not in ("http","https") or not address.hostname or address.username or address.password or address.query or address.fragment:
            p.error("invalid Home Assistant origin")
    header.append("constexpr char bell_camera[]="+json.dumps(camera)+";")
    header.append("constexpr char ha_origin[]="+json.dumps(ha_origin)+";")
    duration=bell.get("duration_s",30)
    if type(duration) is not int or not 10<=duration<=120:p.error("invalid doorbell duration")
    header.append(f"constexpr int bell_seconds={duration};")
    media=config.get("media") or {}
    speakers=[s if isinstance(s,str) else s.get("entity_id") for s in media.get("speakers",[])]
    speakers=[s for s in speakers if s]
    default=media.get("default_speaker")
    if default and default not in speakers:
        speakers.insert(0,default)
    if any(not re.fullmatch(r"media_player\.[a-z0-9_]+",s) for s in speakers):
        p.error("invalid media player entity")
    header.append("constexpr char initial_speaker[]="+json.dumps(speakers[0] if speakers else "")+";")
    header.append("constexpr char initial_speaker_name[]="+json.dumps(media.get("default_speaker_name") or "")+";")
    labels={s["entity_id"]:s.get("name") for s in media.get("speakers",[]) if isinstance(s,dict) and s.get("entity_id")}
    labels.setdefault(default,media.get("default_speaker_name"))
    header.append("constexpr const char *speaker_ids[]={"+",".join(map(json.dumps,speakers or [""]))+"};")
    header.append("constexpr const char *speaker_labels[]={"+",".join(json.dumps(labels.get(s) or s.partition(".")[2]) for s in speakers or [""])+"};")
    header.append(f"constexpr int speaker_count={len(speakers)};")
    for role in ("temperature","humidity","climate"):
        entity=config.get("sensors",{}).get(role,"") or ""
        if entity and not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+",entity):
            p.error(f"invalid {role} entity")
        header.append(f"constexpr char {role}_entity[]="+json.dumps(entity)+";")
    header.append("constexpr p4_runtime::FleetSettings fleet_settings={" + ",".join(map(json.dumps, fields)) + "};\n}")
    dest = args.build / "live_runtime"
    dest.mkdir(exist_ok=True)
    for src in Path(__file__).parent.glob("*.h"):
        shutil.copyfile(src, dest / src.name)
    (dest / "live_settings.h").write_text("\n".join(header), encoding="utf-8")
    # The navigation acceleration table fits in the unused tail of the motion
    # partition. Preserve both OTA slots and the accepted motion bank in place.
    chunks = (args.build / "motion_chunks.h").read_text(encoding="ascii").split("chunk_data[]=", 1)[1]
    blob = bytes.fromhex("".join(re.findall(r"\\x([a-f0-9]{2})", chunks)))
    start = ((args.build / "study-motion.bin").stat().st_size + 65535) & ~65535
    if not blob or start + len(blob) > 0x1980000:
        p.error("navigation table does not fit the reserved Study partition")
    volume_file=args.build/"volume-art.bin"
    if not volume_file.exists():p.error("regenerate media_art.h and volume-art.bin with media_art.py")
    volume=volume_file.read_bytes()
    volume_offset=(start+len(blob)+4095)&~4095
    if not volume or volume_offset+len(volume)>0x1980000:p.error("volume artwork does not fit after the navigation bank")
    volume_sha=",".join(map(str,hashlib.sha256(volume).digest()))
    text_settings=""
    if args.hosted_wifi:
        if "STUDY_PACKED_SEGMENTS" not in (args.build/"navigation_assets.h").read_text():
            p.error("regenerate the compact Study motion bank before enabling the C6")
        packed=(args.build/"text-art.bin").read_bytes()
        text_offset=(volume_offset+len(volume)+4095)&~4095
        if not packed or text_offset+len(packed)>0x1980000:p.error("text artwork exceeds the Study partition")
        text_sha=",".join(map(str,hashlib.sha256(packed).digest()))
        text_settings=f"constexpr unsigned text_offset={text_offset},text_packed_size={len(packed)};\nconstexpr unsigned char text_sha[]={{{text_sha}}};\n"
    (args.build / "live-motion-tail.bin").write_bytes(blob)
    palette_file=args.build/"palette-art.bin"
    if args.architectural_only and not palette_file.is_file():
        p.error("Architectural-only builds require the rendered palette bank")
    if palette_file.is_file():
        if not (args.build/"palette_assets.h").is_file() or not args.hosted_wifi or not text_settings:
            p.error("native palettes require palette_assets.h and the compact hosted-Wi-Fi build")
        palette_offset=(text_offset+len(packed)+4095)&~4095
        palette=palette_file.read_bytes()
        if not palette or palette_offset+len(palette)>0x1980000:p.error("palette artwork exceeds the Study partition")
        palette_sha=",".join(map(str,hashlib.sha256(palette).digest()))
        text_settings+=f"constexpr unsigned palette_offset={palette_offset},palette_size={len(palette)};\nconstexpr unsigned char palette_sha[]={{{palette_sha}}};\n"
        shutil.copyfile(Path(__file__).parent.parent/"study/palette_renderer.h",dest/"palette_renderer.h")
    expected = ",".join(map(str, hashlib.sha256(blob).digest()))
    (dest / "motion_tail.h").write_text(
        "#pragma once\nnamespace study {\n"
        f"constexpr unsigned tail_offset={start},tail_size={len(blob)};\n"
        f"constexpr unsigned char tail_sha[]={{{expected}}};\n"
        f"constexpr unsigned volume_offset={volume_offset},volume_size={len(volume)};\n"
        f"constexpr unsigned char volume_sha[]={{{volume_sha}}};\n{text_settings}}}\n")
    source = (args.build / "study.yaml").read_text(encoding="utf-8")
    artwork_header = args.build / "study_assets.h"
    artwork_source = artwork_header.read_text(encoding="utf-8")
    if "#define STUDY_LZ4_ARTWORK" in artwork_source:
        shutil.copytree(Path(__file__).parent.parent/"study/study_lz4",args.build/"study_lz4",dirs_exist_ok=True)
        if "study_lz4" not in source:
            source=source.replace("includes: [","includes: [study_lz4, ",1)
    if "slider_paint=" not in artwork_source:
        artwork_header.write_text(artwork_source + "\nnamespace study { constexpr auto slider_paint=slider; }\n",encoding="utf-8")
    if args.architectural_only:
        import sys
        sys.path.insert(0,str(Path(__file__).parent.parent / "study"))
        from identify_art import generate as generate_identify
        generate_identify(config,args.build)
    if args.production:
        source = re.sub(r"(?ms)^    - action: (?:navigation_demo|lamp_demo)\n.*?(?=^    - action:|^\S|\Z)", "", source)
    source = source.replace("          for (const auto &p : touches) {",
                            "          if(study::observe_touches(touches))return;\n          for (const auto &p : touches) {")
    if not (args.build / "control_art.h").exists():
        p.error("generate control_art.h using esphome/study/control_art.py first")
    if not (args.build / "media_art.h").exists():
        p.error("generate media_art.h using esphome/study/media_art.py first")
    if not (args.build / "text_art.h").exists():
        p.error("generate text_art.h using esphome/study/text_art.py first")
    shutil.copyfile(Path(__file__).parent.parent/"study/text_renderer.h",args.build/"text_renderer.h")
    shutil.copyfile(Path(__file__).parent.parent/"study/network_screen.h",dest/"network_screen.h")
    source = source.replace("study_assets.h, study.h", "study_assets.h, control_art.h, media_art.h, text_art.h, text_renderer.h, study.h")
    source = source.replace("includes: [", "includes: [live_runtime, ",1)
    if palette_file.is_file():
        source=source.replace(", study.h",", palette_assets.h, study.h",1)
    source=source.replace("  includes:", "  platformio_options:\n    build_flags: [-DUSE_API_HOMEASSISTANT_ACTION_RESPONSES, -DUSE_API_HOMEASSISTANT_ACTION_RESPONSES_ERRORS, -DUSE_API_HOMEASSISTANT_ACTION_RESPONSES_JSON]\n  includes:",1)
    if args.architectural_only:
        source=source.replace("build_flags: [","build_flags: [-DSTUDY_IDENTIFY, -DSTUDY_ARCHITECTURAL_ONLY,",1)
        source=source.replace("  includes: [","  includes: [identify_assets.h, ",1)
        # The motion and palette banks remain memory mapped from NOR. During
        # an NVS erase, both cores must stop reading NOR, including the page
        # decoder on the second core. IDF's PSRAM XiP profile skips that guard.
        source=source.replace('CONFIG_SPIRAM_XIP_FROM_PSRAM: "y"', 'CONFIG_SPIRAM_XIP_FROM_PSRAM: "n"')
        # The hosted C6 pool has a 1600-byte stride. Every TX block must
        # meet the SDMMC driver's external-memory cache-line alignment.
        source=source.replace('CONFIG_CACHE_L2_CACHE_LINE_128B: "y"', 'CONFIG_CACHE_L2_CACHE_LINE_64B: "y"')
    source+="\njson:\n"
    # Initialise network interfaces before allocating the optional renderer
    # workers and restoring the palette. Physical display setup still runs
    # at 400. Starting the UI at 230 requires no network connection.
    source=source.replace("    - priority: 400\n", "    - priority: 230\n",1)
    if args.hosted_wifi:
        import esphome.components.network as network_component
        network_dir=args.build/"bench_components/network"
        shutil.copytree(Path(network_component.__file__).parent,network_dir,dirs_exist_ok=True,ignore=shutil.ignore_patterns("__pycache__"))
        def network_patch(filename,old,new):
            path=network_dir/filename
            contents=path.read_text(encoding="utf8")
            if contents.count(old)!=1:raise ValueError(f"Unexpected ESPHome network component in {filename}")
            path.write_text(contents.replace(old,new),encoding="utf8")
        network_patch("util.h","namespace esphome::network {",'''#include <esp_netif.h>
#include <atomic>
namespace esphome::network {
inline std::atomic<esp_netif_t*> study_station_netif{nullptr};
inline bool study_station_ip(esp_netif_ip_info_t &info){
  auto *netif=study_station_netif.load();
  return netif && esp_netif_is_netif_up(netif) && esp_netif_get_ip_info(netif,&info)==ESP_OK && info.ip.addr;
}''')
        network_patch("util.h","inline bool is_connected() {","inline bool is_connected() {\n  esp_netif_ip_info_t info{};if(study_station_ip(info))return true;")
        network_patch("util.cpp","if (ethernet::global_eth_component != nullptr)\n    return ethernet::global_eth_component->get_ip_addresses();\n#endif",'''if (ethernet::global_eth_component != nullptr && ethernet::global_eth_component->is_connected())
    return ethernet::global_eth_component->get_ip_addresses();
#endif
  esp_netif_ip_info_t info{};
  if(study_station_ip(info)){
    ip4_addr_t ip{};ip.addr=info.ip.addr;
    network::IPAddresses addresses{};addresses[0]=network::IPAddress(&ip);return addresses;
  }''')
        source=source.replace("components: [mipi_dsi]","components: [mipi_dsi, network]")
        source=source.replace("build_flags: [","build_flags: [-DSTUDY_EXTERNAL_TEXT, ",1)
        # The hosted radio restores its station after component setup.
        source=source.replace("  on_boot:\n","  on_boot:\n    - priority: -100\n      then:\n        - lambda: 'study::station.restore();'\n",1)
        source+="""\nesp32_hosted:
  type: sdio
  variant: ESP32C6
  active_high: true
  reset_pin: GPIO54
  clk_pin: GPIO18
  cmd_pin: GPIO19
  d0_pin: GPIO14
  d1_pin: GPIO15
  d2_pin: GPIO16
  d3_pin: GPIO17
  use_psram: true
"""
    source = source.replace("esp_driver_jpeg, esp_driver_ppa]", "esp_driver_jpeg, esp_driver_ppa, esp_http_client, json, nvs_flash, esp_driver_tsens]")
    source = source.replace("    type: esp-idf\n", "    type: esp-idf\n    components: [espressif/esp_websocket_client==1.4.0]\n", 1)
    source = source.replace("    sdkconfig_options:\n", '''    sdkconfig_options:
      CONFIG_FREERTOS_GENERATE_RUN_TIME_STATS: "y"
      CONFIG_FREERTOS_USE_TRACE_FACILITY: "y"
      CONFIG_FREERTOS_RUN_TIME_STATS_USING_ESP_TIMER: "y"
''', 1)
    if args.card_assets:
        study=Path(__file__).parent.parent/"study"
        for name in ("card_assets.h","card_lights.h"):
            path=args.card_assets/name
            if not path.is_file():p.error(f"Missing generated artwork index {name}")
            shutil.copyfile(path,dest/name)
        routes=args.card_assets/"card_routes.h"
        if not routes.is_file():p.error("Missing generated card_routes.h from the CM5 capture")
        shutil.copyfile(routes,dest/routes.name)
        for name in ("card_art.h","card_screen.h","card_light_controls.h","card_lights_page.h"):
            shutil.copyfile(study/name,dest/name)
        extended=[(args.card_assets/name).is_file() for name in ("card_presets.h","card_fields.h")]
        if any(extended) and not all(extended):p.error("Provide both the card_presets.h and card_fields.h indexes")
        if all(extended):
            for name in ("card_presets.h","card_fields.h"):
                shutil.copyfile(args.card_assets/name,dest/name)
            for name in ("card_text.h","card_presets_page.h"):
                shutil.copyfile(study/name,dest/name)
            numbers=args.card_assets/"card_numbers.h"
            if numbers.is_file():shutil.copyfile(numbers,dest/numbers.name)
            else:(dest/"card_numbers.h").unlink(missing_ok=True)
            speakers=args.card_assets/"card_speakers.h"
            if speakers.is_file():
                shutil.copyfile(speakers,dest/speakers.name)
                shutil.copyfile(study/"card_speaker_page.h",dest/"card_speaker_page.h")
                source=source.replace("build_flags: [","build_flags: [-DSTUDY_CARD_SPEAKERS, ",1)
                player=args.card_assets/"card_player.h"
                if player.is_file():
                    if not palette_file.is_file():p.error("Music and the theme picker require the matching Architectural palette bank")
                    shutil.copyfile(player,dest/player.name)
                    source=source.replace("build_flags: [","build_flags: [-DSTUDY_CARD_PLAYER, ",1)
                    settings=args.card_assets/"card_settings.h"
                    if settings.is_file():
                        shutil.copyfile(settings,dest/settings.name)
                        source=source.replace("build_flags: [","build_flags: [-DSTUDY_CARD_SETTINGS, ",1)
                        diagnostics=args.card_assets/"card_diagnostics.h"
                        if diagnostics.is_file():
                            shutil.copyfile(diagnostics,dest/diagnostics.name)
                            source=source.replace("build_flags: [","build_flags: [-DSTUDY_CARD_DIAGNOSTICS, ",1)
                    library=args.card_assets/"card_library.h"
                    if library.is_file():
                        shutil.copyfile(library,dest/library.name)
                        source=source.replace("build_flags: [","build_flags: [-DSTUDY_CARD_LIBRARY, ",1)
                        wifi=args.card_assets/"card_wifi.h"
                        if wifi.is_file() and args.hosted_wifi:
                            shutil.copyfile(wifi,dest/wifi.name)
                            source=source.replace("build_flags: [","build_flags: [-DSTUDY_CARD_WIFI, ",1)
                        overlays=args.card_assets/"card_overlay.h"
                        bell=args.card_assets/"card_bell.h"
                        if bell.is_file():
                            shutil.copyfile(bell,dest/bell.name)
                            source=source.replace("build_flags: [","build_flags: [-DSTUDY_CARD_BELL, ",1)
                        if overlays.is_file():
                            shutil.copyfile(overlays,dest/overlays.name)
                            source=source.replace("build_flags: [","build_flags: [-DSTUDY_CARD_OVERLAYS, ",1)
                            geometry=args.card_assets/"card_motion_geometry.h"
                            if geometry.is_file():
                                shutil.copyfile(geometry,dest/geometry.name)
                                source=source.replace("build_flags: [","build_flags: [-DSTUDY_CARD_MOTION_GEOMETRY, ",1)
                            editor=args.card_assets/"card_editor.h"
                            if editor.is_file():
                                shutil.copyfile(editor,dest/editor.name)
                                source=source.replace("build_flags: [","build_flags: [-DSTUDY_CARD_EDITOR, ",1)
            source=source.replace("build_flags: [","build_flags: [-DSTUDY_CARD_FIELDS, ",1)
        source=source.replace("build_flags: [","build_flags: [-DSTUDY_CARD_ART, ",1)
        source=source.replace("json, nvs_flash]","json, nvs_flash, fatfs, sdmmc, esp_driver_sdmmc]")
        source=source.replace("    advanced:\n","    advanced:\n      disable_fatfs: false\n      disable_vfs_support_dir: false\n",1)
        source=source.replace("    sdkconfig_options:\n",'    sdkconfig_options:\n      CONFIG_FATFS_LFN_NONE: "n"\n      CONFIG_FATFS_LFN_HEAP: "y"\n',1)
    source = source.replace("    sdkconfig_options:\n", '    sdkconfig_options:\n      CONFIG_MBEDTLS_CERTIFICATE_BUNDLE: "y"\n')
    source = source.replace("\napi:\n", "\napi:\n  homeassistant_services: true\n  homeassistant_states: true\n")
    source = source.replace("    - action: ring\n","    - action: ring_live_camera\n      then:\n        - lambda: 'if(study::bell_enabled)study::camera_ring(false);'\n        - api.respond:\n            success: !lambda 'return study::bell_enabled;'\n    - action: ring\n")
    source += "\ntime:\n  - platform: homeassistant\n    id: study_clock\n"
    source = source.replace("study::begin(id(panel_display)", "study::screen_callbacks([](){auto t=id(study_clock).now();return t.is_valid()?int(t.hour)*60+t.minute:-1;}, [](int level){return id(backlight_ctrl).write_byte(0x96, (level*255+50)/100);}); study::begin(id(panel_display)")
    if "-DSTUDY_CARD_FIELDS" in source:
        source=source.replace("study::screen_callbacks(", "study::card_date_now=[](){auto t=id(study_clock).now(); std::string room=study::card_room_label; return t.is_valid()?t.strftime(\"%a, \")+std::to_string(t.day_of_month)+t.strftime(\" %b\")+\"  ·  \"+room:room;}; study::screen_callbacks(",1)
    (args.build / "study-live.yaml").write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
