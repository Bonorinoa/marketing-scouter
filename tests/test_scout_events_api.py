"""Pinned 2026-10-14: API discovery / human / Win writes go to <data_dir>/scout_events.jsonl via src/events.py,
append-only, pipeline ScoutEvent schema; existing bytes are never rewritten."""
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.models import ScoutEvent
from tests.test_api_dor import card_and_handoff, receipt
from tests.test_intake_contract import intake, post
from tests.test_xbrief_bridge import fake  # noqa: F401

LIVE = Path(__file__).resolve().parents[1] / "data" / "db" / "scout_events.jsonl"
PREFIX = (b'{"scout_run_id": "run_8c5f02e953d7", "ts": "2026-09-26T01:50:13.801145Z", "kind": "discovered", '
          b'"candidate_id": "cand_efd7c0c57c6d", "note": "https://x.com/fixture_user_68/status/9000000000000000901"}\n')


def _rows(p):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def test_discovery_appends_pipeline_schema_and_keeps_prefix(tmp_path, fake):  # noqa: F811
    d = tmp_path / "data"
    d.mkdir()
    (d / "scout_events.jsonl").write_bytes(PREFIX)
    before = hashlib.sha256(PREFIX).hexdigest()
    c = TestClient(create_app(str(d)))
    intake(c, [post(), post("Big Five measurement on LLMs: which prompt version is valid? empty finding")],
           run_id="run_pin")
    raw = (d / "scout_events.jsonl").read_bytes()
    assert raw.startswith(PREFIX) and hashlib.sha256(raw[:len(PREFIX)]).hexdigest() == before
    new = _rows(d / "scout_events.jsonl")[1:]
    kinds = [r["kind"] for r in new]
    assert kinds.count("discovered") == 2 and "scored" in kinds and "decision" in kinds
    for r in new:   # one reader handles both: every row parses as the pipeline model
        ScoutEvent.model_validate(r)
        assert r["scout_run_id"] == "run_pin"
    assert not any(k in r for r in new for k in ("dropped_assets", "kept_card_id"))   # schema only


def test_human_and_win_appended(tmp_path):
    d = tmp_path / "data"
    c = TestClient(create_app(str(d)))
    _, h = card_and_handoff(c)
    assert receipt(c, h, win_type="claim_named_reply").status_code == 200
    rows = _rows(d / "scout_events.jsonl")
    assert any(r["kind"] == "human" for r in rows)
    win = [r for r in rows if r["kind"] == "win"]
    assert len(win) == 1 and win[0]["wins"] == ["claim_named_reply"] and win[0].get("row_hash")
    for r in rows:
        ScoutEvent.model_validate(r)


def test_events_never_go_to_repo_default_when_data_dir_set(tmp_path, fake):  # noqa: F811
    before = LIVE.read_bytes() if LIVE.exists() else None
    c = TestClient(create_app(str(tmp_path / "d")))
    intake(c, [post()], run_id="run_iso")
    assert (LIVE.read_bytes() if LIVE.exists() else None) == before
    assert (tmp_path / "d" / "scout_events.jsonl").stat().st_size > 0


LIVE_SHA = "6540612f5750dc30cdcba189b3f806abf3345400d4c12620af016262167d66cb"


def test_live_34_rows_on_a_copy_keep_their_hash(tmp_path, fake):  # noqa: F811
    import pytest
    if not LIVE.exists() or hashlib.sha256(LIVE.read_bytes()[:7492]).hexdigest() != LIVE_SHA:
        pytest.skip("live 34-row file not present here")
    old = LIVE.read_bytes()[:7492]
    d = tmp_path / "copy"
    d.mkdir()
    (d / "scout_events.jsonl").write_bytes(old)   # a COPY; the live file is never opened for writing
    intake(TestClient(create_app(str(d))), [post()], run_id="run_copy")
    raw = (d / "scout_events.jsonl").read_bytes()
    assert hashlib.sha256(raw[:len(old)]).hexdigest() == LIVE_SHA and len(raw) > len(old)
