"""Pinned (Augusto 10-16): the voice gate does NOT block swearing or roasts; it only TAGS them
(has_profanity / has_put_down in GateResult.tags, stored with the gate dict). AT's v2 drafts, the v1 'bs' draft,
'cope' and masked/leetspeak forms all pass the gate's abuse dimension; no profanity/put_down code exists.
(Other hard rules, e.g. x_handle/x_hashtag/x_emoji, still apply and are tested elsewhere.)"""
import pytest

from src.voice_gate import CODES, check_draft


def tags(text, card=None):
    return check_draft(text, card or CARD).to_dict()["tags"]

CARD = {"outlet": "x", "door": "Augusto-civic", "slugs": [], "asset_title": "Verification is scarce",
        "asset_claim": "Verification is the scarce input once generation is cheap."}
BASE = "Cheap generation makes verification the scarce part; that is where local newsrooms still matter."
ABUSE = {"profanity", "put_down"}
BLOCKING_HERE = ABUSE | {"x_handle", "x_hashtag", "x_emoji", "cta_bait", "quote_cue_opener"}


def codes(text, card=CARD):
    return {r["code"] for r in check_draft(text, card).reasons}


# AT's three v2 drafts (verbatim) and the v1 'bs' draft
AT_DRAFTS = [
    ("Qualitative tracking \u2260 experimental validity. Your LLM \u201cagents\u201d are just statistical parrots on a diet of "
     "human data. Stop confusing a glib simulation with actual fieldwork, you absolute clown.", "put_down"),
    ("Qualitative tracking is just pattern-matching cope. You\u2019re not doing fieldwork, you\u2019re prompting a parrot. "
     "Either go to the field or shut the fuck up.", "profanity"),
    ("Qualitative tracking of non-WEIRD behavior where human data exist? So a parrot with a training set. Not fieldwork, "
     "not novel. The caveat is the whole fucking point. Stop pretending this is progress.", "profanity"),
    ("Qualitative tracking != human equivalence. LLM synthetic agents track non-WEIRD behavior where data exist, but "
     "they're not substitutes for fieldwork. The bs would be claiming otherwise. Coping would be denying they work at all.",
     "profanity"),
]


def test_no_abuse_codes_exist():
    assert not ABUSE & set(CODES)


@pytest.mark.parametrize("text,_old_code", AT_DRAFTS)
def test_at_drafts_pass_abuse_wise_but_are_tagged(text, _old_code):
    assert not codes(text) & BLOCKING_HERE
    t = tags(text)
    assert t["has_profanity"] or t["has_put_down"]


@pytest.mark.parametrize("bad", [
    "you absolute clown", "you clowns", "You total idiot", "you're an idiot", "you are so stupid", "moronic take",
    "shut up", "shut the fuck up", "STFU", "the whole fucking point", "f*ck", "f**k this", "f***ing clowns", "sh*t",
    "sh#t", "f%ck", "fuuuuck", "fuckkkk", "shiiiit", "F U C K", "f.u.c.k", "s-h-i-t", "sh1t", "5h1t", "fr34king",
    "bull$hit", "c1own", "1d10t", "cl0wn", "clowwwn", "f\u200buck", "\uff46\uff55\uff43\uff4b", "wtf", "that is bs", "bs.",
    "b.s.", "not cope", "pure copium", "are you still coping?", "that's cope", "grifters", "go to hell", "dipshit",
])
def test_swearing_and_roasts_pass(bad):
    assert not codes(BASE + " " + bad) & ABUSE, bad
    assert codes(BASE + " " + bad) == codes(BASE), bad
    t = tags(BASE + " " + bad)
    assert t["has_profanity"] or t["has_put_down"], bad


@pytest.mark.parametrize("ok", [
    "Scunthorpe", "people cope with noisy data", "coping with the data", "how teams cope well with drift",
    "She has a BS degree", "a BS in physics", "B.S. in economics", "BS/MS students", "class sizes", "assess",
    "cocktail", "Dickens", "shiitake", "peacock", "therapist", "Classic results", "scope", "telescope", "copepod",
    "the #1 cause", "C#", "issue #42", "meet @ 5pm", "you are right", "stupid question, but", "dumb luck", "assume",
    "a bit of a pass", "Hancock", "cockpit", "grape", "spice", "shell", "fork", "duck", "luck", "puck", "the 1440 shift",
])
def test_ordinary_words_pass(ok):
    assert not codes(BASE + " " + ok) & ABUSE, ok
    assert tags(BASE + " " + ok) == {"has_profanity": False, "has_put_down": False}, ok


def test_other_outlets_not_blocked_either():
    assert not codes("Esto es una mierda pero fuck it.", {**CARD, "outlet": "oped"}) & ABUSE
    assert not codes(BASE + " you idiot", {**CARD, "outlet": "linkedin"}) & ABUSE


def test_x_hard_rules_still_apply_next_to_swearing():
    c = codes(BASE + " shut the fuck up @fixture_user_40 #dunk \U0001F921")
    assert {"x_handle", "x_hashtag", "x_emoji"} <= c and not c & ABUSE


def test_tags_never_change_ok():
    r = check_draft(BASE + " shut the fuck up, you absolute clown", CARD)
    assert r.ok == check_draft(BASE, CARD).ok and r.tags == {"has_profanity": True, "has_put_down": True}


def test_empty_draft_still_has_tags():
    assert check_draft("", CARD).to_dict()["tags"] == {"has_profanity": False, "has_put_down": False}


# AT fd231c4 review: normal economics prose is never tagged (and never blocked)
@pytest.mark.parametrize("prose", [
    "winners and losers from trade", "the loser-pays rule", "coping strategies of households under shocks",
    "coping mechanisms", "the idiot index", "clown fish", "clownfish", "the grifter literature", "the bastard wing",
    "a bs in physics", "pass the bs test", "MF-DFA", "an FK model", "the SHT table", "the 'cope' framing misleads",
    "calling it \u201cbullshit\u201d misses it", "cope with", "BS degree", "Scunthorpe", "class", "assess", "cocktail",
    "shitake", "shiitake", "hell of a result", "damn", "Pissarides", "prickly", "dummy variable", "Freakonomics",
    "craps", "after", "the TF-IDF baseline", "a ratio of means", "imagine a world with cheap verification",
])
def test_normal_prose_not_tagged(prose):
    r = check_draft(BASE + " " + prose, CARD)
    assert r.tags == {"has_profanity": False, "has_put_down": False}, prose
    assert {x["code"] for x in r.reasons} == codes(BASE)


# AT fd231c4 review: evasions are tagged (measurement only; never blocked)
@pytest.mark.parametrize("ev", [
    "\u0441l\u043ewn", "\u0455h\u0456t", "fu\u0441k", "sh_it", "pelotudo", "boludo", "boludez", "mierda", "forro",
    "eff off", "dumb af", "ffs", "what tf", "gtfoh", "dumbfuck", "asshat", "ass-clown", "imagine believing this",
    "ratio", "L take", "midwit", "clownery", "pure idiocy", "dumb take", "stupid paper", "do better.", "idiota",
    "imb\u00e9cil", "la concha", "carajo",
])
def test_evasions_tagged_never_blocked(ev):
    r = check_draft(BASE + " " + ev, CARD)
    assert r.tags["has_profanity"] or r.tags["has_put_down"], ev
    assert {x["code"] for x in r.reasons} == codes(BASE), ev


def test_tags_never_block_or_alter_the_draft():
    text = BASE + " shut the fuck up, you absolute clown, pure cope"
    before = text
    r = check_draft(text, CARD)
    assert text == before                                   # input untouched
    assert r.ok == check_draft(BASE, CARD).ok and r.reasons == check_draft(BASE, CARD).reasons
    assert r.tags == {"has_profanity": True, "has_put_down": True}
    assert not {"profanity", "put_down"} & {x["code"] for x in r.reasons + r.warnings}
