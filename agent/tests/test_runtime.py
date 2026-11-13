import json
import os
import subprocess
import sys
import time
import uuid
from http.client import IncompleteRead
from pathlib import Path

import pytest

from nika import runtime
from nika.config import Settings
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
    # A unique directory prevents stale data from earlier interrupted test runs.
    data_dir = tmp_path / f"nika-data-{uuid.uuid4().hex}"
    settings = Settings(data_dir=data_dir, database_path=data_dir / "nika.sqlite3")
    env = os.environ.copy()
    env["NIKA_DATA"] = str(settings.data_dir)
    env["NIKA_DATABASE_PATH"] = str(settings.database_path)
    process = subprocess.Popen(
        [sys.executable, "-m", "nika.runtime", "--serve"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    status_path = settings.data_dir / "runtime" / "status.json"

    try:
        deadline = time.monotonic() + 10
        crashed_status = None
        while time.monotonic() < deadline:
            crashed_status = get_runtime_status(settings)
            if crashed_status is not None:
                break
            if process.poll() is not None:
                break
            time.sleep(0.05)

        assert crashed_status is not None
        assert crashed_status["pid"] == process.pid
        process.kill()
        process.wait(timeout=5)

        assert status_path.exists()  # A forced exit cannot run the cleanup block.
        assert get_runtime_status(settings) is None
        assert start_runtime(settings) == "started"
        assert get_runtime_status(settings) is not None
        assert stop_runtime(settings)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if get_runtime_status(settings) is not None:
            stop_runtime(settings)


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
