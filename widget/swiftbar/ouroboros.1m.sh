#!/usr/bin/env bash
set -euo pipefail

MAIN_DIR="${OUROBOROS_MAIN_DIR:-/Users/tani/trading_bot/trading_bot/MAIN}"
PY_BIN="${PY_BIN:-python3}"

exec "$PY_BIN" "$MAIN_DIR/tools/widget_status.py" --main-dir "$MAIN_DIR" --print-swiftbar
