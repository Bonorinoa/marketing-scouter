"""Built-in civic drafts: the claim ends with terminal punctuation before the seed sentence."""
import json
import re

import pytest

from src.draft import _end_sentence, shape_draft
from src.fit import claim_for_slug
from src.models import InventoryAsset, Outlet, ScoredCard, VoiceDoor


@pytest.mark.parametrize("raw,want", [("don’t ban", "don’t ban."), ("ok.", "ok."), ("why?", "why?"),
                                      ("«no ban»", "«no ban»."), ("“stop.”", "“stop.”"), ("", "")])
def test_end_sentence(raw, want):
    assert _end_sentence(raw) == want


def _civic_assets():
    for a in json.load(open("data/seed_inventory.json")):
        yield InventoryAsset(**a)


@pytest.mark.parametrize("outlet", [Outlet.X, Outlet.OPED] if hasattr(Outlet, "OPED") else [Outlet.X])
def test_claim_not_run_into_next_sentence(outlet):
    """Claim must not run into the next sentence; with post text, do not open on the claim."""
    from src.voice_gate import claim_restated
    seen = 0
    for a in _civic_assets():
        for slug in a.slugs:
            card = ScoredCard(candidate_id="c", asset_id=a.asset_id, outlet=outlet, url="https://x.com/fixture_user_54/status/12345",
                              slugs=[slug], voice_door=VoiceDoor.AUGUSTO_CIVIC, S=80.0)
            d = shape_draft(card, a)
            claim = claim_for_slug(slug).rstrip()
            assert not re.search(r"ban In Tucum", d), d
            if claim and claim in d:
                seen += 1
            if a.door_archive == VoiceDoor.AUGUSTO_CIVIC or a.door_archive.value == "Augusto-civic":
                post = "Community Notes flagged a SynthID watermark on a viral image."
                d2 = shape_draft(card.model_copy(update={"title_or_snippet": post}), a, post_text=post)
                assert not claim_restated(d2, [claim, a.one_line_claim or ""]), d2
                assert d2.startswith("On Community Notes, "), d2   # answers the post; never "Re:" (P1 #6)
    assert seen


# ---- every built-in draft path: any claim followed by more text must end its sentence first ----
from src.draft import CLAIM_ES_DRAFT  # noqa: E402
from src.fit import fit_slug_map  # noqa: E402
from src.models import MoveType  # noqa: E402

_CLOSE = "\"'”’»)]"
ALL_ASSETS = list(_civic_assets())
ALL_SLUGS = sorted(fit_slug_map())


def _claims(asset, slug):
    out = {claim_for_slug(slug), CLAIM_ES_DRAFT.get(slug), asset.one_line_claim}
    return {c.strip() for c in out if c and c.strip() and c.strip()[-1] not in ".!?…" + _CLOSE}


def _runs_on(draft, claim):
    """True if an unpunctuated claim is followed (after spaces/newlines) by more text."""
    i = draft.find(claim)
    while i != -1:
        rest = draft[i + len(claim):]
        if rest.strip() and not rest.lstrip(_CLOSE)[:1] in tuple(".!?…"):
            return True
        i = draft.find(claim, i + 1)
    return False


def _variants():
    # real assets, plus: claim without its period, and no asset claim (falls back to the unpunctuated slug claim)
    for a in ALL_ASSETS:
        yield a.asset_id, a
        if a.one_line_claim:
            yield a.asset_id + "-nopunct", a.model_copy(update={"one_line_claim": a.one_line_claim.rstrip(" .")})
        yield a.asset_id + "-noclaim", a.model_copy(update={"one_line_claim": None})


@pytest.mark.parametrize("asset", [v for _, v in _variants()], ids=[i for i, _ in _variants()])
def test_every_draft_path_ends_claim_sentence(asset):
    outlets = [o for o in Outlet]
    checked = 0
    for door in VoiceDoor:
        for slug in sorted(set(asset.slugs or []) | set(ALL_SLUGS)):
            for outlet in outlets:
                for mv in (None, *MoveType):
                    sc = ScoredCard(candidate_id="c", asset_id=asset.asset_id, outlet=outlet,
                                    url="https://x.com/fixture_user_54/status/1", slugs=[slug], voice_door=door, S=80.0)
                    if mv:
                        sc.move_type = mv
                    d = shape_draft(sc, asset)
                    for cl in _claims(asset, slug):
                        if cl in d:
                            checked += 1
                            assert not _runs_on(d, cl), (asset.asset_id, door, slug, outlet, mv, cl, d)
    assert checked
