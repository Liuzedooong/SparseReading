from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_SOURCE = ROOT / "packages" / "sparseread-core" / "src" / "sparseread"
PROJECT_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for source in path.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".", 1)[0])
    return roots


def test_core_has_no_framework_imports() -> None:
    assert not (
        {
            "nanobot",
            "sparseread_nanobot",
            "sparseread_opencode",
            "sparseread_openclaw",
            "sparseread_claude",
            "sparseread_agent_tools",
            "mcp",
        }
        & imported_roots(CORE_SOURCE)
    )


def test_each_framework_adapter_is_an_independent_distribution() -> None:
    expected = {
        "nanobot": "sparseread-nanobot",
        "opencode": "sparseread-opencode",
        "openclaw": "sparseread-openclaw",
        "claude": "sparseread-claude",
    }
    for framework, distribution in expected.items():
        pyproject = ROOT / "integrations" / framework / "python" / "pyproject.toml"
        payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        assert payload["project"]["name"] == distribution
        expected_core = "sparseread-core>=0.1,<0.2" if framework == "openclaw" else "sparseread-core>=0.1.4,<0.2"
        expected_deps = [expected_core, "mcp>=1.26,<2.0"] if framework == "claude" else [expected_core]
        assert payload["project"]["dependencies"] == expected_deps
        assert payload["project"]["version"] == PROJECT_VERSION


def test_javascript_plugins_are_publishable_and_versioned() -> None:
    for framework in ("opencode", "openclaw"):
        package = json.loads(
            (ROOT / "integrations" / framework / "plugin" / "package.json").read_text(encoding="utf-8")
        )
        assert package["name"] == f"@sparseread/{framework}"
        assert package["private"] is False
        assert package["version"] == PROJECT_VERSION
        assert package["scripts"]["prepack"] == "npm run build"


def test_release_has_one_canonical_framework_source() -> None:
    assert not (ROOT / "opencode_pilot").exists()
    assert not (ROOT / "openclaw_pilot").exists()


def test_host_transport_is_an_independent_core_only_adapter() -> None:
    package = ROOT / "integrations/agent-tools/python"
    metadata = tomllib.loads((package / "pyproject.toml").read_text())
    assert metadata["project"]["name"] == "sparseread-agent-tools"
    assert metadata["project"]["dependencies"] == ["sparseread-core>=0.1,<0.2", "mcp>=1.26,<2.0"]
    assert not ({"sparseread_claude", "sparseread_opencode", "sparseread_openclaw", "sparseread_nanobot"} & imported_roots(package / "src"))


def test_pi_package_ships_source_without_a_second_host_sdk() -> None:
    package = json.loads((ROOT / "integrations/pi/package/package.json").read_text())
    assert package["name"] == "@sparseread/pi"
    assert package["version"] == PROJECT_VERSION
    assert package["pi"]["extensions"] == ["./src/index.ts"]
    assert "pi-package" in package["keywords"]
    assert not package.get("dependencies")
    assert "@earendil-works/pi-coding-agent" in package["peerDependencies"]


def test_runtime_version_constants_match_project_metadata() -> None:
    paths = [
        ("packages/sparseread-core/src/sparseread/__init__.py", "packages/sparseread-core/pyproject.toml"),
        ("integrations/nanobot/python/src/sparseread_nanobot/__init__.py", "integrations/nanobot/python/pyproject.toml"),
        ("integrations/opencode/python/src/sparseread_opencode/__init__.py", "integrations/opencode/python/pyproject.toml"),
        ("integrations/openclaw/python/src/sparseread_openclaw/__init__.py", "integrations/openclaw/python/pyproject.toml"),
    ]
    for source, metadata in paths:
        tree = ast.parse((ROOT / source).read_text(encoding="utf-8"))
        version = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets))
        project_version = tomllib.loads((ROOT / metadata).read_text(encoding="utf-8"))["project"]["version"]
        assert version == project_version == PROJECT_VERSION
