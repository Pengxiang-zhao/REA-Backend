"""Structural checks for independent, inventory-bound reviewer samples.

These records make review scope inspectable. They cannot establish that the
reviewer was independent, read the cited material, or found every missing path.
"""
from __future__ import annotations

from pathlib import PurePosixPath

SAMPLE_FIELDS = {"id", "entry", "selection_reason", "risk_focus", "author_item_ids",
                 "evidence", "reconstructed_chain", "comparison"}
EVIDENCE_FIELDS = {"id", "input_id", "path", "sha256", "symbol", "location", "note"}
CHAIN_KINDS = {"entry", "prerequisite", "request", "consumer", "state", "terminal", "other"}


def check_sampling(c, value, *, available, analysis_items, gaps, issues, accepted):
    """Check explicit scope, direct raw references, and finding dispositions.

    ``available`` is rebuilt from the current authorized inputs and compared
    with the frozen inventory by the caller, not supplied by the reviewer.
    """
    sampling = c.obj(value, "review.sampling", {"selection_rationale", "not_inspected", "samples"})
    c.string(sampling.get("selection_rationale"), "review.sampling.selection_rationale")
    c.strings(sampling.get("not_inspected"), "review.sampling.not_inspected")
    samples = c.records(sampling.get("samples"), "review.sampling.samples", SAMPLE_FIELDS, nonempty=True)
    for sid, sample in samples.items():
        label = f"review sample {sid}"
        for field in ("entry", "selection_reason"):
            c.string(sample.get(field), f"{label}.{field}")
        c.strings(sample.get("risk_focus"), f"{label}.risk_focus", True)
        author_ids = c.refs(sample.get("author_item_ids"), analysis_items, f"{label}.author_item_ids")
        evidence = c.records(sample.get("evidence"), f"{label}.evidence", EVIDENCE_FIELDS, nonempty=True)
        for eid, row in evidence.items():
            ref_label = f"{label}.evidence.{eid}"
            for field in ("symbol", "location", "note"):
                c.string(row.get(field), f"{ref_label}.{field}")
            iid, relative = row.get("input_id"), row.get("path")
            c.string(iid, f"{ref_label}.input_id")
            c.sha(row.get("sha256"), f"{ref_label}.sha256")
            if not c.string(relative, f"{ref_label}.path"):
                continue
            path = PurePosixPath(relative)
            safe = not path.is_absolute() and ".." not in path.parts and "\\" not in relative and str(path) == relative
            if not c.check(safe, f"{ref_label}: canonical relative path required"):
                continue
            entry = available.get((iid, relative)) if isinstance(iid, str) else None
            c.check(entry is not None, f"{ref_label}: raw evidence must be generation-visible and present in frozen inventory")
            if entry is not None:
                c.check(row.get("sha256") == entry["sha256"], f"{ref_label}: raw evidence hash differs from frozen inventory")
        chain = c.records(sample.get("reconstructed_chain"), f"{label}.reconstructed_chain",
                          {"id", "kind", "observation", "evidence_ids"}, nonempty=True)
        used_evidence = set()
        for nid, node in chain.items():
            node_label = f"{label}.reconstructed_chain.{nid}"
            c.enum(node.get("kind"), CHAIN_KINDS, f"{node_label}.kind")
            c.string(node.get("observation"), f"{node_label}.observation")
            used_evidence.update(c.refs(node.get("evidence_ids"), evidence, f"{node_label}.evidence_ids", True))
        c.check(set(evidence) <= used_evidence, f"{label}: raw evidence must be used by the reconstructed chain")
        comparison = c.obj(sample.get("comparison"), f"{label}.comparison",
                           {"finding", "status", "issue_ids", "work_item_ids", "gap_ids"})
        c.string(comparison.get("finding"), f"{label}.comparison.finding")
        status = comparison.get("status")
        c.enum(status, {"matched", "discrepancy"}, f"{label}.comparison.status")
        issue_ids = c.refs(comparison.get("issue_ids"), issues, f"{label}.comparison.issue_ids", status == "discrepancy")
        work_ids = c.refs(comparison.get("work_item_ids"), analysis_items, f"{label}.comparison.work_item_ids")
        gap_ids = c.refs(comparison.get("gap_ids"), gaps, f"{label}.comparison.gap_ids")
        if status == "matched":
            c.check(bool(author_ids), f"{label}: matched sample must identify compared author work")
        if status != "discrepancy":
            continue
        c.check(bool(work_ids or gap_ids), f"{label}: discrepancy must map to existing work items or gaps")
        mapped = set(work_ids) | set(gap_ids)
        for issue_id in issue_ids:
            if issue_id in issues:
                targets = issues[issue_id].get("target_ids")
                c.check(isinstance(targets, list) and bool(mapped.intersection(x for x in targets if isinstance(x, str))),
                        f"{label}: issue {issue_id} must target the discrepancy's work or gap mapping")
        if not accepted:
            continue
        open_gaps = {gid for gid in gap_ids if gid in gaps and gaps[gid].get("status") == "open"}
        blocked = [analysis_items[wid] for wid in work_ids
                   if wid in analysis_items and analysis_items[wid].get("state") == "blocked"]
        unresolved_work = [wid for wid in work_ids if wid in analysis_items
                           and analysis_items[wid].get("state") not in ("answered", "out_of_scope")]
        open_issues = [iid for iid in issue_ids if iid in issues and issues[iid].get("status") == "open"]
        if open_gaps or unresolved_work or open_issues:
            c.check(bool(open_gaps), f"{label}: accepted unresolved discrepancy must retain an open SRS gap")
            c.check(all(any(gid in item.get("gap_ids", []) for item in blocked) for gid in open_gaps),
                    f"{label}: accepted unresolved discrepancy needs blocked work retaining each open gap")
            c.check(bool(open_issues), f"{label}: unresolved discrepancy cannot be hidden behind resolved review issues")
        else:
            c.check(bool(issue_ids) and all(issues[iid].get("status") == "resolved" for iid in issue_ids if iid in issues),
                    f"{label}: accepted discrepancy must have resolved issues or explicit unresolved gap mapping")
