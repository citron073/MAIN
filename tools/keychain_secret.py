from __future__ import annotations

import subprocess
from typing import Optional


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
    api_key = read_generic_password(service=service, account=account_key)
    api_secret = read_generic_password(service=service, account=account_secret)
    if not api_key or not api_secret:
        raise KeychainError("empty api key/secret from keychain")
    return api_key, api_secret


def safe_read_generic_password(service: str, account: str) -> Optional[str]:
    try:
        return read_generic_password(service=service, account=account)
    except Exception:
        return None
