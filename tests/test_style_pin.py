"""Blocker 2 (AT on f27e221): the style guide must match the sha pinned for the active style version."""
import hashlib

import pytest
from fastapi.testclient import TestClient

import src.api.xbrief_bridge as xb
from src.api.app import create_app

D = {"door": "EconLLM", "url": "https://x.com/fixture_user_54/status/1", "text": "t"}


def _never_run(*a, **k):
    raise AssertionError("model/x-brief must not run when the style check fails")


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    """A made-up v1/v2 pair; v1 pinned to its sha, v2 left unset (as in production)."""
    v1, v2 = tmp_path / "style_augusto.v1.md", tmp_path / "style_augusto.v2.md"
    v1.write_text("made-up v1 guide"); v2.write_text("made-up v2 guide")
    monkeypatch.setitem(xb.EXPECTED_STYLE_SHA, "v1", hashlib.sha256(b"made-up v1 guide").hexdigest())
    monkeypatch.setitem(xb.EXPECTED_STYLE_SHA, "v2", None)
    monkeypatch.setenv("MS_STYLE_VERSION", "v1")
    monkeypatch.setenv("MS_STYLE_FILE", str(v1))
    monkeypatch.setattr(xb, "run", _never_run)
    return v1, v2


def test_production_pins():
    assert xb.EXPECTED_STYLE_SHA["v1"] == "2b1b3c86738630f47f7cc3bd86e4d3694fb303752b8f8891049dbbba46e8cb16"
    assert xb.EXPECTED_STYLE_SHA["v2"] is None          # v2 unapproved: unset, not selectable
    assert xb.DEFAULT_STYLE == "v1"


def test_matching_v1_is_ok(pinned):
    i = xb.style_info()
    assert i["style_ok"] is True and i["style_active"] == "v1" and i["style_source"] == "bridge"


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_wrong_sha_fails_each_version(pinned, monkeypatch, version, tmp_path):
    v1, v2 = pinned
    monkeypatch.setenv("MS_STYLE_VERSION", version)
    monkeypatch.setenv("MS_STYLE_FILE", str(v1 if version == "v1" else v2))
    monkeypatch.setitem(xb.EXPECTED_STYLE_SHA, version, "0" * 64)   # deliberately wrong
    r = xb.draft(D)
    assert r["status"] == "error" and r["code"] == "style_mismatch" and r["draft_text"] is None


def test_v2_selected_with_unset_sha_is_mismatch(pinned, monkeypatch):
    _v1, v2 = pinned
    monkeypatch.setenv("MS_STYLE_VERSION", "v2"); monkeypatch.setenv("MS_STYLE_FILE", str(v2))
    assert xb.style_info()["style_ok"] is False
    assert xb.draft(D)["code"] == "style_mismatch"


def test_unknown_version_is_mismatch(pinned, monkeypatch):
    monkeypatch.setenv("MS_STYLE_VERSION", "v9")
    assert xb.draft(D)["code"] == "style_mismatch"


def test_edited_file_is_mismatch(pinned):
    v1, _ = pinned
    v1.write_text("made-up v1 guide + an edit")
    assert xb.draft(D)["code"] == "style_mismatch"


def test_empty_file_is_mismatch_even_if_pinned_to_empty(pinned, monkeypatch):
    v1, _ = pinned
    v1.write_text("")
    monkeypatch.setitem(xb.EXPECTED_STYLE_SHA, "v1", hashlib.sha256(b"").hexdigest())
    assert xb.draft(D)["code"] == "style_mismatch"
    v1.write_text("  \n")
    monkeypatch.setitem(xb.EXPECTED_STYLE_SHA, "v1", hashlib.sha256(b"  \n").hexdigest())
    assert xb.draft(D)["code"] == "style_mismatch"


def test_v2_symlink_to_v1_fails_when_v2_selected(pinned, monkeypatch, tmp_path):
    v1, _ = pinned
    link = tmp_path / "linkdir"; link.mkdir()
    l2 = link / "style_augusto.v2.md"; l2.symlink_to(v1)
    monkeypatch.setitem(xb.EXPECTED_STYLE_SHA, "v2", "f" * 64)
    monkeypatch.setenv("MS_STYLE_VERSION", "v2"); monkeypatch.setenv("MS_STYLE_FILE", str(l2))
    i = xb.style_info()
    assert i["style_version"] == "style_augusto.v1" and i["style_ok"] is False
    assert xb.draft(D)["code"] == "style_mismatch"


def test_isolation_off_reads_xbrief_file_and_is_reported(pinned, monkeypatch, tmp_path):
    xs = tmp_path / "x-style.md"; xs.write_text("x-brief default style")   # not the pinned guide
    monkeypatch.setenv("MS_XBRIEF_ISOLATE", "0"); monkeypatch.setenv("MS_XBRIEF_STYLE", str(xs))
    i = xb.style_info()
    assert i["style_source"] == "xbrief_default" and i["style_ok"] is False
    r = xb.draft(D)
    assert r["code"] == "style_mismatch" and "xbrief_default" in r["detail"]


def test_health_red_on_mismatch_and_green_on_match(pinned, tmp_path):
    v1, _ = pinned
    h = TestClient(create_app(str(tmp_path / "d1"))).get("/health").json()
    assert h["style_ok"] is True and h["style_active"] == "v1"
    v1.write_text("tampered")
    h = TestClient(create_app(str(tmp_path / "d2"))).get("/health").json()
    assert h["style_ok"] is False and h["ok"] is False and h["style_file_present"] is True


def _run_env(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"; cfg.mkdir()
    (cfg / "config.yaml").write_text("model: x\n")
    monkeypatch.setenv("MS_XBRIEF_CONFIG", str(cfg / "config.yaml"))
    monkeypatch.setenv("MS_XBRIEF_VAULT", str(tmp_path / "vault"))
    monkeypatch.setenv("MS_XBRIEF_RUNS", str(tmp_path / "runs"))


def test_run_dir_gets_a_copy_of_the_hashed_bytes_not_a_link(pinned, tmp_path, monkeypatch):
    v1, _ = pinned
    _run_env(tmp_path, monkeypatch)
    seen = {}
    real = xb.make_run_dir

    def spy(*a, **k):
        proj, vault = real(*a, **k)
        v1.write_text("swapped after the check")          # swap the source right after the run dir is built
        seen["dst"] = proj / "config" / "x-style.md"
        raise RuntimeError("stop before running x-brief")
    monkeypatch.setattr(xb, "make_run_dir", spy)
    try:
        xb.draft(D)
    except RuntimeError:
        pass
    dst = seen["dst"]
    assert not dst.is_symlink() and dst.read_bytes() == b"made-up v1 guide"


def test_draft_copies_bytes_it_hashed_even_if_file_changes_between(pinned, tmp_path, monkeypatch):
    v1, _ = pinned
    _run_env(tmp_path, monkeypatch)
    real_read = xb._read_style

    def read_then_swap():
        out = real_read()
        v1.write_text("swapped between hash and copy")
        return out
    monkeypatch.setattr(xb, "_read_style", read_then_swap)
    got = {}
    real = xb.make_run_dir

    def spy(*a, **k):
        proj, _v = real(*a, **k)
        got["b"] = (proj / "config" / "x-style.md").read_bytes()
        raise RuntimeError("stop")
    monkeypatch.setattr(xb, "make_run_dir", spy)
    try:
        xb.draft(D)
    except RuntimeError:
        pass
    assert got["b"] == b"made-up v1 guide"


def test_dangling_symlink_fails_closed(pinned, tmp_path, monkeypatch):
    link = tmp_path / "dangling.md"; link.symlink_to(tmp_path / "nowhere.md")
    monkeypatch.setenv("MS_STYLE_FILE", str(link))
    i = xb.style_info()
    assert i["style_file_present"] is False and i["style_ok"] is False
    r = xb.draft(D)
    assert r["status"] == "error" and r["code"] == "style_missing" and r["draft_text"] is None
