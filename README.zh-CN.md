# SparseRead

<div align="center">

**面向 AI Agent 的按需阅读**

SparseRead 是一个免训练的阅读层。Agent 可以在长报告、PDF、日志和表格中
只提取回答问题所需的证据，保留来源定位，并在需要时继续读取原文。

[![CI](https://github.com/Liuzedooong/SparseReading/actions/workflows/ci.yml/badge.svg)](https://github.com/Liuzedooong/SparseReading/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[安装](#安装) · [支持版本](#支持版本) · [论文](https://arxiv.org/abs/2608.22237) · [项目网站](https://sparseread.pages.dev/) · [English](README.md)

</div>

## 🔥 最新动态

- **2026-11-14 · [v0.1.4](https://github.com/Liuzedooong/SparseReading/releases/tag/v0.1.4) 更新** — 已适配当日最新的 OpenCode **2.3.0**、Claude Code **2.1.325**、Codex CLI **0.169.0** 和 NanoBot **0.4.1**。OpenCode V2 新增用户级全局安装，初装默认 `advisory`，首次成功取证满 48 小时后建议考虑 `auto`。
- **2026-09-28：** [v0.1.3](https://github.com/Liuzedooong/SparseReading/releases/tag/v0.1.3) 修复 Codex/Pi 在大型工作区切换完整原生读取时的超时。
- **2026-09-28：** [v0.1.2](https://github.com/Liuzedooong/SparseReading/releases/tag/v0.1.2) 新增 Codex 和 Pi 支持。
- **2026-09-14：** 支持 Claude Code、OpenCode、OpenClaw 和 NanoBot 四个框架。

## 支持版本

| 框架 | 已验证的宿主版本 | 安装方式 |
|---|---|---|
| OpenCode | **2.3.0** · V1 1.19.5 和 1.17.14 | [项目安装或用户级全局安装](docs/sparseread_installation.md#opencode-v2-全局安装) |
| Claude Code | **2.1.325** | [MCP 和 hooks](integrations/claude/README.md) |
| Codex CLI | **0.169.0** | [项目插件和 MCP](docs/codex-pi-adapters.md#一次安装) |
| NanoBot | **0.4.1** | [Python 适配器与 AgentLoop](integrations/nanobot/python/README.md) |
| OpenClaw | 2026.7.1-2 | [Profile 插件](integrations/openclaw/README.md) |
| Pi | 0.87.1 | [项目扩展](docs/codex-pi-adapters.md#一次安装) |

上表列出在 macOS arm64 上实测的版本。OpenClaw 和 Pi 为指定版本回归。
权限、模型运行及平台范围见[宿主验证矩阵](docs/framework_upgrade_20261114/validation-summary.md)。

## 安装

准备 Python 3.11+、[uv](https://docs.astral.sh/uv/) 和目标 Agent。OpenCode、OpenClaw、
Codex、Pi 还需要 Node.js 22 或更新版本。以下下载校验命令适用于 macOS。

请从一个新目录开始。[下载更新后的 v0.1.4 安装 ZIP](https://github.com/Liuzedooong/SparseReading/releases/download/v0.1.4/sparseread-source-installer-v0.1.4-20261114.zip)。

```bash
curl -fLO https://github.com/Liuzedooong/SparseReading/releases/download/v0.1.4/sparseread-source-installer-v0.1.4-20261114.zip &&
curl -fLO https://github.com/Liuzedooong/SparseReading/releases/download/v0.1.4/SHA256SUMS-20261114 &&
grep '  sparseread-source-installer-v0.1.4-20261114.zip$' SHA256SUMS-20261114 | shasum -a 256 -c - &&
unzip -q sparseread-source-installer-v0.1.4-20261114.zip &&
cd sparseread-v0.1.4
```

### OpenCode V2 全局安装

在解压目录运行，安装一次即可在当前用户的多个本地项目中使用。

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform opencode --global --doctor
```

重启 OpenCode 后，可让 Agent「用 SparseRead 从这份长报告中提取根因和对应的原文依据」。
首次全局安装默认使用 `advisory`，保留原生读取。首次成功取得证据满 48 小时后，
下一次成功取证会在终端提示一次。想切换时，加上 `--sparseread-mode auto` 重跑安装并重启；
重装时省略模式会沿用之前的选择。

项目安装以及 Claude Code、Codex、NanoBot、OpenClaw、Pi 的安装命令见[完整安装指南](docs/sparseread_installation.md)。

### 快速体验

完整 git checkout 内置了一个长 Markdown fixture；源码安装归档不包含该 fixture：

```bash
opencode run "Use SparseRead to inspect tests/fixtures/quick_test/incident-report.md and report ROOT_CAUSE, MITIGATION_OWNER, and FINAL_DEADLINE."
```

其他 adapter 也可提供同类请求；实际验证范围见上表。

## 结果概览

<p align="center">
  <img src="assets/launch/sparseread-demo-wide.gif" alt="SparseRead 回放：全文读取 vs 稀疏取证，以及成本-质量前沿" width="100%">
</p>

当前论文评测覆盖 125 个任务、5 类工作场景和 6 个主流模型：Claude Opus 5、
Qwen3.6-Plus、DeepSeek-V4-Flash、DeepSeek-V4-Pro、GLM-5.1、Kimi-K2.5。

| 指标 | 论文报告结果 |
|---|---:|
| 最高 token 降幅 | **92.9%** |
| 最高端到端时间降幅 | **89.0%** |
| token 和时间同时下降的模型–场景单元 | **30 / 30** |
| 得分保持或提升的单元 | **26 / 30** |
| 稀疏阅读场景中得分保持或提升的单元 | **22 / 24** |

收益并不依赖单一模型：六个模型都出现在完整评测矩阵中，并在论文报告中获得了
收益。指标定义、基线和完整结果请见[论文](https://arxiv.org/abs/2608.22237)。

### 论文的跨框架评测

| 框架 | token 中位降幅 | 时间中位降幅 |
|---|---:|---:|
| NanoBot | **69.0%** | **64.4%** |
| OpenCode | **71.8%** | **64.9%** |
| OpenClaw | **28.7%** | **28.2%** |

## 工作方式

- **Read Gate**：根据 artifact 形态和任务成本选择 `auto`、`native` 或 `advisory`。
  小文件、全表计算等低收益任务保持原生工具。
- **Reader Backends**：为文本/PDF、结构化数据和多文件集合提供有类型、有限制的读取。
- **EvidencePack**：返回带来源锚点的紧凑证据、未解决需求和下一步建议。
- **有状态协议**：支持 preview、定向读取、细化、验证、显式原文回退和停止。

生产入口由框架暴露，用户通常不需要直接调用：

```text
sro_preview(path) -> 有限预览 + FileCard
sro_read(target, mode, hint) -> EvidencePack
sro_raw(raw_ref) -> 显式原文回退
```

## 仓库结构

```text
packages/sparseread-core/       框架无关 core 和测试
integrations/<framework>/       NanoBot、OpenCode、OpenClaw、Claude Code adapter
scripts/install_sparseread.py   源码安装器和 doctor
tests/                          发布、bridge、gate、安装器测试
benchmarks/                     可复现实验 runner 和精选 fixture
docs/                           安装、架构和设计说明
```

Core 与 adapter 分离：adapter 只负责宿主框架的 bridge、生命周期和安装面，不复制阅读
协议。

## 开发与测试

以下命令需要完整 git checkout；源码安装归档不包含 tests 和 benchmark。

单独运行 core 测试：

```bash
uv run --project packages/sparseread-core --with pytest --with pytest-asyncio \
  pytest packages/sparseread-core/tests -q
```

运行完整发布测试：

```bash
PYTHONPATH="packages/sparseread-core/src:integrations/nanobot/python/src:integrations/opencode/python/src:integrations/openclaw/python/src:integrations/claude/python/src" \
  uv run --project . --extra test --with 'nanobot-ai==0.4.1' pytest -q
```

更多架构约束见[发布架构](docs/release_architecture.md)。benchmark 和历史结果用于复现，
不会被任何发布包导入。

## 当前边界

- PyPI 项目注册待完成；npm 和各框架官方 marketplace 尚未作为发行入口，使用源码安装器。
- Claude Code 使用 MCP 和逐事件 hooks；本轮Windows 和 PowerShell 仍待单独验证。
- SparseRead 是选择性基础设施：小文件、精确全表计算和其他低稀疏任务应继续使用原生访问。

## 贡献

提交 PR 前请阅读 [CONTRIBUTING.md](https://github.com/Liuzedooong/SparseReading/blob/main/CONTRIBUTING.md)。欢迎 bug 报告和聚焦于框架适配的
反馈。

## 引用

```bibtex
@article{liu2026readless,
  title   = {Read Less, Solve More: Token-Efficient Sparse Reading for AI Agents},
  author  = {Liu, Zedong and Wu, Jiaan and Ma, Xinyang and Xu, Le and Wang, Kai and Hu, Yuanchao and Tao, Dingwen and Tan, Guangming},
  journal = {arXiv preprint arXiv:2608.22237},
  year    = {2026}
}
```

## 许可证

SparseRead 使用 [MIT License](LICENSE) 发布。


## 仓库迁移说明

本仓库保留了原仓库的代码、提交历史、分支和标签，但属于独立仓库，没有继承 GitHub Fork 关系、Star、Issue、PR 和 Release 附件。
