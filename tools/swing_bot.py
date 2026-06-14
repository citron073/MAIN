#!/usr/bin/env python3
"""日足スイングbot (PAPER専用 v0.1) — docs/SWING_BOT_DESIGN.md 準拠。

検証済み構成(trading_knowledge/06 検証8/9・WF通過のみ):
  SWING-BTC: BTCUSDT日足  entry=ドンチャン20日 / exit=10日逆側トレーリング + 初期SL=ATR14×2
  SWING-US : QQQ,SPY日足  entry=ドンチャン55日 / exit=20日逆側トレーリング + 初期SL=ATR14×2

1日1回(systemd timer 09:15 JST)実行・常駐しない。実弾コードパスなし(PAPERのみ)。
データ: BTC=Binance public klines / US=IB Gateway(ダウン時はスキップ+ntfy警告)。
状態=swing_state.json / 設定=SWING_CONTROL.csv / ログ=../logs/swing_trade_log.csv / 通知=ntfy(high)。
"""
from __future__ import annotations

import csv
import json
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

MAIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MAIN_DIR))

STATE_FILE = MAIN_DIR / "swing_state.json"
CONTROL_FILE = MAIN_DIR / "SWING_CONTROL.csv"
LOG_FILE = MAIN_DIR.parent / "logs" / "swing_trade_log.csv"
SECRETS_FILE = MAIN_DIR / ".streamlit" / "secrets.toml"
JST = timezone(timedelta(hours=9))

# 検証済みパラメータ(固定・変更はWF再検証が条件 / 06 検証8・9)
MARKETS = [
    # crypto(20/10): 検証8 WF通過 / ETHは検証10 個別WF通過(+7.26/+0.36)
    {"key": "BTC", "symbol": "BTCUSDT", "source": "binance", "entry_n": 20, "exit_n": 10},
    {"key": "ETH", "symbol": "ETHUSDT", "source": "binance", "entry_n": 20, "exit_n": 10},
    # US(55/20): QQQ/SPY=検証8 / GLD,MSFT,NVDA,SMH=検証10 個別WFスクリーニング合格(両期間プラス)
    {"key": "QQQ", "symbol": "QQQ", "source": "ibkr", "entry_n": 55, "exit_n": 20},
    {"key": "SPY", "symbol": "SPY", "source": "ibkr", "entry_n": 55, "exit_n": 20},
    {"key": "GLD", "symbol": "GLD", "source": "ibkr", "entry_n": 55, "exit_n": 20},
    {"key": "MSFT", "symbol": "MSFT", "source": "ibkr", "entry_n": 55, "exit_n": 20},
    {"key": "NVDA", "symbol": "NVDA", "source": "ibkr", "entry_n": 55, "exit_n": 20},
    {"key": "SMH", "symbol": "SMH", "source": "ibkr", "entry_n": 55, "exit_n": 20},
    {"key": "NFLX", "symbol": "NFLX", "source": "ibkr", "entry_n": 55, "exit_n": 20},  # 検証10追補: WF+1.51/+5.34・$100未満で唯一合格
]
ATR_N = 14
SL_ATR_MULT = 2.0

# 相関クラスタ(2026-06-14 相関監査: N_eff≈2.2・テック群平均相関0.64・BTC-ETH 0.79)。
# 「9市場」は実質テックβ/cryptoβ/金 の3クラスタ。同クラスタの積み増しは相関リスクの集中＝
# 1トレード1%が実効N%に膨らむ穴。swing_max_per_cluster で同時保有を制限する。
CLUSTER = {
    "BTC": "CRYPTO", "ETH": "CRYPTO",
    "QQQ": "TECH", "SPY": "TECH", "MSFT": "TECH", "NVDA": "TECH", "SMH": "TECH", "NFLX": "TECH",
    "GLD": "GOLD",
}


def _now_jst() -> datetime:
    return datetime.now(JST)


def _load_control() -> Dict[str, str]:
    ctrl: Dict[str, str] = {}
    if CONTROL_FILE.exists():
        for row in csv.reader(CONTROL_FILE.open()):
            if len(row) >= 2 and row[0].strip() and not row[0].startswith("#"):
                ctrl[row[0].strip()] = row[1].strip()
    return ctrl


def _load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            print("[swing] WARN state破損→初期化")
    return {"positions": {}, "last_bar": {}}


def _save_state(state: Dict[str, Any]) -> None:
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    tmp.replace(STATE_FILE)


def _read_secret(key: str) -> str:
    if not SECRETS_FILE.exists():
        return ""
    for line in SECRETS_FILE.read_text().splitlines():
        if line.strip().startswith(key):
            parts = line.split("=", 1)
            if len(parts) == 2:
                return parts[1].strip().strip('"').strip("'")
    return ""


def _send_ntfy(title: str, body: str) -> None:
    url = _read_secret("ntfy_topic_url")
    safe_title = title.encode("ascii", errors="replace").decode("ascii")
    if not url:
        print(f"[swing] NTFY_SKIP url未設定 {safe_title}")
        return
    try:
        req = urllib.request.Request(
            url, data=body.encode("utf-8"), method="POST",
            headers={"Content-Type": "text/plain; charset=utf-8",
                     "Title": safe_title, "Priority": "high", "Tags": "ocean"})
        with urllib.request.urlopen(req, timeout=10.0) as r:
            print(f"[swing] NTFY_OK http={getattr(r, 'status', '?')} {safe_title}")
    except Exception as e:
        print(f"[swing] NTFY_FAIL {safe_title} err={type(e).__name__}: {e}")


def _append_log(row: Dict[str, Any]) -> None:
    fields = ["time", "market", "side", "event", "price", "size", "sl", "note"]
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    new = not LOG_FILE.exists()
    with LOG_FILE.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)
        f.flush()
        try:
            import os
            os.fsync(f.fileno())
        except Exception:
            pass


def _fetch_binance_daily(symbol: str, limit: int = 120) -> List[Dict[str, float]]:
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit={limit}"
    with urllib.request.urlopen(url, timeout=15.0) as r:
        raw = json.loads(r.read().decode())
    out = []
    for k in raw:
        out.append({"time": datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
                    "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
                    "close": float(k[4]), "closed": bool(k[6] / 1000 < datetime.now(timezone.utc).timestamp())})
    return [b for b in out if b["closed"]]


_IBKR_ADAPTER = None


def _fetch_ibkr_daily(symbol: str) -> Optional[List[Dict[str, float]]]:
    global _IBKR_ADAPTER
    try:
        if _IBKR_ADAPTER is None:
            from ibkr_adapter import IBKRAdapter
            a = IBKRAdapter(host="127.0.0.1", port=7496, client_id=81,
                            timeout_sec=30.0, readonly=True, market_data_type="delayed")
            if not a.connect():
                return None
            _IBKR_ADAPTER = a
        bars = _IBKR_ADAPTER.get_historical_bars(symbol, bar_size="1 day", duration="6 M")
        return [{"time": str(b["time"])[:10], "open": b["open"], "high": b["high"],
                 "low": b["low"], "close": b["close"]} for b in bars]
    except Exception as e:
        print(f"[swing] IBKR fetch error {symbol}: {type(e).__name__}: {e}")
        return None


def _atr(bars: List[Dict[str, float]], n: int = ATR_N) -> Optional[float]:
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(len(bars) - n, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / n


def _process_market(m: Dict[str, Any], bars: List[Dict[str, float]], state: Dict[str, Any],
                    ctrl: Dict[str, str]) -> None:
    key = m["key"]
    last = bars[-1]
    bar_date = last["time"]
    if state["last_bar"].get(key) == bar_date:
        print(f"[swing] {key}: bar {bar_date} 処理済み(休場/重複) skip")
        return
    pos = state["positions"].get(key)
    risk_pct = float(ctrl.get("swing_risk_pct", "1.0"))
    equity = float(ctrl.get(f"swing_equity_{key.lower()}", ctrl.get("swing_equity_usd", "10000")))

    # --- 出口判定(保有中) ---
    if pos:
        side = pos["side"]
        exit_n = m["exit_n"]
        prior = bars[-(exit_n + 1):-1]
        if side == "BUY":
            ch = min(b["low"] for b in prior)
            stop = max(float(pos["sl_price"]), ch)
            hit = last["low"] <= stop
            exit_px = last["open"] if last["open"] < stop else stop
        else:
            ch = max(b["high"] for b in prior)
            stop = min(float(pos["sl_price"]), ch)
            hit = last["high"] >= stop
            exit_px = last["open"] if last["open"] > stop else stop
        if hit:
            entry_px = float(pos["entry_price"])
            ret = (exit_px - entry_px) / entry_px * 100 if side == "BUY" else (entry_px - exit_px) / entry_px * 100
            pnl = ret / 100 * entry_px * float(pos["size"])
            note = (f"exit=trail_or_sl stop={stop:.2f} entry={entry_px:.2f} ret={ret:+.3f}% "
                    f"pnl_usd={pnl:+.2f} held_from={pos['entry_date']}")
            _append_log({"time": _now_jst().strftime("%Y-%m-%d %H:%M:%S"), "market": key,
                         "side": side, "event": "PAPER_EXIT", "price": round(exit_px, 2),
                         "size": pos["size"], "sl": round(stop, 2), "note": note})
            _send_ntfy(f"[SWING] EXIT {key} {side}",
                       f"{key} {side} 決済(paper)\n入:{entry_px:.2f} 出:{exit_px:.2f}\n{ret:+.3f}% (${pnl:+.2f})\n保有 {pos['entry_date']}→{bar_date}")
            del state["positions"][key]
        else:
            print(f"[swing] {key}: 保有中 {side} stop={stop:.2f} close={last['close']:.2f}")
        state["last_bar"][key] = bar_date
        return

    # --- 入口判定(ノーポジ) ---
    entry_n = m["entry_n"]
    if len(bars) < entry_n + ATR_N + 2:
        print(f"[swing] {key}: バー不足 {len(bars)}")
        return
    prior = bars[-(entry_n + 1):-1]
    ch_hi = max(b["high"] for b in prior)
    ch_lo = min(b["low"] for b in prior)
    c = last["close"]
    sig = "BUY" if c > ch_hi else ("SELL" if c < ch_lo else None)
    state["last_bar"][key] = bar_date
    if not sig:
        print(f"[swing] {key}: シグナルなし close={c:.2f} ch=[{ch_lo:.2f},{ch_hi:.2f}]")
        return
    max_pos = int(float(ctrl.get("swing_max_positions", "4")))
    if len(state["positions"]) >= max_pos:
        note = f"max_positions={max_pos}到達のためエントリー見送り sig={sig} close={c:.2f}"
        print(f"[swing] {key}: {note}")
        _append_log({"time": _now_jst().strftime("%Y-%m-%d %H:%M:%S"), "market": key,
                     "side": sig, "event": "SKIP_MAX_POS", "price": round(c, 2),
                     "size": 0, "sl": 0, "note": note})
        _send_ntfy(f"[SWING] SKIP {key} {sig}", f"{key} {sig} シグナルあり、ただし同時ポジ上限{max_pos}で見送り")
        return
    # 相関クラスタ上限(相関集中=実効リスク膨張の穴を塞ぐ / 相関監査2026-06-14)
    max_cluster = int(float(ctrl.get("swing_max_per_cluster", "2")))
    cl = CLUSTER.get(key, key)
    open_in_cluster = sum(1 for mk in state["positions"] if CLUSTER.get(mk, mk) == cl)
    if open_in_cluster >= max_cluster:
        note = f"cluster={cl} 上限{max_cluster}到達(相関集中回避・既存{open_in_cluster}) sig={sig} close={c:.2f}"
        print(f"[swing] {key}: {note}")
        _append_log({"time": _now_jst().strftime("%Y-%m-%d %H:%M:%S"), "market": key,
                     "side": sig, "event": "SKIP_CLUSTER_LIMIT", "price": round(c, 2),
                     "size": 0, "sl": 0, "note": note})
        _send_ntfy(f"[SWING] SKIP {key} {sig}", f"{key} {sig} シグナルあり、ただし{cl}クラスタ上限{max_cluster}で見送り(相関集中回避)")
        return
    atr = _atr(bars)
    if not atr:
        return
    stop_dist = SL_ATR_MULT * atr
    sl_price = c - stop_dist if sig == "BUY" else c + stop_dist
    size = round((equity * risk_pct / 100.0) / stop_dist, 6)  # リスク1%をSL幅で逆算
    state["positions"][key] = {
        "side": sig, "entry_price": c, "entry_date": bar_date,
        "sl_price": round(sl_price, 2), "size": size, "exit_n": m["exit_n"],
    }
    note = (f"donchian{entry_n} break ch=[{ch_lo:.2f},{ch_hi:.2f}] atr={atr:.2f} "
            f"sl={sl_price:.2f} risk={risk_pct}% equity={equity}")
    _append_log({"time": _now_jst().strftime("%Y-%m-%d %H:%M:%S"), "market": key,
                 "side": sig, "event": "PAPER_ENTRY", "price": round(c, 2),
                 "size": size, "sl": round(sl_price, 2), "note": note})
    _send_ntfy(f"[SWING] ENTRY {key} {sig}",
               f"{key} {sig} 新規(paper)\n価格:{c:.2f} SL:{sl_price:.2f}(ATR×2)\nsize:{size} (リスク{risk_pct}%)\nドンチャン{entry_n}日ブレイク")


def main() -> int:
    print(f"[swing] start {_now_jst().strftime('%Y-%m-%d %H:%M:%S')} JST (PAPER v0.1)")
    ctrl = _load_control()
    if ctrl.get("swing_enabled", "1") != "1":
        print("[swing] swing_enabled!=1 skip")
        return 0
    state = _load_state()
    for m in MARKETS:
        try:
            if m["source"] == "binance":
                bars = _fetch_binance_daily(m["symbol"])
            else:
                bars = _fetch_ibkr_daily(m["symbol"])
                if bars is None:
                    _send_ntfy(f"[SWING] WARN {m['key']} データ取得不可",
                               "IB Gateway未接続のためUS判定をスキップしました(本日分)")
                    continue
            if not bars:
                print(f"[swing] {m['key']}: bars空 skip")
                continue
            _process_market(m, bars, state, ctrl)
        except Exception as e:
            print(f"[swing] ERROR {m['key']}: {type(e).__name__}: {e}")
            _send_ntfy(f"[SWING] ERROR {m['key']}", f"{type(e).__name__}: {e}")
    _save_state(state)
    try:
        if _IBKR_ADAPTER is not None:
            _IBKR_ADAPTER.disconnect()
    except Exception:
        pass
    print("[swing] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
