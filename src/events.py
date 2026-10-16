"""Append-only JSONL ScoutEvent log."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Iterable

from .models import ScoutEvent

_DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "db" / "scout_events.jsonl"
)
_lock = Lock()


class EventLog:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else _DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, event: ScoutEvent) -> None:
        line = json.dumps(event.to_jsonl_dict(), ensure_ascii=False)
        with _lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def append_many(self, events: Iterable[ScoutEvent]) -> None:
        lines = [
            json.dumps(e.to_jsonl_dict(), ensure_ascii=False) for e in events
        ]
        if not lines:
            return
        with _lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        out: list[dict] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def export_bytes(self) -> bytes:
        if not self.path.exists():
            return b""
        return self.path.read_bytes()

    def clear(self) -> None:
        with _lock:
            self.path.write_text("", encoding="utf-8")


def win_aggregates(events: list[dict]) -> dict[str, int | float]:
    """Weekly-style distribution wins only."""
    claim = warm = evidence = 0
    acted = 0
    for e in events:
        kind = e.get("kind")
        if kind == "win":
            for w in e.get("wins") or []:
                if w == "claim_named_reply":
                    claim += 1
                elif w == "warm_intro":
                    warm += 1
                elif w == "evidence_ab":
                    evidence += 1
        if kind == "human" and e.get("human") == "acted":
            acted += 1
            # evidence_ab may also be recorded on win events; count acted with A/B via wins
    return {
        "claim_named_reply": claim,
        "warm_intro": warm,
        "evidence_ab": evidence,
        "acted_n": acted,
    }
