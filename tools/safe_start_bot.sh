#!/usr/bin/env bash
set -euo pipefail

MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${MAIN_DIR}"

# shellcheck source=/dev/null
source "${MAIN_DIR}/tools/safe_common.sh"

INTERVAL="${INTERVAL:-300}"
ALLOW_LIVE=0
SKIP_GUARD=0
SKIP_RUN_CHECK=0
PRINT_TICK=0

while (($#)); do
  case "$1" in
    --interval)
      shift
      INTERVAL="${1:-}"
      ;;
    --allow-live)
      ALLOW_LIVE=1
      ;;
    --skip-guard)
      SKIP_GUARD=1
      ;;
    --skip-run-check)
      SKIP_RUN_CHECK=1
      ;;
    --print-tick)
      PRINT_TICK=1
      ;;
    *)
      echo "[ERROR] unknown option: $1" >&2
      echo "usage: $0 [--interval N] [--allow-live] [--skip-guard] [--skip-run-check] [--print-tick]" >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! "${INTERVAL}" =~ ^[0-9]+$ ]]; then
  echo "[FAIL] interval must be integer seconds" >&2
  exit 2
fi

LOCK_DIR="${MAIN_DIR}/.run_lock"
RUN_LOG="${MAIN_DIR}/run.log"

PID_EXISTING="$(safe_lock_pid "${LOCK_DIR}")"
if safe_pid_alive "${PID_EXISTING}"; then
  echo "[INFO] bot already running (pid=${PID_EXISTING})"
  exit 0
fi

if [[ "${SKIP_GUARD}" != "1" ]]; then
  if [[ "${SKIP_RUN_CHECK}" == "1" ]]; then
    "${MAIN_DIR}/tools/safe_guard.sh" --skip-run-check
  else
    "${MAIN_DIR}/tools/safe_guard.sh"
  fi
else
  echo "[WARN] safe_guard skipped by --skip-guard"
fi

eval "$(safe_control_export "${MAIN_DIR}/CONTROL.csv")"
if [[ "${LIVE_CANDIDATE}" == "1" && "${ALLOW_LIVE}" != "1" ]]; then
  echo "[FAIL] LIVE candidate mode detected. add --allow-live to prevent accidental live start." >&2
  exit 4
fi

safe_clear_stale_lock "${LOCK_DIR}"

RUN_CMD=(python3 "${MAIN_DIR}/run.py" --interval "${INTERVAL}")
if [[ "${PRINT_TICK}" == "1" ]]; then
  RUN_CMD+=(--print-tick)
fi

echo "[RUN] nohup ${RUN_CMD[*]}"
nohup "${RUN_CMD[@]}" >> "${RUN_LOG}" 2>&1 &
NEW_PID="$!"
sleep 1
if ! kill -0 "${NEW_PID}" 2>/dev/null; then
  echo "[FAIL] runner process exited immediately. check ${RUN_LOG}" >&2
  exit 5
fi

for _ in $(seq 1 20); do
  PID_LOCK="$(safe_lock_pid "${LOCK_DIR}")"
  if safe_pid_alive "${PID_LOCK}"; then
    echo "[OK] bot started pid=${PID_LOCK} (run.py pid=${NEW_PID})"
    echo "[OK] run log: ${RUN_LOG}"
    exit 0
  fi
  sleep 0.2
done

echo "[WARN] process started (pid=${NEW_PID}) but lock file is not ready yet."
echo "[WARN] check run log: ${RUN_LOG}"
