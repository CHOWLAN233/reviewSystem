"""
Markdown writer -- renders structured content into .md files and
organizes them in the output directory tree.

Output layout:
    02_Output_Notes/
    └── {Course_Name}/
        ├── md/                                    <-- all .md files at course level
        │   ├── Week_01_Topic_summary.md
        │   └── Week_01_Topic_lab_solution.md      (if has_lab)
        ├── Week_01_Topic/
        │   ├── summary.pdf                         (after PDF conversion)
        │   ├── lab_solution.pdf                    (after PDF conversion)
        │   └── original_file.ppt                   (copy for reference)
        └── Week_02_Another_Topic/
            └── ...
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..classifier.ai_classifier import ClassificationResult
from .summarizer import LectureSummary
from .lab_solver import LabSolution

logger = logging.getLogger(__name__)


class MarkdownWriter:
    """Creates output directories and writes rendered Markdown files atomically."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ensure_output_dir(
        self, classification: ClassificationResult, source_filename: str = ""
    ) -> Path:
        """
        Create (if needed) and return the output directory for this lecture.

        Naming priority:
        1. If week > 0 AND a folder for this (course, week) already exists,
           reuse the existing folder name (even if topic differs).
        2. If week > 0 and no existing folder: ``Week_{week:02d}_{topic_slug}/``
        3. If week == 0: use sanitized original PPT filename as folder name

        This prevents duplicate folders when two files (e.g. PPT + PDF)
        of the same lecture are classified with slightly different topics.

        Parameters
        ----------
        classification : ClassificationResult
        source_filename : str
            Original filename, used as fallback folder name when week is unknown.

        Returns
        -------
        Path
            The created (or existing) output directory for PDFs and source copies.
        """
        course = self._sanitize(classification.course_name)
        course_dir = self.output_dir / course

        if classification.week_number > 0:
            week_prefix = f"Week_{classification.week_number:02d}_"

            # Check if a folder for this (course, week) already exists.
            # If so, reuse it to avoid duplicates when two files of the
            # same lecture (e.g. PPT + PDF) are classified with slightly
            # different topic names.
            existing = self._find_existing_week_folder(course_dir, week_prefix)
            if existing is not None:
                logger.info(
                    f"Reusing existing folder for week {classification.week_number}: "
                    f"{existing.name} (classified topic: {classification.topic})"
                )
                return existing

            topic_slug = self._sanitize(classification.topic)
            folder_name = week_prefix + topic_slug
        else:
            if source_filename:
                stem = Path(source_filename).stem
                folder_name = self._sanitize(stem)
            else:
                topic_slug = self._sanitize(classification.topic)
                folder_name = f"Unknown_{topic_slug}"

        dir_path = course_dir / folder_name
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output directory: {dir_path}")
        return dir_path

    def get_md_dir(self, classification: ClassificationResult) -> Path:
        """
        Return the course-level ``md/`` directory where all .md files
        for this course are stored.

        Parameters
        ----------
        classification : ClassificationResult

        Returns
        -------
        Path
            e.g. ``02_Output_Notes/SOF_103/md/``
        """
        course = self._sanitize(classification.course_name)
        md_dir = self.output_dir / course / "md"
        md_dir.mkdir(parents=True, exist_ok=True)
        return md_dir

    def get_week_folder_name(self, classification: ClassificationResult, source_filename: str = "") -> str:
        """
        Return the week folder name (without course prefix) used for
        naming md files and the week output directory.

        Returns
        -------
        str
            e.g. ``Week_01_Introduction``
        """
        if classification.week_number > 0:
            topic_slug = self._sanitize(classification.topic)
            return f"Week_{classification.week_number:02d}_{topic_slug}"
        else:
            if source_filename:
                stem = Path(source_filename).stem
                return self._sanitize(stem)
            else:
                topic_slug = self._sanitize(classification.topic)
                return f"Unknown_{topic_slug}"

    def write_summary(
        self,
        output_dir: Path,
        classification: ClassificationResult,
        summary: LectureSummary,
        source_filename: str,
    ) -> Path:
        """
        Render and write ``summary.md`` into the course-level ``md/`` folder.

        The file is named ``{week_folder_name}_summary.md``.

        Returns the path to the written file.
        """
        content = self._render_summary(classification, summary, source_filename)
        md_dir = self.get_md_dir(classification)
        week_name = self.get_week_folder_name(classification, source_filename)
        filepath = md_dir / f"{week_name}_summary.md"
        self._atomic_write(filepath, content)
        logger.info(f"Wrote summary: {filepath}")
        return filepath

    def write_lab_solution(
        self,
        output_dir: Path,
        classification: ClassificationResult,
        solution: LabSolution,
        source_filename: str,
    ) -> Path:
        """
        Render and write ``lab_solution.md`` into the course-level ``md/`` folder.

        The file is named ``{week_folder_name}_lab_solution.md``.

        Returns the path to the written file.
        """
        content = self._render_lab(classification, solution, source_filename)
        md_dir = self.get_md_dir(classification)
        week_name = self.get_week_folder_name(classification, source_filename)
        filepath = md_dir / f"{week_name}_lab_solution.md"
        self._atomic_write(filepath, content)
        logger.info(f"Wrote lab solution: {filepath}")
        return filepath

    def get_relative_output_path(
        self, output_dir: Path
    ) -> str:
        """Return *output_dir* relative to ``self.output_dir``."""
        try:
            return str(output_dir.relative_to(self.output_dir))
        except ValueError:
            return str(output_dir)

    # ------------------------------------------------------------------
    # Render helpers
    # ------------------------------------------------------------------

    def _render_summary(
        self,
        classification: ClassificationResult,
        summary: LectureSummary,
        source_filename: str,
    ) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        lines: list[str] = [
            f"# {classification.course_name} Week {classification.week_number}: {classification.topic}",
            "",
            f"> Generated by Review Agent on {timestamp}  ",
            f"> Source: `{source_filename}`  ",
            f"> Classification confidence: {classification.confidence:.0%}",
            "",
            "---",
            "",
            "## 1. Core Knowledge Outline",
            "",
            summary.outline or "*No outline generated.*",
            "",
        ]

        if summary.glossary:
            lines.extend([
                "---",
                "",
                "## 2. Key Concepts & Glossary",
                "",
                "| Term | Definition | Memory Anchor / Analogy |",
                "|:-----|:-----------|:------------------------|",
            ])
            for entry in summary.glossary:
                lines.append(
                    f"| {entry.term} | {entry.definition} | {entry.analogy} |"
                )
            lines.append("")

        if summary.takeaways:
            lines.extend([
                "---",
                "",
                "## 3. Critical Takeaways",
                "",
                summary.takeaways,
                "",
            ])

        lines.extend([
            "---",
            "",
            "## 4. Detailed Notes (AI-Expanded)",
            "",
            summary.detailed_notes or summary.outline or "*No detailed notes generated.*",
            "",
        ])

        return "\n".join(lines)

    def _render_lab(
        self,
        classification: ClassificationResult,
        solution: LabSolution,
        source_filename: str,
    ) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        lines: list[str] = [
            f"# {classification.course_name} Week {classification.week_number}: Lab Solution -- {classification.topic}",
            "",
            f"> Generated by Review Agent on {timestamp}  ",
            f"> Source: `{source_filename}`",
            "",
            "---",
            "",
            "## Lab Objectives",
            "",
            solution.objectives or "*No objectives specified.*",
            "",
            "---",
            "",
            "## Solutions & Explanations",
            "",
            solution.solutions or "*No solutions generated.*",
            "",
            "---",
            "",
            "## Common Pitfalls & Debugging Tips",
            "",
            solution.pitfalls or "*No pitfalls identified.*",
            "",
            "---",
            "",
            "## Environment & Dependencies Checklist",
            "",
            solution.environment_checklist or "*No special dependencies.*",
            "",
        ]

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _find_existing_week_folder(course_dir: Path, week_prefix: str) -> Path | None:
        """
        Scan *course_dir* for a folder whose name starts with *week_prefix*.

        Returns the first match, or None if no such folder exists.
        """
        if not course_dir.exists():
            return None
        for entry in sorted(course_dir.iterdir()):
            if entry.is_dir() and entry.name.startswith(week_prefix):
                return entry
        return None

    def _sanitize(self, name: str) -> str:
        """
        Replace characters that are illegal in file/directory names
        on Windows / macOS / Linux with underscores.
        """
        # Characters illegal in at least one major OS
        illegal = r'[<>:"/\\|?*\x00-\x1f]'
        sanitized = re.sub(illegal, "_", name)
        # Trim trailing dots and spaces (Windows restriction)
        sanitized = sanitized.rstrip(". ")
        # Limit length for practicality
        if len(sanitized) > 100:
            sanitized = sanitized[:100]
        return sanitized or "Unknown"

    def _atomic_write(self, filepath: Path, content: str) -> None:
        """
        Write *content* to *filepath* atomically:

        1. Write to a temporary file in the same directory.
        2. ``os.replace`` the temp file to the target (atomic on POSIX,
           near-atomic on Windows for same-volume moves).
        """
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Write to a temp file in the same directory (same filesystem -> atomic rename)
        fd, tmp_path = tempfile.mkstemp(
            suffix=".md", prefix=".tmp_", dir=str(filepath.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.replace(tmp_path, filepath)
        except Exception:
            # Clean up temp file on failure
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
