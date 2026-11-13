import json
import os
import signal
import time
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
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )

    assert start_runtime(settings) == "started"
    crashed_status = get_runtime_status(settings)
    assert crashed_status is not None
    crashed_pid = crashed_status["pid"]
    status_path = settings.data_dir / "runtime" / "status.json"

    os.kill(crashed_pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while runtime._pid_is_running(crashed_pid) and time.monotonic() < deadline:
        time.sleep(0.05)

    assert not runtime._pid_is_running(crashed_pid)
    assert status_path.exists()  # An abrupt exit cannot run the cleanup block.
    assert get_runtime_status(settings) is None

    assert start_runtime(settings) == "started"
    assert get_runtime_status(settings) is not None
    assert stop_runtime(settings)


def test_start_recovers_stale_startup_lock(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    runtime_dir = settings.data_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "start.lock").write_text("999999999", encoding="ascii")

    assert start_runtime(settings) == "started"
    assert not (runtime_dir / "start.lock").exists()
    assert stop_runtime(settings)


def test_start_does_not_delete_a_fresh_unreadable_startup_lock(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "nika-data",
        database_path=tmp_path / "nika-data" / "nika.sqlite3",
    )
    runtime_dir = settings.data_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    lock_path = runtime_dir / "start.lock"
    lock_path.write_text("", encoding="ascii")

    with pytest.raises(RuntimeError, match="already starting"):
        start_runtime(settings)
    assert lock_path.exists()


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
