#!/usr/bin/env python3
"""
Review Agent -- CLI Entry Point
================================
AI-powered lecture note generator that transforms PPT/PDF files
into structured Markdown review notes and PDF exports.

Usage:
    python main.py          # Interactive menu mode
    python main.py --help   # Show legacy CLI flags (batch mode)
    python main.py --version  # Show version
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
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

VERSION = "2.0.0"

logger = logging.getLogger("main")


# ======================================================================
# Utilities
# ======================================================================

def clear_screen() -> None:
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """Configure root logger with console and optional file output."""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)-7s] %(name)s - %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
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
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception as e:
        print(f"  [WARN] Could not open folder: {e}")


def close_folder(path: Path) -> None:
    """
    Close any Explorer/Finder windows showing *path*.

    On Windows, uses COM to enumerate and close matching Explorer windows.
    On other platforms this is a no-op (Finder windows are not closable via CLI).
    """
    if os.name != "nt":
        return
    try:
        target = str(path.resolve()).replace("\\", "/").lower()
        import pythoncom
        pythoncom.CoInitialize()
        from win32com.client import Dispatch
        shell = Dispatch("Shell.Application")
        for window in shell.Windows():
            try:
                location = str(window.LocationURL).lower()
                # LocationURL looks like: file:///C:/path/to/folder
                if target in location or location.endswith(target):
                    window.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()
    except ImportError:
        # Fallback: try PowerShell (no extra deps needed)
        try:
            folder_name = path.name.lower()
            ps_cmd = (
                f'$shell = New-Object -ComObject Shell.Application; '
                f'$shell.Windows() | Where-Object {{ '
                f'$_.LocationURL -like "*{folder_name}*" '
                f'}} | ForEach-Object {{ $_.Quit() }}'
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass  # Best effort only
    except Exception:
        pass  # Best effort only


# Track opened folders so we can close them later
_opened_folder: Path | None = None


def open_and_track(path: Path) -> None:
    """Open a folder and remember it for later closing."""
    global _opened_folder
    # Close previously opened folder first
    if _opened_folder is not None:
        close_folder(_opened_folder)
    open_folder(path)
    _opened_folder = path


def close_tracked_folder() -> None:
    """Close the last tracked folder, if any."""
    global _opened_folder
    if _opened_folder is not None:
        close_folder(_opened_folder)
        _opened_folder = None


# ======================================================================
# Validation helpers
# ======================================================================

_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9][\w./-]+$")


def _validate_model_name(name: str) -> str | None:
    """
    Validate a model identifier string.

    Returns an error message string if invalid, or None if valid.
    """
    if not name or not name.strip():
        return "Model name cannot be empty"
    if not _MODEL_NAME_RE.match(name.strip()):
        return "Model name should be in the format: provider/model-name (e.g. gemini/gemini-2.0-flash)"
    if "/" not in name.strip():
        return "Model name should include a provider prefix (e.g. 'gemini/', 'claude-', 'deepseek/')"
    return None


def _validate_directory(path_str: str) -> str | None:
    """
    Validate a directory path string.

    Returns an error message string if invalid, or None if valid.
    Does NOT require the directory to exist yet (it will be created).
    """
    if not path_str or not path_str.strip():
        return "Path cannot be empty"
    p = Path(path_str.strip())
    if p.is_absolute():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            return f"Cannot access parent directory: {e}"
    return None


# ======================================================================
# Settings factory (avoids hardcoded fallback duplication)
# ======================================================================

def _settings_or_default() -> Settings | None:
    """
    Try to load Settings from env, returning None on failure.

    This factory is used by menus 2 and 3 which only need path
    information and do not require an API key.
    """
    try:
        return Settings.from_env()
    except ValueError:
        # Return a bare-minimum Settings for path-only operations
        return Settings(
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
            review_mode="basic",
        )


# ======================================================================
# .env helpers
# ======================================================================

# Version marker written into .env to detect when .env.example has new keys
_ENV_VERSION = "2"


def _ensure_env_file() -> Path:
    """Ensure .env exists (copy from .env.example if needed). Return its path."""
    env_path = _PROJECT_ROOT / ".env"
    example_path = _PROJECT_ROOT / ".env.example"

    if not env_path.exists() and example_path.exists():
        shutil.copy(example_path, env_path)
        logger.info("Created .env from .env.example template")

    if not env_path.exists():
        env_path.write_text(f"# Review Agent v{VERSION} configuration\nAPI_KEY=sk-your-api-key-here\n", encoding="utf-8")

    return env_path


def _update_env_file(key: str, value: str) -> None:
    """
    Update or add a key-value pair in the .env file.

    - Skips commented-out lines (does not match ``# KEY=...``)
    - Replaces existing active key, or appends if not found
    """
    env_path = _ensure_env_file()
    lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip comments
        if stripped.startswith("#"):
            continue
        # Match active KEY=value line
        if stripped.startswith(f"{key}=") or line.lstrip().startswith(f"{key}="):
            # Preserve any leading whitespace on this line
            leading = line[:len(line) - len(line.lstrip())]
            lines[i] = f"{leading}{key}={value}"
            found = True
            break

    if not found:
        lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _check_env_version() -> None:
    """
    Compare .env.example against .env and warn if the template has
    new keys not present in the user's .env file.
    """
    env_path = _PROJECT_ROOT / ".env"
    example_path = _PROJECT_ROOT / ".env.example"

    if not env_path.exists() or not example_path.exists():
        return

    # Parse active (non-comment) keys from both files
    def _active_keys(path: Path) -> set[str]:
        keys: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0].strip()
            if key:
                keys.add(key)
        return keys

    env_keys = _active_keys(env_path)
    example_keys = _active_keys(example_path)
    missing = example_keys - env_keys

    if missing:
        print(f"\n  [INFO] .env.example has new config keys not in your .env file:")
        for k in sorted(missing):
            print(f"         - {k}")
        print(f"  Consider reviewing .env.example for new options.")


# ======================================================================
# CJK font detection for PDF export
# ======================================================================

_CJK_FONT_CANDIDATES = {
    "Windows": [
        "C:/Windows/Fonts/msyh.ttc",       # Microsoft YaHei
        "C:/Windows/Fonts/simsun.ttc",     # SimSun
    ],
    "Darwin": [
        "/System/Library/Fonts/PingFang.ttc",          # PingFang SC
        "/System/Library/Fonts/STHeiti Light.ttc",     # Heiti SC
    ],
    "Linux": [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    ],
}


def _check_cjk_fonts() -> bool:
    """
    Check if CJK fonts are available on this system for PDF export.

    Returns True if at least one CJK font is found.
    """
    candidates = _CJK_FONT_CANDIDATES.get(sys.platform.capitalize() if sys.platform == "darwin" else
                                          "Windows" if os.name == "nt" else "Linux", [])

    for path in candidates:
        if Path(path).exists():
            return True
    return False


def _warn_missing_cjk_fonts() -> None:
    """Print a warning if CJK fonts are not found."""
    if not _check_cjk_fonts():
        print("\n  [WARN] No CJK (Chinese/Japanese/Korean) fonts detected on this system.")
        print("  PDF export may show blank squares instead of Chinese characters.")
        if sys.platform == "linux" or (sys.platform == "linux2"):
            print("  Install with: sudo apt install fonts-noto-cjk")
        elif sys.platform == "darwin":
            print("  PingFang SC should be installed by default. Check System Preferences.")
        elif os.name == "nt":
            print("  Microsoft YaHei should be installed by default on Chinese Windows.")


# ======================================================================
# Processing log capture (silent progress + error log export)
# ======================================================================

class _ProcessingLogCapture:
    """
    Context manager that suppresses console logs during processing,
    captures them to a temp file, and on error exports the log.

    Usage::

        with _ProcessingLogCapture() as cap:
            # ... run pipeline ...
            cap.mark_success()  # on success, delete temp log
        # on error or exception, log file is kept and path is printed
    """

    def __init__(self) -> None:
        self._temp_path: Path | None = None
        self._handler: logging.FileHandler | None = None
        self._old_levels: dict[str, int] = {}
        self._success = False

    def __enter__(self) -> "_ProcessingLogCapture":
        import tempfile
        # Create temp log file
        fd, tmp = tempfile.mkstemp(suffix=".log", prefix="review_agent_")
        os.close(fd)
        self._temp_path = Path(tmp)

        # Add file handler for full capture
        self._handler = logging.FileHandler(self._temp_path, encoding="utf-8")
        self._handler.setLevel(logging.DEBUG)
        self._handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-7s] %(name)s - %(message)s",
            datefmt="%H:%M:%S",
        ))
        root = logging.getLogger()
        root.addHandler(self._handler)

        # Suppress console: raise all logger levels to WARNING
        for name in ("main", "src", "prompts", ""):
            lg = logging.getLogger(name) if name else root
            self._old_levels[name] = lg.level
            lg.setLevel(logging.WARNING)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        root = logging.getLogger()
        if self._handler:
            self._handler.flush()
            root.removeHandler(self._handler)
            self._handler.close()

        # Restore old levels
        for name, level in self._old_levels.items():
            lg = logging.getLogger(name) if name else root
            lg.setLevel(level)

        if not self._success and self._temp_path and self._temp_path.exists():
            # Error occurred - export to permanent location
            dest = _PROJECT_ROOT / f"error_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            try:
                import shutil
                shutil.move(str(self._temp_path), str(dest))
                print(f"\n  [ERROR LOG] Full error details exported to:")
                print(f"    {dest.resolve()}")
            except Exception:
                if self._temp_path.exists():
                    print(f"\n  [ERROR LOG] See: {self._temp_path.resolve()}")
        elif self._temp_path and self._temp_path.exists():
            # Success - clean up
            self._temp_path.unlink(missing_ok=True)

        return False  # Don't suppress exceptions

    def mark_success(self) -> None:
        """Call after pipeline completes without errors."""
        self._success = True


# ======================================================================
# Interactive Menu Handlers
# ======================================================================

def menu_upload(settings: Settings) -> None:
    """
    Option 1: Upload and process files.

    1. Opens the input folder for the user to drop files in.
    2. Scans and lists all detected PPT/PDF files.
    3. Allows the user to select which files to process (or all).
    4. Processes selected files with a real-time progress bar.
    5. Optionally converts output to PDF.
    6. Opens the output folder on completion.
    """
    clear_screen()
    print_header("Upload & Process Files")

    input_dir = settings.input_dir
    input_dir.mkdir(parents=True, exist_ok=True)

    # Open the input folder for the user
    open_and_track(input_dir.resolve())

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

    # Scan for files
    scanner = FileScanner(input_dir, settings.supported_extensions)
    files = scanner.scan()

    if not files:
        print("  [INFO] No supported files found in the input directory.")
        print("  Please add .pptx, .ppt, or .pdf files and try again.")
        press_enter()
        return

    print(f"\n  [INFO] Found {len(files)} supported file(s):")
    for i, fp in enumerate(files, 1):
        try:
            rel = fp.relative_to(input_dir)
        except ValueError:
            rel = fp
        print(f"    [{i}] {rel}")
    print()

    # Check against state to find new/changed
    state_mgr = StateManager(settings.state_file)
    state = state_mgr.load_state()
    new_or_changed = state_mgr.find_new_or_changed(files, state)

    if not new_or_changed:
        print("  [INFO] All files are already up-to-date. Nothing to process.")
        press_enter()
        return

    # Mark which files are new/changed
    new_set = set(new_or_changed)
    print(f"  [INFO] {len(new_or_changed)} file(s) need processing:")
    new_indices: list[int] = []
    for i, fp in enumerate(files, 1):
        tag = " [NEW/MODIFIED]" if fp in new_set else " [up-to-date]"
        try:
            rel = fp.relative_to(input_dir)
        except ValueError:
            rel = fp
        print(f"    [{i}] {rel}{tag}")
        if fp in new_set:
            new_indices.append(i)
    print()

    # File selection loop (allows re-selection on "no")
    looping = False
    while True:
        if looping:
            clear_screen()
            print_header("Upload & Process Files")
            print(f"\n  [INFO] Found {len(files)} supported file(s):")
            for i, fp in enumerate(files, 1):
                tag = " [NEW/MODIFIED]" if fp in new_set else " [up-to-date]"
                try:
                    rel = fp.relative_to(input_dir)
                except ValueError:
                    rel = fp
                print(f"    [{i}] {rel}{tag}")
            print()

        print("  Select which files to process:")
        print("    - Press Enter to process ALL new/modified files")
        print("    - Enter file numbers separated by commas (e.g. 1,3,5)")
        print("    - Type 'all' to process everything including up-to-date files")
        print("    - Type 'b' to go back to main menu")
        print()
        selection = input("  Your choice: ").strip().lower()

        if selection == "b":
            print("  Cancelled.")
            press_enter()
            return

        selected_files: list[Path] = []
        if selection == "":
            selected_files = list(new_or_changed)
        elif selection == "all":
            selected_files = list(files)
        else:
            try:
                indices = [int(x.strip()) for x in selection.split(",") if x.strip()]
                for idx in indices:
                    if 1 <= idx <= len(files):
                        selected_files.append(files[idx - 1])
                    else:
                        print(f"  [WARN] Invalid index {idx}, skipping.")
            except ValueError:
                print("  [ERROR] Invalid input. Please try again.")
                looping = True
                continue

        if not selected_files:
            print("  [INFO] No files selected.")
            looping = True
            continue

        print(f"\n  [INFO] Will process {len(selected_files)} file(s):")
        for fp in selected_files:
            try:
                rel = fp.relative_to(input_dir)
            except ValueError:
                rel = fp
            print(f"    - {rel}")
        print()

        # Confirm
        choice = input("  Start processing? (y/n): ").strip().lower()
        if choice in ("y", "yes"):
            break  # Exit loop, proceed to processing
        looping = True  # Loop back to file selection

    # Build pipeline and run
    pipeline = Pipeline(settings)

    def cli_progress(message: str, fraction: float) -> None:
        pct = int(fraction * 100)
        bar_len = 30
        filled = int(bar_len * fraction)
        bar = "#" * filled + "-" * (bar_len - filled)
        print(f"\r  [{bar}] {pct:3d}%  {message}", end="", flush=True)

    print()
    log_capture = _ProcessingLogCapture()
    with log_capture:
        try:
            # Force only the selected files
            force_names = [fp.name for fp in selected_files]
            report = pipeline.run(progress_callback=cli_progress, force_files=force_names)
            log_capture.mark_success()
            print()  # newline after progress bar
            print_report(report)

            # Offer PDF conversion
            print()
            if report.processed > 0:
                # Check CJK fonts before offering PDF conversion
                _warn_missing_cjk_fonts()

                pdf_choice = input("\n  Convert generated notes to PDF? (y/n): ").strip().lower()
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
            print("\n\n  [INFO] Interrupted by user. Partial results have been saved.")
            try:
                state = state_mgr.load_state()
                state_mgr.save_state(state)
                print("  [INFO] Processing state saved for completed files.")
            except Exception:
                pass
        except Exception as exc:
            logger.exception(f"Fatal error: {exc}")
            print(f"\n  [ERROR] Pipeline failed: {exc}")

    # Open output folder for the user
    output_dir = settings.output_dir
    if output_dir.exists():
        print()
        print(f"  Opening output folder: {output_dir.resolve()}")
        open_and_track(output_dir.resolve())

    press_enter()


def menu_view_output(settings: Settings) -> None:
    """
    Option 2: View exported PDF files and output structure.

    Displays the output directory tree with PDF and MD files.
    Press 'o' to open the output folder in file explorer.
    """
    clear_screen()
    print_header("View Exported Files")

    output_dir = settings.output_dir

    if not output_dir.exists():
        print(f"\n  [INFO] Output directory does not exist yet.")
        print(f"  Expected location: {output_dir.resolve()}")
        print("  Run 'Upload & Process Files' first to generate notes.")
        print()
        print("  Press 'o' to open parent directory, or Enter to go back.")
        choice = input("  > ").strip().lower()
        if choice == "o":
            open_and_track(output_dir.parent.resolve())
        return

    # Find all PDF and MD files
    pdf_files = sorted(output_dir.rglob("*.pdf"))
    md_files = sorted(output_dir.rglob("*.md"))

    if not pdf_files and not md_files:
        print(f"\n  [INFO] No PDF or MD files found in output directory.")
        print(f"  Location: {output_dir.resolve()}")
        print()
        print("  Press 'o' to open the output folder, or Enter to go back.")
        choice = input("  > ").strip().lower()
        if choice == "o":
            open_and_track(output_dir.resolve())
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

    print()
    print("  Press 'o' to open the output folder, or Enter to go back.")
    choice = input("  > ").strip().lower()
    if choice == "o":
        open_and_track(output_dir.resolve())


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

    # Check for new .env keys
    _check_env_version()

    # Load current values from environment
    if current_settings is None:
        try:
            current_settings = Settings.from_env()
        except ValueError:
            pass

    while True:
        clear_screen()
        print_header("Settings")

        # Display current configuration
        if current_settings:
            key_display = "***" + current_settings.classifier_api_key[-4:] if len(current_settings.classifier_api_key) >= 4 else "(not set)"
            print(f"\n  [1] API Key:          {key_display}")
            print(f"  [2] Model Preset:      {current_settings.preset or 'custom'}")
            print(f"  [3] Classifier Model:  {current_settings.classifier_model}")
            print(f"  [4] Summarizer Model:  {current_settings.summarizer_model}")
            print(f"  [5] Lab Solver Model:  {current_settings.lab_solver_model}")
            print(f"  [6] Input Directory:   {current_settings.input_dir}")
            print(f"  [7] Output Directory:  {current_settings.output_dir}")
            print(f"  [8] Log Level:         {current_settings.log_level}")
            print(f"  [9] Review Mode:       {current_settings.review_mode}")
        else:
            print(f"\n  [1] API Key:          (not set)")
            print(f"  [2] Model Preset:      balanced")
            print(f"  [3-5] Models:          (using preset defaults)")
            print(f"  [6] Input Directory:   01_Input_PPTs")
            print(f"  [7] Output Directory:  02_Output_Notes")
            print(f"  [8] Log Level:         INFO")
            print(f"  [9] Review Mode:       basic")

        print(f"\n  [0] View/edit .env file directly")
        print(f"  [R] Return to main menu")

        print()
        choice = input("  Select a setting to modify (0-9, R=return): ").strip()

        if choice.upper() == "R":
            break
        elif choice == "0":
            _edit_env_file()
            press_enter()
        elif choice == "1":
            print()
            new_key = input("  Enter new API key (or press Enter to keep current): ").strip()
            if new_key:
                if len(new_key) < 8:
                    print("  [WARN] API key seems too short (< 8 chars). Are you sure?")
                    confirm = input("  Continue anyway? (y/n): ").strip().lower()
                    if confirm not in ("y", "yes"):
                        press_enter()
                        continue
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
                print(f"  Valid options: {', '.join(MODEL_PRESETS.keys())}")
            press_enter()
        elif choice in ("3", "4", "5"):
            model_type = {"3": "classifier", "4": "summarizer", "5": "lab solver"}[choice]
            env_key = {"3": "CLASSIFIER_MODEL", "4": "SUMMARIZER_MODEL", "5": "LAB_SOLVER_MODEL"}[choice]
            examples = {"3": "gemini/gemini-2.0-flash", "4": "claude-sonnet-4-20250514", "5": "deepseek/deepseek-chat"}[choice]
            print()
            new_model = input(f"  Enter {model_type} model (e.g. {examples}): ").strip()
            if new_model:
                error = _validate_model_name(new_model)
                if error:
                    print(f"  [WARN] {error}")
                    confirm = input("  Save anyway? (y/n): ").strip().lower()
                    if confirm not in ("y", "yes"):
                        press_enter()
                        continue
                os.environ[env_key] = new_model
                _update_env_file(env_key, new_model)
                print(f"  [OK] {model_type.capitalize()} model updated.")
            press_enter()
        elif choice in ("6", "7"):
            dir_type = "input" if choice == "6" else "output"
            env_key = "INPUT_DIR" if choice == "6" else "OUTPUT_DIR"
            print()
            new_dir = input(f"  Enter new {dir_type} directory path: ").strip()
            if new_dir:
                error = _validate_directory(new_dir)
                if error:
                    print(f"  [ERROR] {error}")
                    press_enter()
                    continue
                os.environ[env_key] = new_dir
                _update_env_file(env_key, new_dir)
                # Create the directory
                Path(new_dir).mkdir(parents=True, exist_ok=True)
                print(f"  [OK] {dir_type.capitalize()} directory set to: {new_dir}")
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
                print(f"  [ERROR] Invalid log level. Valid: DEBUG, INFO, WARNING, ERROR")
            press_enter()
        elif choice == "9":
            print()
            print("  Review mode controls post-processing quality checks:")
            print("    off   - No review (fastest, may contain artifacts)")
            print("    basic - Regex-based cleanup (recommended, no extra API cost)")
            print("    deep  - Full LLM review pass (most thorough, extra API call)")
            print()
            new_mode = input("  Enter review mode (off/basic/deep): ").strip().lower()
            if new_mode in ("off", "basic", "deep"):
                os.environ["REVIEW_MODE"] = new_mode
                _update_env_file("REVIEW_MODE", new_mode)
                print(f"  [OK] Review mode set to: {new_mode}")
            else:
                print(f"  [ERROR] Invalid mode. Valid: off, basic, deep")
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


def _edit_env_file() -> None:
    """Display the .env file contents (with masked API keys) for review."""
    env_path = _ensure_env_file()

    print(f"\n  .env file location: {env_path.resolve()}")
    print()
    print("  Current .env contents:")
    print("  " + "-" * 55)
    content = env_path.read_text(encoding="utf-8")
    for line in content.splitlines():
        # Mask API keys in display
        if any(line.strip().startswith(k) for k in (
            "API_KEY=", "CLASSIFIER_API_KEY=",
            "SUMMARIZER_API_KEY=", "LAB_SOLVER_API_KEY=",
        )):
            parts = line.split("=", 1)
            if len(parts) == 2 and len(parts[1]) > 4:
                prefix = line[:len(line) - len(line.lstrip())]
                print(f"  {prefix}{parts[0]}={'*' * (len(parts[1]) - 4)}{parts[1][-4:]}")
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
              python main.py                              Process all new/changed files
              python main.py --dry-run                    Preview what would be processed
              python main.py --force lecture1.pptx        Force reprocess a specific file
              python main.py --preset budget              Use budget-friendly models
              python main.py --input ./my_ppts --output ./my_notes
              python main.py --pdf --log-file agent.log   Process with PDF export + log to file
        """),
    )
    parser.add_argument(
        "--version", action="version",
        version=f"Review Agent v{VERSION}",
        help="Show version and exit",
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
        "--log-file", type=str, default=None,
        help="Write logs to a file in addition to console output",
    )
    parser.add_argument(
        "--pdf", action="store_true",
        help="Convert generated Markdown notes to PDF (requires playwright + chromium)",
    )
    args = parser.parse_args()

    setup_logging(args.log_level, log_file=args.log_file)
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

    logger.info(f"Review Agent v{VERSION}")
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
        print("\n\nInterrupted by user. Partial results saved.", file=sys.stderr)
        # Save whatever progress was made
        try:
            from src.scanner.state_manager import StateManager
            mgr = StateManager(settings.state_file)
            state = mgr.load_state()
            mgr.save_state(state)
        except Exception:
            pass
        sys.exit(130)
    except Exception as exc:
        logger.exception(f"Fatal error: {exc}")
        sys.exit(1)


# ======================================================================
# Startup validation & first-time setup
# ======================================================================

def _test_api_connection(settings: Settings) -> tuple[bool, str]:
    """
    Test whether the configured API key and model can connect successfully.

    Makes a minimal completion request (1 token) to verify the API key
    and network connectivity.

    Returns
    -------
    tuple[bool, str]
        (success, message) -- message is a user-friendly status/error string.
    """
    model = settings.classifier_model
    api_key = settings.classifier_api_key

    if not api_key:
        return False, "No API key configured."

    try:
        from litellm import completion

        response = completion(
            model=model,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=1,
            api_key=api_key,
            timeout=15,
        )
        _ = response.choices[0].message.content
        return True, f"Connected successfully to {model}"
    except ImportError:
        return False, "litellm package not installed. Run: pip install litellm"
    except Exception as exc:
        err_msg = str(exc).strip()
        # Extract the most useful part of the error
        if len(err_msg) > 200:
            err_msg = err_msg[:200] + "..."
        return False, f"Connection failed: {err_msg}"


def _first_time_setup() -> Settings | None:
    """
    Guided first-time setup: configure API key, choose preset, test connection.

    Returns
    -------
    Settings | None
        Validated Settings object, or None if the user wants to exit.
    """
    clear_screen()
    print()
    print("=" * 60)
    print(f"  Welcome to Review Agent v{VERSION}")
    print("  AI-Powered Lecture Note Generator")
    print("=" * 60)
    print()
    print("  It looks like this is your first time running Review Agent,")
    print("  or your API key is not yet configured.")
    print()
    print("  Let's set things up. You will need:")
    print("    - An API key from an LLM provider (e.g. DeepSeek, OpenAI, etc.)")
    print("    - (Optional) A preferred model preset")
    print()
    print("  Supported providers via LiteLLM:")
    print("    OpenAI | Anthropic | Google (Gemini) | DeepSeek | Ollama | ...")
    print()

    # Step 1: API Key
    while True:
        print("-" * 60)
        api_key = input("  Step 1: Enter your API key: ").strip()
        if not api_key:
            print("  [ERROR] API key cannot be empty.")
            again = input("  Try again? (y/n): ").strip().lower()
            if again not in ("y", "yes"):
                return None
            continue
        if len(api_key) < 8:
            print("  [WARN] API key seems too short (< 8 characters).")
            confirm = input("  Use this key anyway? (y/n): ").strip().lower()
            if confirm not in ("y", "yes"):
                continue
        break

    os.environ["API_KEY"] = api_key
    _update_env_file("API_KEY", api_key)

    # Step 2: Choose preset
    print()
    print("-" * 60)
    print("  Step 2: Choose a model preset (or press Enter for 'balanced'):")
    print()
    for name, models in MODEL_PRESETS.items():
        print(f"    {name:<12} classifier={models['classifier']}")
        print(f"              summarizer={models['summarizer']}")
        print(f"              lab_solver={models['lab_solver']}")
        print()
    preset = input("  Preset [budget/balanced/maximum, default: balanced]: ").strip().lower()
    if preset not in MODEL_PRESETS:
        preset = "balanced"
    os.environ["PRESET"] = preset
    _update_env_file("PRESET", preset)
    print(f"  [OK] Using '{preset}' preset.")

    # Step 3: Test connection
    print()
    print("-" * 60)
    print("  Step 3: Testing connection...")
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(f"  [ERROR] Configuration error: {exc}")
        press_enter()
        return None

    success, message = _test_api_connection(settings)
    if success:
        print(f"  [OK] {message}")
        print()
        print("=" * 60)
        print("  Setup complete! You're ready to go.")
        print("=" * 60)
        press_enter()
        return settings
    else:
        print(f"  [FAIL] {message}")
        print()
        print("  Troubleshooting tips:")
        print("    1. Check that your API key is correct and not expired")
        print("    2. Check your internet connection")
        print("    3. If using a custom API base, edit .env directly")
        print("    4. Try a different model (you can change it in Settings later)")
        print()
        print("  You can continue without a working connection, but processing")
        print("  will fail until the API key issue is resolved.")
        choice = input("  Continue anyway? (y/n): ").strip().lower()
        if choice in ("y", "yes"):
            print("  [INFO] Continuing with unverified API key. You can reconfigure in [4] Settings.")
            press_enter()
            return settings
        return None


def menu_regenerate(settings: Settings) -> None:
    """
    Option 5: Regenerate files.

    1. Confirmation prompt before proceeding.
    2. Scans and groups files by parent folder.
    3. User selects which folder(s) to regenerate.
    4. Deletes old output folders, clears state records.
    5. Runs the pipeline. Results overwrite existing output.
    """
    clear_screen()
    print_header("Regenerate Files")

    # Step 1: Confirmation
    print()
    print("  WARNING: This will DELETE the existing output for selected")
    print("  courses and reprocess them from scratch.")
    print()
    choice = input("  Are you sure you want to continue? (y/n): ").strip().lower()
    if choice not in ("y", "yes"):
        print("  Cancelled.")
        press_enter()
        return

    # Step 2: Scan and group files by parent folder
    input_dir = settings.input_dir
    input_dir.mkdir(parents=True, exist_ok=True)
    scanner = FileScanner(input_dir, settings.supported_extensions)
    files = scanner.scan()

    if not files:
        print(f"\n  [INFO] No supported files found in the input directory.")
        press_enter()
        return

    # Group files by top-level folder name (first component of relative path)
    state_mgr = StateManager(settings.state_file)
    state = state_mgr.load_state()
    groups: dict[str, list[Path]] = {}
    for fp in files:
        try:
            rel = fp.relative_to(input_dir)
            # Use only the first path component as the group name
            parts = rel.parts
            folder = parts[0] if parts else "(root)"
        except ValueError:
            folder = "(root)"
        groups.setdefault(folder, []).append(fp)

    # Sort groups by name
    sorted_groups = sorted(groups.items(), key=lambda x: x[0].lower())

    print(f"\n  Found {len(files)} file(s) in {len(sorted_groups)} folder(s):\n")
    for i, (folder, folder_files) in enumerate(sorted_groups, 1):
        # Find latest timestamp in this group
        latest = ""
        for fp in folder_files:
            record = state.get(fp.name)
            if record and record.last_processed > latest:
                latest = record.last_processed
        tag = f" [last: {latest[:16]}]" if latest else ""
        print(f"    [{i}] {folder}  ({len(folder_files)} files{tag})")
    print()

    # Step 3: Select folders + confirm (loop on "no")
    looping = False
    while True:
        if looping:
            clear_screen()
            print_header("Regenerate Files")
            print(f"\n  {len(sorted_groups)} folder(s) available:\n")
            for i, (folder, folder_files) in enumerate(sorted_groups, 1):
                latest = ""
                for fp in folder_files:
                    record = state.get(fp.name)
                    if record and record.last_processed > latest:
                        latest = record.last_processed
                tag = f" [last: {latest[:16]}]" if latest else ""
                print(f"    [{i}] {folder}  ({len(folder_files)} files{tag})")
            print()

        print("  Which folder do you want to regenerate?")
        print("    - Enter folder numbers separated by commas (e.g. 1,3)")
        print("    - Enter 'all' to regenerate everything")
        print("    - Type 'b' to go back to main menu")
        print()
        selection = input("  Your choice: ").strip().lower()

        if selection == "b":
            print("  Cancelled.")
            press_enter()
            return

        selected_groups: list[tuple[str, list[Path]]] = []
        if selection == "all":
            selected_groups = list(sorted_groups)
        else:
            try:
                indices = [int(x.strip()) for x in selection.split(",") if x.strip()]
                for idx in indices:
                    if 1 <= idx <= len(sorted_groups):
                        selected_groups.append(sorted_groups[idx - 1])
                    else:
                        print(f"  [WARN] Invalid index {idx}, skipping.")
            except ValueError:
                print("  [ERROR] Invalid input. Please try again.")
                looping = True
                continue

        if not selected_groups:
            print("  [INFO] No folder selected.")
            looping = True
            continue

        # Flatten selected groups to file list
        selected_files: list[Path] = []
        print(f"\n  Will regenerate {len(selected_groups)} folder(s):")
        for folder, folder_files in selected_groups:
            print(f"    - {folder} ({len(folder_files)} files)")
            selected_files.extend(folder_files)
        print()

        # Confirmation
        choice = input("  Start regeneration? This will DELETE old output first. (y/n): ").strip().lower()
        if choice in ("y", "yes"):
            break
        looping = True

    # Step 4: Delete old output folders and clear state
    import shutil as _shutil
    output_dir = settings.output_dir
    deleted_count = 0

    for folder, folder_files in selected_groups:
        # Find the course name from state records of files in this group
        course_name = None
        for fp in folder_files:
            record = state.get(fp.name)
            if record and record.output_path:
                # output_path like "SOF 103/Week_01_..." → course = "SOF 103"
                course_name = record.output_path.split("/")[0].split("\\")[0]
                break

        # Fallback: try folder name as course name
        if not course_name and folder != "(root)":
            candidate = output_dir / folder
            if candidate.exists():
                course_name = folder

        if course_name:
            target = output_dir / course_name
            if target.exists():
                _shutil.rmtree(target, ignore_errors=True)
                logger.info(f"Deleted old output: {target}")
                deleted_count += 1
                print(f"  [INFO] Deleted: {target.name}/")

    # Clear state for all selected files
    for fp in selected_files:
        if fp.name in state:
            del state[fp.name]
    state_mgr.save_state(state)

    if deleted_count > 0:
        print(f"  [INFO] Deleted {deleted_count} old output folder(s).")

    # Step 5: Run the pipeline
    pipeline = Pipeline(settings)

    def cli_progress(message: str, fraction: float) -> None:
        pct = int(fraction * 100)
        bar_len = 30
        filled = int(bar_len * fraction)
        bar = "#" * filled + "-" * (bar_len - filled)
        print(f"\r  [{bar}] {pct:3d}%  {message}", end="", flush=True)

    print()
    log_capture = _ProcessingLogCapture()
    with log_capture:
        try:
            force_names = [fp.name for fp in selected_files]
            report = pipeline.run(progress_callback=cli_progress, force_files=force_names)
            log_capture.mark_success()
            print()
            print_report(report)

            if report.processed > 0:
                _warn_missing_cjk_fonts()
                pdf_choice = input("\n  Convert regenerated notes to PDF? (y/n): ").strip().lower()
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
            print("\n\n  [INFO] Interrupted by user. Partial results saved.")
            try:
                state = state_mgr.load_state()
                state_mgr.save_state(state)
            except Exception:
                pass
        except Exception as exc:
            logger.exception(f"Regeneration failed: {exc}")
            print(f"\n  [ERROR] Regeneration failed: {exc}")

    if output_dir.exists():
        print()
        print(f"  Opening output folder: {output_dir.resolve()}")
        open_and_track(output_dir.resolve())

    press_enter()


def _startup_check() -> Settings | None:
    """
    Run on every interactive launch: verify API key is configured and working.

    Returns
    -------
    Settings | None
        Validated Settings, or None to exit.
    """
    setup_logging("WARNING")  # Suppress noisy logs during startup

    # Try loading settings
    try:
        settings = Settings.from_env()
    except ValueError:
        # No API key configured -- run first-time setup
        return _first_time_setup()

    # API key is configured, but is it valid?
    success, message = _test_api_connection(settings)

    # Restore normal logging
    setup_logging(settings.log_level if settings else "INFO")

    if success:
        logger.info(f"API connection verified: {message}")
        return settings

    # Connection failed
    clear_screen()
    print()
    print("=" * 60)
    print(f"  Review Agent v{VERSION} -- Startup Check")
    print("=" * 60)
    print()
    print(f"  [WARN] Could not connect to the API with the current settings.")
    print(f"  Model: {settings.classifier_model}")
    print(f"  Error: {message}")
    print()
    print("  What would you like to do?")
    print("    [1] Go to Settings to fix configuration")
    print("    [2] Continue anyway (processing will likely fail)")
    print("    [3] Exit")
    print()
    choice = input("  Select an option [1-3]: ").strip()

    if choice == "1":
        new_settings = menu_settings(settings)
        if new_settings is None:
            new_settings = _settings_or_default()
        # Re-test after settings change
        if new_settings and new_settings.classifier_api_key:
            success2, msg2 = _test_api_connection(new_settings)
            if success2:
                print(f"\n  [OK] {msg2}")
                press_enter()
                return new_settings
            else:
                print(f"\n  [FAIL] Still unable to connect: {msg2}")
                print("  You can continue and try again from [4] Settings.")
                press_enter()
                return new_settings
        return new_settings
    elif choice == "2":
        print("  [INFO] Continuing with unverified connection.")
        press_enter()
        return settings
    elif choice == "3":
        return None
    else:
        print("  [INFO] Continuing with unverified connection.")
        press_enter()
        return settings


# ======================================================================
# Interactive Menu (main mode)
# ======================================================================

def interactive_main() -> None:
    """Run the Review Agent in interactive CLI menu mode."""
    setup_logging("INFO")

    # Check .env version
    _check_env_version()

    # ---- Startup validation: check API key before entering main menu ----
    settings = _startup_check()
    if settings is None:
        print("\n  Goodbye!")
        sys.exit(0)

    while True:
        clear_screen()
        print()
        print("=" * 60)
        print(f"         Review Agent v{VERSION}")
        print("    AI-Powered Lecture Note Generator")
        print("=" * 60)
        print()
        print("  [1] Upload & Process Files")
        print("  [2] View Exported PDFs / Output")
        print("  [3] Processing History")
        print("  [4] Settings")
        print("  [5] Regenerate Files")
        print("  [6] Exit")
        print()

        # Quick status line
        if settings:
            try:
                input_count = FileScanner(settings.input_dir, settings.supported_extensions).get_file_count()
                key_ok = bool(settings.classifier_api_key)
            except ValueError:
                input_count = 0
                key_ok = False
            print(f"  Status: {input_count} file(s) in input | "
                  f"API key: {'configured' if key_ok else 'MISSING'}"
                  f" | Preset: {settings.preset or 'custom'}")
        else:
            print(f"  Status: API key NOT configured. Go to [4] Settings to set up.")

        print()
        choice = input("  Select an option [1-6]: ").strip()

        if choice == "1":
            if settings is None or not settings.classifier_api_key:
                try:
                    settings = Settings.from_env()
                except ValueError as exc:
                    print(f"\n  [ERROR] Configuration required: {exc}")
                    print("  Go to [4] Settings to configure your API key first.")
                    press_enter()
                    continue
            menu_upload(settings)
        elif choice == "2":
            settings = _settings_or_default()
            menu_view_output(settings)
        elif choice == "3":
            settings = _settings_or_default()
            menu_history(settings)
        elif choice == "4":
            settings = menu_settings(settings)
            if settings is None:
                settings = _settings_or_default()
        elif choice == "5":
            if settings is None or not settings.classifier_api_key:
                try:
                    settings = Settings.from_env()
                except ValueError as exc:
                    print(f"\n  [ERROR] Configuration required: {exc}")
                    print("  Go to [4] Settings to configure your API key first.")
                    press_enter()
                    continue
            menu_regenerate(settings)
        elif choice == "6":
            print("\n  Goodbye!")
            sys.exit(0)
        else:
            print("\n  Invalid choice. Please enter a number from 1 to 6.")
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
