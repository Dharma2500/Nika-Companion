"""Validated local, secret-free configuration for the Nika agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class ConfigurationError(RuntimeError):
    """Raised when environment-based configuration cannot be resolved safely."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved filesystem settings for one local Nika installation."""

    data_dir: Path
    database_path: Path

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from environment variables without reading API secrets."""
        configured_data_dir = os.environ.get("NIKA_DATA")
        if configured_data_dir is None:
            try:
                data_dir = (Path.home() / "NIKA_DATA").resolve()
            except (OSError, RuntimeError, ValueError) as error:
                raise ConfigurationError(
                    f"Cannot resolve the default NIKA_DATA directory: {error}"
                ) from error
        else:
            data_dir = _resolve_configured_path("NIKA_DATA", configured_data_dir)

        configured_database = os.environ.get("NIKA_DATABASE_PATH")
        database_path = (
            _resolve_configured_path("NIKA_DATABASE_PATH", configured_database)
            if configured_database is not None
            else data_dir / "nika.sqlite3"
        )

        return cls(data_dir=data_dir, database_path=database_path)


@dataclass(frozen=True, slots=True)
class ConfigDiagnostic:
    """One actionable configuration finding."""

    severity: Literal["ERROR", "WARNING"]
    message: str


def _resolve_configured_path(name: str, value: str) -> Path:
    if not value.strip():
        raise ConfigurationError(
            f"{name} is set but empty. Remove it or provide a valid filesystem path."
        )
    if "\x00" in value:
        raise ConfigurationError(f"{name} contains an invalid null character.")

    try:
        return Path(value).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise ConfigurationError(f"Cannot resolve {name}={value!r}: {error}") from error


def diagnose_settings(settings: Settings) -> tuple[ConfigDiagnostic, ...]:
    """Check path types and whether required directories/files can be accessed."""
    findings: list[ConfigDiagnostic] = []

    try:
        data_dir = Path(settings.data_dir).resolve()
        database_path = Path(settings.database_path).resolve()
    except (OSError, RuntimeError, ValueError) as error:
        return (
            ConfigDiagnostic("ERROR", f"Configured path cannot be resolved: {error}"),
        )

    if data_dir == database_path:
        findings.append(
            ConfigDiagnostic(
                "ERROR",
                "NIKA_DATABASE_PATH points to NIKA_DATA itself; it must point to a database file.",
            )
        )

    _check_directory(data_dir, "NIKA_DATA", findings)
    _check_directory(database_path.parent, "Database parent directory", findings)

    if database_path.exists():
        if database_path.is_dir():
            findings.append(
                ConfigDiagnostic(
                    "ERROR",
                    f"Database path is a directory, not a file: {database_path}",
                )
            )
        elif not database_path.is_file():
            findings.append(
                ConfigDiagnostic(
                    "ERROR",
                    f"Database path is not a regular file: {database_path}",
                )
            )
        elif not os.access(database_path, os.R_OK | os.W_OK):
            findings.append(
                ConfigDiagnostic(
                    "ERROR",
                    f"Database file must be readable and writable: {database_path}",
                )
            )

    try:
        database_is_inside_data = database_path.is_relative_to(data_dir)
    except ValueError:
        database_is_inside_data = False
    if not database_is_inside_data:
        findings.append(
            ConfigDiagnostic(
                "WARNING",
                "Database is outside NIKA_DATA. Logs, runtime state and backups will "
                "still be stored under NIKA_DATA.",
            )
        )

    return tuple(findings)


def _check_directory(
    path: Path,
    label: str,
    findings: list[ConfigDiagnostic],
) -> None:
    """Check an existing directory or the nearest parent needed to create it."""
    candidate = path
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent

    if not candidate.exists() or not candidate.is_dir():
        findings.append(
            ConfigDiagnostic(
                "ERROR",
                f"{label} cannot be created because this path component is not a directory: "
                f"{candidate}",
            )
        )
        return

    if not os.access(candidate, os.R_OK | os.W_OK | os.X_OK):
        findings.append(
            ConfigDiagnostic(
                "ERROR",
                f"{label} directory is not accessible for reading and writing: {candidate}",
            )
        )
