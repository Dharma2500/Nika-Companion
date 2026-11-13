"""Structured local logging with secret redaction and bounded disk usage."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from nika.config import Settings

DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5
REDACTED = "[REDACTED]"

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "auth_token",
    "authorization",
    "password",
    "passwd",
    "secret",
    "private_key",
    "client_secret",
    "credential",
)

_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    (?P<prefix>
        ["']?
        (?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|
           authorization|password|passwd|secret|private[_-]?key|client[_-]?secret|
           credential)
        ["']?\s*[:=]\s*
    )
    (?:
        (?P<quote>["'])(?P<quoted>.*?)(?P=quote)
        |
        (?P<bare>[^,;\s}\]]+)
    )
    """
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_KNOWN_TOKEN_FORMATS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b"),
)

_STANDARD_RECORD_FIELDS = frozenset(
    logging.makeLogRecord({}).__dict__
    | {
        "message",
        "asctime",
    }
)


def _is_sensitive_key(key: object) -> bool:
    raw_key = str(key)
    normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", raw_key).casefold().replace("-", "_")
    compact = normalized.replace("_", "")
    return (
        any(part in normalized for part in _SENSITIVE_KEY_PARTS)
        or any(part.replace("_", "") in compact for part in _SENSITIVE_KEY_PARTS)
        or normalized == "token"
        or normalized.endswith("_token")
        or compact.endswith("token")
    )


def redact_value(value: Any, *, key: object | None = None) -> Any:
    """Redact sensitive structured fields and recognizable secret strings."""
    if key is not None and _is_sensitive_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {str(item_key): redact_value(item, key=item_key) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        text = _BEARER_TOKEN.sub("Bearer " + REDACTED, value)
        text = _SECRET_ASSIGNMENT.sub(
            lambda match: (
                match.group("prefix")
                + (match.group("quote") or "")
                + REDACTED
                + (match.group("quote") or "")
            ),
            text,
        )
        for pattern in _KNOWN_TOKEN_FORMATS:
            text = pattern.sub(REDACTED, text)
        return text
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_value(str(value))


class JsonRedactingFormatter(logging.Formatter):
    """Render one safe JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            message = record.getMessage()
        except Exception:
            message = "[unrenderable log message]"
        document: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_value(message),
        }

        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_"):
                document[key] = redact_value(value, key=key)

        if record.exc_info:
            exception_text = self.formatException(record.exc_info)
            document["exception"] = redact_value(exception_text)

        return json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )


def setup_logging(
    settings: Settings | None = None,
    *,
    level: int = logging.INFO,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> logging.Logger:
    """Configure one rotating JSONL file under the local data directory."""
    if max_bytes < 1:
        raise ValueError("max_bytes must be at least 1")
    if backup_count < 0:
        raise ValueError("backup_count must not be negative")

    resolved = settings or Settings.from_env()
    log_dir = resolved.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "nika.jsonl"

    logger = logging.getLogger("nika")
    logger.setLevel(level)
    logger.propagate = False

    for existing in list(logger.handlers):
        if getattr(existing, "_nika_managed_handler", False):
            logger.removeHandler(existing)
            existing.close()

    handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(JsonRedactingFormatter())
    handler._nika_managed_handler = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger inside the Nika namespace."""
    if not name or name == "nika":
        return logging.getLogger("nika")
    if name.startswith("nika."):
        return logging.getLogger(name)
    return logging.getLogger(f"nika.{name}")
