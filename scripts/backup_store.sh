#!/usr/bin/env bash
# Copy data/db to /workspace/backups/store-<ts>/ with SHA256SUMS; keep newest 14.
# Writes data/heartbeats/backup.json (ok or fail) via src/heartbeat.py. Run by ensure_up --loop daily and cron.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
STARTED=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
SRC_DB="${BACKUP_SRC:-$REPO/data/db}"
hb() { (cd "$REPO" && "$PY" -m src.heartbeat backup "$@" --started "$STARTED" ${HEARTBEAT_DIR:+--dir "$HEARTBEAT_DIR"}) || true; }
trap 'hb fail "backup failed (exit $?)"' ERR
ROOT=${BACKUP_ROOT:-/workspace/backups}
KEEP=${KEEP:-14}
# one backup at a time (cron hourly check vs ensure_up --loop): a second caller waits up to 10 min, then gives up
mkdir -p "$ROOT"; exec 7>"${BACKUP_LOCK:-$ROOT/.backup_store.lock}"
flock -w 600 7 || { trap - ERR; echo "backup: another backup is running" >&2; exit 75; }
# BACKUP_IF_DUE_H=<h>: re-check "is a backup due" INSIDE the lock, so a caller that waited never makes a duplicate
if [ -n "${BACKUP_IF_DUE_H:-}" ]; then
  HBF="${HEARTBEAT_DIR:-$REPO/data/heartbeats}/backup.json"
  if "$PY" - "$HBF" "$BACKUP_IF_DUE_H" <<'PYEOF'
import json, sys, datetime
try:
    r = json.load(open(sys.argv[1]))
    r = (r.get("last_run") or {}) if r.get("skipped") else r
    age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(r["finished_at"])
    sys.exit(0 if r.get("ok") and age.total_seconds() < float(sys.argv[2]) * 3600 else 1)
except Exception:
    sys.exit(1)
PYEOF
  then trap - ERR; echo "backup: not due (last good backup < ${BACKUP_IF_DUE_H}h old)"; exit 0; fi
fi
TS=$(date -u +%Y%m%dT%H%M%SZ)
DEST="$ROOT/store-$TS"
mkdir -p "$DEST"
for f in "$SRC_DB"/*; do
  if [[ "$f" == *.db ]]; then
    "$PY" - "$f" "$DEST/$(basename "$f")" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(f"file:{src}?mode=ro", uri=True); d = sqlite3.connect(dst)
s.backup(d); s.close()
r = d.execute("PRAGMA integrity_check").fetchone()[0]; d.close()
if r != "ok":
    sys.exit(f"integrity_check failed for {dst}: {r}")
print(f"ok {dst}")
PY
  else
    cp -p "$f" "$DEST/"
  fi
done
(cd "$DEST" && sha256sum -- * > SHA256SUMS)
echo "backup: $DEST"
trap - ERR
hb ok "$DEST integrity ok"
ls -1d "$ROOT"/store-* 2>/dev/null | sort | head -n -"$KEEP" | xargs -r rm -rf --
