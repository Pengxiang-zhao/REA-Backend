# <App name> Backend Software Requirements Specification

> Purpose: guide independent backend design, implementation, and acceptance. Organize discovered capabilities for a fixed client version, retaining unknowns and deferrals. See [SRS formats](../docs/srs-format.md) for the companion index and bindings. Template fields do not represent established facts.

## 1. Document and product overview

- Document ID, version, status, author, and date:
- App name, client version, platform, and build variant:
- Product purpose, intended users, and backend goals:
- Client commit / APK hash and dependency versions:
- Input inventory, analysis revision, method version, and frozen run:
- Terminology and permitted references:

| Document version | Change and rationale | Affected modules | Input / analysis / method version |
|---|---|---|---|
| | | | |

## 2. System boundary and runtime environment

- Responsibilities of the client, independent backend, and external services:
- Client/backend interaction overview; optionally include a context diagram:
- Protocol/client/service versions and deployment, network, and resource requirements:
- Fixed or selectable protocol branches, conditions, current choice, and basis:
- Discovery, implementation, and validation scopes:
- Responsibilities excluded from this backend and reasons:
- Input completeness and unresolved dependencies, dynamic code, or remote resources:
- Differences between final goals and current execution conditions:

## 3. Users, roles, and scenarios

| Role | Identity and authentication | Objects and permitted operations | Relationships to other roles |
|---|---|---|---|
| | | | |

Describe evidenced scenarios and cross-module flows. Keep unsupported roles/rules unknown instead of inventing product features.

## 4. Capability overview

Organize discovered user, background, and dependency capabilities by module. This inventory records known scope; it does not prove exhaustive client coverage.

| Capability ID | Module / capability | Client entry or background trigger | Backend responsibility | Requirements | Analysis state and gaps |
|---|---|---|---|---|---|
| `<CAP-...>` | | | | | |

Retain unused SDK candidates, local-only behavior, deferrals, and blockers with their basis. Implementation and validation status belongs in section 10.

## 5. Functional requirements

Repeat the structure below for actual modules. Every requirement has a stable ID and independent HTML anchor. Prose carries full behavior; the index carries summaries and relationships. Cross-reference shared data, interfaces, and rules.

### 5.x <Module name>

**Purpose and boundary**

- Covered capabilities, roles, prerequisites, and related modules:
- Operations and primary/alternative flows; optionally include a flow/state diagram:

**Requirement**

| Field | Content |
|---|---|
| ID / title | `<FR-MODULE-NNN>` |
| Obligation | The backend shall …; a checkable behavior/result |
| Actor, conditions, and inputs | |
| Normal handling and outputs | |
| Rules and state transitions | |
| Exceptions, alternative flows, and failure state | |
| Applicable access, repetition, retry, and concurrency constraints | |
| Related objects, interfaces, and cross-module effects | |
| Priority and dependencies | |
| Verification conditions / method | |
| Conclusion type, original evidence, and unresolved IDs | |

Split complex behavior into independent obligations. Distinguish direct contracts, inference, compatibility assumptions/local choices, project additions, and unknowns.

**Consequential interactions, where evidenced**

If shared state, ordering, or branching affects backend obligations, describe actual entry, conditions, initial state, and success/stop criteria, then use the table. A simple single call can remain in its requirement entry. See [behavior tracing](../docs/apk-behavior-tracing.md).

| Step / prior state | Request or local action | Client decision order and branches | Required response and state change | Next step / termination | Evidence / unknowns |
|---|---|---|---|---|---|
| | | | | | |

Carry applicable consumer/wire/state/resources findings into requirements or this table, including conversions, response branches, failure state, and resource-content constraints. Reference unresolved dimensions and gaps rather than duplicating the analysis ledger. Deferral does not make investigation unnecessary.

## 6. Data requirements

### 6.1 Conceptual model and relationships

Describe evidenced entities, ownership, relationships, uniqueness, integrity, and lifecycle; optionally include a conceptual diagram. Client DTOs are not physical database design.

| Object | Business meaning | ID and ownership | Relationships and integrity | Lifecycle / deletion |
|---|---|---|---|---|
| | | | | |

### 6.2 Data dictionary

| Object.field | Meaning and type | Absent / null / default and consumer behavior | Mutability and constraints | Evidence / unknowns |
|---|---|---|---|---|
| | | | | |

Add evidenced retention, ordering, time, version, cursor, and consistency rules. Leave physical tables and indices to design.

When persisted values affect decisions, record wire parsing → storage conversion → reload → comparison/branch evidence, final domains, and precision constraints. Do not invent universal units, ID widths, or deduplication. List consumer/parser differences and unexecuted verification separately.

## 7. Interfaces and integrations

### 7.1 Shared conventions

Describe applicable protocol, addressing, versions, encodings, media types, credentials, parameters, errors, pagination, ordering, time, and repeated requests. Link concrete exceptions instead of overriding actual consumers with global defaults.

### 7.2 Interface inventory

| Interface ID | Capability / requirement | Method and path or event | Input / output objects | Errors and constraints | Detailed attachment |
|---|---|---|---|---|---|
| | | | | | |

Use the actual protocol; HTTP may include OpenAPI. Attachments remain traceable to prose and the frozen version.

### 7.3 External dependencies

| Dependency | Capability | Input / output and version | Local replacement policy | Failure and fallback behavior |
|---|---|---|---|---|
| | | | | |

## 8. Quality and runtime requirements

Include applicable consistency, reliability, performance, capacity, security, compatibility, and observability requirements. Metrics need a basis; missing targets remain unknown or explicit project choices.

| Requirement ID | Quality obligation | Metric and threshold | Load and runtime conditions | Verification | Basis / unknowns |
|---|---|---|---|---|---|
| `<NFR-...>` | | | | | |

## 9. Project-specific extensions

Describe only explicitly requested additions beyond recovered client behavior. Label their source as a project decision and explain their effect on known client contracts. If none are selected, state that this section is not applicable.

| Requirement ID | Capability | Behavior and effects | Boundary and conditions | Verification |
|---|---|---|---|---|
| `<EXT-...>` | | | | |

## 10. Delivery and acceptance

### 10.1 Implementation plan

| Capability / requirement ID | Priority and dependencies | Delivery phase | Implementation status | Reason for unimplemented scope |
|---|---|---|---|---|
| | | | | |

### 10.2 Validation and coverage

| Capability / requirement ID | Validation method | Case or check ID | Result and version | Untested scope |
|---|---|---|---|---|
| | | | | |

Report discovery, requirement clarity, implementation, and acceptance separately with their evidence and limits. Static review, HTTP checks, and real-client validation establish different claims. Follow [SRS to backend](../docs/srs-to-backend.md); requirement changes retain old baselines and receive renewed review.

## Appendix A. Inputs and evidence

| Input ID | Kind and version | Path / URL / hash | Access and purpose | Completeness limitations |
|---|---|---|---|---|
| | | | | |

| Evidence ID | Input and actual file / symbol / line / record | Supported requirements | Conclusion type | Limitations |
|---|---|---|---|---|
| | | | | |

Record actual sources. Analysis summaries organize evidence without replacing originals. Label permitted reference feedback according to input policy.

## Appendix B. Assumptions, gaps, and decisions

| Gap ID | Unknown or pending choice | Affected capabilities / requirements | Missing material | Disposition / local decision and rationale | Version and verification |
|---|---|---|---|---|---|
| | | | | | |

Retain discovery blockers and candidates. Settlement means a recorded disposition, not universal resolution. Important unknowns still constrain implementable scope.

## Appendix C. Traceability

Maintain discovery → capability → requirement → original source → design/implementation → validation relationships. Reference the companion index and frozen analysis without copying prose. State completed and incomplete scope at each stage.
