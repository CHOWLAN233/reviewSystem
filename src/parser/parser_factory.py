"""
Parser factory: maps file extensions to parser instances.
"""

from pathlib import Path

from .base_parser import AbstractParser
from .pptx_parser import PPTXParser
from .pdf_parser import PDFParser


def get_parser(filepath: Path) -> AbstractParser:
    """
    Return the appropriate parser for *filepath* based on its extension.

    Raises
    ------
    ValueError
        If the file extension is not supported.
    """
    ext = filepath.suffix.lower()
    if ext in (".pptx", ".ppt"):
        return PPTXParser()
    if ext == ".pdf":
        return PDFParser()
    raise ValueError(f"Unsupported file type: {ext!r} (supported: .pptx, .ppt, .pdf)")
