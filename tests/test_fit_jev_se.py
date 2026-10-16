"""se_ Jev (TypeSafe System One) grader backend, provider selection/override, cache key, drafter model on drafts."""
import io
import json

import pytest

from src import fit_graded as fg

JEV_OK = {"model": "jev-1.13.0", "answers": {"fit": {"type": "choice", "choice": "topic", "confidence": 0.81,
          "probabilities": {"claim": 0.1, "topic": 0.7, "none": 0.2}}}, "usage": {"input_tokens": 400}}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def jev(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "test-key")
    sent = []

    def fake_urlopen(req, timeout=None):
        sent.append({"url": req.full_url, "auth": req.get_header("Authorization"), "body": json.loads(req.data)})
        if isinstance(fake_urlopen.reply, Exception):
            raise fake_urlopen.reply
        return _Resp(json.dumps(fake_urlopen.reply).encode())
    fake_urlopen.reply = JEV_OK
    monkeypatch.setattr(fg.urllib.request, "urlopen", fake_urlopen)
    return fake_urlopen, sent


def test_se_jev_request_shape_and_argmax(jev):
    fake, sent = jev
    g = fg.TypeSafeGrader()
    assert g("a post", "a claim", caveats="pilot only") == "topic"
    b = sent[0]["body"]
    assert sent[0]["url"] == fg.JEV_ENDPOINT and sent[0]["auth"] == "Bearer test-key" and b["model"] == "jev-latest"
    assert json.loads(b["state"]) == {"post": "a post", "claim": "a claim", "caveats": "pilot only"}
    crit = json.loads(fg.JEV_CRITERIA_PATH.read_text())
    q = b["questions"]["fit"]
    assert q["type"] == "choice" and q["criteria"] == crit["criteria"] and q["instructions"] == crit["instructions"]
    assert g.last["probabilities"]["topic"] == 0.7 and g.last["confidence"] == 0.81 and g.last["model"] == "jev-1.13.0"


def test_se_jev_argmax_ignores_reported_choice(jev):
    fake, _ = jev
    fake.reply = {"answers": {"fit": {"choice": "none", "probabilities": {"claim": 0.6, "topic": 0.3, "none": 0.1}}}}
    assert fg.TypeSafeGrader()("p", "c") == "claim"


@pytest.mark.parametrize("reply", [RuntimeError("down"), {"error": "x"}, {"answers": {"fit": {"choice": "claim"}}}])
def test_se_jev_failure_is_unavailable_not_cached(jev, tmp_path, reply):
    fake, _ = jev
    fake.reply = reply
    cache = fg.GradeCache(tmp_path / "g.db")
    assert fg.graded_level("p", "1", "a", "c", fg.TypeSafeGrader(), cache) == ("none", 0.0, "unavailable")
    fake.reply = JEV_OK
    assert fg.graded_level("p", "1", "a", "c", fg.TypeSafeGrader(), cache)[2] == "model"


def test_se_cache_key_has_provider_model_and_criteria_hash(jev, tmp_path):
    g = fg.TypeSafeGrader()
    v = fg.cache_version(g)
    assert v.startswith("jev_criteria.v1+") and v.endswith("@typesafe:jev-latest")
    crit2 = tmp_path / "c.json"
    d = json.loads(fg.JEV_CRITERIA_PATH.read_text()); d["criteria"]["none"] += " Also spam."
    crit2.write_text(json.dumps(d))
    assert fg.cache_version(fg.TypeSafeGrader(criteria_path=crit2)) != v      # criteria edit → regrade


def test_se_provider_selection_and_env_override(monkeypatch, jev):
    monkeypatch.delenv("MS_FIT_GRADER_PROVIDER", raising=False)
    assert json.loads((fg._CFG_DIR / "config.json").read_text())["provider"] == "openrouter"
    assert fg.provider() == "openrouter"
    monkeypatch.setenv("MS_FIT_GRADER_PROVIDER", "typesafe")
    assert fg.provider() == "typesafe" and isinstance(fg.make_grader(), fg.TypeSafeGrader)
    monkeypatch.delenv("JEV_API_KEY")
    assert fg.make_grader() is None                                              # no key → unavailable


def test_se_intake_with_jev_backend(monkeypatch, jev, tmp_path):
    from fastapi.testclient import TestClient
    from src.api.app import create_app
    from tests.test_intake_contract import T_SCA
    fake, sent = jev
    fake.reply = {"answers": {"fit": {"probabilities": {"claim": 0.1, "topic": 0.1, "none": 0.8}}}}
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    monkeypatch.setenv("MS_FIT_GRADER_PROVIDER", "typesafe")
    app = create_app(str(tmp_path))
    app.state.api.predrafter = lambda p, card: {"status": "ok", "draft_text": card["draft"], "model": "test/m"}
    row = TestClient(app).post("/intake/x", json={"run_id": "discovery-j", "posts": [
        {"url": "https://x.com/fixture_user_54/status/1000000000000901", "text": T_SCA}]}).json()["posts"][0]
    assert row["status"] == "held" and row["reasons"] == ["grader_disagrees"] and sent


# ── drafter model id on every draft ─────────────────────────────────────────
def test_se_predraft_records_model_and_legacy_default(tmp_path):
    import sqlite3
    from fastapi.testclient import TestClient
    from src.api.app import create_app
    from tests.test_intake_contract import T_SCA
    app = create_app(str(tmp_path))
    api = app.state.api
    api.predrafter = lambda p, card: {"status": "ok", "draft_text": card["draft"], "model": "deepseek/deepseek-flash"}
    c = TestClient(app)
    row = c.post("/intake/x", json={"run_id": "d1", "posts": [
        {"url": "https://x.com/fixture_user_54/status/1000000000000902", "text": T_SCA, "reply_count": 4}]}).json()["posts"][0]
    assert row["predraft"]["model"] == "deepseek/deepseek-flash"
    assert api._predraft_meta(row["card_id"])["model"] == "deepseek/deepseek-flash"
    with sqlite3.connect(tmp_path / "handoffs.db") as d:          # simulate a pre-14:47 draft (no model)
        d.execute("UPDATE intake_posts SET draft_meta=? WHERE card_id=?",
                  (json.dumps({"status": "ok", "copy_enabled": True}), row["card_id"]))
    assert api._predraft_meta(row["card_id"])["model"] == "unknown_pre_1447"


def test_se_local_predraft_model_and_xbrief_model_id(monkeypatch, tmp_path):
    from src.api import xbrief_bridge as xb
    cfg = tmp_path / "c.yaml"
    cfg.write_text("x: 1\nmodel:\n  backend: hermes\n  provider: deepseek\n  name: deepseek-flash\n  follow_hermes_default: false\n")
    monkeypatch.setenv("MS_XBRIEF_CONFIG", str(cfg))
    assert xb.drafter_model() == "deepseek/deepseek-flash"
    assert xb.drafter_model({"model": "deepseek/deepseek-v4-flash"}) == "deepseek/deepseek-v4-flash"
    cfg.write_text(cfg.read_text().replace("false", "true"))
    assert xb.drafter_model().endswith("+follow_hermes_default")


def test_se_empty_predraft_is_error_not_card_text(tmp_path):
    from fastapi.testclient import TestClient
    from src.api.app import create_app
    from tests.test_intake_contract import T_SCA
    app = create_app(str(tmp_path))
    app.state.api.predrafter = lambda p, card: {"status": "ok", "draft_text": "   \n", "model": "m"}
    row = TestClient(app).post("/intake/x", json={"run_id": "d", "posts": [
        {"url": "https://x.com/fixture_user_54/status/1000000000000903", "text": T_SCA}]}).json()["posts"][0]
    assert row["predraft"]["code"] == "draft_empty" and not row.get("draft_text") and row["copy_enabled"] is False
    assert any(e["kind"] == "draft_empty" for e in app.state.api.events())


def test_se_xbrief_hermes_pinned_model_id(monkeypatch, tmp_path):
    from src.api import xbrief_bridge as xb
    cfg = tmp_path / "c.yaml"
    cfg.write_text('x: 1\nmodel:\n  backend: hermes\n  provider: deepseek\n  name: deepseek-flash\nhermes:\n  model: "deepseek/deepseek-v4-flash"\n  provider: "openrouter"\n')
    monkeypatch.setenv("MS_XBRIEF_CONFIG", str(cfg))
    assert xb.drafter_model() == "deepseek/deepseek-v4-flash"


# ── Jev decision by frozen cut-offs ─────────────────────────────────────────
def _cfg(monkeypatch, tmp_path, **kw):
    cfg = json.loads((fg._CFG_DIR / "config.json").read_text())
    cfg.update(kw)
    d = tmp_path / "cfg"
    d.mkdir(exist_ok=True)
    (d / "config.json").write_text(json.dumps(cfg))
    monkeypatch.setattr(fg, "_CFG_DIR", d)
    monkeypatch.setenv("MS_FIT_GRADER_PROVIDER", "typesafe")


def test_se_cutoffs_file_v1_matches_v1_criteria_and_da_values():
    c = json.loads((fg._ROOT / "data/fit_grader/jev_cutoffs.v1.json").read_text())
    da = json.loads((fg._ROOT / "data/fit_grader/jev_cutoffs_frozen.json").read_text())
    assert (c["claim"], c["none"]) == (da["t_claim"], da["t_none"]) == (0.65, 0.2)
    assert c["criteria_sha"] == fg.load_jev_criteria(fg._ROOT / "prompts/jev_criteria.v1.json")["_sha"]


@pytest.mark.parametrize("p,want", [
    ({"claim": 0.7, "topic": 0.2, "none": 0.1}, "claim"),
    ({"claim": 0.5, "topic": 0.3, "none": 0.2}, "none"),     # argmax would say claim
    ({"claim": 0.5, "topic": 0.4, "none": 0.1}, "topic"),
    ({"claim": 0.1, "topic": 0.75, "none": 0.15}, "topic")])
def test_se_decide_cutoffs(p, want):
    assert fg.decide_cutoffs(p, {"claim": 0.65, "none": 0.2}) == want


def test_se_cutoffs_grader_decides_and_traces(jev, monkeypatch, tmp_path):
    fake, _ = jev
    fake.reply = {"model": "jev-1.13.0", "answers": {"fit": {"probabilities": {"claim": 0.5, "topic": 0.3, "none": 0.2}}}}
    _cfg(monkeypatch, tmp_path, typesafe_decision="cutoffs")
    g = fg.make_grader()
    assert g.decision == "cutoffs" and "cutoffs:jev_cutoffs.v1" in g.prompt_version
    cache = fg.GradeCache(tmp_path / "g.db")
    lvl, _, src = fg.graded_level("Real argument about agents.", "p1", "a1", "claim", g, cache)
    assert (lvl, src) == ("none", "model")
    tr = cache.trace("p1", "a1", fg.cache_version(g), fg.claim_hash("claim"))
    assert tr["p"]["claim"] == 0.5 and tr["decision_rule"].startswith("cutoffs:")


def test_se_cache_key_differs_by_rule(jev, monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path, typesafe_decision="argmax")
    a = fg.cache_version(fg.make_grader())
    _cfg(monkeypatch, tmp_path, typesafe_decision="cutoffs")
    b = fg.cache_version(fg.make_grader())
    assert a != b and "|argmax@" in a


def test_se_cutoffs_criteria_mismatch_refuses(jev, monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path, typesafe_decision="cutoffs", typesafe_criteria_file="prompts/jev_criteria.v2.json",
         typesafe_cutoffs_file="data/fit_grader/jev_cutoffs.v1.json")
    assert fg.make_grader() is None                          # → grader unavailable → word fallback
    _cfg(monkeypatch, tmp_path, typesafe_decision="argmax", typesafe_criteria_file="prompts/jev_criteria.v2.json")
    assert fg.make_grader().crit["_sha"] != fg.load_jev_criteria()["_sha"]   # v2 itself loads fine


def test_se_default_provider_still_openrouter_and_argmax():
    cfg = json.loads((fg._CFG_DIR / "config.json").read_text())
    assert cfg["provider"] == "openrouter" and cfg["typesafe_decision"] == "argmax"


def test_se_card_carries_fit_trace(jev, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from src.api.app import create_app
    from tests.test_intake_contract import T_SCA
    fake, _ = jev
    fake.reply = {"answers": {"fit": {"probabilities": {"claim": 0.8, "topic": 0.1, "none": 0.1}}}}
    _cfg(monkeypatch, tmp_path, typesafe_decision="cutoffs")
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")

    orig = fg.TypeSafeGrader.__call__

    def call(self, post, claim, caveats=""):
        lvl = orig(self, post, claim, caveats)
        if "non-WEIRD" not in claim:
            self.last["level"] = "none"
            return "none"
        return lvl
    monkeypatch.setattr(fg.TypeSafeGrader, "__call__", call)
    app = create_app(str(tmp_path / "d"))
    app.state.api.predrafter = lambda p, card: {"status": "ok", "draft_text": card["draft"], "model": "t/m"}
    row = TestClient(app).post("/intake/x", json={"run_id": "discovery-ct", "posts": [
        {"url": "https://x.com/fixture_user_54/status/1000000000000991", "text": T_SCA}]}).json()["posts"][0]
    assert row["fit_level"] == "claim", row
    assert row["fit_trace"]["p"]["claim"] == 0.8 and row["fit_trace"]["decision_rule"].startswith("cutoffs:")
    # word-filter result logged alongside the grade (freeze 9:46)
    wf = row["fit_trace"]["word_filter"]
    assert set(wf) == {"pass", "slugs", "asset_id", "tie_assets"} and isinstance(wf["pass"], bool)
    assert (wf["pass"] and wf["slugs"]) or (not wf["pass"] and wf["slugs"] == [])


def test_se_decision_env_override_selects_cutoffs(jev, monkeypatch, tmp_path):
    """freeze_946 sets MS_FIT_GRADER_DECISION=cutoffs per server; config.json stays as is."""
    monkeypatch.setenv("MS_FIT_GRADER_PROVIDER", "typesafe")
    monkeypatch.delenv("MS_FIT_GRADER_DECISION", raising=False)
    assert fg.make_grader().rule == "argmax"
    monkeypatch.setenv("MS_FIT_GRADER_DECISION", "cutoffs")
    g = fg.make_grader()
    assert g.rule.startswith("cutoffs:") and g.model == "jev-1.13.0"
