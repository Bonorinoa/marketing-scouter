"""Pinned: x-brief ranker decline -> explicit xbrief_declined with reason; :8710 starts with x-brief drafting."""
from pathlib import Path
from src.api import xbrief_bridge as xb

ROOT = Path(__file__).resolve().parents[1]
DECLINED = """# Brief\n\n## Recommendations\n\nNothing worth reposting or commenting on in this window.\n\nReason: This is a joke about AI sports-lineups.\n\n## Original post opportunities\n\nNone.\n"""
DRAFTED = """## Recommendations\n\n### #1 — @fixture_user_41 / x\n- **Source:** https://x.com/fixture_user_54/status/1\n- **Draft:** hello\n\n## Run notes\n"""


def test_decline_reason_extracted():
    assert xb.extract_decline(DECLINED) == "This is a joke about AI sports-lineups."


def test_no_decline_when_recommendation_present():
    assert xb.extract_decline(DRAFTED) is None
    assert xb.extract_decline("no sections") is None


def test_declined_code_has_plain_message():
    assert xb.ERRORS["xbrief_declined"].startswith("No draft:")


def test_live_8710_starts_with_xbrief_predraft():
    up = (ROOT / "scripts/up.sh").read_text()
    line = next(l for l in up.splitlines() if "MS_FIT_SHADOW=1" in l and "env -u" in l)
    assert 'MS_INTAKE_PREDRAFT="${LIVE_PREDRAFT:-xbrief}"' in line
