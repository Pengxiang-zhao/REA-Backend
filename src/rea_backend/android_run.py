"""Replay explicit emulator steps and retain fresh, build-bound evidence.

This is a trusted-code development runner, not an Android agent, a sandbox or a
business oracle. It owns only the subprocesses it starts. AccountManager and
external storage are never implicitly cleared by an app-data reset.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
import zlib

from .android import AndroidDevice
from .build_validation import (_cleanup, _external_temp_base, _integrity, _json,
                               _now, _require, _snapshot, _write_files)
from .srs import file_hash

FORMAT = "rea-backend.android-run-plan/v1"
NOTE = ("Fresh device and collector evidence only; command assertions and semantic coverage remain "
        "the plan author's responsibility. App data, accounts, external files and backend storage "
        "are distinct state layers. Device leases coordinate this runner, not external adb users.")


def _save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_adb(explicit=None):
    candidates = [explicit] if explicit else [shutil.which("adb")]
    if not explicit:
        for variable in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
            if os.environ.get(variable):
                candidates.append(Path(os.environ[variable]) / "platform-tools/adb")
        candidates += [Path.home() / "Library/Android/sdk/platform-tools/adb",
                       Path.home() / "Android/Sdk/platform-tools/adb"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return Path(candidate).resolve()
    raise ValueError("adb not found; supply --adb or configure Android SDK/PATH")


@contextmanager
def device_lease(serial):
    """OS-released advisory lease; retain the inode so waiters cannot split locks."""
    import fcntl
    root = Path(tempfile.gettempdir()) / f"rea-backend-android-{os.getuid()}"
    root.mkdir(mode=0o700, exist_ok=True)
    _require(not root.is_symlink() and root.stat().st_uid == os.getuid(), "Unsafe device lease directory")
    name = hashlib.sha256(serial.encode()).hexdigest() + ".lock"
    fd = os.open(root / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(f"Emulator {serial} is already leased by another runner") from None
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps({"serial": serial, "pid": os.getpid(), "started_at": _now()}).encode())
        yield
    finally:
        os.close(fd)


def _fresh(out, build=None):
    out = Path(out).absolute()
    _require(not out.exists() and not out.is_symlink(), "Output already exists; choose a new directory")
    _require(not any(p.is_symlink() for p in out.parents), "Output cannot use symlink parents")
    out = out.resolve()
    if build:
        _require(not out.is_relative_to(build) and not build.is_relative_to(out), "Output and build must be separate")
    out.mkdir(parents=True)
    return out


def _doctor(device, out, expected=None):
    identity = device.identity()
    if expected:
        _require(identity["apk_sha256"] == expected, "Installed APK differs from the planned APK SHA-256")
    network = device.run("shell", "dumpsys", "connectivity", check=False)
    (out / "connectivity.txt").write_bytes(network.stdout)
    (out / "connectivity.stderr").write_bytes(network.stderr)
    version = subprocess.run([str(device.adb), "version"], capture_output=True, timeout=10)
    (out / "adb-version.txt").write_bytes(version.stdout + version.stderr)
    java = shutil.which("java")
    result = {"identity": identity, "adb": str(device.adb), "adb_sha256": file_hash(device.adb),
              "connectivity_command_exit_code": network.returncode,
              "validated_capability_observed": bool(re.search(rb"\bVALIDATED\b", network.stdout)),
              "network_note": "Diagnostic observation, not proof of active network validation or App connectivity.",
              "java": java, "python": sys.executable, "python_version": sys.version}
    if java:
        try:
            probe = subprocess.run([java, "-version"], capture_output=True, timeout=10)
            (out / "java-version.txt").write_bytes(probe.stdout + probe.stderr)
            result["java_exit_code"] = probe.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["java_error"] = str(exc)
    _save(out / "doctor.json", result)
    return result


def android_doctor(*, adb, serial, avd, package, activity, out, apk_sha256=None):
    device = AndroidDevice(find_adb(adb), serial, avd, package, activity)
    out = _fresh(out)
    result = {"format": "rea-backend.android-doctor/v1", "status": "failed", "note": NOTE}
    try:
        result.update(_doctor(device, out, apk_sha256), status="checked")
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        result["error"] = str(exc)
    _save(out / "report.json", result)
    return result


def _argv(value, label):
    _require(isinstance(value, list) and value and all(isinstance(a, str) and "\0" not in a for a in value)
             and value[0].strip(), f"{label}: explicit nonempty argv required")


def _seconds(value, label, maximum=60):
    _require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= maximum,
             f"{label}: positive duration at most {maximum} seconds required")


def _plan(raw):
    plan = _json(raw, "Android plan")
    fields = {"format", "purpose", "device", "initial_state", "backend", "collectors", "steps"}
    _require(isinstance(plan, dict) and set(plan) == fields and plan["format"] == FORMAT, "Invalid Android plan fields/format")
    for name in ("purpose", "initial_state"):
        _require(isinstance(plan[name], str) and plan[name].strip(), f"{name} is required")
    d = plan["device"]
    _require(isinstance(d, dict) and set(d) == {"serial", "avd", "package", "activity", "apk_sha256"}, "Invalid device fields")
    _require(all(isinstance(v, str) for v in d.values()), "Device fields must be strings")
    AndroidDevice(Path("adb"), d["serial"], d["avd"], d["package"], d["activity"])
    _require(bool(re.fullmatch(r"[0-9a-f]{64}", d["apk_sha256"])), "Expected APK SHA-256 required")
    b = plan["backend"]
    _require(isinstance(b, dict) and set(b) == {"argv", "ready_argv", "port", "timeout_seconds", "env"}, "Invalid backend fields")
    for name in ("argv", "ready_argv"):
        _argv(b[name], "backend." + name)
    _seconds(b["timeout_seconds"], "backend.timeout_seconds")
    _require(type(b["port"]) is int and 0 <= b["port"] <= 65535, "Backend port must be 0 (allocate) or a valid port")
    _require(isinstance(b["env"], dict) and all(isinstance(k, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k)
             and isinstance(v, str) and "\0" not in v for k, v in b["env"].items()), "Invalid backend environment")
    collectors = plan["collectors"]
    _require(isinstance(collectors, list), "collectors must be an array")
    ids = set()
    for c in collectors:
        _require(isinstance(c, dict) and set(c) == {"id", "kind", "argv", "timeout_seconds"}, "Invalid collector fields")
        _identifier(c["id"], ids)
        _require(isinstance(c["kind"], str) and c["kind"] in {"request", "storage", "diagnostic"}, "Unknown collector kind")
        _argv(c["argv"], "collector.argv")
        _seconds(c["timeout_seconds"], "collector.timeout_seconds")
    _require(isinstance(plan["steps"], list) and 1 <= len(plan["steps"]) <= 100, "Plan needs 1–100 steps")
    ids = set()
    for step in plan["steps"]:
        _require(isinstance(step, dict) and set(step) == {"id", "purpose", "actions", "ui_xml"}, "Invalid step fields")
        _identifier(step["id"], ids)
        _require(isinstance(step["purpose"], str) and step["purpose"].strip(), "Step purpose required")
        _require(isinstance(step["ui_xml"], str) and step["ui_xml"] in {"required", "optional", "skip"}, "Invalid ui_xml policy")
        _require(isinstance(step["actions"], list) and len(step["actions"]) <= 100, "Invalid actions")
        for action in step["actions"]:
            _action_check(action)
    return plan


def _identifier(value, seen):
    _require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value)
             and value.casefold() not in seen, "Duplicate or invalid identifier")
    seen.add(value.casefold())


def _action_check(a):
    _require(isinstance(a, dict) and isinstance(a.get("kind"), str), "Invalid action")
    simple = {"launch", "force_stop", "clear_app_data", "restart_backend"}
    fields = {"click": {"attribute", "value"}, "tap": {"x", "y"}, "text": {"value"},
              "key": {"code"}, "swipe": {"x1", "y1", "x2", "y2", "duration_ms"}, "wait": {"seconds"}}
    kind = a["kind"]
    _require(kind in simple | fields.keys(), f"Unknown action {kind}")
    _require(set(a) == {"kind"} | fields.get(kind, set()), f"Invalid fields for {kind}")
    if kind == "click":
        _require(isinstance(a["attribute"], str) and a["attribute"] in {"resource-id", "text", "content-desc"}
                 and isinstance(a["value"], str) and a["value"], "Invalid selector")
    elif kind == "text":
        _require(isinstance(a["value"], str) and a["value"] and all(32 <= ord(c) < 127 for c in a["value"]), "input text supports explicit ASCII only")
    elif kind == "wait":
        _seconds(a["seconds"], "wait.seconds", 15)
    elif kind == "key":
        _require(isinstance(a["code"], str) and re.fullmatch(r"(?:KEYCODE_[A-Z0-9_]+|[0-9]{1,3})", a["code"]), "Invalid key code")
    elif kind in {"tap", "swipe"}:
        _require(all(type(v) is int and 0 <= v <= 10000 for k, v in a.items() if k != "kind"), "Invalid coordinate/duration")


def _tree(device):
    remote = "/sdcard/rea-backend-" + uuid.uuid4().hex + ".xml"
    try:
        result = device.run("shell", "uiautomator", "dump", remote)
        _require(b"dumped to:" in result.stdout, "UI dump did not confirm success; previous XML is never reused")
        raw = device.run("exec-out", "cat", remote).stdout
        root = ET.fromstring(raw)
        _require(root.tag == "hierarchy" and bool(list(root.iter("node"))), "Invalid or empty UI hierarchy")
        return raw, root
    finally:
        device.run("shell", "rm", "-f", remote, check=False)


def _png(raw):
    """Reject truncated/corrupt capture bytes; this does not inspect UI content."""
    _require(isinstance(raw, bytes) and raw.startswith(b"\x89PNG\r\n\x1a\n"), "Screenshot is not PNG data")
    cursor, header, compressed, finished, palette = 8, None, bytearray(), False, False
    while cursor < len(raw):
        _require(cursor + 12 <= len(raw), "Screenshot has a truncated PNG chunk")
        length = int.from_bytes(raw[cursor:cursor + 4], "big")
        kind = raw[cursor + 4:cursor + 8]
        end = cursor + 12 + length
        _require(end <= len(raw), "Screenshot has a truncated PNG chunk")
        content = raw[cursor + 8:cursor + 8 + length]
        checksum = int.from_bytes(raw[end - 4:end], "big")
        _require(zlib.crc32(kind + content) == checksum, "Screenshot PNG checksum mismatch")
        if header is None:
            _require(kind == b"IHDR" and length == 13, "Screenshot PNG must start with IHDR")
            header = content
            _require(int.from_bytes(header[:4], "big") > 0 and int.from_bytes(header[4:8], "big") > 0,
                     "Screenshot PNG has invalid dimensions")
        elif kind == b"IHDR":
            raise ValueError("Screenshot PNG has duplicate IHDR")
        if kind == b"IDAT":
            compressed.extend(content)
        elif kind == b"PLTE":
            palette = length > 0 and length % 3 == 0
        elif kind == b"IEND":
            _require(length == 0 and end == len(raw), "Screenshot PNG has an invalid ending")
            finished = True
        cursor = end
    _require(finished and compressed, "Screenshot PNG is missing image data or its ending")
    width, height = int.from_bytes(header[:4], "big"), int.from_bytes(header[4:8], "big")
    depth, color, compression, filtering, interlace = header[8:]
    depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
    _require(depth in depths.get(color, ()) and compression == filtering == 0 and interlace in (0, 1),
             "Screenshot PNG has invalid image parameters")
    _require(color != 3 or palette, "Screenshot indexed PNG is missing a palette")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    passes = [(0, 0, 1, 1)] if interlace == 0 else [
        (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
        (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
    rows = []
    for x, y, dx, dy in passes:
        columns, count = max(0, (width - x + dx - 1) // dx), max(0, (height - y + dy - 1) // dy)
        if columns and count:
            rows.append((count, (columns * channels * depth + 7) // 8 + 1))
    expected = sum(count * size for count, size in rows)
    _require(expected <= 256 * 1024 * 1024, "Screenshot PNG image data is too large")
    try:
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(compressed, expected + 1)
        _require(len(decoded) == expected and decoder.eof and not decoder.unused_data,
                 "Screenshot PNG image data has an invalid length")
        offset = 0
        for count, size in rows:
            _require(all(decoded[offset + row * size] <= 4 for row in range(count)), "Screenshot PNG has an invalid row filter")
            offset += count * size
    except zlib.error as exc:
        raise ValueError("Screenshot PNG image data is corrupt") from exc


def _expand(argv, values):
    result = []
    for part in argv:
        for key, value in values.items():
            part = part.replace("{" + key + "}", str(value))
        result.append(part)
    return result


def _port(requested):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", requested))
        return sock.getsockname()[1]


def _command(argv, *, cwd, env, timeout, directory, label):
    """Keep diagnostics on timeout and clean up the command's owned process group."""
    process = None
    with (directory / (label + ".stdout")).open("wb") as stdout, (directory / (label + ".stderr")).open("wb") as stderr:
        try:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, start_new_session=True)
            process.wait(timeout=timeout)
        finally:
            if process:
                cleanup = _cleanup(process)
                _save(directory / (label + ".command.json"), {"argv": argv, "returncode": process.returncode, "cleanup": cleanup})
                _require(not cleanup["errors"], "Collector/readiness process cleanup failed")
    return subprocess.CompletedProcess(argv, process.returncode,
                                       (directory / (label + ".stdout")).read_bytes(),
                                       (directory / (label + ".stderr")).read_bytes())


def run_android(build, plan_path, out, *, adb=None):
    build = Path(build).absolute()
    _require(not any(p.is_symlink() for p in build.parents), "Build cannot use symlink parents")
    _require(not build.is_symlink(), "Build cannot be a symlink")
    build = build.resolve()
    manifest, data, hashes, modes = _snapshot(build)
    raw = Path(plan_path).read_bytes()
    plan = _plan(raw)
    device = AndroidDevice(find_adb(adb), **{k: plan["device"][k] for k in ("serial", "avd", "package", "activity")})
    out = _fresh(out, build)
    (out / "plan.json").write_bytes(raw)
    report = {"format": "rea-backend.android-run/v1", "status": "failed", "run_id": uuid.uuid4().hex,
              "started_at": _now(), "build_sha256": hashes["build.json"], "plan_sha256": file_hash(out / "plan.json"),
              "initial_state": plan["initial_state"], "steps": [], "lifecycle": [], "note": NOTE,
              "business_correctness": "not_assessed", "state_resets": [], "stage": "preflight"}
    process, reverse, temp, values = None, False, None, {}
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update(PYTHONDONTWRITEBYTECODE="1")

    def stop():
        nonlocal process
        if process is not None:
            cleanup = _cleanup(process)
            report["lifecycle"].append({"event": "stop", "at": _now(), "pid": process.pid, "cleanup": cleanup})
            process = None
            _require(not cleanup.get("errors"), "Owned backend cleanup failed")

    def start():
        nonlocal process
        argv = _expand(plan["backend"]["argv"], values)
        with (out / "server.log").open("ab") as log:
            process = subprocess.Popen(argv, cwd=values["build"], env=env, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        report["lifecycle"].append({"event": "start", "at": _now(), "pid": process.pid, "argv": argv})
        deadline = time.monotonic() + plan["backend"]["timeout_seconds"]
        startup = sum(event["event"] == "start" for event in report["lifecycle"])
        attempt = 0
        while time.monotonic() < deadline:
            _require(process.poll() is None, "Owned backend exited during startup; see server.log")
            attempt += 1
            try:
                result = _command(_expand(plan["backend"]["ready_argv"], values), cwd=values["build"], env=env,
                                  timeout=min(5, max(.01, deadline - time.monotonic())), directory=out,
                                  label=f"ready-{startup:03}-{attempt:03}")
                if result.returncode == 0:
                    _require(process.poll() is None, "Backend exited while readiness was checked")
                    return
            except subprocess.TimeoutExpired:
                pass
            time.sleep(.1)
        raise RuntimeError("Backend readiness timed out")

    try:
        with device_lease(device.serial):
            try:
                report["doctor"] = _doctor(device, out, plan["device"]["apk_sha256"])
                temp = tempfile.TemporaryDirectory(prefix="rea-backend-android-", dir=_external_temp_base(build, out))
                copied = Path(temp.name) / "build"
                _write_files(copied, data, modes)
                _write_files(out / "build-source", data, modes)
                runtime = out / "runtime"
                runtime.mkdir()
                port = _port(plan["backend"]["port"])
                values.update(build=copied, run=runtime, python=sys.executable, port=port)
                env.update({k: _expand([v], values)[0] for k, v in plan["backend"]["env"].items()})
                env.pop("PYTHONPATH", None)
                env.pop("PYTHONHOME", None)
                env["PYTHONDONTWRITEBYTECODE"] = "1"
                report.update(port=port, stage="backend_start")
                start()
                device.run("reverse", "--no-rebind", f"tcp:{port}", f"tcp:{port}")
                reverse = True
                for step in plan["steps"]:
                    report["stage"] = "step:" + step["id"]
                    folder = out / "steps" / step["id"]
                    folder.mkdir(parents=True)
                    entry = {"id": step["id"], "started_at": _now(), "status": "failed", "actions": [], "collectors": []}
                    report["steps"].append(entry)
                    for action in step["actions"]:
                        entry["actions"].append({"action": action, "at": _now()})
                        kind = action["kind"]
                        if kind == "restart_backend":
                            stop()
                            start()
                        elif kind == "launch":
                            result = device.run("shell", "am", "start", "-W", "-n", device.activity)
                            _require(not re.search(rb"(?:Error|Exception|Status:\s*(?!ok)\w+)", result.stdout + result.stderr), "Activity launch failed")
                        elif kind == "force_stop":
                            device.force_stop()
                        elif kind == "clear_app_data":
                            result = device.run("shell", "pm", "clear", device.package)
                            _require(result.stdout.strip() == b"Success", "App data clear failed")
                            report["state_resets"].append({"at": _now(), "step_id": step["id"], "app_data": "cleared",
                                                          "accounts": "not_reset", "external_storage": "not_verified", "backend": "not_reset"})
                        elif kind == "wait":
                            time.sleep(action["seconds"])
                        elif kind == "click":
                            _, root = _tree(device)
                            nodes = [n for n in root.iter("node") if n.get(action["attribute"]) == action["value"]]
                            _require(len(nodes) == 1, f"UI selector matched {len(nodes)} nodes; expected exactly one")
                            bounds = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", nodes[0].get("bounds", ""))
                            _require(bounds is not None, "UI node has invalid bounds")
                            x1, y1, x2, y2 = map(int, bounds.groups())
                            _require(x2 > x1 and y2 > y1, "UI node has empty bounds")
                            device.run("shell", "input", "tap", (x1 + x2) // 2, (y1 + y2) // 2)
                        elif kind == "text":
                            device.run("shell", "input", "text", shlex.quote(action["value"].replace(" ", "%s")))
                        elif kind == "key":
                            device.run("shell", "input", "keyevent", action["code"])
                        elif kind == "tap":
                            device.run("shell", "input", "tap", action["x"], action["y"])
                        elif kind == "swipe":
                            device.run("shell", "input", "swipe", *(action[k] for k in ("x1", "y1", "x2", "y2", "duration_ms")))
                    png = device.run("exec-out", "screencap", "-p").stdout
                    _png(png)
                    (folder / "screen.png").write_bytes(png)
                    if step["ui_xml"] != "skip":
                        try:
                            xml, _ = _tree(device)
                            (folder / "ui.xml").write_bytes(xml)
                            entry["ui_xml"] = "captured"
                        except (ValueError, OSError, subprocess.SubprocessError, ET.ParseError) as exc:
                            entry["ui_xml"] = "unavailable"
                            entry["ui_error"] = str(exc)
                            if step["ui_xml"] == "required":
                                raise
                    else:
                        entry["ui_xml"] = "skipped"
                    for collector in plan["collectors"]:
                        result = _command(_expand(collector["argv"], {**values, "capture": folder}), cwd=copied, env=env,
                                          timeout=collector["timeout_seconds"], directory=folder, label=collector["id"])
                        entry["collectors"].append({"id": collector["id"], "kind": collector["kind"], "exit_code": result.returncode})
                        _require(result.returncode == 0 and bool(result.stdout.strip()), "Collector failed or returned no evidence: " + collector["id"])
                        _json(result.stdout, "collector " + collector["id"])
                    _require(process.poll() is None, "Backend exited during client actions")
                    check = _integrity(copied, hashes)
                    _require(check["status"] == "passed", "Build copy changed during Android run")
                    entry.update(status="captured", finished_at=_now())
                    _save(folder / "step.json", entry)
                after = device.identity()
                device._same_identity(report["doctor"]["identity"], after)
                report.update(status="captured", stage="complete")
            finally:
                try:
                    stop()
                finally:
                    if reverse:
                        device.run("reverse", "--remove", f"tcp:{values['port']}")
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError, ET.ParseError) as exc:
        report.update(status="failed", error=str(exc), error_type=type(exc).__name__)
        if report["steps"] and report["steps"][-1]["status"] == "failed":
            entry = report["steps"][-1]
            entry.update(finished_at=_now(), error=str(exc), error_type=type(exc).__name__)
            _save(out / "steps" / entry["id"] / "step.json", entry)
    finally:
        report["integrity"] = {"original": _integrity(build, hashes)}
        if values:
            report["integrity"]["executed_copy"] = _integrity(values["build"], hashes)
            report["integrity"]["retained_copy"] = _integrity(out / "build-source", hashes)
        if any(r["status"] != "passed" for r in report["integrity"].values()):
            report["status"] = "failed"
        if temp:
            temp.cleanup()
        report["finished_at"] = _now()
        report["artifacts"] = {p.relative_to(out).as_posix(): file_hash(p) for p in sorted(out.rglob("*"))
                               if p.is_file() and not p.is_symlink() and p != out / "report.json"}
        _save(out / "report.json", report)
    return report
