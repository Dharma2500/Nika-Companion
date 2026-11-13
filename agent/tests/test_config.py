from pathlib import Path

from nika.config import Settings


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
