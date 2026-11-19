import sqlite3
from pathlib import Path

import pytest

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


def test_doctor_reports_invalid_configuration_before_database_creation(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    data_path = tmp_path / "data-is-a-file"
    data_path.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("NIKA_DATA", str(data_path))
    monkeypatch.delenv("NIKA_DATABASE_PATH", raising=False)

    assert cli.run_doctor() == 1

    output = capsys.readouterr().out
    assert "Nika configuration: ERROR" in output
    assert "NIKA_DATA" in output
    assert "Nika local core: OK" not in output


def test_doctor_reports_external_database_location_warning(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    data_dir = tmp_path / "nika-data"
    database_path = tmp_path / "separate" / "nika.sqlite3"
    monkeypatch.setenv("NIKA_DATA", str(data_dir))
    monkeypatch.setenv("NIKA_DATABASE_PATH", str(database_path))

    assert cli.run_doctor() == 0

    output = capsys.readouterr().out
    assert "Nika configuration: OK" in output
    assert "WARNING:" in output
    assert "outside NIKA_DATA" in output
    assert "SQLite integrity: OK" in output



def test_cli_rejects_invalid_configuration_before_creating_logs(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    data_path = tmp_path / "data-is-a-file"
    data_path.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("NIKA_DATA", str(data_path))
    monkeypatch.delenv("NIKA_DATABASE_PATH", raising=False)
    monkeypatch.setattr("sys.argv", ["nika", "doctor"])

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    assert "Nika configuration: ERROR" in capsys.readouterr().out
    assert not (tmp_path / "data-is-a-file" / "logs").exists()



def test_migrate_data_command_stops_runtime_and_preserves_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source-data"
    settings = Settings(data_dir=source_dir, database_path=source_dir / "nika.sqlite3")
    database = Database(settings.database_path)
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO event_log VALUES (?, ?, ?, ?, ?)",
            ("migration-event", "2026-01-01T00:00:00+00:00", "test", "pytest", "{}"),
        )

    monkeypatch.setattr(cli, "_storage", lambda: (settings, database))
    assert start_runtime(settings) == "started"

    destination = tmp_path / "new-drive" / "NIKA_DATA"
    assert cli.run_migrate_data(str(destination)) == 0

    assert get_runtime_status(settings) is None
    assert _event_ids(database) == ["migration-event"]
    assert _event_ids(Database(destination / "nika.sqlite3")) == ["migration-event"]
    assert (destination / "backups").is_dir()
    assert (destination / "learning").is_dir()
    assert (destination / "migration-manifest.json").is_file()



def test_dashboard_command_starts_runtime_and_opens_loopback_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    started: list[Settings] = []
    opened: list[tuple[str, int]] = []

    monkeypatch.setattr(
        cli.Settings,
        "from_env",
        classmethod(lambda cls: settings),
    )
    monkeypatch.setattr(cli, "get_runtime_status", lambda selected: None)
    monkeypatch.setattr(cli, "start_runtime", lambda selected: started.append(selected))
    monkeypatch.setattr(
        cli,
        "create_dashboard_ticket",
        lambda selected: ("http://127.0.0.1:45678/dashboard/", "one-time-ticket"),
    )
    monkeypatch.setattr(
        cli.webbrowser,
        "open",
        lambda url, new=0: opened.append((url, new)) or True,
    )

    assert cli.run_dashboard() == 0
    assert started == [settings]
    assert opened == [
        ("http://127.0.0.1:45678/dashboard/#ticket=one-time-ticket", 2)
    ]
    output = capsys.readouterr().out
    assert "локальная панель" in output
    assert "one-time-ticket" not in output
