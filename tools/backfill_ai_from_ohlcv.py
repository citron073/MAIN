#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build synthetic AI training rows from historical OHLCV.

This tool is intentionally conservative:
- Uses next bar open for entry (avoid look-ahead on signal bar close).
- Applies TP/SL/timeout exits with pessimistic conflict handling (SL first).
- Subtracts round-trip fee from ret_pct.

Output schema is aligned with bot AI training log so that bot.py can ingest it.
"""

from __future__ import annotations

import argparse
import json
import math
from itertools import product
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


AI_TRAIN_FIELDS = [
    "time",
    "pos_id",
    "side",
    "entry_time",
    "exit_time",
    "hold_min",
    "entry_price",
    "exit_price",
    "ret_pct",
    "outcome",
    "result",
    "ai_score",
    "ai_score_extend",
    "spread_entry_pct",
    "ma_gap_pct",
    "ma_slope_pct_per_step",
    "volatility_pct",
    "trendline_slope_pct_per_step",
    "channel_pos",
    "channel_width_pct",
    "trend",
    "signal",
    "best_fav",
    "extend_count",
    "exec_mode",
    "stage",
]


def _pick_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols = {str(c).strip().lower(): str(c) for c in df.columns}
    for c in candidates:
        hit = cols.get(c.lower())
        if hit:
            return hit
    return None


def load_ohlcv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        raise RuntimeError(f"empty csv: {path}")

    col_time = _pick_col(df, ["time", "timestamp", "datetime", "date", "open_time"])
    col_open = _pick_col(df, ["open", "o"])
    col_high = _pick_col(df, ["high", "h"])
    col_low = _pick_col(df, ["low", "l"])
    col_close = _pick_col(df, ["close", "c"])
    col_volume = _pick_col(df, ["volume", "vol", "v"])

    if not col_time or not col_high or not col_low or not col_close:
        raise RuntimeError(
            "required columns not found. need time/high/low/close (open is optional)."
        )

    out = pd.DataFrame()
    out["time"] = pd.to_datetime(df[col_time], errors="coerce")
    out["close"] = pd.to_numeric(df[col_close], errors="coerce")
    out["high"] = pd.to_numeric(df[col_high], errors="coerce")
    out["low"] = pd.to_numeric(df[col_low], errors="coerce")
    if col_open:
        out["open"] = pd.to_numeric(df[col_open], errors="coerce")
    else:
        out["open"] = out["close"]
    if col_volume:
        out["volume"] = pd.to_numeric(df[col_volume], errors="coerce")
    else:
        out["volume"] = 0.0

    out = out.dropna(subset=["time", "open", "high", "low", "close"]).copy()
    out = out.sort_values("time").reset_index(drop=True)
    if len(out) < 200:
        raise RuntimeError("not enough rows (need >= 200 bars)")
    return out


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


@dataclass
class SimCfg:
    fast: int = 20
    slow: int = 60
    channel_n: int = 48
    hold_bars: int = 12
    tp_pct: float = 0.35
    sl_pct: float = -0.25
    fee_bps: float = 1.0
    cooldown_bars: int = 1
    max_trades: int = 0


def _fee_total_pct(fee_bps: float) -> float:
    # 1 bps = 0.01%
    return 2.0 * float(fee_bps) * 0.01


def _ret_pct(side: str, entry: float, exitp: float) -> float:
    if side == "SELL":
        return (entry - exitp) / entry * 100.0
    return (exitp - entry) / entry * 100.0


def _score_from_gap_pct(gap_pct: float) -> float:
    # Smooth mapping: larger |gap| -> larger confidence, capped.
    x = abs(float(gap_pct))
    s = 0.5 + 0.45 * (1.0 - math.exp(-x * 14.0))
    return _clamp(s, 0.05, 0.99)


def _prepare_features(df: pd.DataFrame, cfg: SimCfg) -> pd.DataFrame:
    out = df.copy()
    out["sma_fast"] = out["close"].rolling(cfg.fast, min_periods=cfg.fast).mean()
    out["sma_slow"] = out["close"].rolling(cfg.slow, min_periods=cfg.slow).mean()
    out["ma_gap_pct"] = ((out["sma_fast"] - out["sma_slow"]) / out["sma_slow"]) * 100.0
    out["ma_slope_pct_per_step"] = out["sma_slow"].pct_change() * 100.0
    out["ret1"] = out["close"].pct_change()
    out["volatility_pct"] = out["ret1"].rolling(20, min_periods=20).std() * 100.0
    out["ch_hi_prev"] = out["high"].rolling(cfg.channel_n, min_periods=cfg.channel_n).max().shift(1)
    out["ch_lo_prev"] = out["low"].rolling(cfg.channel_n, min_periods=cfg.channel_n).min().shift(1)
    out["channel_width_pct"] = ((out["ch_hi_prev"] - out["ch_lo_prev"]) / out["close"]) * 100.0
    out["spread_entry_pct"] = ((out["high"] - out["low"]) / out["close"]) * 100.0
    out["trendline_slope_pct_per_step"] = out["close"].rolling(20, min_periods=20).mean().pct_change() * 100.0

    denom = (out["ch_hi_prev"] - out["ch_lo_prev"]).replace(0, pd.NA)
    out["channel_pos"] = ((out["close"] - out["ch_lo_prev"]) / denom).clip(0.0, 1.0)
    return out


def _signal_sma_cross(row: pd.Series) -> Tuple[Optional[str], float]:
    gap = row.get("ma_gap_pct")
    if pd.isna(gap):
        return None, 0.0
    if float(gap) > 0:
        return "BUY", _score_from_gap_pct(float(gap))
    if float(gap) < 0:
        return "SELL", _score_from_gap_pct(float(gap))
    return None, 0.0


def _signal_channel_breakout(row: pd.Series) -> Tuple[Optional[str], float]:
    close = row.get("close")
    hi = row.get("ch_hi_prev")
    lo = row.get("ch_lo_prev")
    if pd.isna(close) or pd.isna(hi) or pd.isna(lo):
        return None, 0.0
    close_f = float(close)
    hi_f = float(hi)
    lo_f = float(lo)
    if close_f > hi_f and hi_f > 0:
        b = (close_f - hi_f) / hi_f * 100.0
        return "BUY", _score_from_gap_pct(b)
    if close_f < lo_f and lo_f > 0:
        b = (lo_f - close_f) / lo_f * 100.0
        return "SELL", _score_from_gap_pct(b)
    return None, 0.0


def _resolve_signal(strategy: str, row: pd.Series) -> Tuple[Optional[str], float]:
    is_contra = strategy.endswith("_contra")
    base = strategy[:-7] if is_contra else strategy
    side: Optional[str] = None
    score: float = 0.0
    if base == "sma_cross":
        side, score = _signal_sma_cross(row)
    elif base == "channel_breakout":
        side, score = _signal_channel_breakout(row)
    if is_contra and side:
        side = "SELL" if side == "BUY" else "BUY"
    if side:
        return side, score
    return None, 0.0


def simulate_strategy(df: pd.DataFrame, strategy: str, cfg: SimCfg) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    fee_total_pct = _fee_total_pct(cfg.fee_bps)

    warmup = max(cfg.slow + 2, cfg.channel_n + 2, 50)
    pos: Optional[Dict[str, Any]] = None
    cooldown_until = -1
    seq = 0

    for i in range(warmup, len(df) - 1):
        row = df.iloc[i]

        if pos is not None:
            entry = float(pos["entry_price"])
            side = str(pos["side"])
            tp_price = entry * (1.0 + (cfg.tp_pct / 100.0)) if side == "BUY" else entry * (1.0 - (cfg.tp_pct / 100.0))
            sl_price = entry * (1.0 + (cfg.sl_pct / 100.0)) if side == "BUY" else entry * (1.0 - (cfg.sl_pct / 100.0))

            hi = float(row["high"])
            lo = float(row["low"])
            close = float(row["close"])
            t_exit = pd.Timestamp(row["time"]).to_pydatetime()

            fav_now = ((hi - entry) / entry * 100.0) if side == "BUY" else ((entry - lo) / entry * 100.0)
            pos["best_fav"] = max(float(pos.get("best_fav", 0.0)), float(fav_now))

            tp_hit = (hi >= tp_price) if side == "BUY" else (lo <= tp_price)
            sl_hit = (lo <= sl_price) if side == "BUY" else (hi >= sl_price)
            timeout_hit = (i - int(pos["entry_idx"])) >= cfg.hold_bars

            exit_price = close
            outcome = "TIMEOUT"
            result = "PAPER_EXIT_TIMEOUT"
            if sl_hit:
                exit_price = sl_price
                outcome = "SL"
                result = "PAPER_EXIT_SL"
            elif tp_hit:
                exit_price = tp_price
                outcome = "TP"
                result = "PAPER_EXIT_TP"
            elif timeout_hit:
                exit_price = close
                outcome = "TIMEOUT"
                result = "PAPER_EXIT_TIMEOUT"
            else:
                continue

            gross = _ret_pct(side, entry, float(exit_price))
            net = float(gross) - float(fee_total_pct)
            hold_min = max(0, int((t_exit - pos["entry_time"]).total_seconds() // 60))

            seq += 1
            pos_id = f"BT-{strategy.upper()}-{pos['entry_time'].strftime('%Y%m%d%H%M%S')}-{side}-{seq:05d}"
            records.append(
                {
                    "time": t_exit.strftime("%Y-%m-%d %H:%M:%S"),
                    "pos_id": pos_id,
                    "side": side,
                    "entry_time": pos["entry_time"].strftime("%Y-%m-%d %H:%M:%S"),
                    "exit_time": t_exit.strftime("%Y-%m-%d %H:%M:%S"),
                    "hold_min": hold_min,
                    "entry_price": round(entry, 6),
                    "exit_price": round(float(exit_price), 6),
                    "ret_pct": round(float(net), 6),
                    "outcome": outcome,
                    "result": result,
                    "ai_score": round(float(pos["ai_score"]), 6),
                    "ai_score_extend": round(float(pos["ai_score"]), 6),
                    "spread_entry_pct": round(float(pos.get("spread_entry_pct", 0.0)), 6),
                    "ma_gap_pct": round(float(pos.get("ma_gap_pct", 0.0)), 6),
                    "ma_slope_pct_per_step": round(float(pos.get("ma_slope_pct_per_step", 0.0)), 6),
                    "volatility_pct": round(float(pos.get("volatility_pct", 0.0)), 6),
                    "trendline_slope_pct_per_step": round(float(pos.get("trendline_slope_pct_per_step", 0.0)), 6),
                    "channel_pos": round(float(pos.get("channel_pos", 0.5)), 6),
                    "channel_width_pct": round(float(pos.get("channel_width_pct", 0.0)), 6),
                    "trend": "UP" if side == "BUY" else "DOWN",
                    "signal": f"{strategy.upper()}_{side}",
                    "best_fav": round(float(pos.get("best_fav", 0.0)), 6),
                    "extend_count": 0,
                    "exec_mode": "BACKTEST",
                    "stage": strategy.upper(),
                }
            )
            pos = None
            cooldown_until = i + max(0, int(cfg.cooldown_bars))
            if cfg.max_trades > 0 and len(records) >= cfg.max_trades:
                break

        if pos is not None:
            continue
        if i < cooldown_until:
            continue

        side, ai_score = _resolve_signal(strategy, row)
        if not side:
            continue
        entry_idx = i + 1
        if entry_idx >= len(df):
            break
        next_row = df.iloc[entry_idx]
        entry_price = float(next_row["open"])
        if entry_price <= 0:
            continue
        pos = {
            "side": side,
            "entry_idx": int(entry_idx),
            "entry_price": float(entry_price),
            "entry_time": pd.Timestamp(next_row["time"]).to_pydatetime(),
            "ai_score": float(ai_score),
            "best_fav": 0.0,
            "spread_entry_pct": float(row.get("spread_entry_pct") or 0.0),
            "ma_gap_pct": float(row.get("ma_gap_pct") or 0.0),
            "ma_slope_pct_per_step": float(row.get("ma_slope_pct_per_step") or 0.0),
            "volatility_pct": float(row.get("volatility_pct") or 0.0),
            "trendline_slope_pct_per_step": float(row.get("trendline_slope_pct_per_step") or 0.0),
            "channel_pos": float(row.get("channel_pos") or 0.5),
            "channel_width_pct": float(row.get("channel_width_pct") or 0.0),
        }

    return records


def _normalize_output_rows(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=AI_TRAIN_FIELDS)
    df = pd.DataFrame(rows)
    for c in AI_TRAIN_FIELDS:
        if c not in df.columns:
            df[c] = ""
    return df[AI_TRAIN_FIELDS].copy()


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _ret_stats(df: pd.DataFrame) -> Dict[str, float]:
    if df.empty:
        return {
            "n": 0,
            "win_rate": 0.0,
            "expectancy": 0.0,
            "pf": 0.0,
            "ret_sum": 0.0,
        }
    r = pd.to_numeric(df.get("ret_pct"), errors="coerce")
    r = r[r.notna()]
    if r.empty:
        return {
            "n": 0,
            "win_rate": 0.0,
            "expectancy": 0.0,
            "pf": 0.0,
            "ret_sum": 0.0,
        }
    pos = float(r[r > 0].sum())
    neg = float(abs(r[r < 0].sum()))
    pf = (pos / neg) if neg > 0 else (9.9 if pos > 0 else 0.0)
    return {
        "n": int(len(r)),
        "win_rate": float((r > 0).mean() * 100.0),
        "expectancy": float(r.mean()),
        "pf": float(pf),
        "ret_sum": float(r.sum()),
    }


def _hour_mask_jst(entry_time_series: pd.Series, mode: str) -> pd.Series:
    dt = pd.to_datetime(entry_time_series, errors="coerce")
    h = (dt + pd.Timedelta(hours=9)).dt.hour
    live = (h >= 10) & (h < 17) & (h != 13)
    if mode == "live_jst":
        return live.fillna(False)
    if mode == "off_live_jst":
        return (~live).fillna(False)
    return pd.Series([True] * len(entry_time_series), index=entry_time_series.index)


def _stage_groups(stages: List[str]) -> List[Tuple[str, List[str]]]:
    uniq = sorted({str(s).strip().upper() for s in stages if str(s).strip()})
    out: List[Tuple[str, List[str]]] = []
    if not uniq:
        return [("all", [])]
    out.append(("all", uniq))
    trend = [s for s in uniq if ("CONTRA" not in s)]
    contra = [s for s in uniq if ("CONTRA" in s)]
    if trend:
        out.append(("trend_only", trend))
    if contra:
        out.append(("contra_only", contra))
    sma = [s for s in uniq if ("SMA_CROSS" in s)]
    channel = [s for s in uniq if ("CHANNEL_BREAKOUT" in s)]
    if sma:
        out.append(("sma_only", sma))
    if channel:
        out.append(("channel_only", channel))
    return out


def _apply_filter_candidate(df: pd.DataFrame, cand: Dict[str, Any]) -> pd.DataFrame:
    out = df.copy()
    stages = cand.get("stages", [])
    if stages:
        out = out[out["stage"].astype(str).str.upper().isin(stages)]
    out = out[pd.to_numeric(out["ai_score"], errors="coerce") >= float(cand["min_ai_score"])]
    out = out[pd.to_numeric(out["spread_entry_pct"], errors="coerce") <= float(cand["max_spread_pct"])]
    out = out[pd.to_numeric(out["channel_width_pct"], errors="coerce") >= float(cand["min_channel_width_pct"])]
    hmask = _hour_mask_jst(out["entry_time"], str(cand["hour_mode"]))
    out = out[hmask]
    return out


def _optimize_filter_grid(df: pd.DataFrame, args: argparse.Namespace) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    if df.empty:
        return df, {"enabled": True, "best": None, "candidates": []}

    work = df.copy()
    for c in ("ai_score", "spread_entry_pct", "channel_width_pct", "ret_pct"):
        if c not in work.columns:
            work[c] = 0.0
        work[c] = pd.to_numeric(work[c], errors="coerce")
    work["stage"] = work.get("stage", "").astype(str).str.upper()
    work = work[work["ret_pct"].notna()].copy()
    if work.empty:
        return df, {"enabled": True, "best": None, "candidates": []}

    stage_groups = _stage_groups(list(work["stage"].dropna().unique()))
    score_grid = [0.50, 0.60, 0.70, 0.80]
    spread_grid = [0.20, 0.30, 0.50, 0.80]
    ch_width_grid = [0.00, 0.15, 0.30]
    hour_modes = ["all", "live_jst", "off_live_jst"]

    cands: List[Dict[str, Any]] = []
    for gname, gstages in stage_groups:
        base = work if not gstages else work[work["stage"].isin(gstages)]
        if base.empty:
            continue
        for min_ai_score, max_spread_pct, min_channel_width_pct, hour_mode in product(
            score_grid,
            spread_grid,
            ch_width_grid,
            hour_modes,
        ):
            cand = {
                "group": gname,
                "stages": gstages,
                "min_ai_score": float(min_ai_score),
                "max_spread_pct": float(max_spread_pct),
                "min_channel_width_pct": float(min_channel_width_pct),
                "hour_mode": str(hour_mode),
            }
            sub = _apply_filter_candidate(base, cand)
            st = _ret_stats(sub)
            if st["n"] < int(args.opt_min_trades):
                continue
            passed = (st["pf"] >= float(args.opt_target_pf)) and (st["expectancy"] >= float(args.opt_target_exp))
            rec = dict(cand)
            rec.update(
                {
                    "n": int(st["n"]),
                    "pf": float(st["pf"]),
                    "expectancy": float(st["expectancy"]),
                    "win_rate": float(st["win_rate"]),
                    "ret_sum": float(st["ret_sum"]),
                    "passed": bool(passed),
                }
            )
            cands.append(rec)

    cands = sorted(
        cands,
        key=lambda x: (
            1 if bool(x.get("passed")) else 0,
            _safe_float(x.get("pf"), 0.0),
            _safe_float(x.get("expectancy"), -999.0),
            int(x.get("n", 0)),
        ),
        reverse=True,
    )
    topk = cands[: max(1, int(args.opt_topk))]
    if not cands:
        print("[OPT] no candidate met opt_min_trades")
        return df, {"enabled": True, "best": None, "candidates": []}

    best = cands[0]
    for i, c in enumerate(topk, start=1):
        print(
            "[OPT] rank={} pass={} pf={:.4f} exp={:.6f} n={} wr={:.2f}% group={} hour={} ai>={:.2f} spread<={:.2f} chw>={:.2f}".format(
                i,
                c["passed"],
                c["pf"],
                c["expectancy"],
                c["n"],
                c["win_rate"],
                c["group"],
                c["hour_mode"],
                c["min_ai_score"],
                c["max_spread_pct"],
                c["min_channel_width_pct"],
            )
        )

    if bool(best.get("passed")) or bool(args.opt_apply_best_on_fail):
        filtered = _apply_filter_candidate(work, best)
        print(
            "[OPT] apply candidate pass={} n={} pf={:.4f} exp={:.6f}".format(
                best["passed"],
                best["n"],
                best["pf"],
                best["expectancy"],
            )
        )
        return filtered, {"enabled": True, "best": best, "candidates": topk}

    print("[OPT] best candidate did not pass target; keep original rows (safe default).")
    return df, {"enabled": True, "best": best, "candidates": topk}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Create synthetic ai_training_log from OHLCV csv.")
    ap.add_argument("--ohlcv", required=True, help="input OHLCV csv path (time/open/high/low/close)")
    ap.add_argument(
        "--out",
        default="../logs/backtest/ai_training_log_backtest.csv",
        help="output csv path (default: ../logs/backtest/ai_training_log_backtest.csv)",
    )
    ap.add_argument(
        "--strategy",
        default="all",
        help=(
            "all | all_contra | all_plus | "
            "sma_cross | channel_breakout | sma_cross_contra | channel_breakout_contra | comma-separated list"
        ),
    )
    ap.add_argument("--fast", type=int, default=20)
    ap.add_argument("--slow", type=int, default=60)
    ap.add_argument("--channel-n", type=int, default=48)
    ap.add_argument("--hold-bars", type=int, default=12)
    ap.add_argument("--tp-pct", type=float, default=0.35)
    ap.add_argument("--sl-pct", type=float, default=-0.25)
    ap.add_argument("--fee-bps", type=float, default=1.0)
    ap.add_argument("--cooldown-bars", type=int, default=1)
    ap.add_argument("--max-trades", type=int, default=0, help="0 means no cap")
    ap.add_argument("--append", action="store_true", help="append to existing output file")
    ap.add_argument("--optimize-filters", action="store_true", help="grid-search filter candidates and keep best")
    ap.add_argument("--opt-target-pf", type=float, default=1.05, help="target PF for optimizer pass")
    ap.add_argument("--opt-target-exp", type=float, default=0.0, help="target expectancy(%%) for optimizer pass")
    ap.add_argument("--opt-min-trades", type=int, default=500, help="minimum trades per candidate")
    ap.add_argument("--opt-topk", type=int, default=10, help="print top-k optimizer candidates")
    ap.add_argument("--opt-apply-best-on-fail", action="store_true", help="apply best candidate even if target not met")
    ap.add_argument("--opt-report", default="", help="optional json report path for optimizer result")
    return ap.parse_args()


def _resolve_strategies(raw: str) -> List[str]:
    s = (raw or "all").strip().lower()
    if s == "all":
        return ["sma_cross", "channel_breakout"]
    if s == "all_contra":
        return ["sma_cross_contra", "channel_breakout_contra"]
    if s in ("all_plus", "all_plus_contra"):
        return ["sma_cross", "channel_breakout", "sma_cross_contra", "channel_breakout_contra"]
    out: List[str] = []
    for p in [x.strip().lower() for x in s.split(",") if x.strip()]:
        if p in ("sma_cross", "channel_breakout", "sma_cross_contra", "channel_breakout_contra"):
            out.append(p)
    return sorted(set(out))


def main() -> int:
    args = parse_args()
    strategies = _resolve_strategies(args.strategy)
    if not strategies:
        print("[ERROR] no valid strategy selected")
        return 2

    cfg = SimCfg(
        fast=max(2, int(args.fast)),
        slow=max(int(args.fast) + 1, int(args.slow)),
        channel_n=max(5, int(args.channel_n)),
        hold_bars=max(1, int(args.hold_bars)),
        tp_pct=max(0.01, float(args.tp_pct)),
        sl_pct=min(-0.01, float(args.sl_pct)),
        fee_bps=max(0.0, float(args.fee_bps)),
        cooldown_bars=max(0, int(args.cooldown_bars)),
        max_trades=max(0, int(args.max_trades)),
    )

    src = Path(args.ohlcv).expanduser()
    out = Path(args.out).expanduser()
    if not src.exists():
        print(f"[ERROR] input not found: {src}")
        return 2

    try:
        base = load_ohlcv(src)
        feat = _prepare_features(base, cfg)
    except Exception as e:
        print(f"[ERROR] failed to load/prepare OHLCV: {e}")
        return 2

    all_rows: List[Dict[str, Any]] = []
    for stg in strategies:
        rows = simulate_strategy(feat, stg, cfg)
        all_rows.extend(rows)
        if rows:
            wins = sum(1 for r in rows if float(r.get("ret_pct", 0.0)) > 0.0)
            wr = (wins / len(rows)) * 100.0
            ret_sum = sum(float(r.get("ret_pct", 0.0)) for r in rows)
            print(f"[OK] {stg}: trades={len(rows)} win_rate={wr:.1f}% ret_sum={ret_sum:.3f}%")
        else:
            print(f"[WARN] {stg}: no trades generated")

    if not all_rows:
        print("[WARN] no rows generated")
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    out_df = _normalize_output_rows(all_rows)
    out_df = out_df.sort_values("time").reset_index(drop=True)
    opt_meta: Dict[str, Any] = {}
    if args.optimize_filters:
        out_df, opt_meta = _optimize_filter_grid(out_df, args)
        out_df = _normalize_output_rows(out_df.to_dict(orient="records"))
        out_df = out_df.sort_values("time").reset_index(drop=True)
        if args.opt_report:
            try:
                rp = Path(args.opt_report).expanduser()
                rp.parent.mkdir(parents=True, exist_ok=True)
                rp.write_text(json.dumps(opt_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"[OPT] report saved: {rp}")
            except Exception as e:
                print(f"[WARN] failed to save opt report: {e}")

    if args.append and out.exists():
        try:
            cur = pd.read_csv(out)
            for c in AI_TRAIN_FIELDS:
                if c not in cur.columns:
                    cur[c] = ""
            merged = pd.concat([cur[AI_TRAIN_FIELDS], out_df], ignore_index=True)
            merged = merged.drop_duplicates(subset=["pos_id"], keep="last")
            merged = merged.sort_values("time").reset_index(drop=True)
            merged.to_csv(out, index=False)
            print(f"[OK] appended: {out} rows={len(merged)}")
            return 0
        except Exception as e:
            print(f"[ERROR] append failed: {e}")
            return 2

    out_df.to_csv(out, index=False)
    print(f"[OK] wrote: {out} rows={len(out_df)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
