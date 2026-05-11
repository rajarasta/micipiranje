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
    # revision note at top of plan file.
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
