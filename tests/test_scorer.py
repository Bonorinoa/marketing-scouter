"""DA scorer tests — §9 formula, kill gates, queue replace policy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models import (
    PROTECTED_STATES,
    QUEUE_CAP,
    REPLACE_MARGIN,
    AdapterId,
    Candidate,
    CardState,
    Decision,
    EvidenceGrade,
    Outlet,
    ScoreFactors,
    ScoredCard,
    TStatus,
    VoiceDoor,
)
from src.scorer import (
    compute_S,
    compute_factors,
    queue_decision,
    s_safe_kill,
)
from src.win_export import WIN_SHEET_COLUMNS, aggregate_wins

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "seed_score_fixtures.json"  # made-up; data/ copy is gitignored


def _candidate(**kwargs) -> Candidate:
    defaults = dict(
        adapter=AdapterId.MANUAL_PASTE,
        outlet=Outlet.X,
        url="https://x.com/fixture_user_68/status/1",
        title_or_snippet="neutral thread about methods",
    )
    defaults.update(kwargs)
    return Candidate(**defaults)


def _card(*, S: float, state: CardState = CardState.OPEN, card_id: str = "c") -> ScoredCard:
    return ScoredCard(
        card_id=card_id,
        candidate_id="cand_x",
        asset_id="asset_x",
        outlet=Outlet.X,
        url="https://x.com/fixture_user_68/status/9",
        S=S,
        state=state,
    )


# ── Fit / Evidence / likes ───────────────────────────────────────────────────


def test_empty_fit_yields_zero_fit_and_no_enqueue_path():
    factors = compute_factors(
        fit=0.0,
        age_hours=6,
        format_prior=0.7,
        evidence=EvidenceGrade.A,
        door_match=1.0,
        effort_penalty=0,
    )
    assert factors.Fit == 0.0
    s = compute_S(factors)
    # S is mathematically defined, but empty Fit is a hard "no card" path
    assert s == pytest.approx(64.5)  # 6h old: U = 1 - 0.4*6/48 = 0.95
    kills = s_safe_kill(
        _candidate(),
        draft_hints={"slugs": [], "evidence_grade": "A"},
    )
    assert "empty_fit" in kills
    # queue path: callers must not enqueue when Fit empty / kill non-empty
    assert kills  # no-enqueue path


def test_evidence_c_killed():
    kills = s_safe_kill(
        _candidate(title_or_snippet="solid methods thread on SCA"),
        draft_hints={
            "slugs": ["sca-nonweird"],
            "evidence_grade": EvidenceGrade.C,
        },
    )
    assert "evidence_c" in kills
    factors = compute_factors(
        fit=1.0,
        age_hours=12,
        format_prior=0.7,
        evidence=EvidenceGrade.C,
        door_match=1.0,
    )
    assert factors.Evidence == 0.0


def test_likes_do_not_change_S():
    base = dict(
        fit=0.8,
        age_hours=24,
        format_prior=1.0,
        evidence=EvidenceGrade.A,
        door_match=1.0,
        effort_penalty=0,
    )
    f0 = compute_factors(**base, like_count=0)
    f1 = compute_factors(**base, like_count=50_000)
    assert f0.model_dump() == f1.model_dump()
    assert compute_S(f0) == compute_S(f1)
    # Buffer / Feed SR folklore also ignored
    f2 = compute_factors(**base, buffer_pct=21.77, feed_sr_pct=3.52, like_count=99)
    assert compute_S(f2) == compute_S(f0)


# ── Queue replace / protect ──────────────────────────────────────────────────


def test_replace_only_when_new_s_meets_margin():
    open_cards = [_card(S=50.0 + i, card_id=f"o{i}", state=CardState.OPEN) for i in range(QUEUE_CAP)]
    # min unprotected S = 50; need >= 60
    assert min(c.S for c in open_cards) == 50.0
    drop = queue_decision(50.0 + REPLACE_MARGIN - 0.01, open_cards)
    assert drop.decision == Decision.DROP
    assert drop.replaced_card_id is None

    rep = queue_decision(50.0 + REPLACE_MARGIN, open_cards)
    assert rep.decision == Decision.REPLACE
    assert rep.replaced_card_id == "o0"  # lowest S


def test_protected_states_never_auto_dropped():
    # Fill queue with only protected cards + one weak open
    protected = [
        _card(S=10.0, state=CardState.DRAFTING, card_id="draft"),
        _card(S=5.0, state=CardState.AWAITING_APPROVAL, card_id="await"),
        _card(S=1.0, state=CardState.PINNED, card_id="pin"),
    ]
    opens = [
        _card(S=40.0, state=CardState.OPEN, card_id="open1"),
        _card(S=41.0, state=CardState.OPEN, card_id="open2"),
        _card(S=42.0, state=CardState.OPEN, card_id="open3"),
        _card(S=43.0, state=CardState.OPEN, card_id="open4"),
    ]
    full = protected + opens
    assert len(full) == QUEUE_CAP
    for st in PROTECTED_STATES:
        assert st in {CardState.DRAFTING, CardState.AWAITING_APPROVAL, CardState.PINNED}

    result = queue_decision(40.0 + REPLACE_MARGIN, full)
    assert result.decision == Decision.REPLACE
    assert result.replaced_card_id == "open1"
    assert result.replaced_card_id not in {"draft", "await", "pin"}

    # All protected → cannot replace anyone
    only_prot = [
        _card(S=float(i), state=st, card_id=f"p{i}")
        for i, st in enumerate(
            [
                CardState.DRAFTING,
                CardState.AWAITING_APPROVAL,
                CardState.PINNED,
                CardState.DRAFTING,
                CardState.PINNED,
                CardState.AWAITING_APPROVAL,
                CardState.DRAFTING,
            ]
        )
    ]
    blocked = queue_decision(999.0, only_prot)
    assert blocked.decision == Decision.DROP
    assert blocked.replaced_card_id is None


def test_enqueue_under_cap():
    cards = [_card(S=80.0, card_id="a")]
    r = queue_decision(10.0, cards)
    assert r.decision == Decision.ENQUEUE
    assert r.replaced_card_id is None


# ── Folklore / bait kill ─────────────────────────────────────────────────────


def test_folklore_kill_reason_on_bait_keywords():
    cand = _candidate(
        title_or_snippet="Post in the golden hour and use report:like math for Premium organic multiplier"
    )
    kills = s_safe_kill(cand, draft_hints={"slugs": ["sca-nonweird"], "evidence_grade": "A"})
    assert "folklore" in kills

    bait = _candidate(title_or_snippet="Congrats on the launch! emoji-bait engagement bait thread")
    kills2 = s_safe_kill(bait, draft_hints={"slugs": ["sca-nonweird"], "evidence_grade": "A"})
    assert "bait" in kills2


def test_promo_cta_kill():
    cand = _candidate(title_or_snippet="DM me for the deck — book a demo today")
    kills = s_safe_kill(cand, draft_hints={"slugs": ["sca-nonweird"], "evidence_grade": "A"})
    assert "promo_cta" in kills


# ── Formula + fixtures ───────────────────────────────────────────────────────


def test_compute_s_formula():
    f = ScoreFactors(
        Fit=1.0, Urgency=1.0, FormatPrior=0.7, Evidence=1.0, DoorMatch=1.0, EffortPenalty=0.0
    )
    assert compute_S(f) == pytest.approx(95.5)


def test_seed_fixtures_match_expected():
    data = json.loads(FIXTURES.read_text())
    for fx in data["fixtures"]:
        inp = fx["score_inputs"]
        factors = compute_factors(
            fit=inp["fit"],
            age_hours=inp.get("age_hours"),
            format_kind=inp.get("format_kind"),
            outlet=fx["candidate"]["outlet"],
            evidence=inp["evidence"],
            voice_door=inp.get("voice_door"),
            intended_door=inp.get("intended_door"),
            effort_penalty=inp.get("effort_penalty", 0),
            like_count=fx["candidate"].get("like_count"),
        )
        exp = fx["expected_factors"]
        assert factors.Fit == pytest.approx(exp["Fit"]), fx["id"]
        assert factors.Urgency == pytest.approx(exp["Urgency"]), fx["id"]
        assert factors.FormatPrior == pytest.approx(exp["FormatPrior"]), fx["id"]
        assert factors.Evidence == pytest.approx(exp["Evidence"]), fx["id"]
        assert factors.DoorMatch == pytest.approx(exp["DoorMatch"]), fx["id"]
        assert factors.EffortPenalty == pytest.approx(exp["EffortPenalty"]), fx["id"]
        assert compute_S(factors) == pytest.approx(fx["expected_S"]), fx["id"]
        if "kill_reasons" in fx:
            kills = s_safe_kill(
                _candidate(
                    outlet=Outlet(fx["candidate"]["outlet"]),
                    title_or_snippet=fx["candidate"]["title_or_snippet"],
                    url=fx["candidate"]["url"],
                    adapter=AdapterId(fx["candidate"]["adapter"]),
                ),
                draft_hints={
                    "slugs": fx["asset"].get("slugs") or [],
                    "evidence_grade": fx["asset"].get("evidence_grade", "A"),
                    "fit": inp["fit"],
                },
            )
            for kr in fx["kill_reasons"]:
                assert kr in kills, (fx["id"], kills)


def test_win_export_columns_and_aggregate():
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
    events = [
        {
            "kind": "win",
            "ts": "2026-09-20T15:00:00+00:00",
            "slug": "sca-nonweird",
            "outlet": "x",
            "asset_id": "asset_sca_nonweird",
            "source_id": None,
            "card_id": "card_abc",
            "wins": ["claim_named_reply", "evidence_ab"],
            "note": "peer named the SCA claim",
        },
        {"kind": "scored", "S": 90.0},  # ignored
    ]
    rows = aggregate_wins(events)
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-09-20"
    assert rows[0]["win_type"] == "claim_named_reply"
    assert rows[0]["asset_id"] == "asset_sca_nonweird"
    assert "org_id" not in rows[0]
    assert set(rows[0].keys()) == set(WIN_SHEET_COLUMNS)
    assert list(rows[0].keys()) == WIN_SHEET_COLUMNS
