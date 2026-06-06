#!/usr/bin/env bash
set -euo pipefail

MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SKIP_APT=0
SKIP_RUN_CHECK=0
WITH_SECRETS=0
SKIP_GIT_HOOK=0
WITH_NGROK_SERVICE=0
WITH_SHADOW_SERVICE=0
WITH_TRADE_NOTIFIER_SERVICE=0
WITH_WEEKLY_AUTOTRAIN_SERVICE=0
WITH_DAILY_AUTOTRAIN_SERVICE=0
WITH_CHAMPION_GATE_SERVICE=0
WITH_CHAMPION_ROLLBACK_SERVICE=0
WITH_DRIFT_WATCH_SERVICE=0
WITH_WIDGET_STATUS_SERVICE=0

usage() {
  cat <<'EOF'
usage: cloud_ubuntu_setup.sh [--skip-apt] [--skip-run-check] [--with-secrets] [--skip-git-hook] [--with-ngrok-service] [--with-shadow-service] [--with-trade-notifier-service] [--with-weekly-autotrain-service] [--with-daily-autotrain-service] [--with-champion-gate-service] [--with-champion-rollback-service] [--with-drift-watch-service] [--with-widget-status-service]

Run this on Ubuntu VM after code is copied to ~/trading_bot/trading_bot/MAIN.

What it does:
  1) apt install base deps
  2) create venv and install python deps
  3) run py_compile (+ optional run_check.sh)
  4) optionally register cloud secrets (interactive)
  5) install+start systemd services with current user/home
     (optional: include ngrok tunnel service / shadow runner / trade notifier timer / weekly autotrain timer / daily autotrain timer / champion gate timer / champion rollback timer / drift watch timer / widget status service)
  6) install git post-commit change-log hook
  7) run cloud healthcheck
EOF
}

while (($#)); do
  case "$1" in
    --skip-apt)
      SKIP_APT=1
      ;;
    --skip-run-check)
      SKIP_RUN_CHECK=1
      ;;
    --with-secrets)
      WITH_SECRETS=1
      ;;
    --skip-git-hook)
      SKIP_GIT_HOOK=1
      ;;
    --with-ngrok-service)
      WITH_NGROK_SERVICE=1
      ;;
    --with-shadow-service)
      WITH_SHADOW_SERVICE=1
      ;;
    --with-trade-notifier-service)
      WITH_TRADE_NOTIFIER_SERVICE=1
      ;;
    --with-weekly-autotrain-service)
      WITH_WEEKLY_AUTOTRAIN_SERVICE=1
      ;;
    --with-daily-autotrain-service)
      WITH_DAILY_AUTOTRAIN_SERVICE=1
      ;;
    --with-champion-gate-service)
      WITH_CHAMPION_GATE_SERVICE=1
      ;;
    --with-champion-rollback-service)
      WITH_CHAMPION_ROLLBACK_SERVICE=1
      ;;
    --with-drift-watch-service)
      WITH_DRIFT_WATCH_SERVICE=1
      ;;
    --with-widget-status-service)
      WITH_WIDGET_STATUS_SERVICE=1
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

if [[ ! -f "${MAIN_DIR}/dashboard.py" || ! -f "${MAIN_DIR}/run.py" ]]; then
  echo "[FAIL] MAIN directory not found: ${MAIN_DIR}" >&2
  exit 3
fi

if [[ ! -x "${MAIN_DIR}/tools/install_systemd_services.sh" ]]; then
  chmod +x "${MAIN_DIR}/tools/install_systemd_services.sh"
fi
if [[ ! -x "${MAIN_DIR}/tools/cloud_systemd_healthcheck.sh" ]]; then
  chmod +x "${MAIN_DIR}/tools/cloud_systemd_healthcheck.sh"
fi
if [[ ! -x "${MAIN_DIR}/tools/register_cloud_secrets_env.sh" ]]; then
  chmod +x "${MAIN_DIR}/tools/register_cloud_secrets_env.sh"
fi
if [[ ! -x "${MAIN_DIR}/tools/install_git_post_commit_hook.sh" && -f "${MAIN_DIR}/tools/install_git_post_commit_hook.sh" ]]; then
  chmod +x "${MAIN_DIR}/tools/install_git_post_commit_hook.sh"
fi

SUDO=""
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    echo "[FAIL] sudo not found and current user is not root." >&2
    exit 4
  fi
fi

if [[ "${SKIP_APT}" != "1" ]]; then
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "[FAIL] apt-get not found. this script is for Ubuntu/Debian." >&2
    exit 5
  fi
  echo "[RUN] apt install dependencies"
  ${SUDO} apt-get update
  ${SUDO} apt-get install -y git python3 python3-venv python3-pip
else
  echo "[SKIP] apt install"
fi

cd "${MAIN_DIR}"
recreate_venv=0
if [[ ! -d ".venv" ]]; then
  recreate_venv=1
else
  if [[ ! -x ".venv/bin/python" ]]; then
    echo "[WARN] .venv exists but python executable is missing"
    recreate_venv=1
  elif ! .venv/bin/python -c "import sys; print(sys.version_info[0])" >/dev/null 2>&1; then
    echo "[WARN] .venv python is not executable on this host (possible cross-OS/cross-arch copy)"
    recreate_venv=1
  fi
fi

if [[ "${recreate_venv}" == "1" ]]; then
  echo "[RUN] recreate venv (.venv)"
  rm -rf .venv
  python3 -m venv .venv
fi

echo "[RUN] pip install runtime packages"
if [[ ! -x ".venv/bin/python" ]]; then
  echo "[FAIL] venv python not found: ${MAIN_DIR}/.venv/bin/python" >&2
  exit 7
fi
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install streamlit pandas numpy plotly "streamlit[auth]" authlib

echo "[RUN] py_compile"
python3 -m py_compile bot.py dashboard.py tools/live_preflight.py tools/keychain_secret.py tools/drift_resume_summary.py tools/weekly_auto_feedback.py tools/daily_auto_train_reset.py tools/champion_challenger_promote.py tools/champion_rollback_guard.py tools/market_drift_watch.py tools/widget_status.py

if [[ "${SKIP_RUN_CHECK}" != "1" ]]; then
  echo "[RUN] ./run_check.sh"
  ./run_check.sh
else
  echo "[SKIP] run_check.sh"
fi

if [[ "${WITH_SECRETS}" == "1" ]]; then
  echo "[RUN] register cloud secrets"
  ${SUDO} "${MAIN_DIR}/tools/register_cloud_secrets_env.sh" /etc/ouroboros/secrets.env
else
  echo "[INFO] skip secrets registration. run later if needed:"
  echo "  ${SUDO:+sudo }./tools/register_cloud_secrets_env.sh /etc/ouroboros/secrets.env"
fi

echo "[RUN] install and start systemd services"
install_args=()
if [[ "${WITH_NGROK_SERVICE}" == "1" ]]; then
  install_args+=(--with-ngrok)
fi
if [[ "${WITH_SHADOW_SERVICE}" == "1" ]]; then
  install_args+=(--with-shadow)
fi
if [[ "${WITH_TRADE_NOTIFIER_SERVICE}" == "1" ]]; then
  install_args+=(--with-trade-notifier)
fi
if [[ "${WITH_WEEKLY_AUTOTRAIN_SERVICE}" == "1" ]]; then
  install_args+=(--with-weekly-autotrain)
fi
if [[ "${WITH_DAILY_AUTOTRAIN_SERVICE}" == "1" ]]; then
  install_args+=(--with-daily-autotrain)
fi
if [[ "${WITH_CHAMPION_GATE_SERVICE}" == "1" ]]; then
  install_args+=(--with-champion-gate)
fi
if [[ "${WITH_CHAMPION_ROLLBACK_SERVICE}" == "1" ]]; then
  install_args+=(--with-champion-rollback)
fi
if [[ "${WITH_DRIFT_WATCH_SERVICE}" == "1" ]]; then
  install_args+=(--with-drift-watch)
fi
if [[ "${WITH_WIDGET_STATUS_SERVICE}" == "1" ]]; then
  install_args+=(--with-widget-status)
fi
"${MAIN_DIR}/tools/install_systemd_services.sh" "${install_args[@]}"

if [[ "${SKIP_GIT_HOOK}" != "1" ]]; then
  if [[ -x "${MAIN_DIR}/tools/install_git_post_commit_hook.sh" && -d "${MAIN_DIR}/.git/hooks" ]]; then
    echo "[RUN] install git post-commit change-log hook"
    "${MAIN_DIR}/tools/install_git_post_commit_hook.sh"
  else
    echo "[WARN] skip git hook install (.git/hooks or installer not found)"
  fi
else
  echo "[SKIP] git hook install"
fi

echo "[RUN] healthcheck"
health_args=()
if [[ "${WITH_NGROK_SERVICE}" == "1" ]]; then
  health_args+=(--include-ngrok)
fi
if [[ "${WITH_SHADOW_SERVICE}" == "1" ]]; then
  health_args+=(--include-shadow)
fi
if [[ "${WITH_TRADE_NOTIFIER_SERVICE}" == "1" ]]; then
  health_args+=(--include-trade-notifier)
fi
if [[ "${WITH_WEEKLY_AUTOTRAIN_SERVICE}" == "1" ]]; then
  health_args+=(--include-weekly-autotrain)
fi
if [[ "${WITH_DAILY_AUTOTRAIN_SERVICE}" == "1" ]]; then
  health_args+=(--include-daily-autotrain)
fi
if [[ "${WITH_CHAMPION_GATE_SERVICE}" == "1" ]]; then
  health_args+=(--include-champion-gate)
fi
if [[ "${WITH_CHAMPION_ROLLBACK_SERVICE}" == "1" ]]; then
  health_args+=(--include-champion-rollback)
fi
if [[ "${WITH_DRIFT_WATCH_SERVICE}" == "1" ]]; then
  health_args+=(--include-drift-watch)
fi
if [[ "${WITH_WIDGET_STATUS_SERVICE}" == "1" ]]; then
  health_args+=(--include-widget-status)
fi
"${MAIN_DIR}/tools/cloud_systemd_healthcheck.sh" "${health_args[@]}"

echo "[OK] cloud ubuntu setup completed"
echo "[NEXT] if secrets were not set yet:"
echo "  ${SUDO:+sudo }./tools/register_cloud_secrets_env.sh /etc/ouroboros/secrets.env"
restart_units="ouroboros-bot.service ouroboros-dashboard.service"
if [[ "${WITH_NGROK_SERVICE}" == "1" ]]; then
  restart_units="${restart_units} ouroboros-ngrok.service"
fi
if [[ "${WITH_SHADOW_SERVICE}" == "1" ]]; then
  restart_units="${restart_units} ouroboros-shadow.service"
fi
if [[ "${WITH_TRADE_NOTIFIER_SERVICE}" == "1" ]]; then
  restart_units="${restart_units} ouroboros-trade-notifier.timer"
fi
if [[ "${WITH_WEEKLY_AUTOTRAIN_SERVICE}" == "1" ]]; then
  restart_units="${restart_units} ouroboros-weekly-autotrain.timer"
fi
if [[ "${WITH_DAILY_AUTOTRAIN_SERVICE}" == "1" ]]; then
  restart_units="${restart_units} ouroboros-daily-autotrain.timer"
fi
if [[ "${WITH_CHAMPION_GATE_SERVICE}" == "1" ]]; then
  restart_units="${restart_units} ouroboros-champion-gate.timer"
fi
if [[ "${WITH_CHAMPION_ROLLBACK_SERVICE}" == "1" ]]; then
  restart_units="${restart_units} ouroboros-champion-rollback.timer"
fi
if [[ "${WITH_DRIFT_WATCH_SERVICE}" == "1" ]]; then
  restart_units="${restart_units} ouroboros-drift-watch.timer"
fi
if [[ "${WITH_WIDGET_STATUS_SERVICE}" == "1" ]]; then
  restart_units="${restart_units} ouroboros-widget-status.service"
fi
echo "  ${SUDO:+sudo }systemctl restart ${restart_units}"
next_health="./tools/cloud_systemd_healthcheck.sh --run-preflight"
if [[ "${WITH_NGROK_SERVICE}" == "1" ]]; then
  next_health="${next_health} --include-ngrok"
fi
if [[ "${WITH_SHADOW_SERVICE}" == "1" ]]; then
  next_health="${next_health} --include-shadow"
fi
if [[ "${WITH_TRADE_NOTIFIER_SERVICE}" == "1" ]]; then
  next_health="${next_health} --include-trade-notifier"
fi
if [[ "${WITH_WEEKLY_AUTOTRAIN_SERVICE}" == "1" ]]; then
  next_health="${next_health} --include-weekly-autotrain"
fi
if [[ "${WITH_DAILY_AUTOTRAIN_SERVICE}" == "1" ]]; then
  next_health="${next_health} --include-daily-autotrain"
fi
if [[ "${WITH_CHAMPION_GATE_SERVICE}" == "1" ]]; then
  next_health="${next_health} --include-champion-gate"
fi
if [[ "${WITH_CHAMPION_ROLLBACK_SERVICE}" == "1" ]]; then
  next_health="${next_health} --include-champion-rollback"
fi
if [[ "${WITH_DRIFT_WATCH_SERVICE}" == "1" ]]; then
  next_health="${next_health} --include-drift-watch"
fi
if [[ "${WITH_WIDGET_STATUS_SERVICE}" == "1" ]]; then
  next_health="${next_health} --include-widget-status"
fi
echo "  ${next_health}"
