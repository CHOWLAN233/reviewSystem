#!/usr/bin/env python3
"""
Review Agent -- CLI Entry Point
================================
AI-powered lecture note generator that transforms PPT/PDF files
into structured Markdown review notes and PDF exports.

Usage:
    python main.py          # Interactive menu mode
    python main.py --help   # Show legacy CLI flags (batch mode)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import textwrap
from datetime import datetime
from pathlib import Path

# Ensure the project root is on sys.path so `src` is importable
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config.settings import Settings, MODEL_PRESETS
from src.pipeline import Pipeline, ProcessingReport
from src.scanner.file_scanner import FileScanner
from src.scanner.state_manager import StateManager

logger = logging.getLogger("main")


# ======================================================================
# Utilities
# ======================================================================

def clear_screen() -> None:
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with a simple console format."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)-7s] %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )


def press_enter() -> None:
    """Prompt the user to press Enter to continue."""
    input("\nPress Enter to return to the main menu...")


def print_header(title: str) -> None:
    """Print a styled section header."""
    width = 60
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def print_bar(message: str) -> None:
    """Print a separator with a label."""
    print(f"\n--- {message} ---")


def open_folder(path: Path) -> None:
    """Open a folder in the OS file explorer."""
    try:
        if os.name == "nt":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", str(path)], check=False)
        else:
            import subprocess
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception as e:
        print(f"  [WARN] Could not open folder: {e}")


# ======================================================================
# Interactive Menu Handlers
# ======================================================================

def menu_upload(settings: Settings) -> None:
    """
    Option 1: Upload and process files.

    Prompts the user to place PPT/PDF files in the input directory,
    then scans, detects new/changed files, and processes them with
    a real-time progress bar.
    """
    clear_screen()
    print_header("Upload & Process Files")

    input_dir = settings.input_dir
    input_dir.mkdir(parents=True, exist_ok=True)

    # Open the input folder for the user
    open_folder(input_dir.resolve())

    print(f"\n  Input directory: {input_dir}")
    print(f"  Supported formats: .pptx, .ppt, .pdf")
    print()
    print("  Place your PPT or PDF files into the input folder,")
    print("  then return here and press Enter to continue.")
    print(f"  You can organize files in sub-folders (e.g. by course name).")
    print()
    print(f"  Input folder:")
    print(f"    {input_dir.resolve()}")
    print()

    input("  Press Enter after you have added your files...")
    scanner = FileScanner(input_dir, settings.supported_extensions)
    files = scanner.scan()

    if not files:
        print("  [INFO] No supported files found in the input directory.")
        print("  Please add .pptx, .ppt, or .pdf files and try again.")
        press_enter()
        return

    print(f"  [INFO] Found {len(files)} supported file(s):")
    for fp in files:
        try:
            rel = fp.relative_to(input_dir)
        except ValueError:
            rel = fp
        print(f"    - {rel}")
    print()

    # Check against state to find new/changed
    state_mgr = StateManager(settings.state_file)
    state = state_mgr.load_state()
    new_or_changed = state_mgr.find_new_or_changed(files, state)

    if not new_or_changed:
        print("  [INFO] All files are already up-to-date. Nothing to process.")
        press_enter()
        return

    print(f"  [INFO] {len(new_or_changed)} file(s) need processing:")
    for fp in new_or_changed:
        try:
            rel = fp.relative_to(input_dir)
        except ValueError:
            rel = fp
        print(f"    - {rel}")
    print()

    # Confirm
    choice = input("  Start processing? (y/n): ").strip().lower()
    if choice not in ("y", "yes"):
        print("  Cancelled.")
        press_enter()
        return

    # Build pipeline and run
    pipeline = Pipeline(settings)

    def cli_progress(message: str, fraction: float) -> None:
        pct = int(fraction * 100)
        bar_len = 30
        filled = int(bar_len * fraction)
        bar = "#" * filled + "-" * (bar_len - filled)
        print(f"\r  [{bar}] {pct:3d}%  {message}", end="", flush=True)

    print()
    try:
        report = pipeline.run(progress_callback=cli_progress)
        print()  # newline after progress bar
        print_report(report)

        # Offer PDF conversion
        print()
        pdf_choice = input("  Convert generated notes to PDF? (y/n): ").strip().lower()
        if pdf_choice in ("y", "yes"):
            print_bar("PDF Conversion")
            try:
                from convert_md_to_pdf import convert_all
                convert_all(settings.output_dir)
            except ImportError as exc:
                print(f"  [ERROR] PDF conversion requires additional dependencies: {exc}")
                print("  Install with: pip install playwright && python -m playwright install chromium")
            except Exception as exc:
                print(f"  [ERROR] PDF conversion failed: {exc}")

    except KeyboardInterrupt:
        print("\n\n  Interrupted by user.")
    except Exception as exc:
        logger.exception(f"Fatal error: {exc}")
        print(f"\n  [ERROR] Pipeline failed: {exc}")

    # Open output folder for the user
    output_dir = settings.output_dir
    if output_dir.exists():
        print()
        print(f"  Opening output folder: {output_dir.resolve()}")
        open_folder(output_dir.resolve())

    press_enter()


def menu_view_output(settings: Settings) -> None:
    """
    Option 2: View exported PDF files and output structure.

    Displays the output directory tree with PDF and MD files.
    """
    clear_screen()
    print_header("View Exported Files")

    output_dir = settings.output_dir

    if not output_dir.exists():
        print(f"\n  [INFO] Output directory does not exist yet.")
        print(f"  Expected location: {output_dir.resolve()}")
        print("  Run 'Upload & Process Files' first to generate notes.")
        press_enter()
        return

    # Find all PDF and MD files
    pdf_files = sorted(output_dir.rglob("*.pdf"))
    md_files = sorted(output_dir.rglob("*.md"))

    if not pdf_files and not md_files:
        print(f"\n  [INFO] No PDF or MD files found in output directory.")
        print(f"  Location: {output_dir.resolve()}")
        press_enter()
        return

    print(f"\n  Output directory: {output_dir.resolve()}")
    print(f"  PDF files found: {len(pdf_files)}")
    print(f"  MD files found:  {len(md_files)}")
    print()

    # Print directory tree
    print("  Directory structure:")
    print(f"  {output_dir.name}/")
    _print_tree(output_dir, prefix="    ", max_depth=3, current_depth=0)

    # List PDFs
    if pdf_files:
        print(f"\n  PDF files:")
        for f in pdf_files:
            try:
                rel = f.relative_to(output_dir)
            except ValueError:
                rel = f
            size_kb = f.stat().st_size / 1024
            print(f"    - {rel}  ({size_kb:.0f} KB)")

    # List MDs
    if md_files:
        print(f"\n  Markdown files:")
        for f in md_files:
            try:
                rel = f.relative_to(output_dir)
            except ValueError:
                rel = f
            print(f"    - {rel}")

    press_enter()


def _print_tree(directory: Path, prefix: str, max_depth: int, current_depth: int) -> None:
    """Recursively print a directory tree, skipping .gitkeep files."""
    if current_depth >= max_depth:
        return

    try:
        entries = sorted(directory.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    except PermissionError:
        return

    for i, entry in enumerate(entries):
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        is_last = i == len(entries) - 1
        connector = "`-- " if is_last else "|-- "
        print(f"{prefix}{connector}{entry.name}")

        if entry.is_dir():
            extension = "    " if is_last else "|   "
            _print_tree(entry, prefix + extension, max_depth, current_depth + 1)


def menu_history(settings: Settings) -> None:
    """
    Option 3: Upload / processing history.

    Displays the contents of .sync_state.json in a human-readable format.
    """
    clear_screen()
    print_header("Processing History")

    state_file = settings.state_file

    if not state_file.exists():
        print(f"\n  [INFO] No processing history found.")
        print(f"  State file does not exist: {state_file.resolve()}")
        print("  Run 'Upload & Process Files' first to create a history.")
        press_enter()
        return

    state_mgr = StateManager(state_file)
    state = state_mgr.load_state()

    if not state:
        print(f"\n  [INFO] Processing history is empty.")
        press_enter()
        return

    print(f"\n  State file: {state_file.resolve()}")
    print(f"  Tracked files: {len(state)}")
    print()

    # Summary stats
    processed = sum(1 for r in state.values() if r.status == "processed")
    errors = sum(1 for r in state.values() if r.status == "error")
    skipped = sum(1 for r in state.values() if r.status == "skipped")

    print(f"  Summary: {processed} processed | {errors} errors | {skipped} skipped")
    print()
    print(f"  {'Filename':<50} {'Status':<12} {'Last Processed':<20} {'Output':<30}")
    print(f"  {'-'*50} {'-'*12} {'-'*20} {'-'*30}")

    for fname, record in sorted(state.items()):
        status_display = {
            "processed": "OK",
            "error": "ERROR",
            "skipped": "SKIPPED",
        }.get(record.status, record.status)

        # Truncate timestamp for display
        ts = record.last_processed[:19] if record.last_processed else "N/A"

        output = record.output_path or record.error_message or "-"
        if len(output) > 28:
            output = output[:25] + "..."

        fname_disp = fname if len(fname) <= 48 else fname[:45] + "..."
        print(f"  {fname_disp:<50} {status_display:<12} {ts:<20} {output:<30}")

    # Option to view raw JSON
    print()
    choice = input("  View full raw JSON? (y/n): ").strip().lower()
    if choice in ("y", "yes"):
        with open(state_file, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        print()
        print(json.dumps(raw, indent=2, ensure_ascii=False))

    # Option to reset history
    print()
    choice = input("  Reset/clear processing history? (y/n): ").strip().lower()
    if choice in ("y", "yes"):
        confirm = input("  Are you sure? This cannot be undone. (yes/no): ").strip().lower()
        if confirm == "yes":
            state_file.unlink(missing_ok=True)
            backup = Path(str(state_file) + ".backup")
            backup.unlink(missing_ok=True)
            print("  [INFO] Processing history cleared.")

    press_enter()


def menu_settings(current_settings: Settings | None) -> Settings | None:
    """
    Option 4: Configure settings.

    Allows users to view and modify:
    - API key
    - Model preset
    - Input / Output directories
    - Individual model overrides
    """
    clear_screen()
    print_header("Settings")

    # Load current values from environment
    if current_settings is None:
        try:
            current_settings = Settings.from_env()
        except ValueError:
            # No API key set yet -- create a minimal placeholder
            pass

    while True:
        clear_screen()
        print_header("Settings")

        # Display current configuration
        if current_settings:
            print(f"\n  [1] API Key:          {'***' + current_settings.classifier_api_key[-4:] if current_settings.classifier_api_key else '(not set)'}")
            print(f"  [2] Model Preset:      {current_settings.preset or 'custom'}")
            print(f"  [3] Classifier Model:  {current_settings.classifier_model}")
            print(f"  [4] Summarizer Model:  {current_settings.summarizer_model}")
            print(f"  [5] Lab Solver Model:  {current_settings.lab_solver_model}")
            print(f"  [6] Input Directory:   {current_settings.input_dir}")
            print(f"  [7] Output Directory:  {current_settings.output_dir}")
            print(f"  [8] Log Level:         {current_settings.log_level}")
        else:
            print(f"\n  [1] API Key:          (not set)")
            print(f"  [2] Model Preset:      balanced")
            print(f"  [3-5] Models:          (using preset defaults)")
            print(f"  [6] Input Directory:   01_Input_PPTs")
            print(f"  [7] Output Directory:  02_Output_Notes")
            print(f"  [8] Log Level:         INFO")

        print(f"\n  [9] View/edit .env file directly")
        print(f"  [0] Return to main menu")

        print()
        choice = input("  Select a setting to modify (0-9): ").strip()

        if choice == "0":
            break
        elif choice == "1":
            print()
            new_key = input("  Enter new API key (or press Enter to keep current): ").strip()
            if new_key:
                os.environ["API_KEY"] = new_key
                _update_env_file("API_KEY", new_key)
                print("  [OK] API key updated.")
                press_enter()
        elif choice == "2":
            print()
            print("  Available presets:")
            for name, models in MODEL_PRESETS.items():
                print(f"    {name:<12} classifier={models['classifier']}, summarizer={models['summarizer']}, lab={models['lab_solver']}")
            print()
            new_preset = input("  Enter preset name (budget/balanced/maximum): ").strip().lower()
            if new_preset in MODEL_PRESETS:
                os.environ["PRESET"] = new_preset
                _update_env_file("PRESET", new_preset)
                print(f"  [OK] Preset set to '{new_preset}'.")
            else:
                print(f"  [ERROR] Unknown preset: {new_preset}")
            press_enter()
        elif choice == "3":
            print()
            new_model = input("  Enter classifier model (e.g. gemini/gemini-2.0-flash): ").strip()
            if new_model:
                os.environ["CLASSIFIER_MODEL"] = new_model
                _update_env_file("CLASSIFIER_MODEL", new_model)
                print("  [OK] Classifier model updated.")
            press_enter()
        elif choice == "4":
            print()
            new_model = input("  Enter summarizer model (e.g. claude-sonnet-4-20250514): ").strip()
            if new_model:
                os.environ["SUMMARIZER_MODEL"] = new_model
                _update_env_file("SUMMARIZER_MODEL", new_model)
                print("  [OK] Summarizer model updated.")
            press_enter()
        elif choice == "5":
            print()
            new_model = input("  Enter lab solver model (e.g. deepseek/deepseek-chat): ").strip()
            if new_model:
                os.environ["LAB_SOLVER_MODEL"] = new_model
                _update_env_file("LAB_SOLVER_MODEL", new_model)
                print("  [OK] Lab solver model updated.")
            press_enter()
        elif choice == "6":
            print()
            new_dir = input("  Enter new input directory path: ").strip()
            if new_dir:
                os.environ["INPUT_DIR"] = new_dir
                _update_env_file("INPUT_DIR", new_dir)
                print(f"  [OK] Input directory set to: {new_dir}")
            press_enter()
        elif choice == "7":
            print()
            new_dir = input("  Enter new output directory path: ").strip()
            if new_dir:
                os.environ["OUTPUT_DIR"] = new_dir
                _update_env_file("OUTPUT_DIR", new_dir)
                print(f"  [OK] Output directory set to: {new_dir}")
            press_enter()
        elif choice == "8":
            print()
            print("  Available levels: DEBUG, INFO, WARNING, ERROR")
            new_level = input("  Enter log level: ").strip().upper()
            if new_level in ("DEBUG", "INFO", "WARNING", "ERROR"):
                os.environ["LOG_LEVEL"] = new_level
                _update_env_file("LOG_LEVEL", new_level)
                setup_logging(new_level)
                print(f"  [OK] Log level set to: {new_level}")
            else:
                print(f"  [ERROR] Invalid log level.")
            press_enter()
        elif choice == "9":
            _edit_env_file()
            press_enter()
        else:
            print("  Invalid choice.")
            press_enter()

        # Reload settings after any change
        try:
            current_settings = Settings.from_env()
        except ValueError:
            current_settings = None

    return current_settings


def _update_env_file(key: str, value: str) -> None:
    """Update or add a key-value pair in the .env file."""
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        # Copy from .env.example if .env doesn't exist
        example_path = _PROJECT_ROOT / ".env.example"
        if example_path.exists():
            import shutil
            shutil.copy(example_path, env_path)

    if not env_path.exists():
        # Create fresh
        env_path.write_text(f"{key}={value}\n", encoding="utf-8")
        return

    lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}=") or line.startswith(f"# {key}="):
            lines[i] = f"{key}={value}"
            found = True
            break

    if not found:
        lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _edit_env_file() -> None:
    """Open the .env file for manual editing."""
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        example_path = _PROJECT_ROOT / ".env.example"
        if example_path.exists():
            import shutil
            shutil.copy(example_path, env_path)

    if not env_path.exists():
        print("  [ERROR] No .env or .env.example file found.")
        return

    print(f"\n  .env file location: {env_path.resolve()}")
    print()
    print("  Current .env contents:")
    print("  " + "-" * 55)
    content = env_path.read_text(encoding="utf-8")
    for line in content.splitlines():
        # Mask API keys in display
        if line.startswith("API_KEY=") or line.startswith("CLASSIFIER_API_KEY=") or \
           line.startswith("SUMMARIZER_API_KEY=") or line.startswith("LAB_SOLVER_API_KEY="):
            parts = line.split("=", 1)
            if len(parts) == 2 and len(parts[1]) > 4:
                print(f"  {parts[0]}={'*' * (len(parts[1]) - 4)}{parts[1][-4:]}")
            else:
                print(f"  {line}")
        else:
            print(f"  {line}")
    print("  " + "-" * 55)
    print()
    print("  To edit: open this file in any text editor.")
    print(f"    {env_path.resolve()}")


# ======================================================================
# Legacy CLI (batch mode)
# ======================================================================

def print_report(report: ProcessingReport) -> None:
    """Pretty-print a processing report to the console."""
    print()
    print("=" * 60)
    print("  REVIEW AGENT -- Processing Report")
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


def legacy_main() -> None:
    """Legacy batch-mode CLI entry point (when --flags are used)."""
    parser = argparse.ArgumentParser(
        description="Review Agent -- AI-powered lecture note generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python main.py                           Process all new/changed files
              python main.py --dry-run                 Preview what would be processed
              python main.py --force lecture1.pptx     Force reprocess a specific file
              python main.py --preset budget           Use budget-friendly models
              python main.py --input ./my_ppts --output ./my_notes
        """),
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
        help="Scan and classify only -- do NOT generate any notes (saves API tokens)",
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

    if args.preset:
        os.environ["PRESET"] = args.preset
        logger.info(f"Using model preset: {args.preset}")

    try:
        settings = Settings.from_env(overrides)
    except ValueError as exc:
        print(f"[ERROR] Configuration error: {exc}", file=sys.stderr)
        print("\nMake sure you have a .env file with at least an API_KEY set.", file=sys.stderr)
        print("Copy .env.example to .env and fill in your API key(s).", file=sys.stderr)
        sys.exit(1)

    logger.info(f"Input directory : {settings.input_dir}")
    logger.info(f"Output directory: {settings.output_dir}")
    logger.info(f"Classifier      : {settings.classifier_model}")
    logger.info(f"Summarizer      : {settings.summarizer_model}")
    logger.info(f"Lab Solver      : {settings.lab_solver_model}")

    # ---- Run ----
    pipeline = Pipeline(settings)

    if args.dry_run:
        logger.info("Dry-run mode -- classifying only, no content generation.")
        report = pipeline.dry_run()
        print_report(report)
        return

    def cli_progress(message: str, fraction: float) -> None:
        pct = int(fraction * 100)
        bar_len = 30
        filled = int(bar_len * fraction)
        bar = "#" * filled + "-" * (bar_len - filled)
        print(f"\r  [{bar}] {pct:3d}%  {message}", end="", flush=True)

    try:
        report = pipeline.run(
            progress_callback=cli_progress,
            force_files=args.force,
        )
        print()
        print_report(report)

        if args.pdf:
            logger.info("--pdf flag set, converting Markdown to PDF ...")
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
        print("\n\nInterrupted by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        logger.exception(f"Fatal error: {exc}")
        sys.exit(1)


# ======================================================================
# Interactive Menu (main mode)
# ======================================================================

def interactive_main() -> None:
    """Run the Review Agent in interactive CLI menu mode."""
    setup_logging("INFO")

    # Load settings
    settings = None
    try:
        settings = Settings.from_env()
    except ValueError:
        pass  # Will prompt user to configure

    while True:
        clear_screen()
        print()
        print("=" * 60)
        print("         Review Agent v1.0")
        print("    AI-Powered Lecture Note Generator")
        print("=" * 60)
        print()
        print("  [1] Upload & Process Files")
        print("  [2] View Exported PDFs / Output")
        print("  [3] Processing History")
        print("  [4] Settings")
        print("  [5] Exit")
        print()

        # Quick status line
        if settings:
            input_count = FileScanner(settings.input_dir, settings.supported_extensions).get_file_count()
            print(f"  Status: {input_count} file(s) in input | "
                  f"API key: {'configured' if settings.classifier_api_key else 'MISSING'}"
                  f" | Preset: {settings.preset or 'custom'}")
        else:
            print(f"  Status: API key NOT configured. Go to [4] Settings to set up.")

        print()
        choice = input("  Select an option [1-5]: ").strip()

        if choice == "1":
            # Reload settings (may have been changed in menu 4)
            if settings is None:
                try:
                    settings = Settings.from_env()
                except ValueError as exc:
                    print(f"\n  [ERROR] Configuration required: {exc}")
                    print("  Go to [4] Settings to configure your API key first.")
                    press_enter()
                    continue
            menu_upload(settings)
        elif choice == "2":
            if settings is None:
                try:
                    settings = Settings.from_env()
                except ValueError:
                    settings = Settings(
                        input_dir=_PROJECT_ROOT / "01_Input_PPTs",
                        output_dir=_PROJECT_ROOT / "02_Output_Notes",
                        state_file=_PROJECT_ROOT / ".sync_state.json",
                        classifier_model="", classifier_api_key="",
                        classifier_api_base=None, classifier_temperature=0.1,
                        classifier_max_tokens=512, summarizer_model="",
                        summarizer_api_key="", summarizer_api_base=None,
                        summarizer_temperature=0.3, summarizer_max_tokens=4096,
                        lab_solver_model="", lab_solver_api_key="",
                        lab_solver_api_base=None, lab_solver_temperature=0.2,
                        lab_solver_max_tokens=4096, classification_slide_count=3,
                        max_retries=3, retry_base_delay=2.0,
                    )
            menu_view_output(settings)
        elif choice == "3":
            if settings is None:
                try:
                    settings = Settings.from_env()
                except ValueError:
                    settings = Settings(
                        input_dir=_PROJECT_ROOT / "01_Input_PPTs",
                        output_dir=_PROJECT_ROOT / "02_Output_Notes",
                        state_file=_PROJECT_ROOT / ".sync_state.json",
                        classifier_model="", classifier_api_key="",
                        classifier_api_base=None, classifier_temperature=0.1,
                        classifier_max_tokens=512, summarizer_model="",
                        summarizer_api_key="", summarizer_api_base=None,
                        summarizer_temperature=0.3, summarizer_max_tokens=4096,
                        lab_solver_model="", lab_solver_api_key="",
                        lab_solver_api_base=None, lab_solver_temperature=0.2,
                        lab_solver_max_tokens=4096, classification_slide_count=3,
                        max_retries=3, retry_base_delay=2.0,
                    )
            menu_history(settings)
        elif choice == "4":
            settings = menu_settings(settings)
            # Reload after settings changes
            if settings is None:
                try:
                    settings = Settings.from_env()
                except ValueError:
                    settings = None
        elif choice == "5":
            print("\n  Goodbye!")
            sys.exit(0)
        else:
            print("\n  Invalid choice. Please enter a number from 1 to 5.")
            press_enter()


# ======================================================================
# Entry Point
# ======================================================================

if __name__ == "__main__":
    # If any CLI flags are passed, use legacy batch mode
    if len(sys.argv) > 1:
        legacy_main()
    else:
        interactive_main()
