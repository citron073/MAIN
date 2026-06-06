#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.trade_event_notifier import _build_daily_trade_review

DEFAULT_MAIN_LOGS_DIR = ROOT_DIR.parent / "logs"
DEFAULT_SHADOW_LOGS_DIR = ROOT_DIR.parent / "logs" / "instances" / "shadow"


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except Exception:
        return int(default)


def _log_days(logs_dir: Path) -> List[str]:
    if not logs_dir.exists():
        return []
    days: List[str] = []
    for path in logs_dir.glob("trade_log_*.csv"):
        m = re.match(r"trade_log_(\d{8})\.csv$", path.name)
        if m:
            days.append(m.group(1))
    return sorted(set(days))


def _note_value(note: str, key: str) -> str:
    m = re.search(rf"\b{re.escape(key)}=([^\s]+)\b", str(note or ""))
    return m.group(1) if m else ""


def _read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _classify_shadow_sl(
    logs_dir: Path,
    days: List[str],
    *,
    reversal_wrap_th: float = 0.033,
    profit_miss_th: float = 0.077,
) -> Dict[str, Any]:
    """Classify PAPER_EXIT_SL rows by best_fav into reversal_wrap / middle / profit_miss.

    reversal_wrap : best_fav < reversal_wrap_th  (never progressed — entry direction wrong)
    profit_miss   : best_fav >= profit_miss_th   (reached significant profit then gave back to SL)
    middle        : between the two thresholds
    Default thresholds are ~15% and ~35% of TP=0.220%.
    """
    total = 0
    reversal_wrap_n = 0
    profit_miss_n = 0
    middle_n = 0

    for day8 in days:
        for row in _read_csv_rows(logs_dir / f"trade_log_{day8}.csv"):
            if str(row.get("result", "") or "") != "PAPER_EXIT_SL":
                continue
            note = str(row.get("note", "") or "")
            bf_str = _note_value(note, "best_fav")
            try:
                best_fav = float(bf_str)
            except (ValueError, TypeError):
                best_fav = 0.0
            total += 1
            if best_fav < reversal_wrap_th:
                reversal_wrap_n += 1
            elif best_fav >= profit_miss_th:
                profit_miss_n += 1
            else:
                middle_n += 1

    return {
        "sl_n": total,
        "reversal_wrap_n": reversal_wrap_n,
        "middle_n": middle_n,
        "profit_miss_n": profit_miss_n,
        "reversal_wrap_pct": round(reversal_wrap_n / total * 100.0, 2) if total > 0 else 0.0,
        "profit_miss_pct": round(profit_miss_n / total * 100.0, 2) if total > 0 else 0.0,
        "thresholds": {
            "reversal_wrap_best_fav_lt": reversal_wrap_th,
            "profit_miss_best_fav_gte": profit_miss_th,
        },
    }


def _mr_counts_from_logs(logs_dir: Path, days: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "mr_rows_total": 0,
        "mr_trigger_n": 0,
        "mr_rank_a_n": 0,
        "mr_rank_b_n": 0,
        "mr_rank_c_n": 0,
    }
    for day8 in days:
        for row in _read_csv_rows(logs_dir / f"trade_log_{day8}.csv"):
            result = str(row.get("result", "") or "")
            if not result.startswith("OBSERVE_MR"):
                continue
            out["mr_rows_total"] += 1
            if result == "OBSERVE_MR_TRIGGER":
                out["mr_trigger_n"] += 1
            rank = _note_value(str(row.get("note", "") or ""), "mr_rank").upper()
            if rank == "A":
                out["mr_rank_a_n"] += 1
            elif rank == "B":
                out["mr_rank_b_n"] += 1
            elif rank == "C":
                out["mr_rank_c_n"] += 1
    return out


def resolve_days(main_logs_dir: Path, shadow_logs_dir: Path, *, days: Optional[List[str]] = None, lookback_days: int = 3) -> List[str]:
    if days:
        return sorted({str(d).strip() for d in days if str(d).strip()})
    all_days = sorted(set(_log_days(main_logs_dir)) | set(_log_days(shadow_logs_dir)))
    if lookback_days <= 0:
        return all_days
    return all_days[-int(lookback_days):]


def _empty_aggregate() -> Dict[str, Any]:
    return {
        "active_days": 0,
        "closed_n": 0,
        "win_n": 0,
        "loss_n": 0,
        "pnl_jpy_sum": 0.0,
        "ret_sum_pct": 0.0,
        "avg_ret_pct": 0.0,
        "mfe_sum_pct": 0.0,
        "mae_proxy_sum_pct": 0.0,
        "giveback_sum_pct": 0.0,
        "avg_mfe_pct": 0.0,
        "avg_mae_proxy_pct": 0.0,
        "avg_giveback_pct": 0.0,
        "progress_reached_n": 0,
        "win_rate_pct": 0.0,
        "gross_profit_jpy": 0.0,
        "gross_loss_jpy": 0.0,
        "profit_factor_jpy": 0.0,
        "tp_n": 0,
        "sl_n": 0,
        "timeout_n": 0,
        "tp_rate_pct": 0.0,
        "sl_rate_pct": 0.0,
        "timeout_rate_pct": 0.0,
        "near_tp_giveback_exit_n": 0,
        "no_follow_through_exit_n": 0,
        "progress_reversal_exit_n": 0,
        "progress_timeout_n": 0,
        "weak_progress_exit_n": 0,
        "observe_trend_strength_weak_n": 0,
        "observe_ai_block_htf60_countertrend_n": 0,
        "observe_ai_block_htf15_60_conflict_n": 0,
    }


def _merge_counter_row(dst: Dict[str, Any], src: Dict[str, Any]) -> None:
    for key in ("n", "win_n", "loss_n", "flat_n", "TP", "SL", "TIMEOUT", "OTHER"):
        dst[key] = int(_safe_int(dst.get(key), 0)) + int(_safe_int(src.get(key), 0))
    for key in ("ret_sum_pct", "pnl_jpy_sum", "mfe_sum_pct", "mae_proxy_sum_pct", "giveback_sum_pct"):
        dst[key] = float(_safe_float(dst.get(key), 0.0)) + float(_safe_float(src.get(key), 0.0))
    for key in ("mfe_n", "mae_proxy_n", "giveback_n"):
        dst[key] = int(_safe_int(dst.get(key), 0)) + int(_safe_int(src.get(key), 0))


def _finalize_feature_table(table: Dict[str, Dict[str, Any]], *, limit: int = 20) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for label, raw in table.items():
        n = int(_safe_int(raw.get("n"), 0))
        if n <= 0:
            continue
        win_n = int(_safe_int(raw.get("win_n"), 0))
        pnl = float(_safe_float(raw.get("pnl_jpy_sum"), 0.0))
        ret_sum = float(_safe_float(raw.get("ret_sum_pct"), 0.0))
        rows.append(
            {
                "label": str(label),
                "n": n,
                "win_n": win_n,
                "loss_n": int(_safe_int(raw.get("loss_n"), 0)),
                "win_rate_pct": round(float(win_n) / float(n) * 100.0, 4),
                "pnl_jpy_sum": round(pnl, 6),
                "ret_sum_pct": round(ret_sum, 6),
                "avg_ret_pct": round(ret_sum / float(n), 6),
                "avg_mfe_pct": round(float(_safe_float(raw.get("mfe_sum_pct"), 0.0)) / float(max(1, _safe_int(raw.get("mfe_n"), 0))), 6)
                if _safe_int(raw.get("mfe_n"), 0) > 0
                else 0.0,
                "avg_mae_proxy_pct": round(
                    float(_safe_float(raw.get("mae_proxy_sum_pct"), 0.0)) / float(max(1, _safe_int(raw.get("mae_proxy_n"), 0))),
                    6,
                )
                if _safe_int(raw.get("mae_proxy_n"), 0) > 0
                else 0.0,
                "avg_giveback_pct": round(
                    float(_safe_float(raw.get("giveback_sum_pct"), 0.0)) / float(max(1, _safe_int(raw.get("giveback_n"), 0))),
                    6,
                )
                if _safe_int(raw.get("giveback_n"), 0) > 0
                else 0.0,
                "TP": int(_safe_int(raw.get("TP"), 0)),
                "SL": int(_safe_int(raw.get("SL"), 0)),
                "TIMEOUT": int(_safe_int(raw.get("TIMEOUT"), 0)),
            }
        )
    rows.sort(key=lambda r: (-int(r["n"]), -abs(float(r["pnl_jpy_sum"])), str(r["label"])))
    return rows[: int(limit)]


def _aggregate_reviews(reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = _empty_aggregate()
    feature_table: Dict[str, Dict[str, Any]] = defaultdict(dict)
    phase_table: Dict[str, Dict[str, Any]] = defaultdict(dict)
    for review in reviews:
        if _safe_int(review.get("active_row_n"), 0) > 0 or _safe_int(review.get("closed_n"), 0) > 0:
            out["active_days"] += 1
        out["closed_n"] += _safe_int(review.get("closed_n"), 0)
        out["win_n"] += _safe_int(review.get("win_n"), 0)
        out["loss_n"] += _safe_int(review.get("loss_n"), 0)
        out["pnl_jpy_sum"] += _safe_float(review.get("pnl_jpy_sum"), 0.0)
        out["ret_sum_pct"] += _safe_float(review.get("ret_sum_pct"), 0.0)
        out["mfe_sum_pct"] += _safe_float(review.get("mfe_sum_pct"), 0.0)
        out["mae_proxy_sum_pct"] += _safe_float(review.get("mae_proxy_sum_pct"), 0.0)
        out["giveback_sum_pct"] += _safe_float(review.get("giveback_sum_pct"), 0.0)
        out["progress_reached_n"] += _safe_int(review.get("progress_reached_n"), 0)
        out["gross_profit_jpy"] += _safe_float(review.get("gross_profit_jpy"), 0.0)
        out["gross_loss_jpy"] += _safe_float(review.get("gross_loss_jpy"), 0.0)
        out["near_tp_giveback_exit_n"] += _safe_int(review.get("near_tp_giveback_exit_n"), 0)
        out["no_follow_through_exit_n"] += _safe_int(review.get("no_follow_through_exit_n"), 0)
        out["progress_reversal_exit_n"] += _safe_int(review.get("progress_reversal_exit_n"), 0)
        out["progress_timeout_n"] += _safe_int(review.get("progress_timeout_n"), 0)
        out["weak_progress_exit_n"] += _safe_int(review.get("weak_progress_exit_n"), 0)
        out["observe_trend_strength_weak_n"] += _safe_int(review.get("observe_trend_strength_weak_n"), 0)
        out["observe_ai_block_htf60_countertrend_n"] += _safe_int(review.get("observe_ai_block_htf60_countertrend_n"), 0)
        out["observe_ai_block_htf15_60_conflict_n"] += _safe_int(review.get("observe_ai_block_htf15_60_conflict_n"), 0)
        breakdown = review.get("exit_reason_breakdown") if isinstance(review.get("exit_reason_breakdown"), dict) else {}
        out["tp_n"] += _safe_int(breakdown.get("TP"), 0)
        out["sl_n"] += _safe_int(breakdown.get("SL"), 0)
        out["timeout_n"] += _safe_int(breakdown.get("TIMEOUT"), 0)
        tf = review.get("technical_feature_outcomes")
        if isinstance(tf, dict):
            for label, row in tf.items():
                if isinstance(row, dict):
                    _merge_counter_row(feature_table[str(label)], row)
        ph = review.get("market_phase_outcomes")
        if isinstance(ph, dict):
            for label, row in ph.items():
                if isinstance(row, dict):
                    _merge_counter_row(phase_table[str(label)], row)

    closed_n = max(0, int(out["closed_n"]))
    if closed_n > 0:
        out["avg_ret_pct"] = round(float(out["ret_sum_pct"]) / float(closed_n), 6)
        out["avg_mfe_pct"] = round(float(out["mfe_sum_pct"]) / float(closed_n), 6)
        out["avg_mae_proxy_pct"] = round(float(out["mae_proxy_sum_pct"]) / float(closed_n), 6)
        out["avg_giveback_pct"] = round(float(out["giveback_sum_pct"]) / float(closed_n), 6)
        out["win_rate_pct"] = round(float(out["win_n"]) / float(closed_n) * 100.0, 4)
        out["tp_rate_pct"] = round(float(out["tp_n"]) / float(closed_n) * 100.0, 4)
        out["sl_rate_pct"] = round(float(out["sl_n"]) / float(closed_n) * 100.0, 4)
        out["timeout_rate_pct"] = round(float(out["timeout_n"]) / float(closed_n) * 100.0, 4)
    abs_loss = abs(float(out["gross_loss_jpy"]))
    out["profit_factor_jpy"] = round(
        (float(out["gross_profit_jpy"]) / abs_loss) if abs_loss > 0 else (8.0 if float(out["gross_profit_jpy"]) > 0 else 0.0),
        6,
    )
    out["pnl_jpy_sum"] = round(float(out["pnl_jpy_sum"]), 6)
    out["ret_sum_pct"] = round(float(out["ret_sum_pct"]), 6)
    out["mfe_sum_pct"] = round(float(out["mfe_sum_pct"]), 6)
    out["mae_proxy_sum_pct"] = round(float(out["mae_proxy_sum_pct"]), 6)
    out["giveback_sum_pct"] = round(float(out["giveback_sum_pct"]), 6)
    out["feature_outcomes_top"] = _finalize_feature_table(feature_table, limit=20)
    out["market_phase_outcomes"] = _finalize_feature_table(phase_table, limit=8)
    return out


def _build_feature_gate_review(shadow: Dict[str, Any]) -> Dict[str, Any]:
    feature_rows = shadow.get("feature_outcomes_top") if isinstance(shadow.get("feature_outcomes_top"), list) else []
    phase_rows = shadow.get("market_phase_outcomes") if isinstance(shadow.get("market_phase_outcomes"), list) else []
    aiba_rows = [row for row in feature_rows if str(row.get("label", "")).startswith("aiba_")][:6]
    cp_rows = [row for row in feature_rows if str(row.get("label", "")).startswith("pattern")][:4]
    phase_feature_rows = [row for row in feature_rows if str(row.get("label", "")).startswith("phase")][:6]
    watch: List[str] = []
    for row in phase_rows:
        if str(row.get("label")) == "B" and _safe_int(row.get("n"), 0) > 0:
            watch.append(f"phase_B_seen n={_safe_int(row.get('n'), 0)} pnl={_safe_float(row.get('pnl_jpy_sum'), 0.0):+.0f}")
    for row in aiba_rows:
        if _safe_int(row.get("n"), 0) >= 3 and _safe_float(row.get("avg_ret_pct"), 0.0) < 0:
            watch.append(f"aiba_negative {row.get('label')} avg={_safe_float(row.get('avg_ret_pct'), 0.0):+.4f}")
    if _safe_int(shadow.get("near_tp_giveback_exit_n"), 0) > 0:
        watch.append(f"near_tp_giveback_exit_n={_safe_int(shadow.get('near_tp_giveback_exit_n'), 0)}")
    return {
        "status": "REPORT_ONLY",
        "decision_impact": "none",
        "phase_top": phase_rows[:6],
        "phase_feature_top": phase_feature_rows,
        "aiba_top": aiba_rows,
        "chart_pattern_top": cp_rows,
        "exit_tech": {
            "near_tp_giveback_exit_n": _safe_int(shadow.get("near_tp_giveback_exit_n"), 0),
            "no_follow_through_exit_n": _safe_int(shadow.get("no_follow_through_exit_n"), 0),
            "progress_reversal_exit_n": _safe_int(shadow.get("progress_reversal_exit_n"), 0),
            "progress_timeout_n": _safe_int(shadow.get("progress_timeout_n"), 0),
            "weak_progress_exit_n": _safe_int(shadow.get("weak_progress_exit_n"), 0),
            "progress_reached_n": _safe_int(shadow.get("progress_reached_n"), 0),
            "avg_mfe_pct": _safe_float(shadow.get("avg_mfe_pct"), 0.0),
            "avg_mae_proxy_pct": _safe_float(shadow.get("avg_mae_proxy_pct"), 0.0),
            "avg_giveback_pct": _safe_float(shadow.get("avg_giveback_pct"), 0.0),
        },
        "watch": watch,
    }


def _decide(
    *,
    main: Dict[str, Any],
    shadow: Dict[str, Any],
    min_days: int,
    min_closed: int,
    min_pf: float,
    min_win_rate_pct: float,
    max_sl_rate_pct: float,
    min_mr_rank_a: int,
) -> Dict[str, Any]:
    reasons: List[str] = []
    decision = "WAIT"
    shadow_closed = _safe_int(shadow.get("closed_n"), 0)
    shadow_active_days = _safe_int(shadow.get("active_days"), 0)
    shadow_pf = _safe_float(shadow.get("profit_factor_jpy"), 0.0)
    shadow_pnl = _safe_float(shadow.get("pnl_jpy_sum"), 0.0)
    shadow_win = _safe_float(shadow.get("win_rate_pct"), 0.0)
    shadow_sl = _safe_int(shadow.get("sl_n"), 0)
    sl_rate = _safe_float(shadow.get("sl_rate_pct"), 0.0)
    main_closed = _safe_int(main.get("closed_n"), 0)
    main_avg = _safe_float(main.get("avg_ret_pct"), 0.0)
    shadow_avg = _safe_float(shadow.get("avg_ret_pct"), 0.0)

    if shadow_active_days < int(min_days):
        reasons.append(f"active_days<{int(min_days)} ({shadow_active_days})")
    if shadow_closed < int(min_closed):
        reasons.append(f"closed_n<{int(min_closed)} ({shadow_closed})")
    if shadow_pnl <= 0:
        reasons.append(f"pnl_jpy_sum<=0 ({shadow_pnl:+.0f})")
    if shadow_pf < float(min_pf):
        reasons.append(f"profit_factor<{float(min_pf):.2f} ({shadow_pf:.2f})")
    if shadow_win < float(min_win_rate_pct):
        reasons.append(f"win_rate<{float(min_win_rate_pct):.1f}% ({shadow_win:.1f}%)")
    if sl_rate > float(max_sl_rate_pct):
        reasons.append(f"sl_rate>{float(max_sl_rate_pct):.1f}% ({sl_rate:.1f}%)")
    if int(min_mr_rank_a) > 0 and _safe_int(shadow.get("mr_rank_a_n"), 0) < int(min_mr_rank_a):
        reasons.append(f"mr_rank_a_n<{int(min_mr_rank_a)} ({_safe_int(shadow.get('mr_rank_a_n'), 0)})")
    if main_closed > 0 and shadow_avg < (main_avg - 0.02):
        reasons.append(f"shadow_avg_ret worse than main ({shadow_avg:+.4f} < {main_avg:+.4f})")

    if not reasons:
        decision = "OK"
        reasons.append("shadow promotion candidate; still require human review before main-live")
    elif shadow_closed >= int(min_closed) and (shadow_pnl < 0 or shadow_pf < 0.85):
        decision = "NG"
    return {
        "decision": decision,
        "reasons": reasons,
        "sl_rate_pct": round(sl_rate, 4),
    }


def build_report(
    *,
    main_logs_dir: Path = DEFAULT_MAIN_LOGS_DIR,
    shadow_logs_dir: Path = DEFAULT_SHADOW_LOGS_DIR,
    days: Optional[List[str]] = None,
    lookback_days: int = 3,
    min_days: int = 3,
    min_closed: int = 10,
    min_pf: float = 1.05,
    min_win_rate_pct: float = 45.0,
    max_sl_rate_pct: float = 40.0,
    min_mr_rank_a: int = 0,
) -> Dict[str, Any]:
    resolved_days = resolve_days(main_logs_dir, shadow_logs_dir, days=days, lookback_days=lookback_days)
    main_reviews = [_build_daily_trade_review(main_logs_dir, day8) for day8 in resolved_days]
    shadow_reviews = [_build_daily_trade_review(shadow_logs_dir, day8) for day8 in resolved_days]
    main_agg = _aggregate_reviews(main_reviews)
    shadow_agg = _aggregate_reviews(shadow_reviews)
    main_agg.update(_mr_counts_from_logs(main_logs_dir, resolved_days))
    shadow_agg.update(_mr_counts_from_logs(shadow_logs_dir, resolved_days))
    shadow_sl_classification = _classify_shadow_sl(shadow_logs_dir, resolved_days)
    decision = _decide(
        main=main_agg,
        shadow=shadow_agg,
        min_days=min_days,
        min_closed=min_closed,
        min_pf=min_pf,
        min_win_rate_pct=min_win_rate_pct,
        max_sl_rate_pct=max_sl_rate_pct,
        min_mr_rank_a=min_mr_rank_a,
    )
    return {
        "days": resolved_days,
        "main_logs_dir": str(main_logs_dir),
        "shadow_logs_dir": str(shadow_logs_dir),
        "thresholds": {
            "min_days": int(min_days),
            "min_closed": int(min_closed),
            "min_pf": float(min_pf),
            "min_win_rate_pct": float(min_win_rate_pct),
            "max_sl_rate_pct": float(max_sl_rate_pct),
            "min_mr_rank_a": int(min_mr_rank_a),
        },
        "decision": decision["decision"],
        "reasons": decision["reasons"],
        "feature_gate_review": _build_feature_gate_review(shadow_agg),
        "main": main_agg,
        "shadow": {**shadow_agg, "sl_rate_pct": decision["sl_rate_pct"], "sl_classification": shadow_sl_classification},
        "delta": {
            "pnl_jpy_sum": round(_safe_float(shadow_agg.get("pnl_jpy_sum")) - _safe_float(main_agg.get("pnl_jpy_sum")), 6),
            "avg_ret_pct": round(_safe_float(shadow_agg.get("avg_ret_pct")) - _safe_float(main_agg.get("avg_ret_pct")), 6),
            "profit_factor_jpy": round(_safe_float(shadow_agg.get("profit_factor_jpy")) - _safe_float(main_agg.get("profit_factor_jpy")), 6),
        },
    }


def format_text(report: Dict[str, Any]) -> str:
    shadow = report.get("shadow", {})
    main = report.get("main", {})
    delta = report.get("delta", {})
    feature_gate = report.get("feature_gate_review") if isinstance(report.get("feature_gate_review"), dict) else {}
    exit_tech = feature_gate.get("exit_tech") if isinstance(feature_gate.get("exit_tech"), dict) else {}
    phase_top = feature_gate.get("phase_top") if isinstance(feature_gate.get("phase_top"), list) else []
    aiba_top = feature_gate.get("aiba_top") if isinstance(feature_gate.get("aiba_top"), list) else []
    phase_label = str(phase_top[0].get("label")) if phase_top and isinstance(phase_top[0], dict) else "-"
    aiba_label = str(aiba_top[0].get("label")) if aiba_top and isinstance(aiba_top[0], dict) else "-"
    sl_cls = shadow.get("sl_classification") if isinstance(shadow.get("sl_classification"), dict) else {}
    lines = [
        f"shadow_promotion={report.get('decision')} days={','.join(report.get('days') or [])}",
        f"reason={'; '.join(report.get('reasons') or [])}",
        (
            "shadow="
            f"pnl_jpy:{_safe_float(shadow.get('pnl_jpy_sum')):+.0f} "
            f"closed:{_safe_int(shadow.get('closed_n'))} "
            f"win:{_safe_float(shadow.get('win_rate_pct')):.1f}% "
            f"pf:{_safe_float(shadow.get('profit_factor_jpy')):.2f} "
            f"tp/sl/to:{_safe_int(shadow.get('tp_n'))}/{_safe_int(shadow.get('sl_n'))}/{_safe_int(shadow.get('timeout_n'))} "
            f"rate:{_safe_float(shadow.get('tp_rate_pct')):.1f}/{_safe_float(shadow.get('sl_rate_pct')):.1f}/{_safe_float(shadow.get('timeout_rate_pct')):.1f}% "
            f"nf:{_safe_int(shadow.get('no_follow_through_exit_n'))} "
            f"mrA/B/C:{_safe_int(shadow.get('mr_rank_a_n'))}/{_safe_int(shadow.get('mr_rank_b_n'))}/{_safe_int(shadow.get('mr_rank_c_n'))}"
        ),
        (
            "feature_gate="
            f"{feature_gate.get('status', 'REPORT_ONLY')} "
            f"impact:{feature_gate.get('decision_impact', 'none')} "
            f"phase_top:{phase_label} "
            f"aiba_top:{aiba_label} "
            f"near_tp:{_safe_int(exit_tech.get('near_tp_giveback_exit_n'))} "
            f"progress_rev:{_safe_int(exit_tech.get('progress_reversal_exit_n'))} "
            f"mfe/mae/giveback:{_safe_float(exit_tech.get('avg_mfe_pct')):.3f}/{_safe_float(exit_tech.get('avg_mae_proxy_pct')):.3f}/{_safe_float(exit_tech.get('avg_giveback_pct')):.3f}"
        ),
        (
            "main="
            f"pnl_jpy:{_safe_float(main.get('pnl_jpy_sum')):+.0f} "
            f"closed:{_safe_int(main.get('closed_n'))} "
            f"win:{_safe_float(main.get('win_rate_pct')):.1f}% "
            f"pf:{_safe_float(main.get('profit_factor_jpy')):.2f}"
        ),
        (
            "delta="
            f"pnl_jpy:{_safe_float(delta.get('pnl_jpy_sum')):+.0f} "
            f"avg_ret:{_safe_float(delta.get('avg_ret_pct')):+.4f} "
            f"pf:{_safe_float(delta.get('profit_factor_jpy')):+.2f}"
        ),
        (
            "sl_classification="
            f"total:{_safe_int(sl_cls.get('sl_n'), 0)} "
            f"reversal_wrap:{_safe_int(sl_cls.get('reversal_wrap_n'), 0)}({_safe_float(sl_cls.get('reversal_wrap_pct'), 0.0):.1f}%) "
            f"profit_miss:{_safe_int(sl_cls.get('profit_miss_n'), 0)}({_safe_float(sl_cls.get('profit_miss_pct'), 0.0):.1f}%) "
            f"middle:{_safe_int(sl_cls.get('middle_n'), 0)}"
        ),
    ]
    return "\n".join(lines)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Summarize shadow-paper logs and produce a conservative promotion gate.")
    p.add_argument("--main-logs-dir", default=str(DEFAULT_MAIN_LOGS_DIR))
    p.add_argument("--shadow-logs-dir", default=str(DEFAULT_SHADOW_LOGS_DIR))
    p.add_argument("--day8", action="append", default=[], help="Day to include. Can be repeated.")
    p.add_argument("--lookback-days", type=int, default=3)
    p.add_argument("--min-days", type=int, default=3)
    p.add_argument("--min-closed", type=int, default=10)
    p.add_argument("--min-pf", type=float, default=1.05)
    p.add_argument("--min-win-rate-pct", type=float, default=45.0)
    p.add_argument("--max-sl-rate-pct", type=float, default=40.0)
    p.add_argument("--min-mr-rank-a", type=int, default=0, help="Optional MR A-rank sample threshold.")
    p.add_argument("--fail-on-ng", action="store_true", help="Return non-zero when the promotion decision is NG.")
    p.add_argument("--print-json", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    report = build_report(
        main_logs_dir=Path(args.main_logs_dir).expanduser(),
        shadow_logs_dir=Path(args.shadow_logs_dir).expanduser(),
        days=list(args.day8 or []),
        lookback_days=int(args.lookback_days),
        min_days=int(args.min_days),
        min_closed=int(args.min_closed),
        min_pf=float(args.min_pf),
        min_win_rate_pct=float(args.min_win_rate_pct),
        max_sl_rate_pct=float(args.max_sl_rate_pct),
        min_mr_rank_a=int(args.min_mr_rank_a),
    )
    if args.print_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_text(report))
    if bool(args.fail_on_ng) and report.get("decision") == "NG":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
