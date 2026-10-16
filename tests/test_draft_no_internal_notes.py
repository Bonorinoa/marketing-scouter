"""Drafts never carry internal evidence/status notes or topic tags (Designer blocker, 2026-10-13 17:02 PT).

Forbidden set = the real strings: every asset's `notes` (data/seed_inventory.json), every slug's 'use when' topic
list, and the fit-tags.md section headings / door labels that the old parser shifted into slug claims.
The asset caveat is allowed (it is the drafting limit sentence)."""
import json
import re
from pathlib import Path

import pytest

from src.draft import shape_draft
from src.fit import _FIT_TAGS_PATH, fit_slug_map
from src.models import InventoryAsset, MoveType, Outlet, ScoredCard, VoiceDoor

ROOT = Path(__file__).resolve().parent.parent
SEED = json.loads((ROOT / "data" / "seed_inventory.json").read_text(encoding="utf-8"))
ASSETS = [InventoryAsset(**{k: v for k, v in a.items() if k in InventoryAsset.model_fields}) for a in SEED]
NOTES = sorted({a["notes"].strip() for a in SEED if a.get("notes")})
TAGS = sorted({s.use_when.strip() for s in fit_slug_map().values() if s.use_when and len(s.use_when) > 12})
HEADINGS = re.findall(r"(?m)^#{2,3} .+$", _FIT_TAGS_PATH.read_text(encoding="utf-8"))
DOOR_LABELS = ["`Augusto-civic`", "`EconLLM`"]


def _forbidden_hits(text: str) -> list[str]:
    t = " ".join(text.split())
    hits = [n for n in NOTES if n in t]
    hits += [g for g in TAGS if g in t]
    hits += [h for h in HEADINGS if h.lstrip("# ").strip() in t]
    hits += [d for d in DOOR_LABELS if d in t]
    return hits


def test_forbidden_set_is_real_and_not_empty():
    assert len(NOTES) >= 6 and len(TAGS) >= 10 and HEADINGS
    assert "misinfo, Community Notes, AI and journalism, Adepa" in TAGS


def test_slug_claims_are_claims_not_tags_or_headings():
    for s in fit_slug_map().values():
        assert s.claim_one_liner != s.use_when, s.slug
        assert not s.claim_one_liner.startswith(("#", "`")) and "###" not in s.use_when, s.slug
    assert fit_slug_map()["cheap-gen-scarce-verify"].claim_one_liner.startswith("Generation/amplification is cheap")
    assert fit_slug_map()["cheap-gen-scarce-verify"].door == VoiceDoor.AUGUSTO_CIVIC


@pytest.mark.parametrize("asset", ASSETS, ids=lambda a: a.asset_id)
def test_builtin_drafts_have_no_notes_or_tags(asset):
    door = VoiceDoor(asset.door_archive.value) if asset.door_archive else VoiceDoor.ECONLLM
    for slug in asset.slugs or []:
        for outlet in (Outlet.X, Outlet.LINKEDIN):
            for mv in (None, MoveType.QUOTE, MoveType.ORIGINAL):
                sc = ScoredCard(candidate_id="c", asset_id=asset.asset_id, outlet=outlet,
                                url="https://x.com/fixture_user_54/status/1", slugs=[slug], voice_door=door, S=80.0)
                if mv:
                    sc.move_type = mv
                d = shape_draft(sc, asset)
                assert not _forbidden_hits(d), (slug, outlet, mv, _forbidden_hits(d), d)


def test_xbrief_path_sends_no_notes_or_tags(tmp_path, monkeypatch):
    from src.api import xbrief_bridge as xb
    for a in ASSETS:
        inp = xb.bridge_input({"url": "https://x.com/fixture_user_54/status/1", "asset_id": a.asset_id, "door": "EconLLM",
                               "claim": a.one_line_claim, "caveat": a.caveat, "text": "post"}, a.title)
        assert not _forbidden_hits(json.dumps(inp, ensure_ascii=False)), a.asset_id
        g = xb.asset_instructions(inp["asset_claim"], inp["asset_caveat"])
        assert not _forbidden_hits(g), a.asset_id


def test_xbrief_caveat_append_is_never_a_note(fake_xbrief=None):
    # the bridge only appends the asset caveat; none of the caveats is one of the internal notes verbatim
    for a in ASSETS:
        if a.caveat:
            assert a.caveat.strip() not in NOTES
