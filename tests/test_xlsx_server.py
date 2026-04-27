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
