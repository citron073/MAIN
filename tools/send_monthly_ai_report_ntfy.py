#!/usr/bin/env python3
"""Monthly AI training log report via ntfy. Run on the 1st of each month.

Reads logs/ai_training_log.csv, groups by month, and sends a performance
summary (WR, PF, avg_ret, sample count) via ntfy.
"""
from __future__ import annotations

import csv
import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MAIN_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = MAIN_DIR.parent / "logs"
AI_LOG = LOGS_DIR / "ai_training_log.csv"
SECRETS_TOML = MAIN_DIR / ".streamlit" / "secrets.toml"


def _read_toml_str(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            return v if v not in ("", "***MASKED***") else ""
    return ""


def _http_post(url: str, body: bytes, headers: Dict[str, str]) -> Tuple[bool, str]:
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8) as r:
            return True, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)


def _build_report(lookback_months: int = 6) -> str:
    if not AI_LOG.exists():
        return "[skip] ai_training_log.csv not found"

    by_month: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "win": 0, "win_ret": 0.0, "loss_ret": 0.0, "total_ret": 0.0}
    )

    with AI_LOG.open(encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # use exit_time if available, else time
            t_str = row.get("exit_time") or row.get("time") or ""
            if len(t_str) < 7:
                continue
            month_key = t_str[:7]  # YYYY-MM

            outcome = str(row.get("outcome") or "").strip().upper()
            ret_raw = row.get("ret_pct")
            try:
                ret = float(ret_raw or 0)
            except ValueError:
                ret = 0.0

            by_month[month_key]["n"] += 1
            by_month[month_key]["total_ret"] += ret
            if outcome in ("TP", "WIN") or ret > 0:
                by_month[month_key]["win"] += 1
                by_month[month_key]["win_ret"] += ret
            elif outcome in ("SL", "LOSS") or ret < 0:
                by_month[month_key]["loss_ret"] += ret

    if not by_month:
        return "[skip] no samples in ai_training_log.csv"

    today = date.today()
    current_ym = today.strftime("%Y-%m")
    # include only months up to last month (current month may be incomplete)
    months = sorted(by_month.keys())[-lookback_months - 1:]
    months = [m for m in months if m < current_ym]

    rows: List[str] = []
    for m in months:
        d = by_month[m]
        n = d["n"]
        win = d["win"]
        wr = win / n * 100 if n else 0.0
        avg_ret = d["total_ret"] / n * 100 if n else 0.0
        pf_str = "-"
        if d["loss_ret"] < 0 and d["win_ret"] > 0:
            pf = d["win_ret"] / abs(d["loss_ret"])
            pf_str = f"{pf:.2f}"
        trend = "✅" if wr >= 44 else "⚠️" if wr >= 38 else "❌"
        rows.append(
            f"{trend} {m}  WR={wr:.0f}%  PF={pf_str}  avg={avg_ret:+.3f}%  n={n}"
        )

    # summary: last 3 months combined
    recent_months = months[-3:]
    rc_n = rc_win = 0
    rc_ret = 0.0
    for m in recent_months:
        d = by_month[m]
        rc_n += d["n"]
        rc_win += d["win"]
        rc_ret += d["total_ret"]
    rc_wr = rc_win / rc_n * 100 if rc_n else 0.0
    rc_avg = rc_ret / rc_n * 100 if rc_n else 0.0

    lines = [
        f"📊 Ouroboros 月次AIレポート {today.strftime('%Y/%m')}",
        "",
        *rows,
        "",
        f"直近3ヶ月合計: WR={rc_wr:.0f}% avg={rc_avg:+.3f}% N={rc_n}",
    ]
    return "\n".join(lines)


def main() -> int:
    today = date.today()
    force = "--force" in sys.argv

    if today.day != 1 and not force:
        print(f"[skip] today={today}, not 1st of month. Use --force to run.")
        return 0

    report = _build_report(lookback_months=6)
    print(report)

    ntfy_url = _read_toml_str(SECRETS_TOML, "ntfy_topic_url")
    if not ntfy_url:
        print("[skip] ntfy_topic_url not configured")
        return 0

    headers: Dict[str, str] = {
        "Content-Type": "text/plain; charset=utf-8",
        "Title": f"Ouroboros Monthly AI Report {today.strftime('%Y/%m')}",
        "Tags": "bar_chart",
        "Priority": "default",
    }
    bearer = _read_toml_str(SECRETS_TOML, "ntfy_bearer_token")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    ok, msg = _http_post(ntfy_url, report.encode("utf-8"), headers)
    print(f"[{'OK' if ok else 'WARN'}] ntfy {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
