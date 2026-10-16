"""se_ POST /intake/x dry_run + 12:15 PT replay regression (Data Analyst's fixture, read-only)."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import core
from src.api.app import create_app
from tests.test_intake_contract import T_NOFIT, T_SCA

FIX = Path(__file__).parent / "fixtures" / "discovery_20261013_offtopic.json"


@pytest.fixture
def c(tmp_path):
    app = create_app(str(tmp_path))
    calls = []
    app.state.api.predrafter = lambda p, card: calls.append(1) or {"status": "ok", "draft_text": card["draft"]}
    app.state.calls = calls
    return TestClient(app)


def X(sid, text=T_SCA):
    return {"url": f"https://x.com/fixture_user_54/status/{sid}", "text": text, "reply_count": 4, "quote_count": 1}


def counts(tmp_path):
    with sqlite3.connect(tmp_path / "scouter.db") as d, sqlite3.connect(tmp_path / "handoffs.db") as h:
        return (d.execute("SELECT count(*) FROM cards").fetchone()[0],
                h.execute("SELECT count(*) FROM intake_posts").fetchone()[0])


def test_se_dry_run_writes_nothing(c, tmp_path):
    c.post("/intake/x", json={"run_id": "discovery-0", "posts": [X(1)]})
    before, st, ev = counts(tmp_path), c.get("/status").json(), len(c.get("/events").json())
    n_calls = len(c.app.state.calls)
    j = c.post("/intake/x", json={"run_id": "discovery-dry", "dry_run": True,
                                  "posts": [X(1), X(2), X(3, T_NOFIT), {"url": "https://example.com/x", "text": "hi"}]}).json()
    assert j["dry_run"] is True and j["predrafted"] == 0
    assert [p["status"] for p in j["posts"]] == ["duplicate", "queued", "killed", "refused"]
    assert j["posts"][1]["S"] > 0 and j["posts"][2]["reasons"] == ["empty_fit"]
    assert counts(tmp_path) == before and len(c.app.state.calls) == n_calls
    after = c.get("/status").json()
    assert after["queue_size"] == st["queue_size"] and after["x_last_checked"] == st["x_last_checked"]
    new = c.get("/events").json()[ev:]
    assert [e["kind"] for e in new] == ["intake_dry_run"] and new[0]["queued"] == 1
    real = c.post("/intake/x", json={"run_id": "discovery-1", "posts": [X(2)]}).json()
    assert real["dry_run"] is False and real["posts"][0]["status"] == "queued"


def test_se_dry_run_simulates_cap(c):
    j = c.post("/intake/x", json={"run_id": "d", "dry_run": True, "posts": [X(10 + i) for i in range(9)]}).json()
    assert j["counts"]["queued"] == 7 and j["counts"]["held"] == 2


@pytest.mark.parametrize("dry", [True, False])
def test_se_replay_1215_offtopic_regression(c, monkeypatch, dry):
    if not FIX.exists():
        pytest.skip("Data Analyst's 12:15 fixture missing")
    d = json.loads(FIX.read_text())
    monkeypatch.setattr(core, "_now", lambda: datetime(2026, 10, 13, 19, 35, 44, tzinfo=timezone.utc))
    keys = sorted(d["posts"], key=int)
    j = c.post("/intake/x", json={"run_id": d["run_id"], "dry_run": dry, "posts": [d["posts"][k] for k in keys]}).json()
    got = {k: (p["status"], p["reasons"]) for k, p in zip(keys, j["posts"])}
    for k in ("0", "1", "7", "8", "17"):  # queued/held at 12:15 under the keyword scorer
        assert got[k] == ("killed", ["empty_fit"]), (k, got[k])
    for k in ("20", "21"):  # made-up notes-bot rows (fixture_bot_01): killed earlier, as bot_author (data/bot_accounts.json, 2026-10-14)
        assert got[k] == ("killed", ["bot_author"]), (k, got[k])
    assert got["6"][0] == "queued"  # the genuine opening still queues
