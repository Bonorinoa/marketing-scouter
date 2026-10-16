#!/usr/bin/env bash
# Idempotent bring-up for Market Scouter. Usage: [MODE=model|either|binary|graded] scripts/up.sh [--check] [--with-test-copy]
# MODE sets MS_FIT_GRADED_MODE for the :8712 test copy only (default model). :8710 never gets it.
# LIVE_PREDRAFT sets MS_INTAKE_PREDRAFT for :8710 (default xbrief; was unset -> core default 'local' = local_template).
# PREDRAFT sets MS_INTAKE_PREDRAFT for the :8712 copy (default xbrief: x-brief -> Hermes -> deepseek-v4-flash).
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS=/workspace/logs
COPY_DIR=/workspace/ms-either-copy/db
CHECK=0; WITH_COPY=0; ONLY=""
COPY_MODE="${MODE:-model}"
case "$COPY_MODE" in model|either|binary|graded) ;; *) echo "bad MODE=$COPY_MODE (model|either|binary|graded)" >&2; exit 2 ;; esac
for a in "$@"; do
  case "$a" in
    --check) CHECK=1 ;;
    --with-test-copy) WITH_COPY=1 ;;
    --only=*) ONLY="${a#--only=}"; [ "$ONLY" = 8712 ] && WITH_COPY=1 ;;  # start just this server (ensure_up.sh)
    -h|--help) echo "usage: $0 [--check] [--with-test-copy]"; exit 0 ;;
    *) echo "unknown arg: $a" >&2; exit 2 ;;
  esac
done

answers() { curl -fsS -m 3 "http://127.0.0.1:$1${2:-/status}" >/dev/null 2>&1; }

status_line() {
  local p=$1 body
  if [ "$p" = 5173 ]; then
    if answers 5173 /; then echo ":5173 up"; else echo ":5173 DOWN"; fi; return
  fi
  if body=$(curl -fsS -m 5 "http://127.0.0.1:$p/status" 2>/dev/null); then
    printf '%s' "$body" | python3 -c "import sys,json;d=json.load(sys.stdin);print(f':$p up queue_size={d.get(\"queue_size\")} drafting_ok={d.get(\"drafting_ok\")}')"
  else
    echo ":$p DOWN"
  fi
}

wait_for() { local p=$1 path=${2:-/status} i; for i in $(seq 1 30); do answers "$p" "$path" && return 0; sleep 1; done; echo "warn: :$p not answering after 30s (see $LOGS)" >&2; }

if [ "$CHECK" = 1 ]; then
  status_line 8710; status_line 5173
  if [ "$WITH_COPY" = 1 ] || answers 8712; then status_line 8712; fi
  exit 0
fi

mkdir -p "$LOGS"
cd "$REPO"

if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import uvicorn, pytest" >/dev/null 2>&1; then
  echo "rebuilding .venv"
  rm -rf .venv
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
  .venv/bin/pip install -q -e .
  .venv/bin/pip install -q pytest
fi
if [ ! -d web/node_modules ]; then echo "npm ci in web/"; (cd web && npm ci --silent); fi

if [ "$WITH_COPY" = 1 ] && [ ! -d "$COPY_DIR" ]; then
  cat >&2 <<MSG
refusing --with-test-copy: $COPY_DIR missing. Create it with:
  mkdir -p /workspace/ms-either-copy && cp -r $REPO/data/db /workspace/ms-either-copy/
  $REPO/.venv/bin/python scripts/backfill_claims.py --data-dir $COPY_DIR --skip econllm_lab --apply
MSG
  exit 1
fi

if { [ -z "$ONLY" ] || [ "$ONLY" = 8710 ]; } && ! answers 8710; then
  echo "starting :8710"
  env -u MS_FIT_GRADED -u MS_FIT_GRADED_MODE -u MS_DATA_DIR MS_FIT_SHADOW=1 MS_INTAKE_PREDRAFT="${LIVE_PREDRAFT:-xbrief}" \
    nohup .venv/bin/uvicorn src.api.app:app --port 8710 >"$LOGS/ms8710.log" 2>&1 &
  wait_for 8710
fi
if [ -z "$ONLY" ] && ! answers 5173 /; then
  echo "starting :5173"
  (cd web && nohup npx vite --host 127.0.0.1 --port 5173 >"$LOGS/web5173.log" 2>&1 &)
  wait_for 5173 /
fi
if [ "$WITH_COPY" = 1 ] && { [ -z "$ONLY" ] || [ "$ONLY" = 8712 ]; } && ! answers 8712; then
  echo "starting :8712 (test copy, MS_FIT_GRADED_MODE=$COPY_MODE)"
  env -u MS_FIT_GRADED MS_DATA_DIR="$COPY_DIR" MS_FIT_GRADED_MODE="$COPY_MODE" MS_INTAKE_PREDRAFT="${PREDRAFT:-xbrief}" \
    nohup .venv/bin/uvicorn src.api.app:app --host 127.0.0.1 --port 8712 >"$LOGS/ms8712.log" 2>&1 &
  wait_for 8712
fi

status_line 8710; status_line 5173
[ "$WITH_COPY" = 1 ] && status_line 8712
# keep-alive: arm the ensure_up loop (no crontab/systemd on the box); --only runs come from that loop itself
[ -z "$ONLY" ] && [ -x "$REPO/scripts/ensure_up.sh" ] && "$REPO/scripts/ensure_up.sh" --arm || true
exit 0
