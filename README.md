<div align="center">

# REA-Backend

**Build independent backends from Android client source or APKs.**

An agent-driven pipeline: discover requirements, implement a service, and validate it with the client.

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Version 0.1.0](https://img.shields.io/badge/version-0.1.0-7C3AED)](pyproject.toml)
[![Agent Skill](https://img.shields.io/badge/Agent-Skill-14B8A6)](src/rea_backend/resources/skills/rea-backend/SKILL.md)

**English** · [简体中文](README.zh-CN.md)

[Quick start](#-quick-start) · [Docs](#-documentation) · [Citation](#-citation)

</div>

<p align="center">
  <img src="docs/assets/pipeline.svg" alt="Client source and APK analysis converge into evidence, reviewed requirements, an independent backend, and client validation." width="1080" />
</p>

## ✨ What it does

- **Two input routes.** Start from client source or an APK, without requiring the original server implementation.
- **Your own backend.** Build a service that manages its own accounts, business data, and persistence for the chosen feature scope.
- **Traceable results.** Keep evidence, reviewed requirements, implementation mappings, and client validation records together. Unknown behavior stays explicit.

Your coding agent performs the analysis and programming. The CLI collects evidence, freezes records, packages builds, and runs validation plans. The resulting service runs independently of the agent.

## 🚀 Quick start

Requires **Python 3.12+** and a coding agent with terminal access.

```bash
git clone https://github.com/Pengxiang-zhao/REA-Backend.git
cd REA-Backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
rea-backend init-workspace --out workspace
```

Then give your agent the client source or APK and a prompt such as:

> Read `workspace/skills/rea-backend/SKILL.md`. Use the supplied client materials to discover backend requirements, review the specification, then build and validate an independent service. Preserve evidence and unresolved gaps.

APK analysis and Android validation use separately installed tools. See the [setup guide](docs/getting-started.md) for dependencies, both input routes, and commands.

## 📚 Documentation

| Guide | Start here for |
| --- | --- |
| [Getting started](docs/getting-started.md) | Installation and your first run |
| [Agent Skill](src/rea_backend/resources/skills/rea-backend/SKILL.md) | The workflow your coding agent follows |
| [Engineering](docs/engineering.md) | Architecture, artifacts, and reliability checks |
| [Scope & limitations](docs/status.md) | Included components and validation status |
| [Acknowledgments](docs/acknowledgments.md) | Upstream tools and attribution |

*Initial standalone version. Fresh real-app runs with this extracted package are still pending; earlier runs retain their own baselines.*

## ⭐ Star history

If this project is useful, consider giving it a star.

<details>
<summary>View the star history chart</summary>

The chart requires public GitHub data and cannot read this repository's star history while it is private.

[![Star History Chart](https://api.star-history.com/chart?repos=Pengxiang-zhao/REA-Backend&type=date&legend=top-left)](https://www.star-history.com/?repos=Pengxiang-zhao%2FREA-Backend&type=date&legend=top-left)

</details>

## 📖 Citation

To reference this software, use [CITATION.cff](CITATION.cff) or the BibTeX below.

```bibtex
@software{rea_backend_2026,
  author  = {{Pengxiang-zhao}},
  title   = {{REA-Backend}},
  year    = {2026},
  version = {0.1.0},
  url     = {https://github.com/Pengxiang-zhao/REA-Backend}
}
```
