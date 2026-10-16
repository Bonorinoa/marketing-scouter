"""se_ length caps: intake kills > 10000 chars ('too_long'); grader input truncated to MS_FIT_MAX_POST_CHARS; 413 over 1MB."""
import json

from fastapi.testclient import TestClient

from src.api.app import create_app
from tests.test_fit_either_se import FakeGrader
from tests.test_intake_contract import T_SCA


def _client(tmp_path, g=None):
    app = create_app(str(tmp_path))
    app.state.api.fit_grader = g
    app.state.api.predrafter = lambda p, card: {"status": "ok", "draft_text": card["draft"]}
    return TestClient(app), app.state.api


def test_se_too_long_killed_before_grader(tmp_path, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    g = FakeGrader({})
    c, api = _client(tmp_path, g)
    row = c.post("/intake/x", json={"run_id": "discovery-l", "posts": [
        {"url": "https://x.com/fixture_user_54/status/1000000000000951", "text": T_SCA + " x" * 6000}]}).json()["posts"][0]
    assert row["status"] == "killed" and row["reasons"] == ["too_long"] and g.calls == []
    assert any(e["kind"] == "killed" and e.get("kill_reasons") == ["too_long"] for e in api.events())


def test_se_grader_input_truncated(tmp_path, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    monkeypatch.setenv("MS_FIT_MAX_POST_CHARS", "300")
    seen = []

    class G(FakeGrader):
        def __call__(self, text, claim):
            seen.append(len(text))
            return "none"
    c, api = _client(tmp_path, G({}))
    c.post("/intake/x", json={"run_id": "discovery-t", "posts": [
        {"url": "https://x.com/fixture_user_54/status/1000000000000952", "text": T_SCA + " words" * 1000}]})
    assert seen and max(seen) == 300


def test_se_request_body_413(tmp_path):
    c, api = _client(tmp_path)
    big = {"run_id": "x", "posts": [{"url": "https://x.com/fixture_user_54/status/1", "text": "a" * (1024 * 1024 + 10)}]}
    r = c.post("/intake/x", content=json.dumps(big), headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "request_too_large"
    assert any(e["kind"] == "request_too_large" for e in api.events())
    assert c.get("/status").status_code == 200
