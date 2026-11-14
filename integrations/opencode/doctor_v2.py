#!/usr/bin/env python3
"""Exercise an installed V2 plugin through an isolated real OpenCode host.

The local scripted provider is a transport fixture, not a model-quality test.
Only generated fixture text is submitted to it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def check(command: list[str], workspace: Path, *, global_install: bool = False) -> None:
    config_dir = workspace if global_install else workspace / ".opencode"
    plugin = config_dir / "plugins" / "sparseread"
    config = json.loads((config_dir / "sparseread.json").read_text(encoding="utf-8"))
    observed: dict[str, object] = {}

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            tools = request.get("tools", [])
            observed["tools"] = [item.get("function", {}).get("name", item.get("name")) for item in tools]
            results = [m for m in request.get("messages", []) if m.get("role") == "tool"]
            if results:
                observed["result"] = results[-1].get("content", "")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()

            def chunk(delta: dict, finish: str | None = None) -> None:
                payload = {"id": "fixture", "object": "chat.completion.chunk", "created": 1,
                           "model": "scripted", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                self.wfile.write(("data: " + json.dumps(payload) + "\n\n").encode())
            chunk({"role": "assistant"})
            if not results:
                chunk({"tool_calls": [{"index": 0, "id": "call_sro_doctor", "type": "function", "function": {
                    "name": "sro_preview", "arguments": json.dumps({"path": "fixture.txt"})}}]})
                chunk({}, "tool_calls")
            else:
                chunk({"content": "SRO_DOCTOR_COMPLETE"})
                chunk({}, "stop")
            self.wfile.write(b"data: [DONE]\n\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="sparseread-opencode-doctor-") as name:
            root = Path(name)
            test_workspace = root / "workspace"
            test_workspace.mkdir()
            test_config = root / "xdg_config_home" / "opencode" if global_install else test_workspace / ".opencode"
            plugin_target = test_config / "plugins" / "sparseread"
            shutil.copytree(plugin, plugin_target)
            if global_install:
                shutil.copytree(config_dir / "sparseread" / "runtime" / "opencode", test_config / "sparseread" / "runtime" / "opencode", symlinks=True)
            if not global_install:
                config["projectRoot"] = str(test_workspace)
            (test_config / "sparseread.json").write_text(json.dumps(config), encoding="utf-8")
            (test_workspace / "fixture.txt").write_text("SparseRead doctor fixture.\n" * 200, encoding="utf-8")
            host_config = {
                "share": "disabled", "model": "fixture/scripted",
                "providers": {"fixture": {"package": "@opencode/ai/providers/openai-compatible", "settings": {
                    "apiKey": "local-placeholder", "baseURL": f"http://127.0.0.1:{server.server_port}/v1", "timeout": 10000},
                    "models": {"scripted": {"name": "SparseRead doctor fixture"}}}},
                "permissions": [{"action": "*", "resource": "*", "effect": "allow"}],
            }
            (test_workspace / "opencode.json").write_text(json.dumps(host_config), encoding="utf-8")
            env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT") if key in os.environ}
            env["HOME"] = str(root / "home")
            for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
                env[variable] = str(root / variable.lower())
            env["TMPDIR"] = str(root / "tmp")
            env["NO_PROXY"] = "localhost,127.0.0.1"
            for variable in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "TMPDIR"):
                Path(env[variable]).mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-q"], cwd=test_workspace, env=env, capture_output=True, check=True, timeout=10)
            result = subprocess.run([*command, "run", "--standalone", "--format", "json", "--model", "fixture/scripted", "Run the local SparseRead doctor fixture."],
                                    cwd=test_workspace, env=env, capture_output=True, text=True, timeout=90)
            events = []
            for line in result.stdout.splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            completed = any(e.get("type") == "tool_use" and e.get("part", {}).get("tool") == "sro_preview"
                            and e.get("part", {}).get("state", {}).get("status") == "completed" for e in events)
            expected = {"sro_preview", "sro_read", "sro_raw", "sro_card", "sro_trace"}
            try:
                preview = json.loads(str(observed.get("result", ""))).get("preview_pack", {})
                valid_preview = bool(preview.get("artifact_id")) and not preview.get("error")
            except (ValueError, TypeError, AttributeError):
                valid_preview = False
            if result.returncode or not completed or not expected.issubset(set(observed.get("tools", []))) or not valid_preview:
                statuses = [(e.get("part", {}).get("tool"), e.get("part", {}).get("state", {}).get("status"))
                            for e in events if e.get("type") == "tool_use"]
                raise RuntimeError(f"OpenCode host did not register and complete the synthetic sro_preview call (exit={result.returncode}, tools={observed.get('tools', [])}, calls={statuses})")
            print("[doctor] OpenCode V2 host registered five tools and completed synthetic sro_preview (scripted local provider; not a real-model test)")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
