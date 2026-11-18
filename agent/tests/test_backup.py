import os
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



def _event_rows(database: Database) -> list[str]:
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


def test_restore_backup_preserves_pre_restore_database(tmp_path: Path) -> None:
    database = Database(tmp_path / "data" / "nika.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO event_log VALUES (?, ?, ?, ?, ?)",
            ("event-before", "2026-01-01T00:00:00+00:00", "test", "pytest", "{}"),
        )

    manager = BackupManager(database, tmp_path / "backups")
    backup_path = manager.create_backup()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO event_log VALUES (?, ?, ?, ?, ?)",
            ("event-after", "2026-01-02T00:00:00+00:00", "test", "pytest", "{}"),
        )

    safety_path = manager.restore_backup(backup_path)

    assert safety_path is not None
    assert safety_path.is_dir()
    assert (safety_path / "manifest.json").is_file()
    assert _event_rows(database) == ["event-before"]

    safety_database = Database(safety_path / database.path.name)
    assert _event_rows(safety_database) == ["event-after", "event-before"]


def test_restore_removes_old_sidecars_and_preserves_them_in_safety_copy(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "data" / "nika.sqlite3")
    database.initialize()
    manager = BackupManager(database, tmp_path / "backups")
    backup_path = manager.create_backup()

    sidecars = [
        Path(f"{database.path}-wal"),
        Path(f"{database.path}-shm"),
        Path(f"{database.path}-journal"),
    ]
    expected: dict[str, bytes] = {}
    for index, sidecar in enumerate(sidecars):
        payload = f"old-sidecar-{index}".encode()
        sidecar.write_bytes(payload)
        expected[sidecar.name] = payload

    safety_path = manager.restore_backup(backup_path)

    assert safety_path is not None
    for sidecar in sidecars:
        assert not sidecar.exists()
        assert (safety_path / sidecar.name).read_bytes() == expected[sidecar.name]
    assert manager.verify_backup(database.path)


def test_restore_rejects_invalid_source_without_changing_database(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "nika.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO event_log VALUES (?, ?, ?, ?, ?)",
            ("keep-me", "2026-01-01T00:00:00+00:00", "test", "pytest", "{}"),
        )
    manager = BackupManager(database, tmp_path / "backups")
    invalid_backup = tmp_path / "invalid.sqlite3"
    invalid_backup.write_bytes(b"not a sqlite database")

    with pytest.raises(sqlite3.DatabaseError):
        manager.restore_backup(invalid_backup)

    assert _event_rows(database) == ["keep-me"]
    assert not (tmp_path / "backups" / "restore-safety").exists()


def test_restore_rejects_incompatible_schema_without_changing_database(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "nika.sqlite3")
    database.initialize()
    manager = BackupManager(database, tmp_path / "backups")
    backup_path = manager.create_backup()

    connection = sqlite3.connect(backup_path)
    try:
        connection.execute("PRAGMA user_version = 0")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="requires schema"):
        manager.restore_backup(backup_path)

    assert manager.verify_backup(database.path)
    assert not (tmp_path / "backups" / "restore-safety").exists()


def test_restore_rolls_back_when_atomic_swap_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "nika.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO event_log VALUES (?, ?, ?, ?, ?)",
            ("before-backup", "2026-01-01T00:00:00+00:00", "test", "pytest", "{}"),
        )
    manager = BackupManager(database, tmp_path / "backups")
    backup_path = manager.create_backup()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO event_log VALUES (?, ?, ?, ?, ?)",
            ("keep-after-failure", "2026-01-02T00:00:00+00:00", "test", "pytest", "{}"),
        )

    real_replace = os.replace
    failed = False

    def fail_database_swap(source, destination):
        nonlocal failed
        if Path(destination) == database.path and not failed:
            failed = True
            raise OSError("simulated atomic swap failure")
        return real_replace(source, destination)

    monkeypatch.setattr("nika.backup.os.replace", fail_database_swap)

    with pytest.raises(OSError, match="simulated atomic swap failure"):
        manager.restore_backup(backup_path)

    assert failed
    assert _event_rows(database) == ["before-backup", "keep-after-failure"]
    safety_root = tmp_path / "backups" / "restore-safety"
    assert len(list(safety_root.glob("pre-restore-*"))) == 1



def test_restore_rolls_back_after_post_install_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "nika.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO event_log VALUES (?, ?, ?, ?, ?)",
            ("original", "2026-01-01T00:00:00+00:00", "test", "pytest", "{}"),
        )
    manager = BackupManager(database, tmp_path / "backups")
    backup_path = manager.create_backup()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO event_log VALUES (?, ?, ?, ?, ?)",
            ("later", "2026-01-02T00:00:00+00:00", "test", "pytest", "{}"),
        )

    real_verify = manager.verify_backup

    def fail_installed_database(path: Path) -> bool:
        if Path(path).resolve() == database.path.resolve():
            return False
        return real_verify(path)

    monkeypatch.setattr(manager, "verify_backup", fail_installed_database)

    with pytest.raises(sqlite3.DatabaseError, match="post-install"):
        manager.restore_backup(backup_path)

    assert _event_rows(database) == ["later", "original"]


def test_restore_migrates_v1_backup_without_modifying_source(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "active" / "nika.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO event_log VALUES (?, ?, ?, ?, ?)",
            ("active-row", "2026-01-02T00:00:00+00:00", "test", "pytest", "{}"),
        )

    legacy_path = tmp_path / "legacy-v1.sqlite3"
    legacy_connection = sqlite3.connect(legacy_path)
    try:
        legacy_connection.executescript(
            """
            CREATE TABLE event_log (
                event_id TEXT PRIMARY KEY,
                occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE memories (
                memory_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL
                    CHECK (confidence >= 0.0 AND confidence <= 1.0)
            );
            CREATE TABLE skills (
                skill_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                definition_json TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL
                    CHECK (confidence >= 0.0 AND confidence <= 1.0),
                UNIQUE (name, version)
            );
            CREATE TABLE world_facts (
                fact_id TEXT PRIMARY KEY,
                world_id TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                fact_type TEXT NOT NULL,
                value_json TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL
                    CHECK (confidence >= 0.0 AND confidence <= 1.0)
            );
            """
        )
        legacy_connection.execute(
            "INSERT INTO event_log VALUES (?, ?, ?, ?, ?)",
            ("legacy-event", "2026-01-01T00:00:00+00:00", "test", "legacy", "{}"),
        )
        legacy_connection.execute(
            """INSERT INTO memories (
                memory_id, created_at, updated_at, category, content, source, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "legacy-memory",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "preference",
                "Виталий предпочитает русский язык.",
                "legacy-import",
                0.9,
            ),
        )
        legacy_connection.execute("PRAGMA user_version = 1")
        legacy_connection.commit()
    finally:
        legacy_connection.close()

    manager = BackupManager(database, tmp_path / "backups")
    assert manager.verify_backup(legacy_path)
    assert manager._schema_version(legacy_path) == 1

    safety_path = manager.restore_backup(legacy_path)

    assert safety_path is not None
    assert _event_rows(database) == ["legacy-event"]
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        memory = connection.execute(
            "SELECT content, provenance_type, scope FROM memories "
            "WHERE memory_id = 'legacy-memory'"
        ).fetchone()
    assert memory is not None
    assert memory["content"] == "Виталий предпочитает русский язык."
    assert memory["provenance_type"] == "hypothesis"
    assert memory["scope"] == "global"

    # The original v1 backup is a recovery artifact and must remain unchanged.
    assert manager._schema_version(legacy_path) == 1
    assert manager.verify_backup(legacy_path)
