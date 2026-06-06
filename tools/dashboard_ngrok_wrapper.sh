#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
STARTER="${MAIN_DIR}/tools/start_dashboard_ngrok.sh"

RESTART_DELAY_SEC="${RESTART_DELAY_SEC:-5}"
MAX_RESTARTS="${MAX_RESTARTS:-0}"   # 0 = infinite
ONESHOT="${ONESHOT:-0}"              # 1 = run once

LOG_DIR="${MAIN_DIR}/ci_logs"
WRAP_LOG="${WRAP_LOG:-${LOG_DIR}/dashboard_ngrok_wrapper.log}"

mkdir -p "${LOG_DIR}"

if [[ ! -x "${STARTER}" ]]; then
  echo "[FAIL] starter not executable: ${STARTER}" >&2
  exit 2
fi

CHILD_PID=""

cleanup() {
  local code=$?
  if [[ -n "${CHILD_PID}" ]]; then
    kill "${CHILD_PID}" >/dev/null 2>&1 || true
    wait "${CHILD_PID}" >/dev/null 2>&1 || true
  fi
  exit "${code}"
}
trap cleanup INT TERM EXIT

restart_count=0

echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] wrapper start" | tee -a "${WRAP_LOG}"

auto_loop() {
  while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] launching start_dashboard_ngrok.sh" | tee -a "${WRAP_LOG}"

    "${STARTER}" >>"${WRAP_LOG}" 2>&1 &
    CHILD_PID=$!
    wait "${CHILD_PID}"
    rc=$?
    CHILD_PID=""

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN] starter exited rc=${rc}" | tee -a "${WRAP_LOG}"

    if [[ "${ONESHOT}" == "1" ]]; then
      return "${rc}"
    fi

    restart_count=$((restart_count + 1))
    if [[ "${MAX_RESTARTS}" != "0" && ${restart_count} -ge ${MAX_RESTARTS} ]]; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN] reached MAX_RESTARTS=${MAX_RESTARTS}" | tee -a "${WRAP_LOG}"
      return 0
    fi

    sleep "${RESTART_DELAY_SEC}"
  done
}

auto_loop
