import json
import sqlite3
from pathlib import Path

import pytest

from nika.config import Settings
from nika.database import Database
from nika.migration import migrate_data_directory


def _make_data_directory(tmp_path: Path) -> tuple[Settings, Database]:
    data_dir = tmp_path / "source-data"
    database = Database(data_dir / "nika.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO event_log VALUES (?, ?, ?, ?, ?)",
            ("kept-event", "2026-01-01T00:00:00+00:00", "test", "pytest", "{}"),
        )
    return Settings(data_dir=data_dir, database_path=database.path), database


def _event_ids(path: Path) -> list[str]:
    with sqlite3.connect(path) as connection:
        return [
            row[0]
            for row in connection.execute(
                "SELECT event_id FROM event_log ORDER BY event_id"
            ).fetchall()
        ]


def test_migration_copies_and_verifies_data_without_deleting_source(
    tmp_path: Path,
) -> None:
    settings, database = _make_data_directory(tmp_path)
    (settings.data_dir / "logs").mkdir()
    (settings.data_dir / "logs" / "cli.jsonl").write_text(
        '{"message":"old log"}\n',
        encoding="utf-8",
    )
    (settings.data_dir / "learning" / "datasets").mkdir(parents=True)
    (settings.data_dir / "learning" / "datasets" / "examples.jsonl").write_text(
        '{"prompt":"hello"}\n',
        encoding="utf-8",
    )
    (settings.data_dir / "backups").mkdir()
    (settings.data_dir / "backups" / "existing-backup.sqlite3").write_bytes(b"backup marker")
    (settings.data_dir / "runtime").mkdir()
    (settings.data_dir / "runtime" / "status.json").write_text(
        '{"pid":123,"port":12345,"token":"stale"}',
        encoding="utf-8",
    )
    destination = tmp_path / "D" / "NIKA_DATA"

    migrated = migrate_data_directory(settings, destination)

    assert migrated == destination.resolve()
    assert _event_ids(migrated / "nika.sqlite3") == ["kept-event"]
    assert _event_ids(settings.database_path) == ["kept-event"]
    assert (migrated / "logs" / "cli.jsonl").is_file()
    assert (migrated / "backups" / "existing-backup.sqlite3").read_bytes() == b"backup marker"
    assert (migrated / "learning" / "datasets" / "examples.jsonl").is_file()
    assert (migrated / "runtime").is_dir()
    assert not (migrated / "runtime" / "status.json").exists()
    manifest = json.loads((migrated / "migration-manifest.json").read_text(encoding="utf-8"))
    assert manifest["sqlite_integrity"] == "ok"
    assert manifest["source_preserved"] is True
    assert not list(destination.parent.glob(".NIKA_DATA.migrating-*"))


def test_migration_refuses_existing_destination_without_overwriting(
    tmp_path: Path,
) -> None:
    settings, _ = _make_data_directory(tmp_path)
    destination = tmp_path / "destination"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        migrate_data_directory(settings, destination)

    assert marker.read_text(encoding="utf-8") == "do not overwrite"


def test_migration_rejects_nested_source_and_destination(
    tmp_path: Path,
) -> None:
    settings, _ = _make_data_directory(tmp_path)

    with pytest.raises(ValueError, match="must not contain each other"):
        migrate_data_directory(settings, settings.data_dir / "nested")


def test_migration_requires_database_inside_data_directory(
    tmp_path: Path,
) -> None:
    settings, database = _make_data_directory(tmp_path)
    external_database = tmp_path / "external.sqlite3"
    external_database.write_bytes(database.path.read_bytes())
    external_settings = Settings(
        data_dir=settings.data_dir,
        database_path=external_database,
    )

    with pytest.raises(RuntimeError, match="outside NIKA_DATA"):
        migrate_data_directory(external_settings, tmp_path / "new-data")
