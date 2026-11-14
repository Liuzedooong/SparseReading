# SparseRead

<div align="center">

**Token-efficient reading for AI agents**

SparseRead is a training-free reading layer for Claude Code, OpenCode, Codex,
NanoBot, OpenClaw, and Pi. Agents can pull just the evidence they need from
long files, PDFs, logs, and spreadsheets, with source references and access
to the original text when needed.

[![CI](https://github.com/Liuzedooong/SparseReading/actions/workflows/ci.yml/badge.svg)](https://github.com/Liuzedooong/SparseReading/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[Install](#install) · [Supported versions](#supported-versions) · [Paper](https://arxiv.org/abs/2608.22237) · [Site](https://sparseread.pages.dev/) · [中文](README.zh-CN.md)

</div>

## 🔥 News

- **2026-11-14 · [v0.1.4](https://github.com/Liuzedooong/SparseReading/releases/tag/v0.1.4) update** — Validated the latest versions of four hosts on macOS arm64: OpenCode **2.3.0**, Claude Code **2.1.325**, Codex CLI **0.169.0**, and NanoBot **0.4.1**. OpenCode V2 adds per-user installation with advisory mode first and a one-time auto-mode suggestion once 48 hours have elapsed since the first successful evidence read.
- **2026-09-28:** [v0.1.3](https://github.com/Liuzedooong/SparseReading/releases/tag/v0.1.3) fixes a large-workspace timeout when switching to full-fidelity native reading in Codex/Pi.
- **2026-09-28:** Added Codex and Pi support in [v0.1.2](https://github.com/Liuzedooong/SparseReading/releases/tag/v0.1.2).
- **2026-09-14:** Support for Claude Code, OpenCode, OpenClaw, and NanoBot.

## Supported versions

| Framework | Verified host versions | Setup |
|---|---|---|
| OpenCode | **2.3.0** · V1 1.19.5 and 1.17.14 | [Project or per-user installation](docs/installation.md#global-opencode-v2-install) |
| Claude Code | **2.1.325** | [MCP and hooks](integrations/claude/README.md) |
| Codex CLI | **0.169.0** | [Project plugin and MCP](docs/installation.md#install-an-adapter) |
| NanoBot | **0.4.1** | [Python adapter and AgentLoop](integrations/nanobot/python/README.md) |
| OpenClaw | 2026.7.1-2 | [Profile plugin](integrations/openclaw/README.md) |
| Pi | 0.87.1 | [Project extension](docs/installation.md#install-an-adapter) |

These are the exact versions exercised on macOS arm64. OpenClaw and Pi are
fixed-version regression checks. The [host validation matrix](docs/framework_upgrade_20261114/validation-summary.md)
covers permissions, model workflows, and platform scope.

## Install

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), and your agent CLI.
OpenCode, OpenClaw, Codex, and Pi also require Node.js 22 or newer.
The download check below uses the macOS checksum tool.

Start in a fresh directory. [Download the updated v0.1.4 installer ZIP](https://github.com/Liuzedooong/SparseReading/releases/download/v0.1.4/sparseread-source-installer-v0.1.4-20261114.zip).

```bash
curl -fLO https://github.com/Liuzedooong/SparseReading/releases/download/v0.1.4/sparseread-source-installer-v0.1.4-20261114.zip &&
curl -fLO https://github.com/Liuzedooong/SparseReading/releases/download/v0.1.4/SHA256SUMS-20261114 &&
grep '  sparseread-source-installer-v0.1.4-20261114.zip$' SHA256SUMS-20261114 | shasum -a 256 -c - &&
unzip -q sparseread-source-installer-v0.1.4-20261114.zip &&
cd sparseread-v0.1.4
```

### OpenCode V2, all local projects

From the extracted directory, install once for your user account:

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform opencode --global --doctor
```

Restart OpenCode and ask, “Use SparseRead to find the root cause in this report
and cite the relevant passages.” Fresh global installs use `advisory` mode,
so native reads still work as usual. Once 48 hours have elapsed since the first
successful evidence read, the next such read shows a one-time terminal
suggestion. To use `auto`, rerun the installer with `--sparseread-mode auto`
and restart. A reinstall without a mode flag keeps your choice.

See the [installation guide](docs/installation.md#install-an-adapter) for
OpenCode project installs and commands for Claude Code, Codex, NanoBot, OpenClaw, and Pi.

### Quick test

A full git checkout includes a small long-document fixture; the source installer archive does not:

```bash
opencode run "Use SparseRead to inspect tests/fixtures/quick_test/incident-report.md and report ROOT_CAUSE, MITIGATION_OWNER, and FINAL_DEADLINE."
```

Other adapters can expose the same request; see the validation matrix for
what has been exercised in v0.1.4.

## Results

<p align="center">
  <img src="assets/launch/sparseread-demo-wide.gif" alt="SparseRead replay: full read vs sparse evidence, then the cost-quality frontier" width="100%">
</p>

The current paper evaluation covers 125 tasks, five workload scenarios, and six
frontier models: Claude Opus 5, Qwen3.6-Plus, DeepSeek-V4-Flash,
DeepSeek-V4-Pro, GLM-5.1, and Kimi-K2.5.

| Headline | Reported result |
|---|---:|
| Maximum token reduction | **92.9%** |
| Maximum wall-time reduction | **89.0%** |
| Model–scenario cells with lower tokens and lower time | **30 / 30** |
| Cells preserving or improving task score | **26 / 30** |
| Sparse-fit cells preserving or improving task score | **22 / 24** |

The gain is not tied to one model: the evaluation includes strong reasoning
models as well as general-purpose frontier models, and the paper reports
benefits for all six models across the full matrix. See the
[paper](https://arxiv.org/abs/2608.22237) for definitions, baselines, and the
complete results.

### Cross-framework paper results

| Framework | Median token reduction | Median time saving |
|---|---:|---:|
| NanoBot | **69.0%** | **64.4%** |
| OpenCode | **71.8%** | **64.9%** |
| OpenClaw | **28.7%** | **28.2%** |

## How it works

- **Read Gate** — selects `auto`, `native`, or `advisory` behavior from artifact
  shape and task economics. Low-benefit computation and small-file work stays
  on native tools.
- **Reader Backends** — provide typed, bounded views for text/PDF, structured
  data, and multi-file collections.
- **EvidencePack** — returns compact evidence with source anchors, unresolved
  requirements, and a suggested next action.
- **Stateful protocol** — supports preview, targeted reading, refinement,
  verification, explicit raw fallback, and stopping.

The public production entrypoints are framework-facing tools; users normally
do not need to invoke them directly:

```text
sro_preview(path) -> bounded preview + FileCard
sro_read(target, mode, hint) -> EvidencePack
sro_raw(raw_ref) -> explicit raw fallback
```

## Repository layout

```text
packages/sparseread-core/       framework-neutral core and tests
integrations/<framework>/       NanoBot, OpenCode, OpenClaw, Claude Code adapters
scripts/install_sparseread.py   source installer and doctor
tests/                          release, bridge, gate, and installer tests
benchmarks/                     reproducibility runners and selected fixtures
docs/                           installation, architecture, and design notes
```

The core and adapters are intentionally separate. A framework adapter owns only
the host-specific bridge, lifecycle hooks, and installation surface; it does
not fork the reading protocol.

## Development

The following test commands require a full git checkout; installer archives omit tests and benchmarks.

Run the core suite independently:

```bash
uv run --project packages/sparseread-core --with pytest --with pytest-asyncio \
  pytest packages/sparseread-core/tests -q
```

Run the full release suite:

```bash
PYTHONPATH="packages/sparseread-core/src:integrations/nanobot/python/src:integrations/opencode/python/src:integrations/openclaw/python/src:integrations/claude/python/src" \
  uv run --project . --extra test --with 'nanobot-ai==0.4.1' pytest -q
```

Build the Python distributions and JavaScript plugins through the same CI path:

```bash
npm --prefix integrations/opencode/plugin ci
npm --prefix integrations/opencode/plugin run build
npm --prefix integrations/openclaw/plugin ci
npm --prefix integrations/openclaw/plugin run build
```

Benchmark runners and historical result files are kept for reproducibility;
they are not imported by any release package. See the
[release architecture](docs/release_architecture.md) before adding a new
integration.

## Release scope and limitations

- PyPI project registration is pending; npm and official framework-marketplace publishing are not currently distribution paths.
- Claude Code uses MCP and per-event hooks; its Windows and PowerShell
  paths have not been independently qualified in this batch.
- SparseRead is selective by design. Native access remains the right choice for
  small files, exact full-table computation, and other low-sparsity tasks.

## Contributing

Please read [CONTRIBUTING.md](https://github.com/Liuzedooong/SparseReading/blob/main/CONTRIBUTING.md) before opening a pull request.
Bug reports and focused integration feedback are welcome.

## Citation

```bibtex
@article{liu2026readless,
  title   = {Read Less, Solve More: Token-Efficient Sparse Reading for AI Agents},
  author  = {Liu, Zedong and Wu, Jiaan and Ma, Xinyang and Xu, Le and Wang, Kai and Hu, Yuanchao and Tao, Dingwen and Tan, Guangming},
  journal = {arXiv preprint arXiv:2608.22237},
  year    = {2026}
}
```

## License

SparseRead is released under the [MIT License](LICENSE).


## Repository migration

This is an independent continuation of the original source repository. It preserves Git commit history, branches and tags, but does not inherit the GitHub Fork relation, stars, issues, pull requests or release attachments.
