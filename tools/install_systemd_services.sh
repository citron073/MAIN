#!/usr/bin/env bash
set -euo pipefail

MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BOT_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-bot.service"
DASH_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-dashboard.service"
SHADOW_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-shadow.service"
MR_OBSERVE_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-mr-observe.service"
NGROK_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-ngrok.service"
NOTIFIER_SERVICE_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-trade-notifier.service"
NOTIFIER_TIMER_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-trade-notifier.timer"
WEEKLY_SERVICE_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-weekly-autotrain.service"
WEEKLY_TIMER_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-weekly-autotrain.timer"
DAILY_SERVICE_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-daily-autotrain.service"
DAILY_TIMER_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-daily-autotrain.timer"
CHAMPION_SERVICE_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-champion-gate.service"
CHAMPION_TIMER_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-champion-gate.timer"
CHAMPION_ROLLBACK_SERVICE_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-champion-rollback.service"
CHAMPION_ROLLBACK_TIMER_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-champion-rollback.timer"
DRIFT_WATCH_SERVICE_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-drift-watch.service"
DRIFT_WATCH_TIMER_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-drift-watch.timer"
WIDGET_STATUS_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-widget-status.service"
MORNING_START_SERVICE_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-morning-start-check.service"
MORNING_START_TIMER_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-morning-start-check.timer"
AUDIT_SERVICE_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-audit.service"
AUDIT_TIMER_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-audit.timer"
AUDIT_WEEKLY_SERVICE_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-audit-weekly.service"
AUDIT_WEEKLY_TIMER_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-audit-weekly.timer"
STATE_BACKUP_SERVICE_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-state-backup.service"
STATE_BACKUP_TIMER_SRC="${MAIN_DIR}/deploy/systemd/ouroboros-state-backup.timer"
BOT_UNIT="ouroboros-bot.service"
DASH_UNIT="ouroboros-dashboard.service"
SHADOW_UNIT="ouroboros-shadow.service"
MR_OBSERVE_UNIT="ouroboros-mr-observe.service"
NGROK_UNIT="ouroboros-ngrok.service"
NOTIFIER_SERVICE_UNIT="ouroboros-trade-notifier.service"
NOTIFIER_TIMER_UNIT="ouroboros-trade-notifier.timer"
WEEKLY_SERVICE_UNIT="ouroboros-weekly-autotrain.service"
WEEKLY_TIMER_UNIT="ouroboros-weekly-autotrain.timer"
DAILY_SERVICE_UNIT="ouroboros-daily-autotrain.service"
DAILY_TIMER_UNIT="ouroboros-daily-autotrain.timer"
CHAMPION_SERVICE_UNIT="ouroboros-champion-gate.service"
CHAMPION_TIMER_UNIT="ouroboros-champion-gate.timer"
CHAMPION_ROLLBACK_SERVICE_UNIT="ouroboros-champion-rollback.service"
CHAMPION_ROLLBACK_TIMER_UNIT="ouroboros-champion-rollback.timer"
DRIFT_WATCH_SERVICE_UNIT="ouroboros-drift-watch.service"
DRIFT_WATCH_TIMER_UNIT="ouroboros-drift-watch.timer"
WIDGET_STATUS_UNIT="ouroboros-widget-status.service"
MORNING_START_SERVICE_UNIT="ouroboros-morning-start-check.service"
MORNING_START_TIMER_UNIT="ouroboros-morning-start-check.timer"
AUDIT_SERVICE_UNIT="ouroboros-audit.service"
AUDIT_TIMER_UNIT="ouroboros-audit.timer"
AUDIT_WEEKLY_SERVICE_UNIT="ouroboros-audit-weekly.service"
AUDIT_WEEKLY_TIMER_UNIT="ouroboros-audit-weekly.timer"
STATE_BACKUP_SERVICE_UNIT="ouroboros-state-backup.service"
STATE_BACKUP_TIMER_UNIT="ouroboros-state-backup.timer"
WITH_NGROK=0
WITH_SHADOW=0
WITH_MR_OBSERVE=0
WITH_TRADE_NOTIFIER=0
WITH_WEEKLY_AUTOTRAIN=0
WITH_DAILY_AUTOTRAIN=0
WITH_CHAMPION_GATE=0
WITH_CHAMPION_ROLLBACK=0
WITH_DRIFT_WATCH=0
WITH_WIDGET_STATUS=0
WITH_MORNING_START_CHECK=0
WITH_AUDIT=0
WITH_STATE_BACKUP=0

usage() {
  cat <<'EOF'
usage: install_systemd_services.sh [--with-ngrok] [--with-shadow] [--with-mr-observe] [--with-trade-notifier] [--with-weekly-autotrain] [--with-daily-autotrain] [--with-champion-gate] [--with-champion-rollback] [--with-drift-watch] [--with-widget-status] [--with-morning-start-check] [--with-audit] [--with-state-backup]

Install and enable systemd services for bot/dashboard.
Options:
  --with-ngrok            also install+enable ouroboros-ngrok.service
  --with-shadow           also install+enable ouroboros-shadow.service
  --with-mr-observe       also install+enable ouroboros-mr-observe.service
  --with-trade-notifier   also install+enable ouroboros-trade-notifier.timer
  --with-weekly-autotrain also install+enable ouroboros-weekly-autotrain.timer
  --with-daily-autotrain  also install+enable ouroboros-daily-autotrain.timer
  --with-champion-gate    also install+enable ouroboros-champion-gate.timer
  --with-champion-rollback also install+enable ouroboros-champion-rollback.timer
  --with-drift-watch      also install+enable ouroboros-drift-watch.timer
  --with-widget-status    also install+enable ouroboros-widget-status.service
  --with-morning-start-check also install+enable ouroboros-morning-start-check.timer
  --with-audit            also install+enable ouroboros-audit.timer + ouroboros-audit-weekly.timer (daily 01:30 / Mon 02:00)
  --with-state-backup     also install+enable ouroboros-state-backup.timer (daily 02:00)
EOF
}

while (($#)); do
  case "$1" in
    --with-ngrok)
      WITH_NGROK=1
      ;;
    --with-shadow)
      WITH_SHADOW=1
      ;;
    --with-mr-observe)
      WITH_MR_OBSERVE=1
      ;;
    --with-trade-notifier)
      WITH_TRADE_NOTIFIER=1
      ;;
    --with-weekly-autotrain)
      WITH_WEEKLY_AUTOTRAIN=1
      ;;
    --with-daily-autotrain)
      WITH_DAILY_AUTOTRAIN=1
      ;;
    --with-champion-gate)
      WITH_CHAMPION_GATE=1
      ;;
    --with-champion-rollback)
      WITH_CHAMPION_ROLLBACK=1
      ;;
    --with-drift-watch)
      WITH_DRIFT_WATCH=1
      ;;
    --with-widget-status)
      WITH_WIDGET_STATUS=1
      ;;
    --with-morning-start-check)
      WITH_MORNING_START_CHECK=1
      ;;
    --with-audit)
      WITH_AUDIT=1
      ;;
    --with-state-backup)
      WITH_STATE_BACKUP=1
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

if [[ ! -f "${BOT_SRC}" || ! -f "${DASH_SRC}" ]]; then
  echo "[FAIL] service template not found under deploy/systemd" >&2
  exit 3
fi
if [[ "${WITH_NGROK}" == "1" && ! -f "${NGROK_SRC}" ]]; then
  echo "[FAIL] ngrok service template not found: ${NGROK_SRC}" >&2
  exit 4
fi
if [[ "${WITH_SHADOW}" == "1" && ! -f "${SHADOW_SRC}" ]]; then
  echo "[FAIL] shadow service template not found: ${SHADOW_SRC}" >&2
  exit 12
fi
if [[ "${WITH_MR_OBSERVE}" == "1" && ! -f "${MR_OBSERVE_SRC}" ]]; then
  echo "[FAIL] mr observe service template not found: ${MR_OBSERVE_SRC}" >&2
  exit 27
fi
if [[ "${WITH_TRADE_NOTIFIER}" == "1" ]]; then
  if [[ ! -f "${NOTIFIER_SERVICE_SRC}" ]]; then
    echo "[FAIL] trade notifier service template not found: ${NOTIFIER_SERVICE_SRC}" >&2
    exit 8
  fi
  if [[ ! -f "${NOTIFIER_TIMER_SRC}" ]]; then
    echo "[FAIL] trade notifier timer template not found: ${NOTIFIER_TIMER_SRC}" >&2
    exit 9
  fi
fi
if [[ "${WITH_WEEKLY_AUTOTRAIN}" == "1" ]]; then
  if [[ ! -f "${WEEKLY_SERVICE_SRC}" ]]; then
    echo "[FAIL] weekly autotrain service template not found: ${WEEKLY_SERVICE_SRC}" >&2
    exit 10
  fi
  if [[ ! -f "${WEEKLY_TIMER_SRC}" ]]; then
    echo "[FAIL] weekly autotrain timer template not found: ${WEEKLY_TIMER_SRC}" >&2
    exit 11
  fi
fi
if [[ "${WITH_DAILY_AUTOTRAIN}" == "1" ]]; then
  if [[ ! -f "${DAILY_SERVICE_SRC}" ]]; then
    echo "[FAIL] daily autotrain service template not found: ${DAILY_SERVICE_SRC}" >&2
    exit 13
  fi
  if [[ ! -f "${DAILY_TIMER_SRC}" ]]; then
    echo "[FAIL] daily autotrain timer template not found: ${DAILY_TIMER_SRC}" >&2
    exit 14
  fi
fi
if [[ "${WITH_CHAMPION_GATE}" == "1" ]]; then
  if [[ ! -f "${CHAMPION_SERVICE_SRC}" ]]; then
    echo "[FAIL] champion gate service template not found: ${CHAMPION_SERVICE_SRC}" >&2
    exit 15
  fi
  if [[ ! -f "${CHAMPION_TIMER_SRC}" ]]; then
    echo "[FAIL] champion gate timer template not found: ${CHAMPION_TIMER_SRC}" >&2
    exit 16
  fi
fi
if [[ "${WITH_CHAMPION_ROLLBACK}" == "1" ]]; then
  if [[ ! -f "${CHAMPION_ROLLBACK_SERVICE_SRC}" ]]; then
    echo "[FAIL] champion rollback service template not found: ${CHAMPION_ROLLBACK_SERVICE_SRC}" >&2
    exit 17
  fi
  if [[ ! -f "${CHAMPION_ROLLBACK_TIMER_SRC}" ]]; then
    echo "[FAIL] champion rollback timer template not found: ${CHAMPION_ROLLBACK_TIMER_SRC}" >&2
    exit 18
  fi
fi
if [[ "${WITH_DRIFT_WATCH}" == "1" ]]; then
  if [[ ! -f "${DRIFT_WATCH_SERVICE_SRC}" ]]; then
    echo "[FAIL] drift watch service template not found: ${DRIFT_WATCH_SERVICE_SRC}" >&2
    exit 19
  fi
  if [[ ! -f "${DRIFT_WATCH_TIMER_SRC}" ]]; then
    echo "[FAIL] drift watch timer template not found: ${DRIFT_WATCH_TIMER_SRC}" >&2
    exit 20
  fi
fi
if [[ "${WITH_WIDGET_STATUS}" == "1" && ! -f "${WIDGET_STATUS_SRC}" ]]; then
  echo "[FAIL] widget status service template not found: ${WIDGET_STATUS_SRC}" >&2
  exit 23
fi
if [[ "${WITH_MORNING_START_CHECK}" == "1" ]]; then
  if [[ ! -f "${MORNING_START_SERVICE_SRC}" ]]; then
    echo "[FAIL] morning start service template not found: ${MORNING_START_SERVICE_SRC}" >&2
    exit 25
  fi
  if [[ ! -f "${MORNING_START_TIMER_SRC}" ]]; then
    echo "[FAIL] morning start timer template not found: ${MORNING_START_TIMER_SRC}" >&2
    exit 26
  fi
fi
if [[ "${WITH_AUDIT}" == "1" ]]; then
  if [[ ! -f "${AUDIT_SERVICE_SRC}" ]]; then
    echo "[FAIL] audit service template not found: ${AUDIT_SERVICE_SRC}" >&2
    exit 28
  fi
  if [[ ! -f "${AUDIT_TIMER_SRC}" ]]; then
    echo "[FAIL] audit timer template not found: ${AUDIT_TIMER_SRC}" >&2
    exit 29
  fi
  if [[ ! -f "${AUDIT_WEEKLY_SERVICE_SRC}" ]]; then
    echo "[FAIL] audit-weekly service template not found: ${AUDIT_WEEKLY_SERVICE_SRC}" >&2
    exit 30
  fi
  if [[ ! -f "${AUDIT_WEEKLY_TIMER_SRC}" ]]; then
    echo "[FAIL] audit-weekly timer template not found: ${AUDIT_WEEKLY_TIMER_SRC}" >&2
    exit 31
  fi
fi
if [[ "${WITH_STATE_BACKUP}" == "1" ]]; then
  if [[ ! -f "${STATE_BACKUP_SERVICE_SRC}" ]]; then
    echo "[FAIL] state-backup service template not found: ${STATE_BACKUP_SERVICE_SRC}" >&2
    exit 32
  fi
  if [[ ! -f "${STATE_BACKUP_TIMER_SRC}" ]]; then
    echo "[FAIL] state-backup timer template not found: ${STATE_BACKUP_TIMER_SRC}" >&2
    exit 33
  fi
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "[FAIL] systemctl not found (Linux systemd required)." >&2
  exit 5
fi
if [[ "${WITH_NGROK}" == "1" && ! "$(command -v ngrok || true)" ]]; then
  echo "[FAIL] ngrok command not found. install ngrok first, or run without --with-ngrok." >&2
  exit 6
fi

ME="$(whoami)"
MYHOME="${HOME}"
SUDO=""
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    echo "[FAIL] sudo not found and current user is not root." >&2
    exit 7
  fi
fi

tmp_bot="$(mktemp)"
tmp_dash="$(mktemp)"
tmp_shadow="$(mktemp)"
tmp_mr_observe="$(mktemp)"
tmp_ngrok="$(mktemp)"
tmp_notifier_service="$(mktemp)"
tmp_notifier_timer="$(mktemp)"
tmp_weekly_service="$(mktemp)"
tmp_weekly_timer="$(mktemp)"
tmp_daily_service="$(mktemp)"
tmp_daily_timer="$(mktemp)"
tmp_champion_service="$(mktemp)"
tmp_champion_timer="$(mktemp)"
tmp_champion_rollback_service="$(mktemp)"
tmp_champion_rollback_timer="$(mktemp)"
tmp_drift_watch_service="$(mktemp)"
tmp_drift_watch_timer="$(mktemp)"
tmp_widget_status="$(mktemp)"
tmp_morning_start_service="$(mktemp)"
tmp_morning_start_timer="$(mktemp)"
tmp_audit_service="$(mktemp)"
tmp_audit_timer="$(mktemp)"
tmp_audit_weekly_service="$(mktemp)"
tmp_audit_weekly_timer="$(mktemp)"
tmp_state_backup_service="$(mktemp)"
tmp_state_backup_timer="$(mktemp)"
cleanup() {
  rm -f "${tmp_bot}" "${tmp_dash}" "${tmp_shadow}" "${tmp_mr_observe}" "${tmp_ngrok}" "${tmp_notifier_service}" "${tmp_notifier_timer}" "${tmp_weekly_service}" "${tmp_weekly_timer}" "${tmp_daily_service}" "${tmp_daily_timer}" "${tmp_champion_service}" "${tmp_champion_timer}" "${tmp_champion_rollback_service}" "${tmp_champion_rollback_timer}" "${tmp_drift_watch_service}" "${tmp_drift_watch_timer}" "${tmp_widget_status}" "${tmp_morning_start_service}" "${tmp_morning_start_timer}" "${tmp_audit_service}" "${tmp_audit_timer}" "${tmp_audit_weekly_service}" "${tmp_audit_weekly_timer}" "${tmp_state_backup_service}" "${tmp_state_backup_timer}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

render_unit() {
  local src="$1"
  local dst="$2"
  sed -E \
    -e "s|^User=.*|User=${ME}|g" \
    -e "s|/home/ubuntu/trading_bot/trading_bot/MAIN|${MAIN_DIR}|g" \
    -e "s|/home/ubuntu/trading_bot/MAIN|${MAIN_DIR}|g" \
    -e "s|/home/ubuntu|${MYHOME}|g" \
    "${src}" > "${dst}"
}

render_unit "${BOT_SRC}" "${tmp_bot}"
render_unit "${DASH_SRC}" "${tmp_dash}"
if [[ "${WITH_SHADOW}" == "1" ]]; then
  render_unit "${SHADOW_SRC}" "${tmp_shadow}"
fi
if [[ "${WITH_MR_OBSERVE}" == "1" ]]; then
  render_unit "${MR_OBSERVE_SRC}" "${tmp_mr_observe}"
fi
if [[ "${WITH_NGROK}" == "1" ]]; then
  render_unit "${NGROK_SRC}" "${tmp_ngrok}"
fi
if [[ "${WITH_TRADE_NOTIFIER}" == "1" ]]; then
  render_unit "${NOTIFIER_SERVICE_SRC}" "${tmp_notifier_service}"
  render_unit "${NOTIFIER_TIMER_SRC}" "${tmp_notifier_timer}"
fi
if [[ "${WITH_WEEKLY_AUTOTRAIN}" == "1" ]]; then
  render_unit "${WEEKLY_SERVICE_SRC}" "${tmp_weekly_service}"
  render_unit "${WEEKLY_TIMER_SRC}" "${tmp_weekly_timer}"
fi
if [[ "${WITH_DAILY_AUTOTRAIN}" == "1" ]]; then
  render_unit "${DAILY_SERVICE_SRC}" "${tmp_daily_service}"
  render_unit "${DAILY_TIMER_SRC}" "${tmp_daily_timer}"
fi
if [[ "${WITH_CHAMPION_GATE}" == "1" ]]; then
  render_unit "${CHAMPION_SERVICE_SRC}" "${tmp_champion_service}"
  render_unit "${CHAMPION_TIMER_SRC}" "${tmp_champion_timer}"
fi
if [[ "${WITH_CHAMPION_ROLLBACK}" == "1" ]]; then
  render_unit "${CHAMPION_ROLLBACK_SERVICE_SRC}" "${tmp_champion_rollback_service}"
  render_unit "${CHAMPION_ROLLBACK_TIMER_SRC}" "${tmp_champion_rollback_timer}"
fi
if [[ "${WITH_DRIFT_WATCH}" == "1" ]]; then
  render_unit "${DRIFT_WATCH_SERVICE_SRC}" "${tmp_drift_watch_service}"
  render_unit "${DRIFT_WATCH_TIMER_SRC}" "${tmp_drift_watch_timer}"
fi
if [[ "${WITH_WIDGET_STATUS}" == "1" ]]; then
  render_unit "${WIDGET_STATUS_SRC}" "${tmp_widget_status}"
fi
if [[ "${WITH_MORNING_START_CHECK}" == "1" ]]; then
  render_unit "${MORNING_START_SERVICE_SRC}" "${tmp_morning_start_service}"
  render_unit "${MORNING_START_TIMER_SRC}" "${tmp_morning_start_timer}"
fi
if [[ "${WITH_AUDIT}" == "1" ]]; then
  render_unit "${AUDIT_SERVICE_SRC}" "${tmp_audit_service}"
  render_unit "${AUDIT_TIMER_SRC}" "${tmp_audit_timer}"
  render_unit "${AUDIT_WEEKLY_SERVICE_SRC}" "${tmp_audit_weekly_service}"
  render_unit "${AUDIT_WEEKLY_TIMER_SRC}" "${tmp_audit_weekly_timer}"
fi
if [[ "${WITH_STATE_BACKUP}" == "1" ]]; then
  render_unit "${STATE_BACKUP_SERVICE_SRC}" "${tmp_state_backup_service}"
  render_unit "${STATE_BACKUP_TIMER_SRC}" "${tmp_state_backup_timer}"
fi

validate_python_execstart_options() {
  local unit_path="$1"
  local unit_name="$2"
  local exec_line cmd
  exec_line="$(grep -E '^ExecStart=' "${unit_path}" | head -n 1 || true)"
  if [[ -z "${exec_line}" ]]; then
    return 0
  fi
  cmd="${exec_line#ExecStart=}"

  local -a argv
  read -r -a argv <<< "${cmd}"
  if [[ "${#argv[@]}" -lt 2 ]]; then
    return 0
  fi

  local exe_base
  exe_base="$(basename "${argv[0]}")"
  case "${exe_base}" in
    python|python3|python3.*|pypy|pypy3)
      ;;
    *)
      return 0
      ;;
  esac

  local script_idx=-1
  local i
  for i in "${!argv[@]}"; do
    if [[ "${argv[$i]}" == *.py ]]; then
      script_idx="${i}"
      break
    fi
  done
  if [[ "${script_idx}" -lt 0 ]]; then
    return 0
  fi

  local script_path="${argv[$script_idx]}"
  if [[ "${script_path}" != /* ]]; then
    script_path="${MAIN_DIR}/${script_path}"
  fi
  if [[ ! -f "${script_path}" ]]; then
    echo "[FAIL] ${unit_name}: script not found for validation: ${script_path}" >&2
    exit 21
  fi
  if [[ ! -x "${argv[0]}" ]]; then
    echo "[FAIL] ${unit_name}: interpreter not executable: ${argv[0]}" >&2
    exit 22
  fi

  local help_out
  if ! help_out="$("${argv[0]}" "${script_path}" --help 2>&1)"; then
    echo "[WARN] ${unit_name}: skip ExecStart option validation (--help failed)" >&2
    echo "[WARN] ${unit_name}: ${help_out}" >&2
    return 0
  fi

  local -A help_opts=()
  while IFS= read -r opt; do
    [[ -n "${opt}" ]] && help_opts["${opt}"]=1
  done < <(printf '%s\n' "${help_out}" | grep -oE -- '--[A-Za-z0-9][A-Za-z0-9-]*' | sort -u)

  if [[ "${#help_opts[@]}" -eq 0 ]]; then
    echo "[WARN] ${unit_name}: skip ExecStart option validation (no options found in --help)" >&2
    return 0
  fi

  local -a missing=()
  local tok opt
  for ((i=script_idx + 1; i<${#argv[@]}; i++)); do
    tok="${argv[$i]}"
    if [[ "${tok}" == --* ]]; then
      opt="${tok%%=*}"
      if [[ -z "${help_opts[$opt]:-}" ]]; then
        missing+=("${opt}")
      fi
    fi
  done

  if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "[FAIL] ${unit_name}: unsupported ExecStart options: ${missing[*]}" >&2
    exit 24
  fi

  echo "[OK] ${unit_name}: ExecStart options validated"
}

validate_python_execstart_options "${tmp_bot}" "${BOT_UNIT}"
if [[ "${WITH_SHADOW}" == "1" ]]; then
  validate_python_execstart_options "${tmp_shadow}" "${SHADOW_UNIT}"
fi
if [[ "${WITH_MR_OBSERVE}" == "1" ]]; then
  validate_python_execstart_options "${tmp_mr_observe}" "${MR_OBSERVE_UNIT}"
fi
if [[ "${WITH_TRADE_NOTIFIER}" == "1" ]]; then
  validate_python_execstart_options "${tmp_notifier_service}" "${NOTIFIER_SERVICE_UNIT}"
fi
if [[ "${WITH_WEEKLY_AUTOTRAIN}" == "1" ]]; then
  validate_python_execstart_options "${tmp_weekly_service}" "${WEEKLY_SERVICE_UNIT}"
fi
if [[ "${WITH_DAILY_AUTOTRAIN}" == "1" ]]; then
  validate_python_execstart_options "${tmp_daily_service}" "${DAILY_SERVICE_UNIT}"
fi
if [[ "${WITH_CHAMPION_GATE}" == "1" ]]; then
  validate_python_execstart_options "${tmp_champion_service}" "${CHAMPION_SERVICE_UNIT}"
fi
if [[ "${WITH_CHAMPION_ROLLBACK}" == "1" ]]; then
  validate_python_execstart_options "${tmp_champion_rollback_service}" "${CHAMPION_ROLLBACK_SERVICE_UNIT}"
fi
if [[ "${WITH_DRIFT_WATCH}" == "1" ]]; then
  validate_python_execstart_options "${tmp_drift_watch_service}" "${DRIFT_WATCH_SERVICE_UNIT}"
fi
if [[ "${WITH_MORNING_START_CHECK}" == "1" ]]; then
  validate_python_execstart_options "${tmp_morning_start_service}" "${MORNING_START_SERVICE_UNIT}"
fi

echo "[INFO] install units as user=${ME} home=${MYHOME}"
${SUDO} cp "${tmp_bot}" "/etc/systemd/system/${BOT_UNIT}"
${SUDO} cp "${tmp_dash}" "/etc/systemd/system/${DASH_UNIT}"
if [[ "${WITH_SHADOW}" == "1" ]]; then
  ${SUDO} cp "${tmp_shadow}" "/etc/systemd/system/${SHADOW_UNIT}"
fi
if [[ "${WITH_MR_OBSERVE}" == "1" ]]; then
  ${SUDO} cp "${tmp_mr_observe}" "/etc/systemd/system/${MR_OBSERVE_UNIT}"
fi
if [[ "${WITH_NGROK}" == "1" ]]; then
  ${SUDO} cp "${tmp_ngrok}" "/etc/systemd/system/${NGROK_UNIT}"
fi
if [[ "${WITH_TRADE_NOTIFIER}" == "1" ]]; then
  ${SUDO} cp "${tmp_notifier_service}" "/etc/systemd/system/${NOTIFIER_SERVICE_UNIT}"
  ${SUDO} cp "${tmp_notifier_timer}" "/etc/systemd/system/${NOTIFIER_TIMER_UNIT}"
fi
if [[ "${WITH_WEEKLY_AUTOTRAIN}" == "1" ]]; then
  ${SUDO} cp "${tmp_weekly_service}" "/etc/systemd/system/${WEEKLY_SERVICE_UNIT}"
  ${SUDO} cp "${tmp_weekly_timer}" "/etc/systemd/system/${WEEKLY_TIMER_UNIT}"
fi
if [[ "${WITH_DAILY_AUTOTRAIN}" == "1" ]]; then
  ${SUDO} cp "${tmp_daily_service}" "/etc/systemd/system/${DAILY_SERVICE_UNIT}"
  ${SUDO} cp "${tmp_daily_timer}" "/etc/systemd/system/${DAILY_TIMER_UNIT}"
fi
if [[ "${WITH_CHAMPION_GATE}" == "1" ]]; then
  ${SUDO} cp "${tmp_champion_service}" "/etc/systemd/system/${CHAMPION_SERVICE_UNIT}"
  ${SUDO} cp "${tmp_champion_timer}" "/etc/systemd/system/${CHAMPION_TIMER_UNIT}"
fi
if [[ "${WITH_CHAMPION_ROLLBACK}" == "1" ]]; then
  ${SUDO} cp "${tmp_champion_rollback_service}" "/etc/systemd/system/${CHAMPION_ROLLBACK_SERVICE_UNIT}"
  ${SUDO} cp "${tmp_champion_rollback_timer}" "/etc/systemd/system/${CHAMPION_ROLLBACK_TIMER_UNIT}"
fi
if [[ "${WITH_DRIFT_WATCH}" == "1" ]]; then
  ${SUDO} cp "${tmp_drift_watch_service}" "/etc/systemd/system/${DRIFT_WATCH_SERVICE_UNIT}"
  ${SUDO} cp "${tmp_drift_watch_timer}" "/etc/systemd/system/${DRIFT_WATCH_TIMER_UNIT}"
fi
if [[ "${WITH_WIDGET_STATUS}" == "1" ]]; then
  ${SUDO} cp "${tmp_widget_status}" "/etc/systemd/system/${WIDGET_STATUS_UNIT}"
fi
if [[ "${WITH_MORNING_START_CHECK}" == "1" ]]; then
  ${SUDO} cp "${tmp_morning_start_service}" "/etc/systemd/system/${MORNING_START_SERVICE_UNIT}"
  ${SUDO} cp "${tmp_morning_start_timer}" "/etc/systemd/system/${MORNING_START_TIMER_UNIT}"
fi
if [[ "${WITH_AUDIT}" == "1" ]]; then
  ${SUDO} cp "${tmp_audit_service}" "/etc/systemd/system/${AUDIT_SERVICE_UNIT}"
  ${SUDO} cp "${tmp_audit_timer}" "/etc/systemd/system/${AUDIT_TIMER_UNIT}"
  ${SUDO} cp "${tmp_audit_weekly_service}" "/etc/systemd/system/${AUDIT_WEEKLY_SERVICE_UNIT}"
  ${SUDO} cp "${tmp_audit_weekly_timer}" "/etc/systemd/system/${AUDIT_WEEKLY_TIMER_UNIT}"
fi
if [[ "${WITH_STATE_BACKUP}" == "1" ]]; then
  ${SUDO} cp "${tmp_state_backup_service}" "/etc/systemd/system/${STATE_BACKUP_SERVICE_UNIT}"
  ${SUDO} cp "${tmp_state_backup_timer}" "/etc/systemd/system/${STATE_BACKUP_TIMER_UNIT}"
fi
${SUDO} systemctl daemon-reload

units=("${BOT_UNIT}" "${DASH_UNIT}")
if [[ "${WITH_SHADOW}" == "1" ]]; then
  units+=("${SHADOW_UNIT}")
fi
if [[ "${WITH_MR_OBSERVE}" == "1" ]]; then
  units+=("${MR_OBSERVE_UNIT}")
fi
if [[ "${WITH_NGROK}" == "1" ]]; then
  units+=("${NGROK_UNIT}")
fi
if [[ "${WITH_WIDGET_STATUS}" == "1" ]]; then
  units+=("${WIDGET_STATUS_UNIT}")
fi
${SUDO} systemctl enable --now "${units[@]}"
if [[ "${WITH_TRADE_NOTIFIER}" == "1" ]]; then
  ${SUDO} systemctl enable --now "${NOTIFIER_TIMER_UNIT}"
  # Run once immediately so notification path can be verified.
  ${SUDO} systemctl start "${NOTIFIER_SERVICE_UNIT}" || true
fi
if [[ "${WITH_WEEKLY_AUTOTRAIN}" == "1" ]]; then
  ${SUDO} systemctl enable --now "${WEEKLY_TIMER_UNIT}"
  # Run once immediately so weekly feedback pipeline can be verified.
  ${SUDO} systemctl start "${WEEKLY_SERVICE_UNIT}" || true
fi
if [[ "${WITH_DAILY_AUTOTRAIN}" == "1" ]]; then
  ${SUDO} systemctl enable --now "${DAILY_TIMER_UNIT}"
  # Run once immediately so daily trigger path can be verified.
  ${SUDO} systemctl start "${DAILY_SERVICE_UNIT}" || true
fi
if [[ "${WITH_CHAMPION_GATE}" == "1" ]]; then
  ${SUDO} systemctl enable --now "${CHAMPION_TIMER_UNIT}"
  # Run once immediately so promote gate path can be verified.
  ${SUDO} systemctl start "${CHAMPION_SERVICE_UNIT}" || true
fi
if [[ "${WITH_CHAMPION_ROLLBACK}" == "1" ]]; then
  ${SUDO} systemctl enable --now "${CHAMPION_ROLLBACK_TIMER_UNIT}"
  # Run once immediately so rollback guard path can be verified.
  ${SUDO} systemctl start "${CHAMPION_ROLLBACK_SERVICE_UNIT}" || true
fi
if [[ "${WITH_DRIFT_WATCH}" == "1" ]]; then
  ${SUDO} systemctl enable --now "${DRIFT_WATCH_TIMER_UNIT}"
  # Run once immediately so drift watch path can be verified.
  ${SUDO} systemctl start "${DRIFT_WATCH_SERVICE_UNIT}" || true
fi
if [[ "${WITH_MORNING_START_CHECK}" == "1" ]]; then
  ${SUDO} systemctl enable --now "${MORNING_START_TIMER_UNIT}"
  # Run once immediately so morning start guard path can be verified.
  ${SUDO} systemctl start "${MORNING_START_SERVICE_UNIT}" || true
fi
if [[ "${WITH_AUDIT}" == "1" ]]; then
  ${SUDO} systemctl enable --now "${AUDIT_TIMER_UNIT}"
  ${SUDO} systemctl enable --now "${AUDIT_WEEKLY_TIMER_UNIT}"
fi
if [[ "${WITH_STATE_BACKUP}" == "1" ]]; then
  ${SUDO} systemctl enable --now "${STATE_BACKUP_TIMER_UNIT}"
fi

all_enabled=("${units[@]}")
if [[ "${WITH_TRADE_NOTIFIER}" == "1" ]]; then
  all_enabled+=("${NOTIFIER_TIMER_UNIT}")
fi
if [[ "${WITH_WEEKLY_AUTOTRAIN}" == "1" ]]; then
  all_enabled+=("${WEEKLY_TIMER_UNIT}")
fi
if [[ "${WITH_DAILY_AUTOTRAIN}" == "1" ]]; then
  all_enabled+=("${DAILY_TIMER_UNIT}")
fi
if [[ "${WITH_CHAMPION_GATE}" == "1" ]]; then
  all_enabled+=("${CHAMPION_TIMER_UNIT}")
fi
if [[ "${WITH_CHAMPION_ROLLBACK}" == "1" ]]; then
  all_enabled+=("${CHAMPION_ROLLBACK_TIMER_UNIT}")
fi
if [[ "${WITH_DRIFT_WATCH}" == "1" ]]; then
  all_enabled+=("${DRIFT_WATCH_TIMER_UNIT}")
fi
if [[ "${WITH_MORNING_START_CHECK}" == "1" ]]; then
  all_enabled+=("${MORNING_START_TIMER_UNIT}")
fi
if [[ "${WITH_AUDIT}" == "1" ]]; then
  all_enabled+=("${AUDIT_TIMER_UNIT}" "${AUDIT_WEEKLY_TIMER_UNIT}")
fi
if [[ "${WITH_STATE_BACKUP}" == "1" ]]; then
  all_enabled+=("${STATE_BACKUP_TIMER_UNIT}")
fi
echo "[OK] enabled: ${all_enabled[*]}"
echo "[NEXT] status check:"
echo "  ${SUDO:+sudo }systemctl status ${BOT_UNIT} --no-pager -l"
echo "  ${SUDO:+sudo }systemctl status ${DASH_UNIT} --no-pager -l"
if [[ "${WITH_SHADOW}" == "1" ]]; then
  echo "  ${SUDO:+sudo }systemctl status ${SHADOW_UNIT} --no-pager -l"
fi
if [[ "${WITH_NGROK}" == "1" ]]; then
  echo "  ${SUDO:+sudo }systemctl status ${NGROK_UNIT} --no-pager -l"
fi
if [[ "${WITH_WIDGET_STATUS}" == "1" ]]; then
  echo "  ${SUDO:+sudo }systemctl status ${WIDGET_STATUS_UNIT} --no-pager -l"
  echo "  ${SUDO:+sudo }journalctl -u ${WIDGET_STATUS_UNIT} -n 80 --no-pager"
fi
if [[ "${WITH_TRADE_NOTIFIER}" == "1" ]]; then
  echo "  ${SUDO:+sudo }systemctl status ${NOTIFIER_TIMER_UNIT} --no-pager -l"
  echo "  ${SUDO:+sudo }journalctl -u ${NOTIFIER_SERVICE_UNIT} -n 80 --no-pager"
fi
if [[ "${WITH_WEEKLY_AUTOTRAIN}" == "1" ]]; then
  echo "  ${SUDO:+sudo }systemctl status ${WEEKLY_TIMER_UNIT} --no-pager -l"
  echo "  ${SUDO:+sudo }journalctl -u ${WEEKLY_SERVICE_UNIT} -n 80 --no-pager"
fi
if [[ "${WITH_DAILY_AUTOTRAIN}" == "1" ]]; then
  echo "  ${SUDO:+sudo }systemctl status ${DAILY_TIMER_UNIT} --no-pager -l"
  echo "  ${SUDO:+sudo }journalctl -u ${DAILY_SERVICE_UNIT} -n 80 --no-pager"
fi
if [[ "${WITH_CHAMPION_GATE}" == "1" ]]; then
  echo "  ${SUDO:+sudo }systemctl status ${CHAMPION_TIMER_UNIT} --no-pager -l"
  echo "  ${SUDO:+sudo }journalctl -u ${CHAMPION_SERVICE_UNIT} -n 80 --no-pager"
fi
if [[ "${WITH_CHAMPION_ROLLBACK}" == "1" ]]; then
  echo "  ${SUDO:+sudo }systemctl status ${CHAMPION_ROLLBACK_TIMER_UNIT} --no-pager -l"
  echo "  ${SUDO:+sudo }journalctl -u ${CHAMPION_ROLLBACK_SERVICE_UNIT} -n 80 --no-pager"
fi
if [[ "${WITH_DRIFT_WATCH}" == "1" ]]; then
  echo "  ${SUDO:+sudo }systemctl status ${DRIFT_WATCH_TIMER_UNIT} --no-pager -l"
  echo "  ${SUDO:+sudo }journalctl -u ${DRIFT_WATCH_SERVICE_UNIT} -n 80 --no-pager"
fi
if [[ "${WITH_MORNING_START_CHECK}" == "1" ]]; then
  echo "  ${SUDO:+sudo }systemctl status ${MORNING_START_TIMER_UNIT} --no-pager -l"
  echo "  ${SUDO:+sudo }journalctl -u ${MORNING_START_SERVICE_UNIT} -n 80 --no-pager"
fi
if [[ "${WITH_AUDIT}" == "1" ]]; then
  echo "  ${SUDO:+sudo }systemctl status ${AUDIT_TIMER_UNIT} --no-pager -l"
  echo "  ${SUDO:+sudo }systemctl status ${AUDIT_WEEKLY_TIMER_UNIT} --no-pager -l"
  echo "  ${SUDO:+sudo }journalctl -u ${AUDIT_SERVICE_UNIT} -n 40 --no-pager"
fi
if [[ "${WITH_STATE_BACKUP}" == "1" ]]; then
  echo "  ${SUDO:+sudo }systemctl status ${STATE_BACKUP_TIMER_UNIT} --no-pager -l"
  echo "  ${SUDO:+sudo }journalctl -u ${STATE_BACKUP_SERVICE_UNIT} -n 40 --no-pager"
fi
