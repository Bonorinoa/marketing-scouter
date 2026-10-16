#!/usr/bin/env bash
# On-demand drafting probe: forces ONE real test draft (x-brief model call) on a server. Never run by the
# ensure_up loop or /health. Usage: scripts/probe_draft.sh [port=8712]
p="${1:-8712}"
curl -fsS -m 600 "http://127.0.0.1:$p/status?probe=draft" | python3 -c '
import sys, json; d = json.load(sys.stdin)
print(json.dumps({k: d.get(k) for k in ("drafting_ok", "probe_draft_produced", "drafting_source", "drafting_reason", "drafting_checked_at")}, indent=1))'
