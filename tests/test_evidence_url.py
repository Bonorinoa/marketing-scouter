"""da_ evidence_url validation (server side, no DNS)."""
import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.core import ScouterAPI
from src.win_evidence import check_link, evidence_url_problem
from tests.conftest import FAKE_DNS
from tests.test_win_evidence import _rec_handoff, _receipt

BAD = [
    "http://x.com/fixture_user_54/status/1", "ftp://x.com/fixture_user_54", "javascript:alert(1)", "file:///etc/passwd",
    "data:text/html,hi", "https://user@x.com/fixture_user_54", "https://user:pw@x.com/fixture_user_54",
    "https://localhost/a", "https://app.localhost/a", "https://0.0.0.0/a", "https://127.0.0.1/a",
    "https://10.1.2.3/a", "https://172.16.0.1/a", "https://172.31.255.1/a", "https://192.168.1.1/a",
    "https://169.254.169.254/latest", "https://[::1]/a", "https://[fe80::1]/a", "https://[fc00::1]/a",
    "https://[fd12:3456::1]/a", "https://[::ffff:127.0.0.1]/a", "https://2130706433/a", "https://0x7f000001/a",
    "https://0x7f.0.0.1/a", "https://017700000001/a", "https://localhost:8710/wins", "https://127.0.0.1:5173/",
    "https://scouter.example.com/a", "https://intranet/a", "", None, "https://x.com/fixture_user_54 b",
]


@pytest.mark.parametrize("url", BAD)
def test_da_evidence_url_refused(monkeypatch, url):
    monkeypatch.setenv("MS_APP_HOSTS", "scouter.example.com")
    assert evidence_url_problem(url)


@pytest.mark.parametrize("url", ["https://x.com/fixture_user_64/status/123", "https://www.linkedin.com/posts/a-1",
                                 "https://8.8.8.8/a", "https://scholar.google.com/x:443"])
def test_da_evidence_url_public_https_ok(url):
    assert evidence_url_problem(url) is None


def test_da_injected_resolver_is_used(tmp_path):
    seen = []
    def resolver(host):
        seen.append(host)
        return ["8.8.8.8"]
    assert check_link("https://some-public-host.org/a", resolver) is None
    assert seen == ["some-public-host.org"]
    api = ScouterAPI(tmp_path, resolver=resolver)
    assert api.resolver is resolver


@pytest.mark.parametrize("addrs", [["10.0.0.5"], ["8.8.8.8", "127.0.0.1"], ["169.254.169.254"],
                                   ["::1"], ["fe80::1%eth0"], ["fd00::1"], ["::ffff:192.168.0.1"]])
def test_da_resolves_private_refused(addrs):
    assert check_link("https://evil.example.org/a", lambda h: addrs) == ("evidence_url_invalid", "resolves_private")


@pytest.mark.parametrize("fail", [OSError("nxdomain"), []])
def test_da_unresolvable(fail):
    def r(h):
        if isinstance(fail, Exception):
            raise fail
        return fail
    assert check_link("https://nope.example.org/a", r)[0] == "evidence_url_unresolvable"


@pytest.mark.parametrize("field,addrs,code", [
    ("evidence_url", ["10.1.1.1"], "evidence_url_invalid"),
    ("evidence_url", OSError("nx"), "evidence_url_unresolvable"),
    ("archive_url", ["127.0.0.1"], "archive_url_invalid"),
    ("archive_url", OSError("nx"), "archive_url_unresolvable"),
])
def test_da_api_dns_refusals(tmp_path, field, addrs, code):
    c = TestClient(create_app(str(tmp_path)))
    h = _rec_handoff(c, 1)
    body = {"evidence_url": "https://x.com/fixture_user_61/status/1", "archive_url": "https://archive.example.org/s"}
    host = "x.com" if field == "evidence_url" else "archive.example.org"
    FAKE_DNS[host] = addrs
    r = _receipt(c, h, **body)
    assert r.status_code == 422 and r.json()["code"] == code and r.json()["reason"]
    assert c.get("/wins?include_test=true").json() == []
    assert c.get(f"/handoff/{h['payload']['handoff_id']}").json()["status"] == "sealed"


@pytest.mark.parametrize("url", ["http://x.com/fixture_user_54", "https://127.0.0.1:8710/wins", "javascript:alert(1)"])
def test_da_api_refuses_with_plain_422(tmp_path, url):
    c = TestClient(create_app(str(tmp_path)))
    r = _receipt(c, _rec_handoff(c, 1), evidence_url=url)
    j = r.json()
    assert r.status_code == 422 and j["code"] == "evidence_url_invalid" and j["reason"] and j["message"]
    assert c.get("/wins?include_test=true").json() == []


@pytest.mark.parametrize("val", ["user", "model", None])
def test_da_receipt_refuses_client_authored_by(tmp_path, val):
    c = TestClient(create_app(str(tmp_path)))
    h = _rec_handoff(c, 1)
    r = _receipt(c, h, evidence_url="https://x.com/fixture_user_61/status/1", authored_by=val)
    assert r.status_code == 422 and r.json()["code"] == "authored_by_client_forbidden"
    assert c.get("/wins?include_test=true").json() == []
    assert c.get(f"/handoff/{h['payload']['handoff_id']}").json()["status"] == "sealed"  # not consumed


def test_da_receipt_refuses_unknown_fields(tmp_path):
    c = TestClient(create_app(str(tmp_path)))
    r = _receipt(c, _rec_handoff(c, 1), evidence_url="https://x.com/fixture_user_61/status/1", is_test=False)
    assert r.status_code == 422 and r.json()["code"] == "bad_request"
