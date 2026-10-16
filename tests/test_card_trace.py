"""Sprint Wed 4:46: trace page data. GET /cards/{id}/trace = post → grade → score → draft + events. Read-only."""
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.models import Outlet
from tests.test_fit_either_se import FakeGrader
from tests.test_intake_contract import T_SCA

URL = "https://x.com/fixture_user_60/status/1000000000000900"


def test_trace_has_post_grade_score_draft_and_events(tmp_path, monkeypatch):
    monkeypatch.delenv("MS_FIT_GRADED_MODE", raising=False)
    monkeypatch.setenv("MS_FIT_SHADOW", "1")
    app = create_app(str(tmp_path))
    api = app.state.api
    api.fit_grader, api.fit_shadow_sync = FakeGrader({T_SCA: "claim"}), True
    api.predrafter = lambda p, card: {"status": "ok", "draft_text": "On LLM synthetic participants, our pilots found real gaps.", "model": "fake"}
    c = TestClient(app)
    c.post("/intake/x", json={"run_id": "discovery-tr", "posts": [{"url": URL, "text": T_SCA, "author_handle": "someone", "reply_count": 4}]})
    card = api.store.open_cards(Outlet.X)[0]
    before = api.events_path.read_bytes()
    t = c.get(f"/cards/{card.card_id}/trace").json()
    assert api.events_path.read_bytes() == before                 # read-only: no event written
    assert t["source"]["url"] == URL and t["source"]["text"] == T_SCA and t["source"]["status_id"] == "1000000000000900"
    assert t["grade"]["asset_id"] == card.asset_id and t["grade"]["slugs"] == card.slugs and t["grade"]["claim"]
    assert t["grade"]["filter_source"] in ("word", "model")
    assert t["grade"]["shadow_level"] == "claim"                   # shadow grade from the cache, same asset
    assert t["score"]["S"] == card.S and set(t["score"]["factors"]) >= {"Fit", "Urgency", "EffortPenalty"}
    assert t["draft"]["model"] == "fake"
    kinds = [e["kind"] for e in t["events"]]
    assert "scored" in kinds and "decision" in kinds


def test_trace_unknown_card_404(tmp_path):
    r = TestClient(create_app(str(tmp_path))).get("/cards/card_nope/trace")
    assert r.status_code == 404 and r.json()["code"] == "unknown_card"
