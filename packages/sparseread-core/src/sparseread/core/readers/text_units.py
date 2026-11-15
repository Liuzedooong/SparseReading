"""Shared text segmentation for prose and the native PDF parser."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from sparseread.pdf import PdfUnit

_LONG_UNIT_CHARS = 1600
_LONG_UNIT_OVERLAP = 180


@dataclass(slots=True)
class TextUnit:
    anchor: str
    text: str
    heading: str = ""
    pdf: PdfUnit | None = None
    pdf_version: str = ""

    @property
    def is_table(self) -> bool:
        return self.pdf is not None and self.pdf.kind in {"table", "table_row"}

    def source(self, version: str) -> dict | None:
        if self.pdf is None:
            return None
        data = {
            "ref": self.pdf.ref,
            "parse_version": version,
            "kind": self.pdf.kind,
            "heading_path": list(self.pdf.heading_path),
        }
        if self.pdf.provenance:
            data["provenance"] = [
                {key: value for key, value in asdict(location).items() if value is not None}
                for location in self.pdf.provenance
            ]
        if self.pdf.citation_uri:
            data["citation_uri"] = self.pdf.citation_uri
        return data


def segment_text(
    text: str, *, kind: str, page: int | None = None,
) -> tuple[list[TextUnit], list[str], str]:
    lines = text.splitlines()
    units: list[TextUnit] = []
    skeleton: list[str] = []
    buf: list[str] = []
    start_line = 1
    heading = ""

    def flush(end_line: int) -> None:
        nonlocal buf, start_line
        raw = "\n".join(buf).strip()
        if raw:
            prefix = f"p{page}:" if page is not None else ""
            _append_text_units(units, prefix, start_line, end_line, raw, heading)
        buf = []
        start_line = end_line + 1

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        is_heading = looks_like_heading(stripped)
        is_list = looks_like_list_item(line)
        if is_heading:
            flush(idx - 1)
            heading = stripped
            skeleton.append(f"p{page} {stripped}" if page is not None else stripped)
            start_line = idx
            buf = [line]
            continue
        if not stripped:
            flush(idx - 1)
            continue
        if is_list and buf and len("\n".join(buf)) > 500:
            flush(idx - 1)
        if not buf:
            start_line = idx
        buf.append(line)
        if len("\n".join(buf)) > 1200:
            flush(idx)
    flush(len(lines))
    return units, dedupe(skeleton), kind

def _append_text_units(
    units: list[TextUnit],
    prefix: str,
    start_line: int,
    end_line: int,
    raw: str,
    heading: str,
) -> None:
    base_anchor = f"{prefix}L{start_line}-L{end_line}"
    if len(raw) <= _LONG_UNIT_CHARS:
        units.append(TextUnit(anchor=base_anchor, text=raw, heading=heading))
        return
    for char_start, char_end, chunk in _split_long_text(raw):
        units.append(TextUnit(anchor=f"{base_anchor}:C{char_start}-{char_end}", text=chunk, heading=heading))

def _split_long_text(text: str) -> list[tuple[int, int, str]]:
    chunks: list[tuple[int, int, str]] = []
    start = 0
    length = len(text)
    while start < length:
        hard_end = min(length, start + _LONG_UNIT_CHARS)
        end = hard_end
        if hard_end < length:
            window = text[start:hard_end]
            sentence_breaks = [window.rfind(mark) for mark in (". ", "? ", "! ")]
            best_sentence = max(sentence_breaks)
            if best_sentence >= _LONG_UNIT_CHARS // 2:
                end = start + best_sentence + 1
            else:
                space = window.rfind(" ")
                if space >= _LONG_UNIT_CHARS // 2:
                    end = start + space
        chunk = text[start:end].strip()
        if chunk:
            chunks.append((start, end, chunk))
        if end >= length:
            break
        start = max(end - _LONG_UNIT_OVERLAP, start + 1)
    return chunks

def looks_like_list_item(line: str) -> bool:
    return bool(re.match(r"^\s*(?:[-*]|\d+[.)])\s+\S", line))


def looks_like_heading(stripped: str) -> bool:
    if not stripped or len(stripped) > 140:
        return False
    if "http://" in stripped or "https://" in stripped:
        return False
    if re.fullmatch(r"[\d\s./:%-]+", stripped):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z&/+.-]*", stripped)
    if not words or len(words) > 18:
        return False
    digit_count = sum(ch.isdigit() for ch in stripped)
    if digit_count > max(3, len(stripped) // 5):
        return False
    if stripped.startswith("#"):
        return True
    if re.match(r"^\d+(?:\.\d+)*[.)]?\s+\S", stripped):
        return True
    if stripped.isupper() and len(words) >= 2:
        return True
    if stripped.endswith((".", "?", "!", ";")):
        return False
    capitalized = sum(1 for word in words if word[:1].isupper())
    return capitalized >= max(1, len(words) - 1)

def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out
