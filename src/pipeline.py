"""Thin in-process ScoutRunner: paste → Candidate → S_safe → Fit → score → queue + draft."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .adapters import get_adapter
from .draft import shape_draft
from .events import EventLog
from .fit import match_slugs_from_text
from .models import (
    AdapterId,
    Decision,
    EventKind,
    InventoryAsset,
    Outlet,
    ScoutEvent,
    ScoutRun,
    ScoredCard,
    VoiceDoor,
)
from .post_identity import note_dropped, resolve_post_dedupe
from .score import queue_decision, score_candidate
from .scorer import _is_protected
from .store import Store


class ScoutRunner:
    def __init__(self, store: Store, events: EventLog):
        self.store = store
        self.events = events

    def paste_and_scout(
        self,
        url: str,
        *,
        outlet: Outlet,
        asset: InventoryAsset,
        title_hint: str | None = None,
        author: str | None = None,
        age_hours: float = 12.0,
        reply_count: int | None = 4,
        quote_count: int | None = 1,
        comment_count: int | None = None,
        like_count: int | None = None,
        voice_door: VoiceDoor | None = None,
        adapter_id: str | None = None,
    ) -> dict:
        """Happy path. Returns result dict with card / kills / decision."""
        adapter_key = adapter_id or "manual.paste"
        adapter = get_adapter(adapter_key)
        run = ScoutRun(
            adapter=AdapterId(adapter_key),
            query_or_slug=None,
            query=url,
        )
        self.store.save_run(run)

        # Discover
        if hasattr(adapter, "discover") and adapter_key in (
            "manual.paste",
            "li.paste",
        ):
            kwargs = dict(
                outlet_hint=outlet,
                title_hint=title_hint,
                author=author,
                age_hours=age_hours,
                like_count=like_count,
            )
            if outlet == Outlet.X:
                kwargs["reply_count"] = reply_count
                kwargs["quote_count"] = quote_count
            else:
                kwargs["comment_count"] = comment_count
            candidates = adapter.discover([url], **kwargs)
        else:
            candidates = [adapter.fetch(url)]

        run.candidates_n = len(candidates)
        run.finished_at = datetime.now(timezone.utc)
        self.store.save_run(run)

        results = []
        for cand in candidates:
            self.events.append(
                ScoutEvent(
                    scout_run_id=run.scout_run_id,
                    kind=EventKind.DISCOVERED,
                    candidate_id=cand.candidate_id,
                    note=cand.url,
                )
            )

            # Prefer asset slugs matched against snippet
            matched = match_slugs_from_text(
                (title_hint or "") + " " + (cand.title_or_snippet or ""),
                candidate_slugs=asset.slugs or None,
            )
            if asset.slugs and not matched:
                # If user explicitly chose an asset, allow soft match on first slug
                # only when title_hint or snippet has research tokens — else fit_empty
                text = ((title_hint or "") + " " + (cand.title_or_snippet or "")).lower()
                tokens = (
                    "llm",
                    "ai",
                    "gpt",
                    "weird",
                    "validity",
                    "culture",
                    "agent",
                    "survey",
                    "misinfo",
                    "desinformación",
                    "complexity",
                    "governance",
                    "measurement",
                    "construct",
                    "journalism",
                    "adepa",
                    "verify",
                )
                if any(t in text for t in tokens):
                    matched = list(asset.slugs[:1])

            card, kills, factors = score_candidate(
                cand,
                asset,
                matched_slugs=matched or None,
                voice_door=voice_door,
            )

            if kills:
                self.events.append(
                    ScoutEvent(
                        scout_run_id=run.scout_run_id,
                        kind=EventKind.KILLED,
                        candidate_id=cand.candidate_id,
                        kill_reasons=kills,
                        factors=factors.as_dict() if factors else None,
                    )
                )
                results.append(
                    {
                        "ok": False,
                        "kill_reasons": kills,
                        "candidate": cand,
                        "card": None,
                        "decision": None,
                        "scout_run_id": run.scout_run_id,
                    }
                )
                continue

            assert card is not None
            card.draft_text = shape_draft(card, asset)

            self.events.append(
                ScoutEvent(
                    scout_run_id=run.scout_run_id,
                    kind=EventKind.SCORED,
                    candidate_id=cand.candidate_id,
                    card_id=card.card_id,
                    factors=card.factors.as_dict(),
                    S=card.S,
                )
            )

            # One card per post (same helper as api/core.py): an existing protected or >=S card wins
            dup = resolve_post_dedupe(card, self.store.list_cards(), _is_protected)
            if dup and not dup["ok"]:
                kept = dup["kept"]
                note_dropped(kept, dup["key"], [card.asset_id])
                self.store.upsert_card(kept)
                self.events.append(ScoutEvent(scout_run_id=run.scout_run_id, kind=EventKind.POST_DEDUPE,
                                              candidate_id=cand.candidate_id, card_id=kept.card_id,
                                              asset_id=card.asset_id, note=f"{dup['key']} dropped=1 kept={kept.asset_id}"))
                results.append({"ok": False, "kill_reasons": [], "candidate": cand, "card": None,
                                "decision": None, "status": "duplicate_post", "kept_card_id": kept.card_id,
                                "scout_run_id": run.scout_run_id})
                continue
            losers = (dup or {}).get("losers") or []
            loser_ids = {c.card_id for c in losers}
            open_cards = [c for c in self.store.open_cards(card.outlet) if c.card_id not in loser_ids]
            decision, replaced_id = queue_decision(card, open_cards)
            if losers and decision in (Decision.ENQUEUE, Decision.REPLACE):
                from .models import CardState

                for c in losers:
                    c.state = CardState.SKIPPED
                    self.store.upsert_card(c)
                note_dropped(card, dup["key"], [c.asset_id for c in losers])
                self.events.append(ScoutEvent(scout_run_id=run.scout_run_id, kind=EventKind.POST_DEDUPE,
                                              candidate_id=cand.candidate_id, card_id=card.card_id,
                                              asset_id=card.asset_id,
                                              note=f"{dup['key']} dropped={len(losers)} "
                                                   f"dropped_assets={','.join(c.asset_id for c in losers)}"))

            if decision == Decision.ENQUEUE:
                self.store.upsert_card(card)
            elif decision == Decision.REPLACE and replaced_id:
                old = self.store.get_card(replaced_id)
                if old:
                    from .models import CardState

                    old.state = CardState.WATCH
                    self.store.upsert_card(old)
                self.store.upsert_card(card)
            elif decision == Decision.WATCH:
                from .models import CardState

                card.state = CardState.WATCH
                self.store.upsert_card(card)
            # DROP → do not persist as open

            self.events.append(
                ScoutEvent(
                    scout_run_id=run.scout_run_id,
                    kind=EventKind.DECISION,
                    candidate_id=cand.candidate_id,
                    card_id=card.card_id,
                    S=card.S,
                    decision=decision,
                    replaced_card_id=replaced_id,
                )
            )

            results.append(
                {
                    "ok": decision
                    in (Decision.ENQUEUE, Decision.REPLACE, Decision.WATCH),
                    "kill_reasons": [],
                    "candidate": cand,
                    "card": card,
                    "decision": decision,
                    "replaced_card_id": replaced_id,
                    "scout_run_id": run.scout_run_id,
                }
            )

        return {
            "scout_run_id": run.scout_run_id,
            "results": results,
            "primary": results[0] if results else None,
        }
