# SparseRead installation

This guide describes the current single-repository source installation. The
repository ships one framework-neutral core and one adapter per supported agent
framework. It does not require a framework checkout at runtime.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- A current patched Node.js 22 or newer for OpenCode/OpenClaw/Codex/Pi; npm for OpenCode/OpenClaw builds
- Git
- An installed OpenCode, OpenClaw, Claude Code, NanoBot, Codex, or Pi host

Windows users should use PowerShell. The installer resolves `.cmd`, `.exe`, and
`.bat` host commands automatically.

The installer validates Python before changing a workspace. The `uv run` form
below supplies a compatible interpreter; when invoking the script directly,
pass `--python /path/to/python3.12` if the default `python3` is older than 3.11.
PDF/XLSX reader dependencies are installed by default; use
`--reader-extras none` for a text-only runtime.

## Verify a checkout

The following tests require a full git checkout; the source installer archive
intentionally omits tests and benchmark fixtures.

```bash
git clone https://github.com/Liuzedooong/SparseReading.git
cd SparseReading

PYTHONPATH="packages/sparseread-core/src:integrations/nanobot/python/src:integrations/opencode/python/src:integrations/openclaw/python/src:integrations/claude/python/src" \
  uv run --project . --extra test pytest tests/test_release_fixtures.py -q
```

For a full local regression:

```bash
PYTHONPATH="packages/sparseread-core/src:integrations/nanobot/python/src:integrations/opencode/python/src:integrations/openclaw/python/src:integrations/claude/python/src" \
  uv run --project . --extra test pytest -q
```

On PowerShell, replace the `:` separators in `PYTHONPATH` with `;`.

## Install an adapter

Codex or Pi (project-scoped):

Use a checkout containing the desired adapter changes. The historical
[`v0.1.3` tagged source archive](https://github.com/Liuzedooong/SparseReading/archive/refs/tags/v0.1.3.zip)
includes the earlier Codex/Pi adapters but not this upgrade; original release
attachments were not migrated. No new release has been published in this batch.

```bash
uv run --python 3.12 python scripts/install_sparseread.py \
  --platform codex --workspace /path/to/your/project --doctor
uv run --python 3.12 python scripts/install_sparseread.py \
  --platform pi --workspace /path/to/your/project --doctor
```

Restart/reload in the project and review its trust prompt. Codex hook trust is
separate from plugin installation; Pi project extensions also require approval.
Use `--sparseread-mode advisory` for non-blocking guidance. Read the
[Codex/Pi design and recovery notes](codex-pi-adapters.md) for tested host versions,
cache-safe reinstalls, native fallback, and source-package limitations.

OpenCode:

```bash
uv run --project . python scripts/install_sparseread.py \
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
uv run --project . python scripts/install_sparseread.py \
  --platform openclaw \
  --doctor
```

Claude Code:

```bash
uv run --project . python scripts/install_sparseread.py \
  --platform claude \
  --claude-workspace /path/to/your/project \
  --doctor
```

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

For current candidate host versions and evidence boundaries, see the
[validation matrix](framework_upgrade_20261114/validation-summary.md).

For architecture and package ownership, see
[`docs/release_architecture.md`](release_architecture.md). For the Chinese
installation guide and the detailed Windows matrix, see
[`docs/sparseread_installation.md`](sparseread_installation.md).
