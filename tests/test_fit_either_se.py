"""se_ MS_FIT_GRADED_MODE=either (word OR v1 grader, F=0.75, drafts only for claim) + brand_post label."""
import json

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.brand import is_brand_post
from tests.test_intake_contract import T_NOFIT, T_SCA

SCA_PARA = "Synthetic agents built on language models can mirror non-Western lived experience surprisingly well"


class FakeGrader:
    model, prompt_version = "fake/model", "either-test"

    def __init__(self, answers=None, claim_has="non-WEIRD", boom=False):
        self.answers, self.claim_has, self.boom, self.calls = answers or {}, claim_has, boom, []

    def __call__(self, text, claim):
        self.calls.append(text)
        if self.boom:
            raise RuntimeError("kaboom")
        if self.claim_has and self.claim_has not in (claim or ""):
            return "none"
        return self.answers.get(text.strip(), "none")


@pytest.fixture
def mk(tmp_path, monkeypatch):
    monkeypatch.delenv("MS_FIT_GRADED", raising=False)
    monkeypatch.delenv("MS_FIT_SHADOW", raising=False)
    n = [0]

    def _mk(grader=None):
        n[0] += 1
        app = create_app(str(tmp_path / str(n[0])))
        api = app.state.api
        api.drafts = []
        api.predrafter = lambda p, card: api.drafts.append(p["text"]) or {"status": "ok", "draft_text": card["draft"]}
        api.fit_grader = grader
        return TestClient(app), api
    return _mk


def X(sid, text=T_SCA, author=None):
    return {"url": f"https://x.com/fixture_user_54/status/{sid}", "text": text, "reply_count": 4, "quote_count": 1,
            "author_handle": author}


def run(c, posts, rid="discovery-e"):
    r = c.post("/intake/x", json={"run_id": rid, "posts": posts})
    assert r.status_code == 200
    return r.json()["posts"]


def fits(api):
    return {e["card_id"]: e["factors"]["Fit"] for e in api.events() if e["kind"] == "scored"}


def either_ev(api):
    return [e for e in api.events() if e["kind"] == "fit_either"]


def test_se_either_lifts_empty_fit_when_graded_topic_and_F_fixed(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "either")
    c, api = mk(FakeGrader({SCA_PARA: "topic", T_SCA: "claim"}))
    rows = run(c, [X(1000000000000001, SCA_PARA), X(1000000000000002, T_SCA)])
    lifted, word = rows
    assert lifted["status"] in ("queued", "held") and lifted["fit_level"] == "topic", lifted
    assert word["status"] in ("queued", "held") and word["fit_level"] == "claim"
    f = fits(api)
    assert f[lifted["card_id"]] == f[word["card_id"]] == 0.75
    assert api.drafts == [T_SCA]                         # draft only for claim
    assert lifted["no_draft"] is True and not lifted.get("predrafted")
    ev = either_ev(api)[-1]
    assert ev["n_added_by_grader"] == 1 and ev["posts_graded"] == 2 and ev["capped"] is False


def test_se_either_word_only_post_gets_F_075_no_draft(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "either")
    c, api = mk(FakeGrader({}))                          # grader says none; word passes
    row = run(c, [X(1000000000000003)])[0]
    assert row["status"] == "queued" and fits(api)[row["card_id"]] == 0.75
    assert row["no_draft"] is True and api.drafts == [] and either_ev(api)[-1]["n_word_only"] == 1


def test_se_either_hashtag_stuffed_still_killed(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "either")
    t = "LLM agents non-WEIRD #ai #llm #survey #weird #gpt #culture"
    c, api = mk(FakeGrader({t: "claim"}, claim_has=None))
    row = run(c, [X(1000000000000004, t)])[0]
    assert row["status"] == "killed" and "hashtag_stuffed" in row["reasons"]


def test_se_either_grader_exception_equals_word_only(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "either")
    c, api = mk(FakeGrader(boom=True))
    rows = run(c, [X(1000000000000005), X(1000000000000006, SCA_PARA)])
    assert rows[0]["status"] == "queued" and rows[1]["reasons"] == ["empty_fit"]
    assert any(e["kind"] == "fit_grader_unavailable" for e in api.events())


def test_se_either_cap_respected(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "either")
    monkeypatch.setenv("MS_FIT_SHADOW_MAX_CALLS", "1")    # cap counts posts sent to the grader
    g = FakeGrader({SCA_PARA: "topic", SCA_PARA + " too": "topic"})
    c, api = mk(g)
    rows = run(c, [X(1000000000000007, SCA_PARA), X(1000000000000008, SCA_PARA + " too")])
    ev = either_ev(api)[-1]
    assert len(g.calls) <= 8 and ev["posts_called"] == 1 and ev["model_calls"] == len(g.calls) and ev["capped"] is True
    assert rows[0]["status"] != "killed" and rows[1]["reasons"] == ["empty_fit"]   # after cap: word only


def test_se_either_skips_shadow(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "either")
    monkeypatch.setenv("MS_FIT_SHADOW", "1")
    c, api = mk(FakeGrader({}))
    run(c, [X(1000000000000009)])
    assert not [e for e in api.events() if e["kind"] == "fit_shadow"]


def test_se_mode_unset_unchanged(mk, monkeypatch):
    monkeypatch.delenv("MS_FIT_GRADED_MODE", raising=False)
    g = FakeGrader({SCA_PARA: "claim"})
    c, api = mk(g)
    rows = run(c, [X(1000000000000010), X(1000000000000011, SCA_PARA)])
    assert rows[0]["status"] == "queued" and rows[0].get("predrafted") and rows[0].get("fit_level") is None
    assert rows[1]["reasons"] == ["empty_fit"] and g.calls == [] and not either_ev(api)
    assert fits(api)[rows[0]["card_id"]] != 0.75


# ── brand_post label ───────────────────────────────────────────────────────
@pytest.mark.parametrize("text,author,want", [
    ("see https://acme.io/pricing for details", None, True),
    ("read https://acme.io/blog?utm_source=x", None, True),
    ("Book a demo today", None, True), ("Start your free trial", None, True),
    ("Use promo code LLM10", None, True), ("Neat thread https://x.com/fixture_user_54/status/1/pricing", None, False),
    (T_SCA, None, False), (T_SCA, "Fixture_User_32", True)])
def test_se_brand_detection(text, author, want, monkeypatch, tmp_path):
    p = tmp_path / "b.json"; p.write_text(json.dumps(["@fixture_user_32"]))
    monkeypatch.setattr("src.brand.BRAND_ACCOUNTS_PATH", p)
    assert is_brand_post(text, author) is want


@pytest.mark.parametrize("mode", [None, "either"])
def test_se_brand_ad_arguing_claim_queued_same_S_no_draft(mk, monkeypatch, mode):
    if mode:
        monkeypatch.setenv("MS_FIT_GRADED_MODE", mode)
    else:
        monkeypatch.delenv("MS_FIT_GRADED_MODE", raising=False)
    ad = T_SCA + " Start a free trial: https://acme.io/demo?utm_source=x"   # (book a demo / promo code → promo_cta kill)
    plain = T_SCA + " See https://acme.io/blog/notes"
    g = FakeGrader({ad: "claim", plain: "claim"})
    c1, a1 = mk(g)
    r_ad = run(c1, [X(1000000000000020, ad)])[0]
    c2, a2 = mk(g)
    r_plain = run(c2, [X(1000000000000021, plain)])[0]
    assert r_ad["status"] == "queued" and r_ad["labels"] == ["brand_post"] and r_ad["S"] == r_plain["S"]
    assert r_ad["no_draft"] is True and not r_ad.get("predrafted") and r_ad["copy_enabled"] is False
    assert r_ad["predraft"]["code"] == "no_draft_brand" and a1.drafts == []
    assert r_plain.get("predrafted") and r_plain["labels"] == []
    card = [x for x in c1.get("/queue").json()["cards"] if x["card_id"] == r_ad["card_id"]][0]
    assert card["labels"] == ["brand_post"]
