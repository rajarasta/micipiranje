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


def test_read_with_focus_live(tmp_path):
    import delegate_server

    lines = [
        "import math",
        "",
        "",
        "def add(a, b):",
        "    return a + b",
        "",
        "",
        "def subtract(a, b):",
        "    return a - b",
        "",
        "",
        "def compute_tax(amount, rate):",
        "    # Computes tax on amount using the provided rate.",
        "    return amount * rate",
        "",
        "",
        "def multiply(a, b):",
        "    return a * b",
        "",
        "",
        "def divide(a, b):",
        "    if b == 0:",
        "        raise ZeroDivisionError",
        "    return a / b",
        "",
        "",
        "def power(a, b):",
        "    return a ** b",
        "",
        "",
    ]
    path = tmp_path / "math_utils.py"
    path.write_text("\n".join(lines), encoding="utf-8")

    result = delegate_server.read_with_focus(
        path=str(path), focus="tax calculation", max_words=80
    )

    expected_total = len(path.read_text(encoding="utf-8").splitlines())
    assert result["range_unit"] == "lines"
    assert result["file_type"] == "python"
    assert result["total_units"] == expected_total

    file_lines = path.read_text(encoding="utf-8").splitlines()
    tax_line = next(
        i for i, line in enumerate(file_lines, start=1) if "def compute_tax" in line
    )
    assert any(
        start <= tax_line <= end for start, end in result["relevant_ranges"]
    ), f"no range covers compute_tax at line {tax_line}: {result['relevant_ranges']}"

    summary_lower = result["summary"].lower()
    assert "tax" in summary_lower or "porez" in summary_lower


def test_rank_files_live(tmp_path):
    import delegate_server

    http_file = tmp_path / "http_server.py"
    http_file.write_text(
        "from http.server import HTTPServer, BaseHTTPRequestHandler\n"
        "\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200)\n"
        "        self.end_headers()\n"
        "        self.wfile.write(b'hello')\n"
        "\n"
        "def main():\n"
        "    server = HTTPServer(('127.0.0.1', 8080), Handler)\n"
        "    server.serve_forever()\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )

    tax_file = tmp_path / "tax_calc.py"
    tax_file.write_text(
        "def compute_vat(amount, rate=0.25):\n"
        "    return amount * rate\n"
        "\n"
        "def apply_discount(amount, pct):\n"
        "    return amount * (1 - pct / 100)\n"
        "\n"
        "def total_with_tax(items, rate):\n"
        "    return sum(items) * (1 + rate)\n",
        encoding="utf-8",
    )

    utils_file = tmp_path / "string_utils.py"
    utils_file.write_text(
        "def slugify(s):\n"
        "    return s.lower().replace(' ', '-')\n"
        "\n"
        "def truncate(s, n):\n"
        "    return s[:n] + '...' if len(s) > n else s\n"
        "\n"
        "def reverse(s):\n"
        "    return s[::-1]\n",
        encoding="utf-8",
    )

    paths = [str(tax_file), str(utils_file), str(http_file)]
    result = delegate_server.rank_files(query="HTTP server setup", paths=paths)

    assert len(result) == 3
    assert result[0]["path"] == str(http_file), (
        f"expected HTTP server file at top, got: {result}"
    )
