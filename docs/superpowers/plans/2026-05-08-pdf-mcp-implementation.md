# lm-pdf MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only MCP server that lets a local LLM inspect, search, and visually render PDF documents (contracts, offers, specs) inside the existing `LM_MCP_ROOT` sandbox, with 7 tools backed by PyMuPDF + pdfplumber + rapidfuzz and an optional Tesseract OCR fallback, plus an on-disk cache so the same PDF parses once.

**Architecture:** Single Python file [pdf_server.py](../../../pdf_server.py) at project root, mirroring the structure of [xlsx_server.py](../../../xlsx_server.py). Self-bootstraps via PEP 723 `# /// script` deps when run with `uv run --script`. Supports stdio (LM Studio) and streamable-http (llama.cpp WebUI) transports through `MCP_TRANSPORT` env var. Disk cache lives at `<LM_MCP_ROOT>/.lm-pdf-cache/` with a JSON sidecar per PDF (parsed text, outline, tables) and a `renders/` subdir for rasterized page PNGs.

**Tech Stack:** Python ≥3.10, `mcp>=1.2` (FastMCP), `pymupdf>=1.24`, `pdfplumber>=0.11`, `rapidfuzz>=3.0`, `pytesseract>=0.3.10` (binary optional), pytest for tests.

**Spec:** [docs/superpowers/specs/2026-05-07-pdf-mcp-design.md](../specs/2026-05-07-pdf-mcp-design.md)

---

## File Structure

| File | Status | Responsibility |
| --- | --- | --- |
| `pdf_server.py` | Create | Single-file MCP server. Sandbox + cache + parser + 7 tools. ~700 LOC. |
| `tests/test_pdf_server.py` | Create | All tests (helpers + per-tool happy + edge cases). |
| `tests/fixtures/pdf/build_fixtures.py` | Create | One-shot generator for test PDFs. Run manually, output committed. |
| `tests/fixtures/pdf/*.pdf` | Create | 6 committed fixture PDFs (binary). |
| `tests/conftest.py` | Modify | Add per-fixture-PDF copy fixtures (`simple_text_pdf`, `with_toc_pdf`, etc.) |
| `run_tests.sh` | Modify | Add `--with pymupdf --with pdfplumber --with pytesseract --with Pillow` flags so tests can import `pdf_server`. |
| `start-mcp-http.sh` | Modify | Add `start_one lm-pdf 8092 "$PROJECT_DIR/pdf_server.py"`. |
| `stop-mcp-http.sh` | Modify | Add `stop_server lm-pdf`. |
| `PDF_MCP_README.md` | Create | User-facing README, mirrors `XLSX_MCP_README.md`. |

`~/.lmstudio/mcp.json` is **not** modified by this plan — adding the new `lm-pdf` entry is a one-line manual step the user does when ready, documented in the README.

---

## Task 1: Server skeleton with sandbox helpers and tests for them

**Files:**

- Create: `pdf_server.py`
- Create: `tests/test_pdf_server.py`
- Modify: `run_tests.sh`

- [ ] **Step 1: Update run_tests.sh to install PDF deps for the test runner**

Modify `run_tests.sh` so pytest can `import pdf_server`. Replace its single `exec` line:

```bash
#!/usr/bin/env bash
set -euo pipefail
exec uv run --with pytest --with pandas --with openpyxl --with xlrd --with rapidfuzz --with 'mcp>=1.2' --with 'pymupdf>=1.24' --with 'pdfplumber>=0.11' --with 'pytesseract>=0.3.10' --with Pillow pytest "$@"
```

Note: `Pillow` is added because `pytesseract` requires it at import time even when no OCR is run.

- [ ] **Step 2: Write the failing tests for `_root` and `_safe`**

Create `tests/test_pdf_server.py`:

```python
import pytest


def test_root_raises_when_env_missing(monkeypatch):
    monkeypatch.delenv("LM_MCP_ROOT", raising=False)
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(RuntimeError, match="LM_MCP_ROOT"):
        pdf_server._root()


def test_root_raises_when_not_directory(tmp_path, monkeypatch):
    fake = tmp_path / "nope"
    monkeypatch.setenv("LM_MCP_ROOT", str(fake))
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(RuntimeError, match="not a directory"):
        pdf_server._root()


def test_safe_resolves_relative_path(sandbox):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    (sandbox / "x.pdf").write_bytes(b"%PDF-1.4 fake")
    p = pdf_server._safe("x.pdf")
    assert p == (sandbox / "x.pdf").resolve()


def test_safe_rejects_path_escape(sandbox):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="escapes sandbox root"):
        pdf_server._safe("../etc/passwd")


def test_safe_rejects_absolute_outside(sandbox):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="escapes sandbox root"):
        pdf_server._safe("/etc/passwd")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py -v`
Expected: ImportError (`No module named 'pdf_server'`).

- [ ] **Step 4: Create the server skeleton**

Create `pdf_server.py`:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=1.2",
#   "pymupdf>=1.24",
#   "pdfplumber>=0.11",
#   "rapidfuzz>=3.0",
#   "pytesseract>=0.3.10",
#   "Pillow>=10.0",
# ]
# ///
"""LM Studio PDF inspection MCP server.

Read-only tools to inspect, search and render PDF documents inside
LM_MCP_ROOT. See docs/superpowers/specs/2026-05-07-pdf-mcp-design.md.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("lm-pdf")


def _root() -> Path:
    val = os.environ.get("LM_MCP_ROOT")
    if not val:
        raise RuntimeError("LM_MCP_ROOT environment variable is required")
    p = Path(val).resolve()
    if not p.is_dir():
        raise RuntimeError(f"LM_MCP_ROOT is not a directory: {p}")
    return p


def _safe(path: str) -> Path:
    root = _root()
    p = Path(path)
    target = (p if p.is_absolute() else root / p).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"path escapes sandbox root: {target}")
    return target


if __name__ == "__main__":
    _root()  # eager validation at startup
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        mcp.settings.host = os.environ.get("MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("MCP_PORT", "8092"))
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py -v`
Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py run_tests.sh
git commit -m "feat(pdf): add lm-pdf MCP server skeleton with sandbox helpers"
```

---

## Task 2: Generate and commit fixture PDFs

**Files:**

- Create: `tests/fixtures/pdf/build_fixtures.py`
- Create: `tests/fixtures/pdf/simple-text.pdf`
- Create: `tests/fixtures/pdf/with-toc.pdf`
- Create: `tests/fixtures/pdf/with-tables.pdf`
- Create: `tests/fixtures/pdf/scanned-page.pdf`
- Create: `tests/fixtures/pdf/croatian.pdf`
- Create: `tests/fixtures/pdf/large.pdf`
- Create: `tests/fixtures/pdf/encrypted.pdf`

- [ ] **Step 1: Create the fixture generator script**

Create `tests/fixtures/pdf/build_fixtures.py`:

```python
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
    doc.save(target, deflate=True, garbage=4)
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
        page.insert_text((50, 100), title, fontsize=16)
        body = (
            f"This is the body of {title}.\n\n"
            f"Rok isporuke je 30 dana od potpisa ugovora.\n\n"
            f"Detalji vezani uz ovu sekciju nalaze se na stranici {i}."
        )
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
        page.insert_text((50, 100), f"Stranica {i}", fontsize=14, fontfile=DEJAVU)
        page.insert_text((50, 140), body, fontsize=11, fontfile=DEJAVU)
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
```

- [ ] **Step 2: Run the script to generate fixtures**

Run: `uv run --script tests/fixtures/pdf/build_fixtures.py`
Expected output: 7 lines `wrote tests/fixtures/pdf/<name>.pdf`. If the script complains about missing DejaVu, install with `sudo apt install fonts-dejavu` and rerun.

- [ ] **Step 3: Verify the fixtures exist and have non-zero size**

Run: `ls -la tests/fixtures/pdf/*.pdf`
Expected: 7 PDF files, each non-zero (≥ ~1 KB except `large.pdf` ~50 KB).

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/pdf/build_fixtures.py tests/fixtures/pdf/*.pdf
git commit -m "test(pdf): add fixture PDFs and generator script"
```

---

## Task 3: Conftest fixtures for copying PDFs into sandbox

**Files:**

- Modify: `tests/conftest.py`
- Modify: `tests/test_pdf_server.py` (add a smoke test that uses the fixture)

- [ ] **Step 1: Write a failing test that uses a `simple_text_pdf` fixture**

Append to `tests/test_pdf_server.py`:

```python
def test_simple_text_fixture_lands_in_sandbox(simple_text_pdf, sandbox):
    assert simple_text_pdf == sandbox / "simple-text.pdf"
    assert simple_text_pdf.exists()
    assert simple_text_pdf.read_bytes()[:5] == b"%PDF-"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./run_tests.sh tests/test_pdf_server.py::test_simple_text_fixture_lands_in_sandbox -v`
Expected: ERROR — `fixture 'simple_text_pdf' not found`.

- [ ] **Step 3: Add per-PDF copy fixtures to conftest.py**

Append to `tests/conftest.py`:

```python
import shutil

FIXTURE_PDF_DIR = Path(__file__).parent / "fixtures" / "pdf"


def _copy_pdf(name: str, sandbox: Path) -> Path:
    src = FIXTURE_PDF_DIR / name
    dst = sandbox / name
    shutil.copy(src, dst)
    return dst


@pytest.fixture
def simple_text_pdf(sandbox):
    return _copy_pdf("simple-text.pdf", sandbox)


@pytest.fixture
def with_toc_pdf(sandbox):
    return _copy_pdf("with-toc.pdf", sandbox)


@pytest.fixture
def with_tables_pdf(sandbox):
    return _copy_pdf("with-tables.pdf", sandbox)


@pytest.fixture
def scanned_pdf(sandbox):
    return _copy_pdf("scanned-page.pdf", sandbox)


@pytest.fixture
def croatian_pdf(sandbox):
    return _copy_pdf("croatian.pdf", sandbox)


@pytest.fixture
def large_pdf(sandbox):
    return _copy_pdf("large.pdf", sandbox)


@pytest.fixture
def encrypted_pdf(sandbox):
    return _copy_pdf("encrypted.pdf", sandbox)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./run_tests.sh tests/test_pdf_server.py::test_simple_text_fixture_lands_in_sandbox -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_pdf_server.py
git commit -m "test(pdf): add conftest fixtures that copy PDFs into sandbox"
```

---

## Task 4: Cache infrastructure (paths, key, atomic read/write)

**Files:**

- Modify: `pdf_server.py` (add cache helpers)
- Modify: `tests/test_pdf_server.py` (cache tests)

- [ ] **Step 1: Write failing tests for cache helpers**

Append to `tests/test_pdf_server.py`:

```python
def test_cache_paths_for_pdf(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    json_path = pdf_server._cache_path(simple_text_pdf)
    assert json_path.parent.name == ".lm-pdf-cache"
    assert json_path.suffix == ".json"
    assert "simple-text.pdf" in json_path.name
    # Cache key must include size and mtime_ns
    st = simple_text_pdf.stat()
    assert str(st.st_size) in json_path.name
    assert str(st.st_mtime_ns) in json_path.name


def test_render_cache_path(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    p = pdf_server._render_cache_path(simple_text_pdf, page=3, dpi=150)
    assert p.parent.name == "renders"
    assert p.parent.parent.name == ".lm-pdf-cache"
    assert "p3" in p.name
    assert "dpi150" in p.name
    assert p.suffix == ".png"


def test_cache_read_miss(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    assert pdf_server._read_cache(simple_text_pdf) is None


def test_cache_write_then_read(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    payload = {"version": 1, "pages": [{"page": 1, "text": "hello"}]}
    pdf_server._write_cache(simple_text_pdf, payload)
    got = pdf_server._read_cache(simple_text_pdf)
    assert got == payload


def test_cache_invalidates_when_pdf_changes(simple_text_pdf):
    import importlib
    import os
    import time
    import pdf_server
    importlib.reload(pdf_server)
    pdf_server._write_cache(simple_text_pdf, {"version": 1, "pages": []})
    # Touch the PDF — mtime_ns changes → old cache file no longer matches the key.
    time.sleep(0.01)
    os.utime(simple_text_pdf, None)
    assert pdf_server._read_cache(simple_text_pdf) is None


def test_cache_disabled_via_env(simple_text_pdf, monkeypatch):
    import importlib
    import pdf_server
    monkeypatch.setenv("LM_PDF_NO_CACHE", "1")
    importlib.reload(pdf_server)
    pdf_server._write_cache(simple_text_pdf, {"version": 1, "pages": []})
    # With cache disabled, _read_cache must not return data even if a stale file exists.
    assert pdf_server._read_cache(simple_text_pdf) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k cache`
Expected: 6 ERRORS — `module 'pdf_server' has no attribute '_cache_path'` (etc.).

- [ ] **Step 3: Add cache helpers to pdf_server.py**

Add to `pdf_server.py` after `_safe`:

```python
import json
import tempfile

_CACHE_DIR_NAME = ".lm-pdf-cache"
_RENDERS_SUBDIR = "renders"


def _cache_disabled() -> bool:
    return os.environ.get("LM_PDF_NO_CACHE") == "1"


def _cache_dir() -> Path:
    d = _root() / _CACHE_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _renders_dir() -> Path:
    d = _cache_dir() / _RENDERS_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(target: Path) -> str:
    st = target.stat()
    return f"{target.name}__{st.st_size}__{st.st_mtime_ns}"


def _cache_path(target: Path) -> Path:
    return _cache_dir() / f"{_cache_key(target)}.json"


def _render_cache_path(target: Path, page: int, dpi: int) -> Path:
    key = _cache_key(target)
    return _renders_dir() / f"{key}__p{page}__dpi{dpi}.png"


def _read_cache(target: Path) -> dict | None:
    if _cache_disabled():
        return None
    cp = _cache_path(target)
    if not cp.exists():
        return None
    try:
        with cp.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        # Corrupted cache → treat as miss; orchestrator will re-parse and overwrite.
        return None


def _write_cache(target: Path, payload: dict) -> None:
    if _cache_disabled():
        return
    cp = _cache_path(target)
    cp.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=cp.name + ".", dir=str(cp.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, cp)
    except OSError:
        # Disk full or permission — caller still gets the payload in-memory.
        try:
            os.unlink(tmp)
        except OSError:
            pass
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k cache`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): add cache infrastructure with size+mtime keying"
```

---

## Task 5: Output helpers — TSV with truncation and escaping

**Files:**

- Modify: `pdf_server.py` (add `_to_tsv`, `_escape_cell`)
- Modify: `tests/test_pdf_server.py` (TSV tests)

- [ ] **Step 1: Write failing TSV tests**

Append to `tests/test_pdf_server.py`:

```python
def test_to_tsv_basic():
    import pdf_server
    out = pdf_server._to_tsv(
        rows=[["a", "b"], [1, "x"], [2, "y"]],
        header_lines=["# meta"],
    )
    assert out == "# meta\na\tb\n1\tx\n2\ty"


def test_to_tsv_escapes_tab_newline_cr():
    import pdf_server
    out = pdf_server._to_tsv(
        rows=[["a"], ["with\ttab"], ["with\nnewline"], ["with\rcr"]],
        header_lines=[],
    )
    lines = out.split("\n")
    assert lines == ["a", "with\\ttab", "with\\nnewline", "with\\rcr"]


def test_to_tsv_none_to_empty():
    import pdf_server
    out = pdf_server._to_tsv(rows=[["a", "b"], [1, None], [None, "x"]], header_lines=[])
    assert out == "a\tb\n1\t\n\tx"


def test_to_tsv_truncates_at_row_boundary():
    import pdf_server
    rows = [["a"]] + [[f"row{i}"] for i in range(100)]
    out = pdf_server._to_tsv(rows=rows, header_lines=["# big"], max_chars=40)
    lines = out.split("\n")
    assert lines[-1].startswith("# truncated,")
    assert "more rows omitted" in lines[-1]
    data = [l for l in lines if l.startswith("row")]
    # Each data row is one full token; no partial rows.
    for i, l in enumerate(data):
        assert l == f"row{i}"


def test_to_tsv_no_truncation_under_cap():
    import pdf_server
    out = pdf_server._to_tsv(rows=[["a"], [1], [2]], header_lines=[], max_chars=50000)
    assert "truncated" not in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k to_tsv`
Expected: 5 ERRORS — `module 'pdf_server' has no attribute '_to_tsv'`.

- [ ] **Step 3: Add the helpers to pdf_server.py**

Add to `pdf_server.py` after the cache helpers:

```python
def _escape_cell(v) -> str:
    if v is None:
        return ""
    s = str(v)
    return s.replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def _to_tsv(rows: list[list], header_lines: list[str], max_chars: int = 50000) -> str:
    """Render rows as TSV with optional `# ...` metadata lines on top.

    rows[0] is the header row (rendered as-is). Cells are escaped per
    _escape_cell. If the running output would exceed max_chars, truncate at
    the row boundary and append a `# truncated, N more rows omitted` line.
    """
    lines = list(header_lines)
    if rows:
        head, *data = rows
        lines.append("\t".join(_escape_cell(c) for c in head))
        char_count = sum(len(l) + 1 for l in lines)
        truncated = 0
        for i, row in enumerate(data):
            line = "\t".join(_escape_cell(c) for c in row)
            if char_count + len(line) + 1 > max_chars:
                truncated = len(data) - i
                break
            lines.append(line)
            char_count += len(line) + 1
        if truncated:
            lines.append(
                f"# truncated, {truncated} more rows omitted — narrow your query or paginate"
            )
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k to_tsv`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): add TSV output helper with row-boundary truncation"
```

---

## Task 6: Text extraction (PyMuPDF, no OCR yet)

**Files:**

- Modify: `pdf_server.py`
- Modify: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing tests for text extraction**

Append to `tests/test_pdf_server.py`:

```python
def test_extract_pages_text_simple(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    pages = pdf_server._extract_pages_text(simple_text_pdf)
    assert len(pages) == 5
    assert pages[0]["page"] == 1
    assert "Page 1 of simple text fixture" in pages[0]["text"]
    assert pages[0]["ocr_used"] is False


def test_extract_pages_text_empty_page_marked(scanned_pdf, monkeypatch):
    import importlib
    import pdf_server
    # Force OCR-disabled path so the empty page comes back with text=""
    monkeypatch.setattr("pdf_server._has_tesseract", lambda: False)
    importlib.reload(pdf_server)
    monkeypatch.setattr("pdf_server._has_tesseract", lambda: False)
    pages = pdf_server._extract_pages_text(scanned_pdf)
    assert len(pages) == 3
    # Page 2 is image-only — should have empty text and ocr_used=False.
    assert pages[1]["text"] == ""
    assert pages[1]["ocr_used"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k extract_pages_text`
Expected: 2 ERRORS — `_extract_pages_text` not defined.

- [ ] **Step 3: Add the text extractor to pdf_server.py**

Add to `pdf_server.py`:

```python
import shutil
import fitz  # PyMuPDF

_OCR_MIN_CHARS = 20  # below this, treat page as empty and try OCR


def _has_tesseract() -> bool:
    """True if the tesseract binary is on PATH. Cached per-process."""
    return shutil.which("tesseract") is not None


def _page_text_via_fitz(page) -> str:
    return page.get_text("text") or ""


def _extract_pages_text(pdf_path: Path) -> list[dict]:
    """Extract per-page text. ocr_used is False here; OCR fallback is added in Task 7."""
    out = []
    with fitz.open(pdf_path) as doc:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            text = _page_text_via_fitz(page).strip()
            if len(text) >= _OCR_MIN_CHARS:
                out.append({"page": i + 1, "text": text, "ocr_used": False})
            else:
                # In Task 7 this branch will attempt OCR. For now: empty.
                out.append({"page": i + 1, "text": "", "ocr_used": False})
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k extract_pages_text`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): add per-page text extraction via PyMuPDF"
```

---

## Task 7: OCR fallback for pages without text

**Files:**

- Modify: `pdf_server.py`
- Modify: `tests/test_pdf_server.py`

- [ ] **Step 1: Write a failing test that exercises the OCR path with a mocked tesseract**

Append to `tests/test_pdf_server.py`:

```python
def test_extract_pages_text_ocr_fallback(scanned_pdf, monkeypatch):
    """Pretend tesseract is installed and pytesseract returns canned text."""
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    monkeypatch.setattr("pdf_server._has_tesseract", lambda: True)

    def fake_image_to_string(img, lang=""):
        # Deterministic stub regardless of input image.
        return "OCR EXTRACTED TEXT FROM PAGE"

    import pytesseract
    monkeypatch.setattr(pytesseract, "image_to_string", fake_image_to_string)
    pages = pdf_server._extract_pages_text(scanned_pdf)
    # Pages 1 and 3 already have text; only page 2 (image-only) used OCR.
    assert pages[0]["ocr_used"] is False
    assert pages[2]["ocr_used"] is False
    assert pages[1]["ocr_used"] is True
    assert "OCR EXTRACTED TEXT FROM PAGE" in pages[1]["text"]


def test_extract_pages_text_ocr_unavailable(scanned_pdf, monkeypatch):
    """No tesseract → image-only page returns empty text, no error."""
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    monkeypatch.setattr("pdf_server._has_tesseract", lambda: False)
    pages = pdf_server._extract_pages_text(scanned_pdf)
    assert pages[1]["text"] == ""
    assert pages[1]["ocr_used"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k ocr`
Expected: `test_extract_pages_text_ocr_fallback` FAILS — page 2 has `ocr_used=False` because Task 6's stub returns empty.

- [ ] **Step 3: Wire the OCR fallback into `_extract_pages_text`**

Replace the body of `_extract_pages_text` in `pdf_server.py` with:

```python
def _ocr_page(page, lang: str) -> str:
    import pytesseract
    from PIL import Image
    pix = page.get_pixmap(dpi=200)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    try:
        return pytesseract.image_to_string(img, lang=lang) or ""
    except pytesseract.TesseractError:
        return ""


def _ocr_lang() -> str:
    """Return language string for tesseract.

    Defaults to "hrv+eng". Falls back to "eng" when hrv traineddata is missing.
    Determined per-call to keep the helper stateless and easy to test.
    """
    import pytesseract
    try:
        langs = set(pytesseract.get_languages(config=""))
    except (pytesseract.TesseractError, FileNotFoundError):
        return "eng"
    if "hrv" in langs:
        return "hrv+eng"
    return "eng"


def _extract_pages_text(pdf_path: Path) -> list[dict]:
    """Per-page text. Falls back to Tesseract OCR for pages without a text layer."""
    out = []
    use_ocr = _has_tesseract()
    lang = _ocr_lang() if use_ocr else "eng"
    with fitz.open(pdf_path) as doc:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            text = _page_text_via_fitz(page).strip()
            if len(text) >= _OCR_MIN_CHARS:
                out.append({"page": i + 1, "text": text, "ocr_used": False})
                continue
            if use_ocr:
                ocr_text = _ocr_page(page, lang).strip()
                if ocr_text:
                    out.append({"page": i + 1, "text": ocr_text, "ocr_used": True})
                    continue
            out.append({"page": i + 1, "text": "", "ocr_used": False})
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k ocr`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): add Tesseract OCR fallback for pages without text"
```

---

## Task 8: Tables extraction via pdfplumber

**Files:**

- Modify: `pdf_server.py`
- Modify: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pdf_server.py`:

```python
def test_extract_tables_with_tables(with_tables_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    tables = pdf_server._extract_tables(with_tables_pdf)
    # 4 tables across 3 pages.
    assert len(tables) == 4
    pages = [t["page"] for t in tables]
    assert pages == [1, 2, 2, 3]
    # Table 1 should have header row "Stavka, Kolicina, JM, Cijena".
    first = tables[0]
    assert first["index"] == 0
    assert first["rows"][0] == ["Stavka", "Kolicina", "JM", "Cijena"]
    assert ["Vijak M8x40 inox", "500", "kom", "0.45"] in first["rows"]


def test_extract_tables_no_tables(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    tables = pdf_server._extract_tables(simple_text_pdf)
    assert tables == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k extract_tables`
Expected: 2 ERRORS — `_extract_tables` not defined.

- [ ] **Step 3: Add the table extractor**

Add to `pdf_server.py`:

```python
import pdfplumber


def _extract_tables(pdf_path: Path) -> list[dict]:
    """Walk every page, return tables as a list of dicts.

    Each entry: {"page": int (1-based), "index": int (0-based within the page), "rows": list[list[str]]}.
    Empty cells become "" instead of None; cell strings are .strip()-ed so the
    column headers match what the LLM expects regardless of pdfplumber padding.
    """
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables() or []
            for j, raw in enumerate(tables):
                normalized = [
                    ["" if c is None else str(c).strip() for c in row] for row in raw
                ]
                out.append({"page": i, "index": j, "rows": normalized})
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k extract_tables`
Expected: 2 PASS. If table 1 row count is off by one, pdfplumber may have included a phantom row — adjust the fixture or the assertion to match observed output, but the column ordering and `Vijak M8x40 inox` row must be present.

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): add table extraction via pdfplumber"
```

---

## Task 9: Outline + metadata extraction, and the parse orchestrator with cache

**Files:**

- Modify: `pdf_server.py`
- Modify: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pdf_server.py`:

```python
def test_extract_outline_with_toc(with_toc_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    outline = pdf_server._extract_outline(with_toc_pdf)
    assert len(outline) == 10
    assert outline[0] == {"level": 1, "title": "1. Predmet ugovora", "page": 1}
    assert outline[5] == {"level": 3, "title": "2.1.1 Rok isporuke", "page": 6}


def test_extract_outline_no_toc(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    outline = pdf_server._extract_outline(simple_text_pdf)
    assert outline == []


def test_extract_meta(with_toc_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    meta = pdf_server._extract_meta(with_toc_pdf)
    assert meta["title"] == "with-toc"
    assert meta["page_count"] == 10


def test_get_parsed_caches_after_first_call(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    cache_path = pdf_server._cache_path(simple_text_pdf)
    assert not cache_path.exists()
    parsed = pdf_server._get_parsed(simple_text_pdf)
    assert cache_path.exists()
    # Second call must return identical content from cache (no re-parse).
    parsed2 = pdf_server._get_parsed(simple_text_pdf)
    assert parsed == parsed2
    assert parsed["meta"]["page_count"] == 5
    assert len(parsed["pages"]) == 5
    assert parsed["stats"]["pages_with_text"] == 5


def test_get_parsed_invalidates_when_pdf_changes(simple_text_pdf, with_toc_pdf, sandbox):
    import importlib
    import os
    import shutil
    import time
    import pdf_server
    importlib.reload(pdf_server)
    # First parse: simple-text contents at this path.
    pdf_server._get_parsed(simple_text_pdf)
    # Overwrite file with a different PDF (with-toc has a different size and 10 pages).
    time.sleep(0.01)
    shutil.copy(with_toc_pdf, simple_text_pdf)
    os.utime(simple_text_pdf, None)
    parsed = pdf_server._get_parsed(simple_text_pdf)
    assert parsed["meta"]["page_count"] == 10
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k "outline or meta or get_parsed"`
Expected: 5 ERRORS / FAILs — helpers not defined.

- [ ] **Step 3: Add outline/meta/orchestrator helpers**

Add to `pdf_server.py`:

```python
_PARSE_VERSION = 1


def _extract_outline(pdf_path: Path) -> list[dict]:
    with fitz.open(pdf_path) as doc:
        toc = doc.get_toc(simple=True) or []
    return [{"level": lvl, "title": title, "page": page} for lvl, title, page in toc]


def _extract_meta(pdf_path: Path) -> dict:
    with fitz.open(pdf_path) as doc:
        m = doc.metadata or {}
        return {
            "title": m.get("title") or "",
            "author": m.get("author") or "",
            "creator": m.get("creator") or "",
            "creation_date": m.get("creationDate") or "",
            "page_count": doc.page_count,
        }


def _parse_pdf(pdf_path: Path) -> dict:
    """Run the full parse pipeline and return a structured payload.

    The caller decides whether to also write it to cache via _write_cache.
    """
    pages = _extract_pages_text(pdf_path)
    tables = _extract_tables(pdf_path)
    outline = _extract_outline(pdf_path)
    meta = _extract_meta(pdf_path)
    stats = {
        "pages_with_text": sum(1 for p in pages if p["text"] and not p["ocr_used"]),
        "pages_ocr": sum(1 for p in pages if p["ocr_used"]),
        "pages_empty": sum(1 for p in pages if not p["text"]),
        "tables_count": len(tables),
    }
    st = pdf_path.stat()
    return {
        "version": _PARSE_VERSION,
        "source": pdf_path.name,
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "meta": meta,
        "outline": outline,
        "pages": pages,
        "tables": tables,
        "stats": stats,
    }


def _get_parsed(pdf_path: Path) -> dict:
    """Read cached parse if fresh, otherwise parse-and-cache."""
    cached = _read_cache(pdf_path)
    if cached and cached.get("version") == _PARSE_VERSION:
        return cached
    parsed = _parse_pdf(pdf_path)
    _write_cache(pdf_path, parsed)
    return parsed


def _open_target(path: str) -> Path:
    """Resolve a sandboxed path and validate it points to a readable PDF.

    Raises FileNotFoundError, ValueError("expected .pdf") or ValueError("PDF is encrypted").
    """
    target = _safe(path)
    if not target.exists():
        raise FileNotFoundError(str(target))
    if target.suffix.lower() != ".pdf":
        raise ValueError(f"expected .pdf, got {target.suffix!r}")
    # Detect encryption early — fitz.open succeeds, but doc.is_encrypted is True.
    with fitz.open(target) as doc:
        if doc.is_encrypted:
            raise ValueError("PDF is encrypted; password not supported")
    return target
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k "outline or meta or get_parsed"`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): add outline/meta extraction and cached parse orchestrator"
```

---

## Task 10: `pdf_overview` tool

**Files:**

- Modify: `pdf_server.py`
- Modify: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pdf_server.py`:

```python
def test_overview_with_toc(with_toc_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_overview("with-toc.pdf")
    assert "with-toc.pdf" in out
    assert "page_count=10" in out
    assert "1. Predmet ugovora" in out
    assert "2.1.1 Rok isporuke" in out
    assert "(str. 6)" in out
    assert "no TOC bookmarks" not in out


def test_overview_no_toc(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_overview("simple-text.pdf")
    assert "page_count=5" in out
    assert "no TOC bookmarks" in out


def test_overview_tables_listed(with_tables_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_overview("with-tables.pdf")
    assert "tables_count=4" in out
    # Pages with tables should appear in the listing.
    assert "tables on pages: 1, 2, 3" in out


def test_overview_encrypted_raises(encrypted_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="encrypted"):
        pdf_server.pdf_overview("encrypted.pdf")


def test_overview_missing_file_raises(sandbox):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(FileNotFoundError):
        pdf_server.pdf_overview("nope.pdf")


def test_overview_wrong_extension_raises(sandbox):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    (sandbox / "x.txt").write_text("hi")
    with pytest.raises(ValueError, match="expected .pdf"):
        pdf_server.pdf_overview("x.txt")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k overview`
Expected: 6 ERRORS/FAILs — `pdf_overview` not defined.

- [ ] **Step 3: Implement `pdf_overview`**

Add to `pdf_server.py`:

```python
@mcp.tool()
def pdf_overview(path: str) -> str:
    """First pass over a PDF: file size, page count, metadata, TOC outline,
    text/OCR/empty stats and a list of pages that contain tables. Use this
    before any other pdf_* tool so you know what you are dealing with."""
    target = _open_target(path)
    parsed = _get_parsed(target)
    meta = parsed["meta"]
    stats = parsed["stats"]
    outline = parsed["outline"]
    tables = parsed["tables"]
    size = parsed["size"]

    lines: list[str] = [
        f"# file={target.name}",
        f"# size={size}",
        f"# page_count={meta['page_count']}",
    ]
    for k in ("title", "author", "creator", "creation_date"):
        if meta.get(k):
            lines.append(f"# {k}={meta[k]}")
    lines.append(
        f"# stats: pages_with_text={stats['pages_with_text']} "
        f"pages_ocr={stats['pages_ocr']} pages_empty={stats['pages_empty']}"
    )
    lines.append(f"# tables_count={stats['tables_count']}")
    if tables:
        pages_with_tables = sorted({t["page"] for t in tables})
        lines.append(
            "# tables on pages: " + ", ".join(str(p) for p in pages_with_tables)
        )

    if outline:
        lines.append("")
        lines.append("# outline:")
        for entry in outline:
            indent = "  " * (entry["level"] - 1)
            lines.append(f"{indent}{entry['title']} (str. {entry['page']})")
    else:
        lines.append("# no TOC bookmarks; use pdf_search to locate sections")

    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k overview`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): add pdf_overview tool"
```

---

## Task 11: `pdf_read_pages` tool

**Files:**

- Modify: `pdf_server.py`
- Modify: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pdf_server.py`:

```python
def test_read_pages_basic(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_read_pages("simple-text.pdf", start=1, count=2)
    assert "# page 1 of 5" in out
    assert "# page 2 of 5" in out
    assert "Page 1 of simple text fixture" in out
    assert "# page 3 of 5" not in out


def test_read_pages_default_count_is_3(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_read_pages("simple-text.pdf", start=1)
    assert "# page 3 of 5" in out
    assert "# page 4 of 5" not in out


def test_read_pages_start_past_end(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_read_pages("simple-text.pdf", start=99, count=3)
    assert "start 99 > page_count 5" in out


def test_read_pages_count_clamped(large_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_read_pages("large.pdf", start=1, count=999)
    assert "count clamped to 20" in out
    # 20 pages rendered, no page 21.
    assert "# page 20 of 100" in out
    assert "# page 21 of 100" not in out


def test_read_pages_invalid_args(simple_text_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="page must be"):
        pdf_server.pdf_read_pages("simple-text.pdf", start=0)
    with pytest.raises(ValueError, match="count must be"):
        pdf_server.pdf_read_pages("simple-text.pdf", start=1, count=0)


def test_read_pages_marks_ocr_and_empty(scanned_pdf, monkeypatch):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    monkeypatch.setattr("pdf_server._has_tesseract", lambda: False)
    out = pdf_server.pdf_read_pages("scanned-page.pdf", start=1, count=3)
    # Page 2 is image-only without OCR available → marked (no text).
    assert "# page 2 of 3 (no text)" in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k read_pages`
Expected: 6 ERRORS/FAILs.

- [ ] **Step 3: Implement `pdf_read_pages`**

Add to `pdf_server.py`:

```python
_READ_PAGES_CAP = 20


@mcp.tool()
def pdf_read_pages(path: str, start: int, count: int = 3) -> str:
    """Read text of pages [start, start+count). start is 1-based. count default
    3, hard cap 20. Inline tables are not rendered here — use pdf_extract_tables
    for table content. Pages that were OCR'd are marked with `(OCR)`; pages that
    have no text and no OCR available are marked `(no text)`."""
    if start < 1:
        raise ValueError("page must be >= 1")
    if count <= 0:
        raise ValueError("count must be > 0")
    target = _open_target(path)
    parsed = _get_parsed(target)
    pages = parsed["pages"]
    total = parsed["meta"]["page_count"]

    if start > total:
        return f"# start {start} > page_count {total}, nothing to show"

    clamped = min(count, _READ_PAGES_CAP)
    end_excl = min(start + clamped, total + 1)

    blocks: list[str] = []
    if clamped < count:
        blocks.append(f"# count clamped to {clamped} (cap={_READ_PAGES_CAP})")
    for n in range(start, end_excl):
        p = pages[n - 1]
        suffix = ""
        if p["ocr_used"]:
            suffix = " (OCR)"
        elif not p["text"]:
            suffix = " (no text)"
        blocks.append(f"# page {n} of {total}{suffix}")
        blocks.append("")
        blocks.append(p["text"])
        blocks.append("")
    return "\n".join(blocks).rstrip()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k read_pages`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): add pdf_read_pages tool"
```

---

## Task 12: `pdf_search` tool

**Files:**

- Modify: `pdf_server.py`
- Modify: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pdf_server.py`:

```python
def test_search_exact_finds_paragraph(with_toc_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_search("with-toc.pdf", "Rok isporuke", mode="exact")
    assert "mode=exact" in out
    assert "Rok isporuke" in out
    # Header section column should resolve via TOC.
    assert "score" not in out  # exact mode: no score column
    assert "page" in out


def test_search_fuzzy_returns_score(with_toc_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    # Token-reordered query: rapidfuzz.token_set_ratio is order-insensitive,
    # so "isporuke rok" still matches the "Rok isporuke je 30 dana ..." line
    # with score 100 — the assertion confirms fuzzy mode renders a score column.
    out = pdf_server.pdf_search("with-toc.pdf", "isporuke rok", mode="fuzzy")
    assert "mode=fuzzy" in out
    assert "score" in out
    assert "Rok isporuke" in out


def test_search_no_match(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_search("simple-text.pdf", "thisstringdoesnotexist", mode="exact")
    assert "no matches" in out


def test_search_empty_query_raises(simple_text_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="query cannot be empty"):
        pdf_server.pdf_search("simple-text.pdf", "")


def test_search_invalid_mode_raises(simple_text_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="mode must be"):
        pdf_server.pdf_search("simple-text.pdf", "x", mode="bogus")


def test_search_page_range_filters(with_toc_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_search(
        "with-toc.pdf", "ovu sekciju", mode="exact", page_range=[1, 3]
    )
    # Pages 1..3 should hit, page 6+ must not show up.
    assert "ovu sekciju" in out
    # No row should reference a page outside [1, 3].
    for line in out.splitlines():
        if line.startswith("#") or line.startswith("page") or not line.strip():
            continue
        cols = line.split("\t")
        # Columns: page, section, paragraph (exact mode, no score).
        page_col = cols[0]
        if page_col.isdigit():
            assert 1 <= int(page_col) <= 3


def test_search_page_range_invalid_shape(simple_text_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="2-element list"):
        pdf_server.pdf_search("simple-text.pdf", "x", page_range=[1])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k "search and not find_pages and not page_range_invalid_shape"`
Expected: 6 ERRORS/FAILs (search not defined or paragraph splitter not in place).

- [ ] **Step 3: Implement `pdf_search` and helpers**

Add to `pdf_server.py`:

```python
import re
from rapidfuzz import fuzz

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")
_FUZZY_THRESHOLD = 60
_SEARCH_LIMIT_DEFAULT = 20
_TSV_MAX_CHARS = 50000


def _split_paragraphs(text: str) -> list[str]:
    parts = _PARAGRAPH_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def _section_for_page(outline: list[dict], page: int) -> str:
    """Return the title of the latest TOC entry whose page <= the given page."""
    best = ""
    for entry in outline:
        if entry["page"] <= page:
            best = entry["title"]
        else:
            break
    return best


def _check_page_range(page_range, total: int) -> tuple[int, int]:
    if page_range is None:
        return 1, total
    if not isinstance(page_range, (list, tuple)) or len(page_range) != 2:
        raise ValueError("page_range must be a 2-element list [start, end]")
    s, e = int(page_range[0]), int(page_range[1])
    return max(1, s), min(total, e)


@mcp.tool()
def pdf_search(
    path: str,
    query: str,
    mode: str = "fuzzy",
    limit: int = _SEARCH_LIMIT_DEFAULT,
    page_range: list[int] | None = None,
) -> str:
    """Search PDF text at paragraph granularity.

    mode='exact' is case-insensitive substring; mode='fuzzy' uses
    rapidfuzz.token_set_ratio with score >= 60. page_range=[start, end]
    optionally narrows the search (1-based, inclusive). Returns top `limit`
    paragraphs as TSV with page, section and paragraph columns; fuzzy mode
    prepends a score column."""
    if not query:
        raise ValueError("query cannot be empty")
    if mode not in ("exact", "fuzzy"):
        raise ValueError(f"mode must be 'exact' or 'fuzzy', got {mode!r}")
    target = _open_target(path)
    parsed = _get_parsed(target)
    total = parsed["meta"]["page_count"]
    p_lo, p_hi = _check_page_range(page_range, total)

    candidates: list[tuple[int, str, str, int]] = []  # (page, section, paragraph, score)
    outline = parsed["outline"]
    for p in parsed["pages"]:
        n = p["page"]
        if n < p_lo or n > p_hi:
            continue
        section = _section_for_page(outline, n)
        for para in _split_paragraphs(p["text"]):
            if mode == "exact":
                if query.casefold() in para.casefold():
                    candidates.append((n, section, para, 100))
            else:
                score = int(fuzz.token_set_ratio(query, para))
                if score >= _FUZZY_THRESHOLD:
                    candidates.append((n, section, para, score))

    if mode == "fuzzy":
        candidates.sort(key=lambda r: r[3], reverse=True)
    # exact mode: keep document order

    total_matches = len(candidates)
    top = candidates[:limit]

    range_note = ""
    if page_range is not None:
        range_note = f", page_range=[{p_lo}, {p_hi}]"
    header_lines = [
        f"# search {query!r}, mode={mode}, threshold={_FUZZY_THRESHOLD}{range_note}, "
        f"showing {len(top)} of {total_matches} matches"
    ]
    if total_matches == 0:
        header_lines.append("# no matches")
        return "\n".join(header_lines)

    if mode == "fuzzy":
        rows = [["score", "page", "section", "paragraph"]]
        for page, section, para, score in top:
            rows.append([score, page, section, para])
    else:
        rows = [["page", "section", "paragraph"]]
        for page, section, para, _ in top:
            rows.append([page, section, para])
    return _to_tsv(rows, header_lines, max_chars=_TSV_MAX_CHARS)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k search`
Expected: 7 PASS (the 6 from step 1 plus `test_search_page_range_invalid_shape`).

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): add pdf_search tool with exact and fuzzy modes"
```

---

## Task 13: `pdf_find_pages` tool (aggregate matches by page)

**Files:**

- Modify: `pdf_server.py`
- Modify: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pdf_server.py`:

```python
def test_find_pages_aggregates(with_toc_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_find_pages("with-toc.pdf", "Rok isporuke", mode="exact")
    # All 10 pages contain the same body line, so every page is a hit.
    assert "10 pages" in out
    # Sorted ascending by page.
    lines = [l for l in out.splitlines() if l and not l.startswith("#") and l != "page\thits"]
    pages_seen = []
    for l in lines:
        cols = l.split("\t")
        if cols[0].isdigit():
            pages_seen.append(int(cols[0]))
    assert pages_seen == sorted(pages_seen)


def test_find_pages_no_matches(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_find_pages("simple-text.pdf", "absolutelynothere", mode="exact")
    assert "no pages match query" in out


def test_find_pages_fuzzy_includes_top_score(with_toc_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    # Token-reordered query — fuzzy match guaranteed against "Rok isporuke ...".
    out = pdf_server.pdf_find_pages("with-toc.pdf", "isporuke rok", mode="fuzzy")
    assert "top_score" in out


def test_find_pages_limit_clamped(with_toc_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="query cannot be empty"):
        pdf_server.pdf_find_pages("with-toc.pdf", "")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k find_pages`
Expected: 4 ERRORS — `pdf_find_pages` not defined.

- [ ] **Step 3: Implement `pdf_find_pages`**

Add to `pdf_server.py`:

```python
_FIND_PAGES_LIMIT_CAP = 100


@mcp.tool()
def pdf_find_pages(
    path: str,
    query: str,
    mode: str = "fuzzy",
    limit: int = _SEARCH_LIMIT_DEFAULT,
) -> str:
    """List pages where the query appears, with hit count and (for fuzzy) the
    best score per page. Output is sorted by page ascending so the LLM can
    walk the document front-to-back. Use pdf_render_page after this to look
    at a specific page visually."""
    if not query:
        raise ValueError("query cannot be empty")
    if mode not in ("exact", "fuzzy"):
        raise ValueError(f"mode must be 'exact' or 'fuzzy', got {mode!r}")
    target = _open_target(path)
    parsed = _get_parsed(target)
    outline = parsed["outline"]

    by_page: dict[int, dict] = {}
    total_hits = 0
    for p in parsed["pages"]:
        n = p["page"]
        for para in _split_paragraphs(p["text"]):
            hit, score = False, 0
            if mode == "exact":
                if query.casefold() in para.casefold():
                    hit, score = True, 100
            else:
                score = int(fuzz.token_set_ratio(query, para))
                if score >= _FUZZY_THRESHOLD:
                    hit = True
            if hit:
                total_hits += 1
                bucket = by_page.setdefault(
                    n, {"hits": 0, "top_score": 0, "section": _section_for_page(outline, n)}
                )
                bucket["hits"] += 1
                if score > bucket["top_score"]:
                    bucket["top_score"] = score

    clamped = max(1, min(limit, _FIND_PAGES_LIMIT_CAP))
    sorted_pages = sorted(by_page.items())
    shown = sorted_pages[:clamped]
    truncated = max(0, len(sorted_pages) - clamped)

    header = [
        f"# pages with {query!r}, mode={mode}, threshold={_FUZZY_THRESHOLD}: "
        f"{len(by_page)} pages, {total_hits} total matches"
    ]
    if not by_page:
        header.append("# no pages match query")
        return "\n".join(header)

    if mode == "fuzzy":
        rows = [["page", "section", "hits", "top_score"]]
        for page, info in shown:
            rows.append([page, info["section"], info["hits"], info["top_score"]])
    else:
        rows = [["page", "section", "hits"]]
        for page, info in shown:
            rows.append([page, info["section"], info["hits"]])

    out = _to_tsv(rows, header, max_chars=_TSV_MAX_CHARS)
    if truncated:
        out += f"\n# truncated, {truncated} more pages omitted"
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k find_pages`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): add pdf_find_pages tool aggregating matches by page"
```

---

## Task 14: `pdf_read_section` tool

**Files:**

- Modify: `pdf_server.py`
- Modify: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pdf_server.py`:

```python
def test_read_section_exact_match(with_toc_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_read_section("with-toc.pdf", "2.1.1 Rok isporuke")
    assert "2.1.1 Rok isporuke" in out
    assert "page 6" in out
    # Section spans only page 6 (next entry "3. Cijena i placanje" starts on page 7).
    assert "Section 7" not in out  # text from a later page should not appear


def test_read_section_fuzzy_match(with_toc_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_read_section("with-toc.pdf", "rok isporuke")
    assert "Rok isporuke" in out


def test_read_section_no_match(with_toc_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="not found"):
        pdf_server.pdf_read_section("with-toc.pdf", "Nepoznata sekcija xyz")


def test_read_section_no_toc(simple_text_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="no TOC bookmarks"):
        pdf_server.pdf_read_section("simple-text.pdf", "anything")


def test_read_section_level_filter(with_toc_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    # Only level 1 entries — picks "1. Predmet ugovora", not "1.1 Definicije".
    out = pdf_server.pdf_read_section("with-toc.pdf", "Predmet", level=1)
    assert "1. Predmet ugovora" in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k read_section`
Expected: 5 ERRORS/FAILs.

- [ ] **Step 3: Implement `pdf_read_section`**

Add to `pdf_server.py`:

```python
_HEADING_THRESHOLD = 70


@mcp.tool()
def pdf_read_section(path: str, heading: str, level: int | None = None) -> str:
    """Return the full text of a TOC section by heading. Heading is matched
    fuzzily (rapidfuzz.partial_ratio >= 70) against bookmark titles. Section
    runs from its starting page until the page before the next bookmark of
    the same or higher level. Pass level=N to restrict matching to entries
    at depth N. Errors if the PDF has no TOC bookmarks."""
    target = _open_target(path)
    parsed = _get_parsed(target)
    outline = parsed["outline"]
    if not outline:
        raise ValueError(
            "PDF has no TOC bookmarks; cannot resolve sections — use pdf_search instead"
        )

    pool = [e for e in outline if level is None or e["level"] == level]
    if not pool:
        raise ValueError(
            f"no TOC entries at level={level}; available levels: "
            f"{sorted({e['level'] for e in outline})}"
        )

    scored = sorted(
        (
            (int(fuzz.partial_ratio(heading, e["title"])), idx, e)
            for idx, e in enumerate(pool)
        ),
        key=lambda x: (-x[0], x[1]),
    )
    best_score, _, best_entry = scored[0]
    if best_score < _HEADING_THRESHOLD:
        suggestions = ", ".join(e["title"] for _, _, e in scored[:3])
        raise ValueError(
            f"section {heading!r} not found; nearest TOC entries: {suggestions}"
        )

    other_top: list[str] = []
    if len(scored) > 1 and scored[1][0] == best_score:
        other_top = [e["title"] for _, _, e in scored[1:4] if _ == best_score]

    # Determine end page: page before next entry of same-or-higher level in the FULL outline.
    start_page = best_entry["page"]
    best_level = best_entry["level"]
    full_idx = next(i for i, e in enumerate(outline) if e is best_entry)
    end_page = parsed["meta"]["page_count"]
    for e in outline[full_idx + 1 :]:
        if e["level"] <= best_level:
            end_page = e["page"] - 1
            break

    header = [
        f"# section: {best_entry['title']!r}",
        f"# pages {start_page}–{end_page} of {parsed['meta']['page_count']}",
    ]
    if other_top:
        header.append(
            "# other candidates with same score: "
            + ", ".join(repr(t) for t in other_top)
            + " — pass level= to disambiguate"
        )

    body_blocks: list[str] = []
    for n in range(start_page, end_page + 1):
        p = parsed["pages"][n - 1]
        body_blocks.append(f"## page {n}")
        body_blocks.append(p["text"])
        body_blocks.append("")
    return "\n".join(header + [""] + body_blocks).rstrip()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k read_section`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): add pdf_read_section tool"
```

---

## Task 15: `pdf_extract_tables` tool

**Files:**

- Modify: `pdf_server.py`
- Modify: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pdf_server.py`:

```python
def test_extract_tables_all(with_tables_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_extract_tables("with-tables.pdf")
    assert "4 tables" in out
    assert "## table 0 (page 1" in out
    assert "Vijak M8x40 inox" in out
    assert "## table" in out


def test_extract_tables_page_filter(with_tables_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_extract_tables("with-tables.pdf", page=2)
    # 2 tables on page 2.
    assert "page=2" in out
    assert "Materijal" in out
    assert "Vijak M8x40 inox" not in out  # page 1 content


def test_extract_tables_page_no_tables(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_extract_tables("simple-text.pdf")
    assert "0 tables" in out


def test_extract_tables_invalid_page(with_tables_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="page must be"):
        pdf_server.pdf_extract_tables("with-tables.pdf", page=0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k "extract_tables and pdf_extract_tables"`
Expected: 4 ERRORS — `pdf_extract_tables` not defined as MCP tool yet.

- [ ] **Step 3: Implement `pdf_extract_tables`**

Add to `pdf_server.py`:

```python
_EXTRACT_TABLES_CAP = 20


@mcp.tool()
def pdf_extract_tables(path: str, page: int | None = None) -> str:
    """Extract tables as TSV. page=None returns every table grouped by page;
    page=N returns only tables on that page (1-based). Hard cap 20 tables per
    call — narrow with page= when truncated."""
    target = _open_target(path)
    parsed = _get_parsed(target)
    total = parsed["meta"]["page_count"]
    if page is not None and page < 1:
        raise ValueError("page must be >= 1")
    if page is not None and page > total:
        return f"# page {page} > page_count {total}, nothing to show"

    tables = parsed["tables"]
    if page is not None:
        tables = [t for t in tables if t["page"] == page]

    pages_with = sorted({t["page"] for t in tables})
    if page is not None:
        header = [f"# {len(tables)} tables on page={page} of {total}"]
    else:
        header = [
            f"# {len(tables)} tables in document"
            + (f", on pages: {', '.join(str(p) for p in pages_with)}" if tables else "")
        ]

    if not tables:
        return "\n".join(header)

    capped = tables[:_EXTRACT_TABLES_CAP]
    truncated = len(tables) - len(capped)

    blocks = list(header) + [""]
    for t in capped:
        rows = t["rows"]
        n_rows = len(rows)
        n_cols = len(rows[0]) if rows else 0
        blocks.append(
            f"## table {t['index']} (page {t['page']}, {n_rows} rows × {n_cols} cols)"
        )
        blocks.append(_to_tsv(rows, header_lines=[], max_chars=_TSV_MAX_CHARS))
        blocks.append("")
    if truncated:
        blocks.append(
            f"# truncated, {truncated} more tables omitted — use page= to narrow"
        )
    return "\n".join(blocks).rstrip()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k "pdf_extract_tables"`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): add pdf_extract_tables tool"
```

---

## Task 16: `pdf_render_page` tool with multipart MCP response

**Files:**

- Modify: `pdf_server.py`
- Modify: `tests/test_pdf_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pdf_server.py`:

```python
def test_render_page_returns_text_and_image(simple_text_pdf):
    import importlib
    from mcp.types import ImageContent, TextContent
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_render_page("simple-text.pdf", page=1, dpi=100)
    assert isinstance(out, list)
    text_items = [c for c in out if isinstance(c, TextContent)]
    image_items = [c for c in out if isinstance(c, ImageContent)]
    assert len(text_items) == 1
    assert len(image_items) == 1
    assert "page 1 of 5" in text_items[0].text
    assert image_items[0].mimeType == "image/png"
    # base64 PNG should start with iVBORw0KGgo (the PNG header in base64).
    assert image_items[0].data.startswith("iVBORw0KGgo")


def test_render_page_caches_png(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    pdf_server.pdf_render_page("simple-text.pdf", page=2, dpi=72)
    expected = pdf_server._render_cache_path(simple_text_pdf, page=2, dpi=72)
    assert expected.exists()
    assert expected.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_page_invalid_page(simple_text_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="page must be in range"):
        pdf_server.pdf_render_page("simple-text.pdf", page=99)
    with pytest.raises(ValueError, match="page must be in range"):
        pdf_server.pdf_render_page("simple-text.pdf", page=0)


def test_render_page_invalid_dpi(simple_text_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="dpi must be between"):
        pdf_server.pdf_render_page("simple-text.pdf", page=1, dpi=10)
    with pytest.raises(ValueError, match="dpi must be between"):
        pdf_server.pdf_render_page("simple-text.pdf", page=1, dpi=999)


def test_render_page_no_cache_env(simple_text_pdf, monkeypatch):
    import importlib
    from mcp.types import ImageContent
    import pdf_server
    monkeypatch.setenv("LM_PDF_NO_CACHE", "1")
    importlib.reload(pdf_server)
    out = pdf_server.pdf_render_page("simple-text.pdf", page=1, dpi=72)
    image_items = [c for c in out if isinstance(c, ImageContent)]
    assert len(image_items) == 1
    # No PNG should be written to disk in NO_CACHE mode.
    expected = pdf_server._render_cache_path(simple_text_pdf, page=1, dpi=72)
    assert not expected.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k render_page`
Expected: 5 ERRORS — `pdf_render_page` not defined.

- [ ] **Step 3: Implement `pdf_render_page`**

Add to `pdf_server.py`:

```python
import base64
from mcp.types import ImageContent, TextContent

_DPI_MIN = 72
_DPI_MAX = 300
_DPI_DEFAULT = 150


@mcp.tool()
def pdf_render_page(path: str, page: int, dpi: int = _DPI_DEFAULT) -> list:
    """Render a single PDF page as a PNG and return it inline.

    Returns a multipart MCP response: one TextContent block with metadata
    (page number, DPI, dimensions, cache path) followed by one ImageContent
    block with the base64 PNG (mimeType image/png) so vision-capable clients
    receive the image directly. Single-page only — call again for more pages."""
    target = _open_target(path)
    parsed = _get_parsed(target)
    total = parsed["meta"]["page_count"]
    if not (1 <= page <= total):
        raise ValueError(f"page must be in range [1, {total}]")
    if not (_DPI_MIN <= dpi <= _DPI_MAX):
        raise ValueError(f"dpi must be between {_DPI_MIN} and {_DPI_MAX}")

    cache_disabled = _cache_disabled()
    render_path = _render_cache_path(target, page, dpi)
    png_bytes: bytes | None = None
    cache_note = ""

    if not cache_disabled and render_path.exists():
        png_bytes = render_path.read_bytes()
        cache_note = f"# cached at: {render_path.relative_to(_root())}"
    else:
        with fitz.open(target) as doc:
            pix = doc.load_page(page - 1).get_pixmap(dpi=dpi)
            png_bytes = pix.tobytes("png")
        if cache_disabled:
            cache_note = "# render not cached: LM_PDF_NO_CACHE=1"
        else:
            try:
                render_path.parent.mkdir(parents=True, exist_ok=True)
                render_path.write_bytes(png_bytes)
                cache_note = f"# cached at: {render_path.relative_to(_root())}"
            except OSError as e:
                cache_note = f"# render not cached: {e.strerror or e}"

    # PNG IHDR chunk: width at bytes [16:20], height at [20:24], big-endian.
    width = int.from_bytes(png_bytes[16:20], "big")
    height = int.from_bytes(png_bytes[20:24], "big")
    size_kb = len(png_bytes) // 1024
    text_lines = [
        f"# page {page} of {total}, rendered at {dpi} dpi ({width}×{height} px, {size_kb} KB)",
    ]
    if cache_note:
        text_lines.append(cache_note)

    return [
        TextContent(type="text", text="\n".join(text_lines)),
        ImageContent(
            type="image",
            data=base64.b64encode(png_bytes).decode("ascii"),
            mimeType="image/png",
        ),
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./run_tests.sh tests/test_pdf_server.py -v -k render_page`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_server.py tests/test_pdf_server.py
git commit -m "feat(pdf): add pdf_render_page tool with multipart text+image response"
```

---

## Task 17: HTTP transport scripts

**Files:**

- Modify: `start-mcp-http.sh`
- Modify: `stop-mcp-http.sh`

- [ ] **Step 1: Add lm-pdf to start-mcp-http.sh**

Modify `start-mcp-http.sh` — replace the block that lists per-server starts and the printed endpoint list:

```bash
start_one lm-fs   8089 "$PROJECT_DIR/server.py"
start_one lm-web  8090 "$PROJECT_DIR/web_server.py" \
  LM_WEB_BACKEND=auto SEARXNG_URL=http://127.0.0.1:8080
start_one lm-xlsx 8091 "$PROJECT_DIR/xlsx_server.py"
start_one lm-pdf  8092 "$PROJECT_DIR/pdf_server.py"

echo
echo "All MCP servers started. Endpoints:"
echo "  lm-fs   : http://127.0.0.1:8089/mcp"
echo "  lm-web  : http://127.0.0.1:8090/mcp"
echo "  lm-xlsx : http://127.0.0.1:8091/mcp"
echo "  lm-pdf  : http://127.0.0.1:8092/mcp"
echo
echo "Stop with: ./stop-mcp-http.sh"
```

- [ ] **Step 2: Add lm-pdf to stop-mcp-http.sh**

Modify `stop-mcp-http.sh` — append below the existing `stop_server` calls:

```bash
stop_server lm-fs
stop_server lm-web
stop_server lm-xlsx
stop_server lm-pdf
```

- [ ] **Step 3: Smoke test the HTTP server starts**

Run: `./start-mcp-http.sh && sleep 2 && curl -sf -X POST http://127.0.0.1:8092/mcp -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 500`
Expected: JSON-RPC response listing the seven `pdf_*` tools (or a Streamable HTTP wrapper around it). If you see `pdf_overview`, `pdf_render_page`, the server is running.

Then stop it: `./stop-mcp-http.sh`
Expected: `[lm-pdf] stopped (pid …)`.

- [ ] **Step 4: Commit**

```bash
git add start-mcp-http.sh stop-mcp-http.sh
git commit -m "chore(pdf): wire lm-pdf into HTTP start/stop scripts on port 8092"
```

---

## Task 18: User-facing README

**Files:**

- Create: `PDF_MCP_README.md`

- [ ] **Step 1: Write the README**

Create `PDF_MCP_README.md`:

```markdown
# lm-pdf — PDF inspection MCP for LM Studio and llama.cpp

Read-only MCP server that lets an LLM inspect, search and render PDF documents (contracts, offers, specs) inside the same `LM_MCP_ROOT` sandbox used by `lm-fs` ([server.py](server.py)) and `lm-xlsx` ([xlsx_server.py](xlsx_server.py)).

See the design spec for full details: [docs/superpowers/specs/2026-05-07-pdf-mcp-design.md](docs/superpowers/specs/2026-05-07-pdf-mcp-design.md).

## Tools

| Tool | Purpose |
| --- | --- |
| `pdf_overview(path)` | First pass: page count, metadata, TOC outline, text/OCR/empty stats, table list |
| `pdf_read_pages(path, start, count=3)` | Page text, paginated; hard cap 20 |
| `pdf_read_section(path, heading, level=None)` | Full text of a TOC section by fuzzy heading match |
| `pdf_search(path, query, mode="fuzzy", limit=20, page_range=None)` | Paragraph search; exact or `rapidfuzz.token_set_ratio ≥ 60` |
| `pdf_extract_tables(path, page=None)` | Tables as TSV; per-page or whole-doc |
| `pdf_find_pages(path, query, mode="fuzzy", limit=20)` | Aggregated page list with hit counts (sorted by page) |
| `pdf_render_page(path, page, dpi=150)` | Render a single page as PNG; returns inline image to vision models |

All text output is TSV with `# ...` metadata headers, capped at ~50k characters with a `# truncated` marker. `pdf_render_page` is the only tool that returns multipart content (text + image).

## Install in LM Studio

Add a new entry alongside the existing `lm-fs`, `lm-web` and `lm-xlsx` blocks in `~/.lmstudio/mcp.json`:

```json
{
  "mcpServers": {
    "lm-pdf": {
      "command": "/full/path/to/uv",
      "args": ["run", "--script", "/full/path/to/pdf_server.py"],
      "env": { "LM_MCP_ROOT": "/full/path/to/sandbox" }
    }
  }
}
```

The first run downloads PyMuPDF, pdfplumber, rapidfuzz, pytesseract and Pillow via `uv` (~70 MB).

## Use from llama.cpp WebUI

`lm-pdf` is wired into `start-mcp-http.sh` on port `8092`. After starting:

```text
http://127.0.0.1:8092/mcp
```

## Run tests

```bash
./run_tests.sh tests/test_pdf_server.py -v
```

Fixtures live in `tests/fixtures/pdf/`. Regenerate them with `uv run --script tests/fixtures/pdf/build_fixtures.py` (requires DejaVuSans for `croatian.pdf`).

## Optional: Tesseract OCR

For scanned PDFs, install Tesseract and Croatian language data:

```bash
sudo apt install tesseract-ocr tesseract-ocr-hrv tesseract-ocr-eng
```

Without Tesseract, image-only pages return empty text and are flagged `(no text)` in `pdf_read_pages`. The server still works for born-digital PDFs.

## Supported / not supported

Supported: `.pdf` (born-digital and OCR-fallback for scans), TOC bookmarks, table extraction (heuristic), Croatian text via OCR with `hrv+eng`.

Not supported: encrypted PDFs (raises `ValueError`), fillable form fields, math/equations (use a different parser), individual figure cropping, multi-document operations.
```

- [ ] **Step 2: Commit**

```bash
git add PDF_MCP_README.md
git commit -m "docs(pdf): add user-facing README for lm-pdf MCP server"
```

---

## Task 19: Final integration smoke test

**Files:**

- Modify: `tests/test_pdf_server.py`

- [ ] **Step 1: Add a smoke test that exercises every tool end-to-end on a fresh sandbox**

Append to `tests/test_pdf_server.py`:

```python
def test_smoke_full_pipeline(with_toc_pdf, with_tables_pdf, simple_text_pdf):
    """Run every tool in the order an LLM would: overview → search → find_pages
    → read_section → extract_tables → render_page. The assertion focus is that
    nothing raises and outputs cross-reference each other consistently."""
    import importlib
    from mcp.types import ImageContent, TextContent
    import pdf_server
    importlib.reload(pdf_server)

    overview = pdf_server.pdf_overview("with-toc.pdf")
    assert "page_count=10" in overview

    search_out = pdf_server.pdf_search("with-toc.pdf", "Rok isporuke", mode="exact")
    assert "Rok isporuke" in search_out

    find_out = pdf_server.pdf_find_pages("with-toc.pdf", "Rok isporuke", mode="exact")
    assert "10 pages" in find_out

    section_out = pdf_server.pdf_read_section("with-toc.pdf", "2.1.1 Rok isporuke")
    assert "page 6" in section_out

    tables_out = pdf_server.pdf_extract_tables("with-tables.pdf")
    assert "Vijak M8x40 inox" in tables_out

    render_out = pdf_server.pdf_render_page("simple-text.pdf", page=1, dpi=72)
    assert any(isinstance(c, TextContent) for c in render_out)
    assert any(isinstance(c, ImageContent) for c in render_out)
```

- [ ] **Step 2: Run all tests**

Run: `./run_tests.sh tests/test_pdf_server.py -v`
Expected: every test passes — no XFAIL, no errors. Total ≥ 50 tests.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pdf_server.py
git commit -m "test(pdf): add end-to-end smoke test exercising all 7 tools"
```

---

## Done

When this plan finishes:

1. `pdf_server.py` exists at project root with 7 read-only tools.
2. The full test suite passes: `./run_tests.sh tests/test_pdf_server.py -v`.
3. `start-mcp-http.sh` boots `lm-pdf` on port 8092 alongside the other servers.
4. `PDF_MCP_README.md` documents config and capabilities.
5. The user can manually add the `lm-pdf` block to `~/.lmstudio/mcp.json` (see README) and start using the server in LM Studio.

The seven git commits land in this order: skeleton → fixtures → conftest → cache → tsv → text → ocr → tables → outline+meta → overview → read_pages → search → find_pages → read_section → extract_tables → render_page → http scripts → README → smoke test (19 commits total).
