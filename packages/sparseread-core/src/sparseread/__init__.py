"""Framework-neutral SparseRead public API."""

from sparseread.config import SparseReadConfig
from sparseread.core.readers.native_pdf import NativePdfSource
from sparseread.pdf import PdfLocation, PdfSection, PdfSnapshot, PdfSource, PdfSourceError, PdfUnit
from sparseread.wrapper import SparseRead, SparseReadAgentWrapper, wrap

__version__ = "0.1.4"

__all__ = [
    "NativePdfSource",
    "PdfLocation",
    "PdfSection",
    "PdfSnapshot",
    "PdfSource",
    "PdfSourceError",
    "PdfUnit",
    "SparseRead",
    "SparseReadAgentWrapper",
    "SparseReadConfig",
    "__version__",
    "wrap",
]
