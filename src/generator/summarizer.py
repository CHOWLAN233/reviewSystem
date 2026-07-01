"""
Lecture summarizer – transforms raw slide text into structured review notes.

Uses a powerful LLM to expand, explain, and organize lecture content
into a student-friendly Markdown format.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ..llm.litellm_client import LiteLLMClient, LiteLLMError
from ..classifier.ai_classifier import ClassificationResult
from prompts.summarization import (
    SUMMARIZER_SYSTEM_PROMPT,
    build_summarization_user_prompt,
)

logger = logging.getLogger(__name__)


@dataclass
class GlossaryEntry:
    """One row in the concept glossary table."""

    term: str
    definition: str
    analogy: str


@dataclass
class LectureSummary:
    """Structured output from the lecture summarizer."""

    outline: str
    glossary: list[GlossaryEntry] = field(default_factory=list)
    takeaways: str = ""
    detailed_notes: str = ""
    raw_content: str = ""


class LectureSummarizer:
    """Generate comprehensive, structured review notes from lecture slides."""

    def __init__(self, llm_client: LiteLLMClient) -> None:
        """
        Parameters
        ----------
        llm_client : LiteLLMClient
            A client configured with a powerful model for deep content generation.
        """
        self.llm = llm_client

    def summarize(
        self, full_text: str, classification: ClassificationResult
    ) -> LectureSummary:
        """
        Generate a structured lecture summary.

        Parameters
        ----------
        full_text : str
            The complete extracted text from all slides.
        classification : ClassificationResult
            Metadata from the classifier (provides context to the LLM).

        Returns
        -------
        LectureSummary
        """
        user_prompt = build_summarization_user_prompt(
            classification.course_name,
            classification.week_number,
            classification.topic,
            full_text,
        )

        logger.info(
            f"Summarizing: {classification.course_name} Week {classification.week_number}"
        )
        try:
            raw = self.llm.complete(user_prompt, system_prompt=SUMMARIZER_SYSTEM_PROMPT)
        except LiteLLMError as exc:
            logger.error(f"Summarization failed: {exc}")
            return LectureSummary(
                outline=f"*Summarization failed: {exc}*",
                raw_content=str(exc),
            )

        return self._parse_response(raw)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse_response(self, raw: str) -> LectureSummary:
        """Parse the LLM's Markdown response into structured sections."""
        outline = self._extract_section(raw, "1. Core Knowledge Outline")
        takeaways = self._extract_section(raw, "3. Critical Takeaways")
        detailed = self._extract_section(raw, "4. Detailed Notes")
        glossary = self._extract_glossary(raw)

        # Fallback: if a section is empty, use whatever content exists
        if not outline:
            # Use the content between ## 1. and ## 2. (or end)
            outline = self._extract_section(raw, "1.", fallback_header="## 2.")

        return LectureSummary(
            outline=outline or raw[:500] + "...",
            glossary=glossary,
            takeaways=takeaways or "",
            detailed_notes=detailed or raw,
            raw_content=raw,
        )

    def _extract_section(
        self, text: str, header: str, fallback_header: str = ""
    ) -> str:
        """
        Extract content under a markdown header like ``## 1. Core Knowledge Outline``.

        Returns everything between *header* and the next ``##`` header,
        or the end of text.
        """
        # Escape for regex but keep basic patterns
        escaped = re.escape(header)
        pattern = rf"##\s+{escaped}\s*\n(.*?)(?=\n##\s|\Z)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Try a looser match
        pattern_loose = rf"{escaped}\s*\n(.*?)(?=\n##\s|\Z)"
        match = re.search(pattern_loose, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

        return ""

    def _extract_glossary(self, text: str) -> list[GlossaryEntry]:
        """
        Parse the glossary table from the markdown.

        Looks for a markdown table after the ``## 2. Key Concepts & Glossary`` header.
        """
        section = self._extract_section(text, "2. Key Concepts & Glossary")
        if not section:
            return []

        entries: list[GlossaryEntry] = []
        # Find markdown table rows: | col1 | col2 | col3 |
        table_pattern = r"\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|"
        for match in re.finditer(table_pattern, section):
            term = match.group(1).strip()
            definition = match.group(2).strip()
            analogy = match.group(3).strip()

            # Skip header rows
            if term.lower() in ("term", "术语", "---", ":---"):
                continue
            # Skip separator lines
            if all(c in "-: |" for c in term):
                continue

            entries.append(GlossaryEntry(term=term, definition=definition, analogy=analogy))

        return entries
