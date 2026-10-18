"""Bind agent-written backend code to a reviewed SRS and package it unchanged.

This stage does not generate code, execute submitted code, or certify coverage.
The implementation map makes partial scope and local policy decisions explicit.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import tempfile

from .srs import _Checks, _read, check_srs, file_hash, load_config


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _local_file(root: Path, value: str) -> Path:
    _require(_text(value), "Implementation file path must be a nonempty string")
    path = PurePosixPath(value)
    _require(not path.is_absolute() and ".." not in path.parts and "\\" not in value
             and str(path) == value, f"Implementation path must be canonical and relative: {value}")
    target = root / value
    _require(not target.is_symlink() and not any(p.is_symlink() for p in target.parents),
             f"Implementation symlinks are not supported: {value}")
    _require(target.is_file(), f"Missing implementation file: {value}")
    return target


def validate_implementation(value: dict, config: dict, index: dict, srs: Path, root: Path) -> dict:
    fields = {"format", "name", "app_id", "route", "srs_hashes", "entrypoint", "files", "requirements", "decisions"}
    _require(isinstance(value, dict) and set(value) == fields, "Invalid implementation manifest fields")
    tracked = _read(srs / "run.json").get("format") == "rea-backend.srs-run/v2"
    _require(value["format"] == ("rea-backend.srs-implementation/v2" if tracked else "rea-backend.srs-implementation/v1"),
             "Implementation format must match the SRS generation (v1 legacy or v2 tracked)")
    _require(_text(value["name"]), "Implementation name is required")
    _require(value["app_id"] == config["app"]["id"], "Implementation App differs from the SRS input")
    _require(value["route"] == config["route"], "Implementation source/APK route differs from the SRS input")
    bindings = ["backend-srs.md", "index.json", "inventory.json"]
    if tracked:
        bindings += ["run.json", "analysis/analysis.json", "method/manifest.json"]
    expected = {name: file_hash(srs / name) for name in bindings}
    _require(value["srs_hashes"] == expected, "Implementation is bound to a different SRS; review the mapping again")
    files = value["files"]
    _require(isinstance(files, list) and files and all(_text(p) for p in files), "Implementation files required")
    _require(len(files) == len(set(files)), "Duplicate implementation files")
    _require("implementation.json" not in files and "requirements.txt" in files,
             "Declare requirements.txt; implementation.json is packaged separately")
    _require(isinstance(value["entrypoint"], str) and value["entrypoint"] in files, "Entrypoint must be a declared file")
    for filename in files:
        _local_file(root, filename)
    reqs = {r["id"]: r for r in index["requirements"]}
    capabilities = {c["id"]: c for c in index["capabilities"]}
    gaps = {g["id"]: g for g in index["gaps"]}
    rows = value["requirements"]
    _require(isinstance(rows, list), "Requirements mapping must be an array")
    mapped, active, needed_decisions = set(), set(), set()
    for row in rows:
        _require(isinstance(row, dict) and set(row) == {"id", "status", "files", "note"}, "Invalid requirement mapping")
        rid = row["id"]
        _require(isinstance(rid, str) and rid in reqs and rid not in mapped, "Unknown or duplicate mapped requirement")
        mapped.add(rid)
        _require(isinstance(row["status"], str) and row["status"] in {"implemented", "partial", "deferred"},
                 f"Invalid implementation status: {rid}")
        _require(_text(row["note"]), f"Scope and limitations must be explained: {rid}")
        refs = row["files"]
        _require(isinstance(refs, list) and all(isinstance(p, str) and p in files for p in refs)
                 and len(refs) == len(set(refs)), f"Invalid implementation file references: {rid}")
        if row["status"] != "deferred":
            _require(bool(refs), f"Implemented/partial requirements need code references: {rid}")
            active.add(rid)
            associated_gaps = set(reqs[rid]["gap_ids"])
            for cid in reqs[rid]["capability_ids"]:
                associated_gaps.update(capabilities[cid]["gap_ids"])
            needed_decisions.update(g for g in associated_gaps if gaps[g]["status"] == "open" and gaps[g]["blocking"])
    _require(mapped == set(reqs), "Map every SRS requirement, including deferred requirements")
    _require(bool(active), "Implementation must select at least one requirement")
    decisions = value["decisions"]
    _require(isinstance(decisions, list), "Decisions must be an array")
    decided = set()
    for row in decisions:
        _require(isinstance(row, dict) and set(row) == {"gap_id", "kind", "choice", "validation"}, "Invalid local decision")
        gid = row["gap_id"]
        _require(isinstance(gid, str) and gid in gaps and gid not in decided, "Unknown or duplicate decision gap")
        _require(isinstance(row["kind"], str) and row["kind"] in {"local_policy", "deferred_validation"}, "Invalid decision kind")
        _require(_text(row["choice"]) and _text(row["validation"]), "Explain each choice and its validation boundary")
        decided.add(gid)
    _require(needed_decisions <= decided, f"Active requirements have unexplained blocking gaps: {sorted(needed_decisions-decided)}")
    return {"requirements": dict(Counter(r["status"] for r in rows)), "local_decisions": len(decisions),
            "note": "Implementation statuses are author declarations, not test or Android verification results."}


def _baseline_files(srs: Path) -> list[str]:
    names = ["backend-srs.md", "index.json", "inventory.json", "run.json", "review.json"]
    if _read(srs / "run.json").get("format") == "rea-backend.srs-run/v2":
        from .method_bundle import check_method
        c = _Checks()
        names += ["method/" + name for name in check_method(c, srs / "method")]
        _require(not c.errors, "SRS method snapshot check failed: " + "; ".join(c.errors))
        analysis = _read(srs / "analysis/analysis.json")
        revision = analysis.get("revision")
        _require(type(revision) is int and revision >= 1, "Invalid frozen analysis revision")
        names += ["analysis/analysis.json"]
        names += [f"analysis/revisions/{number:08}.json" for number in range(1, revision + 1)]
    return names


def build_from_srs(config_path: Path, srs: Path, implementation: Path, out: Path) -> dict:
    """Copy a reviewed baseline and an explicitly scoped implementation to a fresh bundle."""
    for path in (config_path, srs, implementation, out):
        _require(not path.is_symlink() and not any(p.is_symlink() for p in path.absolute().parents),
                 f"Symlink paths are not supported: {path}")
    config_path, srs, implementation, out = (p.resolve() for p in (config_path, srs, implementation, out))
    _require(not out.exists(), "Output already exists; choose a new build directory")
    config = load_config(config_path)
    protected = [srs, implementation, config_path]
    protected += [(config_path.parent / i["path"]).resolve() for i in config["inputs"]]
    _require(not any(out == p or out.is_relative_to(p) for p in protected), "Output must not be inside an input directory")
    baseline_names = _baseline_files(srs)
    baseline_hashes = {name: file_hash(srs / name) for name in baseline_names}
    config_hash = file_hash(config_path)
    check = check_srs(config_path, srs, require_reviewed=True)
    _require(check["status"] == "checked", "SRS review/evidence check failed: " + "; ".join(check["errors"]))
    source_manifest = _local_file(implementation, "implementation.json")
    manifest_hash = file_hash(source_manifest)
    manifest = _read(source_manifest)
    summary = validate_implementation(manifest, config, _read(srs / "index.json"), srs, implementation)
    # Freeze bytes before copying so subsequent edits cannot silently change this build.
    data = {"implementation/" + name: _local_file(implementation, name).read_bytes() for name in manifest["files"]}
    data["implementation/implementation.json"] = source_manifest.read_bytes()
    for name in baseline_names:
        data["srs/" + name] = (srs / name).read_bytes()
    # Recheck the copied baseline against the validated hashes rather than trusting copy order.
    import hashlib
    for name, digest in baseline_hashes.items():
        _require(hashlib.sha256(data["srs/" + name]).hexdigest() == digest, "SRS changed while preparing the build")
    _require(hashlib.sha256(data["implementation/implementation.json"]).hexdigest() == manifest_hash,
             "Implementation manifest changed while preparing the build")
    data["input-config.json"] = config_path.read_bytes()
    _require(hashlib.sha256(data["input-config.json"]).hexdigest() == config_hash, "Input config changed during build")
    data["srs-check.json"] = (json.dumps(check, ensure_ascii=False, indent=2) + "\n").encode()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".srs-build-", dir=out.parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        for name, content in data.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        record = {"format": "rea-backend.srs-build/v2" if check["analysis_tracking"] == "tracked" else "rea-backend.srs-build/v1",
                  "created_at": datetime.now(timezone.utc).isoformat(),
                  "app_id": config["app"]["id"], "route": config["route"], "builder_sha256": file_hash(Path(__file__)),
                  "entrypoint": "implementation/" + manifest["entrypoint"], "scope": summary,
                  "files": {name: file_hash(staging / name) for name in sorted(data)},
                  "generation": "agent-authored code; this command validates provenance and packages files only",
                  "validation": "No implementation tests, Android checks or reference comparison run by this command."}
        (staging / "build.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staging.rename(out)
    return {"status": "built", "output": str(out), "route": config["route"], "scope": summary,
            "srs_review": check["review"], "srs_ready_for_full_implementation": check["ready_for_implementation"],
            "note": record["validation"]}
