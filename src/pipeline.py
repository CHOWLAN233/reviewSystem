"""
Core pipeline orchestrator.

Wires together scanning, state management, parsing, classification,
summarization, lab solving, and markdown writing into a single
end-to-end workflow.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from .generator.review_cleaner import ReviewCleaner, ReviewResult

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

        # Secondary review cleaner
        review_llm = LiteLLMClient(
            model=settings.classifier_model,  # Use cheaper model for review
            api_key=settings.classifier_api_key,
            api_base=settings.classifier_api_base,
            temperature=0.1,
            max_tokens=min(settings.classifier_max_tokens, 2048),
            max_retries=settings.max_retries,
            retry_base_delay=settings.retry_base_delay,
        )
        self.review_cleaner = ReviewCleaner(
            llm_client=review_llm,
            review_mode=settings.review_mode,
        )

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

        # 3. Process files in parallel
        total = len(new_or_changed)
        completed_count = 0
        completed_lock = threading.Lock()

        # Determine concurrency: env var or default to 4 workers
        max_workers = int(os.environ.get("MAX_WORKERS", "4"))

        # Build a list of (filepath, subfolder_hint) tuples
        tasks: list[tuple[Path, str | None]] = []
        for filepath in new_or_changed:
            try:
                subfolder = filepath.relative_to(self.settings.input_dir).parent
                subfolder_hint = str(subfolder) if str(subfolder) != "." else None
            except ValueError:
                subfolder_hint = None
            tasks.append((filepath, subfolder_hint))

        logger.info(f"Processing {total} file(s) with {max_workers} parallel workers …")

        # Submit all tasks to the thread pool
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {
                executor.submit(self._process_single_file, fp, hint): (fp, hint)
                for fp, hint in tasks
            }

            for future in as_completed(future_to_file):
                filepath, _hint = future_to_file[future]
                try:
                    result = future.result()
                except Exception as exc:
                    # This should not happen — _process_single_file catches all
                    logger.error(f"Unexpected thread error for {filepath.name}: {exc}")
                    result = ProcessedFile(
                        filename=filepath.name,
                        status="error",
                        error=f"Thread error: {exc}",
                    )

                report.details.append(result)

                if result.status == "processed":
                    report.processed += 1
                elif result.status == "error":
                    report.errors += 1
                else:
                    report.skipped += 1

                # Update state record for this file (dict assignment is atomic in CPython)
                state[filepath.name] = self.state_manager.build_file_record(
                    filepath,
                    status=result.status,
                    output_path=result.output_path or None,
                    error_message=result.error or None,
                )

                # Thread-safe progress update
                with completed_lock:
                    completed_count += 1
                    fraction = 0.1 + 0.85 * (completed_count / total)
                    self._report(
                        progress_callback,
                        f"Processing ({completed_count}/{total}): {result.filename} [{result.status}]",
                        fraction,
                    )

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
                # Compute subfolder hint for classification context
                try:
                    subfolder = filepath.relative_to(self.settings.input_dir).parent
                    subfolder_hint = str(subfolder) if str(subfolder) != "." else None
                except ValueError:
                    subfolder_hint = None
                classification = self.classifier.classify(filepath, subfolder_hint=subfolder_hint)
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

    def _process_single_file(self, filepath: Path, subfolder_hint: str | None = None) -> ProcessedFile:
        """
        Process one file through the full pipeline.

        All exceptions are caught per-file so one failure does not abort the batch.
        """
        filename = filepath.name
        result = ProcessedFile(filename=filename, status="pending")

        try:
            # a. Classify
            logger.info(f"[{filename}] Classifying …")
            classification = self.classifier.classify(filepath, subfolder_hint=subfolder_hint)
            result.course = classification.course_name
            result.week = classification.week_number
            result.topic = classification.topic

            # b. Create output directory (pass filename for week=0 fallback naming)
            output_dir = self.writer.ensure_output_dir(classification, source_filename=filename)
            result.output_path = self.writer.get_relative_output_path(output_dir)

            # c. Parse full text
            logger.info(f"[{filename}] Extracting full text …")
            parser = get_parser(filepath)
            full_text = parser.extract_text(filepath)

            if not full_text.strip():
                logger.warning(f"[{filename}] No text extracted – writing placeholder.")
                self._write_placeholder(output_dir, filename, classification)
                self._copy_source_file(filepath, output_dir)
                result.status = "processed"
                return result

            # d. Summarize
            logger.info(f"[{filename}] Summarizing …")
            summary = self.summarizer.summarize(full_text, classification)

            # e. Secondary review: clean artifacts from the generated Markdown
            logger.info(f"[{filename}] Reviewing (mode: {self.review_cleaner.review_mode}) …")
            review_result = self._review_summary(summary, filename)
            if review_result.changes_made > 0:
                logger.info(
                    f"[{filename}] Review: {review_result.changes_made} issue(s) fixed"
                )

            self.writer.write_summary(output_dir, classification, summary, filename)

            # f. Lab solving (if applicable)
            if classification.has_lab:
                logger.info(f"[{filename}] Solving lab …")
                lab_solution = self.lab_solver.solve(full_text, classification)
                self.writer.write_lab_solution(output_dir, classification, lab_solution, filename)

            # g. Copy original file into output folder for reference
            self._copy_source_file(filepath, output_dir)

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
            f"> Warning: Placeholder -- no text could be extracted from `{filename}`.\n\n"
            f"This file may be image-heavy or use an unsupported format. "
            f"Try converting it to a text-based format or use a Vision LLM for processing.\n"
        )
        md_dir = self.writer.get_md_dir(classification)
        week_name = self.writer.get_week_folder_name(classification, filename)
        filepath = md_dir / f"{week_name}_summary.md"
        self.writer._atomic_write(filepath, content)

    def _review_summary(self, summary, filename: str) -> ReviewResult:
        """
        Run the secondary review on the generated summary content.

        Reviews both the detailed notes and the outline/takeaways sections
        for code artifacts, garbled text, and formatting issues.
        """
        # Concatenate all summary sections for review
        parts = [summary.detailed_notes, summary.outline, summary.takeaways]
        combined = "\n\n".join(p for p in parts if p and p.strip())

        if not combined.strip():
            return ReviewResult(cleaned_content="")

        result = self.review_cleaner.review(combined)

        # Apply cleaned content back to the summary sections
        if result.changes_made > 0:
            # The review cleaner returns the full cleaned text.
            # We apply it primarily to detailed_notes (the largest section)
            # while keeping other sections intact unless they had issues.
            cleaned = result.cleaned_content
            if cleaned and len(cleaned) > 100:
                # Replace detailed_notes with the cleaned version
                # (the cleaner preserves all sections, so we replace the
                #  largest part which is detailed_notes)
                summary.detailed_notes = cleaned
                summary.raw_content = cleaned

        return result

    @staticmethod
    def _copy_source_file(source_path: Path, output_dir: Path) -> None:
        """
        Copy the original PPT/PDF file into the output directory for reference.

        Skips if the file already exists in the output (same size).
        """
        import shutil

        dest = output_dir / source_path.name
        if dest.exists() and dest.stat().st_size == source_path.stat().st_size:
            logger.debug(f"Source file already in output: {dest.name}")
            return

        try:
            shutil.copy2(source_path, dest)
            logger.info(f"Copied source file: {source_path.name} → {output_dir}")
        except OSError as exc:
            logger.warning(f"Could not copy source file {source_path.name}: {exc}")

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
