"""da_ Data Analyst: Fit is claim-level. Made-up posts modelled on discovery-2026-10-13T19:35:31Z rows that the
bare-keyword matcher queued/held must now be killed as empty_fit; a genuine opening still queues."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.fit import claim_match, prefilter

FIX = json.loads((Path(__file__).parent / "fixtures" / "discovery_20261013_offtopic.json").read_text())
POSTS = {int(k): v for k, v in FIX["posts"].items()}
OFF_TOPIC = [0, 1, 8, 17, 20, 7, 21]   # made-up: publishers x2, token promo, LLM hype, notes-bot log x2, mind thesis
GENUINE = 6                             # made-up agentic-AI-as-complex-adaptive-systems post → econ-ai-cas


@pytest.fixture
def c(tmp_path):
    app = create_app(str(tmp_path))
    app.state.api.predrafter = lambda p, card: {"status": "ok", "draft_text": card["draft"]}
    return TestClient(app)


def _post(i, sid):
    p = POSTS[i]
    return {"url": f"https://x.com/fixture_user_60/status/{sid}", "text": p["text"], "author_handle": "someone",
            "reply_count": p.get("reply_count"), "quote_count": p.get("quote_count"), "like_count": p.get("like_count")}


@pytest.mark.parametrize("i", OFF_TOPIC)
def test_da_real_offtopic_post_killed_empty_fit(c, i):
    rows = c.post("/intake/x", json={"run_id": f"r{i}", "posts": [_post(i, 10**15 + i)]}).json()["posts"]
    assert rows[0]["status"] == "killed" and rows[0]["reasons"] == ["empty_fit"], rows


def test_da_genuine_opening_from_run_still_queues(c):
    rows = c.post("/intake/x", json={"run_id": "g", "posts": [_post(GENUINE, 10**15 + 99)]}).json()["posts"]
    assert rows[0]["status"] == "queued" and rows[0]["S"] > 0, rows


def test_da_bare_keyword_never_credits():
    pool = ["cvp-measurement-layer", "gpt4o-weird", "complexity-policy", "sca-pilot-ethics", "cheap-gen-scarce-verify"]
    assert claim_match("Three of the Big Five book publishers use AI", pool) == []
    assert claim_match("GPT-6 is coming and the LLM era is over", pool) == []
    assert claim_match("Our pilot program for ChatGPT copilots", pool) == []
    assert claim_match("TRON and the Complexity Science Hub on blockchain", pool) == []
    # claim-level hits still credit
    assert claim_match("Construct validity of Big Five personality scores on LLMs", pool) == ["cvp-measurement-layer"]
    assert claim_match("GPT answers cluster with WEIRD world values", pool) == ["gpt4o-weird"]


def test_da_researcher_prefilter_runs_first():
    assert prefilter("TRON airdrop survey for respondents", ["smart-surveys"]) == []
    assert prefilter("Community Notes y verificación con contexto local", ["verification-local-context"]) \
        == ["verification-local-context"]
