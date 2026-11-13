"""Command-line entry point for local diagnostics and storage operations."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from nika.backup import BackupManager
from nika.config import Settings
from nika.database import Database


def _storage() -> tuple[Settings, Database]:
    settings = Settings.from_env()
    database = Database(settings.database_path)
    return settings, database


def run_doctor() -> int:
    settings, database = _storage()
    try:
        database.initialize()
        healthy = database.health_check()
    except (OSError, RuntimeError, sqlite3.Error) as error:
        print(f"Nika local core: ERROR ({error})")
        return 1

    print("Nika local core: OK")
    print(f"Data directory: {settings.data_dir}")
    print(f"Database: {settings.database_path}")
    print(f"SQLite integrity: {'OK' if healthy else 'FAILED'}")
    return 0 if healthy else 1


def run_backup() -> int:
    settings, database = _storage()
    try:
        database.initialize()
        manager = BackupManager(database, settings.data_dir / "backups")
        backup_path = manager.create_backup()
    except (OSError, RuntimeError, sqlite3.Error) as error:
        print(f"Backup: ERROR ({error})")
        return 1

    print("Backup: OK")
    print(f"File: {backup_path}")
    print(f"Retained backups: {len(manager.list_backups())}")
    return 0


def run_backup_verify(path: str) -> int:
    settings, database = _storage()
    manager = BackupManager(database, settings.data_dir / "backups")
    try:
        valid = manager.verify_backup(Path(path))
    except (OSError, RuntimeError, sqlite3.Error) as error:
        print(f"Backup verification: ERROR ({error})")
        return 1

    print(f"Backup verification: {'OK' if valid else 'FAILED'}")
    return 0 if valid else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="nika")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("doctor", help="initialize local storage and run diagnostics")
    subparsers.add_parser("backup", help="create and verify a local database backup")
    verify_parser = subparsers.add_parser(
        "backup-verify",
        help="verify a backup file",
    )
    verify_parser.add_argument("path", help="path to the SQLite backup")

    args = parser.parse_args()
    if args.command == "doctor":
        raise SystemExit(run_doctor())
    if args.command == "backup":
        raise SystemExit(run_backup())
    if args.command == "backup-verify":
        raise SystemExit(run_backup_verify(args.path))

    parser.print_help()
    raise SystemExit(0)


if __name__ == "__main__":
    main()
