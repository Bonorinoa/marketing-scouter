"""se_ self-exclusion (data/self_accounts.json) + live style hash on drafts."""
import glob
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import xbrief_bridge as xb
from src.api.app import create_app
from src.self_accounts import drop_self_posts, is_self_account, self_accounts
from tests.test_fit_either_se import FakeGrader
from tests.test_intake_contract import T_SCA

ROOT = Path(__file__).resolve().parent.parent


def test_se_self_accounts_file():
    assert self_accounts() == {"fixture_user_91", "fixture_user_92"}
    for h in ("@Fixture_User_91", " fixture_user_92 ", "@Fixture_User_92"):
        assert is_self_account(h)
    assert not is_self_account("someone_else") and not is_self_account(None)


@pytest.mark.parametrize("mode", [None, "model", "either"])
def test_se_self_post_killed_before_grader(tmp_path, monkeypatch, mode):
    if mode:
        monkeypatch.setenv("MS_FIT_GRADED_MODE", mode)
    else:
        monkeypatch.delenv("MS_FIT_GRADED_MODE", raising=False)
    monkeypatch.setenv("MS_FIT_SHADOW", "1")
    app = create_app(str(tmp_path))
    api = app.state.api
    g = FakeGrader({T_SCA: "claim"})
    api.fit_grader, api.fit_shadow_sync = g, True
    api.predrafter = lambda p, card: {"status": "ok", "draft_text": card["draft"]}
    rows = TestClient(app).post("/intake/x", json={"run_id": "discovery-self", "posts": [
        {"url": "https://x.com/fixture_user_91/status/1000000000000701", "text": T_SCA, "author_handle": "@Fixture_User_91"},
        {"url": "https://x.com/fixture_user_54/status/1000000000000702", "text": T_SCA, "author_handle": "Fixture_User_92"}]}).json()["posts"]
    assert all(r["status"] == "killed" and r["reasons"] == ["self_post"] for r in rows)
    assert g.calls == []                                                 # no grader call, no cap use
    assert not api.store.open_cards(__import__("src.models", fromlist=["Outlet"]).Outlet.X)


def test_se_drop_self_posts_helper():
    rows = [{"url": "https://x.com/fixture_user_91/status/1"}, {"author": "@fixture_user_92"},
            {"url": "https://x.com/fixture_user_66/status/2"}, {"post_id": "3"}]
    assert drop_self_posts(rows) == rows[2:]


def test_se_no_self_posts_in_labelled_batches():
    for f in (glob.glob(str(ROOT / "data" / "fit_rubric*" / "*.json")) + glob.glob(str(ROOT / "data" / "fit_rubric*.json"))
              + [str(ROOT / "tests" / "fixtures" / "fit_rubric.anon.json")]):   # data/ copies exist only on the box
        d = json.loads(Path(f).read_text())
        rows = (d.get("posts") or d.get("labels") or [e for a in (d.get("assets") or {}).values()
                                                       for e in a.get("examples", [])]) if isinstance(d, dict) else d
        rows = [r for r in rows if isinstance(r, dict)]
        assert drop_self_posts(rows) == rows, f


def test_se_style_info_live_hash(tmp_path, monkeypatch):
    guide = tmp_path / "style_augusto.v2.md"
    monkeypatch.setenv("MS_STYLE_FILE", str(guide))
    i = xb.style_info()
    assert (i["style_version"], i["style_sha"], i["style_file_present"], i["style_ok"]) == (None, None, False, False)
    guide.write_text("v2 text")
    a = xb.style_info()
    assert (a["style_version"], a["style_sha"], a["style_file_present"]) == (
        "style_augusto.v2", hashlib.sha256(b"v2 text").hexdigest(), True)
    assert a["style_ok"] is False   # not the pinned sha
    guide.write_text("v2 text + edits")                      # Marketing edits: no restart needed
    assert xb.style_info()["style_sha"] != a["style_sha"]


def test_default_style_file_is_v1_and_style_files_gitignored():
    assert xb.DEFAULT_STYLE == "v1" and xb.STYLE_FILE.name == "style_augusto.v1.md"
    import subprocess
    for f in ("prompts/style_augusto.v1.md", "prompts/style_augusto.v2.md"):
        assert subprocess.run(["git", "check-ignore", "-q", f], cwd=ROOT).returncode == 0


def test_missing_style_health_and_draft_fail_closed(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from src.api.app import create_app
    monkeypatch.setenv("MS_STYLE_FILE", str(tmp_path / "gone.md"))
    h = TestClient(create_app(str(tmp_path / "data"))).get("/health").json()
    assert h["style_file_present"] is False and h["style_sha"] is None
    r = xb.draft({"door": "EconLLM", "url": "https://x.com/fixture_user_54/status/1", "text": "t"})
    assert r["status"] == "error" and r["code"] == "style_missing" and r["draft_text"] is None
    good = tmp_path / "style_augusto.v2.md"; good.write_text("ok")
    monkeypatch.setenv("MS_STYLE_FILE", str(good))
    h = TestClient(create_app(str(tmp_path / "data2"))).get("/health").json()
    assert h["style_file_present"] is True and h["style_sha"] == hashlib.sha256(b"ok").hexdigest()


def test_run_dir_links_bridge_style_not_xbrief_default(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"; cfg.mkdir()
    (cfg / "config.yaml").write_text("model: x\n")
    (cfg / "x-style.md").write_text("DEFAULT v1")
    good = tmp_path / "style_augusto.v2.md"; good.write_text("V2")
    monkeypatch.setenv("MS_XBRIEF_CONFIG", str(cfg / "config.yaml"))
    monkeypatch.setenv("MS_XBRIEF_VAULT", str(tmp_path / "vault"))
    monkeypatch.setenv("MS_XBRIEF_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("MS_STYLE_FILE", str(good))
    proj, _v = xb.make_run_dir("t", None, None)
    assert (proj / "config" / "x-style.md").read_text() == "V2"


def test_se_style_recorded_on_predraft(tmp_path):
    app = create_app(str(tmp_path))
    api = app.state.api
    api.predrafter = lambda p, card: {"status": "ok", "draft_text": card["draft"], "model": "m",
                                      "style_version": "style_augusto.v1", "style_sha": "abc"}
    row = TestClient(app).post("/intake/x", json={"run_id": "d", "posts": [
        {"url": "https://x.com/fixture_user_54/status/1000000000000703", "text": T_SCA, "reply_count": 4}]}).json()["posts"][0]
    assert row["predraft"]["style_version"] == "style_augusto.v1" and row["predraft"]["style_sha"] == "abc"
    assert api._predraft_meta(row["card_id"])["style_sha"] == "abc"


def test_se_bridge_draft_carries_style(monkeypatch, tmp_path):
    import subprocess
    monkeypatch.setenv("MS_STYLE_FILE", str(tmp_path / "missing.md"))
    def fake_run(sub, *a, **k):
        return subprocess.CompletedProcess([sub], 1, "", "boom")
    monkeypatch.setattr(xb, "run", fake_run)
    out = xb.draft({"url": "https://x.com/fixture_user_54/status/1", "door": "EconLLM"})
    assert out["status"] == "error" and out["style_version"] is None and out["style_sha"] is None
    assert out["code"] == "style_missing"
    ok = tmp_path / "style_augusto.v2.md"; ok.write_text("v2")
    monkeypatch.setenv("MS_STYLE_FILE", str(ok))
    out = xb.draft({"url": "https://x.com/fixture_user_54/status/1", "door": "EconLLM"})
    assert out["style_version"] == "style_augusto.v2" and out["style_sha"] == hashlib.sha256(b"v2").hexdigest()


@pytest.mark.parametrize("url,text", [
    ("https://x.com/Fixture_User_91/status/1000000000000711", T_SCA),                       # own post URL, no author
    ("https://x.com/fixture_user_54/status/1000000000000712", T_SCA + " https://twitter.com/fixture_user_92/status/123"),  # linked
    ("https://x.com/fixture_user_54/status/1000000000000713", T_SCA + " x.com/fixture_user_91/status/9"),  # quoted, bare
])
def test_se_self_post_by_url(tmp_path, monkeypatch, url, text):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    app = create_app(str(tmp_path))
    g = FakeGrader({text: "claim"})
    app.state.api.fit_grader = g
    row = TestClient(app).post("/intake/x", json={"run_id": "discovery-u", "posts": [{"url": url, "text": text}]}).json()["posts"][0]
    assert row["status"] == "killed" and row["reasons"] == ["self_post"] and g.calls == []


def test_se_other_handles_not_self():
    from src.self_accounts import self_in_urls
    assert not self_in_urls("see https://x.com/fixture_user_91e/status/1 and https://x.com/fixture_user_60/status/2")
    assert not self_in_urls("https://x.com/fixture_user_91")      # profile link, not a status
