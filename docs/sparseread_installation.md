# SparseRead 安装指南

这份文档描述 v0.1.4 源码安装形态。SparseRead 现在是
多个框架共享一个 core（`packages/sparseread-core`），桥接面不同：

- NanoBot：作为普通 Python 依赖安装（`sparseread-core` + `sparseread-nanobot`），
  由 NanoBot 框架内部加载 adapter；
- OpenCode：通过 TS 插件 + Python bridge 安装到 workspace；
- OpenClaw：通过 npm 插件包 + Python bridge 安装到 OpenClaw profile；
- Claude Code：通过 MCP stdio server + 逐事件 PreToolUse/PostToolUse hook
  安装（Claude Code 没有 npm 插件系统，`.mcp.json` 和
  `.claude/settings.local.json` 就是它的“插件形态”）。

PyPI 项目注册待完成；npm/官方插件市场目前不是发行入口。用户可以从源码
稳定安装、验证、使用，并通过共享 core 保持协议一致。Codex/Pi 入口见
[单独指南](codex-pi-adapters.md)。

v0.1.4 的已核验范围以 [验证矩阵](framework_upgrade_20261114/validation-summary.md)
为准，主要是 macOS arm64 指定版本。Linux、Windows、Desktop 和远程环境不能因
安装脚本存在就视为已通过；[Windows 历史记录](https://github.com/Liuzedooong/SparseReading/blob/main/docs/windows_fresh_install_test_report.md)
只描述当时的旧候选，不代表本轮适配验证。源码安装归档不包含 tests 或 benchmark。

## 当前生产入口

这是框架和 agent 内部看到的工具形态，不是要求用户手动输入的命令。生产路径从 `sro_preview` 开始：

```text
sro_preview(path) -> L0 默认预览，内含 FileCard，不需要 HintSpec
sro_read(target, mode, hint) -> 有明确目标时再读取定向证据
sro_raw(raw_ref) -> 明确需要原文时的回溯入口
```

`sro_card` 仍会注册，但只用于 benchmark 和旧脚本兼容。新插件和新框架集成都应该把 `sro_preview` 作为内部第一入口。

## 模型可见的 SparseRead 指南在哪里

各框架不是完全相同的 skill 文件形态：

- NanoBot adapter 内置 guidance（与旧宿主 SKILL.md 正文一致，以 system 消息
  注入），不依赖仓库内的 NanoBot framework checkout。
- OpenClaw 插件随带 skill：`integrations/openclaw/plugin/skills/sparse-reading/SKILL.md`。
- OpenCode 当前没有独立 `SKILL.md`。它通过插件注册 `sro_preview`、`sro_read` 等工具，并在大文件/截断输出场景给模型 nudge。日常使用时，用户应该在任务里要求 agent 自动使用 SparseRead。
- Claude Code 使用安装器写入 workspace 的 `CLAUDE.md`（模板位于
  `integrations/claude/CLAUDE.md`），配合 MCP 工具描述一起给模型提供使用协议。

所以，用户文档不应该写成工具调用教程；工具调用顺序是给模型和插件看的。

## 环境要求

- Python 3.11+
- `uv`
- 已安装安全更新的 Node.js 22 或更高版本
- `npm`
- 已安装的 OpenCode CLI、OpenClaw CLI 或 Claude Code CLI（按目标框架选择）

Windows 上如果 `npm`、`openclaw` 等入口实际是 `.cmd/.exe/.bat`，安装脚本会自动解析到对应入口，不需要手动修改命令名。

安装器会在修改目标 workspace 或 profile 前校验 Python 和宿主 CLI。推荐使用下文的
`uv run --project . python ...` 形式，以避免系统 `python3` 低于 3.11；直接调用脚本时
可用 `--python /path/to/python3.12` 显式指定。默认安装 PDF/XLSX 阅读器，纯文本部署可用
`--reader-extras none` 减少 runtime 依赖。

当前候选在 macOS arm64 上验证过 OpenCode 2.3.0（另测 V1 1.17.14/1.19.5）、
Claude Code 2.1.325、Codex CLI 0.169.0 与官方 NanoBot 0.4.1 的指定宿主路径。
固定提交 `05768c8` 的源码归档已通过 Pi 0.87.1 与 OpenClaw 2026.7.1-2
的指定宿主回归；这不表示二者已升级至最新版。各自模型、权限和工件边界见验证矩阵。

用户安装时只需要选择一个 SparseRead 模式：

- `auto`：默认模式。SparseRead 会在高收益任务上自动接管大文件、PDF、日志和审计证据包的 broad read/search/dump；小文件、脚本、配置、全表计算等低收益任务保持原生工具。
- `advisory`：只注册 SparseRead 工具和提示，不拦截原生读取，依靠模型自然选择是否使用 SparseRead。

不传 `--sparseread-mode` 时，除 OpenCode V2 全局初次安装外默认是 `auto`。OpenClaw `2026.6.11` 的 `auto` 会自动配置必要的 lifecycle hook 权限；如果 `doctor` 报告 hook 未加载，优先检查 OpenClaw 插件权限或 profile 配置。只有明确想关闭拦截时，才使用 `--sparseread-mode advisory`。

## 验证范围

| 路径 | 本轮状态 |
|---|---|
| OpenCode 2.3.0；V1 1.17.14/1.19.5 | macOS arm64 指定宿主场景通过；远程和其他系统未验证 |
| Claude Code 2.1.325 | macOS arm64 hooks/MCP 指定场景通过；Windows/PowerShell 未验证 |
| Codex CLI 0.169.0 | macOS arm64 指定 CLI 场景通过；Desktop/Cloud/Web 未验证 |
| NanoBot 0.4.1 | macOS arm64 官方 AgentLoop 与指定权限场景通过；其他版本及 Windows 未验证 |
| OpenClaw 2026.7.1-2 / Pi 0.87.1 | `05768c8` 源码归档在 macOS 完成指定宿主回归；不代表最新版升级 |

真实模型验证和确定性测试、候选 wheel 与最终归档的区别见
[验证矩阵](framework_upgrade_20261114/validation-summary.md)。


## OpenCode V2 全局安装

在更新后的 v0.1.4 安装目录中执行：

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform opencode --global --doctor
```

默认仍为项目安装。`--global` 面向当前用户，不可与 `--opencode-workspace`
或其他 platform 一起使用；仅支持 OpenCode V2，V1 尚不具备 V2 所需的权限绑定。
默认位置为 `$XDG_CONFIG_HOME/opencode`，未设置时为 `~/.config/opencode`；
绝对路径形式的 `OPENCODE_CONFIG_DIR` 会覆盖此位置，相对路径会被拒绝。
每个本地会话使用其实际工作目录；远程工作区不受支持。安装后重启 OpenCode。

全局初次安装默认 `advisory`；重装时不指定模式会保留原有 policy 和 bridge 模式。
若希望改用 auto，可自行用 `--platform opencode --global --sparseread-mode auto`
重跑安装并重启 OpenCode。在本地终端 UI 中，首次在 advisory 模式下成功取得非空 `sro_read` 证据
满 48 小时后，下一次符合条件的读取会显示一次建议；不会自动切换模式。提示需要读取发生时本地 TUI 正在运行；
无界面运行不会显示提示。此功能只保存首次时间和是否提示，不保存来源路径或内容。

在实测的 2.3.0 中，全局与项目中同 ID 的插件同时存在时，宿主只运行全局副本，
并可能将项目副本显示为 `Duplicate plugin ID: sparseread` 失败；项目文件仍保留。
若某个项目需要禁用 SparseRead，可在该项目的 OpenCode 配置中加入
`"plugins": ["-sparseread"]`（已有列表时合并），该设置会同时禁用同 ID 的全局
和项目副本。也可自行检查并移除旧的项目 SparseRead 插件。

卸载全局副本时，检查后只移除全局配置根目录内的 `plugins/sparseread`、
`sparseread.json`、`sparseread/runtime/opencode` 和（如存在）
`sparseread/onboarding`，保留其他插件及配置。
移除后，保留的项目副本可再次生效。`--doctor` 使用隔离的确定性 provider，
验证宿主注册及调用，不代表真实模型质量或性能测试。

## Fresh Machine 安装

下载源码安装归档（以下校验命令适用于 macOS）：

```bash
curl -fLO https://github.com/Liuzedooong/SparseReading/releases/download/v0.1.4/sparseread-source-installer-v0.1.4-20261114.zip &&
curl -fLO https://github.com/Liuzedooong/SparseReading/releases/download/v0.1.4/SHA256SUMS-20261114 &&
grep '  sparseread-source-installer-v0.1.4-20261114.zip$' SHA256SUMS-20261114 | shasum -a 256 -c - &&
unzip -q sparseread-source-installer-v0.1.4-20261114.zip &&
cd sparseread-v0.1.4
```

以下测试需要完整 git checkout；源码安装归档不包含 tests。先跑 release fixture：

```bash
PYTHONPATH="packages/sparseread-core/src:integrations/nanobot/python/src:integrations/opencode/python/src:integrations/openclaw/python/src:integrations/claude/python/src" \
  uv run --project . --extra test pytest tests/test_release_fixtures.py -q
```

完整本地回归：

```bash
PYTHONPATH="packages/sparseread-core/src:integrations/nanobot/python/src:integrations/opencode/python/src:integrations/openclaw/python/src:integrations/claude/python/src" \
  uv run --project . --extra test pytest -q
```

Windows PowerShell 可直接使用：

```powershell
$env:PYTHONPATH="packages/sparseread-core/src;integrations\nanobot\python\src;integrations\opencode\python\src;integrations\openclaw\python\src;integrations\claude\python\src"
  uv run --project . --extra test pytest tests/test_release_fixtures.py -q
```

## 安装到 OpenCode

假设你已经能在目标 workspace 里运行 `opencode`。

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform opencode \
  --opencode-workspace /path/to/your/project \
  --doctor
```

安装脚本会写入：

```text
/path/to/your/project/.opencode/plugins/sparseread.js       # V1
/path/to/your/project/.opencode/plugins/sparseread/        # V2
/path/to/your/project/.opencode/sparseread.json
/path/to/your/project/.sparseread/runtime/opencode/
```

启动 OpenCode：

```bash
cd /path/to/your/project
opencode run "Use SparseRead to inspect the large report and answer the question"
```

Windows PowerShell：

```powershell
uv run --no-project --python 3.12 python scripts/install_sparseread.py --platform opencode --opencode-workspace D:\path\to\your\project --doctor
Set-Location D:\path\to\your\project
opencode run "请自动使用 SparseRead 阅读长报告并回答问题"
```

如果 `opencode` 不在 PATH，显式指定可执行文件路径：

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform opencode \
  --opencode-cmd /absolute/path/to/opencode \
  --opencode-workspace /path/to/your/project \
  --doctor
```

OpenCode 插件会暴露：

```text
sro_preview, sro_raw, sro_card, sro_read, sro_trace
```

注意：OpenCode 对 workspace 外路径的默认权限更严格。第一次验证安装时，推荐把测试文件放在当前 workspace 内，或者直接把本仓库根目录作为 workspace 来运行 quick test，而不是从另一个 workspace 读取本仓库外的绝对路径文件。

## 安装到 OpenClaw

假设你已经能运行 `openclaw`。

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform openclaw \
  --doctor
```

安装脚本会：

- 构建 `integrations/openclaw/plugin`；
- 将插件打成 npm tarball 后执行普通 `openclaw plugins install`（不是 source link）；
- 启用 `sparseread-openclaw`；
- 在 OpenClaw profile 下创建 wheel-only 的受管 Python runtime，并写入 bridge 配置。

检查插件是否加载：

```bash
openclaw plugins inspect sparseread-openclaw --runtime --json
```

预期工具面：

```text
sro_preview, sro_raw, sro_card, sro_read, sro_decide, sro_trace
```

如果使用命名 profile：

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform openclaw \
  --openclaw-profile work \
  --doctor

openclaw --profile work plugins inspect sparseread-openclaw --runtime --json
```

OpenClaw 的 provider/model/key 仍由 OpenClaw 自己配置。SparseRead 不安装或管理模型密钥。

第一次在新机器上使用 OpenClaw 前，先确保你的目标 profile 本身已经能正常启动普通 agent 会话；SparseRead 只负责插件和 bridge，不替你修 OpenClaw 自己的 provider/model 配置。

Windows PowerShell：

```powershell
uv run --no-project --python 3.12 python scripts/install_sparseread.py --platform openclaw --doctor
```

## 安装到 NanoBot

NanoBot 使用 `sparseread-core` 与 `sparseread-nanobot` Python 包；候选的可选
`nanobot` 依赖固定 `nanobot-ai==0.4.1`，在官方 AgentLoop 启动前调用
`sparseread_nanobot.install(agent)`。每个持久回合必须先选择 stock `read_file`
建立原生 reader 权限证明，有界读取也可；shell、目录列表和有界/强制读取保持原生。
缺少证明或路径被拒绝时使用原生工具，非持久回合跳过 SparseRead 源访问。
测试仅覆盖 macOS 上的 0.4.1 场景，其他版本与 Windows 未验证。具体安装和
权限边界见 [NanoBot adapter 指南](../integrations/nanobot/python/README.md)
及验证矩阵；历史 0.3.x 论文收益不代表新版本的性能结果。

## 安装到 Claude Code

假设你已经能运行 `claude`：

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform claude \
  --claude-workspace /path/to/your/project \
  --doctor
```

Windows PowerShell：

```powershell
uv run --no-project --python 3.12 python scripts/install_sparseread.py --platform claude --claude-workspace D:\path\to\project --doctor
```

安装脚本会：

- 构建 `sparseread-core` + `sparseread-claude` wheel，创建受管 Python runtime
  `~/.sparseread/claude/`；
- 合并写入 `/path/to/your/project/.mcp.json`（MCP stdio server，
  暴露 `sro_preview/sro_read/sro_card/sro_raw/sro_decide/sro_trace/
  sro_preflight/sro_usage` 8 个工具）；
- 合并写入 `/path/to/your/project/.claude/settings.local.json`
  （逐事件 PreToolUse/PostToolUse hook；auto 模式仅可能转向符合条件的无界
  Read 或单文件 cat，大输出提示使用 additionalContext，不替换原输出）；
- 如果 workspace 还没有 `CLAUDE.md`，写入 SRO 使用协议模板。

安装后重启 Claude Code（或新开会话）。验证：

```bash
cd /path/to/your/project
claude "请自动使用 SparseRead 阅读长报告并回答问题"
```

模型和凭据由 Claude Code 用户自行管理。当前有限 DeepSeek 测试经临时协议转换，
不是原生 Anthropic 后端资格或性能结论。MCP 工具授权与宿主原生 Read 的逐文件
授权是不同合同；集合工具调用可读取目标目录中的多个文件。

Windows 注意：同事在 Windows 11 上曾遇到 MCP stdio/SSE 连接问题；本仓库
未在 Windows 上复验，发布前需要在目标机器上单独验证 `.mcp.json` 连接。

## 同时安装多个框架

如果两个 CLI 都已经安装：

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform both \
  --opencode-workspace /path/to/your/project \
  --doctor
```

如需关闭拦截、只让模型自然选择 SparseRead：

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform both \
  --opencode-workspace /path/to/your/project \
  --sparseread-mode advisory \
  --doctor
```

`--platform both` 目前等价于 OpenCode + OpenClaw。Claude Code 需要单独再执行
一次 `--platform claude`；NanoBot 走 Python 依赖安装，与 CLI 安装互不影响。

## 框架行为与权限边界

不同适配器的 hook、权限、会话和回退机制不同；请以各自 README 和
[验证矩阵](framework_upgrade_20261114/validation-summary.md)为准。Claude 的
advisory 不拦截原生读取，OpenCode V2 对集合逐源检查宿主权限，Codex 的项目
信任与 hook 信任分开。原生读取、显式验证和适用时的回退仍可用。

## Doctor 检查

只检查本机命令和 bridge，不改框架配置：

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py --platform opencode --doctor-only
uv run --no-project --python 3.12 python scripts/install_sparseread.py --platform openclaw --doctor-only
uv run --no-project --python 3.12 python scripts/install_sparseread.py --platform claude --doctor-only
```

Windows PowerShell：

```powershell
uv run --no-project --python 3.12 python scripts/install_sparseread.py --platform opencode --doctor-only
uv run --no-project --python 3.12 python scripts/install_sparseread.py --platform openclaw --doctor-only
uv run --no-project --python 3.12 python scripts/install_sparseread.py --platform claude --doctor-only
```

doctor 检查范围因框架不同；其结果不能自动证明真实模型激活或宿主权限已批准：

- bridge smoke：先校验 bridge protocol `1.0`，再用临时 markdown fixture 验证 `sro_preview` 能返回 FileCard 和 L0 预览；
- 已安装集成检查：
  - OpenCode 根据 V1/V2 验证对应入口、配置和受管 runtime；V2 doctor 使用隔离宿主与确定性 provider 测试 preview；
  - OpenClaw 验证 `plugins inspect --runtime --json` 中的 SparseRead 工具面；默认 `auto` 下还会检查拦截 hook 已注册，`advisory` 下会检查没有 native tool 拦截 hook。
  - Claude Code 验证 `sparseread_claude.bridge` 的 protocol smoke（与
    OpenCode/OpenClaw 同一套 bridge 校验），并检查受管 Python runtime 存在。

## 日常使用建议

用户不需要手动调用 `sro_preview`、`sro_read` 或填写 `HintSpec`。正确用法是在任务里告诉 agent 自动使用 SparseRead，例如：

```text
请自动使用 SparseRead 阅读这个大文件/证据包，只提取完成任务所需的证据；证据足够后直接写结果，不要反复全文读取。
```

适合明确要求 agent 使用 SparseRead 的场景：

- 大文件、长 markdown、PDF、长日志；
- 多文件证据包、审计材料、诊断材料；
- 问题本身只需要文件中的少量证据，而不是完整重算或逐行处理。

通常不需要特别要求 SparseRead 的场景：

- 小文件、脚本、配置改动；
- 全表计算、精确逐行统计、需要运行代码得到答案的任务；
- 你已经知道要改哪几行代码的普通开发任务。

agent 内部会按生产协议工作：先做 L0 preview；如果 preview 不够，再围绕明确问题读取 EvidencePack；证据已经 ready 时直接写交付物；只有明确需要原文时才回溯 raw 内容。用户只需要描述任务和目标，不需要自己组织这些工具调用。

不要把 SparseRead 当成“所有内容都压缩”的代理。它的优势是让 agent 少读无关材料，并在需要时用可回溯的 evidence pack 补证据。

## 快速体验测试

完整 git checkout 提供了一个长 markdown fixture；源码安装归档不包含此 fixture：

```text
tests/fixtures/quick_test/incident-report.md
```

OpenCode 安装后，推荐直接在本仓库根目录运行：

```bash
cd /absolute/path/to/SparseReading
opencode run "请自动使用 SparseRead 阅读 tests/fixtures/quick_test/incident-report.md，只提取必要证据，并回答 ROOT_CAUSE、MITIGATION_OWNER、FINAL_DEADLINE 分别是什么。不要让我手动调用工具。"
```

如果你已经在别的 workspace 里工作，先把 `tests/fixtures/quick_test/incident-report.md` 复制进去再测。OpenClaw、Claude Code 或 nanobot 会话中发送同类自然语言请求即可。Claude Code 的快速体验：

```bash
cd /path/to/your/project
claude "请自动使用 SparseRead 阅读 tests/fixtures/quick_test/incident-report.md，只提取必要证据，并回答 ROOT_CAUSE、MITIGATION_OWNER、FINAL_DEADLINE 分别是什么。"
```

预期答案应包含：

```text
ROOT_CAUSE: cache invalidation used customer_id instead of tenant_id.
MITIGATION_OWNER: Mira Chen, Data Platform on-call.
FINAL_DEADLINE: 2026-07-18 09:30 UTC.
```

## 版本发布前固定测试

在完整 git checkout 中，每次版本更新至少跑（源码安装归档不包含 tests）：

```bash
PYTHONPATH="packages/sparseread-core/src:integrations/nanobot/python/src:integrations/opencode/python/src:integrations/openclaw/python/src:integrations/claude/python/src" \
  uv run --project . --extra test pytest tests/test_release_fixtures.py -q
```

这 6 个 fixture 覆盖：

1. 长 markdown key-value 字段；
2. 日志 level preview 和 raw selector；
3. CSV schema/sample/signals；
4. JSON schema/sample/signals；
5. YAML schema/sample/signals；
6. XML root/schema/sample preview。

每个 fixture 都会同时经过 `OpenCodeBridge` 和 `OpenClawBridge`，所以它检查的
不只是 reader，也包括两个框架 bridge 的 core 功能一致性。四个框架的
发行边界由 `test_release_package_boundaries.py` 覆盖：core 无框架导入，
每个 adapter 独立发行且只依赖 core。

## Benchmark 兼容

历史 benchmark 和旧脚本可能还统计 `sro_card -> sro_read`。这条路径保留，并可通过 `SPARSEREAD_MODE=bench_protocol` 或 `SparseReadConfig(mode="bench_protocol")` 使用。

生产安装默认是 `--sparseread-mode auto`；OpenCode V2 全局初次安装默认 advisory。用户侧用自然语言要求 agent 自动使用 SparseRead；框架内部仍以 `sro_preview` 作为第一入口。需要只提示不拦截时，安装时改用 `--sparseread-mode advisory`。
OpenCode benchmark runner 里的 `plugin_auto` 才对应这个生产安装形态；`plugin_nudge` 和 `plugin_replace_truncation_experimental` 只是兼容/调试对照行，不是用户安装后的默认模式。
