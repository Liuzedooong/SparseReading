from pathlib import Path

import pytest

from sparseread.bridge.server import BridgePolicy, SparseReadBridgeServer


def make_bridge(workspace):
    return SparseReadBridgeServer(
        workspace=workspace,
        mode="auto",
        classifier=lambda info, decision: {"mode": decision.mode, "block_native_read": False},
        policy=BridgePolicy(platform="test", gate_key="gate", ready_guard="test"),
    )


def call(bridge, method, **params):
    return bridge.handle({"method": method, "params": params})


def test_manifest_token_blocks_replacement_and_cross_session(tmp_path):
    source = tmp_path / "file.txt"
    source.write_text("hello")
    bridge = make_bridge(tmp_path)
    ctx = {"session_id": "one"}
    manifest = call(bridge, "source_manifest", target={"path": str(source)}, context=ctx)
    replacement = tmp_path / "replacement"
    replacement.write_text("world")
    replacement.replace(source)
    with pytest.raises(ValueError, match="changed"):
        call(bridge, "preview", target={"path": str(source)}, context=ctx, manifest_token=manifest["manifest_token"])
    fresh = call(bridge, "source_manifest", target={"path": str(source)}, context=ctx)
    with pytest.raises(ValueError, match="unauthorized"):
        call(bridge, "preview", target={"path": str(source)}, context={"session_id": "two"}, manifest_token=fresh["manifest_token"])


def test_manifest_bound_decide_and_card_do_not_read_parent_collection(tmp_path, monkeypatch):
    source = tmp_path / "file.txt"
    source.write_text("hello")
    (tmp_path / "sibling.txt").write_text("private sibling")
    bridge = make_bridge(tmp_path)
    def reject_collection(*args, **kwargs):
        raise AssertionError("manifest-bound single-file call read parent collection")
    monkeypatch.setattr(bridge.runtime.orchestrator.collection_reader, "_items", reject_collection)
    for method in ("decide", "card"):
        manifest = call(bridge, "source_manifest", target={"path": str(source)})
        call(bridge, method, path=str(source), manifest_token=manifest["manifest_token"])


def test_manifest_relative_source_and_end_cleanup(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    cwd = tmp_path / "elsewhere"
    workspace.mkdir()
    cwd.mkdir()
    (workspace / "file.txt").write_text("workspace value")
    (cwd / "file.txt").write_text("decoy value")
    monkeypatch.chdir(cwd)
    bridge = make_bridge(workspace)
    context = {"session_id": "one"}
    manifest = call(bridge, "source_manifest", target={"path": "file.txt"}, context=context)
    result = call(bridge, "preview", target={"path": "file.txt"}, context=context, manifest_token=manifest["manifest_token"])
    assert "workspace value" in str(result) and "decoy value" not in str(result)
    pending = call(bridge, "source_manifest", target={"path": "file.txt"}, context=context)
    call(bridge, "lifecycle_event", type="session_end", context=context)
    with pytest.raises(ValueError, match="unauthorized"):
        call(bridge, "preview", target={"path": "file.txt"}, context=context, manifest_token=pending["manifest_token"])


def test_manifest_rejects_hint_artifact_override(tmp_path):
    allowed = tmp_path / "allowed.txt"
    denied = tmp_path / "denied.txt"
    allowed.write_text("allowed content")
    denied.write_text("secret content")
    bridge = make_bridge(tmp_path)
    context = {"session_id": "one"}
    preview = call(bridge, "preview", target={"path": str(denied)}, context=context)
    denied_id = preview["preview_pack"]["artifact_id"]
    manifest = call(bridge, "source_manifest", target={"path": str(allowed)}, context=context)
    with pytest.raises(ValueError, match="authorized source"):
        call(bridge, "read", target={"path": str(allowed)}, mode="collect",
             hint={"goal": "read", "artifact": denied_id}, context=context,
             manifest_token=manifest["manifest_token"])


@pytest.mark.parametrize("method", ["preview", "card", "decide", "read"])
def test_manifest_rejects_raw_ref_override_for_other_methods(tmp_path, method):
    allowed = tmp_path / "allowed.txt"
    denied = tmp_path / "denied.txt"
    allowed.write_text("allowed content")
    denied.write_text("secret content")
    bridge = make_bridge(tmp_path)
    context = {"session_id": "one"}
    preview = call(bridge, "preview", target={"path": str(allowed)}, context=context)
    raw_ref = preview["preview_pack"]["raw_ref"]
    manifest = call(bridge, "source_manifest", raw_ref=raw_ref, context=context)
    params = {"raw_ref": raw_ref, "context": context, "manifest_token": manifest["manifest_token"]}
    if method in {"card", "decide"}:
        params["path"] = str(denied)
    else:
        params["target"] = {"path": str(denied)}
    if method == "read":
        params.update(mode="collect", hint={"goal": "read secret"})
    with pytest.raises(ValueError, match="ambiguous"):
        call(bridge, method, **params)


def test_source_manifest_rejects_ambiguous_target(tmp_path):
    source = tmp_path / "file.txt"
    source.write_text("content")
    bridge = make_bridge(tmp_path)
    preview = call(bridge, "preview", target={"path": str(source)})
    aid = preview["preview_pack"]["artifact_id"]
    with pytest.raises(ValueError, match="ambiguous"):
        call(bridge, "source_manifest", target={"path": str(source), "artifact_id": aid})


def test_manifest_rejects_whitespace_suffix_path_confusion(tmp_path):
    allowed = tmp_path / "report.txt "
    denied = tmp_path / "report.txt"
    allowed.write_text("authorized")
    denied.write_text("secret")
    bridge = make_bridge(tmp_path)
    with pytest.raises(ValueError, match="whitespace"):
        call(bridge, "source_manifest", target={"path": str(allowed)})


def test_old_raw_ref_rejected_after_same_size_rewrite_with_restored_mtime(tmp_path):
    import os
    source = tmp_path / "source.txt"
    source.write_text("value 1111")
    bridge = make_bridge(tmp_path)
    context = {"session_id": "one"}
    old = call(bridge, "preview", target={"path": str(source)}, context=context)["preview_pack"]["raw_ref"]
    stat = source.stat()
    source.write_text("value 2222")
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(ValueError, match="unauthorized"):
        call(bridge, "source_manifest", raw_ref=old, context=context)
    fresh = call(bridge, "preview", target={"path": str(source)}, context=context)["preview_pack"]["raw_ref"]
    assert fresh != old
    with pytest.raises(ValueError, match="unauthorized"):
        call(bridge, "source_manifest", raw_ref=old, context=context)
    manifest = call(bridge, "source_manifest", raw_ref=fresh, context=context)
    raw = call(bridge, "raw", raw_ref=fresh, context=context, manifest_token=manifest["manifest_token"])
    assert raw["raw"]["content"] == "value 2222"


def test_evicted_full_raw_ref_never_aliases_newer_reference(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("old")
    bridge = make_bridge(tmp_path)
    old = call(bridge, "preview", target={"path": str(source)})["preview_pack"]["raw_ref"]
    source.write_text("new")
    fresh = call(bridge, "preview", target={"path": str(source)})["preview_pack"]["raw_ref"]
    assert fresh != old
    bridge.runtime.orchestrator._raw_refs.pop(old)
    raw = call(bridge, "raw", raw_ref=old)
    assert "unknown or stale raw_ref" in raw["raw"]["error"]
