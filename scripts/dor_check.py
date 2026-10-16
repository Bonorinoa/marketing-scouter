"""Run the manual-test DoR strips and write reports/dor-YYYY-MM-DD.{html,json}.

Green only when EVERY case in every strip passes. UI cases (`ui:<id>`) come from web/ vitest DOM + source asserts (web/src/test/ui_checks.test.tsx);
OpenAPI/pytest green alone never flips a chrome strip.

Also hard-gates color-token leaks and Playwright card-visibility AA checks.
"""
from __future__ import annotations

import html
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRIPS = {
    "SE": [("asset-scope", ["test_se_asset_scope", "test_se_queue_scoped_to_selected_asset", "ui:scope_queue"]),
           ("UX feedback: health dot, offline disables actions", ["ui:api_offline"]), ("door-scoped handoff", ["test_se_door_scoped_handoff"]),
           ("dual-door kill", ["test_se_dual_door_kill", "test_se_dual_door_explicit_from_asset"]),
           ("attested receipt", ["test_se_attested_receipt"]), ("expired_handoff", ["test_se_expired_handoff"]),
           ("API: health data+scoring, plain {code,message} errors, recommend timing", ["test_se_health_reports_data_and_scoring", "test_se_errors_plain_code_message", "test_se_recommend_timing"]),
           ("x-brief: mixed card hands off only active slugs in rank order", ["test_se_mixed_card_hands_off_only_active_in_rank"])],
    "Adversarial": [("forged receipt → no Win", ["test_adv_forged_receipt_no_win", "test_adv_replay_receipt"]),
                    ("pause refuse", ["test_adv_pause_refuse"]), ("multi-match block", ["test_adv_multi_match_block"]),
                    ("expired_handoff", ["test_adv_expired_handoff"]),
                    ("no Post chrome (DOM + source)", ["test_adv_no_post_routes", "ui:no_post_chrome"]),
                    ("lens_mismatch → Scout slug on Wins", ["test_adv_lens_mismatch_scout_slug_on_wins"]),
                    ("card visibility AA (Playwright)", ["ui:card_visibility"]),
                    ("color tokens confined", ["ui:color_tokens"]),
                    ("UX traps: copy failure visible, killed persists, pending survives reload", ["ui:copy_failure_visible", "ui:killed_persists", "test_adv_pending_handoffs_survive_reload", "ui:pending_survives_reload"]),
                    ("no_lens: all-off-list card can't hand off", ["test_adv_no_lens_all_off_list", "ui:no_lens_disabled"]),
                    ("handoff carries no samples or draft text", ["test_handoff_payload_has_no_samples_or_draft"])],
    "Marketing": [("asset tone on card (title·type·door·tone_hint from inventory)",
                   ["test_mkt_asset_tone_on_card", "test_mkt_asset_surface_tone_hint_from_inventory", "ui:asset_tone_card"]),
                  ("language: X/LI English, Spanish + ES · op-ed chip only on op-eds", ["test_mkt_civic_post_english_oped_spanish", "ui:es_chip_oped_only"]),
                  ("plain words in drafts + invariants in How it works", ["test_mkt_plain_words_in_drafts", "ui:invariants_in_guide", "ui:copy_names_asset_door"]),
                  ("civic op-ed Spanish + pause refuse", ["test_mkt_civic_spanish_and_pause_refuse", "ui:civic_spanish",
                                                    "ui:civic_pause_chrome"]),
                  ("no fake Win", ["test_mkt_no_fake_win"]),
                  ("UX foundations: onboarding, purpose + empty state per tab, plain kill reasons", ["ui:ux_foundations", "ui:scout_outcome", "ui:ux_views"]),
                  ("card visibility AA (Playwright)", ["ui:card_visibility"])],
    "DA": [("scoped Fit no-borrow", ["test_da_scoped_fit_no_borrow"]), ("full §9", ["test_da_full_s9_strip", "ui:s9_complete"]),
           ("likes≠S (no chip)", ["test_da_likes_not_s", "ui:likes_not_chip"]),
           ("Wins only after attested receipt w/ asset_id+slug+outlet",
            ["test_da_wins_after_attested_receipt_fields", "test_win_sheet_column_order_includes_asset_id", "test_spa_win_columns_mirror_sheet_schema", "ui:attest_required"]),
           ("Add asset form: closed pick lists, plain refusals", ["test_da_add_asset_form_rules", "ui:add_asset_form"])],
    "Researcher": [("scoped Fit = asset slugs only", ["test_rs_scoped_fit_only_asset_slugs"]),
                   ("closed interests seed", ["test_rs_closed_interests_seed", "test_rs_seed_doors_match_registry",
                                              "ui:closed_fit_list"]),
                   ("Adepa Evidence soft/pending", ["test_rs_adepa_evidence_soft_pending", "ui:evidence_soft"]),
                   ("civic handoff pauses EconLLM Active (chrome + API)", ["test_rs_civic_handoff_pauses_econllm",
                                                                         "ui:civic_pause_chrome"]),
                   ("scoped SCA arXiv → sca/synthetic-societies only", ["test_rs_sca_arxiv_scoped_only_sca"]),
                   ("construct-validity on SCA → empty_fit", ["test_da_scoped_fit_no_borrow"]),
                   ("Adepa carta Spanish civic", ["test_rs_adepa_carta_spanish_civic"]),
                   ("x-brief seed: 10 active in rank + vault sync", ["test_rs_xbrief_seed_active_rank", "test_rs_xbrief_seed_vault_sync"])],
}


def run_color_lint() -> bool:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "lint_tokens.py")], cwd=ROOT, capture_output=True, text=True)
    print(r.stdout or "")
    if r.returncode != 0:
        print(r.stderr or "", file=sys.stderr)
    return r.returncode == 0


def run_ui_checks() -> set[str]:
    """Run web/ vitest DOM+source checks; return ids of passing `ui:<id>` tests (written to reports/ui_checks.json)."""
    out = ROOT / "reports" / "_ui_vitest.json"
    out.unlink(missing_ok=True)
    subprocess.run(["npx", "vitest", "run", "--reporter=json", f"--outputFile={out}"], cwd=ROOT / "web",
                   capture_output=True)
    done: set[str] = set()
    if out.exists():
        for f in json.loads(out.read_text()).get("testResults", []):
            for t in f.get("assertionResults", []):
                title = t.get("title", "")
                if title.startswith("ui:") and t.get("status") == "passed":
                    done.add(title[3:].split(" ")[0])
    (ROOT / "reports" / "ui_checks.json").write_text(json.dumps(sorted(done)))
    return done


def run_card_visibility() -> bool:
    """Playwright card visibility + AA at 1280x800 and 390x844."""
    report = ROOT / "reports" / "_card_visibility.json"
    report.unlink(missing_ok=True)
    r = subprocess.run(
        ["npx", "playwright", "test", "--reporter=json"],
        cwd=ROOT / "web",
        capture_output=True,
        text=True,
    )
    # playwright json reporter prints to stdout
    payload = r.stdout.strip()
    ok = r.returncode == 0
    try:
        data = json.loads(payload) if payload.startswith("{") else {}
        report.write_text(json.dumps({"ok": ok, "returncode": r.returncode, "summary": {
            "expected": data.get("stats", {}).get("expected"),
            "unexpected": data.get("stats", {}).get("unexpected"),
            "skipped": data.get("stats", {}).get("skipped"),
        }}, indent=2))
    except json.JSONDecodeError:
        report.write_text(json.dumps({"ok": ok, "returncode": r.returncode, "stdout_tail": payload[-2000:], "stderr_tail": (r.stderr or "")[-2000:]}))
    if not ok:
        print("card_visibility FAIL", (r.stderr or "")[-1500:], (r.stdout or "")[-1500:], file=sys.stderr)
    return ok


def main() -> int:
    # Hard gate: color literals outside tokens.css fail the run before strips.
    color_ok = run_color_lint()
    ui_done = run_ui_checks()
    if color_ok:
        ui_done.add("color_tokens")
    vis_ok = run_card_visibility()
    if vis_ok:
        ui_done.add("card_visibility")
        ui_done.add("ux_views")
    (ROOT / "reports" / "ui_checks.json").write_text(json.dumps(sorted(ui_done)))

    xml = ROOT / "reports" / "_junit.xml"
    subprocess.run([sys.executable, "-m", "pytest", "-q", "tests", f"--junitxml={xml}"], cwd=ROOT,
                   capture_output=True)
    res = {}
    for tc in ET.parse(xml).getroot().iter("testcase"):
        res[tc.get("name")] = not any(ch.tag in ("failure", "error", "skipped") for ch in tc)
    out, green = {}, True
    for strip, cases in STRIPS.items():
        rows = []
        for label, tests in cases:
            fails = [t for t in tests if (t.startswith("ui:") and t[3:] not in ui_done) or
                     (not t.startswith("ui:") and not res.get(t, False))]
            rows.append({"case": label, "pass": not fails,
                         "why": ", ".join(f"ui:{t[3:]} (DOM/source assert failing)" if t.startswith("ui:") else t for t in fails)})
        ok = all(r["pass"] for r in rows)
        green &= ok
        out[strip] = {"pass": ok, "cases": rows}
    # color leak also forces red even if somehow unmapped
    if not color_ok:
        green = False
        out.setdefault("Adversarial", {"pass": False, "cases": []})
        out["Adversarial"]["pass"] = False
    day = datetime.now().strftime("%Y-%m-%d")
    report = {"date": day, "dor_green": green, "pytest_total": len(res), "pytest_pass": sum(res.values()),
              "color_lint": color_ok, "card_visibility": vis_ok, "strips": out}
    (ROOT / "reports" / f"dor-{day}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    body = "".join(
        f"<h3>{s} — {'PASS' if v['pass'] else 'FAIL'}</h3><ul>" +
        "".join(f"<li>{'✅' if r['pass'] else '❌'} {html.escape(r['case'])}"
                f"{' — ' + html.escape(r['why']) if r['why'] else ''}</li>" for r in v["cases"]) + "</ul>"
        for s, v in out.items())
    (ROOT / "reports" / f"dor-{day}.html").write_text(
        f"<html><meta charset='utf-8'><body style='font-family:sans-serif'><h2>Market Scouter DoR — {day}</h2>"
        f"<p>DoR {'GREEN' if green else 'NOT READY'} · pytest {report['pytest_pass']}/{report['pytest_total']}"
        f" · color_lint {'OK' if color_ok else 'FAIL'} · card_visibility {'OK' if vis_ok else 'FAIL'}</p>"
        f"{body}</body></html>")
    print(json.dumps({k: v["pass"] for k, v in out.items()} | {"dor_green": green, "color_lint": color_ok, "card_visibility": vis_ok}))
    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(main())
