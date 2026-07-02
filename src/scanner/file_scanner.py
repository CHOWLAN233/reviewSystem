"""
Scans the input directory (recursively) for supported lecture files.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class FileScanner:
    """Discover supported PPT/PDF files in the input directory and its subdirectories."""

    def __init__(self, input_dir: Path, extensions: tuple[str, ...]) -> None:
        """
        Parameters
        ----------
        input_dir : Path
            The directory to scan.
        extensions : tuple of str
            Supported file extensions, e.g. ``('.pptx', '.ppt', '.pdf')``.
        """
        self.input_dir = input_dir
        self.extensions = tuple(e.lower() for e in extensions)

    def scan(self) -> list[Path]:
        """
        Return absolute paths of all files whose extension is in *extensions*,
        sorted by filename for deterministic processing order.

        Scans recursively into subdirectories. Subfolder names can be used
        as course-name hints during classification.
        """
        if not self.input_dir.exists():
            logger.warning(f"Input directory does not exist: {self.input_dir}")
            return []

        files: list[Path] = []
        for ext in self.extensions:
            files.extend(self.input_dir.rglob(f"*{ext}"))
            files.extend(self.input_dir.rglob(f"*{ext.upper()}"))

        # De-duplicate while preserving order
        seen: set[str] = set()
        unique: list[Path] = []
        for f in sorted(files, key=lambda p: p.name.lower()):
            resolved = str(f.resolve())
            if resolved not in seen:
                seen.add(resolved)
                unique.append(f)

        logger.info(f"Scanner found {len(unique)} supported file(s) in {self.input_dir}")
        return unique

    def get_scan_info(self) -> list[dict]:
        """
        Return a list of dicts with file path and subfolder info.

        Returns
        -------
        list[dict]
            Each dict has 'path' (Path), 'subfolder' (str or None).
        """
        files = self.scan()
        result = []
        for fp in files:
            try:
                rel = fp.relative_to(self.input_dir)
                subfolder = str(rel.parent) if str(rel.parent) != "." else None
            except ValueError:
                subfolder = None
            result.append({"path": fp, "subfolder": subfolder})
        return result

    def get_file_count(self) -> int:
        """Return the number of supported files found in the input directory."""
        return len(self.scan())
