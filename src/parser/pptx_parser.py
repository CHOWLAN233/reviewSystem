"""
PPTX file parser using python-pptx.

Extracts text from slide shapes (text frames, tables, group shapes)
and speaker notes.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pptx import Presentation
from pptx.shapes.base import BaseShape
from pptx.table import Table

from .base_parser import AbstractParser

logger = logging.getLogger(__name__)


class PPTXParserError(Exception):
    """Raised when a PPTX file cannot be parsed."""


class PPTXParser(AbstractParser):
    """Extract text from PowerPoint (.pptx) files."""

    def extract_text(self, filepath: Path) -> str:
        """Iterate all slides and extract text from every shape."""
        prs = self._open(filepath)
        parts: list[str] = []
        for idx, slide in enumerate(prs.slides, start=1):
            slide_lines: list[str] = [f"\n--- Slide {idx} ---"]
            for shape in slide.shapes:
                text = self._extract_shape_text(shape)
                if text.strip():
                    slide_lines.append(text)
            # Speaker notes
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    slide_lines.append(f"[Speaker Notes]: {notes}")
            parts.append("\n".join(slide_lines))
        return "\n".join(parts)

    def extract_pages_text(self, filepath: Path, start: int, count: int) -> str:
        """Extract text from slides [*start*, *start* + *count*)."""
        prs = self._open(filepath)
        total = len(prs.slides)
        end = min(start + count, total)
        parts: list[str] = []
        for idx in range(start, end):
            slide = prs.slides[idx]
            slide_lines: list[str] = [f"\n--- Slide {idx + 1} ---"]
            for shape in slide.shapes:
                text = self._extract_shape_text(shape)
                if text.strip():
                    slide_lines.append(text)
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    slide_lines.append(f"[Speaker Notes]: {notes}")
            parts.append("\n".join(slide_lines))
        return "\n".join(parts)

    def get_page_count(self, filepath: Path) -> int:
        """Return the number of slides."""
        prs = self._open(filepath)
        return len(prs.slides)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _open(self, filepath: Path) -> Presentation:
        """Open the presentation, raising ``PPTXParserError`` on failure."""
        try:
            return Presentation(str(filepath))
        except Exception as exc:
            raise PPTXParserError(f"Failed to open {filepath.name}: {exc}") from exc

    def _extract_shape_text(self, shape: BaseShape) -> str:
        """Extract text from a shape, handling text frames, tables, and groups."""
        # Text frame (most common)
        if shape.has_text_frame:
            paragraphs = []
            for para in shape.text_frame.paragraphs:
                p_text = para.text.strip()
                if p_text:
                    paragraphs.append(p_text)
            return "\n".join(paragraphs)

        # Table
        if shape.has_table:
            table: Table = shape.table
            rows = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                rows.append(" | ".join(c for c in cells if c))
            return "\n".join(rows)

        # Group shape – recurse
        if shape.shape_type == 6:  # MSO_SHAPE_TYPE.GROUP
            try:
                return "\n".join(
                    self._extract_shape_text(s) for s in shape.shapes
                )
            except AttributeError:
                pass

        return ""
