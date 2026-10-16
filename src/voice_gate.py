"""Draft voice gate: pure pass/block check for x-brief drafts before they render.

The gate never edits a draft. It returns GateResult(ok, reasons); each reason is
{"code": <stable code>, "message": <plain text the UI shows as is>}.
No I/O except reading slug claims from fit-tags.md (via src.fit) when the card
does not supply them. No posting capability, ever.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit, parse_qsl, unquote
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

CODES = (
    "lang_mismatch",
    "cta_bait",
    "claim_missing",
    "claim_restated",
    "door_mix",
    "too_long",
    "invented_metric",
    "empty_draft",
    "door_missing",
    "caveat_dropped",
    "caveat_in_draft",
    "claim_overlap",
    "quote_cue_opener",
    "x_handle",
    "x_hashtag",
    "x_emoji",
)
TAG_KEYS = ("has_profanity", "has_put_down")   # log-only (Augusto 10-16): never block, never affect ok
CLAIM_OVERLAP_MAX = 0.6   # draft may reuse < 60% of a claim's content words (claim_echo tokenizer)
CLAIM_OVERLAP_MIN_WORDS = 5
WARNING_CODES = ("possible_metric", "claim_negated", "lang_uncertain")
VALID_DOORS = {"EconLLM", "Augusto-civic"}

ENGLISH_OUTLETS = {"x", "linkedin"}
SPANISH_OUTLETS = {"oped", "op-ed", "carta"}
OUTLET_LABEL = {"x": "X", "linkedin": "LinkedIn", "oped": "op-ed", "op-ed": "op-ed", "carta": "carta"}
X_MAX = 280
LINKEDIN_MAX = 3000
URL_WEIGHT = 23
# X drafts: no @handles (any position, incl. stacked leading reply handles), no hashtags, no emoji.
# Checked on normalize_text() output (NFKC + zero-width stripped), so '@\u200bfoo' and fullwidth '＠foo' count.
# twitter-text mention rule: '@' not preceded by [A-Za-z0-9_!#$%&*@] (so '.@h', 'x.@h', '...@h' DO link),
# no space after '@' ('$5 @ 3%', 'meet @ 5pm' are prose).
_X_HANDLE_RE = re.compile(r"(?<![A-Za-z0-9_!#$%&*@])@[A-Za-z0-9_]{1,15}(?![A-Za-z0-9_]*@)")
_X_HASHTAG_RE = re.compile(r"(?<![\w&/#])#[^\W\d_][\w]*|(?<![\w&/#])#\d+[^\W\d][\w]*")
# Emoji = Emoji_Presentation chars (default-emoji) + any char followed by VS16 (U+FE0F) or keycap (U+20E3).
# Text-default symbols (✓ ✗ ★ ⚠ ⌘ ⌈⌉ ➜ ☺ © ™) pass unless a VS16 makes them emoji.
_EMOJI_PRESENTATION = (
    "\U0001F000-\U0001FAFF"                      # mahjong .. symbols & pictographs ext-A (incl. flags, skin tones)
    "\u231A\u231B\u23E9-\u23EC\u23F0\u23F3\u25FD\u25FE\u2614\u2615\u2648-\u2653\u267F\u2693\u26A1"
    "\u26AA\u26AB\u26BD\u26BE\u26C4\u26C5\u26CE\u26D4\u26EA\u26F2\u26F3\u26F5\u26FA\u26FD\u2705"
    "\u270A\u270B\u2728\u274C\u274E\u2753-\u2755\u2757\u2795-\u2797\u27B0\u27BF\u2B1B\u2B1C\u2B50\u2B55"
)
_X_EMOJI_RE = re.compile(f"[{_EMOJI_PRESENTATION}]|.[\uFE0F\u20E3]", re.S)

_TLDS = ("com|org|net|edu|gov|io|ly|ai|dev|co|me|app|info|biz|xyz|site|link|page|example|"
         "ar|uk|us|es|mx|br|de|fr|eu|ca|au|in|tv|gg|to|so|sh|cc|news|blog|online|tech|lab|pub")
_URL_RE = re.compile(
    rf"(?:https?://[^\s<>\"']+)|(?:\b(?:www\.)?(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:{_TLDS})\b(?:/[^\s<>\"']*)?)",
    re.I,
)
_ZW_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")  # kept for callers; normalize_text strips all Cf


# Invisible but not Cf: CGJ (Mn), Hangul fillers (Lo), braille blank (So).
_EXTRA_INVISIBLE = frozenset("\u034f\u115f\u1160\u3164\uffa0\u2800")


def _is_invisible(ch: str) -> bool:
    return ch in _EXTRA_INVISIBLE or unicodedata.category(ch) == "Cf"


def _strip_cf(t: str, repl: str = "") -> str:
    """Drop (or replace with repl) every Unicode format char (Cf) plus the _EXTRA_INVISIBLE set."""
    return "".join(repl if _is_invisible(ch) else ch for ch in t)


def normalize_text_spaced(text: str) -> str:
    """Like normalize_text, but invisibles become a space. X sees the raw text, where an invisible
    char before @/# is a boundary, so handle/hashtag checks run on this variant too."""
    return _strip_cf(unicodedata.normalize("NFKC", _strip_cf(text or "", " ")), " ")
_WORD_RE = re.compile(r"[a-záéíóúñü]+", re.I)

_EN_STOP = set("the and of to is in that it for on with as are this be not but by from at or have an they which you we was their more can if about what so".split())
_ES_STOP = set("el la los las de que y en un una es por con para del al lo se no su sus como más pero sino nos ya muy sin sobre entre también cuando porque está son hay".split())

_CTA_PATTERNS = [
    r"\bdm me\b", r"\bdm for\b", r"\blink in (my )?bio\b", r"\bfollow me\b", r"\bfollow for more\b",
    r"\bsubscribe\b", r"\bcheck out my\b", r"\bsign up\b", r"\bjoin my\b", r"\bsmash that\b",
    r"\bescribime\b", r"\bescríbeme\b", r"\bmandame (un )?(md|dm|mensaje)\b", r"\bmd\b",
    r"\blink en (mi )?bio\b", r"\bseguime\b", r"\bsígueme\b", r"\bsigueme\b",
    r"\bsuscrib[íi]te\b", r"\bsuscr[íi]bete\b", r"\bmir[aá] mi\b", r"\bchequ?e[aá] mi\b",
    r"\bregistr[aá]te\b", r"\binscrib[íi]te\b",
]
_CTA_RE = re.compile("|".join(_CTA_PATTERNS), re.I)

# Engagement bait: imperative at sentence start + up to 6 words + a reward hook.
_SENT_START = r"(?:^|(?<=[.!?\n:;])\s*|(?<=[.!?]\s))"
_ENGAGE_RE = re.compile(
    _SENT_START
    + r"(?:reply|comment|type|drop|like|rt|retweet|repost|share)\b[^.!?\n]{0,60}?"
      r"\b(?:and i'?\s?ll|and i will|to get|for (?:the|my|a|access|a copy|more|free))\b"
    + r"|" + _SENT_START
    + r"(?:respond[eé]|coment[aá]|escrib[ií]|escribe|dej[aá]|compart[ií]|comparte|dale like)\b[^.!?\n]{0,60}?"
      r"(?:\by te (?:lo |la )?(?:env[ií]o|mando|paso)\b|\bpara recibir\b)",
    re.I | re.M,
)

_LAB_BRAND_RE = re.compile(r"\beconllm\b|\bour lab\b|\bnuestro laboratorio\b|\bsca pilots?\b", re.I)
_CIVIC_OPED_RE = re.compile(r"\b(op-?ed|carta de lectores|carta abierta|columna de opini[oó]n|as a concerned citizen|como ciudadano)\b", re.I)

_WORD_METRIC_RE = re.compile(
    r"\b(?:(?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|a hundred|hundred)[- ]?(?:\w+ )?(?:percent|per cent|times|fold)"
    r"|doubl\w*|tripl\w*|quadrupl\w*|half as|twice as|(?:twice|thrice)\b"
    r"|(?:dos|tres|cuatro|cinco|diez) veces|el doble|el triple|la mitad"
    r"|(?:diez|veinte|treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa|cien)\w* por ciento)",
    re.I,
)
_NEG_RE = re.compile(r"\b(?:not|don'?t|doesn'?t|didn'?t|never|fails? to|no|nunca|cannot|can'?t|won'?t|isn'?t|aren'?t)\b", re.I)

_METRIC_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(%|x\b|×|times\b|veces\b)", re.I)

_STOP_TERMS = _EN_STOP | _ES_STOP | set(
    "llm llms ai model models via build built use uses using one both only not cheap make makes".split()
)


@dataclass
class GateResult:
    ok: bool
    reasons: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)  # never affect ok
    tags: dict[str, Any] = field(default_factory=dict)            # log-only telemetry; never affect ok

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "reasons": list(self.reasons), "warnings": list(self.warnings), "tags": dict(self.tags)}


def normalize_text(text: str) -> str:
    """NFKC (folds math-alphanumeric + roman-numeral lookalikes), strip all format chars (Unicode Cf).
    Used only for checking; the draft itself is never changed."""
    return _strip_cf(unicodedata.normalize("NFKC", _strip_cf(text or "")))


def collapse_letters(text: str) -> str:
    """Punctuation -> space, then join runs of single letters: 'D.M. me' / 'D M me' -> 'DM me'."""
    t = re.sub(r"[^\w\s]|_", " ", text)
    t = re.sub(r"\s+", " ", t)
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r"(?<!\w)([^\W\d_]) (?=[^\W\d_](?!\w))", r"\1", t)
    return t


def _strip_trailing(u: str) -> str:
    return u.rstrip(".,;:!?)]}'\"")


def normalize_url(u: str) -> tuple[str, str, str] | None:
    u = _strip_trailing(u)
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    try:
        sp = urlsplit(u)
    except ValueError:
        return None
    host = (sp.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = sp.path.rstrip("/")
    return ("https" if sp.scheme.lower() in ("http", "https") else sp.scheme.lower(), host, path)


_DOMAINISH_RE = re.compile(rf"(?:[a-z0-9-]+\.)+(?:{_TLDS})\b", re.I)


def _carries_url(value: str) -> bool:
    v = value
    for _ in range(3):  # decode nested percent-encoding
        v = unquote(v)
    v = v.lower()
    return ("://" in v or "http" in v or "//" in v or "%2f%2f" in value.lower()
            or bool(_DOMAINISH_RE.search(v)))


def safe_query_fragment(u: str) -> bool:
    """Only utm_* params whose values carry no URL; fragment must carry no URL."""
    try:
        sp = urlsplit(_strip_trailing(u) if re.match(r"^https?://", u, re.I) else "https://" + _strip_trailing(u))
    except ValueError:
        return False
    if sp.query:
        for k, v in parse_qsl(sp.query, keep_blank_values=True):
            if not k.lower().startswith("utm_") or _carries_url(v) or _carries_url(k):
                return False
        if any(not part or "=" not in part for part in sp.query.split("&")):
            return False
    if sp.fragment and _carries_url(sp.fragment):
        return False
    return True


@dataclass
class DraftCard:
    """What the gate needs about a card. Build it from the sealed handoff payload."""
    outlet: str                       # "x" | "linkedin" | "oped" | "carta"
    door: str                         # "Augusto-civic" | "EconLLM"
    slugs: list[str] = field(default_factory=list)   # matched/active Fit slugs
    asset_title: str = ""
    asset_url: Optional[str] = None
    asset_claim: Optional[str] = None  # asset one_line_claim
    slug_claims: Optional[dict[str, str]] = None  # override; else read from fit-tags.md
    asset_caveat: Optional[str] = None  # the card's own caveat field (shown next to the claim, never in the draft)
    evidence_grade: Optional[str] = None  # "A" | "B" | "C"; Grade B needs a caveat


def _get(card: Any, key: str, default=None):
    if isinstance(card, Mapping):
        return card.get(key, default)
    return getattr(card, key, default)


def _norm_card(card: Any) -> DraftCard:
    if isinstance(card, DraftCard):
        return card
    door = _get(card, "door") or _get(card, "voice_door") or _get(card, "door_archive") or ""
    outlet = _get(card, "outlet") or "x"
    return DraftCard(
        outlet=str(getattr(outlet, "value", outlet)).lower(),
        door=str(getattr(door, "value", door)),
        slugs=list(_get(card, "slugs") or []),
        asset_title=_get(card, "asset_title") or _get(card, "title") or "",
        asset_url=_get(card, "asset_url") or _get(card, "url"),
        asset_claim=_get(card, "asset_claim") or _get(card, "one_line_claim"),
        slug_claims=_get(card, "slug_claims"),
        asset_caveat=_get(card, "asset_caveat") or _get(card, "caveat"),
        evidence_grade=(lambda g: str(getattr(g, "value", g)).upper() if g else None)(_get(card, "evidence_grade")),
    )


def _slug_claims(c: DraftCard) -> list[str]:
    if c.slug_claims is not None:
        return [c.slug_claims[s] for s in c.slugs if s in c.slug_claims]
    from src.fit import fit_slug_map  # lazy: keeps the module importable standalone
    m = fit_slug_map()
    return [m[s].claim_one_liner for s in c.slugs if s in m]


def detect_language(text: str) -> str:
    """'en', 'es' or 'unknown' via stopword ratios (dependency-free)."""
    words = [w.lower() for w in _WORD_RE.findall(_URL_RE.sub(" ", text))]
    if not words:
        return "unknown"
    en = sum(w in _EN_STOP for w in words)
    es = sum(w in _ES_STOP for w in words)
    accents = len(re.findall(r"[áéíóúñ¿¡]", text, re.I))
    es += accents * 0.5
    if en + es < 2:
        return "unknown"
    if en >= es * 1.5:
        return "en"
    if es >= en * 1.5:
        return "es"
    return "unknown"


def x_length(text: str) -> int:
    return len(_URL_RE.sub("x" * URL_WEIGHT, text))


def _stem(w: str) -> str:
    w = w.lower()
    for suf in ("ation", "ción", "ing", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _negated_claim(text: str, claim_terms: set[str]) -> Optional[str]:
    """Return the negation word if one sits within 3 words before a claim term."""
    words = re.findall(r"[\w'’]+", text.lower().replace("’", "'"))
    for i, w in enumerate(words):
        if _NEG_RE.fullmatch(w) or (w in ("fail", "fails") and i + 1 < len(words) and words[i + 1] == "to"):
            window = words[i + 1 : i + 4]
            if any(_stem(x) in claim_terms for x in window if len(x) >= 4):
                return w
    return None


def _terms(text: str) -> set[str]:
    return {_stem(w) for w in _WORD_RE.findall(text or "") if len(w) >= 4 and w.lower() not in _STOP_TERMS}


_QUOTE_CUE_RE = re.compile(r"^\s*(?:re\s*:|[\"“”«„'‘])", re.I)


def opens_on_quote_cue(text: str) -> bool:
    """True when a draft opens with "Re:" or a quote of the post instead of answering it (Designer P1 #6)."""
    return bool(_QUOTE_CUE_RE.match(normalize_text(re.sub(r"https?://\S+", " ", text or ""))))


def first_sentence(text: str) -> str:
    """Leading sentence for claim_restated (URLs stripped)."""
    t = normalize_text(re.sub(r"https?://\S+", " ", text or "")).strip()
    if not t:
        return ""
    parts = re.split(r"(?<=[.!?…])\s+", t, maxsplit=1)
    return (parts[0] if parts else t).strip()


def claim_restated(draft_text: str, claims: list[str]) -> bool:
    """True when the draft's first sentence near-verbatim restates a claim (Designer P2 #7).

    Paraphrases that reuse a few claim terms are fine; leading with the claim itself is not.
    """
    from .claim_echo import _tokens, is_echo, run_score
    first = first_sentence(draft_text)
    if not first:
        return False
    ft = _tokens(first)
    if not ft:
        return False
    for c in claims:
        c = (c or "").strip()
        if not c:
            continue
        a = " ".join(normalize_text(first).lower().split())
        b = " ".join(normalize_text(c).lower().split()).rstrip(".")
        if b and (a == b or a.rstrip(".") == b or a.startswith(b + " ") or a.startswith(b + ",")
                  or a.startswith(b + "—") or a.startswith(b + " -") or a.startswith(b + " –")):
            return True
        if not is_echo(first, c) and run_score(first, c) < 0.6:
            continue
        ct = _tokens(c)
        if not ct:
            continue
        # Near-verbatim: most of the first sentence is claim words (not a longer framed reply)
        overlap = len(set(ft) & set(ct)) / max(len(set(ft)), 1)
        if overlap >= 0.65 or run_score(first, c) >= 0.7:
            return True
    return False



def _flat(s: str) -> str:
    return " ".join(normalize_text(s or "").lower().split())


def caveat_in(text: str, caveat: str) -> bool:
    c = _flat(caveat).rstrip(".")
    return bool(c) and c in _flat(text)


def strip_caveat(text: str, caveat: Optional[str]) -> str:
    """Remove a verbatim caveat (case/space-insensitive) from draft text; it belongs in the card field."""
    cav = (caveat or "").strip()
    if not text or not cav:
        return text
    words = [re.escape(w) for w in normalize_text(cav).rstrip(".").split()]
    pat = re.compile(r"\s*" + r"\s+".join(words) + r"\.?", re.I)
    return re.sub(r"\s{2,}", " ", pat.sub(" ", normalize_text(text))).strip()


def claim_overlap(draft_text: str, claim: str) -> float:
    """Share of the claim's content words present in the draft, via claim_echo's own tokenizer."""
    from .claim_echo import _tokens, content_words
    cw = content_words(claim or "")
    if len(cw) < CLAIM_OVERLAP_MIN_WORDS:
        return 0.0
    return len(cw & set(_tokens(draft_text or ""))) / len(cw)


# ---- Swearing and put-downs: LOG-ONLY tags (Augusto 10-16: don't block bad words or roasts). Every outlet.
# Tokens are checked after NFKC/Cf stripping, lowercasing, leetspeak folding (0->o, 1/!->i, 3->e, 4/@->a, 5/$->s,
# 7->t), with letter runs collapsed (fuuuck -> fuck), masked letters (f*ck, f**k, sh#t) treated as wildcards, and
# spaced/dotted letters joined (f.u.c.k). Word-boundary matching only, so Scunthorpe, class, assess, cocktail pass.
_SWEAR_STEMS = ("fuck", "motherfuck", "clusterfuck", "shit", "bullshit", "horseshit", "cunt", "twat", "bitch",
                "bastard", "asshole", "arsehole", "dickhead", "wank", "prick", "piss", "goddamn", "dumbass", "jackass")
_SWEAR_SUFFIX = r"(?:s|es|ed|er|ers|ing|in|y|ty|tier|tiest|head|heads|face|show|storm|load|off|wit|wits)?"
_SWEAR_EXACT = {"wtf", "stfu", "gtfo", "fck", "fk", "fkn", "fkin", "fking", "fcking", "fuk", "fuking", "sht", "shyt",
                "mf", "mofo", "bs", "freaking", "freakin", "fricking", "frickin", "frigging", "friggin", "fkng", "bullsh", "damnit", "dammit", "crap", "crappy"}
_PUTDOWN_WORDS = ("clown", "idiot", "idiotic", "moron", "moronic", "imbecile", "cretin", "dimwit", "nitwit", "halfwit",
                  "dunce", "buffoon", "loser", "grifter", "dipshit", "numbskull", "dumbo", "clownish", "copium")
_PUTDOWN_RE_WORD = re.compile(r"^(?:" + "|".join(_PUTDOWN_WORDS) + r")s?$")
_SWEAR_RE_WORD = re.compile(r"^(?:" + "|".join(_SWEAR_STEMS) + ")" + _SWEAR_SUFFIX + "$")
_LEET = str.maketrans({"0": "o", "1": "i", "!": "i", "3": "e", "4": "a", "@": "a", "5": "s", "$": "s", "7": "t"})
_LEET_L = str.maketrans({"0": "o", "1": "l", "!": "l", "|": "l", "3": "e", "4": "a", "@": "a", "5": "s", "$": "s", "7": "t"})
_MASK = "*#%"
_TOKEN_RE = re.compile(r"[a-z0-9@$!*#%]+(?:'[a-z]+)?")
_PUTDOWN_PHRASES = re.compile(
    r"\bshut\s+(?:the\s+\S+\s+|your\s+\S+\s+)?up\b|\bgo\s+to\s+hell\b|\bget\s+(?:a\s+clue|lost|a\s+brain)\b"
    r"|\bkys\b|\b(?:you|ya|u)(?:'re|\s+are|\s+r)?\s+(?:(?:so|such|an?|absolute|total|complete|fucking|utter)\s+)*"
    r"(?:stupid|dumb|pathetic|clueless|braindead|brain-dead|ignorant|delusional|clowns?|idiots?|morons?|fools?|losers?)\b"
    r"|\b(?:you|ya|u)\s+(?:(?:absolute|total|complete|utter|fucking)\s+)*(?:fools?|clowns?)\b",
    re.I)
# 'cope' and 'bs' read as a put-down in a reply ("not cope", "that's bs"); 'cope with', 'coping with', 'BS degree',
# 'BS in physics', 'BS/MS' and 'B.S.' (uppercase degree forms) pass.
_COPE_RE = re.compile(r"\b(?:cope|copes|coping|coper|copers|copium|copey)\b(?!\s+(?:\w+\s+){0,2}with\b)", re.I)
_BS_DEGREE_RE = re.compile(r"\b(?:B\.S\.|BS|BSc|B\.Sc\.)(?=\s*(?:degree|in\b|from\b|/|,?\s*(?:MS|MA|PhD)\b|program|student|holder))")


def _squeeze(w: str) -> str:
    return re.sub(r"(.)\1+", r"\1", w)


def _mask_match(tok: str, rx: re.Pattern) -> bool:
    """'f*ck' / 'f***ing' / 'sh#t': each mask run stands for 1..n+1 letters; check every stem form."""
    if not any(m in tok for m in _MASK) or not re.search(r"[a-z]", tok) or len(tok) < 3:
        return False
    stems = list(_SWEAR_STEMS) + list(_PUTDOWN_WORDS)
    pat = "".join(f"[a-z]{{1,{len(run) + 1}}}" if run[0] in _MASK else re.escape(run)
                  for run in re.findall(r"[*#%]+|[^*#%]+", tok))
    w = re.compile(pat + "$")
    return any(w.match(st + suf) for st in stems for suf in ("", "s", "ing", "in", "ed", "er", "y", "ty"))


# Cyrillic/Greek look-alikes -> Latin (NFKC leaves them alone), for tagging only
_CONFUSABLES = str.maketrans({
    "а": "a", "с": "c", "е": "e", "о": "o", "р": "p", "х": "x", "у": "y", "ѕ": "s", "і": "i", "ј": "j", "ԁ": "d",
    "һ": "h", "ӏ": "l", "к": "k", "м": "m", "т": "t", "н": "h", "в": "b", "ԝ": "w", "ո": "n", "ս": "u",
    "А": "A", "С": "C", "Е": "E", "О": "O", "Р": "P", "Х": "X", "У": "Y", "Ѕ": "S", "І": "I", "Ј": "J", "К": "K",
    "М": "M", "Т": "T", "Н": "H", "В": "B",
    "ο": "o", "α": "a", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
    "Ο": "O", "Α": "A", "Ε": "E", "Ι": "I", "Κ": "K", "Ν": "N", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
})
# Normal prose that must never be tagged (AT fd231c4 #4)
_ABUSE_EXEMPT_RE = re.compile(
    r"\bwinners\s+and\s+losers\b|\blosers?\s+from\b|\bloser[-\s]pays\b|\bcoping\s+(?:strateg\w*|mechanism\w*|skills?|style\w*)\b"
    r"|\bidiot\s+index\b|\bclown\s*fish\w*\b|\bgrifter\s+literature\b|\bbastard\s+wing\b"
    r"|\bbs\s+(?:test|degree|in\b|from\b)",
    re.I)
_QUOTED_WORD_RE = re.compile(r"[\"“”'‘’«»]\s*[^\s\"“”'‘’«»]+\s*[\"“”'‘’«»]")
# Short tokens that are also acronyms: only lowercase counts (MF-DFA, FK model, SHT table, BS degree stay clean)
_CASE_SENSITIVE_SHORT = {"mf", "fk", "sht", "bs", "af", "tf", "ffs", "gtfoh", "fkn"}
_SWEAR_EXTRA = {"af", "ffs", "tf", "gtfoh", "dumbfuck", "asshat", "assclown", "fuckwit", "shithead", "dumbfuk",
                # Spanish (Rioplatense included)
                "mierda", "carajo", "forro", "forra", "puto", "puta", "pelotudo", "pelotuda", "pelotudez", "boludo",
                "boluda", "boludez", "concha", "conchudo", "conchuda", "cagada", "pendejo", "pendeja", "gilipollas"}
_PUTDOWN_EXTRA = {"midwit", "midwits", "clownery", "idiocy", "idiota", "idiotas", "imbecil", "imbeciles", "tarado",
                  "tarada", "estupido", "estupida", "ignorante"}
_PUTDOWN_PHRASES2 = re.compile(
    r"\bimagine\s+(?:believing|thinking)\b|^\s*ratio\s*[.!]*\s*$|(?<!\w)ratio\s*[.!]*\s*$|\bL\s+take\b"
    r"|\b(?:dumb|stupid|braindead|brain-dead|idiotic|moronic|clown)\s+(?:take|paper|argument|post|research|idea)s?\b"
    r"|\bdo\s+better\s*[.!]*\s*$|\beff\s+off\b|\bla\s+concha\b",
    re.I | re.M)


def _abuse_prep(text: str) -> str:
    t = normalize_text(text).translate(_CONFUSABLES)
    t = "".join(ch for ch in unicodedata.normalize("NFKD", t) if not unicodedata.combining(ch))
    t = _ABUSE_EXEMPT_RE.sub(" ", t)
    t = _QUOTED_WORD_RE.sub(" ", t)               # a quoted single word is a mention ("the 'cope' framing")
    return re.sub(r"(?<=[A-Za-z0-9*])_+(?=[A-Za-z0-9*])", "", t)   # sh_it / f_u_c_k


def _abuse_tokens(text: str) -> list[str]:
    """Tokens with their original case (lowercased per check)."""
    return [t.split("'")[0] for t in re.findall(r"[A-Za-z0-9@$!*#%]+(?:'[A-Za-z]+)?", text.replace("’", "'"))]


def abuse_hits(text: str) -> tuple[Optional[str], Optional[str]]:
    """-> (profanity word, put-down phrase); None when clean. LOG-ONLY tagging; checking copy only."""
    t = _abuse_prep(text)
    joined = collapse_letters(t)   # f.u.c.k / f u c k -> fuck
    prof = put = None
    for src in (t, joined):
        for orig in _abuse_tokens(src):
            tok = orig.lower()
            if "@" in tok and not tok.strip("@"):
                continue
            forms = {tok} if tok.isdigit() else {tok.translate(_LEET), tok.translate(_LEET_L)}
            for cand in forms | {_squeeze(f) for f in forms}:
                if not cand or not re.search(r"[a-z]", cand):
                    continue
                if cand in _CASE_SENSITIVE_SHORT and not orig.islower():
                    continue   # acronym (MF, FK, SHT, BS)
                if (_SWEAR_RE_WORD.match(cand) or _SWEAR_RE_WORD.match(_squeeze(cand)) or cand in _SWEAR_EXACT
                        or cand in _SWEAR_EXTRA):
                    prof = prof or orig
                elif _PUTDOWN_RE_WORD.match(cand) or _PUTDOWN_RE_WORD.match(_squeeze(cand)) or cand in _PUTDOWN_EXTRA:
                    put = put or orig
            if prof is None and _mask_match(tok, _SWEAR_RE_WORD):
                prof = orig
    if prof is None and re.search(r"(?<![A-Za-z])b\.\s?s\.(?![A-Za-z])", t) and not _BS_DEGREE_RE.search(t):
        prof = "b.s."
    m = (_PUTDOWN_PHRASES.search(t) or _PUTDOWN_PHRASES2.search(t)
         or _PUTDOWN_PHRASES.search(" ".join(_squeeze(w.translate(_LEET)) for w in t.split())))
    if m:
        put = put or m.group(0)
    c = _COPE_RE.search(t)
    if c:
        put = put or c.group(0)
    return prof, put


def check_draft(draft_text: str, card: Any) -> GateResult:
    c = _norm_card(card)
    text = normalize_text(draft_text or "")  # checking copy only; draft_text is never changed
    collapsed = collapse_letters(text)
    reasons: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def block(code: str, msg: str) -> None:
        reasons.append({"code": code, "message": msg})

    def warn(code: str, msg: str) -> None:
        warnings.append({"code": code, "message": msg})

    if c.door not in VALID_DOORS:
        block("door_missing", "This card has no voice set; pick EconLLM or Augusto-civic.")

    prof, put = abuse_hits(draft_text or "")   # log-only tags, never a block
    tags = {"has_profanity": bool(prof), "has_put_down": bool(put)}

    if not text.strip():
        block("empty_draft", "The draft is empty.")
        return GateResult(False, reasons, tags=tags)

    outlet = c.outlet.lower()
    label = OUTLET_LABEL.get(outlet, outlet)
    civic = c.door == "Augusto-civic"

    # 1. Language by outlet
    lang = detect_language(text)
    if outlet in ENGLISH_OUTLETS and lang == "es":
        block("lang_mismatch", f"This {label} draft looks Spanish; {label} posts are English-only.")
    elif outlet in SPANISH_OUTLETS and lang == "en":
        block("lang_mismatch", f"This {label} draft looks English; {label} pieces are Spanish-only.")
    elif lang == "unknown" and (outlet in ENGLISH_OUTLETS or outlet in SPANISH_OUTLETS):
        want = "English" if outlet in ENGLISH_OUTLETS else "Spanish"
        warn("lang_uncertain", f"Couldn't tell this draft's language; {label} drafts must be {want}. Check it before copying.")

    # 2. CTA / self-promo bait (one plain link to the asset is allowed)
    m = (_CTA_RE.search(text) or _CTA_RE.search(collapsed)
         or _ENGAGE_RE.search(text.replace("’", "'")) or _ENGAGE_RE.search(". ".join(collapse_letters(x) for x in re.split(r"(?<=[a-z]{2})[.!?]+(?=\s|$)|\n", text, flags=re.I))))
    if m:
        block("cta_bait", f'Remove the call-to-action "{m.group(0)}"; drafts carry no self-promo bait.')
    urls = _URL_RE.findall(text)
    if len(urls) > 1:
        block("cta_bait", "Only one plain link to the asset is allowed.")
    if any(".." in (normalize_url(u) or ("", "", ".."))[2] or "/../" in u or u.endswith("/..") for u in urls):
        block("cta_bait", "Links can't contain '..' path segments.")
    elif len(urls) == 1:
        got = normalize_url(urls[0])
        want = normalize_url(c.asset_url) if c.asset_url else None
        if want is None or got is None or got[1:] != want[1:] or not safe_query_fragment(urls[0]):
            block("cta_bait", "The only link allowed is the asset's own link.")

    # 2b. First line answers the post's point: never "Re:" or a quoted cue
    if opens_on_quote_cue(text):
        block("quote_cue_opener", 'Don\'t open with "Re:" or a quote of their post; answer their point in the first line.')

    # 3. Named claim present (in own words); first sentence must not restate it
    claim_texts = _slug_claims(c) + [c.asset_title or "", c.asset_claim or ""]
    claim_terms = _terms(" ".join(claim_texts))
    restatable = [x for x in (_slug_claims(c) + [c.asset_claim or ""]) if (x or "").strip()]
    if claim_restated(text, restatable):
        block("claim_restated",
              "The reply's first sentence restates your claim. Respond to the post, then bring in your angle.")
    elif any(claim_overlap(text, x) >= CLAIM_OVERLAP_MAX for x in restatable):
        block("claim_overlap",
              "The reply repeats most of your claim's words. Say it in fewer of its own words; the claim is on the card.")
    elif not (_terms(text) & claim_terms):
        block("claim_missing", "The draft doesn't name the card's matched claim; say the claim in your own words.")
    else:
        neg = _negated_claim(_URL_RE.sub(" ", text), claim_terms)
        if neg:
            warn("claim_negated", f'The draft says "{neg}" right next to the claim; make sure it states the claim, not its opposite.')

    # 4. Door consistency
    if civic and _LAB_BRAND_RE.search(text):
        block("door_mix", "This is a civic-door draft; drop the EconLLM lab branding.")
    if not civic and _CIVIC_OPED_RE.search(text):
        block("door_mix", "This is an EconLLM draft; it shouldn't present itself as a civic op-ed.")

    # 5. Length (counts everything, handles included) + X hard rules
    if outlet == "x":
        variants = [_URL_RE.sub(" ", text), _URL_RE.sub(" ", normalize_text_spaced(draft_text or ""))]
        h = next((m for v in variants for m in [_X_HANDLE_RE.search(v)] if m), None)
        if h:
            block("x_handle", f'Remove "{h.group(0)}"; X drafts carry no @handles (the reply target is set when you post).')
        ht = next((m for v in variants for m in [_X_HASHTAG_RE.search(v)] if m), None)
        if ht:
            block("x_hashtag", f'Remove the hashtag "{ht.group(0)}"; X drafts carry no hashtags.')
        if _X_EMOJI_RE.search(text):
            block("x_emoji", "Remove the emoji; X drafts carry no emoji.")
        n = x_length(text)
        if n > X_MAX:
            block("too_long", f"X drafts must be {X_MAX} characters or fewer (links count as {URL_WEIGHT}); this one is {n}.")
    elif outlet == "linkedin" and len(text) > LINKEDIN_MAX:
        block("too_long", f"LinkedIn drafts must be {LINKEDIN_MAX} characters or fewer; this one is {len(text)}.")

    # 6. Caveat lives in the card's own field, next to the claim; never in the copyable draft body.
    #    Grade B without a caveat on the card is effectively Grade C.
    cav = (c.asset_caveat or "").strip()
    if cav:
        if caveat_in(text, cav):
            block("caveat_in_draft", "The caveat is shown on the card next to the claim; take it out of the reply.")
    elif c.evidence_grade == "B":
        block("caveat_dropped", "This asset is Evidence B but has no caveat written down; add a caveat to the asset before drafting.")

    # 7. Nothing invented
    allowed = " ".join(claim_texts)
    for num, _unit in _METRIC_RE.findall(_URL_RE.sub(" ", text)):
        if not re.search(rf"(?<![\d.,]){re.escape(num)}(?![\d])", allowed):
            block("invented_metric", f'The draft states "{num}" as a result, but that number isn\'t on the card.')
            break
    wm = _WORD_METRIC_RE.search(text)
    if wm and wm.group(0).lower() not in allowed.lower():
        warn("possible_metric", f'"{wm.group(0)}" reads like a result; only keep it if it is on the card.')

    return GateResult(not reasons, reasons, warnings, tags)
