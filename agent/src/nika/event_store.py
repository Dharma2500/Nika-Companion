"""Append-only event journal for observations and agent activity."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from nika.database import Database


@dataclass(frozen=True, slots=True)
class NewEvent:
    event_type: str
    source: str
    payload: dict[str, object]


class EventStore:
    """Persists events before any optional AI analysis is attempted."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def append(self, event: NewEvent) -> str:
        if not event.event_type.strip():
            raise ValueError("event_type must not be empty")
        if not event.source.strip():
            raise ValueError("source must not be empty")

        event_id = str(uuid4())
        occurred_at = datetime.now(UTC).isoformat()
        payload_json = json.dumps(
            event.payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO event_log (
                    event_id, occurred_at, event_type, source, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (event_id, occurred_at, event.event_type, event.source, payload_json),
            )
        return event_id

    def count(self) -> int:
        with self.database.connect() as connection:
            row = connection.execute("SELECT COUNT(*) FROM event_log").fetchone()
            return int(row[0])

    def get(self, event_id: str) -> sqlite3.Row | None:
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT * FROM event_log WHERE event_id = ?",
                (event_id,),
            ).fetchone()
