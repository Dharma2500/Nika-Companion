import sqlite3
from pathlib import Path

import pytest

from nika.backup import BackupManager
from nika.database import Database


def test_backup_is_created_and_verified(tmp_path: Path) -> None:
    database = Database(tmp_path / "data" / "nika.sqlite3")
    database.initialize()
    backup_manager = BackupManager(database, tmp_path / "backups")

    backup_path = backup_manager.create_backup()

    assert backup_path.is_file()
    assert backup_manager.verify_backup(backup_path)
    assert backup_manager.list_backups() == [backup_path]


def test_backup_contains_database_data(tmp_path: Path) -> None:
    database = Database(tmp_path / "nika.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO event_log VALUES (?, ?, ?, ?, ?)",
            ("event-1", "2026-01-01T00:00:00+00:00", "test", "pytest", "{}"),
        )

    manager = BackupManager(database, tmp_path / "backups")
    backup_path = manager.create_backup()
    connection = sqlite3.connect(backup_path)
    try:
        count = connection.execute("SELECT COUNT(*) FROM event_log").fetchone()[0]
    finally:
        connection.close()

    assert count == 1


def test_backup_retention_keeps_newest_files(tmp_path: Path) -> None:
    database = Database(tmp_path / "nika.sqlite3")
    database.initialize()
    manager = BackupManager(database, tmp_path / "backups", retention=2)

    created = [manager.create_backup() for _ in range(3)]

    assert len(manager.list_backups()) == 2
    assert created[0] not in manager.list_backups()
    assert set(manager.list_backups()) == set(created[1:])


def test_verify_rejects_missing_backup(tmp_path: Path) -> None:
    database = Database(tmp_path / "nika.sqlite3")
    manager = BackupManager(database, tmp_path / "backups")

    with pytest.raises(FileNotFoundError):
        manager.verify_backup(tmp_path / "missing.sqlite3")


def test_backup_requires_existing_database(tmp_path: Path) -> None:
    database = Database(tmp_path / "missing.sqlite3")
    manager = BackupManager(database, tmp_path / "backups")

    with pytest.raises(FileNotFoundError):
        manager.create_backup()


def test_backup_manager_rejects_zero_retention(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="retention"):
        BackupManager(Database(tmp_path / "nika.sqlite3"), tmp_path / "backups", 0)
