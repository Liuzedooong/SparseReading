from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
INSTALLER_PATH = ROOT / "scripts" / "install_sparseread.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("install_sparseread_for_test", INSTALLER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_require_command_falls_back_to_windows_cmd_suffix(monkeypatch, tmp_path: Path) -> None:
    installer = load_installer()
    npm_cmd = tmp_path / "npm.cmd"
    npm_cmd.write_text("@echo off\n", encoding="utf-8")
    npm_cmd.chmod(0o755)

    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(installer.os, "name", "nt")

    # Windows PATHEXT lookup may return the canonical extension case (npm.CMD);
    # the extension is case-insensitive on Windows, so compare normalized names.
    assert Path(installer.require_command("npm")).name.lower() == "npm.cmd"


def test_npm_install_and_build_uses_resolved_command(monkeypatch, tmp_path: Path) -> None:
    installer = load_installer()
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    calls: list[list[str]] = []

    monkeypatch.setattr(installer, "require_command", lambda *_args, **_kwargs: "C:/node/npm.cmd")

    def fake_run(cmd: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(installer, "run", fake_run)

    installer.npm_install_and_build(tmp_path, dry_run=False)

    # .cmd files are invoked directly (not wrapped in cmd.exe /c) because
    # Windows CreateProcess can launch .cmd files natively by full path.
    assert calls == [
        ["C:/node/npm.cmd", "ci", "--ignore-scripts"],
        ["C:/node/npm.cmd", "run", "build"],
    ]


def test_bridge_command_uses_managed_python() -> None:
    installer = load_installer()
    python = Path("C:/Users/me/.sparseread/Scripts/python.exe")

    command = installer.bridge_command(python)

    assert command == [str(python)]


def test_bridge_invocation_appends_module_to_managed_python() -> None:
    installer = load_installer()
    python = Path("/opt/sparseread/bin/python")

    command = installer.bridge_invocation(python, "-m", "sparseread_openclaw.bridge")

    assert command == [str(python), "-m", "sparseread_openclaw.bridge"]


def test_resolve_python_rejects_an_explicit_old_interpreter(monkeypatch) -> None:
    installer = load_installer()
    monkeypatch.setattr(installer, "python_version", lambda _python: (3, 10))

    try:
        installer.resolve_python("/usr/bin/python3.10")
    except SystemExit as exc:
        assert "requires Python 3.11+" in str(exc)
        assert "selected interpreter" in str(exc)
    else:
        raise AssertionError("expected an explicit Python 3.10 interpreter to be rejected")


def test_resolve_python_uses_uv_managed_interpreter_when_default_is_old(monkeypatch) -> None:
    installer = load_installer()
    versions = {"/usr/bin/python3.9": (3, 9), "/opt/uv/python3.12": (3, 12)}
    monkeypatch.setattr(installer.sys, "executable", "/usr/bin/python3.9")
    monkeypatch.setattr(installer, "python_version", lambda python: versions[python])
    monkeypatch.setattr(installer.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    def fake_run(cmd, **_kwargs):
        assert cmd == ["/usr/bin/uv", "python", "find", "3.12"]
        return subprocess.CompletedProcess(cmd, 0, "/opt/uv/python3.12\n", "")

    monkeypatch.setattr(installer.subprocess, "run", fake_run)

    assert installer.resolve_python() == "/opt/uv/python3.12"


def test_merge_json_rejects_invalid_existing_config(tmp_path: Path) -> None:
    installer = load_installer()
    config = tmp_path / "settings.json"
    config.write_text("{invalid", encoding="utf-8")

    try:
        installer.merge_json(config, {"enabled": True}, dry_run=False)
    except SystemExit as exc:
        assert "existing JSON config is invalid" in str(exc)
    else:
        raise AssertionError("expected invalid JSON config to fail safely")


def test_install_python_runtime_can_skip_optional_reader_dependencies(monkeypatch, tmp_path: Path) -> None:
    installer = load_installer()
    calls: list[list[str]] = []
    monkeypatch.setattr(installer, "command_spec", lambda *_args, **_kwargs: installer.CommandSpec("uv"))

    def fake_run(cmd: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(installer, "run", fake_run)

    installer.install_python_runtime(
        tmp_path / "runtime",
        tmp_path / "adapter",
        python="python3.12",
        dry_run=True,
        reader_extras="none",
    )

    pip_install = calls[-1]
    assert "pymupdf>=1.25.0" not in pip_install
    assert "openpyxl>=3.1.0,<4.0.0" not in pip_install


def test_public_install_mode_auto_maps_to_internal_defaults() -> None:
    installer = load_installer()

    profile = installer.install_profile(SimpleNamespace(sparseread_mode="auto"))

    assert profile.policy == "auto"
    assert profile.mode == "auto"
    assert profile.openclaw_hook_mode == "enforce"


def test_public_install_mode_advisory_disables_openclaw_interception() -> None:
    installer = load_installer()

    profile = installer.install_profile(SimpleNamespace(sparseread_mode="advisory"))

    assert profile.policy == "advisory"
    assert profile.mode == "auto"
    assert profile.openclaw_hook_mode == "prompt"


def test_installer_help_only_exposes_public_sparse_read_mode() -> None:
    proc = subprocess.run(
        [sys.executable, str(INSTALLER_PATH), "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    assert "--sparseread-mode" in proc.stdout
    assert "--policy" not in proc.stdout
    assert "--openclaw-hook-mode" not in proc.stdout
    assert " --mode " not in proc.stdout


def test_install_opencode_writes_persistent_workspace_config(monkeypatch, tmp_path: Path) -> None:
    installer = load_installer()
    workspace = tmp_path / "workspace"

    monkeypatch.setattr(installer, "command_spec", lambda *_args, **_kwargs: installer.CommandSpec("/bin/true"))
    monkeypatch.setattr(installer, "opencode_major", lambda *_args: 1)
    monkeypatch.setattr(installer, "npm_install_and_build", lambda *_args, **_kwargs: None)
    managed_python = tmp_path / "managed" / "bin" / "python"
    monkeypatch.setattr(installer, "install_python_runtime", lambda *_args, **_kwargs: managed_python)
    def fake_install_plugin(plugin_target, *, dry_run):  # noqa: ARG001
        plugin_target.parent.mkdir(parents=True, exist_ok=True)
        plugin_target.write_text("// mock plugin\n", encoding="utf-8")

    monkeypatch.setattr(installer, "install_opencode_plugin_file", fake_install_plugin)

    installer.install_opencode(
        SimpleNamespace(
            opencode_workspace=str(workspace),
            opencode_cmd="opencode",
            sparseread_mode="auto",
            skip_build=True,
            dry_run=False,
        )
    )

    plugin_target, config_target = installer.opencode_workspace_paths(workspace.resolve())
    config = json.loads(config_target.read_text(encoding="utf-8"))

    assert plugin_target.exists()
    assert config["projectRoot"] == str(workspace.resolve())
    assert config["bridgeModule"] == "sparseread_opencode.bridge"
    assert config["bridgeProtocol"] == "1.0"
    assert config["policy"] == "auto"
    assert config["mode"] == "auto"
    assert isinstance(config["bridgeCommand"], list)
    installer.validate_opencode_workspace(workspace.resolve())
    assert not (workspace / ".opencode" / "sparseread.env").exists()


def test_openclaw_install_patch_defaults_enforce_hook_mode(monkeypatch, tmp_path: Path) -> None:
    installer = load_installer()
    calls: list[list[str]] = []
    checked_calls: list[bool] = []
    patches: list[dict] = []

    monkeypatch.setattr(installer, "command_spec", lambda *_args, **_kwargs: installer.CommandSpec("/bin/true"))
    monkeypatch.setattr(installer, "npm_install_and_build", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(installer, "install_python_runtime", lambda *_args, **_kwargs: tmp_path / "runtime" / "bin" / "python")
    monkeypatch.setattr(installer, "npm_pack", lambda *_args, **_kwargs: tmp_path / "sparseread-openclaw.tgz")

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if "plugins" in cmd and ("install" in cmd or "enable" in cmd):
            checked_calls.append(kwargs.get("check", True))
        if cmd[-3:] == ["config", "patch", "--stdin"]:
            patches.append(json.loads(kwargs["input_text"]))
        if cmd[-5:] == ["plugins", "inspect", "sparseread-openclaw", "--runtime", "--json"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                json.dumps(
                    {
                        "status": "loaded",
                        "plugin": {"rootDir": str(tmp_path / "installed-openclaw")},
                        "toolNames": list(installer.OPENCLAW_RUNTIME_TOOLS),
                        "hookCount": 5,
                        "typedHooks": [
                            {"name": "before_prompt_build"},
                            {"name": "before_tool_call"},
                            {"name": "after_tool_call"},
                            {"name": "llm_output"},
                            {"name": "agent_end"},
                        ],
                    }
                ),
                "",
            )
        return subprocess.CompletedProcess(cmd, 0, "{}", "")

    monkeypatch.setattr(installer, "run", fake_run)

    installer.install_openclaw(
        SimpleNamespace(
            openclaw_cmd="openclaw",
            openclaw_profile="",
            openclaw_workspace=str(tmp_path),
            sparseread_mode="auto",
            skip_build=True,
            dry_run=False,
        )
    )

    entry = patches[0]["plugins"]["entries"]["sparseread-openclaw"]
    config = entry["config"]
    assert config["hookMode"] == "enforce"
    assert config["bridgeProtocol"] == "1.0"
    assert entry["hooks"]["allowPromptInjection"] is True
    assert entry["hooks"]["allowConversationAccess"] is True
    assert checked_calls == [True, True]
    assert any(cmd[-2:] == ["sparseread-openclaw", "--force"] for cmd in calls)
    assert any(cmd[-3:] == ["registry", "--refresh", "--json"] for cmd in calls)


def test_openclaw_install_patch_advisory_mode_has_no_before_tool_call_policy(monkeypatch, tmp_path: Path) -> None:
    installer = load_installer()
    patches: list[dict] = []

    monkeypatch.setattr(installer, "command_spec", lambda *_args, **_kwargs: installer.CommandSpec("/bin/true"))
    monkeypatch.setattr(installer, "npm_install_and_build", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(installer, "install_python_runtime", lambda *_args, **_kwargs: tmp_path / "runtime" / "bin" / "python")
    monkeypatch.setattr(installer, "npm_pack", lambda *_args, **_kwargs: tmp_path / "sparseread-openclaw.tgz")

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        if cmd[-3:] == ["config", "patch", "--stdin"]:
            patches.append(json.loads(kwargs["input_text"]))
        if cmd[-5:] == ["plugins", "inspect", "sparseread-openclaw", "--runtime", "--json"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                json.dumps(
                    {
                        "status": "loaded",
                        "plugin": {"rootDir": str(tmp_path / "installed-openclaw")},
                        "toolNames": list(installer.OPENCLAW_RUNTIME_TOOLS),
                        "hookCount": 2,
                        "hookNames": ["before_prompt_build", "agent_end"],
                    }
                ),
                "",
            )
        return subprocess.CompletedProcess(cmd, 0, "{}", "")

    monkeypatch.setattr(installer, "run", fake_run)

    installer.install_openclaw(
        SimpleNamespace(
            openclaw_cmd="openclaw",
            openclaw_profile="",
            openclaw_workspace=str(tmp_path),
            sparseread_mode="advisory",
            skip_build=True,
            dry_run=False,
        )
    )

    entry = patches[0]["plugins"]["entries"]["sparseread-openclaw"]
    assert entry["config"]["policy"] == "advisory"
    assert entry["config"]["mode"] == "auto"
    assert entry["config"]["hookMode"] == "prompt"
    assert entry["hooks"] == {"allowPromptInjection": True, "allowConversationAccess": True}


def test_validate_openclaw_runtime_accepts_hookless_production_payload() -> None:
    installer = load_installer()
    payload = {
        "status": "loaded",
        "plugin": {"rootDir": "/tmp/sparseread-installed-openclaw"},
        "toolNames": list(installer.OPENCLAW_RUNTIME_TOOLS),
        "hookCount": 0,
        "hookNames": [],
    }

    installer.validate_openclaw_runtime(json.dumps(payload), hook_mode="off")


def test_validate_openclaw_runtime_accepts_prompt_only_payload() -> None:
    installer = load_installer()
    payload = {
        "status": "loaded",
        "plugin": {"rootDir": "/tmp/sparseread-installed-openclaw"},
        "toolNames": list(installer.OPENCLAW_RUNTIME_TOOLS),
        "hookCount": 1,
        "hookNames": ["before_prompt_build"],
    }

    installer.validate_openclaw_runtime(json.dumps(payload), hook_mode="prompt")


def test_validate_openclaw_runtime_accepts_enforce_payload() -> None:
    installer = load_installer()
    payload = {
        "status": "loaded",
        "plugin": {"rootDir": "/tmp/sparseread-installed-openclaw"},
        "toolNames": list(installer.OPENCLAW_RUNTIME_TOOLS),
        "hookCount": 3,
        "typedHooks": [
            {"name": "before_prompt_build"},
            {"name": "before_tool_call"},
            {"name": "after_tool_call"},
        ],
    }

    installer.validate_openclaw_runtime(json.dumps(payload), hook_mode="enforce")


def test_validate_openclaw_runtime_rejects_enforce_without_before_tool_call() -> None:
    installer = load_installer()
    payload = {
        "status": "loaded",
        "plugin": {"rootDir": "/tmp/sparseread-installed-openclaw"},
        "toolNames": list(installer.OPENCLAW_RUNTIME_TOOLS),
        "hookCount": 2,
        "typedHooks": [{"name": "before_prompt_build"}, {"name": "after_tool_call"}],
    }

    try:
        installer.validate_openclaw_runtime(json.dumps(payload), hook_mode="enforce")
    except SystemExit as exc:
        assert "must register before_tool_call" in str(exc)
    else:
        raise AssertionError("expected enforce mode without before_tool_call to fail doctor")


def test_validate_openclaw_runtime_rejects_prompt_native_lifecycle_hooks() -> None:
    installer = load_installer()
    payload = {
        "status": "loaded",
        "plugin": {"rootDir": "/tmp/sparseread-installed-openclaw"},
        "toolNames": list(installer.OPENCLAW_RUNTIME_TOOLS),
        "hookCount": 2,
        "hookNames": ["before_prompt_build", "before_tool_call"],
    }

    try:
        installer.validate_openclaw_runtime(json.dumps(payload), hook_mode="prompt")
    except SystemExit as exc:
        assert "must not register native tool lifecycle hooks" in str(exc)
    else:
        raise AssertionError("expected prompt mode native lifecycle hook to fail doctor")


def test_validate_openclaw_runtime_rejects_duplicate_sparse_read_plugins() -> None:
    installer = load_installer()
    payload = {
        "status": "loaded",
        "plugin": {"rootDir": "/tmp/sparseread-installed-openclaw"},
        "toolNames": list(installer.OPENCLAW_RUNTIME_TOOLS),
        "hookCount": 0,
        "hookNames": [],
        "diagnostics": [{"message": "duplicate plugin id resolved by explicit config-selected plugin"}],
    }

    try:
        installer.validate_openclaw_runtime(json.dumps(payload), hook_mode="off")
    except SystemExit as exc:
        assert "duplicate SparseRead plugins" in str(exc)
    else:
        raise AssertionError("expected duplicate plugin diagnostic to fail doctor")


def test_opencode_detects_exact_supported_major(monkeypatch) -> None:
    installer = load_installer()
    monkeypatch.setattr(installer, "command_spec", lambda *_a, **_k: installer.CommandSpec("opencode"))
    monkeypatch.setattr(installer, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "2.3.0\n", ""))
    assert installer.opencode_major("opencode") == 2
    monkeypatch.setattr(installer, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "3.0.0\n", ""))
    import pytest
    with pytest.raises(SystemExit, match="supported OpenCode major"):
        installer.opencode_major("opencode")


def test_opencode_v2_install_is_idempotent_and_preserves_other_plugins(monkeypatch, tmp_path: Path) -> None:
    installer = load_installer()
    source = tmp_path / "build"
    (source / "dist" / ".sparseread-transport").mkdir(parents=True)
    (source / "dist" / "v2.js").write_text("// v2", encoding="utf-8")
    (source / "dist" / ".sparseread-transport" / "transport.js").write_text("// transport", encoding="utf-8")
    sdk = source / "node_modules" / "@opencode" / "plugin"
    sdk.mkdir(parents=True)
    (sdk / "package.json").write_text('{}', encoding="utf-8")
    (source / "package.json").write_text('{"version":"0.1.3"}', encoding="utf-8")
    monkeypatch.setattr(installer, "OPENCODE_PLUGIN", source)
    plugins = tmp_path / "workspace" / ".opencode" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "other.js").write_text("keep", encoding="utf-8")
    legacy = plugins / "sparseread.js"
    legacy.write_text("// SparseReadOpenCodePlugin", encoding="utf-8")
    installer.install_opencode_v2(legacy, dry_run=False)
    installer.install_opencode_v2(legacy, dry_run=False)
    assert not legacy.exists()
    assert (plugins / "other.js").read_text() == "keep"
    assert json.loads((plugins / "sparseread" / "package.json").read_text())["version"] == "0.1.3"
    assert (plugins / "sparseread" / ".sparseread-transport" / "transport.js").exists()


def test_opencode_v2_refuses_unmanaged_legacy(monkeypatch, tmp_path: Path) -> None:
    installer = load_installer()
    legacy = tmp_path / "plugins" / "sparseread.js"
    legacy.parent.mkdir()
    legacy.write_text("// unrelated user plugin", encoding="utf-8")
    import pytest
    with pytest.raises(SystemExit, match="unmanaged plugin"):
        installer.install_opencode_v2(legacy, dry_run=False)
    assert legacy.read_text() == "// unrelated user plugin"


def test_opencode_install_failure_restores_config(monkeypatch, tmp_path: Path) -> None:
    import pytest
    installer = load_installer()
    workspace = tmp_path / "workspace"
    config = workspace / ".opencode" / "sparseread.json"
    config.parent.mkdir(parents=True)
    old = '{"policy": "observe", "custom": "keep"}\n'
    config.write_text(old, encoding="utf-8")
    monkeypatch.setattr(installer, "opencode_major", lambda *_args: 2)
    monkeypatch.setattr(installer, "install_python_runtime", lambda *_args, **_kwargs: tmp_path / "python")
    def fail(*_args, **_kwargs):
        raise RuntimeError("simulated install failure")
    monkeypatch.setattr(installer, "install_opencode_v2", fail)
    args = SimpleNamespace(opencode_workspace=str(workspace), opencode_cmd="opencode", sparseread_mode="auto", skip_build=True, dry_run=False)
    with pytest.raises(RuntimeError, match="simulated"):
        installer.install_opencode(args)
    assert config.read_text(encoding="utf-8") == old


def test_opencode_rejects_dangling_symlink_before_runtime(monkeypatch, tmp_path: Path) -> None:
    import pytest
    installer = load_installer()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    try:
        (workspace / ".opencode").symlink_to(tmp_path / "missing", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    monkeypatch.setattr(installer, "opencode_major", lambda *_args: 2)
    monkeypatch.setattr(installer, "install_python_runtime", lambda *_args, **_kwargs: pytest.fail("runtime must not start"))
    args = SimpleNamespace(opencode_workspace=str(workspace), opencode_cmd="opencode", sparseread_mode="auto", skip_build=True, dry_run=False)
    with pytest.raises(SystemExit, match="symlink"):
        installer.install_opencode(args)


def test_opencode_doctor_failure_restores_runtime_and_entry(monkeypatch, tmp_path: Path) -> None:
    import pytest
    installer = load_installer()
    workspace = tmp_path / "workspace"
    runtime = installer.opencode_runtime_dir(workspace)
    runtime.mkdir(parents=True)
    (runtime / "old").write_text("original runtime")
    plugin = workspace / ".opencode" / "plugins" / "sparseread"
    plugin.mkdir(parents=True)
    (plugin / "package.json").write_text('{"name":"sparseread-opencode-v2"}')
    (plugin / "old").write_text("original plugin")
    config = workspace / ".opencode" / "sparseread.json"
    config.write_text('{"custom":"original"}\n')
    monkeypatch.setattr(installer, "opencode_major", lambda *_args: 2)
    def runtime_install(target, *_args, upgrade_backup, **_kwargs):
        target.rename(upgrade_backup)
        target.mkdir()
        (target / "new").write_text("new runtime")
        return target / "bin" / "python"
    def plugin_install(_legacy, **_kwargs):
        (plugin / "old").unlink()
        (plugin / "new").write_text("new plugin")
    def fail_doctor(_args):
        raise RuntimeError("doctor failed")
    monkeypatch.setattr(installer, "install_python_runtime", runtime_install)
    monkeypatch.setattr(installer, "install_opencode_v2", plugin_install)
    monkeypatch.setattr(installer, "doctor_opencode", fail_doctor)
    args = SimpleNamespace(opencode_workspace=str(workspace), opencode_cmd="opencode", sparseread_mode="auto", skip_build=True, dry_run=False, doctor=True)
    with pytest.raises(RuntimeError, match="doctor failed"):
        installer.install_opencode(args)
    assert (runtime / "old").read_text() == "original runtime"
    assert (plugin / "old").read_text() == "original plugin"
    assert not (plugin / "new").exists()
    assert config.read_text() == '{"custom":"original"}\n'


def test_opencode_transport_replacement_does_not_write_through_hardlink(monkeypatch, tmp_path: Path) -> None:
    installer = load_installer()
    source = tmp_path / "source" / "dist"
    (source / ".sparseread-transport").mkdir(parents=True)
    (source / "sparseread.js").write_text("SparseReadOpenCodePlugin")
    (source / ".sparseread-transport" / "transport.js").write_text("SparseReadBridge new")
    monkeypatch.setattr(installer, "OPENCODE_PLUGIN", source.parent)
    plugins = tmp_path / "plugins"
    transport = plugins / ".sparseread-transport" / "transport.js"
    transport.parent.mkdir(parents=True)
    transport.write_text("SparseReadBridge old")
    linked = tmp_path / "other"
    import os
    try:
        os.link(transport, linked)
    except OSError:
        import pytest
        pytest.skip("hardlink creation is unavailable")
    installer.install_opencode_plugin_file(plugins / "sparseread.js", dry_run=False)
    assert linked.read_text() == "SparseReadBridge old"
    assert transport.read_text() == "SparseReadBridge new"


def test_opencode_retains_backups_if_rollback_fails(monkeypatch, tmp_path: Path) -> None:
    import pytest
    installer = load_installer()
    workspace = tmp_path / "workspace"
    runtime = installer.opencode_runtime_dir(workspace)
    runtime.mkdir(parents=True)
    (runtime / "old").write_text("old runtime")
    config = workspace / ".opencode" / "sparseread.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"custom":"original"}\n')
    monkeypatch.setattr(installer, "opencode_major", lambda *_args: 2)
    def runtime_install(target, *_args, upgrade_backup, **_kwargs):
        target.rename(upgrade_backup)
        target.mkdir()
        return target / "bin" / "python"
    monkeypatch.setattr(installer, "install_python_runtime", runtime_install)
    monkeypatch.setattr(installer, "install_opencode_v2", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(installer, "doctor_opencode", lambda *_args: (_ for _ in ()).throw(RuntimeError("doctor failed")))
    original_replace = Path.replace
    def fail_restore(self, target):
        if self.name == "config" and self.parent.name.startswith(".sparseread-rollback-"):
            raise OSError("simulated restore failure")
        return original_replace(self, target)
    monkeypatch.setattr(Path, "replace", fail_restore)
    args = SimpleNamespace(opencode_workspace=str(workspace), opencode_cmd="opencode", sparseread_mode="auto", skip_build=True, dry_run=False, doctor=True)
    with pytest.raises(RuntimeError, match="backups retained"):
        installer.install_opencode(args)
    backups = list(runtime.parent.glob(".sparseread-rollback-*/runtime/old"))
    assert len(backups) == 1 and backups[0].read_text() == "old runtime"
