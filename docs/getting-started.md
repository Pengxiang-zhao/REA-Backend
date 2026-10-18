# Getting started

REA-Backend provides a coding-agent workflow and deterministic command-line tools. The agent reads evidence, writes requirements and service code, and performs independent review. Commands check and package that work; they do not call a model.

## Install

Use Python 3.12 or newer:

```sh
git clone https://github.com/Pengxiang-zhao/REA-Backend.git
cd REA-Backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
rea-backend --help
rea-backend init-workspace --out workspace
```

On Windows, activate the environment with `.venv\Scripts\Activate.ps1`. The Python core uses the standard library. APK inspection and Android execution require the external tools described below. Process-group cleanup and device locking are exercised on POSIX systems; Windows device execution has not been verified.

`init-workspace` exports these resources into a new directory and refuses to overwrite an existing one:

```text
workspace/
├── skills/rea-backend/
│   ├── SKILL.md
│   ├── references/review.md
│   └── agents/openai.yaml
├── docs/
└── templates/
```

Give your coding agent the absolute path to `workspace/skills/rea-backend/SKILL.md` and the input configuration. Keep the exported tree together so its links resolve. Exporting resources does not change your agent's global configuration.

## Source route

Edit `workspace/templates/srs-inputs.json` to record the app, a fixed client revision, input paths, limitations, and desired scope. Paths are relative to the configuration file; the template expects client materials under `workspace/inputs/client/`. An absolute input path is also accepted. Only inputs with `access: "generation"` can supply evidence; `excluded` materials stay outside discovery.

```sh
rea-backend srs-explore \
  --config workspace/templates/srs-inputs.json \
  --out runs/source-analysis
```

Ask the agent to follow the exported skill, inspect the declared materials, collect additional permitted evidence, and maintain the analysis ledger. The command initializes records; it does not investigate the client for you.

After the agent resolves each registered item or records its explicit blocker/exclusion:

```sh
rea-backend srs-analysis-check \
  --config workspace/templates/srs-inputs.json \
  --analysis runs/source-analysis --require-settled

rea-backend srs-init \
  --config workspace/templates/srs-inputs.json \
  --analysis runs/source-analysis \
  --out runs/source-srs
```

The agent writes the SRS and index; a separate reviewer inspects permitted originals and records the review. The default template and method load from the installed package, regardless of the current working directory. A custom `--template` or `--method-manifest` must be declared explicitly.

## APK route

Install [REA](https://github.com/morluto/rea), its Android-analysis dependencies, a compatible Node.js version, and [Apktool](https://apktool.org/docs/install). Follow the upstream tools' current setup instructions. The bridge requires `@modelcontextprotocol/client` in the selected Node modules directory. For a source installation of REA, configure its actual paths:

```sh
export REA_ENTRYPOINT=/absolute/path/to/rea/scripts/rea.mjs
export REA_NODE_MODULES=/absolute/path/to/rea/node_modules
export REA_APKTOOL_COMMAND=/absolute/path/to/apktool
export REA_JADX_MCP_JAR=/absolute/path/to/jadx-headless-mcp.jar

rea-backend prepare \
  --apk /absolute/path/to/app.apk \
  --out runs/apk-prepared

rea-backend srs-explore \
  --config runs/apk-prepared/srs-inputs.json \
  --out runs/apk-analysis
```

Preparation records APK identity, decoded files, provider responses, candidate declarations, and limitations. It does not produce a complete specification. The agent follows the same discovery, SRS, review, and implementation stages as the source route, using only the APK route's declared inputs.

For additional targeted observations, build a JSONL request file from the current provider catalog and invoke:

```sh
rea-backend rea-session --out runs/extra-evidence --requests requests.jsonl
```

Each line is a tool request with `name` and `arguments`. The bridge accepts the read-only Android package, class, method, search, and reference tools and preserves complete requests, responses, session metadata, and failures. Add the new evidence directory to the input configuration before relying on it. `prepare --rea-requests FILE` includes additional requests in the initial session.

A previous preparation can supply its verified decoded tree:

```sh
rea-backend prepare \
  --apk /absolute/path/to/app.apk \
  --decoded runs/apk-prepared/decoded \
  --decode-record runs/apk-prepared \
  --rea-evidence runs/apk-prepared/rea \
  --out runs/apk-prepared-02
```

Reuse checks the APK identity and complete decoded inventory. Changed inputs require fresh preparation. Retained provider errors and partial results remain visible when reused.

## Build and validate

Use the configuration and SRS paths for the chosen route. Once an independent review is recorded and the agent has written the service and `implementation.json`:

```sh
rea-backend srs-check \
  --config workspace/templates/srs-inputs.json \
  --bundle runs/source-srs --require-reviewed

rea-backend srs-build \
  --config workspace/templates/srs-inputs.json \
  --srs runs/source-srs \
  --implementation work/service \
  --out runs/build-01

rea-backend srs-validate-build \
  --build runs/build-01 \
  --plan work/early-client-plan.json \
  --out runs/validation-01
```

The service, implementation mapping, and validation plan are authored for the current SRS; these paths are examples, not bundled implementations. Complete the initial client workflow before expanding the service. Package the final code into a new build and run its final validation plan. Keep previous builds and failures.

For client checks, install Android SDK platform-tools and configure a specific Android emulator. `android-doctor` verifies device and APK identity; `android-run` executes an explicit device/service plan and captures fresh evidence. Read the exported `docs/android-run.md` and `docs/srs-to-backend.md` for plan fields, early/final requirements, and process ownership. The runner executes declared commands and is not a security sandbox.

## Development checks

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
python -m build
```

The tests include synthetic source and APK fixtures, protocol and process checks, and a non-editable wheel installed into a separate virtual environment outside the repository. Synthetic fixtures exercise tooling; they do not establish real-app compatibility. Node bridge tests use a stub transport and skip when Node.js is unavailable.

New artifacts use the `rea-backend.*` format namespace and method `rea-backend/v1`. The method freezes ten normative resources, including the skill. Existing frozen artifacts from another namespace are not modified or relabeled; begin a new run with the declared inputs.
