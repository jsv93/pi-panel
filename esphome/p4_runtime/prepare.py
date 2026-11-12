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
    args = p.parse_args()
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
    for key, name, default in [("soft", "soft", 30), ("bright", "bright", 100), ("include_presets", "members", True)]:
        array("bool" if key == "include_presets" else "int", "seed_" + name, [l.pop(key, default) for l in lights])
    header.append("constexpr char layout_contract[]=" + json.dumps(json.dumps(contract, separators=(",", ":"))) + ";")
    fields = [args.server.rstrip("/"), args.id, args.mac, args.id, identity["token"], identity["sign_key"]]
    display=config["display"]
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
    (args.build / "live-motion-tail.bin").write_bytes(blob)
    expected = ",".join(map(str, hashlib.sha256(blob).digest()))
    (dest / "motion_tail.h").write_text(
        "#pragma once\nnamespace study {\n"
        f"constexpr unsigned tail_offset={start},tail_size={len(blob)};\n"
        f"constexpr unsigned char tail_sha[]={{{expected}}};\n}}\n")
    source = (args.build / "study.yaml").read_text(encoding="utf-8")
    if not (args.build / "control_art.h").exists():
        p.error("generate control_art.h using esphome/study/control_art.py first")
    if not (args.build / "media_art.h").exists():
        p.error("generate media_art.h using esphome/study/media_art.py first")
    if not (args.build / "text_art.h").exists():
        p.error("generate text_art.h using esphome/study/text_art.py first")
    shutil.copyfile(Path(__file__).parent.parent/"study/text_renderer.h",args.build/"text_renderer.h")
    source = source.replace("study_assets.h, study.h", "study_assets.h, control_art.h, media_art.h, text_art.h, text_renderer.h, study.h")
    source = source.replace("includes: [scanout.h", "includes: [live_runtime, scanout.h")
    source = source.replace("esp_driver_jpeg, esp_driver_ppa]", "esp_driver_jpeg, esp_driver_ppa, esp_http_client, json, nvs_flash]")
    source = source.replace("    sdkconfig_options:\n", '    sdkconfig_options:\n      CONFIG_MBEDTLS_CERTIFICATE_BUNDLE: "y"\n')
    source = source.replace("\napi:\n", "\napi:\n  homeassistant_services: true\n  homeassistant_states: true\n")
    source = source.replace("    - action: ring\n","    - action: ring_live_camera\n      then:\n        - lambda: 'if(study::bell_enabled)study::camera_ring(false);'\n        - api.respond:\n            success: !lambda 'return study::bell_enabled;'\n    - action: ring\n")
    source += "\ntime:\n  - platform: homeassistant\n    id: study_clock\n"
    source = source.replace("study::begin(id(panel_display)", "study::screen_callbacks([](){auto t=id(study_clock).now();return t.is_valid()?int(t.hour)*60+t.minute:-1;}, [](int level){return id(backlight_ctrl).write_byte(0x96, (level*255+50)/100);}); study::begin(id(panel_display)")
    (args.build / "study-live.yaml").write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
