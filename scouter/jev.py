"""Jev (TypeSafe System One) client: one POST, three primitives, no retries, no secrets in errors.

Jev decides, it never writes. The scout asks one atomic yes/no (`noul`) question per interest,
because compound rubrics ("how good an opportunity?") collapse to the midpoint (see the probe
notes in the brain-fart log).
"""
import json
import time

from . import config

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"               # pinned, not the alias, so scores stay comparable over time
PRICE_PER_INPUT_TOKEN = 0.042 / 1e6


class JevError(RuntimeError):
    """Messages are safe to log: they never contain the key."""


def _post(key, state, questions, timeout=15):
    body = json.dumps({"model": MODEL, "state": state, "questions": questions},
                      ensure_ascii=False).encode("utf-8")
    import ssl
    import urllib.error
    import urllib.request
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json",
        "Accept": "application/json", "User-Agent": config.UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise JevError("Jev HTTP %d: %s" % (e.code, detail.replace(key, "[redacted]")))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise JevError("Jev request failed: %s" % type(e).__name__)


def relevance_questions(interests):
    """One noul per interest. Question ids are positional (i0, i1, ...) and mapped back by caller."""
    qs = {}
    for n, it in enumerate(interests):
        qs["i%d" % n] = {"type": "noul", "instructions": (
            "Is this item substantively about: %s. %s (Reply high only if the item itself is about "
            "this, not merely adjacent or sharing a few words.)" % (it["name"], it["description"]))}
    qs["personal"] = {"type": "noul", "instructions": (
        "Would a credible response to this item require the author to disclose private personal "
        "details (family, health, location, immigration status, finances)?")}
    return qs


def score_item(key, item, interests):
    """Return dict: relevance, lens, scores (name->p), personal, input_tokens, cost_usd, ms."""
    started = time.monotonic()
    state = {"source": item["source"], "title": item["title"], "summary": item.get("summary", "")[:600]}
    resp = _post(key, state, relevance_questions(interests))
    answers = resp.get("answers") or {}
    scores = {}
    for n, it in enumerate(interests):
        a = answers.get("i%d" % n)
        if a is None or a.get("noul") is None:
            raise JevError("Jev answer missing for interest %r" % it["name"])
        scores[it["name"]] = float(a["noul"])
    lens = max(scores, key=scores.get)
    tokens = int((resp.get("usage") or {}).get("input_tokens", 0))
    return {"relevance": scores[lens], "lens": lens, "scores": scores,
            "personal": float((answers.get("personal") or {}).get("noul", 0.0)),
            "input_tokens": tokens, "cost_usd": tokens * PRICE_PER_INPUT_TOKEN,
            "ms": int((time.monotonic() - started) * 1000)}
