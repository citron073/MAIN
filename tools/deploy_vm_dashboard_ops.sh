#!/usr/bin/env bash
set -euo pipefail

MAIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST=""
USER_NAME="ubuntu"
KEY_PATH=""
REMOTE_MAIN=""
APPLY=0

usage() {
  cat <<'EOF'
usage: deploy_vm_dashboard_ops.sh --host HOST --key PATH [--user ubuntu] [--remote-main PATH] [--apply]

Deploy read-only dashboard/monitoring pieces to the VM:
  - unified dashboard static server on :8793
  - IBKR read-only smoke timer against VM-local 127.0.0.1:7497
  - Daily Ops timer
  - IB Gateway watch timer

Safety:
  - no order placement
  - no public 7497 exposure
  - no package install
  - no secrets printing
  - dry-run by default; use --apply to install/restart systemd units
EOF
}

while (($#)); do
  case "$1" in
    --host)
      shift; HOST="${1:-}"
      ;;
    --user)
      shift; USER_NAME="${1:-}"
      ;;
    --key)
      shift; KEY_PATH="${1:-}"
      ;;
    --remote-main)
      shift; REMOTE_MAIN="${1:-}"
      ;;
    --apply)
      APPLY=1
      ;;
    -h|--help)
      usage; exit 0
      ;;
    *)
      echo "[FAIL] unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ -z "${HOST}" || -z "${KEY_PATH}" ]]; then
  echo "[FAIL] --host and --key are required" >&2
  usage >&2
  exit 2
fi

KEY_PATH="${KEY_PATH/#\~/${HOME}}"
REMOTE="${USER_NAME}@${HOST}"
SSH_OPTS=(-o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=8 -i "${KEY_PATH}")

run_ssh() {
  ssh "${SSH_OPTS[@]}" "$@"
}

run_scp() {
  scp "${SSH_OPTS[@]}" "$@"
}

if [[ -z "${REMOTE_MAIN}" ]]; then
  REMOTE_MAIN="$(run_ssh "${REMOTE}" "bash -lc 'for c in \"\$HOME/trading_bot/MAIN\" \"\$HOME/trading_bot/trading_bot/MAIN\"; do if [[ -f \"\$c/test_ibkr_connection.py\" || -f \"\$c/dashboard.py\" ]]; then printf \"%s\" \"\$c\"; exit 0; fi; done'")"
fi
if [[ -z "${REMOTE_MAIN}" ]]; then
  echo "[FAIL] remote MAIN not detected; pass --remote-main" >&2
  exit 3
fi

echo "[INFO] local MAIN=${MAIN_DIR}"
echo "[INFO] remote=${REMOTE}:${REMOTE_MAIN}"
echo "[INFO] apply=${APPLY}"

FILES=(
  "test_ibkr_connection.py"
  "ibkr_adapter.py"
  "tools/daily_ops_check.py"
  "tools/ibkr_gateway_watch.py"
  "tools/unified_dashboard_healthcheck.py"
  "tools/version_consistency_check.py"
  "tools/trade_log_zero_day_review.py"
  "tools/unified_dashboard.html"
  "HANDOVER.json"
  "docs/OUROBOROS_TRADING_SPEC_TABLE.md"
  "tests/test_live_logic_unittest.py"
  "tests/test_widget_status_unittest.py"
  "deploy/systemd/ouroboros-unified-dashboard.service"
  "deploy/systemd/ouroboros-ibkr-readonly-smoke.service"
  "deploy/systemd/ouroboros-ibkr-readonly-smoke.timer"
  "deploy/systemd/ouroboros-daily-ops-check.service"
  "deploy/systemd/ouroboros-daily-ops-check.timer"
  "deploy/systemd/ouroboros-ibkr-gateway-watch.service"
  "deploy/systemd/ouroboros-ibkr-gateway-watch.timer"
)

echo "[RUN] local syntax checks"
python3 -m py_compile \
  "${MAIN_DIR}/test_ibkr_connection.py" \
  "${MAIN_DIR}/ibkr_adapter.py" \
  "${MAIN_DIR}/tools/daily_ops_check.py" \
  "${MAIN_DIR}/tools/ibkr_gateway_watch.py" \
  "${MAIN_DIR}/tools/unified_dashboard_healthcheck.py" \
  "${MAIN_DIR}/tools/version_consistency_check.py" \
  "${MAIN_DIR}/tools/trade_log_zero_day_review.py"

if [[ "${APPLY}" != "1" ]]; then
  echo "[DRY-RUN] would copy:"
  printf '  %s\n' "${FILES[@]}"
  echo "[DRY-RUN] would install/restart:"
  echo "  ouroboros-unified-dashboard.service"
  echo "  ouroboros-ibkr-readonly-smoke.timer"
  echo "  ouroboros-daily-ops-check.timer"
  echo "  ouroboros-ibkr-gateway-watch.timer"
  echo "[INFO] rerun with --apply to deploy"
  exit 0
fi

echo "[RUN] copy files"
for rel in "${FILES[@]}"; do
  src="${MAIN_DIR}/${rel}"
  dst="${REMOTE}:${REMOTE_MAIN}/${rel}"
  echo "  - ${rel}"
  run_scp "${src}" "${dst}"
done

echo "[RUN] remote install/restart/check"
run_ssh -t "${REMOTE}" "bash -s -- '${REMOTE_MAIN}'" <<'EOS'
set -euo pipefail
REMOTE_MAIN="$1"
cd "${REMOTE_MAIN}"

python3 -m py_compile \
  test_ibkr_connection.py \
  ibkr_adapter.py \
  tools/daily_ops_check.py \
  tools/ibkr_gateway_watch.py \
  tools/unified_dashboard_healthcheck.py \
  tools/version_consistency_check.py \
  tools/trade_log_zero_day_review.py

units=(
  ouroboros-unified-dashboard.service
  ouroboros-ibkr-readonly-smoke.service
  ouroboros-ibkr-readonly-smoke.timer
  ouroboros-daily-ops-check.service
  ouroboros-daily-ops-check.timer
  ouroboros-ibkr-gateway-watch.service
  ouroboros-ibkr-gateway-watch.timer
)

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT
for unit in "${units[@]}"; do
  sed -E \
    -e "s|/home/ubuntu/trading_bot/MAIN|${REMOTE_MAIN}|g" \
    -e "s|/home/ubuntu/trading_bot/trading_bot/MAIN|${REMOTE_MAIN}|g" \
    -e "s|^User=.*|User=$(whoami)|g" \
    "deploy/systemd/${unit}" > "${tmpdir}/${unit}"
  sudo cp "${tmpdir}/${unit}" "/etc/systemd/system/${unit}"
done

sudo systemctl daemon-reload
sudo systemctl enable --now ouroboros-unified-dashboard.service
sudo systemctl enable --now ouroboros-ibkr-readonly-smoke.timer
sudo systemctl enable --now ouroboros-daily-ops-check.timer
sudo systemctl enable --now ouroboros-ibkr-gateway-watch.timer

sudo systemctl start ouroboros-ibkr-readonly-smoke.service || true
sudo systemctl start ouroboros-daily-ops-check.service || true
sudo systemctl start ouroboros-ibkr-gateway-watch.service || true

echo "[INFO] services"
systemctl --no-pager --full status ouroboros-unified-dashboard.service | sed -n '1,14p' || true
echo "[INFO] timers"
systemctl list-timers --all | grep -E 'ouroboros-(ibkr-readonly-smoke|daily-ops-check|ibkr-gateway-watch)' || true
echo "[INFO] latest daily ops"
python3 tools/daily_ops_check.py --url http://127.0.0.1:8793/tools/unified_dashboard.html --timeout-sec 15 | sed -n '1,180p'
EOS

echo "[OK] VM dashboard ops deployed"
