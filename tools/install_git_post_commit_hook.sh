#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOK_DIR="${MAIN_DIR}/.git/hooks"
HOOK_PATH="${HOOK_DIR}/post-commit"
STAMP="$(date +%Y%m%d_%H%M%S)"

if [[ ! -d "${HOOK_DIR}" ]]; then
  echo "[FAIL] git hooks dir not found: ${HOOK_DIR}" >&2
  exit 1
fi

if [[ -f "${HOOK_PATH}" ]] && ! grep -q "OUROBOROS_POST_COMMIT_HOOK" "${HOOK_PATH}" 2>/dev/null; then
  cp -p "${HOOK_PATH}" "${HOOK_PATH}.bak.${STAMP}"
  echo "[INFO] existing hook backed up: ${HOOK_PATH}.bak.${STAMP}"
fi

cat > "${HOOK_PATH}" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
# OUROBOROS_POST_COMMIT_HOOK

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ "${OUROBOROS_AUTO_CHANGELOG:-1}" == "0" ]]; then
  exit 0
fi

PY_BIN="${PY_BIN:-python3}"
if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PY_BIN="${REPO_ROOT}/.venv/bin/python"
fi

"${PY_BIN}" "${REPO_ROOT}/tools/git_post_commit_change_log.py" || true
SH

chmod +x "${HOOK_PATH}"
echo "[OK] installed git post-commit hook: ${HOOK_PATH}"
echo "[INFO] disable temporarily: OUROBOROS_AUTO_CHANGELOG=0 git commit ..."
