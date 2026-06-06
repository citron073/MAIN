#!/usr/bin/env python3
"""Read-only readiness check for moving IB Gateway to the VM.

The script does not install packages, reveal secrets, open ports, or start
services. It only inspects whether the VM has the pieces needed to run IB
Gateway Paper in a headless/stable setup.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "review_out"
DEFAULT_REMOTE_USER = "ubuntu"
DEFAULT_REMOTE_MAIN_CANDIDATES = [
    "$HOME/trading_bot/MAIN",
    "$HOME/trading_bot/trading_bot/MAIN",
]
REMOTE_CHECK_SCRIPT = r'''
set +e
printf 'section=system\n'
uname -a 2>/dev/null | sed 's/^/uname=/'
printf 'whoami=%s\n' "$(whoami 2>/dev/null)"
printf 'pwd=%s\n' "$(pwd 2>/dev/null)"

printf 'section=commands\n'
for c in java xvfb-run Xvfb x11vnc vncserver openbox fluxbox ss curl unzip; do
  if command -v "$c" >/dev/null 2>&1; then
    printf 'cmd_%s=1:%s\n' "$c" "$(command -v "$c")"
  else
    printf 'cmd_%s=0\n' "$c"
  fi
done

printf 'section=ibgateway_files\n'
for p in "$HOME/Jts" "$HOME/IBJts" "$HOME/ibgateway" "/opt/ibgateway" "/opt/IBGateway" "/usr/local/ibgateway"; do
  if [ -e "$p" ]; then
    printf 'path=%s\n' "$p"
  fi
done

printf 'section=process\n'
ps aux 2>/dev/null | grep -Ei 'ibgateway|ib gateway|jts|xvfb|x11vnc|vncserver' | grep -v grep | sed 's/^/proc=/'

printf 'section=ports\n'
if command -v ss >/dev/null 2>&1; then
  ss -ltn 2>/dev/null | grep -E ':(7497|4002)\b' | sed 's/^/listen=/'
else
  printf 'ss_missing=1\n'
fi

printf 'section=systemd\n'
if command -v systemctl >/dev/null 2>&1; then
  systemctl list-unit-files 2>/dev/null | grep -Ei 'ibgateway|xvfb|vnc' | sed 's/^/unit=/'
else
  printf 'systemctl_missing=1\n'
fi
'''


def _now_jst_naive() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


def _run_local_command(cmd: List[str], timeout_sec: float) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
        }


def _ssh_command(host: str, user: str, key: str, timeout_sec: float) -> List[str]:
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={int(max(1, timeout_sec))}",
    ]
    if key:
        cmd.extend(["-i", key])
    cmd.append(f"{user}@{host}")
    cmd.append(f"bash -lc {shlex.quote(REMOTE_CHECK_SCRIPT)}")
    return cmd


def _parse_remote_lines(text: str) -> Dict[str, Any]:
    sections: Dict[str, List[str]] = {}
    current = "unknown"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("section="):
            current = line.split("=", 1)[1]
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {
        "sections": sections,
        "commands": _parse_command_presence(sections.get("commands", [])),
        "ibgateway_paths": [line.split("=", 1)[1] for line in sections.get("ibgateway_files", []) if line.startswith("path=")],
        "process_lines": [line.split("=", 1)[1] for line in sections.get("process", []) if line.startswith("proc=")],
        "listen_lines": [line.split("=", 1)[1] for line in sections.get("ports", []) if line.startswith("listen=")],
        "unit_lines": [line.split("=", 1)[1] for line in sections.get("systemd", []) if line.startswith("unit=")],
    }


def _parse_command_presence(lines: List[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for line in lines:
        if not line.startswith("cmd_"):
            continue
        key, value = line.split("=", 1)
        name = key[4:]
        parts = value.split(":", 1)
        present = parts[0] == "1"
        out[name] = {"present": present, "path": parts[1] if present and len(parts) > 1 else ""}
    return out


def build_readiness(parsed: Dict[str, Any], *, ssh_ok: bool) -> Dict[str, Any]:
    commands = parsed.get("commands") or {}
    has_java = bool(commands.get("java", {}).get("present"))
    has_headless_display = bool(
        commands.get("Xvfb", {}).get("present")
        or commands.get("xvfb-run", {}).get("present")
        or commands.get("vncserver", {}).get("present")
    )
    has_remote_gui = bool(commands.get("x11vnc", {}).get("present") or commands.get("vncserver", {}).get("present"))
    has_window_manager = bool(commands.get("openbox", {}).get("present") or commands.get("fluxbox", {}).get("present"))
    has_ibgateway_files = bool(parsed.get("ibgateway_paths"))
    ibgateway_running = any("ibgateway" in line.lower() or "ib gateway" in line.lower() for line in parsed.get("process_lines", []))
    port_7497_listening = any(":7497" in line for line in parsed.get("listen_lines", []))

    blockers: List[str] = []
    warnings: List[str] = []
    if not ssh_ok:
        blockers.append("ssh_unreachable")
    if ssh_ok and not has_java:
        blockers.append("java_missing")
    if ssh_ok and not has_headless_display:
        blockers.append("headless_display_missing")
    if ssh_ok and not has_ibgateway_files:
        warnings.append("ibgateway_files_not_found")
    if ssh_ok and has_headless_display and not has_remote_gui:
        warnings.append("remote_gui_access_not_detected")
    if ssh_ok and has_headless_display and not has_window_manager:
        warnings.append("window_manager_not_detected")
    if ssh_ok and has_ibgateway_files and not ibgateway_running:
        warnings.append("ibgateway_not_running")
    if ssh_ok and ibgateway_running and not port_7497_listening:
        warnings.append("port_7497_not_listening")

    if blockers:
        status = "BLOCKED"
    elif has_ibgateway_files and ibgateway_running and port_7497_listening:
        status = "READY_SMOKE"
    elif has_java and has_headless_display:
        status = "SETUP_NEEDED"
    else:
        status = "NEEDS_REVIEW"

    next_steps = []
    if "java_missing" in blockers:
        next_steps.append("VMへJava runtimeを入れる")
    if "headless_display_missing" in blockers:
        next_steps.append("VMへXvfb/VNC等のヘッドレスGUI環境を入れる")
    if "ibgateway_files_not_found" in warnings:
        next_steps.append("VMへIB Gateway Linux版を配置する")
    if "remote_gui_access_not_detected" in warnings:
        next_steps.append("初回ログイン用にVNCまたはSSH X11転送を用意する")
    if "ibgateway_not_running" in warnings:
        next_steps.append("IB Gateway PaperをVM上で起動・ログインする")
    if "port_7497_not_listening" in warnings:
        next_steps.append("IB Gateway API Socket Portを7497にし、localhost接続を許可する")
    if status == "READY_SMOKE":
        next_steps.append("SSHトンネル経由でread-only smokeを実行する")

    return {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "capabilities": {
            "java": has_java,
            "headless_display": has_headless_display,
            "remote_gui_access": has_remote_gui,
            "window_manager": has_window_manager,
            "ibgateway_files": has_ibgateway_files,
            "ibgateway_running": ibgateway_running,
            "port_7497_listening": port_7497_listening,
        },
        "next_steps": next_steps,
    }


def build_report(host: str, user: str, key: str, timeout_sec: float) -> Dict[str, Any]:
    generated_at = _now_jst_naive().strftime("%Y-%m-%d %H:%M:%S")
    if not host:
        parsed = {
            "sections": {},
            "commands": {},
            "ibgateway_paths": [],
            "process_lines": [],
            "listen_lines": [],
            "unit_lines": [],
        }
        readiness = {
            "status": "LOCAL_PLAN",
            "blockers": [],
            "warnings": ["host_not_specified"],
            "capabilities": {
                "java": False,
                "headless_display": False,
                "remote_gui_access": False,
                "window_manager": False,
                "ibgateway_files": False,
                "ibgateway_running": False,
                "port_7497_listening": False,
            },
            "next_steps": [
                "VM host/keyを指定して読み取り専用チェックを実行する",
                "SETUP_NEEDEDならJava + headless GUI + IB Gateway配置を準備する",
            ],
        }
        return {
            "generated_at_jst": generated_at,
            "mode": "local_plan",
            "host": "",
            "user": user,
            "ssh": {"ok": False, "skipped": True, "error": "host未指定"},
            "parsed": parsed,
            "readiness": readiness,
            "safety": _safety_block(),
        }

    cmd = _ssh_command(host, user, key, timeout_sec)
    result = _run_local_command(cmd, timeout_sec + 3)
    parsed = _parse_remote_lines(result["stdout"]) if result["stdout"] else {
        "sections": {},
        "commands": {},
        "ibgateway_paths": [],
        "process_lines": [],
        "listen_lines": [],
        "unit_lines": [],
    }
    readiness = build_readiness(parsed, ssh_ok=bool(result["ok"]))
    return {
        "generated_at_jst": generated_at,
        "mode": "ssh_read_only",
        "host": host,
        "user": user,
        "ssh": {
            "ok": bool(result["ok"]),
            "returncode": result["returncode"],
            "error": (result["stderr"] or "").strip(),
        },
        "parsed": parsed,
        "readiness": readiness,
        "safety": _safety_block(),
    }


def _safety_block() -> Dict[str, bool]:
    return {
        "installs_packages": False,
        "starts_services": False,
        "opens_public_ports": False,
        "reads_or_prints_secrets": False,
        "places_orders": False,
    }


def write_report(report: Dict[str, Any], out_dir: Path) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    day8 = _now_jst_naive().strftime("%Y%m%d")
    json_path = out_dir / f"vm_ibkr_gateway_readiness_{day8}.json"
    md_path = out_dir / f"vm_ibkr_gateway_readiness_{day8}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def render_markdown(report: Dict[str, Any]) -> str:
    readiness = report.get("readiness") or {}
    caps = readiness.get("capabilities") or {}
    lines = [
        "# VM IB Gateway Readiness",
        "",
        f"- generated_at_jst: {report.get('generated_at_jst', '-')}",
        f"- host: {report.get('host') or '未指定'}",
        f"- status: {readiness.get('status', '-')}",
        "",
        "## Safety",
    ]
    for key, value in (report.get("safety") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Capabilities"])
    for key in [
        "java",
        "headless_display",
        "remote_gui_access",
        "window_manager",
        "ibgateway_files",
        "ibgateway_running",
        "port_7497_listening",
    ]:
        lines.append(f"- {key}: {caps.get(key)}")
    lines.extend(["", "## Blockers"])
    blockers = readiness.get("blockers") or []
    lines.extend([f"- {item}" for item in blockers] or ["- none"])
    lines.extend(["", "## Warnings"])
    warnings = readiness.get("warnings") or []
    lines.extend([f"- {item}" for item in warnings] or ["- none"])
    lines.extend(["", "## Next Steps"])
    next_steps = readiness.get("next_steps") or []
    lines.extend([f"- {item}" for item in next_steps] or ["- none"])
    lines.extend(
        [
            "",
            "## Recommended Tunnel Smoke",
            "```bash",
            "cd ~/trading_bot/trading_bot/MAIN",
            "./tools/open_vm_ibkr_tunnel.sh --host <VM_HOST> --key <SSH_KEY>",
            "python3 test_ibkr_connection.py --host 127.0.0.1 --port 17497 --client-id 1 --stocks AAPL,MSFT,NVDA,TSLA,QQQ,SPY --fx USDJPY",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only VM readiness check for moving IB Gateway.")
    ap.add_argument("--host", default="")
    ap.add_argument("--user", default=DEFAULT_REMOTE_USER)
    ap.add_argument("--key", default="")
    ap.add_argument("--timeout-sec", type=float, default=8.0)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--print-json", action="store_true")
    args = ap.parse_args()

    key = str(Path(args.key).expanduser()) if args.key else ""
    report = build_report(args.host, args.user, key, args.timeout_sec)
    paths = write_report(report, Path(args.out_dir))
    if args.print_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    status = (report.get("readiness") or {}).get("status", "UNKNOWN")
    print(f"vm_ibkr_gateway_readiness={status}")
    print(f"saved_json={paths['json']}")
    print(f"saved_md={paths['md']}")
    return 0 if status in {"LOCAL_PLAN", "READY_SMOKE", "SETUP_NEEDED", "NEEDS_REVIEW"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
