"""Verified SQLite backups with retention for the local Nika data store."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from nika.database import SCHEMA_VERSION, Database


class BackupManager:
    """Creates and verifies consistent SQLite backups."""

    def __init__(
        self,
        database: Database,
        backup_dir: Path,
        retention: int = 10,
    ) -> None:
        if retention < 1:
            raise ValueError("retention must be at least 1")
        self.database = database
        self.backup_dir = Path(backup_dir)
        self.retention = retention

    def create_backup(self) -> Path:
        """Create a consistent backup, verify it, then apply retention."""
        if not self.database.path.is_file():
            raise FileNotFoundError(self.database.path)

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        target = self.backup_dir / f"nika-{timestamp}.sqlite3"
        temporary = target.with_suffix(".sqlite3.tmp")

        source = self.database.connect()
        destination: sqlite3.Connection | None = None
        try:
            destination = sqlite3.connect(temporary)
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise sqlite3.DatabaseError("backup integrity check failed")
            destination.close()
            destination = None
        finally:
            if destination is not None:
                destination.close()
            source.close()

        os.replace(temporary, target)
        self._apply_retention()
        return target

    def verify_backup(self, path: Path) -> bool:
        """Verify SQLite integrity and reject unsupported future schemas."""
        backup_path = Path(path).resolve()
        if not backup_path.is_file():
            raise FileNotFoundError(backup_path)

        connection = sqlite3.connect(f"{backup_path.as_uri()}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if integrity is None or integrity[0] != "ok":
                return False
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Backup schema {version} is newer than supported "
                    f"schema {SCHEMA_VERSION}."
                )
            return True
        finally:
            connection.close()

    def list_backups(self) -> list[Path]:
        """Return managed backups newest first."""
        if not self.backup_dir.exists():
            return []
        return sorted(
            self.backup_dir.glob("nika-*.sqlite3"),
            key=lambda path: path.name,
            reverse=True,
        )

    def _apply_retention(self) -> None:
        for old_backup in self.list_backups()[self.retention :]:
            old_backup.unlink()
