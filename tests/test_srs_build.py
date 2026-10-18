"""The handoff must preserve provenance without hiding partial implementation."""
import hashlib
import json

import pytest

from rea_backend.srs_build import build_from_srs
from test_srs import bundle, materials, mutate_index, reviewed, write_json


@pytest.fixture
def implementation(bundle):
    reviewed(bundle)
    root = bundle["root"] / "implementation"
    root.mkdir()
    (root / "app.py").write_text("raise RuntimeError('Packaging must never execute submitted code')\n")
    (root / "requirements.txt").write_text("# Synthetic fixture has no dependencies.\n")
    manifest = {
        "format": "rea-backend.srs-implementation/v1", "name": "reader-pilot", "app_id": "reader", "route": "source",
        "srs_hashes": {n: hashlib.sha256((bundle["out"] / n).read_bytes()).hexdigest()
                       for n in ("backend-srs.md", "index.json", "inventory.json")},
        "entrypoint": "app.py", "files": ["app.py", "requirements.txt"],
        "requirements": [{"id": "FR-articles-001", "status": "partial", "files": ["app.py"],
                          "note": "Synthetic code; no claim of runtime support."}], "decisions": [],
    }
    write_json(root / "implementation.json", manifest)
    return {**bundle, "implementation": root, "manifest": manifest, "build": bundle["root"] / "built"}


def build(item):
    return build_from_srs(item["config"], item["out"], item["implementation"], item["build"])


def save_manifest(item):
    write_json(item["implementation"] / "implementation.json", item["manifest"])


def test_packages_exact_bytes_with_route_and_hashes_without_executing_code(implementation):
    result = build(implementation)
    assert result["status"] == "built"
    assert result["route"] == "source"
    assert result["scope"]["requirements"] == {"partial": 1}
    output = implementation["build"]
    record = json.loads((output / "build.json").read_text())
    for name, digest in record["files"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    assert (output / "implementation/app.py").read_bytes() == (implementation["implementation"] / "app.py").read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        build(implementation)


@pytest.mark.parametrize("change", [
    lambda m: m.update(route="apk"),
    lambda m: m.update(app_id="other"),
    lambda m: m["srs_hashes"].update({"backend-srs.md": "0" * 64}),
    lambda m: m.update(requirements=[]),
    lambda m: m["requirements"].append(dict(m["requirements"][0])),
    lambda m: m["requirements"][0].update(files=[]),
    lambda m: m["files"].append("../outside.py"),
    lambda m: m["files"].append("missing.py"),
    lambda m: m.update(entrypoint="undeclared.py"),
])
def test_rejects_mixed_routes_stale_baselines_and_incomplete_mapping(implementation, change):
    change(implementation["manifest"])
    save_manifest(implementation)
    with pytest.raises(ValueError):
        build(implementation)
    assert not implementation["build"].exists()


def test_requires_current_independent_review_and_unchanged_source(implementation):
    implementation["source"].write_text("changed after review\n")
    with pytest.raises(ValueError, match="SRS review/evidence"):
        build(implementation)


@pytest.mark.parametrize("through_capability", [False, True])
def test_open_blocking_gap_requires_explicit_policy_without_rewriting_srs(implementation, through_capability):
    def add_gap(index):
        index["gaps"] = [{"id": "G-boundary", "question": "Which boundary?", "impact": "List membership",
                          "blocking": True, "status": "open", "resolution": "", "evidence_ids": []}]
        collection = "capabilities" if through_capability else "requirements"
        index[collection][0]["gap_ids"] = ["G-boundary"]
    mutate_index(implementation, add_gap)
    reviewed(implementation)
    implementation["manifest"]["srs_hashes"]["index.json"] = hashlib.sha256((implementation["out"] / "index.json").read_bytes()).hexdigest()
    save_manifest(implementation)
    with pytest.raises(ValueError, match="unexplained blocking gaps"):
        build(implementation)
    implementation["manifest"]["decisions"] = [{"gap_id": "G-boundary", "kind": "local_policy",
                                               "choice": "Inclusive lower bound for this mock.",
                                               "validation": "No original-server equivalence claim."}]
    save_manifest(implementation)
    result = build(implementation)
    assert result["srs_ready_for_full_implementation"] is False
    assert json.loads((implementation["out"] / "index.json").read_text())["gaps"][0]["status"] == "open"


def test_rejects_implementation_symlink_and_output_nested_under_input(implementation):
    app = implementation["implementation"] / "app.py"
    app.unlink()
    app.symlink_to(implementation["source"])
    with pytest.raises(ValueError, match="symlink"):
        build(implementation)
    app.unlink()
    app.write_text("# Restored fixture\n")
    implementation["build"] = implementation["source"].parent / "output"
    with pytest.raises(ValueError, match="inside an input"):
        build(implementation)


def test_detects_review_mutated_during_check(implementation, monkeypatch):
    import rea_backend.srs_build as module
    original = module.check_srs
    def changed_review(*args, **kwargs):
        result = original(*args, **kwargs)
        (implementation["out"] / "review.json").write_text("{}\n")
        return result
    monkeypatch.setattr(module, "check_srs", changed_review)
    with pytest.raises(ValueError, match="SRS changed"):
        build(implementation)
    assert not implementation["build"].exists()


def tracked_implementation(materials):
    from test_analysis import tracked_bundle
    tracked_bundle(materials)
    reviewed(materials)
    root = materials["root"] / "implementation"
    root.mkdir()
    (root / "app.py").write_text("raise RuntimeError('Never execute packaged fixture')\n")
    (root / "requirements.txt").write_text("# Synthetic fixture\n")
    manifest = {
        "format": "rea-backend.srs-implementation/v2", "name": "reader-pilot", "app_id": "reader", "route": "source",
        "srs_hashes": {n: hashlib.sha256((materials["out"] / n).read_bytes()).hexdigest() for n in (
            "backend-srs.md", "index.json", "inventory.json", "run.json", "analysis/analysis.json", "method/manifest.json")},
        "entrypoint": "app.py", "files": ["app.py", "requirements.txt"],
        "requirements": [{"id": "FR-articles-001", "status": "partial", "files": ["app.py"], "note": "Synthetic scope."}],
        "decisions": [],
    }
    write_json(root / "implementation.json", manifest)
    return {**materials, "implementation": root, "manifest": manifest, "build": materials["root"] / "built"}


def test_tracked_build_packages_all_frozen_provenance(materials):
    item = tracked_implementation(materials)
    assert build(item)["status"] == "built"
    record = json.loads((item["build"] / "build.json").read_text())
    assert record["format"] == "rea-backend.srs-build/v2"
    assert "srs/analysis/revisions/00000001.json" in record["files"]
    assert "srs/analysis/revisions/00000002.json" in record["files"]
    assert "srs/method/files/skill.md" in record["files"]
    for name, digest in record["files"].items():
        assert hashlib.sha256((item["build"] / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("mutation", ["legacy", "missing_method", "stale_analysis"])
def test_tracked_implementation_requires_current_provenance_bindings(materials, mutation):
    item = tracked_implementation(materials)
    if mutation == "legacy":
        item["manifest"]["format"] = "rea-backend.srs-implementation/v1"
    elif mutation == "missing_method":
        del item["manifest"]["srs_hashes"]["method/manifest.json"]
    else:
        item["manifest"]["srs_hashes"]["analysis/analysis.json"] = "0" * 64
    save_manifest(item)
    with pytest.raises(ValueError, match="format|different SRS"):
        build(item)
    assert not item["build"].exists()


def test_tracked_build_detects_method_mutation_during_check(materials, monkeypatch):
    import rea_backend.srs_build as module
    item = tracked_implementation(materials)
    original = module.check_srs
    def changed_method(*args, **kwargs):
        result = original(*args, **kwargs)
        (item["out"] / "method/files/skill.md").write_text("changed during packaging\n")
        return result
    monkeypatch.setattr(module, "check_srs", changed_method)
    with pytest.raises(ValueError, match="SRS changed"):
        build(item)
    assert not item["build"].exists()
