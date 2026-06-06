#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today_text() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _resolve_path(p: str) -> Path:
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    return path


def _safe_bool(v: Any, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on", "y", "t"):
        return True
    if s in ("0", "false", "no", "off", "n", "f"):
        return False
    return default


def _load_json_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json_dict(path: Path, obj: Dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_control_ai_auto_train_enabled(path: Path, default: bool = True) -> bool:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if not row:
                continue
            key = str(row[0]).strip()
            if key.startswith("#"):
                continue
            if key == "ai_auto_train_enabled":
                val = str(row[1]).strip() if len(row) >= 2 else ""
                return _safe_bool(val, default)
    return default


def run_daily_reset(args: argparse.Namespace) -> int:
    state_path = _resolve_path(args.state_path)
    control_path = _resolve_path(args.control_path)

    ai_auto_train_enabled = _read_control_ai_auto_train_enabled(control_path, True)
    if not ai_auto_train_enabled:
        print("[INFO] ai_auto_train_enabled=0 -> skip reset")
        return 0

    state = _load_json_dict(state_path)
    before_day = str(state.get("_ai_auto_train_day", ""))
    today = _today_text()
    if (not args.force) and before_day == today:
        print(f"[INFO] _ai_auto_train_day is already today ({today}) -> skip reset")
        return 0
    if args.skip_if_empty and before_day == "":
        print("[INFO] _ai_auto_train_day is already empty -> skip")
        return 0

    state["_ai_auto_train_day"] = ""

    prev_meta = state.get("_daily_auto_train")
    prev_count = 0
    if isinstance(prev_meta, dict):
        try:
            prev_count = int(prev_meta.get("count", 0))
        except Exception:
            prev_count = 0

    state["_daily_auto_train"] = {
        "updated_at": _now_text(),
        "trigger": str(args.trigger),
        "today": today,
        "before_day": before_day,
        "after_day": "",
        "ai_auto_train_enabled": True,
        "count": max(prev_count, 0) + 1,
    }

    if args.dry_run:
        print(f"[DRYRUN] state update path={state_path} _ai_auto_train_day: {before_day} -> ''")
        return 0

    _write_json_dict(state_path, state)
    print(f"[OK] state updated path={state_path} _ai_auto_train_day: {before_day} -> ''")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Reset state._ai_auto_train_day daily so next bot tick can execute AI auto-train."
    )
    ap.add_argument("--state-path", default="state.json", help="state json path (default: state.json)")
    ap.add_argument("--control-path", default="CONTROL.csv", help="control csv path (default: CONTROL.csv)")
    ap.add_argument("--trigger", default="systemd_daily_autotrain", help="metadata trigger label")
    ap.add_argument("--force", action="store_true", help="reset even if _ai_auto_train_day is already today")
    ap.add_argument("--skip-if-empty", action="store_true", help="skip when _ai_auto_train_day is already empty")
    ap.add_argument("--dry-run", action="store_true", help="do not write state")
    return ap


def main() -> None:
    args = build_arg_parser().parse_args()
    try:
        rc = run_daily_reset(args)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(2)
    except Exception as e:
        print(f"[ERROR] fatal: {e}")
        sys.exit(2)
    sys.exit(rc)


if __name__ == "__main__":
    main()
