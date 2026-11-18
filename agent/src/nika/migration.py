"""Safe migration of the complete local data directory to another disk."""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from nika.config import Settings
from nika.database import SCHEMA_VERSION


def migrate_data_directory(settings: Settings, destination: Path) -> Path:
    """Copy Nika's data to a new directory and verify it before publishing.

    The caller must hold runtime_maintenance_lock(settings). The source is never
    deleted or modified by this function. Runtime metadata is intentionally not
    copied because its PID and lock state belong to the old process/location.
    """
    source = Path(settings.data_dir).resolve()
    source_database = Path(settings.database_path).resolve()
    target = Path(destination).expanduser().resolve()

    if not source.is_dir():
        raise RuntimeError(f"Source data directory does not exist: {source}")
    if not source_database.is_file():
        raise RuntimeError(f"Source database does not exist: {source_database}")
    try:
        database_relative = source_database.relative_to(source)
    except ValueError as error:
        raise RuntimeError(
            "The configured database is outside NIKA_DATA. Move it into NIKA_DATA "
            "before using the automatic data migration."
        ) from error

    try:
        Path(settings.learning_path).resolve().relative_to(source)
    except ValueError as error:
        raise RuntimeError(
            "NIKA_LEARNING_DIR is outside NIKA_DATA. Migrate that learning directory "
            "separately or unset NIKA_LEARNING_DIR before migrating."
        ) from error

    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("Source and destination directories must not contain each other.")
    if target.exists():
        raise FileExistsError(
            f"Destination already exists: {target}. Choose a new, empty destination path."
        )

    for item in source.rglob("*"):
        if item.is_symlink():
            raise RuntimeError(
                f"Symbolic links are not supported in an automatic data migration: {item}"
            )

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.migrating-{uuid.uuid4().hex}"

    def ignore_entries(directory: str, entries: list[str]) -> set[str]:
        current = Path(directory).resolve()
        ignored: set[str] = set()
        if current == source:
            ignored.update(entry for entry in entries if entry.casefold() == "runtime")
        if current == source_database.parent:
            database_names = {
                source_database.name.casefold(),
                f"{source_database.name}-wal".casefold(),
                f"{source_database.name}-shm".casefold(),
                f"{source_database.name}-journal".casefold(),
            }
            ignored.update(entry for entry in entries if entry.casefold() in database_names)
        return ignored

    try:
        shutil.copytree(
            source,
            staging,
            copy_function=shutil.copy2,
            ignore=ignore_entries,
        )

        staged_database = staging / database_relative
        staged_database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(source_database, timeout=10.0)) as source_connection:
            source_integrity = source_connection.execute("PRAGMA integrity_check").fetchone()
            source_schema = int(source_connection.execute("PRAGMA user_version").fetchone()[0])
            if source_integrity is None or source_integrity[0] != "ok":
                raise RuntimeError("The source database failed SQLite integrity_check.")
            if source_schema != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Source database schema {source_schema} does not match "
                    f"supported schema {SCHEMA_VERSION}."
                )
            with closing(
                sqlite3.connect(staged_database, timeout=10.0)
            ) as target_connection:
                source_connection.backup(target_connection)
                target_integrity = target_connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()
                target_schema = int(
                    target_connection.execute("PRAGMA user_version").fetchone()[0]
                )

        if target_integrity is None or target_integrity[0] != "ok":
            raise RuntimeError("The migrated database failed SQLite integrity_check.")
        if target_schema != SCHEMA_VERSION:
            raise RuntimeError(
                f"Migrated database schema {target_schema} does not match "
                f"supported schema {SCHEMA_VERSION}."
            )

        (staging / "runtime").mkdir(exist_ok=True)
        learning_root = staging / Path(settings.learning_path).resolve().relative_to(source)
        learning_root.mkdir(parents=True, exist_ok=True)
        for directory in (
            "datasets",
            "base-models",
            "adapters",
            "checkpoints",
            "runs",
            "cache",
            "exports",
        ):
            (learning_root / directory).mkdir(exist_ok=True)
        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "source_data_directory": str(source),
            "destination_data_directory": str(target),
            "database_relative_path": database_relative.as_posix(),
            "schema_version": target_schema,
            "sqlite_integrity": "ok",
            "runtime_state_copied": False,
            "source_preserved": True,
        }
        (staging / "migration-manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        staging.replace(target)
        return target
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
