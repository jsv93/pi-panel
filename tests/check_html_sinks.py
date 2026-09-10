"""Find markup built from plain template literals in the admin GUI.

index.html escapes by default: markup is built with html``, which escapes
every interpolation, and raw() marks the few fragments that are already safe.
A plain backtick template that contains both markup and an interpolation is
the thing that slips past that -- the exact shape of every injection path the
2026-09 audit found. This lists every one, so a new one is a failed check
rather than a finding in the next audit.

    python tests/check_html_sinks.py

Exit 1 if any are found that are not on the allowlist below.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "server", "app", "static", "index.html")

# Plain templates that build markup from values that are not data -- a count,
# a boolean-derived word, a fixed CSS variable. Listed by a fragment of their
# text so an edit that changes one makes it fail loudly and get looked at.
ALLOW = [
]


def scan(src):
    """Yield (offset, tag, has_interpolation, text) for each template literal."""
    i, n = 0, len(src)
    while i < n:
        if src[i] != "`":
            i += 1
            continue
        j = i - 1
        while j >= 0 and src[j] in " \t":
            j -= 1
        k = j
        while k >= 0 and (src[k].isalnum() or src[k] == "_"):
            k -= 1
        tag = src[k + 1:j + 1]
        end, interp = _close(src, i + 1)
        yield i, tag, interp, src[i:end + 1]
        i = end + 1


def _close(src, t):
    """Index of the backtick closing the template that starts before t."""
    depth, interp = 0, False
    while t < len(src):
        c = src[t]
        if c == "\\":
            t += 2
            continue
        if c == "$" and src[t + 1:t + 2] == "{":
            depth += 1
            interp = True
            t += 2
            continue
        if c == "}" and depth:
            depth -= 1
            t += 1
            continue
        if c == "`":
            if not depth:
                return t, interp
            t = _close(src, t + 1)[0] + 1        # a template nested in ${ }
            continue
        t += 1
    return t, interp


def main():
    s = open(PATH, encoding="utf-8").read()
    start = s.find("<script")
    js = s[start:s.rfind("</script>")]
    base = s[:start].count("\n")
    found = []
    for off, tag, interp, body in scan(js):
        if tag in ("html", "raw") or not interp or "<" not in body:
            continue
        if any(a in body for a in ALLOW):
            continue
        found.append((base + js[:off].count("\n") + 1, " ".join(body.split())[:100]))
    if found:
        print(f"{len(found)} plain template(s) build markup from interpolated values:\n")
        for ln, b in found:
            print(f"  index.html:{ln}  {b}")
        print("\nUse html`` (escapes) or raw() for a fragment that is already safe.")
        return 1
    print("no unescaped markup templates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
