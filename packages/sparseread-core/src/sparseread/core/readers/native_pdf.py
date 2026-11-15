"""Built-in PDF source with the legacy parser and text layout."""

from __future__ import annotations

import shutil
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from sparseread.core.readers.text_units import segment_text
from sparseread.pdf import PdfLocation, PdfSection, PdfSnapshot, PdfSourceError, PdfUnit


class NativePdfSource:
    @property
    def fingerprint(self) -> str:
        executable = shutil.which("pdftotext")
        if executable:
            binary = Path(executable).resolve()
            stat = binary.stat()
            return f"native-text-v1:pdftotext-layout:{binary}:{stat.st_ino}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"
        try:
            pymupdf = version("pymupdf")
        except PackageNotFoundError:
            pymupdf = "unavailable"
        return f"native-text-v1:pymupdf:{pymupdf}"

    def open(self, path: Path) -> PdfSnapshot:
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            pages = self._pages_with_pymupdf(path)
        else:
            if result.returncode != 0:
                detail = (result.stderr or "").strip() or f"pdftotext exited with {result.returncode}"
                raise PdfSourceError(detail)
            pages = (result.stdout or "").split("\f")

        units: list[PdfUnit] = []
        outline: list[PdfSection] = []
        for page, text in enumerate(pages, start=1):
            page_units, headings, _ = segment_text(text, kind="pdf", page=page)
            refs: dict[str, str] = {}
            for unit in page_units:
                units.append(PdfUnit(
                    unit.anchor, unit.text,
                    heading_path=(unit.heading,) if unit.heading else (),
                    provenance=(PdfLocation(page),),
                ))
                refs.setdefault(f"p{page} {unit.heading}", unit.anchor)
            outline.extend(PdfSection(refs[heading], heading) for heading in headings if heading in refs)
        return PdfSnapshot("native-text-v1", tuple(units), tuple(outline[:24]))

    @staticmethod
    def _pages_with_pymupdf(path: Path) -> list[str]:
        try:
            import fitz
        except ImportError as exc:
            raise PdfSourceError("PDF reading requires pdftotext or pymupdf") from exc
        try:
            doc = fitz.open(str(path))
        except Exception as exc:
            raise PdfSourceError(f"pymupdf failed to open PDF: {exc}") from exc
        with doc:
            return [page.get_text("text") for page in doc]
