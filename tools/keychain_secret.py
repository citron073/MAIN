from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

_LINUX_SECRETS_FILE = "/etc/ouroboros/secrets.env"
_linux_secrets_loaded = False


def _load_linux_secrets_env_file(path: str = _LINUX_SECRETS_FILE) -> None:
    """Load key=value pairs from a systemd EnvironmentFile into os.environ.

    Only sets vars not already present. Called once on non-Darwin AUTO path so
    that live_preflight and ci_check work without manually sourcing the file.
    """
    global _linux_secrets_loaded
    if _linux_secrets_loaded:
        return
    _linux_secrets_loaded = True
    p = Path(path)
    if not p.exists():
        return
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
                v = v[1:-1]
            elif len(v) >= 2 and v[0] == "'" and v[-1] == "'":
                v = v[1:-1]
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass


class KeychainError(RuntimeError):
    pass


def read_generic_password(service: str, account: str) -> str:
    """
    Read a secret from macOS Keychain:
      security find-generic-password -s <service> -a <account> -w
    """
    cmd = [
        "security",
        "find-generic-password",
        "-s",
        str(service),
        "-a",
        str(account),
        "-w",
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "unknown keychain error").strip()
        raise KeychainError(err)
    return (p.stdout or "").strip()


def read_pair(service: str, account_key: str, account_secret: str) -> tuple[str, str]:
    api_key, api_secret, _ = read_pair_with_source(
        service=service,
        account_key=account_key,
        account_secret=account_secret,
    )
    return api_key, api_secret


def _provider_name(raw: Optional[str]) -> str:
    s = str(raw or "AUTO").strip().upper()
    if s in ("AUTO", "KEYCHAIN", "ENV"):
        return s
    return "AUTO"


def _env_name_candidates(kind: str, account_name: str) -> list[str]:
    k = str(kind).strip().upper()
    if k == "KEY":
        defaults = [
            "OUROBOROS_BITFLYER_API_KEY",
            "BITFLYER_API_KEY",
            "OUROBOROS_API_KEY",
        ]
    else:
        defaults = [
            "OUROBOROS_BITFLYER_API_SECRET",
            "BITFLYER_API_SECRET",
            "OUROBOROS_API_SECRET",
        ]

    out: list[str] = []
    for n in defaults:
        if n not in out:
            out.append(n)

    acc = str(account_name or "").strip()
    if acc:
        for n in (acc, acc.upper()):
            if n and n not in out:
                out.append(n)
    return out


def _read_env_secret(candidates: list[str], label: str) -> str:
    for name in candidates:
        v = os.getenv(name)
        if v:
            return str(v).strip()
    tried = ", ".join(candidates)
    raise KeychainError(f"missing {label} in environment. tried: {tried}")


def read_pair_from_env(account_key: str, account_secret: str) -> tuple[str, str]:
    key_names = _env_name_candidates("KEY", account_key)
    sec_names = _env_name_candidates("SECRET", account_secret)
    api_key = _read_env_secret(key_names, "api key")
    api_secret = _read_env_secret(sec_names, "api secret")
    if not api_key or not api_secret:
        raise KeychainError("empty api key/secret from environment")
    return api_key, api_secret


def read_pair_with_source(service: str, account_key: str, account_secret: str) -> tuple[str, str, str]:
    """
    Read API key/secret by provider policy.

    Provider selection (`OUROBOROS_SECRET_PROVIDER`):
      - AUTO (default): macOS -> KEYCHAIN first, otherwise ENV first
      - KEYCHAIN: force macOS Keychain
      - ENV: force environment variables
    """
    provider = _provider_name(os.getenv("OUROBOROS_SECRET_PROVIDER"))

    if provider == "KEYCHAIN":
        k = read_generic_password(service=service, account=account_key)
        s = read_generic_password(service=service, account=account_secret)
        if not k or not s:
            raise KeychainError("empty api key/secret from keychain")
        return k, s, "KEYCHAIN"

    if provider == "ENV":
        k, s = read_pair_from_env(account_key=account_key, account_secret=account_secret)
        return k, s, "ENV"

    # AUTO: keep existing macOS behavior first; use ENV for cloud/Linux.
    if sys.platform == "darwin":
        try:
            k = read_generic_password(service=service, account=account_key)
            s = read_generic_password(service=service, account=account_secret)
            if k and s:
                return k, s, "KEYCHAIN"
        except Exception:
            pass
        k, s = read_pair_from_env(account_key=account_key, account_secret=account_secret)
        return k, s, "ENV"

    _load_linux_secrets_env_file()
    try:
        k, s = read_pair_from_env(account_key=account_key, account_secret=account_secret)
        return k, s, "ENV"
    except Exception as env_error:
        if shutil.which("security") is None:
            raise env_error
        k = read_generic_password(service=service, account=account_key)
        s = read_generic_password(service=service, account=account_secret)
        if not k or not s:
            raise KeychainError("empty api key/secret from keychain")
        return k, s, "KEYCHAIN"


def secret_provider() -> str:
    return _provider_name(os.getenv("OUROBOROS_SECRET_PROVIDER"))


def safe_read_generic_password(service: str, account: str) -> Optional[str]:
    try:
        return read_generic_password(service=service, account=account)
    except Exception:
        return None
