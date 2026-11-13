import json
from pathlib import Path

import pytest

from nika.database import Database
from nika.event_store import EventStore, NewEvent


def test_event_is_persisted_and_can_be_read_back(tmp_path: Path) -> None:
    database = Database(tmp_path / "nika.sqlite3")
    database.initialize()
    store = EventStore(database)
    event_id = store.append(
        NewEvent(
            event_type="agent.started",
            source="local-agent",
            payload={"message": "Nika online", "attempt": 1},
        )
    )
    row = store.get(event_id)
    assert row is not None
    assert row["event_type"] == "agent.started"
    assert json.loads(row["payload_json"]) == {
        "attempt": 1,
        "message": "Nika online",
    }
    assert store.count() == 1


def test_event_rejects_empty_type(tmp_path: Path) -> None:
    database = Database(tmp_path / "nika.sqlite3")
    database.initialize()
    store = EventStore(database)
    with pytest.raises(ValueError, match="event_type"):
        store.append(NewEvent(event_type=" ", source="test", payload={}))
