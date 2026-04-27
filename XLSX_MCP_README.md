# lm-xlsx — Excel/CSV inspection MCP for LM Studio

Read-only MCP server giving an LLM the tools to inspect and fuzzy-search large Excel and CSV tables inside the same `LM_MCP_ROOT` sandbox used by `lm-fs` ([server.py](server.py)).

See the design spec for full details: [docs/superpowers/specs/2026-04-27-xlsx-mcp-design.md](docs/superpowers/specs/2026-04-27-xlsx-mcp-design.md).

## Tools

| Tool | Purpose |
|---|---|
| `xlsx_overview(path, sheet=None)` | First pass: dimensions, sheets, column types, head & tail |
| `xlsx_read_rows(path, start, count=50, sheet=None)` | Paginated row read, hard cap 1000 |
| `xlsx_read_column(path, column, start=0, count=200, sheet=None, unique=False)` | One-column read with optional distinct values, hard cap 2000 |
| `xlsx_search(path, query, columns=None, mode="fuzzy", limit=20, sheet=None)` | Search rows; `exact` (case-insensitive substring) or `fuzzy` (rapidfuzz token_set_ratio, score ≥ 60) |
| `xlsx_match_list(path, candidates, column, limit_per_candidate=5, sheet=None)` | For each candidate string, top N rows from `column` by fuzzy similarity (no threshold — LLM judges from scores) |

All output is TSV with a `# ...` metadata header. Output capped at ~50k characters with a `# truncated` marker.

## Install in LM Studio

Add alongside the existing `lm-fs` entry:

```json
{
  "mcpServers": {
    "lm-fs": {
      "command": "uv",
      "args": ["run", "/full/path/to/server.py"],
      "env": {"LM_MCP_ROOT": "/full/path/to/sandbox"}
    },
    "lm-xlsx": {
      "command": "uv",
      "args": ["run", "/full/path/to/xlsx_server.py"],
      "env": {"LM_MCP_ROOT": "/full/path/to/sandbox"}
    }
  }
}
```

Both servers share the same `LM_MCP_ROOT`. Excel/CSV files the LLM should read must live inside that directory.

## Run tests

```bash
./run_tests.sh tests/test_xlsx_server.py -v
```

Requires `uv` on PATH. Dependencies are pulled in on the fly (`pandas`, `openpyxl`, `xlrd`, `rapidfuzz`, `pytest`, `mcp`).

## Supported formats

- `.xlsx` (via `openpyxl`)
- `.xls` (via `xlrd 2.x` — old Excel only)
- `.csv` (via pandas; encoding probed UTF-8 → cp1250 → latin-1)

## Out of scope

Writing/editing cells, formulas, charts, multi-file joins, pivots, exports. If those become needed, they go into separate tools, not this server.
