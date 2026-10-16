"""Untrusted model decline reasons -> plain, short card text (Researcher copy, 2026-10-14)."""
from __future__ import annotations

import html
import re
import unicodedata
from typing import Optional

MAX_LEN = 140
NO_DRAFT_LINE = "No draft: the drafter passed on this one. Reason: {reason}"
NO_DRAFT_TOOLTIP = "The drafter read this and chose not to reply. You can still reply yourself from the handoff."
NO_DRAFT_FALLBACK = "none given."

_TAG = re.compile(r"<[^>]*>")
_MDLINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S*")
_DOMAIN = re.compile(r"(?i)\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?")
_HANDLE = re.compile(r"(?<![\w])@\w+")
_MD = re.compile(r"[*_`#>|~\[\]]+")


def sanitize_reason(raw: Optional[str]) -> str:
    """Plain text, no links/handles/markup/control chars, one line, <=140 chars on a word boundary."""
    if not raw:
        return ""
    s = html.unescape(unicodedata.normalize("NFKC", str(raw)))
    s = "".join(" " if unicodedata.category(c)[0] in "CZ" and c != " " else c for c in s)
    s = _TAG.sub(" ", s)
    s = _MDLINK.sub(r"\1", s)
    s = _URL.sub(" ", s)
    s = _DOMAIN.sub(" ", s)
    s = _HANDLE.sub(" ", s)
    s = _MD.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    if len(s) > MAX_LEN:
        cut = s[: MAX_LEN - 1]
        if " " in cut:
            cut = cut[: cut.rfind(" ")]
        s = cut.rstrip(" ,;:.-") + "…"
    return s


def no_draft_line(reason: Optional[str]) -> str:
    return NO_DRAFT_LINE.format(reason=sanitize_reason(reason) or NO_DRAFT_FALLBACK)
