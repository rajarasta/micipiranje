# lm-pdf — PDF inspection MCP for LM Studio and llama.cpp

Read-only MCP server that lets an LLM inspect, search and render PDF documents (contracts, offers, specs) inside the same `LM_MCP_ROOT` sandbox used by `lm-fs` ([server.py](server.py)) and `lm-xlsx` ([xlsx_server.py](xlsx_server.py)).

See the design spec for full details: [docs/superpowers/specs/2026-05-07-pdf-mcp-design.md](docs/superpowers/specs/2026-05-07-pdf-mcp-design.md).

## Tools

| Tool | Purpose |
| --- | --- |
| `pdf_overview(path)` | First pass: page count, metadata, TOC outline, text/OCR/empty stats, table list |
| `pdf_read_pages(path, start, count=3)` | Page text, paginated; hard cap 20 |
| `pdf_read_section(path, heading, level=None)` | Full text of a TOC section by fuzzy heading match |
| `pdf_search(path, query, mode="fuzzy", limit=20, page_range=None)` | Paragraph search; exact or `rapidfuzz.token_set_ratio ≥ 60` |
| `pdf_extract_tables(path, page=None)` | Tables as TSV; per-page or whole-doc |
| `pdf_find_pages(path, query, mode="fuzzy", limit=20)` | Aggregated page list with hit counts (sorted by page) |
| `pdf_render_page(path, page, dpi=150)` | Render a single page as PNG; returns inline image to vision models |
| `pdf_inspect_layout(path, page, dpi=150)` | List detected regions (text/image/drawing) with pixel bboxes |
| `pdf_extract_region(path, page, bbox, dpi=150, save_as=None)` | Crop a region as PNG, save to sandbox, return inline image |

All text output is TSV with `# ...` metadata headers, capped at ~50k characters with a `# truncated` marker. `pdf_render_page` and `pdf_extract_region` return multipart content (text + image).

## Use case: report with cropped images

Vision-model workflow for an analyst building a report from a contract or technical spec:

1. `pdf_render_page(path, page=N, dpi=150)` — vision model sees the full page.
2. `pdf_inspect_layout(path, page=N, dpi=150)` — model gets the list of text blocks, embedded images, and vector drawings with bboxes (same coordinate system as the render).
3. `pdf_extract_region(path, page=N, bbox=[x0, y0, x1, y1], dpi=150, save_as="reports/signature_p5.png")` — crops the chosen region, saves it inside the sandbox.
4. Use `lm-fs` to write a markdown report that references the saved PNG path. The cropped images live in the same sandbox so any other tool can pick them up.

## Install in LM Studio

Add a new entry alongside the existing `lm-fs`, `lm-web` and `lm-xlsx` blocks in `~/.lmstudio/mcp.json`:

```json
{
  "mcpServers": {
    "lm-pdf": {
      "command": "/full/path/to/uv",
      "args": ["run", "--script", "/full/path/to/pdf_server.py"],
      "env": { "LM_MCP_ROOT": "/full/path/to/sandbox" }
    }
  }
}
```

The first run downloads PyMuPDF, pdfplumber, rapidfuzz, pytesseract and Pillow via `uv` (~70 MB).

## Use from llama.cpp WebUI

`lm-pdf` is wired into `start-mcp-http.sh` on port `8092`. After starting:

```text
http://127.0.0.1:8092/mcp
```

## Run tests

```bash
./run_tests.sh tests/test_pdf_server.py -v
```

Fixtures live in `tests/fixtures/pdf/`. Regenerate them with `uv run --script tests/fixtures/pdf/build_fixtures.py` (requires DejaVuSans for `croatian.pdf`).

## Optional: Tesseract OCR

For scanned PDFs, install Tesseract and Croatian language data:

```bash
sudo apt install tesseract-ocr tesseract-ocr-hrv tesseract-ocr-eng
```

Without Tesseract, image-only pages return empty text and are flagged `(no text)` in `pdf_read_pages`. The server still works for born-digital PDFs.

## Supported / not supported

Supported: `.pdf` (born-digital and OCR-fallback for scans), TOC bookmarks, table extraction (heuristic), Croatian text via OCR with `hrv+eng`.

Not supported: encrypted PDFs (raises `ValueError`), fillable form fields, math/equations (use a different parser), individual figure cropping, multi-document operations.
