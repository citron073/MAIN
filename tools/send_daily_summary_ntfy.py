#!/usr/bin/env python3
"""Send daily trade summary to ntfy. Run after 17:30 (after trading window closes).

Called by ouroboros-daily-ci-check.service as ExecStartPost.
"""
from __future__ import annotations

import csv
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT.parent / "logs"
STATE_JSON = ROOT / "state.json"
CONTROL_CSV = ROOT / "CONTROL.csv"
SECRETS_TOML = ROOT / ".streamlit" / "secrets.toml"
OPS_CHECKS = ROOT / ".ops_checks.json"


def _read_toml_str(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            return v if v not in ("", "***MASKED***") else ""
    return ""


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _http_post(url: str, body: bytes, headers: Dict[str, str], timeout: float = 5.0) -> Tuple[bool, str]:
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)


def _build_summary(day8: str) -> str:
    log_f = LOGS_DIR / f"trade_log_{day8}.csv"
    state = _read_json(STATE_JSON)

    # Trade results
    tp = sl = smart_exit = obs_ok = ma_near = tw = ai_block = 0
    log_text = ""
    if log_f.exists():
        log_text = log_f.read_text(encoding="utf-8", errors="ignore")
        for r in csv.reader(log_text.splitlines()):
            if len(r) < 2:
                continue
            res = r[1]
            if "TP" in res and "EXIT" in res:
                tp += 1
            if "SL" in res and "EXIT" in res:
                sl += 1
            if res == "OBSERVE_OK":
                obs_ok += 1
            if "FAST_MA_NEAR" in res:
                ma_near += 1
            if res == "OBSERVE_TREND_STRENGTH_WEAK":
                tw += 1
            if res == "OBSERVE_AI_BLOCK":
                ai_block += 1
        smart_exit = (
            log_text.count("exit_tech=NEAR_TP_GIVEBACK")
            + log_text.count("exit_tech=PROGRESS_REVERSAL")
            + log_text.count("exit_tech=WEAK_PROGRESS")
            + log_text.count("exit_tech=NO_FOLLOW_THROUGH")
        )

    total = tp + sl + smart_exit
    closed = tp + sl
    wr_str = f"{tp/closed*100:.0f}%" if closed > 0 else "N/A"

    # Risk state (fix: use _risk_realized_jpy, not _risk_daily_loss_jpy)
    collateral = state.get("_risk_day_start_jpy", 0) or 0
    realized_jpy = state.get("_risk_realized_jpy", 0) or 0
    realized_pct = state.get("_risk_realized_pct", 0.0) or 0.0
    streak = state.get("_streak_consecutive_losses", state.get("_streak_losses", 0)) or 0
    streak_stop = bool(state.get("_streak_stop"))

    # 7-day WR
    today_dt = datetime.strptime(day8, "%Y%m%d")
    week_tp = week_sl = 0
    for i in range(7):
        d = today_dt - timedelta(days=i)
        f = LOGS_DIR / f"trade_log_{d.strftime('%Y%m%d')}.csv"
        if not f.exists():
            continue
        for r in csv.reader(f.open(encoding="utf-8", errors="ignore")):
            if len(r) < 2:
                continue
            if "TP" in r[1] and "EXIT" in r[1]:
                week_tp += 1
            if "SL" in r[1] and "EXIT" in r[1]:
                week_sl += 1
    week_total = week_tp + week_sl
    week_wr = f"{week_tp/week_total*100:.0f}%" if week_total > 0 else "N/A"

    # Status emoji
    pnl_sign = "+" if realized_jpy >= 0 else ""
    status = "✅" if realized_jpy > 0 else "⚠️" if closed > 0 else "📭"
    if streak_stop:
        status = "🛑"

    smart_str = f"  🚪スマート出口={smart_exit}" if smart_exit > 0 else ""
    lines = [
        f"{status} Ouroboros 日次サマリー {day8[:4]}/{day8[4:6]}/{day8[6:]}",
        "",
        f"PnL: {pnl_sign}{realized_jpy:,.0f}¥ ({pnl_sign}{realized_pct:.3f}%)",
        f"本日 TP={tp} SL={sl} WR={wr_str}{smart_str}",
        f"7日WR={week_wr} ({week_tp}勝{week_sl}敗) | OBSERVE={obs_ok} MA近={ma_near} AI={ai_block}",
        f"証拠金={collateral:,.0f}¥  連敗={streak}",
    ]
    if streak_stop:
        lines.append("🛑 連敗ストップ発動中")

    return "\n".join(lines)


def main() -> int:
    day8 = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")
    ntfy_url = _read_toml_str(SECRETS_TOML, "ntfy_topic_url")
    if not ntfy_url:
        print("[skip] ntfy_topic_url not configured")
        return 0

    body = _build_summary(day8)
    print(f"[ntfy] sending daily summary for {day8}")
    print(body)

    headers: Dict[str, str] = {
        "Content-Type": "text/plain; charset=utf-8",
        "Title": f"Ouroboros {day8}",
        "Tags": "chart_with_upwards_trend",
        "Priority": "default",
    }
    bearer = _read_toml_str(SECRETS_TOML, "ntfy_bearer_token")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    ok, msg = _http_post(ntfy_url, body.encode("utf-8"), headers)
    if ok:
        print(f"[OK] ntfy sent: {msg}")
    else:
        print(f"[WARN] ntfy failed: {msg}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
