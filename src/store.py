"""SQLite persistence for inventory, cards, watchlist, scout runs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .models import (
    CardState,
    InventoryAsset,
    Outlet,
    ScoredCard,
    ScoutRun,
    WatchlistSource,
)

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "db" / "scouter.db"


def _ser(obj) -> str:
    if hasattr(obj, "model_dump_json"):
        return obj.model_dump_json()
    return json.dumps(obj)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS inventory (
                    asset_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cards (
                    card_id TEXT PRIMARY KEY,
                    outlet TEXT NOT NULL,
                    state TEXT NOT NULL,
                    S REAL NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cards_outlet_state
                    ON cards(outlet, state);
                CREATE INDEX IF NOT EXISTS idx_cards_s ON cards(S DESC);
                CREATE TABLE IF NOT EXISTS watchlist (
                    source_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scout_runs (
                    scout_run_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    # ── Inventory ─────────────────────────────────────────────────────────────

    def upsert_asset(self, asset: InventoryAsset) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO inventory(asset_id, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (asset.asset_id, asset.model_dump_json(), _utcnow_iso()),
            )

    def list_assets(self) -> list[InventoryAsset]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT payload FROM inventory ORDER BY updated_at DESC"
            ).fetchall()
        return [InventoryAsset.model_validate_json(r["payload"]) for r in rows]

    def get_asset(self, asset_id: str) -> Optional[InventoryAsset]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload FROM inventory WHERE asset_id=?", (asset_id,)
            ).fetchone()
        return InventoryAsset.model_validate_json(row["payload"]) if row else None

    def delete_asset(self, asset_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM inventory WHERE asset_id=?", (asset_id,))

    # ── Cards ─────────────────────────────────────────────────────────────────

    def upsert_card(self, card: ScoredCard) -> None:
        card.updated_at = datetime.now(timezone.utc)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO cards(card_id, outlet, state, S, payload, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(card_id) DO UPDATE SET
                    outlet=excluded.outlet, state=excluded.state, S=excluded.S,
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (
                    card.card_id,
                    card.outlet.value,
                    card.state.value,
                    card.S,
                    card.model_dump_json(),
                    _utcnow_iso(),
                ),
            )

    def get_card(self, card_id: str) -> Optional[ScoredCard]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload FROM cards WHERE card_id=?", (card_id,)
            ).fetchone()
        return ScoredCard.model_validate_json(row["payload"]) if row else None

    def list_cards(
        self,
        *,
        outlet: Outlet | None = None,
        states: list[CardState] | None = None,
    ) -> list[ScoredCard]:
        q = "SELECT payload FROM cards WHERE 1=1"
        params: list = []
        if outlet:
            q += " AND outlet=?"
            params.append(outlet.value)
        if states:
            placeholders = ",".join("?" for _ in states)
            q += f" AND state IN ({placeholders})"
            params.extend(s.value for s in states)
        q += " ORDER BY S DESC, updated_at DESC"
        with self._conn() as conn:
            rows = conn.execute(q, params).fetchall()
        return [ScoredCard.model_validate_json(r["payload"]) for r in rows]

    def open_cards(self, outlet: Outlet) -> list[ScoredCard]:
        return self.list_cards(
            outlet=outlet,
            states=[
                CardState.OPEN,
                CardState.DRAFTING,
                CardState.AWAITING_APPROVAL,
                CardState.PINNED,
            ],
        )

    def delete_card(self, card_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM cards WHERE card_id=?", (card_id,))

    # ── Watchlist ─────────────────────────────────────────────────────────────

    def upsert_watchlist(self, src: WatchlistSource) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO watchlist(source_id, payload) VALUES (?, ?)
                ON CONFLICT(source_id) DO UPDATE SET payload=excluded.payload
                """,
                (src.source_id, src.model_dump_json()),
            )

    def list_watchlist(self) -> list[WatchlistSource]:
        with self._conn() as conn:
            rows = conn.execute("SELECT payload FROM watchlist").fetchall()
        return [WatchlistSource.model_validate_json(r["payload"]) for r in rows]

    # ── Scout runs ────────────────────────────────────────────────────────────

    def save_run(self, run: ScoutRun) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO scout_runs(scout_run_id, payload) VALUES (?, ?)
                ON CONFLICT(scout_run_id) DO UPDATE SET payload=excluded.payload
                """,
                (run.scout_run_id, run.model_dump_json()),
            )

    # ── Meta / seed flag ──────────────────────────────────────────────────────

    def get_meta(self, key: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO meta(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )
