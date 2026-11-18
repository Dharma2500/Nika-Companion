"""Command-line entry point for local diagnostics and runtime operations."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from nika.backup import BackupManager
from nika.config import ConfigurationError, Settings, diagnose_settings
from nika.database import Database
from nika.logging_setup import get_logger, setup_logging
from nika.runtime import (
    get_runtime_status,
    runtime_maintenance_lock,
    serve,
    start_runtime,
    stop_runtime,
)

LOGGER = get_logger(__name__)


def _storage() -> tuple[Settings, Database]:
    settings = Settings.from_env()
    database = Database(settings.database_path)
    return settings, database


def run_doctor() -> int:
    try:
        settings = Settings.from_env()
        database = Database(settings.database_path)
        findings = diagnose_settings(settings)
        errors = [item for item in findings if item.severity == "ERROR"]
        print(f"Nika configuration: {'ERROR' if errors else 'OK'}")
        for finding in findings:
            print(f"{finding.severity}: {finding.message}")
        if errors:
            return 1

        database.initialize()
        healthy = database.health_check()
    except (ConfigurationError, OSError, RuntimeError, sqlite3.Error) as error:
        LOGGER.exception("doctor.failed")
        print(f"Nika local core: ERROR ({error})")
        return 1

    LOGGER.info("doctor.completed", extra={"database_healthy": healthy})
    print("Nika local core: OK")
    print(f"Data directory: {settings.data_dir}")
    print(f"Database: {settings.database_path}")
    print(f"Logs: {settings.data_dir / 'logs'} (cli.jsonl and runtime.jsonl)")
    print(f"SQLite integrity: {'OK' if healthy else 'FAILED'}")
    return 0 if healthy else 1


def run_backup() -> int:
    settings, database = _storage()
    try:
        database.initialize()
        manager = BackupManager(database, settings.data_dir / "backups")
        backup_path = manager.create_backup()
    except (OSError, RuntimeError, sqlite3.Error) as error:
        LOGGER.exception("backup.failed")
        print(f"Backup: ERROR ({error})")
        return 1

    LOGGER.info("backup.created", extra={"backup_path": str(backup_path)})
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
        LOGGER.exception("backup.verification_failed", extra={"backup_path": path})
        print(f"Backup verification: ERROR ({error})")
        return 1

    print(f"Backup verification: {'OK' if valid else 'FAILED'}")
    return 0 if valid else 1


def run_restore(path: str, confirmed: bool = False) -> int:
    settings, database = _storage()
    manager = BackupManager(database, settings.data_dir / "backups")
    try:
        source = manager.validate_restore_source(Path(path))
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        LOGGER.exception("backup.restore_preflight_failed", extra={"backup_path": path})
        print(f"Restore preflight: ERROR ({error})")
        return 1

    if not confirmed:
        print("The selected backup passed SQLite integrity and schema checks.")
        print(f"Database to replace: {settings.database_path}")
        print("Nika will be stopped before replacement.")
        print("The current database and SQLite sidecar files will be preserved locally.")
        try:
            answer = input("Continue with restore? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("Restore: cancelled")
            return 1
        if answer not in {"y", "yes"}:
            print("Restore: cancelled")
            return 0

    try:
        with runtime_maintenance_lock(settings):
            safety_path = manager.restore_backup(source)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        LOGGER.exception(
            "backup.restore_failed",
            extra={"backup_path": str(source)},
        )
        print(f"Restore: ERROR ({error})")
        return 1

    LOGGER.info(
        "backup.restored",
        extra={
            "backup_path": str(source),
            "safety_copy": str(safety_path) if safety_path else None,
        },
    )
    print("Restore: OK")
    print(f"Restored from: {source}")
    if safety_path is not None:
        print(f"Pre-restore safety copy: {safety_path}")
    else:
        print("Pre-restore safety copy: not needed (no previous database existed)")
    return 0


def run_start() -> int:
    try:
        result = start_runtime()
    except (OSError, RuntimeError) as error:
        LOGGER.exception("runtime.start_failed")
        print(f"Nika start: ERROR ({error})")
        return 1
    LOGGER.info("runtime.start_command", extra={"result": result})
    if result == "already_running":
        print("Nika runtime: already running")
    else:
        print("Nika runtime: started")
    return 0


def run_foreground() -> int:
    settings = Settings.from_env()
    setup_logging(settings, filename="runtime.jsonl")
    try:
        serve(foreground=True)
    except (OSError, RuntimeError) as error:
        LOGGER.exception("runtime.foreground_failed")
        print(f"Nika foreground: ERROR ({error})")
        return 1
    return 0


def run_status() -> int:
    status = get_runtime_status()
    if status is None:
        print("Nika runtime: STOPPED")
        return 1
    print("Nika runtime: RUNNING")
    print(f"Process ID: {status['pid']}")
    return 0


def run_stop() -> int:
    try:
        stopped = stop_runtime()
    except (OSError, RuntimeError) as error:
        LOGGER.exception("runtime.stop_failed")
        print(f"Nika stop: ERROR ({error})")
        return 1
    LOGGER.info("runtime.stop_command", extra={"stopped": stopped})
    if stopped:
        print("Nika runtime: stopped")
        return 0
    print("Nika runtime: not running or shutdown timed out")
    return 1


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
    restore_parser = subparsers.add_parser(
        "restore",
        help="restore the database from a verified backup",
    )
    restore_parser.add_argument("path", help="path to the SQLite backup")
    restore_parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the interactive confirmation prompt",
    )
    subparsers.add_parser("start", help="start the local Nika runtime in the background")
    subparsers.add_parser("foreground", help="run Nika in this console; closing it stops Nika")
    subparsers.add_parser("status", help="show local runtime status")
    subparsers.add_parser("stop", help="gracefully stop the local Nika runtime")

    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        findings = diagnose_settings(settings)
        errors = [item for item in findings if item.severity == "ERROR"]
        if errors:
            print("Nika configuration: ERROR")
            for finding in errors:
                print(f"ERROR: {finding.message}")
            raise SystemExit(2)
        setup_logging(settings, filename="cli.jsonl")
    except ConfigurationError as error:
        print(f"Nika configuration: ERROR ({error})")
        raise SystemExit(2) from error
    except OSError as error:
        print(f"Nika logging: ERROR ({error})")
        raise SystemExit(2) from error

    LOGGER.info("cli.command", extra={"command": args.command or "help"})
    commands = {
        "doctor": run_doctor,
        "backup": run_backup,
        "start": run_start,
        "foreground": run_foreground,
        "status": run_status,
        "stop": run_stop,
    }
    if args.command == "backup-verify":
        raise SystemExit(run_backup_verify(args.path))
    if args.command == "restore":
        raise SystemExit(run_restore(args.path, confirmed=args.yes))
    if args.command in commands:
        raise SystemExit(commands[args.command]())

    parser.print_help()
    raise SystemExit(0)


if __name__ == "__main__":
    main()
