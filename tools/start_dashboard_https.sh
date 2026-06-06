#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PY_BIN="${PY_BIN:-python3}"
ADDRESS="${ADDRESS:-0.0.0.0}"
PORT="${PORT:-8501}"
CERT_DIR="${CERT_DIR:-$ROOT_DIR/.streamlit/certs}"
CERT_FILE="${CERT_FILE:-$CERT_DIR/dashboard.crt}"
KEY_FILE="${KEY_FILE:-$CERT_DIR/dashboard.key}"

LAN_IP="${LAN_IP:-}"
if [[ -z "${LAN_IP}" ]]; then
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
fi
if [[ -z "${LAN_IP}" ]]; then
  LAN_IP="$(ipconfig getifaddr en1 2>/dev/null || true)"
fi

mkdir -p "$CERT_DIR"

gen_self_signed() {
  local san
  local tmp
  san="DNS:localhost,IP:127.0.0.1"
  if [[ -n "${LAN_IP}" ]]; then
    san="${san},IP:${LAN_IP}"
  fi
  tmp="$(mktemp)"
  cat >"$tmp" <<EOF
[req]
distinguished_name=req_distinguished_name
x509_extensions=v3_req
prompt=no

[req_distinguished_name]
CN=ouroboros-dashboard.local

[v3_req]
subjectAltName=${san}
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
EOF
  openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
    -keyout "$KEY_FILE" -out "$CERT_FILE" -config "$tmp"
  rm -f "$tmp"
}

if [[ ! -s "$CERT_FILE" || ! -s "$KEY_FILE" ]]; then
  if command -v mkcert >/dev/null 2>&1; then
    echo "[INFO] generating TLS cert via mkcert"
    mkcert -install >/dev/null 2>&1 || true
    if [[ -n "${LAN_IP}" ]]; then
      mkcert -cert-file "$CERT_FILE" -key-file "$KEY_FILE" localhost 127.0.0.1 "${LAN_IP}"
    else
      mkcert -cert-file "$CERT_FILE" -key-file "$KEY_FILE" localhost 127.0.0.1
    fi
  else
    echo "[WARN] mkcert not found. generating self-signed cert"
    gen_self_signed
  fi
fi

echo "[INFO] starting streamlit HTTPS on ${ADDRESS}:${PORT}"
echo "[INFO] local:   https://localhost:${PORT}"
if [[ -n "${LAN_IP}" ]]; then
  echo "[INFO] iPhone:  https://${LAN_IP}:${PORT}"
fi
echo "[INFO] cert:    ${CERT_FILE}"
echo "[INFO] key:     ${KEY_FILE}"

exec "$PY_BIN" -m streamlit run dashboard.py \
  --server.address "$ADDRESS" \
  --server.port "$PORT" \
  --server.headless true \
  --server.sslCertFile "$CERT_FILE" \
  --server.sslKeyFile "$KEY_FILE"
