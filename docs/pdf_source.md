# Implementing a local PDF source

A PDF source supplies a parsed view of one local PDF. SparseRead handles
artifact identity, reading policy, selection, budgets, and evidence state.
The default `NativePdfSource` keeps the existing Poppler/PyMuPDF behavior.
A contributor can implement a different source in a separate package and
enable it explicitly from Python.

```python
from pathlib import Path

from sparseread import PdfSection, PdfSnapshot, PdfSource, PdfUnit, SparseRead, SparseReadConfig


class ExamplePdfSource:
    fingerprint = "example:1.0:layout-default"

    def open(self, path: Path) -> PdfSnapshot:
        # A test double. A real source parses the authorized PDF at path.
        return PdfSnapshot(
            version="example-output-v1",
            units=(
                PdfUnit("#/headings/0", "Results", "heading", ("Results",)),
                PdfUnit("#/texts/0", "Owner: Ada", heading_path=("Results",)),
            ),
            outline=(PdfSection("#/headings/0", "Results"),),
        )


source: PdfSource = ExamplePdfSource()
runtime = SparseRead(SparseReadConfig(workspace="/path/to/project", pdf_source=source))
preview = runtime.orchestrator.preview("/path/to/project/report.pdf")
raw = runtime.orchestrator.raw(preview.raw_ref, selector="#/texts/0")
```

The public types are exported from `sparseread`. Python hosts can pass the
same config to `wrap(agent, config=...)`. Bridge implementations can pass
`pdf_source=...` to `SparseReadBridgeServer` at startup. Stock CLI installations
use the built-in source. Select the provider in trusted host setup. The host
continues to authorize each file access through its existing permission
mechanism, including when a cached snapshot can be reused. Direct Python
callers are responsible for authorizing the files they pass to the runtime.

## Provider input and output

- `open(path)` receives a canonical path to one authorized regular local
  PDF. Parse only that file and raise `PdfSourceError` when a usable snapshot
  cannot be produced. Keep parsing local and read-only. Arrange dependency and
  model setup in the optional provider package, outside the core installation.
- `fingerprint` identifies the parser implementation, version, and
  output-affecting configuration. Include applicable layout, OCR, table, and
  model revisions. Keep this property cheap and free of I/O on source contents.
  The bridge can read it before opening the file. Change it whenever existing
  parsed output may be invalid.
- `PdfSnapshot.version` is an opaque stable parse revision. Return the same
  value, units, refs and outline when parsing the same bytes with the same
  fingerprint. Core derives the effective `parse_version` from the file
  SHA-256, parser fingerprint and snapshot version. Use immutable tuples.
- `PdfUnit.ref` is an opaque unique node identifier inside the snapshot.
  Keep it stable within the parse. Units follow reading order. `kind`
  distinguishes headings, text, tables, rows, and other semantic units.
  `heading_path` lists titles from outermost to innermost section. An outline
  entry points to an existing unit, with a title and one-based hierarchy level.
- `PdfLocation.page` is one-based. `bbox` is `(left, top, right, bottom)`
  in source coordinates. Include `coord_origin` and `page_size` when available.
  An optional `char_span` is a zero-based, end-exclusive range in that unit's
  text, using Unicode characters. Multiple locations can describe a span across
  pages. Omit unknown metadata. A provider may supply an authoritative
  `citation_uri` for a node. This is descriptive data; the runtime returns it
  without resolving it.
- For `table` and `table_row`, use a representation that preserves which
  headers, values, units and rows belong together. For a large table, prefer
  independently meaningful rows with their headers and refs. SparseRead can
  return a complete table unit in focused evidence when it fits. It omits
  units that exceed the selection limit instead of slicing rows. Its legacy
  slot selector does not infer individual cell values from table units; if
  the best slot match is a table, it reports partial coverage and the source
  ref. An explicit raw read can retrieve that node.

## Identity, errors and compatibility

Open a fresh path with `sro_preview`. Later reads use the same artifact and
parse version. A successful preview, focus, collect and raw can all share the
same parse. Local file identity and the parser fingerprint are checked on
reuse. The runtime keeps a small, bounded cache; eviction or a snapshot too
large to retain can trigger a reload. The runtime checks that the reloaded
version matches before serving an existing reference.

If the local source or parser configuration changes, refresh with
`sro_preview`. A stale raw reference fails, ready evidence for the prior
parse is dropped, and a failed preview produces no new raw reference. An
explicitly selected provider's error is returned through the existing read
or preview error fields. A caller can then use its authorized native tool
or start a runtime with a different provider and preview again.

Native PDF and non-PDF success responses retain their previous fields. For
an injected source, preview adds `structure.parse_version` and an outline.
Preview samples, selected evidence blocks, and attributable slots may
include a `source` object with `ref`, `parse_version`, `kind`, `heading_path`,
`provenance`, and optional `citation_uri`. A block's provenance identifies
the source unit; it does not certify a clipped excerpt or a derived slot
value as a verbatim quote.

Use the opaque `raw_ref` from preview. With an injected source, an exact
`selector` matching a unit ref returns that unit in the `extracted_text`
view, including its line breaks. A supplied range is relative to the unit
and its response is capped at 50,000 characters. Otherwise the existing
document range and text search forms apply. References are scoped to the
runtime conversation where they were issued.

## Scope of the first Docling contribution

Implement the local `DoclingPdfSource` in an optional distribution or
dependency group. Map reading-order nodes into immutable units, keep
Docling refs and available provenance, preserve table header associations,
and declare the supported Docling versions and parsing options. Keep
selection, `HintSpec`, Gate behavior, evidence closure and fallback in
SparseRead. A remotely hosted document needs a separate design for
authorization and navigation.

Add fixture tests for two-column order, nested sections, merged or
multi-page tables, and missing provenance. Test that one parse serves
`preview → focus/collect → raw`; that a same-size file replacement,
configuration change or parser error cannot revive old references or
ready state; and that a payload requiring a partial table does not look
like complete evidence. Run the core suite with and without the optional
dependency. Keep fixtures small and record the Docling version, model
configuration and any OCR requirements for real parses.
