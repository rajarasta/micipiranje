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
        with pd.ExcelFile(target, engine=engine) as xf:
            sheets = list(xf.sheet_names)
            active = sheet if sheet is not None else sheets[0]
            if active not in sheets:
                raise ValueError(f"sheet {active!r} not found, available: {sheets}")
            df = xf.parse(active)
        return df, {"type": kind, "sheets": sheets, "active_sheet": active, "encoding": None}
    if ext == ".csv":
        for enc in _CSV_ENCODINGS:
            try:
                df = pd.read_csv(target, encoding=enc)
                return df, {"type": "csv", "sheets": None, "active_sheet": None, "encoding": enc}
            except UnicodeDecodeError:
                pass
        # pragma: no cover — latin-1 maps all 256 byte values, so the loop above
        # always returns; this raise exists only to satisfy the type checker.
        raise UnicodeDecodeError(
            "csv", b"", 0, 1, f"could not decode {target} with any of {_CSV_ENCODINGS}"
        )
    raise ValueError(f"unsupported file type {ext!r}, expected .xlsx/.xls/.csv")


def _to_tsv(df: pd.DataFrame, header_lines: list[str], max_chars: int = 50000) -> str:
    """Render a DataFrame as TSV with optional `# ...` metadata lines on top.

    NaN/None → empty string. Cells with tab/newline/carriage-return are escaped.
    Rows are truncated at the row boundary if the total would exceed max_chars,
    and a `# truncated, N more rows omitted` line is appended.
    """
    def fmt(v):
        if pd.isna(v):
            return ""
        s = str(v)
        return s.replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")

    lines = list(header_lines)
    lines.append("\t".join(str(c) for c in df.columns))
    char_count = sum(len(l) + 1 for l in lines)

    truncated = 0
    for i, row in enumerate(df.itertuples(index=False, name=None)):
        line = "\t".join(fmt(v) for v in row)
        if char_count + len(line) + 1 > max_chars:
            truncated = len(df) - i
            break
        lines.append(line)
        char_count += len(line) + 1

    if truncated:
        lines.append(
            f"# truncated, {truncated} more rows omitted — narrow your query or paginate"
        )
    return "\n".join(lines)


def _col_types(df: pd.DataFrame) -> list[str]:
    """Render column descriptors like `name:int`, `name:string`."""
    out = []
    for c in df.columns:
        dt = df[c].dtype
        if pd.api.types.is_integer_dtype(dt):
            t = "int"
        elif pd.api.types.is_float_dtype(dt):
            t = "float"
        elif pd.api.types.is_bool_dtype(dt):
            t = "bool"
        elif pd.api.types.is_datetime64_any_dtype(dt):
            t = "datetime"
        else:
            t = "string"
        out.append(f"{c}:{t}")
    return out


@mcp.tool()
def xlsx_overview(path: str, sheet: str | None = None) -> str:
    """Quick overview of a table: type, sheets, dimensions, columns with types,
    first 5 rows and last 5 rows. Use this first on any unknown file."""
    df, meta = _load_table(path, sheet)
    rows, cols = df.shape
    header = [
        f"# file={path}",
        f"# type={meta['type']}",
    ]
    if meta["sheets"] is not None:
        header.append(f"# sheets={meta['sheets']}")
        header.append(f"# active_sheet={meta['active_sheet']}")
    if meta["encoding"] is not None:
        header.append(f"# encoding={meta['encoding']}")
    header.append(f"# rows={rows} cols={cols}")
    header.append(f"# columns: {', '.join(_col_types(df))}")

    head_block = _to_tsv(df.head(5), header_lines=["# first 5 rows"])
    tail_block = _to_tsv(df.tail(5), header_lines=["# last 5 rows"])
    return "\n".join(header) + "\n\n" + head_block + "\n\n" + tail_block


if __name__ == "__main__":
    # Eagerly verify the env var at startup when running as a server.
    _root()
    mcp.run()
