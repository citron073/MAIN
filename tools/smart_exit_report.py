#!/usr/bin/env python3
"""Smart exit effectiveness report.

Matches PAPER_EXIT_TIMEOUT / PAPER_EXIT_EARLY_ADVERSE rows from trade_log
against ai_training_log.csv via pos_id to retrieve ret_pct, hold_min, best_fav (MFE).

Usage:
  python3 tools/smart_exit_report.py [--days N] [--ntfy]
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT.parent / "logs"
AI_LOG = LOGS_DIR / "ai_training_log.csv"
SECRETS_TOML = ROOT / ".streamlit" / "secrets.toml"
NOTIFY_STATE = ROOT / ".streamlit" / "notification_policy_state.json"

try:
    from tools.notification_policy import LEVEL_INFO, post_ntfy, read_toml_str
except ModuleNotFoundError:
    sys.path.insert(0, str(ROOT))
    from tools.notification_policy import LEVEL_INFO, post_ntfy, read_toml_str  # type: ignore

SMART_KEYS = [
    "NEAR_TP_GIVEBACK",
    "PROGRESS_REVERSAL",
    "WEAK_PROGRESS",
    "NO_FOLLOW_THROUGH",
    "EARLY_ADVERSE",
]
SMART_LABELS = {
    "NEAR_TP_GIVEBACK":   "NearTP返却      ",
    "PROGRESS_REVERSAL":  "進行中反転      ",
    "WEAK_PROGRESS":      "弱進行          ",
    "NO_FOLLOW_THROUGH":  "フォロースルーなし",
    "EARLY_ADVERSE":      "早期逆行        ",
}
EXIT_TECH_RE = re.compile(r"exit_tech=(\S+)")

def _load_ai_log() -> Dict[str, Dict[str, Any]]:
    """Return {pos_id: {ret_pct, hold_min, best_fav}} from ai_training_log.csv."""
    data: Dict[str, Dict[str, Any]] = {}
    if not AI_LOG.exists():
        return data
    try:
        with AI_LOG.open(encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                pid = str(row.get("pos_id", "")).strip()
                if not pid:
                    continue
                try:
                    rp = float(row.get("ret_pct") or 0)
                except ValueError:
                    rp = 0.0
                try:
                    hm = float(row.get("hold_min") or 0)
                except ValueError:
                    hm = 0.0
                try:
                    bf = float(row.get("best_fav") or 0)
                except ValueError:
                    bf = 0.0
                data[pid] = {"ret_pct": rp, "hold_min": hm, "best_fav": bf}
    except Exception:
        pass
    return data


def _analyse(lookback_days: int = 30) -> Dict[str, Any]:
    today = datetime.now().date()
    cutoff = today - timedelta(days=lookback_days)
    ai_data = _load_ai_log()

    smart: Dict[str, Dict[str, Any]] = {
        k: {"n": 0, "rets": [], "hold_mins": [], "mfes": [], "no_ret": 0}
        for k in SMART_KEYS + ["TP", "SL", "TIMEOUT_OTHER", "EOD"]
    }
    total_exits = 0

    for i in range(lookback_days):
        d = cutoff + timedelta(days=i + 1)
        log = LOGS_DIR / f"trade_log_{d.strftime('%Y%m%d')}.csv"
        if not log.exists():
            continue
        try:
            with log.open(encoding="utf-8", errors="replace") as f:
                for row in csv.DictReader(f):
                    result = str(row.get("result", "")).strip()
                    if "EXIT" not in result:
                        continue
                    total_exits += 1
                    note = str(row.get("note", ""))
                    pos_id = str(row.get("pos_id", "")).strip()
                    ai_row = ai_data.get(pos_id)
                    ret_pct = ai_row["ret_pct"] if ai_row else None
                    hold_min = ai_row["hold_min"] if ai_row else None
                    mfe = ai_row["best_fav"] if ai_row else None

                    # EARLY_ADVERSE is its own result type (not TIMEOUT)
                    if result == "PAPER_EXIT_EARLY_ADVERSE":
                        key = "EARLY_ADVERSE"
                    else:
                        m = EXIT_TECH_RE.search(note)
                        if m:
                            key = m.group(1)
                            if key not in smart:
                                key = "TIMEOUT_OTHER"
                        elif "PAPER_EXIT_TP" in result:
                            key = "TP"
                        elif "PAPER_EXIT_SL" in result:
                            key = "SL"
                        elif "PAPER_EXIT_EOD" in result or "PAPER_EXIT_TIMEOUT" in result:
                            key = "EOD"
                        else:
                            key = "TIMEOUT_OTHER"

                    if key not in smart:
                        smart[key] = {"n": 0, "rets": [], "hold_mins": [], "mfes": [], "no_ret": 0}
                    smart[key]["n"] += 1
                    if ret_pct is not None:
                        smart[key]["rets"].append(ret_pct)
                    else:
                        smart[key]["no_ret"] = smart[key].get("no_ret", 0) + 1
                    if hold_min is not None:
                        smart[key]["hold_mins"].append(hold_min)
                    if mfe is not None:
                        smart[key]["mfes"].append(mfe)
        except Exception:
            continue

    return {"by_type": smart, "total_exits": total_exits, "lookback_days": lookback_days}


def _avg(vals: List[float]) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def _format_report(data: Dict[str, Any]) -> str:
    by_type = data["by_type"]
    total_exits = data["total_exits"]
    days = data["lookback_days"]

    tp_n = by_type.get("TP", {}).get("n", 0)
    sl_n = by_type.get("SL", {}).get("n", 0)
    smart_total = sum(by_type.get(k, {}).get("n", 0) for k in SMART_KEYS)
    eod_n = by_type.get("EOD", {}).get("n", 0)

    if tp_n + sl_n > 0:
        trade_wr = tp_n / (tp_n + sl_n) * 100
        wr_str = f"{trade_wr:.0f}%"
    else:
        wr_str = "N/A"

    lines = [
        f"スマート出口効果レポート（過去{days}日）",
        "",
        f"総EXIT: {total_exits}件  TP: {tp_n}件  SL: {sl_n}件  EOD: {eod_n}件  WR: {wr_str}  スマート: {smart_total}件",
        "",
        f"{'種別':<22}  件数  avg_ret    WR     avg_hold  avg_MFE",
        "-" * 64,
    ]

    all_smart_rets: List[float] = []
    for k in SMART_KEYS:
        d = by_type.get(k, {"n": 0, "rets": [], "hold_mins": [], "mfes": []})
        n = d["n"]
        label = SMART_LABELS[k]
        if n == 0:
            lines.append(f"  {label}  0件   -          -      -         -")
            continue
        rets = d["rets"]
        hmins = d.get("hold_mins", [])
        mfes = d.get("mfes", [])
        if rets:
            avg_r = _avg(rets) * 100  # type: ignore[operator]
            win_n = sum(1 for r in rets if r > 0)
            wr = win_n / len(rets) * 100
            icon = "✓" if avg_r > 0 else "!"
            avg_h = f"{_avg(hmins):.0f}m" if hmins else "-"
            avg_m = f"{_avg(mfes)*100:.3f}%" if mfes else "-"  # type: ignore[operator]
            lines.append(
                f"  {icon} {label}  {n:3d}件  {avg_r:+.3f}%  {wr:.0f}%"
                f"  {avg_h:>7}  {avg_m}"
            )
            all_smart_rets.extend(rets)
        else:
            lines.append(f"  {label}  {n:3d}件  (ret不明)")

    # TP/SL baseline for comparison
    lines += ["-" * 64]
    for baseline_key, label in [("TP", "TP確定          "), ("SL", "SL確定          ")]:
        bd = by_type.get(baseline_key, {"n": 0, "rets": [], "hold_mins": [], "mfes": []})
        bn = bd["n"]
        if bn == 0:
            lines.append(f"    {label}  0件   -")
            continue
        brets = bd["rets"]
        bhmins = bd.get("hold_mins", [])
        bmfes = bd.get("mfes", [])
        if brets:
            bavg = _avg(brets) * 100  # type: ignore[operator]
            bwr = sum(1 for r in brets if r > 0) / len(brets) * 100
            bh = f"{_avg(bhmins):.0f}m" if bhmins else "-"
            bm = f"{_avg(bmfes)*100:.3f}%" if bmfes else "-"  # type: ignore[operator]
            lines.append(f"    {label}  {bn:3d}件  {bavg:+.3f}%  {bwr:.0f}%  {bh:>7}  {bm}")
        else:
            lines.append(f"    {label}  {bn:3d}件  (ret不明)")

    if all_smart_rets:
        avg_all = _avg(all_smart_rets) * 100  # type: ignore[operator]
        win_all = sum(1 for r in all_smart_rets if r > 0)
        wr_all = win_all / len(all_smart_rets) * 100
        lines += [
            "-" * 64,
            f"  スマート合計  {smart_total}件  avg={avg_all:+.3f}%  WR={wr_all:.0f}%",
        ]

    if total_exits == 0:
        lines.append("(データなし: EXIT ログが存在しません)")

    return "\n".join(lines)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--ntfy", action="store_true")
    args = parser.parse_args()

    data = _analyse(lookback_days=args.days)
    report = _format_report(data)
    print(report)

    if args.ntfy:
        ntfy_url = _read_toml_str(SECRETS_TOML, "ntfy_topic_url")
        if not ntfy_url:
            print("[skip] ntfy_topic_url not configured")
            return 0
        bearer = _read_toml_str(SECRETS_TOML, "ntfy_bearer_token")
        ok, msg = post_ntfy(
            ntfy_url,
            f"Smart Exit Report {datetime.now().strftime('%Y/%m/%d')}",
            report,
            level=LEVEL_INFO,
            tags="brain,smart_exit",
            bearer=bearer,
            state_path=NOTIFY_STATE,
            event_code=f"smart_exit_report_{args.days}_{datetime.now().strftime('%Y%m%d')}",
        )
        print(f"[{'OK' if ok else 'WARN'}] ntfy {msg}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
