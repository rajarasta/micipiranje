#!/usr/bin/env bash
set -euo pipefail
exec uv run --with pytest --with pandas --with openpyxl --with xlrd --with rapidfuzz --with 'mcp>=1.2' --with 'openai>=1.40' --with 'pymupdf>=1.24' --with 'pdfplumber>=0.11' --with 'pytesseract>=0.3.10' --with 'Pillow>=10.0' pytest "$@"
