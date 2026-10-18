"""Real subprocess failures retain preparation receipts and terminate owned work."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from rea_backend import preparation


def receipt(directory):
    return json.loads((directory / "probe.command.json").read_text())


def capture_processes(monkeypatch):
    processes = []
    original = subprocess.Popen

    def start(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(preparation.subprocess, "Popen", start)
    return processes


def test_start_failure_preserves_empty_streams_and_command_receipt(tmp_path):
    argv = [str(tmp_path / "missing-executable")]
    with pytest.raises(OSError):
        preparation.run_logged(argv, tmp_path, "probe", timeout=1)
    record = receipt(tmp_path)
    assert record["status"] == "failed_to_start"
    assert record["argv"] == argv
    assert record["returncode"] is None
    assert record["seconds"] >= 0
    assert record["error"]
    assert (tmp_path / "probe.stdout.log").read_bytes() == b""
    assert (tmp_path / "probe.stderr.log").read_bytes() == b""


@pytest.mark.parametrize("returncode", [0, 7])
def test_exit_status_and_streams_survive_process_cleanup(tmp_path, monkeypatch, returncode):
    processes = capture_processes(monkeypatch)
    argv = [sys.executable, "-c", (
        "import sys; print('stdout evidence', flush=True); "
        "print('stderr evidence', file=sys.stderr, flush=True); "
        f"sys.exit({returncode})"
    )]
    if returncode:
        with pytest.raises(RuntimeError):
            preparation.run_logged(argv, tmp_path, "probe", timeout=5)
    else:
        preparation.run_logged(argv, tmp_path, "probe", timeout=5)
    record = receipt(tmp_path)
    assert record["status"] == ("failed" if returncode else "completed")
    assert record["argv"] == argv
    assert record["returncode"] == returncode
    assert record["cleanup"]["leader_reaped"] is True
    assert len(processes) == 1 and processes[0].poll() == returncode
    assert (tmp_path / "probe.stdout.log").read_text().strip() == "stdout evidence"
    assert (tmp_path / "probe.stderr.log").read_text().strip() == "stderr evidence"


def test_timeout_retains_partial_streams_and_reaps_process(tmp_path, monkeypatch):
    processes = capture_processes(monkeypatch)
    argv = [sys.executable, "-c", (
        "import sys,time; print('partial stdout', flush=True); "
        "print('partial stderr', file=sys.stderr, flush=True); time.sleep(30)"
    )]
    started = time.monotonic()
    with pytest.raises(RuntimeError):
        preparation.run_logged(argv, tmp_path, "probe", timeout=0.5)
    record = receipt(tmp_path)
    assert record["status"] == "timed_out"
    assert record["argv"] == argv
    assert record["returncode"] is not None
    assert record["cleanup"]["leader_reaped"] is True
    assert len(processes) == 1 and processes[0].poll() == record["returncode"]
    assert time.monotonic() - started < 8
    assert (tmp_path / "probe.stdout.log").read_text().strip() == "partial stdout"
    assert (tmp_path / "probe.stderr.log").read_text().strip() == "partial stderr"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
@pytest.mark.parametrize("parent_waits", [False, True])
def test_finished_or_timed_out_command_cannot_leave_descendant_work(tmp_path, parent_waits):
    leaked = tmp_path / "descendant-ran-after-cleanup"
    child = (
        "import signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(1.3); "
        f"Path({str(leaked)!r}).write_text('leaked')"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
        "print('child launched', flush=True)"
    )
    if parent_waits:
        parent += "; time.sleep(30)"
    argv = [sys.executable, "-c", parent]
    if parent_waits:
        with pytest.raises(RuntimeError):
            preparation.run_logged(argv, tmp_path, "probe", timeout=0.5)
    else:
        preparation.run_logged(argv, tmp_path, "probe", timeout=5)
    record = receipt(tmp_path)
    assert record["status"] == ("timed_out" if parent_waits else "completed")
    assert record["cleanup"]["sigterm_sent"] is True
    assert record["cleanup"]["leader_reaped"] is True
    time.sleep(1.4)
    assert not leaked.exists(), "A descendant outlived the command's process-group cleanup"
