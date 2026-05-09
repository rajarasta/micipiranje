# Local LLM workspace — MCP servers + launchers

Self-contained collection of four MCP servers and the launcher scripts that run them alongside [llama.cpp](https://github.com/ggml-org/llama.cpp)'s `llama-server` (with the WebUI MCP proxy) and [LM Studio](https://lmstudio.ai/). Both clients are first-class — every server is reachable via HTTP for the WebUI and via stdio for LM Studio's `mcp.json`.

## Components

### MCP servers

| Server | File | Port | Purpose |
| --- | --- | --- | --- |
| `lm-fs` | [server.py](server.py) | 8089 | Read/write files inside the sandbox |
| `lm-web` | [web_server.py](web_server.py) | 8090 | Web search/fetch via SearXNG and direct HTTP |
| `lm-xlsx` | [xlsx_server.py](xlsx_server.py) | 8091 | Read/inspect XLSX/CSV — see [XLSX_MCP_README.md](XLSX_MCP_README.md) |
| `lm-pdf` | [pdf_server.py](pdf_server.py) | 8092 | Inspect, search, render, crop PDFs — see [PDF_MCP_README.md](PDF_MCP_README.md) |

All four read from the same sandbox directory pointed at by the `LM_MCP_ROOT` environment variable (default in [start-mcp-http.sh](start-mcp-http.sh): `./lm-studio-sandbox`).

### Launchers

- [start-mcp-http.sh](start-mcp-http.sh) — starts all four MCP servers in HTTP mode (background, PID files in `~/.local/state/llama-mcp/`).
- [stop-mcp-http.sh](stop-mcp-http.sh) — stops them.
- [run-llama-server.sh](run-llama-server.sh) — foreground launcher for `llama-server` itself (Qwen3.5-9B by default, port 8033, with WebUI MCP proxy enabled).

### LM Studio frozen-copy fork ([lm-studio-mcp/](lm-studio-mcp/))

Mirror of the four servers configured for LM Studio's stdio transport (no HTTP `__main__` block). LM Studio is a permanent first-class client; this directory keeps the stdio variant of each server in sync with the canonical HTTP-capable copy at the repo root. When editing a server, mirror the change to both copies.

## Quick start

In two terminals:

```bash
# terminal 1 — background MCP servers
./start-mcp-http.sh

# terminal 2 — foreground llama-server with WebUI (Ctrl+C to stop)
./run-llama-server.sh
```

Then open `http://127.0.0.1:8033/` and add three MCP entries via the WebUI settings:

- `http://127.0.0.1:8089/mcp`
- `http://127.0.0.1:8090/mcp`
- `http://127.0.0.1:8091/mcp`
- `http://127.0.0.1:8092/mcp`

For each entry, enable the **"use llama-server proxy"** toggle. Stop with `./stop-mcp-http.sh`.

### Useful environment overrides

- `CTX_SIZE=131072 ./run-llama-server.sh` — raise context window for `llama-server`
- `KV_CACHE_TYPE=f16 ./run-llama-server.sh` — keep KV cache in fp16
- `LM_PDF_INLINE_RENDER=1 ./start-mcp-http.sh` — force `pdf_render_page` to return inline base64 images (default `0` keeps prompt context lean)
- `LM_PDF_FILES_URL_BASE=http://host:port/files` — override the URL prefix the PDF server emits for browser-rendered images (default derived from `MCP_HOST`/`MCP_PORT`)

## LM Studio integration

Add entries to `~/.lmstudio/mcp.json`:

```json
{
  "mcpServers": {
    "lm-fs":   { "command": "/full/path/to/uv", "args": ["run", "--script", "/full/path/to/lm-studio-mcp/server.py"],     "env": { "LM_MCP_ROOT": "/full/path/to/sandbox" } },
    "lm-web":  { "command": "/full/path/to/uv", "args": ["run", "--script", "/full/path/to/lm-studio-mcp/web_server.py"],  "env": { "LM_MCP_ROOT": "/full/path/to/sandbox" } },
    "lm-xlsx": { "command": "/full/path/to/uv", "args": ["run", "--script", "/full/path/to/lm-studio-mcp/xlsx_server.py"], "env": { "LM_MCP_ROOT": "/full/path/to/sandbox" } },
    "lm-pdf":  { "command": "/full/path/to/uv", "args": ["run", "--script", "/full/path/to/lm-studio-mcp/pdf_server.py"],  "env": { "LM_MCP_ROOT": "/full/path/to/sandbox" } }
  }
}
```

Use the `lm-studio-mcp/` copies (stdio transport), not the canonical root copies (HTTP transport).

## Tests

```bash
./run_tests.sh                          # run everything
./run_tests.sh tests/test_pdf_server.py # one server's suite
```

The script runs `pytest` inside `uv run --with ...` with all test-time deps spelled out, so no `requirements.txt` is needed. Fixtures live under [tests/fixtures/](tests/fixtures/).

## Dependencies

Runtime deps live **inside each server script** as PEP 723 inline metadata (`# /// script ... # ///`). `uv run --script <file>` reads them, builds an isolated environment, and runs the script. There is no top-level `requirements.txt` and adding one would just risk drift.

To install `uv` itself: `curl -LsSf https://astral.sh/uv/install.sh | sh`.

Optional system packages:

- **Tesseract OCR** for scanned PDFs: `sudo apt install tesseract-ocr tesseract-ocr-hrv tesseract-ocr-eng`
- **SearXNG** for `lm-web` searches: a local instance at `http://127.0.0.1:8080` is the default

## Sandbox

`LM_MCP_ROOT` is the only directory the MCP servers will read or write. Everything in there is fair game: the user puts their PDFs/XLSX into it; the PDF server caches renders and crops under `<sandbox>/.lm-pdf-cache/`. The repo's [lm-studio-sandbox/](lm-studio-sandbox/) is a convenient default and is gitignored — never commit user content.

## Documentation

- [PDF_MCP_README.md](PDF_MCP_README.md) — `lm-pdf` tool list, Tesseract setup, vision-model crop workflow
- [XLSX_MCP_README.md](XLSX_MCP_README.md) — `lm-xlsx` tools and conventions
- [docs/superpowers/specs/](docs/superpowers/specs/) — design specs for each server
- [docs/windows/](docs/windows/) — Windows packaging notes
