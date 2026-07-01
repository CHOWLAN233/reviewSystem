"""
PDF file parser using PyMuPDF (fitz).

Extracts text from each page with page markers.
"""

from __future__ import annotations

import logging
from pathlib import Path

import fitz  # PyMuPDF

from .base_parser import AbstractParser

logger = logging.getLogger(__name__)


class PDFParserError(Exception):
    """Raised when a PDF file cannot be parsed."""


class PDFParser(AbstractParser):
    """Extract text from PDF files via PyMuPDF."""

    def extract_text(self, filepath: Path) -> str:
        """Extract text from all pages."""
        doc = self._open(filepath)
        parts: list[str] = []
        for idx, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            if text:
                parts.append(f"\n--- Page {idx} ---\n{text}")
        doc.close()
        return "\n".join(parts)

    def extract_pages_text(self, filepath: Path, start: int, count: int) -> str:
        """Extract text from pages [*start*, *start* + *count*)."""
        doc = self._open(filepath)
        total = doc.page_count
        end = min(start + count, total)
        parts: list[str] = []
        for idx in range(start, end):
            text = doc[idx].get_text().strip()
            if text:
                parts.append(f"\n--- Page {idx + 1} ---\n{text}")
        doc.close()
        return "\n".join(parts)

    def get_page_count(self, filepath: Path) -> int:
        """Return the number of pages."""
        doc = self._open(filepath)
        count = doc.page_count
        doc.close()
        return count

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _open(self, filepath: Path) -> fitz.Document:
        """Open the PDF, raising ``PDFParserError`` on failure."""
        try:
            return fitz.open(str(filepath))
        except Exception as exc:
            raise PDFParserError(f"Failed to open {filepath.name}: {exc}") from exc
