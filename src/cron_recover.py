"""Cron recovery for ensure_up --arm / --cron-check (no shell anywhere; fixed argv; fixed minimal env).

1. If cron isn't running: `sudo -n true` must succeed, then START_ARGV runs. No passwordless sudo -> a failed
   cron heartbeat, so /status warns in plain words. Nothing from the caller's env can change either command.
   Every run writes the `cron` heartbeat (ok or failed); the */15 tick writes `cron_tick` instead.
2. Crontab merge: only lines from scripts/crontab.txt that are missing get appended, written through
   `crontab -` on stdin. Existing (hand-edited) lines are never changed or reordered; the only line ever removed
   is our own retired tick (RETIRED_LINES, exact match after whitespace normalisation, active lines only). Comments in the
   wanted file are never added (comment-only diffs are no-ops), exact duplicates are added once, and malformed
   wanted lines are skipped and logged. A crontab that can't be read (other than "no crontab") is never written.
CLI: python -m src.cron_recover [--pin PIN_SHA_FILE (default data/pins/8710.sha)] [--dir HEARTBEAT_DIR]
   (the wanted crontab is `git show <pinned sha>:scripts/crontab.txt`; never the working tree)  (log lines on stdout; exit 0 ok, 1 fail)
"""
from __future__ import annotations

import fcntl
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from . import heartbeat

ROOT = Path(__file__).resolve().parents[1]
FIXED_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"}
SUDO_CHECK_ARGV = ["/usr/bin/sudo", "-n", "/usr/bin/true"]
START_ARGV = ["/usr/bin/sudo", "-n", "/usr/sbin/service", "cron", "start"]
PGREP_ARGV = ["/usr/bin/pgrep", "-x", "cron|crond"]
CRONTAB_LIST_ARGV = ["/usr/bin/crontab", "-l"]
CRONTAB_LOAD_ARGV = ["/usr/bin/crontab", "-"]
GIT = "/usr/bin/git"
CRONTAB_REL = "scripts/crontab.txt"
DEFAULT_PIN = ROOT / "data" / "pins" / "8710.sha"     # live pin: only a pin move can deploy cron changes
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def git_show_argv(repo: Path, sha: str) -> list[str]:
    return [GIT, "-C", str(repo), "show", f"{sha}:{CRONTAB_REL}"]

_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=")
_SPECIAL_RE = re.compile(r"^@(reboot|yearly|annually|monthly|weekly|daily|midnight|hourly)\s+\S")
_FIELD = r"[0-9A-Za-z*/,\-]+"
_SCHED_RE = re.compile(rf"^{_FIELD}(\s+{_FIELD}){{4}}\s+\S")

Runner = Callable[..., subprocess.CompletedProcess]


def _run(argv: list[str], input_text: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), input=input_text, capture_output=True, text=True, timeout=30,
                          shell=False, env=dict(FIXED_ENV), cwd="/")


def is_comment_or_blank(line: str) -> bool:
    return not line.strip() or line.lstrip().startswith("#")


def is_valid_entry(line: str) -> bool:
    s = line.strip()
    return bool(_ENV_RE.match(s) or _SPECIAL_RE.match(s) or _SCHED_RE.match(s))


def norm(line: str) -> str:
    """Comparison key only (never written): collapse tabs/runs of spaces, drop leading/trailing space."""
    return " ".join(line.split())


# Our own lines that crontab.txt no longer carries and --arm removes. Exact (whitespace-normalised) match only.
RETIRED_LINES = (
    # pre-f531e7e */15 tick: wrote the `cron` job (legacy CLI alias), replaced by the `cron_tick` line
    "*/15 * * * * cd /workspace/marketing-scouter && .venv/bin/python -m src.heartbeat cron ok cron tick >/dev/null 2>&1",
)
_RETIRED = {" ".join(l.split()) for l in RETIRED_LINES}


def drop_retired(current: str) -> tuple[str, list[str]]:
    """-> (current minus retired lines, removed lines). Every other line, comment and byte is kept."""
    kept, removed = [], []
    for line in current.splitlines(keepends=True):
        if not is_comment_or_blank(line) and norm(line) in _RETIRED:
            removed.append(line.rstrip("\r\n"))
        else:
            kept.append(line)
    return "".join(kept), removed


DEFAULT_LOCK = ROOT / "logs" / "cron_recover.lock"
LOCK_WAIT_S = 30.0


class _Lock:
    """Exclusive flock held across crontab read + write, so two --arm/--cron-check runs never interleave."""
    def __init__(self, path: Path, wait_s: Optional[float] = None):
        self.path, self.f = Path(path), None
        self.wait_s = LOCK_WAIT_S if wait_s is None else wait_s

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "a")
        end = time.monotonic() + self.wait_s
        while True:
            try:
                fcntl.flock(self.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() >= end:
                    self.f.close()
                    raise TimeoutError(f"another cron check held {self.path} for over {self.wait_s:g}s")
                time.sleep(0.1)

    def __exit__(self, *exc):
        fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        self.f.close()


def merge(current: str, wanted: str) -> tuple[Optional[str], list[str], list[str]]:
    """-> (new crontab text or None if nothing to change, added lines, skipped malformed wanted lines).
    `current` minus RETIRED_LINES is kept byte-for-byte as the prefix of the new text."""
    current, removed = drop_retired(current)
    have = {norm(l) for l in current.splitlines() if not is_comment_or_blank(l)}
    added, malformed = [], []
    for line in wanted.splitlines():
        if is_comment_or_blank(line):
            continue
        s = line.rstrip()
        if not is_valid_entry(s):
            malformed.append(s)
            continue
        if norm(s) in have:
            continue
        have.add(norm(s))
        added.append(s)
    if not added:
        return (current if removed else None), [], malformed
    base = current if (not current or current.endswith("\n")) else current + "\n"
    return base + "\n".join(added) + "\n", added, malformed


class _CmdError(Exception):
    pass


def recover(wanted_path: Optional[Path] = None, hb_dir: Optional[Path] = None, run: Runner = _run,
            log: Callable[[str], None] = print, lock_path: Optional[Path] = None,
            pin_file: Optional[Path] = None, repo: Path = ROOT) -> bool:
    """wanted_path (tests) or pin_file: with a pin, the wanted crontab is `git show <pinned sha>:scripts/crontab.txt`,
    never the working tree, so a commit to main cannot deploy cron changes. Any read problem fails closed."""
    def fail(msg: str) -> bool:
        log(msg)
        try:
            heartbeat.write("cron", False, msg, directory=hb_dir)
        except Exception as e:  # noqa: BLE001
            log(f"could not write the cron heartbeat: {type(e).__name__}")
        return False

    def ok(msg: str) -> bool:
        try:   # a successful recover is the only thing that clears an earlier failed one
            heartbeat.write("cron", True, msg, directory=hb_dir)
        except Exception as e:  # noqa: BLE001
            log(f"could not write the cron heartbeat: {type(e).__name__}")
        return True

    def call(argv: list[str], what: str, input_text: Optional[str] = None) -> subprocess.CompletedProcess:
        try:
            return run(argv, input_text=input_text) if input_text is not None else run(argv)
        except subprocess.TimeoutExpired:
            raise _CmdError(f"{what} timed out, so cron was left as it was")
        except OSError as e:
            raise _CmdError(f"{what} could not be run ({type(e).__name__}), so cron was left as it was")

    try:
        if call(PGREP_ARGV, "checking whether cron runs").returncode != 0:
            if call(SUDO_CHECK_ARGV, "checking for passwordless sudo").returncode != 0:
                return fail("cron is not running and this box has no passwordless sudo to start it")
            if call(START_ARGV, "starting cron").returncode != 0:
                return fail("cron was not running and starting it failed")
            log("cron was not running; started it")
        if pin_file is not None:
            try:
                sha = Path(pin_file).read_text().strip()
            except (OSError, UnicodeDecodeError) as e:
                return fail(f"could not read the pin {pin_file} ({type(e).__name__}), so cron was left as it was")
            if not _SHA_RE.match(sha):
                return fail(f"the pin {pin_file} holds no valid sha, so cron was left as it was")
            r = call(git_show_argv(repo, sha), "reading the pinned crontab")
            if r.returncode != 0 or not (r.stdout or "").strip():
                return fail(f"pinned commit {sha[:10]} has no readable {CRONTAB_REL}, so cron was left as it was")
            wanted, wanted_path = r.stdout, f"{sha[:10]}:{CRONTAB_REL}"
        elif wanted_path is None:
            return fail("no pin given, so cron was left as it was")
        else:
            try:
                wanted = Path(wanted_path).read_text()
            except (OSError, UnicodeDecodeError) as e:
                return fail(f"could not read {wanted_path} ({type(e).__name__}), so cron was left as it was")
        try:
            lock = _Lock(lock_path or DEFAULT_LOCK)
            lock.__enter__()
        except (TimeoutError, OSError) as e:
            return fail(f"could not lock the crontab: {e}")
        try:
            r = call(CRONTAB_LIST_ARGV, "reading the crontab")
            if r.returncode != 0:
                if "no crontab" not in (r.stderr or "").lower():
                    return fail("could not read the crontab, so it was left unchanged")
                current = ""
            else:
                current = r.stdout or ""
            new, added, malformed = merge(current, wanted)
            for m in malformed:
                log(f"crontab: skipped malformed line from {wanted_path}: {m!r}")
            if new is None:
                return ok("crontab already has every line from scripts/crontab.txt")
            if call(CRONTAB_LOAD_ARGV, "loading the crontab", input_text=new).returncode != 0:
                return fail("could not load scripts/crontab.txt into the crontab")
            log(f"crontab: added {len(added)} missing line(s) from {wanted_path}")
            return ok(f"crontab: added {len(added)} missing line(s)")
        finally:
            lock.__exit__(None, None, None)
    except _CmdError as e:
        return fail(str(e))
    except Exception as e:  # noqa: BLE001  any other surprise (e.g. UnicodeDecodeError) is a plain failure
        return fail(f"cron recovery hit an unexpected error ({type(e).__name__}), so cron was left as it was")


def main(argv: list[str]) -> int:
    opts = {"--pin": str(DEFAULT_PIN), "--dir": None}   # no --crontab: the CLI reads only the pinned commit
    it = iter(argv)
    for a in it:
        if a not in opts:
            print(__doc__, file=sys.stderr)
            return 2
        opts[a] = next(it)
    return 0 if recover(None, Path(opts["--dir"]) if opts["--dir"] else None, pin_file=Path(opts["--pin"])) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
