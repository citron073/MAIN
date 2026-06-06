#!/usr/bin/env bash
set -euo pipefail

HOST=""
USER_NAME="ubuntu"
KEY_PATH=""
LOCAL_PORT="${LOCAL_PORT:-17497}"
REMOTE_PORT="${REMOTE_PORT:-7497}"

usage() {
  cat <<'EOF'
usage: open_vm_ibkr_tunnel.sh --host HOST [--user ubuntu] [--key PATH] [--local-port 17497] [--remote-port 7497]

Creates a local SSH tunnel:
  127.0.0.1:${LOCAL_PORT} -> VM 127.0.0.1:${REMOTE_PORT}

Safe notes:
  - Does not expose IB Gateway publicly.
  - Does not place orders.
  - Keep this process running while testing.

Smoke test in another terminal:
  python3 test_ibkr_connection.py --host 127.0.0.1 --port 17497 --client-id 1 --stocks AAPL,MSFT,NVDA,TSLA,QQQ,SPY --fx USDJPY
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

echo "[INFO] opening SSH tunnel"
echo "[INFO] local:  127.0.0.1:${LOCAL_PORT}"
echo "[INFO] remote: 127.0.0.1:${REMOTE_PORT} on ${USER_NAME}@${HOST}"
echo "[INFO] stop: Ctrl+C"
ssh "${SSH_OPTS[@]}" -N -L "127.0.0.1:${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" "${USER_NAME}@${HOST}"
