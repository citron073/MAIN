#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOK_DIR="${MAIN_DIR}/.git/hooks"
HOOK_PATH="${HOOK_DIR}/post-commit"

if [[ ! -f "${HOOK_PATH}" ]]; then
  echo "[INFO] hook not found: ${HOOK_PATH}"
  exit 0
fi

if ! grep -q "OUROBOROS_POST_COMMIT_HOOK" "${HOOK_PATH}" 2>/dev/null; then
  echo "[WARN] post-commit hook is not managed by ouroboros. skip."
  exit 0
fi

rm -f "${HOOK_PATH}"
echo "[OK] removed managed hook: ${HOOK_PATH}"

latest_bak="$(ls -1t "${HOOK_PATH}".bak.* 2>/dev/null | head -n 1 || true)"
if [[ -n "${latest_bak}" ]]; then
  cp -p "${latest_bak}" "${HOOK_PATH}"
  chmod +x "${HOOK_PATH}"
  echo "[OK] restored backup hook: ${latest_bak}"
fi
