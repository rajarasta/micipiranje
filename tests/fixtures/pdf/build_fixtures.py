# /// script
# requires-python = ">=3.10"
# dependencies = ["pymupdf>=1.24"]
# ///
"""One-shot generator for lm-pdf test fixtures.

Run with: uv run --script tests/fixtures/pdf/build_fixtures.py
Output PDFs are committed to git; regenerate only when the spec changes.
"""

from __future__ import annotations

import io
from pathlib import Path

import fitz  # PyMuPDF

OUT = Path(__file__).parent
DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _save(doc: fitz.Document, name: str) -> None:
    target = OUT / name
    doc.set_metadata({
        "title": name.removesuffix(".pdf"),
        "author": "lm-pdf fixtures",
        "creator": "build_fixtures.py",
        "creationDate": "D:20260101000000Z",
        "modDate": "D:20260101000000Z",
    })
    doc.save(target, deflate=True, garbage=4, no_new_id=True)
    doc.close()
    print(f"wrote {target}")


def build_simple_text() -> None:
    """5 pages of plain English text, born-digital."""
    doc = fitz.open()
    for i in range(1, 6):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 100), f"Page {i} of simple text fixture.", fontsize=14)
        page.insert_text(
            (50, 140),
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit.\n"
            "Sed do eiusmod tempor incididunt ut labore et dolore magna.",
            fontsize=11,
        )
    _save(doc, "simple-text.pdf")


def build_with_toc() -> None:
    """10 pages with a 3-level TOC."""
    doc = fitz.open()
    sections = [
        (1, "1. Predmet ugovora", 1),
        (2, "1.1 Definicije", 2),
        (2, "1.2 Strane", 3),
        (1, "2. Obveze", 4),
        (2, "2.1 Isporuka", 5),
        (3, "2.1.1 Rok isporuke", 6),
        (1, "3. Cijena i placanje", 7),
        (1, "4. Garancija", 8),
        (1, "5. Penali", 9),
        (1, "6. Zavrsne odredbe", 10),
    ]
    for i in range(1, 11):
        page = doc.new_page(width=595, height=842)
        title = next((s[1] for s in sections if s[2] == i), f"Section {i}")
        body = (
            f"This is the body of {title}.\n\n"
            f"Rok isporuke je 30 dana od potpisa ugovora.\n\n"
            f"Detalji vezani uz ovu sekciju nalaze se na stranici {i}."
        )
        page.insert_text((50, 100), title, fontsize=16)
        page.insert_text((50, 140), body, fontsize=11)
    doc.set_toc([list(s) for s in sections])
    _save(doc, "with-toc.pdf")


def build_with_tables() -> None:
    """3 pages, 4 tables drawn as line+text grids."""
    doc = fitz.open()
    # Page 1 — single 4-col 5-row table
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((50, 60), "Tablica 1: cjenik artikala", fontsize=12)
    _draw_table(
        p1,
        x=50, y=80, col_widths=[180, 60, 50, 60], row_height=22,
        rows=[
            ["Stavka", "Kolicina", "JM", "Cijena"],
            ["Vijak M8x40 inox", "500", "kom", "0.45"],
            ["Matica M8 inox", "1000", "kom", "0.12"],
            ["Vijak M10x60 cink", "200", "kom", "0.80"],
            ["Podloska M8", "1500", "kom", "0.05"],
        ],
    )
    # Page 2 — two small tables stacked
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((50, 60), "Tablica 2: troskovi", fontsize=12)
    _draw_table(
        p2,
        x=50, y=80, col_widths=[200, 80], row_height=22,
        rows=[
            ["Stavka", "Iznos"],
            ["Materijal", "1250.00"],
            ["Rad", "850.00"],
        ],
    )
    p2.insert_text((50, 200), "Tablica 3: rokovi", fontsize=12)
    _draw_table(
        p2,
        x=50, y=220, col_widths=[150, 100, 100], row_height=22,
        rows=[
            ["Faza", "Pocetak", "Kraj"],
            ["Priprema", "01.05.2026.", "10.05.2026."],
            ["Izrada", "11.05.2026.", "30.05.2026."],
        ],
    )
    # Page 3 — wide table
    p3 = doc.new_page(width=595, height=842)
    p3.insert_text((50, 60), "Tablica 4: specifikacije", fontsize=12)
    _draw_table(
        p3,
        x=50, y=80, col_widths=[80, 100, 80, 80, 80], row_height=22,
        rows=[
            ["Sifra", "Naziv", "Tezina", "Promjer", "Duljina"],
            ["A001", "Vijak M8", "10g", "8mm", "40mm"],
            ["A002", "Vijak M10", "18g", "10mm", "60mm"],
        ],
    )
    _save(doc, "with-tables.pdf")


def _draw_table(page, x, y, col_widths, row_height, rows):
    n_rows = len(rows)
    n_cols = len(col_widths)
    width = sum(col_widths)
    height = row_height * n_rows
    # Outer rect
    page.draw_rect(fitz.Rect(x, y, x + width, y + height), color=(0, 0, 0), width=0.8)
    # Row separators
    for r in range(1, n_rows):
        ry = y + r * row_height
        page.draw_line(fitz.Point(x, ry), fitz.Point(x + width, ry), width=0.5)
    # Column separators
    cx = x
    for cw in col_widths[:-1]:
        cx += cw
        page.draw_line(fitz.Point(cx, y), fitz.Point(cx, y + height), width=0.5)
    # Cell text
    for r, row in enumerate(rows):
        cy = y + r * row_height + 14
        cx = x + 4
        for c, cell in enumerate(row):
            page.insert_text((cx, cy), str(cell), fontsize=10)
            cx += col_widths[c]


def build_scanned_page() -> None:
    """3 pages, page 2 has no text layer (image-only)."""
    doc = fitz.open()
    # Page 1: text
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((50, 100), "First page with text.", fontsize=14)
    # Page 2: render to PNG, then replace this page with the image only.
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((50, 100), "This page will become an image-only scan.", fontsize=14)
    pix = p2.get_pixmap(dpi=150)
    img_bytes = pix.tobytes("png")
    doc.delete_page(1)
    p2_new = doc.new_page(width=595, height=842, pno=1)
    p2_new.insert_image(fitz.Rect(0, 0, 595, 842), stream=img_bytes)
    # Page 3: text
    p3 = doc.new_page(width=595, height=842)
    p3.insert_text((50, 100), "Third page with text.", fontsize=14)
    _save(doc, "scanned-page.pdf")


def build_croatian() -> None:
    """3 pages with Croatian diacritics. Requires DejaVuSans on the system."""
    if not Path(DEJAVU).exists():
        raise SystemExit(
            f"DejaVuSans font not found at {DEJAVU}. "
            "Install fonts-dejavu or edit DEJAVU constant in build_fixtures.py."
        )
    doc = fitz.open()
    for i, body in enumerate(
        [
            "Šaroliki čokoladni dezert s đumbirom i žemljom.",
            "Naručili smo vijke M8x40 nehrđajući čelik. Rok isporuke je 30 dana.",
            "Zaštita životne sredine i zdravlja zaposlenika je naša briga.",
        ],
        start=1,
    ):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 100), f"Stranica {i}", fontsize=14, fontfile=DEJAVU, fontname="dejavu")
        page.insert_text((50, 140), body, fontsize=11, fontfile=DEJAVU, fontname="dejavu")
    _save(doc, "croatian.pdf")


def build_large() -> None:
    """100-page PDF for pagination/cap testing."""
    doc = fitz.open()
    for i in range(1, 101):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 100), f"Page {i} of 100", fontsize=12)
        page.insert_text((50, 140), f"Identifier-{i:04d}.", fontsize=10)
    _save(doc, "large.pdf")


def build_encrypted() -> None:
    """1-page PDF encrypted with a user password."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100), "Secret content.", fontsize=14)
    target = OUT / "encrypted.pdf"
    doc.save(
        target,
        encryption=fitz.PDF_ENCRYPT_AES_128,
        owner_pw="owner",
        user_pw="user",
        deflate=True,
        garbage=4,
        no_new_id=True,
    )
    doc.close()
    print(f"wrote {target}")


if __name__ == "__main__":
    build_simple_text()
    build_with_toc()
    build_with_tables()
    build_scanned_page()
    build_croatian()
    build_large()
    build_encrypted()
