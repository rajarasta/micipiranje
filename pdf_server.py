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

import json
import os
import shutil
import tempfile
from pathlib import Path

import fitz  # PyMuPDF

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


_CACHE_DIR_NAME = ".lm-pdf-cache"
_RENDERS_SUBDIR = "renders"


def _cache_disabled() -> bool:
    return os.environ.get("LM_PDF_NO_CACHE") == "1"


def _cache_dir() -> Path:
    d = _root() / _CACHE_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _renders_dir() -> Path:
    d = _cache_dir() / _RENDERS_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(target: Path) -> str:
    st = target.stat()
    return f"{target.name}__{st.st_size}__{st.st_mtime_ns}"


def _cache_path(target: Path) -> Path:
    return _cache_dir() / f"{_cache_key(target)}.json"


def _render_cache_path(target: Path, page: int, dpi: int) -> Path:
    key = _cache_key(target)
    return _renders_dir() / f"{key}__p{page}__dpi{dpi}.png"


def _read_cache(target: Path) -> dict | None:
    if _cache_disabled():
        return None
    cp = _cache_path(target)
    if not cp.exists():
        return None
    try:
        with cp.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        # Corrupted cache → treat as miss; orchestrator will re-parse and overwrite.
        return None


def _write_cache(target: Path, payload: dict) -> None:
    if _cache_disabled():
        return
    cp = _cache_path(target)
    cp.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=cp.name + ".", dir=str(cp.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, cp)
    except OSError:
        # Disk full or permission — caller still gets the payload in-memory.
        try:
            os.unlink(tmp)
        except OSError:
            pass



def _escape_cell(v) -> str:
    if v is None:
        return ""
    s = str(v)
    return s.replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def _to_tsv(rows: list[list], header_lines: list[str], max_chars: int = 50000) -> str:
    """Render rows as TSV with optional `# ...` metadata lines on top.

    rows[0] is the header row (rendered as-is). Cells are escaped per
    _escape_cell. If the running output would exceed max_chars, truncate at
    the row boundary and append a `# truncated, N more rows omitted` line.
    """
    lines = list(header_lines)
    if rows:
        head, *data = rows
        lines.append("\t".join(_escape_cell(c) for c in head))
        char_count = sum(len(l) + 1 for l in lines)
        truncated = 0
        for i, row in enumerate(data):
            line = "\t".join(_escape_cell(c) for c in row)
            if char_count + len(line) + 1 > max_chars:
                truncated = len(data) - i
                break
            lines.append(line)
            char_count += len(line) + 1
        if truncated:
            lines.append(
                f"# truncated, {truncated} more rows omitted — narrow your query or paginate"
            )
    return "\n".join(lines)


_OCR_MIN_CHARS = 20  # below this, treat page as empty and try OCR


def _has_tesseract() -> bool:
    """True if the tesseract binary is on PATH. Cached per-process."""
    return shutil.which("tesseract") is not None


def _page_text_via_fitz(page) -> str:
    return page.get_text("text") or ""


def _extract_pages_text(pdf_path: Path) -> list[dict]:
    """Extract per-page text. ocr_used is False here; OCR fallback is added in Task 7."""
    out = []
    with fitz.open(pdf_path) as doc:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            text = _page_text_via_fitz(page).strip()
            if len(text) >= _OCR_MIN_CHARS:
                out.append({"page": i + 1, "text": text, "ocr_used": False})
            else:
                # In Task 7 this branch will attempt OCR. For now: empty.
                out.append({"page": i + 1, "text": "", "ocr_used": False})
    return out


if __name__ == "__main__":
    _root()  # eager validation at startup
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        mcp.settings.host = os.environ.get("MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("MCP_PORT", "8092"))
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
