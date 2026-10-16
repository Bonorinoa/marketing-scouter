"""Caveat is the card's own field (2026-10-14 caveat move; supersedes Marketing 2026-10-13 verbatim-in-draft rule).
Grade B without a caveat on the card is effectively Grade C (Data Analyst). The copyable draft never carries it."""
from src.api import xbrief_bridge as xb
from src.claim_echo import content_words
from src.voice_gate import check_draft, claim_overlap, strip_caveat, CLAIM_OVERLAP_MAX

CLAIM = "GPT-4o-mini responses to WVS-like questions cluster close to WEIRD, especially US, values."
CAV = "This is one model on survey-style questions, so read it as a bias signal, not a settled result."
URL = "https://example.org/essay"
OWN = f"Worth stressing next to the non-WEIRD pilots: small models lean American on value surveys. {URL}"


def gate_card(caveat=CAV, grade="B", outlet="x"):
    return {"outlet": outlet, "door": "EconLLM", "slugs": ["gpt4o-weird"], "asset_title": "WEIRD essay",
            "asset_url": URL, "asset_claim": CLAIM, "asset_caveat": caveat, "evidence_grade": grade}


def codes(r):
    return [x["code"] for x in r.reasons]


def test_own_words_draft_with_caveat_on_card_passes():
    r = check_draft(OWN, gate_card())
    assert r.ok, r.reasons


def test_caveat_in_draft_body_blocked():
    assert codes(check_draft(f"{OWN} {CAV}", gate_card())) == ["caveat_in_draft"]
    assert codes(check_draft(f"{OWN} {CAV.upper()}", gate_card())) == ["caveat_in_draft"]


def test_grade_b_without_card_caveat_blocked():
    r = check_draft(OWN, gate_card(caveat=None))
    assert codes(r) == ["caveat_dropped"] and "no caveat" in r.reasons[0]["message"]


def test_grade_a_without_caveat_not_blocked():
    assert check_draft(OWN, gate_card(caveat=None, grade="A")).ok


def test_strip_caveat_removes_verbatim_any_case():
    assert strip_caveat(f"{OWN} {CAV}", CAV) == OWN
    assert strip_caveat(f"{OWN}  {CAV.lower()}", CAV) == OWN
    assert strip_caveat(OWN, None) == OWN


def test_bridge_does_not_ask_for_caveat_in_reply():
    ins = xb.asset_instructions(CLAIM, CAV)
    assert CAV not in ins and "do not include caveats" in ins


def test_claim_overlap_uses_claim_echo_tokenizer_and_blocks_at_60pct():
    cw = sorted(content_words(CLAIM))
    assert CLAIM_OVERLAP_MAX == 0.6 and len(cw) >= 5
    k = -(-len(cw) * 6 // 10)               # smallest count reaching 60%
    hit = "Replying here: " + " ".join(cw[:k]) + "."
    miss = "Replying here: " + " ".join(cw[:k - 1]) + "."
    assert claim_overlap(hit, CLAIM) >= 0.6 and "claim_overlap" in codes(check_draft(hit, gate_card()))
    assert claim_overlap(miss, CLAIM) < 0.6 and "claim_overlap" not in codes(check_draft(miss, gate_card()))


def test_verbatim_claim_mid_reply_blocked():
    assert "claim_overlap" in codes(check_draft(f"Fair point on the thread. {CLAIM} {URL}", gate_card()))
