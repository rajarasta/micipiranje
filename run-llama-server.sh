#!/usr/bin/env bash
# Foreground launcher for llama-server with Qwen3.5-9B + WebUI MCP proxy.
# Stop with Ctrl+C. MCP servers must be started separately via ./start-mcp-http.sh.

set -euo pipefail

LLAMA_BIN="${LLAMA_BIN:-/home/josip-rastocic/llama/latest/build/bin/llama-server}"
MODEL_DIR="/media/josip-rastocic/DrugiDisk/Programi/LM STUDIO/modeli/.lmstudio/models/lmstudio-community"
MODEL="${MODEL:-$MODEL_DIR/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf}"
# Multimodal projector — same dir as MODEL, enables vision input (image tokens
# from MCP ImageContent, PDF page renders, pasted images in WebUI). 880 MB BF16.
MMPROJ="${MMPROJ:-$MODEL_DIR/Qwen3.5-9B-GGUF/mmproj-Qwen3.5-9B-BF16.gguf}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8033}"
# Qwen3.5-9B is a hybrid SSM + attention model (full_attention_interval=4),
# native ctx 262144 (256k). Only ~25% of layers carry full KV cache, so
# at 80k Q8_0 the KV cache is ~1.4 GB (not the ~5 GB a dense model would need).
# Measured fit on RTX 5070 Ti (16 GB): model 4.8 + ctx 1.4 + compute 0.5 ≈ 6.7 GB.
CTX_SIZE="${CTX_SIZE:-81920}"    # 80 * 1024
N_GPU_LAYERS="${N_GPU_LAYERS:-99}"
KV_CACHE_TYPE="${KV_CACHE_TYPE:-q8_0}"
N_PARALLEL="${N_PARALLEL:-1}"

if [[ ! -x "$LLAMA_BIN" ]]; then
  echo "llama-server not found or not executable: $LLAMA_BIN" >&2
  exit 1
fi
if [[ ! -f "$MODEL" ]]; then
  echo "Model file not found: $MODEL" >&2
  exit 1
fi
if [[ ! -f "$MMPROJ" ]]; then
  echo "WARNING: mmproj file not found: $MMPROJ" >&2
  echo "Vision input will be disabled. Set MMPROJ='' to silence this warning." >&2
  MMPROJ=""
fi

echo "Model     : $MODEL"
[[ -n "$MMPROJ" ]] && echo "MMProj    : $MMPROJ"
echo "Endpoint  : http://$HOST:$PORT/  (WebUI + OpenAI API)"
echo "Context   : $CTX_SIZE tokens (parallel slots: $N_PARALLEL)"
echo "GPU layers: $N_GPU_LAYERS"
echo "KV cache  : $KV_CACHE_TYPE (flash attention on)"
echo

mmproj_args=()
[[ -n "$MMPROJ" ]] && mmproj_args=(--mmproj "$MMPROJ")

exec "$LLAMA_BIN" \
  --model "$MODEL" \
  "${mmproj_args[@]}" \
  --host "$HOST" \
  --port "$PORT" \
  --n-gpu-layers "$N_GPU_LAYERS" \
  --ctx-size "$CTX_SIZE" \
  --parallel "$N_PARALLEL" \
  --flash-attn on \
  --cache-type-k "$KV_CACHE_TYPE" \
  --cache-type-v "$KV_CACHE_TYPE" \
  --jinja \
  --webui-mcp-proxy \
  --threads "$(nproc)"
