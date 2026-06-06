#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PY_BIN="${PY_BIN:-python3}"

echo "[INFO] starting streamlit on 0.0.0.0:8501"
echo "[INFO] open on iPhone: http://<your-mac-or-vm-ip>:8501"
exec "$PY_BIN" -m streamlit run dashboard.py \
  --server.address 0.0.0.0 \
  --server.port 8501 \
  --server.headless true
