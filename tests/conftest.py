import os
import socket
import sqlite3
import tempfile
from pathlib import Path

import pytest

# Must run before any test module imports src.api.app, whose module-level
# `app = create_app()` would otherwise open (and seed/backfill) the live data/db.
_TEST_DATA = tempfile.mkdtemp(prefix="ms-test-data-")
os.environ["MS_DATA_DIR"] = _TEST_DATA
# account lists are gitignored (real handles); tests use made-up fixtures so fresh clones pass
# the real style guide is gitignored; drafting tests use a made-up one
os.environ["MS_STYLE_FILE"] = str(Path(__file__).resolve().parent / "fixtures" / "style_test.md")
os.environ["MS_ACCOUNTS_DIR"] = str(Path(__file__).resolve().parent / "fixtures" / "accounts")
# the made-up guide gets its own 'test' style version with its pinned sha (real v1/v2 pins are untouched)
os.environ["MS_STYLE_VERSION"] = "test"
LIVE_DB_DIR = (Path(__file__).resolve().parent.parent / "data" / "db").resolve()

import src.store as _store  # noqa: E402
_store._DEFAULT_DB = Path(_TEST_DATA) / "scouter.db"

import hashlib as _hashlib  # noqa: E402
import src.api.xbrief_bridge as _xb  # noqa: E402
_xb.EXPECTED_STYLE_SHA["test"] = _hashlib.sha256(Path(os.environ["MS_STYLE_FILE"]).read_bytes()).hexdigest()

_real_connect = sqlite3.connect


def _guarded_connect(database, *a, **k):
    if isinstance(database, (str, os.PathLike)) and str(database) != ":memory:":
        if Path(database).resolve().is_relative_to(LIVE_DB_DIR):
            raise AssertionError(f"test opened the live store: {database}")
    return _real_connect(database, *a, **k)


sqlite3.connect = _guarded_connect

import src.win_evidence as we  # noqa: E402

FAKE_DNS: dict[str, list[str]] = {}


def fake_resolver(host: str) -> list[str]:
    """No network: public test address unless a test maps the host."""
    if host in FAKE_DNS:
        v = FAKE_DNS[host]
        if isinstance(v, Exception):
            raise v
        return v
    return ["93.184.216.34"]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch, tmp_path):
    """Tests never hit the Wayback Machine or real DNS."""
    monkeypatch.setenv("MS_ARCHIVER", "off")
    monkeypatch.setenv("MS_LANG_CAP", "off")
    # x-brief bridge: per-draft run dirs + vault/config sources under tmp, never the real ones
    _cfg = tmp_path / "xb-src" / "config"
    _cfg.mkdir(parents=True, exist_ok=True)
    (_cfg / "config.yaml").write_text("hermes:\n  model: \"test/model\"\n")
    monkeypatch.setenv("MS_XBRIEF_CONFIG", str(_cfg / "config.yaml"))
    monkeypatch.setenv("MS_XBRIEF_VAULT", str(tmp_path / "xb-src" / "vault"))
    monkeypatch.setenv("MS_XBRIEF_RUNS", str(tmp_path / "xb-runs"))   # legacy fixtures are short English; tests/test_lang_cap_se.py turns it on
    monkeypatch.setenv("MS_DATA_DIR", str(tmp_path / "ms-data"))
    monkeypatch.delenv("MS_GOOGLE_SHEETS_CONNECTION", raising=False)
    monkeypatch.setattr(we, "getaddrinfo_resolver", fake_resolver)

    def boom(*a, **k):
        raise AssertionError("real DNS lookup attempted in tests")
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket, "gethostbyname", boom)
    FAKE_DNS.clear()
    yield
    FAKE_DNS.clear()
