#!/usr/bin/env python3
"""Ouroboros IBKR 週次評価スクリプト

100点 − 減点方式でIBKR米株ボットを評価し、安全範囲内でパラメータを自動調整する。
毎週日曜20時JST（systemdタイマー）に自動実行。
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_VERSION = "2026.05.12.1"

MAIN_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = MAIN_DIR.parent / "logs"
CONTROL_CSV = MAIN_DIR / "IBKR_CONTROL.csv"
REPORT_JSON = Path(__file__).resolve().parent / "ibkr_critic_report.json"
REPORT_MD   = Path(__file__).resolve().parent / "ibkr_critic_report.md"
HISTORY_JSONL = Path(__file__).resolve().parent / "ibkr_critic_history.jsonl"

JST = timezone(timedelta(hours=9))

# Safe auto-adjust bounds
SAFE_BOUNDS: Dict[str, Tuple[float, float]] = {
    "ibkr_tp_pct":             (0.3,  1.5),
    "ibkr_sl_pct":             (-0.5, -0.1),
    "ibkr_vix_block_threshold":(20.0, 40.0),
}

# Parameters that require human approval (never auto-change)
PROTECTED_PARAMS = {
    "ibkr_port", "ibkr_daily_loss_limit_usd", "ibkr_max_trades_per_day",
    "ibkr_shares", "ibkr_enabled",
}


def _now_jst() -> datetime:
    return datetime.now(JST).replace(tzinfo=None)


def _load_control() -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        for row in csv.DictReader(open(CONTROL_CSV, encoding="utf-8-sig")):
            k = str(row.get("key", "") or "").strip()
            if k:
                out[k] = str(row.get("value", "") or "").strip()
    except Exception:
        pass
    return out


def _save_control_param(key: str, value: str) -> None:
    rows = list(csv.DictReader(open(CONTROL_CSV, encoding="utf-8-sig")))
    for row in rows:
        if row["key"] == key:
            row["value"] = value
    import io
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=["key", "value"])
    w.writeheader()
    w.writerows(rows)
    CONTROL_CSV.write_text(out.getvalue(), encoding="utf-8")


def _get_week_range(week_start: Optional[str] = None) -> Tuple[str, str]:
    now = _now_jst()
    if week_start:
        d = datetime.strptime(week_start, "%Y%m%d")
    else:
        days_since_monday = now.weekday()
        d = now - timedelta(days=days_since_monday + 7)
    week_end = d + timedelta(days=6)
    return d.strftime("%Y%m%d"), week_end.strftime("%Y%m%d")


def _load_trade_logs(start: str, end: str) -> List[Dict]:
    trades = []
    d_start = datetime.strptime(start, "%Y%m%d")
    d_end   = datetime.strptime(end, "%Y%m%d")
    d = d_start
    while d <= d_end:
        log_path = LOGS_DIR / f"ibkr_trade_log_{d.strftime('%Y%m%d')}.csv"
        if log_path.exists():
            for row in csv.DictReader(open(log_path)):
                trades.append(dict(row))
        d += timedelta(days=1)
    return trades


def _analyze_trades(trades: List[Dict], ctrl: Dict) -> Dict[str, Any]:
    entries = [t for t in trades if t.get("result") in ("PAPER", "LIVE")]
    exits   = [t for t in trades if re.match(r"(PAPER|LIVE)_EXIT_", t.get("result", ""))]
    vix_blocks = [t for t in trades if t.get("result") == "VIX_BLOCK"]

    tp_count = sum(1 for t in exits if "_EXIT_TP" in t.get("result", ""))
    sl_count = sum(1 for t in exits if "_EXIT_SL" in t.get("result", ""))
    timeout_count = sum(1 for t in exits if "_EXIT_TIMEOUT" in t.get("result", ""))
    total_exits = len(exits)

    win_rate = tp_count / total_exits * 100 if total_exits > 0 else 0.0
    timeout_rate = timeout_count / total_exits * 100 if total_exits > 0 else 0.0

    # Estimate PnL from log notes
    total_pnl = 0.0
    for t in exits:
        note = t.get("note", "")
        m = re.search(r"current_fav=([-\d.]+)", note)
        if m:
            ret_pct = float(m.group(1))
            price = float(t.get("price", 0) or 0)
            shares = float(t.get("lot", 1) or 1)
            pnl_est = ret_pct / 100 * price * shares
            total_pnl += pnl_est

    # Trading days in range
    trading_days = 5  # assume 5-day week

    # Is live mode?
    is_live = ctrl.get("ibkr_port", "7497") == "7496"

    return {
        "total_entries": len(entries),
        "total_exits": total_exits,
        "tp_count": tp_count,
        "sl_count": sl_count,
        "timeout_count": timeout_count,
        "vix_block_count": len(vix_blocks),
        "win_rate": round(win_rate, 1),
        "timeout_rate": round(timeout_rate, 1),
        "estimated_pnl_usd": round(total_pnl, 2),
        "entries_per_day": round(len(entries) / trading_days, 1),
        "is_live": is_live,
        "trading_days": trading_days,
    }


def _score(analysis: Dict) -> Tuple[int, List[str]]:
    score = 100
    deductions = []

    exits = analysis["total_exits"]
    epd   = analysis["entries_per_day"]
    wr    = analysis["win_rate"]
    tr    = analysis["timeout_rate"]
    pnl   = analysis["estimated_pnl_usd"]

    # Trade frequency
    if epd < 0.2:
        score -= 25
        deductions.append("-25: 週1件未満（深刻な機会損失）")
    elif epd < 0.5:
        score -= 15
        deductions.append("-15: 週2.5件未満（過剰フィルター）")

    # Timeout rate
    if tr > 60:
        score -= 20
        deductions.append(f"-20: TIMEOUT率 {tr:.0f}% > 60%（TP/SL未到達が多すぎる）")
    elif tr > 40:
        score -= 12
        deductions.append(f"-12: TIMEOUT率 {tr:.0f}% > 40%")

    # Win rate (break-even for TP=0.5%, SL=-0.25% is ~33.3%)
    BREAK_EVEN = 33.3
    if wr < BREAK_EVEN - 5:
        score -= 15
        deductions.append(f"-15: WR {wr:.1f}% < ブレークイーブン({BREAK_EVEN:.1f}%)-5pt")
    elif wr < BREAK_EVEN:
        score -= 8
        deductions.append(f"-8: WR {wr:.1f}% < ブレークイーブン({BREAK_EVEN:.1f}%)")

    # PnL
    if pnl < 0:
        score -= 10
        deductions.append(f"-10: 推定PnL ${pnl:+.2f}（マイナス週）")

    # Sample size
    if exits < 5:
        score -= 5
        deductions.append(f"-5: サンプル{exits}件 < 5（統計不信頼）")

    return max(0, score), deductions


def _load_last_score() -> Optional[int]:
    if not HISTORY_JSONL.exists():
        return None
    lines = HISTORY_JSONL.read_text("utf-8").strip().splitlines()
    if not lines:
        return None
    last = json.loads(lines[-1])
    return last.get("score")


def _generate_proposals(analysis: Dict, ctrl: Dict, score: int) -> List[Dict]:
    proposals = []

    # If timeout rate is high → tighten TP (reduce)
    if analysis["timeout_rate"] > 50:
        cur = float(ctrl.get("ibkr_tp_pct", 0.5))
        new = round(max(SAFE_BOUNDS["ibkr_tp_pct"][0], cur - 0.1), 2)
        if new != cur:
            proposals.append({
                "param": "ibkr_tp_pct", "old": cur, "new": new,
                "reason": f"TIMEOUT率{analysis['timeout_rate']:.0f}%: TP目標を下げて早期利確",
            })

    # If win rate very low → widen SL (make less negative)
    if analysis["win_rate"] < 25 and analysis["total_exits"] >= 5:
        cur = float(ctrl.get("ibkr_sl_pct", -0.25))
        new = round(min(SAFE_BOUNDS["ibkr_sl_pct"][1], cur + 0.05), 2)
        if new != cur:
            proposals.append({
                "param": "ibkr_sl_pct", "old": cur, "new": new,
                "reason": f"WR{analysis['win_rate']:.1f}%: SLを少し緩めてノイズキャッチを減らす",
            })

    # If VIX blocks are frequent → lower threshold
    if analysis["vix_block_count"] > 10:
        cur = float(ctrl.get("ibkr_vix_block_threshold", 28))
        new = round(max(SAFE_BOUNDS["ibkr_vix_block_threshold"][0], cur - 2), 1)
        if new != cur:
            proposals.append({
                "param": "ibkr_vix_block_threshold", "old": cur, "new": new,
                "reason": f"VIXブロック{analysis['vix_block_count']}件: 閾値を下げてリスク時間を減らす",
            })

    return proposals[:3]


def _apply_changes(proposals: List[Dict], dry_run: bool) -> List[str]:
    applied = []
    for p in proposals:
        param = p["param"]
        old_val = str(p["old"])
        new_val = str(p["new"])
        if dry_run:
            applied.append(f"[DRY-RUN] {param}: {old_val} → {new_val} ({p['reason']})")
        else:
            _save_control_param(param, new_val)
            applied.append(f"{param}: {old_val} → {new_val} ({p['reason']})")
    return applied


def _scp_control(dry_run: bool) -> None:
    if dry_run:
        return
    ssh_key = "/Users/tani/Downloads/ssh-key-2026-03-04-4.key"
    vm_path = "ubuntu@161.33.26.35:/home/ubuntu/trading_bot/MAIN/IBKR_CONTROL.csv"
    local_path = str(CONTROL_CSV)
    try:
        subprocess.run(
            ["scp", "-i", ssh_key, local_path, vm_path],
            check=True, capture_output=True, timeout=30,
        )
    except Exception as e:
        print(f"[ibkr_critic] SCP failed: {e}")


def _write_report(
    week_start: str, week_end: str,
    analysis: Dict, score: int, last_score: Optional[int],
    deductions: List[str], proposals: List[Dict], applied: List[str],
    dry_run: bool,
) -> None:
    score_delta = (score - last_score) if last_score is not None else 0
    trend = "→ 前週と同等" if abs(score_delta) < 5 else (f"↑ +{score_delta}点" if score_delta > 0 else f"↓ {score_delta}点")
    mode_str = "LIVE" if analysis["is_live"] else "PAPER"

    report = {
        "version": SCRIPT_VERSION,
        "generated_at": _now_jst().strftime("%Y-%m-%dT%H:%M:%S"),
        "week_start": week_start,
        "week_end": week_end,
        "mode": mode_str,
        "score": score,
        "last_score": last_score,
        "score_delta": score_delta,
        "analysis": analysis,
        "deductions": deductions,
        "proposals": proposals,
        "applied": applied,
        "dry_run": dry_run,
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")

    # Append to history
    history_entry = {
        "week_start": week_start,
        "score": score,
        "win_rate": analysis["win_rate"],
        "entries_per_day": analysis["entries_per_day"],
        "estimated_pnl_usd": analysis["estimated_pnl_usd"],
        "mode": mode_str,
        "applied": applied,
        "date": _now_jst().strftime("%Y%m%d"),
    }
    with open(HISTORY_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(history_entry, ensure_ascii=False) + "\n")

    # Markdown verdict
    lines = [
        f"# Ouroboros IBKR 週次評価",
        f"",
        f"**期間:** {week_start[:4]}-{week_start[4:6]}-{week_start[6:]} – {week_end[:4]}-{week_end[4:6]}-{week_end[6:]}",
        f"**モード:** {mode_str}",
        f"**スコア:** {score}点 / 100点  （{trend}）",
        f"",
        f"## 取引サマリー",
        f"",
        f"| 指標 | 値 |",
        f"|------|-----|",
        f"| エントリー件数 | {analysis['total_entries']}件 |",
        f"| 1日平均 | {analysis['entries_per_day']}件/日 |",
        f"| 勝率 | {analysis['win_rate']:.1f}% (TP={analysis['tp_count']} SL={analysis['sl_count']} TO={analysis['timeout_count']}) |",
        f"| TIMEOUT率 | {analysis['timeout_rate']:.1f}% |",
        f"| VIXブロック | {analysis['vix_block_count']}件 |",
        f"| 推定PnL | ${analysis['estimated_pnl_usd']:+.2f} |",
        f"",
        f"## 減点内訳",
        f"",
    ]
    if deductions:
        for d in deductions:
            lines.append(f"- {d}")
    else:
        lines.append("- なし（満点）")

    lines += [
        f"",
        f"## 今週の変更",
        f"",
    ]
    if applied:
        for a in applied:
            lines.append(f"- {a}")
    else:
        lines.append(f"- なし（スコア{score}点: {'自動変更なし（70点以上）' if score >= 70 else '提案のみ'}）")

    if proposals and score >= 70:
        lines += [f"", f"## 提案（未適用）", f""]
        for p in proposals:
            lines.append(f"- {p['param']}: {p['old']} → {p['new']}  ({p['reason']})")

    REPORT_MD.write_text("\n".join(lines) + "\n", "utf-8")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=str, default=None,
                        help="評価週の月曜日 YYYYMMDD")
    parser.add_argument("--dry-run", action="store_true",
                        help="分析のみ、パラメータ変更なし")
    args = parser.parse_args()

    dry_run = args.dry_run
    week_start, week_end = _get_week_range(args.week)

    print(f"[ibkr_critic] v{SCRIPT_VERSION} 評価週: {week_start}–{week_end}")

    # Deduplication: skip if same week already evaluated today
    if HISTORY_JSONL.exists():
        today_str = _now_jst().strftime("%Y%m%d")
        for line in HISTORY_JSONL.read_text("utf-8").strip().splitlines():
            entry = json.loads(line)
            entry_week = entry.get("week_start", "").replace("-", "")
            entry_date = entry.get("date", "").replace("-", "")
            if entry_week == week_start and entry_date == today_str:
                print(f"[ibkr_critic] 既評価済み（{today_str}）: スキップ")
                return

    ctrl = _load_control()
    trades = _load_trade_logs(week_start, week_end)
    analysis = _analyze_trades(trades, ctrl)
    score, deductions = _score(analysis)
    last_score = _load_last_score()
    proposals = _generate_proposals(analysis, ctrl, score)

    # Apply only if score < 70 and not dry-run
    applied: List[str] = []
    if score < 70 and not dry_run:
        applied = _apply_changes(proposals, dry_run=False)
        if applied:
            _scp_control(dry_run=False)
    elif dry_run:
        applied = _apply_changes(proposals, dry_run=True)

    _write_report(week_start, week_end, analysis, score, last_score,
                  deductions, proposals, applied, dry_run)

    print(f"[ibkr_critic] スコア: {score}点 / 100点")
    for d in deductions:
        print(f"  {d}")
    for a in applied:
        print(f"  適用: {a}")

    # Print report path
    print(f"[ibkr_critic] レポート: {REPORT_JSON}")
    print(f"[ibkr_critic] Markdown: {REPORT_MD}")


if __name__ == "__main__":
    main()
