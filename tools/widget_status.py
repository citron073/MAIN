#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hmac
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from exchange.bitflyer_private import BitflyerPrivateClient
from tools.drift_resume_summary import build_drift_resume_snapshot
from tools.keychain_secret import read_pair_with_source
from tools.trade_event_notifier import (
    _build_daily_trade_review as _notifier_build_daily_trade_review,
    _build_shadow_day_snapshot as _notifier_build_shadow_day_snapshot,
    _load_toml_section as _load_notify_toml_section,
)

SECRETS_PATH_DEFAULT = ROOT / ".streamlit" / "secrets.toml"
BALANCE_CACHE_TTL_SEC = 45
_BALANCE_CACHE: Dict[str, Any] = {}
WIDGET_SERVER_VERSION = "OuroborosWidget/1.0"
WIDGET_APP_NAME = "Ouroboros Widget"
WIDGET_APP_SHORT_NAME = "Ouroboros"
WIDGET_REACT_ROOT = ROOT / "widget" / "react_portfolio"


def _content_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return "text/html; charset=utf-8"
    if suffix in {".js", ".jsx"}:
        return "application/javascript; charset=utf-8"
    if suffix == ".css":
        return "text/css; charset=utf-8"
    if suffix == ".svg":
        return "image/svg+xml; charset=utf-8"
    if suffix == ".json":
        return "application/json; charset=utf-8"
    if suffix == ".png":
        return "image/png"
    return "application/octet-stream"


def _resolve_widget_react_path(path: str) -> Optional[Path]:
    rel = path.removeprefix("/widget-react").lstrip("/")
    if rel in {"", "/"}:
        rel = "index.html"
    candidate = (WIDGET_REACT_ROOT / rel).resolve()
    try:
        candidate.relative_to(WIDGET_REACT_ROOT.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _read_text_try(path: Path, encodings: Tuple[str, ...] = ("utf-8", "utf-8-sig", "cp932")) -> str:
    for enc in encodings:
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _safe_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off", ""}:
        return False
    return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except Exception:
        return default


def _safe_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def _fmt_float(v: Optional[float], digits: int = 3) -> str:
    if v is None:
        return "-"
    return f"{float(v):.{digits}f}"


def _fmt_jpy(v: Optional[float], digits: int = 0) -> str:
    if v is None:
        return "-"
    return f"{float(v):,.{digits}f}"


def _extract_first_group(text: str, pattern: str, default: str = "-") -> str:
    try:
        m = re.search(pattern, text)
        if m:
            return str(m.group(1) or default)
    except Exception:
        pass
    return default


def _build_version_snapshot() -> Dict[str, Any]:
    dashboard_version = "-"
    yt_tool_raw = "-"
    yt_tool_release_date = "-"
    bot_logic_version = "-"
    feature_schema_version = "-"
    handover_updated_at_jst = "-"
    mr_observe_phase = "phase1-observe-only"

    try:
        dashboard_text = _read_text_try(ROOT / "dashboard.py")
        dashboard_version = _extract_first_group(dashboard_text, r'APP_VERSION = "([^"]+)"', dashboard_version)
    except Exception:
        pass

    try:
        from ouroboros_contract import OUROBOROS_BOT_VERSION, OUROBOROS_FEATURE_SCHEMA_VERSION

        bot_logic_version = OUROBOROS_BOT_VERSION
        feature_schema_version = OUROBOROS_FEATURE_SCHEMA_VERSION
    except Exception:
        try:
            bot_text = _read_text_try(ROOT / "bot.py")
            bot_logic_version = _extract_first_group(
                bot_text,
                r'OUROBOROS_BOT_VERSION = "([^"]+)"',
                bot_logic_version,
            )
            feature_schema_version = _extract_first_group(
                bot_text,
                r'OUROBOROS_FEATURE_SCHEMA_VERSION = "([^"]+)"',
                feature_schema_version,
            )
        except Exception:
            pass

    try:
        yt_text = _read_text_try(ROOT / "yt_tool_version.py")
        yt_tool_raw = _extract_first_group(yt_text, r'TOOL_VERSION = "([^"]+)"', yt_tool_raw)
        yt_tool_release_date = _extract_first_group(yt_text, r'RELEASE_DATE = "([^"]+)"', yt_tool_release_date)
    except Exception:
        pass

    try:
        handover = json.loads(_read_text_try(ROOT / "HANDOVER.json"))
        meta = handover.get("meta", {}) if isinstance(handover.get("meta"), dict) else {}
        versions = handover.get("versions", {}) if isinstance(handover.get("versions"), dict) else {}
        handover_updated_at_jst = str(meta.get("updated_at_jst", handover_updated_at_jst) or handover_updated_at_jst)
        mr_observe_phase = str(versions.get("mr_observe_phase", mr_observe_phase) or mr_observe_phase)
        if bot_logic_version == "-":
            bot_logic_version = str(versions.get("bot_logic", bot_logic_version) or bot_logic_version)
        if feature_schema_version == "-":
            feature_schema_version = str(versions.get("feature_schema", feature_schema_version) or feature_schema_version)
        if dashboard_version == "-":
            dashboard_version = str(versions.get("dashboard", dashboard_version) or dashboard_version)
    except Exception:
        pass

    yt_tool_label = yt_tool_raw if str(yt_tool_raw).startswith("v") else f"v{yt_tool_raw}"
    return {
        "dashboard": dashboard_version,
        "widget_status_server": WIDGET_SERVER_VERSION,
        "bot_logic": bot_logic_version,
        "feature_schema": feature_schema_version,
        "yt_tool": yt_tool_label,
        "yt_tool_release_date": yt_tool_release_date,
        "mr_observe_phase": mr_observe_phase,
        "handover_updated_at_jst": handover_updated_at_jst,
        "summary": f"bot {bot_logic_version} / dash {dashboard_version} / widget {WIDGET_SERVER_VERSION}",
        "detail": f"schema {feature_schema_version} / MR {mr_observe_phase} / handover {handover_updated_at_jst}",
    }


def _goal_text(goal: Dict[str, Any]) -> str:
    pnl = _safe_float(goal.get("pnl_jpy"))
    goal_jpy = _safe_float(goal.get("goal_jpy"))
    if pnl is None or goal_jpy is None:
        return "-"
    return f"{float(pnl):+.0f} / {float(goal_jpy):.0f}"


def _shadow_day_text(shadow_day: Dict[str, Any]) -> str:
    if not isinstance(shadow_day, dict) or not shadow_day.get("available"):
        return "-"
    pnl = float(_safe_float(shadow_day.get("pnl_jpy_sum")) or 0.0)
    closed_n = max(0, _safe_int(shadow_day.get("closed_n"), 0))
    tech_n = max(0, _safe_int(shadow_day.get("exit_technical_n"), 0))
    weak_n = max(0, _safe_int(shadow_day.get("weak_progress_exit_n"), 0))
    progress_reversal_n = max(0, _safe_int(shadow_day.get("progress_reversal_exit_n"), 0))
    near_tp_n = max(0, _safe_int(shadow_day.get("near_tp_giveback_exit_n"), 0))
    progress_timeout_n = max(0, _safe_int(shadow_day.get("progress_timeout_n"), 0))
    no_follow_n = max(0, _safe_int(shadow_day.get("no_follow_through_exit_n"), 0))
    trend_n = max(0, _safe_int(shadow_day.get("observe_trend_strength_weak_n"), 0))
    htf60_n = max(0, _safe_int(shadow_day.get("observe_ai_block_htf60_countertrend_n"), 0))
    conflict_n = max(0, _safe_int(shadow_day.get("observe_ai_block_htf15_60_conflict_n"), 0))
    timeout_n = max(0, _safe_int(shadow_day.get("plain_timeout_n"), _safe_int(shadow_day.get("timeout_n"), 0)))
    return f"{pnl:+.0f} / {closed_n} / tech{tech_n} / wp{weak_n} / pr{progress_reversal_n} / ntp{near_tp_n} / pto{progress_timeout_n} / nf{no_follow_n} / tw{trend_n} / h60{htf60_n} / cf{conflict_n} / to{timeout_n}"


def _weekly_hint_text(weekly: Dict[str, Any]) -> str:
    if not isinstance(weekly, dict):
        return "-"
    decision = str(weekly.get("shadow_decision", "") or "").strip()
    hint = str(weekly.get("pattern_hint", "") or "").strip()
    if decision and hint:
        return f"{decision} / {hint}"
    return decision or hint or "-"


def _shadow_adjustment_text(reflection: Dict[str, Any]) -> str:
    if not isinstance(reflection, dict) or not reflection.get("available"):
        return ""
    filter_hint = str(reflection.get("shadow_filter_hint", "") or "").strip()
    htf_hint = str(reflection.get("shadow_htf_hint", "") or "").strip()
    exit_hint = str(reflection.get("shadow_exit_hint", "") or "").strip()
    parts: List[str] = []
    if filter_hint:
        parts.append(f"filter {filter_hint}")
    if htf_hint:
        parts.append(f"htf {htf_hint}")
    if exit_hint:
        parts.append(f"exit {exit_hint}")
    return " / ".join(parts)


def _versions_text(versions: Dict[str, Any]) -> str:
    if not isinstance(versions, dict):
        return "-"
    return str(versions.get("summary", "-") or "-")


def _balance_kind(ctrl: Dict[str, str]) -> Tuple[str, str]:
    market_type = str(ctrl.get("market_type", "SPOT") or "SPOT").strip().upper()
    if market_type in {"FX", "CFD", "LIGHTNING"}:
        return "collateral", "証拠金"
    return "balance", "残高"


def _build_daily_goal_snapshot(logs_dir: Optional[Path], secrets_path: Path) -> Dict[str, Any]:
    sec = _load_notify_toml_section(secrets_path, "dashboard_security")
    goal_raw = _safe_float(sec.get("trade_notify_daily_goal_jpy"))
    goal_jpy = max(0.0, float(goal_raw) if goal_raw is not None else 100.0)
    day8 = datetime.now().strftime("%Y%m%d")
    pnl_available = logs_dir is not None
    review = _notifier_build_daily_trade_review(logs_dir, day8) if logs_dir else {}
    pnl_jpy = float(_safe_float((review or {}).get("pnl_jpy_sum")) or 0.0) if pnl_available else None
    closed_n = max(0, _safe_int((review or {}).get("closed_n"), 0)) if pnl_available else None
    achieved = (pnl_jpy >= goal_jpy if goal_jpy > 0 else True) if pnl_available else None
    return {
        "day8": day8,
        "goal_jpy": float(goal_jpy),
        "pnl_jpy": float(pnl_jpy) if pnl_jpy is not None else None,
        "delta_jpy": float(pnl_jpy - goal_jpy) if pnl_jpy is not None else None,
        "remaining_jpy": float(max(0.0, goal_jpy - pnl_jpy)) if pnl_jpy is not None else None,
        "achieved": bool(achieved) if achieved is not None else None,
        "closed_n": int(closed_n) if closed_n is not None else None,
        "pnl_available": pnl_available,
    }


def _load_account_balance_snapshot(ctrl: Dict[str, str]) -> Dict[str, Any]:
    kind, label = _balance_kind(ctrl)
    base = {
        "available": False,
        "jpy": None,
        "collateral_jpy": None,
        "jpy_balance": None,
        "available_collateral_jpy": None,
        "open_position_pnl_jpy": None,
        "require_collateral_jpy": None,
        "kind": kind,
        "label": label,
        "exchange": "bitflyer",
        "source": "",
        "error": "",
        "setup_hint": "",
        "updated_at": "-",
    }
    exchange_name = str(ctrl.get("exchange_name") or "bitflyer").strip().lower()
    if exchange_name != "bitflyer":
        base["source"] = exchange_name or "unknown"
        base["error"] = "unsupported_exchange"
        return dict(base)

    service = str(ctrl.get("keychain_service", "ouroboros.bitflyer") or "ouroboros.bitflyer").strip()
    account_key = str(ctrl.get("keychain_account_key", "api_key") or "api_key").strip()
    account_secret = str(ctrl.get("keychain_account_secret", "api_secret") or "api_secret").strip()
    cache_key = "|".join([exchange_name, kind, service, account_key, account_secret])
    now_ts = time.time()
    cached = _BALANCE_CACHE.get(cache_key)
    if isinstance(cached, dict):
        cached_ts = float(cached.get("ts") or 0.0)
        if (now_ts - cached_ts) < BALANCE_CACHE_TTL_SEC and isinstance(cached.get("payload"), dict):
            return dict(cached["payload"])

    try:
        api_key, api_secret, source = read_pair_with_source(
            service=service,
            account_key=account_key,
            account_secret=account_secret,
        )
        client = BitflyerPrivateClient(api_key=api_key, api_secret=api_secret, timeout=8)
        collateral: Dict[str, Any] = {}
        balances: List[Dict[str, Any]] = []
        collateral_jpy: Optional[float] = None
        available_collateral_jpy: Optional[float] = None
        open_position_pnl_jpy: Optional[float] = None
        require_collateral_jpy: Optional[float] = None
        jpy_balance: Optional[float] = None

        try:
            collateral = client.get_collateral()
            for key in ("collateral", "collateral_amount"):
                value = _safe_float(collateral.get(key))
                if value is not None:
                    collateral_jpy = float(value)
                    break
            available_collateral_jpy = _safe_float(collateral.get("available_collateral"))
            open_position_pnl_jpy = _safe_float(collateral.get("open_position_pnl"))
            require_collateral_jpy = _safe_float(collateral.get("require_collateral"))
        except Exception:
            collateral = {}

        try:
            balances = client.get_balance()
            for row in balances:
                if str(row.get("currency_code", "")).upper() != "JPY":
                    continue
                value = _safe_float(row.get("amount"))
                if value is not None:
                    jpy_balance = float(value)
                    break
        except Exception:
            balances = []

        amount = collateral_jpy if kind == "collateral" else jpy_balance
        if amount is None:
            amount = collateral_jpy if collateral_jpy is not None else jpy_balance
        if amount is None:
            raise RuntimeError(
                "bitFlyer account amount not found: "
                f"collateral_keys={list(collateral.keys())} balance_rows={len(balances)}"
            )
        payload = {
            **base,
            "available": True,
            "jpy": float(amount),
            "collateral_jpy": collateral_jpy,
            "jpy_balance": jpy_balance,
            "available_collateral_jpy": available_collateral_jpy,
            "open_position_pnl_jpy": open_position_pnl_jpy,
            "require_collateral_jpy": require_collateral_jpy,
            "source": f"bitflyer:{source}",
            "error": "",
            "setup_hint": "",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        payload = {
            **base,
            "source": "bitflyer",
            "error": str(e).strip()[:160],
            "setup_hint": (
                "MacはKeychain、VM/Linuxは /etc/ouroboros/secrets.env に "
                "OUROBOROS_BITFLYER_API_KEY / OUROBOROS_BITFLYER_API_SECRET を設定"
            ),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    _BALANCE_CACHE[cache_key] = {"ts": now_ts, "payload": dict(payload)}
    return payload


def _parse_jst_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _load_ibkr_account_snapshot(main_dir: Path) -> Dict[str, Any]:
    base = {
        "available": False,
        "source": "review_out/ibkr_connection_latest.json",
        "account_id": "",
        "generated_at_jst": "",
        "age_hours": None,
        "stale": True,
        "currency": "JPY",
        "net_liquidation_jpy": None,
        "available_funds_jpy": None,
        "buying_power_jpy": None,
        "excess_liquidity_jpy": None,
        "total_cash_value_jpy": None,
        "gross_position_value_jpy": None,
        "unrealized_pnl_jpy": None,
        "label": "IBKR NetLiq",
        "error": "",
    }
    path = main_dir / "review_out" / "ibkr_connection_latest.json"
    if not path.exists():
        return {**base, "error": "ibkr_connection_latest.json not found"}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {**base, "error": f"read_error: {str(e)[:120]}"}

    summary = raw.get("account_summary") if isinstance(raw, dict) else None
    if not isinstance(summary, dict) or not summary:
        return {**base, "error": "account_summary missing"}

    account_id = ""
    account_obj: Dict[str, Any] = {}
    for key, value in summary.items():
        if key != "All" and isinstance(value, dict):
            account_id = str(key)
            account_obj = value
            break
    if not account_obj and isinstance(summary.get("All"), dict):
        account_id = "All"
        account_obj = summary["All"]
    if not account_obj:
        return {**base, "error": "account_summary empty"}

    all_obj = summary.get("All") if isinstance(summary.get("All"), dict) else {}
    generated_at = str(raw.get("generated_at_jst", "") or "")
    generated_dt = _parse_jst_datetime(generated_at)
    age_hours = None
    stale = True
    if generated_dt is not None:
        age_hours = max(0.0, (datetime.now() - generated_dt).total_seconds() / 3600.0)
        stale = age_hours > 24.0

    net_liq = _safe_float(account_obj.get("NetLiquidation"))
    if net_liq is None:
        net_liq = _safe_float(all_obj.get("NetLiquidationByCurrency"))

    total_cash = _safe_float(account_obj.get("TotalCashValue"))
    if total_cash is None:
        total_cash = _safe_float(all_obj.get("TotalCashBalance") or all_obj.get("CashBalance"))

    unrealized = _safe_float(all_obj.get("UnrealizedPnL"))

    return {
        **base,
        "available": net_liq is not None,
        "account_id": account_id,
        "generated_at_jst": generated_at,
        "age_hours": round(age_hours, 2) if age_hours is not None else None,
        "stale": bool(stale),
        "net_liquidation_jpy": float(net_liq) if net_liq is not None else None,
        "available_funds_jpy": _safe_float(account_obj.get("AvailableFunds")),
        "buying_power_jpy": _safe_float(account_obj.get("BuyingPower")),
        "excess_liquidity_jpy": _safe_float(account_obj.get("ExcessLiquidity")),
        "total_cash_value_jpy": float(total_cash) if total_cash is not None else None,
        "gross_position_value_jpy": _safe_float(account_obj.get("GrossPositionValue")),
        "unrealized_pnl_jpy": float(unrealized) if unrealized is not None else None,
        "error": "" if net_liq is not None else "NetLiquidation missing",
    }


def _parse_dt(v: Any) -> Optional[datetime]:
    s = str(v or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _age_text(age_sec: Optional[int]) -> str:
    if age_sec is None:
        return "-"
    sec = max(0, int(age_sec))
    if sec < 60:
        return "1分未満"
    mins = sec // 60
    if mins < 60:
        return f"{mins}分前"
    hours = mins // 60
    if hours < 24:
        rem = mins % 60
        return f"{hours}時間{rem}分前" if rem else f"{hours}時間前"
    days = hours // 24
    rem_h = hours % 24
    return f"{days}日{rem_h}時間前" if rem_h else f"{days}日前"


def _read_trade_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        txt = _read_text_try(path)
        return list(csv.DictReader(txt.splitlines()))
    except Exception:
        return []


def _calc_trade_metrics(side: str, entry_price: Optional[float], exit_price: Optional[float], size: Optional[float]) -> Dict[str, Optional[float]]:
    if entry_price is None or exit_price is None or entry_price == 0:
        return {"ret_pct": None, "pnl_jpy": None}
    pnl_per_unit = float(entry_price) - float(exit_price) if str(side or "").strip().upper() == "SELL" else float(exit_price) - float(entry_price)
    ret_pct = (pnl_per_unit / float(entry_price)) * 100.0
    pnl_jpy = (pnl_per_unit * float(size)) if (size is not None) else None
    return {
        "ret_pct": float(ret_pct),
        "pnl_jpy": float(pnl_jpy) if pnl_jpy is not None else None,
    }


def _latest_trade_snapshot(logs_dir: Optional[Path]) -> Dict[str, Any]:
    out = {
        "available": False,
        "day8": "",
        "time": "",
        "kind": "",
        "reason": "",
        "side": "",
        "result": "",
        "entry_price": None,
        "exit_price": None,
        "size": None,
        "ret_pct": None,
        "pnl_jpy": None,
        "age_sec": None,
        "age_text": "-",
    }
    if not logs_dir:
        return out

    try:
        files = sorted(logs_dir.glob("trade_log_*.csv"), reverse=True)
    except Exception:
        return out

    now = datetime.now()
    for path in files:
        day8 = path.stem.replace("trade_log_", "", 1)
        rows = _read_trade_rows(path)
        for row in reversed(rows):
            result = str(row.get("result", "")).strip()
            if result.startswith("PAPER_EXIT_"):
                dt = _parse_dt(row.get("time"))
                side = str(row.get("side", "")).strip().upper()
                entry_price = _safe_float(row.get("price"))
                exit_price = _safe_float(row.get("ltp"))
                size = _safe_float(row.get("size"))
                metrics = _calc_trade_metrics(side, entry_price, exit_price, size)
                age_sec = int(max(0.0, (now - dt).total_seconds())) if dt else None
                return {
                    **out,
                    "available": True,
                    "day8": day8,
                    "time": dt.strftime("%Y-%m-%d %H:%M:%S") if dt else str(row.get("time", "")).strip(),
                    "kind": "EXIT",
                    "reason": result.replace("PAPER_EXIT_", "", 1),
                    "side": side,
                    "result": result,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "size": size,
                    "ret_pct": metrics.get("ret_pct"),
                    "pnl_jpy": metrics.get("pnl_jpy"),
                    "age_sec": age_sec,
                    "age_text": _age_text(age_sec),
                }
            if result == "PAPER":
                dt = _parse_dt(row.get("time"))
                age_sec = int(max(0.0, (now - dt).total_seconds())) if dt else None
                return {
                    **out,
                    "available": True,
                    "day8": day8,
                    "time": dt.strftime("%Y-%m-%d %H:%M:%S") if dt else str(row.get("time", "")).strip(),
                    "kind": "ENTRY",
                    "reason": "ENTRY",
                    "side": str(row.get("side", "")).strip().upper(),
                    "result": result,
                    "entry_price": _safe_float(row.get("price")),
                    "exit_price": None,
                    "size": _safe_float(row.get("size")),
                    "ret_pct": None,
                    "pnl_jpy": None,
                    "age_sec": age_sec,
                    "age_text": _age_text(age_sec),
                }
    return out


def _recent_trades_snapshot(logs_dir: Optional[Path], n: int = 10) -> List[Dict[str, Any]]:
    """Return the last N closed trades from trade log CSVs."""
    if not logs_dir:
        return []
    results: List[Dict[str, Any]] = []
    try:
        files = sorted(logs_dir.glob("trade_log_*.csv"), reverse=True)
    except Exception:
        return []
    now = datetime.now()
    for path in files:
        if len(results) >= n:
            break
        rows = _read_trade_rows(path)
        for row in reversed(rows):
            result = str(row.get("result", "")).strip()
            if not result.startswith("PAPER_EXIT_"):
                continue
            side = str(row.get("side", "")).strip().upper()
            exit_price = _safe_float(row.get("ltp"))
            entry_price = _safe_float(row.get("price"))
            size = _safe_float(row.get("size"))
            dt = _parse_dt(row.get("time"))
            metrics = _calc_trade_metrics(side, entry_price, exit_price, size)
            pos_id = str(row.get("pos_id", "")).split(",")[0].strip()
            age_sec = int(max(0.0, (now - dt).total_seconds())) if dt else None
            results.append({
                "time": dt.strftime("%Y-%m-%d %H:%M:%S") if dt else str(row.get("time", "")).strip(),
                "side": side,
                "exit_reason": result.replace("PAPER_EXIT_", "", 1),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "size": size,
                "ret_pct": metrics.get("ret_pct"),
                "pnl_jpy": metrics.get("pnl_jpy"),
                "age_sec": age_sec,
                "pos_id": pos_id,
            })
            if len(results) >= n:
                break
    return results


def _build_pnl_curve_snapshot(recent_trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a compact closed-trade PnL curve for mobile/widget charts."""
    closed = [
        dict(row)
        for row in reversed(recent_trades or [])
        if _safe_float(row.get("pnl_jpy")) is not None
    ]
    if not closed:
        return {
            "available": False,
            "source": "recent_trades",
            "closed_n": 0,
            "points": [],
            "bars": [],
            "labels": [],
            "total_pnl_jpy": 0.0,
            "win_n": 0,
            "loss_n": 0,
            "win_rate_pct": 0.0,
            "avg_pnl_jpy": 0.0,
            "best_pnl_jpy": None,
            "worst_pnl_jpy": None,
        }

    points: List[float] = [0.0]
    bars: List[float] = []
    labels: List[str] = []
    running = 0.0
    for row in closed:
        pnl = float(_safe_float(row.get("pnl_jpy")) or 0.0)
        running += pnl
        bars.append(round(pnl, 3))
        points.append(round(running, 3))
        label = str(row.get("time", "") or row.get("exit_reason", "") or "").strip()
        labels.append(label[-8:] if label else str(row.get("exit_reason", "") or "-"))

    win_n = sum(1 for v in bars if v > 0)
    loss_n = sum(1 for v in bars if v < 0)
    closed_n = len(bars)
    return {
        "available": True,
        "source": "recent_trades",
        "closed_n": closed_n,
        "points": points,
        "bars": bars,
        "labels": labels,
        "total_pnl_jpy": round(sum(bars), 3),
        "win_n": win_n,
        "loss_n": loss_n,
        "win_rate_pct": round((win_n / closed_n) * 100.0, 1) if closed_n else 0.0,
        "avg_pnl_jpy": round(sum(bars) / closed_n, 3) if closed_n else 0.0,
        "best_pnl_jpy": round(max(bars), 3) if bars else None,
        "worst_pnl_jpy": round(min(bars), 3) if bars else None,
    }


def _build_freshness_snapshot(state_path: Path, latest_trade: Dict[str, Any]) -> Dict[str, Any]:
    state_dt: Optional[datetime] = None
    if state_path.exists():
        try:
            state_dt = datetime.fromtimestamp(state_path.stat().st_mtime)
        except Exception:
            state_dt = None
    trade_dt = _parse_dt(latest_trade.get("time")) if latest_trade.get("available") else None
    refs: List[Tuple[str, datetime]] = []
    if state_dt is not None:
        refs.append(("state", state_dt))
    if trade_dt is not None:
        refs.append(("trade", trade_dt))
    if not refs:
        return {
            "status": "ALERT",
            "reference": "",
            "reference_time": "-",
            "age_sec": None,
            "age_text": "-",
            "summary": "更新情報なし",
        }

    ref_name, ref_dt = max(refs, key=lambda item: item[1])
    age_sec = int(max(0.0, (datetime.now() - ref_dt).total_seconds()))
    if age_sec <= 300:
        status = "OK"
    elif age_sec <= 900:
        status = "WARN"
    else:
        status = "ALERT"
    ref_label = "state" if ref_name == "state" else "trade"
    summary = ("state更新 " if ref_name == "state" else "直近約定 ") + _age_text(age_sec)
    return {
        "status": status,
        "reference": ref_label,
        "reference_time": ref_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "age_sec": age_sec,
        "age_text": _age_text(age_sec),
        "summary": summary,
    }


def _build_weekly_snapshot(logs_dir: Optional[Path], state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    today = datetime.now().date()
    start = today - timedelta(days=today.weekday())
    out = {
        "available": False,
        "start_day8": start.strftime("%Y%m%d"),
        "end_day8": today.strftime("%Y%m%d"),
        "days_count": 0,
        "closed_n": 0,
        "win_n": 0,
        "loss_n": 0,
        "win_rate_pct": 0.0,
        "pnl_jpy_sum": 0.0,
        "avg_ret_pct": 0.0,
        "shadow_decision": "",
        "shadow_reason": "",
        "pattern_hint": "",
        "pattern_reason": "",
        "review_updated_at": "",
    }
    if not logs_dir:
        logs_dir = None

    if logs_dir:
        day = start
        ret_sum = 0.0
        while day <= today:
            day8 = day.strftime("%Y%m%d")
            review = _notifier_build_daily_trade_review(logs_dir, day8)
            closed_n = max(0, _safe_int(review.get("closed_n"), 0))
            if closed_n > 0:
                out["days_count"] = int(out["days_count"]) + 1
            out["closed_n"] = int(out["closed_n"]) + closed_n
            out["win_n"] = int(out["win_n"]) + max(0, _safe_int(review.get("win_n"), 0))
            out["loss_n"] = int(out["loss_n"]) + max(0, _safe_int(review.get("loss_n"), 0))
            out["pnl_jpy_sum"] = float(out["pnl_jpy_sum"]) + float(_safe_float(review.get("pnl_jpy_sum")) or 0.0)
            ret_sum += float(_safe_float(review.get("ret_sum_pct")) or 0.0)
            day += timedelta(days=1)

        closed_n = max(0, int(out["closed_n"]))
        out["available"] = closed_n > 0
        if closed_n > 0:
            out["win_rate_pct"] = (float(out["win_n"]) / float(closed_n)) * 100.0
            out["avg_ret_pct"] = float(ret_sum) / float(closed_n)

    weekly_feedback = (state or {}).get("_weekly_auto_feedback", {}) if isinstance((state or {}).get("_weekly_auto_feedback"), dict) else {}
    shadow_review = weekly_feedback.get("shadow_weekly_review", {}) if isinstance(weekly_feedback.get("shadow_weekly_review"), dict) else {}
    if shadow_review.get("available"):
        out["shadow_decision"] = str(shadow_review.get("decision", "") or "")
        out["shadow_reason"] = str(shadow_review.get("reason", "") or "")
        out["pattern_hint"] = str(shadow_review.get("pattern_hint", "") or "")
        out["pattern_reason"] = str(shadow_review.get("pattern_reason", "") or "")
        out["review_updated_at"] = str(weekly_feedback.get("updated_at", "") or "")
    return out


def _build_sharpe_snapshot(logs_dir: Optional[Path], lookback_days: int = 30) -> Dict[str, Any]:
    out: Dict[str, Any] = {"available": False, "n": 0, "sharpe": None, "avg_ret_pct": None, "std_ret_pct": None, "lookback_days": lookback_days}
    if not logs_dir:
        return out
    today = datetime.now().date()
    returns: List[float] = []
    for i in range(lookback_days):
        d = today - timedelta(days=i)
        path = Path(logs_dir) / f"trade_log_{d.strftime('%Y%m%d')}.csv"
        if not path.exists():
            continue
        for row in _read_trade_rows(path):
            result = str(row.get("result", "")).strip()
            if not result.startswith("PAPER_EXIT_"):
                continue
            side = str(row.get("side", "")).strip().upper()
            entry = _safe_float(row.get("price"))
            exit_ = _safe_float(row.get("ltp"))
            if entry and exit_ and abs(entry) > 0:
                ret = (exit_ - entry) / entry * 100.0 if side == "BUY" else (entry - exit_) / entry * 100.0
                returns.append(ret)
    n = len(returns)
    if n < 5:
        return out
    avg = sum(returns) / n
    variance = sum((r - avg) ** 2 for r in returns) / max(1, n - 1)
    std = variance ** 0.5
    sharpe = round(avg / std, 3) if std > 0 else None
    return {
        "available": True, "n": n,
        "sharpe": sharpe,
        "avg_ret_pct": round(avg, 4),
        "std_ret_pct": round(std, 4),
        "lookback_days": lookback_days,
    }


def _build_fill_rate_by_hour(logs_dir: Optional[Path], lookback_days: int = 14) -> Dict[str, Any]:
    out: Dict[str, Any] = {"available": False, "by_hour": {}, "lookback_days": lookback_days}
    if not logs_dir:
        return out
    today = datetime.now().date()
    hour_data: Dict[int, Dict[str, int]] = {}
    for i in range(lookback_days):
        d = today - timedelta(days=i)
        path = Path(logs_dir) / f"trade_log_{d.strftime('%Y%m%d')}.csv"
        if not path.exists():
            continue
        for row in _read_trade_rows(path):
            result = str(row.get("result", "")).strip()
            t = _parse_dt(row.get("time"))
            if t is None:
                continue
            h = t.hour
            if h not in hour_data:
                hour_data[h] = {"observe_ok": 0, "filled": 0, "unfilled": 0}
            if result == "OBSERVE_OK":
                hour_data[h]["observe_ok"] += 1
            elif result == "PAPER":
                hour_data[h]["filled"] += 1
            elif "UNFILLED" in result.upper() or result == "entry_unfilled":
                hour_data[h]["unfilled"] += 1
    if not hour_data:
        return out
    by_hour: Dict[str, Any] = {}
    for h, hd in sorted(hour_data.items()):
        obs = hd["observe_ok"]
        filled = hd["filled"]
        attempted = filled + hd["unfilled"]
        fill_rate = round(filled / attempted * 100.0, 1) if attempted > 0 else None
        by_hour[str(h)] = {
            "observe_ok": obs, "filled": filled, "unfilled": hd["unfilled"],
            "fill_rate_pct": fill_rate,
        }
    return {"available": bool(by_hour), "by_hour": by_hour, "lookback_days": lookback_days}


def _build_pf_snapshot(logs_dir: Optional[Path], lookback_days: int = 30) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "available": False, "lookback_days": lookback_days,
        "pf": None, "avg_win_pct": None, "avg_loss_pct": None,
        "win_loss_ratio": None, "breakeven_wr_pct": None,
        "win_n": 0, "loss_n": 0,
    }
    if not logs_dir:
        return out
    today = datetime.now().date()
    win_sum = loss_sum = 0.0
    win_n = loss_n = 0
    for i in range(lookback_days):
        d = today - timedelta(days=i)
        path = Path(logs_dir) / f"trade_log_{d.strftime('%Y%m%d')}.csv"
        if not path.exists():
            continue
        for row in _read_trade_rows(path):
            result = str(row.get("result", "")).strip()
            if not result.startswith("PAPER_EXIT_"):
                continue
            side = str(row.get("side", "")).strip().upper()
            entry = _safe_float(row.get("price"))
            exit_ = _safe_float(row.get("ltp"))
            if not entry or not exit_ or abs(entry) < 1:
                continue
            ret = (exit_ - entry) / entry * 100.0 if side == "BUY" else (entry - exit_) / entry * 100.0
            if ret > 0:
                win_sum += ret
                win_n += 1
            elif ret < 0:
                loss_sum += ret
                loss_n += 1
    if win_n == 0 and loss_n == 0:
        return out
    avg_win = win_sum / win_n if win_n > 0 else None
    avg_loss = loss_sum / loss_n if loss_n > 0 else None
    pf = round(win_sum / abs(loss_sum), 3) if loss_sum < 0 and win_sum > 0 else None
    wl_ratio = round(avg_win / abs(avg_loss), 3) if avg_win and avg_loss and avg_loss < 0 else None
    bkeven = round(1.0 / (1.0 + wl_ratio) * 100.0, 1) if wl_ratio else None
    return {
        "available": True, "lookback_days": lookback_days,
        "pf": pf,
        "avg_win_pct": round(avg_win, 4) if avg_win else None,
        "avg_loss_pct": round(avg_loss, 4) if avg_loss else None,
        "win_loss_ratio": wl_ratio,
        "breakeven_wr_pct": bkeven,
        "win_n": win_n, "loss_n": loss_n,
    }


def _parse_ai_block_score(note: str) -> Optional[float]:
    """Extract AI score from OBSERVE_AI_BLOCK note field (e.g. 'score=0.665')."""
    m = re.search(r"AI score=([0-9.]+)", note)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    m = re.search(r"score=([0-9.]+)", note)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _build_ai_gate_snapshot(logs_dir: Optional[Path], lookback_days: int = 14) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "available": False, "lookback_days": lookback_days,
        "ai_pass_n": 0, "ai_block_n": 0, "pass_rate_pct": None, "by_day": [], "by_hour": {},
        "block_avg_score": None, "block_min_score": None,
    }
    if not logs_dir:
        return out
    today = datetime.now().date()
    total_pass = total_block = 0
    by_day = []
    hour_pass: Dict[int, int] = {}
    hour_block: Dict[int, int] = {}
    hour_block_scores: Dict[int, List[float]] = {}
    all_block_scores: List[float] = []
    for i in range(lookback_days - 1, -1, -1):
        d = today - timedelta(days=i)
        path = Path(logs_dir) / f"trade_log_{d.strftime('%Y%m%d')}.csv"
        if not path.exists():
            continue
        day_pass = day_block = 0
        for row in _read_trade_rows(path):
            result = str(row.get("result", "")).strip()
            t = _parse_dt(row.get("time"))
            h = t.hour if t else -1
            if result == "PAPER":
                day_pass += 1
                if h >= 0:
                    hour_pass[h] = hour_pass.get(h, 0) + 1
            elif result == "OBSERVE_AI_BLOCK":
                day_block += 1
                if h >= 0:
                    hour_block[h] = hour_block.get(h, 0) + 1
                    score = _parse_ai_block_score(str(row.get("note", "")))
                    if score is not None:
                        hour_block_scores.setdefault(h, []).append(score)
                        all_block_scores.append(score)
        total_pass += day_pass
        total_block += day_block
        if day_pass + day_block > 0:
            by_day.append({
                "day8": d.strftime("%Y%m%d"),
                "pass_n": day_pass, "block_n": day_block,
                "pass_rate_pct": round(day_pass / (day_pass + day_block) * 100.0, 1),
            })
    total = total_pass + total_block
    if total == 0:
        return out
    all_hours = sorted(set(list(hour_pass.keys()) + list(hour_block.keys())))
    by_hour: Dict[str, Any] = {}
    for h in all_hours:
        p = hour_pass.get(h, 0)
        b = hour_block.get(h, 0)
        tot = p + b
        scores = hour_block_scores.get(h, [])
        by_hour[str(h)] = {
            "pass_n": p, "block_n": b,
            "pass_rate_pct": round(p / tot * 100.0, 1) if tot > 0 else None,
            "block_avg_score": round(sum(scores) / len(scores), 3) if scores else None,
            "block_min_score": round(min(scores), 3) if scores else None,
        }
    block_avg = round(sum(all_block_scores) / len(all_block_scores), 3) if all_block_scores else None
    block_min = round(min(all_block_scores), 3) if all_block_scores else None
    return {
        "available": True,
        "lookback_days": lookback_days,
        "ai_pass_n": total_pass,
        "ai_block_n": total_block,
        "pass_rate_pct": round(total_pass / total * 100.0, 1),
        "by_day": by_day[-7:],
        "by_hour": by_hour,
        "block_avg_score": block_avg,
        "block_min_score": block_min,
    }


def _build_main_day_smart_exits(logs_dir: Optional[Path], day8: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "available": False, "day8": day8,
        "near_tp_giveback_n": 0, "progress_reversal_n": 0,
        "weak_progress_n": 0, "no_follow_through_n": 0, "smart_exit_total": 0,
    }
    if not logs_dir or not day8:
        return result
    log_path = Path(logs_dir) / f"trade_log_{day8}.csv"
    if not log_path.exists():
        return result
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        ntp = text.count("exit_tech=NEAR_TP_GIVEBACK")
        pr = text.count("exit_tech=PROGRESS_REVERSAL")
        wp = text.count("exit_tech=WEAK_PROGRESS")
        nf = text.count("exit_tech=NO_FOLLOW_THROUGH")
        result.update({
            "available": True,
            "near_tp_giveback_n": ntp, "progress_reversal_n": pr,
            "weak_progress_n": wp, "no_follow_through_n": nf,
            "smart_exit_total": ntp + pr + wp + nf,
        })
    except Exception:
        pass
    return result


def _latest_daily_reflection_snapshot(main_dir: Path) -> Dict[str, Any]:
    out = {
        "available": False,
        "day8": "",
        "generated_at": "",
        "goal_achieved": False,
        "sample_confidence": "",
        "next_actions": [],
        "win_notes": [],
        "loss_notes": [],
        "approval_status": "",
        "changed_keys": [],
        "shadow_filter_hint": "",
        "shadow_htf_hint": "",
        "shadow_exit_hint": "",
        "source_path": "",
    }
    out_dir = main_dir / "daily_report_out"
    try:
        files = sorted(out_dir.glob("daily_reflection_*.json"))
    except Exception:
        return out
    if not files:
        return out
    path = files[-1]
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return out
    if not isinstance(obj, dict):
        return out
    reflection = obj.get("reflection", {}) if isinstance(obj.get("reflection"), dict) else {}
    meta = obj.get("meta", {}) if isinstance(obj.get("meta"), dict) else {}
    approval = obj.get("approval", {}) if isinstance(obj.get("approval"), dict) else {}
    day8 = str(((obj.get("range") or {}).get("day8", "")) or path.stem.replace("daily_reflection_", "", 1))
    return {
        "available": True,
        "day8": day8,
        "generated_at": str(meta.get("generated_at_jst", "") or ""),
        "goal_achieved": bool(((obj.get("goal") or {}).get("achieved"))),
        "sample_confidence": str(reflection.get("sample_confidence", "") or ""),
        "next_actions": [str(x) for x in list(reflection.get("next_day_actions") or []) if str(x).strip()][:4],
        "win_notes": [str(x) for x in list(reflection.get("win_notes") or []) if str(x).strip()][:3],
        "loss_notes": [str(x) for x in list(reflection.get("loss_notes") or []) if str(x).strip()][:3],
        "approval_status": str(approval.get("status", "") or ""),
        "changed_keys": [str(x) for x in list(approval.get("changed_keys") or []) if str(x).strip()],
        "shadow_filter_hint": str(reflection.get("shadow_filter_hint", "") or ""),
        "shadow_htf_hint": str(reflection.get("shadow_htf_hint", "") or ""),
        "shadow_exit_hint": str(reflection.get("shadow_exit_hint", "") or ""),
        "source_path": str(path),
    }


def _read_control_csv(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    try:
        txt = _read_text_try(path)
        for row in csv.reader(txt.splitlines()):
            if len(row) < 2:
                continue
            key = str(row[0]).strip()
            if (not key) or key.lower() == "key":
                continue
            out[key] = str(row[1]).strip()
    except Exception:
        return {}
    return out


def _read_state_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _runner_alive(lock_dir: Path) -> bool:
    lock = lock_dir / "lockinfo.txt"
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


def _file_mtime_str(path: Path) -> str:
    if not path.exists():
        return "-"
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "-"


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
            continue
    return None


def _latest_trade_log_day(logs_dir: Optional[Path]) -> str:
    if not logs_dir:
        return ""
    try:
        files = sorted(logs_dir.glob("trade_log_*.csv"))
    except Exception:
        return ""
    if not files:
        return ""
    stem = files[-1].stem
    return stem.replace("trade_log_", "", 1)


def build_widget_status(
    main_dir: Path,
    control_path: Optional[Path] = None,
    state_path: Optional[Path] = None,
) -> Dict[str, Any]:
    main_dir = main_dir.expanduser().resolve()
    control_path = (control_path or (main_dir / "CONTROL.csv")).expanduser().resolve()
    state_path = (state_path or (main_dir / "state.json")).expanduser().resolve()

    ctrl = _read_control_csv(control_path)
    state = _read_state_json(state_path)
    logs_dir = find_logs_dir(main_dir)
    secrets_path = (main_dir / ".streamlit" / "secrets.toml").expanduser().resolve()
    goal = _build_daily_goal_snapshot(logs_dir, secrets_path if secrets_path.exists() else SECRETS_PATH_DEFAULT)
    balance = _load_account_balance_snapshot(ctrl)
    ibkr_account = _load_ibkr_account_snapshot(main_dir)
    bitflyer_account = dict(balance)
    latest_trade = _latest_trade_snapshot(logs_dir)
    sec = _load_notify_toml_section(secrets_path if secrets_path.exists() else SECRETS_PATH_DEFAULT, "dashboard_security")
    warn_sec = max(60, _safe_int(sec.get("widget_freshness_warn_sec"), 300))
    alert_sec = max(warn_sec + 60, _safe_int(sec.get("widget_freshness_alert_sec"), 900))
    freshness = _build_freshness_snapshot(state_path, latest_trade)
    age_sec = freshness.get("age_sec")
    if age_sec is not None:
        if int(age_sec) <= warn_sec:
            freshness["status"] = "OK"
        elif int(age_sec) <= alert_sec:
            freshness["status"] = "WARN"
        else:
            freshness["status"] = "ALERT"
    freshness["warn_sec"] = int(warn_sec)
    freshness["alert_sec"] = int(alert_sec)
    weekly = _build_weekly_snapshot(logs_dir, state=state)
    recent_trades = _recent_trades_snapshot(logs_dir, n=10)
    pnl_curve = _build_pnl_curve_snapshot(recent_trades)
    shadow_day = _notifier_build_shadow_day_snapshot(logs_dir, goal.get("day8", datetime.now().strftime("%Y%m%d")))
    main_day = _build_main_day_smart_exits(logs_dir, goal.get("day8", datetime.now().strftime("%Y%m%d")))
    sharpe = _build_sharpe_snapshot(logs_dir, lookback_days=30)
    pf = _build_pf_snapshot(logs_dir, lookback_days=30)
    fill_rate = _build_fill_rate_by_hour(logs_dir, lookback_days=14)
    ai_gate = _build_ai_gate_snapshot(logs_dir, lookback_days=14)
    latest_reflection = _latest_daily_reflection_snapshot(main_dir)
    versions = _build_version_snapshot()
    phase_obj = state.get("_market_phase", {}) if isinstance(state.get("_market_phase"), dict) else {}
    market_phase = {
        "phase": str(phase_obj.get("phase", "-") or "-"),
        "previous_phase": str(phase_obj.get("previous_phase", "") or ""),
        "transition": str(phase_obj.get("transition", "") or ""),
        "phase_reason": str(phase_obj.get("phase_reason", "") or ""),
        "momentum": str(phase_obj.get("momentum", "") or ""),
        "changed_at_jst": str(phase_obj.get("changed_at_jst", "") or ""),
        "updated_at_jst": str(phase_obj.get("updated_at_jst", "") or ""),
    }
    fib_obj = state.get("_fib_last", {}) if isinstance(state.get("_fib_last"), dict) else {}
    fib_last = {
        "zone": str(fib_obj.get("zone", "") or ""),
        "wave3_candidate": bool(fib_obj.get("wave3_candidate", False)),
        "retrace_pct": fib_obj.get("retrace_pct"),
        "swing_range_pct": fib_obj.get("swing_range_pct"),
        "side": str(fib_obj.get("side", "") or ""),
        "updated_at_jst": str(fib_obj.get("updated_at_jst", "") or ""),
    } if fib_obj else None

    drift_obj = state.get("_drift_watch", {}) if isinstance(state.get("_drift_watch"), dict) else {}
    gate = drift_obj.get("gate", {}) if isinstance(drift_obj.get("gate"), dict) else {}
    recent = drift_obj.get("recent_metrics", {}) if isinstance(drift_obj.get("recent_metrics"), dict) else {}

    closed_n = max(0, _safe_int(recent.get("closed_n"), 0))
    min_recent_closed = max(1, _safe_int(gate.get("min_recent_closed"), 1))
    remaining_samples = max(0, min_recent_closed - closed_n)
    normal_streak = max(0, _safe_int(drift_obj.get("normal_streak"), 0))
    need_normals = max(1, _safe_int(gate.get("resume_require_consecutive_normal"), 1))
    remaining_normals = max(0, need_normals - normal_streak)
    canary_streak = max(0, _safe_int(drift_obj.get("canary_streak"), 0))
    canary_required = max(0, _safe_int(gate.get("resume_canary_runs"), 0))
    resume_outlook = build_drift_resume_snapshot(drift_obj)

    stage = str(state.get("_effective_stage", ctrl.get("rollout_mode", "-")) or "-")
    trade_enabled = _safe_bool(ctrl.get("trade_enabled", "0"))
    today_on = _safe_bool(ctrl.get("today_on", "0"))
    live_enabled = _safe_bool(ctrl.get("live_enabled", "0"))
    paper_mode = _safe_bool(ctrl.get("paper_mode", "0"))
    safety_hard_block = _safe_bool(ctrl.get("safety_hard_block", "0"))
    risk_stop = _safe_bool(state.get("_risk_stop", False))
    streak_stop = _safe_bool(state.get("_streak_stop", False))
    runner_alive = _runner_alive(main_dir / ".run_lock")
    shadow_runner_alive = _runner_alive(main_dir / ".run_lock_shadow")
    ai_auto_train_enabled = _safe_bool(ctrl.get("ai_auto_train_enabled", "1"), True)
    ai_gate_enabled = _safe_bool(ctrl.get("ai_gate_enabled", "1"), True)
    daily_loss_limit_pct = _safe_float(ctrl.get("daily_loss_limit_pct"))
    daily_profit_stop_pct = _safe_float(ctrl.get("daily_profit_stop_pct"))
    risk_realized_pct = _safe_float(state.get("_risk_realized_pct"))
    drift_status = str(drift_obj.get("status", "UNKNOWN") or "UNKNOWN").upper()
    resume_ready = bool(drift_obj.get("resume_ready"))
    canary_ready = bool(drift_obj.get("canary_ready"))
    canary_active = bool(drift_obj.get("canary_active"))

    mode_label = "PAPER" if paper_mode else ("LIVE" if live_enabled else "LOCAL")
    warnings: List[str] = []
    if safety_hard_block:
        warnings.append("safety_hard_block=1")
    if risk_stop:
        warnings.append("risk_stop=ON")
    if streak_stop:
        warnings.append("streak_stop=ON")
    if not today_on:
        warnings.append("today_on=0")
    if not trade_enabled:
        warnings.append("trade_enabled=0")
    if not runner_alive:
        warnings.append("runner=STOPPED")
    if drift_status == "ALERT":
        warnings.append("drift_status=ALERT")
    elif drift_status == "INSUFFICIENT":
        warnings.append(f"drift gate remaining={remaining_samples}")
    elif drift_status in {"UNKNOWN", "-"}:
        warnings.append("drift_status=UNKNOWN")
    if freshness.get("status") == "ALERT":
        warnings.append(f"freshness=ALERT {freshness.get('age_text', '-')}")
    if ibkr_account.get("available") and ibkr_account.get("stale"):
        warnings.append(f"ibkr_account=STALE {ibkr_account.get('age_hours')}h")

    if safety_hard_block or risk_stop or drift_status == "ALERT":
        status_level = "ALERT"
    elif freshness.get("status") == "ALERT":
        status_level = "ALERT"
    elif warnings or freshness.get("status") == "WARN":
        status_level = "WARN"
    else:
        status_level = "OK"

    headline = f"{stage} / trade {'ON' if trade_enabled else 'OFF'} / drift {drift_status}"
    summary_text = (
        f"stage={stage} mode={mode_label} trade={'ON' if trade_enabled else 'OFF'} "
        f"risk={'ON' if risk_stop else 'OFF'} runner={'ON' if runner_alive else 'OFF'} "
        f"drift={drift_status} remain={remaining_samples} "
        f"resume={resume_outlook.get('short', '-')} "
        f"goal={_goal_text(goal)} shadow={_shadow_day_text(shadow_day)} "
        f"fresh={freshness.get('status', '-')} "
        f"ver={_versions_text(versions)}"
    )

    return {
        "version": 1,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status_level": status_level,
        "headline": headline,
        "summary_text": summary_text,
        "goal": goal,
        "balance": balance,
        "bitflyer_account": bitflyer_account,
        "ibkr_account": ibkr_account,
        "freshness": freshness,
        "latest_trade": latest_trade,
        "recent_trades": recent_trades,
        "pnl_curve": pnl_curve,
        "weekly": weekly,
        "shadow_day": shadow_day,
        "latest_reflection": latest_reflection,
        "versions": versions,
        "market_phase": market_phase,
        "fib_last": fib_last,
        "mode_label": mode_label,
        "effective_stage": stage,
        "trade_enabled": trade_enabled,
        "today_on": today_on,
        "live_enabled": live_enabled,
        "paper_mode": paper_mode,
        "safety_hard_block": safety_hard_block,
        "risk_stop": risk_stop,
        "streak_stop": streak_stop,
        "streak_consecutive_losses": max(0, _safe_int(state.get("_streak_consecutive_losses"), 0)),
        "runner_alive": runner_alive,
        "shadow_runner_alive": shadow_runner_alive,
        "ai_auto_train_enabled": ai_auto_train_enabled,
        "ai_gate_enabled": ai_gate_enabled,
        "daily_loss_limit_pct": daily_loss_limit_pct,
        "daily_profit_stop_pct": daily_profit_stop_pct,
        "risk_realized_pct": risk_realized_pct,
        "main_day": main_day,
        "sharpe": sharpe,
        "pf": pf,
        "fill_rate": fill_rate,
        "ai_gate": {**ai_gate, "ai_threshold": _safe_float(ctrl.get("ai_threshold"))},
        "last_ai_auto_train_day": str(state.get("_ai_auto_train_day", "-") or "-"),
        "daily_pnl_jpy": goal.get("pnl_jpy"),
        "daily_closed_n": goal.get("closed_n"),
        "daily_pnl_available": bool(goal.get("pnl_available", False)),
        "latest_trade_log_day": _latest_trade_log_day(logs_dir),
        "source": {
            "main_dir": str(main_dir),
            "control_path": str(control_path),
            "state_path": str(state_path),
            "logs_dir": str(logs_dir) if logs_dir else "",
            "control_mtime": _file_mtime_str(control_path),
            "state_mtime": _file_mtime_str(state_path),
        },
        "drift": {
            "status": drift_status,
            "updated_at": str(drift_obj.get("updated_at", "-") or "-"),
            "closed_n": closed_n,
            "min_recent_closed": min_recent_closed,
            "remaining_samples": remaining_samples,
            "normal_streak": normal_streak,
            "required_normals": need_normals,
            "remaining_normals": remaining_normals,
            "resume_ready": resume_ready,
            "canary_streak": canary_streak,
            "canary_required": canary_required,
            "canary_ready": canary_ready,
            "canary_active": canary_active,
            "reasons": [str(x) for x in (drift_obj.get("reasons") or []) if str(x).strip()],
            "resume_outlook": resume_outlook,
        },
        "warnings": warnings,
    }


def format_status_text(status: Dict[str, Any]) -> str:
    drift = status.get("drift", {}) if isinstance(status.get("drift"), dict) else {}
    goal = status.get("goal", {}) if isinstance(status.get("goal"), dict) else {}
    balance = status.get("balance", {}) if isinstance(status.get("balance"), dict) else {}
    freshness = status.get("freshness", {}) if isinstance(status.get("freshness"), dict) else {}
    latest_trade = status.get("latest_trade", {}) if isinstance(status.get("latest_trade"), dict) else {}
    weekly = status.get("weekly", {}) if isinstance(status.get("weekly"), dict) else {}
    shadow_day = status.get("shadow_day", {}) if isinstance(status.get("shadow_day"), dict) else {}
    latest_reflection = status.get("latest_reflection", {}) if isinstance(status.get("latest_reflection"), dict) else {}
    market_phase = status.get("market_phase", {}) if isinstance(status.get("market_phase"), dict) else {}
    versions = status.get("versions", {}) if isinstance(status.get("versions"), dict) else {}
    versions = status.get("versions", {}) if isinstance(status.get("versions"), dict) else {}
    lines = [
        f"[{status.get('status_level', '-')}] {status.get('headline', '-')}",
        (
            "mode={mode} risk={risk} streak={streak} runner={runner} ai_train={ai_train} daily_limit={limit}".format(
                mode=status.get("mode_label", "-"),
                risk="ON" if status.get("risk_stop") else "OFF",
                streak="ON" if status.get("streak_stop") else "OFF",
                runner="ON" if status.get("runner_alive") else "OFF",
                ai_train="ON" if status.get("ai_auto_train_enabled") else "OFF",
                limit=_fmt_float(status.get("daily_loss_limit_pct")),
            )
        ),
        (
            "drift={st} samples={closed}/{need} remain={remain} resume={resume} canary={canary}/{canary_need}".format(
                st=drift.get("status", "-"),
                closed=drift.get("closed_n", "-"),
                need=drift.get("min_recent_closed", "-"),
                remain=drift.get("remaining_samples", "-"),
                resume="ON" if drift.get("resume_ready") else "OFF",
                canary=drift.get("canary_streak", "-"),
                canary_need=drift.get("canary_required", "-"),
            )
        ),
        (
            "resume_outlook={summary} detail={detail}".format(
                summary=((drift.get("resume_outlook") or {}).get("summary", "-")),
                detail=((drift.get("resume_outlook") or {}).get("detail", "-")),
            )
        ),
        (
            "market_phase={phase} transition={transition} reason={reason} momentum={momentum} changed={changed}".format(
                phase=market_phase.get("phase", "-"),
                transition=market_phase.get("transition", "-") or "-",
                reason=market_phase.get("phase_reason", "-") or "-",
                momentum=market_phase.get("momentum", "-") or "-",
                changed=market_phase.get("changed_at_jst", "-") or "-",
            )
        ),
        (
            "updated=state:{state_mtime} drift:{drift_updated}".format(
                state_mtime=((status.get("source") or {}).get("state_mtime", "-")),
                drift_updated=drift.get("updated_at", "-"),
            )
        ),
        (
            "goal=day:{day8} pnl_jpy:{pnl} target:{goal_jpy} remain:{remain} achieved:{achieved}".format(
                day8=goal.get("day8", "-"),
                pnl=_fmt_jpy(_safe_float(goal.get("pnl_jpy")), 0),
                goal_jpy=_fmt_jpy(_safe_float(goal.get("goal_jpy")), 0),
                remain=_fmt_jpy(_safe_float(goal.get("remaining_jpy")), 0),
                achieved="ON" if goal.get("achieved") else "OFF",
            )
        ),
        (
            "balance={label}:{value}".format(
                label=str(balance.get("label", "残高") or "残高"),
                value=_fmt_jpy(_safe_float(balance.get("jpy")), 0) if balance.get("available") else "-",
            )
        ),
        (
            "freshness={status} ref={ref} age={age}".format(
                status=freshness.get("status", "-"),
                ref=freshness.get("reference", "-"),
                age=freshness.get("age_text", "-"),
            )
        ),
        (
            "latest_trade={kind} {reason} pnl_jpy:{pnl} age:{age}".format(
                kind=latest_trade.get("kind", "-"),
                reason=latest_trade.get("reason", "-"),
                pnl=_fmt_jpy(_safe_float(latest_trade.get("pnl_jpy")), 0),
                age=latest_trade.get("age_text", "-"),
            )
        ),
        (
            "weekly=pnl_jpy:{pnl} win:{win} close:{close} hint:{hint}".format(
                pnl=_fmt_jpy(_safe_float(weekly.get("pnl_jpy_sum")), 0),
                win=f"{float(_safe_float(weekly.get('win_rate_pct')) or 0.0):.1f}%",
                close=weekly.get("closed_n", "-"),
                hint=_weekly_hint_text(weekly),
            )
        ),
        (
            "shadow=day:{day8} pnl_jpy:{pnl} win:{win} close:{close} tech:{tech} weak:{weak} progress_reversal:{progress_reversal} near_tp:{near_tp} progress_timeout:{progress_timeout} no_follow:{no_follow} trend:{trend} htf60:{htf60} conflict:{conflict} timeout:{timeout}".format(
                day8=shadow_day.get("day8", "-"),
                pnl=_fmt_jpy(_safe_float(shadow_day.get("pnl_jpy_sum")), 0),
                win=f"{float(_safe_float(shadow_day.get('win_rate_pct')) or 0.0):.1f}%",
                close=shadow_day.get("closed_n", "-"),
                tech=shadow_day.get("exit_technical_n", "-"),
                weak=shadow_day.get("weak_progress_exit_n", "-"),
                progress_reversal=shadow_day.get("progress_reversal_exit_n", "-"),
                near_tp=shadow_day.get("near_tp_giveback_exit_n", "-"),
                progress_timeout=shadow_day.get("progress_timeout_n", "-"),
                no_follow=shadow_day.get("no_follow_through_exit_n", "-"),
                trend=shadow_day.get("observe_trend_strength_weak_n", "-"),
                htf60=shadow_day.get("observe_ai_block_htf60_countertrend_n", "-"),
                conflict=shadow_day.get("observe_ai_block_htf15_60_conflict_n", "-"),
                timeout=shadow_day.get("plain_timeout_n", shadow_day.get("timeout_n", "-")),
            )
        ),
        (
            "reflection=day:{day8} achieved:{achieved} adjust:{adjust}".format(
                day8=latest_reflection.get("day8", "-") if latest_reflection.get("available") else "-",
                achieved=("ON" if latest_reflection.get("goal_achieved") else "OFF") if latest_reflection.get("available") else "-",
                adjust=_shadow_adjustment_text(latest_reflection) or "-",
            )
        ),
        (
            "versions=bot:{bot} schema:{schema} dashboard:{dashboard} widget:{widget} yt:{yt} mr:{mr} handover:{handover}".format(
                bot=versions.get("bot_logic", "-"),
                schema=versions.get("feature_schema", "-"),
                dashboard=versions.get("dashboard", "-"),
                widget=versions.get("widget_status_server", "-"),
                yt=versions.get("yt_tool", "-"),
                mr=versions.get("mr_observe_phase", "-"),
                handover=versions.get("handover_updated_at_jst", "-"),
            )
        ),
    ]
    warnings = status.get("warnings") or []
    if warnings:
        lines.append("warn=" + "; ".join(str(x) for x in warnings))
    return "\n".join(lines)


def format_swiftbar(status: Dict[str, Any]) -> str:
    color = {
        "OK": "#059669",
        "WARN": "#d97706",
        "ALERT": "#dc2626",
    }.get(str(status.get("status_level", "WARN")).upper(), "#64748b")
    drift = status.get("drift", {}) if isinstance(status.get("drift"), dict) else {}
    goal = status.get("goal", {}) if isinstance(status.get("goal"), dict) else {}
    balance = status.get("balance", {}) if isinstance(status.get("balance"), dict) else {}
    freshness = status.get("freshness", {}) if isinstance(status.get("freshness"), dict) else {}
    latest_trade = status.get("latest_trade", {}) if isinstance(status.get("latest_trade"), dict) else {}
    weekly = status.get("weekly", {}) if isinstance(status.get("weekly"), dict) else {}
    shadow_day = status.get("shadow_day", {}) if isinstance(status.get("shadow_day"), dict) else {}
    latest_reflection = status.get("latest_reflection", {}) if isinstance(status.get("latest_reflection"), dict) else {}
    market_phase = status.get("market_phase", {}) if isinstance(status.get("market_phase"), dict) else {}
    versions = status.get("versions", {}) if isinstance(status.get("versions"), dict) else {}
    title = (
        f"OB {status.get('status_level', '-')} "
        f"{'TRD-ON' if status.get('trade_enabled') else 'TRD-OFF'} "
        f"{drift.get('status', '-')}"
    )
    lines = [
        f"{title} | color={color}",
        "---",
        f"Stage: {status.get('effective_stage', '-')}",
        f"Mode: {status.get('mode_label', '-')}",
        f"Trade: {'ON' if status.get('trade_enabled') else 'OFF'}",
        f"Risk Stop: {'ON' if status.get('risk_stop') else 'OFF'}",
        f"Runner: {'ON' if status.get('runner_alive') else 'OFF'}",
        f"Drift: {drift.get('status', '-')}",
        f"Drift Samples: {drift.get('closed_n', '-')} / {drift.get('min_recent_closed', '-')}",
        f"Drift Remain: {drift.get('remaining_samples', '-')}",
        f"Resume Outlook: {((drift.get('resume_outlook') or {}).get('summary', '-'))}",
        f"Market Phase: {market_phase.get('phase', '-')} / {market_phase.get('transition', '-') or '-'} / {market_phase.get('momentum', '-') or '-'}",
        f"Daily Goal: {_fmt_jpy(_safe_float(goal.get('pnl_jpy')), 0)} / {_fmt_jpy(_safe_float(goal.get('goal_jpy')), 0)}",
        f"Balance: {_fmt_jpy(_safe_float(balance.get('jpy')), 0) if balance.get('available') else '-'}",
        f"Freshness: {freshness.get('status', '-')} / {freshness.get('age_text', '-')}",
        f"Latest Trade: {latest_trade.get('reason', '-')}{(' ' + _fmt_jpy(_safe_float(latest_trade.get('pnl_jpy')), 0)) if latest_trade.get('pnl_jpy') is not None else ''}",
        f"Week: {_fmt_jpy(_safe_float(weekly.get('pnl_jpy_sum')), 0)} / {float(_safe_float(weekly.get('win_rate_pct')) or 0.0):.1f}% / {_weekly_hint_text(weekly)}",
        f"Shadow Day: {_fmt_jpy(_safe_float(shadow_day.get('pnl_jpy_sum')), 0)} / close {shadow_day.get('closed_n', '-')} / tech {shadow_day.get('exit_technical_n', '-')} / weak {shadow_day.get('weak_progress_exit_n', '-')} / pr {shadow_day.get('progress_reversal_exit_n', '-')} / ntp {shadow_day.get('near_tp_giveback_exit_n', '-')} / pto {shadow_day.get('progress_timeout_n', '-')} / nf {shadow_day.get('no_follow_through_exit_n', '-')} / trend {shadow_day.get('observe_trend_strength_weak_n', '-')} / htf60 {shadow_day.get('observe_ai_block_htf60_countertrend_n', '-')} / conflict {shadow_day.get('observe_ai_block_htf15_60_conflict_n', '-')} / timeout {shadow_day.get('plain_timeout_n', shadow_day.get('timeout_n', '-'))} / {float(_safe_float(shadow_day.get('win_rate_pct')) or 0.0):.1f}%",
        f"Reflection: {(latest_reflection.get('day8', '-') if latest_reflection.get('available') else '-')} / {(_shadow_adjustment_text(latest_reflection) or '-')}",
        f"Version: {versions.get('summary', '-')} / {versions.get('detail', '-')}",
        f"Resume Ready: {'ON' if drift.get('resume_ready') else 'OFF'}",
        f"Generated: {status.get('generated_at', '-')}",
    ]
    warnings = status.get("warnings") or []
    if warnings:
        lines.append("---")
        for item in warnings[:6]:
            lines.append(f"! {item}")
    lines.append("---")
    lines.append("Refresh | refresh=true")
    return "\n".join(lines)


def _widget_app_suffix(token: str) -> str:
    return f"?token={quote(token, safe='')}" if token else ""


def _widget_app_manifest(token: str) -> Dict[str, Any]:
    suffix = _widget_app_suffix(token)
    start_url = f"/widget-app{suffix}{'&' if suffix else '?'}source=pwa"
    return {
        "name": WIDGET_APP_NAME,
        "short_name": WIDGET_APP_SHORT_NAME,
        "description": "Ouroboros の軽量監視ウィジェットアプリ",
        "display": "standalone",
        "background_color": "#f8fafc",
        "theme_color": "#0f172a",
        "start_url": start_url,
        "scope": "/",
        "lang": "ja",
    }


def _widget_app_service_worker(token: str) -> str:
    suffix = _widget_app_suffix(token)
    return f"""const CACHE_NAME = "ouroboros-widget-shell-v2";
const SHELL_URLS = ["/widget-app{suffix}", "/widget-status.json{suffix}", "/daily-reflection.json{suffix}"];
const OFFLINE_STATUS = {{
  status_level: "WARN",
  effective_stage: "OFFLINE",
  mode_label: "OFFLINE",
  generated_at: "",
  trade_enabled: false,
  runner_alive: false,
  risk_stop: false,
  streak_stop: false,
  ai_auto_train_enabled: false,
  daily_loss_limit_pct: "-",
  drift: {{
    status: "PAUSED",
    remaining_samples: 0,
    resume_ready: false,
    reasons: ["offline cache unavailable"],
    resume_outlook: {{
      short: "オフライン",
      summary: "ネット接続を確認"
    }}
  }},
  goal: {{}},
  balance: {{ available: false }},
  freshness: {{
    status: "WARN",
    summary: "オフライン表示"
  }},
  latest_trade: {{ available: false }},
  weekly: {{ available: false }},
  shadow_day: {{ available: false }},
  latest_reflection: {{ available: false }},
  versions: {{
    summary: "offline",
    detail: "cached shell only"
  }},
  source: {{
    state_mtime: ""
  }},
  warnings: ["offline_mode=ON"],
  offline_mode: true
}};
const OFFLINE_REFLECTION = {{
  available: false,
  offline_mode: true,
  note: "offline"
}};

async function cachePut(req, res) {{
  try {{
    const cache = await caches.open(CACHE_NAME);
    await cache.put(req, res.clone());
  }} catch (_err) {{
  }}
  return res;
}}

async function offlineJsonResponse(req, fallback) {{
  const hit = await caches.match(req);
  if (hit) {{
    const text = await hit.text();
    return new Response(text, {{
      status: 200,
      headers: {{
        "Content-Type": "application/json; charset=utf-8",
        "X-Ouroboros-Offline": "1"
      }}
    }});
  }}
  return new Response(JSON.stringify(fallback), {{
    status: 200,
    headers: {{
      "Content-Type": "application/json; charset=utf-8",
      "X-Ouroboros-Offline": "1"
    }}
  }});
}}

self.addEventListener("install", (event) => {{
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_URLS)).catch(() => undefined));
}});

self.addEventListener("activate", (event) => {{
  event.waitUntil(self.clients.claim());
}});

self.addEventListener("fetch", (event) => {{
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.pathname === "/widget-status.json") {{
    event.respondWith(
      fetch(req).then((res) => cachePut(req, res)).catch(() => offlineJsonResponse(req, OFFLINE_STATUS))
    );
    return;
  }}
  if (url.pathname === "/daily-reflection.json") {{
    event.respondWith(
      fetch(req).then((res) => cachePut(req, res)).catch(() => offlineJsonResponse(req, OFFLINE_REFLECTION))
    );
    return;
  }}
  event.respondWith(
    fetch(req).then((res) => cachePut(req, res)).catch(() => caches.match(req).then((hit) => hit || caches.match("/widget-app{suffix}")))
  );
}});
"""


def _widget_app_icon_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 180" role="img" aria-label="Ouroboros Widget">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0%" stop-color="#111827"/>
      <stop offset="100%" stop-color="#1f2937"/>
    </linearGradient>
    <linearGradient id="ring" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0%" stop-color="#FF8A5B"/>
      <stop offset="100%" stop-color="#FF6B3B"/>
    </linearGradient>
  </defs>
  <rect x="8" y="8" width="164" height="164" rx="38" fill="url(#bg)"/>
  <circle cx="90" cy="90" r="44" fill="none" stroke="url(#ring)" stroke-width="18" stroke-linecap="round" stroke-dasharray="220 74" transform="rotate(-28 90 90)"/>
  <circle cx="127" cy="67" r="8.5" fill="#FFF4EF"/>
  <circle cx="129" cy="66" r="2.2" fill="#0f172a"/>
  <path d="M62 117c10 7 22 11 35 11 14 0 27-4 38-12" fill="none" stroke="#F8FAFC" stroke-opacity="0.88" stroke-width="8" stroke-linecap="round"/>
  <rect x="54" y="48" width="18" height="8" rx="4" fill="#F8FAFC" fill-opacity="0.9"/>
  <rect x="47" y="65" width="30" height="8" rx="4" fill="#F8FAFC" fill-opacity="0.62"/>
</svg>"""


def _widget_home_manifest(token: str) -> Dict[str, Any]:
    suffix = _widget_app_suffix(token)
    start_url = f"/widget-home{suffix}{'&' if suffix else '?'}source=pwa"
    return {
        "name": "Ouroboros Home",
        "short_name": "Ouroboros",
        "description": "Ouroboros status home screen",
        "display": "standalone",
        "background_color": "#111827",
        "theme_color": "#111827",
        "start_url": start_url,
        "scope": "/",
        "lang": "ja",
        "icons": [
            {"src": "/widget-app-icon.svg", "sizes": "180x180", "type": "image/svg+xml", "purpose": "any maskable"},
        ],
    }


def _widget_home_service_worker(token: str) -> str:
    suffix = _widget_app_suffix(token)
    return f"""const CACHE_NAME = "ouroboros-widget-home-v1";
const SHELL_URLS = ["/widget-home{suffix}", "/widget-status.json{suffix}", "/daily-reflection.json{suffix}", "/widget-app-icon.svg"];
const OFFLINE_STATUS = {{
  status_level: "WARN",
  effective_stage: "OFFLINE",
  mode_label: "OFFLINE",
  generated_at: "",
  trade_enabled: false,
  runner_alive: false,
  risk_stop: false,
  streak_stop: false,
  drift: {{ status: "PAUSED", remaining_samples: 0, resume_ready: false }},
  goal: {{}},
  balance: {{ available: false }},
  freshness: {{ status: "WARN", summary: "offline" }},
  latest_trade: {{ available: false }},
  weekly: {{ available: false }},
  latest_reflection: {{ available: false }},
  warnings: ["offline_mode=ON"],
  offline_mode: true
}};

async function cachePut(req, res) {{
  try {{
    const cache = await caches.open(CACHE_NAME);
    await cache.put(req, res.clone());
  }} catch (_err) {{}}
  return res;
}}

async function offlineJsonResponse(req, fallback) {{
  const hit = await caches.match(req);
  if (hit) return hit;
  return new Response(JSON.stringify(fallback), {{
    status: 200,
    headers: {{"Content-Type": "application/json; charset=utf-8", "X-Ouroboros-Offline": "1"}}
  }});
}}

self.addEventListener("install", (event) => {{
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_URLS)).catch(() => undefined));
}});

self.addEventListener("activate", (event) => {{
  event.waitUntil(self.clients.claim());
}});

self.addEventListener("fetch", (event) => {{
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.pathname === "/widget-status.json") {{
    event.respondWith(fetch(req).then((res) => cachePut(req, res)).catch(() => offlineJsonResponse(req, OFFLINE_STATUS)));
    return;
  }}
  event.respondWith(fetch(req).then((res) => cachePut(req, res)).catch(() => caches.match(req).then((hit) => hit || caches.match("/widget-home{suffix}"))));
}});
"""


def _widget_home_page_html(token: str = "", native_shell: bool = False) -> str:
    app_suffix = _widget_app_suffix(token)
    widget_app_href = f"/widget-app{app_suffix}"
    reflection_href = f"/daily-reflection{app_suffix}"
    dashboard_href = "/dashboard"
    page = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#111827">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Ouroboros">
  <link rel="icon" href="/widget-app-icon.svg">
  <link rel="apple-touch-icon" href="/widget-app-icon.svg">
  <title>Ouroboros Home</title>
  <style>
    :root {
      --text: #f8fafc;
      --muted: rgba(226, 232, 240, 0.74);
      --glass: rgba(15, 23, 42, 0.62);
      --glass-strong: rgba(10, 16, 30, 0.78);
      --line: rgba(255, 255, 255, 0.14);
      --green: #34d399;
      --amber: #fbbf24;
      --red: #fb7185;
      --blue: #60a5fa;
      --coral: #fb8a5d;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; }
    body {
      font-family: "Avenir Next", "Hiragino Sans", "Noto Sans JP", sans-serif;
      color: var(--text);
      background:
        radial-gradient(120% 78% at 18% 0%, rgba(148, 163, 184, 0.48), transparent 55%),
        radial-gradient(100% 82% at 88% 8%, rgba(251, 138, 93, 0.32), transparent 54%),
        linear-gradient(180deg, #202a45 0%, #111827 50%, #080b12 100%);
      overflow-x: hidden;
    }
    .screen {
      min-height: 100vh;
      padding: max(14px, env(safe-area-inset-top)) 16px max(24px, env(safe-area-inset-bottom));
      position: relative;
    }
    .statusbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 36px;
      font-size: 15px;
      font-weight: 800;
    }
    .icons { display: inline-flex; align-items: center; gap: 8px; font-size: 11px; color: rgba(248,250,252,0.9); }
    .bars { display: inline-grid; grid-template-columns: repeat(4, 3px); gap: 2px; align-items: end; height: 12px; }
    .bars span { display: block; width: 3px; border-radius: 99px; background: #fff; }
    .bars span:nth-child(1) { height: 5px; opacity: .68; }
    .bars span:nth-child(2) { height: 7px; opacity: .78; }
    .bars span:nth-child(3) { height: 9px; opacity: .9; }
    .bars span:nth-child(4) { height: 11px; }
    .battery { border: 1px solid rgba(255,255,255,.36); border-radius: 7px; padding: 2px 6px; }
    .island {
      width: 126px;
      height: 36px;
      border-radius: 999px;
      margin: -20px auto 18px;
      background: rgba(0,0,0,.94);
      box-shadow: 0 14px 30px rgba(0,0,0,.38);
    }
    .home-head {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 12px;
      margin: 2px 2px 12px;
    }
    .home-title { font-size: 19px; font-weight: 900; line-height: 1.1; }
    .home-sub { color: var(--muted); font-size: 11px; margin-top: 3px; }
    .live-pill {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 7px 10px;
      border-radius: 999px;
      background: rgba(255,255,255,.13);
      border: 1px solid rgba(255,255,255,.14);
      color: rgba(248,250,252,.9);
      font-size: 11px;
      font-weight: 800;
      white-space: nowrap;
    }
    .dot { width: 7px; height: 7px; border-radius: 99px; background: var(--amber); box-shadow: 0 0 14px var(--amber); }
    .dot.ok { background: var(--green); box-shadow: 0 0 14px var(--green); }
    .dot.alert { background: var(--red); box-shadow: 0 0 14px var(--red); }
    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      align-items: stretch;
    }
    .tile {
      min-height: 86px;
      border-radius: 22px;
      padding: 12px;
      background: linear-gradient(180deg, rgba(255,255,255,.13), rgba(255,255,255,.07));
      border: 1px solid var(--line);
      box-shadow: 0 14px 32px rgba(0,0,0,.22), inset 0 1px 0 rgba(255,255,255,.08);
      backdrop-filter: blur(18px) saturate(150%);
      overflow: hidden;
      position: relative;
    }
    .tile::after {
      content: "";
      position: absolute;
      left: 12px;
      right: 12px;
      bottom: 9px;
      height: 3px;
      border-radius: 999px;
      background: rgba(255,255,255,.22);
    }
    .wide { grid-column: span 4; min-height: 156px; }
    .half { grid-column: span 2; min-height: 132px; }
    .small { grid-column: span 2; }
    .tile-label {
      color: rgba(226,232,240,.72);
      font-size: 10px;
      font-weight: 800;
      letter-spacing: .08em;
      text-transform: uppercase;
      margin-bottom: 8px;
    }
    .tile-value {
      font-size: 27px;
      font-weight: 900;
      line-height: 1;
      word-break: keep-all;
    }
    .wide .tile-value { font-size: 38px; }
    .tile-sub {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      margin-top: 8px;
    }
    .mini-row {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 14px;
    }
    .mini {
      border-radius: 14px;
      padding: 8px;
      background: rgba(0,0,0,.18);
      min-width: 0;
    }
    .mini b { display: block; font-size: 12px; }
    .mini span { display: block; color: var(--muted); font-size: 10px; margin-top: 3px; }
    .warn-list {
      display: grid;
      gap: 7px;
      margin-top: 10px;
    }
    .warn-item {
      border-radius: 12px;
      padding: 8px 9px;
      background: rgba(0,0,0,.18);
      color: rgba(248,250,252,.86);
      font-size: 11px;
      line-height: 1.35;
    }
    .dock {
      position: sticky;
      bottom: max(12px, env(safe-area-inset-bottom));
      z-index: 5;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-top: 18px;
      padding: 10px;
      border-radius: 28px;
      background: rgba(255,255,255,.16);
      border: 1px solid rgba(255,255,255,.16);
      backdrop-filter: blur(24px) saturate(170%);
      box-shadow: 0 18px 44px rgba(0,0,0,.24);
    }
    .dock a {
      color: rgba(248,250,252,.88);
      text-decoration: none;
      text-align: center;
      font-size: 10px;
      font-weight: 800;
      display: grid;
      gap: 5px;
      justify-items: center;
    }
    .dock-icon {
      width: 42px;
      height: 42px;
      border-radius: 13px;
      display: grid;
      place-items: center;
      background: linear-gradient(145deg, rgba(96,165,250,.88), rgba(52,211,153,.78));
      box-shadow: 0 8px 18px rgba(0,0,0,.28), inset 0 1px 0 rgba(255,255,255,.2);
      color: #06111f;
      font-size: 16px;
      font-weight: 900;
    }
    .dock a:nth-child(2) .dock-icon { background: linear-gradient(145deg, rgba(251,191,36,.9), rgba(251,138,93,.78)); }
    .dock a:nth-child(3) .dock-icon { background: linear-gradient(145deg, rgba(167,139,250,.9), rgba(96,165,250,.78)); }
    .dock a:nth-child(4) .dock-icon { background: linear-gradient(145deg, rgba(248,250,252,.88), rgba(148,163,184,.72)); }
    .home-indicator {
      width: 134px;
      height: 5px;
      border-radius: 99px;
      background: rgba(255,255,255,.54);
      margin: 12px auto 0;
    }
    .green { color: var(--green); }
    .amber { color: var(--amber); }
    .red { color: var(--red); }
    .blue { color: var(--blue); }
    body.native-shell .screen {
      padding: 14px 16px max(18px, env(safe-area-inset-bottom));
    }
    body.native-shell .statusbar,
    body.native-shell .island,
    body.native-shell .dock,
    body.native-shell .home-indicator {
      display: none;
    }
    body.native-shell .home-head {
      margin-top: 4px;
    }
    body.native-shell .wide {
      min-height: 148px;
    }
    @media (min-width: 720px) {
      body { display: grid; place-items: center; padding: 24px; }
      body.native-shell { display: block; padding: 0; }
      .screen {
        width: 430px;
        min-height: 900px;
        border-radius: 46px;
        overflow: hidden;
        box-shadow: 0 30px 90px rgba(0,0,0,.45);
      }
      body.native-shell .screen {
        width: auto;
        min-height: 100vh;
        border-radius: 0;
        box-shadow: none;
      }
    }
    @media (max-width: 380px) {
      .tile { border-radius: 18px; padding: 10px; }
      .wide .tile-value { font-size: 32px; }
      .tile-value { font-size: 23px; }
      .dock-icon { width: 38px; height: 38px; }
    }
  </style>
</head>
<body class="__BODY_CLASS__">
  <main class="screen">
    <div class="statusbar" aria-hidden="true">
      <div id="clock">9:41</div>
      <div class="icons">
        <div class="bars"><span></span><span></span><span></span><span></span></div>
        <div>Wi-Fi</div>
        <div class="battery">100%</div>
      </div>
    </div>
    <div class="island" aria-hidden="true"></div>
    <section class="home-head">
      <div>
        <div class="home-title">Ouroboros Home</div>
        <div id="generated" class="home-sub">loading...</div>
      </div>
      <div class="live-pill"><span id="statusDot" class="dot"></span><span id="level">SYNC</span></div>
    </section>
    <section class="grid">
      <article class="tile wide">
        <div class="tile-label">Today</div>
        <div id="headline" class="tile-value">接続中</div>
        <div id="quickline" class="tile-sub">status を取得しています</div>
        <div class="mini-row">
          <div class="mini"><b id="trade">-</b><span>Trade</span></div>
          <div class="mini"><b id="runner">-</b><span>Runner</span></div>
          <div class="mini"><b id="drift">-</b><span>Drift</span></div>
        </div>
      </article>
      <article class="tile half">
        <div class="tile-label">Daily Goal</div>
        <div id="goal" class="tile-value">-</div>
        <div id="goalDetail" class="tile-sub">-</div>
      </article>
      <article class="tile half">
        <div class="tile-label">Balance</div>
        <div id="balance" class="tile-value">-</div>
        <div id="balanceDetail" class="tile-sub">-</div>
      </article>
      <article class="tile half">
        <div class="tile-label">Latest</div>
        <div id="latest" class="tile-value">-</div>
        <div id="latestDetail" class="tile-sub">-</div>
      </article>
      <article class="tile half">
        <div class="tile-label">Week</div>
        <div id="weekly" class="tile-value">-</div>
        <div id="weeklyDetail" class="tile-sub">-</div>
      </article>
      <article class="tile wide">
        <div class="tile-label">Reflection</div>
        <div id="reflection" class="tile-value">-</div>
        <div id="reflectionDetail" class="tile-sub">-</div>
      </article>
      <article class="tile wide">
        <div class="tile-label">Warnings</div>
        <div id="warnings" class="warn-list"></div>
      </article>
    </section>
    <nav class="dock" aria-label="Ouroboros Home Dock">
      <a href="__WIDGET_HOME_HREF__"><span class="dock-icon">O</span><span>Home</span></a>
      <a href="__WIDGET_APP_HREF__"><span class="dock-icon">W</span><span>Widget</span></a>
      <a href="__REFLECTION_HREF__"><span class="dock-icon">R</span><span>Reflect</span></a>
      <a href="__DASHBOARD_HREF__"><span class="dock-icon">D</span><span>Dash</span></a>
    </nav>
    <div class="home-indicator" aria-hidden="true"></div>
  </main>
  <script>
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token") || "";
    const suffix = token ? ("?token=" + encodeURIComponent(token)) : "";
    const manifest = document.createElement("link");
    manifest.rel = "manifest";
    manifest.href = "/widget-home-manifest.json" + suffix;
    document.head.appendChild(manifest);
    if ("serviceWorker" in navigator) {
      window.addEventListener("load", () => {
        if (!document.body.classList.contains("native-shell")) {
          navigator.serviceWorker.register("/widget-home-sw.js" + suffix).catch(() => undefined);
        }
      });
    }
    const $ = (id) => document.getElementById(id);
    const STAGE = { LIVE: "本番", CANARY: "カナリア", PAPER: "ペーパー", SHADOW: "影" };
    const DRIFT = { NORMAL: "正常", INSUFFICIENT: "不足", ALERT: "警戒", PAUSED: "停止" };
    function key(v) { return String(v || "").trim().toUpperCase(); }
    function jpy(v, sign=false) {
      const n = Number(v);
      if (!Number.isFinite(n)) return "-";
      const s = Math.abs(n).toLocaleString("ja-JP", { maximumFractionDigits: 0 });
      if (!sign) return (n < 0 ? "-" : "") + s;
      return n > 0 ? "+" + s : n < 0 ? "-" + s : s;
    }
    function compact(v, sign=false) {
      const n = Number(v);
      if (!Number.isFinite(n)) return "-";
      const a = Math.abs(n);
      const s = a >= 10000 ? (a / 10000).toFixed(1).replace(/\\.0$/, "") + "万" : a.toLocaleString("ja-JP", { maximumFractionDigits: 0 });
      if (!sign) return (n < 0 ? "-" : "") + s;
      return n > 0 ? "+" + s : n < 0 ? "-" + s : s;
    }
    function shortTime(v) {
      const s = String(v || "").trim();
      return s ? s.replace(/^\\d{4}-\\d{2}-\\d{2}\\s+/, "") : "-";
    }
    function setTone(level) {
      const k = key(level);
      $("statusDot").className = "dot " + (k === "OK" ? "ok" : k === "ALERT" ? "alert" : "");
      $("level").textContent = k === "OK" ? "LIVE" : k === "ALERT" ? "CHECK" : "WATCH";
    }
    function latestText(t) {
      if (!t || !t.available) return ["取引なし", "-"];
      if (t.kind === "EXIT") return [`${String(t.reason || "EXIT")}`, `${shortTime(t.time)} / ${jpy(t.pnl_jpy, true)}円`];
      return [`${String(t.reason || "ENTRY")}`, `${shortTime(t.time)} / ${String(t.side || "-")}`];
    }
    function reflectionText(r) {
      if (!r || !r.available) return ["-", "終業反省待ち"];
      const next = Array.isArray(r.next_actions) && r.next_actions.length ? String(r.next_actions[0]) : "次の一手を確認";
      const hint = [r.shadow_filter_hint, r.shadow_htf_hint, r.shadow_exit_hint].filter(Boolean).join(" / ");
      return [r.day8 || "Reflection", `${next}${hint ? " / " + hint : ""}`];
    }
    async function refresh() {
      $("clock").textContent = new Date().toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
      try {
        const res = await fetch("/widget-status.json" + suffix, { cache: "no-store" });
        const data = await res.json();
        const drift = data.drift || {};
        const goal = data.goal || {};
        const balance = data.balance || {};
        const weekly = data.weekly || {};
        setTone(data.status_level);
        $("generated").textContent = `${data.generated_at || "-"}${data.offline_mode ? " / offline" : ""}`;
        $("headline").textContent = `${STAGE[key(data.effective_stage)] || data.effective_stage || "-"} / ${data.trade_enabled ? "取引ON" : "取引OFF"}`;
        $("quickline").textContent = `${DRIFT[key(drift.status)] || drift.status || "-"} / ${drift.resume_ready ? "復帰OK" : "復帰待ち"} / ${data.runner_alive ? "bot稼働" : "bot停止"}`;
        $("trade").textContent = data.trade_enabled ? "ON" : "OFF";
        $("runner").textContent = data.runner_alive ? "稼働" : "停止";
        $("drift").textContent = `${DRIFT[key(drift.status)] || "-"} ${drift.remaining_samples ?? "-"}`;
        $("goal").textContent = goal.goal_jpy == null ? "-" : `${compact(goal.pnl_jpy, true)} / ${compact(goal.goal_jpy)}`;
        $("goalDetail").textContent = goal.achieved ? "達成済み" : `残り ${jpy(goal.remaining_jpy)}円`;
        $("balance").textContent = balance.available ? `¥${compact(balance.jpy)}` : "-";
        $("balanceDetail").textContent = balance.available ? String(balance.label || "残高") : "取得待ち";
        const latest = latestText(data.latest_trade);
        $("latest").textContent = latest[0];
        $("latestDetail").textContent = latest[1];
        $("weekly").textContent = weekly.available ? `${jpy(weekly.pnl_jpy_sum, true)}円` : "-";
        $("weeklyDetail").textContent = weekly.available ? `WR ${Number(weekly.win_rate_pct || 0).toFixed(1)}% / ${weekly.shadow_decision || "-"}` : "週次待ち";
        const refl = reflectionText(data.latest_reflection);
        $("reflection").textContent = refl[0];
        $("reflectionDetail").textContent = refl[1];
        const warnings = Array.isArray(data.warnings) && data.warnings.length ? data.warnings.slice(0, 4) : ["確認事項はありません"];
        $("warnings").innerHTML = warnings.map((w) => `<div class="warn-item">${String(w).replace(/[<>&]/g, (c) => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c]))}</div>`).join("");
      } catch (err) {
        setTone("ALERT");
        $("headline").textContent = "取得エラー";
        $("quickline").textContent = String(err);
        $("warnings").innerHTML = '<div class="warn-item">widget-status.json を確認してください</div>';
      }
    }
    refresh();
    setInterval(refresh, 60000);
  </script>
</body>
</html>"""
    return (
        page.replace("__WIDGET_HOME_HREF__", f"/widget-home{app_suffix}")
        .replace("__WIDGET_APP_HREF__", widget_app_href)
        .replace("__REFLECTION_HREF__", reflection_href)
        .replace("__DASHBOARD_HREF__", dashboard_href)
        .replace("__BODY_CLASS__", "native-shell" if native_shell else "")
    )


def _status_page_html(token: str = "", app_mode: bool = False) -> str:
    app_suffix = _widget_app_suffix(token)
    widget_app_href = f"/widget-app{app_suffix}"
    reflection_href = f"/daily-reflection{app_suffix}"
    dashboard_href = "/dashboard"
    app_mode_class = " app-mode" if app_mode else ""
    page = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0f172a">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <meta name="apple-mobile-web-app-title" content="Ouroboros">
  <link rel="icon" href="/widget-app-icon.svg">
  <link rel="apple-touch-icon" href="/widget-app-icon.svg">
  <title>Ouroboros Widget</title>
  <style>
    :root {
      --bg:
        radial-gradient(circle at top right, rgba(245, 158, 11, 0.18), transparent 28%),
        radial-gradient(circle at top left, rgba(14, 165, 233, 0.12), transparent 24%),
        linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%);
      --card: rgba(255,255,255,0.82);
      --border: rgba(100,116,139,0.24);
      --text: #0f172a;
      --muted: #475569;
      --ok: #059669;
      --warn: #d97706;
      --alert: #dc2626;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Avenir Next", "Hiragino Sans", "Noto Sans JP", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    body.app-mode {
      --card: rgba(15, 23, 42, 0.58);
      --border: rgba(255,255,255,0.12);
      --text: #f8fafc;
      --muted: rgba(226, 232, 240, 0.82);
      --ok: #34d399;
      --warn: #fbbf24;
      --alert: #f87171;
      background:
        radial-gradient(150% 100% at 22% 0%, rgba(67, 89, 173, 0.58) 0%, rgba(39, 49, 93, 0.38) 30%, transparent 60%),
        radial-gradient(140% 110% at 82% 8%, rgba(255, 135, 88, 0.30) 0%, rgba(255, 135, 88, 0.08) 28%, transparent 58%),
        linear-gradient(180deg, #16203a 0%, #0c1222 42%, #060911 100%);
    }
    .ios-statusbar {
      display: none;
    }
    .dynamic-island {
      display: none;
    }
    body.app-mode .ios-statusbar {
      position: sticky;
      top: 0;
      z-index: 40;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: max(8px, env(safe-area-inset-top)) 18px 0;
      color: rgba(248, 250, 252, 0.96);
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.01em;
      text-shadow: 0 1px 2px rgba(0,0,0,0.35);
    }
    body.app-mode .status-icons {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      opacity: 0.92;
    }
    body.app-mode .signal-bars {
      display: inline-grid;
      grid-template-columns: repeat(4, 3px);
      align-items: end;
      gap: 2px;
      height: 12px;
    }
    body.app-mode .signal-bars span {
      display: block;
      width: 3px;
      border-radius: 999px;
      background: rgba(248, 250, 252, 0.96);
    }
    body.app-mode .signal-bars span:nth-child(1) { height: 5px; opacity: 0.72; }
    body.app-mode .signal-bars span:nth-child(2) { height: 7px; opacity: 0.82; }
    body.app-mode .signal-bars span:nth-child(3) { height: 9px; opacity: 0.9; }
    body.app-mode .signal-bars span:nth-child(4) { height: 11px; }
    body.app-mode .battery-pill {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 7px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.15);
      font-size: 11px;
    }
    body.app-mode .dynamic-island {
      position: sticky;
      top: calc(max(8px, env(safe-area-inset-top)) + 6px);
      z-index: 39;
      display: flex;
      justify-content: center;
      pointer-events: none;
      margin-top: -12px;
      margin-bottom: 8px;
    }
    body.app-mode .dynamic-island::before {
      content: "";
      width: 126px;
      height: 36px;
      border-radius: 24px;
      background: rgba(0,0,0,0.92);
      box-shadow: 0 8px 18px rgba(0,0,0,0.38);
      display: block;
    }
    .shell {
      max-width: 860px;
      margin: 0 auto;
      padding: 20px 16px 32px;
    }
    body.app-mode .shell {
      max-width: 560px;
      padding: 8px 14px 104px;
    }
    .hero {
      display: grid;
      gap: 10px;
      margin-bottom: 14px;
      padding: 18px;
      border: 1px solid var(--border);
      border-radius: 24px;
      background: rgba(255,255,255,0.8);
      backdrop-filter: blur(12px);
      box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
    }
    body.app-mode .hero {
      background: linear-gradient(180deg, rgba(20, 28, 52, 0.84), rgba(11, 17, 34, 0.74));
      border: 1px solid rgba(255,255,255,0.12);
      box-shadow: 0 18px 44px rgba(0,0,0,0.26), inset 0 1px 0 rgba(255,255,255,0.08);
    }
    .hero-top {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }
    .appnav {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 2px;
    }
    .appnav a {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(15, 23, 42, 0.05);
      border: 1px solid rgba(100,116,139,0.16);
      color: var(--text);
      text-decoration: none;
      font-size: 12px;
      font-weight: 700;
    }
    body.app-mode .appnav a {
      background: rgba(255,255,255,0.10);
      border-color: rgba(255,255,255,0.12);
      color: rgba(248,250,252,0.92);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);
    }
    .reflection-summary {
      display: none;
    }
    body.app-mode .reflection-summary {
      display: grid;
      gap: 8px;
      margin: 0 0 12px;
      padding: 14px 14px 12px;
      border: 1px solid var(--border);
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(15, 23, 42, 0.68), rgba(30, 41, 59, 0.56));
      backdrop-filter: blur(10px);
      box-shadow: 0 18px 36px rgba(0,0,0,0.22);
    }
    .reflection-summary-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }
    .reflection-summary-title {
      font-size: 15px;
      font-weight: 800;
    }
    .reflection-summary-meta {
      color: var(--muted);
      font-size: 12px;
    }
    .reflection-summary-next {
      font-size: 18px;
      font-weight: 800;
      line-height: 1.35;
    }
    .reflection-summary-notes {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.65;
    }
    .reflection-summary-link {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      width: fit-content;
      color: #2563eb;
      text-decoration: none;
      font-size: 12px;
      font-weight: 700;
    }
    body.app-mode .reflection-summary-link {
      color: #f8c89a;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      border-radius: 999px;
      font-weight: 700;
      width: fit-content;
      background: rgba(15, 23, 42, 0.08);
    }
    .badge.ok { color: var(--ok); background: rgba(5, 150, 105, 0.10); }
    .badge.warn { color: var(--warn); background: rgba(217, 119, 6, 0.10); }
    .badge.alert { color: var(--alert); background: rgba(220, 38, 38, 0.10); }
    .stagepill {
      display: inline-flex;
      align-items: center;
      padding: 10px 14px;
      border-radius: 999px;
      font-weight: 700;
      background: rgba(15, 23, 42, 0.06);
      color: var(--text);
    }
    body.app-mode .badge,
    body.app-mode .stagepill {
      background: rgba(255,255,255,0.10);
      border: 1px solid rgba(255,255,255,0.12);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);
    }
    .headline {
      font-size: clamp(24px, 4vw, 34px);
      font-weight: 800;
      line-height: 1.12;
    }
    body.app-mode .headline {
      letter-spacing: -0.03em;
      text-shadow: 0 10px 28px rgba(0,0,0,0.26);
    }
    .quickline {
      color: var(--text);
      font-size: 14px;
      font-weight: 600;
      opacity: 0.88;
    }
    .meta {
      color: var(--muted);
      font-size: 14px;
    }
    .apphint {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
    }
    .apphint a {
      color: #2563eb;
      text-decoration: none;
      font-weight: 700;
    }
    .appsteps {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 4px;
      color: var(--muted);
      font-size: 11px;
    }
    .appstep {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(15, 23, 42, 0.05);
      border: 1px solid rgba(100,116,139,0.16);
    }
    body.app-mode .appstep {
      background: rgba(255,255,255,0.08);
      border-color: rgba(255,255,255,0.10);
    }
    .home-title {
      display: none;
    }
    body.app-mode .home-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin: 4px 4px 10px;
      color: rgba(248,250,252,0.94);
    }
    body.app-mode .home-title-label {
      font-size: 16px;
      font-weight: 800;
      letter-spacing: -0.02em;
    }
    body.app-mode .home-title-sub {
      font-size: 11px;
      opacity: 0.72;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
      margin: 16px 0;
    }
    body.app-mode .grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin: 12px 0;
    }
    .card {
      --accent: #cbd5e1;
      --accent-bg: rgba(255,255,255,0.82);
      position: relative;
      overflow: hidden;
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 14px;
      background: linear-gradient(180deg, rgba(255,255,255,0.94), var(--accent-bg));
      backdrop-filter: blur(10px);
    }
    body.app-mode .card {
      border-radius: 26px;
      padding: 16px 15px 15px;
      background: linear-gradient(180deg, rgba(15, 23, 42, 0.72), rgba(30, 41, 59, 0.56));
      border: 1px solid rgba(255,255,255,0.10);
      box-shadow: 0 18px 40px rgba(0,0,0,0.22), inset 0 1px 0 rgba(255,255,255,0.05);
    }
    .card::before {
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 5px;
      background: var(--accent);
    }
    body.app-mode .card::before {
      inset: auto 14px 10px 14px;
      width: auto;
      height: 3px;
      border-radius: 999px;
      opacity: 0.72;
    }
    .label {
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
      letter-spacing: 0.02em;
    }
    .value {
      font-size: 22px;
      font-weight: 800;
      line-height: 1.1;
    }
    .value.small {
      font-size: 18px;
    }
    .sub {
      color: var(--muted);
      font-size: 13px;
      margin-top: 6px;
    }
    .warnbox {
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 14px;
      background: rgba(255,255,255,0.72);
    }
    body.app-mode .warnbox {
      background: rgba(15, 23, 42, 0.58);
      border-color: rgba(255,255,255,0.12);
      box-shadow: 0 18px 36px rgba(0,0,0,0.20);
    }
    .warnbox h2 {
      margin: 0 0 10px;
      font-size: 15px;
    }
    .warnbox ul {
      margin: 0;
      padding-left: 0;
      list-style: none;
      color: var(--muted);
      display: grid;
      gap: 8px;
    }
    .warnbox li {
      padding: 10px 12px;
      border-radius: 12px;
      background: rgba(248, 250, 252, 0.9);
    }
    .warnbox li.warn {
      background: rgba(255, 247, 237, 0.96);
      color: #9a3412;
      border-left: 4px solid #f59e0b;
    }
    .warnbox li.alert {
      background: rgba(254, 226, 226, 0.98);
      color: #991b1b;
      border-left: 4px solid #dc2626;
    }
    .warnbox li.note {
      background: rgba(240, 253, 244, 0.96);
      color: #065f46;
      border-left: 4px solid #10b981;
    }
    .error {
      color: var(--alert);
      font-weight: 700;
      margin-top: 16px;
    }
    .bottomnav {
      display: none;
    }
    body.app-mode .bottomnav {
      position: fixed;
      left: 50%;
      bottom: max(12px, env(safe-area-inset-bottom));
      transform: translateX(-50%);
      z-index: 30;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      width: min(92vw, 520px);
      padding: 10px;
      border: 1px solid rgba(100,116,139,0.18);
      border-radius: 28px;
      background: rgba(255,255,255,0.14);
      backdrop-filter: blur(22px) saturate(160%);
      box-shadow: 0 18px 40px rgba(15, 23, 42, 0.18);
    }
    .bottomnav a {
      display: inline-flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 4px;
      min-height: 52px;
      border-radius: 14px;
      color: rgba(248, 250, 252, 0.84);
      text-decoration: none;
      font-size: 11px;
      font-weight: 700;
    }
    .bottomnav a.active {
      background: rgba(255,255,255,0.16);
      color: #ffffff;
    }
    .bottomnav .emoji {
      font-size: 15px;
      line-height: 1;
    }
    .home-indicator {
      display: none;
    }
    body.app-mode .home-indicator {
      position: fixed;
      left: 50%;
      bottom: 4px;
      transform: translateX(-50%);
      z-index: 28;
      display: block;
      width: 134px;
      height: 5px;
      border-radius: 999px;
      background: rgba(255,255,255,0.48);
    }
    @media (max-width: 640px) {
      .shell {
        padding: 14px 12px 24px;
      }
      .hero {
        padding: 16px;
        border-radius: 20px;
      }
      .headline {
        font-size: 24px;
      }
      .grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }
      .card {
        padding: 12px;
        border-radius: 16px;
      }
      .value {
        font-size: 19px;
      }
      .value.small {
        font-size: 16px;
      }
      .sub {
        font-size: 12px;
      }
      body.app-mode .bottomnav {
        width: min(94vw, 520px);
        gap: 6px;
        padding: 8px;
      }
      .bottomnav a {
        min-height: 48px;
      }
      body.app-mode .card {
        border-radius: 24px;
      }
    }
  </style>
</head>
<body class="__APP_MODE_CLASS__">
  <div class="ios-statusbar" aria-hidden="true">
    <div id="statusbar_time">9:41</div>
    <div class="status-icons">
      <div class="signal-bars"><span></span><span></span><span></span><span></span></div>
      <div>Wi-Fi</div>
      <div class="battery-pill">100%</div>
    </div>
  </div>
  <div class="dynamic-island" aria-hidden="true"></div>
  <div class="shell">
    <div class="hero">
      <div class="hero-top">
        <div id="badge" class="badge">読込中</div>
        <div id="stagepill" class="stagepill">運用 -</div>
      </div>
      <div class="appnav">
        <a href="__WIDGET_APP_HREF__">Overview</a>
        <a href="__REFLECTION_HREF__">Reflection</a>
        <a href="__DASHBOARD_HREF__">Dashboard</a>
      </div>
      <div id="headline" class="headline">接続中...</div>
      <div id="quickline" class="quickline">状況を取得しています...</div>
      <div id="meta" class="meta">接続中...</div>
      <div class="apphint">ホーム画面に置く場合は <a href="__WIDGET_APP_HREF__">/widget-app</a> を開いて「ホーム画面に追加」を使います。</div>
      <div class="appsteps">
        <div class="appstep">1. <b>/widget-app</b> を開く</div>
        <div class="appstep">2. 共有メニュー</div>
        <div class="appstep">3. ホーム画面に追加</div>
      </div>
    </div>
    <div class="reflection-summary">
      <div class="reflection-summary-top">
        <div class="reflection-summary-title">Reflection Snapshot</div>
        <div id="reflection_summary_meta" class="reflection-summary-meta">終業反省を確認中...</div>
      </div>
      <div id="reflection_summary_next" class="reflection-summary-next">反省の要点を読み込み中...</div>
      <div id="reflection_summary_notes" class="reflection-summary-notes">Reflection に移動しなくても、その日の要点をここで確認できます。</div>
      <a class="reflection-summary-link" href="__REFLECTION_HREF__">Reflection を開く</a>
    </div>
    <div class="home-title">
      <div>
        <div class="home-title-label">Home Widgets</div>
        <div class="home-title-sub">Ouroboros monitor stack</div>
      </div>
    </div>
    <div class="grid">
      <div id="card-stage" class="card">
        <div class="label">運用段階</div>
        <div id="stage" class="value">-</div>
        <div id="mode" class="sub">-</div>
      </div>
      <div id="card-trade" class="card">
        <div class="label">稼働状況</div>
        <div id="trade" class="value">-</div>
        <div id="runner" class="sub">bot -</div>
      </div>
      <div id="card-risk" class="card">
        <div class="label">停止系</div>
        <div id="risk" class="value">-</div>
        <div id="streak" class="sub">-</div>
      </div>
      <div id="card-drift" class="card">
        <div class="label">ドリフト</div>
        <div id="drift_status" class="value small">-</div>
        <div id="drift_reason" class="sub">-</div>
      </div>
      <div id="card-samples" class="card">
        <div class="label">復帰条件</div>
        <div id="samples" class="value">-</div>
        <div id="resume" class="sub">-</div>
      </div>
      <div id="card-goal" class="card">
        <div class="label">日次目標</div>
        <div id="goal" class="value small">-</div>
        <div id="goal_detail" class="sub">-</div>
      </div>
      <div id="card-balance" class="card">
        <div class="label">残高</div>
        <div id="balance" class="value small">-</div>
        <div id="balance_detail" class="sub">-</div>
      </div>
      <div id="card-freshness" class="card">
        <div class="label">鮮度</div>
        <div id="freshness" class="value small">-</div>
        <div id="freshness_detail" class="sub">-</div>
      </div>
      <div id="card-latest" class="card">
        <div class="label">直近トレード</div>
        <div id="latest_trade" class="value small">-</div>
        <div id="latest_trade_detail" class="sub">-</div>
      </div>
      <div id="card-weekly" class="card">
        <div class="label">今週累計</div>
        <div id="weekly" class="value small">-</div>
        <div id="weekly_detail" class="sub">-</div>
      </div>
      <div id="card-shadow-day" class="card">
        <div class="label">影日次</div>
        <div id="shadow_day" class="value small">-</div>
        <div id="shadow_day_detail" class="sub">-</div>
      </div>
      <div id="card-reflection" class="card">
        <div class="label">終業反省</div>
        <div id="reflection" class="value small">-</div>
        <div id="reflection_detail" class="sub">-</div>
      </div>
      <div id="card-version" class="card">
        <div class="label">バージョン</div>
        <div id="version_info" class="value small">-</div>
        <div id="version_detail" class="sub">-</div>
      </div>
      <div id="card-ai" class="card">
        <div class="label">AI / 日次</div>
        <div id="ai" class="value">-</div>
        <div id="limit" class="sub">-</div>
      </div>
    </div>
    <div class="warnbox">
      <h2>注意ポイント</h2>
      <ul id="warnings"></ul>
    </div>
    <div id="error" class="error"></div>
  </div>
  <nav class="bottomnav" aria-label="Widget App Navigation">
    <a class="active" href="__WIDGET_APP_HREF__"><span class="emoji">🏠</span><span>Overview</span></a>
    <a href="__REFLECTION_HREF__"><span class="emoji">🪞</span><span>Reflection</span></a>
    <a href="__DASHBOARD_HREF__"><span class="emoji">📊</span><span>Dashboard</span></a>
  </nav>
  <div class="home-indicator" aria-hidden="true"></div>
  <script>
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token") || "";
    const suffix = token ? ("?token=" + encodeURIComponent(token)) : "";
    const manifestHref = "/widget-app-manifest.json" + suffix;
    const manifestLink = document.createElement("link");
    manifestLink.rel = "manifest";
    manifestLink.href = manifestHref;
    document.head.appendChild(manifestLink);
    if ("serviceWorker" in navigator) {
      window.addEventListener("load", () => {
        navigator.serviceWorker.register("/widget-app-sw.js" + suffix).catch(() => undefined);
      });
    }
    const badgeEl = document.getElementById("badge");
    const stagePillEl = document.getElementById("stagepill");
    const headlineEl = document.getElementById("headline");
    const quicklineEl = document.getElementById("quickline");
    const metaEl = document.getElementById("meta");
    const errorEl = document.getElementById("error");
    const statusbarTimeEl = document.getElementById("statusbar_time");
    const reflectionSummaryMetaEl = document.getElementById("reflection_summary_meta");
    const reflectionSummaryNextEl = document.getElementById("reflection_summary_next");
    const reflectionSummaryNotesEl = document.getElementById("reflection_summary_notes");
    const LEVEL_LABELS = { OK: "正常", WARN: "注意", ALERT: "警戒" };
    const STAGE_LABELS = { LIVE: "本番", CANARY: "カナリア", PAPER: "ペーパー", SHADOW: "影運用" };
    const MODE_LABELS = { LIVE: "本番モード", CANARY: "カナリア運用", PAPER: "ペーパーモード", SHADOW: "影運用" };
    const DRIFT_LABELS = { NORMAL: "正常", INSUFFICIENT: "サンプル不足", ALERT: "警戒", PAUSED: "停止中" };
    const TONES = {
      ok: { accent: "#059669", bg: "rgba(209, 250, 229, 0.75)" },
      warn: { accent: "#d97706", bg: "rgba(254, 243, 199, 0.88)" },
      alert: { accent: "#dc2626", bg: "rgba(254, 226, 226, 0.88)" },
      info: { accent: "#2563eb", bg: "rgba(219, 234, 254, 0.84)" },
      neutral: { accent: "#64748b", bg: "rgba(226, 232, 240, 0.86)" },
      teal: { accent: "#0f766e", bg: "rgba(204, 251, 241, 0.82)" }
    };
    function keyOf(value) {
      return String(value || "").trim().toUpperCase();
    }
    function levelLabel(value) {
      return LEVEL_LABELS[keyOf(value)] || String(value || "-");
    }
    function stageLabel(value) {
      return STAGE_LABELS[keyOf(value)] || String(value || "-");
    }
    function modeLabel(value) {
      return MODE_LABELS[keyOf(value)] || String(value || "-");
    }
    function driftLabel(value) {
      return DRIFT_LABELS[keyOf(value)] || String(value || "-");
    }
    function driftOutlook(drift) {
      return (drift && drift.resume_outlook) ? drift.resume_outlook : {};
    }
    function onOffLabel(flag) {
      return flag ? "ON" : "OFF";
    }
    function runnerLabel(flag) {
      return flag ? "稼働中" : "停止中";
    }
    function shortTimestamp(value) {
      const s = String(value || "").trim();
      return s ? s.replace(/^\\d{4}-\\d{2}-\\d{2}\\s+/, "") : "-";
    }
    function currentClockText() {
      const now = new Date();
      return now.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
    }
    function translateReason(value) {
      const s = String(value || "").trim();
      if (!s) return "理由なし";
      let m = s.match(/^recent_closed<(\\d+) \\((\\d+)\\)$/);
      if (m) return "直近約定数が不足 (" + m[2] + "/" + m[1] + ")";
      return s;
    }
    function translateWarning(value) {
      const s = String(value || "").trim();
      if (!s) return "-";
      if (s === "offline_mode=ON") return "オフライン表示中";
      let m = s.match(/^drift gate remaining=(\\d+)$/);
      if (m) return "ドリフト復帰まで残り " + m[1] + " 件";
      m = s.match(/^freshness=ALERT (.+)$/);
      if (m) return "鮮度低下: " + m[1];
      if (s === "streak_stop=ON") return "連敗停止が作動中";
      if (s === "risk_stop=ON") return "リスク停止が作動中";
      if (s === "trade_enabled=0") return "取引が無効";
      if (s === "runner=STOPPED" || s === "runner=OFF") return "bot が停止中";
      return s;
    }
    function warningTone(value) {
      const s = String(value || "").trim();
      if (s === "risk_stop=ON" || s.startsWith("freshness=ALERT")) return "alert";
      return "warn";
    }
    function stopSummary(data) {
      if (data.risk_stop) return "リスク停止中";
      if (data.streak_stop) return "連敗停止中";
      return "通常";
    }
    function stageTone(value) {
      const key = keyOf(value);
      if (key === "LIVE") return "info";
      if (key === "CANARY") return "warn";
      if (key === "SHADOW") return "teal";
      return "neutral";
    }
    function driftTone(value) {
      const key = keyOf(value);
      if (key === "NORMAL") return "ok";
      if (key === "INSUFFICIENT" || key === "ALERT") return "warn";
      return "neutral";
    }
    function tradeTone(data) {
      if (data.trade_enabled && data.runner_alive) return "ok";
      if (!data.trade_enabled || !data.runner_alive) return "warn";
      return "neutral";
    }
    function setCardTone(cardId, valueId, toneKey) {
      const card = document.getElementById(cardId);
      if (!card) return;
      const tone = TONES[toneKey] || TONES.neutral;
      card.style.setProperty("--accent", tone.accent);
      card.style.setProperty("--accent-bg", tone.bg);
      if (valueId) {
        const valueEl = document.getElementById(valueId);
        if (valueEl) valueEl.style.color = tone.accent;
      }
    }
    function buildHeadline(data, drift) {
      return stageLabel(data.effective_stage || "-") + " / 取引 " + onOffLabel(data.trade_enabled) + " / " + driftLabel(drift.status || "-");
    }
    function buildQuickline(data, drift) {
      const outlook = driftOutlook(drift);
      return "bot " + runnerLabel(data.runner_alive) + " ・ " + String(outlook.short || ("残り " + String(drift.remaining_samples ?? "-"))) + " ・ " + stopSummary(data);
    }
    function formatJpy(value, digits = 0, withSign = false) {
      const num = Number(value);
      if (!Number.isFinite(num)) return "-";
      const text = num.toLocaleString("ja-JP", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
      if (withSign) {
        if (num > 0) return "+" + text;
        if (num < 0) return text;
      }
      return text;
    }
    function goalValue(goal) {
      if (!goal || goal.goal_jpy == null) return "-";
      return formatJpy(goal.pnl_jpy, 0, true) + " / " + formatJpy(goal.goal_jpy, 0, false);
    }
    function goalDetail(goal) {
      if (!goal || goal.goal_jpy == null) return "-";
      if (goal.achieved) return "達成済み";
      return "残り " + formatJpy(goal.remaining_jpy, 0, false);
    }
    function balanceValue(balance) {
      if (!balance || !balance.available) return "-";
      return "¥" + formatJpy(balance.jpy, 0, false);
    }
    function balanceDetail(balance) {
      if (!balance || !balance.available) return "取得待ち";
      return String(balance.label || "残高");
    }
    function freshnessValue(freshness) {
      if (!freshness || !freshness.status) return "-";
      if (freshness.status === "OK") return "正常";
      if (freshness.status === "WARN") return "注意";
      return "警戒";
    }
    function freshnessDetail(freshness) {
      if (!freshness) return "-";
      return String(freshness.summary || freshness.age_text || "-");
    }
    function freshnessTone(freshness) {
      if (!freshness || !freshness.status) return "neutral";
      if (freshness.status === "OK") return "ok";
      if (freshness.status === "WARN") return "warn";
      return "alert";
    }
    function latestTradeReasonLabel(reason) {
      const s = String(reason || "").trim().toUpperCase();
      if (!s) return "取引なし";
      if (s === "TP") return "利確";
      if (s === "SL") return "損切";
      if (s === "TIMEOUT") return "時間切れ";
      if (s === "EOD") return "EOD";
      if (s === "PARTIAL_TP") return "分割利確";
      if (s === "ENTRY") return "新規";
      return s;
    }
    function latestTradeValue(trade) {
      if (!trade || !trade.available) return "取引なし";
      if (trade.kind === "EXIT") {
        return latestTradeReasonLabel(trade.reason) + " " + formatJpy(trade.pnl_jpy, 0, true);
      }
      return latestTradeReasonLabel(trade.reason) + " " + String(trade.side || "-");
    }
    function latestTradeDetail(trade) {
      if (!trade || !trade.available) return "-";
      const time = shortTimestamp(trade.time || "-");
      if (trade.kind === "EXIT") {
        const ret = Number.isFinite(Number(trade.ret_pct)) ? (" / " + Number(trade.ret_pct).toFixed(2) + "%") : "";
        return time + " / " + String(trade.side || "-") + ret;
      }
      return time + " / " + String(trade.side || "-") + " / " + formatJpy(trade.entry_price, 0, false);
    }
    function latestTradeTone(trade) {
      if (!trade || !trade.available) return "neutral";
      if (trade.kind === "EXIT") {
        const pnl = Number(trade.pnl_jpy);
        if (Number.isFinite(pnl) && pnl > 0) return "ok";
        if (Number.isFinite(pnl) && pnl < 0) return "alert";
        return "warn";
      }
      return "info";
    }
    function weeklyValue(weekly) {
      if (!weekly || !weekly.available) return "-";
      return formatJpy(weekly.pnl_jpy_sum, 0, true) + " / " + Number(weekly.win_rate_pct || 0).toFixed(0) + "%";
    }
    function weeklyHint(weekly) {
      if (!weekly) return "";
      const decision = String(weekly.shadow_decision || "").trim();
      const hint = String(weekly.pattern_hint || "").trim();
      if (decision && hint) return decision + " / " + hint;
      return decision || hint || "";
    }
    function weeklyDetail(weekly) {
      if (!weekly || !weekly.available) return "今週約定なし";
      const hint = weeklyHint(weekly);
      if (hint) return "close " + String(weekly.closed_n || 0) + " / " + hint;
      return "close " + String(weekly.closed_n || 0) + " / " + String(weekly.start_day8 || "-") + "-";
    }
    function weeklyTone(weekly) {
      if (!weekly || !weekly.available) return "neutral";
      const pnl = Number(weekly.pnl_jpy_sum);
      if (Number.isFinite(pnl) && pnl > 0) return "ok";
      if (Number.isFinite(pnl) && pnl < 0) return "alert";
      return "warn";
    }
    function shadowDayValue(shadow) {
      if (!shadow || !shadow.available) return "データなし";
      return formatJpy(shadow.pnl_jpy_sum, 0, true) + " / " + String(shadow.closed_n || 0) + "件";
    }
    function shadowDayDetail(shadow) {
      if (!shadow || !shadow.available) return "影運用の当日約定なし";
      return "勝率 " + Number(shadow.win_rate_pct || 0).toFixed(0) + "% / tech " + String(shadow.exit_technical_n || 0) + " / weak " + String(shadow.weak_progress_exit_n || 0) + " / pr " + String(shadow.progress_reversal_exit_n || 0) + " / ntp " + String(shadow.near_tp_giveback_exit_n || 0) + " / pto " + String(shadow.progress_timeout_n || 0) + " / nf " + String(shadow.no_follow_through_exit_n || 0) + " / htf60 " + String(shadow.observe_ai_block_htf60_countertrend_n || 0) + " / conflict " + String(shadow.observe_ai_block_htf15_60_conflict_n || 0) + " / timeout " + String(shadow.plain_timeout_n ?? shadow.timeout_n ?? 0) + " / " + String(shadow.last_result || "-");
    }
    function shadowDayTone(shadow) {
      if (!shadow || !shadow.available) return "neutral";
      const pnl = Number(shadow.pnl_jpy_sum);
      if (Number.isFinite(pnl) && pnl > 0) return "ok";
      if (Number.isFinite(pnl) && pnl < 0) return "alert";
      return "warn";
    }
    function reflectionValue(reflection) {
      if (!reflection || !reflection.available) return "未生成";
      return String(reflection.goal_achieved ? "達成" : "未達");
    }
    function reflectionDetail(reflection) {
      if (!reflection || !reflection.available) return "まだ終業反省なし";
      const adjust = [];
      if (String(reflection.shadow_filter_hint || "").trim()) adjust.push("filter " + String(reflection.shadow_filter_hint || "").trim());
      if (String(reflection.shadow_htf_hint || "").trim()) adjust.push("htf " + String(reflection.shadow_htf_hint || "").trim());
      if (String(reflection.shadow_exit_hint || "").trim()) adjust.push("exit " + String(reflection.shadow_exit_hint || "").trim());
      if (adjust.length) return String(reflection.day8 || "-") + " / " + adjust.join(" / ");
      return String(reflection.day8 || "-") + " / " + String((reflection.next_actions || [])[0] || "詳細を開く");
    }
    function reflectionTone(reflection) {
      if (!reflection || !reflection.available) return "neutral";
      return reflection.goal_achieved ? "ok" : "warn";
    }
    function reflectionSummaryMeta(reflection) {
      if (!reflection || !reflection.available) return "終業反省なし";
      const conf = String(reflection.sample_confidence || "").trim().toLowerCase();
      const confLabel = conf === "high" ? "信頼度 高" : (conf === "medium" ? "信頼度 中" : (conf === "low" ? "信頼度 低" : "信頼度 -"));
      return String(reflection.day8 || "-") + " / " + confLabel + " / " + (reflection.goal_achieved ? "目標達成" : "目標未達");
    }
    function reflectionSummaryNext(reflection) {
      if (!reflection || !reflection.available) return "Reflection 未生成。まずは当日の終業反省を待ちます。";
      return String((reflection.next_actions || [])[0] || (reflection.win_notes || [])[0] || "翌日アクションなし");
    }
    function reflectionSummaryNotes(reflection) {
      if (!reflection || !reflection.available) return "オフライン時は最後に取得できた内容を表示します。";
      const notes = [];
      const adjust = reflectionDetail(reflection);
      if (adjust && adjust !== "まだ終業反省なし") notes.push(adjust);
      if ((reflection.loss_notes || []).length) notes.push("loss " + String((reflection.loss_notes || [])[0]));
      if ((reflection.win_notes || []).length) notes.push("win " + String((reflection.win_notes || [])[0]));
      return notes.slice(0, 2).join(" / ") || "Reflection 詳細を開く";
    }
    function versionValue(versions) {
      if (!versions) return "-";
      return String(versions.summary || "-");
    }
    function versionDetail(versions) {
      if (!versions) return "-";
      return String(versions.detail || "-");
    }
    function resumeOutlookValue(drift) {
      const outlook = driftOutlook(drift);
      return String(outlook.short || ("残り " + String(drift.remaining_samples ?? "-")));
    }
    function resumeOutlookDetail(drift) {
      const outlook = driftOutlook(drift);
      return String(outlook.detail || ("約定 " + String(drift.closed_n || 0) + " / " + String(drift.min_recent_closed || 0) + " ・ 復帰 " + (drift.resume_ready ? "OK" : "待機")));
    }
    function resumeOutlookTone(drift) {
      const phase = keyOf((driftOutlook(drift) || {}).phase);
      if (phase === "READY" || phase === "NORMAL") return "ok";
      if (phase === "ALERT") return "alert";
      if (phase === "UNKNOWN") return "neutral";
      return "warn";
    }
    function goalTone(goal) {
      if (!goal || goal.goal_jpy == null) return "neutral";
      return goal.achieved ? "ok" : "warn";
    }
    function balanceTone(balance) {
      if (!balance || !balance.available) return "neutral";
      return "info";
    }
    function setText(id, value) {
      const el = document.getElementById(id);
      if (el) el.textContent = String(value ?? "-");
    }
    async function refresh() {
      try {
        if (statusbarTimeEl) statusbarTimeEl.textContent = currentClockText();
        const res = await fetch("/widget-status.json" + suffix, { cache: "no-store" });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        const drift = data.drift || {};
        const goal = data.goal || {};
        const balance = data.balance || {};
        const freshness = data.freshness || {};
        const latestTrade = data.latest_trade || {};
        const weekly = data.weekly || {};
        const shadowDay = data.shadow_day || {};
        const reflection = data.latest_reflection || {};
        const versions = data.versions || {};
        const warnings = Array.isArray(data.warnings) ? data.warnings : [];
        const lvl = String(data.status_level || "WARN").toLowerCase();
        const offlineMode = res.headers.get("X-Ouroboros-Offline") === "1" || Boolean(data.offline_mode);
        badgeEl.className = "badge " + lvl;
        badgeEl.textContent = levelLabel(data.status_level || "-");
        stagePillEl.textContent = "運用 " + stageLabel(data.effective_stage || "-");
        headlineEl.textContent = buildHeadline(data, drift);
        quicklineEl.textContent = buildQuickline(data, drift);
        metaEl.textContent = (offlineMode ? "オフライン表示 / " : "") + "更新 " + shortTimestamp(data.generated_at || "-") + " / state更新 " + shortTimestamp((data.source || {}).state_mtime || "-");
        setText("stage", stageLabel(data.effective_stage || "-"));
        setText("mode", modeLabel(data.mode_label || "-"));
        setText("trade", data.trade_enabled ? "取引 ON" : "取引 OFF");
        setText("runner", "bot " + runnerLabel(data.runner_alive));
        setText("risk", stopSummary(data));
        setText("streak", "リスク " + onOffLabel(data.risk_stop) + " / 連敗 " + onOffLabel(data.streak_stop));
        setText("drift_status", driftLabel(drift.status || "-"));
        setText("drift_reason", String((drift.resume_outlook || {}).summary || translateReason((drift.reasons || [])[0] || "")));
        setText("samples", resumeOutlookValue(drift));
        setText("resume", resumeOutlookDetail(drift));
        setText("goal", goalValue(goal));
        setText("goal_detail", goalDetail(goal));
        setText("balance", balanceValue(balance));
        setText("balance_detail", balanceDetail(balance));
        setText("freshness", freshnessValue(freshness));
        setText("freshness_detail", freshnessDetail(freshness));
        setText("latest_trade", latestTradeValue(latestTrade));
        setText("latest_trade_detail", latestTradeDetail(latestTrade));
        setText("weekly", weeklyValue(weekly));
        setText("weekly_detail", weeklyDetail(weekly));
        setText("shadow_day", shadowDayValue(shadowDay));
        setText("shadow_day_detail", shadowDayDetail(shadowDay));
        setText("reflection", reflectionValue(reflection));
        setText("reflection_detail", reflectionDetail(reflection));
        setText("reflection_summary_meta", reflectionSummaryMeta(reflection));
        setText("reflection_summary_next", reflectionSummaryNext(reflection));
        setText("reflection_summary_notes", reflectionSummaryNotes(reflection));
        setText("version_info", versionValue(versions));
        setText("version_detail", versionDetail(versions));
        setText("ai", data.ai_auto_train_enabled ? "学習 ON" : "学習 OFF");
        setText("limit", "日次上限 " + String(data.daily_loss_limit_pct ?? "-"));
        setCardTone("card-stage", "stage", stageTone(data.effective_stage || "-"));
        setCardTone("card-trade", "trade", tradeTone(data));
        setCardTone("card-risk", "risk", data.risk_stop ? "alert" : (data.streak_stop ? "warn" : "ok"));
        setCardTone("card-drift", "drift_status", driftTone(drift.status || "-"));
        setCardTone("card-samples", "samples", resumeOutlookTone(drift));
        setCardTone("card-goal", "goal", goalTone(goal));
        setCardTone("card-balance", "balance", balanceTone(balance));
        setCardTone("card-freshness", "freshness", freshnessTone(freshness));
        setCardTone("card-latest", "latest_trade", latestTradeTone(latestTrade));
        setCardTone("card-weekly", "weekly", weeklyTone(weekly));
        setCardTone("card-shadow-day", "shadow_day", shadowDayTone(shadowDay));
        setCardTone("card-reflection", "reflection", reflectionTone(reflection));
        setCardTone("card-version", "version_info", "info");
        setCardTone("card-ai", "ai", data.ai_auto_train_enabled ? "ok" : "neutral");
        const ul = document.getElementById("warnings");
        ul.innerHTML = "";
        const items = warnings.length ? warnings.slice() : ["目立つ警告はありません"];
        if (offlineMode && !items.includes("offline_mode=ON")) items.unshift("offline_mode=ON");
        items.forEach((raw) => {
          const li = document.createElement("li");
          li.className = items.length && String(raw) !== "目立つ警告はありません" ? warningTone(raw) : "note";
          li.textContent = items.length && String(raw) !== "目立つ警告はありません" ? translateWarning(raw) : String(raw);
          ul.appendChild(li);
        });
        errorEl.textContent = offlineMode ? "オフライン表示中: 最後に取得できた状態または簡易状態を表示しています。" : "";
      } catch (err) {
        errorEl.textContent = "取得に失敗しました: " + String(err) + " / オンライン復帰後に自動更新されます。";
      }
    }
    refresh();
    setInterval(refresh, 30000);
  </script>
</body>
</html>"""
    return (
        page
        .replace("__WIDGET_APP_HREF__", widget_app_href)
        .replace("__REFLECTION_HREF__", reflection_href)
        .replace("__DASHBOARD_HREF__", dashboard_href)
        .replace("__APP_MODE_CLASS__", app_mode_class.strip())
    )


def _daily_reflection_page_html(payload: Dict[str, Any], token: str) -> str:
    latest = payload.get("latest_reflection", {}) if isinstance(payload.get("latest_reflection"), dict) else {}
    goal = payload.get("goal", {}) if isinstance(payload.get("goal"), dict) else {}
    weekly = payload.get("weekly", {}) if isinstance(payload.get("weekly"), dict) else {}
    nav_suffix = f"?token={html.escape(token)}" if token else ""
    if not latest.get("available"):
        body = "<p>終業反省レポートはまだありません。</p>"
    else:
        actions = "".join(f"<li>{html.escape(str(x))}</li>" for x in (latest.get("next_actions") or [])[:4]) or "<li>翌日アクションなし</li>"
        wins = "".join(f"<li>{html.escape(str(x))}</li>" for x in (latest.get("win_notes") or [])[:3]) or "<li>記録なし</li>"
        losses = "".join(f"<li>{html.escape(str(x))}</li>" for x in (latest.get("loss_notes") or [])[:3]) or "<li>記録なし</li>"
        achieved = "達成" if latest.get("goal_achieved") else "未達"
        conf = {"high": "高", "medium": "中", "low": "低"}.get(str(latest.get("sample_confidence", "")).lower(), "-")
        body = f"""
        <div class="hero">
          <div class="badge">{html.escape(str(latest.get("day8", "-")))}</div>
          <h1>終業反省 {achieved}</h1>
          <p>信頼度 {conf} / 生成 {html.escape(str(latest.get("generated_at", "-")))}</p>
          <p>当日損益 {html.escape(_fmt_jpy(_safe_float(goal.get("pnl_jpy")), 0))} / 目標 {html.escape(_fmt_jpy(_safe_float(goal.get("goal_jpy")), 0))}</p>
          <p>今週累計 {html.escape(_fmt_jpy(_safe_float(weekly.get("pnl_jpy_sum")), 0))} / 勝率 {float(_safe_float(weekly.get("win_rate_pct")) or 0.0):.1f}%</p>
          <p>shadow調整 {html.escape(_shadow_adjustment_text(latest) or "-")}</p>
        </div>
        <div class="grid">
          <section class="card"><h2>勝因</h2><ul>{wins}</ul></section>
          <section class="card"><h2>敗因</h2><ul>{losses}</ul></section>
          <section class="card wide"><h2>翌日アクション</h2><ul>{actions}</ul></section>
        </div>
        """
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ouroboros Daily Reflection</title>
  <style>
    body {{
      margin: 0;
      font-family: "Avenir Next", "Hiragino Sans", "Noto Sans JP", sans-serif;
      background: linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%);
      color: #0f172a;
    }}
    .shell {{
      max-width: 860px;
      margin: 0 auto;
      padding: 20px 16px 32px;
    }}
    .nav a {{
      color: #2563eb;
      text-decoration: none;
      font-weight: 700;
    }}
    .hero, .card {{
      background: rgba(255,255,255,0.88);
      border: 1px solid rgba(100,116,139,0.20);
      border-radius: 20px;
      padding: 16px;
      box-shadow: 0 12px 30px rgba(15,23,42,0.06);
    }}
    .hero {{
      margin-top: 12px;
      margin-bottom: 14px;
    }}
    .badge {{
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      background: #dbeafe;
      color: #1d4ed8;
      font-weight: 700;
      margin-bottom: 10px;
    }}
    .hero h1 {{
      margin: 0 0 10px;
      font-size: clamp(24px, 4vw, 34px);
    }}
    .hero p {{
      margin: 6px 0;
      color: #475569;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }}
    .wide {{
      grid-column: 1 / -1;
    }}
    .card h2 {{
      margin: 0 0 10px;
      font-size: 16px;
    }}
    ul {{
      margin: 0;
      padding-left: 18px;
      color: #334155;
    }}
    li + li {{
      margin-top: 6px;
    }}
  </style>
</head>
<body>
  <div class="shell">
    <div class="nav"><a href="/{nav_suffix}">← ステータスへ戻る</a></div>
    {body}
  </div>
</body>
</html>"""


def _json_bytes(payload: Dict[str, Any], pretty: bool = True) -> bytes:
    if pretty:
        return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _make_handler(main_dir: Path, control_path: Path, state_path: Path, token: str):
    class WidgetHandler(BaseHTTPRequestHandler):
        server_version = WIDGET_SERVER_VERSION

        def _authorized(self) -> bool:
            if not token:
                return True
            parsed = urlparse(self.path)
            qtoken = parse_qs(parsed.query).get("token", [""])[0]
            if qtoken and hmac.compare_digest(qtoken, token):
                return True
            auth = str(self.headers.get("Authorization", "")).strip()
            if auth.lower().startswith("bearer "):
                bearer = auth[7:].strip()
                if bearer and hmac.compare_digest(bearer, token):
                    return True
            return False

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802  # CORS preflight
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_HEAD(self) -> None:  # noqa: N802
            self.do_GET()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path or "/"
            if path == "/_health":
                self._send(200, b"ok\n", "text/plain; charset=utf-8")
                return
            if path == "/widget-app-manifest.json":
                body = _json_bytes(_widget_app_manifest(parse_qs(parsed.query).get("token", [""])[0]), pretty=True)
                self._send(200, body, "application/manifest+json; charset=utf-8")
                return
            if path == "/widget-app-sw.js":
                body = _widget_app_service_worker(parse_qs(parsed.query).get("token", [""])[0]).encode("utf-8")
                self._send(200, body, "application/javascript; charset=utf-8")
                return
            if path == "/widget-home-manifest.json":
                body = _json_bytes(_widget_home_manifest(parse_qs(parsed.query).get("token", [""])[0]), pretty=True)
                self._send(200, body, "application/manifest+json; charset=utf-8")
                return
            if path == "/widget-home-sw.js":
                body = _widget_home_service_worker(parse_qs(parsed.query).get("token", [""])[0]).encode("utf-8")
                self._send(200, body, "application/javascript; charset=utf-8")
                return
            if path == "/widget-app-icon.svg":
                body = _widget_app_icon_svg().encode("utf-8")
                self._send(200, body, "image/svg+xml; charset=utf-8")
                return
            if path in {"/unified_dashboard.html", "/dashboard"}:
                _dash = Path(__file__).parent / "unified_dashboard.html"
                if _dash.exists():
                    self._send(200, _dash.read_bytes(), "text/html; charset=utf-8")
                else:
                    self._send(404, b"dashboard not found\n", "text/plain; charset=utf-8")
                return
            if path == "/widget-react" or path.startswith("/widget-react/"):
                asset_path = _resolve_widget_react_path(path)
                if asset_path is None:
                    self._send(404, b"widget-react asset not found\n", "text/plain; charset=utf-8")
                    return
                if asset_path.name == "index.html" and not self._authorized():
                    self._send(401, b"unauthorized\n", "text/plain; charset=utf-8")
                    return
                self._send(200, asset_path.read_bytes(), _content_type_for_path(asset_path))
                return
            if path == "/.harness/last_validate.log":
                _log = main_dir / ".harness" / "last_validate.log"
                if _log.exists():
                    self._send(200, _log.read_bytes(), "text/plain; charset=utf-8")
                else:
                    self._send(404, b"not found\n", "text/plain; charset=utf-8")
                return
            if not self._authorized():
                self._send(401, b"unauthorized\n", "text/plain; charset=utf-8")
                return

            payload = build_widget_status(main_dir=main_dir, control_path=control_path, state_path=state_path)
            if path == "/widget-home":
                query = parse_qs(parsed.query)
                body = _widget_home_page_html(
                    query.get("token", [""])[0],
                    native_shell=query.get("native", ["0"])[0] == "1",
                ).encode("utf-8")
                self._send(200, body, "text/html; charset=utf-8")
                return
            if path in {"/", "/widget", "/index.html", "/widget-app"}:
                body = _status_page_html(
                    parse_qs(parsed.query).get("token", [""])[0],
                    app_mode=(path == "/widget-app"),
                ).encode("utf-8")
                self._send(200, body, "text/html; charset=utf-8")
                return
            if path == "/daily-reflection":
                body = _daily_reflection_page_html(payload, token).encode("utf-8")
                self._send(200, body, "text/html; charset=utf-8")
                return
            if path == "/widget-status.json":
                self._send(200, _json_bytes(payload, pretty=True), "application/json; charset=utf-8")
                return
            if path == "/daily-reflection.json":
                latest = payload.get("latest_reflection", {})
                body = _json_bytes(latest if isinstance(latest, dict) else {}, pretty=True)
                self._send(200, body, "application/json; charset=utf-8")
                return
            if path == "/widget-status.txt":
                self._send(200, (format_status_text(payload) + "\n").encode("utf-8"), "text/plain; charset=utf-8")
                return
            body = f"not found: {html.escape(path)}\n".encode("utf-8")
            self._send(404, body, "text/plain; charset=utf-8")

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write(
                "[widget_status] {addr} - {msg}\n".format(
                    addr=self.address_string(),
                    msg=fmt % args,
                )
            )

    return WidgetHandler


def serve_widget_status(main_dir: Path, control_path: Path, state_path: Path, host: str, port: int, token: str) -> int:
    handler = _make_handler(main_dir=main_dir, control_path=control_path, state_path=state_path, token=token)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"[OK] widget status server listening on http://{host}:{port}", flush=True)
    if token:
        print("[INFO] token auth enabled (Bearer or ?token=...)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] stopped", flush=True)
    finally:
        server.server_close()
    return 0


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build or serve compact Ouroboros status for widgets.")
    ap.add_argument("--main-dir", default=str(ROOT), help=f"default: {ROOT}")
    ap.add_argument("--control-path", default="", help="override CONTROL.csv path")
    ap.add_argument("--state-path", default="", help="override state.json path")
    ap.add_argument("--json-out", default="", help="write JSON payload to file")
    ap.add_argument("--text-out", default="", help="write text payload to file")
    ap.add_argument("--print-json", action="store_true", help="print JSON to stdout")
    ap.add_argument("--print-text", action="store_true", help="print human-readable text to stdout")
    ap.add_argument("--print-swiftbar", action="store_true", help="print SwiftBar-compatible output to stdout")
    ap.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    ap.add_argument("--serve", action="store_true", help="serve compact HTML/JSON/TXT over HTTP")
    ap.add_argument("--host", default=os.getenv("WIDGET_STATUS_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("WIDGET_STATUS_PORT", "8787")))
    ap.add_argument("--token", default=os.getenv("WIDGET_STATUS_TOKEN", ""), help="optional bearer/query token for HTTP mode")
    args = ap.parse_args(argv)

    main_dir = Path(args.main_dir).expanduser().resolve()
    control_path = Path(args.control_path).expanduser().resolve() if args.control_path else (main_dir / "CONTROL.csv")
    state_path = Path(args.state_path).expanduser().resolve() if args.state_path else (main_dir / "state.json")

    payload = build_widget_status(main_dir=main_dir, control_path=control_path, state_path=state_path)

    wrote = False
    if args.json_out:
        _write_text(Path(args.json_out).expanduser().resolve(), _json_bytes(payload, pretty=True).decode("utf-8"))
        wrote = True
    if args.text_out:
        _write_text(Path(args.text_out).expanduser().resolve(), format_status_text(payload) + "\n")
        wrote = True
    if args.print_json:
        sys.stdout.write(_json_bytes(payload, pretty=(args.pretty or True)).decode("utf-8"))
        wrote = True
    if args.print_text:
        sys.stdout.write(format_status_text(payload) + "\n")
        wrote = True
    if args.print_swiftbar:
        sys.stdout.write(format_swiftbar(payload) + "\n")
        wrote = True
    if args.serve:
        return serve_widget_status(
            main_dir=main_dir,
            control_path=control_path,
            state_path=state_path,
            host=args.host,
            port=int(args.port),
            token=str(args.token or ""),
        )
    if not wrote:
        sys.stdout.write(format_status_text(payload) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
