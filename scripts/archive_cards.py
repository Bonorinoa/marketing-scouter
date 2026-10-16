"""Archive CARDS ONLY (no scout runs, no handoffs) into an archived_* state. Idempotent; prior state → archive_log.

Usage: .venv/bin/python scripts/archive_cards.py --label archived_offtopic_1215 --states open [--outlet x] [--data-dir data/db]
Stop the API first. Wins and the hash chain are never touched.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.core import ROOT, ScouterAPI  # noqa: E402


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "data" / "db"))
    ap.add_argument("--label", required=True)
    ap.add_argument("--states", required=True, help="comma list, e.g. open")
    a = ap.parse_args(argv)
    api = ScouterAPI(a.data_dir)
    head = api.wins_head()
    out = api.archive_cards(a.label, [s.strip() for s in a.states.split(",") if s.strip()])
    assert api.wins_head() == head, "wins hash chain changed"
    out["wins_head"] = head
    print(json.dumps(out))
    return out


if __name__ == "__main__":
    main()
