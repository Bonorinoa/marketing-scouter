"""Sprint Wed 4:46: promo_cta graded-claim log. In shadow mode the grader also sees posts the promo-word
rule killed; each is logged (append-only) with its graded level. The kill itself never changes."""
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.models import Outlet
from tests.test_fit_either_se import FakeGrader
from tests.test_intake_contract import T_SCA

PROMO = T_SCA + " Book a demo today."


def test_promo_cta_kill_logged_with_grade_and_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv("MS_FIT_GRADED_MODE", raising=False)
    monkeypatch.setenv("MS_FIT_SHADOW", "1")
    app = create_app(str(tmp_path))
    api = app.state.api
    api.fit_grader, api.fit_shadow_sync = FakeGrader({PROMO: "claim", T_SCA: "claim"}), True
    api.predrafter = lambda p, card: {"status": "ok", "draft_text": card["draft"]}
    c = TestClient(app)
    rows = c.post("/intake/x", json={"run_id": "discovery-promo", "posts": [
        {"url": "https://x.com/fixture_user_67/status/1000000000000950", "text": PROMO, "author_handle": "vendor"},
        {"url": "https://x.com/fixture_user_60/status/1000000000000951", "text": T_SCA, "author_handle": "someone"}]}).json()["posts"]
    assert rows[0]["status"] == "killed" and "promo_cta" in rows[0]["reasons"]       # kill unchanged
    assert all(c_.url.endswith("951") for c_ in api.store.open_cards(Outlet.X))
    log = c.get("/fit/promo-cta-graded").json()
    assert log["n"] == 1 and log["n_claim"] == 1
    r = log["rows"][0]
    assert r["status_id"] == "1000000000000950" and r["graded_best_level"] == "claim"
    assert r["scout_run_id"] == "discovery-promo" and "promo_cta" in r["word_status"]["reasons"]
    ev = [e for e in api.events() if e["kind"] == "fit_shadow"][-1]
    assert ev["n_promo_cta_graded"] == 1 and ev["n_promo_cta_graded_claim"] == 1
    # append-only: a second run adds, never rewrites
    before = (tmp_path / "promo_cta_graded.jsonl").read_bytes()
    c.post("/intake/x", json={"run_id": "discovery-promo2", "posts": [
        {"url": "https://x.com/fixture_user_67/status/1000000000000952", "text": PROMO + " ", "author_handle": "vendor"}]})
    after = (tmp_path / "promo_cta_graded.jsonl").read_bytes()
    assert after.startswith(before) and len(after) > len(before)


def test_promo_log_empty_without_shadow(tmp_path, monkeypatch):
    monkeypatch.delenv("MS_FIT_SHADOW", raising=False)
    c = TestClient(create_app(str(tmp_path)))
    assert c.get("/fit/promo-cta-graded").json() == {"n": 0, "n_claim": 0, "rows": []}
