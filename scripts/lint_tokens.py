#!/usr/bin/env python3
"""Fail if hex/rgb/hsl/rgba color literals appear under web/ outside tokens.css."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
TOKENS = (WEB / "src" / "tokens.css").resolve()
EXTS = {".css", ".tsx", ".ts", ".html"}
SKIP_NAMES = {"schema.d.ts", "fixtures.json", "tokens.css"}
SKIP_DIRS = {"node_modules", "dist", ".git"}

# Match #rgb/#rrggbb/#rrggbbaa and rgb()/rgba()/hsl()/hsla() — not CSS var names.
COLOR_RE = re.compile(
    r"(?i)(?:#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})\b|(?:rgba?|hsla?)\([^)]*\))"
)


def main() -> int:
    leaks: list[str] = []
    for path in WEB.rglob("*"):
        if not path.is_file():
            continue
        if any(p in SKIP_DIRS for p in path.parts):
            continue
        if path.suffix not in EXTS:
            continue
        if path.name in SKIP_NAMES:
            continue
        if path.resolve() == TOKENS:
            continue
        # fixtures live under src/test — excluded by name; also skip *.json via EXTS
        text = path.read_text(encoding="utf-8", errors="replace")
        # Drop block comments so sample RGB in docs/comments do not trip the gate.
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        for i, line in enumerate(text.splitlines(), 1):
            code = re.sub(r"//.*$", "", line)
            code = re.sub(r"<!--.*?-->", "", code)
            if COLOR_RE.search(code):
                rel = path.relative_to(ROOT)
                leaks.append(f"{rel}:{i}: {line.strip()[:120]}")
    if leaks:
        print("COLOR LINT FAIL — literals outside tokens.css:")
        for L in leaks:
            print(f"  {L}")
        return 1
    print("COLOR LINT OK — no hex/rgb/hsl/rgba outside tokens.css")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
