"""x-brief bridge: the ONLY way Market Scouter runs x-brief. Suggests only, never posts.

Mapping (all argv lists, never a shell):
  capture -> x-brief [--project P] add <url> --source cli --no-fetch --no-screenshot
                     --no-notify --reconsider --json
  draft   -> x-brief [--project P] process --reconsider --no-open --json
             then the draft is read from the brief markdown named in the JSON ("brief"),
             in the "### #n" block whose "- **Source:**" equals our url ("- **Draft:**" line).
  health  -> x-brief [--project P] doctor
Anything else raises ForbiddenSubcommand. publish/published/mark/auth/schedule/... are never run.

Sandbox: the child env drops every PATH dir that holds `xurl` (x-brief's only X API route,
used read-only by enrichment) and `add` passes --no-fetch, so nothing the bridge runs reaches X.
Input comes only from the sealed handoff payload; voice samples / style corpus are never sent.
"""
from __future__ import annotations

import json
import os
import hashlib
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

DEFAULT_BIN = "/home/box/.local/bin/x-brief"
ALLOWED = frozenset({"add", "process", "doctor"})
FORBIDDEN_KEYS = frozenset({"samples", "voice_samples", "style", "style_corpus", "corpus"})
ERRORS = {
    "draft_empty": "x-brief returned an empty draft. Copy the handoff instead.",
    "xbrief_unavailable": "x-brief isn't available on this computer right now. Copy the handoff instead.",
    "xbrief_timeout": "x-brief took too long and was stopped. Copy the handoff instead.",
    "xbrief_failed": "x-brief ran but reported an error. Copy the handoff instead.",
    "xbrief_no_draft": "x-brief didn't write a draft for this post. Copy the handoff instead.",
    "xbrief_declined": "No draft: the drafter passed on this one.",
    "style_missing": "The approved style guide isn't on this computer, so drafting is off. Copy the handoff instead.",
    "style_mismatch": "The style guide on this computer isn't the approved version, so drafting is off. Copy the handoff instead.",
}


def extract_decline(brief_md: str) -> Optional[str]:
    """The ranker's own reason when a brief has no recommendation ("Nothing worth ..." + "Reason: ...")."""
    sec = brief_md.split("## Recommendations", 1)
    if len(sec) < 2:
        return None
    body = sec[1].split("\n## ", 1)[0]
    if "### " in body or "Nothing worth" not in body:
        return None
    m = re.search(r"(?m)^Reason:\s*(.+)$", body)
    return m.group(1).strip()[:300] if m else "the model judged nothing here worth replying to."


class ForbiddenSubcommand(Exception):
    pass


class BridgeError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code, self.detail = code, detail


def _bin() -> str:
    return os.environ.get("MS_XBRIEF_BIN", DEFAULT_BIN)


def _timeout() -> float:
    try:
        return float(os.environ.get("MS_XBRIEF_TIMEOUT", "90"))
    except ValueError:
        return 90.0


def sandbox_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("MS_")}
    dirs = [d for d in env.get("PATH", "").split(os.pathsep)
            if d and not os.path.exists(os.path.join(d, "xurl"))]
    env["PATH"] = os.pathsep.join(dirs)
    env["XBRIEF_BRIDGE"] = "market-scouter"
    return env


def build_argv(sub: str, *args: str, project: Optional[str] = None) -> list[str]:
    if sub not in ALLOWED:
        raise ForbiddenSubcommand(sub)
    argv = [_bin()]
    proj = project or os.environ.get("MS_XBRIEF_PROJECT")
    if proj:
        argv += ["--project", proj]
    return argv + [sub, *[str(a) for a in args]]


def run(sub: str, *args: str, timeout: Optional[float] = None, project: Optional[str] = None,
        env_extra: Optional[dict] = None) -> subprocess.CompletedProcess:
    argv = build_argv(sub, *args, project=project)
    if not (os.path.isfile(argv[0]) and os.access(argv[0], os.X_OK)):
        raise BridgeError("xbrief_unavailable", argv[0])
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             env={**sandbox_env(), **(env_extra or {})}, start_new_session=True, shell=False)
    except OSError as e:
        raise BridgeError("xbrief_unavailable", str(e))
    try:
        out, err = p.communicate(timeout=timeout or _timeout())
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.communicate()
        raise BridgeError("xbrief_timeout", f"{sub} > {timeout or _timeout()}s")
    return subprocess.CompletedProcess(argv, p.returncode, out, err)


def bridge_input(payload: dict, asset_title: str = "") -> dict:
    """The only fields that leave Market Scouter. Built from the sealed payload."""
    return {"url": payload["url"], "asset_id": payload.get("asset_id"), "asset_title": asset_title,
            "door": payload.get("door"),
            "text": payload.get("text") or None, "author": payload.get("author") or None,
            "asset_claim": payload.get("asset_claim") or payload.get("claim") or None,
            "asset_caveat": payload.get("asset_caveat") or payload.get("caveat") or None,
            "active_slugs": list((payload.get("xbrief_interests") or {}).get("active")
                                 or payload.get("xbrief_slugs") or [])}


def _last_json(text: str) -> Optional[dict]:
    """Last top-level JSON object in stdout. x-brief prints trailing lines after its --json summary
    (e.g. 'pool unchanged: {...}'), so decode the object in place instead of parsing to end of text."""
    dec = json.JSONDecoder()
    starts = [m.start() + 1 for m in re.finditer(r"\n\{", text)]
    if text.startswith("{"):
        starts.insert(0, 0)
    for start in reversed(starts):
        try:
            obj, _ = dec.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


_STATUS_RE = re.compile(r"/status(?:es)?/(\d{5,25})(?:\D|$)")


def _status_id(u: str) -> Optional[str]:
    m = _STATUS_RE.search(u or "")
    return m.group(1) if m else None


def extract_draft(brief_md: str, url: str) -> Optional[str]:
    """Return the Draft line for THIS post only.

    `process` drafts the whole pool, so blocks are matched by the post's X status id
    (falling back to the exact URL when there is no status id), never by position.
    Exactly one block must match; zero or several -> None (xbrief_no_draft), so another
    post's draft can never land on this card.
    """
    want = _status_id(url)
    hits = []
    for block in re.split(r"(?m)^### ", brief_md)[1:]:
        m = re.search(r"(?m)^- \*\*Source:\*\* (\S+)", block)
        if not m:
            continue
        src = m.group(1).strip()
        same = (_status_id(src) == want) if want else (src == url.strip())
        if same:
            hits.append(block)
    if len(hits) != 1:
        return None
    d = re.search(r"(?m)^- \*\*Draft:\*\* (.+)$", hits[0])
    if d and not d.group(1).startswith("none this run"):
        return d.group(1).strip()
    return None


XBRIEF_CONFIG = Path("/workspace/x-brief/config/config.yaml")


def drafter_model(summary: Optional[dict] = None) -> str:
    """Model id that wrote an x-brief draft: from the run summary when it reports one, else x-brief's config."""
    for k in ("model", "model_id", "draft_model"):
        v = (summary or {}).get(k)
        if isinstance(v, str) and v:
            return v
    try:
        txt = Path(os.environ.get("MS_XBRIEF_CONFIG", XBRIEF_CONFIG)).read_text(encoding="utf-8")
        blk = txt.split("\nmodel:", 1)[1]
        get = lambda key: (re.search(rf"^\s+{key}:\s*([^#\n]*)", blk, re.M) or [None, ""])[1].strip().strip('"')
        follow = get("follow_hermes_default").lower() == "true"
        if get("backend").lower() == "hermes" and "\nhermes:" in txt:   # hermes backend: hermes.model pins it
            hb = txt.split("\nhermes:", 1)[1]
            hm = (re.search(r'^\s+model:\s*"?([^"#\n]*)', hb, re.M) or [None, ""])[1].strip()
            if hm:
                return hm
            return "hermes_default"
        return f"{get('provider')}/{get('name')}" + ("+follow_hermes_default" if follow else "")
    except (OSError, IndexError):
        return "unknown"


XBRIEF_STYLE = Path("/workspace/x-brief/config/x-style.md")
# The style guide the bridge drafts with. Gitignored (it quotes his posts): read from disk in the code checkout
# (ensure_up links v1+v2 into pinned worktrees). MS_STYLE_FILE overrides the path, never the expected sha.
_PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
STYLE_FILES = {"v1": _PROMPTS / "style_augusto.v1.md", "v2": _PROMPTS / "style_augusto.v2.md"}
# Pinned sha256 per version. Drafting runs only when the file read for this draft has EXACTLY the active
# version's sha; a mismatch, an empty file, or a link to another version fails closed with style_mismatch.
EXPECTED_STYLE_SHA = {
    "v1": "2b1b3c86738630f47f7cc3bd86e4d3694fb303752b8f8891049dbbba46e8cb16",   # approved; tonight's pin
    "v2": None,   # unset until Augusto approves a v2 text; selecting v2 before then => style_mismatch
}
DEFAULT_STYLE = "v1"
STYLE_FILE = STYLE_FILES[DEFAULT_STYLE]


def active_style() -> str:
    """The style version setting (MS_STYLE_VERSION, default v1). Its expected sha travels with it."""
    return os.environ.get("MS_STYLE_VERSION", DEFAULT_STYLE)
_EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def style_path() -> Path:
    if not _isolated():          # non-isolated runs read x-brief's own config/x-style.md (reported, sha-checked)
        return Path(os.environ.get("MS_XBRIEF_STYLE", XBRIEF_STYLE))
    return Path(os.environ.get("MS_STYLE_FILE") or STYLE_FILES.get(active_style(), STYLE_FILE))


def expected_style_sha() -> Optional[str]:
    return EXPECTED_STYLE_SHA.get(active_style())   # unknown or unset version => None => never ok


def _read_style() -> tuple[dict, Optional[bytes]]:
    """Read the style guide ONCE: (info, exact bytes hashed). A missing file or dangling symlink -> (missing, None)."""
    p = style_path()
    base = {"style_active": active_style(), "style_expected_sha": expected_style_sha(),
            "style_source": "bridge" if _isolated() else "xbrief_default"}
    try:
        data = p.read_bytes()
    except OSError:
        return {"style_version": None, "style_sha": None, "style_file_present": False, "style_ok": False, **base}, None
    sha = hashlib.sha256(data).hexdigest()
    exp = base["style_expected_sha"]
    ok = bool(exp) and bool(data.strip()) and sha != _EMPTY_SHA and sha == exp
    return {"style_version": p.resolve().stem, "style_sha": sha, "style_file_present": True, "style_ok": ok, **base}, data


def style_info() -> dict:
    """The style guide x-brief reads during this draft, read LIVE: version from the resolved file name,
    sha256 of its current bytes, whether it is present, and style_ok (present, non-empty, sha == pinned sha
    of the active version). style_source says which file was read: 'bridge' or 'xbrief_default' (isolation off)."""
    return _read_style()[0]


XBRIEF_VAULT = Path(os.path.expanduser("~/Documents/x-brief-vault"))
RUNS_DIR = Path("/workspace/x-brief-bridge/runs")
_USER_END = "<!-- x-brief:writing-user:end -->"


def _isolated() -> bool:
    return os.environ.get("MS_XBRIEF_ISOLATE", "1") != "0"


def asset_instructions(claim: Optional[str], caveat: Optional[str]) -> str:
    """Per-draft writing instruction carrying the matched asset's claim and caveat (what the voice gate checks)."""
    out = []
    if claim:
        out.append(f'For this draft only: state this claim in your own words, keeping its key terms: "{claim.strip()}"')
    if caveat:   # the caveat is shown on the card next to the claim, never in the reply
        out.append("For this draft only: do not include caveats or disclaimers about this claim; they are shown separately.")
    if claim or caveat:
        out.append("For this draft only: the whole draft must fit in one X post (under 280 characters).")
    return "\n".join(out)


PROBE_OVERRIDES = ((r"(?m)^(\s*min_candidates:\s*)\d+", r"\g<1>1"), (r"(?m)^(\s*min_confidence:\s*)\d+", r"\g<1>0"),
                   (r"(?m)^(\s*min_score:\s*)[\d.]+", r"\g<1>0"))


def make_run_dir(tag: str, claim: Optional[str], caveat: Optional[str], force: bool = False,
                 style_bytes: Optional[bytes] = None) -> tuple[Path, Path]:
    """Throwaway x-brief project + vault for ONE draft, so bridge/probe posts never enter the user's real pool.
    project/config: copy of the live config.yaml + links to its style/interests files.
    vault: links to the user's Profile/ and Writing/Samples.md (x-brief's own context, read-only use);
    Writing/Guidelines.md = the user's file with the asset claim/caveat added inside their own instruction area."""
    src_cfg = Path(os.environ.get("MS_XBRIEF_CONFIG", XBRIEF_CONFIG)).parent
    src_vault = Path(os.environ.get("MS_XBRIEF_VAULT", XBRIEF_VAULT))
    base = Path(os.environ.get("MS_XBRIEF_RUNS", RUNS_DIR))
    root = base / f"{time.strftime('%Y%m%d-%H%M%S')}-{re.sub(r'[^A-Za-z0-9_-]', '', tag)[:40]}"
    proj, vault = root / "project", root / "vault"
    (proj / "config").mkdir(parents=True, exist_ok=True)
    for f in src_cfg.iterdir():
        if f.name == "config.yaml":
            cfg = f.read_text(encoding="utf-8")
            if force:  # drafting probe only: the ranker may not decline the single probe post (copy only)
                for pat, rep in PROBE_OVERRIDES:
                    cfg = re.sub(pat, rep, cfg)
            (proj / "config" / f.name).write_text(cfg, encoding="utf-8")
        elif f.name == "x-style.md":
            continue   # the bridge's own style file is linked below (never x-brief's default)
        elif f.is_file() and not f.name.startswith("config.yaml."):
            (proj / "config" / f.name).symlink_to(f.resolve())
    if style_bytes is None:   # direct callers: read now (draft() passes the exact bytes it hashed)
        sp = style_path()
        if not sp.is_file():
            raise FileNotFoundError(f"style file missing: {sp}")
        style_bytes = sp.read_bytes()
    dst = proj / "config" / "x-style.md"
    if dst.is_symlink() or dst.exists():   # same-second run dir reuse
        dst.unlink()
    dst.write_bytes(style_bytes)   # a COPY of the hashed bytes: swapping the source after the check changes nothing
    (vault / "Writing").mkdir(parents=True, exist_ok=True)
    if (src_vault / "Profile").is_dir():
        (vault / "Profile").symlink_to((src_vault / "Profile").resolve())
    if (src_vault / "Writing" / "Samples.md").is_file():
        (vault / "Writing" / "Samples.md").symlink_to((src_vault / "Writing" / "Samples.md").resolve())
    g = src_vault / "Writing" / "Guidelines.md"
    text = g.read_text(encoding="utf-8") if g.is_file() else ""
    extra = asset_instructions(claim, caveat)
    # bridge drafts are single X posts: the copy's length control is 'short' (the user's file is untouched)
    text = re.sub(r"(?m)^(length:\s*)\w+", r"\1short", text, count=1)
    if extra:
        text = text.replace(_USER_END, extra + "\n\n" + _USER_END, 1) if _USER_END in text else (text + "\n\n" + extra + "\n")
    (vault / "Writing" / "Guidelines.md").write_text(text, encoding="utf-8")
    return proj, vault


def draft(inp: dict, force: bool = False) -> dict:
    """add + process for one item. Returns {status, draft_text, provenance, elapsed_ms[, code, message]}."""
    assert not (FORBIDDEN_KEYS & set(inp)), "voice samples never leave Market Scouter"
    if not inp.get("door"):
        raise ValueError("door_required")
    t0 = time.monotonic()
    prov: dict[str, Any] = {"input": inp, "commands": []}
    style, style_bytes = _read_style()   # read once; these exact bytes are hashed, checked and copied

    def fail(code: str, detail: str = "") -> dict:
        return {"status": "error", "code": code, "message": ERRORS[code], "detail": detail[-500:], **style,
                "draft_text": None, "provenance": prov, "elapsed_ms": int((time.monotonic() - t0) * 1000)}
    if not style["style_file_present"]:   # fail closed: never draft with a missing or default style
        return fail("style_missing", str(style_path()))
    if not style["style_ok"]:   # wrong version, edited, empty, or x-brief's own file (isolation off)
        return fail("style_mismatch", f"{style['style_source']}:{style_path()} sha={style['style_sha']} "
                                      f"expected {style['style_active']}={style['style_expected_sha']}")
    try:
        kw: dict[str, Any] = {}
        if _isolated():
            proj, vault = make_run_dir(_status_id(inp["url"]) or "draft", inp.get("asset_claim"), inp.get("asset_caveat"), force=force,
                                       style_bytes=style_bytes)
            # x-brief resolves its project from $XBRIEF_HOME when --project is absent (cli.make_ctx)
            # the launcher also puts $XBRIEF_HOME on PYTHONPATH to find its package: point PYTHONPATH at the code
            code = os.environ.get("MS_XBRIEF_CODE") or str(Path(os.environ.get("MS_XBRIEF_CONFIG", XBRIEF_CONFIG)).resolve().parent.parent)
            kw = {"env_extra": {"XBRIEF_HOME": str(proj), "XBRIEF_VAULT_PATH": str(vault), "PYTHONPATH": code}}
            prov["run_dir"] = str(proj.parent)
        extra = []   # the post being answered (not a voice sample): without it x-brief has nothing to draft
        if inp.get("text"):
            extra += ["--text", str(inp["text"])]
        if inp.get("author"):
            extra += ["--author", "@" + str(inp["author"]).lstrip("@")]
        a = run("add", inp["url"], *extra, "--source", "cli", "--no-fetch", "--no-screenshot", "--no-notify",
                "--reconsider", "--json", **kw)
        prov["commands"].append(["add", a.returncode])
        if a.returncode != 0:
            return fail("xbrief_failed", a.stderr or a.stdout)
        p = run("process", "--reconsider", "--no-open", "--json", **kw)
        prov["commands"].append(["process", p.returncode])
        if p.returncode != 0:
            return fail("xbrief_failed", p.stderr or p.stdout)
    except BridgeError as e:
        return fail(e.code, e.detail)
    summary = _last_json(p.stdout) or {}
    brief = summary.get("brief")
    prov.update(run_id=summary.get("run_id"), brief=brief)
    text = None
    md = Path(brief).read_text(encoding="utf-8") if brief and Path(brief).is_file() else ""
    if md:
        text = extract_draft(md, inp["url"])
    if text is not None and not text.strip():
        return fail("draft_empty", str(brief))   # whitespace-only draft is an error, never a card
    if not text:
        why = extract_decline(md) if md else None
        if why:   # model ran and declined: say so plainly, with its reason, on the card
            r = fail("xbrief_declined", str(brief))
            from .decline_text import no_draft_line, sanitize_reason
            r["decline_reason"] = sanitize_reason(why)   # untrusted model text: cleaned before it is stored
            r["message"] = no_draft_line(why)
            r["model"] = drafter_model(summary)
            return r
        return fail("xbrief_no_draft", str(brief))
    from ..voice_gate import strip_caveat
    text = strip_caveat(text, inp.get("asset_caveat"))   # caveat is a card field, never draft body
    if not text.strip():
        return fail("draft_empty", str(brief))
    return {"status": "ok", "draft_text": text, "caveat_appended": False, "provenance": prov, "model": drafter_model(summary), **style,
            "elapsed_ms": int((time.monotonic() - t0) * 1000)}


def health() -> dict:
    b = _bin()
    present = os.path.isfile(b) and os.access(b, os.X_OK)
    out = {"binary": b, "present": present, "doctor_ok": False, "up": False}
    if present:
        try:
            d = run("doctor", timeout=min(_timeout(), 30))
            out["doctor_ok"] = d.returncode == 0
            out["detail"] = (d.stdout or "")[-800:]
        except BridgeError as e:
            out["error"] = e.code
    out["up"] = present and "error" not in out
    return out
