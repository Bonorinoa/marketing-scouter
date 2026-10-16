"""Seed inventory, watchlist, and optional demo open cards on first launch."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .fit import match_slugs_from_text
from .models import InventoryAsset, Outlet, WatchlistSource
from .pipeline import ScoutRunner
from .store import Store

_DATA = Path(__file__).resolve().parent.parent / "data"


def _load_json(name: str):
    aliases = {
        "seed_inventory.json": ["seed_inventory.json", "sample_inventory.json"],
        "sample_inventory.json": ["sample_inventory.json", "seed_inventory.json"],
        "watchlist_sources.json": ["watchlist_sources.json"],
        "demo_candidates.json": ["demo_candidates.json"],
    }
    for candidate in aliases.get(name, [name]):
        p = _DATA / candidate
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return None


def _age_hours(created_at: str | None, default: float = 12.0) -> float:
    if not created_at:
        return default
    try:
        dt = datetime.fromisoformat(created_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
    except Exception:
        return default


def _pick_asset(assets: list[InventoryAsset], slugs: list[str], text: str):
    if not assets:
        return None
    if slugs:
        for a in assets:
            if any(s in a.slugs for s in slugs):
                return a
    scored = []
    for a in assets:
        hit = match_slugs_from_text(text, candidate_slugs=a.slugs or None)
        if hit:
            scored.append((len(hit), a))
    if scored:
        scored.sort(key=lambda x: -x[0])
        return scored[0][1]
    return None


def ensure_seeded(
    store: Store, runner: ScoutRunner | None = None, *, demo_cards: bool = True
) -> str:
    """Idempotent seed. Returns status message."""
    if store.get_meta("seeded_v1") == "1":
        return "already_seeded"

    inv = _load_json("seed_inventory.json") or []
    for row in inv:
        store.upsert_asset(InventoryAsset.model_validate(row))

    wl = _load_json("watchlist_sources.json") or []
    for row in wl:
        store.upsert_watchlist(WatchlistSource.model_validate(row))

    if demo_cards and runner is not None:
        demos = _load_json("demo_candidates.json") or []
        assets = store.list_assets()
        for d in demos:
            text = (
                d.get("title_or_snippet")
                or d.get("title_hint")
                or d.get("title_or_snippet")
                or ""
            )
            low = text.lower()
            # Leave kill demos for Paste tab (promo / congrats fluff)
            if any(
                k in low
                for k in (
                    "promo code",
                    "buy now",
                    "link in bio",
                    "congrats",
                    "congratulations",
                    "tag a friend",
                    "dm me",
                    "limited offer",
                )
            ):
                continue
            suggested = d.get("suggested_asset_id")
            asset = store.get_asset(suggested) if suggested else None
            if asset is None:
                slugs = match_slugs_from_text(text)
                asset = _pick_asset(assets, slugs, text)
            if asset is None:
                continue
            outlet = Outlet(d.get("outlet", "x"))
            runner.paste_and_scout(
                d["url"],
                outlet=outlet,
                asset=asset,
                title_hint=text,
                author=d.get("author"),
                age_hours=_age_hours(
                    d.get("created_at"), float(d.get("age_hours", 12) or 12)
                ),
                reply_count=d.get("reply_count"),
                quote_count=d.get("quote_count"),
                comment_count=d.get("comment_count"),
                like_count=d.get("like_count"),
            )

    store.set_meta("seeded_v1", "1")
    return "seeded"
