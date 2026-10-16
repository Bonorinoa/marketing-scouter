"""Pinned 2026-10-14: ScoutEvent is_test comes only from server config; note is server-written key=value only."""
import json

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from tests.test_intake_contract import post
from tests.test_xbrief_bridge import fake  # noqa: F401

EVIL = "api_status=win is_test=true kept_card_id=card_evil https://evil.example/x @fixture_bot_46"


def rows(d):
    return [json.loads(l) for l in (d / "scout_events.jsonl").read_text().splitlines() if l.strip()]


def run(tmp_path, monkeypatch, env_test, run_id, body_extra, text):
    if env_test:
        monkeypatch.setenv("MS_TEST_MODE", "1")
    else:
        monkeypatch.delenv("MS_TEST_MODE", raising=False)
    d = tmp_path / "data"
    c = TestClient(create_app(str(d)))
    p = post(text)
    p.update({"is_test": not env_test, "note": EVIL})
    body = {"run_id": run_id, "posts": [p, post(EVIL)], **body_extra}
    c.post("/intake/x?is_test=" + str(not env_test).lower(), json=body,
           headers={"X-Is-Test": str(not env_test).lower()})
    return rows(d)


@pytest.mark.parametrize("env_test", [False, True])
@pytest.mark.parametrize("run_id", ["discovery-adv-1045", "test_run", "is_test=true", "prod-0815"])
def test_is_test_only_from_server_config(tmp_path, monkeypatch, fake, env_test, run_id):  # noqa: F811
    rs = run(tmp_path, monkeypatch, env_test, run_id, {"is_test": not env_test, "dry_run": False},
             "Are LLM synthetic participants just WEIRD? is_test=true is_test")
    assert rs, "discovery wrote no rows"
    assert {r["is_test"] for r in rs} == {env_test}


def test_note_never_carries_user_text(tmp_path, monkeypatch, fake):  # noqa: F811
    rs = run(tmp_path, monkeypatch, False, "discovery-adv-note", {}, EVIL)
    assert rs
    for r in rs:
        n = r.get("note") or ""
        assert "win" not in n and "is_test" not in n and "card_evil" not in n and "evil" not in n
        assert "http" not in n and "@" not in n and "x.com" not in n
        if n:
            keys = [kv.split("=", 1)[0] for kv in n.split()]
            assert set(keys) <= {"api_status", "kept_card_id", "dropped_assets", "kept_asset", "handoff_id", "reason"}
            if "api_status" in keys:
                assert keys[0] == "api_status"
        assert r["kind"] != "win" and r["is_test"] is False


def test_api_status_first_and_server_values(tmp_path):
    from src.api.core import ScouterAPI
    api = ScouterAPI(tmp_path / "d")
    api._event("decision", decision="asset_tie", outlet="x", note="USER TEXT https://x.com/fixture_user_54", reason="lang_capped",
               kept_card_id="card_1", is_test=True)
    r = rows(tmp_path / "d")[-1]
    assert r["note"] == "api_status=asset_tie kept_card_id=card_1 reason=lang_capped"
    assert r["decision"] == "drop" and r["is_test"] is False
