#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="${1:-fast}"
HARNESS_DIR="$ROOT_DIR/.harness"
LOG_PATH="$HARNESS_DIR/last_validate.log"
mkdir -p "$HARNESS_DIR"

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

run_cmd() {
  echo ""
  echo "[harness] $*"
  "$@"
}

run_node_check() {
  if have_cmd node && [[ -f widget/scriptable/OuroborosWidget.local.js ]]; then
    run_cmd node --check widget/scriptable/OuroborosWidget.local.js
  else
    echo "[harness] SKIP node --check: node or widget script not found"
  fi
}

run_json_check() {
  if [[ -f HANDOVER.json ]]; then
    echo ""
    echo "[harness] python3 -m json.tool HANDOVER.json >/dev/null"
    python3 -m json.tool HANDOVER.json >/dev/null
  fi
}

run_core_py_compile() {
  run_cmd python3 -m py_compile \
    bot.py \
    ouroboros_contract.py \
    ibkr_paper_adapter.py \
    test_ibkr_connection.py \
    tools/notification_policy.py \
    tools/harness_quality_check.py \
    tools/harness_work_items.py \
    tools/harness_spec_template.py \
    tools/react_frontend_harness_check.py \
    tools/effective_config_dump.py \
    tools/local_llm_healthcheck.py \
    tools/local_llm_trade_review.py \
    tools/llm_reflection_audit.py \
    tools/shadow_promotion_report.py \
    tools/trade_system_review.py \
    tools/trade_event_notifier.py \
    tools/daily_ops_check.py \
    tools/ibkr_gateway_watch.py \
    tools/ibkr_import_audit.py \
    tools/vm_ibkr_gateway_readiness.py \
    tools/version_consistency_check.py \
    tools/time_block_review.py \
    tools/stale_artifact_review.py \
    tools/archive_stale_artifacts.py \
    tools/widget_status.py \
    tools/mr_observe_summary.py \
    tools/llm_provider.py
}

run_fast_tests() {
  run_cmd python3 -m unittest \
    tests.test_version_consistency_check_unittest \
    tests.test_harness_quality_check_unittest \
    tests.test_harness_work_items_unittest \
    tests.test_harness_spec_template_unittest \
    tests.test_react_frontend_harness_check_unittest \
    tests.test_effective_config_dump_unittest \
    tests.test_local_llm_healthcheck_unittest \
    tests.test_local_llm_trade_review_unittest \
    tests.test_llm_reflection_audit_unittest \
    tests.test_shadow_promotion_report_unittest \
    tests.test_trade_system_review_unittest \
    tests.test_live_logic_unittest \
    tests.test_trade_event_notifier_unittest \
    tests.test_trade_log_zero_day_review_unittest \
    tests.test_signal_scanner_weekly_unittest \
    tests.test_signal_scanner_outcome_unittest \
    tests.test_daily_ops_check_unittest \
    tests.test_ibkr_gateway_watch_unittest \
    tests.test_ibkr_import_audit_unittest \
    tests.test_vm_ibkr_gateway_readiness_unittest \
    tests.test_ibkr_connection_unittest \
    tests.test_time_block_review_unittest \
    tests.test_stale_artifact_review_unittest \
    tests.test_archive_stale_artifacts_unittest \
    tests.test_notification_policy_unittest \
    tests.test_widget_status_unittest
}

run_trade_tests() {
  run_cmd python3 -m unittest \
    tests.test_version_consistency_check_unittest \
    tests.test_harness_quality_check_unittest \
    tests.test_harness_work_items_unittest \
    tests.test_harness_spec_template_unittest \
    tests.test_react_frontend_harness_check_unittest \
    tests.test_effective_config_dump_unittest \
    tests.test_local_llm_healthcheck_unittest \
    tests.test_local_llm_trade_review_unittest \
    tests.test_llm_reflection_audit_unittest \
    tests.test_shadow_promotion_report_unittest \
    tests.test_trade_system_review_unittest \
    tests.test_live_logic_unittest \
    tests.test_trade_event_notifier_unittest \
    tests.test_trade_log_zero_day_review_unittest \
    tests.test_signal_scanner_weekly_unittest \
    tests.test_signal_scanner_outcome_unittest \
    tests.test_daily_ops_check_unittest \
    tests.test_ibkr_gateway_watch_unittest \
    tests.test_ibkr_import_audit_unittest \
    tests.test_vm_ibkr_gateway_readiness_unittest \
    tests.test_ibkr_connection_unittest \
    tests.test_time_block_review_unittest \
    tests.test_stale_artifact_review_unittest \
    tests.test_archive_stale_artifacts_unittest \
    tests.test_notification_policy_unittest \
    tests.test_widget_status_unittest \
    tests.test_mr_observe_summary_unittest \
    tests.test_weekly_auto_feedback_unittest \
    tests.test_llm_provider_unittest \
    tests.test_apply_daily_reflection_unittest \
    tests.test_drift_resume_summary_unittest \
    tests.test_morning_start_guard_unittest \
    tests.test_print_widget_tailscale_info_unittest
}

main() {
  echo "[harness] mode=$MODE"
  echo "[harness] root=$ROOT_DIR"
  echo "[harness] log=$LOG_PATH"
  echo "[harness] started_at=$(date '+%Y-%m-%d %H:%M:%S %Z')"

  case "$MODE" in
    fast)
      run_core_py_compile
      run_json_check
      run_cmd python3 tools/version_consistency_check.py
      run_node_check
      run_fast_tests
      ;;
    trade)
      run_core_py_compile
      run_json_check
      run_cmd python3 tools/version_consistency_check.py
      run_node_check
      run_trade_tests
      ;;
    all-tests)
      run_core_py_compile
      run_json_check
      run_node_check
      run_cmd python3 -m unittest discover tests
      ;;
    lint)
      if have_cmd ruff; then
        run_cmd ruff check bot.py tools tests
      else
        run_cmd python3 -m ruff check bot.py tools tests
      fi
      ;;
    typecheck)
      if have_cmd mypy; then
        run_cmd mypy bot.py tools
      else
        run_cmd python3 -m mypy bot.py tools
      fi
      ;;
    *)
      echo "[harness] unknown mode: $MODE" >&2
      echo "usage: ./scripts/validate.sh [fast|trade|all-tests|lint|typecheck]" >&2
      exit 2
      ;;
  esac

  echo ""
  echo "[harness] completed_at=$(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "[harness] OK"
}

main 2>&1 | tee "$LOG_PATH"
exit "${PIPESTATUS[0]}"
