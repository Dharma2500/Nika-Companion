"""Command-line entry point for local diagnostics."""

from __future__ import annotations

import argparse
import sqlite3

from nika.config import Settings
from nika.database import Database


def run_doctor() -> int:
    settings = Settings.from_env()
    database = Database(settings.database_path)
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="nika")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("doctor", help="initialize local storage and run diagnostics")
    args = parser.parse_args()
    if args.command == "doctor":
        raise SystemExit(run_doctor())
    parser.print_help()
    raise SystemExit(0)


if __name__ == "__main__":
    main()
