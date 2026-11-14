"""Build the rules Word document from RULES.md (no Word needed): RULES.md is the source; run this after editing it.

    python build_rules_doc.py        writes Classification_Rules_<today>.docx next to this file

Layout: a title block, numbered section headings with a rule under them, bullets with bold lead-ins, styled tables
(dark header row, banded rows; two-column "label | text" tables without a header), shaded boxes for samples, and a
running header and page numbers."""
import re
from datetime import date as today
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

HERE = Path(__file__).parent
date = f"{today.today():%d %B %Y}".lstrip("0")
src, out = HERE / "RULES.md", HERE / f"Classification_Rules_{today.today():%Y-%m-%d}.docx"
lines = src.read_text(encoding="utf-8").splitlines()

NAVY, TEAL = RGBColor(0x1F, 0x3A, 0x5F), RGBColor(0x2E, 0x6F, 0x8E)
GREY, TEXT = RGBColor(0x6B, 0x72, 0x80), RGBColor(0x22, 0x26, 0x2E)
HEADER_FILL, BAND_FILL, LABEL_FILL, BORDER = "1F3A5F", "F3F6FA", "EAF0F7", "C9D3E0"
PAGE_WIDTH = 7.0  # inches of text width (8.5 - 2 x 0.75)

doc = Document()
section = doc.sections[0]
section.left_margin = section.right_margin = Inches(0.75)
section.top_margin, section.bottom_margin = Inches(0.8), Inches(0.7)

normal = doc.styles["Normal"]
normal.font.name, normal.font.size, normal.font.color.rgb = "Calibri", Pt(10.5), TEXT
normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
normal.paragraph_format.space_after, normal.paragraph_format.line_spacing = Pt(5), 1.12
for name, size, color, before, after in (("Heading 1", 15, NAVY, 18, 6), ("Heading 2", 12, TEAL, 12, 4)):
    style = doc.styles[name]
    style.font.name, style.font.size, style.font.color.rgb, style.font.bold = "Calibri", Pt(size), color, True
    style.element.rPr.rFonts.set(qn("w:asciiTheme"), "")  # don't let the theme font override Calibri
    style.paragraph_format.space_before, style.paragraph_format.space_after = Pt(before), Pt(after)
    style.paragraph_format.keep_with_next = True
bullets = doc.styles["List Bullet"]
bullets.paragraph_format.space_after, bullets.paragraph_format.left_indent = Pt(3), Inches(0.25)


def shade(element, fill):
    """Background colour for a paragraph or a table cell."""
    props = element.get_or_add_pPr() if element.tag.endswith("}p") else element.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), fill)
    props.append(shd)


def border_below(paragraph, color="C9D3E0", size=6):
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for key, value in (("val", "single"), ("sz", str(size)), ("space", "4"), ("color", color)):
        bottom.set(qn(f"w:{key}"), value)
    borders.append(bottom)
    paragraph._p.get_or_add_pPr().append(borders)


def table_borders(table):
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        for key, value in (("val", "single"), ("sz", "4"), ("space", "0"), ("color", BORDER)):
            e.set(qn(f"w:{key}"), value)
        borders.append(e)
    table._tbl.tblPr.append(borders)


def cell_margins(table, top=50, bottom=50, side=90):
    margins = OxmlElement("w:tblCellMar")
    for edge, value in (("top", top), ("bottom", bottom), ("left", side), ("right", side)):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:w"), str(value)); e.set(qn("w:type"), "dxa")
        margins.append(e)
    table._tbl.tblPr.append(margins)


INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)")


def add_text(paragraph, text, size=None, color=None, bold=False):
    """Markdown bold, italic and code inside a line."""
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**"):
            run = paragraph.add_run(part[2:-2]); run.bold = True
        elif part.startswith("`"):
            run = paragraph.add_run(part[1:-1]); run.font.name = "Consolas"
        elif part.startswith("*"):
            run = paragraph.add_run(part[1:-1]); run.italic = True
        else:
            run = paragraph.add_run(part); run.bold = bold or None
        if size:
            run.font.size = Pt(size)
        if color is not None:
            run.font.color.rgb = color


def page_number_field(paragraph):
    for text, instr in (("Page ", None), (None, "PAGE"), (" of ", None), (None, "NUMPAGES")):
        if text:
            run = paragraph.add_run(text)
        else:
            run = paragraph.add_run()
            for kind, value in (("begin", None), ("instr", instr), ("end", None)):
                if kind == "instr":
                    t = OxmlElement("w:instrText"); t.set(qn("xml:space"), "preserve"); t.text = value
                    run._r.append(t)
                else:
                    f = OxmlElement("w:fldChar"); f.set(qn("w:fldCharType"), kind); run._r.append(f)
        run.font.size, run.font.color.rgb = Pt(8.5), GREY


def cells(row):
    return [c.strip() for c in row.strip().strip("|").split("|")]


def column_widths(rows, key_value):
    if key_value:
        return [1.55, PAGE_WIDTH - 1.55]
    longest = [max(len(r[c]) if c < len(r) else 0 for r in rows) for c in range(len(rows[0]))]
    # longer columns get more room, but not in proportion; very short ones (a "#" column) stay narrow
    weights = [max(n, 3) ** 0.6 if n <= 4 else max(n, 20) ** 0.6 for n in longest]
    return [PAGE_WIDTH * w / sum(weights) for w in weights]


def add_table(rows):
    key_value = all(not c for c in rows[0])  # "| | |" header: a label column and a text column, no header row
    body = rows[1:] if key_value else rows
    table = doc.add_table(rows=len(body), cols=len(rows[0]))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table_borders(table); cell_margins(table)
    widths = column_widths(body, key_value)
    layout = OxmlElement("w:tblLayout"); layout.set(qn("w:type"), "fixed")  # Word keeps these widths
    table._tbl.tblPr.append(layout)
    grid = table._tbl.tblGrid
    for col, width in zip(grid.findall(qn("w:gridCol")), widths):
        col.set(qn("w:w"), str(int(width * 1440)))
    for c, width in enumerate(widths):
        table.columns[c].width = Inches(width)
    for r, row in enumerate(body):
        for c in range(len(rows[0])):
            cell = table.cell(r, c)
            cell.width = Inches(widths[c])
            text = row[c] if c < len(row) else ""
            p = cell.paragraphs[0]
            p.paragraph_format.space_after, p.paragraph_format.line_spacing = Pt(0), 1.05
            header = r == 0 and not key_value
            if header:
                add_text(p, text.replace("**", ""), size=9.5, color=RGBColor(0xFF, 0xFF, 0xFF), bold=True)
                shade(cell._tc, HEADER_FILL)
            elif key_value and c == 0:
                add_text(p, text.replace("**", ""), size=9.5, color=NAVY, bold=True)
                shade(cell._tc, LABEL_FILL)
            else:
                add_text(p, text, size=9.5)
                if not key_value and r % 2 == 0:
                    shade(cell._tc, BAND_FILL)
    if not key_value:  # the header row repeats on every page
        tr_pr = table.rows[0]._tr.get_or_add_trPr()
        repeat = OxmlElement("w:tblHeader"); repeat.set(qn("w:val"), "true"); tr_pr.append(repeat)
    spacer = doc.add_paragraph(); spacer.paragraph_format.space_after = Pt(4)


def add_code(block):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.1)
    p.paragraph_format.space_before, p.paragraph_format.space_after, p.paragraph_format.line_spacing = Pt(2), Pt(8), 1.0
    run = p.add_run("\n".join(block))
    run.font.name, run.font.size, run.font.color.rgb = "Consolas", Pt(8.5), TEXT
    shade(p._p, "F2F4F7")


def main():
    """Read RULES.md and write the dated Word document next to it."""
    # running header and page numbers
    header = section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    add_text(header, f"Industry Classification Rules  |  {date}", size=8.5, color=GREY)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    page_number_field(footer)

    i, para = 0, []


    def flush():
        nonlocal para
        if para:
            add_text(doc.add_paragraph(), " ".join(para))
            para = []


    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush(); i += 1
            block = []
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i]); i += 1
            add_code(block); i += 1
            continue
        if line.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"^\|\s*-", lines[i]):
                    rows.append(cells(lines[i]))
                i += 1
            add_table(rows)
            continue
        if line.startswith("# "):
            flush()
            title = doc.add_paragraph()
            title.paragraph_format.space_after = Pt(2)
            add_text(title, line[2:].strip(), size=24, color=NAVY, bold=True)
            sub = doc.add_paragraph()
            add_text(sub, f"As of {date}", size=10.5, color=GREY)
            border_below(sub, color="1F3A5F", size=12)
            sub.paragraph_format.space_after = Pt(12)
        elif line.startswith("## "):
            flush()
            h = doc.add_heading(line[3:].strip(), level=1)
            border_below(h)
        elif line.startswith("### "):
            flush(); doc.add_heading(line[4:].strip(), level=2)
        elif not line.strip() or line.strip() == "---":
            flush()
        elif line.lstrip().startswith("- "):
            flush()
            add_text(doc.add_paragraph(style="List Bullet"), line.lstrip()[2:])
        else:
            para.append(line.strip())
        i += 1
    flush()
    doc.save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
