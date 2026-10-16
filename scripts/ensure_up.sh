#!/usr/bin/env bash
# Idempotent keep-alive for Market Scouter (:8710 live, :8712 test copy). No systemd/crontab on the box.
#   scripts/ensure_up.sh            one pass: for each server whose /health is not OK, integrity-check its DBs,
#                                   then start it via scripts/up.sh with the env captured from the running process.
#   scripts/ensure_up.sh --capture  only refresh the captured env (logs/ensure_up.<port>.env) from /proc.
#   scripts/ensure_up.sh --loop     run a pass every ${ENSURE_EVERY:-300}s forever (singleton via flock).
#   scripts/ensure_up.sh --backup-if-due  run scripts/backup_store.sh if the last good backup is >24h old.
#   scripts/ensure_up.sh --cron-check  start cron if it is down (passwordless sudo only) and load any missing
#                                   scripts/crontab.txt lines; failures go to the cron heartbeat (/status warns).
#   scripts/ensure_up.sh --arm      run --cron-check, then start the --loop in the background with nohup if it isn't running (idempotent).
# A failed integrity check refuses the start, appends to logs/ensure_up.log, writes data/ALERT_db_integrity, exits 3.
# Test hooks: ENSURE_DB_DIR_<port> overrides the DB dir checked; ENSURE_PORTS limits ports (default "8710 8712").
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
LOGDIR="$REPO/logs"; LOG="${ENSURE_LOG:-$LOGDIR/ensure_up.log}"; ALERT="${ENSURE_ALERT:-$REPO/data/ALERT_db_integrity}"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
PORTS="${ENSURE_PORTS:-8710 8712}"
mkdir -p "$LOGDIR"
log() { echo "$(date '+%F %T %Z') $*" >>"$LOG"; }

healthy() { curl -fsS -m 5 "http://127.0.0.1:$1/health" 2>/dev/null | "$PY" -c 'import sys,json;sys.exit(0 if json.load(sys.stdin).get("ok") is True else 1)' 2>/dev/null; }
pid_of() { ss -ltnpH "sport = :$1" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2; }

# Capture only MS_* settings (never secrets) and args of the running server, so restarts match.
capture() {
  local p=$1 pid; pid=$(pid_of "$p"); [ -n "$pid" ] || return 1
  { tr '\0' '\n' <"/proc/$pid/environ" | grep -E '^MS_[A-Z0-9_]+=' ; echo "# args: $(tr '\0' ' ' <"/proc/$pid/cmdline")"; } \
    >"$LOGDIR/ensure_up.$p.env.tmp" && mv "$LOGDIR/ensure_up.$p.env.tmp" "$LOGDIR/ensure_up.$p.env"
}
# start with every captured MS_* setting (except MS_BUILD_SHA, which is the pin) exported, so restarts match
with_env() {
  local p=$1; shift
  ( set -a
    while IFS= read -r kv; do export "$kv"; done < <(grep -E '^MS_[A-Z0-9_]+=' "$LOGDIR/ensure_up.$p.env" 2>/dev/null | grep -v '^MS_BUILD_SHA=')
    set +a; "$@" )
}
envval() { grep -E "^$2=" "$LOGDIR/ensure_up.$1.env" 2>/dev/null | head -1 | cut -d= -f2-; }

db_dir() {
  local p=$1 o; o="ENSURE_DB_DIR_$p"
  if [ -n "${!o:-}" ]; then echo "${!o}"; return; fi
  local d; d=$(envval "$p" MS_DATA_DIR)
  if [ -n "$d" ]; then echo "$d"; elif [ "$p" = 8712 ]; then echo /workspace/ms-either-copy/db; else echo "$REPO/data/db"; fi
}

integrity() {  # prints one line per bad file; returns nonzero if any file is not 'ok'
  "$PY" - "$1" <<'PYEOF'
import sqlite3, sys, pathlib
bad = 0
for f in sorted(pathlib.Path(sys.argv[1]).glob("*.db")):
    try:
        con = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
        r = [x[0] for x in con.execute("PRAGMA integrity_check").fetchall()]
        con.close()
    except Exception as e:
        r = [f"error: {e}"]
    if r != ["ok"]:
        bad = 1; print(f"{f}: {'; '.join(r)[:300]}")
sys.exit(bad)
PYEOF
}

STATUS="${ENSURE_STATUS:-$REPO/data/ensure_up_status.json}"; PINS="${ENSURE_PINS:-$REPO/data/pins}"
WT_ROOT="${ENSURE_WT_ROOT:-/workspace/ms-worktrees}"

# status <port> <state> <reason> <db> <build_sha> <integrity ok|failed|"">  (atomic merge into $STATUS)
status() {
  "$PY" - "$STATUS" "$@" "$PINS" <<'PYEOF'
import json, os, sys, datetime, tempfile
path, port, state, reason, db, sha, integ, pins = sys.argv[1:9]
now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
try:
    d = json.load(open(path))
except Exception:
    d = {}
d.setdefault("servers", {})
prev = d["servers"].get(port, {})
e = {"port": int(port), "state": state, "reason": reason or None, "db": db, "checked_at": now,
     "build_sha": sha or prev.get("build_sha"),
     "integrity": integ or prev.get("integrity"),
     "integrity_checked_at": now if integ else prev.get("integrity_checked_at")}
try:
    e["boot_id"] = open("/proc/sys/kernel/random/boot_id").read().strip()
except Exception:
    e["boot_id"] = None
try:
    e["pinned_sha"] = open(os.path.join(pins, port + ".sha")).read().strip() or None
except Exception:
    e["pinned_sha"] = None
e["checked_sha"] = e["build_sha"]   # commit the running server reported when checked
e["written_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
d["servers"][port] = e; d["updated_at"] = now
d["doc"] = ("8:15 routine: /health unreachable => red; then read servers[<port>].state/reason here. "
            "state ok|down|integrity_failed|start_failed; /health.integrity=failed also => red. "
            "Entry is stale (treat as down) if boot_id != current boot_id, written_at older than 10 min, "
            "or checked_sha != pinned_sha.")
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or "."); os.write(fd, json.dumps(d, indent=1).encode()); os.close(fd)
os.replace(tmp, path)
PYEOF
}

health_field() { curl -fsS -m 5 "http://127.0.0.1:$1/health" 2>/dev/null | "$PY" -c "import sys,json;print(json.load(sys.stdin).get('$2') or '')" 2>/dev/null; }

pin_of() {  # pinned commit; default = the commit the server runs now (its /health build_sha), else repo HEAD
  local p=$1 f="$PINS/$1.sha" sha; mkdir -p "$PINS"
  if [ ! -s "$f" ]; then
    sha=$(health_field "$p" build_sha); sha=${sha%-dirty}
    [ -n "$sha" ] || sha=$(git -C "$REPO" rev-parse HEAD)
    echo "$sha" >"$f"; log ":$p pin defaulted to $sha (data/pins/$p.sha)"
  fi
  git -C "$REPO" rev-parse --verify -q "$(tr -d '[:space:]' <"$f")^{commit}"
}

worktree_for() {  # /workspace/ms-worktrees/<sha>, sharing the repo's venv, node_modules and the live data/db
  local sha=$1 wt="$WT_ROOT/$1"
  if [ ! -d "$wt/.git" ] && [ ! -f "$wt/.git" ]; then
    mkdir -p "$WT_ROOT"; git -C "$REPO" worktree add --detach -f "$wt" "$sha" >>"$LOG" 2>&1 || return 1
  fi
  [ -e "$wt/.venv" ] || ln -s "$REPO/.venv" "$wt/.venv"
  [ -e "$wt/web/node_modules" ] || ln -s "$REPO/web/node_modules" "$wt/web/node_modules"
  [ -e "$wt/data/db" ] || ln -s "$REPO/data/db" "$wt/data/db"
  local f  # untracked (gitignored) account lists live only in the main checkout
  for f in bot_accounts.json brand_accounts.json self_accounts.json; do
    [ -e "$wt/data/$f" ] || [ ! -e "$REPO/data/$f" ] || ln -s "$REPO/data/$f" "$wt/data/$f"
  done
  # approved style guide (gitignored; quotes Augusto's posts): the drafter reads it from the worktree
  # (v1 too: untracked after f531e7e, still read by older pins / x-brief live)
  for f in style_augusto.v1.md style_augusto.v2.md; do
    [ -e "$wt/prompts/$f" ] || [ ! -e "$REPO/prompts/$f" ] || ln -s "$REPO/prompts/$f" "$wt/prompts/$f"
  done
  echo "$wt"
}

one_pass() {
  local rc=0 p
  for p in $PORTS; do
    if [ -e "$LOGDIR/ensure_up.pause.$p" ]; then log ":$p paused ($(cat "$LOGDIR/ensure_up.pause.$p" 2>/dev/null)); skipped"; continue; fi
    local dir out integ="ok" sha; dir=$(db_dir "$p")
    out=$(integrity "$dir") || integ="failed"
    if healthy "$p"; then
      capture "$p"; sha=$(health_field "$p" build_sha)
      [ -s "$PINS/$p.sha" ] || pin_of "$p" >/dev/null
      if [ "$integ" = ok ]; then status "$p" ok "" "$dir" "$sha" ok; continue; fi
      log "ALERT :$p is up but its DB failed integrity_check: $out"
      echo "$(date '+%F %T %Z') :$p (running) integrity_check failed: $out" >>"$ALERT"
      status "$p" integrity_failed "integrity_check: ${out:0:300}" "$dir" "$sha" failed; rc=3; continue
    fi
    log ":$p health not OK; integrity_check on $dir/*.db: $integ"
    if [ "$integ" != ok ]; then
      log "REFUSING to start :$p: DB integrity check failed: $out"
      { echo "$(date '+%F %T %Z') :$p refused to start, integrity_check failed:"; echo "$out"; } >>"$ALERT"
      status "$p" integrity_failed "refused start; integrity_check: ${out:0:300}" "$dir" "" failed; rc=3; continue
    fi
    status "$p" down "health not OK; starting" "$dir" "" ok
    local pin wt; pin=$(pin_of "$p") || { status "$p" start_failed "bad pin in data/pins/$p.sha" "$dir" "" ok; rc=1; continue; }
    wt=$(worktree_for "$pin") || { status "$p" start_failed "git worktree add $pin failed" "$dir" "" ok; rc=1; continue; }
    if [ "$p" = 8710 ]; then
      [ "$(envval 8710 MS_FIT_SHADOW)" = "1" ] || [ ! -f "$LOGDIR/ensure_up.8710.env" ] || log "warn: captured :8710 env differs from up.sh (MS_FIT_SHADOW=1)"
      log "starting :8710 at $pin via $wt/scripts/up.sh --only=8710"
      with_env 8710 env MS_BUILD_SHA="$pin" "$wt/scripts/up.sh" --only=8710 >>"$LOG" 2>&1 || rc=1
    else
      local mode pre; mode=$(envval 8712 MS_FIT_GRADED_MODE); pre=$(envval 8712 MS_INTAKE_PREDRAFT)
      log "starting :8712 at $pin via $wt/scripts/up.sh --only=8712 (MODE=${mode:-model} PREDRAFT=${pre:-xbrief})"
      with_env 8712 env MS_BUILD_SHA="$pin" MODE="${mode:-model}" PREDRAFT="${pre:-xbrief}" "$wt/scripts/up.sh" --only=8712 >>"$LOG" 2>&1 || rc=1
    fi
    if healthy "$p"; then
      sha=$(health_field "$p" build_sha); log ":$p healthy after start, build_sha=$sha"; capture "$p"
      status "$p" ok "restarted by ensure_up" "$dir" "$sha" ok
    else
      log ":$p still not healthy after start"; status "$p" start_failed "not healthy after up.sh (see logs)" "$dir" "" ok; rc=1
    fi
  done
  return $rc
}

# one pass at a time across the --loop and cron (both call this), so a down server is never started twice
locked_pass() { ( flock -w 120 9 || exit 75; one_pass ) 9>"$LOGDIR/ensure_up.pass.lock"; }
health_hb() { (cd "$REPO" && "$PY" -m src.heartbeat health "$@" ${HEARTBEAT_DIR:+--dir "$HEARTBEAT_DIR"}) || true; }
# Daily live-DB backup, independent of bot routines: runs scripts/backup_store.sh (keeps newest 14) when
# data/heartbeats/backup.json has no successful run in the last BACKUP_EVERY_H hours (default 24).
backup_if_due() {
  local hbf="${HEARTBEAT_DIR:-$REPO/data/heartbeats}/backup.json"
  if "$PY" - "$hbf" "${BACKUP_EVERY_H:-24}" <<'PYEOF'
import json, sys, datetime
try:
    r = json.load(open(sys.argv[1])); r = r.get("last_run") or r if r.get("skipped") else r
    if not r.get("ok"): sys.exit(1)
    age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(r["finished_at"])
    sys.exit(0 if age.total_seconds() < float(sys.argv[2]) * 3600 else 1)
except Exception:
    sys.exit(1)
PYEOF
  then return 0; fi
  log "backup due; running scripts/backup_store.sh"
  BACKUP_IF_DUE_H="${BACKUP_EVERY_H:-24}" "$REPO/scripts/backup_store.sh" >>"$LOG" 2>&1 || { log "backup FAILED"; return 1; }
}

# Cron recovery lives in src/cron_recover.py: fixed argv, no shell, fixed minimal env, crontab via stdin only.
cron_check() {
  # wanted crontab comes from the LIVE PIN's commit (git show <sha>:scripts/crontab.txt), never the working tree
  (cd "$REPO" && "$PY" -m src.cron_recover --pin "${CRON_PIN_FILE:-$PINS/8710.sha}" \
     ${HEARTBEAT_DIR:+--dir "$HEARTBEAT_DIR"}) | while IFS= read -r l; do log "$l"; done
  return "${PIPESTATUS[0]}"
}

LOCKF="${ENSURE_LOCK:-$LOGDIR/ensure_up.lock}"   # content: "<pid> <boot_id>"
boot_id() { cat /proc/sys/kernel/random/boot_id 2>/dev/null; }
lock_live() {  # 0 if the lock names a live ensure_up loop from this boot
  [ -s "$LOCKF" ] || return 1
  local pid bid; read -r pid bid <"$LOCKF" || return 1
  [ -n "$pid" ] && [ "$bid" = "$(boot_id)" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | grep -q 'ensure_up.sh --loop' || return 1
}
case "${1:-}" in
  --capture) for p in $PORTS; do capture "$p" && echo "captured :$p -> $LOGDIR/ensure_up.$p.env" || echo ":$p not running"; done ;;
  --loop)
    exec 8>"$LOCKF.mutex"; flock 8
    if lock_live && [ "$(cut -d' ' -f1 "$LOCKF")" != "$$" ]; then echo "loop already running"; exit 0; fi
    echo "$$ $(boot_id)" >"$LOCKF.tmp" && mv "$LOCKF.tmp" "$LOCKF"; flock -u 8; exec 8>&-
    log "loop started pid $$ boot $(boot_id) every ${ENSURE_EVERY:-300}s"
    trap '[ "$(cut -d" " -f1 "$LOCKF" 2>/dev/null)" = "$$" ] && rm -f "$LOCKF"' EXIT
    while true; do locked_pass; backup_if_due; sleep "${ENSURE_EVERY:-300}"; done ;;
  --cron-check) cron_check; exit $? ;;
  --arm)
    cron_check || true
    if lock_live; then echo "loop already running (pid $(cut -d' ' -f1 "$LOCKF"))"; exit 0; fi
    if [ -e "$LOCKF" ]; then log "stale lock removed: $(cat "$LOCKF" 2>/dev/null) (boot now $(boot_id))"; rm -f "$LOCKF"; fi
    nohup setsid "$REPO/scripts/ensure_up.sh" --loop >>"$LOG" 2>&1 </dev/null &
    sleep 1; echo "armed loop pid $!" ;;
  --backup-if-due) backup_if_due; exit $? ;;
  "") locked_pass; rc=$?
      if [ $rc = 0 ]; then health_hb ok "all servers healthy (${PORTS})"; else health_hb fail "ensure_up pass rc=$rc; see logs/ensure_up.log"; fi
      exit $rc ;;
  *) echo "usage: $0 [--capture|--loop|--arm|--cron-check|--backup-if-due]" >&2; exit 2 ;;
esac
