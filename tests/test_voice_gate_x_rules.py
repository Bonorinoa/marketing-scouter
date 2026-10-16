"""Pinned: X drafts hard-fail on any @fixture_user_44 (zero-width/NFKC-proof), hashtags and emoji; length counts everything."""
from src.voice_gate import check_draft

CARD = {"outlet": "x", "door": "Augusto-civic", "slugs": [], "asset_title": "Verification is scarce",
        "asset_claim": "Verification is the scarce input once generation is cheap."}
BASE = "Cheap generation makes verification the scarce part; that is where local newsrooms still matter."


def codes(text, card=CARD):
    return {r["code"] for r in check_draft(text, card).reasons}


def test_clean_base_has_no_x_rule_codes():
    assert not codes(BASE) & {"x_handle", "x_hashtag", "x_emoji", "too_long"}


def test_leading_handle_fails():
    assert "x_handle" in codes("@fixture_user_40 " + BASE)


def test_twenty_stacked_handles_fail_and_count_toward_length():
    t = " ".join(f"@fixture_user_53{i:02d}" for i in range(20)) + " " + BASE   # 20*16 = 320 handle chars, over 280 on their own
    c = codes(t)
    assert "x_handle" in c and "too_long" in c


def test_zero_width_after_at_fails():
    assert "x_handle" in codes(BASE + " @\u200bfoo")


def test_fullwidth_at_fails():
    assert "x_handle" in codes(BASE + " \uff20foo")


def test_hashtag_fails():
    assert "x_hashtag" in codes(BASE + " #OwnYourIntelligence")


def test_emoji_fails():
    assert "x_emoji" in codes(BASE + " \U0001F680")


def test_email_and_numbers_not_flagged():
    c = codes("Verification is scarce, write to desk@example.org about issue #12 today.")
    assert not c & {"x_handle", "x_hashtag"}


def test_linkedin_unaffected():
    assert not codes("@fixture_user_40 " + BASE + " #tag", {**CARD, "outlet": "linkedin"}) & {"x_handle", "x_hashtag", "x_emoji"}


# ── AT vg review (2026-10-16) ──
import pytest  # noqa: E402


@pytest.mark.parametrize("t", [".@fixture_user_24 thanks", "x.@fixture_user_24", "\u2026@fixture_user_24", "...@fixture_user_24", "!x(@fixture_user_24)"])
def test_dot_and_ellipsis_handles_fail(t):
    assert "x_handle" in codes(BASE + " " + t)


@pytest.mark.parametrize("t", ["It costs $5 @ 3% interest.", "Let's meet @ 5pm.", "Tested @ 3 sites.",
                               "write to desk@example.org", "foo@bar", "a_@b", "a!@b", "a#@b", "a&@b", "a*@b"])
def test_prose_at_signs_pass(t):
    assert "x_handle" not in codes(BASE + " " + t)


@pytest.mark.parametrize("ch", ["\u2713", "\u2717", "\u2605", "\u26a0", "\u2318", "\u2308x\u2309", "\u279c",
                                "\u2714", "\u2611", "\u266a", "\u2696", "\u263a", "\u263a\ufe0e", "\u00a9", "\u2122"])
def test_text_default_symbols_pass(ch):
    assert "x_emoji" not in codes(BASE + " " + ch + " replicated")


@pytest.mark.parametrize("e", ["\U0001F600", "\U0001F468\u200d\U0001F469\u200d\U0001F467", "\U0001F1E6\U0001F1F7",
                               "1\ufe0f\u20e3", "1\u20e3", "\u263a\ufe0f", "\u26a0\ufe0f", "\u2705", "\u2728", "\u23f0",
                               "\u2b50", "\U0001F44D\U0001F3FD", "\U0001FAE8", "\u00a9\ufe0f"])
def test_emoji_fail(e):
    assert "x_emoji" in codes(BASE + " " + e)


@pytest.mark.parametrize("cf", ["\u200e", "\u200f", "\u2061", "\u180e", "\u034f", "\u115f", "\u1160", "\u3164", "\uffa0", "\u2800", "\U000E0041", "\u202a", "\u2066", "\u00ad", "\ufeff"])
def test_invisible_format_chars_stripped_before_handle_check(cf):
    assert "x_handle" in codes(BASE + " @" + cf + "fixture_user_24")
    assert "x_handle" in codes(BASE + " jo" + cf + "@fixture_user_24"[0:0] + " @fixture_user_48" + cf + "hndoe")


def test_normalize_strips_all_cf():
    import unicodedata
    from src.voice_gate import normalize_text
    s = "a\u200e\u2061\U000E0041\u202ab\u00adc"
    assert not [c for c in normalize_text(s) if unicodedata.category(c) == "Cf"]


@pytest.mark.parametrize("s", ["x\u200b@fixture_user_24", "x\u2060@fixture_user_24", "word\ufeff@fixture_user_24", "1\u200b@fixture_user_24",
                               "x\u3164@fixture_user_24", "x\u2800@fixture_user_24", "x\u034f@fixture_user_24"])
def test_invisible_before_at_is_boundary(s):
    assert "x_handle" in codes(BASE + " " + s)


@pytest.mark.parametrize("s", ["x\u200b#OwnAI", "word\ufeff#OwnAI", "x\u2060#OwnAI"])
def test_invisible_before_hash_is_boundary(s):
    assert "x_hashtag" in codes(BASE + " " + s)


@pytest.mark.parametrize("s", ["email@example.com", "meet @ 5pm", "meet @\u200b 5pm", "issue #42", "C#"])
def test_spaced_variant_no_new_false_positives(s):
    c = codes(BASE + " " + s)
    assert "x_handle" not in c and "x_hashtag" not in c
