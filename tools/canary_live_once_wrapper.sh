#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CANARY_SCRIPT="${MAIN_DIR}/tools/canary_live_window_test.sh"
CI_LOG_DIR="${MAIN_DIR}/ci_logs"

TARGET_DATE=""
DURATION_SEC=600
INTERVAL_SEC=60
LOT=""
LABEL=""
PLIST_PATH=""

usage() {
  cat <<'USAGE'
Usage:
  ./tools/canary_live_once_wrapper.sh \
    --target-date YYYY-MM-DD \
    --label com.ouroboros.canary.once \
    --plist-path /Users/<you>/Library/LaunchAgents/com.ouroboros.canary.once.plist \
    [--duration-sec N] [--interval-sec N] [--lot BTC]
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-date)
      TARGET_DATE="$2"
      shift 2
      ;;
    --duration-sec)
      DURATION_SEC="$2"
      shift 2
      ;;
    --interval-sec)
      INTERVAL_SEC="$2"
      shift 2
      ;;
    --lot)
      LOT="$2"
      shift 2
      ;;
    --label)
      LABEL="$2"
      shift 2
      ;;
    --plist-path)
      PLIST_PATH="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[FAIL] unknown arg: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${TARGET_DATE}" || -z "${LABEL}" || -z "${PLIST_PATH}" ]]; then
  echo "[FAIL] required args missing" >&2
  usage
  exit 2
fi
if [[ ! -x "${CANARY_SCRIPT}" ]]; then
  echo "[FAIL] executable not found: ${CANARY_SCRIPT}" >&2
  exit 3
fi

mkdir -p "${CI_LOG_DIR}"
LOG_FILE="${CI_LOG_DIR}/canary_once_$(date +%Y%m%d).log"
exec >> "${LOG_FILE}" 2>&1

echo "[WRAPPER] start at $(date '+%Y-%m-%d %H:%M:%S')"
echo "[WRAPPER] target_date=${TARGET_DATE} label=${LABEL}"

TODAY="$(date +%Y-%m-%d)"
if [[ "${TODAY}" != "${TARGET_DATE}" ]]; then
  echo "[WRAPPER] skip: today=${TODAY} != target_date=${TARGET_DATE}"
  exit 0
fi

MARKER="${CI_LOG_DIR}/.canary_once_done_${TARGET_DATE}"
if [[ -f "${MARKER}" ]]; then
  echo "[WRAPPER] already done marker exists: ${MARKER}"
  exit 0
fi

set +e
if [[ -n "${LOT}" ]]; then
  "${CANARY_SCRIPT}" --duration-sec "${DURATION_SEC}" --interval-sec "${INTERVAL_SEC}" --lot "${LOT}"
else
  "${CANARY_SCRIPT}" --duration-sec "${DURATION_SEC}" --interval-sec "${INTERVAL_SEC}"
fi
RC=$?
set -e

echo "rc=${RC} done_at=$(date '+%Y-%m-%d %H:%M:%S')" > "${MARKER}"
echo "[WRAPPER] canary script exit rc=${RC}"

if command -v launchctl >/dev/null 2>&1; then
  UID_NUM="$(id -u)"
  launchctl bootout "gui/${UID_NUM}" "${PLIST_PATH}" >/dev/null 2>&1 || launchctl unload "${PLIST_PATH}" >/dev/null 2>&1 || true
fi
rm -f "${PLIST_PATH}" || true

echo "[WRAPPER] unloaded and removed plist: ${PLIST_PATH}"
exit "${RC}"
