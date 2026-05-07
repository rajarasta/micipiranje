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
