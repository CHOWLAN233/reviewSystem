"""
Core pipeline orchestrator.

Wires together scanning, state management, parsing, classification,
summarization, lab solving, and markdown writing into a single
end-to-end workflow.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .config.settings import Settings
from .scanner.file_scanner import FileScanner
from .scanner.state_manager import StateManager, FileRecord
from .parser.parser_factory import get_parser
from .parser.pptx_parser import PPTXParserError
from .parser.pdf_parser import PDFParserError
from .llm.litellm_client import LiteLLMClient, LiteLLMError
from .classifier.ai_classifier import AIClassifier, ClassificationResult
from .generator.summarizer import LectureSummarizer
from .generator.lab_solver import LabSolver
from .generator.markdown_writer import MarkdownWriter

logger = logging.getLogger(__name__)


@dataclass
class ProcessedFile:
    """Result for a single processed file."""

    filename: str
    status: str  # "processed" | "error" | "skipped"
    course: str = ""
    week: int = 0
    topic: str = ""
    output_path: str = ""
    error: str = ""


@dataclass
class ProcessingReport:
    """Summary report returned by ``Pipeline.run()``."""

    total_scanned: int = 0
    new_or_changed: int = 0
    processed: int = 0
    errors: int = 0
    skipped: int = 0
    details: list[ProcessedFile] = field(default_factory=list)
    elapsed_seconds: float = 0.0


# Type alias for progress callbacks
ProgressCallback = Callable[[str, float], None]


class Pipeline:
    """
    End-to-end pipeline: scan → classify → summarize → (lab solve) → write.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        # Ensure directories exist
        settings.ensure_directories()

        # ---- Sub-components ----
        self.scanner = FileScanner(settings.input_dir, settings.supported_extensions)
        self.state_manager = StateManager(settings.state_file)

        # LLM clients – one per role
        self.classifier_llm = LiteLLMClient(
            model=settings.classifier_model,
            api_key=settings.classifier_api_key,
            api_base=settings.classifier_api_base,
            temperature=settings.classifier_temperature,
            max_tokens=settings.classifier_max_tokens,
            max_retries=settings.max_retries,
            retry_base_delay=settings.retry_base_delay,
        )
        self.summarizer_llm = LiteLLMClient(
            model=settings.summarizer_model,
            api_key=settings.summarizer_api_key,
            api_base=settings.summarizer_api_base,
            temperature=settings.summarizer_temperature,
            max_tokens=settings.summarizer_max_tokens,
            max_retries=settings.max_retries,
            retry_base_delay=settings.retry_base_delay,
        )
        self.lab_llm = LiteLLMClient(
            model=settings.lab_solver_model,
            api_key=settings.lab_solver_api_key,
            api_base=settings.lab_solver_api_base,
            temperature=settings.lab_solver_temperature,
            max_tokens=settings.lab_solver_max_tokens,
            max_retries=settings.max_retries,
            retry_base_delay=settings.retry_base_delay,
        )

        # Higher-level components
        self.classifier = AIClassifier(
            self.classifier_llm,
            slide_count=settings.classification_slide_count,
        )
        self.summarizer = LectureSummarizer(self.summarizer_llm)
        self.lab_solver = LabSolver(self.lab_llm)
        self.writer = MarkdownWriter(settings.output_dir)

        # Force reprocessing list
        self._force_files: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        progress_callback: Optional[ProgressCallback] = None,
        force_files: Optional[list[str]] = None,
    ) -> ProcessingReport:
        """
        Execute the full pipeline.

        Parameters
        ----------
        progress_callback : callable | None
            Optional ``(message: str, fraction: float) -> None`` for UI updates.
        force_files : list[str] | None
            Filenames (basenames) to force reprocess regardless of state.

        Returns
        -------
        ProcessingReport
        """
        started = time.monotonic()
        report = ProcessingReport()
        self._force_files = set(force_files or [])

        # 1. Scan
        self._report(progress_callback, "Scanning input directory …", 0.0)
        scanned = self.scanner.scan()
        report.total_scanned = len(scanned)

        if not scanned:
            logger.info("No supported files found in input directory.")
            self._report(progress_callback, "Done – no files to process.", 1.0)
            report.elapsed_seconds = time.monotonic() - started
            return report

        # 2. Load state & diff
        self._report(progress_callback, "Loading state & detecting changes …", 0.05)
        state = self.state_manager.load_state()
        new_or_changed = self.state_manager.find_new_or_changed(scanned, state)

        # Apply force reprocessing
        if self._force_files:
            for fp in scanned:
                if fp.name in self._force_files and fp not in new_or_changed:
                    new_or_changed.append(fp)
                    logger.info(f"Force reprocessing: {fp.name}")

        report.new_or_changed = len(new_or_changed)

        if not new_or_changed:
            logger.info("All files are up-to-date. Nothing to process.")
            self._report(progress_callback, "Done – everything is up-to-date.", 1.0)
            report.elapsed_seconds = time.monotonic() - started
            return report

        # 3. Process each file
        total = len(new_or_changed)
        for idx, filepath in enumerate(new_or_changed):
            fraction = 0.1 + 0.85 * (idx / total)
            self._report(
                progress_callback,
                f"Processing ({idx + 1}/{total}): {filepath.name}",
                fraction,
            )

            result = self._process_single_file(filepath)
            report.details.append(result)

            if result.status == "processed":
                report.processed += 1
            elif result.status == "error":
                report.errors += 1
            else:
                report.skipped += 1

            # Update state record for this file
            state[filepath.name] = self.state_manager.build_file_record(
                filepath,
                status=result.status,
                output_path=result.output_path or None,
                error_message=result.error or None,
            )
            # Inject classification data if available
            if result.course:
                # We don't persist the full classification here since we'd need
                # to store it after the classify step. Instead the build_file_record
                # captures the status and output path.
                pass

        # 4. Persist state
        self._report(progress_callback, "Saving state …", 0.96)
        self.state_manager.save_state(state)

        report.elapsed_seconds = time.monotonic() - started
        self._report(
            progress_callback,
            f"Done – {report.processed} processed, {report.errors} errors, "
            f"{report.skipped} skipped in {report.elapsed_seconds:.1f}s.",
            1.0,
        )

        return report

    def dry_run(self) -> ProcessingReport:
        """
        Scan and classify only – no LLM summarization and no file writing.

        Useful for previewing what would be processed before spending API tokens.
        """
        report = ProcessingReport()
        scanned = self.scanner.scan()
        report.total_scanned = len(scanned)

        if not scanned:
            return report

        state = self.state_manager.load_state()
        new_or_changed = self.state_manager.find_new_or_changed(scanned, state)
        report.new_or_changed = len(new_or_changed)

        for filepath in new_or_changed:
            try:
                classification = self.classifier.classify(filepath)
                report.details.append(ProcessedFile(
                    filename=filepath.name,
                    status="processed",
                    course=classification.course_name,
                    week=classification.week_number,
                    topic=classification.topic,
                ))
            except Exception as exc:
                report.details.append(ProcessedFile(
                    filename=filepath.name,
                    status="error",
                    error=str(exc),
                ))

        return report

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _process_single_file(self, filepath: Path) -> ProcessedFile:
        """
        Process one file through the full pipeline.

        All exceptions are caught per-file so one failure does not abort the batch.
        """
        filename = filepath.name
        result = ProcessedFile(filename=filename, status="pending")

        try:
            # a. Classify
            logger.info(f"[{filename}] Classifying …")
            classification = self.classifier.classify(filepath)
            result.course = classification.course_name
            result.week = classification.week_number
            result.topic = classification.topic

            # b. Create output directory
            output_dir = self.writer.ensure_output_dir(classification)
            result.output_path = self.writer.get_relative_output_path(output_dir)

            # c. Parse full text
            logger.info(f"[{filename}] Extracting full text …")
            parser = get_parser(filepath)
            full_text = parser.extract_text(filepath)

            if not full_text.strip():
                logger.warning(f"[{filename}] No text extracted – writing placeholder.")
                self._write_placeholder(output_dir, filename, classification)
                result.status = "processed"
                return result

            # d. Summarize
            logger.info(f"[{filename}] Summarizing …")
            summary = self.summarizer.summarize(full_text, classification)
            self.writer.write_summary(output_dir, classification, summary, filename)

            # e. Lab solving (if applicable)
            if classification.has_lab:
                logger.info(f"[{filename}] Solving lab …")
                lab_solution = self.lab_solver.solve(full_text, classification)
                self.writer.write_lab_solution(output_dir, classification, lab_solution, filename)

            result.status = "processed"
            logger.info(f"[{filename}] ✓ Done → {result.output_path}")

        except (PPTXParserError, PDFParserError) as exc:
            logger.error(f"[{filename}] Parse error: {exc}")
            result.status = "error"
            result.error = f"Parse error: {exc}"
        except LiteLLMError as exc:
            logger.error(f"[{filename}] LLM error: {exc}")
            result.status = "error"
            result.error = f"LLM API error: {exc}"
        except OSError as exc:
            logger.error(f"[{filename}] File system error: {exc}")
            result.status = "error"
            result.error = f"File system error: {exc}"
        except Exception as exc:
            logger.exception(f"[{filename}] Unexpected error: {type(exc).__name__}: {exc}")
            result.status = "error"
            result.error = f"{type(exc).__name__}: {exc}"

        return result

    def _write_placeholder(
        self, output_dir: Path, filename: str, classification: ClassificationResult
    ) -> None:
        """Write a placeholder note when no text could be extracted."""
        content = (
            f"# {classification.course_name} Week {classification.week_number}: {classification.topic}\n\n"
            f"> ⚠ Placeholder – no text could be extracted from `{filename}`.\n\n"
            f"This file may be image-heavy or use an unsupported format. "
            f"Try converting it to a text-based format or use a Vision LLM for processing.\n"
        )
        filepath = output_dir / "summary.md"
        self.writer._atomic_write(filepath, content)

    @staticmethod
    def _report(
        callback: Optional[ProgressCallback], message: str, fraction: float
    ) -> None:
        """Invoke the progress callback if provided."""
        if callback:
            try:
                callback(message, fraction)
            except Exception:
                pass  # Never let a UI callback break the pipeline
