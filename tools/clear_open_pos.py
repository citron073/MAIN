#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
clear_open_pos.py
- state.json の _open_pos を「ログを残してから」安全にクリアする
- orphan化を防ぐための手動操作用ツール

Usage:
  python3 tools/clear_open_pos.py --reason "manual stop"
  python3 tools/clear_open_pos.py --dry-run
"""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = MAIN_DIR / "state.json"

LOG_FIELDS = [
    "time",
    "result",
    "side",
    "price",
    "size",
    "ltp",
    "best_bid",
    "best_ask",
    "spread_pct",
    "limit_pct",
    "ma_fast",
    "ma_slow",
    "trend",
    "signal",
    "pos_id",
    "note",
    "ai_score",
]

def now_str(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M:%S")

def logs_dir_path() -> Path:
    return MAIN_DIR.parent / "logs"

def today_log_path(now: datetime) -> Path:
    d = logs_dir_path()
    d.mkdir(parents=True, exist_ok=True)
    day = now.strftime("%Y%m%d")
    return d / f"trade_log_{day}.csv"

def write_log(csv_path: Path, row: dict) -> None:
    file_exists = csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
        if not file_exists:
            w.writeheader()
        out = {k: row.get(k, "") for k in LOG_FIELDS}
        w.writerow(out)

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reason", default="manual_clear", help="log note reason")
    ap.add_argument("--dry-run", action="store_true", help="do not write/clear, just show what would happen")
    args = ap.parse_args()

    now = datetime.now()
    state = load_state()
    op = state.get("_open_pos")

    if not isinstance(op, dict) or not op:
        print("[INFO] no _open_pos in state.json (nothing to clear)")
        return

    pos_id = (op.get("pos_id") or "").strip()
    side = (op.get("side") or "").strip()
    entry_price = op.get("entry_price", "")
    size = op.get("size", "")
    exp = op.get("expiry_time_jst", "")
    ec = op.get("extend_count", "")
    bf = op.get("best_fav", "")
    tm = op.get("timeout_mode", "")
    ai_score = op.get("ai_score", "")

    note = (
        f"MANUAL_CLEAR reason={args.reason} "
        f"entry={op.get('entry_time_jst','')} exp={exp} "
        f"timeout_mode={tm} extend_count={ec} best_fav={bf}"
    )
    # pos_id は note にも入れておく（突合が楽）
    if pos_id:
        note = f"{note} pos_id={pos_id}"

    row = {
        "time": now_str(now),
        "result": "MANUAL_CLEAR_OPEN_POS",
        "side": side,
        "price": entry_price,
        "size": size,
        "ltp": "",
        "best_bid": "",
        "best_ask": "",
        "spread_pct": "",
        "limit_pct": "",
        "ma_fast": op.get("ma_fast", ""),
        "ma_slow": op.get("ma_slow", ""),
        "trend": op.get("trend", "UNKNOWN"),
        "signal": op.get("signal", "NONE"),
        "pos_id": pos_id,
        "note": note,
        "ai_score": ai_score if ai_score is not None else "",
    }

    print("[INFO] target open_pos:")
    print("  pos_id       :", pos_id)
    print("  side/price   :", side, entry_price)
    print("  expiry       :", exp)
    print("  timeout_mode :", tm)
    print("  extend_count :", ec)
    print("  best_fav     :", bf)

    if args.dry_run:
        print("[DRY] would append log + clear _open_pos")
        return

    # 1) log
    csv_path = today_log_path(now)
    write_log(csv_path, row)
    print("[OK] appended log:", csv_path)

    # 2) clear
    state.pop("_open_pos", None)
    save_state(state)
    print("[OK] cleared _open_pos in:", STATE_FILE)

if __name__ == "__main__":
    main()
