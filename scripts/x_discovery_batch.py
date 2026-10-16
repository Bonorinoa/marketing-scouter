"""X discovery batch: a fail-closed read gate plus the /intake/x batch builder, with provenance.

The X reads themselves happen in the bot routine (x MCP search_posts_all); the server never calls X.
Every read MUST request the fields in X_READ_ARGS (lang included), e.g. post.fields=created_at,public_metrics,lang.

  check [--first] [LAST_RESULT_FILE]
      Run BEFORE each X read. Parses "N of M today" from the previous read's raw result. Missing or garbled
      count, or N < floor (data/x_scout_queries.v1.json rules.budget.stop_when_remaining_below, default 150)
      => skip: prints {"status":"skip",...}, writes the discovery heartbeat as a deliberate skip
      (shared_x_read_cap), logs `discovery skip shared_x_read_cap`, exit 0. --first allows the run's first read
      (no previous result yet). Otherwise prints {"status":"ok","left":N}.
  build RUN_ID OUT_POSTS.json query_id=result_file ...
      Re-checks every read's count (same fail-closed rule). On skip: no posts file, skip heartbeat, exit 0.
      Else writes the batch (≤50, deduped; posts with no lang are kept for lang_gate; only an explicit non-en
      lang is dropped), saves raw responses to data/x_raw/<run_id>/<query_id>.json, and appends one row per read
      to data/x_reads.jsonl: bot, run_id, query_id, config_sha, results, post_ids (IDs only), reads_left_today.
Stdout is one JSON line with "status": "ok" | "skip".
EXIT CODES: 0 = ok; 4 = deliberate skip (shared_x_read_cap: NOT a failure; the routine must stop reading and
report a skip); 2 = usage / refused input (bad run_id or query_id, path outside data/x_raw).
Count parsing (anti-spoof): only non-JSON lines that START with "X reads left" are read (post text sits in the JSON
line); the LAST such line is used; two lines that disagree, a minus sign, N > M, or >7 digits => skip.
--first is allowed once per run_id (marker data/x_raw/<run_id>/.first); a second --first for the same run => skip.
run_id and query_id must fullmatch [A-Za-z0-9_:-]+.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("MS_DISCOVERY_DATA", ROOT / "data"))
QUERIES = Path(os.environ.get("MS_X_QUERIES", ROOT / "data" / "x_scout_queries.v1.json"))
LEFT_LINE = re.compile(r"^X reads left\b.*?(?<![\w-])(-?\d+) of (-?\d+) today\b")
TOKEN = re.compile(r"[A-Za-z0-9_:-]+")
SKIP_REASON = "shared_x_read_cap"
X_READ_ARGS = {"post.fields": "created_at,public_metrics,lang", "expansions": "author_id", "user.fields": "username",
               "max_results": 25}


def floor() -> int:
    try:
        return int(json.loads(QUERIES.read_text())["rules"]["budget"]["stop_when_remaining_below"])
    except Exception:
        return 150


def remaining(text: str) -> int | None:
    """Remaining reads today from the tool's own count line, or None (=> skip) if absent, ambiguous or absurd."""
    vals = set()
    for line in (text or "").splitlines():
        s = line.strip()
        if not s.startswith("X reads left") or s.startswith("{"):
            continue
        m = LEFT_LINE.match(s)
        if not m:
            return None
        n, tot = m.group(1), m.group(2)
        if n.startswith("-") or tot.startswith("-") or len(n) > 7 or len(tot) > 7 or int(n) > int(tot):
            return None
        vals.add(int(n))
    return vals.pop() if len(vals) == 1 else None


def _skip(run_id: str | None, why: str) -> int:
    detail = f"discovery skip {SKIP_REASON}: {why}" + (f" (run {run_id})" if run_id else "")
    print(detail, file=sys.stderr)
    try:
        subprocess.run([sys.executable, "-m", "src.heartbeat", "discovery", "skip", SKIP_REASON],
                       cwd=ROOT, check=False, timeout=30,
                       env={**os.environ, "PYTHONPATH": str(ROOT)})
    except Exception:  # noqa: BLE001
        pass
    with (DATA / "x_reads.jsonl").open("a") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": "discovery_skip",
                            "reason": SKIP_REASON, "why": why, "run_id": run_id}) + "\n")
    print(json.dumps({"status": "skip", "reason": SKIP_REASON, "why": why}))
    return 4


def _rawdir(run_id: str) -> Path | None:
    """data/x_raw/<run_id>, or None if run_id is not a plain token or would resolve outside data/x_raw."""
    if not TOKEN.fullmatch(run_id or ""):
        return None
    base = (DATA / "x_raw").resolve()
    d = (base / run_id).resolve()
    return d if d.parent == base else None


def _refuse(msg: str) -> int:
    print(json.dumps({"status": "refused", "why": msg}))
    print(msg, file=sys.stderr)
    return 2


def check(args: list[str]) -> int:
    first = "--first" in args
    run_id = None
    rest = []
    it = iter(a for a in args if a != "--first")
    for a in it:
        if a == "--run":
            run_id = next(it, None)
        else:
            rest.append(a)
    files = rest
    if not files:
        if not first:
            return _skip(run_id, "no previous read result to check")
        d = _rawdir(run_id or "")
        if d is None:
            return _refuse("check --first needs --run RUN_ID matching [A-Za-z0-9_:-]+")
        marker = d / ".first"
        if marker.exists():
            return _skip(run_id, "--first already used for this run")
        d.mkdir(parents=True, exist_ok=True)
        marker.write_text(datetime.now(timezone.utc).isoformat(timespec="seconds"))
        print(json.dumps({"status": "ok", "left": None, "first": True}))
        return 0
    rem = remaining(Path(files[0]).read_text() if Path(files[0]).exists() else "")
    if rem is None:
        return _skip(None, "remaining count missing or unreadable")
    if rem < floor():
        return _skip(None, f"{rem} reads left today < floor {floor()}")
    print(json.dumps({"status": "ok", "left": rem}))
    return 0


def build(args: list[str]) -> int:
    if len(args) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    run_id, out = args[0], Path(args[1])
    rawdir = _rawdir(run_id)
    if rawdir is None:
        return _refuse(f"run_id must match [A-Za-z0-9_:-]+ and stay under data/x_raw: {run_id!r}")
    for spec in args[2:]:
        if "=" not in spec or not TOKEN.fullmatch(spec.split("=", 1)[0]):
            return _refuse(f"query_id must match [A-Za-z0-9_:-]+: {spec.split('=', 1)[0]!r}")
    qbytes = QUERIES.read_bytes()
    config_sha = hashlib.sha256(qbytes).hexdigest()
    qs = {q["query_id"]: q for q in json.loads(qbytes)["queries"]}
    reads, raws = [], {}
    for spec in args[2:]:
        qid, f = spec.split("=", 1)
        t = Path(f).read_text()
        rem = remaining(t)
        if rem is None:
            return _skip(run_id, f"remaining count missing or unreadable after {qid}")
        if rem < floor():
            return _skip(run_id, f"{rem} reads left today < floor {floor()} after {qid}")
        m = re.search(r"^\{.*\}$", t, re.M)
        try:
            j = json.loads(m.group(0)) if m else {}
        except ValueError:
            j = {}
        raws[qid] = t
        reads.append((qid, rem, j))
    posts, seen, rows = [], set(), []
    for qid, rem, j in reads:
        data = j.get("data") or []
        users = {u["id"]: u["username"] for u in (j.get("includes") or {}).get("users", [])}
        q = qs.get(qid, {})
        rows.append({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bot": "systems-engineer",
                     "run_id": run_id, "query_id": qid, "config_sha": config_sha, "results": len(data),
                     "post_ids": [str(p.get("id")) for p in data], "reads_left_today": rem})
        for p in data:
            lang = p.get("lang")
            if p["id"] in seen or (lang and lang != "en"):
                continue
            seen.add(p["id"])
            m_ = p.get("public_metrics") or {}
            posts.append({"url": p["url"], "text": p["text"], "author_handle": users.get(p.get("author_id"), ""),
                          "created_at": p.get("created_at"), "reply_count": m_.get("reply_count"),
                          "quote_count": m_.get("quote_count"), "like_count": m_.get("like_count"),
                          "query_id": qid, "lane": q.get("lane"), "source_tag": q.get("source_tag")})
    rawdir.mkdir(parents=True, exist_ok=True)
    for qid, t in raws.items():
        dest = (rawdir / f"{qid}.json").resolve()
        if dest.parent != rawdir:
            return _refuse(f"raw path escapes data/x_raw: {qid!r}")
        dest.write_text(t)
    with (DATA / "x_reads.jsonl").open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    out.write_text(json.dumps(posts[:50], indent=1))
    print(json.dumps({"status": "ok", "posts": len(posts[:50]), "found": len(posts), "reads": len(rows),
                      "config_sha": config_sha}))
    return 0


def main(a: list[str]) -> int:
    if a and a[0] == "check":
        return check(a[1:])
    if a and a[0] == "build":
        return build(a[1:])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
