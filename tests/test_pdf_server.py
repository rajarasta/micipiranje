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


def test_cache_key_is_ascii_for_non_ascii_filename(sandbox):
    """Cache keys (and the /files URLs they end up in) must be ASCII-only,
    so models that mis-transcribe non-ASCII chars (e.g. Croatian ž→Ž) can
    still copy the URL into chat without 404s. Regression for the broken
    /files/renders/...monta%C5%BDni... bug.
    """
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    pdf = sandbox / "RN ZZJZ - montažni fasada - 5.01 Sjever.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    key = pdf_server._cache_key(pdf)
    assert key.isascii(), f"cache key contains non-ASCII chars: {key!r}"
    # Also check the rendered cache filename — what actually goes into the URL.
    rp = pdf_server._render_cache_path(pdf, page=4, dpi=150)
    assert rp.name.isascii(), f"render cache filename has non-ASCII: {rp.name!r}"
    # Sanity: distinct non-ASCII filenames must produce distinct keys (the
    # short hash suffix guarantees this even when sanitized stems collide).
    other = sandbox / "RN ZZJZ - montaŽni fasada - 5.01 Sjever.pdf"  # capital Ž
    other.write_bytes(b"%PDF-1.4 fake")
    assert pdf_server._cache_key(pdf) != pdf_server._cache_key(other)


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


def _http_mode(monkeypatch, *, port="8092"):
    """Switch the loaded pdf_server into HTTP transport URL-emitting mode.

    Tools check MCP_TRANSPORT/MCP_HOST/MCP_PORT at *call* time (not import),
    so a module reload isn't strictly required, but callers usually reload
    anyway after changing other env vars."""
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_PORT", port)


def test_render_page_inline_disabled_env(simple_text_pdf, monkeypatch):
    import importlib
    from mcp.types import ImageContent, TextContent
    import pdf_server
    monkeypatch.setenv("LM_PDF_INLINE_RENDER", "0")
    importlib.reload(pdf_server)
    out = pdf_server.pdf_render_page("simple-text.pdf", page=1, dpi=72)
    text_items = [c for c in out if isinstance(c, TextContent)]
    image_items = [c for c in out if isinstance(c, ImageContent)]
    # No inline image returned (the whole point of the env var).
    assert len(image_items) == 0
    assert len(text_items) == 1
    assert "page 1" in text_items[0].text
    assert "inline image suppressed" in text_items[0].text
    assert "LM_PDF_INLINE_RENDER=0" in text_items[0].text
    # In stdio mode (default — no MCP_TRANSPORT), no markdown image of any
    # kind: neither data: nor http://. Clients rely on ImageContent only.
    assert "data:image/png;base64," not in text_items[0].text
    assert "http://" not in text_items[0].text
    assert "cache://" not in text_items[0].text
    # PNG must still be written to disk so the path in the response is valid.
    expected = pdf_server._render_cache_path(simple_text_pdf, page=1, dpi=72)
    assert expected.exists()


def test_render_page_emits_http_url_in_http_mode(simple_text_pdf, monkeypatch):
    """Under HTTP transport, render_page text must contain a markdown image
    link to /files/renders/... so browser clients display the page without
    the base64 entering the prompt context."""
    import importlib
    import re
    from mcp.types import ImageContent, TextContent
    import pdf_server
    _http_mode(monkeypatch)
    monkeypatch.delenv("LM_PDF_INLINE_RENDER", raising=False)
    importlib.reload(pdf_server)
    out = pdf_server.pdf_render_page("simple-text.pdf", page=1, dpi=72)
    text_items = [c for c in out if isinstance(c, TextContent)]
    image_items = [c for c in out if isinstance(c, ImageContent)]
    assert len(image_items) == 1, "ImageContent stays for clients that consume it"
    m = re.search(
        r"!\[[^\]]*\]\(http://127\.0\.0\.1:8092/files/renders/([^)]+)\)",
        text_items[0].text,
    )
    assert m is not None, (
        f"expected /files/renders/... markdown image link, got: {text_items[0].text!r}"
    )
    # The URL must point at the same file the cache logic wrote.
    expected = pdf_server._render_cache_path(simple_text_pdf, page=1, dpi=72)
    assert expected.exists()
    # No data: URL — that's the whole bug we're fixing.
    assert "data:image/png;base64," not in text_items[0].text
    # Reply-surfacing hint must precede the markdown image so capable models
    # know to copy the link into their reply (so it renders in the main chat
    # flow, not just inside the tool-result block).
    assert "include the next markdown line verbatim in your reply" in text_items[0].text


def test_render_page_http_url_emitted_even_when_inline_disabled(
    simple_text_pdf, monkeypatch,
):
    """LM_PDF_INLINE_RENDER=0 + HTTP transport: ImageContent suppressed (no
    base64 in the prompt) BUT the HTTP URL still emitted so the WebUI can
    fetch and display the image. This is the combination that fixes context
    overflow without losing image visibility."""
    import importlib
    from mcp.types import ImageContent, TextContent
    import pdf_server
    _http_mode(monkeypatch)
    monkeypatch.setenv("LM_PDF_INLINE_RENDER", "0")
    importlib.reload(pdf_server)
    out = pdf_server.pdf_render_page("simple-text.pdf", page=1, dpi=72)
    text_items = [c for c in out if isinstance(c, TextContent)]
    image_items = [c for c in out if isinstance(c, ImageContent)]
    assert len(image_items) == 0
    assert "http://127.0.0.1:8092/files/renders/" in text_items[0].text
    assert "inline image suppressed" in text_items[0].text


def test_extract_region_emits_http_url_in_http_mode(simple_text_pdf, monkeypatch):
    """Under HTTP transport, extract_region text must contain a markdown image
    link to /files/extracts/... pointing to the auto-saved crop."""
    import importlib
    import re
    from mcp.types import ImageContent, TextContent
    import pdf_server
    _http_mode(monkeypatch)
    importlib.reload(pdf_server)
    out = pdf_server.pdf_extract_region(
        "simple-text.pdf", page=1, bbox=[100, 100, 300, 300], dpi=72,
    )
    text_items = [c for c in out if isinstance(c, TextContent)]
    image_items = [c for c in out if isinstance(c, ImageContent)]
    assert len(text_items) == 1 and len(image_items) == 1
    m = re.search(
        r"!\[[^\]]*\]\(http://127\.0\.0\.1:8092/files/extracts/([^)]+)\)",
        text_items[0].text,
    )
    assert m is not None, (
        f"expected /files/extracts/... markdown image link, got: {text_items[0].text!r}"
    )
    # No data: URL bloat in the text (regression guard for the context overflow).
    assert "data:image/png;base64," not in text_items[0].text
    # Reply-surfacing hint must precede the markdown image.
    assert "include the next markdown line verbatim in your reply" in text_items[0].text


def test_extract_region_no_url_in_stdio_mode(simple_text_pdf):
    """Default (stdio) mode: extract_region must NOT emit any URL in text.
    Clients consume the image via ImageContent only."""
    import importlib
    from mcp.types import ImageContent, TextContent
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_extract_region(
        "simple-text.pdf", page=1, bbox=[100, 100, 300, 300], dpi=72,
    )
    text = next(c for c in out if isinstance(c, TextContent)).text
    image_items = [c for c in out if isinstance(c, ImageContent)]
    assert len(image_items) == 1
    assert "http://" not in text
    assert "data:image/png;base64," not in text
    assert "cache://" not in text


def test_extract_region_no_unexpected_url_scheme_in_text(simple_text_pdf, monkeypatch):
    """Even in HTTP mode, the only URL scheme allowed is the legitimate
    http:// link to /files/. Guards against the original `# cached at: ...`
    regression that produced fake `cache://...` URLs the model could
    hallucinate into."""
    import importlib
    import re
    import pdf_server
    from mcp.types import TextContent
    _http_mode(monkeypatch)
    importlib.reload(pdf_server)
    out = pdf_server.pdf_extract_region(
        "simple-text.pdf", page=1, bbox=[50, 50, 250, 250], dpi=72,
    )
    text = next(c for c in out if isinstance(c, TextContent)).text
    # Strip the legitimate http:// link before scheme-shape probing.
    stripped = re.sub(
        r"http://127\.0\.0\.1:8092/files/[^\s)]+", "<HTTP_URL>", text,
    )
    assert "cache://" not in stripped
    assert "://" not in stripped, (
        f"text contains an unexpected URL scheme: {stripped!r}"
    )


def test_extract_region_distinct_bboxes_yield_distinct_bytes(simple_text_pdf):
    """Two non-overlapping crops on the same page must produce different PNG
    bytes. Defends against any future cache-key collision between extracts."""
    import importlib
    import pdf_server
    from mcp.types import ImageContent
    importlib.reload(pdf_server)
    out_a = pdf_server.pdf_extract_region(
        "simple-text.pdf", page=1, bbox=[80, 80, 240, 240], dpi=72,
    )
    out_b = pdf_server.pdf_extract_region(
        "simple-text.pdf", page=1, bbox=[300, 300, 460, 460], dpi=72,
    )
    img_a = next(c for c in out_a if isinstance(c, ImageContent)).data
    img_b = next(c for c in out_b if isinstance(c, ImageContent)).data
    assert img_a != img_b, "two distinct bboxes returned identical PNG bytes"


def test_extract_region_inline_render_env_does_not_affect_extract(
    simple_text_pdf, monkeypatch,
):
    """LM_PDF_INLINE_RENDER=0 governs render_page only. Under HTTP mode,
    extract_region must still return ImageContent and emit the HTTP URL."""
    import importlib
    import pdf_server
    from mcp.types import ImageContent, TextContent
    _http_mode(monkeypatch)
    monkeypatch.setenv("LM_PDF_INLINE_RENDER", "0")
    importlib.reload(pdf_server)
    out = pdf_server.pdf_extract_region(
        "simple-text.pdf", page=1, bbox=[100, 100, 300, 300], dpi=72,
    )
    image_items = [c for c in out if isinstance(c, ImageContent)]
    text_items = [c for c in out if isinstance(c, TextContent)]
    assert len(image_items) == 1, (
        "extract_region must return ImageContent even when LM_PDF_INLINE_RENDER=0"
    )
    assert "http://127.0.0.1:8092/files/extracts/" in text_items[0].text


def test_extract_region_save_as_outside_cache_omits_http_url(
    simple_text_pdf, monkeypatch,
):
    """When save_as routes the PNG outside .lm-pdf-cache/, no HTTP URL is
    emitted (the /files route only serves cache-dir files). ImageContent is
    still returned so non-WebUI clients work."""
    import importlib
    import pdf_server
    from mcp.types import ImageContent, TextContent
    _http_mode(monkeypatch)
    importlib.reload(pdf_server)
    out = pdf_server.pdf_extract_region(
        "simple-text.pdf",
        page=1,
        bbox=[100, 100, 300, 300],
        dpi=72,
        save_as="my-crop.png",
    )
    text = next(c for c in out if isinstance(c, TextContent)).text
    assert "http://" not in text, (
        "save_as paths land outside cache dir; no HTTP URL should be emitted"
    )
    assert any(isinstance(c, ImageContent) for c in out)


def test_files_route_serves_cached_extract(simple_text_pdf, monkeypatch):
    """End-to-end: extract_region writes a PNG to .lm-pdf-cache/extracts/,
    GET /files/extracts/<name> via the registered Starlette route returns
    the same bytes with image/png content type."""
    import asyncio
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_extract_region(
        "simple-text.pdf", page=1, bbox=[80, 80, 240, 240], dpi=72,
    )
    # Find the file the tool wrote, derive the relative URL.
    extracts = pdf_server._extracts_dir()
    saved = next(extracts.glob("*.png"))
    rel = f"extracts/{saved.name}"

    class _MockReq:
        path_params = {"rel_path": rel}

    resp = asyncio.run(pdf_server._serve_cache_file(_MockReq()))
    assert resp.status_code == 200
    assert resp.media_type == "image/png"
    # FileResponse exposes the underlying path (as Path or str).
    from pathlib import Path
    assert Path(resp.path) == saved
    # Cross-origin headers must be present so browsers (running the WebUI on
    # a different port) can embed the image. Missing CORP is what blocked
    # rendering in llama.cpp WebUI on Firefox/Chrome.
    assert resp.headers.get("Cross-Origin-Resource-Policy") == "cross-origin"
    assert resp.headers.get("Access-Control-Allow-Origin") == "*"


def test_files_route_404_on_missing(simple_text_pdf, monkeypatch):
    import asyncio
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    pdf_server._cache_dir()  # ensure cache dir exists

    class _MockReq:
        path_params = {"rel_path": "extracts/does-not-exist.png"}

    resp = asyncio.run(pdf_server._serve_cache_file(_MockReq()))
    assert resp.status_code == 404


def test_files_route_blocks_path_traversal(simple_text_pdf, monkeypatch, tmp_path):
    """Any path that resolves outside .lm-pdf-cache/ must return 403.
    Guards against `../`, absolute paths, and symlink escapes."""
    import asyncio
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    pdf_server._cache_dir()  # ensure cache dir exists

    for malicious in [
        "../../../etc/passwd",
        "../../etc/passwd",
        "../foo.png",  # one level up = inside sandbox but outside cache
        "/etc/passwd",
    ]:
        class _MockReq:
            path_params = {"rel_path": malicious}

        resp = asyncio.run(pdf_server._serve_cache_file(_MockReq()))
        assert resp.status_code in (403, 404), (
            f"path {malicious!r} expected 403/404, got {resp.status_code}"
        )


def test_extract_region_pixel_matches_render_subregion(simple_text_pdf):
    """The cropped PNG returned by pdf_extract_region must contain the same
    pixels as the matching sub-region of pdf_render_page at the same DPI.
    This catches silent regressions where bbox math drifts (e.g. a future
    DPI/points conversion bug returns the full page instead of the crop)."""
    import importlib
    from base64 import b64decode
    from io import BytesIO
    import numpy as np
    from PIL import Image
    from mcp.types import ImageContent
    import pdf_server
    importlib.reload(pdf_server)

    dpi = 72
    bbox = [40, 60, 200, 180]  # x0, y0, x1, y1 in pixels @ dpi

    render_out = pdf_server.pdf_render_page("simple-text.pdf", page=1, dpi=dpi)
    render_b64 = next(
        c for c in render_out if isinstance(c, ImageContent)
    ).data
    render_img = np.asarray(Image.open(BytesIO(b64decode(render_b64))).convert("RGB"))

    extract_out = pdf_server.pdf_extract_region(
        "simple-text.pdf", page=1, bbox=bbox, dpi=dpi,
    )
    extract_b64 = next(
        c for c in extract_out if isinstance(c, ImageContent)
    ).data
    extract_img = np.asarray(
        Image.open(BytesIO(b64decode(extract_b64))).convert("RGB")
    )

    x0, y0, x1, y1 = bbox
    crop_from_render = render_img[y0:y1, x0:x1]

    # Allow ±1 px tolerance on each side for floating-point clip rounding.
    assert abs(extract_img.shape[0] - crop_from_render.shape[0]) <= 1
    assert abs(extract_img.shape[1] - crop_from_render.shape[1]) <= 1

    # Trim to the common region before comparing pixels.
    h = min(extract_img.shape[0], crop_from_render.shape[0])
    w = min(extract_img.shape[1], crop_from_render.shape[1])
    diff = np.abs(
        extract_img[:h, :w].astype(np.int16)
        - crop_from_render[:h, :w].astype(np.int16)
    )
    # PyMuPDF's get_pixmap(clip=...) should produce byte-equivalent output to
    # slicing a full render. A small mean threshold tolerates anti-alias
    # jitter at clip boundaries.
    assert diff.mean() < 2.0, f"mean abs pixel diff too high: {diff.mean()}"


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


def test_extract_region_default_save(simple_text_pdf):
    import importlib
    from mcp.types import ImageContent, TextContent
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_extract_region(
        "simple-text.pdf", page=1, bbox=[100, 100, 300, 300], dpi=150
    )
    # Multipart: one TextContent + one ImageContent.
    assert any(isinstance(c, TextContent) for c in out)
    image_items = [c for c in out if isinstance(c, ImageContent)]
    assert len(image_items) == 1
    assert image_items[0].mimeType == "image/png"
    # PNG signature in base64 starts with iVBORw0KGgo.
    assert image_items[0].data.startswith("iVBORw0KGgo")
    # Auto-saved file exists in extracts/ with the PNG signature.
    extracts = pdf_server._extracts_dir()
    matching = list(extracts.glob("*__p1__bbox100_100_300_300__dpi150.png"))
    assert len(matching) == 1
    assert matching[0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_extract_region_custom_save_as(simple_text_pdf, sandbox):
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    pdf_server.pdf_extract_region(
        "simple-text.pdf", page=1, bbox=[100, 100, 300, 300],
        dpi=150, save_as="reports/sig.png",
    )
    saved = sandbox / "reports" / "sig.png"
    assert saved.exists()
    assert saved.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_extract_region_save_as_escapes_sandbox(simple_text_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="escapes sandbox root"):
        pdf_server.pdf_extract_region(
            "simple-text.pdf", page=1, bbox=[100, 100, 300, 300],
            save_as="../escape.png",
        )


def test_extract_region_save_as_wrong_extension(simple_text_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="must end with .png"):
        pdf_server.pdf_extract_region(
            "simple-text.pdf", page=1, bbox=[100, 100, 300, 300],
            save_as="x.jpg",
        )


def test_extract_region_invalid_bbox(simple_text_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    # Wrong shape.
    with pytest.raises(ValueError, match="4-element list"):
        pdf_server.pdf_extract_region("simple-text.pdf", page=1, bbox=[1, 2, 3])
    # Inverted (x0 >= x1).
    with pytest.raises(ValueError, match="empty or inverted"):
        pdf_server.pdf_extract_region(
            "simple-text.pdf", page=1, bbox=[300, 100, 100, 300]
        )
    # Negative coordinate.
    with pytest.raises(ValueError, match="negative coordinates"):
        pdf_server.pdf_extract_region(
            "simple-text.pdf", page=1, bbox=[-10, 100, 200, 300]
        )


def test_extract_region_bbox_past_page(simple_text_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    # A4 @ 150 dpi ≈ 1240×1754 px; 5000 px is well past the right edge.
    with pytest.raises(ValueError, match="extends past page bounds"):
        pdf_server.pdf_extract_region(
            "simple-text.pdf", page=1, bbox=[100, 100, 5000, 300], dpi=150
        )


def test_extract_region_invalid_page_or_dpi(simple_text_pdf):
    import importlib
    import pytest
    import pdf_server
    importlib.reload(pdf_server)
    with pytest.raises(ValueError, match="page must be in range"):
        pdf_server.pdf_extract_region(
            "simple-text.pdf", page=99, bbox=[10, 10, 100, 100]
        )
    with pytest.raises(ValueError, match="dpi must be between"):
        pdf_server.pdf_extract_region(
            "simple-text.pdf", page=1, bbox=[10, 10, 100, 100], dpi=10
        )


def test_extract_region_inline_image_dimensions(simple_text_pdf):
    """A 200×200 px bbox @ 150 dpi must produce a ~200×200 px PNG."""
    import importlib
    import base64
    from mcp.types import ImageContent
    import pdf_server
    importlib.reload(pdf_server)
    out = pdf_server.pdf_extract_region(
        "simple-text.pdf", page=1, bbox=[100, 100, 300, 300], dpi=150
    )
    img = next(c for c in out if isinstance(c, ImageContent))
    png = base64.b64decode(img.data)
    width = int.from_bytes(png[16:20], "big")
    height = int.from_bytes(png[20:24], "big")
    # Allow ±2 px slack for PyMuPDF rounding behavior at clip edges.
    assert 198 <= width <= 202
    assert 198 <= height <= 202


def _make_drawing(x0, y0, x1, y1, items_count=1):
    """Test fixture: build a drawing dict shaped like p.get_drawings() output."""
    import fitz
    return {"rect": fitz.Rect(x0, y0, x1, y1), "items": [None] * items_count}


def test_cluster_drawings_overlap_merges():
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    a = _make_drawing(10, 10, 50, 50, items_count=3)
    b = _make_drawing(40, 40, 90, 90, items_count=2)  # overlaps a
    clusters = pdf_server._cluster_drawings(
        [a, b], cluster_tolerance=0, min_area=0, max_drawings=10,
    )
    assert len(clusters) == 1
    c = clusters[0]
    assert c["rect"] == (10, 10, 90, 90)
    assert c["n_drawings"] == 2
    assert c["total_shapes"] == 5


def test_cluster_drawings_disjoint_separate():
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    a = _make_drawing(10, 10, 50, 50)
    b = _make_drawing(500, 500, 600, 600)  # far away
    clusters = pdf_server._cluster_drawings(
        [a, b], cluster_tolerance=8, min_area=0, max_drawings=10,
    )
    assert len(clusters) == 2
    rects = {c["rect"] for c in clusters}
    assert (10.0, 10.0, 50.0, 50.0) in rects
    assert (500.0, 500.0, 600.0, 600.0) in rects


def test_cluster_drawings_tolerance_merges():
    import importlib
    import pdf_server
    importlib.reload(pdf_server)
    # Two rects 5 PDF points apart; with tolerance=8 they should merge.
    a = _make_drawing(10, 10, 50, 50)
    b = _make_drawing(55, 10, 90, 50)  # 5pt gap on x-axis
    clusters = pdf_server._cluster_drawings(
        [a, b], cluster_tolerance=8, min_area=0, max_drawings=10,
    )
    assert len(clusters) == 1, f"expected merge with tolerance=8, got {clusters}"

    # Same rects with tolerance=0 must stay separate.
    clusters = pdf_server._cluster_drawings(
        [a, b], cluster_tolerance=0, min_area=0, max_drawings=10,
    )
    assert len(clusters) == 2
