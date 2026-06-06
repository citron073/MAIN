#!/usr/bin/env python3
"""
Signal Scanner Outcome Tracker — check if past SIGNAL_ONLY candidates hit SL or TP.

Reads all signal_weekly_*.json files in review_out/ (up to last N weeks),
fetches latest daily close via yfinance, and determines whether each candidate
hit their TP, SL, is still open, or expired.

Saves to review_out/signal_scanner_outcomes.csv (upsert: already-final rows kept).

Usage:
    python3 signal_scanner_outcome.py           # check all, print summary
    python3 signal_scanner_outcome.py --dry-run # print only, no file save
    python3 signal_scanner_outcome.py --weeks 4 # look back N weeks (default: 8)
    python3 signal_scanner_outcome.py --ntfy    # send summary to ntfy
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
REVIEW_OUT = ROOT / "review_out"
OUTCOMES_CSV = REVIEW_OUT / "signal_scanner_outcomes.csv"
FEEDBACK_JSON = REVIEW_OUT / "signal_scanner_feedback_latest.json"
SECRETS_FILE = ROOT / ".streamlit" / "secrets.toml"
NOTIFY_STATE = ROOT / ".streamlit" / "notification_policy_state.json"

try:
    from tools.notification_policy import LEVEL_INFO, post_ntfy, read_toml_str
except ModuleNotFoundError:
    sys.path.insert(0, str(ROOT))
    from tools.notification_policy import LEVEL_INFO, post_ntfy, read_toml_str  # type: ignore

OUTCOME_HEADERS = [
    "scanned_at_jst", "symbol", "market_type", "signal",
    "entry_price", "sl_price", "tp_price", "confidence",
    "outcome", "current_price", "pnl_pct", "elapsed_days",
    "checked_at_jst",
]

SIGNAL_FILE_GLOB = "signal_weekly_*.json"
EXPIRY_DAYS = 7  # treat as EXPIRED after this many days without hitting SL/TP
FX_PRIORITY_MIN_CLOSED = 5

# Note: intraday SL/TP hits are NOT tracked (daily close only).
# This means HIT_SL/HIT_TP reflect end-of-day prices only.


def _now_jst() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


def _now_jst_str() -> str:
    return _now_jst().strftime("%Y-%m-%d %H:%M:%S")


def _fetch_current_price(symbol: str, market_type: str) -> Optional[float]:
    """Fetch latest close price from yfinance."""
    try:
        import yfinance as yf  # type: ignore
        if market_type == "FX":
            fx_map = {
                "USDJPY": "USDJPY=X", "EURUSD": "EURUSD=X",
                "GBPJPY": "GBPJPY=X", "EURJPY": "EURJPY=X", "GBPUSD": "GBPUSD=X",
            }
            ticker = fx_map.get(symbol, symbol + "=X")
        else:
            ticker = symbol
        df = yf.Ticker(ticker).history(period="5d", interval="1d")
        if df is None or len(df) == 0:
            return None
        return float(df["Close"].values[-1])
    except Exception as exc:
        print(f"  [yfinance] {symbol}: {exc}", file=sys.stderr)
        return None


def _determine_outcome(
    signal: str,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    current_price: float,
    elapsed_days: float,
) -> str:
    """Return HIT_TP / HIT_SL / OPEN / EXPIRED based on daily close."""
    if signal == "BUY":
        if current_price >= tp_price:
            return "HIT_TP"
        if current_price <= sl_price:
            return "HIT_SL"
    else:  # SELL
        if current_price <= tp_price:
            return "HIT_TP"
        if current_price >= sl_price:
            return "HIT_SL"
    return "EXPIRED" if elapsed_days >= EXPIRY_DAYS else "OPEN"


def _load_signal_files(weeks: int = 8) -> List[Dict[str, Any]]:
    cutoff = _now_jst() - timedelta(weeks=weeks)
    all_candidates: List[Dict[str, Any]] = []
    for f in sorted(REVIEW_OUT.glob(SIGNAL_FILE_GLOB)):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            gen_str = data.get("generated_at_jst", "")
            try:
                if datetime.strptime(gen_str[:19], "%Y-%m-%d %H:%M:%S") < cutoff:
                    continue
            except ValueError:
                pass
            for c in data.get("candidates", []):
                c["_source_file"] = f.name
                all_candidates.append(c)
        except Exception as exc:
            print(f"  [outcome] error reading {f.name}: {exc}", file=sys.stderr)
    return all_candidates


def _load_existing_outcomes() -> Dict[str, Dict]:
    existing: Dict[str, Dict] = {}
    if not OUTCOMES_CSV.exists():
        return existing
    try:
        with OUTCOMES_CSV.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = f"{row.get('scanned_at_jst','')}-{row.get('symbol','')}"
                existing[key] = dict(row)
    except Exception:
        pass
    return existing


def check_outcomes(candidates: List[Dict]) -> List[Dict]:
    existing = _load_existing_outcomes()
    now = _now_jst()
    now_str = _now_jst_str()
    price_cache: Dict[str, Optional[float]] = {}
    results: List[Dict] = []

    for c in candidates:
        symbol = c.get("symbol", "")
        market_type = c.get("market_type", "STOCK")
        signal = c.get("signal", "")
        scanned_at = c.get("scanned_at_jst", "")
        key = f"{scanned_at}-{symbol}"

        # Skip already-final outcomes (don't re-check)
        existing_row = existing.get(key, {})
        if existing_row.get("outcome") in ("HIT_TP", "HIT_SL", "EXPIRED"):
            continue

        try:
            entry_price = float(c.get("entry_price", 0))
            sl_price = float(c.get("sl_price", 0))
            tp_price = float(c.get("tp_price", 0))
            conf = int(c.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        if not (entry_price and sl_price and tp_price):
            continue

        elapsed_days = 0.0
        try:
            scanned_dt = datetime.strptime(scanned_at[:19], "%Y-%m-%d %H:%M:%S")
            elapsed_days = (now - scanned_dt).total_seconds() / 86400
        except ValueError:
            pass

        if symbol not in price_cache:
            price_cache[symbol] = _fetch_current_price(symbol, market_type)
        current_price = price_cache[symbol]
        if current_price is None:
            continue

        outcome = _determine_outcome(signal, entry_price, sl_price, tp_price, current_price, elapsed_days)
        pnl_pct = round(
            (current_price - entry_price) / entry_price * 100 if signal == "BUY"
            else (entry_price - current_price) / entry_price * 100,
            2,
        )

        results.append({
            "scanned_at_jst": scanned_at,
            "symbol": symbol,
            "market_type": market_type,
            "signal": signal,
            "entry_price": entry_price,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "confidence": conf,
            "outcome": outcome,
            "current_price": round(current_price, 6),
            "pnl_pct": pnl_pct,
            "elapsed_days": round(elapsed_days, 1),
            "checked_at_jst": now_str,
        })
    return results


def save_outcomes(results: List[Dict]) -> None:
    REVIEW_OUT.mkdir(parents=True, exist_ok=True)
    existing_rows: List[Dict] = []
    if OUTCOMES_CSV.exists():
        try:
            with OUTCOMES_CSV.open(encoding="utf-8") as f:
                existing_rows = list(csv.DictReader(f))
        except Exception:
            pass

    idx: Dict[str, int] = {
        f"{r.get('scanned_at_jst','')}-{r.get('symbol','')}": i
        for i, r in enumerate(existing_rows)
    }
    for r in results:
        key = f"{r['scanned_at_jst']}-{r['symbol']}"
        if key in idx:
            existing_rows[idx[key]] = r
        else:
            existing_rows.append(r)

    with OUTCOMES_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTCOME_HEADERS, extrasaction="ignore")
        w.writeheader()
        w.writerows(existing_rows)


def _analyze_by_confidence(all_rows: List[Dict]) -> List[Dict]:
    """AF: Group closed outcomes by confidence band and compute WR per band."""
    bands = [
        ("high",   80, 101, "80-100%"),
        ("medium", 60, 80,  "60-79%"),
        ("low",    0,  60,  "<60%"),
    ]
    result = []
    for band_id, lo, hi, label in bands:
        rows = [
            r for r in all_rows
            if r.get("outcome") in ("HIT_TP", "HIT_SL")
            and lo <= int(r.get("confidence", 0)) < hi
        ]
        if not rows:
            result.append({"band": label, "trades": 0, "wr": None, "avg_pnl": None})
            continue
        tp = sum(1 for r in rows if r.get("outcome") == "HIT_TP")
        wr = tp / len(rows) * 100
        try:
            avg_pnl = sum(float(r.get("pnl_pct", 0)) for r in rows) / len(rows)
        except Exception:
            avg_pnl = 0.0
        result.append({"band": label, "trades": len(rows), "wr": wr, "avg_pnl": avg_pnl})
    return result


def _confidence_threshold_hint(bands: List[Dict]) -> Optional[str]:
    """AF: Suggest adjusting the confidence threshold based on band performance."""
    high = next((b for b in bands if b["band"] == "80-100%"), None)
    medium = next((b for b in bands if b["band"] == "60-79%"), None)
    low = next((b for b in bands if b["band"] == "<60%"), None)

    # Only suggest when there's enough data (min 5 trades per band for recommendation)
    hints = []
    if low and low["trades"] >= 5 and low["wr"] is not None and low["wr"] < 40:
        hints.append("→ 信頼スコア<60%帯の勝率が低い。MIN_CONFIDENCEを60以上に引き上げ推奨")
    if medium and medium["trades"] >= 5 and medium["wr"] is not None and medium["wr"] < 45:
        hints.append("→ 60-79%帯の勝率も低い。MIN_CONFIDENCEを80以上に引き上げを検討")
    if high and high["trades"] >= 5 and high["wr"] is not None and high["wr"] >= 55:
        hints.append("→ 80-100%帯の勝率が高い。高信頼度シグナルを優先するとよい")
    return "\n".join(hints) if hints else None


def save_outcomes_json(all_rows: List[Dict], bands: List[Dict]) -> None:
    """AG: Write signal_scanner_outcomes_latest.json for dashboard consumption."""
    REVIEW_OUT.mkdir(parents=True, exist_ok=True)
    closed = [r for r in all_rows if r.get("outcome") in ("HIT_TP", "HIT_SL")]
    hit_tp = [r for r in all_rows if r.get("outcome") == "HIT_TP"]
    hit_sl = [r for r in all_rows if r.get("outcome") == "HIT_SL"]
    open_ = [r for r in all_rows if r.get("outcome") == "OPEN"]
    expired = [r for r in all_rows if r.get("outcome") == "EXPIRED"]

    wr = len(hit_tp) / len(closed) * 100 if closed else None
    try:
        avg_pnl = sum(float(r.get("pnl_pct", 0)) for r in closed) / len(closed) if closed else None
    except Exception:
        avg_pnl = None

    # Most recent 20 closed/open rows for dashboard table
    recent = sorted(all_rows, key=lambda r: r.get("checked_at_jst", ""), reverse=True)[:20]

    payload = {
        "generated_at_jst": _now_jst_str(),
        "total": len(all_rows),
        "hit_tp": len(hit_tp),
        "hit_sl": len(hit_sl),
        "open_count": len(open_),
        "expired_count": len(expired),
        "closed_count": len(closed),
        "win_rate_pct": round(wr, 1) if wr is not None else None,
        "avg_pnl_pct": round(avg_pnl, 2) if avg_pnl is not None else None,
        "confidence_bands": bands,
        "recent_rows": recent,
    }
    out_path = REVIEW_OUT / "signal_scanner_outcomes_latest.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"[outcome] JSON → {out_path.name}")


def _summarize_group(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    closed = [r for r in rows if r.get("outcome") in ("HIT_TP", "HIT_SL")]
    if not closed:
        return {"closed_count": 0, "win_rate_pct": None, "avg_pnl_pct": None}
    tp = sum(1 for r in closed if r.get("outcome") == "HIT_TP")
    wr = tp / len(closed) * 100
    avg_pnl = sum(float(r.get("pnl_pct", 0) or 0) for r in closed) / len(closed)
    return {
        "closed_count": len(closed),
        "win_rate_pct": round(wr, 1),
        "avg_pnl_pct": round(avg_pnl, 2),
    }


def build_feedback_payload(all_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    by_side: Dict[str, List[Dict[str, Any]]] = {}
    by_market: Dict[str, List[Dict[str, Any]]] = {}
    for row in all_rows:
        if row.get("outcome") not in ("HIT_TP", "HIT_SL"):
            continue
        symbol = str(row.get("symbol", "")).strip()
        side = str(row.get("signal", "")).strip().upper()
        market = str(row.get("market_type", "")).strip().upper()
        if symbol:
            by_symbol.setdefault(symbol, []).append(row)
        if side:
            by_side.setdefault(side, []).append(row)
        if market:
            by_market.setdefault(market, []).append(row)

    symbol_stats = {
        key: _summarize_group(rows)
        for key, rows in sorted(by_symbol.items())
    }
    side_stats = {
        key: _summarize_group(rows)
        for key, rows in sorted(by_side.items())
    }
    market_type_stats = {
        key: _summarize_group(rows)
        for key, rows in sorted(by_market.items())
    }

    fx = market_type_stats.get("FX", {})
    stock = market_type_stats.get("STOCK", {})
    fx_closed = int(fx.get("closed_count") or 0)
    stock_closed = int(stock.get("closed_count") or 0)
    fx_priority = {
        "preferred_market": "NEUTRAL",
        "reason": f"closedサンプル不足 (min={FX_PRIORITY_MIN_CLOSED}, FX={fx_closed}, STOCK={stock_closed})",
        "score_adjustment": 0,
        "min_closed_required": FX_PRIORITY_MIN_CLOSED,
    }
    if fx_closed >= FX_PRIORITY_MIN_CLOSED and stock_closed >= FX_PRIORITY_MIN_CLOSED:
        fx_wr = float(fx.get("win_rate_pct") or 0)
        stock_wr = float(stock.get("win_rate_pct") or 0)
        if fx_wr >= stock_wr + 8:
            fx_priority = {
                "preferred_market": "FX",
                "reason": f"FX WR {fx_wr:.1f}% > STOCK WR {stock_wr:.1f}%",
                "score_adjustment": 5,
                "min_closed_required": FX_PRIORITY_MIN_CLOSED,
            }
        elif stock_wr >= fx_wr + 8:
            fx_priority = {
                "preferred_market": "STOCK",
                "reason": f"STOCK WR {stock_wr:.1f}% > FX WR {fx_wr:.1f}%",
                "score_adjustment": -5,
                "min_closed_required": FX_PRIORITY_MIN_CLOSED,
            }
        else:
            fx_priority = {
                "preferred_market": "NEUTRAL",
                "reason": f"FX WR {fx_wr:.1f}% / STOCK WR {stock_wr:.1f}% で大差なし",
                "score_adjustment": 0,
                "min_closed_required": FX_PRIORITY_MIN_CLOSED,
            }

    return {
        "generated_at_jst": _now_jst_str(),
        "closed_count": sum(v.get("closed_count", 0) for v in symbol_stats.values()),
        "by_symbol": symbol_stats,
        "by_side": side_stats,
        "by_market_type": market_type_stats,
        "fx_priority": fx_priority,
    }


def save_feedback_json(all_rows: List[Dict[str, Any]]) -> None:
    payload = build_feedback_payload(all_rows)
    FEEDBACK_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"[outcome] feedback → {FEEDBACK_JSON.name}")


def _format_summary(results: List[Dict], all_rows: List[Dict]) -> str:
    closed = [r for r in all_rows if r.get("outcome") in ("HIT_TP", "HIT_SL")]
    hit_tp = [r for r in all_rows if r.get("outcome") == "HIT_TP"]
    hit_sl = [r for r in all_rows if r.get("outcome") == "HIT_SL"]
    open_ = [r for r in all_rows if r.get("outcome") == "OPEN"]
    expired = [r for r in all_rows if r.get("outcome") == "EXPIRED"]

    lines = [
        f"[Signal Outcome] {_now_jst_str()} JST",
        f"全時期: TP={len(hit_tp)} SL={len(hit_sl)} OPEN={len(open_)} EXPIRED={len(expired)}  計={len(all_rows)}件",
    ]
    if closed:
        wr = len(hit_tp) / len(closed) * 100
        try:
            avg_pnl = sum(float(r.get("pnl_pct", 0)) for r in closed) / len(closed)
        except Exception:
            avg_pnl = 0.0
        lines.append(f"勝率(TP/SL): {wr:.1f}%  平均PnL: {avg_pnl:+.2f}%  ({len(closed)}件決着)")

    # AF: confidence band analysis
    bands = _analyze_by_confidence(all_rows)
    bands_with_data = [b for b in bands if b["trades"] > 0]
    if bands_with_data:
        lines.append("\n信頼スコア帯別成績 (決着件のみ):")
        for b in bands:
            if b["trades"] == 0:
                lines.append(f"  conf {b['band']:8s}  データなし")
            else:
                lines.append(
                    f"  conf {b['band']:8s}  {b['trades']:3d}件  WR={b['wr']:.0f}%  avgPnL={b['avg_pnl']:+.2f}%"
                )
        hint = _confidence_threshold_hint(bands)
        if hint:
            lines.append(f"\n💡 閾値調整ヒント:")
            lines.append(hint)

    if results:
        lines.append(f"\n今回更新: {len(results)}件")
        for r in sorted(results, key=lambda x: x.get("outcome", "")):
            icon = "✅" if r["outcome"] == "HIT_TP" else "🛑" if r["outcome"] == "HIT_SL" else "⏳" if r["outcome"] == "OPEN" else "⏰"
            lines.append(
                f"  {icon} {r['symbol']:6s} {r['signal']:4s}  {r['outcome']:10s}  "
                f"pnl={r['pnl_pct']:+.2f}%  conf={r['confidence']}%  {r['elapsed_days']:.1f}d"
            )
    return "\n".join(lines)


def _send_ntfy(text: str) -> None:
    ntfy_url = read_toml_str(SECRETS_FILE, "ntfy_topic_url")
    if not ntfy_url:
        return
    bearer = read_toml_str(SECRETS_FILE, "ntfy_bearer_token")
    level = LEVEL_INFO
    body = f"event_level={level}\n{text[:7600]}"
    try:
        ok, msg = post_ntfy(
            ntfy_url,
            "Signal Outcome 精度レポート",
            body,
            level=level,
            tags="bar_chart,signal_outcome",
            bearer=bearer,
            state_path=NOTIFY_STATE,
            event_code=f"signal_outcome_{_now_jst().strftime('%Y%m%d')}",
        )
        print(f"[outcome] ntfy {msg}")
    except Exception as exc:
        print(f"[outcome] ntfy error: {exc}", file=sys.stderr)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Check signal scanner outcome accuracy")
    ap.add_argument("--dry-run", action="store_true", help="Print only, no file save")
    ap.add_argument("--weeks", type=int, default=8, help="Look back N weeks (default: 8)")
    ap.add_argument("--ntfy", action="store_true", help="Send summary via ntfy")
    args = ap.parse_args()

    candidates = _load_signal_files(weeks=args.weeks)
    if not candidates:
        print(f"[outcome] No signal files found in {REVIEW_OUT}/signal_weekly_*.json")
        sys.exit(0)

    print(f"[outcome] Loaded {len(candidates)} candidates from signal_weekly_*.json")
    results = check_outcomes(candidates)

    if not args.dry_run:
        save_outcomes(results)
        print(f"[outcome] saved → {OUTCOMES_CSV.name}")

    # Load full history for summary
    all_rows: List[Dict] = []
    if OUTCOMES_CSV.exists() and not args.dry_run:
        try:
            with OUTCOMES_CSV.open(encoding="utf-8") as f:
                all_rows = list(csv.DictReader(f))
        except Exception:
            all_rows = results
    else:
        all_rows = results

    # AF/AG: confidence band analysis + save JSON for dashboard
    bands = _analyze_by_confidence(all_rows)
    summary = _format_summary(results, all_rows)
    print("\n" + summary)

    if not args.dry_run:
        save_outcomes_json(all_rows, bands)
        save_feedback_json(all_rows)

    if args.ntfy and not args.dry_run:
        _send_ntfy(summary)
