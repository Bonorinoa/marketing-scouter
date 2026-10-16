"""Personal O-1A win export → Google Sheets–shaped rows (Augusto, no org_id)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence, Union

from src.models import EventKind, ScoutEvent, WinSignal

# Column order for the personal win sheet (Marketing / Systems handoff).
# Matches docs/CARD-UX-BRIEF.md: date · slug · outlet · asset_id · source_id · win_type · card_id · note
WIN_SHEET_COLUMNS: list[str] = [
    "date",
    "slug",
    "outlet",
    "asset_id",
    "source_id",
    "win_type",
    "card_id",
    "note",
    "evidence_url",
    "archive_url",
    "criterion_hint",
    "is_test",
    "prev_hash",
    "row_hash",
]

_OWNER = "Augusto personal"  # dossier owner; never org_id
_MISSING = object()


def _ts_date(ts: Union[datetime, str, None]) -> str:
    if ts is None:
        return datetime.now(timezone.utc).date().isoformat()
    if isinstance(ts, datetime):
        d = ts
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).date().isoformat()
    s = str(ts)
    # ISO date or datetime prefix
    return s[:10] if len(s) >= 10 else s


def _win_type_str(w: Union[WinSignal, str]) -> str:
    if isinstance(w, WinSignal):
        return w.value
    return str(w)


def _event_as_mapping(event: Union[ScoutEvent, Mapping[str, Any]]) -> Mapping[str, Any]:
    if isinstance(event, ScoutEvent):
        return event.model_dump(mode="python", exclude_none=False)
    return event


def _card_value(card: Any, key: str, default: Any = None) -> Any:
    if isinstance(card, Mapping):
        return card.get(key, default)
    return getattr(card, key, default)


def _outlet_value(outlet: Any) -> str:
    if outlet is None:
        return ""
    value = getattr(outlet, "value", outlet)
    return str(value) if value is not None else ""


def _norm_optional(value: Any) -> Optional[str]:
    if value is None or value is _MISSING:
        return None
    s = str(value).strip()
    return s if s else None


def win_fields_from_card(card: Any) -> dict[str, Any]:
    """Return the dossier identity fields carried by a scored card.

    The primary Fit claim is the first card slug.  ``source_id`` is read from
    an explicit card field first, then from ``raw_meta`` when available.
    ``asset_id`` piece-keys the row when recommend was asset-scoped; omit/null
    only in explicit general/profile-wide mode (no asset on the card).
    """
    slugs = _card_value(card, "slugs", []) or []
    if isinstance(slugs, str):
        slugs = [slugs]
    slug = next((str(value).strip() for value in slugs if value and str(value).strip()), "")

    outlet = _outlet_value(_card_value(card, "outlet", ""))

    source_id = _card_value(card, "source_id", _MISSING)
    if source_id is _MISSING or source_id in (None, ""):
        raw_meta = _card_value(card, "raw_meta", {}) or {}
        if isinstance(raw_meta, Mapping):
            source_id = raw_meta.get("source_id")
    if source_id is _MISSING:
        source_id = None

    asset_id = _norm_optional(_card_value(card, "asset_id", None))

    return {
        "slug": slug,
        "outlet": outlet,
        "asset_id": asset_id,
        "source_id": source_id if source_id not in ("", _MISSING) else None,
    }


def aggregate_wins(
    events: Sequence[Union[ScoutEvent, Mapping[str, Any]]],
    cards_by_id: Mapping[str, Any] | None = None,
    include_test: bool = False,
) -> list[dict[str, Any]]:
    """Flatten win events into personal dossier rows, one row per win signal.

    Event ``slug``, ``outlet``, ``asset_id``, and ``source_id`` take precedence.
    When a legacy win event is missing any of those fields, ``cards_by_id`` can
    supply them from the acted card.  A legacy slug accidentally stored in
    ``note`` is cleared only when the slug was successfully backfilled from
    that card.  Vanity metrics are never inferred or emitted.
    """
    rows: list[dict[str, Any]] = []
    for ev in events:
        m = _event_as_mapping(ev)
        kind = m.get("kind")
        kind_s = kind.value if isinstance(kind, EventKind) else str(kind or "")
        if kind_s != EventKind.WIN.value and kind_s != "win":
            continue
        wins = m.get("wins") or []
        if m.get("is_test") and not include_test:
            continue
        if not wins:
            continue
        base_date = _ts_date(m.get("ts") or m.get("date"))
        slug = m.get("slug") or ""
        outlet = _outlet_value(m.get("outlet"))
        asset_id = _norm_optional(m.get("asset_id"))
        source_id = m.get("source_id")
        card_id = m.get("card_id") or ""
        note = m.get("note") or ""

        filled_slug_from_card = False
        if cards_by_id is not None and card_id in cards_by_id:
            card_fields = win_fields_from_card(cards_by_id[card_id])
            if not slug and card_fields["slug"]:
                slug = card_fields["slug"]
                filled_slug_from_card = True
            if not outlet and card_fields["outlet"]:
                outlet = card_fields["outlet"]
            if asset_id is None and card_fields["asset_id"] is not None:
                asset_id = card_fields["asset_id"]
            if source_id in (None, "") and card_fields["source_id"] not in (None, ""):
                source_id = card_fields["source_id"]

        if filled_slug_from_card and note == slug:
            note = ""

        for w in wins:
            rows.append(
                {
                    "date": base_date,
                    "slug": slug,
                    "outlet": outlet,
                    "asset_id": asset_id,
                    "source_id": source_id if source_id not in (None, "") else None,
                    "win_type": _win_type_str(w),
                    "card_id": card_id,
                    "note": note,
                    "evidence_url": m.get("evidence_url"),
                    "archive_url": m.get("archive_url"),
                    "criterion_hint": m.get("criterion_hint") or "none",
                    "is_test": bool(m.get("is_test", False)),
                    "prev_hash": m.get("prev_hash"),
                    "row_hash": m.get("row_hash"),
                }
            )
    # stable chronological-ish order
    rows.sort(key=lambda r: (r["date"], r.get("card_id") or "", r["win_type"]))
    return rows


def win_row_owner() -> str:
    """Explicit dossier owner label (no org_id)."""
    return _OWNER


__all__ = [
    "WIN_SHEET_COLUMNS",
    "aggregate_wins",
    "win_fields_from_card",
    "win_row_owner",
]
