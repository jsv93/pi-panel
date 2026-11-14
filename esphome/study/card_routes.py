"""Export the visible touch targets measured by the CM5 Chromium reference."""
import re
from pathlib import Path


def actions(page, elements):
    speaker = 0
    colour = 0
    effect = 0
    for el in elements:
        data, key = el["attrs"], el["id"]
        classes = set(el["classes"].split())
        title = el["text"].partition("\n")[0]
        command, argument = None, 0
        sheet = data.get("sheet")
        if sheet in ("scenes", "lights", "climate", "blinds", "media", "settings", "scene-edit"):
            command = "open_" + sheet.replace("-", "_")
        elif "close" in data or "ovclose" in data or key == "bBack":
            command = "back"
        elif data.get("preset") in ("soft", "off", "bright"):
            command, argument = "preset", ("soft", "off", "bright").index(data["preset"])
        elif "light" in data:
            command, argument = "light", int(data["light"])
        elif re.fullmatch(r"ls\d+", key):
            command, argument = "brightness", int(key[2:])
        elif key in ("icoSearch", "icoMore", "icoSpk", "mpVolumeButton", "mpVolumeClose", "mVol",
                     "themeRow", "paletteRow", "wifiRow", "archMiniArt", "spDown", "spUp", "bl",
                     "prev", "next", "rep", "shuf", "pp", "ctSlider", "bView"):
            command = key
        elif page == "speakers" and "spk-select" in classes:
            command, argument = "speaker", speaker
        elif page == "speakers" and "spk-transfer" in classes:
            command, argument = "transfer", speaker
            speaker += 1
        elif page == "theme" and title.lower() in ("default","ambient","architectural"):
            command, argument = "choose_theme", ("default","ambient","architectural").index(title.lower())
        elif page == "palette" and title.lower() in ("linen","midnight","ember","slate","heath","mono"):
            command, argument = "choose_palette", ("linen","midnight","ember","slate","heath","mono").index(title.lower())
        elif page.startswith("detail"):
            if "act" in classes:
                command = "membership"
            elif "sw" in classes:
                command, argument = "colour", colour
                colour += 1
            elif "tile" in classes:
                command, argument = "effect", effect
                effect += 1
        if command:
            x,y,w,h = el["r"]
            if min(x,y)<0 or min(w,h)<=0 or x+w>720 or y+h>1280:
                raise ValueError(f"Invalid kiosk hit area on {page}")
            yield command, argument, x,y,w,h


def emit(directory, geometry):
    names = sorted({name for layout in geometry for name in layout})
    commands = set()
    rows = []
    for theme, layout in enumerate(geometry):
        for name in names:
            for action, arg, x,y,w,h in actions(name, layout[name]):
                commands.add(action)
                rows.append((theme, name.replace("-", "_"), action, arg, x,y,w,h))
    lines = ["#pragma once", '#include "card_assets.h"', "namespace study {",
             "enum class CardAction {"+",".join(sorted(commands))+"};",
             "struct CardHit {int theme;CardPage page;CardAction action;int arg,x,y,w,h;};",
             "constexpr CardHit card_hits[]={"]
    for theme,page,cmd,arg,x,y,w,h in rows:
        lines.append(f"  {{{theme},CardPage::{page},CardAction::{cmd},{arg},{x},{y},{w},{h}}},")
    lines.extend(["};","inline const CardHit *card_hit(int theme,CardPage page,int x,int y){",
                  "  for(const auto &r:card_hits)if(r.theme==theme && r.page==page && x>=r.x && x<r.x+r.w && y>=r.y && y<r.y+r.h)return &r;",
                  "  return nullptr;","}","}"])
    Path(directory,"card_routes.h").write_text("\n".join(lines)+"\n",encoding="ascii")
