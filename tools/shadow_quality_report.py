#!/usr/bin/env python3
"""Shadow bot quality report — ai_training_log based analysis.

Compares Shadow vs MAIN closed-trade quality using ai_training_log.csv.
Includes WR, expectancy, time-of-day breakdown, AI score band, fib_zone,
and aiba_aligned breakdowns. Saves .md and .json reports.

Usage:
    python3 tools/shadow_quality_report.py
    python3 tools/shadow_quality_report.py --days 14
    python3 tools/shadow_quality_report.py --since 20260429
    python3 tools/shadow_quality_report.py --output-dir /tmp/reports
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT.parent / "logs"

def _discover_logs(base_dir: Path) -> List[Path]:
    if not base_dir.exists():
        return []
    paths = sorted(base_dir.glob("ai_training_log*.csv"))
    return sorted(paths, key=lambda p: (0 if p.name == "ai_training_log.csv" else 1, p.name))


SHADOW_AI_LOGS = _discover_logs(LOGS_DIR / "instances" / "shadow")
MAIN_AI_LOGS = _discover_logs(LOGS_DIR)

DEFAULT_OUTPUT_DIR = ROOT / "reports"

# Outcomes considered as wins
WIN_OUTCOMES = {"TP", "WIN"}
# Outcomes considered as losses
LOSS_OUTCOMES = {"SL", "LOSS", "TIMEOUT", "EOD"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return default


def _parse_dt(s: str) -> Optional[datetime]:
    """Parse ISO-ish datetime string (first 19 chars)."""
    if not s:
        return None
    try:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _read_ai_log(path: Path) -> List[Dict[str, str]]:
    """Return rows from a single ai_training_log CSV. Empty list if missing."""
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            return list(csv.DictReader(f))
    except Exception as exc:
        print(f"[warn] Could not read {path}: {exc}", file=sys.stderr)
        return []


def _load_combined(current: Path, legacy: Path) -> List[Dict[str, str]]:
    """Load current + legacy logs, deduplicate by pos_id (current takes priority)."""
    return _load_from_list([legacy, current])


def _load_from_list(paths: List[Path]) -> List[Dict[str, str]]:
    """Load multiple log files in order, deduplicating by pos_id (later files take priority)."""
    seen: Dict[str, Dict[str, str]] = {}
    for path in paths:
        for row in _read_ai_log(path):
            pid = row.get("pos_id", "").strip()
            if pid:
                seen[pid] = row
            else:
                seen[f"_nokey_{len(seen)}"] = row
    return list(seen.values())


def _filter_rows(
    rows: List[Dict[str, str]],
    *,
    since_date: Optional[datetime] = None,
) -> List[Dict[str, str]]:
    """Filter rows by exit_time (or entry_time) >= since_date."""
    if since_date is None:
        return rows
    out: List[Dict[str, str]] = []
    for row in rows:
        t_str = row.get("exit_time") or row.get("entry_time") or row.get("time") or ""
        dt = _parse_dt(t_str)
        if dt is None or dt >= since_date:
            out.append(row)
    return out


def _is_closed_trade(row: Dict[str, str]) -> bool:
    """Return True if the row represents a fully closed trade."""
    outcome = row.get("outcome", "").strip().upper()
    result = row.get("result", "").strip().upper()
    # outcome column is the primary signal
    if outcome in WIN_OUTCOMES or outcome in LOSS_OUTCOMES:
        return True
    # Fallback: result column
    if result in {"TP", "SL", "TIMEOUT", "EOD"}:
        return True
    # Fallback: non-zero ret_pct
    try:
        if abs(float(row.get("ret_pct") or 0)) > 1e-9:
            return True
    except ValueError:
        pass
    return False


def _outcome_of(row: Dict[str, str]) -> str:
    """Return normalised outcome: TP, SL, TIMEOUT, EOD, or UNKNOWN."""
    outcome = row.get("outcome", "").strip().upper()
    if outcome in WIN_OUTCOMES:
        return "TP"
    if outcome == "SL":
        return "SL"
    if outcome == "TIMEOUT":
        return "TIMEOUT"
    if outcome == "EOD":
        return "EOD"
    # Fallback via result column
    result = row.get("result", "").strip().upper()
    if result in ("TP", "SL", "TIMEOUT", "EOD"):
        return result
    # Fallback via ret_pct sign
    try:
        ret = float(row.get("ret_pct") or 0)
        if abs(ret) > 1e-9:
            return "TP" if ret > 0 else "SL"
    except ValueError:
        pass
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _compute_stats(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    """Compute aggregate stats for a set of ai_training_log rows."""
    closed = [r for r in rows if _is_closed_trade(r)]
    n = len(closed)
    if n == 0:
        return {
            "n": 0, "tp": 0, "sl": 0, "timeout": 0, "eod": 0, "other": 0,
            "wr": None, "avg_ret_pct": None, "total_ret_pct": None,
            "avg_hold_min": None, "avg_ai_score": None, "avg_mfe": None,
            "expectancy": None,
            "avg_tp_ret": None, "avg_sl_ret": None,
        }

    tp_n = sl_n = timeout_n = eod_n = other_n = 0
    ret_sum = 0.0
    hold_sum = 0.0
    ai_score_sum = 0.0
    mfe_sum = 0.0
    tp_rets: List[float] = []
    sl_rets: List[float] = []

    for row in closed:
        outcome = _outcome_of(row)
        ret = _safe_float(row.get("ret_pct"), 0.0)
        hold = _safe_float(row.get("hold_min"), 0.0)
        ai = _safe_float(row.get("ai_score"), 0.0)
        mfe = _safe_float(row.get("best_fav"), 0.0)

        ret_sum += ret
        hold_sum += hold
        ai_score_sum += ai
        mfe_sum += mfe

        if outcome == "TP":
            tp_n += 1
            tp_rets.append(ret)
        elif outcome == "SL":
            sl_n += 1
            sl_rets.append(ret)
        elif outcome == "TIMEOUT":
            timeout_n += 1
        elif outcome == "EOD":
            eod_n += 1
        else:
            other_n += 1

    decisive = tp_n + sl_n  # for WR calculation
    wr: Optional[float] = tp_n / decisive if decisive > 0 else None

    avg_tp_ret: Optional[float] = sum(tp_rets) / len(tp_rets) if tp_rets else None
    avg_sl_ret: Optional[float] = sum(sl_rets) / len(sl_rets) if sl_rets else None

    expectancy: Optional[float] = None
    if wr is not None and avg_tp_ret is not None and avg_sl_ret is not None:
        expectancy = wr * avg_tp_ret + (1.0 - wr) * avg_sl_ret

    return {
        "n": n,
        "tp": tp_n,
        "sl": sl_n,
        "timeout": timeout_n,
        "eod": eod_n,
        "other": other_n,
        "wr": wr,
        "avg_ret_pct": ret_sum / n,
        "total_ret_pct": ret_sum,
        "avg_hold_min": hold_sum / n,
        "avg_ai_score": ai_score_sum / n,
        "avg_mfe": mfe_sum / n,
        "expectancy": expectancy,
        "avg_tp_ret": avg_tp_ret,
        "avg_sl_ret": avg_sl_ret,
    }


def _hour_breakdown(rows: List[Dict[str, str]]) -> Dict[int, Dict[str, Any]]:
    """Group closed trades by entry_time hour and compute stats."""
    by_hour: Dict[int, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        if not _is_closed_trade(row):
            continue
        entry_t = row.get("entry_time") or row.get("time") or ""
        dt = _parse_dt(entry_t)
        if dt is None:
            continue
        by_hour[dt.hour].append(row)
    result: Dict[int, Dict[str, Any]] = {}
    for h in sorted(by_hour):
        result[h] = _compute_stats(by_hour[h])
    return result


def _ai_score_band_breakdown(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    """Group closed trades by AI score band and compute stats."""
    bands: Dict[str, List[Dict[str, str]]] = {
        "<0.80": [],
        "0.80-0.85": [],
        "0.85-0.90": [],
        "0.90-0.95": [],
        "0.95+": [],
    }
    for row in rows:
        if not _is_closed_trade(row):
            continue
        score = _safe_float(row.get("ai_score"), 0.0)
        if score < 0.80:
            bands["<0.80"].append(row)
        elif score < 0.85:
            bands["0.80-0.85"].append(row)
        elif score < 0.90:
            bands["0.85-0.90"].append(row)
        elif score < 0.95:
            bands["0.90-0.95"].append(row)
        else:
            bands["0.95+"].append(row)
    return {band: _compute_stats(band_rows) for band, band_rows in bands.items()}


def _fib_zone_breakdown(rows: List[Dict[str, str]]) -> Optional[Dict[str, Dict[str, Any]]]:
    """Group closed trades by fib_zone if column exists. Returns None if column absent."""
    has_col = any("fib_zone" in row for row in rows)
    if not has_col:
        return None
    by_zone: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        if not _is_closed_trade(row):
            continue
        zone = (row.get("fib_zone") or "NA").strip() or "NA"
        by_zone[zone].append(row)
    return {z: _compute_stats(by_zone[z]) for z in sorted(by_zone)}


def _aiba_breakdown(rows: List[Dict[str, str]]) -> Optional[Dict[str, Dict[str, Any]]]:
    """Group closed trades by aiba_aligned (1/0). Returns None if column absent."""
    has_col = any("aiba_aligned" in row for row in rows)
    if not has_col:
        return None
    aligned: List[Dict[str, str]] = []
    not_aligned: List[Dict[str, str]] = []
    for row in rows:
        if not _is_closed_trade(row):
            continue
        val = str(row.get("aiba_aligned", "")).strip().lower()
        if val in ("1", "true", "yes"):
            aligned.append(row)
        else:
            not_aligned.append(row)
    return {
        "aligned": _compute_stats(aligned),
        "not_aligned": _compute_stats(not_aligned),
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _pct(v: Optional[float], decimals: int = 1) -> str:
    if v is None:
        return "N/A"
    return f"{v * 100:.{decimals}f}%"


def _ret(v: Optional[float]) -> str:
    """Format ret_pct / expectancy value (already in % units)."""
    if v is None:
        return "N/A"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.3f}%"


def _mfe(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{v:.3f}%"


def _score(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{v:.3f}"


def _hold(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{v:.1f}min"


def _stats_summary_lines(label: str, s: Dict[str, Any]) -> List[str]:
    decisive = s["tp"] + s["sl"]
    lines = [
        f"### {label}",
        f"- 取引数 (N): {s['n']} | TP: {s['tp']} | SL: {s['sl']} | TIMEOUT: {s['timeout']} | EOD: {s['eod']}",
        f"- 決定的取引 (TP+SL): {decisive}",
        f"- WR (TP/(TP+SL)): {_pct(s['wr'])}",
        f"- avg_ret_pct: {_ret(s['avg_ret_pct'])} | total_ret_pct: {_ret(s['total_ret_pct'])}",
        f"- avg_hold_min: {_hold(s['avg_hold_min'])} | avg_ai_score: {_score(s['avg_ai_score'])}",
        f"- avg_MFE (best_fav): {_mfe(s['avg_mfe'])}",
        f"- avg_tp_ret: {_ret(s['avg_tp_ret'])} | avg_sl_ret: {_ret(s['avg_sl_ret'])}",
        f"- expectancy: {_ret(s['expectancy'])}",
    ]
    return lines


def _breakdown_table(
    header: str,
    breakdown: Dict[str, Dict[str, Any]],
) -> List[str]:
    lines = [f"### {header}", ""]
    lines.append(f"| {'区分':<18} | {'N':>5} | {'WR':>7} | {'avg_ret':>9} | {'avg_MFE':>9} |")
    lines.append(f"|{'-'*20}|{'-'*7}|{'-'*9}|{'-'*11}|{'-'*11}|")
    for key, s in breakdown.items():
        wr_s = _pct(s["wr"]) if s["n"] > 0 else "N/A"
        ret_s = _ret(s["avg_ret_pct"]) if s["n"] > 0 else "N/A"
        mfe_s = _mfe(s["avg_mfe"]) if s["n"] > 0 else "N/A"
        lines.append(f"| {str(key):<18} | {s['n']:>5} | {wr_s:>7} | {ret_s:>9} | {mfe_s:>9} |")
    lines.append("")
    return lines


def _hour_table(hour_data: Dict[int, Dict[str, Any]]) -> List[str]:
    lines = ["### 時間帯別 (entry_time hour)", ""]
    lines.append(f"| {'時間':>5} | {'N':>5} | {'WR':>7} | {'avg_ret':>9} | {'avg_MFE':>9} |")
    lines.append(f"|{'-'*7}|{'-'*7}|{'-'*9}|{'-'*11}|{'-'*11}|")
    for h, s in sorted(hour_data.items()):
        wr_s = _pct(s["wr"]) if s["n"] > 0 else "N/A"
        ret_s = _ret(s["avg_ret_pct"]) if s["n"] > 0 else "N/A"
        mfe_s = _mfe(s["avg_mfe"]) if s["n"] > 0 else "N/A"
        lines.append(f"| {h:>3}h   | {s['n']:>5} | {wr_s:>7} | {ret_s:>9} | {mfe_s:>9} |")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Conclusion
# ---------------------------------------------------------------------------

def _conclude(shadow_stats: Dict[str, Any], main_stats: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Return (recommendation, reasoning_lines)."""
    shadow_wr = shadow_stats.get("wr")
    main_wr = main_stats.get("wr")
    shadow_exp = shadow_stats.get("expectancy")
    shadow_n = shadow_stats.get("n", 0)

    reasons: List[str] = []

    if shadow_n < 10:
        reasons.append(f"Shadow データ不足 (N={shadow_n}, 最低10件必要)")
        return "要継続観察", reasons

    if shadow_wr is None:
        reasons.append("Shadow WR が計算不能 (TP/SL ゼロ)")
        return "要継続観察", reasons

    if main_wr is None:
        reasons.append("MAIN WR が計算不能 — Shadow WR のみで判定")
        # Fall through to check expectancy

    wr_ok = (main_wr is None) or (shadow_wr >= main_wr)
    exp_ok = shadow_exp is not None and shadow_exp > 0

    if wr_ok and exp_ok:
        reasons.append(
            f"Shadow WR ({_pct(shadow_wr)}) >= MAIN WR ({_pct(main_wr)}) かつ "
            f"expectancy={_ret(shadow_exp)} > 0"
        )
        return "ai_train_include_shadow=1 推奨", reasons
    else:
        if not wr_ok:
            reasons.append(
                f"Shadow WR ({_pct(shadow_wr)}) < MAIN WR ({_pct(main_wr)})"
            )
        if not exp_ok:
            reasons.append(
                f"Shadow expectancy={_ret(shadow_exp)} <= 0 (損益見込み不足)"
            )
        return "要継続観察", reasons


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_report(
    shadow_rows: List[Dict[str, str]],
    main_rows: List[Dict[str, str]],
    *,
    since_date: Optional[datetime] = None,
    shadow_log_paths: List[str],
    main_log_paths: List[str],
) -> Dict[str, Any]:
    shadow_filtered = _filter_rows(shadow_rows, since_date=since_date)
    main_filtered = _filter_rows(main_rows, since_date=since_date)

    shadow_stats = _compute_stats(shadow_filtered)
    main_stats = _compute_stats(main_filtered)

    shadow_hours = _hour_breakdown(shadow_filtered)
    shadow_ai_bands = _ai_score_band_breakdown(shadow_filtered)
    shadow_fib = _fib_zone_breakdown(shadow_filtered)
    shadow_aiba = _aiba_breakdown(shadow_filtered)

    main_hours = _hour_breakdown(main_filtered)
    main_ai_bands = _ai_score_band_breakdown(main_filtered)

    recommendation, reasons = _conclude(shadow_stats, main_stats)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "since_date": since_date.strftime("%Y-%m-%d") if since_date else None,
        "shadow_log_paths": shadow_log_paths,
        "main_log_paths": main_log_paths,
        "shadow_total_rows_loaded": len(shadow_rows),
        "main_total_rows_loaded": len(main_rows),
        "shadow_filtered_rows": len(shadow_filtered),
        "main_filtered_rows": len(main_filtered),
        "shadow": shadow_stats,
        "main": main_stats,
        "shadow_hour_breakdown": {str(k): v for k, v in shadow_hours.items()},
        "main_hour_breakdown": {str(k): v for k, v in main_hours.items()},
        "shadow_ai_score_bands": shadow_ai_bands,
        "main_ai_score_bands": main_ai_bands,
        "shadow_fib_zone": shadow_fib,
        "shadow_aiba_aligned": shadow_aiba,
        "recommendation": recommendation,
        "recommendation_reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------

def format_markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    since = report.get("since_date") or "全期間"
    gen = report.get("generated_at", "")

    lines += [
        f"# Shadow Quality Report",
        f"",
        f"生成日時: {gen}  |  期間: {since} 以降",
        f"",
        "---",
        "",
        "## データソース",
        "",
    ]
    for p in report.get("shadow_log_paths", []):
        lines.append(f"- Shadow: `{p}`")
    for p in report.get("main_log_paths", []):
        lines.append(f"- MAIN:   `{p}`")
    lines += [
        f"",
        f"Shadow 読込行数: {report['shadow_total_rows_loaded']}  "
        f"(フィルター後: {report['shadow_filtered_rows']})",
        f"MAIN 読込行数:   {report['main_total_rows_loaded']}  "
        f"(フィルター後: {report['main_filtered_rows']})",
        "",
        "---",
        "",
        "## 統計サマリー",
        "",
    ]

    shadow_s = report["shadow"]
    main_s = report["main"]

    lines += _stats_summary_lines("Shadow", shadow_s)
    lines.append("")
    lines += _stats_summary_lines("MAIN", main_s)

    # Delta
    def _delta_wr() -> str:
        sw = shadow_s.get("wr")
        mw = main_s.get("wr")
        if sw is None or mw is None:
            return "N/A"
        d = (sw - mw) * 100
        return f"{d:+.1f}pt"

    def _delta_exp() -> str:
        se = shadow_s.get("expectancy")
        me = main_s.get("expectancy")
        if se is None or me is None:
            return "N/A"
        d = se - me
        return f"{d:+.3f}%"

    lines += [
        "",
        "### Delta (Shadow - MAIN)",
        f"- WR差: {_delta_wr()}",
        f"- expectancy差: {_delta_exp()}",
        "",
        "---",
        "",
        "## 時間帯別分析",
        "",
        "### Shadow",
        "",
    ]
    shadow_hours: Dict[str, Any] = report.get("shadow_hour_breakdown", {})
    lines += _hour_table({int(k): v for k, v in shadow_hours.items()})

    lines += ["### MAIN", ""]
    main_hours: Dict[str, Any] = report.get("main_hour_breakdown", {})
    lines += _hour_table({int(k): v for k, v in main_hours.items()})

    lines += ["---", "", "## AI スコアバンド別分析", "", "### Shadow", ""]
    lines += _breakdown_table("AI Score Band — Shadow", report.get("shadow_ai_score_bands", {}))

    lines += ["### MAIN", ""]
    lines += _breakdown_table("AI Score Band — MAIN", report.get("main_ai_score_bands", {}))

    fib = report.get("shadow_fib_zone")
    if fib is not None:
        lines += ["---", "", "## Fib Zone 別分析 (Shadow)", ""]
        lines += _breakdown_table("Fib Zone", fib)
    else:
        lines += ["---", "", "## Fib Zone 別分析", "", "_fib_zone 列が存在しません_", ""]

    aiba = report.get("shadow_aiba_aligned")
    if aiba is not None:
        lines += ["---", "", "## aiba_aligned 別分析 (Shadow)", ""]
        lines += _breakdown_table("aiba_aligned", aiba)
    else:
        lines += ["---", "", "## aiba_aligned 別分析", "", "_aiba_aligned 列が存在しません_", ""]

    # Conclusion
    rec = report.get("recommendation", "N/A")
    reason_list = report.get("recommendation_reasons", [])
    lines += [
        "---",
        "",
        "## 結論",
        "",
        f"**推奨: {rec}**",
        "",
        "判定根拠:",
        "",
    ]
    for r in reason_list:
        lines.append(f"- {r}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# stdout plain-text formatter
# ---------------------------------------------------------------------------

def format_plaintext(report: Dict[str, Any]) -> str:
    """Compact single-page stdout summary."""
    shadow_s = report["shadow"]
    main_s = report["main"]
    since = report.get("since_date") or "全期間"
    gen = report.get("generated_at", "")

    def _wr(s: Dict[str, Any]) -> str:
        w = s.get("wr")
        return f"{w*100:.1f}%" if w is not None else "N/A"

    lines = [
        f"=== Shadow Quality Report  generated={gen}  since={since} ===",
        "",
        f"[Shadow]  N={shadow_s['n']}  TP={shadow_s['tp']}  SL={shadow_s['sl']}  "
        f"TIMEOUT={shadow_s['timeout']}  EOD={shadow_s['eod']}",
        f"          WR={_wr(shadow_s)}  avg_ret={_ret(shadow_s['avg_ret_pct'])}  "
        f"total_ret={_ret(shadow_s['total_ret_pct'])}",
        f"          avg_hold={_hold(shadow_s['avg_hold_min'])}  "
        f"avg_ai_score={_score(shadow_s['avg_ai_score'])}  avg_MFE={_mfe(shadow_s['avg_mfe'])}",
        f"          expectancy={_ret(shadow_s['expectancy'])}  "
        f"avg_tp_ret={_ret(shadow_s['avg_tp_ret'])}  avg_sl_ret={_ret(shadow_s['avg_sl_ret'])}",
        "",
        f"[MAIN]    N={main_s['n']}  TP={main_s['tp']}  SL={main_s['sl']}  "
        f"TIMEOUT={main_s['timeout']}  EOD={main_s['eod']}",
        f"          WR={_wr(main_s)}  avg_ret={_ret(main_s['avg_ret_pct'])}  "
        f"total_ret={_ret(main_s['total_ret_pct'])}",
        f"          avg_hold={_hold(main_s['avg_hold_min'])}  "
        f"avg_ai_score={_score(main_s['avg_ai_score'])}  avg_MFE={_mfe(main_s['avg_mfe'])}",
        f"          expectancy={_ret(main_s['expectancy'])}",
        "",
    ]

    # Hour breakdown (shadow only for brevity)
    shadow_hours: Dict[str, Any] = report.get("shadow_hour_breakdown", {})
    if shadow_hours:
        lines.append("[Shadow 時間帯]  Hour  N    WR      avg_ret   avg_MFE")
        for h_str in sorted(shadow_hours, key=lambda x: int(x)):
            s = shadow_hours[h_str]
            wr_s = f"{s['wr']*100:.1f}%" if s.get("wr") is not None else "N/A"
            lines.append(
                f"                 {int(h_str):02d}h  {s['n']:>4}  {wr_s:>6}  "
                f"{_ret(s['avg_ret_pct']):>9}  {_mfe(s['avg_mfe']):>9}"
            )
        lines.append("")

    # AI score bands
    bands = report.get("shadow_ai_score_bands", {})
    if bands:
        lines.append("[Shadow AI score bands]  Band           N    WR      avg_ret")
        for band, s in bands.items():
            wr_s = f"{s['wr']*100:.1f}%" if s.get("wr") is not None else "N/A"
            lines.append(
                f"                         {band:<14} {s['n']:>4}  {wr_s:>6}  {_ret(s['avg_ret_pct']):>9}"
            )
        lines.append("")

    # Fib zone
    fib = report.get("shadow_fib_zone")
    if fib:
        lines.append("[Shadow Fib Zone]  Zone         N    WR      avg_ret")
        for zone, s in sorted(fib.items()):
            wr_s = f"{s['wr']*100:.1f}%" if s.get("wr") is not None else "N/A"
            lines.append(
                f"                   {zone:<12} {s['n']:>4}  {wr_s:>6}  {_ret(s['avg_ret_pct']):>9}"
            )
        lines.append("")

    # aiba_aligned
    aiba = report.get("shadow_aiba_aligned")
    if aiba:
        lines.append("[Shadow aiba_aligned]  Segment     N    WR      avg_ret")
        for seg, s in aiba.items():
            wr_s = f"{s['wr']*100:.1f}%" if s.get("wr") is not None else "N/A"
            lines.append(
                f"                       {seg:<11} {s['n']:>4}  {wr_s:>6}  {_ret(s['avg_ret_pct']):>9}"
            )
        lines.append("")

    rec = report.get("recommendation", "N/A")
    reasons = report.get("recommendation_reasons", [])
    lines += [
        "=== 結論 ===",
        f"推奨: {rec}",
    ]
    for r in reasons:
        lines.append(f"  - {r}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Shadow bot quality report from ai_training_log.csv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--days", type=int, default=None,
        help="直近 N 日間のみ対象 (デフォルト: 全期間)",
    )
    p.add_argument(
        "--since", metavar="YYYYMMDD", default=None,
        help="この日付以降のデータのみ対象",
    )
    p.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT_DIR),
        help=f"レポート保存先ディレクトリ (デフォルト: {DEFAULT_OUTPUT_DIR})",
    )
    p.add_argument(
        "--no-save", action="store_true",
        help="ファイル保存をスキップ (stdout のみ)",
    )
    p.add_argument(
        "--json", action="store_true",
        help="stdout に JSON のみ出力",
    )
    return p.parse_args(argv)


def _resolve_since_date(args: argparse.Namespace) -> Optional[datetime]:
    if args.since:
        try:
            return datetime.strptime(args.since, "%Y%m%d")
        except ValueError:
            print(f"[error] --since の書式が不正です: {args.since} (YYYYMMDD 形式で指定)", file=sys.stderr)
            sys.exit(1)
    if args.days is not None:
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=args.days)
    return None


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    since_date = _resolve_since_date(args)

    # Load shadow logs (auto-discovered)
    shadow_rows = _load_from_list(SHADOW_AI_LOGS)
    main_rows = _load_from_list(MAIN_AI_LOGS)

    # Collect path info for report metadata
    shadow_paths = [str(p) for p in SHADOW_AI_LOGS if p.exists()]
    main_paths = [str(p) for p in MAIN_AI_LOGS if p.exists()]

    if not shadow_rows:
        print(
            f"[warn] Shadow ai_training_log が見つからないか空です。\n"
            f"  {LOGS_DIR / 'instances' / 'shadow'}",
            file=sys.stderr,
        )

    report = build_report(
        shadow_rows,
        main_rows,
        since_date=since_date,
        shadow_log_paths=shadow_paths,
        main_log_paths=main_paths,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    plain = format_plaintext(report)
    print(plain)

    if not args.no_save:
        output_dir = Path(args.output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        date_suffix = datetime.now().strftime("%Y%m%d")

        md_path = output_dir / f"shadow_quality_report_{date_suffix}.md"
        json_path = output_dir / f"shadow_quality_report_{date_suffix}.json"

        md_content = format_markdown(report)
        md_path.write_text(md_content, encoding="utf-8")
        print(f"\n[saved] {md_path}")

        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[saved] {json_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
