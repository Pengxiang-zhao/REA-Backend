"""A parent conclusion must not erase unresolved, source-bound contract work."""
from copy import deepcopy

import pytest

from rea_backend.analysis import check_analysis, initialize_analysis, update_analysis
from rea_backend.srs import check_srs, initialize_srs
from test_analysis import work_item
from test_srs import materials, digest, read_json, reviewed, valid_index, write_document, write_json


def start(materials):
    analysis = materials["root"] / "analysis"
    initialize_analysis(materials["config"], analysis)
    return analysis


def blocked_consumer(materials):
    item = work_item(materials, state="blocked")
    item["contract_checks"]["consumer"] = {
        "state": "blocked", "finding": "Only the DTO is available; the null and empty response branches are not visible.",
        "evidence": [], "next_action": "Collect the calling method and its response parser from approved inputs.",
        "gap_ids": ["G-analysis"],
    }
    return item


@pytest.mark.parametrize("mutation", [
    lambda i: i.pop("contract_checks"),
    lambda i: i["contract_checks"].pop("consumer"),
    lambda i: i["contract_checks"].update(unrecognized={}),
    lambda i: i["contract_checks"]["wire"].update(state="answered", evidence=[]),
    lambda i: i["contract_checks"]["resources"].update(evidence=[]),
    lambda i: i["contract_checks"]["state"].update(finding=""),
    lambda i: i["contract_checks"]["consumer"]["evidence"][0].update(sha256="0" * 64),
    lambda i: i.update(contract_checks=[]),
])
def test_contract_disposition_requires_all_dimensions_and_bound_evidence(materials, mutation):
    analysis = start(materials)
    item = work_item(materials, state="answered")
    before = (analysis / "analysis.json").read_bytes()
    mutation(item)
    with pytest.raises(ValueError, match="Invalid analysis update"):
        update_analysis(materials["config"], analysis, [item], 1)
    assert (analysis / "analysis.json").read_bytes() == before


@pytest.mark.parametrize("parent_state", ["answered", "out_of_scope"])
@pytest.mark.parametrize("child_state", ["pending", "blocked"])
def test_resolved_parent_cannot_hide_open_contract_work(materials, parent_state, child_state):
    analysis = start(materials)
    item = work_item(materials, state=parent_state)
    item["contract_checks"]["consumer"].update(state=child_state, next_action="Inspect the caller.")
    with pytest.raises(ValueError, match="resolved parent"):
        update_analysis(materials["config"], analysis, [item], 1)


def test_blocked_parent_cannot_freeze_unexamined_children(materials):
    analysis = start(materials)
    item = blocked_consumer(materials)
    item["contract_checks"]["wire"].update(state="pending", next_action="Read the ID conversion.")
    update_analysis(materials["config"], analysis, [item], 1)
    report = check_analysis(materials["config"], analysis)
    assert report["status"] == "checked" and not report["settled"]
    assert {r["id"] for r in report["contract_next_actions"]} == {"Q-articles/consumer", "Q-articles/wire"}
    with pytest.raises(ValueError, match="pending contract"):
        initialize_srs(materials["config"], materials["out"], template=materials["template"], analysis=analysis)
    assert not materials["out"].exists()


def test_contract_gap_must_be_carried_by_parent_and_stay_open_in_srs(materials):
    analysis = start(materials)
    item = blocked_consumer(materials)
    missing_gap = deepcopy(item)
    missing_gap["gap_ids"] = []
    with pytest.raises(ValueError, match="parent gap_ids"):
        update_analysis(materials["config"], analysis, [missing_gap], 1)
    update_analysis(materials["config"], analysis, [item], 1)
    report = check_analysis(materials["config"], analysis, require_settled=True)
    assert report["settled"] and report["contract_counts"]["blocked"] == 1
    initialize_srs(materials["config"], materials["out"], template=materials["template"], analysis=analysis)
    index = valid_index(materials)
    index["gaps"] = read_json(materials["out"] / "index.json")["gaps"]
    write_json(materials["out"] / "index.json", index)
    write_document(materials["out"] / "backend-srs.md")
    reviewed(materials)
    result = check_srs(materials["config"], materials["out"], require_reviewed=True)
    assert result["status"] == "checked" and not result["ready_for_implementation"]
    index["gaps"][0].update(status="resolved", resolution="Implementation was postponed.")
    write_json(materials["out"] / "index.json", index)
    assert any("blocked item must retain open gap" in error
               for error in check_srs(materials["config"], materials["out"])["errors"])


def test_contract_checks_cannot_be_removed_or_downgraded_in_history(materials):
    analysis = start(materials)
    update_analysis(materials["config"], analysis, [work_item(materials)], 1)
    value = read_json(analysis / "analysis.json")
    value["format"] = "rea-backend.analysis/v1"
    for item in value["items"]:
        item.pop("contract_checks")
        item.pop("flow_trace")
    write_json(analysis / "analysis.json", value)
    write_json(analysis / "revisions/00000002.json", value)
    assert any("invalid revision" in error for error in check_analysis(materials["config"], analysis)["errors"])


def test_legacy_v1_can_resume_and_freeze_without_rewriting_history(materials):
    analysis = start(materials)
    initial = read_json(analysis / "analysis.json")
    initial["format"] = "rea-backend.analysis/v1"
    write_json(analysis / "analysis.json", initial)
    write_json(analysis / "revisions/00000001.json", initial)
    original = (analysis / "revisions/00000001.json").read_bytes()
    item = work_item(materials, state="answered")
    item.pop("contract_checks")
    item.pop("flow_trace")
    update_analysis(materials["config"], analysis, [item], 1)
    report = check_analysis(materials["config"], analysis, require_settled=True)
    assert report["settled"] and report["contract_tracking"] == "legacy/untracked"
    assert report["contract_counts"] == {}
    initialize_srs(materials["config"], materials["out"], template=materials["template"], analysis=analysis)
    assert (analysis / "revisions/00000001.json").read_bytes() == original
    assert read_json(materials["out"] / "analysis/analysis.json")["format"] == "rea-backend.analysis/v1"


def test_unavailable_contract_evidence_requires_new_material_and_revision(materials):
    analysis = start(materials)
    item = blocked_consumer(materials)
    update_analysis(materials["config"], analysis, [item], 1)
    old = (analysis / "revisions/00000002.json").read_bytes()
    materials["source"].write_text("// Synthetic consumer: null stops; [] continues; empty token is a next page.\n")
    resolved = work_item(materials, state="answered")
    resolved["contract_checks"]["consumer"].update(
        state="answered", finding="The fixture consumer distinguishes null, empty collection and empty continuation.")
    update_analysis(materials["config"], analysis, [resolved], 2)
    assert check_analysis(materials["config"], analysis, require_settled=True)["settled"]
    assert (analysis / "revisions/00000002.json").read_bytes() == old
    assert read_json(analysis / "analysis.json")["items"][0]["sources"][0]["sha256"] == digest(materials["source"])
