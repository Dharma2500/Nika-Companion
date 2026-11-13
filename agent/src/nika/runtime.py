"""Local runtime process and authenticated loopback control endpoint."""

from __future__ import annotations

import ctypes
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from nika.config import Settings
from nika.logging_setup import get_logger, setup_logging

LOGGER = get_logger(__name__)

START_TIMEOUT = 15.0
STOP_TIMEOUT = 10.0


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
    if not isinstance(data.get("port"), int) or not isinstance(data.get("token"), str):
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
    except (OSError, URLError, json.JSONDecodeError, ValueError):
        return None
    return result if isinstance(result, dict) else None


def get_runtime_status(settings: Settings | None = None) -> dict[str, Any] | None:
    """Return live process status, or None when no responsive runtime exists."""
    settings = settings or Settings.from_env()
    status = _read_status(settings)
    if status is None:
        return None
    response = _request(status, "GET", "/status")
    if response is None or response.get("state") != "running":
        return None
    return response


def start_runtime(settings: Settings | None = None) -> str:
    """Start one detached runtime process and wait until its control endpoint is ready."""
    settings = settings or Settings.from_env()
    runtime_dir = _runtime_dir(settings)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    if get_runtime_status(settings) is not None:
        LOGGER.info("runtime.start_skipped", extra={"reason": "already_running"})
        return "already_running"

    LOGGER.info("runtime.start_requested")
    lock_path = _lock_path(settings)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        try:
            lock_pid = int(lock_path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            lock_pid = -1
        if _pid_is_running(lock_pid):
            raise RuntimeError("Nika is already starting.") from error
        lock_path.unlink(missing_ok=True)
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)

    with os.fdopen(descriptor, "w", encoding="ascii") as lock_file:
        lock_file.write(str(os.getpid()))

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
        lock_path.unlink(missing_ok=True)
        raise

    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        live_status = get_runtime_status(settings)
        if live_status is not None:
            lock_path.unlink(missing_ok=True)
            LOGGER.info("runtime.started", extra={"pid": live_status["pid"]})
            return "started"
        if process.poll() is not None:
            lock_path.unlink(missing_ok=True)
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
    lock_path.unlink(missing_ok=True)
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
            return False
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
    token = secrets.token_urlsafe(32)
    stop_event = threading.Event()
    shutdown_complete = threading.Event()
    _console_handler: tuple[Any, Any] | None = None

    class Handler(BaseHTTPRequestHandler):
        def _authorized(self) -> bool:
            supplied = self.headers.get("X-Nika-Token", "")
            return secrets.compare_digest(supplied, token)

        def _send(self, status_code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/status":
                self._send(404, {"error": "not_found"})
            elif not self._authorized():
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

        def do_POST(self) -> None:
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

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.timeout = 0.2
    status_path = _status_path(settings)
    temporary_path = status_path.with_suffix(".tmp")
    status_data = {
        "pid": os.getpid(),
        "port": server.server_address[1],
        "token": token,
        "started_at": time.time(),
    }
    try:
        temporary_path.write_text(json.dumps(status_data), encoding="utf-8")
        os.replace(temporary_path, status_path)
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
            server.server_close()
            status_path.unlink(missing_ok=True)
            temporary_path.unlink(missing_ok=True)
            LOGGER.info("runtime.serve_stopped", extra={"pid": os.getpid()})
        finally:
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
