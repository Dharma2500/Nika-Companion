import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from nika.openai_provider import (
    OpenAIProviderManager,
    OpenAIResponsesProvider,
    OpenAISettings,
)
from nika.provider import ProviderError


def _response_body(text: str = "Привет, Виталий!") -> bytes:
    return json.dumps(
        {
            "id": "resp_test",
            "status": "completed",
            "model": "gpt-4.1-mini",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
            "usage": {
                "input_tokens": 42,
                "input_tokens_details": {"cached_tokens": 12},
                "output_tokens": 18,
                "output_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": 60,
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")


class _FakeOpenAIServer:
    def __init__(self, handler_factory):
        self.calls: list[dict[str, object]] = []
        calls = self.calls

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                calls.append(
                    {
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "body": body,
                    }
                )
                status, response = handler_factory(calls[-1])
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _context() -> dict[str, object]:
    return {
        "schema_version": 1,
        "personality": "Ты Ника. Отвечай честно и коротко.",
        "history": [{"role": "user", "content": "Привет!"}],
        "memories": [],
        "world_context": None,
    }


def test_responses_api_sends_compact_non_stored_request_and_parses_usage() -> None:
    with _FakeOpenAIServer(lambda _call: (200, _response_body())) as server:
        provider = OpenAIResponsesProvider(
            "sk-test-primary-012345678901234567",
            OpenAISettings(),
            base_url=server.base_url,
        )
        result = provider.complete(_context(), key_slot="primary")

    assert result.text == "Привет, Виталий!"
    assert result.key_slot == "primary"
    assert result.usage.input_tokens == 42
    assert result.usage.output_tokens == 18
    assert result.usage.cached_tokens == 12
    assert server.calls[0]["path"] == "/v1/responses"
    assert server.calls[0]["authorization"] == (
        "Bearer sk-test-primary-012345678901234567"
    )
    assert server.calls[0]["body"]["store"] is False
    assert server.calls[0]["body"]["max_output_tokens"] == 320
    assert "tools" not in server.calls[0]["body"]


def test_quota_exhaustion_switches_from_primary_to_secondary() -> None:
    def handler(call):
        if call["authorization"].endswith("primary-012345678901234567"):
            return (
                429,
                json.dumps(
                    {
                        "error": {
                            "type": "insufficient_quota",
                            "code": "insufficient_quota",
                            "message": "private billing details",
                        }
                    }
                ).encode(),
            )
        return 200, _response_body("Ответ от резервного ключа")

    with _FakeOpenAIServer(handler) as server:
        manager = OpenAIProviderManager()
        manager.configure(
            primary_key="sk-test-primary-012345678901234567",
            secondary_key="sk-test-secondary-012345678901234567",
            settings=OpenAISettings(),
            base_url=server.base_url,
        )
        result = manager.complete(_context())

    assert result.text == "Ответ от резервного ключа"
    assert result.key_slot == "secondary"
    assert len(server.calls) == 2
    assert server.calls[0]["authorization"].endswith(
        "primary-012345678901234567"
    )
    assert server.calls[1]["authorization"].endswith(
        "secondary-012345678901234567"
    )


def test_transient_rate_limit_does_not_burn_secondary_key() -> None:
    with _FakeOpenAIServer(
        lambda _call: (
            429,
            json.dumps(
                {
                    "error": {
                        "type": "rate_limit_error",
                        "code": "rate_limit_exceeded",
                        "message": "try later",
                    }
                }
            ).encode(),
        )
    ) as server:
        manager = OpenAIProviderManager()
        manager.configure(
            primary_key="sk-test-primary-012345678901234567",
            secondary_key="sk-test-secondary-012345678901234567",
            settings=OpenAISettings(),
            base_url=server.base_url,
        )
        with pytest.raises(ProviderError) as error:
            manager.complete(_context())

    assert error.value.kind == "rate_limit"
    assert len(server.calls) == 1


def test_invalid_request_does_not_fail_over() -> None:
    with _FakeOpenAIServer(
        lambda _call: (
            400,
            json.dumps(
                {
                    "error": {
                        "type": "invalid_request_error",
                        "code": "model_not_found",
                        "message": "model unavailable",
                    }
                }
            ).encode(),
        )
    ) as server:
        manager = OpenAIProviderManager()
        manager.configure(
            primary_key="sk-test-primary-012345678901234567",
            secondary_key="sk-test-secondary-012345678901234567",
            settings=OpenAISettings(),
            base_url=server.base_url,
        )
        with pytest.raises(ProviderError) as error:
            manager.complete(_context())

    assert error.value.kind == "invalid_request"
    assert len(server.calls) == 1


def test_openai_model_and_budget_settings_are_bounded() -> None:
    with pytest.raises(ValueError):
        OpenAISettings(max_output_tokens=5000)
    with pytest.raises(ValueError):
        OpenAISettings(daily_token_limit=1)
