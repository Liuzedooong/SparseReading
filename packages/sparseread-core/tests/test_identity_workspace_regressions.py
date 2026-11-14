import asyncio
import json

from sparseread.core.orchestrator import SparseReadingOrchestrator
from sparseread.core.tools import SroCardTool, SroPreviewTool, SroReadTool


HINT = {"goal": "find total", "slots": [{"id": "total", "question": "How many skills?", "expected": "count"}]}


def test_context_isolation_reopen_and_end(tmp_path):
    path = tmp_path / "report.txt"
    path.write_text("The registry contains 5705 skills.\n")
    sro = SparseReadingOrchestrator(tmp_path)

    async def task(session):
        sro.set_context({"conversation_id": session, "turn_id": "1"})
        await asyncio.sleep(0)
        pack = json.loads(await SroReadTool(sro).execute(target={"path": str(path)}, mode="collect", hint=HINT))["evidence_pack"]
        await asyncio.sleep(0)
        assert sro._conversation_id() == session
        return pack["artifact_id"]

    async def both():
        return await asyncio.gather(task("one"), task("two"))

    one, two = asyncio.run(both())
    assert one != two and set(sro._text_observations) == {one, two}
    sro.reopen_artifact(one)
    assert one not in sro._text_observations and two in sro._text_observations
    sro.end_conversation("two")
    assert two not in sro._text_observations and two not in sro._slot_digests


def test_deleted_source_invalidates_guard(tmp_path):
    path = tmp_path / "report.txt"
    path.write_text("The registry contains 5705 skills.\n")
    sro = SparseReadingOrchestrator(tmp_path)
    sro.read({"path": str(path)}, "collect", HINT)
    assert sro.has_text_slot_digest(path)
    path.unlink()
    assert not sro.has_text_slot_digest(path)
    assert not sro._text_observations


def test_workspace_relative_paths_and_absolute_and_missing(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    cwd = tmp_path / "cwd"
    workspace.mkdir()
    cwd.mkdir()
    (workspace / "same.txt").write_text("The registry contains 5705 skills.\n")
    (cwd / "same.txt").write_text("The registry contains 9999 skills.\n")
    (cwd / "missing.txt").write_text("cwd decoy")
    monkeypatch.chdir(cwd)
    sro = SparseReadingOrchestrator(workspace)
    card = json.loads(asyncio.run(SroCardTool(sro).execute("same.txt")))["file_card"]
    preview = json.loads(asyncio.run(SroPreviewTool(sro).execute(path="same.txt")))["preview_pack"]
    pack = json.loads(asyncio.run(SroReadTool(sro).execute(target={"path": "same.txt"}, mode="collect", hint=HINT)))["evidence_pack"]
    assert card["path"] == str((workspace / "same.txt").resolve())
    assert preview["card"]["path"] == card["path"]
    assert "5705" in json.dumps(pack) and "9999" not in json.dumps(pack)
    absolute = json.loads(asyncio.run(SroCardTool(sro).execute(str(cwd / "same.txt"))))["file_card"]
    assert absolute["path"] == str((cwd / "same.txt").resolve())
    missing = json.loads(asyncio.run(SroPreviewTool(sro).execute(path="missing.txt")))["preview_pack"]
    assert missing["error"] and "cwd decoy" not in json.dumps(missing)
    no_workspace = SparseReadingOrchestrator(None)
    fallback = json.loads(asyncio.run(SroCardTool(no_workspace).execute("same.txt")))["file_card"]
    assert fallback["path"] == str((cwd / "same.txt").resolve())


def test_source_change_during_reader_is_not_cached(tmp_path, monkeypatch):
    path = tmp_path / "report.txt"
    path.write_text("The registry contains 5705 skills.\n")
    sro = SparseReadingOrchestrator(tmp_path)
    read = sro.text_reader.read
    def change_during_read(*args, **kwargs):
        pack = read(*args, **kwargs)
        path.write_text("The registry contains 6806 skills.\n")
        return pack
    monkeypatch.setattr(sro.text_reader, "read", change_during_read)
    sro.read({"path": str(path)}, "collect", HINT)
    assert not sro._text_observations and not sro._slot_digests
