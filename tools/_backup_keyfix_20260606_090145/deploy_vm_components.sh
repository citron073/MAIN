#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MAIN_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

HOST=""
USER_NAME="ubuntu"
KEY_PATH=""
REMOTE_MAIN="/home/ubuntu/trading_bot/MAIN"
REMOTE_MAIN_EXPLICIT=0

WITH_DRIFT_WATCH=0
WITH_WEEKLY_AUTOTRAIN=0
WITH_TRADE_NOTIFIER=0
WITH_WIDGET_STATUS=0
WITH_MORNING_START_CHECK=0
WITH_MR_OBSERVE=0
WITH_ALL_CORE=0

usage() {
  cat <<'EOF'
usage: deploy_vm_components.sh --host <host-or-ip> [options]

options:
  --host HOST                VM host or IP (required)
  --user USER                SSH user (default: ubuntu)
  --key PATH                 SSH private key path (optional)
  --remote-main PATH         Remote MAIN directory (optional; auto-detects ~/trading_bot/MAIN then ~/trading_bot/trading_bot/MAIN)
  --with-drift-watch         Deploy drift watch tool + service + timer
  --with-weekly-autotrain    Deploy weekly auto feedback tool + service + timer
  --with-trade-notifier      Deploy trade notifier tool + service + timer
  --with-widget-status       Deploy widget status scripts + systemd service
  --with-morning-start-check Deploy morning pre-open safety check + systemd timer
  --with-mr-observe         Deploy MR observe-only instance files + systemd service
  --all-core                 Same as: --with-drift-watch --with-weekly-autotrain --with-trade-notifier
  -h, --help                 Show help

example:
  ./tools/deploy_vm_components.sh \
    --host 161.33.26.35 \
    --key ~/Downloads/ssh-key-2026-03-04-4.key \
    --with-drift-watch --with-weekly-autotrain
EOF
}

while (($#)); do
  case "$1" in
    --host)
      shift
      HOST="${1:-}"
      ;;
    --user)
      shift
      USER_NAME="${1:-}"
      ;;
    --key)
      shift
      KEY_PATH="${1:-}"
      ;;
    --remote-main)
      shift
      REMOTE_MAIN="${1:-}"
      REMOTE_MAIN_EXPLICIT=1
      ;;
    --with-drift-watch)
      WITH_DRIFT_WATCH=1
      ;;
    --with-weekly-autotrain)
      WITH_WEEKLY_AUTOTRAIN=1
      ;;
    --with-trade-notifier)
      WITH_TRADE_NOTIFIER=1
      ;;
    --with-widget-status)
      WITH_WIDGET_STATUS=1
      ;;
    --with-morning-start-check)
      WITH_MORNING_START_CHECK=1
      ;;
    --with-mr-observe)
      WITH_MR_OBSERVE=1
      ;;
    --all-core)
      WITH_ALL_CORE=1
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

if [[ -z "${HOST}" ]]; then
  echo "[FAIL] --host is required" >&2
  usage >&2
  exit 2
fi

if [[ "${WITH_ALL_CORE}" == "1" ]]; then
  WITH_DRIFT_WATCH=1
  WITH_WEEKLY_AUTOTRAIN=1
  WITH_TRADE_NOTIFIER=1
fi

if [[ "${WITH_DRIFT_WATCH}" != "1" && "${WITH_WEEKLY_AUTOTRAIN}" != "1" && "${WITH_TRADE_NOTIFIER}" != "1" && "${WITH_WIDGET_STATUS}" != "1" && "${WITH_MORNING_START_CHECK}" != "1" && "${WITH_MR_OBSERVE}" != "1" ]]; then
  echo "[FAIL] select at least one component flag (or --all-core)" >&2
  usage >&2
  exit 2
fi

if [[ -n "${KEY_PATH}" ]]; then
  KEY_PATH="${KEY_PATH/#\~/${HOME}}"
fi

SSH_OPTS=(-o IdentitiesOnly=yes)
if [[ -n "${KEY_PATH}" ]]; then
  SSH_OPTS+=(-i "${KEY_PATH}")
fi

run_ssh() {
  ssh "${SSH_OPTS[@]}" "$@"
}

run_scp() {
  scp "${SSH_OPTS[@]}" "$@"
}

REMOTE="${USER_NAME}@${HOST}"

if [[ "${REMOTE_MAIN_EXPLICIT}" != "1" ]]; then
  detected_main="$(run_ssh "${REMOTE}" "bash -lc 'for c in \"\$HOME/trading_bot/MAIN\" \"\$HOME/trading_bot/trading_bot/MAIN\"; do if [[ -f \"\$c/dashboard.py\" || -f \"\$c/run.py\" ]]; then printf \"%s\" \"\$c\"; exit 0; fi; done'")"
  if [[ -n "${detected_main}" ]]; then
    REMOTE_MAIN="${detected_main}"
  fi
fi

echo "[INFO] local MAIN=${MAIN_DIR}"
echo "[INFO] remote=${REMOTE}:${REMOTE_MAIN}"

declare -a COPY_FILES=()
declare -a COPY_DIRS=()
declare -a INSTALL_FLAGS=()
declare -a COMPILE_FILES=()
declare -a RESTART_TIMERS=()
declare -a START_SERVICES=()
declare -a JOURNAL_UNITS=()

if [[ "${WITH_DRIFT_WATCH}" == "1" ]]; then
  COPY_FILES+=(
    "tools/market_drift_watch.py"
    "deploy/systemd/ouroboros-drift-watch.service"
    "deploy/systemd/ouroboros-drift-watch.timer"
  )
  INSTALL_FLAGS+=("--with-drift-watch")
  COMPILE_FILES+=("tools/market_drift_watch.py")
  RESTART_TIMERS+=("ouroboros-drift-watch.timer")
  START_SERVICES+=("ouroboros-drift-watch.service")
  JOURNAL_UNITS+=("ouroboros-drift-watch.service")
fi

if [[ "${WITH_WEEKLY_AUTOTRAIN}" == "1" ]]; then
  COPY_FILES+=(
    "tools/weekly_auto_feedback.py"
    "deploy/systemd/ouroboros-weekly-autotrain.service"
    "deploy/systemd/ouroboros-weekly-autotrain.timer"
  )
  INSTALL_FLAGS+=("--with-weekly-autotrain")
  COMPILE_FILES+=("tools/weekly_auto_feedback.py")
  RESTART_TIMERS+=("ouroboros-weekly-autotrain.timer")
  START_SERVICES+=("ouroboros-weekly-autotrain.service")
  JOURNAL_UNITS+=("ouroboros-weekly-autotrain.service")
fi

if [[ "${WITH_TRADE_NOTIFIER}" == "1" ]]; then
  COPY_FILES+=(
    "tools/drift_resume_summary.py"
    "tools/apply_daily_reflection.py"
    "tools/trade_event_notifier.py"
    "deploy/systemd/ouroboros-trade-notifier.service"
    "deploy/systemd/ouroboros-trade-notifier.timer"
  )
  INSTALL_FLAGS+=("--with-trade-notifier")
  COMPILE_FILES+=("tools/drift_resume_summary.py" "tools/apply_daily_reflection.py" "tools/trade_event_notifier.py")
  RESTART_TIMERS+=("ouroboros-trade-notifier.timer")
  START_SERVICES+=("ouroboros-trade-notifier.service")
  JOURNAL_UNITS+=("ouroboros-trade-notifier.service")
fi

if [[ "${WITH_WIDGET_STATUS}" == "1" ]]; then
  COPY_FILES+=(
    "tools/drift_resume_summary.py"
    "tools/widget_status.py"
    "tools/start_widget_status_server.sh"
    "deploy/systemd/ouroboros-widget-status.service"
    "WIDGETS.md"
    "widget/scriptable/OuroborosWidget.js"
    "widget/swiftbar/ouroboros.1m.sh"
  )
  COPY_DIRS+=(
    "widget/react_portfolio"
  )
  INSTALL_FLAGS+=("--with-widget-status")
  COMPILE_FILES+=("tools/drift_resume_summary.py" "tools/widget_status.py")
  START_SERVICES+=("ouroboros-widget-status.service")
  JOURNAL_UNITS+=("ouroboros-widget-status.service")
fi

if [[ "${WITH_MORNING_START_CHECK}" == "1" ]]; then
  COPY_FILES+=(
    "tools/drift_resume_summary.py"
    "tools/morning_start_guard.py"
    "tools/live_preflight.py"
    "tools/keychain_secret.py"
    "deploy/systemd/ouroboros-morning-start-check.service"
    "deploy/systemd/ouroboros-morning-start-check.timer"
  )
  INSTALL_FLAGS+=("--with-morning-start-check")
  COMPILE_FILES+=("tools/drift_resume_summary.py" "tools/morning_start_guard.py" "tools/live_preflight.py")
  RESTART_TIMERS+=("ouroboros-morning-start-check.timer")
  START_SERVICES+=("ouroboros-morning-start-check.service")
  JOURNAL_UNITS+=("ouroboros-morning-start-check.service")
fi

if [[ "${WITH_MR_OBSERVE}" == "1" ]]; then
  COPY_FILES+=(
    "bot.py"
    "run.py"
    "CONTROL_mr_observe.csv"
    "tools/start_mr_observe.sh"
    "tools/stop_mr_observe.sh"
    "deploy/systemd/ouroboros-mr-observe.service"
  )
  INSTALL_FLAGS+=("--with-mr-observe")
  COMPILE_FILES+=("bot.py")
  START_SERVICES+=("ouroboros-mr-observe.service")
  JOURNAL_UNITS+=("ouroboros-mr-observe.service")
fi

if [[ "${#INSTALL_FLAGS[@]}" -gt 0 ]]; then
  COPY_FILES+=(
    "tools/install_systemd_services.sh"
    "deploy/systemd/ouroboros-bot.service"
    "deploy/systemd/ouroboros-dashboard.service"
  )
fi

for rel in "${COPY_FILES[@]}"; do
  src="${MAIN_DIR}/${rel}"
  if [[ ! -f "${src}" ]]; then
    echo "[FAIL] local file not found: ${src}" >&2
    exit 3
  fi
done
for rel in "${COPY_DIRS[@]}"; do
  src="${MAIN_DIR}/${rel}"
  if [[ ! -d "${src}" ]]; then
    echo "[FAIL] local directory not found: ${src}" >&2
    exit 3
  fi
done

echo "[RUN] ensure remote directories"
run_ssh "${REMOTE}" "mkdir -p '${REMOTE_MAIN}/tools' '${REMOTE_MAIN}/deploy/systemd' '${REMOTE_MAIN}/widget/scriptable' '${REMOTE_MAIN}/widget/swiftbar' '${REMOTE_MAIN}/widget'"

echo "[RUN] upload component files"
for rel in "${COPY_FILES[@]}"; do
  src="${MAIN_DIR}/${rel}"
  dst="${REMOTE}:${REMOTE_MAIN}/${rel}"
  echo "  - ${rel}"
  run_scp "${src}" "${dst}"
done
for rel in "${COPY_DIRS[@]}"; do
  src="${MAIN_DIR}/${rel}"
  dst="${REMOTE}:${REMOTE_MAIN}/$(dirname "${rel}")/"
  echo "  - ${rel}/"
  run_scp -r "${src}" "${dst}"
done

INSTALL_FLAGS_STR="${INSTALL_FLAGS[*]-}"
COMPILE_FILES_STR="${COMPILE_FILES[*]-}"
RESTART_TIMERS_STR="${RESTART_TIMERS[*]-}"
START_SERVICES_STR="${START_SERVICES[*]-}"
JOURNAL_UNITS_STR="${JOURNAL_UNITS[*]-}"

echo "[RUN] remote install/reload/restart/check"
run_ssh -t "${REMOTE}" "bash -s -- '${REMOTE_MAIN}' '${INSTALL_FLAGS_STR}' '${COMPILE_FILES_STR}' '${RESTART_TIMERS_STR}' '${START_SERVICES_STR}' '${JOURNAL_UNITS_STR}'" <<'EOS'
set -euo pipefail

REMOTE_MAIN="$1"
INSTALL_FLAGS_STR="$2"
COMPILE_FILES_STR="$3"
RESTART_TIMERS_STR="$4"
START_SERVICES_STR="$5"
JOURNAL_UNITS_STR="$6"

cd "${REMOTE_MAIN}"

for f in ${COMPILE_FILES_STR}; do
  python3 -m py_compile "${f}"
done

if [[ -n "${INSTALL_FLAGS_STR}" ]]; then
  chmod +x ./tools/install_systemd_services.sh
  ./tools/install_systemd_services.sh ${INSTALL_FLAGS_STR}
  sudo systemctl daemon-reload
fi

for u in ${RESTART_TIMERS_STR}; do
  sudo systemctl restart "${u}"
done

for u in ${START_SERVICES_STR}; do
  sudo systemctl start "${u}"
done

echo "[INFO] timers"
systemctl list-timers --all | grep -E 'ouroboros-(drift-watch|weekly-autotrain|trade-notifier|morning-start-check)' || true
echo "[INFO] services"
systemctl --no-pager --full status ouroboros-widget-status.service 2>/dev/null | sed -n '1,12p' || true

for u in ${JOURNAL_UNITS_STR}; do
  echo "[INFO] journal ${u}"
  sudo journalctl -u "${u}" -n 40 --no-pager || true
done
EOS

echo "[OK] deploy finished"
