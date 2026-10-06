#!/usr/bin/env python3
"""Gather every reference document into one file you can carry.

    python docs/build-reference.py [outfile]

For handing the project to someone -- or something -- that does not have the
repository: another machine, another session, a reviewer, a printer.

Generated rather than kept in the repo on purpose. A committed copy of
documentation that also lives somewhere else is a second source of truth, and
this project has lost more than one evening to a stale copy of something that
had a fresher original. Regenerate it when you need it.

Contents are copied verbatim. Nothing is reflowed, summarised or reordered
inside a document: what arrives is what the repository says.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Reading order, not alphabetical: what it is, the rules that shape it, the
# decisions, then the subsystems, then what the hardware taught us, then the
# per-component notes.
DOCS = [
    ("README.md",                  "What this is"),
    ("CLAUDE.md",                  "Constraints that were expensive to learn"),
    ("docs/ARCHITECTURE.md",       "Architecture decisions, and what was rejected"),
    ("docs/SECURITY.md",           "Security audit and what was done about it"),
    ("docs/DALI-INTEGRATION.md",   "DALI gateway API and the degraded path"),
    ("docs/INTEGRATION.md",        "The Home Assistant integration"),
    ("docs/HA-ADDON-PLAN.md",      "Add-on packaging plan"),
    ("docs/PI-FINDINGS.md",        "Raspberry Pi hardware findings"),
    ("docs/PI-KIOSK-FINDINGS.md",  "Pi kiosk findings"),
    ("docs/P4-FINDINGS.md",        "ESP32-P4 findings (retired platform)"),
    ("server/README.md",           "Config server"),
    ("addon/README.md",            "Add-on packaging"),
    ("pi-os/README.md",            "Pi OS kiosk boot"),
    ("tests/README.md",            "Tests"),
    ("panel-ui/FONT-LICENCE.md",   "Font licence"),
]


def git(*args, default=""):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return default


def anchor(title):
    return "".join(c for c in title.lower().replace(" ", "-")
                   if c.isalnum() or c in "-_")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "pi-panel-reference.md"
    described = git("describe", "--tags", "--always", default="unknown")
    commit = git("rev-parse", "--short", "HEAD", default="unknown")
    dirty = bool(git("status", "--porcelain"))
    origin = git("config", "--get", "remote.origin.url", default="")

    parts, toc, missing = [], [], []
    for path, blurb in DOCS:
        full = os.path.join(ROOT, path)
        if not os.path.isfile(full):
            missing.append(path)
            continue
        body = open(full, encoding="utf-8").read().rstrip()
        title = next((l[2:].strip() for l in body.splitlines() if l.startswith("# ")), path)
        toc.append(f"- [{title}](#{anchor(title)}) — {blurb}  \n  `{path}`")
        parts.append(f"<!-- ==== {path} ==== -->\n\n{body}\n")

    head = [
        "# pi-panel — reference documentation",
        "",
        f"Every reference document in the repository, as of **{described}** "
        f"(`{commit}`{', with uncommitted changes' if dirty else ''}), "
        f"gathered {time.strftime('%Y-%m-%d')}.",
        "",
        f"Source: {origin}" if origin else "",
        "",
        "Copied verbatim by `docs/build-reference.py`. Nothing here is a summary — "
        "where this disagrees with the repository, the repository is right, and this "
        "file is out of date. Regenerate rather than edit it.",
        "",
        "## Contents",
        "",
        *toc,
        "",
    ]
    if missing:
        head += ["> Listed but not found, so not included: "
                 + ", ".join(f"`{m}`" for m in missing), ""]

    doc = "\n".join(l for l in head if l is not None) + "\n---\n\n" + "\n\n---\n\n".join(parts)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(doc)

    print(f"{out}: {len(parts)} documents, {doc.count(chr(10)) + 1} lines, "
          f"{len(doc) / 1024:.0f} KB")
    for m in missing:
        print(f"  missing: {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
