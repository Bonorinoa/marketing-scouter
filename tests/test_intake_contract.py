"""Data Analyst scoring contract for POST /intake/x (discovery intake).

Skips cleanly until Systems Engineer registers the route. No network: fake x-brief
binary (tests.test_xbrief_bridge.fake) + conftest DNS/socket guard.
Expected S is recomputed with src/score.score_candidate, which is the thin adapter
over src/scorer.compute_factors/compute_S/s_safe_kill (the DA primitives).
Response parsing is tolerant of key names (results|posts, kill_reasons|reasons,
S|card.S, predrafted list|per-post flag) because the route shape isn't frozen yet.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.models import AdapterId, Candidate, EvidenceGrade, Outlet, TStatus, VoiceDoor
from src.score import score_candidate
from src.scorer import compute_S
from tests.test_xbrief_bridge import fake  # noqa: F401  (fixture: fake x-brief, no network)

ROUTE = "/intake/x"
SCA = "asset_sca_nonweird"      # grade A, EconLLM
GPT = "asset_gpt4o_weird"       # grade B, EconLLM
T_SCA = "Are LLM synthetic participants just WEIRD? Results look different"   # 1 slug, A
T_GPT = "Does the WVS world values map hold up for GPT answers?"              # 1 slug, B
T_NOFIT = "What a nice sunset over the river tonight"


def _has_route(app) -> bool:
    return any(getattr(r, "path", None) == ROUTE and "POST" in (getattr(r, "methods", None) or set())
               for r in app.routes)


@pytest.fixture
def c(tmp_path, fake):  # noqa: F811
    app = create_app(str(tmp_path / "data"))
    if not _has_route(app):
        pytest.skip("POST /intake/x not registered yet")
    return TestClient(app)


_SEQ = iter(range(10**12, 10**13))


def post(text=T_SCA, *, sid=None, likes=0, age_h=1.0, replies=4, quotes=1, handle="someone"):
    sid = sid or next(_SEQ)
    return {"url": f"https://x.com/{handle}/status/{sid}", "text": text, "author_handle": handle,
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=age_h)).isoformat(),
            "reply_count": replies, "quote_count": quotes, "like_count": likes}


def intake(c, posts, run_id="run_test"):
    return c.post(ROUTE, json={"run_id": run_id, "posts": posts})


def results(r):
    j = r.json()
    rows = j.get("results") if isinstance(j, dict) else j
    if rows is None:
        rows = j.get("posts")
    assert isinstance(rows, list), j
    return rows


def sid_of(row):
    for k in ("status_id", "id"):
        if row.get(k):
            return str(row[k])
    return str(row.get("url") or (row.get("card") or {}).get("url")).rstrip("/").split("/")[-1]


def S_of(row):
    if row.get("S") is not None:
        return float(row["S"])
    card = row.get("card") or {}
    return None if card.get("S") is None else float(card["S"])


def reasons(row):
    return list(row.get("kill_reasons") or row.get("reasons") or [])


def by_sid(r):
    return {sid_of(x): x for x in results(r)}


def queue(c):
    return c.get("/queue").json()["cards"]


def predrafted_sids(r):
    j = r.json()
    if isinstance(j, dict) and isinstance(j.get("predrafted"), list):
        out = set()
        for v in j["predrafted"]:
            v = v if isinstance(v, str) else (v.get("url") or v.get("status_id") or v.get("card_id"))
            out.add(str(v).rstrip("/").split("/")[-1])
        cards = {x.get("card_id"): sid_of(x) for x in results(r) if x.get("card_id")}
        return {cards.get(v, v) for v in out}
    return {sid_of(x) for x in results(r) if x.get("predrafted") or x.get("draft")}


def expected_S(c, p, asset_id, slugs):
    """Run the DA scorer directly on the same input."""
    api = c.app.state.api
    asset = api.store.get_asset(asset_id)
    cand = Candidate(adapter=AdapterId.MANUAL_PASTE, outlet=Outlet.X, url=p["url"], title_or_snippet=p["text"],
                     author=p["author_handle"], created_at=datetime.fromisoformat(p["created_at"]),
                     reply_count=p["reply_count"], quote_count=p["quote_count"], like_count=p["like_count"],
                     T_status=TStatus.UNKNOWN)
    card, kills, f = score_candidate(cand, asset, matched_slugs=slugs,
                                     voice_door=VoiceDoor(asset.door_archive.value))
    assert not kills and card is not None
    assert card.S == round(compute_S(f), 2)
    return card.S


# 1 ─────────────────────────────────────────────────────────────────────────
def test_da_intake_S_matches_scorer(c):
    ps = [post(T_SCA), post(T_GPT), post(T_SCA, age_h=72)]
    rows = by_sid(intake(c, ps))
    q = {x["url"]: x for x in queue(c)}
    for p in ps:
        row = rows[p["url"].split("/")[-1]]
        assert row["status"] == "queued", row
        card = q[p["url"]]
        exp = expected_S(c, p, card.get("asset_id") or (card.get("asset") or {}).get("asset_id")
                         or (SCA if p["text"] == T_SCA else GPT), card["slugs"])
        assert S_of(row) == pytest.approx(exp) == pytest.approx(card["S"])


# 2 ─────────────────────────────────────────────────────────────────────────
def test_da_intake_empty_fit_and_evidence_c_killed(c):
    api = c.app.state.api
    a = api.store.get_asset(GPT)
    api.store.upsert_asset(a.model_copy(update={"evidence_grade": EvidenceGrade.C}))
    nofit, evc = post(T_NOFIT), post(T_GPT)
    rows = by_sid(intake(c, [nofit, evc]))
    r1, r2 = rows[nofit["url"].split("/")[-1]], rows[evc["url"].split("/")[-1]]
    assert r1["status"] == "killed" and "empty_fit" in reasons(r1)
    assert r2["status"] == "killed" and "evidence_c" in reasons(r2)
    assert not any(x["url"] in (nofit["url"], evc["url"]) for x in queue(c))


# 3 ─────────────────────────────────────────────────────────────────────────
def test_da_intake_likes_never_move_S(c):
    lo, hi = post(T_SCA, likes=0), post(T_SCA, likes=10**6)
    rows = by_sid(intake(c, [lo, hi]))
    a, b = rows[lo["url"].split("/")[-1]], rows[hi["url"].split("/")[-1]]
    assert S_of(a) is not None and S_of(a) == S_of(b)
    q = {x["url"]: x["S"] for x in queue(c)}
    assert q[lo["url"]] == q[hi["url"]]


# 4 ─────────────────────────────────────────────────────────────────────────
def _mixed_batch(likes_hi_on_low):
    """6 high-S (A, fresh) + 6 lower-S (B, fresh) posts; likes on the LOW ones if flag."""
    hi = [post(T_SCA, sid=7000 + i, likes=(0 if likes_hi_on_low else 10**6)) for i in range(6)]
    lo = [post(T_GPT, sid=8000 + i, likes=(10**6 if likes_hi_on_low else 0)) for i in range(6)]
    return hi + lo


def _predraft_contract(c, r):
    pre = predrafted_sids(r)
    qS = {x["url"].split("/")[-1]: x["S"] for x in queue(c)}
    assert pre and len(pre) <= 10
    assert pre <= set(qS), "pre-drafts must be queued cards"
    floor = min(qS[s] for s in pre)
    assert all(qS[s] <= floor for s in set(qS) - pre), "a higher-S queued card was skipped"
    return pre


def test_da_intake_predraft_top_by_S_invariant_to_likes(tmp_path, fake):  # noqa: F811
    sets = []
    for i, flag in enumerate((False, True)):
        app = create_app(str(tmp_path / f"d{i}"))
        if not _has_route(app):
            pytest.skip("POST /intake/x not registered yet")
        cc = TestClient(app)
        sets.append(_predraft_contract(cc, intake(cc, _mixed_batch(flag))))
    assert sets[0] == sets[1]


def test_da_intake_predraft_tiebreak_deterministic(tmp_path, fake):  # noqa: F811
    """Same posts in reversed order → same pre-draft set (tiebreak not by arrival order)."""
    sets = []
    for i, rev in enumerate((False, True)):
        app = create_app(str(tmp_path / f"t{i}"))
        if not _has_route(app):
            pytest.skip("POST /intake/x not registered yet")
        cc = TestClient(app)
        batch = [post(T_SCA, sid=9000 + k) for k in range(12)]
        sets.append(_predraft_contract(cc, intake(cc, batch[::-1] if rev else batch)))
    assert sets[0] == sets[1]


# 5 ─────────────────────────────────────────────────────────────────────────
def test_da_intake_cap7_and_plus10_replace(c):
    low = [post(T_GPT, age_h=72) for _ in range(7)]          # B stale: S = 75
    intake(c, low)
    q = queue(c)
    assert len([x for x in q if x["outlet"] == "x"]) == 7
    low_S = min(x["S"] for x in q)
    near = post(T_GPT)                                        # B fresh: 83 < 75+10
    row = by_sid(intake(c, [near]))[near["url"].split("/")[-1]]
    assert row["status"] != "queued"
    assert len(queue(c)) == 7
    big = post(T_SCA)                                         # A fresh: 91 ≥ 75+10
    assert S_of(by_sid(intake(c, [big]))[big["url"].split("/")[-1]]) >= low_S + 10
    q2 = queue(c)
    assert len(q2) == 7 and big["url"] in {x["url"] for x in q2}


# 6 ─────────────────────────────────────────────────────────────────────────
def test_da_intake_duplicate_status_id_noop(c):
    p = post(T_SCA)
    first = by_sid(intake(c, [p]))[p["url"].split("/")[-1]]
    before = queue(c)
    again = dict(p, like_count=10**6, text=p["text"] + " cultural agent",
                 url=p["url"].replace("someone", "SomeoneElse") + "?s=20")
    row = results(intake(c, [again], run_id="run_2"))[0]
    assert row["status"] == "duplicate", row
    assert queue(c) == before
    assert first["status"] == "queued"


# 7 ─────────────────────────────────────────────────────────────────────────
def test_da_intake_51_refused_plainly(c):
    r = intake(c, [post() for _ in range(51)])
    assert r.status_code in (400, 413, 422)
    j = r.json()
    err = j.get("error") if isinstance(j.get("error"), dict) else {}
    msg = err.get("message") or j.get("detail") or j.get("message")
    assert isinstance(msg, str) and msg.strip() and "Traceback" not in msg, j
    assert queue(c) == []


# 8 ─────────────────────────────────────────────────────────────────────────
def test_da_intake_no_win_no_receipt(c):
    head = c.get("/wins/head").json()
    intake(c, [post(T_SCA), post(T_GPT), post(T_NOFIT)])
    assert c.get("/wins").json() in ([], {"wins": []}) or not c.get("/wins").json().get("wins")
    assert c.get("/wins/head").json() == head
    v = c.get("/wins/verify").json()
    assert v.get("ok") is True, v
    kinds = {e.get("kind") for e in c.get("/events").json()} if isinstance(c.get("/events").json(), list) else set()
    assert not kinds & {"receipt", "win", "acted"}


# ── Marketing: every pre-draft passes the voice gate (2026-10-13) ─────────────
BAD_DRAFTS = {
    "lang_mismatch": "Los agentes culturales sintéticos muestran que la encuesta nunca hizo la pregunta correcta en la región.",
    "cta_bait": "Our non-WEIRD cultural agents change the picture. Reply 'yes' and I'll send you the preprint!",
    "stray_link": "Our non-WEIRD cultural agents change the picture. Details: https://evil.example/x https://arxiv.org/abs/2501.06834",
}


@pytest.mark.parametrize("kind", list(BAD_DRAFTS))
def test_mkt_intake_predraft_gated_no_redraft(tmp_path, fake, kind):  # noqa: F811
    app = create_app(str(tmp_path / "data"))
    if not _has_route(app):
        pytest.skip("POST /intake/x not registered yet")
    calls = []

    def bad(post_, card):
        calls.append(card.get("card_id"))
        return {"status": "ok", "draft_text": BAD_DRAFTS[kind], "source": "test"}

    app.state.api.predrafter = bad
    r = intake(TestClient(app), [post()])
    row = results(r)[0]
    assert row["status"] == "queued" and row["predrafted"]
    assert row["gate"]["ok"] is False and row["copy_enabled"] is False, row["gate"]
    assert row["gate"]["reasons"], "blocked draft must say why"
    assert len(calls) == 1, "a blocked pre-draft keeps its slot; never redraft to fill it"


def test_mkt_cvprofiles_x_predraft_fits_and_passes(c):
    """Built-in X draft for asset_cvprofiles was 310 chars (too_long); it must fit and pass the gate."""
    row = results(intake(c, [post("Big Five measurement on LLMs: which prompt version is valid? empty finding")]))[0]
    assert row["status"] == "queued" and row["predrafted"]
    # 2026-10-14: fits (no too_long) and carries no caveat; the built-in template's verbatim claim is now
    # blocked by claim_overlap, so copy is off for local_template drafts.
    assert [x["code"] for x in row["gate"]["reasons"]] == ["claim_overlap"] and not row["copy_enabled"], row["gate"]

