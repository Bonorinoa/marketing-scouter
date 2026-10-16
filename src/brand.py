"""brand_post label: a product-page link, CTA words, or a listed brand account. Label only: never a kill, never S."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .account_lists import path_for as _acc_path
from typing import Optional

BRAND_ACCOUNTS_PATH = Path(__file__).resolve().parent.parent / "data" / "brand_accounts.json"
_URL = re.compile(r"https?://[^\s]+", re.I)
_X_HOSTS = re.compile(r"^https?://(?:www\.|mobile\.)?(?:x\.com|twitter\.com|t\.co)(?:/|$)", re.I)
_PRODUCT = re.compile(r"/(?:pricing|demo|signup|sign-up|product|products)(?:[/?#.]|$)|[?&]utm_[a-z]+=", re.I)
_CTA = re.compile(r"\b(?:sign[\s-]?up|book a demo|free trial|try it|register now|discount|promo code)\b", re.I)


def brand_accounts(path: Optional[Path] = None) -> set[str]:
    try:
        return {str(h).lstrip("@").lower() for h in json.loads(Path(path or _acc_path("brand_accounts.json", BRAND_ACCOUNTS_PATH)).read_text())}
    except (OSError, ValueError, TypeError):
        return set()


def is_brand_post(text: str, author: Optional[str] = None, accounts: Optional[set[str]] = None) -> bool:
    t = text or ""
    if any(not _X_HOSTS.match(u) and _PRODUCT.search(u) for u in _URL.findall(t)):
        return True
    if _CTA.search(t):
        return True
    acc = brand_accounts() if accounts is None else accounts
    return bool(author) and author.lstrip("@").lower() in acc


def labels_for(text: str, author: Optional[str] = None) -> list[str]:
    return ["brand_post"] if is_brand_post(text, author) else []
