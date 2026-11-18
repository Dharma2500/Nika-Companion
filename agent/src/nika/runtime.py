"""Local runtime process and authenticated loopback control endpoint."""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from http.cookies import SimpleCookie
from ctypes import wintypes
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from nika.config import Settings
from nika.context import ContextBuilder, ContextBuildError
from nika.database import SCHEMA_VERSION, Database
from nika.dashboard import render_dashboard
from nika.dialogue import (
    MAX_CHAT_REQUEST_BYTES,
    ChatValidationError,
    decode_chat_request,
)
from nika.event_store import EventStore, NewEvent
from nika.logging_setup import get_logger, setup_logging
from nika.memory import (
    ConversationStore,
    MemoryStore,
    MemoryValidationError,
    MessageInput,
)
from nika.observation import (
    MAX_OBSERVATION_BYTES,
    ObservationValidationError,
    decode_observation,
)
from nika.provider import (
    OpenAICompatibleProvider,
    ProviderConfigurationError,
    ProviderError,
    ProviderManager,
    load_provider_config,
)

LOGGER = get_logger(__name__)

_WINDOWS_MUTEX_GUARD = threading.Lock()
_WINDOWS_MUTEX_NAMES: set[str] = set()
_WINDOWS_MUTEX_HANDLES: dict[int, str] = {}

START_TIMEOUT = 15.0
STOP_TIMEOUT = 10.0

BRIDGE_PROTOCOL_VERSION = 1
BRIDGE_HELLO_PATH = "/bridge/v1/hello"
BRIDGE_OBSERVE_PATH = "/bridge/v1/observe"
BRIDGE_CHAT_PATH = "/bridge/v1/chat"
BRIDGE_MAX_REQUEST_BYTES = 64 * 1024
BRIDGE_MAX_CLOCK_SKEW_SECONDS = 60
BRIDGE_NONCE_TTL_SECONDS = 120
BRIDGE_MAX_TRACKED_NONCES = 4096

DASHBOARD_TICKET_TTL_SECONDS = 60
DASHBOARD_SESSION_TTL_SECONDS = 3600
DASHBOARD_MAX_PENDING_TICKETS = 8


def create_bridge_signature(
    token: str,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body: bytes = b"",
) -> str:
    """Create the protocol-v1 HMAC signature shared with the Minecraft client."""
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(
        (method.upper(), path, timestamp, nonce, body_hash)
    ).encode("utf-8")
    return hmac.new(token.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


class BridgeAuthenticator:
    """Authenticate bounded bridge requests and reject timestamp/nonce replays."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._seen_nonces: dict[str, float] = {}
        self._lock = threading.Lock()

    def verify(
        self,
        method: str,
        path: str,
        timestamp: str,
        nonce: str,
        signature: str,
        body: bytes = b"",
    ) -> bool:
        method = method.upper()
        is_handshake = method == "GET" and path == BRIDGE_HELLO_PATH and not body
        is_observation = (
            method == "POST"
            and path == BRIDGE_OBSERVE_PATH
            and 0 < len(body) <= MAX_OBSERVATION_BYTES
        )
        is_chat = (
            method == "POST"
            and path == BRIDGE_CHAT_PATH
            and 0 < len(body) <= MAX_CHAT_REQUEST_BYTES
        )
        if not (is_handshake or is_observation or is_chat):
            return False
        if len(body) > BRIDGE_MAX_REQUEST_BYTES:
            return False
        if not timestamp.isascii() or not timestamp.isdecimal() or len(timestamp) > 12:
            return False
        if not 16 <= len(nonce) <= 128 or not nonce.isascii():
            return False
        if any(not (character.isalnum() or character in "-_") for character in nonce):
            return False
        if len(signature) != 64 or any(
            character not in "0123456789abcdef" for character in signature
        ):
            return False

        now = time.time()
        issued_at = int(timestamp)
        if abs(now - issued_at) > BRIDGE_MAX_CLOCK_SKEW_SECONDS:
            return False

        expected = create_bridge_signature(
            self._token, method, path, timestamp, nonce, body
        )
        if not hmac.compare_digest(signature, expected):
            return False

        with self._lock:
            expired = [
                seen_nonce
                for seen_nonce, expires_at in self._seen_nonces.items()
                if expires_at < now
            ]
            for seen_nonce in expired:
                self._seen_nonces.pop(seen_nonce, None)
            if nonce in self._seen_nonces:
                return False
            if len(self._seen_nonces) >= BRIDGE_MAX_TRACKED_NONCES:
                return False
            self._seen_nonces[nonce] = now + BRIDGE_NONCE_TTL_SECONDS
        return True


def _runtime_dir(settings: Settings) -> Path:
    return settings.data_dir / "runtime"


def _status_path(settings: Settings) -> Path:
    return _runtime_dir(settings) / "status.json"


def _lock_path(settings: Settings) -> Path:
    return _runtime_dir(settings) / "start.lock"


def _read_status(settings: Settings) -> dict[str, Any] | None:
    try:
        data = json.loads(_status_path(settings).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if type(data.get("pid")) is not int or data["pid"] <= 0:
        return None
    if type(data.get("port")) is not int or not 1 <= data["port"] <= 65535:
        return None
    if not isinstance(data.get("token"), str) or not data["token"]:
        return None
    return data


def _request(
    status: dict[str, Any],
    method: str,
    path: str,
    timeout: float = 1.0,
) -> dict[str, Any] | None:
    request = Request(
        f"http://127.0.0.1:{status['port']}{path}",
        data=b"" if method == "POST" else None,
        headers={"X-Nika-Token": status["token"]},
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, HTTPException, json.JSONDecodeError, ValueError):
        return None
    return result if isinstance(result, dict) else None


def get_runtime_status(settings: Settings | None = None) -> dict[str, Any] | None:
    """Return live process status, or None when no responsive runtime exists."""
    settings = settings or Settings.from_env()
    status = _read_status(settings)
    if status is None:
        return None
    response = _request(status, "GET", "/status")
    if (
        response is None
        or response.get("state") != "running"
        or response.get("pid") != status["pid"]
    ):
        return None
    return response




def create_dashboard_ticket(settings: Settings | None = None) -> tuple[str, str]:
    """Create a single-use dashboard ticket through the authenticated local runtime."""
    settings = settings or Settings.from_env()
    status = _read_status(settings)
    if status is None or get_runtime_status(settings) is None:
        raise RuntimeError("Nika runtime is not running.")

    endpoint = (
        f"http://127.0.0.1:{status['port']}/dashboard/session/create"
    )
    request = Request(
        endpoint,
        data=b"",
        headers={"X-Nika-Token": status["token"]},
        method="POST",
    )
    try:
        with urlopen(request, timeout=3.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, HTTPException, json.JSONDecodeError, ValueError):
        raise RuntimeError("Could not create a local dashboard session.") from None

    ticket = payload.get("ticket") if isinstance(payload, dict) else None
    if not isinstance(ticket, str) or not ticket:
        raise RuntimeError("The local runtime returned an invalid dashboard ticket.")

    return f"http://127.0.0.1:{status['port']}/dashboard/", ticket


def _acquire_start_lock(settings: Settings) -> int:
    """Acquire an OS-level lock that the operating system releases on process exit."""
    lock_path = _lock_path(settings)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        create_mutex.restype = wintypes.HANDLE
        wait_for_single_object = kernel32.WaitForSingleObject
        wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        wait_for_single_object.restype = wintypes.DWORD
        release_mutex = kernel32.ReleaseMutex
        release_mutex.argtypes = [wintypes.HANDLE]
        release_mutex.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        lock_identity = str(lock_path.resolve()).casefold().encode("utf-8")
        mutex_name = (
            "Local\\NikaStartup-" + hashlib.sha256(lock_identity).hexdigest()
        )
        handle = create_mutex(None, False, mutex_name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())

        with _WINDOWS_MUTEX_GUARD:
            if mutex_name in _WINDOWS_MUTEX_NAMES:
                close_handle(handle)
                raise RuntimeError("Nika is already starting.")
            _WINDOWS_MUTEX_NAMES.add(mutex_name)

        wait_result = wait_for_single_object(handle, 0)
        if wait_result not in (0x00000000, 0x00000080):  # OBJECT_0 or ABANDONED
            winerror = ctypes.get_last_error()
            with _WINDOWS_MUTEX_GUARD:
                _WINDOWS_MUTEX_NAMES.discard(mutex_name)
            close_handle(handle)
            if wait_result == 0x00000102:  # WAIT_TIMEOUT
                raise RuntimeError("Nika is already starting.")
            raise ctypes.WinError(winerror)

        handle_value = int(handle)
        try:
            lock_path.write_text(str(os.getpid()), encoding="ascii")
        except Exception:
            release_mutex(handle)
            close_handle(handle)
            with _WINDOWS_MUTEX_GUARD:
                _WINDOWS_MUTEX_NAMES.discard(mutex_name)
            raise

        with _WINDOWS_MUTEX_GUARD:
            _WINDOWS_MUTEX_HANDLES[handle_value] = mutex_name
        return handle_value

    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
        os.lseek(descriptor, 0, os.SEEK_SET)

        import fcntl

        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError("Nika is already starting.") from error

        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _release_start_lock(descriptor: int) -> None:
    """Release the OS-level startup lock."""
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        release_mutex = kernel32.ReleaseMutex
        release_mutex.argtypes = [wintypes.HANDLE]
        release_mutex.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        try:
            if not release_mutex(wintypes.HANDLE(descriptor)):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            if not close_handle(wintypes.HANDLE(descriptor)):
                LOGGER.error(
                    "runtime.start_mutex_close_failed",
                    extra={"winerror": ctypes.get_last_error()},
                )
            with _WINDOWS_MUTEX_GUARD:
                mutex_name = _WINDOWS_MUTEX_HANDLES.pop(descriptor, None)
                if mutex_name is not None:
                    _WINDOWS_MUTEX_NAMES.discard(mutex_name)
        return

    try:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        LOGGER.exception("runtime.start_lock_release_failed")
    finally:
        os.close(descriptor)


def _check_stale_runtime_status(settings: Settings) -> bool:
    """Reject ambiguous live processes and report status left by a crashed one."""
    status_path = _status_path(settings)
    if not status_path.exists():
        return False

    status = _read_status(settings)
    if status is None:
        raise RuntimeError(
            f"Nika runtime status file is invalid: {status_path}. "
            "It was preserved for inspection; refusing to start another instance."
        )

    response = _request(status, "GET", "/status")
    if (
        response is not None
        and response.get("state") == "running"
        and response.get("pid") == status["pid"]
    ):
        return True

    pid = status["pid"]
    if _pid_is_running(pid):
        raise RuntimeError(
            f"Nika runtime process {pid} is still alive, but its control endpoint "
            "is not responding. Refusing to start another instance."
        )

    # Keep the stale file until the new runtime atomically replaces it. This avoids
    # deleting a newer process's status during a concurrent startup.
    LOGGER.warning("runtime.stale_status_detected", extra={"pid": pid})
    return False


def start_runtime(settings: Settings | None = None) -> str:
    """Start one detached runtime process and wait until its control endpoint is ready."""
    settings = settings or Settings.from_env()
    runtime_dir = _runtime_dir(settings)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    if get_runtime_status(settings) is not None:
        LOGGER.info("runtime.start_skipped", extra={"reason": "already_running"})
        return "already_running"

    LOGGER.info("runtime.start_requested")
    descriptor = _acquire_start_lock(settings)
    try:
        if get_runtime_status(settings) is not None:
            _release_start_lock(descriptor)
            LOGGER.info("runtime.start_skipped", extra={"reason": "already_running"})
            return "already_running"
        if _check_stale_runtime_status(settings):
            _release_start_lock(descriptor)
            LOGGER.info("runtime.start_skipped", extra={"reason": "already_running"})
            return "already_running"
    except Exception:
        _release_start_lock(descriptor)
        raise

    log_path = settings.data_dir / "logs" / "runtime.jsonl"
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW

    child_env = os.environ.copy()
    child_env["NIKA_DATA"] = str(settings.data_dir.resolve())
    child_env["NIKA_DATABASE_PATH"] = str(settings.database_path.resolve())

    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "nika.runtime", "--serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
            start_new_session=os.name != "nt",
            env=child_env,
        )
    except OSError:
        _release_start_lock(descriptor)
        raise

    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        live_status = get_runtime_status(settings)
        if live_status is not None:
            _release_start_lock(descriptor)
            LOGGER.info("runtime.started", extra={"pid": live_status["pid"]})
            return "started"
        if process.poll() is not None:
            _release_start_lock(descriptor)
            raise RuntimeError(
                f"Nika runtime exited during startup. Check the log: {log_path}"
            )
        time.sleep(0.2)

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
    _release_start_lock(descriptor)
    raise RuntimeError(f"Nika runtime did not become ready. Check the log: {log_path}")


def stop_runtime(settings: Settings | None = None) -> bool:
    """Request graceful shutdown and wait for the control endpoint to disappear."""
    settings = settings or Settings.from_env()
    status = _read_status(settings)
    if status is None:
        return False

    response = _request(status, "POST", "/stop")
    if response is None or response.get("accepted") is not True:
        LOGGER.warning("runtime.stop_request_rejected")
        return False

    LOGGER.info("runtime.stop_requested", extra={"pid": status.get("pid")})

    deadline = time.monotonic() + STOP_TIMEOUT
    status_path = _status_path(settings)
    while time.monotonic() < deadline:
        endpoint_stopped = _request(status, "GET", "/status", timeout=0.3) is None
        if endpoint_stopped and not status_path.exists():
            LOGGER.info("runtime.stopped", extra={"pid": status.get("pid")})
            return True
        time.sleep(0.2)
    return False


@contextmanager
def runtime_maintenance_lock(settings: Settings | None = None) -> Iterator[None]:
    """Reserve startup and stop any known runtime before database maintenance."""
    settings = settings or Settings.from_env()
    descriptor = _acquire_start_lock(settings)
    try:
        status_path = _status_path(settings)
        if status_path.exists():
            status = _read_status(settings)
            if status is None:
                raise RuntimeError(
                    f"Nika runtime status file is invalid: {status_path}. "
                    "Refusing database maintenance until it is inspected."
                )

            response = _request(status, "GET", "/status")
            runtime_responds = (
                response is not None
                and response.get("state") == "running"
                and response.get("pid") == status["pid"]
            )
            if runtime_responds:
                if not stop_runtime(settings):
                    raise RuntimeError(
                        "Nika runtime did not stop cleanly; database was not changed."
                    )
            elif _pid_is_running(status["pid"]):
                raise RuntimeError(
                    f"Nika runtime process {status['pid']} is still alive but "
                    "unresponsive; database was not changed."
                )
            else:
                LOGGER.warning(
                    "runtime.stale_status_removed_for_maintenance",
                    extra={"pid": status["pid"]},
                )
                status_path.unlink(missing_ok=True)

        if status_path.exists():
            raise RuntimeError(
                "Nika runtime status remains after shutdown; database was not changed."
            )
        yield
    finally:
        _release_start_lock(descriptor)


def _pid_is_running(pid: int) -> bool:
    """Check a PID without sending a signal that could affect the process on Windows."""
    if pid <= 0:
        return False
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        open_process.restype = ctypes.c_void_p
        handle = open_process(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            # Access denied means the process exists but cannot be queried.
            return ctypes.get_last_error() == 5
        try:
            exit_code = ctypes.c_ulong()
            get_exit_code = kernel32.GetExitCodeProcess
            get_exit_code.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            get_exit_code.restype = ctypes.c_int
            if not get_exit_code(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [ctypes.c_void_p]
            close_handle.restype = ctypes.c_int
            close_handle(handle)
    if sys.platform.startswith("linux"):
        try:
            process_stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
            closing_parenthesis = process_stat.rfind(")")
            if closing_parenthesis >= 0:
                fields = process_stat[closing_parenthesis + 2 :].split()
                if fields and fields[0] in {"Z", "X"}:
                    return False
        except FileNotFoundError:
            return False
        except OSError:
            pass

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _install_windows_close_handler(
    stop_event: threading.Event,
    shutdown_complete: threading.Event,
) -> tuple[Any, Any]:
    """Wait for foreground runtime cleanup when its console window is closed."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handler_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

    @handler_type
    def handle_console_event(event_code: int) -> int:
        if event_code not in (2, 5, 6):  # CLOSE, LOGOFF, SHUTDOWN
            return 0
        stop_event.set()
        shutdown_complete.wait(timeout=4.0)
        return 1

    register_handler = kernel32.SetConsoleCtrlHandler
    register_handler.argtypes = [handler_type, wintypes.BOOL]
    register_handler.restype = wintypes.BOOL
    if not register_handler(handle_console_event, True):
        raise ctypes.WinError(ctypes.get_last_error())
    return kernel32, handle_console_event


def serve(foreground: bool = False) -> None:
    """Run the local control server until a graceful stop request arrives."""
    settings = Settings.from_env()
    if foreground and get_runtime_status(settings) is not None:
        raise RuntimeError("Nika is already running. Stop the existing runtime first.")

    runtime_dir = _runtime_dir(settings)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    foreground_lock_descriptor: int | None = None
    if foreground:
        foreground_lock_descriptor = _acquire_start_lock(settings)
        try:
            if get_runtime_status(settings) is not None:
                raise RuntimeError("Nika is already running. Stop the existing runtime first.")
            if _check_stale_runtime_status(settings):
                raise RuntimeError(
                    "Nika is already running. Stop the existing runtime first."
                )
        except Exception:
            _release_start_lock(foreground_lock_descriptor)
            foreground_lock_descriptor = None
            raise

    token = secrets.token_urlsafe(32)
    bridge_token = secrets.token_urlsafe(32)
    bridge_authenticator = BridgeAuthenticator(bridge_token)
    database = Database(settings.database_path)
    database.initialize()
    event_store = EventStore(database)
    memory_store = MemoryStore(database)
    conversation_store = ConversationStore(database)
    context_builder = ContextBuilder(conversation_store, memory_store)
    provider_manager = ProviderManager()
    try:
        provider_config = load_provider_config()
        if provider_config is not None:
            provider_manager = ProviderManager(
                OpenAICompatibleProvider(provider_config)
            )
    except ProviderConfigurationError:
        # Keep the local runtime and memory available; never log config values.
        LOGGER.error("runtime.provider_configuration_invalid")
    chat_request_lock = threading.Lock()
    dashboard_auth_lock = threading.Lock()
    dashboard_tickets: dict[str, float] = {}
    dashboard_sessions: dict[str, float] = {}
    stop_event = threading.Event()
    shutdown_complete = threading.Event()
    _console_handler: tuple[Any, Any] | None = None

    class Handler(BaseHTTPRequestHandler):
        def _authorized(self) -> bool:
            supplied = self.headers.get("X-Nika-Token", "")
            return secrets.compare_digest(supplied, token)

        def _dashboard_expected_host(self) -> str:
            if server is None:
                return ""
            return f"127.0.0.1:{server.server_address[1]}"

        def _dashboard_local_host(self) -> bool:
            return self.headers.get("Host", "").lower() == self._dashboard_expected_host()

        def _dashboard_origin(self) -> str:
            return f"http://{self._dashboard_expected_host()}"

        def _dashboard_session_valid(self) -> bool:
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except Exception:
                return False
            morsel = cookie.get("nika_dashboard_session")
            if morsel is None:
                return False

            now = time.time()
            with dashboard_auth_lock:
                expired = [
                    key for key, expires_at in dashboard_sessions.items()
                    if expires_at <= now
                ]
                for key in expired:
                    dashboard_sessions.pop(key, None)
                return morsel.value in dashboard_sessions

        def _bridge_authorized(self) -> bool:
            return bridge_authenticator.verify(
                method=self.command,
                path=self.path,
                timestamp=self.headers.get("X-Nika-Bridge-Timestamp", ""),
                nonce=self.headers.get("X-Nika-Bridge-Nonce", ""),
                signature=self.headers.get("X-Nika-Bridge-Signature", ""),
            )

        def _send(self, status_code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path in {"/dashboard", "/dashboard/"}:
                if not self._dashboard_local_host():
                    self._send(403, {"error": "local_host_required"})
                    return
                nonce = secrets.token_urlsafe(24)
                body = render_dashboard(nonce)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'none'; "
                    f"script-src 'nonce-{nonce}'; "
                    f"style-src 'nonce-{nonce}'; "
                    "connect-src 'self'; img-src 'none'; "
                    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
                )
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/dashboard/api/status":
                if not self._dashboard_local_host():
                    self._send(403, {"error": "local_host_required"})
                    return
                if not self._dashboard_session_valid():
                    self._send(401, {"error": "dashboard_session_required"})
                    return

                database_healthy = False
                counts: dict[str, int | None] = {
                    "events": None,
                    "memories": None,
                    "conversations": None,
                    "messages": None,
                }
                try:
                    database_healthy = database.health_check()
                    with closing(database.connect()) as connection:
                        counts = {
                            "events": int(
                                connection.execute("SELECT COUNT(*) FROM event_log").fetchone()[0]
                            ),
                            "memories": int(
                                connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
                            ),
                            "conversations": int(
                                connection.execute(
                                    "SELECT COUNT(*) FROM conversations"
                                ).fetchone()[0]
                            ),
                            "messages": int(
                                connection.execute(
                                    "SELECT COUNT(*) FROM conversation_messages"
                                ).fetchone()[0]
                            ),
                        }
                except sqlite3.Error:
                    LOGGER.warning("runtime.dashboard_database_check_failed")

                started_at = status_data.get("started_at", time.time())
                self._send(
                    200,
                    {
                        "runtime": "running",
                        "uptime_seconds": max(0.0, time.time() - float(started_at)),
                        "database": {
                            "healthy": database_healthy,
                            "schema_version": SCHEMA_VERSION,
                        },
                        "provider": {"configured": provider_manager.is_available},
                        "capabilities": [
                            "health.read",
                            "observation.submit",
                            *(
                                ["dialogue.chat"]
                                if provider_manager.is_available
                                else []
                            ),
                        ],
                        "counts": counts,
                    },
                )
                return

            if self.path == "/status":
                if not self._authorized():
                    self._send(403, {"error": "unauthorized"})
                else:
                    self._send(
                        200,
                        {
                            "state": "running",
                            "pid": os.getpid(),
                            "version": "0.1.0",
                        },
                    )
                return

            if self.path != BRIDGE_HELLO_PATH:
                self._send(404, {"error": "not_found"})
                return

            raw_length = self.headers.get("Content-Length", "0")
            if not raw_length.isascii() or not raw_length.isdecimal():
                self._send(400, {"error": "invalid_content_length"})
                return
            if len(raw_length) > 10:
                self._send(413, {"error": "request_too_large"})
                return
            content_length = int(raw_length)
            if content_length > BRIDGE_MAX_REQUEST_BYTES:
                self._send(413, {"error": "request_too_large"})
                return
            if content_length != 0 or self.headers.get("Transfer-Encoding") is not None:
                self._send(400, {"error": "body_not_allowed"})
                return
            if not self._bridge_authorized():
                self._send(403, {"error": "unauthorized"})
                return

            self._send(
                200,
                {
                    "service": "nika",
                    "protocol_version": BRIDGE_PROTOCOL_VERSION,
                    "state": "running",
                    "pid": os.getpid(),
                    "version": "0.1.0",
                    "capabilities": [
                        "health.read",
                        "observation.submit",
                        *(
                            ["dialogue.chat"]
                            if provider_manager.is_available
                            else []
                        ),
                    ],
                },
            )

        def do_POST(self) -> None:
            if self.path == "/dashboard/session/create":
                if not self._dashboard_local_host() or not self._authorized():
                    self._send(403, {"error": "unauthorized"})
                    return

                now = time.time()
                ticket = secrets.token_urlsafe(32)
                with dashboard_auth_lock:
                    expired = [
                        key for key, expires_at in dashboard_tickets.items()
                        if expires_at <= now
                    ]
                    for key in expired:
                        dashboard_tickets.pop(key, None)
                    while len(dashboard_tickets) >= DASHBOARD_MAX_PENDING_TICKETS:
                        oldest = min(dashboard_tickets, key=dashboard_tickets.get)
                        dashboard_tickets.pop(oldest, None)
                    dashboard_tickets[ticket] = now + DASHBOARD_TICKET_TTL_SECONDS

                self._send(
                    201,
                    {"ticket": ticket, "expires_in": DASHBOARD_TICKET_TTL_SECONDS},
                )
                return

            if self.path == "/dashboard/session/exchange":
                if (
                    not self._dashboard_local_host()
                    or self.headers.get("Origin") != self._dashboard_origin()
                    or self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin"
                ):
                    self._send(403, {"error": "same_origin_required"})
                    return

                raw_length = self.headers.get("Content-Length", "")
                if not raw_length or not raw_length.isascii() or not raw_length.isdecimal():
                    self._send(400, {"error": "invalid_content_length"})
                    return
                if len(raw_length) > 4 or int(raw_length) > 4096:
                    self._send(413, {"error": "dashboard_request_too_large"})
                    return
                if self.headers.get("Transfer-Encoding") is not None:
                    self._send(400, {"error": "invalid_dashboard_body"})
                    return
                content_type = self.headers.get("Content-Type", "")
                if content_type.split(";", 1)[0].strip().lower() != "application/json":
                    self._send(415, {"error": "application_json_required"})
                    return

                body = self.rfile.read(int(raw_length))
                try:
                    payload = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send(400, {"error": "invalid_dashboard_body"})
                    return
                if (
                    not isinstance(payload, dict)
                    or set(payload) != {"ticket"}
                    or not isinstance(payload["ticket"], str)
                    or not 32 <= len(payload["ticket"]) <= 128
                ):
                    self._send(400, {"error": "invalid_dashboard_ticket"})
                    return

                now = time.time()
                with dashboard_auth_lock:
                    expiry = dashboard_tickets.pop(payload["ticket"], None)
                    if expiry is None or expiry <= now:
                        self._send(403, {"error": "dashboard_ticket_invalid_or_expired"})
                        return
                    session = secrets.token_urlsafe(32)
                    dashboard_sessions[session] = now + DASHBOARD_SESSION_TTL_SECONDS

                response_body = json.dumps({"authenticated": True}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(response_body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header(
                    "Set-Cookie",
                    "nika_dashboard_session="
                    + session
                    + "; HttpOnly; SameSite=Strict; Path=/dashboard; Max-Age="
                    + str(DASHBOARD_SESSION_TTL_SECONDS),
                )
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(response_body)
                return

            if self.path == BRIDGE_CHAT_PATH:
                raw_length = self.headers.get("Content-Length", "")
                if (
                    not raw_length
                    or not raw_length.isascii()
                    or not raw_length.isdecimal()
                ):
                    self._send(400, {"error": "invalid_content_length"})
                    return
                if len(raw_length) > 10:
                    self._send(413, {"error": "request_too_large"})
                    return
                content_length = int(raw_length)
                if content_length > MAX_CHAT_REQUEST_BYTES:
                    self._send(413, {"error": "chat_request_too_large"})
                    return
                if (
                    content_length == 0
                    or self.headers.get("Transfer-Encoding") is not None
                ):
                    self._send(400, {"error": "invalid_chat_body"})
                    return
                content_type = self.headers.get("Content-Type", "")
                if content_type.split(";", 1)[0].strip().lower() != "application/json":
                    self._send(415, {"error": "application_json_required"})
                    return

                body = self.rfile.read(content_length)
                if len(body) != content_length:
                    self._send(400, {"error": "incomplete_request_body"})
                    return
                if not bridge_authenticator.verify(
                    method=self.command,
                    path=self.path,
                    timestamp=self.headers.get("X-Nika-Bridge-Timestamp", ""),
                    nonce=self.headers.get("X-Nika-Bridge-Nonce", ""),
                    signature=self.headers.get("X-Nika-Bridge-Signature", ""),
                    body=body,
                ):
                    self._send(403, {"error": "unauthorized"})
                    return

                try:
                    chat_request = decode_chat_request(body)
                except ChatValidationError as error:
                    self._send(
                        400,
                        {"error": "invalid_chat_request", "message": str(error)},
                    )
                    return

                if not provider_manager.is_available:
                    self._send(503, {"error": "provider_unconfigured"})
                    return

                # The local runtime is a single trusted process. Serializing chat
                # requests prevents simultaneous duplicate generation while the
                # unique request IDs keep retries idempotent across reconnects.
                with chat_request_lock:
                    try:
                        conversation = conversation_store.get_conversation(
                            chat_request.conversation_id
                        )
                        if conversation is None:
                            try:
                                conversation = conversation_store.create_conversation(
                                    conversation_id=chat_request.conversation_id
                                )
                            except sqlite3.IntegrityError:
                                conversation = conversation_store.get_conversation(
                                    chat_request.conversation_id
                                )
                                if conversation is None:
                                    raise

                        existing_user = conversation_store.get_message_by_request_id(
                            chat_request.request_id
                        )
                        if existing_user is not None and (
                            existing_user.conversation_id != chat_request.conversation_id
                            or existing_user.role != "user"
                            or existing_user.content != chat_request.message
                            or existing_user.source != "minecraft-client"
                        ):
                            self._send(409, {"error": "request_id_conflict"})
                            return

                        assistant_request_id = f"{chat_request.request_id}:assistant"
                        cached_reply = conversation_store.get_message_by_request_id(
                            assistant_request_id
                        )
                        if cached_reply is not None:
                            if (
                                cached_reply.conversation_id
                                != chat_request.conversation_id
                                or cached_reply.role != "assistant"
                            ):
                                self._send(409, {"error": "request_id_conflict"})
                                return
                            self._send(
                                200,
                                {
                                    "service": "nika",
                                    "accepted": True,
                                    "conversation_id": chat_request.conversation_id,
                                    "request_id": chat_request.request_id,
                                    "assistant_message_id": cached_reply.message_id,
                                    "reply": cached_reply.content,
                                    "cached": True,
                                },
                            )
                            return

                        conversation_store.append_message(
                            chat_request.conversation_id,
                            MessageInput(
                                role="user",
                                content=chat_request.message,
                                source="minecraft-client",
                                request_id=chat_request.request_id,
                            ),
                        )
                        conversation = conversation_store.get_conversation(
                            chat_request.conversation_id
                        )
                        if conversation is None:
                            raise MemoryValidationError("Conversation disappeared.")

                        context = context_builder.build(
                            chat_request.conversation_id,
                            chat_request.message,
                            world_id=conversation.world_id,
                        )
                    except (MemoryValidationError, ContextBuildError) as error:
                        self._send(
                            400,
                            {"error": "invalid_conversation", "message": str(error)},
                        )
                        return
                    except sqlite3.Error:
                        LOGGER.exception("runtime.chat_persistence_failed")
                        self._send(503, {"error": "chat_persistence_failed"})
                        return

                    try:
                        reply = provider_manager.complete(context)
                    except ProviderError:
                        # The user turn remains stored. Retrying the same request ID
                        # reuses it and only retries generation; no chat text is logged.
                        self._send(503, {"error": "provider_unavailable"})
                        return

                    try:
                        assistant_message = conversation_store.append_message(
                            chat_request.conversation_id,
                            MessageInput(
                                role="assistant",
                                content=reply,
                                source="nika-core",
                                request_id=assistant_request_id,
                            ),
                        )
                    except (MemoryValidationError, sqlite3.Error):
                        LOGGER.exception("runtime.chat_reply_persist_failed")
                        self._send(503, {"error": "reply_persistence_failed"})
                        return

                    self._send(
                        200,
                        {
                            "service": "nika",
                            "accepted": True,
                            "conversation_id": chat_request.conversation_id,
                            "request_id": chat_request.request_id,
                            "assistant_message_id": assistant_message.message_id,
                            "reply": assistant_message.content,
                            "cached": False,
                        },
                    )
                return

            if self.path == BRIDGE_OBSERVE_PATH:
                raw_length = self.headers.get("Content-Length", "")
                if not raw_length or not raw_length.isascii() or not raw_length.isdecimal():
                    self._send(400, {"error": "invalid_content_length"})
                    return
                if len(raw_length) > 10:
                    self._send(413, {"error": "request_too_large"})
                    return
                content_length = int(raw_length)
                if content_length > MAX_OBSERVATION_BYTES:
                    self._send(413, {"error": "observation_too_large"})
                    return
                if (
                    content_length == 0
                    or self.headers.get("Transfer-Encoding") is not None
                ):
                    self._send(400, {"error": "invalid_observation_body"})
                    return
                content_type = self.headers.get("Content-Type", "")
                if content_type.split(";", 1)[0].strip().lower() != "application/json":
                    self._send(415, {"error": "application_json_required"})
                    return

                body = self.rfile.read(content_length)
                if len(body) != content_length:
                    self._send(400, {"error": "incomplete_request_body"})
                    return
                if not bridge_authenticator.verify(
                    method=self.command,
                    path=self.path,
                    timestamp=self.headers.get("X-Nika-Bridge-Timestamp", ""),
                    nonce=self.headers.get("X-Nika-Bridge-Nonce", ""),
                    signature=self.headers.get("X-Nika-Bridge-Signature", ""),
                    body=body,
                ):
                    self._send(403, {"error": "unauthorized"})
                    return

                try:
                    observation = decode_observation(body)
                except ObservationValidationError as error:
                    self._send(
                        400,
                        {"error": "invalid_observation", "message": str(error)},
                    )
                    return

                try:
                    event_id = event_store.append(
                        NewEvent(
                            event_type=f"minecraft.observation.v{observation['schema_version']}",
                            source="minecraft-client",
                            payload=observation,
                        )
                    )
                except sqlite3.Error:
                    LOGGER.exception("runtime.observation_persist_failed")
                    self._send(503, {"error": "observation_persistence_failed"})
                    return

                self._send(
                    202,
                    {
                        "service": "nika",
                        "accepted": True,
                        "schema_version": observation["schema_version"],
                        "event_id": event_id,
                    },
                )
                return

            if self.path != "/stop":
                self._send(404, {"error": "not_found"})
            elif not self._authorized():
                self._send(403, {"error": "unauthorized"})
            else:
                self._send(200, {"accepted": True})
                LOGGER.info("runtime.shutdown_requested", extra={"pid": os.getpid()})
                stop_event.set()

        def log_message(self, format: str, *args: object) -> None:
            return

    server: ThreadingHTTPServer | None = None
    status_path = _status_path(settings)
    temporary_path = status_path.with_suffix(".tmp")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        server.timeout = 0.2
        status_data = {
            "pid": os.getpid(),
            "port": server.server_address[1],
            "token": token,
            "bridge_token": bridge_token,
            "bridge_protocol_version": BRIDGE_PROTOCOL_VERSION,
            "started_at": time.time(),
        }
        temporary_path.write_text(json.dumps(status_data), encoding="utf-8")
        os.replace(temporary_path, status_path)
        if foreground_lock_descriptor is not None:
            _release_start_lock(foreground_lock_descriptor)
            foreground_lock_descriptor = None
        if foreground and os.name == "nt":
            _console_handler = _install_windows_close_handler(
                stop_event,
                shutdown_complete,
            )
        LOGGER.info(
            "runtime.serve_started",
            extra={"pid": os.getpid(), "mode": "foreground" if foreground else "background"},
        )
        if foreground:
            print("Nika runtime: RUNNING", flush=True)
            print("Close this window to stop Nika safely.", flush=True)
        while not stop_event.is_set():
            server.handle_request()
    except KeyboardInterrupt:
        if foreground:
            print("\nNika runtime: stopping...", flush=True)
    finally:
        try:
            if server is not None:
                server.server_close()
            status_path.unlink(missing_ok=True)
            temporary_path.unlink(missing_ok=True)
            LOGGER.info("runtime.serve_stopped", extra={"pid": os.getpid()})
        finally:
            if foreground_lock_descriptor is not None:
                _release_start_lock(foreground_lock_descriptor)
            stop_event.set()
            shutdown_complete.set()


def main() -> None:
    settings = Settings.from_env()
    setup_logging(settings, filename="runtime.jsonl")
    if len(sys.argv) == 2 and sys.argv[1] == "--serve":
        try:
            serve()
        except Exception:
            LOGGER.exception("runtime.process_crashed")
            raise
    else:
        raise SystemExit("This module is managed by the nika command-line interface.")


if __name__ == "__main__":
    main()
