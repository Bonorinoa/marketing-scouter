"""se_ shadow graded Fit (MS_FIT_SHADOW=1): log-only; never touches S, cards, queue or slots."""
import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from tests.test_intake_contract import T_NOFIT, T_SCA

JUNK = "#ai #llm #gpt #crypto #airdrop #moon free tokens"


class FakeGrader:
    model, prompt_version = "fake/model", "shadow-test"

    def __init__(self, level="claim", boom=False):
        self.level, self.boom, self.calls = level, boom, []

    def __call__(self, text, claim):
        self.calls.append(text)
        if self.boom:
            raise RuntimeError("kaboom")
        return self.level


def _client(tmp_path, grader):
    app = create_app(str(tmp_path))
    api = app.state.api
    api.predrafter = lambda p, card: {"status": "ok", "draft_text": card["draft"]}
    api.fit_grader = grader
    return TestClient(app), api


def X(sid, text=T_SCA):
    return {"url": f"https://x.com/fixture_user_54/status/{sid}", "text": text, "reply_count": 4, "quote_count": 1}


def _run(c, api, run_id, posts, dry=False):
    r = c.post("/intake/x", json={"run_id": run_id, "posts": posts, "dry_run": dry})
    t = api._fit_shadow_thread
    if t is not None:
        t.join(10)
    return r


def _shadow(api):
    return [e for e in api.events() if e["kind"] == "fit_shadow"]


POSTS = [X(1000000000000001 + i) for i in range(3)] + [X(1000000000000010, T_NOFIT)]


def _strip(j):
    return [{k: v for k, v in r.items() if k not in ("card_id",)} for r in j["posts"]]


def test_se_shadow_does_not_change_cards_S_or_queue(tmp_path, monkeypatch):
    monkeypatch.delenv("MS_FIT_GRADED", raising=False)
    out = {}
    for flag in ("0", "1"):
        monkeypatch.setenv("MS_FIT_SHADOW", flag)
        c, api = _client(tmp_path / flag, FakeGrader("none"))
        j = _run(c, api, "discovery-a", POSTS).json()
        st = c.get("/status").json()
        out[flag] = (_strip(j), j["counts"], st.get("queue_size"),
                     sorted((x.S, x.slugs[0] if x.slugs else None) for x in api.store.open_cards(__import__("src.models", fromlist=["Outlet"]).Outlet.X)))
        assert bool(_shadow(api)) == (flag == "1")
    assert out["0"] == out["1"]


def test_se_dry_and_non_discovery_runs_no_shadow(tmp_path, monkeypatch):
    monkeypatch.setenv("MS_FIT_SHADOW", "1")
    c, api = _client(tmp_path, FakeGrader())
    _run(c, api, "discovery-dry", [X(1000000000000001)], dry=True)
    _run(c, api, "manual-1", [X(1000000000000002)])
    assert _shadow(api) == [] and api.fit_grader.calls == []


def test_se_shadow_cap_respected(tmp_path, monkeypatch):
    monkeypatch.setenv("MS_FIT_SHADOW", "1")
    monkeypatch.setenv("MS_FIT_SHADOW_MAX_CALLS", "3")   # cap counts POSTS sent to the grader (like intake)
    g = FakeGrader("claim")
    c, api = _client(tmp_path, g)
    _run(c, api, "discovery-cap", [X(1000000000000001 + i) for i in range(5)])
    ev = _shadow(api)[-1]
    n_assets = len([a for a in api.store.list_assets() if a.slugs])
    assert ev["posts_called"] == 3 and ev["posts_graded"] == 3 and ev["capped"] is True
    assert len(g.calls) == 3 * n_assets and ev["model_calls"] == len(g.calls)
    # cache hits don't count toward the cap: pre-seed every grade for a fresh post
    from src import fit_graded as fg
    from src.fit import fit_slug_map
    sid = "1000000000000099"
    for a in api.store.list_assets():
        if a.slugs:
            cl = a.one_line_claim or fit_slug_map()[a.slugs[0]].claim_one_liner
            api._fit_cache().put(sid, a.asset_id, fg.cache_version(g), fg.claim_hash(cl), g.model, "topic")
    g.calls.clear()
    _run(c, api, "discovery-cap2", [X(int(sid))])
    ev2 = _shadow(api)[-1]
    assert ev2["model_calls"] == 0 and ev2["cache_hits"] > 3 and ev2["capped"] is False and ev2["posts_graded"] == 1


def test_se_shadow_grader_error_logged_intake_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("MS_FIT_SHADOW", "1")
    c, api = _client(tmp_path, FakeGrader(boom=True))
    r = _run(c, api, "discovery-err", [X(1000000000000001)])
    assert r.status_code == 200
    assert "error" in _shadow(api)[-1]
    # grader missing entirely
    api.fit_grader = None
    monkeypatch.setattr("src.fit_graded.OpenRouterGrader.available", classmethod(lambda cls: False))
    r = _run(c, api, "discovery-err2", [X(1000000000000002)])
    assert r.status_code == 200 and _shadow(api)[-1]["error"] == "grader_unavailable"


def test_se_shadow_skips_junk_and_logs_disagreements(tmp_path, monkeypatch):
    monkeypatch.setenv("MS_FIT_SHADOW", "1")
    g = FakeGrader("claim")
    c, api = _client(tmp_path, g)
    _run(c, api, "discovery-j", [X(1000000000000001, JUNK), X(1000000000000002, T_NOFIT)])
    assert JUNK not in g.calls
    ev = _shadow(api)[-1]
    assert ev["posts_graded"] == 1
    d = ev["word_killed_graded_not_none"]
    assert ev["n_word_killed_graded_not_none"] == 1 and ev["n_word_passed_graded_none"] == 0
    assert d[0]["status_id"] == "1000000000000002" and d[0]["graded_best_level"] == "claim"
    assert d[0]["word_status"]["status"] == "killed"


def test_se_empty_fit_killed_post_is_graded(tmp_path, monkeypatch):
    monkeypatch.setenv("MS_FIT_SHADOW", "1")
    g = FakeGrader("topic")
    c, api = _client(tmp_path, g)
    j = _run(c, api, "discovery-ef", [X(1000000000000003, T_NOFIT), X(1000000000000004)]).json()
    assert "empty_fit" in j["posts"][0]["reasons"]
    assert T_NOFIT in g.calls
    ev = _shadow(api)[-1]
    k = ev["word_killed_graded_not_none"]
    assert [x["status_id"] for x in k] == ["1000000000000003"] and "empty_fit" in k[0]["word_status"]["reasons"]
    assert ev["posts_graded"] == 2 and ev["n_word_passed_graded_none"] == 0
    # grader none on a word-passed post lands in the other list
    g.level = "none"
    _run(c, api, "discovery-ef2", [X(1000000000000005)])
    ev = _shadow(api)[-1]
    assert ev["n_word_passed_graded_none"] == 1 and ev["word_killed_graded_not_none"] == []
