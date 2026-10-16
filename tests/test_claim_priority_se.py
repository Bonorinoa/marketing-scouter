"""se_ claim-first queue (MS_QUEUE_CLAIM_FIRST, default OFF): tier order + tiered replace; S unchanged."""
import pytest

from src.api.core import ScouterAPI
from src.models import CardState, Decision, Outlet, ScoredCard
from tests.test_fit_either_se import FakeGrader, X, mk, run  # noqa: F401
from tests.test_intake_contract import T_SCA


def posts():
    topics = [X(1000000000000800 + i, T_SCA + f" topic {i}") for i in range(7)]
    claims = [X(1000000000000850 + i, T_SCA + f" claim {i}") for i in range(2)]
    return topics + claims


def answers():
    return {**{T_SCA + f" topic {i}": "topic" for i in range(7)}, **{T_SCA + f" claim {i}": "claim" for i in range(2)}}


def _ev(api, mode):
    return [x for x in api.events() if x["kind"] == f"fit_{mode}"][-1]


@pytest.mark.parametrize("mode", ["model", "either"])
def test_se_claim_first_on_admits_claims(mk, monkeypatch, mode):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", mode)
    monkeypatch.setenv("MS_QUEUE_CLAIM_FIRST", "1")
    c, api = mk(FakeGrader(answers()))
    by = {r["status_id"]: r for r in run(c, posts())}
    claims = [by[str(1000000000000850 + i)] for i in range(2)]
    topics = [by[str(1000000000000800 + i)] for i in range(7)]
    assert all(r["status"] == "queued" for r in claims)
    assert sum(r["status"] == "queued" for r in topics) == 5
    assert all(r["status"] == "held" for r in topics if r["status"] != "queued")       # overflow, as today
    assert len({r["S"] for r in claims + topics}) == 1                                  # S untouched
    e = _ev(api, mode)
    assert e["n_claim_displaced"] == 2 and e["n_topic_displaced"] == 2
    cards = c.get("/queue").json()["cards"]
    assert sorted(x["fit_level"] for x in cards) == ["claim"] * 2 + ["topic"] * 5
    rr = {x["fit_level"]: x["rank_reason"] for x in cards}
    assert rr["claim"]["text"].startswith("Ranked first: argues one of your claims · S ")
    assert rr["topic"]["text"].startswith("On your topic, no claim to answer · S ")
    assert rr["claim"]["tooltip"].startswith("Cards that argue a claim")


@pytest.mark.parametrize("mode", ["model", "either"])
def test_se_claim_first_off_keeps_order_but_logs(mk, monkeypatch, mode):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", mode)
    monkeypatch.delenv("MS_QUEUE_CLAIM_FIRST", raising=False)
    c, api = mk(FakeGrader(answers()))
    by = {r["status_id"]: r for r in run(c, posts())}
    assert all(by[str(1000000000000800 + i)]["status"] == "queued" for i in range(7))
    assert all(by[str(1000000000000850 + i)]["status"] != "queued" for i in range(2))
    e = _ev(api, mode)
    assert e["n_claim_displaced"] == 2 and e["n_topic_displaced"] == 2                # would-have counts
    cards = c.get("/queue").json()["cards"]
    assert all(x["fit_level"] == "topic" and x["rank_reason"] is None for x in cards)


# ── tiered replace rule (unit) ─────────────────────────────────────────────
def card(i, S, lvl):
    return ScoredCard(card_id=f"c{i}", candidate_id=f"k{i}", asset_id="a", outlet=Outlet.X,
                      url=f"https://x.com/fixture_user_54/status/{1000 + i}", S=S, fit_level=lvl, state=CardState.OPEN)


def test_se_full_of_topics_claim_replaces_lowest_topic_regardless_of_S(monkeypatch):
    monkeypatch.setenv("MS_QUEUE_CLAIM_FIRST", "1")
    q = [card(i, 90 + i, "topic") for i in range(7)]
    dec, rep = ScouterAPI._queue_decision(card(99, 40, "claim"), q)
    assert dec == Decision.REPLACE and rep == "c0"
    monkeypatch.setenv("MS_QUEUE_CLAIM_FIRST", "0")                                    # flag off: S rule only
    assert ScouterAPI._queue_decision(card(99, 40, "claim"), q)[0] != Decision.REPLACE


def test_se_full_of_claims_topic_never_replaces(monkeypatch):
    monkeypatch.setenv("MS_QUEUE_CLAIM_FIRST", "1")
    q = [card(i, 40 + i, "claim") for i in range(7)]
    dec, rep = ScouterAPI._queue_decision(card(99, 99, "topic"), q)
    assert dec in (Decision.DROP, Decision.WATCH) and rep is None
    monkeypatch.setenv("MS_QUEUE_CLAIM_FIRST", "0")                                    # old rule would replace
    assert ScouterAPI._queue_decision(card(99, 99, "topic"), q)[0] == Decision.REPLACE


def test_se_same_tier_plus_10_rule(monkeypatch):
    monkeypatch.setenv("MS_QUEUE_CLAIM_FIRST", "1")
    q = [card(i, 50 + i, "claim") for i in range(7)]
    assert ScouterAPI._queue_decision(card(99, 59.9, "claim"), q)[0] in (Decision.DROP, Decision.WATCH)
    assert ScouterAPI._queue_decision(card(99, 60, "claim"), q) == (Decision.REPLACE, "c0")


def test_se_protected_cards_never_replaced(monkeypatch):
    monkeypatch.setenv("MS_QUEUE_CLAIM_FIRST", "1")
    q = [card(i, 50, "topic").model_copy(update={"state": CardState.PINNED}) for i in range(7)]
    assert ScouterAPI._queue_decision(card(99, 99, "claim"), q)[1] is None
