"""Pinned 2026-10-16: one weak hint alone never clears Fit (the 4 hints added for gpt4o-weird / econllm-lab)."""
import pytest
from fastapi.testclient import TestClient

from src import fit
from src.api.app import create_app
from tests.test_intake_contract import post
from tests.test_xbrief_bridge import fake  # noqa: F401

CASES = [
    ("econllm-lab", "LLM agents are coming to our chain! Join the airdrop now, claim your free tokens today"),
    ("econllm-lab", "Our new LLM agents ship next week, sign up for early access"),
    ("econllm-lab", "Game theory explains why my roommate never does the dishes"),
    ("gpt4o-weird", "Cultural alignment matters for every team offsite we run"),
    ("gpt4o-weird", "Whose values does your company really live by? Hiring now"),
]


@pytest.mark.parametrize("slug,text", CASES)
def test_one_weak_hint_does_not_clear_slug(slug, text):
    assert slug not in fit.claim_match(text, [slug])
    assert slug not in fit.claim_match(text, list(fit._KEYWORD_HINTS))


@pytest.mark.parametrize("slug,text", CASES)
def test_one_weak_hint_hashtag_or_quote_does_not_clear(slug, text):
    hint = next(h for h in ("llm agents", "game theory", "cultural alignment", "whose values") if h in text.lower())
    assert slug not in fit.claim_match(f'"{hint}" is the buzzword of the week #{hint.replace(" ", "")}', [slug])


@pytest.mark.parametrize("slug,text", CASES)
def test_one_weak_hint_post_never_queues(tmp_path, monkeypatch, fake, slug, text):  # noqa: F811
    monkeypatch.delenv("MS_TEST_MODE", raising=False)
    c = TestClient(create_app(str(tmp_path / "data")))
    r = c.post("/intake/x", json={"run_id": "weak-hint-pin", "posts": [post(text)]})
    assert r.status_code == 200, r.text
    row = r.json()["posts"][0]
    assert row["status"] != "queued", row
    assert row["status"] == "killed" and "empty_fit" in row["reasons"], row
