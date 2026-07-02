"""
Secondary review cleaner for LLM-generated Markdown notes.

After the summarizer produces an initial draft, the ReviewCleaner
performs a quality-control pass to catch and fix:
- Raw code blocks that are PPT artifacts (not legitimate examples)
- Garbled text from binary extraction
- Broken or inconsistent Markdown formatting
- PPT metadata remnants (slide numbers, timestamps, headers)
- Unescaped LaTeX that could break PDF rendering

Supports two modes:
  - ``basic`` : regex-based cleanup only (no extra API cost)
  - ``deep``  : second LLM review pass for thorough content quality check
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    """Result of the secondary review pass."""

    cleaned_content: str
    issues_found: list[str] = field(default_factory=list)
    changes_made: int = 0


# ---------------------------------------------------------------------------
# Patterns for basic (regex-based) cleanup
# ---------------------------------------------------------------------------

# Slide number artifacts like "--- Slide 1 ---", "Slide 5 of 30"
_SLIDE_MARKER_RE = re.compile(
    r"(?:\n|^)-{3,}\s*Slide\s+\d+\s*(?:of\s+\d+)?\s*-{3,}\s*\n?", re.IGNORECASE
)

# Raw PPT metadata lines: timestamps, slide master names, etc.
_PPT_META_RE = re.compile(
    r"^\s*(?:\d{1,2}[:：]\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?|"
    r"Slide\s+\d+\s*$|"
    r"\[.*?(?:Speaker\s*Notes?|备注|Note).*?\])\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Lines that are >70% non-alphanumeric garbage (binary extraction artifacts)
_GARBAGE_LINE_RE = re.compile(r"^[^a-zA-Z0-9一-鿿]{10,}$")

# Excessive whitespace: 4+ consecutive blank lines
_MULTI_BLANK_RE = re.compile(r"\n{4,}")

# Code blocks without language tag (likely artifacts rather than intentional code)
_BARE_CODE_BLOCK_RE = re.compile(r"```\s*\n(.*?)```", re.DOTALL)

# Suspiciously long code blocks (>40 lines) that probably are extraction artifacts
_LONG_CODE_BLOCK_RE = re.compile(r"```\w*\n(.{2000,}?)```", re.DOTALL)

# Raw escape sequences from PDF/PPT extraction
_ESCAPE_SEQ_RE = re.compile(r"\\x[0-9a-fA-F]{2}|\\u[0-9a-fA-F]{4}|\\n|\\r|\\t")

# PPT control characters
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Broken URL artifacts
_BROKEN_URL_RE = re.compile(r"https?://\S*\.\.\.?\s*$", re.MULTILINE)

# Encoding mojibake patterns (common in CJK text extraction)
_MOJIBASE_RE = re.compile(r"[�]{2,}")  # replacement chars
_MOJIBASE_ISO_RE = re.compile(
    r"(?:Ã[€¢£¤¥¦§¨©ª«¬­®¯°±²³]|"  # common UTF-8 mis-decoded as Latin-1
    r"â<80><99>|â<80><9c>|â<80><9d>|â<80>"  # smart quotes
    r")+"
)

# LaTeX fragments that are clearly garbled
_GARBLED_LATEX_RE = re.compile(r"\${1,2}[^$]{0,2}\${1,2}")  # empty/malformed $...$

# ANSI escape sequences (often from terminal output artifacts)
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# Unicode private use area (PUA) characters – often PPT-specific symbols
_PUA_CHARS_RE = re.compile(r"[-0-￿Dက00-ჿFD]+")

# Isolated Unicode symbols/dingbats that are likely extraction artifacts
_SYMBOL_GARBAGE_RE = re.compile(r"[■-◿☀-⛿✀-➿⌀-⏿]{3,}")

# Lines that are ONLY punctuation, symbols, or whitespace (no letters/numbers/CJK)
_PUNCT_ONLY_LINE_RE = re.compile(
    r"^\s*[\s\.\,\;\:\!\?\-\+\=\*\/\\\|\(\)\[\]\{\}<>@#\$%\^&\*_~`'\""
    r" -⁯　、。，．：；！？"
    r"‘’“”–—… "
    r"]+\s*$"
)

# Garbled character sequences: random mixes of Latin/numbers/symbols with no pattern
# (common in binary extraction where UTF-8 is misaligned)
_RANDOM_CHAR_RUN_RE = re.compile(r"[^\s]{20,}")  # 20+ chars without space (likely garbled)

# Null bytes and BOM artifacts
_NULL_BOM_RE = re.compile(r"[\x00\xEF\xBB\xBF\xFE\xFF]")

# PPT table cell artifacts: lines like "| |   |   |" or "|:---|:---|"
_EMPTY_TABLE_ROW_RE = re.compile(r"^\|[\s\|\-\:]*\|[\s\|\-\:]*$", re.MULTILINE)

# Common PPT text artifacts: "Click to edit", "Enter title", etc.
_PPT_EDITOR_UI_RE = re.compile(
    r"(?i)(click\s+to\s+(add|edit)\s+\w+|"
    r"enter\s+(your\s+)?(title|text|subtitle|notes)|"
    r"placeholder\s+\w+|"
    r"\[Type\s+\w+\s+here\])"
)


class ReviewCleaner:
    """
    Post-processes LLM-generated Markdown to remove artifacts and improve quality.

    Parameters
    ----------
    llm_client : LiteLLMClient | None
        Optional LLM client for deep review mode. If None, only basic
        (regex-based) cleaning is available.
    review_mode : str
        ``"off"``, ``"basic"`` (default), or ``"deep"``.
    """

    def __init__(self, llm_client=None, review_mode: str = "basic") -> None:
        self.llm = llm_client
        self.review_mode = review_mode

    def review(self, raw_markdown: str) -> ReviewResult:
        """
        Run the secondary review on *raw_markdown*.

        Parameters
        ----------
        raw_markdown : str
            The raw Markdown output from the summarizer.

        Returns
        -------
        ReviewResult
            Cleaned content with issue report.
        """
        if self.review_mode == "off" or not raw_markdown.strip():
            return ReviewResult(cleaned_content=raw_markdown)

        issues: list[str] = []
        content = raw_markdown

        # ---- Phase 1: Basic regex cleanup (always runs) ----
        content, basic_issues = self._basic_clean(content)
        issues.extend(basic_issues)

        # ---- Phase 2: Deep LLM review (optional) ----
        if self.review_mode == "deep" and self.llm is not None:
            try:
                content, deep_issues = self._deep_review(content)
                issues.extend(deep_issues)
            except Exception as exc:
                logger.warning(f"Deep review failed, using basic-cleaned output: {exc}")
                issues.append(f"[WARN] Deep review skipped: {exc}")

        changes = len(issues)
        if changes > 0:
            logger.info(f"Review complete: {changes} issue(s) addressed")
            for issue in issues:
                logger.debug(f"  - {issue}")

        return ReviewResult(
            cleaned_content=content,
            issues_found=issues,
            changes_made=changes,
        )

    # ------------------------------------------------------------------
    # Basic cleanup (regex-based, no API cost)
    # ------------------------------------------------------------------

    def _basic_clean(self, content: str) -> tuple[str, list[str]]:
        """Run all regex-based cleanup filters."""
        issues: list[str] = []

        # 1. Remove control characters
        before = len(content)
        content = _CONTROL_CHARS_RE.sub("", content)
        if len(content) < before:
            issues.append("Removed control characters")

        # 2. Remove slide markers
        before_count = len(_SLIDE_MARKER_RE.findall(content))
        if before_count > 0:
            content = _SLIDE_MARKER_RE.sub("\n", content)
            issues.append(f"Removed {before_count} slide marker(s)")

        # 3. Remove PPT metadata lines
        before_count = len(_PPT_META_RE.findall(content))
        if before_count > 0:
            content = _PPT_META_RE.sub("", content)
            issues.append(f"Removed {before_count} PPT metadata line(s)")

        # 4. Normalize excessive whitespace
        before_count = len(_MULTI_BLANK_RE.findall(content))
        if before_count > 0:
            content = _MULTI_BLANK_RE.sub("\n\n\n", content)
            issues.append(f"Normalized {before_count} excessive blank section(s)")

        # 5. Detect and strip garbage lines
        lines = content.split("\n")
        cleaned_lines = []
        garbage_count = 0
        for line in lines:
            if _GARBAGE_LINE_RE.match(line) and len(line) > 15:
                garbage_count += 1
                continue
            cleaned_lines.append(line)
        if garbage_count > 0:
            content = "\n".join(cleaned_lines)
            issues.append(f"Removed {garbage_count} garbage line(s)")

        # 6. Strip mojibake patterns
        if _MOJIBASE_RE.search(content):
            content = _MOJIBASE_RE.sub("", content)
            issues.append("Stripped replacement-character mojibake")

        # 7. Fix empty/malformed LaTeX
        broken_latex = _GARBLED_LATEX_RE.findall(content)
        if broken_latex:
            content = _GARBLED_LATEX_RE.sub("", content)
            issues.append(f"Fixed {len(broken_latex)} malformed LaTeX fragment(s)")

        # 8. Remove encoding mojibake (Latin-1 mis-decoded UTF-8)
        if _MOJIBASE_ISO_RE.search(content):
            content = _MOJIBASE_ISO_RE.sub("", content)
            issues.append("Stripped encoding mojibake")

        # 9. Strip broken URL artifacts
        broken_urls = len(_BROKEN_URL_RE.findall(content))
        if broken_urls > 0:
            content = _BROKEN_URL_RE.sub("", content)
            issues.append(f"Removed {broken_urls} broken URL artifact(s)")

        # 10. Detect and label suspiciously long code blocks
        long_blocks = _LONG_CODE_BLOCK_RE.findall(content)
        if long_blocks:
            for i, block in enumerate(long_blocks):
                placeholder = (
                    f"\n> [Review note: Long code block ({len(block):,} chars) "
                    f"may contain extraction artifacts. Verify correctness.]\n\n"
                )
                content = content.replace(block, placeholder, 1)
            issues.append(f"Flagged {len(long_blocks)} suspicious long code block(s)")

        # 11. Strip ANSI escape sequences
        ansi_count = len(_ANSI_ESCAPE_RE.findall(content))
        if ansi_count > 0:
            content = _ANSI_ESCAPE_RE.sub("", content)
            issues.append(f"Removed {ansi_count} ANSI escape sequence(s)")

        # 12. Strip Unicode private use area characters
        pua_count = len(_PUA_CHARS_RE.findall(content))
        if pua_count > 0:
            content = _PUA_CHARS_RE.sub("", content)
            issues.append(f"Removed {pua_count} private-use character(s)")

        # 13. Strip isolated symbol runs (dingbats from PPT)
        symbol_runs = _SYMBOL_GARBAGE_RE.findall(content)
        if symbol_runs:
            content = _SYMBOL_GARBAGE_RE.sub("", content)
            issues.append(f"Removed {len(symbol_runs)} symbol-garbage run(s)")

        # 14. Remove punctuation-only lines
        lines = content.split("\n")
        punct_count = 0
        cleaned = []
        for line in lines:
            if _PUNCT_ONLY_LINE_RE.match(line):
                punct_count += 1
                continue
            cleaned.append(line)
        if punct_count > 0:
            content = "\n".join(cleaned)
            issues.append(f"Removed {punct_count} punctuation-only line(s)")

        # 15. Flag suspiciously long unbroken strings (possible binary artifact)
        long_runs = _RANDOM_CHAR_RUN_RE.findall(content)
        if long_runs:
            filtered_runs = [r for r in long_runs if not any(
                c.isalpha() and c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                for c in r[:5]
            )]
            for run in filtered_runs[:10]:  # Limit replacements
                content = content.replace(run, "", 1)
            if filtered_runs:
                issues.append(f"Removed {len(filtered_runs)} garbled char run(s)")

        # 16. Strip null bytes and BOM
        null_count = len(_NULL_BOM_RE.findall(content))
        if null_count > 0:
            content = _NULL_BOM_RE.sub("", content)
            issues.append(f"Removed {null_count} null/BOM byte(s)")

        # 17. Remove empty table rows
        empty_rows = len(_EMPTY_TABLE_ROW_RE.findall(content))
        if empty_rows > 0:
            content = _EMPTY_TABLE_ROW_RE.sub("", content)
            issues.append(f"Removed {empty_rows} empty table row(s)")

        # 18. Remove PPT editor UI artifacts
        ui_artifacts = _PPT_EDITOR_UI_RE.findall(content)
        if ui_artifacts:
            for artifact in set(ui_artifacts):
                content = content.replace(artifact, "")
            issues.append(f"Removed {len(ui_artifacts)} PPT editor UI artifact(s)")

        # Final pass: remove doubled blank lines from all the removals
        content = _MULTI_BLANK_RE.sub("\n\n\n", content)

        return content, issues

    # ------------------------------------------------------------------
    # Deep review (LLM-based, thorough content check)
    # ------------------------------------------------------------------

    _DEEP_REVIEW_SYSTEM_PROMPT = """\
You are a meticulous technical editor reviewing AI-generated lecture notes.
Your job is to identify and fix quality issues in the Markdown content.

REVIEW CHECKLIST – fix ALL of the following:
1. **Code artifacts**: Remove any raw code blocks that are PPT extraction \
artifacts (not legitimate programming examples). Legitimate code examples \
should have a language tag (e.g. ```python) and be clearly related to the \
lecture content.
2. **Garbled text**: Find and remove any character sequences that are clearly \
binary extraction artifacts: random symbols, mojibake, Unicode replacement \
characters (U+FFFD), or nonsensical character runs.
3. **Formatting**: Ensure consistent Markdown formatting. Fix broken lists, \
unclosed code fences, and missing blank lines between sections.
4. **LaTeX/CJK quality**: Check that all LaTeX math is properly wrapped in \
$...$ or $$...$$. Ensure no CJK characters appear inside LaTeX math blocks.
5. **PPT metadata**: Remove any remaining slide numbers, timestamps, or \
presentation metadata that leaked through.
6. **Content accuracy**: Flag (with an HTML comment <!-- REVIEW: ... -->) any \
factually questionable claims or contradictions.

IMPORTANT RULES:
- Preserve ALL legitimate educational content. Do NOT remove real code examples, \
  formulas, or explanations.
- Maintain the original bilingual Chinese/English structure.
- Do NOT rewrite the entire document. Only fix what is broken.
- If the content is already clean, return it unchanged.
- NEVER add ```markdown fences around the entire output."""

    def _deep_review(self, content: str) -> tuple[str, list[str]]:
        """
        Send the content through a second LLM pass for thorough review.

        Only fixes problematic sections; preserves clean content as-is.
        """
        if len(content) < 200:
            return content, ["Content too short for deep review, skipped"]

        # Truncate extremely long content to avoid excessive API cost
        # (the review model only needs to see enough to identify patterns)
        review_content = content
        if len(content) > 15000:
            # Keep first 8000 + last 4000 chars (intro + conclusion are most important)
            review_content = content[:8000] + "\n\n[... middle section omitted for review ...]\n\n" + content[-4000:]
            logger.info(f"Deep review: content truncated from {len(content):,} to {len(review_content):,} chars")

        prompt = f"""\
Review the following lecture notes for artifacts and formatting issues.
Return the CLEANED version with all issues fixed.

CONTENT TO REVIEW:
---
{review_content}
---

Return the full cleaned Markdown. If no issues found, return the content unchanged."""

        try:
            raw = self.llm.complete(prompt, system_prompt=self._DEEP_REVIEW_SYSTEM_PROMPT)
        except Exception as exc:
            raise RuntimeError(f"Deep review LLM call failed: {exc}")

        # Detect if the LLM made changes
        issues: list[str] = []
        if raw.strip() != content.strip():
            # Count approximate changes
            diff_ratio = abs(len(raw) - len(content)) / max(len(content), 1)
            if diff_ratio > 0.01:
                issues.append(f"Deep review: content changed ({diff_ratio:.0%} delta)")
            else:
                issues.append("Deep review: minor corrections applied")

        return raw.strip(), issues
