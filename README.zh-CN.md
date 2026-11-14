# SparseRead

Codex / Pi 框架适配已加入源码安装入口：

历史 `v0.1.3` 标签已包含两个适配。当前升级尚未发布；如需使用本次候选改动，请使用包含相应提交的 checkout，[v0.1.3 源码压缩包](https://github.com/Liuzedooong/SparseReading/archive/refs/tags/v0.1.3.zip)不包含本次升级。在项目根目录运行：

原仓库的 Release 附件没有迁移，版本标签与源码仍然保留。

```bash
uv run --python 3.12 python scripts/install_sparseread.py \
  --platform codex --workspace /absolute/path/to/project --doctor
uv run --python 3.12 python scripts/install_sparseread.py \
  --platform pi --workspace /absolute/path/to/project --doctor
```

安装后在目标项目重启并审核信任提示。Codex 的 hook 信任与插件安装是分开的；
Pi 项目扩展也需用户批准。加 `--sparseread-mode advisory` 可仅使用工具/提示而不
拦截原生读取。两端复用共享核心，尚不代表论文外的新框架收益实测。
详见[适配设计、安装与回退](docs/codex-pi-adapters.md)。

<div align="center">

**少读一点，解决更多。**

SparseRead 是一个免训练、面向工具调用型 Agent 的阅读层。在大范围读取之前，
先控制哪些证据真正进入模型上下文，同时保留来源锚点、细化、验证和原生回退能力。

[![CI](https://github.com/Liuzedooong/SparseReading/actions/workflows/ci.yml/badge.svg)](https://github.com/Liuzedooong/SparseReading/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[论文](https://arxiv.org/abs/2608.22237) · [项目网站](https://sparseread.pages.dev/) · [English](README.md)

</div>

## 🔥 最新动态

- **2026-09-28：** [v0.1.3](https://github.com/Liuzedooong/SparseReading/releases/tag/v0.1.3) 修复 Codex/Pi 在大型工作区切换完整原生读取时的超时。
- **2026-09-28：** [v0.1.2](https://github.com/Liuzedooong/SparseReading/releases/tag/v0.1.2) 新增 Codex 和 Pi 支持。
- **2026-09-14：** 支持 Claude Code、OpenCode、OpenClaw 和 NanoBot 四个框架。

<p align="center">
  <img src="https://raw.githubusercontent.com/Liuzedooong/SparseReading/main/assets/launch/sparseread-demo-wide.gif" alt="SparseRead 回放：全文读取 vs 稀疏取证，以及成本-质量前沿" width="100%">
</p>

Agent 很擅长推理，但默认的阅读动作往往仍然是：

```text
全部读入 -> 全部放进上下文 -> 再开始推理
```

对于长报告、PDF、workspace、日志、表格和多文件审计，这种方式成本很高。
SparseRead 在 Agent 原生工具前增加一个小型控制面：

```text
artifact -> Read Gate -> Reader Backend -> EvidencePack -> refine / verify / stop
```

Agent 仍然决定自己需要什么；SparseRead 让这次读取有边界、有来源、可继续细化，
也能在原生访问更合适时回退。

## 结果概览

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

### 跨框架支持

论文的端到端可迁移性表格评测了 NanoBot、OpenCode、OpenClaw 三个框架；当前单仓库
发布基线新增了 Claude Code 第四个 adapter：

| 框架 | Adapter | token 中位降幅 | 时间中位降幅 | 论文状态 |
|---|---|---:|---:|---|
| [NanoBot](integrations/nanobot/python/README.md) | `sparseread-nanobot` | **69.0%** | **64.4%** | 已评测 |
| [OpenCode](integrations/opencode/README.md) | `sparseread-opencode` | **71.8%** | **64.9%** | 已评测 |
| [OpenClaw](integrations/openclaw/README.md) | `sparseread-openclaw` | **28.7%** | **28.2%** | 已评测 |
| [Claude Code](integrations/claude/README.md) | `sparseread-claude` | — | — | 源码适配，未纳入论文表格 |

Claude Code 使用 MCP 加逐事件 `PreToolUse`/`PostToolUse` hooks，不使用 npm 插件。
当前本地集成验证报告见
[`benchmarks/qwenclawbench/claude_final_aggregate_20260805.md`](https://github.com/Liuzedooong/SparseReading/blob/v0.1.3/benchmarks/qwenclawbench/claude_final_aggregate_20260805.md)。
该报告尚未纳入论文中的三框架表格。

### v0.1.4 宿主验证

在 macOS arm64 上，OpenCode 2.3.0（另测 V1 1.17.14/1.19.5）、Claude Code
2.1.325、Codex CLI 0.169.0 和官方 NanoBot 0.4.1 AgentLoop 已完成相应真实宿主的
确定性协议检查，并各有一次有限 DeepSeek 工作流。Claude 和 Codex 使用仅供测试的
协议转换器，Claude 的模型运行早于最终候选的少量改动；NanoBot 使用官方宿主与
Chat SSE。NanoBot 每个持久回合须先选择原生 stock `read_file` 才能直接访问
SparseRead 源，shell 继续走原生路径。`05768c8` 源码归档也通过 Pi 0.87.1 与
OpenClaw 2026.7.1-2 的指定宿主回归；这是固定版本验证，不代表两者均已升级至最新版。
上述结果不建立 Windows、Desktop、远程环境支持或升级后的性能收益；
详细范围和证据见[验证矩阵](docs/framework_upgrade_20261114/validation-summary.md)。

## 安装

源码安装器会为所选框架构建受管 runtime，安装后的集成不会在运行时导入本 checkout
的源码。v0.1.4 提供源码安装归档。

环境要求：Python 3.11+、[uv](https://docs.astral.sh/uv/)、OpenCode/OpenClaw/Codex/Pi 所需的
已安装安全更新的 Node.js 22 或更高版本，以及目标 Agent CLI。

安装器会在修改 workspace 前校验 Python 版本。如果系统默认 `python3` 过旧，推荐使用
上面的 `uv run` 形式，或显式传入 `--python /path/to/python3.12`。默认安装 PDF/XLSX
阅读器；只处理文本时可以加 `--reader-extras none`。

```bash
curl -fLO https://github.com/Liuzedooong/SparseReading/releases/download/v0.1.4/sparseread-source-installer-v0.1.4.zip &&
curl -fLO https://github.com/Liuzedooong/SparseReading/releases/download/v0.1.4/SHA256SUMS &&
grep '  sparseread-source-installer-v0.1.4.zip$' SHA256SUMS | shasum -a 256 -c - &&
unzip -q sparseread-source-installer-v0.1.4.zip &&
cd sparseread-v0.1.4
```

上述校验命令适用于 macOS；源码安装归档不包含 tests 或 benchmark。

选择一个框架：

```bash
# Codex / Pi：选择对应项目
uv run --no-project --python 3.12 python scripts/install_sparseread.py --platform codex --workspace /path/to/project --doctor
uv run --no-project --python 3.12 python scripts/install_sparseread.py --platform pi --workspace /path/to/project --doctor

# OpenCode：安装到已有 workspace
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform opencode \
  --opencode-workspace /path/to/your/project \
  --doctor

# OpenClaw：安装到当前 profile
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform openclaw \
  --doctor

# Claude Code：向 workspace 写入 MCP 和逐事件 hooks
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform claude \
  --claude-workspace /path/to/your/project \
  --doctor
```

NanoBot 作为 Python 依赖安装 `sparseread-core` 和 `sparseread-nanobot`，见
[NanoBot adapter 说明](integrations/nanobot/python/README.md)。完整平台矩阵见
[`docs/sparseread_installation.md`](docs/sparseread_installation.md)；英文简版见
[`docs/installation.md`](docs/installation.md)。

安装完成后，用户不需要手动调用 `sro_preview` 或填写 `HintSpec`。只要在任务中说明
使用 SparseRead，例如：

```text
请使用 SparseRead 阅读这个大报告，只提取回答问题所需的证据；证据足够后停止读取。
```

### 快速体验

完整 git checkout 内置了一个长 Markdown fixture；源码安装归档不包含该 fixture：

```bash
opencode run "Use SparseRead to inspect tests/fixtures/quick_test/incident-report.md and report ROOT_CAUSE, MITIGATION_OWNER, and FINAL_DEADLINE."
```

其他 adapter 也可提供同类请求；当前候选实际验证范围见验证矩阵。

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
  uv run --project . --extra test pytest -q
```

更多架构约束见[发布架构](docs/release_architecture.md)。benchmark 和历史结果用于复现，
不会被任何发布包导入。

## 当前边界

- `v0.1.3` 是历史源码标签；当前候选尚未发布为新版本。
- PyPI 项目注册待完成；npm 和各框架官方 marketplace 尚未作为发行入口，使用源码安装器。
- Claude 候选使用 MCP 和逐事件 hooks；本轮未独立验证 Windows 和 PowerShell 路径。
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
