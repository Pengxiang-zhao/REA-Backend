"""Opt-in execution of an explicit test plan against a frozen build copy.

This is an arbitrary-code runner, not a security or network sandbox. A zero exit
code records the test author's assertion outcome, not semantic correctness,
requirement coverage, Android compatibility, or upstream-service equivalence.
Only manifest-bound source bytes are copied as the tested build. Test authors
may deliberately retain additional regular files through ``{artifacts}``.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

from . import validation_contracts


PLAN_FORMAT = "rea-backend.build-validation-plan/v1"
REPORT_FORMAT = "rea-backend.build-validation/v1"
PLAN_FORMAT_V2 = validation_contracts.PLAN_V2
REPORT_FORMAT_V2 = validation_contracts.REPORT_V2
MAX_TIMEOUT_SECONDS = 600
MAX_CASES = 100
SCOPE = ("Agent-authored subprocess checks only. A zero exit code does not establish "
         "semantic correctness, requirement coverage, Android compatibility, or reference-service equivalence. "
         "This runner is not a security or network sandbox.")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(data, label):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, f"Duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"Non-finite JSON number in {label}: {value}")

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON in {label}: {exc}") from exc


def _relative(value):
    _require(isinstance(value, str) and value, "Build file paths must be nonempty strings")
    path = PurePosixPath(value)
    _require(not path.is_absolute() and not PureWindowsPath(value).drive and "\\" not in value
             and ".." not in path.parts and str(path) == value and value != "." and "\0" not in value,
             f"Build file path must be canonical and relative: {value!r}")
    return value


def _read_regular(root, name):
    """Read regular bytes without following a symlink at any build component."""
    parts = PurePosixPath(_relative(name)).parts
    if os.name == "posix":
        descriptors = []
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            descriptors.append(os.open(root, flags))
            for part in parts[:-1]:
                descriptors.append(os.open(part, flags, dir_fd=descriptors[-1]))
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptors[-1])
            with os.fdopen(fd, "rb") as stream:
                _require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), f"Not a regular file: {name}")
                return stream.read()
        finally:
            for fd in reversed(descriptors):
                os.close(fd)
    target = root
    for part in parts:
        target = target / part
        _require(not target.is_symlink(), f"Symlink is not supported: {name}")
    _require(stat.S_ISREG(target.stat().st_mode), f"Not a regular file: {name}")
    return target.read_bytes()


def _inventory(root):
    _require(root.is_dir() and not root.is_symlink(), f"Expected a real directory: {root}")
    files, directories = set(), set()

    def visit(directory):
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                name = path.relative_to(root).as_posix()
                _require(not entry.is_symlink(), f"Symlink is not supported: {name}")
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISDIR(mode):
                    directories.add(name)
                    visit(path)
                else:
                    _require(stat.S_ISREG(mode), f"Not a regular file: {name}")
                    files.add(name)
    visit(root)
    return files, directories


def _integrity(root, hashes):
    errors, actual = [], {}
    try:
        names, directories = _inventory(root)
        allowed_dirs = {str(parent) for name in hashes for parent in PurePosixPath(name).parents
                        if str(parent) != "."}
        if names != set(hashes):
            errors.append({"missing": sorted(set(hashes) - names), "undeclared": sorted(names - set(hashes))})
        if directories - allowed_dirs:
            errors.append({"undeclared_directories": sorted(directories - allowed_dirs)})
        for name in sorted(names & set(hashes)):
            actual[name] = _sha(_read_regular(root, name))
            if actual[name] != hashes[name]:
                errors.append({"path": name, "expected_sha256": hashes[name], "actual_sha256": actual[name]})
    except (OSError, ValueError) as exc:
        errors.append({"error": str(exc)})
    return {"status": "passed" if not errors else "failed", "hashes": actual, "errors": errors}


def _snapshot(build):
    raw = _read_regular(build, "build.json")
    manifest = _json(raw, "build.json")
    _require(isinstance(manifest, dict) and isinstance(manifest.get("format"), str) and manifest["format"] in
             {"rea-backend.srs-build/v1", "rea-backend.srs-build/v2"}, "Expected an srs-build v1/v2 manifest")
    files = manifest.get("files")
    _require(isinstance(files, dict) and files, "Build manifest files must be a nonempty hash map")
    for name, digest in files.items():
        _relative(name)
        _require(name != "build.json" and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest),
                 f"Invalid or self-referential build hash: {name}")
    _require(isinstance(manifest.get("entrypoint"), str) and manifest["entrypoint"] in files,
             "Build entrypoint must be a hash-bound file")
    hashes = {**files, "build.json": _sha(raw)}
    check = _integrity(build, hashes)
    _require(check["status"] == "passed", "Build integrity check failed: " + json.dumps(check["errors"]))
    data = {name: _read_regular(build, name) for name in sorted(hashes)}
    _require(all(_sha(data[name]) == digest for name, digest in hashes.items()), "Build changed while reading source bytes")
    modes = {name: (build / name).stat(follow_symlinks=False).st_mode & 0o111 for name in hashes}
    return manifest, data, hashes, modes


def _plan(raw, data):
    plan = _json(raw, "validation plan")
    _require(isinstance(plan, dict), "Invalid validation plan fields")
    version2 = plan.get("format") == PLAN_FORMAT_V2
    fields = {"format", "purpose", "cases"} | ({"phase", "scope", "obligations"} if version2 else set())
    if version2 and plan.get("phase") == "final":
        fields.add("early_client")
    _require(set(plan) == fields, "Invalid validation plan fields")
    _require(plan["format"] in (PLAN_FORMAT, PLAN_FORMAT_V2), f"Expected plan format {PLAN_FORMAT} or {PLAN_FORMAT_V2}")
    _require(isinstance(plan["purpose"], str) and plan["purpose"].strip(), "Plan purpose is required")
    cases = plan["cases"]
    _require(isinstance(cases, list) and 1 <= len(cases) <= MAX_CASES, f"Plan requires 1–{MAX_CASES} cases")
    ids, linked = set(), set()
    for case in cases:
        required = {"id", "purpose", "argv", "timeout_seconds"}
        optional = {"requirement_ids"}
        if version2:
            required |= {"requirement_ids", "workflow_ids", "obligation_ids", "check_kind", "required_artifacts"}
            optional = {"model_limitations", "failure_artifact"}
        _require(isinstance(case, dict) and required <= set(case) <= required | optional, "Invalid validation case fields")
        cid = case["id"]
        _require(isinstance(cid, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", cid) and cid.casefold() not in ids,
                 "Case id must be unique and contain only letters, digits, underscores or hyphens")
        ids.add(cid.casefold())
        _require(isinstance(case["purpose"], str) and case["purpose"].strip(), f"Case purpose is required: {cid}")
        argv = case["argv"]
        _require(isinstance(argv, list) and argv and all(isinstance(a, str) and "\0" not in a for a in argv)
                 and argv[0].strip(), f"Case argv must be an explicit nonempty string array: {cid}")
        timeout = case["timeout_seconds"]
        _require(type(timeout) in (int, float) and 0 < timeout <= MAX_TIMEOUT_SECONDS and math.isfinite(timeout),
                 f"Case timeout_seconds must be positive and at most {MAX_TIMEOUT_SECONDS}: {cid}")
        refs = case.get("requirement_ids", [])
        _require(isinstance(refs, list) and all(isinstance(r, str) and r for r in refs)
                 and len(refs) == len(set(refs)), f"Invalid requirement_ids: {cid}")
        linked.update(refs)
    if linked or version2:
        _require("srs/index.json" in data, "Requirement links need a hash-bound srs/index.json")
        index = _json(data["srs/index.json"], "srs/index.json")
        rows = index.get("requirements") if isinstance(index, dict) else None
        _require(isinstance(rows, list) and all(isinstance(row, dict) and isinstance(row.get("id"), str)
                                               for row in rows), "Invalid requirement index")
        known = [row["id"] for row in rows]
        _require(len(known) == len(set(known)) and linked <= set(known), "Unknown or ambiguous requirement_ids")
    if version2:
        validation_contracts.validate_plan(plan, data, _json)
        if plan["phase"] == "final":
            early = plan["early_client"]
            _require(isinstance(early, dict) and set(early) == {"path", "sha256"}, "Invalid early_client binding")
            _relative(early["path"])
            _require(isinstance(early["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", early["sha256"]),
                     "Invalid early_client report hash")
    return plan


def _early_gate(plan, plan_parent, data, hashes):
    """Copy and recheck the early run's explicit assertions and retained evidence."""
    if plan.get("phase") != "final" or plan["format"] != PLAN_FORMAT_V2:
        return {}, None
    binding = plan["early_client"]
    raw = _read_regular(plan_parent, binding["path"])
    _require(_sha(raw) == binding["sha256"], "early_client report hash mismatch")
    report = _json(raw, "early_client report")
    _require(isinstance(report, dict) and report.get("format") == REPORT_FORMAT_V2
             and report.get("phase") == "early_client" and report.get("status") == "passed",
             "Final validation requires a successful v2 early_client report")
    _require(report.get("errors") == [] and report.get("failures") == [], "early_client report retains failures")
    root = plan_parent / PurePosixPath(binding["path"]).parent
    saved = {"report.json": raw}
    _, early_data, early_hashes, _ = _snapshot(root / "build")
    _require(report.get("start_hashes") == early_hashes, "early_client build snapshot differs from its report")
    saved.update({"build/" + name: content for name, content in early_data.items()})
    frozen = _read_regular(root, "plan.json")
    _require(_sha(frozen) == report.get("plan_sha256"), "early_client frozen plan hash mismatch")
    prior = _plan(frozen, early_data)
    _require(prior.get("phase") == "early_client", "early_client report must bind an early_client plan")
    _require(report.get("validation_scope") == prior["scope"] and report.get("obligations") == prior["obligations"],
             "early_client report scope differs from its frozen plan")
    _require(set(prior["scope"]["workflow_ids"]) <= set(plan["scope"]["workflow_ids"]),
             "early_client workflows are outside final validation scope")
    _require(set(prior["scope"]["requirement_ids"]) <= set(plan["scope"]["requirement_ids"]),
             "early_client requirements are outside final validation scope")
    saved["plan.json"] = frozen
    prior_srs = {name: digest for name, digest in early_hashes.items() if name.startswith("srs/")}
    current_srs = {name: digest for name, digest in hashes.items() if name.startswith("srs/")}
    changed_srs = sorted(name for name in prior_srs.keys() | current_srs.keys()
                         if prior_srs.get(name) != current_srs.get(name))
    _require(not changed_srs,
             f"early_client uses another frozen SRS baseline: {changed_srs}; rerun the early phase")
    integrity = report.get("final_integrity")
    _require(isinstance(integrity, dict) and set(integrity) == {"source", "execution_copy", "packaged_snapshot"}
             and all(isinstance(value, dict) and value.get("status") == "passed" for value in integrity.values()),
             "early_client report has no passing integrity checks")
    cases = report.get("cases")
    _require(isinstance(cases, list) and len(cases) == len(prior["cases"]), "Invalid early_client case results")
    for case, result in zip(prior["cases"], cases):
        _require(isinstance(result, dict) and result.get("id") == case["id"] and result.get("status") == "passed"
                 and result.get("process_exit_zero") is True and result.get("timed_out") is False
                 and result.get("returncode") == 0, "early_client has an unsuccessful case")
        _require(not any(key in result for key in ("launch_error", "artifact_error", "cleanup_error", "integrity_failure", "failure")),
                 "early_client case retains a failure")
        for field in ("check_kind", "requirement_ids", "workflow_ids", "obligation_ids"):
            _require(result.get(field) == case[field], f"early_client case differs from its frozen plan: {case['id']}/{field}")
        artifacts = result.get("artifacts")
        _require(isinstance(artifacts, dict), "early_client artifact manifest is missing")
        _require(case.get("failure_artifact") not in artifacts, "early_client retains a failure attribution artifact")
        for expected in case["required_artifacts"]:
            path = expected["path"]
            metadata = artifacts.get(path)
            _require(isinstance(metadata, dict) and type(metadata.get("bytes")) is int and metadata["bytes"] > 0
                     and type(metadata.get("mtime_ns")) is int
                     and type(result.get("evidence_boundary_mtime_ns")) is int
                     and metadata["mtime_ns"] >= result["evidence_boundary_mtime_ns"],
                     f"early_client lacks fresh required evidence: {case['id']}/{path}")
        for path, metadata in artifacts.items():
            _relative(path)
            _require(isinstance(metadata, dict), "Invalid early_client artifact metadata")
            relative = f"cases/{case['id']}/artifacts/{path}"
            content = _read_regular(root, relative)
            _require(_sha(content) == metadata.get("sha256") and len(content) == metadata.get("bytes"),
                     f"early_client artifact hash mismatch: {relative}")
            saved[relative] = content
        for stream in ("stdout", "stderr"):
            metadata = result.get(stream)
            relative = f"cases/{case['id']}/{stream}.txt"
            _require(isinstance(metadata, dict) and metadata.get("path") == relative,
                     f"Invalid early_client {stream} metadata")
            content = _read_regular(root, relative)
            _require(_sha(content) == metadata.get("sha256") and len(content) == metadata.get("bytes"),
                     f"early_client {stream} hash mismatch: {case['id']}")
            saved[relative] = content
    return saved, {"status": "passed", "report_sha256": _sha(raw), "snapshot": "early_client/report.json",
                   "run_id": report.get("run_id"), "workflow_ids": prior["scope"]["workflow_ids"],
                   "requirement_ids": prior["scope"]["requirement_ids"],
                   "scope": "Verified prior runner assertions and retained file hashes; not an independent semantic verdict."}


def _write_files(root, data, modes=None):
    root.mkdir()
    for name, content in data.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
        if modes is not None:
            path.chmod(0o600 | modes[name])


def _external_temp_base(build, out):
    repositories = set()
    for path in (build, Path.cwd().resolve(), Path(__file__).resolve()):
        for parent in (path, *path.parents):
            if (parent / ".git").exists():
                repositories.add(parent)
                break
    candidates = [Path(tempfile.gettempdir()).resolve()]
    if os.name == "posix":
        candidates.append(Path("/tmp").resolve())
    for candidate in candidates:
        if candidate.is_dir() and not any(candidate == p or candidate.is_relative_to(p)
                                          for p in repositories | {build, out}):
            return candidate
    raise ValueError("No temporary directory outside the source repository is available")


def _cleanup(process):
    """Best-effort group cleanup, followed by bounded leader cleanup and reaping."""
    result = {"strategy": "POSIX process group TERM/KILL" if os.name == "posix" else "child terminate/kill",
              "sigterm_sent": False, "sigkill_sent": False, "leader_fallback": False,
              "leader_sigterm_sent": False, "leader_sigkill_sent": False,
              "process_group_signals": "unsupported", "errors": []}

    def error(operation, exc):
        result["errors"].append({"operation": operation, "error": str(exc)})

    def wait(timeout, final=False):
        try:
            process.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired as exc:
            if final:
                error("wait for leader", exc)
        except OSError as exc:
            error("wait for leader", exc)
        return False

    if os.name == "posix":
        def send(sig):
            try:
                os.killpg(process.pid, sig)
                return True
            except ProcessLookupError:
                return False
            except OSError as exc:
                error(f"process group {sig.name}", exc)
                return False
        result["sigterm_sent"] = send(signal.SIGTERM)
        if result["sigterm_sent"]:
            # The leader may already have exited while its child still ignores TERM.
            time.sleep(0.1)
        # Reap an exited leader before signalling again: macOS can return EPERM
        # when only the unreaped leader remains in the process group.
        try:
            process.poll()
        except OSError as exc:
            error("poll leader", exc)
        if result["sigterm_sent"] or result["errors"]:
            result["sigkill_sent"] = send(signal.SIGKILL)
        result["process_group_signals"] = "failed" if result["errors"] else "completed"

    if not wait(0.1):
        result["leader_fallback"] = True
        try:
            process.terminate()
            result["leader_sigterm_sent"] = True
        except ProcessLookupError:
            pass
        except OSError as exc:
            error("leader terminate", exc)
        if not wait(0.1):
            try:
                process.kill()
                result["leader_sigkill_sent"] = True
            except ProcessLookupError:
                pass
            except OSError as exc:
                error("leader kill", exc)
            wait(5, final=True)
    result["leader_reaped"] = process.returncode is not None
    return result


def _execute(case, workspace, out, execution_build):
    directory = workspace / "cases" / case["id"]
    cwd, artifacts = directory / "work", directory / "artifacts"
    cwd.mkdir(parents=True)
    artifacts.mkdir()
    # A marker on this filesystem avoids assuming nanosecond timestamp resolution.
    # The private empty directory establishes a fresh destination; retained mtime
    # checks additionally reject copies which preserve old recording timestamps.
    marker = artifacts / ".capture-boundary"
    marker.touch()
    evidence_boundary = marker.stat().st_mtime_ns
    marker.unlink()
    destination = out / "cases" / case["id"]
    destination.mkdir(parents=True)
    substitutions = {"{python}": sys.executable, "{build}": str(execution_build), "{artifacts}": str(artifacts)}
    argv = []
    for argument in case["argv"]:
        for token, replacement in substitutions.items():
            argument = argument.replace(token, replacement)
        argv.append(argument)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update(PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(cwd), TMP=str(cwd), TEMP=str(cwd))
    record = {"id": case["id"], "purpose": case["purpose"], "requirement_ids": case.get("requirement_ids", []),
              "argv": argv, "cwd_historical_temporary_path": str(cwd), "timeout_seconds": case["timeout_seconds"],
              "started_at_utc": _now(), "returncode": None, "timed_out": False, "status": "failed"}
    version2 = "check_kind" in case
    if version2:
        record.update({key: case[key] for key in ("workflow_ids", "obligation_ids", "check_kind")})
        record["evidence_boundary_mtime_ns"] = evidence_boundary
        if "model_limitations" in case:
            record["model_limitations"] = case["model_limitations"]
    process, began = None, time.monotonic()
    with (destination / "stdout.txt").open("xb") as stdout, (destination / "stderr.txt").open("xb") as stderr:
        try:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, shell=False, start_new_session=os.name == "posix")
            try:
                process.wait(timeout=case["timeout_seconds"])
            except subprocess.TimeoutExpired:
                record["timed_out"] = True
        except (OSError, ValueError) as exc:
            record["launch_error"] = str(exc)
        finally:
            if process is not None:
                try:
                    record["cleanup"] = _cleanup(process)
                    if record["cleanup"]["errors"]:
                        record["cleanup_error"] = "; ".join(
                            f"{item['operation']}: {item['error']}" for item in record["cleanup"]["errors"])
                except (OSError, subprocess.TimeoutExpired) as exc:
                    record["cleanup_error"] = str(exc)
                record["returncode"] = process.returncode
    record.update(finished_at_utc=_now(), duration_seconds=round(time.monotonic() - began, 6))
    for name in ("stdout", "stderr"):
        path = destination / f"{name}.txt"
        record[name] = {"path": path.relative_to(out).as_posix(), "sha256": _sha(path.read_bytes()), "bytes": path.stat().st_size}
    record["process_exit_zero"] = record["returncode"] == 0 and not record["timed_out"]
    saved = {}
    try:
        names, _ = _inventory(artifacts)
        saved = {name: _read_regular(artifacts, name) for name in sorted(names)}
        mtimes = {name: (artifacts / name).stat(follow_symlinks=False).st_mtime_ns for name in saved}
        _write_files(destination / "artifacts", saved)
        record["artifacts"] = {name: {"sha256": _sha(content), "bytes": len(content),
                                      **({"mtime_ns": mtimes[name]} if version2 else {})}
                               for name, content in saved.items()}
    except (OSError, ValueError) as exc:
        record["artifact_error"] = str(exc)
    if record["process_exit_zero"] and not any(key in record for key in ("launch_error", "artifact_error", "cleanup_error")):
        record["status"] = "passed"
    if version2:
        record["evidence_checks"] = validation_contracts.evidence_checks(
            case, record.get("artifacts", {}), evidence_boundary)
        if any(check["status"] != "passed" for check in record["evidence_checks"]) or case.get("failure_artifact") in saved:
            record["status"] = "failed"
        if record["status"] == "failed":
            record["failure"] = validation_contracts.failure_record(case, record, saved, _json)
    return record


def validate_build(build: Path, plan: Path, out: Path) -> dict:
    """Validate inputs, run a frozen plan, and return the persisted result report.

    Invalid inputs raise ValueError before creating output or launching a process.
    Runtime failures return status=failed with evidence in a fresh output folder.
    v1 preserves exit-code checks. v2 additionally binds selected workflow risks
    and mandatory evidence, distinguishes client/consumer/model checks, and
    requires a same-SRS early-client report before final validation. Neither
    mode establishes semantic correctness by itself.
    """
    build, plan, out = (Path(p) for p in (build, plan, out))
    _require(not any(p.is_symlink() for p in (build, plan, out)), "Symlink input/output paths are not supported")
    build, plan, out = (p.resolve() for p in (build, plan, out))
    _require(not out.exists(), "Output already exists; choose a fresh output directory")
    _require(not out.is_relative_to(build), "Output must not be inside the build")
    ancestor = out.parent
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    _require(ancestor.is_dir(), "Output parent must be a directory")
    try:
        manifest, data, hashes, modes = _snapshot(build)
        plan_bytes = _read_regular(plan.parent, plan.name)
        frozen_plan = _plan(plan_bytes, data)
        early_files, early_gate = _early_gate(frozen_plan, plan.parent, data, hashes)
    except OSError as exc:
        raise ValueError(f"Cannot read build or plan: {exc}") from exc
    temporary_base = _external_temp_base(build, out)
    version2 = frozen_plan["format"] == PLAN_FORMAT_V2
    report = {"format": REPORT_FORMAT_V2 if version2 else REPORT_FORMAT, "run_id": uuid.uuid4().hex, "status": "running", "started_at_utc": _now(),
              "purpose": frozen_plan["purpose"], "source_build": str(build), "source_plan": str(plan), "output": str(out),
              "build_format": manifest["format"], "build_manifest_sha256": hashes["build.json"],
              "plan_sha256": _sha(plan_bytes), "start_hashes": hashes, "python_executable": sys.executable,
              "scope": SCOPE, "source_snapshot": "build", "plan_snapshot": "plan.json", "errors": [],
              "cases": [{"id": case["id"], "status": "not_run", "reason": "not reached"} for case in frozen_plan["cases"]],
              "retention": "Only bound source bytes, the exact plan, stdout/stderr and explicitly written regular artifact files are packaged; working directories are removed.",
              "process_cleanup_boundary": "POSIX cases start a new session and the runner attempts to terminate their process group after every case, with bounded leader cleanup as a fallback. Cleanup failure is recorded and stops later cases. Deliberately detached processes are outside this mechanism; this is not a sandbox."}
    if version2:
        report.update(phase=frozen_plan["phase"], validation_scope=frozen_plan["scope"],
                      obligations=frozen_plan["obligations"], failures=[],
                      early_client_gate=early_gate or {"status": "this_run", "final_validation_still_required": True},
                      evidence_boundary="Required evidence must be nonempty regular files in a fresh case directory with filesystem mtime at or after the case boundary. Labels and file freshness do not independently prove recording time, UI success, business correctness or storage provenance.")
    out.mkdir(parents=True, exist_ok=False)
    _write_files(out / "build", data, modes)
    (out / "plan.json").write_bytes(plan_bytes)
    if early_files:
        _write_files(out / "early_client", early_files)

    def save():
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="rea-backend-build-validation-", dir=temporary_base) as temporary:
        workspace = Path(temporary).resolve()
        execution_build = workspace / "build"
        _write_files(execution_build, data, modes)
        report["execution_build_historical_temporary_path"] = str(execution_build)

        def checks():
            return {"source": _integrity(build, hashes), "execution_copy": _integrity(execution_build, hashes),
                    "packaged_snapshot": _integrity(out / "build", hashes)}

        def intact(value):
            return all(check["status"] == "passed" for check in value.values())

        save()
        try:
            for index, case in enumerate(frozen_plan["cases"]):
                before = checks()
                if not intact(before):
                    report["errors"].append({"kind": "integrity_before_case", "case_id": case["id"], "checks": before})
                    break
                report["cases"][index] = {"id": case["id"], "purpose": case["purpose"], "status": "running",
                                          "started_at_utc": _now(), "integrity_before": before}
                save()
                record = _execute(case, workspace, out, execution_build)
                record["integrity_before"] = before
                record["integrity_after"] = checks()
                report["cases"][index] = record
                if not intact(record["integrity_after"]):
                    record["status"] = "failed"
                    record["integrity_failure"] = True
                    report["errors"].append({"kind": "integrity_after_case", "case_id": case["id"]})
                    break
                if "cleanup_error" in record:
                    report["errors"].append({"kind": "cleanup_failure", "case_id": case["id"],
                                             "error": record["cleanup_error"]})
                    break
                save()
        except Exception as exc:
            report["errors"].append({"kind": "runner_error", "error": str(exc)})
        finally:
            report["final_integrity"] = checks()
            report["status"] = ("passed" if not report["errors"] and intact(report["final_integrity"])
                                and all(case["status"] == "passed" for case in report["cases"]) else "failed")
            for case in report["cases"]:
                if case["status"] == "running":
                    case.update(status="failed", error="Execution interrupted before its final result was recorded")
                    for name in ("stdout", "stderr"):
                        path = out / "cases" / case["id"] / f"{name}.txt"
                        if path.is_file() and not path.is_symlink():
                            case[name] = {"path": path.relative_to(out).as_posix(), "sha256": _sha(path.read_bytes()),
                                          "bytes": path.stat().st_size}
                if case["status"] == "not_run":
                    case["reason"] = "validation stopped before this case; see errors and integrity checks"
            if version2:
                planned = {case["id"]: case for case in frozen_plan["cases"]}
                for case in report["cases"]:
                    if case["status"] == "failed" and "failure" not in case:
                        case["failure"] = validation_contracts.failure_record(planned[case["id"]], case, {}, _json)
                report["failures"] = [case["failure"] for case in report["cases"] if "failure" in case]
                report["coverage"] = {
                    "status": "passed" if report["status"] == "passed" else "incomplete",
                    "planned_workflow_ids": frozen_plan["scope"]["workflow_ids"],
                    "planned_requirement_ids": frozen_plan["scope"]["requirement_ids"],
                    "passed_case_ids": [case["id"] for case in report["cases"] if case["status"] == "passed"],
                    "not_run_case_ids": [case["id"] for case in report["cases"] if case["status"] == "not_run"],
                    "model_case_ids": [case["id"] for case in frozen_plan["cases"] if case["check_kind"] == "model"],
                    "note": "Coverage is of declared scoped checks only; passing does not prove discovery completeness or independent acceptance."}
            report["finished_at_utc"] = _now()
            save()
    return report
