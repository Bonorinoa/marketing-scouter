"""Build the ALLOWLIST public tree from a COMMIT (git archive, never the working tree) and scrub it.

Usage: python -m scripts.build_public_tree [--sha REV] [--dest DIR] [--keep] [--allow-opaque REL ...]
REV defaults to HEAD. Only files of that commit matching INCLUDE (and not EXCLUDE) go in. docs/*.md go in
only if each passes scrub_check on its own; failing docs are left out and listed. docs/BUILD-LOG.md never
goes in. A file at public_overrides/<path> replaces <path> in the tree
(the live copy on main stays byte-identical, e.g. the grader prompt the pin grades with). Nothing in the repo is changed. Exit code is scrub_check's (0 clean, 1 findings, 2 cannot run).
"""
from __future__ import annotations

import fnmatch
import importlib.util
import io
import shutil
import subprocess
import sys
import tarfile
from typing import Optional
import tempfile
from pathlib import Path

from scripts import scrub_check

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ["src/*", "tests/*", "web/src/*", "web/e2e/*", "web/index.html", "web/package.json",
           "web/package-lock.json", "web/playwright.config.ts", "web/tsconfig.json", "web/vite.config.ts",
           "web/.gitignore", "docs/*.md", "README.md", "LICENSE", "LICENSE.*", "pyproject.toml",
           "requirements.txt", ".gitignore", "legacy/*", "observability-schema.md", "scripts/*.py", "scripts/*.sh",
           "scripts/crontab.txt", "scripts/scrub_allow.json", "prompts/fit_grader.v*.md",
           "prompts/jev_criteria.v*.json", "data/fit_grader/*", *sorted(scrub_check.DATA_ALLOW)]
EXCLUDE = ["*/__pycache__/*", "*.pyc", "*.egg-info/*", "web/dist/*", "web/node_modules/*", "docs/BUILD-LOG.md",
           "src/marketing_scouter.egg-info/*"]


def _git_bytes(*a: str) -> bytes:
    r = subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise scrub_check.SourceError(f"git {a[0]} failed: {r.stderr.decode(errors='replace').strip()[:200]}")
    return r.stdout


def missing_required(dest: Path, source: Optional[set] = None) -> list[str]:
    """Required files missing from the built tree, or (given the commit's own paths) missing from the commit
    itself: an override never stands in for a deleted source file such as the live grader prompts."""
    miss = [r for r in REQUIRED if not (dest / r).is_file()]
    if source is not None:
        miss += [f"{r} (only an override)" for r in REQUIRED if r not in source and r not in miss]
    return miss


def checker_at(dest: Path):
    """scrub_check.py and its allowlist/corpus config as committed at the sha (from the built tree)."""
    p = dest / "scripts" / "scrub_check.py"
    if not p.is_file():
        raise scrub_check.SourceError("scripts/scrub_check.py missing at that sha")
    spec = importlib.util.spec_from_file_location("scrub_check_at_sha", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod     # dataclasses need the module registered
    old, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # never write __pycache__ into the tree
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    return mod


def select(paths: list[str]) -> list[str]:
    ok = lambda p: any(fnmatch.fnmatch(p, g) for g in INCLUDE) and not any(fnmatch.fnmatch(p, g) for g in EXCLUDE)
    return sorted({p for p in paths if ok(p)})


# a fresh clone must be able to run: build fails (exit 2) if any of these is missing from the built tree
REQUIRED = sorted({*scrub_check.DATA_ALLOW, "data/fit_grader/config.json", "data/fit_grader/jev_cutoffs.v1.json",
                   "data/fit_grader/prompt_placeholder.v1.txt", "data/fit_grader/jev_cutoffs_frozen.json",
                   "prompts/fit_grader.v1.md", "prompts/fit_grader.v2.md", "prompts/jev_criteria.v1.json",
                   "README.md", "LICENSE", "pyproject.toml", "requirements.txt", "web/package.json", "web/package-lock.json",
                   "web/index.html", "web/vite.config.ts", "scripts/crontab.txt", "scripts/scrub_check.py",
                   "scripts/scrub_allow.json", "src/api/app.py", "tests/conftest.py",
                   "tests/fixtures/accounts/bot_accounts.json", "tests/fixtures/accounts/self_accounts.json",
                   "tests/fixtures/accounts/brand_accounts.json"})
OVERRIDE_DIR = "public_overrides/"   # public-only copies swapped in for the same path; the dir itself never ships


def build(dest: Path, sha: str = "HEAD") -> tuple[list[str], str]:
    full = _git_bytes("rev-parse", "--verify", f"{sha}^{{commit}}").decode().strip()
    tar = tarfile.open(fileobj=io.BytesIO(_git_bytes("archive", "--format=tar", full)))
    members = {m.name: m for m in tar.getmembers() if m.isfile() or m.issym()}
    overrides = {n[len(OVERRIDE_DIR):]: members[n] for n in members if n.startswith(OVERRIDE_DIR)}
    files = sorted(set(select(list(members))) | set(overrides))
    for rel in files:
        m = overrides.get(rel) or members[rel]   # e.g. made-up-example grader prompts replace the live ones
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if m.issym():
            out.symlink_to(m.linkname)        # kept as a link so the check sees escapes
        else:
            out.write_bytes(tar.extractfile(m).read())
    build.source = {n for n in members if not n.startswith(OVERRIDE_DIR)}   # the commit's own paths
    return files, full


def drop_failing_docs(dest: Path, sc=scrub_check, log=print) -> list[str]:
    corpus = sc.build_corpus(sc.corpus_files(ROOT, strict=True), strict=True, repo=ROOT)
    handles = sc.account_handles(ROOT, strict=True)
    allow = sc.load_allow_file(dest / "scripts" / "scrub_allow.json")
    dropped = []
    for p in sorted((dest / "docs").glob("*.md")) if (dest / "docs").is_dir() else []:
        rel = p.relative_to(dest).as_posix()
        if p.is_symlink():
            continue
        if sc.scan_text(rel, p.read_text(encoding="utf-8", errors="replace"), corpus, handles, allow):
            p.unlink()
            dropped.append(rel)
    for d in dropped:
        log(f"public tree: left out {d} (does not pass the scrub)")
    return dropped


def main(argv: list[str]) -> int:
    dest, keep, allow, sha = None, False, [], "HEAD"
    it = iter(argv)
    for a in it:
        if a == "--dest":
            dest = Path(next(it))
        elif a == "--sha":
            sha = next(it)
        elif a == "--keep":
            keep = True
        elif a == "--allow-opaque":
            allow.append(next(it))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    tmp = Path(tempfile.mkdtemp(prefix="ms_public_")) if dest is None else dest
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        try:
            files, full = build(tmp, sha)
            miss = missing_required(tmp, getattr(build, "source", None))
            if miss:
                print(f"public tree: required file(s) missing at {full[:10]}: {', '.join(miss)}", file=sys.stderr)
                return 2
            sc = checker_at(tmp)
            drop_failing_docs(tmp, sc)
        except Exception as e:  # noqa: BLE001  any build/source problem fails closed (SourceError at any sha)
            print(f"scrub_check: cannot run, {type(e).__name__}: {e}", file=sys.stderr)
            return 2
        print(f"public tree: {len(files)} files from {full[:10]} -> {tmp}")
        return sc.main([str(tmp), "--repo", str(ROOT), "--allow-file", str(tmp / "scripts" / "scrub_allow.json"),
                        *sum((["--allow-opaque", x] for x in allow), [])])
    finally:
        if dest is None and not keep:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
