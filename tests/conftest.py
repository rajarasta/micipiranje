import sys
from pathlib import Path

import pandas as pd
import pytest

# Make project root importable so tests can `import xlsx_server`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Set LM_MCP_ROOT to a tmp_path and return it."""
    monkeypatch.setenv("LM_MCP_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def small_xlsx(sandbox):
    """A 2-sheet xlsx with 3 rows in the main sheet."""
    path = sandbox / "small.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({
            "sifra": [1001, 1002, 1003],
            "naziv": ["Vijak M8x40 inox", "Matica M8 inox", "Vijak M10x60 cink"],
            "cijena": [0.45, 0.12, 0.80],
            "jmj": ["kom", "kom", "kom"],
        }).to_excel(writer, sheet_name="Glavni", index=False)
        pd.DataFrame({
            "kategorija": ["Vijci", "Matice"],
            "broj": [120, 35],
        }).to_excel(writer, sheet_name="Sazetak", index=False)
    return path


@pytest.fixture
def small_csv_utf8(sandbox):
    path = sandbox / "small_utf8.csv"
    pd.DataFrame({
        "a": [1, 2, 3],
        "b": ["č", "ć", "đ"],
    }).to_csv(path, index=False, encoding="utf-8")
    return path


@pytest.fixture
def small_csv_cp1250(sandbox):
    path = sandbox / "small_cp1250.csv"
    pd.DataFrame({
        "a": [1, 2, 3],
        "b": ["č", "ć", "đ"],
    }).to_csv(path, index=False, encoding="cp1250")
    return path


@pytest.fixture
def large_xlsx(sandbox):
    """A single-sheet xlsx with 10000 rows for pagination/cap testing."""
    path = sandbox / "large.xlsx"
    pd.DataFrame({
        "id": list(range(10000)),
        "name": [f"Item {i}" for i in range(10000)],
    }).to_excel(path, index=False, engine="openpyxl")
    return path
