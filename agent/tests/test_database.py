import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from nika.database import SCHEMA_VERSION, Database


def test_initialize_creates_versioned_schema(tmp_path: Path) -> None:
    database = Database(tmp_path / "nested" / "nika.sqlite3")
    database.initialize()
    assert database.health_check()
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        memory_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(memories)")
        }
    assert {"event_log", "memories", "skills", "world_facts"} <= tables
    assert {"provenance_type", "scope", "world_id", "tags_json"} <= memory_columns
    assert {"conversations", "conversation_messages"} <= tables


def test_initialize_is_idempotent(tmp_path: Path) -> None:
    database = Database(tmp_path / "nika.sqlite3")
    database.initialize()
    database.initialize()
    assert database.health_check()


def test_newer_schema_is_not_modified(tmp_path: Path) -> None:
    database = Database(tmp_path / "future.sqlite3")
    with database.connect() as connection:
        connection.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="newer than supported"):
        database.initialize()
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 999


def test_failed_migration_rolls_back_partial_schema(tmp_path: Path) -> None:
    database = Database(tmp_path / "broken-migration.sqlite3")
    with closing(database.connect()) as connection:
        connection.execute("CREATE TABLE memories (sentinel INTEGER)")

    with pytest.raises(sqlite3.OperationalError):
        database.initialize()

    with closing(database.connect()) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert "event_log" not in tables
    assert "memories" in tables
    assert version == 0


def test_migration_v2_preserves_existing_memories(tmp_path: Path) -> None:
    database = Database(tmp_path / "legacy.sqlite3")
    with database.transaction() as connection:
        connection.execute(
            """CREATE TABLE event_log (
                event_id TEXT PRIMARY KEY,
                occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE memories (
                memory_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE skills (
                skill_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                definition_json TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE world_facts (
                fact_id TEXT PRIMARY KEY,
                world_id TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                fact_type TEXT NOT NULL,
                value_json TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL
            )"""
        )
        connection.execute(
            """INSERT INTO memories VALUES (
                'legacy-1', '2026-01-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00', 'preference',
                'Vitaly likes clear answers', 'conversation', 0.8
            )"""
        )
        connection.execute("PRAGMA user_version = 1")

    database.initialize()
    record = database.connect().execute(
        "SELECT * FROM memories WHERE memory_id = 'legacy-1'"
    ).fetchone()
    assert record is not None
    assert record["content"] == "Vitaly likes clear answers"
    assert record["provenance_type"] == "hypothesis"
    assert record["scope"] == "global"
