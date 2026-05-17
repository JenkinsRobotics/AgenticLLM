#!/usr/bin/env bash
# Start a local OpenAI-compatible server for the Gemma 4 26B-A4B model so
# hermes-agent (which expects an OpenAI-wire endpoint) can drive it 100%
# offline. Uses llama-cpp-python's built-in server module — same Llama
# instance our other three frameworks load in-process, just exposed over
# HTTP for hermes-agent.
#
# Port 11435 is chosen to avoid clashes with Ollama (11434) and LM Studio (1234).
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${HERMES_LLM_PORT:-11435}"
MODEL_PATH="${HERMES_LLM_MODEL:-/Users/jonathanjenkins/.lmstudio/models/lmstudio-community/gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf}"
# hermes-agent's built-in system prompt + tool schema runs ~12-14K tokens
# before the user prompt is appended. 32K leaves room on Gemma 4 (262K train).
N_CTX="${HERMES_LLM_CTX:-32768}"
GPU_LAYERS="${HERMES_LLM_GPU_LAYERS:--1}"

if [ ! -f "$MODEL_PATH" ]; then
  echo "Model file not found: $MODEL_PATH" >&2
  echo "Set HERMES_LLM_MODEL=/path/to/model.gguf and re-run." >&2
  exit 1
fi

echo "[hermes-llm] Serving $(basename "$MODEL_PATH") on http://127.0.0.1:${PORT}/v1"
exec .venv/bin/python -m llama_cpp.server \
  --model "$MODEL_PATH" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --n_ctx "$N_CTX" \
  --n_gpu_layers "$GPU_LAYERS" \
  --model_alias gemma-4-26b-a4b
  # Intentionally NO --chat_format: the hardcoded "gemma" template is
  # for Gemma 1/2 and corrupts Gemma 4 output. llama-cpp-python reads
  # the GGUF's embedded template, which is the right one for Gemma 4.
