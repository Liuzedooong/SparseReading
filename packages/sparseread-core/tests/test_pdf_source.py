from __future__ import annotations

import os
from dataclasses import replace
from subprocess import CompletedProcess
from pathlib import Path

import pytest

from sparseread import NativePdfSource, PdfLocation, PdfSection, PdfSnapshot, PdfSourceError, PdfUnit, SparseRead, SparseReadConfig
from sparseread.bridge.server import BridgePolicy, SparseReadBridgeServer

FOCUS = {"goal": "Find the project owner", "needles": ["Owner"]}
COLLECT = {"goal": "Find the project owner", "slots": [{"id": "owner", "question": "Who is the owner?"}]}
BOX = PdfLocation(2, (12.0, 20.0, 40.0, 48.0), "bottom_left", (600.0, 800.0))


class FixtureSource:
    fingerprint = "fixture:1:tuned"

    def __init__(self) -> None:
        self.opens: list[Path] = []

    def open(self, path: Path) -> PdfSnapshot:
        assert path == path.resolve()
        self.opens.append(path)
        owner = path.read_text().removeprefix("%PDF-").strip()
        return PdfSnapshot("schema.v1", (
            PdfUnit("#/texts/0", "Results", "heading", ("Results",)),
            PdfUnit("#/texts/1", f"Owner: {owner}", heading_path=("Results", "Owners"),
                    provenance=(BOX,), citation_uri="fixture://version/owner"),
            PdfUnit("#/tables/0", "| Year | Revenue |\n| --- | --- |\n| 2026 | 12 |",
                    "table", ("Results", "Finance"), (BOX,)),
            PdfUnit("#/texts/2", "Appendix has unrelated details.", heading_path=("Appendix",)),
        ), (PdfSection("#/texts/0", "Results"),))


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    path = tmp_path / "result.pdf"
    path.write_text("%PDF-Ada" + " " * 5000)
    return path


def test_public_injection_keeps_one_snapshot_through_all_read_paths(pdf: Path) -> None:
    source = FixtureSource()
    sro = SparseRead(SparseReadConfig(workspace=pdf.parent, pdf_source=source)).orchestrator
    preview = sro.preview(str(pdf))
    preview_dict = preview.to_dict()
    version = preview_dict["structure"]["parse_version"]
    assert preview_dict["structure"]["outline"] == [{"ref": "#/texts/0", "title": "Results", "level": 1}]
    target = {"artifact_id": preview.artifact_id}
    focus = sro.read(target, "focus", FOCUS).to_dict()
    block = next(block for block in focus["evidence"] if block["anchor"] == "#/texts/1")
    origin = block["source"]
    assert origin == preview_dict["samples"][1]["source"]
    assert origin["parse_version"] == version
    assert origin["heading_path"] == ["Results", "Owners"]
    assert origin["provenance"][0]["bbox"] == BOX.bbox

    collect = sro.read(target, "collect", COLLECT).to_dict()
    slot = collect["slot_digest"]["slots"][0]
    assert slot["candidate"] == "Ada" and slot["source"] == origin
    assert sro.read(target, "collect", COLLECT).slot_digest["guard"]

    raw = sro.raw(preview.raw_ref, selector="#/texts/1")
    assert raw["content"] == "Owner: Ada" and raw["source"] == origin
    assert sro.raw(f"raw:{preview.artifact_id}", range={"start": 0, "end": 1})["content"] == "#"
    assert source.opens == [pdf]


@pytest.mark.parametrize("change", ["bytes", "configuration"])
def test_refresh_invalidates_refs_and_ready_for_same_artifact(pdf: Path, change: str) -> None:
    source = FixtureSource()
    sro = SparseRead(workspace=pdf.parent, pdf_source=source).orchestrator
    preview = sro.preview(str(pdf))
    target = {"artifact_id": preview.artifact_id}
    context = {"goal": "selective_read"}
    assert sro.read(target, "collect", COLLECT, context).slot_digest["overall_status"] == "ready"
    assert sro.current_episode().status == "evidence_ready"
    if change == "bytes":
        before = pdf.stat()
        pdf.write_text("%PDF-Eve" + " " * 5000)
        os.utime(pdf, ns=(before.st_atime_ns, before.st_mtime_ns))
    else:
        source.fingerprint = "fixture:1:changed"
    assert "stale raw_ref" in sro.raw(preview.raw_ref)["error"]
    assert "stale PDF source" in sro.read(target, "collect", COLLECT, context).error
    assert sro.current_episode().status == "open"
    assert len(source.opens) == 1

    refreshed = sro.preview(str(pdf))
    assert refreshed.artifact_id == preview.artifact_id
    assert refreshed.raw_ref != preview.raw_ref
    assert refreshed.structure["parse_version"] != preview.structure["parse_version"]
    pack = sro.read(target, "collect", COLLECT, context)
    assert "guard" not in pack.slot_digest
    assert pack.slot_digest["slots"][0]["candidate"] == ("Eve" if change == "bytes" else "Ada")
    assert "stale raw_ref" in sro.raw(preview.raw_ref)["error"]
    assert len(source.opens) == 2


def test_structured_scope_and_atomic_table_evidence(pdf: Path, monkeypatch) -> None:
    sro = SparseRead(workspace=pdf.parent, pdf_source=FixtureSource()).orchestrator
    preview = sro.preview(str(pdf))
    target = {"artifact_id": preview.artifact_id}
    hint = {"goal": "Read the Results section", "scope": "expand", "needles": ["Results"]}
    pack = sro.read(target, "focus", hint)
    assert {block.anchor for block in pack.evidence} == {"#/texts/0", "#/texts/1", "#/tables/0"}
    table = pack.evidence[-1]
    assert table.source["kind"] == "table"
    assert table.text == sro.raw(preview.raw_ref, selector=table.anchor)["content"]
    assert "| 2026 | 12 |" in table.text
    slot = {"goal": "Revenue", "slots": [{"id": "revenue", "question": "What is the Revenue?"}]}
    collect = sro.read(target, "collect", slot)
    assert collect.slot_digest["slots"][0]["status"] == "partial"
    assert collect.slot_digest["slots"][0]["source"]["ref"] == table.anchor
    assert collect.unresolved == ["revenue"]

    monkeypatch.setenv("SRO_FOCUS_BUDGET_CHARS", "200")
    bounded = sro.read(target, "focus", {"goal": "Find revenue", "needles": ["Revenue"]})
    assert all(block.anchor != table.anchor for block in bounded.evidence)
    assert bounded.unresolved == ["Revenue"]


def test_evicted_snapshot_reloads_only_if_version_matches(pdf: Path, monkeypatch) -> None:
    source = FixtureSource()
    sro = SparseRead(workspace=pdf.parent, pdf_source=source).orchestrator
    monkeypatch.setattr(sro.text_reader.pdf_cache, "_MAX_SNAPSHOTS", 1)
    first = sro.preview(str(pdf))
    other = pdf.with_name("other.pdf")
    other.write_text("%PDF-Eve" + " " * 5000)
    sro.preview(str(other))
    assert sro.raw(first.raw_ref, selector="#/texts/1")["content"] == "Owner: Ada"
    assert source.opens == [pdf, other, pdf]


def test_parse_failure_and_version_drift_do_not_publish_reference(pdf: Path) -> None:
    class ChangingSource(FixtureSource):
        def open(self, path: Path) -> PdfSnapshot:
            result = super().open(path)
            path.write_text("%PDF-Eve" + " " * 5000)
            return result

    sro = SparseRead(workspace=pdf.parent, pdf_source=ChangingSource()).orchestrator
    failed = sro.preview(str(pdf))
    assert not failed.raw_ref and "changed during parsing" in failed.error
    assert not sro.has_text_slot_digest(pdf)
    with pytest.raises(PdfSourceError, match="unique"):
        PdfSnapshot("v1", (PdfUnit("duplicate", "a"), PdfUnit("duplicate", "b")))


def test_bridge_manifest_is_metadata_only_and_cannot_be_reused_across_sessions(pdf: Path) -> None:
    source = FixtureSource()
    bridge = SparseReadBridgeServer(
        workspace=pdf.parent,
        classifier=lambda info, decision: {},
        policy=BridgePolicy(platform="pdf-contract", gate_key="gate", ready_guard="test"),
        pdf_source=source,
    )
    first = {"conversation_id": "first", "turn_id": "1"}
    second = {"conversation_id": "second", "turn_id": "1"}

    def call(method, context=first, **params):
        return bridge.handle({"method": method, "params": {**params, "context": context}})

    target = {"path": str(pdf)}
    manifest = call("source_manifest", target=target)
    assert not source.opens
    with pytest.raises(ValueError, match="manifest"):
        call("preview", second, target=target, manifest_token=manifest["manifest_token"])
    assert not source.opens
    manifest = call("source_manifest", target=target)
    preview = call("preview", target=target, manifest_token=manifest["manifest_token"],
                   episode_hint={"goal": "selective_read"})["preview_pack"]
    ref = preview["raw_ref"]
    assert ref and len(source.opens) == 1
    with pytest.raises(ValueError, match="unauthorized raw_ref"):
        call("source_manifest", second, raw_ref=ref)
    manifest = call("source_manifest", raw_ref=ref)
    raw = call("raw", raw_ref=ref, manifest_token=manifest["manifest_token"], selector="#/texts/1")["raw"]
    assert raw["content"] == "Owner: Ada" and len(source.opens) == 1


def test_evicted_ready_is_not_reused_if_parse_revision_differs(pdf: Path, monkeypatch) -> None:
    class RevisableSource(FixtureSource):
        revision = "v1"

        def open(self, path: Path) -> PdfSnapshot:
            return replace(super().open(path), version=self.revision)

    source = RevisableSource()
    sro = SparseRead(workspace=pdf.parent, pdf_source=source).orchestrator
    monkeypatch.setattr(sro.text_reader.pdf_cache, "_MAX_SNAPSHOTS", 1)
    first = sro.preview(str(pdf))
    target = {"artifact_id": first.artifact_id}
    assert sro.read(target, "collect", COLLECT).slot_digest["overall_status"] == "ready"
    other = pdf.with_name("other.pdf")
    other.write_text("%PDF-Eve")
    sro.preview(str(other))
    source.revision = "v2"

    assert "stale PDF source" in sro.read(target, "collect", COLLECT).error
    assert not sro.has_text_slot_digest(pdf)
    assert "stale raw_ref" in sro.raw(first.raw_ref)["error"]
    assert sro.preview(str(pdf)).raw_ref != first.raw_ref


def test_native_source_keeps_poppler_layout_and_fallback_contract(pdf: Path, monkeypatch) -> None:
    source = NativePdfSource()

    def poppler(argv, **_kwargs):
        assert argv == ["pdftotext", "-layout", str(pdf), "-"]
        return CompletedProcess(argv, 0, "RESULTS SUMMARY\n\nOwner: Ada.\fMore text.", "")

    monkeypatch.setattr("sparseread.core.readers.native_pdf.subprocess.run", poppler)
    snapshot = source.open(pdf)
    assert snapshot.outline[0].title == "p1 RESULTS SUMMARY"
    assert [unit.ref for unit in snapshot.units] == ["p1:L1-L1", "p1:L3-L3", "p2:L1-L1"]

    def missing(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("sparseread.core.readers.native_pdf.subprocess.run", missing)
    monkeypatch.setattr(NativePdfSource, "_pages_with_pymupdf", staticmethod(lambda _path: ["Fallback text."]))
    assert source.open(pdf).units[0].text == "Fallback text."

    monkeypatch.setattr(
        "sparseread.core.readers.native_pdf.subprocess.run",
        lambda argv, **_kwargs: CompletedProcess(argv, 1, "", "bad PDF"),
    )
    with pytest.raises(PdfSourceError, match="bad PDF"):
        source.open(pdf)
