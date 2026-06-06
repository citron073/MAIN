#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${UNIFIED_DASHBOARD_HOST:-127.0.0.1}"
PORT="${UNIFIED_DASHBOARD_PORT:-8792}"
RUNTIME_PATH="${ROOT_DIR}/review_out/unified_dashboard_runtime.json"

STAMP="$(date +%Y%m%d_%H%M%S)"
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
TAILSCALE_IP="$(ifconfig 2>/dev/null | awk '/inet 100\./ {print $2; exit}')"
MODE_LABEL="local"

usage() {
  cat <<'USAGE'
Usage:
  ./tools/start_unified_dashboard.sh [options]

Options:
  --public       Bind 0.0.0.0 and print LAN/Tailscale URLs
  --tailscale    Bind the current Tailscale 100.x address only
  --host HOST    Override bind host
  --port PORT    Override port
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --public)
      HOST="0.0.0.0"
      MODE_LABEL="public"
      shift
      ;;
    --tailscale)
      if [[ -z "${TAILSCALE_IP}" ]]; then
        echo "[WARN] Tailscale 100.x IP not found. Falling back to 127.0.0.1." >&2
        HOST="127.0.0.1"
        MODE_LABEL="local-fallback"
        shift
        continue
      fi
      HOST="${TAILSCALE_IP}"
      MODE_LABEL="tailscale"
      shift
      ;;
    --host)
      HOST="$2"
      MODE_LABEL="custom"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
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

URL="http://${HOST}:${PORT}/tools/unified_dashboard.html?v=${STAMP}"
LOCAL_URL="http://127.0.0.1:${PORT}/tools/unified_dashboard.html?v=${STAMP}"
HEALTHCHECK_URL="${URL}"
if [[ "${HOST}" == "0.0.0.0" || "${HOST}" == "127.0.0.1" ]]; then
  HEALTHCHECK_URL="${LOCAL_URL}"
fi

echo "[INFO] Ouroboros unified dashboard"
echo "[INFO] root=${ROOT_DIR}"
echo "[INFO] url=${URL}"
echo "[INFO] healthcheck=${HEALTHCHECK_URL}"
if [[ "${HOST}" == "0.0.0.0" ]]; then
  echo "[INFO] local=${LOCAL_URL}"
  if [[ -n "${LAN_IP}" ]]; then
    echo "[INFO] LAN=http://${LAN_IP}:${PORT}/tools/unified_dashboard.html?v=${STAMP}"
  fi
  if [[ -n "${TAILSCALE_IP}" ]]; then
    echo "[INFO] Tailscale=http://${TAILSCALE_IP}:${PORT}/tools/unified_dashboard.html?v=${STAMP}"
  fi
  echo "[INFO] public mode: same LAN or Tailscale devices can open the LAN/Tailscale URL"
fi
if [[ -n "${TAILSCALE_IP}" && "${HOST}" == "${TAILSCALE_IP}" ]]; then
  echo "[INFO] Tailscale=http://${TAILSCALE_IP}:${PORT}/tools/unified_dashboard.html?v=${STAMP}"
  echo "[INFO] tailscale mode: only devices on your Tailnet can open this URL"
fi
echo "[INFO] stop: Ctrl+C"
mkdir -p "$(dirname "${RUNTIME_PATH}")"
cat > "${RUNTIME_PATH}" <<JSON
{
  "updated_at": "$(date '+%Y-%m-%d %H:%M:%S')",
  "mode": "${MODE_LABEL}",
  "host": "${HOST}",
  "port": "${PORT}",
  "url": "${URL}",
  "local_url": "${LOCAL_URL}",
  "healthcheck_url": "${HEALTHCHECK_URL}",
  "tailscale_ip": "${TAILSCALE_IP}",
  "lan_ip": "${LAN_IP}"
}
JSON
cd "$ROOT_DIR"
python3 -m http.server "$PORT" --bind "$HOST" --directory "$ROOT_DIR"
