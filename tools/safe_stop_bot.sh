#!/usr/bin/env bash
set -euo pipefail

MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${MAIN_DIR}"

# shellcheck source=/dev/null
source "${MAIN_DIR}/tools/safe_common.sh"

FORCE_KILL=0
TIMEOUT_SEC=20

while (($#)); do
  case "$1" in
    --force-kill)
      FORCE_KILL=1
      ;;
    --timeout-sec)
      shift
      TIMEOUT_SEC="${1:-}"
      ;;
    *)
      echo "[ERROR] unknown option: $1" >&2
      echo "usage: $0 [--force-kill] [--timeout-sec N]" >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! "${TIMEOUT_SEC}" =~ ^[0-9]+$ ]]; then
  echo "[FAIL] timeout-sec must be integer seconds" >&2
  exit 2
fi

LOCK_DIR="${MAIN_DIR}/.run_lock"
PID_MAIN="$(safe_lock_pid "${LOCK_DIR}")"

if ! safe_pid_alive "${PID_MAIN}"; then
  safe_clear_stale_lock "${LOCK_DIR}"
  echo "[INFO] main bot is not running."
  exit 0
fi

echo "[RUN] stop bot pid=${PID_MAIN} (SIGTERM)"
kill -TERM "${PID_MAIN}" 2>/dev/null || true

for _ in $(seq 1 "${TIMEOUT_SEC}"); do
  if ! safe_pid_alive "${PID_MAIN}"; then
    safe_clear_stale_lock "${LOCK_DIR}"
    echo "[OK] bot stopped."
    exit 0
  fi
  sleep 1
done

if [[ "${FORCE_KILL}" == "1" ]]; then
  echo "[WARN] still alive after ${TIMEOUT_SEC}s. sending SIGKILL pid=${PID_MAIN}"
  kill -KILL "${PID_MAIN}" 2>/dev/null || true
  sleep 0.5
  if safe_pid_alive "${PID_MAIN}"; then
    echo "[FAIL] failed to kill pid=${PID_MAIN}" >&2
    exit 5
  fi
  safe_clear_stale_lock "${LOCK_DIR}"
  echo "[OK] bot stopped with SIGKILL."
  exit 0
fi

echo "[FAIL] bot still alive after ${TIMEOUT_SEC}s. retry with --force-kill if needed." >&2
exit 4
