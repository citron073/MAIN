#!/usr/bin/env bash
set -euo pipefail

MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONTROL_FILE="${MAIN_DIR}/CONTROL_mr_observe.csv"
LOCK_DIR="${MAIN_DIR}/.run_lock_mr_observe"
LOG_FILE="${MAIN_DIR}/run_mr_observe.log"
INTERVAL="${1:-300}"

if [[ ! "${INTERVAL}" =~ ^[0-9]+$ ]]; then
  echo "[ERROR] interval must be integer seconds (example: 300)" >&2
  exit 2
fi

if [[ ! -f "${CONTROL_FILE}" ]]; then
  echo "[FAIL] control file not found: ${CONTROL_FILE}" >&2
  exit 3
fi

if [[ -f "${LOCK_DIR}/lockinfo.txt" ]]; then
  PID="$(awk -F= '/^pid=/{print $2}' "${LOCK_DIR}/lockinfo.txt" | tr -d '[:space:]' || true)"
  if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
    echo "[INFO] MR observe runner already running (pid=${PID})"
    exit 0
  fi
fi

echo "[INFO] starting MR observe runner"
echo "[INFO] control: ${CONTROL_FILE}"
echo "[INFO] logs: ${MAIN_DIR}/../logs/instances/mr_observe"
echo "[INFO] run log: ${LOG_FILE}"

(
  export OUROBOROS_INSTANCE="mr_observe"
  export OUROBOROS_CONTROL_PATH="${CONTROL_FILE}"
  export OUROBOROS_RUN_LOCK_PATH="${LOCK_DIR}"
  nohup python3 "${MAIN_DIR}/run.py" --interval "${INTERVAL}" --print-tick >> "${LOG_FILE}" 2>&1 &
  echo "[OK] MR observe started pid=$!"
)
