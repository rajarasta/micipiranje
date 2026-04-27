#!/usr/bin/env bash
set -euo pipefail
exec uv run --with pytest --with pandas --with openpyxl --with xlrd --with rapidfuzz --with 'mcp>=1.2' pytest "$@"
