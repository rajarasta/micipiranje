# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=1.2",
#   "pymupdf>=1.24",
#   "pdfplumber>=0.11",
#   "rapidfuzz>=3.0",
#   "pytesseract>=0.3.10",
#   "Pillow>=10.0",
# ]
# ///
"""LM Studio PDF inspection MCP server.

Read-only tools to inspect, search and render PDF documents inside
LM_MCP_ROOT. See docs/superpowers/specs/2026-05-07-pdf-mcp-design.md.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("lm-pdf")


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
    _root()  # eager validation at startup
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        mcp.settings.host = os.environ.get("MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("MCP_PORT", "8092"))
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
