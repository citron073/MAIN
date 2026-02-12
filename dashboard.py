# MAIN/dashboard.py
# ============================================================
# Trading Bot Dashboard (v3-FULL+)  ★bot.py(AI搭載) 完全整合・初心者UI
#
# ✅ 目的（最終網羅版 + 追加分析）
# - CONTROL.csv (key,value) をDashboardで完全操作（追加キーを落とさない）
# - daily_report / audit をボタン実行（subprocess）し、監査JSONを取り込み
# - pos_id OPEN/CLOSED 可視化（監査JSON優先 / フォールバック）
# - issuesのpos_idクリック → 検索欄へ反映 + 詳細ジャンプ
# - 損益・勝率・連勝/連敗・平均勝ち/負け・価格帯（エントリー価格分布）を表示
# - 初心者UI（タブ構成 / ヒント / SAFETYバナー）
#
# ★追加（今回）
# 1) AIスコア × MAE/MFE（散布図）
# 2) AI ON / OFF 比較（KPI/テーブル）
# 3) 時間帯 × AIスコア（ヒートマップ/帯別）
#
# 起動:
#   cd /Users/tani/trading_bot/trading_bot/MAIN
#   python3 -m streamlit run dashboard.py
# ============================================================

from __future__ import annotations

import csv
import json
import sys
import time
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

import pandas as pd
import streamlit as st
import numpy as np
import altair as alt


# =========================
# i18n（必要最低限。今後拡張しても書き換え不要）
# =========================
I18N = {
    "ja": {
        "app_title": "Trading Bot Dashboard (v3-FULL+)",
        "settings": "設定",
        "lang": "Language / 言語",
        "reload": "再読込",
        "paths": "Paths",
        "main_dir": "MAIN",
        "logs_dir": "logs",
        "control_file": "CONTROL.csv",
        "state_file": "state.json",
        "audit_out_dir": "daily_report_out",

        "tab_overview": "① 概要（勝ち負け）",
        "tab_positions": "② pos_id（OPEN/CLOSED）",
        "tab_logs": "③ ログ分析",
        "tab_control": "④ CONTROL（設定）",
        "tab_tools": "⑤ ツール（実行）",
        "tab_state": "⑥ state.json",

        "missing_logs": "logs が見つかりません（trade_log_*.csv が無い）",
        "missing_trade_log": "trade_log が見つかりません",
        "missing_control": "CONTROL.csv が見つかりません（保存ボタンで作成できます）",

        "time_filter": "時間フィルタ 10:00-16:00（16は含めない）",
        "trade_log_file": "trade_log file",
        "file": "FILE",

        "audit_integration": "監査（daily_report）統合",
        "audit_loaded": "監査JSONを読み込みました",
        "audit_not_found": "監査JSONが見つかりません（必要なら生成）",
        "refresh_audit": "▶ 選択範囲で daily_report を実行して取り込む",

        "tools_panel": "ツール（実行）",
        "run_daily_report": "▶ daily_report 実行",
        "run_audit": "▶ audit 実行",
        "script_args": "引数（任意：空白区切り）",
        "script_not_found": "ファイルが見つかりません",
        "script_output": "実行結果（stdout/stderr）",

        "ai_panel": "AI Gate（bot判断 / bot.py整合）",
        "ai_control_hint": "AIは bot.py 側で「PAPER直前」に最終フィルタとして働きます。Dashboardは CONTROL を更新するだけです。",

        "control_panel": "CONTROL 更新（Dashboard → bot）",
        "control_hint": "Dashboard から CONTROL.csv（key,value）を更新します（bot.py が読む想定）",
        "load_control": "CONTROLを読み込み",
        "save_control": "CONTROLを保存（更新）",
        "saved_ok": "保存しました",
        "saved_ng": "保存に失敗",
        "control_preview": "CONTROL 現在値",
        "control_updated_at": "最終更新",
        "control_schema_note": "※ CONTROL項目は増減OK。bot.py 側が参照する key 名と一致させてください。",

        "pos_view": "pos_id 可視化（OPEN / CLOSED）",
        "pos_status": "status",
        "pos_side": "side",
        "pos_search": "検索（pos_id / note）",
        "pos_detail": "pos_id 詳細（時系列）",
        "target_logs": "対象ログ",
        "latest_1": "直近1日",
        "latest_3": "直近3日",
        "latest_7": "直近7日",
        "manual": "手動選択",
        "loading_days": "読み込み",

        "data_source": "データ源",
        "source_audit": "監査（daily_report）",
        "source_fallback": "推定（ログ集計）",
        "audit_issues": "監査 issues（WARN/ERROR）",

        "overview_title": "今日/選択日の勝ち負けが一発で分かる",
        "kpi_trades": "トレード数",
        "kpi_closed": "決済数（CLOSED）",
        "kpi_winrate": "勝率",
        "kpi_pnl": "推定損益（%）",
        "kpi_avg_win": "平均勝ち（%）",
        "kpi_avg_loss": "平均負け（%）",
        "kpi_streak": "最大連勝 / 最大連敗",
        "price_band": "価格帯（エントリー価格）",

        "notes": "メモ",
        "state_view": "state.json（_control_snapshot / _open_pos）を見る",
        "snapshot": "_control_snapshot",
        "open_pos": "_open_pos",
    },
    "en": {
        "app_title": "Trading Bot Dashboard (v3-FULL+)",
        "settings": "Settings",
        "lang": "Language",
        "reload": "Reload",
        "paths": "Paths",
        "main_dir": "MAIN",
        "logs_dir": "logs",
        "control_file": "CONTROL.csv",
        "state_file": "state.json",
        "audit_out_dir": "daily_report_out",

        "tab_overview": "1) Overview",
        "tab_positions": "2) pos_id",
        "tab_logs": "3) Log analytics",
        "tab_control": "4) CONTROL",
        "tab_tools": "5) Tools",
        "tab_state": "6) state.json",

        "missing_logs": "logs not found (no trade_log_*.csv)",
        "missing_trade_log": "trade_log not found",
        "missing_control": "CONTROL.csv not found (you can create it by saving)",

        "time_filter": "Time Filter 10:00-16:00",
        "trade_log_file": "trade_log file",
        "file": "FILE",

        "audit_integration": "Audit integration (daily_report)",
        "audit_loaded": "Loaded audit JSON",
        "audit_not_found": "Audit JSON not found (generate if needed)",
        "refresh_audit": "▶ Run daily_report for selected days and load JSON",

        "tools_panel": "Tools",
        "run_daily_report": "▶ Run daily_report",
        "run_audit": "▶ Run audit",
        "script_args": "Args (optional, space-separated)",
        "script_not_found": "File not found",
        "script_output": "Output (stdout/stderr)",

        "ai_panel": "AI Gate (aligned to bot.py)",
        "ai_control_hint": "AI is applied in bot.py as a final filter before PAPER. This dashboard only updates CONTROL.csv.",

        "control_panel": "CONTROL Update (Dashboard → bot)",
        "control_hint": "Update CONTROL.csv (key,value) via dashboard (bot.py reads it)",
        "load_control": "Load CONTROL",
        "save_control": "Save CONTROL (Update)",
        "saved_ok": "Saved",
        "saved_ng": "Save failed",
        "control_preview": "CONTROL current values",
        "control_updated_at": "Last updated",
        "control_schema_note": "* Add/remove fields OK. Keep key names aligned with bot.py.",

        "pos_view": "pos_id View (OPEN / CLOSED)",
        "pos_status": "status",
        "pos_side": "side",
        "pos_search": "Search (pos_id / note)",
        "pos_detail": "pos_id Detail (timeline)",
        "target_logs": "Target logs",
        "latest_1": "Latest 1 day",
        "latest_3": "Latest 3 days",
        "latest_7": "Latest 7 days",
        "manual": "Manual select",
        "loading_days": "Loading",

        "data_source": "Data source",
        "source_audit": "Audit (daily_report)",
        "source_fallback": "Fallback (log aggregation)",
        "audit_issues": "Audit issues (WARN/ERROR)",

        "overview_title": "Quick view: win/loss for selected days",
        "kpi_trades": "Trades",
        "kpi_closed": "Closed",
        "kpi_winrate": "Win rate",
        "kpi_pnl": "Estimated PnL (%)",
        "kpi_avg_win": "Avg win (%)",
        "kpi_avg_loss": "Avg loss (%)",
        "kpi_streak": "Max win/loss streak",
        "price_band": "Price band (entry price)",

        "notes": "Notes",
        "state_view": "View state.json (_control_snapshot / _open_pos)",
        "snapshot": "_control_snapshot",
        "open_pos": "_open_pos",
    },
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
        main_dir.parent / "logs",
        main_dir / "logs",
        Path("../logs").resolve(),
        Path("./logs").resolve(),
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
        main_dir.parent / "control" / "CONTROL.csv",
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


# =========================
# CONTROL defaults（bot.py整合 key,value）
# =========================
DEFAULTS: Dict[str, str] = {
    "today_on": "1",
    "trade_enabled": "1",
    "paper_mode": "1",
    "observe_only": "0",
    "one_position_only": "1",

    "tp_buy_pct": "0.155",
    "tp_sell_pct": "0.180",
    "sl_pct": "-0.220",
    "win_min": "120",
    "timeout_mode": "IGNORE",

    "spread_limit_pct": "0.0005",
    "max_trades_per_day": "50",
    "no_paper_hours": "13",
    "sell_fast_ma_distance_pct": "0.10",

    "fast_n": "5",
    "slow_n": "20",
    "max_ltp_history": "200",
    "lot": "0.001",

    "max_extend_count": "1",
    "extend_min": "30",
    "extend_min_bestfav_pct": "0.08",
    "partial_tp_trigger_pct": "0.10",

    "safety_hard_block": "1",

    # ===== AI (bot.py整合) =====
    "ai_enabled": "0",
    "ai_mode": "SCORE_ONLY",          # SCORE_ONLY / VETO / GATE
    "ai_threshold": "0.55",           # GATE用
    "ai_veto_threshold": "0.30",      # VETO用
    "ai_features": "spread,trend,ma_gap,ma_slope,volatility",
    "ai_debug": "0",
}


def read_control_kv_csv(path: Path) -> Tuple[Dict[str, str], Dict[str, Any]]:
    meta = {"path": str(path), "exists": path.exists(), "mtime": None}
    if not path.exists():
        return dict(DEFAULTS), meta

    try:
        meta["mtime"] = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        meta["mtime"] = None

    out: Dict[str, str] = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            r = csv.reader(f)
            for row in r:
                if not row or len(row) < 2:
                    continue
                k = str(row[0]).strip()
                v = str(row[1]).strip()
                if k.lower() == "key" and v.lower() == "value":
                    continue
                if k:
                    out[k] = v
    except Exception:
        return dict(DEFAULTS), meta

    for k, v in DEFAULTS.items():
        out.setdefault(k, v)

    return out, meta


def write_control_kv_csv(path: Path, d: Dict[str, str]) -> Tuple[bool, str]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [["key", "value"]]
        for k in DEFAULTS.keys():
            rows.append([k, str(d.get(k, ""))])

        extra = [k for k in d.keys() if k not in DEFAULTS]
        for k in sorted(extra):
            rows.append([k, str(d.get(k, ""))])

        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerows(rows)
        tmp.replace(path)
        return True, str(path)
    except Exception as e:
        return False, str(e)


def parse_hours(s: str) -> List[int]:
    s = (s or "").strip().replace("[", "").replace("]", "")
    if not s:
        return []
    out: List[int] = []
    for p in [x.strip() for x in s.split(",") if x.strip()]:
        try:
            h = int(p)
            if 0 <= h <= 23:
                out.append(h)
        except Exception:
            pass
    return out


def validate_control_kv(control: Dict[str, str]) -> List[str]:
    errs: List[str] = []

    def f(k: str):
        try:
            float(str(control.get(k, "")).strip())
        except Exception:
            errs.append(f"{k} は数値で指定してください")

    def i(k: str):
        try:
            int(float(str(control.get(k, "")).strip()))
        except Exception:
            errs.append(f"{k} は整数で指定してください")

    for k in [
        "tp_buy_pct", "tp_sell_pct", "sl_pct", "spread_limit_pct",
        "sell_fast_ma_distance_pct", "lot", "extend_min_bestfav_pct",
        "partial_tp_trigger_pct", "ai_threshold", "ai_veto_threshold",
    ]:
        f(k)

    for k in [
        "win_min", "max_trades_per_day", "fast_n", "slow_n", "max_ltp_history",
        "max_extend_count", "extend_min",
    ]:
        i(k)

    tm = str(control.get("timeout_mode", "")).strip().upper()
    if tm not in ("IGNORE", "EXTEND", "PARTIAL"):
        errs.append("timeout_mode は IGNORE / EXTEND / PARTIAL のいずれか")

    if str(control.get("no_paper_hours", "")).strip():
        if len(parse_hours(control["no_paper_hours"])) == 0:
            errs.append("no_paper_hours の形式が不正（例: 13 / 13,14 / [13]）")

    for k in [
        "today_on", "trade_enabled", "paper_mode", "observe_only",
        "one_position_only", "ai_enabled", "ai_debug", "safety_hard_block",
    ]:
        v = str(control.get(k, "")).strip().lower()
        if v not in ("0", "1", "true", "false", "yes", "no", "on", "off"):
            errs.append(f"{k} は 0/1（または true/false）を推奨")

    am = str(control.get("ai_mode", "SCORE_ONLY")).strip().upper()
    if am not in ("SCORE_ONLY", "VETO", "GATE"):
        errs.append("ai_mode は SCORE_ONLY / VETO / GATE のいずれか")

    try:
        th = float(str(control.get("ai_threshold", "0.55")).strip())
        if not (0.0 <= th <= 1.0):
            errs.append("ai_threshold は 0.0〜1.0 の範囲を推奨")
    except Exception:
        pass

    try:
        vt = float(str(control.get("ai_veto_threshold", "0.30")).strip())
        if not (0.0 <= vt <= 1.0):
            errs.append("ai_veto_threshold は 0.0〜1.0 の範囲を推奨")
    except Exception:
        pass

    return errs


# =========================
# state.json
# =========================
def read_state_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# =========================
# scripts (daily_report / audit)
# =========================
def run_script(py_path: Path, args: List[str], timeout_sec: int = 180) -> Tuple[int, str]:
    if not py_path.exists():
        return 127, f"[ERROR] not found: {py_path}"
    cmd = [sys.executable, str(py_path), *args]
    try:
        cp = subprocess.run(
            cmd,
            cwd=str(py_path.parent),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        out = ""
        if cp.stdout:
            out += cp.stdout
        if cp.stderr:
            out += ("\n--- stderr ---\n" + cp.stderr)
        return cp.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return 124, f"[ERROR] timeout ({timeout_sec}s): {' '.join(cmd)}"
    except Exception as e:
        return 1, f"[ERROR] failed to run: {e}"


# =========================
# trade_log parsing
# =========================
LOG_NAME_RE = re.compile(r"trade_log_(\d{8})\.csv$")
EXIT_RESULTS = {
    "PAPER_EXIT_TP",
    "PAPER_EXIT_SL",
    "PAPER_EXIT_TIMEOUT",
    "PAPER_EXIT_PARTIAL_TP",
    "PAPER_EXIT_EOD",
}
POS_ID_ANY_RE = re.compile(r"([0-9]{8}-[0-9]{6}-[A-Z]+-\d{3})")


def safe_float_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def safe_dt_series(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


@st.cache_data(show_spinner=False)
def read_trade_log(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, encoding="utf-8")

    if "time" in df.columns:
        df["time_dt"] = safe_dt_series(df["time"])
        df["hour"] = df["time_dt"].dt.hour
    else:
        df["time_dt"] = pd.NaT
        df["hour"] = pd.NA

    for col in ["price", "ltp", "best_bid", "best_ask", "spread_pct", "size", "pnl", "fee"]:
        if col in df.columns:
            df[col + "_num"] = safe_float_series(df[col])

    return df


def apply_time_filter(df: pd.DataFrame, start_hour: int = 10, end_hour: int = 16) -> pd.DataFrame:
    if "hour" not in df.columns:
        return df
    m = df["hour"].between(start_hour, end_hour - 1, inclusive="both")
    return df[m].copy()


def normalize_exit(result: str) -> str:
    r = str(result or "").upper()
    if not r.startswith("PAPER_EXIT"):
        return "NOT_EXIT"
    if "PARTIAL" in r:
        return "PARTIAL"
    if "TIMEOUT" in r:
        return "TIMEOUT"
    if "TP" in r:
        return "TP"
    if "SL" in r:
        return "SL"
    if "EOD" in r:
        return "EOD"
    return "OTHER"


def _safe_get(row: Dict[str, Any], k: str) -> str:
    v = row.get(k, "")
    return "" if v is None else str(v)


def list_log_days(logs_dir: Path) -> List[str]:
    if not logs_dir.exists():
        return []
    days: List[str] = []
    for p in logs_dir.glob("trade_log_*.csv"):
        m = LOG_NAME_RE.search(p.name)
        if m:
            days.append(m.group(1))
    return sorted(set(days), reverse=True)


def load_rows_for_days(logs_dir: Path, day8_list: List[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for day8 in day8_list:
        p = logs_dir / f"trade_log_{day8}.csv"
        if not p.exists():
            continue
        try:
            with open(p, newline="", encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    row["_day8"] = day8
                    rows.append(row)
        except Exception:
            continue
    return rows


# =========================
# daily_report_out JSON
# =========================
def compute_audit_key(day8_list: List[str]) -> Optional[str]:
    if not day8_list:
        return None
    ds = sorted(set([d for d in day8_list if re.fullmatch(r"\d{8}", str(d or ""))]), reverse=True)
    if not ds:
        return None
    if len(ds) == 1:
        return f"daily_report_{ds[0]}"
    oldest = ds[-1]
    newest = ds[0]
    return f"daily_report_{oldest}_{newest}"


def load_daily_report_json(out_dir: Path, day8_list: List[str]) -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
    key = compute_audit_key(day8_list)
    if not key:
        return None, None
    p = out_dir / f"{key}.json"
    if not p.exists():
        return None, p
    try:
        return json.loads(p.read_text(encoding="utf-8")), p
    except Exception:
        return None, p


# =========================
# pos_id summaries
# =========================
@dataclass
class PosSummary:
    pos_id: str
    status: str
    side: str
    entry_time: str
    exit_time: str
    entry_price: str
    exit_ltp: str
    last_result: str
    last_time: str
    last_note: str
    source_days: str
    data_source: str
    ai_score: Optional[float] = None
    ai_pass: Optional[bool] = None


def build_pos_summaries_fallback(rows: List[Dict[str, Any]], state: Dict[str, Any]) -> List[PosSummary]:
    open_pos = state.get("_open_pos") if isinstance(state.get("_open_pos"), dict) else {}
    open_pos_id = str(open_pos.get("pos_id") or "").strip()

    by: Dict[str, Dict[str, Any]] = {}

    def parse_time(s: str) -> datetime:
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return datetime.min

    rows_sorted = sorted(rows, key=lambda r: parse_time(_safe_get(r, "time")))

    for row in rows_sorted:
        pid = _safe_get(row, "pos_id").strip()
        if not pid:
            continue
        d = by.setdefault(pid, {"first_paper": None, "last_exit": None, "last_row": None, "days": set()})
        d["days"].add(_safe_get(row, "_day8"))

        result = _safe_get(row, "result").strip()
        d["last_row"] = row

        if result == "PAPER" and d["first_paper"] is None:
            d["first_paper"] = row

        if result in EXIT_RESULTS:
            d["last_exit"] = row

    out: List[PosSummary] = []
    for pid, d in by.items():
        first_paper = d.get("first_paper")
        last_exit = d.get("last_exit")
        last_row = d.get("last_row")

        has_entry = first_paper is not None
        has_exit = last_exit is not None

        if open_pos_id and pid == open_pos_id:
            status = "OPEN"
        elif has_exit:
            status = "CLOSED"
        elif has_entry:
            status = "OPEN"
        else:
            status = "UNKNOWN"

        def g(r, k) -> str:
            return "" if r is None else _safe_get(r, k)

        side = g(first_paper, "side") or g(last_row, "side")
        entry_time = g(first_paper, "time")
        exit_time = g(last_exit, "time")
        entry_price = g(first_paper, "price")
        exit_ltp = g(last_exit, "ltp")

        last_result = g(last_row, "result")
        last_time = g(last_row, "time")
        last_note = g(last_row, "note")

        days = sorted(list(d.get("days", set())), reverse=True)
        source_days = ",".join(days)

        out.append(
            PosSummary(
                pos_id=pid,
                status=status,
                side=side,
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price,
                exit_ltp=exit_ltp,
                last_result=last_result,
                last_time=last_time,
                last_note=last_note,
                source_days=source_days,
                data_source="fallback",
            )
        )

    def key_ps(ps: PosSummary) -> datetime:
        try:
            return datetime.strptime(ps.last_time, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return datetime.min

    return sorted(out, key=key_ps, reverse=True)


def build_pos_summaries_integrated(
    rows: List[Dict[str, Any]],
    state: Dict[str, Any],
    audit_json: Optional[Dict[str, Any]],
) -> List[PosSummary]:
    if not audit_json or not isinstance(audit_json, dict):
        return build_pos_summaries_fallback(rows, state)

    per_pos = audit_json.get("per_pos")
    if not isinstance(per_pos, dict) or not per_pos:
        return build_pos_summaries_fallback(rows, state)

    def parse_time(s: str) -> datetime:
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return datetime.min

    last_row_by: Dict[str, Dict[str, Any]] = {}
    days_by: Dict[str, set] = {}
    for r in sorted(rows, key=lambda r: parse_time(_safe_get(r, "time"))):
        pid = _safe_get(r, "pos_id").strip()
        if not pid:
            continue
        last_row_by[pid] = r
        days_by.setdefault(pid, set()).add(_safe_get(r, "_day8"))

    open_pos = state.get("_open_pos") if isinstance(state.get("_open_pos"), dict) else {}
    open_pos_id = str(open_pos.get("pos_id") or "").strip()

    out: List[PosSummary] = []

    for pid, d in per_pos.items():
        if not isinstance(d, dict):
            continue

        stt = str(d.get("status") or "").upper()
        if stt == "ERROR_EXIT_WITHOUT_ENTRY":
            status = "ERROR"
        elif stt in ("OPEN", "CLOSED", "UNKNOWN"):
            status = stt
        else:
            status = "UNKNOWN"

        if open_pos_id and pid == open_pos_id and status == "UNKNOWN":
            status = "OPEN"

        entry = d.get("entry") if isinstance(d.get("entry"), dict) else None
        exit_ = d.get("exit") if isinstance(d.get("exit"), dict) else None

        side = str((entry or {}).get("side") or "")
        entry_time = str((entry or {}).get("time") or "")
        entry_price = str((entry or {}).get("price") or "")

        exit_time = str((exit_ or {}).get("time") or "")
        outcome = str((exit_ or {}).get("result") or "")
        exit_ltp = str((exit_ or {}).get("ltp") or "")

        ai_score = None
        ai_pass = None
        if isinstance(d.get("ai"), dict):
            a = d.get("ai")
            try:
                if "score" in a:
                    ai_score = float(a.get("score"))
            except Exception:
                ai_score = None
            if "pass" in a:
                try:
                    ai_pass = bool(a.get("pass"))
                except Exception:
                    ai_pass = None
        else:
            if "ai_score" in d:
                try:
                    ai_score = float(d.get("ai_score"))
                except Exception:
                    ai_score = None
            if "ai_pass" in d:
                try:
                    ai_pass = bool(d.get("ai_pass"))
                except Exception:
                    ai_pass = None

        lr = last_row_by.get(pid, {})
        last_result = _safe_get(lr, "result") or outcome
        last_time = _safe_get(lr, "time") or (exit_time or entry_time)
        last_note = _safe_get(lr, "note")

        days = sorted(list(days_by.get(pid, set())), reverse=True)
        source_days = ",".join(days)

        out.append(
            PosSummary(
                pos_id=pid,
                status=status,
                side=side,
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price,
                exit_ltp=exit_ltp,
                last_result=last_result,
                last_time=last_time,
                last_note=last_note,
                source_days=source_days,
                data_source="audit",
                ai_score=ai_score,
                ai_pass=ai_pass,
            )
        )

    def key_ps(ps: PosSummary) -> datetime:
        try:
            return datetime.strptime(ps.last_time, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return datetime.min

    return sorted(out, key=key_ps, reverse=True)


# =========================
# Stats（勝ち負け推定）
# =========================
def _side_sign(side: str) -> int:
    s = str(side or "").strip().upper()
    if s == "SELL":
        return -1
    return 1


def compute_closed_trades_from_rows(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    pos_id 単位で entry(PAPER) と exit(PAPER_EXIT_*) を対応させ、ret% を推定。
    失敗しても落ちない（不明は NaN）。
    """
    cols = [
        "pos_id", "side", "entry_time", "exit_time",
        "entry_price", "exit_ltp", "exit_result",
        "ret_pct", "ret_bp", "hour", "day8",
    ]
    if not rows:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows)
    if df.empty or "pos_id" not in df.columns:
        return pd.DataFrame(columns=cols)

    for c in ["time", "result", "side", "price", "ltp", "_day8"]:
        if c not in df.columns:
            df[c] = ""

    df["time_dt"] = safe_dt_series(df["time"])
    df["hour"] = df["time_dt"].dt.hour
    df["price_num"] = safe_float_series(df["price"])
    df["ltp_num"] = safe_float_series(df["ltp"])

    entry_df = (
        df[df["result"].astype(str).str.upper() == "PAPER"]
        .sort_values("time_dt")
        .groupby("pos_id", as_index=False)
        .first()
        .rename(columns={
            "time": "entry_time",
            "time_dt": "entry_time_dt",
            "price_num": "entry_price",
            "side": "side_entry",
            "_day8": "day8_entry",
            "hour": "hour_entry",
        })
    )

    exit_mask = df["result"].astype(str).str.upper().isin(EXIT_RESULTS)
    exit_df = (
        df[exit_mask]
        .sort_values("time_dt")
        .groupby("pos_id", as_index=False)
        .last()
        .rename(columns={
            "time": "exit_time",
            "time_dt": "exit_time_dt",
            "ltp_num": "exit_ltp",
            "result": "exit_result",
            "_day8": "day8_exit",
        })
    )

    merged = pd.merge(entry_df, exit_df, on="pos_id", how="inner")
    if merged.empty:
        return pd.DataFrame(columns=cols)

    merged["side"] = merged["side_entry"].astype(str).str.upper()
    merged["entry_price"] = pd.to_numeric(merged["entry_price"], errors="coerce")
    merged["exit_ltp"] = pd.to_numeric(merged["exit_ltp"], errors="coerce")

    def calc_ret(row) -> float:
        try:
            ep = float(row["entry_price"])
            xl = float(row["exit_ltp"])
            if not np.isfinite(ep) or not np.isfinite(xl) or ep <= 0:
                return float("nan")
            sign = _side_sign(row["side"])
            if sign == 1:
                return (xl - ep) / ep * 100.0
            return (ep - xl) / ep * 100.0
        except Exception:
            return float("nan")

    merged["ret_pct"] = merged.apply(calc_ret, axis=1)
    merged["ret_bp"] = merged["ret_pct"] * 100.0
    merged["hour"] = merged["hour_entry"]
    merged["day8"] = merged["day8_entry"]

    out = merged[[
        "pos_id", "side", "entry_time", "exit_time",
        "entry_price", "exit_ltp", "exit_result",
        "ret_pct", "ret_bp", "hour", "day8",
    ]].copy()

    return out.sort_values("exit_time", ascending=False)


def max_streak(series_bool: List[bool]) -> Tuple[int, int]:
    mw = ml = cw = cl = 0
    for b in series_bool:
        if b:
            cw += 1
            cl = 0
        else:
            cl += 1
            cw = 0
        mw = max(mw, cw)
        ml = max(ml, cl)
    return mw, ml


def bval_str(v: str) -> bool:
    return str(v or "0").strip().lower() in ("1", "true", "yes", "on")


# =========================
# Visualization helpers (Altair safe)
# =========================
WEEKDAY_LABELS_JA = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

def _safe_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return float("nan")

def _win_flag(ret_pct) -> int:
    try:
        return 1 if float(ret_pct) > 0 else 0
    except Exception:
        return 0


def ui_select_days(days: List[str], key_prefix: str, default_mode: str) -> List[str]:
    """
    共通の日選択UI（Overview/pos_idで使い回し）
    default_mode: one of T('latest_1'), T('latest_3'), T('latest_7'), T('manual')
    """
    mode = st.selectbox(
        "対象日",
        [T("latest_1"), T("latest_3"), T("latest_7"), T("manual")],
        index=[T("latest_1"), T("latest_3"), T("latest_7"), T("manual")].index(default_mode),
        key=f"{key_prefix}_mode",
    )
    if mode == T("latest_1"):
        return days[:1]
    if mode == T("latest_3"):
        return days[:3]
    if mode == T("latest_7"):
        return days[:7]
    return st.multiselect("YYYYMMDD", options=days, default=days[:3], key=f"{key_prefix}_manual")


def build_hour_winrate_heatmap_df(closed: pd.DataFrame) -> pd.DataFrame:
    if closed is None or closed.empty:
        return pd.DataFrame(columns=["weekday", "weekday_label", "hour", "winrate", "count"])

    df = closed.copy()
    dt = pd.to_datetime(df.get("entry_time", pd.Series(dtype=str)), errors="coerce")
    df["weekday"] = dt.dt.weekday
    df["weekday_label"] = df["weekday"].apply(
        lambda x: WEEKDAY_LABELS_JA[int(x)] if pd.notna(x) and 0 <= int(x) <= 6 else "NA"
    )
    df["hour"] = pd.to_numeric(df.get("hour", np.nan), errors="coerce")
    df["win"] = df["ret_pct"].apply(_win_flag)

    df = df.dropna(subset=["weekday", "hour"])
    if df.empty:
        return pd.DataFrame(columns=["weekday", "weekday_label", "hour", "winrate", "count"])

    g = df.groupby(["weekday", "weekday_label", "hour"], as_index=False).agg(
        winrate=("win", "mean"),
        count=("win", "size"),
    )
    g["winrate"] = g["winrate"] * 100.0

    hours = list(range(0, 24))
    wds = list(range(0, 7))
    base = pd.MultiIndex.from_product([wds, hours], names=["weekday", "hour"]).to_frame(index=False)
    base["weekday_label"] = base["weekday"].apply(lambda x: WEEKDAY_LABELS_JA[int(x)])
    out = base.merge(g, on=["weekday", "weekday_label", "hour"], how="left")
    out["count"] = out["count"].fillna(0).astype(int)
    out["winrate"] = out["winrate"].fillna(np.nan)
    return out


def extract_ai_map_from_audit(audit_json: Optional[Dict[str, Any]]) -> Tuple[Dict[str, float], Dict[str, Optional[bool]]]:
    score_map: Dict[str, float] = {}
    pass_map: Dict[str, Optional[bool]] = {}
    if not audit_json or not isinstance(audit_json, dict):
        return score_map, pass_map

    per_pos = audit_json.get("per_pos")
    if not isinstance(per_pos, dict):
        return score_map, pass_map

    for pid, d in per_pos.items():
        if not isinstance(d, dict):
            continue
        sc = None
        ps = None
        if isinstance(d.get("ai"), dict):
            a = d.get("ai")
            sc = a.get("score")
            ps = a.get("pass")
        else:
            sc = d.get("ai_score")
            ps = d.get("ai_pass")

        try:
            if sc is not None and str(sc).strip() != "":
                score_map[pid] = float(sc)
        except Exception:
            pass

        if ps is not None:
            try:
                pass_map[pid] = bool(ps)
            except Exception:
                pass_map[pid] = None

    return score_map, pass_map


def attach_ai_to_closed(closed: pd.DataFrame, audit_json: Optional[Dict[str, Any]]) -> pd.DataFrame:
    if closed is None or closed.empty:
        return closed
    score_map, pass_map = extract_ai_map_from_audit(audit_json)
    df = closed.copy()
    df["ai_score"] = df["pos_id"].map(score_map)
    df["ai_pass_audit"] = df["pos_id"].map(pass_map)
    return df


def build_ai_band_df(closed_with_ai: pd.DataFrame, veto_th: float, gate_th: float) -> pd.DataFrame:
    if closed_with_ai is None or closed_with_ai.empty:
        return pd.DataFrame(columns=["band", "winrate", "count"])

    df = closed_with_ai.copy()
    df["win"] = df["ret_pct"].apply(_win_flag)

    def band_of(x):
        try:
            if x is None or (isinstance(x, float) and np.isnan(x)):
                return "NA"
            s = float(x)
            if s < veto_th:
                return f"0.00–{veto_th:.2f}"
            if s < gate_th:
                return f"{veto_th:.2f}–{gate_th:.2f}"
            return f"{gate_th:.2f}–1.00"
        except Exception:
            return "NA"

    df["band"] = df["ai_score"].apply(band_of)
    g = df.groupby("band", as_index=False).agg(
        winrate=("win", "mean"),
        count=("win", "size"),
    )
    g["winrate"] = g["winrate"] * 100.0

    order = ["NA", f"0.00–{veto_th:.2f}", f"{veto_th:.2f}–{gate_th:.2f}", f"{gate_th:.2f}–1.00"]
    g["band"] = pd.Categorical(g["band"], categories=order, ordered=True)
    g = g.sort_values("band")
    g["band"] = g["band"].astype(str)
    return g


# =========================
# ① 追加：MAE/MFE 抽出（audit優先 → trade_log列探索）
# =========================
def _num(v) -> Optional[float]:
    try:
        x = float(v)
        if np.isfinite(x):
            return x
    except Exception:
        pass
    return None


def extract_mae_mfe_from_audit(audit_json: Optional[Dict[str, Any]]) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    per_pos から MAE/MFE を “あり得るキー”で探索して拾う
    例:
      per_pos[pos_id]["mae_pct"]
      per_pos[pos_id]["mfe_pct"]
      per_pos[pos_id]["mae"]
      per_pos[pos_id]["mfe"]
      per_pos[pos_id]["metrics"]["mae_pct"] など
    """
    mae_map: Dict[str, float] = {}
    mfe_map: Dict[str, float] = {}
    if not audit_json or not isinstance(audit_json, dict):
        return mae_map, mfe_map
    per_pos = audit_json.get("per_pos")
    if not isinstance(per_pos, dict):
        return mae_map, mfe_map

    cand_mae = ["mae_pct", "mae", "max_adverse_pct", "max_adverse", "mae_bp"]
    cand_mfe = ["mfe_pct", "mfe", "max_favorable_pct", "max_favorable", "mfe_bp"]

    for pid, d in per_pos.items():
        if not isinstance(d, dict):
            continue

        def dig(obj: Any, keys: List[str]) -> Optional[float]:
            if isinstance(obj, dict):
                for k in keys:
                    if k in obj:
                        x = _num(obj.get(k))
                        if x is not None:
                            return x
                # nested
                for nk in ["metrics", "stat", "stats", "risk", "perf"]:
                    if isinstance(obj.get(nk), dict):
                        x = dig(obj.get(nk), keys)
                        if x is not None:
                            return x
            return None

        mae = dig(d, cand_mae)
        mfe = dig(d, cand_mfe)

        # bp で来た場合は%に寄せる（推定：100bp=1%）
        if mae is not None and abs(mae) > 5 and "bp" in str(d.keys()):
            pass

        if mae is not None:
            mae_map[pid] = float(mae)
        if mfe is not None:
            mfe_map[pid] = float(mfe)

    return mae_map, mfe_map


def attach_mae_mfe_to_closed(
    closed: pd.DataFrame,
    rows: List[Dict[str, Any]],
    audit_json: Optional[Dict[str, Any]],
) -> pd.DataFrame:
    """
    closed に mae/mfe を付与。
    1) 監査JSON per_pos から拾う
    2) 無ければ trade_log rows から列探索（pos_id単位の max/min を推定）
    """
    if closed is None or closed.empty:
        return closed

    df = closed.copy()
    mae_map, mfe_map = extract_mae_mfe_from_audit(audit_json)
    df["mae"] = df["pos_id"].map(mae_map)
    df["mfe"] = df["pos_id"].map(mfe_map)

    # auditで埋まらない分を rows から推定（列がある場合のみ）
    need = df["mae"].isna() | df["mfe"].isna()
    if not need.any():
        return df

    if not rows:
        return df

    r = pd.DataFrame(rows)
    if r.empty or "pos_id" not in r.columns:
        return df

    # あり得る列名候補（ログ側）
    mae_cols = ["mae", "mae_pct", "max_adverse", "max_adverse_pct", "mae_bp"]
    mfe_cols = ["mfe", "mfe_pct", "max_favorable", "max_favorable_pct", "mfe_bp"]

    def pick_first(cols: List[str]) -> Optional[str]:
        for c in cols:
            if c in r.columns:
                return c
        return None

    c_mae = pick_first(mae_cols)
    c_mfe = pick_first(mfe_cols)

    if c_mae is None and c_mfe is None:
        return df

    if c_mae is not None:
        r[c_mae] = pd.to_numeric(r[c_mae], errors="coerce")
    if c_mfe is not None:
        r[c_mfe] = pd.to_numeric(r[c_mfe], errors="coerce")

    g = r.groupby("pos_id", as_index=False).agg(
        mae_val=(c_mae, "min") if c_mae else ("pos_id", "size"),
        mfe_val=(c_mfe, "max") if c_mfe else ("pos_id", "size"),
    )
    if "mae_val" in g.columns and c_mae is None:
        g["mae_val"] = np.nan
    if "mfe_val" in g.columns and c_mfe is None:
        g["mfe_val"] = np.nan

    df = df.merge(g[["pos_id", "mae_val", "mfe_val"]], on="pos_id", how="left")
    df["mae"] = df["mae"].combine_first(df["mae_val"])
    df["mfe"] = df["mfe"].combine_first(df["mfe_val"])
    df = df.drop(columns=[c for c in ["mae_val", "mfe_val"] if c in df.columns])
    return df


# =========================
# ② 追加：AI ON/OFF 判定（audit pass優先 / 無ければ推定）
# =========================
def infer_ai_pass(ai_score: Optional[float], ai_mode: str, gate_th: float, veto_th: float) -> Optional[bool]:
    if ai_score is None or (isinstance(ai_score, float) and np.isnan(ai_score)):
        return None
    m = (ai_mode or "SCORE_ONLY").strip().upper()
    try:
        s = float(ai_score)
    except Exception:
        return None
    if m == "GATE":
        return s >= gate_th
    if m == "VETO":
        return s >= veto_th
    return True  # SCORE_ONLY


def build_ai_onoff_table(
    closed_ai: pd.DataFrame,
    ai_enabled: bool,
    ai_mode: str,
    gate_th: float,
    veto_th: float,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    return: (kpi_df, detail_df)
    """
    if closed_ai is None or closed_ai.empty:
        empty_kpi = pd.DataFrame(columns=["group", "trades", "winrate(%)", "avg_ret(%)", "sum_ret(%)"])
        return empty_kpi, pd.DataFrame()

    df = closed_ai.copy()
    df["win"] = df["ret_pct"].apply(_win_flag)

    # pass判定：auditがあればそれを優先、無ければ推定
    def eff_pass(row) -> Optional[bool]:
        ap = row.get("ai_pass_audit", None)
        if ap is not None and not (isinstance(ap, float) and np.isnan(ap)):
            return bool(ap)
        return infer_ai_pass(row.get("ai_score", None), ai_mode=ai_mode, gate_th=gate_th, veto_th=veto_th)

    df["ai_pass_eff"] = df.apply(eff_pass, axis=1)

    # OFF = 全件
    off = df.copy()

    # ON = ai_enabled のときだけ “通過” を採用。ai_enabled=FalseならON=OFF扱いで比較が意味薄いので同一。
    if ai_enabled:
        on = df[df["ai_pass_eff"] == True].copy()
    else:
        on = df.copy()

    def kpi(block: pd.DataFrame, name: str) -> Dict[str, Any]:
        if block is None or block.empty:
            return {"group": name, "trades": 0, "winrate(%)": np.nan, "avg_ret(%)": np.nan, "sum_ret(%)": 0.0}
        trades = int(len(block))
        winrate = float(block["win"].mean() * 100.0) if trades else np.nan
        avg_ret = float(pd.to_numeric(block["ret_pct"], errors="coerce").mean())
        sum_ret = float(pd.to_numeric(block["ret_pct"], errors="coerce").sum())
        return {"group": name, "trades": trades, "winrate(%)": winrate, "avg_ret(%)": avg_ret, "sum_ret(%)": sum_ret}

    kpi_df = pd.DataFrame([kpi(off, "AI OFF（全件）"), kpi(on, "AI ON（通過のみ）")])

    detail = df[[
        "pos_id", "day8", "side", "entry_time", "exit_time", "hour",
        "entry_price", "exit_ltp", "exit_result", "ret_pct",
        "ai_score", "ai_pass_audit", "ai_pass_eff",
    ]].copy()

    return kpi_df, detail


# =========================
# UI init
# =========================
st.set_page_config(page_title="Trading Bot Dashboard", layout="wide")

if "lang" not in st.session_state:
    st.session_state["lang"] = "ja"
if "pos_q" not in st.session_state:
    st.session_state["pos_q"] = ""
if "pos_jump" not in st.session_state:
    st.session_state["pos_jump"] = ""

main_dir = get_main_dir()
logs_dir = find_logs_dir(main_dir)
control_path = find_control_csv(main_dir)
state_path = find_state_json(main_dir)
audit_out = daily_report_out_dir(main_dir)

DAILY_REPORT_PY = main_dir / "daily_report.py"
AUDIT_PY = main_dir / "audit.py"


# =========================
# Sidebar（最小＆迷わない）
# =========================
with st.sidebar:
    st.header(T("settings"))
    lang = st.selectbox(T("lang"), options=["ja", "en"], index=0 if st.session_state["lang"] == "ja" else 1)
    st.session_state["lang"] = lang

    st.divider()
    st.subheader(T("paths"))
    st.caption(T("main_dir"))
    st.code(str(main_dir), language="text")
    st.caption(T("logs_dir"))
    st.code(str(logs_dir) if logs_dir else "(not found)", language="text")
    st.caption(T("control_file"))
    st.code(str(control_path), language="text")
    st.caption(T("state_file"))
    st.code(str(state_path), language="text")
    st.caption(T("audit_out_dir"))
    st.code(str(audit_out), language="text")

    if st.button(T("reload"), use_container_width=True):
        st.rerun()

    st.divider()
    st.subheader(T("trade_log_file"))

    time_filter_on = st.checkbox(T("time_filter"), value=True)
    selected_trade_log: Optional[Path] = None
    if logs_dir is None:
        st.error(T("missing_logs"))
    else:
        files = sorted(logs_dir.glob("trade_log_*.csv"))
        if not files:
            st.error(T("missing_trade_log"))
        else:
            opt_names = [p.name for p in files]
            default_idx = max(0, len(opt_names) - 1)
            sel_name = st.selectbox(T("trade_log_file"), options=opt_names, index=default_idx)
            selected_trade_log = logs_dir / sel_name


# =========================
# Header
# =========================
st.title(T("app_title"))

# =========================
# Status Banner (SAFETY / MODE / AI)
# =========================
ctrl_now, _meta = read_control_kv_csv(control_path)

safety_on = bval_str(ctrl_now.get("safety_hard_block", "0"))
trade_on  = bval_str(ctrl_now.get("trade_enabled", "0"))
today_on  = bval_str(ctrl_now.get("today_on", "0"))
observe   = bval_str(ctrl_now.get("observe_only", "0"))
paper     = bval_str(ctrl_now.get("paper_mode", "0"))

ai_on     = bval_str(ctrl_now.get("ai_enabled", "0"))
ai_mode   = str(ctrl_now.get("ai_mode", "SCORE_ONLY")).strip().upper()
ai_th     = _safe_float(ctrl_now.get("ai_threshold", "0.55"))
ai_veto   = _safe_float(ctrl_now.get("ai_veto_threshold", "0.30"))

with st.container():
    c1, c2, c3, c4, c5, c6 = st.columns([1.2, 1.0, 1.0, 1.0, 1.2, 2.6])

    with c1:
        if safety_on:
            st.error("🛑 SAFETY: ON", icon="🛑")
        else:
            st.success("✅ SAFETY: OFF", icon="✅")

    with c2:
        st.metric("today_on", "ON" if today_on else "OFF")

    with c3:
        st.metric("trade", "ON" if trade_on else "OFF")

    with c4:
        st.metric("observe_only", "ON" if observe else "OFF")

    with c5:
        st.metric("paper_mode", "ON" if paper else "OFF")

    with c6:
        if ai_on:
            st.info(f"🤖 AI: ON / {ai_mode}  | veto={ai_veto:.2f} gate={ai_th:.2f}")
        else:
            st.info(f"🤖 AI: OFF / {ai_mode}  | veto={ai_veto:.2f} gate={ai_th:.2f}")

with st.expander(T("ai_panel"), expanded=False):
    st.caption(T("ai_control_hint"))
    c1, c2, c3 = st.columns([1.2, 1.6, 2.2])
    with c1:
        st.metric("ai_enabled", "ON" if ai_on else "OFF")
        st.metric("ai_mode", ai_mode)
    with c2:
        st.write("thresholds")
        st.code(
            f"ai_threshold={ctrl_now.get('ai_threshold','0.55')}\n"
            f"ai_veto_threshold={ctrl_now.get('ai_veto_threshold','0.30')}\n"
            f"ai_debug={ctrl_now.get('ai_debug','0')}\n"
            f"safety_hard_block={ctrl_now.get('safety_hard_block','1')}",
            language="text",
        )
    with c3:
        st.write("ai_features")
        st.code(str(ctrl_now.get("ai_features", DEFAULTS["ai_features"])), language="text")

if safety_on:
    st.error("🛑 SAFETY HARD BLOCK : ON（botは売買を停止します）", icon="🛑")
elif (today_on and trade_on and (not observe) and (not paper)):
    st.warning("⚠️ LIVE想定の状態です（observe_only=OFF & paper_mode=OFF）。誤発注に注意。", icon="⚠️")

st.divider()

# =========================
# Tabs
# =========================
tab_overview, tab_positions, tab_logs, tab_control, tab_tools, tab_state = st.tabs([
    T("tab_overview"),
    T("tab_positions"),
    T("tab_logs"),
    T("tab_control"),
    T("tab_tools"),
    T("tab_state"),
])


# =========================
# ⑤ Tools（実行）
# =========================
with tab_tools:
    st.subheader(T("tools_panel"))

    toolA, toolB = st.columns([1, 1])

    with toolA:
        st.write("daily_report.py:", "OK" if DAILY_REPORT_PY.exists() else T("script_not_found"))
        daily_args = st.text_input(T("script_args") + " (daily_report)", value="")
        if st.button(T("run_daily_report"), use_container_width=True):
            args = [x for x in daily_args.strip().split(" ") if x.strip()] if daily_args.strip() else []
            code, out_txt = run_script(DAILY_REPORT_PY, args=args, timeout_sec=180)
            st.write("returncode:", code)
            st.text_area(T("script_output"), out_txt or "(no output)", height=220)

    with toolB:
        st.write("audit.py:", "OK" if AUDIT_PY.exists() else T("script_not_found"))
        audit_args = st.text_input(T("script_args") + " (audit)", value="")
        if st.button(T("run_audit"), use_container_width=True):
            args = [x for x in audit_args.strip().split(" ") if x.strip()] if audit_args.strip() else []
            code, out_txt = run_script(AUDIT_PY, args=args, timeout_sec=180)
            st.write("returncode:", code)
            st.text_area(T("script_output"), out_txt or "(no output)", height=220)

    st.info(
        "📌 よく使うのはここ：\n"
        "- daily_report は **YYYYMMDD** または **YYYYMMDD-YYYYMMDD** を渡す想定\n"
        "- 例： `20260210 --out-dir daily_report_out`\n"
        "- pos_idタブにも **範囲指定の daily_report 実行ボタン**があります（そっちが普段用）"
    )


# =========================
# ⑥ state.json
# =========================
with tab_state:
    st.subheader(T("state_view"))
    st_json = read_state_json(state_path)
    st.write(T("snapshot"))
    st.json(st_json.get("_control_snapshot", {}))
    st.write(T("open_pos"))
    st.json(st_json.get("_open_pos", {}))


# =========================
# ② pos_id（監査統合）
# =========================
with tab_positions:
    st.subheader(T("pos_view"))

    if logs_dir is None:
        st.warning(T("missing_logs"))
    else:
        days = list_log_days(logs_dir)
        if not days:
            st.warning(T("missing_logs"))
        else:
            mode = st.selectbox(
                T("target_logs"),
                [T("latest_1"), T("latest_3"), T("latest_7"), T("manual")],
                index=1,
            )
            if mode == T("latest_1"):
                target_days = days[:1]
            elif mode == T("latest_3"):
                target_days = days[:3]
            elif mode == T("latest_7"):
                target_days = days[:7]
            else:
                target_days = st.multiselect("YYYYMMDD", options=days, default=days[:3])

            st.caption(f"{T('loading_days')}: " + (", ".join(target_days) if target_days else "(none)"))

            st.markdown(f"**{T('audit_integration')}**")
            audit_json, audit_path_candidate = load_daily_report_json(audit_out, target_days)

            cA, cB = st.columns([1.2, 1.8])
            with cA:
                if st.button(T("refresh_audit"), use_container_width=True):
                    if not DAILY_REPORT_PY.exists():
                        st.error(T("script_not_found"))
                    else:
                        ds = sorted(set(target_days), reverse=True)
                        if len(ds) == 1:
                            token = ds[0]
                        else:
                            token = f"{ds[-1]}-{ds[0]}"
                        code, out_txt = run_script(
                            DAILY_REPORT_PY,
                            args=[token, "--out-dir", str(audit_out)],
                            timeout_sec=180,
                        )
                        st.write("returncode:", code)
                        st.text_area(T("script_output"), out_txt or "(no output)", height=200)
                        audit_json, audit_path_candidate = load_daily_report_json(audit_out, target_days)

            with cB:
                if audit_json is not None:
                    st.success(f"{T('audit_loaded')}: {audit_path_candidate}")
                else:
                    if audit_path_candidate is not None:
                        st.info(f"{T('audit_not_found')}: {audit_path_candidate}")

            state_now = read_state_json(state_path)
            rows = load_rows_for_days(logs_dir, target_days)
            summaries = build_pos_summaries_integrated(rows, state_now, audit_json)

            if audit_json is not None:
                issues = audit_json.get("issues") if isinstance(audit_json.get("issues"), list) else []
                if issues:
                    with st.expander(T("audit_issues"), expanded=False):
                        st.write(f"issues={len(issues)}")
                        issue_q = st.text_input("issues 検索（任意）", value="")
                        view = issues
                        if issue_q.strip():
                            qq = issue_q.strip().lower()
                            view = [x for x in issues if qq in str(x).lower()]

                        for i, msg in enumerate(view[:500]):
                            s = str(msg)
                            m = POS_ID_ANY_RE.search(s)
                            pid = m.group(1) if m else ""
                            if pid:
                                a, b = st.columns([1, 6])
                                with a:
                                    if st.button(f"pos: {pid}", key=f"audit_issue_posbtn_{i}_{pid}"):
                                        st.session_state["pos_q"] = pid
                                        st.session_state["pos_jump"] = pid
                                        st.rerun()
                                with b:
                                    st.code(s, language="text")
                            else:
                                st.code(s, language="text")

                        if len(view) > 500:
                            st.caption(f"... ({len(view)-500} more)")

            st.divider()

            f1, f2, f3, f4 = st.columns([1, 1, 2, 1])
            with f1:
                status_filter = st.selectbox(T("pos_status"), ["ALL", "OPEN", "CLOSED", "UNKNOWN", "ERROR"], index=0)
            with f2:
                side_filter = st.selectbox(T("pos_side"), ["ALL", "BUY", "SELL"], index=0)
            with f3:
                st.text_input(T("pos_search"), key="pos_q")
                q = st.session_state.get("pos_q", "")
            with f4:
                src_filter = st.selectbox(T("data_source"), ["ALL", T("source_audit"), T("source_fallback")], index=0)

            def match(ps: PosSummary) -> bool:
                if status_filter != "ALL" and ps.status != status_filter:
                    return False
                if side_filter != "ALL" and (ps.side or "").upper() != side_filter:
                    return False
                if src_filter != "ALL":
                    want = "audit" if src_filter == T("source_audit") else "fallback"
                    if ps.data_source != want:
                        return False
                if q.strip():
                    qq = q.strip().lower()
                    if qq not in ps.pos_id.lower() and qq not in (ps.last_note or "").lower():
                        return False
                return True

            filtered = [ps for ps in summaries if match(ps)]
            open_n = sum(1 for ps in filtered if ps.status == "OPEN")
            closed_n = sum(1 for ps in filtered if ps.status == "CLOSED")
            unk_n = sum(1 for ps in filtered if ps.status == "UNKNOWN")
            err_n = sum(1 for ps in filtered if ps.status == "ERROR")
            st.caption(f"rows={len(filtered)} / OPEN={open_n} / CLOSED={closed_n} / UNKNOWN={unk_n} / ERROR={err_n}")

            table = []
            for ps in filtered:
                table.append({
                    "status": ps.status,
                    "source": (T("source_audit") if ps.data_source == "audit" else T("source_fallback")),
                    "pos_id": ps.pos_id,
                    "side": ps.side,
                    "entry_time": ps.entry_time,
                    "exit_time": ps.exit_time,
                    "entry_price": ps.entry_price,
                    "exit_ltp": ps.exit_ltp,
                    "last_result": ps.last_result,
                    "last_time": ps.last_time,
                    "source_days": ps.source_days,
                    "ai_score": ps.ai_score if ps.ai_score is not None else "",
                    "ai_pass": ps.ai_pass if ps.ai_pass is not None else "",
                    "last_note": ps.last_note,
                })
            st.dataframe(table, use_container_width=True, hide_index=True)

            st.subheader(T("pos_detail"))
            if filtered:
                opts = [ps.pos_id for ps in filtered]
                jump = st.session_state.get("pos_jump", "")
                default_idx = 0
                if jump and jump in opts:
                    default_idx = opts.index(jump)

                sel = st.selectbox("pos_id", options=opts, index=default_idx)
                st.session_state["pos_jump"] = sel

                pr = [r for r in rows if _safe_get(r, "pos_id").strip() == sel]
                pr = sorted(pr, key=lambda r: _safe_get(r, "time") or "9999-99-99 99:99:99")

                detail = []
                for r in pr:
                    detail.append({
                        "time": _safe_get(r, "time"),
                        "result": _safe_get(r, "result"),
                        "side": _safe_get(r, "side"),
                        "price": _safe_get(r, "price"),
                        "ltp": _safe_get(r, "ltp"),
                        "best_bid": _safe_get(r, "best_bid"),
                        "best_ask": _safe_get(r, "best_ask"),
                        "spread_pct": _safe_get(r, "spread_pct"),
                        "ma_fast": _safe_get(r, "ma_fast"),
                        "ma_slow": _safe_get(r, "ma_slow"),
                        "trend": _safe_get(r, "trend"),
                        "signal": _safe_get(r, "signal"),
                        "note": _safe_get(r, "note"),
                        "_day": _safe_get(r, "_day8"),
                    })
                st.dataframe(detail, use_container_width=True, hide_index=True)
            else:
                st.info("フィルタ条件に一致する pos_id がありません")


# =========================
# ① 概要（勝ち負け + 追加分析）
# =========================
with tab_overview:
    st.subheader(T("overview_title"))

    if logs_dir is None:
        st.warning(T("missing_logs"))
    else:
        days = list_log_days(logs_dir)
        if not days:
            st.warning(T("missing_logs"))
        else:
            # 共通UI化
            target_days = ui_select_days(days, key_prefix="ov", default_mode=T("latest_1"))
            st.caption("対象: " + (", ".join(target_days) if target_days else "(none)"))

            rows = load_rows_for_days(logs_dir, target_days)
            closed = compute_closed_trades_from_rows(rows)

            # 監査JSON
            audit_json_ov, audit_path_ov = load_daily_report_json(audit_out, target_days)
            if audit_json_ov is None and audit_path_ov is not None:
                st.info(f"監査JSON: 見つからず（{audit_path_ov}）。AI/MAE/MFEの一部表示が不明になる可能性。")
            elif audit_json_ov is not None:
                st.success(f"監査JSON: {audit_path_ov}")

            # KPI
            trades_total = int(len(set([_safe_get(r, "pos_id").strip() for r in rows if _safe_get(r, "pos_id").strip()])))
            closed_n = int(len(closed))

            if closed_n > 0:
                wins = closed["ret_pct"].dropna() > 0
                win_n = int(wins.sum())
                winrate = win_n / closed_n * 100.0 if closed_n else 0.0
                pnl_sum = float(closed["ret_pct"].dropna().sum()) if len(closed["ret_pct"].dropna()) else 0.0
                avg_win = float(closed.loc[closed["ret_pct"] > 0, "ret_pct"].mean()) if win_n else 0.0
                loss_n = int((closed["ret_pct"].dropna() <= 0).sum())
                avg_loss = float(closed.loc[closed["ret_pct"] <= 0, "ret_pct"].mean()) if loss_n else 0.0

                seq = list((closed.sort_values("exit_time")["ret_pct"].fillna(0.0) > 0.0).tolist())
                mw, ml = max_streak(seq)
            else:
                winrate = pnl_sum = avg_win = avg_loss = 0.0
                mw, ml = (0, 0)

            k1, k2, k3, k4, k5, k6 = st.columns(6)
            k1.metric(T("kpi_trades"), f"{trades_total}")
            k2.metric(T("kpi_closed"), f"{closed_n}")
            k3.metric(T("kpi_winrate"), f"{winrate:.1f}%")
            k4.metric(T("kpi_pnl"), f"{pnl_sum:.2f}%")
            k5.metric(T("kpi_avg_win"), f"{avg_win:.2f}%")
            k6.metric(T("kpi_avg_loss"), f"{avg_loss:.2f}%")
            st.caption(f"{T('kpi_streak')}: {mw} / {ml}")

            st.divider()

            # =========================================================
            # 価格帯（エントリー価格）
            # =========================================================
            st.subheader(T("price_band"))
            if closed_n > 0 and "entry_price" in closed.columns:
                ep = pd.to_numeric(closed["entry_price"], errors="coerce").dropna()
                if len(ep) > 0:
                    band = pd.cut(ep, bins=10)
                    band_cnt = band.value_counts().sort_index()
                    df_band = band_cnt.rename_axis("price_band").reset_index(name="count")
                    df_band["price_band"] = df_band["price_band"].astype(str).str.replace(" ", "", regex=False)
                    st.bar_chart(df_band.set_index("price_band")["count"], use_container_width=True)
                else:
                    st.info("entry_price が数値として読み取れません")
            else:
                st.info("決済データが無いので価格帯は表示できません（PAPER→PAPER_EXIT が必要）")

            st.divider()

            # =========================================================
            # ③ 時間帯 × 勝率（既存の勝率ヒートマップ）
            # =========================================================
            st.subheader("時間帯 × 勝率（ヒートマップ）")
            if closed_n > 0:
                hm = build_hour_winrate_heatmap_df(closed)
                min_count = st.slider("表示する最小件数（少ない枠は隠す）", 0, 20, 1, 1)
                hm2 = hm.copy()
                hm2.loc[hm2["count"] < min_count, "winrate"] = np.nan

                chart = (
                    alt.Chart(hm2)
                    .mark_rect()
                    .encode(
                        x=alt.X("hour:O", title="Entry Hour"),
                        y=alt.Y("weekday_label:O", sort=WEEKDAY_LABELS_JA, title="Weekday"),
                        color=alt.Color("winrate:Q", title="Win rate (%)"),
                        tooltip=[
                            alt.Tooltip("weekday_label:N", title="weekday"),
                            alt.Tooltip("hour:O", title="hour"),
                            alt.Tooltip("winrate:Q", title="winrate(%)", format=".1f"),
                            alt.Tooltip("count:Q", title="count"),
                        ],
                    )
                    .properties(height=220)
                )
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("決済データが無いのでヒートマップは表示できません")

            st.divider()

            # =========================================================
            # 追加③：時間帯 × AIスコア（帯別勝率）
            # =========================================================
            st.subheader("③ 時間帯 × AIスコア（帯別 勝率/件数）")
            if closed_n > 0:
                closed_ai = attach_ai_to_closed(closed, audit_json_ov)

                # 帯を作る
                veto_th = ai_veto
                gate_th = ai_th

                def band_of(x):
                    try:
                        if x is None or (isinstance(x, float) and np.isnan(x)):
                            return "NA"
                        s = float(x)
                        if s < veto_th:
                            return f"0.00–{veto_th:.2f}"
                        if s < gate_th:
                            return f"{veto_th:.2f}–{gate_th:.2f}"
                        return f"{gate_th:.2f}–1.00"
                    except Exception:
                        return "NA"

                dfh = closed_ai.copy()
                dfh["band"] = dfh["ai_score"].apply(band_of)
                dfh["hour"] = pd.to_numeric(dfh.get("hour", np.nan), errors="coerce")
                dfh["win"] = dfh["ret_pct"].apply(_win_flag)

                dfh = dfh.dropna(subset=["hour"])
                if dfh.empty:
                    st.info("hour / ai_score が無いので表示できません（監査JSONに ai.score が必要）")
                else:
                    g = dfh.groupby(["band", "hour"], as_index=False).agg(
                        winrate=("win", "mean"),
                        count=("win", "size"),
                    )
                    g["winrate"] = g["winrate"] * 100.0

                    order = ["NA", f"0.00–{veto_th:.2f}", f"{veto_th:.2f}–{gate_th:.2f}", f"{gate_th:.2f}–1.00"]
                    g["band"] = pd.Categorical(g["band"], categories=order, ordered=True)

                    # winrate heatmap
                    chart_ai_time = (
                        alt.Chart(g)
                        .mark_rect()
                        .encode(
                            x=alt.X("hour:O", title="Entry Hour"),
                            y=alt.Y("band:O", title="AI score band"),
                            color=alt.Color("winrate:Q", title="Win rate (%)"),
                            tooltip=[
                                alt.Tooltip("band:N"),
                                alt.Tooltip("hour:O"),
                                alt.Tooltip("winrate:Q", format=".1f"),
                                alt.Tooltip("count:Q"),
                            ],
                        )
                        .properties(height=180)
                    )
                    st.altair_chart(chart_ai_time, use_container_width=True)

                    # count heatmap（参考）
                    chart_cnt = (
                        alt.Chart(g)
                        .mark_rect()
                        .encode(
                            x=alt.X("hour:O", title="Entry Hour"),
                            y=alt.Y("band:O", title="AI score band"),
                            color=alt.Color("count:Q", title="Count"),
                            tooltip=[alt.Tooltip("band:N"), alt.Tooltip("hour:O"), alt.Tooltip("count:Q")],
                        )
                        .properties(height=160)
                    )
                    st.caption("参考：帯×時間帯の件数")
                    st.altair_chart(chart_cnt, use_container_width=True)
            else:
                st.info("決済データが無いので表示できません")

            st.divider()

            # =========================================================
            # 追加②：AI ON / OFF 比較（KPI + テーブル）
            # =========================================================
            st.subheader("② AI ON / OFF 比較")
            if closed_n > 0:
                closed_ai = attach_ai_to_closed(closed, audit_json_ov)

                kpi_df, detail_df = build_ai_onoff_table(
                    closed_ai=closed_ai,
                    ai_enabled=ai_on,
                    ai_mode=ai_mode,
                    gate_th=ai_th,
                    veto_th=ai_veto,
                )

                left, right = st.columns([1.0, 2.0])
                with left:
                    st.dataframe(kpi_df, use_container_width=True, hide_index=True)
                    st.caption("※AI ON は『通過のみ』。ai_pass が無い場合は mode/threshold から推定します。")
                with right:
                    # ざっくり比較バー
                    if not kpi_df.empty:
                        b = kpi_df.copy()
                        b["winrate(%)"] = pd.to_numeric(b["winrate(%)"], errors="coerce")
                        chart_onoff = (
                            alt.Chart(b)
                            .mark_bar()
                            .encode(
                                x=alt.X("group:N", title="Group"),
                                y=alt.Y("winrate(%):Q", title="Win rate (%)", scale=alt.Scale(domain=[0, 100])),
                                tooltip=[alt.Tooltip("group:N"), alt.Tooltip("winrate(%):Q", format=".1f")],
                            )
                        )
                        # altairの列名に%が混ざると扱いにくいので整形
                        b2 = b.rename(columns={"winrate(%)": "winrate_pct"})
                        chart_onoff = (
                            alt.Chart(b2)
                            .mark_bar()
                            .encode(
                                x=alt.X("group:N", title="Group"),
                                y=alt.Y("winrate_pct:Q", title="Win rate (%)", scale=alt.Scale(domain=[0, 100])),
                                tooltip=[alt.Tooltip("group:N"), alt.Tooltip("winrate_pct:Q", format=".1f")],
                            )
                            .properties(height=160)
                        )
                        st.altair_chart(chart_onoff, use_container_width=True)

                with st.expander("AI ON/OFF 詳細（pos_id単位）", expanded=False):
                    st.dataframe(detail_df, use_container_width=True, hide_index=True)

            else:
                st.info("決済データが無いので比較できません")

            st.divider()

            # =========================================================
            # 追加①：AIスコア × MAE/MFE（散布図）
            # =========================================================
            st.subheader("① AIスコア × MAE/MFE（散布図）")
            if closed_n > 0:
                # AI付与 + MAE/MFE付与
                closed_ai = attach_ai_to_closed(closed, audit_json_ov)
                closed_m = attach_mae_mfe_to_closed(closed_ai, rows=rows, audit_json=audit_json_ov)

                # 必須
                has_ai = "ai_score" in closed_m.columns and closed_m["ai_score"].notna().any()
                has_mae = "mae" in closed_m.columns and closed_m["mae"].notna().any()
                has_mfe = "mfe" in closed_m.columns and closed_m["mfe"].notna().any()

                if not has_ai:
                    st.info("AIスコアが見つかりません（監査JSONに ai.score が必要）")
                else:
                    # 表示設定
                    ysel = st.selectbox("Y軸", ["MAE", "MFE"], index=0)
                    if ysel == "MAE" and not has_mae:
                        st.info("MAEが見つかりません（監査JSON or trade_log に mae系列が必要）")
                    elif ysel == "MFE" and not has_mfe:
                        st.info("MFEが見つかりません（監査JSON or trade_log に mfe系列が必要）")
                    else:
                        plot = closed_m.copy()
                        plot["win"] = plot["ret_pct"].apply(lambda x: "WIN" if pd.notna(x) and x > 0 else "LOSS")
                        plot["y"] = plot["mae"] if ysel == "MAE" else plot["mfe"]

                        plot = plot.dropna(subset=["ai_score", "y"])
                        if plot.empty:
                            st.info("必要なデータが揃っていません（ai_score と mae/mfe が必要）")
                        else:
                            # 散布図
                            chart_scatter = (
                                alt.Chart(plot)
                                .mark_circle(size=70)
                                .encode(
                                    x=alt.X("ai_score:Q", title="AI score", scale=alt.Scale(domain=[0, 1])),
                                    y=alt.Y("y:Q", title=f"{ysel}"),
                                    color=alt.Color("win:N", title="Result"),
                                    tooltip=[
                                        alt.Tooltip("pos_id:N"),
                                        alt.Tooltip("day8:N"),
                                        alt.Tooltip("ret_pct:Q", format=".2f"),
                                        alt.Tooltip("ai_score:Q", format=".3f"),
                                        alt.Tooltip("y:Q", format=".3f"),
                                    ],
                                )
                                .properties(height=260)
                            )
                            st.altair_chart(chart_scatter, use_container_width=True)

                            st.caption("※MAE/MFE の単位は、監査JSON/ログの実装に依存します（%で出しているなら%）。")

                            with st.expander("データ（AI/MAE/MFE付き）", expanded=False):
                                cols = [
                                    "pos_id", "day8", "side", "entry_time", "exit_time", "hour",
                                    "ret_pct", "ai_score", "ai_pass_audit", "mae", "mfe",
                                ]
                                cols = [c for c in cols if c in closed_m.columns]
                                st.dataframe(closed_m[cols].copy(), use_container_width=True, hide_index=True)

            else:
                st.info("決済データが無いので表示できません")

            st.divider()

            # =========================================================
            # 決済トレード一覧（推定）
            # =========================================================
            st.subheader("決済トレード一覧（推定）")
            if closed_n > 0:
                show = closed.copy()
                show["win"] = show["ret_pct"].apply(lambda x: "WIN" if pd.notna(x) and x > 0 else "LOSS")
                cols = [
                    "pos_id", "day8", "side", "entry_time", "exit_time",
                    "hour", "entry_price", "exit_ltp", "exit_result",
                    "ret_pct", "win"
                ]
                cols = [c for c in cols if c in show.columns]
                show2 = show[cols].copy()
                if "ret_pct" in show2.columns:
                    show2["ret_pct"] = pd.to_numeric(show2["ret_pct"], errors="coerce")

                st.dataframe(show2, use_container_width=True, hide_index=True)
                st.caption("※損益は trade_log の entry(price) と exit(ltp) から推定（手数料等は加味していません）")

                csv_bytes = show2.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "⬇️ 決済一覧CSVをダウンロード",
                    data=csv_bytes,
                    file_name="closed_trades.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            else:
                st.info("まだ決済が無い（またはログ不足）ため、一覧は空です")


# =========================
# ③ ログ分析（選択ファイル）
# =========================
with tab_logs:
    st.subheader("ログ分析（選択ファイル）")

    if selected_trade_log is None or not selected_trade_log.exists():
        st.error(T("missing_trade_log"))
        st.stop()

    df_all = read_trade_log(selected_trade_log)
    df = apply_time_filter(df_all) if time_filter_on else df_all

    if "result" not in df.columns:
        st.error("CSVに result 列がありません")
        st.stop()

    cnt = df["result"].fillna("").value_counts()
    observe_n = int(cnt[[k for k in cnt.index if str(k).startswith("OBSERVE")]].sum()) if len(cnt) else 0
    skip_spread_n = int(cnt.get("SKIP_SPREAD", 0))
    skip_news_n = int(cnt.get("SKIP_NEWS", 0))
    paper_n = int(cnt.get("PAPER", 0))
    denom = paper_n + observe_n
    paper_rate = (paper_n / denom * 100.0) if denom > 0 else 0.0

    st.caption(f"{T('file')}: {selected_trade_log}")

    cA, cB, cC, cD, cE, cF = st.columns(6)
    cA.metric("rows", f"{len(df)}")
    cB.metric("OBSERVE", f"{observe_n}")
    cC.metric("SKIP_SPREAD", f"{skip_spread_n}")
    cD.metric("SKIP_NEWS", f"{skip_news_n}")
    cE.metric("PAPER", f"{paper_n}")
    cF.metric("PAPER率", f"{paper_rate:.1f}%")

    st.divider()

    df_exit = df[df["result"].astype(str).str.upper().str.startswith("PAPER_EXIT")].copy()
    if not df_exit.empty:
        df_exit["exit_norm"] = df_exit["result"].apply(normalize_exit)
        exit_cnt = df_exit["exit_norm"].value_counts()
    else:
        exit_cnt = pd.Series(dtype=int)

    st.subheader("決済内訳（PAPER_EXIT_*）")
    xA, xB, xC, xD, xE, xF = st.columns(6)
    xA.metric("TP", f"{int(exit_cnt.get('TP', 0))}")
    xB.metric("SL", f"{int(exit_cnt.get('SL', 0))}")
    xC.metric("TIMEOUT", f"{int(exit_cnt.get('TIMEOUT', 0))}")
    xD.metric("PARTIAL", f"{int(exit_cnt.get('PARTIAL', 0))}")
    xE.metric("EOD", f"{int(exit_cnt.get('EOD', 0))}")
    xF.metric("OTHER", f"{int(exit_cnt.get('OTHER', 0))}")

    st.divider()

    st.subheader("result counts")
    cnt_df = cnt.rename_axis("result").reset_index(name="count")
    st.dataframe(cnt_df, use_container_width=True, height=320)

    st.divider()

    st.subheader("時間帯テーブル")
    if "hour" in df.columns:
        def is_observe(x: str) -> bool:
            return str(x).startswith("OBSERVE")

        df2 = df.copy()
        df2["is_observe"] = df2["result"].astype(str).apply(is_observe).astype(int)
        df2["is_skip_spread"] = (df2["result"].astype(str) == "SKIP_SPREAD").astype(int)
        df2["is_skip_news"] = (df2["result"].astype(str) == "SKIP_NEWS").astype(int)
        df2["is_paper"] = (df2["result"].astype(str) == "PAPER").astype(int)

        if "spread_pct_num" in df2.columns:
            df2["spread_pct_num2"] = df2["spread_pct_num"]
        else:
            df2["spread_pct_num2"] = pd.NA

        hour_grp = df2.groupby("hour", dropna=True).agg(
            total=("result", "size"),
            OBSERVE=("is_observe", "sum"),
            SKIP_SPREAD=("is_skip_spread", "sum"),
            SKIP_NEWS=("is_skip_news", "sum"),
            PAPER=("is_paper", "sum"),
            avg_spread=("spread_pct_num2", "mean"),
        ).reset_index()

        hour_grp["avg_spread"] = hour_grp["avg_spread"].apply(lambda x: f"{x:.4f}%" if pd.notna(x) else "-")
        st.dataframe(hour_grp.sort_values("hour"), use_container_width=True, height=320)
    else:
        st.info("hour列が無いので時間帯テーブルはスキップ")

    st.divider()

    st.subheader("スプレッド統計")
    if "spread_pct_num" in df.columns:
        sp = df["spread_pct_num"].dropna()
        if len(sp) > 0:
            sA, sB, sC = st.columns(3)
            sA.metric("平均", f"{sp.mean():.4f}%")
            sB.metric("最小", f"{sp.min():.4f}%")
            sC.metric("最大", f"{sp.max():.4f}%")
        else:
            st.info("spread_pct データなし")
    else:
        st.info("spread_pct 列なし")


# =========================
# ④ CONTROL（設定）
# =========================
with tab_control:
    st.subheader(T("control_panel"))
    st.caption(T("control_hint"))

    control, meta2 = read_control_kv_csv(control_path)
    if not control_path.exists():
        st.warning(T("missing_control"))

    def bval(k: str) -> bool:
        return str(control.get(k, "0")).strip().lower() in ("1", "true", "yes", "on")

    st.markdown("### よく触る（初心者向け）")
    with st.form("control_form_easy"):
        ec1, ec2, ec3 = st.columns(3)
        with ec1:
            today_on = st.checkbox("today_on（今日稼働）", value=bval("today_on"))
            trade_enabled = st.checkbox("trade_enabled（売買許可）", value=bval("trade_enabled"))
            observe_only = st.checkbox("observe_only（観測のみ）", value=bval("observe_only"))
        with ec2:
            one_position_only = st.checkbox("one_position_only（同時ポジ1つ）", value=bval("one_position_only"))
            paper_mode = st.checkbox("paper_mode（PAPERモード）", value=bval("paper_mode"))
            safety_hard_block = st.checkbox("safety_hard_block（緊急停止）", value=bval("safety_hard_block"))
        with ec3:
            max_trades_per_day = st.text_input("max_trades_per_day", value=str(control["max_trades_per_day"]))
            spread_limit_pct = st.text_input("spread_limit_pct（例 0.0005=0.05%）", value=str(control["spread_limit_pct"]))
            no_paper_hours = st.text_input("no_paper_hours（例: 13 / 13,14 / [13]）", value=str(control["no_paper_hours"]))

        st.markdown("---")
        st.markdown("### 利確/損切（基本）")
        rc1, rc2, rc3 = st.columns(3)
        with rc1:
            tp_buy_pct = st.text_input("tp_buy_pct", value=str(control["tp_buy_pct"]))
        with rc2:
            tp_sell_pct = st.text_input("tp_sell_pct", value=str(control["tp_sell_pct"]))
        with rc3:
            sl_pct = st.text_input("sl_pct（負）", value=str(control["sl_pct"]))

        st.markdown("---")
        st.markdown("### AI（bot.py整合）")
        st.caption(T("ai_control_hint"))
        a1, a2, a3 = st.columns([1.2, 1.8, 2.0])
        with a1:
            ai_enabled = st.checkbox("ai_enabled", value=bval("ai_enabled"))
            ai_debug = st.checkbox("ai_debug", value=bval("ai_debug"))
            ai_mode_in = st.selectbox(
                "ai_mode",
                ["SCORE_ONLY", "VETO", "GATE"],
                index=["SCORE_ONLY", "VETO", "GATE"].index(
                    str(control.get("ai_mode", "SCORE_ONLY")).upper()
                    if str(control.get("ai_mode", "SCORE_ONLY")).upper() in ("SCORE_ONLY", "VETO", "GATE")
                    else "SCORE_ONLY"
                ),
            )
        with a2:
            ai_threshold = st.text_input("ai_threshold（GATE用 0.0〜1.0）", value=str(control.get("ai_threshold", "0.55")))
            ai_veto_threshold = st.text_input("ai_veto_threshold（VETO用 0.0〜1.0）", value=str(control.get("ai_veto_threshold", "0.30")))
        with a3:
            ai_features = st.text_input("ai_features（CSV）", value=str(control.get("ai_features", DEFAULTS["ai_features"])))

        st.caption(T("control_schema_note"))

        colA, colB = st.columns(2)
        save_btn = colA.form_submit_button(T("save_control"))
        load_btn = colB.form_submit_button(T("load_control"))

    if load_btn:
        st.rerun()

    if save_btn:
        newc = dict(control)
        newc["today_on"] = "1" if today_on else "0"
        newc["trade_enabled"] = "1" if trade_enabled else "0"
        newc["observe_only"] = "1" if observe_only else "0"
        newc["one_position_only"] = "1" if one_position_only else "0"
        newc["paper_mode"] = "1" if paper_mode else "0"
        newc["safety_hard_block"] = "1" if safety_hard_block else "0"

        newc["max_trades_per_day"] = max_trades_per_day
        newc["spread_limit_pct"] = spread_limit_pct
        newc["no_paper_hours"] = no_paper_hours

        newc["tp_buy_pct"] = tp_buy_pct
        newc["tp_sell_pct"] = tp_sell_pct
        newc["sl_pct"] = sl_pct

        newc["ai_enabled"] = "1" if ai_enabled else "0"
        newc["ai_debug"] = "1" if ai_debug else "0"
        newc["ai_mode"] = str(ai_mode_in).strip().upper()
        newc["ai_threshold"] = ai_threshold
        newc["ai_veto_threshold"] = ai_veto_threshold
        newc["ai_features"] = ai_features

        errs = validate_control_kv(newc)
        if errs:
            st.error("保存できません（入力エラー）")
            for e in errs:
                st.write("- ", e)
        else:
            ok, msg = write_control_kv_csv(control_path, newc)
            if ok:
                st.success(f"{T('saved_ok')}: {msg}")
                time.sleep(0.2)
                st.rerun()
            else:
                st.error(f"{T('saved_ng')}: {msg}")

    st.divider()
    st.markdown(f"**{T('control_preview')}**")
    ctrl_preview, meta3 = read_control_kv_csv(control_path)
    st.json(ctrl_preview)
    if meta3.get("mtime"):
        st.caption(f"{T('control_updated_at')}: {meta3.get('mtime')}")


# =========================
# Notes
# =========================
st.divider()
st.subheader(T("notes"))
st.write(
    "- pos_id 表示は **daily_report_out の監査JSONがあれば最優先**で採用（OPEN/CLOSEDを監査基準に統一）。\n"
    "- 監査JSONが無い場合は **従来のログ集計（フォールバック）**で表示します。\n"
    "- 監査の issues（WARN/ERROR）は pos_id 画面内で確認できます。\n"
    "- ★issues の pos_id ボタンを押すと、pos_id 検索欄に反映＆詳細もジャンプします。\n"
    "- 詳細タイムラインは常に trade_log の実データを表示します（監査と実ログの両面確認用）。\n"
    "- ★AI項目は **bot.py と完全に整合**（ai_mode/threshold/features 等）。Dashboardは CONTROL を更新するだけで、最終判断は bot.py が行います。\n"
    "- 「勝ち負け（推定）」は trade_log の entry(price) と exit(ltp) から推定。fee/pnl列がある場合は将来ここに合算拡張できます。\n"
    "- ★追加：AIスコア×MAE/MFE、AI ON/OFF 比較、時間帯×AIスコア を Overview に統合しました。\n"
)
