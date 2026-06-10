#!/usr/bin/env python3
"""IB Gateway から米株の履歴OHLCバーを取得して CSV 保存する（バックテスト/仮想取引の素材）。

ライブbot(client_id=20)と別client_id・readonlyで併存接続する。IB Gatewayが稼働中(US場 or
ログイン中)に実行すること。reqHistoricalData のペーシング制限を避けるため銘柄間に小休止を入れる。

Usage:
    python3 tools/ibkr_fetch_history.py [--symbols QQQ,SPY,AMD] [--bar-size "5 mins"] \
        [--duration "30 D"] [--out-dir data/us_stocks] [--client-id 77] [--port 7496]

出力: <out-dir>/<SYMBOL>_<barslug>.csv  (列: time,open,high,low,close,volume)
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # .../MAIN
sys.path.insert(0, str(ROOT))

# 既定ユニバース: 高流動の指数ETF + 実際に取引した銘柄 + 主要大型株
DEFAULT_SYMBOLS = "QQQ,SPY,AMD,NEM,AAPL,MSFT,NVDA,TSLA,META,AMZN"


def _read_ctrl_int(key: str, default: int) -> int:
    p = ROOT / "IBKR_CONTROL.csv"
    if p.exists():
        for row in csv.reader(p.open()):
            if len(row) >= 2 and row[0].strip() == key:
                try:
                    return int(float(row[1].strip()))
                except ValueError:
                    pass
    return default


def _slug(bar_size: str) -> str:
    return bar_size.replace(" ", "").replace("mins", "min").replace("min", "min")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    ap.add_argument("--bar-size", default="5 mins")
    ap.add_argument("--duration", default="30 D")
    ap.add_argument("--out-dir", default="data/us_stocks")
    ap.add_argument("--client-id", type=int, default=77)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--sleep", type=float, default=2.0, help="銘柄間の休止秒(ペーシング対策)")
    args = ap.parse_args()

    port = args.port if args.port is not None else _read_ctrl_int("ibkr_port", 7496)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    out_dir = (ROOT / args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(args.bar_size)

    from ibkr_adapter import IBKRAdapter
    adapter = IBKRAdapter(host=args.host, port=port, client_id=args.client_id,
                          timeout_sec=30.0, readonly=True, market_data_type="delayed")
    if not adapter.connect():
        print(f"[fetch] connect失敗 port={port} client_id={args.client_id}")
        return 1
    print(f"[fetch] connected port={port} client_id={args.client_id} "
          f"bar='{args.bar_size}' dur='{args.duration}' symbols={len(symbols)}")

    ok = 0
    for i, sym in enumerate(symbols):
        try:
            bars = adapter.get_historical_bars(sym, bar_size=args.bar_size,
                                               duration=args.duration, use_rth=True)
        except Exception as e:
            print(f"[fetch] {sym}: ERROR {type(e).__name__}: {e}")
            continue
        if not bars:
            print(f"[fetch] {sym}: 0 bars (skip)")
            continue
        out = out_dir / f"{sym}_{slug}.csv"
        fields = ["time", "open", "high", "low", "close", "volume"]
        with out.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for b in bars:
                w.writerow({k: b.get(k, "") for k in fields})
        ok += 1
        print(f"[fetch] {sym}: {len(bars)} bars -> {out.name}")
        if i < len(symbols) - 1:
            time.sleep(args.sleep)

    try:
        adapter.disconnect()
    except Exception:
        pass
    print(f"[fetch] 完了: {ok}/{len(symbols)} 銘柄保存 -> {out_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
