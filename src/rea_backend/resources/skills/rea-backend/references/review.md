# Independent content review

Review whether the requirements are supported by original evidence, omit important behavior, or leave the selected implementation scope unclear. Structural checks establish provenance and version relationships; they do not perform content review. Record fields are defined in [SRS formats](../../../docs/srs-format.md).

## Prepare an independent context

Provide the reviewer with the input configuration, permitted original materials, and the complete candidate bundle, including analysis revisions and the method snapshot. Confirm access permissions, then read the frozen files by ID in `method/manifest.json`. The current package's method may differ from the frozen one. An author summary, API inventory, expected conclusions, or historical answers are insufficient inputs.

Original materials must remain readable and match the frozen inventory. Analysis records help locate evidence and check registered questions; they do not replace it. An APK reviewer receives only that route's permitted materials. Method links and examples do not expand access. Record the actual inspected scope and any accidental access outside it.

A suitable handoff, without preselected business conclusions:

> Independently review this client's backend SRS. Verify its input policy and frozen baseline, read the frozen method, then inspect original materials and the candidate document. Select entry points yourself to find omitted capabilities, unresolved questions, and contradictions. For consequential interactions, reconstruct key branches from actual call sites before comparing them with the author's record. State inspected and uninspected scope, unresolved conclusions, and what static and runtime evidence each support. Produce a separate review.json bound to the final candidate files. Do not edit the author's document or describe static review as demonstrated client compatibility.

## Start from materials, then compare conclusions

1. **Select entry points independently.** Sample user, background, protocol, and data/dependency materials, prioritizing entry points, version conditions, and unexplored clues that could change backend responsibilities. Record why each was selected, actual inspected locations, and uninspected scope. Four discovery summaries do not establish exhaustive reading.
2. **Reconstruct consequential behavior.** From construction and call sites, inspect initial state, the first action, response-check order, exception handling, writeback, and termination. Read matching dependencies and overrides where needed; apply the frozen REA/smali procedure for APKs. Repeating the author's successful sequence is insufficient.
3. **Compare conclusions and gaps.** Separate evidence-supported behavior, inference, local policy, and missing information. Check whether local choices satisfy known consumer constraints; labeling a choice an assumption does not remove this check.
4. **Reconcile registered questions.** Check that candidates, local capabilities, deferrals, blockers, and scope exclusions retain reasons and references. Blocked work must remain visible as open gaps. Machine settlement cannot rule out undiscovered work; report newly found questions.

For analysis/v2 and v3, independently inspect the applicability and disposition of `consumer`, `wire`, `state`, and `resources`. Check narrowly scoped `not_applicable` claims and answers based only on declarations. Investigate relevant differences in absent/null/empty values, conversions, branch order, and writeback. Do not invent a rule where no evidence shows the behavior. A blocked dimension remains blocked at the parent item and gap level; deferring implementation does not resolve it. Analysis/v1 lacks these investigations and cannot be described as having passed them.

Where clues warrant it, inspect final storage ranges, comparisons after save/reload, the actual parser's accepted domain, early returns, loop bounds, and failure writeback. If file preservation is a local implementation policy, inspect its rejection paths and label its origin correctly. Record static deductions separately from executed probes.

## Content decisions

For analysis/v3, use review/v3 `sampling` to retain independent selection. Prioritize default entry points, prerequisites of major writes, parallel page dependencies, and the boundaries of the author's `answered`/`not_applicable` claims. Do not manufacture flows unsupported by the materials. Each sample records its rationale, actual symbols and originals, reconstructed chain, comparison, and omission disposition; list uninspected scope separately. A reviewer can discover an unregistered entry point without an existing author work item.

The checker verifies sample references and issue dispositions, not sampling sufficiency. Findings requiring new evidence or changed analysis return to discovery and a new baseline. A genuinely unavailable part may be accepted within a bounded SRS only while retaining blocked work and open gaps; a summary saying “later” is insufficient. Historical reviews retain their original format and meaning.

| Aspect | Review focus |
|---|---|
| Responsibility and scope | Local behavior or unused SDK declarations must not become mandatory backend features without evidence; selected checks must not define discovery scope. |
| Implementability | Requirements describe conditions, results, state, exceptions, and verification conditions; important unknowns constrain the claimed implementable scope. |
| Evidence boundary | Distinguish contracts, inference, local choices, project additions, and unknowns; identify disallowed sources and summary-only conclusions. |
| Cross-module consistency | Roles, ownership, state, time, errors, and data conventions agree; global defaults respect concrete consumer exceptions. |
| Goals and status | Current execution limitations do not silently narrow final requirements; discovery, acceptance, implementation, and runtime success stay separate. |

Acceptance must reflect completed review. It can apply to a bounded SRS with explicit unknowns and does not establish full product restoration. `ready_for_implementation` separately depends on unknowns, blockers, and input completeness; selecting a local implementation scope cannot erase wider gaps.

Actual-client compatibility claims require evidence of a real package, session entry, and selected workflows. This does not prevent earlier static SRS acceptance. Apply the frozen behavior-tracing procedure for evidence levels and initial-state declarations; HTTP success cannot replace real-client results.

## Revisions and binding

After draft structure checks, the author sets `index.status` to `reviewed` and submits the final candidate. This marks a candidate ready for review. The reviewer creates a separate record from the actual files; only an accepted independent record with matching hashes establishes acceptance. Identity and independence remain reviewer declarations; the program cannot prove separate contexts.

Issues identify capability, requirement, evidence, gap, or work-item IDs and explain the fact, impact, and required correction. Retain unresolved issues with reasons. Recheck changes and affected cross-module behavior before binding the final files. Any change to the document, index, run, inventory, frozen analysis, or frozen method invalidates old review bindings. Additional evidence or changed analysis requires a new baseline.

Finally run the frozen-format check with `--require-reviewed`. Without an independent reviewer, deliver a self-checked draft and do not assert independent acceptance. Passing a command does not replace this substantive review.
