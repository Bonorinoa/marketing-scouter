"""Auditable §9 scoring + S_safe kill gates + queue decision (DA).

Canonical formula (MVP-DESIGN §9 / observability-schema.md):
  S = 30*Fit + 20*Urgency + 15*FormatPrior + 20*Evidence + 15*DoorMatch - EffortPenalty

Likes, Buffer %, Feed SR %, and report:like folklore NEVER enter S.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence, Union

from src.models import (
    PROTECTED_STATES,
    QUEUE_CAP,
    REPLACE_MARGIN,
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

# ── Constants ────────────────────────────────────────────────────────────────

EVIDENCE_VALUES: dict[EvidenceGrade, float] = {
    EvidenceGrade.A: 1.0,
    EvidenceGrade.B: 0.6,
    EvidenceGrade.C: 0.0,
}

EFFORT_PENALTY_ALLOWED = frozenset({0.0, 10.0, 25.0})

FORMAT_PRIOR_LINKEDIN: dict[str, float] = {
    "carousel": 1.0,
    "doc": 1.0,
    "document": 1.0,
    "image+text": 0.7,
    "image_text": 0.7,
    "video": 0.7,
    "link-only": 0.4,
    "link_only": 0.4,
    "thin_text": 0.4,
    "thin-text": 0.4,
    "text": 0.4,
}

FORMAT_PRIOR_X: dict[str, float] = {
    "original": 1.0,
    "quote": 1.0,
    "copy_link": 1.0,
    "copy-link": 1.0,
    "mutual_reply": 1.0,
    "mutual-reply": 1.0,
    "substantive_reply": 0.7,
    "substantive-reply": 0.7,
    "reply": 0.7,
    "reply_farm": 0.4,
    "reply-farm": 0.4,
    "like_bait": 0.4,
    "like-bait": 0.4,
}

# Kill keyword banks (case-insensitive substring match on snippet / draft_hints text)
_PROMO_CTA_MARKERS = (
    "dm me",
    "dm for",
    "link in bio",
    "book a call",
    "book a demo",
    "buy now",
    "sign up now",
    "limited offer",
    "promo code",
    "use code",
    "soft cta",
)

_BAIT_MARKERS = (
    "congrats",
    "congratulations!",
    "emoji-bait",
    "emoji bait",
    "like-bait",
    "like bait",
    "engagement bait",
    "manipulative poll",
    "pod comment",
    "comment pod",
    "bot-comment",
    "bot comment",
    "pile-on",
    "pile on",
)

_FOLKLORE_MARKERS = (
    "golden hour",
    "golden-hour",
    "bookmark-bait",
    "bookmark bait",
    "bookmark=#1",
    "bookmark = #1",
    "hide link in reply",
    "hide-link-in-reply",
    "link tax",
    "report:like",
    "report∶like",
    "report/like",
    "premium-as-organic",
    "premium as organic",
    "premium organic multiplier",
    "buffer %",
    "feed sr",
    "feed sr %",
    "toy p_a",
    "vqv as organic",
)


@dataclass(frozen=True)
class QueueDecisionResult:
    """Outcome of queue_decision for Systems / telemetry."""

    decision: Decision
    replaced_card_id: Optional[str] = None


# ── Factor helpers ───────────────────────────────────────────────────────────


URGENCY_FRESH_HOURS = 48.0
URGENCY_FRESH_DROP = 0.4  # pinned in tests/test_urgency_decay_pin.py


def urgency_from_age_hours(
    age_hours: Optional[float],
    *,
    evergreen: bool = False,
) -> float:
    """Map opportunity age → Urgency on [0, 1].

    <48h → linear 1.0 → 0.6 (URGENCY_FRESH_DROP over URGENCY_FRESH_HOURS, continuous with the 2–7d step);
    2–7d → 0.6; evergreen / unknown → 0.3; stale (>7d cold) → 0.0.
    """
    if evergreen:
        return 0.3
    if age_hours is None:
        return 0.3  # unknown age treated as evergreen (soft), not invented ER
    if age_hours < 0:
        return 0.0
    if age_hours < URGENCY_FRESH_HOURS:
        # whole hours: S is stable within an hour, so re-scoring the same post seconds apart can't reorder it
        h = float(int(age_hours))
        return round(1.0 - URGENCY_FRESH_DROP * (h / URGENCY_FRESH_HOURS), 4)
    if age_hours <= 7.0 * 24.0:
        return 0.6
    return 0.0  # >7d cold / stale


def age_hours_from_created(
    created_at: Optional[datetime],
    *,
    now: Optional[datetime] = None,
) -> Optional[float]:
    """Hours since candidate.created_at; None if unknown."""
    if created_at is None:
        return None
    now = now or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0.0, (now - created_at).total_seconds() / 3600.0)


def evidence_value(grade: Union[EvidenceGrade, str, float]) -> float:
    if isinstance(grade, (int, float)):
        return float(grade)
    if isinstance(grade, str):
        grade = EvidenceGrade(grade)
    return EVIDENCE_VALUES[grade]


def format_prior_value(
    outlet: Union[Outlet, str],
    format_kind: str,
) -> float:
    """Playbook ordinal only ∈ {1.0, 0.7, 0.4}. Never Buffer % / Feed SR %."""
    outlet_s = outlet.value if isinstance(outlet, Outlet) else str(outlet).lower()
    key = format_kind.strip().lower().replace(" ", "_")
    table = FORMAT_PRIOR_LINKEDIN if outlet_s == "linkedin" else FORMAT_PRIOR_X
    if key not in table:
        # allow hyphen aliases already in tables; fallback thin/reply-farm
        alt = key.replace("_", "-")
        if alt in table:
            return table[alt]
        raise ValueError(
            f"Unknown format_kind={format_kind!r} for outlet={outlet_s}; "
            f"expected one of {sorted(set(table) | set(FORMAT_PRIOR_X) | set(FORMAT_PRIOR_LINKEDIN))}"
        )
    return table[key]


def door_match_value(
    *,
    voice_door: Union[VoiceDoor, str],
    intended_door: Optional[Union[VoiceDoor, str]] = None,
    mix_logos: bool = False,
) -> float:
    """DoorMatch: correct doorplate=1.0; mix logos=0.3; wrong door=0.0."""
    if mix_logos:
        return 0.3
    vd = voice_door.value if isinstance(voice_door, VoiceDoor) else str(voice_door)
    if intended_door is None:
        return 1.0
    intended = (
        intended_door.value if isinstance(intended_door, VoiceDoor) else str(intended_door)
    )
    return 1.0 if vd == intended else 0.0


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def normalize_effort_penalty(effort_penalty: float) -> float:
    ep = float(effort_penalty)
    if ep not in EFFORT_PENALTY_ALLOWED:
        # snap to nearest allowed bucket rather than inventing continuous penalties
        allowed = sorted(EFFORT_PENALTY_ALLOWED)
        ep = min(allowed, key=lambda a: abs(a - ep))
    return ep


# ── Public API ───────────────────────────────────────────────────────────────


def compute_factors(
    *,
    fit: float,
    urgency: Optional[float] = None,
    age_hours: Optional[float] = None,
    evergreen: bool = False,
    format_prior: Optional[float] = None,
    outlet: Optional[Union[Outlet, str]] = None,
    format_kind: Optional[str] = None,
    evidence: Union[EvidenceGrade, str, float] = EvidenceGrade.A,
    door_match: Optional[float] = None,
    voice_door: Optional[Union[VoiceDoor, str]] = None,
    intended_door: Optional[Union[VoiceDoor, str]] = None,
    mix_logos: bool = False,
    effort_penalty: float = 0.0,
    # Accepted but IGNORED for S (informational / display only):
    like_count: Optional[int] = None,  # noqa: ARG001 — never drives S
    reply_count: Optional[int] = None,  # soft T badge only; no invented ER
    quote_count: Optional[int] = None,
    comment_count: Optional[int] = None,
    t_status: Union[TStatus, str] = TStatus.UNKNOWN,
    buffer_pct: Optional[float] = None,  # noqa: ARG001 — folklore; ignored
    feed_sr_pct: Optional[float] = None,  # noqa: ARG001 — folklore; ignored
) -> ScoreFactors:
    """Build ScoreFactors for §9. Likes / Buffer% / Feed SR% are ignored."""
    _ = (like_count, buffer_pct, feed_sr_pct, reply_count, quote_count, comment_count, t_status)

    fit_v = clamp01(fit)

    if urgency is not None:
        urg_v = clamp01(urgency)
    else:
        urg_v = urgency_from_age_hours(age_hours, evergreen=evergreen)

    if format_prior is not None:
        fp_v = float(format_prior)
        if fp_v not in (1.0, 0.7, 0.4):
            # allow exact ordinals only; clamp to nearest playbook bucket
            fp_v = min((1.0, 0.7, 0.4), key=lambda a: abs(a - fp_v))
    elif outlet is not None and format_kind is not None:
        fp_v = format_prior_value(outlet, format_kind)
    else:
        fp_v = 0.7  # mid default when caller has not classified format yet

    ev_v = clamp01(evidence_value(evidence))

    if door_match is not None:
        dm_v = clamp01(door_match)
    elif voice_door is not None:
        dm_v = door_match_value(
            voice_door=voice_door,
            intended_door=intended_door,
            mix_logos=mix_logos,
        )
    else:
        dm_v = 1.0 if not mix_logos else 0.3

    ep_v = normalize_effort_penalty(effort_penalty)

    return ScoreFactors(
        Fit=fit_v,
        Urgency=urg_v,
        FormatPrior=fp_v,
        Evidence=ev_v,
        DoorMatch=dm_v,
        EffortPenalty=ep_v,
    )


def compute_S(factors: ScoreFactors) -> float:
    """§9 additive score. Fit empty (0) ⇒ S uses Fit=0; caller should not enqueue."""
    return (
        30.0 * factors.Fit
        + 20.0 * factors.Urgency
        + 15.0 * factors.FormatPrior
        + 20.0 * factors.Evidence
        + 15.0 * factors.DoorMatch
        - float(factors.EffortPenalty)
    )


def _hint_text(draft_hints: Optional[Mapping[str, Any]]) -> str:
    if not draft_hints:
        return ""
    parts: list[str] = []
    for key in ("draft_text", "text", "note", "title", "snippet", "raw"):
        v = draft_hints.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v)
    # also scan string values for keyword hits
    for v in draft_hints.values():
        if isinstance(v, str) and v.strip() and v not in parts:
            parts.append(v)
    return "\n".join(parts).lower()


def _as_evidence(v: Any) -> Optional[EvidenceGrade]:
    if v is None:
        return None
    if isinstance(v, EvidenceGrade):
        return v
    if isinstance(v, str):
        return EvidenceGrade(v)
    return None


def _slugs_from_hints(draft_hints: Optional[Mapping[str, Any]]) -> list[str]:
    if not draft_hints:
        return []
    slugs = draft_hints.get("slugs") or draft_hints.get("fit_slugs") or []
    if isinstance(slugs, str):
        return [s.strip() for s in slugs.split(",") if s.strip()]
    if isinstance(slugs, Sequence):
        return [str(s).strip() for s in slugs if str(s).strip()]
    return []


def s_safe_kill(
    candidate: Candidate,
    draft_hints: Optional[Mapping[str, Any]] = None,
) -> list[str]:
    """Hard kill gates. Empty list = pass.

    Kill ids: promo_cta | bait | folklore | empty_fit | evidence_c | door_mix
    """
    reasons: list[str] = []
    hints = dict(draft_hints or {})
    blob = " ".join(
        filter(
            None,
            [
                (candidate.title_or_snippet or "").lower(),
                (candidate.author or "").lower(),
                _hint_text(hints),
            ],
        )
    )

    if any(m in blob for m in _PROMO_CTA_MARKERS):
        reasons.append("promo_cta")
    if any(m in blob for m in _BAIT_MARKERS):
        reasons.append("bait")
    if any(m in blob for m in _FOLKLORE_MARKERS):
        reasons.append("folklore")

    slugs = _slugs_from_hints(hints)
    fit_explicit = hints.get("fit")
    if fit_explicit is not None:
        try:
            if float(fit_explicit) <= 0.0:
                reasons.append("empty_fit")
        except (TypeError, ValueError):
            pass
    elif "slugs" in hints or "fit_slugs" in hints:
        if not slugs:
            reasons.append("empty_fit")

    grade = _as_evidence(hints.get("evidence_grade") or hints.get("evidence"))
    if grade is EvidenceGrade.C:
        reasons.append("evidence_c")

    # door_mix: explicit flag, or voice_door conflict + mix_logos, or lab plug on civic
    if hints.get("door_mix") or hints.get("mix_logos"):
        reasons.append("door_mix")
    else:
        voice = hints.get("voice_door")
        intended = hints.get("intended_door")
        if voice is not None and intended is not None:
            vv = voice.value if isinstance(voice, VoiceDoor) else str(voice)
            ii = intended.value if isinstance(intended, VoiceDoor) else str(intended)
            if vv != ii:
                reasons.append("door_mix")
        # civic drafts must not plug the lab
        draft = (hints.get("draft_text") or "").lower()
        vd = hints.get("voice_door")
        vd_s = vd.value if isinstance(vd, VoiceDoor) else (str(vd) if vd else "")
        if vd_s == VoiceDoor.AUGUSTO_CIVIC.value and any(
            plug in draft for plug in ("econllm lab", "econllm.com", "join our lab")
        ):
            reasons.append("door_mix")

    # stable unique order
    seen: set[str] = set()
    ordered: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            ordered.append(r)
    return ordered


def _is_protected(card: ScoredCard) -> bool:
    state = card.state
    if isinstance(state, CardState):
        return state in PROTECTED_STATES
    return CardState(str(state)) in PROTECTED_STATES


def _status_num(url: str) -> int:
    import re as _re
    m = _re.search(r"/status(?:es)?/(\d{1,25})", url or "")
    return int(m.group(1)) if m else 0


def queue_decision(
    new_S: float,
    open_cards: list[ScoredCard],
    *,
    queue_cap: int = QUEUE_CAP,
    replace_margin: float = REPLACE_MARGIN,
) -> QueueDecisionResult:
    """Cap-7 replace policy.

    - Under cap → enqueue
    - At/over cap → replace lowest *unprotected* only if
      new_S >= min(S_unprotected) + REPLACE_MARGIN (default 10)
    - Protected states (drafting / awaiting_approval / pinned) never auto-dropped
    - Otherwise → drop (caller may shelf to watch separately)
    """
    open_n = len(open_cards)
    if open_n < queue_cap:
        return QueueDecisionResult(decision=Decision.ENQUEUE)

    unprotected = [c for c in open_cards if not _is_protected(c)]
    if not unprotected:
        # cannot displace protected cards
        return QueueDecisionResult(decision=Decision.DROP)

    # equal S: the newest X status ID goes first, so the oldest status keeps its place
    lowest = min(unprotected, key=lambda c: (c.S, -_status_num(c.url), c.card_id))
    threshold = float(lowest.S) + float(replace_margin)
    if float(new_S) >= threshold:
        return QueueDecisionResult(
            decision=Decision.REPLACE,
            replaced_card_id=lowest.card_id,
        )
    return QueueDecisionResult(decision=Decision.DROP)


__all__ = [
    "QueueDecisionResult",
    "compute_factors",
    "compute_S",
    "s_safe_kill",
    "queue_decision",
    "urgency_from_age_hours",
    "age_hours_from_created",
    "format_prior_value",
    "evidence_value",
    "door_match_value",
]
