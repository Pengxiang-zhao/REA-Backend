"""The opt-in runner preserves evidence and cannot silently test another build."""
import hashlib
import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from rea_backend import build_validation
from rea_backend.build_validation import PLAN_FORMAT, PLAN_FORMAT_V2, validate_build
from test_srs import materials


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value) + "\n")


def make_build(tmp_path, script="print('assertions completed')\n", version=2):
    root = tmp_path.resolve()
    build = root / "source-repository" / "build"
    build.mkdir(parents=True)
    (build.parent / ".git").mkdir()
    files = {
        "implementation/check.py": script,
        "implementation/helper.txt": "immutable fixture\n",
        "implementation/requirements.txt": "# standard library only\n",
        "srs/index.json": json.dumps({"requirements": [{"id": "FR-001"}]}),
    }
    for name, text in files.items():
        target = build / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    write_json(build / "build.json", {
        "format": f"rea-backend.srs-build/v{version}", "app_id": "fixture", "route": "source",
        "entrypoint": "implementation/check.py", "files": {name: digest(build / name) for name in files},
    })
    plan = root / "plan.json"
    write_json(plan, {"format": PLAN_FORMAT, "purpose": "Exercise the frozen synthetic build.", "cases": [
        {"id": "check", "purpose": "Run explicit fixture assertions.",
         "argv": ["{python}", "{build}/implementation/check.py"], "timeout_seconds": 5,
         "requirement_ids": ["FR-001"]},
    ]})
    return build, plan, root / "results"


def set_cases(plan, cases):
    value = json.loads(plan.read_text())
    value["cases"] = cases
    write_json(plan, value)


def case(cid, code, timeout=5):
    return {"id": cid, "purpose": "Assert one synthetic condition.",
            "argv": ["{python}", "-c", code], "timeout_seconds": timeout}


@pytest.mark.parametrize("version", [1, 2])
def test_exact_copies_isolated_argv_and_frozen_plan(tmp_path, monkeypatch, version):
    script = """import json, os, sys
from pathlib import Path
assert 'PYTHONPATH' not in os.environ
assert Path.cwd().name == 'work'
assert not Path.cwd().is_relative_to(Path(sys.argv[3]))
assert not Path(__file__).samefile(sys.argv[2])
assert Path(__file__).read_bytes() == Path(sys.argv[2]).read_bytes()
Path(sys.argv[1], 'result.json').write_text(json.dumps({'asserted': True}))
print(sys.argv[4])
print('stderr retained', file=sys.stderr)
"""
    build, plan, out = make_build(tmp_path, script, version)
    value = json.loads(plan.read_text())
    shell_marker = tmp_path / "must-not-be-created"
    literal = f"$(touch {shell_marker}); literal argument"
    value["cases"][0]["argv"] += ["{artifacts}", str(build / "implementation/check.py"), str(build.parent), literal]
    write_json(plan, value)
    monkeypatch.setenv("PYTHONPATH", "/untrusted/inherited/path")
    before_plan = plan.read_bytes()
    report = validate_build(build, plan, out)
    assert report["status"] == "passed"
    assert report == json.loads((out / "report.json").read_text())
    assert (out / "plan.json").read_bytes() == before_plan
    assert report["plan_sha256"] == hashlib.sha256(before_plan).hexdigest()
    for name, expected in report["start_hashes"].items():
        assert digest(build / name) == digest(out / "build" / name) == expected
        assert not (build / name).samefile(out / "build" / name)
    execution = Path(report["execution_build_historical_temporary_path"])
    assert not execution.is_relative_to(build.parent)
    assert not execution.exists()
    assert (out / "cases/check/stdout.txt").read_text().strip() == literal
    assert (out / "cases/check/stderr.txt").read_text().strip() == "stderr retained"
    assert json.loads((out / "cases/check/artifacts/result.json").read_text()) == {"asserted": True}
    assert not shell_marker.exists()
    assert report["cases"][0]["requirement_ids"] == ["FR-001"]
    assert "does not establish semantic correctness" in report["scope"]


def test_nonzero_preserved_while_later_case_runs(tmp_path):
    build, plan, out = make_build(tmp_path)
    set_cases(plan, [case("reject", "import sys; print('failure evidence'); print('assertion failed', file=sys.stderr); sys.exit(7)"),
                     case("later", "print('independent later check')")])
    report = validate_build(build, plan, out)
    assert report["status"] == "failed"
    assert [(row["status"], row["returncode"]) for row in report["cases"]] == [("failed", 7), ("passed", 0)]
    assert "failure evidence" in (out / "cases/reject/stdout.txt").read_text()
    assert "assertion failed" in (out / "cases/reject/stderr.txt").read_text()
    assert json.loads((out / "report.json").read_text())["status"] == "failed"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process group cleanup")
@pytest.mark.parametrize("parent_waits", [True, False])
def test_timeout_or_success_stops_child_processes(tmp_path, parent_waits):
    build, plan, out = make_build(tmp_path)
    marker = tmp_path / "leaked-child"
    child = ("import signal,time; from pathlib import Path; "
             "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(0.8); "
             f"Path({str(marker)!r}).write_text('leaked')")
    code = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); print('child started', flush=True)"
    if parent_waits:
        code += "; time.sleep(30)"
    set_cases(plan, [case("child", code, timeout=0.25), case("later", "print('independent later check')")])
    started = time.monotonic()
    report = validate_build(build, plan, out)
    assert time.monotonic() - started < 5
    row = report["cases"][0]
    assert row["timed_out"] is parent_waits
    assert row["status"] == ("failed" if parent_waits else "passed")
    assert row["cleanup"]["sigterm_sent"]
    if parent_waits:
        assert row["returncode"] < 0
    assert report["cases"][1]["status"] == "passed"
    time.sleep(0.9)
    assert not marker.exists(), "A child escaped the case's process-group cleanup"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process group cleanup")
@pytest.mark.parametrize("mode", ["running", "ignores-term", "exited"])
def test_denied_group_signal_reaps_leader_and_stops_following_cases(tmp_path, monkeypatch, mode):
    build, plan, out = make_build(tmp_path)
    code = "print('already complete')" if mode == "exited" else "import time; time.sleep(30)"
    set_cases(plan, [case("denied", code, timeout=0.25),
                     case("pending", "raise AssertionError('cleanup failure must stop the plan')")])
    processes = []
    original_popen = subprocess.Popen

    def spawn(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        if mode == "ignores-term":
            # Force the real process to need SIGKILL without a startup race in
            # installing a signal handler in the child.
            process.terminate = lambda: None
        return process

    def denied(*args):
        raise PermissionError(errno.EPERM, "process-group signalling denied")

    monkeypatch.setattr(build_validation.subprocess, "Popen", spawn)
    monkeypatch.setattr(build_validation.os, "killpg", denied)
    started = time.monotonic()
    try:
        report = validate_build(build, plan, out)
        assert time.monotonic() - started < 5
        row = report["cases"][0]
        assert report["status"] == row["status"] == "failed"
        assert row["returncode"] == processes[0].poll()
        assert row["returncode"] is not None
        assert row["cleanup"]["leader_reaped"]
        assert row["cleanup"]["process_group_signals"] == "failed"
        assert "process-group signalling denied" in row["cleanup_error"]
        assert row["cleanup"]["leader_fallback"] is (mode != "exited")
        assert row["cleanup"]["leader_sigkill_sent"] is (mode == "ignores-term")
        assert row["process_exit_zero"] is (mode == "exited")
        assert report["cases"][1]["status"] == "not_run"
        assert report["errors"][0]["kind"] == "cleanup_failure"
        assert report == json.loads((out / "report.json").read_text())
    finally:
        # A failed assertion must never leave the deliberately long-lived
        # fixture running, including when testing a broken cleanup path.
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


@pytest.mark.skipif(os.name != "posix", reason="POSIX process group cleanup")
def test_cleanup_reaps_terminated_leader_before_second_group_signal(monkeypatch):
    class ExitedLeader:
        pid = 12345
        returncode = None

        def poll(self):
            self.returncode = -signal.SIGTERM
            return self.returncode

        def wait(self, timeout):
            assert self.returncode is not None
            return self.returncode

    process = ExitedLeader()
    signals = []

    def signal_group(pid, sig):
        signals.append(sig)
        if sig == signal.SIGKILL:
            if process.returncode is None:
                raise PermissionError(errno.EPERM, "macOS unreaped group leader")
            raise ProcessLookupError(errno.ESRCH, "group is gone")

    monkeypatch.setattr(build_validation.os, "killpg", signal_group)
    result = build_validation._cleanup(process)
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert result["errors"] == []
    assert result["leader_reaped"]
    assert result["process_group_signals"] == "completed"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process group cleanup")
def test_cleanup_is_bounded_and_reports_when_all_signals_are_denied(monkeypatch):
    waits = []

    def denied(*args):
        raise PermissionError(errno.EPERM, "all signals denied")

    class UnkillableLeader:
        pid = 12345
        returncode = None
        terminate = staticmethod(denied)
        kill = staticmethod(denied)

        def poll(self):
            return None

        def wait(self, timeout):
            waits.append(timeout)
            raise subprocess.TimeoutExpired("fixture", timeout)

    monkeypatch.setattr(build_validation.os, "killpg", denied)
    result = build_validation._cleanup(UnkillableLeader())
    assert len(waits) == 3 and sum(waits) <= 5.2
    assert not result["leader_reaped"]
    assert result["process_group_signals"] == "failed"
    assert {item["operation"] for item in result["errors"]} == {
        "process group SIGTERM", "process group SIGKILL", "leader terminate", "leader kill", "wait for leader"}


@pytest.mark.parametrize("target", ["implementation/check.py", "build.json"])
def test_execution_tamper_aborts_pending_cases_but_preserves_source_snapshot(tmp_path, target):
    build, plan, out = make_build(tmp_path)
    original = (build / target).read_bytes()
    marker = tmp_path / "pending-ran"
    set_cases(plan, [case("tamper", f"from pathlib import Path; Path('{{build}}/{target}').write_text('changed')"),
                     case("pending", f"from pathlib import Path; Path({str(marker)!r}).touch()")])
    report = validate_build(build, plan, out)
    assert report["status"] == "failed"
    assert report["cases"][0]["process_exit_zero"]
    assert report["cases"][0]["integrity_failure"]
    assert report["cases"][1]["status"] == "not_run"
    assert report["final_integrity"]["execution_copy"]["status"] == "failed"
    assert (build / target).read_bytes() == (out / "build" / target).read_bytes() == original
    assert not marker.exists()


@pytest.mark.parametrize("target", ["implementation/helper.txt", "build.json"])
def test_original_source_tamper_cannot_be_rebound_after_execution(tmp_path, target):
    build, plan, out = make_build(tmp_path)
    original_hash = digest(build / target)
    set_cases(plan, [case("source-tamper", f"from pathlib import Path; Path({str(build / target)!r}).write_text('changed')"),
                     case("pending", "raise AssertionError('must not run')")])
    report = validate_build(build, plan, out)
    assert report["status"] == "failed"
    assert report["final_integrity"]["source"]["status"] == "failed"
    assert report["cases"][1]["status"] == "not_run"
    assert report["start_hashes"][target] == digest(out / "build" / target) == original_hash


@pytest.mark.parametrize("problem", ["undeclared", "missing", "changed", "missing-hash", "invalid-hash", "traversal", "symlink"])
def test_invalid_build_rejected_before_execution_or_output(tmp_path, monkeypatch, problem):
    build, plan, out = make_build(tmp_path)
    manifest = json.loads((build / "build.json").read_text())
    if problem == "undeclared":
        (build / "unexpected.txt").write_text("must not copy")
    elif problem == "missing":
        (build / "implementation/helper.txt").unlink()
    elif problem == "changed":
        (build / "implementation/helper.txt").write_text("wrong bytes")
    elif problem == "missing-hash":
        del manifest["files"]["implementation/helper.txt"]
    elif problem == "invalid-hash":
        manifest["files"]["implementation/helper.txt"] = "not-a-digest"
    elif problem == "traversal":
        manifest["files"]["../outside.txt"] = "0" * 64
    else:
        target = build / "implementation/helper.txt"
        target.unlink()
        target.symlink_to(plan)
    write_json(build / "build.json", manifest)
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid input executed a command")
    monkeypatch.setattr("rea_backend.build_validation.subprocess.Popen", forbidden)
    with pytest.raises(ValueError):
        validate_build(build, plan, out)
    assert not out.exists()


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(purpose=""),
    lambda p: p.update(shell=True),
    lambda p: p.update(cases=[]),
    lambda p: p["cases"].append(dict(p["cases"][0])),
    lambda p: p["cases"].append({**p["cases"][0], "id": "CHECK"}),
    lambda p: p["cases"][0].update(timeout_seconds=0),
    lambda p: p["cases"][0].update(timeout_seconds=True),
    lambda p: p["cases"][0].update(timeout_seconds=601),
    lambda p: p["cases"][0].update(timeout_seconds=10**1000),
    lambda p: p["cases"][0].update(argv="python check.py"),
    lambda p: p["cases"][0].update(argv=["python", "\0"]),
    lambda p: p["cases"][0].update(expected_exit_code=7),
    lambda p: p["cases"][0].update(id="../outside"),
    lambda p: p["cases"][0].update(requirement_ids=["FR-unknown"]),
])
def test_malformed_plan_rejected_without_execution(tmp_path, monkeypatch, mutation):
    build, plan, out = make_build(tmp_path)
    value = json.loads(plan.read_text())
    mutation(value)
    write_json(plan, value)
    def forbidden(*args, **kwargs):
        raise AssertionError("Malformed plan executed a command")
    monkeypatch.setattr("rea_backend.build_validation.subprocess.Popen", forbidden)
    with pytest.raises(ValueError):
        validate_build(build, plan, out)
    assert not out.exists()


@pytest.mark.parametrize("raw", ['{"format":"first","format":"second"}', '{"timeout_seconds":NaN}'])
def test_ambiguous_json_is_rejected(tmp_path, raw):
    build, plan, out = make_build(tmp_path)
    plan.write_text(raw)
    with pytest.raises(ValueError):
        validate_build(build, plan, out)
    assert not out.exists()


@pytest.mark.parametrize("value", [[], {}, None, 2, "rea-backend.srs-build/v3"])
def test_invalid_build_format_raises_value_error(tmp_path, value):
    build, plan, out = make_build(tmp_path)
    manifest = json.loads((build / "build.json").read_text())
    manifest["format"] = value
    write_json(build / "build.json", manifest)
    with pytest.raises(ValueError, match="srs-build v1/v2"):
        validate_build(build, plan, out)
    assert not out.exists()


def test_no_overwrite_and_no_output_inside_source_build(tmp_path):
    build, plan, out = make_build(tmp_path)
    out.mkdir()
    (out / "keep").write_text("original")
    with pytest.raises(ValueError, match="already exists"):
        validate_build(build, plan, out)
    assert (out / "keep").read_text() == "original"
    with pytest.raises(ValueError, match="inside the build"):
        validate_build(build, plan, build / "output")
    assert not (build / "output").exists()


def test_spawn_error_retained_and_artifact_symlink_not_followed(tmp_path):
    build, plan, out = make_build(tmp_path)
    missing = case("missing-command", "")
    missing["argv"] = [str(tmp_path / "missing-executable")]
    link = case("linked-artifact", "from pathlib import Path; Path('{artifacts}/link').symlink_to(" + repr(str(plan)) + ")")
    set_cases(plan, [missing, link])
    report = validate_build(build, plan, out)
    assert report["status"] == "failed"
    assert "launch_error" in report["cases"][0]
    assert report["cases"][0]["returncode"] is None
    assert "Symlink" in report["cases"][1]["artifact_error"]
    assert not (out / "cases/linked-artifact/artifacts/link").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX special files")
def test_fifo_manifest_does_not_block_preflight(tmp_path):
    build, plan, out = make_build(tmp_path)
    (build / "build.json").unlink()
    os.mkfifo(build / "build.json")
    started = time.monotonic()
    with pytest.raises(ValueError, match="regular file"):
        validate_build(build, plan, out)
    assert time.monotonic() - started < 2
    assert not out.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX external temporary fallback")
def test_temp_environment_cannot_place_execution_inside_repository(tmp_path, monkeypatch):
    build, plan, out = make_build(tmp_path)
    bad_temp = build.parent / "scratch"
    bad_temp.mkdir()
    monkeypatch.setattr("rea_backend.build_validation.tempfile.tempdir", str(bad_temp))
    report = validate_build(build, plan, out)
    assert report["status"] == "passed"
    assert not Path(report["execution_build_historical_temporary_path"]).is_relative_to(build.parent)


def make_v2_build(tmp_path):
    """Synthetic frozen discovery and accepted-review receipts, not an App oracle."""
    build, plan, out = make_build(tmp_path)
    extra = {
        "srs/analysis/analysis.json": json.dumps({"format": "rea-backend.analysis/v3", "items": [
            {"id": "A-home", "flow_trace": {"state": "answered", "nodes": [
                {"id": "entry", "kind": "entry"}, {"id": "render", "kind": "consumer"}]},
             "contract_checks": {kind: {"state": "answered"} for kind in ("consumer", "wire", "state", "resources")}}]}),
        "srs/backend-srs.md": "# Synthetic frozen requirements\n",
        "srs/inventory.json": "{}\n", "srs/run.json": "{}\n", "srs/method/manifest.json": "{}\n",
    }
    for name, content in extra.items():
        (build / name).parent.mkdir(parents=True, exist_ok=True)
        (build / name).write_text(content)
    review = {"format": "rea-backend.srs-review/v3", "verdict": "accepted", "independent": True}
    for field, name in (("document_sha256", "backend-srs.md"), ("index_sha256", "index.json"),
                        ("inventory_sha256", "inventory.json"), ("run_sha256", "run.json"),
                        ("analysis_sha256", "analysis/analysis.json"), ("method_sha256", "method/manifest.json")):
        review[field] = digest(build / "srs" / name)
    write_json(build / "srs/review.json", review)
    write_json(build / "srs-check.json", {"status": "checked", "review": "accepted",
                                         "document_sha256": review["document_sha256"], "index_sha256": review["index_sha256"]})
    manifest = json.loads((build / "build.json").read_text())
    names = list(manifest["files"]) + list(extra) + ["srs/review.json", "srs-check.json"]
    manifest["files"] = {name: digest(build / name) for name in names}
    write_json(build / "build.json", manifest)
    write_json(plan, {"format": PLAN_FORMAT_V2, "purpose": "Synthetic workflow fixture.", "phase": "early_client",
                      "scope": {"workflow_ids": ["A-home"], "requirement_ids": ["FR-001"]},
                      "obligations": [{"id": "risk-render", "item_id": "A-home", "contract_kind": "consumer",
                                       "node_ids": ["render"], "requirement_ids": ["FR-001"],
                                       "risk": "A successful HTTP response may still fail the actual renderer."}],
                      "cases": [v2_case()]})
    return build, plan, out


def v2_case(code=None, kind="real_client"):
    code = code or ("from pathlib import Path; p=Path('{artifacts}'); "
                    "p.joinpath('ui.xml').write_text('<home rendered=\"true\"/>'); "
                    "p.joinpath('requests.json').write_text('{\"request_observed\":true}')")
    value = {**case("home", code), "requirement_ids": ["FR-001"], "workflow_ids": ["A-home"],
             "obligation_ids": ["risk-render"], "check_kind": kind,
             "required_artifacts": [{"path": "ui.xml", "kind": "ui"}, {"path": "requests.json", "kind": "request"}]}
    if kind == "model":
        value["model_limitations"] = "Synthetic renderer assertions; the Android runtime is not exercised."
    return value


def test_v2_preserves_explicit_risk_links_and_evidence_hashes(tmp_path):
    build, plan, out = make_v2_build(tmp_path)
    report = validate_build(build, plan, out)
    assert report["format"] == "rea-backend.build-validation/v2"
    assert report["status"] == "passed"
    assert report["phase"] == "early_client"
    assert report["early_client_gate"]["final_validation_still_required"] is True
    assert report["coverage"]["planned_workflow_ids"] == ["A-home"]
    assert report["cases"][0]["obligation_ids"] == ["risk-render"]
    for evidence in report["cases"][0]["evidence_checks"]:
        assert evidence["status"] == "passed"
        assert evidence["sha256"] == digest(out / "cases/home/artifacts" / evidence["path"])
    assert report["failures"] == []


@pytest.mark.parametrize("problem", ["missing", "empty", "stale"])
def test_http_success_cannot_pass_without_fresh_client_evidence(tmp_path, problem):
    build, plan, out = make_v2_build(tmp_path)
    code = "from pathlib import Path; import os; p=Path('{artifacts}'); p.joinpath('requests.json').write_text('HTTP 200')"
    if problem != "missing":
        code += "; p.joinpath('ui.xml').write_text(" + repr("" if problem == "empty" else "old UI") + ")"
    if problem == "stale":
        code += "; os.utime(p/'ui.xml', (1, 1))"
    set_cases(plan, [v2_case(code)])
    report = validate_build(build, plan, out)
    assert report["status"] == "failed"
    assert report["cases"][0]["process_exit_zero"]
    assert report["cases"][0]["evidence_checks"][0]["error"] == problem
    assert report["failures"][0]["category"] == "unknown"
    assert report["failures"][0]["next_stage"] == "investigation"


@pytest.mark.parametrize("mutation", [
    lambda p: p["scope"].update(workflow_ids=["A-missing"]),
    lambda p: p["scope"].update(requirement_ids=["FR-missing"]),
    lambda p: p["obligations"][0].update(item_id="A-missing"),
    lambda p: p["obligations"][0].update(node_ids=["unknown-node"]),
    lambda p: p["obligations"][0].update(contract_kind="guessed"),
    lambda p: p["cases"][0].update(obligation_ids=[]),
    lambda p: p["cases"][0].update(check_kind="http"),
    lambda p: p["cases"][0].update(check_kind="model", model_limitations="Synthetic model only."),
    lambda p: p["cases"][0].update(required_artifacts=[]),
    lambda p: p["cases"][0]["required_artifacts"][0].update(path="../escape"),
    lambda p: p.update(phase="final"),
])
def test_v2_invalid_or_non_client_early_plan_does_not_execute(tmp_path, monkeypatch, mutation):
    build, plan, out = make_v2_build(tmp_path)
    value = json.loads(plan.read_text())
    mutation(value)
    write_json(plan, value)
    monkeypatch.setattr(build_validation.subprocess, "Popen", lambda *a, **k: pytest.fail("Must reject before execution"))
    with pytest.raises(ValueError):
        validate_build(build, plan, out)
    assert not out.exists()


@pytest.mark.parametrize("category,stage", [("requirement_gap", "discovery_srs"), ("implementation", "implementation"),
                                           ("environment", "environment"), ("unknown", "investigation")])
def test_authored_failure_evidence_routes_to_the_right_stage(tmp_path, category, stage):
    build, plan, out = make_v2_build(tmp_path)
    diagnostic = {"category": category, "summary": "Observed synthetic failure; investigate its retained log.",
                  "evidence_paths": ["observed.txt"]}
    code = ("from pathlib import Path; import sys; p=Path('{artifacts}'); p.joinpath('observed.txt').write_text('failure trace'); "
            "p.joinpath('failure.json').write_text(" + repr(json.dumps(diagnostic)) + "); sys.exit(2)")
    check = v2_case(code)
    check["failure_artifact"] = "failure.json"
    set_cases(plan, [check])
    report = validate_build(build, plan, out)
    failure = report["failures"][0]
    assert failure["category"] == category and failure["next_stage"] == stage
    assert failure["attribution"] == "author_observation_not_independently_verified"
    assert failure["artifact_sha256"] == digest(out / "cases/home/artifacts/failure.json")
    assert report == json.loads((out / "report.json").read_text())


def test_unsubstantiated_failure_diagnosis_stays_unknown_even_with_zero_exit(tmp_path):
    build, plan, out = make_v2_build(tmp_path)
    diagnostic = {"category": "requirement_gap", "summary": "An unsupported attribution.", "evidence_paths": ["missing.log"]}
    check = v2_case()
    check["argv"][-1] += "; p.joinpath('failure.json').write_text(" + repr(json.dumps(diagnostic)) + ")"
    check["failure_artifact"] = "failure.json"
    set_cases(plan, [check])
    report = validate_build(build, plan, out)
    assert report["status"] == "failed"
    assert report["cases"][0]["process_exit_zero"]
    assert report["failures"][0]["category"] == "unknown"
    assert "Missing, empty or stale" in report["failures"][0]["attribution_error"]


def test_v2_timeout_preserves_partial_evidence_and_unknown_diagnosis(tmp_path):
    build, plan, out = make_v2_build(tmp_path)
    check = v2_case("from pathlib import Path; import time; Path('{artifacts}/ui.xml').write_text('partial UI'); time.sleep(30)")
    check["timeout_seconds"] = .2
    set_cases(plan, [check])
    report = validate_build(build, plan, out)
    assert report["status"] == "failed" and report["cases"][0]["timed_out"]
    assert (out / "cases/home/artifacts/ui.xml").read_text() == "partial UI"
    assert report["failures"][0]["category"] == "unknown"
    assert "time limit" in report["failures"][0]["summary"]


def prepare_final(build, plan, early):
    value = json.loads(plan.read_text())
    value.update(phase="final", early_client={"path": early.relative_to(plan.parent).as_posix() + "/report.json",
                                             "sha256": digest(early / "report.json")})
    write_json(plan, value)


def test_final_binds_early_evidence_but_allows_expanded_implementation(tmp_path):
    build, plan, out = make_v2_build(tmp_path)
    early = tmp_path / "early"
    validate_build(build, plan, early)
    prepare_final(build, plan, early)
    # Expansion may change backend bytes, but cannot silently switch the SRS.
    (build / "implementation/check.py").write_text("print('expanded after early client smoke')\n")
    manifest = json.loads((build / "build.json").read_text())
    manifest["files"]["implementation/check.py"] = digest(build / "implementation/check.py")
    write_json(build / "build.json", manifest)
    report = validate_build(build, plan, out)
    assert report["status"] == "passed" and report["phase"] == "final"
    assert report["early_client_gate"]["status"] == "passed"
    assert (out / "early_client/report.json").read_bytes() == (early / "report.json").read_bytes()
    assert (out / "early_client/cases/home/artifacts/ui.xml").read_bytes() == (early / "cases/home/artifacts/ui.xml").read_bytes()


@pytest.mark.parametrize("target", ["report.json", "plan.json", "cases/home/artifacts/ui.xml", "cases/home/stdout.txt",
                                    "build/srs/index.json", "build/implementation/check.py"])
def test_final_rejects_tampered_early_package_before_execution(tmp_path, monkeypatch, target):
    build, plan, out = make_v2_build(tmp_path)
    early = tmp_path / "early"
    validate_build(build, plan, early)
    prepare_final(build, plan, early)
    (early / target).write_text("tampered")
    monkeypatch.setattr(build_validation.subprocess, "Popen", lambda *a, **k: pytest.fail("Must reject before execution"))
    with pytest.raises(ValueError):
        validate_build(build, plan, out)
    assert not out.exists()


def test_model_is_supplemental_and_requires_limitations(tmp_path):
    build, plan, out = make_v2_build(tmp_path)
    early = tmp_path / "early"
    validate_build(build, plan, early)
    prepare_final(build, plan, early)
    check = v2_case(kind="model")
    check["id"] = "model"
    check.pop("model_limitations")
    set_cases(plan, [v2_case(), check])
    with pytest.raises(ValueError, match="Model limitations"):
        validate_build(build, plan, out)
    check["model_limitations"] = "Synthetic model only; no Android runtime."
    set_cases(plan, [check])
    with pytest.raises(ValueError, match="final requires a real-client"):
        validate_build(build, plan, out)
    set_cases(plan, [v2_case(), check])
    report = validate_build(build, plan, out)
    assert report["status"] == "passed"
    assert report["coverage"]["model_case_ids"] == ["model"]
    assert "Android runtime" in report["cases"][1]["model_limitations"]


def test_new_srs_baseline_requires_new_early_client_run(tmp_path):
    build, plan, out = make_v2_build(tmp_path)
    early = tmp_path / "early"
    validate_build(build, plan, early)
    prepare_final(build, plan, early)
    analysis = build / "srs/analysis/analysis.json"
    analysis.write_text(analysis.read_text() + "\n")
    review_path = build / "srs/review.json"
    review = json.loads(review_path.read_text())
    review["analysis_sha256"] = digest(analysis)
    write_json(review_path, review)
    manifest = json.loads((build / "build.json").read_text())
    for name in ("srs/analysis/analysis.json", "srs/review.json"):
        manifest["files"][name] = digest(build / name)
    write_json(build / "build.json", manifest)
    with pytest.raises(ValueError, match="another frozen SRS baseline"):
        validate_build(build, plan, out)
    assert not out.exists()


def test_state_risk_requires_storage_evidence_without_imposing_it_on_reads(tmp_path):
    build, plan, out = make_v2_build(tmp_path)
    value = json.loads(plan.read_text())
    value["obligations"][0]["contract_kind"] = "state"
    write_json(plan, value)
    with pytest.raises(ValueError, match="actual-storage"):
        validate_build(build, plan, out)
    value["cases"][0]["required_artifacts"].append({"path": "storage.json", "kind": "storage"})
    value["cases"][0]["argv"][-1] += "; p.joinpath('storage.json').write_text('{\"persisted\":true}')"
    write_json(plan, value)
    assert validate_build(build, plan, out)["status"] == "passed"


def test_v2_requires_accepted_review_before_running_client(tmp_path):
    build, plan, out = make_v2_build(tmp_path)
    review_path = build / "srs/review.json"
    review = json.loads(review_path.read_text())
    review["verdict"] = "revisions_required"
    write_json(review_path, review)
    manifest = json.loads((build / "build.json").read_text())
    manifest["files"]["srs/review.json"] = digest(review_path)
    write_json(build / "build.json", manifest)
    with pytest.raises(ValueError, match="independently accepted"):
        validate_build(build, plan, out)
    assert not out.exists()


def rebind_fixture_file(build, name, value):
    """Update fixture hash bindings to exercise content validation after integrity."""
    target = build / name
    if isinstance(value, (dict, list)):
        write_json(target, value)
    else:
        target.write_text(value)
    review_path = build / "srs/review.json"
    review = json.loads(review_path.read_text())
    fields = {"srs/backend-srs.md": "document_sha256", "srs/index.json": "index_sha256",
              "srs/inventory.json": "inventory_sha256", "srs/run.json": "run_sha256",
              "srs/analysis/analysis.json": "analysis_sha256", "srs/method/manifest.json": "method_sha256"}
    if name in fields:
        review[fields[name]] = digest(target)
        write_json(review_path, review)
        if name in ("srs/backend-srs.md", "srs/index.json"):
            receipt_path = build / "srs-check.json"
            receipt = json.loads(receipt_path.read_text())
            receipt[fields[name]] = digest(target)
            write_json(receipt_path, receipt)
    manifest = json.loads((build / "build.json").read_text())
    manifest["files"] = {path: digest(build / path) for path in manifest["files"]}
    write_json(build / "build.json", manifest)


@pytest.mark.parametrize("target", ["srs/backend-srs.md", "srs/inventory.json", "srs/run.json", "srs/method/manifest.json"])
def test_any_changed_frozen_srs_artifact_requires_new_early_run(tmp_path, target):
    build, plan, out = make_v2_build(tmp_path)
    early = tmp_path / "early"
    validate_build(build, plan, early)
    prepare_final(build, plan, early)
    rebind_fixture_file(build, target, (build / target).read_text() + "\n")
    with pytest.raises(ValueError, match="another frozen SRS baseline"):
        validate_build(build, plan, out)
    assert not out.exists()


@pytest.mark.parametrize("mutation", [
    lambda item: item["flow_trace"].update(state=[]),
    lambda item: item["flow_trace"].update(nodes=None),
    lambda item: item["flow_trace"]["nodes"][0].update(id={}),
    lambda item: item["flow_trace"]["nodes"].append(dict(item["flow_trace"]["nodes"][0])),
    lambda item: item["contract_checks"]["consumer"].update(state={}),
])
def test_malformed_frozen_contract_metadata_is_rejected_without_type_errors(tmp_path, monkeypatch, mutation):
    build, plan, out = make_v2_build(tmp_path)
    analysis = json.loads((build / "srs/analysis/analysis.json").read_text())
    mutation(analysis["items"][0])
    rebind_fixture_file(build, "srs/analysis/analysis.json", analysis)
    monkeypatch.setattr(build_validation.subprocess, "Popen", lambda *a, **k: pytest.fail("Malformed frozen metadata must not execute"))
    with pytest.raises(ValueError):
        validate_build(build, plan, out)
    assert not out.exists()


@pytest.mark.parametrize("mutation", [
    lambda result: result.update(check_kind="model"),
    lambda result: result.update(workflow_ids=[]),
    lambda result: result.update(cleanup_error="The owned process was not terminated."),
])
def test_early_report_cannot_contradict_its_plan_or_retain_failure(tmp_path, mutation):
    build, plan, out = make_v2_build(tmp_path)
    early = tmp_path / "early"
    validate_build(build, plan, early)
    record = json.loads((early / "report.json").read_text())
    mutation(record["cases"][0])
    write_json(early / "report.json", record)
    prepare_final(build, plan, early)
    with pytest.raises(ValueError, match="differs from its frozen plan|retains a failure"):
        validate_build(build, plan, out)
    assert not out.exists()


def test_v2_executes_packaged_real_srs_build_chain_with_synthetic_check(materials):
    """Exercise production freeze/review/build APIs; the subprocess is a fake client.

    This regression checks format compatibility, never Android semantics or
    independent review quality. The recorded scope explicitly says so.
    """
    from rea_backend.analysis import initialize_analysis, update_analysis
    from rea_backend.srs import initialize_srs
    from rea_backend.srs_build import build_from_srs
    from test_flow_discovery import flow_item
    from test_srs import reviewed, valid_index, write_document

    analysis = materials["root"] / "analysis"
    initialize_analysis(materials["config"], analysis)
    item = flow_item(materials)
    item["contract_checks"]["consumer"]["state"] = "answered"
    update_analysis(materials["config"], analysis, [item], 1)
    initialize_srs(materials["config"], materials["out"], template=materials["template"], analysis=analysis)
    write_json(materials["out"] / "index.json", valid_index(materials))
    write_document(materials["out"] / "backend-srs.md")
    reviewed(materials)
    implementation = materials["root"] / "implementation"
    implementation.mkdir()
    (implementation / "app.py").write_text("# Packaging fixture; no running backend is claimed.\n")
    (implementation / "requirements.txt").write_text("# Synthetic fixture uses the standard library only.\n")
    write_json(implementation / "implementation.json", {
        "format": "rea-backend.srs-implementation/v2", "name": "synthetic-validation-chain",
        "app_id": "reader", "route": "source", "entrypoint": "app.py", "files": ["app.py", "requirements.txt"],
        "srs_hashes": {name: digest(materials["out"] / name) for name in (
            "backend-srs.md", "index.json", "inventory.json", "run.json", "analysis/analysis.json", "method/manifest.json")},
        "requirements": [{"id": "FR-articles-001", "status": "partial", "files": ["app.py"],
                          "note": "Only packaging and validation protocol compatibility are tested."}], "decisions": [],
    })
    build = materials["root"] / "build"
    assert build_from_srs(materials["config"], materials["out"], implementation, build)["status"] == "built"
    check = v2_case()
    check.update(requirement_ids=["FR-articles-001"], workflow_ids=["Q-page"])
    plan = materials["root"] / "plan.json"
    write_json(plan, {"format": PLAN_FORMAT_V2, "purpose": "Synthetic protocol test; no real Android claim.",
                      "phase": "early_client", "scope": {"workflow_ids": ["Q-page"], "requirement_ids": ["FR-articles-001"]},
                      "obligations": [{"id": "risk-render", "item_id": "Q-page", "contract_kind": "consumer",
                                       "node_ids": ["N-sort"], "requirement_ids": ["FR-articles-001"],
                                       "risk": "Synthetic frozen consumer constraint."}], "cases": [check]})
    early, final = materials["root"] / "early", materials["root"] / "final"
    assert validate_build(build, plan, early)["status"] == "passed"
    prepare_final(build, plan, early)
    result = validate_build(build, plan, final)
    assert result["status"] == "passed", result
    assert result["early_client_gate"]["status"] == "passed"
