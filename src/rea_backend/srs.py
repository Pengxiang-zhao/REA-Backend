"""Prepare and check evidence-backed, app-wide SRS bundles.

The agent authors the prose and index. These deterministic tools never call a
model, infer business rules, or certify semantic completeness.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from . import __version__
from .resource_files import resource_file

ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
SHA = re.compile(r"^[0-9a-f]{64}$")
AREAS = {"ui", "background", "protocol", "data_and_dependencies"}
KINDS = {"client_source", "client_dependency", "client_apk", "decoded_apk",
         "rea_evidence", "public_docs", "client_trace", "environment_spec", "reference"}
IGNORED = {".git", "__pycache__", ".DS_Store"}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{path}: duplicate JSON key {key}")
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class _Checks:
    def __init__(self):
        self.errors: list[str] = []

    def check(self, condition, message):
        if not condition:
            self.errors.append(message)
        return bool(condition)

    def obj(self, value, label, required, optional=()):
        if not self.check(isinstance(value, dict), f"{label}: object required"):
            return {}
        self.check(not (set(required) - value.keys()), f"{label}: missing fields {sorted(set(required) - value.keys())}")
        self.check(not (value.keys() - set(required) - set(optional)), f"{label}: unknown fields {sorted(value.keys() - set(required) - set(optional))}")
        return value

    def string(self, value, label, empty=False):
        return self.check(isinstance(value, str) and (empty or bool(value.strip())), f"{label}: {'string' if empty else 'non-empty string'} required")

    def enum(self, value, allowed, label):
        return self.check(isinstance(value, str) and value in allowed, f"{label}: expected one of {sorted(allowed)}")

    def identity(self, value, label):
        return self.check(isinstance(value, str) and bool(ID.fullmatch(value)), f"{label}: stable ID required")

    def sha(self, value, label):
        return self.check(isinstance(value, str) and bool(SHA.fullmatch(value)), f"{label}: SHA-256 required")

    def strings(self, value, label, nonempty=False):
        if not self.check(isinstance(value, list), f"{label}: array required"):
            return []
        if nonempty:
            self.check(bool(value), f"{label}: nonempty array required")
        good = [v for i, v in enumerate(value) if self.string(v, f"{label}[{i}]")]
        self.check(len(set(good)) == len(good), f"{label}: duplicate values")
        return good

    def refs(self, value, targets, label, nonempty=False):
        result = self.strings(value, label, nonempty)
        for rid in result:
            self.check(rid in targets, f"{label}: unknown reference {rid}")
        return result

    def records(self, value, label, fields, optional=(), nonempty=False):
        if not self.check(isinstance(value, list), f"{label}: array required"):
            return {}
        if nonempty:
            self.check(bool(value), f"{label}: nonempty array required")
        records = {}
        for i, item in enumerate(value):
            item = self.obj(item, f"{label}[{i}]", fields, optional)
            rid = item.get("id")
            if self.identity(rid, f"{label}[{i}].id"):
                if self.check(rid not in records, f"{label}: duplicate ID {rid}"):
                    records[rid] = item
        return records


def load_config(path: Path) -> dict:
    c = _Checks()
    config = c.obj(_read(path), "config", {"format", "app", "route", "context", "inputs", "environment"})
    c.check(config.get("format") == "rea-backend.srs-config/v1", "config.format: expected rea-backend.srs-config/v1")
    app = c.obj(config.get("app"), "app", {"id", "name", "version", "platform", "variant"})
    c.identity(app.get("id"), "app.id")
    for key in ("name", "version", "platform", "variant"):
        c.string(app.get(key), f"app.{key}")
    c.enum(config.get("route"), {"source", "apk"}, "route")
    context = c.obj(config.get("context"), "context", {"mode", "notes"})
    c.enum(context.get("mode"), {"client_only", "reference_assisted"}, "context.mode")
    c.string(context.get("notes"), "context.notes")
    env = c.obj(config.get("environment"), "environment", {"goals", "constraints"})
    c.strings(env.get("goals"), "environment.goals", True)
    c.strings(env.get("constraints"), "environment.constraints")
    inputs = c.records(config.get("inputs"), "inputs", {"id", "kind", "path", "version", "access", "complete", "limitations", "exclude"}, {"sha256"}, True)
    for iid, item in inputs.items():
        c.enum(item.get("kind"), KINDS, f"{iid}.kind")
        c.enum(item.get("access"), {"generation", "excluded"}, f"{iid}.access")
        for key in ("path", "version"):
            c.string(item.get(key), f"{iid}.{key}")
        c.check(type(item.get("complete")) is bool, f"{iid}.complete: boolean required")
        c.strings(item.get("limitations"), f"{iid}.limitations", item.get("complete") is False)
        c.strings(item.get("exclude"), f"{iid}.exclude")
        if "sha256" in item:
            c.sha(item["sha256"], f"{iid}.sha256")
        if item.get("access") == "generation":
            if context.get("mode") == "client_only":
                c.check(item.get("kind") != "reference", f"{iid}: reference input forbidden in client_only generation")
            if config.get("route") == "apk":
                c.check(item.get("kind") not in ("client_source", "client_dependency"), f"{iid}: source input forbidden in APK route")
    primary = "client_source" if config.get("route") == "source" else "client_apk"
    c.check(any(i.get("kind") == primary and i.get("access") == "generation" for i in inputs.values()), f"inputs: route requires generation {primary}")
    if c.errors:
        raise ValueError("Invalid SRS config:\n" + "\n".join(c.errors))
    generation_roots = [(i["id"], _root(path, i)) for i in inputs.values() if i["access"] == "generation"]
    excluded_roots = [(i["id"], _root(path, i)) for i in inputs.values() if i["access"] == "excluded"]
    for gid, generation in generation_roots:
        for eid, excluded in excluded_roots:
            if generation.is_relative_to(excluded) or excluded.is_relative_to(generation):
                raise ValueError(f"Input overlap: generation {gid} and excluded {eid} must have disjoint paths")
    return config


def _root(config_path: Path, item: dict) -> Path:
    raw = config_path.parent / item["path"]
    # resolve() alone would silently follow an out-of-scope symlink.
    if raw.is_symlink() or any(parent.is_symlink() for parent in raw.absolute().parents):
        raise ValueError(f"{item['id']}: symlink input path is not supported")
    return raw.resolve()


def _snapshot(config_path: Path, config: dict) -> dict:
    inputs = []
    for item in config["inputs"]:
        if item["access"] != "generation":
            continue
        root = _root(config_path, item)
        if not root.exists():
            raise ValueError(f"Missing input {item['id']}: {root}")
        files = []

        def add(path, relative):
            if path.is_symlink():
                raise ValueError(f"{item['id']}: symlink is not supported: {relative}")
            if not path.is_file():
                raise ValueError(f"{item['id']}: not a regular file: {relative}")
            files.append({"path": relative, "sha256": file_hash(path), "bytes": path.stat().st_size})

        def walk(directory):
            for path in sorted(directory.iterdir()):
                relative = path.relative_to(root).as_posix()
                if path.name in IGNORED or any(fnmatch.fnmatchcase(relative, pattern) for pattern in item["exclude"]):
                    continue
                if path.is_symlink():
                    raise ValueError(f"{item['id']}: symlink is not supported: {relative}")
                if path.is_dir():
                    walk(path)
                else:
                    add(path, relative)
        if root.is_dir():
            if "sha256" in item:
                raise ValueError(f"{item['id']}: sha256 is only supported for single-file inputs")
            walk(root)
        else:
            add(root, root.name)
            if "sha256" in item and files[0]["sha256"] != item["sha256"]:
                raise ValueError(f"{item['id']}: expected input sha256 does not match")
        if not files:
            raise ValueError(f"{item['id']}: no files in input after exclusions")
        inputs.append({"id": item["id"], "kind": item["kind"], "version": item["version"],
                       "complete": item["complete"], "limitations": item["limitations"],
                       "exclude": item["exclude"], "files": sorted(files, key=lambda f: f["path"])})
    return {"format": "rea-backend.srs-inventory/v1", "config_sha256": file_hash(config_path),
            "ignored_names": sorted(IGNORED), "inputs": inputs}


def initialize_srs(config_path: Path, out: Path, template: Path | None = None, *,
                   analysis: Path | None = None, method_manifest: Path | None = None) -> dict:
    config_path, out = config_path.resolve(), out.resolve()
    config = load_config(config_path)
    for item in config["inputs"]:
        if item["access"] == "generation":
            root = _root(config_path, item)
            if out == root or out.is_relative_to(root):
                raise ValueError("SRS output cannot be inside an input")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError(f"SRS output must be an empty directory: {out}")
    if template is None:
        template = resource_file("templates/backend-requirements.md")
    template = template.resolve()
    frozen_analysis, frozen_method = {}, {}
    if method_manifest is not None and analysis is None:
        raise ValueError("--method-manifest requires tracked --analysis initialization")
    if analysis is not None:
        from .analysis import _lock, check_analysis
        from .method_bundle import prepare_method
        analysis = analysis.resolve()
        if out == analysis or out.is_relative_to(analysis) or analysis.is_relative_to(out):
            raise ValueError("SRS output and analysis workspace must be separate directories")
        with _lock(analysis):
            report = check_analysis(config_path, analysis, require_settled=True)
            if report["status"] != "checked":
                raise ValueError("Analysis is not settled:\n" + "\n".join(report["errors"]))
            frozen_analysis = {"analysis.json": (analysis / "analysis.json").read_bytes()}
            for number in range(1, report["revision"] + 1):
                relative = f"revisions/{number:08}.json"
                frozen_analysis[relative] = (analysis / relative).read_bytes()
        frozen_method = prepare_method(template, method_manifest)
    body = template.read_text(encoding="utf-8").replace("<App name>", config["app"]["name"])
    # Prefer frozen resources so tracked drafts remain readable after delivery.
    frozen_links = {}
    if frozen_method:
        for row in json.loads(frozen_method["manifest.json"])["files"]:
            frozen_links[Path(row["source"]).resolve()] = "method/" + row["path"]
    # Preserve other relative links when the draft is created elsewhere.
    import os

    def template_link(match):
        relative, separator, fragment = match.group(1).partition("#")
        source = (template.parent / relative).resolve()
        target = frozen_links.get(source, Path(os.path.relpath(source, out)).as_posix())
        return "](" + target + separator + fragment + ")"

    body = re.sub(r"\]\((\.\.?/[^)]+)\)", template_link, body)
    inventory = _snapshot(config_path, config)
    if frozen_analysis:
        # Bind the captured work list to the exact input inventory that is about
        # to be frozen, including material collected during exploration.
        from .analysis import _validate
        freeze_checks = _Checks()
        available = {(i["id"], f["path"]): f for i in inventory["inputs"] for f in i["files"]}
        _validate(freeze_checks, json.loads(frozen_analysis["analysis.json"]), config_path, config,
                  require_settled=True, available=available)
        previous = None
        for relative, content in frozen_analysis.items():
            if not relative.startswith("revisions/"):
                continue
            revision = json.loads(content)
            freeze_checks.check(revision.get("previous_sha256") == previous,
                                "analysis: history changed while preparing the freeze")
            previous = hashlib.sha256(content).hexdigest()
        freeze_checks.check(previous == hashlib.sha256(frozen_analysis["analysis.json"]).hexdigest(),
                            "analysis: work list changed while preparing the freeze")
        if freeze_checks.errors:
            raise ValueError("Analysis freeze failed:\n" + "\n".join(freeze_checks.errors))
    index = {"format": "rea-backend.srs-index/v1", "app_id": config["app"]["id"],
             "scope": "app-wide", "status": "draft",
             "discovery": [{"area": area, "summary": "", "evidence_ids": [], "gap_ids": []} for area in sorted(AREAS)],
             "capabilities": [], "requirements": [], "evidence": [], "gaps": [], "limitations": []}
    if frozen_analysis:
        registered_gaps = {}
        for item in json.loads(frozen_analysis["analysis.json"])["items"]:
            if item["state"] != "blocked":
                continue
            for gid in item["gap_ids"]:
                registered_gaps.setdefault(gid, {"id": gid, "question": item["question"], "impact": item["finding"],
                    "blocking": True, "status": "open", "resolution": "", "evidence_ids": []})
                row = next(d for d in index["discovery"] if d["area"] == item["area"])
                if gid not in row["gap_ids"]:
                    row["gap_ids"].append(gid)
        index["gaps"] = list(registered_gaps.values())
    out.mkdir(parents=True, exist_ok=True)
    _write(out / "inventory.json", inventory)
    _write(out / "index.json", index)
    (out / "backend-srs.md").write_text(body, encoding="utf-8")
    skill = resource_file("skills/rea-backend/SKILL.md")
    run = {"format": "rea-backend.srs-run/v2" if analysis is not None else "rea-backend.srs-run/v1", "tool_version": __version__,
           "created_at": datetime.now(timezone.utc).isoformat(), "tool_sha256": file_hash(Path(__file__)),
           "config_sha256": file_hash(config_path),
           "inventory_sha256": file_hash(out / "inventory.json"), "template_sha256": file_hash(template),
           "skill_sha256": file_hash(skill),
           "analysis_tracking": "tracked" if analysis is not None else "legacy/untracked"}
    if analysis is not None:
        for directory, data in (("analysis", frozen_analysis), ("method", frozen_method)):
            for relative, content in data.items():
                target = out / directory / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        run["analysis_sha256"] = file_hash(out / "analysis/analysis.json")
        run["method_sha256"] = file_hash(out / "method/manifest.json")
        frozen_manifest = _read(out / "method/manifest.json")
        run["skill_sha256"] = next(r["sha256"] for r in frozen_manifest["files"] if r["id"] == "skill")
    _write(out / "run.json", run)
    return {"status": "initialized", "output": str(out),
            "input_files": sum(len(i["files"]) for i in inventory["inputs"]),
            "analysis_tracking": run["analysis_tracking"],
            "note": "Scaffold only. Author the SRS and index, preserve unresolved analysis gaps, and obtain independent review."
                    if analysis is not None else "Legacy/untracked scaffold: no resumable analysis or complete method snapshot is recorded."}


def check_srs(config_path: Path, bundle: Path, require_reviewed: bool = False) -> dict:
    config_path, bundle = config_path.resolve(), bundle.resolve()
    config = load_config(config_path)
    c = _Checks()
    warnings = []
    inputs = {i["id"]: i for i in config["inputs"] if i["access"] == "generation"}
    inventory = _read(bundle / "inventory.json")
    run = _read(bundle / "run.json")
    tracked = run.get("format") == "rea-backend.srs-run/v2"
    c.check(run.get("format") in ("rea-backend.srs-run/v1", "rea-backend.srs-run/v2"), "run: invalid format")
    c.check(run.get("config_sha256") == file_hash(config_path), "run: config changed; initialize a new bundle")
    c.check(run.get("inventory_sha256") == file_hash(bundle / "inventory.json"), "run: inventory changed after initialization")
    # The fresh snapshot is authoritative for lookups, never the supplied manifest.
    current = _snapshot(config_path, config)
    c.check(inventory == current, "inventory: input files or metadata changed; initialize a new bundle")
    available = {(i["id"], f["path"]): f for i in current["inputs"] for f in i["files"]}
    analysis_items = {}
    analysis_report = None
    sampled_review_required = False
    if tracked:
        from .analysis import check_analysis
        from .method_bundle import check_method
        c.check(run.get("analysis_tracking") == "tracked", "run: v2 requires tracked analysis")
        for key, relative in (("analysis_sha256", "analysis/analysis.json"), ("method_sha256", "method/manifest.json")):
            target = bundle / relative
            if c.check(target.is_file() and not target.is_symlink(), f"run: missing or unsafe {relative}"):
                c.check(run.get(key) == file_hash(target), f"run: {relative} changed after initialization")
        check_method(c, bundle / "method")
        analysis_report = check_analysis(config_path, bundle / "analysis", require_settled=True, available=available)
        c.errors.extend(analysis_report["errors"])
        frozen_analysis = _read(bundle / "analysis/analysis.json")
        sampled_review_required = frozen_analysis.get("format") == "rea-backend.analysis/v3"
        if analysis_report["status"] == "checked":
            analysis_items = {i["id"]: i for i in frozen_analysis["items"]}
        try:
            method_rows = {r["id"]: r for r in _read(bundle / "method/manifest.json")["files"]}
            for iid, key in (("template", "template_sha256"), ("skill", "skill_sha256")):
                c.check(run.get(key) == method_rows.get(iid, {}).get("sha256"), f"run: {key} differs from frozen method")
        except (OSError, ValueError, KeyError, TypeError):
            c.check(False, "run: invalid frozen method binding")
    else:
        warnings.append("Legacy/untracked bundle: discovery work history and complete method snapshot were not recorded.")
    provenance_valid = not c.errors
    doc_path, index_path = bundle / "backend-srs.md", bundle / "index.json"
    body = doc_path.read_text(encoding="utf-8")

    def has_prose(text):
        text = re.sub(r"<!--[\s\S]*?-->", "", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"^\s*#{1,6}\s+.*$", "", text, flags=re.M)

        def populated_table(match):
            rows = [line.strip().strip("|").split("|") for line in match.group().splitlines() if line.strip()]
            if len(rows) > 1 and all(re.fullmatch(r"\s*:?-+:?\s*", cell) for cell in rows[1]):
                if not any(re.search(r"\w", cell) for row in rows[2:] for cell in row):
                    return ""
            return match.group()

        text = re.sub(r"(?:^[ \t]*\|[^\n]*(?:\n|$))+", populated_table, text, flags=re.M)
        return bool(re.search(r"\w", text))

    def section(pattern, label):
        match = re.search(pattern, body, re.M)
        if c.check(match is not None, f"document: missing {label}"):
            tail = body[match.end():]
            following = re.search(r"^##\s+", tail, re.M)
            content = tail[:following.start()] if following else tail
            c.check(has_prose(content), f"document: empty {label}")

    for number in range(1, 11):
        section(rf"^##[ \t]+{number}\.[ \t]+[^\n]+", f"section {number}")
    for letter in "ABC":
        section(rf"^##[ \t]+Appendix[ \t]+{letter}[. \t][^\n]*", f"appendix {letter}")
    for placeholder in ("<App name>", "<Module name>", "<FR-MODULE-NNN>", "<CAP-...>", "<NFR-...>", "<EXT-...>"):
        c.check(placeholder not in body, f"document: unfilled template placeholder {placeholder}")
    anchors = re.findall(r'<a\s+id="([A-Za-z][A-Za-z0-9_.:-]*)"\s*></a>', body)
    c.check(len(anchors) == len(set(anchors)), "document: duplicate anchors")
    index = c.obj(_read(index_path), "index", {"format", "app_id", "scope", "status", "discovery", "capabilities", "requirements", "evidence", "gaps", "limitations"})
    c.check(index.get("format") == "rea-backend.srs-index/v1", "index.format: expected rea-backend.srs-index/v1")
    c.check(index.get("app_id") == config["app"]["id"], "index.app_id: config mismatch")
    c.check(index.get("scope") == "app-wide", "index.scope: expected app-wide")
    c.enum(index.get("status"), {"draft", "reviewed"}, "index.status")
    limits = c.strings(index.get("limitations"), "limitations")
    evidence = c.records(index.get("evidence"), "evidence", {"id", "input_id", "path", "sha256", "note"}, {"start_line", "end_line"})
    gaps = c.records(index.get("gaps"), "gaps", {"id", "question", "impact", "blocking", "status", "resolution", "evidence_ids"})
    caps = c.records(index.get("capabilities"), "capabilities", {"id", "title", "module", "trigger", "execution", "backend_responsibility", "analysis", "disposition", "reason", "evidence_ids", "requirement_ids", "gap_ids"}, nonempty=True)
    reqs = c.records(index.get("requirements"), "requirements", {"id", "title", "kind", "status", "statement", "acceptance", "basis", "anchor", "capability_ids", "evidence_ids", "gap_ids"}, nonempty=True)
    all_ids = list(evidence) + list(gaps) + list(caps) + list(reqs)
    c.check(len(all_ids) == len(set(all_ids)), "index: IDs must be globally unique")
    for eid, item in evidence.items():
        c.string(item.get("note"), f"{eid}.note")
        iid, relative = item.get("input_id"), item.get("path")
        if not c.check(isinstance(iid, str) and iid in inputs, f"{eid}: evidence input must be generation-visible"):
            continue
        if not c.string(relative, f"{eid}.path"):
            continue
        path = PurePosixPath(relative)
        safe = not path.is_absolute() and ".." not in path.parts and "\\" not in relative and str(path) == relative
        if not c.check(safe, f"{eid}: evidence path must be canonical and relative"):
            continue
        entry = available.get((iid, relative))
        if not c.check(entry is not None, f"{eid}: file absent from input inventory: {relative}"):
            continue
        c.sha(item.get("sha256"), f"{eid}.sha256")
        c.check(item.get("sha256") == entry["sha256"], f"{eid}: evidence sha256 mismatch")
        if "start_line" in item or "end_line" in item:
            start, end = item.get("start_line"), item.get("end_line")
            valid = type(start) is int and type(end) is int and 1 <= start <= end
            if c.check(valid, f"{eid}: invalid start_line/end_line pair"):
                root = _root(config_path, inputs[iid])
                source = root / relative if root.is_dir() else root
                try:
                    lines = len(source.read_text(encoding="utf-8").splitlines())
                    c.check(end <= lines, f"{eid}: evidence line range exceeds file ({lines} lines)")
                except UnicodeError:
                    c.check(False, f"{eid}: line evidence requires UTF-8 text")
    for gid, item in gaps.items():
        for key in ("question", "impact"):
            c.string(item.get(key), f"{gid}.{key}")
        c.enum(item.get("status"), {"open", "resolved"}, f"{gid}.status")
        c.check(type(item.get("blocking")) is bool, f"{gid}.blocking: boolean required")
        c.string(item.get("resolution"), f"{gid}.resolution", item.get("status") != "resolved")
        c.refs(item.get("evidence_ids"), evidence, f"{gid}.evidence_ids")
    for iid, item in analysis_items.items():
        for gid in item["gap_ids"]:
            c.check(gid in gaps, f"analysis {iid}: unknown SRS gap reference {gid}")
            if item["state"] == "blocked" and gid in gaps:
                c.check(gaps[gid].get("status") == "open", f"analysis {iid}: blocked item must retain open gap {gid}")
    cap_refs, req_refs = {}, {}
    for cid, item in caps.items():
        for key in ("title", "module", "trigger", "backend_responsibility", "reason"):
            c.string(item.get(key), f"{cid}.{key}")
        execution = c.strings(item.get("execution"), f"{cid}.execution", True)
        for place in execution:
            c.enum(place, {"backend", "client", "external", "unknown"}, f"{cid}.execution")
        c.enum(item.get("analysis"), {"analyzed", "candidate", "blocked"}, f"{cid}.analysis")
        c.enum(item.get("disposition"), {"planned", "deferred", "client_only", "external", "undecided"}, f"{cid}.disposition")
        er = c.refs(item.get("evidence_ids"), evidence, f"{cid}.evidence_ids")
        gr = c.refs(item.get("gap_ids"), gaps, f"{cid}.gap_ids")
        cap_refs[cid] = c.refs(item.get("requirement_ids"), reqs, f"{cid}.requirement_ids",
                               "backend" in execution and item.get("analysis") == "analyzed")
        c.check(bool(er or gr), f"{cid}: evidence or gap required")
        if item.get("analysis") in ("candidate", "blocked") or "unknown" in execution:
            c.check(any(gaps[g].get("status") == "open" for g in gr if g in gaps), f"{cid}: unresolved capability needs an open gap")
        if item.get("disposition") == "client_only":
            c.check(execution == ["client"], f"{cid}: client_only disposition conflicts with execution")
    req_anchors = []
    for rid, item in reqs.items():
        for key in ("title", "statement", "acceptance"):
            c.string(item.get(key), f"{rid}.{key}")
        c.enum(item.get("kind"), {"functional", "data", "interface", "quality", "extension"}, f"{rid}.kind")
        c.enum(item.get("status"), {"observed", "inferred", "assumed", "unknown", "project"}, f"{rid}.status")
        c.string(item.get("basis"), f"{rid}.basis", item.get("status") not in ("inferred", "assumed", "project"))
        anchor = item.get("anchor")
        if c.identity(anchor, f"{rid}.anchor"):
            req_anchors.append(anchor)
            c.check(anchor in anchors, f"{rid}: missing document anchor {anchor}")
            marker = re.search(r'<a\s+id="' + re.escape(anchor) + r'"\s*></a>', body)
            if marker:
                tail = body[marker.end():]
                following = re.search(r'<a\s+id="|^##\s+', tail, re.M)
                content = tail[:following.start()] if following else tail
                c.check(has_prose(content), f"{rid}: document anchor has no requirement text")
        c.refs(item.get("evidence_ids"), evidence, f"{rid}.evidence_ids", item.get("status") in ("observed", "inferred"))
        gr = c.refs(item.get("gap_ids"), gaps, f"{rid}.gap_ids")
        req_refs[rid] = c.refs(item.get("capability_ids"), caps, f"{rid}.capability_ids", item.get("kind") in ("functional", "data", "interface"))
        if item.get("status") == "unknown":
            c.check(any(gaps[g].get("status") == "open" for g in gr if g in gaps), f"{rid}: unknown requirement needs an open gap")
        if item.get("kind") == "extension":
            c.check(item.get("status") == "project", f"{rid}: Local extensions must have project status")
    c.check(len(req_anchors) == len(set(req_anchors)), "requirements: duplicate document anchors")
    for cid, refs in cap_refs.items():
        for rid in refs:
            c.check(cid in req_refs.get(rid, []), f"{cid}/{rid}: capability/requirement references must be bidirectional")
    for rid, refs in req_refs.items():
        for cid in refs:
            c.check(rid in cap_refs.get(cid, []), f"{cid}/{rid}: capability/requirement references must be bidirectional")
    discovery = index.get("discovery")
    seen_areas = []
    if c.check(isinstance(discovery, list), "discovery: array required"):
        for i, row in enumerate(discovery):
            row = c.obj(row, f"discovery[{i}]", {"area", "summary", "evidence_ids", "gap_ids"})
            area = row.get("area")
            if c.enum(area, AREAS, f"discovery[{i}].area"):
                seen_areas.append(area)
            c.string(row.get("summary"), f"discovery[{i}].summary")
            er = c.refs(row.get("evidence_ids"), evidence, f"discovery[{i}].evidence_ids")
            gr = c.refs(row.get("gap_ids"), gaps, f"discovery[{i}].gap_ids")
            c.check(bool(er or gr), f"discovery[{i}]: evidence or gap required")
    c.check(set(seen_areas) == AREAS and len(seen_areas) == len(AREAS), "discovery: exactly one record for each of four areas required")
    open_gaps = [gid for gid, gap in gaps.items() if gap.get("status") == "open"]
    blocking = [gid for gid in open_gaps if gaps[gid].get("blocking") is True]
    incomplete = [iid for iid, item in inputs.items() if not item["complete"]]
    if incomplete:
        c.check(bool(limits) and bool(open_gaps), "incomplete inputs require limitations and open gaps")
        warnings.append("Incomplete inputs: " + ", ".join(incomplete))
    if open_gaps:
        warnings.append(f"{len(open_gaps)} open gaps; {len(blocking)} blocking")
    review_ok = False
    sampling_tracking = "not_recorded" if sampled_review_required else "legacy/untracked"
    sample_count = 0
    if (bundle / "review.json").exists():
        review = _read(bundle / "review.json")
        review_ok = _check_review(c, review, bundle, set(all_ids) | set(analysis_items), tracked=tracked,
                                 sampled=sampled_review_required, available=available,
                                 analysis_items=analysis_items, gaps=gaps)
        if sampled_review_required and review.get("format") == "rea-backend.srs-review/v3":
            sampling_tracking = "tracked"
            samples = review.get("sampling", {}).get("samples") if isinstance(review.get("sampling"), dict) else None
            sample_count = len(samples) if isinstance(samples, list) else 0
        if tracked:
            review_ok = review_ok and provenance_valid
    else:
        warnings.append("Independent review has not been recorded")
    if not sampled_review_required:
        warnings.append("Legacy/untracked review sampling: this frozen analysis does not require v3 raw-evidence samples.")
    if require_reviewed or index.get("status") == "reviewed":
        c.check(index.get("status") == "reviewed", "index.status: reviewed required")
        c.check(review_ok, "review: current independent accepted review required")
    unresolved = [cid for cid, cap in caps.items() if cap.get("analysis") != "analyzed"
                  or not isinstance(cap.get("execution"), list) or "unknown" in cap["execution"]]
    unknown = [rid for rid, req in reqs.items() if req.get("status") == "unknown"]
    blocked_analysis = [iid for iid, item in analysis_items.items() if item["state"] == "blocked"]
    if blocked_analysis:
        warnings.append(f"{len(blocked_analysis)} blocked analysis items remain unresolved")
    ready = not c.errors and review_ok and index.get("status") == "reviewed" and not (blocking or incomplete or unresolved or unknown or blocked_analysis)
    return {"status": "error" if c.errors else "checked", "errors": c.errors, "warnings": warnings,
            "document_sha256": file_hash(doc_path), "index_sha256": file_hash(index_path),
            "review": "accepted" if review_ok else "not_accepted", "ready_for_implementation": ready,
            "review_sampling": sampling_tracking, "review_sample_count": sample_count,
            "analysis_tracking": "tracked" if tracked else "legacy/untracked", "analysis_work": analysis_report,
            "counts": {"capabilities": len(caps), "requirements": len(reqs), "evidence": len(evidence),
                       "open_gaps": len(open_gaps), "blocking_gaps": len(blocking),
                       "analysis": dict(Counter(cap.get("analysis") for cap in caps.values() if isinstance(cap.get("analysis"), str))),
                       "requirement_status": dict(Counter(req.get("status") for req in reqs.values() if isinstance(req.get("status"), str)))},
            "note": "Checks verify structure and local evidence integrity, not semantic completeness or original-server equivalence."}


def _check_review(c: _Checks, value: dict, bundle: Path, targets: set[str], *, tracked: bool = False,
                  sampled: bool = False, available=None, analysis_items=None, gaps=None) -> bool:
    before = len(c.errors)
    fields = {"format", "reviewer", "independent", "verdict", "document_sha256", "index_sha256", "inventory_sha256", "summary", "issues"}
    if tracked:
        fields |= {"run_sha256", "analysis_sha256", "method_sha256"}
    if sampled:
        fields.add("sampling")
    review = c.obj(value, "review", fields)
    expected = "rea-backend.srs-review/v3" if sampled else "rea-backend.srs-review/v2" if tracked else "rea-backend.srs-review/v1"
    c.check(review.get("format") == expected, f"review.format: expected {expected}")
    for key in ("reviewer", "summary"):
        c.string(review.get(key), f"review.{key}")
    c.check(type(review.get("independent")) is bool, "review.independent: boolean required")
    c.enum(review.get("verdict"), {"accepted", "revisions_required"}, "review.verdict")
    for key, filename in (("document_sha256", "backend-srs.md"), ("index_sha256", "index.json"), ("inventory_sha256", "inventory.json")):
        c.check(review.get(key) == file_hash(bundle / filename), f"review.{key}: stale review; final artifacts must be reviewed again")
    if tracked:
        for key, filename in (("run_sha256", "run.json"), ("analysis_sha256", "analysis/analysis.json"), ("method_sha256", "method/manifest.json")):
            target = bundle / filename
            c.check(target.is_file() and review.get(key) == file_hash(target), f"review.{key}: stale review; frozen provenance must be reviewed again")
    issues = c.records(review.get("issues"), "review.issues", {"id", "severity", "status", "target_ids", "finding", "resolution"})
    for iid, item in issues.items():
        c.enum(item.get("severity"), {"high", "medium", "low"}, f"{iid}.severity")
        c.enum(item.get("status"), {"open", "resolved"}, f"{iid}.status")
        c.refs(item.get("target_ids"), targets, f"{iid}.target_ids")
        c.string(item.get("finding"), f"{iid}.finding")
        c.string(item.get("resolution"), f"{iid}.resolution", item.get("status") != "resolved")
        if review.get("verdict") == "accepted":
            c.check(not (item.get("status") == "open" and item.get("severity") in ("high", "medium")), f"{iid}: accepted review cannot retain open high/medium findings")
    if sampled:
        from .review_sampling import check_sampling
        check_sampling(c, review.get("sampling"), available=available or {},
                       analysis_items=analysis_items or {}, gaps=gaps or {}, issues=issues,
                       accepted=review.get("verdict") == "accepted")
    return len(c.errors) == before and review.get("independent") is True and review.get("verdict") == "accepted"
