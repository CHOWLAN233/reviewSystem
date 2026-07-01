"""
Abstract base class for document parsers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class AbstractParser(ABC):
    """Interface that all document parsers must implement."""

    @abstractmethod
    def extract_text(self, filepath: Path) -> str:
        """Extract all text content from the file."""

    @abstractmethod
    def extract_pages_text(self, filepath: Path, start: int, count: int) -> str:
        """
        Extract text from a contiguous range of slides/pages.

        Parameters
        ----------
        filepath : Path
        start : int
            Zero-based starting page/slide index.
        count : int
            Number of pages/slides to extract.
        """

    @abstractmethod
    def get_page_count(self, filepath: Path) -> int:
        """Return the total number of slides or pages in the file."""
