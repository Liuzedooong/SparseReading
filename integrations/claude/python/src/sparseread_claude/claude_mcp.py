"""SparseRead MCP server for Claude Code.

Exposes SRO tools over the MCP stdio transport.  The server wraps the shared
core runtime through ``ClaudeBridge``; tool descriptions double as Claude Code
guidance, and ``sro_preview`` accepts an optional ``episode_hint`` so the
shared GateContext/episode path works the same way it does on the other
framework adapters.

Usage:
  python -m sparseread_claude.claude_mcp --workspace .
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool

from sparseread_claude.bridge import ClaudeBridge
from sparseread_claude.token_tracker import TokenTracker


def _path_value(target: Any) -> str:
    if isinstance(target, dict):
        return str(target.get("path") or target.get("artifact_id") or "")
    return str(target or "")


SRO_PREVIEW_TOOL = Tool(
    name="sro_preview",
    description=(
        "⚠️ PRIMARY SparseRead ENTRYPOINT for large files, PDFs, and directories. "
        "Consider for targeted evidence when the target is: "
        "(1) a PDF file of any size, "
        "(2) a text/markdown/log file larger than ~12KB, "
        "(3) a directory with 3+ files, "
        "(4) a CSV/JSON/structured data file over ~8KB. "
        "Returns a compact preview with structure overview, content samples, "
        "key signals, a raw_ref for full-content fallback, and next_action "
        "guidance. For multi-file audit or structured-compute episodes, pass "
        "episode_hint {goal, relation, coverage, summary} on the FIRST preview "
        "so the Gate can route the whole episode consistently."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path or absolute path inside the configured workspace."},
            "artifact_id": {
                "type": "string",
                "description": "Existing artifact id for follow-up previews.",
            },
            "episode_hint": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "enum": [
                            "selective_read",
                            "cross_file_evidence",
                            "structured_compute",
                            "edit_or_execute",
                            "full_fidelity",
                            "unknown",
                        ],
                    },
                    "relation": {
                        "type": "string",
                        "enum": ["new", "continue", "switch", "unknown"],
                    },
                    "coverage": {
                        "type": "string",
                        "enum": ["selective", "exhaustive", "unknown"],
                    },
                    "summary": {"type": "string"},
                },
            },
        },
    },
)


SRO_READ_TOOL = Tool(
    name="sro_read",
    description=(
        "TARGETED sparse evidence extraction AFTER sro_preview. "
        "Modes: scout/focus/collect/refine/verify. "
        "The hint MUST contain a 'goal'; use 'slots' or 'needles' for collect. "
        "A ready digest can support the answer; verification and native fallback "
        "remain available when necessary."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "target": {
                "type": "object",
                "description": '{"artifact_id": "<id>"} or {"path": "<path>"}.',
            },
            "mode": {
                "type": "string",
                "enum": ["scout", "focus", "collect", "refine", "verify"],
            },
            "hint": {
                "type": "object",
                "description": "HintSpec with goal, needles, slots, want, scope, type_hint.",
            },
            "episode_hint": {
                "type": "object",
                "description": "Optional episode boundary hint (goal/relation/coverage/summary).",
            },
        },
        "required": ["target", "mode", "hint"],
    },
)


SRO_CARD_TOOL = Tool(
    name="sro_card",
    description=(
        "COMPATIBILITY/DEBUG: Return a SparseRead FileCard with metadata and "
        "gate decision. Production flows should use sro_preview."
    ),
    inputSchema={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
)


SRO_RAW_TOOL = Tool(
    name="sro_raw",
    description=(
        "FALLBACK: Retrieve original content behind a raw_ref. Use ONLY when "
        "preview/targeted reads are insufficient."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "raw_ref": {"type": "string"},
            "range": {"type": "object", "description": "Zero-based Unicode character offsets {start, end}; end is exclusive. Default returns at most 50000 characters; check truncated."},
            "selector": {"type": "string", "description": "Case-insensitive line selector."},
        },
        "required": ["raw_ref"],
    },
)


SRO_DECIDE_TOOL = Tool(
    name="sro_decide",
    description=(
        "DIAGNOSTIC: Inspect a path and return the SparseRead gate decision "
        "plus the Claude adapter profile (enforce/advisory/native)."
    ),
    inputSchema={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
)


SRO_TRACE_TOOL = Tool(
    name="sro_trace",
    description=(
        "Return the SparseRead session trace: preview/read/card/decide events, "
        "native tool events, gate decisions, and usage stats."
    ),
    inputSchema={"type": "object", "properties": {}},
)


SRO_PREFLIGHT_TOOL = Tool(
    name="sro_preflight",
    description=(
        "Inspect top-level regular files in the workspace and return high-confidence "
        "evidence targets. Directories are not scanned by this preflight."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "max_candidates": {"type": "integer", "description": "1-64, default 24."},
            "max_results": {"type": "integer", "description": "1-5, default 3."},
        },
    },
)


SRO_USAGE_TOOL = Tool(
    name="sro_usage",
    description=(
        "Return SparseRead token consumption metrics: full-file vs SR response "
        "tokens, session savings, and top savings by artifact."
    ),
    inputSchema={"type": "object", "properties": {}},
)


ALL_TOOLS = [
    SRO_PREVIEW_TOOL,
    SRO_READ_TOOL,
    SRO_CARD_TOOL,
    SRO_RAW_TOOL,
    SRO_DECIDE_TOOL,
    SRO_TRACE_TOOL,
    SRO_PREFLIGHT_TOOL,
    SRO_USAGE_TOOL,
]


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return str(value)


def _slim_for_model(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Trim heavy envelope fields from tool responses the model will read.

    The shared bridge attaches decision/gate/episode objects to preview/read
    results for plugin plumbing.  On Claude Code those fields are available
    through sro_decide/sro_trace, so returning compact summaries keeps the
    model's context small (matching the colleague report's file-read metrics).
    """
    if tool_name not in {"sro_preview", "sro_read", "sro_card"}:
        return result
    slim = dict(result)
    decision = slim.get("decision")
    if isinstance(decision, dict):
        slim["decision"] = {
            key: decision.get(key)
            for key in ("mode", "action", "reason", "code", "preview_recommended", "scope_kind")
        }
    episode = slim.get("episode")
    if isinstance(episode, dict):
        slim["episode"] = {
            key: episode.get(key)
            for key in (
                "episode_id",
                "conversation_id",
                "scope",
                "goal",
                "status",
                "mode",
                "decision_code",
            )
        }
    if tool_name == "sro_preview":
        slim.pop("claude_gate", None)
    return slim


class SparseReadClaudeMCP:
    """MCP wrapper around the shared ClaudeBridge runtime."""

    def __init__(self, workspace: str, mode: str = "auto") -> None:
        self.workspace = str(Path(workspace).expanduser().resolve())
        if not Path(self.workspace).is_dir():
            raise ValueError("workspace must be an existing directory")
        self.mode = mode
        self.bridge = ClaudeBridge(workspace=self.workspace, mode=mode)
        self.tracker = TokenTracker(enable_log=os_env_flag("SRO_TOKEN_LOG", "1"))

    def handle(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request: dict[str, Any] = {"method": method, "params": params or {}}
        return self.bridge.handle(request)

    def _path(self, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("path must be a non-empty string")
        root = Path(self.workspace)
        path = Path(value).expanduser()
        resolved = (path if path.is_absolute() else root / path).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("SparseRead target is outside the configured workspace; use native tools")
        return str(resolved)

    def _bound_params(self, method: str, arguments: dict[str, Any]) -> dict[str, Any]:
        params = dict(arguments)
        if method in {"preview", "card", "read", "decide"}:
            if params.get("path"):
                params["path"] = self._path(params["path"])
            if isinstance(params.get("target"), dict) and params["target"].get("path"):
                params["target"] = {**params["target"], "path": self._path(params["target"]["path"])}
            target = params.get("target")
            if target is None:
                target = {"artifact_id": params["artifact_id"]} if params.get("artifact_id") else {"path": params.get("path")}
            manifest = self.handle("source_manifest", {"target": target})
        elif method == "raw":
            try:
                manifest = self.handle("source_manifest", {"raw_ref": params.get("raw_ref")})
            except ValueError as exc:
                raise ValueError("unknown or stale raw_ref; call sro_preview again or use native reading") from exc
        else:
            return params
        self._path(manifest["root"])
        for item in manifest["paths"]:
            self._path(item["path"])
            self._path(item["canonical_path"])
        params["manifest_token"] = manifest["manifest_token"]
        return params

    def _preflight(self, arguments: dict[str, Any]) -> dict[str, Any]:
        requested = arguments.get("workspace")
        if requested and requested != self.workspace:
            raise ValueError("preflight is limited to the configured workspace")
        limit = min(64, max(1, int(arguments.get("max_candidates", 24))))
        maximum = min(5, max(1, int(arguments.get("max_results", 3))))
        handoffs = []
        for candidate in sorted(Path(self.workspace).iterdir(), key=lambda item: item.name.lower())[:limit]:
            if candidate.name.startswith(".") or candidate.is_symlink() or not candidate.is_file():
                continue
            params = self._bound_params("decide", {"path": str(candidate)})
            result = self.handle("decide", params)
            gate = result.get("claude_gate") or {}
            if gate.get("mode") == "enforce":
                handoffs.append({"path": str(candidate), "relative_path": candidate.name,
                                 "type": result.get("type"), "reason": gate.get("reason"),
                                 "decision_mode": result.get("decision", {}).get("mode"),
                                 "gate_mode": gate.get("mode"), "trajectory": gate.get("trajectory")})
                if len(handoffs) >= maximum:
                    break
        result = {"workspace": self.workspace, "handoffs": handoffs, "handoff_count": len(handoffs),
                  "scope": "top-level regular files"}
        if handoffs:
            result["first_action"] = {"tool": "sro_preview", "path": handoffs[0]["relative_path"]}
        self.bridge._record("sro_preflight", {"workspace": self.workspace}, result)
        return result

    def handle_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name == "sro_usage":
            try:
                return _safe_json(self.usage())
            except Exception as exc:
                return _safe_json({"error": str(exc)})
        method_map: dict[str, str] = {
            "sro_preview": "preview",
            "sro_read": "read",
            "sro_card": "card",
            "sro_raw": "raw",
            "sro_decide": "decide",
            "sro_trace": "trace",
            "sro_preflight": "preflight",
        }
        method = method_map.get(tool_name)
        if method is None:
            return _safe_json({"error": f"unknown tool: {tool_name}"})
        try:
            result = self._preflight(arguments) if method == "preflight" else self.handle(method, self._bound_params(method, arguments))
            result = _slim_for_model(tool_name, result)
            self._record_usage(tool_name, arguments, result)
            return _safe_json(result)
        except Exception as exc:
            return _safe_json({"error": str(exc)})

    def _record_usage(
        self, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]
    ) -> None:
        if tool_name not in {"sro_preview", "sro_read", "sro_card", "sro_raw"}:
            return
        path = _path_value(arguments.get("target") or arguments.get("path"))
        if not path:
            return
        response_json = json.dumps(result, ensure_ascii=False, default=str)
        size = 0
        try:
            size = Path(path).stat().st_size
        except OSError:
            pass
        if tool_name == "sro_preview":
            self.tracker.record_preview(path, size, Path(path).suffix, response_json)
        elif tool_name == "sro_read":
            self.tracker.record_read(
                path, size, Path(path).suffix, response_json, mode=str(arguments.get("mode", ""))
            )
        elif tool_name == "sro_card":
            self.tracker.record_card(path, size, Path(path).suffix, response_json)
        else:
            self.tracker.record_raw(path, size, Path(path).suffix, response_json)

    def usage(self) -> dict[str, Any]:
        return {
            "token_tracker": self.tracker.to_dict(),
            "trace": self.handle("trace"),
        }


def os_env_flag(name: str, default: str) -> bool:
    import os

    return (os.environ.get(name) or default) != "0"


def build_server(sr_mcp: SparseReadClaudeMCP) -> Server:
    server = Server("sparseread")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return ALL_TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        result_text = sr_mcp.handle_tool(name, arguments or {})
        result = json.loads(result_text)
        is_error = bool(result.get("error")) or any(
            isinstance(result.get(key), dict) and bool(result[key].get("error"))
            for key in ("raw", "preview_pack", "evidence_pack")
        )
        return CallToolResult(content=[TextContent(type="text", text=result_text)], isError=is_error)

    return server


async def run_mcp_server(workspace: str, mode: str) -> None:
    sr_mcp = SparseReadClaudeMCP(workspace=workspace, mode=mode)
    mcp_server = build_server(sr_mcp)
    async with stdio_server() as (read_stream, write_stream):
        await mcp_server.run(
            read_stream,
            write_stream,
            mcp_server.create_initialization_options(),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SparseRead MCP Server for Claude Code")
    parser.add_argument("--workspace", default=".")
    parser.add_argument(
        "--mode",
        default="auto",
        choices=[
            "auto",
            "bench_protocol",
            "force",
            "force_sro",
            "native",
            "advisory",
            "observe",
            "nudge",
            "enforce",
        ],
    )
    args = parser.parse_args(argv)
    workspace = str(Path(args.workspace).resolve())
    print(
        f"[sparseread] Starting MCP server — workspace: {workspace}, mode: {args.mode}",
        file=sys.stderr,
    )
    try:
        asyncio.run(run_mcp_server(workspace, args.mode))
    except KeyboardInterrupt:
        print("[sparseread] MCP server stopped.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
