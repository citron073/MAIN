#!/usr/bin/env bash
set -euo pipefail

# Safe VM-side retry guard for IB Gateway.
# - Does not read or print credentials.
# - Does not place orders.
# - Does not restart while a fresh login attempt is still within the grace window.

IBG_UNIT="${IBG_UNIT:-ouroboros-ibgateway.service}"
REMINDER_UNIT="${REMINDER_UNIT:-ouroboros-ibkr-2fa-reminder.service}"
IBKR_API_PORTS="${IBKR_API_PORTS:-7496 7497}"
MIN_ACTIVE_MINUTES="${MIN_ACTIVE_MINUTES:-25}"
MAIN_DIR="${MAIN_DIR:-/home/ubuntu/trading_bot/MAIN}"
OUT_DIR="${OUT_DIR:-${MAIN_DIR}/review_out}"
STATE_PATH="${STATE_PATH:-${OUT_DIR}/ibkr_gateway_retry_latest.json}"

mkdir -p "${OUT_DIR}"

now_jst() {
  TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M:%S'
}

json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip(), ensure_ascii=False))'
}

write_state() {
  local status="$1"
  local action="$2"
  local reason="$3"
  local port_status="$4"
  local service_status="$5"
  local active_seconds="$6"
  local escaped_reason
  escaped_reason="$(printf '%s' "${reason}" | json_escape)"
  cat >"${STATE_PATH}" <<JSON
{
  "generated_at_jst": "$(now_jst)",
  "status": "${status}",
  "action": "${action}",
  "reason": ${escaped_reason},
  "ibg_unit": "${IBG_UNIT}",
  "service_status": "${service_status}",
  "active_seconds": ${active_seconds},
  "api_ports": "${IBKR_API_PORTS}",
  "port_status": "${port_status}",
  "min_active_minutes": ${MIN_ACTIVE_MINUTES},
  "safety": {
    "reads_or_prints_credentials": false,
    "places_orders": false,
    "opens_public_ports": false
  }
}
JSON
}

port_status="closed"
for port in ${IBKR_API_PORTS}; do
  if ss -ltn 2>/dev/null | grep -q ":${port} "; then
    port_status="open:${port}"
    break
  fi
done

service_status="$(systemctl is-active "${IBG_UNIT}" 2>/dev/null || echo unknown)"
active_seconds=0
if [[ "${service_status}" == "active" ]]; then
  active_enter_ns="$(systemctl show "${IBG_UNIT}" -p ActiveEnterTimestampMonotonic --value 2>/dev/null || echo 0)"
  now_ns="$(cut -d' ' -f1 /proc/uptime 2>/dev/null | awk '{printf "%.0f", $1 * 1000000}' || echo 0)"
  if [[ "${active_enter_ns}" =~ ^[0-9]+$ && "${now_ns}" =~ ^[0-9]+$ && "${active_enter_ns}" -gt 0 && "${now_ns}" -gt "${active_enter_ns}" ]]; then
    active_seconds=$(( (now_ns - active_enter_ns) / 1000000 ))
  fi
fi

if [[ "${port_status}" == open:* ]]; then
  write_state "OK" "none" "IB Gateway API port is already listening" "${port_status}" "${service_status}" "${active_seconds}"
  echo "[OK] ${port_status}; no retry needed"
  exit 0
fi

if [[ "${service_status}" == "active" && "${active_seconds}" -lt $((MIN_ACTIVE_MINUTES * 60)) ]]; then
  write_state "WAITING" "none" "IB Gateway is active and still inside login grace window" "${port_status}" "${service_status}" "${active_seconds}"
  echo "[WAIT] ${IBG_UNIT} active ${active_seconds}s; waiting for login/API"
  exit 0
fi

if systemctl list-unit-files "${REMINDER_UNIT}" >/dev/null 2>&1; then
  sudo systemctl start "${REMINDER_UNIT}" >/dev/null 2>&1 || true
fi

sudo systemctl reset-failed "${IBG_UNIT}" >/dev/null 2>&1 || true
sudo systemctl restart "${IBG_UNIT}"
write_state "RETRY_STARTED" "restart" "API port closed; restarted IB Gateway for another login attempt" "${port_status}" "${service_status}" "${active_seconds}"
echo "[RETRY] restarted ${IBG_UNIT}; API ports still require login/API readiness"
