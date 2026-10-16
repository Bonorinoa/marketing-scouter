"""Job heartbeats: each scheduled job writes <heartbeat_dir>/<job>.json atomically.

Row: {job, started_at, finished_at, ok, detail, sha, skipped}. `skipped` is a reason string for a deliberate
skip (e.g. shared_x_read_cap); a skip is not a failure, but it does not refresh last_ran either.
/status reads these and warns in plain words when a job is older than its expected interval.
CLI (for cron/shell): python -m src.heartbeat <job> <ok|fail|skip> [detail] [--started ISO] [--dir DIR]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
JOBS = ("discovery", "backup", "health", "build", "cron", "cron_tick")
# expected interval in hours; None = event-driven (builds), never warned about
EXPECTED_HOURS: dict[str, Optional[float]] = {"discovery": 12, "backup": 26, "health": 26, "build": None,
                                           "cron": None,      # cron recover (--arm): event-driven, warns only on failure
                                           "cron_tick": 0.5}  # */15 scheduler tick; warn past 30 min
LABEL = {"discovery": "X discovery", "backup": "Backup", "health": "Health check", "build": "Build",
         "cron": "Cron recovery", "cron_tick": "Cron tick"}
# The */15 tick has its own job id so it can never overwrite (clear) a failed cron-recover heartbeat; only a
# later successful recover clears it. Legacy CLI calls `heartbeat cron ok ...` (the installed crontab line) are
# routed to cron_tick for the same reason.
CLI_ALIASES = {"cron": "cron_tick"}


def heartbeat_dir(data_dir: Path | str | None = None) -> Path:
    if os.environ.get("MS_HEARTBEAT_DIR"):
        return Path(os.environ["MS_HEARTBEAT_DIR"])
    d = Path(data_dir or os.environ.get("MS_DATA_DIR") or ROOT / "data" / "db")
    return d.parent / "heartbeats" if d.name == "db" else d / "heartbeats"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha() -> Optional[str]:
    if os.environ.get("MS_BUILD_SHA"):
        return os.environ["MS_BUILD_SHA"]
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def write(job: str, ok: bool, detail: str = "", started_at: Optional[str] = None, skipped: Optional[str] = None,
          directory: Path | str | None = None, sha: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    if job not in JOBS:
        raise ValueError(f"unknown job {job!r}; expected one of {JOBS}")
    d = Path(directory) if directory else heartbeat_dir()
    d.mkdir(parents=True, exist_ok=True)
    fin = (now or _now()).isoformat(timespec="seconds")
    row = {"job": job, "started_at": started_at or fin, "finished_at": fin, "ok": bool(ok),
           "detail": str(detail)[:500], "sha": sha or _sha(), "skipped": skipped}
    path = d / f"{job}.json"
    prev = read_one(path)
    if skipped and prev:   # keep the last real run so a skip never fakes freshness
        row["last_run"] = (prev.get("last_run") if prev.get("skipped") else
                           {k: prev.get(k) for k in ("started_at", "finished_at", "ok", "detail", "sha")})
    fd, tmp = tempfile.mkstemp(dir=d, prefix=f".{job}.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(row, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return row


def read_one(path: Path) -> Optional[dict]:
    try:
        return json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001
        return None


def _ago(h: float) -> str:
    if h < 1:
        return f"{int(h * 60)} min ago"
    if h < 48:
        return f"{h:.0f} h ago"
    return f"{h / 24:.0f} days ago"


def jobs_block(directory: Path | str | None = None, now: Optional[datetime] = None) -> dict:
    """{job: {last_ran, ok, detail, sha, skipped, age_hours, expected_hours, stale, warning}} + warnings list."""
    d = Path(directory) if directory else heartbeat_dir()
    now = now or _now()
    out: dict = {}
    warnings: list[str] = []
    for job in JOBS:
        row = read_one(d / f"{job}.json")
        exp = EXPECTED_HOURS[job]
        real = (row.get("last_run") if row and row.get("skipped") else row) or None
        last = real.get("finished_at") if real else None
        age = (now - datetime.fromisoformat(last)).total_seconds() / 3600 if last else None
        stale = bool(exp) and (age is None or age > exp)
        warn = None
        if stale:
            if job == "cron_tick":
                warn = ("The box's cron scheduler has never checked in, so scheduled health checks and backups "
                        "may not be running." if age is None else
                        f"The box's cron scheduler last checked in {_ago(age)}; it should every 15 min, so "
                        "scheduled health checks and backups may not be running.")
            else:
                warn = (f"{LABEL[job]} has never reported a run." if age is None else
                        f"{LABEL[job]} last ran {_ago(age)}; it should run every {exp:g} h.")
        if row and row.get("skipped"):
            s = f"Last {LABEL[job].lower()} was skipped on purpose ({row['skipped']})."
            warn = f"{warn} {s}" if warn else s   # a recent deliberate skip is still shown, as a note
        elif real and real.get("ok") is False:
            f = f"{LABEL[job]}'s last run failed: {real.get('detail') or 'no detail'}."
            warn = f"{warn} {f}" if warn else f
        if warn:
            warnings.append(warn)
        out[job] = {"last_ran": last, "ok": real.get("ok") if real else None, "detail": real.get("detail") if real else None,
                    "sha": real.get("sha") if real else None, "skipped": row.get("skipped") if row else None,
                    "skipped_at": row.get("finished_at") if row and row.get("skipped") else None,
                    "age_hours": round(age, 2) if age is not None else None, "expected_hours": exp,
                    "stale": stale, "warning": warn}
    return {"jobs": out, "warnings": warnings}


def main(argv: list[str]) -> int:
    args, opts = [], {}
    it = iter(argv)
    for a in it:
        if a in ("--started", "--dir"):
            opts[a] = next(it)
        else:
            args.append(a)
    if len(args) < 2 or args[1] not in ("ok", "fail", "skip"):
        print(__doc__, file=sys.stderr)
        return 2
    job, state, detail = CLI_ALIASES.get(args[0], args[0]), args[1], " ".join(args[2:])
    write(job, ok=state != "fail", detail=detail, started_at=opts.get("--started"),
          skipped=(detail or "skipped") if state == "skip" else None, directory=opts.get("--dir"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
