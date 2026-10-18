# Tracing client behavior from APK evidence

This supplements [requirements discovery](requirements-discovery.md) when call order, shared state, or branches affect backend behavior. Trace consumption, writeback, and termination. The same reasoning applies to source analysis. The APK route obtains evidence from separately installed REA, decoded resources, smali, and permitted runtime records, without borrowing source-route conclusions. Record the REA version and follow its upstream installation and license requirements; this package does not bundle REA.

## Verify the actual tool capabilities

Read the current REA tool catalog, parameter schemas, and version before choosing class, method, reference, resource, or call queries. Preserve actual tool identities and requests. Historical tool names, example output fields, and default overload selection are not universal contracts.

Extracted endpoints, models, and resources provide navigation. Follow clues into complete implementations and consumers, preserving full output, pagination/truncation, and tool errors. Where tool output is incomplete, use permitted decoded artifacts or smali. Unresolved behavior remains in analysis items and gaps.

If generic endpoint extraction returns nothing, check which declarations the extractor supports. Query actual screens, request constructors, serializers, strings, and resources, then smali when necessary. Zero results establish neither absence of a backend nor a need to invent endpoints. A local-only client can support an evidenced conclusion that no backend is needed after its entry points are checked.

Preparation reports distinguish RPC outcome, material availability, and request/receipt matching. Successful RPC receipts can still report unavailable bodies, truncation, partial coverage, or fallback. Missing availability metadata stays unknown. `matched` means comparable request fields agree, not complete or trustworthy execution. A `mismatch` cannot support the requested method; `unverified` requires stating unchecked parts. Read originals and sidecars, then choose the next query around a concrete gap.

Each material traces to the original APK hash, extraction tool version, and collection conditions. Search hits suggest further reading; missing static references do not prove runtime unreachability. Exploration can continue collecting evidence; the formal SRS cites registered, frozen material.

## Follow actual call chains

1. **Entry and construction.** Trace screens, background components, events, or bridges through construction and dependency injection to actual clients, state containers, and storage. State is shared only where evidence shows it; one page does not automatically imply one session instance.
2. **Concrete implementation.** Verify classes, parents, interfaces, overrides, versions, and build conditions at call sites. Read smali when decompilation omits or distorts control flow. Cross-check resource constants and configuration against execution paths.
3. **Response and exception consumers.** Follow status, headers, body, parsing, and exception conversion in actual order, then upper-layer handling. Backend error policy must satisfy that consumer order.
4. **Writeback and termination.** Trace commits, ID replacement, state cleanup, cursor movement, subsequent calls, and exits. Distinguish optimistic UI from confirmed writes and inspect state left after failure or repetition.

For overloaded methods, determine parameter and return types from the actual call site before reading a matching implementation. Preserve overload arguments or returned signatures when supported by the catalog. Otherwise verify the full smali method descriptor and invoke instruction. Overload indices do not carry across packages or engine versions. Keep unresolved signatures unknown without inventing offsets or locations.

For suspensions, loops, and exception conversion, inspect decisive smali branches instead of repeatedly requesting identical pseudocode. Register the exact question under consumer/wire/state/resources. A query resolves only what its evidence supports; even a complete method body does not resolve untraced callers or consumers.

## Express interactions as checkable constraints

During exploration, retain clues and questions in work items. After freezing, place consequential interactions in SRS section 5 or an appendix, linked to existing capability, requirement, evidence, and gap IDs. [SRS formats](srs-format.md) defines JSON fields; avoid unbound parallel requirement documents.

| Record | Include where applicable |
|---|---|
| Entry and conditions | Trigger, actual method/implementation, version or setting conditions, and uncertain reachability. |
| Initial state | Whether relevant instances, credentials, sessions, caches, queues, or cursors are new, reused, or cleared. |
| Ordered actions | Requests and local actions; values passed, stored, or cleared between them. |
| Decisions and branches | Response/exception check order; continuation, retry, fallback, failure, and termination. |
| Minimum response constraints | Status, headers, markers, fields, types, and body shape required for subsequent steps. |
| Resulting state and basis | What client/server state changes, when success is declared, evidence locations, unknowns, and local choices. |

Use the template interaction table for longer flows. Expand absent/null/empty distinctions when consumers or clues warrant them; DTO types do not prove interchangeability. Deferred flows stay in capabilities/gaps. Simple requests need no artificial multi-step table.

Trace conversions as entry value → local representation → wire value → returned-value consumption, recording widths, encoding, and applicable callers. Different consumers may require different rules. If persisted values affect decisions, continue through converters, reload construction, and comparisons, recording precision, final domains, normalization, and branch effects. Resource constraints should support post-implementation checks using the actual format/parser. A static SRS cannot describe future tests as passed.

## Separate static and runtime evidence

| Evidence | Supports | Does not establish |
|---|---|---|
| Original APK static materials | Visible construction, order, parsing, branches, writeback, and termination constraints. | Dynamic reachability, actual network configuration, or success on a device. |
| HTTP checks derived from contracts | A particular initial state's requests, responses, persistence, and subsequent reads. | That the real APK selects the same entry, ordering, and parsing results. |
| Actual APK integration | Observed client/server outcomes for a specified device, package, entry point, and conditions. | Unrun branches, other devices, or all original-server semantics. |

The [reviewer](../skills/rea-backend/references/review.md) independently samples and reconstructs original entry points. Static SRS review can precede implementation; runtime compatibility claims need real package evidence afterward.

Record actual initial state, entry, requests/application logs, key UI, and before/after backend state. A fresh-session check states what was retained or cleared; undisclosed preauthentication cannot establish first-use behavior. After writes, observe subsequent client actions and read again. If repackaging, signing, or network configuration changes, identify the original and executed APKs and the modification scope separately.

On failure, return to route-permitted originals and distinguish missing requirements, implementation deviations, local policy, environment issues, and unknown causes. Changed formal requirements require registered new traces, resumed discovery, a new baseline, and independent review. The checker does not infer these semantics or replace real-client evidence with HTTP success.
