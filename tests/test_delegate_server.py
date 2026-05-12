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
    # Prompt-contract assertions (added per Task 5 code review): guard against
    # silently dropping {categories} from the system prompt or {text} from user.
    sys_msg = call_kwargs["messages"][0]["content"]
    assert "aluminij" in sys_msg
    assert "staklo" in sys_msg
    user_msg = call_kwargs["messages"][1]["content"]
    assert user_msg == "Profil 6063 T6, debljina 2 mm"
    assert call_kwargs["model"] == "qwen3.5-9b"


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
    # Prompt-contract assertions
    sys_msg = call_kwargs["messages"][0]["content"]
    assert "datum" in sys_msg and "klijent" in sys_msg
    assert call_kwargs["messages"][1]["content"] == "Račun 2026-04-15 ACME d.o.o. iznos 1250,50 kn"


def test_extract_json_raises_value_error_on_invalid_json():
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion(
        "ovo nije JSON, ovo je rečenica"
    )

    with patch.object(delegate_server, "_client", return_value=fake_client):
        with pytest.raises(ValueError, match=r"model did not return valid JSON.*raw="):
            delegate_server.extract_json(text="...", schema={"type": "object"})


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
    # User message should be the input text
    assert call_kwargs["messages"][1]["content"] == "long text about aluminum prices..."


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


# ---------------------------------------------------------------------------
# read_with_focus tests (Phase 1)
# ---------------------------------------------------------------------------


def test_read_with_focus_text_file_returns_summary_and_line_ranges(tmp_path):
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    # 30-line Python file (one-liner functions, one line each)
    py_file = tmp_path / "module.py"
    lines = [f"def foo_{n}(): pass" for n in range(1, 31)]
    py_file.write_text("\n".join(lines) + "\n")

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion(
        '{"summary": "Found tax fn at lines 5-10", "relevant_ranges": [[5, 10]], "range_unit": "lines"}'
    )

    with patch.object(delegate_server, "_client", return_value=fake_client):
        result = delegate_server.read_with_focus(
            path=str(py_file), focus="tax functions"
        )

    assert "summary" in result
    assert result["relevant_ranges"] == [(5, 10)]
    assert result["range_unit"] == "lines"
    assert result["total_units"] == 30
    assert result["file_type"] == "python"

    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    sys_msg = call_kwargs["messages"][0]["content"]
    assert "tax functions" in sys_msg
    user_msg = call_kwargs["messages"][1]["content"]
    assert "L1: " in user_msg
    assert call_kwargs["temperature"] == 0.2
    assert call_kwargs["response_format"] == {"type": "json_object"}
    assert call_kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


def test_read_with_focus_pdf_file_returns_page_ranges(tmp_path):
    import importlib
    import delegate_server
    importlib.reload(delegate_server)
    import pymupdf

    pdf_file = tmp_path / "document.pdf"
    doc = pymupdf.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Page one content about invoices")
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Page two content about contracts")
    doc.save(str(pdf_file))
    doc.close()

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion(
        '{"summary": "Invoice on page 1", "relevant_ranges": [[1, 1]], "range_unit": "pages"}'
    )

    with patch.object(delegate_server, "_client", return_value=fake_client):
        result = delegate_server.read_with_focus(
            path=str(pdf_file), focus="invoices"
        )

    assert result["range_unit"] == "pages"
    assert result["total_units"] == 2
    assert result["file_type"] == "pdf"

    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    user_msg = call_kwargs["messages"][1]["content"]
    assert "=== PAGE 1 ===" in user_msg
    assert "=== PAGE 2 ===" in user_msg


def test_read_with_focus_empty_file_skips_llm(tmp_path):
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("")

    fake_client = MagicMock()

    with patch.object(delegate_server, "_client", return_value=fake_client):
        result = delegate_server.read_with_focus(
            path=str(empty_file), focus="anything"
        )

    fake_client.chat.completions.create.assert_not_called()
    assert result["summary"] == "(empty file)"
    assert result["relevant_ranges"] == []
    assert result["range_unit"] == "lines"
    assert result["total_units"] == 0
    assert result["file_type"] == "text"


def test_read_with_focus_binary_raises(tmp_path):
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    bin_file = tmp_path / "image.png"
    bin_file.write_bytes(b"\x80\x81\x82\xff\xfe")

    with pytest.raises(ValueError, match="binary"):
        delegate_server.read_with_focus(path=str(bin_file), focus="anything")


def test_read_with_focus_missing_path_raises():
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    with pytest.raises(FileNotFoundError):
        delegate_server.read_with_focus(
            path="/nonexistent/path/does_not_exist.txt", focus="anything"
        )


def test_read_with_focus_file_too_large_raises(tmp_path):
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    large_file = tmp_path / "big.txt"
    large_file.write_text("x" * 250_000)

    fake_client = MagicMock()

    with patch.object(delegate_server, "_client", return_value=fake_client):
        with pytest.raises(ValueError, match="file too large"):
            delegate_server.read_with_focus(path=str(large_file), focus="anything")

    fake_client.chat.completions.create.assert_not_called()


def test_read_with_focus_malformed_range_raises(tmp_path):
    """Model returning a range with wrong element count → ValueError, not silent pass-through."""
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    txt_file = tmp_path / "sample.txt"
    txt_file.write_text("line one\nline two\nline three\n")

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion(
        '{"summary": "ok", "relevant_ranges": [[1, 5, 3]], "range_unit": "lines"}'
    )

    with patch.object(delegate_server, "_client", return_value=fake_client):
        with pytest.raises(ValueError, match="malformed range"):
            delegate_server.read_with_focus(path=str(txt_file), focus="anything")


# ---------------------------------------------------------------------------
# rank_files tests (Phase 2)
# ---------------------------------------------------------------------------


def test_rank_files_batched_returns_sorted_results(tmp_path):
    """Three files ranked by model; result sorted DESC by score."""
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    f0 = tmp_path / "alpha.txt"
    f1 = tmp_path / "beta.txt"
    f2 = tmp_path / "gamma.txt"
    f0.write_text("alpha content about invoices")
    f1.write_text("beta content: exact match for query")
    f2.write_text("gamma content: unrelated stuff")

    paths = [str(f0), str(f1), str(f2)]

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion(
        '{"rankings": ['
        '{"index": 1, "score": 9, "reason": "exact match"},'
        '{"index": 0, "score": 4, "reason": "tangential"},'
        '{"index": 2, "score": 2, "reason": "unrelated"}'
        ']}'
    )

    with patch.object(delegate_server, "_client", return_value=fake_client):
        result = delegate_server.rank_files(
            query="find invoice-related files",
            paths=paths,
        )

    # Single LLM call
    fake_client.chat.completions.create.assert_called_once()

    # Sorted DESC by score
    assert result[0]["path"] == str(f1)
    assert result[0]["score"] == 9
    assert result[1]["score"] == 4
    assert result[2]["score"] == 2

    # All results have required keys
    for item in result:
        assert "path" in item
        assert "score" in item
        assert "reason" in item

    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["temperature"] == 0.2
    assert call_kwargs["response_format"] == {"type": "json_object"}
    assert call_kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}

    # System prompt contains the query
    sys_msg = call_kwargs["messages"][0]["content"]
    assert "find invoice-related files" in sys_msg

    # User message contains index markers and file paths
    user_msg = call_kwargs["messages"][1]["content"]
    assert "[0]" in user_msg
    assert "[1]" in user_msg
    assert "[2]" in user_msg
    assert str(f0) in user_msg
    assert str(f1) in user_msg
    assert str(f2) in user_msg


def test_rank_files_empty_paths_skips_llm():
    """Empty paths list returns [] without any LLM call."""
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    fake_client = MagicMock()

    with patch.object(delegate_server, "_client", return_value=fake_client):
        result = delegate_server.rank_files(query="anything", paths=[])

    assert result == []
    fake_client.chat.completions.create.assert_not_called()


def test_rank_files_missing_path_gets_zero(tmp_path):
    """A non-existent path gets score=0 and reason='(file not found)'; batch continues."""
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    f0 = tmp_path / "exists1.txt"
    f2 = tmp_path / "exists2.txt"
    f0.write_text("content of first file")
    f2.write_text("content of third file")

    paths = [str(f0), "/nonexistent/file.txt", str(f2)]

    fake_client = MagicMock()
    # Model only returns rankings for index 0 and 2 (skips missing index 1)
    fake_client.chat.completions.create.return_value = _fake_completion(
        '{"rankings": ['
        '{"index": 0, "score": 7, "reason": "relevant"},'
        '{"index": 2, "score": 3, "reason": "partial"}'
        ']}'
    )

    with patch.object(delegate_server, "_client", return_value=fake_client):
        result = delegate_server.rank_files(query="test query", paths=paths)

    # Result list length matches input
    assert len(result) == 3

    # Find the entry for the missing path
    result_by_path = {item["path"]: item for item in result}
    missing_entry = result_by_path["/nonexistent/file.txt"]
    assert missing_entry["score"] == 0
    assert missing_entry["reason"] == "(file not found)"

    # Other two paths have model-provided scores
    assert result_by_path[str(f0)]["score"] == 7
    assert result_by_path[str(f2)]["score"] == 3


def test_rank_files_budget_exceeded_raises(tmp_path):
    """Budget > 60k tokens raises ValueError BEFORE any LLM call."""
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    # 30 files * 10_000 chars preview each → budget = (300_000 // 4) + (50 * 30) = 75_000 + 1_500 = 76_500 > 60k
    # Must pass preview_chars=10_000 so that all chars are actually loaded into previews[i].
    files = []
    for i in range(30):
        f = tmp_path / f"file_{i}.txt"
        f.write_text("x" * 10_000)
        files.append(str(f))

    fake_client = MagicMock()

    with patch.object(delegate_server, "_client", return_value=fake_client):
        with pytest.raises(ValueError, match="token budget exceeded"):
            delegate_server.rank_files(query="any query", paths=files, preview_chars=10_000)

    # LLM must NOT have been called
    fake_client.chat.completions.create.assert_not_called()


def test_rank_files_pdf_preview_uses_only_first_page(tmp_path):
    """PDF ranking only reads page 1; later pages must not appear in the prompt."""
    import importlib
    import delegate_server
    importlib.reload(delegate_server)
    import pymupdf

    pdf_file = tmp_path / "multipage.pdf"
    doc = pymupdf.open()
    for i, marker in enumerate(
        ["PAGE_ONE_MARKER", "PAGE_TWO_MARKER", "PAGE_THREE_MARKER",
         "PAGE_FOUR_MARKER", "PAGE_FIVE_MARKER"],
        start=1,
    ):
        page = doc.new_page()
        page.insert_text((72, 72), f"This is page {i} with marker {marker}")
    doc.save(str(pdf_file))
    doc.close()

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion(
        '{"rankings": [{"index": 0, "score": 5, "reason": "pdf file"}]}'
    )

    with patch.object(delegate_server, "_client", return_value=fake_client):
        delegate_server.rank_files(
            query="find marker content",
            paths=[str(pdf_file)],
        )

    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    user_msg = call_kwargs["messages"][1]["content"]

    # Page 1 content should be present
    assert "PAGE_ONE_MARKER" in user_msg
    # Pages 2+ should NOT appear in the prompt
    assert "PAGE_TWO_MARKER" not in user_msg


def test_rank_files_malformed_item_treated_as_omitted(tmp_path):
    """Item with valid index but missing 'reason' → score=0, reason='(model omitted)'."""
    import importlib
    import delegate_server
    importlib.reload(delegate_server)

    f0 = tmp_path / "file0.txt"
    f1 = tmp_path / "file1.txt"
    f0.write_text("content of file zero")
    f1.write_text("content of file one")

    paths = [str(f0), str(f1)]

    fake_client = MagicMock()
    # Second item has score but is missing 'reason' → should be treated as omitted
    fake_client.chat.completions.create.return_value = _fake_completion(
        '{"rankings": ['
        '{"index": 0, "score": 7, "reason": "ok"},'
        '{"index": 1, "score": 5}'
        ']}'
    )

    with patch.object(delegate_server, "_client", return_value=fake_client):
        result = delegate_server.rank_files(query="test query", paths=paths)

    result_by_path = {item["path"]: item for item in result}

    # Well-formed item: normal score and reason
    assert result_by_path[str(f0)]["score"] == 7
    assert result_by_path[str(f0)]["reason"] == "ok"

    # Malformed item (missing 'reason'): treated as omitted
    assert result_by_path[str(f1)]["score"] == 0
    assert result_by_path[str(f1)]["reason"] == "(model omitted)"
