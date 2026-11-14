"""NanoBot 0.4.1 host bindings. Core remains independent of NanoBot."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from collections import OrderedDict
from contextvars import ContextVar, Token
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from nanobot.agent.hook import AgentHook
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import current_request_context
from nanobot.agent.tools.filesystem import ReadFileTool
from nanobot.runtime_context import RuntimeContextBlock
from sparseread import SparseRead
from sparseread.bridge.server import BridgePolicy, SparseReadBridgeServer
from sparseread.config import SparseReadConfig
from sparseread.core.policy import SparseCommandPolicy

from sparseread_nanobot.guidance import SRO_GUIDANCE
from sparseread_nanobot.hook import EXEC_TOOLS, WRITE_TOOLS, candidate_paths

_CALL_ID: ContextVar[str] = ContextVar("sparseread_nanobot_call_id", default="")


def _classify(_info: Any, decision: Any) -> dict[str, Any]:
    force = decision.mode == "force_sro"
    return {"mode": "enforce" if force else decision.mode,
            "block_native_read": force, "block_native_exec_dump": force,
            "nudge_native": decision.mode != "native", "reason": decision.reason,
            "trajectory": "sro_first" if force else "native"}


def _inside(root: Path, value: str | Path) -> Path:
    path = _lexical(root, value).resolve(strict=False)
    if not path.is_relative_to(root):
        raise ValueError("SparseRead source is outside the session workspace; use native tools")
    return path


def _lexical(root: Path, value: str | Path) -> Path:
    raw = Path(value).expanduser()
    # Resolving a symlink before '..' differs from lexical normalization.
    # Leave such requests to the native reader instead of changing identity.
    if ".." in raw.parts:
        raise ValueError("SparseRead does not normalize parent components; use native tools")
    path = Path(os.path.abspath(raw if raw.is_absolute() else root / raw))
    if not path.is_relative_to(root):
        raise ValueError("SparseRead source is outside the session workspace; use native tools")
    return path


@dataclass
class SessionRuntime:
    bridge: SparseReadBridgeServer
    lock: asyncio.Lock
    conversation: str
    workspace: Path
    policy: SparseCommandPolicy
    active: int = 0
    enabled_turns: set[str] = field(default_factory=set)
    native_readers: dict[str, ReadFileTool] = field(default_factory=dict)

    def context(self, request: Any) -> dict[str, str]:
        return {"conversation_id": self.conversation, "turn_id": str(request.turn_id or ""),
                "message_id": str(request.message_id or ""), "tool_call_id": _CALL_ID.get()}

    def manifest(self, source: dict[str, Any], context: dict[str, str]) -> str:
        if context["turn_id"] not in self.native_readers:
            raise ValueError("NanoBot read policy is not established in this turn; use read_file first")
        target = source.get("target")
        if isinstance(target, dict) and isinstance(target.get("path"), str):
            self.authorize(target["path"], context["turn_id"])
        result = self.bridge.handle({"method": "source_manifest", "params": {**source, "context": context}})
        if not result.get("complete") or not result.get("manifest_token") or not result.get("paths"):
            raise ValueError("incomplete source manifest; use native tools")
        for entry in result["paths"]:
            self.authorize(entry["path"], context["turn_id"])
            self.authorize(entry["canonical_path"], context["turn_id"])
        self.authorize(result["root"], context["turn_id"])
        return result["manifest_token"]

    def authorize(self, value: str | Path, turn_id: str) -> None:
        lexical = _lexical(self.workspace, value)
        source = _inside(self.workspace, lexical)
        native = self.native_readers.get(turn_id)
        # Only a stock reader actually selected by this turn is authoritative.
        if type(native) is not ReadFileTool:
            raise ValueError("NanoBot read policy is not established in this turn; use read_file first")
        resolved = Path(native._resolve_read(str(lexical))).resolve(strict=False)
        if resolved != source:
            raise ValueError("NanoBot native source resolution differs; use native tools")
        if source.is_file() and source.stat().st_size > native._MAX_FILE_SIZE_BYTES:
            raise ValueError("source exceeds NanoBot native read size limit")

    def call(self, method: str, args: dict[str, Any], request: Any) -> dict[str, Any]:
        params = dict(args)
        context = self.context(request)
        params["context"] = context
        if method in {"preview", "card", "read", "raw", "decide"}:
            target = params.get("target")
            if isinstance(target, str):
                target = {"path": target}
            if isinstance(target, dict) and isinstance(target.get("path"), str):
                target = {**target, "path": str(_lexical(self.workspace, target["path"]))}
                params["target"] = target
            if isinstance(params.get("path"), str):
                params["path"] = str(_lexical(self.workspace, params["path"]))
            if params.get("raw_ref"):
                source = {"raw_ref": params["raw_ref"]}
            elif target is not None:
                source = {"target": target}
            elif params.get("artifact_id"):
                source = {"target": {"artifact_id": params["artifact_id"]}}
            else:
                source = {"target": {"path": params.get("path")}}
            params["manifest_token"] = self.manifest(source, context)
        result = self.bridge.handle({"method": method, "params": params})
        for name in ("raw", "preview_pack", "evidence_pack"):
            value = result.get(name)
            if isinstance(value, dict) and value.get("error") and not value.get("sro_guard"):
                raise ValueError(str(value["error"]))
        return result


class RuntimeRegistry:
    def __init__(self, config: SparseReadConfig, tools: Any):
        self.config = config
        self.tools = tools
        self.sessions: OrderedDict[tuple[str, str, str], SessionRuntime] = OrderedDict()
        self.max_sessions = 128

    def get(self, request: Any) -> SessionRuntime:
        if request is None or not request.session_key or request.workspace is None:
            raise ValueError("NanoBot request has no session or workspace; use native tools")
        if not request.persist_session:
            raise ValueError("SparseRead is unavailable for ephemeral NanoBot turns; use native tools")
        generation = request.session_generation
        if not generation:
            raise ValueError("NanoBot request has no session generation; use native tools")
        root = Path(request.workspace).expanduser().resolve(strict=True)
        scope = getattr(request, "workspace_scope", None)
        if scope is not None:
            scope_root = Path(scope.project_path).expanduser().resolve(strict=True)
            if scope_root != root:
                raise ValueError("NanoBot workspace does not match its effective scope; use native tools")
            root = scope_root
        if not root.is_dir():
            raise ValueError("NanoBot workspace is not a directory")
        key = (str(root), str(request.session_key), str(generation))
        for old_key, old_runtime in list(self.sessions.items()):
            if old_key[:2] == key[:2] and old_key != key and old_runtime.active == 0:
                del self.sessions[old_key]
        if key not in self.sessions:
            if len(self.sessions) >= self.max_sessions:
                victim = next((item for item, runtime in self.sessions.items() if runtime.active == 0), None)
                if victim is None:
                    raise ValueError("SparseRead session limit reached; use native tools")
                del self.sessions[victim]
            config = replace(self.config, workspace=root)
            bridge = SparseReadBridgeServer(workspace=root, mode=config.mode, classifier=_classify,
                policy=BridgePolicy(platform="NanoBot", gate_key="nanobot_gate", ready_guard="nanobot_ready", guard_cards_after_ready=False))
            bridge.runtime = SparseRead(config)
            bridge.episodes = bridge.runtime.orchestrator.episodes
            conversation = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
            self.sessions[key] = SessionRuntime(bridge, asyncio.Lock(), conversation, root, SparseCommandPolicy(bridge.runtime.orchestrator))
        self.sessions.move_to_end(key)
        return self.sessions[key]

    def acquire(self, request: Any) -> SessionRuntime:
        runtime = self.get(request)
        runtime.active += 1
        return runtime

    def release(self, runtime: SessionRuntime) -> None:
        runtime.active = max(0, runtime.active - 1)


class NanoTool(Tool):
    """Official Tool interface; each execution resolves its own request runtime."""
    _sparseread_owned = True

    def __init__(self, registry: RuntimeRegistry, prototype: Any):
        self.registry = registry
        self.prototype = prototype

    @property
    def name(self) -> str:
        return self.prototype.name

    @property
    def description(self) -> str:
        if self.name == "sro_raw":
            return "Retrieve original content from raw_ref; range uses Unicode character offsets, end exclusive."
        return self.prototype.description

    @property
    def parameters(self) -> dict[str, Any]:
        return self.prototype.parameters

    @property
    def concurrency_safe(self) -> bool:
        return False

    def runtime_context_provider(self):
        if self.name == ("sro_card" if self.registry.config.mode == "bench_protocol" else "sro_preview"):
            return self._provide_context
        return None

    async def _provide_context(self, request: Any) -> RuntimeContextBlock | None:
        if self.registry.config.mode == "native" or not request.persist_session or not request.turn_id:
            return None
        try:
            runtime = self.registry.get(request)
        except (OSError, ValueError):
            return None
        runtime.enabled_turns.add(str(request.turn_id))
        return RuntimeContextBlock(source="sparseread", content=(
            "NanoBot: call the native read_file tool first in each turn to establish its access policy. "
            "For a broad source, it may return a SparseRead handoff; then use sro_preview and sro_read.\n\n" + SRO_GUIDANCE))

    async def execute(self, **kwargs: Any) -> Any:
        request = current_request_context()
        runtime = None
        try:
            runtime = self.registry.acquire(request)
            async with runtime.lock:
                if self.name == "sro_guard":
                    return str(kwargs.get("message", ""))
                if self.name == "sro_handoff":
                    target = _lexical(runtime.workspace, kwargs["path"])
                    runtime.authorize(target, str(request.turn_id or ""))
                    return f"SparseRead: call sro_preview with path {json.dumps(str(target), ensure_ascii=False)}, then use sro_read for targeted evidence. Native bounded reads remain available."
                result = runtime.call(self.name.removeprefix("sro_"), kwargs, request)
                return json.dumps(result, ensure_ascii=False)
        except Exception as error:
            return self.error(f"SparseRead could not access this source: {error}. Use native tools as appropriate.")
        finally:
            if runtime is not None:
                self.registry.release(runtime)


class InternalTool:
    def __init__(self, name: str, description: str, properties: dict[str, Any], required: list[str]):
        self.name, self.description = name, description
        self.parameters = {"type": "object", "properties": properties, "required": required}


class NanoHook(AgentHook):
    """Turn-local hook; successful callbacks are attributed to tool call IDs."""
    _sparseread_owned = True

    def __init__(self, registry: RuntimeRegistry, request: Any, runtime: SessionRuntime):
        super().__init__()
        self.registry = registry
        self.request = request
        self.runtime = runtime
        self.pending: dict[str, tuple[str, dict[str, Any]]] = {}
        self.call_tokens: dict[str, tuple[Token[str], asyncio.Task[Any] | None]] = {}
        self.reminders: dict[str, tuple[int, str]] = {}

    def create_reminder(self, target: Path, native: ReadFileTool) -> tuple[Path, int, str]:
        if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW") or not {os.open, os.mkdir, os.unlink}.issubset(os.supports_dir_fd):
            raise ValueError("secure reminder creation unavailable")
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.runtime.workspace, flags)
        try:
            for name in (".sparseread", "nanobot-reminders"):
                try:
                    os.mkdir(name, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                next_fd = os.open(name, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            name = f"{secrets.token_hex(16)}.txt"
            hint_path = self.runtime.workspace / ".sparseread" / "nanobot-reminders" / name
            if Path(native._resolve_read(str(hint_path))).resolve(strict=False) != hint_path:
                raise ValueError("native reader cannot access reminder")
            file_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=fd)
            try:
                text = f"SparseRead: call sro_preview with path {json.dumps(str(target), ensure_ascii=False)}, then use sro_read for targeted evidence. Native bounded reads remain available.\n"
                with os.fdopen(file_fd, "w", encoding="utf-8") as output:
                    output.write(text)
            except BaseException:
                try:
                    os.unlink(name, dir_fd=fd)
                except OSError:
                    pass
                raise
            return hint_path, fd, name
        except BaseException:
            os.close(fd)
            raise

    def clear_reminder(self, call_id: str) -> None:
        item = self.reminders.pop(call_id, None)
        if item is None:
            return
        fd, name = item
        try:
            os.unlink(name, dir_fd=fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    async def before_execute_tool(self, context: Any, tool_call: Any, tool: Any, params: Any) -> None:
        call_id = str(tool_call.id)
        self.call_tokens[call_id] = (_CALL_ID.set(call_id), asyncio.current_task())
        if context.session_key != self.request.session_key or not isinstance(params, dict):
            return
        name = str(tool_call.name or "")
        if name in WRITE_TOOLS or name in EXEC_TOOLS:
            self.pending[call_id] = (name, dict(params))
        if name != "read_file" or type(tool) is not ReadFileTool or not self.request.turn_id:
            return
        turn_id = str(self.request.turn_id)
        self.runtime.native_readers[turn_id] = tool
        if (self.registry.config.mode not in {"auto", "force", "force_sro", "enforce"}
                or turn_id not in self.runtime.enabled_turns or params.get("force") is True
                or params.get("limit") is not None or params.get("pages")
                or params.get("offset") not in (None, 0, 1)
                or set(params) - {"path", "offset", "limit", "pages", "force"}):
            return
        value = params.get("path")
        if not isinstance(value, str) or not value or value != value.strip():
            return
        try:
            target = _lexical(self.runtime.workspace, value)
            # authorize() uses the actual prepared native reader before the
            # metadata-only manifest and content-sensitive classifier.
            self.runtime.authorize(target, turn_id)
            if not target.is_file():
                return
            async with self.runtime.lock:
                decision = self.runtime.call("decide", {"path": str(target)}, self.request)
            if decision.get("should_handoff_read") is not True:
                return
            hint_path, fd, name = self.create_reminder(target, tool)
            self.reminders[call_id] = (fd, name)
            params["path"] = str(hint_path)
            params.pop("offset", None)
            params.pop("limit", None)
        except (OSError, ValueError, RuntimeError):
            return

    def clear_call(self, tool_call: Any) -> None:
        entry = self.call_tokens.pop(str(tool_call.id), None)
        if entry is not None and entry[1] is asyncio.current_task():
            _CALL_ID.reset(entry[0])

    async def after_execute_tool(self, context: Any, tool_call: Any, tool: Any, params: Any, result: Any) -> None:
        try:
            self.clear_reminder(str(tool_call.id))
            entry = self.pending.pop(str(tool_call.id), None)
            if isinstance(result, str) and result.lstrip().lower().startswith("error") and tool_call.name == "read_file":
                self.runtime.native_readers.pop(str(self.request.turn_id), None)
            if entry is None or (isinstance(result, str) and result.lstrip().lower().startswith("error")):
                return
            name, args = entry
            async with self.runtime.lock:
                self.runtime.bridge.runtime.orchestrator.set_context(self.runtime.context(self.request))
                if name in WRITE_TOOLS:
                    for value in candidate_paths(args):
                        try:
                            self.runtime.bridge.runtime.orchestrator.record_output_write(_inside(self.runtime.workspace, value))
                        except (OSError, ValueError):
                            continue
                elif name in EXEC_TOOLS:
                    command = str(args.get("command") or args.get("cmd") or "")
                    cwd = str(args.get("working_dir") or args.get("cwd") or args.get("workdir") or self.runtime.workspace)
                    self.runtime.policy.record_result(command, cwd, str(result))
        finally:
            self.clear_call(tool_call)

    async def on_execute_tool_error(self, context: Any, tool_call: Any, tool: Any, params: Any, error: Any) -> None:
        self.pending.pop(str(tool_call.id), None)
        self.clear_reminder(str(tool_call.id))
        if tool_call.name == "read_file":
            self.runtime.native_readers.pop(str(self.request.turn_id), None)
        self.clear_call(tool_call)

    async def on_finally(self, context: Any) -> None:
        try:
            self.pending.clear()
            for token, task in reversed(list(self.call_tokens.values())):
                if task is asyncio.current_task():
                    _CALL_ID.reset(token)
            self.call_tokens.clear()
            for call_id in list(self.reminders):
                self.clear_reminder(call_id)
            self.runtime.enabled_turns.discard(str(self.request.turn_id))
            self.runtime.native_readers.pop(str(self.request.turn_id), None)
            if context.exception is None and context.error is None and context.final_content:
                async with self.runtime.lock:
                    self.runtime.bridge.runtime.orchestrator.set_context(self.runtime.context(self.request))
                    self.runtime.bridge.runtime.orchestrator.finish_episode(self.runtime.conversation)
        finally:
            self.registry.release(self.runtime)


class HookFactory:
    _sparseread_owned = True

    def __init__(self, registry: RuntimeRegistry):
        self.registry = registry

    def __call__(self, context: Any) -> NanoHook | None:
        request = current_request_context()
        if request is None or not context.session_key or context.session_key != request.session_key:
            return None
        try:
            runtime = self.registry.acquire(request)
            return NanoHook(self.registry, request, runtime)
        except (OSError, ValueError):
            return None
