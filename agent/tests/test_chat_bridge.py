import json
import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from nika.config import Settings
from nika.database import Database
from nika.memory import ConversationStore
from nika.runtime import (
    BRIDGE_CHAT_PATH,
    create_bridge_signature,
    start_runtime,
    stop_runtime,
)


@contextmanager
def fake_provider(
    reply: str = "Привет! Я Ника.",
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    calls: list[dict[str, Any]] = []
    response_body = json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": reply}}]},
        ensure_ascii=False,
    ).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            request_body = self.rfile.read(length)
            calls.append(json.loads(request_body.decode("utf-8")))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}/v1", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _chat_request(
    status: dict[str, Any],
    *,
    request_id: str,
    conversation_id: str,
    message: str,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> Request:
    body = json.dumps(
        {
            "schema_version": 1,
            "request_id": request_id,
            "conversation_id": conversation_id,
            "message": message,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    issued_at = timestamp or str(int(time.time()))
    request_nonce = nonce or secrets.token_urlsafe(24)
    signature = create_bridge_signature(
        str(status["bridge_token"]),
        "POST",
        BRIDGE_CHAT_PATH,
        issued_at,
        request_nonce,
        body,
    )
    return Request(
        f"http://127.0.0.1:{status['port']}{BRIDGE_CHAT_PATH}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Nika-Bridge-Timestamp": issued_at,
            "X-Nika-Bridge-Nonce": request_nonce,
            "X-Nika-Bridge-Signature": signature,
        },
        method="POST",
    )


def _runtime_settings(tmp_path) -> Settings:
    data_dir = tmp_path / "nika-data"
    return Settings(data_dir=data_dir, database_path=data_dir / "nika.sqlite3")


def _read_runtime_status(settings: Settings) -> dict[str, Any]:
    return json.loads(
        (settings.data_dir / "runtime" / "status.json").read_text(encoding="utf-8")
    )


def test_bridge_chat_persists_user_and_assistant_and_retries_idempotently(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _runtime_settings(tmp_path)
    user_text = "Ника, расскажи мне про этот механизм."
    conversation_id = str(uuid4())
    request_id = str(uuid4())

    with fake_provider() as (base_url, provider_calls):
        monkeypatch.setenv("NIKA_LLM_BASE_URL", base_url)
        monkeypatch.setenv("NIKA_LLM_MODEL", "test-local-model")
        monkeypatch.delenv("NIKA_LLM_API_KEY", raising=False)
        assert start_runtime(settings) == "started"
        try:
            status = _read_runtime_status(settings)

            with urlopen(
                _chat_request(
                    status,
                    request_id=request_id,
                    conversation_id=conversation_id,
                    message=user_text,
                ),
                timeout=5,
            ) as response:
                first = json.loads(response.read().decode("utf-8"))
                assert response.status == 200

            assert first["accepted"] is True
            assert first["cached"] is False
            assert first["reply"] == "Привет! Я Ника."

            # A retry uses a fresh HMAC nonce, but the same request UUID.
            with urlopen(
                _chat_request(
                    status,
                    request_id=request_id,
                    conversation_id=conversation_id,
                    message=user_text,
                ),
                timeout=5,
            ) as response:
                second = json.loads(response.read().decode("utf-8"))
                assert response.status == 200

            assert second["cached"] is True
            assert second["assistant_message_id"] == first["assistant_message_id"]
            assert second["reply"] == first["reply"]
            assert len(provider_calls) == 1
        finally:
            assert stop_runtime(settings)

    conversation_store = ConversationStore(Database(settings.database_path))
    messages = conversation_store.get_recent_messages(conversation_id, limit=10)
    assert [(item.role, item.content) for item in messages] == [
        ("user", user_text),
        ("assistant", "Привет! Я Ника."),
    ]
    assert messages[0].request_id == request_id
    assert messages[1].request_id == f"{request_id}:assistant"

    log_path = settings.data_dir / "logs" / "runtime.jsonl"
    if log_path.exists():
        assert user_text not in log_path.read_text(encoding="utf-8")


def test_bridge_chat_rejects_reused_request_id_with_different_message(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _runtime_settings(tmp_path)
    conversation_id = str(uuid4())
    request_id = str(uuid4())

    with fake_provider() as (base_url, provider_calls):
        monkeypatch.setenv("NIKA_LLM_BASE_URL", base_url)
        monkeypatch.setenv("NIKA_LLM_MODEL", "test-local-model")
        assert start_runtime(settings) == "started"
        try:
            status = _read_runtime_status(settings)
            first = _chat_request(
                status,
                request_id=request_id,
                conversation_id=conversation_id,
                message="Первоначальное сообщение",
            )
            with urlopen(first, timeout=5) as response:
                assert response.status == 200
                response.read()

            conflicting = _chat_request(
                status,
                request_id=request_id,
                conversation_id=conversation_id,
                message="Другой текст с тем же ID",
            )
            with pytest.raises(HTTPError) as error:
                urlopen(conflicting, timeout=5)
            assert error.value.code == 409
            assert len(provider_calls) == 1
        finally:
            assert stop_runtime(settings)


def test_bridge_chat_requires_provider_and_does_not_store_message(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _runtime_settings(tmp_path)
    monkeypatch.delenv("NIKA_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NIKA_LLM_MODEL", raising=False)
    monkeypatch.delenv("NIKA_LLM_API_KEY", raising=False)
    assert start_runtime(settings) == "started"
    try:
        status = _read_runtime_status(settings)
        request = _chat_request(
            status,
            request_id=str(uuid4()),
            conversation_id=str(uuid4()),
            message="Ника, ты здесь?",
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request, timeout=5)
        assert error.value.code == 503
        with urlopen(
            Request(
                f"http://127.0.0.1:{status['port']}{BRIDGE_CHAT_PATH}",
                data=None,
                headers={},
                method="OPTIONS",
            ),
            timeout=5,
        ) as response:
            assert response.status == 404
    finally:
        assert stop_runtime(settings)

    with Database(settings.database_path).connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        messages = connection.execute(
            "SELECT COUNT(*) FROM conversation_messages"
        ).fetchone()[0]
    assert count == 0
    assert messages == 0


def test_bridge_chat_rejects_replayed_hmac_nonce(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _runtime_settings(tmp_path)
    with fake_provider() as (base_url, provider_calls):
        monkeypatch.setenv("NIKA_LLM_BASE_URL", base_url)
        monkeypatch.setenv("NIKA_LLM_MODEL", "test-local-model")
        assert start_runtime(settings) == "started"
        try:
            status = _read_runtime_status(settings)
            timestamp = str(int(time.time()))
            nonce = secrets.token_urlsafe(24)
            kwargs = {
                "request_id": str(uuid4()),
                "conversation_id": str(uuid4()),
                "message": "Ника, проверка повтора.",
                "timestamp": timestamp,
                "nonce": nonce,
            }
            request = _chat_request(status, **kwargs)
            with urlopen(request, timeout=5) as response:
                assert response.status == 200
                response.read()

            replay = _chat_request(status, **kwargs)
            with pytest.raises(HTTPError) as error:
                urlopen(replay, timeout=5)
            assert error.value.code == 403
            assert len(provider_calls) == 1
        finally:
            assert stop_runtime(settings)
