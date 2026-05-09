#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO"
SANDBOX="$PROJECT_DIR/lm-studio-sandbox"
LOG_DIR="$HOME/.local/state/llama-mcp"
UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}"

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR"

# Per-server start helper. Pass extra env via leading args before the command
# (uses `env` so the assignments are parsed at runtime, not by the shell).
start_one() {
  local name="$1"; shift
  local port="$1"; shift
  local script="$1"; shift
  local pidfile="$LOG_DIR/$name.pid"
  local logfile="$LOG_DIR/$name.log"

  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "[$name] already running (pid $(cat "$pidfile"))"
    return
  fi

  env \
    MCP_TRANSPORT=http \
    MCP_HOST=127.0.0.1 \
    MCP_PORT="$port" \
    LM_MCP_ROOT="$SANDBOX" \
    "$@" \
    "$UV_BIN" run --script "$script" >"$logfile" 2>&1 &
  echo $! > "$pidfile"
  echo "[$name] started on :$port (pid $!), log: $logfile"
}

start_one lm-fs   8089 "$PROJECT_DIR/server.py"
start_one lm-web  8090 "$PROJECT_DIR/web_server.py" \
  LM_WEB_BACKEND=auto SEARXNG_URL=http://127.0.0.1:8080
start_one lm-xlsx 8091 "$PROJECT_DIR/xlsx_server.py"
start_one lm-pdf  8092 "$PROJECT_DIR/pdf_server.py" \
  LM_PDF_INLINE_RENDER="${LM_PDF_INLINE_RENDER:-0}"

echo
echo "All MCP servers started. Endpoints:"
echo "  lm-fs   : http://127.0.0.1:8089/mcp"
echo "  lm-web  : http://127.0.0.1:8090/mcp"
echo "  lm-xlsx : http://127.0.0.1:8091/mcp"
echo "  lm-pdf  : http://127.0.0.1:8092/mcp"
echo
echo "Stop with: ./stop-mcp-http.sh"
