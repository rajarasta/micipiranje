# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=1.2",
#   "openai>=1.40",
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
from typing import Any

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
        raise ValueError(f"model did not return valid JSON: {exc}; raw={raw!r}") from exc
