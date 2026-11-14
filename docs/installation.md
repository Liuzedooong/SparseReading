# SparseRead installation

This guide describes the current single-repository source installation. The
repository ships one framework-neutral core and one adapter per supported agent
framework. It does not require a framework checkout at runtime.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- A current patched Node.js 22 or newer for OpenCode/OpenClaw/Codex/Pi; npm for OpenCode/OpenClaw builds
- An installed OpenCode, OpenClaw, Claude Code, NanoBot, Codex, or Pi host

The commands below are for macOS; Windows behavior is not qualified for this release.

The installer validates Python before changing a workspace. The `uv run` form
below supplies a compatible interpreter; when invoking the script directly,
pass `--python /path/to/python3.12` if the default `python3` is older than 3.11.
PDF/XLSX reader dependencies are installed by default; use
`--reader-extras none` for a text-only runtime.

## Download the v0.1.4 installer

```bash
curl -fLO https://github.com/Liuzedooong/SparseReading/releases/download/v0.1.4/sparseread-source-installer-v0.1.4.zip &&
curl -fLO https://github.com/Liuzedooong/SparseReading/releases/download/v0.1.4/SHA256SUMS &&
grep '  sparseread-source-installer-v0.1.4.zip$' SHA256SUMS | shasum -a 256 -c - &&
unzip -q sparseread-source-installer-v0.1.4.zip &&
cd sparseread-v0.1.4
```

The checksum command above is for macOS. The source installer archive omits tests and benchmarks; a full Git checkout is only needed to run the repository test suite. PyPI project registration is pending.

## Install an adapter

Codex or Pi (project-scoped):

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform codex --workspace /path/to/your/project --doctor
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform pi --workspace /path/to/your/project --doctor
```

Restart/reload in the project and review its trust prompt. Codex hook trust is
separate from plugin installation; Pi project extensions also require approval.
Use `--sparseread-mode advisory` for non-blocking guidance. Read the
[Codex/Pi design and recovery notes](codex-pi-adapters.md) for tested host versions,
cache-safe reinstalls, native fallback, and source-package limitations.

OpenCode:

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform opencode \
  --opencode-workspace /path/to/your/project \
  --doctor
```

The installer detects OpenCode major version and selects the matching V1 or V2
entry. Host-level scripted checks cover 1.17.14, 1.19.5, and 2.3.0 on macOS;
other versions and operating systems need separate validation. V2 `--doctor`
starts an isolated local host and deterministic provider to exercise a synthetic
preview. This validates host registration and invocation, not real-model task
quality or performance. Remote workspaces are not supported by the local bridge.

OpenClaw:

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform openclaw \
  --doctor
```

Claude Code:

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform claude \
  --claude-workspace /path/to/your/project \
  --doctor
```

Pi 0.87.1 and OpenClaw 2026.7.1-2 were exercised from the `05768c8` source
archive on macOS using their actual SDK or CLI. These are fixed-version
regressions, not claims of latest-version upgrades.

NanoBot uses ordinary Python packages:

```bash
uv pip install \
  packages/sparseread-core \
  integrations/nanobot/python
```

The official `nanobot-ai==0.4.1` host and the current adapter have been
validated on macOS arm64 for the scenarios in the validation matrix. Install
the optional `nanobot` extra or the pinned host separately, then call
`sparseread_nanobot.install(agent)` before the AgentLoop starts. Each persistent
turn must first select the stock `read_file` to establish the reader policy;
a bounded read qualifies. Shell calls remain native. Other NanoBot versions and
Windows are not qualified by these tests.

## Modes

The default `auto` mode routes high-confidence sparse-reading tasks through
SparseRead while leaving small or computation-heavy tasks native. Use
`advisory` when you want the tools and model guidance without intercepting
native reads.

Users normally do not call `sro_preview` or `sro_read` manually. Ask the agent
to use SparseRead for a large artifact and let the selected adapter expose the
protocol.

## Platform notes

- OpenCode uses a workspace plugin plus a managed Python bridge.
- OpenClaw uses a packed npm plugin plus a managed Python bridge.
- Claude Code uses an MCP stdio server, `PreToolUse`/`PostToolUse` hooks, and a
  generated `CLAUDE.md` when the workspace does not already have one. The
  advisory mode does not block native reads; MCP and native Read use separate
  host permissions. See `integrations/claude/README.md` for workspace, shell,
  collection and platform limits.
- NanoBot uses `sparseread-core` and `sparseread-nanobot` as Python dependencies.

For validated host versions and evidence boundaries, see the
[validation matrix](framework_upgrade_20261114/validation-summary.md).

For architecture and package ownership, see
[`docs/release_architecture.md`](release_architecture.md). For the Chinese
installation guide and the detailed Windows matrix, see
[`docs/sparseread_installation.md`](sparseread_installation.md).
