"""Market Scouter — Streamlit entry (suggests only; never posts)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # repo root (app lives in legacy/)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from src.events import EventLog, win_aggregates
from src.fit import load_fit_slugs
from src.models import (
    CardState,
    EventKind,
    HumanAction,
    Outlet,
    ScoutEvent,
    WinSignal,
)
from src.pipeline import ScoutRunner
from src.seed import ensure_seeded
from src.store import Store
from legacy.theme import card_html, hero_html, inject_css
from src.win_export import WIN_SHEET_COLUMNS, aggregate_wins, win_fields_from_card

DB_PATH = ROOT / "data" / "db" / "scouter.db"
EVENTS_PATH = ROOT / "data" / "db" / "scout_events.jsonl"

st.set_page_config(
    page_title="Market Scouter · Augusto Bonorino",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def get_store() -> Store:
    return Store(DB_PATH)


@st.cache_resource
def get_events() -> EventLog:
    return EventLog(EVENTS_PATH)


@st.cache_resource
def get_runner() -> ScoutRunner:
    return ScoutRunner(get_store(), get_events())


@st.cache_data(show_spinner=False)
def cached_fit_slugs():
    return load_fit_slugs()


def _factors_dict(card) -> dict:
    f = card.factors
    return f.model_dump() if hasattr(f, "model_dump") else dict(f)


def _render_card(card, asset_title: str = "") -> None:
    door = card.voice_door.value if hasattr(card.voice_door, "value") else str(card.voice_door)
    move = card.move_type.value if hasattr(card.move_type, "value") else str(card.move_type)
    t_status = card.T_status.value if hasattr(card.T_status, "value") else str(card.T_status)
    st.markdown(
        card_html(
            title=card.title_or_snippet or card.url,
            url=card.url,
            door=door,
            move=move,
            slugs=list(card.slugs or []),
            draft=card.draft_text or "",
            S=float(card.S),
            factors=_factors_dict(card),
            asset_title=asset_title or card.asset_id,
            author=card.author,
            playbook=list(card.playbook_rule_ids or []),
            t_status=t_status,
        ),
        unsafe_allow_html=True,
    )


def _human_action(card, action: HumanAction, wins: list[WinSignal] | None = None) -> None:
    store, events = get_store(), get_events()
    if action == HumanAction.ACTED:
        card.state = CardState.DONE
    elif action == HumanAction.SKIPPED:
        card.state = CardState.SKIPPED
    elif action == HumanAction.EDITED:
        card.state = CardState.DRAFTING
    store.upsert_card(card)
    events.append(
        ScoutEvent(
            kind=EventKind.HUMAN,
            card_id=card.card_id,
            human=action,
            note=f"{action.value} via UI",
        )
    )
    if wins:
        events.append(
            ScoutEvent(
                kind=EventKind.WIN,
                card_id=card.card_id,
                wins=wins,
                **win_fields_from_card(card),
                note=None,
            )
        )


def main() -> None:
    st.markdown(inject_css(), unsafe_allow_html=True)
    st.markdown(hero_html(), unsafe_allow_html=True)

    store = get_store()
    events = get_events()
    runner = get_runner()
    _ = cached_fit_slugs()

    with st.sidebar:
        st.markdown("### ◈ Market Scouter")
        st.caption("Augusto Bonorino · personal PhD/CSS + O-1A")
        st.info("**Suggests only.** Never posts, schedules, or OAuth-as-poster.")
        seed_status = ensure_seeded(store, runner, demo_cards=True)
        st.caption(f"Seed: `{seed_status}`")
        open_x = len(store.open_cards(Outlet.X))
        open_li = len(store.open_cards(Outlet.LINKEDIN))
        st.metric("Open X", f"{open_x} / 7")
        st.metric("Open LinkedIn", f"{open_li} / 7")
        st.markdown("---")
        st.caption("EconLLM = claim-source door label, not org ownership.")
        st.caption("Wins: claim_named_reply · warm_intro · evidence_ab")

    tabs = st.tabs(
        ["Inventory", "Watchlist", "Queue", "Paste & Scout", "Done / Skipped", "Wins"]
    )

    assets = store.list_assets()
    asset_by_id = {a.asset_id: a for a in assets}

    # ── Inventory ──────────────────────────────────────────────────────────
    with tabs[0]:
        st.subheader("Inventory")
        st.caption("Assets to advertise organically. Evidence C never enqueues.")
        if not assets:
            st.markdown(
                '<div class="ms-empty">No inventory yet.</div>', unsafe_allow_html=True
            )
        for a in assets:
            with st.expander(f"{a.title} · {a.evidence_grade.value}", expanded=False):
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.write(a.one_line_claim or "—")
                c2.write(f"Door archive: **{a.door_archive.value}**")
                c3.write(f"Slugs: `{', '.join(a.slugs)}`")
                if a.url:
                    st.markdown(f"[Durable URL]({a.url})")
                if a.oped_status:
                    st.caption(f"Op-ed status: {a.oped_status.value}")

    # ── Watchlist ──────────────────────────────────────────────────────────
    with tabs[1]:
        st.subheader("Watchlist")
        st.caption("Topic-led sources — geography ≠ Fit.")
        for w in store.list_watchlist():
            door = w.door.value if hasattr(w.door, "value") else w.door
            tags = ", ".join(f"`{t}`" for t in (w.claim_tags or []))
            st.markdown(f"**{w.label}** · `{door}` · {tags}")
            if w.notes:
                st.caption(w.notes)

    # ── Queue ──────────────────────────────────────────────────────────────
    with tabs[2]:
        st.subheader("Open queue (cap 7 / outlet)")
        qx, qli = st.tabs(["X", "LinkedIn"])
        for tab, outlet in ((qx, Outlet.X), (qli, Outlet.LINKEDIN)):
            with tab:
                cards = store.open_cards(outlet)
                if not cards:
                    st.markdown(
                        '<div class="ms-empty">Queue empty — paste a URL in Paste & Scout.</div>',
                        unsafe_allow_html=True,
                    )
                    continue
                for card in cards:
                    asset = asset_by_id.get(card.asset_id)
                    _render_card(card, asset.title if asset else card.asset_id)
                    b1, b2, b3, b4 = st.columns([1, 1, 1, 2])
                    with b1:
                        if st.button("Acted", key=f"act_{card.card_id}", use_container_width=True):
                            _human_action(card, HumanAction.ACTED)
                            st.rerun()
                    with b2:
                        if st.button("Edited", key=f"edit_{card.card_id}", use_container_width=True):
                            _human_action(card, HumanAction.EDITED)
                            st.rerun()
                    with b3:
                        if st.button("Skipped", key=f"skip_{card.card_id}", use_container_width=True):
                            _human_action(card, HumanAction.SKIPPED)
                            st.rerun()
                    with b4:
                        win_opts = st.multiselect(
                            "Win signals",
                            options=[w.value for w in WinSignal],
                            key=f"wins_{card.card_id}",
                            label_visibility="collapsed",
                            placeholder="Optional wins…",
                        )
                        if win_opts and st.button(
                            "Log wins", key=f"logwin_{card.card_id}", use_container_width=True
                        ):
                            _human_action(
                                card,
                                HumanAction.ACTED,
                                [WinSignal(w) for w in win_opts],
                            )
                            st.rerun()
                    st.text_area(
                        "Draft (copy manually — never auto-posted)",
                        value=card.draft_text,
                        key=f"draft_{card.card_id}",
                        height=140,
                    )
                    st.divider()

    # ── Paste & Scout ──────────────────────────────────────────────────────
    with tabs[3]:
        st.subheader("Paste & Scout")
        st.caption("Happy path: URL → Candidate → S_safe → Fit → score → queue card.")
        with st.form("paste_form", clear_on_submit=False):
            url = st.text_input(
                "Public URL",
                placeholder="https://x.com/…/status/… or LinkedIn post URL",
            )
            c1, c2 = st.columns(2)
            with c1:
                outlet_s = st.selectbox("Outlet", ["x", "linkedin"])
            with c2:
                labels = {
                    a.asset_id: f"{a.title} [{a.evidence_grade.value}]" for a in assets
                }
                asset_id = st.selectbox(
                    "Matched inventory asset",
                    options=list(labels.keys()) or [""],
                    format_func=lambda i: labels.get(i, i),
                )
            title_hint = st.text_area(
                "Optional snippet / topic hint (improves Fit)",
                placeholder="Paste post text or keywords: WEIRD, construct validity, verificación local…",
                height=90,
            )
            c3, c4, c5, c6 = st.columns(4)
            age_hours = c3.number_input("Age (hours)", min_value=0.0, value=12.0, step=1.0)
            reply_count = c4.number_input("Replies (X)", min_value=0, value=4, step=1)
            quote_count = c5.number_input("Quotes (X)", min_value=0, value=1, step=1)
            like_count = c6.number_input("Likes (info only)", min_value=0, value=0, step=1)
            comment_count = st.number_input(
                "Comments (LinkedIn; 0 = unknown)", min_value=0, value=0, step=1
            )
            submitted = st.form_submit_button(
                "Scout", type="primary", use_container_width=True
            )

        if submitted:
            if not url.strip() or not asset_id:
                st.error("Paste a URL and select an inventory asset.")
            else:
                asset = asset_by_id[asset_id]
                outlet = Outlet(outlet_s)
                with st.spinner("Scoring…"):
                    result = runner.paste_and_scout(
                        url.strip(),
                        outlet=outlet,
                        asset=asset,
                        title_hint=title_hint.strip() or None,
                        age_hours=float(age_hours),
                        reply_count=int(reply_count) if outlet == Outlet.X else None,
                        quote_count=int(quote_count) if outlet == Outlet.X else None,
                        comment_count=(int(comment_count) or None)
                        if outlet == Outlet.LINKEDIN
                        else None,
                        like_count=int(like_count) or None,
                    )
                st.session_state["last_scout"] = result.get("primary")

        primary = st.session_state.get("last_scout")
        if primary:
            kills = primary.get("kill_reasons") or []
            if kills:
                st.warning(
                    "Killed — no card. Reasons: "
                    + ", ".join(f"`{k}`" for k in kills)
                )
            elif not primary.get("ok") or primary.get("card") is None:
                st.info(
                    f"No open card. Decision: "
                    f"`{getattr(primary.get('decision'), 'value', primary.get('decision'))}`"
                )
            else:
                card = primary["card"]
                stored = store.get_card(card.card_id) or card
                decision = primary.get("decision")
                st.success(
                    f"Decision: **{getattr(decision, 'value', decision)}** · "
                    f"S = **{stored.S:.1f}** · door **{stored.voice_door.value}**"
                )
                if stored.like_count_info:
                    st.caption(
                        f"Likes (informational only, not in S): {stored.like_count_info}"
                    )
                title = (
                    asset_by_id[stored.asset_id].title
                    if stored.asset_id in asset_by_id
                    else stored.asset_id
                )
                _render_card(stored, title)
                st.text_area("Draft to copy", value=stored.draft_text, height=160)

        with st.expander("Sample URLs for demo"):
            st.code(
                "https://x.com/fixture_user_68/status/9000000000000000901\n"
                "https://www.linkedin.com/posts/example_construct-validity-1840010000000000003\n"
                "https://x.com/fixture_user_21/status/9000000000000000904\n"
                "https://x.com/fixture_user_33/status/9000000000000000902  # promo kill",
                language=None,
            )

    # ── Done / Skipped ─────────────────────────────────────────────────────
    with tabs[4]:
        st.subheader("Done / Skipped")
        done = store.list_cards(states=[CardState.DONE, CardState.SKIPPED])
        if not done:
            st.markdown(
                '<div class="ms-empty">No closed cards yet.</div>',
                unsafe_allow_html=True,
            )
        for card in done:
            asset = asset_by_id.get(card.asset_id)
            st.markdown(
                f"**{card.state.value}** · S={card.S:.1f} · {card.voice_door.value} · "
                f"[{card.outlet.value}]({card.url}) · "
                f"{asset.title if asset else card.asset_id}"
            )

    # ── Wins ───────────────────────────────────────────────────────────────
    with tabs[5]:
        st.subheader("Wins (distribution only)")
        st.caption("No impressions / Buffer % / invented ER as success metrics.")
        all_events = events.read_all()
        agg = win_aggregates(all_events)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("claim_named_reply", agg.get("claim_named_reply", 0))
        c2.metric("warm_intro", agg.get("warm_intro", 0))
        c3.metric("evidence_ab", agg.get("evidence_ab", 0))
        c4.metric("acted", agg.get("acted_n", 0))

        cards = {
            c.card_id: c
            for c in store.list_cards(
                states=[
                    CardState.OPEN,
                    CardState.DRAFTING,
                    CardState.AWAITING_APPROVAL,
                    CardState.PINNED,
                    CardState.DONE,
                ]
            )
        }
        rows = aggregate_wins(all_events, cards_by_id=cards)
        if rows:
            st.dataframe(rows, use_container_width=True)
            st.caption("Columns: " + " · ".join(WIN_SHEET_COLUMNS))
        else:
            st.markdown(
                '<div class="ms-empty">No win events yet — Acted + win signals on a queue card.</div>',
                unsafe_allow_html=True,
            )

        raw = events.export_bytes()
        st.download_button(
            "Download ScoutEvent JSONL",
            data=raw or b"",
            file_name="scout_events.jsonl",
            mime="application/x-ndjson",
        )

    st.markdown(
        '<div class="ms-gate">Market Scouter v0 · suggests only · likes never drive S · '
        "Fit empty → 0 → no card · Evidence C out · cap 7/outlet</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
