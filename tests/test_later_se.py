"""Later (24h) is server-persisted; caps exclude Later; empty post_text never in Openings."""
from __future__ import annotations

import tempfile
from datetime import timedelta

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api import core as core_mod


SCA = "asset_sca_nonweird"
SNIP = dict(
    url="https://x.com/fixture_user_54/status/42",
    outlet="x",
    author="fixture_user_23",
    snippet="Are LLM synthetic participants just WEIRD? non-WEIRD cultural agent results",
)


def test_later_drops_from_openings_and_caps():
    with tempfile.TemporaryDirectory() as d:
        c = TestClient(create_app(d))
        r = c.post(f"/recommend?asset_id={SCA}", json=SNIP).json()
        assert r["ok"] and r["card"]
        cid = r["card"]["card_id"]
        assert r["card"]["post_text"]
        assert r["card"]["author"] == "@fixture_user_23"
        q = c.get("/queue").json()
        assert len(q["cards"]) == 1 and q["cap"]["x"] == "1/7"
        assert q.get("later") == []
        lr = c.post("/later", json={"card_id": cid})
        assert lr.status_code == 200
        assert "later_until" in lr.json()
        q2 = c.get("/queue").json()
        assert q2["cards"] == []
        assert len(q2["later"]) == 1
        assert q2["later"][0]["card_id"] == cid
        assert q2["cap"]["x"] == "0/7"  # caps don't count Later


def test_later_returns_after_24h(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        c = TestClient(create_app(d))
        cid = c.post(f"/recommend?asset_id={SCA}", json=SNIP).json()["card"]["card_id"]
        c.post("/later", json={"card_id": cid})
        assert c.get("/queue").json()["cards"] == []
        real_now = core_mod._now()
        monkeypatch.setattr(core_mod, "_now", lambda: real_now + timedelta(hours=25))
        q = c.get("/queue").json()
        assert len(q["cards"]) == 1 and q["cards"][0]["card_id"] == cid
        assert q.get("later") == []


def test_empty_post_text_not_in_openings():
    with tempfile.TemporaryDirectory() as d:
        c = TestClient(create_app(d))
        # enqueue normally then blank the stored snippet
        cid = c.post(f"/recommend?asset_id={SCA}", json=SNIP).json()["card"]["card_id"]
        from src.api.core import ScouterAPI
        api = ScouterAPI(d)
        card = api.store.get_card(cid)
        assert card
        card.title_or_snippet = "   "
        api.store.upsert_card(card)
        q = c.get("/queue").json()
        assert q["cards"] == []
        assert q["cap"]["x"] == "0/7"
