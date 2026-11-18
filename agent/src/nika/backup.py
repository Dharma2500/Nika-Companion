"""Verified SQLite backups with retention for the local Nika data store."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import uuid
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

    def validate_restore_source(self, path: Path) -> Path:
        """Validate a restore source without changing the active database."""
        source = Path(path).expanduser().resolve()
        database_path = self.database.path.resolve()
        if source == database_path:
            raise ValueError("The backup path must differ from the active database path.")
        if not self.verify_backup(source):
            raise sqlite3.DatabaseError("The selected backup failed its integrity check.")

        schema_version = self._schema_version(source)
        if not 1 <= schema_version <= SCHEMA_VERSION:
            raise RuntimeError(
                f"Restore requires a supported schema from 1 to {SCHEMA_VERSION}; "
                f"the selected backup uses schema {schema_version}."
            )
        return source

    def restore_backup(self, path: Path) -> Path | None:
        """Restore a verified backup, retaining a raw pre-restore safety snapshot.

        The caller must hold the runtime maintenance lock so no Nika process can
        open the database while the files are replaced.
        """
        source = self.validate_restore_source(path)
        database_path = self.database.path.resolve()

        database_path.parent.mkdir(parents=True, exist_ok=True)
        sidecars = self._sidecar_paths(database_path)
        had_original_files = database_path.exists() or any(
            sidecar.exists() for sidecar in sidecars
        )
        safety_dir: Path | None = None
        temporary_path: Path | None = None
        database_replaced = False

        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{database_path.name}.restore-",
                suffix=".tmp",
                dir=database_path.parent,
            )
            os.close(descriptor)
            temporary_path = Path(temporary_name)
            shutil.copy2(source, temporary_path)
            if not self.verify_backup(temporary_path):
                raise sqlite3.DatabaseError(
                    "The staged restore file failed its integrity check."
                )

            # Migrate older supported backups on a staged copy only. Never alter
            # the selected backup file, and never install a partially migrated DB.
            Database(temporary_path).initialize()
            staged_connection = sqlite3.connect(temporary_path)
            try:
                staged_version = int(
                    staged_connection.execute("PRAGMA user_version").fetchone()[0]
                )
                if staged_version != SCHEMA_VERSION:
                    raise sqlite3.DatabaseError(
                        f"Staged restore schema {staged_version} does not match "
                        f"supported schema {SCHEMA_VERSION}."
                    )
                staged_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                staged_connection.execute("PRAGMA journal_mode = DELETE")
                integrity = staged_connection.execute("PRAGMA integrity_check").fetchone()
                if integrity is None or integrity[0] != "ok":
                    raise sqlite3.DatabaseError(
                        "The migrated restore file failed its integrity check."
                    )
            finally:
                staged_connection.close()

            for staged_sidecar in self._sidecar_paths(temporary_path):
                staged_sidecar.unlink(missing_ok=True)

            if self._schema_version(temporary_path) != SCHEMA_VERSION:
                raise sqlite3.DatabaseError(
                    "The staged restore file is not at the current schema version."
                )

            if had_original_files:
                safety_dir = self._create_restore_safety_copy(
                    database_path,
                    sidecars,
                )

            # A WAL or journal from the old database must never be replayed against
            # the restored database. Their bytes remain in the safety snapshot.
            for sidecar in sidecars:
                sidecar.unlink(missing_ok=True)

            os.replace(temporary_path, database_path)
            temporary_path = None
            database_replaced = True

            if not self.verify_backup(database_path):
                raise sqlite3.DatabaseError(
                    "The restored database failed its post-install integrity check."
                )
            # Read-only verification can create transient WAL/SHM files for a
            # database whose persistent journal mode is WAL.
            for sidecar in sidecars:
                sidecar.unlink(missing_ok=True)

            return safety_dir
        except Exception as error:
            try:
                if safety_dir is not None:
                    self._restore_safety_copy(
                        database_path,
                        sidecars,
                        safety_dir,
                        restore_database=database_replaced,
                    )
                elif not had_original_files:
                    database_path.unlink(missing_ok=True)
                    for sidecar in sidecars:
                        sidecar.unlink(missing_ok=True)
            except Exception as rollback_error:
                raise RuntimeError(
                    "Restore failed and automatic rollback also failed. "
                    f"Preserve the safety snapshot at {safety_dir!s}. "
                    f"Restore error: {error}; rollback error: {rollback_error}"
                ) from rollback_error
            raise
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _sidecar_paths(database_path: Path) -> list[Path]:
        return [
            Path(f"{database_path}-wal"),
            Path(f"{database_path}-shm"),
            Path(f"{database_path}-journal"),
        ]

    @staticmethod
    def _schema_version(path: Path) -> int:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()

    def _create_restore_safety_copy(
        self,
        database_path: Path,
        sidecars: list[Path],
    ) -> Path:
        """Copy the exact pre-restore database files into a retained local folder."""
        safety_root = self.backup_dir / "restore-safety"
        safety_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        final_dir = safety_root / f"pre-restore-{timestamp}-{uuid.uuid4().hex[:8]}"
        temporary_dir = Path(tempfile.mkdtemp(prefix=".pending-", dir=safety_root))
        copied_files: list[str] = []

        try:
            for source in [database_path, *sidecars]:
                if source.is_file():
                    shutil.copy2(source, temporary_dir / source.name)
                    copied_files.append(source.name)

            manifest = {
                "created_at": datetime.now(UTC).isoformat(),
                "database_path": str(database_path),
                "files": copied_files,
                "kind": "raw_pre_restore_safety_copy",
            }
            (temporary_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary_dir, final_dir)
            return final_dir
        except Exception:
            shutil.rmtree(temporary_dir, ignore_errors=True)
            raise

    def _restore_safety_copy(
        self,
        database_path: Path,
        sidecars: list[Path],
        safety_dir: Path,
        *,
        restore_database: bool,
    ) -> None:
        """Put pre-restore files back after a failed database swap."""
        for sidecar in sidecars:
            sidecar.unlink(missing_ok=True)

        original_database = safety_dir / database_path.name
        if restore_database and original_database.is_file():
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{database_path.name}.rollback-",
                suffix=".tmp",
                dir=database_path.parent,
            )
            os.close(descriptor)
            temporary_path = Path(temporary_name)
            try:
                shutil.copy2(original_database, temporary_path)
                os.replace(temporary_path, database_path)
            finally:
                temporary_path.unlink(missing_ok=True)
        elif restore_database:
            database_path.unlink(missing_ok=True)

        for sidecar in sidecars:
            saved_sidecar = safety_dir / sidecar.name
            if saved_sidecar.is_file():
                shutil.copy2(saved_sidecar, sidecar)

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
