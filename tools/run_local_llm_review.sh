#!/usr/bin/env bash
set -euo pipefail

MAIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${MAIN_DIR}"

DAY8="${1:-${DAY8:-}}"
LOCAL_LLM_MODE="${LOCAL_LLM_MODE:-auto}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:1.5b}"
OLLAMA_FALLBACK_MODELS="${OLLAMA_FALLBACK_MODELS:-qwen2.5:0.5b,qwen2.5:1.5b,llama3.2:1b}"
OLLAMA_TIMEOUT_SEC="${OLLAMA_TIMEOUT_SEC:-45}"
OLLAMA_NUM_PREDICT="${OLLAMA_NUM_PREDICT:-280}"

echo "[INFO] local LLM review runner"
echo "[INFO] mode=local-only; VM writes/service restarts are not performed"
echo "[INFO] day8=${DAY8:-latest}"

python3 tools/local_llm_healthcheck.py \
  --base-url "${OLLAMA_BASE_URL}" \
  --model "${OLLAMA_MODEL}" \
  --fallback-models "${OLLAMA_FALLBACK_MODELS}" \
  --timeout-sec 5 || true

if [[ -n "${DAY8}" ]]; then
  ./tools/sync_vm_llm_inputs.sh "${DAY8}"
else
  ./tools/sync_vm_llm_inputs.sh
fi

ARGS=(
  --snapshot-dir .local_llm/vm_snapshot/latest
  --llm-mode "${LOCAL_LLM_MODE}"
  --ollama-base-url "${OLLAMA_BASE_URL}"
  --ollama-model "${OLLAMA_MODEL}"
  --ollama-fallback-models "${OLLAMA_FALLBACK_MODELS}"
  --timeout-sec "${OLLAMA_TIMEOUT_SEC}"
  --num-predict "${OLLAMA_NUM_PREDICT}"
)
if [[ -n "${DAY8}" ]]; then
  ARGS+=(--day8 "${DAY8}")
fi

python3 tools/local_llm_trade_review.py "${ARGS[@]}"
