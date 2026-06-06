#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from tools.apply_daily_reflection import apply_daily_reflection_report
    from tools.drift_resume_summary import build_drift_resume_snapshot
    from tools.llm_provider import normalize_openai_base_url, run_openai_responses_summary
    from tools.notification_policy import (
        LEVEL_CRITICAL,
        LEVEL_INFO,
        LEVEL_WARN,
        priority_for_level,
        tags_for_level,
    )
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.apply_daily_reflection import apply_daily_reflection_report
    from tools.drift_resume_summary import build_drift_resume_snapshot
    from tools.llm_provider import normalize_openai_base_url, run_openai_responses_summary
    from tools.notification_policy import (
        LEVEL_CRITICAL,
        LEVEL_INFO,
        LEVEL_WARN,
        priority_for_level,
        tags_for_level,
    )

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR_DEFAULT = ROOT.parent / "logs"
CURSOR_PATH_DEFAULT = ROOT / ".streamlit" / "trade_event_cursor.json"
SECRETS_PATH_DEFAULT = ROOT / ".streamlit" / "secrets.toml"
STATE_JSON_DEFAULT = ROOT / "state.json"
RUN_LOCK_DIR_DEFAULT = ROOT / ".run_lock"
CONTROL_CSV_DEFAULT = ROOT / "CONTROL.csv"
DAILY_REPORT_OUT_DIR_DEFAULT = ROOT / "daily_report_out"
OLLAMA_BASE_URL_DEFAULT = os.getenv("OUROBOROS_OLLAMA_BASE_URL", os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
OLLAMA_MODEL_DEFAULT = os.getenv("OUROBOROS_OLLAMA_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b"))
OLLAMA_TIMEOUT_SEC_DEFAULT = 240
OLLAMA_MAX_CHARS_DEFAULT = 700
OPENAI_BASE_URL_DEFAULT = os.getenv("OUROBOROS_OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL_DEFAULT = os.getenv("OUROBOROS_OPENAI_MODEL", "gpt-5.4-mini")
OPENAI_API_KEY_ENV_DEFAULT = os.getenv("OUROBOROS_OPENAI_API_KEY_ENV", "OPENAI_API_KEY")
OPENAI_MAX_OUTPUT_TOKENS_DEFAULT = 320
MODEL_SIZE_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*b", re.IGNORECASE)


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            out = dict(default)
            out.update(obj)
            return out
    except Exception:
        pass
    return dict(default)


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _safe_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "on", "y"}:
        return True
    if s in {"0", "false", "no", "off", "n"}:
        return False
    return default


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        return float(s)
    except Exception:
        return None


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


def _parse_time(v: Any) -> Optional[datetime]:
    s = str(v or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


_NOTE_KV_RE = re.compile(r"(\b[a-zA-Z_][a-zA-Z0-9_]*)=([^\s]+)")


def _parse_note_kv(note: Any) -> Dict[str, str]:
    text = str(note or "")
    out: Dict[str, str] = {}
    for m in _NOTE_KV_RE.finditer(text):
        key = str(m.group(1) or "").strip()
        val = str(m.group(2) or "").strip().rstrip(",")
        if key and key not in out:
            out[key] = val
    return out


def _technical_feature_labels_from_note(note: Any) -> List[str]:
    kv = _parse_note_kv(note)
    labels: List[str] = []

    def add(key: str, label_key: Optional[str] = None, *, skip: Tuple[str, ...] = ("", "NA", "none")) -> None:
        val = str(kv.get(key, "") or "").strip()
        if val in skip:
            return
        labels.append(f"{label_key or key}={val}")

    add("gc_recent", "gc_recent")
    if str(kv.get("gc_strong", "")).strip() == "1":
        labels.append("gc_strong=1")
    add("ti_rsi_zone", "rsi")
    add("ti_bb_zone", "bb")
    add("ti_atr_regime", "atr")
    add("ti_trend_power_regime", "trend_power")
    add("cp_name", "pattern")
    add("cp_stage", "pattern_stage")
    add("cp_bias", "pattern_bias")
    add("cp_quality", "pattern_quality")
    if str(kv.get("cp_confirmed", "")).strip() == "1":
        labels.append("pattern_confirmed=1")
    add("phase", "phase")
    add("phase_reason", "phase_reason")
    add("phase_momentum", "phase_momentum")
    add("phase_transition", "phase_transition")
    if str(kv.get("up_break", "")).strip() == "1":
        labels.append("up_break=1")
    if str(kv.get("down_break", "")).strip() == "1":
        labels.append("down_break=1")
    add("aiba_trend", "aiba_trend")
    add("aiba_cross", "aiba_cross")
    add("aiba_ppp", "aiba_ppp")
    if str(kv.get("aiba_9", "")).strip() == "1":
        labels.append("aiba_9=1")
    if str(kv.get("aiba_try_fail", "")).strip() == "1":
        labels.append("aiba_try_fail=1")

    seen = set()
    out: List[str] = []
    for label in labels:
        if label not in seen:
            out.append(label)
            seen.add(label)
    return out


def _update_technical_feature_outcome(
    table: Dict[str, Dict[str, Any]],
    label: str,
    *,
    exit_reason: str,
    ret_pct: float,
    pnl_jpy: Optional[float],
    mfe_pct: Optional[float] = None,
    mae_proxy_pct: Optional[float] = None,
    giveback_pct: Optional[float] = None,
) -> None:
    if not label:
        return
    row = table.setdefault(
        label,
        {
            "n": 0,
            "win_n": 0,
            "loss_n": 0,
            "flat_n": 0,
            "ret_sum_pct": 0.0,
            "pnl_jpy_sum": 0.0,
            "mfe_sum_pct": 0.0,
            "mae_proxy_sum_pct": 0.0,
            "giveback_sum_pct": 0.0,
            "mfe_n": 0,
            "mae_proxy_n": 0,
            "giveback_n": 0,
            "TP": 0,
            "SL": 0,
            "TIMEOUT": 0,
            "OTHER": 0,
        },
    )
    row["n"] = int(row.get("n", 0)) + 1
    row["ret_sum_pct"] = float(row.get("ret_sum_pct", 0.0)) + float(ret_pct)
    row["pnl_jpy_sum"] = float(row.get("pnl_jpy_sum", 0.0)) + float(pnl_jpy or 0.0)
    if mfe_pct is not None:
        row["mfe_sum_pct"] = float(row.get("mfe_sum_pct", 0.0)) + float(mfe_pct)
        row["mfe_n"] = int(row.get("mfe_n", 0)) + 1
    if mae_proxy_pct is not None:
        row["mae_proxy_sum_pct"] = float(row.get("mae_proxy_sum_pct", 0.0)) + float(mae_proxy_pct)
        row["mae_proxy_n"] = int(row.get("mae_proxy_n", 0)) + 1
    if giveback_pct is not None:
        row["giveback_sum_pct"] = float(row.get("giveback_sum_pct", 0.0)) + float(giveback_pct)
        row["giveback_n"] = int(row.get("giveback_n", 0)) + 1
    if float(ret_pct) > 0:
        row["win_n"] = int(row.get("win_n", 0)) + 1
    elif float(ret_pct) < 0:
        row["loss_n"] = int(row.get("loss_n", 0)) + 1
    else:
        row["flat_n"] = int(row.get("flat_n", 0)) + 1

    reason = str(exit_reason or "OTHER").strip().upper()
    if reason not in ("TP", "SL", "TIMEOUT"):
        reason = "OTHER"
    row[reason] = int(row.get(reason, 0)) + 1


def _finalize_technical_feature_outcomes(table: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for label, row in sorted(table.items(), key=lambda item: (-int(_safe_int(item[1].get("n"), 0)), str(item[0]))):
        n = int(_safe_int(row.get("n"), 0))
        win_n = int(_safe_int(row.get("win_n"), 0))
        new_row = dict(row)
        new_row["win_rate_pct"] = round((float(win_n) / float(n) * 100.0) if n > 0 else 0.0, 4)
        new_row["avg_ret_pct"] = round((float(_safe_float(row.get("ret_sum_pct")) or 0.0) / float(n)) if n > 0 else 0.0, 6)
        new_row["ret_sum_pct"] = round(float(_safe_float(row.get("ret_sum_pct")) or 0.0), 6)
        new_row["pnl_jpy_sum"] = round(float(_safe_float(row.get("pnl_jpy_sum")) or 0.0), 6)
        mfe_n = int(_safe_int(row.get("mfe_n"), 0))
        mae_n = int(_safe_int(row.get("mae_proxy_n"), 0))
        giveback_n = int(_safe_int(row.get("giveback_n"), 0))
        new_row["mfe_sum_pct"] = round(float(_safe_float(row.get("mfe_sum_pct")) or 0.0), 6)
        new_row["mae_proxy_sum_pct"] = round(float(_safe_float(row.get("mae_proxy_sum_pct")) or 0.0), 6)
        new_row["giveback_sum_pct"] = round(float(_safe_float(row.get("giveback_sum_pct")) or 0.0), 6)
        new_row["avg_mfe_pct"] = round((new_row["mfe_sum_pct"] / float(mfe_n)) if mfe_n > 0 else 0.0, 6)
        new_row["avg_mae_proxy_pct"] = round((new_row["mae_proxy_sum_pct"] / float(mae_n)) if mae_n > 0 else 0.0, 6)
        new_row["avg_giveback_pct"] = round((new_row["giveback_sum_pct"] / float(giveback_n)) if giveback_n > 0 else 0.0, 6)
        out[str(label)] = new_row
    return out


def _update_market_phase_outcome(
    table: Dict[str, Dict[str, Any]],
    phase: str,
    *,
    exit_reason: str,
    ret_pct: float,
    pnl_jpy: Optional[float],
    up_break: bool,
    down_break: bool,
    momentum: str,
    mfe_pct: Optional[float] = None,
    mae_proxy_pct: Optional[float] = None,
    giveback_pct: Optional[float] = None,
) -> None:
    key = str(phase or "UNKNOWN").strip().upper() or "UNKNOWN"
    if key not in ("A", "B", "C"):
        key = "UNKNOWN"
    row = table.setdefault(
        key,
        {
            "n": 0,
            "win_n": 0,
            "loss_n": 0,
            "flat_n": 0,
            "ret_sum_pct": 0.0,
            "pnl_jpy_sum": 0.0,
            "mfe_sum_pct": 0.0,
            "mae_proxy_sum_pct": 0.0,
            "giveback_sum_pct": 0.0,
            "mfe_n": 0,
            "mae_proxy_n": 0,
            "giveback_n": 0,
            "TP": 0,
            "SL": 0,
            "TIMEOUT": 0,
            "OTHER": 0,
            "up_break_n": 0,
            "down_break_n": 0,
            "momentum_n": 0,
        },
    )
    row["n"] = int(row.get("n", 0)) + 1
    row["ret_sum_pct"] = float(row.get("ret_sum_pct", 0.0)) + float(ret_pct)
    row["pnl_jpy_sum"] = float(row.get("pnl_jpy_sum", 0.0)) + float(pnl_jpy or 0.0)
    if mfe_pct is not None:
        row["mfe_sum_pct"] = float(row.get("mfe_sum_pct", 0.0)) + float(mfe_pct)
        row["mfe_n"] = int(row.get("mfe_n", 0)) + 1
    if mae_proxy_pct is not None:
        row["mae_proxy_sum_pct"] = float(row.get("mae_proxy_sum_pct", 0.0)) + float(mae_proxy_pct)
        row["mae_proxy_n"] = int(row.get("mae_proxy_n", 0)) + 1
    if giveback_pct is not None:
        row["giveback_sum_pct"] = float(row.get("giveback_sum_pct", 0.0)) + float(giveback_pct)
        row["giveback_n"] = int(row.get("giveback_n", 0)) + 1
    if float(ret_pct) > 0:
        row["win_n"] = int(row.get("win_n", 0)) + 1
    elif float(ret_pct) < 0:
        row["loss_n"] = int(row.get("loss_n", 0)) + 1
    else:
        row["flat_n"] = int(row.get("flat_n", 0)) + 1
    reason = str(exit_reason or "OTHER").strip().upper()
    if reason not in ("TP", "SL", "TIMEOUT"):
        reason = "OTHER"
    row[reason] = int(row.get(reason, 0)) + 1
    if bool(up_break):
        row["up_break_n"] = int(row.get("up_break_n", 0)) + 1
    if bool(down_break):
        row["down_break_n"] = int(row.get("down_break_n", 0)) + 1
    if str(momentum or "").strip().lower() not in ("", "none", "na"):
        row["momentum_n"] = int(row.get("momentum_n", 0)) + 1


def _finalize_market_phase_outcomes(table: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for label in ("A", "B", "C", "UNKNOWN"):
        row = table.get(label)
        if not isinstance(row, dict):
            continue
        n = int(_safe_int(row.get("n"), 0))
        win_n = int(_safe_int(row.get("win_n"), 0))
        new_row = dict(row)
        new_row["win_rate_pct"] = round((float(win_n) / float(n) * 100.0) if n > 0 else 0.0, 4)
        new_row["avg_ret_pct"] = round((float(_safe_float(row.get("ret_sum_pct")) or 0.0) / float(n)) if n > 0 else 0.0, 6)
        new_row["ret_sum_pct"] = round(float(_safe_float(row.get("ret_sum_pct")) or 0.0), 6)
        new_row["pnl_jpy_sum"] = round(float(_safe_float(row.get("pnl_jpy_sum")) or 0.0), 6)
        mfe_n = int(_safe_int(row.get("mfe_n"), 0))
        mae_n = int(_safe_int(row.get("mae_proxy_n"), 0))
        giveback_n = int(_safe_int(row.get("giveback_n"), 0))
        new_row["mfe_sum_pct"] = round(float(_safe_float(row.get("mfe_sum_pct")) or 0.0), 6)
        new_row["mae_proxy_sum_pct"] = round(float(_safe_float(row.get("mae_proxy_sum_pct")) or 0.0), 6)
        new_row["giveback_sum_pct"] = round(float(_safe_float(row.get("giveback_sum_pct")) or 0.0), 6)
        new_row["avg_mfe_pct"] = round((new_row["mfe_sum_pct"] / float(mfe_n)) if mfe_n > 0 else 0.0, 6)
        new_row["avg_mae_proxy_pct"] = round((new_row["mae_proxy_sum_pct"] / float(mae_n)) if mae_n > 0 else 0.0, 6)
        new_row["avg_giveback_pct"] = round((new_row["giveback_sum_pct"] / float(giveback_n)) if giveback_n > 0 else 0.0, 6)
        out[label] = new_row
    return out


def _format_market_phase_outcomes(daily_review: Dict[str, Any]) -> str:
    table = daily_review.get("market_phase_outcomes") if isinstance(daily_review, dict) else {}
    if not isinstance(table, dict) or not table:
        return "-"
    parts: List[str] = []
    for phase in ("A", "B", "C"):
        row = table.get(phase)
        if not isinstance(row, dict):
            continue
        n = int(_safe_int(row.get("n"), 0))
        if n <= 0:
            continue
        parts.append(
            "{phase}:{n}件 win{win:.0f}% pnl{pnl:+.0f} br{br}".format(
                phase=phase,
                n=n,
                win=float(_safe_float(row.get("win_rate_pct")) or 0.0),
                pnl=float(_safe_float(row.get("pnl_jpy_sum")) or 0.0),
                br=int(_safe_int(row.get("momentum_n"), 0)),
            )
        )
    return " / ".join(parts) if parts else "-"


def _update_counter(table: Dict[str, int], key: str) -> None:
    k = str(key or "").strip() or "UNKNOWN"
    table[k] = int(_safe_int(table.get(k), 0)) + 1


def _format_market_phase_transitions(daily_review: Dict[str, Any]) -> str:
    counts = daily_review.get("market_phase_transition_counts") if isinstance(daily_review, dict) else {}
    if not isinstance(counts, dict) or not counts:
        return "-"
    parts: List[str] = []
    for key, value in sorted(counts.items(), key=lambda item: (-int(_safe_int(item[1], 0)), str(item[0])))[:4]:
        n = int(_safe_int(value, 0))
        if n > 0:
            parts.append(f"{key}:{n}")
    latest = str(daily_review.get("latest_market_phase_transition", "") or "").strip()
    base = " / ".join(parts) if parts else "-"
    return f"{base} / 最新={latest}" if latest else base


def _format_technical_feature_outcomes(daily_review: Dict[str, Any], limit: int = 4) -> str:
    table = daily_review.get("technical_feature_outcomes") if isinstance(daily_review, dict) else {}
    if not isinstance(table, dict) or not table:
        return "-"
    parts: List[str] = []
    for label, row in table.items():
        if len(parts) >= int(limit):
            break
        if not isinstance(row, dict):
            continue
        n = int(_safe_int(row.get("n"), 0))
        if n <= 0:
            continue
        parts.append(
            f"{label}:n{n}/win{float(_safe_float(row.get('win_rate_pct')) or 0.0):.0f}%/"
            f"pnl{float(_safe_float(row.get('pnl_jpy_sum')) or 0.0):+.1f}"
        )
    return " | ".join(parts) if parts else "-"


def _classify_loss_trade_pattern(
    *,
    result: str,
    ret_pct: Optional[float],
    hold_min: Optional[float],
    best_fav_pct: Optional[float],
) -> Tuple[str, str]:
    if ret_pct is None or float(ret_pct) >= 0.0:
        return "", ""
    r = str(result or "").strip().upper()
    hold_v = float(hold_min) if hold_min is not None else None
    best_fav_v = float(best_fav_pct) if best_fav_pct is not None else None

    if r == "PAPER_EXIT_SL" and best_fav_v is not None and best_fav_v >= 0.08:
        return "reversal", "含み益から反転して損切り"
    if r == "PAPER_EXIT_SL" and ((hold_v is not None and hold_v <= 12.0) or hold_v is None) and (best_fav_v is None or best_fav_v <= 0.0):
        return "late_entry", "入ってすぐ逆行して損切り"
    if r in {"PAPER_EXIT_TIMEOUT", "PAPER_EXIT_EOD", "PAPER_EXIT_PRENEWS"}:
        return "weak_follow_through", "伸び切らず時間要因で失速"
    if best_fav_v is not None and best_fav_v > 0.0:
        return "reversal", "一度は利が乗ったが戻された"
    if hold_v is not None and hold_v <= 12.0:
        return "late_entry", "初動の逆行を食いやすい入り方"
    if hold_v is not None and hold_v >= 20.0:
        return "weak_follow_through", "保有しても伸びが続かなかった"
    return "other", "負け方の型はその他"


def _loss_pattern_label_ja(key: Any) -> str:
    mp = {
        "reversal": "反転巻き込み",
        "weak_follow_through": "伸び不足",
        "late_entry": "entry遅れ",
        "other": "その他",
    }
    return mp.get(str(key or "").strip(), "-")


def _opportunity_pattern_label_ja(key: Any) -> str:
    mp = {
        "entry_unfilled": "entry約定失敗",
        "exit_unfilled": "exit取り逃し",
        "news_avoidance": "時間帯回避",
        "time_block": "時間ブロック",
        "spread_block": "spread回避",
    }
    return mp.get(str(key or "").strip(), "-")


def _shift_day8(day8: str, delta_days: int) -> str:
    s = str(day8 or "").strip()
    if not s:
        return ""
    try:
        dt = datetime.strptime(s, "%Y%m%d")
    except Exception:
        return ""
    return (dt + timedelta(days=int(delta_days))).strftime("%Y%m%d")


def _http_get_ok(url: str, timeout_sec: float = 2.0) -> bool:
    req = urllib.request.Request(url=url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            code = int(getattr(resp, "status", 200))
            return 200 <= code < 300
    except Exception:
        return False


def _calc_trade_metrics(
    *,
    side: str,
    entry_price: Optional[float],
    exit_price: Optional[float],
    size: Optional[float],
) -> Dict[str, Optional[float]]:
    if entry_price is None or exit_price is None or entry_price == 0:
        return {
            "ret_pct": None,
            "pnl_per_unit": None,
            "pnl_jpy": None,
        }

    s = str(side or "").strip().upper()
    if s == "SELL":
        pnl_per_unit = float(entry_price) - float(exit_price)
    else:
        pnl_per_unit = float(exit_price) - float(entry_price)
    ret_pct = (pnl_per_unit / float(entry_price)) * 100.0
    pnl_jpy = (pnl_per_unit * float(size)) if (size is not None) else None
    return {
        "ret_pct": float(ret_pct),
        "pnl_per_unit": float(pnl_per_unit),
        "pnl_jpy": (float(pnl_jpy) if pnl_jpy is not None else None),
    }


def _evaluate_trade_quality(result: str, ret_pct: Optional[float]) -> Tuple[str, str]:
    r = str(result or "").strip().upper()
    if ret_pct is not None:
        if ret_pct > 0:
            if r == "PAPER_EXIT_TP":
                return "GOOD", "tp_and_profit"
            return "GOOD", "profit"
        if ret_pct < 0:
            if r == "PAPER_EXIT_SL":
                return "BAD", "sl_and_loss"
            return "BAD", "loss"
        return "NEUTRAL", "flat"

    if r == "PAPER_EXIT_TP":
        return "GOOD", "tp"
    if r == "PAPER_EXIT_SL":
        return "BAD", "sl"
    if r in {"PAPER_EXIT_TIMEOUT", "PAPER_EXIT_EOD", "PAPER_EXIT_PARTIAL_TP", "PAPER_EXIT_PRENEWS"}:
        return "NEUTRAL", "timeout_or_eod"
    return "NEUTRAL", "unknown"


def _evaluate_vs_expectancy(ret_pct: float, expectancy_ref_pct: float) -> Tuple[str, float]:
    delta = float(ret_pct) - float(expectancy_ref_pct)
    band = max(0.02, abs(expectancy_ref_pct) * 0.2)
    if delta > band:
        return "ABOVE", float(delta)
    if delta < -band:
        return "BELOW", float(delta)
    return "NEAR", float(delta)


def _evaluation_label_ja(evaluation: str) -> str:
    ev = str(evaluation or "").strip().upper()
    if ev == "GOOD":
        return "良い取引"
    if ev == "BAD":
        return "悪い取引"
    return "中立"


def _quality_reason_ja(quality_reason: str) -> str:
    qr = str(quality_reason or "").strip().lower()
    mp = {
        "tp_and_profit": "利確で決済し、損益はプラスでした。",
        "sl_and_loss": "損切りで決済し、損益はマイナスでした。",
        "profit": "決済損益はプラスでした。",
        "loss": "決済損益はマイナスでした。",
        "flat": "決済損益はほぼゼロでした。",
        "tp": "利確で決済しました。",
        "sl": "損切りで決済しました。",
        "timeout_or_eod": "時間要因（TIMEOUT/EOD）で決済しました。",
        "unknown": "決済理由の判定ができませんでした。",
    }
    return mp.get(qr, mp["unknown"])


def _expectancy_comment_ja(vs_expectancy: str, exp_delta: float) -> str:
    ve = str(vs_expectancy or "").strip().upper()
    if ve == "ABOVE":
        return f"期待値を {abs(float(exp_delta)):.4f} pt 上回りました。"
    if ve == "BELOW":
        return f"期待値を {abs(float(exp_delta)):.4f} pt 下回りました。"
    return f"期待値付近の結果です（差分 {float(exp_delta):+.4f} pt）。"


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
        if cur != section:
            continue
        if "=" not in line:
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

        # remove inline comments for non-quoted scalars
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
            # HTTP header values must be latin-1 compatible.
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


def _http_get_json(url: str, timeout_sec: int) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        raw = resp.read()
    text = raw.decode("utf-8", errors="replace")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"invalid JSON object from {url}")
    return data


def _http_post_json(url: str, payload: Dict[str, Any], timeout_sec: int) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        raw = resp.read()
    text = raw.decode("utf-8", errors="replace")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"invalid JSON object from {url}")
    return data


def _normalize_base_url(base_url: str) -> str:
    s = str(base_url or "").strip()
    if not s:
        return "http://127.0.0.1:11434"
    return s.rstrip("/")


def _model_size_score(model_name: str) -> float:
    s = str(model_name or "").strip()
    m = MODEL_SIZE_RE.search(s)
    if not m:
        return 9999.0
    try:
        return float(m.group(1))
    except Exception:
        return 9999.0


def _is_ollama_model_match(installed: str, requested: str) -> bool:
    i = str(installed or "").strip()
    r = str(requested or "").strip()
    if not i or not r:
        return False
    if i == r:
        return True
    if i.startswith(r + ":") or r.startswith(i + ":"):
        return True
    return i.split(":", 1)[0] == r.split(":", 1)[0]


def _unique_keep_order(items: List[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _ollama_list_models(base_url: str, timeout_sec: int) -> List[str]:
    data = _http_get_json(f"{_normalize_base_url(base_url)}/api/tags", timeout_sec=timeout_sec)
    models = data.get("models")
    if not isinstance(models, list):
        return []
    out: List[str] = []
    for m in models:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name", "")).strip()
        if name:
            out.append(name)
    return out


def _is_ollama_generate_model(model_name: str) -> bool:
    s = str(model_name or "").strip().lower()
    if not s:
        return False
    blocked = ("embed", "embedding", "nomic-embed", "bge-", "all-minilm")
    return not any(x in s for x in blocked)


def _ollama_attempt_model_order(
    *,
    requested_model: str,
    installed_models: List[str],
    fallback_models: List[str],
    auto_mode: bool,
) -> List[str]:
    requested = str(requested_model or "").strip()
    candidates: List[str] = []
    if requested:
        candidates.append(requested)
    if auto_mode:
        generate_installed = [m for m in installed_models if _is_ollama_generate_model(m)]
        smaller_first = sorted(generate_installed, key=_model_size_score)
        candidates.extend(smaller_first)
        candidates.extend([m for m in fallback_models if _is_ollama_generate_model(m)])
    else:
        candidates.extend([m for m in fallback_models if _is_ollama_generate_model(m)])
    return _unique_keep_order([m for m in candidates if str(m or "").strip()])


def _run_ollama_summary(
    *,
    base_url: str,
    model: str,
    prompt: str,
    timeout_sec: int,
    max_chars: int,
) -> str:
    data = _http_post_json(
        f"{_normalize_base_url(base_url)}/api/generate",
        payload={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 220,
            },
        },
        timeout_sec=timeout_sec,
    )
    text = str(data.get("response", "")).strip()
    if not text:
        raise ValueError("empty response from ollama")
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rstrip() + "..."
    return text


def _latin1_safe_header_value(value: str, fallback: str) -> str:
    s = str(value or "").strip()
    if not s:
        return str(fallback)
    try:
        s.encode("latin-1")
        return s
    except Exception:
        s_ascii = s.encode("ascii", errors="ignore").decode("ascii").strip()
        if s_ascii:
            return s_ascii
        return str(fallback)


def _notify_target_effective(msg: str) -> bool:
    s = str(msg or "").strip().lower()
    return s not in {"disabled", "no_target", "dry_run"}


def _cooldown_remaining_sec(
    cursor: Dict[str, Any],
    event_key: str,
    cooldown_sec: int,
    now_ts: Optional[float] = None,
) -> float:
    cd = max(0, int(cooldown_sec))
    if cd <= 0:
        return 0.0
    if now_ts is None:
        now_ts = time.time()
    d = cursor.get("notify_last_sent_ts")
    if not isinstance(d, dict):
        return 0.0
    last = _safe_float(d.get(str(event_key)))
    if last is None:
        return 0.0
    elapsed = max(0.0, float(now_ts) - float(last))
    rem = float(cd) - elapsed
    return rem if rem > 0 else 0.0


def _cooldown_mark_sent(cursor: Dict[str, Any], event_key: str, now_ts: Optional[float] = None) -> None:
    if now_ts is None:
        now_ts = time.time()
    d = cursor.get("notify_last_sent_ts")
    if not isinstance(d, dict):
        d = {}
        cursor["notify_last_sent_ts"] = d
    d[str(event_key)] = round(float(now_ts), 3)


def _state_change_event_key(base_key: str, now_on: bool) -> str:
    base = str(base_key or "").strip() or "state_changed"
    return f"{base}_{'on' if bool(now_on) else 'off'}"


def _day8(dt: Optional[datetime] = None) -> str:
    base = dt or datetime.now()
    return base.strftime("%Y%m%d")


def _reset_daily_stats(cursor: Dict[str, Any], day8: str) -> None:
    cursor["daily_day8"] = str(day8)
    cursor["daily_ret_pct_sum"] = 0.0
    cursor["daily_pnl_jpy_sum"] = 0.0
    cursor["daily_closed_count"] = 0
    cursor["daily_loss_alerted_day8"] = ""
    cursor["daily_trade_disabled_day8"] = ""
    cursor["daily_goal_report_sent_day8"] = ""
    cursor["daily_goal_report_handled_day8"] = ""
    cursor["loss_streak"] = 0
    cursor["loss_streak_alert_level"] = 0
    cursor["trade_enabled_disabled_reason"] = ""
    cursor["trade_enabled_disabled_at"] = ""
    cursor["trade_enabled_disabled_exec_mode"] = ""
    cursor["trade_enabled_disabled_pos_id"] = ""


def _day8_history_values(value: Any) -> List[str]:
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = str(value or "").replace(";", ",").split(",")
    out: List[str] = []
    for raw in raw_values:
        s = str(raw or "").strip()
        if len(s) == 8 and s.isdigit() and s not in out:
            out.append(s)
    return out


def _daily_goal_report_done_day8s(
    *,
    sent_day8: str = "",
    handled_day8: str = "",
    sent_day8s: Any = None,
) -> List[str]:
    out = _day8_history_values(sent_day8s)
    for day8 in [sent_day8, handled_day8]:
        s = str(day8 or "").strip()
        if len(s) == 8 and s.isdigit() and s not in out:
            out.append(s)
    return out[-14:]


def _mark_daily_goal_report_done(cursor: Dict[str, Any], day8: str, *, sent: bool) -> None:
    s = str(day8 or "").strip()
    if not (len(s) == 8 and s.isdigit()):
        return
    cursor["daily_goal_report_handled_day8"] = s
    if sent:
        cursor["daily_goal_report_sent_day8"] = s
    done = _daily_goal_report_done_day8s(
        sent_day8=str(cursor.get("daily_goal_report_sent_day8", "")),
        handled_day8=str(cursor.get("daily_goal_report_handled_day8", "")),
        sent_day8s=cursor.get("daily_goal_report_sent_day8s"),
    )
    if s not in done:
        done.append(s)
    cursor["daily_goal_report_sent_day8s"] = done[-14:]


def _record_trade_enabled_auto_disabled(
    cursor: Dict[str, Any],
    *,
    day8: str,
    ts: str,
    reason: str,
    payload: Dict[str, Any],
) -> None:
    cursor["daily_trade_disabled_day8"] = str(day8)
    cursor["trade_enabled_disabled_reason"] = str(reason or "").strip()
    cursor["trade_enabled_disabled_at"] = str(ts or "").strip()
    cursor["trade_enabled_disabled_exec_mode"] = str(payload.get("exec_mode", "") or "").strip()
    cursor["trade_enabled_disabled_pos_id"] = str(payload.get("pos_id", "") or "").strip()


def _accumulate_daily_trade_exit(
    cursor: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    now_dt: Optional[datetime] = None,
) -> Dict[str, Any]:
    base_dt = _parse_time(payload.get("time")) or now_dt or datetime.now()
    day8 = _day8(base_dt)
    if str(cursor.get("daily_day8", "")).strip() != day8:
        _reset_daily_stats(cursor, day8)

    daily_ret_pct_sum = float(_safe_float(cursor.get("daily_ret_pct_sum")) or 0.0)
    daily_pnl_jpy_sum = float(_safe_float(cursor.get("daily_pnl_jpy_sum")) or 0.0)
    daily_closed_count = max(0, _safe_int(cursor.get("daily_closed_count"), 0)) + 1

    ret_pct = _safe_float(payload.get("ret_pct"))
    pnl_jpy = _safe_float(payload.get("pnl_jpy"))

    if ret_pct is not None:
        daily_ret_pct_sum += float(ret_pct)
    if pnl_jpy is not None:
        daily_pnl_jpy_sum += float(pnl_jpy)

    cursor["daily_ret_pct_sum"] = round(float(daily_ret_pct_sum), 6)
    cursor["daily_pnl_jpy_sum"] = round(float(daily_pnl_jpy_sum), 6)
    cursor["daily_closed_count"] = int(daily_closed_count)

    return {
        "day8": day8,
        "ret_pct": ret_pct,
        "pnl_jpy": pnl_jpy,
        "daily_ret_pct_sum": float(cursor["daily_ret_pct_sum"]),
        "daily_pnl_jpy_sum": float(cursor["daily_pnl_jpy_sum"]),
        "daily_closed_count": int(cursor["daily_closed_count"]),
    }


def _current_daily_snapshot(cursor: Dict[str, Any], *, now_dt: Optional[datetime] = None) -> Dict[str, Any]:
    today8 = _day8(now_dt or datetime.now())
    cursor_day8 = str(cursor.get("daily_day8", "")).strip()
    if cursor_day8 != today8:
        return {
            "day8": today8,
            "daily_ret_pct_sum": 0.0,
            "daily_pnl_jpy_sum": 0.0,
            "daily_closed_count": 0,
        }
    return {
        "day8": today8,
        "daily_ret_pct_sum": float(_safe_float(cursor.get("daily_ret_pct_sum")) or 0.0),
        "daily_pnl_jpy_sum": float(_safe_float(cursor.get("daily_pnl_jpy_sum")) or 0.0),
        "daily_closed_count": max(0, _safe_int(cursor.get("daily_closed_count"), 0)),
    }


def _read_control_values(control_path: Path) -> Dict[str, str]:
    if not control_path.exists():
        return {}
    out: Dict[str, str] = {}
    try:
        with control_path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.reader(f):
                if not row:
                    continue
                key = str(row[0]).strip()
                if not key or key.startswith("#"):
                    continue
                out[key] = str(row[1]).strip() if len(row) >= 2 else ""
    except Exception:
        return {}
    return out


def _hours_csv_to_list(v: Any) -> List[int]:
    vals: List[int] = []
    for part in str(v or "").split(","):
        s = part.strip()
        if not s:
            continue
        iv = _safe_int(s, -1)
        if 0 <= iv <= 23:
            vals.append(int(iv))
    return sorted(set(vals))


def _merge_hours_csv(existing_csv: Any, add_hours: List[int], limit: int = 8) -> str:
    merged = _hours_csv_to_list(existing_csv)
    for h in add_hours:
        iv = _safe_int(h, -1)
        if 0 <= iv <= 23 and iv not in merged:
            merged.append(iv)
    merged = sorted(set(merged))
    return ",".join(str(x) for x in merged[: max(1, int(limit))])


def _build_daily_goal_report(
    *,
    report_dt: datetime,
    host: str,
    day8: str,
    goal_jpy: float,
    daily_pnl_jpy_sum: float,
    daily_ret_pct_sum: float,
    daily_closed_count: int,
    close_reason: str = "runner_off",
) -> Tuple[str, str, Dict[str, Any]]:
    reason_map = {
        "runner_off": "runner_alive OFF",
        "out_of_time": "trade_time 終了（SKIP_OUT_OF_TIME）",
        "day_rollover": "日付跨ぎ補完",
        "scheduled_close": "21時定時締め",
    }
    reason_label = reason_map.get(str(close_reason or "").strip(), str(close_reason or "runner_off"))
    achieved = float(daily_pnl_jpy_sum) >= float(goal_jpy)
    status_label = "達成" if achieved else "未達"
    delta_jpy = float(daily_pnl_jpy_sum) - float(goal_jpy)
    ascii_status_label = "ACHIEVED" if achieved else "MISSED"
    japanese_title = f"Ouroboros 終業レポート [{status_label}]"
    title = f"Ouroboros Daily Report [{ascii_status_label}]"
    text = (
        f"{japanese_title}\n"
        f"時刻={report_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"日付={day8}\n"
        f"終業判定={reason_label}\n"
        f"ホスト={host}\n\n"
        "【目標】\n"
        f"1日目標(JPY)={float(goal_jpy):.2f}\n"
        f"当日実現損益(JPY)={float(daily_pnl_jpy_sum):.2f}\n"
        f"目標差額(JPY)={float(delta_jpy):+.2f}\n"
        f"目標判定={status_label}\n"
        f"決済件数={int(daily_closed_count)}\n"
        f"当日累積損益率(%)={float(daily_ret_pct_sum):.4f}"
    )
    payload = {
        "event": "daily_goal_report",
        "notification_title": title,
        "notification_title_ja": japanese_title,
        "time": report_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "day8": str(day8),
        "goal_jpy": float(goal_jpy),
        "daily_pnl_jpy_sum": float(daily_pnl_jpy_sum),
        "goal_delta_jpy": float(delta_jpy),
        "goal_achieved": bool(achieved),
        "daily_ret_pct_sum": float(daily_ret_pct_sum),
        "daily_closed_count": int(daily_closed_count),
        "close_reason": str(close_reason),
        "host": host,
    }
    return title, text, payload


def _shadow_logs_dir(logs_dir: Optional[Path]) -> Optional[Path]:
    if not logs_dir:
        return None
    try:
        return Path(logs_dir) / "instances" / "shadow"
    except Exception:
        return None


def _build_shadow_day_snapshot(logs_dir: Optional[Path], day8: str) -> Dict[str, Any]:
    out = {
        "available": False,
        "day8": str(day8),
        "closed_n": 0,
        "active_row_n": 0,
        "win_n": 0,
        "loss_n": 0,
        "win_rate_pct": 0.0,
        "pnl_jpy_sum": 0.0,
        "exit_technical_n": 0,
        "weak_progress_exit_n": 0,
        "progress_reversal_exit_n": 0,
        "near_tp_giveback_exit_n": 0,
        "progress_timeout_n": 0,
        "no_follow_through_exit_n": 0,
        "timeout_raw_n": 0,
        "plain_timeout_n": 0,
        "timeout_n": 0,
        "observe_trend_strength_weak_n": 0,
        "observe_ai_block_htf60_countertrend_n": 0,
        "observe_ai_block_htf15_60_conflict_n": 0,
        "last_time": "",
        "last_result": "",
    }
    shadow_logs = _shadow_logs_dir(logs_dir)
    if not shadow_logs or not shadow_logs.exists():
        return out
    review = _build_daily_trade_review(shadow_logs, day8)
    closed_n = max(0, _safe_int(review.get("closed_n"), 0))
    active_row_n = max(0, _safe_int(review.get("active_row_n"), 0))
    weak_progress_n = max(0, _safe_int(review.get("weak_progress_exit_n"), 0))
    progress_reversal_n = max(0, _safe_int(review.get("progress_reversal_exit_n"), 0))
    near_tp_giveback_n = max(0, _safe_int(review.get("near_tp_giveback_exit_n"), 0))
    progress_timeout_n = max(0, _safe_int(review.get("progress_timeout_n"), 0))
    no_follow_through_n = max(0, _safe_int(review.get("no_follow_through_exit_n"), 0))
    timeout_raw_n = max(0, _safe_int((review.get("exit_reason_breakdown") or {}).get("TIMEOUT"), 0))
    plain_timeout_n = max(
        0,
        timeout_raw_n - weak_progress_n - progress_reversal_n - near_tp_giveback_n - progress_timeout_n - no_follow_through_n,
    )
    return {
        **out,
        "available": bool(closed_n > 0 or active_row_n > 0 or review.get("has_runtime_activity")),
        "closed_n": closed_n,
        "active_row_n": active_row_n,
        "win_n": max(0, _safe_int(review.get("win_n"), 0)),
        "loss_n": max(0, _safe_int(review.get("loss_n"), 0)),
        "win_rate_pct": float(_safe_float(review.get("win_rate_pct")) or 0.0),
        "pnl_jpy_sum": float(_safe_float(review.get("pnl_jpy_sum")) or 0.0),
        "exit_technical_n": max(0, _safe_int(review.get("exit_technical_n"), 0)),
        "weak_progress_exit_n": weak_progress_n,
        "progress_reversal_exit_n": progress_reversal_n,
        "near_tp_giveback_exit_n": near_tp_giveback_n,
        "progress_timeout_n": progress_timeout_n,
        "no_follow_through_exit_n": no_follow_through_n,
        "timeout_raw_n": timeout_raw_n,
        "plain_timeout_n": plain_timeout_n,
        "timeout_n": plain_timeout_n,
        "observe_trend_strength_weak_n": max(0, _safe_int(review.get("observe_trend_strength_weak_n"), 0)),
        "observe_ai_block_htf60_countertrend_n": max(0, _safe_int(review.get("observe_ai_block_htf60_countertrend_n"), 0)),
        "observe_ai_block_htf15_60_conflict_n": max(0, _safe_int(review.get("observe_ai_block_htf15_60_conflict_n"), 0)),
        "last_time": str(review.get("last_time", "") or ""),
        "last_result": str(review.get("last_result", "") or ""),
    }


def _build_daily_trade_review(logs_dir: Path, day8: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "day8": str(day8),
        "log_path": str(logs_dir / f"trade_log_{day8}.csv"),
        "row_n": 0,
        "active_row_n": 0,
        "skip_out_of_time_n": 0,
        "skip_news_n": 0,
        "skip_spread_n": 0,
        "observe_time_block_n": 0,
        "observe_ai_block_n": 0,
        "observe_ai_block_htf60_countertrend_n": 0,
        "observe_ai_block_htf15_60_conflict_n": 0,
        "observe_buy_fast_ma_near_n": 0,
        "observe_sell_fast_ma_near_n": 0,
        "observe_trend_flip_cooldown_n": 0,
        "observe_trend_strength_weak_n": 0,
        "entry_unfilled_n": 0,
        "exit_unfilled_n": 0,
        "last_time": "",
        "last_result": "",
        "has_runtime_activity": False,
        "ended_out_of_time": False,
        "closed_n": 0,
        "win_n": 0,
        "loss_n": 0,
        "flat_n": 0,
        "win_rate_pct": 0.0,
        "ret_sum_pct": 0.0,
        "avg_ret_pct": 0.0,
        "pnl_jpy_sum": 0.0,
        "mfe_sum_pct": 0.0,
        "mae_proxy_sum_pct": 0.0,
        "giveback_sum_pct": 0.0,
        "avg_mfe_pct": 0.0,
        "avg_mae_proxy_pct": 0.0,
        "avg_giveback_pct": 0.0,
        "mfe_n": 0,
        "mae_proxy_n": 0,
        "giveback_n": 0,
        "progress_reached_n": 0,
        "exit_technical_n": 0,
        "weak_progress_exit_n": 0,
        "progress_reversal_exit_n": 0,
        "near_tp_giveback_exit_n": 0,
        "progress_timeout_n": 0,
        "no_follow_through_exit_n": 0,
        "gross_profit_jpy": 0.0,
        "gross_loss_jpy": 0.0,
        "profit_factor_jpy": 0.0,
        "exit_reason_breakdown": {
            "TP": 0,
            "SL": 0,
            "TIMEOUT": 0,
            "PARTIAL_TP": 0,
            "EOD": 0,
            "PRENEWS": 0,
            "OTHER": 0,
        },
        "loss_pattern_breakdown": {
            "reversal": 0,
            "weak_follow_through": 0,
            "late_entry": 0,
            "other": 0,
        },
        "opportunity_pattern_breakdown": {
            "entry_unfilled": 0,
            "exit_unfilled": 0,
            "news_avoidance": 0,
            "time_block": 0,
            "spread_block": 0,
        },
        "technical_feature_outcomes": {},
        "market_phase_outcomes": {},
        "market_phase_transition_counts": {},
        "market_phase_transition_n": 0,
        "latest_market_phase_transition": "",
        "latest_market_phase_transition_time": "",
        "observe_phase_b_n": 0,
        "good_hours": [],
        "bad_hours": [],
        "best_trade": {},
        "worst_trade": {},
    }
    log_path = logs_dir / f"trade_log_{day8}.csv"
    if not log_path.exists():
        return out

    rows = _read_csv_rows(log_path)
    last_dt: Optional[datetime] = None
    entry_by_pos: Dict[str, Dict[str, Any]] = {}
    exit_by_pos: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        dt = _parse_time(row.get("time"))
        result = str(row.get("result", "")).strip()
        if result:
            out["row_n"] = int(out["row_n"]) + 1
            if result == "SKIP_OUT_OF_TIME":
                out["skip_out_of_time_n"] = int(out["skip_out_of_time_n"]) + 1
            else:
                out["active_row_n"] = int(out["active_row_n"]) + 1
            note_text = str(row.get("note", "") or "")
            row_note_kv = _parse_note_kv(note_text)
            phase_transition = str(row_note_kv.get("phase_transition", "") or "").strip()
            if phase_transition:
                counts = out.get("market_phase_transition_counts")
                if isinstance(counts, dict):
                    _update_counter(counts, phase_transition)
                out["market_phase_transition_n"] = int(out["market_phase_transition_n"]) + 1
                if dt is not None:
                    latest_transition_dt = _parse_time(str(out.get("latest_market_phase_transition_time", "")))
                    if latest_transition_dt is None or dt >= latest_transition_dt:
                        out["latest_market_phase_transition"] = phase_transition
                        out["latest_market_phase_transition_time"] = dt.strftime("%Y-%m-%d %H:%M:%S")
            if result == "SKIP_NEWS":
                out["skip_news_n"] = int(out["skip_news_n"]) + 1
            elif result == "SKIP_SPREAD":
                out["skip_spread_n"] = int(out["skip_spread_n"]) + 1
            elif result == "OBSERVE_TIME_BLOCK":
                out["observe_time_block_n"] = int(out["observe_time_block_n"]) + 1
            elif result == "OBSERVE_AI_BLOCK":
                out["observe_ai_block_n"] = int(out["observe_ai_block_n"]) + 1
                if "htf60_countertrend=1" in note_text:
                    out["observe_ai_block_htf60_countertrend_n"] = int(out["observe_ai_block_htf60_countertrend_n"]) + 1
                if "htf15_60_conflict=1" in note_text:
                    out["observe_ai_block_htf15_60_conflict_n"] = int(out["observe_ai_block_htf15_60_conflict_n"]) + 1
            elif result == "OBSERVE_BUY_FAST_MA_NEAR":
                out["observe_buy_fast_ma_near_n"] = int(out["observe_buy_fast_ma_near_n"]) + 1
            elif result == "OBSERVE_SELL_FAST_MA_NEAR":
                out["observe_sell_fast_ma_near_n"] = int(out["observe_sell_fast_ma_near_n"]) + 1
            elif result == "OBSERVE_TREND_FLIP_COOLDOWN":
                out["observe_trend_flip_cooldown_n"] = int(out["observe_trend_flip_cooldown_n"]) + 1
            elif result == "OBSERVE_TREND_STRENGTH_WEAK":
                out["observe_trend_strength_weak_n"] = int(out["observe_trend_strength_weak_n"]) + 1
            elif result == "OBSERVE_PHASE_B":
                out["observe_phase_b_n"] = int(out["observe_phase_b_n"]) + 1
            if "entry_unfilled" in note_text:
                out["entry_unfilled_n"] = int(out["entry_unfilled_n"]) + 1
            if "exit_unfilled" in note_text:
                out["exit_unfilled_n"] = int(out["exit_unfilled_n"]) + 1
        if dt is not None and (last_dt is None or dt >= last_dt):
            last_dt = dt
            out["last_time"] = dt.strftime("%Y-%m-%d %H:%M:%S")
            out["last_result"] = result

        pos_id = str(row.get("pos_id", "")).strip()
        if not pos_id:
            continue
        if dt is None:
            continue
        if result == "PAPER":
            prev = entry_by_pos.get(pos_id)
            if prev is None or dt < prev["dt"]:
                entry_by_pos[pos_id] = {
                    "dt": dt,
                    "side": str(row.get("side", "")).strip().upper(),
                    "entry_price": _safe_float(row.get("price")),
                    "size": _safe_float(row.get("size")),
                    "note": str(row.get("note", "") or ""),
                }
        elif result.startswith("PAPER_EXIT_"):
            prev = exit_by_pos.get(pos_id)
            if prev is None or dt >= prev["dt"]:
                exit_by_pos[pos_id] = {
                    "dt": dt,
                    "result": result,
                    "exit_price": _safe_float(row.get("ltp")),
                    "note": str(row.get("note", "") or ""),
                }

    hour_stats: Dict[int, Dict[str, float]] = {}
    best_trade: Optional[Dict[str, Any]] = None
    worst_trade: Optional[Dict[str, Any]] = None
    for pos_id in sorted(set(entry_by_pos.keys()) & set(exit_by_pos.keys())):
        entry = entry_by_pos.get(pos_id) or {}
        exit_row = exit_by_pos.get(pos_id) or {}
        side = str(entry.get("side", "")).strip().upper()
        metrics = _calc_trade_metrics(
            side=side,
            entry_price=_safe_float(entry.get("entry_price")),
            exit_price=_safe_float(exit_row.get("exit_price")),
            size=_safe_float(entry.get("size")),
        )
        ret_pct = _safe_float(metrics.get("ret_pct"))
        pnl_jpy = _safe_float(metrics.get("pnl_jpy"))
        if ret_pct is None:
            continue

        entry_dt = entry.get("dt")
        exit_dt = exit_row.get("dt")
        hold_min: Optional[float] = None
        if isinstance(entry_dt, datetime) and isinstance(exit_dt, datetime):
            hold_min = max(0.0, float((exit_dt - entry_dt).total_seconds()) / 60.0)
        note_kv = _parse_note_kv(exit_row.get("note", ""))
        entry_note_kv = _parse_note_kv(entry.get("note", ""))
        best_fav_pct = _safe_float(note_kv.get("best_fav"))
        max_adv_pct = _safe_float(note_kv.get("max_adv"))
        current_fav_pct = _safe_float(note_kv.get("current_fav"))
        mfe_pct = max(0.0, float(best_fav_pct)) if best_fav_pct is not None else max(0.0, float(ret_pct))
        mae_proxy_pct = max(0.0, float(max_adv_pct)) if max_adv_pct is not None else max(0.0, -float(ret_pct))
        end_fav_pct = float(current_fav_pct) if current_fav_pct is not None else float(ret_pct)
        giveback_pct = max(0.0, float(mfe_pct) - float(end_fav_pct))

        out["closed_n"] = int(out["closed_n"]) + 1
        out["ret_sum_pct"] = float(out["ret_sum_pct"]) + float(ret_pct)
        if pnl_jpy is not None:
            out["pnl_jpy_sum"] = float(out["pnl_jpy_sum"]) + float(pnl_jpy)
            if pnl_jpy > 0:
                out["gross_profit_jpy"] = float(out["gross_profit_jpy"]) + float(pnl_jpy)
            elif pnl_jpy < 0:
                out["gross_loss_jpy"] = float(out["gross_loss_jpy"]) + float(pnl_jpy)
        out["mfe_sum_pct"] = float(out["mfe_sum_pct"]) + float(mfe_pct)
        out["mae_proxy_sum_pct"] = float(out["mae_proxy_sum_pct"]) + float(mae_proxy_pct)
        out["giveback_sum_pct"] = float(out["giveback_sum_pct"]) + float(giveback_pct)
        out["mfe_n"] = int(out["mfe_n"]) + 1
        out["mae_proxy_n"] = int(out["mae_proxy_n"]) + 1
        out["giveback_n"] = int(out["giveback_n"]) + 1
        if float(mfe_pct) >= 0.08:
            out["progress_reached_n"] = int(out["progress_reached_n"]) + 1

        if ret_pct > 0:
            out["win_n"] = int(out["win_n"]) + 1
        elif ret_pct < 0:
            out["loss_n"] = int(out["loss_n"]) + 1
        else:
            out["flat_n"] = int(out["flat_n"]) + 1

        reason = str(exit_row.get("result", "")).replace("PAPER_EXIT_", "", 1)
        if reason not in out["exit_reason_breakdown"]:
            reason = "OTHER"
        out["exit_reason_breakdown"][reason] = int(out["exit_reason_breakdown"][reason]) + 1
        feature_table = out.get("technical_feature_outcomes")
        if isinstance(feature_table, dict):
            for label in _technical_feature_labels_from_note(entry.get("note", "")):
                _update_technical_feature_outcome(
                    feature_table,
                    label,
                    exit_reason=reason,
                    ret_pct=float(ret_pct),
                    pnl_jpy=pnl_jpy,
                    mfe_pct=mfe_pct,
                    mae_proxy_pct=mae_proxy_pct,
                    giveback_pct=giveback_pct,
                )
        phase_table = out.get("market_phase_outcomes")
        if isinstance(phase_table, dict):
            _update_market_phase_outcome(
                phase_table,
                str(entry_note_kv.get("phase", "UNKNOWN")),
                exit_reason=reason,
                ret_pct=float(ret_pct),
                pnl_jpy=pnl_jpy,
                up_break=str(entry_note_kv.get("up_break", "")).strip() == "1",
                down_break=str(entry_note_kv.get("down_break", "")).strip() == "1",
                momentum=str(entry_note_kv.get("phase_momentum", "")),
                mfe_pct=mfe_pct,
                mae_proxy_pct=mae_proxy_pct,
                giveback_pct=giveback_pct,
            )
        note_text = str(exit_row.get("note", "") or "")
        if "exit_tech=" in note_text:
            out["exit_technical_n"] = int(out["exit_technical_n"]) + 1
        is_weak_progress = "exit_tech=WEAK_PROGRESS" in note_text
        is_progress_reversal = "exit_tech=PROGRESS_REVERSAL" in note_text
        is_near_tp_giveback = "exit_tech=NEAR_TP_GIVEBACK" in note_text
        is_no_follow_through = "exit_tech=NO_FOLLOW_THROUGH" in note_text
        if is_weak_progress:
            out["weak_progress_exit_n"] = int(out["weak_progress_exit_n"]) + 1
        if is_progress_reversal:
            out["progress_reversal_exit_n"] = int(out["progress_reversal_exit_n"]) + 1
        if is_near_tp_giveback:
            out["near_tp_giveback_exit_n"] = int(out["near_tp_giveback_exit_n"]) + 1
        if is_no_follow_through:
            out["no_follow_through_exit_n"] = int(out["no_follow_through_exit_n"]) + 1
        if (
            reason == "TIMEOUT"
            and (not is_weak_progress)
            and (not is_progress_reversal)
            and (not is_near_tp_giveback)
            and (not is_no_follow_through)
            and best_fav_pct is not None
            and float(best_fav_pct) >= 0.08
        ):
            out["progress_timeout_n"] = int(out["progress_timeout_n"]) + 1

        if isinstance(exit_dt, datetime):
            hour = int(exit_dt.hour)
            hs = hour_stats.setdefault(hour, {"closed_n": 0.0, "ret_sum_pct": 0.0, "pnl_jpy_sum": 0.0})
            hs["closed_n"] += 1.0
            hs["ret_sum_pct"] += float(ret_pct)
            hs["pnl_jpy_sum"] += float(pnl_jpy or 0.0)

        loss_pattern_key, loss_pattern_reason = _classify_loss_trade_pattern(
            result=str(exit_row.get("result", "")),
            ret_pct=ret_pct,
            hold_min=hold_min,
            best_fav_pct=best_fav_pct,
        )
        if loss_pattern_key in out["loss_pattern_breakdown"]:
            out["loss_pattern_breakdown"][loss_pattern_key] = int(out["loss_pattern_breakdown"][loss_pattern_key]) + 1

        trade_summary = {
            "pos_id": pos_id,
            "ret_pct": float(ret_pct),
            "pnl_jpy": float(pnl_jpy or 0.0),
            "result": str(exit_row.get("result", "")),
            "hold_min": round(float(hold_min), 2) if hold_min is not None else None,
            "best_fav_pct": (round(float(best_fav_pct), 6) if best_fav_pct is not None else None),
            "mfe_pct": round(float(mfe_pct), 6),
            "mae_proxy_pct": round(float(mae_proxy_pct), 6),
            "giveback_pct": round(float(giveback_pct), 6),
            "loss_pattern_key": loss_pattern_key,
            "loss_pattern_label_ja": _loss_pattern_label_ja(loss_pattern_key) if loss_pattern_key else "",
            "loss_pattern_reason": loss_pattern_reason,
        }
        if best_trade is None or float(trade_summary["pnl_jpy"]) > float(best_trade.get("pnl_jpy", 0.0)):
            best_trade = dict(trade_summary)
        if worst_trade is None or float(trade_summary["pnl_jpy"]) < float(worst_trade.get("pnl_jpy", 0.0)):
            worst_trade = dict(trade_summary)

    closed_n = int(out["closed_n"])
    if closed_n > 0:
        out["win_rate_pct"] = round(float(out["win_n"]) / float(closed_n) * 100.0, 4)
        out["avg_ret_pct"] = round(float(out["ret_sum_pct"]) / float(closed_n), 6)
    out["ret_sum_pct"] = round(float(out["ret_sum_pct"]), 6)
    out["pnl_jpy_sum"] = round(float(out["pnl_jpy_sum"]), 6)
    out["mfe_sum_pct"] = round(float(out["mfe_sum_pct"]), 6)
    out["mae_proxy_sum_pct"] = round(float(out["mae_proxy_sum_pct"]), 6)
    out["giveback_sum_pct"] = round(float(out["giveback_sum_pct"]), 6)
    out["avg_mfe_pct"] = round(float(out["mfe_sum_pct"]) / float(max(1, int(out["mfe_n"]))), 6) if int(out["mfe_n"]) > 0 else 0.0
    out["avg_mae_proxy_pct"] = (
        round(float(out["mae_proxy_sum_pct"]) / float(max(1, int(out["mae_proxy_n"]))), 6) if int(out["mae_proxy_n"]) > 0 else 0.0
    )
    out["avg_giveback_pct"] = (
        round(float(out["giveback_sum_pct"]) / float(max(1, int(out["giveback_n"]))), 6) if int(out["giveback_n"]) > 0 else 0.0
    )
    out["gross_profit_jpy"] = round(float(out["gross_profit_jpy"]), 6)
    out["gross_loss_jpy"] = round(float(out["gross_loss_jpy"]), 6)
    abs_loss = abs(float(out["gross_loss_jpy"]))
    out["profit_factor_jpy"] = round(
        (float(out["gross_profit_jpy"]) / abs_loss) if abs_loss > 0 else (8.0 if float(out["gross_profit_jpy"]) > 0 else 0.0),
        6,
    )
    out["best_trade"] = best_trade or {}
    out["worst_trade"] = worst_trade or {}
    feature_table = out.get("technical_feature_outcomes")
    out["technical_feature_outcomes"] = (
        _finalize_technical_feature_outcomes(feature_table) if isinstance(feature_table, dict) else {}
    )
    phase_table = out.get("market_phase_outcomes")
    out["market_phase_outcomes"] = (
        _finalize_market_phase_outcomes(phase_table) if isinstance(phase_table, dict) else {}
    )
    loss_pattern_breakdown = out.get("loss_pattern_breakdown") or {}
    dominant_key = ""
    dominant_n = 0
    if isinstance(loss_pattern_breakdown, dict):
        for key, value in dict(loss_pattern_breakdown).items():
            n = int(_safe_int(value, 0))
            if n > dominant_n:
                dominant_key = str(key)
                dominant_n = n
    out["dominant_loss_pattern_key"] = dominant_key
    out["dominant_loss_pattern_label_ja"] = _loss_pattern_label_ja(dominant_key) if dominant_key else ""
    opportunity_pattern_breakdown = out.get("opportunity_pattern_breakdown") or {}
    if isinstance(opportunity_pattern_breakdown, dict):
        opportunity_pattern_breakdown["entry_unfilled"] = int(out.get("entry_unfilled_n", 0))
        opportunity_pattern_breakdown["exit_unfilled"] = int(out.get("exit_unfilled_n", 0))
        opportunity_pattern_breakdown["news_avoidance"] = int(out.get("skip_news_n", 0)) + int(_safe_int((out.get("exit_reason_breakdown") or {}).get("PRENEWS"), 0))
        opportunity_pattern_breakdown["time_block"] = int(out.get("observe_time_block_n", 0))
        opportunity_pattern_breakdown["spread_block"] = int(out.get("skip_spread_n", 0))
    dominant_opp_key = ""
    dominant_opp_n = 0
    if isinstance(opportunity_pattern_breakdown, dict):
        for key, value in dict(opportunity_pattern_breakdown).items():
            n = int(_safe_int(value, 0))
            if n > dominant_opp_n:
                dominant_opp_key = str(key)
                dominant_opp_n = n
    out["dominant_opportunity_pattern_key"] = dominant_opp_key
    out["dominant_opportunity_pattern_label_ja"] = _opportunity_pattern_label_ja(dominant_opp_key) if dominant_opp_key else ""

    hour_rank: List[Tuple[int, float, float, float]] = []
    for h, hs in hour_stats.items():
        n = int(hs["closed_n"])
        if n <= 0:
            continue
        avg_ret_pct = float(hs["ret_sum_pct"]) / float(n)
        avg_pnl_jpy = float(hs["pnl_jpy_sum"]) / float(n)
        hour_rank.append((int(h), avg_ret_pct, avg_pnl_jpy, float(n)))
    hour_rank.sort(key=lambda x: (x[1], x[2], x[3]), reverse=True)
    out["good_hours"] = [int(x[0]) for x in hour_rank[:2] if float(x[1]) > 0 or float(x[2]) > 0]
    hour_rank.sort(key=lambda x: (x[1], x[2], -x[3]))
    out["bad_hours"] = [int(x[0]) for x in hour_rank[:2] if float(x[1]) < 0 or float(x[2]) < 0]
    out["has_runtime_activity"] = int(out["active_row_n"]) > 0
    out["ended_out_of_time"] = bool(out["has_runtime_activity"]) and str(out.get("last_result", "")) == "SKIP_OUT_OF_TIME"
    return out


def _resolve_snapshot_logs_dir(snapshot_dir: Optional[Path]) -> Optional[Path]:
    if snapshot_dir is None:
        return None
    base = Path(snapshot_dir).expanduser()
    if (base / "logs").exists():
        return base / "logs"
    if base.exists():
        return base
    return None


def _snapshot_freshness(
    *,
    snapshot_dir: Optional[Path],
    logs_dir: Path,
    now_dt: Optional[datetime] = None,
    stale_after_min: int = 240,
) -> Dict[str, Any]:
    base = Path(snapshot_dir).expanduser() if snapshot_dir is not None else Path(logs_dir)
    try:
        resolved = base.resolve()
    except Exception:
        resolved = base
    if resolved.name == "logs":
        root = resolved.parent
    elif (resolved / "logs").exists():
        root = resolved
    else:
        root = Path(logs_dir).parent
    name = root.name
    out: Dict[str, Any] = {
        "report_snapshot_name": name,
        "report_snapshot_age_min": None,
        "report_snapshot_freshness": "UNKNOWN",
    }
    m = re.match(r"^(\d{8})_(\d{6})$", name)
    if not m:
        return out
    try:
        snap_dt = datetime.strptime(f"{m.group(1)}{m.group(2)}", "%Y%m%d%H%M%S")
    except Exception:
        return out
    now = now_dt or datetime.now()
    age_min = int(max(0, (now - snap_dt).total_seconds() // 60))
    out["report_snapshot_age_min"] = age_min
    out["report_snapshot_freshness"] = "OK" if age_min <= int(stale_after_min) else "STALE"
    return out


def _stamp_daily_review_source(
    review: Dict[str, Any],
    *,
    logs_dir: Path,
    source: str,
    reason: str,
    snapshot_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    out = dict(review)
    out["report_log_source"] = str(source)
    out["report_logs_dir"] = str(logs_dir)
    out["report_log_source_reason"] = str(reason)
    if str(source) == "vm_snapshot":
        out.update(_snapshot_freshness(snapshot_dir=snapshot_dir, logs_dir=logs_dir))
    return out


def _build_daily_trade_review_with_snapshot_fallback(
    *,
    primary_logs_dir: Path,
    day8: str,
    snapshot_dir: Optional[Path] = None,
    enabled: bool = True,
) -> Tuple[Dict[str, Any], Path]:
    primary_dir = Path(primary_logs_dir)
    primary = _build_daily_trade_review(primary_dir, day8)
    if not bool(enabled):
        return _stamp_daily_review_source(
            primary,
            logs_dir=primary_dir,
            source="primary",
            reason="snapshot_fallback_disabled",
            snapshot_dir=snapshot_dir,
        ), primary_dir

    snapshot_logs_dir = _resolve_snapshot_logs_dir(snapshot_dir)
    if snapshot_logs_dir is None:
        return _stamp_daily_review_source(
            primary,
            logs_dir=primary_dir,
            source="primary",
            reason="snapshot_missing",
            snapshot_dir=snapshot_dir,
        ), primary_dir

    snapshot = _build_daily_trade_review(snapshot_logs_dir, day8)
    primary_score = int(_safe_int(primary.get("row_n"), 0)) + int(_safe_int(primary.get("closed_n"), 0)) * 10
    snapshot_score = int(_safe_int(snapshot.get("row_n"), 0)) + int(_safe_int(snapshot.get("closed_n"), 0)) * 10
    if snapshot_score > primary_score:
        return _stamp_daily_review_source(
            snapshot,
            logs_dir=snapshot_logs_dir,
            source="vm_snapshot",
            reason=f"snapshot_score>{primary_score}",
            snapshot_dir=snapshot_dir,
        ), snapshot_logs_dir

    return _stamp_daily_review_source(
        primary,
        logs_dir=primary_dir,
        source="primary",
        reason=f"primary_score>={snapshot_score}",
        snapshot_dir=snapshot_dir,
    ), primary_dir


def _pick_daily_goal_report_day(
    *,
    today8: str,
    sent_day8: str,
    handled_day8: str,
    sent_day8s: Any = None,
    now_hour: int,
    report_hour: int,
    runner_now: bool,
    runner_seen_day8: str,
    cursor_day8: str,
    current_day_review: Dict[str, Any],
    cursor_day_review: Dict[str, Any],
) -> Tuple[str, str]:
    done_day8s = set(
        _daily_goal_report_done_day8s(
            sent_day8=sent_day8,
            handled_day8=handled_day8,
            sent_day8s=sent_day8s,
        )
    )
    if cursor_day8 and cursor_day8 != today8 and cursor_day8 not in done_day8s:
        if bool(cursor_day_review.get("has_runtime_activity")) or _safe_int(cursor_day_review.get("closed_n"), 0) > 0:
            return cursor_day8, "day_rollover"
    if today8 in done_day8s:
        return "", ""
    if max(0, min(23, int(_safe_int(now_hour, 0)))) >= max(0, min(23, int(_safe_int(report_hour, 21)))):
        return today8, "scheduled_close"
    return "", ""


def _csv_token_list(v: Any) -> List[str]:
    out: List[str] = []
    for token in str(v or "").split(","):
        s = token.strip()
        if s and s not in out:
            out.append(s)
    return out


def _sample_confidence_rank(v: Any) -> int:
    s = str(v or "").strip().lower()
    if s == "high":
        return 3
    if s == "medium":
        return 2
    if s == "low":
        return 1
    return 0


def _evaluate_daily_reflection_auto_apply(
    *,
    reflection: Dict[str, Any],
    sec: Dict[str, Any],
) -> Dict[str, Any]:
    enabled = _safe_bool(sec.get("trade_notify_daily_reflection_auto_apply_enabled"), False)
    allow_keys_default = "ai_train_weekly_good_hours,ai_train_weekly_bad_hours,no_paper_hours"
    allow_keys = _csv_token_list(sec.get("trade_notify_daily_reflection_auto_apply_keys", allow_keys_default))
    min_conf = str(sec.get("trade_notify_daily_reflection_auto_apply_min_confidence", "high")).strip().lower() or "high"
    max_changes = max(1, _safe_int(sec.get("trade_notify_daily_reflection_auto_apply_max_changes"), 2))
    approver = str(sec.get("trade_notify_daily_reflection_auto_apply_approver", "notifier_auto")).strip() or "notifier_auto"
    suggested_raw = reflection.get("suggested_control_updates")
    suggested = {str(k): str(v) for k, v in dict(suggested_raw).items()} if isinstance(suggested_raw, dict) else {}
    sample_confidence = str(reflection.get("sample_confidence", "")).strip().lower() or "-"
    blocked_keys = [k for k in sorted(suggested.keys()) if k not in allow_keys]
    allowed_updates = {k: v for k, v in sorted(suggested.items()) if k in allow_keys}
    reasons: List[str] = []

    if not enabled:
        reasons.append("auto_apply_disabled")
    if not suggested:
        reasons.append("no_suggestions")
    if _sample_confidence_rank(sample_confidence) < _sample_confidence_rank(min_conf):
        reasons.append(f"sample_confidence<{min_conf}")
    if len(allowed_updates) > max_changes:
        reasons.append(f"allowed_changes>{max_changes}")
    if not allowed_updates and suggested:
        reasons.append("no_allowed_keys")
    if blocked_keys:
        reasons.append("disallowed_keys_present")

    return {
        "enabled": enabled,
        "eligible": len(reasons) == 0,
        "reason": ",".join(reasons) if reasons else "eligible",
        "allowed_keys": allow_keys,
        "blocked_keys": blocked_keys,
        "min_confidence": min_conf,
        "sample_confidence": sample_confidence,
        "max_changes": max_changes,
        "approver": approver,
        "updates": allowed_updates,
        "suggested_count": len(suggested),
        "allowed_count": len(allowed_updates),
    }


def _auto_apply_text_block(auto_apply: Dict[str, Any]) -> str:
    if not auto_apply:
        return "【自動承認】\n自動承認=未評価"
    updates = auto_apply.get("updates") or {}
    update_text = ", ".join(f"{k}={v}" for k, v in sorted(dict(updates).items())) or "-"
    blocked_text = ",".join(str(x) for x in list(auto_apply.get("blocked_keys") or [])) or "-"
    if not _safe_bool(auto_apply.get("enabled"), False):
        if updates:
            return f"【自動承認】\n自動承認=OFF\n候補={update_text}"
        return "【自動承認】\n自動承認=OFF"
    if auto_apply.get("applied"):
        return (
            "【自動承認】\n"
            f"自動承認=適用済み\n"
            f"mode={auto_apply.get('approval_status', 'auto_approved')}\n"
            f"changes={update_text}"
        )
    return (
        "【自動承認】\n"
        "自動承認=未適用\n"
        f"reason={auto_apply.get('reason', '-')}\n"
        f"allowed={update_text}\n"
        f"blocked={blocked_text}"
    )


def _build_daily_reflection(
    *,
    daily_review: Dict[str, Any],
    state_obj: Dict[str, Any],
    control_values: Dict[str, str],
    goal_jpy: float,
    shadow_review: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    closed_n = max(0, _safe_int(daily_review.get("closed_n"), 0))
    active_row_n = max(0, _safe_int(daily_review.get("active_row_n"), 0))
    pnl_jpy_sum = float(_safe_float(daily_review.get("pnl_jpy_sum")) or 0.0)
    win_rate_pct = float(_safe_float(daily_review.get("win_rate_pct")) or 0.0)
    avg_ret_pct = float(_safe_float(daily_review.get("avg_ret_pct")) or 0.0)
    profit_factor_jpy = float(_safe_float(daily_review.get("profit_factor_jpy")) or 0.0)
    exit_breakdown = daily_review.get("exit_reason_breakdown") or {}
    tp_n = _safe_int(exit_breakdown.get("TP"), 0)
    sl_n = _safe_int(exit_breakdown.get("SL"), 0)
    timeout_n = _safe_int(exit_breakdown.get("TIMEOUT"), 0)
    eod_n = _safe_int(exit_breakdown.get("EOD"), 0)
    prenews_n = _safe_int(exit_breakdown.get("PRENEWS"), 0)
    loss_pattern_breakdown = daily_review.get("loss_pattern_breakdown") if isinstance(daily_review.get("loss_pattern_breakdown"), dict) else {}
    dominant_loss_pattern_key = str(daily_review.get("dominant_loss_pattern_key", "") or "").strip()
    dominant_loss_pattern_label = str(daily_review.get("dominant_loss_pattern_label_ja", "") or "").strip()
    opportunity_pattern_breakdown = daily_review.get("opportunity_pattern_breakdown") if isinstance(daily_review.get("opportunity_pattern_breakdown"), dict) else {}
    dominant_opportunity_pattern_key = str(daily_review.get("dominant_opportunity_pattern_key", "") or "").strip()
    dominant_opportunity_pattern_label = str(daily_review.get("dominant_opportunity_pattern_label_ja", "") or "").strip()
    good_hours = list(daily_review.get("good_hours") or [])
    bad_hours = list(daily_review.get("bad_hours") or [])
    worst_trade = daily_review.get("worst_trade") if isinstance(daily_review.get("worst_trade"), dict) else {}
    observe_ai_block_n = max(0, _safe_int(daily_review.get("observe_ai_block_n"), 0))
    observe_ai_block_htf60_countertrend_n = max(0, _safe_int(daily_review.get("observe_ai_block_htf60_countertrend_n"), 0))
    observe_ai_block_htf15_60_conflict_n = max(0, _safe_int(daily_review.get("observe_ai_block_htf15_60_conflict_n"), 0))
    observe_buy_fast_ma_near_n = max(0, _safe_int(daily_review.get("observe_buy_fast_ma_near_n"), 0))
    observe_sell_fast_ma_near_n = max(0, _safe_int(daily_review.get("observe_sell_fast_ma_near_n"), 0))
    observe_trend_flip_cooldown_n = max(0, _safe_int(daily_review.get("observe_trend_flip_cooldown_n"), 0))
    observe_trend_strength_weak_n = max(0, _safe_int(daily_review.get("observe_trend_strength_weak_n"), 0))

    drift_obj = state_obj.get("_drift_watch", {})
    drift_status = str(drift_obj.get("status", "")).strip().upper() if isinstance(drift_obj, dict) else ""
    resume_outlook = build_drift_resume_snapshot(drift_obj if isinstance(drift_obj, dict) else {})
    risk_stop = _safe_bool(state_obj.get("_risk_stop", False), False)
    streak_stop = _safe_bool(state_obj.get("_streak_stop", False), False)
    achieved = pnl_jpy_sum >= float(goal_jpy)
    sample_confidence = "high" if closed_n >= 4 or active_row_n >= 10 else ("medium" if closed_n >= 2 or active_row_n >= 4 else "low")

    win_notes: List[str] = []
    loss_notes: List[str] = []
    next_actions: List[str] = []
    suggested_updates: Dict[str, str] = {}

    if closed_n <= 0:
        loss_notes.append("決済が0件で、日次の学習サンプルが不足。")
        next_actions.append("設定変更よりも、まずサンプル確保を優先。")
    else:
        if achieved:
            win_notes.append(f"日次目標 {float(goal_jpy):.0f}円を達成。")
        if win_rate_pct >= 60.0 and closed_n >= 2:
            win_notes.append(f"勝率 {win_rate_pct:.1f}% と安定。")
        if profit_factor_jpy >= 1.2 and closed_n >= 3:
            win_notes.append(f"PF {profit_factor_jpy:.2f} で利益が損失を上回った。")
        if tp_n > sl_n:
            win_notes.append(f"TP主導で決済できた（TP={tp_n}, SL={sl_n}）。")
        if good_hours:
            win_notes.append(f"良化時間帯は {','.join(str(int(h)) for h in good_hours)} 時。")
        if (
            observe_buy_fast_ma_near_n > 0
            or observe_trend_flip_cooldown_n > 0
            or observe_trend_strength_weak_n > 0
            or observe_ai_block_htf60_countertrend_n > 0
            or observe_ai_block_htf15_60_conflict_n > 0
        ):
            win_notes.append(
                "見送りガードが機能"
                f"（BUY近接={observe_buy_fast_ma_near_n}, 反転待機={observe_trend_flip_cooldown_n}, "
                f"トレンド弱={observe_trend_strength_weak_n}, 60逆風={observe_ai_block_htf60_countertrend_n}, "
                f"15/60ねじれ={observe_ai_block_htf15_60_conflict_n}）。"
            )

        if pnl_jpy_sum < float(goal_jpy):
            loss_notes.append(f"目標未達で差額は {pnl_jpy_sum - float(goal_jpy):+.0f}円。")
        if risk_stop:
            loss_notes.append("risk_stop が発動し、日次損失ガードに到達。")
        if streak_stop:
            loss_notes.append("streak_stop が発動し、連敗停止が必要。")
        if drift_status and drift_status != "NORMAL":
            loss_notes.append(f"drift_status={drift_status} で環境適合が弱い。")
        if profit_factor_jpy < 1.0 and closed_n >= 3:
            loss_notes.append(f"PF {profit_factor_jpy:.2f} で損失優位。")
        if avg_ret_pct <= 0.0 and closed_n >= 3:
            loss_notes.append(f"平均損益率 {avg_ret_pct:+.4f}% と期待値が弱い。")
        if sl_n >= tp_n and sl_n > 0:
            loss_notes.append(f"SL が TP を上回った（SL={sl_n}, TP={tp_n}）。")
        dominant_loss_n = _safe_int(loss_pattern_breakdown.get(dominant_loss_pattern_key), 0) if dominant_loss_pattern_key else 0
        if dominant_loss_pattern_key and dominant_loss_n > 0:
            loss_notes.append(f"負け型は {dominant_loss_pattern_label} が中心（{dominant_loss_n}件）。")
        if (timeout_n + eod_n) >= max(2, closed_n // 2) and closed_n > 0:
            loss_notes.append(f"TIMEOUT/EOD が多い（TIMEOUT={timeout_n}, EOD={eod_n}）。")
        dominant_opp_n = _safe_int(opportunity_pattern_breakdown.get(dominant_opportunity_pattern_key), 0) if dominant_opportunity_pattern_key else 0
        if dominant_opportunity_pattern_key and dominant_opp_n > 0:
            loss_notes.append(f"機会損失は {dominant_opportunity_pattern_label} が中心（{dominant_opp_n}件）。")
        if bad_hours:
            loss_notes.append(f"悪化時間帯は {','.join(str(int(h)) for h in bad_hours)} 時。")
        worst_pnl = _safe_float(worst_trade.get("pnl_jpy"))
        if worst_pnl is not None and worst_pnl < 0 and abs(float(worst_pnl)) >= max(20.0, abs(pnl_jpy_sum) * 0.5):
            loss_notes.append(f"単発最大損失 {float(worst_pnl):.2f}JPY が重い。")
        if (
            observe_ai_block_n <= 0
            and observe_buy_fast_ma_near_n <= 0
            and observe_trend_flip_cooldown_n <= 0
            and observe_trend_strength_weak_n <= 0
            and observe_ai_block_htf60_countertrend_n <= 0
            and observe_ai_block_htf15_60_conflict_n <= 0
        ):
            loss_notes.append("入口ガードの発火が少なく、見送り不足の可能性。")

    streak_stop_enabled = _safe_bool(control_values.get("streak_stop_enabled"), False)
    streak_stop_max_losses = max(0, _safe_int(control_values.get("streak_stop_max_losses"), 0))
    current_daily_limit = _safe_float(control_values.get("daily_loss_limit_pct"))
    current_good_hours = str(control_values.get("ai_train_weekly_good_hours", "")).strip()
    current_bad_hours = str(control_values.get("ai_train_weekly_bad_hours", "")).strip()
    current_no_paper_hours = str(control_values.get("no_paper_hours", "")).strip()

    can_tighten = closed_n >= 3 or risk_stop or streak_stop
    can_use_hours = closed_n >= 3 and sample_confidence != "low"

    if can_tighten and win_rate_pct < 50.0 and not streak_stop_enabled:
        suggested_updates["streak_stop_enabled"] = "1"
        next_actions.append("翌日は連敗停止を有効化して防御を強める。")
    if can_tighten and (win_rate_pct < 50.0 or sl_n >= 2 or risk_stop) and streak_stop_max_losses > 2:
        suggested_updates["streak_stop_max_losses"] = "2"
        next_actions.append("連敗許容を 2 回へ圧縮。")
    if can_tighten and (pnl_jpy_sum < 0 or risk_stop) and (profit_factor_jpy < 1.0 or streak_stop or risk_stop) and (
        current_daily_limit is None or abs(float(current_daily_limit)) > 0.5
    ):
        suggested_updates["daily_loss_limit_pct"] = "-0.50"
        next_actions.append("翌日は日次損失上限を -0.50% へ引き締め候補。")
    if can_use_hours and good_hours and achieved:
        merged_good_hours = _merge_hours_csv(current_good_hours, [int(x) for x in good_hours], limit=8)
        if merged_good_hours and merged_good_hours != current_good_hours:
            suggested_updates["ai_train_weekly_good_hours"] = merged_good_hours
            next_actions.append(f"良化時間帯 {merged_good_hours} 時を学習優遇へ反映候補。")
    if can_use_hours and bad_hours:
        merged_bad_hours = _merge_hours_csv(current_bad_hours, [int(x) for x in bad_hours], limit=8)
        if merged_bad_hours and merged_bad_hours != current_bad_hours:
            suggested_updates["ai_train_weekly_bad_hours"] = merged_bad_hours
            next_actions.append(f"悪化時間帯 {merged_bad_hours} 時は学習ペナルティ候補。")
        merged_no_paper_hours = _merge_hours_csv(current_no_paper_hours, [int(x) for x in bad_hours[:1]], limit=8)
        if merged_no_paper_hours and merged_no_paper_hours != current_no_paper_hours:
            suggested_updates["no_paper_hours"] = merged_no_paper_hours
            next_actions.append(f"悪化時間帯 {merged_no_paper_hours} 時は no_paper_hours 候補。")
    if timeout_n + eod_n >= max(2, closed_n // 2) and closed_n > 0:
        next_actions.append("TIMEOUT/EOD が多いため、翌日は時間切れ前の手仕舞い条件を確認。")
    if dominant_opportunity_pattern_key == "entry_unfilled":
        next_actions.append("entry約定失敗があるため、entry の price offset と通りやすさを確認。")
    elif dominant_opportunity_pattern_key == "exit_unfilled":
        next_actions.append("exit取り逃しがあるため、利確/損切りの marketable 条件を再確認。")
    elif dominant_opportunity_pattern_key == "news_avoidance":
        next_actions.append("時間帯回避が多いため、昼休み/ニュース前後の参加余地を見直す。")
    elif dominant_opportunity_pattern_key == "time_block":
        next_actions.append("時間ブロックが多いため、EOD/no_paper の窓設定を再確認。")
    elif dominant_opportunity_pattern_key == "spread_block":
        next_actions.append("spread回避が多いため、広がりやすい時間の参加抑制を維持。")
    if dominant_loss_pattern_key == "reversal":
        next_actions.append("反転巻き込みが多いため、利が乗った玉の逃がし条件を再確認。")
    elif dominant_loss_pattern_key == "weak_follow_through":
        next_actions.append("伸び不足が多いため、トレンド強度不足の見送りを優先。")
    elif dominant_loss_pattern_key == "late_entry":
        next_actions.append("entry遅れが多いため、MA近接や反転直後の entry をさらに慎重化。")
    if (
        observe_buy_fast_ma_near_n > 0
        or observe_trend_flip_cooldown_n > 0
        or observe_trend_strength_weak_n > 0
        or observe_ai_block_htf60_countertrend_n > 0
        or observe_ai_block_htf15_60_conflict_n > 0
    ):
        next_actions.append(
            "見送り件数を確認"
            f"（BUY近接={observe_buy_fast_ma_near_n}, 反転待機={observe_trend_flip_cooldown_n}, "
            f"トレンド弱={observe_trend_strength_weak_n}, 60逆風={observe_ai_block_htf60_countertrend_n}, "
            f"15/60ねじれ={observe_ai_block_htf15_60_conflict_n}）。"
        )
    if sample_confidence == "low":
        next_actions.append("サンプル信頼度が低いため、自動変更は最小限で継続観察。")

    if not win_notes:
        win_notes.append("大きな優位は限定的で、再現確認が必要。")
    if not loss_notes:
        loss_notes.append("重大な崩れはなく、現設定の継続観察でよい。")
    if not next_actions:
        next_actions.append("翌日は現設定を維持し、追加サンプルを優先。")

    shadow_filter_hint = "評価保留"
    shadow_filter_reason = ""
    shadow_htf_hint = "評価保留"
    shadow_htf_reason = ""
    shadow_exit_hint = "評価保留"
    shadow_exit_reason = ""
    if isinstance(shadow_review, dict) and shadow_review.get("available"):
        trend_now = int(_safe_int(shadow_review.get("observe_trend_strength_weak_n"), 0))
        trend_prev = int(_safe_int(shadow_review.get("prev_observe_trend_strength_weak_n"), 0))
        trend_delta = int(_safe_int(shadow_review.get("observe_trend_strength_weak_delta"), trend_now - trend_prev))
        htf60_now = int(_safe_int(shadow_review.get("observe_ai_block_htf60_countertrend_n"), 0))
        htf60_prev = int(_safe_int(shadow_review.get("prev_observe_ai_block_htf60_countertrend_n"), 0))
        htf60_delta = int(_safe_int(shadow_review.get("observe_ai_block_htf60_countertrend_delta"), htf60_now - htf60_prev))
        conflict_now = int(_safe_int(shadow_review.get("observe_ai_block_htf15_60_conflict_n"), 0))
        conflict_prev = int(_safe_int(shadow_review.get("prev_observe_ai_block_htf15_60_conflict_n"), 0))
        conflict_delta = int(
            _safe_int(shadow_review.get("observe_ai_block_htf15_60_conflict_delta"), conflict_now - conflict_prev)
        )
        weak_now = int(_safe_int(shadow_review.get("weak_progress_exit_n"), 0))
        weak_prev = int(_safe_int(shadow_review.get("prev_weak_progress_exit_n"), 0))
        weak_delta = int(_safe_int(shadow_review.get("weak_progress_exit_delta"), weak_now - weak_prev))
        progress_reversal_now = int(_safe_int(shadow_review.get("progress_reversal_exit_n"), 0))
        progress_reversal_prev = int(_safe_int(shadow_review.get("prev_progress_reversal_exit_n"), 0))
        progress_reversal_delta = int(
            _safe_int(
                shadow_review.get("progress_reversal_exit_delta"),
                progress_reversal_now - progress_reversal_prev,
            )
        )
        near_tp_now = int(_safe_int(shadow_review.get("near_tp_giveback_exit_n"), 0))
        near_tp_prev = int(_safe_int(shadow_review.get("prev_near_tp_giveback_exit_n"), 0))
        near_tp_delta = int(
            _safe_int(
                shadow_review.get("near_tp_giveback_exit_delta"),
                near_tp_now - near_tp_prev,
            )
        )
        progress_timeout_now = int(_safe_int(shadow_review.get("progress_timeout_n"), 0))
        progress_timeout_prev = int(_safe_int(shadow_review.get("prev_progress_timeout_n"), 0))
        progress_timeout_delta = int(
            _safe_int(shadow_review.get("progress_timeout_delta"), progress_timeout_now - progress_timeout_prev)
        )
        timeout_now = int(_safe_int(shadow_review.get("plain_timeout_n"), _safe_int(shadow_review.get("timeout_n"), 0)))
        timeout_prev = int(_safe_int(shadow_review.get("prev_plain_timeout_n"), _safe_int(shadow_review.get("prev_timeout_n"), 0)))
        timeout_delta = int(_safe_int(shadow_review.get("timeout_delta"), timeout_now - timeout_prev))
        closed_shadow = int(_safe_int(shadow_review.get("closed_n"), 0))
        if closed_shadow >= 3:
            if trend_delta > 0 and timeout_delta < 0:
                shadow_filter_hint = "維持寄り"
                shadow_filter_reason = f"trend弱 {trend_now}件 ({trend_delta:+d}) / TIMEOUT {timeout_now}件 ({timeout_delta:+d})"
            elif trend_delta > 0 and timeout_delta >= 0:
                shadow_filter_hint = "少し緩め候補"
                shadow_filter_reason = f"trend弱 {trend_now}件 ({trend_delta:+d}) の割に TIMEOUT {timeout_now}件 ({timeout_delta:+d})"
            elif trend_delta <= 0 and timeout_delta > 0:
                shadow_filter_hint = "少し強め候補"
                shadow_filter_reason = f"trend弱 {trend_now}件 ({trend_delta:+d}) でも TIMEOUT {timeout_now}件 ({timeout_delta:+d})"
            else:
                shadow_filter_hint = "現状維持"
                shadow_filter_reason = f"trend弱 {trend_now}件 ({trend_delta:+d}) / TIMEOUT {timeout_now}件 ({timeout_delta:+d})"
            htf_block_delta = htf60_delta + conflict_delta
            if htf_block_delta > 0 and timeout_delta <= 0:
                shadow_htf_hint = "維持寄り"
                shadow_htf_reason = (
                    f"HTF60逆風 {htf60_now}件 ({htf60_delta:+d}) / "
                    f"15/60ねじれ {conflict_now}件 ({conflict_delta:+d}) / "
                    f"TIMEOUT {timeout_now}件 ({timeout_delta:+d})"
                )
            elif htf_block_delta > 0 and timeout_delta > 0:
                shadow_htf_hint = "観察寄り"
                shadow_htf_reason = (
                    f"HTF60逆風 {htf60_now}件 ({htf60_delta:+d}) / "
                    f"15/60ねじれ {conflict_now}件 ({conflict_delta:+d}) の割に "
                    f"TIMEOUT {timeout_now}件 ({timeout_delta:+d})"
                )
            elif htf_block_delta <= 0 and timeout_delta > 0:
                shadow_htf_hint = "少し強め候補"
                shadow_htf_reason = (
                    f"HTF60逆風 {htf60_now}件 ({htf60_delta:+d}) / "
                    f"15/60ねじれ {conflict_now}件 ({conflict_delta:+d}) でも "
                    f"TIMEOUT {timeout_now}件 ({timeout_delta:+d})"
                )
            else:
                shadow_htf_hint = "現状維持"
                shadow_htf_reason = (
                    f"HTF60逆風 {htf60_now}件 ({htf60_delta:+d}) / "
                    f"15/60ねじれ {conflict_now}件 ({conflict_delta:+d}) / "
                    f"TIMEOUT {timeout_now}件 ({timeout_delta:+d})"
                )
            if near_tp_delta > 0 and progress_timeout_delta <= 0:
                shadow_exit_hint = "維持寄り"
                shadow_exit_reason = (
                    f"NEAR_TP_GIVEBACK {near_tp_now}件 ({near_tp_delta:+d}) / "
                    f"進行後TIMEOUT {progress_timeout_now}件 ({progress_timeout_delta:+d})"
                )
            elif near_tp_delta <= 0 and progress_timeout_delta > 0:
                shadow_exit_hint = "少し早め候補"
                shadow_exit_reason = (
                    f"NEAR_TP_GIVEBACK {near_tp_now}件 ({near_tp_delta:+d}) に対し "
                    f"進行後TIMEOUT {progress_timeout_now}件 ({progress_timeout_delta:+d})"
                )
            elif progress_reversal_delta > 0 and progress_timeout_delta < 0:
                shadow_exit_hint = "維持寄り"
                shadow_exit_reason = (
                    f"PROGRESS_REVERSAL {progress_reversal_now}件 ({progress_reversal_delta:+d}) / "
                    f"進行後TIMEOUT {progress_timeout_now}件 ({progress_timeout_delta:+d})"
                )
            elif progress_reversal_delta <= 0 and progress_timeout_delta > 0:
                shadow_exit_hint = "少し早め候補"
                shadow_exit_reason = (
                    f"PROGRESS_REVERSAL {progress_reversal_now}件 ({progress_reversal_delta:+d}) に対し "
                    f"進行後TIMEOUT {progress_timeout_now}件 ({progress_timeout_delta:+d})"
                )
            elif progress_reversal_delta > 0 and progress_timeout_delta >= 0:
                shadow_exit_hint = "観察寄り"
                shadow_exit_reason = (
                    f"PROGRESS_REVERSAL {progress_reversal_now}件 ({progress_reversal_delta:+d}) でも "
                    f"進行後TIMEOUT {progress_timeout_now}件 ({progress_timeout_delta:+d})"
                )
            elif weak_delta > 0 and timeout_delta < 0:
                shadow_exit_hint = "維持寄り"
                shadow_exit_reason = f"WEAK_PROGRESS {weak_now}件 ({weak_delta:+d}) / TIMEOUT {timeout_now}件 ({timeout_delta:+d})"
            elif weak_delta <= 0 and timeout_delta > 0:
                shadow_exit_hint = "少し早め候補"
                shadow_exit_reason = f"WEAK_PROGRESS {weak_now}件 ({weak_delta:+d}) に対し TIMEOUT {timeout_now}件 ({timeout_delta:+d})"
            elif weak_delta > 0 and timeout_delta >= 0:
                shadow_exit_hint = "観察寄り"
                shadow_exit_reason = f"WEAK_PROGRESS {weak_now}件 ({weak_delta:+d}) でも TIMEOUT {timeout_now}件 ({timeout_delta:+d})"
            else:
                shadow_exit_hint = "現状維持"
                shadow_exit_reason = f"WEAK_PROGRESS {weak_now}件 ({weak_delta:+d}) / TIMEOUT {timeout_now}件 ({timeout_delta:+d})"
        else:
            shadow_filter_reason = f"shadow closed_n={closed_shadow} で判断保留"
            shadow_htf_reason = f"shadow closed_n={closed_shadow} で判断保留"
            shadow_exit_reason = f"shadow closed_n={closed_shadow} で判断保留"

    if shadow_filter_reason:
        next_actions.append(f"shadow filter={shadow_filter_hint} ({shadow_filter_reason})")
    if shadow_htf_reason:
        next_actions.append(f"shadow htf={shadow_htf_hint} ({shadow_htf_reason})")
    if shadow_exit_reason:
        next_actions.append(f"shadow exit={shadow_exit_hint} ({shadow_exit_reason})")

    return {
        "goal_achieved": bool(achieved),
        "drift_status": drift_status or "-",
        "resume_outlook": dict(resume_outlook),
        "resume_outlook_summary": str(resume_outlook.get("summary", "-") or "-"),
        "resume_outlook_detail": str(resume_outlook.get("detail", "-") or "-"),
        "guard_counts": {
            "ai_block": int(observe_ai_block_n),
            "ai_block_htf60_countertrend": int(observe_ai_block_htf60_countertrend_n),
            "ai_block_htf15_60_conflict": int(observe_ai_block_htf15_60_conflict_n),
            "buy_fast_ma_near": int(observe_buy_fast_ma_near_n),
            "sell_fast_ma_near": int(observe_sell_fast_ma_near_n),
            "trend_flip_cooldown": int(observe_trend_flip_cooldown_n),
            "trend_strength_weak": int(observe_trend_strength_weak_n),
        },
        "loss_pattern_breakdown": dict(loss_pattern_breakdown),
        "dominant_loss_pattern_key": dominant_loss_pattern_key,
        "dominant_loss_pattern_label_ja": dominant_loss_pattern_label,
        "opportunity_pattern_breakdown": dict(opportunity_pattern_breakdown),
        "dominant_opportunity_pattern_key": dominant_opportunity_pattern_key,
        "dominant_opportunity_pattern_label_ja": dominant_opportunity_pattern_label,
        "risk_stop": bool(risk_stop),
        "streak_stop": bool(streak_stop),
        "sample_confidence": sample_confidence,
        "shadow_filter_hint": shadow_filter_hint,
        "shadow_filter_reason": shadow_filter_reason,
        "shadow_htf_hint": shadow_htf_hint,
        "shadow_htf_reason": shadow_htf_reason,
        "shadow_exit_hint": shadow_exit_hint,
        "shadow_exit_reason": shadow_exit_reason,
        "win_notes": list(win_notes[:3]),
        "loss_notes": list(loss_notes[:3]),
        "next_day_actions": list(next_actions[:4]),
        "suggested_control_updates": dict(suggested_updates),
    }


def _build_daily_reflection_report(
    *,
    report_dt: datetime,
    host: str,
    day8: str,
    goal_jpy: float,
    daily_review: Dict[str, Any],
    reflection: Dict[str, Any],
    shadow_review: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out = {
        "meta": {
            "spec": "OUROBOROS_DAILY_REFLECTION_V1",
            "generated_at_jst": report_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "host": host,
        },
        "goal": {
            "target_jpy": float(goal_jpy),
            "achieved": bool(reflection.get("goal_achieved")),
        },
        "range": {
            "day8": str(day8),
        },
        "daily_review": dict(daily_review),
        "reflection": dict(reflection),
        "approval": {
            "status": "pending",
            "approved_at": "",
            "approved_by": "",
            "changed_keys": [],
            "changed_count": 0,
        },
    }
    if isinstance(shadow_review, dict) and shadow_review:
        out["shadow_review"] = dict(shadow_review)
    return out


def _reflection_text_block(reflection: Dict[str, Any]) -> str:
    win_notes = list(reflection.get("win_notes") or [])
    loss_notes = list(reflection.get("loss_notes") or [])
    next_actions = list(reflection.get("next_day_actions") or [])
    suggested = reflection.get("suggested_control_updates") or {}
    sample_confidence = str(reflection.get("sample_confidence", "-")).strip().lower()
    sample_confidence_ja = {
        "high": "高",
        "medium": "中",
        "low": "低",
    }.get(sample_confidence, "-")
    suggested_text = ", ".join(f"{k}={v}" for k, v in sorted(dict(suggested).items())) or "-"
    loss_pattern = str(reflection.get("dominant_loss_pattern_label_ja", "") or "").strip() or "-"
    opp_pattern = str(reflection.get("dominant_opportunity_pattern_label_ja", "") or "").strip() or "-"
    shadow_filter_hint = str(reflection.get("shadow_filter_hint", "-") or "-").strip() or "-"
    shadow_htf_hint = str(reflection.get("shadow_htf_hint", "-") or "-").strip() or "-"
    shadow_exit_hint = str(reflection.get("shadow_exit_hint", "-") or "-").strip() or "-"
    return (
        "【反省】\n"
        f"反省信頼度={sample_confidence_ja}\n"
        f"負け型={loss_pattern}\n"
        f"機会損失={opp_pattern}\n"
        f"shadow調整=filter={shadow_filter_hint} / htf={shadow_htf_hint} / exit={shadow_exit_hint}\n"
        f"勝因={' / '.join(str(x) for x in win_notes[:3])}\n"
        f"敗因={' / '.join(str(x) for x in loss_notes[:3])}\n"
        f"翌日方針={' / '.join(str(x) for x in next_actions[:4])}\n"
        f"変更候補={suggested_text}"
    )


def _format_hour_list(hours: Any) -> str:
    vals = [str(int(x)) for x in list(hours or []) if 0 <= _safe_int(x, -1) <= 23]
    return ",".join(vals) if vals else "-"


def _format_trade_snapshot(trade: Any) -> str:
    if not isinstance(trade, dict) or not trade:
        return "-"
    pnl = _safe_float(trade.get("pnl_jpy"))
    ret = _safe_float(trade.get("ret_pct"))
    result = str(trade.get("result", "-")).strip() or "-"
    parts = [result]
    if pnl is not None:
        parts.append(f"{float(pnl):+.2f}JPY")
    if ret is not None:
        parts.append(f"{float(ret):+.3f}%")
    return " ".join(parts)


def _reflection_resume_outlook_text(reflection: Dict[str, Any]) -> str:
    summary = str(reflection.get("resume_outlook_summary", "") or "").strip()
    if summary:
        return summary
    drift_status = str(reflection.get("drift_status", "") or "").strip().upper()
    if drift_status == "NORMAL":
        return "復帰OK"
    if drift_status == "INSUFFICIENT":
        return "復帰待ち"
    if drift_status == "ALERT":
        return "警戒中"
    return "-"


def _build_daily_goal_summary_block(
    *,
    goal_jpy: float,
    daily_review: Dict[str, Any],
    reflection: Dict[str, Any],
    auto_apply: Dict[str, Any],
    shadow_review: Optional[Dict[str, Any]] = None,
) -> str:
    pnl_jpy = float(_safe_float(daily_review.get("pnl_jpy_sum")) or 0.0)
    ret_pct = float(_safe_float(daily_review.get("ret_sum_pct")) or 0.0)
    closed_n = int(_safe_int(daily_review.get("closed_n"), 0))
    delta_jpy = pnl_jpy - float(goal_jpy)
    status_label = "達成" if pnl_jpy >= float(goal_jpy) else "未達"
    sample_confidence = str(reflection.get("sample_confidence", "-")).strip().lower()
    sample_confidence_ja = {
        "high": "高",
        "medium": "中",
        "low": "低",
    }.get(sample_confidence, "-")
    resume_text = _reflection_resume_outlook_text(reflection)
    drift_text = str(reflection.get("drift_status", "-") or "-")

    auto_line = "未評価"
    if auto_apply:
        if auto_apply.get("applied"):
            auto_line = "適用済み"
        elif _safe_bool(auto_apply.get("enabled"), False):
            auto_line = f"未適用({auto_apply.get('reason', '-')})"
        else:
            auto_line = "OFF"

    shadow_line = "shadow=データなし"
    if isinstance(shadow_review, dict) and shadow_review.get("available"):
        shadow_line = (
            f"shadow={float(_safe_float(shadow_review.get('pnl_jpy_sum')) or 0.0):+.2f}JPY"
            f" / close={int(_safe_int(shadow_review.get('closed_n'), 0))}"
            f" / win={float(_safe_float(shadow_review.get('win_rate_pct')) or 0.0):.1f}%"
            f" / tech={int(_safe_int(shadow_review.get('exit_technical_n'), 0))}"
            f" / weak={int(_safe_int(shadow_review.get('weak_progress_exit_n'), 0))}"
            f" / pr={int(_safe_int(shadow_review.get('progress_reversal_exit_n'), 0))}"
            f" / ntp={int(_safe_int(shadow_review.get('near_tp_giveback_exit_n'), 0))}"
            f" / pto={int(_safe_int(shadow_review.get('progress_timeout_n'), 0))}"
            f" / nf={int(_safe_int(shadow_review.get('no_follow_through_exit_n'), 0))}"
            f" / trend={int(_safe_int(shadow_review.get('observe_trend_strength_weak_n'), 0))}"
            f" / htf60={int(_safe_int(shadow_review.get('observe_ai_block_htf60_countertrend_n'), 0))}"
            f" / conflict={int(_safe_int(shadow_review.get('observe_ai_block_htf15_60_conflict_n'), 0))}"
            f" / timeout={int(_safe_int(shadow_review.get('plain_timeout_n'), _safe_int(shadow_review.get('timeout_n'), 0)))}"
        )
    shadow_focus = ""
    if isinstance(shadow_review, dict):
        tech_now = int(_safe_int(shadow_review.get("exit_technical_n"), 0))
        tech_prev = int(_safe_int(shadow_review.get("prev_exit_technical_n"), 0))
        tech_delta = int(_safe_int(shadow_review.get("exit_technical_delta"), tech_now - tech_prev))
        trend_now = int(_safe_int(shadow_review.get("observe_trend_strength_weak_n"), 0))
        trend_prev = int(_safe_int(shadow_review.get("prev_observe_trend_strength_weak_n"), 0))
        trend_delta = int(_safe_int(shadow_review.get("observe_trend_strength_weak_delta"), trend_now - trend_prev))
        weak_now = int(_safe_int(shadow_review.get("weak_progress_exit_n"), 0))
        weak_prev = int(_safe_int(shadow_review.get("prev_weak_progress_exit_n"), 0))
        weak_delta = int(_safe_int(shadow_review.get("weak_progress_exit_delta"), weak_now - weak_prev))
        progress_reversal_now = int(_safe_int(shadow_review.get("progress_reversal_exit_n"), 0))
        progress_reversal_prev = int(_safe_int(shadow_review.get("prev_progress_reversal_exit_n"), 0))
        progress_reversal_delta = int(
            _safe_int(
                shadow_review.get("progress_reversal_exit_delta"),
                progress_reversal_now - progress_reversal_prev,
            )
        )
        near_tp_now = int(_safe_int(shadow_review.get("near_tp_giveback_exit_n"), 0))
        near_tp_prev = int(_safe_int(shadow_review.get("prev_near_tp_giveback_exit_n"), 0))
        near_tp_delta = int(
            _safe_int(
                shadow_review.get("near_tp_giveback_exit_delta"),
                near_tp_now - near_tp_prev,
            )
        )
        progress_timeout_now = int(_safe_int(shadow_review.get("progress_timeout_n"), 0))
        progress_timeout_prev = int(_safe_int(shadow_review.get("prev_progress_timeout_n"), 0))
        progress_timeout_delta = int(
            _safe_int(shadow_review.get("progress_timeout_delta"), progress_timeout_now - progress_timeout_prev)
        )
        no_follow_now = int(_safe_int(shadow_review.get("no_follow_through_exit_n"), 0))
        no_follow_prev = int(_safe_int(shadow_review.get("prev_no_follow_through_exit_n"), 0))
        no_follow_delta = int(
            _safe_int(shadow_review.get("no_follow_through_exit_delta"), no_follow_now - no_follow_prev)
        )
        htf60_now = int(_safe_int(shadow_review.get("observe_ai_block_htf60_countertrend_n"), 0))
        htf60_prev = int(_safe_int(shadow_review.get("prev_observe_ai_block_htf60_countertrend_n"), 0))
        htf60_delta = int(_safe_int(shadow_review.get("observe_ai_block_htf60_countertrend_delta"), htf60_now - htf60_prev))
        conflict_now = int(_safe_int(shadow_review.get("observe_ai_block_htf15_60_conflict_n"), 0))
        conflict_prev = int(_safe_int(shadow_review.get("prev_observe_ai_block_htf15_60_conflict_n"), 0))
        conflict_delta = int(
            _safe_int(shadow_review.get("observe_ai_block_htf15_60_conflict_delta"), conflict_now - conflict_prev)
        )
        timeout_now = int(_safe_int(shadow_review.get("plain_timeout_n"), _safe_int(shadow_review.get("timeout_n"), 0)))
        timeout_prev = int(_safe_int(shadow_review.get("prev_plain_timeout_n"), _safe_int(shadow_review.get("prev_timeout_n"), 0)))
        timeout_delta = int(_safe_int(shadow_review.get("timeout_delta"), timeout_now - timeout_prev))
        focus_lines: List[str] = []
        if tech_now > 0 and tech_delta > 0:
            focus_lines.append(f"shadow注目=技術的exit {tech_now}件 (前日比 +{tech_delta})")
        if weak_now > 0 and weak_delta > 0:
            focus_lines.append(f"shadow注目=WEAK_PROGRESS {weak_now}件 (前日比 +{weak_delta})")
        if progress_reversal_now > 0 and progress_reversal_delta > 0:
            focus_lines.append(f"shadow注目=進行戻しexit {progress_reversal_now}件 (前日比 +{progress_reversal_delta})")
        if near_tp_now > 0 and near_tp_delta > 0:
            focus_lines.append(f"shadow注目=TP寸前戻しexit {near_tp_now}件 (前日比 +{near_tp_delta})")
        if progress_timeout_now > 0 and progress_timeout_delta > 0:
            focus_lines.append(f"shadow注目=進行後TIMEOUT {progress_timeout_now}件 (前日比 +{progress_timeout_delta})")
        if no_follow_now > 0 and no_follow_delta > 0:
            focus_lines.append(f"shadow注目=初動なしexit {no_follow_now}件 (前日比 +{no_follow_delta})")
        if htf60_now > 0 and htf60_delta > 0:
            focus_lines.append(f"shadow注目=HTF60逆風ブロック {htf60_now}件 (前日比 +{htf60_delta})")
        if conflict_now > 0 and conflict_delta > 0:
            focus_lines.append(f"shadow注目=15/60ねじれブロック {conflict_now}件 (前日比 +{conflict_delta})")
        if (
            trend_now > 0
            or timeout_now > 0
            or trend_prev > 0
            or timeout_prev > 0
            or progress_reversal_now > 0
            or progress_reversal_prev > 0
            or near_tp_now > 0
            or near_tp_prev > 0
            or progress_timeout_now > 0
            or progress_timeout_prev > 0
            or no_follow_now > 0
            or no_follow_prev > 0
            or htf60_now > 0
            or htf60_prev > 0
            or conflict_now > 0
            or conflict_prev > 0
        ):
            focus_lines.append(
                "shadow比較="
                f"trend弱 {trend_now}件 ({trend_delta:+d}) / "
                f"weak {weak_now}件 ({weak_delta:+d}) / "
                f"進行戻しexit {progress_reversal_now}件 ({progress_reversal_delta:+d}) / "
                f"TP寸前戻しexit {near_tp_now}件 ({near_tp_delta:+d}) / "
                f"進行後TIMEOUT {progress_timeout_now}件 ({progress_timeout_delta:+d}) / "
                f"初動なしexit {no_follow_now}件 ({no_follow_delta:+d}) / "
                f"HTF60逆風 {htf60_now}件 ({htf60_delta:+d}) / "
                f"15/60ねじれ {conflict_now}件 ({conflict_delta:+d}) / "
                f"TIMEOUT {timeout_now}件 ({timeout_delta:+d})"
            )
            if near_tp_delta > 0 and progress_timeout_delta <= 0:
                focus_lines.append("shadow判定=TP寸前戻しexit が出て進行後TIMEOUT は増えていない。利確寸前の逃がしは維持寄り")
            elif near_tp_delta > 0 and progress_timeout_delta > 0:
                focus_lines.append("shadow判定=TP寸前戻しexit は出たが進行後TIMEOUT 改善は薄い。閾値は観察寄り")
            elif progress_reversal_delta > 0 and progress_timeout_delta < 0:
                focus_lines.append("shadow判定=進行戻しexit 増で進行後TIMEOUT 減。戻し対策は維持寄り")
            elif progress_reversal_delta > 0 and progress_timeout_delta >= 0:
                focus_lines.append("shadow判定=進行戻しexit は出たが進行後TIMEOUT 改善は薄い。閾値は観察寄り")
            elif weak_delta > 0 and timeout_delta < 0:
                focus_lines.append("shadow判定=WEAK_PROGRESS 増で TIMEOUT 減。flat玉の早仕舞いは維持寄り")
            elif no_follow_delta > 0 and timeout_delta < 0:
                focus_lines.append("shadow判定=初動なしexit 増で TIMEOUT 減。初動なし玉の早仕舞いは維持寄り")
            elif trend_delta > 0 and timeout_delta < 0:
                focus_lines.append("shadow判定=見送り増で TIMEOUT 減。trend 強度フィルタは維持寄り")
            elif weak_delta > 0 and timeout_delta >= 0:
                focus_lines.append("shadow判定=WEAK_PROGRESS 増の割に TIMEOUT 改善が薄い。閾値は据え置きで観察寄り")
            elif no_follow_delta > 0 and timeout_delta >= 0:
                focus_lines.append("shadow判定=初動なしexit 増の割に TIMEOUT 改善が薄い。閾値は観察寄り")
            elif trend_delta > 0 and timeout_delta >= 0:
                focus_lines.append("shadow判定=見送り増の割に TIMEOUT 改善が薄い。min_er は少し緩め候補")
            elif trend_delta <= 0 and timeout_delta > 0:
                focus_lines.append("shadow判定=TIMEOUT 増で効き不足。min_er は少し強め候補")
        if focus_lines:
            shadow_focus = "\n" + "\n".join(focus_lines)

    return (
        "【要約】\n"
        f"判定={status_label} / 損益={pnl_jpy:+.2f}JPY / 目標差額={delta_jpy:+.2f}JPY\n"
        f"件数={closed_n} / 累積ret={ret_pct:+.4f}% / 信頼度={sample_confidence_ja}\n"
        f"drift={drift_text} / 復帰={resume_text} / 自動承認={auto_line}\n"
        f"{shadow_line}"
        f"{shadow_focus}"
    )


def _daily_review_text_block(
    daily_review: Dict[str, Any],
    reflection: Dict[str, Any],
    shadow_review: Optional[Dict[str, Any]] = None,
) -> str:
    sample_confidence = str(reflection.get("sample_confidence", "-")).strip().lower()
    sample_confidence_ja = {
        "high": "高",
        "medium": "中",
        "low": "低",
    }.get(sample_confidence, "-")
    guard_counts = reflection.get("guard_counts") if isinstance(reflection.get("guard_counts"), dict) else {}
    ai_block_n = int(_safe_int(guard_counts.get("ai_block"), 0))
    ai_block_htf60_countertrend_n = int(_safe_int(guard_counts.get("ai_block_htf60_countertrend"), 0))
    ai_block_htf15_60_conflict_n = int(_safe_int(guard_counts.get("ai_block_htf15_60_conflict"), 0))
    buy_fast_ma_near_n = int(_safe_int(guard_counts.get("buy_fast_ma_near"), 0))
    trend_flip_cooldown_n = int(_safe_int(guard_counts.get("trend_flip_cooldown"), 0))
    trend_strength_weak_n = int(_safe_int(guard_counts.get("trend_strength_weak"), 0))
    loss_patterns = reflection.get("loss_pattern_breakdown") if isinstance(reflection.get("loss_pattern_breakdown"), dict) else {}
    opp_patterns = reflection.get("opportunity_pattern_breakdown") if isinstance(reflection.get("opportunity_pattern_breakdown"), dict) else {}
    loss_pattern_text = (
        f"反転={int(_safe_int(loss_patterns.get('reversal'), 0))}/"
        f"伸び={int(_safe_int(loss_patterns.get('weak_follow_through'), 0))}/"
        f"遅れ={int(_safe_int(loss_patterns.get('late_entry'), 0))}"
    )
    opp_pattern_text = (
        f"entry失敗={int(_safe_int(opp_patterns.get('entry_unfilled'), 0))}/"
        f"exit失敗={int(_safe_int(opp_patterns.get('exit_unfilled'), 0))}/"
        f"news={int(_safe_int(opp_patterns.get('news_avoidance'), 0))}/"
        f"time={int(_safe_int(opp_patterns.get('time_block'), 0))}/"
        f"spread={int(_safe_int(opp_patterns.get('spread_block'), 0))}"
    )
    tech_feature_text = _format_technical_feature_outcomes(daily_review)
    phase_feature_text = _format_market_phase_outcomes(daily_review)
    phase_transition_text = _format_market_phase_transitions(daily_review)
    shadow_line = ""
    if isinstance(shadow_review, dict) and shadow_review.get("available"):
        shadow_line = (
            "\n"
            "影運用="
            f"close={int(_safe_int(shadow_review.get('closed_n'), 0))} / "
            f"win={float(_safe_float(shadow_review.get('win_rate_pct')) or 0.0):.1f}% / "
            f"pnl={float(_safe_float(shadow_review.get('pnl_jpy_sum')) or 0.0):+.2f}JPY / "
            f"exit_tech={int(_safe_int(shadow_review.get('exit_technical_n'), 0))} / "
            f"weak_progress={int(_safe_int(shadow_review.get('weak_progress_exit_n'), 0))} / "
            f"progress_reversal={int(_safe_int(shadow_review.get('progress_reversal_exit_n'), 0))} / "
            f"near_tp={int(_safe_int(shadow_review.get('near_tp_giveback_exit_n'), 0))} / "
            f"no_follow={int(_safe_int(shadow_review.get('no_follow_through_exit_n'), 0))} / "
            f"trend_weak={int(_safe_int(shadow_review.get('observe_trend_strength_weak_n'), 0))} / "
            f"htf60_block={int(_safe_int(shadow_review.get('observe_ai_block_htf60_countertrend_n'), 0))} / "
            f"conflict_block={int(_safe_int(shadow_review.get('observe_ai_block_htf15_60_conflict_n'), 0))} / "
            f"timeout={int(_safe_int(shadow_review.get('plain_timeout_n'), _safe_int(shadow_review.get('timeout_n'), 0)))}"
        )
    return (
        "【日次レビュー】\n"
        f"成績=信頼度{sample_confidence_ja} / close={int(_safe_int(daily_review.get('closed_n'), 0))} / "
        f"win={float(_safe_float(daily_review.get('win_rate_pct')) or 0.0):.1f}% / "
        f"pf={float(_safe_float(daily_review.get('profit_factor_jpy')) or 0.0):.2f} / "
        f"avg={float(_safe_float(daily_review.get('avg_ret_pct')) or 0.0):+.4f}% / "
        f"pnl={float(_safe_float(daily_review.get('pnl_jpy_sum')) or 0.0):+.2f}JPY\n"
        f"稼働=active={int(_safe_int(daily_review.get('active_row_n'), 0))} / "
        f"rows={int(_safe_int(daily_review.get('row_n'), 0))} / "
        f"skip_out={int(_safe_int(daily_review.get('skip_out_of_time_n'), 0))} / "
        f"last={str(daily_review.get('last_time') or '-')} {str(daily_review.get('last_result') or '-').strip() or '-'}\n"
        f"guard(ai/buy_near/flip/trend/htf60/conflict)={ai_block_n}/{buy_fast_ma_near_n}/{trend_flip_cooldown_n}/{trend_strength_weak_n}/{ai_block_htf60_countertrend_n}/{ai_block_htf15_60_conflict_n}\n"
        f"環境=drift={str(reflection.get('drift_status', '-'))} / "
        f"復帰={_reflection_resume_outlook_text(reflection)} / "
        f"risk={'ON' if _safe_bool(reflection.get('risk_stop'), False) else 'OFF'} / "
        f"streak={'ON' if _safe_bool(reflection.get('streak_stop'), False) else 'OFF'} / "
        f"良={_format_hour_list(daily_review.get('good_hours'))} / "
        f"悪={_format_hour_list(daily_review.get('bad_hours'))}\n"
        f"負け型={loss_pattern_text} / dominant={str(reflection.get('dominant_loss_pattern_label_ja') or '-')}\n"
        f"機会損失={opp_pattern_text} / dominant={str(reflection.get('dominant_opportunity_pattern_label_ja') or '-')}\n"
        f"局面={phase_feature_text} / 転換={phase_transition_text} / B回避={int(_safe_int(daily_review.get('observe_phase_b_n'), 0))}\n"
        f"特徴表={tech_feature_text}\n"
        f"代表取引=best={_format_trade_snapshot(daily_review.get('best_trade'))} / "
        f"worst={_format_trade_snapshot(daily_review.get('worst_trade'))}"
        f"{shadow_line}"
    )


def _build_daily_reflection_llm_prompt(
    *,
    day8: str,
    goal_jpy: float,
    daily_review: Dict[str, Any],
    reflection: Dict[str, Any],
    shadow_review: Optional[Dict[str, Any]] = None,
) -> str:
    exit_breakdown = daily_review.get("exit_reason_breakdown") or {}
    sample_confidence = str(reflection.get("sample_confidence", "-")).strip().lower() or "-"
    guard_counts = reflection.get("guard_counts") if isinstance(reflection.get("guard_counts"), dict) else {}
    loss_patterns = reflection.get("loss_pattern_breakdown") if isinstance(reflection.get("loss_pattern_breakdown"), dict) else {}
    opp_patterns = reflection.get("opportunity_pattern_breakdown") if isinstance(reflection.get("opportunity_pattern_breakdown"), dict) else {}
    suggested = reflection.get("suggested_control_updates") or {}
    suggested_lines = [f"- {k}={v}" for k, v in sorted(dict(suggested).items())]
    suggested_text = "\n".join(suggested_lines) if suggested_lines else "- 提案なし"
    return (
        "あなたはOuroborosの日次運用レビュー担当です。"
        "以下の数値だけを根拠に、終業時の反省メモを簡潔に書いてください。\n"
        "出力ルール:\n"
        "- ちょうど4行\n"
        "- 各行は必ず次のラベルで開始: 総評:, 勝因:, 敗因:, 翌日:\n"
        "- 各行に数値を最低1つ含める\n"
        "- 各行は1文で、40-90文字程度を目安にする\n"
        "- 前置きや補足は書かない\n\n"
        "判断ヒント:\n"
        "- closed_n<=1 や sample_confidence=low なら『サンプル薄い』を優先\n"
        "- pnl_jpy_sum<goal_jpy なら未達、pnl_jpy_sum>=goal_jpy なら達成として書く\n"
        "- sl_n>tp_n や bad_hours がある日は敗因で触れる\n"
        "- drift_status!=NORMAL や resume_outlook!=復帰OK の日は翌日で慎重運用を示す\n"
        "- dominant_loss_pattern_label_ja があれば敗因か翌日で 反転巻き込み / 伸び不足 / entry遅れ に触れる\n"
        "- dominant_opportunity_pattern_label_ja があれば敗因か翌日で entry約定失敗 / exit取り逃し / 時間帯回避 / 時間ブロック / spread回避 に触れる\n"
        "- ai_block_htf60_countertrend_n や ai_block_htf15_60_conflict_n が多い日は、上位足逆風や時間足ねじれに触れる\n"
        "- technical_feature_summary があれば、勝因/敗因で RSI/BB/ATR/GC の効きに触れる\n"
        "- market_phase_summary があれば、A/B/C局面別の効きやB回避件数に触れる\n"
        "- market_phase_transition_summary があれば、A/B/Cの局面転換と直近転換に触れる\n"
        "- shadow_filter_hint があれば翌日で維持/緩める/強める判断に触れる\n"
        "- shadow_htf_hint があれば翌日で HTF60逆風や 15/60ねじれの維持/強化/観察に触れる\n"
        "- shadow_exit_hint があれば翌日で WEAK_PROGRESS / PROGRESS_REVERSAL / NEAR_TP_GIVEBACK の維持/早め/観察に触れる\n"
        "- suggested_control_updates が空なら翌日は現設定維持寄りで書く\n\n"
        f"日付: {day8}\n"
        f"goal_jpy: {float(goal_jpy):.2f}\n"
        f"closed_n: {int(_safe_int(daily_review.get('closed_n'), 0))}\n"
        f"active_row_n: {int(_safe_int(daily_review.get('active_row_n'), 0))}\n"
        f"sample_confidence: {sample_confidence}\n"
        f"win_rate_pct: {float(_safe_float(daily_review.get('win_rate_pct')) or 0.0):.2f}\n"
        f"ret_sum_pct: {float(_safe_float(daily_review.get('ret_sum_pct')) or 0.0):.4f}\n"
        f"avg_ret_pct: {float(_safe_float(daily_review.get('avg_ret_pct')) or 0.0):.4f}\n"
        f"pnl_jpy_sum: {float(_safe_float(daily_review.get('pnl_jpy_sum')) or 0.0):.2f}\n"
        f"profit_factor_jpy: {float(_safe_float(daily_review.get('profit_factor_jpy')) or 0.0):.4f}\n"
        f"tp_n: {int(_safe_int(exit_breakdown.get('TP'), 0))}\n"
        f"sl_n: {int(_safe_int(exit_breakdown.get('SL'), 0))}\n"
        f"timeout_n: {int(_safe_int(exit_breakdown.get('TIMEOUT'), 0))}\n"
        f"eod_n: {int(_safe_int(exit_breakdown.get('EOD'), 0))}\n"
        f"loss_pattern_reversal_n: {int(_safe_int(loss_patterns.get('reversal'), 0))}\n"
        f"loss_pattern_weak_follow_through_n: {int(_safe_int(loss_patterns.get('weak_follow_through'), 0))}\n"
        f"loss_pattern_late_entry_n: {int(_safe_int(loss_patterns.get('late_entry'), 0))}\n"
        f"dominant_loss_pattern_label_ja: {str(reflection.get('dominant_loss_pattern_label_ja', '-'))}\n"
        f"opportunity_entry_unfilled_n: {int(_safe_int(opp_patterns.get('entry_unfilled'), 0))}\n"
        f"opportunity_exit_unfilled_n: {int(_safe_int(opp_patterns.get('exit_unfilled'), 0))}\n"
        f"opportunity_news_avoidance_n: {int(_safe_int(opp_patterns.get('news_avoidance'), 0))}\n"
        f"opportunity_time_block_n: {int(_safe_int(opp_patterns.get('time_block'), 0))}\n"
        f"opportunity_spread_block_n: {int(_safe_int(opp_patterns.get('spread_block'), 0))}\n"
        f"dominant_opportunity_pattern_label_ja: {str(reflection.get('dominant_opportunity_pattern_label_ja', '-'))}\n"
        f"ai_block_n: {int(_safe_int(guard_counts.get('ai_block'), 0))}\n"
        f"ai_block_htf60_countertrend_n: {int(_safe_int(guard_counts.get('ai_block_htf60_countertrend'), 0))}\n"
        f"ai_block_htf15_60_conflict_n: {int(_safe_int(guard_counts.get('ai_block_htf15_60_conflict'), 0))}\n"
        f"buy_fast_ma_near_n: {int(_safe_int(guard_counts.get('buy_fast_ma_near'), 0))}\n"
        f"trend_flip_cooldown_n: {int(_safe_int(guard_counts.get('trend_flip_cooldown'), 0))}\n"
        f"good_hours: {','.join(str(int(x)) for x in (daily_review.get('good_hours') or [])) or '-'}\n"
        f"bad_hours: {','.join(str(int(x)) for x in (daily_review.get('bad_hours') or [])) or '-'}\n"
        f"technical_feature_summary: {_format_technical_feature_outcomes(daily_review)}\n"
        f"market_phase_summary: {_format_market_phase_outcomes(daily_review)}\n"
        f"market_phase_transition_summary: {_format_market_phase_transitions(daily_review)}\n"
        f"market_phase_transition_n: {int(_safe_int(daily_review.get('market_phase_transition_n'), 0))}\n"
        f"observe_phase_b_n: {int(_safe_int(daily_review.get('observe_phase_b_n'), 0))}\n"
        f"drift_status: {str(reflection.get('drift_status', '-'))}\n"
        f"resume_outlook: {_reflection_resume_outlook_text(reflection)}\n"
        f"risk_stop: {bool(reflection.get('risk_stop'))}\n"
        f"streak_stop: {bool(reflection.get('streak_stop'))}\n"
        f"shadow_filter_hint: {str(reflection.get('shadow_filter_hint', '-'))}\n"
        f"shadow_filter_reason: {str(reflection.get('shadow_filter_reason', '-'))}\n"
        f"shadow_htf_hint: {str(reflection.get('shadow_htf_hint', '-'))}\n"
        f"shadow_htf_reason: {str(reflection.get('shadow_htf_reason', '-'))}\n"
        f"shadow_exit_hint: {str(reflection.get('shadow_exit_hint', '-'))}\n"
        f"shadow_exit_reason: {str(reflection.get('shadow_exit_reason', '-'))}\n"
        f"shadow_closed_n: {int(_safe_int((shadow_review or {}).get('closed_n'), 0))}\n"
        f"shadow_exit_technical_n: {int(_safe_int((shadow_review or {}).get('exit_technical_n'), 0))}\n"
        f"shadow_weak_progress_n: {int(_safe_int((shadow_review or {}).get('weak_progress_exit_n'), 0))}\n"
        f"shadow_progress_reversal_n: {int(_safe_int((shadow_review or {}).get('progress_reversal_exit_n'), 0))}\n"
        f"shadow_near_tp_giveback_n: {int(_safe_int((shadow_review or {}).get('near_tp_giveback_exit_n'), 0))}\n"
        f"shadow_progress_timeout_n: {int(_safe_int((shadow_review or {}).get('progress_timeout_n'), 0))}\n"
        f"shadow_no_follow_through_n: {int(_safe_int((shadow_review or {}).get('no_follow_through_exit_n'), 0))}\n"
        f"shadow_trend_weak_n: {int(_safe_int((shadow_review or {}).get('observe_trend_strength_weak_n'), 0))}\n"
        f"shadow_timeout_n: {int(_safe_int((shadow_review or {}).get('plain_timeout_n'), _safe_int((shadow_review or {}).get('timeout_n'), 0)))}\n"
        "suggested_control_updates:\n"
        f"{suggested_text}\n"
    )


def _build_fallback_daily_reflection_summary(
    *,
    day8: str,
    goal_jpy: float,
    daily_review: Dict[str, Any],
    reflection: Dict[str, Any],
    shadow_review: Optional[Dict[str, Any]] = None,
) -> str:
    win_notes = list(reflection.get("win_notes") or [])
    loss_notes = list(reflection.get("loss_notes") or [])
    next_actions = list(reflection.get("next_day_actions") or [])
    dominant_loss = str(reflection.get("dominant_loss_pattern_label_ja", "-") or "-")
    dominant_opp = str(reflection.get("dominant_opportunity_pattern_label_ja", "-") or "-")
    return "\n".join(
        [
            f"総評: day8={day8}, pnl_jpy={float(_safe_float(daily_review.get('pnl_jpy_sum')) or 0.0):.2f}, goal_jpy={float(goal_jpy):.2f}。",
            f"勝因: closed_n={int(_safe_int(daily_review.get('closed_n'), 0))}, win_rate={float(_safe_float(daily_review.get('win_rate_pct')) or 0.0):.1f}% で {' / '.join(str(x) for x in win_notes[:2]) or '優位限定的'}。",
            f"敗因: sl={int(_safe_int((daily_review.get('exit_reason_breakdown') or {}).get('SL'), 0))}, 型={dominant_loss}, 機会={dominant_opp}, drift={str(reflection.get('drift_status', '-'))} で {' / '.join(str(x) for x in loss_notes[:2]) or '大きな崩れなし'}。",
            f"翌日: suggested={len(dict(reflection.get('suggested_control_updates') or {}))}, shadow={str(reflection.get('shadow_filter_hint', '-'))}/{str(reflection.get('shadow_htf_hint', '-'))}/{str(reflection.get('shadow_exit_hint', '-'))}, action={' / '.join(str(x) for x in next_actions[:2]) or '現設定維持'}。",
        ]
    )


def _is_low_quality_llm_summary(text: str) -> bool:
    s = str(text or "").strip()
    if len(s) < 40:
        return True
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if len(lines) != 4:
        return True
    labels = ("総評:", "勝因:", "敗因:", "翌日:")
    if [next((lb for lb in labels if ln.startswith(lb)), "") for ln in lines] != list(labels):
        return True
    if not re.search(r"\d", s):
        return True
    unique_lines = {ln for ln in lines}
    if len(unique_lines) < 4:
        return True
    for ln, lb in zip(lines, labels):
        body = ln[len(lb):].strip()
        if len(body) < 8:
            return True
        if not re.search(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff]", body):
            return True
    return False


def _generate_daily_reflection_llm_feedback(
    *,
    day8: str,
    goal_jpy: float,
    daily_review: Dict[str, Any],
    reflection: Dict[str, Any],
    shadow_review: Optional[Dict[str, Any]],
    sec: Dict[str, Any],
) -> Dict[str, Any]:
    llm_mode = str(sec.get("trade_notify_daily_reflection_llm_mode", "off")).strip().lower() or "off"
    llm_provider = str(sec.get("trade_notify_daily_reflection_llm_provider", "ollama")).strip().lower() or "ollama"
    if llm_mode == "openai":
        llm_provider = "openai"
    elif llm_mode == "ollama":
        llm_provider = "ollama"
    feedback: Dict[str, Any] = {
        "mode": llm_mode,
        "provider": llm_provider,
        "used": False,
        "summary": "",
        "base_url": _normalize_base_url(str(sec.get("trade_notify_daily_reflection_ollama_base_url", OLLAMA_BASE_URL_DEFAULT))),
        "model": str(sec.get("trade_notify_daily_reflection_ollama_model", OLLAMA_MODEL_DEFAULT)).strip() or OLLAMA_MODEL_DEFAULT,
        "timeout_sec": max(1, _safe_int(sec.get("trade_notify_daily_reflection_ollama_timeout_sec"), OLLAMA_TIMEOUT_SEC_DEFAULT)),
        "attempt_timeout_sec": 0,
        "max_chars": max(120, _safe_int(sec.get("trade_notify_daily_reflection_ollama_max_chars"), OLLAMA_MAX_CHARS_DEFAULT)),
        "openai_base_url": normalize_openai_base_url(str(sec.get("trade_notify_daily_reflection_openai_base_url", OPENAI_BASE_URL_DEFAULT))),
        "openai_model": str(sec.get("trade_notify_daily_reflection_openai_model", OPENAI_MODEL_DEFAULT)).strip() or OPENAI_MODEL_DEFAULT,
        "openai_api_key_env": str(sec.get("trade_notify_daily_reflection_openai_api_key_env", OPENAI_API_KEY_ENV_DEFAULT)).strip() or OPENAI_API_KEY_ENV_DEFAULT,
        "openai_max_output_tokens": max(64, _safe_int(sec.get("trade_notify_daily_reflection_openai_max_output_tokens"), OPENAI_MAX_OUTPUT_TOKENS_DEFAULT)),
        "reason": "",
        "error": "",
    }
    if llm_mode == "off":
        feedback["reason"] = "llm_mode=off"
        return feedback

    feedback["attempt_timeout_sec"] = max(
        1,
        _safe_int(
            sec.get("trade_notify_daily_reflection_ollama_attempt_timeout_sec"),
            min(int(feedback["timeout_sec"]), 90),
        ),
    )

    prompt = _build_daily_reflection_llm_prompt(
        day8=day8,
        goal_jpy=goal_jpy,
        daily_review=daily_review,
        reflection=reflection,
        shadow_review=shadow_review,
    )
    feedback["prompt_chars"] = len(prompt)

    if llm_provider == "openai":
        try:
            api_key = os.getenv(str(feedback["openai_api_key_env"]), "")
            if not api_key:
                raise ValueError(f"{feedback['openai_api_key_env']} is empty")
            llm_text = run_openai_responses_summary(
                api_key=api_key,
                base_url=str(feedback["openai_base_url"]),
                model=str(feedback["openai_model"]),
                prompt=prompt,
                instructions=(
                    "日本語で、日次トレード反省を短く構造化する。"
                    "売買判断の自動実行は提案せず、根拠と翌日の観察点を明確にする。"
                ),
                timeout_sec=int(feedback["timeout_sec"]),
                max_chars=int(feedback["max_chars"]),
                max_output_tokens=int(feedback["openai_max_output_tokens"]),
            )
            if _is_low_quality_llm_summary(llm_text):
                llm_text = _build_fallback_daily_reflection_summary(
                    day8=day8,
                    goal_jpy=goal_jpy,
                    daily_review=daily_review,
                    reflection=reflection,
                    shadow_review=shadow_review,
                )
                feedback["reason"] = "openai_ok_with_fallback"
            else:
                feedback["reason"] = "openai_ok"
            feedback["used"] = True
            feedback["summary"] = llm_text
            feedback["model"] = str(feedback["openai_model"])
            feedback["base_url"] = str(feedback["openai_base_url"])
            feedback["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            feedback["error"] = ""
            return feedback
        except Exception as e:
            feedback["error"] = str(e)
            feedback["reason"] = "openai_failed"
            if llm_mode != "auto":
                return feedback
            feedback["provider"] = "ollama"
            feedback["reason"] = "openai_failed_try_ollama"

    chosen_model = str(feedback["model"])
    fallback_models = _csv_token_list(sec.get("trade_notify_daily_reflection_ollama_fallback_models", "qwen2.5:0.5b,qwen2.5:1.5b"))
    installed_models: List[str] = []
    try:
        installed_models = _ollama_list_models(str(feedback["base_url"]), int(feedback["timeout_sec"]))
        feedback["installed_models_count"] = len(installed_models)
        feedback["installed_generate_models"] = [m for m in installed_models if _is_ollama_generate_model(m)]
        if llm_mode == "auto":
            if installed_models:
                if not any(_is_ollama_model_match(m, chosen_model) for m in installed_models):
                    sorted_models = sorted([m for m in installed_models if _is_ollama_generate_model(m)], key=_model_size_score)
                    if sorted_models:
                        chosen_model = sorted_models[0]
                        feedback["model"] = chosen_model
                        feedback["reason"] = "requested_model_missing_use_smallest_installed"
                    else:
                        feedback["reason"] = "no_generate_models_installed"
            else:
                feedback["reason"] = "no_models_installed"
    except Exception as e:
        feedback["error"] = str(e)
        feedback["reason"] = "tags_fetch_failed" if llm_mode == "auto" else "tags_fetch_failed_but_try_generate"

    should_run = not (llm_mode == "auto" and feedback.get("reason") == "no_models_installed")
    if not should_run:
        return feedback

    try:
        attempt_models = _ollama_attempt_model_order(
            requested_model=chosen_model,
            installed_models=installed_models,
            fallback_models=fallback_models,
            auto_mode=(llm_mode == "auto"),
        )
        feedback["attempted_models"] = list(attempt_models)
        feedback["attempt_errors"] = {}

        llm_text = ""
        used_model = chosen_model
        last_error: Optional[Exception] = None
        for model_name in attempt_models:
            try:
                llm_text = _run_ollama_summary(
                    base_url=str(feedback["base_url"]),
                    model=model_name,
                    prompt=prompt,
                    timeout_sec=int(feedback["attempt_timeout_sec"]),
                    max_chars=int(feedback["max_chars"]),
                )
                used_model = model_name
                break
            except Exception as e:
                feedback["attempt_errors"][model_name] = str(e)
                last_error = e
                continue
        if not llm_text:
            if last_error is None:
                raise RuntimeError("ollama generate failed without details")
            raise last_error
        if _is_low_quality_llm_summary(llm_text):
            llm_text = _build_fallback_daily_reflection_summary(
                day8=day8,
                goal_jpy=goal_jpy,
                daily_review=daily_review,
                reflection=reflection,
                shadow_review=shadow_review,
            )
            feedback["reason"] = "ok_with_fallback"
        feedback["used"] = True
        feedback["model"] = used_model
        feedback["summary"] = llm_text
        feedback["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if feedback.get("reason") in ("", "tags_fetch_failed", "tags_fetch_failed_but_try_generate", "generate_failed"):
            feedback["reason"] = "ok"
        feedback["error"] = ""
    except Exception as e:
        feedback["error"] = str(e)
        if not feedback.get("reason"):
            feedback["reason"] = "generate_failed"
        fallback_text = _build_fallback_daily_reflection_summary(
            day8=day8,
            goal_jpy=goal_jpy,
            daily_review=daily_review,
            reflection=reflection,
            shadow_review=shadow_review,
        )
        feedback["summary"] = fallback_text
        feedback["fallback_used"] = True
        if feedback.get("reason") == "generate_failed":
            feedback["reason"] = "generate_failed_fallback"
    return feedback


def _reflection_command_preview(day8: str) -> str:
    return f"python3 tools/apply_daily_reflection.py {day8}"


def _reflection_command_apply(day8: str) -> str:
    return f"python3 tools/apply_daily_reflection.py {day8} --apply-control"


def _send_event(
    *,
    title: str,
    text: str,
    payload: Dict[str, Any],
    sec: Dict[str, Any],
    dry_run: bool,
    tags: str = "",
    priority: str = "",
) -> Tuple[bool, str]:
    ntfy_url = str(sec.get("ntfy_topic_url", "")).strip()
    ntfy_token = str(sec.get("ntfy_bearer_token", "")).strip()

    webhook_url = str(sec.get("trade_notify_webhook_url", "")).strip()
    webhook_token = str(sec.get("trade_notify_bearer_token", "")).strip()
    if not webhook_url:
        webhook_url = str(sec.get("login_notify_webhook_url", "")).strip()
        webhook_token = str(sec.get("login_notify_bearer_token", "")).strip()

    enabled_default = bool(ntfy_url or webhook_url)
    enabled = _safe_bool(sec.get("trade_notify_enabled", enabled_default), enabled_default)
    if not enabled:
        return True, "disabled"

    if dry_run:
        return True, "dry_run"

    results: List[Tuple[bool, str, str]] = []

    if ntfy_url:
        title_header = _latin1_safe_header_value(title, "Ouroboros Notification")
        event_code = _normalize_notification_event_code(payload.get("event"))
        event_level = _notification_level_for_event(event_code)
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Title": title_header,
            "Tags": tags_for_level(event_level, tags if tags else "money,chart_with_upwards_trend"),
        }
        eff_priority = priority if priority else (
            "high" if event_code == "daily_goal_report" else priority_for_level(event_level)
        )
        if eff_priority:
            headers["Priority"] = eff_priority
        if ntfy_token:
            headers["Authorization"] = f"Bearer {ntfy_token}"
        ok, msg = _http_post(ntfy_url, text.encode("utf-8"), headers)
        results.append((ok, "ntfy", msg))

    if webhook_url:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if webhook_token:
            headers["Authorization"] = f"Bearer {webhook_token}"
        webhook_payload = dict(payload)
        event_code = _normalize_notification_event_code(webhook_payload.get("event"))
        webhook_payload.setdefault("event_code", event_code)
        webhook_payload.setdefault("event_level", _notification_level_for_event(event_code))
        body = json.dumps(webhook_payload, ensure_ascii=False).encode("utf-8")
        ok, msg = _http_post(webhook_url, body, headers)
        results.append((ok, "webhook", msg))

    if not results:
        return True, "no_target"

    ok_all = all(x[0] for x in results)
    detail = ", ".join([f"{name}:{msg}" for _, name, msg in results])
    return ok_all, detail


def _normalize_notification_event_code(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return "unknown"
    raw = re.sub(r"[^a-z0-9_]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw or "unknown"


def _notification_level_for_event(event_code: Any) -> str:
    code = _normalize_notification_event_code(event_code)
    if code in {"daily_goal_report", "market_phase_changed"}:
        return LEVEL_INFO
    if code in {
        "drift_state_changed",
        "runner_state_changed",
        "dashboard_state_changed",
        "ngrok_state_changed",
        "trade_enabled_reenabled",
        "risk_stop_changed",
        "streak_stop_on",
        "no_trade_alert",
    }:
        return LEVEL_WARN
    if code in {"loss_streak_alert", "daily_loss_alert", "dd_alert"}:
        return LEVEL_CRITICAL
    return LEVEL_WARN


def _latest_trade_log(logs_dir: Path) -> Optional[Path]:
    cands = sorted(logs_dir.glob("trade_log_*.csv"))
    if not cands:
        return None
    return cands[-1]


def _read_csv_rows(path: Path) -> List[Dict[str, Any]]:
    try:
        txt = path.read_text(encoding="utf-8")
    except Exception:
        try:
            txt = path.read_text(encoding="utf-8-sig")
        except Exception:
            return []
    try:
        return list(csv.DictReader(txt.splitlines()))
    except Exception:
        return []


def _latest_trade_event_ts(logs_dir: Path) -> Optional[str]:
    lf = _latest_trade_log(logs_dir)
    if lf is None:
        return None
    rows = _read_csv_rows(lf)
    for r in reversed(rows):
        res = str(r.get("result", "")).strip()
        if res == "PAPER" or res.startswith("PAPER_EXIT_"):
            t = str(r.get("time", "")).strip()
            if _parse_time(t) is not None:
                return t
    return None


def _load_state_json_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return {}


def _extract_expectancy_ref_pct(state: Dict[str, Any]) -> Optional[float]:
    auto = state.get("_ai_auto_train")
    if not isinstance(auto, dict):
        return None
    for k in (
        "backtest_gate_eval_expectancy",
        "auto_train_backtest_gate_expectancy",
        "train_backtest_gate_expectancy_min",
    ):
        v = _safe_float(auto.get(k))
        if v is not None:
            return float(v)
    return None


def _set_control_value(control_path: Path, key: str, value: str) -> Tuple[bool, str, Optional[str]]:
    if not control_path.exists():
        return False, f"control csv not found: {control_path}", None
    try:
        with control_path.open("r", encoding="utf-8", newline="") as f:
            rows = [list(r) for r in csv.reader(f)]
    except Exception as e:
        return False, f"control read failed: {e}", None

    found = False
    before: Optional[str] = None
    for row in rows:
        if not row:
            continue
        k = str(row[0]).strip()
        if k != key:
            continue
        found = True
        before = str(row[1]) if len(row) >= 2 else ""
        if len(row) >= 2:
            row[1] = str(value)
        else:
            row.append(str(value))
        break
    if not found:
        rows.append([str(key), str(value)])
        before = None

    try:
        with control_path.open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(rows)
        return True, "ok", before
    except Exception as e:
        return False, f"control write failed: {e}", before


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _runner_alive(run_lock_dir: Path) -> bool:
    lock = run_lock_dir / "lockinfo.txt"
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


def _risk_stop_state(state_json: Path) -> bool:
    if not state_json.exists():
        return False
    try:
        obj = json.loads(state_json.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    return _safe_bool(obj.get("_risk_stop", False), False)


def _drift_watch_state(state_json: Path) -> Dict[str, Any]:
    out = {
        "status": "",
        "recommended_stop_hours": [],
        "hour_blocked_by_drift": False,
        "frozen_by_drift": False,
        "trade_paused_by_drift": False,
    }
    if not state_json.exists():
        return out
    try:
        obj = json.loads(state_json.read_text(encoding="utf-8"))
    except Exception:
        return out
    if not isinstance(obj, dict):
        return out
    d = obj.get("_drift_watch", {})
    if not isinstance(d, dict):
        return out

    status = str(d.get("status", "")).strip().upper()
    hsa = d.get("hourly_stop_analysis", {})
    rec = []
    if isinstance(hsa, dict):
        raw = hsa.get("recommended_stop_hours", [])
        if isinstance(raw, list):
            for x in raw:
                iv = _safe_int(x, -1)
                if 0 <= iv <= 23:
                    rec.append(int(iv))
    rec = sorted(set(rec))

    out["status"] = status
    out["recommended_stop_hours"] = rec
    out["hour_blocked_by_drift"] = _safe_bool(d.get("hour_blocked_by_drift"), False)
    out["frozen_by_drift"] = _safe_bool(d.get("frozen_by_drift"), False)
    out["trade_paused_by_drift"] = _safe_bool(d.get("trade_paused_by_drift"), False)
    out["resume_outlook"] = build_drift_resume_snapshot(d)
    return out


def _build_trade_event(
    row: Dict[str, Any],
    host: str,
    *,
    expectancy_ref_pct: Optional[float] = None,
) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    result = str(row.get("result", "")).strip()
    if not result:
        return None

    if result == "PAPER":
        ev = "trade_entry"
    elif result.startswith("PAPER_EXIT"):
        ev = "trade_exit"
    else:
        return None

    t = str(row.get("time", "")).strip() or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    side = str(row.get("side", "")).strip().upper()
    pos_id = str(row.get("pos_id", "")).strip()
    price = _safe_float(row.get("price"))
    ltp = _safe_float(row.get("ltp"))
    size = _safe_float(row.get("size"))
    note = str(row.get("note", "")).strip()
    exec_mode = "LIVE" if "exec=LIVE" in note else "PAPER"
    title = "Ouroboros 取引通知"
    payload: Dict[str, Any] = {
        "event": ev,
        "time": t,
        "result": result,
        "exec_mode": exec_mode,
        "side": side,
        "size": size,
        "price": price,
        "ltp": ltp,
        "pos_id": pos_id,
        "host": host,
    }

    event_label = "新規エントリー" if ev == "trade_entry" else "決済"
    lines = [
        title,
        f"イベント={event_label}",
        f"時刻={t}",
        f"結果={result}",
        f"実行モード={exec_mode}",
        f"売買={side or '-'}",
        f"数量={size if size is not None else '-'}",
        f"価格={price if price is not None else '-'}",
        f"LTP={ltp if ltp is not None else '-'}",
    ]

    if ev == "trade_exit":
        metrics = _calc_trade_metrics(side=side, entry_price=price, exit_price=ltp, size=size)
        ret_pct = metrics.get("ret_pct")
        pnl_jpy = metrics.get("pnl_jpy")
        quality, quality_reason = _evaluate_trade_quality(result=result, ret_pct=ret_pct)
        quality_label_ja = _evaluation_label_ja(quality)
        reason_ja = _quality_reason_ja(quality_reason)
        evaluation_comment = reason_ja
        lines.extend(
            [
                f"損益率(%)={f'{ret_pct:.4f}' if ret_pct is not None else '-'}",
                f"損益(JPY)={f'{pnl_jpy:.2f}' if pnl_jpy is not None else '-'}",
                f"評価={quality}（{quality_label_ja}）",
                f"評価理由={quality_reason}",
            ]
        )
        payload["ret_pct"] = ret_pct
        payload["pnl_jpy"] = pnl_jpy
        payload["evaluation"] = quality
        payload["evaluation_label_ja"] = quality_label_ja
        payload["evaluation_reason"] = quality_reason
        payload["evaluation_comment_ja"] = evaluation_comment
        if ret_pct is not None and expectancy_ref_pct is not None:
            vs_exp, exp_delta = _evaluate_vs_expectancy(float(ret_pct), float(expectancy_ref_pct))
            exp_comment_ja = _expectancy_comment_ja(vs_exp, exp_delta)
            evaluation_comment = f"{reason_ja} {exp_comment_ja}"
            lines.extend(
                [
                    f"期待値基準(%)={expectancy_ref_pct:.4f}",
                    f"期待値差分(%)={exp_delta:.4f}",
                    f"期待値比較={vs_exp}",
                ]
            )
            payload["expectancy_ref_pct"] = float(expectancy_ref_pct)
            payload["expectancy_delta_pct"] = float(exp_delta)
            payload["vs_expectancy"] = str(vs_exp)
            payload["expectancy_comment_ja"] = exp_comment_ja
        lines.append(f"判定コメント={evaluation_comment}")
        payload["evaluation_comment_ja"] = evaluation_comment
        title = f"Ouroboros 決済通知 [{quality}]"
        lines[0] = title

    lines.extend(
        [
            f"ポジションID={pos_id or '-'}",
            f"ホスト={host}",
        ]
    )
    text = "\n".join(lines)
    return title, text, payload


def main() -> int:
    ap = argparse.ArgumentParser(description="Send trade/risk/process events to ntfy/webhook from trade logs.")
    ap.add_argument("--logs-dir", default=str(LOGS_DIR_DEFAULT))
    ap.add_argument("--cursor", default=str(CURSOR_PATH_DEFAULT))
    ap.add_argument("--secrets", default=str(SECRETS_PATH_DEFAULT))
    ap.add_argument("--state-json", default=str(STATE_JSON_DEFAULT))
    ap.add_argument("--run-lock-dir", default=str(RUN_LOCK_DIR_DEFAULT))
    ap.add_argument("--control-csv", default=str(CONTROL_CSV_DEFAULT))
    ap.add_argument("--daily-report-out-dir", default=str(DAILY_REPORT_OUT_DIR_DEFAULT))
    ap.add_argument(
        "--daily-report-snapshot-dir",
        default=str(ROOT / ".local_llm" / "vm_snapshot" / "latest"),
        help="Optional read-only VM snapshot root or logs dir used only for daily reflection fallback.",
    )
    ap.add_argument("--bootstrap-send", action="store_true", help="Send existing rows on first run.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    logs_dir = Path(args.logs_dir).expanduser().resolve()
    cursor_path = Path(args.cursor).expanduser().resolve()
    secrets_path = Path(args.secrets).expanduser().resolve()
    state_json = Path(args.state_json).expanduser().resolve()
    run_lock_dir = Path(args.run_lock_dir).expanduser().resolve()
    control_csv_path = Path(args.control_csv).expanduser().resolve()
    daily_report_out_dir = Path(args.daily_report_out_dir).expanduser().resolve()
    daily_report_snapshot_dir = Path(str(args.daily_report_snapshot_dir)).expanduser()

    sec = _load_toml_section(secrets_path, "dashboard_security")
    host = socket.gethostname()
    now = datetime.now()
    state_obj = _load_state_json_dict(state_json)
    expectancy_ref_pct = _extract_expectancy_ref_pct(state_obj)

    # ---- alert settings ----
    loss_streak_enabled = _safe_bool(sec.get("trade_notify_loss_streak_enabled"), True)
    loss_streak_threshold = max(2, _safe_int(sec.get("trade_notify_loss_streak_threshold"), 3))
    daily_loss_enabled = _safe_bool(sec.get("trade_notify_daily_loss_enabled"), True)
    daily_loss_limit_pct_raw = _safe_float(sec.get("trade_notify_daily_loss_limit_pct"))
    if daily_loss_limit_pct_raw is not None:
        daily_loss_limit_pct = abs(float(daily_loss_limit_pct_raw))
    else:
        # Fall back to CONTROL.csv value (e.g. -2.0 → 2.0)
        _ctrl_early = _read_control_values(control_csv_path)
        _ctrl_raw = _safe_float(_ctrl_early.get("daily_loss_limit_pct"))
        daily_loss_limit_pct = abs(float(_ctrl_raw)) if _ctrl_raw is not None else 2.0
    auto_disable_trade_enabled = _safe_bool(sec.get("trade_notify_auto_disable_trade_enabled"), False)
    daily_goal_report_enabled = _safe_bool(sec.get("trade_notify_daily_goal_report_enabled"), True)
    daily_goal_jpy_raw = _safe_float(sec.get("trade_notify_daily_goal_jpy"))
    daily_goal_jpy = max(0.0, float(daily_goal_jpy_raw) if daily_goal_jpy_raw is not None else 100.0)
    daily_goal_report_hour = max(0, min(23, _safe_int(sec.get("trade_notify_daily_goal_report_hour"), 21)))
    daily_goal_snapshot_fallback_enabled = _safe_bool(
        sec.get("trade_notify_daily_goal_snapshot_fallback_enabled"),
        True,
    )

    no_trade_enabled = _safe_bool(sec.get("trade_notify_no_trade_enabled"), True)
    no_trade_minutes = max(30, _safe_int(sec.get("trade_notify_no_trade_minutes"), 60))

    service_watch_enabled = _safe_bool(sec.get("trade_notify_service_watch_enabled"), True)
    watch_dashboard = _safe_bool(sec.get("trade_notify_watch_dashboard"), True)
    watch_ngrok = _safe_bool(sec.get("trade_notify_watch_ngrok"), False)
    drift_watch_notify_enabled = _safe_bool(sec.get("trade_notify_drift_watch_enabled"), True)
    market_phase_notify_enabled = _safe_bool(sec.get("trade_notify_market_phase_enabled"), True)
    notify_min_interval_sec = max(0, _safe_int(sec.get("trade_notify_min_interval_sec"), 180))
    alert_min_interval_sec = max(0, _safe_int(sec.get("trade_notify_alert_min_interval_sec"), notify_min_interval_sec))
    state_change_min_interval_sec = max(
        0,
        _safe_int(sec.get("trade_notify_state_change_min_interval_sec"), notify_min_interval_sec),
    )

    cursor = _read_json(
        cursor_path,
        {
            "last_file": "",
            "last_line": 0,
            "risk_stop": None,
            "runner_alive": None,
            "dashboard_alive": None,
            "ngrok_alive": None,
            "drift_status": "",
            "drift_stop_hours_csv": "",
            "drift_hour_blocked_by_drift": False,
            "drift_resume_outlook_summary": "",
            "market_phase": "",
            "market_phase_changed_at_jst": "",
            "loss_streak": 0,
            "loss_streak_alert_level": 0,
            "daily_day8": "",
            "daily_ret_pct_sum": 0.0,
            "daily_pnl_jpy_sum": 0.0,
            "daily_closed_count": 0,
            "streak_stop": None,
            "daily_loss_alerted_day8": "",
            "dd_alert_alerted_day8": "",
            "daily_trade_disabled_day8": "",
            "trade_enabled_disabled_reason": "",
            "trade_enabled_disabled_at": "",
            "trade_enabled_disabled_exec_mode": "",
            "trade_enabled_disabled_pos_id": "",
            "trade_enabled_reenabled_notified_at": "",
            "daily_goal_report_sent_day8": "",
            "daily_goal_report_handled_day8": "",
            "last_trade_event_ts": "",
            "no_trade_alerted": False,
            "runner_seen_day8": "",
            "notify_last_sent_ts": {},
            "updated_at": "",
        },
    )

    def _is_cooldown_blocked(event_key: str, cooldown_sec: int, label: str) -> bool:
        rem = _cooldown_remaining_sec(cursor, event_key, cooldown_sec)
        if rem > 0:
            print(f"[SKIP] {label} cooldown remain={rem:.1f}s")
            return True
        return False

    def _mark_sent_if_effective(event_key: str, ok: bool, msg: str) -> None:
        if bool(args.dry_run):
            return
        if not bool(ok):
            return
        if not _notify_target_effective(msg):
            return
        _cooldown_mark_sent(cursor, event_key)

    sent = 0

    if logs_dir.exists():
        if not str(cursor.get("last_trade_event_ts", "")).strip():
            ts0 = _latest_trade_event_ts(logs_dir)
            if ts0:
                cursor["last_trade_event_ts"] = str(ts0)
        lf = _latest_trade_log(logs_dir)
        if lf is not None:
            rows = _read_csv_rows(lf)
            prev_file = str(cursor.get("last_file", ""))
            prev_line = int(cursor.get("last_line", 0) or 0)

            if prev_file == str(lf):
                start = max(0, min(prev_line, len(rows)))
            else:
                start = 0 if bool(args.bootstrap_send) else len(rows)

            for r in rows[start:]:
                ev = _build_trade_event(r, host, expectancy_ref_pct=expectancy_ref_pct)
                if not ev:
                    continue
                title, text, payload = ev
                ok, msg = _send_event(title=title, text=text, payload=payload, sec=sec, dry_run=bool(args.dry_run))
                tag = "OK" if ok else "FAIL"
                print(f"[{tag}] trade event: {payload.get('event')} {payload.get('result')} pos_id={payload.get('pos_id','-')} ({msg})")
                sent += 1

                # last trade timestamp / no-trade reset
                ev_ts = str(payload.get("time", "")).strip()
                if ev_ts:
                    cursor["last_trade_event_ts"] = ev_ts
                cursor["no_trade_alerted"] = False

                if str(payload.get("event")) != "trade_exit":
                    continue

                daily_stats = _accumulate_daily_trade_exit(cursor, payload, now_dt=now)
                day8 = str(daily_stats.get("day8", ""))
                ret_pct = _safe_float(daily_stats.get("ret_pct"))
                if ret_pct is None:
                    continue

                daily_sum = float(daily_stats.get("daily_ret_pct_sum") or 0.0)

                if float(ret_pct) < 0:
                    streak = _safe_int(cursor.get("loss_streak"), 0) + 1
                else:
                    streak = 0
                    cursor["loss_streak_alert_level"] = 0
                cursor["loss_streak"] = int(streak)

                if loss_streak_enabled and streak >= loss_streak_threshold:
                    alerted_lv = _safe_int(cursor.get("loss_streak_alert_level"), 0)
                    if streak > alerted_lv:
                        if _is_cooldown_blocked("loss_streak_alert", alert_min_interval_sec, "loss_streak_alert"):
                            cursor["loss_streak_alert_level"] = int(streak)
                        else:
                            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            t2 = "Ouroboros 連敗アラート"
                            x2 = (
                                f"{t2}\n"
                                f"時刻={ts}\n"
                                f"連敗数={streak}\n"
                                f"しきい値={loss_streak_threshold}\n"
                                f"直近損益率(%)={ret_pct:.4f}\n"
                                f"当日累積損益率(%)={daily_sum:.4f}\n"
                                f"ポジションID={payload.get('pos_id','-')}\n"
                                f"ホスト={host}"
                            )
                            p2 = {
                                "event": "loss_streak_alert",
                                "time": ts,
                                "streak": int(streak),
                                "threshold": int(loss_streak_threshold),
                                "last_ret_pct": float(ret_pct),
                                "daily_ret_pct_sum": float(daily_sum),
                                "pos_id": payload.get("pos_id", ""),
                                "host": host,
                            }
                            ok2, msg2 = _send_event(title=t2, text=x2, payload=p2, sec=sec, dry_run=bool(args.dry_run))
                            print(f"[{'OK' if ok2 else 'FAIL'}] loss_streak_alert streak={streak} ({msg2})")
                            cursor["loss_streak_alert_level"] = int(streak)
                            _mark_sent_if_effective("loss_streak_alert", ok2, msg2)
                            sent += 1

                if daily_loss_enabled and daily_loss_limit_pct > 0:
                    crossed = float(daily_sum) <= -float(daily_loss_limit_pct)
                    already_alerted = str(cursor.get("daily_loss_alerted_day8", "")) == day8
                    if crossed and not already_alerted:
                        if _is_cooldown_blocked("daily_loss_alert", alert_min_interval_sec, "daily_loss_alert"):
                            pass
                        else:
                            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            t3 = "Ouroboros 日次損失アラート"
                            x3 = (
                                f"{t3}\n"
                                f"時刻={ts}\n"
                                f"日付={day8}\n"
                                f"当日累積損益率(%)={daily_sum:.4f}\n"
                                f"下限しきい値(%)={-daily_loss_limit_pct:.4f}\n"
                                f"ポジションID={payload.get('pos_id','-')}\n"
                                f"ホスト={host}"
                            )
                            p3 = {
                                "event": "daily_loss_alert",
                                "time": ts,
                                "day8": day8,
                                "daily_ret_pct_sum": float(daily_sum),
                                "daily_loss_limit_pct": -float(daily_loss_limit_pct),
                                "pos_id": payload.get("pos_id", ""),
                                "host": host,
                            }
                            ok3, msg3 = _send_event(
                                title=t3, text=x3, payload=p3, sec=sec, dry_run=bool(args.dry_run),
                                tags="warning", priority="high",
                            )
                            print(f"[{'OK' if ok3 else 'FAIL'}] daily_loss_alert day8={day8} ({msg3})")
                            cursor["daily_loss_alerted_day8"] = day8
                            _mark_sent_if_effective("daily_loss_alert", ok3, msg3)
                            sent += 1

                            if auto_disable_trade_enabled and str(cursor.get("daily_trade_disabled_day8", "")) != day8:
                                if not _is_cooldown_blocked(
                                    "auto_disable_trade_enabled",
                                    alert_min_interval_sec,
                                    "auto_disable_trade_enabled",
                                ):
                                    okc, msgc, before_v = _set_control_value(control_csv_path, "trade_enabled", "0")
                                    t4 = "Ouroboros 自動売買停止"
                                    x4 = (
                                        f"{t4}\n"
                                        f"時刻={ts}\n"
                                        f"日付={day8}\n"
                                        f"理由=daily_loss_breach\n"
                                        f"trade_enabled(変更前)={before_v if before_v is not None else '-'}\n"
                                        f"trade_enabled(変更後)=0\n"
                                        f"CONTROL.csv={control_csv_path}\n"
                                        f"実行結果={msgc}\n"
                                        f"ホスト={host}"
                                    )
                                    p4 = {
                                        "event": "auto_disable_trade_enabled",
                                        "time": ts,
                                        "day8": day8,
                                        "reason": "daily_loss_breach",
                                        "trade_enabled_before": before_v,
                                        "trade_enabled_after": "0",
                                        "control_path": str(control_csv_path),
                                        "ok": bool(okc),
                                        "message": str(msgc),
                                        "host": host,
                                    }
                                    ok4, msg4 = _send_event(
                                        title=t4,
                                        text=x4,
                                        payload=p4,
                                        sec=sec,
                                        dry_run=bool(args.dry_run),
                                    )
                                    print(f"[{'OK' if ok4 else 'FAIL'}] auto_disable_trade_enabled ok={okc} ({msg4})")
                                    if okc:
                                        _record_trade_enabled_auto_disabled(
                                            cursor,
                                            day8=day8,
                                            ts=ts,
                                            reason="daily_loss_breach",
                                            payload=payload,
                                        )
                                    _mark_sent_if_effective("auto_disable_trade_enabled", ok4, msg4)
                                    sent += 1

            cursor["last_file"] = str(lf)
            cursor["last_line"] = len(rows)

    if no_trade_enabled:
        last_trade_ts = str(cursor.get("last_trade_event_ts", "")).strip()
        ldt = _parse_time(last_trade_ts)
        if ldt is not None:
            idle_min = max(0.0, (now - ldt).total_seconds() / 60.0)
            if idle_min >= float(no_trade_minutes) and not _safe_bool(cursor.get("no_trade_alerted"), False):
                if not _is_cooldown_blocked("no_trade_alert", alert_min_interval_sec, "no_trade_alert"):
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    t5 = "Ouroboros ノートレードアラート"
                    x5 = (
                        f"{t5}\n"
                        f"時刻={ts}\n"
                        f"最終取引時刻={last_trade_ts}\n"
                        f"無取引時間(分)={idle_min:.1f}\n"
                        f"しきい値(分)={no_trade_minutes}\n"
                        f"ホスト={host}"
                    )
                    p5 = {
                        "event": "no_trade_alert",
                        "time": ts,
                        "last_trade_time": last_trade_ts,
                        "idle_minutes": round(float(idle_min), 3),
                        "threshold_minutes": int(no_trade_minutes),
                        "host": host,
                    }
                    ok5, msg5 = _send_event(title=t5, text=x5, payload=p5, sec=sec, dry_run=bool(args.dry_run))
                    print(f"[{'OK' if ok5 else 'FAIL'}] no_trade_alert idle_min={idle_min:.1f} ({msg5})")
                    cursor["no_trade_alerted"] = True
                    _mark_sent_if_effective("no_trade_alert", ok5, msg5)
                    sent += 1

    phase_obj = state_obj.get("_market_phase", {}) if isinstance(state_obj.get("_market_phase"), dict) else {}
    phase_now = str(phase_obj.get("phase", "") or "").strip().upper()
    phase_changed_at = str(phase_obj.get("changed_at_jst", "") or "").strip()
    phase_transition = str(phase_obj.get("transition", "") or "").strip()
    phase_prev_cursor = str(cursor.get("market_phase", "") or "").strip().upper()
    phase_changed_prev = str(cursor.get("market_phase_changed_at_jst", "") or "").strip()
    if phase_now in {"A", "B", "C"}:
        if not phase_prev_cursor:
            cursor["market_phase"] = phase_now
            cursor["market_phase_changed_at_jst"] = phase_changed_at
        elif (
            market_phase_notify_enabled
            and phase_transition
            and phase_changed_at
            and (phase_now != phase_prev_cursor or phase_changed_at != phase_changed_prev)
        ):
            phase_event_key = "market_phase_changed"
            if not _is_cooldown_blocked(phase_event_key, state_change_min_interval_sec, "market_phase_changed"):
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                is_resume = phase_prev_cursor == "B" and phase_now in ("A", "C")
                event_name = "market_phase_resume" if is_resume else "market_phase_changed"
                title = "Ouroboros 市場復帰 エントリー再開可能" if is_resume else "Ouroboros 局面転換"
                resume_line = "エントリー再開可能 (phase B終了)\n" if is_resume else ""
                text = (
                    f"{title}\n"
                    f"時刻={ts}\n"
                    f"転換={phase_transition}\n"
                    f"現在局面={phase_now}\n"
                    f"理由={str(phase_obj.get('phase_reason', '-') or '-')}\n"
                    f"勢い={str(phase_obj.get('momentum', '-') or '-')}\n"
                    f"検出時刻={phase_changed_at}\n"
                    f"{resume_line}"
                    f"ホスト={host}"
                )
                payload = {
                    "event": event_name,
                    "time": ts,
                    "phase": phase_now,
                    "transition": phase_transition,
                    "phase_reason": str(phase_obj.get("phase_reason", "") or ""),
                    "momentum": str(phase_obj.get("momentum", "") or ""),
                    "changed_at_jst": phase_changed_at,
                    "host": host,
                }
                if is_resume:
                    ok, msg = _send_event(
                        title=title, text=text, payload=payload, sec=sec, dry_run=bool(args.dry_run),
                        tags="green_circle", priority="high",
                    )
                else:
                    ok, msg = _send_event(title=title, text=text, payload=payload, sec=sec, dry_run=bool(args.dry_run))
                print(f"[{'OK' if ok else 'FAIL'}] {event_name} {phase_transition} ({msg})")
                _mark_sent_if_effective(phase_event_key, ok, msg)
                sent += 1
            cursor["market_phase"] = phase_now
            cursor["market_phase_changed_at_jst"] = phase_changed_at
        else:
            cursor["market_phase"] = phase_now
            cursor["market_phase_changed_at_jst"] = phase_changed_at

    risk_now = _risk_stop_state(state_json)
    risk_prev = cursor.get("risk_stop", None)
    if risk_prev is None:
        cursor["risk_stop"] = bool(risk_now)
    elif bool(risk_prev) != bool(risk_now):
        risk_event_key = _state_change_event_key("risk_stop_changed", bool(risk_now))
        if not _is_cooldown_blocked(risk_event_key, state_change_min_interval_sec, "risk_stop_changed"):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            title = "Ouroboros リスク停止状態の変更"
            text = (
                f"{title}\n"
                f"時刻={ts}\n"
                f"risk_stop={'ON' if risk_now else 'OFF'}\n"
                f"ホスト={host}"
            )
            payload = {
                "event": "risk_stop_changed",
                "time": ts,
                "risk_stop": bool(risk_now),
                "host": host,
            }
            ok, msg = _send_event(title=title, text=text, payload=payload, sec=sec, dry_run=bool(args.dry_run))
            tag = "OK" if ok else "FAIL"
            print(f"[{tag}] risk_stop_changed -> {risk_now} ({msg})")
            _mark_sent_if_effective(risk_event_key, ok, msg)
            sent += 1
        cursor["risk_stop"] = bool(risk_now)

    # streak_stop: notify only on OFF→ON transition (3連敗停止)
    streak_now = _safe_bool(state_obj.get("_streak_stop", False), False) if isinstance(state_obj, dict) else False
    streak_prev = cursor.get("streak_stop", None)
    if streak_prev is None:
        cursor["streak_stop"] = bool(streak_now)
    elif not bool(streak_prev) and bool(streak_now):
        # OFF → ON: immediate alert
        streak_event_key = _state_change_event_key("streak_stop_on", True)
        if not _is_cooldown_blocked(streak_event_key, state_change_min_interval_sec, "streak_stop_on"):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            max_losses = int(_safe_int(_read_control_values(control_csv_path).get("streak_stop_max_losses"), 3))
            title = "Ouroboros 連敗ストップ発動"
            text = (
                f"⛔ 連敗ストップ発動\n"
                f"時刻={ts}\n"
                f"{max_losses}連敗を検知し、本日のエントリーを停止しました。\n"
                f"ホスト={host}"
            )
            payload = {
                "event": "streak_stop_on",
                "time": ts,
                "streak_stop": True,
                "streak_stop_max_losses": max_losses,
                "host": host,
            }
            ok, msg = _send_event(
                title=title, text=text, payload=payload, sec=sec, dry_run=bool(args.dry_run),
                tags="rotating_light", priority="high",
            )
            tag = "OK" if ok else "FAIL"
            print(f"[{tag}] streak_stop_on ({msg})")
            _mark_sent_if_effective(streak_event_key, ok, msg)
            sent += 1
        cursor["streak_stop"] = True
    elif bool(streak_prev) and not bool(streak_now):
        # ON → OFF: reset cursor (no notification needed — morning guard restores)
        cursor["streak_stop"] = False

    runner_now = _runner_alive(run_lock_dir)
    today8 = _day8(now)
    if runner_now:
        cursor["runner_seen_day8"] = today8
    runner_prev = cursor.get("runner_alive", None)
    if runner_prev is None:
        cursor["runner_alive"] = bool(runner_now)
    elif bool(runner_prev) != bool(runner_now):
        runner_event_key = _state_change_event_key("runner_state_changed", bool(runner_now))
        if not _is_cooldown_blocked(runner_event_key, state_change_min_interval_sec, "runner_state_changed"):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            title = "Ouroboros ランナー状態の変更"
            text = (
                f"{title}\n"
                f"時刻={ts}\n"
                f"runner_alive={'ON' if runner_now else 'OFF'}\n"
                f"ホスト={host}"
            )
            payload = {
                "event": "runner_state_changed",
                "time": ts,
                "runner_alive": bool(runner_now),
                "host": host,
            }
            ok, msg = _send_event(title=title, text=text, payload=payload, sec=sec, dry_run=bool(args.dry_run))
            tag = "OK" if ok else "FAIL"
            print(f"[{tag}] runner_state_changed -> {runner_now} ({msg})")
            _mark_sent_if_effective(runner_event_key, ok, msg)
            sent += 1
        cursor["runner_alive"] = bool(runner_now)

    if daily_goal_report_enabled:
        runner_seen_day8 = str(cursor.get("runner_seen_day8", "")).strip()
        sent_day8 = str(cursor.get("daily_goal_report_sent_day8", "")).strip()
        handled_day8 = str(cursor.get("daily_goal_report_handled_day8", "")).strip()
        sent_day8s = cursor.get("daily_goal_report_sent_day8s")
        cursor_day8 = str(cursor.get("daily_day8", "")).strip()
        current_day_review, current_report_logs_dir = _build_daily_trade_review_with_snapshot_fallback(
            primary_logs_dir=logs_dir,
            day8=today8,
            snapshot_dir=daily_report_snapshot_dir,
            enabled=daily_goal_snapshot_fallback_enabled,
        )
        if cursor_day8 and cursor_day8 != today8:
            cursor_day_review, cursor_report_logs_dir = _build_daily_trade_review_with_snapshot_fallback(
                primary_logs_dir=logs_dir,
                day8=cursor_day8,
                snapshot_dir=daily_report_snapshot_dir,
                enabled=daily_goal_snapshot_fallback_enabled,
            )
        else:
            cursor_day_review = current_day_review
            cursor_report_logs_dir = current_report_logs_dir
        report_day8, close_reason = _pick_daily_goal_report_day(
            today8=today8,
            sent_day8=sent_day8,
            handled_day8=handled_day8,
            sent_day8s=sent_day8s,
            now_hour=int(now.hour),
            report_hour=daily_goal_report_hour,
            runner_now=bool(runner_now),
            runner_seen_day8=runner_seen_day8,
            cursor_day8=cursor_day8,
            current_day_review=current_day_review,
            cursor_day_review=cursor_day_review,
        )
        if report_day8:
            daily_review = current_day_review if report_day8 == today8 else cursor_day_review
            report_logs_dir = current_report_logs_dir if report_day8 == today8 else cursor_report_logs_dir
            shadow_review = _build_shadow_day_snapshot(report_logs_dir, report_day8)
            prev_shadow_day8 = _shift_day8(report_day8, -1)
            prev_shadow_review = _build_shadow_day_snapshot(report_logs_dir, prev_shadow_day8) if prev_shadow_day8 else {}
            shadow_review["prev_exit_technical_n"] = int(_safe_int(prev_shadow_review.get("exit_technical_n"), 0))
            shadow_review["exit_technical_delta"] = int(
                _safe_int(shadow_review.get("exit_technical_n"), 0)
                - _safe_int(prev_shadow_review.get("exit_technical_n"), 0)
            )
            shadow_review["prev_observe_trend_strength_weak_n"] = int(
                _safe_int(prev_shadow_review.get("observe_trend_strength_weak_n"), 0)
            )
            shadow_review["observe_trend_strength_weak_delta"] = int(
                _safe_int(shadow_review.get("observe_trend_strength_weak_n"), 0)
                - _safe_int(prev_shadow_review.get("observe_trend_strength_weak_n"), 0)
            )
            shadow_review["prev_observe_ai_block_htf60_countertrend_n"] = int(
                _safe_int(prev_shadow_review.get("observe_ai_block_htf60_countertrend_n"), 0)
            )
            shadow_review["observe_ai_block_htf60_countertrend_delta"] = int(
                _safe_int(shadow_review.get("observe_ai_block_htf60_countertrend_n"), 0)
                - _safe_int(prev_shadow_review.get("observe_ai_block_htf60_countertrend_n"), 0)
            )
            shadow_review["prev_observe_ai_block_htf15_60_conflict_n"] = int(
                _safe_int(prev_shadow_review.get("observe_ai_block_htf15_60_conflict_n"), 0)
            )
            shadow_review["observe_ai_block_htf15_60_conflict_delta"] = int(
                _safe_int(shadow_review.get("observe_ai_block_htf15_60_conflict_n"), 0)
                - _safe_int(prev_shadow_review.get("observe_ai_block_htf15_60_conflict_n"), 0)
            )
            shadow_review["prev_weak_progress_exit_n"] = int(
                _safe_int(prev_shadow_review.get("weak_progress_exit_n"), 0)
            )
            shadow_review["weak_progress_exit_delta"] = int(
                _safe_int(shadow_review.get("weak_progress_exit_n"), 0)
                - _safe_int(prev_shadow_review.get("weak_progress_exit_n"), 0)
            )
            shadow_review["prev_progress_reversal_exit_n"] = int(
                _safe_int(prev_shadow_review.get("progress_reversal_exit_n"), 0)
            )
            shadow_review["progress_reversal_exit_delta"] = int(
                _safe_int(shadow_review.get("progress_reversal_exit_n"), 0)
                - _safe_int(prev_shadow_review.get("progress_reversal_exit_n"), 0)
            )
            shadow_review["prev_near_tp_giveback_exit_n"] = int(
                _safe_int(prev_shadow_review.get("near_tp_giveback_exit_n"), 0)
            )
            shadow_review["near_tp_giveback_exit_delta"] = int(
                _safe_int(shadow_review.get("near_tp_giveback_exit_n"), 0)
                - _safe_int(prev_shadow_review.get("near_tp_giveback_exit_n"), 0)
            )
            shadow_review["prev_progress_timeout_n"] = int(
                _safe_int(prev_shadow_review.get("progress_timeout_n"), 0)
            )
            shadow_review["progress_timeout_delta"] = int(
                _safe_int(shadow_review.get("progress_timeout_n"), 0)
                - _safe_int(prev_shadow_review.get("progress_timeout_n"), 0)
            )
            shadow_review["prev_no_follow_through_exit_n"] = int(
                _safe_int(prev_shadow_review.get("no_follow_through_exit_n"), 0)
            )
            shadow_review["no_follow_through_exit_delta"] = int(
                _safe_int(shadow_review.get("no_follow_through_exit_n"), 0)
                - _safe_int(prev_shadow_review.get("no_follow_through_exit_n"), 0)
            )
            shadow_review["prev_timeout_n"] = int(_safe_int(prev_shadow_review.get("timeout_n"), 0))
            shadow_review["prev_plain_timeout_n"] = int(
                _safe_int(prev_shadow_review.get("plain_timeout_n"), _safe_int(prev_shadow_review.get("timeout_n"), 0))
            )
            shadow_review["timeout_delta"] = int(
                _safe_int(shadow_review.get("plain_timeout_n"), _safe_int(shadow_review.get("timeout_n"), 0))
                - _safe_int(prev_shadow_review.get("plain_timeout_n"), _safe_int(prev_shadow_review.get("timeout_n"), 0))
            )
            control_values = _read_control_values(control_csv_path)
            reflection = _build_daily_reflection(
                daily_review=daily_review,
                state_obj=state_obj,
                control_values=control_values,
                goal_jpy=daily_goal_jpy,
                shadow_review=shadow_review,
            )
            auto_apply = _evaluate_daily_reflection_auto_apply(
                reflection=reflection,
                sec=sec,
            )
            llm_feedback = _generate_daily_reflection_llm_feedback(
                day8=report_day8,
                goal_jpy=daily_goal_jpy,
                daily_review=daily_review,
                reflection=reflection,
                shadow_review=shadow_review,
                sec=sec,
            )
            reflection["llm_feedback"] = llm_feedback
            reflection_report = _build_daily_reflection_report(
                report_dt=now,
                host=host,
                day8=report_day8,
                goal_jpy=daily_goal_jpy,
                daily_review=daily_review,
                reflection=reflection,
                shadow_review=shadow_review,
            )
            reflection_report["auto_approval"] = dict(auto_apply)
            reflection_report_path = daily_report_out_dir / f"daily_reflection_{report_day8}.json"
            if not bool(args.dry_run):
                _write_json(reflection_report_path, reflection_report)
            auto_apply_result = dict(auto_apply)
            if auto_apply.get("eligible") and not bool(args.dry_run):
                auto_apply_result = dict(
                    apply_daily_reflection_report(
                        reflection_path=reflection_report_path,
                        control_path=control_csv_path,
                        state_path=state_json,
                        approver=str(auto_apply.get("approver") or "notifier_auto"),
                        dry_run=bool(args.dry_run),
                        override_updates=dict(auto_apply.get("updates") or {}),
                        approval_status="auto_approved",
                        approval_mode="auto",
                        approval_note=str(auto_apply.get("reason") or "eligible"),
                    )
                )
                auto_apply_result.update(
                    {
                        "eligible": True,
                        "applied": not bool(args.dry_run),
                        "reason": "eligible",
                        "blocked_keys": list(auto_apply.get("blocked_keys") or []),
                        "approval_status": "auto_approved",
                    }
                )
            elif auto_apply.get("eligible"):
                auto_apply_result.update(
                    {
                        "applied": False,
                        "approval_status": "auto_approved",
                        "changed": {k: {"before": "", "after": v} for k, v in sorted(dict(auto_apply.get("updates") or {}).items())},
                        "approval": {
                            "status": "auto_approved",
                            "approved_by": str(auto_apply.get("approver") or "notifier_auto"),
                            "mode": "auto",
                        },
                    }
                )
            else:
                auto_apply_result["applied"] = False
                auto_apply_result["approval_status"] = "pending"
            if not bool(args.dry_run):
                persisted_report = _read_json(reflection_report_path, {})
                persisted_report["auto_approval"] = dict(auto_apply_result)
                _write_json(reflection_report_path, persisted_report)
            preview_cmd = _reflection_command_preview(report_day8)
            apply_cmd = _reflection_command_apply(report_day8)
            title, text, payload = _build_daily_goal_report(
                report_dt=now,
                host=host,
                day8=report_day8,
                goal_jpy=daily_goal_jpy,
                daily_pnl_jpy_sum=float(_safe_float(daily_review.get("pnl_jpy_sum")) or 0.0),
                daily_ret_pct_sum=float(_safe_float(daily_review.get("ret_sum_pct")) or 0.0),
                daily_closed_count=int(_safe_int(daily_review.get("closed_n"), 0)),
                close_reason=close_reason,
            )
            llm_text = str(llm_feedback.get("summary", "")).strip()
            llm_block = f"【LLM反省】\n{llm_text}\n" if llm_text else ""
            summary_block = _build_daily_goal_summary_block(
                goal_jpy=daily_goal_jpy,
                daily_review=daily_review,
                reflection=reflection,
                auto_apply=auto_apply_result,
                shadow_review=shadow_review,
            )
            text = (
                f"{text}\n"
                f"\n{summary_block}\n"
                f"\n【詳細】\n"
                f"{_daily_review_text_block(daily_review, reflection, shadow_review)}\n"
                f"\n{_reflection_text_block(reflection)}\n"
                f"\n{_auto_apply_text_block(auto_apply_result)}\n"
                f"\n{llm_block}"
                f"【操作】\n"
                f"反省JSON={reflection_report_path}\n"
                f"承認プレビュー={preview_cmd}\n"
                f"承認実行={apply_cmd}"
            )
            payload["daily_review"] = daily_review
            payload["shadow_review"] = shadow_review
            payload["reflection"] = reflection
            payload["reflection_report_path"] = str(reflection_report_path)
            payload["auto_approval"] = auto_apply_result
            payload["daily_reflection_llm_feedback"] = llm_feedback
            payload["approval_preview_command"] = preview_cmd
            payload["approval_apply_command"] = apply_cmd
            ok, msg = _send_event(title=title, text=text, payload=payload, sec=sec, dry_run=bool(args.dry_run))
            tag = "OK" if ok else "FAIL"
            print(
                f"[{tag}] daily_goal_report day8={report_day8} "
                f"reason={close_reason} achieved={payload.get('goal_achieved')} pnl_jpy={payload.get('daily_pnl_jpy_sum')} "
                f"report={reflection_report_path} ({msg})"
            )
            if not bool(args.dry_run):
                _mark_daily_goal_report_done(
                    cursor,
                    report_day8,
                    sent=bool(ok) and _notify_target_effective(msg),
                )
            sent += 1

    if service_watch_enabled and watch_dashboard:
        dash_now = _http_get_ok("http://127.0.0.1:8501/_stcore/health", timeout_sec=2.0)
        dash_prev = cursor.get("dashboard_alive", None)
        if dash_prev is None:
            cursor["dashboard_alive"] = bool(dash_now)
        elif bool(dash_prev) != bool(dash_now):
            dash_event_key = _state_change_event_key("dashboard_state_changed", bool(dash_now))
            if not _is_cooldown_blocked(
                dash_event_key,
                state_change_min_interval_sec,
                "dashboard_state_changed",
            ):
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                title = "Ouroboros ダッシュボード状態の変更"
                text = (
                    f"{title}\n"
                    f"時刻={ts}\n"
                    f"dashboard_alive={'ON' if dash_now else 'OFF'}\n"
                    f"ホスト={host}"
                )
                payload = {
                    "event": "dashboard_state_changed",
                    "time": ts,
                    "dashboard_alive": bool(dash_now),
                    "host": host,
                }
                ok, msg = _send_event(title=title, text=text, payload=payload, sec=sec, dry_run=bool(args.dry_run))
                tag = "OK" if ok else "FAIL"
                print(f"[{tag}] dashboard_state_changed -> {dash_now} ({msg})")
                _mark_sent_if_effective(dash_event_key, ok, msg)
                sent += 1
            cursor["dashboard_alive"] = bool(dash_now)

    if service_watch_enabled and watch_ngrok:
        ngrok_now = _http_get_ok("http://127.0.0.1:4040/api/tunnels", timeout_sec=2.0)
        ngrok_prev = cursor.get("ngrok_alive", None)
        if ngrok_prev is None:
            cursor["ngrok_alive"] = bool(ngrok_now)
        elif bool(ngrok_prev) != bool(ngrok_now):
            ngrok_event_key = _state_change_event_key("ngrok_state_changed", bool(ngrok_now))
            if not _is_cooldown_blocked(ngrok_event_key, state_change_min_interval_sec, "ngrok_state_changed"):
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                title = "Ouroboros ngrok状態の変更"
                text = (
                    f"{title}\n"
                    f"時刻={ts}\n"
                    f"ngrok_alive={'ON' if ngrok_now else 'OFF'}\n"
                    f"ホスト={host}"
                )
                payload = {
                    "event": "ngrok_state_changed",
                    "time": ts,
                    "ngrok_alive": bool(ngrok_now),
                    "host": host,
                }
                ok, msg = _send_event(title=title, text=text, payload=payload, sec=sec, dry_run=bool(args.dry_run))
                tag = "OK" if ok else "FAIL"
                print(f"[{tag}] ngrok_state_changed -> {ngrok_now} ({msg})")
                _mark_sent_if_effective(ngrok_event_key, ok, msg)
                sent += 1
            cursor["ngrok_alive"] = bool(ngrok_now)

    if drift_watch_notify_enabled:
        drift_now = _drift_watch_state(state_json)
        drift_status_now = str(drift_now.get("status", "")).strip().upper()
        drift_hours_now = list(drift_now.get("recommended_stop_hours") or [])
        drift_hours_now_csv = ",".join(str(int(x)) for x in drift_hours_now)
        drift_block_now = _safe_bool(drift_now.get("hour_blocked_by_drift"), False)
        drift_outlook_now = drift_now.get("resume_outlook", {}) if isinstance(drift_now.get("resume_outlook"), dict) else {}
        drift_outlook_now_summary = str(drift_outlook_now.get("summary", "") or "")

        drift_status_prev = str(cursor.get("drift_status", "")).strip().upper()
        drift_hours_prev_csv = str(cursor.get("drift_stop_hours_csv", "")).strip()
        drift_block_prev = _safe_bool(cursor.get("drift_hour_blocked_by_drift"), False)
        drift_outlook_prev_summary = str(cursor.get("drift_resume_outlook_summary", "")).strip()

        # Initialize baseline without sending on the first run.
        if (
            not drift_status_prev
            and not drift_hours_prev_csv
            and not drift_outlook_prev_summary
            and (cursor.get("drift_hour_blocked_by_drift", None) is False)
        ):
            cursor["drift_status"] = drift_status_now
            cursor["drift_stop_hours_csv"] = drift_hours_now_csv
            cursor["drift_hour_blocked_by_drift"] = bool(drift_block_now)
            cursor["drift_resume_outlook_summary"] = drift_outlook_now_summary
        elif (
            drift_status_prev != drift_status_now
            or drift_hours_prev_csv != drift_hours_now_csv
            or bool(drift_block_prev) != bool(drift_block_now)
            or drift_outlook_prev_summary != drift_outlook_now_summary
        ):
            if not _is_cooldown_blocked("drift_state_changed", state_change_min_interval_sec, "drift_state_changed"):
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                title = "Ouroboros ドリフト状態の変更"
                text = (
                    f"{title}\n"
                    f"時刻={ts}\n"
                    f"drift_status={drift_status_prev or '-'} -> {drift_status_now or '-'}\n"
                    f"推奨停止時間帯={drift_hours_prev_csv or '-'} -> {drift_hours_now_csv or '-'}\n"
                    f"hour_blocked_by_drift={bool(drift_block_prev)} -> {bool(drift_block_now)}\n"
                    f"復帰見込み={drift_outlook_prev_summary or '-'} -> {drift_outlook_now_summary or '-'}\n"
                    f"復帰詳細={str(drift_outlook_now.get('detail', '-') or '-')}\n"
                    f"frozen_by_drift={_safe_bool(drift_now.get('frozen_by_drift'), False)}\n"
                    f"trade_paused_by_drift={_safe_bool(drift_now.get('trade_paused_by_drift'), False)}\n"
                    f"ホスト={host}"
                )
                payload = {
                    "event": "drift_state_changed",
                    "time": ts,
                    "drift_status_before": drift_status_prev,
                    "drift_status_after": drift_status_now,
                    "recommended_stop_hours_before": drift_hours_prev_csv,
                    "recommended_stop_hours_after": drift_hours_now_csv,
                    "hour_blocked_by_drift_before": bool(drift_block_prev),
                    "hour_blocked_by_drift_after": bool(drift_block_now),
                    "resume_outlook_before": drift_outlook_prev_summary,
                    "resume_outlook_after": drift_outlook_now_summary,
                    "resume_outlook": drift_outlook_now,
                    "frozen_by_drift": _safe_bool(drift_now.get("frozen_by_drift"), False),
                    "trade_paused_by_drift": _safe_bool(drift_now.get("trade_paused_by_drift"), False),
                    "host": host,
                }
                ok, msg = _send_event(title=title, text=text, payload=payload, sec=sec, dry_run=bool(args.dry_run))
                tag = "OK" if ok else "FAIL"
                print(
                    f"[{tag}] drift_state_changed status={drift_status_prev or '-'}->{drift_status_now or '-'} "
                    f"hours={drift_hours_prev_csv or '-'}->{drift_hours_now_csv or '-'} ({msg})"
                )
                _mark_sent_if_effective("drift_state_changed", ok, msg)
                sent += 1
            cursor["drift_status"] = drift_status_now
            cursor["drift_stop_hours_csv"] = drift_hours_now_csv
            cursor["drift_hour_blocked_by_drift"] = bool(drift_block_now)
            cursor["drift_resume_outlook_summary"] = drift_outlook_now_summary

    # trade_enabled 自動再開通知
    reenabled_reason = str(cursor.get("trade_enabled_reenabled_reason", "") or "").strip()
    reenabled_at = str(cursor.get("trade_enabled_reenabled_at", "") or "").strip()
    reenabled_notified_at = str(cursor.get("trade_enabled_reenabled_notified_at", "") or "").strip()
    if reenabled_reason and reenabled_at and reenabled_at != reenabled_notified_at:
        if not _is_cooldown_blocked("trade_enabled_reenabled", state_change_min_interval_sec, "trade_enabled_reenabled"):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            title = "Ouroboros 取引自動再開"
            text = (
                f"{title}\n"
                f"時刻={ts}\n"
                f"再開理由={reenabled_reason}\n"
                f"再開時刻={reenabled_at}\n"
                f"ホスト={host}"
            )
            payload = {
                "event": "trade_enabled_reenabled",
                "time": ts,
                "reenabled_reason": reenabled_reason,
                "reenabled_at": reenabled_at,
                "host": host,
            }
            ok, msg = _send_event(title=title, text=text, payload=payload, sec=sec, dry_run=bool(args.dry_run))
            tag = "OK" if ok else "FAIL"
            print(f"[{tag}] trade_enabled_reenabled reason={reenabled_reason} ({msg})")
            _mark_sent_if_effective("trade_enabled_reenabled", ok, msg)
            sent += 1
        cursor["trade_enabled_reenabled_notified_at"] = reenabled_at

    # DD悪化アラート: max_dd < -5%pt かつ未回復なら ntfy 通知
    try:
        reports_dir = ROOT / "reports"
        today8_dd = _day8(now)
        dd_report_path = reports_dir / f"dd_report_{today8_dd}.json"
        if not dd_report_path.exists():
            # Fall back to all-time report
            dd_report_path = reports_dir / "dd_report_all-time.json"
        if dd_report_path.exists():
            dd_data = _read_json(dd_report_path, {})
            dd_metrics = dd_data.get("metrics") if isinstance(dd_data.get("metrics"), dict) else {}
            dd_amount = _safe_float(dd_metrics.get("daily_max_drawdown_amount"))
            dd_recovery = dd_metrics.get("dd_recovery_minutes")
            dd_alert_threshold = -5.0
            already_dd_alerted = str(cursor.get("dd_alert_alerted_day8", "")) == today8_dd
            if (
                dd_amount is not None
                and dd_amount < dd_alert_threshold
                and dd_recovery is None
                and not already_dd_alerted
            ):
                if not _is_cooldown_blocked("dd_alert", alert_min_interval_sec, "dd_alert"):
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    pf = _safe_float(dd_metrics.get("profit_factor"))
                    rf = _safe_float(dd_metrics.get("recovery_factor"))
                    exp = _safe_float(dd_metrics.get("expectancy_per_trade_pct"))
                    title = "Ouroboros DD悪化アラート"
                    pf_str = f"{pf:.2f}" if pf is not None else "-"
                    rf_str = f"{rf:.2f}" if rf is not None else "-"
                    exp_str = f"{exp:.4f}%pt" if exp is not None else "-"
                    text = (
                        f"{title}\n"
                        f"時刻={ts}\n"
                        f"最大DD={dd_amount:.3f}%pt (閾値={dd_alert_threshold:.1f}%pt)\n"
                        f"DD回復: 未回復\n"
                        f"PF={pf_str} / RF={rf_str}\n"
                        f"期待値={exp_str}\n"
                        f"ホスト={host}"
                    )
                    payload_dd = {
                        "event": "dd_alert",
                        "time": ts,
                        "daily_max_drawdown_amount": dd_amount,
                        "dd_recovery_minutes": None,
                        "profit_factor": pf,
                        "recovery_factor": rf,
                        "expectancy_per_trade_pct": exp,
                        "host": host,
                    }
                    ok_dd, msg_dd = _send_event(
                        title=title, text=text, payload=payload_dd, sec=sec,
                        dry_run=bool(args.dry_run), tags="warning", priority="high",
                    )
                    tag_dd = "OK" if ok_dd else "FAIL"
                    print(f"[{tag_dd}] dd_alert max_dd={dd_amount:.3f} day8={today8_dd} ({msg_dd})")
                    _mark_sent_if_effective("dd_alert", ok_dd, msg_dd)
                    cursor["dd_alert_alerted_day8"] = today8_dd
                    sent += 1
    except Exception as _dd_exc:
        print(f"[WARN] dd_alert check failed: {_dd_exc}")

    cursor["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_json(cursor_path, cursor)

    print(f"[OK] notifier completed sent={sent} dry_run={bool(args.dry_run)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
