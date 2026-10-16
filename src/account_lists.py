"""Account lists (bot/self/brand) live only on the box (gitignored). MS_ACCOUNTS_DIR overrides the directory
(tests point it at tests/fixtures/accounts, made-up handles). A missing or unreadable list must fail closed:
/intake/x refuses with 503 instead of treating the list as empty."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
NAMES = ("bot_accounts.json", "self_accounts.json", "brand_accounts.json")


def path_for(name: str, module_default: Path) -> Path:
    if Path(module_default) != ROOT / "data" / name:   # a test patched the module constant: honour it
        return Path(module_default)
    d = os.environ.get("MS_ACCOUNTS_DIR")
    return Path(d) / name if d else Path(module_default)


def missing(paths: Optional[dict[str, Path]] = None) -> list[str]:
    """Names of account lists that are missing or not valid JSON."""
    from . import bot_accounts as b, brand as br, self_accounts as s
    paths = paths or {"bot_accounts.json": path_for("bot_accounts.json", b.BOT_ACCOUNTS_PATH),
                      "self_accounts.json": path_for("self_accounts.json", s.SELF_ACCOUNTS_PATH),
                      "brand_accounts.json": path_for("brand_accounts.json", br.BRAND_ACCOUNTS_PATH)}
    out = []
    for n, p in paths.items():
        try:
            json.loads(Path(p).read_text())
        except (OSError, ValueError):
            out.append(n)
    return out
