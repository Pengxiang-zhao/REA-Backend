"""Review samples bind independent scope and findings to authorized raw files."""
import pytest

from rea_backend.analysis import initialize_analysis, update_analysis
from rea_backend.srs import initialize_srs
from test_analysis import tracked_bundle, work_item
from test_srs import (materials, bundle, check, read_json, reviewed, valid_index,
                      write_document, write_json)


def make_review(materials, *, state="answered"):
    tracked_bundle(materials, state=state)
    return reviewed(materials)


def save_check(materials, review):
    write_json(materials["out"] / "review.json", review)
    return check(materials, require_reviewed=True)


def discrepancy(review, *, unresolved=False):
    review["issues"] = [{
        "id": "ISSUE-caller", "severity": "low", "status": "open" if unresolved else "resolved",
        "target_ids": ["Q-articles"], "finding": "The sample found an omitted caller constraint.",
        "resolution": "" if unresolved else "The new frozen work item and requirement record the corrected constraint.",
    }]
    review["sampling"]["samples"][0]["comparison"] = {
        "status": "discrepancy", "finding": "Compared the raw caller with the author's registered analysis.",
        "issue_ids": ["ISSUE-caller"], "work_item_ids": ["Q-articles"],
        "gap_ids": ["G-analysis"] if unresolved else [],
    }
    return review


def test_new_analysis_requires_inspectable_raw_samples_without_rewriting_bundle(materials):
    review = make_review(materials)
    before = {p.relative_to(materials["out"]): p.read_bytes()
              for p in materials["out"].rglob("*") if p.is_file()}
    result = check(materials, require_reviewed=True)
    assert review["format"] == "rea-backend.srs-review/v3"
    assert result["status"] == "checked" and result["ready_for_implementation"]
    assert result["review_sampling"] == "tracked" and result["review_sample_count"] == 1
    assert before == {p.relative_to(materials["out"]): p.read_bytes()
                      for p in materials["out"].rglob("*") if p.is_file()}


@pytest.mark.parametrize("mutation, expected", [
    (lambda r: r.pop("sampling"), "sampling"),
    (lambda r: r["sampling"].update(samples=[]), "nonempty array"),
    (lambda r: r["sampling"].pop("not_inspected"), "not_inspected"),
    (lambda r: r["sampling"].update(selection_rationale=""), "selection_rationale"),
    (lambda r: r["sampling"]["samples"][0].update(entry=""), "entry"),
    (lambda r: r["sampling"]["samples"][0].update(risk_focus=[]), "risk_focus"),
    (lambda r: r["sampling"]["samples"][0].update(author_item_ids=[]), "compared author work"),
    (lambda r: r["sampling"]["samples"][0].update(reconstructed_chain=[]), "reconstructed_chain"),
    (lambda r: r["sampling"]["samples"][0]["reconstructed_chain"][0].update(evidence_ids=["EV-GET"]), "unknown reference"),
    (lambda r: r["sampling"]["samples"][0]["reconstructed_chain"][0].update(observation=""), "observation"),
    (lambda r: r["sampling"]["samples"][0]["evidence"][0].update(sha256="0" * 64), "hash differs"),
    (lambda r: r["sampling"]["samples"][0]["evidence"][0].update(input_id="excluded"), "generation-visible"),
    (lambda r: r["sampling"]["samples"][0]["evidence"][0].update(path="../Article.kt"), "canonical relative"),
    (lambda r: r["sampling"]["samples"][0]["evidence"][0].update(symbol=""), "symbol"),
    (lambda r: r["sampling"]["samples"][0]["evidence"][0].update(location=""), "location"),
    (lambda r: r["sampling"]["samples"][0]["comparison"].update(work_item_ids=["Q-missing"]), "unknown reference"),
])
def test_incomplete_or_unbound_review_sampling_is_not_accepted(materials, mutation, expected):
    review = make_review(materials)
    mutation(review)
    result = save_check(materials, review)
    assert result["status"] == "error" and result["review"] == "not_accepted"
    assert any(expected in error for error in result["errors"])


def test_author_index_reference_cannot_replace_raw_review_evidence(materials):
    review = make_review(materials)
    sample = review["sampling"]["samples"][0]
    sample["evidence"] = [{"id": "RAW-articles", "evidence_id": "EV-GET", "note": "Read the author's summary."}]
    result = save_check(materials, review)
    assert result["status"] == "error" and not result["ready_for_implementation"]


def test_fully_inspected_declared_scope_may_have_no_additional_exclusions(materials):
    review = make_review(materials)
    review["sampling"].update(
        selection_rationale="Read the entire four-line declaration fixture; this review does not cover a running App.",
        not_inspected=[],
    )
    result = save_check(materials, review)
    assert result["status"] == "checked" and result["review_sampling"] == "tracked"
    assert "not semantic completeness" in result["note"]


def test_new_bundle_cannot_downgrade_to_v2_review_without_samples(materials):
    review = make_review(materials)
    review.update(format="rea-backend.srs-review/v2")
    review.pop("sampling")
    result = save_check(materials, review)
    assert result["status"] == "error" and result["review_sampling"] == "not_recorded"
    assert any("expected rea-backend.srs-review/v3" in error for error in result["errors"])


def test_resolved_discrepancy_can_be_accepted_against_new_frozen_work(materials):
    review = discrepancy(make_review(materials))
    result = save_check(materials, review)
    assert result["status"] == "checked" and result["ready_for_implementation"]


def test_explicit_unresolved_discrepancy_remains_unready_even_if_document_accepted(materials):
    review = discrepancy(make_review(materials, state="blocked"), unresolved=True)
    result = save_check(materials, review)
    assert result["status"] == "checked" and result["review"] == "accepted"
    assert not result["ready_for_implementation"]


@pytest.mark.parametrize("mutation, expected", [
    (lambda r: r["sampling"]["samples"][0]["comparison"].update(issue_ids=[]), "issue_ids"),
    (lambda r: r["sampling"]["samples"][0]["comparison"].update(work_item_ids=[], gap_ids=[]), "must map"),
    (lambda r: r["issues"][0].update(target_ids=["FR-articles-001"]), "must target"),
    (lambda r: r["issues"][0].update(status="open", resolution=""), "retain an open SRS gap"),
])
def test_discrepancy_cannot_be_declared_closed_without_actionable_disposition(materials, mutation, expected):
    review = discrepancy(make_review(materials))
    mutation(review)
    result = save_check(materials, review)
    assert result["status"] == "error" and not result["ready_for_implementation"]
    assert any(expected in error for error in result["errors"])


def test_resolved_review_issue_cannot_hide_open_frozen_analysis_gap(materials):
    review = discrepancy(make_review(materials, state="blocked"), unresolved=True)
    review["issues"][0].update(status="resolved", resolution="The requirement was documented, but caller remains unavailable.")
    result = save_check(materials, review)
    assert result["status"] == "error"
    assert any("hidden behind resolved review issues" in error for error in result["errors"])


def test_accepted_discrepancy_cannot_leave_gap_without_blocked_analysis_mapping(materials):
    make_review(materials)
    index = read_json(materials["out"] / "index.json")
    index["gaps"].append({"id": "G-analysis", "question": "What does the missing caller do?",
                          "impact": "Unknown consumer behavior.", "blocking": False, "status": "open",
                          "resolution": "", "evidence_ids": []})
    write_json(materials["out"] / "index.json", index)
    review = discrepancy(reviewed(materials), unresolved=True)
    result = save_check(materials, review)
    assert result["status"] == "error"
    assert any("blocked work retaining each open gap" in error for error in result["errors"])


def test_legacy_untracked_srs_keeps_original_review_and_explicit_sampling_limit(bundle):
    reviewed(bundle)
    before = (bundle["out"] / "review.json").read_bytes()
    result = check(bundle, require_reviewed=True)
    assert result["status"] == "checked" and result["review"] == "accepted"
    assert result["review_sampling"] == "legacy/untracked" and result["review_sample_count"] == 0
    assert (bundle["out"] / "review.json").read_bytes() == before


@pytest.mark.parametrize("format", ["rea-backend.analysis/v1", "rea-backend.analysis/v2"])
def test_legacy_tracked_review_acceptance_does_not_invent_v3_samples(materials, format):
    analysis = materials["root"] / "analysis"
    initialize_analysis(materials["config"], analysis)
    # Construct an old fixture before recording work; no frozen result is upgraded.
    initial = read_json(analysis / "analysis.json")
    initial["format"] = format
    write_json(analysis / "analysis.json", initial)
    write_json(analysis / "revisions/00000001.json", initial)
    item = work_item(materials, state="answered")
    item.pop("flow_trace")
    if format.endswith("/v1"):
        item.pop("contract_checks")
    update_analysis(materials["config"], analysis, [item], expected_revision=1)
    initialize_srs(materials["config"], materials["out"], template=materials["template"], analysis=analysis)
    write_json(materials["out"] / "index.json", valid_index(materials))
    write_document(materials["out"] / "backend-srs.md")
    review = reviewed(materials)
    before = {p.relative_to(materials["out"]): p.read_bytes()
              for p in materials["out"].rglob("*") if p.is_file()}
    result = check(materials, require_reviewed=True)
    assert review["format"] == "rea-backend.srs-review/v2" and "sampling" not in review
    assert result["status"] == "checked" and result["ready_for_implementation"]
    assert result["review_sampling"] == "legacy/untracked"
    assert before == {p.relative_to(materials["out"]): p.read_bytes()
                      for p in materials["out"].rglob("*") if p.is_file()}
