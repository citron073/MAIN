#!/usr/bin/env python3
"""Fetch historical FX_BTC_JPY tick data from bitFlyer and aggregate into 5-min OHLC bars.

Usage:
    python3 tools/fetch_historical_ohlc.py [--pages N] [--bar-min M] [--out PATH]

    --pages N      Number of API pages to fetch (500 ticks/page, default=200 → ~100,000 ticks)
    --bar-min M    OHLC bar interval in minutes (default=5)
    --out PATH     Output CSV path (default=data/historical_ohlc.csv)
    --resume       Resume from last fetched ID (default: start fresh)

Output columns: ts, o, h, l, c, ticks, volume
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "historical_ohlc.csv"
API_BASE = "https://api.bitflyer.com"
PRODUCT = "FX_BTC_JPY"
RATE_LIMIT_SLEEP = 0.5  # seconds between API calls (bitFlyer: 500 req/5min ≈ 1.67/sec)


def _fetch_executions(before_id: Optional[int] = None, count: int = 500) -> List[Dict[str, Any]]:
    url = f"{API_BASE}/v1/getexecutions?product_code={PRODUCT}&count={count}"
    if before_id is not None:
        url += f"&before={before_id}"
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "Ouroboros/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("[WARN] rate limited, sleeping 30s...")
            time.sleep(30)
            return []
        raise
    except Exception as e:
        print(f"[WARN] fetch error: {e}")
        return []


def _parse_exec_dt(exec_date: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(exec_date, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _aggregate_to_ohlc(ticks: List[Dict[str, Any]], bar_min: int) -> List[Dict[str, Any]]:
    buckets: Dict[int, List[float]] = defaultdict(list)
    bucket_vol: Dict[int, float] = defaultdict(float)
    for tick in ticks:
        dt = _parse_exec_dt(str(tick.get("exec_date", "")))
        if dt is None:
            continue
        price = float(tick.get("price", 0))
        size = float(tick.get("size", 0))
        if price <= 0:
            continue
        bar_ts = int(dt.timestamp()) // (bar_min * 60) * (bar_min * 60)
        buckets[bar_ts].append(price)
        bucket_vol[bar_ts] += size

    bars: List[Dict[str, Any]] = []
    for ts in sorted(buckets.keys()):
        prices = buckets[ts]
        if not prices:
            continue
        bars.append({
            "ts": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "o": prices[0],
            "h": max(prices),
            "l": min(prices),
            "c": prices[-1],
            "ticks": len(prices),
            "volume": round(bucket_vol[ts], 6),
        })
    return bars


def _load_existing_ohlc(path: Path) -> Tuple[Dict[str, Dict[str, Any]], int]:
    """Load existing OHLC bars, return (ts->bar dict, max execution id seen)."""
    bars: Dict[str, Dict[str, Any]] = {}
    if not path.exists():
        return bars, 0
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                ts = row.get("ts", "")
                if ts:
                    bars[ts] = row
    except Exception:
        pass
    return bars, 0


def _load_resume_id(out_path: Path) -> int:
    """Load minimum exec ID seen (for resuming toward older data)."""
    state_path = out_path.with_suffix(".state.json")
    if not state_path.exists():
        return 0
    try:
        d = json.loads(state_path.read_text(encoding="utf-8"))
        return int(d.get("min_exec_id", 0))
    except Exception:
        return 0


def _save_resume_id(out_path: Path, min_exec_id: int, total_ticks: int) -> None:
    state_path = out_path.with_suffix(".state.json")
    state_path.write_text(
        json.dumps({"min_exec_id": min_exec_id, "total_ticks": total_ticks, "updated_at": datetime.now().isoformat()},
                   indent=2) + "\n",
        encoding="utf-8",
    )


def _write_ohlc(path: Path, bars: Dict[str, Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["ts", "o", "h", "l", "c", "ticks", "volume"]
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for ts in sorted(bars.keys()):
            w.writerow(bars[ts])
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=200, help="Number of API pages (500 ticks each)")
    ap.add_argument("--bar-min", type=int, default=5, help="OHLC bar interval in minutes")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--resume", action="store_true", help="Resume from last fetched execution ID")
    args = ap.parse_args()

    print(f"[fetch_historical_ohlc] target={args.out} pages={args.pages} bar={args.bar_min}min")
    existing_bars, _ = _load_existing_ohlc(args.out)
    print(f"  existing bars: {len(existing_bars)}")

    before_id: Optional[int] = None
    if args.resume:
        resume_id = _load_resume_id(args.out)
        if resume_id > 0:
            before_id = resume_id
            print(f"  resuming from id < {before_id}")

    all_ticks: List[Dict[str, Any]] = []
    min_exec_id = before_id or 999_999_999_999

    for page in range(args.pages):
        ticks = _fetch_executions(before_id=before_id, count=500)
        if not ticks:
            print(f"  page {page+1}: empty (done)")
            break

        all_ticks.extend(ticks)
        ids = [int(t.get("id", 0)) for t in ticks if t.get("id")]
        if ids:
            before_id = min(ids)
            min_exec_id = min(min_exec_id, before_id)

        if (page + 1) % 10 == 0 or page == 0:
            oldest = ticks[-1].get("exec_date", "?")
            print(f"  page {page+1}/{args.pages}: {len(all_ticks)} ticks, oldest={oldest}, before_id={before_id}")

        time.sleep(RATE_LIMIT_SLEEP)

    print(f"\n[aggregate] {len(all_ticks)} ticks → {args.bar_min}-min OHLC bars")
    new_bars = _aggregate_to_ohlc(all_ticks, args.bar_min)
    print(f"  new bars: {len(new_bars)}")

    # Merge with existing
    for bar in new_bars:
        ts = bar["ts"]
        if ts in existing_bars:
            # Merge: update h/l/c/ticks/volume; keep o from earlier (older bar wins open)
            ex = existing_bars[ts]
            existing_bars[ts] = {
                "ts": ts,
                "o": ex["o"],
                "h": max(float(ex["h"]), float(bar["h"])),
                "l": min(float(ex["l"]), float(bar["l"])),
                "c": bar["c"],
                "ticks": int(ex.get("ticks", 0)) + bar["ticks"],
                "volume": round(float(ex.get("volume", 0)) + bar["volume"], 6),
            }
        else:
            existing_bars[ts] = bar

    _write_ohlc(args.out, existing_bars)
    _save_resume_id(args.out, min_exec_id, len(all_ticks))

    date_range = ""
    if existing_bars:
        sorted_ts = sorted(existing_bars.keys())
        date_range = f"{sorted_ts[0][:10]} to {sorted_ts[-1][:10]}"
    print(f"\n[done] total bars={len(existing_bars)} range={date_range}")
    print(f"  saved to: {args.out}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
