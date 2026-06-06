#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PY_BIN="${PY_BIN:-python3}"
NGROK_BIN="${NGROK_BIN:-ngrok}"
STREAMLIT_ADDR="${STREAMLIT_ADDR:-127.0.0.1}"
STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"
UPSTREAM_SCHEME="${UPSTREAM_SCHEME:-auto}" # auto|http|https
AUTO_UPDATE_REDIRECT="${AUTO_UPDATE_REDIRECT:-1}"
AUTO_ENSURE_BRANDING="${AUTO_ENSURE_BRANDING:-1}"
SECRETS_PATH="${SECRETS_PATH:-$ROOT_DIR/.streamlit/secrets.toml}"
STREAMLIT_LOG="${STREAMLIT_LOG:-$ROOT_DIR/run_dashboard_ngrok_streamlit.log}"
NGROK_LOG="${NGROK_LOG:-$ROOT_DIR/run_dashboard_ngrok_tunnel.log}"
SYNC_SCRIPT="${SYNC_SCRIPT:-$ROOT_DIR/tools/sync_dashboard_ngrok_secrets.py}"
STREAMLIT_STARTED_BY_SCRIPT=0
NGROK_STARTED_BY_SCRIPT=0

get_existing_public_url() {
  "$PY_BIN" - <<'PY'
import json
import urllib.request

u = "http://127.0.0.1:4040/api/tunnels"
try:
    with urllib.request.urlopen(u, timeout=0.8) as r:
        obj = json.loads(r.read().decode("utf-8", errors="replace"))
    for t in obj.get("tunnels", []):
        p = str(t.get("public_url", "")).strip()
        if p.startswith("https://"):
            print(p)
            break
except Exception:
    pass
PY
}

if ! command -v "$NGROK_BIN" >/dev/null 2>&1; then
  echo "[ERROR] ngrok not found. install first: brew install ngrok"
  exit 1
fi

echo "[INFO] root: $ROOT_DIR"
echo "[INFO] streamlit target: ${STREAMLIT_ADDR}:${STREAMLIT_PORT} (scheme=${UPSTREAM_SCHEME})"
echo "[INFO] logs:"
echo "  - $STREAMLIT_LOG"
echo "  - $NGROK_LOG"

pick_upstream_scheme() {
  local forced="${UPSTREAM_SCHEME}"
  local health_http="http://${STREAMLIT_ADDR}:${STREAMLIT_PORT}/_stcore/health"
  local health_https="https://${STREAMLIT_ADDR}:${STREAMLIT_PORT}/_stcore/health"
  if [[ "$forced" == "http" ]]; then
    if curl -fsS "$health_http" >/dev/null 2>&1; then
      echo "http"
      return 0
    fi
    return 1
  fi
  if [[ "$forced" == "https" ]]; then
    if curl -kfsS "$health_https" >/dev/null 2>&1; then
      echo "https"
      return 0
    fi
    return 1
  fi

  # auto detect: prefer HTTP, then HTTPS.
  if curl -fsS "$health_http" >/dev/null 2>&1; then
    echo "http"
    return 0
  fi
  if curl -kfsS "$health_https" >/dev/null 2>&1; then
    echo "https"
    return 0
  fi
  return 1
}

cleanup() {
  local code=$?
  if [[ "$NGROK_STARTED_BY_SCRIPT" == "1" && -n "${NGROK_PID:-}" ]]; then
    kill "$NGROK_PID" >/dev/null 2>&1 || true
  fi
  if [[ "$STREAMLIT_STARTED_BY_SCRIPT" == "1" && -n "${STREAMLIT_PID:-}" ]]; then
    kill "$STREAMLIT_PID" >/dev/null 2>&1 || true
  fi
  exit "$code"
}
trap cleanup INT TERM EXIT

DETECTED_SCHEME=""
if DETECTED_SCHEME="$(pick_upstream_scheme)"; then
  echo "[INFO] reusing existing streamlit (${DETECTED_SCHEME}) on ${STREAMLIT_ADDR}:${STREAMLIT_PORT}"
else
  echo "[INFO] starting streamlit..."
  "$PY_BIN" -m streamlit run dashboard.py \
    --server.address "$STREAMLIT_ADDR" \
    --server.port "$STREAMLIT_PORT" \
    --server.headless true >"$STREAMLIT_LOG" 2>&1 &
  STREAMLIT_PID=$!
  STREAMLIT_STARTED_BY_SCRIPT=1
  echo "[INFO] streamlit pid=$STREAMLIT_PID"
fi

for _ in $(seq 1 80); do
  if DETECTED_SCHEME="$(pick_upstream_scheme)"; then
    break
  fi
  sleep 0.25
done

if [[ -z "$DETECTED_SCHEME" ]]; then
  echo "[ERROR] streamlit health check failed at ${STREAMLIT_ADDR}:${STREAMLIT_PORT}"
  echo "[HINT] check log: $STREAMLIT_LOG"
  exit 2
fi

UPSTREAM_URL="${DETECTED_SCHEME}://${STREAMLIT_ADDR}:${STREAMLIT_PORT}"
echo "[INFO] ngrok upstream: ${UPSTREAM_URL}"
PUBLIC_URL="$(get_existing_public_url)"
if [[ -n "$PUBLIC_URL" ]]; then
  echo "[INFO] reusing existing ngrok tunnel: $PUBLIC_URL"
else
  echo "[INFO] starting ngrok tunnel..."
  "$NGROK_BIN" http "$UPSTREAM_URL" --pooling-enabled >"$NGROK_LOG" 2>&1 &
  NGROK_PID=$!
  NGROK_STARTED_BY_SCRIPT=1
  echo "[INFO] ngrok pid=$NGROK_PID"

  for _ in $(seq 1 120); do
    PUBLIC_URL="$(get_existing_public_url)"
    if [[ -n "$PUBLIC_URL" ]]; then
      break
    fi
    sleep 0.25
  done
fi

if [[ -z "$PUBLIC_URL" ]]; then
  echo "[WARN] ngrok public URL not found yet."
  echo "[HINT] open ngrok inspector: http://127.0.0.1:4040"
  if [[ "$NGROK_STARTED_BY_SCRIPT" == "1" ]] && ! kill -0 "$NGROK_PID" >/dev/null 2>&1; then
    echo "[ERROR] ngrok process is not running."
    echo "[HINT] tail -n 80 $NGROK_LOG"
    tail -n 80 "$NGROK_LOG" || true
    exit 3
  fi
else
  REDIRECT_URI="${PUBLIC_URL}/oauth2callback"
  echo "[OK] public url:    $PUBLIC_URL"
  echo "[OK] redirect_uri:  $REDIRECT_URI"
  echo "[INFO] open on iPhone: $PUBLIC_URL"
  echo "[INFO] note: free ngrok shows browser warning page once/7days."

  if [[ "$AUTO_UPDATE_REDIRECT" == "1" && -f "$SECRETS_PATH" ]]; then
    sync_args=(--secrets "$SECRETS_PATH" --public-url "$PUBLIC_URL")
    if [[ "$AUTO_ENSURE_BRANDING" == "1" ]]; then
      sync_args+=(--ensure-branding)
    fi
    if [[ -f "$SYNC_SCRIPT" ]]; then
      "$PY_BIN" "$SYNC_SCRIPT" "${sync_args[@]}" || echo "[WARN] sync_dashboard_ngrok_secrets.py failed"
    else
      echo "[WARN] sync script not found: $SYNC_SCRIPT"
    fi
  fi
fi

echo "[INFO] press Ctrl+C to stop streamlit and ngrok."
if [[ "$NGROK_STARTED_BY_SCRIPT" == "1" ]]; then
  wait "$NGROK_PID"
else
  while true; do
    test_url="$(get_existing_public_url)"
    if [[ -z "$test_url" ]]; then
      echo "[WARN] existing ngrok tunnel is gone."
      exit 4
    fi
    sleep 2
  done
fi
