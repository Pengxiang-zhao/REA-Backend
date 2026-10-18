"""An append-only work list for agent-led discovery before SRS input freeze.

The checks account for registered clues. They do not discover missing behavior
or judge the truth of an author's findings.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath

from .srs import AREAS, IGNORED, _Checks, _read, _root, _write, file_hash, load_config
from .flow_analysis import flow_work, retain_boundaries, validate_flow

FORMAT = "rea-backend.analysis/v3"
CONTRACT_FORMAT = "rea-backend.analysis/v2"
LEGACY_FORMAT = "rea-backend.analysis/v1"
ITEM_FIELDS = {"id", "clue", "question", "area", "sources", "state", "next_action",
               "depends_on", "evidence", "finding", "gap_ids"}
STATES = {"pending", "answered", "blocked", "out_of_scope"}
CONTRACT_KINDS = {"consumer", "wire", "state", "resources"}
CONTRACT_STATES = {"pending", "answered", "blocked", "not_applicable"}
CONTRACT_FIELDS = {"state", "finding", "evidence", "next_action", "gap_ids"}
NOTE = "Checks account only for registered work items and source integrity; they do not establish complete App discovery."


def _item_fields(format: str) -> set[str]:
    return (ITEM_FIELDS | ({"contract_checks"} if format in (FORMAT, CONTRACT_FORMAT) else set())
            | ({"flow_trace"} if format == FORMAT else set()))


def _contracts(c: _Checks, item: dict, iid: str, *, require_settled=False) -> dict:
    """Check scoped investigation dispositions, never infer business answers.

    Source integrity is checked separately for the current revision. Historical
    evidence may have changed during exploration and is not re-read here.
    """
    checks = c.obj(item.get("contract_checks"), f"{iid}.contract_checks", CONTRACT_KINDS)
    for kind in sorted(CONTRACT_KINDS):
        label = f"{iid}.contract_checks.{kind}"
        row = c.obj(checks.get(kind), label, CONTRACT_FIELDS)
        state = row.get("state")
        c.enum(state, CONTRACT_STATES, f"{label}.state")
        c.string(row.get("finding"), f"{label}.finding", state == "pending")
        c.string(row.get("next_action"), f"{label}.next_action", state not in ("pending", "blocked"))
        gaps = c.strings(row.get("gap_ids"), f"{label}.gap_ids", require_settled and state == "blocked")
        for gid in gaps:
            c.identity(gid, f"{label}.gap_ids")
        parent_gaps = item.get("gap_ids")
        c.check(isinstance(parent_gaps, list) and all(gid in parent_gaps for gid in gaps),
                f"{label}: contract gaps must also be retained in the parent gap_ids")
        evidence = row.get("evidence")
        if c.check(isinstance(evidence, list), f"{label}.evidence: array required"):
            if state in ("answered", "not_applicable"):
                c.check(bool(evidence), f"{label}: answered/not_applicable requires scoped evidence")
        if item.get("state") in ("answered", "out_of_scope"):
            c.check(state in ("answered", "not_applicable"),
                    f"{label}: resolved parent cannot hide pending or blocked contract work")
        if state == "blocked":
            c.check(item.get("state") in ("pending", "blocked"),
                    f"{label}: blocked contract requires pending/blocked parent")
        if require_settled:
            c.check(state != "pending", f"{label}: pending contract work cannot be frozen")
            if state == "blocked":
                c.check(item.get("state") == "blocked", f"{label}: settled blocked contract requires blocked parent")
    return checks


def _local(path: Path) -> Path:
    if path.is_symlink() or any(p.is_symlink() for p in path.absolute().parents):
        raise ValueError(f"Analysis symlinks are not supported: {path}")
    return path.resolve()


def _outside_inputs(config_path: Path, config: dict, out: Path) -> None:
    for item in config["inputs"]:
        root = _root(config_path, item)
        if out == root or out.is_relative_to(root):
            raise ValueError("Analysis output cannot be inside an input")


@contextmanager
def _lock(directory: Path):
    path = directory / ".update.lock"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError("Analysis update already in progress; inspect .update.lock before retrying") from exc
    os.close(descriptor)
    try:
        yield
    finally:
        path.unlink()


def initialize_analysis(config_path: Path, out: Path) -> dict:
    """Create revision 1 without inventorying or freezing generation inputs."""
    config_path, out = _local(config_path), _local(out)
    config = load_config(config_path)
    _outside_inputs(config_path, config, out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError(f"Analysis output must be an empty directory: {out}")
    now = datetime.now(timezone.utc).isoformat()
    value = {"format": FORMAT, "app": config["app"], "route": config["route"],
             "context_mode": config["context"]["mode"], "revision": 1,
             "previous_sha256": None, "config_sha256": file_hash(config_path),
             "created_at": now, "updated_at": now, "items": []}
    (out / "revisions").mkdir(parents=True)
    _write(out / "revisions/00000001.json", value)
    _write(out / "analysis.json", value)
    return {"status": "initialized", "output": str(out), "revision": 1, "note": NOTE}


def _source(c: _Checks, row, label: str, config_path: Path, config: dict,
            *, evidence=False, available=None) -> None:
    fields = {"input_id", "path", "sha256"} | ({"note"} if evidence else set())
    row = c.obj(row, label, fields)
    if evidence:
        c.string(row.get("note"), f"{label}.note")
    inputs = {i["id"]: i for i in config["inputs"] if i["access"] == "generation"}
    iid, relative = row.get("input_id"), row.get("path")
    if not c.check(isinstance(iid, str) and iid in inputs, f"{label}: source must be generation-visible"):
        return
    if not c.string(relative, f"{label}.path"):
        return
    path = PurePosixPath(relative)
    if not c.check(not path.is_absolute() and ".." not in path.parts and "\\" not in relative
                   and str(path) == relative, f"{label}: canonical relative path required"):
        return
    c.sha(row.get("sha256"), f"{label}.sha256")
    if available is not None:
        entry = available.get((iid, relative))
        c.check(entry is not None and row.get("sha256") == entry["sha256"],
                f"{label}: source missing or changed from frozen inventory")
        return
    item = inputs[iid]
    # Respect excluded directories as well as excluded individual files.
    ancestors = [PurePosixPath(*path.parts[:i]).as_posix() for i in range(1, len(path.parts) + 1)]
    if not c.check(not any(p in IGNORED for p in path.parts)
                   and not any(fnmatch.fnmatchcase(p, pattern) for p in ancestors for pattern in item["exclude"]),
                   f"{label}: source is excluded from generation inputs"):
        return
    root = _root(config_path, item)
    target = root / relative if root.is_dir() else root
    if not root.is_dir() and not c.check(relative == root.name, f"{label}: single-file source must use its basename"):
        return
    if not c.check(not target.is_symlink() and not any(p.is_symlink() for p in target.parents),
                   f"{label}: source symlinks are not supported"):
        return
    if c.check(target.is_file(), f"{label}: missing source {relative}"):
        c.check(row.get("sha256") == file_hash(target), f"{label}: source sha256 mismatch")


def _validate(c: _Checks, value: dict, config_path: Path, config: dict, *, require_settled=False,
              available=None) -> dict:
    value = c.obj(value, "analysis", {"format", "app", "route", "context_mode", "revision", "previous_sha256",
                                   "config_sha256", "created_at", "updated_at", "items"})
    c.check(value.get("format") in (FORMAT, CONTRACT_FORMAT, LEGACY_FORMAT), "analysis.format: invalid format")
    c.check(value.get("app") == config["app"], "analysis.app: fixed App identity changed")
    c.check(value.get("route") == config["route"], "analysis.route: route changed")
    c.check(value.get("context_mode") == config["context"]["mode"], "analysis.context_mode: input policy changed")
    c.check(type(value.get("revision")) is int and value["revision"] >= 1, "analysis.revision: positive integer required")
    c.sha(value.get("config_sha256"), "analysis.config_sha256")
    for key in ("created_at", "updated_at"):
        c.string(value.get(key), f"analysis.{key}")
    items = c.records(value.get("items"), "analysis.items", _item_fields(value.get("format")), nonempty=require_settled)
    for iid, item in items.items():
        for key in ("clue", "question"):
            c.string(item.get(key), f"{iid}.{key}")
        c.enum(item.get("area"), AREAS, f"{iid}.area")
        state = item.get("state")
        c.enum(state, STATES, f"{iid}.state")
        c.string(item.get("next_action"), f"{iid}.next_action", state not in ("pending", "blocked"))
        c.string(item.get("finding"), f"{iid}.finding", state == "pending")
        deps = c.refs(item.get("depends_on"), items, f"{iid}.depends_on")
        c.check(iid not in deps, f"{iid}: cannot depend on itself")
        if state == "answered":
            c.check(all(items[d].get("state") in ("answered", "out_of_scope") for d in deps if d in items),
                    f"{iid}: answered item has unresolved dependencies")
        gaps = c.strings(item.get("gap_ids"), f"{iid}.gap_ids", require_settled and state == "blocked")
        for gid in gaps:
            c.identity(gid, f"{iid}.gap_ids")
        for field in ("sources", "evidence"):
            rows = item.get(field)
            if not c.check(isinstance(rows, list), f"{iid}.{field}: array required"):
                continue
            if field == "sources" or state == "answered":
                c.check(bool(rows), f"{iid}.{field}: nonempty array required")
            for number, row in enumerate(rows):
                _source(c, row, f"{iid}.{field}[{number}]", config_path, config,
                        evidence=field == "evidence", available=available)
        if require_settled:
            c.check(state != "pending", f"{iid}: pending work cannot be frozen as settled analysis")
        if value.get("format") in (FORMAT, CONTRACT_FORMAT):
            checks = _contracts(c, item, iid, require_settled=require_settled)
            for kind, row in checks.items():
                if not isinstance(row, dict) or not isinstance(row.get("evidence"), list):
                    continue
                for number, evidence in enumerate(row["evidence"]):
                    _source(c, evidence, f"{iid}.contract_checks.{kind}.evidence[{number}]",
                            config_path, config, evidence=True, available=available)
        if value.get("format") == FORMAT:
            validate_flow(c, item, iid, items, require_settled=require_settled,
                          source_check=lambda source, label: _source(c, source, label, config_path, config,
                                                                     evidence=True, available=available))
    visiting, visited = set(), set()

    def visit(iid):
        if iid in visiting:
            c.check(False, f"{iid}: cyclic analysis dependencies")
            return
        if iid in visited:
            return
        visiting.add(iid)
        deps = items[iid].get("depends_on")
        dependencies = list(deps) if isinstance(deps, list) else []
        if value.get("format") == FORMAT:
            trace = items[iid].get("flow_trace")
            boundaries = trace.get("boundaries") if isinstance(trace, dict) else None
            for boundary in boundaries if isinstance(boundaries, list) else []:
                refs = boundary.get("work_item_ids") if isinstance(boundary, dict) else None
                if isinstance(refs, list):
                    dependencies.extend(refs)
        for dep in dependencies:
            if isinstance(dep, str) and dep in items:
                visit(dep)
        visiting.remove(iid)
        visited.add(iid)
    for iid in items:
        visit(iid)
    return items


def _history(c: _Checks, directory: Path, value: dict) -> None:
    """Validate the full chain, including retention of every registered ID."""
    revision = value.get("revision")
    if type(revision) is not int or revision < 1:
        return
    if not c.check(not (directory / "revisions").is_symlink() and not (directory / "analysis.json").is_symlink(),
                   "analysis: symlink work list or revisions directory not supported"):
        return
    paths = sorted((directory / "revisions").glob("*.json"))
    expected = [f"{n:08}.json" for n in range(1, revision + 1)]
    if not c.check([p.name for p in paths] == expected, "analysis: revision history missing or inconsistent"):
        return
    previous, registered, previous_items = None, set(), {}
    for number, path in enumerate(paths, 1):
        if not c.check(not path.is_symlink(), f"analysis: symlink revision {path.name}"):
            return
        row = _read(path)
        c.check(row.get("format") in (FORMAT, CONTRACT_FORMAT, LEGACY_FORMAT)
                and row.get("format") == value.get("format") and row.get("revision") == number,
                f"analysis: invalid revision {number}")
        c.check(row.get("previous_sha256") == previous, f"analysis: broken history chain at revision {number}")
        for key in ("app", "route", "context_mode", "created_at"):
            c.check(row.get(key) == value.get(key), f"analysis: identity changed at revision {number}: {key}")
        records = row.get("items")
        if row.get("format") in (FORMAT, CONTRACT_FORMAT) and isinstance(records, list):
            for item in records:
                if isinstance(item, dict):
                    _contracts(c, item, f"revision {number}/{item.get('id')}")
        current_items = {r["id"]: r for r in records if isinstance(r, dict) and isinstance(r.get("id"), str)} if isinstance(records, list) else {}
        if row.get("format") == FORMAT:
            for iid, item in current_items.items():
                validate_flow(c, item, iid, current_items)
            retain_boundaries(c, previous_items, current_items, f"analysis revision {number}")
        previous_items = current_items
        ids = {r.get("id") for r in records if isinstance(r, dict) and isinstance(r.get("id"), str)} if isinstance(records, list) else set()
        c.check(registered <= ids, f"analysis: registered items disappeared at revision {number}: {sorted(registered - ids)}")
        registered = ids
        previous = file_hash(path)
    c.check(previous == file_hash(directory / "analysis.json"), "analysis: current work list differs from its persisted revision")


def check_analysis(config_path: Path, analysis: Path, require_settled: bool = False, *, available=None) -> dict:
    config_path, analysis = _local(config_path), _local(analysis)
    config = load_config(config_path)
    c = _Checks()
    try:
        if (analysis / "analysis.json").is_symlink():
            raise ValueError("symlink work list is not supported")
        value = _read(analysis / "analysis.json")
        items = _validate(c, value, config_path, config, require_settled=require_settled, available=available)
        _history(c, analysis, value)
    except (OSError, ValueError) as exc:
        c.check(False, f"analysis: {exc}")
        value, items = {}, {}
    counts = dict(Counter(i.get("state") for i in items.values() if isinstance(i.get("state"), str)))
    contract_work = {f"{iid}/{kind}": row for iid, item in items.items()
                     if isinstance(item.get("contract_checks"), dict)
                     for kind, row in item["contract_checks"].items() if isinstance(row, dict)}
    contract_counts = dict(Counter(row.get("state") for row in contract_work.values()
                                   if isinstance(row.get("state"), str)))
    flows = flow_work(items)
    flow_counts = dict(Counter(row.get("state") for row in flows.values() if isinstance(row.get("state"), str)))
    settled = bool(items) and not c.errors and not counts.get("pending") and all(
        i.get("state") != "blocked" or bool(i.get("gap_ids")) for i in items.values()) and not contract_counts.get("pending") and all(
        row.get("state") != "blocked" or bool(row.get("gap_ids")) for row in contract_work.values()) and not flow_counts.get("pending") and all(
        row.get("state") != "blocked" or bool(row.get("gap_ids")) for row in flows.values())
    return {"status": "error" if c.errors else "checked", "errors": c.errors,
            "revision": value.get("revision"), "counts": counts, "settled": settled,
            "contract_tracking": "tracked" if value.get("format") in (FORMAT, CONTRACT_FORMAT) else "legacy/untracked",
            "contract_counts": contract_counts,
            "contract_next_actions": [{"id": key, "state": row.get("state"),
                                       "next_action": row.get("next_action"), "gap_ids": row.get("gap_ids")}
                                      for key, row in contract_work.items() if row.get("state") in ("pending", "blocked")],
            "flow_tracking": "tracked" if value.get("format") == FORMAT else "legacy/untracked",
            "flow_counts": flow_counts,
            "flow_next_actions": [{"id": key, "state": row.get("state"), "next_action": row.get("next_action"),
                                   "work_item_ids": row.get("work_item_ids", []), "gap_ids": row.get("gap_ids")}
                                  for key, row in flows.items() if row.get("state") in ("pending", "blocked")],
            "unresolved_ids": [iid for iid, i in items.items() if i.get("state") in ("pending", "blocked")], "note": NOTE}


def update_analysis(config_path: Path, analysis: Path, updates: list[dict], expected_revision: int) -> dict:
    """Upsert complete records; omitted records remain, and stale writers fail."""
    config_path, analysis = _local(config_path), _local(analysis)
    config = load_config(config_path)
    if type(expected_revision) is not int or expected_revision < 1:
        raise ValueError("expected_revision must be a positive integer")
    if not isinstance(updates, list) or not updates:
        raise ValueError("Analysis updates must be a nonempty array of complete work items")
    with _lock(analysis):
        value = _read(analysis / "analysis.json")
        if value.get("revision") != expected_revision:
            raise ValueError(f"Stale analysis revision: expected {expected_revision}, current {value.get('revision')}")
        c = _Checks()
        _history(c, analysis, value)
        existing = value.get("items")
        c.check(isinstance(existing, list), "analysis.items: array required")
        fields = _item_fields(value.get("format"))
        incoming = c.records(updates, "updates", fields, nonempty=True)
        if c.errors:
            raise ValueError("Invalid analysis update:\n" + "\n".join(c.errors))
        records = c.records(existing, "analysis.items", fields)
        if c.errors:
            raise ValueError("Invalid analysis update:\n" + "\n".join(c.errors))
        if value.get("format") == FORMAT:
            retain_boundaries(c, records, {**records, **incoming}, "analysis update")
        records.update(deepcopy(incoming))
        candidate = {**value, "revision": expected_revision + 1,
                     "previous_sha256": file_hash(analysis / "analysis.json"),
                     "config_sha256": file_hash(config_path), "updated_at": datetime.now(timezone.utc).isoformat(),
                     "items": list(records.values())}
        _validate(c, candidate, config_path, config)
        if c.errors:
            raise ValueError("Invalid analysis update:\n" + "\n".join(c.errors))
        revision_path = analysis / "revisions" / f"{candidate['revision']:08}.json"
        serialized = json.dumps(candidate, ensure_ascii=False, indent=2) + "\n"
        with revision_path.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
        temporary = analysis / ".analysis.json.tmp"
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(analysis / "analysis.json")
    return {"status": "updated", "output": str(analysis), "revision": candidate["revision"],
            "counts": dict(Counter(i["state"] for i in candidate["items"])), "note": NOTE}
