#!/usr/bin/env bash
# Audit which aux/delegate calls fired during a given Hermes session.
#
# Usage:
#   ./audit-session.sh                    # most recent session
#   ./audit-session.sh <session-id>       # specific session (e.g. 20260511_232356_b11ff8)
#
# Reports: tool calls per slot, aux-text/vision POST counts, lm-delegate
# tool invocations vs handshakes, token totals where available.

set -uo pipefail

SESSION_DIR="$HOME/.hermes/sessions"
LOG_DIR="$HOME/.local/state/llama-mcp"

SESSION_ID="${1:-}"
if [[ -z "$SESSION_ID" ]]; then
  SESSION_FILE=$(ls -t "$SESSION_DIR"/session_*.json 2>/dev/null | head -1)
  SESSION_ID=$(basename "$SESSION_FILE" .json | sed 's/^session_//')
else
  SESSION_FILE="$SESSION_DIR/session_${SESSION_ID}.json"
fi

if [[ ! -f "$SESSION_FILE" ]]; then
  echo "Session file not found: $SESSION_FILE"
  exit 1
fi

echo "=== Session $SESSION_ID ==="
~/.local/bin/uv run python3 << PY
import json, collections
data = json.load(open("$SESSION_FILE"))
msgs = data.get("messages", [])
print(f"Title       : {data.get('title') or '(untitled)'}")
print(f"Model       : {data.get('model')}")
print(f"Started     : {data.get('session_start')}")
print(f"Messages    : {len(msgs)}")

tool_calls = collections.Counter()
delegate_calls = []
for m in msgs:
    if not isinstance(m, dict):
        continue
    for tc in (m.get("tool_calls") or []):
        fn = (tc.get("function") or {}).get("name") or tc.get("name") or "<?>"
        tool_calls[fn] += 1
        if fn in {"quick_classify", "extract_json", "summarize_chunk", "session_search", "vision_analyze", "web_extract"}:
            args = (tc.get("function") or {}).get("arguments") or ""
            delegate_calls.append((fn, str(args)[:80]))

print()
print("Tool calls (all):")
for fn, n in tool_calls.most_common():
    print(f"  {n:3d}  {fn}")

print()
print(f"Explicit delegate/aux tool invocations: {len(delegate_calls)}")
for fn, args in delegate_calls:
    print(f"  {fn:20s} {args}")
PY

echo
echo "=== Aux endpoint traffic (llama-server logs) ==="
for log in aux-text aux-vision; do
  f="$LOG_DIR/$log.log"
  [[ -f "$f" ]] || { echo "$log: log missing"; continue; }
  count=$(grep -c "POST /v1/chat/completions.*200" "$f" 2>/dev/null; true)
  echo "$log : ${count:-0} POST /v1/chat/completions"
done

echo
echo "=== lm-delegate MCP traffic ==="
f="$LOG_DIR/lm-delegate.log"
if [[ -f "$f" ]]; then
  echo "  ListToolsRequest (discovery, not actual calls): $(grep -c 'ListToolsRequest' "$f")"
  echo "  CallToolRequest  (actual quick_classify/etc.) : $(grep -c 'CallToolRequest'  "$f")"
fi

echo
echo "=== Per-call timings on aux-text (most recent 5) ==="
grep -E "prompt eval time|^ +eval time|total time" "$LOG_DIR/aux-text.log" 2>/dev/null | tail -15

echo
echo "Tip: for full prompt content, restart llama-server with --verbose"
echo "(very noisy; only enable when actively debugging quality issues)"
