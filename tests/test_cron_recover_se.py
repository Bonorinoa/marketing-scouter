"""Pinned 2026-10-16: cron recovery (src/cron_recover.py) + cron heartbeat in /status.
Every command goes through an injected fake runner; an autouse guard makes any real subprocess call from
src.cron_recover fail the test, so nothing here can touch the box's cron or crontab."""
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src import cron_recover as cr
from src import heartbeat

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 16, 19, 0, tzinfo=timezone.utc)
REAL_RUN = cr._run   # captured before the guard patches it; only ever called with subprocess.run faked
OURS = (ROOT / "scripts" / "crontab.txt").read_text()


@pytest.fixture(autouse=True)
def no_real_commands(monkeypatch):
    def boom(*a, **k):
        raise AssertionError(f"real command attempted: {a} {k}")
    monkeypatch.setattr(cr, "_run", boom)
    monkeypatch.setattr(cr.subprocess, "run", boom)


@pytest.fixture(autouse=True)
def tmp_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "DEFAULT_LOCK", tmp_path / "cron_recover.lock")


class Fake:
    """Stand-in for every command; records argv and stdin."""
    def __init__(self, cron_running=True, sudo_ok=True, start_ok=True, crontab=None, list_err=None, load_ok=True):
        self.calls, self.cron_running, self.sudo_ok, self.start_ok = [], cron_running, sudo_ok, start_ok
        self.crontab, self.list_err, self.load_ok = crontab, list_err, load_ok

    def __call__(self, argv, input_text=None):
        self.calls.append((list(argv), input_text))
        ok = lambda out="", err="", rc=0: subprocess.CompletedProcess(argv, rc, out, err)
        if argv == cr.PGREP_ARGV:
            return ok(rc=0 if self.cron_running else 1)
        if argv == cr.SUDO_CHECK_ARGV:
            return ok(rc=0 if self.sudo_ok else 1)
        if argv == cr.START_ARGV:
            return ok(rc=0 if self.start_ok else 1)
        if argv == cr.CRONTAB_LIST_ARGV:
            if self.list_err:
                return ok(err=self.list_err, rc=1)
            return ok(out=self.crontab) if self.crontab is not None else ok(err="no crontab for box", rc=1)
        if argv == cr.CRONTAB_LOAD_ARGV:
            if self.load_ok:
                self.crontab = input_text
            return ok(rc=0 if self.load_ok else 1)
        raise AssertionError(f"unexpected argv {argv}")


def _wanted(tmp, text=OURS):
    p = tmp / "crontab.txt"; p.write_text(text); return p


def _entries(text):
    return [l for l in text.splitlines() if not cr.is_comment_or_blank(l)]


# --- the start command is fixed ---
def test_start_argv_hardcoded_absolute_service():
    assert cr.START_ARGV == ["/usr/bin/sudo", "-n", "/usr/sbin/service", "cron", "start"]
    assert cr.SUDO_CHECK_ARGV[0] == "/usr/bin/sudo"
    assert Path("/usr/sbin/service").exists() and Path("/usr/bin/sudo").exists()
    assert all(a.startswith("/") for a in (cr.PGREP_ARGV[0], cr.CRONTAB_LIST_ARGV[0], cr.CRONTAB_LOAD_ARGV[0]))


def test_runner_uses_no_shell_and_fixed_env(monkeypatch):
    seen = {}
    monkeypatch.setattr(cr.subprocess, "run", lambda argv, **k: seen.update(argv=argv, **k) or
                        subprocess.CompletedProcess(argv, 0, "", ""))
    monkeypatch.setenv("PATH", "/tmp/evil:/usr/bin")
    monkeypatch.setenv("SUDO_ASKPASS", "/tmp/evil")
    import inspect
    src = inspect.getsource(cr)
    REAL_RUN(cr.START_ARGV)
    assert seen["argv"] == cr.START_ARGV and seen["shell"] is False
    assert seen["env"] == cr.FIXED_ENV and "/tmp/evil" not in str(seen["env"])
    assert "shell=True" not in src and "os.system" not in src and "Popen" not in src


# --- cron start ---
def test_cron_running_never_calls_sudo(tmp_path):
    f = Fake(crontab=OURS)
    assert cr.recover(_wanted(tmp_path), tmp_path / "hb", run=f, log=lambda m: None)
    assert [c[0] for c in f.calls] == [cr.PGREP_ARGV, cr.CRONTAB_LIST_ARGV]


def test_cron_down_with_sudo_starts_it(tmp_path):
    f = Fake(cron_running=False, crontab=OURS)
    assert cr.recover(_wanted(tmp_path), tmp_path / "hb", run=f, log=lambda m: None)
    assert (cr.START_ARGV, None) in f.calls


def test_cron_down_without_sudo_warns_never_starts_never_touches_crontab(tmp_path):
    f = Fake(cron_running=False, sudo_ok=False, crontab="keep\n")
    assert not cr.recover(_wanted(tmp_path), tmp_path / "hb", run=f, log=lambda m: None)
    assert [c[0] for c in f.calls] == [cr.PGREP_ARGV, cr.SUDO_CHECK_ARGV] and f.crontab == "keep\n"
    w = heartbeat.jobs_block(tmp_path / "hb")["jobs"]["cron"]["warning"]
    assert "no passwordless sudo" in w


def test_start_failure_reported(tmp_path):
    f = Fake(cron_running=False, start_ok=False, crontab=OURS)
    assert not cr.recover(_wanted(tmp_path), tmp_path / "hb", run=f, log=lambda m: None)
    assert "starting it failed" in heartbeat.jobs_block(tmp_path / "hb")["jobs"]["cron"]["warning"]


# --- crontab merge ---
def test_writes_via_stdin_only(tmp_path):
    f = Fake(crontab="0 3 * * * /home/box/other.sh\n")
    assert cr.recover(_wanted(tmp_path), tmp_path / "hb", run=f, log=lambda m: None)
    loads = [c for c in f.calls if c[0] == cr.CRONTAB_LOAD_ARGV]
    assert len(loads) == 1 and loads[0][0] == ["/usr/bin/crontab", "-"] and loads[0][1] == f.crontab


def test_hand_edited_lines_kept_byte_for_byte_and_first(tmp_path):
    hand = ("# my notes\nMAILTO=me\n0 3 * * * /home/box/other.sh   # keep spacing\n"
            "*/15 * * * *   /workspace/marketing-scouter/scripts/ensure_up.sh\nnot a cron line\n")
    f = Fake(crontab=hand)
    assert cr.recover(_wanted(tmp_path), tmp_path / "hb", run=f, log=lambda m: None)
    assert f.crontab.startswith(hand)
    assert all(l in f.crontab.splitlines() for l in _entries(OURS))


def test_no_trailing_newline_in_current_kept(tmp_path):
    new, added, _ = cr.merge("0 3 * * * /x", "0 4 * * * /y\n")
    assert new == "0 3 * * * /x\n0 4 * * * /y\n" and added == ["0 4 * * * /y"]


def test_exact_duplicates_added_once_and_idempotent(tmp_path):
    w = _wanted(tmp_path, "0 4 * * * /y\n0 4 * * * /y\n0 4 * * * /y   \n")
    f = Fake(crontab="")
    assert cr.recover(w, tmp_path / "hb", run=f, log=lambda m: None)
    assert _entries(f.crontab) == ["0 4 * * * /y"]
    n = len(f.calls)
    assert cr.recover(w, tmp_path / "hb", run=f, log=lambda m: None)
    assert not [c for c in f.calls[n:] if c[0] == cr.CRONTAB_LOAD_ARGV]


def test_comment_only_diff_is_noop(tmp_path):
    current = "\n".join(_entries(OURS)) + "\n"            # same entries, no comments
    f = Fake(crontab=current)
    w = _wanted(tmp_path, "# brand new comment\n" + OURS + "\n# another\n   # indented\n\n")
    assert cr.recover(w, tmp_path / "hb", run=f, log=lambda m: None)
    assert not [c for c in f.calls if c[0] == cr.CRONTAB_LOAD_ARGV] and f.crontab == current


def test_malformed_wanted_lines_skipped_and_logged(tmp_path):
    logs = []
    w = _wanted(tmp_path, "rm -rf /\n*/15 * * /x\n@weird /x\n0 4 * * * /y\nFOO=bar\n")
    f = Fake(crontab="")
    assert cr.recover(w, tmp_path / "hb", run=f, log=logs.append)
    assert _entries(f.crontab) == ["0 4 * * * /y", "FOO=bar"]
    bad = [m for m in logs if "skipped malformed" in m]
    assert len(bad) == 3 and any("rm -rf /" in m for m in bad)


def test_unreadable_crontab_never_rewritten(tmp_path):
    f = Fake(list_err="crontab: permission denied")
    assert not cr.recover(_wanted(tmp_path), tmp_path / "hb", run=f, log=lambda m: None)
    assert not [c for c in f.calls if c[0] == cr.CRONTAB_LOAD_ARGV]


def test_no_crontab_loads_ours(tmp_path):
    f = Fake(crontab=None)
    assert cr.recover(_wanted(tmp_path), tmp_path / "hb", run=f, log=lambda m: None)
    assert _entries(f.crontab) == _entries(OURS)


def test_ensure_up_delegates_to_python_module():
    sh = (ROOT / "scripts" / "ensure_up.sh").read_text()
    assert "-m src.cron_recover" in sh and "crontab -" not in sh and "service cron" not in sh


# --- heartbeat / status ---
def test_crontab_has_15min_cron_heartbeat_line():
    assert any(l.startswith("*/15 ") and "src.heartbeat cron_tick ok" in l for l in _entries(OURS))
    assert all(cr.is_valid_entry(l) for l in _entries(OURS))


def test_status_warns_when_cron_heartbeat_over_30_min(tmp_path):
    heartbeat.write("cron_tick", True, "cron tick", directory=tmp_path, sha="s", now=NOW - timedelta(minutes=45))
    b = heartbeat.jobs_block(tmp_path, now=NOW)
    assert b["jobs"]["cron_tick"]["stale"] is True
    assert any("cron scheduler last checked in 45 min ago" in x and "every 15 min" in x for x in b["warnings"])


def test_fresh_cron_heartbeat_no_warning(tmp_path):
    heartbeat.write("cron_tick", True, "cron tick", directory=tmp_path, sha="s", now=NOW - timedelta(minutes=10))
    b = heartbeat.jobs_block(tmp_path, now=NOW)
    assert b["jobs"]["cron_tick"]["stale"] is False and b["jobs"]["cron_tick"]["warning"] is None


def test_never_checked_in_warns(tmp_path):
    assert any("never checked in" in x for x in heartbeat.jobs_block(tmp_path, now=NOW)["warnings"])


def test_status_endpoint_shows_stale_cron_warning(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from src.api.app import create_app
    monkeypatch.delenv("MS_HEARTBEAT_DIR", raising=False)
    d = tmp_path / "copy"
    heartbeat.write("cron_tick", True, "cron tick", directory=d / "heartbeats", sha="s",
                    now=datetime.now(timezone.utc) - timedelta(minutes=50))
    s = TestClient(create_app(str(d))).get("/status").json()
    assert s["jobs"]["cron_tick"]["stale"] is True
    assert any("cron scheduler last checked in" in w for w in s["jobs_warnings"])


# --- AT 2026-10-16 fixes: exceptions, whitespace dupes, lock ---
class Raising(Fake):
    def __init__(self, at, exc, **kw):
        super().__init__(**kw); self.at, self.exc = at, exc

    def __call__(self, argv, input_text=None):
        if argv == self.at:
            self.calls.append((list(argv), input_text))
            raise self.exc
        return super().__call__(argv, input_text)


@pytest.mark.parametrize("at,kw", [
    (cr.PGREP_ARGV, {}), (cr.SUDO_CHECK_ARGV, {"cron_running": False}), (cr.START_ARGV, {"cron_running": False}),
    (cr.CRONTAB_LIST_ARGV, {}), (cr.CRONTAB_LOAD_ARGV, {"crontab": ""}),
])
@pytest.mark.parametrize("exc,word", [(subprocess.TimeoutExpired(["x"], 30), "timed out"),
                                      (FileNotFoundError("x"), "could not be run"), (PermissionError("x"), "could not be run")])
def test_command_exceptions_become_failed_heartbeat(tmp_path, at, kw, exc, word):
    f = Raising(at, exc, **kw)
    assert cr.recover(_wanted(tmp_path), tmp_path / "hb", run=f, log=lambda m: None) is False
    j = heartbeat.jobs_block(tmp_path / "hb")["jobs"]["cron"]
    assert j["ok"] is False and word in j["detail"] and "left as it was" in j["detail"]
    if at != cr.CRONTAB_LOAD_ARGV:
        assert not [c for c in f.calls if c[0] == cr.CRONTAB_LOAD_ARGV]


def test_whitespace_variants_are_duplicates_no_second_reboot(tmp_path):
    ours = _entries(OURS)
    messy = []
    for l in ours:
        parts = l.split(" ")
        messy.append("  " + "\t".join(parts[:2]) + "  " + "  ".join(parts[2:]) + " \t")
    current = "\n".join(messy) + "\n"
    f = Fake(crontab=current)
    assert cr.recover(_wanted(tmp_path), tmp_path / "hb", run=f, log=lambda m: None)
    assert not [c for c in f.calls if c[0] == cr.CRONTAB_LOAD_ARGV] and f.crontab == current
    new, added, _ = cr.merge("\t@reboot   /a/ensure_up.sh --arm\n", "@reboot /a/ensure_up.sh --arm\n")
    assert new is None and added == []


def test_whitespace_dupes_within_wanted_added_once(tmp_path):
    new, added, _ = cr.merge("", "@reboot /a --arm\n@reboot\t/a  --arm\n")
    assert added == ["@reboot /a --arm"]


def test_lock_held_during_read_and_write(tmp_path):
    import fcntl
    lock = tmp_path / "cron_recover.lock"
    held = []

    class Probe(Fake):
        def __call__(self, argv, input_text=None):
            if argv in (cr.CRONTAB_LIST_ARGV, cr.CRONTAB_LOAD_ARGV):
                with open(lock, "a") as g:
                    try:
                        fcntl.flock(g.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB); held.append(False)
                        fcntl.flock(g.fileno(), fcntl.LOCK_UN)
                    except BlockingIOError:
                        held.append(True)
            return super().__call__(argv, input_text)

    f = Probe(crontab="")
    assert cr.recover(_wanted(tmp_path), tmp_path / "hb", run=f, log=lambda m: None)
    assert held == [True, True]
    with open(lock, "a") as g:   # released afterwards
        fcntl.flock(g.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_lock_busy_fails_without_touching_crontab(tmp_path, monkeypatch):
    import fcntl
    monkeypatch.setattr(cr, "LOCK_WAIT_S", 0.3)
    lock = tmp_path / "cron_recover.lock"
    with open(lock, "a") as g:
        fcntl.flock(g.fileno(), fcntl.LOCK_EX)
        f = Fake(crontab="")
        assert cr.recover(_wanted(tmp_path), tmp_path / "hb", run=f, log=lambda m: None) is False
    assert not [c for c in f.calls if c[0] in (cr.CRONTAB_LIST_ARGV, cr.CRONTAB_LOAD_ARGV)]
    assert "could not lock the crontab" in heartbeat.jobs_block(tmp_path / "hb")["jobs"]["cron"]["detail"]


# --- AT should-fix on abd66a7: tick has its own job; any other exception is a failed heartbeat ---
def test_tick_never_clears_failed_recover(tmp_path):
    hb = tmp_path / "hb"
    f = Fake(cron_running=False, sudo_ok=False, crontab="keep\n")
    assert not cr.recover(_wanted(tmp_path), hb, run=f, log=lambda m: None)
    for m in (10, 5, 0):   # several */15 ticks after the failure, via the CLI the crontab uses (old and new form)
        assert heartbeat.main(["cron_tick", "ok", "cron", "tick", "--dir", str(hb)]) == 0
        assert heartbeat.main(["cron", "ok", "cron", "tick", "--dir", str(hb)]) == 0
    b = heartbeat.jobs_block(hb)
    assert b["jobs"]["cron"]["ok"] is False and "no passwordless sudo" in b["jobs"]["cron"]["warning"]
    assert b["jobs"]["cron_tick"]["ok"] is True and b["jobs"]["cron_tick"]["warning"] is None
    assert any("Cron recovery's last run failed" in w for w in b["warnings"])


def test_later_successful_recover_clears_failure(tmp_path):
    hb = tmp_path / "hb"
    assert not cr.recover(_wanted(tmp_path), hb, run=Fake(cron_running=False, sudo_ok=False), log=lambda m: None)
    assert cr.recover(_wanted(tmp_path), hb, run=Fake(crontab=OURS), log=lambda m: None)
    j = heartbeat.jobs_block(hb)["jobs"]["cron"]
    assert j["ok"] is True and j["warning"] is None


def test_recover_job_not_stale_without_tick(tmp_path):
    heartbeat.write("cron", True, "ok", directory=tmp_path, sha="s", now=NOW - timedelta(days=3))
    assert heartbeat.jobs_block(tmp_path, now=NOW)["jobs"]["cron"]["warning"] is None


def test_undecodable_crontab_file_is_failed_heartbeat(tmp_path):
    w = tmp_path / "wanted.txt"; w.write_bytes(b"\xff\xfe\x00bad")
    f = Fake(crontab="keep\n")
    assert cr.recover(w, tmp_path / "hb", run=f, log=lambda m: None) is False
    j = heartbeat.jobs_block(tmp_path / "hb")["jobs"]["cron"]
    assert j["ok"] is False and "UnicodeDecodeError" in j["detail"] and f.crontab == "keep\n"


@pytest.mark.parametrize("exc", [UnicodeDecodeError("utf-8", b"x", 0, 1, "bad"), ValueError("x"), RuntimeError("x")])
def test_any_other_exception_is_failed_heartbeat(tmp_path, exc):
    f = Raising(cr.CRONTAB_LIST_ARGV, exc, crontab="keep\n")
    assert cr.recover(_wanted(tmp_path), tmp_path / "hb", run=f, log=lambda m: None) is False
    j = heartbeat.jobs_block(tmp_path / "hb")["jobs"]["cron"]
    assert j["ok"] is False and type(exc).__name__ in j["detail"] and "left as it was" in j["detail"]
    assert f.crontab == "keep\n" and cr.CRONTAB_LOAD_ARGV not in [c[0] for c in f.calls]


# --- retired legacy tick line (fake crontab only) ---
LEGACY = "*/15 * * * * cd /workspace/marketing-scouter && .venv/bin/python -m src.heartbeat cron ok cron tick >/dev/null 2>&1"
NEW_TICK = "*/15 * * * * cd /workspace/marketing-scouter && .venv/bin/python -m src.heartbeat cron_tick ok cron tick >/dev/null 2>&1"


def _old_installed():
    """The crontab as installed from the pre-f531e7e crontab.txt, plus a hand-edited line."""
    return OURS.replace(NEW_TICK, LEGACY) + "5 4 * * * /home/box/my_own_job.sh\n"


def test_arm_drops_only_the_legacy_tick_line(tmp_path):
    before = _old_installed()
    f = Fake(crontab=before)
    assert cr.recover(_wanted(tmp_path), tmp_path, run=f, log=lambda m: None)
    after = f.crontab
    assert LEGACY not in after and after.count(NEW_TICK) == 1
    import difflib
    d = [l for l in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
         if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    assert d == ["-" + LEGACY, "+" + NEW_TICK]
    assert "5 4 * * * /home/box/my_own_job.sh" in after


def test_legacy_removed_even_when_nothing_to_add(tmp_path):
    f = Fake(crontab=OURS + LEGACY + "\n")
    assert cr.recover(_wanted(tmp_path), tmp_path, run=f, log=lambda m: None)
    assert f.crontab == OURS


@pytest.mark.parametrize("variant", [
    LEGACY.replace(" ", "\t", 3), LEGACY + "   ", LEGACY + "\r",
])
def test_legacy_whitespace_variants_removed(tmp_path, variant):
    f = Fake(crontab=OURS + variant + "\n")
    cr.recover(_wanted(tmp_path), tmp_path, run=f, log=lambda m: None)
    assert "heartbeat cron ok" not in f.crontab


@pytest.mark.parametrize("kept", [
    "# " + LEGACY,                                    # commented out: not active, kept
    LEGACY.replace("*/15", "*/10"),                   # different schedule: not ours exactly
    LEGACY.replace(">/dev/null 2>&1", ">>/tmp/t.log"),
    "*/15 * * * * /usr/bin/heartbeat cron ok cron tick",
])
def test_similar_lines_are_kept(tmp_path, kept):
    f = Fake(crontab=OURS + kept + "\n")
    cr.recover(_wanted(tmp_path), tmp_path, run=f, log=lambda m: None)
    assert (f.crontab or OURS + kept + "\n").count(kept) == 1


def test_crontab_txt_has_no_legacy_line():
    assert LEGACY not in OURS and NEW_TICK in OURS


# --- PIN BLOCKER (SD 10-16): --arm reads crontab.txt from the pinned sha, never the working tree ---
class PinFake(Fake):
    def __init__(self, shown=None, show_rc=0, **kw):
        super().__init__(**kw); self.shown, self.show_rc = shown, show_rc

    def __call__(self, argv, input_text=None):
        if argv[:1] == [cr.GIT]:
            self.calls.append((list(argv), input_text))
            return subprocess.CompletedProcess(argv, self.show_rc, self.shown or "", "" if self.show_rc == 0 else "fatal")
        return super().__call__(argv, input_text)


def _pin(tmp_path, sha="b604c29bbada9f3fa1bd09ad32c1a368f6a9ccb7"):
    p = tmp_path / "8710.sha"; p.write_text(sha + "\n"); return p


def test_pin_crontab_comes_from_git_show_of_pinned_sha(tmp_path):
    f = PinFake(shown="*/5 * * * * /bin/true\n", crontab="")
    assert cr.recover(None, tmp_path / "hb", run=f, log=lambda m: None, pin_file=_pin(tmp_path), repo=Path("/r"))
    assert ([cr.GIT, "-C", "/r", "show", "b604c29bbada9f3fa1bd09ad32c1a368f6a9ccb7:scripts/crontab.txt"], None) in f.calls
    assert f.crontab == "*/5 * * * * /bin/true\n"          # pinned content, not scripts/crontab.txt on main


def test_working_tree_crontab_never_read_with_pin(tmp_path, monkeypatch):
    read = []
    real = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: (read.append(self.name), real(self, *a, **k))[1])
    f = PinFake(shown=OURS, crontab=OURS)
    assert cr.recover(None, tmp_path / "hb", run=f, log=lambda m: None, pin_file=_pin(tmp_path))
    assert "crontab.txt" not in read


@pytest.mark.parametrize("case", ["missing", "bad_sha", "show_fails", "empty_file", "show_raises"])
def test_pin_problems_fail_closed(tmp_path, case):
    pin = tmp_path / "missing.sha" if case == "missing" else _pin(tmp_path, "not a sha; rm -rf" if case == "bad_sha" else "abc1234")
    if case == "show_raises":
        f = Raising([cr.GIT, "-C", str(cr.ROOT), "show", "abc1234:scripts/crontab.txt"], subprocess.TimeoutExpired(["git"], 30), crontab="keep\n")
    else:
        f = PinFake(shown="" if case == "empty_file" else OURS, show_rc=128 if case == "show_fails" else 0, crontab="keep\n")
    assert cr.recover(None, tmp_path / "hb", run=f, log=lambda m: None, pin_file=pin) is False
    j = heartbeat.jobs_block(tmp_path / "hb")["jobs"]["cron"]
    assert j["ok"] is False and "left as it was" in j["detail"]
    assert f.crontab == "keep\n" and cr.CRONTAB_LOAD_ARGV not in [c[0] for c in f.calls]


def test_cli_has_no_working_tree_option(monkeypatch):
    got = {}
    monkeypatch.setattr(cr, "recover", lambda w, d, **k: got.update(w=w, **k) or True)
    assert cr.main([]) == 0 and got["w"] is None and got["pin_file"] == cr.DEFAULT_PIN
    assert cr.main(["--crontab", "scripts/crontab.txt"]) == 2


def test_ensure_up_arm_passes_the_live_pin():
    sh = (ROOT / "scripts" / "ensure_up.sh").read_text()
    assert 'src.cron_recover --pin "${CRON_PIN_FILE:-$PINS/8710.sha}"' in sh and "--crontab" not in sh
