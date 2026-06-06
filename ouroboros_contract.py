from __future__ import annotations

from typing import Any, Dict, Optional


OUROBOROS_BOT_VERSION = "2026.06.07.1"
OUROBOROS_FEATURE_SCHEMA_VERSION = (
    "ohlc-chart-pattern-quality-market-phase-transition-near-tp-aiba-"
    "phase-fallback-mfe-mae-fib-elliott-v1"
)

TRADE_LOG_REQUIRED_FIELDS = [
    "time",
    "result",
    "side",
    "price",
    "size",
    "ltp",
    "best_bid",
    "best_ask",
    "spread_pct",
    "limit_pct",
    "ma_fast",
    "ma_slow",
    "trend",
    "signal",
    "note",
    "pos_id",
]

TRADE_LOG_EXTENSION_FIELDS = [
    "is_shadow",
]

TRADE_LOG_FIELDS = [
    *TRADE_LOG_REQUIRED_FIELDS,
    *TRADE_LOG_EXTENSION_FIELDS,
]

RESULT_ALLOWED = {
    "PAPER",
    "PAPER_ENTRY",
    "HOLD_OPEN_POS",
    "OBSERVE_NO_SIGNAL",
    "OBSERVE_OK",
    "OBSERVE_MR",
    "OBSERVE_MR_FILTER_NG",
    "OBSERVE_MR_TRIGGER",
    "OBSERVE_PHASE_B",
    "OBSERVE_TIME_BLOCK",
    "OBSERVE_BUY_FAST_MA_NEAR",
    "OBSERVE_SELL_FAST_MA_NEAR",
    "OBSERVE_TREND_FLIP_COOLDOWN",
    "OBSERVE_TREND_STRENGTH_WEAK",
    "OBSERVE_TRADE_DISABLED",
    "OBSERVE_AI_BLOCK",
    "AI_BLOCKED",
    "SKIP_OUT_OF_TIME",
    "SKIP_TODAY_OFF",
    "SKIP_NEWS",
    "SKIP_SPREAD",
    "SKIP_DAILY_LIMIT",
    "SKIP_TICKER_INCOMPLETE",
    "SKIP_ALREADY_RUNNING",
    "SKIP_COOLDOWN",
    "SKIP_ORPHAN_DETECTED",
    "PAPER_EXIT_TP",
    "PAPER_EXIT_SL",
    "PAPER_EXIT_TIMEOUT",
    "PAPER_EXIT_PARTIAL_TP",
    "PAPER_EXIT_EOD",
    "PAPER_EXIT_PRENEWS",
    "PAPER_EXIT_EARLY_ADVERSE",
    "ERROR_OPEN_POS_BROKEN",
    "MANUAL_CLEAR_OPEN_POS",
}


def build_audit_issue(
    code: str,
    severity: str,
    message: str,
    evidence: Optional[Dict[str, Any]] = None,
    *,
    include_legacy_context: bool = True,
) -> Dict[str, Any]:
    payload_evidence = evidence or {}
    payload: Dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
        "evidence": payload_evidence,
    }
    if include_legacy_context:
        payload["context"] = payload_evidence
    pos_id = payload_evidence.get("pos_id") if isinstance(payload_evidence, dict) else None
    if pos_id:
        payload["pos_id"] = pos_id
    return payload
