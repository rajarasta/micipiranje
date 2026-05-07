#!/usr/bin/env bash
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
    for _ in 1 2 3 4 5; do
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

stop_server lm-fs
stop_server lm-web
stop_server lm-xlsx
stop_server lm-pdf
