from pathlib import Path

import pytest

from sparseread_opencode.bridge import OpenCodeBridge


def call(bridge, method, **params):
    return bridge.handle({"method": method, "params": params})


def test_manifest_revalidates_session_path_and_stat_without_content_reads(tmp_path: Path, monkeypatch):
    path = tmp_path / "source.txt"
    path.write_text("The count is 5705.\n")
    bridge = OpenCodeBridge(workspace=tmp_path, mode="force")
    context = {"session_id": "one"}
    original = Path.read_text
    def forbid_contents(self, *args, **kwargs):
        raise AssertionError("preflight opened source contents")
    monkeypatch.setattr(Path, "read_text", forbid_contents)
    manifest = call(bridge, "source_manifest", target={"path": str(path)}, context=context)
    monkeypatch.setattr(Path, "read_text", original)
    assert manifest["paths"] == [{"path": str(path), "canonical_path": str(path.resolve())}]
    preview = call(bridge, "preview", target={"path": str(path)}, context=context, manifest_token=manifest["manifest_token"])
    artifact_id = preview["preview_pack"]["artifact_id"]
    raw_ref = preview["preview_pack"]["raw_ref"]
    for target in ({"artifact_id": artifact_id},):
        with pytest.raises(ValueError, match="unauthorized"):
            call(bridge, "source_manifest", target=target, context={"session_id": "other"})
    with pytest.raises(ValueError, match="unauthorized"):
        call(bridge, "source_manifest", raw_ref=raw_ref, context={"session_id": "other"})
    changed = call(bridge, "source_manifest", target={"artifact_id": artifact_id}, context=context)
    path.write_text("The count is 6806.\n")
    with pytest.raises(ValueError, match="changed"):
        call(bridge, "read", target={"artifact_id": artifact_id}, mode="collect", hint={"goal": "find count"}, context=context, manifest_token=changed["manifest_token"])
    collection = call(bridge, "source_manifest", target={"path": str(tmp_path)}, context=context)
    assert collection["complete"] and len(collection["paths"]) == 2
    with pytest.raises(ValueError):
        call(bridge, "source_manifest", target={"path": str(tmp_path / "missing")}, context=context)


def test_bridge_changed_question_source_and_verify(tmp_path: Path):
    path = tmp_path / "source.txt"
    path.write_text("The count is 5705.\nThe date is 15 July 2026.\n")
    bridge = OpenCodeBridge(workspace=tmp_path, mode="force")
    first_hint = {"goal": "answer", "slots": [{"id": "q", "question": "What is the count?"}]}
    first = call(bridge, "read", target={"path": str(path)}, mode="collect", hint=first_hint)["evidence_pack"]
    aid = first["artifact_id"]
    second = call(bridge, "read", target={"artifact_id": aid}, mode="collect", hint={"goal": "answer", "slots": [{"id": "q", "question": "What is the date?"}]})["evidence_pack"]
    assert "15 July 2026" in str(second["slot_digest"])
    path.write_text(path.read_text().replace("5705", "6806"))
    third = call(bridge, "read", target={"artifact_id": aid}, mode="collect", hint=first_hint)["evidence_pack"]
    assert "6806" in str(third["slot_digest"]) and "5705" not in str(third["slot_digest"])
    verified = call(bridge, "read", target={"artifact_id": aid}, mode="verify", hint={"goal": "verify count", "needles": ["6806"]})["evidence_pack"]
    assert verified["evidence"] and not verified["error"]
