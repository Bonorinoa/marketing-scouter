"""Canonical post identity: one card per post (Designer blocker 2026-10-13 17:02 PT).

key = 'x:<status id>' for X/Twitter status URLs, else 'url:<normalized url>' (scheme/www/trailing slash/
query/fragment stripped, lowercased host), else 'text:<sha256 of normalized text>'."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlsplit

_STATUS = re.compile(r"(?:x|twitter)\.com/(?:[^/]+/)?(?:i/web/)?status(?:es)?/(\d{5,25})", re.I)
LIVE_STATES = ("open", "drafting", "awaiting_approval", "pinned")


def post_key(url: str | None, text: str | None = None) -> str | None:
    u = (url or "").strip()
    m = _STATUS.search(u)
    if m:
        return "x:" + m.group(1)
    if u and "://" in u or u.startswith("www."):
        s = urlsplit(u if "://" in u else "https://" + u)
        host = s.netloc.lower().removeprefix("www.")
        path = s.path.rstrip("/") or "/"
        if host:
            return f"url:{host}{path}"
    t = " ".join(unicodedata.normalize("NFKC", text or "").casefold().split())
    return "text:" + hashlib.sha256(t.encode()).hexdigest()[:20] if t else None


def resolve_post_dedupe(card, cards, is_protected) -> dict | None:
    """Shared by api/core.py and pipeline.py. None: no other live card for this post.
    {"ok": False, "key", "kept": <existing card>}: an existing protected or >=S card wins, new card is dropped.
    {"ok": True, "key", "losers": [...]}: the new card wins; demote losers only once it is admitted."""
    key = post_key(card.url, getattr(card, "title_or_snippet", None))
    if not key:
        return None
    same = [c for c in cards if c.card_id != card.card_id and c.state.value in LIVE_STATES
            and post_key(c.url, getattr(c, "title_or_snippet", None)) == key]
    if not same:
        return None
    keep_old = [c for c in same if is_protected(c) or c.S >= card.S]
    if keep_old:
        return {"ok": False, "key": key, "kept": max(keep_old, key=lambda c: (c.S, c.card_id))}
    return {"ok": True, "key": key, "losers": same}


def note_dropped(kept, key: str, dropped_assets: list[str]) -> None:
    """Accumulate the post_dedupe record (count + assets) on the surviving card."""
    prev = kept.post_dedupe or {}
    kept.post_dedupe = {"key": key, "dropped": prev.get("dropped", 0) + len(dropped_assets),
                        "dropped_assets": prev.get("dropped_assets", []) + list(dropped_assets)}
