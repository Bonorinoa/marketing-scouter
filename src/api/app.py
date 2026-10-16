"""FastAPI shell over ScouterAPI. Suggests-only: no Post/Schedule/publish routes."""

from __future__ import annotations

import json
import os

from typing import Any, Literal, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..models import EvidenceGrade
from .core import ApiError, ScouterAPI

EVIDENCE_GRADES = frozenset(g.value for g in EvidenceGrade)


class RecommendIn(BaseModel):
    url: str
    outlet: str = "x"
    snippet: str = ""
    author: Optional[str] = None
    age_hours: float = 12.0
    reply_count: Optional[int] = None
    quote_count: Optional[int] = None
    comment_count: Optional[int] = None
    like_count: Optional[int] = None
    voice_door: Optional[str] = None


class IntakeRootIn(BaseModel):
    """The thread's original post, sent with a bot reply (e.g. @grok) so intake scores it instead."""
    url: str
    text: str
    author_handle: Optional[str] = None
    created_at: Optional[str] = None
    reply_count: Optional[int] = None
    quote_count: Optional[int] = None
    like_count: Optional[int] = None


class IntakePostIn(BaseModel):
    url: str
    text: str
    author_handle: Optional[str] = None
    created_at: Optional[str] = None
    reply_count: Optional[int] = None
    quote_count: Optional[int] = None
    like_count: Optional[int] = None  # informational only; never in S, never picks drafts
    conversation_id: Optional[str] = None        # X thread id; bot posts: where the original lives
    in_reply_to_status_id: Optional[str] = None
    thread_root: Optional[IntakeRootIn] = None   # bot posts: score this original post instead
    query_id: Optional[str] = None    # provenance only: which discovery query found this post
    lane: Optional[str] = None
    source_tag: Optional[str] = None


class IntakeXIn(BaseModel):
    run_id: str
    posts: list[IntakePostIn]
    dry_run: bool = False  # score + kill-check only; writes nothing but one intake_dry_run event


class IntakePostOut(BaseModel):
    index: int
    url: str
    status_id: Optional[str] = None
    status: str  # queued | held | killed | duplicate | refused
    reasons: list[str] = []
    message: Optional[str] = None
    card_id: Optional[str] = None
    S: Optional[float] = None
    predrafted: bool = False
    predraft: Optional[dict] = None
    draft_text: Optional[str] = None
    gate: Optional[dict] = None
    copy_enabled: bool = False
    fit_level: Optional[str] = None  # graded Fit only (MS_FIT_GRADED=1): claim | topic
    no_draft: bool = False           # binary/either topic card or brand_post: no pre-draft
    asset_options: list[str] = []    # held asset_tie: every tied asset id
    fit_trace: Optional[dict] = None    # Jev grade: p(claim/topic/none), decision_rule, confidence
    echoed_asset: Optional[str] = None  # held claim_echo: the asset whose claim the post repeats
    labels: list[str] = []           # e.g. ["brand_post"]: label only, never changes S
    redirected_from: Optional[str] = None  # bot post whose thread original this row scored
    target_url: Optional[str] = None       # killed bot_author: the thread's original, to send next run


class IntakeXOut(BaseModel):
    run_id: str
    dry_run: bool = False
    received: int
    counts: dict[str, int]
    predrafted: int
    predraft_cap: int
    started_at: str
    timings: dict[str, float]
    posts: list[IntakePostOut]


class XLastChecked(BaseModel):
    at: Optional[str] = None
    sentence: str
    run_id: Optional[str] = None


class StatusOut(BaseModel):
    scoring_config: Optional[dict] = None   # claim_echo, lang_cap, fit_mode, grader{...}, claims_sha (no model call)
    x_last_checked: XLastChecked
    drafting_ok: bool
    drafting_reason: str
    drafting_checked_at: Optional[str] = None
    probe_draft_produced: Optional[bool] = None
    drafting_source: Optional[str] = None   # "config" (no model call) or "probe" (a test draft ran)
    xbrief_selfcheck: dict
    queue_size: int
    queue_by_outlet: dict[str, int]
    queue_sentence: str
    jobs: dict = {}            # per scheduled job: last_ran, ok, stale, warning (data/heartbeats/<job>.json)
    jobs_warnings: list[str] = []  # plain sentences, one per job that is late, failed or skipped


ERR_BODY = {"content": {"application/json": {"example": {"code": "…", "message": "plain words"}}}}


from ..models import CardState as _CardState  # noqa: E402


class CardStatesOut(BaseModel):
    states: list[_CardState]
    archived: list[_CardState]


class LaterIn(BaseModel):
    card_id: str


class HandoffIn(BaseModel):
    card_id: str
    ttl_hours: Optional[float] = None


class ReceiptIn(BaseModel):
    """Unknown fields are refused. authored_by is declared only so it can be refused by name."""
    model_config = {"extra": "forbid"}
    handoff_id: str
    seal: str = ""
    pause_checksum: str = ""
    attested: bool = False
    attested_by: str = ""
    action: str
    confirmed_lens: Optional[str] = None
    win_type: Optional[str] = None
    note: Optional[str] = None
    evidence_url: Optional[str] = None
    archive_url: Optional[str] = None
    criterion_hint: Optional[str] = None
    authored_by: Optional[Any] = None  # never accepted from the client


class AssetIn(BaseModel):
    title: str
    url: Optional[str] = None
    slugs: list[str]
    door: Optional[str] = None
    door_archive: Optional[str] = None
    evidence_grade: str = "B"
    oped_status: Optional[str] = None
    one_line_claim: Optional[str] = None
    asset_id: Optional[str] = None
    surface: Optional[str] = None
    tone_hint: Optional[str] = None
    caveat: Optional[str] = None


class Reason(BaseModel):
    code: str
    message: str


class GateOut(BaseModel):
    ok: bool
    reasons: list[Reason] = []


class DraftError(BaseModel):
    code: str
    message: str


class DraftOut(BaseModel):
    handoff_id: str
    status: str  # ok | error
    draft_text: Optional[str] = None
    authored_by: str = "model"
    label: str = "model draft"
    model: Optional[str] = None  # drafter model id; drafts saved before 14:47 PT report "unknown_pre_1447"
    gate: Optional[GateOut] = None
    copy_enabled: bool = False
    warnings: list[Reason] = []
    elapsed_ms: int = 0
    lang: Optional[str] = None
    door: Optional[str] = None
    outlet: Optional[str] = None
    drafted_at: Optional[str] = None
    error: Optional[DraftError] = None


class DraftCheckOut(BaseModel):
    handoff_id: str
    gate: GateOut
    copy_enabled: bool
    warnings: list[Reason] = []
    authored_by: str
    lang: Optional[str] = None
    door: Optional[str] = None
    outlet: Optional[str] = None


class XbriefHealthOut(BaseModel):
    binary: str
    present: bool
    doctor_ok: bool
    up: bool
    error: Optional[str] = None
    detail: Optional[str] = None


class DraftCheckIn(BaseModel):
    """authored_by is server-computed only; any extra field (e.g. authored_by) is rejected."""
    model_config = {"extra": "forbid"}
    draft_text: str


import threading

_INTAKE_LOCK = threading.Lock()


MAX_BODY_BYTES = int(os.environ.get("MS_MAX_BODY_BYTES", str(1024 * 1024)))


class BodySizeLimit:
    """Pure ASGI: 413 when a request body exceeds MAX_BODY_BYTES (Content-Length or streamed)."""
    def __init__(self, app, api, limit: int = MAX_BODY_BYTES):
        self.app, self.api, self.limit = app, api, limit

    async def _reject(self, scope, send, n):
        try:
            self.api._event("request_too_large", note=f"{scope.get('method')} {scope.get('path')} bytes>={n}")
        except Exception:  # noqa: BLE001
            pass
        body = json.dumps({"error": {"code": "request_too_large",
                                     "message": f"Request body over {self.limit} bytes."}}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cl = dict(scope.get("headers") or []).get(b"content-length")
        if cl and cl.isdigit() and int(cl) > self.limit:
            return await self._reject(scope, send, int(cl))
        chunks, total = [], 0
        while True:
            msg = await receive()
            if msg["type"] != "http.request":
                chunks.append(msg)
                break
            total += len(msg.get("body", b""))
            if total > self.limit:
                return await self._reject(scope, send, total)
            chunks.append(msg)
            if not msg.get("more_body"):
                break
        it = iter(chunks)

        async def replay():
            try:
                return next(it)
            except StopIteration:
                return await receive()
        return await self.app(scope, replay, send)


def create_app(data_dir: Optional[str] = None) -> FastAPI:
    api = ScouterAPI(data_dir)
    app = FastAPI(title="Market Scouter API", version="0.1.0",
                  description="Suggests only · never posts. Compose with x-brief; you post.")
    app.state.api = api
    app.add_middleware(BodySizeLimit, api=api)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.exception_handler(ApiError)
    async def _err(_: Request, e: ApiError):
        return JSONResponse(status_code=e.status, content={"code": e.code, "message": e.detail,
                                                           "error": e.code, "detail": e.detail, **e.extra})

    @app.exception_handler(RequestValidationError)
    async def _bad(_: Request, e: RequestValidationError):
        fields = sorted({str(x.get("loc", ["", "?"])[-1]) for x in e.errors()})
        msg = "Some fields are missing or the wrong kind: " + ", ".join(fields) + "."
        return JSONResponse(status_code=422, content={"code": "bad_request", "message": msg,
                                                      "error": "bad_request", "detail": msg})

    @app.get("/health")
    def health():
        try:
            n_assets = len(api.store.list_assets())
            from ..fit import fit_slug_map
            n_slugs = len(fit_slug_map())
            from ..score import score_candidate  # noqa: F401
            scoring = True
        except Exception:  # pragma: no cover
            n_assets, n_slugs, scoring = 0, 0, False
        from .build_info import BUILD_SHA, integrity_for
        integ = integrity_for(api.data_dir)   # set by scripts/ensure_up.sh; a failed check turns health red
        from .xbrief_bridge import style_info
        st = style_info()
        return {"ok": scoring and n_slugs > 0 and st["style_ok"] and not (integ and integ["integrity"] != "ok"),
                "suggests_only": True, "data_loaded": n_slugs > 0,
                "scoring_loaded": scoring, "assets": n_assets, "topics": n_slugs, "build_sha": BUILD_SHA,
                "integrity": (integ or {}).get("integrity", "unchecked"),
                "integrity_checked_at": (integ or {}).get("checked_at"),
                "style_version": st["style_version"], "style_sha": st["style_sha"],
                "style_file_present": st["style_file_present"], "style_ok": st["style_ok"],
                "style_active": st["style_active"], "style_expected_sha": st["style_expected_sha"],
                "style_source": st["style_source"]}

    @app.get("/fit")
    def fit():
        return api.fit_vocab()

    @app.get("/inventory")
    def inventory():
        return api.inventory()

    @app.post("/inventory")
    def add_asset(body: AssetIn):
        if body.evidence_grade not in EVIDENCE_GRADES:
            raise ApiError(422, "evidence_grade_invalid", "Evidence grade must be A, B or C.",
                           invalid=[body.evidence_grade])
        d = body.model_dump(exclude_none=True)
        if "door" in d and "door_archive" in d and d["door"] != d["door_archive"]:
            raise ApiError(422, "door_conflict",
                           "The two voice fields disagree. Send one voice: EconLLM or Augusto-civic.")
        if "door" in d:
            d.pop("door_archive", None)
        if "door" not in d and "door_archive" in d:
            d["door"] = d.pop("door_archive")
        return api.add_asset(d, strict=True)

    @app.get("/status", response_model=StatusOut)
    def status(probe: Optional[str] = None):
        """Plain-words freshness: when X was last checked, whether drafting is set up, queue size.
        No model call unless ?probe=draft (forces a real test draft on demand)."""
        return api.status(probe_draft=(probe == "draft"))

    @app.post("/intake/x", response_model=IntakeXOut, responses={
        409: {"description": "intake_busy: another intake batch is still running", **ERR_BODY},
        503: {"description": "account_lists_missing: bot/self/brand account list missing or unreadable (fail closed)", **ERR_BODY},
        422: {"description": "batch_too_large (>50 posts), run_id_required, or bad_request", **ERR_BODY}})
    def intake_x(body: IntakeXIn):
        """Discovery intake for X posts. Scores every post with the same S and kill rules,
        dedupes by status id, pre-drafts at most 10 queued posts by S. Never posts."""
        if not _INTAKE_LOCK.acquire(blocking=False):
            raise ApiError(409, "intake_busy", "Another intake batch is still running. Try again in a moment.")
        try:
            return api.intake_x(body.run_id, [p.model_dump() for p in body.posts], dry_run=body.dry_run)
        finally:
            _INTAKE_LOCK.release()

    @app.post("/recommend", responses={422: {"description": "link_only: paste the post text too", **ERR_BODY}})
    def recommend(body: RecommendIn, asset_id: Optional[str] = None):
        return api.recommend(asset_id=asset_id or None, **body.model_dump())

    @app.get("/card-states", response_model=CardStatesOut)
    def card_states():
        """Closed card-state enum; archived_* states are never queued, counted or replaced."""
        from ..models import ARCHIVED_STATES, CardState
        return {"states": [s.value for s in CardState], "archived": sorted(s.value for s in ARCHIVED_STATES)}

    @app.get("/fit/promo-cta-graded")
    def promo_cta_graded():
        """Read-only promo_cta graded-claim log: shadow grades of posts the promo-word rule killed."""
        rows = api.promo_cta_graded()
        return {"n": len(rows), "n_claim": sum(1 for r in rows if r.get("graded_best_level") == "claim"), "rows": rows}

    @app.get("/cards/{card_id}/trace", responses={404: {"description": "unknown_card", **ERR_BODY}})
    def card_trace(card_id: str):
        """Read-only audit trail for one card: post → fit grade → score → draft, plus its events."""
        return api.card_trace(card_id)

    @app.get("/queue")
    def queue(asset_id: Optional[str] = None):
        return api.queue(asset_id)

    @app.post("/later", responses={404: {"description": "unknown_card", **ERR_BODY},
                                   409: {"description": "archived_card", **ERR_BODY}})
    def later(body: LaterIn):
        """Park a card out of Openings for 24h (server-persisted). Caps do not count it."""
        return api.mark_later(body.card_id)

    @app.post("/handoff", responses={409: {"description": "archived_card, no_lens, door_mix, asset_required", **ERR_BODY}})
    def handoff(body: HandoffIn):
        return api.handoff(body.card_id, body.ttl_hours)

    @app.get("/handoff")
    def handoff_list(status: Literal["pending", "sealed", "received", "expired_handoff",
                                     "archived_pre_redesign"] = "pending"):
        return api.handoffs(status)

    @app.post("/handoff/{handoff_id}/draft", response_model=DraftOut, responses={
        403: {"description": "forged_handoff"}, 404: {"description": "Unknown handoff"},
        409: {"description": "not_pending, archived_handoff, or 'Already drafting this one.'"},
        410: {"description": "expired_handoff"}, 422: {"description": "door_required"},
        502: {"description": "x-brief failed (body still carries status:error + plain message)"}})
    def handoff_draft(handoff_id: str):
        """Ask x-brief for a model draft. Never posts, never records a Win or receipt."""
        return api.draft_handoff(handoff_id)

    @app.get("/handoff/{handoff_id}/draft", response_model=Optional[DraftOut])
    def handoff_draft_latest(handoff_id: str):
        d = api.latest_draft(handoff_id)
        return d if d.get("draft_text") else None

    @app.post("/handoff/{handoff_id}/draft/check", response_model=DraftCheckOut)
    def handoff_draft_check(handoff_id: str, body: DraftCheckIn):
        return api.check_handoff_draft(handoff_id, body.draft_text)

    @app.get("/xbrief/health", response_model=XbriefHealthOut)
    def xbrief_health():
        from .xbrief_bridge import health as xb_health
        return xb_health()

    @app.get("/handoff/{handoff_id}")
    def handoff_status(handoff_id: str):
        return api.handoff_status(handoff_id)

    @app.post("/handoff/receipt", responses={
        409: {"description": "pause_refused, already_received, test_handoff_no_win, archived_handoff "
                              "(handoff or its card archived)", **ERR_BODY}})
    def receipt(body: ReceiptIn):
        if "authored_by" in body.model_fields_set:
            raise ApiError(422, "authored_by_client_forbidden",
                           "authored_by is set by the server, so it can't be sent with a receipt.")
        return api.receipt(**body.model_dump(exclude={"authored_by"}))

    @app.post("/gc")
    def gc():
        return {"expired_handoff": api.gc()}

    @app.get("/wins")
    def wins(include_test: bool = False):
        return api.wins(include_test=include_test)

    @app.get("/wins/head")
    def wins_head():
        return {"head": api.wins_head()}

    @app.get("/wins/verify")
    def wins_verify():
        return api.wins_verify()

    @app.get("/events")
    def events():
        return api.events()

    return app


app = create_app()
