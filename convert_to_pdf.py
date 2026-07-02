"""
Convert all generated summary.md files to PDF.

Uses markdown → HTML → PDF pipeline with fpdf2 (pure Python, no native deps).
Features: Table of Contents, CJK font support, clean typography.
"""

import re as _re
import sys
from pathlib import Path
from markdown import markdown
from fpdf import FPDF

OUTPUT_DIR = Path(__file__).parent / "02_Output_Notes"

# Windows Chinese fonts, ordered by preference
CJK_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",       # Microsoft YaHei
    "C:/Windows/Fonts/msyhbd.ttc",     # Microsoft YaHei Bold
    "C:/Windows/Fonts/simsun.ttc",     # SimSun
    "C:/Windows/Fonts/simhei.ttf",     # SimHei
    "C:/Windows/Fonts/NotoSansCJKsc-VF.otf.ttc",
]


def find_cjk_font():
    """Locate a CJK-capable TTF/OTC font on the system."""
    for path in CJK_FONT_CANDIDATES:
        p = Path(path)
        if p.exists():
            return str(p)
    return None


def generate_toc_page(pdf: FPDF, md_text: str, font_name: str) -> None:
    """Parse markdown headers (## and ###) and add a Table of Contents page."""
    pdf.add_page()

    # TOC title
    pdf.set_font(font_name, "B", 20)
    pdf.cell(0, 14, "Table of Contents / 目录", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(6)

    # Horizontal rule (using a thin line)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(6)

    # Parse headers
    headers = []
    for line in md_text.split("\n"):
        m = _re.match(r"^(#{2,3})\s+(.+)", line.strip())
        if m:
            level = len(m.group(1))  # 2 or 3
            title = m.group(2).strip()
            headers.append((level, title))

    # Render TOC entries
    for level, title in headers:
        indent = 8 if level == 3 else 0
        font_size = 10 if level == 3 else 11
        font_style = "" if level == 3 else "B"
        prefix = "    └ " if level == 3 else ""

        pdf.set_font(font_name, font_style, font_size)
        pdf.set_x(pdf.l_margin + indent)

        # Truncate long titles
        display_title = title[:90] + ("..." if len(title) > 90 else "")
        pdf.cell(0, 7, f"{prefix}{display_title}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(8)


def build_pdf(md_path: Path, font_path: str) -> FPDF:
    """Convert a markdown file to a styled FPDF object."""
    md_text = md_path.read_text(encoding="utf-8")

    # Markdown → HTML (without codehilite which produces unrenderable CSS classes)
    html_body = markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists"],
    )

    # Register font first to know the font name
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_left_margin(20)
    pdf.set_right_margin(20)

    is_cjk = "C:/Windows/Fonts" in font_path
    if is_cjk:
        pdf.add_font("CJK", "", font_path)
        pdf.add_font("CJK", "B", font_path)
        font_name = "CJK"
    else:
        pdf.add_font("Custom", "", font_path)
        pdf.add_font("Custom", "B", font_path)
        font_name = "Custom"

    # Generate Table of Contents page first
    generate_toc_page(pdf, md_text, font_name)

    # Build styled HTML wrapper with improved spacing and typography
    html_full = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
    body {{
        font-family: '{font_name}';
        font-size: 11pt;
        line-height: 1.8;
        color: #222;
    }}
    h1 {{
        font-size: 18pt;
        margin-top: 6pt;
        margin-bottom: 12pt;
        color: #1a1a2e;
        border-bottom: 2px solid #cccccc;
        padding-bottom: 6pt;
    }}
    h2 {{
        font-size: 14pt;
        margin-top: 18pt;
        margin-bottom: 8pt;
        color: #2b5797;
    }}
    h3 {{
        font-size: 12pt;
        margin-top: 14pt;
        margin-bottom: 6pt;
    }}
    h4 {{
        font-size: 11pt;
        margin-top: 10pt;
        margin-bottom: 4pt;
    }}
    p {{
        margin-top: 4pt;
        margin-bottom: 8pt;
    }}
    ul, ol {{
        margin-top: 4pt;
        margin-bottom: 8pt;
        padding-left: 20pt;
    }}
    li {{
        margin-bottom: 4pt;
    }}
    code {{
        font-family: Courier;
        background-color: #f0f0f0;
        padding: 1pt 3pt;
        font-size: 9pt;
    }}
    pre {{
        background-color: #f5f5f5;
        padding: 8pt;
        font-size: 9pt;
        line-height: 1.4;
        border-left: 3pt solid #2b5797;
        margin-top: 6pt;
        margin-bottom: 10pt;
    }}
    table {{
        border-collapse: collapse;
        width: 100%;
        margin-top: 6pt;
        margin-bottom: 12pt;
        font-size: 9.5pt;
    }}
    th, td {{
        border: 1px solid #cccccc;
        padding: 4pt 6pt;
        text-align: left;
    }}
    th {{
        background-color: #e8ecf1;
        font-weight: bold;
    }}
    blockquote {{
        border-left: 3pt solid #cccccc;
        padding-left: 10pt;
        color: #555555;
        margin: 8pt 0;
    }}
    hr {{
        border: none;
        border-top: 1px solid #dddddd;
        margin: 14pt 0;
    }}
    strong {{
        color: #1a1a2e;
    }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

    pdf.add_page()
    try:
        pdf.write_html(html_full, font_family=font_name)
    except Exception as exc:
        # If write_html fails (e.g. due to font issues), fall back to plain text
        _fallback_text_render(pdf, md_text, font_name)

    return pdf


def _fallback_text_render(pdf: FPDF, md_text: str, font_name: str) -> None:
    """Fallback: render markdown as plain text, stripping formatting."""
    pdf.set_font(font_name, "", 10)
    for line in md_text.split("\n"):
        # Strip common markdown formatting
        clean = _re.sub(r"^#{1,6}\s+", "", line.strip())        # headers
        clean = _re.sub(r"^\s*[-*+]\s+", "- ", clean)            # list markers
        clean = _re.sub(r"\*\*(.+?)\*\*", r"\1", clean)          # bold
        clean = _re.sub(r"\*(.+?)\*", r"\1", clean)              # italic
        clean = _re.sub(r"`{1,3}(.+?)`{1,3}", r"\1", clean)     # inline code & code blocks
        clean = _re.sub(r"\[(.+?)\]\(.+?\)", r"\1", clean)       # links
        clean = _re.sub(r"!\[.*?\]\(.+?\)", "", clean)           # images
        clean = _re.sub(r"^\|.*\|$", "", clean)                  # table rows
        clean = _re.sub(r"^>\s+", "", clean)                     # blockquotes
        clean = _re.sub(r"^---+\s*$", "", clean)                 # horizontal rules
        clean = clean.strip()
        if clean:
            try:
                pdf.multi_cell(0, 6, clean)
            except Exception:
                pass


def main():
    font = find_cjk_font()
    if not font:
        print("ERROR: No CJK font found! Tried:")
        for f in CJK_FONT_CANDIDATES:
            print(f"  {f}")
        sys.exit(1)

    print(f"Using font: {font}")

    md_files = sorted(OUTPUT_DIR.rglob("summary.md"))
    if not md_files:
        print("No summary.md files found!")
        sys.exit(1)

    print(f"Converting {len(md_files)} files...\n")

    ok = 0
    for md_path in md_files:
        pdf_path = md_path.with_suffix(".pdf")
        rel = md_path.relative_to(OUTPUT_DIR)

        try:
            pdf = build_pdf(md_path, font)
            pdf.output(str(pdf_path))
            size_kb = pdf_path.stat().st_size / 1024
            print(f"  [OK] {rel} -> {pdf_path.name} ({size_kb:.0f} KB)")
            ok += 1
        except Exception as exc:
            print(f"  [ERR] {rel}: {exc}")

    print(f"\nDone! {ok}/{len(md_files)} converted.")


if __name__ == "__main__":
    main()
