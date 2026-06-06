#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _run(cmd: List[str]) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 1, "", str(e)


def _tailscale_installed() -> bool:
    return shutil.which("tailscale") is not None


def _parse_scutil_status_output(text: str) -> Dict[str, Any]:
    src = str(text or "")
    connected = src.lstrip().startswith("Connected")

    def _match_first(pattern: str) -> str:
        m = re.search(pattern, src, flags=re.DOTALL)
        return str(m.group(1)).strip() if m else ""

    dns_name = _normalize_dns_name(
        _match_first(r"DNSSearchDomains\s*:\s*<array>\s*\{\s*0\s*:\s*([^\s}]+)")
        or _match_first(r"DNSSupplementalMatchDomains\s*:\s*<array>\s*\{\s*1\s*:\s*([^\s}]+)")
    )
    ipv4 = _match_first(r"IPv4\s*:\s*<dictionary>\s*\{.*?Addresses\s*:\s*<array>\s*\{\s*0\s*:\s*([0-9.]+)")
    ipv6 = _match_first(r"IPv6\s*:\s*<dictionary>\s*\{.*?Addresses\s*:\s*<array>\s*\{\s*0\s*:\s*([0-9a-fA-F:]+)")

    ips: List[str] = []
    for ip in (ipv4, ipv6):
        if ip and ip not in ips:
            ips.append(ip)

    return {
        "connected": connected,
        "dns_name": dns_name,
        "tailscale_ips": ips,
    }


def _load_scutil_status(service_names: List[str]) -> Dict[str, Any]:
    for service_name in service_names:
        rc, out, err = _run(["scutil", "--nc", "status", service_name])
        status = _parse_scutil_status_output(out or err or "")
        if status.get("connected"):
            return {
                "ok": True,
                "reason": "ok",
                "message": f"ok via scutil:{service_name}",
                "backend_state": "Running",
                "dns_name": status.get("dns_name", ""),
                "tailscale_ips": status.get("tailscale_ips", []),
                "service_name": service_name,
            }
    return {
        "ok": False,
        "reason": "tailscale_not_ready",
        "message": "No connected Tailscale VPN service found via scutil.",
    }


def _load_status_json() -> Dict[str, Any]:
    rc, out, err = _run(["tailscale", "status", "--json"])
    if rc != 0:
        raise RuntimeError((err or out or "tailscale status failed").strip())
    obj = json.loads(out)
    return obj if isinstance(obj, dict) else {}


def _normalize_dns_name(name: Any) -> str:
    s = str(name or "").strip()
    return s[:-1] if s.endswith(".") else s


def build_candidate_urls(port: int) -> Dict[str, Any]:
    if _tailscale_installed():
        try:
            st = _load_status_json()
            self_obj = st.get("Self", {}) if isinstance(st.get("Self"), dict) else {}
            backend_state = str(st.get("BackendState", "") or "").strip()
            dns_name = _normalize_dns_name(self_obj.get("DNSName"))

            ips: List[str] = []
            for x in self_obj.get("TailscaleIPs", []) if isinstance(self_obj.get("TailscaleIPs"), list) else []:
                s = str(x or "").strip()
                if s:
                    ips.append(s)

            base_urls: List[str] = []
            if dns_name:
                base_urls.append(f"http://{dns_name}:{port}")
            for ip in ips:
                base_urls.append(f"http://{ip}:{port}")

            seen = set()
            base_urls = [x for x in base_urls if not (x in seen or seen.add(x))]

            ok = bool(base_urls) and backend_state.lower() == "running"
            msg = "ok" if ok else f"tailscale backend state={backend_state or '-'}"

            return {
                "ok": ok,
                "reason": "ok" if ok else "tailscale_not_ready",
                "message": msg,
                "backend_state": backend_state,
                "dns_name": dns_name,
                "tailscale_ips": ips,
                "base_urls": base_urls,
                "widget_react_urls": [f"{x}/widget-react/index.html" for x in base_urls],
                "widget_react_scene_urls": {
                    "overview": [f"{x}/widget-react/index.html?scene=overview&native=1" for x in base_urls],
                    "reflection": [f"{x}/widget-react/index.html?scene=reflection&native=1" for x in base_urls],
                    "home": [f"{x}/widget-react/index.html?scene=home" for x in base_urls],
                    "lock": [f"{x}/widget-react/index.html?scene=lock" for x in base_urls],
                    "standby": [f"{x}/widget-react/index.html?scene=standby" for x in base_urls],
                },
                "widget_home_urls": [f"{x}/widget-home" for x in base_urls],
                "widget_app_urls": [f"{x}/widget-app" for x in base_urls],
                "dashboard_urls": [f"{x}/unified_dashboard.html" for x in base_urls],
            }
        except Exception:
            pass

    info = _load_scutil_status(["Tailscale 2", "Tailscale"])
    ips = [str(x) for x in info.get("tailscale_ips", []) if str(x or "").strip()]
    dns_name = _normalize_dns_name(info.get("dns_name"))
    base_urls: List[str] = []
    if dns_name:
        base_urls.append(f"http://{dns_name}:{port}")
    for ip in ips:
        base_urls.append(f"http://{ip}:{port}")
    seen = set()
    base_urls = [x for x in base_urls if not (x in seen or seen.add(x))]
    info["base_urls"] = base_urls
    info["widget_react_urls"] = [f"{x}/widget-react/index.html" for x in base_urls]
    info["widget_react_scene_urls"] = {
        "overview": [f"{x}/widget-react/index.html?scene=overview&native=1" for x in base_urls],
        "reflection": [f"{x}/widget-react/index.html?scene=reflection&native=1" for x in base_urls],
        "home": [f"{x}/widget-react/index.html?scene=home" for x in base_urls],
        "lock": [f"{x}/widget-react/index.html?scene=lock" for x in base_urls],
        "standby": [f"{x}/widget-react/index.html?scene=standby" for x in base_urls],
    }
    info["widget_home_urls"] = [f"{x}/widget-home" for x in base_urls]
    info["widget_app_urls"] = [f"{x}/widget-app" for x in base_urls]
    info["dashboard_urls"] = [f"{x}/unified_dashboard.html" for x in base_urls]
    info["dns_name"] = dns_name
    info["tailscale_ips"] = ips
    info["ok"] = bool(base_urls) and bool(info.get("ok"))
    return info


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Print candidate Tailscale URLs for the Ouroboros widget.")
    ap.add_argument("--port", type=int, default=8787, help="widget status server port (default: 8787)")
    ap.add_argument("--token", default="", help="widget token to include in sample parameter JSON")
    ap.add_argument("--print-json", action="store_true", help="print machine-readable JSON")
    args = ap.parse_args(argv)

    try:
        info = build_candidate_urls(port=int(args.port))
    except Exception as e:
        info = {
            "ok": False,
            "reason": "tailscale_status_failed",
            "message": str(e),
        }

    info["port"] = int(args.port)
    info["token"] = str(args.token or "")
    info["scriptable_parameter_json"] = json.dumps(
        {
            "baseUrls": info.get("base_urls", []),
            "token": str(args.token or ""),
        },
        ensure_ascii=False,
    )

    if args.print_json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info.get("ok") else 1

    if not info.get("ok"):
        print("[FAIL] Tailscale widget URLs are not ready.")
        print(f"reason={info.get('reason', '-')}")
        print(f"message={info.get('message', '-')}")
        print("")
        print("Do this first:")
        print("1. Install Tailscale on this Mac")
        print("2. Sign in on the Mac with the same account you will use on iPhone")
        print("3. Open Tailscale and allow the VPN / system extension prompts")
        print("4. Install Tailscale on iPhone and sign in with the same account")
        return 1

    print("[OK] Tailscale is ready for widget access.")
    print(f"backend_state={info.get('backend_state', '-')}")
    if info.get("dns_name"):
        print(f"dns_name={info.get('dns_name')}")
    if info.get("tailscale_ips"):
        print("tailscale_ips=" + ",".join(str(x) for x in info.get("tailscale_ips", [])))
    print("")
    print("Candidate widget base URLs:")
    for x in info.get("base_urls", []):
        print(f"- {x}/")
    print("")
    print("Candidate ZIP React widget URLs:")
    for x in info.get("widget_react_urls", []):
        print(f"- {x}")
    scene_urls = info.get("widget_react_scene_urls", {})
    if isinstance(scene_urls, dict):
        print("")
        print("Candidate ZIP React scene URLs:")
        for scene in ("overview", "reflection", "home", "lock", "standby"):
            for x in scene_urls.get(scene, []):
                print(f"- {scene}: {x}")
    print("")
    print("Candidate widget home URLs:")
    for x in info.get("widget_home_urls", []):
        print(f"- {x}")
    print("")
    print("Candidate widget app URLs:")
    for x in info.get("widget_app_urls", []):
        print(f"- {x}")
    print("")
    print("Candidate dashboard URLs:")
    for x in info.get("dashboard_urls", []):
        print(f"- {x}")
    print("")
    print("Scriptable widget Parameter:")
    print(info["scriptable_parameter_json"])
    print("")
    print("Recommended next step:")
    print("Set the Scriptable widget Parameter field to the JSON above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
