"""Pinned 2026-10-16 (evening, weak hints reverted): posts built only from the reverted words never clear Fit.
Made-up posts only (no real post text)."""
from src import fit


def test_reverted_words_in_crypto_promo_do_not_clear():
    for t in ["LLM agents game theory airdrop token", "LLM agents and game theory: claim your airdrop now"]:
        assert fit.claim_hits(t, "econllm-lab") == ([], [])
        assert fit.claim_match(t, ["econllm-lab"]) == []


def test_reverted_words_in_plain_promo_do_not_clear():
    t = "Our LLM agents use game theory to close more deals. Join the waitlist for launch day"
    assert fit.claim_match(t, ["econllm-lab"]) == []
    t2 = "Cultural alignment and whose values: book our team workshop this fall"
    assert fit.claim_match(t2, ["gpt4o-weird"]) == []
