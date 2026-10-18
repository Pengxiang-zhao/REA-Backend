# Backend requirements specification

The backend software requirements specification (SRS) guides independent design, implementation, and acceptance. It describes the fixed client's required capabilities, rules, data, interfaces, and operating constraints.

Organize the document by product and functional module. Evidence supports requirements and acceptance checks verify them; neither replaces a complete behavior description. Use the [SRS template](../templates/backend-requirements.md), an engineering template without a claim of standards certification.

## Keep three scopes distinct

| Scope | Purpose | Incomplete capabilities |
|---|---|---|
| Discovery | Inventory discoverable screens, operations, background behavior, and backend dependencies. | Retain candidates, missing evidence, and justified exclusions. |
| Phased implementation | Select modules and requirements for the current delivery. | Retain deferred requirements and reasons. |
| Validation | Select workflows and checks from requirements. | State actual coverage and untested behavior. |

Completeness concerns client-visible product capabilities and runtime dependencies. Register local display behavior before deciding whether it needs backend support. SDK declarations without actual call evidence remain candidates. Unresolved native code, remote pages, or missing source are gaps, not evidence that a capability is absent.

The original server may expose administration or other-channel features never used by this client. These require separately defined scope and sources before becoming requirements.

## Document structure

| Section | Content |
|---|---|
| 1. Document and product overview | Purpose, audience, client/version, terminology, references, and revisions. |
| 2. System boundary and runtime environment | Client/backend/external responsibilities, deployment, and compatibility constraints. |
| 3. Users, roles, and scenarios | Identity, access relationships, and supported usage. |
| 4. Capability overview | Discovered modules, triggers, backend responsibilities, analysis state, and gaps. |
| 5. Functional requirements | Operations, primary/alternative flows, conditions, results, rules, permissions, exceptions, and cross-module effects. |
| 6. Data requirements | Entity/field meaning, relationships, ownership, constraints, lifecycle, deletion, and retention. |
| 7. Interfaces and integrations | Requests/responses, events, files/resources, authentication, versions, and external dependencies. |
| 8. Quality and runtime requirements | Applicable consistency, concurrency, reliability, resource, security, and observability constraints with measurable conditions or unknowns. |
| 9. Project-specific extensions | Explicit additions beyond recovered client behavior, with rationale and scope. |
| 10. Delivery and acceptance | Priorities, dependencies, delivery phases, checks, coverage, and unresolved work. |
| Appendices | Inputs/evidence, assumptions and decisions, and requirement traceability. |

Sections 4 and 5 carry the product description. Modules follow the actual client. For example, a reader and a messaging client need different capability groupings; examples do not define a universal checklist.

## Writing one functional requirement

Describe behavior an implementer can understand, then attach evidence. Give each module an overview and each checkable obligation a stable ID.

| Element | Include |
|---|---|
| ID and title | For example `FR-ARTICLE-DELETE-01`, linked to a capability/module. |
| Obligation | “The backend shall …” followed by one checkable result. |
| Conditions and inputs | Actor, initial object state, and input constraints. |
| Result and rules | Object/relationship changes, later reads, and evidenced atomicity, repetition, or conflict rules. |
| Exceptions and alternatives | Applicable missing objects, access failures, dependency failures, and resulting state. |
| Relationships | Data, interfaces, other modules, quality requirements, and validation. |
| Basis and unknowns | Evidence IDs; distinguish observed contracts, inference, local assumptions, and gaps. |

Deleting an article can affect tags, annotations, favorites, caches, and synchronization. Investigate evidenced dependencies instead of documenting only a DELETE path. Finding relevant code does not resolve every effect; keep unclear behavior open.

Requirements specify behavior. Frameworks, database choices, physical schemas, and module layout usually belong to design. Existing protocol compatibility and explicit operating constraints can be requirements.

## Data, interfaces, and quality

DTOs and serializers reveal client-used projections, not a complete physical data model. Explain meaning, ownership, relationships, and lifecycle; defer tables and indices to implementation design.

OpenAPI can describe HTTP interfaces, authentication, responses, and constraints. Describe other protocols and resources in their actual format. API and functional specifications share object definitions and references.

Include applicable runtime constraints without inventing throughput, latency, or capacity targets. State known metrics with hardware and workload conditions; leave unset targets open. Project-specific additions remain explicitly labeled and are validated separately from recovered client behavior.

## Building the specification

1. Fix client/dependency versions and record missing source, modules, resources, tools, or unresolved APK portions.
2. Cross-check screens, navigation, user actions, jobs, networking, SDKs, storage, and settings to build the capability inventory.
3. Separate backend state, local functionality, third-party responsibilities, and unsupported candidates.
4. Expand modules into flows, rules, data, interfaces, exceptions, and cross-module effects.
5. Reconcile every known capability, interface, and background entry with its disposition, evidence, and verification conditions.
6. Freeze a baseline before selecting implementation phases and checks. Preserve later discoveries as revisions.

Tools index and locate materials; the agent reasons across them and writes the document; validators check structures and references. The [skill](srs-agent.md), SRS commands, and build tools support this workflow without a built-in model orchestrator. Follow [requirements discovery](requirements-discovery.md) for the detailed method.

Use only declared inputs. Register permitted reference documentation, server traces, or feedback with their actual provenance; completeness goals do not expand source access.

## Output

Deliver the human-readable SRS with its capability inventory, module behavior, and appendices, accompanied by the [machine index and frozen records](srs-format.md). Large API definitions or data dictionaries may become explicitly linked attachments; a new project need not generate a large document tree. Continue with [SRS to backend](srs-to-backend.md) for implementation and validation.
