#!/usr/bin/env python3
"""Assemble the single file browser app from the sources in src/.

The result, dist/TrafficVolumes.html, has no external references at all, so it
runs from a file:// URL on a machine with nothing installed.
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
OUT = os.path.join(ROOT, "dist", "TrafficVolumes.html")


def read(name: str) -> str:
    with open(os.path.join(SRC, name), encoding="utf-8") as handle:
        return handle.read()


def script_files() -> list[str]:
    names = [n for n in os.listdir(SRC) if re.match(r"^\d+-.*\.js$", n)]
    return sorted(names)


def build() -> str:
    template = read("index.html")
    style = read("style.css")
    scripts = script_files()
    if not scripts:
        raise SystemExit("No numbered .js sources found in src/")
    bundle = "\n".join(
        f"/* ===== {name} ===== */\n{read(name)}" for name in scripts
    )
    for placeholder, content in (("/*STYLE*/", style), ("/*SCRIPT*/", bundle)):
        if placeholder not in template:
            raise SystemExit(f"{placeholder} missing from src/index.html")
        # A literal backslash in the replacement must survive re.sub, so splice
        # the string directly instead.
        head, _, tail = template.partition(placeholder)
        template = head + content + tail
    if "</script>" in bundle.replace("<\\/script>", ""):
        raise SystemExit("A source file contains </script>, which would end the tag early")
    return template


def main() -> int:
    html = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(html)
    size = os.path.getsize(OUT)
    print(f"{OUT}: {size / 1024:.0f} kB from {len(script_files())} scripts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
