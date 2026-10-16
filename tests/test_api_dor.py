"""Manual-test Definition of Ready — API strips. Test names are prefixed by strip:
se_ (Systems Engineer) · adv_ (Adversarial) · mkt_ (Marketing) · da_ (Data Analyst) · rs_ (Researcher).
"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from src.api import core
from src.api.app import create_app

SCA = "asset_sca_nonweird"
ADEPA = "asset_adepa_lagaceta_carta"
X_WEIRD = dict(url="https://x.com/fixture_user_54/status/1", outlet="x", reply_count=6, quote_count=1, like_count=900,
               snippet="Are LLM synthetic participants just WEIRD? non-WEIRD cultural agent results")
CIVIC = dict(url="https://www.lagaceta.com.ar/nota/1", outlet="x", reply_count=3,
             snippet="Desinformación en Tucumán: Community Notes y verificación con contexto local")


@pytest.fixture
def c(tmp_path):
    return TestClient(create_app(str(tmp_path)))


def rec(c, body, asset_id=None):
    q = f"?asset_id={asset_id}" if asset_id else ""
    return c.post("/recommend" + q, json=body).json()


def card_and_handoff(c, body=X_WEIRD, asset_id=SCA, **kw):
    r = rec(c, body, asset_id)
    assert r["ok"], r
    h = c.post("/handoff", json={"card_id": r["card"]["card_id"], **kw}).json()
    return r["card"], h


CIVIC_MIX = "asset_civic_mix"
CIVIC_MIX_BODY = {**CIVIC, "snippet": CIVIC["snippet"] + " — ai governance"}


def civic_mix(c):
    """Civic op-ed asset with one x-brief-active topic (ai-society-governance) + one off-list topic."""
    c.post("/inventory", json={"asset_id": CIVIC_MIX, "title": "Carta mix", "door": "Augusto-civic",
                               "slugs": ["verification-local-context", "ai-society-governance"],
                               "surface": "carta", "oped_status": "pending", "evidence_grade": "A",
                               "tone_hint": "civic Spanish op-ed"})
    return card_and_handoff(c, CIVIC_MIX_BODY, CIVIC_MIX)


def receipt(c, h, **kw):
    body = dict(handoff_id=h["payload"]["handoff_id"], seal=h["seal"],
                pause_checksum=h["payload"]["pause_checksum"], attested=True, attested_by="user",
                action="acted")
    if kw.get("win_type"):
        body["evidence_url"] = "https://x.com/fixture_user_60/status/42"
    body.update(kw)
    return c.post("/handoff/receipt", json=body)


# ── SE API ──────────────────────────────────────────────────────────────────
def test_se_asset_scope(c):
    r = rec(c, X_WEIRD, SCA)
    assert r["mode"] == "scoped" and r["card"]["asset"]["asset_id"] == SCA
    assert set(r["card"]["slugs"]) <= {"sca-nonweird", "sca-pilot-ethics", "synthetic-societies-validity"}


def test_se_door_scoped_handoff(c):
    _, h = card_and_handoff(c)
    p = h["payload"]
    assert p["door"] == "EconLLM" and p["interest_seed_closed"] and p["asset_id"] == SCA
    assert p["pause_checksum"] and h["seal"]
    assert "cheap-gen-scarce-verify" in p["xbrief_interests"]["paused"]
    assert not set(p["xbrief_interests"]["active"]) & set(p["xbrief_interests"]["paused"])


def test_se_dual_door_kill(c):
    body = dict(url="https://x.com/fixture_user_56/1", outlet="x", snippet="AI governance and AI regulation in the public interest")
    r = rec(c, body)
    assert r["status"] == "killed" and "door_mix" in r["kill_reasons"]


def test_se_dual_door_explicit_from_asset(c):
    c.post("/inventory", json={"asset_id": "asset_gov", "title": "Gov essay", "slugs": ["ai-society-governance"],
                               "door": "Augusto-civic", "evidence_grade": "B",
                               "surface": "substack", "tone_hint": "civic plain"})
    r = rec(c, dict(url="https://x.com/fixture_user_56/1", outlet="x", snippet="ai governance debate"), "asset_gov")
    assert r["ok"] and r["card"]["door"] == "Augusto-civic"


def test_se_attested_receipt(c):
    _, h = card_and_handoff(c)
    assert receipt(c, h, attested=False).status_code == 422
    assert receipt(c, h, attested_by="xbrief-auto").status_code == 422
    assert c.get("/handoff/" + h["payload"]["handoff_id"]).json()["status"] == "sealed"  # never silent clear
    assert receipt(c, h).status_code == 200


def test_se_expired_handoff(c, monkeypatch):
    card, h = card_and_handoff(c, ttl_hours=1)
    real = core._now
    monkeypatch.setattr(core, "_now", lambda: real() + timedelta(hours=2))
    assert c.get("/handoff/" + h["payload"]["handoff_id"]).json()["status"] == "expired_handoff"
    r = receipt(c, h, win_type="claim_named_reply")
    assert r.status_code == 410 and r.json()["error"] == "expired_handoff"
    ev = c.get("/events").json()
    assert not any(e["kind"] == "human" and e.get("human") == "skipped" for e in ev)  # never auto-Skipped
    assert c.get("/wins").json() == []


# ── Adversarial ─────────────────────────────────────────────────────────────
def test_adv_forged_receipt_no_win(c):
    _, h = card_and_handoff(c)
    r = receipt(c, h, seal="0" * 64, win_type="claim_named_reply")
    assert r.status_code == 403 and r.json()["error"] == "forged_receipt"
    r = c.post("/handoff/receipt", json={"handoff_id": "hand_fake", "seal": "x", "pause_checksum": "x",
                                         "attested": True, "attested_by": "user", "action": "acted",
                                         "win_type": "warm_intro"})
    assert r.status_code == 403
    assert c.get("/wins").json() == []


def test_adv_pause_refuse(c):
    _, h = card_and_handoff(c)
    r = receipt(c, h, pause_checksum="", win_type="warm_intro")
    assert r.status_code == 409 and r.json()["error"] == "pause_refused"
    assert c.get("/wins").json() == []


def test_adv_multi_match_block(c):
    body = dict(url="https://x.com/fixture_user_57/1", outlet="x", snippet="non-WEIRD synthetic participants and construct validity of Big Five on LLMs")
    r = rec(c, body)
    assert r["status"] == "asset_pick_required" and r["card"] is None and len(r["asset_options"]) >= 2
    assert c.get("/queue").json()["cards"] == []


def test_adv_expired_handoff(c, monkeypatch):
    test_se_expired_handoff(c, monkeypatch)


def test_adv_no_post_routes(c):
    paths = " ".join(c.get("/openapi.json").json()["paths"]).lower()
    for bad in ("post", "publish", "schedule", "tweet", "share", "oauth"):
        assert bad not in paths.replace("/handoff", "")


def test_adv_lens_mismatch_scout_slug_on_wins(c):
    card, h = card_and_handoff(c)
    r = receipt(c, h, confirmed_lens="gpt4o-weird", win_type="claim_named_reply").json()
    assert r["lens_mismatch"] is True
    w = c.get("/wins").json()
    assert len(w) == 1 and w[0]["slug"] == card["slug"] != "gpt4o-weird"
    assert any(e["kind"] == "lens_mismatch" for e in c.get("/events").json())


def test_adv_replay_receipt(c):
    _, h = card_and_handoff(c)
    assert receipt(c, h, win_type="warm_intro").status_code == 200
    assert receipt(c, h, win_type="warm_intro").status_code == 409
    assert len(c.get("/wins").json()) == 1


# ── Marketing brand ─────────────────────────────────────────────────────────
def test_mkt_asset_tone_on_card(c):
    r = rec(c, X_WEIRD, SCA)["card"]
    assert r["asset"]["type"] == "arxiv" and r["asset"]["tone"] == "academic-finding" and r["lang"] == "en"


def test_mkt_civic_spanish_and_pause_refuse(c):
    # DECISION 2026-10-09 18:05 (BUILD-LOG, supersedes 15:16): the card's outlet decides language.
    # Augusto's X is English-only; Spanish is only for op-eds in Argentine newspapers. A carta card on X is English/social.
    card, h = civic_mix(c)
    assert card["format"] == "social"
    assert card["door"] == "Augusto-civic" and card["lang"] == "en"
    assert "verifi" in card["claim"].lower()
    assert not any(w in (card["draft"] or "").lower() for w in (" la ", " el ", " es ", " de "))
    # Opposite case must fail: a Spanish draft on a carta card on X is blocked.
    from src.voice_gate import check_draft
    es = "La verificación con contexto local importa en Tucumán: las notas de la comunidad no alcanzan sin fuentes de la región."
    g = check_draft(es, card)
    assert not g.ok and "lang_mismatch" in [r.get("code") for r in g.reasons]
    paused = h["payload"]["xbrief_interests"]["paused"]
    assert "sca-nonweird" in paused and "econllm-lab" in paused  # civic pauses EconLLM Active
    assert receipt(c, h, pause_checksum="tampered").status_code == 409


def test_mkt_no_fake_win(c):
    card_and_handoff(c)
    assert c.get("/wins").json() == []  # nothing until attested receipt


# ── DA ──────────────────────────────────────────────────────────────────────
def test_da_scoped_fit_no_borrow(c):
    body = dict(url="https://x.com/fixture_user_55/1", outlet="x", snippet="construct validity of Big Five measurement on LLMs")
    r = rec(c, body, SCA)
    assert r["status"] == "killed" and r["kill_id"] == "empty_fit" and r["card"] is None


def test_da_full_s9_strip(c):
    f = rec(c, X_WEIRD, SCA)["card"]["factors"]
    assert set(f) == {"Fit", "Urgency", "FormatPrior", "Evidence", "DoorMatch", "EffortPenalty"}


def test_da_likes_not_s(c, tmp_path):
    a = rec(c, {**X_WEIRD, "like_count": 0}, SCA)["card"]["S"]
    c2 = TestClient(create_app(str(tmp_path / "b")))
    b = rec(c2, {**X_WEIRD, "like_count": 10**6}, SCA)["card"]["S"]
    assert a == b


def test_da_wins_after_attested_receipt_fields(c):
    card, h = card_and_handoff(c)
    assert c.get("/wins").json() == []
    receipt(c, h, win_type="claim_named_reply")
    w = c.get("/wins").json()[0]
    assert w["asset_id"] == SCA and w["slug"] == card["slug"] and w["outlet"] == "x"
    assert w["win_type"] == "claim_named_reply"


# ── Researcher ──────────────────────────────────────────────────────────────
def test_rs_scoped_fit_only_asset_slugs(c):
    r = rec(c, {**X_WEIRD, "snippet": X_WEIRD["snippet"] + " GPT world values WVS"}, SCA)
    assert set(r["card"]["slugs"]) <= {"sca-nonweird", "sca-pilot-ethics", "synthetic-societies-validity"}
    assert "gpt4o-weird" not in r["card"]["slugs"]


def test_rs_closed_interests_seed(c):
    vocab = {v["slug"] for v in c.get("/fit").json()}
    _, h = card_and_handoff(c)
    i = h["payload"]["xbrief_interests"]
    assert set(i["active"]) | set(i["paused"]) <= vocab
    r = c.post("/inventory", json={"title": "x", "slugs": ["made-up-slug"]})
    assert r.status_code == 422


def test_rs_adepa_evidence_soft_pending(c):
    card, h = civic_mix(c)
    assert h["payload"]["evidence_status"] == "soft_pending" and h["payload"]["evidence_grade"] != "A"
    r = receipt(c, h, confirmed_lens="verification-local-context", win_type="evidence_ab").json()
    assert r["win"] is None and r["win_refused"] == "evidence_soft_pending"


def test_rs_civic_handoff_pauses_econllm(c):
    _, h = civic_mix(c)
    i = h["payload"]["xbrief_interests"]
    econ = {v["slug"] for v in c.get("/fit").json() if v["door"] == "EconLLM"}
    assert econ <= set(i["paused"]) and not econ & set(i["active"])


def test_rs_sca_arxiv_scoped_only_sca(c):
    r = rec(c, X_WEIRD, SCA)
    assert all(s.startswith("sca-") or s == "synthetic-societies-validity" for s in r["card"]["slugs"])


def test_rs_adepa_carta_spanish_civic(c):
    r = rec(c, CIVIC, ADEPA)["card"]
    assert r["asset"]["type"] == "carta" and r["asset"]["lang"] == "es" and r["door"] == "Augusto-civic"


def test_rs_tone_clash_civic_on_sca(c):
    r = rec(c, CIVIC, SCA)
    assert r["status"] == "killed" and "empty_fit" in r["kill_reasons"] and "door_mix" in r["kill_reasons"]


def test_mkt_asset_surface_tone_hint_from_inventory(c):
    """Card chrome uses inventory surface + tone_hint verbatim; never URL-inferred."""
    r = rec(c, X_WEIRD, SCA)["card"]["asset"]
    assert r["surface"] == "arxiv" and r["type"] == "arxiv" and r["tone_hint"] == "EconLLM technical / methods"
    civ = rec(c, CIVIC, ADEPA)["card"]["asset"]
    assert civ["surface"] == "carta" and civ["tone_hint"] == "Augusto-civic: English on X/LinkedIn, Spanish only for op-eds / soft Evidence if pending"  # BUILD-LOG 18:05 language rule
    # an asset whose URL says arxiv but whose inventory surface says substack must render substack
    a = c.post("/inventory", json={"title": "t", "url": "https://arxiv.org/abs/1", "slugs": ["econ-ai-cas"],
                                   "surface": "substack", "tone_hint": "public essay", "door": "EconLLM"}).json()
    assert a["type"] == "substack" and a["tone_hint"] == "public essay"
    b = c.post("/inventory", json={"title": "u", "url": "https://arxiv.org/abs/2", "slugs": ["econ-ai-cas"],
                                   "tone_hint": "x", "door": "EconLLM"})
    assert b.status_code == 422 and b.json()["code"] == "surface_required"  # no guessing from URL


def test_rs_seed_doors_match_registry():
    """x-brief closed seed door labels must agree with the API door registry (dual-door slugs exempt)."""
    import re
    md = (core.ROOT / "data" / "xbrief-interests-seed.md").read_text().split("## Active")[1].split("## Paused")[0]
    for slug, door in re.findall(r"^- `([a-z0-9-]+)` \[([^\]]+)\]", md, re.M):
        reg = core.slug_door(slug)
        assert reg is None or reg == door, (slug, door, reg)


def test_se_queue_scoped_to_selected_asset(c):
    """Scope-bug regression (2026-10-09): /queue?asset_id= returns only that asset's cards; no borrow."""
    rec(c, X_WEIRD, SCA)
    rec(c, CIVIC, ADEPA)
    full = c.get("/queue").json()["cards"]
    assert {x["asset"]["asset_id"] for x in full} >= {SCA, ADEPA}
    for aid in (SCA, ADEPA):
        q = c.get("/queue", params={"asset_id": aid}).json()
        assert q["selected_asset"]["asset_id"] == aid
        assert q["cards"] and all(x["asset"]["asset_id"] == aid for x in q["cards"])


# ── x-brief alignment (slice 4) ─────────────────────────────────────────────
XB_ORDER = ["sca-nonweird", "sca-rag-profiles", "cvp-measurement-layer", "cvp-not-identification",
            "ai-measurement-policy", "complexity-policy", "abm-organizations", "abm-nroy-policy",
            "ai-society-governance", "human-ai-collective-action"]


def test_rs_xbrief_seed_active_rank():
    assert core.xbrief_active() == XB_ORDER
    md = (core.ROOT / "data" / "xbrief-interests-seed.md").read_text()
    import re
    marked = re.findall(r"^- `([a-z0-9-]+)`.*xbrief_active: (?:true|false); xbrief_rank: ", md, re.M)
    assert len(marked) == 21


def test_rs_xbrief_seed_vault_sync():
    """Seed active list must match x-brief's own Interests.md Active section (read-only)."""
    from pathlib import Path
    vault = Path.home() / "Documents" / "x-brief-vault" / "Profile" / "Interests.md"
    if not vault.exists():
        pytest.skip("x-brief vault not on this machine")
    import re
    body = vault.read_text().split("## Active")[1].split("##")[0]
    assert re.findall(r"^- ([a-z0-9-]+) —", body, re.M) == XB_ORDER


def test_adv_no_lens_all_off_list(c):
    r = rec(c, CIVIC, ADEPA)
    assert r["ok"] and r["card"]["xbrief_slugs"] == []
    cid = r["card"]["card_id"]
    # Designer 2026-10-13 Q1: draft present → Copy enabled (not no_lens).
    if (r["card"].get("draft") or "").strip():
        assert r["card"]["handoff_blocked"] is None
        assert c.post("/handoff", json={"card_id": cid}).status_code == 200
    else:
        assert r["card"]["handoff_blocked"] == "no_lens"
        h = c.post("/handoff", json={"card_id": cid})
        assert h.status_code == 409 and h.json()["code"] == "no_lens"
    assert any(x["card_id"] == cid for x in c.get("/queue").json()["cards"])


def test_se_mixed_card_hands_off_only_active_in_rank(c):
    card, h = civic_mix(c)
    assert h["payload"]["xbrief_slugs"] == ["ai-society-governance"]
    assert "verification-local-context" in card["slugs"]
    assert h["payload"]["xbrief_active_count"] == 10
    _, h2 = card_and_handoff(c)
    ranks = [XB_ORDER.index(s) for s in h2["payload"]["xbrief_slugs"]]
    assert ranks == sorted(ranks) and set(h2["payload"]["xbrief_slugs"]) <= set(XB_ORDER)


def test_mkt_civic_post_english_oped_spanish(c):
    c.post("/inventory", json={"asset_id": "asset_gov", "title": "Gov essay", "slugs": ["ai-society-governance"],
                               "door": "Augusto-civic", "surface": "substack", "tone_hint": "civic plain"})
    r = rec(c, dict(url="https://x.com/fixture_user_56/1", outlet="x", snippet="ai governance debate"), "asset_gov")["card"]
    assert r["lang"] == "en" and r["format"] == "social" and r["source_chip"] is None
    assert not any(w in (r["draft"] or "").lower() for w in (" la ", " el ", " es ", " de "))
    li = rec(c, dict(url="https://linkedin.com/p/1", outlet="linkedin", snippet="ai governance debate"), "asset_gov")
    assert li["card"]["lang"] == "en" and "Afirmación" not in (li["card"]["draft"] or "")
    # Outlet decides (decision 18:05): the carta promoted on X is English/social, ES chip hidden.
    op = rec(c, CIVIC, ADEPA)["card"]
    assert op["lang"] == "en" and op["format"] == "social" and op["source_chip"] is None
    # Spanish op-ed cards get their own test once an op-ed outlet exists.


JARGON = ["θ", "nomological", "partial id", "identification", "admissible", "construct validity"]


def test_mkt_plain_words_in_drafts(c):
    """Plain-words rule: no unexplained technical terms in drafts."""
    bodies = [(X_WEIRD, SCA), (dict(url="https://linkedin.com/p/2", outlet="linkedin",
                                     snippet="Big Five measurement on LLMs, which prompt is valid"), "asset_cvprofiles")]
    for b, a in bodies:
        r = rec(c, b, a)
        if r.get("card"):
            d = (r["card"]["draft"] or "").lower()   # X template drafts are blank at view time (2026-10-14)
            assert not [j for j in JARGON if j in d], d


def test_handoff_payload_has_no_samples_or_draft(c):
    _, h = card_and_handoff(c)
    p = h["payload"]
    assert "draft" not in p and "samples" not in p and "writing_samples" not in p
    assert not any(isinstance(v, str) and len(v) > 400 for v in p.values())


# ── room asks 2026-10-09 ────────────────────────────────────────────────────
def test_se_health_reports_data_and_scoring(c):
    h = c.get("/health").json()
    assert h["ok"] and h["data_loaded"] and h["scoring_loaded"] and h["topics"] == 21


def test_se_errors_plain_code_message(c):
    r = c.post("/recommend", json={"outlet": "x"})
    j = r.json()
    assert r.status_code == 422 and j["code"] == "bad_request" and "url" in j["message"]
    assert "loc" not in str(j) and "type_error" not in str(j)
    r2 = c.post("/handoff", json={"card_id": "nope"}).json()
    assert r2["code"] == "unknown_card" and r2["message"]


def test_se_recommend_timing(c):
    r = rec(c, X_WEIRD, SCA)
    assert r["started_at"] and r["duration_ms"] >= 0


def test_adv_pending_handoffs_survive_reload(c):
    card, h = card_and_handoff(c)
    p = c.get("/handoff", params={"status": "pending"}).json()
    assert len(p) == 1 and p[0]["payload"]["handoff_id"] == h["payload"]["handoff_id"]
    assert p[0]["expires_at"] == h["payload"]["expires_at"] and p[0]["seal"] == h["seal"]
    receipt(c, h, win_type="warm_intro")
    assert c.get("/handoff", params={"status": "pending"}).json() == []
    assert receipt(c, h, win_type="warm_intro").json()["code"] == "already_received"
    assert len(c.get("/wins").json()) == 1


def test_da_add_asset_form_rules(c):
    base = {"title": "New essay", "slugs": ["complexity-policy"], "surface": "substack",
            "tone_hint": "plain", "door": "EconLLM"}
    ok = c.post("/inventory", json=base)
    assert ok.status_code == 200 and ok.json()["door"] == "EconLLM" and ok.json()["asset_id"].startswith("asset_")
    for k, code in (("surface", "surface_required"), ("tone_hint", "tone_required"), ("door", "door_required")):
        r = c.post("/inventory", json={**base, k: "" if k != "surface" else "tiktok"})
        assert r.status_code == 422 and r.json()["code"] == code and r.json()["message"]
    r = c.post("/inventory", json={**base, "slugs": ["not-a-topic"]})
    assert r.json()["code"] == "closed_vocab"
    r = c.post("/inventory", json={**base, "asset_id": SCA})
    assert r.status_code == 409 and r.json()["code"] == "asset_id_taken"
