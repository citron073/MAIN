#!/usr/bin/env python3
"""Backtest engine: replay historical OHLC bars through the bot strategy and generate
AI training samples for threshold calibration.

Usage:
    python3 tools/run_backtest.py [--ohlc PATH] [--out PATH] [--dry-run] [--verbose]

    --ohlc PATH    Historical OHLC CSV (default=data/historical_ohlc.csv)
    --out PATH     Output training log (default=logs/backtest/ai_training_log_backtest.csv)
    --dry-run      Show stats without writing output
    --verbose      Print each simulated trade
    --tp-pct F     Take-profit % (default=0.190)
    --sl-pct F     Stop-loss % (default=0.140)
    --fast-n N     Fast MA period (default=5)
    --slow-n N     Slow MA period (default=20)
    --max-hold N   Max hold in bars before timeout (default=36 = 3 hours for 5-min bars)
    --start-hour H Only enter between this hour and end-hour JST (default=10)
    --end-hour H   (default=16)
    --good-hours   Comma-separated hours with +0.05 score boost (default=10,11,12)
    --bad-hours    Comma-separated hours with -0.08 score penalty (default=14,15,16)

Training log format: matches AI_TRAIN_FIELDS in bot.py so the bot can include it in
threshold calibration via ai_train_include_backtest=1.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OHLC = ROOT / "data" / "historical_ohlc.csv"
DEFAULT_OUT = ROOT.parent / "logs" / "backtest" / "ai_training_log_backtest.csv"

AI_TRAIN_FIELDS = [
    "time", "pos_id", "side", "entry_time", "exit_time", "hold_min",
    "entry_price", "exit_price", "ret_pct", "outcome", "result",
    "ai_score", "ai_score_extend", "spread_entry_pct", "ma_gap_pct",
    "ma_slope_pct_per_step", "volatility_pct", "trendline_slope_pct_per_step",
    "channel_pos", "channel_width_pct", "trend", "signal",
    "best_fav", "extend_count", "exec_mode", "stage",
]

JST_OFFSET = 9 * 3600  # seconds


def _load_ohlc(path: Path) -> List[Dict[str, Any]]:
    bars: List[Dict[str, Any]] = []
    if not path.exists():
        print(f"[ERROR] OHLC file not found: {path}")
        return bars
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                ts_str = str(row.get("ts", "")).strip()
                if not ts_str:
                    continue
                # Parse ISO8601 with or without timezone
                for fmt in ("%Y-%m-%dT%H:%M:%S+00:00", "%Y-%m-%dT%H:%M:%S",
                            "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
                    try:
                        dt = datetime.strptime(ts_str[:19], fmt[:19]).replace(tzinfo=timezone.utc)
                        break
                    except Exception:
                        continue
                else:
                    continue
                bars.append({
                    "ts": dt,
                    "o": float(row["o"]),
                    "h": float(row["h"]),
                    "l": float(row["l"]),
                    "c": float(row["c"]),
                    "ticks": int(row.get("ticks", 1)),
                })
            except Exception:
                continue
    bars.sort(key=lambda b: b["ts"])
    return bars


def _sma(prices: List[float], n: int) -> Optional[float]:
    if len(prices) < n:
        return None
    return mean(prices[-n:])


def _volatility_pct(prices: List[float], n: int) -> Optional[float]:
    if len(prices) < n:
        return None
    tail = prices[-n:]
    m = mean(tail)
    if m == 0:
        return None
    try:
        sd = stdev(tail)
    except Exception:
        sd = 0.0
    return sd / m * 100.0


def _efficiency_ratio(prices: List[float], n: int) -> Optional[float]:
    if len(prices) < n:
        return None
    tail = prices[-n:]
    gross = sum(abs(tail[i] - tail[i - 1]) for i in range(1, len(tail)))
    if gross == 0:
        return None
    net = abs(tail[-1] - tail[0])
    return net / gross


def _trendline_slope(prices: List[float], n: int) -> Optional[float]:
    """Least-squares slope as % per step."""
    if len(prices) < n:
        return None
    tail = prices[-n:]
    m = mean(tail)
    if m == 0:
        return None
    xs = list(range(n))
    x_mean = mean(xs)
    num = sum((xs[i] - x_mean) * (tail[i] - m) for i in range(n))
    den = sum((xs[i] - x_mean) ** 2 for i in range(n))
    if den == 0:
        return None
    slope = num / den
    return slope / m * 100.0


def _channel_pos(prices: List[float], n: int) -> Optional[float]:
    """Price position within [min, max] channel: 0=bottom, 1=top."""
    if len(prices) < n:
        return None
    tail = prices[-n:]
    lo, hi = min(tail), max(tail)
    if hi <= lo:
        return 0.5
    return (tail[-1] - lo) / (hi - lo)


def _compute_ai_score(
    side: str,
    fast_ma: float,
    slow_ma: float,
    trend: str,
    ma_gap_pct: float,
    vol_pct: Optional[float],
    er: Optional[float],
    hour_jst: int,
    good_hours: set,
    bad_hours: set,
) -> float:
    score = 0.60

    # Trend alignment
    if (side == "BUY" and trend == "UP") or (side == "SELL" and trend == "DOWN"):
        score += 0.05
    else:
        score -= 0.10

    # MA gap
    gap = abs(ma_gap_pct)
    if gap >= 0.08:
        score += 0.05
    elif gap < 0.03:
        score -= 0.05

    # Volatility
    if vol_pct is not None:
        if vol_pct < 0.05:
            score -= 0.05  # too flat
        elif 0.05 <= vol_pct < 0.15:
            score += 0.03
        elif vol_pct > 0.30:
            score -= 0.05  # too volatile

    # Efficiency ratio (trend strength)
    if er is not None:
        if er >= 0.30:
            score += 0.05
        elif er < 0.15:
            score -= 0.08

    # Time of day
    if hour_jst in good_hours:
        score += 0.05
    elif hour_jst in bad_hours:
        score -= 0.08

    return round(max(0.30, min(0.95, score)), 4)


def _simulate_outcome(
    bars: List[Dict[str, Any]],
    entry_idx: int,
    side: str,
    entry_price: float,
    tp_pct: float,
    sl_pct: float,
    max_hold: int,
) -> Tuple[str, float, float, int]:
    """Return (outcome, exit_price, best_fav_pct, hold_bars)."""
    tp_price = entry_price * (1 + tp_pct / 100) if side == "BUY" else entry_price * (1 - tp_pct / 100)
    sl_price = entry_price * (1 - sl_pct / 100) if side == "BUY" else entry_price * (1 + sl_pct / 100)
    best_fav = 0.0

    for j in range(1, max_hold + 1):
        idx = entry_idx + j
        if idx >= len(bars):
            break
        bar = bars[idx]
        h, l = bar["h"], bar["l"]

        if side == "BUY":
            fav_pct = (h - entry_price) / entry_price * 100
            best_fav = max(best_fav, fav_pct)
            if h >= tp_price:
                return "TP", tp_price, best_fav, j
            if l <= sl_price:
                return "SL", sl_price, best_fav, j
        else:
            fav_pct = (entry_price - l) / entry_price * 100
            best_fav = max(best_fav, fav_pct)
            if l <= tp_price:
                return "TP", tp_price, best_fav, j
            if h >= sl_price:
                return "SL", sl_price, best_fav, j

    exit_price = bars[min(entry_idx + max_hold, len(bars) - 1)]["c"]
    return "TIMEOUT", exit_price, best_fav, max_hold


def run_backtest(
    ohlc_path: Path,
    out_path: Path,
    *,
    tp_pct: float = 0.190,
    sl_pct: float = 0.140,
    fast_n: int = 5,
    slow_n: int = 20,
    max_hold: int = 36,
    start_hour_jst: int = 10,
    end_hour_jst: int = 16,
    good_hours: set = frozenset({10, 11, 12}),
    bad_hours: set = frozenset({14, 15, 16}),
    min_er: float = 0.15,
    verbose: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    bars = _load_ohlc(ohlc_path)
    if not bars:
        return {"error": "no_bars", "trades": 0}

    print(f"[backtest] loaded {len(bars)} OHLC bars from {ohlc_path}")

    warmup = max(slow_n + 5, 30)
    closes: List[float] = []
    trades: List[Dict[str, Any]] = []
    prev_trend: Optional[str] = None
    in_position = False
    cooldown_bars = 0

    for i, bar in enumerate(bars):
        closes.append(bar["c"])

        if len(closes) < warmup:
            continue

        if cooldown_bars > 0:
            cooldown_bars -= 1
            continue

        fast_ma = _sma(closes, fast_n)
        slow_ma = _sma(closes, slow_n)
        if fast_ma is None or slow_ma is None or slow_ma == 0:
            continue

        curr_trend = "UP" if fast_ma > slow_ma else "DOWN"

        # Hour filter (JST = UTC + 9h)
        hour_jst = (bar["ts"].hour + JST_OFFSET // 3600) % 24

        # Only look for entry signals during trading hours
        if not (start_hour_jst <= hour_jst < end_hour_jst):
            prev_trend = curr_trend
            continue

        # Skip blocked hours (equivalent to no_paper_hours)
        if hour_jst in bad_hours and hour_jst not in {10, 11, 12, 13}:
            prev_trend = curr_trend
            continue

        # Entry on trend crossover
        if prev_trend is not None and prev_trend != curr_trend:
            side = "BUY" if curr_trend == "UP" else "SELL"

            # Compute features
            ma_gap_pct = (fast_ma - slow_ma) / slow_ma * 100 if slow_ma != 0 else 0.0
            vol_pct = _volatility_pct(closes, slow_n)
            er = _efficiency_ratio(closes, 20)

            # ER filter equivalent to trend_strength_min_er
            if er is not None and er < min_er:
                prev_trend = curr_trend
                continue

            ai_score = _compute_ai_score(
                side, fast_ma, slow_ma, curr_trend, ma_gap_pct,
                vol_pct, er, hour_jst, good_hours, bad_hours,
            )

            entry_price = bar["c"]
            outcome, exit_price, best_fav, hold_bars = _simulate_outcome(
                bars, i, side, entry_price, tp_pct, sl_pct, max_hold
            )

            if side == "BUY":
                ret_pct = (exit_price - entry_price) / entry_price * 100
            else:
                ret_pct = (entry_price - exit_price) / entry_price * 100

            tl_slope = _trendline_slope(closes, slow_n)
            ch_pos = _channel_pos(closes, slow_n)
            ch_width = None
            if len(closes) >= slow_n:
                tail = closes[-slow_n:]
                lo, hi = min(tail), max(tail)
                ch_width = (hi - lo) / mean(tail) * 100 if mean(tail) > 0 else None

            entry_ts = bar["ts"]
            exit_idx = min(i + hold_bars, len(bars) - 1)
            exit_ts = bars[exit_idx]["ts"]
            hold_min = hold_bars * 5  # assuming 5-min bars

            pos_id = f"bt_{bar['ts'].strftime('%Y%m%d%H%M')}_{side[:1]}"
            result_str = f"PAPER_EXIT_{outcome}"

            row: Dict[str, Any] = {
                "time": exit_ts.strftime("%Y-%m-%d %H:%M:%S"),
                "pos_id": pos_id,
                "side": side,
                "entry_time": entry_ts.strftime("%Y-%m-%d %H:%M:%S"),
                "exit_time": exit_ts.strftime("%Y-%m-%d %H:%M:%S"),
                "hold_min": hold_min,
                "entry_price": round(entry_price, 0),
                "exit_price": round(exit_price, 0),
                "ret_pct": round(ret_pct, 4),
                "outcome": outcome,
                "result": result_str,
                "ai_score": ai_score,
                "ai_score_extend": "",
                "spread_entry_pct": 0.01,
                "ma_gap_pct": round(ma_gap_pct, 4),
                "ma_slope_pct_per_step": round(tl_slope, 6) if tl_slope is not None else "",
                "volatility_pct": round(vol_pct, 4) if vol_pct is not None else "",
                "trendline_slope_pct_per_step": round(tl_slope, 6) if tl_slope is not None else "",
                "channel_pos": round(ch_pos, 4) if ch_pos is not None else "",
                "channel_width_pct": round(ch_width, 4) if ch_width is not None else "",
                "trend": curr_trend,
                "signal": f"BT_{side}",
                "best_fav": round(best_fav, 4),
                "extend_count": 0,
                "exec_mode": "PAPER",
                "stage": "backtest",
            }
            trades.append(row)

            if verbose:
                print(f"  {entry_ts.strftime('%m/%d %H:%M')} {side} {entry_price:,.0f} "
                      f"→ {outcome} {exit_price:,.0f} ret={ret_pct:+.3f}% score={ai_score}")

            cooldown_bars = fast_n  # avoid re-entry immediately after signal
            in_position = False

        prev_trend = curr_trend

    tp_n = sum(1 for t in trades if t["outcome"] == "TP")
    sl_n = sum(1 for t in trades if t["outcome"] == "SL")
    to_n = sum(1 for t in trades if t["outcome"] == "TIMEOUT")
    total = len(trades)
    wr = tp_n / total * 100 if total > 0 else 0
    avg_ret = mean([float(t["ret_pct"]) for t in trades]) if trades else 0
    wins = [float(t["ret_pct"]) for t in trades if float(t["ret_pct"]) > 0]
    losses = [abs(float(t["ret_pct"])) for t in trades if float(t["ret_pct"]) < 0]
    avg_win = mean(wins) if wins else 0
    avg_loss = mean(losses) if losses else 0
    pf = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else 0

    print(f"\n[results] trades={total} TP={tp_n} SL={sl_n} TO={to_n}")
    print(f"  WR={wr:.1f}%  avg_ret={avg_ret:+.4f}%  PF={pf:.3f}")
    print(f"  avg_win={avg_win:.4f}%  avg_loss={avg_loss:.4f}%")

    if dry_run:
        print("[dry-run] not writing output")
        return {"trades": total, "tp": tp_n, "sl": sl_n, "wr": wr, "pf": pf, "avg_ret": avg_ret}

    # Write training log
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=AI_TRAIN_FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in trades:
            w.writerow(row)
    tmp.replace(out_path)
    print(f"  saved to: {out_path}")

    return {"trades": total, "tp": tp_n, "sl": sl_n, "wr": wr, "pf": pf}


def run_sweep(
    ohlc_path: Path,
    *,
    fast_n: int = 5,
    slow_n: int = 20,
    max_hold: int = 36,
    start_hour_jst: int = 10,
    end_hour_jst: int = 16,
    good_hours: set = frozenset({10, 11, 12}),
    bad_hours: set = frozenset({14, 15, 16}),
    min_er: float = 0.15,
) -> None:
    """Try a grid of TP/SL combinations and print a comparison table."""
    tp_candidates = [0.160, 0.180, 0.190, 0.200, 0.220]
    sl_candidates = [0.110, 0.120, 0.130, 0.140, 0.160]

    print("=== パラメータスイープ結果 ===")
    print(f"  OHLCデータ: {ohlc_path}")
    print(f"  グリッド: TP {tp_candidates}  ×  SL {sl_candidates}")
    print()
    print(f"  {'TP%':>6}  {'SL%':>6}  {'trades':>7}  {'WR%':>7}  {'PF':>7}  {'avg_ret%':>9}")
    print("  " + "-" * 55)

    results = []
    for tp in tp_candidates:
        for sl in sl_candidates:
            r = run_backtest(
                ohlc_path=ohlc_path,
                out_path=Path("/dev/null"),
                tp_pct=tp,
                sl_pct=sl,
                fast_n=fast_n,
                slow_n=slow_n,
                max_hold=max_hold,
                start_hour_jst=start_hour_jst,
                end_hour_jst=end_hour_jst,
                good_hours=good_hours,
                bad_hours=bad_hours,
                min_er=min_er,
                verbose=False,
                dry_run=True,
            )
            r["tp_pct"] = tp
            r["sl_pct"] = sl
            results.append(r)

    results.sort(key=lambda x: x.get("pf", 0), reverse=True)
    for r in results:
        tp = r["tp_pct"]
        sl = r["sl_pct"]
        n = r.get("trades", 0)
        wr = r.get("wr", 0)
        pf = r.get("pf", 0)
        avg_ret = r.get("avg_ret", 0)
        marker = " ← best" if r is results[0] else ""
        print(f"  {tp:>6.3f}  {sl:>6.3f}  {n:>7d}  {wr:>7.1f}  {pf:>7.3f}  {avg_ret:>+9.4f}{marker}")

    print()
    best = results[0]
    print(f"推奨: tp_buy_pct={best['tp_pct']:.3f}  sl_pct={best['sl_pct']:.3f}"
          f"  (PF={best.get('pf', 0):.3f}  WR={best.get('wr', 0):.1f}%  n={best.get('trades', 0)})")
    print()
    print("注意: バックテスト結果はオーバーフィットリスクがあります。")
    print("  改善幅が 0.05 PF 未満の場合は現行パラメータを維持してください。")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ohlc", type=Path, default=DEFAULT_OHLC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--tp-pct", type=float, default=0.190)
    ap.add_argument("--sl-pct", type=float, default=0.140)
    ap.add_argument("--fast-n", type=int, default=5)
    ap.add_argument("--slow-n", type=int, default=20)
    ap.add_argument("--max-hold", type=int, default=36)
    ap.add_argument("--start-hour", type=int, default=10)
    ap.add_argument("--end-hour", type=int, default=16)
    ap.add_argument("--good-hours", type=str, default="10,11,12")
    ap.add_argument("--bad-hours", type=str, default="14,15,16")
    ap.add_argument("--min-er", type=float, default=0.15)
    ap.add_argument("--sweep", action="store_true",
                    help="Run TP/SL grid search instead of single backtest")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    good = {int(h.strip()) for h in args.good_hours.split(",") if h.strip()}
    bad = {int(h.strip()) for h in args.bad_hours.split(",") if h.strip()}

    if args.sweep:
        run_sweep(
            ohlc_path=args.ohlc,
            fast_n=args.fast_n,
            slow_n=args.slow_n,
            max_hold=args.max_hold,
            start_hour_jst=args.start_hour,
            end_hour_jst=args.end_hour,
            good_hours=good,
            bad_hours=bad,
            min_er=args.min_er,
        )
        return 0

    result = run_backtest(
        ohlc_path=args.ohlc,
        out_path=args.out,
        tp_pct=args.tp_pct,
        sl_pct=args.sl_pct,
        fast_n=args.fast_n,
        slow_n=args.slow_n,
        max_hold=args.max_hold,
        start_hour_jst=args.start_hour,
        end_hour_jst=args.end_hour,
        good_hours=good,
        bad_hours=bad,
        min_er=args.min_er,
        verbose=args.verbose,
        dry_run=args.dry_run,
    )

    trades = result.get("trades", 0)
    if not args.dry_run and trades > 0:
        print(f"\n[next steps]")
        print(f"  To enable backtest training: add to CONTROL.csv:")
        print(f"    ai_train_include_backtest,1")
        print(f"    ai_train_backtest_boost,0.30")
        print(f"    ai_train_backtest_gate_min_samples,{min(300, trades)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
