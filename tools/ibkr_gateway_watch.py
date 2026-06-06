#!/usr/bin/env python3
"""Read-only IB Gateway watchdog.

This script never places orders. It refreshes the Daily Ops report, checks
whether IB Gateway + the configured API port + the read-only smoke log are healthy, and sends
ntfy only when the state changes or the cooldown expires.

--vm-mode: skip daily_ops_check, instead SSH to VM and check the
ouroboros-ibkr-bot.service status directly. Use this when IB Gateway
runs on the VM (not localhost).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Tuple

try:
    from tools import daily_ops_check
except ImportError:
    import daily_ops_check


ROOT = Path(__file__).resolve().parents[1]
REVIEW_OUT = ROOT / "review_out"
SECRETS_TOML = ROOT / ".streamlit" / "secrets.toml"
STATE_PATH = REVIEW_OUT / "ibkr_gateway_watch_state.json"


def _now_jst_naive() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_toml_str(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            return v if v and v != "***MASKED***" else ""
    return ""


def _http_post(url: str, body: bytes, headers: Dict[str, str], timeout: float = 5.0) -> Tuple[bool, str]:
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, f"HTTP {r.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, str(exc)


def _latest_daily_ops_path(out_dir: Path, day8: str = "") -> Path | None:
    if day8:
        p = out_dir / f"daily_ops_check_{day8}.json"
        return p if p.exists() else None
    files = sorted(out_dir.glob("daily_ops_check_*.json"), key=lambda p: p.name)
    return files[-1] if files else None


def load_or_refresh_report(
    out_dir: Path,
    dashboard_url: str,
    timeout_sec: float,
    *,
    refresh: bool,
    day8: str = "",
) -> Dict[str, Any]:
    if refresh:
        return daily_ops_check.run_daily_ops_check(out_dir, dashboard_url, timeout_sec)
    path = _latest_daily_ops_path(out_dir, day8)
    return _read_json(path) if path else {}


def build_watch_decision(
    report: Dict[str, Any],
    state: Dict[str, Any],
    *,
    now: datetime,
    cooldown_hours: float,
) -> Dict[str, Any]:
    ibkr = report.get("ibkr_log_status") or {}
    port = ibkr.get("effective_port_status") or ibkr.get("tws_port_status") or {}
    runtime = ibkr.get("effective_runtime_status") or ibkr.get("runtime_status") or {}
    ok = bool(
        ibkr.get("connected") is True
        and ibkr.get("needs_smoke") is False
        and ibkr.get("stale") is False
        and port.get("open") is True
        and runtime.get("running") is True
    )
    reason = "OK"
    issue_key = "OK"
    if not ok:
        if runtime.get("running") is False:
            reason = str(runtime.get("next_action") or "IB Gateway Paperが未起動")
            issue_key = "runtime_not_running"
        elif port.get("open") is False:
            reason = str(port.get("next_action") or port.get("error") or "APIポートがCLOSED")
            issue_key = "port_closed"
        elif ibkr.get("stale"):
            reason = "IBKR smokeログが24時間以上古い"
            issue_key = "smoke_stale"
        elif ibkr.get("needs_smoke"):
            reason = str(ibkr.get("active_error_diagnosis") or ibkr.get("next_action") or "Read-Only smoke再実行が必要")
            issue_key = "smoke_needed"
        else:
            reason = "IBKR状態が未確認"
            issue_key = "unknown"

    previous_key = str(state.get("last_issue_key", ""))
    last_sent_at = str(state.get("last_sent_at_jst", ""))
    cooldown_elapsed = True
    if last_sent_at:
        try:
            last_dt = datetime.strptime(last_sent_at, "%Y-%m-%d %H:%M:%S")
            cooldown_elapsed = (now - last_dt).total_seconds() >= cooldown_hours * 3600
        except ValueError:
            cooldown_elapsed = True

    should_notify = False
    event = "steady_ok" if ok else "steady_issue"
    if ok and previous_key and previous_key != "OK":
        should_notify = True
        event = "recovered"
    elif not ok and (issue_key != previous_key or cooldown_elapsed):
        should_notify = True
        event = "issue"

    return {
        "ok": ok,
        "event": event,
        "issue_key": issue_key,
        "reason": reason,
        "should_notify": should_notify,
        "cooldown_elapsed": cooldown_elapsed,
        "generated_at_jst": now.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "connected": ibkr.get("connected"),
            "needs_smoke": ibkr.get("needs_smoke"),
            "stale": ibkr.get("stale"),
            "port_open": port.get("open"),
            "runtime_running": runtime.get("running"),
            "runtime": runtime.get("runtime"),
        },
    }


def build_message(decision: Dict[str, Any], report: Dict[str, Any]) -> Tuple[str, str, str]:
    day8 = str(report.get("day8") or "")
    summary = decision.get("summary") or {}
    api_port = int(getattr(daily_ops_check, "IBKR_TWS_PORT", 7497))
    if decision.get("ok"):
        title = "Ouroboros IB Gateway OK"
        tags = "white_check_mark"
        body = [
            f"IB Gateway read-only check recovered/OK ({day8 or '-'})",
            f"runtime={summary.get('runtime') or '-'} port_open={summary.get('port_open')}",
            f"api_mode={(report.get('ibkr_log_status') or {}).get('api_mode') or 'local'}",
            "VM/trading logic impact: none",
        ]
    else:
        title = "Ouroboros IB Gateway Check"
        tags = "warning"
        body = [
            f"IB Gateway read-only check needs action ({day8 or '-'})",
            f"reason={decision.get('reason')}",
            f"next: IB Gatewayログイン / API ON / Socket Port {api_port} / VM tunnel確認 / Read-Only smoke再実行",
            f"cmd={daily_ops_check.IBKR_READ_ONLY_SMOKE_COMMAND}",
            "orders: not touched",
        ]
    return title, "\n".join(body), tags


def send_ntfy(title: str, body: str, tags: str, timeout_sec: float = 5.0) -> Tuple[bool, str]:
    url = _read_toml_str(SECRETS_TOML, "ntfy_topic_url")
    if not url:
        return False, "ntfy_topic_url not configured"
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Title": title,
        "Tags": tags,
        "Priority": "default",
    }
    bearer = _read_toml_str(SECRETS_TOML, "ntfy_bearer_token")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return _http_post(url, body.encode("utf-8"), headers, timeout=timeout_sec)


def _vm_mode_check(
    vm_host: str,
    vm_user: str,
    vm_key: str,
    state: Dict[str, Any],
    now: datetime,
    cooldown_hours: float,
) -> Tuple[Dict[str, Any], str, str, str]:
    """SSH to VM and check both bot service status and configured API port."""
    api_port = int(getattr(daily_ops_check, "IBKR_TWS_PORT", 7497))
    ssh_opts = [
        "-o", "IdentitiesOnly=yes",
        "-o", "ConnectTimeout=8",
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-i", vm_key,
    ]
    port_status = "unknown"
    try:
        remote_cmd = (
            "bot=$(systemctl is-active ouroboros-ibkr-bot.service 2>/dev/null || echo unknown); "
            f"if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ':{api_port} '; then "
            "port=open; else port=closed; fi; "
            "printf 'bot=%s\\nport=%s\\n' \"$bot\" \"$port\""
        )
        cmd = ["ssh"] + ssh_opts + [f"{vm_user}@{vm_host}", remote_cmd]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        lines = {
            key: value
            for key, _, value in (
                line.partition("=")
                for line in (result.stdout or "").splitlines()
                if "=" in line
            )
        }
        stderr = str(result.stderr or "").strip()
        if result.returncode != 0 and "bot" not in lines:
            err = stderr or f"returncode={result.returncode}"
            bot_status = f"ssh_error:{err}"
            port_status = "unknown"
        else:
            bot_status = str(lines.get("bot") or "unknown").strip().lower()
            port_status = str(lines.get("port") or "unknown").strip().lower()
    except Exception as e:
        bot_status = f"ssh_error:{e}"
        port_status = "unknown"

    # Also read synced state from .local_llm/ibkr/ibkr_state.json if available
    sync_path = ROOT / ".local_llm" / "ibkr" / "ibkr_state.json"
    sync_state: Dict = {}
    if sync_path.exists():
        try:
            sync_state = json.loads(sync_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    ok = bot_status == "active" and port_status == "open"
    if bot_status != "active":
        issue_key = f"vm_bot_{bot_status.replace(':', '_')}"
        reason = f"ouroboros-ibkr-bot.service = {bot_status}"
    elif port_status != "open":
        issue_key = "port_closed"
        reason = f"VM IB Gateway API 127.0.0.1:{api_port} がCLOSED"
    else:
        issue_key = "OK"
        reason = "OK"

    previous_key = str(state.get("last_issue_key", ""))
    last_sent_at = str(state.get("last_sent_at_jst", ""))
    cooldown_elapsed = True
    if last_sent_at:
        try:
            last_dt = datetime.strptime(last_sent_at, "%Y-%m-%d %H:%M:%S")
            cooldown_elapsed = (now - last_dt).total_seconds() >= cooldown_hours * 3600
        except ValueError:
            cooldown_elapsed = True

    should_notify = False
    event = "steady_ok" if ok else "steady_issue"
    if ok and previous_key and previous_key != "OK":
        should_notify = True
        event = "recovered"
    elif not ok and (issue_key != previous_key or cooldown_elapsed):
        should_notify = True
        event = "issue"

    decision = {
        "ok": ok,
        "event": event,
        "issue_key": issue_key,
        "reason": reason,
        "should_notify": should_notify,
        "cooldown_elapsed": cooldown_elapsed,
        "generated_at_jst": now.strftime("%Y-%m-%d %H:%M:%S"),
        "bot_status": bot_status,
        "port_status": port_status,
        "sync_state": sync_state,
    }

    if ok:
        daily_pnl = sync_state.get("daily_realized_pnl_usd", "?")
        trade_cnt = sync_state.get("daily_trade_count", "?")
        title = "Ouroboros IBKR Bot OK"
        tags = "white_check_mark"
        body = (
            f"ibkr-bot active on VM\n"
            f"daily_trade_count={trade_cnt}  daily_pnl=${daily_pnl}"
        )
    else:
        title = "Ouroboros IBKR Bot WARN"
        tags = "warning"
        if issue_key == "port_closed":
            body = (
                f"VM IB Gateway API 127.0.0.1:{api_port} is closed\n"
                f"ouroboros-ibkr-bot.service status: {bot_status}\n"
                f"VM: {vm_user}@{vm_host}\n"
                f"action: IB Gatewayを再ログインし、Socket Port {api_port} を確認"
            )
        else:
            body = (
                f"ouroboros-ibkr-bot.service status: {bot_status}\n"
                f"VM: {vm_user}@{vm_host}\n"
                "action: ssh to VM → sudo systemctl restart ouroboros-ibkr-bot"
            )

    return decision, title, body, tags


def main() -> int:
    ap = argparse.ArgumentParser(description="Watch IB Gateway / IBKR bot health and send deduped ntfy alerts.")
    ap.add_argument("--out-dir", default=str(REVIEW_OUT))
    ap.add_argument("--url", default=daily_ops_check.unified_dashboard_healthcheck.DEFAULT_URL)
    ap.add_argument("--timeout-sec", type=float, default=daily_ops_check.DEFAULT_TIMEOUT_SEC)
    ap.add_argument("--cooldown-hours", type=float, default=6.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-refresh", action="store_true", help="Read latest daily_ops_check JSON without refreshing it.")
    ap.add_argument("--vm-mode", action="store_true",
                    help="Check VM bot service via SSH instead of localhost daily_ops_check.")
    ap.add_argument("--vm-host", default="161.33.26.35")
    ap.add_argument("--vm-user", default="ubuntu")
    ap.add_argument("--vm-key", default="/Users/tani/.ssh/ouroboros_vm_key")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    now = _now_jst_naive()
    state = _read_json(STATE_PATH)

    if args.vm_mode:
        decision, title, body, tags = _vm_mode_check(
            args.vm_host, args.vm_user, args.vm_key,
            state, now, args.cooldown_hours,
        )
    else:
        report = load_or_refresh_report(
            out_dir,
            args.url,
            args.timeout_sec,
            refresh=not args.no_refresh,
        )
        if not report:
            print("ibkr_gateway_watch=NG reason=no_daily_ops_report")
            return 1
        decision = build_watch_decision(report, state, now=now, cooldown_hours=args.cooldown_hours)
        title, body, tags = build_message(decision, report)

    ntfy_result = "skipped"
    ntfy_ok = False
    if decision["should_notify"]:
        if args.dry_run:
            ntfy_result = "dry_run"
        else:
            ntfy_ok, ntfy_result = send_ntfy(title, body, tags)
    if not args.dry_run:
        next_state = {
            "last_issue_key": decision["issue_key"],
            "last_status_ok": decision["ok"],
            "last_checked_at_jst": decision["generated_at_jst"],
            "last_reason": decision["reason"],
        }
        if decision["should_notify"]:
            next_state["last_sent_at_jst"] = decision["generated_at_jst"]
            next_state["last_ntfy_result"] = ntfy_result
        elif state.get("last_sent_at_jst"):
            next_state["last_sent_at_jst"] = state.get("last_sent_at_jst")
            next_state["last_ntfy_result"] = state.get("last_ntfy_result", "")
        _write_json(STATE_PATH, next_state)

    print(
        "ibkr_gateway_watch="
        + ("OK" if decision["ok"] else "WARN")
        + f" event={decision['event']} notify={decision['should_notify']} ntfy={ntfy_result}"
    )
    print(f"reason={decision['reason']}")
    if args.dry_run and decision["should_notify"]:
        print("--- message preview ---")
        print(title)
        print(body)
    if decision["should_notify"] and not args.dry_run and not ntfy_ok and ntfy_result != "skipped":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
