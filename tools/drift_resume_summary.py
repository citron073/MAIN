from __future__ import annotations

from typing import Any, Dict, List, Optional


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


def translate_drift_reason_ja(reason: Any) -> str:
    s = str(reason or "").strip()
    if not s:
        return "-"
    if s.startswith("recent_closed<"):
        try:
            need = s.split("<", 1)[1].split(" ", 1)[0]
            actual = s.rsplit("(", 1)[1].rstrip(")")
            return f"直近約定が不足 {actual}/{need}"
        except Exception:
            return s
    if s.startswith("baseline_closed<"):
        try:
            need = s.split("<", 1)[1].split(" ", 1)[0]
            actual = s.rsplit("(", 1)[1].rstrip(")")
            return f"基準期間の約定が不足 {actual}/{need}"
        except Exception:
            return s
    if s.startswith("pf_drop>="):
        try:
            th = s.split(">=", 1)[1].split(" ", 1)[0]
            actual = s.rsplit("(", 1)[1].rstrip(")")
            return f"PF低下 {actual} >= {th}"
        except Exception:
            return s
    if s.startswith("avg_ret_drop>="):
        try:
            th = s.split(">=", 1)[1].split(" ", 1)[0]
            actual = s.rsplit("(", 1)[1].rstrip(")")
            return f"平均損益率低下 {actual} >= {th}"
        except Exception:
            return s
    if s.startswith("win_rate_drop>="):
        try:
            th = s.split(">=", 1)[1].split(" ", 1)[0]
            actual = s.rsplit("(", 1)[1].rstrip(")")
            return f"勝率低下 {actual} >= {th}"
        except Exception:
            return s
    return s


def build_drift_resume_snapshot(drift_obj: Dict[str, Any]) -> Dict[str, Any]:
    drift = dict(drift_obj or {}) if isinstance(drift_obj, dict) else {}
    gate = drift.get("gate", {}) if isinstance(drift.get("gate"), dict) else {}
    recent = drift.get("recent_metrics", {}) if isinstance(drift.get("recent_metrics"), dict) else {}
    baseline = drift.get("baseline_metrics", {}) if isinstance(drift.get("baseline_metrics"), dict) else {}

    status = str(drift.get("status", "UNKNOWN") or "UNKNOWN").upper()
    closed_n = max(0, _safe_int(recent.get("closed_n"), 0))
    min_recent_closed = max(1, _safe_int(gate.get("min_recent_closed"), 1))
    baseline_closed_n = max(0, _safe_int(baseline.get("closed_n"), 0))
    min_baseline_closed = max(0, _safe_int(gate.get("min_baseline_closed"), 0))
    normal_streak = max(0, _safe_int(drift.get("normal_streak"), 0))
    required_normals = max(1, _safe_int(gate.get("resume_require_consecutive_normal"), 1))
    canary_streak = max(0, _safe_int(drift.get("canary_streak"), 0))
    canary_required = max(0, _safe_int(gate.get("resume_canary_runs"), 0))
    resume_ready = _safe_bool(drift.get("resume_ready"), False)
    canary_ready = _safe_bool(drift.get("canary_ready"), False)
    canary_active = _safe_bool(drift.get("canary_active"), False)
    trade_paused_by_drift = _safe_bool(drift.get("trade_paused_by_drift"), False)
    risk_tightened_by_drift = _safe_bool(drift.get("risk_tightened_by_drift"), False)

    remaining_samples = max(0, min_recent_closed - closed_n)
    remaining_baseline_samples = max(0, min_baseline_closed - baseline_closed_n) if min_baseline_closed > 0 else 0
    remaining_normals = max(0, required_normals - normal_streak)
    remaining_canary = max(0, canary_required - canary_streak)

    reason_texts = [
        translate_drift_reason_ja(x)
        for x in list(drift.get("reasons") or [])
        if str(x or "").strip()
    ]

    progress_parts: List[str] = [f"直近 {closed_n}/{min_recent_closed}"]
    if min_baseline_closed > 0:
        progress_parts.append(f"基準 {baseline_closed_n}/{min_baseline_closed}")
    progress_parts.append(f"通常 {normal_streak}/{required_normals}")
    if canary_required > 0:
        progress_parts.append(f"カナリア {canary_streak}/{canary_required}")
    progress = " / ".join(progress_parts)

    phase = "unknown"
    summary = "復帰条件を確認中"
    short = "確認中"

    if status == "NORMAL":
        if canary_active and canary_required > 0 and remaining_canary > 0:
            phase = "canary_active"
            summary = f"カナリア完了まであと{remaining_canary}回"
            short = f"カナリアあと{remaining_canary}回"
        else:
            gating_active = trade_paused_by_drift or risk_tightened_by_drift
            if gating_active and remaining_normals > 0:
                phase = "normals"
                summary = f"復帰まで通常あと{remaining_normals}回"
                short = f"通常あと{remaining_normals}回"
            elif gating_active and canary_required > 0 and remaining_canary > 0:
                phase = "canary"
                summary = f"復帰までカナリアあと{remaining_canary}回"
                short = f"カナリアあと{remaining_canary}回"
            elif resume_ready and (canary_required <= 0 or canary_ready):
                phase = "ready"
                summary = "復帰OK"
                short = "復帰OK"
            else:
                phase = "normal"
                summary = "通常運転"
                short = "通常運転"
    elif status == "INSUFFICIENT":
        if remaining_samples > 0:
            phase = "recent_samples"
            summary = f"復帰まで約定あと{remaining_samples}件"
            short = f"あと{remaining_samples}件"
        elif remaining_baseline_samples > 0:
            phase = "baseline_samples"
            summary = f"基準期間の約定あと{remaining_baseline_samples}件"
            short = f"基準あと{remaining_baseline_samples}件"
        elif remaining_normals > 0:
            phase = "normals"
            summary = f"復帰まで通常あと{remaining_normals}回"
            short = f"通常あと{remaining_normals}回"
        elif canary_required > 0 and remaining_canary > 0:
            phase = "canary"
            summary = f"復帰までカナリアあと{remaining_canary}回"
            short = f"カナリアあと{remaining_canary}回"
        elif resume_ready:
            phase = "ready"
            summary = "復帰OK"
            short = "復帰OK"
        else:
            phase = "pending"
    elif status == "ALERT":
        phase = "alert"
        summary = "ドリフト警戒中"
        short = "警戒中"
    elif status in {"UNKNOWN", "-"}:
        phase = "unknown"
        summary = "ドリフト状態未取得"
        short = "未取得"

    detail_parts: List[str] = [progress]
    if reason_texts:
        detail_parts.insert(0, reason_texts[0])
    if trade_paused_by_drift:
        detail_parts.append("trade pause中")
    if risk_tightened_by_drift:
        detail_parts.append("risk tighten中")
    detail = " ・ ".join(part for part in detail_parts if part)

    return {
        "phase": phase,
        "status": status,
        "summary": summary,
        "short": short,
        "detail": detail,
        "progress": progress,
        "remaining_samples": remaining_samples,
        "remaining_baseline_samples": remaining_baseline_samples,
        "remaining_normals": remaining_normals,
        "remaining_canary": remaining_canary,
        "resume_ready": resume_ready,
        "canary_ready": canary_ready,
        "canary_active": canary_active,
        "trade_paused_by_drift": trade_paused_by_drift,
        "risk_tightened_by_drift": risk_tightened_by_drift,
        "reasons_ja": reason_texts,
    }
