"""Versioned, evidence-bound validation plan contracts.

These checks bind an author's validation claims to frozen discovery records.
They do not judge evidence semantics or execute an independent client oracle.
"""
from __future__ import annotations

import hashlib
from pathlib import PurePosixPath, PureWindowsPath
import re


PLAN_V2 = "rea-backend.build-validation-plan/v2"
REPORT_V2 = "rea-backend.build-validation/v2"
FAILURE_ROUTES = {
    "requirement_gap": "discovery_srs",
    "implementation": "implementation",
    "environment": "environment",
    "unknown": "investigation",
}
EVIDENCE_KINDS = {"ui", "request", "storage", "consumer", "diagnostic"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def references(value, label, *, nonempty=False):
    require(isinstance(value, list) and all(text(item) for item in value)
            and len(value) == len(set(value)) and (value or not nonempty), f"Invalid {label}")
    return set(value)


def relative(value):
    require(text(value), "Evidence path must be a nonempty string")
    path = PurePosixPath(value)
    require(not path.is_absolute() and not PureWindowsPath(value).drive and "\\" not in value
            and ".." not in path.parts and str(path) == value and value != "." and "\0" not in value,
            f"Evidence path must be canonical and relative: {value!r}")


def flow_nodes(item, label):
    """Inspect frozen metadata defensively before using it as reference targets."""
    trace = item.get("flow_trace")
    require(isinstance(trace, dict) and isinstance(trace.get("state"), str),
            f"Invalid frozen flow trace: {label}")
    nodes = trace.get("nodes")
    require(isinstance(nodes, list) and all(isinstance(node, dict) and text(node.get("id")) for node in nodes),
            f"Invalid frozen flow nodes: {label}")
    ids = [node["id"] for node in nodes]
    require(len(ids) == len(set(ids)), f"Ambiguous frozen flow node IDs: {label}")
    return trace, set(ids)


def validate_plan(plan, data, parse_json):
    """Validate v2 additions after common argv, timeout and requirement checks."""
    require(isinstance(plan["phase"], str) and plan["phase"] in {"early_client", "final"}, "Invalid validation phase")
    require("srs-check.json" in data and "srs/review.json" in data,
            "v2 validation requires a frozen reviewed SRS build receipt")
    receipt = parse_json(data["srs-check.json"], "srs-check.json")
    review = parse_json(data["srs/review.json"], "srs/review.json")
    require(isinstance(receipt, dict) and receipt.get("status") == "checked" and receipt.get("review") == "accepted"
            and isinstance(review, dict) and review.get("format") == "rea-backend.srs-review/v3"
            and review.get("verdict") == "accepted" and review.get("independent") is True,
            "v2 validation requires an independently accepted SRS before execution")
    for field, name in (("document_sha256", "backend-srs.md"), ("index_sha256", "index.json"),
                        ("inventory_sha256", "inventory.json"), ("run_sha256", "run.json"),
                        ("analysis_sha256", "analysis/analysis.json"), ("method_sha256", "method/manifest.json")):
        require("srs/" + name in data and review.get(field) == hashlib.sha256(data["srs/" + name]).hexdigest(),
                f"Stale or missing accepted SRS review binding: {name}")
        if field in {"document_sha256", "index_sha256"}:
            require(receipt.get(field) == review[field], f"Stale SRS build receipt: {field}")
    scope = plan["scope"]
    require(isinstance(scope, dict) and set(scope) == {"workflow_ids", "requirement_ids"}, "Invalid validation scope")
    workflows = references(scope["workflow_ids"], "scope.workflow_ids", nonempty=True)
    requirements = references(scope["requirement_ids"], "scope.requirement_ids", nonempty=True)
    require("srs/analysis/analysis.json" in data, "v2 validation requires frozen srs/analysis/analysis.json")
    analysis = parse_json(data["srs/analysis/analysis.json"], "srs/analysis/analysis.json")
    require(isinstance(analysis, dict) and analysis.get("format") == "rea-backend.analysis/v3",
            "v2 validation requires frozen analysis/v3 flow traces")
    rows = analysis.get("items")
    require(isinstance(rows, list) and all(isinstance(row, dict) and text(row.get("id")) for row in rows),
            "Invalid frozen analysis items")
    items = {row["id"]: row for row in rows}
    require(len(items) == len(rows), "Ambiguous frozen analysis item IDs")
    index = parse_json(data["srs/index.json"], "srs/index.json")
    known_requirements = {row["id"] for row in index["requirements"]}
    require(requirements <= known_requirements, "Unknown scope requirement_ids")
    require(workflows <= set(items), "Unknown scope workflow_ids")
    for workflow in workflows:
        trace, nodes = flow_nodes(items[workflow], workflow)
        require(trace["state"] in {"answered", "blocked"} and nodes,
                f"Scoped workflow has no frozen flow trace: {workflow}")

    obligations = plan["obligations"]
    require(isinstance(obligations, list) and obligations, "Validation obligations must be nonempty")
    by_id = {}
    for obligation in obligations:
        fields = {"id", "item_id", "contract_kind", "node_ids", "requirement_ids", "risk"}
        require(isinstance(obligation, dict) and set(obligation) == fields, "Invalid obligation fields")
        oid = obligation["id"]
        require(isinstance(oid, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", oid)
                and oid not in by_id, "Invalid or duplicate obligation id")
        item_id = obligation["item_id"]
        require(isinstance(item_id, str) and item_id in items, f"Unknown obligation item_id: {oid}")
        kind = obligation["contract_kind"]
        require(isinstance(kind, str) and kind in {"consumer", "wire", "state", "resources", "flow"},
                f"Invalid obligation contract_kind: {oid}")
        item = items[item_id]
        contracts = item.get("contract_checks")
        contract = item.get("flow_trace") if kind == "flow" else (contracts.get(kind) if isinstance(contracts, dict) else None)
        require(isinstance(contract, dict) and isinstance(contract.get("state"), str)
                and contract["state"] in {"answered", "blocked"},
                f"Obligation must reference an investigated frozen contract: {oid}")
        node_ids = references(obligation["node_ids"], f"{oid}.node_ids")
        _, known_nodes = flow_nodes(item, item_id)
        require(node_ids <= known_nodes and (kind != "flow" or node_ids), f"Unknown or missing obligation node_ids: {oid}")
        refs = references(obligation["requirement_ids"], f"{oid}.requirement_ids", nonempty=True)
        require(refs <= requirements, f"Obligation requirement_ids outside validation scope: {oid}")
        require(text(obligation["risk"]), f"Obligation risk is required: {oid}")
        by_id[oid] = obligation

    covered_workflows, covered_requirements, covered_obligations, client_workflows = set(), set(), set(), set()
    for case in plan["cases"]:
        cid = case["id"]
        refs = references(case["requirement_ids"], f"{cid}.requirement_ids")
        flows = references(case["workflow_ids"], f"{cid}.workflow_ids")
        obligations = references(case["obligation_ids"], f"{cid}.obligation_ids")
        require(refs <= requirements and flows <= workflows and obligations <= set(by_id),
                f"Unknown or out-of-scope validation references: {cid}")
        for oid in obligations:
            require(set(by_id[oid]["requirement_ids"]) <= refs, f"Case omits obligation requirement_ids: {cid}/{oid}")
        kind = case["check_kind"]
        require(isinstance(kind, str) and kind in {"real_client", "real_consumer", "model", "http"},
                f"Invalid check_kind: {cid}")
        if kind == "model":
            require(text(case.get("model_limitations")), f"Model limitations are required: {cid}")
        else:
            require("model_limitations" not in case, f"model_limitations only applies to model checks: {cid}")
        artifacts = case["required_artifacts"]
        require(isinstance(artifacts, list) and artifacts, f"Required evidence artifacts are missing: {cid}")
        names, kinds = set(), set()
        for artifact in artifacts:
            require(isinstance(artifact, dict) and set(artifact) == {"path", "kind"}, f"Invalid required artifact: {cid}")
            relative(artifact["path"])
            require(isinstance(artifact["kind"], str) and artifact["kind"] in EVIDENCE_KINDS,
                    f"Invalid evidence kind: {cid}")
            require(artifact["path"] not in names, f"Duplicate required artifact path: {cid}")
            names.add(artifact["path"])
            kinds.add(artifact["kind"])
        if kind == "real_client":
            require(flows and {"ui", "request"} <= kinds,
                    f"Real-client cases require workflow links and UI/request artifacts: {cid}")
            client_workflows.update(flows)
        if kind == "real_consumer":
            require("consumer" in kinds, f"Real-consumer cases require consumer evidence: {cid}")
        if any(by_id[oid]["contract_kind"] == "state" for oid in obligations):
            require("storage" in kinds, f"State obligations require actual-storage evidence: {cid}")
        if "failure_artifact" in case:
            relative(case["failure_artifact"])
            require(case["failure_artifact"] not in names, f"Failure artifact cannot be required success evidence: {cid}")
        covered_workflows.update(flows)
        covered_requirements.update(refs)
        covered_obligations.update(obligations)
    require(covered_workflows == workflows and covered_requirements == requirements,
            "Every scoped workflow and requirement must have a planned check")
    require(covered_obligations == set(by_id), "Every validation obligation must have a planned check")
    require(client_workflows == workflows,
            f"{plan['phase']} requires a real-client check for every scoped workflow")


def evidence_checks(case, saved, boundary_ns):
    checks = []
    for expected in case["required_artifacts"]:
        actual = saved.get(expected["path"])
        error = ("missing" if actual is None else "empty" if not actual["bytes"]
                 else "stale" if actual["mtime_ns"] < boundary_ns else None)
        checks.append({**expected, "status": "failed" if error else "passed",
                       **({"error": error} if error else {}), **(actual or {})})
    return checks


def failure_record(case, record, saved_bytes, parse_json):
    """Default to unknown; an optional evidence-backed author diagnosis may refine it."""
    result = {"case_id": case["id"], "category": "unknown", "summary": "Validation case did not pass.",
              "attribution": "unclassified", "evidence_paths": [], "requirement_ids": case["requirement_ids"],
              "workflow_ids": case["workflow_ids"], "obligation_ids": case["obligation_ids"]}
    if record.get("timed_out"):
        result["summary"] = "Validation command exceeded its time limit; the cause remains unclassified."
    path = case.get("failure_artifact")
    if path in saved_bytes:
        try:
            metadata = record["artifacts"][path]
            require(metadata["bytes"] and metadata["mtime_ns"] >= record["evidence_boundary_mtime_ns"],
                    "Failure attribution artifact is empty or stale")
            value = parse_json(saved_bytes[path], "failure attribution")
            require(isinstance(value, dict) and set(value) == {"category", "summary", "evidence_paths"},
                    "Invalid failure attribution fields")
            require(isinstance(value["category"], str) and value["category"] in FAILURE_ROUTES,
                    "Invalid failure category")
            require(text(value["summary"]), "Failure summary is required")
            refs = references(value["evidence_paths"], "failure.evidence_paths", nonempty=True)
            for ref in refs:
                relative(ref)
                artifact = record["artifacts"].get(ref)
                require(ref != path and artifact and artifact["bytes"]
                        and artifact["mtime_ns"] >= record["evidence_boundary_mtime_ns"],
                        f"Missing, empty or stale failure evidence: {ref}")
            result.update(value, attribution="author_observation_not_independently_verified",
                          artifact_path=path, artifact_sha256=metadata["sha256"])
        except (ValueError, KeyError, TypeError) as exc:
            result["attribution_error"] = str(exc)
    result["next_stage"] = FAILURE_ROUTES[result["category"]]
    return result
