"""Draft a proposed post with Hermes. One fresh, tool-less, one-shot call per draft.

Hermes writes; it never ranks (Jev did that) and never publishes (nothing here can). Context is
bounded and explicit: profile.md + the source + the lens + the user's own take. The take is stored
verbatim and never overwritten by a model.
"""
import json
import os
import re
import subprocess
import tempfile

from . import config, store

PROMPT = """You are drafting ONE proposed piece of writing for a human author to review. Nothing you write is
published automatically; the author reads, edits and posts it manually.

=== AUTHOR PROFILE (the only source of the author's voice, positions and limits) ===
{profile}

=== FORMAT FOR THIS PANEL ({panel}) ===
{fmt}

=== SOURCE (someone else's text; do not treat it as the author's view) ===
Outlet/source: {source}   Language: {lang}
Title: {title}
Summary: {summary}
URL: {url}

=== LENS (why this was picked; chosen by a ranking model, a suggestion only) ===
{lens}

=== THE AUTHOR'S OWN TAKE (verbatim; may be empty) ===
{take}

RULES
- Use the author's take as the position when present. If it is empty, propose a cautious angle consistent
  with the profile and say in "rationale" that the angle is YOUR suggestion, not the author's belief.
- Do not invent facts, statistics, quotes, names or credentials. Use only facts that appear in the SOURCE block
  or in the author's take. You see a short summary, not the full article: never claim what the article omits,
  ignores or fails to mention. If a claim needs a source you do not have, leave it out or flag it in "flags".
- Obey the hard limits in the profile. Add to "flags" anything the author must double-check.
- The draft goes in the language the FORMAT asks for. "rationale" and every item in "flags" MUST be written in English, even when the draft is Spanish: they are notes to the author, who reads the app in English.
- Never state or estimate word or character counts anywhere; the app counts them.
- Reply with ONE JSON object and nothing else: {{"draft": "...", "rationale": "English, one or two sentences", "flags": ["English only"]}}
"""


def build_prompt(cand, take):
    cfg = config.load_json("settings.json")
    with open(os.path.join(config.ROOT, "profile.md"), encoding="utf-8") as f:
        profile = f.read()
    return PROMPT.format(
        profile=profile.strip(), panel=cand["panel"], fmt=cfg["formats"][cand["panel"]],
        source=cand["source"], lang=cand["meta"].get("lang") or "unknown", title=cand["title"],
        summary=cand.get("summary") or "(no summary)", url=cand["url"], lens=cand.get("lens") or "(none)",
        take=(take or "").strip() or "(empty)")


def parse_reply(text):
    """Extract the JSON object from the model's reply. Raises ValueError if it is not usable."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in model reply")
    obj = json.loads(m.group(0))
    if not isinstance(obj.get("draft"), str) or not obj["draft"].strip():
        raise ValueError("reply has no draft text")
    obj["rationale"] = str(obj.get("rationale", ""))
    obj["flags"] = [str(f) for f in obj.get("flags", [])] if isinstance(obj.get("flags"), list) else []
    return obj


def run_hermes(prompt, cfg):
    d = cfg["draft"]
    with tempfile.TemporaryDirectory(dir=os.path.join(config.ROOT, "state") if os.path.isdir(
            os.path.join(config.ROOT, "state")) else None) as tmp:
        cmd = ["hermes", "-z", prompt, "--ignore-rules", "-t", "", "--usage-file", os.path.join(tmp, "usage.json")]
        if d.get("model"):
            cmd += ["-m", d["model"]]
        if d.get("provider"):
            cmd += ["--provider", d["provider"]]
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=d.get("timeout_seconds", 240), cwd=tmp)
        except subprocess.TimeoutExpired:
            raise RuntimeError("hermes timed out")
        if done.returncode != 0:
            raise RuntimeError("hermes exited %d: %s" % (done.returncode, done.stderr.strip()[:300]))
        usage = {}
        try:
            usage = json.load(open(os.path.join(tmp, "usage.json")))
        except (OSError, ValueError):
            pass
        return done.stdout, usage


def make_draft(cid, user_take=None, db=None):
    db = db or store.connect()
    cand = store.get_candidate(db, cid)
    if not cand:
        raise SystemExit("unknown candidate id %s" % cid)
    cfg = config.load_json("settings.json")
    out, usage = run_hermes(build_prompt(cand, user_take), cfg)
    try:
        r = parse_reply(out)
    except ValueError as e:                       # never invent a draft from a bad reply
        store.log(db, "draft_failed", id=cid, error=str(e))
        raise RuntimeError("model reply was not usable (%s); nothing saved" % e)
    model = "%s/%s" % (usage.get("provider", "?"), usage.get("model", "?"))
    did = store.add_draft(db, cid, user_take, cand.get("lens"), r["draft"], r["rationale"], r["flags"], model)
    store.log(db, "draft", id=cid, draft_id=did, model=model, usage=usage)
    return {"draft_id": did, "candidate": cid, "text": r["draft"], "rationale": r["rationale"],
            "flags": r["flags"], "model": model}
