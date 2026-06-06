#!/usr/bin/env python3
"""DD (Drawdown) Evaluation Report — Project Ouroboros

Builds equity curve from confirmed P&L in ai_training_log and computes:
  daily_max_drawdown_amount (in %pt), daily_max_drawdown_pct (vs equity_peak),
  recovery_factor, profit_factor, expectancy_per_trade, etc.

P&L unit: ai_training_log.ret_pct is in %pt (e.g. 0.235 = +0.235%).
初期資金不明のためDD率はequity_peakベース。手数料・スプレッドは含まない前提。

Usage:
  python3 tools/dd_report.py YYYYMMDD [--output-dir PATH] [--print-only]
  python3 tools/dd_report.py --all-time [--output-dir PATH]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT.parent / "logs"
CONTROL_CSV = ROOT / "CONTROL.csv"
TODAY8 = datetime.now().strftime("%Y%m%d")

CLOSED_RESULTS = {
    "PAPER_EXIT_TP",
    "PAPER_EXIT_SL",
    "PAPER_EXIT_TIMEOUT",
    "PAPER_EXIT_EOD",
    "PAPER_EXIT_PRENEWS",
    "PAPER_EXIT_EARLY_ADVERSE",
}

DEFAULT_OUTPUT_DIR = ROOT / "reports"

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _safe_float(v: Any) -> Optional[float]:
    """Return float or None."""
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _parse_dt(s: Any) -> Optional[datetime]:
    """Parse 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD HH:MM', return datetime or None."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _ai_score_bucket(score: Optional[float]) -> str:
    """Return AI score bucket label."""
    if score is None:
        return "unknown"
    if score < 0.70:
        return "under_070"
    if score < 0.73:
        return "070_073"
    if score < 0.80:
        return "073_080"
    if score < 0.85:
        return "080_085"
    if score < 0.90:
        return "085_090"
    return "over_090"


def _er_bucket(er: Optional[float]) -> str:
    """Return efficiency ratio bucket label."""
    if er is None:
        return "unknown"
    if er < 0.20:
        return "under_020"
    if er < 0.30:
        return "020_030"
    if er < 0.45:
        return "030_045"
    if er < 0.60:
        return "045_060"
    return "over_060"


def _read_no_paper_hours() -> set:
    """Read CONTROL.csv key no_paper_hours, return set of ints."""
    if not CONTROL_CSV.exists():
        return set()
    try:
        with open(CONTROL_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row.get("key") or row.get("KEY") or "").strip()
                if key == "no_paper_hours":
                    val = (row.get("value") or row.get("VALUE") or "").strip()
                    hours = set()
                    for part in val.split(","):
                        part = part.strip()
                        if part:
                            try:
                                hours.add(int(float(part)))
                            except ValueError:
                                pass
                    return hours
    except Exception:
        pass
    return set()


def _discover_ai_logs() -> List[Path]:
    """Return List[Path]: main LOGS_DIR glob ai_training_log*.csv + shadow dir glob.

    Sorted with current (non-dated) file first, then dated files, then shadow files.
    """
    paths: List[Path] = []

    # Main LOGS_DIR
    if LOGS_DIR.exists():
        main_logs = sorted(LOGS_DIR.glob("ai_training_log*.csv"))
        # Put ai_training_log.csv (undated) first
        main_logs = sorted(
            main_logs,
            key=lambda p: (0 if p.name == "ai_training_log.csv" else 1, p.name),
        )
        paths.extend(main_logs)

    # Shadow instances dir
    shadow_dir = LOGS_DIR / "instances" / "shadow"
    if shadow_dir.exists():
        shadow_logs = sorted(shadow_dir.glob("ai_training_log*.csv"))
        shadow_logs = sorted(
            shadow_logs,
            key=lambda p: (0 if p.name == "ai_training_log.csv" else 1, p.name),
        )
        paths.extend(shadow_logs)

    return paths


def _load_trades(day8: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load trades from all discovered ai_training_log files.

    For each row with result in CLOSED_RESULTS and ret_pct present:
      - Deduplicate by pos_id (later files override)
      - Optionally filter by exit_day == day8
    Returns list of dicts sorted by exit_time ascending.
    """
    all_logs = _discover_ai_logs()
    shadow_dir = LOGS_DIR / "instances" / "shadow"

    # pos_id -> dict (first file wins — current file is sorted first, legacy files are fallback)
    by_pos: Dict[str, Dict[str, Any]] = {}

    for log_path in all_logs:
        is_shadow = str(log_path).startswith(str(shadow_dir))
        try:
            with open(log_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    result = (row.get("result") or "").strip()
                    if result not in CLOSED_RESULTS:
                        continue

                    ret_pct_raw = row.get("ret_pct")
                    ret_pct = _safe_float(ret_pct_raw)
                    if ret_pct is None:
                        continue

                    pos_id = (row.get("pos_id") or "").strip()
                    if not pos_id:
                        continue

                    # Parse exit_time
                    exit_time_str = (row.get("exit_time") or row.get("closed_at") or "").strip()
                    exit_dt = _parse_dt(exit_time_str)
                    exit_day = exit_dt.strftime("%Y%m%d") if exit_dt else None

                    # Parse entry_time
                    entry_time_str = (row.get("entry_time") or row.get("opened_at") or "").strip()
                    entry_dt = _parse_dt(entry_time_str)

                    # hold_min
                    hold_min = _safe_float(row.get("hold_min") or row.get("hold_minutes"))
                    if hold_min is None and entry_dt and exit_dt:
                        hold_min = (exit_dt - entry_dt).total_seconds() / 60.0

                    # hour
                    hour: Optional[int] = None
                    if exit_dt:
                        hour = exit_dt.hour

                    # ai_score
                    ai_score = _safe_float(row.get("ai_score") or row.get("score"))

                    # best_fav / max_adv
                    best_fav = _safe_float(row.get("best_fav") or row.get("mfe_pct"))
                    max_adv = _safe_float(row.get("max_adv") or row.get("mae_pct"))

                    trade = {
                        "pos_id": pos_id,
                        "side": (row.get("side") or "").strip(),
                        "entry_time": entry_dt,
                        "exit_time": exit_dt,
                        "exit_day": exit_day,
                        "ret_pct": ret_pct,
                        "result": result,
                        "outcome": result.replace("PAPER_EXIT_", ""),
                        "ai_score": ai_score,
                        "ai_score_bucket": _ai_score_bucket(ai_score),
                        "hour": hour,
                        "hold_min": hold_min,
                        "best_fav": best_fav,
                        "max_adv": max_adv,
                        "is_shadow": is_shadow,
                    }
                    if pos_id not in by_pos:
                        by_pos[pos_id] = trade
        except Exception:
            continue

    trades = list(by_pos.values())

    # Filter by day8 if provided
    if day8:
        trades = [t for t in trades if t["exit_day"] == day8]

    # Sort by exit_time ascending (None goes last)
    trades.sort(key=lambda t: (t["exit_time"] is None, t["exit_time"] or datetime.min))

    return trades


# ---------------------------------------------------------------------------
# Equity curve and DD metrics
# ---------------------------------------------------------------------------


def _build_equity_curve(trades: List[Dict[str, Any]]) -> Tuple[List[float], List[float]]:
    """Return (equity, peaks) cumulative lists.

    equity[i] = cumulative sum of ret_pct[0..i]
    peaks[i]  = running max of equity[0..i]
    """
    equity: List[float] = []
    peaks: List[float] = []
    cum = 0.0
    peak = 0.0
    for t in trades:
        cum += t["ret_pct"]
        equity.append(cum)
        if cum > peak:
            peak = cum
        peaks.append(peak)
    return equity, peaks


def _compute_dd_metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute full DD metrics dict from a list of trades."""
    if not trades:
        return {
            "n_trades": 0,
            "net_pnl_pct": None,
            "daily_equity_peak": None,
            "daily_equity_trough": None,
            "daily_max_drawdown_amount": None,
            "daily_max_drawdown_pct": None,
            "dd_recovery_minutes": None,
            "dd_recovery_count": None,
            "max_consecutive_loss": None,
            "loss_streak_drawdown_pct": None,
            "recovery_factor": None,
            "profit_factor": None,
            "expectancy_per_trade_pct": None,
            "note": "データなし",
        }

    n = len(trades)
    rets = [t["ret_pct"] for t in trades]
    net_pnl = sum(rets)

    equity, peaks = _build_equity_curve(trades)

    # Daily equity peak/trough
    daily_equity_peak = max(equity) if equity else 0.0
    daily_equity_trough = min(equity) if equity else 0.0

    # Max drawdown: min(equity[i] - peaks[i])  <= 0
    dd_values = [equity[i] - peaks[i] for i in range(n)]
    daily_max_drawdown_amount = min(dd_values)  # most negative (or 0)
    max_dd_idx = dd_values.index(daily_max_drawdown_amount)
    peak_at_max_dd = peaks[max_dd_idx]

    # DD pct vs peak
    if peak_at_max_dd != 0:
        daily_max_drawdown_pct = daily_max_drawdown_amount / abs(peak_at_max_dd)
    else:
        daily_max_drawdown_pct = None

    # DD recovery: after max_dd point, time until equity >= peak_at_max_dd
    dd_recovery_minutes: Optional[float] = None
    if daily_max_drawdown_amount < 0:
        max_dd_exit_time = trades[max_dd_idx]["exit_time"]
        for i in range(max_dd_idx + 1, n):
            if equity[i] >= peak_at_max_dd:
                rec_time = trades[i]["exit_time"]
                if max_dd_exit_time and rec_time:
                    dd_recovery_minutes = (rec_time - max_dd_exit_time).total_seconds() / 60.0
                else:
                    dd_recovery_minutes = None
                break
        # If we never recovered, dd_recovery_minutes stays None

    # DD recovery count: number of times equity crosses back to >= running peak
    dd_recovery_count = 0
    in_drawdown = False
    for i in range(n):
        if dd_values[i] < 0:
            in_drawdown = True
        elif in_drawdown and dd_values[i] >= 0:
            dd_recovery_count += 1
            in_drawdown = False

    # Max consecutive losses and loss streak drawdown
    max_consec_loss = 0
    loss_streak_dd = 0.0
    cur_streak = 0
    cur_streak_sum = 0.0
    for r in rets:
        if r < 0:
            cur_streak += 1
            cur_streak_sum += r
            if cur_streak > max_consec_loss:
                max_consec_loss = cur_streak
                loss_streak_dd = cur_streak_sum
        else:
            cur_streak = 0
            cur_streak_sum = 0.0

    # Profit factor
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    total_win = sum(wins)
    total_loss = sum(losses)
    profit_factor: Optional[float] = None
    if losses:
        profit_factor = total_win / abs(total_loss) if total_loss != 0 else None

    # Recovery factor
    recovery_factor: Optional[float] = None
    if daily_max_drawdown_amount < 0:
        recovery_factor = net_pnl / abs(daily_max_drawdown_amount)

    # Expectancy
    expectancy_per_trade_pct = net_pnl / n if n > 0 else None

    # Notes
    note_parts = [
        "ret_pctは手数料・スプレッドを含まない",
        "初期資金不明のため初期資金ベースDD率は算出不可",
    ]
    if daily_max_drawdown_pct is None:
        note_parts.append("DD率: peakが0のため算出不可")
    note = " / ".join(note_parts)

    return {
        "n_trades": n,
        "net_pnl_pct": net_pnl,
        "daily_equity_peak": daily_equity_peak,
        "daily_equity_trough": daily_equity_trough,
        "daily_max_drawdown_amount": daily_max_drawdown_amount,
        "daily_max_drawdown_pct": daily_max_drawdown_pct,
        "dd_recovery_minutes": dd_recovery_minutes,
        "dd_recovery_count": dd_recovery_count,
        "max_consecutive_loss": max_consec_loss,
        "loss_streak_drawdown_pct": loss_streak_dd,
        "recovery_factor": recovery_factor,
        "profit_factor": profit_factor,
        "expectancy_per_trade_pct": expectancy_per_trade_pct,
        "note": note,
    }


# ---------------------------------------------------------------------------
# Breakdown helpers
# ---------------------------------------------------------------------------


def _axis_stats(grp: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return stats dict for a group of trades."""
    if not grp:
        return {
            "n": 0,
            "tp_n": 0,
            "sl_n": 0,
            "wr": None,
            "net_pnl_pct": 0.0,
            "avg_ret_pct": None,
            "total_win_pct": 0.0,
            "total_loss_pct": 0.0,
            "min_ret_pct": None,
            "max_ret_pct": None,
        }

    rets = [t["ret_pct"] for t in grp]
    tp_n = sum(1 for t in grp if t["outcome"] == "TP")
    sl_n = sum(1 for t in grp if t["outcome"] == "SL")
    net_pnl = sum(rets)
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]

    tp_sl_total = tp_n + sl_n
    wr = tp_n / tp_sl_total if tp_sl_total > 0 else None

    return {
        "n": len(grp),
        "tp_n": tp_n,
        "sl_n": sl_n,
        "wr": wr,
        "net_pnl_pct": net_pnl,
        "avg_ret_pct": net_pnl / len(grp),
        "total_win_pct": sum(wins),
        "total_loss_pct": sum(losses),
        "min_ret_pct": min(rets),
        "max_ret_pct": max(rets),
    }


def _breakdown(trades: List[Dict[str, Any]], axis_key: str) -> Dict[str, Dict[str, Any]]:
    """Group trades by axis_key and compute _axis_stats for each group."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for t in trades:
        val = str(t.get(axis_key, "unknown"))
        if val not in groups:
            groups[val] = []
        groups[val].append(t)

    return {k: _axis_stats(v) for k, v in sorted(groups.items())}


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def analyse(day8: Optional[str] = None, include_shadow: bool = False) -> Dict[str, Any]:
    """Orchestrate full DD analysis.

    Args:
        day8: YYYYMMDD filter (None = all time)
        include_shadow: whether to include shadow trades
    """
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Load all trades
    all_trades = _load_trades(day8)
    n_total = len(all_trades)

    # 2. Filter shadow if needed
    if include_shadow:
        main_trades = all_trades
    else:
        main_trades = [t for t in all_trades if not t["is_shadow"]]

    n_main = len(main_trades)

    # 3. Read no_paper_hours
    no_paper_hours = _read_no_paper_hours()

    # 4. Attach no_paper_hour_flag and hour_str
    for t in main_trades:
        h = t["hour"]
        flag = (h in no_paper_hours) if h is not None else False
        t["no_paper_hour_flag"] = flag
        t["hour_str"] = f"{h:02d}h" if h is not None else "unknown"

    # 5. Compute DD metrics
    metrics = _compute_dd_metrics(main_trades)

    # 6. worst5: sorted by ret_pct ascending, take first 5
    worst5_raw = sorted(main_trades, key=lambda t: t["ret_pct"])[:5]
    worst5 = [
        {
            "pos_id": t["pos_id"],
            "exit_time": t["exit_time"].strftime("%Y-%m-%d %H:%M:%S") if t["exit_time"] else None,
            "side": t["side"],
            "ret_pct": t["ret_pct"],
            "outcome": t["outcome"],
            "ai_score": t["ai_score"],
            "hour": t["hour"],
        }
        for t in worst5_raw
    ]

    # 7. dd_contributing_conditions
    dd_conds: List[str] = []
    if metrics["max_consecutive_loss"] and metrics["max_consecutive_loss"] >= 3:
        dd_conds.append(
            f"連敗 {metrics['max_consecutive_loss']}回 (streak DD: {metrics['loss_streak_drawdown_pct']:.3f}%pt)"
        )

    # Worst hour by net_pnl
    if main_trades:
        hour_groups: Dict[str, List[float]] = {}
        for t in main_trades:
            hs = t["hour_str"]
            hour_groups.setdefault(hs, []).append(t["ret_pct"])
        worst_hour = min(hour_groups.items(), key=lambda kv: sum(kv[1]))
        if sum(worst_hour[1]) < 0:
            dd_conds.append(
                f"最悪時間帯: {worst_hour[0]} (net {sum(worst_hour[1]):.3f}%pt, N={len(worst_hour[1])})"
            )

    sl_count = sum(1 for t in main_trades if t["outcome"] == "SL")
    if sl_count > 0:
        dd_conds.append(f"SL件数: {sl_count}件")

    if not dd_conds:
        dd_conds.append("顕著なDD悪化要因なし")

    # 8. improvement_candidates
    impr: List[str] = []
    pf = metrics.get("profit_factor")
    rf = metrics.get("recovery_factor")
    dd_rec = metrics.get("dd_recovery_minutes")
    n_trades = metrics["n_trades"]

    if pf is not None and pf < 1.0:
        impr.append(f"Profit Factor {pf:.2f} < 1.0: 損失超過。TP/SL比率・AI閾値の見直しを検討")
    if rf is not None and rf < 1.0:
        impr.append(f"Recovery Factor {rf:.2f} < 1.0: DDからの回復が不十分。ロットサイズ・連敗停止を検討")
    if metrics.get("daily_max_drawdown_amount") is not None:
        if metrics["daily_max_drawdown_amount"] < 0 and dd_rec is None:
            impr.append("最大DDから未回復: daily_loss_limit or streak_stop見直しを検討")
    if n_trades < 5:
        impr.append(f"サンプル数不足 (N={n_trades}): 統計的信頼性が低い")
    if not impr:
        impr.append("現時点で顕著な改善候補なし")

    # 9. Breakdowns
    by_hour = _breakdown(main_trades, "hour_str")
    by_ai_score_bucket = _breakdown(main_trades, "ai_score_bucket")
    by_exit_type = _breakdown(main_trades, "outcome")
    by_side = _breakdown(main_trades, "side")
    by_no_paper_hour = _breakdown(main_trades, "no_paper_hour_flag")
    # Convert bool keys to strings for JSON compatibility
    by_no_paper_hour = {str(k): v for k, v in by_no_paper_hour.items()}

    data_notes = [
        "ret_pct単位: %pt (例: 0.235 = +0.235%)",
        "手数料・スプレッドは含まない",
        "初期資金不明のためDD率はequity_peakベース",
        "pos_idで重複排除済み（後発ファイル優先）",
    ]

    return {
        "generated_at": generated_at,
        "target_day8": day8 or "all-time",
        "include_shadow": include_shadow,
        "n_main_trades": n_main,
        "n_total_trades": n_total,
        "data_notes": data_notes,
        "metrics": metrics,
        "worst_trades_top5": worst5,
        "dd_contributing_conditions": dd_conds,
        "improvement_candidates": impr,
        "by_hour": by_hour,
        "by_ai_score_bucket": by_ai_score_bucket,
        "by_exit_type": by_exit_type,
        "by_side": by_side,
        "by_no_paper_hour": by_no_paper_hour,
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _pct_s(v: Any) -> str:
    """Format float as '+0.000%pt' or 'N/A'."""
    if v is None:
        return "N/A"
    try:
        f = float(v)
        sign = "+" if f >= 0 else ""
        return f"{sign}{f:.3f}%pt"
    except (ValueError, TypeError):
        return "N/A"


def _ratio_s(v: Any) -> str:
    """Format float as '0.0%' or 'N/A'."""
    if v is None:
        return "N/A"
    try:
        return f"{float(v) * 100:.1f}%"
    except (ValueError, TypeError):
        return "N/A"


def _f(v: Any, decimals: int = 3) -> str:
    """Format float or 'N/A'."""
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.{decimals}f}"
    except (ValueError, TypeError):
        return "N/A"


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------


def format_report(data: Dict[str, Any]) -> str:
    """Generate markdown report string from analyse() output."""
    lines: List[str] = []
    m = data["metrics"]
    gen = data["generated_at"]
    day_label = data["target_day8"]
    n_main = data["n_main_trades"]
    notes = data["data_notes"]

    # ------------------------------------------------------------------ #
    # 1. Header
    # ------------------------------------------------------------------ #
    lines.append(f"# DD評価レポート ({gen})")
    lines.append("")
    lines.append(f"- 対象日: {day_label}")
    lines.append(f"- 取引数 (メイン): {n_main}")
    lines.append(f"- Shadow含む: {'Yes' if data['include_shadow'] else 'No'}")
    lines.append(f"- 全取引数 (Shadow含): {data['n_total_trades']}")
    lines.append("")
    lines.append("**データ注記:**")
    for note in notes:
        lines.append(f"  - {note}")
    lines.append("")

    # ------------------------------------------------------------------ #
    # 2. 全体サマリー
    # ------------------------------------------------------------------ #
    lines.append("## 全体サマリー")
    lines.append("")
    lines.append(f"| 指標 | 値 |")
    lines.append(f"|------|-----|")
    lines.append(f"| 取引数 | {m['n_trades']} |")
    lines.append(f"| Net P&L | {_pct_s(m['net_pnl_pct'])} |")
    lines.append(f"| Equity Peak | {_pct_s(m['daily_equity_peak'])} |")
    lines.append(f"| Equity Trough | {_pct_s(m['daily_equity_trough'])} |")
    lines.append(f"| 最大DD (amount) | {_pct_s(m['daily_max_drawdown_amount'])} |")
    lines.append(f"| 最大DD (pct vs peak) | {_ratio_s(m['daily_max_drawdown_pct'])} |")
    lines.append(f"| DD回復時間 (分) | {_f(m['dd_recovery_minutes'], 1)} |")
    lines.append(f"| DD回復回数 | {m['dd_recovery_count'] if m['dd_recovery_count'] is not None else 'N/A'} |")
    lines.append(f"| 最大連敗数 | {m['max_consecutive_loss'] if m['max_consecutive_loss'] is not None else 'N/A'} |")
    lines.append(f"| 連敗DD合計 | {_pct_s(m['loss_streak_drawdown_pct'])} |")
    lines.append(f"| Profit Factor | {_f(m['profit_factor'], 2)} |")
    lines.append(f"| Recovery Factor | {_f(m['recovery_factor'], 2)} |")
    lines.append(f"| Expectancy/trade | {_pct_s(m['expectancy_per_trade_pct'])} |")
    lines.append("")

    # ------------------------------------------------------------------ #
    # Helper to render a breakdown table
    # ------------------------------------------------------------------ #
    def _breakdown_table(bd: Dict[str, Dict[str, Any]], label: str) -> None:
        lines.append(f"| {label} | N | TP | SL | WR | net_pnl | avg_ret |")
        lines.append(f"|--------|---|----|----|-----|---------|---------|")
        for key in sorted(bd.keys()):
            s = bd[key]
            wr = _ratio_s(s["wr"])
            net = _pct_s(s["net_pnl_pct"])
            avg = _pct_s(s["avg_ret_pct"])
            lines.append(
                f"| {key} | {s['n']} | {s['tp_n']} | {s['sl_n']} | {wr} | {net} | {avg} |"
            )
        lines.append("")

    # ------------------------------------------------------------------ #
    # 3. 時間帯別成績
    # ------------------------------------------------------------------ #
    lines.append("## 時間帯別成績")
    lines.append("")
    _breakdown_table(data["by_hour"], "hour")

    # ------------------------------------------------------------------ #
    # 4. AI Score帯別成績
    # ------------------------------------------------------------------ #
    lines.append("## AI Score帯別成績")
    lines.append("")
    _breakdown_table(data["by_ai_score_bucket"], "ai_score_bucket")

    # ------------------------------------------------------------------ #
    # 5. exit_type別成績
    # ------------------------------------------------------------------ #
    lines.append("## exit_type別成績")
    lines.append("")
    _breakdown_table(data["by_exit_type"], "exit_type")

    # ------------------------------------------------------------------ #
    # 6. サイド別成績
    # ------------------------------------------------------------------ #
    lines.append("## サイド別成績")
    lines.append("")
    _breakdown_table(data["by_side"], "side")

    # ------------------------------------------------------------------ #
    # 7. no_paper_hours状況
    # ------------------------------------------------------------------ #
    lines.append("## no_paper_hours状況")
    lines.append("")
    _breakdown_table(data["by_no_paper_hour"], "no_paper_hour")

    # ------------------------------------------------------------------ #
    # 8. 最悪取引 TOP5
    # ------------------------------------------------------------------ #
    lines.append("## 最悪取引 TOP5")
    lines.append("")
    lines.append("| pos_id | exit_time | side | ret_pct | outcome | ai_score | hour |")
    lines.append("|--------|-----------|------|---------|---------|----------|------|")
    for w in data["worst_trades_top5"]:
        ai_s = _f(w["ai_score"], 3) if w["ai_score"] is not None else "N/A"
        h = str(w["hour"]) if w["hour"] is not None else "N/A"
        lines.append(
            f"| {w['pos_id']} | {w['exit_time'] or 'N/A'} | {w['side']} "
            f"| {_pct_s(w['ret_pct'])} | {w['outcome']} | {ai_s} | {h} |"
        )
    lines.append("")

    # ------------------------------------------------------------------ #
    # 9. DD悪化要因
    # ------------------------------------------------------------------ #
    lines.append("## DD悪化要因")
    lines.append("")
    for cond in data["dd_contributing_conditions"]:
        lines.append(f"- {cond}")
    lines.append("")

    # ------------------------------------------------------------------ #
    # 10. 改善候補
    # ------------------------------------------------------------------ #
    lines.append("## 改善候補")
    lines.append("")
    for item in data["improvement_candidates"]:
        lines.append(f"- {item}")
    lines.append("")

    # ------------------------------------------------------------------ #
    # 11. 注意事項
    # ------------------------------------------------------------------ #
    lines.append("## 注意事項")
    lines.append("")
    for note in notes:
        lines.append(f"- {note}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DD Evaluation Report — Project Ouroboros",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "day8",
        nargs="?",
        default=None,
        help="Target date YYYYMMDD (omit for all-time unless --all-time)",
    )
    parser.add_argument(
        "--all-time",
        action="store_true",
        help="Analyse all available data (no date filter)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to save reports (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print report to stdout only, do not save files",
    )
    parser.add_argument(
        "--include-shadow",
        action="store_true",
        help="Include shadow bot trades in the analysis",
    )

    args = parser.parse_args()

    # Determine target day
    if args.all_time:
        target_day = None
    elif args.day8:
        target_day = args.day8
    else:
        target_day = None  # default: all-time if no day given

    # Run analysis
    data = analyse(day8=target_day, include_shadow=args.include_shadow)
    report_md = format_report(data)

    # Print to stdout
    print(report_md)

    # Save files
    if not args.print_only:
        out_dir: Path = args.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        date_suffix = target_day if target_day else "all-time"
        md_path = out_dir / f"dd_report_{date_suffix}.md"
        json_path = out_dir / f"dd_report_{date_suffix}.json"

        md_path.write_text(report_md, encoding="utf-8")
        json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        print(f"\n--- Saved ---")
        print(f"  MD  : {md_path}")
        print(f"  JSON: {json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
