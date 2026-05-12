# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=1.2",
#   "openai>=1.40",
#   "pymupdf>=1.24",
# ]
# ///
"""LM Studio sandbox delegation MCP server.

Exposes three lightweight one-shot tools that proxy to a local OpenAI-compatible
llama-server endpoint (default http://127.0.0.1:8093/v1). Each call is stateless;
the tools never carry context across requests.

Tools:
  - quick_classify(text, categories)   -> single category label
  - extract_json(text, schema)         -> dict matching schema
  - summarize_chunk(text, focus, max_words) -> summary string

Configuration via environment:
  LM_DELEGATE_BACKEND_URL  default: http://127.0.0.1:8093/v1
  LM_DELEGATE_MODEL        default: qwen3.5-9b
  LM_DELEGATE_API_KEY      default: no-key-required
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pymupdf
from mcp.server.fastmcp import FastMCP
from openai import OpenAI

mcp = FastMCP("lm-delegate")


def _client() -> OpenAI:
    """Construct an OpenAI client pointed at the configured backend.

    Re-read env vars on each call so tests can monkeypatch them without
    reloading the module.
    """
    return OpenAI(
        base_url=os.environ.get("LM_DELEGATE_BACKEND_URL", "http://127.0.0.1:8093/v1"),
        api_key=os.environ.get("LM_DELEGATE_API_KEY", "no-key-required"),
    )


def _model() -> str:
    return os.environ.get("LM_DELEGATE_MODEL", "qwen3.5-9b")


@mcp.tool()
def quick_classify(text: str, categories: list[str]) -> str:
    """Classify text into exactly one of the provided categories.

    Returns the category label as a string. If the model returns something
    outside the provided list, returns the fallback "ostalo" (Croatian for
    "other"). Temperature 0; max 200 output tokens to leave room for
    thinking-mode reasoning_content (the Qwen3.5-9B chat template enables
    thinking by default; extra_body explicitly disables it but kept generous
    in case the flag is ignored by a future llama.cpp build).

    Args:
        text: Input text to classify (typical 100-8000 chars).
        categories: Allowed category labels, e.g. ["aluminij", "staklo", "oprema"].
    """
    resp = _client().chat.completions.create(
        model=_model(),
        messages=[
            {
                "role": "system",
                "content": (
                    f"Klasificiraj tekst u TOČNO JEDNU kategoriju iz liste: {categories}. "
                    f"Vrati SAMO ime kategorije, ništa drugo. Bez navodnika, bez objašnjenja."
                ),
            },
            {"role": "user", "content": text},
        ],
        temperature=0.0,
        max_tokens=200,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    label = (resp.choices[0].message.content or "").strip()
    return label if label in categories else "ostalo"


@mcp.tool()
def extract_json(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Extract structured data from free text according to a JSON Schema.

    Uses the llama.cpp `response_format={"type": "json_object"}` grammar
    constraint so the model is forced to emit valid JSON. The Qwen3.5-9B
    thinking-mode flag is explicitly disabled via `extra_body` (see plan
    revision note); JSON-grammar constraint is incompatible with thinking
    in practice because reasoning_content is plain prose.

    Args:
        text: Source text (e.g. invoice line, log entry, free-form note).
        schema: JSON Schema describing the desired output object.

    Returns:
        Parsed dict matching the schema.

    Raises:
        ValueError: If the model output is not valid JSON.
    """
    resp = _client().chat.completions.create(
        model=_model(),
        messages=[
            {
                "role": "system",
                "content": (
                    f"Ekstrahiraj podatke u JSON koji točno odgovara ovoj schemi:\n"
                    f"{json.dumps(schema, ensure_ascii=False)}\n"
                    f"Vrati SAMO valid JSON, bez objašnjenja, bez code-fence-ova."
                ),
            },
            {"role": "user", "content": text},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    raw = resp.choices[0].message.content or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model did not return valid JSON: {exc}; raw={raw[:500]!r}") from exc


@mcp.tool()
def summarize_chunk(text: str, focus: str = "", max_words: int = 200) -> str:
    """Summarise the provided text, optionally biased toward a topic.

    Difference vs `delegate_task`: the text arrives in the argument; the
    callee does not read files or use any tools. One LLM call, no agent loop.

    max_tokens is set to `max_words * 4` to leave room for the model's
    thinking-mode `reasoning_content` (which extra_body explicitly disables
    but kept generous as belt-and-suspenders; see plan revision note).

    Args:
        text: Text to summarise (1-30k chars; longer inputs may be truncated
            by the backend context window).
        focus: Optional topic bias, e.g. "cijene", "rokovi", "kvarovi".
            Empty string disables the focus clause.
        max_words: Target summary length in words. Output is capped at
            `max_words * 4` tokens.
    """
    focus_clause = f" Fokusiraj se posebno na: {focus}." if focus else ""
    resp = _client().chat.completions.create(
        model=_model(),
        messages=[
            {
                "role": "system",
                "content": (
                    f"Napravi koncizan sažetak (cilj ~{max_words} riječi)."
                    f"{focus_clause} Vrati SAMO sažetak, bez uvoda."
                ),
            },
            {"role": "user", "content": text},
        ],
        temperature=0.2,
        max_tokens=max_words * 4,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    return (resp.choices[0].message.content or "").strip()


_EXT_TO_FILE_TYPE: dict[str, str] = {
    ".pdf": "pdf",
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".sh": "shell",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".csv": "csv",
    ".txt": "text",
}


def _detect_file_type(path: Path) -> str:
    ext = path.suffix.lower()
    return _EXT_TO_FILE_TYPE.get(ext, "text")


@mcp.tool()
def read_with_focus(path: str, focus: str, max_words: int = 200) -> dict[str, Any]:
    """Read a file and return a focused summary + relevant ranges.

    For text files (.py, .js, .ts, .sh, .md, .txt, .json, .yaml, .csv, ...):
        - Returns line-based ranges. range_unit = "lines".
    For PDF files (.pdf):
        - Returns page-based ranges via pymupdf. range_unit = "pages".
    For other files:
        - Attempt UTF-8 read; if it fails, raise ValueError("binary file not supported").

    Returns:
        dict with keys:
          summary: str        # ~max_words words
          relevant_ranges: list[tuple[int, int]]   # inclusive line or page ranges
          range_unit: str     # "lines" or "pages"
          total_units: int    # total line count or page count
          file_type: str      # "python", "pdf", "text", "json", ...

    Raises:
        FileNotFoundError: path does not exist.
        ValueError: binary file, or file too large for single-pass (>60k token estimate).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")

    file_type = _detect_file_type(p)
    unit = "pages" if file_type == "pdf" else "lines"

    # --- Read content ---
    if file_type == "pdf":
        try:
            with pymupdf.open(str(p)) as doc:
                pages_text = [
                    f"=== PAGE {i} ===\n{page.get_text()}"
                    for i, page in enumerate(doc, start=1)
                ]
        except Exception as exc:
            raise ValueError(f"PDF read failed: {exc}") from exc
        total_units = len(pages_text)
        content = "\n".join(pages_text)
    else:
        try:
            content = p.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"binary file not supported: {path}") from exc
        total_units = len(content.splitlines())

    # --- Pre-budget check ---
    estimate = len(content) // 4
    if estimate > 60_000:
        raise ValueError(
            f"file too large for single-pass ({estimate} estimated tokens); "
            "consider grep/lm-pdf chunking first"
        )

    # --- Empty file short-circuit ---
    if total_units == 0:
        return {
            "summary": "(empty file)",
            "relevant_ranges": [],
            "range_unit": unit,
            "total_units": 0,
            "file_type": file_type,
        }

    # --- Build numbered content ---
    if file_type == "pdf":
        numbered = content  # page markers already in place
    else:
        lines = content.splitlines()
        numbered = "\n".join(f"L{n}: {line}" for n, line in enumerate(lines, start=1))

    # --- LLM call ---
    system_prompt = (
        f"Read the following file. Focus: {focus}. Return JSON exactly matching:\n"
        f'  {{"summary": <max ~{max_words} word summary>,\n'
        f'   "relevant_ranges": [[start, end], ...],\n'
        f'   "range_unit": "{unit}"}}\n'
        f"Be conservative — only include ranges with genuinely relevant content."
    )

    resp = _client().chat.completions.create(
        model=_model(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": numbered},
        ],
        temperature=0.2,
        max_tokens=max_words * 4 + 500,
        response_format={"type": "json_object"},
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )

    raw = resp.choices[0].message.content or ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"model did not return valid JSON; raw={raw[:500]!r}"
        ) from exc

    # Deterministically set range_unit from file_type (never trust LLM)
    # Convert relevant_ranges to list of tuples, validating each entry
    relevant_ranges: list[tuple[int, int]] = []
    for r in parsed.get("relevant_ranges", []):
        if not (isinstance(r, list) and len(r) == 2 and all(isinstance(v, int) for v in r)):
            raise ValueError(f"model returned malformed range: {r!r}")
        relevant_ranges.append((r[0], r[1]))

    return {
        "summary": parsed.get("summary", ""),
        "relevant_ranges": relevant_ranges,
        "range_unit": unit,
        "total_units": total_units,
        "file_type": file_type,
    }


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        mcp.settings.host = os.environ.get("MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("MCP_PORT", "8095"))
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
