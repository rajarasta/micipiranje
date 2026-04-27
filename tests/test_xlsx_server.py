import pytest


def test_root_raises_when_env_missing(monkeypatch):
    monkeypatch.delenv("LM_MCP_ROOT", raising=False)
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    with pytest.raises(RuntimeError, match="LM_MCP_ROOT"):
        xlsx_server._root()


def test_root_raises_when_not_directory(tmp_path, monkeypatch):
    fake = tmp_path / "nope"
    monkeypatch.setenv("LM_MCP_ROOT", str(fake))
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    with pytest.raises(RuntimeError, match="not a directory"):
        xlsx_server._root()


def test_safe_resolves_relative_path(sandbox):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    (sandbox / "x.txt").write_text("hi")
    p = xlsx_server._safe("x.txt")
    assert p == (sandbox / "x.txt").resolve()


def test_safe_rejects_path_escape(sandbox):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    with pytest.raises(ValueError, match="escapes sandbox root"):
        xlsx_server._safe("../etc/passwd")


def test_safe_rejects_absolute_outside(sandbox):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    with pytest.raises(ValueError, match="escapes sandbox root"):
        xlsx_server._safe("/etc/passwd")


def test_load_xlsx_default_sheet(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    df, meta = xlsx_server._load_table("small.xlsx", sheet=None)
    assert list(df.columns) == ["sifra", "naziv", "cijena", "jmj"]
    assert len(df) == 3
    assert meta["type"] == "xlsx"
    assert meta["sheets"] == ["Glavni", "Sazetak"]
    assert meta["active_sheet"] == "Glavni"
    assert meta["encoding"] is None


def test_load_xlsx_named_sheet(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    df, meta = xlsx_server._load_table("small.xlsx", sheet="Sazetak")
    assert list(df.columns) == ["kategorija", "broj"]
    assert meta["active_sheet"] == "Sazetak"


def test_load_xlsx_unknown_sheet(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    with pytest.raises(ValueError, match="sheet 'Nope' not found"):
        xlsx_server._load_table("small.xlsx", sheet="Nope")


def test_load_csv_utf8(small_csv_utf8):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    df, meta = xlsx_server._load_table("small_utf8.csv", sheet=None)
    assert list(df.columns) == ["a", "b"]
    assert df["b"].tolist() == ["č", "ć", "đ"]
    assert meta["type"] == "csv"
    assert meta["encoding"] == "utf-8"


def test_load_csv_cp1250_fallback(small_csv_cp1250):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    df, meta = xlsx_server._load_table("small_cp1250.csv", sheet=None)
    assert df["b"].tolist() == ["č", "ć", "đ"]
    assert meta["encoding"] == "cp1250"


def test_load_unknown_extension(sandbox):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    (sandbox / "x.txt").write_text("hi")
    with pytest.raises(ValueError, match="unsupported file type"):
        xlsx_server._load_table("x.txt", sheet=None)


def test_load_missing_file(sandbox):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    with pytest.raises(FileNotFoundError):
        xlsx_server._load_table("missing.xlsx", sheet=None)


import pandas as pd


def test_tsv_basic_format():
    import xlsx_server
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    out = xlsx_server._to_tsv(df, header_lines=["# meta"])
    assert out == "# meta\na\tb\n1\tx\n2\ty"


def test_tsv_nan_to_empty():
    import xlsx_server
    df = pd.DataFrame({"a": [1, None], "b": ["x", None]})
    out = xlsx_server._to_tsv(df, header_lines=[])
    lines = out.split("\n")
    assert lines == ["a\tb", "1.0\tx", "\t"]


def test_tsv_escapes_tab_and_newline():
    import xlsx_server
    df = pd.DataFrame({"a": ["with\ttab", "with\nnewline"]})
    out = xlsx_server._to_tsv(df, header_lines=[])
    lines = out.split("\n")
    assert lines == ["a", "with\\ttab", "with\\nnewline"]


def test_tsv_truncates_at_row_boundary():
    import xlsx_server
    df = pd.DataFrame({"a": [f"row{i}" for i in range(100)]})
    out = xlsx_server._to_tsv(df, header_lines=["# big"], max_chars=40)
    lines = out.split("\n")
    # Last line must be the truncation notice; no partial rows.
    assert lines[-1].startswith("# truncated,")
    assert "more rows omitted" in lines[-1]
    # Every data line is one full "rowN" cell.
    data = [l for l in lines if l.startswith("row")]
    assert all(l == f"row{i}" for i, l in enumerate(data))


def test_tsv_no_truncation_when_under_cap():
    import xlsx_server
    df = pd.DataFrame({"a": [1, 2, 3]})
    out = xlsx_server._to_tsv(df, header_lines=[], max_chars=50000)
    assert "truncated" not in out


def test_tsv_datetime_renders_via_str():
    import xlsx_server
    df = pd.DataFrame({"d": [pd.Timestamp("2024-01-15"), pd.NaT]})
    out = xlsx_server._to_tsv(df, header_lines=[])
    lines = out.split("\n")
    # str(Timestamp) gives "2024-01-15 00:00:00"; NaT is NaN-like → empty.
    assert lines == ["d", "2024-01-15 00:00:00", ""]


def test_overview_xlsx(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    out = xlsx_server.xlsx_overview("small.xlsx")
    assert "small.xlsx" in out
    assert "type=xlsx" in out
    assert "sheets=['Glavni', 'Sazetak']" in out
    assert "active_sheet=Glavni" in out
    assert "rows=3" in out
    assert "cols=4" in out
    # Column listing with types
    assert "sifra" in out and "naziv" in out
    # First-rows section header
    assert "# first 5 rows" in out
    assert "# last 5 rows" in out
    # Actual values from the fixture
    assert "Vijak M8x40 inox" in out


def test_overview_csv(small_csv_utf8):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    out = xlsx_server.xlsx_overview("small_utf8.csv")
    assert "type=csv" in out
    assert "encoding=utf-8" in out
    assert "rows=3" in out
    assert "cols=2" in out


def test_overview_named_sheet(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    out = xlsx_server.xlsx_overview("small.xlsx", sheet="Sazetak")
    assert "active_sheet=Sazetak" in out
    assert "kategorija" in out


def test_read_rows_basic(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    out = xlsx_server.xlsx_read_rows("small.xlsx", start=0, count=2)
    assert "rows 0–1 of 3" in out
    assert "Vijak M8x40 inox" in out
    assert "Matica M8 inox" in out
    assert "Vijak M10x60 cink" not in out  # past count


def test_read_rows_offset(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    out = xlsx_server.xlsx_read_rows("small.xlsx", start=2, count=10)
    assert "rows 2–2 of 3" in out
    assert "Vijak M10x60 cink" in out
    assert "Vijak M8x40 inox" not in out


def test_read_rows_start_past_end(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    out = xlsx_server.xlsx_read_rows("small.xlsx", start=99, count=10)
    assert "start 99 >= total 3" in out


def test_read_rows_invalid_count(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    with pytest.raises(ValueError, match="count must be > 0"):
        xlsx_server.xlsx_read_rows("small.xlsx", start=0, count=0)


def test_read_rows_hard_cap(large_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    out = xlsx_server.xlsx_read_rows("large.xlsx", start=0, count=5000)
    # Hard cap is 1000, so the header should announce the clamped range.
    assert "rows 0–999 of 10000" in out
    assert "count clamped to 1000" in out


def test_read_column_by_name(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    out = xlsx_server.xlsx_read_column("small.xlsx", column="naziv")
    assert "column=naziv" in out
    assert "Vijak M8x40 inox" in out
    assert "Matica M8 inox" in out


def test_read_column_by_index(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    out = xlsx_server.xlsx_read_column("small.xlsx", column=1)  # naziv
    assert "column=naziv" in out
    assert "Vijak M8x40 inox" in out


def test_read_column_unknown_name(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    with pytest.raises(ValueError, match="column 'nope' not found"):
        xlsx_server.xlsx_read_column("small.xlsx", column="nope")


def test_read_column_index_out_of_range(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    with pytest.raises(ValueError, match="column index 99 out of range"):
        xlsx_server.xlsx_read_column("small.xlsx", column=99)


def test_read_column_unique_keeps_first_order(sandbox):
    import importlib
    import pandas as pd
    import xlsx_server
    importlib.reload(xlsx_server)
    p = sandbox / "dups.xlsx"
    pd.DataFrame({"x": ["b", "a", "b", "c", "a"]}).to_excel(p, index=False, engine="openpyxl")
    out = xlsx_server.xlsx_read_column("dups.xlsx", column="x", unique=True)
    lines = [l for l in out.split("\n") if l and not l.startswith("#")]
    # First line is the header "x", rest are values.
    values = lines[1:]
    assert values == ["b", "a", "c"]


def test_search_exact_substring(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    out = xlsx_server.xlsx_search("small.xlsx", query="vijak", mode="exact")
    assert "mode=exact" in out
    assert "Vijak M8x40 inox" in out
    assert "Vijak M10x60 cink" in out
    assert "Matica M8 inox" not in out


def test_search_exact_case_insensitive(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    out = xlsx_server.xlsx_search("small.xlsx", query="VIJAK", mode="exact")
    assert "Vijak M8x40 inox" in out


def test_search_fuzzy_finds_reordered_words(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    # Reordered, with synonym/typo style — fuzzy should still hit "Vijak M8x40 inox"
    out = xlsx_server.xlsx_search(
        "small.xlsx", query="M8 inox vijak 40", mode="fuzzy"
    )
    assert "mode=fuzzy" in out
    assert "Vijak M8x40 inox" in out
    # score column present
    lines = [l for l in out.split("\n") if not l.startswith("#")]
    header = lines[0].split("\t")
    assert "score" in header


def test_search_fuzzy_below_threshold_returns_empty(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    out = xlsx_server.xlsx_search(
        "small.xlsx", query="quantum entanglement reactor", mode="fuzzy"
    )
    assert "0 of 0 matches" in out or "no matches" in out


def test_search_empty_query(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    with pytest.raises(ValueError, match="query cannot be empty"):
        xlsx_server.xlsx_search("small.xlsx", query="")


def test_search_specific_columns(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    # "kom" appears in jmj for every row — but if we only search "naziv",
    # we should match nothing.
    out = xlsx_server.xlsx_search(
        "small.xlsx", query="kom", mode="exact", columns=["naziv"]
    )
    assert "0 of 0 matches" in out or "no matches" in out


def test_search_unknown_column(small_xlsx):
    import importlib
    import xlsx_server
    importlib.reload(xlsx_server)
    with pytest.raises(ValueError, match="column 'nope' not found"):
        xlsx_server.xlsx_search("small.xlsx", query="x", columns=["nope"])
