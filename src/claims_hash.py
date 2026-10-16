"""claims_sha: one hash over every asset's id + one_line_claim + caveat (what the grader and claim_echo read).
The :8712 copy store reads claims from its DB, not the seed, so the freeze compares both."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def claims_sha(rows) -> str:
    """rows: dicts or InventoryAsset-like objects. Order-independent; None and '' are the same."""
    def g(r, k):
        return (r.get(k) if isinstance(r, dict) else getattr(r, k, None)) or ""
    lines = sorted(f'{g(r, "asset_id")}\x1f{g(r, "one_line_claim").strip()}\x1f{g(r, "caveat").strip()}' for r in rows)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def seed_claims_sha(path: str | Path) -> str:
    return claims_sha(json.loads(Path(path).read_text(encoding="utf-8")))


def store_claims_sha(data_dir: str | Path) -> str:
    from .store import Store
    return claims_sha(Store(Path(data_dir) / "scouter.db").list_assets())
