<div align="center">

# REA-Backend

**从 Android 客户端源码或 APK，自主构建独立后端。**

由编程 agent 驱动：发现需求、实现服务，并通过实际客户端验证。

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Version 0.1.0](https://img.shields.io/badge/version-0.1.0-7C3AED)](pyproject.toml)
[![Agent Skill](https://img.shields.io/badge/Agent-Skill-14B8A6)](src/rea_backend/resources/skills/rea-backend/SKILL.md)

[English](README.md) · **简体中文**

[快速开始](#-快速开始) · [文档](#-文档导航) · [引用](#-引用)

</div>

<p align="center">
  <img src="docs/assets/pipeline.zh-CN.svg" alt="客户端源码与 APK 分析汇合为行为证据，经需求审查构建独立后端，再通过实际客户端验证。" width="1080" />
</p>

## ✨ 核心能力

- **两条输入路线。** 从客户端源码或 APK 出发，无需提供原服务端实现。
- **自主构建后端。** 在选定功能范围内，实现自行管理账号、业务数据和持久化的服务。
- **过程与结果可追溯。** 保留证据、经过审查的需求、实现映射和客户端验证记录，明确标注未知行为。

编程 agent 负责分析与实现；CLI 负责证据采集、记录冻结、构建封装和验证计划执行。最终服务可以独立于 agent 运行。

## 🚀 快速开始

需要 **Python 3.12+** 和可以执行终端命令的编程 agent。

```bash
git clone https://github.com/Pengxiang-zhao/REA-Backend.git
cd REA-Backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
rea-backend init-workspace --out workspace
```

随后将客户端源码或 APK 交给 agent，例如：

> 阅读 `workspace/skills/rea-backend/SKILL.md`。基于提供的客户端材料发现后端需求，审查需求说明书，再构建并验证独立服务。保留证据和未解决的缺口。

APK 分析和 Android 验证所需的工具需要单独安装。依赖配置、两条路线和具体命令见[入门指南](docs/getting-started.md)。

## 📚 文档导航

配套工程文档使用英文。

| 文档 | 内容 |
| --- | --- |
| [入门指南](docs/getting-started.md) | 安装与首次运行 |
| [Agent Skill](src/rea_backend/resources/skills/rea-backend/SKILL.md) | 编程 agent 遵循的工作流程 |
| [工程设计](docs/engineering.md) | 架构、产物与可靠性检查 |
| [当前范围与限制](docs/status.md) | 已包含的组件和验证状态 |
| [致谢](docs/acknowledgments.md) | 上游工具与来源说明 |

*当前为首版独立实现，尚待使用此独立安装包重新运行真实 App；此前运行结果保留各自的基线。*

## ⭐ Star 趋势

如果这个项目对你有帮助，欢迎点一个 Star。

<details>
<summary>查看 Star 历史曲线</summary>

图表依赖公开的 GitHub 数据，仓库处于私有状态时无法读取 Star 历史。

[![Star History Chart](https://api.star-history.com/chart?repos=Pengxiang-zhao/REA-Backend&type=date&legend=top-left)](https://www.star-history.com/?repos=Pengxiang-zhao%2FREA-Backend&type=date&legend=top-left)

</details>

## 📖 引用

如需引用本软件，可以使用 [CITATION.cff](CITATION.cff) 或以下 BibTeX。

```bibtex
@software{rea_backend_2026,
  author  = {{Pengxiang-zhao}},
  title   = {{REA-Backend}},
  year    = {2026},
  version = {0.1.0},
  url     = {https://github.com/Pengxiang-zhao/REA-Backend}
}
```
