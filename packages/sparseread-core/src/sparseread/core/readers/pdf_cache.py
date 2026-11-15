"""Runtime-local PDF snapshots and their checked source identity."""

from __future__ import annotations

import hashlib
import os
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG
from threading import Lock

from sparseread.pdf import PdfSnapshot, PdfSource, PdfSourceError

FileVersion = tuple[int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class PdfBinding:
    file_version: FileVersion
    fingerprint: str
    version: str


@dataclass(frozen=True, slots=True)
class LoadedPdf:
    binding: PdfBinding
    snapshot: PdfSnapshot


class PdfCache:
    _MAX_SNAPSHOTS = 4
    _MAX_CHARS = 8_000_000

    def __init__(self, source: PdfSource) -> None:
        self._source = source
        self._entries: OrderedDict[Path, tuple[LoadedPdf, int]] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def _file_version(stat: os.stat_result) -> FileVersion:
        if not S_ISREG(stat.st_mode):
            raise PdfSourceError("PDF source requires a regular file")
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    def _signature(self, path: Path) -> tuple[FileVersion, str]:
        if path.resolve(strict=True) != path:
            raise PdfSourceError("PDF path changed after authorization")
        file_version = self._file_version(path.stat())
        try:
            fingerprint = self._source.fingerprint
        except Exception as exc:
            raise PdfSourceError("PDF source fingerprint is unavailable") from exc
        if not isinstance(fingerprint, str) or not fingerprint:
            raise PdfSourceError("PDF source must have a parser fingerprint")
        return file_version, fingerprint

    def current(self, path: Path, binding: PdfBinding) -> bool:
        """Check metadata only; permission preflight must not parse or open the PDF."""
        try:
            return self._signature(path) == (binding.file_version, binding.fingerprint)
        except (OSError, RuntimeError):
            return False

    def load(self, path: Path) -> LoadedPdf:
        with self._lock:
            file_version, fingerprint = self._signature(path)
            cached = self._entries.pop(path, None)
            if cached and (file_version, fingerprint) == (
                cached[0].binding.file_version, cached[0].binding.fingerprint,
            ):
                self._entries[path] = cached
                return cached[0]

            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            flags |= getattr(os, "O_BINARY", 0)
            with os.fdopen(os.open(path, flags), "rb") as stream:
                if self._file_version(os.fstat(stream.fileno())) != file_version:
                    raise PdfSourceError("PDF source changed before parsing; call sro_preview again")
                content_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            if self._signature(path) != (file_version, fingerprint):
                raise PdfSourceError("PDF source changed before parsing; call sro_preview again")
            snapshot = self._source.open(path)
            if self._signature(path) != (file_version, fingerprint):
                raise PdfSourceError("PDF source changed during parsing; call sro_preview again")
            if not isinstance(snapshot, PdfSnapshot):
                raise PdfSourceError("PDF source must return a PdfSnapshot")
            identity = hashlib.sha256(
                repr((content_hash, fingerprint, snapshot.version)).encode("utf-8")
            ).hexdigest()
            loaded = LoadedPdf(PdfBinding(file_version, fingerprint, identity), snapshot)
            size = sum(
                128 + len(unit.text) + len(unit.ref) + sum(map(len, unit.heading_path))
                + len(unit.citation_uri or "") + 128 * len(unit.provenance)
                for unit in snapshot.units
            ) + sum(64 + len(section.title) + len(section.ref) for section in snapshot.outline)
            if size <= self._MAX_CHARS:
                self._entries[path] = loaded, size
                while len(self._entries) > self._MAX_SNAPSHOTS or sum(
                    weight for _, weight in self._entries.values()
                ) > self._MAX_CHARS:
                    self._entries.popitem(last=False)
            return loaded
