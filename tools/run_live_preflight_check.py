#!/usr/bin/env python3
"""Standalone live_preflight runner — writes result to .ops_checks.json.

Runs daily at 09:45 JST (00:45 UTC) via ouroboros-live-preflight.timer,
independent of morning_start_guard so the check always runs even when bot
is already active.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

ROOT = Path(__file__).resolve().parent.parent
OPS_CHECKS = ROOT / ".ops_checks.json"
SECRETS_ENV = Path("/etc/ouroboros/secrets.env")


def _load_env_from_secrets(env: Dict[str, str]) -> None:
    if not SECRETS_ENV.exists():
        return
    try:
        for raw in SECRETS_ENV.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            k = key.strip()
            if not k:
                continue
            try:
                parsed = shlex.split(value.strip(), posix=True)
                env[k] = parsed[0] if parsed else ""
            except Exception:
                env[k] = value.strip().strip("\"'")
    except Exception:
        pass


def _run_preflight() -> Tuple[bool, str]:
    import os
    env = os.environ.copy()
    _load_env_from_secrets(env)
    try:
        cp = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "live_preflight.py")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=30,
        )
    except Exception as e:
        return False, str(e)
    text = (cp.stdout or "") + ("\n" + cp.stderr if cp.stderr else "")
    tail = " | ".join([ln.strip() for ln in text.splitlines()[-3:] if ln.strip()])
    return cp.returncode == 0, tail or f"rc={cp.returncode}"


def _write_ops(ok: bool, msg: str) -> None:
    ops: Dict[str, Any] = {}
    if OPS_CHECKS.exists():
        try:
            ops = json.loads(OPS_CHECKS.read_text(encoding="utf-8"))
        except Exception:
            pass
    now_ts = time.time()
    ops["live_preflight"] = {
        "title": "live_preflight",
        "rc": 0 if ok else 1,
        "ok": ok,
        "updated_ts": now_ts,
        "updated_at": datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d %H:%M:%S"),
        "cmd": str(ROOT / "tools" / "live_preflight.py"),
        "output": msg[:300],
    }
    tmp = OPS_CHECKS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ops, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(OPS_CHECKS)


def main() -> int:
    print(f"[live_preflight] running at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    ok, msg = _run_preflight()
    status = "OK" if ok else "FAIL"
    print(f"[live_preflight] {status}: {msg}")
    _write_ops(ok, msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
