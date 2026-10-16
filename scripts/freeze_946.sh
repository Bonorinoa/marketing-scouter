#!/usr/bin/env bash
# 9:46 freeze for the :8712 test copy. Jev v1 decides: provider typesafe, model jev-1.13.0, criteria v1,
# argmax probabilities + data/fit_grader/jev_cutoffs.v1.json (decision=cutoffs); MS_FIT_GRADED_MODE=model;
# word-filter verdict logged in fit_trace; claim_echo (always on) + lang cap on; x-brief drafting.
# Pins :8712 to FREEZE_SHA (data/pins/freeze_946.sha, committed), never HEAD. Refuses if any commit after FREEZE_SHA,
# or any uncommitted change, touches the frozen paths; refuses if the copy store's claims differ from the seed's.
#   scripts/freeze_946.sh                apply to :8712: archive held cards, write env, pin FREEZE_SHA, restart via ensure_up
#   scripts/freeze_946.sh --dry-run      same steps against a /tmp COPY of the :8712 db on port 8798 (no :8712 change)
#                                         + exactly ONE Jev call to prove the grader works; then stops the dry server
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$REPO"
PY="$REPO/.venv/bin/python"; LOGDIR="$REPO/logs"; mkdir -p "$LOGDIR"
COPY_DB=/workspace/ms-either-copy/db
DRY=0; JEV=1
for a in "$@"; do case "$a" in --dry-run) DRY=1 ;; --no-jev) JEV=0 ;; *) echo "usage: $0 [--dry-run [--no-jev]]" >&2; exit 2 ;; esac; done
FREEZE_ENV=(MS_DATA_DIR="$COPY_DB" MS_FIT_GRADED_MODE=model MS_FIT_GRADER_PROVIDER=typesafe MS_FIT_GRADER_DECISION=cutoffs
            MS_LANG_CAP=on MS_INTAKE_PREDRAFT=xbrief)
say() { echo "[freeze_946 $(date '+%H:%M:%S %Z')] $*"; }
# Result file, written atomically on success, refusal and unexpected error (EXIT trap). A dry run writes ONLY the
# .dryrun.json path, never the real one. Both are gitignored and outside the frozen paths.
if [ "$DRY" = 1 ]; then RESULT="$REPO/data/freeze_946_result.dryrun.json"; else RESULT="$REPO/data/freeze_946_result.json"; fi
STARTED=$(date -Iseconds); REFUSED=""; SHA=""; BUILD=""; CLAIMS=""; QCOUNT=""; SNAP="$LOGDIR/freeze_946.snap.$$.json"
rm -f "$SNAP"
refuse() { REFUSED="$1"; say "REFUSED: $1"; exit 2; }
finish() {
  local rc=$?
  rm -f "$LOGDIR/ensure_up.pause.8712" 2>/dev/null   # never leave ensure_up paused
  FR_RC=$rc FR_DRY=$DRY FR_REFUSED="$REFUSED" FR_SHA="$SHA" FR_BUILD="$BUILD" FR_CLAIMS="$CLAIMS" FR_Q="$QCOUNT" \
  FR_STARTED="$STARTED" FR_SNAP="$SNAP" "$PY" - "$RESULT" <<'PYEOF'
import json, os, sys, datetime, tempfile
e = os.environ; rc = int(e["FR_RC"]); refused = e["FR_REFUSED"] or None
if rc != 0 and not refused:
    refused = f"unexpected_error (exit {rc})"
snap = None
try:
    snap = json.load(open(e["FR_SNAP"]))
except Exception:
    pass
try:
    boot = open("/proc/sys/kernel/random/boot_id").read().strip()
except Exception:
    boot = None
out = {"ok": rc == 0 and not refused, "dry_run": e["FR_DRY"] == "1", "refused_reason": refused, "exit_code": rc,
       "freeze_sha": e["FR_SHA"] or None, "build_sha": e["FR_BUILD"] or None, "claims_sha": e["FR_CLAIMS"] or None,
       "status": snap, "queue_count": int(e["FR_Q"]) if e["FR_Q"].isdigit() else None,
       "started_at": e["FR_STARTED"], "finished_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
       "boot_id": boot}
path = sys.argv[1]
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".freeze_946_result.")
with os.fdopen(fd, "w") as f:
    json.dump(out, f, indent=1)
os.replace(tmp, path)
PYEOF
  rm -f "$SNAP"
  say "result: $RESULT (ok=$([ $rc = 0 ] && [ -z "$REFUSED" ] && echo true || echo false), exit $rc)"
  exit $rc
}
trap finish EXIT
trap 'REFUSED="interrupted"; exit 130' INT TERM
FROZEN=(src prompts data/fit_grader data/seed_inventory.json scripts web/src)
PINF="$REPO/data/pins/freeze_946.sha"
[ -s "$PINF" ] || refuse "missing data/pins/freeze_946.sha (FREEZE_SHA)"
SHA=$(git rev-parse --verify -q "$(tr -d '[:space:]' <"$PINF")^{commit}") || refuse "bad FREEZE_SHA in data/pins/freeze_946.sha"
git merge-base --is-ancestor "$SHA" HEAD || refuse "FREEZE_SHA $SHA is not an ancestor of HEAD"
later=$(git diff --name-only "$SHA" HEAD -- "${FROZEN[@]}")
[ -z "$later" ] || refuse "commits after FREEZE_SHA touch frozen paths: $(echo $later)"
dirty=$(git status --porcelain -- "${FROZEN[@]}")
[ -z "$dirty" ] || refuse "uncommitted changes in frozen paths: $(echo $dirty)"
say "FREEZE_SHA=$SHA (HEAD $(git rev-parse --short HEAD)); frozen paths unchanged since"

check_claims() {  # copy store (what :8712 grades with) must equal the seed at FREEZE_SHA
  git show "$SHA:data/seed_inventory.json" >"$LOGDIR/freeze_946.seed.json" || return 1
  "$PY" - "$1" "$LOGDIR/freeze_946.seed.json" "$LOGDIR/freeze_946.claims" <<'PYEOF'
import sys
from src.claims_hash import seed_claims_sha, store_claims_sha
st, sd = store_claims_sha(sys.argv[1]), seed_claims_sha(sys.argv[2])
print(f"claims_sha store={st} seed={sd}")
open(sys.argv[3], "w").write(st)
sys.exit(0 if st == sd else 1)
PYEOF
  local r=$?; CLAIMS=$(cat "$LOGDIR/freeze_946.claims" 2>/dev/null); return $r
}

[ -n "${JEV_API_KEY:-}" ] || refuse "JEV_API_KEY is not set in this shell"
# config this freeze expects (from data/fit_grader/config.json; refuse if it drifted)
"$PY" - <<'PYEOF'
import json, sys
c = json.load(open("data/fit_grader/config.json"))
want = {"typesafe_model": "jev-1.13.0", "typesafe_criteria_file": "prompts/jev_criteria.v1.json",
        "typesafe_cutoffs_file": "data/fit_grader/jev_cutoffs.v1.json"}
bad = {k: c.get(k) for k, v in want.items() if c.get(k) != v}
if bad:
    print("[freeze_946] config.json drifted:", bad); sys.exit(1)
PYEOF
[ $? = 0 ] || refuse "data/fit_grader/config.json drifted from jev-1.13.0 / criteria v1 / jev_cutoffs.v1"

jev_one_call() {  # exactly one grader call, in the pinned code, with the freeze env
  env "${FREEZE_ENV[@]}" MS_DATA_DIR="$1" "$PY" - <<'PYEOF'
from src import fit_graded as fg
g = fg.make_grader()
assert g is not None and g.provider == "typesafe", "grader unavailable (key/config/cut-offs)"
print(f"grader: provider={g.provider} model={g.model} criteria={g.crit['_version']} rule={g.rule}")
lvl = g("LLM agents playing repeated public-goods games diverge from human subjects in non-WEIRD samples.",
        "LLM simulations of survey respondents need validation against non-WEIRD human data.")
print(f"ONE Jev call ok: level={lvl} p={g.last['probabilities']} model={g.last.get('model')}")
PYEOF
}

show() {  # /health (build_sha), /status (no model call), queue count; snapshot kept for the result file
  local p=$1
  curl -fsS -m 10 "http://127.0.0.1:$p/health" >"$SNAP.health" 2>/dev/null
  curl -fsS -m 30 "http://127.0.0.1:$p/status" >"$SNAP.status" 2>/dev/null
  curl -fsS -m 10 "http://127.0.0.1:$p/queue" >"$SNAP.queue" 2>/dev/null
  "$PY" - "$SNAP" <<'PYEOF'
import json, sys
b = sys.argv[1]
def j(x):
    try: return json.load(open(f"{b}.{x}"))
    except Exception: return None
h, st, q = j("health"), j("status"), j("queue")
snap = {"health": h, "status": {k: st.get(k) for k in ("scoring_config", "drafting_ok", "drafting_source",
        "drafting_reason", "queue_size", "queue_by_outlet")} if st else None,
        "queue": {"cards": len(q["cards"]), "later": len(q["later"]), "cap": q["cap"]} if q else None}
json.dump(snap, open(b, "w"), indent=1)
print(json.dumps(snap, indent=1))
PYEOF
  rm -f "$SNAP.health" "$SNAP.status" "$SNAP.queue"
  BUILD=$("$PY" -c 'import json,sys;print((json.load(open(sys.argv[1]))["health"] or {}).get("build_sha") or "")' "$SNAP" 2>/dev/null)
  QCOUNT=$("$PY" -c 'import json,sys;q=json.load(open(sys.argv[1]))["queue"];print(q["cards"] if q else "")' "$SNAP" 2>/dev/null)
}

if [ "$DRY" = 1 ]; then
  T=/tmp/freeze946; P=8798; rm -rf "$T"; mkdir -p "$T"
  "$PY" - "$COPY_DB" "$T/db" <<'PYEOF'
import sqlite3, sys, pathlib, shutil
s, d = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]); d.mkdir()
for f in s.iterdir():
    if f.suffix == ".db":
        a = sqlite3.connect(f"file:{f}?mode=ro", uri=True); b = sqlite3.connect(d / f.name); a.backup(b); b.close(); a.close()
    elif f.is_file():
        shutil.copy2(f, d / f.name)
PYEOF
  say "dry run: copy of $COPY_DB at $T/db, pin would be $SHA"
  check_claims "$T/db" || refuse "claims mismatch: copy store != seed at FREEZE_SHA"
  say "archive held (watch) cards on the COPY"; "$PY" scripts/archive_cards.py --data-dir "$T/db" --label archived_at_reset --states watch
  WT=/workspace/ms-worktrees/$SHA
  [ -e "$WT/.git" ] || git worktree add --detach -f "$WT" "$SHA" >/dev/null 2>&1 || { say "git worktree add failed"; exit 1; }
  [ -e "$WT/.venv" ] || ln -s "$REPO/.venv" "$WT/.venv"
  if ss -ltnH "sport = :$P" | grep -q .; then refuse "dry-run port $P is busy"; fi
  say "starting dry server :$P from $WT with the freeze env"
  (cd "$WT" && env "${FREEZE_ENV[@]}" MS_DATA_DIR="$T/db" MS_BUILD_SHA="$SHA" MS_ENSURE_STATUS="$T/status.json" \
     nohup .venv/bin/uvicorn src.api.app:app --host 127.0.0.1 --port $P >"$T/server.log" 2>&1 & echo $! >"$T/pid")
  for _ in $(seq 1 30); do curl -fsS -m 2 "http://127.0.0.1:$P/health" >/dev/null 2>&1 && break; sleep 1; done
  SP=$(ss -ltnpH "sport = :$P" | grep -o "pid=[0-9]*" | head -1 | cut -d= -f2); echo "$SP" >"$T/pid"
  tr '\0' '\n' <"/proc/$SP/environ" | grep -E '^MS_' | sort | sed 's/^/env: /'
  [ -n "$SP" ] || refuse "dry server did not start (see $T/server.log)"
  show $P
  [ "$BUILD" = "$SHA" ] && say "build_sha matches pin" || { kill "$SP"; refuse "dry server build_sha $BUILD != FREEZE_SHA $SHA"; }
  rc=0
  if [ "$JEV" = 1 ]; then (cd "$WT" && jev_one_call "$T/db"); rc=$?; else say "--no-jev: grader call skipped"; fi
  kill "$SP" 2>/dev/null; sleep 1
  ss -ltnH "sport = :$P" | grep -q . && say "WARN: :$P still listening" || say "dry server stopped; :8712 untouched"; exit $rc
fi

check_claims "$COPY_DB" || refuse "claims mismatch: :8712 copy store != seed at FREEZE_SHA"
say "pausing ensure_up for :8712"; echo "freeze_946 $$" >"$LOGDIR/ensure_up.pause.8712"
pid=$(ss -ltnpH 'sport = :8712' | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
[ -n "$pid" ] && { say "stopping :8712 (pid $pid)"; kill "$pid"; sleep 2; }
say "archive held (watch) cards on $COPY_DB"; "$PY" scripts/archive_cards.py --data-dir "$COPY_DB" --label archived_at_reset --states watch
{ printf '%s\n' "${FREEZE_ENV[@]}"; echo "# freeze_946 $(date -Iseconds) pin $SHA"; } >"$LOGDIR/ensure_up.8712.env"
say "env: $(grep -v '^#' "$LOGDIR/ensure_up.8712.env" | tr '\n' ' ')"
mkdir -p data/pins && echo "$SHA" >data/pins/8712.sha && say "pinned :8712 to $SHA"
rm -f "$LOGDIR/ensure_up.pause.8712"
ENSURE_PORTS=8712 scripts/ensure_up.sh; rc=$?
say "ensure_up exit $rc"
show 8712
[ "$BUILD" = "$SHA" ] || { say ":8712 build_sha $BUILD != FREEZE_SHA $SHA"; rc=1; }
exit $rc
