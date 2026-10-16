"""Pinned (AT raw_decline1.json, 2026-10-14): old cvprofiles rows with the caveat inside the stored draft.
View-time cleanup: main copy never carries the caveat; template pastes show the basic-drafter no-draft line."""
import json
from pathlib import Path

from src.api.draft_view import (COPY_WITH_CAVEAT_TOOLTIP, TEMPLATE_LINE, clean_draft)

CARDS = {c["card_id"]: c for c in json.loads(
    (Path(__file__).parent / "fixtures" / "raw_decline1_cvprofiles_cards.json").read_text())}


def gate_card(c):
    a = c["asset"]
    return {"outlet": c["outlet"], "door": c["door"], "slugs": c["slugs"], "asset_title": a["title"],
            "asset_url": a["url"], "asset_claim": c["claim"], "asset_caveat": a["caveat"],
            "evidence_grade": a["evidence_grade"]}


def test_model_draft_with_caveat_inside_is_stripped_for_main_copy():
    c = CARDS["card_ed8c823e651c"]
    cav = c["asset"]["caveat"]
    assert cav in c["draft"] and c["copy_enabled"] is True          # the bug as AT saw it
    v = clean_draft(c["draft"], c["predraft"], "x", gate_card(c))
    assert not v["no_draft"] and v["copy_override"] is True
    if True:
        assert cav.lower().rstrip(".") not in v["draft"].lower()
        assert v["draft"] == ("A measurement that fails every variant is a finding about measurement, "
                              "not about the phenomenon. The escape hatch is the point.")
        assert v["draft_with_caveat"] == v["draft"] + "\n\n" + cav
        assert v["copy_with_caveat_label"] == "Copy with caveat"
        assert v["copy_with_caveat_tooltip"] == COPY_WITH_CAVEAT_TOOLTIP == (
            "Copies the draft with the caveat as its last line. Whether readers see the caveat is your call.")


def test_template_paste_is_no_draft_and_copy_off():
    c = CARDS["card_20747fbd4e57"]
    v = clean_draft(c["draft"], c["predraft"], "x", gate_card(c))
    assert v["draft"] is None and v["no_draft"] and v["copy_override"] is False
    assert v["no_draft_line"] == TEMPLATE_LINE == (
        "No draft: the basic drafter can only repeat your claim, so this one is left blank.")


def test_local_template_model_is_no_draft():
    c = CARDS["card_ed8c823e651c"]
    v = clean_draft(c["draft"], {**c["predraft"], "model": "local_template"}, "x", gate_card(c))
    assert v["no_draft_line"] == TEMPLATE_LINE and v["draft"] is None


def test_caveat_only_draft_is_no_draft():
    c = CARDS["card_ed8c823e651c"]
    v = clean_draft(c["asset"]["caveat"].upper(), c["predraft"], "x", gate_card(c))
    assert v["no_draft"] and v["draft"] is None
