#!/usr/bin/env python3
"""
fib_combo_report.py — AI 学習ログから Fib ゾーン別・コンボ別 WR を集計する。

対象: logs/backtest/ai_training_log_backtest_contra.csv (および live training log)
フィールド: fib_zone, fib_wave3_candidate, aiba_aligned (bot.py session38 以降に追加)

Usage:
    python3 tools/fib_combo_report.py                        # 全期間
    python3 tools/fib_combo_report.py --days 30             # 直近 30 日
    python3 tools/fib_combo_report.py --live-only           # live のみ (exec_mode=LIVE)
    python3 tools/fib_combo_report.py --log custom.csv      # 任意のログファイル
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT.parent.parent / "logs"
DEFAULT_LOG = LOGS_DIR / "backtest" / "ai_training_log_backtest_contra.csv"


def load_training_log(path: Path, days: Optional[int], live_only: bool) -> list[dict]:
    if not path.exists():
        print(f"[fib] Log not found: {path}", file=sys.stderr)
        return []
    cutoff = None
    if days is not None:
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            t = row.get("time", "")
            if cutoff and t[:10] < cutoff:
                continue
            if live_only and row.get("exec_mode", "").upper() != "LIVE":
                continue
            rows.append(row)
    return rows


def _outcome_win(row: dict) -> Optional[bool]:
    o = row.get("outcome", "").upper()
    if o == "TP":
        return True
    if o in ("SL", "TIMEOUT", "EOD"):
        return False
    return None


def _segment_key(row: dict) -> str:
    fib = (row.get("fib_zone") or "NA").strip()
    wave3 = str(row.get("fib_wave3_candidate", "")).strip().lower() in ("1", "true")
    aiba = str(row.get("aiba_aligned", "")).strip().lower() in ("1", "true")
    if wave3 and aiba:
        return "GOLDEN+AIBA_combo"
    if wave3:
        return f"GOLDEN(no_aiba)"
    if fib == "REVERSAL":
        return "REVERSAL"
    if fib in ("SHALLOW", "CONTINUATION", "DEEP"):
        return fib
    return f"fib={fib}"


def report(rows: list[dict]) -> None:
    if not rows:
        print("[fib] No rows found.")
        return

    fib_counts = defaultdict(lambda: {"n": 0, "wins": 0, "pnl_sum": 0.0})
    total_n = 0
    total_with_fib = 0

    for row in rows:
        win = _outcome_win(row)
        if win is None:
            continue
        total_n += 1
        seg = _segment_key(row)
        fib_counts[seg]["n"] += 1
        fib_counts[seg]["wins"] += int(win)
        try:
            fib_counts[seg]["pnl_sum"] += float(row.get("ret_pct") or 0.0)
        except ValueError:
            pass
        fib_zone = (row.get("fib_zone") or "NA").strip()
        if fib_zone not in ("NA", "", "None"):
            total_with_fib += 1

    overall_wr = sum(v["wins"] for v in fib_counts.values()) / total_n * 100 if total_n else 0

    print(f"\n[fib] Total resolved trades: {total_n}  (with fib data: {total_with_fib})")
    print(f"[fib] Overall WR: {overall_wr:.1f}%")
    print(f"\n{'Segment':<25} {'N':>5} {'WR%':>7} {'avg ret%':>9}")
    print("-" * 50)
    for seg in sorted(fib_counts):
        v = fib_counts[seg]
        wr = v["wins"] / v["n"] * 100 if v["n"] else 0
        avg_ret = v["pnl_sum"] / v["n"] if v["n"] else 0.0
        marker = " ✓" if seg.startswith("GOLDEN") else ""
        print(f"  {seg:<23} {v['n']:>5} {wr:>6.1f}% {avg_ret:>+9.4f}%{marker}")

    if total_with_fib == 0:
        print("\n[fib] NOTE: fib_zone column is empty — data accumulates as new trades are logged.")
        print("[fib]       Run after trades complete to see segmented WR.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", type=Path, default=DEFAULT_LOG, help="Training log CSV path")
    ap.add_argument("--days", type=int, default=None, help="Limit to last N days")
    ap.add_argument("--live-only", action="store_true", help="Only include live trades")
    args = ap.parse_args()

    rows = load_training_log(args.log, args.days, args.live_only)
    report(rows)


if __name__ == "__main__":
    main()
