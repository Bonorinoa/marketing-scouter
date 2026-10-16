"""Pre-push scrub check: the second layer over the ALLOWLIST public tree (scripts/build_public_tree.py).

Usage: python -m scripts.scrub_check TREE [--repo REPO] [--allow-file JSON] [--allow-opaque REL ...]
Exit 0 clean, 1 findings (listed), 2 usage error or a required source missing/empty (fails closed).
The repo (default: this checkout) supplies .gitignore rules, the bot/brand/self account lists, the exact-string
allowlist (scripts/scrub_allow.json) and the post corpus. The corpus is real posts only, third-party and
Augusto's (style files, echo x_samples/samples, data/x_raw, rubric/demo dumps, discovery dumps; post-text
fields of JSON dumps only). Our own docs, reports and UI test text are never corpus.

Fails on: X/Twitter status URLs with a real-size id (17+ digits; 9000000... ids are fixture ids) on x,
twitter, fxtwitter, vxtwitter, fixupx, nitter... hosts incl /i/web/status/ and percent-encoded forms; bare
snowflake ids; profile paths on those hosts; any at-handle outside tests/fixtures/ (exact allowlisted strings
and fixture_user_NN / fixture_bot_NN excepted), incl split across a line break, \\u0040 and %40 forms;
account-list handles anywhere; sk-or- / SubQ / API-key patterns (also across string concatenation); a
.handoff_secret file; email addresses incl "at/dot" obfuscation (RFC 2606 domains excepted); gitignored
files; data/ files outside DATA_ALLOW; reports/, prompts/style_augusto*, prompts/echo_calibration/, web/dist/
(all name checks case-insensitive); 12+ word runs matching the corpus after decoding JSON, \\uXXXX, %XX and
HTML entities and normalising smart quotes, zero-width chars, case and line breaks (JSON strings also
scanned joined); base64 blobs that decode to text are rescanned, others flagged; unreadable files or
folders; opaque files (images, maps, notebooks, snapshots, binaries) unless --allow-opaque for an image
under web/src/assets/; symlinks leaving the tree (never allowlistable).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SELF_HANDLE = "theholy_hermit"
# config a fresh clone needs (also the builder's REQUIRED manifest); everything else under data/ stays on the box
DATA_ALLOW = {"data/x_scout_queries.v1.json", "data/seed_inventory.json", "data/sheets_win_export_schema.md",
              "data/criterion_hints.json", "data/fit_disambiguation.json", "data/sample_inventory.json",
              "data/watchlist_sources.json", "data/voice_seeds.json", "data/xbrief-interests-seed.md"}
DATA_DIR_ALLOW = ("data/fit_grader/",)   # grader config + numbers-only cutoffs
FIXTURE_DIR = "tests/fixtures/"
FIXTURE_ID_PREFIX = "9000000"
FAKE_HANDLE_RE = re.compile(r"^fixture_(?:user|bot)_\d{2}$", re.I)
NGRAM = 12
BANNED_PREFIXES = ("reports/", "prompts/style_augusto", "prompts/echo_calibration/", "web/dist/")
OPAQUE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tif", ".tiff", ".pdf", ".zip", ".gz",
              ".tar", ".tgz", ".7z", ".map", ".ipynb", ".snap", ".sqlite", ".db", ".woff", ".woff2", ".ttf",
              ".otf", ".mp4", ".mov", ".webm", ".pyc", ".tsbuildinfo"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg"}
OPAQUE_ALLOW_DIR = "web/src/assets/"
CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".scss", ".html", ".toml"}
CODE_AT = {"media", "import", "keyframes", "font", "supports", "layer", "tailwind", "apply", "container",
           "property", "charset", "page", "param", "returns", "return", "type", "typedef", "ts", "deprecated",
           "example", "see", "throws", "default", "override", "description", "enum", "format", "summary",
           "remarks", "link", "internal", "private", "public", "readonly", "since", "todo", "fileoverview",
           "jsx", "vitest", "jest", "reboot", "yearly", "annually", "monthly", "weekly", "daily",
           "midnight", "hourly", "dataclass"}
PY_DECORATORS = {"staticmethod", "classmethod", "property", "dataclass", "pytest", "app", "router", "lru_cache",
                 "cache", "abstractmethod", "contextmanager", "wraps", "functools", "field_validator",
                 "model_validator", "validator", "overload", "cached_property", "total_ordering"}
NPM_FILES = ("package.json", "package-lock.json")
X_RESERVED = {"i", "home", "search", "intent", "settings", "explore", "hashtag", "share", "login", "messages",
              "notifications", "compose", "tos", "privacy", "en", "status"}

_CF = {chr(c) for c in (0x034F, 0x115F, 0x1160, 0x3164, 0xFFA0, 0x2800)}
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'",
                         "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"',
                         "\uff20": "@", "\uff03": "#"})
HOST = (r"(?<![A-Za-z0-9-])(?:[A-Za-z0-9-]+\.)*(?:x|twitter|fxtwitter|vxtwitter|fixupx|fixvx|twittpr|"
        r"nitter(?:\.[A-Za-z0-9-]+)*|xcancel|twstalker)\.(?:com|net|org|cz|it|poast\.org|[a-z]{2,6})")
STATUS_RE = re.compile(HOST + r"/(?:[^\s/\"'<>]+/){0,4}status(?:es)?/(\d{17,})", re.I)
SNOWFLAKE_RE = re.compile(r"(?<![\d.\-])([12]\d{17,18})(?!\d)")
STATUS_HANDLE_RE = re.compile(HOST + r"/@?([^\s/\"'<>]{1,40})/status(?:es)?(?![A-Za-z0-9_])", re.I)
XPATH_RE = re.compile(HOST + r"/@?([A-Za-z0-9_]{1,15})(?![A-Za-z0-9_])", re.I)
HANDLE_RE = re.compile(r"(?<![A-Za-z0-9_.+\-/@&])@(?!\d+\b)([A-Za-z0-9_]{1,15})(?![A-Za-z0-9_@])")
SPLIT_RE = re.compile(r"(?<![A-Za-z0-9_.+\-/@&])@([A-Za-z0-9_]{0,15})[ \t]*\r?\n[ \t>#*\-]*([A-Za-z0-9_]{1,15})")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,})\b")
OBF_EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+\-]{2,}\s*(?:\[at\]|\(at\)|\{at\}|\s+at\s+)\s*([a-z0-9\-]+)\s*"
                          r"(?:\[dot\]|\(dot\)|\{dot\}|\s+dot\s+)\s*(com|org|net|edu|io|ar|co|ai)\b")
KEY_RES = [("openrouter_key", re.compile(r"sk-or-(?:v\d-)?[A-Za-z0-9]{16,}")),
           ("subq_key", re.compile(r"(?i)\bsubq[_\-]?(?:api[_\-]?)?key\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}")),
           ("subq_key", re.compile(r"\bsq[_\-](?:live|test|sk)[_\-][A-Za-z0-9]{20,}")),
           ("api_key", re.compile(r"(?i)\b[A-Z0-9_]*(?:api[_\-]?key|secret|token)\b\s*[:=]\s*['\"]?(?=[A-Za-z0-9_\-]*\d)[A-Za-z0-9_\-]{24,}"))]
CONCAT_RE = re.compile(r"""["']\s*(?:\+|\\?\r?\n)\s*["']|["']\s*\r?\n\s*\+?\s*["']""")
SAFE_EMAIL_DOMAINS = re.compile(r"(?i)(^|\.)(example\.(com|org|net)|test|invalid|localhost|example)$")
B64_MIN = 24     # short blobs are decoded and rescanned too; only >=200-char undecodable ones are flagged
# one run of base64 chars, or a line-wrapped one (lines / adjacent string literals of base64 joined)
B64_ANY_RE = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}(?:(?:[\"']?\s*\+?\s*\\?\r?\n\s*[\"']?)[A-Za-z0-9+/]{16,}={0,2})*")
WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")
_UESC = re.compile(r"\\u([0-9a-fA-F]{4})")


class SourceError(Exception):
    """A required source (corpus, account list, git) is missing, empty or unreadable: exit 2."""


@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    detail: str
    line: int = 0

    def __str__(self) -> str:
        return f"{self.path}{':' + str(self.line) if self.line else ''}: {self.rule}: {self.detail}"


DECODE_PASSES = 8     # AT spec: exactly 8 passes; not converged by then -> decode_not_converged, exit 2
_BSLASH_RE = re.compile(r"\\+/")


class DecodeNotConverged(ValueError):
    """Text still changes after DECODE_PASSES rounds of decoding: reported as a finding, exit 2."""


def _decode_pass(text: str) -> str:
    new = _UESC.sub(lambda m: chr(int(m.group(1), 16)), text)
    new = unquote(new, errors="replace") if "%" in new else new
    new = html.unescape(new)
    return _BSLASH_RE.sub("/", new)          # \/ , \\/ , ... (JSON-escaped, double-escaped) -> /


def decode(text: str) -> str:
    """\\uXXXX escapes, %XX, HTML entities and backslash runs before / decoded to a fixpoint, at most
    DECODE_PASSES passes; still changing after that raises DecodeNotConverged (fails closed). Malformed %XX
    (e.g. 100%ff) never raises: undecodable bytes become U+FFFD and scanning continues."""
    for _ in range(DECODE_PASSES):
        new = _decode_pass(text)
        if new == text:
            return text
        text = new
    if _decode_pass(text) != text:
        raise DecodeNotConverged(f"still changing after {DECODE_PASSES} decode passes")
    return text


def normalize(text: str) -> str:
    t = decode(text).translate(_QUOTES)
    return "".join(ch for ch in t if ch not in _CF and unicodedata.category(ch) != "Cf")


def words(text: str) -> list[str]:
    ws = WORD_RE.findall(normalize(text).lower().replace("\\n", " "))
    return [w for w in ws if not w.isdigit()]


POST_KEYS = {"text", "full_text", "note_tweet", "title_or_snippet", "post_text", "quoted_text", "title"}


def _strings(obj, key: Optional[str] = None, post_only: bool = True) -> Iterable[str]:
    if isinstance(obj, str):
        if not post_only or key in POST_KEYS:
            yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if not post_only:
                yield str(k)
            yield from _strings(v, k, post_only)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, key, post_only)


def _values(obj) -> Iterable[str]:
    """String VALUES only (never keys), depth-first across nested objects and lists."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _values(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _values(v)


def _json_docs(raw: str) -> list:
    try:
        return [json.loads(raw)]
    except ValueError:
        out = []
        for l in raw.splitlines():
            try:
                out.append(json.loads(l))
            except ValueError:
                pass
        return out


def _corpus_texts(path: Path) -> list[str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise SourceError(f"corpus source {path} unreadable ({type(e).__name__})")
    if path.suffix in (".json", ".jsonl"):
        return [s for d in _json_docs(raw) for s in _strings(d)]
    return [raw]


REQUIRED_CORPUS = ["prompts/style_augusto.v1.md", "prompts/style_augusto.v2.md",
                   "prompts/echo_calibration/x_samples.md"]
CORPUS_GLOBS = ["prompts/style_augusto*", "prompts/echo_calibration/samples.md",
                "prompts/echo_calibration/x_samples.md", "data/x_raw/**/*", "data/fit_rubric*.json",
                "data/fit_rubric_*/**/*", "data/demo_candidates.json", "data/seed_score_fixtures.json",
                "data/discovery-*-posts.json", "data/discovery-*-intake-out.json"]
ACCOUNT_LISTS = ("bot_accounts.json", "brand_accounts.json", "self_accounts.json")
MAY_BE_EMPTY = {"brand_accounts.json"}      # no brand accounts yet; must still exist and parse


def corpus_files(repo: Path, strict: bool = False) -> list[Path]:
    out = set()
    for g in CORPUS_GLOBS:
        out.update(p for p in repo.glob(g) if p.is_file() and p.suffix not in OPAQUE_EXT)
    if strict:
        for r in REQUIRED_CORPUS:
            p = repo / r
            if not p.is_file() or p.stat().st_size == 0:
                raise SourceError(f"required corpus source missing or empty: {r}")
    return sorted(out)


MIN_RUNS = 150    # each required source must give at least this many 12-word runs (distinct; real files give 345+; a stub fails)


def build_corpus(files: Iterable[Path], strict: bool = False, repo: Optional[Path] = None) -> set[int]:
    grams: set[int] = set()
    per: dict[str, int] = {}
    for f in files:
        mine: set[int] = set()      # distinct runs, so a repeated stub cannot reach the floor
        for t in _corpus_texts(f):
            try:
                w = words(t)
            except DecodeNotConverged as e:
                raise SourceError(f"corpus source {f} cannot be decoded ({e})")
            for i in range(len(w) - NGRAM + 1):
                mine.add(hash(tuple(w[i:i + NGRAM])))
        grams |= mine
        per[str(f)] = len(mine)
    if strict:
        if not grams:
            raise SourceError("post corpus is empty")
        for r in REQUIRED_CORPUS if repo is not None else ():
            if per.get(str(repo / r), 0) < MIN_RUNS:
                raise SourceError(f"required corpus source {r} gives fewer than {MIN_RUNS} 12-word runs")
    return grams


def account_handles(repo: Path, strict: bool = False) -> set[str]:
    out: set[str] = set()
    for n in ACCOUNT_LISTS:
        try:
            d = json.loads((repo / "data" / n).read_text())
        except (OSError, ValueError) as e:
            if strict:
                raise SourceError(f"account list data/{n} missing or unreadable ({type(e).__name__})")
            continue
        items = d.get("handles", []) if isinstance(d, dict) else d
        if not isinstance(items, list) or (strict and not all(isinstance(h, str) for h in items)):
            if strict:
                raise SourceError(f"account list data/{n} must be a list of strings (got {type(items).__name__})")
            continue
        hs = {h.lstrip("@").lower() for h in items if isinstance(h, str) and h.strip()}
        if strict and not hs and n not in MAY_BE_EMPTY:
            raise SourceError(f"account list data/{n} is empty")
        out |= hs
    return out


GROK_FORMS = {"@grok", "@Grok", "grok"}   # public platform bot; the only string allowed outside tests/


def _sha(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


def load_allow_file(p: Path) -> dict:
    """scrub_allow.json: {"entries": [{"path", "rule", "match_sha256" | "line_sha256", "why"}]}.
    An entry suppresses only that rule in that file, for the matched string whose sha256 is match_sha256, or on
    the line (stripped) whose sha256 is line_sha256. Hashes keep the planted fakes out of the allowlist itself.
    match_sha256 placeholders are allowed only under tests/; outside tests/ only the @grok forms or a line hash."""
    if not p.exists():
        return {"entries": set()}
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        raise SourceError(f"allowlist {p} unreadable ({type(e).__name__})")
    grok = {_sha(g) for g in GROK_FORMS}
    out = set()
    for e in d.get("entries", []):
        path, rule = e.get("path"), e.get("rule")
        kinds = [k for k in ("match_sha256", "line_sha256") if k in e]
        if not path or not rule or len(kinds) != 1 or not re.fullmatch(r"[0-9a-f]{64}", str(e[kinds[0]])) \
                or set(e) - {"path", "rule", "match_sha256", "line_sha256", "why"}:
            raise SourceError(f"bad allowlist entry {e}")
        if not isinstance(path, str) or "*" in path or ".." in path.split("/") or path.startswith("/") \
                or "\\" in path:
            raise SourceError(f"allowlist path must be an exact relative path (no .., *, /, backslash): {e}")
        if kinds[0] == "match_sha256" and not path.startswith("tests/") and e["match_sha256"] not in grok:
            raise SourceError(f"allowlist placeholder outside tests/: {e}")
        out.add((path, rule, kinds[0][0], e[kinds[0]]))
    return {"entries": out}


def load_allow(repo: Path) -> dict:
    return load_allow_file(repo / "scripts" / "scrub_allow.json")


def _allowed(allow: dict, rel: str, rule: str, detail: str, line: Optional[str]) -> bool:
    ent = allow.get("entries", set())
    return (rel, rule, "m", _sha(detail)) in ent or (line is not None and (rel, rule, "l", line_sha(line)) in ent)


def gitignored(repo: Path, rels: list[str], require_git: bool = False) -> set[str]:
    if not (repo / ".git").exists():
        if require_git:
            raise SourceError(f"--repo {repo} is not a git checkout, so .gitignore rules cannot be checked")
        return set()
    if not rels:
        return set()
    r = subprocess.run(["git", "-C", str(repo), "check-ignore", "--no-index", "--stdin"], input="\n".join(rels),
                       capture_output=True, text=True, timeout=60)
    if r.returncode not in (0, 1):
        raise SourceError(f"git check-ignore failed (rc {r.returncode}): {r.stderr.strip()[:200]}")
    return {l.strip() for l in r.stdout.splitlines() if l.strip()}


def line_sha(line: str) -> str:
    return hashlib.sha256(line.strip().encode()).hexdigest()


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _is_code_at(rel: str, text: str, m: re.Match) -> bool:
    ext = os.path.splitext(rel)[1].lower()
    name = m.group(1)
    nxt = text[m.end():m.end() + 1]
    if Path(rel).name in NPM_FILES and nxt and nxt in "/-":
        return True                                           # npm scope (at-sign scope/pkg)
    if Path(rel).name.startswith("crontab") and name.lower() in CODE_AT:
        return True                                           # @reboot etc. in a crontab file
    if ext not in CODE_EXT:
        return False
    if name.lower() in CODE_AT:
        return True
    ls = text.rfind("\n", 0, m.start()) + 1
    le = text.find("\n", m.end())
    line = text[ls:le if le >= 0 else None]
    if nxt in "/-" and nxt and re.search(r"\b(import|from|require|vi\.mock)\b", line):
        return True
    if ext == ".py" and text[ls:m.start()].strip() == "":   # decorator: known name or followed by def/class/@
        if name in PY_DECORATORS:
            return True
        rest = text[le + 1:] if le >= 0 else ""
        nl = rest.lstrip().split("\n", 1)[0].strip()
        return bool(re.match(r"(async\s+def|def|class|@)\b|@", nl)) and re.fullmatch(
            r"@[\w.]+(\(.*\))?\s*", line.strip()) is not None
    return False


def _handle_ok(h: str, allow: dict) -> bool:
    return h == SELF_HANDLE or bool(FAKE_HANDLE_RE.match(h))


def scan_text(rel: str, text: str, corpus: set[int], handles: set[str], allow: Optional[dict] = None,
              depth: int = 0) -> list[Finding]:
    allow = allow or {"entries": set()}
    f: list[Finding] = []
    t = normalize(text)
    in_fixtures = rel.startswith(FIXTURE_DIR)
    lines = t.split("\n")

    def add(rule: str, detail: str, pos: Optional[int] = None) -> None:
        ln = _line(t, pos) if pos is not None else 0
        if _allowed(allow, rel, rule, detail, lines[ln - 1] if ln else None):
            return
        f.append(Finding(rel, rule, detail, ln))

    status_spans = []
    for m in STATUS_RE.finditer(t):
        status_spans.append((m.start(), m.end()))
        if not m.group(1).startswith(FIXTURE_ID_PREFIX):
            add("x_status_url", m.group(0), m.start())
    for m in STATUS_HANDLE_RE.finditer(t):     # handle part of EVERY status URL, whatever the id
        h = m.group(1)
        if h.lower() in X_RESERVED or _handle_ok(h, allow) or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", h):
            continue        # i, i/web, self, fixture_user_NN; templates like {handle} or … carry no handle
        add("x_status_handle", m.group(0), m.start())
    for m in SNOWFLAKE_RE.finditer(t):
        if not any(a <= m.start() < b for a, b in status_spans):
            add("snowflake_id", m.group(1), m.start())
    for m in XPATH_RE.finditer(t):
        h = m.group(1)
        if h.lower() in X_RESERVED or _handle_ok(h, allow) or t[m.end():m.end() + 7].lower() == "/status":
            continue
        add("x_handle_path", m.group(0), m.start())
    for m in HANDLE_RE.finditer(t):
        h = m.group(1)
        if _handle_ok(h, allow) or _is_code_at(rel, t, m):
            continue
        if h.lower() in handles:
            add("account_list_handle", "@" + h, m.start())
        elif not in_fixtures:
            add("handle", "@" + h, m.start())
    for m in SPLIT_RE.finditer(t):
        joined = m.group(1) + m.group(2)
        if _handle_ok(joined, allow) or len(joined) > 15:
            continue
        if (not m.group(1) and not in_fixtures) or (joined.lower() in handles and m.group(1).lower() not in handles):
            add("split_handle", "@" + joined, m.start())
    for h in handles:
        if h == SELF_HANDLE:
            continue
        for m in re.finditer(rf"(?<![A-Za-z0-9_@])[\"'/]{re.escape(h)}[\"'](?![A-Za-z0-9_])", t, re.I):
            add("account_list_handle", h, m.start())
    for m in EMAIL_RE.finditer(t):
        if not SAFE_EMAIL_DOMAINS.search(m.group(1)):
            add("email", m.group(0), m.start())
    for m in OBF_EMAIL_RE.finditer(t):
        add("email_obfuscated", m.group(0), m.start())
    joined_lits = CONCAT_RE.sub("", t)
    seen_keys = set()
    for src in (t, joined_lits):
        for name, rx in KEY_RES:
            for m in rx.finditer(src):
                if m.group(0) in seen_keys:
                    continue
                seen_keys.add(m.group(0))
                if _allowed(allow, rel, name, m.group(0), None):
                    continue
                add(name, m.group(0)[:12] + "…", m.start() if src is t else None)
    if depth == 0:
        for m in B64_ANY_RE.finditer(text):
            blob = re.sub(r"[\s\"'+\\]", "", m.group(0))
            if len(blob) < B64_MIN or not re.search(r"[A-Z]", blob) or not re.search(r"[a-z]", blob):
                continue        # hex digests, words, paths: not base64 text
            try:
                dec = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                if len(blob) >= 200:
                    add("base64_blob", f"{len(blob)} chars of opaque base64", m.start())
                continue
            if sum(ch.isprintable() or ch.isspace() for ch in dec) >= 0.95 * len(dec):
                f.extend(scan_text(rel, dec, corpus, handles, allow, depth=1))
    if corpus:
        texts = [text]
        if rel.lower().endswith((".json", ".jsonl")):
            docs = _json_docs(text)
            vals = [s for d in docs for s in _values(d)]
            both = [" ".join(_strings(d, post_only=False)) for d in docs]
            texts += vals + [" ".join(vals)] + both  # values alone, values joined, keys+values in document order
        seen_runs = set()
        for tx in texts:
            w = words(tx)
            i, n = 0, len(w)
            while i <= n - NGRAM:
                if hash(tuple(w[i:i + NGRAM])) in corpus:
                    j = i + 1
                    while j <= n - NGRAM and hash(tuple(w[j:j + NGRAM])) in corpus:
                        j += 1
                    run = " ".join(w[i:j + NGRAM - 1])
                    if not any(run in s or s in run for s in seen_runs):
                        seen_runs.add(run)
                        if not _allowed(allow, rel, "post_corpus_quote", run, None):
                            f.append(Finding(rel, "post_corpus_quote",
                                             f"{len(run.split())} words: \"{' '.join(run.split()[:14])}…\""))
                    i = j + NGRAM - 1
                else:
                    i += 1
    return f


def check(tree: Path, repo: Path = ROOT, allow_opaque: Iterable[str] = (), corpus: Optional[set[int]] = None,
          handles: Optional[set[str]] = None, allow: Optional[dict] = None, log=print,
          require_git: bool = False) -> list[Finding]:
    tree = Path(tree)
    allow_op = set(allow_opaque)
    corpus = build_corpus(corpus_files(repo, strict=True), strict=True, repo=repo) if corpus is None else corpus
    handles = account_handles(repo, strict=True) if handles is None else handles
    allow = load_allow(repo) if allow is None else allow
    real_tree = tree.resolve()
    findings: list[Finding] = []
    rels: list[str] = []

    def onerror(e: OSError) -> None:
        rel = Path(e.filename).resolve().relative_to(real_tree).as_posix() if e.filename else "?"
        findings.append(Finding(rel, "unreadable_dir", type(e).__name__))

    for dp, dns, fns in os.walk(tree, followlinks=False, onerror=onerror):
        for d in list(dns):
            p = Path(dp) / d
            if p.is_symlink():
                dns.remove(d)
                fns.append(d)
            elif d == ".git":
                dns.remove(d)
        for fn in fns:
            rels.append((Path(dp) / fn).relative_to(tree).as_posix())
    ign = gitignored(repo, rels, require_git)
    for rel in sorted(rels):
        p = tree / rel
        low = rel.casefold()
        if p.is_symlink():
            tgt = p.resolve()
            if not (tgt == real_tree or real_tree in tgt.parents):
                findings.append(Finding(rel, "symlink_escapes_tree", os.readlink(p)))
                continue
            if tgt.is_dir():
                continue
        if low.startswith(BANNED_PREFIXES):
            findings.append(Finding(rel, "banned_path", "never public"))
        if ".handoff_secret" in [x.casefold() for x in Path(rel).parts]:
            findings.append(Finding(rel, "handoff_secret", "secret file"))
        if low.startswith("data/") and rel not in DATA_ALLOW and not rel.startswith(DATA_DIR_ALLOW):
            findings.append(Finding(rel, "data_not_allowlisted", "data/ file outside the allowlist"))
        if rel in ign:
            findings.append(Finding(rel, "gitignored", "matched by .gitignore"))
        ext = Path(rel).suffix.lower()
        snapshot = "__snapshots__" in Path(rel).parts
        try:
            raw = p.read_bytes()
        except OSError as e:
            findings.append(Finding(rel, "unreadable", type(e).__name__))
            continue
        text = None
        if ext not in OPAQUE_EXT and not snapshot and b"\x00" not in raw[:8192]:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = None
        if text is None:
            if rel in allow_op and ext in IMAGE_EXT and rel.startswith(OPAQUE_ALLOW_DIR):
                log(f"scrub_check: opaque file allowlisted: {rel}")
            else:
                findings.append(Finding(rel, "opaque_file", "cannot be text-checked; remove it (images allowlistable "
                                                            f"only under {OPAQUE_ALLOW_DIR})"))
            continue
        try:
            findings.extend(scan_text(rel, text, corpus, handles, allow))
        except DecodeNotConverged as e:
            findings.append(Finding(rel, "decode_not_converged", str(e)))
    return findings


def main(argv: list[str]) -> int:
    args, repo, allow, allow_file = [], ROOT, [], None
    it = iter(argv)
    try:
        for a in it:
            if a == "--repo":
                repo = Path(next(it))
            elif a == "--allow-opaque":
                allow.append(next(it))
            elif a == "--allow-file":
                allow_file = Path(next(it))
            elif a.startswith("-"):
                raise StopIteration
            else:
                args.append(a)
    except StopIteration:
        args = []
    if len(args) != 1 or not Path(args[0]).is_dir():
        print(__doc__, file=sys.stderr)
        return 2
    try:
        al = load_allow_file(allow_file) if allow_file else load_allow(repo)
        found = check(Path(args[0]), repo, allow, allow=al, require_git=True)
    except SourceError as e:
        print(f"scrub_check: cannot run, {e}", file=sys.stderr)
        return 2
    for x in found:
        print(x)
    by_rule: dict[str, int] = {}
    for x in found:
        by_rule[x.rule] = by_rule.get(x.rule, 0) + 1
    print(f"scrub_check: {len(found)} finding(s)" + (f" {by_rule}" if by_rule else " - clean"))
    if any(x.rule == "decode_not_converged" for x in found):
        return 2                    # could not fully decode a file, so it was not checked: fail closed
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
