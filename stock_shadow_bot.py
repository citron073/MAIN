#!/usr/bin/env python3
"""
Stock Shadow Bot — virtual paper trading to accumulate sample trades.

Fetches OHLCV via yfinance (free), applies SMA5/SMA20 + RSI(14) signal,
optionally places paper orders via ibkr_paper_api.py.

Entry : SMA5 > SMA20 AND RSI < 65
Exit  : SMA5 < SMA20 OR RSI > 75 OR stop loss hit

Risk controls (実弾対応):
  stop_pct          : stop loss from entry (default -2%)          Q
  max_positions     : max concurrent open positions (default 3)
  daily_loss_limit  : daily loss limit in USD (default -50)
  commission        : estimated commission per order in USD (default $1)

Features logged per trade (J):
  vol_ratio   = current volume / 20-bar average volume
  price_dev   = (price - SMA20) / SMA20
  prev_return = (price - prev_bar_price) / prev_bar_price

State : review_out/stock_shadow_state.json
Log   : review_out/stock_shadow_YYYYMMDD.csv

Usage:
    python3 stock_shadow_bot.py                           # dry-run, hourly bars
    python3 stock_shadow_bot.py --interval 1d             # daily bars
    python3 stock_shadow_bot.py --execute                 # place paper orders
    python3 stock_shadow_bot.py --symbols AAPL,NVDA,QQQ
    python3 stock_shadow_bot.py --backtest                # 30-day backtest
    python3 stock_shadow_bot.py --backtest --backtest-days 60
    python3 stock_shadow_bot.py --ml-filter               # gate with ML model
    python3 stock_shadow_bot.py --mtf-filter              # require bullish daily trend (L)
    python3 stock_shadow_bot.py --stop-pct -0.03          # 3% stop loss
"""
from __future__ import annotations

import csv
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
REVIEW_OUT = ROOT / "review_out"
STATE_FILE = REVIEW_OUT / "stock_shadow_state.json"
SECRETS_FILE = ROOT / ".streamlit" / "secrets.toml"
NOTIFY_STATE = ROOT / ".streamlit" / "notification_policy_state.json"

try:
    from tools.notification_policy import LEVEL_INFO, post_ntfy, read_toml_str
except ModuleNotFoundError:
    sys.path.insert(0, str(ROOT))
    from tools.notification_policy import LEVEL_INFO, post_ntfy, read_toml_str  # type: ignore

DEFAULT_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "QQQ", "SPY", "AMZN", "META", "AMD"]
DEFAULT_PAPER_API = "http://localhost:8812"
DEFAULT_QUANTITY = 1
DEFAULT_INTERVAL = "1h"
REENTRY_COOLDOWN_HOURS = 2
DEFAULT_STOP_PCT = -0.02         # Q: -2% stop loss from entry price
DEFAULT_TP_PCT = 0.04            # U: +4% take profit from entry (2:1 R:R with SL=-2%)
DEFAULT_RISK_PER_TRADE_USD = 0.0  # AC: 0=disabled; >0 → qty=floor(risk/ATR14)
DEFAULT_MAX_POSITIONS = 3        # max concurrent open positions
DEFAULT_DAILY_LOSS_LIMIT = -50.0  # USD daily loss limit (0 = disabled)
COMMISSION_PER_ORDER_USD = 1.0   # estimated IBKR commission per order

CSV_HEADERS = [
    "timestamp_jst", "symbol", "action", "reason",
    "price", "sma5", "sma20", "rsi14", "quantity",
    "order_id", "order_status", "mode", "interval",
    "vol_ratio", "price_dev", "prev_return", "pnl_usd",
    "sp500_member", "avg_volume_1h",
]

# ── S&P500 quality universe (article: index membership = professional pre-screening proxy) ──
# Index constituents have already passed institutional liquidity/quality review.
# Trading outside this universe = searching for diamonds in 3800 stocks alone.
SP500_CORE_UNIVERSE: frozenset = frozenset({
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "AVGO",
    # Financials
    "JPM", "V", "MA", "BAC", "GS", "MS", "BLK", "SCHW", "AXP", "WFC", "C",
    # Healthcare
    "UNH", "JNJ", "LLY", "ABBV", "MRK", "TMO", "ABT", "DHR", "GILD", "ISRG",
    # Consumer
    "WMT", "PG", "KO", "PEP", "COST", "MCD", "SBUX", "HD", "LOW", "NKE",
    # Energy
    "XOM", "CVX", "COP", "EOG",
    # Industrials
    "RTX", "CAT", "HON", "UPS", "DE", "LMT", "GE",
    # Semiconductors
    "AMD", "INTC", "QCOM", "AMAT", "MU", "TXN", "ADI", "KLAC", "LRCX",
    # Software/cloud
    "CRM", "ORCL", "ADBE", "INTU", "IBM", "NOW", "PANW", "SNPS", "CDNS",
    # Telecom/media
    "T", "VZ", "NFLX", "DIS",
    # Other large caps
    "BRK.B", "ACN", "NEE", "PLD", "AMT", "CI", "CB", "MMC", "AON",
    "BKNG", "REGN", "VRTX", "MDT", "ZTS", "SPGI", "MCO",
    # ETFs — always OK (index products by definition)
    "SPY", "QQQ", "IWM", "VTI", "VOO", "GLD", "TLT", "XLK", "XLF", "XLE",
})

MIN_AVG_VOLUME_1H = 200_000    # 20万株/1h bar ≈ 日次120万株以上
MIN_AVG_VOLUME_1D = 1_000_000  # 100万株/日


def _now_jst() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


def _now_jst_str() -> str:
    return _now_jst().strftime("%Y-%m-%d %H:%M:%S")


def _day8() -> str:
    return _now_jst().strftime("%Y%m%d")


def _log_path() -> Path:
    return REVIEW_OUT / f"stock_shadow_{_day8()}.csv"


# ── yfinance ──────────────────────────────────────────────────────────────────

def _fetch_ohlcv(symbol: str, interval: str = "1h") -> Optional[Dict[str, List[float]]]:
    """Returns {"closes": [...], "volumes": [...]} or None."""
    try:
        import yfinance as yf  # type: ignore
    except ImportError:
        print("  [!] yfinance not installed. Run: pip3 install yfinance", file=sys.stderr)
        return None
    try:
        df = yf.Ticker(symbol).history(period="60d", interval=interval)
        if df is None or len(df) < 22:
            return None
        return {
            "closes": [float(v) for v in df["Close"].values],
            "volumes": [float(v) for v in df["Volume"].values],
            "highs": [float(v) for v in df["High"].values],
            "lows": [float(v) for v in df["Low"].values],
        }
    except Exception as exc:
        print(f"  [yfinance] {symbol}: {exc}", file=sys.stderr)
        return None


def _check_symbol_quality(
    symbol: str,
    volumes: List[float],
    interval: str,
) -> Dict[str, Any]:
    """Index membership + liquidity gate (article: filter garbage stocks first).
    S&P500 membership = passed institutional pre-screening.
    Volume check = minimum daily trading activity.
    Returns {sp500_member, avg_volume, liquid, pass_quality}.
    """
    sym_up = symbol.upper()
    in_sp500 = sym_up in SP500_CORE_UNIVERSE

    avg_vol = 0.0
    if volumes:
        tail = volumes[-20:] if len(volumes) >= 20 else volumes
        avg_vol = sum(tail) / max(len(tail), 1)

    threshold = MIN_AVG_VOLUME_1D if interval == "1d" else MIN_AVG_VOLUME_1H
    liquid = avg_vol >= threshold if avg_vol > 0 else True  # fail-open on missing volume

    return {
        "sp500_member": in_sp500,
        "avg_volume_1h": round(avg_vol),
        "liquid": liquid,
        "pass_quality": in_sp500 or liquid,
    }


def _fetch_closes(symbol: str, interval: str = "1h") -> Optional[List[float]]:
    ohlcv = _fetch_ohlcv(symbol, interval=interval)
    return ohlcv["closes"] if ohlcv else None


# ── Indicators ────────────────────────────────────────────────────────────────

def _sma(closes: List[float], n: int) -> float:
    return sum(closes[-n:]) / n


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


def _vol_ratio(volumes: List[float], n: int = 20) -> float:
    """Current bar volume / n-period average volume."""
    if len(volumes) < n + 1:
        return 1.0
    avg = sum(volumes[-(n + 1):-1]) / n
    return round(volumes[-1] / avg, 4) if avg > 0 else 1.0


def _price_dev(price: float, sma20: float) -> float:
    """(price - SMA20) / SMA20."""
    if sma20 == 0:
        return 0.0
    return round((price - sma20) / sma20, 6)


def _prev_return(closes: List[float]) -> float:
    """(last_close - prev_close) / prev_close."""
    if len(closes) < 2 or closes[-2] == 0:
        return 0.0
    return round((closes[-1] - closes[-2]) / closes[-2], 6)


def _atr14(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """True Range ATR over last `period` bars."""
    if len(highs) < period + 1:
        return closes[-1] * 0.02  # fallback: 2% of price
    trs: List[float] = []
    for i in range(-period, 0):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / period


def _atr_quantity(risk_per_trade_usd: float, atr: float) -> int:
    """Position size = floor(risk / ATR). Min 1."""
    if atr <= 0:
        return 1
    return max(1, int(risk_per_trade_usd / atr))


# ── Signal ────────────────────────────────────────────────────────────────────

def compute_signal(
    symbol: str,
    in_position: bool,
    interval: str = "1h",
    closes_override: Optional[List[float]] = None,
    volumes_override: Optional[List[float]] = None,
) -> Optional[Dict[str, Any]]:
    if closes_override is not None:
        closes = closes_override
        volumes = volumes_override or []
    else:
        ohlcv = _fetch_ohlcv(symbol, interval=interval)
        if ohlcv is None:
            return None
        closes = ohlcv["closes"]
        volumes = ohlcv["volumes"]

    quality = _check_symbol_quality(symbol, volumes, interval)
    price = closes[-1]
    sma5 = round(_sma(closes, 5), 4)
    sma20 = round(_sma(closes, 20), 4)
    rsi = _rsi(closes)
    vr = _vol_ratio(volumes) if len(volumes) >= 21 else 1.0
    pd_ = _price_dev(price, sma20)
    pr = _prev_return(closes)

    if in_position:
        if sma5 < sma20:
            action, reason = "SELL", "SMA5_CROSS_DOWN"
        elif rsi > 75:
            action, reason = "SELL", "RSI_OVERBOUGHT"
        else:
            action, reason = "HOLD", "IN_POSITION"
    else:
        if sma5 > sma20 and rsi < 65:
            action, reason = "BUY", "SMA5_ABOVE_SMA20"
        else:
            action, reason = "HOLD", "NO_SIGNAL"

    return {
        "symbol": symbol, "price": round(float(price), 4),
        "sma5": sma5, "sma20": sma20, "rsi14": rsi,
        "vol_ratio": vr, "price_dev": pd_, "prev_return": pr,
        "action": action, "reason": reason,
        "sp500_member": quality["sp500_member"],
        "avg_volume_1h": quality["avg_volume_1h"],
        "pass_quality": quality["pass_quality"],
    }


# ── State ─────────────────────────────────────────────────────────────────────

def load_state() -> Dict[str, Any]:
    REVIEW_OUT.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "positions": {}, "total_trades": 0, "total_pnl_usd": 0.0,
        "daily_pnl_usd": {}, "cooldown_until": {}, "last_signals": {},
        "peak_pnl": 0.0, "max_drawdown_usd": 0.0, "commission_paid_usd": 0.0,
    }


def save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


# ── ML filter ─────────────────────────────────────────────────────────────────

def _load_ml_model() -> Optional[Dict[str, Any]]:
    model_path = REVIEW_OUT / "stock_ml_model.json"
    if not model_path.exists():
        return None
    try:
        return json.loads(model_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _ml_predict(model: Dict[str, Any], sig: Dict[str, Any]) -> float:
    """Return P(profitable exit) using saved logistic regression weights."""
    import math
    w = model.get("weights", [])
    b = model.get("bias", 0.0)
    features = model.get("features", ["sma_ratio", "rsi_norm"])
    sma5 = sig.get("sma5", 1.0)
    sma20 = sig.get("sma20", 1.0)
    feat_map = {
        "sma_ratio": sma5 / sma20 if sma20 != 0 else 1.0,
        "rsi_norm": sig.get("rsi14", 50.0) / 100.0,
        "vol_ratio": sig.get("vol_ratio", 1.0),
        "price_dev": sig.get("price_dev", 0.0),
        "prev_return": sig.get("prev_return", 0.0),
    }
    x = [feat_map.get(f, 0.0) for f in features]
    if len(w) != len(x):
        x = [feat_map["sma_ratio"], feat_map["rsi_norm"]]
        w = w[:2] if len(w) >= 2 else [0.0, 0.0]
    z = sum(wi * xi for wi, xi in zip(w, x)) + b
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


# ── Notifications (K2) ────────────────────────────────────────────────────────

def _parse_toml_simple(path: Path) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip().strip('"').strip("'")
    return result


def _send_trade_notify(action: str, symbol: str, price: float,
                       pnl: Optional[float], interval: str,
                       extra: str = "") -> None:
    """Fire-and-forget ntfy notification on BUY or SELL. Silent on error."""
    ntfy_url = read_toml_str(SECRETS_FILE, "ntfy_topic_url")
    if not ntfy_url:
        return
    bearer = read_toml_str(SECRETS_FILE, "ntfy_bearer_token")
    if action == "BUY":
        title = f"Shadow BUY {symbol}"
        body = f"{symbol} BUY @ ${price:.2f}  [{interval}]{extra}"
        tags = "arrow_up"
    elif action == "SHORT":
        title = f"Shadow SHORT {symbol}"
        body = f"{symbol} SHORT @ ${price:.2f}  [{interval}]{extra}"
        tags = "arrow_down"
    elif action == "COVER":
        pnl_str = f"  P&L=${pnl:+.2f}" if pnl is not None else ""
        title = f"Shadow COVER {symbol}"
        body = f"{symbol} COVER @ ${price:.2f}{pnl_str}  [{interval}]{extra}"
        tags = "arrow_up"
    else:
        pnl_str = f"  P&L=${pnl:+.2f}" if pnl is not None else ""
        title = f"Shadow SELL {symbol}"
        body = f"{symbol} SELL @ ${price:.2f}{pnl_str}  [{interval}]{extra}"
        tags = "arrow_down"
    try:
        ok, msg = post_ntfy(
            ntfy_url,
            title,
            body,
            level=LEVEL_INFO,
            tags=tags,
            bearer=bearer,
            state_path=NOTIFY_STATE,
            event_code="",
        )
        print(f"    → ntfy {msg}: {title}")
    except Exception as exc:
        print(f"    → ntfy error: {exc}", file=sys.stderr)


# ── Multi-timeframe filter (L) ────────────────────────────────────────────────

def _check_daily_trend(symbol: str) -> bool:
    """Return True if daily SMA5 > SMA20 (bullish daily trend). True on data error."""
    closes = _fetch_closes(symbol, interval="1d")
    if closes is None or len(closes) < 20:
        return True
    return _sma(closes, 5) > _sma(closes, 20)


# ── Paper API ─────────────────────────────────────────────────────────────────

def place_paper_order(base_url: str, symbol: str, action: str, quantity: int) -> Optional[Dict]:
    body = json.dumps(
        {"symbol": symbol, "action": action, "quantity": quantity, "order_type": "MKT"}
    ).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/order", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"  [paper-api] /order: {exc}", file=sys.stderr)
        return None


# ── CSV log ───────────────────────────────────────────────────────────────────

def append_log(row: Dict[str, Any], log_path: Optional[Path] = None) -> None:
    path = log_path or _log_path()
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADERS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerow(row)


# ── Main run ──────────────────────────────────────────────────────────────────

def run(
    symbols: List[str],
    execute: bool,
    paper_api: str,
    quantity: int,
    interval: str = "1h",
    log_hold: bool = True,
    ml_filter: bool = False,
    ml_min_prob: float = 0.55,
    mtf_filter: bool = False,
    stop_pct: float = DEFAULT_STOP_PCT,
    tp_pct: float = DEFAULT_TP_PCT,
    max_positions: int = DEFAULT_MAX_POSITIONS,
    daily_loss_limit: float = DEFAULT_DAILY_LOSS_LIMIT,
    commission: float = COMMISSION_PER_ORDER_USD,
    risk_per_trade: float = DEFAULT_RISK_PER_TRADE_USD,
    both_sides: bool = False,
) -> None:
    state = load_state()
    positions: Dict[str, Any] = state.get("positions", {})
    total_trades: int = int(state.get("total_trades", 0))
    total_pnl: float = float(state.get("total_pnl_usd", 0.0))
    daily_pnl: Dict[str, float] = state.get("daily_pnl_usd", {})
    cooldown_until: Dict[str, str] = state.get("cooldown_until", {})
    last_signals: Dict[str, Any] = state.get("last_signals", {})
    peak_pnl: float = float(state.get("peak_pnl", 0.0))
    max_drawdown: float = float(state.get("max_drawdown_usd", 0.0))
    commission_paid: float = float(state.get("commission_paid_usd", 0.0))
    mode = "EXECUTE" if execute else "DRY_RUN"

    ml_model = _load_ml_model() if ml_filter else None
    if ml_filter and ml_model is None:
        print("  [ml] No model found — skipping ML filter (run stock_ml_train.py first)", file=sys.stderr)

    filters = []
    if ml_filter:
        filters.append(f"ML≥{ml_min_prob:.0%}")
    if mtf_filter:
        filters.append("MTF:1d")
    if stop_pct < 0:
        filters.append(f"SL{stop_pct:.0%}")
    if tp_pct > 0:
        filters.append(f"TP+{tp_pct:.0%}")
    if risk_per_trade > 0:
        filters.append(f"ATRsize${risk_per_trade:.0f}")
    filter_str = f"  filters=[{','.join(filters)}]" if filters else ""

    now = _now_jst()
    today_str = now.strftime("%Y-%m-%d")
    today_pnl = daily_pnl.get(today_str, 0.0)
    daily_blocked = daily_loss_limit < 0 and today_pnl <= daily_loss_limit

    print(f"[shadow] {_now_jst_str()}  mode={mode}  interval={interval}  symbols={symbols}{filter_str}")
    print(f"[shadow] open={list(positions.keys()) or 'none'}  today_pnl=${today_pnl:+.2f}  "
          f"cumPnL=${total_pnl:+.2f}  drawdown=${max_drawdown:.2f}")
    if daily_blocked:
        print(f"[shadow] *** DAILY LOSS LIMIT HIT (${today_pnl:.2f} <= ${daily_loss_limit:.2f}) — BUY entries blocked ***")
    print()

    for symbol in symbols:
        in_pos = symbol in positions
        sig = compute_signal(symbol, in_position=in_pos, interval=interval)
        if sig is None:
            print(f"  [{symbol}] data unavailable — skipped")
            continue

        # Quality gate: S&P500 membership + liquidity check (article: filter garbage first)
        if not sig.get("sp500_member") and not in_pos:
            if sig["action"] == "BUY" or (both_sides and sig["action"] == "SHORT"):
                print(f"  [{symbol}] ⚠ NOT S&P500 — new entry blocked (use index-member symbols)")
                continue
        if not sig.get("pass_quality") and not in_pos:
            avg_v = sig.get("avg_volume_1h", 0)
            if sig["action"] in ("BUY", "SHORT"):
                print(f"  [{symbol}] LOW VOLUME (avg={avg_v:,}/bar) — new entry skipped")
                continue

        # P/N: pre-fetch daily trend (avoids double-fetch in MTF gate)
        daily_bull: Optional[bool] = None
        if mtf_filter:
            daily_bull = _check_daily_trend(symbol)

        pos_side = positions[symbol].get("side", "LONG") if in_pos else None

        # AH: SHORT position — SL/TP/Breakeven (inverted direction vs LONG)
        if in_pos and pos_side == "SHORT":
            ep = float(positions[symbol].get("entry_price", sig["price"]))
            saved_stop = positions[symbol].get("stop_price")
            effective_stop = saved_stop if saved_stop is not None else ep * (1 + abs(stop_pct))
            if stop_pct < 0 and sig["price"] >= effective_stop:
                be_active = positions[symbol].get("breakeven_activated", False)
                sig["action"] = "COVER"
                sig["reason"] = "BREAKEVEN_SL" if be_active else "STOP_LOSS"
                print(f"  [{symbol}] *** SHORT {'BREAKEVEN SL' if be_active else 'STOP LOSS'} "
                      f"@ ${sig['price']:.2f}  (entry=${ep:.2f}  stop=${effective_stop:.2f}) ***")
            if tp_pct > 0 and sig["action"] != "COVER":
                tp_price_val = ep * (1 - tp_pct)
                if sig["price"] <= tp_price_val:
                    sig["action"] = "COVER"
                    sig["reason"] = "TAKE_PROFIT"
                    print(f"  [{symbol}] *** SHORT TAKE PROFIT @ ${sig['price']:.2f}  "
                          f"(entry=${ep:.2f}  tp={tp_price_val:.2f}) ***")
            if (tp_pct > 0 and stop_pct < 0 and sig["action"] != "COVER"
                    and not positions[symbol].get("breakeven_activated")):
                partial_threshold = ep * (1 - tp_pct * 0.5)
                if sig["price"] <= partial_threshold:
                    positions[symbol]["stop_price"] = ep
                    positions[symbol]["breakeven_activated"] = True
                    print(f"  [{symbol}] *** SHORT BREAKEVEN SL activated @ ${ep:.2f} ***")
            if sig["action"] not in ("COVER",):
                if sig["sma5"] > sig["sma20"]:
                    sig["action"] = "COVER"
                    sig["reason"] = "SMA5_CROSS_UP"
                elif sig["rsi14"] < 25:
                    sig["action"] = "COVER"
                    sig["reason"] = "RSI_OVERSOLD"
                else:
                    sig["action"] = "HOLD"
                    sig["reason"] = "IN_SHORT_POSITION"

        # Q/X: LONG stop loss + breakeven SL — evaluate BEFORE HOLD check
        if in_pos and pos_side != "SHORT" and stop_pct < 0:
            ep = float(positions[symbol].get("entry_price", sig["price"]))
            # Use saved stop_price (may have been moved to breakeven by X)
            saved_stop = positions[symbol].get("stop_price")
            effective_stop = saved_stop if saved_stop is not None else ep * (1 + stop_pct)
            if sig["price"] <= effective_stop:
                be_active = positions[symbol].get("breakeven_activated", False)
                sig["action"] = "SELL"
                sig["reason"] = "BREAKEVEN_SL" if be_active else "STOP_LOSS"
                print(f"  [{symbol}] *** {'BREAKEVEN SL' if be_active else 'STOP LOSS'} "
                      f"@ ${sig['price']:.2f}  (entry=${ep:.2f}  stop=${effective_stop:.2f}) ***")

        # U: LONG take profit override — evaluate BEFORE HOLD check
        if in_pos and pos_side != "SHORT" and tp_pct > 0 and sig["action"] != "SELL":
            ep = float(positions[symbol].get("entry_price", sig["price"]))
            tp_price_val = ep * (1 + tp_pct)
            if sig["price"] >= tp_price_val:
                sig["action"] = "SELL"
                sig["reason"] = "TAKE_PROFIT"
                print(f"  [{symbol}] *** TAKE PROFIT @ ${sig['price']:.2f}  "
                      f"(entry=${ep:.2f}  tp=${tp_price_val:.2f}) ***")

        # X: LONG breakeven SL activation — at 50% of TP distance, move stop to entry
        if in_pos and pos_side != "SHORT" and tp_pct > 0 and stop_pct < 0 and sig["action"] != "SELL":
            ep = float(positions[symbol].get("entry_price", sig["price"]))
            partial_threshold = ep * (1 + tp_pct * 0.5)
            if sig["price"] >= partial_threshold and not positions[symbol].get("breakeven_activated"):
                positions[symbol]["stop_price"] = ep
                positions[symbol]["breakeven_activated"] = True
                print(f"  [{symbol}] *** BREAKEVEN SL activated @ ${ep:.2f} "
                      f"(price=${sig['price']:.2f} >= {partial_threshold:.2f}) ***")

        # Save last_signals (after stop-loss override so action is accurate)
        last_sig_entry: Dict[str, Any] = {
            "price": sig["price"], "sma5": sig["sma5"], "sma20": sig["sma20"],
            "rsi14": sig["rsi14"], "vol_ratio": sig["vol_ratio"],
            "price_dev": sig["price_dev"], "prev_return": sig["prev_return"],
            "action": sig["action"], "reason": sig["reason"],
            "ts": _now_jst_str(),
        }
        if mtf_filter:
            last_sig_entry["daily_bull"] = daily_bull
        last_signals[symbol] = last_sig_entry

        trend_tag = f"  daily={'↑' if daily_bull else '↓' if daily_bull is False else '?'}" if mtf_filter else ""
        if sig["reason"] != "STOP_LOSS":  # stop loss already printed above
            print(f"  [{symbol}] {sig['action']:4s}  price=${sig['price']:.2f}"
                  f"  SMA5={sig['sma5']:.2f}  SMA20={sig['sma20']:.2f}"
                  f"  RSI={sig['rsi14']:.1f}  vr={sig['vol_ratio']:.2f}{trend_tag}  [{sig['reason']}]")

        # Log HOLD as negative training samples (B)
        if sig["action"] == "HOLD" and log_hold:
            append_log({
                "timestamp_jst": _now_jst_str(), "symbol": symbol, "action": "HOLD",
                "reason": sig["reason"], "price": sig["price"],
                "sma5": sig["sma5"], "sma20": sig["sma20"], "rsi14": sig["rsi14"],
                "vol_ratio": sig["vol_ratio"], "price_dev": sig["price_dev"],
                "prev_return": sig["prev_return"],
                "quantity": quantity, "order_id": None,
                "order_status": "HOLD_LOG", "mode": mode, "interval": interval,
            })
            continue

        # AH: SHORT entry when both_sides and signal is bearish
        if not in_pos and both_sides and sig["action"] == "HOLD":
            if sig["sma5"] < sig["sma20"] and sig["rsi14"] > 50:
                sig["action"] = "SHORT"
                sig["reason"] = "SMA5_BELOW_SMA20"

        if sig["action"] not in ("BUY", "SELL", "SHORT", "COVER"):
            continue
        if sig["action"] in ("SELL", "COVER") and not in_pos:
            continue

        # Cooldown check (F)
        if sig["action"] in ("BUY", "SHORT") and symbol in cooldown_until:
            try:
                cd_until = datetime.strptime(cooldown_until[symbol], "%Y-%m-%d %H:%M:%S")
                if now < cd_until:
                    remaining = int((cd_until - now).total_seconds() / 60)
                    print(f"    → COOLDOWN ({remaining}min left) — skipped")
                    if log_hold:
                        append_log({
                            "timestamp_jst": _now_jst_str(), "symbol": symbol, "action": "HOLD",
                            "reason": "COOLDOWN", "price": sig["price"],
                            "sma5": sig["sma5"], "sma20": sig["sma20"], "rsi14": sig["rsi14"],
                            "vol_ratio": sig["vol_ratio"], "price_dev": sig["price_dev"],
                            "prev_return": sig["prev_return"],
                            "quantity": quantity, "order_id": None,
                            "order_status": "COOLDOWN", "mode": mode, "interval": interval,
                        })
                    continue
            except (ValueError, TypeError):
                pass

        # Max positions check
        if sig["action"] in ("BUY", "SHORT") and len(positions) >= max_positions:
            print(f"    → MAX_POSITIONS ({max_positions}) — skipped")
            if log_hold:
                append_log({
                    "timestamp_jst": _now_jst_str(), "symbol": symbol, "action": "HOLD",
                    "reason": "MAX_POSITIONS", "price": sig["price"],
                    "sma5": sig["sma5"], "sma20": sig["sma20"], "rsi14": sig["rsi14"],
                    "vol_ratio": sig["vol_ratio"], "price_dev": sig["price_dev"],
                    "prev_return": sig["prev_return"],
                    "quantity": quantity, "order_id": None,
                    "order_status": "MAX_POSITIONS", "mode": mode, "interval": interval,
                })
            continue

        # Daily loss limit check
        if sig["action"] in ("BUY", "SHORT") and daily_blocked:
            print(f"    → DAILY_LOSS_LIMIT — skipped")
            if log_hold:
                append_log({
                    "timestamp_jst": _now_jst_str(), "symbol": symbol, "action": "HOLD",
                    "reason": "DAILY_LOSS_LIMIT", "price": sig["price"],
                    "sma5": sig["sma5"], "sma20": sig["sma20"], "rsi14": sig["rsi14"],
                    "vol_ratio": sig["vol_ratio"], "price_dev": sig["price_dev"],
                    "prev_return": sig["prev_return"],
                    "quantity": quantity, "order_id": None,
                    "order_status": "DAILY_LOSS_LIMIT", "mode": mode, "interval": interval,
                })
            continue

        # Multi-timeframe filter (L) — only for LONG BUY entries
        if sig["action"] == "BUY" and mtf_filter and interval == "1h":
            if daily_bull is None:
                daily_bull = _check_daily_trend(symbol)
            if not daily_bull:
                print(f"    → MTF filter blocked entry (daily SMA5 < SMA20)")
                if log_hold:
                    append_log({
                        "timestamp_jst": _now_jst_str(), "symbol": symbol, "action": "HOLD",
                        "reason": "MTF_FILTER", "price": sig["price"],
                        "sma5": sig["sma5"], "sma20": sig["sma20"], "rsi14": sig["rsi14"],
                        "vol_ratio": sig["vol_ratio"], "price_dev": sig["price_dev"],
                        "prev_return": sig["prev_return"],
                        "quantity": quantity, "order_id": None,
                        "order_status": "MTF_FILTER", "mode": mode, "interval": interval,
                    })
                continue

        # ML filter (E) — only for LONG BUY entries
        if sig["action"] == "BUY" and ml_model is not None:
            prob = _ml_predict(ml_model, sig)
            print(f"    → ML P(profit)={prob:.1%}  (threshold={ml_min_prob:.0%})")
            if prob < ml_min_prob:
                print(f"    → ML gate blocked entry")
                if log_hold:
                    append_log({
                        "timestamp_jst": _now_jst_str(), "symbol": symbol, "action": "HOLD",
                        "reason": "ML_GATE", "price": sig["price"],
                        "sma5": sig["sma5"], "sma20": sig["sma20"], "rsi14": sig["rsi14"],
                        "vol_ratio": sig["vol_ratio"], "price_dev": sig["price_dev"],
                        "prev_return": sig["prev_return"],
                        "quantity": quantity, "order_id": None,
                        "order_status": "ML_GATE", "mode": mode, "interval": interval,
                    })
                continue

        # AC: ATR-based dynamic quantity sizing
        effective_qty = quantity
        if sig["action"] in ("BUY", "SHORT") and risk_per_trade > 0:
            ohlcv_atr = _fetch_ohlcv(symbol, interval=interval)
            if (ohlcv_atr and len(ohlcv_atr.get("highs", [])) >= 15
                    and len(ohlcv_atr.get("lows", [])) >= 15):
                atr_val = _atr14(ohlcv_atr["highs"], ohlcv_atr["lows"], ohlcv_atr["closes"])
                effective_qty = _atr_quantity(risk_per_trade, atr_val)
                print(f"    → ATR14={atr_val:.4f}  risk=${risk_per_trade:.0f} → qty={effective_qty}")

        order_id, order_status = None, "DRY_RUN"
        if execute:
            result = place_paper_order(paper_api, symbol, sig["action"], effective_qty)
            if result and "error" not in result:
                order_id = result.get("order_id")
                order_status = result.get("status", "SUBMITTED")
                print(f"    → paper order {order_id} [{order_status}]")
            else:
                order_status = "API_ERROR"
                print(f"    → paper API error: {result}")

        log_pnl_usd: Optional[float] = None
        if sig["action"] == "BUY":
            positions[symbol] = {
                "entry_price": sig["price"],
                "entry_time": _now_jst_str(),
                "quantity": effective_qty,
                "reason": sig["reason"],
                "side": "LONG",
                "stop_price": round(sig["price"] * (1 + stop_pct), 4) if stop_pct < 0 else None,
                "tp_price": round(sig["price"] * (1 + tp_pct), 4) if tp_pct > 0 else None,
            }
            commission_paid = round(commission_paid + commission, 2)
            _send_trade_notify("BUY", symbol, sig["price"], None, interval)  # K2
        elif sig["action"] == "SHORT":
            # AH: SHORT entry — SL is above entry, TP is below entry
            positions[symbol] = {
                "entry_price": sig["price"],
                "entry_time": _now_jst_str(),
                "quantity": effective_qty,
                "reason": sig["reason"],
                "side": "SHORT",
                "stop_price": round(sig["price"] * (1 + abs(stop_pct)), 4) if stop_pct < 0 else None,
                "tp_price": round(sig["price"] * (1 - tp_pct), 4) if tp_pct > 0 else None,
            }
            commission_paid = round(commission_paid + commission, 2)
            _send_trade_notify("SHORT", symbol, sig["price"], None, interval)
        elif sig["action"] == "COVER":
            # AH: COVER exit — P&L is entry - current (inverted vs SELL)
            entry = positions.pop(symbol, {})
            effective_qty = int(entry.get("quantity", quantity))
            gross_pnl = (float(entry.get("entry_price", sig["price"])) - sig["price"]) * effective_qty
            net_pnl = round(gross_pnl - commission * 2, 2)
            log_pnl_usd = net_pnl
            commission_paid = round(commission_paid + commission, 2)
            total_trades += 1
            total_pnl = round(total_pnl + net_pnl, 2)
            date_str = now.strftime("%Y-%m-%d")
            daily_pnl[date_str] = round(daily_pnl.get(date_str, 0.0) + net_pnl, 2)
            if total_pnl > peak_pnl:
                peak_pnl = total_pnl
            dd = total_pnl - peak_pnl
            if dd < max_drawdown:
                max_drawdown = dd
            cd_dt = now + timedelta(hours=REENTRY_COOLDOWN_HOURS)
            cooldown_until[symbol] = cd_dt.strftime("%Y-%m-%d %H:%M:%S")
            notify_extra = f"  [{sig['reason']}]" if sig["reason"] == "STOP_LOSS" else ""
            print(f"    → SHORT exit P&L: ${net_pnl:+.2f} (gross ${gross_pnl:+.2f} - comm ${commission*2:.2f})"
                  f"  cum=${total_pnl:+.2f}  dd=${max_drawdown:.2f}  trades={total_trades}")
            _send_trade_notify("COVER", symbol, sig["price"], net_pnl, interval, notify_extra)
        elif sig["action"] == "SELL":
            entry = positions.pop(symbol, {})
            effective_qty = int(entry.get("quantity", quantity))
            gross_pnl = (sig["price"] - float(entry.get("entry_price", sig["price"]))) * effective_qty
            # Deduct round-trip commission (buy + sell)
            net_pnl = round(gross_pnl - commission * 2, 2)
            log_pnl_usd = net_pnl
            commission_paid = round(commission_paid + commission, 2)
            total_trades += 1
            total_pnl = round(total_pnl + net_pnl, 2)
            date_str = now.strftime("%Y-%m-%d")
            daily_pnl[date_str] = round(daily_pnl.get(date_str, 0.0) + net_pnl, 2)
            # Drawdown tracking
            if total_pnl > peak_pnl:
                peak_pnl = total_pnl
            dd = total_pnl - peak_pnl
            if dd < max_drawdown:
                max_drawdown = dd
            # Re-entry cooldown (F)
            cd_dt = now + timedelta(hours=REENTRY_COOLDOWN_HOURS)
            cooldown_until[symbol] = cd_dt.strftime("%Y-%m-%d %H:%M:%S")
            notify_extra = f"  [{sig['reason']}]" if sig["reason"] == "STOP_LOSS" else ""
            print(f"    → exit P&L: ${net_pnl:+.2f} (gross ${gross_pnl:+.2f} - comm ${commission*2:.2f})"
                  f"  cum=${total_pnl:+.2f}  dd=${max_drawdown:.2f}  trades={total_trades}")
            _send_trade_notify("SELL", symbol, sig["price"], net_pnl, interval, notify_extra)  # K2

        append_log({
            "timestamp_jst": _now_jst_str(), "symbol": symbol,
            "action": sig["action"], "reason": sig["reason"],
            "price": sig["price"], "sma5": sig["sma5"],
            "sma20": sig["sma20"], "rsi14": sig["rsi14"],
            "vol_ratio": sig["vol_ratio"], "price_dev": sig["price_dev"],
            "prev_return": sig["prev_return"],
            "quantity": effective_qty, "order_id": order_id,
            "order_status": order_status, "mode": mode, "interval": interval,
            "pnl_usd": log_pnl_usd,
        })

    state["positions"] = positions
    state["total_trades"] = total_trades
    state["total_pnl_usd"] = total_pnl
    state["daily_pnl_usd"] = daily_pnl
    state["cooldown_until"] = cooldown_until
    state["last_signals"] = last_signals
    state["peak_pnl"] = peak_pnl
    state["max_drawdown_usd"] = max_drawdown
    state["commission_paid_usd"] = commission_paid
    state["last_run_jst"] = _now_jst_str()
    state["open_count"] = len(positions)
    state["symbols"] = symbols
    state["interval"] = interval
    save_state(state)

    print()
    print(f"[shadow] open={list(positions.keys()) or 'none'}"
          f"  trades={total_trades}  cumPnL=${total_pnl:+.2f}"
          f"  peak=${peak_pnl:+.2f}  maxDD=${max_drawdown:.2f}")
    print(f"[shadow] log → {_log_path()}")


# ── Backtest (C) ──────────────────────────────────────────────────────────────

def run_backtest(
    symbols: List[str],
    days: int = 30,
    quantity: int = 1,
    interval: str = "1h",
    stop_pct: float = DEFAULT_STOP_PCT,
    tp_pct: float = DEFAULT_TP_PCT,
    both_sides: bool = False,
) -> None:
    """Simulate SMA5/SMA20+RSI+StopLoss signal over the last N days of historical data."""
    try:
        import yfinance as yf  # type: ignore
    except ImportError:
        print("[backtest] yfinance not installed. Run: pip3 install yfinance", file=sys.stderr)
        return

    warmup = 35
    fetch_days = days + warmup
    bt_log = REVIEW_OUT / f"backtest_{_day8()}_{interval}.csv"
    REVIEW_OUT.mkdir(parents=True, exist_ok=True)

    total_trades = 0
    total_pnl = 0.0
    wins = 0
    all_rows: List[Dict[str, Any]] = []

    tp_str = f"+{tp_pct:.0%}" if tp_pct > 0 else "off"
    print(f"[backtest] interval={interval}  days={days}  stop={stop_pct:.0%}  tp={tp_str}  symbols={symbols}")
    print()

    for symbol in symbols:
        try:
            df = yf.Ticker(symbol).history(period=f"{fetch_days}d", interval=interval)
        except Exception as exc:
            print(f"  [{symbol}] fetch error: {exc}", file=sys.stderr)
            continue
        if df is None or len(df) < warmup + 2:
            print(f"  [{symbol}] insufficient data ({len(df) if df is not None else 0} bars) — skipped")
            continue

        closes = [float(v) for v in df["Close"].values]
        volumes = [float(v) for v in df["Volume"].values]
        timestamps = list(df.index)

        position: Optional[Dict[str, Any]] = None
        sym_trades = 0
        sym_pnl = 0.0
        sym_wins = 0

        for i in range(20, len(closes)):
            cl_win = closes[:i + 1]
            vol_win = volumes[:i + 1]
            price = cl_win[-1]
            sma5 = round(_sma(cl_win, 5), 4)
            sma20 = round(_sma(cl_win, 20), 4)
            rsi = _rsi(cl_win)
            vr = _vol_ratio(vol_win)
            pd_ = _price_dev(price, sma20)
            pr = _prev_return(cl_win)
            ts = str(timestamps[i])[:19]

            if position is None:
                if sma5 > sma20 and rsi < 65:
                    position = {
                        "side": "LONG",
                        "entry_price": price,
                        "stop_price": price * (1 + stop_pct) if stop_pct < 0 else None,
                        "tp_price": price * (1 + tp_pct) if tp_pct > 0 else None,
                    }
                    all_rows.append({
                        "timestamp_jst": ts, "symbol": symbol, "action": "BUY",
                        "reason": "SMA5_ABOVE_SMA20", "price": round(price, 4),
                        "sma5": sma5, "sma20": sma20, "rsi14": rsi,
                        "vol_ratio": vr, "price_dev": pd_, "prev_return": pr,
                        "quantity": quantity, "order_id": None,
                        "order_status": "BACKTEST", "mode": "BACKTEST", "interval": interval,
                    })
                elif both_sides and sma5 < sma20 and rsi > 50:
                    # AH: SHORT entry in backtest
                    position = {
                        "side": "SHORT",
                        "entry_price": price,
                        "stop_price": price * (1 + abs(stop_pct)) if stop_pct < 0 else None,
                        "tp_price": price * (1 - tp_pct) if tp_pct > 0 else None,
                    }
                    all_rows.append({
                        "timestamp_jst": ts, "symbol": symbol, "action": "SHORT",
                        "reason": "SMA5_BELOW_SMA20", "price": round(price, 4),
                        "sma5": sma5, "sma20": sma20, "rsi14": rsi,
                        "vol_ratio": vr, "price_dev": pd_, "prev_return": pr,
                        "quantity": quantity, "order_id": None,
                        "order_status": "BACKTEST", "mode": "BACKTEST", "interval": interval,
                    })
            else:
                pos_side_bt = position.get("side", "LONG")

                if pos_side_bt == "LONG":
                    # X: breakeven SL activation in backtest (LONG)
                    if (tp_pct > 0 and stop_pct < 0 and not position.get("breakeven_activated")
                            and position.get("tp_price")):
                        partial_threshold = position["entry_price"] * (1 + tp_pct * 0.5)
                        if price >= partial_threshold:
                            position["stop_price"] = position["entry_price"]
                            position["breakeven_activated"] = True

                    exit_reason = None
                    if stop_pct < 0 and position.get("stop_price") is not None and price <= position["stop_price"]:
                        exit_reason = "BREAKEVEN_SL" if position.get("breakeven_activated") else "STOP_LOSS"
                    elif tp_pct > 0 and position.get("tp_price") is not None and price >= position["tp_price"]:
                        exit_reason = "TAKE_PROFIT"
                    elif sma5 < sma20:
                        exit_reason = "SMA5_CROSS_DOWN"
                    elif rsi > 75:
                        exit_reason = "RSI_OVERBOUGHT"

                    if exit_reason:
                        pnl = round((price - position["entry_price"]) * quantity, 2)
                        sym_pnl += pnl
                        sym_trades += 1
                        if pnl > 0:
                            sym_wins += 1
                        all_rows.append({
                            "timestamp_jst": ts, "symbol": symbol, "action": "SELL",
                            "reason": exit_reason, "price": round(price, 4),
                            "sma5": sma5, "sma20": sma20, "rsi14": rsi,
                            "vol_ratio": vr, "price_dev": pd_, "prev_return": pr,
                            "quantity": quantity, "order_id": None,
                            "order_status": "BACKTEST", "mode": "BACKTEST", "interval": interval,
                            "pnl_usd": pnl,
                        })
                        position = None

                else:
                    # AH: SHORT position exit in backtest
                    if (tp_pct > 0 and stop_pct < 0 and not position.get("breakeven_activated")
                            and position.get("tp_price")):
                        partial_threshold = position["entry_price"] * (1 - tp_pct * 0.5)
                        if price <= partial_threshold:
                            position["stop_price"] = position["entry_price"]
                            position["breakeven_activated"] = True

                    exit_reason = None
                    if stop_pct < 0 and position.get("stop_price") is not None and price >= position["stop_price"]:
                        exit_reason = "BREAKEVEN_SL" if position.get("breakeven_activated") else "STOP_LOSS"
                    elif tp_pct > 0 and position.get("tp_price") is not None and price <= position["tp_price"]:
                        exit_reason = "TAKE_PROFIT"
                    elif sma5 > sma20:
                        exit_reason = "SMA5_CROSS_UP"
                    elif rsi < 25:
                        exit_reason = "RSI_OVERSOLD"

                    if exit_reason:
                        pnl = round((position["entry_price"] - price) * quantity, 2)
                        sym_pnl += pnl
                        sym_trades += 1
                        if pnl > 0:
                            sym_wins += 1
                        all_rows.append({
                            "timestamp_jst": ts, "symbol": symbol, "action": "COVER",
                            "reason": exit_reason, "price": round(price, 4),
                            "sma5": sma5, "sma20": sma20, "rsi14": rsi,
                            "vol_ratio": vr, "price_dev": pd_, "prev_return": pr,
                            "quantity": quantity, "order_id": None,
                            "order_status": "BACKTEST", "mode": "BACKTEST", "interval": interval,
                            "pnl_usd": pnl,
                        })
                        position = None

        if position is not None:
            price = closes[-1]
            pos_side_bt = position.get("side", "LONG")
            if pos_side_bt == "LONG":
                pnl = round((price - position["entry_price"]) * quantity, 2)
                exit_action = "SELL"
            else:
                pnl = round((position["entry_price"] - price) * quantity, 2)
                exit_action = "COVER"
            sym_pnl += pnl
            sym_trades += 1
            if pnl > 0:
                sym_wins += 1
            all_rows.append({
                "timestamp_jst": str(timestamps[-1])[:19], "symbol": symbol, "action": exit_action,
                "reason": "END_OF_DATA", "price": round(price, 4),
                "sma5": 0, "sma20": 0, "rsi14": 0,
                "vol_ratio": 1.0, "price_dev": 0.0, "prev_return": 0.0,
                "quantity": quantity, "order_id": None,
                "order_status": "BACKTEST_CLOSE", "mode": "BACKTEST", "interval": interval,
                "pnl_usd": pnl,
            })

        wr_str = f"{sym_wins/sym_trades*100:.0f}%" if sym_trades > 0 else "—"
        print(f"  [{symbol}]  trades={sym_trades}  wins={sym_wins}  WR={wr_str}"
              f"  PnL=${sym_pnl:+.2f}")
        total_trades += sym_trades
        total_pnl += sym_pnl
        wins += sym_wins

    print()
    overall_wr = f"{wins/total_trades*100:.1f}%" if total_trades > 0 else "—"
    print(f"[backtest] TOTAL  trades={total_trades}  wins={wins}"
          f"  WR={overall_wr}  PnL=${total_pnl:+.2f}")

    bt_headers = CSV_HEADERS + ["pnl_usd"]
    with bt_log.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=bt_headers, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)
    print(f"[backtest] log → {bt_log}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Stock shadow paper trading bot")
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--execute", action="store_true", help="Place paper orders via Paper API")
    ap.add_argument("--paper-api", default=DEFAULT_PAPER_API)
    ap.add_argument("--quantity", type=int, default=DEFAULT_QUANTITY, help="Shares per order")
    ap.add_argument("--interval", default=DEFAULT_INTERVAL, choices=["1h", "1d"],
                    help="Bar interval: 1h (hourly, default) or 1d (daily)")
    ap.add_argument("--no-hold-log", action="store_true",
                    help="Skip logging HOLD states to CSV")
    ap.add_argument("--ml-filter", action="store_true",
                    help="Gate BUY signals with ML model (requires stock_ml_train.py)")
    ap.add_argument("--ml-min-prob", type=float, default=0.55,
                    help="Min ML probability to allow BUY (default: 0.55)")
    ap.add_argument("--mtf-filter", action="store_true",
                    help="L: require bullish daily SMA5>SMA20 before 1h BUY entry")
    ap.add_argument("--stop-pct", type=float, default=DEFAULT_STOP_PCT,
                    help=f"Q: stop loss fraction from entry (default: {DEFAULT_STOP_PCT}, 0=disabled)")
    ap.add_argument("--tp-pct", type=float, default=DEFAULT_TP_PCT,
                    help=f"U: take profit fraction from entry (default: {DEFAULT_TP_PCT}, 0=disabled)")
    ap.add_argument("--max-positions", type=int, default=DEFAULT_MAX_POSITIONS,
                    help=f"Max concurrent open positions (default: {DEFAULT_MAX_POSITIONS})")
    ap.add_argument("--daily-loss-limit", type=float, default=DEFAULT_DAILY_LOSS_LIMIT,
                    help=f"Daily loss limit in USD (default: {DEFAULT_DAILY_LOSS_LIMIT}, 0=disabled)")
    ap.add_argument("--no-commission", action="store_true",
                    help="Disable commission deduction from P&L")
    ap.add_argument("--risk-per-trade", type=float, default=DEFAULT_RISK_PER_TRADE_USD,
                    help=f"AC: ATR-based sizing — target risk per trade in USD (0=use fixed --quantity)")
    ap.add_argument("--both-sides", action="store_true",
                    help="AH: also enter SHORT positions (SMA5<SMA20 and RSI>50)")
    ap.add_argument("--backtest", action="store_true",
                    help="Run backtest over historical data instead of live signal")
    ap.add_argument("--backtest-days", type=int, default=30,
                    help="Number of days to backtest (default: 30)")
    args = ap.parse_args()

    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    commission_val = 0.0 if args.no_commission else COMMISSION_PER_ORDER_USD

    if args.backtest:
        run_backtest(syms, days=args.backtest_days, quantity=args.quantity,
                     interval=args.interval, stop_pct=args.stop_pct, tp_pct=args.tp_pct,
                     both_sides=args.both_sides)
    else:
        run(
            syms,
            execute=args.execute,
            paper_api=args.paper_api,
            quantity=args.quantity,
            interval=args.interval,
            log_hold=not args.no_hold_log,
            ml_filter=args.ml_filter,
            ml_min_prob=args.ml_min_prob,
            mtf_filter=args.mtf_filter,
            stop_pct=args.stop_pct,
            tp_pct=args.tp_pct,
            max_positions=args.max_positions,
            daily_loss_limit=args.daily_loss_limit,
            commission=commission_val,
            risk_per_trade=args.risk_per_trade,
            both_sides=args.both_sides,
        )
