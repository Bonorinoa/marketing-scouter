"""View-time draft cleanup for cards (2026-10-14). Covers old stored rows: never trust card.draft_text as-is.

Main copy never carries the caveat; "Copy with caveat" is a quieter secondary action.
"""
from __future__ import annotations

from typing import Optional

TEMPLATE_LINE = "No draft: the basic drafter can only repeat your claim, so this one is left blank."
REPEAT_LINE = "No draft: this draft repeated your claim or caveat, so it's left blank."
COPY_WITH_CAVEAT_LABEL = "Copy with caveat"
COPY_WITH_CAVEAT_TOOLTIP = "Copies the draft with the caveat as its last line. Whether readers see the caveat is your call."
BLOCKING = {"claim_overlap", "caveat_in_draft", "claim_restated"}


def _model_origin(pre: Optional[dict]) -> bool:
    if not pre or pre.get("status") != "ok":
        return False
    m = str(pre.get("model") or "")
    return bool(m) and m not in ("unknown", "local_template") and not m.startswith("local")


def clean_draft(draft: Optional[str], pre: Optional[dict], outlet: str, gate_card: dict) -> dict:
    """-> {draft, copy_enabled|None, no_draft, no_draft_line, draft_with_caveat}."""
    from ..voice_gate import caveat_in, check_draft, strip_caveat
    cav = (gate_card.get("asset_caveat") or "").strip()
    out = {"draft": draft, "no_draft": False, "no_draft_line": None, "draft_with_caveat": None,
           "copy_with_caveat_label": None, "copy_with_caveat_tooltip": None, "copy_override": None}
    if not (draft or "").strip():
        return out
    blank = {"draft": None, "no_draft": True, "copy_override": False}
    if outlet == "x" and not _model_origin(pre):
        return {**out, **blank, "no_draft_line": TEMPLATE_LINE}
    text = strip_caveat(draft, cav)
    if not text.strip() or (cav and caveat_in(text, cav)):
        return {**out, **blank, "no_draft_line": REPEAT_LINE}
    gate = check_draft(text, gate_card)
    if {r["code"] for r in gate.reasons} & BLOCKING:
        return {**out, **blank, "no_draft_line": REPEAT_LINE}
    out["draft"] = text
    if text != draft:
        out["copy_override"] = bool(gate.ok)
    if cav:
        out.update(draft_with_caveat=f"{text.rstrip()}\n\n{cav}", copy_with_caveat_label=COPY_WITH_CAVEAT_LABEL,
                   copy_with_caveat_tooltip=COPY_WITH_CAVEAT_TOOLTIP)
    return out


def raw_draft(draft: Optional[str], pre: Optional[dict], outlet: str, gate_card: dict) -> dict:
    """Internal (drafter input / probe): stored seed as-is, never shown or copied."""
    return {"draft": draft, "no_draft": False, "no_draft_line": None, "draft_with_caveat": None,
            "copy_with_caveat_label": None, "copy_with_caveat_tooltip": None, "copy_override": None}
