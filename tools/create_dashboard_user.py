#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AUTH_PATH = ROOT / ".streamlit" / "dashboard_auth.json"


def _safe_int(v: Any, default: int) -> int:
    try:
        return int(float(str(v).strip()))
    except Exception:
        return default


def _safe_bool(v: Any, default: bool) -> bool:
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


def _auth_mode_norm(v: Any) -> str:
    s = str(v or "").strip().upper()
    if s in {"LOCAL", "OIDC", "AUTO"}:
        return s
    if s in {"APPLE", "APPLE_OIDC"}:
        return "OIDC"
    return "AUTO"


def _read_json_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            return obj
    except Exception:
        return {}
    return {}


def _write_json_dict(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _pbkdf2_hash(password: str, salt: bytes, iterations: int) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, max(100_000, int(iterations)))
    return base64.b64encode(dk).decode("ascii")


def _ask_password_interactive() -> str:
    p1 = getpass.getpass("new password: ")
    if len(p1) < 12:
        raise SystemExit("password must be at least 12 characters")
    p2 = getpass.getpass("confirm password: ")
    if p1 != p2:
        raise SystemExit("password confirmation mismatch")
    return p1


def _normalize_config(obj: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(obj) if isinstance(obj, dict) else {}
    users = obj.get("users")
    if not isinstance(users, list):
        users = []
    cfg["enabled"] = _safe_bool(cfg.get("enabled", True), True)
    cfg["mode"] = _auth_mode_norm(cfg.get("mode", "AUTO"))
    cfg["oidc_provider"] = str(cfg.get("oidc_provider", "apple") or "apple").strip()
    cfg["session_timeout_min"] = max(5, _safe_int(cfg.get("session_timeout_min", 30), 30))
    cfg["max_failures"] = max(1, _safe_int(cfg.get("max_failures", 5), 5))
    cfg["lock_minutes"] = max(1, _safe_int(cfg.get("lock_minutes", 10), 10))
    cfg["allow_breakglass_in_auto"] = _safe_bool(cfg.get("allow_breakglass_in_auto", True), True)
    cfg["breakglass_daily_limit"] = max(1, _safe_int(cfg.get("breakglass_daily_limit", 3), 3))
    cfg["users"] = [u for u in users if isinstance(u, dict)]
    return cfg


def upsert_user(
    cfg: Dict[str, Any],
    username: str,
    password: str,
    iterations: int,
) -> Dict[str, Any]:
    users: List[Dict[str, Any]] = list(cfg.get("users", []))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    salt = secrets.token_bytes(16)
    rec = {
        "username": username,
        "salt": base64.b64encode(salt).decode("ascii"),
        "password_hash": _pbkdf2_hash(password, salt, iterations),
        "iterations": int(iterations),
        "updated_at": now,
    }
    idx = None
    for i, u in enumerate(users):
        if str(u.get("username", "")).strip() == username:
            idx = i
            break
    if idx is None:
        rec["created_at"] = now
        users.append(rec)
    else:
        prev = users[idx]
        rec["created_at"] = str(prev.get("created_at", now))
        users[idx] = rec
    cfg["users"] = users
    return cfg


def main() -> int:
    ap = argparse.ArgumentParser(description="Create/update dashboard login user (password is PBKDF2-hashed).")
    ap.add_argument("--username", required=True, help="login username")
    ap.add_argument("--password", default=None, help="optional plain password (use prompt when omitted)")
    ap.add_argument("--auth-file", default=str(DEFAULT_AUTH_PATH), help=f"default: {DEFAULT_AUTH_PATH}")
    ap.add_argument("--iterations", type=int, default=310000, help="PBKDF2 iterations (default: 310000)")
    ap.add_argument("--session-timeout-min", type=int, default=30)
    ap.add_argument("--max-failures", type=int, default=5)
    ap.add_argument("--lock-minutes", type=int, default=10)
    ap.add_argument("--mode", choices=["LOCAL", "OIDC", "AUTO"], default=None, help="auth mode override")
    ap.add_argument("--oidc-provider", default=None, help="OIDC provider name (default: apple)")
    ap.add_argument("--allow-breakglass-in-auto", choices=["0", "1"], default=None)
    ap.add_argument("--breakglass-daily-limit", type=int, default=None)
    args = ap.parse_args()

    username = str(args.username).strip()
    if not username:
        raise SystemExit("username is empty")

    password = args.password if args.password is not None else _ask_password_interactive()
    if len(password) < 12:
        raise SystemExit("password must be at least 12 characters")

    auth_file = Path(args.auth_file).expanduser().resolve()
    cfg = _normalize_config(_read_json_dict(auth_file))
    cfg["enabled"] = True
    if args.mode:
        cfg["mode"] = _auth_mode_norm(args.mode)
    if args.oidc_provider:
        cfg["oidc_provider"] = str(args.oidc_provider).strip() or "apple"
    cfg["session_timeout_min"] = max(5, int(args.session_timeout_min))
    cfg["max_failures"] = max(1, int(args.max_failures))
    cfg["lock_minutes"] = max(1, int(args.lock_minutes))
    if args.allow_breakglass_in_auto is not None:
        cfg["allow_breakglass_in_auto"] = bool(int(args.allow_breakglass_in_auto))
    if args.breakglass_daily_limit is not None:
        cfg["breakglass_daily_limit"] = max(1, int(args.breakglass_daily_limit))
    cfg = upsert_user(cfg, username=username, password=password, iterations=max(100000, int(args.iterations)))
    _write_json_dict(auth_file, cfg)

    print(f"[OK] user saved: {username}")
    print(f"[OK] auth file: {auth_file}")
    print(f"[INFO] users={len(cfg.get('users', []))} timeout={cfg['session_timeout_min']}min lock={cfg['lock_minutes']}min")
    print(f"[INFO] mode={cfg.get('mode', 'AUTO')} oidc_provider={cfg.get('oidc_provider', 'apple')}")
    print(
        "[INFO] breakglass: allow_in_auto={} daily_limit={}".format(
            cfg.get("allow_breakglass_in_auto", True),
            cfg.get("breakglass_daily_limit", 3),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
