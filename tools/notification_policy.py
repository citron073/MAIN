#!/usr/bin/env python3
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Optional, Tuple

LEVEL_INFO = "INFO"
LEVEL_WARN = "WARN"
LEVEL_CRITICAL = "CRITICAL"

LEVEL_PRIORITY = {
    LEVEL_INFO: "default",
    LEVEL_WARN: "high",
    LEVEL_CRITICAL: "high",
}

LEVEL_TAGS = {
    LEVEL_INFO: "info",
    LEVEL_WARN: "warning",
    LEVEL_CRITICAL: "rotating_light",
}

LEVEL_COOLDOWN_SEC = {
    LEVEL_INFO: 0,
    LEVEL_WARN: 30 * 60,
    LEVEL_CRITICAL: 10 * 60,
}


def normalize_level(level: str) -> str:
    raw = str(level or "").strip().upper()
    if raw in (LEVEL_INFO, LEVEL_WARN, LEVEL_CRITICAL):
        return raw
    return LEVEL_INFO


def priority_for_level(level: str) -> str:
    return str(LEVEL_PRIORITY.get(normalize_level(level), "default"))


def tags_for_level(level: str, extra_tags: str = "") -> str:
    base = str(LEVEL_TAGS.get(normalize_level(level), "info"))
    extra = [s.strip() for s in str(extra_tags or "").split(",") if s.strip()]
    out = [base]
    for tag in extra:
        if tag not in out:
            out.append(tag)
    return ",".join(out)


def safe_ntfy_title(title: str, fallback: str = "Ouroboros Notification") -> str:
    safe = str(title or "").encode("latin-1", errors="ignore").decode("latin-1").strip()
    return safe or fallback


def read_toml_str(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            return value if value not in ("", "***MASKED***") else ""
    return ""


def build_ntfy_headers(title: str, *, level: str = LEVEL_INFO, tags: str = "", bearer: str = "") -> Dict[str, str]:
    headers: Dict[str, str] = {
        "Content-Type": "text/plain; charset=utf-8",
        "Title": safe_ntfy_title(title),
        "Priority": priority_for_level(level),
        "Tags": tags_for_level(level, tags),
    }
    bearer = str(bearer or "").strip()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return headers


def _read_state(path: Path) -> Dict[str, float]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(path: Path, payload: Dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def cooldown_sec_for_level(level: str) -> int:
    return int(LEVEL_COOLDOWN_SEC.get(normalize_level(level), 0))


def should_send(state_path: Path, event_code: str, *, level: str = LEVEL_INFO, cooldown_sec: Optional[int] = None, now_ts: Optional[float] = None) -> Tuple[bool, int]:
    event_code = str(event_code or "").strip()
    if not event_code:
        return True, 0
    now = float(now_ts if now_ts is not None else time.time())
    cd = max(0, int(cooldown_sec if cooldown_sec is not None else cooldown_sec_for_level(level)))
    if cd <= 0:
        return True, 0
    state = _read_state(state_path)
    if event_code not in state:
        return True, 0
    last_ts = float(state.get(event_code, 0.0) or 0.0)
    if last_ts <= 0.0:
        return True, 0
    remaining = int(max(0.0, (last_ts + cd) - now))
    return remaining <= 0, remaining


def mark_sent(state_path: Path, event_code: str, *, now_ts: Optional[float] = None) -> None:
    event_code = str(event_code or "").strip()
    if not event_code:
        return
    now = float(now_ts if now_ts is not None else time.time())
    state = _read_state(state_path)
    state[event_code] = now
    _write_state(state_path, state)


def post_ntfy(
    url: str,
    title: str,
    body: str,
    *,
    level: str = LEVEL_INFO,
    tags: str = "",
    bearer: str = "",
    timeout: float = 8.0,
    state_path: Optional[Path] = None,
    event_code: str = "",
    cooldown_sec: Optional[int] = None,
) -> Tuple[bool, str]:
    url = str(url or "").strip()
    if not url:
        return False, "no_url"
    if state_path and event_code:
        allowed, remaining = should_send(state_path, event_code, level=level, cooldown_sec=cooldown_sec)
        if not allowed:
            return True, f"cooldown:{remaining}s"
    headers = build_ntfy_headers(title, level=level, tags=tags, bearer=bearer)
    try:
        req = urllib.request.Request(url, data=str(body).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            msg = f"HTTP {getattr(resp, 'status', 200)}"
        if state_path and event_code:
            mark_sent(state_path, event_code)
        return True, msg
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, str(exc)
