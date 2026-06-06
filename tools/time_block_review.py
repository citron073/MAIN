#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LOGS_DIR = ROOT_DIR.parent / "logs"
DEFAULT_CONTROL_PATH = ROOT_DIR / "CONTROL.csv"


def _read_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _read_control(path: Path) -> Dict[str, str]:
    rows = _read_rows(path)
    return {str(r.get("key", "")).strip(): str(r.get("value", "")).strip() for r in rows if str(r.get("key", "")).strip()}


def _hour_from_time(value: str) -> str:
    s = str(value or "")
    hour = s[11:13]
    return hour if hour.isdigit() else "-"


def _reason_from_note(note: str) -> str:
    s = str(note or "").strip()
    if not s:
        return "unknown"
    if "no_paper_hour" in s:
        return "no_paper_hour"
    if "eod_entry_window" in s:
        return "eod_entry_window"
    return s.split()[0]


def resolve_log_path(logs_dir: Path, day8: str) -> Path:
    if day8:
        return logs_dir / f"trade_log_{day8}.csv"
    paths = sorted(logs_dir.glob("trade_log_*.csv"))
    return paths[-1] if paths else logs_dir / "trade_log_.csv"


def build_review(rows: List[Dict[str, str]], *, day8: str, control: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    control = control or {}
    blocked = [r for r in rows if str(r.get("result", "")) == "OBSERVE_TIME_BLOCK"]
    by_hour = Counter(_hour_from_time(str(r.get("time", ""))) for r in blocked)
    by_reason = Counter(_reason_from_note(str(r.get("note", ""))) for r in blocked)
    by_signal = Counter(str(r.get("signal", "") or "-") for r in blocked)
    by_hour_reason = Counter(f"{_hour_from_time(str(r.get('time', '')))}:{_reason_from_note(str(r.get('note', '')))}" for r in blocked)
    return {
        "day8": day8,
        "rows_total": len(rows),
        "time_block_n": len(blocked),
        "time_block_by_hour": dict(sorted(by_hour.items())),
        "time_block_by_reason": dict(sorted(by_reason.items())),
        "time_block_by_signal": dict(sorted(by_signal.items())),
        "time_block_by_hour_reason": dict(sorted(by_hour_reason.items())),
        "control_no_paper_hours": str(control.get("no_paper_hours", "") or ""),
        "control_start_hour": str(control.get("start_hour", "") or ""),
        "control_end_hour": str(control.get("end_hour", "") or ""),
        "suggestion": _build_suggestion(by_reason, by_hour, control),
    }


def _build_suggestion(by_reason: Counter[str], by_hour: Counter[str], control: Dict[str, str]) -> str:
    if not by_reason:
        return "時間ブロックは少ないため変更不要。"
    no_paper_hours = str(control.get("no_paper_hours", "") or "").strip()
    top_hour = by_hour.most_common(1)[0][0] if by_hour else "-"
    if by_reason.get("no_paper_hour", 0) > 0:
        return f"no_paper_hours={no_paper_hours or '-'} の影響あり。hour={top_hour} はPAPER/observeで先に検証してから緩める。"
    if by_reason.get("eod_entry_window", 0) > 0:
        return "EOD entry blockが中心。終盤は保護目的のため、本体では維持し、別PAPERで検証する。"
    return "理由が混在。hour別にPAPER/observeで検証してから変更する。"


def format_text(review: Dict[str, Any]) -> str:
    return "\n".join(
        [
            f"day={review['day8']}",
            f"rows_total={review['rows_total']} time_block_n={review['time_block_n']}",
            f"control_no_paper_hours={review['control_no_paper_hours'] or '-'} start={review['control_start_hour'] or '-'} end={review['control_end_hour'] or '-'}",
            f"time_block_by_hour={json.dumps(review['time_block_by_hour'], ensure_ascii=False, sort_keys=True)}",
            f"time_block_by_reason={json.dumps(review['time_block_by_reason'], ensure_ascii=False, sort_keys=True)}",
            f"time_block_by_signal={json.dumps(review['time_block_by_signal'], ensure_ascii=False, sort_keys=True)}",
            f"time_block_by_hour_reason={json.dumps(review['time_block_by_hour_reason'], ensure_ascii=False, sort_keys=True)}",
            f"suggestion={review['suggestion']}",
        ]
    )


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Review OBSERVE_TIME_BLOCK reasons by hour.")
    p.add_argument("--logs-dir", default=str(DEFAULT_LOGS_DIR))
    p.add_argument("--control", default=str(DEFAULT_CONTROL_PATH))
    p.add_argument("--day8", default="")
    p.add_argument("--print-json", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    logs_dir = Path(str(args.logs_dir)).expanduser()
    control_path = Path(str(args.control)).expanduser()
    log_path = resolve_log_path(logs_dir, str(args.day8 or ""))
    day8 = str(args.day8 or log_path.stem.replace("trade_log_", ""))
    review = build_review(_read_rows(log_path), day8=day8, control=_read_control(control_path))
    if args.print_json:
        print(json.dumps(review, ensure_ascii=False, indent=2))
    else:
        print(format_text(review))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
