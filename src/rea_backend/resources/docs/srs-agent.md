# Agent and tool responsibilities

The [REA-Backend skill](../skills/rea-backend/SKILL.md) guides the host coding agent through discovery, SRS writing, independent review, implementation, and validation. Deterministic commands maintain records and version bindings; they do not call a model, infer business rules, or establish exhaustive client coverage.

A suitable request:

> Use $rea-backend to read this input configuration, investigate permitted materials, and maintain resumable analysis. Freeze the baseline, write and independently review backend requirements, then implement and validate the selected scope.

Hosts that do not discover the skill automatically can read its entry point explicitly. Export the resources with `rea-backend init-workspace --out PATH`, retaining `skills/`, `docs/`, and `templates/` together. For a new client, complete the [configuration template](../templates/srs-inputs.json) with fixed versions, paths, permissions, and goals. Historical requirements, code, and results are not default inputs.

## Responsibilities by stage

| Stage | Agent | Tools | Passing does not establish |
|---|---|---|---|
| Discovery and collection | Find entries, read originals, trace responsibility, and record questions/next actions. | Preserve revisions and check sources, dependencies, and expected revision. | Exhaustive discovery or correct conclusions. |
| Settlement and freezing | Assess answers, blockers, and exclusions. | Check registered dispositions and freeze inventory/history/method. | No omissions, no important unknowns, or full implementability. |
| SRS authoring | Write behavior, relationships, evidence, and gaps. | Prepare templates and check document/index structure and references. | Semantic correctness or original-server equivalence. |
| Independent review | Independently sample originals and reconstruct behavior; inspect contradictions and omissions. | Validate declarations and bind review to the candidate. | Verified independent runtime identity or client compatibility. |
| Implementation and validation | Choose scope, author code/checks, execute and interpret validation. | Check mappings, package builds, execute plans, and retain results. | Automatic backend generation or compatibility from packaging/HTTP success alone. |

Exploration supports ongoing collection and resumption. Each SRS freezes its own analysis and method copies. Later updates do not alter earlier baselines; preserve old configurations/originals and version new materials. Untracked initialization remains readable but cannot claim the newer tracked process.

Commands provide no batch model scheduler, automatic evidence selection, or semantic reviewer. Independent module work may run in parallel while handling revision conflicts. The reviewer uses a separate context and permitted originals.

Analysis/v3 retains actual flows and untraced boundaries in work items. Review/v3 retains independent samples and reconstructed chains. Validation/v2 binds risks, early client feedback, and final scope evidence. `android-run` manages explicit device/service actions and fresh collection. Machine checks validate recorded structures and relationships without inferring completeness or business success.

## Single maintenance locations

| Topic | Reference |
|---|---|
| Discovery, collection, evidence reasoning, and settlement | [Requirements discovery](requirements-discovery.md). |
| APK tool selection and evidence-triggered interaction tracing | [Behavior tracing](apk-behavior-tracing.md). |
| CLI, configuration, analysis/SRS/review formats, and bindings | [SRS formats](srs-format.md). |
| Human-readable SRS sections and entries | [SRS template](../templates/backend-requirements.md). |
| Independent review inputs, actions, and conclusions | [Review procedure](../skills/rea-backend/references/review.md). |
| Requirements to implementation, packaging, and validation | [SRS to backend](srs-to-backend.md). |
| Explicit device plans, service lifecycle, and collection | [Android runner](android-run.md). |

The skill entry point routes to these references without duplicating their detailed contracts. Generic methods describe when to investigate and how to retain uncertainty; actual fields, features, and product rules come from current inputs. Method changes need fresh runs to assess discovery/review behavior; structural checks alone cannot establish improvement.
