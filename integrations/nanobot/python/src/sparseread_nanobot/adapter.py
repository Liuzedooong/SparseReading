"""Install the official NanoBot 0.4.1 adapter without importing it into core."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from sparseread.config import SparseReadConfig, SparseReadMode
from sparseread.wrapper import SparseRead


class NanobotAdapter:
    """Register per-request tools and a per-turn hook factory on NanoBot 0.4.1."""

    @staticmethod
    def matches(agent: Any) -> bool:
        tools = getattr(agent, "tools", None)
        return all(hasattr(tools, attr) for attr in ("register", "unregister", "get", "has")) and isinstance(getattr(agent, "_hook_factories", None), list)

    def install(self, agent: Any, sparseread: SparseRead, *, conversation_id: str | None = None) -> list[str]:
        # A static conversation_id cannot safely identify an active host session.
        if conversation_id not in (None, "default"):
            raise ValueError("NanoBot sessions are determined by RequestContext, not a static conversation_id")
        try:
            host_version = version("nanobot-ai")
        except PackageNotFoundError as exc:
            raise RuntimeError("Install nanobot-ai==0.4.1 to use the NanoBot adapter") from exc
        if host_version != "0.4.1":
            raise RuntimeError(f"NanoBot adapter requires tested nanobot-ai==0.4.1, got {host_version}")
        if not self.matches(agent):
            raise TypeError("NanoBot 0.4.1 AgentLoop with ToolRegistry and hook factories is required")

        from sparseread_nanobot.v041 import HookFactory, InternalTool, NanoTool, RuntimeRegistry

        tools = agent.tools
        registry = RuntimeRegistry(sparseread.config, tools)
        prototypes = list(sparseread.tools())
        prototypes.extend([
            InternalTool("sro_guard", "Internal SparseRead guard; do not call directly.", {"message": {"type": "string"}}, ["message"]),
            InternalTool("sro_handoff", "Internal SparseRead handoff; do not call directly.", {"path": {"type": "string"}, "episode_hint": {"type": "object"}}, ["path"]),
        ])
        previous_runtime = getattr(agent, "sparseread", None)
        def owned(tool: Any) -> bool:
            return bool(getattr(tool, "_sparseread_owned", False)) or (
                isinstance(previous_runtime, SparseRead)
                and getattr(tool, "orchestrator", None) is previous_runtime.orchestrator
            ) or (type(tool).__module__ == "sparseread_nanobot.hook" and type(tool).__name__ in {"SroGuardTool", "SroHandoffTool"})
        for prototype in prototypes:
            existing = tools.get(prototype.name)
            if existing is not None and not owned(existing):
                raise ValueError(f"Refusing to replace a non-SparseRead tool: {prototype.name}")
        previous_names = set(getattr(agent, "_sparseread_tool_names", ())) | {"sro_preview", "sro_raw", "sro_card", "sro_read", "sro_guard", "sro_handoff"}
        names = {prototype.name for prototype in prototypes}
        for name in previous_names - names:
            existing = tools.get(name)
            if existing is not None and owned(existing):
                tools.unregister(name)
        for prototype in prototypes:
            tools.register(NanoTool(registry, prototype))
        agent._hook_factories[:] = [factory for factory in agent._hook_factories if not getattr(factory, "_sparseread_owned", False)]
        agent._hook_factories.append(HookFactory(registry))
        if isinstance(getattr(agent, "_extra_hooks", None), list):
            agent._extra_hooks[:] = [hook for hook in agent._extra_hooks if not (type(hook).__module__ == "sparseread_nanobot.hook" and type(hook).__name__ == "SparseReadHook")]
        agent._sparseread_tool_names = names
        agent._sparseread_registry = registry
        agent.sparseread = sparseread  # Configuration template; active state is session-owned.
        return [*sorted(names), "hook:sparse_read"]


def install(agent: Any, *, mode: SparseReadMode = "auto", workspace: str | Path | None = None,
            config: SparseReadConfig | None = None, conversation_id: str | None = None) -> SparseRead:
    """Install using a configuration template; request contexts own active sessions."""
    runtime = SparseRead(config or SparseReadConfig(mode=mode, workspace=workspace))
    NanobotAdapter().install(agent, runtime, conversation_id=conversation_id)
    return runtime
