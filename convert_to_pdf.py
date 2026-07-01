"""
Convert all generated summary.md files to PDF.

Uses markdown → HTML → PDF pipeline with fpdf2 (pure Python, no native deps).
"""
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


def build_pdf(md_path: Path, font_path: str) -> FPDF:
    """Convert a markdown file to a styled FPDF object."""
    md_text = md_path.read_text(encoding="utf-8")

    # Markdown → HTML
    html_body = markdown(
        md_text,
        extensions=["tables", "fenced_code", "codehilite"],
    )

    # Wrap in clean HTML for fpdf2's write_html
    html_full = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body>
{html_body}
</body>
</html>"""

    pdf = FPDF()
    pdf.add_page()

    # Register CJK font
    is_cjk = "C:/Windows/Fonts" in font_path
    if is_cjk:
        pdf.add_font("CJK", "", font_path, uni=True)
        pdf.add_font("CJK", "B", font_path, uni=True)  # same file for bold
        font_name = "CJK"
    else:
        pdf.add_font("Custom", "", font_path, uni=True)
        pdf.add_font("Custom", "B", font_path, uni=True)
        font_name = "Custom"

    try:
        pdf.write_html(html_full, font_family=font_name)
    except Exception as exc:
        # If write_html fails (e.g. due to font issues), fall back to plain text
        pdf.set_font(font_name, "", 10)
        for line in md_text.split("\n"):
            # Skip markdown formatting, just write text
            clean = line.strip()
            if clean and not clean.startswith("#") and not clean.startswith("|") and not clean.startswith(">"):
                try:
                    pdf.multi_cell(0, 6, clean)
                except Exception:
                    pass

    return pdf


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
