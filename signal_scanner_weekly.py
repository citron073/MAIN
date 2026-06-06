#!/usr/bin/env python3
"""
Signal Scanner Weekly — SIGNAL_ONLY candidate extraction.

Scans FX majors and US stocks using technical analysis (MA5/MA20/RSI/ATR),
evaluates risk/reward based on ¥100,000 capital, and produces a
SIGNAL_ONLY report for manual review.

IMPORTANT:
  - This script does NOT place any orders.
  - No placeOrder / buy / sell calls are made anywhere in this file.
  - Output is SIGNAL_ONLY for human review only.

Data sources (in priority order):
  1. IBKR Paper API localhost:8812/snapshot  (for live bid/ask when available)
  2. yfinance (OHLCV history, always available — delayed data)

Result convention:
  OBSERVE_OK   — candidates found, signal_only records saved
  OBSERVE_OK   — no actionable candidates (below threshold)
  ERROR        — data fetch failed

Usage:
    python3 signal_scanner_weekly.py               # full scan
    python3 signal_scanner_weekly.py --dry-run     # print, don't notify
    python3 signal_scanner_weekly.py --fx-only
    python3 signal_scanner_weekly.py --stocks-only
    python3 signal_scanner_weekly.py --interval 1d
"""
from __future__ import annotations

import csv
import json
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
REVIEW_OUT = ROOT / "review_out"
SECRETS_FILE = ROOT / ".streamlit" / "secrets.toml"
PAPER_API_URL = "http://localhost:8812"
FEEDBACK_JSON = REVIEW_OUT / "signal_scanner_feedback_latest.json"

# ── Capital & risk parameters ─────────────────────────────────────────────────
CAPITAL_JPY = 100_000
TARGET_PROFIT_JPY = 10_000        # 10% target (informational)
MAX_RISK_PER_TRADE_JPY = 1_000   # ¥1,000 max per trade
MAX_DAILY_LOSS_JPY = 2_000
MAX_WEEKLY_LOSS_JPY = 5_000
MIN_RISK_REWARD = 1.5
MAX_SPREAD_PCT = 0.003            # 0.3% max spread
GOAL_REFERENCE_PCT = 10.0

# ── Instruments ───────────────────────────────────────────────────────────────
FX_PAIRS = ["USDJPY", "EURUSD", "GBPJPY", "EURJPY", "GBPUSD"]
FX_YF_TICKERS = {
    "USDJPY": "USDJPY=X",
    "EURUSD": "EURUSD=X",
    "GBPJPY": "GBPJPY=X",
    "EURJPY": "EURJPY=X",
    "GBPUSD": "GBPUSD=X",
}
STOCK_SYMBOLS = ["AAPL", "NVDA", "TSLA", "AMZN", "META", "AMD", "MSFT", "QQQ"]

# FX pairs quoted in JPY directly
FX_JPY_QUOTED = {"USDJPY", "GBPJPY", "EURJPY"}


def _now_jst() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


def _now_jst_str() -> str:
    return _now_jst().strftime("%Y-%m-%d %H:%M:%S")


def _day8() -> str:
    return _now_jst().strftime("%Y%m%d")


def _signal_only_note(market_type: str, symbol: str, signal: str, reason: str) -> str:
    compact_reason = " ".join(str(reason or "").split())
    return (
        f"SIGNAL_ONLY_CANDIDATE market={market_type} symbol={symbol} "
        f"side={signal} reason={compact_reason}"
    )


def _load_feedback() -> Dict[str, Any]:
    if not FEEDBACK_JSON.exists():
        return {}
    try:
        return json.loads(FEEDBACK_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _feedback_adjustment(
    symbol: str,
    market_type: str,
    signal: str,
    feedback: Optional[Dict[str, Any]],
) -> Tuple[int, str]:
    if not isinstance(feedback, dict) or not feedback:
        return 0, ""

    delta = 0
    notes: List[str] = []

    by_symbol = feedback.get("by_symbol") if isinstance(feedback.get("by_symbol"), dict) else {}
    sym = by_symbol.get(symbol) if isinstance(by_symbol, dict) else None
    if isinstance(sym, dict) and int(sym.get("closed_count") or 0) >= 3:
        sym_n = int(sym.get("closed_count") or 0)
        wr = float(sym.get("win_rate_pct") or 0)
        if wr >= 60:
            delta += 8
            notes.append(f"symbol:+8 (WR={wr:.1f}%, n={sym_n})")
        elif wr <= 40:
            delta -= 8
            notes.append(f"symbol:-8 (WR={wr:.1f}%, n={sym_n})")

    by_side = feedback.get("by_side") if isinstance(feedback.get("by_side"), dict) else {}
    side = by_side.get(signal) if isinstance(by_side, dict) else None
    if isinstance(side, dict) and int(side.get("closed_count") or 0) >= 5:
        side_n = int(side.get("closed_count") or 0)
        wr = float(side.get("win_rate_pct") or 0)
        if wr >= 55:
            delta += 4
            notes.append(f"side:+4 (WR={wr:.1f}%, n={side_n})")
        elif wr <= 40:
            delta -= 4
            notes.append(f"side:-4 (WR={wr:.1f}%, n={side_n})")

    fx_pref = feedback.get("fx_priority") if isinstance(feedback.get("fx_priority"), dict) else {}
    pref_market = str(fx_pref.get("preferred_market") or "")
    market_adj = int(fx_pref.get("score_adjustment") or 0)
    if pref_market == market_type and market_adj:
        delta += abs(market_adj)
        notes.append(f"market:+{abs(market_adj)} (pref={pref_market})")
    elif pref_market and pref_market != "NEUTRAL" and pref_market != market_type and market_adj:
        delta -= abs(market_adj)
        notes.append(f"market:-{abs(market_adj)} (pref={pref_market})")

    delta = max(-15, min(15, delta))
    return delta, " / ".join(notes)


def _feedback_summary(feedback: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(feedback, dict) or not feedback:
        return {
            "closed_count": 0,
            "preferred_market": "NEUTRAL",
            "min_closed_required": 5,
            "reason": "feedback未生成",
            "score_adjustment": 0,
        }

    fx_pref = feedback.get("fx_priority") if isinstance(feedback.get("fx_priority"), dict) else {}
    return {
        "closed_count": int(feedback.get("closed_count") or 0),
        "preferred_market": str(fx_pref.get("preferred_market") or "NEUTRAL"),
        "min_closed_required": int(fx_pref.get("min_closed_required") or 5),
        "reason": str(fx_pref.get("reason") or ""),
        "score_adjustment": int(fx_pref.get("score_adjustment") or 0),
    }


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_ohlcv(yf_ticker: str, interval: str = "1h", period: str = "60d") -> Optional[Dict[str, Any]]:
    """Fetch OHLCV from yfinance. Returns dict with closes/highs/lows/volumes or None."""
    try:
        import yfinance as yf  # type: ignore
        df = yf.Ticker(yf_ticker).history(period=period, interval=interval)
        if df is None or len(df) < 22:
            return None
        return {
            "closes": [float(v) for v in df["Close"].values],
            "highs": [float(v) for v in df["High"].values],
            "lows": [float(v) for v in df["Low"].values],
            "volumes": [float(v) for v in df["Volume"].values],
            "n": len(df),
        }
    except Exception as exc:
        print(f"  [yfinance] {yf_ticker}: {exc}", file=sys.stderr)
        return None


def try_ibkr_snapshot() -> Optional[Dict[str, Any]]:
    """Try IBKR Paper API snapshot. Returns None if not available (graceful fallback)."""
    try:
        req = urllib.request.Request(f"{PAPER_API_URL}/snapshot", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def get_usdjpy_rate(ibkr: Optional[Dict[str, Any]]) -> float:
    """Extract USDJPY rate from IBKR snapshot, or fetch from yfinance."""
    if ibkr:
        fx = ibkr.get("fx_snapshot_USDJPY", {})
        rate = fx.get("market_price") or fx.get("last") or fx.get("bid") or fx.get("close")
        if rate and float(rate) > 0:
            return float(rate)
    ohlcv = fetch_ohlcv("USDJPY=X", interval="1d", period="5d")
    if ohlcv:
        return ohlcv["closes"][-1]
    return 150.0  # fallback estimate


def _get_ibkr_stock(ibkr: Optional[Dict[str, Any]], symbol: str) -> Optional[Dict[str, Any]]:
    if ibkr:
        return ibkr.get("stock_snapshots", {}).get(symbol)
    return None


# ── Technical indicators ──────────────────────────────────────────────────────

def _sma(values: List[float], n: int) -> float:
    return sum(values[-n:]) / n if len(values) >= n else sum(values) / len(values)


def _rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 2:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-period:]
    gains = [max(d, 0.0) for d in recent]
    losses = [abs(min(d, 0.0)) for d in recent]
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    if avg_l == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_g / avg_l)), 2)


def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Average True Range over last period bars."""
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(max(1, len(closes) - period), len(closes)):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


def compute_indicators(ohlcv: Dict[str, Any]) -> Dict[str, float]:
    closes = ohlcv["closes"]
    highs = ohlcv["highs"]
    lows = ohlcv["lows"]
    return {
        "ma5": round(_sma(closes, 5), 6),
        "ma20": round(_sma(closes, 20), 6),
        "rsi14": round(_rsi(closes), 2),
        "atr14": round(_atr(highs, lows, closes, 14), 6),
        "price": round(closes[-1], 6),
        "prev_close": round(closes[-2], 6) if len(closes) >= 2 else closes[-1],
    }


# ── Risk/reward calculation ───────────────────────────────────────────────────

def _calc_position(
    signal: str,
    entry: float,
    atr: float,
    fx_rate: float,
    is_jpy_quoted: bool,
    market_type: str,
) -> Dict[str, Any]:
    """
    Compute SL/TP/risk/reward/quantity for a candidate.
    All monetary output is in JPY.
    """
    if atr <= 0:
        return {}

    sl_distance = atr * 1.0
    tp_distance = atr * 2.0

    if signal == "BUY":
        sl_price = entry - sl_distance
        tp_price = entry + tp_distance
    else:  # SELL
        sl_price = entry + sl_distance
        tp_price = entry - tp_distance

    rr = tp_distance / sl_distance if sl_distance > 0 else 0

    # Convert risk per unit to JPY
    if market_type == "FX":
        if is_jpy_quoted:
            # e.g. USDJPY: 1 unit = 1 base currency, risk in JPY directly
            risk_per_unit_jpy = sl_distance
            profit_per_unit_jpy = tp_distance
        else:
            # e.g. EURUSD: 1 unit = 1 EUR, risk in USD → JPY
            risk_per_unit_jpy = sl_distance * fx_rate
            profit_per_unit_jpy = tp_distance * fx_rate
    else:
        # Stocks: price in USD
        risk_per_unit_jpy = sl_distance * fx_rate
        profit_per_unit_jpy = tp_distance * fx_rate

    # How many units fit within MAX_RISK_PER_TRADE_JPY?
    if risk_per_unit_jpy > 0:
        quantity = max(1, int(MAX_RISK_PER_TRADE_JPY / risk_per_unit_jpy))
    else:
        quantity = 1

    actual_risk_jpy = round(quantity * risk_per_unit_jpy, 0)
    actual_profit_jpy = round(quantity * profit_per_unit_jpy, 0)

    # Cap at max risk
    if actual_risk_jpy > MAX_RISK_PER_TRADE_JPY * 2:
        quantity = 1
        actual_risk_jpy = round(risk_per_unit_jpy, 0)
        actual_profit_jpy = round(profit_per_unit_jpy, 0)

    return {
        "entry_price": round(entry, 6),
        "sl_price": round(sl_price, 6),
        "tp_price": round(tp_price, 6),
        "risk_reward": round(rr, 2),
        "quantity_suggested": quantity,
        "risk_per_trade_jpy": int(actual_risk_jpy),
        "target_profit_jpy": int(actual_profit_jpy),
    }


# ── Candidate scoring ─────────────────────────────────────────────────────────

def _check_daily_alignment(yf_ticker: str, signal: str) -> Optional[bool]:
    """V: Return True if daily SMA5/SMA20 aligns with signal direction (bullish for BUY etc.)."""
    try:
        ohlcv = fetch_ohlcv(yf_ticker, interval="1d", period="30d")
        if ohlcv is None or len(ohlcv["closes"]) < 20:
            return None
        closes = ohlcv["closes"]
        ma5 = _sma(closes, 5)
        ma20 = _sma(closes, 20)
        if signal == "BUY":
            return ma5 > ma20
        else:
            return ma5 < ma20
    except Exception:
        return None


def _confidence(
    trend: str,
    signal: str,
    ind: Dict[str, float],
    rr: float,
    price_available: bool,
    daily_aligned: Optional[bool] = None,
) -> int:
    score = 0
    ma5, ma20, rsi = ind["ma5"], ind["ma20"], ind["rsi14"]
    gap_pct = abs(ma5 - ma20) / ma20 if ma20 > 0 else 0

    # Trend strength
    if gap_pct > 0.005:
        score += 20
    elif gap_pct > 0.002:
        score += 10

    # RSI zone
    if signal == "BUY" and rsi < 60:
        score += 20
    elif signal == "BUY" and rsi < 65:
        score += 10
    elif signal == "SELL" and rsi > 40:
        score += 20
    elif signal == "SELL" and rsi > 35:
        score += 10

    # Trend alignment
    if (signal == "BUY" and ma5 > ma20) or (signal == "SELL" and ma5 < ma20):
        score += 20

    # R:R
    if rr >= 2.0:
        score += 20
    elif rr >= 1.5:
        score += 10

    # Data quality
    if price_available:
        score += 20
    else:
        score += 5  # delayed data still usable

    # V: MTF alignment bonus (daily trend confirms 1h signal)
    if daily_aligned is True:
        score += 10

    return min(score, 100)


# ── Candidate analysis ────────────────────────────────────────────────────────

def analyze(
    symbol: str,
    market_type: str,
    yf_ticker: str,
    ibkr_snap: Optional[Dict[str, Any]],
    fx_rate: float,
    interval: str = "1h",
    feedback: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Analyze one symbol and return a candidate dict or None if not tradable.
    NO orders are placed here.
    """
    ohlcv = fetch_ohlcv(yf_ticker, interval=interval)
    if ohlcv is None:
        return {
            "symbol": symbol, "market_type": market_type,
            "result": "SKIP", "reason": "data_unavailable",
            "market_data_status": "NO_SUBSCRIPTION_OR_DELAYED_ONLY",
        }

    ind = compute_indicators(ohlcv)
    price = ind["price"]
    ma5, ma20, rsi, atr = ind["ma5"], ind["ma20"], ind["rsi14"], ind["atr14"]

    # Bid/ask from IBKR if available
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread: Optional[float] = None
    market_data_status = "DELAYED_OK"
    price_available = True
    reference_only = False

    if ibkr_snap and market_type == "STOCK":
        s = ibkr_snap.get("stock_snapshots", {}).get(symbol, {})
        mds = s.get("market_data_status", "")
        if mds == "NO_SUBSCRIPTION_OR_DELAYED_ONLY":
            market_data_status = mds
            reference_only = True
            price_available = False
        elif s.get("bid") and s.get("ask"):
            bid = float(s["bid"])
            ask = float(s["ask"])
            spread = round(ask - bid, 6)
            market_data_status = mds or "DELAYED_OK"
            price_available = s.get("price_available", True)

    if market_type == "FX" and ibkr_snap:
        if symbol == "USDJPY":
            fx_s = ibkr_snap.get("fx_snapshot_USDJPY", {})
            if fx_s.get("bid") and fx_s.get("ask"):
                bid = float(fx_s["bid"])
                ask = float(fx_s["ask"])
                spread = round(ask - bid, 6)
                market_data_status = fx_s.get("market_data_status", "DELAYED_OK")

    # Spread check
    spread_pct = (spread / price) if (spread and price > 0) else 0.0
    if spread_pct > MAX_SPREAD_PCT:
        return {
            "symbol": symbol, "market_type": market_type,
            "result": "SKIP", "reason": f"spread_too_wide ({spread_pct:.3%})",
            "market_data_status": market_data_status,
        }

    # Exclude NO_SUBSCRIPTION stocks
    if market_data_status == "NO_SUBSCRIPTION_OR_DELAYED_ONLY":
        return {
            "symbol": symbol, "market_type": market_type,
            "result": "SKIP", "reason": "no_subscription",
            "market_data_status": market_data_status,
        }

    # Trend and signal
    trend = "BULLISH" if ma5 > ma20 else "BEARISH" if ma5 < ma20 else "NEUTRAL"
    if ma5 > ma20 and rsi < 65:
        signal = "BUY"
    elif ma5 < ma20 and rsi > 35:
        signal = "SELL"
    else:
        signal = "NEUTRAL"

    if signal == "NEUTRAL":
        return {
            "symbol": symbol, "market_type": market_type, "signal": "NEUTRAL",
            "result": "SKIP", "reason": "no_signal",
            "current_price": price, "ma_fast": ma5, "ma_slow": ma20,
            "rsi14": rsi, "trend": trend,
            "market_data_status": market_data_status,
        }

    is_jpy = symbol in FX_JPY_QUOTED
    pos = _calc_position(signal, price, atr, fx_rate, is_jpy, market_type)
    if not pos:
        return None

    rr = pos.get("risk_reward", 0)
    if rr < MIN_RISK_REWARD:
        return {
            "symbol": symbol, "market_type": market_type, "signal": signal,
            "result": "SKIP", "reason": f"rr_too_low ({rr:.1f})",
            "market_data_status": market_data_status,
        }

    risk_jpy = pos.get("risk_per_trade_jpy", 0)
    if risk_jpy > MAX_RISK_PER_TRADE_JPY * 2:
        return {
            "symbol": symbol, "market_type": market_type, "signal": signal,
            "result": "SKIP", "reason": f"risk_too_high (¥{risk_jpy})",
            "market_data_status": market_data_status,
        }

    # V: check daily MTF alignment (only when scanning 1h bars)
    daily_aligned: Optional[bool] = None
    if interval != "1d":
        daily_aligned = _check_daily_alignment(yf_ticker, signal)

    base_conf = _confidence(trend, signal, ind, rr, price_available, daily_aligned=daily_aligned)
    feedback_adj, feedback_reason = _feedback_adjustment(symbol, market_type, signal, feedback)
    conf = max(0, min(100, base_conf + feedback_adj))
    invalidation = (
        f"{symbol} {'SMA5 が SMA20 を下回る' if signal == 'BUY' else 'SMA5 が SMA20 を上回る'}"
        f" または RSI が {'75超' if signal == 'BUY' else '25未満'} になった場合"
    )
    reason_parts = [
        f"{'MA5>MA20' if signal == 'BUY' else 'MA5<MA20'} (gap={abs(ma5-ma20)/ma20*100:.2f}%)",
        f"RSI={rsi:.1f}",
        f"ATR={atr:.4f}",
    ]
    signal_reason = "、".join(reason_parts)
    note = _signal_only_note(market_type, symbol, signal, signal_reason)

    return {
        "result": "OBSERVE_OK",
        "mode": "SIGNAL_ONLY",
        "market_type": market_type,
        "symbol": symbol,
        "direction_candidate": signal,
        "current_price": round(price, 6),
        "bid": bid,
        "ask": ask,
        "spread": spread,
        "spread_pct": round(spread_pct * 100, 4) if spread is not None else None,
        "market_data_status": market_data_status,
        "price_available": price_available,
        "reference_only": reference_only,
        "trend": trend,
        "signal": signal,
        "ma_fast": ma5,
        "ma_slow": ma20,
        "rsi14": rsi,
        "atr14": round(atr, 6),
        "volatility": round(atr / price * 100, 3) if price > 0 else None,
        "entry_direction": signal,
        "entry_price": pos["entry_price"],
        "sl_price": pos["sl_price"],
        "tp_price": pos["tp_price"],
        "invalidation_price": pos["sl_price"],
        "target_price": pos["tp_price"],
        "risk_reward": pos["risk_reward"],
        "quantity_suggested": pos["quantity_suggested"],
        "risk_per_trade_jpy": pos["risk_per_trade_jpy"],
        "target_profit_jpy": pos["target_profit_jpy"],
        "max_loss_estimate": pos["risk_per_trade_jpy"],
        "confidence": conf,
        "confidence_base": base_conf,
        "feedback_score_adj": feedback_adj,
        "feedback_reason": feedback_reason,
        "daily_aligned": daily_aligned,
        "reason": signal_reason,
        "signal_reason": signal_reason,
        "invalidation_reason": invalidation,
        "note": note,
        "scanned_at_jst": _now_jst_str(),
    }


# ── Full scan ─────────────────────────────────────────────────────────────────

def scan(
    scan_fx: bool = True,
    scan_stocks: bool = True,
    interval: str = "1h",
    direction_filter: Optional[str] = None,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Run full scan. Returns (candidates, skipped).
    NO orders are placed.
    """
    print(f"[scanner] {_now_jst_str()}  interval={interval}  SIGNAL_ONLY mode")
    print(f"[scanner] capital=¥{CAPITAL_JPY:,}  max_risk=¥{MAX_RISK_PER_TRADE_JPY:,}/trade  target=¥{TARGET_PROFIT_JPY:,}")
    print()

    # Try IBKR Paper API (optional, graceful fallback)
    ibkr = try_ibkr_snapshot()
    if ibkr:
        print(f"[scanner] IBKR Paper API connected — live bid/ask available")
    else:
        print(f"[scanner] IBKR Paper API not available — using yfinance delayed data")
    print()

    fx_rate = get_usdjpy_rate(ibkr)
    print(f"[scanner] USDJPY rate: {fx_rate:.2f}")
    print()

    feedback = _load_feedback()
    if feedback:
        fx_pref = feedback.get("fx_priority") if isinstance(feedback.get("fx_priority"), dict) else {}
        print(
            f"[scanner] feedback loaded — closed={feedback.get('closed_count', 0)}  "
            f"preferred_market={fx_pref.get('preferred_market', 'NEUTRAL')}"
        )
        print()

    candidates: List[Dict] = []
    skipped: List[Dict] = []

    if scan_fx:
        print("[scanner] --- FX scan ---")
        for pair in FX_PAIRS:
            yf_ticker = FX_YF_TICKERS[pair]
            result = analyze(pair, "FX", yf_ticker, ibkr, fx_rate, interval=interval, feedback=feedback)
            if result:
                if result.get("result") == "OBSERVE_OK":
                    candidates.append(result)
                    print(f"  [{pair}] SIGNAL {result['signal']}  conf={result['confidence']}%  "
                          f"RR={result['risk_reward']}  risk=¥{result['risk_per_trade_jpy']}")
                else:
                    skipped.append(result)
                    print(f"  [{pair}] SKIP  {result.get('reason','')}")
        print()

    if scan_stocks:
        print("[scanner] --- Stocks scan ---")
        for symbol in STOCK_SYMBOLS:
            result = analyze(symbol, "STOCK", symbol, ibkr, fx_rate, interval=interval, feedback=feedback)
            if result:
                if result.get("result") == "OBSERVE_OK":
                    candidates.append(result)
                    print(f"  [{symbol}] SIGNAL {result['signal']}  conf={result['confidence']}%  "
                          f"RR={result['risk_reward']}  risk=¥{result['risk_per_trade_jpy']}  "
                          f"[{result.get('market_data_status','')}]")
                else:
                    skipped.append(result)
                    print(f"  [{symbol}] SKIP  {result.get('reason','')}  "
                          f"[{result.get('market_data_status','')}]")
        print()

    # Sort by confidence desc
    candidates.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    # AI: direction filter — keep only BUY or SELL candidates if requested
    if direction_filter in ("BUY", "SELL"):
        candidates = [c for c in candidates if c.get("signal") == direction_filter]
    return candidates, skipped


# ── Report formatting ─────────────────────────────────────────────────────────

def format_report(
    candidates: List[Dict],
    skipped: List[Dict],
    fx_rate: float,
    new_symbols: Optional[List[str]] = None,
    gone_symbols: Optional[List[str]] = None,
    direction_filter: Optional[str] = None,
) -> str:
    now_str = _now_jst_str()
    dir_label = ""
    if direction_filter == "BUY":
        dir_label = " [ロング候補のみ]"
    elif direction_filter == "SELL":
        dir_label = " [ショート候補のみ]"
    lines = [
        f"[SIGNAL_ONLY 週次候補レポート{dir_label}] {now_str} JST",
        f"想定資金: ¥{CAPITAL_JPY:,}  目標: ¥{TARGET_PROFIT_JPY:,}(+10%)",
        f"最大リスク/トレード: ¥{MAX_RISK_PER_TRADE_JPY:,}  週上限: ¥{MAX_WEEKLY_LOSS_JPY:,}",
        f"USDJPY: {fx_rate:.2f}",
        "",
        "⚠️ SIGNAL_ONLY — 実注文なし。手動確認後に判断すること。",
        "",
    ]

    if not candidates:
        lines += [
            "OBSERVE_NO_SIGNAL",
            "候補: なし（閾値を満たす候補が見つかりませんでした）",
        ]
        return "\n".join(lines)

    lines.append(f"OBSERVE_OK")
    lines.append(f"候補: {len(candidates)}件")
    lines.append("")

    total_risk_jpy = sum(c.get("risk_per_trade_jpy", 0) for c in candidates)
    total_tp_jpy = sum(c.get("target_profit_jpy", 0) for c in candidates)
    lines.append(f"合計想定リスク: ¥{total_risk_jpy:,}  合計想定利益: ¥{total_tp_jpy:,}")
    if total_risk_jpy > 0:
        lines.append(f"合計R:R: {total_tp_jpy/total_risk_jpy:.1f}")
    lines.append("")

    for i, c in enumerate(candidates, 1):
        sym = c["symbol"]
        sig = c["signal"]
        lines += [
            f"━━ #{i} {sym} ({c['market_type']}) ━━",
            f"  シグナル  : {sig}  信頼度={c['confidence']}%",
            f"  価格      : {c['current_price']}  (MA5={c['ma_fast']}  MA20={c['ma_slow']}  RSI={c['rsi14']})",
            f"  エントリー: {c['entry_price']}  方向={c['entry_direction']}",
            f"  損切り    : {c['sl_price']}  利確: {c['tp_price']}",
            f"  R:R       : {c['risk_reward']}",
        ]
        if c["market_type"] == "FX":
            lines.append(f"  推奨数量  : {c['quantity_suggested']}units  "
                         f"リスク=¥{c['risk_per_trade_jpy']:,}  目標=¥{c['target_profit_jpy']:,}")
        else:
            lines.append(f"  推奨数量  : {c['quantity_suggested']}株  "
                         f"リスク=¥{c['risk_per_trade_jpy']:,}  目標=¥{c['target_profit_jpy']:,}")
        lines.append(f"  データ    : {c['market_data_status']}"
                     + (f"  bid={c['bid']}  ask={c['ask']}" if c.get("bid") else "  (bid/ask不明)"))
        lines.append(f"  根拠      : {c['reason']}")
        lines.append(f"  無効条件  : {c['invalidation_reason']}")
        lines.append("")

    skipped_sigs = [s for s in skipped if s.get("signal") not in (None, "NEUTRAL", "")]
    if skipped_sigs:
        lines.append(f"--- 除外候補 ({len(skipped_sigs)}件) ---")
        for s in skipped_sigs:
            lines.append(f"  {s['symbol']} {s.get('signal','-')} → {s.get('reason','')}")
        lines.append("")

    # AB: previous-scan comparison
    if new_symbols or gone_symbols:
        lines.append("--- 前回比較 ---")
        if new_symbols:
            lines.append(f"  🆕 NEW  : {', '.join(new_symbols)}")
        if gone_symbols:
            lines.append(f"  ❌ GONE : {', '.join(gone_symbols)}")
        lines.append("")

    lines.append("⚠️ 注意事項:")
    lines.append("  • データは遅延あり。実弾前に最新価格を必ず確認すること")
    lines.append("  • このレポートは候補抽出のみ。注文は手動で実施すること")
    lines.append(f"  • 週最大損失 ¥{MAX_WEEKLY_LOSS_JPY:,} を超えた場合は即時撤退")
    return "\n".join(lines)


# ── Previous-scan comparison (AB) ────────────────────────────────────────────

def _load_previous_scan_symbols() -> Optional[Dict[str, str]]:
    """Return {symbol: signal} from the most-recent dated signal_weekly_*.json (not today's)."""
    today = _day8()
    files = sorted(REVIEW_OUT.glob("signal_weekly_????????.json"), reverse=True)
    for f in files:
        stem = f.stem  # e.g. "signal_weekly_20260501"
        if stem.endswith(today):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            return {c["symbol"]: c.get("signal", "") for c in data.get("candidates", [])}
        except Exception:
            pass
    return None


def diff_vs_previous(
    candidates: List[Dict],
    prev: Optional[Dict[str, str]],
) -> Tuple[List[str], List[str]]:
    """Return (new_symbols, gone_symbols) compared to previous scan."""
    if prev is None:
        return [], []
    current = {c["symbol"] for c in candidates}
    prev_set = set(prev.keys())
    new_syms = sorted(current - prev_set)
    gone_syms = sorted(prev_set - current)
    return new_syms, gone_syms


# ── Save results ──────────────────────────────────────────────────────────────

def _update_weekly_history(candidates: List[Dict], skipped: List[Dict]) -> None:
    """AL: Maintain signal_weekly_history.json with last 4 scan summaries for dashboard."""
    history_path = REVIEW_OUT / "signal_weekly_history.json"
    try:
        existing: List[Dict] = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
    except Exception:
        existing = []

    buy_count = sum(1 for c in candidates if c.get("signal") == "BUY")
    sell_count = sum(1 for c in candidates if c.get("signal") == "SELL")
    confs = [c.get("confidence", 0) for c in candidates]
    avg_conf = round(sum(confs) / len(confs), 1) if confs else None
    top3 = [{"symbol": c["symbol"], "signal": c.get("signal"), "conf": c.get("confidence")}
            for c in candidates[:3]]

    entry = {
        "generated_at_jst": _now_jst_str(),
        "date8": _day8(),
        "total": len(candidates),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "avg_confidence": avg_conf,
        "skipped_count": len(skipped),
        "top3": top3,
    }
    # Prepend and keep last 4 entries; deduplicate by date8
    filtered = [e for e in existing if e.get("date8") != entry["date8"]]
    history = [entry] + filtered[:3]
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def save_results(candidates: List[Dict], skipped: List[Dict], report: str,
                 direction_filter: Optional[str] = None) -> None:
    REVIEW_OUT.mkdir(parents=True, exist_ok=True)
    day = _day8()
    result = "OBSERVE_OK" if candidates else "OBSERVE_NO_SIGNAL"
    feedback = _load_feedback()
    payload = {
        "generated_at_jst": _now_jst_str(),
        "mode": "SIGNAL_ONLY",
        "result": result,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "skipped_count": len(skipped),
        "capital_jpy": CAPITAL_JPY,
        "target_profit_jpy": TARGET_PROFIT_JPY,
        "goal_reference_pct": GOAL_REFERENCE_PCT,
        "max_risk_per_trade_jpy": MAX_RISK_PER_TRADE_JPY,
        "max_daily_loss_jpy": MAX_DAILY_LOSS_JPY,
        "max_weekly_loss_jpy": MAX_WEEKLY_LOSS_JPY,
        "feedback_summary": _feedback_summary(feedback),
    }
    if direction_filter:
        payload["direction_filter"] = direction_filter
    # JSON with full candidate data
    json_path = REVIEW_OUT / f"signal_weekly_{day}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # Text report
    txt_path = REVIEW_OUT / f"signal_weekly_{day}.txt"
    txt_path.write_text(report, encoding="utf-8")
    # CSV summary
    csv_path = REVIEW_OUT / f"signal_weekly_{day}.csv"
    fields = [
        "scanned_at_jst",
        "symbol",
        "market_type",
        "direction_candidate",
        "signal",
        "current_price",
        "spread",
        "spread_pct",
        "volatility",
        "signal_reason",
        "invalidation_price",
        "target_price",
        "risk_reward",
        "max_loss_estimate",
        "risk_per_trade_jpy",
        "target_profit_jpy",
        "confidence",
        "note",
        "market_data_status",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(candidates)
    # signal_scanner_latest.json for dashboard (W)
    latest_path = REVIEW_OUT / "signal_scanner_latest.json"
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # AL: weekly history for dashboard comparison
    if not direction_filter:
        _update_weekly_history(candidates, skipped)
    print(f"[scanner] saved → {json_path.name}  {txt_path.name}"
          + (f"  {csv_path.name}" if candidates else "")
          + f"  {latest_path.name}")


# ── Notification ──────────────────────────────────────────────────────────────

def _parse_toml_simple(path: Path) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def send_notification(text: str, dry_run: bool = False) -> None:
    if dry_run:
        print("[scanner] DRY-RUN — report above, no notification sent")
        return
    secrets = _parse_toml_simple(SECRETS_FILE)
    ntfy_url = secrets.get("ntfy_topic_url", "").strip()
    if not ntfy_url:
        print("[scanner] ntfy not configured — saved to file only")
        return
    # Truncate for ntfy (8KB limit)
    body = text[:7800].encode("utf-8")
    try:
        req = urllib.request.Request(
            ntfy_url, data=body, method="POST",
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Title": "Signal Weekly SIGNAL_ONLY",
                "Priority": "default",
                "Tags": "mag",
            },
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
        print(f"[scanner] ntfy sent → {ntfy_url}")
    except Exception as exc:
        print(f"[scanner] ntfy error: {exc}", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description="SIGNAL_ONLY weekly candidate scanner — no orders placed"
    )
    ap.add_argument("--dry-run", action="store_true", help="Print report only, no notification")
    ap.add_argument("--fx-only", action="store_true")
    ap.add_argument("--stocks-only", action="store_true")
    ap.add_argument("--interval", default="1h", choices=["1h", "1d"],
                    help="Bar interval for analysis (default: 1h)")
    # AI: direction filter
    ap.add_argument("--long-only", action="store_true", help="Show only BUY (long) candidates")
    ap.add_argument("--short-only", action="store_true", help="Show only SELL (short) candidates")
    args = ap.parse_args()

    do_fx = not args.stocks_only
    do_stocks = not args.fx_only
    direction_filter: Optional[str] = None
    if args.long_only:
        direction_filter = "BUY"
    elif args.short_only:
        direction_filter = "SELL"

    candidates, skipped = scan(scan_fx=do_fx, scan_stocks=do_stocks,
                                interval=args.interval, direction_filter=direction_filter)

    # Fetch USDJPY for report
    ibkr = try_ibkr_snapshot()
    fx_rate = get_usdjpy_rate(ibkr)

    # AB: compare with previous scan
    prev_scan = _load_previous_scan_symbols()
    new_syms, gone_syms = diff_vs_previous(candidates, prev_scan)

    report = format_report(candidates, skipped, fx_rate, new_symbols=new_syms, gone_symbols=gone_syms,
                           direction_filter=direction_filter)

    print()
    print(report)
    print()

    save_results(candidates, skipped, report, direction_filter=direction_filter)
    send_notification(report, dry_run=args.dry_run)
