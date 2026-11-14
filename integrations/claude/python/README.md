# sparseread-claude

Claude Code adapter for SparseRead: JSONL bridge, eight-tool MCP stdio server,
per-event hooks and token tracker, backed by the framework-neutral
`sparseread-core` runtime.

```bash
python -m sparseread_claude.bridge --workspace .
python -m sparseread_claude.claude_mcp --workspace . --mode auto
python -m sparseread_claude.hook --single --workspace . --mode auto
```

Install via `scripts/install_sparseread.py --platform claude`; use
`--sparseread-mode advisory` to avoid hook interception. See
`integrations/claude/README.md` for path, permission, one-time state, shell and
platform boundaries.
