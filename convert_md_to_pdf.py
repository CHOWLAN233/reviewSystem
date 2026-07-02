#!/usr/bin/env python3
"""
Convert all generated Markdown files to PDF.

Reads .md files from the course-level ``md/`` subfolder and writes
PDF output into the corresponding week folder alongside the source PPT.

Output structure:
    02_Output_Notes/
    └── {Course_Name}/
        ├── md/                                    <-- source .md files (course level)
        │   ├── Week_01_Topic_summary.md
        │   └── Week_01_Topic_lab_solution.md
        ├── Week_01_Topic/
        │   ├── summary.pdf                         <-- generated PDF
        │   ├── lab_solution.pdf                    <-- generated PDF
        │   └── original_file.ppt
        └── Week_02_Another_Topic/
            └── ...
"""

import logging
import re
import sys
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Project root is the directory containing this script
PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "02_Output_Notes"

# CJK-capable CSS optimized for Chromium rendering
PDF_CSS = """
@page {
    size: A4;
    margin: 2cm 2.2cm;
}

body {
    font-family: 'Microsoft YaHei', 'SimHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif;
    font-size: 12pt;
    line-height: 1.8;
    color: #1a1a1a;
    max-width: 100%;
}

h1 {
    font-size: 22pt;
    border-bottom: 2px solid #2c3e50;
    padding-bottom: 8px;
    margin-top: 0;
    color: #2c3e50;
}

h2 {
    font-size: 16pt;
    border-bottom: 1px solid #bdc3c7;
    padding-bottom: 4px;
    margin-top: 24px;
    color: #34495e;
}

h3 {
    font-size: 13pt;
    margin-top: 18px;
    color: #555;
}

h4 {
    font-size: 11pt;
    margin-top: 14px;
    color: #666;
}

code {
    font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
    background: #f4f4f4;
    padding: 2px 5px;
    border-radius: 3px;
    font-size: 10pt;
    word-break: break-all;
}

pre {
    background: #f8f8f8;
    border: 1px solid #ddd;
    border-left: 3px solid #3498db;
    padding: 12px;
    border-radius: 4px;
    overflow-x: auto;
    font-size: 9.5pt;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-all;
}

pre code {
    background: none;
    padding: 0;
}

table {
    border-collapse: collapse;
    width: 100%;
    margin: 12px 0;
    font-size: 10pt;
    page-break-inside: avoid;
}

th, td {
    border: 1px solid #ccc;
    padding: 6px 10px;
    text-align: left;
    vertical-align: top;
}

th {
    background: #ecf0f1;
    font-weight: bold;
}

blockquote {
    border-left: 4px solid #3498db;
    margin: 12px 0;
    padding: 6px 16px;
    background: #f0f7fb;
    color: #555;
}

ul, ol {
    padding-left: 24px;
}

li {
    margin: 3px 0;
}

strong {
    color: #2c3e50;
}

hr {
    border: none;
    border-top: 1px solid #ddd;
    margin: 20px 0;
}

a {
    color: #2980b9;
    text-decoration: none;
}
"""


def md_to_html(md_path: Path) -> str:
    """Convert a Markdown file to a complete HTML document."""
    md_text = md_path.read_text(encoding="utf-8")

    # Convert Markdown to HTML body
    md_extensions = [
        "fenced_code",
        "tables",
        "codehilite",
        "toc",
        "nl2br",
        "sane_lists",
    ]
    body_html = markdown.markdown(md_text, extensions=md_extensions)

    # Wrap in a full HTML document with CSS
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>{PDF_CSS}</style>
</head>
<body>
{body_html}
</body>
</html>"""
    return html


def find_week_dir(course_dir: Path, week_name: str) -> Path:
    """
    Given a course directory and a week folder name (e.g. ``Week_01_Introduction``),
    return the matching week directory.

    Falls back to creating the directory if it does not exist.
    """
    week_dir = course_dir / week_name
    week_dir.mkdir(parents=True, exist_ok=True)
    return week_dir


def parse_md_filename(md_filename: str) -> tuple[str | None, str | None]:
    """
    Parse an md filename like ``Week_01_Introduction_summary.md``
    into ``(week_name, file_type)``.

    Returns
    -------
    tuple[str | None, str | None]
        (week_folder_name, file_type)  e.g. ("Week_01_Introduction", "summary")
        or (None, None) if the filename does not match the pattern.
    """
    stem = Path(md_filename).stem  # e.g. "Week_01_Introduction_summary"

    # Try to match: Week_NN_TopicName_type
    pattern = r'^(Week_\d{2}_.+)_(summary|lab_solution)$'
    match = re.match(pattern, stem)
    if match:
        return match.group(1), match.group(2)

    return None, None


def convert_all(output_dir: Path) -> None:
    """
    Find all .md files in course-level ``md/`` folders and convert them
    to PDF in the corresponding week folder.
    """
    # Find md/ folders at the course level
    md_dirs = list(output_dir.glob("*/md"))
    if not md_dirs:
        logger.warning(f"No course-level md/ folders found in {output_dir}")
        return

    md_files: list[tuple[Path, str, str]] = []  # (md_path, course_name, week_name, type)
    for md_dir in md_dirs:
        course_name = md_dir.parent.name
        for f in sorted(md_dir.glob("*.md")):
            week_name, file_type = parse_md_filename(f.name)
            if week_name and file_type:
                md_files.append((f, course_name, week_name, file_type))
            else:
                logger.warning(f"Cannot parse filename: {f.name}, skipping.")

    if not md_files:
        logger.warning("No parseable .md files found.")
        return

    logger.info(f"Found {len(md_files)} Markdown file(s) to convert")
    logger.info("Launching headless Chromium (one-time) ...")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()

        for md_path, course_name, week_name, file_type in md_files:
            # PDF goes into the week folder
            week_dir = output_dir / course_name / week_name
            week_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = week_dir / f"{file_type}.pdf"

            rel = md_path.relative_to(output_dir)
            logger.info(f"Converting: {rel}")

            try:
                html = md_to_html(md_path)

                page = context.new_page()
                page.set_content(html, wait_until="networkidle")
                page.pdf(
                    path=str(pdf_path),
                    format="A4",
                    margin={"top": "2cm", "bottom": "2cm", "left": "2.2cm", "right": "2.2cm"},
                    print_background=True,
                )
                page.close()

                pdf_rel = pdf_path.relative_to(output_dir)
                pdf_size = pdf_path.stat().st_size / 1024
                logger.info(f"  -> PDF: {pdf_rel} ({pdf_size:.0f} KB)")
            except Exception as exc:
                logger.error(f"  [FAIL] {rel}: {exc}")
                continue

        browser.close()

    logger.info("Done!")


if __name__ == "__main__":
    convert_all(OUTPUT_DIR)
