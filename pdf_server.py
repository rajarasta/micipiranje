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
import pdfplumber

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


def _extract_tables(pdf_path: Path) -> list[dict]:
    """Walk every page, return tables as a list of dicts.

    Each entry: {"page": int (1-based), "index": int (0-based within the page), "rows": list[list[str]]}.
    Empty cells become "" instead of None; cell strings are .strip()-ed so the
    column headers match what the LLM expects regardless of pdfplumber padding.
    """
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables() or []
            for j, raw in enumerate(tables):
                normalized = [
                    ["" if c is None else str(c).strip() for c in row] for row in raw
                ]
                out.append({"page": i, "index": j, "rows": normalized})
    return out


_OCR_MIN_CHARS = 20  # below this, treat page as empty and try OCR


def _has_tesseract() -> bool:
    """True if the tesseract binary is on PATH. Cached per-process."""
    return shutil.which("tesseract") is not None


def _page_text_via_fitz(page) -> str:
    return page.get_text("text") or ""


def _ocr_page(page, lang: str) -> str:
    import pytesseract
    from PIL import Image
    pix = page.get_pixmap(dpi=200)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    try:
        return pytesseract.image_to_string(img, lang=lang) or ""
    except pytesseract.TesseractError:
        return ""


def _ocr_lang() -> str:
    """Return language string for tesseract.

    Defaults to "hrv+eng". Falls back to "eng" when hrv traineddata is missing.
    Determined per-call to keep the helper stateless and easy to test.
    """
    import pytesseract
    try:
        langs = set(pytesseract.get_languages(config=""))
    except (pytesseract.TesseractError, OSError):
        return "eng"
    if "hrv" in langs:
        return "hrv+eng"
    return "eng"


def _extract_pages_text(pdf_path: Path) -> list[dict]:
    """Per-page text. Falls back to Tesseract OCR for pages without a text layer."""
    out = []
    use_ocr = _has_tesseract()
    lang = _ocr_lang() if use_ocr else "eng"
    with fitz.open(pdf_path) as doc:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            text = _page_text_via_fitz(page).strip()
            if len(text) >= _OCR_MIN_CHARS:
                out.append({"page": i + 1, "text": text, "ocr_used": False})
                continue
            if use_ocr:
                ocr_text = _ocr_page(page, lang).strip()
                if ocr_text:
                    out.append({"page": i + 1, "text": ocr_text, "ocr_used": True})
                    continue
            out.append({"page": i + 1, "text": "", "ocr_used": False})
    return out


_PARSE_VERSION = 1


def _extract_outline(pdf_path: Path) -> list[dict]:
    with fitz.open(pdf_path) as doc:
        toc = doc.get_toc(simple=True) or []
    return [{"level": lvl, "title": title, "page": page} for lvl, title, page in toc]


def _extract_meta(pdf_path: Path) -> dict:
    with fitz.open(pdf_path) as doc:
        m = doc.metadata or {}
        return {
            "title": m.get("title") or "",
            "author": m.get("author") or "",
            "creator": m.get("creator") or "",
            "creation_date": m.get("creationDate") or "",
            "page_count": doc.page_count,
        }


def _parse_pdf(pdf_path: Path) -> dict:
    """Run the full parse pipeline and return a structured payload.

    The caller decides whether to also write it to cache via _write_cache.
    """
    pages = _extract_pages_text(pdf_path)
    tables = _extract_tables(pdf_path)
    outline = _extract_outline(pdf_path)
    meta = _extract_meta(pdf_path)
    stats = {
        "pages_with_text": sum(1 for p in pages if p["text"] and not p["ocr_used"]),
        "pages_ocr": sum(1 for p in pages if p["ocr_used"]),
        "pages_empty": sum(1 for p in pages if not p["text"]),
        "tables_count": len(tables),
    }
    st = pdf_path.stat()
    return {
        "version": _PARSE_VERSION,
        "source": pdf_path.name,
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "meta": meta,
        "outline": outline,
        "pages": pages,
        "tables": tables,
        "stats": stats,
    }


def _get_parsed(pdf_path: Path) -> dict:
    """Read cached parse if fresh, otherwise parse-and-cache."""
    cached = _read_cache(pdf_path)
    if cached and cached.get("version") == _PARSE_VERSION:
        return cached
    parsed = _parse_pdf(pdf_path)
    _write_cache(pdf_path, parsed)
    return parsed


def _open_target(path: str) -> Path:
    """Resolve a sandboxed path and validate it points to a readable PDF.

    Raises FileNotFoundError, ValueError("expected .pdf") or ValueError("PDF is encrypted").
    """
    target = _safe(path)
    if not target.exists():
        raise FileNotFoundError(str(target))
    if target.suffix.lower() != ".pdf":
        raise ValueError(f"expected .pdf, got {target.suffix!r}")
    # Detect encryption early — fitz.open succeeds, but doc.is_encrypted is True.
    with fitz.open(target) as doc:
        if doc.is_encrypted:
            raise ValueError("PDF is encrypted; password not supported")
    return target


@mcp.tool()
def pdf_overview(path: str) -> str:
    """First pass over a PDF: file size, page count, metadata, TOC outline,
    text/OCR/empty stats and a list of pages that contain tables. Use this
    before any other pdf_* tool so you know what you are dealing with."""
    target = _open_target(path)
    parsed = _get_parsed(target)
    meta = parsed["meta"]
    stats = parsed["stats"]
    outline = parsed["outline"]
    tables = parsed["tables"]
    size = parsed["size"]

    lines: list[str] = [
        f"# file={target.name}",
        f"# size={size}",
        f"# page_count={meta['page_count']}",
    ]
    for k in ("title", "author", "creator", "creation_date"):
        if meta.get(k):
            lines.append(f"# {k}={meta[k]}")
    lines.append(
        f"# stats: pages_with_text={stats['pages_with_text']} "
        f"pages_ocr={stats['pages_ocr']} pages_empty={stats['pages_empty']}"
    )
    lines.append(f"# tables_count={stats['tables_count']}")
    if tables:
        pages_with_tables = sorted({t["page"] for t in tables})
        lines.append(
            "# tables on pages: " + ", ".join(str(p) for p in pages_with_tables)
        )

    if outline:
        lines.append("")
        lines.append("# outline:")
        for entry in outline:
            indent = "  " * (entry["level"] - 1)
            lines.append(f"{indent}{entry['title']} (str. {entry['page']})")
    else:
        lines.append("# no TOC bookmarks; use pdf_search to locate sections")

    return "\n".join(lines)


if __name__ == "__main__":
    _root()  # eager validation at startup
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        mcp.settings.host = os.environ.get("MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("MCP_PORT", "8092"))
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
