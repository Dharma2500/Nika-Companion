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



def test_foreground_runtime_refuses_to_replace_running_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runtime,
        "get_runtime_status",
        lambda settings=None: {"state": "running"},
    )

    with pytest.raises(RuntimeError, match="already running"):
        runtime.serve(foreground=True)
