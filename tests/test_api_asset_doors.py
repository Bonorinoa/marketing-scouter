"""SE: asset form door gates (Adversarial gaps 1 & 2, 2026-10-09)."""
import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app

BASE = dict(title="t", surface="substack", tone_hint="plain", evidence_grade="B")


@pytest.fixture
def c(tmp_path):
    return TestClient(create_app(str(tmp_path)))


def test_se_civic_only_topic_on_econllm_refused(c):
    r = c.post("/inventory", json={**BASE, "asset_id": "a1", "door": "EconLLM",
                                   "slugs": ["sca-nonweird", "verification-local-context"]})
    assert r.status_code == 422 and r.json()["code"] == "door_mix"
    assert "verification-local-context" in r.json()["message"]
    assert c.get("/inventory").json() and all(a["asset_id"] != "a1" for a in c.get("/inventory").json())


def test_se_econllm_topic_on_civic_refused(c):
    r = c.post("/inventory", json={**BASE, "asset_id": "a2", "door": "Augusto-civic",
                                   "slugs": ["verification-local-context", "sca-nonweird"]})
    assert r.status_code == 422 and r.json()["code"] == "door_mix"


def test_se_dual_door_topic_allowed_either_voice(c):
    for i, door in enumerate(["EconLLM", "Augusto-civic"]):
        r = c.post("/inventory", json={**BASE, "asset_id": f"d{i}", "door": door,
                                       "slugs": ["ai-society-governance"]})
        assert r.status_code == 200, r.text


def test_se_conflicting_door_fields_refused(c):
    r = c.post("/inventory", json={**BASE, "asset_id": "a3", "door": "EconLLM",
                                   "door_archive": "Augusto-civic", "slugs": ["sca-nonweird"]})
    assert r.status_code == 422 and r.json()["code"] == "door_conflict"


def test_se_matching_door_fields_ok(c):
    r = c.post("/inventory", json={**BASE, "asset_id": "a4", "door": "EconLLM",
                                   "door_archive": "EconLLM", "slugs": ["sca-nonweird"]})
    assert r.status_code == 200, r.text
