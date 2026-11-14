#!/usr/bin/env python3
"""Install self-contained SparseRead adapters for existing agent CLIs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_PACKAGE = ROOT / "packages" / "sparseread-core"
OPENCODE_ADAPTER = ROOT / "integrations" / "opencode" / "python"
OPENCLAW_ADAPTER = ROOT / "integrations" / "openclaw" / "python"
CLAUDE_ADAPTER = ROOT / "integrations" / "claude" / "python"
HOST_ADAPTER = ROOT / "integrations" / "agent-tools" / "python"
CODEX_PLUGIN = ROOT / "integrations" / "codex" / "plugin" / "sparseread-codex"
PI_PLUGIN = ROOT / "integrations" / "pi" / "package"
OPENCODE_PLUGIN = ROOT / "integrations" / "opencode" / "plugin"
OPENCLAW_PLUGIN = ROOT / "integrations" / "openclaw" / "plugin"
BRIDGE_PROTOCOL_VERSION = "1.0"
MIN_PYTHON = (3, 11)
WINDOWS_COMMAND_SUFFIXES = (".cmd", ".exe", ".bat")
# .cmd files (e.g. npm.CMD) are batch scripts but subprocess.run() on Windows
# can launch them via the full path returned by shutil.which().  Only .bat
# files need explicit COMSPEC wrapping to avoid quoting conflicts.
WINDOWS_SHELL_EXTS: set[str] = set()
OPENCODE_RUNTIME_TOOLS = ("sro_preview", "sro_raw", "sro_card", "sro_read", "sro_trace")
OPENCLAW_RUNTIME_TOOLS = ("sro_preview", "sro_raw", "sro_card", "sro_read", "sro_decide", "sro_trace")
CLAUDE_RUNTIME_TOOLS = (
    "sro_preview",
    "sro_read",
    "sro_card",
    "sro_raw",
    "sro_decide",
    "sro_trace",
    "sro_preflight",
    "sro_usage",
)
READER_DEPENDENCIES = ("pymupdf>=1.25.0", "openpyxl>=3.1.0,<4.0.0")


@dataclass(frozen=True)
class CommandSpec:
    executable: str

    def argv(self, *args: str) -> list[str]:
        if is_windows_shell_script(self.executable):
            shell = os.environ.get("COMSPEC") or "cmd.exe"
            return [shell, "/d", "/s", "/c", subprocess.list2cmdline([self.executable, *args])]
        return [self.executable, *args]


@dataclass(frozen=True)
class InstallProfile:
    policy: str
    mode: str
    openclaw_hook_mode: str


def install_profile(args: argparse.Namespace) -> InstallProfile:
    """Map the user-facing SparseRead mode to internal adapter knobs.

    Public installs expose only two modes:
    - auto: gate-controlled interception for high-benefit reads.
    - advisory: prompt/tool guidance only; no OpenClaw native tool interception.

    The legacy internal flags remain accepted for old scripts, but are not
    shown in help or docs.
    """

    public_mode = getattr(args, "sparseread_mode", None) or "auto"
    if public_mode not in {"auto", "advisory"}:
        raise SystemExit(f"invalid SparseRead mode: {public_mode}")
    default_policy = "auto" if public_mode == "auto" else "advisory"
    default_hook_mode = "enforce" if public_mode == "auto" else "prompt"
    return InstallProfile(
        policy=getattr(args, "policy", None) or default_policy,
        mode=getattr(args, "mode", None) or "auto",
        openclaw_hook_mode=getattr(args, "openclaw_hook_mode", None) or default_hook_mode,
    )


def run(
    cmd: list[str],
    *,
    cwd: Path = ROOT,
    input_text: str | None = None,
    check: bool = True,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    print("$ " + " ".join(cmd), flush=True)
    if dry_run:
        return subprocess.CompletedProcess(cmd, 0, "", "")
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise SystemExit(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def require_command(name: str, *, install_hint: str = "") -> str:
    path = shutil.which(name)
    if path:
        return path
    if os.name == "nt" and not Path(name).suffix:
        for suffix in WINDOWS_COMMAND_SUFFIXES:
            path = shutil.which(f"{name}{suffix}")
            if path:
                return path
    suffix = f" {install_hint}" if install_hint else ""
    raise SystemExit(f"missing required command: {name}.{suffix}")


def python_version(python: str) -> tuple[int, int]:
    """Return the major/minor version for an interpreter selected by the user."""
    try:
        proc = subprocess.run(
            [python, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise SystemExit(f"cannot execute Python interpreter {python!r}: {exc}") from exc
    if proc.returncode != 0:
        raise SystemExit(
            f"cannot inspect Python interpreter {python!r}.\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    try:
        major, minor = (int(part) for part in proc.stdout.strip().split()[:2])
    except (ValueError, TypeError) as exc:
        raise SystemExit(f"Python interpreter {python!r} returned an invalid version: {proc.stdout!r}") from exc
    return major, minor


def resolve_python(python: str | None = None) -> str:
    """Select a compatible interpreter before creating any managed runtime."""
    requested = python or sys.executable
    version = python_version(requested)
    if version >= MIN_PYTHON:
        return requested
    if python:
        raise SystemExit(
            f"SparseRead requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+. "
            f"The selected interpreter {requested!r} is Python {version[0]}.{version[1]}."
        )

    uv_path = shutil.which("uv")
    if uv_path:
        probe = subprocess.run(
            [uv_path, "python", "find", "3.12"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        candidates = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
        if probe.returncode == 0 and candidates:
            candidate = candidates[-1]
            candidate_version = python_version(candidate)
            if candidate_version >= MIN_PYTHON:
                print(
                    f"[install] current Python is {version[0]}.{version[1]}; "
                    f"using uv-managed Python {candidate}"
                )
                return candidate

    raise SystemExit(
        f"SparseRead requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+. "
        f"The current interpreter is Python {version[0]}.{version[1]}. "
        "Install a compatible interpreter with `uv python install 3.12`, then "
        "rerun with `--python <path>` if it is not discoverable."
    )


def command_spec(name: str, *, install_hint: str = "") -> CommandSpec:
    return CommandSpec(require_command(name, install_hint=install_hint))


def openclaw_runtime_hook_names(payload: dict) -> set[str]:
    names: set[str] = set()
    for source in (payload, payload.get("plugin") if isinstance(payload.get("plugin"), dict) else {}):
        if not isinstance(source, dict):
            continue
        for key in ("hookNames", "hooks", "typedHooks"):
            items = source.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, str):
                    names.add(item)
                elif isinstance(item, dict) and isinstance(item.get("name"), str):
                    names.add(item["name"])
    return names


def is_windows_shell_script(path: str) -> bool:
    return Path(path).suffix.lower() in WINDOWS_SHELL_EXTS


def runtime_python(runtime_dir: Path) -> Path:
    scripts = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return runtime_dir / scripts / executable


def bridge_command(python: Path) -> list[str]:
    return [str(python)]


def bridge_invocation(python: Path, *args: str) -> list[str]:
    return CommandSpec(str(python)).argv(*args)


def opencode_runtime_dir(workspace: Path) -> Path:
    return workspace / ".sparseread" / "runtime" / "opencode"


def opencode_global_root() -> Path:
    override = os.environ.get("OPENCODE_CONFIG_DIR")
    if override:
        if not Path(override).is_absolute():
            raise SystemExit("OpenCode --global requires an absolute OPENCODE_CONFIG_DIR; set an absolute path or unset it.")
        return Path(override)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg).expanduser() if xdg and Path(xdg).is_absolute() else Path.home() / ".config") / "opencode"


def opencode_install_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    if getattr(args, "global_install", False):
        root = opencode_global_root()
        return root, root / "plugins" / "sparseread.js", root / "sparseread.json", root / "sparseread" / "runtime" / "opencode"
    root = Path(args.opencode_workspace or os.getcwd()).expanduser().resolve()
    legacy, config = opencode_workspace_paths(root)
    return root, legacy, config, opencode_runtime_dir(root)


def openclaw_runtime_dir(profile: str) -> Path:
    return openclaw_profile_config_path(profile).parent / "sparseread" / "runtime"


def claude_runtime_dir() -> Path:
    return Path.home() / ".sparseread" / "claude"


def claude_mcp_config(workspace: Path, python: Path, mode: str) -> dict[str, object]:
    return {
        "mcpServers": {
            "sparseread": {
                "command": str(python),
                "args": [
                    "-m",
                    "sparseread_claude.claude_mcp",
                    "--workspace",
                    str(workspace),
                    "--mode",
                    mode,
                ],
                "env": {"SRO_ENABLED": "1"},
            }
        }
    }


def claude_settings_config(workspace: Path, python: Path, mode: str = "auto") -> dict[str, object]:
    hook_entry = {
        "type": "command",
        "command": str(python),
        "args": ["-m", "sparseread_claude.hook", "--single", "--workspace", str(workspace), "--mode", mode],
    }
    return {
        "enabledMcpjsonServers": ["sparseread"],
        "hooks": {
            "PreToolUse": [
                {"matcher": "Read|Bash", "hooks": [hook_entry]},
            ],
            "PostToolUse": [
                {"matcher": "Read|Bash", "hooks": [hook_entry]},
            ],
        },
    }


def merge_json(path: Path, patch: dict[str, object], *, dry_run: bool) -> None:
    """Merge a JSON config file with a patch, preserving unrelated keys."""
    if dry_run:
        return
    payload: dict[str, object] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise SystemExit(f"cannot read existing JSON config {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"existing JSON config is invalid: {path}. "
                "Fix or back up the file before running the installer again."
            ) from exc
        if not isinstance(existing, dict):
            raise SystemExit(f"existing JSON config must contain an object: {path}")
        payload = existing
    for key, value in patch.items():
        if key == "hooks" and isinstance(value, dict) and isinstance(payload.get("hooks"), dict):
            hooks = dict(payload["hooks"])
            for event, entries in value.items():
                existing_entries = hooks.get(event)
                if not isinstance(existing_entries, list):
                    hooks[event] = entries
                    continue
                merged = list(existing_entries)
                for entry in entries:
                    if entry not in merged:
                        merged.append(entry)
                hooks[event] = merged
            payload["hooks"] = hooks
        elif key == "mcpServers" and isinstance(value, dict) and isinstance(payload.get("mcpServers"), dict):
            servers = dict(payload["mcpServers"])
            servers.update(value)
            payload["mcpServers"] = servers
        elif key == "enabledMcpjsonServers" and isinstance(value, list) and isinstance(payload.get("enabledMcpjsonServers"), list):
            merged = list(payload["enabledMcpjsonServers"])
            for item in value:
                if item not in merged:
                    merged.append(item)
            payload["enabledMcpjsonServers"] = merged
        else:
            payload[key] = value
    write_json(path, payload, ensure_ascii=False)


def merge_claude_settings(path: Path, patch: dict[str, object]) -> None:
    """Atomically replace only this adapter's hooks, preserving others."""
    payload: dict[str, object] = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"cannot read existing JSON config {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise SystemExit(f"existing JSON config must contain an object: {path}")
    hooks = payload.get("hooks")
    if hooks is None:
        hooks = {}
    if not isinstance(hooks, dict):
        raise SystemExit(f"existing hooks must be an object: {path}")
    patch_hooks = patch["hooks"]
    for event in ("PreToolUse", "PostToolUse"):
        entries = hooks.get(event, [])
        if not isinstance(entries, list):
            raise SystemExit(f"existing {event} hooks must be a list: {path}")
        cleaned = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                cleaned.append(entry)
                continue
            remaining = []
            for hook in entry["hooks"]:
                if isinstance(hook, dict):
                    arguments = hook.get("args")
                    text = str(hook.get("command") or "") + " " + (" ".join(map(str, arguments)) if isinstance(arguments, list) else "")
                    if "sparseread_claude.hook" in text:
                        continue
                remaining.append(hook)
            if remaining:
                cleaned.append({**entry, "hooks": remaining})
        hooks[event] = cleaned + patch_hooks[event]
    payload["hooks"] = hooks
    servers = payload.get("enabledMcpjsonServers", [])
    if not isinstance(servers, list):
        raise SystemExit(f"existing enabledMcpjsonServers must be a list: {path}")
    if "sparseread" not in servers:
        servers.append("sparseread")
    payload["enabledMcpjsonServers"] = servers
    write_json(path, payload, ensure_ascii=False)


def opencode_workspace_config(workspace: Path, python: Path, policy: str, mode: str) -> dict[str, object]:
    return {
        "projectRoot": str(workspace),
        "bridgeCommand": bridge_command(python),
        "bridgeModule": "sparseread_opencode.bridge",
        "bridgeProtocol": BRIDGE_PROTOCOL_VERSION,
        "policy": policy,
        "mode": mode,
    }


def write_text_atomic(path: Path, content: str) -> None:
    """Write a file beside its destination, then replace it atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        os.replace(temporary, path)
    except OSError as exc:
        raise SystemExit(f"cannot write {path}: {exc}") from exc
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink(missing_ok=True)


def write_json(path: Path, payload: dict[str, object], *, ensure_ascii: bool = True) -> None:
    write_text_atomic(path, json.dumps(payload, ensure_ascii=ensure_ascii, indent=2) + "\n")


def read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"{path} must contain a JSON object.")
    return payload


def openclaw_profile_config_path(profile: str) -> Path:
    base = Path.home() / (".openclaw" if not profile else f".openclaw-{profile}")
    return base / "openclaw.json"


def opencode_workspace_paths(workspace: Path) -> tuple[Path, Path]:
    return workspace / ".opencode" / "plugins" / "sparseread.js", workspace / ".opencode" / "sparseread.json"


def opencode_major(command: str) -> int:
    spec = command_spec(command)
    result = run(spec.argv("--version"), check=False)
    match = re.search(r"(?<!\d)(\d+)\.\d+\.\d+", result.stdout)
    if result.returncode or not match or int(match.group(1)) not in (1, 2):
        raise SystemExit("Cannot determine a supported OpenCode major version (1 or 2).")
    return int(match.group(1))


def validate_opencode_workspace(workspace: Path, major: int = 1, *, global_install: bool = False) -> None:
    plugin_target, config_target = (workspace / "plugins" / "sparseread.js", workspace / "sparseread.json") if global_install else opencode_workspace_paths(workspace)
    if major == 2:
        plugin_target = plugin_target.parent / "sparseread" / "package.json"
    if not plugin_target.exists():
        raise SystemExit(f"OpenCode plugin file is missing: {plugin_target}")
    if not config_target.exists():
        raise SystemExit(f"OpenCode config is missing: {config_target}")
    if global_install and not (plugin_target.parent / "global.json").is_file():
        raise SystemExit("OpenCode global plugin marker is missing.")
    config = read_json(config_target)
    if (global_install and "projectRoot" in config) or (not global_install and config.get("projectRoot") != str(workspace)):
        raise SystemExit(f"OpenCode config has unexpected projectRoot: {config.get('projectRoot')}")
    if config.get("bridgeModule") != "sparseread_opencode.bridge":
        raise SystemExit(f"OpenCode config has unexpected bridgeModule: {config.get('bridgeModule')}")
    if config.get("bridgeProtocol") != BRIDGE_PROTOCOL_VERSION:
        raise SystemExit(f"OpenCode config has unexpected bridgeProtocol: {config.get('bridgeProtocol')}")
    if config.get("policy") not in {"observe", "advisory", "enforce", "native", "auto"}:
        raise SystemExit(f"OpenCode config has invalid policy: {config.get('policy')}")
    if config.get("mode") not in {"auto", "bench_protocol", "force", "force_sro", "native", "advisory"}:
        raise SystemExit(f"OpenCode config has invalid mode: {config.get('mode')}")
    bridge_cmd = config.get("bridgeCommand")
    if (
        not isinstance(bridge_cmd, list)
        or not bridge_cmd
        or any(not isinstance(part, str) or not part.strip() for part in bridge_cmd)
    ):
        raise SystemExit(f"OpenCode config has invalid bridgeCommand: {bridge_cmd!r}")
    print(f"[doctor] opencode workspace config passed: {config_target}")


def validate_openclaw_runtime(stdout: str, *, hook_mode: str) -> None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"OpenClaw runtime inspect returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("OpenClaw runtime inspect must return a JSON object.")
    plugin = payload.get("plugin")
    if not isinstance(plugin, dict):
        raise SystemExit("OpenClaw runtime inspect must include plugin metadata.")
    root_dir = plugin.get("rootDir")
    if not isinstance(root_dir, str) or not root_dir.strip():
        raise SystemExit("OpenClaw runtime inspect did not report an installed plugin root.")
    if Path(root_dir).resolve() == OPENCLAW_PLUGIN.resolve():
        raise SystemExit("OpenClaw is still loading SparseRead from the source checkout instead of an installed package.")
    diagnostics = payload.get("diagnostics")
    if isinstance(diagnostics, list):
        for item in diagnostics:
            if not isinstance(item, dict):
                continue
            message = item.get("message")
            if isinstance(message, str) and "duplicate plugin id" in message.lower():
                raise SystemExit(f"OpenClaw runtime still reports duplicate SparseRead plugins: {message}")
    status = payload.get("status")
    if isinstance(status, str) and status.lower() != "loaded":
        raise SystemExit(f"OpenClaw runtime inspect reported non-loaded status: {status}")
    text = json.dumps(payload, sort_keys=True)
    missing = [tool for tool in OPENCLAW_RUNTIME_TOOLS if tool not in text]
    if missing:
        raise SystemExit(f"OpenClaw runtime inspect is missing SparseRead tools: {', '.join(missing)}")
    hook_names = openclaw_runtime_hook_names(payload)
    if hook_mode == "off":
        hook_count = payload.get("hookCount")
        hooks = payload.get("hooks")
        if isinstance(hook_count, int) and hook_count != 0:
            raise SystemExit(f"OpenClaw production install expected 0 hooks, got hookCount={hook_count}")
        if hook_names:
            raise SystemExit(f"OpenClaw production install expected no hookNames, got {hook_names}")
        if isinstance(hooks, list) and hooks:
            raise SystemExit(f"OpenClaw production install expected no runtime hooks, got {hooks}")
    if hook_mode == "prompt":
        disallowed = {"before_tool_call", "after_tool_call", "llm_output"} & hook_names
        if disallowed:
            raise SystemExit(
                "OpenClaw prompt install must not register native tool lifecycle hooks: "
                f"{sorted(disallowed)}"
            )
    if hook_mode == "enforce" and "before_tool_call" not in hook_names:
        raise SystemExit(
            "OpenClaw enforce install must register before_tool_call; "
            f"runtime hooks were {sorted(hook_names)}"
        )
    print("[doctor] openclaw runtime inspect passed")


def npm_install_and_build(plugin_dir: Path, *, dry_run: bool) -> None:
    npm_cmd = command_spec("npm")
    if (plugin_dir / "package-lock.json").exists():
        run(npm_cmd.argv("ci", "--ignore-scripts"), cwd=plugin_dir, dry_run=dry_run)
    else:
        run(npm_cmd.argv("install", "--ignore-scripts"), cwd=plugin_dir, dry_run=dry_run)
    run(npm_cmd.argv("run", "build"), cwd=plugin_dir, dry_run=dry_run)


def npm_pack(plugin_dir: Path, destination: Path, *, dry_run: bool) -> Path:
    npm_cmd = command_spec("npm")
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)
    proc = run(
        npm_cmd.argv("pack", "--json", "--pack-destination", str(destination)),
        cwd=plugin_dir,
        dry_run=dry_run,
    )
    if dry_run:
        return destination / "sparseread-plugin.tgz"
    payload = json.loads(proc.stdout)
    if (
        not isinstance(payload, list)
        or not payload
        or not isinstance(payload[0], dict)
        or not isinstance(payload[0].get("filename"), str)
    ):
        raise SystemExit(f"npm pack returned an unexpected payload: {proc.stdout}")
    return destination / payload[0]["filename"]


def install_python_runtime(
    runtime_dir: Path,
    adapter: Path,
    *,
    python: str,
    dry_run: bool,
    reader_extras: str = "all",
    upgrade_existing: bool = False,
    upgrade_backup: Path | None = None,
) -> Path:
    if reader_extras not in {"all", "none"}:
        raise SystemExit(f"invalid reader extras selection: {reader_extras}")
    if upgrade_existing and runtime_dir.exists() and not dry_run:
        if runtime_dir.is_symlink() or not (runtime_dir / "pyvenv.cfg").is_file():
            raise SystemExit(f"Refusing to replace unmanaged runtime: {runtime_dir}")
        resolved_python = Path(shutil.which(python) or python).resolve()
        if resolved_python.is_relative_to(runtime_dir.resolve()):
            raise SystemExit("Select a Python interpreter outside the OpenCode runtime being upgraded")
        python = str(resolved_python)
        with tempfile.TemporaryDirectory(prefix=".sparseread-runtime-", dir=runtime_dir.parent) as temporary:
            backup = upgrade_backup or Path(temporary) / "old"
            runtime_dir.rename(backup)
            try:
                install_python_runtime(runtime_dir, adapter, python=python, dry_run=False, reader_extras=reader_extras)
            except BaseException:
                if runtime_dir.exists():
                    shutil.rmtree(runtime_dir)
                backup.rename(runtime_dir)
                raise
        return runtime_python(runtime_dir)
    uv_cmd = command_spec("uv", install_hint="Install uv first: https://docs.astral.sh/uv/")
    managed_python = runtime_python(runtime_dir)
    run(uv_cmd.argv("venv", str(runtime_dir), "--python", python), dry_run=dry_run)
    with tempfile.TemporaryDirectory(prefix="sparseread-python-pack-") as tmp:
        wheel_dir = Path(tmp)
        run(uv_cmd.argv("build", "--wheel", "--project", str(CORE_PACKAGE), "--out-dir", str(wheel_dir)), dry_run=dry_run)
        run(uv_cmd.argv("build", "--wheel", "--project", str(adapter), "--out-dir", str(wheel_dir)), dry_run=dry_run)
        if dry_run:
            wheels = [wheel_dir / "sparseread_core.whl", wheel_dir / "sparseread_adapter.whl"]
        else:
            wheels = sorted(wheel_dir.glob("*.whl"))
            if len(wheels) != 2:
                raise SystemExit(f"expected core and adapter wheels, found: {wheels}")
        install_args = [
            "pip",
            "install",
            "--force-reinstall",
            "--python",
            str(managed_python),
            *(str(wheel) for wheel in wheels),
        ]
        if reader_extras == "all":
            install_args.extend(READER_DEPENDENCIES)
        run(uv_cmd.argv(*install_args), dry_run=dry_run)
    return managed_python


def host_workspace(args: argparse.Namespace) -> Path:
    return Path(args.workspace or os.getcwd()).expanduser().resolve()


def codex_project_payloads(workspace: Path) -> tuple[dict, str, str]:
    """Merge only our marketplace entry and append an isolated TOML table."""
    marketplace_file = workspace / ".agents" / "plugins" / "marketplace.json"
    payload = read_json(marketplace_file) if marketplace_file.exists() else {
        "name": "sparseread-" + hashlib.sha256(str(workspace).encode()).hexdigest()[:12],
        "plugins": [],
    }
    name = payload.get("name")
    entries = payload.get("plugins")
    if not isinstance(name, str) or not name or not isinstance(entries, list):
        raise SystemExit(f"Invalid Codex marketplace: {marketplace_file}")
    entry = {
        "name": "sparseread-codex",
        "source": {"source": "local", "path": "./.sparseread/codex/sparseread-codex"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Productivity",
    }
    existing = [item for item in entries if isinstance(item, dict) and item.get("name") == entry["name"]]
    if existing and any(item.get("source") != entry["source"] for item in existing):
        raise SystemExit("A different sparseread-codex marketplace entry already exists; refusing to overwrite it.")
    if not existing:
        entries.append(entry)
    config = workspace / ".codex" / "config.toml"
    text = config.read_text(encoding="utf-8") if config.exists() else ""
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"Cannot merge invalid Codex config {config}: {exc}") from exc
    key = f"sparseread-codex@{name}"
    plugins = parsed.get("plugins", {})
    if not isinstance(plugins, dict):
        raise SystemExit(f"Codex plugins config must be a table: {config}")
    if key not in plugins:
        text += f'\n# SparseRead project adapter (hooks still require explicit trust).\n[plugins.{json.dumps(key)}]\nenabled = true\n'
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise SystemExit(f"Cannot safely append to {config}; use a plugins table instead of an inline table: {exc}") from exc
    elif not isinstance(plugins[key], dict) or plugins[key].get("enabled") is not True:
        print("[install] Existing Codex plugin disabled setting preserved; enable it manually when ready.")
    return payload, text, key


def validate_host_destination(args: argparse.Namespace) -> None:
    workspace = host_workspace(args)
    if not workspace.is_dir():
        raise SystemExit(f"Workspace must already exist: {workspace}")
    plugin = workspace / ".sparseread" / args.platform / f"sparseread-{args.platform}"
    destinations = [plugin]
    if args.platform == "codex":
        destinations += [workspace / ".agents/plugins/marketplace.json", workspace / ".codex/config.toml"]
    else:
        destinations.append(workspace / ".pi/settings.json")
    for destination in destinations:
        current = destination
        while current != workspace:
            if current.is_symlink():
                raise SystemExit(f"Refusing a symlinked installation destination: {current}")
            current = current.parent
    # copytree follows pre-existing links in child directories/files as well.
    # Inspect only the owned plugin tree, not runtime venvs (which use symlinks).
    if plugin.is_dir():
        for child in plugin.rglob("*"):
            if child.is_symlink():
                raise SystemExit(f"Refusing a symlink inside the installation destination: {child}")
    if args.platform == "codex":
        codex_project_payloads(workspace)
    else:
        settings = workspace / ".pi" / "settings.json"
        if settings.exists():
            try:
                read_json(settings)
            except (OSError, json.JSONDecodeError) as exc:
                raise SystemExit(f"Cannot merge Pi settings {settings}: {exc}") from exc
    if plugin.exists() and not (plugin / ".sparseread-runtime.json").is_file():
        raise SystemExit(f"Unmanaged plugin directory exists, refusing to overwrite: {plugin}")


def install_host(args: argparse.Namespace) -> None:
    validate_host_destination(args)
    workspace = host_workspace(args)
    root = workspace / ".sparseread" / args.platform
    target = root / f"sparseread-{args.platform}"
    # A new generation keeps the prior installed runtime intact if building fails.
    if args.dry_run:
        runtime = root / "runtime-new"
    else:
        root.mkdir(parents=True, exist_ok=True)
        runtime = Path(tempfile.mkdtemp(prefix="runtime-", dir=root)) / "venv"
    python = install_python_runtime(runtime, HOST_ADAPTER, python=args.python,
                                    dry_run=args.dry_run, reader_extras=args.reader_extras)
    source = CODEX_PLUGIN if args.platform == "codex" else PI_PLUGIN
    if args.dry_run:
        print(f"[dry-run] Copy packaged plugin {source} -> {target}")
    else:
        shutil.copytree(source, target, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("node_modules", "tests", "test", "__pycache__", "package-lock.json", "tsconfig.json"))
        write_json(target / ".sparseread-runtime.json", {
            "python": str(python), "workspace": str(workspace),
            "mode": args.sparseread_mode, "protocol": BRIDGE_PROTOCOL_VERSION,
        })
        if args.platform == "codex":
            # MCP config is not a shell: hook env placeholders are not portable
            # across Codex clients here. Use the persistent managed install path.
            node = require_command("node")
            launcher = str(target / "scripts" / "launcher.mjs")
            write_json(target / ".mcp.json", {"mcpServers": {"sparseread": {
                "command": node,
                "args": [launcher, "mcp"],
            }}})
            hooks_path = target / "hooks" / "hooks.json"
            hooks = read_json(hooks_path)
            for event, flag in (("PreToolUse", "--hook"), ("SessionStart", "--session-start")):
                for group in hooks["hooks"].get(event, []):
                    for hook in group.get("hooks", []):
                        if hook.get("type") == "command":
                            hook["command"] = shlex.join([node, launcher, flag])
                            hook["commandWindows"] = subprocess.list2cmdline([node, launcher, flag])
            write_json(hooks_path, hooks)
            manifest_path = target / ".codex-plugin" / "plugin.json"
            manifest = read_json(manifest_path)
            base_version = str(manifest["version"]).split("+", 1)[0]
            # Codex caches local packages by version. A reinstall/mode switch must
            # not retain the previous runtime/hook configuration from that cache.
            install_id = hashlib.sha256(str(python).encode()).hexdigest()[:12]
            manifest["version"] = f"{base_version}+local.{install_id}"
            write_json(manifest_path, manifest)
    if args.platform == "codex":
        payload, config, key = codex_project_payloads(workspace)
        if not args.dry_run:
            write_json(workspace / ".agents" / "plugins" / "marketplace.json", payload)
            write_text_atomic(workspace / ".codex" / "config.toml", config)
        print(f"[install] Codex project plugin: {key}. Restart in this trusted project; review/trust bundled hooks before auto interception.")
        print("[install] No personal Codex config was changed. MCP/skill availability and hook trust are separate.")
    else:
        command = command_spec(args.pi_cmd).argv("install", "--local", str(target))
        if getattr(args, "pi_approve", False):
            command.append("--approve")
        result = run(command, cwd=workspace, dry_run=args.dry_run, check=False)
        if result.returncode:
            detail = result.stderr + result.stdout
            if "Project is not trusted" in detail:
                raise SystemExit("Pi requires project trust before changing local package settings. "
                                 "Review this project's files/extensions, then rerun with --pi-approve "
                                 "to approve this install command only. No trust was granted automatically.")
            raise SystemExit(f"Pi project package registration failed ({result.returncode}): {detail}")
        print("[install] Pi project package registered. Restart or /reload; approve project extensions only after review.")
    print(f"[install] Self-contained runtime: {python}. Previous runtime generations are retained for rollback.")


def doctor_host(args: argparse.Namespace) -> None:
    workspace = host_workspace(args)
    target = workspace / ".sparseread" / args.platform / f"sparseread-{args.platform}"
    if args.dry_run:
        print(f"[dry-run] Validate {target} and its installed transport")
        return
    config = read_json(target / ".sparseread-runtime.json")
    if config.get("workspace") != str(workspace) or config.get("protocol") != BRIDGE_PROTOCOL_VERSION:
        raise SystemExit(f"Unexpected runtime configuration: {target}")
    python = config.get("python")
    if not isinstance(python, str) or not Path(python).is_file():
        raise SystemExit(f"Installed interpreter is missing: {python}")
    result = run([python, "-m", "sparseread_agent_tools.doctor", "--host", args.platform,
                  "--workspace", str(workspace), "--mode", str(config.get("mode", "auto"))], cwd=workspace)
    print(result.stdout.strip())
    print("[doctor] Transport/config passed; host activation has not been verified.")
    if args.platform == "codex":
        command = [python, str(ROOT / "scripts" / "check_codex_plugin.py"), str(workspace), "--codex", args.codex_cmd]
        print(f"[doctor] With project trust approved, run in an isolated test workspace: {shlex.join(command)}")
        print("[doctor] Hook trust and actual hook execution require separate host verification.")
    else:
        print("[doctor] Verify host project/extension trust and activation separately.")


def install_opencode_plugin_file(plugin_target: Path, *, dry_run: bool) -> None:
    """Copy the pre-built plugin dist file directly into the OpenCode plugins dir.

    We intentionally avoid npm install / node_modules resolution because
    OpenCode manages .opencode/package.json itself and may prune packages
    installed outside its dependency tree.  The plugin only imports from
    @opencode-ai/plugin (bundled with OpenCode) and Node.js built-ins, so
    a direct file copy is sufficient.
    """
    dist_file = OPENCODE_PLUGIN / "dist" / "sparseread.js"
    if not dry_run:
        plugin_target.parent.mkdir(parents=True, exist_ok=True)
        if plugin_target.exists():
            text = plugin_target.read_text(encoding="utf-8")
            if "SparseReadOpenCodePlugin" not in text and "sparseread_opencode.bridge" not in text:
                raise SystemExit(f"Refusing to overwrite unmanaged plugin: {plugin_target}")
        transport = plugin_target.parent / ".sparseread-transport"
        transport.mkdir(exist_ok=True)
        existing_transport = transport / "transport.js"
        if existing_transport.exists() and "SparseReadBridge" not in existing_transport.read_text(encoding="utf-8"):
            raise SystemExit(f"Refusing to overwrite unmanaged transport: {existing_transport}")
        with tempfile.NamedTemporaryFile(prefix=".transport-", suffix=".js", dir=transport, delete=False) as staged_transport:
            temporary_transport = Path(staged_transport.name)
        try:
            shutil.copy2(OPENCODE_PLUGIN / "dist" / ".sparseread-transport" / "transport.js", temporary_transport)
            temporary_transport.replace(existing_transport)
        finally:
            temporary_transport.unlink(missing_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".sparseread-", suffix=".js", dir=plugin_target.parent, delete=False) as staged:
            temporary = Path(staged.name)
        try:
            shutil.copy2(dist_file, temporary)
            temporary.replace(plugin_target)
        finally:
            temporary.unlink(missing_ok=True)


def install_opencode_v2(plugin_target: Path, *, dry_run: bool, global_install: bool = False) -> None:
    if dry_run:
        return
    plugins = plugin_target.parent
    plugins.mkdir(parents=True, exist_ok=True)
    target = plugins / "sparseread"
    if target.exists():
        manifest = target / "package.json"
        if not manifest.is_file() or read_json(manifest).get("name") != "sparseread-opencode-v2":
            raise SystemExit(f"Refusing to overwrite unmanaged plugin directory: {target}")
    if plugin_target.exists():
        legacy = plugin_target.read_text(encoding="utf-8")
        if "SparseReadOpenCodePlugin" not in legacy and "sparseread_opencode.bridge" not in legacy:
            raise SystemExit(f"Refusing to replace unmanaged plugin: {plugin_target}")
    with tempfile.TemporaryDirectory(prefix=".sparseread-install-", dir=plugins) as temporary:
        stage = Path(temporary) / "new"
        stage.mkdir()
        shutil.copy2(OPENCODE_PLUGIN / "dist" / "v2.js", stage / "v2.js")
        shutil.copy2(OPENCODE_PLUGIN / "dist" / "onboarding.js", stage / "onboarding.js")
        if global_install:
            shutil.copy2(OPENCODE_PLUGIN / "dist" / "tui.js", stage / "tui.js")
            write_json(stage / "global.json", {"global": True})
        shutil.copytree(OPENCODE_PLUGIN / "dist" / ".sparseread-transport", stage / ".sparseread-transport")
        sdk = stage / "node_modules" / "@opencode" / "plugin"
        sdk.parent.mkdir(parents=True)
        shutil.copytree(OPENCODE_PLUGIN / "node_modules" / "@opencode" / "plugin", sdk)
        version = read_json(OPENCODE_PLUGIN / "package.json")["version"]
        exports = {".": "./v2.js"}
        if global_install:
            exports["./tui"] = "./tui.js"
        write_json(stage / "package.json", {"name": "sparseread-opencode-v2", "version": version, "type": "module", "exports": exports})
        backup = Path(temporary) / "old"
        if target.exists():
            target.rename(backup)
        try:
            stage.rename(target)
            if plugin_target.exists():
                plugin_target.unlink()
        except BaseException:
            if target.exists():
                shutil.rmtree(target)
            if backup.exists():
                backup.rename(target)
            raise


def validate_opencode_targets(workspace: Path, *, global_install: bool = False) -> None:
    """Reject symlink redirection and collisions before changing managed files."""
    relative_paths = (
        ".opencode", ".opencode/plugins", ".opencode/plugins/sparseread.js",
        ".opencode/plugins/sparseread", ".opencode/plugins/.sparseread-transport",
        ".opencode/plugins/.sparseread-transport/transport.js", ".opencode/sparseread.json",
        ".sparseread", ".sparseread/runtime", ".sparseread/runtime/opencode",
    )
    if global_install:
        relative_paths = (".", "plugins", "plugins/sparseread.js", "plugins/sparseread", "plugins/.sparseread-transport", "plugins/.sparseread-transport/transport.js", "sparseread.json", "sparseread", "sparseread/runtime", "sparseread/runtime/opencode")
    for relative in relative_paths:
        target = workspace / relative
        if target.is_symlink():
            raise SystemExit(f"Refusing symlink in OpenCode installation path: {target}")
    legacy = workspace / "plugins" / "sparseread.js" if global_install else opencode_workspace_paths(workspace)[0]
    if legacy.exists() and (not legacy.is_file() or not any(marker in legacy.read_text(encoding="utf-8") for marker in ("SparseReadOpenCodePlugin", "sparseread_opencode.bridge"))):
        raise SystemExit(f"Refusing to replace unmanaged plugin: {legacy}")
    v2 = legacy.parent / "sparseread"
    if v2.exists():
        manifest = v2 / "package.json"
        if not v2.is_dir() or manifest.is_symlink() or not manifest.is_file() or read_json(manifest).get("name") != "sparseread-opencode-v2":
            raise SystemExit(f"Refusing to replace unmanaged plugin: {v2}")
    transport = legacy.parent / ".sparseread-transport" / "transport.js"
    if transport.exists() and (not transport.is_file() or "SparseReadBridge" not in transport.read_text(encoding="utf-8")):
        raise SystemExit(f"Refusing to replace unmanaged transport: {transport}")


def opencode_global_modes(args: argparse.Namespace, previous: dict | None) -> tuple[str, str]:
    policies = ("observe", "advisory", "enforce", "native", "auto")
    modes = ("auto", "bench_protocol", "force", "force_sro", "native", "advisory")
    if previous is not None and (previous.get("policy") not in policies or previous.get("mode") not in modes):
        raise SystemExit("Existing global OpenCode SparseRead policy or mode is invalid; fix the config before reinstalling.")
    explicit = getattr(args, "sparseread_mode", None)
    policy = explicit or getattr(args, "policy", None) or (previous["policy"] if previous else "advisory")
    mode = getattr(args, "mode", None) or ("auto" if explicit else previous["mode"] if previous else "auto")
    return policy, mode


def install_opencode(args: argparse.Namespace) -> None:
    profile = install_profile(args)
    global_install = getattr(args, "global_install", False)
    workspace, legacy, config_target, runtime = opencode_install_paths(args)
    v2_target = legacy.parent / "sparseread"
    transport = legacy.parent / ".sparseread-transport" / "transport.js"
    major = opencode_major(args.opencode_cmd)
    if global_install and major != 2:
        raise SystemExit("OpenCode --global requires V2; V1 lacks the required host permission binding.")
    validate_opencode_targets(workspace, global_install=global_install)
    if global_install and config_target.exists() and read_json(config_target).get("bridgeModule") != "sparseread_opencode.bridge":
        raise SystemExit(f"Refusing to overwrite unmanaged OpenCode config: {config_target}")
    if global_install:
        opencode_global_modes(args, read_json(config_target) if config_target.exists() else None)
    if global_install and runtime.exists():
        marker = v2_target / "global.json"
        if not config_target.is_file() or not marker.is_file() or marker.is_symlink() or read_json(marker).get("global") is not True:
            raise SystemExit(f"Refusing to replace unowned global OpenCode runtime: {runtime}")
    if not args.skip_build:
        npm_install_and_build(OPENCODE_PLUGIN, dry_run=args.dry_run)
    if args.dry_run:
        install_python_runtime(runtime, OPENCODE_ADAPTER, python=getattr(args, "python", None) or sys.executable, dry_run=True, reader_extras=getattr(args, "reader_extras", "all"))
        return
    runtime.parent.mkdir(parents=True, exist_ok=True)
    transaction = Path(tempfile.mkdtemp(prefix=".sparseread-rollback-", dir=runtime.parent))
    keep_backup = False
    runtime_existed = runtime.exists()
    previous_config = config_target.exists()
    previous_legacy = legacy.exists()
    previous_transport = transport.exists()
    previous_v2 = v2_target.exists()
    config_changed = False
    plugin_changed = False
    try:
        for present, source, name in ((previous_config, config_target, "config"), (previous_legacy, legacy, "legacy"), (previous_transport, transport, "transport")):
            if present:
                shutil.copy2(source, transaction / name)
        if previous_v2:
            shutil.copytree(v2_target, transaction / "plugin", symlinks=True)
        managed_python = install_python_runtime(
            runtime, OPENCODE_ADAPTER, python=getattr(args, "python", None) or sys.executable,
            dry_run=False, reader_extras=getattr(args, "reader_extras", "all"),
            upgrade_existing=True, upgrade_backup=transaction / "runtime")
        config_target.parent.mkdir(parents=True, exist_ok=True)
        settings = read_json(config_target) if previous_config else {}
        if global_install:
            policy, mode = opencode_global_modes(args, settings if previous_config else None)
        else:
            policy, mode = profile.policy, profile.mode
        settings.update(opencode_workspace_config(workspace, managed_python, policy, mode))
        if global_install:
            settings.pop("projectRoot", None)
        config_changed = True
        write_json(config_target, settings)
        if previous_config:
            config_target.chmod((transaction / "config").stat().st_mode)
        plugin_changed = True
        if major == 2:
            if global_install:
                install_opencode_v2(legacy, dry_run=False, global_install=True)
            else:
                install_opencode_v2(legacy, dry_run=False)
            plugin_target = v2_target
        else:
            if v2_target.exists():
                shutil.rmtree(v2_target)
            install_opencode_plugin_file(legacy, dry_run=False)
            plugin_target = legacy
        if getattr(args, "doctor", False):
            doctor_opencode(args)
    except BaseException as original:
        try:
            if config_changed:
                if previous_config:
                    (transaction / "config").replace(config_target)
                else:
                    config_target.unlink(missing_ok=True)
            if plugin_changed:
                if previous_legacy:
                    (transaction / "legacy").replace(legacy)
                else:
                    legacy.unlink(missing_ok=True)
                if previous_transport:
                    (transaction / "transport").replace(transport)
                else:
                    transport.unlink(missing_ok=True)
                if v2_target.exists():
                    shutil.rmtree(v2_target)
                if previous_v2:
                    (transaction / "plugin").rename(v2_target)
            backup = transaction / "runtime"
            if backup.exists():
                if runtime.exists():
                    shutil.rmtree(runtime)
                backup.rename(runtime)
            elif not runtime_existed and runtime.exists():
                shutil.rmtree(runtime)
        except BaseException as rollback_error:
            keep_backup = True
            raise RuntimeError(f"OpenCode installation failed and rollback failed; backups retained at {transaction}: {rollback_error}") from original
        raise
    finally:
        if not keep_backup:
            shutil.rmtree(transaction)
    print(f"[opencode] {'global config root' if global_install else 'install workspace'}: {workspace}")
    print(f"[opencode] plugin: {plugin_target}")
    print(f"[opencode] config: {config_target}")
    print("[opencode] launch with: opencode run ...")


def install_claude(args: argparse.Namespace) -> None:
    install_profile(args)
    claude_mode = getattr(args, "mode", None) or getattr(args, "sparseread_mode", None) or "auto"
    hook_mode = "advisory" if claude_mode in {"advisory", "observe", "native", "nudge"} else "auto"
    workspace = Path(args.claude_workspace or os.getcwd()).expanduser().resolve()
    runtime = claude_runtime_dir()
    if runtime.is_symlink():
        raise SystemExit(f"Refusing symlink in Claude runtime path: {runtime}")
    mcp_path = workspace / ".mcp.json"
    settings_path = workspace / ".claude" / "settings.local.json"
    guidance = workspace / "CLAUDE.md"
    for path in (workspace / ".claude", mcp_path, settings_path, guidance):
        if path.is_symlink():
            raise SystemExit(f"Refusing symlink in Claude installation path: {path}")
    if args.dry_run:
        install_python_runtime(runtime, CLAUDE_ADAPTER, python=getattr(args, "python", None) or sys.executable,
                               dry_run=True, reader_extras=getattr(args, "reader_extras", "all"))
        return
    runtime.parent.mkdir(parents=True, exist_ok=True)
    transaction = Path(tempfile.mkdtemp(prefix=".sparseread-claude-rollback-", dir=runtime.parent))
    keep_backup = False
    runtime_existed = runtime.exists()
    old_mcp, old_settings, old_guidance = mcp_path.exists(), settings_path.exists(), guidance.exists()
    mcp_changed = settings_changed = guidance_changed = False
    try:
        for present, source, name in ((old_mcp, mcp_path, "mcp"), (old_settings, settings_path, "settings")):
            if present:
                shutil.copy2(source, transaction / name)
        managed_python = install_python_runtime(
            runtime, CLAUDE_ADAPTER, python=getattr(args, "python", None) or sys.executable,
            dry_run=False, reader_extras=getattr(args, "reader_extras", "all"),
            upgrade_existing=True, upgrade_backup=transaction / "runtime")
        mcp_changed = True
        merge_json(mcp_path, claude_mcp_config(workspace, managed_python, claude_mode), dry_run=False)
        if old_mcp:
            mcp_path.chmod((transaction / "mcp").stat().st_mode)
        settings_changed = True
        merge_claude_settings(settings_path, claude_settings_config(workspace, managed_python, hook_mode))
        if old_settings:
            settings_path.chmod((transaction / "settings").stat().st_mode)
        if not old_guidance:
            template = ROOT / "integrations" / "claude" / "CLAUDE.md"
            if template.exists():
                guidance_changed = True
                write_text_atomic(guidance, template.read_text(encoding="utf-8"))
        if getattr(args, "doctor", False):
            doctor(args)
    except BaseException as original:
        try:
            for changed, existed, target, name in ((mcp_changed, old_mcp, mcp_path, "mcp"),
                                                    (settings_changed, old_settings, settings_path, "settings")):
                if changed:
                    if existed:
                        (transaction / name).replace(target)
                    else:
                        target.unlink(missing_ok=True)
            if guidance_changed:
                guidance.unlink(missing_ok=True)
            backup = transaction / "runtime"
            if backup.exists():
                if runtime.exists():
                    shutil.rmtree(runtime)
                backup.rename(runtime)
            elif not runtime_existed and runtime.exists():
                shutil.rmtree(runtime)
        except BaseException as rollback_error:
            keep_backup = True
            raise RuntimeError(f"Claude installation failed and rollback failed; backups retained at {transaction}: {rollback_error}") from original
        raise
    finally:
        if not keep_backup:
            shutil.rmtree(transaction)
    print(f"[claude] install workspace: {workspace}")
    print(f"[claude] mcp config: {mcp_path}")
    print(f"[claude] hook config: {settings_path}")
    print(f"[claude] managed python: {managed_python}")
    if old_guidance:
        print("[claude] Existing CLAUDE.md was preserved; review its SparseRead guidance for the selected mode.")
    print("[claude] restart Claude Code or start a new session after install")


def install_openclaw(args: argparse.Namespace) -> None:
    profile = install_profile(args)
    openclaw_cmd = command_spec(args.openclaw_cmd)
    if not args.skip_build:
        npm_install_and_build(OPENCLAW_PLUGIN, dry_run=args.dry_run)
    managed_python = install_python_runtime(
        openclaw_runtime_dir(args.openclaw_profile),
        OPENCLAW_ADAPTER,
        python=getattr(args, "python", None) or sys.executable,
        dry_run=args.dry_run,
        reader_extras=getattr(args, "reader_extras", "all"),
    )
    profile_args = ["--profile", args.openclaw_profile] if args.openclaw_profile else []
    hook_policy: dict[str, bool] = {}
    if profile.openclaw_hook_mode in {"prompt", "trace", "enforce"}:
        hook_policy["allowPromptInjection"] = True
    if profile.openclaw_hook_mode in {"prompt", "trace", "enforce"}:
        hook_policy["allowConversationAccess"] = True
    run(
        openclaw_cmd.argv(*profile_args, "plugins", "uninstall", "sparseread-openclaw", "--force"),
        check=False,
        dry_run=args.dry_run,
    )
    pack_dir = openclaw_runtime_dir(args.openclaw_profile).parent / "pack"
    tarball = npm_pack(OPENCLAW_PLUGIN, pack_dir, dry_run=args.dry_run)
    try:
        run(
            openclaw_cmd.argv(*profile_args, "plugins", "install", str(tarball)),
            dry_run=args.dry_run,
        )
        run(
            openclaw_cmd.argv(*profile_args, "plugins", "enable", "sparseread-openclaw"),
            dry_run=args.dry_run,
        )
    finally:
        if not args.dry_run:
            tarball.unlink(missing_ok=True)
    run(openclaw_cmd.argv(*profile_args, "plugins", "registry", "--refresh", "--json"), dry_run=args.dry_run)
    patch = {
        "plugins": {
            "entries": {
                "sparseread-openclaw": {
                    "enabled": True,
                    "hooks": hook_policy,
                    "config": {
                        "policy": profile.policy,
                        "bridgeCommand": json.dumps(bridge_command(managed_python)),
                        "bridgeProtocol": BRIDGE_PROTOCOL_VERSION,
                        "projectRoot": str(openclaw_profile_config_path(args.openclaw_profile).parent),
                        "workspaceRoot": str(Path(args.openclaw_workspace).expanduser().resolve())
                        if args.openclaw_workspace
                        else "",
                        "bridgeModule": "sparseread_openclaw.bridge",
                        "mode": profile.mode,
                        "hookMode": profile.openclaw_hook_mode,
                    },
                }
            }
        }
    }
    run(
        openclaw_cmd.argv(*profile_args, "config", "patch", "--stdin"),
        input_text=json.dumps(patch),
        dry_run=args.dry_run,
    )
    inspect = run(
        openclaw_cmd.argv(*profile_args, "plugins", "inspect", "sparseread-openclaw", "--runtime", "--json"),
        check=False,
        dry_run=args.dry_run,
    )
    if not args.dry_run and inspect.returncode != 0:
        raise SystemExit(
            "OpenClaw plugin install did not load cleanly. "
            f"Inspect stderr:\n{inspect.stderr}\nInspect stdout:\n{inspect.stdout}"
        )
    if inspect.returncode == 0 and inspect.stdout:
        validate_openclaw_runtime(inspect.stdout, hook_mode=profile.openclaw_hook_mode)
    print("[openclaw] restart the gateway or start a new agent run after install")


def bridge_smoke(python: Path, module: str, *, dry_run: bool, isolated: bool = False) -> None:
    with tempfile.TemporaryDirectory(prefix="sparseread-install-smoke-") as tmp:
        workspace = Path(tmp)
        target = workspace / "report.md"
        target.write_text("# Report\n\nROOT_CAUSE: cache invalidation used tenant_id.\n", encoding="utf-8")
        payload = "\n".join(
            [
                json.dumps({"id": "0", "method": "version", "params": {}}),
                json.dumps({"id": "1", "method": "preview", "params": {"path": str(target)}}),
                json.dumps({"id": "2", "method": "trace", "params": {}}),
                json.dumps({"id": "3", "method": "shutdown", "params": {}}),
                "",
            ]
        )
        proc = run(
            bridge_invocation(python, *(["-I"] if isolated else []), "-m", module, "--workspace", str(workspace), "--mode", "force"),
            cwd=workspace if isolated else None,
            input_text=payload,
            check=False,
            dry_run=dry_run,
        )
        if dry_run:
            return
        if proc.returncode != 0:
            raise SystemExit(f"{module} smoke failed:\n{proc.stderr}")
        if f'"protocol_version":"{BRIDGE_PROTOCOL_VERSION}"' not in proc.stdout.replace(" ", ""):
            raise SystemExit(f"{module} smoke reported an incompatible bridge protocol:\n{proc.stdout}")
        if '"sro_preview_calls":1' not in proc.stdout.replace(" ", ""):
            raise SystemExit(f"{module} smoke did not report preview call:\n{proc.stdout}")
        print(f"[doctor] {module} bridge smoke passed")


def doctor_opencode(args: argparse.Namespace) -> None:
    command_spec("node")
    command_spec("npm")
    major = opencode_major(args.opencode_cmd)
    global_install = getattr(args, "global_install", False)
    if global_install and major != 2:
        raise SystemExit("OpenCode --global requires V2; V1 lacks the required host permission binding.")
    workspace, _, _, runtime = opencode_install_paths(args)
    bridge_smoke(runtime_python(runtime), "sparseread_opencode.bridge", dry_run=args.dry_run, isolated=global_install)
    if not args.dry_run:
        validate_opencode_workspace(workspace, major, global_install=global_install)
        if major == 2:
            spec = importlib.util.spec_from_file_location("sparseread_opencode_doctor", ROOT / "integrations" / "opencode" / "doctor_v2.py")
            if spec is None or spec.loader is None:
                raise SystemExit("Could not load OpenCode V2 host doctor")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            try:
                module.check(command_spec(args.opencode_cmd).argv(), workspace, global_install=global_install)
            except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
                raise SystemExit(f"OpenCode V2 host doctor failed: {exc}") from exc
        else:
            print("[doctor] transport/config only; OpenCode V1 host invocation has not been verified")


def doctor(args: argparse.Namespace, *, skip_opencode: bool = False) -> None:
    profile = install_profile(args)
    command_spec("uv", install_hint="Install uv first: https://docs.astral.sh/uv/")
    if args.platform in {"codex", "pi"}:
        command_spec(args.codex_cmd if args.platform == "codex" else args.pi_cmd)
        doctor_host(args)
        return
    if args.platform in {"opencode", "both"} and not skip_opencode:
        doctor_opencode(args)
    if args.platform in {"openclaw", "both"}:
        command_spec("node")
        command_spec("npm")
        openclaw_cmd = command_spec(args.openclaw_cmd)
        bridge_smoke(runtime_python(openclaw_runtime_dir(args.openclaw_profile)), "sparseread_openclaw.bridge", dry_run=args.dry_run)
        if not args.dry_run:
            profile_args = ["--profile", args.openclaw_profile] if args.openclaw_profile else []
            inspect = run(
                openclaw_cmd.argv(*profile_args, "plugins", "inspect", "sparseread-openclaw", "--runtime", "--json"),
                check=False,
                dry_run=False,
            )
            if inspect.returncode != 0:
                raise SystemExit(
                    "OpenClaw runtime inspect failed during doctor. "
                    f"Inspect stderr:\n{inspect.stderr}\nInspect stdout:\n{inspect.stdout}"
                )
            validate_openclaw_runtime(inspect.stdout, hook_mode=profile.openclaw_hook_mode)
    if args.platform == "claude":
        command_spec(getattr(args, "claude_cmd", "claude"))
        bridge_smoke(runtime_python(claude_runtime_dir()), "sparseread_claude.bridge", dry_run=args.dry_run)


def preflight(args: argparse.Namespace) -> None:
    """Validate every command and interpreter before mutating a target."""
    command_spec("uv", install_hint="Install uv first: https://docs.astral.sh/uv/")
    args.python = resolve_python(getattr(args, "python", None))
    if args.platform in {"codex", "pi"}:
        command_spec("node")
        cli = command_spec(args.codex_cmd if args.platform == "codex" else args.pi_cmd)
        if args.platform == "codex":
            run(cli.argv("plugin", "list", "--help"))
        validate_host_destination(args)
    if args.platform in {"opencode", "both"}:
        if not args.skip_build:
            command_spec("node")
            command_spec("npm")
        command_spec(args.opencode_cmd)
    if args.platform in {"openclaw", "both"}:
        command_spec("node")
        command_spec("npm")
        command_spec(args.openclaw_cmd)
    if args.platform == "claude":
        command_spec(getattr(args, "claude_cmd", "claude"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install self-contained SparseRead framework adapters.")
    parser.add_argument(
        "--platform",
        choices=["opencode", "openclaw", "claude", "codex", "pi", "both"],
        default="both",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--opencode-workspace", default="", help="Workspace to receive the OpenCode SparseRead plugin")
    scope.add_argument("--global", dest="global_install", action="store_true", help="Install for the current user (OpenCode V2 only)")
    parser.add_argument("--opencode-cmd", default="opencode")
    parser.add_argument("--openclaw-cmd", default="openclaw")
    parser.add_argument("--openclaw-profile", default="", help="Optional OpenClaw profile name")
    parser.add_argument("--openclaw-workspace", default="", help="Optional OpenClaw default SparseRead workspaceRoot")
    parser.add_argument("--claude-workspace", default="", help="Workspace to receive the Claude Code SRO config")
    parser.add_argument("--claude-cmd", default="claude", help="Claude Code executable used for preflight/doctor")
    parser.add_argument("--workspace", default="", help="Existing project to receive the Codex or Pi adapter")
    parser.add_argument("--codex-cmd", default="codex", help="Codex executable used for preflight/doctor")
    parser.add_argument("--pi-cmd", default="pi", help="Pi executable used for project package registration")
    parser.add_argument("--pi-approve", action="store_true",
                        help="Explicitly trust Pi project-local files for this installation command only; use after reviewing the project/extensions")
    parser.add_argument(
        "--python",
        default=None,
        help="Python used to create the managed SparseRead runtime (defaults to a compatible interpreter)",
    )
    parser.add_argument(
        "--reader-extras",
        choices=["all", "none"],
        default="all",
        help="Install PDF/XLSX reader dependencies (default: all; use none for text-only installs)",
    )
    parser.add_argument(
        "--sparseread-mode",
        choices=["auto", "advisory"],
        default=None,
        help=(
            "User-facing SparseRead mode. auto is the default except for a fresh OpenCode global install (advisory): gate-controlled interception for "
            "high-benefit reads. advisory registers tools/prompts only and never intercepts native reads."
        ),
    )
    parser.add_argument(
        "--openclaw-hook-mode",
        choices=["off", "prompt", "trace", "enforce"],
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--policy",
        choices=["observe", "advisory", "enforce", "native", "auto"],
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "bench_protocol", "force", "force_sro", "native", "advisory"],
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--skip-build", action="store_true", help="Skip npm install/build for plugin packages")
    parser.add_argument("--doctor", action="store_true", help="Run bridge/CLI checks after install")
    parser.add_argument("--doctor-only", action="store_true", help="Only run checks; do not install")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.global_install and args.platform != "opencode":
        parser.error("--global requires --platform opencode")
    if not args.global_install and args.sparseread_mode is None:
        args.sparseread_mode = "auto"
    return args


def main() -> int:
    args = parse_args()
    if args.dry_run:
        print("[dry-run] no files or framework configs will be changed")
    if args.doctor_only:
        doctor(args)
        return 0
    preflight(args)
    if args.platform in {"opencode", "both"}:
        install_opencode(args)
    if args.platform in {"openclaw", "both"}:
        install_openclaw(args)
    if args.platform == "claude":
        install_claude(args)
    if args.platform in {"codex", "pi"}:
        install_host(args)
    if args.doctor and args.platform != "claude":
        doctor(args, skip_opencode=args.platform in {"opencode", "both"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
