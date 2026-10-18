# Android development validation runner

`android-run` executes explicit service lifecycle, device operations, and evidence collection in a bounded run. It does not call a model, choose business workflows, modify APKs, or judge business correctness. The route-local agent authors actions and assertions from frozen contracts. For staged acceptance, invoke it through [validation plan/v2](srs-to-backend.md#staged-validation-plan-v2) and inspect actual requests, storage, and consumer outcomes.

## Environment diagnostics

```sh
rea-backend android-doctor \
  --serial emulator-5554 --avd your_avd \
  --package org.example.client --activity org.example.client/.MainActivity \
  --apk-sha256 <installed-apk-sha256> --out artifacts/doctor/run-01
```

Identify the authorized dedicated emulator. ADB lookup uses `--adb`, PATH, Android SDK environment variables, and common SDK locations. Reports retain AVD, system fingerprint, installed APK hash, ADB version/hash, Python, and discoverable Java. No local JDK path is hardcoded. Only a single base APK is supported; split packages are explicitly rejected rather than assumed equivalent.

Connectivity's VALIDATED flag is a diagnostic observation, not proof that the current network/client works. Doctor does not clear data, accounts, or backend state. Failures preserve a report and return nonzero.

## Execution plan

```sh
rea-backend android-run \
  --build artifacts/backend/run-01 \
  --plan path/to/android-plan.json \
  --out artifacts/android/run-01
```

Output must be new and separate from the build. The runner verifies all build hashes, creates a physical execution copy outside the repository, and retains an initial snapshot. It checks executed files during collection and completion. Databases do not belong inside historical build directories.

A `rea-backend.android-run-plan/v1` plan contains exactly these fields. Addresses, scripts, arguments, and actions depend on the actual client.

| Field | Shape |
|---|---|
| `format` | Format identifier. |
| `purpose` | Nonempty collection purpose. |
| `device` | `{serial,avd,package,activity,apk_sha256}`, all required. |
| `initial_state` | Nonempty declaration of relevant accounts, client caches, queued work, external files, and backend data. The declaration is not automatically verified. |
| `backend` | `{argv,ready_argv,port,timeout_seconds,env}`. |
| `collectors` | Array of `{id,kind,argv,timeout_seconds}`. |
| `steps` | 1–100 entries of `{id,purpose,actions,ui_xml}`. |

Backend port 0 allocates a local port; otherwise select an unused port. Argv is an explicit string array without a shell. The service listens locally and uses isolated data. `ready_argv` verifies actual service identity/readiness; exit 0 means ready. Timeouts are positive and at most 60 seconds. Env is an explicit string mapping. Execution removes PYTHONPATH/PYTHONHOME and disables bytecode writes.

Argv/env placeholders: `{python}`, `{build}` (execution copy), `{run}` (this run's persistent data directory), and `{port}`. Collectors also receive `{capture}` (current step collection directory). Include scripts in build files where possible; record external tools' versions and origins. JSON braces inside file contents are unaffected; no shell/environment expansion occurs.

Collector kinds are `request / storage / diagnostic`. Successful collection requires exit 0 and nonempty valid JSON on stdout. JSON can legitimately record no new requests; business assertions must inspect that meaning. Preserve stdout/stderr and command results. Timeouts/errors must not become empty successful state. Collectors read real logs/storage rather than echoing expected results. Separate new requests from earlier ones and service storage from client cache.

After each step's actions, collect a fresh screenshot and all collectors. `ui_xml` is `required / optional / skip`: required failures fail the step; optional failures retain diagnostics and screenshots; skip records omission. Dumps use unique device filenames rather than prior results. Prefer unique semantic attributes for clicking; ambiguous matches fail so the agent can update the plan from current evidence.

| Action | Complete fields |
|---|---|
| Launch/stop client | `{kind: "launch"}` or `{kind: "force_stop"}`. |
| Clear app data | `{kind: "clear_app_data"}`. |
| Restart using the same backend data | `{kind: "restart_backend"}`. |
| Semantic click | `{kind: "click", attribute: "resource-id" or "text" or "content-desc", value: "actual value"}`. |
| Coordinate tap | `{kind: "tap", x: integer, y: integer}`. |
| Enter synthetic text | `{kind: "text", value: "ASCII text"}`; not a Unicode input method. |
| Key | `{kind: "key", code: "KEYCODE_BACK"}`; numeric strings are also supported. |
| Swipe | `{kind: "swipe", x1, y1, x2, y2, duration_ms}`, all integers. |
| Bounded wait | `{kind: "wait", seconds: positive number}`, at most 15 seconds. |

There is no implicit state clearing. `clear_app_data` runs only `pm clear`; reports state that accounts were not reset, external files were not verified, and backend data was not reset. Prepare relevant AccountManager accounts, queues, and external files through legitimate client operations and record them; pm clear does not establish a fully fresh environment. Backend restart reuses `{run}` without replaying fixtures; actual persistence requires evidence and assertions.

An OS-released device lock coordinates this runner's instances, not outside ADB operators. ADB reverse uses no-rebind and rejects conflicting mappings; cleanup removes only mappings created by this run. Service/collector processes use their own process groups and are cleaned up by ownership. The runner does not kill unrelated processes by port or name.

## Report boundaries

Outputs retain the plan, build snapshot, diagnostics, service starts/readiness checks, step actions/screenshots/XML/collector results, errors, hashes, and `report.json`. Tool failures preserve collected results; missing evidence is not replaced with old files.

`status=captured` means actions and required collection succeeded; `business_correctness=not_assessed` remains. Screens can reflect cached data and successful HTTP responses can still fail consumer parsing. Higher-level checks associate evidence with frozen requirements and assert requests, storage, and actual consumer behavior. This runner executes permitted code without a security/network sandbox. Use synthetic credentials and keep private secrets out of plans, actions, and logs.
