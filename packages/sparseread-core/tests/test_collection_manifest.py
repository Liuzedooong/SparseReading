import os
from pathlib import Path

import pytest

from sparseread.bridge.server import BridgePolicy, SparseReadBridgeServer


def make_bridge(workspace):
    return SparseReadBridgeServer(workspace=workspace, mode="force",
        classifier=lambda info, decision: {"mode": decision.mode, "block_native_read": False},
        policy=BridgePolicy(platform="test", gate_key="gate", ready_guard="test"))


def call(bridge, method, **params):
    return bridge.handle({"method": method, "params": params})


def manifest(bridge, target, context):
    return call(bridge, "source_manifest", target=target, context=context)


def test_collection_manifest_requires_all_paths_and_detects_changes(tmp_path, monkeypatch):
    root = tmp_path / "collection"
    root.mkdir()
    (root / "a.txt").write_text("red 1111")
    (root / "b.txt").write_text("blue 2222")
    bridge = make_bridge(tmp_path)
    context = {"session_id": "one"}
    original = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("body read")))
    m = manifest(bridge, {"path": str(root)}, context)
    monkeypatch.setattr(Path, "read_text", original)
    assert {Path(x["path"]).name for x in m["paths"]} == {"collection", "a.txt", "b.txt"}
    (root / "c.txt").write_text("new source")
    with pytest.raises(ValueError, match="changed"):
        call(bridge, "preview", target={"path": str(root)}, context=context, manifest_token=m["manifest_token"])
    m = manifest(bridge, {"path": str(root)}, context)
    old = (root / "a.txt").stat()
    (root / "a.txt").write_text("red 9999")
    os.utime(root / "a.txt", ns=(old.st_atime_ns, old.st_mtime_ns))
    with pytest.raises(ValueError, match="changed"):
        call(bridge, "preview", target={"path": str(root)}, context=context, manifest_token=m["manifest_token"])
    (root / "link.txt").symlink_to(root / "a.txt")
    with pytest.raises(ValueError, match="symlinks"):
        manifest(bridge, {"path": str(root)}, context)


def test_collection_bound_reads_new_question_verify_and_raw_version(tmp_path):
    root = tmp_path / "collection"
    root.mkdir()
    source = root / "a.txt"
    source.write_text("ALPHA: first item.\nBETA: second item.\n")
    (root / "b.txt").write_text("Gamma: third item.\n")
    bridge = make_bridge(tmp_path)
    context = {"session_id": "one"}
    target = {"path": str(root)}
    m = manifest(bridge, target, context)
    preview = call(bridge, "preview", target=target, context=context, manifest_token=m["manifest_token"])
    aid = preview["preview_pack"]["artifact_id"]
    raw_ref = preview["preview_pack"]["raw_ref"]
    target = {"artifact_id": aid}
    def read(mode, goal, needle):
        m = manifest(bridge, target, context)
        return call(bridge, "read", target=target, mode=mode,
                    hint={"goal": goal, "needles": [needle], "type_hint": "collection"},
                    context=context, manifest_token=m["manifest_token"])["evidence_pack"]
    first = read("collect", "find alpha", "ALPHA")
    assert "first item" in str(first)
    second = read("collect", "find beta", "BETA")
    assert "second item" in str(second) and not str(second.get("summary", "")).startswith("adapter ready guard")
    verified = read("verify", "verify beta", "BETA")
    assert "second item" in str(verified) and not verified.get("error")
    m = call(bridge, "source_manifest", raw_ref=raw_ref, context=context)
    raw = call(bridge, "raw", raw_ref=raw_ref, selector="a.txt", context=context, manifest_token=m["manifest_token"])
    assert "first item" in raw["raw"]["content"]
    source.write_text("ALPHA: new item!!\nBETA: second item.\n")
    with pytest.raises(ValueError, match="stale"):
        call(bridge, "source_manifest", raw_ref=raw_ref, context=context)
    fresh = read("collect", "find alpha", "ALPHA")
    assert "new item" in str(fresh) and "first item" not in str(fresh)
    m = manifest(bridge, target, context)
    preview2 = call(bridge, "preview", target=target, context=context, manifest_token=m["manifest_token"])
    assert preview2["preview_pack"]["raw_ref"] != raw_ref


def test_collection_excludes_new_source_after_validation(tmp_path, monkeypatch):
    root = tmp_path / "collection"
    root.mkdir()
    (root / "a.txt").write_text("approved text")
    bridge = make_bridge(tmp_path)
    context = {"session_id": "one"}
    m = manifest(bridge, {"path": str(root)}, context)
    original = bridge._dispatch
    def mutate_after_validation(method, params):
        (root / "new.txt").write_text("UNAUTHORIZED SECRET")
        return original(method, params)
    monkeypatch.setattr(bridge, "_dispatch", mutate_after_validation)
    result = call(bridge, "preview", target={"path": str(root)}, context=context, manifest_token=m["manifest_token"])
    assert "UNAUTHORIZED SECRET" not in str(result)


def test_replacement_after_validation_never_reads_replacement(tmp_path, monkeypatch):
    root = tmp_path / "collection"
    root.mkdir()
    source = root / "a.txt"
    source.write_text("approved")
    other = tmp_path / "secret.txt"
    other.write_text("UNAUTHORIZED SECRET")
    bridge = make_bridge(tmp_path)
    context = {"session_id": "one"}
    m = manifest(bridge, {"path": str(root)}, context)
    original = bridge._dispatch
    def replace_after_validation(method, params):
        source.unlink()
        source.symlink_to(other)
        return original(method, params)
    monkeypatch.setattr(bridge, "_dispatch", replace_after_validation)
    with pytest.raises(ValueError, match="changed"):
        call(bridge, "preview", target={"path": str(root)}, context=context, manifest_token=m["manifest_token"])


def test_collection_reopen_preserves_output_provenance(tmp_path):
    root = tmp_path / "collection"
    root.mkdir()
    (root / "a.txt").write_text("Alpha: item")
    bridge = make_bridge(tmp_path)
    context = {"session_id": "one"}
    target = {"path": str(root)}
    m = manifest(bridge, target, context)
    preview = call(bridge, "preview", target=target, context=context, manifest_token=m["manifest_token"])
    aid = preview["preview_pack"]["artifact_id"]
    orch = bridge.runtime.orchestrator
    orch._required_outputs_by_artifact[aid] = {"result.md"}
    orch._written_outputs_by_artifact[aid] = {"result.md"}
    orch._ready_collection_artifacts[aid] = {"instruction": "stale"}
    m = manifest(bridge, {"artifact_id": aid}, context)
    call(bridge, "read", target={"artifact_id": aid}, mode="focus", hint={"goal": "read alpha"},
         context=context, manifest_token=m["manifest_token"],
         episode_hint={"relation": "switch", "goal": "cross_file_evidence", "coverage": "selective"})
    assert orch._required_outputs_by_artifact[aid] == {"result.md"}
    assert orch._written_outputs_by_artifact[aid] == {"result.md"}


def test_collection_cross_session_and_reset_reject_reference(tmp_path):
    root = tmp_path / "collection"
    root.mkdir()
    (root / "a.txt").write_text("hello")
    bridge = make_bridge(tmp_path)
    one = {"session_id": "one"}
    two = {"session_id": "two"}
    m = manifest(bridge, {"path": str(root)}, one)
    preview = call(bridge, "preview", target={"path": str(root)}, context=one, manifest_token=m["manifest_token"])
    aid = preview["preview_pack"]["artifact_id"]
    raw_ref = preview["preview_pack"]["raw_ref"]
    with pytest.raises(ValueError, match="unauthorized"):
        manifest(bridge, {"artifact_id": aid}, two)
    with pytest.raises(ValueError, match="unauthorized"):
        call(bridge, "source_manifest", raw_ref=raw_ref, context=two)
    call(bridge, "lifecycle_event", type="session_end", context=one)
    with pytest.raises(ValueError, match="unauthorized"):
        call(bridge, "source_manifest", raw_ref=raw_ref, context=one)


def test_collection_manifest_rejects_traversal_error_and_limit(tmp_path, monkeypatch):
    root = tmp_path / "collection"
    root.mkdir()
    bridge = make_bridge(tmp_path)
    context = {"session_id": "one"}
    original_walk = os.walk
    def bad_walk(path, *, followlinks, onerror):
        onerror(PermissionError("blocked"))
        return iter(())
    monkeypatch.setattr(os, "walk", bad_walk)
    with pytest.raises(ValueError, match="unavailable"):
        manifest(bridge, {"path": str(root)}, context)
    monkeypatch.setattr(os, "walk", original_walk)
    for i in range(1025):
        (root / f"{i}.txt").touch()
    with pytest.raises(ValueError, match="1024"):
        manifest(bridge, {"path": str(root)}, context)


def test_collection_root_returned_for_opaque_references(tmp_path):
    root = tmp_path / "collection"
    root.mkdir()
    (root / "a.txt").write_text("hello")
    bridge = make_bridge(tmp_path)
    context = {"session_id": "one"}
    m = manifest(bridge, {"path": str(root)}, context)
    preview = call(bridge, "preview", target={"path": str(root)}, context=context, manifest_token=m["manifest_token"])
    aid = preview["preview_pack"]["artifact_id"]
    raw_ref = preview["preview_pack"]["raw_ref"]
    for m in (manifest(bridge, {"artifact_id": aid}, context), call(bridge, "source_manifest", raw_ref=raw_ref, context=context)):
        assert {"path": str(root), "canonical_path": str(root.resolve())} in m["paths"]


def test_gate_pdf_probe_uses_only_frozen_collection(tmp_path):
    root = tmp_path / "collection"
    root.mkdir()
    approved = root / "a.txt"
    approved.write_text("hello")
    bridge = make_bridge(tmp_path)
    context = {"session_id": "one"}
    m = manifest(bridge, {"path": str(root)}, context)
    original = bridge._dispatch
    def add_pdf(method, params):
        (root / "new.pdf").write_bytes(b"x" * 5000)
        assert not bridge.runtime.orchestrator.benefit_gate._contains_long_pdf(root)
        assert bridge.runtime.orchestrator.inspect(root).size_bytes == len("hello")
        return original(method, params)
    bridge._dispatch = add_pdf
    call(bridge, "preview", target={"path": str(root)}, context=context, manifest_token=m["manifest_token"])
