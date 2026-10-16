"""Claim-echo guard (deterministic, grader-independent).

A post that parrots one of our own one_line_claims is not someone arguing it; if the grader still says
'claim', hold it as 'claim_echo'. Echo when either:
  * >= 50% of the claim's normalized token 5-grams appear verbatim in the post, or
  * the longest verbatim token run shared with the claim covers >= 50% of the claim (and >= 6 tokens), or
  * the post contains >= 80% of the claim's content words (claim minus stopwords; claims with >= 5 such words).
Known limit: translations (e.g. a Spanish rendering of an English claim) share almost no tokens and are not caught.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

NGRAM = 5
NGRAM_MIN = 0.5
CONTENT_MIN = 0.8
STOP = set("""a an the and or but of to in on at by for with from as is are was were be been being can could
should would will may might must do does did not no only that this these those it its their there where which who
whom whose what when how than then so such into over under about via per our we you your i my me""".split())


def _tokens(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"https?://\S+", " ", s)
    return re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)*", s)


def _grams(t: list[str]) -> set[tuple]:
    return {tuple(t[i:i + NGRAM]) for i in range(len(t) - NGRAM + 1)}


RUN_MIN = 0.5


def _longest_run(a: list[str], b: list[str]) -> int:
    best, prev = 0, [0] * (len(b) + 1)
    for x in a:
        cur = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            if x == y:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def run_score(text: str, claim: str) -> float:
    ct = _tokens(claim)
    r = _longest_run(_tokens(text), ct)
    return r / len(ct) if ct and r >= 6 else 0.0


def content_words(s: str) -> set[str]:
    """claim_echo's content-word set (tokens minus STOP, len > 2). Shared by the voice gate's claim_overlap."""
    return {w for w in _tokens(s) if w not in STOP and len(w) > 2}


def echo_score(text: str, claim: str) -> tuple[float, float]:
    pt, ct = _tokens(text), _tokens(claim)
    cg = _grams(ct)
    ng = len(cg & _grams(pt)) / len(cg) if cg else 0.0
    cw = content_words(claim)
    cont = len(cw & set(pt)) / len(cw) if len(cw) >= 5 else 0.0
    return ng, cont


def is_echo(text: str, claim: str) -> bool:
    ng, cont = echo_score(text, claim)
    return ng >= NGRAM_MIN or cont >= CONTENT_MIN or run_score(text, claim) >= RUN_MIN


def echoed_claim(text: str, claims: Iterable[tuple[str, str]]) -> Optional[str]:
    """First (asset_id) whose claim the text echoes; claims = [(asset_id, claim_text)]."""
    return next((aid for aid, c in claims if c and is_echo(text, c)), None)
