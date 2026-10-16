"""Win export identity and legacy-card backfill tests."""

from __future__ import annotations

from src.models import EventKind, Outlet, ScoredCard, ScoutEvent, WinSignal
from src.win_export import WIN_SHEET_COLUMNS, aggregate_wins, win_fields_from_card


def _card() -> ScoredCard:
    return ScoredCard(
        card_id="card_legacy",
        candidate_id="candidate_legacy",
        asset_id="asset_sca",
        outlet=Outlet.LINKEDIN,
        url="https://www.linkedin.com/posts/example-1",
        slugs=["sca-nonweird", "verification-local-context"],
    )


def test_win_sheet_column_order_includes_asset_id():
    assert WIN_SHEET_COLUMNS == [
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


def test_win_fields_from_card_uses_first_slug_and_outlet_value():
    assert win_fields_from_card(_card()) == {
        "slug": "sca-nonweird",
        "outlet": "linkedin",
        "asset_id": "asset_sca",
        "source_id": None,
    }


def test_win_fields_from_card_omits_asset_id_when_absent():
    """General / profile-wide: no asset on card → asset_id null."""
    fields = win_fields_from_card(
        {
            "slugs": ["sca-nonweird"],
            "outlet": "x",
            # no asset_id key
        }
    )
    assert fields["asset_id"] is None


def test_aggregate_backfills_missing_identity_from_card_and_cleans_legacy_note():
    event = ScoutEvent(
        kind=EventKind.WIN,
        card_id="card_legacy",
        wins=[WinSignal.CLAIM_NAMED_REPLY],
        note="sca-nonweird",
    )

    rows = aggregate_wins([event], cards_by_id={"card_legacy": _card()})

    assert rows[0]["slug"] == "sca-nonweird"
    assert rows[0]["outlet"] == "linkedin"
    assert rows[0]["asset_id"] == "asset_sca"
    assert rows[0]["source_id"] is None
    assert rows[0]["note"] == ""
    assert list(rows[0].keys()) == WIN_SHEET_COLUMNS


def test_aggregate_prefers_event_asset_id_over_card():
    event = {
        "kind": "win",
        "ts": "2026-10-07T12:00:00+00:00",
        "card_id": "card_legacy",
        "slug": "sca-nonweird",
        "outlet": "x",
        "asset_id": "asset_from_event",
        "wins": ["claim_named_reply"],
        "note": "",
    }
    rows = aggregate_wins([event], cards_by_id={"card_legacy": _card()})
    assert rows[0]["asset_id"] == "asset_from_event"


def test_spa_win_columns_mirror_sheet_schema():
    """web/ Wins table columns must mirror WIN_SHEET_COLUMNS (incl. asset_id) — chrome cannot drift."""
    import re
    from pathlib import Path
    ts = (Path(__file__).resolve().parents[1] / "web" / "src" / "api" / "types.ts").read_text()
    cols = re.search(r"WIN_COLUMNS = \[([^\]]+)\]", ts).group(1)
    spa = [c.strip().strip('"') for c in cols.split(",")]
    # TODO(web owner): SPA still shows the first 8 columns; evidence columns not yet in the Wins table.
    assert spa == WIN_SHEET_COLUMNS[: len(spa)] and len(spa) >= 8
