# SRS workflow and machine formats

This is the maintenance location for commands, configurations, analysis records, SRS indices, and review bindings. See [discovery](requirements-discovery.md) for investigation and the [SRS template](../templates/backend-requirements.md) for prose. Machine checks establish declared provenance, registered dispositions, and version relationships, not semantic correctness or exhaustive discovery.

## Stage commands

Run in an environment with this package installed, using permitted inputs and separate output paths. Commands do not download evidence or call a model.

```sh
rea-backend srs-explore --config path/to/inputs.json --out path/to/analysis
rea-backend srs-analysis-update --config path/to/inputs.json --analysis path/to/analysis --updates path/to/updates.json --expected-revision 1
rea-backend srs-analysis-check --config path/to/inputs.json --analysis path/to/analysis
rea-backend srs-analysis-check --config path/to/inputs.json --analysis path/to/analysis --require-settled
rea-backend srs-init --config path/to/inputs.json --analysis path/to/analysis --out path/to/srs-v1
rea-backend srs-check --config path/to/inputs.json --bundle path/to/srs-v1
rea-backend srs-check --config path/to/inputs.json --bundle path/to/srs-v1 --require-reviewed
```

`python -m rea_backend` is equivalent to `rea-backend`. These are distinct stages with agent investigation, writing, and review between them. Running the list mechanically cannot complete the work. Use the actual current revision for `--expected-revision`; successful updates increment it. Check failures return nonzero.

`srs-explore` creates a resumable workspace without freezing evidence. Register permitted additions during discovery. `srs-init --analysis` requires settled registered work and freezes inputs, analysis history, and method before agent authorship. Initialization refuses a nonempty directory. Keep analysis/SRS outputs separate from each other and from input directories.

APK `prepare` produces `srs-handoff.md` and `srs-inputs.json` for discovery. Successful preparation does not establish completed analysis; read the saved requests and full receipts.

## Input configuration `rea-backend.srs-config/v1`

Fields are required unless marked optional. Paths resolve relative to the configuration file. Declare materials, access, and goals without prefilled business answers.

```json
{
  "format": "rea-backend.srs-config/v1",
  "app": {"id": "example", "name": "Example", "version": "fixed-version", "platform": "Android", "variant": "main"},
  "route": "source",
  "context": {"mode": "client_only", "notes": "Use only the fixed client and declared dependencies."},
  "inputs": [{
    "id": "client", "kind": "client_source", "path": "../inputs/client",
    "version": "fixed-commit", "access": "generation", "complete": true,
    "limitations": [], "exclude": []
  }],
  "environment": {
    "goals": ["An independent backend for the Android client."],
    "constraints": ["No runtime dependency on the original service."]
  }
}
```

- `route`: `source` or `apk`, requiring `client_source` or `client_apk` respectively.
- `context.mode`: `client_only` or `reference_assisted`; explain reference assistance. This declares source policy, not runtime isolation.
- `inputs.kind`: `client_source`, `client_dependency`, `client_apk`, `decoded_apk`, `rea_evidence`, `public_docs`, `client_trace`, `environment_spec`, or `reference`.
- `access`: `generation` or `excluded`. Only generation inputs support analysis/requirements. Paths across access classes cannot match or be ancestors of one another, including with exclusion globs. `client_only` disallows generation references; the APK route disallows generation client source/dependencies.
- `complete`: completeness of the declared material, not knowledge of every client behavior. False requires `limitations`; the formal SRS must retain limitations and open gaps.
- `exclude`: relative globs. `.git`, `__pycache__`, and `.DS_Store` are always ignored; other exclusions are explicit. Symlinks are rejected.
- Optional `sha256`: expected SHA-256 for a file input. Directories are inventoried per file; a version label alone does not verify a Git commit.

During exploration the materials list can change, while `app`, `route`, and `context.mode` remain fixed within a chain. After freezing, preserve the configuration and original materials unchanged. Further collection uses versioned configurations and material locations, then a new SRS baseline. Original inputs are not copied into the bundle.

## Analysis record `rea-backend.analysis/v3`

`srs-explore` defaults to v3. Existing v1/v2 records in this namespace retain their format-specific checks. V1 lacks contract investigations; v1/v2 lack flow tracing, reported as `legacy/untracked`. Do not relabel older chains as newer investigations. A new method requires a new analysis run and actual renewed investigation. These readers do not imply automatic conversion from other projects' artifact namespaces.

The directory contains `analysis.json` and complete revision snapshots beginning with `revisions/00000001.json`. Revision 1 has no items; every update creates the next revision. Current bytes must equal the latest snapshot. Preserve historical hashes and registered IDs; do not edit history manually.

Top-level fields: `format`, `app` (the full configured object), `route`, `context_mode`, `revision`, `previous_sha256` (initially null), `config_sha256`, `created_at`, `updated_at`, and `items`. The config hash identifies that update's configuration; sources are checked against currently permitted inputs.

`--updates` accepts a **nonempty JSON array** of complete items. An existing ID replaces the current record; a new ID appends it; omitted existing items remain. A stale expected revision is rejected. Read and merge current progress instead of overwriting another investigator.

| Work-item field | Rule |
|---|---|
| `id` | Stable ID beginning with an ASCII letter, followed by letters, digits, dots, underscores, colons, or hyphens. |
| `clue`, `question` | Nonempty clue and question. |
| `area` | `ui / background / protocol / data_and_dependencies`. |
| `sources` | Nonempty array of `{input_id,path,sha256}`. |
| `state` | `pending / answered / blocked / out_of_scope`. |
| `next_action` | Nonempty for pending/blocked; otherwise may be empty. |
| `depends_on` | Existing item IDs; no self-reference or cycles. |
| `evidence` | Array of `{input_id,path,sha256,note}`; notes are nonempty. |
| `finding` | Answer, blocker, or exclusion reason; only pending may be empty. |
| `gap_ids` | Formal SRS gap IDs, which may be reserved before prose is written. |
| `contract_checks` | V2/v3 require exactly `consumer`, `wire`, `state`, and `resources`, each with the disposition object below. |
| `flow_trace` | V3 requires the bounded flow graph and boundaries described below. |

Sources must be generation inputs, obey exclusions, and match actual hashes. A source path is normalized relative to its input root, without `..`, backslashes, or absolute paths. File inputs use their basename. Analysis source objects use no SRS evidence IDs or line fields; put locations in notes, then use checked line ranges in the SRS index if needed.

Answered items require findings and nonempty evidence; dependencies must be answered or out_of_scope. Blocked items retain findings and next actions; out_of_scope retains a reason. `--require-settled` additionally requires nonempty work, no pending items, and gap IDs for every blocker. Authors and reviewers assess whether discovery and answers are adequate.

Each `contract_checks` object contains exactly:

| Field | Rule |
|---|---|
| `state` | `pending / answered / blocked / not_applicable`. |
| `finding` | Conclusion, blocker, or inapplicability within the current question; only pending may be empty. |
| `evidence` | `{input_id,path,sha256,note}` array; nonempty for answered/not_applicable and checked against permissions/hashes. |
| `next_action` | Nonempty for pending/blocked, identifying the next material or operation. |
| `gap_ids` | Must also occur in the parent item; blocked investigations require gaps at freezing. |

Consumer covers response handling and branches; wire covers actual values, conversions, and type bounds; state covers writeback, failures, and later reads; resources covers acquisition and consumed formats. Inapplicability is local to the question. Missing materials do not establish absence of a product feature. The checker cannot judge the truth of prose reasons.

New dimensions can start pending. An answered/out_of_scope parent cannot contain pending/blocked children. A blocked child requires a pending or blocked parent, and a blocked parent at settlement. Any pending child prevents freezing. Full updates retain every key and chain format; historical source hashes need not match subsequently supplemented materials.

Check reports contain `status`, `errors`, `revision`, `counts`, `settled`, `unresolved_ids`, `note`, `contract_tracking`, `contract_counts`, and `contract_next_actions`. Next actions have `{id: "item-id/dimension",state,next_action,gap_ids}`. Counts describe registered items. Blocked work may be settled while still unresolved and unready for full implementation.

### V3 flow tracing

`flow_trace` contains exactly `{state,scope,finding,evidence,next_action,gap_ids,nodes,edges,boundaries}`. State is `pending / answered / blocked / not_applicable`; scope is nonempty. The other disposition fields follow contract-check rules, including parent gap propagation. An evidenced declaration-only question can mark graph tracing inapplicable without removing registered boundaries.

| Collection | Complete element | Constraints |
|---|---|---|
| `nodes` | `{id,kind,symbol,location,evidence}` | Kind: `entry / prerequisite / request / consumer / state / terminal`; nonempty symbol/location and original evidence. |
| `edges` | `{id,from,to,kind,evidence}` | Existing local nodes; kind: `sequence / requires / parallel / branch`; nonempty evidence. |
| `boundaries` | `{id,node_id,question,state,work_item_ids,gap_ids,resolution_node_ids,evidence,next_action}` | Origin node plus references to current work items, parent gaps, and local resolution nodes. |

IDs are unique within each collection. Evidence uses `{input_id,path,sha256,note}`. Symbols/locations identify actual branches; the checker verifies original hashes without interpreting code. Edges point from predecessors to subsequent nodes; `requires` points from a prerequisite to its dependent action. Represent parallel branches separately.

Answered graphs need an entry and terminal, every node reachable from an entry, and every node able to reach a terminal or explicitly handled boundary. Requests and writes are not mandatory in every flow. Retry cycles are allowed with terminal or boundary exits. Completeness applies only to the registered graph.

Boundary states follow the four disposition states. Pending prevents freezing; blocked requires retained parent gaps. Answered boundaries need evidence and either resolved other work items or downstream resolution nodes. Self-delegation and unknown references are invalid. Inapplicability needs exclusion evidence. Resolved graphs/boundaries cannot conceal unresolved delegated work. Once added, work-item and boundary IDs persist through later revisions.

Reports add `flow_tracking`, `flow_counts`, and `flow_next_actions`, with item or `item-id/boundary-id`, state, next action, and gap IDs. These guide targeted investigation without launching tools automatically.

## Frozen SRS and method version

`srs-init --analysis` creates:

```text
srs-v1/
  backend-srs.md
  index.json
  inventory.json
  run.json
  analysis/analysis.json
  analysis/revisions/00000001.json ...
  method/manifest.json
  method/files/...
  review.json                 # Added by independent review
```

`inventory.json` stores generation-input file sizes and SHA-256 values. Rechecking inventories detects additions, deletions, content changes, or configuration changes. Complete sections 1–10 and appendices A–C; every indexed requirement has an independent HTML anchor such as `<a id="FR-example-001"></a>` and a concrete prose entry.

`run.json` uses `rea-backend.srs-run/v2` and records `tool_version`, `created_at`, `tool_sha256` (SRS module hash), `config_sha256`, `inventory_sha256`, `template_sha256`, `skill_sha256`, plus:

| Field | Binding |
|---|---|
| `analysis_tracking` | Always `tracked`. |
| `analysis_sha256` | `analysis/analysis.json`; its previous-hash chain binds full history. |
| `method_sha256` | `method/manifest.json`; file entries bind the method snapshot. |

Initialization scaffolds blocked items' gaps as open index entries. Every analysis gap must appear in the finished SRS; blocked gaps stay open. The author fills prose and evidence relationships; initialization does not derive business requirements.

Default method `rea-backend/v1` freezes ten explicit files, not an entire documentation tree. It uses analysis/v3 flow boundaries and review/v3 independent sampling. Older analysis formats retain their actual level of tracking.

| ID | Bundled/exported file |
|---|---|
| `skill` | `skills/rea-backend/SKILL.md` |
| `template` | `templates/backend-requirements.md` |
| `discovery` | `docs/requirements-discovery.md` |
| `behavior` | `docs/apk-behavior-tracing.md` |
| `format` | `docs/srs-format.md` |
| `review` | `skills/rea-backend/references/review.md` |
| `requirements` | `docs/backend-requirements.md` |
| `build` | `docs/srs-to-backend.md` |
| `android` | `docs/android-run.md` |
| `agent` | `docs/srs-agent.md` |

The frozen manifest uses `rea-backend.srs-method/v1`, with `version` and `files`; each file is `{id,path,source,sha256,bytes}`. Paths resolve below `method/`, normally `files/<id><suffix>`. `source` records the originating path and is not reread for checking. Relative links inside frozen files do not recursively expand the snapshot; review resolves required files by manifest ID.

`--method-manifest path/to/method.json` overrides the method only with `--analysis`. Its format is `rea-backend.srs-method-spec/v1`, containing `{format,version,files}` with a nonempty version and `{id,path}` files. All ten IDs are required; additions must be explicit. Paths are relative to the manifest or absolute and must be regular files, not directories or symlinks. The template ID freezes the actual template used. The packaged template is the default; `--template` selects an explicit alternative.

Later analysis updates or package upgrades do not change frozen copies. Validation uses bundle-local analysis and method records, while original configuration/materials remain available and unchanged. New evidence or changed findings creates a new baseline.

## Requirement index `rea-backend.srs-index/v1`

The index accompanies prose. Exact top-level fields: `format`, `app_id`, `scope` (always `app-wide`), `status` (`draft / reviewed`), `discovery`, `capabilities`, `requirements`, `evidence`, `gaps`, and `limitations`. Collections are arrays. IDs across index collections are globally unique and follow the stable ID character rules above.

### Discovery

One entry per area with `{area,summary,evidence_ids,gap_ids}`. Summaries describe actual inspected materials, findings, and limitations. Each entry references evidence or gaps; “complete” alone is insufficient.

### Capabilities

| Field | Content |
|---|---|
| `id`, `title`, `module`, `trigger` | Stable identity, title, module, and actual trigger. |
| `execution` | Array of `backend / client / external / unknown`; mixed responsibility may select several. |
| `backend_responsibility` | Backend obligation or evidence for no backend responsibility. |
| `analysis` | `analyzed / candidate / blocked`. |
| `disposition` | `planned / deferred / client_only / external / undecided`. |
| `reason` | Disposition rationale; deferral does not delete the capability. |
| `evidence_ids`, `requirement_ids`, `gap_ids` | Relationship arrays, empty when absent. |

Every capability references evidence or gaps. Candidate, blocked, or unknown responsibility requires open gaps. An analyzed backend capability references requirements; purely local behavior need not invent backend obligations.

### Requirements

Fields: `{id,title,kind,status,statement,acceptance,basis,anchor,capability_ids,evidence_ids,gap_ids}`.

- `kind`: `functional / data / interface / quality / extension`.
- `status`: `observed` (verifiable client contract), `inferred`, `assumed` (compatibility assumption/local policy), `unknown`, or `project` (explicit addition).
- Nonempty statement and acceptance; complete behavior belongs at the unique prose anchor, usually the requirement ID.
- Observed/inferred require evidence; inferred/assumed/project require a nonempty basis; unknown requires open gaps. Extension requirements use project status.
- Functional/data/interface requirements reference capabilities. Global quality/extension requirements may omit them. Capability/requirement links are reciprocal.

### Evidence

Fields: `{id,input_id,path,sha256,note}` with optional paired `start_line` and `end_line`, a 1-based inclusive range in UTF-8 text. Binary evidence may omit lines. Paths follow source rules and match the frozen inventory/hash. Notes explain supported facts and limitations.

### Gaps and limitations

Gap fields: `{id,question,impact,blocking,status,resolution,evidence_ids}`; blocking is boolean, status is `open / resolved`. Resolved gaps require a resolution; open gaps may use an empty string. A local policy can document a choice but an arbitrary success response cannot resolve unknown behavior.

Limitations are nonempty strings in an array, which may be empty. Incomplete inputs require an overall limitation and open gaps. Preserve unknowns, blockers, and decisions instead of deleting them to pass checks.

## Independent review `rea-backend.srs-review/v3`

The reviewer reads frozen procedures, permitted originals, and the candidate bundle, then writes `review.json` separately. After draft checks, the author sets index status to reviewed for the candidate; this is not acceptance.

| Field | Content |
|---|---|
| `format` | Analysis/v3 requires `rea-backend.srs-review/v3`; tracked v1/v2 analysis uses review/v2. |
| `reviewer`, `independent` | Reviewer identity and independence declaration; acceptance requires true. |
| `verdict` | `accepted / revisions_required`. |
| `document_sha256`, `index_sha256`, `inventory_sha256` | Actual document/index/inventory hashes. |
| `run_sha256`, `analysis_sha256`, `method_sha256` | Actual run, analysis, and method-manifest hashes. |
| `summary` | Actual scope, independent sampling/reconstruction, unresolved parts, conclusions, and limitations. |
| `issues` | Issue array, empty when none. |
| `sampling` | Required for v3; absent in older review formats. |

Issue fields: `{id,severity,status,target_ids,finding,resolution}`. Severity is `high / medium / low`; status is `open / resolved`. Targets are index IDs or frozen work-item IDs. Resolved issues explain the resolution. Acceptance forbids open high/medium issues. The checker does not verify reviewer identity or context separation.

Changed bound files invalidate review. `--require-reviewed` requires reviewed status, independent acceptance, and matching hashes. The frozen review procedure governs substantive review actions.

Sampling contains exactly `{selection_rationale,not_inspected,samples}`: a nonempty rationale, array of uninspected-scope strings, and nonempty samples. An empty uninspected list does not establish exhaustive product inspection.

Each sample is `{id,entry,selection_reason,risk_focus,author_item_ids,evidence,reconstructed_chain,comparison}`. Entry and selection reason are nonempty; risk_focus is a nonempty string array; author IDs reference frozen items and may be empty for a new independent discovery.

- Evidence is a nonempty array of `{id,input_id,path,sha256,symbol,location,note}`, bound directly to permitted frozen originals. Symbol/location/note are nonempty.
- Reconstructed chains are nonempty ordered arrays of `{id,kind,observation,evidence_ids}`. Kind is a flow-node kind or `other`. Every node uses evidence, and every sample evidence entry is used.
- Comparison is `{finding,status,issue_ids,work_item_ids,gap_ids}` with status `matched / discrepancy`. Matched comparisons identify corresponding author items. Discrepancies link issues and existing work items/gaps, with matching issue targets.

Accepted discrepancies must be resolved or explicitly retain open gaps, blocked items carrying them, and open review issues, subject to the prohibition on open high/medium issues. Omitted work needing collection or new analysis returns to a new baseline. A resolved review label cannot conceal open gaps in the same comparison.

Reports add `review_sampling` (`tracked / legacy/untracked / not_recorded`) and `review_sample_count`. These verify registered sample relationships, not sufficiency or semantic correctness.

## Results and older format support

`srs-check` separately returns structural errors, review state, `ready_for_implementation`, `analysis_tracking` (`tracked / legacy/untracked`), and `analysis_work` (null for untracked bundles). Incomplete inputs, open blocking gaps, unknown requirements, candidate/blocked/unknown capabilities, or any blocked analysis item prevent full-scope readiness. Marking a gap nonblocking does not remove a blocked item. Known modules may proceed without deleting unresolved scope.

Initializing without `--analysis` produces `rea-backend.srs-run/v1`, explicitly `legacy/untracked`, without analysis history or a complete method snapshot. Its review/v1 binds only document, index, and inventory. Do not change format strings to simulate a migration; the tracked workflow must actually create analysis and a new baseline.

Use a matching implementation format downstream. V2 binds run, analysis, and method and packages their frozen files; see [SRS to backend](srs-to-backend.md). Structural acceptance and independent document review do not establish actual-client compatibility.
