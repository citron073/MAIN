#!/usr/bin/env python3
"""
Ouroboros BTC Critic — weekly automated performance evaluator.
Runs on VM every Sunday JST 20:00 via systemd timer.
Outputs a JSON report + markdown summary to tools/critic_report.json.
"""

import csv, json, re, glob, os, subprocess, sys
from datetime import datetime, timedelta, timezone
from collections import defaultdict

JST = timezone(timedelta(hours=9))
LOGS_DIR = "/home/ubuntu/trading_bot/logs"
SHADOW_LOGS_DIR = "/home/ubuntu/trading_bot/logs/instances/shadow"
CONTROL_CSV = "/home/ubuntu/trading_bot/MAIN/CONTROL.csv"
REPORT_JSON = "/home/ubuntu/trading_bot/MAIN/tools/critic_report.json"
REPORT_MD   = "/home/ubuntu/trading_bot/MAIN/tools/critic_report.md"
CRITIC_HISTORY = "/home/ubuntu/trading_bot/MAIN/tools/critic_history.jsonl"

TP_PCT   = 0.220
SL_PCT   = 0.140
BE_WR    = SL_PCT / (SL_PCT + TP_PCT) * 100   # 38.9%

# --- safe auto-adjust bounds ---
SAFE_BOUNDS = {
    "buy_fast_ma_distance_pct":  (0.04, 0.10),
    "sell_fast_ma_distance_pct": (0.06, 0.12),
    "win_min":                   (60,   150),
}
# hours the critic is NEVER allowed to unblock automatically
HARD_BLOCK_HOURS = {14, 16}


# ──────────────────────────────────────────────────────────────────────────────
# Data loading
# ──────────────────────────────────────────────────────────────────────────────

def load_control():
    ctrl = {}
    try:
        with open(CONTROL_CSV) as f:
            for row in csv.DictReader(f):
                ctrl[row["key"]] = row["value"]
    except Exception as e:
        print(f"[critic] WARNING: could not read CONTROL.csv: {e}")
    return ctrl

def last_week_dates():
    """Return Mon–Fri dates of the most recently completed trading week."""
    today = datetime.now(JST)
    # go back to last Friday
    days_since_friday = (today.weekday() - 4) % 7
    last_friday = today - timedelta(days=days_since_friday)
    week = []
    for i in range(4, -1, -1):
        d = last_friday - timedelta(days=i)
        if d.weekday() < 5:
            week.append(d.strftime("%Y%m%d"))
    return week

def load_trades(dates, directory=LOGS_DIR):
    rows = []
    for d in dates:
        fp = f"{directory}/trade_log_{d}.csv"
        try:
            with open(fp) as f:
                for row in csv.DictReader(f):
                    rows.append(dict(row))
        except FileNotFoundError:
            pass
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# Analysis
# ──────────────────────────────────────────────────────────────────────────────

def is_closed(res):
    return any(x in res for x in [
        "EXIT_TP", "EXIT_SL", "EXIT_TIMEOUT",
        "EXIT_WEAK", "EXIT_REVERSAL", "EXIT_GIVEBACK",
        "EXIT_NFT", "EXIT_ADVERSE", "EXIT_TECH",
    ])

def is_win(res):
    return "EXIT_TP" in res

def is_timeout(res):
    return "EXIT_TIMEOUT" in res

def is_sl(res):
    return "EXIT_SL" in res

def analyze(rows):
    closed = [r for r in rows if is_closed(r.get("result", ""))]
    skips  = defaultdict(int)
    obs    = defaultdict(int)
    for r in rows:
        res = r.get("result", "")
        if "SKIP" in res:   skips[res] += 1
        if "OBSERVE" in res: obs[res]  += 1

    total   = len(closed)
    wins    = sum(1 for r in closed if is_win(r["result"]))
    sls     = sum(1 for r in closed if is_sl(r["result"]))
    timeouts = sum(1 for r in closed if is_timeout(r["result"]))
    smart   = total - wins - sls - timeouts

    wr_vs_sl = wins / (wins + sls) * 100 if (wins + sls) > 0 else None
    wr_all   = wins / total * 100 if total > 0 else 0

    holds = []
    by_hr = defaultdict(lambda: [0, 0])   # [wins, total]
    for r in closed:
        t  = r.get("time", "")
        hr = int(t[11:13]) if len(t) > 12 else -1
        if hr >= 0:
            by_hr[hr][1] += 1
            if is_win(r["result"]):
                by_hr[hr][0] += 1
        m = re.search(r"hold_min=([\d.]+)", r.get("note", ""))
        if m:
            holds.append(float(m.group(1)))

    avg_hold = sum(holds) / len(holds) if holds else None

    # estimated PnL
    est_pnl = wins * TP_PCT - sls * SL_PCT - timeouts * 0.02 - smart * 0.03

    return {
        "total": total,
        "wins":  wins,
        "sls":   sls,
        "timeouts": timeouts,
        "smart": smart,
        "wr_vs_sl": wr_vs_sl,
        "wr_all": wr_all,
        "avg_hold_min": avg_hold,
        "est_pnl_pct": est_pnl,
        "timeout_rate": timeouts / total if total else 0,
        "by_hour": {str(h): {"wins": v[0], "total": v[1]} for h, v in sorted(by_hr.items())},
        "skips": dict(sorted(skips.items(), key=lambda x: -x[1])[:8]),
        "observes": dict(sorted(obs.items(), key=lambda x: -x[1])[:8]),
    }

def shadow_hour_wr(dates):
    """Get shadow WR by hour for the last week using shadow logs."""
    rows = load_trades(dates, directory=SHADOW_LOGS_DIR)
    by_hr = defaultdict(lambda: [0, 0])
    for r in rows:
        res = r.get("result", "")
        if not is_closed(res): continue
        t  = r.get("time", "")
        hr = int(t[11:13]) if len(t) > 12 else -1
        if hr >= 0:
            by_hr[hr][1] += 1
            if is_win(res):
                by_hr[hr][0] += 1
    return {h: {"wins": v[0], "total": v[1], "wr": v[0]/v[1]*100} for h, v in by_hr.items() if v[1] >= 5}


# ──────────────────────────────────────────────────────────────────────────────
# Scoring (100点 - 減点)
# ──────────────────────────────────────────────────────────────────────────────

def score(stats, n_days=5):
    deductions = []
    score = 100

    # --- trade volume ---
    per_day = stats["total"] / n_days if n_days else 0
    if per_day < 1.0:
        d = 25; deductions.append(("取引件数が極端に少ない（%d件/週）" % stats["total"], d))
    elif per_day < 2.0:
        d = 15; deductions.append(("取引件数が少ない（%.1f件/日）" % per_day, d))
    elif per_day < 3.0:
        d = 5; deductions.append(("取引件数がやや少ない（%.1f件/日）" % per_day, d))
    score -= sum(x[1] for x in deductions[-1:])

    # --- timeout rate ---
    tr = stats["timeout_rate"]
    if tr > 0.60:
        d = 20; deductions.append(("TIMEOUT率が高すぎる（%.0f%%）" % (tr*100), d))
    elif tr > 0.40:
        d = 12; deductions.append(("TIMEOUT率が高い（%.0f%%）" % (tr*100), d))
    elif tr > 0.25:
        d = 5; deductions.append(("TIMEOUTがやや多い（%.0f%%）" % (tr*100), d))
    score -= sum(x[1] for x in deductions[-1:])

    # --- WR vs break-even ---
    wr = stats.get("wr_vs_sl")
    if wr is None:
        deductions.append(("SLゼロのためWR計算不能（SL件数が不足）", 0))
    elif wr < BE_WR - 5:
        d = 15; deductions.append(("WR %.1f%% はBE(%.1f%%)を大きく下回る" % (wr, BE_WR), d))
        score -= d
    elif wr < BE_WR:
        d = 8; deductions.append(("WR %.1f%% はBE(%.1f%%)をわずかに下回る" % (wr, BE_WR), d))
        score -= d
    else:
        deductions.append(("WR %.1f%% > BE %.1f%% ✓" % (wr, BE_WR), 0))

    # --- PnL ---
    pnl = stats["est_pnl_pct"]
    if pnl < -0.3:
        d = 10; deductions.append(("推定PnL %+.3f%% — 損失週" % pnl, d)); score -= d
    elif pnl < 0:
        d = 5; deductions.append(("推定PnL %+.3f%% — 小幅マイナス" % pnl, d)); score -= d
    else:
        deductions.append(("推定PnL %+.3f%% ✓" % pnl, 0))

    # --- sample size penalty ---
    if stats["total"] < 10:
        d = 5; deductions.append(("サンプル不足（%d件）— 統計的信頼性低" % stats["total"], d)); score -= d

    score = max(0, min(100, score))
    return score, deductions


# ──────────────────────────────────────────────────────────────────────────────
# Recommendations
# ──────────────────────────────────────────────────────────────────────────────

def recommendations(stats, ctrl, shadow_hr):
    recs = []

    # --- fast_ma_distance too tight ---
    obs = stats.get("observes", {})
    fast_ma_blocks = obs.get("OBSERVE_BUY_FAST_MA_NEAR", 0) + obs.get("OBSERVE_SELL_FAST_MA_NEAR", 0)
    if fast_ma_blocks > 30:
        buy_d  = float(ctrl.get("buy_fast_ma_distance_pct", 0.08))
        sell_d = float(ctrl.get("sell_fast_ma_distance_pct", 0.10))
        new_buy  = max(SAFE_BOUNDS["buy_fast_ma_distance_pct"][0],  round(buy_d - 0.02, 2))
        new_sell = max(SAFE_BOUNDS["sell_fast_ma_distance_pct"][0], round(sell_d - 0.02, 2))
        recs.append({
            "priority": 1,
            "title": "fast_ma_distance を緩和（機会損失%d件）" % fast_ma_blocks,
            "changes": {
                "buy_fast_ma_distance_pct":  (buy_d,  new_buy),
                "sell_fast_ma_distance_pct": (sell_d, new_sell),
            },
            "auto_apply": True,
        })

    # --- timeout rate high ---
    if stats["timeout_rate"] > 0.40 and stats["total"] >= 5:
        wm = int(ctrl.get("win_min", 120))
        new_wm = max(SAFE_BOUNDS["win_min"][0], wm - 15)
        if new_wm != wm:
            recs.append({
                "priority": 2,
                "title": "win_min 短縮（TIMEOUT率%.0f%%）" % (stats["timeout_rate"] * 100),
                "changes": {"win_min": (wm, new_wm)},
                "auto_apply": True,
            })

    # --- hour unblock candidates from shadow ---
    blocked_str = ctrl.get("no_paper_hours", "")
    blocked = {int(h.strip()) for h in blocked_str.replace('"','').split(",") if h.strip().isdigit()}
    unblock_candidates = []
    for hr, s in shadow_hr.items():
        if hr in blocked and hr not in HARD_BLOCK_HOURS and s["wr"] >= BE_WR and s["total"] >= 10:
            unblock_candidates.append((hr, s["wr"], s["total"]))
    if unblock_candidates:
        hrs_str = ",".join(str(h) for h, _, _ in unblock_candidates)
        new_blocked = blocked - {h for h, _, _ in unblock_candidates}
        new_blocked_str = '"' + ",".join(str(h) for h in sorted(new_blocked)) + '"'
        detail = ", ".join(f"{h}h WR{w:.0f}%({n}件)" for h, w, n in unblock_candidates)
        recs.append({
            "priority": 3,
            "title": f"ブロック解除候補: {hrs_str}h — シャドウWR良好 ({detail})",
            "changes": {"no_paper_hours": (blocked_str, new_blocked_str)},
            "auto_apply": False,   # requires human review
        })

    return recs


# ──────────────────────────────────────────────────────────────────────────────
# Apply changes to CONTROL.csv
# ──────────────────────────────────────────────────────────────────────────────

def apply_control_changes(changes: dict):
    try:
        with open(CONTROL_CSV) as f:
            lines = f.readlines()

        applied = []
        for i, line in enumerate(lines):
            for key, (old, new) in changes.items():
                if line.startswith(f"{key},"):
                    lines[i] = f"{key},{new}\n"
                    applied.append((key, old, new))
                    break

        with open(CONTROL_CSV, "w") as f:
            f.writelines(lines)
        return applied
    except Exception as e:
        print(f"[critic] ERROR applying changes: {e}")
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Report generation
# ──────────────────────────────────────────────────────────────────────────────

def write_markdown(report):
    s    = report["score"]
    stats = report["stats"]
    dates = report["dates"]
    recs  = report["recommendations"]
    applied = report.get("applied_changes", [])

    lines = [
        f"# Ouroboros BTC 週次評価レポート",
        f"",
        f"**評価期間**: {dates[0]} – {dates[-1]}  |  **スコア: {s}点 / 100点**",
        f"",
        f"## 成績サマリー",
        f"",
        f"| 項目 | 値 |",
        f"|------|----|",
        f"| クローズ件数 | {stats['total']}件 |",
        f"| TP / SL / TIMEOUT / スマート | {stats['wins']} / {stats['sls']} / {stats['timeouts']} / {stats['smart']} |",
        f"| WR (TP vs SL) | {('%.1f%%' % stats['wr_vs_sl']) if stats['wr_vs_sl'] is not None else 'N/A (SLなし)'} |",
        f"| TIMEOUT率 | {stats['timeout_rate']*100:.0f}% |",
        f"| 推定PnL | {stats['est_pnl_pct']:+.3f}% |",
        f"| 平均保有時間 | {('%.0f分' % stats['avg_hold_min']) if stats['avg_hold_min'] else 'N/A'} |",
        f"",
        f"## 減点内訳",
        f"",
    ]
    for label, pts in report["deductions"]:
        if pts > 0:
            lines.append(f"- **-{pts}点**: {label}")
        else:
            lines.append(f"- ✅ {label}")

    lines += ["", "## 改善提案", ""]
    for rec in recs:
        auto = "（自動適用済み）" if rec.get("auto_apply") else "（要人間確認）"
        lines.append(f"### P{rec['priority']}: {rec['title']} {auto}")
        for k, (old, new) in rec["changes"].items():
            lines.append(f"- `{k}`: {old} → **{new}**")
        lines.append("")

    if applied:
        lines += ["## 自動適用した変更", ""]
        for key, old, new in applied:
            lines.append(f"- `{key}`: {old} → {new}")
        lines.append("")

    lines += [
        f"---",
        f"*生成: {datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')} by Ouroboros BTC Critic*",
    ]

    with open(REPORT_MD, "w") as f:
        f.write("\n".join(lines))
    print(f"[critic] Report written to {REPORT_MD}")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now(JST)
    dates = last_week_dates()
    print(f"[critic] Evaluating week: {dates[0]} – {dates[-1]}")

    rows   = load_trades(dates)
    stats  = analyze(rows)
    shadow = shadow_hour_wr(dates)
    ctrl   = load_control()

    s, deductions = score(stats, n_days=len(dates))
    recs = recommendations(stats, ctrl, shadow)

    # Auto-apply safe recommendations
    # Skip if this week's changes were already applied (history check)
    applied = []
    already_changed_this_week = False
    try:
        # week_start in YYYYMMDD; history uses YYYY-MM-DD — normalise to YYYYMMDD for comparison
        week_start_yyyymmdd = dates[0] if dates else ""
        with open(CRITIC_HISTORY) as f:
            for line in f:
                entry = json.loads(line)
                entry_week = entry.get("week_start", entry.get("date", "")).replace("-", "")
                if entry_week == week_start_yyyymmdd and entry.get("applied_count", 0) > 0:
                    already_changed_this_week = True
                    break
    except FileNotFoundError:
        pass

    if already_changed_this_week:
        print(f"[critic] Skipping auto-apply — changes already applied this week")
    elif s < 80:
        auto_changes = {}
        for rec in recs:
            if rec.get("auto_apply"):
                # Only apply if current value actually matches the old value (no manual override)
                for k, (old, new) in rec["changes"].items():
                    current = ctrl.get(k, "")
                    if str(current) == str(old):
                        auto_changes[k] = (old, new)
                    else:
                        print(f"[critic] Skipping {k}: current={current} != expected={old} (manual override detected)")
        if auto_changes:
            print(f"[critic] Auto-applying {len(auto_changes)} change(s)...")
            applied = apply_control_changes(auto_changes)
            for key, old, new in applied:
                print(f"  {key}: {old} → {new}")

    report = {
        "generated_at": now.isoformat(),
        "dates": dates,
        "score": s,
        "stats": stats,
        "deductions": deductions,
        "recommendations": recs,
        "applied_changes": applied,
        "shadow_by_hour": {str(k): v for k, v in shadow.items()},
    }

    with open(REPORT_JSON, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"[critic] JSON report → {REPORT_JSON}")

    write_markdown(report)

    # Append to history
    with open(CRITIC_HISTORY, "a") as f:
        f.write(json.dumps({
            "date": now.date().isoformat(),
            "week_start": dates[0] if dates else "",
            "score": s,
            "total_trades": stats["total"],
            "applied_count": len(applied),
        }) + "\n")

    print(f"[critic] Score: {s}/100 | Trades: {stats['total']} | Auto-applied: {len(applied)}")
    return s

if __name__ == "__main__":
    sys.exit(0 if main() >= 60 else 1)
