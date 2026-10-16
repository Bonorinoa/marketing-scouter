"""Card-level scoring bridge — prefers DA src.scorer (compute_factors → compute_S → queue_decision).

Fit empty → 0 → no card; Evidence C out; likes never drive S.
"""

from __future__ import annotations

from typing import Optional

from .fit import door_for_slugs, match_slugs_from_text
from .models import (
    Candidate,
    CardState,
    Decision,
    EvidenceGrade,
    InventoryAsset,
    MoveType,
    Outlet,
    ScoreFactors,
    ScoredCard,
    TStatus,
    VoiceDoor,
)
from .scorer import (
    QueueDecisionResult,
    age_hours_from_created,
    compute_S,
    compute_factors,
    queue_decision as da_queue_decision,
    s_safe_kill,
)


def _default_move(outlet: Outlet) -> MoveType:
    return MoveType.REPLY if outlet == Outlet.X else MoveType.COMMENT


def _format_kind(outlet: Outlet, move: MoveType, meta: dict | None) -> str:
    meta = meta or {}
    fmt = (meta.get("format") or "").lower().replace(" ", "_")
    if outlet == Outlet.LINKEDIN:
        if fmt in ("carousel", "doc", "document", "image+text", "image_text", "video"):
            return fmt if fmt != "document" else "doc"
        return "text"
    if move == MoveType.QUOTE:
        return "quote"
    if move == MoveType.ORIGINAL:
        return "original"
    return "substantive_reply"


def _playbook_ids(outlet: Outlet, move: MoveType) -> list[str]:
    if outlet == Outlet.X:
        if move == MoveType.REPLY:
            return ["X:reply-interject", "X:copy-link-framing"]
        if move == MoveType.QUOTE:
            return ["X:quote-claim-link", "X:QuoteWeight"]
        return ["X:original-rare"]
    if move == MoveType.COMMENT:
        return ["LI:substantive-comment", "LI:anti-slop"]
    return ["LI:results-discussion", "LI:anti-skip"]


def _resolve_slugs(
    candidate: Candidate,
    asset: InventoryAsset,
    matched_slugs: list[str] | None,
) -> list[str]:
    if matched_slugs is not None:
        return list(matched_slugs)
    slugs = match_slugs_from_text(
        candidate.title_or_snippet or "",
        candidate_slugs=asset.slugs or None,
    )
    if asset.slugs:
        inter = [s for s in slugs if s in asset.slugs]
        if inter:
            return inter
    return slugs


def score_candidate(
    candidate: Candidate,
    asset: InventoryAsset,
    *,
    matched_slugs: list[str] | None = None,
    voice_door: VoiceDoor | None = None,
    move: MoveType | None = None,
    fit_override: float | None = None,
) -> tuple[Optional[ScoredCard], list[str], Optional[ScoreFactors]]:
    """Score candidate vs asset using DA scorer primitives.

    Returns (card_or_None, kill_reasons, factors_or_None).
    """
    slugs = _resolve_slugs(candidate, asset, matched_slugs)
    move = move or _default_move(candidate.outlet)
    door = voice_door or (door_for_slugs(slugs) if slugs else VoiceDoor.ECONLLM)
    intended = door_for_slugs(slugs) if slugs else door

    # Fit: empty → 0
    if not slugs:
        fit_val = 0.0
    elif len(slugs) >= 2:
        fit_val = 1.0
    else:
        fit_val = 0.85
    if fit_override is not None and slugs:  # graded Fit (MS_FIT_GRADED=1): claim 1.0 / topic 0.5
        fit_val = float(fit_override)

    draft_hints = {
        "slugs": slugs,
        "fit": fit_val,
        "evidence_grade": asset.evidence_grade.value
        if isinstance(asset.evidence_grade, EvidenceGrade)
        else str(asset.evidence_grade),
        "voice_door": door,
        "intended_door": intended,
        "title": candidate.title_or_snippet,
        "snippet": candidate.title_or_snippet,
    }

    kills = s_safe_kill(candidate, draft_hints)
    # Also hard-stop Evidence C / empty fit even if hint path missed
    if fit_val <= 0 and "empty_fit" not in kills:
        kills = list(kills) + ["empty_fit"]
    if asset.evidence_grade == EvidenceGrade.C and "evidence_c" not in kills:
        kills = list(kills) + ["evidence_c"]

    if kills:
        factors = None
        if fit_val <= 0 or "empty_fit" in kills:
            factors = ScoreFactors(Fit=0.0)
        elif "evidence_c" in kills:
            factors = ScoreFactors(Fit=fit_val, Evidence=0.0)
        return None, kills, factors

    age_h = age_hours_from_created(candidate.created_at)
    factors = compute_factors(
        fit=fit_val,
        age_hours=age_h,
        outlet=candidate.outlet,
        format_kind=_format_kind(candidate.outlet, move, candidate.raw_meta),
        evidence=asset.evidence_grade,
        voice_door=door,
        intended_door=intended,
        effort_penalty=0.0 if move in (MoveType.REPLY, MoveType.COMMENT, MoveType.QUOTE) else 10.0,
        like_count=candidate.like_count,  # ignored inside compute_factors
        reply_count=candidate.reply_count,
        quote_count=candidate.quote_count,
        comment_count=candidate.comment_count,
        t_status=candidate.T_status,
    )
    s = round(compute_S(factors), 2)

    t_status = candidate.T_status
    if candidate.outlet == Outlet.LINKEDIN and candidate.comment_count is None:
        t_status = TStatus.UNKNOWN
    elif candidate.outlet == Outlet.X and (
        candidate.reply_count is not None or candidate.quote_count is not None
    ):
        t_status = TStatus.OK

    card = ScoredCard(
        candidate_id=candidate.candidate_id,
        asset_id=asset.asset_id,
        outlet=candidate.outlet,
        url=candidate.url,
        title_or_snippet=candidate.title_or_snippet,
        author=candidate.author,
        slugs=slugs,
        voice_door=door,
        move_type=move,
        draft_text="",
        S=s,
        factors=factors,
        T_status=t_status,
        state=CardState.OPEN,
        playbook_rule_ids=_playbook_ids(candidate.outlet, move),
        like_count_info=candidate.like_count,
    )
    return card, [], factors


def queue_decision(
    new_card: ScoredCard,
    open_cards: list[ScoredCard],
) -> tuple[Decision, Optional[str]]:
    """Adapter over DA queue_decision(new_S, open_cards)."""
    same = [
        c
        for c in open_cards
        if c.outlet == new_card.outlet
        and c.state
        in {
            CardState.OPEN,
            CardState.DRAFTING,
            CardState.AWAITING_APPROVAL,
            CardState.PINNED,
        }
    ]
    result: QueueDecisionResult = da_queue_decision(new_card.S, same)
    # Soft watch shelf when drop + weak urgency / strong fit
    if (
        result.decision == Decision.DROP
        and new_card.factors.Urgency < 0.5
        and new_card.factors.Fit >= 0.7
    ):
        return Decision.WATCH, None
    return result.decision, result.replaced_card_id


# Re-exports for tests / UI
__all__ = [
    "score_candidate",
    "queue_decision",
    "s_safe_kill",
    "compute_factors",
    "compute_S",
]
