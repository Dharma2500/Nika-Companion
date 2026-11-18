import json
import os
import secrets
import signal
import subprocess
import sys
import time
import uuid
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from nika import runtime
from nika.config import Settings
from nika.database import Database
from nika.event_store import EventStore
from nika.runtime import get_runtime_status, start_runtime, stop_runtime


def test_runtime_can_start_report_status_and_stop(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )

    assert start_runtime(settings) == "started"
    status = get_runtime_status(settings)
    assert status is not None
    assert status["state"] == "running"
    assert status["pid"] > 0

    assert start_runtime(settings) == "already_running"
    assert stop_runtime(settings)
    assert not (settings.data_dir / "runtime" / "status.json").exists()

    deadline = time.monotonic() + 3
    while get_runtime_status(settings) is not None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert get_runtime_status(settings) is None


def test_foreground_runtime_refuses_to_replace_running_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime,
        "get_runtime_status",
        lambda settings=None: {"state": "running"},
    )

    with pytest.raises(RuntimeError, match="already running"):
        runtime.serve(foreground=True)


def test_runtime_recovers_after_ungraceful_process_exit(tmp_path: Path) -> None:
    data_dir = tmp_path / f"nika-data-{uuid.uuid4().hex}"
    settings = Settings(data_dir=data_dir, database_path=data_dir / "nika.sqlite3")

    assert start_runtime(settings) == "started"
    crashed_status = get_runtime_status(settings)
    assert crashed_status is not None
    crashed_pid = crashed_status["pid"]
    status_path = settings.data_dir / "runtime" / "status.json"

    # SIGTERM is a forced process exit on Windows and the default termination
    # signal on POSIX. Do not call the Runtime shutdown endpoint.
    os.kill(crashed_pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while runtime._pid_is_running(crashed_pid) and time.monotonic() < deadline:
        time.sleep(0.05)

    assert not runtime._pid_is_running(crashed_pid)
    assert status_path.exists()  # A forced exit cannot run the cleanup block.
    assert get_runtime_status(settings) is None

    assert start_runtime(settings) == "started"
    assert get_runtime_status(settings) is not None
    assert stop_runtime(settings)


def test_stale_startup_marker_does_not_block_when_os_lock_is_free(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    runtime_dir = settings.data_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "start.lock").write_text("999999999", encoding="ascii")

    descriptor = runtime._acquire_start_lock(settings)
    runtime._release_start_lock(descriptor)


def test_startup_lock_is_exclusive_and_released_after_process_exit(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    env = os.environ.copy()
    env["NIKA_DATA"] = str(settings.data_dir)
    env["NIKA_DATABASE_PATH"] = str(settings.database_path)
    code = (
        "import time; "
        "from nika.config import Settings; "
        "from nika.runtime import _acquire_start_lock; "
        "_acquire_start_lock(Settings.from_env()); "
        "print('locked', flush=True); "
        "time.sleep(60)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    try:
        deadline = time.monotonic() + 5
        acquired_by_other = False
        while time.monotonic() < deadline and process.poll() is None:
            try:
                descriptor = runtime._acquire_start_lock(settings)
            except RuntimeError as error:
                assert "already starting" in str(error)
                acquired_by_other = True
                break
            else:
                runtime._release_start_lock(descriptor)
                time.sleep(0.05)

        assert acquired_by_other
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    descriptor = runtime._acquire_start_lock(settings)
    runtime._release_start_lock(descriptor)


def test_start_refuses_to_replace_invalid_status_file(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    runtime_dir = settings.data_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    status_path = runtime_dir / "status.json"
    status_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(RuntimeError, match="status file is invalid"):
        start_runtime(settings)
    assert status_path.read_text(encoding="utf-8") == "{broken"


def test_start_refuses_to_replace_status_for_unresponsive_live_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    runtime_dir = settings.data_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    status_path = runtime_dir / "status.json"
    status_path.write_text(
        json.dumps({"pid": os.getpid(), "port": 12345, "token": "test-token"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "_request", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_pid_is_running", lambda pid: True)

    with pytest.raises(RuntimeError, match="still alive"):
        start_runtime(settings)
    assert status_path.exists()


def test_runtime_status_rejects_a_different_responder_pid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    runtime_dir = settings.data_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "status.json").write_text(
        json.dumps({"pid": 12345, "port": 12345, "token": "test-token"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime,
        "_request",
        lambda *args, **kwargs: {"state": "running", "pid": 54321},
    )

    assert get_runtime_status(settings) is None


def test_request_handles_truncated_http_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TruncatedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def read(self) -> bytes:
            raise IncompleteRead(b"", 20)

    monkeypatch.setattr(runtime, "urlopen", lambda *args, **kwargs: TruncatedResponse())

    assert runtime._request({"port": 12345, "token": "test"}, "GET", "/status") is None

def test_maintenance_lock_stops_runtime_and_blocks_new_start(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    assert start_runtime(settings) == "started"

    with runtime.runtime_maintenance_lock(settings):
        assert get_runtime_status(settings) is None
        with pytest.raises(RuntimeError, match="already starting"):
            start_runtime(settings)

    assert start_runtime(settings) == "started"
    assert stop_runtime(settings)


def test_maintenance_lock_preserves_invalid_runtime_status(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    runtime_dir = settings.data_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    status_path = runtime_dir / "status.json"
    status_path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(RuntimeError, match="status file is invalid"):
        with runtime.runtime_maintenance_lock(settings):
            pytest.fail("maintenance must not begin with invalid runtime status")

    assert status_path.read_text(encoding="utf-8") == "{invalid"


def test_maintenance_lock_removes_dead_runtime_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    runtime_dir = settings.data_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    status_path = runtime_dir / "status.json"
    status_path.write_text(
        json.dumps({"pid": 2147483647, "port": 12345, "token": "stale-token"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "_pid_is_running", lambda pid: False)
    monkeypatch.setattr(runtime, "_request", lambda *args, **kwargs: None)

    with runtime.runtime_maintenance_lock(settings):
        assert not status_path.exists()

def _signed_bridge_request(
    status: dict[str, object],
    *,
    timestamp: str | None = None,
    nonce: str | None = None,
    signature: str | None = None,
) -> Request:
    issued_at = timestamp or str(int(time.time()))
    request_nonce = nonce or secrets.token_urlsafe(24)
    request_signature = signature or runtime.create_bridge_signature(
        str(status["bridge_token"]),
        "GET",
        runtime.BRIDGE_HELLO_PATH,
        issued_at,
        request_nonce,
    )
    return Request(
        f"http://127.0.0.1:{status['port']}{runtime.BRIDGE_HELLO_PATH}",
        headers={
            "X-Nika-Bridge-Timestamp": issued_at,
            "X-Nika-Bridge-Nonce": request_nonce,
            "X-Nika-Bridge-Signature": request_signature,
        },
        method="GET",
    )


def _signed_observation_request(
    status: dict[str, object],
    body: bytes,
    *,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> Request:
    issued_at = timestamp or str(int(time.time()))
    request_nonce = nonce or secrets.token_urlsafe(24)
    signature = runtime.create_bridge_signature(
        str(status["bridge_token"]),
        "POST",
        runtime.BRIDGE_OBSERVE_PATH,
        issued_at,
        request_nonce,
        body,
    )
    return Request(
        f"http://127.0.0.1:{status['port']}{runtime.BRIDGE_OBSERVE_PATH}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Nika-Bridge-Timestamp": issued_at,
            "X-Nika-Bridge-Nonce": request_nonce,
            "X-Nika-Bridge-Signature": signature,
        },
        method="POST",
    )


def _signed_chat_request(
    status: dict[str, object],
    body: bytes,
    *,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> Request:
    issued_at = timestamp or str(int(time.time()))
    request_nonce = nonce or secrets.token_urlsafe(24)
    signature = runtime.create_bridge_signature(
        str(status["bridge_token"]),
        "POST",
        runtime.BRIDGE_CHAT_PATH,
        issued_at,
        request_nonce,
        body,
    )
    return Request(
        f"http://127.0.0.1:{status['port']}{runtime.BRIDGE_CHAT_PATH}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Nika-Bridge-Timestamp": issued_at,
            "X-Nika-Bridge-Nonce": request_nonce,
            "X-Nika-Bridge-Signature": signature,
        },
        method="POST",
    )


def _sample_observation_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "client": {"minecraft_version": "1.21.11", "mod_version": "0.1.0"},
        "world": {"dimension": "minecraft:overworld"},
        "player": {
            "x": 125.5,
            "y": 72.0,
            "z": -4096.25,
            "health": 18.0,
            "food_level": 17,
            "selected_item": "minecraft:diamond_pickaxe",
        },
    }


def test_bridge_chat_without_provider_does_not_persist_user_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The runtime inherits environment variables from the test process. Keep
    # this check deterministic even when a developer has configured LM Studio.
    for name in ("NIKA_LLM_BASE_URL", "NIKA_LLM_MODEL", "NIKA_LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    assert start_runtime(settings) == "started"
    try:
        status = json.loads(
            (settings.data_dir / "runtime" / "status.json").read_text(
                encoding="utf-8"
            )
        )
        conversation_id = str(uuid.uuid4())
        body = json.dumps(
            {
                "schema_version": 1,
                "request_id": str(uuid.uuid4()),
                "conversation_id": conversation_id,
                "message": "Привет, Ника!",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = _signed_chat_request(status, body)

        with pytest.raises(HTTPError) as error:
            urlopen(request, timeout=2)
        assert error.value.code == 503

        database = Database(settings.database_path)
        with database.connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM conversation_messages"
            ).fetchone()[0]
        assert count == 0
    finally:
        assert stop_runtime(settings)


def test_bridge_observation_v3_persists_environment_and_player_state(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    assert start_runtime(settings) == "started"
    try:
        status = json.loads(
            (settings.data_dir / "runtime" / "status.json").read_text(
                encoding="utf-8"
            )
        )
        payload = _sample_observation_payload()
        payload["schema_version"] = 3
        payload["client"]["mod_version"] = "0.3.0"
        payload["world"]["block_sample"] = {
            "center": {"x": 125, "y": 72, "z": -4096},
            "range": {"x": 2, "y": 1, "z": 2},
            "scanned_positions": 75,
            "non_air_blocks": 0,
            "truncated": False,
            "blocks": [],
        }
        payload["world"]["environment"] = {
            "biome": "minecraft:plains",
            "time_of_day_ticks": 6000,
            "raining": False,
            "thundering": False,
            "light_level": 12,
        }
        payload["player"]["state"] = {
            "game_mode": "survival",
            "on_ground": True,
            "sprinting": False,
            "swimming": False,
            "crouching": False,
        }
        body = json.dumps(payload).encode("utf-8")
        request = _signed_observation_request(status, body)
        with urlopen(request, timeout=2) as response:
            acknowledgement = json.loads(response.read().decode("utf-8"))
            assert response.status == 202

        assert acknowledgement["schema_version"] == 3
        event_store = EventStore(Database(settings.database_path))
        event = event_store.get(acknowledgement["event_id"])
        assert event is not None
        assert event["event_type"] == "minecraft.observation.v3"
        assert json.loads(event["payload_json"]) == payload
        assert event_store.count() == 1
    finally:
        assert stop_runtime(settings)


def test_bridge_observation_v2_persists_bounded_block_sample(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    assert start_runtime(settings) == "started"
    try:
        status = json.loads(
            (settings.data_dir / "runtime" / "status.json").read_text(
                encoding="utf-8"
            )
        )
        payload = _sample_observation_payload()
        payload["schema_version"] = 2
        payload["client"]["mod_version"] = "0.2.0"
        payload["world"]["block_sample"] = {
            "center": {"x": 125, "y": 72, "z": -4096},
            "range": {"x": 2, "y": 1, "z": 2},
            "scanned_positions": 75,
            "non_air_blocks": 1,
            "truncated": False,
            "blocks": [
                {
                    "dx": 0,
                    "dy": -1,
                    "dz": 0,
                    "id": "minecraft:stone",
                    "properties": {},
                    "properties_truncated": False,
                }
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        request = _signed_observation_request(status, body)
        with urlopen(request, timeout=2) as response:
            acknowledgement = json.loads(response.read().decode("utf-8"))
            assert response.status == 202

        assert acknowledgement["schema_version"] == 2
        event_store = EventStore(Database(settings.database_path))
        event = event_store.get(acknowledgement["event_id"])
        assert event is not None
        assert event["event_type"] == "minecraft.observation.v2"
        assert json.loads(event["payload_json"]) == payload
        assert event_store.count() == 1
    finally:
        assert stop_runtime(settings)


def test_bridge_observation_v1_is_authenticated_and_persisted(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    assert start_runtime(settings) == "started"
    try:
        status = json.loads(
            (settings.data_dir / "runtime" / "status.json").read_text(
                encoding="utf-8"
            )
        )
        body = json.dumps(_sample_observation_payload()).encode("utf-8")
        timestamp = str(int(time.time()))
        nonce = secrets.token_urlsafe(24)
        request = _signed_observation_request(
            status, body, timestamp=timestamp, nonce=nonce
        )
        with urlopen(request, timeout=2) as response:
            acknowledgement = json.loads(response.read().decode("utf-8"))
            assert response.status == 202

        assert acknowledgement["service"] == "nika"
        assert acknowledgement["accepted"] is True
        assert acknowledgement["schema_version"] == 1
        event_store = EventStore(Database(settings.database_path))
        event = event_store.get(acknowledgement["event_id"])
        assert event is not None
        assert event["event_type"] == "minecraft.observation.v1"
        assert event["source"] == "minecraft-client"
        assert json.loads(event["payload_json"]) == _sample_observation_payload()

        replay = _signed_observation_request(
            status, body, timestamp=timestamp, nonce=nonce
        )
        with pytest.raises(HTTPError) as replay_error:
            urlopen(replay, timeout=2)
        assert replay_error.value.code == 403
        assert event_store.count() == 1
    finally:
        assert stop_runtime(settings)


def test_bridge_observation_rejects_invalid_payload_without_persisting(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    assert start_runtime(settings) == "started"
    try:
        status = json.loads(
            (settings.data_dir / "runtime" / "status.json").read_text(
                encoding="utf-8"
            )
        )
        payload = _sample_observation_payload()
        payload["unexpected"] = "must be rejected"
        body = json.dumps(payload).encode("utf-8")
        request = _signed_observation_request(status, body)

        with pytest.raises(HTTPError) as error:
            urlopen(request, timeout=2)
        assert error.value.code == 400
        assert EventStore(Database(settings.database_path)).count() == 0
    finally:
        assert stop_runtime(settings)


def test_bridge_v1_handshake_is_authenticated_and_replay_protected(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    assert start_runtime(settings) == "started"
    try:
        status_path = settings.data_dir / "runtime" / "status.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        assert status["bridge_protocol_version"] == runtime.BRIDGE_PROTOCOL_VERSION
        assert status["bridge_token"] != status["token"]

        timestamp = str(int(time.time()))
        nonce = secrets.token_urlsafe(24)
        request = _signed_bridge_request(status, timestamp=timestamp, nonce=nonce)
        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))

        assert payload["service"] == "nika"
        assert payload["protocol_version"] == 1
        assert payload["state"] == "running"
        assert payload["pid"] == status["pid"]
        assert payload["capabilities"] == ["health.read", "observation.submit"]

        replay = _signed_bridge_request(status, timestamp=timestamp, nonce=nonce)
        with pytest.raises(HTTPError) as error:
            urlopen(replay, timeout=2)
        assert error.value.code == 403
    finally:
        assert stop_runtime(settings)


def test_bridge_rejects_bad_signatures_and_expired_timestamps(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    assert start_runtime(settings) == "started"
    try:
        status = json.loads(
            (settings.data_dir / "runtime" / "status.json").read_text(
                encoding="utf-8"
            )
        )
        bad_signature = _signed_bridge_request(
            status,
            signature="0" * 64,
        )
        with pytest.raises(HTTPError) as bad_signature_error:
            urlopen(bad_signature, timeout=2)
        assert bad_signature_error.value.code == 403

        expired_timestamp = str(
            int(time.time()) - runtime.BRIDGE_MAX_CLOCK_SKEW_SECONDS - 10
        )
        expired = _signed_bridge_request(status, timestamp=expired_timestamp)
        with pytest.raises(HTTPError) as expired_error:
            urlopen(expired, timeout=2)
        assert expired_error.value.code == 403

        oversized_timestamp = _signed_bridge_request(
            status,
            timestamp="9" * 100,
        )
        with pytest.raises(HTTPError) as oversized_error:
            urlopen(oversized_timestamp, timeout=2)
        assert oversized_error.value.code == 403
    finally:
        assert stop_runtime(settings)




def test_dashboard_uses_single_use_ticket_and_redacted_local_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("NIKA_LLM_BASE_URL", "NIKA_LLM_MODEL", "NIKA_LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    assert start_runtime(settings) == "started"
    try:
        status = json.loads(
            (settings.data_dir / "runtime" / "status.json").read_text(
                encoding="utf-8"
            )
        )
        base_url = f"http://127.0.0.1:{status['port']}"
        dashboard_url = f"{base_url}/dashboard/"

        page_request = Request(dashboard_url)
        with urlopen(page_request, timeout=2) as response:
            page = response.read().decode("utf-8")
            policy = response.headers["Content-Security-Policy"]
            assert response.status == 200
            assert "Ника" in page
            assert "nonce-" in policy
            assert "frame-ancestors 'none'" in policy
            assert "https://" not in page

        unauthenticated = Request(f"{base_url}/dashboard/api/status")
        with pytest.raises(HTTPError) as unauthorized:
            urlopen(unauthenticated, timeout=2)
        assert unauthorized.value.code == 401

        ticket_request = Request(
            f"{base_url}/dashboard/session/create",
            data=b"",
            headers={"X-Nika-Token": status["token"]},
            method="POST",
        )
        with urlopen(ticket_request, timeout=2) as response:
            ticket_payload = json.loads(response.read().decode("utf-8"))
            assert response.status == 201
        ticket = ticket_payload["ticket"]
        assert ticket_payload["expires_in"] == 60

        exchange_body = json.dumps({"ticket": ticket}).encode("utf-8")
        wrong_origin = Request(
            f"{base_url}/dashboard/session/exchange",
            data=exchange_body,
            headers={
                "Content-Type": "application/json",
                "Origin": "https://example.invalid",
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as csrf_error:
            urlopen(wrong_origin, timeout=2)
        assert csrf_error.value.code == 403

        exchange = Request(
            f"{base_url}/dashboard/session/exchange",
            data=exchange_body,
            headers={
                "Content-Type": "application/json",
                "Origin": base_url,
            },
            method="POST",
        )
        with urlopen(exchange, timeout=2) as response:
            exchange_payload = json.loads(response.read().decode("utf-8"))
            cookie_header = response.headers["Set-Cookie"]
            assert response.status == 200
            assert exchange_payload == {"authenticated": True}
            assert "HttpOnly" in cookie_header
            assert "SameSite=Strict" in cookie_header
        cookie = cookie_header.split(";", 1)[0]

        status_request = Request(
            f"{base_url}/dashboard/api/status",
            headers={"Cookie": cookie},
        )
        with urlopen(status_request, timeout=2) as response:
            dashboard_status = json.loads(response.read().decode("utf-8"))
            assert response.status == 200

        assert dashboard_status["runtime"] == "running"
        assert dashboard_status["database"] == {
            "healthy": True,
            "schema_version": 2,
        }
        assert dashboard_status["provider"] == {"configured": False}
        assert dashboard_status["counts"] == {
            "events": 0,
            "memories": 0,
            "conversations": 0,
            "messages": 0,
        }
        assert "token" not in dashboard_status
        assert "bridge_token" not in dashboard_status
        assert "api_key" not in dashboard_status

        replay = Request(
            f"{base_url}/dashboard/session/exchange",
            data=exchange_body,
            headers={
                "Content-Type": "application/json",
                "Origin": base_url,
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as replay_error:
            urlopen(replay, timeout=2)
        assert replay_error.value.code == 403
    finally:
        assert stop_runtime(settings)
