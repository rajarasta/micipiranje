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
from rapidfuzz import fuzz, process

_CSV_ENCODINGS = ["utf-8", "cp1250", "latin-1"]
_FUZZY_THRESHOLD = 60


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


_ROWS_CAP = 1000


@mcp.tool()
def xlsx_read_rows(path: str, start: int, count: int = 50, sheet: str | None = None) -> str:
    """Read a slice of rows [start, start+count). start is 0-based (row 0 = first
    data row after the header). count default 50, hard cap 1000."""
    if count <= 0:
        raise ValueError("count must be > 0")
    df, meta = _load_table(path, sheet)
    total = len(df)
    header = []
    if start >= total:
        header.append(f"# start {start} >= total {total}, nothing to show")
        if meta["active_sheet"]:
            header.append(f"# sheet={meta['active_sheet']}")
        return "\n".join(header)
    clamped = min(count, _ROWS_CAP)
    end = min(start + clamped, total)
    sliced = df.iloc[start:end]
    note = []
    sheet_part = f', sheet "{meta["active_sheet"]}"' if meta["active_sheet"] else ""
    note.append(f"# rows {start}–{end - 1} of {total}{sheet_part}")
    if clamped < count:
        note.append(f"# count clamped to {clamped} (cap={_ROWS_CAP})")
    return _to_tsv(sliced, header_lines=note)


_COLUMN_CAP = 2000


def _resolve_column(df: pd.DataFrame, column) -> str:
    if isinstance(column, int):
        if column < 0 or column >= len(df.columns):
            raise ValueError(
                f"column index {column} out of range, valid: 0..{len(df.columns) - 1}"
            )
        return df.columns[column]
    if column not in df.columns:
        raise ValueError(f"column {column!r} not found, available: {list(df.columns)}")
    return column


@mcp.tool()
def xlsx_read_column(
    path: str,
    column,
    start: int = 0,
    count: int = 200,
    sheet: str | None = None,
    unique: bool = False,
) -> str:
    """Read values of a single column with pagination. `column` is a name or
    0-based index. With unique=True, returns distinct values preserving first-seen
    order. count default 200, hard cap 2000."""
    if count <= 0:
        raise ValueError("count must be > 0")
    df, meta = _load_table(path, sheet)
    col = _resolve_column(df, column)
    series = df[col]
    if unique:
        # drop_duplicates preserves order of first occurrence
        series = series.drop_duplicates()
    total = len(series)
    header = [f"# column={col}"]
    if meta["active_sheet"]:
        header.append(f"# sheet={meta['active_sheet']}")
    if unique:
        header.append("# unique=True")
    if total == 0:
        header.append("# column is empty")
        return "\n".join(header)
    if start >= total:
        header.append(f"# start {start} >= total {total}, nothing to show")
        return "\n".join(header)
    clamped = min(count, _COLUMN_CAP)
    end = min(start + clamped, total)
    sliced = series.iloc[start:end].to_frame()
    header.append(f"# values {start}–{end - 1} of {total}")
    if clamped < count:
        header.append(f"# count clamped to {clamped} (cap={_COLUMN_CAP})")
    return _to_tsv(sliced, header_lines=header)


def _string_columns(df: pd.DataFrame) -> list[str]:
    return [
        c
        for c in df.columns
        if df[c].dtype == "object"
        or pd.api.types.is_string_dtype(df[c])
    ]


def _join_row(row: pd.Series, cols: list[str]) -> str:
    return " ".join("" if pd.isna(row[c]) else str(row[c]) for c in cols)


@mcp.tool()
def xlsx_search(
    path: str,
    query: str,
    columns: list[str] | None = None,
    mode: str = "fuzzy",
    limit: int = 20,
    sheet: str | None = None,
) -> str:
    """Search rows. mode='exact' is case-insensitive substring; mode='fuzzy' uses
    rapidfuzz.token_set_ratio with score >= 60. columns=None searches all
    string columns. Returns top `limit` rows sorted by score desc, with a `score`
    column appended in fuzzy mode."""
    if not query:
        raise ValueError("query cannot be empty")
    if mode not in ("exact", "fuzzy"):
        raise ValueError(f"mode must be 'exact' or 'fuzzy', got {mode!r}")
    df, meta = _load_table(path, sheet)
    if columns is None:
        cols = _string_columns(df)
    else:
        for c in columns:
            if c not in df.columns:
                raise ValueError(f"column {c!r} not found, available: {list(df.columns)}")
        cols = columns
    if not cols:
        return f"# search {query!r}, mode={mode}: no string columns to search"

    joined = df.apply(lambda r: _join_row(r, cols), axis=1)

    if mode == "exact":
        q = query.casefold()
        mask = joined.str.casefold().str.contains(q, regex=False, na=False)
        result = df[mask].head(limit)
        total = int(mask.sum())
        header = [
            f"# search {query!r}, mode=exact, columns={cols}, "
            f"showing {len(result)} of {total} matches"
        ]
        if total == 0:
            header.append("# no matches")
            return "\n".join(header)
        return _to_tsv(result, header_lines=header)

    # fuzzy
    scores = joined.map(lambda s: fuzz.token_set_ratio(query, s))
    matched_idx = scores[scores >= _FUZZY_THRESHOLD].sort_values(ascending=False).index
    total = len(matched_idx)
    top = matched_idx[:limit]
    result = df.loc[top].copy()
    result.insert(0, "score", scores.loc[top].astype(int).values)
    header = [
        f"# search {query!r}, mode=fuzzy, columns={cols}, threshold={_FUZZY_THRESHOLD}, "
        f"showing {len(result)} of {total} matches"
    ]
    if total == 0:
        header.append("# no matches")
        return "\n".join(header)
    return _to_tsv(result, header_lines=header)


@mcp.tool()
def xlsx_match_list(
    path: str,
    candidates: list[str],
    column: str,
    limit_per_candidate: int = 5,
    sheet: str | None = None,
) -> str:
    """For each string in `candidates`, return the top N most-similar rows from
    `column` by rapidfuzz.token_set_ratio. No threshold — top N always returned
    so the LLM can judge from scores. Output is grouped per candidate."""
    if not candidates:
        raise ValueError("candidates cannot be empty")
    if limit_per_candidate <= 0:
        raise ValueError("limit_per_candidate must be > 0")
    df, meta = _load_table(path, sheet)
    if column not in df.columns:
        raise ValueError(f"column {column!r} not found, available: {list(df.columns)}")

    choices = df[column].astype(str).tolist()

    blocks: list[str] = [
        f"# matched {len(candidates)} candidates against column {column!r}, "
        f"top {limit_per_candidate} each"
    ]
    if meta["active_sheet"]:
        blocks.append(f"# sheet={meta['active_sheet']}")
    blocks.append("")

    for cand in candidates:
        matches = process.extract(
            cand, choices, scorer=fuzz.token_set_ratio, limit=limit_per_candidate
        )
        # matches: list of (matched_string, score, index)
        idx = [m[2] for m in matches]
        scores = [int(m[1]) for m in matches]
        rows = df.iloc[idx].copy()
        rows.insert(0, "score", scores)
        # Already sorted by rapidfuzz, but make ordering explicit for stability
        rows = rows.sort_values("score", ascending=False)
        blocks.append(f'## "{cand}"')
        blocks.append(_to_tsv(rows, header_lines=[]))
        blocks.append("")
    return "\n".join(blocks).rstrip()


if __name__ == "__main__":
    # Eagerly verify the env var at startup when running as a server.
    _root()
    mcp.run()
