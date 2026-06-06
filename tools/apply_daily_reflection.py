#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
DAILY_REPORT_OUT_DIR_DEFAULT = ROOT / "daily_report_out"
CONTROL_PATH_DEFAULT = ROOT / "CONTROL.csv"
STATE_PATH_DEFAULT = ROOT / "state.json"


def _resolve_path(p: str) -> Path:
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    return path


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_json_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return {}


def _write_json_dict(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_control_rows(path: Path) -> List[List[str]]:
    if not path.exists():
        raise FileNotFoundError(f"control file not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        return [list(r) for r in csv.reader(f)]


def _write_control_rows(path: Path, rows: List[List[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)


def _apply_control_updates_to_rows(
    rows: List[List[str]],
    updates: Dict[str, str],
) -> Tuple[List[List[str]], Dict[str, Dict[str, str]]]:
    out = [list(r) for r in rows]
    key_to_idx: Dict[str, int] = {}
    for i, row in enumerate(out):
        if not row:
            continue
        key = str(row[0]).strip()
        if not key or key.startswith("#"):
            continue
        if key not in key_to_idx:
            key_to_idx[key] = i

    changed: Dict[str, Dict[str, str]] = {}
    for key in sorted(updates.keys()):
        new_v = str(updates[key])
        if key in key_to_idx:
            idx = key_to_idx[key]
            row = out[idx]
            old_v = str(row[1]) if len(row) >= 2 else ""
            if old_v != new_v:
                if len(row) >= 2:
                    row[1] = new_v
                else:
                    row.append(new_v)
                changed[key] = {"before": old_v, "after": new_v}
        else:
            out.append([key, new_v])
            changed[key] = {"before": "", "after": new_v}
    return out, changed


def _find_latest_reflection(out_dir: Path) -> Optional[Path]:
    files = sorted(out_dir.glob("daily_reflection_*.json"))
    if not files:
        return None
    return files[-1]


def _resolve_reflection_path(target: Optional[str], out_dir: Path) -> Path:
    if target:
        s = str(target).strip()
        if len(s) == 8 and s.isdigit():
            return out_dir / f"daily_reflection_{s}.json"
        p = Path(s).expanduser()
        if not p.is_absolute():
            p = (ROOT / p).resolve()
        return p
    latest = _find_latest_reflection(out_dir)
    if latest is None:
        raise FileNotFoundError(f"daily reflection json not found in {out_dir}")
    return latest


def apply_daily_reflection_report(
    *,
    reflection_path: Path,
    control_path: Path,
    state_path: Path,
    approver: str,
    dry_run: bool = False,
    override_updates: Optional[Dict[str, str]] = None,
    approval_status: str = "approved",
    approval_mode: str = "manual",
    approval_note: str = "",
) -> Dict[str, Any]:
    report = _load_json_dict(reflection_path)
    if not report:
        raise FileNotFoundError(f"daily reflection json not found or invalid: {reflection_path}")

    reflection = report.get("reflection")
    if not isinstance(reflection, dict):
        raise ValueError(f"reflection block missing: {reflection_path}")

    suggested_raw = override_updates if override_updates is not None else reflection.get("suggested_control_updates")
    suggested = {str(k): str(v) for k, v in dict(suggested_raw).items()} if isinstance(suggested_raw, dict) else {}
    day8 = str(report.get("range", {}).get("day8", "") if isinstance(report.get("range"), dict) else "")

    rows = _load_control_rows(control_path)
    updated_rows, changed = _apply_control_updates_to_rows(rows, suggested)
    approval = {
        "status": str(approval_status or "approved"),
        "approved_at": _now_text(),
        "approved_by": str(approver or "unknown").strip() or "unknown",
        "changed_keys": sorted(changed.keys()),
        "changed_count": len(changed),
        "control_path": str(control_path),
        "mode": str(approval_mode or "manual"),
    }
    if approval_note:
        approval["note"] = str(approval_note)

    state = _load_json_dict(state_path)
    state["_daily_reflection_apply"] = {
        "updated_at": approval["approved_at"],
        "approved_by": approval["approved_by"],
        "day8": day8,
        "reflection_path": str(reflection_path),
        "changed_keys": sorted(changed.keys()),
        "changed_count": len(changed),
        "mode": approval["mode"],
    }

    report["approval"] = approval
    report["applied_control_updates"] = changed

    if not dry_run:
        _write_control_rows(control_path, updated_rows)
        _write_json_dict(state_path, state)
        _write_json_dict(reflection_path, report)

    return {
        "reflection_path": str(reflection_path),
        "day8": day8,
        "suggested": suggested,
        "changed": changed,
        "approval": approval,
        "dry_run": bool(dry_run),
    }


def run_apply_daily_reflection(args: argparse.Namespace) -> int:
    out_dir = _resolve_path(args.daily_report_out_dir)
    control_path = _resolve_path(args.control_path)
    state_path = _resolve_path(args.state_path)
    reflection_path = _resolve_reflection_path(args.target, out_dir)

    report = _load_json_dict(reflection_path)
    if not report:
        raise FileNotFoundError(f"daily reflection json not found or invalid: {reflection_path}")

    reflection = report.get("reflection")
    if not isinstance(reflection, dict):
        raise ValueError(f"reflection block missing: {reflection_path}")

    suggested_raw = reflection.get("suggested_control_updates")
    suggested = {str(k): str(v) for k, v in dict(suggested_raw).items()} if isinstance(suggested_raw, dict) else {}
    day8 = str(report.get("range", {}).get("day8", "") if isinstance(report.get("range"), dict) else "")
    goal = report.get("goal") if isinstance(report.get("goal"), dict) else {}
    achieved = bool(goal.get("achieved", False))

    print(f"[INFO] reflection={reflection_path}")
    print(f"[INFO] day8={day8 or '-'} goal_achieved={achieved}")

    if args.print_suggested or (not args.apply_control):
        print(json.dumps(suggested, ensure_ascii=False, indent=2))

    if not suggested:
        print("[INFO] suggested_control_updates is empty")
        return 0

    rows = _load_control_rows(control_path)
    updated_rows, changed = _apply_control_updates_to_rows(rows, suggested)
    print(f"[INFO] changed_keys={len(changed)} control={control_path}")
    for key in sorted(changed.keys()):
        ch = changed[key]
        print(f"[UPDATE] {key}: {ch.get('before', '')} -> {ch.get('after', '')}")

    if not args.apply_control:
        print("[INFO] preview only (set --apply-control to approve and write)")
        return 0

    approver = str(args.approver or os.getenv("USER") or "unknown").strip() or "unknown"
    result = apply_daily_reflection_report(
        reflection_path=reflection_path,
        control_path=control_path,
        state_path=state_path,
        approver=approver,
        dry_run=bool(args.dry_run),
        approval_status="approved",
        approval_mode="manual",
    )
    if args.dry_run:
        print("[DRYRUN] control/state/reflection write skipped")
        return 0
    print(f"[OK] control updated keys={len(result['changed'])} path={control_path}")
    print(f"[OK] reflection approved path={reflection_path}")
    print(f"[OK] state updated path={state_path}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Preview or approve suggested CONTROL updates from daily reflection JSON."
    )
    ap.add_argument("target", nargs="?", default=None, help="day8 (YYYYMMDD) or daily_reflection json path")
    ap.add_argument("--daily-report-out-dir", default=str(DAILY_REPORT_OUT_DIR_DEFAULT))
    ap.add_argument("--control-path", default=str(CONTROL_PATH_DEFAULT))
    ap.add_argument("--state-path", default=str(STATE_PATH_DEFAULT))
    ap.add_argument("--print-suggested", action="store_true", help="print suggested_control_updates JSON")
    ap.add_argument("--apply-control", action="store_true", help="approve and apply suggested updates to CONTROL.csv")
    ap.add_argument("--approver", default="", help="approver label saved into reflection/state")
    ap.add_argument("--dry-run", action="store_true", help="do not write CONTROL/state/reflection")
    return ap


def main() -> None:
    args = build_arg_parser().parse_args()
    try:
        rc = run_apply_daily_reflection(args)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        raise SystemExit(2)
    except ValueError as e:
        print(f"[ERROR] {e}")
        raise SystemExit(2)
    except Exception as e:
        print(f"[ERROR] fatal: {e}")
        raise SystemExit(2)
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
