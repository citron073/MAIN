#!/usr/bin/env bash
set -euo pipefail

MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${MAIN_DIR}"

# shellcheck source=/dev/null
source "${MAIN_DIR}/tools/safe_common.sh"

NO_BACKUP=0
SKIP_RUN_CHECK=0
SKIP_LIVE_PREFLIGHT=0

while (($#)); do
  case "$1" in
    --no-backup)
      NO_BACKUP=1
      ;;
    --skip-run-check)
      SKIP_RUN_CHECK=1
      ;;
    --skip-live-preflight)
      SKIP_LIVE_PREFLIGHT=1
      ;;
    *)
      echo "[ERROR] unknown option: $1" >&2
      echo "usage: $0 [--no-backup] [--skip-run-check] [--skip-live-preflight]" >&2
      exit 2
      ;;
  esac
  shift
done

eval "$(safe_control_export "${MAIN_DIR}/CONTROL.csv")"

echo "[CHECK] control: paper_mode=${PAPER_MODE} live_enabled=${LIVE_ENABLED} today_on=${TODAY_ON} trade_enabled=${TRADE_ENABLED} observe_only=${OBSERVE_ONLY} safety_hard_block=${SAFETY_HARD_BLOCK}"
echo "[CHECK] risk: daily_loss_limit_pct=${DAILY_LOSS_LIMIT_PCT}"

if [[ "${DAILY_LOSS_VALID}" != "1" ]]; then
  echo "[FAIL] daily_loss_limit_pct must be negative. fix CONTROL.csv before start." >&2
  exit 3
fi

if [[ "${NO_BACKUP}" != "1" ]]; then
  TS="$(date +%Y%m%d_%H%M%S)"
  BACKUP_DIR="${MAIN_DIR}/backups/safe_guard_${TS}"
  mkdir -p "${BACKUP_DIR}"
  for p in CONTROL.csv CONTROL_shadow.csv state.json state_shadow.json; do
    if [[ -f "${MAIN_DIR}/${p}" ]]; then
      cp -p "${MAIN_DIR}/${p}" "${BACKUP_DIR}/${p}"
    fi
  done
  echo "[OK] backup: ${BACKUP_DIR}"
fi

safe_clear_stale_lock "${MAIN_DIR}/.run_lock"

echo "[RUN] py_compile core files"
python3 -m py_compile \
  bot.py \
  run.py \
  daily_report.py \
  audit.py \
  dashboard.py \
  spec_check.py \
  exchange/bitflyer_private.py \
  tools/keychain_secret.py \
  tools/live_preflight.py
echo "[OK] py_compile"

if [[ "${SKIP_RUN_CHECK}" != "1" ]]; then
  echo "[RUN] ./run_check.sh"
  ./run_check.sh
  echo "[OK] run_check"
else
  echo "[SKIP] run_check"
fi

if [[ "${LIVE_CANDIDATE}" == "1" && "${SKIP_LIVE_PREFLIGHT}" != "1" ]]; then
  echo "[RUN] python3 tools/live_preflight.py"
  python3 tools/live_preflight.py
  echo "[OK] live_preflight"
elif [[ "${LIVE_CANDIDATE}" == "1" ]]; then
  echo "[SKIP] live_preflight (LIVE candidate)"
else
  echo "[INFO] live_preflight skipped (current mode is not LIVE candidate)."
fi

echo "[OK] safe_guard completed"
