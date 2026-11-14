#!/usr/bin/env python3
"""Codex 0.169 app-server plugin and synthetic MCP check; no model or trust writes.

Run after project install, with an isolated CODEX_HOME for test fixtures.
The caller must have explicitly trusted the target project in that test home.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import subprocess
import threading
import time
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--expected-version", default="0.169.0")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    version = subprocess.run([args.codex, "--version"], check=True, capture_output=True, text=True).stdout.strip()
    if version != f"codex-cli {args.expected_version}":
        raise RuntimeError(f"Expected codex-cli {args.expected_version}, got {version}")
    from jsonschema import Draft7Validator
    schema_temp = tempfile.TemporaryDirectory(prefix="sro-codex-schema-")
    schema_root = Path(schema_temp.name)
    subprocess.run([args.codex, "app-server", "generate-json-schema", "--experimental", "--out", str(schema_root)],
                   cwd=workspace, check=True, capture_output=True, text=True)
    names = {
        "initialize": ("v1/InitializeParams.json", "v1/InitializeResponse.json"),
        "plugin/list": ("v2/PluginListParams.json", "v2/PluginListResponse.json"),
        "plugin/read": ("v2/PluginReadParams.json", "v2/PluginReadResponse.json"),
        "thread/start": ("v2/ThreadStartParams.json", "v2/ThreadStartResponse.json"),
        "mcpServerStatus/list": ("v2/ListMcpServerStatusParams.json", "v2/ListMcpServerStatusResponse.json"),
        "mcpServer/tool/call": ("v2/McpServerToolCallParams.json", "v2/McpServerToolCallResponse.json"),
    }
    validators = {name: (Draft7Validator(json.loads((schema_root / req).read_text())),
                         Draft7Validator(json.loads((schema_root / res).read_text()))) for name, (req, res) in names.items()}
    schema_hash = hashlib.sha256((schema_root / "codex_app_server_protocol.v2.schemas.json").read_bytes()).hexdigest()
    print(json.dumps({"host_version": version, "experimental_schema_sha256": schema_hash}))
    messages: queue.Queue[dict] = queue.Queue()
    diagnostics: list[str] = []
    process = subprocess.Popen([args.codex, "app-server", "--stdio",
                                "-c", 'model_provider="sro_diagnostic"',
                                "-c", 'model_providers.sro_diagnostic.name="SparseRead diagnostic"',
                                "-c", 'model_providers.sro_diagnostic.base_url="http://127.0.0.1:1/v1"',
                                "-c", 'model_providers.sro_diagnostic.wire_api="responses"',
                                "-c", 'model_providers.sro_diagnostic.supports_websockets=false',
                                "-c", 'model_providers.sro_diagnostic.requires_openai_auth=false'], cwd=workspace, env=os.environ.copy(),
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def read() -> None:
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except json.JSONDecodeError:
                pass
        messages.put({"error": "Codex app-server stopped: " + "".join(diagnostics)[-2000:]})

    def read_errors() -> None:
        for line in process.stderr:
            diagnostics.append(line)
            del diagnostics[:-20]

    threading.Thread(target=read, daemon=True).start()
    threading.Thread(target=read_errors, daemon=True).start()
    next_id = 0

    def rpc(method: str, params: dict) -> dict:
        nonlocal next_id
        validators[method][0].validate(params)
        next_id += 1
        process.stdin.write(json.dumps({"id": next_id, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        while True:
            message = messages.get(timeout=30)
            if "id" not in message and "error" in message:
                raise RuntimeError(message["error"])
            if message.get("id") == next_id:
                if "error" in message:
                    raise RuntimeError(message["error"])
                result = message["result"]
                validators[method][1].validate(result)
                return result

    try:
        rpc("initialize", {"clientInfo": {"name": "sparseread-smoke", "version": "0.1.1"}, "capabilities": {"experimentalApi": True}})
        process.stdin.write('{"method":"initialized"}\n')
        process.stdin.flush()
        listing = rpc("plugin/list", {"cwds": [str(workspace)], "marketplaceKinds": ["local"], "forceRefetch": False})
        catalog = [{"name": market["name"], "plugins": [plugin for plugin in market.get("plugins", []) if plugin.get("name") == "sparseread-codex"]} for market in listing.get("marketplaces", [])]
        print(json.dumps({"catalog": [market for market in catalog if market["plugins"]]}, ensure_ascii=False))
        detail = rpc("plugin/read", {"pluginName": "sparseread-codex", "marketplacePath": str(workspace / ".agents/plugins/marketplace.json")})
        plugin = detail["plugin"]
        print(json.dumps({"components": {key: plugin.get(key) for key in ("mcpServers", "skills", "hooks")}}, ensure_ascii=False))
        if not plugin.get("mcpServers") or not plugin.get("skills") or not plugin.get("hooks"):
            raise RuntimeError("Codex did not discover the MCP server, skill, and bundled hooks")
        thread = rpc("thread/start", {"cwd": str(workspace), "ephemeral": True})
        thread_id = thread["thread"]["id"]
        expected = {"sro_preview", "sro_read", "sro_raw", "sro_card", "sro_decide", "sro_trace"}
        deadline = time.monotonic() + 20
        while True:
            inventory = rpc("mcpServerStatus/list", {"threadId": thread_id})
            matches = [server for server in inventory.get("data", []) if "sparseread" in server.get("name", "")]
            if matches and matches[0].get("runtimeStatus") == "failed":
                raise RuntimeError("SparseRead MCP startup failed: " + str(matches[0].get("toolsError")))
            if matches and expected.issubset(matches[0].get("tools", {})):
                print(json.dumps({"mcp": {"name": matches[0]["name"], "tools": list(matches[0]["tools"])}}, ensure_ascii=False))
                server = matches[0]["name"]
                def call(tool: str, arguments: dict, *, error: bool = False, thread: str = thread_id) -> dict:
                    result = rpc("mcpServer/tool/call", {"threadId": thread, "server": server, "tool": tool, "arguments": arguments})
                    if bool(result.get("isError")) != error:
                        raise RuntimeError(f"Unexpected {tool} success/error status: {result}")
                    if not result.get("content") or result["content"][0].get("type") != "text":
                        raise RuntimeError(f"Missing text content from {tool}")
                    return json.loads(result["content"][0]["text"])
                with tempfile.TemporaryDirectory(prefix=".sro-host-fixture-", dir=workspace) as temporary:
                    target = Path(temporary) / "fixture.txt"
                    target.write_text("中文🧭abcdef\n" + ("fixture filler\n" * 700) + "Synthetic evidence: ORCHID-571\n", encoding="utf-8")
                    call("sro_card", {"path": str(target)})
                    call("sro_decide", {"path": str(target)})
                    preview = call("sro_preview", {"path": str(target)})["preview_pack"]
                    artifact, raw_ref = preview["artifact_id"], preview["raw_ref"]
                    evidence = call("sro_read", {"target": {"artifact_id": artifact}, "mode": "focus", "hint": {"goal": "Find synthetic evidence", "needles": ["ORCHID"]}})
                    if "ORCHID-571" not in json.dumps(evidence, ensure_ascii=False):
                        raise RuntimeError("Synthetic evidence missing from sro_read")
                    original = call("sro_raw", {"raw_ref": raw_ref, "selector": "ORCHID"})
                    if "ORCHID-571" not in json.dumps(original, ensure_ascii=False):
                        raise RuntimeError("Synthetic evidence missing from sro_raw")
                    ranged = call("sro_raw", {"raw_ref": raw_ref, "range": {"start": 0, "end": 3}})
                    if ranged.get("raw", {}).get("content") != "中文🧭":
                        raise RuntimeError("Unicode raw range did not use exclusive character offsets")
                    other_thread = rpc("thread/start", {"cwd": str(workspace), "ephemeral": True})["thread"]["id"]
                    deadline = time.monotonic() + 20
                    while True:
                        other_inventory = rpc("mcpServerStatus/list", {"threadId": other_thread})
                        if any(item.get("name") == server and expected.issubset(item.get("tools", {})) for item in other_inventory.get("data", [])):
                            break
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Second thread MCP server was not ready")
                        time.sleep(0.25)
                    call("sro_raw", {"raw_ref": raw_ref}, error=True, thread=other_thread)
                    call("sro_trace", {})
                    target.write_text(target.read_text(encoding="utf-8").replace("ORCHID-571", "ORCHID-572"), encoding="utf-8")
                    call("sro_raw", {"raw_ref": raw_ref}, error=True)
                    call("sro_preview", {"path": str(workspace.parent / "sro-outside.txt")}, error=True)
                print(json.dumps({"host_calls": sorted(expected), "unicode_raw": "passed", "cross_thread_raw": "rejected", "source_change": "stale raw rejected", "outside_workspace": "rejected",
                                  "project_trust": "not inspected directly; project-local MCP is active",
                                  "hook_trust": "not inspected; review hooks separately before claiming automatic interception"}))
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(f"SparseRead tools were not loaded for trusted project: {inventory}\n" + "".join(diagnostics))
            time.sleep(0.25)
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        schema_temp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
