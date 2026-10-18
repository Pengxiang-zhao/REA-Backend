"""Registered investigation stays resumable until an explicit SRS freeze."""
import pytest

from rea_backend.analysis import CONTRACT_KINDS, check_analysis, initialize_analysis, update_analysis
from rea_backend.srs import check_srs, initialize_srs
from test_srs import materials, digest, read_json, reviewed, valid_index, write_document, write_json


def work_item(materials, *, iid="Q-articles", state="pending"):
    source = {"input_id": "client", "path": "Article.kt", "sha256": digest(materials["source"])}
    item = {"id": iid, "clue": "The client declares article synchronization.",
            "question": "What response shape does article synchronization consume?", "area": "protocol",
            "sources": [source], "state": state,
            "next_action": "Inspect the declared DTO and remaining call paths." if state in ("pending", "blocked") else "",
            "depends_on": [], "evidence": [{**source, "note": "The declared DTO has integer id and string title."}] if state == "answered" else [],
            "finding": "" if state == "pending" else "The available declaration establishes DTO shape only.",
            "gap_ids": ["G-analysis"] if state == "blocked" else []}
    # This fixture investigates one DTO declaration, not runtime semantics.
    item["contract_checks"] = {
        kind: {"state": "pending" if state == "pending" else "not_applicable",
               "finding": "" if state == "pending" else "This work item only inventories a DTO declaration; consumer behavior is outside this scoped fixture question.",
               "evidence": [] if state == "pending" else [{**source, "note": "Scope is the DTO declaration fixture only."}],
               "next_action": "Inspect whether this declaration is used in this contract dimension." if state == "pending" else "",
               "gap_ids": []}
        for kind in sorted(CONTRACT_KINDS)
    }
    item["flow_trace"] = {
        "state": "pending" if state == "pending" else "not_applicable",
        "scope": "Inventory this DTO declaration; no runtime user flow is claimed.",
        "finding": "" if state == "pending" else "The fixture source contains only a DTO declaration.",
        "evidence": [] if state == "pending" else [{**source, "note": "The synthetic input is scoped to a DTO declaration."}],
        "next_action": "Inspect whether the approved material includes a user flow." if state == "pending" else "",
        "gap_ids": [], "nodes": [], "edges": [], "boundaries": [],
    }
    return item


def tracked_bundle(materials, *, state="answered", method_manifest=None):
    analysis = materials["root"] / "analysis"
    initialize_analysis(materials["config"], analysis)
    update_analysis(materials["config"], analysis, [work_item(materials, state=state)], expected_revision=1)
    initialize_srs(materials["config"], materials["out"], template=materials["template"],
                   analysis=analysis, method_manifest=method_manifest)
    index = valid_index(materials)
    index["gaps"] = read_json(materials["out"] / "index.json")["gaps"]
    write_json(materials["out"] / "index.json", index)
    write_document(materials["out"] / "backend-srs.md")
    return analysis


def test_resume_retains_omitted_items_and_rejects_stale_updates(materials):
    analysis = materials["root"] / "analysis"
    initialize_analysis(materials["config"], analysis)
    first, second = work_item(materials), work_item(materials, iid="Q-retries")
    update_analysis(materials["config"], analysis, [first], expected_revision=1)
    update_analysis(materials["config"], analysis, [second], expected_revision=2)
    report = check_analysis(materials["config"], analysis)
    assert report["status"] == "checked"
    assert report["counts"] == {"pending": 2}
    assert report["settled"] is False
    assert report["unresolved_ids"] == ["Q-articles", "Q-retries"]
    before = (analysis / "analysis.json").read_bytes()
    with pytest.raises(ValueError, match="Stale"):
        update_analysis(materials["config"], analysis, [work_item(materials, state="answered")], expected_revision=2)
    assert (analysis / "analysis.json").read_bytes() == before
    assert len(list((analysis / "revisions").glob("*.json"))) == 3


def test_pending_work_cannot_be_frozen_or_mislabeled_settled(materials):
    analysis = materials["root"] / "analysis"
    initialize_analysis(materials["config"], analysis)
    assert not check_analysis(materials["config"], analysis)["settled"]
    update_analysis(materials["config"], analysis, [work_item(materials)], expected_revision=1)
    assert check_analysis(materials["config"], analysis, require_settled=True)["status"] == "error"
    with pytest.raises(ValueError, match="pending"):
        initialize_srs(materials["config"], materials["out"], template=materials["template"], analysis=analysis)
    assert not materials["out"].exists()


@pytest.mark.parametrize("mutation", [
    lambda item: item.update(evidence=[]),
    lambda item: item.update(finding=""),
    lambda item: item.update(sources=[]),
])
def test_answered_requires_sources_evidence_and_finding(materials, mutation):
    analysis = materials["root"] / "analysis"
    initialize_analysis(materials["config"], analysis)
    item = work_item(materials, state="answered")
    mutation(item)
    with pytest.raises(ValueError, match="Invalid analysis"):
        update_analysis(materials["config"], analysis, [item], expected_revision=1)


def test_answered_dependencies_must_be_resolved_and_cycles_are_rejected(materials):
    analysis = materials["root"] / "analysis"
    initialize_analysis(materials["config"], analysis)
    first, second = work_item(materials), work_item(materials, iid="Q-other", state="answered")
    second["depends_on"] = [first["id"]]
    with pytest.raises(ValueError, match="unresolved dependencies"):
        update_analysis(materials["config"], analysis, [first, second], expected_revision=1)
    second = work_item(materials, iid="Q-other")
    second["depends_on"], first["depends_on"] = [first["id"]], [second["id"]]
    with pytest.raises(ValueError, match="cyclic"):
        update_analysis(materials["config"], analysis, [first, second], expected_revision=1)


def test_blocked_is_retained_and_requires_gap_mapping_before_freeze(materials):
    analysis = materials["root"] / "analysis"
    initialize_analysis(materials["config"], analysis)
    item = work_item(materials, state="blocked")
    item["gap_ids"] = []
    update_analysis(materials["config"], analysis, [item], expected_revision=1)
    report = check_analysis(materials["config"], analysis)
    assert report["status"] == "checked" and not report["settled"]
    with pytest.raises(ValueError, match="gap_ids"):
        initialize_srs(materials["config"], materials["out"], template=materials["template"], analysis=analysis)
    item["gap_ids"] = ["G-analysis"]
    update_analysis(materials["config"], analysis, [item], expected_revision=2)
    report = check_analysis(materials["config"], analysis, require_settled=True)
    assert report["settled"] and report["unresolved_ids"] == ["Q-articles"]


@pytest.mark.parametrize("rewrite_latest_revision", [False, True])
def test_registered_items_cannot_silently_disappear(materials, rewrite_latest_revision):
    analysis = materials["root"] / "analysis"
    initialize_analysis(materials["config"], analysis)
    update_analysis(materials["config"], analysis, [work_item(materials)], expected_revision=1)
    update_analysis(materials["config"], analysis, [work_item(materials, iid="Q-other")], expected_revision=2)
    value = read_json(analysis / "analysis.json")
    value["items"] = value["items"][1:]
    write_json(analysis / "analysis.json", value)
    if rewrite_latest_revision:
        write_json(analysis / "revisions/00000003.json", value)
    report = check_analysis(materials["config"], analysis)
    assert report["status"] == "error"
    assert any("disappeared" in e or "persisted revision" in e for e in report["errors"])


def test_new_evidence_is_collected_before_srs_inventory_freeze(materials):
    analysis = materials["root"] / "analysis"
    initialize_analysis(materials["config"], analysis)
    update_analysis(materials["config"], analysis, [work_item(materials)], expected_revision=1)
    assert not (analysis / "inventory.json").exists()
    trace = materials["root"] / "trace.json"
    trace.write_text('{"observation": "article synchronization response"}\n')
    config = read_json(materials["config"])
    config["inputs"].append({"id": "trace", "kind": "rea_evidence", "path": "trace.json", "version": "capture-1",
                             "access": "generation", "complete": True, "limitations": [], "exclude": []})
    write_json(materials["config"], config)
    item = work_item(materials, state="answered")
    item["evidence"].append({"input_id": "trace", "path": "trace.json", "sha256": digest(trace), "note": "Synthetic capture."})
    update_analysis(materials["config"], analysis, [item], expected_revision=2)
    initialize_srs(materials["config"], materials["out"], template=materials["template"], analysis=analysis)
    assert {i["id"] for i in read_json(materials["out"] / "inventory.json")["inputs"]} == {"client", "trace"}
    assert read_json(materials["out"] / "analysis/analysis.json")["revision"] == 3


def test_evidence_hash_change_requires_explicit_revision(materials):
    analysis = materials["root"] / "analysis"
    initialize_analysis(materials["config"], analysis)
    update_analysis(materials["config"], analysis, [work_item(materials, state="answered")], expected_revision=1)
    before = read_json(analysis / "analysis.json")["items"][0]["sources"][0]["sha256"]
    materials["source"].write_text(materials["source"].read_text() + "// supplementary declaration\n")
    assert check_analysis(materials["config"], analysis)["status"] == "error"
    update_analysis(materials["config"], analysis, [work_item(materials, state="answered")], expected_revision=2)
    assert check_analysis(materials["config"], analysis, require_settled=True)["status"] == "checked"
    assert read_json(analysis / "revisions/00000002.json")["items"][0]["sources"][0]["sha256"] == before


def test_material_changed_during_freeze_does_not_create_a_mixed_baseline(materials, monkeypatch):
    import rea_backend.srs as module
    analysis = materials["root"] / "analysis"
    initialize_analysis(materials["config"], analysis)
    update_analysis(materials["config"], analysis, [work_item(materials, state="answered")], expected_revision=1)
    original = module._snapshot
    def changed_input(*args, **kwargs):
        materials["source"].write_text("Changed after analysis validation.\n")
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "_snapshot", changed_input)
    with pytest.raises(ValueError, match="Analysis freeze failed"):
        initialize_srs(materials["config"], materials["out"], template=materials["template"], analysis=analysis)
    assert not materials["out"].exists()


def test_continuing_analysis_does_not_modify_or_invalidate_its_frozen_srs(materials):
    analysis = tracked_bundle(materials)
    reviewed(materials)
    frozen = (materials["out"] / "analysis/analysis.json").read_bytes()
    update_analysis(materials["config"], analysis, [work_item(materials, iid="Q-new")], expected_revision=2)
    assert check_analysis(materials["config"], analysis)["settled"] is False
    report = check_srs(materials["config"], materials["out"], require_reviewed=True)
    assert report["status"] == "checked" and report["ready_for_implementation"]
    assert (materials["out"] / "analysis/analysis.json").read_bytes() == frozen
