"""Synthetic regressions for registered flow discovery, not App-specific answers."""
from copy import deepcopy

import pytest

from rea_backend.analysis import check_analysis, initialize_analysis, update_analysis
from rea_backend.srs import initialize_srs
from test_analysis import work_item
from test_srs import materials, digest, read_json, write_json


def start(materials):
    analysis = materials["root"] / "analysis"
    initialize_analysis(materials["config"], analysis)
    return analysis


def flow_item(materials, *, state="answered", iid="Q-page"):
    """One page has a pre-request gate, parallel reads, a sort and state write."""
    item = work_item(materials, iid=iid, state=state)
    evidence = [{"input_id": "client", "path": "Article.kt", "sha256": digest(materials["source"]),
                 "note": "Synthetic flow fixture; locators are declared by this test, not a real App claim."}]
    kinds = [("N-open", "entry"), ("N-gate", "prerequisite"), ("N-list", "request"),
             ("N-summary", "request"), ("N-sort", "consumer"), ("N-save", "state"), ("N-done", "terminal")]
    edges = [("N-open", "N-gate", "requires"), ("N-gate", "N-list", "parallel"),
             ("N-gate", "N-summary", "parallel"), ("N-list", "N-sort", "sequence"),
             ("N-summary", "N-sort", "sequence"), ("N-sort", "N-save", "sequence"),
             ("N-save", "N-done", "sequence")]
    item["flow_trace"] = {
        "state": state, "scope": "Synthetic default-page loading and visible saved result.",
        "finding": "The page gates two reads, sorts their aggregate and saves the result." if state != "pending" else "",
        "evidence": evidence, "next_action": "Inspect the remaining branch." if state in ("pending", "blocked") else "",
        "gap_ids": ["G-analysis"] if state == "blocked" else [],
        "nodes": [{"id": nid, "kind": kind, "symbol": f"Fixture.{nid[2:]}", "location": f"Article.kt:{number}",
                   "evidence": deepcopy(evidence)} for number, (nid, kind) in enumerate(kinds, 1)],
        "edges": [{"id": f"E-{number}", "from": origin, "to": target, "kind": kind, "evidence": deepcopy(evidence)}
                  for number, (origin, target, kind) in enumerate(edges, 1)],
        "boundaries": [],
    }
    return item


def boundary(item, *, node="N-gate", state="pending", bid="B-gate"):
    return {"id": bid, "node_id": node, "question": "What happens on the untraced condition before the next action?",
            "state": state, "work_item_ids": [], "gap_ids": ["G-analysis"] if state == "blocked" else [],
            "resolution_node_ids": ["N-list"] if state == "answered" else [],
            "evidence": deepcopy(item["flow_trace"]["evidence"]),
            "next_action": "Inspect the gate's alternate branch and eventual response consumer." if state in ("pending", "blocked") else ""}


def test_pre_request_boundary_is_visible_and_must_be_disposed_before_freeze(materials):
    analysis = start(materials)
    item = flow_item(materials, state="pending")
    item["flow_trace"]["boundaries"] = [boundary(item)]
    update_analysis(materials["config"], analysis, [item], 1)
    report = check_analysis(materials["config"], analysis)
    assert report["status"] == "checked" and not report["settled"]
    assert {row["id"] for row in report["flow_next_actions"]} == {"Q-page", "Q-page/B-gate"}
    with pytest.raises(ValueError, match="pending flow"):
        initialize_srs(materials["config"], materials["out"], template=materials["template"], analysis=analysis)
    resolved = flow_item(materials)
    resolved["flow_trace"]["boundaries"] = [boundary(resolved, state="answered")]
    update_analysis(materials["config"], analysis, [resolved], 2)
    report = check_analysis(materials["config"], analysis, require_settled=True)
    assert report["settled"] and report["flow_tracking"] == "tracked"
    assert report["flow_next_actions"] == []


def test_sorting_consumer_gap_survives_settled_freeze(materials):
    analysis = start(materials)
    item = flow_item(materials, state="blocked")
    item["flow_trace"]["boundaries"] = [boundary(item, node="N-sort", state="blocked", bid="B-sort")]
    update_analysis(materials["config"], analysis, [item], 1)
    report = check_analysis(materials["config"], analysis, require_settled=True)
    assert report["settled"]
    assert report["flow_next_actions"][1]["gap_ids"] == ["G-analysis"]
    initialize_srs(materials["config"], materials["out"], template=materials["template"], analysis=analysis)
    assert read_json(materials["out"] / "index.json")["gaps"][0]["id"] == "G-analysis"


def test_parallel_page_branch_cannot_silently_end_at_an_interface(materials):
    analysis = start(materials)
    item = flow_item(materials)
    item["flow_trace"]["edges"] = [edge for edge in item["flow_trace"]["edges"] if edge["from"] != "N-summary"]
    with pytest.raises(ValueError, match="N-summary: flow must reach"):
        update_analysis(materials["config"], analysis, [item], 1)
    item["flow_trace"]["boundaries"] = [boundary(item, node="N-summary", state="not_applicable", bid="B-summary")]
    update_analysis(materials["config"], analysis, [item], 1)
    assert check_analysis(materials["config"], analysis, require_settled=True)["settled"]


@pytest.mark.parametrize("parent", ["answered", "out_of_scope"])
def test_answered_parent_cannot_hide_linked_unresolved_investigation(materials, parent):
    analysis = start(materials)
    item, child = flow_item(materials), work_item(materials, iid="Q-network")
    item["state"] = parent
    missing = boundary(item, state="answered")
    missing["work_item_ids"] = [child["id"]]
    item["flow_trace"]["boundaries"] = [missing]
    with pytest.raises(ValueError, match="unresolved referenced work"):
        update_analysis(materials["config"], analysis, [item, child], 1)


def test_boundary_delegation_can_resolve_without_copying_child_graph(materials):
    analysis = start(materials)
    item, child = flow_item(materials), work_item(materials, iid="Q-network", state="answered")
    resolved = boundary(item, state="answered")
    resolved.update(work_item_ids=[child["id"]], resolution_node_ids=[])
    item["flow_trace"]["boundaries"] = [resolved]
    update_analysis(materials["config"], analysis, [item, child], 1)
    assert check_analysis(materials["config"], analysis, require_settled=True)["settled"]


def test_boundary_links_cannot_create_circular_investigation_completion(materials):
    analysis = start(materials)
    first, second = flow_item(materials), flow_item(materials, iid="Q-other")
    for item, target in ((first, second), (second, first)):
        record = boundary(item, state="answered")
        record["work_item_ids"] = [target["id"]]
        item["flow_trace"]["boundaries"] = [record]
    with pytest.raises(ValueError, match="cyclic analysis dependencies"):
        update_analysis(materials["config"], analysis, [first, second], 1)


@pytest.mark.parametrize("rewrite_scope", [False, True])
def test_registered_boundary_cannot_be_deleted_by_update_or_scope_rewrite(materials, rewrite_scope):
    analysis = start(materials)
    item = flow_item(materials)
    item["flow_trace"]["boundaries"] = [boundary(item, state="answered")]
    update_analysis(materials["config"], analysis, [item], 1)
    before = (analysis / "analysis.json").read_bytes()
    replacement = work_item(materials, iid=item["id"], state="answered") if rewrite_scope else flow_item(materials)
    with pytest.raises(ValueError, match="registered flow boundaries disappeared"):
        update_analysis(materials["config"], analysis, [replacement], 2)
    assert (analysis / "analysis.json").read_bytes() == before


def test_not_applicable_scope_revision_keeps_explicit_historical_boundary_disposition(materials):
    analysis = start(materials)
    item = flow_item(materials)
    item["flow_trace"]["boundaries"] = [boundary(item, state="answered")]
    update_analysis(materials["config"], analysis, [item], 1)
    item["flow_trace"].update(state="not_applicable", finding="This revision limits its claim; the previous branch remains documented.")
    item["flow_trace"]["boundaries"][0]["state"] = "not_applicable"
    update_analysis(materials["config"], analysis, [item], 2)
    assert check_analysis(materials["config"], analysis, require_settled=True)["settled"]


def test_history_detects_deleted_boundary_even_when_latest_hash_is_rewritten(materials):
    analysis = start(materials)
    item = flow_item(materials)
    item["flow_trace"]["boundaries"] = [boundary(item, state="answered")]
    update_analysis(materials["config"], analysis, [item], 1)
    update_analysis(materials["config"], analysis, [item], 2)
    value = read_json(analysis / "analysis.json")
    value["items"][0]["flow_trace"]["boundaries"] = []
    write_json(analysis / "analysis.json", value)
    write_json(analysis / "revisions/00000003.json", value)
    assert any("registered flow boundaries disappeared" in error for error in check_analysis(materials["config"], analysis)["errors"])


def test_flow_evidence_hash_change_requires_revision_and_retains_old_bytes(materials):
    analysis = start(materials)
    update_analysis(materials["config"], analysis, [flow_item(materials)], 1)
    old = (analysis / "revisions/00000002.json").read_bytes()
    materials["source"].write_text(materials["source"].read_text() + "// newly collected prerequisite branch\n")
    assert check_analysis(materials["config"], analysis)["status"] == "error"
    update_analysis(materials["config"], analysis, [flow_item(materials)], 2)
    assert check_analysis(materials["config"], analysis, require_settled=True)["settled"]
    assert (analysis / "revisions/00000002.json").read_bytes() == old


@pytest.mark.parametrize("mutation, message", [
    (lambda t: t["nodes"][0].update(symbol=""), "symbol"),
    (lambda t: t["nodes"][0].update(location=""), "location"),
    (lambda t: t["nodes"][0].update(evidence=[]), "scoped evidence"),
    (lambda t: t["nodes"][0]["evidence"][0].update(input_id="excluded-only"), "generation-visible"),
    (lambda t: t["nodes"][0]["evidence"][0].update(sha256="0" * 64), "sha256 mismatch"),
    (lambda t: t["edges"][0].update(to="N-missing"), "unknown node"),
    (lambda t: t["boundaries"][0].update(node_id="N-missing"), "unknown node"),
    (lambda t: t["boundaries"][0].update(work_item_ids=["Q-missing"]), "unknown reference"),
    (lambda t: t["boundaries"][0].update(resolution_node_ids=["N-missing"]), "unknown reference"),
    (lambda t: t["boundaries"][0].update(resolution_node_ids=["N-open"]), "downstream"),
    (lambda t: t["boundaries"][0].update(resolution_node_ids=[]), "resolution nodes or resolved work"),
    (lambda t: t.update(nodes=[n for n in t["nodes"] if n["kind"] != "entry"]), "entry node"),
    (lambda t: t.update(nodes=[n for n in t["nodes"] if n["kind"] != "terminal"]), "terminal node"),
])
def test_trace_references_and_provenance_are_checked(materials, mutation, message):
    analysis = start(materials)
    item = flow_item(materials)
    item["flow_trace"]["boundaries"] = [boundary(item, state="answered")]
    mutation(item["flow_trace"])
    with pytest.raises(ValueError, match=message):
        update_analysis(materials["config"], analysis, [item], 1)


@pytest.mark.parametrize("mutation", [
    lambda i: i.update(flow_trace=None),
    lambda i: i["flow_trace"].update(state={}),
    lambda i: i["flow_trace"].update(nodes=[[]]),
    lambda i: i["flow_trace"].update(edges=[None]),
    lambda i: i["flow_trace"].update(boundaries=[[]]),
    lambda i: i["flow_trace"]["nodes"][0].update(kind=[]),
    lambda i: i["flow_trace"]["edges"][0].update(to={}),
    lambda i: i["flow_trace"]["boundaries"][0].update(node_id=[]),
    lambda i: i["flow_trace"]["boundaries"][0].update(work_item_ids=[{}]),
    lambda i: i["flow_trace"]["boundaries"][0].update(resolution_node_ids=[{}]),
    lambda i: i["flow_trace"]["boundaries"][0].update(state=[]),
])
def test_malformed_trace_produces_validation_errors_without_crashing(materials, mutation):
    analysis = start(materials)
    item = flow_item(materials)
    item["flow_trace"]["boundaries"] = [boundary(item, state="answered")]
    mutation(item)
    with pytest.raises(ValueError, match="Invalid analysis update"):
        update_analysis(materials["config"], analysis, [item], 1)


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_legacy_analysis_resumes_without_inventing_flow_history(materials, version):
    analysis = start(materials)
    initial = read_json(analysis / "analysis.json")
    initial["format"] = f"rea-backend.analysis/{version}"
    write_json(analysis / "analysis.json", initial)
    write_json(analysis / "revisions/00000001.json", initial)
    before = (analysis / "revisions/00000001.json").read_bytes()
    item = work_item(materials, state="answered")
    item.pop("flow_trace")
    if version == "v1":
        item.pop("contract_checks")
    update_analysis(materials["config"], analysis, [item], 1)
    result = check_analysis(materials["config"], analysis, require_settled=True)
    assert result["settled"] and result["flow_tracking"] == "legacy/untracked"
    assert result["flow_counts"] == {} and result["flow_next_actions"] == []
    initialize_srs(materials["config"], materials["out"], template=materials["template"], analysis=analysis)
    assert (analysis / "revisions/00000001.json").read_bytes() == before
    assert read_json(materials["out"] / "analysis/analysis.json")["format"] == initial["format"]
