"""Official 0.4.1 AgentLoop contract with a deterministic provider, not a model test."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
pytest.importorskip("nanobot")
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.execution import _partition_tool_batches
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from sparseread_nanobot import install


class ScriptedProvider(LLMProvider):
    def __init__(self):
        super().__init__(provider_name="sparseread-fixture")
        self.requests = []
        self.stream_requests = 0

    def get_default_model(self):
        return "fixture"

    async def chat(self, messages, tools=None, model=None, **kwargs):
        self.requests.append({"messages": messages, "tools": tools})
        last_user = max(i for i, message in enumerate(messages) if message.get("role") == "user")
        user = str(messages[last_user].get("content", ""))
        seen = [m for m in messages[last_user + 1:] if m.get("role") == "tool"]
        if "CASE_FLOW" in user:
            if not seen:
                action = ("read_file", {"path": "document.txt", "limit": 1}, "read-proof")
            elif len(seen) == 1:
                action = ("sro_preview", {"path": "document.txt"}, "preview")
            elif len(seen) == 2:
                preview = json.loads(seen[1]["content"])["preview_pack"]
                action = ("sro_read", {"target": {"artifact_id": preview["artifact_id"]}, "mode": "focus", "hint": {"goal": "Find code", "needles": ["ORCHID"]}}, "read")
            elif len(seen) == 3:
                preview = json.loads(seen[1]["content"])["preview_pack"]
                action = ("sro_raw", {"raw_ref": preview["raw_ref"], "selector": "ORCHID"}, "raw")
            else:
                return LLMResponse(content="FLOW_COMPLETE")
        elif "CASE_READ" in user and not seen:
            action = ("read_file", {"path": "document.txt"}, "read-native")
        elif "CASE_BOUNDED" in user and not seen:
            action = ("read_file", {"path": "document.txt", "offset": 2, "limit": 2}, "read-bounded")
        elif "CASE_CANCEL" in user and not seen:
            action = ("write_file", {"path": "cancel.txt", "content": "must not be written"}, "cancel")
        elif "CASE_DISABLED" in user and len(seen) == 0:
            action = ("read_file", {"path": "document.txt"}, "disabled-read")
        elif "CASE_DISABLED" in user and len(seen) == 1:
            action = ("sro_preview", {"path": "document.txt"}, "disabled-preview")
        elif "CASE_WRITES" in user and not seen:
            return LLMResponse(content=None, finish_reason="tool_calls", tool_calls=[
                ToolCallRequest(id="ok", name="write_file", arguments={"path": "ok.txt", "content": "written"}),
                ToolCallRequest(id="fail", name="write_file", arguments={"path": "fail.txt", "content": "fail"}),
            ])
        else:
            return LLMResponse(content="CASE_COMPLETE")
        name, args, ident = action
        return LLMResponse(content=None, finish_reason="tool_calls", tool_calls=[ToolCallRequest(id=ident, name=name, arguments=args)])

    async def chat_stream(self, messages, tools=None, model=None, on_content_delta=None, **kwargs):
        self.stream_requests += 1
        result = await self.chat(messages, tools, model, **kwargs)
        if result.content and on_content_delta:
            await on_content_delta(result.content)
        return result


class FixtureWrite(Tool):
    @property
    def name(self): return "write_file"
    @property
    def description(self): return "Synthetic write fixture"
    @property
    def parameters(self):
        return {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}
    @property
    def concurrency_safe(self): return True
    def __init__(self, root: Path, started: asyncio.Event | None = None):
        self.root, self.started = root, started
    async def execute(self, path, content):
        if path == "fail.txt":
            return ToolResult.error("Error: synthetic denied write")
        if path == "cancel.txt":
            self.started.set()
            await asyncio.sleep(30)
        (self.root / path).write_text(content)
        return "written"


def make_agent(root: Path, mode: str = "auto"):
    provider = ScriptedProvider()
    agent = AgentLoop(bus=MessageBus(), provider=provider, workspace=root, restrict_to_workspace=True)
    install(agent, mode=mode, workspace=root)
    return agent, provider


def visible_guidance(provider: ScriptedProvider) -> list[bool]:
    return [any("# Sparse Reading" in str(message.get("content", "")) for message in item["messages"]) for item in provider.requests]


@pytest.mark.asyncio
async def test_full_loop_nonstream_and_stream_two_sessions(tmp_path: Path):
    (tmp_path / "document.txt").write_text("中文🧭\n" + "filler line\n" * 1000 + "ORCHID: CAPRI-913\n")
    host, provider = make_agent(tmp_path)
    chunks = []
    async def collect(value): chunks.append(value)
    a, b = await asyncio.gather(host.process_direct("CASE_FLOW A", session_key="cli:A"),
                                host.process_direct("CASE_FLOW B", session_key="cli:B", on_stream=collect))
    assert a.content == b.content == "FLOW_COMPLETE"
    assert provider.stream_requests > 0 and chunks
    assert all(visible_guidance(provider))
    assert len(host._sparseread_registry.sessions) == 2
    for runtime in host._sparseread_registry.sessions.values():
        assert runtime.active == 0
        kinds = [event["kind"] for event in runtime.bridge.events]
        assert "sro_preview" in kinds and "sro_read" in kinds and "sro_raw" in kinds
    await host.process_direct("CASE_FLOW followup", session_key="cli:A")
    assert len(host._sparseread_registry.sessions) == 2
    old = await host.sessions.state.read("cli:A")
    await host.sessions.state.delete("cli:A", expected_generation=old.generation)
    await host.process_direct("CASE_FLOW after clear", session_key="cli:A")
    keys = [key for key in host._sparseread_registry.sessions if key[1] == "cli:A"]
    assert len(keys) == 1 and keys[0][2] != old.generation


@pytest.mark.asyncio
async def test_actual_loop_handoff_and_bounded_native(tmp_path: Path):
    (tmp_path / "document.txt").write_text("ORCHID long evidence\n" * 1200)
    host, provider = make_agent(tmp_path, "force")
    await host.process_direct("CASE_READ", session_key="cli:read")
    assert any("sro_preview" in str(m.get("content")) for x in provider.requests for m in x["messages"] if m.get("role") == "tool")
    before = len(provider.requests)
    await host.process_direct("CASE_BOUNDED", session_key="cli:bounded")
    result_texts = [str(m.get("content")) for x in provider.requests[before:] for m in x["messages"] if m.get("role") == "tool"]
    assert result_texts and all("SparseRead: call sro_preview" not in text for text in result_texts)


@pytest.mark.asyncio
async def test_actual_loop_write_error_and_cancel(tmp_path: Path):
    host, _ = make_agent(tmp_path)
    started = asyncio.Event()
    host.tools.register(FixtureWrite(tmp_path, started))
    await host.process_direct("CASE_WRITES", session_key="cli:write")
    runtime = next(value for key, value in host._sparseread_registry.sessions.items() if key[1] == "cli:write")
    written = runtime.bridge.runtime.orchestrator._written_paths_by_conversation[runtime.conversation]
    assert str((tmp_path / "ok.txt").resolve()) in written
    assert str((tmp_path / "fail.txt").resolve()) not in written
    task = asyncio.create_task(host.process_direct("CASE_CANCEL", session_key="cli:cancel"))
    await asyncio.wait_for(started.wait(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    cancelled = next(value for key, value in host._sparseread_registry.sessions.items() if key[1] == "cli:cancel")
    assert not (tmp_path / "cancel.txt").exists()
    assert not cancelled.bridge.runtime.orchestrator._written_paths_by_conversation.get(cancelled.conversation)
    assert cancelled.active == 0


@pytest.mark.asyncio
async def test_ephemeral_has_no_sro_guidance_or_runtime(tmp_path: Path):
    (tmp_path / "document.txt").write_text("fixture\n" * 1000)
    host, provider = make_agent(tmp_path)
    await host.process_direct("ephemeral without tool call", session_key="cli:ephemeral", ephemeral=True)
    assert not any(visible_guidance(provider))
    assert not host._sparseread_registry.sessions


def test_native_parallel_batches_survive_sro_serialization(tmp_path: Path):
    host, _ = make_agent(tmp_path)
    native = FixtureWrite(tmp_path)
    host.tools.register(native)
    calls = [ToolCallRequest(id=str(i), name=name, arguments={}) for i, name in enumerate(("write_file", "write_file", "sro_card", "write_file", "write_file"))]
    assert [len(batch) for batch in _partition_tool_batches(host.tools, calls, concurrent=True)] == [2, 1, 2]


@pytest.mark.asyncio
async def test_disabled_native_and_preview_are_not_bypassed(tmp_path: Path):
    from nanobot.session.manager import SessionPolicy
    (tmp_path / "document.txt").write_text("ORCHID\n" * 1500)
    host, provider = make_agent(tmp_path, "force")
    await host.process_direct("CASE_DISABLED", session_key="cli:disabled", _session_policy=SessionPolicy(disabled_tools=frozenset({"read_file"})))
    outputs = [str(m.get("content")) for record in provider.requests for m in record["messages"] if m.get("role") == "tool"]
    assert any("not found" in output.lower() for output in outputs)
    assert any("read_file first" in output for output in outputs)
    previous = len(provider.requests)
    await host.process_direct("CASE_READ", session_key="cli:no-preview", _session_policy=SessionPolicy(disabled_tools=frozenset({"sro_preview"})))
    outputs = [str(m.get("content")) for record in provider.requests[previous:] for m in record["messages"] if m.get("role") == "tool"]
    assert outputs and not any("SparseRead: call sro_preview" in output for output in outputs)
