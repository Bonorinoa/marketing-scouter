"""x-brief bridge: fake binary only. Never runs the real x-brief, never posts."""
import json
import os
import stat
import threading
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from src.api import core, xbrief_bridge as xb
from src.api.app import create_app
from tests.test_api_dor import X_WEIRD, SCA, card_and_handoff

FAKE = r'''#!/usr/bin/env python3
import json, os, sys, time
log = os.environ.get("FAKE_LOG_PATH") or "%(log)s"
open(log, "a").write(json.dumps({"argv": sys.argv[1:], "path": os.environ.get("PATH", ""),
                                 "home": os.environ.get("XBRIEF_HOME"), "vault": os.environ.get("XBRIEF_VAULT_PATH")}) + "\n")
mode = open("%(mode)s").read().strip()
args = sys.argv[1:]
sub = args[0]
if sub == "doctor":
    print("OK   python"); sys.exit(0)
if mode == "sleep":
    time.sleep(30)
if mode == "fail" and sub == "process":
    print("boom", file=sys.stderr); sys.exit(3)
if sub == "add":
    print(json.dumps({"state": "added", "url": args[1]})); sys.exit(0)
if sub == "process":
    url = json.loads(open(log).readline())["argv"][1]
    brief = "%(brief)s"
    draft = "" if mode == "nodraft" else "- **Draft:** %(text)s\n"
    open(brief, "w").write("## Recommendations\n\n### #1 — @fixture_user_41 / t\n\n- **Source:** " + url + "\n" + draft)
    print("analysing 1\n" + json.dumps({"run_id": "r1", "status": "success", "brief": brief}, indent=2))
    sys.exit(0)
sys.exit(9)
'''
DRAFT = "Non-WEIRD synthetic cultural agents keep cultural patterns that WEIRD-only LLM participants lose."


@pytest.fixture
def fake(tmp_path, monkeypatch):
    log, mode, brief = tmp_path / "calls.jsonl", tmp_path / "mode", tmp_path / "brief.md"
    mode.write_text("ok")
    b = tmp_path / "x-brief"
    b.write_text(FAKE % {"log": log, "mode": mode, "brief": brief, "text": DRAFT})
    b.chmod(b.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("MS_XBRIEF_BIN", str(b))
    monkeypatch.setenv("MS_XBRIEF_TIMEOUT", "5")

    class F:
        def calls(self):
            return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
        def set(self, m):
            mode.write_text(m)
    return F()


@pytest.fixture
def c(tmp_path):
    return TestClient(create_app(str(tmp_path / "db")))


def hid(c, **kw):
    _card, h = card_and_handoff(c, **kw)
    return h["payload"]["handoff_id"]


def test_success_path_stores_draft_and_no_win(c, fake):
    h = hid(c)
    wins0, ev0 = c.get("/wins").json(), len(c.get("/events").json())
    r = c.post(f"/handoff/{h}/draft").json()
    assert r["status"] == "ok" and r["draft_text"] == DRAFT and r["authored_by"] == "model"
    assert r["label"] == "model draft" and r["error"] is None and set(r["gate"]) == {"ok", "reasons"}
    assert r["door"] == "EconLLM" and r["lang"] == "en"
    r2 = c.post(f"/handoff/{h}/draft").json()  # twice: no double count
    assert r2["status"] == "ok"
    assert c.get("/wins").json() == wins0 == []
    assert not [e for e in c.get("/events").json()[ev0:] if e["kind"] in ("win", "human")]
    assert c.get(f"/handoff/{h}").json()["status"] == "sealed"
    assert c.get(f"/handoff/{h}/draft").json()["draft_text"] == DRAFT
    subs = [x["argv"][0] for x in fake.calls()]
    assert set(subs) <= {"add", "process"}


def test_payload_has_no_samples_and_url_is_one_literal_arg(c, fake, tmp_path):
    evil = "https://x.com/fixture_user_54/status/1;touch " + str(tmp_path / "pwned") + "$(id)`id`\nrm -rf /"
    h = hid(c, body={**X_WEIRD, "url": evil})
    c.post(f"/handoff/{h}/draft")
    add = [x for x in fake.calls() if x["argv"][0] == "add"][0]["argv"]
    assert add[1] == evil and not (tmp_path / "pwned").exists()
    blob = json.dumps([a for x in fake.calls() for a in x["argv"] if a != evil]).lower()
    assert "sample" not in blob and "corpus" not in blob
    with pytest.raises(AssertionError):
        xb.draft({"url": "u", "door": "EconLLM", "voice_samples": ["x"]})


def test_bridge_input_fields_only():
    inp = xb.bridge_input({"url": "u", "asset_id": "a", "door": "EconLLM",
                           "xbrief_interests": {"active": ["s"], "paused": ["p"]}, "samples": 1}, "T")
    assert set(inp) == {"url", "asset_id", "asset_title", "door", "text", "author", "asset_claim", "asset_caveat",
                        "active_slugs"}
    assert inp["text"] is None and inp["author"] is None


def test_bridge_passes_post_text_and_author_as_literal_args(fake):
    xb.draft({"url": "https://x.com/fixture_user_54/status/1", "door": "EconLLM", "text": "post; $(id) text", "author": "fixture_user_40"})
    add = [x for x in fake.calls() if x["argv"][0] == "add"][0]["argv"]
    assert add[add.index("--text") + 1] == "post; $(id) text" and add[add.index("--author") + 1] == "@fixture_user_40"
    assert "--no-fetch" in add


def test_timeout_kills_process_group(c, fake, monkeypatch):
    fake.set("sleep")
    monkeypatch.setenv("MS_XBRIEF_TIMEOUT", "1")
    h = hid(c)
    t = time.monotonic()
    r = c.post(f"/handoff/{h}/draft").json()
    assert time.monotonic() - t < 10
    assert r["status"] == "error" and r["error"]["code"] == "xbrief_timeout"
    b = os.environ["MS_XBRIEF_BIN"]
    assert os.system(f"pgrep -f '[{b[0]}]{b[1:]} add' >/dev/null") != 0


def test_missing_binary_unavailable(c, monkeypatch, tmp_path):
    monkeypatch.setenv("MS_XBRIEF_BIN", str(tmp_path / "nope"))
    h = hid(c)
    r = c.post(f"/handoff/{h}/draft").json()
    assert r["error"]["code"] == "xbrief_unavailable" and r["error"]["message"]
    hz = c.get("/xbrief/health").json()
    assert hz["present"] is False and hz["up"] is False


def test_nonzero_exit_and_no_draft(c, fake):
    fake.set("fail")
    assert c.post(f"/handoff/{hid(c)}/draft").json()["error"]["code"] == "xbrief_failed"
    fake.set("nodraft")  # a second post: one card per post, so the same URL would be a duplicate_post
    other = {**X_WEIRD, "url": X_WEIRD["url"].rstrip("/") + "7"}
    assert c.post(f"/handoff/{hid(c, body=other)}/draft").json()["error"]["code"] == "xbrief_no_draft"


def test_health_up(c, fake):
    hz = c.get("/xbrief/health").json()
    assert hz["present"] and hz["doctor_ok"] and hz["up"]


@pytest.mark.parametrize("sub", ["publish", "published", "mark", "auth", "schedule", "install",
                                 "capture", "on", "run", "style", "brief"])
def test_forbidden_subcommands(sub):
    with pytest.raises(xb.ForbiddenSubcommand):
        xb.build_argv(sub)


def test_allowlist_has_no_posting_path():
    assert xb.ALLOWED == {"add", "process", "doctor"}
    src = open(xb.__file__).read()
    assert "shell=True" not in src


def test_sandbox_removes_xurl(tmp_path, monkeypatch):
    d = tmp_path / "bin"; d.mkdir(); (d / "xurl").write_text("#!/bin/sh\n")
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}/usr/bin")
    assert str(d) not in xb.sandbox_env()["PATH"].split(os.pathsep)


def test_no_xurl_reachable_from_child(c, fake, tmp_path, monkeypatch):
    d = tmp_path / "xb"; d.mkdir(); (d / "xurl").write_text("#!/bin/sh\n")
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}" + os.environ["PATH"])
    c.post(f"/handoff/{hid(c)}/draft")
    for call in fake.calls():
        assert str(d) not in call["path"].split(os.pathsep)
    add = [x for x in fake.calls() if x["argv"][0] == "add"][0]["argv"]
    assert "--no-fetch" in add and "--no-screenshot" in add


def test_expired_forged_unknown_refused(c, fake, monkeypatch):
    h = hid(c)
    real = core._now
    monkeypatch.setattr(core, "_now", lambda: real() + timedelta(hours=100))
    assert c.post(f"/handoff/{h}/draft").status_code == 410
    monkeypatch.setattr(core, "_now", real)
    h2 = hid(c)
    import sqlite3
    api = c.app.state.api
    with sqlite3.connect(api._db) as db:
        db.execute("UPDATE handoffs SET payload=replace(payload,'EconLLM','Augusto-civic') WHERE handoff_id=?", (h2,))
    assert c.post(f"/handoff/{h2}/draft").json()["code"] == "forged_handoff"
    assert c.post("/handoff/hand_nope/draft").status_code == 404
    assert fake.calls() == []


def test_door_required(c, fake):
    h = hid(c)
    api = c.app.state.api
    import sqlite3
    with sqlite3.connect(api._db) as db:
        p = json.loads(db.execute("SELECT payload FROM handoffs WHERE handoff_id=?", (h,)).fetchone()[0])
        p["door"] = None
        db.execute("UPDATE handoffs SET payload=?, seal=? WHERE handoff_id=?", (json.dumps(p), api._seal(p), h))
    r = c.post(f"/handoff/{h}/draft")
    assert r.status_code == 422 and r.json()["code"] == "door_required"
    with pytest.raises(ValueError):
        xb.draft({"url": "u", "door": None})


def test_concurrent_draft_409(c, fake, monkeypatch):
    fake.set("sleep")
    monkeypatch.setenv("MS_XBRIEF_TIMEOUT", "2")
    h = hid(c)
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("a", c.post(f"/handoff/{h}/draft")))
    t.start(); time.sleep(0.5)
    r = c.post(f"/handoff/{h}/draft")
    t.join()
    assert r.status_code == 409 and r.json()["message"] == "Already drafting this one."


def test_check_endpoint_authorship_and_warnings(c, fake):
    h = hid(c)
    c.post(f"/handoff/{h}/draft")
    same = c.post(f"/handoff/{h}/draft/check", json={"draft_text": DRAFT}).json()
    assert same["authored_by"] == "model" and "ok" in same["gate"]
    edited = c.post(f"/handoff/{h}/draft/check",
                    json={"draft_text": DRAFT + " see https://evil.example/x @fixture_user_52"}).json()
    assert edited["authored_by"] == "user_edited"
    codes = {w["code"] for w in edited["warnings"]}
    assert {"foreign_link", "foreign_handle"} <= codes  # gate warnings (e.g. lang_uncertain) merge in too
    assert c.get("/wins").json() == []
    assert c.get(f"/handoff/{h}").json()["status"] == "sealed"


def test_openapi_exposes_routes(c):
    spec = c.get("/openapi.json").json()
    assert "post" in spec["paths"]["/handoff/{handoff_id}/draft"]
    assert "post" in spec["paths"]["/handoff/{handoff_id}/draft/check"]
    assert "get" in spec["paths"]["/xbrief/health"]
    props = spec["components"]["schemas"]["DraftOut"]["properties"]
    assert {"status", "draft_text", "authored_by", "gate", "warnings", "elapsed_ms", "error"} <= set(props)


def test_authored_by_server_only_and_normalized(c, fake):
    h = hid(c)
    c.post(f"/handoff/{h}/draft")
    ws = "  " + DRAFT.replace(" ", "  \u200b", 3) + "\n"
    assert c.post(f"/handoff/{h}/draft/check", json={"draft_text": ws}).json()["authored_by"] == "model"
    r = c.post(f"/handoff/{h}/draft/check", json={"draft_text": DRAFT + "!", "authored_by": "model"})
    assert r.status_code == 422


# ── Adversarial point 3: read-back must match THIS post, never position ──────────
from src.api.xbrief_bridge import extract_draft as _xd

_TWO = """## Recommendations

### #1 — @fixture_user_47 / t
- **Source:** https://x.com/fixture_user_66/status/9000000000000000911
- **Draft:** OTHER POST DRAFT

### #2 — @fixture_user_49 / t
- **Source:** https://twitter.com/fixture_user_65/status/9000000000000000922?s=20
- **Draft:** THIS POST DRAFT
"""


def test_readback_matches_status_id_not_position():
    assert _xd(_TWO, "https://x.com/fixture_user_65/status/9000000000000000922") == "THIS POST DRAFT"
    assert _xd(_TWO, "https://x.com/fixture_user_66/status/9000000000000000911") == "OTHER POST DRAFT"


def test_readback_absent_post_gets_no_draft():
    assert _xd(_TWO, "https://x.com/fixture_user_65/status/9000000000000000933") is None


def test_readback_ambiguous_match_gets_no_draft():
    dup = _TWO + "\n### #3 — @fixture_user_49 / t\n- **Source:** https://x.com/fixture_user_65/status/9000000000000000922\n- **Draft:** DUP\n"
    assert _xd(dup, "https://x.com/fixture_user_65/status/9000000000000000922") is None


def test_last_json_ignores_trailing_lines_after_summary():
    out = ("analysing 1 active post(s)\nnote: x\n{\n  \"run_id\": 2,\n  \"brief\": \"/b.md\"\n}\n\n"
           "brief: /b.md\npool unchanged: {'active': 1}\n")
    assert xb._last_json(out) == {"run_id": 2, "brief": "/b.md"}
    assert xb._last_json('{"a": 1}') == {"a": 1} and xb._last_json("nothing") is None


def test_isolated_run_dir_carries_claim_and_caveat(fake, tmp_path, monkeypatch):
    import pathlib
    vault = pathlib.Path(os.environ["MS_XBRIEF_VAULT"])
    (vault / "Writing").mkdir(parents=True)
    (vault / "Profile").mkdir()
    (vault / "Profile" / "User.md").write_text("me")
    (vault / "Writing" / "Samples.md").write_text("samples")
    (vault / "Writing" / "Guidelines.md").write_text(
        "length: medium  # c\n<!-- x-brief:writing-user:begin -->\nPlain words.\n<!-- x-brief:writing-user:end -->\n")
    r = xb.draft({"url": "https://x.com/fixture_user_54/status/1234567", "door": "EconLLM", "text": "t",
                  "asset_claim": "Synthetic agents track non-WEIRD behavior.", "asset_caveat": "Directional only."})
    calls = fake.calls()
    homes = {c["home"] for c in calls}
    assert len(homes) == 1 and None not in homes and str(tmp_path / "xb-runs") in next(iter(homes))
    run = pathlib.Path(r["provenance"]["run_dir"])
    g = (run / "vault" / "Writing" / "Guidelines.md").read_text()
    user = g.split("writing-user:begin")[1].split("writing-user:end")[0]
    assert "Synthetic agents track non-WEIRD behavior." in user and "Directional only." not in user and "Plain words." in user
    assert "do not include caveats" in user   # caveat is a card field, never sent to be written into the reply
    assert (vault / "Writing" / "Guidelines.md").read_text().count("Directional") == 0   # real file untouched
    assert (run / "vault" / "Profile" / "User.md").read_text() == "me"
    assert "length: short" in g and "length: medium" in (vault / "Writing" / "Guidelines.md").read_text()
    assert (run / "project" / "config" / "config.yaml").is_file()


def test_isolation_off_uses_real_project(fake, monkeypatch):
    monkeypatch.setenv("MS_XBRIEF_ISOLATE", "0")
    xb.draft({"url": "https://x.com/fixture_user_54/status/1", "door": "EconLLM"})
    assert all(c["home"] is None for c in fake.calls())


def test_predraft_sends_matched_claim_and_caveat(monkeypatch):
    from src.api import core
    seen = {}
    monkeypatch.setenv("MS_INTAKE_PREDRAFT", "xbrief")
    monkeypatch.setattr(xb, "draft", lambda inp, force=False: seen.update(inp, force=force) or {"status": "ok", "draft_text": "d"})
    api = core.ScouterAPI.__new__(core.ScouterAPI)
    api.predrafter = None
    api._predraft({"text": "hello", "author_handle": "h"},
                  {"url": "u", "door": "EconLLM", "claim": "C1", "asset": {"asset_id": "a", "title": "T", "caveat": "Cav."}})
    assert seen["asset_claim"] == "C1" and seen["asset_caveat"] == "Cav." and seen["text"] == "hello"
    assert seen["force"] is False   # only the drafting probe forces a draft


def test_probe_run_dir_lowers_ranker_bars_only_when_forced(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"; cfg.mkdir()
    (cfg / "config.yaml").write_text("jev:\n  min_score: 1.5\nranking:\n  min_confidence: 5\n  min_candidates: 2\n")
    monkeypatch.setenv("MS_XBRIEF_CONFIG", str(cfg / "config.yaml"))
    monkeypatch.setenv("MS_XBRIEF_VAULT", str(tmp_path / "vault"))
    monkeypatch.setenv("MS_XBRIEF_RUNS", str(tmp_path / "runs"))
    p, _ = xb.make_run_dir("a", None, None)
    assert "min_candidates: 2" in (p / "config" / "config.yaml").read_text()
    p, _ = xb.make_run_dir("b", None, None, force=True)
    t = (p / "config" / "config.yaml").read_text()
    assert "min_candidates: 1" in t and "min_confidence: 0" in t and "min_score: 0" in t
    assert "min_candidates: 2" in (cfg / "config.yaml").read_text()   # user's config untouched


def _probe_api(monkeypatch, tmp_path, results):
    from src.api import core
    monkeypatch.setenv("MS_INTAKE_PREDRAFT", "xbrief")
    calls = []

    def fake_draft(inp, force=False):
        calls.append(force)
        return results[min(len(calls), len(results)) - 1]
    monkeypatch.setattr(xb, "draft", fake_draft)
    return core.ScouterAPI(str(tmp_path)), calls


def test_probe_declined_by_model_is_not_drafting_off(monkeypatch, tmp_path):
    no = {"status": "error", "code": "xbrief_no_draft", "message": "x-brief didn't write a draft"}
    api, calls = _probe_api(monkeypatch, tmp_path, [no])
    r = api.drafting_probe(force=True)
    assert r["ok"] is True and r["probe_draft_produced"] is False and calls == [True, True, True]
    assert "chose not to draft" in r["reason"]


def test_probe_retries_then_real_draft(monkeypatch, tmp_path):
    no = {"status": "error", "code": "xbrief_no_draft", "message": "x"}
    api, calls = _probe_api(monkeypatch, tmp_path, [no, {"status": "ok", "draft_text": "Some real draft text."}])
    r = api.drafting_probe(force=True)
    assert len(calls) == 2 and r["probe_draft_produced"] is True


def test_probe_real_failure_is_still_off(monkeypatch, tmp_path):
    api, _ = _probe_api(monkeypatch, tmp_path, [{"status": "error", "code": "xbrief_failed", "message": "boom"}])
    r = api.drafting_probe(force=True)
    assert r["ok"] is False and r["probe_draft_produced"] is False


def test_caveat_never_appended_to_draft(fake):
    """Pinned 2026-10-14: the bridge never appends the caveat; it lives in the card's caveat field."""
    r = xb.draft({"url": "https://x.com/fixture_user_54/status/1", "door": "EconLLM", "asset_caveat": "Directional only."})
    assert "Directional only" not in r["draft_text"] and r["caveat_appended"] is False and r["draft_text"] == DRAFT
    r2 = xb.draft({"url": "https://x.com/fixture_user_54/status/1", "door": "EconLLM"})
    assert r2["caveat_appended"] is False and r2["draft_text"] == DRAFT
