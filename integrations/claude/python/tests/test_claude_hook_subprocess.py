"""Exercise the installed shape: each hook event starts a new process."""
import json
import os
import subprocess
import sys
from pathlib import Path


def hook(workspace: Path, event: dict, *args: str):
    env = os.environ.copy()
    if os.environ.get("SRO_TEST_INSTALLED"):
        env.pop("PYTHONPATH", None)
    else:
        repo = Path(__file__).resolve().parents[4]
        env["PYTHONPATH"] = os.pathsep.join([str(repo / "packages/sparseread-core/src"), str(repo / "integrations/claude/python/src")])
    return subprocess.run([sys.executable, "-m", "sparseread_claude.hook", "--single", "--workspace", str(workspace), *args],
                          input=json.dumps(event), capture_output=True, text=True, env=env)


def payload(proc):
    return json.loads(proc.stdout).get("hookSpecificOutput", {})


def test_subprocess_session_once_and_session_isolation(tmp_path):
    source = tmp_path / "large.txt"
    source.write_text("x" * 14000)
    event = {"hook_event_name": "PreToolUse", "session_id": "session-a", "tool_name": "Read", "tool_input": {"file_path": str(source)}}
    first = hook(tmp_path, event)
    retry = hook(tmp_path, event)
    assert payload(first)["permissionDecision"] == "deny"
    assert "permissionDecision" not in payload(retry)
    event["session_id"] = "session-b"
    assert payload(hook(tmp_path, event))["permissionDecision"] == "deny"


def test_official_post_response_and_permission_neutral(tmp_path):
    source = tmp_path / "large.txt"
    source.write_text("x" * 14000)
    pre = {"hook_event_name": "PreToolUse", "session_id": "a", "tool_name": "Bash", "tool_input": {"command": "echo audit-only"}}
    assert "permissionDecision" not in payload(hook(tmp_path, pre))
    pre["tool_input"] = {"command": f"head -n 5 {source}"}
    assert "permissionDecision" not in payload(hook(tmp_path, pre))
    post = {"hook_event_name": "PostToolUse", "session_id": "a", "tool_name": "Bash", "tool_input": {"command": f"cat {source}"}, "tool_response": {"stdout": "x" * 14000, "stderr": ""}}
    result = payload(hook(tmp_path, post))
    assert "SparseRead tip" in result["additionalContext"]
    assert "updatedToolOutput" not in result


def test_advisory_never_denies(tmp_path):
    source = tmp_path / "large.txt"
    source.write_text("x" * 14000)
    event = {"hook_event_name": "PreToolUse", "session_id": "a", "tool_name": "Read", "tool_input": {"file_path": str(source)}}
    proc = hook(tmp_path, event, "--mode", "advisory")
    assert proc.returncode == 0
    assert "permissionDecision" not in payload(proc)


def test_concurrent_processes_claim_once_and_source_change_resets(tmp_path):
    import concurrent.futures
    source = tmp_path / "large.txt"
    source.write_text("x" * 14000)
    event = {"hook_event_name": "PreToolUse", "session_id": "same", "tool_name": "Read", "tool_input": {"file_path": str(source)}}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: payload(hook(tmp_path, event)).get("permissionDecision"), range(6)))
    assert results.count("deny") == 1 and results.count(None) == 5
    old = source.stat()
    source.write_text("y" * 14000)
    os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert payload(hook(tmp_path, event))["permissionDecision"] == "deny"


def test_missing_session_corrupt_state_and_expiry_fail_open(tmp_path):
    import time
    source = tmp_path / "large.txt"
    source.write_text("x" * 14000)
    event = {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": str(source)}}
    assert "permissionDecision" not in payload(hook(tmp_path, event))
    event["session_id"] = "one"
    assert payload(hook(tmp_path, event))["permissionDecision"] == "deny"
    state = tmp_path / ".sparseread" / "claude-hook" / "state.json"
    saved = json.loads(state.read_text())
    state.write_text("not-json")
    assert "permissionDecision" not in payload(hook(tmp_path, event))
    saved["redirects"] = {key: time.time() - 90000 for key in saved["redirects"]}
    state.write_text(json.dumps(saved))
    assert payload(hook(tmp_path, event))["permissionDecision"] == "deny"


def test_conservative_shell_only_unbounded_cat(tmp_path):
    source = tmp_path / "large.txt"
    source.write_text("x" * 14000)
    for i, command in enumerate((f"head -n 5 {source}", f"tail -n 5 {source}",
                                 f"grep x {source}", f"cat {source} | head -n 5",
                                 f"cat {source}; echo done", f"cat {source} {source}")):
        event = {"hook_event_name": "PreToolUse", "session_id": str(i), "tool_name": "Bash", "tool_input": {"command": command}}
        assert "permissionDecision" not in payload(hook(tmp_path, event))
    event = {"hook_event_name": "PreToolUse", "session_id": "cat", "tool_name": "Bash", "tool_input": {"command": f"cat {source}"}}
    assert payload(hook(tmp_path, event))["permissionDecision"] == "deny"


def test_state_symlinks_and_oversize_fail_open(tmp_path):
    source = tmp_path / "large.txt"
    source.write_text("x" * 14000)
    event = {"hook_event_name": "PreToolUse", "session_id": "one", "tool_name": "Read", "tool_input": {"file_path": str(source)}}
    directory = tmp_path / ".sparseread" / "claude-hook"
    directory.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    lock = directory / "state.lock"
    lock.symlink_to(outside)
    assert "permissionDecision" not in payload(hook(tmp_path, event))
    lock.unlink()
    state = directory / "state.json"
    state.symlink_to(outside)
    assert "permissionDecision" not in payload(hook(tmp_path, event))
    assert outside.read_text() == "keep"
    state.unlink()
    state.write_text("x" * 65537)
    assert "permissionDecision" not in payload(hook(tmp_path, event))


def test_workspaces_have_separate_redirects_and_bounded_state(tmp_path):
    import time
    source = tmp_path / "large.txt"
    source.write_text("x" * 14000)
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    event = {"hook_event_name": "PreToolUse", "session_id": "same", "tool_name": "Read", "tool_input": {"file_path": str(source)}}
    assert payload(hook(first, event))["permissionDecision"] == "deny"
    assert payload(hook(second, event))["permissionDecision"] == "deny"
    state = first / ".sparseread/claude-hook/state.json"
    state.write_text(json.dumps({"redirects": {str(i): time.time() for i in range(520)}}))
    event["session_id"] = "new"
    assert payload(hook(first, event))["permissionDecision"] == "deny"
    assert len(json.loads(state.read_text())["redirects"]) == 512


def test_ambiguous_boundary_whitespace_path_is_not_redirected(tmp_path):
    regular = tmp_path / "source.txt"
    spaced = tmp_path / "source.txt "
    regular.write_text("x" * 14000)
    spaced.write_text("different file")
    event = {"hook_event_name": "PreToolUse", "session_id": "one", "tool_name": "Read", "tool_input": {"file_path": str(spaced)}}
    assert "permissionDecision" not in payload(hook(tmp_path, event))
