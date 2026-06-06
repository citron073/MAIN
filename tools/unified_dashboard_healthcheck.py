#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "http://127.0.0.1:8793/tools/unified_dashboard.html"
RUNTIME_PATH = ROOT / "review_out" / "unified_dashboard_runtime.json"


def resolve_default_url() -> str:
    try:
        payload = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_URL
    if not isinstance(payload, dict):
        return DEFAULT_URL
    for key in ("healthcheck_url", "local_url", "url"):
        value = str(payload.get(key, "") or "").strip()
        if value:
            return value
    return DEFAULT_URL


def _now_jst_naive() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            out.append(value)
    return out


def _score(status_code: int, latency_ms: float | None) -> int:
    if status_code == 200:
        if latency_ms is not None and latency_ms <= 1500:
            return 100
        if latency_ms is not None and latency_ms <= 5000:
            return 85
        return 75
    if 200 <= status_code < 500:
        return 60
    if status_code:
        return 30
    return 0


def check_url(url: str, timeout_sec: float) -> Dict[str, Any]:
    started = time.monotonic()
    req = Request(url, method="HEAD", headers={"Cache-Control": "no-cache"})
    try:
        with urlopen(req, timeout=timeout_sec) as res:
            status_code = int(getattr(res, "status", 0) or 0)
            content_length = res.headers.get("Content-Length", "")
            error = ""
    except HTTPError as exc:
        status_code = int(exc.code)
        content_length = ""
        error = str(exc)
    except URLError as exc:
        status_code = 0
        content_length = ""
        error = str(exc.reason)
    except Exception as exc:
        status_code = 0
        content_length = ""
        error = str(exc)
    latency_ms = round((time.monotonic() - started) * 1000, 1)
    return {
        "url": url,
        "ok": status_code == 200,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "content_length": content_length,
        "error": error,
        "score": _score(status_code, latency_ms),
    }


def build_report(url: str, timeout_sec: float, history_path: Path) -> Dict[str, Any]:
    now = _now_jst_naive()
    current = check_url(url, timeout_sec)
    history = _read_jsonl(history_path)
    cutoff = now - timedelta(days=7)
    recent = []
    for item in history:
        ts = str(item.get("checked_at_jst", ""))
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if dt >= cutoff:
            recent.append(item)
    recent_with_current = recent + [{"dashboard": current}]
    total = len(recent_with_current)
    ok_n = sum(1 for item in recent_with_current if (item.get("dashboard") or {}).get("ok") is True)
    uptime_pct = round((ok_n / total * 100.0) if total else 0.0, 1)
    return {
        "checked_at_jst": now.strftime("%Y-%m-%d %H:%M:%S"),
        "day8": now.strftime("%Y%m%d"),
        "dashboard": current,
        "rolling_7d": {
            "sample_n": total,
            "ok_n": ok_n,
            "uptime_pct": uptime_pct,
            "score": round(uptime_pct),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Log and score the iPhone Unified Dashboard health.")
    ap.add_argument("--url", default=resolve_default_url())
    ap.add_argument("--timeout-sec", type=float, default=5.0)
    ap.add_argument("--out-dir", default=str(ROOT / "review_out"))
    ap.add_argument(
        "--log-sandbox-errors",
        action="store_true",
        help="Also persist local sandbox permission failures. Default is to avoid polluting uptime history.",
    )
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    history_path = out_dir / "unified_dashboard_health_history.jsonl"
    report = build_report(args.url, args.timeout_sec, history_path)
    dashboard = report.get("dashboard") or {}
    is_local_permission_error = (
        dashboard.get("status_code") == 0
        and "Operation not permitted" in str(dashboard.get("error", ""))
    )
    if is_local_permission_error and not args.log_sandbox_errors:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("skipped_history_append: local sandbox permission error")
        return 1
    day_path = out_dir / f"unified_dashboard_health_{report['day8']}.json"
    day_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "unified_dashboard_health_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["dashboard"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
