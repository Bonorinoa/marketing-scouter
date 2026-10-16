"""Augusto's own accounts (data/self_accounts.json). Their posts are never cards, never graded, never labelled."""
from __future__ import annotations

import json
from pathlib import Path

from .account_lists import path_for as _acc_path
from typing import Iterable, Optional

SELF_ACCOUNTS_PATH = Path(__file__).resolve().parent.parent / "data" / "self_accounts.json"


def _norm(h: Optional[str]) -> str:
    return (h or "").strip().lstrip("@").lower()


def self_accounts(path: Optional[Path] = None) -> set[str]:
    try:
        return {_norm(h) for h in json.loads(Path(path or _acc_path("self_accounts.json", SELF_ACCOUNTS_PATH)).read_text()) if _norm(h)}
    except (OSError, ValueError, TypeError):
        return set()


def is_self_account(handle: Optional[str], accounts: Optional[set[str]] = None) -> bool:
    h = _norm(handle)
    return bool(h) and h in (self_accounts() if accounts is None else accounts)


def drop_self_posts(rows: Iterable[dict], handle_keys=("author_handle", "author", "handle", "username")) -> list[dict]:
    """For eval/rubric batches: drop rows authored by a self account (any common handle key, or an x.com URL)."""
    acc = self_accounts()
    out = []
    for r in rows:
        hs = [r.get(k) for k in handle_keys if r.get(k)]
        url = str(r.get("url") or r.get("link") or "")
        if "/status/" in url:
            hs.append(url.split("/status/")[0].rstrip("/").rsplit("/", 1)[-1])
        if not any(is_self_account(h, acc) for h in hs):
            out.append(r)
    return out


_STATUS_URL = __import__("re").compile(r"(?:https?://)?(?:www\.|mobile\.)?(?:x|twitter)\.com/@?([A-Za-z0-9_]{1,15})/status(?:es)?/\d+", __import__("re").I)


def self_in_urls(*texts: Optional[str], accounts: Optional[set[str]] = None) -> bool:
    """True if any x.com / twitter.com status URL (the post's own, quoted or linked) is under a self handle."""
    acc = self_accounts() if accounts is None else accounts
    return any(_norm(m.group(1)) in acc for t in texts if t for m in _STATUS_URL.finditer(t))
