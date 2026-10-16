"""da_: invalid evidence grades on POST /inventory return a plain 422, never a 500."""
import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app

BASE = {"title": "Grade probe", "slugs": ["sca-nonweird"], "surface": "arxiv",
        "tone_hint": "plain", "door": "EconLLM", "asset_id": "asset_grade_probe"}


@pytest.fixture
def c(tmp_path):
    return TestClient(create_app(str(tmp_path)), raise_server_exceptions=False)


@pytest.mark.parametrize("grade", ["A+", "a", "", "D"])
def test_da_invalid_evidence_grade_plain_422(c, grade):
    r = c.post("/inventory", json={**BASE, "evidence_grade": grade})
    assert r.status_code == 422
    assert r.json()["message"] == "Evidence grade must be A, B or C."
    assert r.json()["code"] == "evidence_grade_invalid"


def test_da_valid_evidence_grade_not_rejected_for_grade(c):
    r = c.post("/inventory", json={**BASE, "evidence_grade": "B"})
    assert r.status_code == 200, r.text
