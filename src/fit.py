"""Load Fit slug vocabulary from fit-tags.md."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .models import FitSlug, VoiceDoor

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_FIT_TAGS_PATH = _DATA_DIR / "fit-tags.md"

# Fallback if markdown parse misses a row (seeded from design docs)
_FALLBACK_SLUGS: list[dict] = [
    {
        "slug": "sca-nonweird",
        "claim_one_liner": "LLM synthetic cultural agents can qualitatively track non-WEIRD experimental behavior where human data exist",
        "use_when": "LLM-as-subjects, WEIRD bias, cultural alignment, synthetic participants",
        "door": "EconLLM",
    },
    {
        "slug": "sca-pilot-ethics",
        "claim_one_liner": "SCAs are a cheap/ethical way to pilot hard-to-reach population experiments before field work",
        "use_when": "expensive RCTs, hard-to-reach samples, pilot design",
        "door": "EconLLM",
    },
    {
        "slug": "sca-rag-profiles",
        "claim_one_liner": "Cultural profiles built via scrape + RAG + system prompts beat naive persona prompts",
        "use_when": "persona prompting, RAG for agents, prompt engineering for culture",
        "door": "EconLLM",
    },
    {
        "slug": "cvp-measurement-layer",
        "claim_one_liner": "Construct validity = partial ID over a menu of measures; empty M* is a finding",
        "use_when": "LLM construct scores, Big Five-on-LLMs, which prompt is valid",
        "door": "EconLLM",
    },
    {
        "slug": "cvp-not-identification",
        "claim_one_liner": "Result lives in θ / network choice — fragility audit, not causal ID",
        "use_when": "people treating measurement audits as identification",
        "door": "EconLLM",
    },
    {
        "slug": "cvp-empty-finding",
        "claim_one_liner": "Empty admissible set under a stated nomological network is success, not a crash",
        "use_when": "failed personality batteries, collapsing traits, null robustness",
        "door": "EconLLM",
    },
    {
        "slug": "smart-surveys",
        "claim_one_liner": "LLM-assisted survey generation + text-mining insight pipeline for research design",
        "use_when": "survey design automation, AI for questionnaires",
        "door": "EconLLM",
    },
    {
        "slug": "campus-odqa",
        "claim_one_liner": "End-to-end ODQA methodology deployable in a college setting",
        "use_when": "campus AI copilots, institutional QA, edtech RAG",
        "door": "EconLLM",
    },
    {
        "slug": "gpt4o-weird",
        "claim_one_liner": "Frontier chat models' WVS-like responses cluster with WEIRD populations",
        "use_when": "cultural bias of GPT, WVS, alignment to Global South",
        "door": "EconLLM",
    },
    {
        "slug": "cheap-gen-scarce-verify",
        "claim_one_liner": "Generation/amplification is cheap; verification + local context are scarce",
        "use_when": "misinfo, Community Notes, AI and journalism, Adepa",
        "door": "Augusto-civic",
    },
    {
        "slug": "abm-nroy-policy",
        "claim_one_liner": "Honest policy reporting from simulators = range over NROY worlds, not one universe CI",
        "use_when": "ABM policy, history matching, causal ID under interference",
        "door": "EconLLM",
    },
    {
        "slug": "econllm-lab",
        "claim_one_liner": "EconLLM Lab uses games/experiments to pilot econ research and evaluate LLM preferences",
        "use_when": "EconLLM recruiting, lab methods, evaluating LLMs with games",
        "door": "EconLLM",
    },
    {
        "slug": "ai-society-governance",
        "claim_one_liner": "AI governance should shape incentives, norms and information architecture",
        "use_when": "AI regulation, social impacts, institutional design, public-interest tech",
        "door": "Augusto-civic",
    },
    {
        "slug": "verification-local-context",
        "claim_one_liner": "Cheap generation makes verified local context a scarce public good",
        "use_when": "misinformation, journalism, Community Notes, regional narrative gaps",
        "door": "Augusto-civic",
    },
    {
        "slug": "civic-policy-simulation",
        "claim_one_liner": "Simulations are decision aids when assumptions and uncertainty stay visible",
        "use_when": "digital twins, policy sandboxes, participatory modeling, municipal AI",
        "door": "EconLLM",
    },
    {
        "slug": "complexity-policy",
        "claim_one_liner": "Complex policy problems require feedback, emergence and adaptation",
        "use_when": "complexity economics, adaptive governance, policy design",
        "door": "EconLLM",
    },
    {
        "slug": "abm-organizations",
        "claim_one_liner": "ABMs connect micro rules and organizational structure to emergent outcomes",
        "use_when": "firms, networks, institutional change, org design, NetLogo",
        "door": "EconLLM",
    },
    {
        "slug": "econ-ai-cas",
        "claim_one_liner": "Economic experiments + LLM agents + CAS methods form one research program",
        "use_when": "computational social science, artificial societies, agentic economies",
        "door": "EconLLM",
    },
    {
        "slug": "synthetic-societies-validity",
        "claim_one_liner": "Artificial societies are useful only when validated across cultures and tasks",
        "use_when": "generative agents, social simulation, external validity, SCA",
        "door": "EconLLM",
    },
    {
        "slug": "human-ai-collective-action",
        "claim_one_liner": "Unit of analysis is often the human–AI information system, not the model alone",
        "use_when": "collective intelligence, platform governance, polarization, coordination",
        "door": "Augusto-civic",
    },
    {
        "slug": "ai-measurement-policy",
        "claim_one_liner": "Policy cannot outrun measurement: cheap AI proxies need construct-validity audits",
        "use_when": "algorithmic audits, scoring systems, AI evaluation, public-sector deployment",
        "door": "EconLLM",
    },
]


_ROW_RE = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
    re.MULTILINE,
)
_TOPIC_ROW_RE = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*`?([^|`]+?)`?\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
    re.MULTILINE,
)


_DOOR_CELL_RE = re.compile(r"^(?:`?(?:Augusto-civic|EconLLM)`?(?:\s*(?:or|/|,)\s*)?)+$")
_CIVIC_3COL = {"cheap-gen-scarce-verify", "verification-local-context", "ai-society-governance",
               "human-ai-collective-action"}


def _parse_fit_tags_md(text: str) -> list[FitSlug]:
    """One table row per line: | `slug` | [door |] claim | use when |. Cells never span lines (the old
    regexes let a 3-col row swallow the next line, shifting 'use when' into the claim)."""
    slugs: dict[str, FitSlug] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        m = re.fullmatch(r"`([^`]+)`", cells[0])
        if not m or len(cells) < 3:
            continue
        slug = m.group(1)
        if slug in slugs:
            continue
        if len(cells) >= 4 and _DOOR_CELL_RE.match(cells[1]):
            door_raw, claim, use = cells[1], cells[2], cells[3]
            civic = "civic" in door_raw.lower()
        else:
            claim, use = cells[1], cells[2]
            civic = slug in _CIVIC_3COL
        if not claim or "One-line" in claim:
            continue
        slugs[slug] = FitSlug(slug=slug, claim_one_liner=claim, use_when=use,
                              door=VoiceDoor.AUGUSTO_CIVIC if civic else VoiceDoor.ECONLLM)
    return list(slugs.values())


@lru_cache(maxsize=1)
def load_fit_slugs(path: str | None = None) -> tuple[FitSlug, ...]:
    """Cached Fit vocabulary. Returns immutable tuple for hashability."""
    p = Path(path) if path else _FIT_TAGS_PATH
    parsed: list[FitSlug] = []
    if p.exists():
        parsed = _parse_fit_tags_md(p.read_text(encoding="utf-8"))
    by_slug = {s.slug: s for s in parsed}
    for fb in _FALLBACK_SLUGS:
        if fb["slug"] not in by_slug:
            by_slug[fb["slug"]] = FitSlug(
                slug=fb["slug"],
                claim_one_liner=fb["claim_one_liner"],
                use_when=fb["use_when"],
                door=VoiceDoor(fb["door"]),
            )
    return tuple(by_slug.values())


def fit_slug_map(path: str | None = None) -> dict[str, FitSlug]:
    return {s.slug: s for s in load_fit_slugs(path)}


def all_slug_names(path: str | None = None) -> list[str]:
    return sorted(fit_slug_map(path).keys())


# Keyword hints for paste-path Fit matching (thread text → slugs)
_KEYWORD_HINTS: dict[str, list[str]] = {
    "sca-nonweird": [
        "weird",
        "non-weird",
        "synthetic subject",
        "synthetic participant",
        "cultural agent",
        "homo silicus",
        "llm-as-subject",
    ],
    "sca-pilot-ethics": ["pilot", "hard-to-reach", "rct", "ethical"],
    "sca-rag-profiles": ["persona", "rag", "act as", "act like"],
    "cvp-measurement-layer": [
        "construct validity",
        "big five",
        "personality llm",
        "measurement",
    ],
    "cvp-not-identification": ["identification", "specification curve", "fragility"],
    "cvp-empty-finding": ["empty set", "personality collapse", "null robustness"],
    "gpt4o-weird": ["gpt", "wvs", "world values", "cultural bias", "global south"],
    "cheap-gen-scarce-verify": [
        "community notes",
        "misinfo",
        "desinformación",
        "adepa",
        "verification",
        "journalism",
        "la gaceta",
        "verdad",
    ],
    "smart-surveys": ["survey", "questionnaire"],
    "campus-odqa": ["campus", "university qa", "edtech"],
    "complexity-policy": ["complexity", "adaptive governance", "emergence"],
    "econ-ai-cas": ["complex adaptive", "artificial societies", "agentic econom"],
    "synthetic-societies-validity": [
        "generative agents",
        "social simulation",
        "external validity",
    ],
    "ai-society-governance": [
        "ai governance",
        "ai regulation",
        "public interest",
        "ia sociedad",
    ],
    "verification-local-context": [
        "local context",
        "contexto local",
        "local journalism",
    ],
    "ai-measurement-policy": ["algorithmic audit", "scoring system", "ai evaluation"],
    "abm-organizations": ["agent-based", "abm", "netlogo", "organizational"],
    "civic-policy-simulation": ["digital twin", "policy sandbox", "policy simulation"],
    "human-ai-collective-action": [
        "collective intelligence",
        "platform governance",
        "polarization",
    ],
    "abm-nroy-policy": ["nroy", "history matching", "simulator"],
    "econllm-lab": ["econllm", "economic experiment", "llm preferences"],
}


def match_slugs_from_text(
    text: str, candidate_slugs: list[str] | None = None
) -> list[str]:
    """Return Fit slugs whose keyword hints appear in text.

    If candidate_slugs given (from matched asset), prefer intersection.
    """
    lower = (text or "").lower()
    hits: list[str] = []
    pool = candidate_slugs if candidate_slugs else list(_KEYWORD_HINTS.keys())
    for slug in pool:
        hints = _KEYWORD_HINTS.get(slug, [slug.replace("-", " ")])
        if any(h.lower() in lower for h in hints):
            hits.append(slug)
    if not hits and candidate_slugs:
        # Soft fallback: if asset has slugs and text is non-empty research-ish, use first
        research_tokens = (
            "llm",
            "ai",
            "gpt",
            "model",
            "agent",
            "survey",
            "policy",
            "validity",
            "culture",
            "economía",
            "ia ",
        )
        if any(t in lower for t in research_tokens):
            hits = list(candidate_slugs[:2])
    return hits


_CIVIC_SLUGS = frozenset(
    {
        "cheap-gen-scarce-verify",
        "verification-local-context",
        "ai-society-governance",
        "human-ai-collective-action",
    }
)


def door_for_slugs(slugs: list[str]) -> VoiceDoor:
    """Civic door if any civic slug; else EconLLM (claim-source label)."""
    if any(s in _CIVIC_SLUGS for s in slugs):
        return VoiceDoor.AUGUSTO_CIVIC
    m = fit_slug_map()
    for s in slugs:
        fs = m.get(s)
        if fs and fs.door == VoiceDoor.AUGUSTO_CIVIC:
            return VoiceDoor.AUGUSTO_CIVIC
    return VoiceDoor.ECONLLM


def claim_for_slug(slug: str) -> str:
    fs = fit_slug_map().get(slug)
    return fs.claim_one_liner if fs else slug


# ── Claim-level Fit (intake + paste) ─────────────────────────────────────────
# A bare keyword hit is not Fit. A slug is credited only when the post makes a
# claim one of the assets can answer: one specific (strong) phrase in context,
# or two distinct generic (weak) hints of the same slug. Whole-word matching,
# per-hint disambiguation negatives, and junk patterns (crypto/promo, bot logs)
# that zero Fit for the whole post (→ empty_fit).

# Generic single words: never enough alone.
_WEAK_HINTS: frozenset[str] = frozenset({
    "weird", "pilot", "rct", "ethical", "persona", "rag", "act as", "act like",
    "measurement", "identification", "fragility", "gpt", "survey", "questionnaire",
    "campus", "edtech", "complexity", "emergence", "verification", "journalism",
    "verdad", "polarization", "simulator", "organizational", "abm", "public interest",
    "misinfo",
})

# hint -> regex; if it matches anywhere in the post, that hint does not count.
_HINT_NEGATIVES: dict[str, re.Pattern] = {
    "big five": re.compile(
        r"publish|book|harpercollins|simon\s*(&|&amp;|and)\s*schuster|hachette|penguin|macmillan"
        r"|\bbanks?\b|accounting|consult|tech giants|sports?\b|league", re.I),
    "gpt": re.compile(r"\bgpt[- ]?\d", re.I),  # model-release hype ("GPT-6"), not a cultural-bias claim
    "complexity": re.compile(r"complexity science hub", re.I),
}

# Whole-post junk: crypto/token promos and automated bot run logs never carry Fit.
_JUNK_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\b(blockchains?|crypto(currency)?|altcoins?|tokenomics|airdrop|memecoin|defi|nft|"
               r"tron( dao)?|bitcoin|btc|ethereum|eth)\b", re.I),
    re.compile(r"(?m)^\s*\W*\s*(run complete|processed:\s*\d+|hit rate:|notes submitted:)", re.I),
)


def _hint_re(h: str) -> re.Pattern:
    # whole-word on both ends unless the hint is deliberately a prefix (e.g. "agentic econom")
    tail = r"\w*" if h.endswith(("econom",)) else r"(?:s|es)?\b"  # plurals ok
    return re.compile(r"(?<!\w)" + re.escape(h.lower()) + tail, re.I)


def is_junk_post(text: str) -> bool:
    t = text or ""
    return any(p.search(t) for p in _JUNK_PATTERNS)


def claim_hits(text: str, slug: str) -> tuple[list[str], list[str]]:
    """(strong_hits, weak_hits) for slug in text, after negatives."""
    lower = (text or "").lower()
    strong, weak = [], []
    for h in _KEYWORD_HINTS.get(slug, [slug.replace("-", " ")]):
        if not _hint_re(h).search(lower):
            continue
        neg = _HINT_NEGATIVES.get(h.lower())
        if neg and neg.search(text or ""):
            continue
        (weak if h.lower() in _WEAK_HINTS else strong).append(h)
    return strong, weak


_HASHTAG_RE = re.compile(r"(?<!\w)#\w+")
_QUOTE_RE = re.compile(r'"[^"\n]{3,}"|\u201c[^\u201d]{3,}\u201d|&quot;.{3,}?&quot;')


def split_quoted(text: str) -> tuple[str, str]:
    """(text outside quotes, quoted text)."""
    t = text or ""
    quoted = " ".join(m.group(0) for m in _QUOTE_RE.finditer(t))
    return _QUOTE_RE.sub(" ", t), quoted


def claim_match(text: str, pool: list[str]) -> list[str]:
    """Closed-vocab claim-level Fit match. No soft fallback, no borrowing outside pool.

    Hashtag tokens (#AI, #survey) count zero toward the two-generic-words rule.
    Quoted text counts once: every hint found only inside quotes adds at most one generic hit.
    """
    if is_junk_post(text):
        return []
    outside, quoted = split_quoted(text)
    no_tags = _HASHTAG_RE.sub(" ", outside)
    out = []
    for slug in pool:
        strong, _w = claim_hits(outside, slug)
        _s, weak = claim_hits(no_tags, slug)
        qs, qw = claim_hits(quoted, slug) if quoted else ([], [])
        q_extra = 1 if (set(qs) | set(qw)) - set(strong) - set(weak) else 0
        if strong or len(set(weak)) + q_extra >= 2:
            out.append(slug)
    return out


# ── Researcher pre-filter (data/fit_disambiguation.json), runs BEFORE claim_match ──
_DISAMBIG_PATH = _DATA_DIR / "fit_disambiguation.json"


@lru_cache(maxsize=1)
def load_disambiguation() -> dict:
    import json
    try:
        return json.loads(_DISAMBIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _has_term(text: str, term: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(term) + r"(?:s|es)?(?!\w)", text or "", re.I) is not None


def prefilter(text: str, pool: list[str]) -> list[str]:
    """Slugs in pool that survive the Researcher required/excluded terms (global exclude → [])."""
    d = load_disambiguation()
    if any(_has_term(text, t) for t in d.get("_global_exclude", [])):
        return []
    out = []
    for slug in pool:
        rule = d.get(slug) or {}
        if any(_has_term(text, t) for t in rule.get("exclude", [])):
            continue
        need = rule.get("needs_any")
        # needs_any is English-only; a slug's own specific (strong) hint also satisfies it
        # so Spanish civic posts ("contexto local", "desinformación") aren't pre-killed.
        own_strong = [h for h in _KEYWORD_HINTS.get(slug, []) if h.lower() not in _WEAK_HINTS]
        if need and not any(_has_term(text, t) for t in list(need) + own_strong):
            continue
        out.append(slug)
    return out


_claim_match_core = claim_match


def claim_match(text: str, pool: list[str]) -> list[str]:  # noqa: F811 — prefilter first, then claim level
    return _claim_match_core(text, prefilter(text, pool))
