import json
import logging
from pathlib import Path

import pytest

from nika.config import Settings
from nika.logging_setup import get_logger, setup_logging


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )


def _read_json_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_structured_logs_are_json_and_redact_secret_fields(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    logger = setup_logging(settings, level=logging.DEBUG)
    logger.info(
        "provider configured",
        extra={
            "provider": "test-provider",
            "api_key": "api-secret-value",
            "details": {
                "password": "password-secret-value",
                "safe_label": "visible",
            },
        },
    )
    logger.warning("Request failed: Authorization: Bearer bearer-secret-value")
    logger.info("Config string: %s", '{"refresh_token": "refresh-secret-value"}')

    log_path = settings.data_dir / "logs" / "nika.jsonl"
    records = _read_json_lines(log_path)

    assert len(records) == 3
    serialized = log_path.read_text(encoding="utf-8")
    for secret in (
        "api-secret-value",
        "password-secret-value",
        "bearer-secret-value",
        "refresh-secret-value",
    ):
        assert secret not in serialized
    assert "[REDACTED]" in serialized
    assert records[0]["provider"] == "test-provider"
    assert records[0]["details"] == {
        "password": "[REDACTED]",
        "safe_label": "visible",
    }
    assert records[0]["level"] == "INFO"
    assert records[0]["logger"] == "nika"


def test_known_token_formats_are_redacted_from_messages(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    logger = setup_logging(settings)
    logger.info(
        "Tokens: ghp_abcdefghijklmnopqrstuvwxyz123456 "
        "github_pat_abcdefghijklmnopqrstuvwxyz123456 "
        "sk-abcdefghijklmnopqrstuvwxyz123456"
    )

    log_text = (settings.data_dir / "logs" / "nika.jsonl").read_text(encoding="utf-8")
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in log_text
    assert "github_pat_abcdefghijklmnopqrstuvwxyz123456" not in log_text
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in log_text


def test_logging_setup_is_idempotent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = setup_logging(settings)
    second = setup_logging(settings)

    assert first is second
    assert len(
        [handler for handler in second.handlers if getattr(handler, "_nika_managed_handler", False)]
    ) == 1

    second.info("one event")
    records = _read_json_lines(settings.data_dir / "logs" / "nika.jsonl")
    assert len(records) == 1


def test_log_rotation_keeps_a_bounded_number_of_files(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    logger = setup_logging(settings, max_bytes=220, backup_count=2)

    for index in range(20):
        logger.info("rotation event %02d %s", index, "x" * 70)

    for handler in logger.handlers:
        handler.flush()

    log_dir = settings.data_dir / "logs"
    log_files = list(log_dir.glob("nika.jsonl*"))
    assert len(log_files) <= 3
    assert (log_dir / "nika.jsonl").is_file()


def test_logging_rejects_invalid_rotation_settings(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(ValueError, match="max_bytes"):
        setup_logging(settings, max_bytes=0)
    with pytest.raises(ValueError, match="backup_count"):
        setup_logging(settings, backup_count=-1)
