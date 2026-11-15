"""Public contract for local PDF sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol


class PdfSourceError(RuntimeError):
    """An authorized PDF could not be parsed into a usable snapshot."""


@dataclass(frozen=True, slots=True)
class PdfLocation:
    page: int
    bbox: tuple[float, float, float, float] | None = None
    coord_origin: Literal["top_left", "bottom_left"] = "top_left"
    page_size: tuple[float, float] | None = None
    char_span: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class PdfUnit:
    ref: str
    text: str
    kind: str = "text"
    heading_path: tuple[str, ...] = ()
    provenance: tuple[PdfLocation, ...] = ()
    citation_uri: str | None = None


@dataclass(frozen=True, slots=True)
class PdfSection:
    ref: str
    title: str
    level: int = 1


@dataclass(frozen=True, slots=True)
class PdfSnapshot:
    version: str
    units: tuple[PdfUnit, ...]
    outline: tuple[PdfSection, ...] = ()

    def __post_init__(self) -> None:
        if not self.version:
            raise PdfSourceError("PDF snapshot must have a parse version")
        refs = {unit.ref for unit in self.units}
        if "" in refs or len(refs) != len(self.units):
            raise PdfSourceError("PDF units must have unique nonempty refs")
        if any(section.ref not in refs for section in self.outline):
            raise PdfSourceError("PDF outline refs must refer to a unit")


class PdfSource(Protocol):
    @property
    def fingerprint(self) -> str:
        """Identify the parser implementation, version and parsing configuration."""
        ...

    def open(self, path: Path) -> PdfSnapshot:
        """Parse one canonical local path already authorized by the caller."""
        ...
