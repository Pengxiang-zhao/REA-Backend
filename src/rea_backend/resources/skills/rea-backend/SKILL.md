---
name: rea-backend
description: Discover backend requirements from fixed client source or APK evidence, write and independently review an SRS, then implement and validate a standalone backend. Use for client-to-backend reconstruction with traceable inputs and explicit unknowns.
---

# REA-Backend

Build an independent backend from the behaviors exposed by a fixed client version. The agent investigates evidence, authors requirements and code, and interprets results. The CLI records revisions, freezes inputs, checks relationships, packages builds, and executes explicit validation plans; it does not invoke a model or infer business rules.

## Start or resume

Read the input configuration first: client identity and version, input route, permitted evidence, and runtime goals. If none exists, create one from the [input template](../../templates/srs-inputs.json); do not require the user to enumerate every feature in advance. Load only the references relevant to the current stage.

For an existing analysis, read the current `analysis.json` revision, unresolved work items, and their original materials before continuing. For an existing SRS, identify its frozen baseline and review status. Preserve delivered baselines; new evidence and changed findings belong in a new baseline. Summaries and earlier requirements cannot replace the current original evidence.

New analysis uses v3: each work item records `consumer`, `wire`, `state`, and `resources` investigations, plus a bounded `flow_trace` of actual entry points, prerequisites, dependencies, consumers, and untraced boundaries. A declaration-only investigation may use an evidenced, narrowly scoped `not_applicable`; discovered callers still require their own investigation. Use reported next actions for targeted collection. Pending boundaries prevent freezing; unavailable evidence remains blocked with an explicit gap.

The default method is `rea-backend/v1`. An independent reviewer selects entry points from original materials and records actual samples, reconstructed chains, and omissions. When persisted values affect comparison, merging, or retries, trace through storage and reload to the final consumer. Client evidence determines the business rule. Older artifacts retain their frozen method and must not be relabeled as having passed newer checks.

## Stage routing

| Stage | Read and produce |
|---|---|
| Discover, collect, and settle | [Requirements discovery](../../docs/requirements-discovery.md): investigate four entry-point categories; retain candidates, unknowns, and local choices. |
| Analyze APKs or stateful interactions | [Client behavior tracing](../../docs/apk-behavior-tracing.md): use the actual REA catalog, decoded resources, and smali; trace consumption and termination. |
| Freeze inputs, analysis, and method | [Formats and commands](../../docs/srs-format.md): settle registered questions and create a traceable SRS baseline. |
| Write requirements and index | [SRS template](../../templates/backend-requirements.md), machine formats, and, when needed, [requirements versus design](../../docs/backend-requirements.md). |
| Independently review and revise | [Review procedure](references/review.md): sample original entry points and reconstruct consequential branches under the frozen method. |
| Implement and package | [SRS to backend](../../docs/srs-to-backend.md): choose an explicit scope, author service code and checks, then bind them to the reviewed SRS. |
| Validate with the client | [SRS to backend](../../docs/srs-to-backend.md) and [Android runner](../../docs/android-run.md): retain early and final evidence, diagnose failures, and return to the appropriate stage. |

Commands run in a Python environment where this package is installed. `rea-backend init-workspace --out PATH` exports this skill, its documentation, and templates together; retain that directory layout so relative references work. Full command and JSON definitions have one maintenance location in the linked format documents. See [agent and tool responsibilities](../../docs/srs-agent.md) for execution boundaries.

## Invariants

- Links do not expand input permission. The APK route uses only its declared materials, without source-route requirements, implementation, or answer files. Input declarations provide provenance, not operating-system isolation; report accidental access.
- Route isolation also covers task summaries, shared metadata, and caches. A coordinator can handle cross-route overviews; each author and reviewer receives only its permitted materials and neutral tool information.
- Derive responsibilities from actual entry points and consumers. Retain references to original materials; API summaries and previous conclusions are navigation aids.
- Settling a worklist means registered questions have dispositions. Structural checks and freezing establish provenance and version relationships; they do not prove complete discovery, correct semantics, or full client compatibility.
- Preserve unknowns, gaps, deferred work, and explicit local policies. Removing unresolved items or failed checks cannot establish completion.
- Reduce repeated work with tools, verifiable evidence reuse, and independent parallel tasks. Preserve necessary discovery, pre-implementation freezing, independent review, repairs, and client validation required by the selected scope. Final evidence must identify the actual build.

## Completion

Deliver the SRS, index, frozen analysis and method, independent review, and the implementation and validation artifacts required by the requested scope. State the inspected range, remaining unknowns, and implementable scope. Call an SRS reviewed only after independent acceptance and a successful binding check; without a separate review context, retain draft/self-reviewed status.

A bounded SRS can be accepted with explicit unknowns. Report document acceptance, implementation claims, HTTP/storage checks, and actual client results separately. Successful packaging cannot establish runtime compatibility.
