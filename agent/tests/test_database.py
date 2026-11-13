from pathlib import Path

import pytest

from nika.database import Database, SCHEMA_VERSION


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
    assert {"event_log", "memories", "skills", "world_facts"} <= tables


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
