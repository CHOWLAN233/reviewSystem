"""
Lab solver – generates complete lab solutions, pitfalls, and checklists.

Uses a code-capable LLM to produce working solutions with explanations,
common debugging tips, and environment setup instructions.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ..llm.litellm_client import LiteLLMClient, LiteLLMError
from ..classifier.ai_classifier import ClassificationResult
from prompts.lab_solving import (
    LAB_SOLVER_SYSTEM_PROMPT,
    build_lab_solving_user_prompt,
)

logger = logging.getLogger(__name__)


@dataclass
class LabSolution:
    """Structured output from the lab solver."""

    objectives: str = ""
    solutions: str = ""
    pitfalls: str = ""
    environment_checklist: str = ""
    raw_content: str = ""


class LabSolver:
    """Generate complete lab solution guides with explanations and pitfalls."""

    def __init__(self, llm_client: LiteLLMClient) -> None:
        """
        Parameters
        ----------
        llm_client : LiteLLMClient
            A client configured with a code-capable model.
        """
        self.llm = llm_client

    def solve(
        self, full_text: str, classification: ClassificationResult
    ) -> LabSolution:
        """
        Generate a complete lab solution guide.

        Parameters
        ----------
        full_text : str
            The complete extracted text from the lab document.
        classification : ClassificationResult
            Metadata providing course context.

        Returns
        -------
        LabSolution
        """
        user_prompt = build_lab_solving_user_prompt(
            classification.course_name,
            classification.week_number,
            classification.topic,
            full_text,
        )

        logger.info(
            f"Solving lab: {classification.course_name} Week {classification.week_number}"
        )
        try:
            raw = self.llm.complete(user_prompt, system_prompt=LAB_SOLVER_SYSTEM_PROMPT)
        except LiteLLMError as exc:
            logger.error(f"Lab solving failed: {exc}")
            return LabSolution(
                objectives=f"*Lab solving failed: {exc}*",
                raw_content=str(exc),
            )

        return self._parse_response(raw)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse_response(self, raw: str) -> LabSolution:
        """Parse the LLM's Markdown response into structured sections."""
        return LabSolution(
            objectives=self._extract_section(raw, "Lab Objectives"),
            solutions=self._extract_section(raw, "Solutions & Explanations"),
            pitfalls=self._extract_section(raw, "Common Pitfalls & Debugging Tips"),
            environment_checklist=self._extract_section(
                raw, "Environment & Dependencies Checklist"
            ),
            raw_content=raw,
        )

    def _extract_section(self, text: str, header: str) -> str:
        """
        Extract content under a markdown header matching *header* keyword(s).

        Supports bilingual headers like ``## 实验目标 / Lab Objectives``
        by matching any ``## ...`` line that contains the *header* substring.
        """
        escaped = re.escape(header)
        pattern = rf"##\s+.*?{escaped}.*?\s*\n(.*?)(?=\n##\s+\S|\Z)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Looser fallback
        pattern_loose = rf"{escaped}\s*\n(.*?)(?=\n##\s+\S|\Z)"
        match = re.search(pattern_loose, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

        return ""
