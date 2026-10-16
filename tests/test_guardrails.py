"""Product-gate tests: Fit empty, Evidence C, likes ignored, cap-7."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.models import (
    AdapterId,
    Candidate,
    CardState,
    Decision,
    EvidenceGrade,
    InventoryAsset,
    Outlet,
    ScoredCard,
    TStatus,
)
from src.score import queue_decision, score_candidate
from src.scorer import compute_S, compute_factors


def _asset(**kw) -> InventoryAsset:
    base = dict(
        asset_id="a1",
        title="t",
        slugs=["sca-nonweird"],
        evidence_grade=EvidenceGrade.A,
        one_line_claim="claim",
    )
    base.update(kw)
    return InventoryAsset(**base)


def _cand(**kw) -> Candidate:
    base = dict(
        adapter=AdapterId.MANUAL_PASTE,
        outlet=Outlet.X,
        url="https://x.com/fixture_user_62/status/1",
        title_or_snippet="LLM synthetic subjects WEIRD cultural agents",
        created_at=datetime.now(timezone.utc) - timedelta(hours=6),
        reply_count=4,
        quote_count=1,
        like_count=99999,
        T_status=TStatus.OK,
    )
    base.update(kw)
    return Candidate(**base)


def test_fit_empty_no_card():
    card, kills, factors = score_candidate(
        _cand(title_or_snippet="best pasta in rome"),
        _asset(),
        matched_slugs=[],
    )
    assert card is None
    assert "empty_fit" in kills or "fit_empty" in kills or any("fit" in k for k in kills)
    assert factors is None or factors.Fit == 0


def test_evidence_c_no_card():
    card, kills, _ = score_candidate(
        _cand(),
        _asset(evidence_grade=EvidenceGrade.C),
        matched_slugs=["sca-nonweird"],
    )
    assert card is None
    assert any("evidence" in k for k in kills)


def test_likes_do_not_affect_S():
    a = _asset()
    c0 = _cand(like_count=0)
    c1 = _cand(like_count=10_000_000)
    card0, k0, f0 = score_candidate(c0, a, matched_slugs=["sca-nonweird"])
    card1, k1, f1 = score_candidate(c1, a, matched_slugs=["sca-nonweird"])
    assert not k0 and not k1
    assert card0 and card1
    assert card0.S == card1.S
    assert f0.model_dump() == f1.model_dump()


def test_cap7_replace_margin():
    open_cards = [
        ScoredCard(
            card_id=f"c{i}",
            candidate_id=f"k{i}",
            asset_id="a1",
            outlet=Outlet.X,
            url=f"https://x.com/fixture_user_62/status/{i}",
            S=40.0 + i,
            state=CardState.OPEN,
        )
        for i in range(7)
    ]
    new = ScoredCard(
        card_id="new",
        candidate_id="kn",
        asset_id="a1",
        outlet=Outlet.X,
        url="https://x.com/fixture_user_62/status/99",
        S=40.0 + 10 - 0.1,
        state=CardState.OPEN,
    )
    d, rid = queue_decision(new, open_cards)
    assert d == Decision.DROP
    new.S = 40.0 + 10
    d2, rid2 = queue_decision(new, open_cards)
    assert d2 == Decision.REPLACE
    assert rid2 == "c0"


def test_protected_not_replaced():
    open_cards = [
        ScoredCard(
            card_id="prot",
            candidate_id="k0",
            asset_id="a1",
            outlet=Outlet.X,
            url="https://x.com/fixture_user_62/status/0",
            S=1.0,
            state=CardState.PINNED,
        )
    ] + [
        ScoredCard(
            card_id=f"c{i}",
            candidate_id=f"k{i}",
            asset_id="a1",
            outlet=Outlet.X,
            url=f"https://x.com/fixture_user_62/status/{i}",
            S=50.0,
            state=CardState.OPEN,
        )
        for i in range(1, 7)
    ]
    new = ScoredCard(
        card_id="new",
        candidate_id="kn",
        asset_id="a1",
        outlet=Outlet.X,
        url="https://x.com/fixture_user_62/status/99",
        S=999.0,
        state=CardState.OPEN,
    )
    d, rid = queue_decision(new, open_cards)
    assert d == Decision.REPLACE
    assert rid != "prot"
