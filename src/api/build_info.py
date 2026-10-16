"""build_sha + last ensure_up integrity result for /health (red when the last integrity check failed)."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATUS = "/workspace/marketing-scouter/data/ensure_up_status.json"


def _git_sha() -> str | None:
    if os.environ.get("MS_BUILD_SHA"):
        return os.environ["MS_BUILD_SHA"]
    try:
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no", "--", "src"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return (sha + ("-dirty" if dirty else "")) if sha else None
    except Exception:
        return None


BUILD_SHA = _git_sha()   # fixed at process start: the commit this server is running


def integrity_for(data_dir: Path) -> dict | None:
    """Last ensure_up integrity result for the server whose db dir is data_dir, or None if never checked."""
    try:
        servers = json.loads(Path(os.environ.get("MS_ENSURE_STATUS", DEFAULT_STATUS)).read_text()).get("servers", {})
    except Exception:
        return None
    dd = str(Path(data_dir).resolve())
    for s in servers.values():
        if s.get("db") and str(Path(s["db"]).resolve()) == dd and s.get("integrity"):
            return {"integrity": s["integrity"], "checked_at": s.get("integrity_checked_at")}
    return None
