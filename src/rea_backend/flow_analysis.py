"""Validate registered flow traces without claiming semantic completeness.

Graph IDs are local to a work item. Evidence callbacks check the same approved
inputs as all other discovery evidence; historical graphs are checked without
re-reading source bytes which may legitimately have changed in a later revision.
"""
from __future__ import annotations


FLOW_STATES = {"pending", "answered", "blocked", "not_applicable"}
FLOW_KINDS = {"entry", "prerequisite", "request", "consumer", "state", "terminal"}
EDGE_KINDS = {"sequence", "requires", "parallel", "branch"}
FLOW_FIELDS = {"state", "scope", "finding", "evidence", "next_action", "gap_ids", "nodes", "edges", "boundaries"}
NODE_FIELDS = {"id", "kind", "symbol", "location", "evidence"}
EDGE_FIELDS = {"id", "from", "to", "kind", "evidence"}
BOUNDARY_FIELDS = {"id", "node_id", "question", "state", "work_item_ids", "gap_ids", "resolution_node_ids", "evidence", "next_action"}


def _evidence(c, row, label, source_check, *, required=False):
    evidence = row.get("evidence")
    if c.check(isinstance(evidence, list), f"{label}.evidence: array required"):
        if required:
            c.check(bool(evidence), f"{label}: scoped evidence required")
        if source_check is not None:
            for number, source in enumerate(evidence):
                source_check(source, f"{label}.evidence[{number}]")


def _disposition(c, row, label, item, *, require_settled=False):
    state = row.get("state")
    c.enum(state, FLOW_STATES, f"{label}.state")
    c.string(row.get("next_action"), f"{label}.next_action", state not in ("pending", "blocked"))
    gaps = c.strings(row.get("gap_ids"), f"{label}.gap_ids", require_settled and state == "blocked")
    for gid in gaps:
        c.identity(gid, f"{label}.gap_ids")
    parent_gaps = item.get("gap_ids")
    c.check(isinstance(parent_gaps, list) and all(gid in parent_gaps for gid in gaps),
            f"{label}: flow gaps must also be retained in the parent gap_ids")
    if item.get("state") in ("answered", "out_of_scope"):
        c.check(state in ("answered", "not_applicable"),
                f"{label}: resolved parent cannot hide pending or blocked flow work")
    if state == "blocked":
        c.check(item.get("state") in ("pending", "blocked"),
                f"{label}: blocked flow work requires pending/blocked parent")
    if require_settled:
        c.check(state != "pending", f"{label}: pending flow work cannot be frozen")
        if state == "blocked":
            c.check(item.get("state") == "blocked", f"{label}: settled blocked flow work requires blocked parent")
    return state


def validate_flow(c, item, iid, items, *, require_settled=False, source_check=None):
    """Check one flow's structure, provenance, dispositions, and work references."""
    label = f"{iid}.flow_trace"
    trace = c.obj(item.get("flow_trace"), label, FLOW_FIELDS)
    state = _disposition(c, trace, label, item, require_settled=require_settled)
    c.string(trace.get("scope"), f"{label}.scope")
    c.string(trace.get("finding"), f"{label}.finding", state == "pending")
    _evidence(c, trace, label, source_check, required=state in ("answered", "not_applicable"))
    nodes = c.records(trace.get("nodes"), f"{label}.nodes", NODE_FIELDS, nonempty=state == "answered")
    edges = c.records(trace.get("edges"), f"{label}.edges", EDGE_FIELDS)
    boundaries = c.records(trace.get("boundaries"), f"{label}.boundaries", BOUNDARY_FIELDS)
    adjacency = {nid: set() for nid in nodes}
    for nid, node in nodes.items():
        nlabel = f"{label}.nodes/{nid}"
        c.enum(node.get("kind"), FLOW_KINDS, f"{nlabel}.kind")
        c.string(node.get("symbol"), f"{nlabel}.symbol")
        c.string(node.get("location"), f"{nlabel}.location")
        _evidence(c, node, nlabel, source_check, required=True)
    for eid, edge in edges.items():
        elabel = f"{label}.edges/{eid}"
        c.enum(edge.get("kind"), EDGE_KINDS, f"{elabel}.kind")
        endpoints = []
        for field in ("from", "to"):
            target = edge.get(field)
            if c.identity(target, f"{elabel}.{field}"):
                c.check(target in nodes, f"{elabel}.{field}: unknown node {target}")
                endpoints.append(target)
        if len(endpoints) == 2 and all(nid in nodes for nid in endpoints):
            adjacency[endpoints[0]].add(endpoints[1])
        _evidence(c, edge, elabel, source_check, required=True)

    def reachable(origins):
        seen, remaining = set(), list(origins)
        while remaining:
            nid = remaining.pop()
            if nid not in seen:
                seen.add(nid)
                remaining.extend(adjacency.get(nid, set()) - seen)
        return seen

    boundary_nodes = set()
    for bid, boundary in boundaries.items():
        blabel = f"{label}.boundaries/{bid}"
        bstate = _disposition(c, boundary, blabel, item, require_settled=require_settled)
        c.string(boundary.get("question"), f"{blabel}.question")
        node = boundary.get("node_id")
        if c.identity(node, f"{blabel}.node_id"):
            c.check(node in nodes, f"{blabel}.node_id: unknown node {node}")
            if node in nodes:
                boundary_nodes.add(node)
        refs = c.refs(boundary.get("work_item_ids"), items, f"{blabel}.work_item_ids")
        c.check(iid not in refs, f"{blabel}: boundary cannot delegate work to its own item")
        unresolved = [rid for rid in refs if rid in items and items[rid].get("state") not in ("answered", "out_of_scope")]
        if bstate in ("answered", "not_applicable") or state in ("answered", "not_applicable") or item.get("state") in ("answered", "out_of_scope"):
            c.check(not unresolved, f"{blabel}: resolved flow cannot hide unresolved referenced work: {unresolved}")
        if require_settled:
            c.check(not any(items[rid].get("state") == "pending" for rid in refs if rid in items),
                    f"{blabel}: referenced pending work cannot be frozen")
        resolution = c.refs(boundary.get("resolution_node_ids"), nodes, f"{blabel}.resolution_node_ids")
        if bstate == "answered":
            c.check(bool(refs or resolution), f"{blabel}: answered boundary requires resolution nodes or resolved work items")
            for nid in resolution:
                c.check(isinstance(node, str) and nid != node and nid in reachable([node]),
                        f"{blabel}: resolution node {nid} must be downstream of the boundary")
        if state in ("answered", "not_applicable"):
            c.check(bstate in ("answered", "not_applicable"), f"{blabel}: resolved trace cannot hide an unhandled boundary")
        _evidence(c, boundary, blabel, source_check, required=bstate in ("answered", "not_applicable"))

    if state == "answered":
        entries = {nid for nid, node in nodes.items() if node.get("kind") == "entry"}
        terminals = {nid for nid, node in nodes.items() if node.get("kind") == "terminal"}
        c.check(bool(entries), f"{label}: answered trace requires an entry node")
        c.check(bool(terminals), f"{label}: answered trace requires a terminal node")
        c.check(set(nodes) <= reachable(entries), f"{label}: all nodes must be reachable from a recorded entry")
        for nid in nodes:
            c.check(bool(reachable([nid]) & (terminals | boundary_nodes)),
                    f"{label}.nodes/{nid}: flow must reach a terminal or an explicitly disposed boundary")
    return trace


def registered_boundaries(item):
    trace = item.get("flow_trace") if isinstance(item, dict) else None
    rows = trace.get("boundaries") if isinstance(trace, dict) else None
    return {row["id"] for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)} if isinstance(rows, list) else set()


def retain_boundaries(c, previous, current, label):
    for iid, item in previous.items():
        missing = registered_boundaries(item) - registered_boundaries(current.get(iid))
        c.check(not missing, f"{label}/{iid}: registered flow boundaries disappeared: {sorted(missing)}")


def flow_work(items):
    """Flat tracking rows for resume output; graph IDs remain local to an item."""
    result = {}
    for iid, item in items.items():
        trace = item.get("flow_trace")
        if not isinstance(trace, dict):
            continue
        result[iid] = trace
        boundaries = trace.get("boundaries")
        if isinstance(boundaries, list):
            for row in boundaries:
                if isinstance(row, dict) and isinstance(row.get("id"), str):
                    result[f"{iid}/{row['id']}"] = row
    return result
