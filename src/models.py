"""Pydantic v2 data models — Market Scouter observability schema."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid4().hex[:12]}" if prefix else uuid4().hex[:12]


# ── Enums ────────────────────────────────────────────────────────────────────


class AdapterId(str, Enum):
    MANUAL_PASTE = "manual.paste"
    X_SEED = "x.seed"
    X_OFFICIAL = "x.official"
    LI_GOOGLE_SITE = "li.google_site"
    LI_PASTE = "li.paste"


class Outlet(str, Enum):
    X = "x"
    LINKEDIN = "linkedin"


class Modality(str, Enum):
    TEXT = "text"
    TEXT_IMAGE = "text+image"


class DoorArchive(str, Enum):
    ECONLLM = "EconLLM"
    AUGUSTO_CIVIC = "Augusto-civic"


class VoiceDoor(str, Enum):
    ECONLLM = "EconLLM"
    AUGUSTO_CIVIC = "Augusto-civic"


class OpedStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    PENDING = "pending"
    PUBLISHED = "published"
    ATOMIZE = "atomize"


class EvidenceGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class TStatus(str, Enum):
    OK = "ok"
    UNKNOWN = "unknown"


class MoveType(str, Enum):
    REPLY = "reply"
    QUOTE = "quote"
    COMMENT = "comment"
    ORIGINAL = "original"
    SKIP = "skip"


class CriterionHint(str, Enum):
    """O-1A criterion hint. Mirrors data/criterion_hints.json `values` (test-enforced). A hint only."""

    ORIGINAL_CONTRIBUTION = "original_contribution"
    PUBLISHED_ABOUT = "published_about"
    SCHOLARLY_AUTHORSHIP = "scholarly_authorship"
    JUDGING = "judging"
    NONE = "none"


class CardState(str, Enum):
    OPEN = "open"
    DRAFTING = "drafting"
    AWAITING_APPROVAL = "awaiting_approval"
    PINNED = "pinned"
    WATCH = "watch"
    DONE = "done"
    SKIPPED = "skipped"
    ARCHIVED_PRE_REDESIGN = "archived_pre_redesign"  # kept, never queued/counted/replaced
    ARCHIVED_OFFTOPIC_1215 = "archived_offtopic_1215"  # same treatment as archived_pre_redesign
    ARCHIVED_AT_RESET = "archived_at_reset"  # test-copy queue emptied before an AT rerun; same treatment


ARCHIVED_STATES = frozenset({CardState.ARCHIVED_PRE_REDESIGN, CardState.ARCHIVED_OFFTOPIC_1215, CardState.ARCHIVED_AT_RESET})

PROTECTED_STATES = frozenset(
    {CardState.DRAFTING, CardState.AWAITING_APPROVAL, CardState.PINNED}
)


class EventKind(str, Enum):
    DISCOVERED = "discovered"
    KILLED = "killed"
    SCORED = "scored"
    DECISION = "decision"
    HUMAN = "human"
    WIN = "win"
    POST_DEDUPE = "post_dedupe"


class Decision(str, Enum):
    ENQUEUE = "enqueue"
    REPLACE = "replace"
    DROP = "drop"
    WATCH = "watch"


class HumanAction(str, Enum):
    ACTED = "acted"
    EDITED = "edited"
    SKIPPED = "skipped"


class WinSignal(str, Enum):
    CLAIM_NAMED_REPLY = "claim_named_reply"
    WARM_INTRO = "warm_intro"
    EVIDENCE_AB = "evidence_ab"


# ── Models ───────────────────────────────────────────────────────────────────


class FitSlug(BaseModel):
    slug: str
    claim_one_liner: str
    use_when: str
    door: VoiceDoor = VoiceDoor.ECONLLM


class InventoryAsset(BaseModel):
    asset_id: str = Field(default_factory=lambda: _new_id("asset_"))
    title: str
    url: Optional[str] = None
    modality: Modality = Modality.TEXT
    slugs: list[str] = Field(default_factory=list)
    door_archive: DoorArchive = DoorArchive.ECONLLM
    oped_status: Optional[OpedStatus] = None
    evidence_grade: EvidenceGrade = EvidenceGrade.A
    one_line_claim: Optional[str] = None
    notes: Optional[str] = None
    surface: Optional[str] = None  # from inventory (seed_inventory.json); never URL-inferred
    tone_hint: Optional[str] = None  # from inventory; card chrome shows it verbatim
    caveat: Optional[str] = None  # verbatim limit sentence; drafts must carry it (gate: caveat_dropped)
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("slugs")
    @classmethod
    def _normalize_slugs(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s and s.strip()]


class Candidate(BaseModel):
    candidate_id: str = Field(default_factory=lambda: _new_id("cand_"))
    adapter: AdapterId
    outlet: Outlet
    url: str
    title_or_snippet: str = ""
    author: Optional[str] = None
    created_at: Optional[datetime] = None
    reply_count: Optional[int] = None
    quote_count: Optional[int] = None
    comment_count: Optional[int] = None
    like_count: Optional[int] = None  # informational only — never drives S
    raw_meta: dict[str, Any] = Field(default_factory=dict)
    T_status: TStatus = TStatus.UNKNOWN


class ScoreFactors(BaseModel):
    Fit: float = 0.0
    Urgency: float = 0.0
    FormatPrior: float = 0.0
    Evidence: float = 0.0
    DoorMatch: float = 0.0
    EffortPenalty: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class ScoredCard(BaseModel):
    card_id: str = Field(default_factory=lambda: _new_id("card_"))
    candidate_id: str
    asset_id: str
    outlet: Outlet
    url: str
    title_or_snippet: str = ""
    author: Optional[str] = None
    slugs: list[str] = Field(default_factory=list)
    voice_door: VoiceDoor = VoiceDoor.ECONLLM
    move_type: MoveType = MoveType.REPLY
    draft_text: str = ""
    S: float = 0.0
    factors: ScoreFactors = Field(default_factory=ScoreFactors)
    T_status: TStatus = TStatus.UNKNOWN
    state: CardState = CardState.OPEN
    playbook_rule_ids: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)  # e.g. brand_post: label only, never in S
    post_dedupe: Optional[dict] = None  # one card per post: {key, dropped: n, dropped_assets: [...]}
    fit_trace: Optional[dict] = None  # Jev grade: {p: {claim,topic,none}, decision_rule, confidence}
    fit_level: Optional[str] = None  # graded modes: claim | topic | none (word-only route); never in S
    like_count_info: Optional[int] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ScoutRun(BaseModel):
    scout_run_id: str = Field(default_factory=lambda: _new_id("run_"))
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: Optional[datetime] = None
    adapter: AdapterId
    query_or_slug: Optional[str] = None
    query: Optional[str] = None
    candidates_n: int = 0


class ScoutEvent(BaseModel):
    scout_run_id: Optional[str] = None
    ts: datetime = Field(default_factory=_utcnow)
    kind: EventKind
    candidate_id: Optional[str] = None
    card_id: Optional[str] = None
    kill_reasons: Optional[list[str]] = None
    factors: Optional[dict[str, float]] = None
    S: Optional[float] = None
    decision: Optional[Decision] = None
    replaced_card_id: Optional[str] = None
    human: Optional[HumanAction] = None
    wins: Optional[list[WinSignal]] = None
    slug: Optional[str] = None
    outlet: Optional[Outlet] = None
    asset_id: Optional[str] = None
    source_id: Optional[str] = None
    # discovery provenance (server-validated short tokens from POST /intake/x; never sets is_test/status)
    query_id: Optional[str] = None
    lane: Optional[str] = None
    source_tag: Optional[str] = None
    note: Optional[str] = None
    # Wins as evidence
    evidence_url: Optional[str] = None
    archive_url: Optional[str] = None
    archive_status: Optional[str] = None
    criterion_hint: Optional[CriterionHint] = None
    is_test: bool = False
    prev_hash: Optional[str] = None
    row_hash: Optional[str] = None

    def to_jsonl_dict(self) -> dict[str, Any]:
        d = self.model_dump(mode="json", exclude_none=True)
        return d


class WatchlistSource(BaseModel):
    source_id: str
    label: str
    surface: str = "public"
    door: VoiceDoor = VoiceDoor.AUGUSTO_CIVIC
    claim_tags: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    active: bool = True


QUEUE_CAP = 7
REPLACE_MARGIN = 10.0
