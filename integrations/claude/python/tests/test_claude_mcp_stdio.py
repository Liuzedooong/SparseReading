"""Exercise all public tools through the real MCP stdio transport."""
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_mcp_stdio_discovery_unicode_errors_and_source_change(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("甲😀乙\nALPHA 5705\n", encoding="utf-8")
    env = os.environ.copy()
    if os.environ.get("SRO_TEST_INSTALLED"):
        env.pop("PYTHONPATH", None)
    else:
        repo = Path(__file__).resolve().parents[4]
        env["PYTHONPATH"] = os.pathsep.join([str(repo / "packages/sparseread-core/src"), str(repo / "integrations/claude/python/src")])
    env["SRO_TOKEN_LOG"] = "0"
    server = StdioServerParameters(command=sys.executable, args=["-m", "sparseread_claude.claude_mcp", "--workspace", str(tmp_path), "--mode", "force_sro"], env=env)

    async def run():
        async with stdio_client(server) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert {tool.name for tool in tools.tools} == {"sro_preview", "sro_read", "sro_card", "sro_raw", "sro_decide", "sro_trace", "sro_preflight", "sro_usage"}
                assert "Unicode" in next(t for t in tools.tools if t.name == "sro_raw").inputSchema["properties"]["range"]["description"]
                async def call(name, args):
                    result = await client.call_tool(name, args)
                    return result, json.loads(result.content[0].text)
                result, preview = await call("sro_preview", {"path": str(source)})
                assert not result.isError
                raw_ref = preview["preview_pack"]["raw_ref"]
                aid = preview["preview_pack"]["artifact_id"]
                raw_result, raw = await call("sro_raw", {"raw_ref": raw_ref, "range": {"start": 1, "end": 3}})
                assert not raw_result.isError and raw["raw"]["content"] == "😀乙"
                for name, args in [("sro_card", {"path": str(source)}), ("sro_decide", {"path": str(source)}),
                                   ("sro_trace", {}), ("sro_preflight", {"max_candidates": 1}), ("sro_usage", {})]:
                    result, value = await call(name, args)
                    assert not result.isError, (name, value)
                result, value = await call("sro_read", {"target": {"artifact_id": aid}, "mode": "collect", "hint": {"goal": "find alpha", "needles": ["ALPHA"], "slots": [{"id": "q", "question": "What is ALPHA?"}]}})
                assert not result.isError and "5705" in str(value)
                source.write_text("甲😀乙\nALPHA 6806\n", encoding="utf-8")
                stale, value = await call("sro_raw", {"raw_ref": raw_ref})
                assert stale.isError and "stale" in value["error"]
                fresh, value = await call("sro_read", {"target": {"artifact_id": aid}, "mode": "collect", "hint": {"goal": "find alpha", "needles": ["ALPHA"], "slots": [{"id": "q", "question": "What is ALPHA?"}]}})
                assert not fresh.isError and "6806" in str(value)
    asyncio.run(run())


def test_mcp_workspace_boundary_and_safe_preflight(tmp_path, monkeypatch):
    from sparseread_claude.claude_mcp import SparseReadClaudeMCP
    workspace = tmp_path / "workspace"
    cwd = tmp_path / "elsewhere"
    workspace.mkdir()
    cwd.mkdir()
    inside = workspace / "same.txt"
    inside.write_text("WORKSPACE SOURCE " * 1000)
    (cwd / "same.txt").write_text("DECOY SECRET")
    external = cwd / "secret.txt"
    external.write_text("PRIVATE SECRET")
    (workspace / "escape.txt").symlink_to(external)
    monkeypatch.chdir(cwd)
    service = SparseReadClaudeMCP(str(workspace))
    preview = json.loads(service.handle_tool("sro_preview", {"path": "same.txt"}))
    assert preview["preview_pack"]["card"]["path"] == str(inside.resolve())
    assert "DECOY SECRET" not in str(preview)
    for candidate in (str(external), "../elsewhere/secret.txt", "escape.txt"):
        response = json.loads(service.handle_tool("sro_preview", {"path": candidate}))
        assert "outside the configured workspace" in response["error"]
    collection = workspace / "collection"
    collection.mkdir()
    (collection / "escape.txt").symlink_to(external)
    response = json.loads(service.handle_tool("sro_preview", {"path": str(collection)}))
    assert "symlinks" in response["error"] and "PRIVATE SECRET" not in str(response)
    invalid = json.loads(service.handle_tool("sro_preflight", {"workspace": str(cwd)}))
    assert "configured workspace" in invalid["error"]
    alias = json.loads(service.handle_tool("sro_preflight", {"workspace": str(workspace / ".." / "workspace")}))
    assert "configured workspace" in alias["error"]
    (collection / "escape.txt").unlink()
    nested = collection / "nested.txt"
    nested.write_text("NESTED EVIDENCE")
    assert "preview_pack" in json.loads(service.handle_tool("sro_preview", {"path": "collection/nested.txt"}))
    valid = json.loads(service.handle_tool("sro_preflight", {}))
    assert valid["scope"] == "top-level regular files"
    trace = json.loads(service.handle_tool("sro_trace", {}))
    assert any(event["kind"] == "sro_preflight" for event in trace["events"])
    assert all("escape" not in handoff["path"] and "nested.txt" not in handoff["path"] for handoff in valid["handoffs"])
