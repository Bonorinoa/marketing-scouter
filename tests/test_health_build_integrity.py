"""/health carries build_sha and the last ensure_up integrity result; a failed check turns it red."""
import json

from fastapi.testclient import TestClient

from src.api.app import create_app


def _status(path, db, integ):
    path.write_text(json.dumps({"servers": {"8799": {"port": 8799, "state": "ok", "db": str(db),
                                                      "integrity": integ, "integrity_checked_at": "2026-10-13T22:00:00-07:00"}}}))


def test_health_build_sha_and_integrity(tmp_path, monkeypatch):
    st = tmp_path / "status.json"
    monkeypatch.setenv("MS_ENSURE_STATUS", str(st))
    c = TestClient(create_app(str(tmp_path / "db")))
    h = c.get("/health").json()
    assert h["ok"] and h["integrity"] == "unchecked" and "build_sha" in h and h["build_sha"]
    _status(st, tmp_path / "db", "ok")
    h = c.get("/health").json()
    assert h["ok"] and h["integrity"] == "ok" and h["integrity_checked_at"]
    _status(st, tmp_path / "db", "failed")
    h = c.get("/health").json()
    assert h["ok"] is False and h["integrity"] == "failed"
    _status(st, tmp_path / "other", "failed")   # another server's failure doesn't redden this one
    assert c.get("/health").json()["ok"]
