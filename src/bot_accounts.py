"""Platform bot authors (data/bot_accounts.json), e.g. @grok auto-replies.

Discovery never turns a bot's post into a card. When the discovery routine sends the thread's
original post as ``thread_root`` (url + text + author), intake scores that post instead; otherwise
the bot post is killed as ``bot_author`` and, when the routine sent ``conversation_id`` or
``in_reply_to_status_id``, the result carries ``target_url`` so the next run can fetch the original.
This is different from self_accounts.json (Augusto's own handles).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .account_lists import path_for as _acc_path
from typing import Iterable, Optional

BOT_ACCOUNTS_PATH = Path(__file__).resolve().parent.parent / "data" / "bot_accounts.json"
_STATUS_URL = re.compile(r"(?:https?://)?(?:www\.|mobile\.)?(?:x|twitter)\.com/@?([A-Za-z0-9_]{1,15})/status(?:es)?/(\d+)", re.I)
_ID = re.compile(r"^\d{1,25}$")


def _norm(h: Optional[str]) -> str:
    return (h or "").strip().lstrip("@").lower()


def bot_accounts(path: Optional[Path] = None) -> set[str]:
    try:
        data = json.loads(Path(path or _acc_path("bot_accounts.json", BOT_ACCOUNTS_PATH)).read_text())
    except (OSError, ValueError, TypeError):
        return set()
    handles: Iterable = data.get("handles", []) if isinstance(data, dict) else data
    return {_norm(h) for h in handles if isinstance(h, str) and _norm(h)}


def url_handle(url: Optional[str]) -> str:
    m = _STATUS_URL.search(url or "")
    return _norm(m.group(1)) if m else ""


def is_bot_post(post: dict, accounts: Optional[set[str]] = None) -> bool:
    """True when the post's author (author_handle, or the handle in its own status URL) is a bot."""
    acc = bot_accounts() if accounts is None else accounts
    hs = {_norm(post.get("author_handle")), url_handle(post.get("url"))} - {""}
    return any(h in acc for h in hs)


def original_target(post: dict) -> Optional[str]:
    """Where the thread's original post lives, from what the routine sent (never fetched here)."""
    root = post.get("thread_root") or {}
    if isinstance(root, dict) and _STATUS_URL.search(str(root.get("url") or "")):
        return str(root["url"]).strip()
    for k in ("conversation_id", "in_reply_to_status_id"):
        v = str(post.get(k) or "").strip()
        if _ID.match(v) and v not in (url_status_id(post.get("url")) or "",):
            return f"https://x.com/i/status/{v}"
    return None


def url_status_id(url: Optional[str]) -> Optional[str]:
    m = _STATUS_URL.search(url or "")
    return m.group(2) if m else None


def redirect_bot(post: dict, accounts: Optional[set[str]] = None) -> dict:
    """Decide what intake does with one post.

    Returns {"bot": False} for a human post; {"bot": True, "post": <root post>, "redirected_from": url}
    when a usable thread_root (status URL + text, non-bot author) came with it; else
    {"bot": True, "post": None, "target_url": <url or None>} (killed as bot_author).
    """
    acc = bot_accounts() if accounts is None else accounts
    if not is_bot_post(post, acc):
        return {"bot": False}
    root = post.get("thread_root")
    if isinstance(root, dict) and str(root.get("text") or "").strip() and _STATUS_URL.search(str(root.get("url") or "")) \
            and not is_bot_post(root, acc):
        keep = ("url", "text", "author_handle", "created_at", "reply_count", "quote_count", "like_count")
        return {"bot": True, "post": {k: root.get(k) for k in keep}, "redirected_from": (post.get("url") or "").strip()}
    return {"bot": True, "post": None, "target_url": original_target(post)}
