import json
from uuid import uuid4

import pytest

from nika.dialogue import ChatValidationError, decode_chat_request


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "request_id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "message": "Привет, Ника!",
    }


def test_decode_chat_request_accepts_plain_russian_text() -> None:
    payload = valid_payload()
    request = decode_chat_request(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )
    assert request.message == "Привет, Ника!"
    assert request.request_id == payload["request_id"]
    assert request.conversation_id == payload["conversation_id"]


def test_decode_chat_request_rejects_duplicate_keys() -> None:
    request_id = str(uuid4())
    conversation_id = str(uuid4())
    body = (
        '{"schema_version":1,"request_id":"'
        + request_id
        + '","conversation_id":"'
        + conversation_id
        + '","message":"first","message":"second"}'
    ).encode("utf-8")
    with pytest.raises(ChatValidationError, match="Duplicate JSON property"):
        decode_chat_request(body)


def test_decode_chat_request_rejects_unknown_and_missing_fields() -> None:
    payload = valid_payload()
    payload["extra"] = "not allowed"
    with pytest.raises(ChatValidationError, match="unsupported properties"):
        decode_chat_request(json.dumps(payload).encode("utf-8"))

    payload = valid_payload()
    del payload["message"]
    with pytest.raises(ChatValidationError, match="missing properties"):
        decode_chat_request(json.dumps(payload).encode("utf-8"))


def test_decode_chat_request_rejects_invalid_ids_and_empty_text() -> None:
    payload = valid_payload()
    payload["request_id"] = "not-a-uuid"
    with pytest.raises(ChatValidationError, match="canonical UUID"):
        decode_chat_request(json.dumps(payload).encode("utf-8"))

    payload = valid_payload()
    payload["message"] = "   "
    with pytest.raises(ChatValidationError, match="non-empty"):
        decode_chat_request(json.dumps(payload).encode("utf-8"))


def test_decode_chat_request_enforces_message_and_body_limits() -> None:
    payload = valid_payload()
    payload["message"] = "x" * 4001
    with pytest.raises(ChatValidationError, match="4000 characters"):
        decode_chat_request(json.dumps(payload).encode("utf-8"))

    with pytest.raises(ChatValidationError, match="16 KiB"):
        decode_chat_request(b" " * (16 * 1024 + 1))


def test_decode_chat_request_rejects_unsupported_schema_and_null_bytes() -> None:
    payload = valid_payload()
    payload["schema_version"] = 2
    with pytest.raises(ChatValidationError, match="schema version"):
        decode_chat_request(json.dumps(payload).encode("utf-8"))

    payload = valid_payload()
    payload["message"] = "hello\x00world"
    with pytest.raises(ChatValidationError, match="null characters"):
        decode_chat_request(json.dumps(payload).encode("utf-8"))
