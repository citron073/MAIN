#!/usr/bin/env bash
set -euo pipefail

DISPLAY_NUM="${DISPLAY_NUM:-99}"
DISPLAY=":${DISPLAY_NUM}"
IBG_DIR="${IBG_DIR:-$HOME/Jts}"
VNC_PORT="${VNC_PORT:-5901}"
API_PORT="${API_PORT:-7497}"
LOG_DIR="${LOG_DIR:-$HOME/ibgateway-headless-logs}"
LANG="${LANG:-C.UTF-8}"
LC_ALL="${LC_ALL:-C.UTF-8}"
JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:--Duser.language=en -Duser.country=US}"
VNC_PASSWORD="${VNC_PASSWORD:-ouroboros}"
VNC_PASSWD_FILE="${VNC_PASSWD_FILE:-$HOME/.vnc/passwd}"

export LANG LC_ALL JAVA_TOOL_OPTIONS

mkdir -p "$LOG_DIR"
mkdir -p "$(dirname "$VNC_PASSWD_FILE")"

find_ibgateway_bin() {
  for p in \
    "$IBG_DIR/ibgateway" \
    "$IBG_DIR/IB Gateway" \
    "$IBG_DIR/ibgateway-stable" \
    "$IBG_DIR/ibgateway-latest" \
    "$HOME/Jts/ibgateway" \
    "$HOME/Jts/IB Gateway"
  do
    if [[ -x "$p" ]]; then
      printf '%s\n' "$p"
      return 0
    fi
  done
  find "$IBG_DIR" -maxdepth 3 -type f \( -name 'ibgateway' -o -name 'IB Gateway' \) -perm -u+x 2>/dev/null | head -n 1
}

IBG_BIN="$(find_ibgateway_bin || true)"
if [[ -z "$IBG_BIN" ]]; then
  echo "[FAIL] IB Gateway executable not found under ${IBG_DIR}" >&2
  exit 2
fi

echo "[INFO] DISPLAY=${DISPLAY}"
echo "[INFO] IB Gateway=${IBG_BIN}"
echo "[INFO] VNC binds localhost:${VNC_PORT}"
echo "[INFO] VNC auth: enabled"
echo "[INFO] API expected localhost:${API_PORT} after IB Gateway login/config"
echo "[INFO] stop: Ctrl+C"

cleanup() {
  jobs -p | xargs -r kill >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

Xvfb "$DISPLAY" -screen 0 1280x900x24 >"$LOG_DIR/xvfb.out.log" 2>"$LOG_DIR/xvfb.err.log" &
sleep 1
openbox >"$LOG_DIR/openbox.out.log" 2>"$LOG_DIR/openbox.err.log" &
sleep 1
x11vnc -storepasswd "$VNC_PASSWORD" "$VNC_PASSWD_FILE" >/dev/null 2>&1
x11vnc -localhost -display "$DISPLAY" -rfbport "$VNC_PORT" -forever -shared -rfbauth "$VNC_PASSWD_FILE" \
  >"$LOG_DIR/x11vnc.out.log" 2>"$LOG_DIR/x11vnc.err.log" &
sleep 1

DISPLAY="$DISPLAY" "$IBG_BIN" >"$LOG_DIR/ibgateway.out.log" 2>"$LOG_DIR/ibgateway.err.log" &
wait
