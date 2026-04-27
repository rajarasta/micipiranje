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


if __name__ == "__main__":
    # Eagerly verify the env var at startup when running as a server.
    _root()
    mcp.run()
