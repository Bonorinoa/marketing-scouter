"""Graded Fit (DA): model-graded claim / topic / none per (post, asset), anchored on the asset's one_line_claim.

Gated by MS_FIT_GRADED=1 (default OFF). Levels map to F: claim → 1.0, topic → 0.5, none → empty_fit.
Pinned model id, temperature 0 and a versioned prompt live in data/fit_grader/. Grades are cached per
(post_id, asset_id, prompt_version), so re-scoring a post never moves S. Word lists are ONLY a pre-filter
for obvious junk (crypto/airdrop, bot logs, promo CTAs, hashtag stuffing, mass-tag replies); they never
award claim or topic. The grader is injectable; tests use a fake.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import unicodedata
import sqlite3
import urllib.request
from pathlib import Path
from typing import Callable, Optional, Protocol

LEVELS = ("claim", "topic", "none")
LEVEL_F = {"claim": 1.0, "topic": 0.5, "none": 0.0}
_ROOT = Path(__file__).resolve().parent.parent
_CFG_DIR = _ROOT / "data" / "fit_grader"
_TPL_MARK = re.compile(r"<<<[A-Z_]*BEGIN>>>")
_STRICT = re.compile(r"^(claim|topic|none)$")

_JUNK = [
    re.compile(r"\$[A-Z]{2,6}\b"),
    re.compile(r"\b(crypto|web3|airdrop|memecoin|presale|blockchain|tokenomics|giveaway)\b", re.I),
    re.compile(r"\b(debate log|peer debate|run complete|hit rate:|notes submitted:)", re.I),
]
_HASHTAG = re.compile(r"(?<!\w)#\w+")
_MASS_TAG = re.compile(r"^(?:\s*@\w+){5,}")


BINARY_F = 0.75


def mode() -> str:
    """MS_FIT_GRADED_MODE: 'graded' (claim 1.0 / topic 0.5, default) or 'binary' (any not-none → 0.75;
    only model-'claim' posts are pre-drafted, topic posts carry a no_draft flag)."""
    m = os.environ.get("MS_FIT_GRADED_MODE", "graded").strip().lower()
    return m if m in ("binary", "either", "model") else "graded"


def either() -> bool:
    """MS_FIT_GRADED_MODE=either (works without MS_FIT_GRADED): pass if word filter OR v1 grader passes;
    any pass → F=BINARY_F; only model-'claim' posts are pre-drafted."""
    return mode() == "either"


def enabled() -> bool:
    return os.environ.get("MS_FIT_GRADED", "0") == "1"


def load_config(prompt_path: Optional[str] = None) -> dict:
    """Researcher's prompts/fit_grader.v1.md when present, else the DA placeholder.
    The effective prompt_version carries a hash of the prompt text, so editing the prompt regrades."""
    cfg = json.loads((_CFG_DIR / "config.json").read_text(encoding="utf-8"))
    if prompt_path:  # non-live option (eval only): grade with another prompt file; live config untouched
        cfg["prompt_file"] = str(Path(prompt_path).resolve().relative_to(_ROOT))
        cfg["prompt_version"] = Path(prompt_path).stem
    real = _ROOT / cfg["prompt_file"]
    path = real if real.is_file() else _ROOT / cfg["placeholder_prompt_file"]
    cfg["prompt"], cfg["prompt_source"] = path.read_text(encoding="utf-8"), str(path.relative_to(_ROOT))
    cfg["prompt_version"] = f'{cfg["prompt_version"]}+{hashlib.sha256(cfg["prompt"].encode()).hexdigest()[:10]}'
    return cfg


def claim_hash(claim: str) -> str:
    return hashlib.sha256((claim or "").strip().encode()).hexdigest()[:16]


_ZW = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\u00ad]")
_LOOKALIKE = re.compile(r"<{2,}[^<>\n]{0,60}?(?:BEGIN|END)[^<>\n]{0,10}>{2,}|\{post(?:_begin|_end)?\}|\{claim\}", re.I)


def normalise_post(text: str) -> str:
    """Second layer: NFKC (folds fullwidth ＜＜＜ etc.), strip zero-width/bidi chars, neutralise marker look-alikes."""
    t = unicodedata.normalize("NFKC", text or "")
    t = _ZW.sub("", "".join(ch for ch in t if unicodedata.category(ch) != "Cf"))
    return _LOOKALIKE.sub("[marker removed]", t)


def _strip_front_matter(template: str) -> str:
    if template.startswith("---"):  # YAML front matter is metadata, not instructions
        parts = template.split("\n---", 1)
        if len(parts) == 2 and "\n" in parts[1]:
            return parts[1].split("\n", 1)[1]
    return template


def render_prompt(template: str, post_text: str, claim: str, nonce: Optional[str] = None) -> tuple[str, str, str]:
    """(prompt, begin, end). First layer: a random per-call marker the post cannot predict.
    The template's own fixed markers (e.g. <<<UNTRUSTED_POST_BEGIN>>>) are swapped for the random ones."""
    nonce = nonce or secrets.token_hex(16)
    begin, end = f"<<<POST_{nonce}_BEGIN>>>", f"<<<POST_{nonce}_END>>>"
    out = _strip_front_matter(template)
    out = _TPL_MARK.sub(begin, out.replace("{post_begin}", begin).replace("{post_end}", end))
    out = re.sub(r"<<<[A-Z_]*END>>>", end, out)
    safe = normalise_post(post_text)
    if begin not in out:
        safe = f"{begin}\n{safe}\n{end}"
    out = out.replace("{claim}", claim or "").replace("{post}", safe)
    return out, begin, end


def is_obvious_junk(text: str) -> bool:
    """Word-level pre-filter for obvious junk only; never awards claim or topic."""
    t = normalise_post(text)
    if any(p.search(t) for p in _JUNK) or _MASS_TAG.search(t):
        return True
    return is_hashtag_stuffed(text)


def is_hashtag_stuffed(text: str) -> bool:
    """>=4 hashtags making up >=30% of words."""
    words = normalise_post(text or "").split()
    tags = sum(1 for w in words if _HASHTAG.fullmatch(w.strip(".,!?:;")))
    return len(words) > 0 and tags >= 4 and tags / len(words) >= 0.3


class Grader(Protocol):
    model: str
    prompt_version: str
    def __call__(self, post_text: str, claim: str) -> str: ...


def parse_level(raw) -> str:
    """Strict: the whole reply must be exactly claim|topic|none (case/space-insensitive). Anything else → none."""
    if not isinstance(raw, str):
        return "none"
    m = _STRICT.match(raw.strip().lower())
    return m.group(1) if m else "none"


class GraderUnavailable(Exception):
    """Transport/API failure: graded as none for this call, but never cached."""


class GraderEmpty(GraderUnavailable):
    """Empty or unparseable reply (e.g. a reasoning model that spent max_tokens thinking): an ERROR, never 'none'."""


def parse_level_or_none(raw) -> Optional[str]:
    """Strict parse; None when the reply is empty or not exactly claim|topic|none."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    m = _STRICT.match(raw.strip().lower())
    return m.group(1) if m else None


class OpenRouterGrader:
    provider = "openrouter"
    """Real grader. Reads the key from the env var named in config; never logs or stores it."""
    def __init__(self, cfg: Optional[dict] = None, timeout: float = 30.0, prompt_path: Optional[str] = None):
        self.cfg = cfg or load_config(prompt_path)
        self.model, self.prompt_version, self.timeout = self.cfg["model"], self.cfg["prompt_version"], timeout

    @classmethod
    def available(cls) -> bool:
        try:
            return bool(os.environ.get(load_config()["api_key_env"]))
        except (OSError, ValueError, KeyError):
            return False

    def __call__(self, post_text: str, claim: str) -> str:
        body = {"model": self.model, "temperature": self.cfg["temperature"],
                "max_tokens": max(int(self.cfg.get("max_tokens") or 16), 16),
                "reasoning": self.cfg.get("reasoning") or {"enabled": False},   # reasoning models: answer, don't think
                "messages": [{"role": "user", "content": render_prompt(self.cfg["prompt"], post_text, claim)[0]}]}
        req = urllib.request.Request(self.cfg["base_url"], data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + os.environ[self.cfg["api_key_env"]]})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                out = json.loads(r.read())
            content = out["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001 — never error or skip the post
            raise GraderUnavailable(type(e).__name__) from None
        level = parse_level_or_none(content)
        if level is None:
            raise GraderEmpty("empty_reply" if not (content or "").strip() else "unparseable_reply")
        return level


JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_CRITERIA_PATH = _ROOT / "prompts" / "jev_criteria.v1.json"


def provider() -> str:
    """Grader backend: MS_FIT_GRADER_PROVIDER overrides config.json 'provider' ('openrouter' | 'typesafe')."""
    p = os.environ.get("MS_FIT_GRADER_PROVIDER", "").strip().lower()
    if not p:
        try:
            p = str(json.loads((_CFG_DIR / "config.json").read_text(encoding="utf-8")).get("provider") or "")
        except (OSError, ValueError):
            p = ""
    return "typesafe" if p.lower() == "typesafe" else "openrouter"


def load_jev_criteria(path: Optional[Path] = None) -> dict:
    raw = Path(path or JEV_CRITERIA_PATH).read_text(encoding="utf-8")
    d = json.loads(raw)
    assert set(d["criteria"]) == {"claim", "topic", "none"}, "jev criteria must be exactly claim/topic/none"
    d["_sha"] = hashlib.sha256(raw.encode()).hexdigest()
    d["_version"] = f'{d.get("version", "jev_criteria")}+{d["_sha"][:10]}'
    return d


def load_jev_cutoffs(path, criteria_sha: str) -> dict:
    """Versioned cut-offs file {criteria_sha, claim, none|topic, source}. Refuses (GraderUnavailable) when it was
    frozen against a different criteria file than the active one."""
    p = Path(path)
    p = p if p.is_absolute() else _ROOT / p
    raw = p.read_text(encoding="utf-8")
    d = json.loads(raw)
    if d.get("criteria_sha") != criteria_sha:
        raise GraderUnavailable("cutoffs_criteria_mismatch")
    d["_sha"] = hashlib.sha256(raw.encode()).hexdigest()
    return d


def decide_cutoffs(probs: dict, cut: dict) -> str:
    """DA rule (stability_eval jev_cutoffs): claim if p(claim)>=claim; else none if p(none)>=none; else topic.
    If the file gives a topic cut-off instead of none: topic if p(topic)>=topic, else none."""
    if probs["claim"] >= float(cut["claim"]):
        return "claim"
    if cut.get("none") is not None:
        return "none" if probs["none"] >= float(cut["none"]) else "topic"
    if cut.get("topic") is not None:
        return "topic" if probs["topic"] >= float(cut["topic"]) else "none"
    return "topic"


class TypeSafeGrader:
    """Jev (TypeSafe System One): one 'choice' question over claim/topic/none; level = argmax of probabilities.
    State is {post, claim, caveats}. Key from $JEV_API_KEY (never logged). Any failure → GraderUnavailable."""
    provider = "typesafe"
    api_key_env = "JEV_API_KEY"

    def __init__(self, model: str = "jev-latest", timeout: float = 15.0, criteria_path: Optional[Path] = None,
                 endpoint: str = JEV_ENDPOINT, decision: str = "argmax", cutoffs_path=None):
        if criteria_path is not None and not Path(criteria_path).is_absolute():
            criteria_path = _ROOT / criteria_path
        self.crit = load_jev_criteria(criteria_path)
        self.model, self.timeout, self.endpoint = model, timeout, endpoint
        self.decision, self.cutoffs = decision, None
        rule = "argmax"
        if decision == "cutoffs":
            self.cutoffs = load_jev_cutoffs(cutoffs_path, self.crit["_sha"])   # mismatch → GraderUnavailable
            rule = (f"cutoffs:{self.cutoffs.get('version', 'cut')}+{self.cutoffs['_sha'][:10]}"
                    f":c{self.cutoffs['claim']},n{self.cutoffs.get('none')},t{self.cutoffs.get('topic')}")
        elif decision != "argmax":
            raise GraderUnavailable("bad_decision_rule")
        self.rule = rule
        self.prompt_version = f'{self.crit["_version"]}|{rule}'   # cache key: criteria hash + rule + cut-offs
        self.last: Optional[dict] = None   # {level, probabilities, confidence, model} of the last call

    @classmethod
    def available(cls) -> bool:
        try:
            cfg = json.loads((_CFG_DIR / "config.json").read_text(encoding="utf-8"))
            cp = cfg.get("typesafe_criteria_file")
            load_jev_criteria((_ROOT / cp) if cp else None)
        except (OSError, ValueError, KeyError, AssertionError):
            return False
        return bool(os.environ.get(cls.api_key_env))

    def body(self, post_text: str, claim: str, caveats: str = "") -> dict:
        return {"model": self.model,
                "state": json.dumps({"post": post_text, "claim": claim or "", "caveats": caveats or ""},
                                    ensure_ascii=False),
                "questions": {"fit": {"type": "choice", "instructions": self.crit["instructions"],
                                      "criteria": self.crit["criteria"]}}}

    @staticmethod
    def parse(payload) -> dict:
        ans = ((payload or {}).get("answers") or {}).get("fit") or {}
        probs = ans.get("probabilities")
        if not isinstance(probs, dict) or not probs:
            raise GraderUnavailable("bad_response")
        probs = {k: float(probs.get(k, 0.0)) for k in ("claim", "topic", "none")}
        level = max(probs, key=lambda k: (probs[k], -("claim", "topic", "none").index(k)))
        return {"level": level, "choice": ans.get("choice"), "probabilities": probs,
                "confidence": ans.get("confidence"), "model": payload.get("model")}

    def __call__(self, post_text: str, claim: str, caveats: str = "") -> str:
        req = urllib.request.Request(self.endpoint, data=json.dumps(self.body(post_text, claim, caveats)).encode(),
                                     method="POST", headers={"Content-Type": "application/json",
                                                             "Authorization": "Bearer " + os.environ[self.api_key_env]})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                out = json.loads(r.read())
            self.last = self.parse(out)
            if self.cutoffs is not None:
                self.last["level"] = decide_cutoffs(self.last["probabilities"], self.cutoffs)
            self.last["decision_rule"] = self.rule
        except GraderUnavailable:
            raise
        except Exception as e:  # noqa: BLE001
            raise GraderUnavailable(type(e).__name__) from None
        return self.last["level"]


def make_grader():
    """Configured grader (provider from env override or config) or None when its key/config is missing."""
    if provider() == "typesafe":
        if not TypeSafeGrader.available():
            return None
        cfg = json.loads((_CFG_DIR / "config.json").read_text(encoding="utf-8"))
        try:
            return TypeSafeGrader(model=cfg.get("typesafe_model") or "jev-latest",
                                  criteria_path=cfg.get("typesafe_criteria_file") or None,
                                  decision=(os.environ.get("MS_FIT_GRADER_DECISION") or cfg.get("typesafe_decision")
                                            or "argmax"),   # env override: freeze sets cutoffs per server
                                  cutoffs_path=cfg.get("typesafe_cutoffs_file"))
        except (GraderUnavailable, OSError, ValueError, KeyError, AssertionError):
            return None   # bad/mismatched criteria or cut-offs → grader unavailable → word fallback
    return OpenRouterGrader() if OpenRouterGrader.available() else None


class GradeCache:
    """(post_id, asset_id, prompt_version) → level. Once graded, S never moves on re-score."""
    def __init__(self, path: Path | str):
        self.path = str(path)
        with sqlite3.connect(self.path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS fit_grades (post_id TEXT, asset_id TEXT, prompt_version TEXT,"
                      " claim_hash TEXT, model TEXT, level TEXT, graded_at TEXT DEFAULT CURRENT_TIMESTAMP,"
                      " PRIMARY KEY (post_id, asset_id, prompt_version, claim_hash))")
            if "trace" not in {r[1] for r in c.execute("PRAGMA table_info(fit_grades)")}:
                c.execute("ALTER TABLE fit_grades ADD COLUMN trace TEXT")   # {p, decision_rule} for Jev grades

    def get(self, post_id: str, asset_id: str, pv: str, ch: str) -> Optional[str]:
        with sqlite3.connect(self.path) as c:
            r = c.execute("SELECT level FROM fit_grades WHERE post_id=? AND asset_id=? AND prompt_version=?"
                          " AND claim_hash=?", (post_id, asset_id, pv, ch)).fetchone()
        return r[0] if r else None

    def put(self, post_id: str, asset_id: str, pv: str, ch: str, model: str, level: str,
            trace: Optional[dict] = None) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT OR IGNORE INTO fit_grades (post_id, asset_id, prompt_version, claim_hash, model, level,"
                      " trace) VALUES (?,?,?,?,?,?,?)",
                      (post_id, asset_id, pv, ch, model, level, json.dumps(trace) if trace else None))

    def trace(self, post_id: str, asset_id: str, pv: str, ch: str) -> Optional[dict]:
        with sqlite3.connect(self.path) as c:
            r = c.execute("SELECT trace FROM fit_grades WHERE post_id=? AND asset_id=? AND prompt_version=?"
                          " AND claim_hash=?", (post_id, asset_id, pv, ch)).fetchone()
        return json.loads(r[0]) if r and r[0] else None


def max_post_chars() -> int:
    try:
        return max(1, int(os.environ.get("MS_FIT_MAX_POST_CHARS", "2000")))
    except ValueError:
        return 2000


def votes(grader=None) -> int:
    """Grader calls per (post, asset): grader.votes, else MS_FIT_GRADER_VOTES, else config 'votes' (default 1)."""
    v = getattr(grader, "votes", None)
    if v is None:
        v = os.environ.get("MS_FIT_GRADER_VOTES")
    if v is None:
        try:
            v = json.loads((_CFG_DIR / "config.json").read_text(encoding="utf-8")).get("votes", 1)
        except Exception:  # noqa: BLE001
            v = 1
    try:
        return max(1, int(v))
    except (TypeError, ValueError):
        return 1


def combine_votes(levels: list[str]) -> str:
    """Majority: claim only with a strict majority of claim votes (2-of-3); else topic if claim+topic is a
    majority (a split claim vote downgrades to topic); else none."""
    k = len(levels) // 2 + 1
    if levels.count("claim") >= k:
        return "claim"
    if levels.count("claim") + levels.count("topic") >= k:
        return "topic"
    return "none"


def cache_version(grader) -> str:
    """Cache key version = prompt_version @ model id, so a model switch (e.g. off Grok) never reuses old grades.
    Multi-vote grades are keyed separately (#vN) from single-call grades."""
    n = votes(grader)
    return (f"{grader.prompt_version}@{getattr(grader, 'provider', 'openrouter')}:{getattr(grader, 'model', '')}"
            + (f"#v{n}" if n > 1 else ""))


def graded_level(text: str, post_id: str, asset_id: str, claim: str, grader: Grader,
                 cache: Optional[GradeCache] = None, caveats: str = "") -> tuple[str, float, str]:
    """(level, F, source). source ∈ junk | cache | model."""
    if is_obvious_junk(text):
        return "none", 0.0, "junk"
    ch = claim_hash(claim)   # tightening an asset's one_line_claim regrades
    if cache is not None:
        hit = cache.get(post_id, asset_id, cache_version(grader), ch)
        if hit:
            return hit, LEVEL_F[hit], "cache"
    try:
        gtext = text[:max_post_chars()]   # grader input capped (MS_FIT_MAX_POST_CHARS); cache key unchanged
        got = []
        for _ in range(votes(grader)):
            raw = grader(gtext, claim, caveats=caveats) if getattr(grader, "provider", "") == "typesafe" else grader(gtext, claim)
            lv = parse_level_or_none(raw)
            if lv is None:
                return "none", 0.0, "empty"     # any empty/junk vote is an error for the whole grade
            got.append(lv)
        level = got[0] if len(got) == 1 else combine_votes(got)
    except GraderEmpty:
        return "none", 0.0, "empty"         # error, not a 'none' grade: never cached
    except GraderUnavailable:
        return "none", 0.0, "unavailable"   # fail closed, not cached, so a later run regrades
    except Exception:  # noqa: BLE001 — a grader bug must not error or skip the post
        return "none", 0.0, "error"
    if cache is not None:
        last = getattr(grader, "last", None) if getattr(grader, "provider", "") == "typesafe" else None
        tr = ({"p": last.get("probabilities"), "decision_rule": last.get("decision_rule"),
               "confidence": last.get("confidence")} if isinstance(last, dict) else None)
        cache.put(post_id, asset_id, cache_version(grader), ch, grader.model, level, trace=tr)
    return level, LEVEL_F[level], "model"


def model_mode() -> bool:
    """MS_FIT_GRADED_MODE=model: the v1 grader decides (graded none → empty_fit kill even if words matched);
    the word filter is only a fallback when the grader is unavailable, errors, or the per-run cap is hit."""
    return mode() == "model"


def route() -> str | None:
    """'either' | 'model' when a word+grader route is active (no MS_FIT_GRADED needed), else None."""
    m = mode()
    return m if m in ("either", "model") else None
