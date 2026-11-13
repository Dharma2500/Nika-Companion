"""Local, secret-free configuration for the Nika agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved filesystem settings for one local Nika installation."""

    data_dir: Path
    database_path: Path

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from environment variables without reading API secrets."""
        configured_data_dir = os.environ.get("NIKA_DATA")
        data_dir = (
            Path(configured_data_dir).expanduser()
            if configured_data_dir
            else Path.home() / "NIKA_DATA"
        ).resolve()

        configured_database = os.environ.get("NIKA_DATABASE_PATH")
        database_path = (
            Path(configured_database).expanduser().resolve()
            if configured_database
            else data_dir / "nika.sqlite3"
        )

        return cls(data_dir=data_dir, database_path=database_path)
