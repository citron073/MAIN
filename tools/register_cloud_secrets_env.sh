#!/usr/bin/env bash
set -euo pipefail

TARGET_PATH="${1:-/etc/ouroboros/secrets.env}"

echo "[INFO] Register bitFlyer API credentials to cloud env file"
echo "[INFO] target: ${TARGET_PATH}"
echo "[INFO] This script does NOT place secrets in command arguments."
echo "[INFO] Input is hidden. File permission will be forced to 600."
read -r -p "Continue? [y/N]: " ans
if [[ "${ans:-}" != "y" && "${ans:-}" != "Y" ]]; then
  echo "[ABORT] canceled."
  exit 1
fi

read -r -s -p "[STEP] Enter BITFLYER API KEY: " API_KEY
echo
read -r -s -p "[STEP] Enter BITFLYER API SECRET: " API_SECRET
echo

if [[ -z "${API_KEY}" || -z "${API_SECRET}" ]]; then
  echo "[FAIL] empty input."
  exit 2
fi

escape_sq() {
  printf "%s" "$1" | sed "s/'/'\"'\"'/g"
}

target_dir="$(dirname "${TARGET_PATH}")"
tmp_file="$(mktemp)"
cleanup() {
  rm -f "${tmp_file}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

{
  echo "# Ouroboros private secrets (outside repo)"
  echo "OUROBOROS_SECRET_PROVIDER=ENV"
  echo "OUROBOROS_BITFLYER_API_KEY='$(escape_sq "${API_KEY}")'"
  echo "OUROBOROS_BITFLYER_API_SECRET='$(escape_sq "${API_SECRET}")'"
} > "${tmp_file}"

if [[ ! -d "${target_dir}" ]]; then
  mkdir -p "${target_dir}" 2>/dev/null || {
    echo "[FAIL] cannot create directory: ${target_dir}"
    echo "[HINT] run with sudo or use writable path as first arg."
    exit 3
  }
fi

if ! cp "${tmp_file}" "${TARGET_PATH}" 2>/dev/null; then
  echo "[FAIL] cannot write: ${TARGET_PATH}"
  echo "[HINT] run with sudo:"
  echo "  sudo $0 ${TARGET_PATH}"
  exit 4
fi

chmod 600 "${TARGET_PATH}" 2>/dev/null || true
echo "[OK] saved: ${TARGET_PATH}"
echo "[NEXT] systemd service should include:"
echo "  EnvironmentFile=-${TARGET_PATH}"
echo "[NEXT] verify:"
echo "  python3 tools/live_preflight.py"
