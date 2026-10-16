"""Market Scouter API v0 core — truth layer over src/ (fit/scorer/store/ScoutEvent).

Suggests-only forever: no Post / Schedule / publish route exists or may be added.
Locked rules implemented here:
  1. recommend(asset_id | None): scoped Fit never borrows another piece's slugs.
  2. sealed handoff with door-scoped Active injection + pause checksum.
  3. dual-door soft slugs -> door_mix until the door is explicit from a selected asset.
  4. receipt is user-attested only; no Win without a valid receipt; lens_mismatch keeps Scout slug.
  5. handoff orphans: hard TTL -> expired_handoff (never auto-Skipped).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
import time
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from ..draft import shape_draft
from .. import fit_graded
from ..brand import labels_for
from ..claim_echo import echoed_claim
from ..post_identity import note_dropped, resolve_post_dedupe
from .. import lang_gate
from ..self_accounts import is_self_account, self_in_urls
from ..bot_accounts import bot_accounts, redirect_bot
INTAKE_MAX_POST_CHARS = 10000   # longer → killed 'too_long' at intake (never graded)
TIER_RANK = {"claim": 0, "topic": 1}


def claim_first() -> bool:
    """MS_QUEUE_CLAIM_FIRST=1: claim-graded cards take slots before topic, then word-only (default OFF)."""
    return os.environ.get("MS_QUEUE_CLAIM_FIRST", "0") == "1"


RANK_COPY = {  # docs/TAB-COPY.md "Rank line"
    "claim": "Ranked first: argues one of your claims · S {S}",
    "topic": "On your topic, no claim to answer · S {S}",
    "tooltip": "Cards that argue a claim you've made come before topic cards. Within each group, higher S ranks higher.",
}
PRE_MODEL_DRAFTS = "unknown_pre_1447"  # drafts saved before the drafter model was recorded
from ..scorer import REPLACE_MARGIN, _is_protected, _status_num
from ..scorer import _BAIT_MARKERS, _FOLKLORE_MARKERS, _PROMO_CTA_MARKERS
from ..fit import claim_match, _KEYWORD_HINTS, fit_slug_map
from ..models import (
    AdapterId,
    Candidate,
    CardState,
    Decision,
    EvidenceGrade,
    InventoryAsset,
    OpedStatus,
    ARCHIVED_STATES,
    Outlet,
    ScoredCard,
    TStatus,
    VoiceDoor,
)
from ..score import queue_decision, score_candidate
from ..store import Store
from ..win_evidence import (CRITERION_HINTS, default_criterion_hint, GENESIS, chain_head, default_archiver,
                            row_hash, run_archive, check_link, evidence_url_problem, valid_public_url, verify_chain)

ROOT = Path(__file__).resolve().parents[2]
DUAL_DOOR_SLUGS = frozenset({"ai-society-governance", "human-ai-collective-action"})
CIVIC_ONLY_SLUGS = frozenset({"cheap-gen-scarce-verify", "verification-local-context"})
WIN_TYPES = frozenset({"claim_named_reply", "warm_intro", "evidence_ab"})
SOFT_OPED = frozenset({OpedStatus.DRAFT, OpedStatus.SUBMITTED, OpedStatus.PENDING})
DEFAULT_TTL_HOURS = float(os.environ.get("MS_HANDOFF_TTL_HOURS", "72"))
SURFACES = ("arxiv", "github", "medium", "carta", "lab", "conference", "working_paper", "substack")
DOORS = ("EconLLM", "Augusto-civic")
SEED_MD = ROOT / "data" / "xbrief-interests-seed.md"


def xbrief_active() -> list[str]:
    """x-brief Active slugs in rank order, read from the seed file's `xbrief_active: true` marks."""
    rows = []
    for line in SEED_MD.read_text(encoding="utf-8").splitlines():
        m = re.match(r"- `([a-z0-9-]+)`.*xbrief_active: (true|false); xbrief_rank: (\d+|-)", line)
        if m and m.group(2) == "true":
            rows.append((int(m.group(3)), m.group(1)))
    return [s for _, s in sorted(rows)]


def xbrief_slugs(card_slugs: list[str]) -> list[str]:
    """Only the card's slugs x-brief has a lens for, in x-brief rank order."""
    return [s for s in xbrief_active() if s in card_slugs]


def card_is_oped(outlet, a: Optional[InventoryAsset]) -> bool:
    """Card language follows the OUTLET: X/LinkedIn are English; Spanish only for an op-ed outlet."""
    o = getattr(outlet, "value", outlet)
    return o not in ("x", "linkedin") and a is not None and is_oped(a)


def is_oped(a: InventoryAsset) -> bool:
    """Op-ed to an Argentine outlet: the only place Spanish is used."""
    return a.door_archive.value == VoiceDoor.AUGUSTO_CIVIC.value and (a.surface == "carta" or a.oped_status is not None)

# Spanish claim one-liners for civic slugs (translations of fit-tags.md claims; civic is Spanish-first)
CLAIM_ES = {
    "cheap-gen-scarce-verify": "Generar y amplificar es barato; verificar con contexto local es lo escaso.",
    "verification-local-context": "La generación barata convierte al contexto local verificado en un bien público escaso.",
    "ai-society-governance": "La gobernanza de la IA debe moldear incentivos, normas y arquitectura de información, no quedar en prohibir-vs-entusiasmo.",
    "human-ai-collective-action": "La unidad de análisis suele ser el sistema de información humano–IA, no el modelo solo.",
}


LINK_ONLY_MSG = "Paste the post text too, or let discovery fetch it."
_URL_RE = re.compile(r"(https?://\S+|www\.\S+)", re.I)
X_STATUS_RE = re.compile(r"^https://(?:www\.|mobile\.)?(?:x|twitter)\.com/(\w{1,15}|i(?:/web)?)/status/(\d{1,25})(?:[/?#].*)?$")
INTAKE_MAX_POSTS = 50
ARCHIVED = "archived_pre_redesign"
HANDOFF_STATUSES = ("sealed", "received", "expired_handoff", ARCHIVED)
ARCHIVED_CARD_STATES = frozenset(s.value for s in ARCHIVED_STATES)
PREDRAFT_CAP = 10


def is_link_only(snippet: str, url: str = "") -> bool:
    """True when there is no post text: empty, or only links. A bare link must never be scored as text."""
    import unicodedata
    t = "".join(ch for ch in (snippet or "") if unicodedata.category(ch) != "Cf")  # zero-width/format chars
    return not _URL_RE.sub(" ", t).strip(" \t\r\n.,;:-—|").strip()


def x_status_id(url: str) -> Optional[str]:
    m = X_STATUS_RE.match((url or "").strip())
    return m.group(2) if m else None


def human_ago(ts: datetime, now: datetime) -> str:
    sec = max(0, int((now - ts).total_seconds()))
    if sec < 90:
        return "just now"
    for unit, n in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if sec >= n:
            k = round(sec / n) if unit != "day" else sec // n
            return f"{k} {unit}{'s' if k != 1 else ''} ago"
    return "just now"  # pragma: no cover

REPLY_DAILY_MAX = 7               # replies per outlet per day (approved redesign 2026-10-10)
REPLY_BUDGET_TZ = "America/Phoenix"
LATER_META_KEY = "later_until"
LATER_HOURS = 24


def _author_handle(author: Optional[str]) -> Optional[str]:
    if not author:
        return None
    a = str(author).strip()
    if not a:
        return None
    return a if a.startswith("@") else f"@{a}"


def _bot_card(card, bots: set[str]) -> bool:
    from ..bot_accounts import is_bot_post
    return is_bot_post({"author_handle": getattr(card, "author", None), "url": getattr(card, "url", None)}, bots)


def _post_text(card) -> str:
    return (getattr(card, "title_or_snippet", None) or "").strip()


import contextvars
PROV_KEYS = ("query_id", "lane", "source_tag")
_PROV_MAP: "contextvars.ContextVar[dict]" = contextvars.ContextVar("ms_prov_map", default={})
_PROV_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,47}")


def provenance(post: dict) -> dict:
    """Validated discovery provenance from one intake post. Each value must be a short lowercase token
    ([a-z0-9][a-z0-9_.:-]{0,47}); anything else is dropped. Provenance is a label only: it never sets
    is_test, status, S or the queue."""
    out = {}
    for k in PROV_KEYS:
        v = post.get(k)
        if isinstance(v, str) and _PROV_TOKEN.fullmatch(v):
            out[k] = v
    return out


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str, **extra: Any):
        super().__init__(detail)
        self.status, self.code, self.detail, self.extra = status, code, detail, extra


def _now() -> datetime:  # monkeypatched in tests
    return datetime.now(timezone.utc)


def slug_door(slug: str) -> Optional[str]:
    """Registry door for a slug; None for dual-door soft slugs."""
    if slug in DUAL_DOOR_SLUGS:
        return None
    if slug in CIVIC_ONLY_SLUGS:
        return VoiceDoor.AUGUSTO_CIVIC.value
    fs = fit_slug_map().get(slug)
    return fs.door.value if fs else None


def strict_match(text: str, pool: list[str]) -> list[str]:
    """Claim-level Fit match (see fit.claim_match): bare keyword hits don't credit."""
    return claim_match(text, pool)


def asset_type(a: InventoryAsset) -> str:
    """Asset type comes from the inventory `surface` field only — never guessed from the URL."""
    return a.surface or "unspecified"


def asset_tone(a: InventoryAsset) -> dict:
    t = asset_type(a)
    civic = a.door_archive.value == VoiceDoor.AUGUSTO_CIVIC.value
    tone = {
        "arxiv": "academic-finding", "paper": "academic-finding", "package": "methods-practical",
        "essay": "public-essay", "substack": "public-essay", "github": "builder-readme",
        "carta": "civic-provincial", "site": "program-overview", "note": "working-notes",
        "medium": "public-essay", "lab": "program-overview", "conference": "academic-finding",
        "working_paper": "working-notes",
    }.get(t, "civic-provincial" if civic else "working-notes")
    return {"lang": "es" if is_oped(a) else "en", "tone": tone, "format": "op-ed" if is_oped(a) else "social"}


def evidence_status(a: InventoryAsset) -> str:
    if a.oped_status in SOFT_OPED:
        return "soft_pending"
    return "hard" if a.evidence_grade in (EvidenceGrade.A, EvidenceGrade.B) else "out"


class ScouterAPI:
    def __init__(self, data_dir: Path | str | None = None, archiver: Any = None, resolver: Any = None):
        self.archiver = archiver or default_archiver()
        self.resolver = resolver  # None → getaddrinfo at confirm time
        self.test_mode = os.environ.get("MS_TEST_MODE") == "1"
        self.data_dir = Path(data_dir or os.environ.get("MS_DATA_DIR") or ROOT / "data" / "db")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.data_dir / "scouter.db")
        self.predrafter = None  # callable(post, card_view) -> {status, draft_text?, code?, message?}; None → env default
        self.events_path = self.data_dir / "api_events.jsonl"
        self.events_path.touch(exist_ok=True)
        # ScoutEvent log (pipeline schema) lives in THIS server's data dir, never the repo default:
        # :8712/:8713 copies (MS_DATA_DIR) can never append to live's file.
        from ..events import EventLog
        self.scout_log = EventLog(self.data_dir / "scout_events.jsonl")
        self._scout_run_id: Optional[str] = None
        self._db = self.data_dir / "handoffs.db"
        with sqlite3.connect(self._db) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS handoffs (
                handoff_id TEXT PRIMARY KEY, card_id TEXT NOT NULL, status TEXT NOT NULL,
                payload TEXT NOT NULL, seal TEXT NOT NULL, pause_checksum TEXT NOT NULL,
                created_at TEXT NOT NULL, expires_at TEXT NOT NULL)""")
            have = {r[1] for r in c.execute("PRAGMA table_info(handoffs)")}
            for col in ("draft_text", "draft_meta", "draft_at"):
                if col not in have:  # safe additive migration, nullable
                    c.execute(f"ALTER TABLE handoffs ADD COLUMN {col} TEXT")
            c.execute("""CREATE TABLE IF NOT EXISTS intake_posts (
                status_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, url TEXT NOT NULL, status TEXT NOT NULL,
                reasons TEXT, card_id TEXT, S REAL, draft_text TEXT, draft_meta TEXT, received_at TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS archive_log (
                kind TEXT NOT NULL, item_id TEXT NOT NULL, prior_status TEXT, archived_at TEXT NOT NULL,
                label TEXT NOT NULL, PRIMARY KEY (kind, item_id, label))""")
        sp = self.data_dir / ".handoff_secret"
        if not sp.exists():
            sp.write_text(secrets.token_hex(32))
            os.chmod(sp, 0o600)
        self._secret = sp.read_bytes().strip()
        if not self.store.list_assets():
            self._seed_inventory()
        self._backfill_inventory_chrome()

    # ── infra ────────────────────────────────────────────────────────────────
    def _seed_inventory(self) -> None:
        for row in json.loads((ROOT / "data" / "seed_inventory.json").read_text()):
            self.store.upsert_asset(InventoryAsset(**row))

    def _backfill_inventory_chrome(self) -> None:
        """Copy surface/tone_hint from seed_inventory.json onto stored assets by asset_id (never by URL)."""
        seed = {r["asset_id"]: r for r in json.loads((ROOT / "data" / "seed_inventory.json").read_text())}
        won = {w.get("asset_id") for w in self.wins(include_test=True)} if self.events_path.exists() else set()
        for a in self.store.list_assets():
            row = seed.get(a.asset_id)
            if row and (a.surface is None or a.tone_hint is None):
                a = a.model_copy(update={
                    "surface": a.surface or row.get("surface"), "tone_hint": a.tone_hint or row.get("tone_hint")})
                self.store.upsert_asset(a)
            if row and a.caveat is None and row.get("caveat") and a.asset_id not in won:
                self.store.upsert_asset(a.model_copy(update={"caveat": row["caveat"]}))  # never on an asset with Wins

    _mute_events = False

    def _event(self, kind: str, **fields: Any) -> dict:
        ev = {"ts": _now().isoformat(), "kind": kind, **{k: v for k, v in fields.items() if v is not None}}
        if self._mute_events:
            return ev
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        self._scout_event(kind, fields)
        return ev


    _SCOUT_KINDS = {"discovered", "scored", "decision", "killed", "post_dedupe", "human", "win"}

    _NOTE_KEYS = ("api_status", "kept_card_id", "dropped_assets", "kept_asset", "handoff_id", "reason")
    _NOTE_SAFE = re.compile(r"[^A-Za-z0-9_.:,-]")

    def _scout_event(self, kind: str, fields: dict) -> None:
        """Mirror pipeline-kind API events into scout_events.jsonl via src/events.py (append-only, ScoutEvent schema).

        Trust rules (pinned): is_test comes ONLY from server config (MS_TEST_MODE at startup), never from the
        request, run id or post text; note carries ONLY server-written key=value pairs (api_status first),
        never post text, URLs or user notes."""
        if kind not in self._SCOUT_KINDS:
            return
        from ..models import CriterionHint, Decision, ScoutEvent
        known = set(ScoutEvent.model_fields) - {"note", "is_test"} - set(PROV_KEYS)
        d = {k: v for k, v in fields.items() if k in known and v is not None}
        if not d.get("candidate_id") and isinstance(fields.get("note"), str):
            sid = x_status_id(fields["note"].split(" ")[0].strip())   # killed rows carry the URL in note: keep only its id
            if sid:
                d["candidate_id"] = sid
        d.update((_PROV_MAP.get() or {}).get(str(d.get("candidate_id")), {}))
        d.setdefault("scout_run_id", self._scout_run_id)
        pairs: dict[str, Any] = {}
        if kind == "decision" and d.get("decision") not in {x.value for x in Decision}:
            pairs["api_status"] = d.pop("decision", None)   # held/tie/echo etc.: not a pipeline Decision
            d["decision"] = Decision.WATCH.value if pairs["api_status"] == "asset_pick_required" else Decision.DROP.value
        if d.get("criterion_hint") not in {x.value for x in CriterionHint}:
            d.pop("criterion_hint", None)
        for k in self._NOTE_KEYS[1:]:
            if fields.get(k) is not None:
                pairs[k] = fields[k]

        def val(v: Any) -> str:
            v = ",".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v)
            return self._NOTE_SAFE.sub("", v)[:80]
        note = " ".join(f"{k}={val(pairs[k])}" for k in self._NOTE_KEYS if pairs.get(k) is not None)
        if note:
            d["note"] = note
        try:
            self.scout_log.append(ScoutEvent(kind=kind, is_test=bool(self.test_mode), **d))
        except Exception as e:  # noqa: BLE001 — logging must never break intake/receipts
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": _now().isoformat(), "kind": "scout_event_error", "for": kind,
                                    "error": f"{type(e).__name__}: {e}"[:200]}) + "\n")

    def events(self) -> list[dict]:
        return [json.loads(l) for l in self.events_path.read_text().splitlines() if l.strip()]

    def _seal(self, payload: dict) -> str:
        canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hmac.new(self._secret, canon.encode(), hashlib.sha256).hexdigest()

    # ── inventory / fit ──────────────────────────────────────────────────────
    def asset_view(self, a: InventoryAsset) -> dict:
        return {
            "asset_id": a.asset_id, "title": a.title, "url": a.url, "type": asset_type(a),
            "surface": a.surface, "tone_hint": a.tone_hint, "caveat": a.caveat,
            "door": a.door_archive.value, "slugs": a.slugs,
            "primary_slug": a.slugs[0] if a.slugs else None,
            "evidence_grade": a.evidence_grade.value, "evidence_status": evidence_status(a),
            "oped_status": a.oped_status.value if a.oped_status else None, **asset_tone(a),
        }

    def inventory(self) -> list[dict]:
        return [self.asset_view(a) for a in self.store.list_assets()]

    def add_asset(self, data: dict, strict: bool = False) -> dict:
        reg = fit_slug_map()
        if "door" in data:
            data["door_archive"] = data.pop("door")
        bad = [s for s in data.get("slugs", []) if s not in reg]
        if bad:
            raise ApiError(422, "closed_vocab", "Pick topics from your list only: " + ", ".join(bad), invalid=bad)
        if not data.get("slugs"):
            raise ApiError(422, "slugs_required", "Pick at least one topic.")
        if strict:
            if data.get("surface") not in SURFACES:
                raise ApiError(422, "surface_required", "Pick where this asset lives (arxiv, github, substack…).")
            if not (data.get("tone_hint") or "").strip():
                raise ApiError(422, "tone_required", "Say in a few words how drafts should sound.")
            if data.get("door_archive") not in DOORS:
                raise ApiError(422, "door_required", "Pick a voice: EconLLM or Augusto-civic.")
            if not (data.get("title") or "").strip():
                raise ApiError(422, "title_required", "Give the asset a title.")
            door = data.get("door_archive")
            mixed = [s for s in data.get("slugs", []) if slug_door(s) not in (None, door)]
            if mixed:
                raise ApiError(422, "door_mix",
                               f"These topics belong to the other voice, not {door}: " + ", ".join(mixed),
                               invalid=mixed)
        aid = data.get("asset_id")
        if aid and self.store.get_asset(aid):
            if strict:
                raise ApiError(409, "asset_id_taken", "That asset id is already used. Pick another.")
            if aid in {w["asset_id"] for w in self.wins()}:
                raise ApiError(409, "asset_has_wins", "This asset has recorded wins, so it can't be changed.")
        if strict and not aid:
            base = "asset_" + re.sub(r"[^a-z0-9]+", "_", data["title"].lower()).strip("_")[:40]
            aid, n = base, 2
            while self.store.get_asset(aid):
                aid, n = f"{base}_{n}", n + 1
            data["asset_id"] = aid
        a = InventoryAsset(**data)
        self.store.upsert_asset(a)
        return self.asset_view(a)

    def fit_vocab(self) -> list[dict]:
        return [{"slug": s.slug, "claim": s.claim_one_liner, "door": slug_door(s.slug) or "dual",
                 "use_when": s.use_when} for s in fit_slug_map().values()]

    def interests_by_door(self, door: str, card_slugs: list[str]) -> tuple[list[str], list[str]]:
        active, paused = [], []
        for s in sorted(fit_slug_map()):
            d = slug_door(s)
            if d is None:  # dual-door: only active when this card's door made it explicit
                (active if s in card_slugs else paused).append(s)
            elif d == door:
                active.append(s)
            else:
                paused.append(s)
        return active, paused

    # ── 1. recommend ─────────────────────────────────────────────────────────
    def recommend(self, **kw: Any) -> dict:
        if is_link_only(kw.get("snippet", ""), kw.get("url", "")):
            self._event("refused", kill_reasons=["link_only"], outlet=kw.get("outlet"), note=kw.get("url"))
            raise ApiError(422, "link_only", LINK_ONLY_MSG)
        t0, started = time.perf_counter(), _now().isoformat()
        out = self._recommend(**kw)
        out["started_at"], out["duration_ms"] = started, round((time.perf_counter() - t0) * 1000, 1)
        return out

    def _recommend(self, *, url: str, outlet: str, snippet: str = "", asset_id: Optional[str] = None,
                  age_hours: float = 12.0, reply_count: Optional[int] = None,
                  quote_count: Optional[int] = None, comment_count: Optional[int] = None,
                  like_count: Optional[int] = None, voice_door: Optional[str] = None,
                  adapter: AdapterId = AdapterId.MANUAL_PASTE, author: Optional[str] = None,
                  dry: bool = False) -> dict:
        out = Outlet(outlet)
        text = f"{snippet} {url}"
        kills: list[str] = []
        if fit_graded.is_hashtag_stuffed(snippet):
            kills.append("hashtag_stuffed")  # own reason so runs can count these kills separately
        mode = "scoped" if asset_id else "general"
        assets = {a.asset_id: a for a in self.store.list_assets()}

        route = fit_graded.route()          # 'either' | 'model' | None
        either = route is not None
        grader = self._fit_grader() if (fit_graded.enabled() and not either) else None
        if fit_graded.enabled() and not either and grader is None:
            self._event("fit_grader_unavailable", outlet=out.value, note=url)  # falls back to word-level Fit
        fit_override, fit_level = None, None
        if grader is not None:
            # Graded Fit: words are only a junk pre-filter; the model grades the post against each
            # candidate asset's one_line_claim. Best level wins; a tie at the top asks for a pick.
            if asset_id and asset_id not in assets:
                raise ApiError(404, "unknown_asset", f"no asset {asset_id}")
            pool = [assets[asset_id]] if asset_id else list(assets.values())
            pid = x_status_id(url) or url
            graded = []
            for a in pool:
                if not a.slugs:
                    continue
                lvl, f, _src = fit_graded.graded_level(
                    snippet, pid, a.asset_id, a.one_line_claim or fit_slug_map()[a.slugs[0]].claim_one_liner,
                    grader, self._fit_cache(), caveats=a.caveat or "")
                if lvl != "none":
                    graded.append((f, lvl, a))
            best = max((g[0] for g in graded), default=0.0)
            top = [g for g in graded if g[0] == best]
            slugs = []
            if not top:
                kills.append("empty_fit")
            elif len(top) > 1:
                return self._asset_tie(mode, out, url, [g[2] for g in top], snippet, author)
            else:
                fit_override, asset = best, top[0][2]
                fit_level = top[0][1]
                if fit_graded.mode() == "binary":  # any not-none gets one fixed F; level only gates drafting
                    fit_override = fit_graded.BINARY_F
                door = asset.door_archive.value
                word = [s_ for s_ in strict_match(text, asset.slugs)]
                slugs = word or [next((s_ for s_ in asset.slugs if s_ not in DUAL_DOOR_SLUGS), asset.slugs[0])]
                if voice_door and voice_door != door:
                    kills.append("door_mix")
        elif asset_id:
            asset = assets.get(asset_id)
            if not asset:
                raise ApiError(404, "unknown_asset", f"no asset {asset_id}")
            slugs = strict_match(text, asset.slugs)  # never borrow other pieces' slugs
            door = asset.door_archive.value
            if not slugs:
                kills.append("empty_fit")
                # tone/door clash: the paste belongs to the other door's lane
                other = [s for s in strict_match(text, list(fit_slug_map())) if slug_door(s) not in (None, door)]
                if other:
                    kills.append("door_mix")
            if voice_door and voice_door != door:
                kills.append("door_mix")
            if any(slug_door(s) not in (None, door) for s in slugs):
                kills.append("door_mix")
        else:
            inv_slugs = sorted({s for a in assets.values() for s in a.slugs} | set(fit_slug_map()))
            slugs = strict_match(text, inv_slugs)
            if not slugs:
                kills.append("empty_fit")
            if any(s in DUAL_DOOR_SLUGS for s in slugs):
                kills.append("door_mix")  # door must come from an explicitly selected asset
            matches = [a for a in assets.values() if set(a.slugs) & set(slugs)]
            word_tie = None
            if not kills and len(matches) > 1 and either:
                word_tie = matches  # graded route decides the asset; tie only if the grader can't
            elif not kills and len(matches) > 1:
                res = {"ok": False, "mode": mode, "status": "asset_pick_required", "slugs": slugs,
                       "asset_options": [self.asset_view(a) for a in matches], "card": None,
                       "kill_reasons": []}
                self._event("decision", decision="asset_pick_required", slug=slugs[0], outlet=out.value, note=url)
                return res
            if not kills and not matches:
                kills.append("empty_fit")  # vocab hit but nothing in inventory to advertise
            asset = matches[0] if matches else None
            door = asset.door_archive.value if asset else None
            if asset:
                slugs = [s for s in slugs if s in asset.slugs]

        if either:
            # either: word filter OR v1 grader (only empty_fit can be lifted).
            # model:  grader decides; graded none → empty_fit even if words matched; words only as fallback.
            # Any pass → F fixed at BINARY_F; only model-'claim' posts get pre-drafts.
            word_pass = "empty_fit" not in kills
            fit_level, decided = "none", False
            wt = locals().get("word_tie")
            # word-filter verdict, logged next to each grade in fit_trace (before the grader can change anything)
            word_filter = {"pass": word_pass, "slugs": list(slugs) if word_pass else [],
                           "asset_id": asset.asset_id if (word_pass and asset) else None,
                           "tie_assets": [getattr(a, "asset_id", a) for a in (wt or [])]}
            hard = f"{snippet} {author or ''}".lower()
            hard_kill = any(m in hard for m in (*_PROMO_CTA_MARKERS, *_BAIT_MARKERS, *_FOLKLORE_MARKERS))
            run_dry = bool(self._either_run and self._either_run.get("_dry"))
            # grader only after junk / hard-kill / dry-run filters, so none of those can burn the per-run cap
            if (not (set(kills) - {"empty_fit", "door_mix"}) and not fit_graded.is_obvious_junk(snippet)
                    and not fit_graded.is_hashtag_stuffed(snippet) and not hard_kill and not run_dry):
                pool = [assets[asset_id]] if asset_id and asset_id in assets else list(assets.values())
                self._last_grade_empty = False
                graded, failed = self._either_grade(snippet, x_status_id(url) or url, pool)
                if failed:
                    self._event("fit_grader_unavailable", outlet=out.value, note=url)  # word filter alone
                if graded is not None and not failed:
                    decided = True
                    best = max((g[0] for g in graded), default=0.0)
                    top = [g for g in graded if g[0] == best]
                    if len(top) > 1:
                        self._either_stat("n_asset_tie")
                        return self._asset_tie(mode, out, url, [g[2] for g in top], snippet, author)
                    if top:
                        fit_level, asset = top[0][1], top[0][2]
                        door = asset.door_archive.value
                        word = strict_match(text, asset.slugs)
                        slugs = word or [next((s_ for s_ in asset.slugs if s_ not in DUAL_DOOR_SLUGS), asset.slugs[0])]
                        kills = [k for k in kills if k not in ("empty_fit", "door_mix")]
                        if voice_door and voice_door != door:
                            kills.append("door_mix")
                        if not word_pass:
                            self._either_stat("n_added_by_grader")
                    elif route == "model":
                        if word_pass and not kills:
                            # words pass, grader says none: held for review, never queued or killed
                            self._either_stat("n_grader_disagrees")
                            run = self._either_run
                            if run is not None and len(run.setdefault("grader_disagrees_ids", [])) < 200:
                                run["grader_disagrees_ids"].append(x_status_id(url) or url)
                            self._event("decision", decision="grader_disagrees", outlet=out.value, note=url)
                            return {"ok": False, "mode": mode, "status": "grader_disagrees", "slugs": slugs,
                                    "card": None, "kill_reasons": [], "labels": labels_for(snippet, author)}
                        kills.append("empty_fit")  # model mode: graded none + no word pass → kill
                        word_pass = False
                    elif wt:  # either: graded none but words matched several assets
                        self._either_stat("n_asset_tie")
                        return self._asset_tie(mode, out, url, wt, snippet, author)
            grader_fallback = False
            if not decided:
                if route == "model" and word_pass:
                    self._either_stat("n_word_fallback")
                    grader_fallback = not hard_kill  # word-only pass in model mode → held, never queued
                elif (route == "model" and getattr(self, "_last_grade_empty", False)
                      and set(kills) <= {"empty_fit"} and not hard_kill):
                    # empty/unparseable reply is an error, never a 'none' verdict: hold, don't kill
                    self._either_stat("n_word_fallback")
                    self._last_grade_empty = False
                    return {"ok": False, "mode": mode, "status": "grader_fallback", "slugs": [], "card": None,
                            "kill_reasons": [], "labels": labels_for(snippet, author)}
                if wt and word_pass:
                    self._either_stat("n_asset_tie")
                    return self._asset_tie(mode, out, url, wt, snippet, author)
            if fit_level == "none" and word_pass:
                self._either_stat("n_word_only")
            if fit_level != "none" or word_pass:
                fit_override = fit_graded.BINARY_F

        kills = list(dict.fromkeys(kills))
        lang_cap = None
        if (not kills and fit_level == "claim" and out == Outlet.X
                and os.environ.get("MS_LANG_CAP", "on").lower() != "off"
                and door != VoiceDoor.AUGUSTO_CIVIC.value):   # X only; civic (Tucumán/NOA) + non-X never capped
            li = lang_gate.classify(snippet)
            if not li["clearly_english"]:
                lang_cap = {"lang": li["lang"], "reason": li["reason"], "detected": li.get("detected"),
                            "en_share": li["en_share"], "non_latin_share": li["non_latin_share"]}
                fit_level = "topic"                       # X is English-only: no claim draft, ranked as topic
                if fit_graded.mode() not in ("binary",) and not fit_graded.route():
                    fit_override = fit_graded.LEVEL_F["topic"]
                self._either_stat("n_lang_capped")
                self._event("decision", decision="lang_capped", outlet=out.value, note=url, lang=li["lang"],
                            reason=li["reason"])
        if not kills and fit_level == "claim":
            echoed = echoed_claim(snippet, [(a.asset_id, a.one_line_claim) for a in assets.values()])
            if echoed:
                self._either_stat("n_claim_echo")
                self._event("decision", decision="claim_echo", outlet=out.value, note=url, asset_options=[echoed])
                return {"ok": False, "mode": mode, "status": "claim_echo", "slugs": [], "card": None,
                        "kill_reasons": [], "echoed_asset": echoed, "labels": labels_for(snippet, author)}
        if kills:
            # promo_cta + brand label evaluated regardless of which fit kill came first
            blob = f"{snippet} {author or ''}".lower()
            if "promo_cta" not in kills and any(m in blob for m in _PROMO_CTA_MARKERS):
                kills.append("promo_cta")
            self._event("killed", kill_reasons=kills, outlet=out.value, asset_id=asset_id, note=url)
            return {"ok": False, "mode": mode, "status": "killed", "kill_id": kills[0],
                    "kill_reasons": kills, "card": None, "slugs": slugs, "labels": labels_for(snippet, author)}

        cand = Candidate(adapter=adapter, outlet=out, url=url, title_or_snippet=snippet, author=author,
                         created_at=_now() - timedelta(hours=age_hours), reply_count=reply_count,
                         quote_count=quote_count, comment_count=comment_count, like_count=like_count,
                         T_status=TStatus.UNKNOWN)
        scoring_asset = asset
        if evidence_status(asset) == "soft_pending" and asset.evidence_grade == EvidenceGrade.A:
            scoring_asset = asset.model_copy(update={"evidence_grade": EvidenceGrade.B})  # pending never A
        card, skills, _f = score_candidate(cand, scoring_asset, matched_slugs=slugs, voice_door=VoiceDoor(door),
                                           fit_override=fit_override)
        if skills:
            self._event("killed", kill_reasons=skills, outlet=out.value, asset_id=asset.asset_id, note=url)
            return {"ok": False, "mode": mode, "status": "killed", "kill_id": skills[0],
                    "kill_reasons": skills, "card": None, "slugs": slugs}
        card.labels = labels_for(snippet, author)  # label only; S already computed
        if lang_cap:
            card.labels = list(card.labels) + ["lang_capped"]
        card.fit_level = fit_level                  # graded level (claim/topic/none) or None for word-only
        if fit_level and fit_level != "none" and self._fit_grader() is not None:
            g_ = self._fit_grader()
            try:
                card.fit_trace = self._fit_cache().trace(x_status_id(url) or url, asset.asset_id,
                                                         fit_graded.cache_version(g_), fit_graded.claim_hash(
                                                             asset.one_line_claim or fit_slug_map()[asset.slugs[0]].claim_one_liner))
            except Exception:  # noqa: BLE001 — trace is informational
                card.fit_trace = None
        if lang_cap:
            card.fit_trace = {**(card.fit_trace or {}), "lang": lang_cap}
        if locals().get("word_filter") is not None:
            card.fit_trace = {**(card.fit_trace or {}), "word_filter": word_filter}
        card.draft_text = shape_draft(card, asset)
        if dry:  # intake: scored + passed kill rules; queue decision happens later, in S order
            return {"ok": True, "mode": mode, "status": "scored", "slugs": slugs, "kill_reasons": [],
                    "_card": card, "_asset": asset, "fit_level": fit_level,
                    "grader_fallback": bool(locals().get("grader_fallback"))}
        return self._commit(card, asset, slugs, mode)

    def _asset_tie(self, mode: str, out, url: str, tied: list, snippet: str, author: Optional[str]) -> dict:
        """Graded tie: held (not killed, not drafted, not queued) with every tied asset recorded."""
        ids = [a.asset_id for a in tied]
        st = "asset_tie_weak" if len(tied) >= 3 else "asset_tie"   # >=3 equal fits: the grade says little
        if st == "asset_tie_weak":
            self._either_stat("n_asset_tie_weak")
        self._event("decision", decision=st, outlet=out.value, note=url, asset_options=ids)
        return {"ok": False, "mode": mode, "status": st, "slugs": [], "card": None,
                "kill_reasons": [], "asset_options": [self.asset_view(a) for a in tied], "asset_option_ids": ids,
                "labels": labels_for(snippet, author)}

    _either_run: Any = None  # per-intake-run budget/stats for either mode (None outside intake → no cap)

    def _either_stat(self, k: str, n: int = 1) -> None:
        if self._either_run is not None:
            self._either_run[k] = self._either_run.get(k, 0) + n

    def _either_grade(self, snippet: str, pid: str, pool: list):
        """→ (graded [(F, level, asset)] or None when capped/unavailable, failed: bool)."""
        grader = self._fit_grader()
        if grader is None:
            return None, True
        run, cache = self._either_run, self._fit_cache()
        cap = int(os.environ.get("MS_FIT_SHADOW_MAX_CALLS", "200"))
        todo = []
        for a in pool:
            if not a.slugs:
                continue
            claim = a.one_line_claim or fit_slug_map()[a.slugs[0]].claim_one_liner
            todo.append((a, claim, cache.get(pid, a.asset_id, fit_graded.cache_version(grader), fit_graded.claim_hash(claim))))
        misses = sum(1 for t in todo if not t[2])
        # cap counts POSTS sent to the grader (any cache miss), not calls: votes/assets don't burn it faster
        if run is not None and (run.get("capped") or (misses and run.get("posts_called", 0) + 1 > cap)):
            run["capped"] = True  # this and later posts: word filter only
            return None, False
        if misses:
            self._either_stat("posts_called")
        graded = []
        for a, claim, _hit in todo:
            lvl, f, src = fit_graded.graded_level(snippet, pid, a.asset_id, claim, grader, cache,
                                                   caveats=a.caveat or "")
            if src == "cache":
                self._either_stat("cache_hits")
            elif src in ("model", "unavailable", "error", "empty"):
                self._either_stat("model_calls", fit_graded.votes(grader) if src == "model" else 1)
                if src == "empty":
                    self._either_stat("n_grader_empty")
                    self._last_grade_empty = True
                if src != "model":
                    return None, True   # error (incl. empty reply) → fallback, never a 'none' grade
            if lvl != "none":
                graded.append((f, lvl, a))
        self._either_stat("posts_graded")
        return graded, False

    fit_grader: Any = None  # injectable (tests use a fake); default: pinned OpenRouter grader if a key is set

    def _fit_grader(self):
        if self.fit_grader is None:
            self.fit_grader = fit_graded.make_grader()  # provider: MS_FIT_GRADER_PROVIDER or config.json
        return self.fit_grader

    def _fit_cache(self):
        if getattr(self, "_fit_cache_obj", None) is None:
            self._fit_cache_obj = fit_graded.GradeCache(self.data_dir / "fit_grades.db")
        return self._fit_cache_obj

    @staticmethod
    def _queue_decision(card: ScoredCard, open_cards: list, tiered: Optional[bool] = None) -> tuple:
        """Existing S queue rule. With MS_QUEUE_CLAIM_FIRST=1 (graded cards only): a better-tier card (claim >
        topic > word-only) replaces the lowest card of the worst lower tier regardless of S; within a tier the
        +10 rule applies; a card never replaces a better-tier card."""
        if tiered is None:
            tiered = claim_first()
        dec, rep = queue_decision(card, open_cards)
        if not tiered or card.fit_level is None or dec == Decision.ENQUEUE:
            return dec, rep
        tier = lambda c: TIER_RANK.get(c.fit_level, 2)
        same = [c for c in open_cards if c.outlet == card.outlet and c.state in
                (CardState.OPEN, CardState.DRAFTING, CardState.AWAITING_APPROVAL, CardState.PINNED)]
        unprot = [c for c in same if not _is_protected(c)]
        low = lambda cs: min(cs, key=lambda c: (c.S, -_status_num(c.url), c.card_id))
        worse = [c for c in unprot if tier(c) > tier(card)]
        if worse:
            worst = max(tier(c) for c in worse)
            return Decision.REPLACE, low([c for c in worse if tier(c) == worst]).card_id
        peers = [c for c in unprot if tier(c) == tier(card)]
        if peers and card.S >= low(peers).S + REPLACE_MARGIN:
            return Decision.REPLACE, low(peers).card_id
        if card.factors.Urgency < 0.5 and card.factors.Fit >= 0.7:
            return Decision.WATCH, None
        return Decision.DROP, None

    def _dedupe_post(self, card: ScoredCard) -> Optional[dict]:
        """One card per post: keep only the highest-scoring live card for the same canonical post.
        Protected cards (drafting/awaiting approval/pinned) always stay. Returns a drop result for the new card
        when an existing card wins; otherwise demotes the losers to skipped and records them on the new card."""
        r = resolve_post_dedupe(card, self.store.list_cards(), _is_protected)
        if r and not r["ok"]:
            best = r["kept"]
            note_dropped(best, r["key"], [card.asset_id])
            self.store.upsert_card(best)
            self._event("post_dedupe", card_id=best.card_id, note=r["key"], dropped=1, dropped_assets=[card.asset_id],
                        kept_asset=best.asset_id)
            return {"ok": False, "status": "duplicate_post", "kept_card_id": best.card_id}
        return r

    def _commit(self, card: ScoredCard, asset: InventoryAsset, slugs: list[str], mode: str) -> dict:
        out = card.outlet
        dup = self._dedupe_post(card)
        if dup and not dup["ok"]:
            self._event("decision", card_id=card.card_id, decision="duplicate_post", kept_card_id=dup["kept_card_id"])
            return {"ok": False, "mode": mode, "status": "duplicate_post", "kept_card_id": dup["kept_card_id"],
                    "slugs": slugs, "card": None, "kill_reasons": []}
        losers = (dup or {}).get("losers") or []
        later_ids = set(self._active_later())
        peers = [c for c in self._open_for_cap(out, later_ids) if c.card_id not in {l.card_id for l in losers}]
        decision, replaced = self._queue_decision(card, peers)
        if decision == Decision.REPLACE and replaced:
            old = self.store.get_card(replaced)
            if old:
                old.state = CardState.WATCH
                self.store.upsert_card(old)
        if decision in (Decision.ENQUEUE, Decision.REPLACE):
            if losers:   # one card per post: the higher-scoring new card supersedes the old ones
                for c in losers:
                    c.state = CardState.SKIPPED
                    self.store.upsert_card(c)
                note_dropped(card, dup["key"], [c.asset_id for c in losers])
                self._event("post_dedupe", card_id=card.card_id, note=dup["key"], dropped=len(losers),
                            dropped_assets=[c.asset_id for c in losers], kept_asset=card.asset_id)
            self.store.upsert_card(card)
        self._event("scored", card_id=card.card_id, S=card.S, factors=card.factors.as_dict(),
                    slug=slugs[0], outlet=out.value, asset_id=asset.asset_id)
        self._event("decision", card_id=card.card_id, decision=decision.value, replaced_card_id=replaced)
        return {"ok": decision in (Decision.ENQUEUE, Decision.REPLACE), "mode": mode,
                "status": decision.value, "replaced_card_id": replaced, "kill_reasons": [],
                "slugs": slugs, "card": self.card_view(card, asset, mode)}

    def card_view(self, card: ScoredCard, asset: InventoryAsset, mode: str = "scoped", display: bool = True) -> dict:
        civic = card.voice_door == VoiceDoor.AUGUSTO_CIVIC
        slug = card.slugs[0]
        oped = card_is_oped(card.outlet, asset)
        claim = (CLAIM_ES.get(slug) if oped else None) or asset.one_line_claim or fit_slug_map()[slug].claim_one_liner
        lens = xbrief_slugs(card.slugs)
        pre = self._predraft_meta(card.card_id)
        if pre and pre.get("code") == "xbrief_declined":   # re-clean on render: stored rows may predate sanitizing
            from .decline_text import NO_DRAFT_TOOLTIP, no_draft_line, sanitize_reason
            pre = {**pre, "decline_reason": sanitize_reason(pre.get("decline_reason")),
                   "message": no_draft_line(pre.get("decline_reason")), "tooltip": NO_DRAFT_TOOLTIP}
        post = _post_text(card)
        created = card.created_at
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_h = None
        age = None
        if created:
            age_h = max(0.0, (_now() - created).total_seconds() / 3600.0)
            age = human_ago(created, _now())
        from .draft_view import clean_draft, raw_draft as _raw_draft   # view-time: old rows may carry the caveat or a template paste
        dv = (clean_draft if display else _raw_draft)(card.draft_text, pre, card.outlet.value, {
            "outlet": card.outlet.value, "door": card.voice_door.value, "slugs": card.slugs,
            "asset_title": asset.title, "asset_url": asset.url, "asset_claim": claim,
            "asset_caveat": asset.caveat, "evidence_grade": asset.evidence_grade.value})
        copy_en = (pre or {}).get("copy_enabled") if pre else None
        if dv["copy_override"] is not None:
            copy_en = dv["copy_override"]
        return {
            "predraft": pre, "copy_enabled": copy_en,
            "no_draft": dv["no_draft"], "no_draft_line": dv["no_draft_line"],
            "draft_with_caveat": dv["draft_with_caveat"], "copy_with_caveat_label": dv["copy_with_caveat_label"],
            "copy_with_caveat_tooltip": dv["copy_with_caveat_tooltip"],
            "card_id": card.card_id, "url": card.url, "outlet": card.outlet.value, "labels": list(card.labels), "fit_level": card.fit_level, "fit_trace": card.fit_trace, "post_dedupe": card.post_dedupe,
            "rank_reason": ({"tier": card.fit_level, "text": RANK_COPY[card.fit_level].format(S=round(card.S)),
                             "tooltip": RANK_COPY["tooltip"]} if claim_first() and card.fit_level in TIER_RANK else None),
            "door": card.voice_door.value, "slug": slug, "slugs": card.slugs, "claim": claim, "caveat": (asset.caveat or "").strip() or None,
            "author": _author_handle(card.author),
            "post_text": post,
            "age": age,
            "age_hours": (round(age_h, 2) if age_h is not None else None),
            "created_at": created.isoformat() if created else None,
            "S": card.S, "factors": card.factors.as_dict(),  # full §9 strip
            "likes_info": card.like_count_info,  # informational only; never in S
            "T_status": card.T_status.value, "state": card.state.value, "move": card.move_type.value,
            "draft": dv["draft"], "lang": "es" if oped else "en", "mode": mode,
            "format": "op-ed" if oped else "social", "xbrief_slugs": lens,
            "handoff_blocked": None if (lens or (dv["draft"] or "").strip()) else "no_lens",
            "asset": self.asset_view(asset),
            "source_chip": ("La Gaceta" if "lagaceta" in card.url.lower() else
                            "Contexto" if "contexto" in card.url.lower() else None) if oped else None,
        }

    def _later_map(self) -> dict[str, str]:
        raw = self.store.get_meta(LATER_META_KEY)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _save_later(self, m: dict[str, str]) -> None:
        self.store.set_meta(LATER_META_KEY, json.dumps(m, ensure_ascii=False))

    def _active_later(self) -> dict[str, str]:
        """Return still-active Later map; drop expired entries (cards return to Openings if Fresh)."""
        now = _now()
        m = self._later_map()
        kept: dict[str, str] = {}
        for cid, until in m.items():
            try:
                u = datetime.fromisoformat(until)
                if u.tzinfo is None:
                    u = u.replace(tzinfo=timezone.utc)
                if u > now:
                    kept[cid] = until
            except (TypeError, ValueError):
                continue
        if kept != m:
            self._save_later(kept)
        return kept

    def mark_later(self, card_id: str) -> dict:
        card = self.store.get_card(card_id)
        if not card:
            raise ApiError(404, "unknown_card", "That opening no longer exists. Refresh Today.")
        if card.state in ARCHIVED_STATES:
            raise ApiError(409, "archived_card", "This card was archived.")
        m = self._active_later()
        until = (_now() + timedelta(hours=LATER_HOURS)).isoformat()
        m[card_id] = until
        self._save_later(m)
        self._event("later", card_id=card_id, note=until)
        return {"card_id": card_id, "later_until": until}

    def _open_for_cap(self, outlet, later_ids: set[str]) -> list:
        """Open cards that count toward the 7/outlet cap (Later + empty-post excluded)."""
        bots = bot_accounts()
        return [c for c in self.store.open_cards(outlet)
                if c.card_id not in later_ids and _post_text(c) and not _bot_card(c, bots)]

    def card_trace(self, card_id: str) -> dict:
        """Auditable trace of one card (sprint: every card traces post → grade → score → draft).
        Read-only: assembles what the store, the grade cache and the event log already hold; changes nothing."""
        card = self.store.get_card(card_id)
        if not card:
            raise ApiError(404, "unknown_card", "No card with that id.")
        asset = self.store.get_asset(card.asset_id)
        view = self.card_view(card, asset) if asset else {}
        sid = x_status_id(card.url) or ""
        evs = [e for e in self.events()
               if e.get("card_id") == card_id or (sid and (e.get("candidate_id") == sid or sid in str(e.get("note") or "")))]
        grades = []
        if sid:
            try:
                with sqlite3.connect(str(self.data_dir / "fit_grades.db")) as c:
                    rows = c.execute("SELECT asset_id, level, model, prompt_version, graded_at, trace FROM fit_grades"
                                     " WHERE post_id=? ORDER BY asset_id", (sid,)).fetchall()
                grades = [{"asset_id": a, "level": lv, "model": m, "prompt_version": pv, "graded_at": g,
                           "trace": json.loads(t) if t else None} for a, lv, m, pv, g, t in rows]
            except sqlite3.Error:
                grades = []
        shadow = []
        for e in self.events():
            if e.get("kind") != "fit_shadow" or not sid:
                continue
            for key in ("word_passed_graded_none", "word_killed_graded_not_none"):
                for row in e.get(key) or []:
                    if row.get("status_id") == sid:
                        shadow.append({"scout_run_id": e.get("scout_run_id"), "ts": e.get("ts"), "disagreement": key,
                                       "graded_best_level": row.get("graded_best_level"),
                                       "graded_asset": row.get("graded_asset")})
        pre = view.get("predraft") or {}
        fit_source = ("model" if card.fit_trace or view.get("fit_level") else "word")
        return {
            "card_id": card_id, "state": card.state.value if hasattr(card.state, "value") else str(card.state),
            "source": {"url": card.url, "status_id": sid or None, "author": view.get("author") or card.author,
                     "text": _post_text(card), "card_created_at": view.get("created_at"), "age": view.get("age")},
            "grade": {"asset_id": card.asset_id, "asset_title": asset.title if asset else None,
                      "slugs": list(card.slugs), "claim": view.get("claim"), "fit_level": view.get("fit_level"),
                      "fit_trace": card.fit_trace, "filter_source": fit_source, "cached_grades": grades,
                      "shadow_level": next((g["level"] for g in grades if g["asset_id"] == card.asset_id), None),
                      "shadow_disagreements": shadow, "labels": list(view.get("labels") or [])},
            "score": {"S": card.S, "factors": view.get("factors"), "rank_reason": view.get("rank_reason"),
                      "note": "S = Fit, Urgency, Format fit, Evidence, Voice match, minus Effort cost; likes never count."},
            "draft": {"model": pre.get("model"), "status": pre.get("status"), "code": pre.get("code"),
                      "gate": pre.get("gate"), "shown": view.get("draft") or "", "no_draft_line": view.get("no_draft_line"),
                      "copy_enabled": view.get("copy_enabled"), "handoff_blocked": view.get("handoff_blocked")},
            "events": [{k: e.get(k) for k in ("ts", "kind", "decision", "S", "kill_reasons", "scout_run_id", "human")
                        if e.get(k) is not None} for e in evs],
        }

    def replies_today(self) -> dict:
        """Daily reply budget per outlet (approved redesign: "4 of 7 X replies left today").
        used = replies Augusto confirmed posting (acted/edited receipts) since local midnight, America/Phoenix."""
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(REPLY_BUDGET_TZ)
        today = _now().astimezone(tz).date()
        used = {o.value: 0 for o in Outlet}
        for e in self.events():
            if e.get("kind") != "human" or e.get("human") not in ("acted", "edited") or e.get("outlet") not in used:
                continue
            try:
                ts = datetime.fromisoformat(str(e["ts"]))
            except (KeyError, ValueError):
                continue
            if (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(tz).date() == today:
                used[e["outlet"]] += 1
        return {o: {"used": n, "max": REPLY_DAILY_MAX, "left": max(0, REPLY_DAILY_MAX - n)} for o, n in used.items()}

    def queue(self, asset_id: Optional[str] = None) -> dict:
        self.gc()
        later = self._active_later()
        later_ids = set(later)
        assets = {a.asset_id: a for a in self.store.list_assets()}
        cards = [c for o in Outlet for c in self.store.open_cards(o)]
        bots = bot_accounts()
        if asset_id:
            cards = [c for c in cards if c.asset_id == asset_id]
        openings, saved = [], []
        for c in cards:
            if c.asset_id not in assets:
                continue
            if not _post_text(c):
                continue  # no post text → never in Openings
            if _bot_card(c, bots):
                continue  # posted by a platform bot (e.g. @grok) before intake skipped them; kept, not shown
            view = self.card_view(c, assets[c.asset_id])
            if c.card_id in later_ids:
                view["later_until"] = later[c.card_id]
                saved.append(view)
            else:
                openings.append(view)
        return {
            "selected_asset": self.asset_view(assets[asset_id]) if asset_id in assets else None,
            "cap": {o.value: f"{len(self._open_for_cap(o, later_ids))}/7" for o in Outlet},   # queue slots held
            "replies_today": self.replies_today(),   # daily reply budget: what the status line and X button read
            "cards": openings,
            "later": saved,
        }

    # ── 2/3. sealed handoff ──────────────────────────────────────────────────
    def handoff(self, card_id: str, ttl_hours: Optional[float] = None) -> dict:
        card = self.store.get_card(card_id)
        if not card:
            raise ApiError(404, "unknown_card", "no open card (killed cards never hand off)")
        if card.state in ARCHIVED_STATES:
            raise ApiError(409, "archived_card", "This card was archived, so it can't be handed off.")
        asset = self.store.get_asset(card.asset_id)
        if not asset:
            raise ApiError(409, "asset_required", "handoff needs an explicit asset")
        lens = xbrief_slugs(card.slugs)
        if not lens and not (self.card_view(card, asset).get("draft") or "").strip():   # shown draft, not stored
            raise ApiError(409, "no_lens", "x-brief has no lens for this topic yet")
        door = card.voice_door.value
        if door != asset.door_archive.value or any(slug_door(s) not in (None, door) for s in card.slugs):
            raise ApiError(409, "door_mix", "one door per handoff; card door ≠ asset door")
        active, paused = self.interests_by_door(door, card.slugs)
        if not paused or set(active) & set(paused):
            raise ApiError(409, "pause_missing", "door-scoped Active injection could not pause the other door")
        checksum = hashlib.sha256(json.dumps({"door": door, "active": active, "paused": paused},
                                             sort_keys=True).encode()).hexdigest()
        now = _now()
        hid = "hand_" + secrets.token_hex(6)
        payload = {
            "handoff_id": hid, "scout_card_id": card.card_id, "url": card.url,
            "matched_slugs": card.slugs, "scout_slug": card.slugs[0], "door": door,
            "claim_one_liner": self.card_view(card, asset)["claim"],
            "evidence_grade": ("B" if evidence_status(asset) == "soft_pending"
                               and asset.evidence_grade == EvidenceGrade.A else asset.evidence_grade.value),
            "evidence_status": evidence_status(asset),
            "oped_status": asset.oped_status.value if asset.oped_status else None,
            "asset_id": asset.asset_id, "asset_type": asset_type(asset), "outlet": card.outlet.value,
            "interest_seed_closed": True, "xbrief_slugs": lens,
            "xbrief_active_count": len(xbrief_active()),
            "xbrief_interests": {"active": active, "paused": paused},
            "pause_checksum": checksum, "lang": "es" if card_is_oped(card.outlet, asset) else "en",
            "expires_at": (now + timedelta(hours=ttl_hours or DEFAULT_TTL_HOURS)).isoformat(),
        }
        seal = self._seal(payload)
        with sqlite3.connect(self._db) as c:
            c.execute("INSERT INTO handoffs (handoff_id, card_id, status, payload, seal, pause_checksum,"
                      " created_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
                      (hid, card_id, "sealed", json.dumps(payload), seal, checksum,
                       now.isoformat(), payload["expires_at"]))
        card.state = CardState.AWAITING_APPROVAL  # protected while handed off
        self.store.upsert_card(card)
        self._event("handoff", card_id=card_id, slug=card.slugs[0], outlet=card.outlet.value,
                    asset_id=asset.asset_id, note=hid)
        return {"payload": payload, "seal": seal}

    def _handoff_row(self, hid: str) -> Optional[dict]:
        with sqlite3.connect(self._db) as c:
            c.row_factory = sqlite3.Row
            r = c.execute("SELECT * FROM handoffs WHERE handoff_id=?", (hid,)).fetchone()
        return dict(r) if r else None

    def _set_status(self, hid: str, status: str) -> None:
        with sqlite3.connect(self._db) as c:
            c.execute("UPDATE handoffs SET status=? WHERE handoff_id=?", (status, hid))

    # ── 5. GC: hard TTL → expired_handoff ────────────────────────────────────
    def gc(self) -> list[str]:
        now = _now().isoformat()
        with sqlite3.connect(self._db) as c:
            rows = c.execute("SELECT handoff_id, card_id FROM handoffs WHERE status='sealed' AND expires_at<=?",
                             (now,)).fetchall()
        expired = []
        for hid, cid in rows:
            self._set_status(hid, "expired_handoff")
            card = self.store.get_card(cid)
            if card:
                card.state = CardState.WATCH  # off the open queue; NOT Skipped
                self.store.upsert_card(card)
            self._event("expired_handoff", card_id=cid, note=hid)
            expired.append(hid)
        return expired

    def handoffs(self, status: str = "pending") -> list[dict]:
        self.gc()
        st = {"pending": "sealed"}.get(status, status)
        with sqlite3.connect(self._db) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("SELECT * FROM handoffs WHERE status=? ORDER BY created_at", (st,)).fetchall()
        assets = {a.asset_id: a for a in self.store.list_assets()}
        out = []
        for r in rows:
            p = json.loads(r["payload"])
            a = assets.get(p["asset_id"])
            out.append({"payload": p, "seal": r["seal"], "status": status, "expires_at": r["expires_at"],
                        "asset_title": a.title if a else p["asset_id"]})
        return out

    def handoff_status(self, hid: str) -> dict:
        self.gc()
        r = self._handoff_row(hid)
        if not r:
            raise ApiError(404, "unknown_handoff", hid)
        return {"handoff_id": hid, "status": r["status"], "expires_at": r["expires_at"]}

    # ── 4. user-attested receipt ─────────────────────────────────────────────
    def receipt(self, *, handoff_id: str, seal: str, pause_checksum: str, attested: bool,
                attested_by: str, action: str, confirmed_lens: Optional[str] = None,
                win_type: Optional[str] = None, note: Optional[str] = None,
                evidence_url: Optional[str] = None, archive_url: Optional[str] = None,
                criterion_hint: Optional[str] = None) -> dict:
        self.gc()
        r = self._handoff_row(handoff_id)
        if not r or not hmac.compare_digest(r["seal"], seal or ""):
            self._event("receipt_rejected", note=f"forged_receipt:{handoff_id}")
            raise ApiError(403, "forged_receipt", "seal does not match a sealed handoff; no Win")
        if not hmac.compare_digest(r["pause_checksum"], pause_checksum or ""):
            self._event("receipt_rejected", note=f"pause_checksum:{handoff_id}")
            raise ApiError(409, "pause_refused", "pause checksum missing/mismatch; no Win")
        if attested is not True or attested_by != "user":
            raise ApiError(422, "attestation_required", "receipts are user-attested only")
        if r["status"] == ARCHIVED or self._card_archived(r["card_id"]):
            raise ApiError(409, "archived_handoff",
                           "This handoff was archived before the redesign, so it can't record a Win.")
        if r["status"] == "expired_handoff":
            raise ApiError(410, "expired_handoff", "handoff TTL passed; re-scout instead")
        if r["status"] != "sealed":
            raise ApiError(409, "already_received", "You already confirmed this one. A win only counts once.")
        if action not in ("acted", "edited", "skipped"):
            raise ApiError(422, "bad_action", action)
        is_test = self.test_mode or handoff_id in self._test_handoff_ids()
        criterion_hint = criterion_hint or default_criterion_hint(win_type)
        if win_type and action != "skipped":  # validate before the handoff is consumed
            if is_test:
                raise ApiError(409, "test_handoff_no_win",
                               "This handoff came from testing, so it can't record a Win. Skip it instead.")
            if not evidence_url:
                raise ApiError(422, "evidence_url_required",
                               "A Win needs the public link to the reply, intro or citation.")
            bad = check_link(evidence_url, self.resolver)
            if bad:
                raise ApiError(422, bad[0], f"The evidence link was refused: {bad[1]}.", reason=bad[1])
            if archive_url:
                bad = check_link(archive_url, self.resolver)
                if bad:
                    code = bad[0].replace("evidence_url", "archive_url")
                    raise ApiError(422, code, f"The archive link was refused: {bad[1]}.", reason=bad[1])
            if criterion_hint not in CRITERION_HINTS:
                raise ApiError(422, "bad_criterion_hint",
                               "Criterion hint must be one of: " + ", ".join(CRITERION_HINTS) + ".")
        p = json.loads(r["payload"])
        scout_slug = p["scout_slug"]
        out: dict[str, Any] = {"handoff_id": handoff_id, "action": action, "win": None, "lens_mismatch": False}
        self._set_status(handoff_id, "received")
        card = self.store.get_card(p["scout_card_id"])
        if card:
            card.state = CardState.SKIPPED if action == "skipped" else CardState.DONE
            self.store.upsert_card(card)
        self._event("human", human=action, card_id=p["scout_card_id"], slug=scout_slug,
                    outlet=p["outlet"], asset_id=p["asset_id"], note=handoff_id)
        if confirmed_lens and confirmed_lens != scout_slug:
            out["lens_mismatch"] = True
            self._event("lens_mismatch", card_id=p["scout_card_id"], slug=scout_slug,
                        note=f"confirmed_lens={confirmed_lens}")
        if win_type and action != "skipped":
            if win_type not in WIN_TYPES:
                raise ApiError(422, "not_a_win", f"{win_type} is not countable")
            if win_type == "evidence_ab" and p["evidence_status"] == "soft_pending":
                out["win_refused"] = "evidence_soft_pending"
            else:
                archive_url_v, archive_status = run_archive(self.archiver, evidence_url, archive_url)
                row = {"date": _now().date().isoformat(), "slug": scout_slug, "outlet": p["outlet"],
                       "asset_id": p["asset_id"], "source_id": None, "win_type": win_type,
                       "card_id": p["scout_card_id"], "note": note or "",
                       "evidence_url": evidence_url.strip(), "archive_url": archive_url_v,
                       "criterion_hint": criterion_hint, "is_test": is_test,
                       "prev_hash": self.wins_head()}
                row["row_hash"] = row_hash(row)
                ev = {k: v for k, v in row.items() if k != "date"}
                ev["source_id"] = None
                self._event("win", wins=[win_type], handoff_id=handoff_id, archive_status=archive_status,
                            win_date=row["date"], **{k: v for k, v in ev.items() if k != "source_id"})
                out["win"] = row
                out["archive_status"] = archive_status
                if archive_status == "failed":
                    out["archive_message"] = ("The Win was recorded, but the page couldn't be archived. "
                                              "Add an archive link later.")
        return out

    def _test_handoff_ids(self) -> set[str]:
        p = self.data_dir / "test_handoffs.json"
        try:
            return set(json.loads(p.read_text()).get("handoff_ids", []))
        except (OSError, ValueError):
            return set()

    def _win_rows(self) -> list[dict]:
        """Every Win row in log order (test rows included), as hashed."""
        return [{"date": e.get("win_date") or e["ts"][:10], "slug": e["slug"], "outlet": e["outlet"],
                 "asset_id": e["asset_id"], "source_id": e.get("source_id"), "win_type": w,
                 "card_id": e["card_id"], "note": e.get("note", ""), "evidence_url": e.get("evidence_url"),
                 "archive_url": e.get("archive_url"), "criterion_hint": e.get("criterion_hint", "none"),
                 "is_test": bool(e.get("is_test", False)), "prev_hash": e.get("prev_hash"),
                 "row_hash": e.get("row_hash")}
                for e in self.events() if e["kind"] == "win" and e.get("handoff_id") for w in e["wins"]]

    def wins(self, include_test: bool = False) -> list[dict]:
        return [r for r in self._win_rows() if include_test or not r["is_test"]]

    def wins_head(self) -> str:
        return chain_head(self._win_rows())

    def wins_verify(self) -> dict:
        return verify_chain(self._win_rows())



    # ── 7. discovery intake (X) — never posts; pre-drafts ≤10 per run by S ───
    def _predraft(self, post: dict, card: dict, probe: bool = False) -> dict:
        if self.predrafter is not None:
            return self.predrafter(post, card)
        mode = os.environ.get("MS_INTAKE_PREDRAFT", "local")
        if mode == "off":
            return {"status": "skipped", "code": "predraft_off", "message": "Pre-drafting is turned off."}
        post_text = (post.get("text") or "").strip() or (card.get("post_text") or "").strip() or None
        if mode == "xbrief":
            from . import xbrief_bridge as xb
            res = xb.draft({"url": card["url"], "asset_id": card["asset"]["asset_id"],
                            "asset_title": card["asset"]["title"], "door": card["door"],
                            "text": post_text,
                            "asset_claim": card.get("claim") or card["asset"].get("one_line_claim"),
                            "asset_caveat": card["asset"].get("caveat"),
                            "author": post.get("author_handle") or card.get("author") or None,
                            "active_slugs": card.get("xbrief_slugs") or []}, force=probe)
            return res
        # local_template: reshape with post text so the reply opens on the thread (P2 #7)
        from ..draft import shape_draft
        from ..models import MoveType, Outlet, ScoredCard, VoiceDoor
        aid = card["asset"]["asset_id"]
        asset = self.store.get_asset(aid) if hasattr(self, "store") and self.store else None
        if asset is None:
            # fallback: keep prior draft if we cannot load the asset
            return {"status": "ok", "draft_text": card.get("draft"), "source": "local", "model": "local_template"}
        sc = ScoredCard(
            candidate_id="predraft", asset_id=aid, outlet=Outlet(card["outlet"]),
            url=card["url"], title_or_snippet=post_text or "",
            author=post.get("author_handle") or card.get("author"),
            slugs=list(card.get("slugs") or ([card["slug"]] if card.get("slug") else [])),
            voice_door=VoiceDoor(card["door"]), move_type=MoveType.REPLY, S=float(card.get("S") or 0),
        )
        draft_text = shape_draft(sc, asset, post_text=post_text or "")
        return {"status": "ok", "draft_text": draft_text, "source": "local", "model": "local_template"}

    def intake_x(self, run_id: str, posts: list[dict], dry_run: bool = False) -> dict:
        from ..account_lists import missing as _missing_lists
        gone = _missing_lists()
        if gone:   # fail closed: an empty bot/self list would turn Augusto's own or @grok posts into cards
            raise ApiError(503, "account_lists_missing",
                           "Intake is paused: the account list file(s) " + ", ".join(gone)
                           + " are missing or unreadable on this computer, so own and bot posts can't be filtered.",
                           missing=gone)
        if not dry_run:
            out = self._intake_x(run_id, posts, False)
            self._maybe_fit_shadow(run_id, posts, out)
            return out
        self._mute_events = True  # dry run: no killed/scored/decision events either
        try:
            out = self._intake_x(run_id, posts, True)
        finally:
            self._mute_events = False
        self._event("intake_dry_run", scout_run_id=run_id, received=out["received"], **out["counts"])
        return out

    # ── shadow graded Fit (MS_FIT_SHADOW=1): log-only, never touches S / cards / queue / store ──
    fit_shadow_sync = False          # tests: run inline instead of on a thread
    _fit_shadow_thread: Any = None   # last shadow thread (joinable in tests)

    def _maybe_fit_shadow(self, run_id: str, posts: list[dict], out: dict) -> None:
        try:
            if (os.environ.get("MS_FIT_SHADOW", "0") != "1" or fit_graded.route()
                    or not str(run_id).startswith("discovery-")):
                return
            snap = [{"status_id": r.get("status_id"), "status": r.get("status"), "reasons": list(r.get("reasons") or []),
                     "text": (posts[r["index"]].get("text") or "")} for r in out.get("posts", [])
                    if r.get("status") in ("queued", "held", "killed") and r.get("status_id")
                    and not {"self_post", "bot_author"} & set(r.get("reasons") or [])]
            if self.fit_shadow_sync:
                self._fit_shadow(run_id, snap)
            else:
                t = threading.Thread(target=self._fit_shadow, args=(run_id, snap), daemon=True,
                                     name=f"fit-shadow-{run_id}")
                self._fit_shadow_thread = t
                t.start()
        except Exception as e:  # noqa: BLE001 — intake must never fail on shadow
            self._shadow_event({"scout_run_id": run_id, "error": f"{type(e).__name__}: {e}"[:200]})

    def _shadow_event(self, fields: dict) -> None:
        ev = {"ts": _now().isoformat(), "kind": "fit_shadow", **fields}
        try:  # bypasses _mute_events: a concurrent dry run must not swallow it
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass

    def _promo_cta_log(self, run_id: str, row: dict) -> None:
        """Append-only <data_dir>/promo_cta_graded.jsonl: one line per promo_cta-killed post the shadow grader saw.
        Never changes a kill; it's evidence for whether the promo-word rule takes real openings (claim level)."""
        line = {"ts": _now().isoformat(), "scout_run_id": run_id, **row}
        with (self.data_dir / "promo_cta_graded.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def promo_cta_graded(self) -> list[dict]:
        path = self.data_dir / "promo_cta_graded.jsonl"
        if not path.exists():
            return []
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def _fit_shadow(self, run_id: str, snap: list[dict]) -> None:
        stats = {"scout_run_id": run_id, "posts_graded": 0, "posts_called": 0, "model_calls": 0, "cache_hits": 0,
                 "capped": False, "n_asset_tie": 0, "n_grader_empty": 0, "posts_skipped_error": 0, "word_passed_graded_none": [], "word_killed_graded_not_none": []}
        try:
            cap = int(os.environ.get("MS_FIT_SHADOW_MAX_CALLS", "200"))
            grader = self._fit_grader()
            if grader is None:
                stats["error"] = "grader_unavailable"
                return self._shadow_event(stats)
            cache = self._fit_cache()
            assets = [a for a in self.store.list_assets() if a.slugs]
            rank = {"none": 0, "topic": 1, "claim": 2}
            errors = 0
            for p in snap:
                if stats["capped"]:
                    break
                if fit_graded.is_obvious_junk(p["text"]):
                    continue
                best, best_asset, done, levels, failed_post = "none", None, True, [], False
                # cap counts POSTS sent to the grader (any cache miss), like intake; checked before any call
                cv = fit_graded.cache_version(grader)
                misses = sum(1 for a in assets if not cache.get(
                    p["status_id"], a.asset_id, cv,
                    fit_graded.claim_hash(a.one_line_claim or fit_slug_map()[a.slugs[0]].claim_one_liner)))
                if misses and stats["posts_called"] >= cap:
                    stats["capped"] = True
                    break
                if misses:
                    stats["posts_called"] += 1
                for a in assets:
                    claim = a.one_line_claim or fit_slug_map()[a.slugs[0]].claim_one_liner
                    lvl, _f, src = fit_graded.graded_level(p["text"], p["status_id"], a.asset_id, claim, grader,
                                                        cache, caveats=a.caveat or "")
                    if src == "cache":
                        stats["cache_hits"] += 1
                    elif src in ("model", "unavailable", "error", "empty"):
                        stats["model_calls"] += fit_graded.votes(grader) if src == "model" else 1
                        if src != "model":
                            errors += 1
                            stats["n_grader_empty"] += src == "empty"
                            failed_post = True
                            break           # shadow: skip this post entirely on any grader error
                    levels.append(lvl)
                    if rank[lvl] > rank[best]:
                        best, best_asset = lvl, a.asset_id
                if not done:
                    break
                if failed_post:
                    stats["posts_skipped_error"] += 1
                    continue
                stats["posts_graded"] += 1
                if best != "none" and levels.count(best) > 1:
                    stats["n_asset_tie"] += 1
                if "promo_cta" in (p.get("reasons") or []):
                    # promo_cta graded-claim log (sprint Wed 4:46): what the grader thinks of posts the promo-word kill took
                    row = {"status_id": p["status_id"], "graded_best_level": best, "graded_asset": best_asset,
                           "word_status": {"status": p["status"], "reasons": p["reasons"]}}
                    stats.setdefault("promo_cta_graded", []).append(row)
                    self._promo_cta_log(run_id, row)
                word_pass = p["status"] in ("queued", "held")
                if word_pass != (best != "none"):
                    key = "word_passed_graded_none" if word_pass else "word_killed_graded_not_none"
                    stats[key].append({"status_id": p["status_id"],
                                       "word_status": {"status": p["status"], "reasons": p["reasons"]},
                                       "graded_best_level": best, "graded_asset": best_asset})
            pg = stats.get("promo_cta_graded") or []
            stats["n_promo_cta_graded"] = len(pg)
            stats["n_promo_cta_graded_claim"] = sum(1 for r in pg if r["graded_best_level"] == "claim")
            stats["n_word_passed_graded_none"] = len(stats["word_passed_graded_none"])
            stats["n_word_killed_graded_not_none"] = len(stats["word_killed_graded_not_none"])
            if errors:
                stats["error"] = f"grader_failed_calls:{errors}"
        except Exception as e:  # noqa: BLE001
            stats["error"] = f"{type(e).__name__}: {e}"[:200]
        self._shadow_event(stats)

    def _intake_x(self, run_id: str, posts: list[dict], dry: bool) -> dict:
        if fit_graded.route() is None:
            try:
                return self._intake_x_inner(run_id, posts, dry)
            finally:
                self._scout_run_id = None
                _PROV_MAP.set({})
        self._either_run = {"posts_graded": 0, "model_calls": 0, "cache_hits": 0, "capped": False,
                            "n_added_by_grader": 0, "n_word_only": 0, "n_asset_tie": 0, "n_asset_tie_weak": 0, "n_claim_echo": 0, "n_lang_capped": 0, "posts_called": 0, "n_grader_empty": 0,
                            "n_claim_displaced": 0, "n_topic_displaced": 0}
        if fit_graded.model_mode():
            self._either_run.update(n_grader_disagrees=0, grader_disagrees_ids=[], n_word_fallback=0,
                                    n_fallback_held=0)
        self._either_run["_dry"] = dry  # fresh dict per run: cap and counts never carry across runs
        try:
            out = self._intake_x_inner(run_id, posts, dry)
        finally:
            stats, self._either_run = self._either_run, None
            self._scout_run_id = None
            _PROV_MAP.set({})
        stats.pop("_dry", None)
        stats["n_grader_calls"], stats["cap_hit"] = stats.get("model_calls", 0), stats.get("capped", False)
        self._event(f"fit_{fit_graded.route()}", scout_run_id=run_id, dry_run=dry or None, **stats)
        return out

    def _intake_x_inner(self, run_id: str, posts: list[dict], dry: bool) -> dict:
        t0, started = time.perf_counter(), _now()
        if not (run_id or "").strip():
            raise ApiError(422, "run_id_required", "Send the discovery run id.")
        if len(posts) > INTAKE_MAX_POSTS:
            raise ApiError(422, "batch_too_large",
                           f"Send at most {INTAKE_MAX_POSTS} posts per batch; this one had {len(posts)}.",
                           max_posts=INTAKE_MAX_POSTS, got=len(posts))
        results: list[dict] = []
        seen: set[str] = set()
        scored: list[tuple[float, int, dict, Any]] = []
        self._scout_run_id = run_id
        pm: dict = {}   # per request (ContextVar): concurrent intakes never share provenance labels
        for p in posts:
            sid, prov = x_status_id((p.get("url") or "").strip()), provenance(p)
            if sid and prov:
                pm[sid] = prov
        _PROV_MAP.set(pm)
        t_score = time.perf_counter()
        bots = bot_accounts()
        for i, p in enumerate(posts):
            bot = redirect_bot(p, bots) if x_status_id((p.get("url") or "").strip()) else {"bot": False}
            if bot["bot"] and bot.get("post") is None:
                # platform bot (e.g. @grok auto-reply): never a card, never graded (no cap use)
                burl = (p.get("url") or "").strip()
                r = {"index": i, "url": burl, "status_id": x_status_id(burl), "status": "killed",
                     "reasons": ["bot_author"], "target_url": bot.get("target_url"),
                     "message": "Posted by an automated account; send the thread's original post instead."}
                self._event("discovered", scout_run_id=run_id, candidate_id=r["status_id"], outlet="x", note=burl)
                self._event("killed", kill_reasons=["bot_author"], outlet="x", note=burl)
                results.append(r)
                continue
            redirected_from = None
            if bot["bot"]:
                redirected_from, p = bot["redirected_from"], bot["post"]
                posts[i] = p  # pre-draft reads the post the card is about: the thread's original
            url, text = (p.get("url") or "").strip(), p.get("text") or ""
            sid = x_status_id(url)
            r: dict[str, Any] = {"index": i, "url": url, "status_id": sid}
            if redirected_from:
                r["redirected_from"] = redirected_from
                self._event("bot_redirect", scout_run_id=run_id, outlet="x", note=f"{redirected_from} -> {url}")
            if not sid:
                r.update(status="refused", reasons=["not_x_status_url"],
                         message="Only x.com status links can be sent to intake.")
            elif is_link_only(text):  # empty after whitespace + Cf (zero-width) strip, or only links
                r.update(status="refused", reasons=["text_required"], message="Each post needs its text.")
            elif sid in seen or self._intake_blocks(sid):
                r.update(status="duplicate", reasons=[], message="This post was already received.")
            if r.get("status"):
                results.append(r)
                continue
            seen.add(sid)
            self._event("discovered", scout_run_id=run_id, candidate_id=sid, outlet="x", note=url)
            if is_self_account(p.get("author_handle")) or self_in_urls(url, text):
                # Augusto's own posts: never a card, never graded (no cap use)
                r.update(status="killed", reasons=["self_post"])
                self._event("killed", kill_reasons=["self_post"], outlet="x", note=url)
                results.append(r)
                continue
            if len(text) > INTAKE_MAX_POST_CHARS:
                r.update(status="killed", reasons=["too_long"])
                self._event("killed", kill_reasons=["too_long"], outlet="x", note=f"{url} chars={len(text)}")
                results.append(r)
                continue
            age = 12.0
            if p.get("created_at"):
                try:
                    ca = datetime.fromisoformat(str(p["created_at"]).replace("Z", "+00:00"))
                    if ca.tzinfo is None:
                        ca = ca.replace(tzinfo=timezone.utc)
                    age = max(0.0, (_now() - ca).total_seconds() / 3600)
                except ValueError:
                    pass
            rec = self._recommend(url=url, outlet="x", snippet=text, age_hours=age,
                                  reply_count=p.get("reply_count"), quote_count=p.get("quote_count"),
                                  like_count=p.get("like_count"), adapter=AdapterId.X_OFFICIAL,
                                  author=p.get("author_handle"), dry=True)
            if rec.get("labels"):
                r["labels"] = list(rec["labels"])
            if rec["status"] == "killed":
                r.update(status="killed", reasons=rec["kill_reasons"])
            elif rec.get("grader_fallback") or rec["status"] == "grader_fallback":
                r.update(status="held", reasons=["grader_fallback"],
                         message="Grader unavailable or capped for this run; word match only, held for review.")
                self._either_stat("n_fallback_held")
            elif rec["status"] == "grader_disagrees":
                r.update(status="held", reasons=["grader_disagrees"],
                         message="Your words match, but the grader found no fit; held for review.")
            elif rec["status"] == "asset_tie":
                r.update(status="held", reasons=["asset_tie"], asset_options=rec["asset_option_ids"],
                         message="This post fits more than one of your pieces equally; held, not drafted.")
            elif rec["status"] == "asset_tie_weak":
                r.update(status="held", reasons=["asset_tie_weak"], asset_options=rec["asset_option_ids"],
                         message="This post fits three or more of your pieces equally; held, not drafted.")
            elif rec["status"] == "claim_echo":
                r.update(status="held", reasons=["claim_echo"], echoed_asset=rec["echoed_asset"],
                         message="This repeats one of your own claims nearly word for word; held, not drafted.")
            elif rec["status"] == "asset_pick_required":
                r.update(status="killed", reasons=["asset_pick_required"],
                         message="This post fits more than one of your pieces; paste it with an asset picked.")
            else:
                r["S"] = rec["_card"].S
                if rec.get("fit_level"):
                    r["fit_level"] = rec["fit_level"]
                if rec["_card"].fit_trace:
                    r["fit_trace"] = rec["_card"].fit_trace
                if rec["_card"].labels:
                    r["labels"] = list(rec["_card"].labels)
                if "brand_post" in rec["_card"].labels:
                    r["no_draft"] = True  # brand post: card only, copy off, no pre-draft
                elif fit_graded.route() and rec.get("fit_level") != "claim":
                    r["no_draft"] = True  # either/model mode: only model-'claim' posts get pre-drafts
                elif rec.get("fit_level") == "topic" and fit_graded.mode() == "binary":
                    r["no_draft"] = True  # binary mode: only model-'claim' posts get pre-drafts
                scored.append((rec["_card"].S, int(sid), r, rec))
            results.append(r)
        # queue decisions in S order, ties by X status ID oldest first; never arrival order, never likes
        scored.sort(key=lambda x: (-x[0], x[1]))
        if any(x[3].get("fit_level") for x in scored):
            # graded modes: claim before topic before word-only when slots fill (flag); S itself never changes
            rank = TIER_RANK
            old_order = list(scored)
            new_order = sorted(scored, key=lambda x: (rank.get(x[3].get("fit_level"), 2), -x[0], x[1]))
            if claim_first():
                scored[:] = new_order

            def _admitted(order, decide):
                """sids holding a slot at the end of an in-memory run of the queue rule in this order."""
                sim = list(self.store.open_cards(Outlet.X))
                for _S, _sid, _r, rec_ in order:
                    dec, rep = decide(rec_["_card"], sim)
                    if dec in (Decision.ENQUEUE, Decision.REPLACE):
                        sim = [c for c in sim if c.card_id != rep] + [rec_["_card"]]
                held = {c.card_id for c in sim}
                return {x[1] for x in order if x[3]["_card"].card_id in held}
            a_old = _admitted(old_order, lambda c, o: self._queue_decision(c, o, tiered=False))
            a_new = _admitted(new_order, lambda c, o: self._queue_decision(c, o, tiered=True))
            lvl = {x[1]: x[3].get("fit_level") for x in scored}
            self._either_stat("n_claim_displaced", sum(1 for k in a_new - a_old if lvl[k] == "claim"))
            self._either_stat("n_topic_displaced", sum(1 for k in a_old - a_new if lvl[k] == "topic"))
        sim_open = list(self.store.open_cards(Outlet.X)) if dry else None
        for _S, _sid, r, rec in scored:
            if dry:  # same queue rule, against an in-memory copy of the open X queue
                dec, rep = self._queue_decision(rec["_card"], sim_open)
                if dec in (Decision.ENQUEUE, Decision.REPLACE):
                    sim_open = [c for c in sim_open if c.card_id != rep] + [rec["_card"]]
                res = {"status": dec.value}
            else:
                res = self._commit(rec["_card"], rec["_asset"], rec["slugs"], rec["mode"])
            r["card_id"] = rec["_card"].card_id
            if res["status"] in ("enqueue", "replace"):
                r.update(status="queued", reasons=[])
            elif res["status"] == "duplicate_post":   # a live card for this post already scores higher
                r.update(status="duplicate", reasons=["duplicate_post"], card_id=res["kept_card_id"],
                         message="This post already has a card that scores higher; one card per post.")
            else:  # watch / drop: passed every kill rule; held, not killed
                r.update(status="held", reasons=["watch" if res["status"] == "watch" else "below_replace_bar"],
                         message="Scored, but your X queue (7) already holds better openings.")
        score_ms = round((time.perf_counter() - t_score) * 1000, 1)
        # pre-draft: top PREDRAFT_CAP queued cards by S descending (ties by arrival); likes never used
        t_draft = time.perf_counter()
        open_ids = set() if dry else {c.card_id for c in self.store.open_cards(Outlet.X)}
        picks = [x for x in scored if x[2]["status"] == "queued" and x[2]["card_id"] in open_ids
                 and not x[2].get("no_draft")][:PREDRAFT_CAP]
        drafted = 0
        for _S, _sid, r, rec in picks:
            card = self.card_view(rec["_card"], rec["_asset"], rec["mode"], display=False)  # drafter input: raw seed
            try:
                d = self._predraft(posts[r["index"]], card)
            except Exception as e:  # never break the batch on a draft failure
                d = {"status": "error", "code": "predraft_failed", "message": str(e)[:200]}
            if d.get("status") == "ok" and d.get("draft_text"):
                from ..voice_gate import strip_caveat   # caveat is the card's own field, never in the copyable body
                d = {**d, "draft_text": strip_caveat(d["draft_text"], card["asset"].get("caveat"))}
            if d.get("status") == "ok" and not (d.get("draft_text") or "").strip():
                d = {"status": "error", "code": "draft_empty", "message": "The drafter returned an empty draft.",
                     "model": d.get("model")}
                self._event("draft_empty", card_id=r.get("card_id"), note=r.get("url"))
            r["predrafted"] = True  # counts toward the cap even if the gate blocks it; no redraft fills the slot
            r["predraft"] = {"status": d.get("status"), "code": d.get("code"), "message": d.get("message"),
                             "model": d.get("model") or "unknown",
                             "style_version": d.get("style_version"), "style_sha": d.get("style_sha"), "caveat_appended": d.get("caveat_appended")}
            if d.get("code") == "xbrief_declined":
                from .decline_text import NO_DRAFT_TOOLTIP, no_draft_line, sanitize_reason
                r["predraft"]["decline_reason"] = sanitize_reason(d.get("decline_reason"))
                r["predraft"]["message"] = no_draft_line(d.get("decline_reason"))
                r["predraft"]["tooltip"] = NO_DRAFT_TOOLTIP
            if not (d.get("status") == "ok" and d.get("draft_text")):
                # plain no-draft reason on the card instead of a silent empty draft
                r["no_draft_reason"] = d.get("message") or ("No draft (" + str(d.get("code") or "unknown") + ").")
            if d.get("status") == "ok" and d.get("draft_text"):
                gate = voice_gate_check(d["draft_text"], {
                    "outlet": card["outlet"], "door": card["door"], "slugs": card["slugs"],
                    "asset_title": card["asset"]["title"], "asset_url": card["asset"]["url"],
                    "asset_claim": card["claim"], "asset_caveat": card["asset"].get("caveat"),
                    "evidence_grade": card["asset"].get("evidence_grade")})
                r["draft_text"], r["gate"] = d["draft_text"], gate
                r["copy_enabled"] = not gate.get("reasons")
                r["predraft"]["lang"] = card["lang"]
                c_obj = rec["_card"]
                c_obj.draft_text = d["draft_text"]
                self.store.upsert_card(c_obj)
                drafted += 1
        for _S, _sid, r, _rec in scored:
            if r.get("no_draft") and r["status"] == "queued":
                if "brand_post" in (r.get("labels") or []):
                    r["predraft"] = {"status": "skipped", "code": "no_draft_brand",
                                     "message": "Brand post: card only, no pre-draft."}
                else:
                    r["predraft"] = {"status": "skipped", "code": "no_draft_topic",
                                     "message": "Topic-level fit: card only, no pre-draft."}
        draft_ms = round((time.perf_counter() - t_draft) * 1000, 1)
        now_iso = _now().isoformat()
        counts = {k: sum(1 for r in results if r["status"] == k) for k in ("queued", "held", "killed", "duplicate", "refused")}
        if dry:
            return {"run_id": run_id, "dry_run": True, "received": len(posts), "counts": counts, "predrafted": 0,
                    "predraft_cap": PREDRAFT_CAP, "started_at": started.isoformat(),
                    "timings": {"score_ms": score_ms, "predraft_ms": 0.0,
                                "total_ms": round((time.perf_counter() - t0) * 1000, 1)}, "posts": results}
        with sqlite3.connect(self._db) as c:
            for r in results:
                if r["status"] in ("queued", "killed", "held") and r.get("status_id"):
                    c.execute("INSERT OR REPLACE INTO intake_posts (status_id, run_id, url, status, reasons, card_id,"
                              " S, draft_text, draft_meta, received_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (r["status_id"], run_id, r["url"], r["status"], json.dumps(r.get("reasons") or []),
                               r.get("card_id"), r.get("S"), r.get("draft_text"),
                               json.dumps({**r["predraft"], "gate": r.get("gate"), "copy_enabled": r.get("copy_enabled", False)})
                               if r.get("predraft") else (json.dumps({"asset_options": r["asset_options"]})
                                                          if r.get("asset_options") else None), now_iso))
        counts = {k: sum(1 for r in results if r["status"] == k) for k in ("queued", "held", "killed", "duplicate", "refused")}
        timings = {"score_ms": score_ms, "predraft_ms": draft_ms,
                   "total_ms": round((time.perf_counter() - t0) * 1000, 1)}
        self._event("intake_run", scout_run_id=run_id, adapter=AdapterId.X_OFFICIAL.value, outlet="x",
                    started_at=started.isoformat(), received=len(posts), predrafted=drafted,
                    predraft_cap=PREDRAFT_CAP, **counts, **timings)
        return {"run_id": run_id, "dry_run": False, "received": len(posts), "counts": counts, "predrafted": drafted,
                "predraft_cap": PREDRAFT_CAP, "started_at": started.isoformat(), "timings": timings,
                "posts": results}

    def _predraft_meta(self, card_id: str) -> Optional[dict]:
        with sqlite3.connect(self._db) as c:
            r = c.execute("SELECT draft_meta FROM intake_posts WHERE card_id=? AND draft_meta IS NOT NULL",
                          (card_id,)).fetchone()
        if not r:
            return None
        meta = json.loads(r[0])
        if meta.get("status") == "ok":
            meta.setdefault("model", PRE_MODEL_DRAFTS)
        return meta

    def _intake_blocks(self, sid: str) -> bool:
        """A seen status ID is a duplicate unless its only card was archived before the redesign."""
        row = self._intake_row(sid)
        if not row:
            return False
        card = self.store.get_card(row["card_id"]) if row.get("card_id") else None
        return not (card and card.state in ARCHIVED_STATES)

    def _card_archived(self, card_id: str) -> bool:
        card = self.store.get_card(card_id)
        return bool(card and card.state in ARCHIVED_STATES)

    def archive_cards(self, label: str, states: list[str]) -> dict:
        """Cards only (no scout runs, no handoffs): move cards in `states` to archived state `label`. Idempotent."""
        if label not in ARCHIVED_CARD_STATES:
            raise ValueError(f"label must be one of {sorted(ARCHIVED_CARD_STATES)}")
        target, now, ids = CardState(label), _now().isoformat(), []
        want = {CardState(s) for s in states}
        with sqlite3.connect(self._db) as log:
            for card in self.store.list_cards():
                if card.state in ARCHIVED_STATES or card.state not in want:
                    continue
                log.execute("INSERT OR IGNORE INTO archive_log VALUES (?,?,?,?,?)",
                            ("card", card.card_id, card.state.value, now, label))
                card.state = target
                self.store.upsert_card(card)
                ids.append(card.card_id)
        out = {"label": label, "states": sorted(states), "cards": len(ids), "card_ids": ids}
        self._event("archive_cards", note=json.dumps(out))
        return out

    def archive_pre_redesign(self) -> dict:
        """Idempotent: archive (never delete) every card, scout_run and handoff. Wins/hash chain untouched."""
        now = _now().isoformat()
        out = {"cards": 0, "scout_runs": 0, "handoffs": 0, "already": 0}
        with sqlite3.connect(self._db) as log:
            def note(kind, iid, prior):
                cur = log.execute("INSERT OR IGNORE INTO archive_log VALUES (?,?,?,?,?)", (kind, iid, prior, now, ARCHIVED))
                return cur.rowcount
            for card in self.store.list_cards():
                if card.state in ARCHIVED_STATES:
                    out["already"] += 1
                    continue
                note("card", card.card_id, card.state.value)
                card.state = CardState.ARCHIVED_PRE_REDESIGN
                self.store.upsert_card(card)
                out["cards"] += 1
            with sqlite3.connect(self.store.db_path) as sc:
                for rid, payload in sc.execute("SELECT scout_run_id, payload FROM scout_runs").fetchall():
                    p = json.loads(payload)
                    if p.get("archive_status") == ARCHIVED:
                        out["already"] += 1
                        continue
                    note("scout_run", rid, p.get("archive_status") or "active")
                    p["archive_status"] = ARCHIVED
                    sc.execute("UPDATE scout_runs SET payload=? WHERE scout_run_id=?", (json.dumps(p), rid))
                    out["scout_runs"] += 1
            for hid, st in log.execute("SELECT handoff_id, status FROM handoffs").fetchall():
                if st == ARCHIVED:
                    out["already"] += 1
                    continue
                note("handoff", hid, st)
                log.execute("UPDATE handoffs SET status=? WHERE handoff_id=?", (ARCHIVED, hid))
                out["handoffs"] += 1
        self._event("archive_pre_redesign", note=json.dumps(out))
        return out

    def archive_log(self) -> list[dict]:
        with sqlite3.connect(self._db) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute("SELECT * FROM archive_log ORDER BY kind, item_id")]

    def _intake_row(self, sid: str) -> Optional[dict]:
        with sqlite3.connect(self._db) as c:
            c.row_factory = sqlite3.Row
            r = c.execute("SELECT * FROM intake_posts WHERE status_id=?", (sid,)).fetchone()
        return dict(r) if r else None

    PROBE_TTL_S = 600.0

    def _scoring_config(self) -> dict:
        """What decides fit on this server (no model call): claim_echo (always on), lang cap, grader, claims_sha."""
        from ..claims_hash import claims_sha
        try:
            cfg = json.loads((ROOT / "data" / "fit_grader" / "config.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {}
        prov = fit_graded.provider()
        if prov == "typesafe":
            g = {"provider": prov, "model": cfg.get("typesafe_model"), "criteria": cfg.get("typesafe_criteria_file"),
                 "decision": os.environ.get("MS_FIT_GRADER_DECISION") or cfg.get("typesafe_decision") or "argmax",
                 "cutoffs_file": cfg.get("typesafe_cutoffs_file")}
            if g["decision"] != "cutoffs":
                g["cutoffs_file"] = None
        else:
            g = {"provider": prov, "model": cfg.get("model"), "criteria": cfg.get("prompt_file"),
                 "decision": "level", "cutoffs_file": None}
        try:
            csha = claims_sha(self.store.list_assets())
        except Exception:  # noqa: BLE001 — informational
            csha = None
        return {"claim_echo": "on",
                "lang_cap": "off" if os.environ.get("MS_LANG_CAP", "on").lower() == "off" else "on",
                "fit_mode": fit_graded.mode(), "grader": g, "claims_sha": csha}

    def _drafting_config(self) -> dict:
        """Drafting status WITHOUT a model call (default /status, /health, ensure_up loop).
        The built-in drafter is local, so its probe still runs; x-brief/custom report config plus the last
        on-demand probe (/status?probe=draft or scripts/probe_draft.sh), never a new model call."""
        mode = "custom" if self.predrafter is not None else os.environ.get("MS_INTAKE_PREDRAFT", "local")
        if mode == "local":
            return {**self.drafting_probe(), "source": "probe"}
        last = getattr(self, "_probe_cache", None)
        res = {"mode": mode, "source": "config", "checked_at": _now().isoformat(),
               "probe_draft_produced": last[1].get("probe_draft_produced") if last else None}
        if mode == "off":
            return {**res, "ok": False, "reason": "Drafting is off: pre-drafting is turned off (MS_INTAKE_PREDRAFT=off)."}
        if mode == "xbrief":
            from .xbrief_bridge import _bin
            if not Path(_bin()).exists():
                return {**res, "ok": False, "reason": "Drafting is off: x-brief isn't installed on this computer."}
        if last and not last[1]["ok"]:
            return {**res, "ok": False, "reason": last[1]["reason"] + " (last on-demand test)",
                    "checked_at": last[1]["checked_at"]}
        return {**res, "ok": True, "reason": f"Drafting is set up ({mode}); no test draft was run now. "
                                             "Run a test draft with /status?probe=draft."}

    def drafting_probe(self, force: bool = False) -> dict:
        """Cached (~10 min) test draft for an X card through the active pre-drafter + check_draft."""
        c = getattr(self, "_probe_cache", None)
        if c and not force and time.monotonic() - c[0] < self.PROBE_TTL_S:
            return c[1]
        mode = "custom" if self.predrafter is not None else os.environ.get("MS_INTAKE_PREDRAFT", "local")
        res = {"ok": False, "reason": "", "mode": mode, "checked_at": _now().isoformat()}
        try:
            assets = [a for a in self.store.list_assets()
                      if a.door_archive.value == VoiceDoor.ECONLLM.value and a.slugs and xbrief_slugs(a.slugs)]
            if not assets:
                raise RuntimeError("no EconLLM asset to test with")
            failed: list[str] = []
            for asset in assets[:5]:  # built-in is local/cheap; x-brief stops at the first answer
                sc = ScoredCard(candidate_id="probe", asset_id=asset.asset_id, outlet=Outlet.X,
                                url="https://x.com/fixture_user_69/status/1", slugs=asset.slugs[:1],
                                voice_door=VoiceDoor.ECONLLM, S=80.0)
                sc.draft_text = shape_draft(sc, asset)
                card = self.card_view(sc, asset, display=False)
                if mode == "off":
                    res["reason"] = "Drafting is off: pre-drafting is turned off (MS_INTAKE_PREDRAFT=off)."
                    break
                ptxt = (f"Unpopular view: {card['claim']} Most LLM-agent papers still benchmark one prompt on one "
                        "model and call it behavior. Replications across games and seeds keep finding the effect "
                        "flips sign. Which result would you actually bet on?") if mode == "xbrief" else ""
                # x-brief's ranker may decline the probe post; the probe forces a draft (run-dir config only)
                # and retries; a model that ran and parsed but declined every time is not 'drafting off'.
                tries = 3 if mode == "xbrief" else 1
                for _ in range(tries):
                    d = self._predraft({"url": card["url"], "text": ptxt, "author_handle": "probe"}, card, probe=True)
                    if d.get("code") not in ("xbrief_no_draft", "xbrief_declined"):
                        break
                res["probe_draft_produced"] = bool(d.get("status") == "ok" and d.get("draft_text"))
                if d.get("code") in ("xbrief_no_draft", "xbrief_declined"):
                    res["ok"] = True
                    res["reason"] = ("Drafting works: x-brief ran the model and read its answer, but the model chose "
                                     f"not to draft the test post ({tries} tries). Real posts still get drafts.")
                    break
                if d.get("status") != "ok" or not d.get("draft_text"):
                    res["reason"] = "Drafting is off: the test draft didn't come back (" + \
                        (d.get("message") or d.get("code") or "no text") + ")."
                    break
                gate = voice_gate_check(d["draft_text"], {
                    "outlet": "x", "door": card["door"], "slugs": card["slugs"],
                    "asset_title": asset.title, "asset_url": asset.url, "asset_claim": card["claim"],
                    "asset_caveat": asset.caveat, "evidence_grade": asset.evidence_grade.value})
                if gate.get("reasons"):
                    failed.append(asset.asset_id + " " + ",".join(r["code"] for r in gate["reasons"]))
                    if mode == "xbrief":
                        break
                    continue
                res["ok"] = True
                res["reason"] = ("Drafting works: a test X draft came back and passed the draft check"
                                 + (" (x-brief)." if mode == "xbrief" else " (built-in drafter)."))
                break
            res["failed_assets"] = failed
            if failed:
                note = "Test drafts failed the draft check for: " + "; ".join(failed) + "."
                res["reason"] = (res["reason"] + " " + note) if res["ok"] else \
                    "Drafting is off: the test draft failed the draft check (" + "; ".join(failed) + ")."
        except Exception as e:
            res["reason"] = f"Drafting is off: the test draft failed ({str(e)[:160]})."
        self._probe_cache = (time.monotonic(), res)
        return res

    def status(self, xbrief_health: Any = None, probe_draft: bool = False) -> dict:
        now = _now()
        last = None
        for e in reversed(self.events()):
            if (e.get("kind") == "intake_run" and str(e.get("scout_run_id", "")).startswith("discovery-")
                    and (e.get("received", 0) - e.get("refused", 0)) > 0):
                last = e
                break
        if last:
            ts = datetime.fromisoformat(last["ts"])
            x = {"at": last["ts"], "sentence": f"X was last checked {human_ago(ts, now)}.",
                 "run_id": last.get("scout_run_id")}
        else:
            x = {"at": None, "sentence": "X hasn't been checked yet.", "run_id": None}
        probe = self.drafting_probe(force=True) if probe_draft else self._drafting_config()
        ok, reason = probe["ok"], probe["reason"]
        if xbrief_health is None:
            from .xbrief_bridge import health as xb_health
            xbrief_health = xb_health
        try:
            h = xbrief_health()
        except Exception as e:  # pragma: no cover
            h = {"present": False, "doctor_ok": False, "error": str(e)[:200]}
        if not h.get("present"):
            sc = {"ok": False, "note": "x-brief isn't installed on this computer."}
        elif h.get("doctor_ok"):
            sc = {"ok": True, "note": "x-brief's self-check passed."}
        else:
            sc = {"ok": False, "note": "x-brief's self-check reported a problem (often an optional add-on). "
                                       "This doesn't change whether drafting works."}
        bots = bot_accounts()   # bot-author cards from before 2026-10-14 stay in the store but hold no slot
        live = {o: [c for c in self.store.open_cards(o) if not _bot_card(c, bots)] for o in Outlet}
        cards = [c for o in Outlet for c in live[o]]
        by = {o.value: len(live[o]) for o in Outlet}
        return {"scoring_config": self._scoring_config(), "x_last_checked": x, "drafting_ok": ok, "drafting_reason": reason,
                "drafting_checked_at": probe["checked_at"], "probe_draft_produced": probe.get("probe_draft_produced"), "drafting_source": probe.get("source", "probe"), "xbrief_selfcheck": sc,
                "queue_size": len(cards), "queue_by_outlet": by,
                "queue_sentence": f"{len(cards)} card{'s' if len(cards) != 1 else ''} waiting in the queue.",
                **self._jobs_status()}

    def _jobs_status(self) -> dict:
        from .. import heartbeat
        try:
            b = heartbeat.jobs_block(heartbeat.heartbeat_dir(self.data_dir))
        except Exception as e:  # noqa: BLE001 — /status must never fail on a bad heartbeat file
            return {"jobs": {}, "jobs_warnings": [f"Job heartbeats could not be read: {type(e).__name__}."]}
        return {"jobs": b["jobs"], "jobs_warnings": b["warnings"]}

    # ── 6. in-app x-brief draft (never posts, never a Win, never changes status) ──
    def _draftable(self, hid: str, seal: Optional[str] = None) -> tuple[dict, dict]:
        self.gc()
        r = self._handoff_row(hid)
        if not r:
            raise ApiError(404, "unknown_handoff", "There's no handoff with that id.")
        p = json.loads(r["payload"])
        if not hmac.compare_digest(self._seal(p), r["seal"]) or (seal is not None
                                                                 and not hmac.compare_digest(r["seal"], seal)):
            raise ApiError(403, "forged_handoff", "This handoff's seal doesn't match. Re-scout it.")
        if r["status"] == ARCHIVED or self._card_archived(r["card_id"]):
            raise ApiError(409, "archived_handoff", "This handoff was archived before the redesign. Re-scout it.")
        if r["status"] == "expired_handoff" or r["expires_at"] <= _now().isoformat():
            raise ApiError(410, "expired_handoff", "This handoff has expired. Re-scout it.")
        if r["status"] != "sealed":
            raise ApiError(409, "not_pending", "This handoff is no longer pending.")
        return r, p

    def _gate_card(self, p: dict) -> dict:
        a = self.store.get_asset(p["asset_id"])
        return {"outlet": p["outlet"], "door": p["door"], "slugs": p.get("matched_slugs") or [],
                "asset_title": a.title if a else "", "asset_url": (a.url if a else None),
                "asset_claim": p.get("claim_one_liner"), "asset_caveat": (a.caveat if a else None),
                "evidence_grade": (a.evidence_grade.value if a else p.get("evidence_grade"))}

    def _check(self, text: str, p: dict, model_text: Optional[str]) -> dict:
        card = self._gate_card(p)
        gate = voice_gate_check(text, card)
        allowed = " ".join(str(x) for x in (p.get("url"), card["asset_url"], card["asset_title"],
                                            p.get("claim_one_liner")) if x).lower()
        warnings = []
        for u in re.findall(r"https?://\S+|www\.\S+", text or ""):
            if u.rstrip(".,);").lower() not in allowed:
                warnings.append({"code": "foreign_link", "message": f"The draft has a link that isn't from this handoff: {u}"})
        for h in re.findall(r"(?<![\w/])@\w{1,15}", text or ""):
            if h.lower() not in allowed:
                warnings.append({"code": "foreign_handle", "message": f"The draft mentions {h}, who isn't in this handoff."})
        authored = "model" if model_text is not None and _norm_text(text) == _norm_text(model_text) else "user_edited"
        warnings = list(gate.get("warnings") or []) + warnings  # gate warnings never block Copy final
        return {"gate": gate, "copy_enabled": not gate.get("reasons"), "warnings": warnings, "authored_by": authored,
                "lang": p.get("lang"), "door": p["door"], "outlet": p["outlet"]}

    def draft_handoff(self, hid: str) -> dict:
        from . import xbrief_bridge as xb
        _r, p = self._draftable(hid)
        if not p.get("door"):
            raise ApiError(422, "door_required", "This handoff has no voice set, so it can't be drafted.")
        lock = _DRAFT_LOCKS.setdefault(hid, threading.Lock())
        if not lock.acquire(blocking=False):
            raise ApiError(409, "already_drafting", "Already drafting this one.")
        try:
            a = self.store.get_asset(p["asset_id"])
            res = xb.draft(xb.bridge_input(p, a.title if a else ""))
        finally:
            lock.release()
        base = {"handoff_id": hid, "lang": p.get("lang"), "door": p["door"], "outlet": p["outlet"],
                "elapsed_ms": res["elapsed_ms"], "status": res["status"]}
        if res["status"] != "ok":
            self._event("xbrief_draft_error", note=f"{hid}:{res['code']}")
            return {**base, "draft_text": None, "authored_by": "model", "label": "model draft",
                    "gate": None, "copy_enabled": False, "warnings": [],
                    "error": {"code": res["code"], "message": res["message"]}}
        chk = self._check(res["draft_text"], p, res["draft_text"])
        meta = {"provenance": res["provenance"], "elapsed_ms": res["elapsed_ms"], "model": res.get("model") or "unknown",
                "style_version": res.get("style_version"), "style_sha": res.get("style_sha"), "caveat_appended": res.get("caveat_appended"),
                **chk}
        at = _now().isoformat()
        with sqlite3.connect(self._db) as c:
            c.execute("UPDATE handoffs SET draft_text=?, draft_meta=?, draft_at=? WHERE handoff_id=?",
                      (res["draft_text"], json.dumps(meta, ensure_ascii=False), at, hid))
        self._event("xbrief_draft", note=hid)
        return {**base, "draft_text": res["draft_text"], "authored_by": "model", "label": "model draft",
                "drafted_at": at, "provenance": res["provenance"], "model": meta["model"], "error": None, **{k: v for k, v in chk.items() if k != "authored_by"}}

    def latest_draft(self, hid: str) -> dict:
        r = self._handoff_row(hid)
        if not r:
            raise ApiError(404, "unknown_handoff", "There's no handoff with that id.")
        if not r.get("draft_text"):
            return {"handoff_id": hid, "draft_text": None}
        meta = json.loads(r["draft_meta"] or "{}")
        meta.setdefault("model", PRE_MODEL_DRAFTS)
        return {"handoff_id": hid, "draft_text": r["draft_text"], "authored_by": "model",
                "label": "model draft", "drafted_at": r["draft_at"], **meta, "status": "ok"}

    def check_handoff_draft(self, hid: str, draft_text: str) -> dict:
        r, p = self._draftable(hid)
        return {"handoff_id": hid, **self._check(draft_text, p, r.get("draft_text"))}


def _norm_text(t: Optional[str]) -> str:
    """NFKC, strip zero-width chars, collapse whitespace: whitespace-only edits stay model-authored."""
    import unicodedata
    t = unicodedata.normalize("NFKC", t or "")
    t = re.sub(r"[\u200b-\u200d\u2060\ufeff]", "", t)
    return " ".join(t.split())


_DRAFT_LOCKS: dict[str, "threading.Lock"] = {}


def voice_gate_check(text: str, card: dict) -> dict:
    """Marketing's gate (src/voice_gate.py). Pure; never edits text; never a Win."""
    from ..voice_gate import check_draft
    return check_draft(text, card).to_dict()
