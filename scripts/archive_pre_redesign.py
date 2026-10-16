"""Archive (never delete) every pre-redesign card, scout_run and handoff in a data dir. Idempotent.

Usage: .venv/bin/python -m scripts.archive_pre_redesign [--data-dir data/db]
Stop the API first. Wins and the hash chain are never touched. Logs an `archive_pre_redesign` api event.
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
    a = ap.parse_args(argv)
    api = ScouterAPI(a.data_dir)
    head_before = api.wins_head()
    out = api.archive_pre_redesign()
    assert api.wins_head() == head_before, "wins hash chain changed"
    out["wins_head"] = head_before
    print(json.dumps(out))
    return out


if __name__ == "__main__":
    main()
