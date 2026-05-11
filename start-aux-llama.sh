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
    --ctx-size 65536 \
    --parallel 1 \
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
