"""Synthetic device tests exercise lifecycle/evidence invariants, not App coverage."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import struct
import zlib

import pytest

from rea_backend import android_run as runner
from test_build_validation import make_build, write_json


def png_chunk(kind, content):
    return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content))


PNG = (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
       + png_chunk(b"IDAT", zlib.compress(b"\0\0\0\0\xff")) + png_chunk(b"IEND", b""))
XML = b'<hierarchy><node resource-id="fixture:id/open" bounds="[0,0][20,20]"/></hierarchy>'


class FakeDevice:
    instances = []
    bad_xml = False
    duplicate = False

    def __init__(self, adb, serial, avd, package, activity):
        self.adb, self.serial, self.avd, self.package, self.activity = Path(adb), serial, avd, package, activity
        self.commands = []
        self.instances.append(self)

    def identity(self):
        return {"serial": self.serial, "avd": self.avd, "package": self.package,
                "activity": self.activity, "fingerprint": "synthetic-device", "apk_sha256": "a" * 64}

    def run(self, *args, **kwargs):
        self.commands.append(args)
        if args[:3] == ("shell", "uiautomator", "dump"):
            out = b"ERROR: null root" if self.bad_xml else b"UI hierarchy dumped to: " + str(args[3]).encode()
        elif args[:2] == ("exec-out", "cat"):
            out = XML if not self.duplicate else XML.replace(b"</hierarchy>", XML.split(b"<hierarchy>")[1])
        elif args[:2] == ("exec-out", "screencap"):
            out = PNG
        elif args[:3] == ("shell", "am", "start"):
            out = b"Status: ok"
        elif args[:3] == ("shell", "pm", "clear"):
            out = b"Success\n"
        else:
            out = b""
        return subprocess.CompletedProcess(args, 0, out, b"")

    def force_stop(self):
        self.commands.append(("force-stop",))

    @staticmethod
    def _same_identity(expected, actual):
        assert expected == actual


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    script = """import socket, sys, time
from pathlib import Path
path = Path(sys.argv[2]) / 'starts.txt'
path.write_text(str(int(path.read_text()) + 1 if path.exists() else 1))
sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('127.0.0.1', int(sys.argv[1])))
sock.listen()
while True: time.sleep(1)
"""
    build, _, out = make_build(tmp_path, script)
    adb = tmp_path / "adb"
    adb.write_text("#!/bin/sh\nprintf 'synthetic adb\\n'\n")
    adb.chmod(0o700)
    plan = {"format": runner.FORMAT, "purpose": "Synthetic runner invariants", "initial_state": "Synthetic account/cache fixture; backend starts in a fresh run directory.",
            "device": {"serial": "emulator-5998", "avd": "fixture", "package": "org.example.fixture", "activity": "org.example.fixture/.Main", "apk_sha256": "a" * 64},
            "backend": {"argv": ["{python}", "{build}/implementation/check.py", "{port}", "{run}"],
                        "ready_argv": ["{python}", "-c", "import socket,sys; s=socket.create_connection(('127.0.0.1',int(sys.argv[1])),.5); s.close()", "{port}"],
                        "port": 0, "timeout_seconds": 5, "env": {}},
            "collectors": [{"id": "state", "kind": "storage", "argv": ["{python}", "-c", "import json,sys; from pathlib import Path; print(json.dumps({'starts':int(Path(sys.argv[1],'starts.txt').read_text())}))", "{run}"], "timeout_seconds": 3}],
            "steps": [{"id": "cold", "purpose": "Explicit app-data reset", "actions": [{"kind": "clear_app_data"}, {"kind": "launch"}], "ui_xml": "required"},
                      {"id": "persist", "purpose": "Same-storage service restart", "actions": [{"kind": "restart_backend"}, {"kind": "click", "attribute": "resource-id", "value": "fixture:id/open"}], "ui_xml": "required"}]}
    path = tmp_path / "android-plan.json"
    write_json(path, plan)
    FakeDevice.instances, FakeDevice.bad_xml, FakeDevice.duplicate = [], False, False
    monkeypatch.setattr(runner, "AndroidDevice", FakeDevice)
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    return build, path, out, adb, plan


def test_fresh_capture_restart_storage_identity_and_owned_cleanup(runtime):
    build, path, out, adb, _ = runtime
    result = runner.run_android(build, path, out, adb=adb)
    assert result["status"] == "captured", result
    assert result["business_correctness"] == "not_assessed"
    assert result["doctor"]["identity"]["apk_sha256"] == "a" * 64
    assert json.loads((out / "steps/cold/state.stdout").read_text()) == {"starts": 1}
    assert json.loads((out / "steps/persist/state.stdout").read_text()) == {"starts": 2}
    assert result["state_resets"][0]["accounts"] == "not_reset"
    assert all(v["status"] == "passed" for v in result["integrity"].values())
    cmds = FakeDevice.instances[-1].commands
    names = [args[3] for args in cmds if args[:3] == ("shell", "uiautomator", "dump")]
    assert len(names) == len(set(names)) == 3
    assert ("reverse", "--no-rebind", f"tcp:{result['port']}", f"tcp:{result['port']}") in cmds
    assert cmds[-1] == ("reverse", "--remove", f"tcp:{result['port']}")
    assert ("shell", "input", "tap", 10, 10) in cmds
    assert result == json.loads((out / "report.json").read_text())
    for event in result["lifecycle"]:
        if event["event"] == "start":
            with pytest.raises(ProcessLookupError):
                os.kill(event["pid"], 0)
    for name, digest in result["artifacts"].items():
        assert runner.file_hash(out / name) == digest


def test_identity_mismatch_stops_before_any_backend(runtime):
    build, path, out, adb, plan = runtime
    plan["device"]["apk_sha256"] = "b" * 64
    write_json(path, plan)
    result = runner.run_android(build, path, out, adb=adb)
    assert result["status"] == "failed" and "Installed APK" in result["error"]
    assert result["lifecycle"] == [] and not (out / "runtime").exists()


def test_apk_change_during_capture_invalidates_run_and_cleans_up(runtime, monkeypatch):
    from rea_backend.android import AndroidDevice

    build, path, out, adb, _ = runtime
    original, calls = FakeDevice.identity, []
    def identity(self):
        result = original(self)
        calls.append(result)
        if len(calls) > 1:
            result["apk_sha256"] = "b" * 64
        return result
    monkeypatch.setattr(FakeDevice, "identity", identity)
    monkeypatch.setattr(FakeDevice, "_same_identity", staticmethod(AndroidDevice._same_identity))
    result = runner.run_android(build, path, out, adb=adb)
    assert result["status"] == "failed" and "identity mismatch: apk_sha256" in result["error"]
    assert result["lifecycle"][-1]["event"] == "stop"
    assert FakeDevice.instances[-1].commands[-1][:2] == ("reverse", "--remove")


@pytest.mark.parametrize("policy,expected", [("required", "failed"), ("optional", "captured"), ("skip", "captured")])
def test_no_reuse_of_stale_ui_dump(runtime, policy, expected):
    build, path, out, adb, plan = runtime
    plan["steps"] = [{"id": "one", "purpose": "Unavailable hierarchy", "actions": [], "ui_xml": policy}]
    write_json(path, plan)
    FakeDevice.bad_xml = True
    result = runner.run_android(build, path, out, adb=adb)
    assert result["status"] == expected
    assert not (out / "steps/one/ui.xml").exists()
    assert (out / "steps/one/screen.png").read_bytes() == PNG


def test_ambiguous_selector_preserves_failure_and_stops_backend(runtime):
    build, path, out, adb, plan = runtime
    plan["steps"] = [plan["steps"][1]]
    write_json(path, plan)
    FakeDevice.duplicate = True
    result = runner.run_android(build, path, out, adb=adb)
    assert result["status"] == "failed" and "2 nodes" in result["error"]
    assert result["steps"][0]["status"] == "failed"
    assert result["lifecycle"][-1]["event"] == "stop"
    assert json.loads((out / "steps/persist/step.json").read_text()) == result["steps"][0]


def test_collector_failure_cannot_be_marked_captured(runtime):
    build, path, out, adb, plan = runtime
    plan["collectors"][0]["argv"] = ["{python}", "-c", "print('not JSON')"]
    write_json(path, plan)
    result = runner.run_android(build, path, out, adb=adb)
    assert result["status"] == "failed" and "collector" in result["error"]
    assert (out / "steps/cold/state.stdout").read_text().strip() == "not JSON"


def test_collector_timeout_keeps_output_and_cleanup(runtime):
    build, path, out, adb, plan = runtime
    plan["collectors"][0].update(argv=["{python}", "-u", "-c", "import time; print('started'); time.sleep(30)"], timeout_seconds=.2)
    write_json(path, plan)
    result = runner.run_android(build, path, out, adb=adb)
    assert result["status"] == "failed" and result["error_type"] == "TimeoutExpired"
    assert (out / "steps/cold/state.stdout").read_text().strip() == "started"
    assert json.loads((out / "steps/cold/state.command.json").read_text())["cleanup"]["leader_reaped"]


@pytest.mark.parametrize("corrupt", [PNG[:33], PNG[:-12], PNG[:45] + b"broken" + PNG[51:],
                                    PNG[:33] + png_chunk(b"IDAT", zlib.compress(b"short")) + PNG[-12:]])
def test_corrupt_screenshot_is_failed_and_never_saved_as_verified_png(runtime, monkeypatch, corrupt):
    build, path, out, adb, _ = runtime
    original = FakeDevice.run
    def captured(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if args[:2] == ("exec-out", "screencap"):
            result.stdout = corrupt
        return result
    monkeypatch.setattr(FakeDevice, "run", captured)
    result = runner.run_android(build, path, out, adb=adb)
    assert result["status"] == "failed" and "PNG" in result["error"]
    assert not (out / "steps/cold/screen.png").exists()
    assert (out / "steps/cold/step.json").exists()
    assert result["lifecycle"][-1]["event"] == "stop"


def test_nested_collector_report_is_hash_bound_and_startup_attempts_are_retained(runtime):
    build, path, out, adb, plan = runtime
    plan["collectors"][0]["argv"] = ["{python}", "-c",
        "import sys; from pathlib import Path; Path(sys.argv[1], 'report.json').write_text('{\"fresh\":true}'); print('{\"fresh\":true}')", "{capture}"]
    write_json(path, plan)
    result = runner.run_android(build, path, out, adb=adb)
    assert result["status"] == "captured", result
    for step in ("cold", "persist"):
        relative = f"steps/{step}/report.json"
        assert result["artifacts"][relative] == runner.file_hash(out / relative)
    assert list(out.glob("ready-001-*.command.json"))
    assert list(out.glob("ready-002-*.command.json"))


def test_device_lease_rejects_overlap_and_releases_on_error():
    serial = "emulator-5998"
    with pytest.raises(RuntimeError, match="fixture"):
        with runner.device_lease(serial):
            with pytest.raises(ValueError, match="already leased"):
                with runner.device_lease(serial):
                    pass
            raise RuntimeError("fixture")
    with runner.device_lease(serial):
        pass


@pytest.mark.parametrize("mutation", [
    lambda p: p["device"].update(apk_sha256="invalid"),
    lambda p: p["backend"].update(port=True),
    lambda p: p["backend"].update(timeout_seconds=float("inf")),
    lambda p: p["steps"][0].update(id="../outside"),
    lambda p: p["steps"][0].update(actions=[{"kind": "click", "attribute": [], "value": "x"}]),
    lambda p: p["steps"][0].update(actions=[{"kind": "wait", "seconds": -1}]),
])
def test_malformed_plan_rejected_before_mutation(runtime, mutation):
    build, path, out, adb, plan = runtime
    mutation(plan)
    write_json(path, plan)
    with pytest.raises(ValueError):
        runner.run_android(build, path, out, adb=adb)
    assert not out.exists()


def test_existing_output_is_never_reused(runtime):
    build, path, out, adb, _ = runtime
    out.mkdir()
    (out / "ui.xml").write_bytes(XML)
    with pytest.raises(ValueError, match="already exists"):
        runner.run_android(build, path, out, adb=adb)
    assert list(out.iterdir()) == [out / "ui.xml"]


def test_relative_components_cannot_put_output_inside_frozen_build(runtime):
    build, path, out, adb, _ = runtime
    sibling = build.parent / "scratch"
    sibling.mkdir()
    escaped = sibling / ".." / "build" / "capture"
    with pytest.raises(ValueError, match="separate"):
        runner.run_android(build, path, escaped, adb=adb)
    assert not (build / "capture").exists()
