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
