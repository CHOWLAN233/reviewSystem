"""
AI-powered lecture classifier.

Two-step lightweight classification:
    1. Extract text from the first N slides/pages.
    2. Send to a cheap LLM for structured metadata extraction (JSON).

Includes fallback to filename regex when the LLM is unavailable or
produces unparseable output.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..llm.litellm_client import LiteLLMClient, LiteLLMError
from ..parser import get_parser
from prompts.classification import (
    CLASSIFIER_SYSTEM_PROMPT,
    build_classification_user_prompt,
)

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Structured metadata extracted from a lecture file."""

    course_name: str
    week_number: int
    topic: str
    has_lab: bool
    confidence: float = 1.0
    raw_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_name": self.course_name,
            "week_number": self.week_number,
            "topic": self.topic,
            "has_lab": self.has_lab,
            "confidence": self.confidence,
        }


class AIClassifier:
    """
    Classifies lecture files by extracting course name, week number,
    topic, and lab detection via a lightweight LLM.
    """

    def __init__(
        self,
        llm_client: LiteLLMClient,
        slide_count: int = 3,
    ) -> None:
        """
        Parameters
        ----------
        llm_client : LiteLLMClient
            A client configured with a cheap / fast model.
        slide_count : int
            Number of beginning slides/pages to send for classification.
        """
        self.llm = llm_client
        self.slide_count = slide_count

    def classify(self, filepath: Path) -> ClassificationResult:
        """
        Parse the first *slide_count* slides/pages of *filepath* and
        classify via LLM.

        Parameters
        ----------
        filepath : Path
            Path to the lecture file.

        Returns
        -------
        ClassificationResult
        """
        filename = filepath.name

        # 1. Extract text snippet
        try:
            parser = get_parser(filepath)
            page_count = parser.get_page_count(filepath)
            pages_to_read = min(self.slide_count, max(page_count, 1))
            text_snippet = parser.extract_pages_text(filepath, 0, pages_to_read)
        except Exception as exc:
            logger.warning(f"Could not parse {filename}: {exc}. Falling back to filename regex.")
            return self._regex_from_filename(filename)

        if not text_snippet.strip():
            logger.warning(f"No text extracted from {filename}. Falling back to filename regex.")
            return self._regex_from_filename(filename)

        # 2. Call LLM
        user_prompt = build_classification_user_prompt(filename, text_snippet)
        try:
            raw = self.llm.complete(user_prompt, system_prompt=CLASSIFIER_SYSTEM_PROMPT)
            result = self._parse_response(raw, filename)

            # If LLM didn't detect a week number, try filename extraction
            if result.week_number == 0:
                fname_week = self._extract_week_from_filename(filename)
                if fname_week > 0:
                    logger.info(
                        f"LLM returned week=0 for {filename!r}, "
                        f"but filename suggests week={fname_week}. Using filename week."
                    )
                    result.week_number = fname_week
                    result.confidence = min(result.confidence, 0.8)

            logger.info(
                f"Classified {filename!r}: course={result.course_name!r}, "
                f"week={result.week_number}, topic={result.topic!r}, "
                f"has_lab={result.has_lab}, confidence={result.confidence:.2f}"
            )
            return result
        except LiteLLMError as exc:
            logger.warning(f"LLM classification failed for {filename}: {exc}. Using regex fallback.")
            return self._regex_from_filename(filename)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse_response(self, raw: str, filename: str) -> ClassificationResult:
        """Parse the LLM response into a ``ClassificationResult``."""
        try:
            data = json.loads(raw.strip())
            confidence = 1.0
        except json.JSONDecodeError:
            # Try to extract JSON from markdown or mixed text
            data = self._extract_json(raw)
            confidence = 0.7 if data else 0.0

        if not data:
            logger.debug(f"JSON parse failed for {filename}, falling back to regex.")
            return self._regex_from_filename(filename)

        result = ClassificationResult(
            course_name=str(data.get("course_name", "Unknown Course")).strip(),
            week_number=self._safe_int(data.get("week_number", 0)),
            topic=str(data.get("topic", "Unknown Topic")).strip(),
            has_lab=bool(data.get("has_lab", False)),
            confidence=confidence,
            raw_response=raw,
        )
        return self._validate(result)

    def _validate(self, result: ClassificationResult) -> ClassificationResult:
        """Sanitize and validate the classification result."""
        # Ensure week_number is non-negative
        if result.week_number < 0:
            result.week_number = 0

        # Fall back for empty strings
        if not result.course_name:
            result.course_name = "Unknown Course"
            result.confidence = min(result.confidence, 0.3)
        if not result.topic:
            result.topic = "Unknown Topic"

        return result

    @staticmethod
    def _safe_int(value: Any) -> int:
        """Coerce *value* to int, defaulting to 0."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """Try to extract a JSON object from arbitrary text."""
        # Strip markdown code fences
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        # Find first { ... } block
        match = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _extract_week_from_filename(filename: str) -> int:
        """
        Extract week/lecture number from filename patterns.

        Supports:
        - ``Lecture 3.pdf``, ``lecture5.pptx``
        - ``Week 3``, ``week03``
        - ``第3周``, ``第 3 讲``
        - ``W3_xxx``, ``L05_xxx``
        """
        import re
        name = Path(filename).stem

        patterns = [
            r"[Ll]ecture\s*(\d+)",
            r"[Ww]eek\s*(\d+)",
            r"第\s*(\d+)\s*[周讲课]",
            r"\b[Ww](\d+)\b",
            r"\b[Ll](\d+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, name)
            if m:
                return int(m.group(1))
        return 0

    @staticmethod
    def _regex_from_filename(filename: str) -> ClassificationResult:
        """
        Fallback classification using filename pattern matching.

        Supports patterns like:
        - ``CS101_Week1_Intro.pptx``
        - ``第3周_操作系统.pptx``
        - ``week3_lab.pdf``
        - ``Lecture_05_Neural_Networks.pptx``
        """
        name = Path(filename).stem

        # Extract week number
        week = 0
        week_patterns = [
            (r"[Ww]eek\s*(\d+)", False),
            (r"[Ll]ecture\s*(\d+)", False),
            (r"第\s*(\d+)\s*[周讲]", False),
            (r"[Ww](\d+)", False),
            (r"[Ll](\d+)", False),
            (r"(\d+)[-_]?", True),  # generic number – only if nothing else matched
        ]
        for pattern, _ in week_patterns:
            m = re.search(pattern, name)
            if m:
                week = int(m.group(1))
                break

        # Detect lab keywords
        lab_patterns = [
            r"[Ll]ab", r"[Ll]aboratory", r"[Ee]xperiment",
            r"[Pp]ractical", r"[Aa]ssignment",
            r"实验", r"上机", r"作业", r"实训",
            r"[Hh]ands[-\s]?[Oo]n", r"[Ww]orkshop",
        ]
        has_lab = any(re.search(p, name) for p in lab_patterns)

        # Try to extract a readable course name / topic from the filename
        # Replace underscores and hyphens with spaces, strip week/lab artifacts
        cleaned = re.sub(r"[_\-]+", " ", name)
        cleaned = re.sub(
            r"\b(W|L|Week|Lecture|Lab|第)\s*\d+\b", "", cleaned, flags=re.IGNORECASE
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        if not cleaned:
            cleaned = name

        logger.info(f"Regex fallback for {filename!r}: course={cleaned!r}, week={week}, has_lab={has_lab}")

        return ClassificationResult(
            course_name=cleaned if len(cleaned) < 50 else cleaned[:50] + "...",
            week_number=week,
            topic=cleaned if len(cleaned) < 80 else cleaned[:80] + "...",
            has_lab=has_lab,
            confidence=0.3,
        )
