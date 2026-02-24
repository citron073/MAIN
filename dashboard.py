# ============================================================
# Trading Bot Dashboard — Project Ouroboros v1 (SPEC-Compliant)
#
# SPEC:
# - CONTROL.csv (key,value) editing UI
# - Preserve unknown keys (never delete)
# - daily_report / audit execution buttons
# - Audit JSON visualization (priority)
# - pos_id-centric view (status from JSON MUST NOT be rejudged)
# - issues: include pos_id text; buttons jump to search
# - ret_pct estimate: (exit-entry)/entry ; SELL sign inversion; fee not included; always label as "推定"
#
# Run:
#   python3 -m streamlit run dashboard.py
# ============================================================

from __future__ import annotations

import csv
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st
try:
    import plotly.express as px
    import plotly.graph_objects as go

    HAS_PLOTLY = True
except Exception:
    HAS_PLOTLY = False

# =========================
# Page Config
# =========================
st.set_page_config(
    page_title="Trading Bot Dashboard (Ouroboros v1)",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================
# i18n (minimal)
# =========================
I18N = {
    "ja": {
        "app_title": "Trading Bot Dashboard",
        "subtitle": "Ouroboros v1 — 管理・監査パネル",
        "tab_home": "🏠 ホーム・稼働状況",
        "tab_settings": "⚙️ Bot設定 (CONTROL)",
        "tab_analytics": "📊 成績・分析",
        "tab_history": "📝 トレード履歴",
        "tab_pos": "🧩 pos_id・監査(JSON)",
        "tab_guide": "📚 マニュアル・ガイド",
        "tab_tools": "🛠 ツール・メンテナンス",
        "save_success": "設定を保存しました！",
        "save_error": "保存に失敗しました。",
        "loading": "読み込み中...",
        "audit_json_priority": "監査JSONが存在するため、これを最優先で表示しています（Dashboard側でstatus再判定しません）。",
        "fallback_mode": "監査JSONが無いので、ログから推定した結果を表示しています（推定）。",
    }
}


def T(key: str) -> str:
    lang = st.session_state.get("lang", "ja")
    return I18N.get(lang, I18N["ja"]).get(key, key)


# =========================
# Paths
# =========================
def get_main_dir() -> Path:
    return Path(__file__).resolve().parent


def find_logs_dir(main_dir: Path) -> Optional[Path]:
    cands = [
        main_dir / "logs",
        main_dir.parent / "logs",
        Path("./logs").resolve(),
        Path("../logs").resolve(),
    ]
    for p in cands:
        try:
            if p.exists() and any(p.glob("trade_log_*.csv")):
                return p
        except Exception:
            pass
    return None


def find_control_csv(main_dir: Path) -> Path:
    cands = [
        main_dir / "CONTROL.csv",
        main_dir.parent / "CONTROL.csv",
        main_dir / "control" / "CONTROL.csv",
    ]
    for p in cands:
        if p.exists():
            return p
    return main_dir / "CONTROL.csv"


def find_state_json(main_dir: Path) -> Path:
    return main_dir / "state.json"


def daily_report_out_dir(main_dir: Path) -> Path:
    return main_dir / "daily_report_out"


def run_lock_dir(main_dir: Path) -> Path:
    return main_dir / ".run_lock"


# =========================
# CONTROL (SPEC)
# =========================
DEFAULTS: Dict[str, str] = {
    # switches
    "today_on": "1",
    "trade_enabled": "1",
    "paper_mode": "1",
    "observe_only": "0",
    "live_enabled": "0",
    "one_position_only": "1",
    "safety_hard_block": "1",
    "rollout_mode": "AUTO",
    "stage_paper_days": "3",
    "stage_canary_days": "3",
    "canary_lot": "0.001",
    "daily_loss_limit_pct": "-1.0",
    "limit_order_timeout_sec": "30",
    "limit_price_offset_ticks": "0",
    "product_code": "BTC_JPY",
    "market_type": "SPOT",
    "keychain_service": "ouroboros.bitflyer",
    "keychain_account_key": "api_key",
    "keychain_account_secret": "api_secret",
    # risk/params
    "tp_buy_pct": "0.155",
    "tp_sell_pct": "0.180",
    "sl_pct": "-0.220",
    "win_min": "120",
    "timeout_mode": "IGNORE",
    "spread_limit_pct": "0.0005",
    "max_trades_per_day": "50",
    "lot": "0.001",
    # MA params
    "fast_n": "5",
    "slow_n": "20",
    "max_ltp_history": "200",
    # partial/extend
    "max_extend_count": "1",
    "extend_min": "30",
    "extend_min_bestfav_pct": "0.08",
    "partial_tp_trigger_pct": "0.10",
    # AI toggles (compat)
    "ai_model_enabled": "0",
    "ai_enabled": "0",
    "ai_mode": "OFF",
    "ai_threshold": "0.55",
    "ai_veto_threshold": "0.30",
    "ai_auto_train_enabled": "1",
    "ai_auto_lookback_days": "45",
    "ai_features": "spread,trend,ma_gap,ma_slope,volatility",
    "ai_debug": "0",
    "ai_dp_entry": "1",
    "ai_dp_extend": "1",
    "ai_dp_exit": "1",
}

BOOL_TRUE = ("1", "true", "yes", "on", "y", "t")
BOOL_FALSE = ("0", "false", "no", "off", "n", "f")


def bval_str(v: Any) -> bool:
    return str(v or "0").strip().lower() in BOOL_TRUE


def _read_text_try(path: Path, encs: Iterable[str]) -> Optional[str]:
    for enc in encs:
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return None


def read_control_kv_csv(path: Path) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """
    SPEC: key,value. Preserve unknown keys.
    If missing: start with DEFAULTS.
    """
    meta = {"path": str(path), "exists": path.exists(), "mtime": None}
    out: Dict[str, str] = {}
    if path.exists():
        try:
            meta["mtime"] = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            txt = _read_text_try(path, ["utf-8", "utf-8-sig", "cp932"])
            if not txt:
                raise ValueError("cannot read text")
            rows = list(csv.reader(txt.splitlines()))
            for r in rows:
                if len(r) < 2:
                    continue
                k = str(r[0]).strip()
                if not k or k.lower() == "key":
                    continue
                out[k] = str(r[1]).strip()
        except Exception:
            out = {}

    # Apply defaults without deleting unknown keys
    for k, v in DEFAULTS.items():
        out.setdefault(k, v)

    # AI compat: keep both ai_enabled and ai_model_enabled aligned on write; read: if either is ON, treat as ON
    if bval_str(out.get("ai_enabled", "0")) and not bval_str(out.get("ai_model_enabled", "0")):
        out["ai_model_enabled"] = "1"
    if bval_str(out.get("ai_model_enabled", "0")) and not bval_str(out.get("ai_enabled", "0")):
        out["ai_enabled"] = "1"

    return out, meta


def write_control_kv_csv(path: Path, d: Dict[str, str]) -> Tuple[bool, str]:
    """
    SPEC: unknown keys MUST be preserved. We write all keys (sorted).
    Also keep ai_enabled and ai_model_enabled aligned.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        # Align AI toggles
        ai_on = bval_str(d.get("ai_model_enabled", d.get("ai_enabled", "0")))
        d["ai_model_enabled"] = "1" if ai_on else "0"
        d["ai_enabled"] = "1" if ai_on else "0"

        rows = [["key", "value"]] + [[k, str(d.get(k, ""))] for k in sorted(d.keys())]
        tmp = path.with_suffix(path.suffix + ".tmp")
        # create parent dir
        path.parent.mkdir(parents=True, exist_ok=True)
        # write to tmp first
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        # create a timestamped backup of existing file (SPEC: .bak)
        try:
            if path.exists():
                from datetime import datetime as _dt

                bak = path.with_name(path.name + f".bak_{_dt.utcnow().strftime('%Y%m%dT%H%M%SZ')}")
                import shutil

                shutil.copy(path, bak)
        except Exception:
            # non-fatal: continue to replace
            pass
        tmp.replace(path)
        return True, str(path)
    except Exception as e:
        return False, str(e)


# =========================
# Logs / JSON
# =========================
LOG_NAME_RE = re.compile(r"trade_log_(\d{8})\.csv$")
REPORT_JSON_RE = re.compile(r"^daily_report_(\d{8})(?:_(\d{8}))?\.json$")


def list_log_days(logs_dir: Optional[Path]) -> List[str]:
    if not logs_dir or not logs_dir.exists():
        return []
    days = []
    for p in logs_dir.glob("trade_log_*.csv"):
        m = LOG_NAME_RE.search(p.name)
        if m:
            days.append(m.group(1))
    return sorted(set(days), reverse=True)


def _read_csv_dict_rows(path: Path) -> List[Dict[str, Any]]:
    txt = _read_text_try(path, ["utf-8", "utf-8-sig", "cp932"])
    if not txt:
        return []
    try:
        return list(csv.DictReader(txt.splitlines()))
    except Exception:
        return []


@st.cache_data(show_spinner=False)
def read_trade_log_df(csv_path: Path, cache_token: str = "") -> pd.DataFrame:
    # cache_token carries file mtime/size so cache invalidates when the log file changes.
    _ = cache_token
    for enc in ("utf-8", "utf-8-sig", "cp932"):
        try:
            df = pd.read_csv(csv_path, encoding=enc)
            if "time" in df.columns:
                df["time_dt"] = pd.to_datetime(df["time"], errors="coerce")
                df["hour"] = df["time_dt"].dt.hour
            return df
        except Exception:
            continue
    return pd.DataFrame()


def file_cache_token(path: Path) -> str:
    try:
        stt = path.stat()
        return f"{stt.st_mtime_ns}:{stt.st_size}"
    except Exception:
        return "missing"


def safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s == "" or s.lower() in ("none", "nan"):
            return None
        return float(s)
    except Exception:
        return None


def compute_ret_pct(entry_price: Optional[float], exit_price: Optional[float], side: str) -> Optional[float]:
    if entry_price is None or exit_price is None:
        return None
    if entry_price == 0:
        return None
    r = (exit_price - entry_price) / entry_price
    if str(side).upper() == "SELL":
        r = -r
    return r * 100.0


def collect_json_reports(out_dir: Path) -> List[Path]:
    if not out_dir.exists():
        return []
    cands = []
    for p in out_dir.glob("daily_report_*.json"):
        if REPORT_JSON_RE.search(p.name):
            cands.append(p)
    # newest first by mtime
    cands.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
    return cands


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        txt = path.read_text(encoding="utf-8")
        return json.loads(txt)
    except Exception:
        # try utf-8-sig
        try:
            txt = path.read_text(encoding="utf-8-sig")
            return json.loads(txt)
        except Exception:
            return None


def normalize_daily_report_json(j: Dict[str, Any]) -> Dict[str, Any]:
    # Ensure required top-level keys with defaults per SPEC
    if not isinstance(j, dict):
        return {}
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    additions: List[str] = []

    def sset(d: Dict[str, Any], key: str, val: Any, path: str):
        if key not in d:
            additions.append(path)
        d.setdefault(key, val)

    # meta
    if "meta" not in j:
        additions.append("meta")
        j["meta"] = {}
    meta = j["meta"]
    sset(meta, "spec", "UNKNOWN", "meta.spec")
    # generated_at_jst: if missing, insert now
    if "generated_at_jst" not in meta:
        additions.append("meta.generated_at_jst")
        meta["generated_at_jst"] = now
    sset(meta, "target_day8", meta.get("target_day8", "00000000"), "meta.target_day8")
    sset(meta, "rows_total", meta.get("rows_total", 0), "meta.rows_total")
    sset(meta, "rows_used", meta.get("rows_used", 0), "meta.rows_used")

    # daily
    if "daily" not in j:
        additions.append("daily")
        j["daily"] = {}
    daily = j["daily"]
    for k in ("paper_n", "observe_n", "skip_n", "hold_n", "exit_n", "error_n", "paper_rate_pct"):
        if k not in daily:
            additions.append(f"daily.{k}")
        daily.setdefault(k, 0)

    # by_side
    if "by_side" not in j:
        additions.append("by_side")
        j["by_side"] = {}
    bs = j["by_side"]
    for side in ("BUY", "SELL", "UNKNOWN"):
        if side not in bs:
            additions.append(f"by_side.{side}")
            bs[side] = {}
        for k in ("paper_n", "observe_n", "skip_n", "hold_n", "exit_n", "paper_rate_pct", "tp_n", "sl_n", "timeout_n", "partial_tp_n", "eod_n"):
            if k not in bs[side]:
                additions.append(f"by_side.{side}.{k}")
            bs[side].setdefault(k, 0)

    # by_hour
    if "by_hour" not in j:
        additions.append("by_hour")
        j["by_hour"] = {}
    bh = j["by_hour"]
    for h in range(24):
        hh = str(h)
        if hh not in bh:
            additions.append(f"by_hour.{hh}")
            bh[hh] = {}
        for k in ("paper_n", "observe_n", "hold_n", "exit_n", "paper_rate_pct", "spread_avg_pct"):
            if k not in bh[hh]:
                additions.append(f"by_hour.{hh}.{k}")
            bh[hh].setdefault(k, 0)

    # spread
    if "spread" not in j:
        additions.append("spread")
        j["spread"] = {}
    sp = j["spread"]
    for k in ("avg_pct", "p90_pct", "max_pct", "over_limit_n"):
        if k not in sp:
            additions.append(f"spread.{k}")
        sp.setdefault(k, 0)

    # exit_integrity
    if "exit_integrity" not in j:
        additions.append("exit_integrity")
        j["exit_integrity"] = {}
    ei = j["exit_integrity"]
    for k in ("paper_pos_ids", "exit_pos_ids", "open_pos_ids", "missing_exit_pos_ids"):
        if k not in ei:
            additions.append(f"exit_integrity.{k}")
        ei.setdefault(k, [])

    # mae_mfe
    if "mae_mfe" not in j:
        additions.append("mae_mfe")
        j["mae_mfe"] = {}
    mm = j["mae_mfe"]
    if "per_pos" not in mm:
        additions.append("mae_mfe.per_pos")
    mm.setdefault("per_pos", {})
    if "summary" not in mm:
        additions.append("mae_mfe.summary")
    mm.setdefault("summary", {})

    # issues normalization
    orig_issues = j.get("issues", None)
    norm_issues = []
    if orig_issues is None:
        additions.append("issues")
    if isinstance(orig_issues, list):
        for it in orig_issues:
            if isinstance(it, dict):
                norm_issues.append(it)
            else:
                s = str(it)
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, dict):
                        norm_issues.append(parsed)
                        additions.append("issues.parsed_dict")
                        continue
                except Exception:
                    pass
                norm_issues.append(s)
    else:
        # if issues is a single object/string, normalize to list
        additions.append("issues.normalized_to_list")
        s = str(orig_issues)
        try:
            parsed = json.loads(s)
            if isinstance(parsed, dict):
                norm_issues.append(parsed)
            else:
                norm_issues.append(s)
        except Exception:
            norm_issues.append(s)
    j["issues"] = norm_issues

    # attach metadata about what was added
    if additions:
        j.setdefault("_normalized", {})
        j["_normalized"]["added_keys"] = additions

    return j


def dig_first(d: Dict[str, Any], keys: List[str], default=None):
    """
    SPEC note: If key names change, add here for compatibility.
    """
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        if k in cur:
            cur = cur[k]
        else:
            return default
    return cur


# =========================
# pos_id model
# =========================
@dataclass
class PosView:
    pos_id: str
    status: str  # OPEN/CLOSED/UNKNOWN/ERROR
    entry_time: Optional[str]
    entry_side: Optional[str]
    entry_price: Optional[float]
    exit_time: Optional[str]
    exit_result: Optional[str]
    exit_ltp: Optional[float]
    ret_pct_est: Optional[float]  # estimate
    ai_score: Optional[float]
    ai_pass: Optional[bool]
    mae: Optional[float]
    mfe: Optional[float]
    source: str  # "JSON" or "LOG_FALLBACK"
    notes: str = ""


# =========================
# From JSON (priority)
# =========================
def posviews_from_audit_json(j: Dict[str, Any]) -> Tuple[List[PosView], List[str]]:
    issues: List[str] = []
    per_pos = dig_first(j, ["per_pos"], default={})
    if not isinstance(per_pos, dict):
        per_pos = {}

    issues_raw = dig_first(j, ["issues"], default=[])
    if isinstance(issues_raw, list):
        for x in issues_raw:
            try:
                issues.append(str(x))
            except Exception:
                pass

    out: List[PosView] = []
    for pid, obj in per_pos.items():
        if not isinstance(obj, dict):
            continue

        status = str(obj.get("status", "UNKNOWN"))
        if status not in ("OPEN", "CLOSED", "UNKNOWN", "ERROR"):
            status = "UNKNOWN"

        entry = obj.get("entry", {}) if isinstance(obj.get("entry", {}), dict) else {}
        exit_ = obj.get("exit", {}) if isinstance(obj.get("exit", {}), dict) else {}
        ai = obj.get("ai", {}) if isinstance(obj.get("ai", {}), dict) else {}

        entry_time = entry.get("time")
        entry_side = entry.get("side")
        entry_price = safe_float(entry.get("price"))

        exit_time = exit_.get("time")
        exit_result = exit_.get("result")
        exit_ltp = safe_float(exit_.get("ltp"))

        # ret_pct is estimate (fee not included)
        ret_pct = compute_ret_pct(entry_price, exit_ltp, str(entry_side or ""))

        ai_score = safe_float(ai.get("score"))
        ai_pass = ai.get("pass")
        if isinstance(ai_pass, str):
            ai_pass = ai_pass.strip().lower() in BOOL_TRUE
        elif not isinstance(ai_pass, bool):
            ai_pass = None

        mae = safe_float(obj.get("mae"))
        mfe = safe_float(obj.get("mfe"))

        out.append(
            PosView(
                pos_id=str(pid),
                status=status,
                entry_time=str(entry_time) if entry_time is not None else None,
                entry_side=str(entry_side) if entry_side is not None else None,
                entry_price=entry_price,
                exit_time=str(exit_time) if exit_time is not None else None,
                exit_result=str(exit_result) if exit_result is not None else None,
                exit_ltp=exit_ltp,
                ret_pct_est=ret_pct,
                ai_score=ai_score,
                ai_pass=ai_pass,
                mae=mae,
                mfe=mfe,
                source="JSON",
                notes="（推定）ret_pctはfee未加味",
            )
        )

    # stable ordering: open first, then recent-ish (entry_time string sort)
    def _key(p: PosView):
        st_rank = {"OPEN": 0, "UNKNOWN": 1, "ERROR": 2, "CLOSED": 3}.get(p.status, 9)
        t = p.entry_time or ""
        return (st_rank, t)

    out.sort(key=_key)
    return out, issues


# =========================
# From LOG fallback
# =========================
def posviews_from_logs(rows: List[Dict[str, Any]]) -> Tuple[List[PosView], List[str]]:
    """
    Fallback rule (SPEC):
    - If no JSON, infer from logs.
    - This is "推定" (estimate).
    """
    issues: List[str] = []
    by_pid: Dict[str, List[Dict[str, Any]]] = {}

    for r in rows:
        pid = str(r.get("pos_id", "")).strip()
        if not pid:
            continue
        by_pid.setdefault(pid, []).append(r)

    out: List[PosView] = []

    for pid, rr in by_pid.items():
        # sort by time string if present
        rr_sorted = sorted(rr, key=lambda x: str(x.get("time", "")))

        # Entry: first PAPER with side BUY/SELL
        entry_row = None
        for r in rr_sorted:
            if str(r.get("result", "")).strip() == "PAPER":
                entry_row = r
                break

        # Exit: last PAPER_EXIT_* row
        exit_row = None
        for r in rr_sorted:
            if str(r.get("result", "")).startswith("PAPER_EXIT"):
                exit_row = r
        # status inference
        if entry_row and exit_row:
            status = "CLOSED"
        elif entry_row and not exit_row:
            status = "OPEN"
        else:
            status = "UNKNOWN"

        entry_time = str(entry_row.get("time")) if entry_row else None
        entry_side = str(entry_row.get("side")) if entry_row else None
        entry_price = safe_float(entry_row.get("price")) if entry_row else None

        exit_time = str(exit_row.get("time")) if exit_row else None
        exit_result = str(exit_row.get("result")) if exit_row else None
        exit_ltp = safe_float(exit_row.get("ltp")) if exit_row else None

        ret_pct = compute_ret_pct(entry_price, exit_ltp, str(entry_side or ""))

        # optional ai_score (if present on rows; pick from entry if present else latest)
        ai_score = None
        for cand in [entry_row, exit_row] + rr_sorted[::-1]:
            if not cand:
                continue
            if "ai_score" in cand:
                ai_score = safe_float(cand.get("ai_score"))
                if ai_score is not None:
                    break

        notes = "（推定）ログからOPEN/CLOSEDを推定 / ret_pctはfee未加味"

        if status == "UNKNOWN":
            issues.append(f"WARN pos_id={pid} entry/exitが特定できず（推定不能）")

        out.append(
            PosView(
                pos_id=pid,
                status=status,
                entry_time=entry_time,
                entry_side=entry_side,
                entry_price=entry_price,
                exit_time=exit_time,
                exit_result=exit_result,
                exit_ltp=exit_ltp,
                ret_pct_est=ret_pct,
                ai_score=ai_score,
                ai_pass=None,
                mae=None,
                mfe=None,
                source="LOG_FALLBACK",
                notes=notes,
            )
        )

    # sort: open first, then pid
    def _key(p: PosView):
        st_rank = {"OPEN": 0, "UNKNOWN": 1, "ERROR": 2, "CLOSED": 3}.get(p.status, 9)
        return (st_rank, p.pos_id)

    out.sort(key=_key)
    return out, issues


def build_position_metrics_from_logs(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Build one row per pos_id from raw log rows for analytics visualization.
    pnl_est is estimated from entry/exit and size (fee not included).
    """
    by_pid: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        pid = str(r.get("pos_id", "")).strip()
        if not pid:
            continue
        by_pid.setdefault(pid, []).append(r)

    out_rows: List[Dict[str, Any]] = []
    for pid, rr in by_pid.items():
        rr_sorted = sorted(rr, key=lambda x: str(x.get("time", "")))
        entry_row = None
        for r in rr_sorted:
            if str(r.get("result", "")).strip() == "PAPER":
                entry_row = r
                break
        exit_row = None
        for r in rr_sorted:
            if str(r.get("result", "")).startswith("PAPER_EXIT"):
                exit_row = r

        if entry_row and exit_row:
            status = "CLOSED"
        elif entry_row and not exit_row:
            status = "OPEN"
        else:
            status = "UNKNOWN"

        side = str(entry_row.get("side")) if entry_row else ""
        entry_price = safe_float(entry_row.get("price")) if entry_row else None
        size = safe_float(entry_row.get("size")) if entry_row else None
        exit_ltp = safe_float(exit_row.get("ltp")) if exit_row else None
        ret_pct = compute_ret_pct(entry_price, exit_ltp, side)

        pnl_est = None
        if entry_price is not None and exit_ltp is not None and size is not None:
            sign = -1.0 if str(side).upper() == "SELL" else 1.0
            pnl_est = (exit_ltp - entry_price) * size * sign

        out_rows.append(
            {
                "pos_id": pid,
                "status": status,
                "side": side,
                "entry_time": str(entry_row.get("time")) if entry_row else None,
                "exit_time": str(exit_row.get("time")) if exit_row else None,
                "entry_price": entry_price,
                "exit_ltp": exit_ltp,
                "size": size,
                "ret_pct_est": ret_pct,
                "pnl_est": pnl_est,
            }
        )

    if not out_rows:
        return pd.DataFrame()

    df = pd.DataFrame(out_rows)
    df["entry_time_dt"] = pd.to_datetime(df["entry_time"], errors="coerce")
    df["exit_time_dt"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df["time_dt"] = df["exit_time_dt"].fillna(df["entry_time_dt"])
    df = df.sort_values(["time_dt", "pos_id"], ascending=[True, True]).reset_index(drop=True)
    return df


def build_trade_timeline_frames(rows: List[Dict[str, Any]]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Build timeline data for charting.
    - price_df: chronological price points (ltp/bid/ask)
    - event_df: PAPER ENTRY / PAPER_EXIT markers with side and pos_id
    """
    price_rows: List[Dict[str, Any]] = []
    event_rows: List[Dict[str, Any]] = []

    for r in rows:
        t = str(r.get("time", "")).strip()
        if not t:
            continue
        td = pd.to_datetime(t, errors="coerce")
        if pd.isna(td):
            continue

        ltp = safe_float(r.get("ltp"))
        bid = safe_float(r.get("best_bid"))
        ask = safe_float(r.get("best_ask"))
        if ltp is not None or bid is not None or ask is not None:
            price_rows.append({"time_dt": td, "ltp": ltp, "best_bid": bid, "best_ask": ask})

        result = str(r.get("result", "")).strip()
        if result == "PAPER" or result.startswith("PAPER_EXIT"):
            side = str(r.get("side", "")).strip().upper()
            pos_id = str(r.get("pos_id", "")).strip()
            px = safe_float(r.get("price"))
            ev_price = ltp if ltp is not None else px
            if ev_price is None:
                continue

            if result == "PAPER":
                event_kind = "ENTRY_BUY" if side == "BUY" else "ENTRY_SELL"
                event_label = "ENTRY BUY" if side == "BUY" else "ENTRY SELL"
            else:
                event_kind = "EXIT"
                event_label = result

            event_rows.append(
                {
                    "time_dt": td,
                    "event_kind": event_kind,
                    "event_label": event_label,
                    "side": side,
                    "pos_id": pos_id,
                    "price_plot": ev_price,
                    "price": px,
                    "ltp": ltp,
                    "size": safe_float(r.get("size")),
                    "result": result,
                }
            )

    price_df = pd.DataFrame(price_rows)
    if not price_df.empty:
        price_df = price_df.sort_values("time_dt").reset_index(drop=True)
        price_df = price_df.drop_duplicates(subset=["time_dt"], keep="last")

    event_df = pd.DataFrame(event_rows)
    if not event_df.empty:
        event_df = event_df.sort_values("time_dt").reset_index(drop=True)

    return price_df, event_df


# =========================
# UI helpers
# =========================
def ui_status_banner(ctrl: Dict[str, str], lock_info: Dict[str, Any]):
    safety = bval_str(ctrl.get("safety_hard_block", "0"))
    today = bval_str(ctrl.get("today_on", "0"))
    paper = bval_str(ctrl.get("paper_mode", "0"))
    observe = bval_str(ctrl.get("observe_only", "0"))
    is_running = bool(lock_info.get("alive", False))

    if safety:
        st.error("🛑 **SAFETY BLOCK** — 全動作ブロック中（設定タブで解除）")
        return
    if not today:
        st.warning("💤 **停止中** — today_on=0（本日稼働OFF）")
        return
    if not is_running:
        st.warning("⚠️ **プロセス停止中** — 設定はONだが .run_lock のpidが生きていない可能性")
        return

    if observe:
        st.info("👀 **観測のみ** — observe_only=1（発注なし）")
    elif paper:
        st.success("🧪 **PAPERモード** — 架空売買（推奨）")
    else:
        st.success("🚀 **LIVEモード** — 実弾運用（注意）")


def ui_manual_tab(
    ctrl: Dict[str, str],
    state_obj: Dict[str, Any],
    logs_dir: Optional[Path],
    out_dir: Path,
    main_dir: Path,
    control_path: Path,
):
    st.markdown("## 📚 マニュアル・ガイド（運用手順）")
    st.caption("目的: 迷わず操作できるように、日次運用・LIVE移行・トラブル対応をこの画面で確認できます。")

    log_ok = bool(logs_dir and logs_dir.exists())
    report_ok = bool(collect_json_reports(out_dir))
    run_alive = bool(_lock_info(get_main_dir()).get("alive"))
    open_pos = bool((state_obj or {}).get("_open_pos"))

    with st.expander("🚦 現在の運用チェック（自動判定）", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("CONTROL設定", _badge(True))
        c2.metric("logs存在", _badge(log_ok))
        c3.metric("bot稼働", _badge(run_alive, "RUNNING", "STOPPED"))
        c4.metric("監査JSON", _badge(report_ok, "READY", "MISSING"))
        st.write(f"- open_pos: {_badge(open_pos, 'あり', 'なし')}")
        st.write(f"- モード: {'PAPER' if bval_str(ctrl.get('paper_mode')) else 'LIVE候補'} / live_enabled={ctrl.get('live_enabled', '0')}")

    with st.expander("🧪 手順ナビ（この画面で操作）", expanded=True):
        st.caption("運用状態に応じて、必要な操作をこのタブ内で完結できます。")
        errs, warns = _validate_control_values(ctrl)
        if errs:
            st.error("設定エラーがあります。先に `Bot設定` で修正してください。")
            for e in errs:
                st.write(f"- {e}")
        elif warns:
            st.warning("注意点があります。")
            for w in warns[:4]:
                st.write(f"- {w}")
        else:
            st.success("設定チェックは正常です。")

        nav_actions = _suggest_next_actions(
            ctrl=ctrl,
            state_obj=state_obj,
            lock_info=_lock_info(main_dir),
            logs_dir=logs_dir,
            out_dir=out_dir,
        )
        st.markdown("**次にやること（自動提案）**")
        for i, a in enumerate(nav_actions, 1):
            st.write(f"{i}. {a}")

        s1, s2, s3 = st.columns(3)
        with s1:
            if st.button("🧪 safe_paper 適用", use_container_width=True, key="guide_profile_safe"):
                ok, msg = _apply_control_profile(control_path, ctrl, "safe_paper")
                if ok:
                    st.success("safe_paper を適用しました。")
                    st.rerun()
                else:
                    st.error(f"適用失敗: {msg}")
        with s2:
            if st.button("🚀 live_canary 適用", use_container_width=True, key="guide_profile_canary"):
                ok, msg = _apply_control_profile(control_path, ctrl, "live_canary")
                if ok:
                    st.success("live_canary を適用しました。")
                    st.rerun()
                else:
                    st.error(f"適用失敗: {msg}")
        with s3:
            if st.button("🛑 緊急停止", use_container_width=True, key="guide_profile_stop"):
                ok, msg = _apply_control_profile(control_path, ctrl, "emergency_stop")
                if ok:
                    st.success("緊急停止プリセットを適用しました。")
                    st.rerun()
                else:
                    st.error(f"適用失敗: {msg}")

        a1, a2, a3 = st.columns(3)
        with a1:
            if st.button("🔐 live_preflight 実行", use_container_width=True, key="guide_run_preflight"):
                p = main_dir / "tools" / "live_preflight.py"
                if p.exists():
                    _run_action_block("live_preflight", [sys.executable, str(p)], main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        with a2:
            if st.button("✅ run_check.sh 実行", use_container_width=True, key="guide_run_check"):
                p = main_dir / "run_check.sh"
                if p.exists():
                    days = list_log_days(logs_dir) if logs_dir else []
                    cmd = ["bash", str(p)]
                    if days:
                        cmd.append(days[0])
                    _run_action_block("run_check.sh", cmd, main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        with a3:
            if st.button("🧪 ci_check 実行", use_container_width=True, key="guide_run_ci"):
                p = main_dir / "ci_check.py"
                if p.exists():
                    days = list_log_days(logs_dir) if logs_dir else []
                    cmd = [sys.executable, str(p)]
                    if days:
                        cmd.append(days[0])
                    _run_action_block("ci_check", cmd, main_dir)
                else:
                    st.error(f"見つかりません: {p}")

    with st.expander("🧭 タブ別の使い分け", expanded=False):
        st.markdown(
            """
- `ホーム`: 現在状態、次アクション提案、bot起動/停止（2段階ガード）、クイック実行
- `Bot設定`: CONTROLの更新（最重要）
- `成績・分析`: daily_report/audit実行とグラフ確認
- `トレード履歴`: 生ログ確認、原因追跡
- `pos_id・監査`: OPEN/CLOSED整合とissue確認
- `ツール`: preflight/ci_check/run_checkの実行
"""
        )

    with st.expander("🔰 はじめて使う手順（PAPER開始）", expanded=False):
        st.markdown(
            """
1. `Bot設定` で `paper_mode=1`, `live_enabled=0`, `safety_hard_block=0` を確認
2. `ホーム` で `live_preflight` / `run_check.sh` を実行（警告がないことを確認）
3. `ホーム` の `bot起動 (1/2→2/2)` で実行開始
4. 最新ログで `SKIP/OBSERVE/PAPER` が増えることを確認
5. `成績・分析` で `daily_report` と `audit` を実行
6. `pos_id・監査` で OPEN/CLOSED と issues を確認
7. 問題が無い日を連続で作ってから LIVEへ進む
"""
        )

    with st.expander("🚀 LIVE移行手順（段階導入）", expanded=False):
        st.markdown(
            """
1. `ツール` で `live_preflight` を実行し、Keychain/API接続を確認
2. `Bot設定` で `paper_mode=0`, `live_enabled=1`, `rollout_mode=CANARY` を設定
3. `canary_lot`, `daily_loss_limit_pct`, `limit_order_timeout_sec` を小さめで開始
4. `ホーム` で `effective_stage` と `risk_stop` を毎日確認
5. 安定後に `rollout_mode=AUTO` または `LIVE` へ移行
"""
        )

    with st.expander("🧩 pos_id・監査(JSON) の読み方", expanded=False):
        st.markdown(
            """
- 監査JSONがある場合はJSONを最優先表示（Dashboardで再判定しない）
- JSONが無い場合のみログから推定表示
- `ret_pct` は推定（fee未加味、SELL符号反転）
- `issues` に pos_id があればボタンでジャンプして詳細確認
"""
        )

    with st.expander("📈 チャートの読み方（Entry/Exit・損益）", expanded=False):
        st.markdown(
            """
- `成績・分析` の `価格チャート + ENTRY/EXIT` で売買ポイントを確認できます
- 緑▲: BUYエントリー、赤▼: SELLエントリー、黄✕: EXIT
- `累積PnL(推定)` は pos_id 単位の概算（fee未加味）
- `総利益` / `総損失` / `Payoff` / `Profit Factor` で損小利大の傾向を確認
- 要因分析は `Top 利益トレード` / `Top 損失トレード` から `pos_id・監査` へ掘り下げ
"""
        )

    with st.expander("🤖 AI学習の見方", expanded=False):
        st.markdown(
            """
- `ホーム` の `AI学習ステータス` に日次自動更新の結果が表示されます
- `last_day` が当日で更新されていれば、その日は学習判定を実行済みです
- `threshold` が変わった日は、損小利大指標の改善が確認され自動適用されています
- 自動更新を止める場合は `Bot設定` の `ai_auto_train_enabled=0` にします
"""
        )

    with st.expander("🚑 トラブルシュート集", expanded=False):
        st.markdown(
            """
- `logs が空`: botが起動しているか、`today_on` と `trade_enabled` を確認
- `起動できない`: `ホーム` の2段階ガードで `1/2 準備` → `2/2 実行` の順に押す
- `監査JSONが無い`: `成績・分析` タブで `daily_report` 実行
- `risk_stop=ON`: 日次損失ガード発動。翌日リセットまたは設定を見直し
- `LIVEで発注されない`: `live_preflight`、`paper_mode/live_enabled/safety_hard_block` を確認
- `OPENが閉じない`: `PAPER_EXIT_*` ログ有無、issues内容、state.jsonのopen_posを確認
"""
        )

    with st.expander("📘 用語ミニ辞典", expanded=False):
        st.markdown(
            """
- `PAPER`: 仮想約定（実弾なし）
- `CANARY`: 少額LIVEの確認段階
- `effective_stage`: 実効ステージ（PAPER/CANARY/LIVE）
- `risk_stop`: 日次損失ガードによる新規停止フラグ
- `HOLD_OPEN_POS`: 保有継続ログ
"""
        )


def _lock_info(main_dir: Path) -> Dict[str, Any]:
    lock_dir = run_lock_dir(main_dir)
    info = {"exists": False, "alive": False, "pid": None, "state": ""}
    if not lock_dir.exists():
        return info
    info["exists"] = True
    try:
        txt_path = lock_dir / "lockinfo.txt"
        if not txt_path.exists():
            return info
        txt = txt_path.read_text(encoding="utf-8", errors="ignore")
        pid = None
        for line in txt.splitlines():
            if line.startswith("pid="):
                try:
                    pid = int(line.split("=", 1)[1].strip())
                except Exception:
                    pid = None
        info["pid"] = pid
        if pid:
            alive, st = _pid_is_alive(pid)
            info["alive"] = bool(alive)
            info["state"] = st
    except Exception:
        pass
    return info


def _pid_state(pid: int) -> str:
    try:
        p = subprocess.run(
            ["ps", "-p", str(int(pid)), "-o", "stat="],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if p.returncode != 0:
            return ""
        return str((p.stdout or "").strip()).upper()
    except Exception:
        return ""


def _pid_is_alive(pid: int) -> Tuple[bool, str]:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False, ""
    except PermissionError:
        return True, ""
    except Exception:
        return False, ""
    st = _pid_state(pid)
    if st.startswith("Z"):
        return False, st
    return True, st


def _run_subprocess(cmd: List[str], cwd: Path) -> Tuple[int, str]:
    """
    Run and capture output for UI.
    """
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return p.returncode, p.stdout[-4000:]  # limit
    except Exception as e:
        return 999, f"ERROR: {e}"


def _badge(ok: bool, ok_text: str = "OK", ng_text: str = "NG") -> str:
    return f"✅ {ok_text}" if ok else f"❌ {ng_text}"


def _run_action_block(title: str, cmd: List[str], cwd: Path):
    st.markdown(f"**{title}**")
    st.code(" ".join(cmd))
    rc, out = _run_subprocess(cmd, cwd=cwd)
    st.code(out)
    if rc == 0:
        st.success("完了")
    else:
        st.error(f"失敗 rc={rc}")


def _apply_control_profile(control_path: Path, base_ctrl: Dict[str, str], profile_name: str) -> Tuple[bool, str]:
    upd = dict(base_ctrl)
    if profile_name == "safe_paper":
        upd["today_on"] = "1"
        upd["trade_enabled"] = "1"
        upd["paper_mode"] = "1"
        upd["live_enabled"] = "0"
        upd["observe_only"] = "0"
        upd["safety_hard_block"] = "0"
        upd["rollout_mode"] = "AUTO"
    elif profile_name == "live_canary":
        upd["today_on"] = "1"
        upd["trade_enabled"] = "1"
        upd["paper_mode"] = "0"
        upd["live_enabled"] = "1"
        upd["observe_only"] = "0"
        upd["safety_hard_block"] = "0"
        upd["rollout_mode"] = "CANARY"
    elif profile_name == "emergency_stop":
        upd["safety_hard_block"] = "1"
    else:
        return False, f"unknown profile: {profile_name}"
    return write_control_kv_csv(control_path, upd)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(str(v).strip()))
    except Exception:
        return default


def _validate_control_values(ctrl: Dict[str, str]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warns: List[str] = []

    today_on = bval_str(ctrl.get("today_on", "0"))
    trade_enabled = bval_str(ctrl.get("trade_enabled", "0"))
    paper_mode = bval_str(ctrl.get("paper_mode", "1"))
    live_enabled = bval_str(ctrl.get("live_enabled", "0"))
    observe_only = bval_str(ctrl.get("observe_only", "0"))
    safety = bval_str(ctrl.get("safety_hard_block", "0"))

    lot = safe_float(ctrl.get("lot"))
    canary_lot = safe_float(ctrl.get("canary_lot"))
    daily_loss = safe_float(ctrl.get("daily_loss_limit_pct"))
    timeout_sec = _safe_int(ctrl.get("limit_order_timeout_sec", "30"), 30)
    stage_paper_days = _safe_int(ctrl.get("stage_paper_days", "3"), 3)
    stage_canary_days = _safe_int(ctrl.get("stage_canary_days", "3"), 3)
    ai_auto_lookback_days = _safe_int(ctrl.get("ai_auto_lookback_days", "45"), 45)
    ai_auto_train_enabled = bval_str(ctrl.get("ai_auto_train_enabled", "1"))

    if lot is None or lot <= 0:
        errors.append("`lot` は 0 より大きい値が必要です。")
    if canary_lot is None or canary_lot <= 0:
        errors.append("`canary_lot` は 0 より大きい値が必要です。")
    if daily_loss is None:
        errors.append("`daily_loss_limit_pct` は数値で指定してください（例: -1.0）。")
    elif daily_loss >= 0:
        errors.append("`daily_loss_limit_pct` は負値で指定してください（例: -1.0）。")
    if timeout_sec < 5:
        errors.append("`limit_order_timeout_sec` は 5秒以上で指定してください。")
    if stage_paper_days < 0 or stage_canary_days < 0:
        errors.append("`stage_paper_days` / `stage_canary_days` は 0 以上が必要です。")
    if ai_auto_lookback_days < 7:
        errors.append("`ai_auto_lookback_days` は 7 以上で指定してください。")

    if safety:
        warns.append("`safety_hard_block=1` のため、新規発注は停止します。")
    if not today_on:
        warns.append("`today_on=0` のため、本日稼働しません。")
    if not trade_enabled:
        warns.append("`trade_enabled=0` のため、売買ロジックは無効です。")
    if observe_only:
        warns.append("`observe_only=1` のため、発注は行いません。")
    if (not paper_mode) and (not live_enabled):
        warns.append("`paper_mode=0` かつ `live_enabled=0` です。実行しても売買しません。")
    if paper_mode and live_enabled:
        warns.append("`paper_mode=1` のため、`live_enabled=1` でも実行はPAPERになります。")
    if not ai_auto_train_enabled:
        warns.append("`ai_auto_train_enabled=0` のため、AIしきい値の日次自動更新は停止します。")

    product_code = str(ctrl.get("product_code", "BTC_JPY")).strip()
    market_type = str(ctrl.get("market_type", "SPOT")).strip().upper()
    if market_type != "SPOT":
        warns.append(f"`market_type={market_type}` です。段階導入の初期想定は SPOT です。")
    if product_code != "BTC_JPY":
        warns.append(f"`product_code={product_code}` です。初期想定は BTC_JPY です。")

    if (not paper_mode) and live_enabled:
        if not str(ctrl.get("keychain_service", "")).strip():
            errors.append("LIVE時は `keychain_service` が必須です。")
        if not str(ctrl.get("keychain_account_key", "")).strip():
            errors.append("LIVE時は `keychain_account_key` が必須です。")
        if not str(ctrl.get("keychain_account_secret", "")).strip():
            errors.append("LIVE時は `keychain_account_secret` が必須です。")

    return errors, warns


def _suggest_next_actions(
    ctrl: Dict[str, str],
    state_obj: Dict[str, Any],
    lock_info: Dict[str, Any],
    logs_dir: Optional[Path],
    out_dir: Path,
) -> List[str]:
    actions: List[str] = []

    if bval_str(ctrl.get("safety_hard_block", "0")):
        actions.append("緊急停止中です。運用再開するなら `Bot設定` の `safety_hard_block` を OFF にしてください。")
    if not bool(lock_info.get("alive")):
        actions.append("botが停止中です。`ホーム` の `bot起動` で `run.py` を開始してください。")
    if not logs_dir:
        actions.append("logs が見つかりません。起動後に `trade_log_YYYYMMDD.csv` が生成されるか確認してください。")
    if not collect_json_reports(out_dir):
        actions.append("監査JSONが未生成です。`成績・分析` で `daily_report` を実行してください。")
    if bval_str(state_obj.get("_risk_stop", "0")):
        actions.append("`risk_stop=ON` です。日次損失ガード発動中のため、新規ENTRYは停止します。")
    if not bval_str(ctrl.get("ai_auto_train_enabled", "1")):
        actions.append("AI日次自動チューニングがOFFです。必要なら `ai_auto_train_enabled=1` にしてください。")

    paper_mode = bval_str(ctrl.get("paper_mode", "1"))
    live_enabled = bval_str(ctrl.get("live_enabled", "0"))
    if (not paper_mode) and live_enabled:
        if state_obj.get("_live_client_error"):
            actions.append("LIVEクライアントエラーがあります。`ツール` で `live_preflight` を実行して接続を確認してください。")
        else:
            actions.append("LIVE候補です。`live_preflight` と `run_check.sh` を毎日実行してから継続運用してください。")
    else:
        actions.append("まずは安全運用として `safe_paper` プリセットでPAPER運転し、監査が安定してからLIVEへ進んでください。")

    dedup: List[str] = []
    seen = set()
    for a in actions:
        if a in seen:
            continue
        seen.add(a)
        dedup.append(a)
    return dedup[:6]


def _start_runner(main_dir: Path, interval_sec: int = 300, print_tick: bool = False) -> Tuple[bool, str]:
    lock = _lock_info(main_dir)
    if lock.get("alive"):
        return False, f"既に起動中です (pid={lock.get('pid')})"
    run_py = main_dir / "run.py"
    if not run_py.exists():
        return False, f"run.py が見つかりません: {run_py}"

    log_path = main_dir / "run.log"
    cmd = [sys.executable, str(run_py), "--interval", str(max(30, int(interval_sec)))]
    if print_tick:
        cmd.append("--print-tick")

    try:
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(f"\n[dashboard] start request at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            lf.flush()
            subprocess.Popen(
                cmd,
                cwd=str(main_dir),
                stdout=lf,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
    except Exception as e:
        return False, f"起動失敗: {e}"

    deadline = time.time() + 4.0
    while time.time() < deadline:
        chk = _lock_info(main_dir)
        if chk.get("alive"):
            return True, f"起動しました (pid={chk.get('pid')})"
        time.sleep(0.2)
    return True, "起動コマンドを送信しました（lock確認待ち）。"


def _stop_runner(main_dir: Path) -> Tuple[bool, str]:
    lock = _lock_info(main_dir)
    pid = lock.get("pid")
    if not pid:
        return False, ".run_lock の pid が見つかりません。"
    try:
        pid_i = int(pid)
    except Exception:
        return False, f"pid が不正です: {pid}"

    alive0, st0 = _pid_is_alive(pid_i)
    if not alive0:
        if str(st0).startswith("Z"):
            return True, f"既に停止済みです（zombie state={st0}）。親プロセスの回収待ちです。"
        return True, "既に停止済みです。"

    plan = [
        (signal.SIGINT, "SIGINT", 6.0),
        (signal.SIGTERM, "SIGTERM", 4.0),
        (signal.SIGKILL, "SIGKILL", 2.0),
    ]
    for sig, name, wait_sec in plan:
        try:
            os.kill(pid_i, sig)
        except ProcessLookupError:
            return True, f"停止しました（{name}送信時に既に終了）。"
        except Exception as e:
            if name == "SIGKILL":
                return False, f"停止失敗: {e}"
            continue

        deadline = time.time() + float(wait_sec)
        while time.time() < deadline:
            alive_now, _ = _pid_is_alive(pid_i)
            if not alive_now:
                return True, f"停止しました（{name}）。"
            time.sleep(0.2)

    return False, f"停止要求を送信しましたが、pid={pid_i} がまだ生存しています。手動確認してください。"


def _guard_key(action: str) -> str:
    return f"_confirm_guard_until_{action}"


def _clear_guard(action: str) -> None:
    st.session_state.pop(_guard_key(action), None)


def _clear_all_guards() -> None:
    _clear_guard("runner_start")
    _clear_guard("runner_stop")


def _arm_guard(action: str, ttl_sec: int = 0) -> None:
    _clear_all_guards()
    ttl = int(ttl_sec)
    if ttl <= 0:
        st.session_state[_guard_key(action)] = {"armed": True, "expires_at": None}
        return
    st.session_state[_guard_key(action)] = {"armed": True, "expires_at": time.time() + max(3, ttl)}


def _guard_status(action: str) -> Tuple[bool, int, bool]:
    k = _guard_key(action)
    raw = st.session_state.get(k)
    if raw is None:
        return False, 0, False
    # Backward-compat for old sessions storing float timestamp
    if isinstance(raw, (int, float)):
        try:
            remain = int(float(raw) - time.time())
        except Exception:
            _clear_guard(action)
            return False, 0, False
        if remain <= 0:
            _clear_guard(action)
            return False, 0, False
        return True, remain, True

    if not isinstance(raw, dict):
        _clear_guard(action)
        return False, 0, False
    if not bool(raw.get("armed", False)):
        _clear_guard(action)
        return False, 0, False

    expires_at = raw.get("expires_at")
    if expires_at in (None, "", 0):
        return True, 0, False
    try:
        remain = int(float(expires_at) - time.time())
    except Exception:
        _clear_guard(action)
        return False, 0, False
    if remain <= 0:
        _clear_guard(action)
        return False, 0, False
    return True, remain, True


GUARD_TTL_START_DEFAULT = 0
GUARD_TTL_STOP_DEFAULT = 0


def _pick_days_token(days: List[str]) -> Optional[str]:
    if not days:
        return None
    if len(days) == 1:
        return days[0]
    # days list is likely newest-first; token expects oldest_newest in many tools,
    # but user may pass either; here: oldest-newest for clarity
    d_sorted = sorted(days)
    return f"{d_sorted[0]}-{d_sorted[-1]}"


def _format_pct(x: Optional[float]) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    return f"{x:.3f}%"


def _safe_str(x: Any) -> str:
    try:
        return str(x)
    except Exception:
        return ""


def _extract_pos_ids_from_issues(issues: List[str]) -> List[str]:
    # pos_id format: YYYYMMDD-HHMMSS-(BUY|SELL)-NNN
    pat = re.compile(r"(\d{8}-\d{6}-(?:BUY|SELL)-\d{3})")
    found: List[str] = []
    for s in issues:
        for m in pat.finditer(_safe_str(s)):
            found.append(m.group(1))
    # unique preserve order
    seen = set()
    out = []
    for x in found:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


# =========================
# Main
# =========================
def main():
    if "lang" not in st.session_state:
        st.session_state["lang"] = "ja"
    if "pos_search" not in st.session_state:
        st.session_state["pos_search"] = ""

    main_dir = get_main_dir()
    logs_dir = find_logs_dir(main_dir)
    control_path = find_control_csv(main_dir)
    state_path = find_state_json(main_dir)
    out_dir = daily_report_out_dir(main_dir)

    ctrl_now, ctrl_meta = read_control_kv_csv(control_path)
    lock_info = _lock_info(main_dir)
    state_now = load_json(state_path) if state_path.exists() else {}
    if not isinstance(state_now, dict):
        state_now = {}

    # Sidebar
    with st.sidebar:
        st.header(T("app_title"))
        st.caption(T("subtitle"))
        st.divider()

        st.write("**Paths**")
        st.code(
            f"MAIN: {main_dir}\n"
            f"CONTROL: {control_path}\n"
            f"LOGS: {str(logs_dir) if logs_dir else 'NOT FOUND'}\n"
            f"REPORT_OUT: {out_dir}"
        )
        st.divider()

        st.write("**Quick**")
        if st.button("🔄 再読み込み"):
            try:
                st.cache_data.clear()
            except Exception:
                pass
            st.rerun()

        with st.expander("使い方メモ", expanded=False):
            st.markdown(
                """
- まず `Bot設定` でモード確認
- `ホーム` で稼働状態と直近ログ確認
- `成績・分析` で daily_report/audit 実行
- `ツール` で preflight / ci_check 実行
"""
            )

        st.write("**Language**")
        st.session_state["lang"] = st.selectbox("lang", ["ja"], index=0)

    # Header
    ui_status_banner(ctrl_now, lock_info)

    tabs = st.tabs(
        [
            T("tab_home"),
            T("tab_settings"),
            T("tab_analytics"),
            T("tab_history"),
            T("tab_pos"),
            T("tab_guide"),
            T("tab_tools"),
        ]
    )

    # =========================================================
    # TAB: Home
    # =========================================================
    with tabs[0]:
        st.subheader("現在の稼働状況")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("today_on", "ON" if bval_str(ctrl_now.get("today_on")) else "OFF")
        with c2:
            st.metric("mode", "PAPER" if bval_str(ctrl_now.get("paper_mode")) else "LIVE")
        with c3:
            st.metric("observe_only", "ON" if bval_str(ctrl_now.get("observe_only")) else "OFF")
        with c4:
            st.metric("safety_hard_block", "ON" if bval_str(ctrl_now.get("safety_hard_block")) else "OFF")

        state_obj: Dict[str, Any] = dict(state_now)

        c5, c6, c7 = st.columns(3)
        with c5:
            st.metric("live_enabled", "ON" if bval_str(ctrl_now.get("live_enabled")) else "OFF")
        with c6:
            st.metric("effective_stage", str(state_obj.get("_effective_stage", "-")))
        with c7:
            st.metric("risk_stop", "ON" if bval_str(state_obj.get("_risk_stop", "0")) else "OFF")

        st.markdown("### 🤖 AI学習ステータス")
        ai_auto = state_obj.get("_ai_auto_train", {}) if isinstance(state_obj.get("_ai_auto_train"), dict) else {}
        ai1, ai2, ai3, ai4 = st.columns(4)
        with ai1:
            st.metric("auto_train_enabled", "ON" if bval_str(ctrl_now.get("ai_auto_train_enabled", "1")) else "OFF")
        with ai2:
            st.metric("last_day", str(state_obj.get("_ai_auto_train_day", "-")))
        with ai3:
            st.metric("samples", str(ai_auto.get("rows", "-")))
        with ai4:
            st.metric("threshold", f"{ai_auto.get('current_th', '-') } → {ai_auto.get('best_th', '-')}")
        if ai_auto:
            st.caption(
                "auto_train: source={} improve={} applied={}".format(
                    ai_auto.get("source", "-"),
                    ai_auto.get("improve", "-"),
                    ai_auto.get("applied", False),
                )
            )
        else:
            st.caption("まだAI自動学習の実行履歴がありません（bot起動後に日次1回実行）。")

        st.divider()
        st.markdown("### 🗺 運用フロー（推奨順）")
        st.markdown(
            """
1. `Bot設定` でモードと安全スイッチ確認（`paper_mode/live_enabled/safety_hard_block`）
2. `クイック実行` で `live_preflight` と `run_check.sh` を実行
3. `bot 起動/停止` で `run.py` を起動
4. `直近ログ` と `effective_stage/risk_stop` を監視
5. `成績・分析` で `daily_report` と `audit` を更新
"""
        )

        st.divider()
        st.markdown("### 🧭 次にやること（自動提案）")
        for i, step in enumerate(
            _suggest_next_actions(
                ctrl=ctrl_now,
                state_obj=state_obj,
                lock_info=lock_info,
                logs_dir=logs_dir,
                out_dir=out_dir,
            ),
            1,
        ):
            st.write(f"{i}. {step}")

        st.divider()
        st.markdown("### 🎮 bot 起動/停止")
        st.caption("誤操作防止のため2段階ガードです。`1/2 準備` の後に `2/2 実行` を押してください。")
        is_running = bool(lock_info.get("alive"))
        if is_running:
            _clear_guard("runner_start")
        else:
            _clear_guard("runner_stop")
        r1, r2, r3 = st.columns([2, 1, 1])
        with r1:
            run_interval = st.number_input(
                "run.py interval (秒)",
                min_value=30,
                max_value=3600,
                value=300,
                step=30,
                key="home_run_interval_sec",
            )
            run_print_tick = st.toggle("tickログを出力 (--print-tick)", value=False, key="home_run_print_tick")
            gcfg1, gcfg2 = st.columns(2)
            with gcfg1:
                guard_ttl_start = st.number_input(
                    "起動確認秒数 (0=無期限)",
                    min_value=0,
                    max_value=300,
                    value=GUARD_TTL_START_DEFAULT,
                    step=1,
                    key="home_guard_ttl_start",
                )
            with gcfg2:
                guard_ttl_stop = st.number_input(
                    "停止確認秒数 (0=無期限)",
                    min_value=0,
                    max_value=300,
                    value=GUARD_TTL_STOP_DEFAULT,
                    step=1,
                    key="home_guard_ttl_stop",
                )
        with r2:
            start_armed, start_left, start_timed = _guard_status("runner_start")
            if not start_armed:
                if st.button("▶ bot起動 (1/2 準備)", use_container_width=True, disabled=is_running):
                    _arm_guard("runner_start", ttl_sec=int(guard_ttl_start))
                    if int(guard_ttl_start) > 0:
                        st.warning(f"起動準備を有効化しました。{int(guard_ttl_start)}秒以内に `2/2 実行` を押してください。")
                    else:
                        st.warning("起動準備を有効化しました。`2/2 実行` を押してください（無期限待機）。")
                    st.rerun()
            else:
                if start_timed:
                    st.warning(f"起動確認待ち（2/2 実行）: 残り {start_left} 秒")
                    st.caption("※ 秒表示は画面操作時に更新されます。")
                else:
                    st.warning("起動確認待ち（2/2 実行）")
                if st.button("▶ bot起動 (2/2 実行)", type="primary", use_container_width=True, disabled=is_running):
                    _clear_guard("runner_start")
                    ok, msg = _start_runner(main_dir, interval_sec=int(run_interval), print_tick=bool(run_print_tick))
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.warning(msg)
        with r3:
            stop_armed, stop_left, stop_timed = _guard_status("runner_stop")
            if not stop_armed:
                if st.button("■ bot停止 (1/2 準備)", use_container_width=True, disabled=(not is_running)):
                    _arm_guard("runner_stop", ttl_sec=int(guard_ttl_stop))
                    if int(guard_ttl_stop) > 0:
                        st.warning(f"停止準備を有効化しました。{int(guard_ttl_stop)}秒以内に `2/2 実行` を押してください。")
                    else:
                        st.warning("停止準備を有効化しました。`2/2 実行` を押してください（無期限待機）。")
                    st.rerun()
            else:
                if stop_timed:
                    st.warning(f"停止確認待ち（2/2 実行）: 残り {stop_left} 秒")
                    st.caption("※ 秒表示は画面操作時に更新されます。")
                else:
                    st.warning("停止確認待ち（2/2 実行）")
                if st.button("■ bot停止 (2/2 実行)", use_container_width=True, disabled=(not is_running)):
                    _clear_guard("runner_stop")
                    ok, msg = _stop_runner(main_dir)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

        g1, g2 = st.columns([1, 3])
        with g1:
            if st.button("確認状態を解除", use_container_width=True):
                _clear_all_guards()
                st.rerun()
        with g2:
            st.caption(
                "lock status: alive={} pid={} state={}".format(
                    bool(lock_info.get("alive")),
                    lock_info.get("pid"),
                    lock_info.get("state") or "-",
                )
            )

        st.divider()
        st.markdown("### ⚡ クイック実行（ダッシュボード内で完結）")
        st.caption("推奨順: `live_preflight` → `run_check.sh` → `daily_report`。必要に応じて `ci_check` を追加実行。")
        days_for_quick = list_log_days(logs_dir) if logs_dir else []
        q1, q2, q3, q4 = st.columns(4)
        with q1:
            if st.button("🔐 live_preflight 実行", use_container_width=True):
                preflight_py = main_dir / "tools" / "live_preflight.py"
                if preflight_py.exists():
                    _run_action_block("live_preflight", [sys.executable, str(preflight_py)], main_dir)
                else:
                    st.error(f"見つかりません: {preflight_py}")
        with q2:
            if st.button("🧪 ci_check 実行", use_container_width=True):
                ci_py = main_dir / "ci_check.py"
                if not ci_py.exists():
                    st.error("ci_check.py が見つかりません。")
                else:
                    day_arg = days_for_quick[0] if days_for_quick else ""
                    cmd = [sys.executable, str(ci_py)]
                    if day_arg:
                        cmd.append(day_arg)
                    _run_action_block("ci_check", cmd, main_dir)
        with q3:
            if st.button("✅ run_check.sh 実行", use_container_width=True):
                run_sh = main_dir / "run_check.sh"
                if not run_sh.exists():
                    st.error("run_check.sh が見つかりません。")
                else:
                    day_arg = days_for_quick[0] if days_for_quick else ""
                    cmd = ["bash", str(run_sh)]
                    if day_arg:
                        cmd.append(day_arg)
                    _run_action_block("run_check.sh", cmd, main_dir)
        with q4:
            if st.button("📊 daily_report(最新日)", use_container_width=True):
                daily_py = main_dir / "daily_report.py"
                if not daily_py.exists():
                    st.error("daily_report.py が見つかりません。")
                elif not days_for_quick:
                    st.error("対象ログ日が見つかりません。")
                else:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    cmd = [sys.executable, str(daily_py), days_for_quick[0], "--out-dir", str(out_dir)]
                    _run_action_block("daily_report", cmd, main_dir)

        st.divider()
        st.markdown("### 🔔 直近ログ（最新5件）")

        if not logs_dir:
            st.warning("logs/ が見つかりません。")
        else:
            days = list_log_days(logs_dir)
            if not days:
                st.warning("trade_log_YYYYMMDD.csv が見つかりません。")
            else:
                latest_day = days[0]
                p = logs_dir / f"trade_log_{latest_day}.csv"
                df = read_trade_log_df(p, file_cache_token(p))
                if df.empty:
                    st.info("ログは空です。")
                else:
                    cols = [c for c in ["time", "result", "side", "price", "ltp", "spread_pct", "signal", "pos_id", "note"] if c in df.columns]
                    st.dataframe(df[cols].tail(5).iloc[::-1], use_container_width=True)

        st.divider()
        st.markdown("### ✅ 監査JSON（daily_report_out）")
        rep_files = collect_json_reports(out_dir)
        if rep_files:
            st.success(f"監査JSONあり：{len(rep_files)} 件（最新: {rep_files[0].name}）")
        else:
            st.info("監査JSONはまだありません（daily_report を実行してください）。")

    # =========================================================
    # TAB: Settings (CONTROL)
    # =========================================================
    with tabs[1]:
        st.subheader("Bot設定 (CONTROL.csv)")
        st.caption("SPEC: key,value / 未知キー保持 / DEFAULTS外も保存維持")
        st.info("まずはプリセットで状態を切り替え、必要に応じて下の詳細項目を調整する運用がおすすめです。")

        with st.expander("CONTROLメタ情報", expanded=False):
            st.json(ctrl_meta)

        cur_errors, cur_warns = _validate_control_values(ctrl_now)
        with st.expander("🔎 設定の整合性チェック", expanded=bool(cur_errors)):
            if cur_errors:
                st.error("修正必須の項目があります。")
                for x in cur_errors:
                    st.write(f"- {x}")
            else:
                st.success("必須エラーはありません。")
            if cur_warns:
                st.warning("注意事項")
                for x in cur_warns:
                    st.write(f"- {x}")

        st.markdown("### 🎛 クイックプリセット")
        p1, p2, p3 = st.columns(3)
        with p1:
            if st.button("🧪 安全PAPER", use_container_width=True):
                ok, msg = _apply_control_profile(control_path, ctrl_now, "safe_paper")
                if ok:
                    st.success("安全PAPERプリセットを適用しました。")
                    st.rerun()
                else:
                    st.error(f"適用失敗: {msg}")
        with p2:
            if st.button("🚀 LIVE-CANARY", use_container_width=True):
                ok, msg = _apply_control_profile(control_path, ctrl_now, "live_canary")
                if ok:
                    st.success("LIVE-CANARYプリセットを適用しました。")
                    st.rerun()
                else:
                    st.error(f"適用失敗: {msg}")
        with p3:
            if st.button("🛑 緊急停止", use_container_width=True):
                ok, msg = _apply_control_profile(control_path, ctrl_now, "emergency_stop")
                if ok:
                    st.success("緊急停止プリセットを適用しました。")
                    st.rerun()
                else:
                    st.error(f"適用失敗: {msg}")

        # Grouping
        with st.form("control_form"):
            st.markdown("### 🚦 基本スイッチ")
            st.caption("today_on/trade_enabled/safety_hard_block の3つが最優先。挙動が分からない時はここを最初に確認します。")
            a1, a2, a3, a4, a5 = st.columns(5)
            with a1:
                f_today = st.toggle("today_on", value=bval_str(ctrl_now.get("today_on")))
            with a2:
                f_trade = st.toggle("trade_enabled", value=bval_str(ctrl_now.get("trade_enabled")))
            with a3:
                f_paper = st.toggle("paper_mode", value=bval_str(ctrl_now.get("paper_mode")))
            with a4:
                f_live = st.toggle("live_enabled", value=bval_str(ctrl_now.get("live_enabled")))
            with a5:
                f_safety = st.toggle("safety_hard_block", value=bval_str(ctrl_now.get("safety_hard_block")))
            f_observe = st.toggle("observe_only", value=bval_str(ctrl_now.get("observe_only")))

            st.markdown("### 💰 リスク/利確/損切")
            st.caption("ここは売買ロジックの中心パラメータです。大きく変える場合はPAPERで先に確認してください。")
            b1, b2, b3, b4, b5 = st.columns(5)
            with b1:
                f_tp_buy = st.text_input("tp_buy_pct", value=ctrl_now.get("tp_buy_pct", DEFAULTS["tp_buy_pct"]))
            with b2:
                f_tp_sell = st.text_input("tp_sell_pct", value=ctrl_now.get("tp_sell_pct", DEFAULTS["tp_sell_pct"]))
            with b3:
                f_sl = st.text_input("sl_pct", value=ctrl_now.get("sl_pct", DEFAULTS["sl_pct"]))
            with b4:
                f_lot = st.text_input("lot", value=ctrl_now.get("lot", DEFAULTS["lot"]))
            with b5:
                f_win = st.text_input("win_min", value=ctrl_now.get("win_min", DEFAULTS["win_min"]))

            st.markdown("### 🧯 制限/品質フィルタ")
            st.caption("spread上限・日次回数・timeoutモードなど、過剰取引を防ぐ設定です。")
            c1, c2, c3 = st.columns(3)
            with c1:
                f_spread = st.text_input("spread_limit_pct", value=ctrl_now.get("spread_limit_pct", DEFAULTS["spread_limit_pct"]))
            with c2:
                f_max_trades = st.number_input("max_trades_per_day", value=int(float(ctrl_now.get("max_trades_per_day", DEFAULTS["max_trades_per_day"]))), step=1)
            with c3:
                f_timeout_mode = st.selectbox("timeout_mode", ["IGNORE", "EXTEND", "PARTIAL"], index=["IGNORE", "EXTEND", "PARTIAL"].index(ctrl_now.get("timeout_mode", "IGNORE")))

            st.markdown("### 🤖 AI（表示・互換維持）")
            st.caption("AI設定は bot 側で最終判定されます。ここではCONTROL値のみ編集します。")
            d1, d2, d3, d4 = st.columns(4)
            with d1:
                f_ai_enabled = st.toggle("ai_model_enabled (ai_enabledと同期)", value=bval_str(ctrl_now.get("ai_model_enabled")))
            with d2:
                f_ai_mode = st.selectbox("ai_mode", ["OFF", "SCORE_ONLY", "VETO", "GATE"], index=["OFF", "SCORE_ONLY", "VETO", "GATE"].index(ctrl_now.get("ai_mode", "OFF")))
            with d3:
                f_ai_th = st.text_input("ai_threshold", value=ctrl_now.get("ai_threshold", DEFAULTS["ai_threshold"]))
            with d4:
                f_ai_veto = st.text_input("ai_veto_threshold", value=ctrl_now.get("ai_veto_threshold", DEFAULTS["ai_veto_threshold"]))
            d5, d6 = st.columns(2)
            with d5:
                f_ai_auto_train = st.toggle("ai_auto_train_enabled", value=bval_str(ctrl_now.get("ai_auto_train_enabled", DEFAULTS["ai_auto_train_enabled"])))
            with d6:
                f_ai_lookback_days = st.number_input(
                    "ai_auto_lookback_days",
                    min_value=7,
                    max_value=365,
                    value=int(float(ctrl_now.get("ai_auto_lookback_days", DEFAULTS["ai_auto_lookback_days"]))),
                    step=1,
                )
            st.caption("ai_auto_train_enabled=1 で bot 起動時に日次1回だけ閾値自動更新を試行します。")

            st.markdown("### 🚀 LIVE設定")
            st.caption("LIVE導入では paper_mode=0, live_enabled=1 をセットし、段階導入（AUTO/CANARY）で開始します。")
            e1, e2, e3, e4 = st.columns(4)
            rollout_vals = ["AUTO", "PAPER", "CANARY", "LIVE"]
            rollout_now = ctrl_now.get("rollout_mode", "AUTO")
            with e1:
                f_rollout = st.selectbox("rollout_mode", rollout_vals, index=rollout_vals.index(rollout_now) if rollout_now in rollout_vals else 0)
            with e2:
                f_stage_paper_days = st.number_input("stage_paper_days", value=int(float(ctrl_now.get("stage_paper_days", DEFAULTS["stage_paper_days"]))), step=1, min_value=0)
            with e3:
                f_stage_canary_days = st.number_input("stage_canary_days", value=int(float(ctrl_now.get("stage_canary_days", DEFAULTS["stage_canary_days"]))), step=1, min_value=0)
            with e4:
                f_canary_lot = st.text_input("canary_lot", value=ctrl_now.get("canary_lot", DEFAULTS["canary_lot"]))

            f1, f2, f3, f4 = st.columns(4)
            with f1:
                f_daily_loss = st.text_input("daily_loss_limit_pct", value=ctrl_now.get("daily_loss_limit_pct", DEFAULTS["daily_loss_limit_pct"]))
            with f2:
                f_timeout_sec = st.number_input("limit_order_timeout_sec", value=int(float(ctrl_now.get("limit_order_timeout_sec", DEFAULTS["limit_order_timeout_sec"]))), step=1, min_value=5)
            with f3:
                f_offset_ticks = st.number_input("limit_price_offset_ticks", value=int(float(ctrl_now.get("limit_price_offset_ticks", DEFAULTS["limit_price_offset_ticks"]))), step=1, min_value=0)
            with f4:
                f_market_type = st.selectbox("market_type", ["SPOT", "FX", "OTHER"], index=["SPOT", "FX", "OTHER"].index(ctrl_now.get("market_type", "SPOT")) if ctrl_now.get("market_type", "SPOT") in ["SPOT", "FX", "OTHER"] else 0)

            g1, g2 = st.columns(2)
            with g1:
                f_product_code = st.text_input("product_code", value=ctrl_now.get("product_code", DEFAULTS["product_code"]))
            with g2:
                f_keychain_service = st.text_input("keychain_service", value=ctrl_now.get("keychain_service", DEFAULTS["keychain_service"]))

            h1, h2 = st.columns(2)
            with h1:
                f_keychain_key = st.text_input("keychain_account_key", value=ctrl_now.get("keychain_account_key", DEFAULTS["keychain_account_key"]))
            with h2:
                f_keychain_secret = st.text_input("keychain_account_secret", value=ctrl_now.get("keychain_account_secret", DEFAULTS["keychain_account_secret"]))

            # Extra keys view/edit
            st.markdown("### 🧩 extra（DEFAULTS外のキー）")
            extra_keys = sorted([k for k in ctrl_now.keys() if k not in DEFAULTS])
            st.caption("SPEC: 未知キーは消さない。ここで編集した内容も保存されます。")
            extra_json = {k: ctrl_now.get(k, "") for k in extra_keys}
            extra_text = st.text_area(
                "extra (JSON形式で編集可)",
                value=json.dumps(extra_json, ensure_ascii=False, indent=2),
                height=220,
            )

            submitted = st.form_submit_button("💾 保存", use_container_width=True)
            if submitted:
                upd = dict(ctrl_now)  # preserve unknown keys
                upd["today_on"] = "1" if f_today else "0"
                upd["trade_enabled"] = "1" if f_trade else "0"
                upd["paper_mode"] = "1" if f_paper else "0"
                upd["live_enabled"] = "1" if f_live else "0"
                upd["safety_hard_block"] = "1" if f_safety else "0"
                upd["observe_only"] = "1" if f_observe else "0"

                upd["tp_buy_pct"] = str(f_tp_buy).strip()
                upd["tp_sell_pct"] = str(f_tp_sell).strip()
                upd["sl_pct"] = str(f_sl).strip()
                upd["lot"] = str(f_lot).strip()
                upd["win_min"] = str(f_win).strip()

                upd["spread_limit_pct"] = str(f_spread).strip()
                upd["max_trades_per_day"] = str(int(f_max_trades))
                upd["timeout_mode"] = str(f_timeout_mode).strip()

                upd["ai_model_enabled"] = "1" if f_ai_enabled else "0"
                upd["ai_mode"] = str(f_ai_mode).strip()
                upd["ai_threshold"] = str(f_ai_th).strip()
                upd["ai_veto_threshold"] = str(f_ai_veto).strip()
                upd["ai_auto_train_enabled"] = "1" if f_ai_auto_train else "0"
                upd["ai_auto_lookback_days"] = str(int(f_ai_lookback_days))

                upd["rollout_mode"] = str(f_rollout).strip()
                upd["stage_paper_days"] = str(int(f_stage_paper_days))
                upd["stage_canary_days"] = str(int(f_stage_canary_days))
                upd["canary_lot"] = str(f_canary_lot).strip()
                upd["daily_loss_limit_pct"] = str(f_daily_loss).strip()
                upd["limit_order_timeout_sec"] = str(int(f_timeout_sec))
                upd["limit_price_offset_ticks"] = str(int(f_offset_ticks))
                upd["product_code"] = str(f_product_code).strip()
                upd["market_type"] = str(f_market_type).strip()
                upd["keychain_service"] = str(f_keychain_service).strip()
                upd["keychain_account_key"] = str(f_keychain_key).strip()
                upd["keychain_account_secret"] = str(f_keychain_secret).strip()

                # merge extra edits
                try:
                    parsed = json.loads(extra_text) if extra_text.strip() else {}
                    if isinstance(parsed, dict):
                        for k, v in parsed.items():
                            if k in DEFAULTS:
                                continue
                            upd[str(k)] = str(v)
                except Exception:
                    st.error("extraのJSONが壊れています（保存を中止しました）。")
                    st.stop()

                val_errors, val_warns = _validate_control_values(upd)
                if val_errors:
                    st.error("保存を中止しました。修正必須の項目があります。")
                    for x in val_errors:
                        st.write(f"- {x}")
                    st.stop()

                ok, msg = write_control_kv_csv(control_path, upd)
                if ok:
                    st.success(T("save_success"))
                    if val_warns:
                        st.warning("保存しましたが、注意事項があります。")
                        for x in val_warns[:6]:
                            st.write(f"- {x}")
                    time.sleep(0.8)
                    st.rerun()
                else:
                    st.error(f"{T('save_error')}: {msg}")

    # =========================================================
    # TAB: Analytics (buttons only; spec says dashboard has no bot logic)
    # =========================================================
    with tabs[2]:
        st.subheader("成績・分析（生成は daily_report が正）")
        st.caption("手順: 1) 対象日選択 → 2) daily_report/audit実行 → 3) 下の可視化確認。")

        if not logs_dir:
            st.warning("logs/ が見つかりません。")
        else:
            days = list_log_days(logs_dir)
            pick = st.multiselect("対象日(YYYYMMDD)", days, default=days[:3])
            token = _pick_days_token(pick)

            cols = st.columns(4)
            with cols[0]:
                if st.button("▶ daily_report 実行（監査JSON生成）", type="primary", use_container_width=True):
                    daily_py = main_dir / "daily_report.py"
                    if not daily_py.exists():
                        st.error("daily_report.py が見つかりません。")
                    elif not token:
                        st.error("対象日を選択してください。")
                    else:
                        out_dir.mkdir(parents=True, exist_ok=True)
                        cmd = [sys.executable, str(daily_py), token, "--out-dir", str(out_dir)]
                        rc, out = _run_subprocess(cmd, cwd=main_dir)
                        st.code(" ".join(cmd))
                        st.code(out)
                        if rc == 0:
                            st.success("完了（JSONを生成しました）。pos_id・監査(JSON)タブへ。")
                        else:
                            st.error(f"失敗 rc={rc}")

            with cols[1]:
                if st.button("▶ audit 実行（存在する場合）", use_container_width=True):
                    audit_py = main_dir / "audit.py"
                    if not audit_py.exists():
                        st.error("audit.py が見つかりません（未導入ならOK）。")
                    elif not token:
                        st.error("対象日を選択してください。")
                    else:
                        # audit.py expects --day or --start/--end flags; token is like "YYYYMMDD" or "YYYYMMDD-YYYYMMDD"
                        if isinstance(token, str) and "-" in token:
                            start, end = token.split("-", 1)
                            cmd = [sys.executable, str(audit_py), "--start", start, "--end", end, "--out-dir", str(out_dir)]
                        else:
                            cmd = [sys.executable, str(audit_py), "--day", token, "--out-dir", str(out_dir)]
                        rc, out = _run_subprocess(cmd, cwd=main_dir)
                        st.code(" ".join(cmd))
                        st.code(out)
                        if rc == 0:
                            st.success("完了。pos_id・監査(JSON)タブへ。")
                        else:
                            st.error(f"失敗 rc={rc}")
            with cols[2]:
                if st.button("▶ ci_check 実行", use_container_width=True):
                    ci_py = main_dir / "ci_check.py"
                    if not ci_py.exists():
                        st.error("ci_check.py が見つかりません。")
                    else:
                        day_arg = days[0] if days else ""
                        cmd = [sys.executable, str(ci_py)]
                        if day_arg:
                            cmd.append(day_arg)
                        rc, out = _run_subprocess(cmd, cwd=main_dir)
                        st.code(" ".join(cmd))
                        st.code(out)
                        if rc == 0:
                            st.success("完了。")
                        else:
                            st.error(f"失敗 rc={rc}")
            with cols[3]:
                if st.button("▶ live_preflight 実行", use_container_width=True):
                    preflight_py = main_dir / "tools" / "live_preflight.py"
                    if not preflight_py.exists():
                        st.error("tools/live_preflight.py が見つかりません。")
                    else:
                        cmd = [sys.executable, str(preflight_py)]
                        rc, out = _run_subprocess(cmd, cwd=main_dir)
                        st.code(" ".join(cmd))
                        st.code(out)
                        if rc == 0:
                            st.success("完了。")
                        else:
                            st.error(f"失敗 rc={rc}")

            st.divider()
            st.markdown("### 📈 可視化（ログ由来の推定）")
            st.caption("entry/exit の位置、累積推移、勝敗内訳をこのタブ内で確認できます（すべて推定・fee未加味）。")
            with st.expander("📘 成績タブの見方（運用ガイド）", expanded=False):
                st.markdown(
                    """
1. `価格チャート + ENTRY/EXIT` で「どこで入ってどこで出たか」を確認
2. `累積損益カーブ` で右肩下がりが続いていないか確認
3. `損益内訳` で `総利益` と `総損失`、`Payoff` を確認
4. `日次サマリー` で日ごとの崩れを確認
5. 具体的な要因は `トレード履歴` / `pos_id・監査` で深掘り
"""
                )
            if not pick:
                st.info("可視化するには対象日を1日以上選択してください。")
            else:
                raw_rows: List[Dict[str, Any]] = []
                for d in sorted(pick):
                    p = logs_dir / f"trade_log_{d}.csv"
                    if p.exists():
                        raw_rows.extend(_read_csv_dict_rows(p))

                df_pos = build_position_metrics_from_logs(raw_rows)
                price_df, event_df = build_trade_timeline_frames(raw_rows)
                if df_pos.empty:
                    st.info("可視化対象の pos_id データがありません。")
                else:
                    df_closed = df_pos[(df_pos["status"] == "CLOSED") & (df_pos["ret_pct_est"].notna())].copy()
                    df_closed["cum_ret_pct"] = df_closed["ret_pct_est"].cumsum()
                    if "pnl_est" in df_closed.columns:
                        df_closed["cum_pnl_est"] = df_closed["pnl_est"].fillna(0.0).cumsum()
                    else:
                        df_closed["cum_pnl_est"] = 0.0
                    wins = int((df_closed["ret_pct_est"] > 0).sum())
                    losses = int((df_closed["ret_pct_est"] < 0).sum())
                    total = int(len(df_closed))
                    win_rate = (wins / total * 100.0) if total > 0 else 0.0
                    total_ret = float(df_closed["ret_pct_est"].sum()) if total > 0 else 0.0
                    total_pnl = float(df_closed["pnl_est"].fillna(0.0).sum()) if total > 0 else 0.0
                    gross_profit = float(df_closed.loc[df_closed["pnl_est"] > 0, "pnl_est"].sum()) if total > 0 else 0.0
                    gross_loss = float(df_closed.loc[df_closed["pnl_est"] < 0, "pnl_est"].sum()) if total > 0 else 0.0
                    avg_win = float(df_closed.loc[df_closed["pnl_est"] > 0, "pnl_est"].mean()) if wins > 0 else 0.0
                    avg_loss_abs = abs(float(df_closed.loc[df_closed["pnl_est"] < 0, "pnl_est"].mean())) if losses > 0 else 0.0
                    payoff = (avg_win / avg_loss_abs) if avg_loss_abs > 0 else 0.0
                    pf = (gross_profit / abs(gross_loss)) if gross_loss < 0 else 0.0

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("クローズ数", f"{total}")
                    m2.metric("勝率", f"{win_rate:.1f}%")
                    m3.metric("累積ret_pct(推定)", f"{total_ret:.3f}%")
                    m4.metric("累積PnL(推定)", f"{total_pnl:,.4f}")
                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric("総利益(推定)", f"{gross_profit:,.4f}")
                    k2.metric("総損失(推定)", f"{gross_loss:,.4f}")
                    k3.metric("Payoff", f"{payoff:.3f}")
                    k4.metric("Profit Factor", f"{pf:.3f}")

                    if total == 0:
                        st.warning("CLOSEDポジションが無いため、損益チャートを描画できません。")
                    elif not HAS_PLOTLY:
                        st.warning("Plotly未導入のため簡易チャートを表示します。`pip install plotly` を追加すると高機能表示になります。")
                        line_src = df_closed.set_index("time_dt")[["cum_ret_pct"]].copy()
                        line_src.columns = ["累積ret_pct(推定)"]
                        st.line_chart(line_src)
                        bar_src = df_closed.set_index("time_dt")[["ret_pct_est"]].copy()
                        bar_src.columns = ["ret_pct(推定)"]
                        st.bar_chart(bar_src)
                    else:
                        st.markdown("#### 🧭 価格チャート + ENTRY/EXIT（どこで売買したか）")
                        show_bidask = st.toggle("best_bid / best_ask も表示", value=False, key="analytics_show_bidask")
                        if price_df.empty:
                            st.info("価格系列（ltp）が不足しているため、価格チャートを表示できません。")
                        else:
                            fig_price = go.Figure()
                            fig_price.add_trace(
                                go.Scatter(
                                    x=price_df["time_dt"],
                                    y=price_df["ltp"],
                                    mode="lines",
                                    name="LTP",
                                    line=dict(color="#1f77b4", width=2),
                                )
                            )
                            if show_bidask:
                                if "best_bid" in price_df.columns:
                                    fig_price.add_trace(
                                        go.Scatter(
                                            x=price_df["time_dt"],
                                            y=price_df["best_bid"],
                                            mode="lines",
                                            name="best_bid",
                                            line=dict(color="#2ca02c", width=1, dash="dot"),
                                            opacity=0.8,
                                        )
                                    )
                                if "best_ask" in price_df.columns:
                                    fig_price.add_trace(
                                        go.Scatter(
                                            x=price_df["time_dt"],
                                            y=price_df["best_ask"],
                                            mode="lines",
                                            name="best_ask",
                                            line=dict(color="#d62728", width=1, dash="dot"),
                                            opacity=0.8,
                                        )
                                    )

                            if not event_df.empty:
                                eb = event_df[event_df["event_kind"] == "ENTRY_BUY"]
                                es = event_df[event_df["event_kind"] == "ENTRY_SELL"]
                                ex = event_df[event_df["event_kind"] == "EXIT"]
                                if not eb.empty:
                                    fig_price.add_trace(
                                        go.Scatter(
                                            x=eb["time_dt"],
                                            y=eb["price_plot"],
                                            mode="markers",
                                            name="ENTRY BUY",
                                            marker=dict(color="#00CC96", symbol="triangle-up", size=11),
                                            text=eb["pos_id"],
                                            hovertemplate="ENTRY BUY<br>%{x}<br>price=%{y}<br>pos_id=%{text}<extra></extra>",
                                        )
                                    )
                                if not es.empty:
                                    fig_price.add_trace(
                                        go.Scatter(
                                            x=es["time_dt"],
                                            y=es["price_plot"],
                                            mode="markers",
                                            name="ENTRY SELL",
                                            marker=dict(color="#EF553B", symbol="triangle-down", size=11),
                                            text=es["pos_id"],
                                            hovertemplate="ENTRY SELL<br>%{x}<br>price=%{y}<br>pos_id=%{text}<extra></extra>",
                                        )
                                    )
                                if not ex.empty:
                                    fig_price.add_trace(
                                        go.Scatter(
                                            x=ex["time_dt"],
                                            y=ex["price_plot"],
                                            mode="markers",
                                            name="EXIT",
                                            marker=dict(color="#FFB000", symbol="x", size=11),
                                            text=ex["pos_id"],
                                            hovertemplate="EXIT<br>%{x}<br>price=%{y}<br>pos_id=%{text}<extra></extra>",
                                        )
                                    )

                            fig_price.update_layout(
                                title="価格ラインと売買ポイント（推定）",
                                xaxis_title="時刻",
                                yaxis_title="価格",
                                plot_bgcolor="rgba(0,0,0,0)",
                                paper_bgcolor="rgba(0,0,0,0)",
                                margin=dict(l=10, r=10, t=48, b=10),
                                legend=dict(orientation="h"),
                            )
                            st.plotly_chart(fig_price, use_container_width=True)
                            st.caption("ENTRY BUY=緑▲ / ENTRY SELL=赤▼ / EXIT=黄✕")

                        fig_top_col, fig_pie_col = st.columns([2, 1])
                        with fig_top_col:
                            fig_line = go.Figure()
                            fig_line.add_trace(
                                go.Scatter(
                                    x=df_closed["time_dt"],
                                    y=df_closed["cum_ret_pct"],
                                    mode="lines+markers",
                                    name="累積ret_pct(推定)",
                                    line=dict(color="#00CC96", width=3),
                                    fill="tozeroy",
                                    fillcolor="rgba(0,204,150,0.12)",
                                )
                            )
                            fig_line.update_layout(
                                title="累積損益カーブ（ret_pct推定）",
                                xaxis_title="時刻",
                                yaxis_title="累積ret_pct(%)",
                                plot_bgcolor="rgba(0,0,0,0)",
                                paper_bgcolor="rgba(0,0,0,0)",
                                margin=dict(l=10, r=10, t=48, b=10),
                            )
                            st.plotly_chart(fig_line, use_container_width=True)

                        with fig_pie_col:
                            pie_df = pd.DataFrame({"結果": ["Win", "Loss"], "回数": [wins, losses]})
                            fig_pie = px.pie(
                                pie_df,
                                values="回数",
                                names="結果",
                                hole=0.45,
                                color="結果",
                                color_discrete_map={"Win": "#00CC96", "Loss": "#EF553B"},
                                title="勝敗比率",
                            )
                            st.plotly_chart(fig_pie, use_container_width=True)

                        df_closed["pl_type"] = np.where(df_closed["ret_pct_est"] >= 0, "Profit", "Loss")
                        fig_bar = px.bar(
                            df_closed,
                            x="time_dt",
                            y="ret_pct_est",
                            color="pl_type",
                            color_discrete_map={"Profit": "#00CC96", "Loss": "#EF553B"},
                            title="各トレード損益（ret_pct推定）",
                        )
                        fig_bar.update_layout(
                            xaxis_title="時刻",
                            yaxis_title="ret_pct(%)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            paper_bgcolor="rgba(0,0,0,0)",
                            margin=dict(l=10, r=10, t=48, b=10),
                        )
                        st.plotly_chart(fig_bar, use_container_width=True)

                    st.markdown("### 🏆 勝ち負け内訳（推定）")
                    if total > 0:
                        rank_df = df_closed.copy()
                        rank_df = rank_df.sort_values("pnl_est", ascending=False)
                        r1, r2 = st.columns(2)
                        with r1:
                            st.markdown("**Top 利益トレード**")
                            st.dataframe(
                                rank_df[["pos_id", "side", "entry_time", "exit_time", "pnl_est", "ret_pct_est"]].head(5),
                                use_container_width=True,
                            )
                        with r2:
                            st.markdown("**Top 損失トレード**")
                            st.dataframe(
                                rank_df[["pos_id", "side", "entry_time", "exit_time", "pnl_est", "ret_pct_est"]]
                                .tail(5)
                                .sort_values("pnl_est", ascending=True),
                                use_container_width=True,
                            )

                    st.markdown("### 📅 日次サマリー（推定）")
                    daily = df_closed.copy()
                    daily["day"] = daily["time_dt"].dt.strftime("%Y-%m-%d")
                    daily_sum = (
                        daily.groupby("day", dropna=False)
                        .agg(
                            trades=("pos_id", "count"),
                            win_rate_pct=("ret_pct_est", lambda x: float((x > 0).mean() * 100.0) if len(x) else 0.0),
                            ret_pct_sum=("ret_pct_est", "sum"),
                            pnl_est_sum=("pnl_est", "sum"),
                        )
                        .reset_index()
                    )
                    st.dataframe(daily_sum, use_container_width=True)

                    with st.expander("詳細データ（pos_idごとの推定）", expanded=False):
                        show_cols = [
                            c
                            for c in [
                                "pos_id",
                                "status",
                                "side",
                                "entry_time",
                                "exit_time",
                                "entry_price",
                                "exit_ltp",
                                "size",
                                "ret_pct_est",
                                "pnl_est",
                            ]
                            if c in df_pos.columns
                        ]
                        st.dataframe(df_pos[show_cols], use_container_width=True)
                        csv_bytes = df_pos[show_cols].to_csv(index=False).encode("utf-8-sig")
                        st.download_button(
                            "CSVダウンロード（pos_id推定データ）",
                            data=csv_bytes,
                            file_name=f"dashboard_pos_est_{token}.csv",
                            mime="text/csv",
                            use_container_width=True,
                        )

                    st.caption("※ すべて推定値（fee未加味）。最終的な正は daily_report / audit 出力を参照してください。")

        st.divider()
        st.caption("Dashboardは“表示と操作”に徹する。判断・集計ロジックは bot / daily_report が正（SPEC）。")

    # =========================================================
    # TAB: History
    # =========================================================
    with tabs[3]:
        st.subheader("トレード履歴（raw）")
        st.caption("原因調査しやすいように、result・キーワード・件数で絞り込めます。")
        if not logs_dir:
            st.warning("logs/ が見つかりません。")
        else:
            days = list_log_days(logs_dir)
            if not days:
                st.warning("trade_log がありません。")
            else:
                sel = st.selectbox("日付", days, index=0)
                p = logs_dir / f"trade_log_{sel}.csv"
                df = read_trade_log_df(p, file_cache_token(p))
                if df.empty:
                    st.info("空です。")
                else:
                    f1, f2, f3, f4 = st.columns(4)
                    with f1:
                        results = sorted({str(x) for x in df.get("result", pd.Series(dtype=str)).dropna().tolist()}) if "result" in df.columns else []
                        selected_results = st.multiselect("result絞り込み", results, default=[])
                    with f2:
                        keyword = st.text_input("キーワード検索(note/pos_id)", value="")
                    with f3:
                        desc = st.toggle("新しい順", value=True)
                    with f4:
                        max_rows_upper = max(10, int(len(df)))
                        max_rows_default = min(300, max_rows_upper)
                        max_rows = st.number_input(
                            "表示件数",
                            min_value=10,
                            max_value=max_rows_upper,
                            value=max_rows_default,
                            step=10,
                        )

                    dff = df.copy()
                    if selected_results and "result" in dff.columns:
                        dff = dff[dff["result"].astype(str).isin(selected_results)]
                    if keyword:
                        kw = str(keyword).strip()
                        cols_for_kw = [c for c in ["note", "pos_id", "result", "side"] if c in dff.columns]
                        if cols_for_kw:
                            mask = False
                            for c in cols_for_kw:
                                mask = mask | dff[c].astype(str).str.contains(kw, na=False)
                            dff = dff[mask]

                    if "time_dt" in dff.columns:
                        dff = dff.sort_values("time_dt", ascending=not desc)
                    else:
                        dff = dff.iloc[::-1] if desc else dff
                    dff = dff.head(int(max_rows))

                    s1, s2, s3 = st.columns(3)
                    s1.metric("表示行数", len(dff))
                    s2.metric("PAPER", int((dff["result"] == "PAPER").sum()) if "result" in dff.columns else 0)
                    s3.metric("EXIT", int(dff["result"].astype(str).str.startswith("PAPER_EXIT").sum()) if "result" in dff.columns else 0)

                    cols = [c for c in ["time", "pos_id", "result", "side", "price", "ltp", "spread_pct", "trend", "signal", "note"] if c in df.columns]
                    st.dataframe(dff[cols], use_container_width=True)

    # =========================================================
    # TAB: pos_id / Audit(JSON) — SPEC Core
    # =========================================================
    with tabs[4]:
        st.subheader("pos_id・監査(JSON)（SPEC中核）")
        st.caption("まずは監査JSON優先で確認し、必要時のみログ推定へ切り替えてください。")

        rep_files = collect_json_reports(out_dir)
        use_json = False
        selected_json: Optional[Path] = None
        audit_obj: Optional[Dict[str, Any]] = None

        left, right = st.columns([2, 1])
        with left:
            if rep_files:
                use_json = st.toggle("監査JSONを使う（最優先）", value=True)
                if use_json:
                    selected_json = st.selectbox("JSONファイル", rep_files, format_func=lambda p: p.name)
            else:
                st.info("daily_report_out に JSON がありません。ログから推定表示します。")

        with right:
            st.text_input("pos_id 検索", key="pos_search")

        # load
        posviews: List[PosView] = []
        issues: List[str] = []
        mode_label = ""

        if use_json and selected_json:
            audit_obj = load_json(selected_json)
            if not audit_obj:
                st.error("JSONが読めません（壊れている/形式不一致）。ログ推定に切り替えてください。")
            else:
                st.info(T("audit_json_priority"))
                # normalize JSON to meet SPEC contracts (fill missing keys, normalize issues)
                try:
                    audit_obj = normalize_daily_report_json(audit_obj)
                except Exception:
                    pass
                posviews, issues = posviews_from_audit_json(audit_obj)
                mode_label = f"JSON: {selected_json.name}"
                # Some daily_report variants don't emit top-level per_pos.
                # In that case, supplement pos_id table from the corresponding raw log day.
                if not posviews and logs_dir:
                    day8 = str(dig_first(audit_obj, ["meta", "target_day8"], default="")).strip()
                    cand_days: List[str] = []
                    if re.fullmatch(r"\d{8}", day8):
                        cand_days.append(day8)
                    if not cand_days:
                        cand_days = list_log_days(logs_dir)[:1]
                    rows: List[Dict[str, Any]] = []
                    for d in cand_days:
                        p = logs_dir / f"trade_log_{d}.csv"
                        if p.exists():
                            rows.extend(_read_csv_dict_rows(p))
                    if rows:
                        pv_fb, issues_fb = posviews_from_logs(rows)
                        if pv_fb:
                            st.warning("JSONに per_pos が無いため、pos_id一覧はログ推定で補完表示しています。")
                            posviews = pv_fb
                            for it in issues_fb:
                                if it not in issues:
                                    issues.append(it)
                            mode_label = f"JSON: {selected_json.name} + LOG_FALLBACK: {','.join(cand_days)}"
        else:
            # fallback
            if not logs_dir:
                st.warning("logs/ が見つかりません。")
            else:
                # choose days to load
                days = list_log_days(logs_dir)
                pick = st.multiselect("推定対象日（ログ）", days, default=days[:7], help="JSONが無い時のみ使う推定。")
                rows: List[Dict[str, Any]] = []
                for d in pick:
                    p = logs_dir / f"trade_log_{d}.csv"
                    if p.exists():
                        rows.extend(_read_csv_dict_rows(p))
                st.warning(T("fallback_mode"))
                posviews, issues = posviews_from_logs(rows)
                mode_label = f"LOG_FALLBACK: {len(pick)} day(s)"

        st.caption(f"表示モード: {mode_label}")

        # Filter by search
        q = (st.session_state.get("pos_search") or "").strip()
        if q:
            posviews = [p for p in posviews if q in p.pos_id]

        # Summary
        st.divider()
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("TOTAL", len(posviews))
        s2.metric("OPEN", sum(1 for p in posviews if p.status == "OPEN"))
        s3.metric("CLOSED", sum(1 for p in posviews if p.status == "CLOSED"))
        s4.metric("UNKNOWN/ERROR", sum(1 for p in posviews if p.status in ("UNKNOWN", "ERROR")))

        # Table
        st.markdown("### 🧩 pos_id 一覧")
        table_rows = []
        for p in posviews:
            table_rows.append(
                {
                    "pos_id": p.pos_id,
                    "status": p.status,
                    "entry_time": p.entry_time or "-",
                    "side": p.entry_side or "-",
                    "entry_price": p.entry_price if p.entry_price is not None else np.nan,
                    "exit_time": p.exit_time or "-",
                    "exit_result": p.exit_result or "-",
                    "exit_ltp": p.exit_ltp if p.exit_ltp is not None else np.nan,
                    "ret_pct(推定)": p.ret_pct_est if p.ret_pct_est is not None else np.nan,
                    "ai_score": p.ai_score if p.ai_score is not None else np.nan,
                    "mae": p.mae if p.mae is not None else np.nan,
                    "mfe": p.mfe if p.mfe is not None else np.nan,
                    "source": p.source,
                }
            )
        dfp = pd.DataFrame(table_rows)
        if not dfp.empty:
            st.dataframe(dfp, use_container_width=True)
        else:
            st.info("表示対象がありません。")

        st.info("⚠️ ret_pct は **推定**（fee未加味）。SELLは符号反転。")

        # Detail viewer
        st.divider()
        st.markdown("### 🔎 詳細")
        if posviews:
            sel_pid = st.selectbox("pos_id", [p.pos_id for p in posviews], index=0)
            p = next((x for x in posviews if x.pos_id == sel_pid), None)
            if p:
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Entry**")
                    st.json(
                        {
                            "time": p.entry_time,
                            "side": p.entry_side,
                            "price": p.entry_price,
                        }
                    )
                with c2:
                    st.markdown("**Exit**")
                    st.json(
                        {
                            "time": p.exit_time,
                            "result": p.exit_result,
                            "ltp": p.exit_ltp,
                        }
                    )

                st.markdown("**Status**")
                st.code(f"{p.status}  (source={p.source})")

                st.markdown("**Estimate (fee未加味)**")
                st.code(f"ret_pct = {_format_pct(p.ret_pct_est)}  /  note: {p.notes}")

                if p.ai_score is not None or p.ai_pass is not None:
                    st.markdown("**AI**")
                    st.json({"score": p.ai_score, "pass": p.ai_pass})

                if p.mae is not None or p.mfe is not None:
                    st.markdown("**MAE/MFE**")
                    st.json({"mae": p.mae, "mfe": p.mfe})

        # issues
        st.divider()
        st.markdown("### 🚨 issues（pos_idジャンプ）")
        if not issues:
            st.success("issues はありません。")
        else:
            pos_in_issues = _extract_pos_ids_from_issues(issues)
            if pos_in_issues:
                st.caption("pos_id抽出 → ボタンで検索欄へ反映（ジャンプ）")
                btn_cols = st.columns(min(4, max(1, len(pos_in_issues))))
                for i, pid in enumerate(pos_in_issues):
                    with btn_cols[i % len(btn_cols)]:
                        if st.button(f"🔎 {pid}", use_container_width=True):
                            st.session_state["pos_search"] = pid
                            st.rerun()

            st.markdown("**raw issues**")
            for it in issues:
                # If issue is a dict with severity, code, pos_id, message -> colorize
                if isinstance(it, dict):
                    sev = str(it.get("severity", "INFO")).upper()
                    code = it.get("code")
                    pid = it.get("pos_id")
                    msg = it.get("message") or it.get("msg") or ""
                    line = f"[{sev}]"
                    if code:
                        line += f" {code}"
                    if pid:
                        line += f" pos_id={pid}"
                    if msg:
                        line += f" — {msg}"
                    if sev in ("FATAL", "ERROR"):
                        st.error(line)
                    elif sev in ("WARN", "WARNING"):
                        st.warning(line)
                    else:
                        st.info(line)
                else:
                    st.write(f"- {it}")

    # =========================================================
    # TAB: Guide
    # =========================================================
    with tabs[5]:
        ui_manual_tab(ctrl_now, state_now, logs_dir, out_dir, main_dir, control_path)

    # =========================================================
    # TAB: Tools
    # =========================================================
    with tabs[6]:
        st.subheader("ツール・メンテナンス")
        st.caption("CLIに戻らず運用確認できるように、主要コマンドをここから実行できます。")

        st.markdown("### 🛠 メンテ実行")
        t1, t2, t3, t4 = st.columns(4)
        with t1:
            if st.button("live_preflight", use_container_width=True):
                p = main_dir / "tools" / "live_preflight.py"
                if p.exists():
                    _run_action_block("live_preflight", [sys.executable, str(p)], main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        with t2:
            if st.button("ci_check", use_container_width=True):
                p = main_dir / "ci_check.py"
                if p.exists():
                    days = list_log_days(logs_dir) if logs_dir else []
                    cmd = [sys.executable, str(p)]
                    if days:
                        cmd.append(days[0])
                    _run_action_block("ci_check", cmd, main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        with t3:
            if st.button("run_check.sh", use_container_width=True):
                p = main_dir / "run_check.sh"
                if p.exists():
                    days = list_log_days(logs_dir) if logs_dir else []
                    cmd = ["bash", str(p)]
                    if days:
                        cmd.append(days[0])
                    _run_action_block("run_check.sh", cmd, main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        with t4:
            if st.button("spec_check(strict)", use_container_width=True):
                p = main_dir / "spec_check.py"
                days = list_log_days(logs_dir) if logs_dir else []
                if p.exists() and days:
                    _run_action_block("spec_check --strict", [sys.executable, str(p), days[0], "--strict"], main_dir)
                elif not days:
                    st.error("対象ログ日が見つかりません。")
                else:
                    st.error(f"見つかりません: {p}")

        st.divider()
        st.markdown("### 🧪 生成済みレポート一覧")
        rep_files = collect_json_reports(out_dir)
        if rep_files:
            st.dataframe(pd.DataFrame({"file": [p.name for p in rep_files[:50]]}), use_container_width=True)
        else:
            st.info("JSONなし")

        st.divider()
        st.markdown("### 🧷 state.json（存在すれば表示）")
        if state_path.exists():
            try:
                st.json(load_json(state_path) or {})
            except Exception:
                st.warning("state.json を読めません。")
        else:
            st.info("state.json はありません（未作成でもOK）。")

        st.markdown("### 🧯 環境情報")
        st.code(
            f"Python: {sys.version}\n"
            f"MAIN: {get_main_dir()}\n"
            f"CONTROL: {control_path}\n"
            f"LOGS: {str(logs_dir) if logs_dir else 'NOT FOUND'}\n"
            f"REPORT_OUT: {out_dir}"
        )


if __name__ == "__main__":
    main()
