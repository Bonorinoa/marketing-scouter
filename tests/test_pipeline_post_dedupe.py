"""pipeline.ScoutRunner applies the same one-card-per-post helper as api/core.py (temp store only)."""
import json

import pytest

from src.events import EventLog
from src.models import CardState, InventoryAsset, Outlet, ScoredCard, VoiceDoor
from src.pipeline import ScoutRunner
from src.store import Store

URL = "https://x.com/fixture_user_21/status/9000000000000000904"


@pytest.fixture
def env(tmp_path):
    store, events = Store(tmp_path / "db.sqlite"), EventLog(tmp_path / "events.jsonl")
    assets = [InventoryAsset(**a) for a in json.load(open("data/seed_inventory.json"))]
    asset = next(a for a in assets if a.slugs)
    return store, events, ScoutRunner(store, events), asset


def _paste(runner, asset):
    return runner.paste_and_scout("https://twitter.com/Fixture_User_21/status/9000000000000000904?s=20",
                                  outlet=Outlet.X, asset=asset, title_hint="AI misinfo verify journalism llm")["primary"]


def _seed(store, S):
    c = ScoredCard(candidate_id="old", asset_id="asset_other", outlet=Outlet.X, url=URL, slugs=["x"],
                   voice_door=VoiceDoor.AUGUSTO_CIVIC, S=S)
    store.upsert_card(c)
    return c


def _dedupe_events(events):
    return [e for e in events.read_all() if e.get("kind") == "post_dedupe"]


def test_existing_higher_card_wins(env):
    store, events, runner, asset = env
    old = _seed(store, 1000.0)
    r = _paste(runner, asset)
    if r.get("kill_reasons"):
        pytest.skip(f"candidate killed: {r['kill_reasons']}")
    assert r["status"] == "duplicate_post" and r["kept_card_id"] == old.card_id
    kept = store.get_card(old.card_id)
    assert kept.state == CardState.OPEN and kept.post_dedupe["dropped_assets"] == [asset.asset_id]
    assert _dedupe_events(events)


def test_new_higher_card_supersedes(env):
    store, events, runner, asset = env
    old = _seed(store, 0.0)
    r = _paste(runner, asset)
    if r.get("kill_reasons"):
        pytest.skip(f"candidate killed: {r['kill_reasons']}")
    assert r["card"] is not None
    assert store.get_card(old.card_id).state == CardState.SKIPPED
    assert store.get_card(r["card"].card_id).post_dedupe == {"key": "x:9000000000000000904", "dropped": 1,
                                                              "dropped_assets": ["asset_other"]}
    assert _dedupe_events(events)
