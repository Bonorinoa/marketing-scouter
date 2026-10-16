"""se_ archive_pre_redesign: archived, never deleted; out of queue/cap/replace; handoffs refuse Wins."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from scripts.archive_pre_redesign import main as archive_main
from src.api.app import create_app
from tests.test_api_dor import X_WEIRD, card_and_handoff
from tests.test_intake_contract import T_SCA

A = "archived_pre_redesign"


@pytest.fixture
def c(tmp_path):
    app = create_app(str(tmp_path))
    app.state.api.predrafter = lambda p, card: {"status": "ok", "draft_text": card["draft"]}
    return TestClient(app)


def X(sid, text=T_SCA):
    return {"url": f"https://x.com/fixture_user_54/status/{sid}", "text": text, "reply_count": 4, "quote_count": 1}


def test_se_archive_keeps_rows_and_refuses(c, tmp_path):
    api = c.app.state.api
    card, h = card_and_handoff(c)
    c.post("/intake/x", json={"run_id": "discovery-0", "posts": [X(10 + i) for i in range(7)]})
    assert c.get("/status").json()["queue_size"] == 7
    head = c.get("/wins/head").json()
    out = archive_main(["--data-dir", str(tmp_path)])
    assert out["handoffs"] == 1 and out["cards"] == 7
    again = archive_main(["--data-dir", str(tmp_path)])  # idempotent
    assert again["cards"] == again["handoffs"] == 0 and again["already"] >= 8
    with sqlite3.connect(tmp_path / "scouter.db") as d:
        assert d.execute("SELECT count(*) FROM cards WHERE state=?", (A,)).fetchone()[0] == 7
    log = {(r["kind"], r["item_id"]): r["prior_status"] for r in api.archive_log()}
    assert log[("handoff", h["payload"]["handoff_id"])] == "sealed"
    assert log[("card", card["card_id"])] == "awaiting_approval"
    assert c.get("/wins/head").json() == head and c.get("/wins/verify").json()["ok"]
    assert c.get("/queue").json()["cards"] == [] and c.get("/status").json()["queue_size"] == 0
    assert any(e["kind"] == "archive_pre_redesign" for e in c.get("/events").json())
    hid = h["payload"]["handoff_id"]
    r = c.post("/handoff/receipt", json=dict(handoff_id=hid, seal=h["seal"],
               pause_checksum=h["payload"]["pause_checksum"], attested=True, attested_by="user",
               action="acted", win_type="claim_named_reply", evidence_url="https://x.com/fixture_user_61/status/5"))
    assert r.status_code == 409 and r.json()["code"] == "archived_handoff"
    assert c.post(f"/handoff/{hid}/draft").json()["code"] == "archived_handoff"
    assert c.get("/wins?include_test=true").json() == []
    assert [x["payload"]["handoff_id"] for x in c.get(f"/handoff?status={A}").json()] == [hid]


def test_se_archived_out_of_cap_and_reintake(c, tmp_path):
    c.post("/intake/x", json={"run_id": "discovery-0", "posts": [X(100 + i) for i in range(7)]})
    archive_main(["--data-dir", str(tmp_path)])
    j = c.post("/intake/x", json={"run_id": "discovery-1",
                                  "posts": [X(100)] + [X(200 + i) for i in range(6)]}).json()
    assert [p["status"] for p in j["posts"]] == ["queued"] * 7  # archived never fills the 7, never replaced
    assert c.get("/status").json()["queue_size"] == 7
    again = c.post("/intake/x", json={"run_id": "discovery-2", "posts": [X(100)]}).json()
    assert again["posts"][0]["status"] == "duplicate"  # new card is live → duplicate again


def test_se_archived_enum_in_openapi(c):
    spec = c.get("/openapi.json").json()
    params = spec["paths"]["/handoff"]["get"]["parameters"]
    assert A in str(params)
    assert "archived_handoff" in spec["paths"]["/handoff/receipt"]["post"]["responses"]["409"]["description"]


def test_se_archive_cards_offtopic_label(c, tmp_path):
    from scripts.archive_cards import main as cards_main
    api = c.app.state.api
    card, h = card_and_handoff(c)  # awaiting_approval card + sealed handoff
    c.post("/intake/x", json={"run_id": "discovery-0", "posts": [X(300 + i) for i in range(6)]})
    runs_before = [e for e in c.get("/events").json() if e["kind"] == "intake_run"]
    out = cards_main(["--data-dir", str(tmp_path), "--label", "archived_offtopic_1215", "--states", "open"])
    assert out["cards"] == 6 and card["card_id"] not in out["card_ids"]
    assert cards_main(["--data-dir", str(tmp_path), "--label", "archived_offtopic_1215", "--states", "open"])["cards"] == 0
    assert c.get("/status").json()["queue_size"] == 1  # only the handed-off card
    log = [r for r in api.archive_log() if r["label"] == "archived_offtopic_1215"]
    assert len(log) == 6 and {r["prior_status"] for r in log} == {"open"}
    assert [e for e in c.get("/events").json() if e["kind"] == "intake_run"] == runs_before
    assert c.get(f"/handoff?status=sealed").json()  # handoffs untouched
    # handoff on an archived card → 409; re-intake allowed; cap ignores archived
    aid = out["card_ids"][0]
    r = c.post("/handoff", json={"card_id": aid})
    assert r.status_code == 409 and r.json()["code"] == "archived_card"
    j = c.post("/intake/x", json={"run_id": "discovery-1", "posts": [X(300)] + [X(400 + i) for i in range(5)]}).json()
    assert [p["status"] for p in j["posts"]] == ["queued"] * 6
    # archive the handed-off card → its sealed handoff refuses receipt + draft
    cards_main(["--data-dir", str(tmp_path), "--label", "archived_offtopic_1215", "--states", "awaiting_approval"])
    hid = h["payload"]["handoff_id"]
    r = c.post("/handoff/receipt", json=dict(handoff_id=hid, seal=h["seal"], pause_checksum=h["payload"]["pause_checksum"],
               attested=True, attested_by="user", action="acted", win_type="claim_named_reply",
               evidence_url="https://x.com/fixture_user_61/status/5"))
    assert r.status_code == 409 and r.json()["code"] == "archived_handoff"
    assert c.post(f"/handoff/{hid}/draft").json()["code"] == "archived_handoff"
    assert c.get("/wins/verify").json()["count"] == 0
    assert "archived_offtopic_1215" in c.get("/card-states").json()["archived"]


def test_se_archive_cards_rejects_unknown_label(tmp_path):
    from scripts.archive_cards import main as cards_main
    with pytest.raises(ValueError):
        cards_main(["--data-dir", str(tmp_path), "--label", "open", "--states", "open"])
