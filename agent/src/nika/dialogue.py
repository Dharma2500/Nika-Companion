"""Strict request validation for private Minecraft-to-Nika chat messages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

MAX_CHAT_REQUEST_BYTES = 16 * 1024
MAX_CHAT_MESSAGE_CHARS = 4000
CHAT_SCHEMA_VERSION = 1
_CHAT_REQUEST_KEYS = {
    "schema_version",
    "request_id",
    "conversation_id",
    "message",
}


class ChatValidationError(ValueError):
    """Raised when a chat request violates the bridge contract."""


@dataclass(frozen=True, slots=True)
class ChatRequest:
    schema_version: int
    request_id: str
    conversation_id: str
    message: str


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ChatValidationError(f"Duplicate JSON property: {key}.")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ChatValidationError(f"Non-standard JSON numeric constant: {value}.")


def _validate_uuid(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 36:
        raise ChatValidationError(f"{name} must be a canonical UUID.")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ChatValidationError(f"{name} must be a canonical UUID.") from error
    if str(parsed) != value:
        raise ChatValidationError(f"{name} must be a lowercase canonical UUID.")
    return value


def decode_chat_request(body: bytes) -> ChatRequest:
    """Decode strict, bounded UTF-8 JSON for one private Nika chat message."""
    if not isinstance(body, bytes) or not body:
        raise ChatValidationError("Chat request body must not be empty bytes.")
    if len(body) > MAX_CHAT_REQUEST_BYTES:
        raise ChatValidationError("Chat request body exceeds the 16 KiB limit.")

    try:
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ChatValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ChatValidationError("Chat request must be valid UTF-8 JSON.") from error

    if not isinstance(payload, dict):
        raise ChatValidationError("Chat request must be a JSON object.")
    actual = set(payload)
    missing = _CHAT_REQUEST_KEYS - actual
    extra = actual - _CHAT_REQUEST_KEYS
    if missing:
        raise ChatValidationError(
            f"Chat request is missing properties: {', '.join(sorted(missing))}."
        )
    if extra:
        raise ChatValidationError(
            f"Chat request contains unsupported properties: {', '.join(sorted(extra))}."
        )
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != CHAT_SCHEMA_VERSION
    ):
        raise ChatValidationError("Unsupported chat schema version.")

    request_id = _validate_uuid(payload["request_id"], "request_id")
    conversation_id = _validate_uuid(payload["conversation_id"], "conversation_id")
    message = payload["message"]
    if not isinstance(message, str) or not message.strip():
        raise ChatValidationError("message must be a non-empty string.")
    if len(message) > MAX_CHAT_MESSAGE_CHARS:
        raise ChatValidationError(
            f"message must not exceed {MAX_CHAT_MESSAGE_CHARS} characters."
        )
    if "\x00" in message:
        raise ChatValidationError("message must not contain null characters.")

    return ChatRequest(
        schema_version=CHAT_SCHEMA_VERSION,
        request_id=request_id,
        conversation_id=conversation_id,
        message=message.strip(),
    )
