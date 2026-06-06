#!/usr/bin/env bash
set -euo pipefail

HOST=""
USER_NAME="ubuntu"
KEY_PATH=""
LOCAL_PORT="${LOCAL_PORT:-5901}"
REMOTE_PORT="${REMOTE_PORT:-5901}"
PORT_SCAN_LIMIT="${PORT_SCAN_LIMIT:-20}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
STATE_PATH="${STATE_PATH:-${MAIN_DIR}/review_out/ibkr_vnc_tunnel_state.json}"

is_local_port_in_use() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  if command -v nc >/dev/null 2>&1; then
    nc -z 127.0.0.1 "${port}" >/dev/null 2>&1
    return $?
  fi
  return 1
}

choose_local_port() {
  local requested="$1"
  local candidate="$requested"
  local tries=0
  while is_local_port_in_use "$candidate"; do
    if (( tries == 0 )); then
      echo "[WARN] local port ${requested} is already in use; searching for a free fallback port" >&2
    fi
    ((tries += 1))
    if (( tries > PORT_SCAN_LIMIT )); then
      echo "[FAIL] could not find a free local port after ${PORT_SCAN_LIMIT} attempts starting from ${requested}" >&2
      exit 1
    fi
    candidate=$((requested + tries))
  done
  printf '%s\n' "$candidate"
}

now_jst() {
  TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M:%S'
}

write_state() {
  local active="$1"
  local reason="${2:-}"
  mkdir -p "$(dirname "$STATE_PATH")"
  cat >"$STATE_PATH" <<EOF
{
  "active": ${active},
  "requested_local_port": ${REQUESTED_LOCAL_PORT},
  "local_port": ${LOCAL_PORT},
  "remote_port": ${REMOTE_PORT},
  "host": "$(printf '%s' "$HOST")",
  "user": "$(printf '%s' "$USER_NAME")",
  "pid": $$,
  "started_at_jst": "$(printf '%s' "$STARTED_AT_JST")",
  "updated_at_jst": "$(now_jst)",
  "note": "$(printf '%s' "$reason")"
}
EOF
}

on_exit() {
  write_state false "closed"
}

usage() {
  cat <<'EOF'
usage: open_vm_ibkr_vnc_tunnel.sh --host HOST [--user ubuntu] [--key PATH] [--local-port 5901] [--remote-port 5901]

Creates a local SSH tunnel:
  127.0.0.1:${LOCAL_PORT} -> VM 127.0.0.1:${REMOTE_PORT}

Use a VNC client on Mac:
  vnc://127.0.0.1:<chosen-local-port>

If the requested local port is already in use, this script automatically
falls back to the next available local port.

Safety:
  - Does not expose VNC publicly.
  - Does not read or print credentials.
  - Keep this process running while configuring IB Gateway.
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
    --local-port)
      shift
      LOCAL_PORT="${1:-}"
      ;;
    --remote-port)
      shift
      REMOTE_PORT="${1:-}"
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

SSH_OPTS=(-o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3)
if [[ -n "$KEY_PATH" ]]; then
  SSH_OPTS+=(-i "${KEY_PATH/#\~/$HOME}")
fi

REQUESTED_LOCAL_PORT="$LOCAL_PORT"
LOCAL_PORT="$(choose_local_port "$LOCAL_PORT")"
STARTED_AT_JST="$(now_jst)"
trap on_exit EXIT
write_state true "open"

echo "[INFO] opening VNC SSH tunnel"
echo "[INFO] local:  vnc://127.0.0.1:${LOCAL_PORT}"
echo "[INFO] remote: 127.0.0.1:${REMOTE_PORT} on ${USER_NAME}@${HOST}"
echo "[INFO] stop: Ctrl+C"
ssh "${SSH_OPTS[@]}" -N -L "127.0.0.1:${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" "${USER_NAME}@${HOST}"
