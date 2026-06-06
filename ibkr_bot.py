#!/usr/bin/env python3
"""Ouroboros IBKR US Stock Paper Trading Bot

Connects to IB Gateway (port 7497=paper, port 7496=live) and trades US stocks.
Strategy: SMA fast/slow crossover on 1-min bars.
Writes trade logs compatible with Ouroboros log format (pos_id, current_fav, best_fav).
Runs in a 60-second loop; market-hours-aware (US Eastern Time).
"""
from __future__ import annotations

import csv
import json
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

IBKR_BOT_VERSION = "2026.06.04.1"

MAIN_DIR = Path(__file__).resolve().parent
LOGS_DIR = MAIN_DIR.parent / "logs"
CONTROL_CSV = MAIN_DIR / "IBKR_CONTROL.csv"
STATE_FILE = MAIN_DIR / "ibkr_state.json"
SECRETS_TOML = MAIN_DIR / ".streamlit" / "secrets.toml"

LOG_COLUMNS = ["time", "side", "result", "lot", "price", "trend", "note"]

# 投資円卓会議エンジン（任意 / ibkr_council_enabled=1 で有効）
try:
    import investor_council as _council  # type: ignore
except Exception:  # pragma: no cover - 円卓会議が無い環境でも稼働継続
    _council = None

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    _ET_ZONE: Any = ZoneInfo("America/New_York")
    def _now_et() -> datetime:
        return datetime.now(_ET_ZONE).replace(tzinfo=None)
except Exception:
    def _now_et() -> datetime:  # type: ignore[misc]
        return datetime.utcnow() + timedelta(hours=-4)  # EDT fallback

JST = timezone(timedelta(hours=9))

def _now_jst() -> datetime:
    return datetime.now(JST).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Config / state helpers
# ---------------------------------------------------------------------------

def _load_control() -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        for row in csv.DictReader(open(CONTROL_CSV, encoding="utf-8-sig")):
            k = str(row.get("key", "") or "").strip()
            if k:
                out[k] = str(row.get("value", "") or "").strip()
    except Exception:
        pass
    return out


def _ctrl_int(ctrl: Dict, key: str, default: int) -> int:
    try:
        return int(ctrl.get(key, default))
    except Exception:
        return default


def _ctrl_float(ctrl: Dict, key: str, default: float) -> float:
    try:
        return float(ctrl.get(key, default))
    except Exception:
        return default


def _ctrl_bool(ctrl: Dict, key: str, default: bool = False) -> bool:
    v = str(ctrl.get(key, "")).strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _load_state() -> Dict[str, Any]:
    try:
        v = json.loads(STATE_FILE.read_text("utf-8"))
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")


def _read_toml_str(key: str) -> str:
    if not SECRETS_TOML.exists():
        return ""
    for line in SECRETS_TOML.read_text("utf-8").splitlines():
        line = line.strip()
        if line.startswith(key):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            return v if v and v != "***MASKED***" else ""
    return ""


# ---------------------------------------------------------------------------
# ntfy
# ---------------------------------------------------------------------------

def _is_live_mode(ctrl: dict) -> bool:
    """Return True when connected to live IB Gateway (port 7496)."""
    try:
        return int(ctrl.get("ibkr_port", 7497)) == 7496
    except Exception:
        return False


def _send_ntfy(title: str, body: str) -> None:
    url = (_read_toml_str("ntfy_stock_topic_url") or _read_toml_str("ntfy_topic_url"))
    if not url:
        return
    bearer = _read_toml_str("ntfy_bearer_token")
    safe_title = title.encode("ascii", errors="replace").decode("ascii")
    headers: Dict[str, str] = {
        "Content-Type": "text/plain; charset=utf-8",
        "Title": safe_title,
        "Priority": "default",
        "Tags": "chart_increasing",
    }
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        req = urllib.request.Request(url, data=body.encode("utf-8"),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8.0):
            pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Trade log
# ---------------------------------------------------------------------------

def _log_path(day_str: str) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR / f"ibkr_trade_log_{day_str}.csv"


def _append_trade_log(row: Dict[str, Any]) -> None:
    day = _now_jst().strftime("%Y%m%d")
    path = _log_path(day)
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLUMNS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in LOG_COLUMNS})


def _gen_pos_id(side: str) -> str:
    t = _now_jst()
    return t.strftime(f"%Y%m%d-%H%M%S-{side}-001")


# ---------------------------------------------------------------------------
# Sector map — セクター相関ガード用
# ---------------------------------------------------------------------------

_SECTOR_MAP: Dict[str, str] = {
    # Tech
    "AAPL": "tech", "MSFT": "tech", "NVDA": "tech", "AMD": "tech", "AVGO": "tech",
    "GOOGL": "tech", "GOOG": "tech", "META": "tech", "CRM": "tech", "MU": "tech", "PLTR": "tech",
    # Consumer/Growth
    "TSLA": "consumer", "AMZN": "consumer", "NFLX": "consumer", "BKNG": "consumer", "F": "auto",
    # Finance
    "JPM": "finance", "GS": "finance", "BAC": "finance", "V": "finance", "MA": "finance",
    # Crypto-adjacent
    "COIN": "crypto",
    # ETF (treat as independent)
    "QQQ": "etf_qqq", "SPY": "etf_spy", "IWM": "etf_iwm",
    # Energy
    "XOM": "energy", "CVX": "energy", "OXY": "energy",
    # Healthcare
    "UNH": "health", "LLY": "health", "JNJ": "health", "ABBV": "health",
    # Consumer Staples
    "COST": "staples", "WMT": "staples", "PG": "staples",
    # Industrials
    "CAT": "industrial", "RTX": "industrial", "DE": "industrial",
    # Materials
    "FCX": "materials", "NEM": "materials",
    # Utilities
    "NEE": "utilities",
    # Real Estate
    "AMT": "realestate",
}


def _sector_of(symbol: str) -> str:
    return _SECTOR_MAP.get(symbol.upper(), "other")


def _has_sector_conflict(symbol: str, open_positions: Dict) -> bool:
    """Return True if any open position shares the same sector as symbol."""
    sec = _sector_of(symbol)
    if sec in ("other", "etf_qqq", "etf_spy", "etf_iwm"):
        return False  # ETF と不明銘柄は競合扱いしない
    for sym in open_positions:
        if _sector_of(sym) == sec:
            return True
    return False


# ---------------------------------------------------------------------------
# Chart AI — LightGBM シグナルゲート
# ---------------------------------------------------------------------------

CHART_AI_SCORE_PATH = MAIN_DIR / "local_ai" / "chart_ai" / "chart_ai_score.json"
_CHART_AI_STALE_SEC = 86400 * 2  # 2日以上古いスコアは無視


def _chart_ai_gate(symbol: str, signal: str, ctrl: Dict) -> Optional[str]:
    """
    Chart AI スコアファイルを読んでシグナルの方向を確認する。
    ibkr_chart_ai_min_prob: この確率以上の逆張りシグナルを BLOCK（デフォルト 0.80）
    ibkr_chart_ai_enabled: 0=無効(デフォルト) 1=有効

    Returns: None=通過  文字列=ブロック理由
    """
    if not _ctrl_int(ctrl, "ibkr_chart_ai_enabled", 0):
        return None

    if not CHART_AI_SCORE_PATH.exists():
        return None  # スコアなし → パス

    try:
        with open(CHART_AI_SCORE_PATH, "r") as f:
            data = json.load(f)
    except Exception:
        return None

    # スコアの鮮度チェック
    generated_at_str = data.get("generated_at", "")
    if generated_at_str:
        try:
            import re as _re
            ts_str = _re.sub(r"[+-]\d{2}:\d{2}$", "+00:00", generated_at_str.replace("+09:00", "+09:00"))
            from datetime import timezone as _tz
            generated_dt = datetime.fromisoformat(generated_at_str)
            if generated_dt.tzinfo is None:
                generated_dt = generated_dt.replace(tzinfo=timezone.utc)
            age_sec = (datetime.now(tz=timezone.utc) - generated_dt.astimezone(timezone.utc)).total_seconds()
            if age_sec > _CHART_AI_STALE_SEC:
                return None  # 古すぎ → 無視
        except Exception:
            pass

    scores = data.get("scores", {})
    sc = scores.get(symbol)
    if sc is None:
        return None  # このシンボルのスコアなし → パス

    min_prob = _ctrl_float(ctrl, "ibkr_chart_ai_min_prob", 0.80)
    ai_signal  = sc.get("signal", "NEUTRAL")
    long_prob  = float(sc.get("long_prob", 0.5))
    short_prob = float(sc.get("short_prob", 0.5))

    # BUYシグナルなのにAIがSHORT高確率 → ブロック
    if signal == "BUY" and short_prob >= min_prob:
        return (f"CHART_AI_BLOCK BUY {symbol}: AI SHORT {short_prob:.0%} "
                f">= threshold {min_prob:.0%} [signal={ai_signal}]")

    # SELLシグナルなのにAIがLONG高確率 → ブロック
    if signal == "SELL" and long_prob >= min_prob:
        return (f"CHART_AI_BLOCK SELL {symbol}: AI LONG {long_prob:.0%} "
                f">= threshold {min_prob:.0%} [signal={ai_signal}]")

    return None  # 通過


# ---------------------------------------------------------------------------
# VIX — market fear gate (PDF1: VIX恐怖指数ゲート)
# ---------------------------------------------------------------------------

def _fetch_vix(state: Dict) -> Optional[float]:
    """VIX を Yahoo Finance から取得する（30分キャッシュ）。

    VIX > ibkr_vix_block_threshold のときエントリーをブロックする。
    API 失敗時は前回キャッシュにフォールバック（None なら無視）。
    """
    now_ts = time.time()
    cached_ts = float(state.get("_vix_fetched_ts", 0))
    if now_ts - cached_ts < 1800 and "_vix_value" in state:
        return float(state["_vix_value"])
    try:
        import json as _vix_json
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as _r:
            _data = _vix_json.loads(_r.read().decode("utf-8"))
        vix = float(_data["chart"]["result"][0]["meta"]["regularMarketPrice"])
        state["_vix_value"] = vix
        state["_vix_fetched_ts"] = now_ts
        return vix
    except Exception:
        if "_vix_value" in state:
            return float(state["_vix_value"])
        return None


# ---------------------------------------------------------------------------
# Signal / trend
# ---------------------------------------------------------------------------

def _compute_sma_signal(
    bars: List[Dict[str, Any]], fast_n: int, slow_n: int
) -> Optional[str]:
    """Returns 'BUY', 'SELL', or None based on SMA crossover on close prices."""
    closes = [float(b["close"]) for b in bars if float(b.get("close", 0)) > 0]
    if len(closes) < slow_n + 2:
        return None
    prev_fast = sum(closes[-(fast_n + 1):-1]) / fast_n
    prev_slow = sum(closes[-(slow_n + 1):-1]) / slow_n
    now_fast = sum(closes[-fast_n:]) / fast_n
    now_slow = sum(closes[-slow_n:]) / slow_n
    if prev_fast <= prev_slow and now_fast > now_slow:
        return "BUY"
    if prev_fast >= prev_slow and now_fast < now_slow:
        return "SELL"
    return None


def _compute_sma_divergence(
    bars: List[Dict[str, Any]], fast_n: int, slow_n: int
) -> Optional[float]:
    """Returns current fast/slow SMA divergence as % of slow MA. Positive = fast above slow."""
    closes = [float(b["close"]) for b in bars if float(b.get("close", 0)) > 0]
    if len(closes) < slow_n:
        return None
    now_fast = sum(closes[-fast_n:]) / fast_n
    now_slow = sum(closes[-slow_n:]) / slow_n
    if now_slow <= 0:
        return None
    return (now_fast - now_slow) / now_slow * 100


def _momentum_score(bars: List[Dict[str, Any]]) -> float:
    """Score a symbol's momentum: 5-day return × (1 + ATR/price ratio).
    Higher = stronger directional move with volatility."""
    closes = [float(b["close"]) for b in bars if float(b.get("close", 0)) > 0]
    if len(closes) < 2:
        return 0.0
    lookback = min(len(closes) - 1, 75)  # ~75 min = roughly 1.5h of trading
    ret = (closes[-1] - closes[-lookback]) / closes[-lookback] * 100 if closes[-lookback] > 0 else 0.0
    atr = _compute_atr(bars) or 0.0
    price = closes[-1]
    atr_ratio = atr / price * 100 if price > 0 else 0.0
    # Favour directional move; penalise low-volatility (boring) symbols
    return abs(ret) * (1.0 + atr_ratio)


def _trend_label(bars: List[Dict[str, Any]], n: int = 20) -> str:
    closes = [float(b["close"]) for b in bars if float(b.get("close", 0)) > 0]
    if len(closes) < n + 1:
        return "flat"
    return "up" if closes[-1] > closes[-n - 1] else ("down" if closes[-1] < closes[-n - 1] else "flat")


def _compute_vwap(bars: List[Dict[str, Any]]) -> Optional[float]:
    """VWAP from 1-min bars (cumulative typical price × volume)."""
    cum_tp_vol = 0.0
    cum_vol = 0.0
    for b in bars:
        h = float(b.get("high", 0) or 0)
        lw = float(b.get("low", 0) or 0)
        c = float(b.get("close", 0) or 0)
        v = float(b.get("volume", 0) or 0)
        if c > 0 and v > 0:
            cum_tp_vol += ((h + lw + c) / 3) * v
            cum_vol += v
    return cum_tp_vol / cum_vol if cum_vol > 0 else None


def _compute_atr(bars: List[Dict[str, Any]], n: int = 14) -> Optional[float]:
    """Average True Range over last n bars."""
    valid = [b for b in bars if float(b.get("close", 0) or 0) > 0]
    trs = []
    for i in range(1, len(valid)):
        h = float(valid[i].get("high", 0) or 0)
        lw = float(valid[i].get("low", 0) or 0)
        prev_c = float(valid[i - 1].get("close", 0) or 0)
        trs.append(max(h - lw, abs(h - prev_c), abs(lw - prev_c)))
    if len(trs) < n:
        return None
    return sum(trs[-n:]) / n


def _detect_candle_pattern(bars: List[Dict[str, Any]]) -> Optional[str]:
    """Detect last 2-bar engulfing pattern. Returns 'bullish', 'bearish', or None."""
    valid = [b for b in bars if float(b.get("close", 0) or 0) > 0]
    if len(valid) < 2:
        return None
    prev, curr = valid[-2], valid[-1]
    p_o = float(prev.get("open", 0) or 0)
    p_c = float(prev.get("close", 0) or 0)
    c_o = float(curr.get("open", 0) or 0)
    c_c = float(curr.get("close", 0) or 0)
    c_h = float(curr.get("high", 0) or 0)
    c_l = float(curr.get("low", 0) or 0)
    body = abs(c_c - c_o)
    wick = (c_h - c_l) if c_h > c_l else 0
    if wick > 0 and body / wick < 0.1:
        return None  # doji = indecision
    if p_c < p_o and c_c > c_o and c_o <= p_c and c_c >= p_o:
        return "bullish"
    if p_c > p_o and c_c < c_o and c_o >= p_c and c_c <= p_o:
        return "bearish"
    return None


def _volume_surge(bars: List[Dict[str, Any]], n: int = 20) -> bool:
    """True if current bar volume > n-bar average volume."""
    vols = [float(b.get("volume", 0) or 0) for b in bars if float(b.get("close", 0) or 0) > 0]
    if len(vols) < n + 1:
        return True  # not enough data, don't block
    avg = sum(vols[-(n + 1):-1]) / n
    return vols[-1] > avg if avg > 0 else True


def _daily_move_pct(bars: List[Dict[str, Any]]) -> Optional[float]:
    """Return intraday move % from first bar open to current price. Positive = up."""
    valid = [b for b in bars if float(b.get("close", 0) or 0) > 0]
    if len(valid) < 2:
        return None
    day_open = float(valid[0].get("open", 0) or 0)
    current = float(valid[-1].get("close", 0) or 0)
    if day_open <= 0:
        return None
    return (current - day_open) / day_open * 100


# ---------------------------------------------------------------------------
# Market hours (ET)
# ---------------------------------------------------------------------------

def _is_market_hours(ctrl: Dict) -> bool:
    now = _now_et()
    if now.weekday() >= 5:  # Sat/Sun
        return False
    open_h = _ctrl_int(ctrl, "ibkr_start_hour_et", 9)
    open_m = _ctrl_int(ctrl, "ibkr_start_min_et", 35)
    close_h = _ctrl_int(ctrl, "ibkr_end_hour_et", 15)
    close_m = _ctrl_int(ctrl, "ibkr_end_min_et", 50)
    now_min = now.hour * 60 + now.minute
    return open_h * 60 + open_m <= now_min <= close_h * 60 + close_m


def _is_eod_close_time(ctrl: Dict) -> bool:
    now = _now_et()
    eod_h = _ctrl_int(ctrl, "ibkr_eod_close_hour_et", 15)
    eod_m = _ctrl_int(ctrl, "ibkr_eod_close_min_et", 55)
    # Also covers restart-after-EOD: hour > eod_h means we're past the window
    return (now.hour == eod_h and now.minute >= eod_m) or now.hour > eod_h


def _is_stale_position(open_pos: Dict) -> bool:
    """True if position was entered on a previous calendar day (ET).
    Catches weekend-straddling and crash-recovery cases."""
    entry_time_str = open_pos.get("entry_time", "")
    if not entry_time_str:
        return False
    try:
        entry_dt = datetime.fromisoformat(entry_time_str)
        # entry_time is stored in JST; convert to ET date for comparison
        entry_et = entry_dt.astimezone(_ET_ZONE) if hasattr(_ET_ZONE, 'key') else entry_dt
        return entry_et.date() < _now_et().date()
    except Exception:
        return False


def _cancel_protective_stop(adapter: Any, pos: Dict) -> None:
    """ポジションに紐づく防御逆指値（ブローカー側STP）を取り消す。二重約定防止。"""
    sid = pos.get("protective_stop_order_id")
    if not sid:
        return
    try:
        adapter.cancel_order(int(sid))
        print(f"[ibkr_bot] protective stop {sid} cancelled for {pos.get('symbol')}")
    except Exception as e:
        print(f"[ibkr_bot] cancel protective stop error {sid}: {e}")


# ---------------------------------------------------------------------------
# Core trading logic (one loop iteration)
# ---------------------------------------------------------------------------

def _select_top_symbols(adapter: Any, ctrl: Dict, state: Dict) -> List[str]:
    """Morning scan: score all ibkr_monitor_symbols by momentum, return top N.

    ibkr_symbol_select_mode=momentum  → scan & rank (default)
    ibkr_symbol_select_mode=fixed     → return [ibkr_trade_symbol] only
    ibkr_symbol_select_top_n          → how many top symbols to keep (default 8)
    Result cached in state["_intraday_symbols"] until next ET trading day.
    """
    base_symbol = ctrl.get("ibkr_trade_symbol", "QQQ").upper()
    top_n = _ctrl_int(ctrl, "ibkr_symbol_select_top_n", 8)

    if ctrl.get("ibkr_symbol_select_mode", "fixed").lower() != "momentum":
        return [base_symbol]

    today_et = _now_et().strftime("%Y%m%d")
    cached = state.get("_intraday_symbols")
    if state.get("_intraday_symbols_date") == today_et and isinstance(cached, list) and cached:
        return cached

    raw = ctrl.get("ibkr_monitor_symbols", base_symbol)
    candidates = [s.strip().strip('"').upper() for s in raw.split(",") if s.strip()]
    if not candidates:
        return [base_symbol]

    scored: List[tuple] = []
    for sym in candidates:
        try:
            bars = adapter.get_historical_bars(sym, bar_size="1 min", duration="1 D")
            score = _momentum_score(bars)
            scored.append((score, sym))
            print(f"[ibkr_bot] symbol_scan {sym} score={score:.3f}")
        except Exception as e:
            print(f"[ibkr_bot] symbol_scan {sym} error: {e}")

    if not scored:
        return [base_symbol]

    scored.sort(reverse=True)
    top = [sym for _, sym in scored[:top_n]]
    state["_intraday_symbols"] = top
    state["_intraday_symbols_date"] = today_et
    print(f"[ibkr_bot] today's top {top_n} symbols: {top}")
    return top


def _get_symbols(ctrl: Dict, state: Optional[Dict] = None) -> List[str]:
    """Return symbols to scan for entries.

    If state contains cached intraday symbols from morning scan, use those.
    Otherwise fall back to full ibkr_monitor_symbols list.
    """
    if state is not None:
        cached = state.get("_intraday_symbols")
        if isinstance(cached, list) and cached:
            return cached
    raw = ctrl.get("ibkr_monitor_symbols", ctrl.get("ibkr_trade_symbol", "QQQ"))
    syms = [s.strip().strip('"').upper() for s in str(raw).split(",") if s.strip()]
    return syms if syms else ["QQQ"]


def run_once(adapter: Any, ctrl: Dict, state: Dict) -> Dict:
    shares = _ctrl_int(ctrl, "ibkr_shares", 1)
    tp_pct = _ctrl_float(ctrl, "ibkr_tp_pct", 0.5)
    sl_pct = _ctrl_float(ctrl, "ibkr_sl_pct", -0.25)
    fast_n = _ctrl_int(ctrl, "ibkr_signal_fast_n", 5)
    slow_n = _ctrl_int(ctrl, "ibkr_signal_slow_n", 20)
    trade_side = ctrl.get("ibkr_trade_side", "BOTH").upper()
    daily_loss_limit = _ctrl_float(ctrl, "ibkr_daily_loss_limit_usd", -500.0)
    max_trades = _ctrl_int(ctrl, "ibkr_max_trades_per_day", 5)
    vix_block_threshold = _ctrl_float(ctrl, "ibkr_vix_block_threshold", 0.0)
    sma_min_div = _ctrl_float(ctrl, "ibkr_sma_min_divergence_pct", 0.0)
    max_concurrent = _ctrl_int(ctrl, "ibkr_max_concurrent_positions", 1)

    today = _now_jst().strftime("%Y%m%d")
    if state.get("last_trade_day") != today:
        state["daily_realized_pnl_usd"] = 0.0
        state["daily_trade_count"] = 0
        state["loss_streak"] = 0          # 連敗カウントを日次リセット
        state["last_trade_day"] = today
        state.pop("_intraday_symbols", None)
        state.pop("_intraday_symbols_date", None)

    # 週次P&L: 月曜日(weekday=0)になったらリセット
    today_dt = _now_jst()
    week_start = (today_dt - timedelta(days=today_dt.weekday())).strftime("%Y%m%d")
    if state.get("weekly_start") != week_start:
        state["weekly_realized_pnl_usd"] = 0.0
        state["weekly_start"] = week_start

    # ── Morning symbol scan (once per day, during market hours) ───────────
    if (ctrl.get("ibkr_symbol_select_mode", "fixed").lower() == "momentum"
            and not state.get("_intraday_symbols")):
        _select_top_symbols(adapter, ctrl, state)

    # ── Migrate legacy open_pos → open_positions dict ─────────────────────
    if "open_positions" not in state:
        legacy = state.get("open_pos")
        state["open_positions"] = {}
        if legacy and legacy.get("bot_managed"):
            state["open_positions"][str(legacy["symbol"])] = legacy

    open_positions: Dict[str, Dict] = state["open_positions"]

    # ── 照合: ブローカー側で防御逆指値(STP)が約定しポジションが消えていないか ──
    #   消えていたら state を整合させ、二重発注（成行クローズ→逆建て）を防ぐ。
    if open_positions:
        try:
            broker_syms = {str(p.get("contract", {}).get("symbol", "")).upper()
                           for p in adapter.get_positions()
                           if abs(float(p.get("position") or 0)) > 0}
            open_order_ids = {int(o.get("order_id")) for o in adapter.get_open_orders()
                              if o.get("order_id") is not None}
            for sym in list(open_positions.keys()):
                if sym.upper() in broker_syms:
                    continue
                pos = open_positions[sym]
                # 誤発火ガード①: 建ててから90秒未満はIB反映遅延の可能性 → スキップ
                try:
                    age_s = (_now_jst() - datetime.fromisoformat(pos.get("entry_time", ""))).total_seconds()
                except Exception:
                    age_s = 9999
                if age_s < 90:
                    continue
                # 誤発火ガード②: 防御STPがまだオープン注文に在るならポジションも生存 → スキップ
                sid = pos.get("protective_stop_order_id")
                if sid is not None and int(sid) in open_order_ids:
                    continue
                entry_price = float(pos.get("entry_price", 0) or 0)
                stop_px = float(pos.get("stop_price") or entry_price)
                pos_side = str(pos.get("side", ""))
                pos_shares = int(pos.get("shares", shares))
                exit_ret = (((stop_px - entry_price) if pos_side == "BUY" else (entry_price - stop_px))
                            / entry_price * 100) if entry_price else 0.0
                pnl_usd = (stop_px - entry_price) * pos_shares * (1 if pos_side == "BUY" else -1)
                _mode = "LIVE" if _is_live_mode(ctrl) else "PAPER"
                _append_trade_log({
                    "time": _now_jst().strftime("%Y-%m-%d %H:%M:%S"),
                    "side": pos_side, "result": f"{_mode}_EXIT_STOPFILL",
                    "lot": pos_shares, "price": round(stop_px, 4), "trend": "",
                    "note": (f"pos_id={pos.get('pos_id','')} symbol={sym} entry_price={entry_price:.4f} "
                             f"current_fav={exit_ret:.4f} best_fav={float(pos.get('best_fav',0.0)):.4f} broker_stop_filled"),
                })
                state["daily_realized_pnl_usd"] = float(state.get("daily_realized_pnl_usd", 0.0)) + pnl_usd
                state["weekly_realized_pnl_usd"] = float(state.get("weekly_realized_pnl_usd", 0.0)) + pnl_usd
                if exit_ret < 0:
                    state["loss_streak"] = int(state.get("loss_streak", 0)) + 1
                _cancel_protective_stop(adapter, pos)  # 念のため残留STPを掃除
                _send_ntfy(
                    f"[IBKR] STOPFILL {sym} {pos_side}",
                    f"{sym} {pos_side} 防御逆指値約定\n"
                    f"入: ${entry_price:.2f}  出: ${stop_px:.2f}\n"
                    f"P&L: ${pnl_usd:+.2f}  ({exit_ret:+.3f}%)\n"
                    f"当日累計: ${state.get('daily_realized_pnl_usd', 0.0):+.2f}",
                )
                print(f"[ibkr_bot] STOPFILL reconciled {sym} @ ~${stop_px:.2f} ret={exit_ret:+.3f}%")
                del open_positions[sym]
        except Exception as e:
            print(f"[ibkr_bot] position reconcile error: {e}")

    # ── Phase 1: Manage each existing position (TP / SL / EOD / STALE) ──
    for sym in list(open_positions.keys()):
        pos = open_positions[sym]
        snap = adapter.get_stock_snapshot(sym)
        current_price: Optional[float] = snap.get("market_price") or snap.get("last") or snap.get("bid")
        has_price = bool(current_price and float(current_price) > 0)
        current_price = float(current_price) if has_price else None

        entry_price = float(pos["entry_price"])
        pos_side = str(pos["side"])
        pos_id = str(pos["pos_id"])
        pos_shares = int(pos.get("shares", shares))
        pos_tp = float(pos.get("tp_pct", tp_pct))
        pos_sl = float(pos.get("sl_pct", sl_pct))

        if has_price:
            ret_pct = (current_price - entry_price) / entry_price * 100 if pos_side == "BUY" else (entry_price - current_price) / entry_price * 100
            best_fav = max(float(pos.get("best_fav", 0.0)), ret_pct)
            pos["best_fav"] = best_fav
            open_positions[sym] = pos
        else:
            ret_pct = None
            best_fav = float(pos.get("best_fav", 0.0))

        # EOD/STALE は価格が取れなくても強制クローズ（成行は価格不要）。
        # これが翌日持ち越し→ドリフト膨張（MSFT -2.03%型）を断つ最重要修正。
        exit_reason: Optional[str] = None
        if _is_stale_position(pos):
            exit_reason = "STALE"
            print(f"[ibkr_bot] STALE position {pos_id} ({sym}), force closing")
        elif _is_eod_close_time(ctrl):
            exit_reason = "TIMEOUT"
        elif has_price and ret_pct >= pos_tp:
            exit_reason = "TP"
        elif has_price and ret_pct <= pos_sl:
            exit_reason = "SL"
        elif not has_price:
            print(f"[ibkr_bot] no price for {sym}, skip TP/SL check (EOD/STALE still enforced)")

        if exit_reason:
            _cancel_protective_stop(adapter, pos)  # 防御STPを先に取消（二重約定防止）
            close_action = "SELL" if pos_side == "BUY" else "BUY"
            fill_price = current_price if has_price else entry_price
            try:
                result = adapter.place_order(symbol=sym, action=close_action, quantity=pos_shares, order_type="MKT")
                fill_price = float(result.get("avg_fill_price") or fill_price)
            except Exception as e:
                print(f"[ibkr_bot] close order error {sym}: {e}")

            exit_ret = (fill_price - entry_price) / entry_price * 100 if pos_side == "BUY" else (entry_price - fill_price) / entry_price * 100
            _mode = "LIVE" if _is_live_mode(ctrl) else "PAPER"
            _append_trade_log({
                "time": _now_jst().strftime("%Y-%m-%d %H:%M:%S"),
                "side": pos_side,
                "result": f"{_mode}_EXIT_{exit_reason}",
                "lot": pos_shares,
                "price": round(fill_price, 4),
                "trend": "",
                "note": f"pos_id={pos_id} symbol={sym} entry_price={entry_price:.4f} current_fav={exit_ret:.4f} best_fav={best_fav:.4f}",
            })

            pnl_usd = (fill_price - entry_price) * pos_shares * (1 if pos_side == "BUY" else -1)
            state["daily_realized_pnl_usd"] = float(state.get("daily_realized_pnl_usd", 0.0)) + pnl_usd
            state["weekly_realized_pnl_usd"] = float(state.get("weekly_realized_pnl_usd", 0.0)) + pnl_usd
            del open_positions[sym]

            # 連敗カウント更新
            if exit_reason == "SL":
                state["loss_streak"] = int(state.get("loss_streak", 0)) + 1
            elif exit_reason == "TP":
                state["loss_streak"] = 0  # 勝ちでリセット

            if exit_reason == "SL":
                sl_cooldown_min = _ctrl_int(ctrl, "ibkr_sl_cooldown_min", 0)
                if sl_cooldown_min > 0:
                    cooldown_until = (_now_et() + timedelta(minutes=sl_cooldown_min)).strftime("%Y-%m-%dT%H:%M:%S")
                    state["sl_cooldown_until"] = cooldown_until
                    print(f"[ibkr_bot] SL_COOLDOWN: next entry blocked until {cooldown_until} ET")

            _send_ntfy(
                f"[IBKR] {exit_reason} {sym} {pos_side}",
                f"{sym} {pos_side} {exit_reason}\n入: ${entry_price:.2f}  出: ${fill_price:.2f}\nP&L: ${pnl_usd:+.2f}  ({exit_ret:+.3f}%)\n当日累計: ${state['daily_realized_pnl_usd']:+.2f}",
            )
            print(f"[ibkr_bot] EXIT {exit_reason} {sym} {pos_side} @ ${fill_price:.2f}  ret={exit_ret:+.3f}%")

    # ── Phase 2: Scan symbols for new entries ─────────────────────────────
    def _early_exit(reason: str = "") -> Dict:
        if reason:
            print(f"[ibkr_bot] {reason}")
        state["open_pos"] = next(iter(open_positions.values()), None)
        return state

    if float(state.get("daily_realized_pnl_usd", 0.0)) <= daily_loss_limit:
        return _early_exit("DAILY_LOSS_LIMIT reached, skip entry")
    if int(state.get("daily_trade_count", 0)) >= max_trades:
        return _early_exit()
    if not _is_market_hours(ctrl):
        return _early_exit()
    if len(open_positions) >= max_concurrent:
        return _early_exit()

    # ── 連敗ストップ ──────────────────────────────────────────────────────
    streak_max = _ctrl_int(ctrl, "ibkr_streak_stop_max_losses", 2)
    if int(state.get("loss_streak", 0)) >= streak_max:
        return _early_exit(f"STREAK_STOP: {state['loss_streak']} consecutive SL, max={streak_max}")

    # ── 週次損失上限 ──────────────────────────────────────────────────────
    weekly_loss_limit = _ctrl_float(ctrl, "ibkr_weekly_loss_limit_usd", -80.0)
    if float(state.get("weekly_realized_pnl_usd", 0.0)) <= weekly_loss_limit:
        return _early_exit(f"WEEKLY_LOSS_LIMIT reached: ${state.get('weekly_realized_pnl_usd', 0):.2f}")

    # Post-SL cooldown gate
    sl_cooldown_until_str = state.get("sl_cooldown_until", "")
    if sl_cooldown_until_str:
        try:
            cooldown_dt = datetime.fromisoformat(sl_cooldown_until_str)
            if _now_et() < cooldown_dt:
                remaining = int((cooldown_dt - _now_et()).total_seconds() / 60) + 1
                return _early_exit(f"SL_COOLDOWN active: {remaining}min remaining (until {sl_cooldown_until_str} ET)")
            else:
                state.pop("sl_cooldown_until", None)
        except Exception:
            state.pop("sl_cooldown_until", None)

    # VIX gate (fetched once; applies to all symbols)
    vix_val = _fetch_vix(state)
    vix_note = f"vix={vix_val:.1f}" if vix_val is not None else "vix=NA"
    if vix_block_threshold > 0 and vix_val is not None and vix_val >= vix_block_threshold:
        return _early_exit(f"VIX_BLOCK {vix_note} >= threshold={vix_block_threshold}")

    # Iterate candidate symbols; enter up to (max_concurrent - current) positions
    for symbol in _get_symbols(ctrl, state):
        if symbol in open_positions:
            continue
        if len(open_positions) >= max_concurrent:
            break
        if int(state.get("daily_trade_count", 0)) >= max_trades:
            break
        if _has_sector_conflict(symbol, open_positions):
            print(f"[ibkr_bot] SECTOR_CONFLICT {symbol} ({_sector_of(symbol)}) skipped — same sector already open")
            continue

        snap = adapter.get_stock_snapshot(symbol)
        current_price = snap.get("market_price") or snap.get("last") or snap.get("bid")
        if not current_price or float(current_price) <= 0:
            print(f"[ibkr_bot] no price for {symbol}, skip")
            continue
        current_price = float(current_price)

        try:
            bars = adapter.get_historical_bars(symbol, bar_size="1 min", duration="1 D")
        except Exception as e:
            print(f"[ibkr_bot] historical bars error {symbol}: {e}")
            continue

        signal = _compute_sma_signal(bars, fast_n, slow_n)
        sma_div = _compute_sma_divergence(bars, fast_n, slow_n)
        trend = _trend_label(bars)
        vwap = _compute_vwap(bars)
        atr = _compute_atr(bars)
        candle = _detect_candle_pattern(bars)
        daily_move = _daily_move_pct(bars)

        # ATR-based adaptive TP
        effective_tp = tp_pct
        atr_tp_multiplier = _ctrl_float(ctrl, "ibkr_atr_tp_multiplier", 0.0)
        if atr_tp_multiplier > 0 and atr is not None and current_price > 0:
            atr_as_pct = atr / current_price * 100
            atr_tp = atr_tp_multiplier * atr_as_pct
            if atr_tp > effective_tp:
                print(f"[ibkr_bot] ATR_TP {symbol}: {effective_tp:.3f}% → {atr_tp:.3f}%")
                effective_tp = round(atr_tp, 4)

        if trade_side == "BUY" and signal != "BUY":
            signal = None
        elif trade_side == "SELL" and signal != "SELL":
            signal = None

        if signal and sma_min_div > 0 and sma_div is not None and abs(sma_div) < sma_min_div:
            print(f"[ibkr_bot] SMA_DIV_BLOCK {symbol}: |div|={abs(sma_div):.4f}% < min={sma_min_div}%")
            signal = None

        if signal and _ctrl_int(ctrl, "ibkr_setup_vwap_enabled", 0) and vwap:
            if signal == "BUY" and current_price < vwap:
                print(f"[ibkr_bot] VWAP_BLOCK BUY {symbol}: price={current_price:.2f} < vwap={vwap:.2f}")
                signal = None
            elif signal == "SELL" and current_price > vwap:
                print(f"[ibkr_bot] VWAP_BLOCK SELL {symbol}: price={current_price:.2f} > vwap={vwap:.2f}")
                signal = None

        if signal == "BUY" and daily_move is not None and daily_move <= -1.5:
            print(f"[ibkr_bot] DAILY_MOVE_BLOCK BUY {symbol}: intraday={daily_move:.2f}%")
            signal = None

        if signal and _ctrl_int(ctrl, "ibkr_setup_volume_filter", 0) and not _volume_surge(bars):
            print(f"[ibkr_bot] VOL_BLOCK {symbol}: volume below 20-bar average")
            signal = None

        if signal:
            chart_ai_block = _chart_ai_gate(symbol, signal, ctrl)
            if chart_ai_block:
                print(f"[ibkr_bot] {chart_ai_block}")
                _append_trade_log({
                    "time": _now_jst().strftime("%Y-%m-%d %H:%M:%S"),
                    "side": signal,
                    "result": "CHART_AI_BLOCK",
                    "lot": 0,
                    "price": round(current_price, 4),
                    "trend": trend,
                    "note": chart_ai_block,
                })
                signal = None

        # 投資円卓会議ゲート（note記事ベース / ibkr_council_enabled=1 で有効）
        if signal and _council is not None and _ctrl_int(ctrl, "ibkr_council_enabled", 0):
            wk_pnl = float(state.get("weekly_realized_pnl_usd", 0.0))
            dd_stop = _ctrl_float(ctrl, "ibkr_council_weekly_dd_stop_usd", -12.0)
            target = _ctrl_float(ctrl, "ibkr_council_weekly_target_usd", 0.0)
            features = {
                "symbol": symbol, "signal": signal, "trend": trend,
                "price": current_price, "vwap": vwap, "atr": atr,
                "daily_move": daily_move, "tp_pct": effective_tp, "sl_pct": sl_pct,
                "vix": vix_val, "in_universe": True,
                "volume_surge": _volume_surge(bars),
                "week_dd_stopped": wk_pnl <= dd_stop,
                "week_target_hit": target > 0 and wk_pnl >= target,
            }
            council_res = _council.evaluate(features, ctrl)
            try:
                _council.write_report(council_res, {
                    "week": "", "week_realized_pnl_usd": round(wk_pnl, 2),
                    "week_dd_stopped": features["week_dd_stopped"],
                    "week_target_hit": features["week_target_hit"],
                    "dd_stop_usd": dd_stop, "target_usd": target})
            except Exception as _e:
                print(f"[ibkr_bot] council report error: {_e}")
            if council_res["verdict"] != "CONFIRM":
                print(f"[ibkr_bot] COUNCIL_PASS {symbol} {signal}: {council_res['decision_reason']}")
                _append_trade_log({
                    "time": _now_jst().strftime("%Y-%m-%d %H:%M:%S"),
                    "side": signal, "result": "COUNCIL_BLOCK", "lot": 0,
                    "price": round(current_price, 4), "trend": trend,
                    "note": council_res["decision_reason"][:200],
                })
                signal = None
            else:
                print(f"[ibkr_bot] COUNCIL_CONFIRM {symbol} {signal}: {council_res['decision_reason']}")

        if not signal:
            continue

        pos_id = _gen_pos_id(signal)
        fill_price = current_price
        order_id: Optional[int] = None
        try:
            result = adapter.place_order(symbol=symbol, action=signal, quantity=shares, order_type="MKT")
            fill_price = float(result.get("avg_fill_price") or current_price)
            order_id = result.get("order_id")
        except Exception as e:
            print(f"[ibkr_bot] entry order error {symbol}: {e}")
            continue

        # 防御逆指値(STP)をブローカーに即発注。GTCで持ち越し・切断時も損失をSL近辺で確定。
        # これによりSL滑り（-0.5%→-0.91%型）とオーバーナイト窓開けの両方を抑える。
        protective_stop_id: Optional[int] = None
        stop_price: Optional[float] = None
        try:
            sl_frac = sl_pct / 100.0  # sl_pct は負値（例 -0.5）
            stop_price = round(fill_price * (1 + sl_frac), 2) if signal == "BUY" else round(fill_price * (1 - sl_frac), 2)
            stop_action = "SELL" if signal == "BUY" else "BUY"
            stp = adapter.place_order(symbol=symbol, action=stop_action, quantity=shares,
                                      order_type="STP", stop_price=stop_price, tif="GTC")
            protective_stop_id = stp.get("order_id")
            print(f"[ibkr_bot] protective STP {symbol} {stop_action} @ ${stop_price} (id={protective_stop_id})")
        except Exception as e:
            print(f"[ibkr_bot] protective stop placement error {symbol}: {e} (loop-SLでバックアップ)")

        _append_trade_log({
            "time": _now_jst().strftime("%Y-%m-%d %H:%M:%S"),
            "side": signal,
            "result": "LIVE" if _is_live_mode(ctrl) else "PAPER",
            "lot": shares,
            "price": round(fill_price, 4),
            "trend": trend,
            "note": (
                f"pos_id={pos_id} symbol={symbol} "
                f"entry_time={_now_jst().strftime('%Y-%m-%dT%H:%M:%S')} "
                f"entry_price={fill_price:.4f} "
                f"tp_pct={effective_tp} sl_pct={sl_pct} "
                f"sma_fast={fast_n} sma_slow={slow_n}"
                + (f" vwap={vwap:.2f}" if vwap else "")
                + (f" atr={atr:.4f}" if atr else "")
                + (f" candle={candle}" if candle else "")
                + (f" daily_move={daily_move:.2f}%" if daily_move is not None else "")
                + (f" sma_div={sma_div:.4f}%" if sma_div is not None else "")
                + f" {vix_note}"
            ),
        })

        open_positions[symbol] = {
            "bot_managed": True,
            "pos_id": pos_id,
            "symbol": symbol,
            "side": signal,
            "entry_price": fill_price,
            "shares": shares,
            "order_id": order_id,
            "protective_stop_order_id": protective_stop_id,
            "stop_price": stop_price,
            "tp_pct": effective_tp,
            "sl_pct": sl_pct,
            "best_fav": 0.0,
            "entry_time": _now_jst().strftime("%Y-%m-%dT%H:%M:%S"),
        }
        state["daily_trade_count"] = int(state.get("daily_trade_count", 0)) + 1

        _send_ntfy(
            f"[IBKR] ENTRY {symbol} {signal}",
            f"{symbol} {signal} ENTRY\n価格: ${fill_price:.2f}\nシグナル: SMA{fast_n}/SMA{slow_n} クロス  trend={trend}\nTP: +{effective_tp:.2f}%  SL: {sl_pct:.2f}%",
        )
        print(f"[ibkr_bot] ENTRY {signal} {symbol} @ ${fill_price:.2f}  pos_id={pos_id}")

    # Update legacy open_pos for backward compat (dashboard / snapshot scripts read this)
    state["open_pos"] = next(iter(open_positions.values()), None)
    return state


# ---------------------------------------------------------------------------
# Main loop — persistent connection pattern (ib_insync reuses asyncio loop)
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"[ibkr_bot] v{IBKR_BOT_VERSION} starting")
    sys.path.insert(0, str(MAIN_DIR))
    from ibkr_adapter import IBKRAdapter

    while True:
        ctrl = _load_control()

        if not _ctrl_bool(ctrl, "ibkr_enabled", True):
            print("[ibkr_bot] ibkr_enabled=0, waiting 60s")
            time.sleep(60)
            continue

        # Create adapter ONCE per outer loop and keep connection alive.
        # ib_insync reuses the asyncio event loop; recreating IB() every
        # iteration breaks the loop. Connect once, loop inside.
        adapter = IBKRAdapter(
            host=ctrl.get("ibkr_host", "127.0.0.1"),
            port=_ctrl_int(ctrl, "ibkr_port", 7497),
            client_id=_ctrl_int(ctrl, "ibkr_client_id", 20),
            timeout_sec=30.0,
            readonly=False,
            market_data_type="delayed",
        )
        try:
            connected = adapter.connect()
            if not connected:
                print("[ibkr_bot] connect failed, retry in 30s")
                time.sleep(30)
                continue

            print("[ibkr_bot] connected to IB Gateway")

            # Inner loop: stay connected and trade
            while True:
                try:
                    ctrl = _load_control()

                    if not _ctrl_bool(ctrl, "ibkr_enabled", True):
                        print("[ibkr_bot] ibkr_enabled turned off, disconnecting")
                        break

                    if not adapter.is_connected():
                        print("[ibkr_bot] connection lost, reconnecting...")
                        break

                    state = _load_state()
                    state = run_once(adapter, ctrl, state)
                    _save_state(state)

                except Exception as e:
                    print(f"[ibkr_bot] inner loop error: {e}")
                    traceback.print_exc()

                time.sleep(60)

        except Exception as e:
            print(f"[ibkr_bot] ERROR: {e}")
            traceback.print_exc()
        finally:
            try:
                adapter.disconnect()
            except Exception:
                pass

        time.sleep(30)


if __name__ == "__main__":
    main()
