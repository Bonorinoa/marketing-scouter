"""se_ claim_echo: graded-claim posts that parrot one of our one_line_claims are held, not queued/drafted."""
import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.claim_echo import echo_score, is_echo, run_score
from tests.test_fit_either_se import FakeGrader

SCA = "LLM synthetic cultural agents can qualitatively track non-WEIRD experimental behavior where human data exist."
PC_SPORTS = ("Our bullpen can qualitatively track non-WEIRD experimental behavior where human data exist: every reliever "
             "walks the bases loaded. Feedback, emergence and adaptation, not one-shot optimization. Fire the manager.")
PC_CRYPTO = ("Synthetic cultural agents can qualitatively track non-WEIRD behavior and so can our bags. 100x incoming, "
             "diamond hands, wagmi, next leg up to the moon. Don't fade the chart.")
PC_MEME_EN = "LLM synthetic cultural agents can qualitatively track non-WEIRD behavior... just like my cat tracks the fridge at 3am lol"
PC_MEME_ES = ("Los agentes culturales sintéticos de LLM pueden rastrear cualitativamente el comportamiento no-WEIRD... "
              "igual que mi gato rastrea la heladera a las 3am jajaja 😹")
REAL1 = ("Ask GPT a values question and its answers drift toward what WEIRD respondents say; responses from non-Western "
         "surveys get flattened toward that center. Simulated respondents aren't culturally neutral.")
REAL_SCA = ("We ran LLM personas against lab games from Kenya and Peru: directionally right where we had human baselines, "
            "useless magnitudes. Good enough for piloting cross-cultural designs, not for replacing fieldwork.")


@pytest.mark.parametrize("t", [PC_SPORTS, PC_CRYPTO, PC_MEME_EN, SCA + " Fire the manager."])
def test_se_echo_detected(t):
    assert is_echo(t, SCA), (echo_score(t, SCA), run_score(t, SCA))


@pytest.mark.parametrize("t", [REAL1, REAL_SCA])
def test_se_real_paraphrase_not_echo(t):
    assert not is_echo(t, SCA), echo_score(t, SCA)


def test_se_translation_is_known_limit():
    # documented limit: deterministic token overlap cannot see a translation
    assert not is_echo(PC_MEME_ES, SCA)


def _run(tmp_path, monkeypatch, text, level):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    app = create_app(str(tmp_path))
    api = app.state.api
    api.fit_grader = FakeGrader({text: level})
    drafts = []
    api.predrafter = lambda p, card: drafts.append(1) or {"status": "ok", "draft_text": card["draft"]}
    row = TestClient(app).post("/intake/x", json={"run_id": "discovery-e", "posts": [
        {"url": "https://x.com/fixture_user_54/status/1000000000000961", "text": text}]}).json()["posts"][0]
    return row, api, drafts


def test_se_graded_claim_echo_held(tmp_path, monkeypatch):
    row, api, drafts = _run(tmp_path, monkeypatch, PC_SPORTS, "claim")
    assert row["status"] == "held" and row["reasons"] == ["claim_echo"]
    assert row["echoed_asset"] == "asset_sca_nonweird" and drafts == []
    assert any(e["kind"] == "decision" and e.get("decision") == "claim_echo" for e in api.events())


def test_se_echo_graded_topic_not_held(tmp_path, monkeypatch):
    row, _, _ = _run(tmp_path, monkeypatch, PC_SPORTS, "topic")
    assert row["status"] != "held" or row["reasons"] != ["claim_echo"]


def test_se_real_claim_still_queued_and_drafted(tmp_path, monkeypatch):
    row, _, drafts = _run(tmp_path, monkeypatch, REAL_SCA, "claim")
    assert row["status"] == "queued" and drafts
