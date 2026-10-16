"""scripts/scrub_check.py + build_public_tree. All data is made up; every planted leak below is a fake that
scripts/scrub_allow.json lists by exact string, so the real public tree stays clean while these tests prove
each leak class is caught (AT scrub attack 10-16: 77 planted leaks)."""
import base64
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts import build_public_tree as bpt
from scripts import scrub_check as sc

POST = ("the quarterly widget survey shows that seventeen purple llamas prefer jazz over polka "
        "when the moon is full and the coffee is cold")
HANDLES = {"fakebotzz", "fakebrandqq", "theholy_hermit"}
H = "someonefake"
SID = "1849999999999999999"
KEY = "sk-or-v1-abcdefabcdefabcdef0123"
SELF, GROK = "@theholy_hermit", "@grok"
NOALLOW = {"entries": set()}


def corpus():
    w = sc.words(POST)
    return {hash(tuple(w[i:i + 12])) for i in range(len(w) - 11)}


def run(tmp_path, files, allow=(), repo=None, allow_strings=None):
    tree = tmp_path / "tree"
    tree.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        p = tree / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        (p.write_bytes if isinstance(body, bytes) else p.write_text)(body)
    return sc.check(tree, repo or tmp_path / "norepo", allow, corpus(), HANDLES, allow_strings or NOALLOW,
                    log=lambda m: None)


def rules(found):
    return sorted({f.rule for f in found})


def test_clean_tree_passes(tmp_path):
    assert run(tmp_path, {"src/a.py": "@dataclass\nclass A: pass\n# ping @theholy_hermit\n",
                          "README.md": "meet @ 5pm, issue #42, mail me at a@example.com, see @fixture_user_01",
                          "web/package.json": '{"devDependencies": {"@vitejs/plugin-react": "1", "@testing-library/react": "1"}}',
                          "web/src/a.tsx": 'import { render } from "@testing-library/react";\n',
                          "src/s.css": "@media (max-width: 1px) {}", "tests/x.py": "x.com/i/status/1",
                          "tests/y.py": "https://x.com/fixture_user_02/status/9000000000000000001"}) == []


@pytest.mark.parametrize("text,rule", [
    # status URLs: hosts, /i/web/, nitter, percent-encoded, bare snowflake
    (f"https://x.com/{H}/status/{SID}", "x_status_url"),
    (f"twitter.com/{H}/status/{SID}", "x_status_url"),
    (f"https://twitter.com/i/web/status/{SID}", "x_status_url"),
    (f"https://nitter.net/{H}/status/{SID}", "x_status_url"),
    (f"https://nitter.poast.org/{H}/status/{SID}", "x_status_url"),
    (f"https://fxtwitter.com/{H}/status/{SID}", "x_status_url"),
    (f"https%3A%2F%2Fx.com%2F{H}%2Fstatus%2F{SID}", "x_status_url"),
    (f"post id {SID} from the run", "snowflake_id"),
    # profile paths
    (f"https://x.com/{H}", "x_handle_path"), (f"https://fxtwitter.com/{H}", "x_handle_path"),
    (f"https://vxtwitter.com/{H}", "x_handle_path"), (f"https://nitter.net/{H}", "x_handle_path"),
    # handles in every disguise
    (f"hi @{H}", "handle"), (f"hi \uff20{H}", "handle"), ("hi @some\u200bonefake", "handle"),
    (f"hi &#64;{H}", "handle"), (f"hi \\u0040{H}", "handle"), (f"hi %40{H}", "handle"),
    (f"hi @{H}/thread", "handle"), (f"hi {SELF}X", "handle"), (f"hi {GROK}X", "handle"),
    ("ping @\nsomeonefake", "split_handle"), ("ping @fakeb\notzz", "split_handle"),
    ('{"handles": ["fakebotzz"]}', "account_list_handle"),
    # keys, incl. across string concatenation
    (f"key {KEY}", "openrouter_key"), ('k = "sk-" + "or-v1-abcdefabcdefabcdef0123"', "openrouter_key"),
    ('k = ("sk-or-"\n     "v1-abcdefabcdefabcdef0123")', "openrouter_key"),
    ("SUBQ_API_KEY=abcd1234efgh5678", "subq_key"),
    # emails, incl. obfuscated
    ("write to someone@realmail.org", "email"), ("write to someone\\u0040realmail.org", "email"),
    ("someone%40realmail.org", "email"), ("someone at realmail dot org", "email_obfuscated"),
    ("someone [at] realmail [dot] org", "email_obfuscated"),
])
def test_text_rules_fail(tmp_path, text, rule):
    assert rule in rules(run(tmp_path, {"docs/x.md": text}))


def test_python_line_start_at_in_docstring_is_a_handle(tmp_path):
    assert "handle" in rules(run(tmp_path, {"src/a.py": f'"""\n@{H} said so\n"""\n'}))


def test_self_handle_exact_only(tmp_path):
    assert run(tmp_path, {"docs/x.md": "by @theholy_hermit."}) == []


def _allow(*ents):
    return {"entries": {(p, r, "m", sc._sha(m)) for p, r, m in ents}}


def test_allowlist_is_path_and_rule_scoped(tmp_path):
    allow = _allow(("docs/x.md", "handle", "@grok"))
    assert run(tmp_path, {"docs/x.md": "a reply by @grok"}, allow_strings=allow) == []
    assert "handle" in rules(run(tmp_path / "2", {"docs/x.md": f"a reply by {GROK}X"}, allow_strings=allow))
    assert "handle" in rules(run(tmp_path / "3", {"docs/y.md": "a reply by @grok"}, allow_strings=allow))
    ph = _allow(("tests/t.py", "handle", f"@{H}"))
    assert run(tmp_path / "4", {"tests/t.py": f"x = '@{H}'"}, allow_strings=ph) == []
    assert "handle" in rules(run(tmp_path / "5", {"tests/u.py": f"x = '@{H}'"}, allow_strings=ph))
    assert "email" in rules(run(tmp_path / "6", {"tests/t.py": f"x = '@{H}' + 'someone@realmail.org'"}, allow_strings=ph))


@pytest.mark.parametrize("entry", [{"path": "src/a.py", "rule": "handle", "match_sha256": "0" * 64},
                                   {"path": "tests/a.py", "rule": "handle", "match": "@fixture_user_99"},
                                   {"path": "tests/a.py", "match_sha256": "0" * 64}])
def test_allowlist_rejects_placeholders_outside_tests_and_bad_entries(tmp_path, entry):
    p = tmp_path / "a.json"; p.write_text(json.dumps({"entries": [entry]}))
    with pytest.raises(sc.SourceError):
        sc.load_allow_file(p)


def test_allowlist_line_hash_outside_tests_ok(tmp_path):
    p = tmp_path / "a.json"
    line = f"see @{H} here"
    p.write_text(json.dumps({"entries": [{"path": "src/a.py", "rule": "handle", "line_sha256": sc.line_sha(line)}]}))
    al = sc.load_allow_file(p)
    assert run(tmp_path, {"src/a.py": "# " + line + "\n"}, allow_strings=al) != []      # different line text
    assert run(tmp_path / "2", {"src/a.py": line + "\n"}, allow_strings=al) == []

def test_fixture_dir_allows_madeup_handles_but_not_list_handles(tmp_path):
    assert run(tmp_path, {"tests/fixtures/a.json": '{"t": "@madeupname"}'}) == []
    assert "account_list_handle" in rules(run(tmp_path, {"tests/fixtures/b.json": '{"t": "@fakebotzz"}'}))


@pytest.mark.parametrize("variant", [
    POST, POST.upper(), POST.replace(" ", "\n", 5), "\u201c" + POST + "\u201d",
    POST.replace("purple", "pur\u200bple"), POST.replace(" over ", " &#111;ver "),
    POST.replace(" ", "%20"), POST.replace("o", "\\u006f"),
])
def test_corpus_quote_detected_after_normalising(tmp_path, variant):
    assert "post_corpus_quote" in rules(run(tmp_path, {"docs/q.md": "intro: " + variant}))


def test_corpus_quote_in_json_escapes_and_split_strings(tmp_path):
    w = POST.split()
    esc = '{"t": "' + POST.replace("o", "\\u006f").replace("a", "\\u0061") + '"}'        # raw \\uXXXX escapes
    split = json.dumps({"a": " ".join(w[:7]), "key_token": "x", "b": " ".join(w[7:])})
    assert "post_corpus_quote" in rules(run(tmp_path, {"tests/fixtures/e.json": esc}))
    assert "post_corpus_quote" in rules(run(tmp_path / "2", {"tests/fixtures/s.json": split}))


def test_base64_text_rescanned_and_opaque_blob_flagged(tmp_path):
    b = base64.b64encode((POST + " " + POST + " " + POST).encode()).decode()
    assert "post_corpus_quote" in rules(run(tmp_path, {"src/a.py": f'B = "{b}"'}))
    blob = base64.b64encode(os.urandom(300)).decode().replace("=", "")
    assert "base64_blob" in rules(run(tmp_path / "2", {"src/b.py": f'B = "{blob}"'}))


def test_short_overlap_not_flagged(tmp_path):
    assert run(tmp_path, {"docs/q.md": " ".join(POST.split()[:11])}) == []


@pytest.mark.parametrize("rel,rule", [
    ("reports/a.md", "banned_path"), ("Reports/a.md", "banned_path"), ("prompts/style_augusto.v9.md", "banned_path"),
    ("prompts/echo_calibration/x_samples.md", "banned_path"), ("web/dist/a.js", "banned_path"),
    ("data/other.json", "data_not_allowlisted"), ("Data/other.json", "data_not_allowlisted"),
    ("config/.handoff_secret", "handoff_secret"), ("config/.HANDOFF_SECRET", "handoff_secret"),
])
def test_path_rules_case_insensitive(tmp_path, rel, rule):
    assert rule in rules(run(tmp_path, {rel: "fine"}))


def test_allowlisted_data_ok(tmp_path):
    assert run(tmp_path, {"data/seed_inventory.json": "{}", "data/x_scout_queries.v1.json": '{"q": "@theholy_hermit"}',
                          "data/fit_grader/config.json": "{}"}) == []


@pytest.mark.parametrize("rel,body", [("web/a.png", b"\x89PNG\x00"), ("web/a.js.map", "{}"), ("n.ipynb", "{}"),
                                      ("web/__snapshots__/a.txt", "x"), ("src/blob.bin", b"\xff\xfe\x00\x01"),
                                      ("src/x.gz", b"\x1f\x8b\x08")])
def test_opaque_flagged_and_allow_opaque_limited_to_asset_images(tmp_path, rel, body):
    assert "opaque_file" in rules(run(tmp_path, {rel: body}))
    assert "opaque_file" in rules(run(tmp_path / "2", {rel: body}, allow=[rel]))   # not under web/src/assets
    assert run(tmp_path / "3", {"web/src/assets/logo.png": b"\x89PNG\x00"}, allow=["web/src/assets/logo.png"]) == []


def test_symlink_escaping_tree_fails_even_if_allowlisted(tmp_path):
    outside = tmp_path / "secret.txt"; outside.write_text("x")
    tree = tmp_path / "tree"; (tree / "src").mkdir(parents=True)
    (tree / "src" / "link").symlink_to(outside)
    (tree / "src" / "dirlink").symlink_to(tmp_path)
    found = sc.check(tree, tmp_path / "norepo", ["src/link"], corpus(), HANDLES, NOALLOW)
    assert [f.path for f in found if f.rule == "symlink_escapes_tree"] == ["src/dirlink", "src/link"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads chmod 000")
def test_unreadable_dir_and_file_fail(tmp_path):
    tree = tmp_path / "tree"; (tree / "src" / "locked").mkdir(parents=True)
    (tree / "src" / "locked" / "a.py").write_text("x"); (tree / "src" / "b.py").write_text("x")
    os.chmod(tree / "src" / "locked", 0); os.chmod(tree / "src" / "b.py", 0)
    try:
        r = rules(sc.check(tree, tmp_path / "norepo", (), corpus(), HANDLES, NOALLOW))
    finally:
        os.chmod(tree / "src" / "locked", 0o755); os.chmod(tree / "src" / "b.py", 0o644)
    assert "unreadable_dir" in r and "unreadable" in r


def test_gitignored_file_fails(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text("secret_notes.md\n")
    assert "gitignored" in rules(run(tmp_path, {"docs/secret_notes.md": "x"}, repo=repo))


FILLER = " ".join(f"zq{i}word" for i in range(200))   # made-up words so each source clears MIN_RUNS
SRC = POST + "\n\n" + FILLER


def _source_repo(tmp_path, skip=None, empty=None):
    repo = tmp_path / "repo"
    for rel, body in {"prompts/style_augusto.v1.md": SRC, "prompts/style_augusto.v2.md": SRC,
                      "prompts/echo_calibration/x_samples.md": SRC,
                      "data/bot_accounts.json": '{"handles": ["fakebotzz"]}', "data/brand_accounts.json": "[]",
                      "data/self_accounts.json": '["theholy_hermit"]'}.items():
        if rel == skip:
            continue
        p = repo / rel; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("" if rel == empty else body)
    return repo


def test_sources_load_from_repo(tmp_path):
    repo = _source_repo(tmp_path)
    tree = tmp_path / "tree"; (tree / "docs").mkdir(parents=True)
    (tree / "docs" / "a.md").write_text(POST)
    assert rules(sc.check(tree, repo, log=lambda m: None)) == ["post_corpus_quote"]


@pytest.mark.parametrize("skip,empty", [("prompts/style_augusto.v2.md", None), ("prompts/echo_calibration/x_samples.md", None),
                                        ("data/bot_accounts.json", None), ("data/brand_accounts.json", None),
                                        (None, "prompts/style_augusto.v1.md"), (None, "data/self_accounts.json")])
def test_missing_or_empty_source_exits_2(tmp_path, skip, empty, capsys):
    repo = _source_repo(tmp_path, skip, empty)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    t = tmp_path / "t"; (t / "docs").mkdir(parents=True); (t / "docs" / "a.md").write_text(POST)
    assert sc.main([str(t), "--repo", str(repo)]) == 2
    assert "cannot run" in capsys.readouterr().err


def test_cli_exit_codes(tmp_path, capsys):
    repo = _source_repo(tmp_path)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    t = tmp_path / "t"; (t / "docs").mkdir(parents=True)
    (t / "docs" / "a.md").write_text("ok")
    assert sc.main([str(t), "--repo", str(repo)]) == 0
    (t / "docs" / "b.md").write_text(f"@{H}")
    assert sc.main([str(t), "--repo", str(repo)]) == 1
    assert f"docs/b.md:1: handle: @{H}" in capsys.readouterr().out
    assert sc.main([]) == 2


def test_builder_allowlist_selection():
    got = bpt.select(["src/a.py", "tests/fixtures/x.json", "web/src/a.tsx", "web/dist/a.js", "reports/a.md",
                      "data/fit_rubric.json", "data/seed_inventory.json", "prompts/style_augusto.v1.md",
                      "src/__pycache__/a.pyc", "docs/X.md", "docs/BUILD-LOG.md", "demo-shots/a.png", "README.md"])
    assert got == ["README.md", "data/seed_inventory.json", "docs/X.md", "src/a.py", "tests/fixtures/x.json",
                   "web/src/a.tsx"]


def test_builder_uses_the_commit_not_the_working_tree(tmp_path, monkeypatch):
    repo = tmp_path / "r"; (repo / "src").mkdir(parents=True)
    g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    g("init", "-q"); (repo / "src" / "a.py").write_text("committed = 1\n")
    g("add", "."); g("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "c")
    (repo / "src" / "a.py").write_text(f"dirty = '@{H}'\n"); (repo / "src" / "new.py").write_text("untracked\n")
    monkeypatch.setattr(bpt, "ROOT", repo)
    out = tmp_path / "out"; out.mkdir()
    files, _sha = bpt.build(out)
    assert files == ["src/a.py"] and (out / "src" / "a.py").read_text() == "committed = 1\n"


def test_repo_allowlist_file_loads_and_holds_no_plaintext_fakes():
    raw = (sc.ROOT / "scripts" / "scrub_allow.json").read_text()
    assert sc.load_allow(sc.ROOT)["entries"]
    for fake in (f"@{H}", KEY, "someone@realmail.org", SID, GROK + "X", SELF + "X"):
        assert fake not in raw


# --- AT FAIL on 9f2ec42 ---
def test_joined_json_scan_uses_values_only_across_nested_objects(tmp_path):
    w = POST.split()
    doc = {"a": {"k1": " ".join(w[:5]), "deep": [{"k2": " ".join(w[5:11])}]}, "zz_key_with_many_words_here": " ".join(w[11:])}
    assert "post_corpus_quote" in rules(run(tmp_path, {"tests/fixtures/n.json": json.dumps(doc)}))


def test_whitespace_only_required_source_exits_2(tmp_path, capsys):
    repo = _source_repo(tmp_path)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "prompts" / "echo_calibration" / "x_samples.md").write_text("   \n\t\n")
    t = tmp_path / "t"; (t / "docs").mkdir(parents=True); (t / "docs" / "a.md").write_text("ok")
    assert sc.main([str(t), "--repo", str(repo)]) == 2 and "fewer than" in capsys.readouterr().err


def test_repo_without_git_exits_2(tmp_path, capsys):
    repo = _source_repo(tmp_path)
    t = tmp_path / "t"; (t / "docs").mkdir(parents=True); (t / "docs" / "a.md").write_text("ok")
    assert sc.main([str(t), "--repo", str(repo)]) == 2 and "not a git checkout" in capsys.readouterr().err


def test_short_and_line_wrapped_base64_rescanned(tmp_path):
    short = base64.b64encode(f"ping @{H}".encode()).decode()
    assert len(short) < 200 and "handle" in rules(run(tmp_path, {"src/a.py": f'B = "{short}"'}))
    b = base64.b64encode(POST.encode()).decode()
    wrapped = "\n".join(b[i:i + 40] for i in range(0, len(b), 40))
    assert "post_corpus_quote" in rules(run(tmp_path / "2", {"src/b.txt": wrapped}))
    concat = " +\n".join(f'"{b[i:i + 40]}"' for i in range(0, len(b), 40))
    assert "post_corpus_quote" in rules(run(tmp_path / "3", {"src/c.py": f"B = ({concat})"}))


def test_hex_digest_not_treated_as_base64(tmp_path):
    assert run(tmp_path, {"src/a.py": 'S = "' + "ab12" * 16 + '"'}) == []


def test_malformed_percent_never_crashes(tmp_path):
    assert run(tmp_path, {"docs/a.md": "growth was 100%ff and 50%zz, %E2%80 too"}) == []


def test_decode_runs_to_fixpoint():
    x = f"@{H}"
    for _ in range(4):
        x = x.replace("%", "%25").replace("@", "%40")
    assert sc.decode(x) == f"@{H}"


def test_builder_bad_sha_exits_2(capsys):
    assert bpt.main(["--sha", "not-a-real-sha-xyz"]) == 2
    assert "cannot run" in capsys.readouterr().err


def test_builder_reads_allowlist_and_checker_from_the_sha(tmp_path, monkeypatch):
    repo = _commit_repo(tmp_path, {"scripts/scrub_check.py": "MARK = 'from-sha'\n",
                                   "scripts/scrub_allow.json": '{"entries": []}'})
    monkeypatch.setattr(bpt, "ROOT", repo)
    out = tmp_path / "out"; out.mkdir()
    bpt.build(out)
    assert bpt.checker_at(out).MARK == "from-sha" and not (out / "scripts" / "__pycache__").exists()


def test_builder_fails_when_required_file_missing(tmp_path, monkeypatch, capsys):
    repo = _commit_repo(tmp_path, {"src/a.py": "x\n"})
    monkeypatch.setattr(bpt, "ROOT", repo)
    assert bpt.main([]) == 2 and "required file(s) missing" in capsys.readouterr().err


def test_required_manifest_present_on_head_and_self_handle_allowed():
    names = set(subprocess.run(["git", "-C", str(sc.ROOT), "ls-files"], capture_output=True, text=True).stdout.split())
    assert not [r for r in bpt.REQUIRED if r not in names]      # overrides never stand in for a source file
    q = (sc.ROOT / "data" / "x_scout_queries.v1.json").read_text()
    assert "@theholy_hermit" in q
    assert sc.scan_text("data/x_scout_queries.v1.json", q, set(), {"theholy_hermit"}) == []

def _commit_repo(tmp_path, files):
    repo = tmp_path / "r"; repo.mkdir()
    g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    g("init", "-q")
    for rel, body in files.items():
        p = repo / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body)
    g("add", "."); g("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "c")
    return repo


def test_builder_swaps_public_overrides(tmp_path, monkeypatch):
    repo = _commit_repo(tmp_path, {"prompts/fit_grader.v1.md": "LIVE prompt\n",
                                   "public_overrides/prompts/fit_grader.v1.md": "made-up prompt\n", "src/a.py": "x\n"})
    monkeypatch.setattr(bpt, "ROOT", repo)
    out = tmp_path / "out"; out.mkdir()
    files, _ = bpt.build(out)
    assert (out / "prompts" / "fit_grader.v1.md").read_text() == "made-up prompt\n"
    assert not (out / "public_overrides").exists() and "prompts/fit_grader.v1.md" in files


def test_live_grader_prompts_are_the_pre_anonymisation_bytes():
    import hashlib
    want = {"v1": "ea0f03442c5054c2", "v2": "5f4c2e93bdf9d993"}   # == b604c29 (live pin) and d8082ba~1
    for v, h in want.items():
        assert hashlib.sha256((sc.ROOT / "prompts" / f"fit_grader.{v}.md").read_bytes()).hexdigest()[:16] == h
        assert (sc.ROOT / "public_overrides" / "prompts" / f"fit_grader.{v}.md").read_text() != \
            (sc.ROOT / "prompts" / f"fit_grader.{v}.md").read_text()


# --- AT FAIL on 4f2ac80 ---
@pytest.mark.parametrize("text", ["https://x.com/zzfakeperson/status/42", 'f"https://x.com/fakebotzz/status/{sid}"',
                                  "twitter.com/@zzfakeperson/status/1", "https://x.com/zzfakeperson/status/"])
def test_status_url_handle_checked_for_short_or_template_ids(tmp_path, text):
    assert "x_status_handle" in rules(run(tmp_path, {"src/a.py": text}))


@pytest.mark.parametrize("text", ["https://x.com/i/web/status/1", "https://x.com/fixture_user_60/status/{sid}",
                                  "https://x.com/theholy_hermit/status/9", "https://x.com/{handle}/status/{sid}",
                                  "https://x.com/…/status/…"])
def test_status_url_handle_ok_for_reserved_fixture_self_template(tmp_path, text):
    assert "x_status_handle" not in rules(run(tmp_path, {"src/a.py": text}))


def test_repo_tests_use_fixture_handles_in_status_urls():
    import re
    out = subprocess.run(["git", "-C", str(sc.ROOT), "grep", "-nE",
                          r"(x|twitter)\.com/(someone|e|x|b|expert|demo|other|vendor|example)/status",
                          "--", "tests", "web/src", "web/e2e", "scripts/gen_ui_fixtures.py"], capture_output=True, text=True)
    assert out.stdout == ""


def test_json_key_text_scanned_in_document_order(tmp_path):
    w = POST.split()
    doc = {" ".join(w[:5]): " ".join(w[5:10]), "k": " ".join(w[10:])}
    assert "post_corpus_quote" in rules(run(tmp_path, {"tests/fixtures/k.json": json.dumps(doc)}))


def test_stub_corpus_source_exits_2(tmp_path, capsys):
    repo = _source_repo(tmp_path)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    stub = " ".join(POST.split()[:14])
    (repo / "prompts" / "echo_calibration" / "x_samples.md").write_text((stub + "\n") * 50)   # repeats don't count
    t = tmp_path / "t"; (t / "docs").mkdir(parents=True); (t / "docs" / "a.md").write_text("ok")
    assert sc.main([str(t), "--repo", str(repo)]) == 2 and "fewer than" in capsys.readouterr().err


@pytest.mark.parametrize("rel,body", [("data/brand_accounts.json", "5"), ("data/bot_accounts.json", "null"),
                                      ("data/bot_accounts.json", '{"handles": "abc"}'),
                                      ("data/self_accounts.json", '"theholy_hermit"'),
                                      ("data/bot_accounts.json", '["fakebotzz", 7]')])
def test_account_list_wrong_type_exits_2(tmp_path, rel, body, capsys):
    repo = _source_repo(tmp_path)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / rel).write_text(body)
    t = tmp_path / "t"; (t / "docs").mkdir(parents=True); (t / "docs" / "a.md").write_text("ok")
    assert sc.main([str(t), "--repo", str(repo)]) == 2 and "list of strings" in capsys.readouterr().err


@pytest.mark.parametrize("path", ["tests/../src/x.py", "tests/*", "/tests/a.py", "tests/a\\b.py"])
def test_allowlist_rejects_dotdot_and_glob_paths(tmp_path, path):
    p = tmp_path / "allow.json"
    p.write_text(json.dumps({"entries": [{"path": path, "rule": "handle", "match_sha256": "0" * 64}]}))
    with pytest.raises(sc.SourceError, match="exact relative path"):
        sc.load_allow_file(p)


def test_builder_fails_when_live_grader_prompt_exists_only_as_override(tmp_path):
    out = tmp_path / "out"
    for r in bpt.REQUIRED:
        (out / r).parent.mkdir(parents=True, exist_ok=True); (out / r).write_text("x")
    src = set(bpt.REQUIRED) - {"prompts/fit_grader.v1.md", "prompts/fit_grader.v2.md"}
    assert bpt.missing_required(out, src) == ["prompts/fit_grader.v1.md (only an override)",
                                              "prompts/fit_grader.v2.md (only an override)"]
    assert bpt.missing_required(out, set(bpt.REQUIRED)) == []


# --- AT FAIL: JSON-escaped slashes ---
@pytest.mark.parametrize("text,rule", [(r'{"u": "https:\/\/x.com\/zzfakeperson\/status\/7"}', "x_status_handle"),
                                       (r'{"u": "https:\/\/x.com\/zzfakeperson"}', "x_handle_path")])
def test_json_escaped_slash_urls_checked(tmp_path, text, rule):
    assert rule in rules(run(tmp_path, {"src/a.json": text}))


def test_json_escaped_slash_fixture_url_passes(tmp_path):
    assert run(tmp_path, {"src/a.json": r'{"u": "https:\/\/x.com\/fixture_user_60\/status\/9000000000000000001"}'}) == []


def test_license_required_and_committed():
    assert "LICENSE" in bpt.REQUIRED
    names = subprocess.run(["git", "-C", str(sc.ROOT), "ls-files"], capture_output=True, text=True).stdout.split()
    assert "LICENSE" in names and (sc.ROOT / "LICENSE").read_text().startswith("MIT License")


def test_builder_without_license_exits_2(tmp_path):
    out = tmp_path / "out"
    for r in bpt.REQUIRED:
        if r != "LICENSE":
            (out / r).parent.mkdir(parents=True, exist_ok=True); (out / r).write_text("x")
    assert bpt.missing_required(out) == ["LICENSE"]


# --- AT FAIL: double-escaped slashes, decode to a fixpoint (8 passes) ---
DEEP = "%" + "25" * 12 + "41"          # 13 layers of percent-encoding: never converges in 8 passes


@pytest.mark.parametrize("text", [r'{"u": "https:\\/\\/x.com\\/zzfakeperson\\/status\\/7"}',
                                  r'{"u": "https:\\\\/\\\\/x.com\\\\\\\\/zzfakeperson\\\\/status\\\\/7"}',
                                  r'{"u": "https:\u002f\u002fx.com%5C%2Fzzfakeperson\u002fstatus%5C%2F7"}'])
def test_double_and_mixed_escaped_slashes_flagged(tmp_path, text):
    assert "x_status_handle" in rules(run(tmp_path, {"src/a.json": text}))


def test_double_escaped_fixture_url_passes(tmp_path):
    assert run(tmp_path, {"src/a.json": r'"https:\\/\\/x.com\\/fixture_user_60\\/status\\/9000000000000000001"'}) == []


def test_decode_cap_is_8_passes():
    assert sc.DECODE_PASSES == 8
    assert sc.decode("%" + "25" * 6 + "41") == "A"            # 7 layers converge
    with pytest.raises(sc.DecodeNotConverged):
        sc.decode(DEEP)


def test_non_converging_file_is_a_finding_and_exits_2(tmp_path, capsys):
    assert "decode_not_converged" in rules(run(tmp_path, {"docs/a.md": DEEP}))
    repo = _source_repo(tmp_path / "s")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    t = tmp_path / "t"; (t / "docs").mkdir(parents=True); (t / "docs" / "a.md").write_text(DEEP)
    assert sc.main([str(t), "--repo", str(repo)]) == 2 and "decode_not_converged" in capsys.readouterr().out


def test_non_converging_corpus_source_exits_2(tmp_path, capsys):
    repo = _source_repo(tmp_path)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "prompts" / "style_augusto.v2.md").write_text(SRC + "\n" + DEEP)
    t = tmp_path / "t"; (t / "docs").mkdir(parents=True); (t / "docs" / "a.md").write_text("ok")
    assert sc.main([str(t), "--repo", str(repo)]) == 2 and "cannot be decoded" in capsys.readouterr().err
