"""Exercise exploration and freezing through the public CLI, not mocked dispatch."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def invoke(*args):
    return subprocess.run([sys.executable, "-m", "rea_backend", *map(str, args)],
                          cwd=ROOT, text=True, capture_output=True)


def test_cli_exploration_cannot_freeze_pending_or_overwrite_a_newer_revision(tmp_path):
    source = tmp_path / "client"
    source.mkdir()
    initial = source / "client.txt"
    initial.write_text("Synthetic fixture with unresolved entry points.\n")
    config = tmp_path / "inputs.json"
    config.write_text(json.dumps({
        "format": "rea-backend.srs-config/v1",
        "app": {"id": "fixture", "name": "Fixture", "version": "1", "platform": "Android", "variant": "test"},
        "route": "source", "context": {"mode": "client_only", "notes": "CLI protocol fixture only."},
        "inputs": [{"id": "client", "kind": "client_source", "path": "client", "version": "1",
                    "access": "generation", "complete": True, "limitations": [], "exclude": []}],
        "environment": {"goals": ["Test CLI state transitions."], "constraints": []},
    }))
    analysis = tmp_path / "analysis"
    started = invoke("srs-explore", "--config", config, "--out", analysis)
    assert started.returncode == 0, started.stderr
    revision = json.loads((analysis / "analysis.json").read_text())["revision"]
    locator = {"input_id": "client", "path": "client.txt",
               "sha256": hashlib.sha256(initial.read_bytes()).hexdigest()}
    work = {"id": "TASK-entry", "clue": "Fixture entry", "question": "Which entry is reachable?",
            "area": "ui", "sources": [locator], "state": "pending", "next_action": "Inspect the entry.",
            "depends_on": [], "evidence": [], "finding": "", "gap_ids": []}
    work["contract_checks"] = {kind: {"state": "pending", "finding": "", "evidence": [],
                                     "next_action": "Inspect this scoped entry.", "gap_ids": []}
                               for kind in ("consumer", "wire", "state", "resources")}
    work["flow_trace"] = {"state": "pending", "scope": "Fixture entry and its uninspected branches.",
                          "finding": "", "evidence": [], "next_action": "Locate the entry and prerequisite branches.",
                          "gap_ids": [], "nodes": [], "edges": [], "boundaries": []}
    updates = tmp_path / "updates.json"
    updates.write_text(json.dumps([work]))
    updated = invoke("srs-analysis-update", "--config", config, "--analysis", analysis,
                     "--updates", updates, "--expected-revision", revision)
    assert updated.returncode == 0, updated.stderr
    before = (analysis / "analysis.json").read_bytes()
    stale = invoke("srs-analysis-update", "--config", config, "--analysis", analysis,
                   "--updates", updates, "--expected-revision", revision)
    assert stale.returncode != 0
    assert (analysis / "analysis.json").read_bytes() == before
    unsettled = invoke("srs-analysis-check", "--config", config, "--analysis", analysis, "--require-settled")
    assert unsettled.returncode != 0
    frozen = invoke("srs-init", "--config", config, "--analysis", analysis,
                    "--template", ROOT / "src/rea_backend/resources/templates/backend-requirements.md", "--out", tmp_path / "srs")
    assert frozen.returncode != 0
    assert not (tmp_path / "srs" / "run.json").exists()


def validation_fixture(tmp_path, exit_code):
    build = tmp_path / "build"
    build.mkdir()
    script = build / "check.py"
    script.write_text(f"import sys\nprint('retained CLI evidence')\nsys.exit({exit_code})\n")
    (build / "build.json").write_text(json.dumps({
        "format": "rea-backend.srs-build/v2", "entrypoint": "check.py",
        "files": {"check.py": hashlib.sha256(script.read_bytes()).hexdigest()},
    }))
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({
        "format": "rea-backend.build-validation-plan/v1", "purpose": "Exercise CLI status propagation.",
        "cases": [{"id": "check", "purpose": "Run a synthetic check.",
                   "argv": ["{python}", "{build}/check.py"], "timeout_seconds": 5}],
    }))
    return build, plan, tmp_path / "result"


@pytest.mark.parametrize("exit_code", [0, 7])
def test_cli_build_validation_preserves_report_and_propagates_failure(tmp_path, exit_code):
    build, plan, out = validation_fixture(tmp_path, exit_code)
    result = invoke("srs-validate-build", "--build", build, "--plan", plan, "--out", out)
    assert result.returncode == (0 if exit_code == 0 else 1), result.stderr
    report = json.loads((out / "report.json").read_text())
    assert report["status"] == ("passed" if exit_code == 0 else "failed")
    assert report["cases"][0]["returncode"] == exit_code
    assert json.loads(result.stdout) == report
    assert "retained CLI evidence" in (out / "cases/check/stdout.txt").read_text()


def test_cli_build_validation_rejects_malformed_build_before_output(tmp_path):
    build, plan, out = validation_fixture(tmp_path, 0)
    manifest_path = build / "build.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["format"] = []
    manifest_path.write_text(json.dumps(manifest))
    result = invoke("srs-validate-build", "--build", build, "--plan", plan, "--out", out)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert not out.exists()
