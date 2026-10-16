"""Pin the claim_echo config that applies to the approved econllm_lab claim (2026-10-13 21:57 PT).
Thresholds are fixed constants in src/claim_echo.py (not derived from claim texts)."""
import json
import math
from pathlib import Path

from src import claim_echo as ce

CLAIM = ("Combining games, experiments, LLM agents, and complex-systems methods "
         "is a productive way to study heterogeneous behavior.")


def test_constants_fixed():
    assert (ce.NGRAM, ce.NGRAM_MIN, ce.CONTENT_MIN, ce.RUN_MIN) == (5, 0.5, 0.8, 0.5)


def test_seed_has_approved_claim():
    row = next(a for a in json.loads(Path("data/seed_inventory.json").read_text()) if a["asset_id"] == "asset_econllm_lab")
    assert row["one_line_claim"] == CLAIM and "one_line_claim_pending" not in row


def test_econllm_echo_config():
    t = ce._tokens(CLAIM)
    cw = {w for w in t if w not in ce.STOP and len(w) > 2}
    assert len(t) == 16 and len(ce._grams(t)) == 12 and len(cw) == 12
    # effective bars: >=6 of 12 5-grams, >=10 of 12 content words, shared run >=8 tokens
    assert math.ceil(ce.NGRAM_MIN * 12) == 6 and math.ceil(ce.CONTENT_MIN * 12) == 10
    assert max(6, math.ceil(ce.RUN_MIN * 16)) == 8
    assert ce.is_echo("Combining games, experiments, LLM agents, and complex-systems methods works.", CLAIM)
    assert not ce.is_echo("LLM agents in games are a productive way to study behavior.", CLAIM)
