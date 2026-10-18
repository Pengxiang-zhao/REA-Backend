"""A wheel must carry the same discovery method as a checkout installation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit
import venv
import zipfile

import pytest

from test_analysis import work_item
from test_srs import materials, read_json, write_json


ROOT = Path(__file__).resolve().parents[1]
METHOD_IDS = {
    "skill", "template", "discovery", "behavior", "format", "review",
    "requirements", "build", "android", "agent",
}


def run_checked(argv, *, cwd, env=None):
    result = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture(scope="module")
def wheel_install(tmp_path_factory):
    work = tmp_path_factory.mktemp("installed-package")
    wheels = work / "wheels"
    wheels.mkdir()
    # Building without isolation keeps this test offline; build tools are dev dependencies.
    run_checked([
        sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
        "--wheel-dir", str(wheels), str(ROOT),
    ], cwd=work)
    wheel, = wheels.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert "rea_backend/rea_android_session.mjs" in names
        assert "rea_backend/resources/skills/rea-backend/SKILL.md" in names
        assert "rea_backend/resources/skills/rea-backend/references/review.md" in names
        assert "rea_backend/resources/templates/backend-requirements.md" in names
        assert not any(name.startswith(("tests/", "examples/", "refer/")) for name in names)
    environment = work / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    clean_env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    clean_env["PYTHONNOUSERSITE"] = "1"
    run_checked([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], cwd=work, env=clean_env)
    installed = run_checked([
        str(python), "-c", "import rea_backend; print(rea_backend.__file__)",
    ], cwd=work, env=clean_env)
    location = Path(installed.stdout.strip()).resolve()
    assert location.is_relative_to(environment.resolve())
    assert not location.is_relative_to(ROOT)
    executable = environment / ("Scripts/rea-backend.exe" if os.name == "nt" else "bin/rea-backend")
    run_checked([str(executable), "--help"], cwd=work, env=clean_env)
    return python, clean_env


def test_installed_cli_freezes_default_template_and_complete_method_outside_repository(materials, wheel_install):
    python, env = wheel_install
    work = materials["root"]

    def invoke(*args):
        return run_checked([str(python), "-m", "rea_backend", *map(str, args)], cwd=work, env=env)

    analysis = work / "installed-analysis"
    invoke("srs-explore", "--config", materials["config"], "--out", analysis)
    updates = work / "updates.json"
    write_json(updates, [work_item(materials, state="answered")])
    invoke("srs-analysis-update", "--config", materials["config"], "--analysis", analysis,
           "--updates", updates, "--expected-revision", 1)
    # No --template or --method-manifest: both must come from the installed wheel.
    invoke("srs-init", "--config", materials["config"], "--analysis", analysis, "--out", materials["out"])
    bundle = materials["out"]
    run = read_json(bundle / "run.json")
    method = read_json(bundle / "method/manifest.json")
    assert run["format"] == "rea-backend.srs-run/v2"
    assert run["analysis_tracking"] == "tracked"
    assert method["version"] == "rea-backend/v1"
    assert {item["id"] for item in method["files"]} == METHOD_IDS
    for item in method["files"]:
        content = (bundle / "method" / item["path"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == item["sha256"]
        assert len(content) == item["bytes"]
        assert "site-packages" in item["source"]
        assert not Path(item["source"]).is_relative_to(ROOT)
    template = next(item for item in method["files"] if item["id"] == "template")
    assert run["template_sha256"] == template["sha256"]
    assert "<App name>" not in (bundle / "backend-srs.md").read_text()
    assert "Reader" in (bundle / "backend-srs.md").read_text()


def test_exported_skill_keeps_local_reference_closure(wheel_install, tmp_path):
    python, env = wheel_install
    exported = tmp_path / "workspace"
    run_checked([str(python), "-m", "rea_backend", "init-workspace", "--out", str(exported)],
                cwd=tmp_path, env=env)
    skill = exported / "skills/rea-backend/SKILL.md"
    assert skill.is_file()
    queue = [skill]
    seen = set()
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        for href in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            parsed = urlsplit(href)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target = (path.parent / unquote(parsed.path)).resolve()
            assert target.is_relative_to(exported.resolve()), (path, href)
            assert target.is_file(), (path, href)
            if target.suffix == ".md":
                queue.append(target)
    assert exported / "docs/srs-format.md" in seen
    assert exported / "docs/srs-to-backend.md" in seen
    assert exported / "skills/rea-backend/references/review.md" in seen
