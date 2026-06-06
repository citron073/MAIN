#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOGS_DIR = ROOT.parent / "logs"
DEFAULT_CONTROL_PATH = ROOT / "CONTROL.csv"
DEFAULT_STATE_PATH = ROOT / "state.json"
DEFAULT_RUN_LOCK_DIR = ROOT / ".run_lock"


GUARD_KEYWORDS = (
    "AI_BLOCK",
    "OBSERVE",
    "SKIP",
    "TIME_BLOCK",
    "NEWS",
    "SPREAD",
    "GUARD",
)


def _now_jst_naive() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


def _safe_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off", ""}:
        return False
    return default


def _read_control(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    out: Dict[str, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.reader(fh):
            if len(row) >= 2:
                out[str(row[0]).strip()] = str(row[1]).strip()
    return out


def _read_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _runner_alive(lock_dir: Path) -> bool:
    lock = lock_dir / "lockinfo.txt"
    if not lock.exists():
        return False
    try:
        txt = lock.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    m = re.search(r"^pid=(\d+)\s*$", txt, flags=re.M)
    if not m:
        return False
    return _pid_alive(int(m.group(1)))


def _build_main_runtime(control: Dict[str, str], state_path: Path, run_lock_dir: Path) -> Dict[str, Any]:
    state = _read_state(state_path)
    runner_alive = _runner_alive(run_lock_dir)
    state_runner_alive_raw: Optional[Any] = state.get("runner_alive") if isinstance(state, dict) else None
    state_runner_alive = (
        bool(state_runner_alive_raw)
        if isinstance(state_runner_alive_raw, bool)
        else None
    )
    today_on = _safe_bool(control.get("today_on"), True)
    trade_enabled = _safe_bool(control.get("trade_enabled"), True)
    return {
        "today_on": today_on,
        "trade_enabled": trade_enabled,
        "runner_alive": runner_alive,
        "state_runner_alive": state_runner_alive,
        "state_path": str(state_path),
        "run_lock_dir": str(run_lock_dir),
    }


def _classify(
    day8: str,
    row_n: int,
    rows: List[Dict[str, str]],
    control: Dict[str, str],
    log_exists: bool,
    main_runtime: Dict[str, Any],
) -> Dict[str, Any]:
    result_counts = Counter(str(r.get("result", "") or "").strip() for r in rows)
    note_text = " ".join(str(r.get("note", "") or "") for r in rows).upper()
    guard_hits = sum(1 for key in GUARD_KEYWORDS if key in note_text or any(key in k.upper() for k in result_counts))
    now = _now_jst_naive()
    is_today = day8 == now.strftime("%Y%m%d")
    start_hour = int(float(control.get("start_hour", "0") or 0))
    end_hour = int(float(control.get("end_hour", "24") or 24))
    in_time_window = start_hour <= now.hour < end_hour if start_hour < end_hour else True
    today_on = bool(main_runtime.get("today_on", True))
    trade_enabled = bool(main_runtime.get("trade_enabled", True))
    runner_alive = bool(main_runtime.get("runner_alive", False))
    state_runner_alive = main_runtime.get("state_runner_alive", None)

    if row_n > 0 and guard_hits:
        category = "guard_excess"
        label = "ガード過多"
    elif row_n > 0:
        category = "not_zero"
        label = "0行ではありません"
    elif is_today and not in_time_window:
        category = "market_time_window"
        label = "市場時間外"
    elif not today_on:
        category = "today_off"
        label = "today_on=0"
    elif not trade_enabled:
        category = "trade_disabled"
        label = "trade_enabled=0"
    elif runner_alive:
        category = "no_entries_yet"
        label = "未約定 / エントリーなし"
    elif state_runner_alive is True:
        category = "runtime_unclear"
        label = "state上は稼働 / 実プロセス未確認"
    elif is_today and in_time_window:
        category = "main_bot_not_running"
        label = "main bot未起動"
    elif log_exists:
        category = "main_bot_stopped"
        label = "main bot停止後"
    elif not log_exists:
        category = "bot_stopped_or_no_log"
        label = "bot停止"
    else:
        category = "data_missing"
        label = "データ未取得"

    return {
        "category": category,
        "label": label,
        "confidence": "medium" if row_n == 0 else "low",
        "evidence": {
            "log_exists": log_exists,
            "row_n": row_n,
            "result_counts": dict(result_counts),
            "guard_keyword_hits": guard_hits,
            "is_today": is_today,
            "current_hour_jst": now.hour,
            "configured_start_hour": start_hour,
            "configured_end_hour": end_hour,
            "in_time_window_now": in_time_window,
            "today_on": today_on,
            "trade_enabled": trade_enabled,
            "runner_alive": runner_alive,
            "state_runner_alive": state_runner_alive,
        },
    }


def build_report(
    day8: str,
    logs_dir: Path,
    control_path: Path,
    state_path: Optional[Path] = None,
    run_lock_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    log_path = logs_dir / f"trade_log_{day8}.csv"
    rows: List[Dict[str, str]] = []
    if log_path.exists():
        with log_path.open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    control = _read_control(control_path)
    main_dir = control_path.resolve().parent
    effective_state_path = (state_path or (main_dir / DEFAULT_STATE_PATH.name)).resolve()
    effective_run_lock_dir = (run_lock_dir or (main_dir / DEFAULT_RUN_LOCK_DIR.name)).resolve()
    main_runtime = _build_main_runtime(control, effective_state_path, effective_run_lock_dir)
    classification = _classify(day8, len(rows), rows, control, log_path.exists(), main_runtime)
    return {
        "generated_at_jst": _now_jst_naive().strftime("%Y-%m-%d %H:%M:%S"),
        "day8": day8,
        "log_path": str(log_path),
        "control_path": str(control_path),
        "row_n": len(rows),
        "main_runtime": main_runtime,
        "classification": classification,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Classify why trade_log_YYYYMMDD.csv has zero rows.")
    ap.add_argument("--day", default=_now_jst_naive().strftime("%Y%m%d"))
    ap.add_argument("--logs-dir", default=str(DEFAULT_LOGS_DIR))
    ap.add_argument("--control", default=str(DEFAULT_CONTROL_PATH))
    ap.add_argument("--state", default=str(DEFAULT_STATE_PATH))
    ap.add_argument("--run-lock-dir", default=str(DEFAULT_RUN_LOCK_DIR))
    ap.add_argument("--out-dir", default=str(ROOT / "review_out"))
    args = ap.parse_args()

    report = build_report(
        args.day,
        Path(args.logs_dir),
        Path(args.control),
        Path(args.state),
        Path(args.run_lock_dir),
    )
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"trade_log_zero_day_review_{args.day}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "trade_log_zero_day_review_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
