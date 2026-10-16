"""Structure checks for data/fit_rubric.json (versioned Fit reference posts)."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUBRIC = json.loads((ROOT / "tests" / "fixtures" / "fit_rubric.anon.json").read_text())  # anonymised; real rubric gitignored
INVENTORY = json.loads((ROOT / "data" / "seed_inventory.json").read_text())
FIXTURE = (ROOT / "tests" / "fixtures" / "discovery_20261013_offtopic.json").read_text()
LEVELS = {"claim", "topic", "none"}


def _examples():
    for asset_id, a in RUBRIC["assets"].items():
        for ex in a["examples"]:
            yield asset_id, ex


def test_schema_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+", RUBRIC["schema_version"])
    assert set(RUBRIC["levels"]) == LEVELS


def test_covers_every_inventory_asset_with_its_claim():
    # rubric (grading artifact) may track Researcher's pending wording until Augusto approves it
    inv = {a["asset_id"]: a["one_line_claim"] for a in INVENTORY}
    assert set(RUBRIC["assets"]) == set(inv)
    for asset_id, a in RUBRIC["assets"].items():
        assert a["one_line_claim"] == inv[asset_id]


def test_every_asset_has_all_three_levels():
    for asset_id, a in RUBRIC["assets"].items():
        levels = {ex["level"] for ex in a["examples"]}
        assert levels == LEVELS, asset_id


def test_example_fields():
    for asset_id, ex in _examples():
        assert re.fullmatch(r"\d{15,20}", ex["id"]), ex
        assert ex["url"] == f"https://example.invalid/status/{ex['id']}" and ex["id"].startswith("9000000")
        assert ex["level"] in LEVELS
        assert ex["text"].strip() and ex["reason"].strip()


def test_no_duplicate_ids():
    ids = [ex["id"] for _, ex in _examples()]
    assert len(ids) == len(set(ids))


def test_no_overlap_with_1215_holdout():
    held = set(RUBRIC["holdout"]["status_ids"])
    assert len(held) == 50
    held |= set(re.findall(r"status/(\d{15,20})", FIXTURE))
    assert not ({ex["id"] for _, ex in _examples()} & held)
