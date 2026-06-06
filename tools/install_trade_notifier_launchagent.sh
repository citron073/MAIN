#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
NOTIFIER="${MAIN_DIR}/tools/trade_event_notifier.py"

LABEL="com.ouroboros.trade.notifier"
INTERVAL_SEC=60
BOOTSTRAP_SEND=0
LAUNCH_DIR="${HOME}/Library/LaunchAgents"

usage() {
  cat <<'USAGE'
Usage:
  ./tools/install_trade_notifier_launchagent.sh [options]

Options:
  --label NAME          LaunchAgent label (default: com.ouroboros.trade.notifier)
  --interval-sec N      StartInterval seconds (default: 60)
  --bootstrap-send      Send existing rows on first run
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)
      LABEL="$2"
      shift 2
      ;;
    --interval-sec)
      INTERVAL_SEC="$2"
      shift 2
      ;;
    --bootstrap-send)
      BOOTSTRAP_SEND=1
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

python3 - <<'PY' "${INTERVAL_SEC}"
import sys
x = int(sys.argv[1])
if x < 30:
    raise SystemExit("[FAIL] --interval-sec must be >= 30")
PY

if [[ ! -f "${NOTIFIER}" ]]; then
  echo "[FAIL] notifier not found: ${NOTIFIER}" >&2
  exit 2
fi

mkdir -p "${LAUNCH_DIR}" "${MAIN_DIR}/ci_logs"
PLIST_PATH="${LAUNCH_DIR}/${LABEL}.plist"
UID_NUM="$(id -u)"
PY_BIN="$(command -v python3)"

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
      <string>${PY_BIN}</string>
      <string>${NOTIFIER}</string>
PLIST

if [[ "${BOOTSTRAP_SEND}" == "1" ]]; then
  cat >> "${PLIST_PATH}" <<PLIST
      <string>--bootstrap-send</string>
PLIST
fi

cat >> "${PLIST_PATH}" <<PLIST
    </array>

    <key>WorkingDirectory</key>
    <string>${MAIN_DIR}</string>

    <key>StartInterval</key>
    <integer>${INTERVAL_SEC}</integer>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${MAIN_DIR}/ci_logs/launchd_trade_notifier_out.log</string>
    <key>StandardErrorPath</key>
    <string>${MAIN_DIR}/ci_logs/launchd_trade_notifier_err.log</string>
  </dict>
</plist>
PLIST

chmod 644 "${PLIST_PATH}"
launchctl bootstrap "gui/${UID_NUM}" "${PLIST_PATH}" >/dev/null 2>&1 || launchctl load "${PLIST_PATH}"

echo "[OK] trade notifier launch agent installed"
echo "[INFO] label=${LABEL}"
echo "[INFO] plist=${PLIST_PATH}"
echo "[INFO] inspect: launchctl print gui/${UID_NUM}/${LABEL}"
echo "[INFO] remove: ${MAIN_DIR}/tools/uninstall_trade_notifier_launchagent.sh --label ${LABEL}"
