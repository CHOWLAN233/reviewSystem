#!/usr/bin/env python3
"""
Convert all generated Markdown files to PDF and reorganize output.

- Converts summary.md / lab_solution.md → PDF using markdown + Playwright (Chromium)
- Moves .md files into a `md/` subfolder within each week's directory
- Preserves original .ppt files in place
"""

import logging
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


def convert_all(output_dir: Path) -> None:
    """Find all .md files and convert them to PDF, then move to md/ subfolder."""
    md_files = list(output_dir.rglob("*.md"))
    if not md_files:
        logger.warning(f"No .md files found in {output_dir}")
        return

    logger.info(f"Found {len(md_files)} Markdown file(s) to convert")
    logger.info("Launching headless Chromium (one-time) …")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()

        for md_path in md_files:
            pdf_path = md_path.with_suffix(".pdf")

            logger.info(f"Converting: {md_path.relative_to(output_dir)}")
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
                logger.info(f"  → PDF: {pdf_path.relative_to(output_dir)}")
            except Exception as exc:
                logger.error(f"  ✗ Failed: {exc}")
                continue

            # Move .md into md/ subfolder
            md_dir = md_path.parent / "md"
            md_dir.mkdir(parents=True, exist_ok=True)
            new_md_path = md_dir / md_path.name
            md_path.rename(new_md_path)
            logger.info(f"  → MD moved: {new_md_path.relative_to(output_dir)}")

        browser.close()

    logger.info("Done!")


if __name__ == "__main__":
    convert_all(OUTPUT_DIR)
