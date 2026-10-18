# Discovering backend requirements

Use this method for exploration, targeted evidence collection, and requirement reasoning. The fixed client version determines the business modules. Existing checks, API summaries, and historical examples do not define discovery scope. [SRS formats](srs-format.md) define commands and records; the [SRS template](../templates/backend-requirements.md) defines the document.

## Establish scope and permitted evidence

Begin with client identity, version, build variant, readable materials, and runtime goals. A complete user-authored feature list is unnecessary. Distinguish these scopes:

| Scope | Record |
|---|---|
| Discovery | Discoverable user, background, protocol, and dependency capabilities, including local behavior, candidates, and missing materials. |
| Implementation | Capabilities selected for this version, deferrals, and replacement policies with reasons. |
| Validation | Workflows, input versions, actual checks, and untested behavior. |

Separate final product goals from current execution conditions. Missing devices or permissions leave validation incomplete; they do not automatically remove final runtime requirements. Backend responsibilities follow actual client use, without inventing administrative features never exposed by the client.

Record whether the task fixes a protocol branch or allows a choice. A client version can support multiple protocols. Track branch conditions and the implemented choice. If a later task fixes a branch, create a new task/input baseline instead of rewriting the original route's inputs.

Confirm permitted sources before following method links. The source route uses fixed client source and matching dependencies. The APK route uses its declared APK, REA output, decoded resources, smali, and runtime records; it does not borrow source-route analysis, requirements, code, or answers. Reference servers and their responses remain reference-assisted evidence even when observed through a client. Register public documentation with its version and access policy.

Configurations and inventories provide provenance, not context isolation. Record actual reading and the impact of accidental access outside the boundary. The same boundary applies to task summaries, shared environment pages, cached indices, and agent metadata. A coordinator may maintain a cross-route overview; independent authors and reviewers receive only route-permitted content and neutral tool instructions.

## Maintain a resumable worklist

Create an analysis directory before exploration. Permitted materials may still be collected at this stage. Record “clue → question → current evidence → finding or blocker → next action” as work proceeds, rather than reconstructing an investigation from a finished SRS. Save meaningful progress with the expected revision number. On resumption, inspect the current revision and originals before continuing.

Keep work-item IDs stable. Add questions for new entry points, branches, unresolved dependencies, or contradictory rules; retain the disposition of existing questions. Valid dispositions are an evidenced answer, an explicit blocker, or a justified scope exclusion. Failure to locate code does not establish absence; implementation deferral is not a scope exclusion.

Each new item investigates four contract dimensions: response consumption (`consumer`), transmitted values (`wire`), state changes (`state`), and resource content (`resources`). These are investigation views, not mandatory product features. Read the actual entry point and originals before declaring a dimension answered, blocked, or inapplicable. An inapplicability claim for a DTO inventory stays confined to that question; discovered callers require separate investigation.

Before collecting more evidence, verify access and register the source in the configuration. Preserve tool requests, complete results, errors, and collection conditions. Search hits, extracted summaries, and endpoint candidates are clues. Record which question a new tool version or dependency resolves. If it remains unavailable, retain the next action and affected scope.

The worklist need not copy every source line. It must let another context understand what was read, why conclusions follow, what remains unresolved, and where to continue. Settlement describes registered questions, not exhaustive discovery.

## Cross-check four entry-point categories

Inventory available modules or DEX files, resources, components, build conditions, dependency versions, generated/dynamic modules, and missing or truncated material. File counts do not establish feature coverage; possessing an APK does not mean its code was analyzed.

| Area | Entry points and cross-checks |
|---|---|
| `ui` | Screens, navigation, menus, settings, sharing, and imports; follow resources to actual triggers and handlers. |
| `background` | Initialization, jobs, events, synchronization, queues, and retries, including behavior triggered without a screen action. |
| `protocol` | Declarations, direct requests, SDK calls, streams, and file protocols; trace callers and response consumers. |
| `data_and_dependencies` | Local models, caches, databases, dependency implementations, version conditions, and permitted product documentation. |

For each area record inspected scope, findings, and unknowns. SDK-only declarations remain candidates until actual use or a justified disposition is established. Register purely local capabilities with evidence for their responsibility. Distinguish incomplete materials, uninspected materials, and inapplicability.

Trace “actual entry → business handling → request/local action → response consumption → writeback and subsequent actions” to classify backend, client, external, or mixed responsibility. Inspect concrete implementations and matching dependencies, including inheritance, overrides, dynamic dispatch, and conditional activation. Base classes and interface declarations cannot replace concrete behavior.

### Preserve workflow boundaries

Analysis/v3 adds `flow_trace` to existing work items rather than creating another requirement ledger. For selected user flows, inspect prerequisites before the actual entry and follow through confirmed results. Retain symbols, locations, and permitted original-file hashes for consequential nodes. Include session, connectivity, cache, or queue conditions before requests and parallel dependencies used by the same page. If no request is issued, trace the blocking branch from the entry point.

Record only nodes and edges needed to determine responsibility. Discovered but unfinished calls, branches, or consumers become boundaries linked to another work item or gap. Preserve IDs and resolution evidence after resolving them. When a page reads a deferred module, record the read contract separately from implementation of the full module. Evidence still determines concrete probes, defaults, and concurrency behavior.

Finding a request and DTO establishes those nodes only. Follow clues into final sorting, comparisons, save/reload behavior, and aggregate error branches. Declaration-only questions may narrowly mark tracing inapplicable, while their callers remain separately tracked. The checker validates registered connections and dispositions; independent review and client runs can discover omitted entry points.

## Let evidence trigger deeper tracing

Do not prefill generic product answers. Continue when evidence exposes behavior that could change backend constraints:

| Clue | Question to resolve |
|---|---|
| State crosses calls; retries, fallback, or loops appear | What are the actual initial state, action order, continuation and termination conditions, error consumer, and update timing? |
| Overloads, inheritance, version dispatch, or decompiler ambiguity | Which signature and implementation executes? Is the inspected branch the correct one? |
| Returned values affect merging, credentials, relationships, or display | How do actual consumers distinguish absent, null, empty, and alternative response shapes? |
| Optimistic changes, queues, or remote-ID writeback | When is the write confirmed, what survives failure, and what does a subsequent read verify? |
| Shared error/protocol conventions span modules | Does a concrete module's consumer contradict the proposed global default? |

For applicable dimensions, answer:

- **consumer:** Which caller reads status, headers, and body, in what order? Are absent values, null, empty collections, empty strings, and empty bodies distinct? What continues, stops, or confirms success?
- **wire:** How do prefixes, encodings, types, and IDs transform entry values into transmitted parameters? Which collection does the caller select? In which types are numbers or times computed and stored? Intermediate parsing does not establish final acceptance. Separate client type ranges from unknown server capacity limits.
- **state:** What local and remote state changes before and after requests, including optimistic writes, commit detection, retry residue, and subsequent reads? Do comparisons use values reloaded from storage? Record contracts and future verification conditions, not invented implementation success.
- **resources:** What do the URL, authentication, media type, body format, and actual consumer require? After implementation, validate content with the corresponding parser or client. HTTP 200, nonempty bytes, and an extension cannot establish usable content.

Set `next_action` to the caller, signature, parser, smali branch, or permitted runtime observation that could resolve the question. Avoid rescanning a large directory already read. A successful query or zero references does not by itself resolve an item. Truly unavailable evidence becomes blocked with a formal gap while known scope can proceed.

See [behavior tracing](apk-behavior-tracing.md) for stateful interactions. A simple single call can be described directly without an empty workflow table.

### Cross-layer values and rejection paths

When values cross transformations, persistence, or later decisions, add the relevant questions to existing wire/state/consumer findings, next actions, or gaps:

| Clue | Boundary to inspect |
|---|---|
| Numbers, times, IDs, or versions change units, widths, precision, or representation | Trace wire parsing through final storage; record domains, rounding, truncation, overflow, and normalization. Newly generated values must satisfy known consumer constraints. |
| Reloaded values affect equality, ordering, cursors, or conflicts | Trace parsing → save → reload → comparison → branch. Distinguish representation equality, numeric equality, and business equivalence. Inspect no-op and real changes separately without inventing a universal precision policy. |
| Client and server use different parsers or runtimes | Determine the actual consumer's accepted syntax, range, and normalization. A server parser's success is insufficient; specify a consumer-runtime probe where needed, retaining it as unverified until executed. |
| An import, initialization, migration, or startup claims rejection preserves state | Inspect validation before destructive operations and whether reading/opening triggers recovery or writes. Define which data files, logs, resources, and side effects the preservation claim includes. Implementation-specific storage policies are local decisions. |

These are investigation questions, not universal business rules. Do not add persistence experiments to unrelated fields or use content deduplication to hide genuine duplicate-creation/conflict behavior.

## Reduce repeated work

Preserve authorized feature scope, evidence standards, and necessary stages. Batch queries, use verifiable caches and formatting helpers, and parallelize independent tasks. Do not mark unread materials analyzed, collapse author/reviewer judgment, or omit required client validation. Automation must preserve the same evidence and failure information.

Choose tools around an unresolved question. Reuse evidence only when input hashes, tool version, request/parameters, and permissions match, retaining complete receipts and limitations. A source-route summary cannot become APK-route cache evidence. If an unchanged query repeatedly returns no hits or the same error, inspect callers, resources, serializers, or raw code; record a blocker when no further evidence is available.

Independent review retains original-entry sampling. Revision review can focus on changes and affected chains, then rebind final artifacts. Reused results must still apply to inputs, dependencies, and runtime conditions; an unchanged file alone does not justify skipping affected checks. Label older results with their actual version. Validate the final selected scope, then deliver once it passes without new unresolved concerns; additional capabilities can enter a later version without shrinking the current scope retroactively.

## Turn findings into requirements

Describe capability responsibility and disposition, then organize behavior by module. A reader should understand backend obligations without rereading every source file. Data dictionaries and API specifications support behavior; frameworks, physical tables, and algorithms usually belong to design.

Distinguish direct client contracts, supported inference, compatibility assumptions/local choices, project additions, and unknowns. Client error handling does not prove that the original server always returns that error. Client validation is not automatically server validation; DTOs are not database tables; optimistic UI is not confirmed persistence.

Check known consumer constraints before selecting a local policy, including upper-layer handling of returned values and errors. State its rationale, effects, and verification conditions. Keep unsupported authorization, conflict, idempotency, capacity, and latency rules unknown or explicitly chosen. Project-specific additions belong in their own section and must not be presented as recovered behavior.

## Settle, freeze, and revise

Before freezing, inspect all four entry-point categories and registered questions. Continue actionable pending work; preserve unavailable evidence as blockers/gaps and scope exclusions with reasons. Passing the checker establishes recorded dispositions, while authors and reviewers still assess overlooked paths.

In v2/v3, every contract dimension has a disposition; v3 also checks flows and boundaries. Pending work prevents freezing. Blocked children propagate to the parent and open SRS gaps. Machines can check hashes and explanations' presence; independent review judges substance. Bulk `not_applicable` claims cannot replace important call-chain investigation.

Freeze the input inventory, full analysis revision chain, and method files before writing the SRS and index. Map candidates and blockers into capabilities or gaps. Freezing does not generate business conclusions. If writing or review needs new materials, preserve old configurations and originals, collect into versioned locations, and create a new baseline instead of modifying frozen evidence.

Use the [independent review procedure](../skills/rea-backend/references/review.md), then [implement the known scope](srs-to-backend.md). Runtime feedback that changes formal requirements becomes permitted new evidence and returns to discovery. Report discovery, requirement clarity, implementation, and validation separately; the capability inventory is the known scope, not proof of complete client coverage.
