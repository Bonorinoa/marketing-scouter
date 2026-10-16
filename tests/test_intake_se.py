"""se_ Systems Engineer: link-only paste, /status, POST /intake/x shape, cap, gate, no Sheets route."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.api import core
from src.api.app import create_app
from src.models import Decision
from tests.test_intake_contract import T_GPT, T_NOFIT, T_SCA

_N = iter(range(10**15, 10**16))


@pytest.fixture
def c(tmp_path):
    app = create_app(str(tmp_path))
    app.state.api.predrafter = lambda p, card: {"status": "ok", "draft_text": card["draft"]}
    return TestClient(app)


def P(text=T_SCA, sid=None, **kw):
    return {"url": f"https://x.com/fixture_user_60/status/{sid or next(_N)}", "text": text, "author_handle": "someone",
            "reply_count": 4, "quote_count": 1, "like_count": 0, **kw}


def go(c, posts, run_id="run_se"):
    return c.post("/intake/x", json={"run_id": run_id, "posts": posts})


def test_se_link_only_paste_refused(c):
    for snip in ("", "   ", "https://x.com/fixture_user_54/status/9", "www.example.com/x  "):
        r = c.post("/recommend", json={"url": "https://x.com/fixture_user_54/status/9", "outlet": "x", "snippet": snip})
        assert r.status_code == 422 and r.json()["code"] == "link_only"
        assert r.json()["message"] == "Paste the post text too, or let discovery fetch it."
    assert not [e for e in c.get("/events").json() if e["kind"] == "scored"]


def test_se_status_plain_words(c, monkeypatch):
    s = c.app.state.api.status(lambda: {"present": False, "up": False})
    assert s["x_last_checked"] == {"at": None, "sentence": "X hasn't been checked yet.", "run_id": None}
    assert s["drafting_ok"] is True and s["drafting_source"] in ("config", "probe")
    assert s["xbrief_selfcheck"] == {"ok": False, "note": "x-brief isn't installed on this computer."}
    assert s["queue_size"] == 0
    go(c, [P()], run_id="discovery-1")
    later = datetime.now(timezone.utc) + timedelta(hours=2)
    monkeypatch.setattr(core, "_now", lambda: later)
    s = c.app.state.api.status(lambda: {"present": True, "up": True, "doctor_ok": True})
    assert s["x_last_checked"]["sentence"] == "X was last checked 2 hours ago."
    assert s["x_last_checked"]["run_id"] == "discovery-1" and s["drafting_ok"] is True and s["xbrief_selfcheck"]["ok"] and s["queue_size"] == 1
    assert c.get("/status").status_code == 200


def test_se_intake_refusals_and_dedupe(c):
    good = P()
    rows = go(c, [{**P(), "url": "https://example.com/status/1"}, P(text=""), P(text="https://x.com/fixture_user_54"),
                  good, dict(good)]).json()["posts"]
    assert [r["status"] for r in rows] == ["refused", "refused", "refused", "queued", "duplicate"]
    assert rows[0]["reasons"] == ["not_x_status_url"] and rows[1]["reasons"] == ["text_required"]
    again = go(c, [good], run_id="run_2").json()
    assert again["posts"][0]["status"] == "duplicate" and again["counts"]["duplicate"] == 1
    assert go(c, [P() for _ in range(51)]).status_code == 422
    assert go(c, [P() for _ in range(51)]).json()["code"] == "batch_too_large"


def test_se_intake_killed_held(c):
    old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    rows = go(c, [P(T_NOFIT)] + [P(T_SCA) for _ in range(7)] + [P(T_GPT, created_at=old)]).json()["posts"]
    assert rows[0]["status"] == "killed" and rows[0]["reasons"] == ["empty_fit"]
    assert rows[-1]["status"] == "held" and rows[-1]["reasons"][0] in ("below_replace_bar", "watch")


def test_se_predraft_cap_10_by_S_and_gate(c, monkeypatch):
    monkeypatch.setattr(core, "queue_decision", lambda card, open_: (Decision.ENQUEUE, None))
    calls = []
    def drafter(p, card):
        calls.append(card["card_id"])
        return {"status": "ok", "draft_text": "Esto es un borrador en español sobre los participantes sintéticos."
                if len(calls) == 1 else card["draft"]}
    c.app.state.api.predrafter = drafter
    old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    ps = [P(T_GPT, created_at=old, like_count=10**6) for _ in range(8)] + [P(T_SCA) for _ in range(6)]
    j = go(c, ps).json()
    assert j["counts"]["queued"] == 14 and len(calls) == 10
    pre = [r for r in j["posts"] if r["predrafted"]]
    assert len(pre) == 10
    floor = min(r["S"] for r in pre)
    assert all(r["S"] <= floor for r in j["posts"] if not r["predrafted"])
    first = next(r for r in pre if r["card_id"] == calls[0])
    assert first["copy_enabled"] is False and any(x["code"] == "lang_mismatch" for x in first["gate"]["reasons"])
    card = next(x for x in c.get("/queue").json()["cards"] if x["card_id"] == calls[0])
    assert card["copy_enabled"] is False and card["predraft"]["gate"]["reasons"]
    ev = [e for e in c.get("/events").json() if e["kind"] == "intake_run"][-1]
    assert ev["predrafted"] == 10 and "total_ms" in ev and ev["scout_run_id"] == "run_se"


def test_se_intake_openapi_and_no_sheets(c):
    spec = c.get("/openapi.json").json()["paths"]
    assert {"409", "422"} <= set(spec["/intake/x"]["post"]["responses"])
    assert "/wins/export/sheets" not in spec and "/status" in spec
    assert c.post("/wins/export/sheets").status_code in (404, 405)


def test_se_status_selfcheck_never_drives_drafting(tmp_path, monkeypatch):
    monkeypatch.delenv("MS_INTAKE_PREDRAFT", raising=False)
    api = create_app(str(tmp_path)).state.api
    s = api.status(lambda: {"present": True, "up": True, "doctor_ok": False})
    assert s["drafting_ok"] is True and s["xbrief_selfcheck"]["ok"] is False
    assert "doesn't change whether drafting works" in s["xbrief_selfcheck"]["note"]


def test_se_status_probe_only_on_demand(tmp_path):
    """Default /status never drafts (no model call); ?probe=draft forces one test draft on demand."""
    api = create_app(str(tmp_path)).state.api
    calls = []
    api.predrafter = lambda p, card: calls.append(1) or {"status": "ok", "draft_text": "Esto es claramente un texto en español para X sobre participantes."}
    hl = lambda: {"present": False}
    s1 = api.status(hl)
    assert calls == [] and s1["drafting_source"] == "config" and s1["drafting_ok"] is True
    api.status(hl); api.status(hl)
    assert calls == []                      # repeated status / health / loop reads never draft
    s2 = api.status(hl, probe_draft=True)   # on demand
    assert len(calls) >= 1 and s2["drafting_source"] == "probe"
    assert s2["drafting_ok"] is False and "draft check" in s2["drafting_reason"]
    n = len(calls)
    s3 = api.status(hl)                     # config view remembers the last on-demand failure, no new call
    assert len(calls) == n and s3["drafting_ok"] is False and "last on-demand test" in s3["drafting_reason"]
    api.predrafter = lambda p, card: {"status": "error", "code": "xbrief_timeout", "message": "x-brief timed out"}
    assert api.drafting_probe(force=True)["ok"] is False
    assert "didn't come back" in api.status(hl)["drafting_reason"]


def test_se_status_probe_query_param(tmp_path):
    from fastapi.testclient import TestClient
    app = create_app(str(tmp_path)); api = app.state.api
    calls = []
    api.predrafter = lambda p, card: calls.append(1) or {"status": "ok", "draft_text": "x"}
    c = TestClient(app)
    c.get("/status"); c.get("/health")
    assert calls == []
    c.get("/status?probe=draft")
    assert calls


def test_se_x_last_checked_only_discovery_runs_with_real_posts(c):
    hl = lambda: {"present": False}
    go(c, [P()], run_id="manual-1")                                   # not a discovery run
    go(c, [{**P(), "url": "https://example.com/a"}], run_id="discovery-2")  # all refused
    assert c.app.state.api.status(hl)["x_last_checked"]["at"] is None
    go(c, [P()], run_id="discovery-3")
    assert c.app.state.api.status(hl)["x_last_checked"]["run_id"] == "discovery-3"


def test_se_zero_width_text_refused(c):
    for t in ("\u200b", " \u200c\u200d ", "\u2060\ufeff\n", "\u200b https://x.com/fixture_user_54/status/2"):
        row = go(c, [P(text=t)]).json()["posts"][0]
        assert row["status"] == "refused" and row["reasons"] == ["text_required"], row
    r = c.post("/recommend", json={"url": "https://x.com/fixture_user_54/status/9", "outlet": "x", "snippet": "\u200b\ufeff"})
    assert r.status_code == 422 and r.json()["code"] == "link_only"
    assert not [e for e in c.get("/events").json() if e["kind"] == "scored"]


def test_se_probe_reports_failing_asset_but_works(tmp_path):
    api = create_app(str(tmp_path)).state.api
    first = []
    def d(p, card):
        first.append(card["asset"]["asset_id"])
        return {"status": "ok", "draft_text": ("x" * 400) if len(first) == 1 else card["draft"]}
    api.predrafter = d
    pr = api.drafting_probe(force=True)
    assert pr["ok"] is True and pr["failed_assets"] and first[0] in pr["reason"]


def test_se_status_scoring_config(tmp_path, monkeypatch):
    from src.claims_hash import claims_sha, seed_claims_sha
    monkeypatch.setenv("MS_FIT_GRADER_PROVIDER", "typesafe")
    monkeypatch.setenv("MS_FIT_GRADER_DECISION", "cutoffs")
    monkeypatch.setenv("MS_LANG_CAP", "on")
    api = create_app(str(tmp_path)).state.api
    sc = api.status(lambda: {"present": False})["scoring_config"]
    assert sc["claim_echo"] == "on" and sc["lang_cap"] == "on"
    assert sc["grader"] == {"provider": "typesafe", "model": "jev-1.13.0", "criteria": "prompts/jev_criteria.v1.json",
                            "decision": "cutoffs", "cutoffs_file": "data/fit_grader/jev_cutoffs.v1.json"}
    assert sc["claims_sha"] == claims_sha(api.store.list_assets()) == seed_claims_sha("data/seed_inventory.json")
    monkeypatch.setenv("MS_LANG_CAP", "off")
    assert api.status(lambda: {"present": False})["scoring_config"]["lang_cap"] == "off"


def test_claims_sha_order_independent_and_sensitive():
    from src.claims_hash import claims_sha
    a = [{"asset_id": "a", "one_line_claim": "X.", "caveat": None}, {"asset_id": "b", "one_line_claim": "Y.", "caveat": "c"}]
    assert claims_sha(a) == claims_sha(list(reversed(a)))
    assert claims_sha(a) != claims_sha([{**a[0], "one_line_claim": "X!"}, a[1]])
    assert claims_sha(a) != claims_sha([a[0], {**a[1], "caveat": "d"}])
