"""Freeze an explicit list of normative method files, never a directory tree."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from .srs import _Checks, _read
from .resource_files import resource_root

METHOD_VERSION = "rea-backend/v1"
REQUIRED_IDS = {"skill", "template", "discovery", "behavior", "format", "review",
                "requirements", "build", "android", "agent"}
# Deliberately excludes docs/results, reference applications and generated SRS.
DEFAULT_FILES = (
    ("skill", "skills/rea-backend/SKILL.md"),
    ("template", "templates/backend-requirements.md"),
    ("discovery", "docs/requirements-discovery.md"),
    ("behavior", "docs/apk-behavior-tracing.md"),
    ("format", "docs/srs-format.md"),
    ("review", "skills/rea-backend/references/review.md"),
    ("requirements", "docs/backend-requirements.md"),
    ("build", "docs/srs-to-backend.md"),
    ("android", "docs/android-run.md"),
    ("agent", "docs/srs-agent.md"),
)


def prepare_method(template: Path, manifest: Path | None = None) -> dict[str, bytes]:
    """Return immutable bytes to write under bundle/method/."""
    root = resource_root()
    spec = {"format": "rea-backend.srs-method-spec/v1", "version": METHOD_VERSION,
            "files": [{"id": iid, "path": path} for iid, path in DEFAULT_FILES]}
    if manifest is not None:
        spec = _read(manifest)
        root = manifest.resolve().parent
    c = _Checks()
    c.obj(spec, "method spec", {"format", "version", "files"})
    c.check(spec.get("format") == "rea-backend.srs-method-spec/v1", "method spec: invalid format")
    c.string(spec.get("version"), "method spec.version")
    rows = c.records(spec.get("files"), "method spec.files", {"id", "path"}, nonempty=True)
    c.check(REQUIRED_IDS <= rows.keys(), f"method spec: required IDs {sorted(REQUIRED_IDS)}")
    data, files = {}, []
    for iid, row in rows.items():
        if not c.string(row.get("path"), f"method spec.{iid}.path"):
            continue
        source = template if iid == "template" else root / row["path"]
        if not c.check(not source.is_symlink() and not any(p.is_symlink() for p in source.absolute().parents),
                       f"method spec.{iid}: symlinks not supported"):
            continue
        if not c.check(source.is_file(), f"method spec.{iid}: file required: {source}"):
            continue
        content = source.read_bytes()
        relative = f"files/{iid}{source.suffix}"
        data[relative] = content
        files.append({"id": iid, "path": relative, "source": str(source.resolve()),
                      "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)})
    if c.errors:
        raise ValueError("Invalid method specification:\n" + "\n".join(c.errors))
    frozen = {"format": "rea-backend.srs-method/v1", "version": spec["version"], "files": files}
    data["manifest.json"] = (json.dumps(frozen, ensure_ascii=False, indent=2) + "\n").encode()
    return data


def check_method(c: _Checks, directory: Path) -> list[str]:
    """Check only the frozen bundle; repository upgrades are irrelevant."""
    names = ["manifest.json"]
    try:
        c.check(not directory.is_symlink(), "method: symlink directory not supported")
        manifest = directory / "manifest.json"
        if not c.check(not manifest.is_symlink(), "method: symlink manifest not supported"):
            return names
        value = c.obj(_read(manifest), "method", {"format", "version", "files"})
        c.check(value.get("format") == "rea-backend.srs-method/v1", "method: invalid format")
        c.string(value.get("version"), "method.version")
        rows = c.records(value.get("files"), "method.files", {"id", "path", "source", "sha256", "bytes"}, nonempty=True)
        c.check(REQUIRED_IDS <= rows.keys(), f"method: missing required file IDs {sorted(REQUIRED_IDS - rows.keys())}")
        for iid, row in rows.items():
            relative = row.get("path")
            if not c.string(relative, f"method.{iid}.path"):
                continue
            path = PurePosixPath(relative)
            if not c.check(not path.is_absolute() and ".." not in path.parts and "\\" not in relative
                           and str(path) == relative and path.parts[0] == "files", f"method.{iid}: unsafe file path"):
                continue
            c.check(relative not in names, f"method.{iid}: duplicate file path")
            names.append(relative)
            target = directory / relative
            c.string(row.get("source"), f"method.{iid}.source")
            c.sha(row.get("sha256"), f"method.{iid}.sha256")
            c.check(type(row.get("bytes")) is int and row["bytes"] >= 0, f"method.{iid}.bytes: integer required")
            if not c.check(not target.is_symlink() and not any(p.is_symlink() for p in target.parents),
                           f"method.{iid}: symlinks not supported"):
                continue
            if c.check(target.is_file(), f"method.{iid}: missing snapshot file"):
                content = target.read_bytes()
                c.check(hashlib.sha256(content).hexdigest() == row.get("sha256") and len(content) == row.get("bytes"),
                        f"method.{iid}: frozen method file changed")
    except (OSError, ValueError) as exc:
        c.check(False, f"method: {exc}")
    return names
