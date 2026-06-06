#!/usr/bin/env bash
set -euo pipefail

MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BOT_UNIT="${BOT_UNIT:-ouroboros-bot.service}"
DASH_UNIT="${DASH_UNIT:-ouroboros-dashboard.service}"
SHADOW_UNIT="${SHADOW_UNIT:-ouroboros-shadow.service}"
MR_OBSERVE_UNIT="${MR_OBSERVE_UNIT:-ouroboros-mr-observe.service}"
NGROK_UNIT="${NGROK_UNIT:-ouroboros-ngrok.service}"
NOTIFIER_TIMER_UNIT="${NOTIFIER_TIMER_UNIT:-ouroboros-trade-notifier.timer}"
WEEKLY_TIMER_UNIT="${WEEKLY_TIMER_UNIT:-ouroboros-weekly-autotrain.timer}"
DAILY_TIMER_UNIT="${DAILY_TIMER_UNIT:-ouroboros-daily-autotrain.timer}"
CHAMPION_TIMER_UNIT="${CHAMPION_TIMER_UNIT:-ouroboros-champion-gate.timer}"
CHAMPION_ROLLBACK_TIMER_UNIT="${CHAMPION_ROLLBACK_TIMER_UNIT:-ouroboros-champion-rollback.timer}"
DRIFT_WATCH_TIMER_UNIT="${DRIFT_WATCH_TIMER_UNIT:-ouroboros-drift-watch.timer}"
WIDGET_STATUS_UNIT="${WIDGET_STATUS_UNIT:-ouroboros-widget-status.service}"
SECRETS_ENV="${SECRETS_ENV:-/etc/ouroboros/secrets.env}"
RUN_PREFLIGHT=0
INCLUDE_NGROK=0
INCLUDE_SHADOW=0
INCLUDE_MR_OBSERVE=0
INCLUDE_TRADE_NOTIFIER=0
INCLUDE_WEEKLY_AUTOTRAIN=0
INCLUDE_DAILY_AUTOTRAIN=0
INCLUDE_CHAMPION_GATE=0
INCLUDE_CHAMPION_ROLLBACK=0
INCLUDE_DRIFT_WATCH=0
INCLUDE_WIDGET_STATUS=0

usage() {
  cat <<'EOF'
usage: cloud_systemd_healthcheck.sh [--run-preflight] [--include-ngrok] [--include-shadow] [--include-mr-observe] [--include-trade-notifier] [--include-weekly-autotrain] [--include-daily-autotrain] [--include-champion-gate] [--include-champion-rollback] [--include-drift-watch] [--include-widget-status]

Checks:
  - systemctl availability
  - unit active/enabled status
  - secrets env file existence and permission
  - optional: python3 tools/live_preflight.py
  - optional: ngrok service active/enabled status
  - optional: shadow service active/enabled status
  - optional: MR observe service active/enabled status
  - optional: trade notifier timer active/enabled status
  - optional: weekly autotrain timer active/enabled status
  - optional: daily autotrain timer active/enabled status
  - optional: champion gate timer active/enabled status
  - optional: champion rollback timer active/enabled status
  - optional: drift watch timer active/enabled status
  - optional: widget status service active/enabled status

Environment override:
  BOT_UNIT, DASH_UNIT, SHADOW_UNIT, MR_OBSERVE_UNIT, NGROK_UNIT, NOTIFIER_TIMER_UNIT, WEEKLY_TIMER_UNIT, DAILY_TIMER_UNIT, CHAMPION_TIMER_UNIT, CHAMPION_ROLLBACK_TIMER_UNIT, DRIFT_WATCH_TIMER_UNIT, WIDGET_STATUS_UNIT, SECRETS_ENV
EOF
}

while (($#)); do
  case "$1" in
    --run-preflight)
      RUN_PREFLIGHT=1
      ;;
    --include-ngrok)
      INCLUDE_NGROK=1
      ;;
    --include-shadow)
      INCLUDE_SHADOW=1
      ;;
    --include-mr-observe)
      INCLUDE_MR_OBSERVE=1
      ;;
    --include-trade-notifier)
      INCLUDE_TRADE_NOTIFIER=1
      ;;
    --include-weekly-autotrain)
      INCLUDE_WEEKLY_AUTOTRAIN=1
      ;;
    --include-daily-autotrain)
      INCLUDE_DAILY_AUTOTRAIN=1
      ;;
    --include-champion-gate)
      INCLUDE_CHAMPION_GATE=1
      ;;
    --include-champion-rollback)
      INCLUDE_CHAMPION_ROLLBACK=1
      ;;
    --include-drift-watch)
      INCLUDE_DRIFT_WATCH=1
      ;;
    --include-widget-status)
      INCLUDE_WIDGET_STATUS=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[FAIL] unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if ! command -v systemctl >/dev/null 2>&1; then
  echo "[FAIL] systemctl not found. run this on Linux VM with systemd." >&2
  exit 3
fi

check_unit() {
  local unit="$1"
  local active enabled
  active="$(systemctl is-active "${unit}" 2>/dev/null || true)"
  if [[ "${active}" == "activating" ]]; then
    # Give services a short warm-up window right after enable/restart.
    for _ in $(seq 1 10); do
      sleep 1
      active="$(systemctl is-active "${unit}" 2>/dev/null || true)"
      if [[ "${active}" == "active" ]]; then
        break
      fi
    done
  fi
  enabled="$(systemctl is-enabled "${unit}" 2>/dev/null || true)"
  echo "[CHECK] unit=${unit} active=${active:-unknown} enabled=${enabled:-unknown}"
  if [[ "${active}" != "active" ]]; then
    echo "[FAIL] ${unit} is not active" >&2
    return 1
  fi
  if [[ "${enabled}" != "enabled" ]]; then
    echo "[WARN] ${unit} is not enabled (won't auto start after reboot)"
  fi
  return 0
}

check_secret_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "[FAIL] secrets file not found: ${path}" >&2
    return 1
  fi
  local mode
  mode="$(stat -c '%a' "${path}" 2>/dev/null || true)"
  echo "[CHECK] secrets file=${path} mode=${mode:-unknown}"
  if [[ -n "${mode}" ]]; then
    # require owner-only read/write at most
    if [[ "${mode}" -gt 600 ]]; then
      echo "[WARN] secrets file permission is broad (${mode}). recommend: chmod 600 ${path}"
    fi
  fi
  return 0
}

load_secret_env_if_exists() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    return 0
  fi
  if [[ -r "${path}" ]]; then
    # shellcheck disable=SC1090
    set -a
    . "${path}"
    set +a
    echo "[INFO] loaded secrets env: ${path}"
    return 0
  fi
  echo "[INFO] secrets env is not readable by current user: ${path}"
  return 0
}

run_preflight() {
  local main_dir="$1"
  local secrets_path="$2"
  if [[ -f "${secrets_path}" && -r "${secrets_path}" ]]; then
    (
      cd "${main_dir}"
      python3 tools/live_preflight.py
    )
    return 0
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo bash -lc "
set -euo pipefail
if [[ -f '${secrets_path}' ]]; then
  set -a
  . '${secrets_path}'
  set +a
fi
cd '${main_dir}'
python3 tools/live_preflight.py
"
    return 0
  fi

  echo "[FAIL] cannot run preflight with secrets: file not readable and sudo unavailable." >&2
  return 1
}

echo "[INFO] cloud systemd healthcheck"
echo "[INFO] main_dir=${MAIN_DIR}"

check_unit "${BOT_UNIT}"
check_unit "${DASH_UNIT}"
if [[ "${INCLUDE_SHADOW}" == "1" ]]; then
  check_unit "${SHADOW_UNIT}"
fi
if [[ "${INCLUDE_MR_OBSERVE}" == "1" ]]; then
  check_unit "${MR_OBSERVE_UNIT}"
fi
if [[ "${INCLUDE_NGROK}" == "1" ]]; then
  check_unit "${NGROK_UNIT}"
fi
if [[ "${INCLUDE_TRADE_NOTIFIER}" == "1" ]]; then
  check_unit "${NOTIFIER_TIMER_UNIT}"
fi
if [[ "${INCLUDE_WEEKLY_AUTOTRAIN}" == "1" ]]; then
  check_unit "${WEEKLY_TIMER_UNIT}"
fi
if [[ "${INCLUDE_DAILY_AUTOTRAIN}" == "1" ]]; then
  check_unit "${DAILY_TIMER_UNIT}"
fi
if [[ "${INCLUDE_CHAMPION_GATE}" == "1" ]]; then
  check_unit "${CHAMPION_TIMER_UNIT}"
fi
if [[ "${INCLUDE_CHAMPION_ROLLBACK}" == "1" ]]; then
  check_unit "${CHAMPION_ROLLBACK_TIMER_UNIT}"
fi
if [[ "${INCLUDE_DRIFT_WATCH}" == "1" ]]; then
  check_unit "${DRIFT_WATCH_TIMER_UNIT}"
fi
if [[ "${INCLUDE_WIDGET_STATUS}" == "1" ]]; then
  check_unit "${WIDGET_STATUS_UNIT}"
fi
check_secret_file "${SECRETS_ENV}"
load_secret_env_if_exists "${SECRETS_ENV}"

if [[ "${RUN_PREFLIGHT}" == "1" ]]; then
  echo "[RUN] python3 tools/live_preflight.py"
  run_preflight "${MAIN_DIR}" "${SECRETS_ENV}"
fi

echo "[OK] cloud systemd healthcheck completed"
