#!/usr/bin/env python3
"""Session pre-briefing via LLM pattern analysis.

Reads last N days of trade logs, builds a statistical pattern summary,
feeds it to a local LLM (Ollama), and sends the result via ntfy.
Designed to run at 09:45 JST before the 10:00 trading session.
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
LOGS_DIR = MAIN_DIR.parent / "logs"
SECRETS_TOML = MAIN_DIR / ".streamlit" / "secrets.toml"
OUT_DIR = MAIN_DIR / "prebrief_out"

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_TIMEOUT_SEC = 200
DEFAULT_MODEL = "qwen2.5:0.5b"
DEFAULT_LOOKBACK_DAYS = 14
MAX_CHARS = 800


# ---------------------------------------------------------------------------
# Secrets / config helpers
# ---------------------------------------------------------------------------

def _read_toml_str(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            return v if v not in ("", "***MASKED***") else ""
    return ""


def _read_control(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    out: Dict[str, str] = {}
    try:
        for row in csv.DictReader(path.open(newline="", encoding="utf-8-sig")):
            k = str(row.get("key", "") or "").strip()
            if k:
                out[k] = str(row.get("value", "") or "").strip()
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# Trade log parsing
# ---------------------------------------------------------------------------

def _parse_note(note: str) -> Dict[str, str]:
    """Parse key=value tokens from a trade log note field."""
    out: Dict[str, str] = {}
    for token in note.split():
        if "=" in token:
            k, _, v = token.partition("=")
            out[k.strip()] = v.strip()
    return out


def _load_trade_pairs(logs_dir: Path, lookback_days: int) -> List[Dict[str, Any]]:
    """Load completed entry+exit pairs from trade_log_*.csv files."""
    cutoff = (date.today() - timedelta(days=lookback_days)).strftime("%Y%m%d")
    files = sorted(glob.glob(str(logs_dir / "trade_log_*.csv")))

    entries: Dict[str, Dict] = {}
    pairs: List[Dict[str, Any]] = []

    for f in files:
        day = Path(f).stem.replace("trade_log_", "")
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

                # Determine outcome
                if result == "PAPER_EXIT_TP":
                    outcome = "TP"
                elif result == "PAPER_EXIT_SL":
                    outcome = "SL"
                else:
                    outcome = "TIMEOUT"

                # Entry hour
                entry_time_str = en.get("entry_time") or entry["row"].get("time", "")
                try:
                    hour = int(entry_time_str[11:13])
                except Exception:
                    hour = -1

                # Use current_fav (actual exit P&L). best_fav is max-advance and stays positive even on SL.
                try:
                    ret_pct = float(ex_note.get("current_fav") or ex_note.get("ret_pct") or ex_note.get("best_fav") or 0.0)
                except Exception:
                    ret_pct = 0.0

                pairs.append({
                    "day": entry["day"],
                    "pos_id": pos_id,
                    "side": row.get("side") or entry["row"].get("side", ""),
                    "outcome": outcome,
                    "ret_pct": ret_pct,
                    "hour": hour,
                    "ai_score": _safe_float(en.get("score")),
                    "htf15": en.get("htf15_bias", "?"),
                    "htf60": en.get("htf60_bias", "?"),
                    "phase": en.get("phase", "?"),
                    "phase_momentum": en.get("phase_momentum", "?"),
                    "cp_name": en.get("cp_name", "NONE"),
                    "cp_bias": en.get("cp_bias", "?"),
                    "cp_confirmed": en.get("cp_confirmed", "0"),
                    "trend": row.get("trend") or entry["row"].get("trend", "?"),
                    "rsi_zone": en.get("ti_rsi_zone", "?"),
                    "bb_zone": en.get("ti_bb_zone", "?"),
                })

    return sorted(pairs, key=lambda x: (x["day"], x["pos_id"]))


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Statistics builder
# ---------------------------------------------------------------------------

def _wr_avg(results: List[Tuple[str, float]]) -> Tuple[int, float, float]:
    """Returns (count, win_rate_pct, avg_ret_pct)."""
    if not results:
        return 0, 0.0, 0.0
    wins = sum(1 for o, _ in results if o == "TP")
    avg = sum(r for _, r in results) / len(results)
    return len(results), round(wins / len(results) * 100, 1), round(avg, 4)


def _build_stats(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not pairs:
        return {}

    by_cp: Dict[str, List] = defaultdict(list)
    by_htf: Dict[str, List] = defaultdict(list)
    by_phase: Dict[str, List] = defaultdict(list)
    by_hour: Dict[int, List] = defaultdict(list)
    by_side: Dict[str, List] = defaultdict(list)
    by_trend: Dict[str, List] = defaultdict(list)

    for p in pairs:
        t = (p["outcome"], p["ret_pct"])
        by_cp[p["cp_name"]].append(t)
        htf_key = f"HTF15={p['htf15']} HTF60={p['htf60']}"
        by_htf[htf_key].append(t)
        by_phase[p["phase"]].append(t)
        if p["hour"] >= 0:
            by_hour[p["hour"]].append(t)
        by_side[p["side"]].append(t)
        by_trend[p["trend"]].append(t)

    def _fmt_group(d: Dict, min_n: int = 1) -> List[str]:
        rows = []
        for k, v in sorted(d.items()):
            n, wr, avg = _wr_avg(v)
            if n >= min_n:
                rows.append(f"  {k}: n={n} WR={wr}% avg={avg:+.3f}%")
        return rows

    recent = pairs[-5:]
    recent_seq = " ".join(
        ("✓" if p["outcome"] == "TP" else "✗") for p in recent
    )

    return {
        "total": len(pairs),
        "overall": _wr_avg([(p["outcome"], p["ret_pct"]) for p in pairs]),
        "by_cp": _fmt_group(by_cp),
        "by_htf": _fmt_group(by_htf),
        "by_phase": _fmt_group(by_phase),
        "by_hour": [
            f"  {h}h: n={_wr_avg(v)[0]} WR={_wr_avg(v)[1]}% avg={_wr_avg(v)[2]:+.3f}%"
            for h, v in sorted(by_hour.items())
            if _wr_avg(v)[0] >= 1
        ],
        "by_side": _fmt_group(by_side),
        "by_trend": _fmt_group(by_trend),
        "recent_seq": recent_seq,
        "recent_detail": [
            f"  {p['day']} {p['hour']}h {p['side']} {p['cp_name']} htf15={p['htf15']} htf60={p['htf60']} → {p['outcome']} ({p['ret_pct']:+.3f}%)"
            for p in recent
        ],
    }


# ---------------------------------------------------------------------------
# LLM prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(stats: Dict[str, Any], lookback_days: int) -> str:
    total = stats.get("total", 0)
    n, wr, avg = stats.get("overall", (0, 0.0, 0.0))

    # Keep prompt concise for small model memory efficiency
    cp_lines = stats.get("by_cp", [])[:4]
    htf_lines = stats.get("by_htf", [])[:4]
    hour_lines = stats.get("by_hour", [])[:4]
    side_lines = stats.get("by_side", [])[:2]
    recent_seq = stats.get("recent_seq", "")
    recent_last = stats.get("recent_detail", [])[-3:]

    lines = [
        f"BTC FX取引{total}件({lookback_days}日) WR={wr}% avg={avg:+.3f}%",
        "CP別: " + " / ".join(l.strip() for l in cp_lines),
        "HTF別: " + " / ".join(l.strip() for l in htf_lines),
        "時間別: " + " / ".join(l.strip() for l in hour_lines),
        "売買: " + " / ".join(l.strip() for l in side_lines),
        f"直近: {recent_seq}",
    ] + recent_last + [
        "---",
        "BTC取引アナリストとして150字以内で回答:",
        "①有効パターン ②回避条件 ③本日バイアス(10-17JST)",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ollama caller
# ---------------------------------------------------------------------------

def _call_ollama(prompt: str, model: str, timeout_sec: int) -> str:
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    text = str(data.get("response") or "").strip()
    if not text:
        raise ValueError("empty response from ollama")
    return text[:MAX_CHARS].rstrip() + ("..." if len(text) > MAX_CHARS else "")


# ---------------------------------------------------------------------------
# ntfy sender
# ---------------------------------------------------------------------------

def _send_ntfy(url: str, bearer: str, title: str, body: str) -> bool:
    # ntfy Title header must be ASCII — encode non-ASCII chars as unicode escapes
    safe_title = title.encode("ascii", errors="replace").decode("ascii")
    headers: Dict[str, str] = {
        "Content-Type": "text/plain; charset=utf-8",
        "Title": safe_title,
        "Priority": "default",
        "Tags": "chart",
    }
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        req = urllib.request.Request(url, data=body.encode("utf-8"),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10.0) as r:
            print(f"[ntfy] sent: HTTP {r.status}")
            return True
    except urllib.error.HTTPError as e:
        print(f"[ntfy] HTTP error {e.code}")
        return False
    except Exception as e:
        print(f"[ntfy] error: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Session pre-briefing LLM")
    p.add_argument("--days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--dry-run", action="store_true", help="Print prompt only, no LLM call")
    p.add_argument("--no-ntfy", action="store_true", help="Skip ntfy notification")
    args = p.parse_args(argv)

    control = _read_control(MAIN_DIR / "CONTROL.csv")
    lookback = int(control.get("prebrief_lookback_days") or args.days)
    model = str(control.get("prebrief_ollama_model") or args.model)

    print(f"[prebrief] loading {lookback}d trade pairs from {LOGS_DIR}")
    pairs = _load_trade_pairs(LOGS_DIR, lookback)
    print(f"[prebrief] loaded {len(pairs)} completed trades")

    if len(pairs) < 3:
        print("[prebrief] not enough trades for analysis (need ≥3), exiting")
        return 0

    stats = _build_stats(pairs)
    prompt = _build_prompt(stats, lookback)

    if args.dry_run:
        print("=== PROMPT ===")
        print(prompt)
        return 0

    print(f"[prebrief] calling ollama model={model}")
    try:
        llm_text = _call_ollama(prompt, model, OLLAMA_TIMEOUT_SEC)
        print(f"[prebrief] LLM response ({len(llm_text)} chars):")
        print(llm_text)
    except Exception as e:
        print(f"[prebrief] LLM error: {e}")
        llm_text = f"[LLM error: {e}]"

    # Save to file
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"prebrief_{ts}.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lookback_days": lookback,
        "model": model,
        "trade_count": len(pairs),
        "stats_overall": stats.get("overall"),
        "llm_text": llm_text,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[prebrief] saved to {out_path}")

    if args.no_ntfy:
        return 0

    ntfy_url = _read_toml_str(SECRETS_TOML, "ntfy_topic_url")
    if not ntfy_url:
        print("[prebrief] ntfy_topic_url not configured, skip")
        return 0

    bearer = _read_toml_str(SECRETS_TOML, "ntfy_bearer_token")
    n, wr, avg = stats.get("overall", (0, 0.0, 0.0))
    title = f"[prebrief] session analysis ({n}t WR={wr}%)"
    _send_ntfy(ntfy_url, bearer, title, llm_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
