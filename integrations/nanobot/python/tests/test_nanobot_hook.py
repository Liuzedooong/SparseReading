from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("nanobot")
from nanobot.agent.hook import AgentHook, AgentHookContext, AgentRunHookContext, AgentTurnHookContext, CompositeHook
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool
from nanobot.providers.base import LLMResponse, ToolCallRequest
from sparseread.config import SparseReadConfig
from sparseread.wrapper import SparseRead
from sparseread_nanobot.adapter import NanobotAdapter
from sparseread_nanobot.v041 import HookFactory, NanoHook, RuntimeRegistry


def request(root: Path, session: str = "session-a", generation: str = "gen-a", turn: str = "turn-1", *, persist: bool = True) -> RequestContext:
    return RequestContext(channel="cli", chat_id="direct", session_key=session, session_generation=generation,
                          turn_id=turn, workspace=root, persist_session=persist)


def agent(root: Path, mode: str = "auto"):
    host = SimpleNamespace(tools=ToolRegistry(), _hook_factories=[], _extra_hooks=[])
    host.tools.register(ReadFileTool(workspace=root, allowed_dir=root, restrict_to_workspace=True))
    template = SparseRead(SparseReadConfig(mode=mode, workspace=root))
    NanobotAdapter().install(host, template)
    return host


def hook(host, ctx):
    with request_context(ctx):
        return host._hook_factories[0](AgentTurnHookContext(session_key=ctx.session_key, workspace=ctx.workspace))


def call(name: str, args: dict, ident: str = "call-1") -> ToolCallRequest:
    return ToolCallRequest(id=ident, name=name, arguments=args)


async def establish(host, ctx, path="large.txt"):
    h = hook(host, ctx)
    await host.tools.get("sro_preview").runtime_context_provider()(ctx)
    item = call("read_file", {"path": path, "limit": 1}, "proof")
    context = AgentHookContext(iteration=0, messages=[], session_key=ctx.session_key)
    native, params, error = host.tools.prepare_call(item.name, item.arguments)
    assert error is None
    with request_context(ctx):
        await h.before_execute_tool(context, item, native, params)
        result = await native.execute(**params)
        assert not getattr(result, "is_error", False)
        await h.after_execute_tool(context, item, native, params, result)
    return h


@pytest.mark.asyncio
async def test_official_tool_registry_composite_and_repeat_install(tmp_path: Path):
    host = agent(tmp_path)
    expected = {"sro_preview", "sro_raw", "sro_card", "sro_read", "sro_guard", "sro_handoff"}
    assert expected.issubset(set(host.tools.tool_names))
    assert len(host.tools.get_runtime_context_providers()) == 1
    assert all(host.tools.get(name).concurrency_safe is False for name in expected)
    names = [entry["function"]["name"] for entry in host.tools.get_definitions()]
    assert expected.issubset(names)
    h = hook(host, request(tmp_path))
    assert isinstance(h, AgentHook)
    chain = CompositeHook([AgentHook(), h])
    assert chain.has_run_hooks() and chain.wants_streaming() is False
    NanobotAdapter().install(host, SparseRead(SparseReadConfig(workspace=tmp_path, mode="advisory")))
    assert len(host._hook_factories) == 1
    assert host._sparseread_registry.config.mode == "advisory"


@pytest.mark.asyncio
async def test_per_request_runtimes_and_reference_isolation(tmp_path: Path):
    host = agent(tmp_path)
    (tmp_path / "large.txt").write_text("中文🧭 evidence ORCHID\n" * 1000)
    first = request(tmp_path, "a", "ga")
    second = request(tmp_path, "b", "gb")
    async def preview(ctx):
        h = await establish(host, ctx)
        with request_context(ctx):
            value = json.loads(await host.tools.execute("sro_preview", {"path": "large.txt"}))["preview_pack"]
        return value, h
    (a, ha), (b, hb) = await __import__("asyncio").gather(preview(first), preview(second))
    assert len(host._sparseread_registry.sessions) == 2
    with request_context(second):
        forbidden = await host.tools.execute("sro_raw", {"raw_ref": a["raw_ref"]})
        assert forbidden.is_error
    with request_context(first):
        raw = json.loads(await host.tools.execute("sro_raw", {"raw_ref": a["raw_ref"], "range": {"start": 0, "end": 3}}))
        assert raw["raw"]["content"] == "中文🧭"
    assert a["raw_ref"] and b["raw_ref"]
    await ha.on_finally(AgentRunHookContext(messages=[]))
    await hb.on_finally(AgentRunHookContext(messages=[]))


@pytest.mark.asyncio
async def test_generation_and_source_change_invalidate_refs(tmp_path: Path):
    host = agent(tmp_path)
    source = tmp_path / "large.txt"
    source.write_text("evidence AAA\n" * 500)
    first = request(tmp_path, "a", "generation-1")
    h = await establish(host, first)
    with request_context(first):
        preview = json.loads(await host.tools.execute("sro_preview", {"path": "large.txt"}))["preview_pack"]
        source.write_text(source.read_text().replace("AAA", "BBB"))
        stale = await host.tools.execute("sro_raw", {"raw_ref": preview["raw_ref"]})
        assert stale.is_error
    await h.on_finally(AgentRunHookContext(messages=[]))
    second = request(tmp_path, "a", "generation-2")
    h2 = await establish(host, second)
    with request_context(second):
        wrong_generation = await host.tools.execute("sro_raw", {"raw_ref": preview["raw_ref"]})
        assert wrong_generation.is_error
    await h2.on_finally(AgentRunHookContext(messages=[]))


@pytest.mark.asyncio
async def test_handoff_is_scoped_and_bounded_native(tmp_path: Path):
    host = agent(tmp_path, "force")
    (tmp_path / "large.txt").write_text("data\n" * 2000)
    ctx = request(tmp_path)
    h = hook(host, ctx)
    await host.tools.get("sro_preview").runtime_context_provider()(ctx)
    context = AgentHookContext(iteration=0, messages=[], session_key=ctx.session_key)
    native = host.tools.get("read_file")
    with request_context(ctx):
        full = call("read_file", {"path": "large.txt"})
        params = dict(full.arguments)
        await h.before_execute_tool(context, full, native, params)
        assert full.name == "read_file" and params["path"] != "large.txt"
        result = await native.execute(**params)
        assert "sro_preview" in str(result)
        reminder = Path(params["path"])
        await h.after_execute_tool(context, full, native, params, result)
        assert not reminder.exists()
        bounded = call("read_file", {"path": "large.txt", "offset": 2, "limit": 5}, "bounded")
        params = dict(bounded.arguments)
        await h.before_execute_tool(context, bounded, native, params)
        assert params["path"] == "large.txt"
        await h.after_execute_tool(context, bounded, native, params, "ok")
    await h.on_finally(AgentRunHookContext(messages=[]))


@pytest.mark.asyncio
async def test_advisory_and_native_do_not_rewrite(tmp_path: Path):
    (tmp_path / "large.txt").write_text("data\n" * 2000)
    for mode in ("advisory", "native"):
        host = agent(tmp_path, mode)
        ctx = request(tmp_path)
        h = hook(host, ctx)
        provider = host.tools.get("sro_preview").runtime_context_provider()
        guidance = await provider(ctx)
        assert bool(guidance) == (mode != "native")
        item = call("read_file", {"path": "large.txt"})
        params = dict(item.arguments)
        with request_context(ctx):
            await h.before_execute_tool(AgentHookContext(iteration=0, messages=[], session_key=ctx.session_key), item, host.tools.get("read_file"), params)
            assert params["path"] == "large.txt"
            await h.after_execute_tool(AgentHookContext(iteration=0, messages=[], session_key=ctx.session_key), item, host.tools.get("read_file"), params, "ok")
        await h.on_finally(AgentRunHookContext(messages=[]))


@pytest.mark.asyncio
async def test_record_only_successful_write_by_call_id_and_cleanup(tmp_path: Path):
    host = agent(tmp_path)
    h = hook(host, request(tmp_path))
    ok, failed, pending = (call("write_file", {"path": name}, ident) for name, ident in (("ok.txt", "ok"), ("bad.txt", "bad"), ("cancel.txt", "cancel")))
    context = AgentHookContext(iteration=0, messages=[], session_key="session-a", response=LLMResponse(content=None, tool_calls=[ok, failed, pending]))
    async def success():
        await h.before_execute_tool(context, ok, None, ok.arguments)
        (tmp_path / "ok.txt").write_text("written")
        await h.after_execute_tool(context, ok, None, ok.arguments, "written")
    async def failure():
        await h.before_execute_tool(context, failed, None, failed.arguments)
        await h.on_execute_tool_error(context, failed, None, failed.arguments, RuntimeError("failed"))
    await __import__("asyncio").gather(success(), failure())
    h.pending["cancel"] = ("write_file", pending.arguments)
    await h.on_finally(AgentRunHookContext(messages=[], exception=RuntimeError("cancelled")))
    written = h.runtime.bridge.runtime.orchestrator._written_paths_by_conversation[h.runtime.conversation]
    assert str((tmp_path / "ok.txt").resolve()) in written
    assert str((tmp_path / "bad.txt").resolve()) not in written
    assert str((tmp_path / "cancel.txt").resolve()) not in written
    assert h.pending == {}


@pytest.mark.asyncio
async def test_outside_symlink_and_ephemeral_fail_closed(tmp_path: Path):
    host = agent(tmp_path)
    (tmp_path / "allowed.txt").write_text("allowed")
    outside = tmp_path.parent / "external-nanobot-fixture.txt"
    outside.write_text("outside")
    link = tmp_path / "link.txt"
    link.symlink_to(outside)
    try:
        h = await establish(host, request(tmp_path), "allowed.txt")
        with request_context(request(tmp_path)):
            result = await host.tools.execute("sro_preview", {"path": "link.txt"})
            assert result.is_error and "outside" in result
        await h.on_finally(AgentRunHookContext(messages=[]))
        transient = request(tmp_path, persist=False)
        with request_context(transient):
            assert (await host.tools.execute("sro_preview", {"path": "link.txt"})).is_error
        assert hook(host, transient) is None
    finally:
        outside.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_native_exact_file_rule_is_not_bypassed_by_symlink(tmp_path: Path):
    host = agent(tmp_path)
    limited = tmp_path / "limited"
    limited.mkdir()
    (limited / "seed.txt").write_text("allowed")
    extra = tmp_path / "extra.txt"
    extra.write_text("extra source")
    alias = tmp_path / "alias.txt"
    alias.symlink_to(extra)
    host.tools.register(ReadFileTool(workspace=tmp_path, allowed_dir=limited, extra_read_allowed_files=[extra], restrict_to_workspace=True))
    ctx = request(tmp_path)
    h = await establish(host, ctx, "limited/seed.txt")
    with request_context(ctx):
        direct = await host.tools.execute("sro_preview", {"path": "extra.txt"})
        assert not getattr(direct, "is_error", False)
        via_alias = await host.tools.execute("sro_preview", {"path": "alias.txt"})
        assert via_alias.is_error
    await h.on_finally(AgentRunHookContext(messages=[]))


@pytest.mark.asyncio
async def test_missing_turn_proof_and_mismatched_workspace_fail_closed(tmp_path: Path):
    host = agent(tmp_path)
    (tmp_path / "large.txt").write_text("data\n" * 500)
    with request_context(request(tmp_path)):
        result = await host.tools.execute("sro_preview", {"path": "large.txt"})
    assert result.is_error and "read_file first" in result
    from nanobot.security.workspace_access import default_workspace_scope
    other = tmp_path / "other"
    other.mkdir()
    context = RequestContext(channel="cli", chat_id="direct", session_key="s", session_generation="g", turn_id="t", workspace=tmp_path,
                             workspace_scope=default_workspace_scope(other, True))
    with request_context(context):
        result = await host.tools.execute("sro_preview", {"path": "large.txt"})
    assert result.is_error and "scope" in result


def test_session_registry_is_bounded_and_preserves_active(tmp_path: Path):
    host = agent(tmp_path)
    registry = host._sparseread_registry
    registry.max_sessions = 2
    a = registry.acquire(request(tmp_path, "a", "g"))
    registry.get(request(tmp_path, "b", "g"))
    registry.get(request(tmp_path, "c", "g"))
    assert len(registry.sessions) == 2
    assert any(value is a for value in registry.sessions.values())
    assert not any(key[1] == "b" for key in registry.sessions)
    registry.release(a)


@pytest.mark.asyncio
async def test_parent_component_remains_native_and_direct_sro_rejects(tmp_path: Path):
    host = agent(tmp_path, "force")
    (tmp_path / "ordinary").mkdir()
    (tmp_path / "other" / "child").mkdir(parents=True)
    (tmp_path / "ordinary" / "document.txt").write_text("wrong source\n" * 500)
    (tmp_path / "other" / "document.txt").write_text("actual source\n" * 500)
    (tmp_path / "ordinary" / "jump").symlink_to(tmp_path / "other" / "child", target_is_directory=True)
    ctx = request(tmp_path)
    h = await establish(host, ctx, "ordinary/document.txt")
    value = "ordinary/jump/../document.txt"
    item = call("read_file", {"path": value}, "parent-component")
    params = dict(item.arguments)
    context = AgentHookContext(iteration=0, messages=[], session_key=ctx.session_key)
    native = host.tools.get("read_file")
    with request_context(ctx):
        await h.before_execute_tool(context, item, native, params)
        assert params["path"] == value
        result = await native.execute(**params)
        assert "actual source" in str(result) and "wrong source" not in str(result)
        await h.after_execute_tool(context, item, native, params, result)
        assert (await host.tools.execute("sro_preview", {"path": value})).is_error
    await h.on_finally(AgentRunHookContext(messages=[]))


@pytest.mark.asyncio
async def test_cancelled_same_task_restores_call_context(tmp_path: Path):
    from sparseread_nanobot.v041 import _CALL_ID
    host = agent(tmp_path)
    ctx = request(tmp_path)
    h = hook(host, ctx)
    item = call("write_file", {"path": "cancel.txt"}, "cancelled")
    context = AgentHookContext(iteration=0, messages=[], session_key=ctx.session_key)
    assert _CALL_ID.get() == ""
    await h.before_execute_tool(context, item, None, item.arguments)
    assert _CALL_ID.get() == "cancelled"
    await h.on_finally(AgentRunHookContext(messages=[], exception=__import__("asyncio").CancelledError()))
    assert _CALL_ID.get() == ""
    assert h.pending == {}


@pytest.mark.asyncio
async def test_all_tools_execute_and_collection_permissions(tmp_path: Path):
    host = agent(tmp_path)
    folder = tmp_path / "collection"
    folder.mkdir()
    (folder / "one.txt").write_text("ORCHID evidence one\n" * 300)
    (folder / "two.txt").write_text("ORCHID evidence two\n" * 300)
    ctx = request(tmp_path)
    h = await establish(host, ctx, "collection/one.txt")
    with request_context(ctx):
        for name in ("sro_preview", "sro_card", "sro_read", "sro_raw", "sro_guard", "sro_handoff"):
            assert host.tools.get(name).parameters["type"] == "object"
        preview = json.loads(await host.tools.execute("sro_preview", {"path": "collection"}))["preview_pack"]
        card = await host.tools.execute("sro_card", {"path": "collection"})
        assert not getattr(card, "is_error", False)
        focused = await host.tools.execute("sro_read", {"target": {"artifact_id": preview["artifact_id"]}, "mode": "focus", "hint": {"goal": "find evidence", "needles": ["ORCHID"]}})
        assert not getattr(focused, "is_error", False)
        raw = await host.tools.execute("sro_raw", {"raw_ref": preview["raw_ref"], "selector": "one.txt"})
        assert not getattr(raw, "is_error", False)
        assert "ORCHID evidence one" in json.loads(raw)["raw"]["content"]
        assert str(await host.tools.execute("sro_guard", {"message": "covered"})) == "covered"
        handoff = await host.tools.execute("sro_handoff", {"path": "collection/one.txt"})
        assert "sro_preview" in str(handoff)
        (folder / "link.txt").symlink_to(folder / "one.txt")
        assert (await host.tools.execute("sro_preview", {"path": "collection"})).is_error
        assert (await host.tools.execute("sro_raw", {"raw_ref": preview["raw_ref"]})).is_error
    await h.on_finally(AgentRunHookContext(messages=[]))
