#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download Binance public klines and save as OHLCV CSV.

Output columns:
time,open,high,low,close,volume
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple
from urllib.parse import urlencode
from urllib.request import urlopen


BASE_URL = "https://api.binance.com/api/v3/klines"
MAX_LIMIT = 1000
INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _parse_ymd(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _fetch_once(
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    limit: int,
    *,
    timeout_sec: float,
    retries: int,
) -> List[List]:
    q = urlencode(
        {
            "symbol": symbol,
            "interval": interval,
            "startTime": int(start_ms),
            "endTime": int(end_ms),
            "limit": int(limit),
        }
    )
    url = f"{BASE_URL}?{q}"
    last_err: Exception | None = None
    for k in range(max(1, int(retries))):
        try:
            with urlopen(url, timeout=float(timeout_sec)) as r:
                body = r.read().decode("utf-8", errors="replace")
            data = json.loads(body)
            if not isinstance(data, list):
                raise RuntimeError(f"unexpected response: {data}")
            return data
        except Exception as e:  # pragma: no cover - network dependent
            last_err = e
            backoff = min(4.0, 0.5 * (2 ** k))
            print(f"[WARN] fetch failed retry={k+1}/{retries} err={e}")
            time.sleep(backoff)
    if last_err is None:
        raise RuntimeError("fetch failed without error")
    raise RuntimeError(f"fetch failed after retries: {last_err}")


def fetch_all(
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    *,
    sleep_sec: float,
    progress_every: int,
    timeout_sec: float,
    retries: int,
) -> List[Tuple[str, float, float, float, float, float]]:
    out: List[Tuple[str, float, float, float, float, float]] = []
    cursor = start_ms
    pages = 0
    t0 = time.time()
    step_ms = int(INTERVAL_MS.get(interval, 60_000))
    while cursor < end_ms:
        rows = _fetch_once(
            symbol,
            interval,
            cursor,
            end_ms,
            MAX_LIMIT,
            timeout_sec=timeout_sec,
            retries=retries,
        )
        if not rows:
            break
        for r in rows:
            # Binance kline:
            # [open_time, open, high, low, close, volume, close_time, ...]
            ot = int(r[0])
            if ot >= end_ms:
                continue
            t = datetime.fromtimestamp(ot / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            out.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
        last_open = int(rows[-1][0])
        if last_open < cursor:
            break
        # move to next candle
        cursor = last_open + step_ms
        pages += 1
        if progress_every > 0 and (pages % progress_every == 0):
            elapsed = max(1e-6, time.time() - t0)
            pct = ((cursor - start_ms) / max(1, (end_ms - start_ms))) * 100.0
            pace = len(out) / elapsed
            eta_sec = (max(0, end_ms - cursor) / max(1, step_ms)) / max(1e-6, pace)
            upto = datetime.fromtimestamp(max(start_ms, min(cursor, end_ms)) / 1000.0, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            print(
                f"[PROGRESS] pages={pages} rows={len(out)} pct={pct:.1f}% upto_utc={upto} "
                f"speed={pace:.1f} rows/s eta={eta_sec/60.0:.1f}m"
            )
        time.sleep(max(0.0, float(sleep_sec)))
    # dedupe by time
    seen = set()
    dedup: List[Tuple[str, float, float, float, float, float]] = []
    for row in out:
        if row[0] in seen:
            continue
        seen.add(row[0])
        dedup.append(row)
    dedup.sort(key=lambda x: x[0])
    return dedup


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Fetch Binance OHLCV into csv (UTC).")
    ap.add_argument("--symbol", default="BTCUSDT", help="example: BTCUSDT")
    ap.add_argument("--interval", default="5m", help="1m/3m/5m/15m/1h/4h/1d ...")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD (UTC, exclusive)")
    ap.add_argument("--out", default="../logs/backtest/ohlcv_binance_btcusdt_5m.csv")
    ap.add_argument("--sleep-sec", type=float, default=0.08, help="sleep between API pages")
    ap.add_argument("--progress-every", type=int, default=20, help="print progress every N pages")
    ap.add_argument("--timeout-sec", type=float, default=20.0, help="HTTP timeout seconds")
    ap.add_argument("--retries", type=int, default=3, help="retries per page on network error")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    start = _parse_ymd(args.start)
    end = _parse_ymd(args.end)
    if end <= start:
        print("[ERROR] --end must be after --start")
        return 2
    start_ms = _to_ms(start)
    end_ms = _to_ms(end)
    print(f"[INFO] fetch symbol={args.symbol} interval={args.interval} start={args.start} end={args.end}")
    if args.interval not in INTERVAL_MS:
        print(f"[WARN] unknown interval={args.interval}; progress estimation may be inaccurate")
    rows = fetch_all(
        args.symbol.upper(),
        args.interval,
        start_ms,
        end_ms,
        sleep_sec=float(args.sleep_sec),
        progress_every=max(1, int(args.progress_every)),
        timeout_sec=float(args.timeout_sec),
        retries=max(1, int(args.retries)),
    )
    if not rows:
        print("[ERROR] no rows fetched")
        return 2
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for r in rows:
            w.writerow(r)
    print(f"[OK] wrote {out} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
