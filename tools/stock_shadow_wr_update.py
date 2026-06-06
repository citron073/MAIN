#!/usr/bin/env python3
"""
stock_shadow_wr_update.py — backtest CSV から取引ベース WR を集計し
stock_shadow_state.json に trade_wr_* / weekly_trade_stats を書き戻す。

取引日WR（daily_pnl_usd ベース）より正確な TP/SL ベースの WR を提供する。

Usage:
    python3 stock_shadow_wr_update.py              # update state.json in-place
    python3 stock_shadow_wr_update.py --print      # print stats only, no write
    python3 stock_shadow_wr_update.py --weeks 4    # last N weeks (default: all)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVIEW_OUT = ROOT / "review_out"
STATE_FILE = REVIEW_OUT / "stock_shadow_state.json"

EXIT_ACTIONS = {"SELL", "COVER"}


def _iso_week(ts_str: str) -> str:
    """Return 'YYYY-Www' for a timestamp string."""
    try:
        dt = datetime.strptime(ts_str[:10], "%Y-%m-%d")
        return dt.strftime("%G-W%V")
    except ValueError:
        return "unknown"


def load_trades() -> list[dict]:
    """Load all exit rows (SELL/COVER) with pnl_usd from backtest_*.csv."""
    trades: list[dict] = []
    for f in sorted(REVIEW_OUT.glob("backtest_*.csv")):
        try:
            with f.open(encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    if row.get("action", "").upper() not in EXIT_ACTIONS:
                        continue
                    pnl_raw = row.get("pnl_usd", "").strip()
                    if not pnl_raw:
                        continue
                    try:
                        pnl = float(pnl_raw)
                    except ValueError:
                        continue
                    trades.append({
                        "ts": row.get("timestamp_jst", ""),
                        "symbol": row.get("symbol", ""),
                        "action": row.get("action", ""),
                        "pnl_usd": pnl,
                        "week": _iso_week(row.get("timestamp_jst", "")),
                    })
        except Exception as exc:
            print(f"  [!] {f.name}: {exc}", file=sys.stderr)
    return trades


def compute_stats(trades: list[dict], weeks: int | None = None) -> dict:
    if not trades:
        return {"trade_wr_pct": None, "trade_wr_n": 0, "trade_wr_wins": 0,
                "trade_pnl_usd": 0.0, "weekly_trade_stats": {}}

    # Optional time filter
    if weeks is not None:
        cutoff_ts = (datetime.utcnow() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
        trades = [t for t in trades if t["ts"][:10] >= cutoff_ts]

    weekly: dict[str, dict] = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0})
    total_n = 0
    total_wins = 0
    total_pnl = 0.0

    for t in trades:
        wk = t["week"]
        win = t["pnl_usd"] > 0
        weekly[wk]["n"] += 1
        weekly[wk]["wins"] += int(win)
        weekly[wk]["pnl"] += t["pnl_usd"]
        total_n += 1
        total_wins += int(win)
        total_pnl += t["pnl_usd"]

    weekly_stats = {
        wk: {
            "n": v["n"],
            "wins": v["wins"],
            "wr_pct": round(v["wins"] / v["n"] * 100, 1) if v["n"] else None,
            "pnl_usd": round(v["pnl"], 2),
        }
        for wk, v in sorted(weekly.items())
    }

    return {
        "trade_wr_pct": round(total_wins / total_n * 100, 1) if total_n else None,
        "trade_wr_n": total_n,
        "trade_wr_wins": total_wins,
        "trade_pnl_usd": round(total_pnl, 2),
        "weekly_trade_stats": weekly_stats,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", help="Print stats only, no write")
    ap.add_argument("--weeks", type=int, default=None, help="Limit to last N weeks")
    args = ap.parse_args()

    trades = load_trades()
    stats = compute_stats(trades, weeks=args.weeks)

    print(f"[wr] trades={stats['trade_wr_n']}  wins={stats['trade_wr_wins']}  "
          f"WR={stats['trade_wr_pct']}%  PnL=${stats['trade_pnl_usd']}")
    if stats["weekly_trade_stats"]:
        print("[wr] Weekly breakdown:")
        for wk, v in stats["weekly_trade_stats"].items():
            print(f"     {wk}: {v['wins']}/{v['n']} ({v['wr_pct']}%) PnL=${v['pnl_usd']}")

    if args.print:
        return

    # Update stock_shadow_state.json in-place
    state: dict = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    state.update(stats)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[wr] Updated → {STATE_FILE}")


if __name__ == "__main__":
    main()
