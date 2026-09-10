"""HACS will not install this repository if the layout drifts, and it says so
only at install time, in someone else's Home Assistant. Cheap to check here.

    python tests/test_hacs_layout.py
"""
import json
import os
import sys
from glob import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = True


def chk(label, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("  PASS  " if cond else "  FAIL  ") + label + (("  " + detail) if detail else ""))


def main():
    os.chdir(ROOT)

    chk("hacs.json at repo root", os.path.isfile("hacs.json"))
    try:
        h = json.load(open("hacs.json", encoding="utf-8"))
    except Exception as e:
        chk("hacs.json parses", False, str(e))
        return 1
    chk("hacs.json names the integration", bool(h.get("name")), repr(h.get("name")))

    # HACS manages the first subdirectory only, so a second one silently wins
    # or loses depending on sort order.
    dirs = sorted(d for d in glob("custom_components/*") if os.path.isdir(d))
    chk("exactly one integration under custom_components/", len(dirs) == 1, str(dirs))
    if not dirs:
        return 1

    domain_dir = dirs[0]
    mp = os.path.join(domain_dir, "manifest.json")
    chk("manifest.json present", os.path.isfile(mp), mp)
    if not os.path.isfile(mp):
        return 1
    m = json.load(open(mp, encoding="utf-8"))

    for k in ("domain", "name", "version", "documentation", "issue_tracker", "codeowners"):
        chk("manifest has " + k, m.get(k) not in ("", [], None), repr(m.get(k))[:70])

    chk("domain matches its directory name",
        m.get("domain") == os.path.basename(domain_dir),
        f"{m.get('domain')!r} vs {os.path.basename(domain_dir)!r}")

    # HACS compares this against the installed copy to offer updates. Left at
    # the number it was scaffolded with, it never offers one.
    chk("version is not the scaffold default", m.get("version") != "0.1.0", repr(m.get("version")))

    chk("README.md at repo root (HACS renders it)", os.path.isfile("README.md"))
    # What git tracks, not what is on disk. HACS installs from the repository,
    # and a __pycache__ appears in the working tree every time anyone runs the
    # code -- checked on disk, this failed after any compile, and a check that
    # fails for no reason is one people learn to skip.
    import subprocess
    try:
        tracked = subprocess.run(["git", "ls-files", "custom_components"], cwd=ROOT,
                                 capture_output=True, text=True, check=True).stdout
        chk("no __pycache__ tracked under custom_components/", "__pycache__" not in tracked)
    except Exception as e:
        print(f"  SKIP  __pycache__ check (git unavailable: {e})")

    # Every platform the integration declares must actually be there.
    init = open(os.path.join(domain_dir, "__init__.py"), encoding="utf-8").read()
    for plat in ("sensor", "binary_sensor", "button", "number", "switch"):
        if f'"{plat}"' in init or f"Platform.{plat.upper()}" in init:
            chk(f"{plat}.py exists for a declared platform",
                os.path.isfile(os.path.join(domain_dir, plat + ".py")))

    print("\n" + ("ALL CHECKS PASS" if ok else "SOMETHING IS WRONG"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
