#!/usr/bin/env python3
"""Validate _drift_watch and _weekly_auto_feedback objects in state.json."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STATE_PATH = ROOT_DIR / "state.json"

_DRIFT_STATUS_VALID = {"OK", "WARN", "DRIFT", "INSUFFICIENT", "UNKNOWN", "DISABLED"}
_FIB_ZONE_VALID = {"CONTINUATION", "SHALLOW", "GOLDEN", "DEEP", "REVERSAL", "NA", "NONE", ""}
_MARKET_PHASE_VALID = {"A", "B", "C", ""}
_SHADOW_REVIEW_VALID = {"昇格候補", "保留", "差し戻し", "評価保留", ""}


def _safe_int(v: Any) -> Optional[int]:
    try:
        return int(float(v))
    except Exception:
        return None


def _is_day8(v: Any) -> bool:
    return bool(v) and bool(re.match(r"^\d{8}$", str(v)))


def _check_drift_watch(dw: Any) -> Tuple[List[str], List[str]]:
    """Returns (errors, warnings)."""
    if not isinstance(dw, dict):
        return [f"_drift_watch is not a dict (got {type(dw).__name__})"], []
    errors: List[str] = []
    warnings: List[str] = []

    status = str(dw.get("status", "") or "")
    if status not in _DRIFT_STATUS_VALID:
        errors.append(f"status={status!r} not in {sorted(_DRIFT_STATUS_VALID)}")

    if not str(dw.get("updated_at", "") or "").strip():
        warnings.append("updated_at is empty")

    for key in ("recent_metrics", "baseline_metrics"):
        m = dw.get(key)
        if not isinstance(m, dict):
            errors.append(f"{key} missing or not a dict")
        else:
            cn = _safe_int(m.get("closed_n"))
            if cn is None or cn < 0:
                errors.append(f"{key}.closed_n invalid (got {m.get('closed_n')!r})")

    for key in ("drops", "gate"):
        if not isinstance(dw.get(key), dict):
            warnings.append(f"{key} missing or not a dict")

    frozen = bool(dw.get("frozen_by_drift"))
    if frozen and not bool(dw.get("train_freeze_applied")):
        errors.append("frozen_by_drift=True but train_freeze_applied=False")

    paused = bool(dw.get("trade_paused_by_drift"))
    if paused and not bool(dw.get("trade_pause_applied")):
        errors.append("trade_paused_by_drift=True but trade_pause_applied=False")

    for rc_key in ("weekly_report_recent_rc", "weekly_report_baseline_rc"):
        rc = _safe_int(dw.get(rc_key))
        if rc is not None and rc != 0:
            warnings.append(f"{rc_key}={rc} (non-zero, weekly report may have failed)")

    ns = _safe_int(dw.get("normal_streak"))
    if ns is not None and ns < 0:
        warnings.append(f"normal_streak={ns} is negative")

    for bool_key in ("resume_ready", "canary_ready"):
        v = dw.get(bool_key)
        if v is not None and not isinstance(v, (bool, int)):
            warnings.append(f"{bool_key}={v!r} should be bool/int")

    return errors, warnings


def _check_weekly_auto_feedback(wf: Any) -> Tuple[List[str], List[str]]:
    """Returns (errors, warnings)."""
    if not isinstance(wf, dict):
        return [f"_weekly_auto_feedback is not a dict (got {type(wf).__name__})"], []
    errors: List[str] = []
    warnings: List[str] = []

    if not str(wf.get("updated_at", "") or "").strip():
        warnings.append("updated_at is empty")

    for key in ("range_start8", "range_end8"):
        v = wf.get(key)
        if not _is_day8(v):
            warnings.append(f"{key}={v!r} is not a valid YYYYMMDD date")

    # summary: str (compact text) or dict (structured) — both valid
    summary = wf.get("summary")
    if summary is not None and not isinstance(summary, (str, dict)):
        errors.append(f"summary unexpected type (got {type(summary).__name__})")

    ac = wf.get("apply_control")
    if ac is not None and not isinstance(ac, (bool, int)):
        warnings.append(f"apply_control={ac!r} should be bool/int")

    # llm_feedback: dict (metadata+result) or str — both valid
    lf = wf.get("llm_feedback")
    if lf is not None and not isinstance(lf, (str, dict)):
        warnings.append(f"llm_feedback unexpected type (got {type(lf).__name__})")

    # temporal ordering: range_start8 must not be after range_end8
    rs = str(wf.get("range_start8", "") or "")
    re_ = str(wf.get("range_end8", "") or "")
    if _is_day8(rs) and _is_day8(re_) and rs > re_:
        errors.append(f"range_start8={rs} is after range_end8={re_}")

    srr = wf.get("shadow_weekly_review")
    if srr is not None:
        if isinstance(srr, dict):
            decision = str(srr.get("decision", "") or "")
            if decision and decision not in _SHADOW_REVIEW_VALID:
                warnings.append(f"shadow_weekly_review.decision={decision!r} not in known values {sorted(_SHADOW_REVIEW_VALID)}")
        elif isinstance(srr, str):
            if srr and srr not in _SHADOW_REVIEW_VALID:
                warnings.append(f"shadow_weekly_review={srr!r} not in known values {sorted(_SHADOW_REVIEW_VALID)}")

    return errors, warnings


def _check_fib_last(fl: Any) -> Tuple[List[str], List[str]]:
    """Returns (errors, warnings) for _fib_last."""
    if not isinstance(fl, dict):
        return [f"_fib_last is not a dict (got {type(fl).__name__})"], []
    errors: List[str] = []
    warnings: List[str] = []

    zone = str(fl.get("zone", "") or "")
    if zone not in _FIB_ZONE_VALID:
        warnings.append(f"zone={zone!r} not in known values {sorted(_FIB_ZONE_VALID)}")

    if not str(fl.get("updated_at_jst", "") or "").strip():
        warnings.append("updated_at_jst is empty")

    side = str(fl.get("side", "") or "")
    if side and side not in ("BUY", "SELL"):
        warnings.append(f"side={side!r} should be BUY or SELL")

    return errors, warnings


def _check_market_phase(mp: Any) -> Tuple[List[str], List[str]]:
    """Returns (errors, warnings) for _market_phase."""
    if not isinstance(mp, dict):
        return [f"_market_phase is not a dict (got {type(mp).__name__})"], []
    errors: List[str] = []
    warnings: List[str] = []

    phase = str(mp.get("phase", "") or "")
    if phase not in _MARKET_PHASE_VALID:
        warnings.append(f"phase={phase!r} not in {sorted(_MARKET_PHASE_VALID)}")

    if not str(mp.get("updated_at_jst", "") or "").strip():
        warnings.append("updated_at_jst is empty")

    return errors, warnings


def check_state(state_path: Path) -> Tuple[bool, List[Tuple[str, str]]]:
    """Validate state.json. Returns (ok, [(level, message), ...]).

    ok=True when no ERROR-level issues are found.
    """
    if not state_path.exists():
        return False, [("ERROR", f"state.json not found: {state_path}")]

    try:
        state: Any = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, [("ERROR", f"state.json parse error: {e}")]

    if not isinstance(state, dict):
        return False, [("ERROR", "state.json root is not a dict")]

    items: List[Tuple[str, str]] = []

    if "_drift_watch" not in state:
        items.append(("WARN", "_drift_watch key missing from state.json"))
    else:
        errs, warns = _check_drift_watch(state["_drift_watch"])
        for msg in errs:
            items.append(("ERROR", f"drift_watch: {msg}"))
        for msg in warns:
            items.append(("WARN", f"drift_watch: {msg}"))

    if "_weekly_auto_feedback" not in state:
        items.append(("WARN", "_weekly_auto_feedback key missing from state.json"))
    else:
        errs, warns = _check_weekly_auto_feedback(state["_weekly_auto_feedback"])
        for msg in errs:
            items.append(("ERROR", f"weekly_auto_feedback: {msg}"))
        for msg in warns:
            items.append(("WARN", f"weekly_auto_feedback: {msg}"))

    if "_fib_last" in state:
        errs, warns = _check_fib_last(state["_fib_last"])
        for msg in errs:
            items.append(("ERROR", f"fib_last: {msg}"))
        for msg in warns:
            items.append(("WARN", f"fib_last: {msg}"))

    if "_market_phase" in state:
        errs, warns = _check_market_phase(state["_market_phase"])
        for msg in errs:
            items.append(("ERROR", f"market_phase: {msg}"))
        for msg in warns:
            items.append(("WARN", f"market_phase: {msg}"))

    ok = all(level != "ERROR" for level, _ in items)
    return ok, items


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Validate state.json drift/weekly object schemas.")
    p.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    p.add_argument("--print-json", action="store_true")
    args = p.parse_args(argv)

    state_path = Path(args.state_path).expanduser()
    ok, items = check_state(state_path)

    if args.print_json:
        result = {
            "ok": ok,
            "state_path": str(state_path),
            "issues": [{"level": lvl, "message": msg} for lvl, msg in items],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    if not items:
        print(f"[OK] state.json schema valid: {state_path}")
    else:
        for level, msg in items:
            print(f"[{level}] {msg}")
        if ok:
            warns = sum(1 for lvl, _ in items if lvl == "WARN")
            print(f"[OK] schema check passed with {warns} warning(s)")
        else:
            errors = sum(1 for lvl, _ in items if lvl == "ERROR")
            print(f"[FAIL] schema check failed: {errors} error(s)")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
