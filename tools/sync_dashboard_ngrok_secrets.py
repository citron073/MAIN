#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import List, Tuple


def _fetch_public_url(tunnels_url: str, timeout_sec: float = 2.0) -> str:
    req = urllib.request.Request(tunnels_url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_sec) as r:
        obj = json.loads(r.read().decode("utf-8", errors="replace"))
    for t in obj.get("tunnels", []):
        u = str(t.get("public_url", "")).strip()
        if u.startswith("https://"):
            return u.rstrip("/")
    return ""


def _normalize_redirect_line(uri: str) -> str:
    return f'redirect_uri = "{uri}/oauth2callback"'


def _upsert_redirect_uri(text: str, public_url: str) -> Tuple[str, bool]:
    redirect_line = _normalize_redirect_line(public_url)
    pat = re.compile(r'(?m)^\s*redirect_uri\s*=\s*"[^"]*"\s*$')
    if pat.search(text):
        new_text, n = pat.subn(redirect_line, text, count=1)
        return new_text, n > 0 and new_text != text

    auth_pat = re.compile(r'(?m)^\[auth\]\s*$')
    m = auth_pat.search(text)
    if m:
        insert_pos = m.end()
        prefix = text[:insert_pos]
        suffix = text[insert_pos:]
        if not suffix.startswith("\n"):
            suffix = "\n" + suffix
        new_text = prefix + "\n" + redirect_line + suffix
        return new_text, new_text != text

    hdr = "[auth]\n" + redirect_line + "\n\n"
    new_text = hdr + text
    return new_text, new_text != text


def _ensure_dashboard_branding(
    text: str,
    icon_path: str,
    app_title: str,
) -> Tuple[str, bool]:
    changed = False
    block_pat = re.compile(
        r'(?ms)^\[dashboard_branding\]\s*$.*?(?=^\[[^\n]+\]\s*$|\Z)'
    )
    m = block_pat.search(text)
    if m:
        block = m.group(0)
        add_lines: List[str] = []
        if not re.search(r'(?m)^\s*apple_touch_icon_path\s*=', block) and not re.search(
            r'(?m)^\s*apple_touch_icon_url\s*=', block
        ):
            add_lines.append(f'apple_touch_icon_path = "{icon_path}"')
        if not re.search(r'(?m)^\s*apple_mobile_web_app_title\s*=', block):
            add_lines.append(f'apple_mobile_web_app_title = "{app_title}"')
        if add_lines:
            if not block.endswith("\n"):
                block += "\n"
            block += "\n".join(add_lines) + "\n"
            text = text[: m.start()] + block + text[m.end() :]
            changed = True
        return text, changed

    append = (
        "\n[dashboard_branding]\n"
        f'apple_touch_icon_path = "{icon_path}"\n'
        f'apple_mobile_web_app_title = "{app_title}"\n'
    )
    if not text.endswith("\n"):
        text += "\n"
    text += append
    return text, True


def _restart_service(service_name: str) -> Tuple[bool, str]:
    try:
        cp = subprocess.run(
            ["systemctl", "restart", service_name],
            check=True,
            capture_output=True,
            text=True,
        )
        out = (cp.stdout or "").strip() or f"restarted {service_name}"
        return True, out
    except Exception as e:
        return False, str(e)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Sync ngrok public URL into .streamlit/secrets.toml redirect_uri (and optional branding defaults)."
    )
    ap.add_argument(
        "--secrets",
        default=str(Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"),
        help="Path to secrets.toml",
    )
    ap.add_argument(
        "--tunnels-url",
        default="http://127.0.0.1:4040/api/tunnels",
        help="ngrok local API endpoint",
    )
    ap.add_argument(
        "--public-url",
        default="",
        help="Explicit public URL (https://...) to use instead of querying ngrok API",
    )
    ap.add_argument(
        "--ensure-branding",
        action="store_true",
        default=False,
        help="Ensure [dashboard_branding] contains icon/title keys when missing",
    )
    ap.add_argument(
        "--icon-path",
        default=".streamlit/assets/apple-touch-icon.png",
        help="Default icon path used when --ensure-branding and key is missing",
    )
    ap.add_argument(
        "--app-title",
        default="Project Ouroboros",
        help="Default app title used when --ensure-branding and key is missing",
    )
    ap.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    ap.add_argument(
        "--restart-dashboard-service",
        action="store_true",
        help="Run systemctl restart for dashboard service after write",
    )
    ap.add_argument(
        "--service-name",
        default="ouroboros-dashboard.service",
        help="Systemd service name used with --restart-dashboard-service",
    )
    args = ap.parse_args()

    secrets_path = Path(args.secrets).expanduser().resolve()
    if not secrets_path.exists():
        print(f"[FAIL] secrets not found: {secrets_path}")
        return 2

    public_url = str(args.public_url or "").strip().rstrip("/")
    if public_url and not public_url.startswith("https://"):
        print(f"[FAIL] --public-url must start with https://, got: {public_url}")
        return 2
    if not public_url:
        try:
            public_url = _fetch_public_url(args.tunnels_url, timeout_sec=2.0)
        except Exception as e:
            print(f"[FAIL] ngrok API query failed: {e}")
            return 3
    if not public_url:
        print("[FAIL] no https ngrok tunnel found")
        return 4

    old_text = secrets_path.read_text(encoding="utf-8")
    text = old_text
    changed_any = False

    text, changed_redirect = _upsert_redirect_uri(text, public_url)
    changed_any = changed_any or changed_redirect

    changed_branding = False
    if args.ensure_branding:
        text, changed_branding = _ensure_dashboard_branding(text, args.icon_path, args.app_title)
        changed_any = changed_any or changed_branding

    redirect_uri = f"{public_url}/oauth2callback"
    print(f"[OK] public_url={public_url}")
    print(f"[OK] redirect_uri={redirect_uri}")

    if args.dry_run:
        print(
            "[DRYRUN] redirect_changed={} branding_changed={} write={}".format(
                changed_redirect, changed_branding, changed_any
            )
        )
        return 0

    if changed_any:
        secrets_path.write_text(text, encoding="utf-8")
        print(f"[OK] updated: {secrets_path}")
    else:
        print(f"[OK] no change: {secrets_path}")

    if args.restart_dashboard_service:
        ok, msg = _restart_service(args.service_name)
        if ok:
            print(f"[OK] {msg}")
        else:
            print(f"[WARN] restart failed: {msg}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
