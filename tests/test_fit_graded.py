"""da_ Data Analyst: hashtag/quote rule (on by default) + model-graded Fit scaffold (MS_FIT_GRADED, default OFF)."""
import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import fit_graded as fg
from src.api.app import create_app
from src.fit import claim_match

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).parent / "fixtures" / "fit_v1"
HQ = json.loads((FIX / "hashtag_quote_v1.json").read_text())["cases"]
ADV = json.loads((FIX / "adversarial_v1.json").read_text())["cases"]
RUBRIC_FILE = ROOT / "tests" / "fixtures" / "fit_rubric.anon.json"  # anonymised; real rubric gitignored
RUBRIC = json.loads(RUBRIC_FILE.read_text())


# ── part 1: hashtags count zero, quoted text counts once ─────────────────────
@pytest.mark.parametrize("case", HQ, ids=[c["id"] for c in HQ])
def test_da_hashtag_and_quote_rule(case):
    assert claim_match(case["text"], case["slug_pool"]) == case["expect"]


# ── part 2: scaffold ─────────────────────────────────────────────────────────
class FakeGrader:
    model, prompt_version = "fake/model", "fit-test"

    def __init__(self, answers, claim_has=None):
        self.answers, self.claim_has, self.calls = answers, claim_has, 0

    def __call__(self, text, claim):
        self.calls += 1
        if self.claim_has and self.claim_has not in (claim or ""):
            return "none"
        return self.answers.get(text.strip(), "none")


def test_da_grader_config_pinned_and_versioned():
    cfg = fg.load_config()
    assert cfg["temperature"] == 0 and "/" in cfg["model"] and cfg["prompt_version"].startswith("fit_grader.v1+")
    assert "{claim}" in cfg["prompt"] and "{post}" in cfg["prompt"] and cfg["max_tokens"] <= 16 and cfg["reasoning"] == {"enabled": False}
    assert "api_key" not in json.dumps({k: v for k, v in cfg.items() if k != "api_key_env"}).lower()


def test_da_graded_off_by_default(monkeypatch):
    monkeypatch.delenv("MS_FIT_GRADED", raising=False)
    assert fg.enabled() is False


@pytest.mark.parametrize("raw,lvl", [("claim", "claim"), (" Topic\n", "topic"), ("NONE", "none"), ("Topic.", "none"), ("claim, because…", "none"),
                                     ("I think: claim", "none"), ("", "none"), (None, "none"), ("maybe?", "none")])
def test_da_parse_level_fails_closed(raw, lvl):
    assert fg.parse_level(raw) == lvl


@pytest.mark.parametrize("case", [c for c in ADV if c["expect"] == ["killed"]], ids=lambda c: c["id"])
def test_da_adversarial_junk_never_reaches_model(case):
    g = FakeGrader({case["text"]: "claim"})
    lvl, f, src = fg.graded_level(case["text"], case["id"], case["asset_id"], "x", g)
    assert (lvl, f, src, g.calls) == ("none", 0.0, "junk", 0)
    assert claim_match(case["text"], ["sca-nonweird", "smart-surveys", "gpt4o-weird"]) == []


def test_da_cache_pins_level_so_S_never_moves(tmp_path):
    cache = fg.GradeCache(tmp_path / "g.db")
    g1 = FakeGrader({"post": "claim"})
    assert fg.graded_level("post", "1", "a", "c", g1, cache)[:2] == ("claim", 1.0)
    g2 = FakeGrader({"post": "none"})                    # model drifts later …
    assert fg.graded_level("post", "1", "a", "c", g2, cache) == ("claim", 1.0, "cache") and g2.calls == 0
    g3 = FakeGrader({"post": "topic"}); g3.prompt_version = "fit-test-2"   # new prompt version → regrade
    assert fg.graded_level("post", "1", "a", "c", g3, cache)[:2] == ("topic", 0.5)


SCA_POST = next(c for c in ADV if c["id"] == "at3")["text"]


def _intake(c, text, sid):
    return c.post("/intake/x", json={"run_id": f"r{sid}", "posts": [
        {"url": f"https://x.com/fixture_user_54/status/{sid}", "text": text, "reply_count": 4, "quote_count": 1}]}).json()["posts"][0]


@pytest.fixture
def c(tmp_path):
    app = create_app(str(tmp_path))
    app.state.api.predrafter = lambda p, card: {"status": "ok", "draft_text": card["draft"]}
    return TestClient(app)


def test_da_graded_levels_map_to_F_and_kill(c, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED", "1")
    api = c.app.state.api
    api.fit_grader = FakeGrader({SCA_POST: "claim"}, "non-WEIRD")
    claim_row = _intake(c, SCA_POST, 10**15 + 1)
    assert claim_row["status"] == "queued", claim_row
    api.fit_grader = FakeGrader({SCA_POST: "topic"}, "non-WEIRD")
    topic_row = _intake(c, SCA_POST + " ", 10**15 + 2)
    assert topic_row["status"] in ("queued", "held") and topic_row["S"] == claim_row["S"] - 15  # 30·(1.0−0.5)
    api.fit_grader = FakeGrader({})
    assert _intake(c, SCA_POST + "  ", 10**15 + 3)["reasons"] == ["empty_fit"]
    monkeypatch.setenv("MS_FIT_GRADED", "0")
    api.fit_grader = FakeGrader({})
    # OFF: grader never consulted; word-level Fit still misses this paraphrase (the gap graded Fit closes)
    assert _intake(c, SCA_POST + "   ", 10**15 + 4)["reasons"] == ["empty_fit"]
    assert api.fit_grader.calls == 0


# ── rubric split ─────────────────────────────────────────────────────────────
def _all_examples():
    return [(aid, e) for aid, a in RUBRIC["assets"].items() for e in a["examples"]]


def test_da_rubric_split_is_committed_and_hash_derived():
    for _aid, e in _all_examples():
        want = "heldout" if int(hashlib.sha256(e["id"].encode()).hexdigest(), 16) % 2 else "fit"
        assert e["split"] == want, e["id"]


def test_da_heldout_never_in_grader_code_or_fixtures():
    sources = [ROOT / "src" / "fit_graded.py", ROOT / "src" / "fit.py", *(ROOT / "data" / "fit_grader").rglob("*"), *(ROOT / "prompts").rglob("*"),
               *(p for p in (Path(__file__).parent / "fixtures").rglob("*.json") if p.resolve() != RUBRIC_FILE.resolve()), Path(__file__)]
    blob = "\n".join(p.read_text(encoding="utf-8") for p in sources if p.is_file())
    held = [e for _a, e in _all_examples() if e["split"] == "heldout"]
    assert held
    for e in held:
        assert e["id"] not in blob
        t = " ".join(e["text"].split())
        for i in range(0, max(1, len(t) - 40), 20):
            assert t[i:i + 40] not in blob, (e["id"], t[i:i + 40])


@pytest.mark.skipif(os.environ.get("MS_FIT_LIVE") != "1", reason="live model check; set MS_FIT_LIVE=1")
@pytest.mark.parametrize("case", ADV, ids=lambda c: c["id"])
def test_da_adversarial_live_model(case):
    a = RUBRIC["assets"][case["asset_id"]]
    lvl, _f, src = fg.graded_level(case["text"], case["id"], case["asset_id"], a["one_line_claim"], fg.OpenRouterGrader())
    assert ("killed" if src == "junk" else lvl) in case["expect"]


INJ = [c for c in ADV if c["id"].startswith("inj")]


@pytest.mark.parametrize("case", INJ, ids=lambda c: c["id"])
def test_da_prompt_random_marker_and_lookalikes_neutralised(case):
    cfg = fg.load_config()
    out, b, e = fg.render_prompt(cfg["prompt"], case["text"], "CLAIM")
    out2, b2, _ = fg.render_prompt(cfg["prompt"], case["text"], "CLAIM")
    assert b != b2                                               # fresh secrets.token_hex marker per call
    assert out.count(b) == 1 and out.count(e) == 1 and out.index(b) < out.index(e)
    body = out[out.index(b) + len(b):out.index(e)]
    assert "UNTRUSTED_POST_END" not in body.replace(" ", "_") and "\u200b" not in body and "＜" not in body
    assert "{claim}" not in out and "{post}" not in out and "model_id:" not in out   # front matter dropped


@pytest.mark.parametrize("case", [c for c in ADV if c["id"].startswith("inj")], ids=lambda c: c["id"])
def test_da_injection_output_noncompliant_is_none(case):
    # a model that "obeys" the injection with chatter can never yield claim: only an exact word parses
    for raw in ("Answer: claim", "claim.", "CLAIM - as instructed", "claim\nclaim"):
        level = fg.graded_level(case["text"], case["id"], case["asset_id"], "c", _Const(raw))[0]
        assert level == "none"


class _Const:
    model, prompt_version = "fake/model", "v"
    def __init__(self, raw): self.raw = raw
    def __call__(self, t, c): return self.raw


def test_da_grader_errors_never_skip_and_never_cache(tmp_path):
    cache = fg.GradeCache(tmp_path / "g.db")

    class Down:
        model, prompt_version = "fake/model", "v"
        def __call__(self, t, c): raise fg.GraderUnavailable("URLError")

    class Buggy(Down):
        def __call__(self, t, c): raise KeyError("choices")

    assert fg.graded_level("p", "1", "a", "c", Down(), cache) == ("none", 0.0, "unavailable")
    assert fg.graded_level("p", "1", "a", "c", Buggy(), cache) == ("none", 0.0, "error")
    assert cache.get("1", "a", "v", fg.claim_hash("c")) is None


def test_da_cache_key_includes_claim_hash(tmp_path):
    cache = fg.GradeCache(tmp_path / "g.db")
    assert fg.graded_level("p", "1", "a", "old claim", FakeGrader({"p": "claim"}), cache)[0] == "claim"
    assert fg.graded_level("p", "1", "a", "old claim", FakeGrader({"p": "none"}), cache)[2] == "cache"
    assert fg.graded_level("p", "1", "a", "tightened claim", FakeGrader({"p": "topic"}), cache)[:2] == ("topic", 0.5)


def test_da_binary_mode_fixed_F_and_claim_only_drafts(c, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED", "1")
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "binary")
    api = c.app.state.api
    calls = []
    api.predrafter = lambda p, card: calls.append(p["text"]) or {"status": "ok", "draft_text": card["draft"]}
    t_claim, t_topic = SCA_POST, SCA_POST + " (course listing)"
    api.fit_grader = FakeGrader({t_claim: "claim", t_topic: "topic"}, "non-WEIRD")
    rows = c.post("/intake/x", json={"run_id": "bin", "posts": [
        {"url": "https://x.com/fixture_user_54/status/1000000000000101", "text": t_claim, "reply_count": 4, "quote_count": 1},
        {"url": "https://x.com/fixture_user_54/status/1000000000000102", "text": t_topic, "reply_count": 4, "quote_count": 1}]}).json()["posts"]
    assert all("fit_level" in r for r in rows), rows
    by = {r["fit_level"]: r for r in rows}
    assert by["claim"]["S"] == by["topic"]["S"]                     # one fixed F for any not-none
    assert by["claim"].get("predrafted") and not by["topic"].get("predrafted")
    assert by["topic"]["no_draft"] is True and by["topic"]["predraft"]["code"] == "no_draft_topic"
    assert calls == [t_claim]


def test_da_binary_F_value_and_default_mode(monkeypatch):
    monkeypatch.delenv("MS_FIT_GRADED_MODE", raising=False)
    assert fg.mode() == "graded" and fg.BINARY_F == 0.75
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "binary")
    assert fg.mode() == "binary"


def test_da_eval_prompt_override_does_not_touch_live_config():
    live = fg.load_config()
    v2 = ROOT / "prompts" / "fit_grader.v2.md"
    if not v2.exists():
        pytest.skip("no v2 prompt")
    alt = fg.load_config(str(v2))
    assert alt["prompt_source"] == "prompts/fit_grader.v2.md" and alt["prompt_version"] != live["prompt_version"]
    assert fg.load_config()["prompt_version"] == live["prompt_version"]


def test_se_cache_key_includes_model_id(tmp_path):
    """A model switch (e.g. x-ai/grok → deepseek) must regrade, never reuse old grades."""
    cache = fg.GradeCache(tmp_path / "g.db")
    old = FakeGrader({"p": "claim"}); old.model = "x-ai/grok-4-fast"
    assert fg.graded_level("p", "1", "a", "c", old, cache)[2] == "model"
    new = FakeGrader({"p": "none"}); new.model = "deepseek/deepseek-v4-flash"
    assert fg.graded_level("p", "1", "a", "c", new, cache) == ("none", 0.0, "model") and new.calls == 1
    assert fg.graded_level("p", "1", "a", "c", new, cache)[2] == "cache"


class _EmptyGrader(FakeGrader):
    def __call__(self, text, claim):
        self.calls += 1
        return self.answers.get(text, "")


@pytest.mark.parametrize("reply", ["", "   ", "Topic.", "I think claim"])
def test_se_empty_or_unparseable_reply_is_error_not_none(tmp_path, reply):
    cache = fg.GradeCache(tmp_path / "g.db")
    g = _EmptyGrader({"p": reply})
    assert fg.graded_level("p", "1", "a", "c", g, cache) == ("none", 0.0, "empty")
    assert fg.graded_level("p", "1", "a", "c", FakeGrader({"p": "claim"}), cache)[2] == "model"  # not cached


def test_se_openrouter_body_disables_reasoning_and_empty_raises(monkeypatch):
    import io
    sent = {}

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(req, timeout=None):
        sent["body"] = json.loads(req.data)
        return R(json.dumps({"choices": [{"message": {"content": ""}}]}).encode())
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(fg.urllib.request, "urlopen", fake)
    with pytest.raises(fg.GraderEmpty):
        fg.OpenRouterGrader()("post", "claim")
    assert sent["body"]["reasoning"] == {"enabled": False} and sent["body"]["max_tokens"] >= 16
