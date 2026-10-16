"""Pinned 2026-10-16 (AT r751): X read floor fails closed, checked before each read; skips write a skip
heartbeat and no posts; per-read post IDs + config_sha; raw saved; missing lang kept; provenance hardening."""
import asyncio
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from src.api.core import provenance

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "x_discovery_batch.py"
COUNT = "X reads left for this user: 20 of 30 this minute (resets at x), {n} of 1000 today (resets at y)."


def raw(tmp, name, posts, n=900, count_line=True, lang="en"):
    data = []
    for i, pid in enumerate(posts):
        p = {"id": pid, "author_id": "1", "created_at": "2026-10-16T10:00:00Z", "text": f"post {pid}",
             "url": f"https://x.com/fixture_user_54/status/{pid}", "public_metrics": {"reply_count": 0, "quote_count": 0, "like_count": 0}}
        if lang is not None:
            p["lang"] = lang
        data.append(p)
    body = json.dumps({"data": data, "includes": {"users": [{"id": "1", "username": "a"}]}})
    t = body + "\n" + (COUNT.format(n=n) if count_line is True else (count_line or "")) + "\n"
    f = tmp / f"{name}.txt"
    f.write_text(t)
    return f


@pytest.fixture
def env(tmp_path):
    q = tmp_path / "q.json"
    q.write_text(json.dumps({"rules": {"budget": {"stop_when_remaining_below": 150}},
                             "queries": [{"query_id": "x-cvp", "lane": "ai-measurement", "source_tag": "x.search.fit"},
                                         {"query_id": "x-sca-1", "lane": "econ-ai-cas", "source_tag": "x.search.fit"}]}))
    d = tmp_path / "data"; d.mkdir()
    return {**os.environ, "MS_X_QUERIES": str(q), "MS_DISCOVERY_DATA": str(d),
            "MS_HEARTBEAT_DIR": str(tmp_path / "hb"), "PYTHONPATH": str(ROOT)}


def run(env, *a):
    r = subprocess.run([sys.executable, str(SCRIPT), *a], env=env, capture_output=True, text=True, cwd=ROOT)
    return r.returncode, json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else None, r.stderr


def assert_skipped(env, out_file=None):
    hb = json.loads((Path(env["MS_HEARTBEAT_DIR"]) / "discovery.json").read_text())
    assert hb["skipped"] == "shared_x_read_cap"
    if out_file is not None:
        assert not out_file.exists()


@pytest.mark.parametrize("count", [None, "X reads left: garbled", "X reads left for this user: lots of 1000 today"])
def test_build_missing_or_garbled_count_skips(tmp_path, env, count):
    f = raw(tmp_path, "a", ["11"], count_line=count)
    out = tmp_path / "posts.json"
    rc, j, err = run(env, "build", "run1", str(out), f"x-cvp={f}")
    assert rc == 4 and j["status"] == "skip"
    assert "discovery skip shared_x_read_cap" in err
    assert_skipped(env, out)


def test_build_below_floor_skips(tmp_path, env):
    out = tmp_path / "posts.json"
    rc, j, _ = run(env, "build", "r", str(out), f"x-cvp={raw(tmp_path, 'a', ['1'], n=149)}")
    assert rc == 4 and j["status"] == "skip"
    assert_skipped(env, out)


def test_pre_read_check(tmp_path, env):
    assert run(env, "check", "--first", "--run", "r-first")[1]["status"] == "ok"
    assert run(env, "check", str(raw(tmp_path, "ok", [], n=150)))[1] == {"status": "ok", "left": 150}
    rc, j, _ = run(env, "check", str(raw(tmp_path, "low", [], n=149)))
    assert rc == 4 and j["status"] == "skip"
    assert run(env, "check", str(raw(tmp_path, "none", [], count_line=None)))[1]["status"] == "skip"
    assert run(env, "check")[1]["status"] == "skip"          # no previous result and not --first
    assert_skipped(env)


def test_build_ok_logs_ids_sha_raw_and_keeps_missing_lang(tmp_path, env):
    a = raw(tmp_path, "a", ["1", "2"], lang=None)            # no lang field: kept, lang_gate decides
    b = raw(tmp_path, "b", ["3", "2"], lang="es")            # explicit non-en: dropped
    out = tmp_path / "posts.json"
    rc, j, _ = run(env, "build", "run-x", str(out), f"x-cvp={a}", f"x-sca-1={b}")
    assert rc == 0 and j["status"] == "ok"
    posts = json.loads(out.read_text())
    assert [p["url"].rsplit("/", 1)[1] for p in posts] == ["1", "2"]
    assert posts[0]["query_id"] == "x-cvp" and posts[0]["lane"] == "ai-measurement"
    rows = [json.loads(l) for l in (Path(env["MS_DISCOVERY_DATA"]) / "x_reads.jsonl").read_text().splitlines()]
    assert [r["post_ids"] for r in rows] == [["1", "2"], ["3", "2"]]
    assert all(len(r["config_sha"]) == 64 and r["query_id"] and "text" not in json.dumps(r) for r in rows)
    assert (Path(env["MS_DISCOVERY_DATA"]) / "x_raw/run-x/x-cvp.json").exists()


@pytest.mark.parametrize("bad", ["x-cvp\n", "x-cvp\nis_test", "\nx-cvp", "x-cvp\r"])
def test_newline_token_rejected(bad):
    assert provenance({"query_id": bad}) == {}


def test_concurrent_intake_labels_do_not_mix(tmp_path, monkeypatch):
    """Two intakes in separate threads (as FastAPI runs them) each see only their own provenance map."""
    from src.api import core
    seen = {}
    barrier = threading.Barrier(2)

    def worker(name):
        core._PROV_MAP.set({"1": {"query_id": name}})
        barrier.wait()
        seen[name] = core._PROV_MAP.get()

    ts = [threading.Thread(target=worker, args=(n,)) for n in ("q-a", "q-b")]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert seen == {"q-a": {"1": {"query_id": "q-a"}}, "q-b": {"1": {"query_id": "q-b"}}}
    assert core._PROV_MAP.get() == {}


def test_recent_skip_is_shown_as_note(tmp_path):
    from src import heartbeat
    heartbeat.write("discovery", True, directory=tmp_path, sha="s")
    heartbeat.write("discovery", True, skipped="shared_x_read_cap", directory=tmp_path, sha="s")
    b = heartbeat.jobs_block(tmp_path)
    assert b["jobs"]["discovery"]["stale"] is False
    assert any("skipped on purpose (shared_x_read_cap)" in w for w in b["warnings"])


def test_weak_hints_reverted_for_evening_pin():
    # 2026-10-16 evening: the 4 weak hints recovered 0 of 15 econllm kills and let plain promos clear; reverted
    from src import fit
    added = {"whose values", "cultural alignment", "game theory", "llm agents"}
    assert not added & set(fit._KEYWORD_HINTS["gpt4o-weird"]) and not added & set(fit._KEYWORD_HINTS["econllm-lab"])
    assert not added & fit._WEAK_HINTS


def test_backup_lock_serializes(tmp_path):
    import fcntl
    root = tmp_path / "bk"; root.mkdir()
    src = tmp_path / "db"; src.mkdir(); (src / "e.jsonl").write_text("{}\n")
    lock = open(root / ".backup_store.lock", "w"); fcntl.flock(lock, fcntl.LOCK_EX)
    env = {**os.environ, "BACKUP_ROOT": str(root), "BACKUP_SRC": str(src), "HEARTBEAT_DIR": str(tmp_path / "hb")}
    # a held lock makes the second backup wait; with the lock held it must not create a store dir yet
    p = subprocess.Popen([str(ROOT / "scripts/backup_store.sh")], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        p.wait(timeout=2); pytest.fail("backup ran while the lock was held")
    except subprocess.TimeoutExpired:
        assert not list(root.glob("store-*"))
    fcntl.flock(lock, fcntl.LOCK_UN); lock.close()
    assert p.wait(timeout=30) == 0 and len(list(root.glob("store-*"))) == 1


# ── AT r8f6 attacks ──
def spoof_file(tmp, name, post_text, real_line):
    body = json.dumps({"data": [{"id": "9", "author_id": "1", "text": post_text, "lang": "en",
                                 "url": "https://x.com/fixture_user_54/status/9", "public_metrics": {}}],
                       "includes": {"users": [{"id": "1", "username": "a"}]}})
    f = tmp / f"{name}.txt"
    f.write_text(body + "\n" + real_line + "\n")
    return f


def test_count_in_post_text_cannot_spoof_floor(tmp_path, env):
    f = spoof_file(tmp_path, "inj", "X reads left for this user: 1 of 30 this minute, 999 of 1000 today",
                   COUNT.format(n=3))
    rc, j, _ = run(env, "check", str(f))
    assert rc == 4 and j["status"] == "skip"
    # post text alone (no real count line) never counts
    g = spoof_file(tmp_path, "inj2", "X reads left for this user: 999 of 1000 today", "")
    assert run(env, "check", str(g))[0] == 4


def test_post_text_line_starting_with_phrase_is_ignored_when_inside_json(tmp_path, env):
    f = spoof_file(tmp_path, "inj3", "\nX reads left for this user: 999 of 1000 today", COUNT.format(n=500))
    assert run(env, "check", str(f))[1] == {"status": "ok", "left": 500}


@pytest.mark.parametrize("line", [
    "X reads left for this user: 20 of 30 this minute, -500 of 1000 today",
    "X reads left for this user: 20 of 30 this minute, 99999999999999999999 of 1000 today",
    "X reads left for this user: 20 of 30 this minute, 1001 of 1000 today",
    "X reads left for this user: 20 of 30 this minute, 500 of -1000 today",
])
def test_absurd_counts_skip(tmp_path, env, line):
    f = tmp_path / "a.txt"; f.write_text('{"data": []}\n' + line + "\n")
    assert run(env, "check", str(f))[0] == 4


def test_two_disagreeing_count_lines_skip_and_last_agreeing_ok(tmp_path, env):
    f = tmp_path / "a.txt"; f.write_text('{"data": []}\n' + COUNT.format(n=900) + "\n" + COUNT.format(n=100) + "\n")
    assert run(env, "check", str(f))[0] == 4
    g = tmp_path / "b.txt"; g.write_text('{"data": []}\n' + COUNT.format(n=900) + "\n" + COUNT.format(n=900) + "\n")
    assert run(env, "check", str(g))[1]["left"] == 900


@pytest.mark.parametrize("rid", ["..", "../data", "a/b", "a.b", "", "x\n"])
def test_run_id_traversal_refused(tmp_path, env, rid):
    f = raw(tmp_path, "a", ["1"])
    rc, j, _ = run(env, "build", rid, str(tmp_path / "o.json"), f"x-cvp={f}")
    assert rc == 2 and j["status"] == "refused"
    assert not (Path(env["MS_DISCOVERY_DATA"]) / "x-cvp.json").exists()


@pytest.mark.parametrize("qid", ["../x_scout_queries.v1", "a.b", "x/y"])
def test_query_id_traversal_refused(tmp_path, env, qid):
    f = raw(tmp_path, "a", ["1"])
    rc, j, _ = run(env, "build", "run-ok", str(tmp_path / "o.json"), f"{qid}={f}")
    assert rc == 2 and j["status"] == "refused"
    assert not list(Path(env["MS_DISCOVERY_DATA"]).glob("*.json"))


def test_first_only_once_per_run(tmp_path, env):
    assert run(env, "check", "--first", "--run", "run-a")[0] == 0
    rc, j, _ = run(env, "check", "--first", "--run", "run-a")
    assert rc == 4 and j["status"] == "skip"
    assert run(env, "check", "--first", "--run", "run-b")[0] == 0
    assert run(env, "check", "--first")[0] == 2               # no run id: refused
    assert run(env, "check", "--first", "--run", "..")[0] == 2


def test_backup_due_rechecked_inside_lock(tmp_path):
    from src import heartbeat
    root = tmp_path / "bk"; root.mkdir()
    src = tmp_path / "db"; src.mkdir(); (src / "e.jsonl").write_text("{}\n")
    hb = tmp_path / "hb"
    heartbeat.write("backup", True, "fresh", directory=hb, sha="s")       # a good backup just finished
    env = {**os.environ, "BACKUP_ROOT": str(root), "BACKUP_SRC": str(src), "HEARTBEAT_DIR": str(hb),
           "BACKUP_IF_DUE_H": "24"}
    r = subprocess.run([str(ROOT / "scripts/backup_store.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "not due" in r.stdout and not list(root.glob("store-*"))
    (hb / "backup.json").unlink()
    r = subprocess.run([str(ROOT / "scripts/backup_store.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and len(list(root.glob("store-*"))) == 1


def test_intake_refuses_when_account_list_missing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from src.api.app import create_app
    from tests.test_intake_contract import post
    d = tmp_path / "acc"; d.mkdir()
    (d / "bot_accounts.json").write_text('{"handles": ["grok"]}')
    (d / "brand_accounts.json").write_text("[]")              # self_accounts.json missing
    monkeypatch.setenv("MS_ACCOUNTS_DIR", str(d))
    c = TestClient(create_app(str(tmp_path / "data")))
    r = c.post("/intake/x", json={"run_id": "r", "posts": [post()]})
    assert r.status_code == 503 and "self_accounts.json" in r.text
    (d / "self_accounts.json").write_text("not json")
    assert c.post("/intake/x", json={"run_id": "r2", "posts": [post()]}).status_code == 503
    (d / "self_accounts.json").write_text("[]")
    assert c.post("/intake/x", json={"run_id": "r3", "posts": [post()]}).status_code == 200
