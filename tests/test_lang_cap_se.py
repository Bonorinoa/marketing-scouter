"""se_ X language cap: graded claim on a not-clearly-English X post → topic, lang_capped, no draft."""
import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from tests.test_fit_either_se import FakeGrader
from tests.test_lang_gate import EN, ES_PLUS_EN, PT, RU

ES_SCA = ("Los agentes sintéticos de LLM no pueden reemplazar el trabajo de campo, pero en los juegos de laboratorio "
          "siguen la dirección de los datos humanos no-WEIRD.")
EN_SCA = ("We ran LLM personas against non-WEIRD lab games from Kenya and Peru: they were directionally right where we "
          "had human baselines. That is enough for piloting designs, not for replacing the fieldwork.")


class OnlySca(FakeGrader):
    def __call__(self, text, claim):
        self.calls.append(text)
        return "claim" if "non-WEIRD" in claim else "none"


def _run(tmp_path, monkeypatch, text, url="https://x.com/fixture_user_54/status/1000000000000971", lang="on"):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    monkeypatch.setenv("MS_LANG_CAP", lang)
    app = create_app(str(tmp_path))
    api = app.state.api
    api.fit_grader = OnlySca({})
    drafts = []
    api.predrafter = lambda p, card: drafts.append(1) or {"status": "ok", "draft_text": card["draft"], "model": "t"}
    row = TestClient(app).post("/intake/x", json={"run_id": "discovery-lang", "posts": [{"url": url, "text": text}]}).json()["posts"][0]
    return row, api, drafts


@pytest.mark.parametrize("text", [ES_SCA, ES_SCA + " " + EN, PT + " non-WEIRD", RU + " non-WEIRD"])
def test_se_not_clearly_english_capped_topic_no_draft(tmp_path, monkeypatch, text):
    row, api, drafts = _run(tmp_path, monkeypatch, text)
    if row["status"] == "queued":
        assert row["fit_level"] == "topic" and "lang_capped" in row["labels"] and drafts == []
        assert row["fit_trace"]["lang"]["lang"] != "en"
        e = [x for x in api.events() if x["kind"] == "fit_model"][-1]
        assert e["n_lang_capped"] == 1


def test_se_spanish_capped_case_is_queued(tmp_path, monkeypatch):
    row, _, drafts = _run(tmp_path, monkeypatch, ES_SCA)
    assert row["status"] == "queued" and row["fit_level"] == "topic" and "lang_capped" in row["labels"] and not drafts


def test_se_clean_english_claim_drafts(tmp_path, monkeypatch):
    row, _, drafts = _run(tmp_path, monkeypatch, EN_SCA)
    assert row["status"] == "queued" and row["fit_level"] == "claim" and "lang_capped" not in row.get("labels", []) and drafts


def test_se_civic_door_never_capped(monkeypatch):
    # door gate is in core: civic (Tucumán/NOA Spanish voice) and non-X outlets skip the cap
    import inspect
    from src.api import core
    src = inspect.getsource(core.ScouterAPI._recommend)
    assert "out == Outlet.X" in src and "VoiceDoor.AUGUSTO_CIVIC" in src


def test_se_short_english_fixture_not_capped_after_fix(tmp_path, monkeypatch):
    from tests.test_intake_contract import T_SCA   # 'Are LLM synthetic participants just WEIRD? Results look different'
    row, _, drafts = _run(tmp_path, monkeypatch, T_SCA)
    assert row["fit_level"] == "claim" and "lang_capped" not in row.get("labels", []) and drafts


def test_se_kill_switch_off(tmp_path, monkeypatch):
    row, _, drafts = _run(tmp_path, monkeypatch, ES_SCA)
    row2, _, d2 = _run(tmp_path / "b", monkeypatch, ES_SCA, url="https://x.com/fixture_user_54/status/1000000000000972", lang="off")
    assert "lang_capped" in row["labels"] and not drafts
    assert row2["fit_level"] == "claim" and "lang_capped" not in row2.get("labels", []) and d2


def test_se_default_on_outside_tests(monkeypatch):
    monkeypatch.delenv("MS_LANG_CAP", raising=False)
    import os
    assert os.environ.get("MS_LANG_CAP", "on") == "on"
