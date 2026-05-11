# Hermes Local Auxiliary Delegation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route Hermes's six auxiliary task slots and `delegate_task` children to two local llama-server endpoints (text + vision) on the RTX 5070 Ti, and ship a new `lm-delegate` FastMCP server with three lightweight one-shot tools (`quick_classify`, `extract_json`, `summarize_chunk`) that proxy to the text endpoint.

**Architecture:** Two new llama-server processes start on the host (port 8093 = Qwen3.5-9B Q4, port 8094 = gemma-4-E4B Q4 + mmproj), managed by shell scripts mirroring the existing `start-mcp-http.sh` pattern. A new FastMCP server (`delegate_server.py`, port 8095) joins the existing four MCP servers. Hermes is rewired by editing `~/.hermes/config.yaml` (six `auxiliary.*` blocks, one `delegation` block, one `mcp_servers` entry).

**Tech Stack:** llama.cpp CUDA build (existing at `~/llama/latest/build/bin/llama-server`), FastMCP (`mcp>=1.2`), OpenAI Python SDK (`openai>=1.40`), Bash launch/stop scripts, pytest for the MCP server unit tests, Hermes config YAML.

**Spec reference:** [`docs/superpowers/specs/2026-05-11-hermes-aux-delegation-design.md`](../specs/2026-05-11-hermes-aux-delegation-design.md)

**Plan revision 2026-05-11 (post-Task-3):** Task 3 smoke-testing revealed that Qwen3.5-9B (via `--jinja` template) activates **thinking mode** by default, emitting `reasoning_content` before the user-facing answer. A `max_tokens=20` budget burns entirely on reasoning, returning empty `content`. Tasks 5-7 below have been patched to (a) pass `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` so the model skips the reasoning phase, and (b) use generous `max_tokens` as a belt-and-suspenders so the call still produces output if the thinking-disable flag is ignored by a future llama.cpp build. Tests were updated to assert both. Hermes auxiliary slots (Task 10) inherit this via per-task `extra_body` in `config.yaml`.

---

## File Structure

**Files to create (outer `LM STUDIO/` git repo):**

| Path | Responsibility |
|------|----------------|
| `start-aux-llama.sh` | Launches text + vision llama-server processes; writes PID files. |
| `stop-aux-llama.sh` | Stops aux llama-server processes by PID file. |
| `delegate_server.py` | FastMCP server exposing `quick_classify`, `extract_json`, `summarize_chunk`. |
| `lm-studio-mcp/delegate_server.py` | Frozen stdio-only copy for LM Studio (no HTTP transport). |
| `tests/test_delegate_server.py` | pytest unit tests for the three tools (mocked OpenAI client). |

**Files to modify:**

| Path | Change |
|------|--------|
| `start-mcp-http.sh` | Add `start_one lm-delegate 8095 …` row. |
| `stop-mcp-http.sh` | Add `stop_server lm-delegate` row. |
| `~/.hermes/config.yaml` | Add `auxiliary.*`, `delegation`, `mcp_servers.lm-delegate` blocks. |
| `~/.lmstudio/mcp.json` | Add `lm-delegate` entry pointing to frozen stdio copy. |

**Files NOT touched:** existing FastMCP servers (`server.py`, `web_server.py`, `xlsx_server.py`, `pdf_server.py`), the Docker 35B on port 8000, the `run-llama-server.sh` non-Docker launcher.

---

## Phase 1 — Aux llama-server endpoints

### Task 1: Write `start-aux-llama.sh`

**Files:**

- Create: `LM STUDIO/start-aux-llama.sh`

- [ ] **Step 1: Verify model files exist**

Run:

```bash
ls -lh "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO/modeli/.lmstudio/models/lmstudio-community/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf"
ls -lh "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO/modeli/.lmstudio/models/lmstudio-community/gemma-4-E4B-it-GGUF/gemma-4-E4B-it-Q4_K_M.gguf"
ls -lh "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO/modeli/.lmstudio/models/lmstudio-community/gemma-4-E4B-it-GGUF/mmproj-gemma-4-E4B-it-BF16.gguf"
```

Expected: each command prints the file (~5.5 GB, ~3.5 GB, ~600 MB).

- [ ] **Step 2: Verify CUDA llama-server binary works**

Run:

```bash
~/llama/latest/build/bin/llama-server --version 2>&1 | head -3
```

Expected output contains `ggml_cuda_init: found 1 CUDA devices` and `Device 0: NVIDIA GeForce RTX 5070 Ti`.

- [ ] **Step 3: Create `start-aux-llama.sh`**

Write to `LM STUDIO/start-aux-llama.sh`:

```bash
#!/usr/bin/env bash
# Background launcher for the two auxiliary llama-server endpoints on RTX 5070 Ti.
# Text endpoint (8093): Qwen3.5-9B Q4 — compression/web_extract/session_search/title_generation/curator/delegation.
# Vision endpoint (8094): gemma-4-E4B Q4 + mmproj — auxiliary.vision.
#
# Stop with ./stop-aux-llama.sh.

set -euo pipefail

PROJECT_DIR="/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
MODEL_DIR="$PROJECT_DIR/modeli/.lmstudio/models/lmstudio-community"
LLAMA_BIN="${LLAMA_BIN:-/home/josip-rastocic/llama/latest/build/bin/llama-server}"
LOG_DIR="$HOME/.local/state/llama-mcp"

mkdir -p "$LOG_DIR"

start_one() {
  local name="$1"; shift
  local pidfile="$LOG_DIR/$name.pid"
  local logfile="$LOG_DIR/$name.log"

  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "[$name] already running (pid $(cat "$pidfile"))"
    return
  fi

  "$@" >"$logfile" 2>&1 &
  echo $! > "$pidfile"
  echo "[$name] started (pid $!), log: $logfile"
}

start_one aux-text \
  "$LLAMA_BIN" \
    --model "$MODEL_DIR/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf" \
    --alias "qwen3.5-9b" \
    --host 127.0.0.1 --port 8093 \
    --n-gpu-layers 99 \
    --ctx-size 8192 \
    --parallel 3 \
    --flash-attn on \
    --cache-type-k q8_0 \
    --cache-type-v q8_0 \
    --jinja

start_one aux-vision \
  "$LLAMA_BIN" \
    --model "$MODEL_DIR/gemma-4-E4B-it-GGUF/gemma-4-E4B-it-Q4_K_M.gguf" \
    --alias "gemma-4-e4b-it" \
    --mmproj "$MODEL_DIR/gemma-4-E4B-it-GGUF/mmproj-gemma-4-E4B-it-BF16.gguf" \
    --host 127.0.0.1 --port 8094 \
    --n-gpu-layers 99 \
    --ctx-size 8192 \
    --parallel 1 \
    --flash-attn on \
    --jinja

echo
echo "Aux llama-servers started. Endpoints:"
echo "  text   : http://127.0.0.1:8093/v1"
echo "  vision : http://127.0.0.1:8094/v1"
echo "Tail logs with: tail -f $LOG_DIR/aux-text.log $LOG_DIR/aux-vision.log"
```

- [ ] **Step 4: Make executable**

Run:

```bash
chmod +x "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO/start-aux-llama.sh"
```

- [ ] **Step 5: Commit**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
git add start-aux-llama.sh
git commit -m "feat(aux-llama): add launcher for text + vision aux endpoints"
```

---

### Task 2: Write `stop-aux-llama.sh`

**Files:**

- Create: `LM STUDIO/stop-aux-llama.sh`

- [ ] **Step 1: Create `stop-aux-llama.sh`**

Write to `LM STUDIO/stop-aux-llama.sh`:

```bash
#!/usr/bin/env bash
# Stops the two auxiliary llama-server processes started by start-aux-llama.sh.

set -uo pipefail

LOG_DIR="$HOME/.local/state/llama-mcp"

stop_server() {
  local name="$1"
  local pidfile="$LOG_DIR/$name.pid"

  if [[ ! -f "$pidfile" ]]; then
    echo "[$name] no pidfile, not running"
    return
  fi

  local pid
  pid=$(cat "$pidfile")
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid"
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.5
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "[$name] still alive after TERM, sending KILL"
      kill -KILL "$pid" 2>/dev/null || true
    fi
    echo "[$name] stopped (pid $pid)"
  else
    echo "[$name] pidfile present but process gone"
  fi
  rm -f "$pidfile"
}

stop_server aux-text
stop_server aux-vision
```

The TERM-then-KILL window is 5 s here (10 × 0.5 s) — longer than the MCP stop script (2.5 s) because llama-server cleanup of GPU buffers can briefly stall on first signal.

- [ ] **Step 2: Make executable**

```bash
chmod +x "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO/stop-aux-llama.sh"
```

- [ ] **Step 3: Commit**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
git add stop-aux-llama.sh
git commit -m "feat(aux-llama): add matching stop script"
```

---

### Task 3: Smoke test aux endpoints

**Files:** none changed; this verifies Task 1 + 2 work.

- [ ] **Step 1: Start endpoints**

Run:

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
./start-aux-llama.sh
```

Expected output ends with the two endpoint URLs and `(pid N)` lines.

- [ ] **Step 2: Wait for model load (60–90 s) and verify the endpoints**

Wait until the log shows `HTTP server listening`, then run:

```bash
curl -s http://127.0.0.1:8093/v1/models | head -20
curl -s http://127.0.0.1:8094/v1/models | head -20
```

Expected: each returns JSON with `"data": [{"id": "qwen3.5-9b", ...}]` (text) and `"id": "gemma-4-e4b-it"` (vision). The `id` field must match the `--alias` flag.

- [ ] **Step 3: Smoke a text completion**

Run:

```bash
curl -s http://127.0.0.1:8093/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3.5-9b",
    "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
    "max_tokens": 10,
    "temperature": 0
  }' | head -50
```

Expected: JSON response with `choices[0].message.content` containing the string `pong`.

- [ ] **Step 4: Smoke a vision completion (text-only round-trip — image input is tested later in §9)**

Run:

```bash
curl -s http://127.0.0.1:8094/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "gemma-4-e4b-it",
    "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
    "max_tokens": 10,
    "temperature": 0
  }' | head -50
```

Expected: JSON response with `pong` in content.

- [ ] **Step 5: Verify VRAM usage**

Run:

```bash
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
```

Expected: `memory.used` is roughly 11–13 GB out of 16 GB (per spec §6.4).

- [ ] **Step 6: Stop endpoints (leave them off until Phase 3 needs them)**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
./stop-aux-llama.sh
```

Expected: both endpoints report `stopped (pid N)`.

---

## Phase 2 — `lm-delegate` MCP server

### Task 4: Skeleton `delegate_server.py` (PEP 723 deps + FastMCP init)

**Files:**

- Create: `LM STUDIO/delegate_server.py`

- [ ] **Step 1: Create the skeleton**

Write to `LM STUDIO/delegate_server.py`:

```python
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
```

- [ ] **Step 2: Verify it imports**

Run:

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
~/.local/bin/uv run --script delegate_server.py --help 2>&1 | head -10
```

Expected: FastMCP startup output (or usage help). No `ImportError` or `SyntaxError`.

- [ ] **Step 3: Commit**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
git add delegate_server.py
git commit -m "feat(lm-delegate): scaffold MCP server with client helpers"
```

---

### Task 5: `quick_classify` tool (TDD)

**Files:**

- Modify: `LM STUDIO/delegate_server.py`
- Create: `LM STUDIO/tests/test_delegate_server.py`

- [ ] **Step 1: Write the failing test**

Create `LM STUDIO/tests/test_delegate_server.py`:

```python
"""Unit tests for lm-delegate MCP server.

These tests mock the OpenAI client entirely — they do NOT require a live
llama-server. Integration smoke tests against a live endpoint live in
tests/test_delegate_server_integration.py (created in Task 9).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fake_completion(content: str) -> SimpleNamespace:
    """Build a fake OpenAI ChatCompletion response with the given content."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def test_quick_classify_returns_label_when_in_list():
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion("aluminij")

    with patch.object(delegate_server, "_client", return_value=fake_client):
        result = delegate_server.quick_classify(
            text="Profil 6063 T6, debljina 2 mm",
            categories=["aluminij", "staklo", "oprema", "ostalo"],
        )

    assert result == "aluminij"
    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["temperature"] == 0.0
    # Generous max_tokens accommodates thinking-mode reasoning_content
    # (Qwen3.5-9B via --jinja activates thinking by default); see plan
    # revision note at top of this file.
    assert call_kwargs["max_tokens"] == 200
    # Belt-and-suspenders: also explicitly disable thinking via extra_body.
    assert call_kwargs["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_quick_classify_falls_back_to_ostalo_when_model_returns_invalid():
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion("nepoznato")

    with patch.object(delegate_server, "_client", return_value=fake_client):
        result = delegate_server.quick_classify(
            text="...",
            categories=["aluminij", "staklo"],
        )

    assert result == "ostalo"


def test_quick_classify_strips_whitespace_from_model_output():
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion("  staklo  \n")

    with patch.object(delegate_server, "_client", return_value=fake_client):
        result = delegate_server.quick_classify(
            text="...", categories=["aluminij", "staklo"]
        )

    assert result == "staklo"
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
./run_tests.sh tests/test_delegate_server.py -v
```

Expected: failures because `delegate_server.quick_classify` doesn't exist yet (`AttributeError: module 'delegate_server' has no attribute 'quick_classify'`).

- [ ] **Step 3: Implement `quick_classify`**

Append to `LM STUDIO/delegate_server.py`:

```python
@mcp.tool()
def quick_classify(text: str, categories: list[str]) -> str:
    """Classify text into exactly one of the provided categories.

    Returns the category label as a string. If the model returns something
    outside the provided list, returns the fallback "ostalo" (Croatian for
    "other"). Temperature 0; max 20 output tokens.

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
```

- [ ] **Step 4: Run the tests and verify they pass**

Run:

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
./run_tests.sh tests/test_delegate_server.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
git add delegate_server.py tests/test_delegate_server.py
git commit -m "feat(lm-delegate): add quick_classify tool"
```

---

### Task 6: `extract_json` tool (TDD)

**Files:**

- Modify: `LM STUDIO/delegate_server.py`
- Modify: `LM STUDIO/tests/test_delegate_server.py`

- [ ] **Step 1: Add failing tests**

Append to `LM STUDIO/tests/test_delegate_server.py`:

```python
def test_extract_json_parses_model_response():
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion(
        '{"datum": "2026-04-15", "klijent": "ACME d.o.o.", "suma": 1250.50}'
    )

    schema = {
        "type": "object",
        "properties": {
            "datum": {"type": "string"},
            "klijent": {"type": "string"},
            "suma": {"type": "number"},
        },
        "required": ["datum", "klijent", "suma"],
    }

    with patch.object(delegate_server, "_client", return_value=fake_client):
        result = delegate_server.extract_json(
            text="Račun 2026-04-15 ACME d.o.o. iznos 1250,50 kn",
            schema=schema,
        )

    assert result == {"datum": "2026-04-15", "klijent": "ACME d.o.o.", "suma": 1250.50}

    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["temperature"] == 0.0
    assert call_kwargs["response_format"] == {"type": "json_object"}
    assert call_kwargs["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_extract_json_raises_value_error_on_invalid_json():
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion(
        "ovo nije JSON, ovo je rečenica"
    )

    with patch.object(delegate_server, "_client", return_value=fake_client):
        with pytest.raises(ValueError, match="model did not return valid JSON"):
            delegate_server.extract_json(text="...", schema={"type": "object"})
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
./run_tests.sh tests/test_delegate_server.py -v -k extract_json
```

Expected: `AttributeError: module 'delegate_server' has no attribute 'extract_json'`.

- [ ] **Step 3: Implement `extract_json`**

Append to `LM STUDIO/delegate_server.py`:

```python
@mcp.tool()
def extract_json(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Extract structured data from free text according to a JSON Schema.

    Uses the llama.cpp `response_format={"type": "json_object"}` grammar
    constraint so the model is forced to emit valid JSON.

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
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
./run_tests.sh tests/test_delegate_server.py -v
```

Expected: 5 tests pass total (3 from Task 5 + 2 new).

- [ ] **Step 5: Commit**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
git add delegate_server.py tests/test_delegate_server.py
git commit -m "feat(lm-delegate): add extract_json tool with json_object response_format"
```

---

### Task 7: `summarize_chunk` tool (TDD)

**Files:**

- Modify: `LM STUDIO/delegate_server.py`
- Modify: `LM STUDIO/tests/test_delegate_server.py`

- [ ] **Step 1: Add failing tests**

Append to `LM STUDIO/tests/test_delegate_server.py`:

```python
def test_summarize_chunk_returns_stripped_summary():
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion(
        "  Cijena aluminija je porasla 12% u Q1 2024.  \n"
    )

    with patch.object(delegate_server, "_client", return_value=fake_client):
        result = delegate_server.summarize_chunk(
            text="long text about aluminum prices...",
            focus="cijene",
            max_words=50,
        )

    assert result == "Cijena aluminija je porasla 12% u Q1 2024."

    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["temperature"] == 0.2
    assert call_kwargs["max_tokens"] == 200  # max_words * 4 (room for reasoning + summary)
    assert call_kwargs["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    # System prompt should mention the focus when provided
    sys_content = call_kwargs["messages"][0]["content"]
    assert "cijene" in sys_content


def test_summarize_chunk_omits_focus_clause_when_empty():
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion("Kratak sažetak.")

    with patch.object(delegate_server, "_client", return_value=fake_client):
        delegate_server.summarize_chunk(text="...", focus="", max_words=200)

    sys_content = fake_client.chat.completions.create.call_args.kwargs["messages"][0][
        "content"
    ]
    assert "Fokusiraj" not in sys_content
```

- [ ] **Step 2: Run tests and verify they fail**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
./run_tests.sh tests/test_delegate_server.py -v -k summarize_chunk
```

Expected: `AttributeError: module 'delegate_server' has no attribute 'summarize_chunk'`.

- [ ] **Step 3: Implement `summarize_chunk`**

Append to `LM STUDIO/delegate_server.py`:

```python
@mcp.tool()
def summarize_chunk(text: str, focus: str = "", max_words: int = 200) -> str:
    """Summarise the provided text, optionally biased toward a topic.

    Difference vs `delegate_task`: the text arrives in the argument; the
    callee does not read files or use any tools. One LLM call, no agent loop.

    Args:
        text: Text to summarise (1-30k chars; longer inputs may be truncated
            by the backend context window).
        focus: Optional topic bias, e.g. "cijene", "rokovi", "kvarovi".
            Empty string disables the focus clause.
        max_words: Target summary length in words. Output is capped at
            `max_words * 2` tokens.
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
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
./run_tests.sh tests/test_delegate_server.py -v
```

Expected: 7 tests pass total.

- [ ] **Step 5: Commit**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
git add delegate_server.py tests/test_delegate_server.py
git commit -m "feat(lm-delegate): add summarize_chunk tool"
```

---

### Task 8: Wire `lm-delegate` into `start-mcp-http.sh` and `stop-mcp-http.sh`

**Files:**

- Modify: `LM STUDIO/start-mcp-http.sh`
- Modify: `LM STUDIO/stop-mcp-http.sh`

- [ ] **Step 1: Edit `start-mcp-http.sh`**

Open `LM STUDIO/start-mcp-http.sh`. After the existing `start_one lm-pdf 8092 …` block, add:

```bash
start_one lm-delegate 8095 "$PROJECT_DIR/delegate_server.py" \
  LM_DELEGATE_BACKEND_URL=http://127.0.0.1:8093/v1 \
  LM_DELEGATE_MODEL=qwen3.5-9b
```

Also extend the echo block at the bottom by adding the line:

```bash
echo "  lm-delegate : http://127.0.0.1:8095/mcp"
```

- [ ] **Step 2: Edit `stop-mcp-http.sh`**

Open `LM STUDIO/stop-mcp-http.sh`. After the existing `stop_server lm-pdf` line, add:

```bash
stop_server lm-delegate
```

- [ ] **Step 3: Verify scripts parse**

Run:

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
bash -n start-mcp-http.sh
bash -n stop-mcp-http.sh
```

Expected: no output (success).

- [ ] **Step 4: Commit**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
git add start-mcp-http.sh stop-mcp-http.sh
git commit -m "feat(lm-delegate): wire into start/stop-mcp-http scripts on port 8095"
```

---

### Task 9: Integration smoke test against live endpoints

**Files:**

- Create: `LM STUDIO/tests/test_delegate_server_integration.py`

This test is **opt-in** — runs only when both `LM_DELEGATE_BACKEND_URL` is reachable AND env `RUN_INTEGRATION=1`. Default pytest run skips it.

- [ ] **Step 1: Start the aux text endpoint**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
./start-aux-llama.sh
sleep 60   # wait for model load — adjust if log shows "HTTP server listening" earlier
tail -1 ~/.local/state/llama-mcp/aux-text.log
```

Expected: log line contains `HTTP server listening`.

- [ ] **Step 2: Start the MCP servers (including lm-delegate)**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
./start-mcp-http.sh
```

Expected: `[lm-delegate] started on :8095 (pid N)`.

- [ ] **Step 3: Write the integration test**

Create `LM STUDIO/tests/test_delegate_server_integration.py`:

```python
"""Integration smoke tests against a live aux-text llama-server.

Opt-in: requires RUN_INTEGRATION=1 in the environment AND a reachable
backend at LM_DELEGATE_BACKEND_URL (default http://127.0.0.1:8093/v1).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="integration tests gated behind RUN_INTEGRATION=1",
)


def test_quick_classify_live():
    import delegate_server
    result = delegate_server.quick_classify(
        text="Aluminijski profil 6063, eloksiran, dužina 6 m",
        categories=["aluminij", "staklo", "oprema", "ostalo"],
    )
    assert result == "aluminij"


def test_extract_json_live():
    import delegate_server
    result = delegate_server.extract_json(
        text="Račun broj 2024-0042 od 15. travnja 2024, klijent ACME d.o.o., iznos 1250,50 EUR",
        schema={
            "type": "object",
            "properties": {
                "broj": {"type": "string"},
                "klijent": {"type": "string"},
                "iznos_eur": {"type": "number"},
            },
            "required": ["broj", "klijent", "iznos_eur"],
        },
    )
    assert "broj" in result
    assert "ACME" in result.get("klijent", "")
    assert result.get("iznos_eur") == pytest.approx(1250.50, rel=0.01)


def test_summarize_chunk_live():
    import delegate_server
    text = (
        "U prvom kvartalu 2024. godine cijena aluminija na LME burzi porasla je "
        "12% u odnosu na prethodni kvartal, dosegnuvši 2350 USD po toni. Razlog "
        "su geopolitičke tenzije i smanjena ponuda iz Rusije. Analitičari očekuju "
        "stabilizaciju u drugom kvartalu."
    )
    result = delegate_server.summarize_chunk(text, focus="cijene", max_words=40)
    assert len(result) > 20
    assert "alumin" in result.lower() or "cijen" in result.lower()
```

- [ ] **Step 4: Run integration tests**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
RUN_INTEGRATION=1 ./run_tests.sh tests/test_delegate_server_integration.py -v
```

Expected: 3 tests pass. If any test fails on quality (e.g. classifier returns "ostalo" for the aluminum profile), this is a model-quality signal — proceed but note for §10 mitigation review.

- [ ] **Step 5: Stop servers (keep state clean before Phase 3)**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
./stop-mcp-http.sh
./stop-aux-llama.sh
```

- [ ] **Step 6: Commit**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
git add tests/test_delegate_server_integration.py
git commit -m "test(lm-delegate): add opt-in integration smoke tests"
```

---

## Phase 3 — Hermes config wiring

### Task 10: Back up Hermes config and add auxiliary block

**Files:**

- Modify: `~/.hermes/config.yaml`

- [ ] **Step 1: Back up the current config**

Run:

```bash
cp ~/.hermes/config.yaml ~/.hermes/config.yaml.bak-$(date +%Y%m%d-%H%M%S)
ls -lh ~/.hermes/config.yaml*
```

Expected: original + a `.bak-YYYYMMDD-HHMMSS` copy exist.

- [ ] **Step 2: Inspect the current config for existing `auxiliary:` or `delegation:` keys**

Run:

```bash
grep -nE "^(auxiliary|delegation|mcp_servers):" ~/.hermes/config.yaml || echo "none of those keys present"
```

If `auxiliary:` already exists, edit in place (preserve siblings). If absent, append the new block.

- [ ] **Step 3: Add the auxiliary block**

If no `auxiliary:` block exists, append to `~/.hermes/config.yaml`:

```yaml
# YAML anchor for the thinking-mode disable flag shared by all Qwen3.5-9B routes.
# Without this, Qwen3.5-9B (via --jinja) emits reasoning_content first and burns
# the token budget, leaving content="" for short outputs like titles. Hermes
# auxiliary call_llm() passes extra_body straight through to the OpenAI request.
_no_think: &no_think
  chat_template_kwargs:
    enable_thinking: false

auxiliary:
  compression:
    base_url: "http://127.0.0.1:8093/v1"
    api_key: "no-key-required"
    model: "qwen3.5-9b"
    timeout: 60
    extra_body: *no_think

  web_extract:
    base_url: "http://127.0.0.1:8093/v1"
    api_key: "no-key-required"
    model: "qwen3.5-9b"
    timeout: 60
    extra_body: *no_think

  session_search:
    base_url: "http://127.0.0.1:8093/v1"
    api_key: "no-key-required"
    model: "qwen3.5-9b"
    timeout: 60
    max_concurrency: 3
    extra_body: *no_think

  title_generation:
    base_url: "http://127.0.0.1:8093/v1"
    api_key: "no-key-required"
    model: "qwen3.5-9b"
    extra_body: *no_think

  curator:
    base_url: "http://127.0.0.1:8093/v1"
    api_key: "no-key-required"
    model: "qwen3.5-9b"
    extra_body: *no_think

  vision:
    base_url: "http://127.0.0.1:8094/v1"
    api_key: "no-key-required"
    model: "gemma-4-e4b-it"
    timeout: 60
    download_timeout: 30
    # gemma-4 does not have thinking mode, so no extra_body needed for vision.
```

If `auxiliary:` already exists, merge each task slot's keys under it instead. The YAML anchor `&no_think` / `*no_think` is optional — you may inline the `extra_body: {chat_template_kwargs: {enable_thinking: false}}` block five times if you prefer no anchors.

- [ ] **Step 4: Validate YAML syntax**

Run:

```bash
~/.local/bin/uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('$HOME/.hermes/config.yaml'))"
```

Expected: no exception (silent success).

- [ ] **Step 5: Commit (the YAML lives outside the repo — note this is a system-level config; no git commit needed). Move on.**

The Hermes config is not tracked in the LM STUDIO/ repo. Step 5 is intentionally a no-op; the `.bak-…` file from Step 1 is the rollback path.

---

### Task 11: Add `delegation` and `mcp_servers` blocks

**Files:**

- Modify: `~/.hermes/config.yaml`

- [ ] **Step 1: Append the delegation block**

Append to `~/.hermes/config.yaml`:

```yaml
delegation:
  provider: "custom"
  base_url: "http://127.0.0.1:8093/v1"
  api_key: "no-key-required"
  model: "qwen3.5-9b"
  max_concurrent_children: 2
  child_timeout_seconds: 300
  subagent_auto_approve: false
```

If `delegation:` already exists, merge the keys instead.

**Note on thinking-mode in delegation children:** `tools/delegate_tool.py` does NOT read `delegation.extra_body` — child AIAgents spawn through the normal agent loop, not direct `call_llm()`. Thinking mode in Qwen3.5-9B may surface as long latency for short subagent tasks (the child generates a `<think>...</think>` block before its real action). If this becomes painful in Task 19 validation, the workaround is to (a) include "Do not use thinking mode" in the goal text when calling `delegate_task`, or (b) point `delegation.model` at a non-thinking model (e.g., load `gpt-oss-20b` on a third aux endpoint, off-plan). For now we accept the latency cost — children rarely run more than a few times per session, so the impact is much smaller than for auxiliary slots which fire on every compaction/title/etc.

**`extra_body` for auxiliary:** confirmed by reading `agent/auxiliary_client.py:3690` (`_get_task_extra_body` reads `auxiliary.<task>.extra_body` and merges into the OpenAI request body). The YAML structure with the `&no_think` anchor in the auxiliary block above is what the resolver expects.

- [ ] **Step 2: Append the mcp_servers entry**

Append (or merge into existing `mcp_servers:` block):

```yaml
mcp_servers:
  lm-delegate:
    url: "http://127.0.0.1:8095/mcp"
```

- [ ] **Step 3: Validate YAML syntax**

```bash
~/.local/bin/uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('$HOME/.hermes/config.yaml'))"
```

Expected: silent success.

---

### Task 12: Restart Hermes and verify wiring

**Files:** none changed; this verifies Tasks 10–11.

- [ ] **Step 1: Start all backends**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
./start-aux-llama.sh
sleep 60
./start-mcp-http.sh
```

Expected: all six MCP servers + two aux llama-servers reported as started.

- [ ] **Step 2: Launch Hermes and run a probe prompt**

Run:

```bash
hermes
```

Inside Hermes, type:

```
Generate a one-word answer: what color is the sky?
```

Expected: Hermes returns an answer. Then in a second terminal, confirm the title generation fired against the aux endpoint:

```bash
tail -20 ~/.local/state/llama-mcp/aux-text.log | grep -i "POST /v1/chat/completions" || true
```

Expected: at least one POST entry (from `title_generation`).

- [ ] **Step 3: Trigger session_search**

Inside Hermes, type:

```
/sessions search "aluminum"
```

Expected: Hermes returns summaries (possibly empty if no past sessions match). Then check the aux log:

```bash
tail -50 ~/.local/state/llama-mcp/aux-text.log | grep -i "POST /v1/chat/completions" | wc -l
```

Expected: count increases by up to 3 (one per matching session, fanned out).

- [ ] **Step 4: Confirm `lm-delegate` MCP is registered**

Inside Hermes, type:

```
/tools list | grep -i delegate
```

Expected: shows `quick_classify`, `extract_json`, `summarize_chunk` from `lm-delegate`.

- [ ] **Step 5: Exit Hermes**

Press `Ctrl-C` or type `/exit` inside Hermes.

---

## Phase 4 — Per-slot quality validation

Each task below corresponds to one row of spec §9. Run after Phase 3 is green. If a task fails, apply the §10 mitigation and re-run.

### Task 13: Validate `compression` slot

- [ ] **Step 1: Force a long session to trigger compression**

Start Hermes:

```bash
hermes
```

Run a CSV exploration session. Reference: the sandbox has `ExportOrdersSve1.csv` (4853 rows). Ask Hermes to do ~15 different queries (filter by date, group by client, sum amounts, etc.). The goal is to fill the 122 k context past the compression threshold (Hermes will auto-compress).

- [ ] **Step 2: After compression fires, probe for retained information**

Watch the Hermes UI for a `[CONTEXT COMPACTION]` marker. Then ask:

```
Which CSV file have we been analysing, and what were the three queries we ran in the first half of the conversation?
```

Expected: Hermes correctly names `ExportOrdersSve1.csv` and lists three queries from the compressed segment.

- [ ] **Step 3: Decision point**

- PASS → continue.
- FAIL (Hermes loses references) → apply §10 mitigation: temporarily set `auxiliary.compression.base_url: ""` (or remove the block) so Hermes falls back to the auto chain (cloud). Note the failure in a follow-up.

---

### Task 14: Validate `web_extract` slot

- [ ] **Step 1: Trigger a web fetch with extraction**

Inside Hermes:

```
Fetch https://en.wikipedia.org/wiki/Aluminium and summarize what aluminium is used for.
```

Expected: Hermes invokes `lm-web` (or built-in browser tool), then auxiliary `web_extract` summarises the page, and returns 3-5 bullet points.

- [ ] **Step 2: Verify the aux log shows a web_extract call**

```bash
tail -100 ~/.local/state/llama-mcp/aux-text.log | grep -c "POST /v1/chat/completions"
```

Expected: count increased since Task 13.

- [ ] **Step 3: Decision point**

- PASS → continue.
- FAIL (summary hallucinates or is empty) → swap `auxiliary.web_extract.model` to `gpt-oss-20b` (load a third llama-server on demand, off-plan) **OR** flip back to `provider: "auto"` for this slot.

---

### Task 15: Validate `session_search` slot

- [ ] **Step 1: Search for a known past topic**

Inside Hermes, search for something present in past session transcripts:

```
/sessions search "PDF"
```

(Adjust the query to match a real past Hermes session topic. If none exists, do `/sessions list` first.)

Expected: 1-3 session summaries returned, each with a date and a short focused summary.

- [ ] **Step 2: Verify parallel fan-out hit `--parallel 3`**

```bash
grep -E "slot|task" ~/.local/state/llama-mcp/aux-text.log | tail -20
```

Expected: log lines reference multiple slot IDs (0, 1, 2) within a short time window.

- [ ] **Step 3: Decision point**

- PASS → continue.
- FAIL (only one summary returned, or stall) → check that `--parallel 3` is actually set in `start-aux-llama.sh`; if so, lower `auxiliary.session_search.max_concurrency` to 2 and re-test.

---

### Task 16: Validate `title_generation` slot

- [ ] **Step 1: Start 3 fresh sessions with distinct topics**

```bash
hermes  # Session 1: ask about CSV analysis
# /exit
hermes  # Session 2: ask about PDF parsing
# /exit
hermes  # Session 3: ask about web scraping
# /exit
```

- [ ] **Step 2: Verify titles are reasonable**

```bash
hermes
```

Inside, run `/sessions list` and check the last three titles.

Expected: titles are 3-7 words, descriptive, in the same language as the conversation, no trailing punctuation/quotes.

- [ ] **Step 3: Decision point**

- PASS → continue.
- FAIL (NULL titles or generic "Untitled session") → check `~/.local/state/llama-mcp/aux-text.log` for errors; verify backend reachable. If titles are present but ugly, accept (low impact) and continue.

---

### Task 17: Validate `vision` slot

- [ ] **Step 1: Trigger vision_analyze with a local image**

Inside Hermes:

```
Describe what's in the file /media/josip-rastocic/DrugiDisk/Programi/LM STUDIO/lm-studio-sandbox/aluminum_analysis.html screenshot.
```

(If Hermes does not auto-render the HTML to image, instead point at any PNG/JPG in the sandbox — e.g. browse `~/Pictures/` for a real photo.)

Expected: Hermes invokes `vision_analyze` → auxiliary.vision endpoint at :8094 → returns a description.

- [ ] **Step 2: Verify the vision log shows the request**

```bash
tail -50 ~/.local/state/llama-mcp/aux-vision.log | grep -i "POST /v1/chat/completions"
```

Expected: at least one POST entry.

- [ ] **Step 3: Decision point**

- PASS → continue.
- FAIL (gemma-4-E4B output is too vague or wrong) → apply §10 mitigation: swap to `Qwen3.5-9B` + its mmproj on port 8094. Update `start-aux-llama.sh` to reference the 9B model + mmproj and reduce `--parallel` on the text endpoint to 2 (KV math in spec §10).

---

### Task 18: Validate `curator` slot

The curator runs idle-triggered. To test it deterministically, set a short interval in config.

- [ ] **Step 1: Add a short curator interval to config**

Edit `~/.hermes/config.yaml`. Find or add a `curator:` block (this is the curator's own config, not the auxiliary routing):

```yaml
curator:
  interval_hours: 0.01   # ~36 seconds, for testing only
```

- [ ] **Step 2: Start Hermes, wait idle, observe**

```bash
hermes
```

Inside, type a single short message, then sit idle for ~1 minute. Watch `~/.hermes/.curator_state`:

```bash
watch -n 5 cat ~/.hermes/.curator_state
```

Expected: `last_run_at` updates after ~36 s of idle time.

- [ ] **Step 3: Revert the interval after the test**

Edit `~/.hermes/config.yaml` and either remove `interval_hours` or restore the prior value (default is 24h).

- [ ] **Step 4: Decision point**

- PASS → continue.
- FAIL (no curator run, or exception in `~/.local/state/hermes/*.log`) → set `auxiliary.curator.base_url: ""` to revert to auto; raise a follow-up issue.

---

### Task 19: Validate `lm-delegate` MCP tools via Hermes

The three custom MCP tools were unit-tested in Tasks 5-7 and integration-tested in Task 9, but here we verify Hermes actually calls them.

- [ ] **Step 1: Use `quick_classify` from Hermes**

Inside Hermes:

```
Use the quick_classify tool to classify this text into one of [aluminij, staklo, oprema, ostalo]: "Profil eloksirani 6063 T6 dužine 6 m".
```

Expected: Hermes calls `lm-delegate.quick_classify`, returns `aluminij`.

- [ ] **Step 2: Use `extract_json`**

Inside Hermes:

```
Use extract_json on this text with schema {"type": "object", "properties": {"datum": {"type": "string"}, "klijent": {"type": "string"}, "suma_eur": {"type": "number"}}}: "Račun 2024-0042 od 15.4.2024, klijent ACME d.o.o., iznos 1250.50 EUR"
```

Expected: returns a JSON object with `datum`, `klijent`, `suma_eur`.

- [ ] **Step 3: Use `summarize_chunk`**

Inside Hermes:

```
Use summarize_chunk to summarize this with focus="cijene" in 30 words: "U Q1 2024 cijena aluminija na LME porasla 12% na 2350 USD/tona zbog geopolitike i ruske ponude. Stabilizacija očekivana u Q2."
```

Expected: returns a ~30-word summary about price increase.

- [ ] **Step 4: Decision point**

- PASS → Phase 4 complete.
- FAIL (Hermes can't see the tools) → check `/tools list` and the `mcp_servers.lm-delegate.url` in config; verify port 8095 is reachable with `curl http://127.0.0.1:8095/mcp` returning an MCP handshake.

---

## Phase 5 — LM Studio mirror

### Task 20: Copy `delegate_server.py` to `lm-studio-mcp/` (frozen stdio-only)

**Files:**

- Create: `LM STUDIO/lm-studio-mcp/delegate_server.py`

- [ ] **Step 1: Verify the frozen-copies directory exists**

```bash
ls "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO/lm-studio-mcp/" 2>&1 | head -10
```

Expected: existing frozen MCP files (per the dual-frontend memory).

- [ ] **Step 2: Copy the file verbatim**

```bash
cp "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO/delegate_server.py" \
   "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO/lm-studio-mcp/delegate_server.py"
```

The same file works for both stdio (LM Studio) and HTTP (llama.cpp WebUI via start-mcp-http.sh) because FastMCP picks transport based on the `MCP_TRANSPORT` env var. LM Studio spawns it with no env override → stdio mode by default.

- [ ] **Step 3: Smoke-test stdio mode**

```bash
~/.local/bin/uv run --script "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO/lm-studio-mcp/delegate_server.py" </dev/null 2>&1 | head -5
```

Expected: stdio MCP handshake on stdout (or graceful exit on EOF). No `ImportError`.

- [ ] **Step 4: Commit**

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
git add lm-studio-mcp/delegate_server.py
git commit -m "feat(lm-delegate): mirror frozen stdio copy for LM Studio"
```

---

### Task 21: Register `lm-delegate` in LM Studio's mcp.json

**Files:**

- Modify: `~/.lmstudio/mcp.json`

- [ ] **Step 1: Back up and inspect current mcp.json**

```bash
cp ~/.lmstudio/mcp.json ~/.lmstudio/mcp.json.bak-$(date +%Y%m%d-%H%M%S)
cat ~/.lmstudio/mcp.json
```

Expected: a JSON object with an `mcpServers` (or `servers`) key listing existing entries like `lm-fs`, `lm-web`, etc.

- [ ] **Step 2: Add the `lm-delegate` entry**

Edit `~/.lmstudio/mcp.json` to add an entry (preserving existing entries; the exact JSON key may be `mcpServers` or `servers` — match the existing format). The entry shape, assuming `mcpServers`:

```json
"lm-delegate": {
  "command": "/home/josip-rastocic/.local/bin/uv",
  "args": [
    "run",
    "--script",
    "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO/lm-studio-mcp/delegate_server.py"
  ],
  "env": {
    "LM_DELEGATE_BACKEND_URL": "http://127.0.0.1:8093/v1",
    "LM_DELEGATE_MODEL": "qwen3.5-9b"
  }
}
```

- [ ] **Step 3: Validate JSON syntax**

```bash
~/.local/bin/uv run --with-requirements /dev/null python -c "import json; json.load(open('$HOME/.lmstudio/mcp.json'))"
```

Expected: silent success.

- [ ] **Step 4: Restart LM Studio (manual step)**

Quit LM Studio fully and reopen it. In the chat interface, open the MCP tools panel; `lm-delegate` should appear with three tools.

- [ ] **Step 5: One-shot smoke test in LM Studio chat**

Send a message:

```
Use quick_classify to label "Profil 6063 T6 aluminijski" with categories ["aluminij", "staklo", "oprema"]. Reply with just the label.
```

Expected: model invokes the tool, returns `aluminij`.

- [ ] **Step 6: Final commit (config files not tracked, just close the loop)**

The mcp.json is not in the repo. The `.bak-…` file from Step 1 is the rollback path. No git action.

---

## Final verification

- [ ] **All Phase 1-3 tasks complete and committed**
- [ ] **All Phase 4 validation tasks have a PASS decision (or a documented mitigation)**
- [ ] **Phase 5 mirror works in LM Studio**
- [ ] **Both clients (Hermes + LM Studio) can call `lm-delegate` tools**
- [ ] **No regressions in existing 4 MCP servers (run `./run_tests.sh` to confirm all pre-existing tests still pass)**

Run final regression:

```bash
cd "/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
./run_tests.sh
```

Expected: full test suite green (all pre-existing tests + 7 new `test_delegate_server.py` unit tests).
