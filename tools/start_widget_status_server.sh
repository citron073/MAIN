#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PY_BIN="${PY_BIN:-python3}"
HOST="${WIDGET_STATUS_HOST:-127.0.0.1}"
PORT="${WIDGET_STATUS_PORT:-8787}"
TOKEN="${WIDGET_STATUS_TOKEN:-}"
LAN_IP="${WIDGET_STATUS_LAN_IP:-}"

if [[ -z "${LAN_IP}" ]]; then
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
fi
if [[ -z "${LAN_IP}" ]]; then
  LAN_IP="$(ipconfig getifaddr en1 2>/dev/null || true)"
fi
if [[ -z "${LAN_IP}" ]]; then
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
fi

echo "[INFO] main: ${ROOT_DIR}"
echo "[INFO] local: http://127.0.0.1:${PORT}/"
if [[ "${HOST}" == "0.0.0.0" && -n "${LAN_IP}" ]]; then
  echo "[INFO] LAN:   http://${LAN_IP}:${PORT}/"
fi
if [[ -n "${TOKEN}" ]]; then
  echo "[INFO] token auth: enabled"
  if [[ "${HOST}" == "0.0.0.0" && -n "${LAN_IP}" ]]; then
    echo "[INFO] LAN+token: http://${LAN_IP}:${PORT}/?token=${TOKEN}"
  fi
else
  echo "[WARN] token auth: disabled"
fi
echo "[INFO] stop: Ctrl+C"

cmd=(
  "$PY_BIN"
  "$ROOT_DIR/tools/widget_status.py"
  --main-dir "$ROOT_DIR"
  --serve
  --host "$HOST"
  --port "$PORT"
)

if [[ -n "${TOKEN}" ]]; then
  cmd+=(--token "$TOKEN")
fi

exec "${cmd[@]}"
