#!/usr/bin/env python3
"""
Review Agent – CLI Entry Point
===============================
AI-powered lecture note generator that transforms PPT/PDF files
into structured Markdown review notes.

Usage::

    python main.py                          # Process all new/changed files
    python main.py --dry-run                # Preview classifications only
    python main.py --force file1.pptx       # Force reprocess specific files
    python main.py --input ./my_ppts        # Custom input directory
    python main.py --preset budget          # Use budget model preset
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path so `src` is importable
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config.settings import Settings, MODEL_PRESETS
from src.pipeline import Pipeline, ProcessingReport


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with a simple console format."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)-7s] %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )


def print_report(report: ProcessingReport) -> None:
    """Pretty-print a processing report to the console."""
    print()
    print("=" * 60)
    print("  REVIEW AGENT – Processing Report")
    print("=" * 60)
    print(f"  Files scanned      : {report.total_scanned}")
    print(f"  New or changed     : {report.new_or_changed}")
    print(f"  Processed (ok)     : {report.processed}")
    print(f"  Errors             : {report.errors}")
    print(f"  Skipped            : {report.skipped}")
    print(f"  Elapsed            : {report.elapsed_seconds:.1f}s")
    print("-" * 60)

    if report.details:
        for detail in report.details:
            icon = "[OK]" if detail.status == "processed" else "[ERR]"
            print(f"  {icon} {detail.filename:40s} -> {detail.output_path or detail.error}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review Agent – AI-powered lecture note generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                           Process all new/changed files
  python main.py --dry-run                 Preview what would be processed
  python main.py --force lecture1.pptx     Force reprocess a specific file
  python main.py --preset budget           Use budget-friendly models
  python main.py --input ./my_ppts --output ./my_notes
        """,
    )
    parser.add_argument(
        "--input", type=Path, default=None,
        help="Override input directory (default: 01_Input_PPTs)",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Override output directory (default: 02_Output_Notes)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scan and classify only – do NOT generate any notes (saves API tokens)",
    )
    parser.add_argument(
        "--force", type=str, nargs="*", default=None,
        help="Force reprocess specific files (by filename), even if unchanged",
    )
    parser.add_argument(
        "--preset", type=str, choices=list(MODEL_PRESETS.keys()),
        help="Use a predefined model preset: " + ", ".join(MODEL_PRESETS.keys()),
    )
    parser.add_argument(
        "--log-level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    parser.add_argument(
        "--pdf", action="store_true",
        help="Convert generated Markdown notes to PDF (requires playwright + chromium)",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)
    logger = logging.getLogger("main")

    # ---- Build settings ----
    overrides: dict = {}
    if args.input:
        overrides["input_dir"] = str(args.input)
    if args.output:
        overrides["output_dir"] = str(args.output)

    # If a preset is selected, set it in the environment so Settings picks it up
    if args.preset:
        import os
        os.environ["PRESET"] = args.preset
        logger.info(f"Using model preset: {args.preset}")

    try:
        settings = Settings.from_env(overrides)
    except ValueError as exc:
        print(f"❌ Configuration error: {exc}", file=sys.stderr)
        print("\nMake sure you have a .env file with at least an API_KEY set.", file=sys.stderr)
        print("Copy .env.example to .env and fill in your API key(s).", file=sys.stderr)
        sys.exit(1)

    logger.info(f"Input directory : {settings.input_dir}")
    logger.info(f"Output directory: {settings.output_dir}")
    logger.info(f"State file      : {settings.state_file}")
    logger.info(f"Classifier      : {settings.classifier_model}")
    logger.info(f"Summarizer      : {settings.summarizer_model}")
    logger.info(f"Lab Solver      : {settings.lab_solver_model}")

    # ---- Run ----
    pipeline = Pipeline(settings)

    if args.dry_run:
        logger.info("Dry-run mode – classifying only, no content generation.")
        report = pipeline.dry_run()
        print_report(report)
        return

    # Progress callback for CLI
    def cli_progress(message: str, fraction: float) -> None:
        pct = int(fraction * 100)
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        print(f"\r  [{bar}] {pct:3d}%  {message}", end="", flush=True)

    try:
        report = pipeline.run(
            progress_callback=cli_progress,
            force_files=args.force,
        )
        print()  # newline after progress bar
        print_report(report)

        # Optional: convert Markdown → PDF
        if args.pdf:
            logger.info("--pdf flag set, converting Markdown to PDF …")
            try:
                from convert_md_to_pdf import convert_all
                convert_all(settings.output_dir)
            except ImportError as exc:
                logger.error(
                    f"PDF conversion requires additional dependencies: {exc}\n"
                    "Install with: pip install playwright && python -m playwright install chromium"
                )
            except Exception as exc:
                logger.error(f"PDF conversion failed: {exc}")
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        logger.exception(f"Fatal error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
