#!/usr/bin/env python3
"""TP/SL calibration report based on MFE (best_fav) distribution.

Answers: "Is our TP=0.220% optimal, or do we exit too early/late?"
Uses best_fav (MFE = Maximum Favorable Excursion) from ai_training_log.

Note: MAE (Maximum Adverse Excursion) is not yet in the training log schema.
      Only MFE-based TP calibration is possible at this time.

Usage:
  python3 tools/tp_sl_calibration_report.py [--days N] [--include-backtest]
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    return sorted(paths, key=lambda p: (0 if p.name == "ai_training_log.csv" else 1, p.name))

CLOSED_RESULTS = {"PAPER_EXIT_TP", "PAPER_EXIT_SL", "PAPER_EXIT_TIMEOUT",
                  "PAPER_EXIT_EOD", "PAPER_EXIT_PRENEWS", "PAPER_EXIT_EARLY_ADVERSE"}

# MFE analysis checkpoints (%)
MFE_CHECKPOINTS = [0.05, 0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20, 0.22, 0.25, 0.28, 0.30, 0.35, 0.40]

# MAE (max_adv) checkpoints: % of trades where adverse move STAYED within threshold
MAE_CHECKPOINTS = [0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20]

# Virtual TP candidates to simulate (%)
VIRTUAL_TP_CANDIDATES = [0.14, 0.16, 0.18, 0.20, 0.22, 0.25, 0.28, 0.30]
# Virtual SL candidates to simulate (%) — requires max_adv data
VIRTUAL_SL_CANDIDATES = [0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20, 0.22]
CURRENT_TP = 0.220
CURRENT_SL = 0.140


def _safe_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def _load_rows(paths: List[Path], since8: Optional[str]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen: set = set()
    for path in paths:
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8", errors="replace") as f:
                for row in csv.DictReader(f):
                    if str(row.get("result", "")).strip() not in CLOSED_RESULTS:
                        continue
                    if since8:
                        t = str(row.get("time", "") or row.get("exit_time", "")).strip()
                        if t and t.replace("-", "").replace(" ", "")[:8] < since8:
                            continue
                    pid = str(row.get("pos_id", "")).strip()
                    if pid and pid in seen:
                        continue
                    if pid:
                        seen.add(pid)
                    rows.append(row)
        except Exception:
            continue
    return rows


def analyse(days: Optional[int] = None, include_backtest: bool = False) -> Dict[str, Any]:
    since8 = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d") if days else None

    live_rows = _load_rows(_discover_ai_logs(), since8)
    bt_rows: List[Dict[str, str]] = []
    if include_backtest and AI_LOG_BACKTEST.exists():
        bt_rows = _load_rows([AI_LOG_BACKTEST], since8)

    all_rows = live_rows + bt_rows

    # Separate by outcome
    tp_rows = [r for r in all_rows if "PAPER_EXIT_TP" in str(r.get("result", ""))]
    sl_rows = [r for r in all_rows if "PAPER_EXIT_SL" in str(r.get("result", ""))]
    non_sl_rows = [r for r in all_rows if "PAPER_EXIT_SL" not in str(r.get("result", ""))]

    # MFE distribution for ALL trades
    mfes_all = [_safe_float(r.get("best_fav")) for r in all_rows]
    mfes_all = [v for v in mfes_all if v is not None]

    # MFE distribution for TP trades
    mfes_tp = [_safe_float(r.get("best_fav")) for r in tp_rows]
    mfes_tp = [v for v in mfes_tp if v is not None]

    # MFE distribution for SL trades (how much they were in profit before hitting SL)
    mfes_sl = [_safe_float(r.get("best_fav")) for r in sl_rows]
    mfes_sl = [v for v in mfes_sl if v is not None]

    # ret_pct for TP and SL
    rets_tp = [_safe_float(r.get("ret_pct")) for r in tp_rows]
    rets_tp_clean = [v for v in rets_tp if v is not None]
    rets_sl = [_safe_float(r.get("ret_pct")) for r in sl_rows]
    rets_sl_clean = [v for v in rets_sl if v is not None]

    def _pct_reached(mfes: List[float], threshold: float) -> float:
        if not mfes:
            return 0.0
        return sum(1 for v in mfes if v >= threshold) / len(mfes)

    # MFE checkpoints: what % of ALL trades reached each level
    mfe_reach_all = {
        cp: {"all": _pct_reached(mfes_all, cp),
             "tp": _pct_reached(mfes_tp, cp),
             "sl": _pct_reached(mfes_sl, cp)}
        for cp in MFE_CHECKPOINTS
    }

    # Virtual TP simulation (using all trades as if we had set TP at each level)
    # Assumes: if MFE >= virtual_TP → would have exited at virtual_TP (+virtual_TP% return)
    #          else → actual ret_pct (SL or TIMEOUT result)
    def _simulate_tp(vtp: float) -> Dict[str, Any]:
        sim_rets: List[float] = []
        sim_tp = sim_sl = sim_other = 0
        for row in all_rows:
            mfe = _safe_float(row.get("best_fav"))
            actual_ret = _safe_float(row.get("ret_pct"))
            result = str(row.get("result", ""))
            if mfe is not None and mfe >= vtp:
                sim_rets.append(vtp)
                sim_tp += 1
            elif "PAPER_EXIT_SL" in result and actual_ret is not None:
                sim_rets.append(actual_ret)
                sim_sl += 1
            elif actual_ret is not None:
                sim_rets.append(actual_ret)
                sim_other += 1
        n = len(sim_rets)
        wr = sim_tp / (sim_tp + sim_sl) if (sim_tp + sim_sl) > 0 else None
        avg = sum(sim_rets) / n if sim_rets else None
        total = sum(sim_rets) if sim_rets else None
        return {"vtp": vtp, "n": n, "tp": sim_tp, "sl": sim_sl,
                "wr": wr, "avg_ret": avg, "total_ret": total}

    vtp_sims = {f"{vtp:.3f}": _simulate_tp(vtp) for vtp in VIRTUAL_TP_CANDIDATES}

    # Best virtual TP by expectancy
    best_vtp = max(vtp_sims.values(),
                   key=lambda s: s["avg_ret"] if s["avg_ret"] is not None else float("-inf"),
                   default=None)

    # Current TP actual stats
    n = len(all_rows)
    tp_n, sl_n = len(tp_rows), len(sl_rows)
    actual_wr = tp_n / (tp_n + sl_n) if (tp_n + sl_n) > 0 else None
    actual_avg_tp = sum(rets_tp_clean) / len(rets_tp_clean) if rets_tp_clean else None
    actual_avg_sl = sum(rets_sl_clean) / len(rets_sl_clean) if rets_sl_clean else None
    actual_expectancy = (
        actual_wr * (actual_avg_tp or 0) + (1 - actual_wr) * (actual_avg_sl or 0)
        if actual_wr is not None else None
    )

    # SL trades that had meaningful MFE (profit_miss cases)
    sl_with_profit = [v for v in mfes_sl if v >= 0.05]
    sl_immediate = [v for v in mfes_sl if v < 0.01]

    # MAE analysis (max_adv — field added 2026-05-10; only new rows have it)
    mae_rows = [(r, _safe_float(r.get("max_adv"))) for r in all_rows]
    mae_rows_valid = [(r, v) for r, v in mae_rows if v is not None and v > 0]
    maes = [v for _, v in mae_rows_valid]
    mae_n = len(maes)
    mae_checkpoints = {}
    if maes:
        for cp in MAE_CHECKPOINTS:
            within = sum(1 for v in maes if v <= cp)
            mae_checkpoints[f"{cp:.3f}"] = {
                "within_n": within,
                "within_pct": within / mae_n,
            }

    def _simulate_sl(vsl: float) -> Dict[str, Any]:
        sim_rets: List[float] = []
        sim_tp = sim_sl_hit = sim_other = 0
        for row, mae in mae_rows_valid:
            result = str(row.get("result", ""))
            actual_ret = _safe_float(row.get("ret_pct"))
            if mae >= vsl:
                sim_rets.append(-vsl)
                sim_sl_hit += 1
            elif "PAPER_EXIT_TP" in result:
                if actual_ret is not None:
                    sim_rets.append(actual_ret)
                sim_tp += 1
            elif actual_ret is not None:
                sim_rets.append(actual_ret)
                sim_other += 1
        n_sim = len(sim_rets)
        wr_sim = sim_tp / (sim_tp + sim_sl_hit) if (sim_tp + sim_sl_hit) > 0 else None
        avg_sim = sum(sim_rets) / n_sim if sim_rets else None
        total_sim = sum(sim_rets) if sim_rets else None
        return {"vsl": vsl, "n": n_sim, "tp": sim_tp, "sl": sim_sl_hit,
                "wr": wr_sim, "avg_ret": avg_sim, "total_ret": total_sim}

    vsl_sims = {f"{vsl:.3f}": _simulate_sl(vsl) for vsl in VIRTUAL_SL_CANDIDATES} if mae_n >= 30 else {}

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "n_live": len(live_rows),
        "n_backtest": len(bt_rows),
        "n_total": n,
        "current_tp_pct": CURRENT_TP,
        "current_sl_pct": CURRENT_SL,
        "actual": {
            "tp_n": tp_n, "sl_n": sl_n,
            "wr": actual_wr,
            "avg_tp_ret": actual_avg_tp,
            "avg_sl_ret": actual_avg_sl,
            "expectancy": actual_expectancy,
            "avg_mfe_all": sum(mfes_all) / len(mfes_all) if mfes_all else None,
            "avg_mfe_tp": sum(mfes_tp) / len(mfes_tp) if mfes_tp else None,
            "avg_mfe_sl": sum(mfes_sl) / len(mfes_sl) if mfes_sl else None,
        },
        "mfe_reach_pct": {f"{cp:.3f}": v for cp, v in mfe_reach_all.items()},
        "vtp_simulation": vtp_sims,
        "best_vtp": best_vtp,
        "sl_analysis": {
            "total": len(sl_rows),
            "profit_miss_n": len(sl_with_profit),  # had ≥0.05% MFE then hit SL
            "immediate_reversal_n": len(sl_immediate),  # MFE <0.01% (went straight to SL)
            "profit_miss_pct": len(sl_with_profit) / len(sl_rows) if sl_rows else None,
        },
        "mae_analysis": {
            "n_with_data": mae_n,
            "avg_mae": sum(maes) / mae_n if maes else None,
            "max_mae": max(maes) if maes else None,
            "mae_checkpoints": mae_checkpoints,
        },
        "vsl_simulation": vsl_sims,
        "recommendation": _recommendation(
            best_vtp, actual_expectancy, actual_wr, mfes_tp, tp_n, sl_n
        ),
    }


def _recommendation(
    best_vtp: Optional[Dict[str, Any]],
    current_exp: Optional[float],
    wr: Optional[float],
    mfes_tp: List[float],
    tp_n: int, sl_n: int,
) -> str:
    if best_vtp is None or not mfes_tp:
        return "データ不足：判断不可"
    bvtp = best_vtp.get("vtp", CURRENT_TP)
    bexp = best_vtp.get("avg_ret")
    if bexp is None or current_exp is None:
        return "データ不足：期待値計算不可"
    if abs(bvtp - CURRENT_TP) < 0.005:
        return f"現行TP={CURRENT_TP:.3f}%は適切（シミュ最適TP={bvtp:.3f}%で差異なし）"
    if bvtp < CURRENT_TP:
        return (
            f"TPを{bvtp:.3f}%に引き下げると期待値が改善する可能性あり "
            f"（現行={CURRENT_TP:.3f}% → 推奨={bvtp:.3f}%）。"
            "Shadow で検証後に調整を推奨。"
        )
    return (
        f"TPを{bvtp:.3f}%に引き上げると期待値が改善する可能性あり "
        f"（現行={CURRENT_TP:.3f}% → 推奨={bvtp:.3f}%）。"
        "TP到達前のスマート出口が機能している場合は現状維持も検討。"
    )


def _pct(v: Optional[float], digits: int = 3) -> str:
    return f"{v:.{digits}f}%" if v is not None else "N/A"


def _ratio(v: Optional[float]) -> str:
    return f"{v*100:.1f}%" if v is not None else "N/A"


def format_report(data: Dict[str, Any]) -> str:
    lines = [
        f"# TP/SL キャリブレーション レポート ({data['generated_at']})",
        f"  live={data['n_live']}件 backtest={data['n_backtest']}件 合計={data['n_total']}件",
        f"  現行TP={data['current_tp_pct']:.3f}%  現行SL={data['current_sl_pct']:.3f}%",
        "",
    ]

    act = data.get("actual", {})
    lines += [
        "## 現行成績",
        f"  TP={act['tp_n']} SL={act['sl_n']}  WR={_ratio(act.get('wr'))}",
        f"  avg_ret_TP={_pct(act.get('avg_tp_ret'))}  avg_ret_SL={_pct(act.get('avg_sl_ret'))}",
        f"  期待値={_pct(act.get('expectancy'))}",
        f"  avg_MFE(全体)={_pct(act.get('avg_mfe_all'))}  avg_MFE(TP)={_pct(act.get('avg_mfe_tp'))}  avg_MFE(SL)={_pct(act.get('avg_mfe_sl'))}",
        "",
    ]

    sl_a = data.get("sl_analysis", {})
    if sl_a.get("total", 0) > 0:
        lines += [
            "## SL 分析",
            f"  SL計={sl_a['total']}件  うち利益圏から戻りSL={sl_a.get('profit_miss_n',0)}件"
            f"  ({_ratio(sl_a.get('profit_miss_pct'))})  即逆行SL={sl_a.get('immediate_reversal_n',0)}件",
            "",
        ]

    lines += [
        "## MFE 到達率（全トレード中、各水準に到達した割合）",
        f"  {'MFE':>8}  {'全体':>6}  {'TP時':>6}  {'SL時':>6}",
        "  " + "-" * 32,
    ]
    for cp_str, vals in data.get("mfe_reach_pct", {}).items():
        cp_label = f">={float(cp_str):.2f}%"
        lines.append(
            f"  {cp_label:>8}  {_ratio(vals.get('all')):>6}  "
            f"{_ratio(vals.get('tp')):>6}  {_ratio(vals.get('sl')):>6}"
        )

    lines += [
        "",
        "## 仮想TP シミュレーション",
        "  (MFE≥仮想TP → 仮想TPで利確と仮定、SLはそのまま)",
        f"  {'vTP':>8}  {'TP件':>5}  {'SL件':>5}  {'WR':>6}  {'avg_ret':>9}  {'合計ret':>10}",
        "  " + "-" * 52,
    ]
    current_vtp = f"{data['current_tp_pct']:.3f}"
    for vtp_str, s in sorted(data.get("vtp_simulation", {}).items(), key=lambda x: float(x[0])):
        marker = " ◀現行" if vtp_str == current_vtp else ""
        lines.append(
            f"  {float(vtp_str):.3f}%  {s['tp']:>5}  {s['sl']:>5}  "
            f"{_ratio(s.get('wr')):>6}  {_pct(s.get('avg_ret')):>9}  "
            f"{_pct(s.get('total_ret')):>10}{marker}"
        )

    bvtp = data.get("best_vtp")
    if bvtp:
        lines += [
            "",
            f"  シミュ最適TP: {bvtp['vtp']:.3f}%  (avg_ret={_pct(bvtp.get('avg_ret'))})",
        ]

    # MAE section
    mae_a = data.get("mae_analysis", {})
    mae_n = mae_a.get("n_with_data", 0)
    lines += ["", "## MAE 分析（最大逆行幅 max_adv — 2026-05-10 追加）"]
    if mae_n == 0:
        lines.append("  データなし（max_adv フィールド追加後のトレードから蓄積されます）")
    else:
        lines += [
            f"  max_adv データあり: {mae_n}件  avg_MAE={_pct(mae_a.get('avg_mae'))}  max_MAE={_pct(mae_a.get('max_mae'))}",
            "",
            "  MAE 内包率（逆行幅がこの水準以内に収まったトレードの割合）",
            f"  {'SL候補':>8}  {'件数':>5}  {'割合':>6}",
            "  " + "-" * 28,
        ]
        for cp_str, vals in mae_a.get("mae_checkpoints", {}).items():
            lines.append(
                f"  <={float(cp_str):.3f}%  {vals.get('within_n',0):>5}  {_ratio(vals.get('within_pct')):>6}"
            )

    vsl_sims = data.get("vsl_simulation", {})
    if vsl_sims:
        lines += [
            "",
            "## 仮想SL シミュレーション",
            "  (MAE<仮想SL → SLヒットせず実績出口、MAE≥仮想SL → -SLで確定と仮定)",
            f"  {'vSL':>8}  {'TP件':>5}  {'SL件':>5}  {'WR':>6}  {'avg_ret':>9}  {'合計ret':>10}",
            "  " + "-" * 52,
        ]
        current_vsl = f"{data['current_sl_pct']:.3f}"
        for vsl_str, s in sorted(vsl_sims.items(), key=lambda x: float(x[0])):
            marker = " ◀現行" if vsl_str == current_vsl else ""
            lines.append(
                f"  {float(vsl_str):.3f}%  {s['tp']:>5}  {s['sl']:>5}  "
                f"{_ratio(s.get('wr')):>6}  {_pct(s.get('avg_ret')):>9}  "
                f"{_pct(s.get('total_ret')):>10}{marker}"
            )

    lines += [
        "",
        "## 推奨",
        f"  {data.get('recommendation', 'N/A')}",
        "",
        "## 注意",
        "  - max_adv (MAE) フィールドは 2026-05-10 から ai_training_log に追加",
        "  - 仮想SL シミュは MAE データが 30件以上で自動的に有効化",
        "  - 仮想TP シミュは MFE に基づく上限推定であり、スリッページ・スマート出口は考慮外",
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
        (out_dir / f"tp_sl_calibration_report_{TODAY8}.md").write_text(report, encoding="utf-8")
        (out_dir / f"tp_sl_calibration_report_{TODAY8}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n[saved] reports/tp_sl_calibration_report_{TODAY8}.md|.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
