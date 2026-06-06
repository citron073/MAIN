#!/usr/bin/env python3
"""AI score band quality report.

Evaluates whether higher AI scores actually correlate with better trade outcomes.
Pre-condition for enabling lot scaling by AI score.

Usage:
  python3 tools/ai_score_quality_report.py [--days N] [--include-backtest] [--output-dir PATH]
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT.parent / "logs"
TODAY8 = datetime.now().strftime("%Y%m%d")

AI_LOG_BACKTEST = LOGS_DIR / "backtest" / "ai_training_log_backtest_contra.csv"


def _discover_ai_logs() -> List[Path]:
    paths: List[Path] = []
    for p in sorted(LOGS_DIR.glob("ai_training_log*.csv")):
        paths.append(p)
    shadow_dir = LOGS_DIR / "instances" / "shadow"
    if shadow_dir.exists():
        for p in sorted(shadow_dir.glob("ai_training_log*.csv")):
            paths.append(p)
    # current file first so pos_id dedup keeps fresh data
    return sorted(paths, key=lambda p: (0 if p.name == "ai_training_log.csv" else 1, p.name))

SCORE_BANDS: List[Tuple[Optional[float], Optional[float], str]] = [
    (None, 0.70, "<0.70"),
    (0.70, 0.75, "0.70-0.75"),
    (0.75, 0.80, "0.75-0.80"),
    (0.80, 0.85, "0.80-0.85"),
    (0.85, 0.90, "0.85-0.90"),
    (0.90, 0.95, "0.90-0.95"),
    (0.95, None, "0.95+"),
]

CLOSED_RESULTS = {"PAPER_EXIT_TP", "PAPER_EXIT_SL", "PAPER_EXIT_TIMEOUT",
                  "PAPER_EXIT_EOD", "PAPER_EXIT_PRENEWS", "PAPER_EXIT_EARLY_ADVERSE"}


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _load_training_rows(paths: List[Path], since8: Optional[str] = None) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen_pos: set = set()
    for path in paths:
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8", errors="replace") as f:
                for row in csv.DictReader(f):
                    result = str(row.get("result", "")).strip()
                    if result not in CLOSED_RESULTS:
                        continue
                    ai_score_raw = str(row.get("ai_score", "")).strip()
                    if not ai_score_raw:
                        continue
                    if since8:
                        t = str(row.get("time", "") or row.get("exit_time", "")).strip()
                        if t and t.replace("-", "").replace(" ", "")[:8] < since8:
                            continue
                    pid = str(row.get("pos_id", "")).strip()
                    if pid and pid in seen_pos:
                        continue
                    if pid:
                        seen_pos.add(pid)
                    rows.append(row)
        except Exception:
            continue
    return rows


def _band_for(score: float) -> str:
    for lo, hi, label in SCORE_BANDS:
        if (lo is None or score >= lo) and (hi is None or score < hi):
            return label
    return "0.95+"


def _stats_for_rows(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    if not rows:
        return {}
    tp = sl = timeout = other = 0
    rets: List[float] = []
    holds: List[float] = []
    mfes: List[float] = []
    scores: List[float] = []
    tp_rets: List[float] = []
    sl_rets: List[float] = []

    for row in rows:
        result = str(row.get("result", "")).strip()
        ret = _safe_float(row.get("ret_pct"), None)  # type: ignore[arg-type]
        hold = _safe_float(row.get("hold_min"), None)  # type: ignore[arg-type]
        mfe = _safe_float(row.get("best_fav"), None)  # type: ignore[arg-type]
        score = _safe_float(row.get("ai_score"), None)  # type: ignore[arg-type]

        if "PAPER_EXIT_TP" in result:
            tp += 1
            if ret is not None:
                tp_rets.append(ret)
        elif "PAPER_EXIT_SL" in result:
            sl += 1
            if ret is not None:
                sl_rets.append(ret)
        elif "PAPER_EXIT" in result:
            timeout += 1
        else:
            other += 1

        if ret is not None:
            rets.append(ret)
        if hold is not None and hold > 0:
            holds.append(hold)
        if mfe is not None:
            mfes.append(mfe)
        if score is not None:
            scores.append(score)

    n = len(rows)
    wr = tp / (tp + sl) if (tp + sl) > 0 else None
    avg_ret = sum(rets) / len(rets) if rets else None
    total_ret = sum(rets) if rets else None
    avg_hold = sum(holds) / len(holds) if holds else None
    avg_mfe = sum(mfes) / len(mfes) if mfes else None
    avg_score = sum(scores) / len(scores) if scores else None
    avg_tp_ret = sum(tp_rets) / len(tp_rets) if tp_rets else None
    avg_sl_ret = sum(sl_rets) / len(sl_rets) if sl_rets else None
    expectancy = None
    if wr is not None and avg_tp_ret is not None and avg_sl_ret is not None:
        expectancy = wr * avg_tp_ret + (1.0 - wr) * avg_sl_ret

    return {
        "n": n, "tp": tp, "sl": sl, "timeout": timeout,
        "wr": wr, "avg_ret": avg_ret, "total_ret": total_ret,
        "avg_hold": avg_hold, "avg_mfe": avg_mfe, "avg_score": avg_score,
        "expectancy": expectancy,
    }


def analyse(days: Optional[int] = None, include_backtest: bool = False) -> Dict[str, Any]:
    since8 = None
    if days is not None:
        since8 = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    live_rows = _load_training_rows(_discover_ai_logs(), since8)
    backtest_rows: List[Dict[str, str]] = []
    if include_backtest and AI_LOG_BACKTEST.exists():
        backtest_rows = _load_training_rows([AI_LOG_BACKTEST], since8)

    all_rows = live_rows + backtest_rows

    # Band breakdown
    band_rows: Dict[str, List[Dict[str, str]]] = {label: [] for _, _, label in SCORE_BANDS}
    for row in all_rows:
        try:
            score = float(row.get("ai_score") or 0)
        except Exception:
            continue
        label = _band_for(score)
        if label in band_rows:
            band_rows[label].append(row)

    band_stats: Dict[str, Any] = {}
    for _, _, label in SCORE_BANDS:
        band_stats[label] = _stats_for_rows(band_rows[label])

    # Side breakdown
    buy_rows = [r for r in all_rows if str(r.get("side", "")).upper() == "BUY"]
    sell_rows = [r for r in all_rows if str(r.get("side", "")).upper() == "SELL"]

    # AIBA alignment breakdown
    aiba_rows: Dict[str, List[Dict[str, str]]] = {"aligned": [], "not_aligned": [], "unknown": []}
    for row in all_rows:
        v = str(row.get("aiba_aligned", "")).strip()
        if v == "1" or v.lower() == "true":
            aiba_rows["aligned"].append(row)
        elif v == "0" or v.lower() == "false":
            aiba_rows["not_aligned"].append(row)
        else:
            aiba_rows["unknown"].append(row)

    # Monotonicity check: is score correlated with WR / avg_ret?
    bands_with_data = [
        (label, band_stats[label])
        for _, _, label in SCORE_BANDS
        if band_stats[label].get("n", 0) >= 3
    ]
    wr_monotone = _is_monotone([s.get("wr") for _, s in bands_with_data])
    ret_monotone = _is_monotone([s.get("avg_ret") for _, s in bands_with_data])

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "since8": since8,
        "n_live": len(live_rows),
        "n_backtest": len(backtest_rows),
        "n_total": len(all_rows),
        "overall": _stats_for_rows(all_rows),
        "by_score_band": band_stats,
        "by_side": {
            "BUY": _stats_for_rows(buy_rows),
            "SELL": _stats_for_rows(sell_rows),
        },
        "by_aiba": {k: _stats_for_rows(v) for k, v in aiba_rows.items()},
        "monotonicity": {
            "wr_increases_with_score": wr_monotone,
            "ret_increases_with_score": ret_monotone,
        },
        "lot_scale_recommendation": _lot_scale_recommendation(bands_with_data),
    }


def _is_monotone(vals: List[Optional[float]]) -> Optional[bool]:
    clean = [v for v in vals if v is not None]
    if len(clean) < 2:
        return None
    return all(b >= a for a, b in zip(clean, clean[1:]))


def _lot_scale_recommendation(bands_with_data: List[Tuple[str, Dict[str, Any]]]) -> str:
    if len(bands_with_data) < 2:
        return "データ不足：判断不可（n>=3のバンドが2つ以上必要）"
    all_wrs = [s.get("wr") for _, s in bands_with_data]
    all_rets = [s.get("avg_ret") for _, s in bands_with_data]
    clean_wrs = [v for v in all_wrs if v is not None]
    clean_rets = [v for v in all_rets if v is not None]
    if not clean_wrs or not clean_rets:
        return "データ不足"
    wr_mono = all(b >= a for a, b in zip(clean_wrs, clean_wrs[1:]))
    ret_mono = all(b >= a for a, b in zip(clean_rets, clean_rets[1:]))
    if wr_mono and ret_mono:
        return "推奨: スコアとWR・期待値が単調増加 → ロット増加の根拠あり（要閾値検証）"
    elif wr_mono or ret_mono:
        return "要観察: 一部単調性あり。スコア0.90以上を基準にした2段階ロットを検討"
    else:
        return "非推奨: スコアとWR・期待値が単調増加していない → 現段階でのロット増加は根拠不足"


def _pct(v: Optional[float]) -> str:
    return f"{v:.3f}%" if v is not None else "N/A"


def _fmt_band(label: str, s: Dict[str, Any]) -> str:
    n = s.get("n", 0)
    if n == 0:
        return f"  {label:12s}  0件"
    wr = f"{s['wr']*100:.0f}%" if s.get("wr") is not None else "N/A"
    ret = _pct(s.get("avg_ret"))
    mfe = _pct(s.get("avg_mfe"))
    hold = f"{s['avg_hold']:.0f}m" if s.get("avg_hold") else "N/A"
    tp, sl = s.get("tp", 0), s.get("sl", 0)
    exp = _pct(s.get("expectancy"))
    return f"  {label:12s}  {n:4d}件  TP:{tp} SL:{sl}  WR:{wr:>4}  avg:{ret:>9}  期待値:{exp:>9}  MFE:{mfe:>9}  hold:{hold}"


def format_report(data: Dict[str, Any]) -> str:
    lines = [
        f"# AI Score 帯別品質レポート ({data['generated_at']})",
        f"  live={data['n_live']}件 backtest={data['n_backtest']}件 合計={data['n_total']}件",
        "",
    ]

    ov = data.get("overall", {})
    if ov:
        wr_str = f"{ov['wr']*100:.1f}%" if ov.get("wr") is not None else "N/A"
        lines += [
            "## 全体サマリー",
            f"  N={ov['n']} TP={ov['tp']} SL={ov['sl']} TIMEOUT={ov['timeout']}",
            f"  WR={wr_str}  avg_ret={_pct(ov.get('avg_ret'))}  期待値={_pct(ov.get('expectancy'))}",
            "  avg_score={0}  avg_hold={1}".format(_pct(ov.get('avg_score')), f"{ov['avg_hold']:.0f}m" if ov.get('avg_hold') else 'N/A'),
            "",
        ]

    lines += [
        "## Score 帯別成績",
        f"  {'Band':12s}  {'N':>5}  TP/SL      WR    avg_ret    期待値     MFE        hold",
        "  " + "-" * 72,
    ]
    for _, _, label in SCORE_BANDS:
        s = data["by_score_band"].get(label, {})
        lines.append(_fmt_band(label, s))

    mono = data.get("monotonicity", {})
    lines += [
        "",
        f"  WR 単調増加: {'✓' if mono.get('wr_increases_with_score') else '✗' if mono.get('wr_increases_with_score') is False else '不明'}",
        f"  期待値 単調増加: {'✓' if mono.get('ret_increases_with_score') else '✗' if mono.get('ret_increases_with_score') is False else '不明'}",
    ]

    # Side breakdown
    lines += ["", "## サイド別成績"]
    for side in ("BUY", "SELL"):
        s = data["by_side"].get(side, {})
        lines.append(_fmt_band(side, s))

    # AIBA breakdown
    lines += ["", "## AIBA アライン別成績"]
    for key, label in [("aligned", "AIBA=1"), ("not_aligned", "AIBA=0")]:
        s = data["by_aiba"].get(key, {})
        lines.append(_fmt_band(label, s))

    lines += [
        "",
        "## ロット増加 推奨判定",
        f"  {data.get('lot_scale_recommendation', 'N/A')}",
    ]

    return "\n".join(lines)


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--include-backtest", action="store_true")
    p.add_argument("--output-dir", default=str(ROOT / "reports"))
    p.add_argument("--print-only", action="store_true")
    args = p.parse_args()

    data = analyse(days=args.days, include_backtest=args.include_backtest)
    report = format_report(data)
    print(report)

    if not args.print_only:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(exist_ok=True)
        (out_dir / f"ai_score_quality_report_{TODAY8}.md").write_text(report, encoding="utf-8")
        (out_dir / f"ai_score_quality_report_{TODAY8}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n[saved] reports/ai_score_quality_report_{TODAY8}.md|.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
