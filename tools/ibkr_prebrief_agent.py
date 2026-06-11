#!/usr/bin/env python3
"""IBKR US Stock pre-session briefing via Ollama LLM.

Reads last N days of ibkr_trade_log_*.csv (synced from VM by ibkr_vm_sync.sh),
builds pattern statistics, calls Ollama, and sends the result via ntfy.
Designed to run at 22:15 JST (30 min before US market open at 09:30 ET).
"""
from __future__ import annotations

import csv
import glob
import json
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MAIN_DIR = Path(__file__).resolve().parents[1]
IBKR_LOGS_DIR = MAIN_DIR / ".local_llm" / "ibkr" / "logs"
SECRETS_TOML = MAIN_DIR / ".streamlit" / "secrets.toml"
OUT_DIR = MAIN_DIR / ".local_llm" / "ibkr" / "prebrief"
LATEST_PATH = OUT_DIR / "prebrief_latest.json"

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_TIMEOUT_SEC = 300
DEFAULT_MODEL = "qwen2.5:0.5b"
DEFAULT_LOOKBACK_DAYS = 14
MAX_CHARS = 700


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_toml_str(key: str) -> str:
    if not SECRETS_TOML.exists():
        return ""
    for line in SECRETS_TOML.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            return v if v and v != "***MASKED***" else ""
    return ""


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _parse_note(note: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for token in note.split():
        if "=" in token:
            k, _, v = token.partition("=")
            out[k.strip()] = v.strip()
    return out


def _write_output(payload: Dict[str, Any], out_path: Path) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    out_path.write_text(text, encoding="utf-8")
    LATEST_PATH.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Trade log parsing
# ---------------------------------------------------------------------------

def _load_trade_pairs(logs_dir: Path, lookback_days: int) -> List[Dict[str, Any]]:
    """Load completed entry+exit pairs from ibkr_trade_log_*.csv."""
    cutoff = (date.today() - timedelta(days=lookback_days)).strftime("%Y%m%d")
    files = sorted(glob.glob(str(logs_dir / "ibkr_trade_log_*.csv")))

    entries: Dict[str, Dict] = {}
    pairs: List[Dict[str, Any]] = []

    for f in files:
        day = Path(f).stem.replace("ibkr_trade_log_", "")
        if day < cutoff:
            continue
        try:
            rows = list(csv.DictReader(open(f, encoding="utf-8-sig")))
        except Exception:
            continue
        for row in rows:
            result = row.get("result", "")
            note = row.get("note", "")
            m = re.search(r"pos_id=(\S+)", note)
            pos_id = m.group(1) if m else ""

            if result == "PAPER" and pos_id:
                entries[pos_id] = {"row": row, "note": _parse_note(note), "day": day}

            elif result.startswith("PAPER_EXIT") and pos_id and pos_id in entries:
                entry = entries.pop(pos_id)
                en = entry["note"]
                ex_note = _parse_note(note)

                if result == "PAPER_EXIT_TP":
                    outcome = "TP"
                elif result == "PAPER_EXIT_SL":
                    outcome = "SL"
                else:
                    outcome = "TIMEOUT"

                entry_time_str = en.get("entry_time") or entry["row"].get("time", "")
                try:
                    hour = int(entry_time_str[11:13])  # UTC hour from ISO string
                    # Convert UTC → ET (subtract 4 for EDT)
                    hour = (hour - 4) % 24
                except Exception:
                    hour = -1

                try:
                    ret_pct = _safe_float(ex_note.get("current_fav") or ex_note.get("best_fav") or 0.0)
                except Exception:
                    ret_pct = 0.0

                pairs.append({
                    "day": entry["day"],
                    "pos_id": pos_id,
                    "side": row.get("side") or entry["row"].get("side", ""),
                    "outcome": outcome,
                    "ret_pct": ret_pct,
                    "hour_et": hour,
                    "symbol": en.get("symbol", "?"),
                    "sma_fast": en.get("sma_fast", "?"),
                    "sma_slow": en.get("sma_slow", "?"),
                    "trend": entry["row"].get("trend", "?"),
                })

    return sorted(pairs, key=lambda x: (x["day"], x["pos_id"]))


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _wr_avg(results: List[Tuple[str, float]]) -> Tuple[int, float, float]:
    if not results:
        return 0, 0.0, 0.0
    wins = sum(1 for o, _ in results if o == "TP")
    avg = sum(r for _, r in results) / len(results)
    return len(results), round(wins / len(results) * 100, 1), round(avg, 4)


def _build_stats(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not pairs:
        return {}

    by_side: Dict[str, List] = defaultdict(list)
    by_hour: Dict[int, List] = defaultdict(list)
    by_trend: Dict[str, List] = defaultdict(list)
    by_outcome: Dict[str, int] = defaultdict(int)

    for p in pairs:
        t = (p["outcome"], p["ret_pct"])
        by_side[p["side"]].append(t)
        if p["hour_et"] >= 0:
            by_hour[p["hour_et"]].append(t)
        by_trend[p["trend"]].append(t)
        by_outcome[p["outcome"]] += 1

    def _fmt(d: Dict) -> List[str]:
        rows = []
        for k, v in sorted(d.items()):
            n, wr, avg = _wr_avg(v)
            rows.append(f"  {k}: n={n} WR={wr}% avg={avg:+.3f}%")
        return rows

    recent = pairs[-5:]
    recent_seq = " ".join("✓" if p["outcome"] == "TP" else "✗" for p in recent)

    return {
        "total": len(pairs),
        "overall": _wr_avg([(p["outcome"], p["ret_pct"]) for p in pairs]),
        "by_side": _fmt(by_side),
        "by_hour": [
            f"  {h}h ET: n={_wr_avg(v)[0]} WR={_wr_avg(v)[1]}% avg={_wr_avg(v)[2]:+.3f}%"
            for h, v in sorted(by_hour.items())
        ],
        "by_trend": _fmt(by_trend),
        "recent_seq": recent_seq,
        "recent_detail": [
            f"  {p['day']} {p['hour_et']}h ET {p['side']} {p['symbol']} trend={p['trend']} → {p['outcome']} ({p['ret_pct']:+.3f}%)"
            for p in recent
        ],
        "outcome_counts": dict(by_outcome),
    }


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(stats: Dict[str, Any], lookback_days: int) -> str:
    n, wr, avg = stats.get("overall", (0, 0.0, 0.0))
    total = stats.get("total", 0)
    side_lines = stats.get("by_side", [])[:2]
    hour_lines = stats.get("by_hour", [])[:6]
    trend_lines = stats.get("by_trend", [])[:3]
    recent_seq = stats.get("recent_seq", "")
    recent_last = stats.get("recent_detail", [])[-3:]

    lines = [
        f"US株取引{total}件({lookback_days}日) WR={wr}% avg={avg:+.3f}%",
        "売買別: " + " / ".join(l.strip() for l in side_lines),
        "時間別(ET): " + " / ".join(l.strip() for l in hour_lines),
        "トレンド別: " + " / ".join(l.strip() for l in trend_lines),
        f"直近: {recent_seq}",
    ] + recent_last + [
        "---",
        "US株トレードアナリストとして100字以内で回答:",
        "①本日バイアス(up/down/flat) ②有効パターン ③注意条件",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

def _call_ollama(prompt: str, model: str, timeout_sec: int) -> str:
    # ウォームアップ(2026-06-12): 1日1回実行のため毎回コールドスタートし本呼び出しがタイムアウトしていた対策。
    # 小さな生成でモデルを事前ロードする(失敗は無視・本呼び出しがそのまま再試行になる)。
    try:
        _wreq = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/generate",
            data=json.dumps({"model": model, "prompt": "ok", "stream": False,
                             "options": {"num_predict": 1}}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(_wreq, timeout=240.0):
            pass
    except Exception:
        pass
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=payload, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    text = str(data.get("response") or "").strip()
    if not text:
        raise ValueError("empty response from ollama")
    return text[:MAX_CHARS].rstrip() + ("..." if len(text) > MAX_CHARS else "")


# ---------------------------------------------------------------------------
# ntfy
# ---------------------------------------------------------------------------

def _send_ntfy(title: str, body: str) -> bool:
    url = _read_toml_str("ntfy_topic_url")
    if not url:
        print("[ibkr_prebrief] ntfy_topic_url not configured, skip")
        return False
    bearer = _read_toml_str("ntfy_bearer_token")
    safe_title = title.encode("ascii", errors="replace").decode("ascii")
    headers: Dict[str, str] = {
        "Content-Type": "text/plain; charset=utf-8",
        "Title": safe_title,
        "Priority": "default",
        "Tags": "chart_increasing,robot",
    }
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        req = urllib.request.Request(url, data=body.encode("utf-8"),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10.0) as r:
            print(f"[ibkr_prebrief] ntfy sent: HTTP {r.status}")
            return True
    except urllib.error.HTTPError as e:
        print(f"[ibkr_prebrief] ntfy HTTP {e.code}")
        return False
    except Exception as e:
        print(f"[ibkr_prebrief] ntfy error: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="IBKR pre-session LLM briefing")
    p.add_argument("--days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--dry-run", action="store_true", help="Print prompt only, no LLM call or ntfy")
    p.add_argument("--no-ntfy", action="store_true")
    p.add_argument("--logs-dir", default=str(IBKR_LOGS_DIR))
    args = p.parse_args(argv)

    logs_dir = Path(args.logs_dir)
    print(f"[ibkr_prebrief] loading {args.days}d trade pairs from {logs_dir}")
    pairs = _load_trade_pairs(logs_dir, args.days)
    print(f"[ibkr_prebrief] loaded {len(pairs)} completed trades")

    if len(pairs) < 3:
        print("[ibkr_prebrief] not enough trades (need ≥3). Sending minimal ntfy.")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = OUT_DIR / f"prebrief_{ts}.json"
        payload = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "lookback_days": args.days,
            "model": args.model,
            "trade_count": len(pairs),
            "stats_overall": None,
            "llm_text": "[LLM skipped: insufficient_data]",
            "status": "insufficient_data",
        }
        _write_output(payload, out_path)
        print(f"[ibkr_prebrief] saved to {out_path}")
        if not args.dry_run and not args.no_ntfy:
            _send_ntfy(
                "[IBKR prebrief] データ不足",
                f"直近{args.days}日の完了取引が{len(pairs)}件のみ。"
                "US市場開始(ET 09:30)まで取引データが蓄積されるのを待ちます。",
            )
        return 0

    stats = _build_stats(pairs)
    prompt = _build_prompt(stats, args.days)

    if args.dry_run:
        print("=== PROMPT ===")
        print(prompt)
        return 0

    print(f"[ibkr_prebrief] calling ollama model={args.model}")
    try:
        llm_text = _call_ollama(prompt, args.model, OLLAMA_TIMEOUT_SEC)
        print(f"[ibkr_prebrief] LLM ({len(llm_text)} chars): {llm_text[:100]}...")
    except Exception as e:
        print(f"[ibkr_prebrief] LLM error: {e}")
        llm_text = f"[LLM error: {e}]"

    # Save output
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"prebrief_{ts}.json"
    n, wr, avg = stats.get("overall", (0, 0.0, 0.0))
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lookback_days": args.days,
        "model": args.model,
        "trade_count": len(pairs),
        "stats_overall": stats.get("overall"),
        "llm_text": llm_text,
        "status": "ok",
    }
    _write_output(payload, out_path)
    print(f"[ibkr_prebrief] saved to {out_path}")

    if args.no_ntfy:
        return 0

    title = f"[IBKR prebrief] {n}t WR={wr}%"
    _send_ntfy(title, llm_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
