#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.drift_resume_summary import build_drift_resume_snapshot

SECRETS_PATH_DEFAULT = ROOT / ".streamlit" / "secrets.toml"
CONTROL_CSV_DEFAULT = ROOT / "CONTROL.csv"
STATE_JSON_DEFAULT = ROOT / "state.json"
CURSOR_PATH_DEFAULT = ROOT / ".streamlit" / "morning_start_guard.json"
RUN_LOCK_DIR_DEFAULT = ROOT / ".run_lock"
SECRETS_ENV_FALLBACK = Path("/etc/ouroboros/secrets.env")


def _safe_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return int(default)
        s = str(v).strip()
        if not s:
            return int(default)
        return int(float(s))
    except Exception:
        return int(default)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return float(default)
        s = str(v).strip()
        if not s:
            return float(default)
        return float(s)
    except Exception:
        return float(default)


def _load_toml_section(path: Path, section: str) -> Dict[str, Any]:
    if not path.exists():
        return {}
    cur = ""
    out: Dict[str, Any] = {}
    try:
        txt = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    for raw in txt.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            cur = line[1:-1].strip()
            continue
        if cur != section or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        val = v.strip()
        if val.startswith('"') and val.endswith('"') and len(val) >= 2:
            out[key] = val[1:-1]
            continue
        if val.startswith("'") and val.endswith("'") and len(val) >= 2:
            out[key] = val[1:-1]
            continue
        lv = val.lower()
        if lv in {"true", "false"}:
            out[key] = (lv == "true")
            continue
        if " #" in val:
            val = val.split(" #", 1)[0].strip()
        out[key] = val
    return out


def _http_post(url: str, body: bytes, headers: Dict[str, str], timeout_sec: float = 3.0) -> Tuple[bool, str]:
    safe_headers: Dict[str, str] = {}
    for k, v in (headers or {}).items():
        try:
            sv = str(v)
        except Exception:
            continue
        try:
            sv.encode("latin-1")
            safe_headers[str(k)] = sv
        except Exception:
            continue
    req = urllib.request.Request(url=url, data=body, headers=safe_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            code = int(getattr(resp, "status", 200))
            return (200 <= code < 300), f"http={code}"
    except urllib.error.HTTPError as e:
        return False, f"http={e.code}"
    except Exception as e:
        return False, str(e)


def _read_control_rows(path: Path) -> List[List[str]]:
    rows: List[List[str]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            rows.append(list(row))
    return rows


def _control_dict(rows: List[List[str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in rows:
        if len(row) < 2:
            continue
        k = str(row[0]).strip()
        v = str(row[1]).strip()
        if not k or k.lower() == "key":
            continue
        out[k] = v
    return out


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _write_json_preserve_owner(path: Path, obj: Dict[str, Any]) -> None:
    owner_ref = path if path.exists() else path.parent
    st = owner_ref.stat()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, st.st_mode & 0o777)
    except Exception:
        pass
    try:
        os.chown(tmp, st.st_uid, st.st_gid)
    except Exception:
        pass
    tmp.replace(path)
    try:
        os.chown(path, st.st_uid, st.st_gid)
    except Exception:
        pass


def _write_control_rows_preserve_owner(path: Path, rows: List[List[str]]) -> None:
    owner_ref = path if path.exists() else path.parent
    st = owner_ref.stat()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerows(rows)
    try:
        os.chmod(tmp, st.st_mode & 0o777)
    except Exception:
        pass
    try:
        os.chown(tmp, st.st_uid, st.st_gid)
    except Exception:
        pass
    tmp.replace(path)
    try:
        os.chown(path, st.st_uid, st.st_gid)
    except Exception:
        pass


def _upsert_control_values(rows: List[List[str]], updates: Dict[str, str]) -> Tuple[List[List[str]], Dict[str, str]]:
    out = [list(r) for r in rows]
    before: Dict[str, str] = {}
    seen = set()
    for row in out:
        if not row:
            continue
        key = str(row[0]).strip()
        if not key or key.lower() == "key":
            continue
        if key in updates:
            before[key] = str(row[1]).strip() if len(row) >= 2 else ""
            if len(row) >= 2:
                row[1] = str(updates[key])
            else:
                row.append(str(updates[key]))
            seen.add(key)
    for key, value in updates.items():
        if key in seen:
            continue
        before[key] = ""
        out.append([str(key), str(value)])
    return out, before


def _lock_pid(lock_dir: Path) -> Optional[int]:
    lock_file = lock_dir / "lockinfo.txt"
    if not lock_file.exists():
        return None
    try:
        for line in lock_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("pid="):
                return int(line.split("=", 1)[1].strip())
    except Exception:
        return None
    return None


def _runner_alive(lock_dir: Path) -> bool:
    pid = _lock_pid(lock_dir)
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _systemctl_is_active(unit: str) -> bool:
    if not unit:
        return False
    try:
        cp = subprocess.run(
            ["systemctl", "is-active", "--quiet", unit],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return cp.returncode == 0
    except Exception:
        return False


def _update_preflight_ops_check(main_dir: Path, ok: bool, msg: str) -> None:
    """Write live_preflight result to .ops_checks.json for dashboard visibility."""
    ops_path = main_dir / ".ops_checks.json"
    now_dt = datetime.now()
    now_ts = float(now_dt.timestamp())
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    ok_bool = bool(ok)
    msg_text = str(msg or "")
    ops: Dict[str, Any] = {}
    if ops_path.exists():
        try:
            ops = json.loads(ops_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    ops["live_preflight"] = {
        "title": "live_preflight",
        "rc": 0 if ok_bool else 1,
        "ok": ok_bool,
        "updated_ts": now_ts,
        "updated_at": now_str,
        "cmd": str(main_dir / "tools" / "live_preflight.py"),
        "output": msg_text[:200],
    }
    tmp = ops_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ops, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(ops_path)


def _run_live_preflight(main_dir: Path) -> Tuple[bool, str]:
    env = os.environ.copy()
    env_file = Path(env.get("OUROBOROS_SECRETS_ENV_FILE", str(SECRETS_ENV_FALLBACK)))
    if env_file.exists():
        try:
            for raw in env_file.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                k = key.strip()
                if not k:
                    continue
                try:
                    parsed = shlex.split(value.strip(), posix=True)
                    env[k] = parsed[0] if parsed else ""
                except Exception:
                    env[k] = value.strip().strip("\"'")
        except Exception:
            pass
    try:
        cp = subprocess.run(
            [sys.executable, str(main_dir / "tools" / "live_preflight.py")],
            cwd=str(main_dir),
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    except Exception as e:
        return False, str(e)
    text = (cp.stdout or "") + ("\n" + cp.stderr if cp.stderr else "")
    tail = " | ".join([ln.strip() for ln in text.splitlines()[-3:] if ln.strip()])
    if cp.returncode == 0:
        return True, (tail or "preflight_ok")
    return False, (tail or f"preflight_rc={cp.returncode}")


def _day8(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d")


def _start_window_status(
    *,
    now: datetime,
    start_hour: int,
    end_hour: int,
    window_before_min: int,
    grace_after_min: int,
) -> Tuple[bool, str]:
    now_min = int(now.hour * 60 + now.minute)
    start_min = int(max(0, min(23, start_hour)) * 60)
    end_min = int(max(1, min(24, end_hour)) * 60)
    if end_min <= start_min:
        end_min = min(24 * 60, start_min + 60)
    lower = max(0, start_min - max(0, window_before_min))
    upper = min(end_min, start_min + max(0, grace_after_min))
    if lower <= now_min <= upper:
        return True, f"in_window {lower//60:02d}:{lower%60:02d}-{upper//60:02d}:{upper%60:02d}"
    return False, f"outside_window {lower//60:02d}:{lower%60:02d}-{upper//60:02d}:{upper%60:02d}"


def _trade_disable_context(notifier_cursor: Dict[str, Any], *, now: datetime) -> Dict[str, Any]:
    obj = notifier_cursor if isinstance(notifier_cursor, dict) else {}
    reason = str(obj.get("trade_enabled_disabled_reason", "") or "").strip()
    disabled_day8 = str(
        obj.get("trade_enabled_disabled_day8", "") or obj.get("daily_trade_disabled_day8", "") or ""
    ).strip()
    disabled_at = str(obj.get("trade_enabled_disabled_at", "") or "").strip()
    disabled_exec_mode = str(obj.get("trade_enabled_disabled_exec_mode", "") or "").strip().upper()
    disabled_pos_id = str(obj.get("trade_enabled_disabled_pos_id", "") or "").strip()
    legacy_auto_disabled = bool(disabled_day8 and not reason)
    auto_disabled = bool(reason == "daily_loss_breach" or legacy_auto_disabled)
    from_previous_day = bool(disabled_day8 and disabled_day8 != _day8(now))
    return {
        "reason": reason or ("daily_loss_breach" if legacy_auto_disabled else ""),
        "disabled_day8": disabled_day8,
        "disabled_at": disabled_at,
        "disabled_exec_mode": disabled_exec_mode,
        "disabled_pos_id": disabled_pos_id,
        "legacy_auto_disabled": legacy_auto_disabled,
        "auto_disabled": auto_disabled,
        "from_previous_day": from_previous_day,
    }


def evaluate_morning_start(
    control: Dict[str, str],
    state: Dict[str, Any],
    notifier_cursor: Optional[Dict[str, Any]] = None,
    *,
    now: Optional[datetime] = None,
    window_before_min: int = 20,
    grace_after_min: int = 5,
    auto_enable_today_on: bool = True,
    auto_enable_trade_enabled: bool = True,
    require_drift_normal: bool = True,
    allow_sample_recovery_on_drift_insufficient: bool = True,
    sample_recovery_max_remaining_samples: int = 4,
    allow_deep_sample_recovery_on_drift_insufficient: bool = True,
    deep_sample_recovery_max_remaining_samples: int = 6,
    deep_recovery_daily_loss_limit_pct: float = -0.30,
    deep_recovery_streak_max_losses: int = 2,
) -> Dict[str, Any]:
    base_now = now or datetime.now()
    start_hour = max(0, min(23, _safe_int(control.get("start_hour"), 10)))
    end_hour = max(1, min(24, _safe_int(control.get("end_hour"), 17)))
    in_window, window_reason = _start_window_status(
        now=base_now,
        start_hour=start_hour,
        end_hour=end_hour,
        window_before_min=window_before_min,
        grace_after_min=grace_after_min,
    )
    if not in_window:
        return {
            "status": "skip",
            "ok": False,
            "within_window": False,
            "window_reason": window_reason,
            "block_reasons": [],
            "updates": {},
            "start_hour": start_hour,
            "end_hour": end_hour,
        }

    paper_mode = _safe_bool(control.get("paper_mode"), False)
    live_enabled = _safe_bool(control.get("live_enabled"), False)
    today_on = _safe_bool(control.get("today_on"), True)
    trade_enabled = _safe_bool(control.get("trade_enabled"), True)
    observe_only = _safe_bool(control.get("observe_only"), False)
    safety_hard_block = _safe_bool(control.get("safety_hard_block"), False)
    risk_stop = _safe_bool(state.get("_risk_stop"), False)
    streak_stop = _safe_bool(state.get("_streak_stop"), False)

    drift_obj = state.get("_drift_watch", {}) if isinstance(state.get("_drift_watch"), dict) else {}
    drift_status = str(drift_obj.get("status", "UNKNOWN") or "UNKNOWN").upper()
    resume_ready = _safe_bool(drift_obj.get("resume_ready"), False)
    canary_ready = _safe_bool(drift_obj.get("canary_ready"), False)
    trade_paused_by_drift = _safe_bool(drift_obj.get("trade_paused_by_drift"), False)
    risk_tightened_by_drift = _safe_bool(drift_obj.get("risk_tightened_by_drift"), False)
    resume_outlook = build_drift_resume_snapshot(drift_obj)
    remaining_samples = max(0, _safe_int(resume_outlook.get("remaining_samples"), 0))
    remaining_baseline_samples = max(0, _safe_int(resume_outlook.get("remaining_baseline_samples"), 0))
    trade_disable_ctx = _trade_disable_context(notifier_cursor or {}, now=base_now)
    current_daily_loss_limit_pct = _safe_float(control.get("daily_loss_limit_pct"), -1.0)
    current_streak_stop_enabled = _safe_bool(control.get("streak_stop_enabled"), False)
    current_streak_stop_max_losses = max(1, _safe_int(control.get("streak_stop_max_losses"), 3))

    updates: Dict[str, str] = {}
    block_reasons: List[str] = []
    sample_recovery_reason = ""
    sample_recovery_from_previous_day_auto_disable = bool(
        allow_sample_recovery_on_drift_insufficient
        and drift_status == "INSUFFICIENT"
        and not trade_paused_by_drift
        and trade_disable_ctx.get("auto_disabled")
        and trade_disable_ctx.get("from_previous_day")
        and not risk_tightened_by_drift
        and not paper_mode
        and live_enabled
        and not observe_only
        and not safety_hard_block
        and not risk_stop
        and not streak_stop
    )
    sample_recovery_near_threshold = bool(
        allow_sample_recovery_on_drift_insufficient
        and drift_status == "INSUFFICIENT"
        and not trade_paused_by_drift
        and not risk_tightened_by_drift
        and not paper_mode
        and live_enabled
        and not observe_only
        and not safety_hard_block
        and not risk_stop
        and not streak_stop
        and not trade_enabled
        and remaining_baseline_samples <= 0
        and 0 < remaining_samples <= max(0, int(sample_recovery_max_remaining_samples))
    )
    sample_recovery_deep_shortage = bool(
        allow_deep_sample_recovery_on_drift_insufficient
        and drift_status == "INSUFFICIENT"
        and not trade_paused_by_drift
        and not paper_mode
        and live_enabled
        and not observe_only
        and not safety_hard_block
        and not risk_stop
        and not streak_stop
        and not trade_enabled
        and remaining_baseline_samples <= 0
        and remaining_samples > max(0, int(sample_recovery_max_remaining_samples))
        and remaining_samples <= max(0, int(deep_sample_recovery_max_remaining_samples))
    )
    sample_recovery_mode = bool(
        sample_recovery_from_previous_day_auto_disable
        or sample_recovery_near_threshold
        or sample_recovery_deep_shortage
    )
    if sample_recovery_from_previous_day_auto_disable:
        sample_recovery_reason = "previous_day_daily_loss_breach"
    elif sample_recovery_near_threshold:
        sample_recovery_reason = "low_sample_shortage"
    elif sample_recovery_deep_shortage:
        sample_recovery_reason = "deep_sample_shortage"

    if paper_mode:
        block_reasons.append("paper_mode=1")
    if not live_enabled:
        block_reasons.append("live_enabled=0")
    if observe_only:
        block_reasons.append("observe_only=1")
    if safety_hard_block:
        block_reasons.append("safety_hard_block=1")
    if risk_stop:
        block_reasons.append("risk_stop=ON")
    if streak_stop:
        block_reasons.append("streak_stop=ON")
    if require_drift_normal and drift_status != "NORMAL" and not sample_recovery_mode:
        block_reasons.append(f"drift={drift_status}")
    if trade_paused_by_drift and not resume_ready:
        block_reasons.append("trade_paused_by_drift")
    if risk_tightened_by_drift and not canary_ready:
        block_reasons.append("risk_restore_canary_pending")

    if not today_on:
        if auto_enable_today_on:
            updates["today_on"] = "1"
        else:
            block_reasons.append("today_on=0")

    if not trade_enabled:
        if auto_enable_trade_enabled:
            updates["trade_enabled"] = "1"
        else:
            block_reasons.append("trade_enabled=0")

    if sample_recovery_reason == "deep_sample_shortage":
        target_daily_loss_limit_pct = float(deep_recovery_daily_loss_limit_pct)
        target_streak_max_losses = max(1, int(deep_recovery_streak_max_losses))
        if current_daily_loss_limit_pct < target_daily_loss_limit_pct:
            updates["daily_loss_limit_pct"] = str(target_daily_loss_limit_pct)
        if not current_streak_stop_enabled:
            updates["streak_stop_enabled"] = "1"
        if current_streak_stop_max_losses > target_streak_max_losses:
            updates["streak_stop_max_losses"] = str(target_streak_max_losses)

    effective_today_on = bool(updates.get("today_on") == "1" or today_on)
    effective_trade_enabled = bool(updates.get("trade_enabled") == "1" or trade_enabled)
    effective_live_candidate = bool(
        (not paper_mode)
        and live_enabled
        and effective_today_on
        and effective_trade_enabled
        and (not observe_only)
        and (not safety_hard_block)
        and (not risk_stop)
        and (not streak_stop)
        and (not block_reasons)
    )

    return {
        "status": "ready" if not block_reasons else "blocked",
        "ok": not block_reasons,
        "within_window": True,
        "window_reason": window_reason,
        "block_reasons": block_reasons,
        "updates": updates,
        "paper_mode": paper_mode,
        "live_enabled": live_enabled,
        "today_on": today_on,
        "trade_enabled": trade_enabled,
        "observe_only": observe_only,
        "safety_hard_block": safety_hard_block,
        "risk_stop": risk_stop,
        "streak_stop": streak_stop,
        "drift_status": drift_status,
        "resume_outlook": resume_outlook,
        "resume_ready": resume_ready,
        "canary_ready": canary_ready,
        "trade_paused_by_drift": trade_paused_by_drift,
        "risk_tightened_by_drift": risk_tightened_by_drift,
        "sample_recovery_mode": sample_recovery_mode,
        "sample_recovery_reason": sample_recovery_reason,
        "deep_recovery_daily_loss_limit_pct": float(deep_recovery_daily_loss_limit_pct),
        "deep_recovery_streak_max_losses": int(deep_recovery_streak_max_losses),
        "trade_disable_context": trade_disable_ctx,
        "effective_live_candidate": effective_live_candidate,
        "start_hour": start_hour,
        "end_hour": end_hour,
    }


def _notify_signature(result: str, decision: Dict[str, Any], action_updates: Dict[str, str], bot_action: str) -> str:
    parts = [
        str(result),
        ",".join(str(x) for x in decision.get("block_reasons", [])),
        ",".join(f"{k}={v}" for k, v in sorted(action_updates.items())),
        str(bot_action),
        str(decision.get("drift_status", "")),
    ]
    return "|".join(parts)


def _should_notify(cursor: Dict[str, Any], *, day8: str, signature: str) -> bool:
    last_day8 = str(cursor.get("last_notify_day8", "")).strip()
    last_sig = str(cursor.get("last_notify_signature", "")).strip()
    return not (last_day8 == day8 and last_sig == signature)


def _send_notification(
    *,
    title: str,
    text: str,
    payload: Dict[str, Any],
    secrets_path: Path,
    enabled_default: bool = True,
) -> Tuple[bool, str]:
    sec = _load_toml_section(secrets_path, "dashboard_security")
    enabled = _safe_bool(sec.get("morning_start_notify_enabled"), enabled_default)
    if not enabled:
        return False, "disabled"

    ntfy_url = str(sec.get("ntfy_topic_url", "")).strip()
    ntfy_token = str(sec.get("ntfy_bearer_token", "")).strip()
    webhook_url = str(sec.get("trade_notify_webhook_url", "")).strip()
    webhook_token = str(sec.get("trade_notify_bearer_token", "")).strip()

    if not ntfy_url and not webhook_url:
        return False, "no_target"

    results: List[Tuple[bool, str, str]] = []
    if ntfy_url:
        headers = {
            "Title": title,
            "Tags": "bell",
            "Priority": "default",
            "Content-Type": "text/plain; charset=utf-8",
        }
        if ntfy_token:
            headers["Authorization"] = f"Bearer {ntfy_token}"
        ok, msg = _http_post(ntfy_url, text.encode("utf-8"), headers, timeout_sec=3.0)
        results.append((ok, "ntfy", msg))

    if webhook_url:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if webhook_token:
            headers["Authorization"] = f"Bearer {webhook_token}"
        ok, msg = _http_post(webhook_url, body, headers, timeout_sec=3.0)
        results.append((ok, "webhook", msg))

    ok_any = any(ok for ok, _, _ in results)
    text_msg = ", ".join([f"{name}:{msg}" for ok, name, msg in results if ok]) or ", ".join(
        [f"{name}:{msg}" for _, name, msg in results]
    )
    return ok_any, (text_msg or "no_result")


def run_morning_start_guard(args: argparse.Namespace) -> int:
    main_dir = Path(args.main_dir).resolve()
    control_path = Path(args.control_path).resolve()
    state_path = Path(args.state_path).resolve()
    secrets_path = Path(args.secrets_path).resolve()
    cursor_path = Path(args.cursor_path).resolve()
    trade_event_cursor_path = Path(
        getattr(args, "trade_event_cursor_path", str(ROOT / ".streamlit" / "trade_event_cursor.json"))
    ).resolve()
    run_lock_dir = Path(args.run_lock_dir).resolve()

    rows = _read_control_rows(control_path)
    control = _control_dict(rows)
    state = _load_json(state_path)
    cursor = _load_json(cursor_path)
    notifier_cursor = _load_json(trade_event_cursor_path)
    now = datetime.now()
    today8 = _day8(now)
    sec = _load_toml_section(secrets_path, "dashboard_security")

    decision = evaluate_morning_start(
        control,
        state,
        notifier_cursor,
        now=now,
        window_before_min=max(0, int(args.window_before_min)),
        grace_after_min=max(0, int(args.grace_after_min)),
        auto_enable_today_on=bool(args.auto_enable_today_on),
        auto_enable_trade_enabled=bool(args.auto_enable_trade),
        require_drift_normal=not bool(args.allow_drift_warn),
        allow_sample_recovery_on_drift_insufficient=_safe_bool(
            sec.get(
                "morning_start_allow_sample_recovery_on_drift_insufficient",
                True,
            ),
            True,
        ),
        sample_recovery_max_remaining_samples=max(
            0,
            _safe_int(
                sec.get(
                    "morning_start_sample_recovery_max_remaining_samples",
                    4,
                ),
                4,
            ),
        ),
        allow_deep_sample_recovery_on_drift_insufficient=_safe_bool(
            sec.get("morning_start_allow_deep_sample_recovery_on_drift_insufficient", True),
            True,
        ),
        deep_sample_recovery_max_remaining_samples=max(
            0,
            _safe_int(sec.get("morning_start_deep_sample_recovery_max_remaining_samples", 6), 6),
        ),
        deep_recovery_daily_loss_limit_pct=_safe_float(
            sec.get("morning_start_deep_recovery_daily_loss_limit_pct", -0.30),
            -0.30,
        ),
        deep_recovery_streak_max_losses=max(
            1,
            _safe_int(sec.get("morning_start_deep_recovery_streak_max_losses", 2), 2),
        ),
    )

    action_updates: Dict[str, str] = {}
    action_updates_before: Dict[str, str] = {}
    bot_action = "noop"
    preflight_ok = True
    preflight_msg = "skipped"

    if decision.get("status") == "ready" and decision.get("effective_live_candidate"):
        preflight_ok, preflight_msg = _run_live_preflight(main_dir)
        _update_preflight_ops_check(main_dir, preflight_ok, preflight_msg)
        if not preflight_ok:
            decision["status"] = "blocked"
            decision["ok"] = False
            decision.setdefault("block_reasons", []).append("live_preflight_failed")

    if decision.get("status") == "ready":
        action_updates = dict(decision.get("updates") or {})
        if action_updates and not args.dry_run:
            new_rows, before = _upsert_control_values(rows, action_updates)
            action_updates_before = dict(before)
            _write_control_rows_preserve_owner(control_path, new_rows)
            rows = new_rows
            control = _control_dict(rows)
            action_updates = {k: f"{before.get(k, '')}->{v}" for k, v in action_updates.items()}
        elif action_updates:
            action_updates = {k: f"{control.get(k, '')}->{v}" for k, v in action_updates.items()}

        if (
            decision.get("sample_recovery_mode")
            and "trade_enabled" in dict(decision.get("updates") or {})
            and not args.dry_run
            and isinstance(notifier_cursor, dict)
        ):
            sample_recovery_reason = str(decision.get("sample_recovery_reason") or "").strip()
            if sample_recovery_reason == "previous_day_daily_loss_breach":
                notifier_cursor["trade_enabled_disabled_reason"] = ""
                notifier_cursor["trade_enabled_disabled_at"] = ""
                notifier_cursor["trade_enabled_disabled_exec_mode"] = ""
                notifier_cursor["trade_enabled_disabled_pos_id"] = ""
            notifier_cursor["trade_enabled_reenabled_reason"] = "morning_sample_recovery"
            if sample_recovery_reason:
                notifier_cursor["trade_enabled_reenabled_reason"] = f"morning_sample_recovery:{sample_recovery_reason}"
            notifier_cursor["trade_enabled_reenabled_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
            _write_json_preserve_owner(trade_event_cursor_path, notifier_cursor)

        elif (
            not decision.get("sample_recovery_mode")
            and "trade_enabled" in dict(decision.get("updates") or {})
            and not args.dry_run
            and isinstance(notifier_cursor, dict)
        ):
            drift_st = str(decision.get("drift_status", "") or "")
            re_reason = "morning_drift_normal" if drift_st == "NORMAL" else f"morning_normal_recovery:drift={drift_st}"
            notifier_cursor["trade_enabled_reenabled_reason"] = re_reason
            notifier_cursor["trade_enabled_reenabled_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
            _write_json_preserve_owner(trade_event_cursor_path, notifier_cursor)

        if (
            decision.get("sample_recovery_mode")
            and not args.dry_run
            and str(decision.get("sample_recovery_reason") or "").strip() == "deep_sample_shortage"
        ):
            drift_obj = state.get("_drift_watch", {}) if isinstance(state.get("_drift_watch"), dict) else {}
            if not isinstance(drift_obj, dict):
                drift_obj = {}
            if "daily_loss_limit_pct" in dict(decision.get("updates") or {}) and not str(
                drift_obj.get("daily_loss_limit_before_drift", "") or ""
            ).strip():
                drift_obj["daily_loss_limit_before_drift"] = str(
                    action_updates_before.get("daily_loss_limit_pct", control.get("daily_loss_limit_pct", ""))
                )
            if "streak_stop_enabled" in dict(decision.get("updates") or {}) and not str(
                drift_obj.get("streak_stop_enabled_before_drift", "") or ""
            ).strip():
                drift_obj["streak_stop_enabled_before_drift"] = str(
                    action_updates_before.get("streak_stop_enabled", control.get("streak_stop_enabled", ""))
                )
            if "streak_stop_max_losses" in dict(decision.get("updates") or {}) and not str(
                drift_obj.get("streak_stop_max_losses_before_drift", "") or ""
            ).strip():
                drift_obj["streak_stop_max_losses_before_drift"] = str(
                    action_updates_before.get("streak_stop_max_losses", control.get("streak_stop_max_losses", ""))
                )
            if any(
                key in dict(decision.get("updates") or {})
                for key in ("daily_loss_limit_pct", "streak_stop_enabled", "streak_stop_max_losses")
            ):
                drift_obj["risk_tightened_by_drift"] = True
                drift_obj["updated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
                state["_drift_watch"] = drift_obj
                _write_json_preserve_owner(state_path, state)

        runner_alive = _runner_alive(run_lock_dir)
        service_active = _systemctl_is_active(args.bot_service) if args.bot_service else False
        if (not runner_alive and not service_active) and args.start_bot_service and args.bot_service:
            if args.dry_run:
                bot_action = f"would_start:{args.bot_service}"
            else:
                cp = subprocess.run(
                    ["systemctl", "start", args.bot_service],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                if cp.returncode == 0:
                    bot_action = f"started:{args.bot_service}"
                else:
                    bot_action = f"start_failed:{args.bot_service}"
                    decision["status"] = "blocked"
                    decision["ok"] = False
                    decision.setdefault("block_reasons", []).append("bot_service_start_failed")
        else:
            bot_action = "already_running" if (runner_alive or service_active) else "not_started"

    result = str(decision.get("status", "skip"))
    summary = {
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "result": result,
        "window": str(decision.get("window_reason", "-")),
        "block_reasons": list(decision.get("block_reasons", [])),
        "resume_outlook": dict(decision.get("resume_outlook") or {}),
        "trade_disable_context": dict(decision.get("trade_disable_context") or {}),
        "sample_recovery_mode": bool(decision.get("sample_recovery_mode")),
        "sample_recovery_reason": str(decision.get("sample_recovery_reason") or ""),
        "updates": action_updates,
        "bot_action": bot_action,
        "preflight": {"ok": preflight_ok, "msg": preflight_msg},
    }

    if args.print_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"[{result.upper()}] morning_start_guard {summary['window']}")
        if summary["block_reasons"]:
            print("reasons=" + "; ".join(summary["block_reasons"]))
        if summary["resume_outlook"]:
            print("resume_outlook=" + str((summary["resume_outlook"] or {}).get("summary", "-")))
        if summary["sample_recovery_mode"]:
            print(
                "recovery_mode=sample_collection"
                + (
                    f" reason={summary['sample_recovery_reason']}"
                    if summary.get("sample_recovery_reason")
                    else ""
                )
            )
        if action_updates:
            print("updates=" + "; ".join(f"{k}:{v}" for k, v in action_updates.items()))
        print(f"bot={bot_action}")
        print(f"preflight={'OK' if preflight_ok else 'FAIL'} {preflight_msg}")

    if args.notify and decision.get("within_window"):
        title = {
            "ready": "Ouroboros 朝チェックOK",
            "blocked": "Ouroboros 朝チェック保留",
            "skip": "Ouroboros 朝チェック待機",
        }.get(result, "Ouroboros 朝チェック")
        text = (
            f"{title}\n"
            f"時刻={summary['time']}\n"
            f"window={summary['window']}\n"
            f"reasons={' / '.join(summary['block_reasons']) if summary['block_reasons'] else '-'}\n"
            f"resume_outlook={str((summary['resume_outlook'] or {}).get('summary', '-') or '-')}\n"
            f"resume_detail={str((summary['resume_outlook'] or {}).get('detail', '-') or '-')}\n"
            f"sample_recovery_mode={'ON' if summary['sample_recovery_mode'] else 'OFF'}\n"
            f"sample_recovery_reason={summary['sample_recovery_reason'] or '-'}\n"
            f"updates={' / '.join(f'{k}:{v}' for k, v in action_updates.items()) if action_updates else '-'}\n"
            f"bot={bot_action}\n"
            f"preflight={'OK' if preflight_ok else 'FAIL'} {preflight_msg}\n"
            f"host={os.uname().nodename if hasattr(os, 'uname') else '-'}"
        )
        sig = _notify_signature(result, decision, action_updates, bot_action)
        if _should_notify(cursor, day8=today8, signature=sig):
            ok, msg = _send_notification(
                title=title,
                text=text,
                payload={"event": "morning_start_guard", **summary},
                secrets_path=secrets_path,
                enabled_default=True,
            )
            print(f"[{'OK' if ok else 'INFO'}] notify {msg}")
            cursor["last_notify_day8"] = today8
            cursor["last_notify_signature"] = sig

    cursor["last_run_day8"] = today8
    cursor["last_result"] = result
    cursor["last_summary"] = summary
    if not args.dry_run:
        _write_json_preserve_owner(cursor_path, cursor)

    return 0 if result in {"ready", "blocked", "skip"} else 1


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Morning safety check and optional bot/trade auto start.")
    ap.add_argument("--main-dir", default=str(ROOT))
    ap.add_argument("--control-path", default=str(CONTROL_CSV_DEFAULT))
    ap.add_argument("--state-path", default=str(STATE_JSON_DEFAULT))
    ap.add_argument("--secrets-path", default=str(SECRETS_PATH_DEFAULT))
    ap.add_argument("--cursor-path", default=str(CURSOR_PATH_DEFAULT))
    ap.add_argument("--trade-event-cursor-path", default=str(ROOT / ".streamlit" / "trade_event_cursor.json"))
    ap.add_argument("--run-lock-dir", default=str(RUN_LOCK_DIR_DEFAULT))
    ap.add_argument("--bot-service", default="ouroboros-bot.service")
    ap.add_argument("--window-before-min", type=int, default=20)
    ap.add_argument("--grace-after-min", type=int, default=5)
    ap.add_argument("--auto-enable-today-on", action="store_true")
    ap.add_argument("--auto-enable-trade", action="store_true")
    ap.add_argument("--allow-drift-warn", action="store_true", help="allow morning start when drift status is WARN")
    ap.add_argument("--start-bot-service", action="store_true")
    ap.add_argument("--notify", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--print-json", action="store_true")
    return ap


def main() -> int:
    return run_morning_start_guard(build_arg_parser().parse_args())


if __name__ == "__main__":
    sys.exit(main())
