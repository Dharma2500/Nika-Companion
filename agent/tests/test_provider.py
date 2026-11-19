import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from nika.provider import (
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderConfigurationError,
    ProviderError,
    ProviderManager,
    load_provider_config,
    save_provider_config,
)


@contextmanager
def fake_chat_endpoint(
    response_body: bytes,
    *,
    status: int = 200,
) -> Iterator[tuple[str, dict[str, object]]]:
    captured: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            captured["path"] = self.path
            captured["authorization"] = self.headers.get("Authorization")
            captured["body"] = self.rfile.read(length)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/v1", captured
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def sample_context() -> dict[str, object]:
    return {
        "schema_version": 1,
        "personality": "Ты Ника. Отвечай честно.",
        "history": [{"role": "user", "content": "Привет, Ника!"}],
        "memories": [
            {
                "content": "Виталий предпочитает русский язык.",
                "provenance_type": "user_taught",
                "confidence": 1.0,
            }
        ],
        "world_context": None,
    }


def test_provider_loads_explicit_environment_configuration() -> None:
    config = load_provider_config(
        {
            "NIKA_LLM_BASE_URL": "http://127.0.0.1:1234/v1/",
            "NIKA_LLM_MODEL": "local-model",
            "NIKA_LLM_API_KEY": "local-token",
        }
    )

    assert config is not None
    assert config.base_url == "http://127.0.0.1:1234/v1"
    assert config.model == "local-model"
    assert config.api_key == "local-token"


def test_provider_is_unconfigured_when_environment_is_empty() -> None:
    assert load_provider_config({}) is None
    with pytest.raises(ProviderConfigurationError, match="configured together"):
        load_provider_config({"NIKA_LLM_BASE_URL": "http://127.0.0.1:1234/v1"})


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://127.0.0.1/v1",
        "http://user:password@127.0.0.1/v1",
        "http://127.0.0.1/v1?token=secret",
        "http://127.0.0.1/v1#fragment",
    ],
)
def test_provider_rejects_unsafe_or_invalid_base_urls(base_url: str) -> None:
    with pytest.raises(ProviderConfigurationError):
        ProviderConfig(base_url=base_url, model="local-model")


def test_provider_posts_chat_completions_and_returns_assistant_text() -> None:
    response = json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": "Привет, Виталий!"}}]},
        ensure_ascii=False,
    ).encode("utf-8")
    with fake_chat_endpoint(response) as (base_url, captured):
        provider = OpenAICompatibleProvider(
            ProviderConfig(base_url=base_url, model="local-model", api_key="secret")
        )
        result = provider.complete(sample_context())

    assert result == "Привет, Виталий!"
    assert captured["path"] == "/v1/chat/completions"
    assert captured["authorization"] == "Bearer secret"
    payload = json.loads(captured["body"])
    assert payload["model"] == "local-model"
    assert payload["stream"] is False
    assert payload["messages"][-1] == {
        "role": "user",
        "content": "Привет, Ника!",
    }
    assert "untrusted reference data" in payload["messages"][1]["content"]


def test_provider_sanitizes_http_errors_without_echoing_response_body() -> None:
    with fake_chat_endpoint(b"private server error", status=503) as (base_url, _):
        provider = OpenAICompatibleProvider(
            ProviderConfig(base_url=base_url, model="local-model")
        )
        with pytest.raises(ProviderError, match="HTTP 503") as error:
            provider.complete(sample_context())
    assert "private server error" not in str(error.value)


def test_provider_rejects_oversized_response() -> None:
    from nika.provider import MAX_PROVIDER_RESPONSE_BYTES

    body = b" " * (MAX_PROVIDER_RESPONSE_BYTES + 1)
    with fake_chat_endpoint(body) as (base_url, _):
        provider = OpenAICompatibleProvider(
            ProviderConfig(base_url=base_url, model="local-model")
        )
        with pytest.raises(ProviderError, match="64 KiB"):
            provider.complete(sample_context())


def test_provider_manager_reports_missing_provider_honestly() -> None:
    manager = ProviderManager()
    assert not manager.is_available
    with pytest.raises(ProviderError, match="No language model provider"):
        manager.complete(sample_context())



def test_provider_settings_are_saved_without_secrets_and_reloaded(tmp_path) -> None:
    path = tmp_path / "config" / "provider.json"
    saved = save_provider_config(
        path,
        base_url="http://127.0.0.1:1234/v1/",
        model="local-model",
    )

    assert saved.base_url == "http://127.0.0.1:1234/v1"
    assert path.exists()
    raw = path.read_text(encoding="utf-8")
    assert "api_key" not in raw
    assert "secret" not in raw

    loaded = load_provider_config({}, config_path=path)
    assert loaded is not None
    assert loaded.base_url == "http://127.0.0.1:1234/v1"
    assert loaded.model == "local-model"
    assert loaded.api_key is None


def test_environment_configuration_overrides_saved_provider_settings(tmp_path) -> None:
    path = tmp_path / "provider.json"
    save_provider_config(
        path,
        base_url="http://127.0.0.1:1234/v1",
        model="saved-model",
    )

    loaded = load_provider_config(
        {
            "NIKA_LLM_BASE_URL": "http://127.0.0.1:9999/v1",
            "NIKA_LLM_MODEL": "environment-model",
            "NIKA_LLM_API_KEY": "local-secret",
        },
        config_path=path,
    )

    assert loaded is not None
    assert loaded.base_url == "http://127.0.0.1:9999/v1"
    assert loaded.model == "environment-model"
    assert loaded.api_key == "local-secret"


def test_provider_configuration_rejects_duplicate_json_properties(tmp_path) -> None:
    path = tmp_path / "provider.json"
    path.write_text(
        '{"schema_version":1,"schema_version":1,'
        '"base_url":"http://127.0.0.1:1234/v1","model":"local-model"}',
        encoding="utf-8",
    )

    with pytest.raises(ProviderConfigurationError, match="valid JSON"):
        load_provider_config({}, config_path=path)


def test_provider_manager_can_be_configured_and_connection_tested() -> None:
    response = json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": "Nika connection OK"}}]}
    ).encode("utf-8")
    with fake_chat_endpoint(response) as (base_url, captured):
        manager = ProviderManager()
        assert not manager.is_available
        manager.configure(ProviderConfig(base_url=base_url, model="local-model"))
        assert manager.is_available
        manager.test_connection()

    assert captured["path"] == "/v1/chat/completions"
    payload = json.loads(captured["body"])
    assert payload["messages"][-1]["content"] == "Reply with exactly: Nika connection OK"
