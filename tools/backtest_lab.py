#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import bot


DEFAULT_LOGS_DIR = ROOT_DIR.parent / "logs"
LOG_RE = re.compile(r"^trade_log_(\d{8})\.csv$")


def _safe_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if v is None:
            return default
        s = str(v).strip()
        if not s or s.lower() in {"nan", "none"}:
            return default
        return float(s)
    except Exception:
        return default


def _parse_time(v: Any) -> Optional[datetime]:
    text = str(v or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass
    try:
        # pandas is intentionally avoided here; keep this tool lightweight.
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _floor_time(ts: datetime, timeframe_min: int) -> datetime:
    n = max(1, int(timeframe_min))
    minute = (int(ts.minute) // n) * n
    return ts.replace(minute=minute, second=0, microsecond=0)


def list_days(logs_dir: Path = DEFAULT_LOGS_DIR) -> List[str]:
    if not logs_dir.exists():
        return []
    days: List[str] = []
    for path in logs_dir.glob("trade_log_*.csv"):
        m = LOG_RE.match(path.name)
        if m:
            days.append(m.group(1))
    return sorted(set(days))


def resolve_log_paths(logs_dir: Path, days: Iterable[str]) -> List[Path]:
    out: List[Path] = []
    for day8 in days:
        clean = str(day8 or "").strip()
        if not clean:
            continue
        path = logs_dir / f"trade_log_{clean}.csv"
        if path.exists():
            out.append(path)
    return out


def read_price_points(paths: Iterable[Path]) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    for path in paths:
        try:
            with path.open(newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    ts = _parse_time(row.get("time"))
                    ltp = _safe_float(row.get("ltp"))
                    if ts is None or ltp is None:
                        continue
                    points.append(
                        {
                            "time": ts,
                            "price": float(ltp),
                            "result": str(row.get("result", "") or ""),
                            "note": str(row.get("note", "") or ""),
                        }
                    )
        except Exception:
            continue
    points.sort(key=lambda x: x["time"])
    dedup: Dict[datetime, Dict[str, Any]] = {}
    for p in points:
        dedup[p["time"]] = p
    return [dedup[k] for k in sorted(dedup)]


def build_ohlc(points: List[Dict[str, Any]], *, timeframe_min: int = 5) -> List[Dict[str, Any]]:
    buckets: Dict[datetime, List[float]] = {}
    for p in points:
        ts = p.get("time")
        price = _safe_float(p.get("price"))
        if not isinstance(ts, datetime) or price is None:
            continue
        key = _floor_time(ts, timeframe_min)
        buckets.setdefault(key, []).append(float(price))
    candles: List[Dict[str, Any]] = []
    for key in sorted(buckets):
        prices = buckets[key]
        if not prices:
            continue
        candles.append(
            {
                "start": key.strftime("%Y-%m-%d %H:%M:%S"),
                "open": prices[0],
                "high": max(prices),
                "low": min(prices),
                "close": prices[-1],
                "ticks": len(prices),
            }
        )
    return candles


def _sma(vals: List[float], n: int) -> Optional[float]:
    n = int(n)
    if n <= 0 or len(vals) < n:
        return None
    return sum(vals[-n:]) / float(n)


def _sma_prev(vals: List[float], n: int) -> Optional[float]:
    n = int(n)
    if n <= 0 or len(vals) < n + 1:
        return None
    return sum(vals[-n - 1:-1]) / float(n)


@dataclass
class BacktestParams:
    strategy: str = "phase_follow"
    timeframe_min: int = 5
    fast_n: int = 5
    slow_n: int = 20
    tp_pct: float = 0.15
    sl_pct: float = 0.12
    max_hold_bars: int = 12
    require_break: bool = False
    require_quality_ok: bool = True
    one_position_only: bool = True


def _signal_ma_cross(candles: List[Dict[str, Any]], p: BacktestParams) -> Tuple[str, str]:
    closes = [float(x["close"]) for x in candles]
    fast = _sma(closes, p.fast_n)
    slow = _sma(closes, p.slow_n)
    fast_prev = _sma_prev(closes, p.fast_n)
    slow_prev = _sma_prev(closes, p.slow_n)
    if None in (fast, slow, fast_prev, slow_prev):
        return "", "ma_cross=NA"
    if float(fast_prev) <= float(slow_prev) and float(fast) > float(slow):
        return "BUY", "ma_cross=golden"
    if float(fast_prev) >= float(slow_prev) and float(fast) < float(slow):
        return "SELL", "ma_cross=dead"
    return "", "ma_cross=none"


def _signal_phase_follow(candles: List[Dict[str, Any]], p: BacktestParams) -> Tuple[str, str]:
    closes = [float(x["close"]) for x in candles]
    cfg = bot.Cfg(
        fast_n=max(2, int(p.fast_n)),
        slow_n=max(int(p.fast_n) + 1, int(p.slow_n)),
        market_phase_lookback_n=max(5, int(p.slow_n)),
    )
    snap = bot.calc_market_phase_snapshot({"ltp_history": closes}, candles, price=closes[-1], cfg=cfg)
    phase = str(snap.get("phase", "UNKNOWN")).upper()
    up_break = bool(snap.get("up_break"))
    down_break = bool(snap.get("down_break"))
    reason = str(snap.get("phase_reason", ""))
    if phase == "C" and (up_break or not p.require_break):
        return "BUY", f"phase=C reason={reason} up_break={1 if up_break else 0}"
    if phase == "A" and (down_break or not p.require_break):
        return "SELL", f"phase=A reason={reason} down_break={1 if down_break else 0}"
    return "", f"phase={phase} reason={reason}"


def _signal_chart_pattern(candles: List[Dict[str, Any]], p: BacktestParams) -> Tuple[str, str]:
    cfg = bot.Cfg(
        chart_pattern_min_bar_ticks=2,
        chart_pattern_quality_lookback_bars=6,
        double_top_peak_tolerance_pct=0.30,
        double_bottom_trough_tolerance_pct=0.30,
    )
    snap = bot.calc_chart_pattern_snapshot(candles, cfg)
    name = str(snap.get("pattern_name", "NONE"))
    stage = str(snap.get("pattern_stage", "NONE"))
    bias = str(snap.get("pattern_bias", "NEUTRAL")).upper()
    quality = str(snap.get("pattern_quality", "NA")).upper()
    confirmed = bool(snap.get("pattern_confirmed"))
    if p.require_quality_ok and quality != "OK":
        return "", f"pattern={name} stage={stage} quality={quality}"
    if confirmed and bias == "BUY":
        return "BUY", f"pattern={name} confirmed=1 quality={quality}"
    if confirmed and bias == "SELL":
        return "SELL", f"pattern={name} confirmed=1 quality={quality}"
    return "", f"pattern={name} stage={stage} quality={quality}"


def _signal_aiba(candles: List[Dict[str, Any]], p: BacktestParams) -> Tuple[str, str]:
    closes = [float(x["close"]) for x in candles]
    cfg = bot.Cfg(
        aiba_ma_short_n=max(2, int(p.fast_n)),
        aiba_ma_mid_n=max(int(p.fast_n) + 1, int(p.slow_n)),
        aiba_ma_long_n=max(int(p.slow_n) + 5, int(p.slow_n) * 3),
        aiba_try_fail_min_count=2,
    )
    snap = bot.calc_aiba_style_snapshot({"ltp_history": closes}, candles, price=closes[-1], cfg=cfg)
    cross = str(snap.get("cross_type", "NONE")).upper()
    ppp = str(snap.get("ppp_flag", "NONE")).upper()
    try_fail = bool(snap.get("try_fail_flag"))
    if cross == "KUCHIBASHI" or ppp == "PPP":
        return "BUY", f"aiba_cross={cross} aiba_ppp={ppp}"
    if cross == "REV_KUCHIBASHI" or ppp == "REV_PPP" or try_fail:
        return "SELL", f"aiba_cross={cross} aiba_ppp={ppp} try_fail={1 if try_fail else 0}"
    return "", f"aiba_cross={cross} aiba_ppp={ppp} try_fail={1 if try_fail else 0}"


def build_signal(candles: List[Dict[str, Any]], p: BacktestParams) -> Tuple[str, str]:
    if len(candles) < max(3, min(int(p.slow_n), 8)):
        return "", "warmup"
    strategy = str(p.strategy or "").strip().lower()
    if strategy == "ma_cross":
        return _signal_ma_cross(candles, p)
    if strategy == "chart_pattern":
        return _signal_chart_pattern(candles, p)
    if strategy == "aiba_style":
        return _signal_aiba(candles, p)
    if strategy == "combo_phase_pattern":
        phase_side, phase_note = _signal_phase_follow(candles, p)
        pat_side, pat_note = _signal_chart_pattern(candles, p)
        if phase_side and pat_side and phase_side == pat_side:
            return phase_side, f"{phase_note} {pat_note}"
        return "", f"{phase_note} {pat_note}"
    return _signal_phase_follow(candles, p)


def _exit_for_candle(pos: Dict[str, Any], candle: Dict[str, Any], p: BacktestParams, index: int) -> Tuple[bool, float, str]:
    side = str(pos.get("side", "")).upper()
    entry = float(pos.get("entry_price"))
    high = float(candle["high"])
    low = float(candle["low"])
    close = float(candle["close"])
    hold = int(index) - int(pos.get("entry_index", index))
    tp = max(0.0, float(p.tp_pct)) / 100.0
    sl = max(0.0, float(p.sl_pct)) / 100.0
    if side == "BUY":
        tp_price = entry * (1.0 + tp)
        sl_price = entry * (1.0 - sl)
        # Conservative same-bar rule: SL first when both are touched.
        if low <= sl_price:
            return True, sl_price, "SL"
        if high >= tp_price:
            return True, tp_price, "TP"
    else:
        tp_price = entry * (1.0 - tp)
        sl_price = entry * (1.0 + sl)
        if high >= sl_price:
            return True, sl_price, "SL"
        if low <= tp_price:
            return True, tp_price, "TP"
    if hold >= max(1, int(p.max_hold_bars)):
        return True, close, "TIMEOUT"
    return False, close, ""


def run_backtest(candles: List[Dict[str, Any]], p: BacktestParams) -> Dict[str, Any]:
    trades: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    pos: Optional[Dict[str, Any]] = None
    for i, candle in enumerate(candles):
        close = float(candle["close"])
        ts = str(candle.get("start", ""))
        if pos is not None:
            do_exit, exit_price, reason = _exit_for_candle(pos, candle, p, i)
            if do_exit:
                side = str(pos["side"])
                entry = float(pos["entry_price"])
                if side == "BUY":
                    ret_pct = (float(exit_price) - entry) / entry * 100.0
                else:
                    ret_pct = (entry - float(exit_price)) / entry * 100.0
                trade = {
                    "entry_time": pos["entry_time"],
                    "exit_time": ts,
                    "side": side,
                    "entry_price": round(entry, 6),
                    "exit_price": round(float(exit_price), 6),
                    "ret_pct": round(ret_pct, 6),
                    "exit_reason": reason,
                    "hold_bars": int(i) - int(pos["entry_index"]),
                    "entry_note": pos.get("entry_note", ""),
                }
                trades.append(trade)
                events.append({"time": ts, "event": f"EXIT_{reason}", "side": side, "price": round(float(exit_price), 6), "ret_pct": round(ret_pct, 6)})
                pos = None

        if pos is None:
            side, note = build_signal(candles[: i + 1], p)
            if side in {"BUY", "SELL"}:
                pos = {
                    "side": side,
                    "entry_price": close,
                    "entry_time": ts,
                    "entry_index": i,
                    "entry_note": note,
                }
                events.append({"time": ts, "event": "ENTRY", "side": side, "price": round(close, 6), "note": note})

    if pos is not None and candles:
        last = candles[-1]
        side = str(pos["side"])
        entry = float(pos["entry_price"])
        exit_price = float(last["close"])
        ret_pct = (exit_price - entry) / entry * 100.0 if side == "BUY" else (entry - exit_price) / entry * 100.0
        trades.append(
            {
                "entry_time": pos["entry_time"],
                "exit_time": str(last.get("start", "")),
                "side": side,
                "entry_price": round(entry, 6),
                "exit_price": round(exit_price, 6),
                "ret_pct": round(ret_pct, 6),
                "exit_reason": "EOD",
                "hold_bars": max(0, len(candles) - 1 - int(pos["entry_index"])),
                "entry_note": pos.get("entry_note", ""),
            }
        )
    return {
        "params": p.__dict__,
        "candles": candles,
        "events": events,
        "trades": trades,
        "metrics": summarize_trades(trades),
    }


def summarize_trades(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(trades)
    wins = [x for x in trades if float(x.get("ret_pct", 0.0)) > 0]
    losses = [x for x in trades if float(x.get("ret_pct", 0.0)) < 0]
    ret_sum = sum(float(x.get("ret_pct", 0.0)) for x in trades)
    gross_win = sum(float(x.get("ret_pct", 0.0)) for x in wins)
    gross_loss = sum(float(x.get("ret_pct", 0.0)) for x in losses)
    pf = (gross_win / abs(gross_loss)) if gross_loss < 0 else (8.0 if gross_win > 0 else 0.0)
    return {
        "trade_n": n,
        "win_n": len(wins),
        "loss_n": len(losses),
        "win_rate_pct": round((len(wins) / n * 100.0) if n else 0.0, 4),
        "ret_sum_pct": round(ret_sum, 6),
        "avg_ret_pct": round((ret_sum / n) if n else 0.0, 6),
        "profit_factor": round(pf, 6),
        "tp_n": sum(1 for x in trades if x.get("exit_reason") == "TP"),
        "sl_n": sum(1 for x in trades if x.get("exit_reason") == "SL"),
        "timeout_n": sum(1 for x in trades if x.get("exit_reason") == "TIMEOUT"),
        "eod_n": sum(1 for x in trades if x.get("exit_reason") == "EOD"),
    }


def build_from_logs(logs_dir: Path, days: Iterable[str], params: BacktestParams) -> Dict[str, Any]:
    paths = resolve_log_paths(logs_dir, days)
    points = read_price_points(paths)
    candles = build_ohlc(points, timeframe_min=int(params.timeframe_min))
    result = run_backtest(candles, params)
    result["source"] = {
        "logs_dir": str(logs_dir),
        "days": [str(x) for x in days],
        "log_files": [str(x) for x in paths],
        "price_points": len(points),
        "candle_n": len(candles),
    }
    return result


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Local historical chart backtest lab.")
    p.add_argument("--logs-dir", default=str(DEFAULT_LOGS_DIR))
    p.add_argument("--day", action="append", dest="days", default=[])
    p.add_argument("--strategy", default="phase_follow", choices=["phase_follow", "ma_cross", "chart_pattern", "aiba_style", "combo_phase_pattern"])
    p.add_argument("--timeframe-min", type=int, default=5)
    p.add_argument("--fast-n", type=int, default=5)
    p.add_argument("--slow-n", type=int, default=20)
    p.add_argument("--tp-pct", type=float, default=0.15)
    p.add_argument("--sl-pct", type=float, default=0.12)
    p.add_argument("--max-hold-bars", type=int, default=12)
    p.add_argument("--require-break", action="store_true")
    p.add_argument("--allow-thin-pattern", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    days = list(args.days or [])
    if not days:
        days = list_days(Path(args.logs_dir))[-5:]
    params = BacktestParams(
        strategy=str(args.strategy),
        timeframe_min=int(args.timeframe_min),
        fast_n=int(args.fast_n),
        slow_n=int(args.slow_n),
        tp_pct=float(args.tp_pct),
        sl_pct=float(args.sl_pct),
        max_hold_bars=int(args.max_hold_bars),
        require_break=bool(args.require_break),
        require_quality_ok=not bool(args.allow_thin_pattern),
    )
    print(json.dumps(build_from_logs(Path(args.logs_dir), days, params), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
