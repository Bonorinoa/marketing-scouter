"""Backfill one_line_claim from data/seed_inventory.json into the live store.

Dry run by default: prints old/new + sha256(new) per asset that differs. --apply writes, after a backup
under data/backups/claims-<ts>/ (old asset payloads + sha256 list), and appends a 'claims_backfill' event.

Usage: .venv/bin/python scripts/backfill_claims.py [--data-dir data/db] [--skip econllm_lab] [--apply]
"""
import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.store import Store  # noqa: E402


def sha(s: str) -> str:
    return hashlib.sha256((s or "").encode()).hexdigest()


def _norm(aid: str) -> str:
    return aid if aid.startswith("asset_") else f"asset_{aid}"


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "data" / "db"))
    ap.add_argument("--seed", default=str(ROOT / "data" / "seed_inventory.json"))
    ap.add_argument("--skip", action="append", default=[], help="asset id (with or without asset_), repeatable")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    skip = {_norm(s) for x in a.skip for s in x.split(",") if s.strip()}
    seed = {r["asset_id"]: r.get("one_line_claim") for r in json.loads(Path(a.seed).read_text())}
    db = Path(a.data_dir) / "scouter.db"
    if not db.exists():
        sys.exit(f"no store at {db}")
    store = Store(db)
    live = {x.asset_id: x for x in store.list_assets()}
    changes, skipped, missing = [], [], sorted(set(seed) - set(live))
    for aid, new in sorted(seed.items()):
        if aid not in live or not new or (live[aid].one_line_claim or "") == new:
            continue
        row = {"asset_id": aid, "old": live[aid].one_line_claim, "new": new, "new_sha256": sha(new)}
        (skipped if aid in skip else changes).append(row)
    for r in changes:
        print(f"== {r['asset_id']}\n  old: {r['old']}\n  new: {r['new']}\n  sha256(new): {r['new_sha256']}")
    for r in skipped:
        print(f"-- SKIPPED {r['asset_id']} (kept old)\n  old: {r['old']}\n  new: {r['new']}")
    if missing:
        print(f"seed assets not in store (ignored): {missing}")
    out = {"apply": a.apply, "changed": [r["asset_id"] for r in changes], "skipped": [r["asset_id"] for r in skipped]}
    if a.apply and changes:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bdir = ROOT / "data" / "backups" / f"claims-{ts}"
        bdir.mkdir(parents=True, exist_ok=False)
        shutil.copy2(db, bdir / "scouter.db")
        (bdir / "assets_before.json").write_text(json.dumps(
            {aid: json.loads(x.model_dump_json()) for aid, x in live.items()}, indent=2, ensure_ascii=False))
        (bdir / "sha256.txt").write_text("".join(
            f"{r['asset_id']}\told={sha(r['old'] or '')}\tnew={r['new_sha256']}\n" for r in changes))
        for r in changes:
            store.upsert_asset(live[r["asset_id"]].model_copy(update={"one_line_claim": r["new"]}))
        ev = {"ts": datetime.now(timezone.utc).isoformat(), "kind": "claims_backfill", "backup": str(bdir),
              "changed": [{"asset_id": r["asset_id"], "new_sha256": r["new_sha256"]} for r in changes],
              "skipped": out["skipped"]}
        with (Path(a.data_dir) / "api_events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        out["backup"] = str(bdir)
    print(json.dumps(out))
    return out


if __name__ == "__main__":
    main()
