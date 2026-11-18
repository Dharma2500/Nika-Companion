import sqlite3
from pathlib import Path

from nika import cli
from nika.backup import BackupManager
from nika.config import Settings
from nika.database import Database
from nika.runtime import get_runtime_status, start_runtime


def _event_ids(database: Database) -> list[str]:
    connection = sqlite3.connect(database.path)
    try:
        return [
            row[0]
            for row in connection.execute(
                "SELECT event_id FROM event_log ORDER BY event_id"
            ).fetchall()
        ]
    finally:
        connection.close()


def test_restore_command_stops_runtime_and_restores_database(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "nika-data"
    settings = Settings(data_dir=data_dir, database_path=data_dir / "nika.sqlite3")
    database = Database(settings.database_path)
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO event_log VALUES (?, ?, ?, ?, ?)",
            ("saved-event", "2026-01-01T00:00:00+00:00", "test", "pytest", "{}"),
        )

    manager = BackupManager(database, data_dir / "backups")
    backup_path = manager.create_backup()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO event_log VALUES (?, ?, ?, ?, ?)",
            ("later-event", "2026-01-02T00:00:00+00:00", "test", "pytest", "{}"),
        )

    monkeypatch.setattr(cli, "_storage", lambda: (settings, database))
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")

    assert start_runtime(settings) == "started"
    assert cli.run_restore(str(backup_path)) == 0

    assert get_runtime_status(settings) is None
    assert _event_ids(database) == ["saved-event"]
    safety_dirs = list((data_dir / "backups" / "restore-safety").glob("pre-restore-*"))
    assert len(safety_dirs) == 1
    safety_database = Database(safety_dirs[0] / database.path.name)
    assert _event_ids(safety_database) == ["later-event", "saved-event"]
