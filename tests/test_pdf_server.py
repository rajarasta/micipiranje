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


def test_inspect_layout_text_blocks(simple_text_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_inspect_layout("simple-text.pdf", page=1)
    # At least 1 text block on page 1; the hint must mention the fixture text.
    assert "# layout for page 1 of 5" in out
    assert "regions detected" in out
    text_lines = [l for l in out.splitlines() if "\ttext\t" in l]
    assert len(text_lines) >= 1
    assert any("Page 1 of simple text fixture" in l for l in text_lines)


def test_inspect_layout_drawings(with_tables_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_inspect_layout("with-tables.pdf", page=1)
    # The table on page 1 is drawn with explicit rectangles + lines, so at
    # least one "drawing" type row must appear.
    drawing_lines = [l for l in out.splitlines() if "\tdrawing\t" in l]
    assert len(drawing_lines) >= 1


def test_inspect_layout_image_block(scanned_pdf):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    # scanned-page.pdf has an image-only middle page (page 2).
    out = pdf_server.pdf_inspect_layout("scanned-page.pdf", page=2)
    image_lines = [l for l in out.splitlines() if "\timage\t" in l]
    assert len(image_lines) >= 1


def test_inspect_layout_invalid_page(simple_text_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="page must be in range"):
        pdf_server.pdf_inspect_layout("simple-text.pdf", page=99)
    with pytest.raises(ValueError, match="page must be in range"):
        pdf_server.pdf_inspect_layout("simple-text.pdf", page=0)


def test_inspect_layout_invalid_dpi(simple_text_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="dpi must be between"):
        pdf_server.pdf_inspect_layout("simple-text.pdf", page=1, dpi=10)
    with pytest.raises(ValueError, match="dpi must be between"):
        pdf_server.pdf_inspect_layout("simple-text.pdf", page=1, dpi=999)
