"""Designer P1 #3 (Wed 4:46): the reply budget is replies posted today, not open queue slots.
/queue.replies_today feeds the status line and the X button; cap (queue slots) is unchanged."""
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.api import core
from src.api.app import create_app


def _ev(api, ts, outlet="x", human="acted"):
    with api.events_path.open("a") as f:
        f.write(json.dumps({"ts": ts, "kind": "human", "human": human, "outlet": outlet, "card_id": "c"}) + "\n")


def test_replies_today_counts_posted_receipts_in_phoenix_day(tmp_path, monkeypatch):
    app = create_app(str(tmp_path))
    api = app.state.api
    # 2026-10-14 17:00 PT == 2026-10-15T00:00Z
    monkeypatch.setattr(core, "_now", lambda: datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc))
    _ev(api, "2026-10-14T07:30:00+00:00")             # 00:30 PT today -> counts
    _ev(api, "2026-10-14T23:59:00+00:00", human="edited")  # 16:59 PT today -> counts
    _ev(api, "2026-10-14T06:59:00+00:00")             # 23:59 PT yesterday -> no
    _ev(api, "2026-10-14T12:00:00+00:00", human="skipped")  # skipped is not a reply
    _ev(api, "2026-10-14T12:00:00+00:00", outlet="linkedin")
    q = TestClient(app).get("/queue").json()
    assert q["replies_today"]["x"] == {"used": 2, "max": 7, "left": 5}
    assert q["replies_today"]["linkedin"] == {"used": 1, "max": 7, "left": 6}
    assert q["cap"]["x"] == "0/7"                      # queue-slot cap untouched


def test_budget_zero_after_seven(tmp_path, monkeypatch):
    app = create_app(str(tmp_path))
    api = app.state.api
    monkeypatch.setattr(core, "_now", lambda: datetime(2026, 10, 14, 20, 0, tzinfo=timezone.utc))
    for i in range(8):
        _ev(api, f"2026-10-14T1{i}:00:00+00:00")
    assert api.replies_today()["x"] == {"used": 8, "max": 7, "left": 0}
