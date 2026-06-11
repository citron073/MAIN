#!/usr/bin/env python3
"""IBKR US Stock post-session review agent.

Reads today's ibkr_trade_log_*.csv (synced from VM), builds a session
summary (P&L, WR, trade count), optionally calls Ollama, and sends ntfy.
Designed to run at 07:05 JST (after US market close at 04:00 JST next day).
"""
from __future__ import annotations

import csv
import glob
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MAIN_DIR = Path(__file__).resolve().parents[1]
IBKR_LOGS_DIR = MAIN_DIR / ".local_llm" / "ibkr" / "logs"
SECRETS_TOML = MAIN_DIR / ".streamlit" / "secrets.toml"
OUT_DIR = MAIN_DIR / ".local_llm" / "ibkr" / "review"
LATEST_PATH = OUT_DIR / "review_latest.json"

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_TIMEOUT_SEC = 300
DEFAULT_MODEL = "qwen2.5:0.5b"
MAX_CHARS = 500

JST = timedelta(hours=9)


def _now_jst() -> datetime:
    return datetime.utcnow() + JST


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
# Session data loader
# ---------------------------------------------------------------------------

def _load_today_session(logs_dir: Path, day8: str) -> Dict[str, Any]:
    """Load all trades for a given day and compute session stats."""
    path = logs_dir / f"ibkr_trade_log_{day8}.csv"
    if not path.exists():
        return {"day8": day8, "found": False, "trades": []}

    entries: Dict[str, Dict] = {}
    closed: List[Dict] = []

    try:
        rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    except Exception:
        return {"day8": day8, "found": True, "error": "csv_read_failed", "trades": []}

    for row in rows:
        result = row.get("result", "")
        note = row.get("note", "")
        m = re.search(r"pos_id=(\S+)", note)
        pos_id = m.group(1) if m else ""

        if result in ("PAPER", "LIVE") and pos_id:
            entries[pos_id] = {"row": row, "note": _parse_note(note)}
        elif (result.startswith("PAPER_EXIT") or result.startswith("LIVE_EXIT_")) and pos_id and pos_id in entries:
            entry = entries.pop(pos_id)
            en = entry["note"]
            ex_note = _parse_note(note)

            outcome = "TP" if result in ("PAPER_EXIT_TP", "LIVE_EXIT_TP") else ("SL" if result in ("PAPER_EXIT_SL", "LIVE_EXIT_SL") else "TIMEOUT")
            ret_pct = _safe_float(ex_note.get("current_fav") or ex_note.get("best_fav") or 0.0)
            entry_price = _safe_float(en.get("entry_price") or entry["row"].get("price") or 0.0)
            shares = int(_safe_float(row.get("lot") or 1))
            exit_price = _safe_float(row.get("price") or 0.0)

            side = row.get("side") or entry["row"].get("side", "")
            if side == "BUY":
                pnl_usd = (exit_price - entry_price) * shares
            else:
                pnl_usd = (entry_price - exit_price) * shares

            closed.append({
                "pos_id": pos_id,
                "side": side,
                "outcome": outcome,
                "ret_pct": ret_pct,
                "pnl_usd": round(pnl_usd, 2),
                "symbol": en.get("symbol", "?"),
                "trend": entry["row"].get("trend", "?"),
            })

    # Open positions at end of session
    open_remaining = len(entries)

    if not closed:
        return {"day8": day8, "found": True, "trade_count": 0, "open_remaining": open_remaining, "trades": []}

    tp_n = sum(1 for t in closed if t["outcome"] == "TP")
    sl_n = sum(1 for t in closed if t["outcome"] == "SL")
    timeout_n = sum(1 for t in closed if t["outcome"] == "TIMEOUT")
    wr = round(tp_n / len(closed) * 100, 1)
    total_pnl = round(sum(t["pnl_usd"] for t in closed), 2)
    avg_ret = round(sum(t["ret_pct"] for t in closed) / len(closed), 4)

    return {
        "day8": day8,
        "found": True,
        "trade_count": len(closed),
        "open_remaining": open_remaining,
        "tp_n": tp_n,
        "sl_n": sl_n,
        "timeout_n": timeout_n,
        "win_rate": wr,
        "total_pnl_usd": total_pnl,
        "avg_ret_pct": avg_ret,
        "trades": closed,
    }


# ---------------------------------------------------------------------------
# Ollama (optional)
# ---------------------------------------------------------------------------

def _call_ollama(summary: Dict[str, Any], model: str, timeout_sec: int) -> str:
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
    n = summary.get("trade_count", 0)
    wr = summary.get("win_rate", 0.0)
    pnl = summary.get("total_pnl_usd", 0.0)
    tp = summary.get("tp_n", 0)
    sl = summary.get("sl_n", 0)
    to = summary.get("timeout_n", 0)
    trades_txt = " / ".join(
        f"{t['side']} {t['symbol']} {t['outcome']} (${t['pnl_usd']:+.2f})"
        for t in summary.get("trades", [])
    )

    prompt = (
        f"IBKR US株 本日セッション: {n}取引 WR={wr}% 合計P&L=${pnl:+.2f}\n"
        f"TP={tp} SL={sl} TIMEOUT={to}\n"
        f"取引詳細: {trades_txt}\n"
        "---\n"
        "US株トレードアナリストとして80字以内で:\n"
        "①本日の評価 ②明日への改善点"
    )

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
        print("[ibkr_review] ntfy_topic_url not configured, skip")
        return False
    bearer = _read_toml_str("ntfy_bearer_token")
    safe_title = title.encode("ascii", errors="replace").decode("ascii")
    headers: Dict[str, str] = {
        "Content-Type": "text/plain; charset=utf-8",
        "Title": safe_title,
        "Priority": "default",
        "Tags": "bar_chart,checkered_flag",
    }
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        req = urllib.request.Request(url, data=body.encode("utf-8"),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10.0) as r:
            print(f"[ibkr_review] ntfy sent: HTTP {r.status}")
            return True
    except urllib.error.HTTPError as e:
        print(f"[ibkr_review] ntfy HTTP {e.code}")
        return False
    except Exception as e:
        print(f"[ibkr_review] ntfy error: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="IBKR post-session review agent")
    p.add_argument("--day", default="", help="YYYYMMDD (default: yesterday JST)")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--no-llm", action="store_true", help="Skip Ollama call")
    p.add_argument("--no-ntfy", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--logs-dir", default=str(IBKR_LOGS_DIR))
    args = p.parse_args(argv)

    logs_dir = Path(args.logs_dir)

    # Default to yesterday JST (US session closes at ~04:00 JST, review runs 07:05)
    if args.day:
        day8 = args.day
    else:
        yesterday = (_now_jst() - timedelta(days=1)).strftime("%Y%m%d")
        today = _now_jst().strftime("%Y%m%d")
        # Use today if today's log exists (session may have ended near midnight)
        today_path = logs_dir / f"ibkr_trade_log_{today}.csv"
        day8 = today if today_path.exists() else yesterday

    print(f"[ibkr_review] loading session data for {day8} from {logs_dir}")
    summary = _load_today_session(logs_dir, day8)

    out_path = OUT_DIR / f"review_{day8}.json"
    if not summary.get("found"):
        print(f"[ibkr_review] no log found for {day8}")
        payload = {
            "generated_at": _now_jst().strftime("%Y-%m-%d %H:%M:%S"),
            "day8": day8,
            "summary": summary,
            "llm_text": "",
            "status": "no_data",
        }
        _write_output(payload, out_path)
        print(f"[ibkr_review] saved to {out_path}")
        if not args.dry_run and not args.no_ntfy:
            _send_ntfy(
                f"[IBKR review] {day8} no data",
                f"{day8}のIBKR取引ログが見つかりません。\nibkr_vm_syncが未実行か、取引なし。",
            )
        return 0

    n = summary.get("trade_count", 0)
    wr = summary.get("win_rate", 0.0)
    pnl = summary.get("total_pnl_usd", 0.0)

    print(f"[ibkr_review] {day8}: {n}取引 WR={wr}% P&L=${pnl:+.2f}")

    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    # Optional LLM review
    llm_text = ""
    if n > 0 and not args.no_llm:
        print(f"[ibkr_review] calling ollama model={args.model}")
        try:
            llm_text = _call_ollama(summary, args.model, OLLAMA_TIMEOUT_SEC)
            print(f"[ibkr_review] LLM: {llm_text[:80]}...")
        except Exception as e:
            print(f"[ibkr_review] LLM error: {e}")
            llm_text = ""

    # Save output
    payload = {
        "generated_at": _now_jst().strftime("%Y-%m-%d %H:%M:%S"),
        "day8": day8,
        "summary": summary,
        "llm_text": llm_text,
        "status": "ok",
    }
    _write_output(payload, out_path)
    print(f"[ibkr_review] saved to {out_path}")

    if args.no_ntfy:
        return 0

    # Build ntfy message
    if n == 0:
        title = f"[IBKR review] {day8} no trades"
        body = f"{day8} IBKR取引なし (市場休場 or 無シグナル)"
    else:
        pnl_sign = "+" if pnl >= 0 else ""
        title = f"[IBKR review] {day8} {n}t WR={wr}% ${pnl_sign}{pnl:.2f}"
        lines = [
            f"{day8} US株セッション完了",
            f"取引: {n}件  WR: {wr}%  P&L: ${pnl:+.2f}",
            f"TP={summary.get('tp_n',0)} SL={summary.get('sl_n',0)} TIMEOUT={summary.get('timeout_n',0)}",
        ]
        if llm_text:
            lines += ["---", llm_text]
        body = "\n".join(lines)

    _send_ntfy(title, body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
