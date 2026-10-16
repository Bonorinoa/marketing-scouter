"""se_ MS_FIT_GRADED_MODE=model, graded ties → held asset_tie, promo/brand independent of fit kills, econllm seed."""
import json
from pathlib import Path

import pytest

from tests.test_fit_either_se import FakeGrader, X, run, mk  # noqa: F401 (fixture)
from tests.test_intake_contract import T_NOFIT, T_SCA

ROOT = Path(__file__).resolve().parent.parent
OLD_ECON = "EconLLM Lab combines games, experiments, LLM agents, and complex-systems methods to study heterogeneous behavior."


def ev(api, kind):
    return [e for e in api.events() if e["kind"] == kind]


@pytest.mark.parametrize("mode,want", [("model", "held"), ("either", "queued")])
def test_se_phrase_copy_word_pass_graded_none(mk, monkeypatch, mode, want):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", mode)
    c, api = mk(FakeGrader({}))                     # word filter passes T_SCA; grader says none
    row = run(c, [X(1000000000000101)])[0]
    assert row["status"] == want, row
    if mode == "model":
        e = ev(api, "fit_model")[-1]
        assert row["reasons"] == ["grader_disagrees"] and not row.get("predrafted")
        assert e["n_grader_disagrees"] == 1 and e["grader_disagrees_ids"] == ["1000000000000101"]
        assert c.get("/status").json()["queue_size"] == 0


def test_se_model_grader_none_without_word_pass_still_killed(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    c, api = mk(FakeGrader({}))
    row = run(c, [X(1000000000000109, T_NOFIT)])[0]
    assert row["status"] == "killed" and row["reasons"] == ["empty_fit"]
    assert ev(api, "fit_model")[-1]["n_grader_disagrees"] == 0


def test_se_model_claim_queued_and_drafted(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    c, api = mk(FakeGrader({T_SCA: "claim"}))
    row = run(c, [X(1000000000000102)])[0]
    assert row["status"] == "queued" and row.get("predrafted") and row["fit_level"] == "claim"


def test_se_model_grader_down_falls_back_to_words(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    c, api = mk(FakeGrader(boom=True))
    rows = run(c, [X(1000000000000103), X(1000000000000104, T_NOFIT)])
    assert rows[0]["status"] == "held" and rows[0]["reasons"] == ["grader_fallback"] and not rows[0].get("predrafted")
    assert rows[1]["reasons"] == ["empty_fit"]
    e = ev(api, "fit_model")[-1]
    assert ev(api, "fit_grader_unavailable") and e["n_word_fallback"] == 1 and e["n_fallback_held"] == 1


def test_se_model_capped_falls_back_to_words(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    monkeypatch.setenv("MS_FIT_SHADOW_MAX_CALLS", "0")
    g = FakeGrader({})
    c, api = mk(g)
    row = run(c, [X(1000000000000105)])[0]
    assert row["status"] == "held" and row["reasons"] == ["grader_fallback"] and g.calls == []
    assert ev(api, "fit_model")[-1]["cap_hit"] is True


@pytest.mark.parametrize("mode", ["model", "either"])
def test_se_tie_is_held_with_all_assets(mk, monkeypatch, mode):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", mode)
    t = "Synthetic respondents keep failing culture tests in every survey we try"
    c, api = mk(FakeGrader({t: "claim"}, claim_has="WEIRD"))   # claim on the 2 WEIRD assets → tie
    row = run(c, [X(1000000000000106, t)])[0]
    assert row["status"] == "held" and row["reasons"] == ["asset_tie"], row
    assert len(row["asset_options"]) >= 2 and not row.get("predrafted")
    assert c.get("/status").json()["queue_size"] == 0
    assert ev(api, f"fit_{mode}")[-1]["n_asset_tie"] == 1


def test_se_graded_mode_tie_held(mk, monkeypatch):
    monkeypatch.delenv("MS_FIT_GRADED_MODE", raising=False)
    monkeypatch.setenv("MS_FIT_GRADED", "1")
    t = "Synthetic respondents keep failing culture tests in every survey we try"
    c, api = mk(FakeGrader({t: "topic"}, claim_has="WEIRD"))
    row = run(c, [X(1000000000000107, t)])[0]
    assert row["status"] == "held" and row["reasons"] == ["asset_tie"] and len(row["asset_options"]) >= 2


def test_se_shadow_counts_ties(mk, monkeypatch):
    monkeypatch.delenv("MS_FIT_GRADED_MODE", raising=False)
    monkeypatch.setenv("MS_FIT_SHADOW", "1")
    c, api = mk(FakeGrader({T_SCA: "claim"}, claim_has=None))
    api.fit_shadow_sync = True
    run(c, [X(1000000000000108)])
    assert ev(api, "fit_shadow")[-1]["n_asset_tie"] == 1


@pytest.mark.parametrize("mode", [None, "either", "model"])
def test_se_promo_and_brand_reported_with_empty_fit(mk, monkeypatch, mode):
    if mode:
        monkeypatch.setenv("MS_FIT_GRADED_MODE", mode)
    else:
        monkeypatch.delenv("MS_FIT_GRADED_MODE", raising=False)
    c, api = mk(FakeGrader({}))
    rows = run(c, [X(1000000000000110, "Great sunset tonight. Book a demo at https://acme.io/demo"),
                   X(1000000000000111, "Great sunset tonight, free trial https://acme.io/pricing")])
    assert set(rows[0]["reasons"]) >= {"empty_fit", "promo_cta"} and rows[0]["labels"] == ["brand_post"]
    assert rows[1]["reasons"] == ["empty_fit"] and rows[1]["labels"] == ["brand_post"]


def test_se_econllm_seed_is_approved_text():
    row = next(a for a in json.loads((ROOT / "data" / "seed_inventory.json").read_text())
               if a["asset_id"] == "asset_econllm_lab")
    # 2026-10-13 21:57 PT Augusto approved the Combining-games wording; pending field removed
    assert row["one_line_claim"] == ("Combining games, experiments, LLM agents, and complex-systems methods "
                                     "is a productive way to study heterogeneous behavior.")
    assert "one_line_claim_pending" not in row


N_ASSETS = 8
WORDY = [T_SCA + f" (take {i})" for i in range(5)]


def test_se_model_cap_two_posts_then_fallback_held(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    monkeypatch.setenv("MS_FIT_SHADOW_MAX_CALLS", "2")   # budget = 2 posts (cap counts posts)
    g = FakeGrader({t: "claim" for t in WORDY})
    c, api = mk(g)
    rows = run(c, [X(1000000000000201 + i, t) for i, t in enumerate(WORDY)])
    assert [r["status"] for r in rows[:2]] == ["queued", "queued"]
    assert all(r["status"] == "held" and r["reasons"] == ["grader_fallback"] and not r.get("predrafted") for r in rows[2:])
    e = ev(api, "fit_model")[-1]
    assert e["posts_graded"] == 2 and e["n_grader_calls"] == 2 * N_ASSETS and e["cap_hit"] is True
    assert e["n_fallback_held"] == 3 and c.get("/status").json()["queue_size"] == 2
    assert len(g.calls) == 2 * N_ASSETS


def test_se_model_junk_and_hard_kills_do_not_burn_cap(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    monkeypatch.setenv("MS_FIT_SHADOW_MAX_CALLS", "1")
    g = FakeGrader({WORDY[0]: "claim"})
    c, api = mk(g)
    junk = [X(1000000000000301, "LLM agents non-WEIRD #ai #llm #survey #weird #gpt #culture"),
            X(1000000000000302, T_SCA + " book a demo now"),
            X(1000000000000303, T_SCA + " congrats everyone"),
            X(1000000000000304, T_SCA + " link in bio"),
            {"url": "https://example.com/x", "text": T_SCA}]           # refused
    rows = run(c, junk + [X(1000000000000305, WORDY[0]), X(1000000000000305, WORDY[0])])  # + duplicate
    assert set(g.calls) == {WORDY[0]} and len(g.calls) == N_ASSETS
    assert rows[5]["status"] == "queued" and rows[6]["status"] == "duplicate"
    assert ev(api, "fit_model")[-1]["n_grader_calls"] == N_ASSETS


def test_se_model_grader_down_all_word_passers_held(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    c, api = mk(FakeGrader(boom=True))
    rows = run(c, [X(1000000000000401 + i, t) for i, t in enumerate(WORDY)])
    assert all(r["status"] == "held" and r["reasons"] == ["grader_fallback"] for r in rows)
    assert ev(api, "fit_model")[-1]["n_fallback_held"] == 5 and c.get("/status").json()["queue_size"] == 0


def test_se_model_cap_resets_between_runs(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    monkeypatch.setenv("MS_FIT_SHADOW_MAX_CALLS", "1")
    g = FakeGrader({t: "claim" for t in WORDY})
    c, api = mk(g)
    a = run(c, [X(1000000000000501, WORDY[0]), X(1000000000000502, WORDY[1])], rid="discovery-r1")
    b = run(c, [X(1000000000000503, WORDY[2]), X(1000000000000504, WORDY[3])], rid="discovery-r2")
    assert [r["status"] for r in a] == ["queued", "held"] and [r["status"] for r in b] == ["queued", "held"]
    e1, e2 = ev(api, "fit_model")[-2:]
    assert e1["n_grader_calls"] == e2["n_grader_calls"] == N_ASSETS and e1["cap_hit"] and e2["cap_hit"]


class EmptyGrader(FakeGrader):
    def __call__(self, text, claim):
        self.calls.append(text)
        return ""


def test_se_model_empty_reply_is_fallback_hold(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    c, api = mk(EmptyGrader())
    row = run(c, [X(1000000000000601)])[0]
    assert row["status"] == "held" and row["reasons"] == ["grader_fallback"]
    assert ev(api, "fit_model")[-1]["n_grader_empty"] == 1


def test_se_either_empty_reply_uses_word_filter(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "either")
    c, api = mk(EmptyGrader())
    rows = run(c, [X(1000000000000602), X(1000000000000603, T_NOFIT)])
    assert rows[0]["status"] == "queued" and rows[1]["reasons"] == ["empty_fit"]
    assert ev(api, "fit_either")[-1]["n_grader_empty"] == 2


def test_se_shadow_skips_post_on_empty_reply(mk, monkeypatch):
    monkeypatch.delenv("MS_FIT_GRADED_MODE", raising=False)
    monkeypatch.setenv("MS_FIT_SHADOW", "1")
    c, api = mk(EmptyGrader())
    api.fit_shadow_sync = True
    run(c, [X(1000000000000604)])
    e = ev(api, "fit_shadow")[-1]
    assert e["posts_graded"] == 0 and e["posts_skipped_error"] == 1 and e["n_grader_empty"] == 1
    assert e["word_passed_graded_none"] == []


def test_se_model_empty_reply_no_word_match_held_not_killed(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    c, api = mk(EmptyGrader())
    row = run(c, [X(1000000000000605, T_NOFIT)])[0]
    assert row["status"] == "held" and row["reasons"] == ["grader_fallback"]
    e = ev(api, "fit_model")[-1]
    assert e["n_grader_empty"] == 1 and e["n_fallback_held"] == 1


def test_se_model_grader_down_no_word_match_still_killed(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    c, api = mk(FakeGrader(boom=True))           # transport error (not empty reply): unchanged
    assert run(c, [X(1000000000000606, T_NOFIT)])[0]["reasons"] == ["empty_fit"]


# ---- votes + weak ties --------------------------------------------------------------------------------

class SeqGrader(FakeGrader):
    """Returns successive answers per call (to simulate vote splits)."""
    def __init__(self, seq, votes=3):
        super().__init__({})
        self.seq, self.votes = list(seq), votes

    def __call__(self, text, claim):
        self.calls.append(text)
        return self.seq.pop(0) if self.seq else "none"


@pytest.mark.parametrize("seq,want", [
    (["claim", "claim", "none"], "claim"), (["claim", "topic", "none"], "topic"),
    (["claim", "none", "none"], "none"), (["topic", "topic", "claim"], "topic"), (["claim"] * 3, "claim")])
def test_se_votes_2_of_3(seq, want):
    from src import fit_graded as fg
    assert fg.combine_votes(seq) == want
    lvl, _, src = fg.graded_level("Some real argument text about agents and data.", "p1", "a1", "claim", SeqGrader(seq))
    assert (lvl, src) == (want, "model")


def test_se_votes_default_1_and_cache_key():
    from src import fit_graded as fg
    assert fg.votes() == 1
    g1, g3 = SeqGrader([], votes=1), SeqGrader([], votes=3)
    assert fg.cache_version(g1) != fg.cache_version(g3) and fg.cache_version(g3).endswith("#v3")


def test_se_votes_cap_counts_posts_not_calls(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    monkeypatch.setenv("MS_FIT_SHADOW_MAX_CALLS", "2")
    g = SeqGrader(["claim"] * 100, votes=3)
    c, api = mk(g)
    run(c, [X(1000000000000700 + i, T_SCA + f" take {i}") for i in range(4)])
    e = ev(api, "fit_model")[-1]
    assert e["posts_called"] == 2 and e["cap_hit"] and len(g.calls) % 3 == 0 and len(g.calls) >= 6


def test_se_weak_tie_three_assets_held(mk, monkeypatch):
    monkeypatch.setenv("MS_FIT_GRADED_MODE", "model")
    class AllTopic(FakeGrader):
        def __call__(self, text, claim):
            self.calls.append(text)
            return "topic"
    c, api = mk(AllTopic({}))
    rows = run(c, [X(1000000000000710, T_SCA)])
    assert len([a for a in api.store.list_assets() if a.slugs]) >= 3
    if True:
        assert rows[0]["status"] == "held" and rows[0]["reasons"] == ["asset_tie_weak"]
        assert len(rows[0]["asset_options"]) >= 3
        assert ev(api, "fit_model")[-1]["n_asset_tie_weak"] == 1
