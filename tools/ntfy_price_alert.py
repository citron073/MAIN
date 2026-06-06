#!/usr/bin/env python3
"""BTC/JPY price spike alert via ntfy. Run every 5 minutes via systemd timer.

Alerts when BTC/JPY moves ±3% (warning) or ±5% (critical) over the past ~60 minutes.
State is stored in MAIN/.ntfy_price_alert_state.json to track price history.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MAIN_DIR = Path(__file__).resolve().parent.parent
SECRETS_TOML = MAIN_DIR / ".streamlit" / "secrets.toml"
STATE_FILE = MAIN_DIR / ".ntfy_price_alert_state.json"

WARN_PCT = 3.0
ALERT_PCT = 5.0
COOLDOWN_MIN = 20
LOOKBACK_MIN = 60
MAX_HISTORY = 90
MIN_TICKS = 8


def _read_toml_str(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            return v if v not in ("", "***MASKED***") else ""
    return ""


def _fetch_btcjpy() -> Optional[float]:
    url = "https://api.bitflyer.com/v1/ticker?product_code=FX_BTC_JPY"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Ouroboros/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
            bid = float(data.get("best_bid") or 0)
            ask = float(data.get("best_ask") or 0)
            if bid > 0 and ask > 0:
                return (bid + ask) / 2
            ltp = float(data.get("ltp") or 0)
            return ltp if ltp > 0 else None
    except Exception as e:
        print(f"[fetch_err] {e}", file=sys.stderr)
        return None


def _load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {"history": [], "last_alert_time": None, "last_alert_pct": None}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"history": [], "last_alert_time": None, "last_alert_pct": None}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _http_post(url: str, body: bytes, headers: Dict[str, str]) -> Tuple[bool, str]:
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return True, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)


def main() -> int:
    price = _fetch_btcjpy()
    if not price:
        print("[skip] price fetch failed")
        return 0

    now = datetime.now()
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%S")
    state = _load_state()
    history: List[Dict[str, Any]] = state.get("history") or []

    history.append({"time": now_iso, "price": price})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    state["history"] = history

    if len(history) < MIN_TICKS:
        _save_state(state)
        print(f"[accumulating] {len(history)}/{MIN_TICKS} ticks  price={price:,.0f}")
        return 0

    # find reference price from ~60 min ago (most recent entry at or before cutoff)
    cutoff = now - timedelta(minutes=LOOKBACK_MIN)
    ref_entry = history[0]
    for entry in history:
        try:
            t = datetime.fromisoformat(entry["time"])
            if t <= cutoff:
                ref_entry = entry
        except Exception:
            continue

    ref_price = float(ref_entry["price"])
    change_pct = (price - ref_price) / ref_price * 100.0
    abs_change = abs(change_pct)

    # check cooldown
    cooldown_ok = True
    last_alert_str = state.get("last_alert_time")
    if last_alert_str:
        try:
            elapsed = (now - datetime.fromisoformat(last_alert_str)).total_seconds()
            cooldown_ok = elapsed >= COOLDOWN_MIN * 60
        except Exception:
            pass

    print(f"[check] price={price:,.0f}  ref={ref_price:,.0f}  Δ={change_pct:+.2f}%  cooldown={'ok' if cooldown_ok else 'wait'}")

    if abs_change < WARN_PCT or not cooldown_ok:
        _save_state(state)
        return 0

    ntfy_url = _read_toml_str(SECRETS_TOML, "ntfy_topic_url")
    if not ntfy_url:
        print("[skip] ntfy_topic_url not configured")
        _save_state(state)
        return 0

    direction = "上昇 ↑" if change_pct > 0 else "下落 ↓"
    emoji = "🚨" if abs_change >= ALERT_PCT else "⚠️"
    level = "急変" if abs_change >= ALERT_PCT else "警戒"
    priority = "urgent" if abs_change >= ALERT_PCT else "high"
    ref_time = ref_entry["time"][11:16]

    body = (
        f"{emoji} BTC/JPY {level} {direction}\n"
        f"\n"
        f"現在値: ¥{price:,.0f}\n"
        f"{ref_time}時点: ¥{ref_price:,.0f}\n"
        f"変化: {change_pct:+.2f}%\n"
        f"時刻: {now.strftime('%H:%M')}"
    )
    headers: Dict[str, str] = {
        "Content-Type": "text/plain; charset=utf-8",
        "Title": f"BTC {change_pct:+.1f}% {level}",
        "Tags": "chart_with_downwards_trend" if change_pct < 0 else "chart_with_upwards_trend",
        "Priority": priority,
    }
    bearer = _read_toml_str(SECRETS_TOML, "ntfy_bearer_token")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    ok, msg = _http_post(ntfy_url, body.encode("utf-8"), headers)
    state["last_alert_time"] = now_iso
    state["last_alert_pct"] = round(change_pct, 2)
    _save_state(state)
    print(f"[{'OK' if ok else 'WARN'}] ntfy {msg}: BTC {change_pct:+.2f}% {level}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
