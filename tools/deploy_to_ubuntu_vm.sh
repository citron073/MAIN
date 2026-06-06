#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

HOST=""
USER_NAME="ubuntu"
KEY_PATH=""
SKIP_COPY=0
SKIP_SETUP=0
WITH_SECRETS=0
WITH_NGROK_SERVICE=0
WITH_TRADE_NOTIFIER_SERVICE=0
WITH_WEEKLY_AUTOTRAIN_SERVICE=0
WITH_WIDGET_STATUS_SERVICE=0

usage() {
  cat <<'EOF'
usage: deploy_to_ubuntu_vm.sh --host <host-or-ip> [options]

options:
  --host HOST          VM host or IP (required)
  --user USER          SSH user (default: ubuntu)
  --key PATH           SSH private key path (optional)
  --skip-copy          Skip scp transfer
  --skip-setup         Skip remote setup run
  --with-secrets       Run remote setup with --with-secrets (interactive prompt on VM)
  --with-ngrok-service Include --with-ngrok-service in remote setup
  --with-trade-notifier-service Include --with-trade-notifier-service in remote setup
  --with-weekly-autotrain-service Include --with-weekly-autotrain-service in remote setup
  --with-widget-status-service Include --with-widget-status-service in remote setup
  -h, --help           Show this help

example:
  ./tools/deploy_to_ubuntu_vm.sh --host 161.33.26.35 --key ~/Downloads/ssh-key-2026-03-02-2.key --with-secrets
  ./tools/deploy_to_ubuntu_vm.sh --host 1.2.3.4 --key ~/.ssh/oci.pem --with-secrets
  ./tools/deploy_to_ubuntu_vm.sh --host 1.2.3.4 --key ~/.ssh/oci.pem --with-secrets --with-ngrok-service --with-trade-notifier-service
  ./tools/deploy_to_ubuntu_vm.sh --host 1.2.3.4 --key ~/.ssh/oci.pem --with-secrets --with-ngrok-service --with-trade-notifier-service --with-weekly-autotrain-service
  ./tools/deploy_to_ubuntu_vm.sh --host 1.2.3.4 --key ~/.ssh/oci.pem --with-widget-status-service
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
    --skip-copy)
      SKIP_COPY=1
      ;;
    --skip-setup)
      SKIP_SETUP=1
      ;;
    --with-secrets)
      WITH_SECRETS=1
      ;;
    --with-ngrok-service)
      WITH_NGROK_SERVICE=1
      ;;
    --with-trade-notifier-service)
      WITH_TRADE_NOTIFIER_SERVICE=1
      ;;
    --with-weekly-autotrain-service)
      WITH_WEEKLY_AUTOTRAIN_SERVICE=1
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

if [[ -z "${HOST}" ]]; then
  echo "[FAIL] --host is required." >&2
  usage >&2
  exit 2
fi

if [[ -n "${KEY_PATH}" ]]; then
  KEY_PATH="${KEY_PATH/#\~/${HOME}}"
fi

run_scp() {
  if [[ -n "${KEY_PATH}" ]]; then
    scp -i "${KEY_PATH}" "$@"
  else
    scp "$@"
  fi
}

run_ssh() {
  if [[ -n "${KEY_PATH}" ]]; then
    ssh -i "${KEY_PATH}" "$@"
  else
    ssh "$@"
  fi
}

remote="${USER_NAME}@${HOST}"
echo "[INFO] local repo: ${REPO_ROOT}"
echo "[INFO] remote: ${remote}"

if [[ "${SKIP_COPY}" != "1" ]]; then
  echo "[RUN] copy repo to VM: ${REPO_ROOT} -> ${remote}:~/"
  run_scp -r "${REPO_ROOT}" "${remote}:~/"
else
  echo "[SKIP] copy"
fi

if [[ "${SKIP_SETUP}" != "1" ]]; then
  remote_setup_args=()
  if [[ "${WITH_SECRETS}" == "1" ]]; then
    remote_setup_args+=(--with-secrets)
  fi
  if [[ "${WITH_NGROK_SERVICE}" == "1" ]]; then
    remote_setup_args+=(--with-ngrok-service)
  fi
  if [[ "${WITH_TRADE_NOTIFIER_SERVICE}" == "1" ]]; then
    remote_setup_args+=(--with-trade-notifier-service)
  fi
  if [[ "${WITH_WEEKLY_AUTOTRAIN_SERVICE}" == "1" ]]; then
    remote_setup_args+=(--with-weekly-autotrain-service)
  fi
  if [[ "${WITH_WIDGET_STATUS_SERVICE}" == "1" ]]; then
    remote_setup_args+=(--with-widget-status-service)
  fi

  echo "[RUN] remote setup"
  run_ssh -t "${remote}" "bash -lc '
set -euo pipefail
CANDS=(\"\$HOME/trading_bot/trading_bot/MAIN\" \"\$HOME/trading_bot/MAIN\")
MAIN_DIR=\"\"
for c in \"\${CANDS[@]}\"; do
  if [[ -f \"\$c/dashboard.py\" ]]; then
    MAIN_DIR=\"\$c\"
    break
  fi
done
if [[ -z \"\$MAIN_DIR\" ]]; then
  echo \"[FAIL] MAIN directory not found on VM. checked: \${CANDS[*]}\" >&2
  exit 6
fi
echo \"[INFO] MAIN_DIR=\$MAIN_DIR\"
cd \"\$MAIN_DIR\"
chmod +x ./tools/cloud_ubuntu_setup.sh
./tools/cloud_ubuntu_setup.sh ${remote_setup_args[*]}
'"
else
  echo "[SKIP] setup"
fi

echo "[OK] deploy_to_ubuntu_vm finished"
