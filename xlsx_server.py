# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=1.2",
#   "pandas>=2.0",
#   "openpyxl>=3.1",
#   "xlrd>=2.0.1",
#   "rapidfuzz>=3.0",
# ]
# ///
"""LM Studio Excel/CSV inspection MCP server.

Read-only tools to inspect and fuzzy-search xlsx/xls/csv tables inside
LM_MCP_ROOT. See docs/superpowers/specs/2026-04-27-xlsx-mcp-design.md.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("lm-xlsx")


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


import pandas as pd

_CSV_ENCODINGS = ["utf-8", "cp1250", "latin-1"]


def _load_table(path: str, sheet: str | None) -> tuple[pd.DataFrame, dict]:
    """Load an xlsx/xls/csv into a DataFrame plus a metadata dict.

    Metadata: {"type": "xlsx"|"xls"|"csv", "sheets": [...], "active_sheet": str|None,
               "encoding": str|None}.
    """
    target = _safe(path)
    if not target.exists():
        raise FileNotFoundError(str(target))
    ext = target.suffix.lower()
    if ext in (".xlsx", ".xls"):
        kind = "xlsx" if ext == ".xlsx" else "xls"
        engine = "openpyxl" if ext == ".xlsx" else "xlrd"
        xf = pd.ExcelFile(target, engine=engine)
        sheets = list(xf.sheet_names)
        active = sheet if sheet is not None else sheets[0]
        if active not in sheets:
            raise ValueError(f"sheet {active!r} not found, available: {sheets}")
        df = xf.parse(active)
        return df, {"type": kind, "sheets": sheets, "active_sheet": active, "encoding": None}
    if ext == ".csv":
        last_err: Exception | None = None
        for enc in _CSV_ENCODINGS:
            try:
                df = pd.read_csv(target, encoding=enc)
                return df, {"type": "csv", "sheets": None, "active_sheet": None, "encoding": enc}
            except UnicodeDecodeError as e:
                last_err = e
        raise UnicodeDecodeError(  # pragma: no cover (last_err always set if we get here)
            "csv", b"", 0, 1, f"could not decode {target} with any of {_CSV_ENCODINGS}"
        )
    raise ValueError(f"unsupported file type {ext!r}, expected .xlsx/.xls/.csv")


if __name__ == "__main__":
    # Eagerly verify the env var at startup when running as a server.
    _root()
    mcp.run()
