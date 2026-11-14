# SparseRead for Claude Code

The adapter uses the framework-neutral SparseRead core, an MCP stdio server
with eight tools, and per-event `PreToolUse`/`PostToolUse` command hooks. It
creates project-local `.mcp.json` and `.claude/settings.local.json` entries;
`CLAUDE.md` guidance is created only when absent.

## Install

```bash
uv run --project . python scripts/install_sparseread.py --platform claude \
  --claude-workspace /path/to/your/project --sparseread-mode auto --doctor
```

Use `--sparseread-mode advisory` for suggestions without SparseRead blocking
native reads. Reinstallation replaces this adapter's hook entries and updates
the MCP mode while preserving other hooks. The installer builds the core and
adapter wheels into a managed runtime under `~/.sparseread/claude`. Doctor
checks the bridge transport; host activation and tool permissions require
separate validation in Claude Code.

## Behavior and limits

- In auto mode, an eligible unbounded `Read` or plain single-file `cat` can be
  redirected once per workspace, session and source version. A retry remains
  subject to normal Claude Code permissions. Missing session identity or an
  unavailable/corrupt state file fails open. State is bounded and expires.
- Bounded reads, searches, pipelines, compound shell syntax and unknown commands
  retain native behavior. PostToolUse can provide a short `additionalContext`
  suggestion after a large read without replacing the original output.
- MCP paths are restricted to the configured workspace, with source manifests
  used for preview/read/card/decide/raw. Unsafe collection symlinks and source
  changes fail closed for the MCP call; use native tools where appropriate.
  Claude's approval of an MCP tool call covers that tool call: it is not the
  built-in Read tool's per-file approval mechanism. Collection calls can read
  multiple files inside the approved target.
- `sro_preflight` only considers top-level regular files in the workspace; use
  explicit `sro_preview` for other permitted files or directories. Raw ranges
  use zero-based Unicode character offsets with exclusive end; stale references
  return MCP errors and need a new preview.
- PowerShell and Windows hook behavior are not verified in this batch; shell
  interception must not be assumed there. MCP/Read support on any platform is
  limited to the hosts and modes actually tested.
