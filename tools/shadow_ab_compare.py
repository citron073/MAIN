#!/usr/bin/env python3
"""Shadow A/B test comparison report.

Two modes:
  (default) Compares MAIN vs Shadow trade_log files side-by-side.
  --ai-log  Compares MAIN vs Shadow using ai_training_log.csv (is_shadow column).
            Use this after 2026-05-13 when enough Shadow ai_training rows have
            accumulated to evaluate WR/PF/avg_ret with the is_shadow field.

Usage:
    python3 tools/shadow_ab_compare.py [--since YYYYMMDD] [--days N]
    python3 tools/shadow_ab_compare.py --ai-log [--since YYYYMMDD]
"""
from __future__ import annotations

import argparse
import collections
import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT.parent / "logs"
MAIN_LOGS_DIR = LOGS_DIR
SHADOW_LOGS_DIR = LOGS_DIR / "instances" / "shadow"

AB_TEST_START = "20260425"  # Shadow restarted with buy_fast_ma_distance_pct=0.06


def _parse_logs(logs_dir: Path, since8: str, days: int) -> Dict:
    since_d = datetime.strptime(since8, "%Y%m%d").date()
    tp = sl = 0
    wins: List[float] = []
    losses: List[float] = []
    ma_near = 0
    observe_ok = 0
    daily: Dict[str, Dict] = {}

    for i in range(days):
        d = since_d + timedelta(days=i)
        if d > datetime.now().date():
            break
        d8 = d.strftime("%Y%m%d")
        f = logs_dir / f"trade_log_{d8}.csv"
        if not f.exists():
            continue

        day_tp = day_sl = day_ma = day_ok = 0
        try:
            for row in csv.reader(f.open(encoding="utf-8", errors="ignore")):
                if len(row) < 2:
                    continue
                res = row[1].strip()
                if res == "OBSERVE_OK":
                    observe_ok += 1
                    day_ok += 1
                if "PAPER_EXIT_TP" in res or res == "TP":
                    tp += 1
                    day_tp += 1
                    if len(row) > 8:
                        try:
                            wins.append(abs(float(row[8])))
                        except Exception:
                            pass
                if "PAPER_EXIT_SL" in res or res == "SL":
                    sl += 1
                    day_sl += 1
                    if len(row) > 8:
                        try:
                            losses.append(abs(float(row[8])))
                        except Exception:
                            pass
                if "FAST_MA_NEAR" in res:
                    ma_near += 1
                    day_ma += 1
        except Exception:
            continue
        daily[d8] = {"tp": day_tp, "sl": day_sl, "ma": day_ma, "ok": day_ok}

    total_trades = tp + sl
    wr = tp / total_trades * 100 if total_trades > 0 else None
    pf = sum(wins) / sum(losses) if losses and sum(losses) > 0 else None
    total_opps = observe_ok + ma_near
    ma_block_pct = ma_near / total_opps * 100 if total_opps > 0 else None

    return {
        "tp": tp,
        "sl": sl,
        "total": total_trades,
        "wr": wr,
        "pf": pf,
        "observe_ok": observe_ok,
        "ma_near": ma_near,
        "total_opps": total_opps,
        "ma_block_pct": ma_block_pct,
        "daily": daily,
    }


AI_LOG_MAIN = LOGS_DIR / "ai_training_log.csv"
AI_LOG_SHADOW = LOGS_DIR / "instances" / "shadow" / "ai_training_log.csv"


def _parse_ai_training_log(ai_log_path: Path, since8: str) -> Dict:
    """Parse ai_training_log.csv and return WR/PF/avg_ret stats since since8."""
    if not ai_log_path.exists():
        return {"tp": 0, "sl": 0, "total": 0, "wr": None, "pf": None, "avg_ret": None, "exists": False}
    since_d = datetime.strptime(since8, "%Y%m%d").date()
    tp_rets: List[float] = []
    sl_rets: List[float] = []
    hour_n: Dict[int, int] = {}
    hour_tp: Dict[int, int] = {}
    try:
        with ai_log_path.open(encoding="utf-8", errors="ignore") as f:
            for row in csv.DictReader(f):
                t = (row.get("exit_time") or row.get("entry_time") or "")[:10]
                try:
                    if datetime.strptime(t, "%Y-%m-%d").date() < since_d:
                        continue
                except ValueError:
                    continue
                entry_t = (row.get("entry_time") or "")
                h: Optional[int] = None
                try:
                    h = int(entry_t[11:13]) if len(entry_t) >= 13 else None
                except (ValueError, TypeError):
                    pass
                ret = 0.0
                try:
                    ret = float(row.get("ret_pct") or 0)
                except ValueError:
                    pass
                outcome = str(row.get("outcome", "")).strip().upper()
                is_win = outcome in ("TP", "WIN") or (outcome not in ("SL", "LOSS") and ret > 0)
                is_trade = outcome in ("TP", "WIN", "SL", "LOSS") or abs(ret) > 0.000001
                if not is_trade:
                    continue
                if is_win:
                    tp_rets.append(ret)
                else:
                    sl_rets.append(ret)
                if h is not None:
                    hour_n[h] = hour_n.get(h, 0) + 1
                    if is_win:
                        hour_tp[h] = hour_tp.get(h, 0) + 1
    except Exception:
        pass
    tp = len(tp_rets)
    sl = len(sl_rets)
    total = tp + sl
    wr = tp / total * 100 if total > 0 else None
    sum_wins = sum(tp_rets)
    sum_losses = abs(sum(sl_rets)) if sl_rets else 0.0
    pf = sum_wins / sum_losses if sum_losses > 0 and sum_wins > 0 else None
    avg_ret = (sum(tp_rets) + sum(sl_rets)) / total * 100 if total > 0 else None
    return {
        "tp": tp, "sl": sl, "total": total,
        "wr": wr, "pf": pf, "avg_ret": avg_ret,
        "hour_n": hour_n, "hour_tp": hour_tp,
        "exists": True,
    }


def _run_ai_log_mode(since8: str) -> int:
    print("=== Shadow A/B 比較 (ai_training_log モード) ===")
    print(f"開始日: {since8[:4]}/{since8[4:6]}/{since8[6:]}  (is_shadow 列で識別)")
    print(f"MAIN ログ:   {AI_LOG_MAIN}")
    print(f"Shadow ログ: {AI_LOG_SHADOW}")
    print()

    main_d = _parse_ai_training_log(AI_LOG_MAIN, since8)
    shadow_d = _parse_ai_training_log(AI_LOG_SHADOW, since8)

    if not main_d["exists"]:
        print(f"⚠️  MAIN ai_training_log が見つかりません: {AI_LOG_MAIN}")
    if not shadow_d["exists"]:
        print(f"⚠️  Shadow ai_training_log が見つかりません: {AI_LOG_SHADOW}")

    def fv(v: Optional[float], fmt: str, na: str = "N/A") -> str:
        return fmt.format(v) if v is not None else na

    print(f"{'指標':<28} {'MAIN':>12} {'Shadow':>12} {'差分':>10}")
    print("-" * 66)

    def row_line(label: str, mv, sv, fmt: str, higher_better: bool = True) -> None:
        ms = fv(mv, fmt)
        ss = fv(sv, fmt)
        if mv is not None and sv is not None:
            d = float(sv) - float(mv)  # type: ignore[arg-type]
            sign = "+" if d > 0 else ""
            arrow = "↑" if (d > 0) == higher_better else "↓"
            ds = f"{sign}{d:.2f} {arrow}"
        else:
            ds = "N/A"
        print(f"  {label:<26} {ms:>12} {ss:>12} {ds:>10}")

    row_line("取引数 (TP+SL)", main_d["total"], shadow_d["total"], "{:.0f}件")
    row_line("WR", main_d["wr"], shadow_d["wr"], "{:.1f}%")
    row_line("PF", main_d["pf"], shadow_d["pf"], "{:.3f}")
    row_line("avg_ret", main_d["avg_ret"], shadow_d["avg_ret"], "{:.4f}%")
    print()

    # Hourly breakdown
    all_hours = sorted(set(list(main_d["hour_n"].keys()) + list(shadow_d["hour_n"].keys())))
    if all_hours:
        print(f"  {'時間帯':<8} {'MAIN WR(N)':>14} {'Shadow WR(N)':>16}")
        print("  " + "-" * 40)
        for h in all_hours:
            mn = main_d["hour_n"].get(h, 0)
            mtp = main_d["hour_tp"].get(h, 0)
            sn = shadow_d["hour_n"].get(h, 0)
            stp = shadow_d["hour_tp"].get(h, 0)
            mwr_s = f"{mtp/mn*100:.0f}%({mn})" if mn > 0 else "-"
            swr_s = f"{stp/sn*100:.0f}%({sn})" if sn > 0 else "-"
            print(f"  {h:02d}h      {mwr_s:>14} {swr_s:>16}")
        print()

    # Judgment
    print("=== 判定 ===")
    mt = main_d["total"]
    st = shadow_d["total"]
    if mt < 5 or st < 5:
        print(f"⚠️  データ不足 — MAIN={mt}件 / Shadow={st}件 (最低基準: 各5件)")
        print("   2026-05-13 以降に再確認してください。")
    else:
        mwr = main_d["wr"] or 0
        swr = shadow_d["wr"] or 0
        mpf = main_d["pf"] or 0
        spf = shadow_d["pf"] or 0
        wr_diff = swr - mwr
        pf_diff = spf - mpf
        print(f"WR差: {wr_diff:+.1f}pt  PF差: {pf_diff:+.3f}")
        if swr >= mwr + 5 and spf >= mpf:
            print("✅ Shadow が WR+5pt 以上かつ PF でも上回っています → Shadow 設定が有利")
        elif swr < mwr - 3 or spf < mpf - 0.05:
            print("⚠️  Shadow が MAIN を明確に下回っています → 要見直し")
        else:
            print("📊 有意差なし — 引き続き観察を続けてください。")
    return 0


def _fmt(v, fmt: str, na: str = "N/A") -> str:
    if v is None:
        return na
    return fmt.format(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=AB_TEST_START, help="Start date YYYYMMDD (default: A/B test start)")
    ap.add_argument("--days", type=int, default=30, help="Max days to look back (default=30)")
    ap.add_argument("--ai-log", action="store_true", help="Compare using ai_training_log.csv (is_shadow mode)")
    args = ap.parse_args()

    if args.ai_log:
        return _run_ai_log_mode(args.since)

    print(f"=== Shadow A/B Test Comparison ===")
    print(f"A/B開始: {args.since[:4]}/{args.since[4:6]}/{args.since[6:]}  期間: {args.days}日")
    print(f"MAIN  buy_fast_ma_distance_pct = 0.08")
    print(f"Shadow buy_fast_ma_distance_pct = 0.06  (fast_MAフィルター緩和)")
    print()

    main_data = _parse_logs(MAIN_LOGS_DIR, args.since, args.days)
    shadow_data = _parse_logs(SHADOW_LOGS_DIR, args.since, args.days)

    # Side-by-side summary
    print(f"{'指標':<28} {'MAIN (0.08)':>14} {'Shadow (0.06)':>14} {'差分':>12}")
    print("-" * 72)

    def row(label, m, s, fmt, delta_fn=None, higher_better=True):
        mv = _fmt(m, fmt)
        sv = _fmt(s, fmt)
        if m is not None and s is not None and delta_fn:
            d = delta_fn(s, m)
            sign = "+" if d > 0 else ""
            arrow = "↑" if (d > 0) == higher_better else "↓"
            dv = f"{sign}{d:.2f} {arrow}"
        else:
            dv = "N/A"
        print(f"  {label:<26} {mv:>14} {sv:>14} {dv:>12}")

    row("取引数 (TP+SL)", main_data["total"], shadow_data["total"],
        "{:.0f}件", lambda s, m: s - m)
    row("WR", main_data["wr"], shadow_data["wr"],
        "{:.1f}%", lambda s, m: s - m)
    row("PF", main_data["pf"], shadow_data["pf"],
        "{:.3f}", lambda s, m: s - m)
    row("OBSERVE_OK (通過)", main_data["observe_ok"], shadow_data["observe_ok"],
        "{:.0f}件", lambda s, m: s - m)
    row("fast_ma_near ブロック", main_data["ma_near"], shadow_data["ma_near"],
        "{:.0f}件", lambda s, m: s - m, higher_better=False)
    row("fast_ma_near ブロック率", main_data["ma_block_pct"], shadow_data["ma_block_pct"],
        "{:.1f}%", lambda s, m: s - m, higher_better=False)

    print()

    # Daily breakdown
    all_dates = sorted(set(list(main_data["daily"].keys()) + list(shadow_data["daily"].keys())))
    if all_dates:
        print(f"  {'日付':<10} {'MAIN TP/SL/MA':>16} {'Shadow TP/SL/MA':>18}")
        print("  " + "-" * 48)
        for d8 in all_dates:
            md = main_data["daily"].get(d8, {})
            sd = shadow_data["daily"].get(d8, {})
            main_s = f"TP={md.get('tp',0)} SL={md.get('sl',0)} MA↓={md.get('ma',0)}"
            shadow_s = f"TP={sd.get('tp',0)} SL={sd.get('sl',0)} MA↓={sd.get('ma',0)}"
            print(f"  {d8:<10} {main_s:>16} {shadow_s:>18}")

    print()

    # Summary judgment
    print("=== 判定 ===")
    if shadow_data["total"] < 5 or main_data["total"] < 5:
        print("⚠️  データ不足 — サンプル数が少なすぎます。1〜2週間後に再確認してください。")
        print(f"   MAIN={main_data['total']}件 / Shadow={shadow_data['total']}件 (判定最低基準: 各5件)")
    else:
        # Compare WR
        mwr = main_data["wr"] or 0
        swr = shadow_data["wr"] or 0
        mpf = main_data["pf"] or 0
        spf = shadow_data["pf"] or 0
        mma = main_data["ma_block_pct"] or 0
        sma = shadow_data["ma_block_pct"] or 0

        wr_diff = swr - mwr
        pf_diff = spf - mpf
        ma_diff = sma - mma  # negative = Shadow blocks less = good

        print(f"WR差: {wr_diff:+.1f}pt  PF差: {pf_diff:+.3f}  MA block率差: {ma_diff:+.1f}pt")
        if swr >= mwr and spf >= mpf:
            print("✅ Shadow が WR・PF ともに上回っています → buy_fast_ma_distance_pct=0.06 が有利")
            print("   次回 /filter で確認後、MAIN も 0.06 への変更を検討してください。")
        elif swr < mwr - 3 or spf < mpf - 0.05:
            print("⚠️  Shadow が MAIN を下回っています → 0.06 の緩和は逆効果の可能性")
            print("   Shadow の設定を 0.08 に戻すか、引き続き観察してください。")
        else:
            print("📊 有意差なし — 引き続き観察を続けてください。")
            if ma_diff < -5:
                print(f"   Shadow の MA ブロック率が {abs(ma_diff):.1f}pt 低く、より多くエントリーできています。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
