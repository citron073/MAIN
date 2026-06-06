#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import weekly_report  # noqa: E402


def _day8(d: date) -> str:
    return d.strftime("%Y%m%d")


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _resolve_path(p: str) -> Path:
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    return path


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return float(default)
        s = str(v).strip()
        if s == "":
            return float(default)
        return float(s)
    except Exception:
        return float(default)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return int(default)
        return int(float(str(v).strip()))
    except Exception:
        return int(default)


def _fmt_float(v: float, ndigits: int = 6) -> str:
    s = f"{float(v):.{int(ndigits)}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


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


def _snapshot_file(path: Path, backup_dir: Path, prefix: str, max_keep: int = 50) -> Optional[Path]:
    if not path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    suffix = path.suffix if path.suffix else ".bak"
    out = backup_dir / f"{prefix}_{ts}{suffix}"
    shutil.copy2(path, out)

    keep_n = max(1, int(max_keep))
    snaps = sorted(
        [p for p in backup_dir.glob(f"{prefix}_*") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in snaps[keep_n:]:
        try:
            old.unlink()
        except Exception:
            pass
    return out


def _load_control_rows(path: Path) -> List[List[str]]:
    if not path.exists():
        raise FileNotFoundError(f"control file not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        return [list(r) for r in csv.reader(f)]


def _write_control_rows(path: Path, rows: List[List[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerows(rows)


def _upsert_control_value(rows: List[List[str]], key: str, value: str) -> Tuple[List[List[str]], Optional[str]]:
    out = [list(r) for r in rows]
    for row in out:
        if not row:
            continue
        k = str(row[0]).strip()
        if not k or k.startswith("#"):
            continue
        if k == key:
            before = str(row[1]) if len(row) >= 2 else ""
            if len(row) >= 2:
                row[1] = str(value)
            else:
                row.append(str(value))
            return out, before
    out.append([str(key), str(value)])
    return out, ""


def _get_control_value(rows: List[List[str]], key: str) -> Optional[str]:
    for row in rows:
        if not row:
            continue
        k = str(row[0]).strip()
        if not k or k.startswith("#"):
            continue
        if k == key:
            return str(row[1]).strip() if len(row) >= 2 else ""
    return None


def _calc_review(logs_dir: Path, start8: str, end8: str, out_dir: Path) -> Tuple[int, Path, Dict[str, Any]]:
    args = argparse.Namespace(
        target=f"{start8}-{end8}",
        start=None,
        end=None,
        out_dir=str(out_dir),
        logs_dir=str(logs_dir),
        week_start="MON",
        strict=False,
    )
    return weekly_report.run_weekly_report(args)


def _extract_metrics(report: Dict[str, Any]) -> Dict[str, float]:
    wr = report.get("weekly_review", {}) if isinstance(report, dict) else {}
    if not isinstance(wr, dict):
        wr = {}
    return {
        "closed_n": float(_safe_int(wr.get("closed_n"), 0)),
        "profit_factor": float(_safe_float(wr.get("profit_factor"), 0.0)),
        "avg_ret_pct": float(_safe_float(wr.get("avg_ret_pct"), 0.0)),
        "win_rate_pct": float(_safe_float(wr.get("win_rate_pct"), 0.0)),
        "ret_sum_pct": float(_safe_float(wr.get("ret_sum_pct"), 0.0)),
    }


def _parse_hours_csv(v: Any) -> List[int]:
    out: List[int] = []
    seen = set()
    s = str(v or "").replace("[", "").replace("]", "").strip()
    if not s:
        return out
    for tok in s.split(","):
        t = tok.strip()
        if not t:
            continue
        try:
            h = int(float(t))
        except Exception:
            continue
        if 0 <= h <= 23 and h not in seen:
            seen.add(h)
            out.append(int(h))
    return out


def _hours_to_csv(hours: List[int]) -> str:
    return ",".join(str(int(h)) for h in hours if 0 <= int(h) <= 23)


def _acquire_nonblocking_lock(lock_path_raw: str) -> Optional[Any]:
    lock_path = _resolve_path(lock_path_raw)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fp = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fp.close()
        return None
    fp.seek(0)
    fp.truncate(0)
    fp.write(str(os.getpid()))
    fp.flush()
    return fp


def _extract_hourly_stop_candidates(
    report: Dict[str, Any],
    *,
    min_samples: int,
    max_hours: int,
    avg_ret_th: float,
    win_rate_th: float,
) -> Tuple[List[int], List[Dict[str, Any]]]:
    wr = report.get("weekly_review", {}) if isinstance(report, dict) else {}
    by_hour = wr.get("by_hour", {}) if isinstance(wr, dict) else {}
    if not isinstance(by_hour, dict):
        by_hour = {}

    min_samples = max(1, int(min_samples))
    max_hours = max(1, int(max_hours))
    cand: List[Dict[str, Any]] = []
    for h in range(24):
        hb = by_hour.get(str(h), {})
        if not isinstance(hb, dict):
            continue
        n = int(_safe_int(hb.get("closed_n"), 0))
        if n < min_samples:
            continue
        avg_ret = float(_safe_float(hb.get("avg_ret_pct"), 0.0))
        win_rate = float(_safe_float(hb.get("win_rate_pct"), 0.0))
        if (avg_ret <= float(avg_ret_th)) or (win_rate <= float(win_rate_th)):
            cand.append(
                {
                    "hour": h,
                    "closed_n": n,
                    "avg_ret_pct": round(avg_ret, 6),
                    "win_rate_pct": round(win_rate, 4),
                }
            )

    # Worse hours first: lower avg_ret, then lower win_rate, then larger samples.
    cand.sort(key=lambda x: (float(x["avg_ret_pct"]), float(x["win_rate_pct"]), -int(x["closed_n"])))
    stop_hours = [int(x["hour"]) for x in cand[:max_hours]]
    return stop_hours, cand


def _resolve_ranges(today: date, recent_days: int, baseline_days: int) -> Dict[str, str]:
    recent_end = today
    recent_start = today - timedelta(days=max(1, recent_days) - 1)
    baseline_end = recent_start - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=max(1, baseline_days) - 1)
    return {
        "recent_start8": _day8(recent_start),
        "recent_end8": _day8(recent_end),
        "baseline_start8": _day8(baseline_start),
        "baseline_end8": _day8(baseline_end),
    }


def run_drift_watch(args: argparse.Namespace) -> int:
    logs_dir = _resolve_path(args.logs_dir)
    out_dir = _resolve_path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = _resolve_path(args.state_path)
    control_path = _resolve_path(args.control_path)
    backup_dir = _resolve_path(args.backup_dir)
    backup_max_keep = max(1, int(args.backup_max_keep))

    today = date.today()
    ranges = _resolve_ranges(today, int(args.recent_days), int(args.baseline_days))

    rc_recent, out_recent, rep_recent = _calc_review(
        logs_dir,
        ranges["recent_start8"],
        ranges["recent_end8"],
        out_dir / "drift_recent",
    )
    rc_base, out_base, rep_base = _calc_review(
        logs_dir,
        ranges["baseline_start8"],
        ranges["baseline_end8"],
        out_dir / "drift_baseline",
    )

    recent = _extract_metrics(rep_recent)
    base = _extract_metrics(rep_base)
    stop_hours, stop_hour_candidates = _extract_hourly_stop_candidates(
        rep_recent,
        min_samples=int(args.hour_block_min_samples),
        max_hours=int(args.hour_block_max_hours),
        avg_ret_th=float(args.hour_block_avg_ret_th),
        win_rate_th=float(args.hour_block_win_rate_th),
    )

    recent_n = int(recent["closed_n"])
    base_n = int(base["closed_n"])
    pf_drop = float(base["profit_factor"]) - float(recent["profit_factor"])
    avg_ret_drop = float(base["avg_ret_pct"]) - float(recent["avg_ret_pct"])
    win_rate_drop = float(base["win_rate_pct"]) - float(recent["win_rate_pct"])

    reasons: List[str] = []
    status = "NORMAL"
    if recent_n < int(args.min_recent_closed):
        status = "INSUFFICIENT"
        reasons.append(f"recent_closed<{int(args.min_recent_closed)} ({recent_n})")
    if base_n < int(args.min_baseline_closed):
        status = "INSUFFICIENT"
        reasons.append(f"baseline_closed<{int(args.min_baseline_closed)} ({base_n})")

    if status != "INSUFFICIENT":
        hits = 0
        if pf_drop >= float(args.pf_drop_th):
            hits += 1
            reasons.append(f"pf_drop>={float(args.pf_drop_th):.4f} ({pf_drop:.4f})")
        if avg_ret_drop >= float(args.avg_ret_drop_th):
            hits += 1
            reasons.append(f"avg_ret_drop>={float(args.avg_ret_drop_th):.4f} ({avg_ret_drop:.4f})")
        if win_rate_drop >= float(args.win_rate_drop_th):
            hits += 1
            reasons.append(f"win_rate_drop>={float(args.win_rate_drop_th):.4f} ({win_rate_drop:.4f})")

        if hits >= 2:
            status = "ALERT"
        elif hits == 1:
            status = "WARN"
        else:
            status = "NORMAL"

    print(
        "[INFO] drift_watch recent(closed={}, pf={:.4f}, avg_ret={:.4f}, win={:.2f}) "
        "baseline(closed={}, pf={:.4f}, avg_ret={:.4f}, win={:.2f}) status={}".format(
            recent_n,
            float(recent["profit_factor"]),
            float(recent["avg_ret_pct"]),
            float(recent["win_rate_pct"]),
            base_n,
            float(base["profit_factor"]),
            float(base["avg_ret_pct"]),
            float(base["win_rate_pct"]),
            status,
        )
    )
    if reasons:
        print("[INFO] drift_reasons: " + "; ".join(reasons))

    state = _load_json_dict(state_path)
    prev_drift = state.get("_drift_watch", {}) if isinstance(state, dict) else {}
    if not isinstance(prev_drift, dict):
        prev_drift = {}
    prev_frozen_by_drift = bool(prev_drift.get("frozen_by_drift"))
    prev_trade_paused_by_drift = bool(prev_drift.get("trade_paused_by_drift"))
    prev_hour_blocked_by_drift = bool(prev_drift.get("hour_blocked_by_drift"))
    prev_risk_tightened_by_drift = bool(prev_drift.get("risk_tightened_by_drift"))
    prev_no_paper_hours_before_drift = str(prev_drift.get("no_paper_hours_before_drift", ""))
    prev_insufficient_streak = int(_safe_int(prev_drift.get("insufficient_streak"), 0))
    prev_insufficient_relax_count = int(_safe_int(prev_drift.get("insufficient_relax_count"), 0))
    prev_daily_loss_limit_before_drift = str(prev_drift.get("daily_loss_limit_before_drift", ""))
    prev_streak_stop_enabled_before_drift = str(prev_drift.get("streak_stop_enabled_before_drift", ""))
    prev_streak_stop_max_losses_before_drift = str(prev_drift.get("streak_stop_max_losses_before_drift", ""))
    prev_normal_streak = int(_safe_int(prev_drift.get("normal_streak"), 0))
    prev_canary_streak = int(_safe_int(prev_drift.get("canary_streak"), 0))
    resume_required_normals = max(1, int(args.resume_require_consecutive_normal))
    resume_canary_runs = max(0, int(args.resume_canary_runs))
    normal_streak = (prev_normal_streak + 1) if status == "NORMAL" else 0
    insufficient_streak = (prev_insufficient_streak + 1) if status == "INSUFFICIENT" else 0
    insufficient_relax_count = prev_insufficient_relax_count if status == "INSUFFICIENT" else 0
    resume_ready = bool(normal_streak >= resume_required_normals)
    canary_streak = (prev_canary_streak + 1) if (status == "NORMAL" and resume_ready) else 0
    canary_ready = bool(resume_canary_runs <= 0 or canary_streak >= resume_canary_runs)
    canary_active = bool(status == "NORMAL" and resume_ready and not canary_ready)

    train_freeze_applied = False
    train_unfreeze_applied = False
    train_freeze_before: Optional[str] = None
    train_freeze_after: Optional[str] = None
    frozen_by_drift = prev_frozen_by_drift
    trade_pause_applied = False
    trade_resume_applied = False
    trade_before: Optional[str] = None
    trade_after: Optional[str] = None
    trade_paused_by_drift = prev_trade_paused_by_drift
    hour_block_applied = False
    hour_unblock_applied = False
    no_paper_hours_before_drift = prev_no_paper_hours_before_drift
    no_paper_hours_before: Optional[str] = None
    no_paper_hours_after: Optional[str] = None
    hour_blocked_by_drift = prev_hour_blocked_by_drift
    risk_tighten_applied = False
    risk_restore_applied = False
    risk_tightened_by_drift = prev_risk_tightened_by_drift
    daily_loss_limit_before_drift = prev_daily_loss_limit_before_drift
    streak_stop_enabled_before_drift = prev_streak_stop_enabled_before_drift
    streak_stop_max_losses_before_drift = prev_streak_stop_max_losses_before_drift
    daily_loss_limit_before: Optional[str] = None
    daily_loss_limit_after: Optional[str] = None
    streak_stop_enabled_before: Optional[str] = None
    streak_stop_enabled_after: Optional[str] = None
    streak_stop_max_losses_before: Optional[str] = None
    streak_stop_max_losses_after: Optional[str] = None
    insufficient_relax_applied = False
    insufficient_relax_before: Optional[str] = None
    insufficient_relax_after: Optional[str] = None
    control_backup_path: Optional[str] = None
    state_backup_path: Optional[str] = None
    control_snapshot_done = False
    state_snapshot_done = False
    control_rows: Optional[List[List[str]]] = None

    def ensure_control_rows() -> List[List[str]]:
        nonlocal control_rows
        if control_rows is None:
            control_rows = _load_control_rows(control_path)
        return control_rows

    def update_control_key(key: str, target: str, tag: str) -> Tuple[bool, Optional[str], str]:
        nonlocal control_rows
        nonlocal control_backup_path, control_snapshot_done
        rows = ensure_control_rows()
        before = _get_control_value(rows, key)
        if ("" if before is None else before) == str(target):
            print(
                f"[INFO] {tag} no change path={control_path} "
                f"{key} already {target}"
            )
            return False, before, str(target)

        rows2, _ = _upsert_control_value(rows, key, str(target))
        if args.dry_run:
            print(
                f"[DRYRUN] control update path={control_path} {key}: "
                f"{'' if before is None else before} -> {target}"
            )
        else:
            if not control_snapshot_done:
                snap = _snapshot_file(control_path, backup_dir, "CONTROL", backup_max_keep)
                control_snapshot_done = True
                if snap is not None:
                    control_backup_path = str(snap)
                    print(f"[OK] backup created path={snap}")
            _write_control_rows(control_path, rows2)
            print(
                f"[OK] control updated path={control_path} {key}: "
                f"{'' if before is None else before} -> {target}"
            )
        control_rows = rows2
        return True, before, str(target)

    if bool(args.apply_train_freeze) and status == "ALERT":
        changed, before, after = update_control_key("ai_auto_train_enabled", "0", "train_freeze")
        train_freeze_applied = changed
        train_freeze_before = before
        train_freeze_after = after
        frozen_by_drift = bool(prev_frozen_by_drift or changed)

    if bool(args.apply_trade_pause) and status == "ALERT":
        changed, before, after = update_control_key("trade_enabled", "0", "trade_pause")
        trade_pause_applied = changed
        trade_before = before
        trade_after = after
        trade_paused_by_drift = bool(prev_trade_paused_by_drift or changed)

    if bool(args.apply_hour_block) and status == "ALERT":
        if stop_hours:
            if not prev_hour_blocked_by_drift:
                rows_now = ensure_control_rows()
                no_paper_hours_before_drift = str(_get_control_value(rows_now, "no_paper_hours") or "")
            target_hours_csv = ",".join(str(int(h)) for h in stop_hours)
            changed, before, after = update_control_key("no_paper_hours", target_hours_csv, "hour_block")
            hour_block_applied = changed
            no_paper_hours_before = before
            no_paper_hours_after = after
            hour_blocked_by_drift = bool(prev_hour_blocked_by_drift or changed)
        else:
            print("[INFO] hour_block skipped: no stop-hour candidates")

    if bool(args.apply_risk_tighten) and status == "ALERT":
        rows_now = ensure_control_rows()
        if not prev_risk_tightened_by_drift:
            daily_loss_limit_before_drift = str(_get_control_value(rows_now, "daily_loss_limit_pct") or "")
            streak_stop_enabled_before_drift = str(_get_control_value(rows_now, "streak_stop_enabled") or "")
            streak_stop_max_losses_before_drift = str(_get_control_value(rows_now, "streak_stop_max_losses") or "")

        target_daily_loss = _fmt_float(float(args.risk_alert_daily_loss_limit_pct), 6)
        target_streak_enabled = "1"
        target_streak_max = str(max(1, int(args.risk_alert_streak_max_losses)))

        changed_daily, before_daily, after_daily = update_control_key(
            "daily_loss_limit_pct", target_daily_loss, "risk_tighten_daily_loss"
        )
        changed_enabled, before_enabled, after_enabled = update_control_key(
            "streak_stop_enabled", target_streak_enabled, "risk_tighten_streak_enabled"
        )
        changed_max, before_max, after_max = update_control_key(
            "streak_stop_max_losses", target_streak_max, "risk_tighten_streak_max_losses"
        )
        risk_tighten_applied = bool(changed_daily or changed_enabled or changed_max)
        daily_loss_limit_before = before_daily
        daily_loss_limit_after = after_daily
        streak_stop_enabled_before = before_enabled
        streak_stop_enabled_after = after_enabled
        streak_stop_max_losses_before = before_max
        streak_stop_max_losses_after = after_max
        risk_tightened_by_drift = bool(prev_risk_tightened_by_drift or risk_tighten_applied)

    if bool(args.insufficient_auto_relax_hours) and status == "INSUFFICIENT":
        relax_after_runs = max(1, int(args.insufficient_relax_after_runs))
        relax_drop_hours = max(1, int(args.insufficient_relax_drop_hours))
        relax_max_applies = max(1, int(args.insufficient_relax_max_applies))

        if not bool(prev_hour_blocked_by_drift or hour_blocked_by_drift):
            print("[INFO] insufficient_relax skipped: hour_blocked_by_drift is False")
        elif insufficient_streak < relax_after_runs:
            print(
                f"[INFO] insufficient_relax gated: insufficient_streak={insufficient_streak} "
                f"< required={relax_after_runs}"
            )
        elif insufficient_relax_count >= relax_max_applies:
            print(
                f"[INFO] insufficient_relax skipped: relax_count={insufficient_relax_count} "
                f">= max={relax_max_applies}"
            )
        else:
            rows_now = ensure_control_rows()
            cur_hours_csv = str(_get_control_value(rows_now, "no_paper_hours") or "")
            cur_hours = _parse_hours_csv(cur_hours_csv)
            if len(cur_hours) <= 1:
                print("[INFO] insufficient_relax skipped: no_paper_hours has <=1 hour")
            else:
                drop_n = min(relax_drop_hours, len(cur_hours) - 1)
                tgt_hours = cur_hours[:-drop_n]
                tgt_csv = _hours_to_csv(tgt_hours)
                changed, before, after = update_control_key(
                    "no_paper_hours",
                    tgt_csv,
                    "insufficient_relax_hours",
                )
                insufficient_relax_applied = bool(changed)
                insufficient_relax_before = before
                insufficient_relax_after = after
                if changed:
                    insufficient_relax_count = int(insufficient_relax_count + 1)

    if bool(args.auto_unfreeze) and status == "NORMAL":
        if prev_frozen_by_drift:
            if resume_ready:
                changed, before, after = update_control_key("ai_auto_train_enabled", "1", "train_unfreeze")
                train_unfreeze_applied = changed
                train_freeze_before = before
                train_freeze_after = after
                frozen_by_drift = False
            else:
                print(
                    f"[INFO] train_unfreeze gated: normal_streak={normal_streak} "
                    f"< required={resume_required_normals}"
                )
        else:
            print("[INFO] train_unfreeze skipped: not frozen_by_drift")

    if bool(args.auto_resume_trade) and status == "NORMAL":
        if prev_trade_paused_by_drift:
            if resume_ready:
                changed, before, after = update_control_key("trade_enabled", "1", "trade_resume")
                trade_resume_applied = changed
                trade_before = before
                trade_after = after
                trade_paused_by_drift = False
            else:
                print(
                    f"[INFO] trade_resume gated: normal_streak={normal_streak} "
                    f"< required={resume_required_normals}"
                )
        else:
            print("[INFO] trade_resume skipped: not trade_paused_by_drift")

    if bool(args.auto_unblock_hours) and status == "NORMAL":
        if prev_hour_blocked_by_drift:
            if resume_ready:
                restore_hours = str(prev_no_paper_hours_before_drift or "")
                changed, before, after = update_control_key("no_paper_hours", restore_hours, "hour_unblock")
                hour_unblock_applied = changed
                no_paper_hours_before = before
                no_paper_hours_after = after
                hour_blocked_by_drift = False
            else:
                print(
                    f"[INFO] hour_unblock gated: normal_streak={normal_streak} "
                    f"< required={resume_required_normals}"
                )
        else:
            print("[INFO] hour_unblock skipped: not hour_blocked_by_drift")

    if bool(args.auto_restore_risk) and status == "NORMAL":
        if prev_risk_tightened_by_drift:
            if resume_ready:
                if canary_ready:
                    restore_daily = str(prev_daily_loss_limit_before_drift or "")
                    restore_streak_enabled = str(prev_streak_stop_enabled_before_drift or "")
                    restore_streak_max = str(prev_streak_stop_max_losses_before_drift or "")

                    changed_daily, before_daily, after_daily = update_control_key(
                        "daily_loss_limit_pct", restore_daily, "risk_restore_daily_loss"
                    )
                    changed_enabled, before_enabled, after_enabled = update_control_key(
                        "streak_stop_enabled", restore_streak_enabled, "risk_restore_streak_enabled"
                    )
                    changed_max, before_max, after_max = update_control_key(
                        "streak_stop_max_losses", restore_streak_max, "risk_restore_streak_max_losses"
                    )
                    risk_restore_applied = bool(changed_daily or changed_enabled or changed_max)
                    daily_loss_limit_before = before_daily
                    daily_loss_limit_after = after_daily
                    streak_stop_enabled_before = before_enabled
                    streak_stop_enabled_after = after_enabled
                    streak_stop_max_losses_before = before_max
                    streak_stop_max_losses_after = after_max
                    risk_tightened_by_drift = False
                else:
                    print(
                        f"[INFO] risk_restore canary: canary_streak={canary_streak} "
                        f"< required={resume_canary_runs}"
                    )
            else:
                print(
                    f"[INFO] risk_restore gated: normal_streak={normal_streak} "
                    f"< required={resume_required_normals}"
                )
        else:
            print("[INFO] risk_restore skipped: not risk_tightened_by_drift")

    state["_drift_watch"] = {
        "updated_at": _now_text(),
        "status": status,
        "reasons": reasons,
        "ranges": ranges,
        "recent_metrics": {
            "closed_n": recent_n,
            "profit_factor": round(float(recent["profit_factor"]), 6),
            "avg_ret_pct": round(float(recent["avg_ret_pct"]), 6),
            "win_rate_pct": round(float(recent["win_rate_pct"]), 6),
            "ret_sum_pct": round(float(recent["ret_sum_pct"]), 6),
        },
        "baseline_metrics": {
            "closed_n": base_n,
            "profit_factor": round(float(base["profit_factor"]), 6),
            "avg_ret_pct": round(float(base["avg_ret_pct"]), 6),
            "win_rate_pct": round(float(base["win_rate_pct"]), 6),
            "ret_sum_pct": round(float(base["ret_sum_pct"]), 6),
        },
        "drops": {
            "profit_factor_drop": round(float(pf_drop), 6),
            "avg_ret_pct_drop": round(float(avg_ret_drop), 6),
            "win_rate_pct_drop": round(float(win_rate_drop), 6),
        },
        "hourly_stop_analysis": {
            "min_samples": int(args.hour_block_min_samples),
            "max_hours": int(args.hour_block_max_hours),
            "avg_ret_th": float(args.hour_block_avg_ret_th),
            "win_rate_th": float(args.hour_block_win_rate_th),
            "recommended_stop_hours": list(int(h) for h in stop_hours),
            "candidates": stop_hour_candidates,
        },
        "gate": {
            "min_recent_closed": int(args.min_recent_closed),
            "min_baseline_closed": int(args.min_baseline_closed),
            "pf_drop_th": float(args.pf_drop_th),
            "avg_ret_drop_th": float(args.avg_ret_drop_th),
            "win_rate_drop_th": float(args.win_rate_drop_th),
            "resume_require_consecutive_normal": int(resume_required_normals),
            "resume_canary_runs": int(resume_canary_runs),
            "insufficient_auto_relax_hours": bool(args.insufficient_auto_relax_hours),
            "insufficient_relax_after_runs": int(args.insufficient_relax_after_runs),
            "insufficient_relax_drop_hours": int(args.insufficient_relax_drop_hours),
            "insufficient_relax_max_applies": int(args.insufficient_relax_max_applies),
        },
        "normal_streak": int(normal_streak),
        "canary_streak": int(canary_streak),
        "canary_ready": bool(canary_ready),
        "canary_active": bool(canary_active),
        "insufficient_streak": int(insufficient_streak),
        "insufficient_relax_count": int(insufficient_relax_count),
        "resume_ready": bool(resume_ready),
        "weekly_report_recent_path": str(out_recent),
        "weekly_report_baseline_path": str(out_base),
        "weekly_report_recent_rc": int(rc_recent),
        "weekly_report_baseline_rc": int(rc_base),
        "apply_train_freeze": bool(args.apply_train_freeze),
        "auto_unfreeze": bool(args.auto_unfreeze),
        "apply_trade_pause": bool(args.apply_trade_pause),
        "auto_resume_trade": bool(args.auto_resume_trade),
        "apply_hour_block": bool(args.apply_hour_block),
        "auto_unblock_hours": bool(args.auto_unblock_hours),
        "apply_risk_tighten": bool(args.apply_risk_tighten),
        "auto_restore_risk": bool(args.auto_restore_risk),
        "risk_alert_daily_loss_limit_pct": float(args.risk_alert_daily_loss_limit_pct),
        "risk_alert_streak_max_losses": int(args.risk_alert_streak_max_losses),
        "train_freeze_applied": bool(train_freeze_applied),
        "train_unfreeze_applied": bool(train_unfreeze_applied),
        "frozen_by_drift": bool(frozen_by_drift),
        "train_freeze_before": (None if train_freeze_before is None else str(train_freeze_before)),
        "train_freeze_after": (None if train_freeze_after is None else str(train_freeze_after)),
        "trade_pause_applied": bool(trade_pause_applied),
        "trade_resume_applied": bool(trade_resume_applied),
        "trade_paused_by_drift": bool(trade_paused_by_drift),
        "trade_before": (None if trade_before is None else str(trade_before)),
        "trade_after": (None if trade_after is None else str(trade_after)),
        "hour_block_applied": bool(hour_block_applied),
        "hour_unblock_applied": bool(hour_unblock_applied),
        "hour_blocked_by_drift": bool(hour_blocked_by_drift),
        "insufficient_relax_applied": bool(insufficient_relax_applied),
        "insufficient_relax_before": (
            None if insufficient_relax_before is None else str(insufficient_relax_before)
        ),
        "insufficient_relax_after": (
            None if insufficient_relax_after is None else str(insufficient_relax_after)
        ),
        "backup_dir": str(backup_dir),
        "control_backup_path": (None if control_backup_path is None else str(control_backup_path)),
        "state_backup_path": (None if state_backup_path is None else str(state_backup_path)),
        "no_paper_hours_before_drift": str(no_paper_hours_before_drift),
        "no_paper_hours_before": (None if no_paper_hours_before is None else str(no_paper_hours_before)),
        "no_paper_hours_after": (None if no_paper_hours_after is None else str(no_paper_hours_after)),
        "risk_tighten_applied": bool(risk_tighten_applied),
        "risk_restore_applied": bool(risk_restore_applied),
        "risk_tightened_by_drift": bool(risk_tightened_by_drift),
        "daily_loss_limit_before_drift": str(daily_loss_limit_before_drift),
        "streak_stop_enabled_before_drift": str(streak_stop_enabled_before_drift),
        "streak_stop_max_losses_before_drift": str(streak_stop_max_losses_before_drift),
        "daily_loss_limit_before": (None if daily_loss_limit_before is None else str(daily_loss_limit_before)),
        "daily_loss_limit_after": (None if daily_loss_limit_after is None else str(daily_loss_limit_after)),
        "streak_stop_enabled_before": (None if streak_stop_enabled_before is None else str(streak_stop_enabled_before)),
        "streak_stop_enabled_after": (None if streak_stop_enabled_after is None else str(streak_stop_enabled_after)),
        "streak_stop_max_losses_before": (
            None if streak_stop_max_losses_before is None else str(streak_stop_max_losses_before)
        ),
        "streak_stop_max_losses_after": (
            None if streak_stop_max_losses_after is None else str(streak_stop_max_losses_after)
        ),
    }

    if args.dry_run:
        print(f"[DRYRUN] state update path={state_path}")
    else:
        if not state_snapshot_done:
            snap = _snapshot_file(state_path, backup_dir, "state", backup_max_keep)
            state_snapshot_done = True
            if snap is not None:
                state_backup_path = str(snap)
                state["_drift_watch"]["state_backup_path"] = state_backup_path
                print(f"[OK] backup created path={snap}")
        _write_json_dict(state_path, state)
        print(f"[OK] state updated path={state_path}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "Watch recent-vs-baseline performance drift. "
            "Can optionally freeze AI auto-train when severe drift is detected."
        )
    )
    ap.add_argument("--logs-dir", default="../logs", help="main trade_log directory")
    ap.add_argument("--out-dir", default="weekly_report_out", help="weekly report output base dir")
    ap.add_argument("--state-path", default="state.json", help="state json path")
    ap.add_argument("--control-path", default="CONTROL.csv", help="control csv path")

    ap.add_argument("--recent-days", type=int, default=3, help="recent window days (default: 3)")
    ap.add_argument("--baseline-days", type=int, default=14, help="baseline window days (default: 14)")

    ap.add_argument("--min-recent-closed", type=int, default=8, help="minimum recent closed trades")
    ap.add_argument("--min-baseline-closed", type=int, default=20, help="minimum baseline closed trades")
    ap.add_argument("--pf-drop-th", type=float, default=0.20, help="threshold for PF drop")
    ap.add_argument("--avg-ret-drop-th", type=float, default=0.03, help="threshold for avg_ret_pct drop")
    ap.add_argument("--win-rate-drop-th", type=float, default=8.0, help="threshold for win_rate_pct drop")

    ap.add_argument("--apply-train-freeze", action="store_true", help="set ai_auto_train_enabled=0 on ALERT")
    ap.add_argument(
        "--auto-unfreeze",
        action="store_true",
        help="set ai_auto_train_enabled=1 on NORMAL when previously frozen_by_drift",
    )
    ap.add_argument("--apply-trade-pause", action="store_true", help="set trade_enabled=0 on ALERT")
    ap.add_argument(
        "--auto-resume-trade",
        action="store_true",
        help="set trade_enabled=1 on NORMAL when previously trade_paused_by_drift",
    )
    ap.add_argument("--apply-hour-block", action="store_true", help="set no_paper_hours to recommended bad hours on ALERT")
    ap.add_argument(
        "--auto-unblock-hours",
        action="store_true",
        help="restore no_paper_hours on NORMAL when previously hour_blocked_by_drift",
    )
    ap.add_argument("--hour-block-min-samples", type=int, default=2, help="minimum closed trades per hour for hour block candidate")
    ap.add_argument("--hour-block-max-hours", type=int, default=6, help="maximum blocked hours from drift analysis")
    ap.add_argument("--hour-block-avg-ret-th", type=float, default=-0.01, help="block candidate if avg_ret_pct <= this")
    ap.add_argument("--hour-block-win-rate-th", type=float, default=40.0, help="block candidate if win_rate_pct <= this")
    ap.add_argument(
        "--apply-risk-tighten",
        action="store_true",
        help="on ALERT, tighten risk controls: daily_loss_limit_pct and streak_stop_*",
    )
    ap.add_argument(
        "--auto-restore-risk",
        action="store_true",
        help="on NORMAL (after resume gate), restore risk controls tightened by drift",
    )
    ap.add_argument(
        "--risk-alert-daily-loss-limit-pct",
        type=float,
        default=-0.30,
        help="target daily_loss_limit_pct to apply while ALERT when --apply-risk-tighten is set",
    )
    ap.add_argument(
        "--risk-alert-streak-max-losses",
        type=int,
        default=2,
        help="target streak_stop_max_losses while ALERT when --apply-risk-tighten is set",
    )
    ap.add_argument(
        "--resume-require-consecutive-normal",
        type=int,
        default=1,
        help="require this many consecutive NORMAL runs before auto unfreeze/resume/unblock/restore",
    )
    ap.add_argument(
        "--resume-canary-runs",
        type=int,
        default=2,
        help="after resume gate is met, keep tightened risk for this many NORMAL runs before risk restore",
    )
    ap.add_argument(
        "--insufficient-auto-relax-hours",
        action="store_true",
        help="on INSUFFICIENT, gradually relax no_paper_hours while keeping drift protection active",
    )
    ap.add_argument(
        "--insufficient-relax-after-runs",
        type=int,
        default=4,
        help="require this many consecutive INSUFFICIENT runs before each relax apply",
    )
    ap.add_argument(
        "--insufficient-relax-drop-hours",
        type=int,
        default=1,
        help="number of blocked hours to remove from tail of no_paper_hours per relax apply",
    )
    ap.add_argument(
        "--insufficient-relax-max-applies",
        type=int,
        default=2,
        help="maximum relax applies allowed in one consecutive INSUFFICIENT period",
    )
    ap.add_argument(
        "--backup-dir",
        default="backups/drift_watch",
        help="directory for state/control snapshots before write",
    )
    ap.add_argument(
        "--backup-max-keep",
        type=int,
        default=50,
        help="maximum snapshots to keep per kind",
    )
    ap.add_argument(
        "--lock-file",
        default="/tmp/ouroboros-drift-watch.lock",
        help="non-blocking lock file path to avoid concurrent runs",
    )
    ap.add_argument("--dry-run", action="store_true", help="do not write files")
    return ap


def main() -> None:
    args = build_arg_parser().parse_args()
    lock_fp = _acquire_nonblocking_lock(str(args.lock_file))
    if lock_fp is None:
        print(f"[INFO] skip: another drift_watch run is active lock={args.lock_file}")
        sys.exit(0)
    try:
        rc = run_drift_watch(args)
    except ValueError as e:
        print(f"[ERROR] {e}")
        sys.exit(2)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(2)
    except Exception as e:
        print(f"[ERROR] fatal: {e}")
        sys.exit(2)
    finally:
        try:
            lock_fp.close()
        except Exception:
            pass
    sys.exit(rc)


if __name__ == "__main__":
    main()
