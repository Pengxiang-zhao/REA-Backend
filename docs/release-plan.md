# Release Plan

The first release will package the **REA-Backend pipeline** for independent installation and use. This repository currently provides the engineering documentation; executable code and installation instructions will follow after extraction and verification.

## First-release scope

| Component | Deliverable |
| --- | --- |
| Agent workflow | Analysis, requirements, review, implementation, and validation instructions |
| Execution tools | Input preparation, analysis records, requirements checks, build packaging, and development validation |
| APK analysis adapter | Tool discovery, invocation records, and version binding for external analysis tools |
| Artifact contracts | Documented record formats, validators, and valid and invalid examples |
| Templates | Input, requirements, implementation, and validation templates with clear authoring responsibilities |
| Client validation adapters | Android diagnostics, device and service management, action execution, and evidence capture |
| Tests and usage documentation | Regression fixtures and verified instructions from input preparation to backend delivery |

Generated app services and original app materials are maintained separately. The core package includes reusable tools and synthetic fixtures. Large input files, runtime databases, developer credentials, and third-party source trees are outside its default scope.

## Proposed repository layout

This is the intended layout for the code release. The executable package, license files, and test directories are not yet included in this documentation preview.

```text
REA-Backend/
├── README.md
├── README.zh-CN.md
├── pyproject.toml
├── LICENSE
├── THIRD_PARTY_NOTICES.md
├── src/rea_backend/
│   ├── cli.py
│   ├── preparation/
│   ├── analysis/
│   ├── requirements/
│   ├── build/
│   ├── validation/
│   └── adapters/
├── skills/
├── templates/
├── tests/
│   └── fixtures/
└── docs/
```

Package names and command interfaces will be finalized during extraction. External analysis tools and the Android SDK remain separately installed dependencies. The code release will include its selected license and applicable third-party notices.

## Release acceptance checks

1. **Standalone installation.** Install a built package outside the development repository, then run it with an external configuration. Skills, method documents, and templates must load from packaged resources without developer-machine paths.
2. **Complete workflow resources.** Confirm that all instructions, references, and templates resolve. Each input route must use its own permitted materials and evidence.
3. **Core regression coverage.** Check revision conflicts, preserved gaps, changed hashes, invalid references, and artifacts from failed or timed-out runs.
4. **Both input routes.** Complete source and APK runs with fixed inputs and recorded tool execution. Keep fixture checks and actual-client checks separately identifiable.
5. **Independent service operation.** Start a generated service in a new directory with its own data store. Verify business reads and writes and persistence across a restart, without the original server or analysis tools running.
6. **Client compatibility.** Pin the client version, document its connection method and adaptations, and exercise selected workflows against early and final builds. Preserve business and storage assertions.
7. **Release integrity.** Verify the package inventory and dependencies, exclude local runtime data and credentials, and check the documented startup instructions.

Each check is completed through execution against the extracted package. Results from earlier development builds are retained with their own versions.

## Milestones

| Milestone | Completion criterion |
| --- | --- |
| Extract code, skills, and resources | The package installs independently and passes the core regression checks. |
| Exercise both routes | Each route produces requirements, a service, client-validation evidence, and recorded limitations. |
| Publish a usable code release | Installation, commands, dependencies, licensing, and artifact scope match the shipped files. |
| Reduce repeated work | Caches verify input identity, and execution tools preserve required checks and evidence. |
| Support additional backend stacks | New dependency and startup profiles pass deployment and client validation. |
