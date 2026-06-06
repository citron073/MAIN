#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import socket
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

try:
    from tools import ibkr_import_audit
    from tools import trade_log_zero_day_review
    from tools import unified_dashboard_healthcheck
    from tools import version_consistency_check
except ImportError:
    import ibkr_import_audit
    import trade_log_zero_day_review
    import unified_dashboard_healthcheck
    import version_consistency_check


ROOT = Path(__file__).resolve().parents[1]
IBKR_READ_ONLY_SMOKE_COMMAND = (
    "python3 test_ibkr_connection.py --stocks AAPL,MSFT,NVDA,TSLA,QQQ,SPY --fx USDJPY"
)
IBKR_VM_TUNNEL_SMOKE_COMMAND = (
    "python3 test_ibkr_connection.py --host 127.0.0.1 --port 17497 --client-id 11 "
    "--stocks AAPL,MSFT,NVDA,TSLA,QQQ,SPY --fx USDJPY"
)
IBKR_VM_READINESS_COMMAND = (
    "python3 tools/vm_ibkr_gateway_readiness.py --host 161.33.26.35 "
    "--key /Users/tani/.ssh/ouroboros_vm_key --print-json"
)
DEFAULT_TIMEOUT_SEC = 15.0
LATEST_DAILY_OPS_PATH = "daily_ops_check_latest.json"
LATEST_HEALTH_PATH = "unified_dashboard_health_latest.json"
LATEST_ZERO_DAY_PATH = "trade_log_zero_day_review_latest.json"
LATEST_IBKR_PATH = "ibkr_connection_latest.json"
LATEST_IBKR_ERROR_PATH = "ibkr_connection_error_latest.json"


def _write_latest(out_dir: Path, filename: str, payload: Dict[str, Any]) -> None:
    (out_dir / filename).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _refresh_latest_alias(out_dir: Path, source_path: str, target_name: str) -> None:
    if not source_path:
        return
    src = Path(source_path)
    if not src.exists():
        return
    (out_dir / target_name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
def _read_ibkr_port() -> int:
    """Read ibkr_port from IBKR_CONTROL.csv (7497=paper, 7496=live)."""
    control_path = ROOT / "IBKR_CONTROL.csv"
    try:
        for row in csv.DictReader(open(control_path, encoding="utf-8-sig")):
            k = str(row.get("key", "") or "").strip()
            if k == "ibkr_port":
                return int(str(row.get("value", "7497")).strip())
    except Exception:
        pass
    return 7497

IBKR_TWS_HOST = "127.0.0.1"
IBKR_TWS_PORT = _read_ibkr_port()
IBKR_VM_TUNNEL_HOST = "127.0.0.1"
IBKR_VM_TUNNEL_PORT = 17497
_is_live = IBKR_TWS_PORT == 7496
IBKR_PREFERRED_RUNTIME = "IB Gateway Live" if _is_live else "IB Gateway Paper"
IBKR_GATEWAY_SETUP_CHECKLIST = [
    f"IB Gatewayを{'Live' if _is_live else 'Paper'} Tradingで起動・ログイン",
    "Configuration/API SettingsでSocket APIを有効化",
    "Read-Only APIはOFFにして発注を許可（Live運用中）" if _is_live else "Read-Only APIは監視のみならON、発注テスト時はOFFを検討",
    f"Socket Portは{'Live用の7496' if _is_live else 'Paper用の7497'}に設定",
    "127.0.0.1/local machineからの接続を許可",
    "API接続承認ダイアログが出る場合は承認またはTrusted IP設定を確認",
]
IBKR_GATEWAY_WATCH_STATE_PATH = ROOT / "review_out" / "ibkr_gateway_watch_state.json"
VM_IBKR_READINESS_GLOB = "vm_ibkr_gateway_readiness_*.json"


def _now_jst_naive() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


def _read_json(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def build_tws_port_status(
    host: str = IBKR_TWS_HOST,
    port: int = IBKR_TWS_PORT,
    timeout_sec: float = 0.5,
) -> Dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            open_ = True
            error = ""
    except OSError as exc:
        open_ = False
        error = f"{exc.__class__.__name__}: {exc}"
    return {
        "host": host,
        "port": port,
        "open": open_,
        "error": error,
        "check": f"{host}:{port}",
        "next_action": "OK" if open_ else f"TWS/IB Gatewayの起動とAPI Socket Port {IBKR_TWS_PORT}を確認",
    }


def _latest_vm_ibkr_readiness(out_dir: Path, day8: str) -> tuple[Dict[str, Any], str]:
    today_path = out_dir / f"vm_ibkr_gateway_readiness_{day8}.json"
    today = _read_json(today_path)
    if today is not None:
        return today, str(today_path)
    files = sorted(out_dir.glob(VM_IBKR_READINESS_GLOB), key=lambda p: p.name)
    if not files:
        return {}, ""
    latest_path = files[-1]
    return _read_json(latest_path) or {}, str(latest_path)


def build_vm_ibkr_readiness_status(out_dir: Path, day8: str) -> Dict[str, Any]:
    report, path = _latest_vm_ibkr_readiness(out_dir, day8)
    readiness = report.get("readiness") if isinstance(report.get("readiness"), dict) else {}
    capabilities = readiness.get("capabilities") if isinstance(readiness.get("capabilities"), dict) else {}
    status = str(readiness.get("status") or "")
    generated_at = str(report.get("generated_at_jst") or "")
    age_hours = None
    if generated_at:
        try:
            dt = datetime.strptime(generated_at, "%Y-%m-%d %H:%M:%S")
            age_hours = round((_now_jst_naive() - dt).total_seconds() / 3600, 1)
        except ValueError:
            age_hours = None
    stale = bool(age_hours is not None and age_hours > 24)
    port_key = f"port_{IBKR_TWS_PORT}_listening"
    port_ready = bool(capabilities.get(port_key) is True or capabilities.get("port_7497_listening") is True)
    running = bool(capabilities.get("ibgateway_running") is True)
    ok = bool(status == "READY_SMOKE" and port_ready and running and not stale)
    if ok:
        next_action = "OK"
    elif not report:
        next_action = "python3 tools/vm_ibkr_gateway_readiness.py --host 161.33.26.35 --key /Users/tani/.ssh/ouroboros_vm_key を実行"
    elif stale:
        next_action = "VM IB Gateway readinessを再実行"
    else:
        next_steps = readiness.get("next_steps") if isinstance(readiness.get("next_steps"), list) else []
        next_action = str(next_steps[0]) if next_steps else "VM IB Gateway状態を確認"
    return {
        "available": bool(report),
        "path": path,
        "generated_at_jst": generated_at,
        "age_hours": age_hours,
        "stale": stale,
        "status": status,
        "ok": ok,
        "capabilities": capabilities,
        "next_action": next_action,
    }


def build_ibkr_runtime_status() -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            ["ps", "aux"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        text = proc.stdout or ""
        error = proc.stderr.strip()
    except Exception as exc:
        text = ""
        error = f"{type(exc).__name__}: {exc}"
    low = text.lower()
    gateway_running = "ibgateway" in low or "ib gateway" in low
    tws_running = "trader workstation" in low or "jts" in low or "tws" in low
    running = gateway_running or tws_running
    if gateway_running:
        runtime = "IB Gateway"
    elif tws_running:
        runtime = "TWS"
    else:
        runtime = ""
    return {
        "preferred_runtime": IBKR_PREFERRED_RUNTIME,
        "running": running,
        "runtime": runtime,
        "gateway_running": gateway_running,
        "tws_running": tws_running,
        "error": error,
        "next_action": "OK" if running else "IB Gateway Paperを起動・ログイン",
        "setup_checklist": IBKR_GATEWAY_SETUP_CHECKLIST,
    }


def _build_vm_port_status(vm_readiness: Dict[str, Any]) -> Dict[str, Any]:
    capabilities = vm_readiness.get("capabilities") if isinstance(vm_readiness.get("capabilities"), dict) else {}
    port_key = f"port_{IBKR_TWS_PORT}_listening"
    open_ = bool(capabilities.get(port_key) is True or capabilities.get("port_7497_listening") is True)
    return {
        "host": "vm:127.0.0.1",
        "port": IBKR_TWS_PORT,
        "open": open_,
        "error": "" if open_ else f"VM readiness reports port {IBKR_TWS_PORT} closed",
        "check": f"vm:127.0.0.1:{IBKR_TWS_PORT}",
        "next_action": "OK" if open_ else str(vm_readiness.get("next_action") or f"VM IB Gateway {IBKR_TWS_PORT}を確認"),
    }


def _is_local_only_ibkr_error(latest_error: Dict[str, Any] | None) -> bool:
    if not latest_error:
        return False
    text = " ".join(
        str(latest_error.get(key) or "")
        for key in ("diagnosis", "detail", "stage")
    ).lower()
    port_str = str(IBKR_TWS_PORT)
    return (
        "ib_insync" in text
        or "17497" in text
        or "tunnel" in text
        or "localhost only" in text
        or f"127.0.0.1:{port_str}" in text
        or f"connect call failed ('127.0.0.1', {port_str})" in text
    )


def build_ibkr_log_status(out_dir: Path, day8: str) -> Dict[str, Any]:
    today_path = out_dir / f"ibkr_connection_{day8}.json"
    today_error_path = out_dir / f"ibkr_connection_error_{day8}.json"
    today = _read_json(today_path)
    today_error = _read_json(today_error_path)
    latest_path = today_path
    latest = today
    if latest is None:
        files = sorted(
            (p for p in out_dir.glob("ibkr_connection_*.json") if "ibkr_connection_error_" not in p.name),
            key=lambda p: p.name,
        )
        if files:
            latest_path = files[-1]
            latest = _read_json(latest_path)
    latest_error_path = today_error_path
    latest_error = today_error
    if latest_error is None:
        error_files = sorted(out_dir.glob("ibkr_connection_error_*.json"), key=lambda p: p.name)
        if error_files:
            latest_error_path = error_files[-1]
            latest_error = _read_json(latest_error_path)
    vm_readiness = build_vm_ibkr_readiness_status(out_dir, day8)
    vm_authoritative = bool(vm_readiness.get("available"))
    connected = bool((latest or {}).get("connected") is True or vm_readiness.get("ok") is True)
    latest_host = str((latest or {}).get("host") or IBKR_TWS_HOST)
    try:
        latest_port = int((latest or {}).get("port") or IBKR_TWS_PORT)
    except (TypeError, ValueError):
        latest_port = IBKR_TWS_PORT
    api_mode = "vm_tunnel" if latest_port == IBKR_VM_TUNNEL_PORT or vm_authoritative else "local"
    generated_at = str((latest or {}).get("generated_at_jst", ""))
    age_hours = None
    if generated_at:
        try:
            dt = datetime.strptime(generated_at, "%Y-%m-%d %H:%M:%S")
            age_hours = round((_now_jst_naive() - dt).total_seconds() / 3600, 1)
        except ValueError:
            age_hours = None
    if vm_authoritative and (not generated_at or latest_port != IBKR_VM_TUNNEL_PORT):
        generated_at = str(vm_readiness.get("generated_at_jst") or generated_at)
        age_hours = vm_readiness.get("age_hours")
    tws_port = build_tws_port_status()
    tunnel_status = build_tws_port_status(IBKR_VM_TUNNEL_HOST, IBKR_VM_TUNNEL_PORT)
    api_endpoint_status = build_tws_port_status(latest_host, latest_port)
    runtime_status = build_ibkr_runtime_status()
    effective_runtime_status = dict(runtime_status)
    if vm_authoritative:
        caps = vm_readiness.get("capabilities") if isinstance(vm_readiness.get("capabilities"), dict) else {}
        vm_running = bool(caps.get("ibgateway_running") is True)
        effective_runtime_status = {
            "preferred_runtime": "VM IB Gateway Paper",
            "running": vm_running,
            "runtime": "VM IB Gateway" if vm_running else "",
            "gateway_running": vm_running,
            "tws_running": False,
            "error": "",
            "next_action": "OK" if vm_running else str(vm_readiness.get("next_action") or "VM IB Gateway Paperを起動・ログイン"),
            "setup_checklist": IBKR_GATEWAY_SETUP_CHECKLIST,
        }
    effective_port_status = _build_vm_port_status(vm_readiness) if vm_authoritative else tws_port
    stale = bool(age_hours is not None and age_hours > 24)
    needs_smoke = (
        (today is None and not (vm_authoritative and vm_readiness.get("ok")))
        or stale
        or not connected
        or not effective_port_status["open"]
        or not effective_runtime_status["running"]
    )
    suppress_local_only_error = bool(vm_authoritative and _is_local_only_ibkr_error(latest_error))
    if needs_smoke:
        if latest_error and latest_error.get("diagnosis") and not suppress_local_only_error:
            next_action = str(latest_error.get("diagnosis"))
        else:
            if not effective_runtime_status["running"]:
                next_action = effective_runtime_status["next_action"]
            elif vm_authoritative and stale:
                next_action = str(vm_readiness.get("next_action") or "VM IB Gateway readinessを再実行")
            elif vm_authoritative and tunnel_status["open"] is False and vm_readiness.get("ok"):
                next_action = "VM IB GatewayはOK。Mac側で ./tools/open_vm_ibkr_tunnel.sh --host 161.33.26.35 --key /Users/tani/.ssh/ouroboros_vm_key を開く"
            elif not effective_port_status["open"]:
                next_action = effective_port_status["next_action"]
            else:
                next_action = "IB Gateway Paperを起動し、Read-Only smokeを再実行"
    else:
        next_action = "OK"
    active_error_available = bool(needs_smoke and latest_error is not None and not suppress_local_only_error)
    active_error = latest_error if active_error_available else {}
    if vm_authoritative and not tunnel_status["open"]:
        smoke_command = IBKR_VM_READINESS_COMMAND
    else:
        smoke_command = IBKR_VM_TUNNEL_SMOKE_COMMAND if api_mode == "vm_tunnel" else IBKR_READ_ONLY_SMOKE_COMMAND
    return {
        "available_today": today is not None,
        "latest_available": latest is not None,
        "latest_path": str(latest_path) if latest is not None else "",
        "latest_error_available": latest_error is not None,
        "latest_error_path": str(latest_error_path) if latest_error is not None else "",
        "latest_error_stage": str((latest_error or {}).get("stage", "")),
        "latest_error_diagnosis": str((latest_error or {}).get("diagnosis", "")),
        "latest_error_detail": str((latest_error or {}).get("detail", "")),
        "latest_error_checklist": (latest_error or {}).get("checklist", []),
        "active_error_available": active_error_available,
        "active_error_stage": str((active_error or {}).get("stage", "")),
        "active_error_diagnosis": str((active_error or {}).get("diagnosis", "")),
        "active_error_detail": str((active_error or {}).get("detail", "")),
        "active_error_checklist": (active_error or {}).get("checklist", []),
        "client_id_diagnostics": (latest_error or {}).get("client_id_diagnostics", {}),
        "generated_at_jst": generated_at,
        "age_hours": age_hours,
        "stale": stale,
        "connected": connected,
        "needs_smoke": needs_smoke,
        "next_action": next_action,
        "api_mode": api_mode,
        "api_endpoint_status": api_endpoint_status,
        "effective_port_status": effective_port_status,
        "effective_runtime_status": effective_runtime_status,
        "tunnel_status": tunnel_status,
        "vm_readiness": vm_readiness,
        "tws_port_status": tws_port,
        "runtime_status": runtime_status,
        "gateway_setup_checklist": IBKR_GATEWAY_SETUP_CHECKLIST,
        "read_only_smoke_command": smoke_command,
        "symbols": (latest or {}).get("stock_symbols", []),
        "positions_n": len((latest or {}).get("positions") or []),
    }


def build_version_consistency_status() -> Dict[str, Any]:
    try:
        result = version_consistency_check.run_version_consistency_check(ROOT)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_count": 1,
            "expected": {},
            "items": [],
        }
    return result


def build_ibkr_import_audit_status() -> Dict[str, Any]:
    try:
        result = ibkr_import_audit.build_audit(ROOT)
    except Exception as exc:
        return {
            "ok": False,
            "unexpected_importers": [],
            "paper_order_importers_allowed": [],
            "next_action": str(exc),
        }
    return result


def build_ibkr_watch_state_status(path: Path = IBKR_GATEWAY_WATCH_STATE_PATH) -> Dict[str, Any]:
    state = _read_json(path) or {}
    last_checked_at = str(state.get("last_checked_at_jst", ""))
    age_minutes = None
    if last_checked_at:
        try:
            dt = datetime.strptime(last_checked_at, "%Y-%m-%d %H:%M:%S")
            age_minutes = round((_now_jst_naive() - dt).total_seconds() / 60, 1)
        except ValueError:
            age_minutes = None
    available = bool(state)
    stale = bool(age_minutes is not None and age_minutes > 15)
    last_ok = state.get("last_status_ok")
    if not available:
        label = "未実行"
        next_action = "python3 tools/ibkr_gateway_watch.py --dry-run で確認"
    elif stale:
        label = "古い"
        next_action = "IB Gateway watch LaunchAgentまたはMacスリープ状態を確認"
    elif last_ok is True:
        label = "OK"
        next_action = "OK"
    elif last_ok is False:
        label = "要確認"
        next_action = str(state.get("last_reason") or "IB Gateway状態を確認")
    else:
        label = "不明"
        next_action = "IB Gateway watch stateを確認"
    return {
        "available": available,
        "path": str(path) if path.exists() else "",
        "last_checked_at_jst": last_checked_at,
        "age_minutes": age_minutes,
        "stale": stale,
        "last_status_ok": last_ok,
        "last_issue_key": str(state.get("last_issue_key", "")),
        "last_reason": str(state.get("last_reason", "")),
        "last_sent_at_jst": str(state.get("last_sent_at_jst", "")),
        "last_ntfy_result": str(state.get("last_ntfy_result", "")),
        "label": label,
        "next_action": next_action,
    }


def run_daily_ops_check(out_dir: Path, dashboard_url: str, timeout_sec: float) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    history_path = out_dir / "unified_dashboard_health_history.jsonl"

    dashboard_report = unified_dashboard_healthcheck.build_report(
        dashboard_url,
        timeout_sec,
        history_path,
    )
    dashboard = dashboard_report.get("dashboard") or {}
    is_local_permission_error = (
        dashboard.get("status_code") == 0
        and "Operation not permitted" in str(dashboard.get("error", ""))
    )
    if not is_local_permission_error:
        _write_latest(out_dir, f"unified_dashboard_health_{dashboard_report['day8']}.json", dashboard_report)
        _write_latest(out_dir, LATEST_HEALTH_PATH, dashboard_report)
        with history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(dashboard_report, ensure_ascii=False, separators=(",", ":")) + "\n")

    day8 = dashboard_report["day8"]
    zero_report = trade_log_zero_day_review.build_report(
        day8,
        trade_log_zero_day_review.DEFAULT_LOGS_DIR,
        ROOT / "CONTROL.csv",
    )
    _write_latest(out_dir, f"trade_log_zero_day_review_{day8}.json", zero_report)
    _write_latest(out_dir, LATEST_ZERO_DAY_PATH, zero_report)
    ibkr_log_status = build_ibkr_log_status(out_dir, day8)
    _refresh_latest_alias(out_dir, str(ibkr_log_status.get("latest_path", "")), LATEST_IBKR_PATH)
    _refresh_latest_alias(out_dir, str(ibkr_log_status.get("latest_error_path", "")), LATEST_IBKR_ERROR_PATH)
    ibkr_watch_state = build_ibkr_watch_state_status(out_dir / "ibkr_gateway_watch_state.json")
    version_consistency = build_version_consistency_status()
    ibkr_import_status = build_ibkr_import_audit_status()

    # DD report: 自動呼び出し
    dd_report_status: Dict[str, Any] = {"available": False, "path": "", "metrics": {}, "error": ""}
    try:
        dd_proc = subprocess.run(
            ["python3", str(ROOT / "tools" / "dd_report.py"), day8],
            capture_output=True,
            text=True,
            timeout=30.0,
            cwd=str(ROOT),
        )
        dd_report_json_path = ROOT / "reports" / f"dd_report_{day8}.json"
        if dd_report_json_path.exists():
            dd_data = json.loads(dd_report_json_path.read_text(encoding="utf-8"))
            dd_metrics = dd_data.get("metrics") if isinstance(dd_data.get("metrics"), dict) else {}
            dd_report_status = {
                "available": True,
                "path": str(dd_report_json_path),
                "metrics": {
                    "n_trades": dd_metrics.get("n_trades"),
                    "daily_max_drawdown_amount": dd_metrics.get("daily_max_drawdown_amount"),
                    "profit_factor": dd_metrics.get("profit_factor"),
                    "recovery_factor": dd_metrics.get("recovery_factor"),
                    "expectancy_per_trade_pct": dd_metrics.get("expectancy_per_trade_pct"),
                    "dd_recovery_minutes": dd_metrics.get("dd_recovery_minutes"),
                },
                "error": dd_proc.stderr.strip() if dd_proc.returncode != 0 else "",
            }
        else:
            dd_report_status["error"] = f"rc={dd_proc.returncode} stderr={dd_proc.stderr.strip()[:200]}"
    except Exception as _dd_exc:
        dd_report_status["error"] = str(_dd_exc)

    # PDCA日次自律評価: dd_report 完了後に呼び出し
    pdca_daily_status: Dict[str, Any] = {"available": False, "hints": [], "error": ""}
    try:
        pdca_proc = subprocess.run(
            ["python3", str(ROOT / "tools" / "pdca_daily_update.py"), "--day8", day8, "--no-notify"],
            capture_output=True,
            text=True,
            timeout=45.0,
            cwd=str(ROOT),
        )
        pdca_json_path = ROOT / "reports" / f"pdca_daily_{day8}.json"
        if pdca_json_path.exists():
            pdca_data = json.loads(pdca_json_path.read_text(encoding="utf-8"))
            pdca_daily_status = {
                "available": True,
                "path": str(pdca_json_path),
                "hints": pdca_data.get("hints", []),
                "updated_entries": pdca_data.get("updated_entries", []),
                "error": pdca_proc.stderr.strip() if pdca_proc.returncode != 0 else "",
            }
        else:
            pdca_daily_status["error"] = f"rc={pdca_proc.returncode} stderr={pdca_proc.stderr.strip()[:200]}"
    except Exception as _pdca_exc:
        pdca_daily_status["error"] = str(_pdca_exc)

    report = {
        "generated_at_jst": dashboard_report["checked_at_jst"],
        "day8": day8,
        "dashboard_health": dashboard_report,
        "trade_log_zero_day": zero_report,
        "ibkr_log_status": ibkr_log_status,
        "ibkr_watch_state": ibkr_watch_state,
        "ibkr_import_audit": ibkr_import_status,
        "version_consistency": version_consistency,
        "dd_report": dd_report_status,
        "pdca_daily": pdca_daily_status,
        "notes": {
            "dashboard_history_appended": not is_local_permission_error,
            "sandbox_permission_error_skipped": is_local_permission_error,
        },
    }
    _write_latest(out_dir, f"daily_ops_check_{day8}.json", report)
    _write_latest(out_dir, LATEST_DAILY_OPS_PATH, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Run daily dashboard uptime and zero trade-log checks.")
    ap.add_argument("--url", default=unified_dashboard_healthcheck.resolve_default_url())
    ap.add_argument("--timeout-sec", type=float, default=DEFAULT_TIMEOUT_SEC)
    ap.add_argument("--out-dir", default=str(ROOT / "review_out"))
    args = ap.parse_args()

    report = run_daily_ops_check(Path(args.out_dir), args.url, args.timeout_sec)
    return 0 if (report["dashboard_health"].get("dashboard") or {}).get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
