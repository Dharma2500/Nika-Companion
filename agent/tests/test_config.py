from pathlib import Path

import pytest

from nika.config import ConfigurationError, Settings, diagnose_settings


def test_default_data_directory_is_outside_repository(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("NIKA_DATA", raising=False)
    monkeypatch.delenv("NIKA_DATABASE_PATH", raising=False)
    settings = Settings.from_env()
    assert settings.data_dir == (tmp_path / "NIKA_DATA").resolve()
    assert settings.database_path == settings.data_dir / "nika.sqlite3"


def test_custom_paths_are_resolved(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    database_path = tmp_path / "custom" / "nika.db"
    monkeypatch.setenv("NIKA_DATA", str(data_dir))
    monkeypatch.setenv("NIKA_DATABASE_PATH", str(database_path))
    settings = Settings.from_env()
    assert settings.data_dir == data_dir.resolve()
    assert settings.database_path == database_path.resolve()


@pytest.mark.parametrize("variable", ["NIKA_DATA", "NIKA_DATABASE_PATH"])
def test_empty_path_environment_variable_is_rejected(
    monkeypatch,
    variable: str,
) -> None:
    monkeypatch.setenv(variable, "   ")
    with pytest.raises(ConfigurationError, match=variable):
        Settings.from_env()


def test_missing_directories_are_valid_when_their_parent_is_writable(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "new-data"
    settings = Settings(data_dir=data_dir, database_path=data_dir / "nika.sqlite3")

    assert diagnose_settings(settings) == ()


def test_data_directory_must_not_be_a_file(tmp_path: Path) -> None:
    data_path = tmp_path / "not-a-directory"
    data_path.write_text("occupied", encoding="utf-8")
    settings = Settings(data_dir=data_path, database_path=data_path / "nika.sqlite3")

    findings = diagnose_settings(settings)

    assert any(
        item.severity == "ERROR" and "NIKA_DATA" in item.message
        for item in findings
    )


def test_database_path_must_not_be_a_directory(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    database_path = tmp_path / "database-directory"
    data_dir.mkdir()
    database_path.mkdir()
    settings = Settings(data_dir=data_dir, database_path=database_path)

    findings = diagnose_settings(settings)

    assert any(
        item.severity == "ERROR" and "Database path is a directory" in item.message
        for item in findings
    )


def test_external_database_path_produces_storage_location_warning(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    database_path = tmp_path / "separate" / "nika.sqlite3"
    settings = Settings(data_dir=data_dir, database_path=database_path)

    findings = diagnose_settings(settings)

    assert any(
        item.severity == "WARNING" and "outside NIKA_DATA" in item.message
        for item in findings
    )


def test_database_path_cannot_equal_data_directory(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir, database_path=data_dir)

    findings = diagnose_settings(settings)

    assert any(
        item.severity == "ERROR" and "points to NIKA_DATA itself" in item.message
        for item in findings
    )



def test_service_directory_must_not_be_a_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "logs").write_text("occupied", encoding="utf-8")
    settings = Settings(data_dir=data_dir, database_path=data_dir / "nika.sqlite3")

    findings = diagnose_settings(settings)

    assert any(
        item.severity == "ERROR" and "Logs directory" in item.message
        for item in findings
    )
