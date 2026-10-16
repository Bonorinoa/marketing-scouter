"""da_ Wins-as-evidence: evidence_url, archive fallback, criterion_hint, hash chain, is_test."""
import json
import logging

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.core import ScouterAPI
from src.models import CriterionHint, ScoutEvent
from src.win_evidence import (CRITERION_HINTS, GENESIS, row_hash,
                              verify_chain, wayback_save_url)
from src.win_export import WIN_SHEET_COLUMNS, aggregate_wins
from tests.test_api_dor import X_WEIRD, card_and_handoff

EV = "https://x.com/fixture_user_64/status/123"


def _receipt(c, h, **kw):
    body = dict(handoff_id=h["payload"]["handoff_id"], seal=h["seal"],
                pause_checksum=h["payload"]["pause_checksum"], attested=True, attested_by="user",
                action="acted", win_type="claim_named_reply")
    body.update(kw)
    return c.post("/handoff/receipt", json=body)


@pytest.fixture
def c(tmp_path):
    return TestClient(create_app(str(tmp_path)))


def _rec_handoff(c, n):
    body = {**X_WEIRD, "url": f"https://x.com/fixture_user_54/status/{n}"}
    return card_and_handoff(c, body)[1]


def test_da_column_order_appends_evidence_fields():
    assert WIN_SHEET_COLUMNS[:8] == ["date", "slug", "outlet", "asset_id", "source_id", "win_type", "card_id", "note"]
    assert WIN_SHEET_COLUMNS[8:] == ["evidence_url", "archive_url", "criterion_hint", "is_test", "prev_hash", "row_hash"]


@pytest.mark.parametrize("bad,code", [(None, "evidence_url_required"), ("", "evidence_url_required"),
                                      ("ftp://x.com/fixture_user_54", "evidence_url_invalid"), ("not a url", "evidence_url_invalid"),
                                      ("http://localhost/x", "evidence_url_invalid")])
def test_da_evidence_url_required(c, bad, code):
    h = _rec_handoff(c, 1)
    r = _receipt(c, h, evidence_url=bad)
    assert r.status_code == 422 and r.json()["code"] == code and r.json()["message"]
    assert c.get("/wins").json() == []
    # handoff not consumed by the refusal: a corrected confirm still works
    assert _receipt(c, h, evidence_url=EV).status_code == 200


def test_da_archive_default_wayback_form_and_provided(c):
    r = _receipt(c, _rec_handoff(c, 1), evidence_url=EV).json()
    assert r["win"]["archive_url"] == wayback_save_url(EV) == "https://web.archive.org/save/" + EV
    r = _receipt(c, _rec_handoff(c, 2), evidence_url=EV,
                 archive_url="https://web.archive.org/web/2026/" + EV).json()
    assert r["archive_status"] == "provided" and r["win"]["archive_url"].startswith("https://web.archive.org/web/")


def test_da_archive_failure_still_records_win(tmp_path):
    class Boom:
        def archive(self, url):
            raise TimeoutError("wayback down")
    api = ScouterAPI(tmp_path, archiver=Boom())
    c = TestClient(create_app(str(tmp_path)))

    h = _rec_handoff(c, 1)
    out = api.receipt(handoff_id=h["payload"]["handoff_id"], seal=h["seal"],
                      pause_checksum=h["payload"]["pause_checksum"], attested=True, attested_by="user",
                      action="acted", win_type="warm_intro", evidence_url=EV)
    assert out["win"] and out["win"]["archive_url"] is None and out["archive_status"] == "failed"
    assert "couldn't be archived" in out["archive_message"]
    assert api.wins_verify()["ok"]


def test_da_criterion_hint_enum(c):
    assert CRITERION_HINTS == tuple(h.value for h in CriterionHint)
    r = _receipt(c, _rec_handoff(c, 1), evidence_url=EV, criterion_hint="original_contributions")
    assert r.status_code == 422 and r.json()["code"] == "bad_criterion_hint"
    # no hint sent → default by Win type from data/criterion_hints.json
    assert _receipt(c, _rec_handoff(c, 2), evidence_url=EV).json()["win"]["criterion_hint"] == "original_contribution"
    assert _receipt(c, _rec_handoff(c, 4), evidence_url=EV, win_type="warm_intro").json()["win"]["criterion_hint"] == "none"
    w = _receipt(c, _rec_handoff(c, 3), evidence_url=EV, criterion_hint="scholarly_authorship").json()["win"]
    assert w["criterion_hint"] == "scholarly_authorship"
    with pytest.raises(Exception):
        ScoutEvent(kind="win", criterion_hint="awards")


def test_da_chain_verify_and_tamper_detection(c, tmp_path):
    for n in range(3):
        _receipt(c, _rec_handoff(c, n), evidence_url=EV)
    wins = c.get("/wins").json()
    assert wins[0]["prev_hash"] == GENESIS
    assert [w["prev_hash"] for w in wins[1:]] == [w["row_hash"] for w in wins[:-1]]
    assert all(row_hash(w) == w["row_hash"] for w in wins)
    v = c.get("/wins/verify").json()
    assert v["ok"] and v["count"] == 3 and v["head"] == wins[-1]["row_hash"] == c.get("/wins/head").json()["head"]
    # tamper: edit one note in the log on disk
    p = tmp_path / "api_events.jsonl"
    lines = p.read_text().splitlines()
    i = next(k for k, l in enumerate(lines) if json.loads(l)["kind"] == "win")
    ev = json.loads(lines[i]); ev["note"] = "edited later"; lines[i] = json.dumps(ev)
    p.write_text("\n".join(lines) + "\n")
    v = c.get("/wins/verify").json()
    assert not v["ok"] and v["index"] == 0 and v["reason"] == "row_hash_mismatch"
    # deleting a row breaks the link too
    assert not verify_chain([wins[0], wins[2]])["ok"]


def test_da_head_genesis_when_empty(c):
    assert c.get("/wins/head").json() == {"head": GENESIS}


def test_da_test_handoffs_never_win_and_excluded(c, tmp_path):
    h = _rec_handoff(c, 1)
    (tmp_path / "test_handoffs.json").write_text(json.dumps({"handoff_ids": [h["payload"]["handoff_id"]]}))
    r = _receipt(c, h, evidence_url=EV)
    assert r.status_code == 409 and r.json()["code"] == "test_handoff_no_win"
    assert c.get("/wins?include_test=true").json() == []
    assert _receipt(c, h, action="skipped", win_type=None).status_code == 200  # skipping is fine


def test_da_is_test_rows_excluded_from_export_by_default(monkeypatch, c):
    monkeypatch.setenv("MS_TEST_MODE", "1")
    rows = aggregate_wins([
        {"kind": "win", "ts": "2026-10-09", "wins": ["warm_intro"], "card_id": "a", "is_test": True},
        {"kind": "win", "ts": "2026-10-09", "wins": ["warm_intro"], "card_id": "b", "evidence_url": EV},
    ])
    assert [r["card_id"] for r in rows] == ["b"] and rows[0]["is_test"] is False
    assert len(aggregate_wins([{"kind": "win", "ts": "2026-10-09", "wins": ["warm_intro"], "is_test": True}],
                              include_test=True)) == 1


def test_da_test_mode_fixture_wins_flagged(monkeypatch, tmp_path):
    monkeypatch.setenv("MS_TEST_MODE", "1")
    c = TestClient(create_app(str(tmp_path)))
    r = _receipt(c, _rec_handoff(c, 1), evidence_url=EV)
    assert r.status_code == 409 and c.get("/wins").json() == []


def test_da_no_double_win_for_one_handoff(c):
    h = _rec_handoff(c, 1)
    assert _receipt(c, h, evidence_url=EV).status_code == 200
    r = _receipt(c, h, evidence_url=EV, win_type="warm_intro")
    assert r.status_code == 409 and r.json()["code"] == "already_received"
    assert len(c.get("/wins?include_test=true").json()) == 1


def test_da_criterion_hints_match_researcher_file():
    import json
    from pathlib import Path
    from src.models import WinSignal
    d = json.loads((Path(__file__).resolve().parents[1] / "data" / "criterion_hints.json").read_text())
    assert list(CRITERION_HINTS) == list(d["values"]) == [h.value for h in CriterionHint]
    assert set(CRITERION_HINTS) == {"original_contribution", "published_about", "scholarly_authorship", "judging", "none"}
    assert set(d["default_by_win_type"]) == {w.value for w in WinSignal}
    assert set(d["default_by_win_type"].values()) <= set(CRITERION_HINTS)
    from src.api.core import WIN_TYPES
    assert set(d["default_by_win_type"]) == set(WIN_TYPES)
