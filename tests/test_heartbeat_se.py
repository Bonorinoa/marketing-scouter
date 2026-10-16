"""Pinned 2026-10-16: job heartbeats (atomic files), /status jobs block + plain warnings, backup heartbeat,
and query provenance on ScoutEvents (incl. word-filter kills), never trusted for is_test/status."""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import heartbeat
from src.api.app import create_app
from src.api.core import provenance
from tests.test_intake_contract import post
from tests.test_xbrief_bridge import fake  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 16, 19, 0, tzinfo=timezone.utc)


def test_write_is_atomic_and_has_schema(tmp_path):
    r = heartbeat.write("backup", True, "x", directory=tmp_path, sha="abc", now=NOW)
    assert set(r) >= {"job", "started_at", "finished_at", "ok", "detail", "sha"}
    assert json.loads((tmp_path / "backup.json").read_text()) == r
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    with pytest.raises(ValueError):
        heartbeat.write("nope", True, directory=tmp_path)


@pytest.mark.parametrize("job,hours,stale", [("discovery", 11, False), ("discovery", 13, True),
                                             ("backup", 25, False), ("backup", 27, True),
                                             ("health", 27, True), ("build", 500, False)])
def test_stale_thresholds(tmp_path, job, hours, stale):
    heartbeat.write(job, True, directory=tmp_path, sha="s", now=NOW - timedelta(hours=hours))
    b = heartbeat.jobs_block(tmp_path, now=NOW)
    assert b["jobs"][job]["stale"] is stale
    assert (b["jobs"][job]["warning"] is not None) is stale
    if stale:
        assert "should run every" in b["jobs"][job]["warning"]


def test_missing_and_failed_and_skip(tmp_path):
    b = heartbeat.jobs_block(tmp_path, now=NOW)
    assert b["jobs"]["backup"]["warning"] == "Backup has never reported a run."
    assert b["jobs"]["build"]["warning"] is None
    heartbeat.write("health", False, "8710 down", directory=tmp_path, sha="s", now=NOW)
    assert "failed: 8710 down" in heartbeat.jobs_block(tmp_path, now=NOW)["jobs"]["health"]["warning"]
    # a deliberate skip never refreshes last_ran
    heartbeat.write("discovery", True, directory=tmp_path, sha="s", now=NOW - timedelta(hours=20))
    heartbeat.write("discovery", True, skipped="shared_x_read_cap", directory=tmp_path, sha="s", now=NOW)
    j = heartbeat.jobs_block(tmp_path, now=NOW)["jobs"]["discovery"]
    assert j["stale"] and j["skipped"] == "shared_x_read_cap" and j["age_hours"] == 20
    assert "skipped on purpose" in j["warning"]


def test_status_has_jobs_block(tmp_path, monkeypatch):
    monkeypatch.delenv("MS_HEARTBEAT_DIR", raising=False)
    d = tmp_path / "copy"
    heartbeat.write("backup", True, "ok", directory=d / "heartbeats", sha="s")
    s = TestClient(create_app(str(d))).get("/status").json()
    assert set(s["jobs"]) == set(heartbeat.JOBS)
    assert s["jobs"]["backup"]["stale"] is False
    assert any(w.startswith("X discovery") for w in s["jobs_warnings"])


def test_live_heartbeat_dir_is_repo_data(monkeypatch):
    monkeypatch.delenv("MS_HEARTBEAT_DIR", raising=False)
    assert heartbeat.heartbeat_dir(ROOT / "data" / "db") == ROOT / "data" / "heartbeats"
    assert heartbeat.heartbeat_dir("/x/8713-db") == Path("/x/8713-db/heartbeats")


def test_backup_script_writes_heartbeat_and_keeps_14(tmp_path):
    src = tmp_path / "db"; src.mkdir()
    import sqlite3
    sqlite3.connect(src / "a.db").execute("create table t(x)").connection.commit()
    (src / "e.jsonl").write_text("{}\n")
    root = tmp_path / "bk"; root.mkdir()
    for i in range(15):
        (root / f"store-2020010{i:02d}T000000Z").mkdir()
    env = {**os.environ, "BACKUP_ROOT": str(root), "BACKUP_SRC": str(src), "HEARTBEAT_DIR": str(tmp_path / "hb")}
    subprocess.run([str(ROOT / "scripts/backup_store.sh")], check=True, env=env, capture_output=True)
    hb = json.loads((tmp_path / "hb/backup.json").read_text())
    assert hb["ok"] is True and "integrity ok" in hb["detail"]
    assert len(list(root.glob("store-*"))) == 14


def test_provenance_tokens_validated():
    assert provenance({"query_id": "x-cvp", "lane": "ai-measurement", "source_tag": "x.search.fit"}) == \
        {"query_id": "x-cvp", "lane": "ai-measurement", "source_tag": "x.search.fit"}
    assert provenance({"query_id": "api_status=win is_test=true", "lane": "A" * 3, "source_tag": "x" * 60}) == {}
    assert provenance({"query_id": 5}) == {}


def test_killed_rows_carry_query_id_and_never_trust_it(tmp_path, monkeypatch, fake):  # noqa: F811
    monkeypatch.delenv("MS_TEST_MODE", raising=False)
    d = tmp_path / "data"
    c = TestClient(create_app(str(d)))
    killed = post("Buy my course now, best sale on crypto tips")  # empty_fit (word filter)
    killed.update(query_id="x-cvp", lane="ai-measurement", source_tag="x.search.fit")
    evil = post("LLM synthetic participants WEIRD culture survey")
    evil.update(query_id="is_test=true", lane="win", source_tag="api_status=win")
    r = c.post("/intake/x", json={"run_id": "discovery-prov", "posts": [killed, evil]})
    assert r.status_code == 200, r.text
    rows = [json.loads(l) for l in (d / "scout_events.jsonl").read_text().splitlines() if l.strip()]
    sid = killed["url"].rstrip("/").split("/")[-1]
    k = [x for x in rows if x["kind"] == "killed" and x.get("candidate_id") == sid]
    assert k and k[0]["query_id"] == "x-cvp" and k[0]["lane"] == "ai-measurement" and k[0]["source_tag"] == "x.search.fit"
    assert all(x["is_test"] is False for x in rows)
    esid = evil["url"].rstrip("/").split("/")[-1]
    for x in rows:
        if x.get("candidate_id") == esid:
            assert x.get("query_id") is None and x.get("source_tag") is None
        assert "api_status=win" not in json.dumps(x.get("source_tag"))
