#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WRAPPER="${MAIN_DIR}/tools/dashboard_ngrok_wrapper.sh"

LABEL="com.ouroboros.dashboard.ngrok"
RESTART_DELAY_SEC=5
MAX_RESTARTS=0
ONESHOT=0
LAUNCH_DIR="${HOME}/Library/LaunchAgents"

usage() {
  cat <<'USAGE'
Usage:
  ./tools/install_dashboard_launchagent.sh [options]

Options:
  --label NAME            LaunchAgent label (default: com.ouroboros.dashboard.ngrok)
  --restart-delay-sec N   Restart delay seconds (default: 5)
  --max-restarts N        0=infinite (default: 0)
  --oneshot               Run once then stop (default: off)
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)
      LABEL="$2"
      shift 2
      ;;
    --restart-delay-sec)
      RESTART_DELAY_SEC="$2"
      shift 2
      ;;
    --max-restarts)
      MAX_RESTARTS="$2"
      shift 2
      ;;
    --oneshot)
      ONESHOT=1
      shift
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

python3 - <<'PY' "${RESTART_DELAY_SEC}" "${MAX_RESTARTS}"
import sys
r = int(sys.argv[1])
m = int(sys.argv[2])
if r < 1:
    raise SystemExit("[FAIL] --restart-delay-sec must be >= 1")
if m < 0:
    raise SystemExit("[FAIL] --max-restarts must be >= 0")
PY

if [[ ! -x "${WRAPPER}" ]]; then
  echo "[FAIL] wrapper not executable: ${WRAPPER}" >&2
  exit 2
fi

mkdir -p "${LAUNCH_DIR}" "${MAIN_DIR}/ci_logs"
PLIST_PATH="${LAUNCH_DIR}/${LABEL}.plist"
UID_NUM="$(id -u)"
PY_BIN="$(command -v python3 || true)"
NGROK_BIN="$(command -v ngrok || true)"
PATH_VAL="${PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"

if [[ -z "${PY_BIN}" ]]; then
  PY_BIN="/usr/bin/python3"
fi
if [[ -z "${NGROK_BIN}" ]]; then
  if [[ -x "/opt/homebrew/bin/ngrok" ]]; then
    NGROK_BIN="/opt/homebrew/bin/ngrok"
  elif [[ -x "/usr/local/bin/ngrok" ]]; then
    NGROK_BIN="/usr/local/bin/ngrok"
  else
    NGROK_BIN="ngrok"
  fi
fi

if [[ -f "${PLIST_PATH}" ]]; then
  launchctl bootout "gui/${UID_NUM}" "${PLIST_PATH}" >/dev/null 2>&1 || launchctl unload "${PLIST_PATH}" >/dev/null 2>&1 || true
  rm -f "${PLIST_PATH}"
fi

cat > "${PLIST_PATH}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${LABEL}</string>

    <key>ProgramArguments</key>
    <array>
      <string>${WRAPPER}</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${MAIN_DIR}</string>

    <key>EnvironmentVariables</key>
    <dict>
      <key>RESTART_DELAY_SEC</key><string>${RESTART_DELAY_SEC}</string>
      <key>MAX_RESTARTS</key><string>${MAX_RESTARTS}</string>
      <key>ONESHOT</key><string>${ONESHOT}</string>
      <key>PY_BIN</key><string>${PY_BIN}</string>
      <key>NGROK_BIN</key><string>${NGROK_BIN}</string>
      <key>PATH</key><string>${PATH_VAL}</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${MAIN_DIR}/ci_logs/launchd_dashboard_out.log</string>
    <key>StandardErrorPath</key>
    <string>${MAIN_DIR}/ci_logs/launchd_dashboard_err.log</string>
  </dict>
</plist>
PLIST

chmod 644 "${PLIST_PATH}"

launchctl bootstrap "gui/${UID_NUM}" "${PLIST_PATH}" >/dev/null 2>&1 || launchctl load "${PLIST_PATH}"

echo "[OK] dashboard launch agent installed"
echo "[INFO] label=${LABEL}"
echo "[INFO] plist=${PLIST_PATH}"
echo "[INFO] wrapper=${WRAPPER}"
echo "[INFO] inspect: launchctl print gui/${UID_NUM}/${LABEL}"
echo "[INFO] remove: ${MAIN_DIR}/tools/uninstall_dashboard_launchagent.sh --label ${LABEL}"
