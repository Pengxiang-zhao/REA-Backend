# Package scope and limitations

The initial standalone implementation includes the reusable requirements-to-backend workflow and its execution tools. Install it from this repository with `python -m pip install .`; see [Getting started](getting-started.md) for inputs and external tool setup.

## Included

| Component | Purpose |
| --- | --- |
| Packaged skill and method | Route the host coding agent through discovery, requirements, independent review, implementation, and validation. |
| APK preparation | Decode inputs, collect analysis responses, verify cached materials, and preserve provenance and limitations. |
| Analysis and SRS tools | Maintain revisions, preserve unknowns, freeze evidence and methods, and validate review bindings. |
| Build tools | Package agent-written service code and map every requirement to an implementation disposition. |
| Validation tools | Execute explicit plans against verified build copies and preserve early/final client evidence and failures. |
| Android adapter | Verify the selected emulator and APK, manage declared service/device actions, and collect evidence. |
| Regression tests | Exercise core invariants with synthetic fixtures and verify an isolated wheel installation. |

The Python core has no required third-party runtime packages. Node.js, the analysis provider and its dependencies, Apktool, and the Android SDK remain external tools. Generated services define their own runtime dependencies.

## Repository layout

```text
REA-Backend/
├── README.md
├── README.zh-CN.md
├── pyproject.toml
├── src/rea_backend/
│   ├── cli.py
│   ├── preparation.py
│   ├── analysis.py
│   ├── srs.py
│   ├── srs_build.py
│   ├── build_validation.py
│   ├── android_run.py
│   └── resources/
│       ├── skills/rea-backend/
│       ├── docs/
│       └── templates/
├── tests/
│   └── fixtures/
└── docs/
```

The method resources have one canonical location inside the package. `init-workspace` exports a usable copy without requiring the source checkout or changing global agent settings. The wheel carries the Python modules, Node bridge, skill, references, and templates. Tests and their synthetic fixtures remain in the source repository.

App source trees, APKs, generated app services, historical run data, developer environments, and media assets are maintained separately. The package does not provide a model scheduler; the host coding agent performs semantic work.

## Verification scope

Core regression tests cover revision conflicts, forbidden input access, missing evidence, changed hashes, unresolved gaps, independent review records, build integrity, failed commands, timeouts, and early/final validation bindings. Installation tests build a wheel, install it in a separate virtual environment, and freeze the default method using an external configuration.

Real-client evidence belongs to a specific app, version, build, and tool configuration. Prior app runs retain their own baselines. A fresh standalone-package run is required before attributing those outcomes to this version.

Earlier pipeline runs exercised selected source and APK workflows on wallabag, ReadYou, Tempo, Grocy, and Nextcloud. Those services and app materials are maintained separately; they are not bundled examples of this standalone package.

## Known limits

- Fresh real-app workflows using this standalone package have not been completed.
- Dependency and startup profiles for additional backend languages are not validated.
- Process cleanup and device locking are exercised on POSIX systems; Windows device execution is unverified.
- External analysis and Android tools are installed separately. Compatibility depends on their versions and configuration.
