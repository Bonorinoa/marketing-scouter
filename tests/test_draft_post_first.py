"""Designer P2 #7: built-in drafts respond to the post; first sentence must not restate the claim."""
import json
from pathlib import Path

from src.draft import shape_draft
from src.models import InventoryAsset, Outlet, ScoredCard, VoiceDoor
from src.voice_gate import check_draft, claim_restated, first_sentence

ROOT = Path(__file__).resolve().parent.parent
SEED = {a["asset_id"]: InventoryAsset(**{k: v for k, v in a.items() if k in InventoryAsset.model_fields})
        for a in json.loads((ROOT / "data" / "seed_inventory.json").read_text())}

# Made-up post in the shape of live card_ead2fc06ec82 (viral AI image)
EAD2_POST = (
    "@fixture_user_50 @fixture_user_51 No real location. This is an AI-generated picture that spread widely "
    "in March 2026. Readers on the first posts spotted a generator watermark, "
    "and no shop has said it is theirs. Earlier look-alike signs were also shown to be fake."
)
EAD2_OLD = (
    "Generation/amplification is cheap; verification + local context are scarce — coexist with AI, "
    "don’t ban. Not published yet: an argument, not evidence."
)


def test_ead2_post_feeds_builtin_not_claim_first():
    a = SEED["asset_adepa_lagaceta_carta"]
    sc = ScoredCard(
        candidate_id="c", asset_id=a.asset_id, outlet=Outlet.X,
        url="https://x.com/fixture_user_68/status/9000000000000000001", title_or_snippet=EAD2_POST,
        author="@grok", slugs=["cheap-gen-scarce-verify"], voice_door=VoiceDoor.AUGUSTO_CIVIC, S=80,
    )
    d = shape_draft(sc, a, post_text=EAD2_POST)
    # Designer P1 #6 (Wed 4:46): never "Re:" / quote-cue; first line answers the post's point
    assert not d.lower().lstrip().startswith("re:") and not d.lstrip().startswith(('"', "“")), d
    assert first_sentence(d) == "On real location, that's where verification matters.", d
    assert a.caveat in d
    assert "generation" in d.lower() and "verification" in d.lower()
    assert not claim_restated(d, [a.one_line_claim or "", EAD2_OLD.split(".")[0]])
    assert not first_sentence(d).lower().startswith("generation")
    # 2026-10-14: core strips the caveat (card field); the built-in template still carries the claim
    # verbatim, so the claim_overlap rule blocks copy for it. That is the intended fallback behaviour.
    from src.voice_gate import strip_caveat
    gate = check_draft(strip_caveat(d, a.caveat), {
        "outlet": "x", "door": "Augusto-civic", "slugs": ["cheap-gen-scarce-verify"],
        "asset_title": a.title, "asset_claim": a.one_line_claim, "asset_caveat": a.caveat,
        "evidence_grade": a.evidence_grade.value,
    })
    assert [x["code"] for x in gate.reasons] == ["claim_overlap"], gate.reasons


def test_old_ead2_template_flagged_by_gate():
    a = SEED["asset_adepa_lagaceta_carta"]
    r = check_draft(EAD2_OLD, {
        "outlet": "x", "door": "Augusto-civic", "slugs": ["cheap-gen-scarce-verify"],
        "asset_title": a.title, "asset_claim": a.one_line_claim, "asset_caveat": a.caveat,
    })
    assert "claim_restated" in {x["code"] for x in r.reasons}


def test_predraft_local_passes_post_text(tmp_path, monkeypatch):
    from src.api.core import ScouterAPI
    monkeypatch.setenv("MS_INTAKE_PREDRAFT", "local")
    api = ScouterAPI(str(tmp_path))
    a = SEED["asset_adepa_lagaceta_carta"]
    api.store.upsert_asset(a)
    card = {
        "url": "https://x.com/grok/status/1", "outlet": "x", "door": "Augusto-civic",
        "slug": "cheap-gen-scarce-verify", "slugs": ["cheap-gen-scarce-verify"],
        "claim": a.one_line_claim, "S": 80, "asset": api.asset_view(a),
        "draft": EAD2_OLD, "post_text": EAD2_POST, "author": "@grok",
    }
    out = api._predraft({"text": EAD2_POST, "author_handle": "@grok"}, card)
    assert out["status"] == "ok" and out["model"] == "local_template"
    assert not out["draft_text"].lower().lstrip().startswith("re:")
    assert first_sentence(out["draft_text"]).startswith("On real location,")
    assert not claim_restated(out["draft_text"], [a.one_line_claim or ""])


def test_no_re_opener_any_door_or_outlet():
    """Every built-in path (X reply, X quote, LinkedIn) opens by answering the post, never "Re:"."""
    from src.models import MoveType
    from src.voice_gate import opens_on_quote_cue
    posts = [EAD2_POST, "Does the WVS world values map hold up for GPT answers?", "https://t.co/abc", "lol"]
    for aid, door, slug in (("asset_adepa_lagaceta_carta", VoiceDoor.AUGUSTO_CIVIC, "cheap-gen-scarce-verify"),
                            ("asset_gpt4o_weird", VoiceDoor.ECONLLM, "gpt4o-weird")):
        a = SEED[aid]
        for outlet, move in ((Outlet.X, MoveType.REPLY), (Outlet.X, MoveType.QUOTE), (Outlet.LINKEDIN, MoveType.REPLY)):
            for post in posts:
                sc = ScoredCard(candidate_id="c", asset_id=aid, outlet=outlet, move_type=move,
                                url="https://x.com/fixture_user_54/status/1", title_or_snippet=post, author="@fixture_user_41",
                                slugs=[slug], voice_door=door, S=80)
                d = shape_draft(sc, a, post_text=post)
                assert not opens_on_quote_cue(d), (aid, outlet, move, post, d)
                assert "Re:" not in d.split("\n")[0], d
                assert not claim_restated(d, [a.one_line_claim or ""]), d


def test_gate_blocks_re_and_quote_cue_openers():
    from src.voice_gate import check_draft as gate
    card = {"outlet": "x", "door": "EconLLM", "slugs": ["gpt4o-weird"],
            "asset_title": "GPT4o is WEIRD", "asset_claim": "GPT-4o-mini answers cluster with WEIRD values on the WVS map."}
    for bad in ('Re: "the WVS map." GPT answers lean WEIRD there.', '"The WVS map" — GPT answers lean WEIRD.',
                "re : the map. GPT answers lean WEIRD.", "“Values map” is right; GPT answers lean WEIRD."):
        assert "quote_cue_opener" in {x["code"] for x in gate(bad, card).reasons}, bad
    ok = gate("On the WVS map, GPT answers lean WEIRD in our runs.", card)
    assert "quote_cue_opener" not in {x["code"] for x in ok.reasons}
