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


def test_simple_text_fixture_lands_in_sandbox(simple_text_pdf, sandbox):
    assert simple_text_pdf == sandbox / "simple-text.pdf"
    assert simple_text_pdf.exists()
    assert simple_text_pdf.read_bytes()[:5] == b"%PDF-"


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
