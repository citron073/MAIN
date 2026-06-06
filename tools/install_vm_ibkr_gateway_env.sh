#!/usr/bin/env bash
set -euo pipefail

HOST=""
USER_NAME="ubuntu"
KEY_PATH=""
APPLY=0
IBG_URL="${IBG_URL:-https://download2.interactivebrokers.com/installers/ibgateway/latest-standalone/ibgateway-latest-standalone-linux-x64.sh}"
REMOTE_INSTALL_DIR="${REMOTE_INSTALL_DIR:-/home/ubuntu/Jts}"
REMOTE_DOWNLOAD_DIR="${REMOTE_DOWNLOAD_DIR:-/home/ubuntu/Downloads}"

usage() {
  cat <<'EOF'
usage: install_vm_ibkr_gateway_env.sh --host HOST [--user ubuntu] [--key PATH] [--apply]

Installs the VM-side runtime needed for IB Gateway Paper:
  - Java runtime
  - Xvfb / x11vnc / openbox headless GUI tools
  - IB Gateway Linux x64 standalone installer into ~/Jts

Safety:
  - Default is dry-run.
  - Does not read or print IBKR credentials.
  - Does not open public ports.
  - Does not place orders.
  - Does not auto-login IB Gateway.

After install, use SSH tunnels for GUI/API:
  ./tools/open_vm_ibkr_vnc_tunnel.sh --host HOST --key PATH
  ./tools/open_vm_ibkr_tunnel.sh --host HOST --key PATH
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
    --apply)
      APPLY=1
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

if [[ -z "$HOST" ]]; then
  echo "[FAIL] --host is required" >&2
  usage >&2
  exit 2
fi

if [[ -n "$KEY_PATH" ]]; then
  KEY_PATH="${KEY_PATH/#\~/$HOME}"
fi

SSH_OPTS=(-o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3)
if [[ -n "$KEY_PATH" ]]; then
  SSH_OPTS+=(-i "$KEY_PATH")
fi

REMOTE="${USER_NAME}@${HOST}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HEADLESS_RUNNER="${SCRIPT_DIR}/run_vm_ibgateway_headless.sh"

read -r -d '' REMOTE_SCRIPT <<'SCRIPT' || true
set -euo pipefail

APPLY="${APPLY}"
IBG_URL="${IBG_URL}"
REMOTE_INSTALL_DIR="${REMOTE_INSTALL_DIR}"
REMOTE_DOWNLOAD_DIR="${REMOTE_DOWNLOAD_DIR}"
INSTALLER="${REMOTE_DOWNLOAD_DIR}/ibgateway-latest-standalone-linux-x64.sh"

echo "[INFO] mode=$([ "$APPLY" = "1" ] && echo apply || echo dry-run)"
echo "[INFO] install_dir=${REMOTE_INSTALL_DIR}"
echo "[INFO] installer=${INSTALLER}"
echo "[INFO] safety: no credentials, no public ports, no orders, no autologin"

if [[ "$APPLY" != "1" ]]; then
  cat <<EOF
[DRY-RUN] would run:
  sudo apt-get update
  sudo apt-get install -y openjdk-17-jre-headless xvfb x11vnc openbox dbus-x11 curl ca-certificates unzip libxtst6 libxrender1 libxi6 libxrandr2 libxinerama1 libxcursor1 libxft2 libgtk-3-0
  mkdir -p "${REMOTE_DOWNLOAD_DIR}"
  curl -L "${IBG_URL}" -o "${INSTALLER}"
  chmod +x "${INSTALLER}"
  "${INSTALLER}" -q -dir "${REMOTE_INSTALL_DIR}"
EOF
  exit 0
fi

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  openjdk-17-jre-headless \
  xvfb \
  x11vnc \
  openbox \
  dbus-x11 \
  curl \
  ca-certificates \
  unzip \
  libxtst6 \
  libxrender1 \
  libxi6 \
  libxrandr2 \
  libxinerama1 \
  libxcursor1 \
  libxft2 \
  libgtk-3-0

mkdir -p "${REMOTE_DOWNLOAD_DIR}"
curl -L "${IBG_URL}" -o "${INSTALLER}"
chmod +x "${INSTALLER}"

if [[ ! -s "${INSTALLER}" ]]; then
  echo "[FAIL] installer download is empty: ${INSTALLER}" >&2
  exit 3
fi

"${INSTALLER}" -q -dir "${REMOTE_INSTALL_DIR}"

echo "[OK] packages installed"
echo "[OK] ibgateway installer applied to ${REMOTE_INSTALL_DIR}"
echo "[INFO] next: run tools/vm_ibkr_gateway_readiness.py again"
SCRIPT

echo "[INFO] remote=${REMOTE}"
echo "[INFO] apply=${APPLY}"
if [[ "$APPLY" == "1" ]]; then
  scp "${SSH_OPTS[@]}" "$HEADLESS_RUNNER" "${REMOTE}:~/run_vm_ibgateway_headless.sh"
  ssh "${SSH_OPTS[@]}" "$REMOTE" "chmod +x ~/run_vm_ibgateway_headless.sh"
else
  echo "[DRY-RUN] would upload: ${HEADLESS_RUNNER} -> ${REMOTE}:~/run_vm_ibgateway_headless.sh"
fi
ssh "${SSH_OPTS[@]}" "$REMOTE" \
  "APPLY='${APPLY}' IBG_URL='${IBG_URL}' REMOTE_INSTALL_DIR='${REMOTE_INSTALL_DIR}' REMOTE_DOWNLOAD_DIR='${REMOTE_DOWNLOAD_DIR}' bash -s" \
  <<<"$REMOTE_SCRIPT"
