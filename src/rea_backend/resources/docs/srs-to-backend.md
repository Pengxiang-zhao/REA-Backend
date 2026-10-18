# Building an independent backend from an SRS

Choose a clear implementation scope from a reviewed SRS and author the service using that route's permitted evidence. Preserve unknown server behavior as gaps and explicit local policies. New SRS baselines follow discovery, collection, settlement, and freezing as described in [SRS formats](srs-format.md). Report document acceptance, implementation claims, HTTP checks, and actual Android validation separately.

## Implementation workflow

```text
Reviewed SRS + permitted client evidence
    → select scope and record local choices
    → agent authors the service, isolated fixtures, and checks
    → srs-build validates provenance/mapping and packages the service
    → HTTP, storage, and consumer checks
    → actual Android client validation
    → diagnose failures and revise the appropriate stage
```

`srs-build` performs deterministic checking and packaging. The host agent writes code; the command does not interpret prose into a program or call a model API. The build retains the requirement version, input route, and implementation decisions. There is no built-in model orchestrator.

After initial discovery freezing and independent acceptance, implement an early usable workflow: actual sign-in/entry, a read or write, a subsequent read after saving, and any retry that the flow genuinely uses. Run the actual client early, then extend the selected scope. Freezing remains before the first business implementation; phased work retains other capabilities and gaps.

## Build and run

Install this package in the working environment. Building checks the original configuration, permitted inputs, final review, and implementation mapping. Running the generated service does not require the original client source, REA, or original server.

```sh
rea-backend srs-build \
  --config path/to/inputs.json --srs path/to/reviewed-srs \
  --implementation path/to/implementation --out artifacts/backend/run-01
```

The output directory must not exist. Use a new versioned directory for rebuilding. The generated bundle includes `implementation/requirements.txt`; install those service dependencies in its own runtime environment.

`rea-backend.srs-build/v2` contains declared service files, implementation mapping, SRS document/index/inventory/run/review, full analysis history, and the method manifest plus its listed files. `build.json` binds every file with SHA-256. `input-config.json` preserves original configuration bytes; its relative paths are not rebased to the package. Original inputs are not copied, so provenance rechecking still needs the original configuration/materials. V1 builds preserve their smaller historical file set without invented analysis snapshots.

## Implementation manifest

New `implementation.json` uses `rea-backend.srs-implementation/v2` with an SRS run/v2 baseline.

| Field | Meaning |
|---|---|
| `format` | `rea-backend.srs-implementation/v2`. |
| `name`, `app_id`, `route` | Implementation identity and route; app/route match the SRS configuration. |
| `srs_hashes` | Exact mapping from the six filenames below to their SHA-256 values. |
| `entrypoint`, `files` | Relative startup file and complete packaged file list. Entrypoint is in files; files includes `requirements.txt` and omits separately packaged `implementation.json`. No symlinks or path escapes. |
| `requirements` | Every SRS requirement's ID, status, implementation files, and scope note. |
| `decisions` | Unresolved gap IDs, selected local policy or deferred validation, and its limits. |

V2 `srs_hashes` contains exactly:

```text
backend-srs.md
index.json
inventory.json
run.json
analysis/analysis.json
method/manifest.json
```

Requirements have `{id,status,files,note}`, with status `implemented / partial / deferred`. Every SRS requirement appears exactly once; implemented/partial entries reference declared files, and at least one requirement is not deferred. Decisions have `{gap_id,kind,choice,validation}`, where kind is `local_policy / deferred_validation`; gap IDs are unique.

SRS run/v1 uses implementation/v1, whose hash map has only document, index, and inventory. Historical-format builds remain `legacy/untracked`; changing a format string is not migration.

Implemented means the author claims code coverage, not test or Android success. Tests report independently. Deferrals remain listed. Blocking gaps on active requirements and their capabilities require explicit dispositions.

Builds require current independent acceptance, unchanged evidence, and matching SRS hashes. V2 review also binds run, analysis, and method. A clearly defined subset can be built without full-SRS `ready_for_implementation=true`, while open gaps remain open. Local policy cannot become an asserted original-server fact. Changes to bound requirements require review and mapping updates; new evidence/analysis requires a new baseline.

## Derive development checks from findings

Write checks for selected requirements and applicable contract investigations, using frozen route-permitted evidence and declared decisions.

| Discovered constraint | Development check |
|---|---|
| Parsing, null/empty distinctions, loops, and stopping | Exercise response forms distinguished by the actual consumer and inspect subsequent actions; do not assume status is checked before body parsing. |
| Wire conversion, numbers, and time | Check final consumer domains, updated values, and save/reload/compare behavior. Use the actual consumer parser or a model with stated limitations. Invalid-input handling follows contracts or explicit policy. |
| Local/remote writeback | Verify actual storage and later business reads, failed-operation residue, reverse operations, and restart using the same database. Retain unintended changes to other objects. |
| Images, bodies, exports, or other resources | Parse actual content with the matching format/parser and observe the real consumer where available. Status, nonempty bytes, or magic headers alone are insufficient. |
| Rejected import, startup, or migration preserves state | Check declared files and side effects, including logs/sidecars when applicable. Inspect old stores on a copy of their complete file set so inspection cannot itself recover or alter them. |

For genuinely unknown rules, state what can be verified and what remains untested. If feedback changes requirements, form a new baseline. If implementation deviates from known requirements, repair it under the current baseline and preserve failure records.

If initialization, writes, and existing data reach the same consumer, cover their entry points or document a shared validated path. Distinguish service restart, client sign-in, and client process restart; one result cannot substitute for another. Select regressions by change impact, bind final evidence to the actual executed build, and stop repeated expansion after the selected scope passes without new concerns.

Automate lifecycle, fixture preparation, action replay, collection, and reporting while retaining assertions, evidence strength, and failures. Early feedback exposes issues sooner; final selected-scope acceptance still requires independent review, relevant HTTP/storage checks, and actual client validation.

## Running checks bound to a build

`srs-validate-build` executes explicit argv plans. It first verifies all bound build/v1 or v2 files, creates a physical execution copy outside the repository, and runs the plan. It checks the original build, execution copy, and retained initial snapshot. Changed bound files fail the run and mark remaining checks not_run. Plans execute approved code and are not security sandboxes; checks use isolated databases/dynamic ports rather than current live instances.

```sh
rea-backend srs-validate-build \
  --build artifacts/backend/run-01 \
  --plan path/to/validation-plan.json \
  --out artifacts/validation/run-01
```

Plan/v1 contains exactly `format`, nonempty `purpose`, and nonempty `cases` (at most 100). Each case requires `id`, `purpose`, a nonempty string-array `argv`, and `timeout_seconds` in `(0,600]`; optional `requirement_ids` reference bundled SRS IDs. Case IDs are unique and follow CLI character constraints. Replace illustrative scripts with actual build entry points:

```json
{
  "format": "rea-backend.build-validation-plan/v1",
  "purpose": "Check the selected implementation against its frozen client contracts.",
  "cases": [{
    "id": "http-contracts",
    "purpose": "Run isolated HTTP and storage checks.",
    "argv": ["{python}", "{build}/implementation/test_http.py", "--out", "{artifacts}/http"],
    "timeout_seconds": 60
  }]
}
```

`{python}` is the current interpreter, `{build}` the execution copy, and `{artifacts}` the case's temporary artifact directory. Argv does not pass through a shell or expand environment variables/substitutions. Child processes remove inherited PYTHONPATH and run outside the repository, but use currently installed dependencies; this does not establish a clean dependency installation.

Include reproducible test scripts in build files and invoke them through `{build}`. For external tools/scripts, retain versions, hashes, and origins separately. Explicit argv does not automatically archive code or dependencies outside the build; freezing a plan alone does not freeze every executable.

Output must be new and outside the build. It retains the plan, initial build snapshot, per-case stdout/stderr, explicit artifacts, and `report.json`, including run ID, version hashes, timing, exit codes, timeouts, and integrity checks. Failures still write reports and return nonzero; invalid plans fail preflight. Normal completion and timeout clean up the created process groups and reap direct children. Cleanup errors fail the run and stop later cases. External services that detach from those groups are outside the isolation guarantee.

Exit 0 means executed checks succeeded. Their assertions and evidence determine coverage and whether Android actually ran. Use new build/output directories after repairs, preserving earlier failures.

Real-client integration also records executed code/build hashes, database, initial state, device, and APK identity. After changing implementations, distinguish an ongoing session from new sign-in. HTTP records cannot replace device-level version binding.

## Staged validation plan v2

Use `rea-backend.build-validation-plan/v2` to bind discovered risks, selected flows, and actual checks. V1 remains available for individual checks without implying completion of v2 stages. Both stages operate on a reviewed, packaged SRS baseline:

1. `early_client`: implement and run a minimal workflow after initial freezing/review; preserve failures and return to the responsible stage before extending implementation.
2. `final`: validate the full selected scope of the final build, binding an earlier successful early_client report from the same SRS baseline. The backend build may have expanded. Early evidence does not replace final real-client runs. A changed SRS baseline requires its own early workflow evidence.

V2 top-level fields are `{format,purpose,phase,scope,obligations,cases}`; final additionally requires `early_client:{path,sha256}`. Path resolves relative to the plan and the hash binds original report bytes. The tool checks and retains the early report, plan, required SRS files, and evidence. SRS index/analysis must match; the nonempty early workflow scope is a subset of final scope. Another client or SRS version's success cannot satisfy this gate.

| Field | V2 constraints |
|---|---|
| `scope` | `{workflow_ids,requirement_ids}`; workflows are analysis/v3 work items with nonempty flow nodes. |
| `obligations` | `{id,item_id,contract_kind,node_ids,requirement_ids,risk}` array; kind `consumer / wire / state / resources / flow`, existing local node IDs, nonempty risk. |
| `cases` | V1 case fields plus required requirement_ids, workflow_ids, obligation_ids, check_kind, and required_artifacts. |
| `check_kind` | `real_client / real_consumer / model / http`; model additionally requires nonempty model_limitations. Record actual runtime/tool versions in evidence. |
| `required_artifacts` | Nonempty `{path,kind}` array; paths are relative to case artifacts, kind `ui / request / storage / consumer / diagnostic`. |
| `failure_artifact` | Optional case field naming a failure-attribution JSON file inside its artifact directory. |

References resolve against frozen items, nodes, requirements, and obligations. Every declared obligation has checks; case workflow/requirement unions equal scope. In both phases each selected flow requires a real_client case with UI and request evidence. Checks containing state obligations also require storage evidence. Consumer/model/HTTP checks supplement real-client runs. The tool checks relationships, not assertion quality or discovery completeness.

Required artifacts must be freshly generated by the case, nonempty regular files within bounds, and readable for hashing. Missing, empty, or old artifacts fail a case even after exit 0. Identical bytes can represent a valid new observation, but timestamps alone do not establish execution; preserve genuine request/storage origins. Assertions check consumption, committed actions, and unintended state changes rather than screenshots or HTTP success alone.

The [Android runner](android-run.md) manages device/service actions and collection. Business checks inspect its report and collected content and, where needed, copy evidence into case artifacts. A captured run is not automatically a business pass.

### Failure attribution and return paths

Failure records contain `{category,summary,evidence_paths}`, with category `requirement_gap / implementation / environment / unknown`. Paths identify fresh, nonempty case evidence. An existing failure record makes the case fail even after exit 0. Missing/invalid attribution or unsupported claims remain unknown.

| Category | Next action |
|---|---|
| `requirement_gap` | Resume route-local discovery, collect evidence, and create a new SRS baseline while preserving the original. |
| `implementation` | Repair code/checks to known contracts without rewriting requirements to hide deviation. |
| `environment` | Repair device, network, tools, or service conditions and rerun affected checks. |
| `unknown` | Investigate the blocking point, retaining failures and selected scope. |

Reports distinguish stage, declared coverage, actual evidence, and attribution. They do not establish equivalence to every original-server behavior. Complete affected checks and final scope; reused results need an explicit version and applicability basis.

## Keep methods separate from client-specific outputs

These resources define workflow, formats, and validation boundaries. Client-specific decisions and evidence belong to the corresponding run, outside the generic package. Links and historical outputs do not expand permitted inputs.
