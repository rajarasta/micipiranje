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

import base64
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber
from rapidfuzz import fuzz

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

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


_READ_PAGES_CAP = 20


@mcp.tool()
def pdf_read_pages(path: str, start: int, count: int = 3) -> str:
    """Read text of pages [start, start+count). start is 1-based. count default
    3, hard cap 20. Inline tables are not rendered here — use pdf_extract_tables
    for table content. Pages that were OCR'd are marked with `(OCR)`; pages that
    have no text and no OCR available are marked `(no text)`."""
    if start < 1:
        raise ValueError("page must be >= 1")
    if count <= 0:
        raise ValueError("count must be > 0")
    target = _open_target(path)
    parsed = _get_parsed(target)
    pages = parsed["pages"]
    total = parsed["meta"]["page_count"]

    if start > total:
        return f"# start {start} > page_count {total}, nothing to show"

    clamped = min(count, _READ_PAGES_CAP)
    end_excl = min(start + clamped, total + 1)

    blocks: list[str] = []
    if clamped < count:
        blocks.append(f"# count clamped to {clamped} (cap={_READ_PAGES_CAP})")
    for n in range(start, end_excl):
        p = pages[n - 1]
        suffix = ""
        if p["ocr_used"]:
            suffix = " (OCR)"
        elif not p["text"]:
            suffix = " (no text)"
        blocks.append(f"# page {n} of {total}{suffix}")
        blocks.append("")
        blocks.append(p["text"])
        blocks.append("")
    return "\n".join(blocks).rstrip()


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


_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")
_FUZZY_THRESHOLD = 60
_SEARCH_LIMIT_DEFAULT = 20
_TSV_MAX_CHARS = 50000


def _split_paragraphs(text: str) -> list[str]:
    parts = _PARAGRAPH_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def _section_for_page(outline: list[dict], page: int) -> str:
    """Return the title of the latest TOC entry whose page <= the given page."""
    best = ""
    for entry in outline:
        if entry["page"] <= page:
            best = entry["title"]
        else:
            break
    return best


def _check_page_range(page_range, total: int) -> tuple[int, int]:
    if page_range is None:
        return 1, total
    if not isinstance(page_range, (list, tuple)) or len(page_range) != 2:
        raise ValueError("page_range must be a 2-element list [start, end]")
    s, e = int(page_range[0]), int(page_range[1])
    return max(1, s), min(total, e)


@mcp.tool()
def pdf_search(
    path: str,
    query: str,
    mode: str = "fuzzy",
    limit: int = _SEARCH_LIMIT_DEFAULT,
    page_range: list[int] | None = None,
) -> str:
    """Search PDF text at paragraph granularity.

    mode='exact' is case-insensitive substring; mode='fuzzy' uses
    rapidfuzz.token_set_ratio with score >= 60. page_range=[start, end]
    optionally narrows the search (1-based, inclusive). Returns top `limit`
    paragraphs as TSV with page, section and paragraph columns; fuzzy mode
    prepends a score column."""
    if not query:
        raise ValueError("query cannot be empty")
    if mode not in ("exact", "fuzzy"):
        raise ValueError(f"mode must be 'exact' or 'fuzzy', got {mode!r}")
    target = _open_target(path)
    parsed = _get_parsed(target)
    total = parsed["meta"]["page_count"]
    p_lo, p_hi = _check_page_range(page_range, total)

    candidates: list[tuple[int, str, str, int]] = []  # (page, section, paragraph, score)
    outline = parsed["outline"]
    for p in parsed["pages"]:
        n = p["page"]
        if n < p_lo or n > p_hi:
            continue
        section = _section_for_page(outline, n)
        for para in _split_paragraphs(p["text"]):
            if mode == "exact":
                if query.casefold() in para.casefold():
                    candidates.append((n, section, para, 100))
            else:
                score = int(fuzz.token_set_ratio(query, para))
                if score >= _FUZZY_THRESHOLD:
                    candidates.append((n, section, para, score))

    if mode == "fuzzy":
        candidates.sort(key=lambda r: r[3], reverse=True)
    # exact mode: keep document order

    total_matches = len(candidates)
    top = candidates[:limit]

    range_note = ""
    if page_range is not None:
        range_note = f", page_range=[{p_lo}, {p_hi}]"
    header_lines = [
        f"# search {query!r}, mode={mode}, threshold={_FUZZY_THRESHOLD}{range_note}, "
        f"showing {len(top)} of {total_matches} matches"
    ]
    if total_matches == 0:
        header_lines.append("# no matches")
        return "\n".join(header_lines)

    if mode == "fuzzy":
        rows = [["score", "page", "section", "paragraph"]]
        for page, section, para, score in top:
            rows.append([score, page, section, para])
    else:
        rows = [["page", "section", "paragraph"]]
        for page, section, para, _ in top:
            rows.append([page, section, para])
    return _to_tsv(rows, header_lines, max_chars=_TSV_MAX_CHARS)


_FIND_PAGES_LIMIT_CAP = 100


@mcp.tool()
def pdf_find_pages(
    path: str,
    query: str,
    mode: str = "fuzzy",
    limit: int = _SEARCH_LIMIT_DEFAULT,
) -> str:
    """List pages where the query appears, with hit count and (for fuzzy) the
    best score per page. Output is sorted by page ascending so the LLM can
    walk the document front-to-back. Use pdf_render_page after this to look
    at a specific page visually."""
    if not query:
        raise ValueError("query cannot be empty")
    if mode not in ("exact", "fuzzy"):
        raise ValueError(f"mode must be 'exact' or 'fuzzy', got {mode!r}")
    target = _open_target(path)
    parsed = _get_parsed(target)
    outline = parsed["outline"]

    by_page: dict[int, dict] = {}
    total_hits = 0
    for p in parsed["pages"]:
        n = p["page"]
        for para in _split_paragraphs(p["text"]):
            hit, score = False, 0
            if mode == "exact":
                if query.casefold() in para.casefold():
                    hit, score = True, 100
            else:
                score = int(fuzz.token_set_ratio(query, para))
                if score >= _FUZZY_THRESHOLD:
                    hit = True
            if hit:
                total_hits += 1
                bucket = by_page.setdefault(
                    n, {"hits": 0, "top_score": 0, "section": _section_for_page(outline, n)}
                )
                bucket["hits"] += 1
                if score > bucket["top_score"]:
                    bucket["top_score"] = score

    clamped = max(1, min(limit, _FIND_PAGES_LIMIT_CAP))
    sorted_pages = sorted(by_page.items())
    shown = sorted_pages[:clamped]
    truncated = max(0, len(sorted_pages) - clamped)

    header = [
        f"# pages with {query!r}, mode={mode}, threshold={_FUZZY_THRESHOLD}: "
        f"{len(by_page)} pages, {total_hits} total matches"
    ]
    if not by_page:
        header.append("# no pages match query")
        return "\n".join(header)

    if mode == "fuzzy":
        rows = [["page", "section", "hits", "top_score"]]
        for page, info in shown:
            rows.append([page, info["section"], info["hits"], info["top_score"]])
    else:
        rows = [["page", "section", "hits"]]
        for page, info in shown:
            rows.append([page, info["section"], info["hits"]])

    out = _to_tsv(rows, header, max_chars=_TSV_MAX_CHARS)
    if truncated:
        out += f"\n# truncated, {truncated} more pages omitted"
    return out


_HEADING_THRESHOLD = 70


@mcp.tool()
def pdf_read_section(path: str, heading: str, level: int | None = None) -> str:
    """Return the full text of a TOC section by heading. Heading is matched
    fuzzily (rapidfuzz.partial_ratio >= 70) against bookmark titles. Section
    runs from its starting page until the page before the next bookmark of
    the same or higher level. Pass level=N to restrict matching to entries
    at depth N. Errors if the PDF has no TOC bookmarks."""
    target = _open_target(path)
    parsed = _get_parsed(target)
    outline = parsed["outline"]
    if not outline:
        raise ValueError(
            "PDF has no TOC bookmarks; cannot resolve sections — use pdf_search instead"
        )

    pool = [e for e in outline if level is None or e["level"] == level]
    if not pool:
        raise ValueError(
            f"no TOC entries at level={level}; available levels: "
            f"{sorted({e['level'] for e in outline})}"
        )

    scored = sorted(
        (
            (int(fuzz.partial_ratio(heading, e["title"])), idx, e)
            for idx, e in enumerate(pool)
        ),
        key=lambda x: (-x[0], x[1]),
    )
    best_score, _, best_entry = scored[0]
    if best_score < _HEADING_THRESHOLD:
        suggestions = ", ".join(e["title"] for _, _, e in scored[:3])
        raise ValueError(
            f"section {heading!r} not found; nearest TOC entries: {suggestions}"
        )

    other_top: list[str] = []
    if len(scored) > 1 and scored[1][0] == best_score:
        other_top = [e["title"] for _, _, e in scored[1:4] if _ == best_score]

    # Determine end page: page before next entry of same-or-higher level in the FULL outline.
    start_page = best_entry["page"]
    best_level = best_entry["level"]
    full_idx = next(i for i, e in enumerate(outline) if e is best_entry)
    end_page = parsed["meta"]["page_count"]
    for e in outline[full_idx + 1 :]:
        if e["level"] <= best_level:
            end_page = e["page"] - 1
            break

    header = [
        f"# section: {best_entry['title']!r}",
        f"# pages {start_page}–{end_page} of {parsed['meta']['page_count']}",
    ]
    if other_top:
        header.append(
            "# other candidates with same score: "
            + ", ".join(repr(t) for t in other_top)
            + " — pass level= to disambiguate"
        )

    body_blocks: list[str] = []
    for n in range(start_page, end_page + 1):
        p = parsed["pages"][n - 1]
        body_blocks.append(f"## page {n}")
        body_blocks.append(p["text"])
        body_blocks.append("")
    return "\n".join(header + [""] + body_blocks).rstrip()


_EXTRACT_TABLES_CAP = 20


@mcp.tool()
def pdf_extract_tables(path: str, page: int | None = None) -> str:
    """Extract tables as TSV. page=None returns every table grouped by page;
    page=N returns only tables on that page (1-based). Hard cap 20 tables per
    call — narrow with page= when truncated."""
    target = _open_target(path)
    parsed = _get_parsed(target)
    total = parsed["meta"]["page_count"]
    if page is not None and page < 1:
        raise ValueError("page must be >= 1")
    if page is not None and page > total:
        return f"# page {page} > page_count {total}, nothing to show"

    tables = parsed["tables"]
    if page is not None:
        tables = [t for t in tables if t["page"] == page]

    pages_with = sorted({t["page"] for t in tables})
    if page is not None:
        header = [f"# {len(tables)} tables on page={page} of {total}"]
    else:
        header = [
            f"# {len(tables)} tables in document"
            + (f", on pages: {', '.join(str(p) for p in pages_with)}" if tables else "")
        ]

    if not tables:
        return "\n".join(header)

    capped = tables[:_EXTRACT_TABLES_CAP]
    truncated = len(tables) - len(capped)

    blocks = list(header) + [""]
    for t in capped:
        rows = t["rows"]
        n_rows = len(rows)
        n_cols = len(rows[0]) if rows else 0
        blocks.append(
            f"## table {t['index']} (page {t['page']}, {n_rows} rows × {n_cols} cols)"
        )
        blocks.append(_to_tsv(rows, header_lines=[], max_chars=_TSV_MAX_CHARS))
        blocks.append("")
    if truncated:
        blocks.append(
            f"# truncated, {truncated} more tables omitted — use page= to narrow"
        )
    return "\n".join(blocks).rstrip()


_DPI_MIN = 72
_DPI_MAX = 300
_DPI_DEFAULT = 150


@mcp.tool()
def pdf_render_page(path: str, page: int, dpi: int = _DPI_DEFAULT) -> list:
    """Render a single PDF page as a PNG and return it inline.

    Returns a multipart MCP response: one TextContent block with metadata
    (page number, DPI, dimensions, cache path) followed by one ImageContent
    block with the base64 PNG (mimeType image/png) so vision-capable clients
    receive the image directly. Single-page only — call again for more pages."""
    target = _open_target(path)
    parsed = _get_parsed(target)
    total = parsed["meta"]["page_count"]
    if not (1 <= page <= total):
        raise ValueError(f"page must be in range [1, {total}]")
    if not (_DPI_MIN <= dpi <= _DPI_MAX):
        raise ValueError(f"dpi must be between {_DPI_MIN} and {_DPI_MAX}")

    cache_disabled = _cache_disabled()
    render_path = _render_cache_path(target, page, dpi)
    png_bytes: bytes | None = None
    cache_note = ""

    if not cache_disabled and render_path.exists():
        png_bytes = render_path.read_bytes()
        cache_note = f"# cached at: {render_path.relative_to(_root())}"
    else:
        with fitz.open(target) as doc:
            pix = doc.load_page(page - 1).get_pixmap(dpi=dpi)
            png_bytes = pix.tobytes("png")
        if cache_disabled:
            cache_note = "# render not cached: LM_PDF_NO_CACHE=1"
        else:
            try:
                render_path.parent.mkdir(parents=True, exist_ok=True)
                render_path.write_bytes(png_bytes)
                cache_note = f"# cached at: {render_path.relative_to(_root())}"
            except OSError as e:
                cache_note = f"# render not cached: {e.strerror or e}"

    # PNG IHDR chunk: width at bytes [16:20], height at [20:24], big-endian.
    width = int.from_bytes(png_bytes[16:20], "big")
    height = int.from_bytes(png_bytes[20:24], "big")
    size_kb = len(png_bytes) // 1024
    text_lines = [
        f"# page {page} of {total}, rendered at {dpi} dpi ({width}×{height} px, {size_kb} KB)",
    ]
    if cache_note:
        text_lines.append(cache_note)

    return [
        TextContent(type="text", text="\n".join(text_lines)),
        ImageContent(
            type="image",
            data=base64.b64encode(png_bytes).decode("ascii"),
            mimeType="image/png",
        ),
    ]


if __name__ == "__main__":
    _root()  # eager validation at startup
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        mcp.settings.host = os.environ.get("MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("MCP_PORT", "8092"))
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
