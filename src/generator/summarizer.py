"""
Lecture summarizer – transforms raw slide text into structured review notes.

Uses a powerful LLM to expand, explain, and organize lecture content
into a student-friendly Markdown format.

Supports chunked processing for long input texts that exceed context limits.
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

    # Maximum characters per chunk (~300K chars ≈ 70K tokens for mixed CJK text)
    # Modern LLMs (DeepSeek, Claude, Gemini) support 128K+ context windows,
    # so larger chunks dramatically reduce LLM API calls without quality loss.
    MAX_CHUNK_CHARS = 300000

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
        Generate a structured lecture summary, chunking if needed.

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
        # Clean the input text: remove non-readable garbage from binary extraction
        full_text = self._clean_text(full_text)

        if not full_text.strip():
            return LectureSummary(
                outline="*No readable text could be extracted from this file.*",
            )

        logger.info(
            f"Summarizing: {classification.course_name} Week {classification.week_number}"
            f" ({len(full_text):,} chars)"
        )

        # If text fits within limit, process in one call
        if len(full_text) <= self.MAX_CHUNK_CHARS:
            return self._single_summarize(full_text, classification)

        # Otherwise, chunk and process in multiple calls
        logger.info(
            f"Text too long ({len(full_text):,} chars). "
            f"Splitting into chunks of {self.MAX_CHUNK_CHARS:,} chars."
        )
        return self._chunked_summarize(full_text, classification)

    # ------------------------------------------------------------------
    # Single-pass summarization
    # ------------------------------------------------------------------

    def _single_summarize(
        self, text: str, classification: ClassificationResult
    ) -> LectureSummary:
        """Process text in a single LLM call."""
        user_prompt = build_summarization_user_prompt(
            classification.course_name,
            classification.week_number,
            classification.topic,
            text,
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
    # Chunked summarization
    # ------------------------------------------------------------------

    def _chunked_summarize(
        self, full_text: str, classification: ClassificationResult
    ) -> LectureSummary:
        """
        Split long text into chunks, summarize each, then merge.

        Strategy:
        1. Split at slide boundaries (--- Slide N ---)
        2. Summarize each chunk with a focused prompt
        3. Merge chunk summaries into one final note
        """
        chunks = self._split_at_slide_boundaries(full_text)
        logger.info(f"Split into {len(chunks)} chunk(s) for processing")

        chunk_summaries: list[str] = []

        for i, chunk in enumerate(chunks):
            logger.info(
                f"Processing chunk {i+1}/{len(chunks)} "
                f"({len(chunk):,} chars)"
            )

            if i == 0:
                # First chunk: full structured summary
                summary = self._summarize_first_chunk(chunk, classification, i+1, len(chunks))
            else:
                # Subsequent chunks: extract key points only
                summary = self._summarize_continuation_chunk(chunk, classification, i+1, len(chunks))

            chunk_summaries.append(summary)

        # Merge all chunk summaries
        if len(chunk_summaries) == 1:
            return self._parse_response(chunk_summaries[0])

        merged = self._merge_chunk_summaries(chunk_summaries, classification)
        return merged

    def _summarize_first_chunk(
        self, chunk: str, classification: ClassificationResult,
        chunk_num: int, total: int
    ) -> str:
        """Summarize the first chunk with the full system prompt."""
        prefix = f"[Part {chunk_num}/{total} – this is the FIRST part of the lecture content]\n\n"
        text = prefix + chunk

        if len(text) > self.MAX_CHUNK_CHARS:
            text = text[:self.MAX_CHUNK_CHARS] + "\n\n[... Truncated ...]"

        user_prompt = build_summarization_user_prompt(
            classification.course_name,
            classification.week_number,
            classification.topic,
            text,
        )

        try:
            return self.llm.complete(user_prompt, system_prompt=SUMMARIZER_SYSTEM_PROMPT)
        except LiteLLMError as exc:
            logger.error(f"Chunk {chunk_num} summarization failed: {exc}")
            return f"## 1. Core Knowledge Outline\n\n*Processing failed for part {chunk_num}: {exc}*\n"

    def _summarize_continuation_chunk(
        self, chunk: str, classification: ClassificationResult,
        chunk_num: int, total: int
    ) -> str:
        """Summarize a continuation chunk – extract key additions only."""
        prefix = (
            f"[Part {chunk_num}/{total} – CONTINUATION of the lecture content. "
            f"Focus on NEW concepts not covered in previous parts.]\n\n"
        )
        text = prefix + chunk

        if len(text) > self.MAX_CHUNK_CHARS:
            text = text[:self.MAX_CHUNK_CHARS] + "\n\n[... Truncated ...]"

        prompt = f"""\
Course: {classification.course_name}
Week: {classification.week_number}
Topic: {classification.topic}

This is part {chunk_num} of {total} of the lecture content. Previous parts have already
been summarized. Extract ONLY the new key points, concepts, and details from this
section that were NOT likely covered in earlier parts.

Lecture slide text (part {chunk_num}/{total}):
---
{text}
---

Output your findings in this structure:

## New Concepts in Part {chunk_num}
[Bullet points of new topics/concepts introduced in this section]

## Key Details & Examples
[Important details, examples, or explanations from this section.
Use bilingual format: Chinese first, then English.]"""

        try:
            return self.llm.complete(prompt, system_prompt=SUMMARIZER_SYSTEM_PROMPT)
        except LiteLLMError as exc:
            logger.error(f"Chunk {chunk_num} summarization failed: {exc}")
            return f"## New Concepts in Part {chunk_num}\n\n*Processing failed: {exc}*\n"

    def _merge_chunk_summaries(
        self, chunk_summaries: list[str], classification: ClassificationResult
    ) -> LectureSummary:
        """
        Merge multiple chunk summaries into one coherent note.

        Uses a final LLM call to synthesize all chunk outputs.
        """
        combined = "\n\n---\n\n".join(
            f"### Part {i+1} Summary\n{s}"
            for i, s in enumerate(chunk_summaries)
        )

        # If combined is short enough, do a merge pass
        if len(combined) <= self.MAX_CHUNK_CHARS:
            merge_prompt = f"""\
Course: {classification.course_name}
Week: {classification.week_number}
Topic: {classification.topic}

Below are {len(chunk_summaries)} partial summaries of a long lecture.
Merge them into ONE coherent, deduplicated review note following the
standard bilingual structure. Remove redundant content across parts.

Partial summaries:
---
{combined}
---

Generate a complete, merged review note with all standard sections:
## 1. 核心知识大纲 / Core Knowledge Outline
## 2. 关键概念与术语表 / Key Concepts & Glossary
## 3. 重点总结 / Critical Takeaways
## 4. 详细笔记（AI 扩展）/ Detailed Notes (AI-Expanded)"""

            try:
                raw = self.llm.complete(merge_prompt, system_prompt=SUMMARIZER_SYSTEM_PROMPT)
                return self._parse_response(raw)
            except LiteLLMError as exc:
                logger.error(f"Merge summarization failed: {exc}")
                # Fall through to local merge

        # Local merge: concatenate with clear separation
        merged = (
            f"## 1. 核心知识大纲 / Core Knowledge Outline\n\n"
            f"*This lecture was processed in {len(chunk_summaries)} parts.*\n\n"
            f"{combined}"
        )
        return LectureSummary(
            outline=f"*Lecture processed in {len(chunk_summaries)} parts – see detailed notes below.*",
            detailed_notes=merged,
            raw_content=combined,
        )

    # ------------------------------------------------------------------
    # Text cleaning
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_text(text: str) -> str:
        """
        Remove garbled/non-readable characters that come from binary extraction.

        Filters out:
        - Non-printable control chars (except newlines, tabs)
        - Isolated Unicode symbols that are likely extraction artifacts
        - Lines that are >80% non-alphanumeric (garbage lines)
        """
        # Remove null bytes and other zero-width characters
        text = text.replace("\x00", "")

        # Keep only printable characters + common whitespace + common CJK + common Latin
        cleaned_lines = []
        for line in text.split("\n"):
            # Filter to keep readable characters
            filtered = []
            for ch in line:
                cp = ord(ch)
                # Printable ASCII
                if 0x20 <= cp <= 0x7E:
                    filtered.append(ch)
                # Common Latin extensions
                elif 0xA0 <= cp <= 0x24F:
                    filtered.append(ch)
                # CJK and fullwidth forms
                elif 0x2E80 <= cp <= 0x9FFF:
                    filtered.append(ch)
                elif 0xF900 <= cp <= 0xFAFF:
                    filtered.append(ch)
                elif 0xFF00 <= cp <= 0xFFEF:
                    filtered.append(ch)
                # Newline, tab, carriage return
                elif cp in (0x09, 0x0A, 0x0D):
                    filtered.append(ch)
                # Skip other characters (likely binary artifacts)

            line = "".join(filtered).strip()

            # Skip lines that are mostly garbage
            if line:
                alpha_ratio = sum(1 for c in line if c.isalnum() or c.isspace()) / max(len(line), 1)
                if alpha_ratio >= 0.3 and len(line) >= 3:
                    cleaned_lines.append(line)

        result = "\n".join(cleaned_lines)

        # Remove excessive consecutive blank lines
        result = re.sub(r"\n{4,}", "\n\n\n", result)

        logger.info(f"Text cleaning: {len(text):,} → {len(result):,} chars "
                     f"({100*len(result)/max(len(text),1):.0f}% retained)")

        return result

    # ------------------------------------------------------------------
    # Chunk splitting
    # ------------------------------------------------------------------

    def _split_at_slide_boundaries(self, text: str) -> list[str]:
        """
        Split text at slide boundary markers (--- Slide N ---).

        Each chunk stays under MAX_CHUNK_CHARS while respecting slide boundaries.
        """
        # Split on slide markers
        slides = re.split(r"\n(?=---\s*Slide\s+\d+\s*---)", text)

        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for slide in slides:
            slide_len = len(slide)
            if current_len + slide_len > self.MAX_CHUNK_CHARS and current:
                chunks.append("\n".join(current))
                current = [slide]
                current_len = slide_len
            else:
                current.append(slide)
                current_len += slide_len

        if current:
            chunks.append("\n".join(current))

        return chunks if chunks else [text]

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, raw: str) -> LectureSummary:
        """Parse the LLM's Markdown response into structured sections."""
        outline = self._extract_section(raw, "Core Knowledge Outline")
        takeaways = self._extract_section(raw, "Critical Takeaways")
        detailed = self._extract_section(raw, "Detailed Notes")
        glossary = self._extract_glossary(raw)

        if not outline:
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
        Extract content under a markdown header matching *header* keyword(s).

        Supports bilingual headers like ``## 1. 核心知识大纲 / Core Knowledge Outline``
        by matching any ``## ...`` line that contains the *header* substring.
        """
        escaped = re.escape(header)
        pattern = rf"##\s+.*?{escaped}.*?\s*\n(.*?)(?=\n##\s|\Z)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

        pattern_loose = rf"{escaped}\s*\n(.*?)(?=\n##\s|\Z)"
        match = re.search(pattern_loose, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

        return ""

    def _extract_glossary(self, text: str) -> list[GlossaryEntry]:
        """Parse the glossary table from the markdown."""
        section = self._extract_section(text, "Key Concepts & Glossary")
        if not section:
            return []

        entries: list[GlossaryEntry] = []
        table_pattern = r"\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|"
        for match in re.finditer(table_pattern, section):
            term = match.group(1).strip()
            definition = match.group(2).strip()
            analogy = match.group(3).strip()

            if term.lower() in ("term", "术语", "术语 term", "---", ":---"):
                continue
            if all(c in "-: |" for c in term):
                continue

            entries.append(GlossaryEntry(term=term, definition=definition, analogy=analogy))

        return entries
