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
