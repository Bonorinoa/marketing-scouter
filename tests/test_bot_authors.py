"""Designer P1 #4 (Wed 4:46): discovery skips bot authors (e.g. @grok auto-replies) and targets
the thread's original post instead. Bots are data/bot_accounts.json, separate from self_accounts."""
import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.bot_accounts import bot_accounts, is_bot_post, original_target, redirect_bot
from src.models import Outlet
from tests.test_fit_either_se import FakeGrader
from tests.test_intake_contract import T_SCA

GROK_URL = "https://x.com/grok/status/1000000000000801"
ROOT_URL = "https://x.com/fixture_user_60/status/1000000000000800"


def _app(tmp_path, monkeypatch):
    monkeypatch.delenv("MS_FIT_GRADED_MODE", raising=False)
    monkeypatch.setenv("MS_FIT_SHADOW", "1")
    app = create_app(str(tmp_path))
    api = app.state.api
    g = FakeGrader({T_SCA: "claim"})
    api.fit_grader, api.fit_shadow_sync = g, True
    api.predrafter = lambda p, card: {"status": "ok", "draft_text": card["draft"], "seen_text": p.get("text")}
    return TestClient(app), api, g


def test_bot_file_has_grok_and_is_not_self():
    acc = bot_accounts()
    assert "grok" in acc
    assert not ({"fixture_user_91", "fixture_user_92"} & acc)
    assert is_bot_post({"author_handle": "@Grok", "url": "https://x.com/fixture_user_54/status/1"})
    assert is_bot_post({"url": GROK_URL})                      # handle from the status URL alone
    assert not is_bot_post({"author_handle": "someone", "url": ROOT_URL})


def test_original_target_from_conversation_or_reply_id():
    assert original_target({"url": GROK_URL, "conversation_id": "1000000000000800"}) == \
        "https://x.com/i/status/1000000000000800"
    assert original_target({"url": GROK_URL, "in_reply_to_status_id": "1000000000000799"}) == \
        "https://x.com/i/status/1000000000000799"
    assert original_target({"url": GROK_URL, "conversation_id": "1000000000000801"}) is None  # own id: no target
    assert original_target({"url": GROK_URL, "conversation_id": "not-an-id"}) is None
    assert redirect_bot({"url": ROOT_URL, "author_handle": "someone"}) == {"bot": False}


def test_bot_post_killed_with_target_no_grader_no_card(tmp_path, monkeypatch):
    c, api, g = _app(tmp_path, monkeypatch)
    rows = c.post("/intake/x", json={"run_id": "discovery-bot", "posts": [
        {"url": GROK_URL, "text": T_SCA, "author_handle": "grok", "conversation_id": "1000000000000800"}]}).json()["posts"]
    assert rows[0]["status"] == "killed" and rows[0]["reasons"] == ["bot_author"]
    assert rows[0]["target_url"] == "https://x.com/i/status/1000000000000800"
    assert g.calls == [] and not api.store.open_cards(Outlet.X)
    assert any(e["kind"] == "killed" and e.get("kill_reasons") == ["bot_author"] for e in api.events())


def test_bot_post_with_thread_root_scores_the_original(tmp_path, monkeypatch):
    c, api, _g = _app(tmp_path, monkeypatch)
    rows = c.post("/intake/x", json={"run_id": "discovery-bot2", "posts": [
        {"url": GROK_URL, "text": "@fixture_user_40 Yes, here's a summary.", "author_handle": "grok",
         "thread_root": {"url": ROOT_URL, "text": T_SCA, "author_handle": "someone", "reply_count": 4}}]}).json()["posts"]
    r = rows[0]
    assert r["url"] == ROOT_URL and r["status_id"] == "1000000000000800"
    assert r["redirected_from"] == GROK_URL
    assert r["status"] == "queued", r
    cards = api.store.open_cards(Outlet.X)
    assert len(cards) == 1 and cards[0].url == ROOT_URL and (cards[0].author or "").lstrip("@") == "someone"
    assert cards[0].title_or_snippet == T_SCA                    # card is about the original, not the bot text
    assert any(e["kind"] == "bot_redirect" for e in api.events())


def test_bot_root_that_is_a_bot_or_self_never_cards(tmp_path, monkeypatch):
    c, api, g = _app(tmp_path, monkeypatch)
    rows = c.post("/intake/x", json={"run_id": "discovery-bot3", "posts": [
        {"url": GROK_URL, "text": T_SCA, "author_handle": "grok",
         "thread_root": {"url": "https://x.com/fixture_bot_02/status/1000000000000810", "text": T_SCA}},
        {"url": "https://x.com/grok/status/1000000000000812", "text": T_SCA, "author_handle": "grok",
         "thread_root": {"url": "https://x.com/fixture_user_91/status/1000000000000811", "text": T_SCA,
                         "author_handle": "fixture_user_91"}}]}).json()["posts"]
    assert rows[0]["status"] == "killed" and rows[0]["reasons"] == ["bot_author"]
    assert rows[1]["status"] == "killed" and rows[1]["reasons"] == ["self_post"]
    assert g.calls == [] and not api.store.open_cards(Outlet.X)


@pytest.mark.parametrize("handle", ["someone", "grok_fan", "notgrok"])
def test_human_posts_mentioning_grok_still_score(tmp_path, monkeypatch, handle):
    c, api, _g = _app(tmp_path, monkeypatch)
    rows = c.post("/intake/x", json={"run_id": "discovery-h", "posts": [
        {"url": f"https://x.com/{handle}/status/1000000000000820", "text": "@grok " + T_SCA,
         "author_handle": handle}]}).json()["posts"]
    assert rows[0]["reasons"] != ["bot_author"] and rows[0]["status"] in ("queued", "held")


def test_existing_bot_cards_hidden_from_openings_and_cap_not_deleted(tmp_path, monkeypatch):
    """Cards made from @grok posts before this fix stay in the store (never deleted) but leave Openings."""
    from src.models import ScoredCard, VoiceDoor
    c, api, _g = _app(tmp_path, monkeypatch)
    c.post("/intake/x", json={"run_id": "discovery-h2", "posts": [
        {"url": ROOT_URL, "text": T_SCA, "author_handle": "someone", "reply_count": 4}]})
    human = api.store.open_cards(Outlet.X)[0]
    bot = ScoredCard(**{**human.model_dump(), "card_id": "card_botold", "url": GROK_URL, "author": "@grok"})
    api.store.upsert_card(bot)
    q = c.get("/queue").json()
    ids = [x["card_id"] for x in q["cards"]]
    assert human.card_id in ids and "card_botold" not in ids
    assert q["cap"]["x"] == "1/7"
    assert api.store.get_card("card_botold") is not None


def test_status_queue_size_skips_bot_cards(tmp_path, monkeypatch):
    from src.models import ScoredCard
    c, api, _g = _app(tmp_path, monkeypatch)
    c.post("/intake/x", json={"run_id": "discovery-h3", "posts": [
        {"url": ROOT_URL, "text": T_SCA, "author_handle": "someone", "reply_count": 4}]})
    human = api.store.open_cards(Outlet.X)[0]
    api.store.upsert_card(ScoredCard(**{**human.model_dump(), "card_id": "card_botold2", "url": GROK_URL, "author": "@grok"}))
    st = c.get("/status").json()
    assert st["queue_size"] == 1 and st["queue_by_outlet"]["x"] == 1
