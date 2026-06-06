#!/usr/bin/env bash
set -euo pipefail

MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOCK_DIR="${MAIN_DIR}/.run_lock_mr_observe"
INFO="${LOCK_DIR}/lockinfo.txt"

if [[ ! -f "${INFO}" ]]; then
  echo "[INFO] lockinfo not found: ${INFO}"
  exit 0
fi

PID="$(awk -F= '/^pid=/{print $2}' "${INFO}" | tr -d '[:space:]' || true)"
if [[ -z "${PID}" ]]; then
  echo "[WARN] pid not found in ${INFO}"
  exit 0
fi

if ! kill -0 "${PID}" 2>/dev/null; then
  echo "[INFO] pid=${PID} is already stopped"
  exit 0
fi

echo "[INFO] stopping MR observe runner pid=${PID}"
kill -INT "${PID}" 2>/dev/null || true
sleep 1
if kill -0 "${PID}" 2>/dev/null; then
  kill -TERM "${PID}" 2>/dev/null || true
  sleep 1
fi
if kill -0 "${PID}" 2>/dev/null; then
  kill -KILL "${PID}" 2>/dev/null || true
fi

if kill -0 "${PID}" 2>/dev/null; then
  echo "[WARN] failed to stop pid=${PID}"
  exit 1
fi

echo "[OK] MR observe runner stopped"
