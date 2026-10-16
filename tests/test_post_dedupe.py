"""One card per post (Designer blocker): dedupe on canonical post identity at card creation."""
import pytest

from src.api.core import ScouterAPI
from src.models import CardState, Outlet, ScoredCard, VoiceDoor
from src.post_identity import post_key


def test_post_key_forms():
    a = post_key("https://x.com/fixture_user_21/status/9000000000000000904?s=20")
    assert a == post_key("https://twitter.com/Fixture_User_21/status/9000000000000000904") == "x:9000000000000000904"
    assert post_key("https://www.lagaceta.com.ar/nota/1/?utm_source=x") == post_key("http://lagaceta.com.ar/nota/1")
    assert post_key("", "Same  text") == post_key(None, "same text") and post_key("", "") is None


@pytest.fixture
def api(tmp_path):
    return ScouterAPI(str(tmp_path))


def _card(asset_id, S, url="https://x.com/fixture_user_21/status/9000000000000000904"):
    return ScoredCard(candidate_id="c-" + asset_id, asset_id=asset_id, outlet=Outlet.X, url=url,
                      slugs=["cheap-gen-scarce-verify"], voice_door=VoiceDoor.AUGUSTO_CIVIC, S=S)


def _asset(api, asset_id):
    return {a.asset_id: a for a in api.store.list_assets()}.get(asset_id) or api.store.list_assets()[0]


def _live(api):
    return [c for c in api.store.list_cards() if c.state.value in ("open", "drafting", "awaiting_approval", "pinned")]


def test_higher_scoring_later_card_supersedes(api):
    lo, hi = _card("asset_civic_mix", 83.0), _card("asset_adepa_lagaceta_carta", 87.5)
    api._commit(lo, _asset(api, lo.asset_id), lo.slugs, "test")
    api._commit(hi, _asset(api, hi.asset_id), hi.slugs, "test")
    live = _live(api)
    assert [c.card_id for c in live] == [hi.card_id]
    assert api.store.get_card(lo.card_id).state == CardState.SKIPPED
    kept = api.store.get_card(hi.card_id)
    assert kept.post_dedupe == {"key": "x:9000000000000000904", "dropped": 1, "dropped_assets": ["asset_civic_mix"]}
    ev = [e for e in api.events() if e["kind"] == "post_dedupe"]
    assert ev and ev[-1]["dropped"] == 1 and ev[-1]["dropped_assets"] == ["asset_civic_mix"]


def test_lower_scoring_later_card_is_dropped_and_logged(api):
    hi, lo = _card("asset_adepa_lagaceta_carta", 87.5), _card("asset_civic_mix", 83.0)
    api._commit(hi, _asset(api, hi.asset_id), hi.slugs, "test")
    res = api._commit(lo, _asset(api, lo.asset_id), lo.slugs, "test")
    assert res["status"] == "duplicate_post" and res["kept_card_id"] == hi.card_id
    assert [c.card_id for c in _live(api)] == [hi.card_id] and api.store.get_card(lo.card_id) is None
    assert api.store.get_card(hi.card_id).post_dedupe["dropped_assets"] == ["asset_civic_mix"]


def test_different_posts_both_kept(api):
    a, b = _card("asset_civic_mix", 83.0), _card("asset_adepa_lagaceta_carta", 87.5, url="https://x.com/fixture_user_54/status/99999")
    for c in (a, b):
        api._commit(c, _asset(api, c.asset_id), c.slugs, "test")
    assert {c.card_id for c in _live(api)} == {a.card_id, b.card_id}
