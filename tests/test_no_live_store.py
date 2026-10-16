import sqlite3
from pathlib import Path

import pytest

LIVE = Path(__file__).resolve().parent.parent / "data" / "db" / "scouter.db"


def test_opening_live_store_fails():
    with pytest.raises(AssertionError, match="live store"):
        sqlite3.connect(str(LIVE))


def test_module_app_not_on_live_store():
    import src.api.app as m
    assert not Path(m.app.state.api.data_dir).resolve().is_relative_to(LIVE.parent.resolve())
