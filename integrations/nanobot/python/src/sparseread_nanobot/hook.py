"""Host-independent helpers for the NanoBot adapter."""

from __future__ import annotations

from typing import Any

READ_TOOLS = {"read_file", "list_dir"}
EXEC_TOOLS = {"exec", "bash", "shell"}
WRITE_TOOLS = {"write_file", "edit_file", "apply_patch", "write"}


def __getattr__(name: str) -> Any:
    if name == "SparseReadHook":
        # Delay the optional host dependency until a NanoBot hook is requested.
        from sparseread_nanobot.v041 import NanoHook
        return NanoHook
    raise AttributeError(name)


def candidate_paths(args: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key in ("file_path", "path", "filename", "target"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            result.append(value)
        elif isinstance(value, dict) and isinstance(value.get("path"), str):
            result.append(value["path"])
    for key in ("paths", "files"):
        value = args.get(key)
        if isinstance(value, list):
            result.extend(item for item in value if isinstance(item, str) and item.strip())
    return result
