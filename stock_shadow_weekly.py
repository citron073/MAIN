#!/usr/bin/env python3
"""
Stock Shadow Weekly Summary — weekly P&L report for shadow trading bot.

Reads stock_shadow_state.json + last N days of CSV logs, computes weekly stats,
and sends via ntfy/webhook if configured in .streamlit/secrets.toml.
Falls back to writing review_out/stock_shadow_weekly.txt if no notifier configured.

Usage:
    python3 stock_shadow_weekly.py                   # send weekly summary
    python3 stock_shadow_weekly.py --dry-run         # print only, no send
    python3 stock_shadow_weekly.py --days 7          # window in days (default: 7)
"""
from __future__ import annotations

import csv
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
REVIEW_OUT = ROOT / "review_out"
STATE_FILE = REVIEW_OUT / "stock_shadow_state.json"
SECRETS_FILE = ROOT / ".streamlit" / "secrets.toml"
WEEKLY_OUT = REVIEW_OUT / "stock_shadow_weekly.txt"
NOTIFY_STATE = ROOT / ".streamlit" / "notification_policy_state.json"

try:
    from tools.notification_policy import LEVEL_CRITICAL, LEVEL_INFO, post_ntfy
except ModuleNotFoundError:
    sys.path.insert(0, str(ROOT))
    from tools.notification_policy import LEVEL_CRITICAL, LEVEL_INFO, post_ntfy  # type: ignore

# Live readiness thresholds
READINESS_MIN_TRADES = 100
READINESS_MIN_WR = 0.46
READINESS_MAX_DD = -30.0    # USD


def _now_jst() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


def _now_jst_str() -> str:
    return _now_jst().strftime("%Y-%m-%d %H:%M:%S")


# ── Load data ─────────────────────────────────────────────────────────────────

def _load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _load_recent_trades(days: int = 7) -> List[Dict[str, str]]:
    cutoff = _now_jst() - timedelta(days=days)
    rows: List[Dict[str, str]] = []
    for f in sorted(REVIEW_OUT.glob("stock_shadow_*.csv")):
        try:
            with f.open(encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    ts_str = row.get("timestamp_jst", "")
                    try:
                        ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                        if ts >= cutoff:
                            rows.append(dict(row))
                    except ValueError:
                        pass
        except Exception:
            pass
    return rows


# ── Compute stats ─────────────────────────────────────────────────────────────

def compute_weekly_stats(rows: List[Dict[str, str]], days: int) -> Dict[str, Any]:
    from collections import defaultdict
    buys = sells = holds = 0
    wins = losses = 0
    total_pnl = 0.0
    pnl_by_symbol: Dict[str, float] = {}
    stop_loss_count = 0

    by_sym: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for r in rows:
        by_sym[r.get("symbol", "")].append(r)

    pnl_direct_count = 0    # AE: trades with pnl_usd in CSV (commission-accurate)
    pnl_estimated_count = 0  # AE: trades where pnl was estimated from entry/exit prices

    for sym, sym_rows in by_sym.items():
        pending: Optional[Dict[str, str]] = None
        for r in sym_rows:
            a = r.get("action", "")
            if a == "BUY":
                buys += 1
                pending = r
            elif a == "SELL":
                sells += 1
                if r.get("reason") in ("STOP_LOSS", "BREAKEVEN_SL"):
                    stop_loss_count += 1
                pnl_str = r.get("pnl_usd", "")
                if pnl_str not in ("", None):
                    try:
                        pnl = float(pnl_str)
                        pnl_direct_count += 1
                    except ValueError:
                        pnl = 0.0
                elif pending:
                    try:
                        pnl = (float(r["price"]) - float(pending["price"])) * int(r.get("quantity", 1))
                        pnl_estimated_count += 1
                    except (KeyError, ValueError):
                        pnl = 0.0
                else:
                    pnl = 0.0
                total_pnl += pnl
                pnl_by_symbol[sym] = round(pnl_by_symbol.get(sym, 0.0) + pnl, 2)
                if pnl > 0:
                    wins += 1
                else:
                    losses += 1
                pending = None
            elif a == "HOLD":
                holds += 1

    completed = wins + losses
    wr = wins / completed if completed > 0 else None
    return {
        "days": days,
        "buys": buys,
        "sells": sells,
        "holds": holds,
        "completed_trades": completed,
        "wins": wins,
        "losses": losses,
        "win_rate": wr,
        "total_pnl_usd": round(total_pnl, 2),
        "pnl_by_symbol": pnl_by_symbol,
        "stop_loss_count": stop_loss_count,
        "pnl_direct_count": pnl_direct_count,       # AE
        "pnl_estimated_count": pnl_estimated_count,  # AE
    }


def compute_winrate_history(weeks: int = 4) -> List[Dict[str, Any]]:
    """
    Compute weekly P&L stats for the last N weeks (S).
    Returns list of dicts [{week_start, trades, wins, pnl, win_rate}, ...] newest last.
    """
    now = _now_jst()
    history = []
    for w in range(weeks - 1, -1, -1):
        week_end = now - timedelta(days=w * 7)
        week_start = week_end - timedelta(days=7)
        rows = _load_recent_trades_range(week_start, week_end)
        stats = compute_weekly_stats(rows, 7)
        history.append({
            "week_start": week_start.strftime("%m/%d"),
            "week_end": week_end.strftime("%m/%d"),
            "trades": stats["completed_trades"],
            "wins": stats["wins"],
            "pnl": stats["total_pnl_usd"],
            "win_rate": stats["win_rate"],
        })
    return history


def _load_recent_trades_range(start: datetime, end: datetime) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for f in sorted(REVIEW_OUT.glob("stock_shadow_*.csv")):
        try:
            with f.open(encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    ts_str = row.get("timestamp_jst", "")
                    try:
                        ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                        if start <= ts < end:
                            rows.append(dict(row))
                    except ValueError:
                        pass
        except Exception:
            pass
    return rows


# ── Live readiness check ──────────────────────────────────────────────────────

def check_live_readiness(state: Dict[str, Any], history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Evaluate whether the shadow system is ready for real trading.
    Returns {score, max_score, checks: [{name, ok, detail}]}.
    """
    model_file = REVIEW_OUT / "stock_ml_model.json"
    total_trades = int(state.get("total_trades", 0))
    max_drawdown = float(state.get("max_drawdown_usd", 0.0))
    last_run_str = state.get("last_run_jst", "")

    # Compute overall win rate from history (all weeks)
    all_wins = sum(w["wins"] for w in history)
    all_trades = sum(w["trades"] for w in history)
    overall_wr = all_wins / all_trades if all_trades > 0 else 0.0

    # Last run recency (within 48h)
    try:
        last_run = datetime.strptime(last_run_str[:19], "%Y-%m-%d %H:%M:%S")
        hours_since = (_now_jst() - last_run).total_seconds() / 3600
        bot_active = hours_since < 48
    except Exception:
        bot_active = False
        hours_since = 999

    # Positive last week
    last_week_pnl = history[-1]["pnl"] if history else 0.0
    last_week_ok = last_week_pnl >= -10.0

    checks = [
        {
            "name": "サンプル数",
            "ok": total_trades >= READINESS_MIN_TRADES,
            "detail": f"{total_trades}件 (要{READINESS_MIN_TRADES}+)",
        },
        {
            "name": "勝率",
            "ok": overall_wr >= READINESS_MIN_WR,
            "detail": f"{overall_wr:.1%} (要{READINESS_MIN_WR:.0%}+)",
        },
        {
            "name": "最大DD",
            "ok": max_drawdown >= READINESS_MAX_DD,
            "detail": f"${max_drawdown:.2f} (要≥${READINESS_MAX_DD:.0f})",
        },
        {
            "name": "MLモデル",
            "ok": model_file.exists(),
            "detail": "trained" if model_file.exists() else "未学習",
        },
        {
            "name": "Bot稼働",
            "ok": bot_active,
            "detail": f"最終実行 {hours_since:.0f}h前" if hours_since < 999 else "未確認",
        },
        {
            "name": "直近週PnL",
            "ok": last_week_ok,
            "detail": f"${last_week_pnl:+.2f} (要≥-$10)",
        },
    ]

    score = sum(1 for c in checks if c["ok"])
    return {"score": score, "max_score": len(checks), "checks": checks}


# ── Format message ────────────────────────────────────────────────────────────

def format_summary(state: Dict[str, Any], stats: Dict[str, Any],
                   history: Optional[List[Dict[str, Any]]] = None,
                   readiness: Optional[Dict[str, Any]] = None) -> str:
    lines = [
        f"[株シャドウ 週次レポート] {_now_jst_str()} JST",
        f"集計期間: 直近 {stats['days']} 日",
        "",
        f"累積 PnL   : ${state.get('total_pnl_usd', 0.0):+.2f} (全期間)",
        f"最大DD     : ${state.get('max_drawdown_usd', 0.0):.2f}",
        f"手数料累計 : ${state.get('commission_paid_usd', 0.0):.2f}",
        f"週間 PnL   : ${stats['total_pnl_usd']:+.2f}",
        f"週間トレード: {stats['completed_trades']}件  勝={stats['wins']}  負={stats['losses']}",
    ]
    # AE: show direct vs estimated PnL source
    d = stats.get("pnl_direct_count", 0)
    e = stats.get("pnl_estimated_count", 0)
    if d + e > 0:
        lines.append(f"PnL集計     : 直接{d}件 / 推定{e}件"
                     + ("  ✓全件実績値" if e == 0 and d > 0 else ""))
    if stats["win_rate"] is not None:
        lines.append(f"勝率        : {stats['win_rate']:.1%}")
    if stats.get("stop_loss_count", 0) > 0:
        lines.append(f"SL発動      : {stats['stop_loss_count']}件")
    if stats["pnl_by_symbol"]:
        lines.append("")
        lines.append("銘柄別 PnL:")
        for sym, pnl in sorted(stats["pnl_by_symbol"].items(), key=lambda x: -abs(x[1])):
            lines.append(f"  {sym:6s}  ${pnl:+.2f}")

    # S: Win rate history (4 weeks)
    if history:
        lines.append("")
        lines.append("週次勝率推移:")
        for w in history:
            wr_str = f"{w['win_rate']:.0%}" if w["win_rate"] is not None else "—"
            trend = "↑" if w["pnl"] > 0 else "↓" if w["pnl"] < 0 else "→"
            lines.append(f"  {w['week_start']}~{w['week_end']}  "
                         f"{w['trades']}件 WR={wr_str} ${w['pnl']:+.2f} {trend}")

    # Live readiness
    if readiness:
        score = readiness["score"]
        max_s = readiness["max_score"]
        bar = "█" * score + "░" * (max_s - score)
        lines.append("")
        lines.append(f"実弾準備スコア: {score}/{max_s} [{bar}]")
        for c in readiness["checks"]:
            mark = "✓" if c["ok"] else "✗"
            lines.append(f"  {mark} {c['name']}: {c['detail']}")

    open_pos = state.get("positions", {})
    if open_pos:
        lines.append("")
        lines.append(f"オープン: {list(open_pos.keys())}")
    lines.append(f"\n監視銘柄: {state.get('symbols', [])}")
    lines.append(f"インターバル: {state.get('interval', '?')}")
    return "\n".join(lines)


# ── Notify ────────────────────────────────────────────────────────────────────

def _parse_toml_simple(path: Path) -> Dict[str, str]:
    """Minimal TOML key=value parser (no tables/arrays needed)."""
    result: Dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip().strip('"').strip("'")
    return result


def send_notification(text: str, dry_run: bool = False) -> bool:
    secrets = _parse_toml_simple(SECRETS_FILE)
    ntfy_url = secrets.get("ntfy_topic_url", "").strip()
    webhook_url = secrets.get("trade_notify_webhook_url", "").strip() or \
                  secrets.get("login_notify_webhook_url", "").strip()

    if dry_run:
        print("[weekly] DRY-RUN — would send:")
        print(text)
        return True

    sent = False

    if ntfy_url:
        try:
            ok, msg = post_ntfy(
                ntfy_url,
                "Shadow Weekly",
                text,
                level=LEVEL_INFO,
                tags="shadow_weekly",
                state_path=NOTIFY_STATE,
                event_code=f"shadow_weekly_{_now_jst().strftime('%Y%m%d')}",
            )
            print(f"[weekly] ntfy {msg}")
            sent = sent or ok
        except Exception as exc:
            print(f"[weekly] ntfy error: {exc}", file=sys.stderr)

    if webhook_url:
        try:
            body = json.dumps({"text": text}).encode("utf-8")
            req = urllib.request.Request(
                webhook_url, data=body, method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10):
                pass
            print(f"[weekly] webhook sent → {webhook_url}")
            sent = True
        except Exception as exc:
            print(f"[weekly] webhook error: {exc}", file=sys.stderr)

    if not sent:
        WEEKLY_OUT.write_text(text, encoding="utf-8")
        print(f"[weekly] no notifier configured — saved to {WEEKLY_OUT}")

    return sent


# ── Live readiness achieved notification (Y) ──────────────────────────────────

def _send_readiness_achieved_notify(score: int, max_score: int) -> None:
    """Y: Send ntfy push when readiness score first reaches max (all checks passed)."""
    secrets = _parse_toml_simple(SECRETS_FILE)
    ntfy_url = secrets.get("ntfy_topic_url", "").strip()
    if not ntfy_url:
        return
    body = (
        f"🎯 シャドウbot 実弾準備完了！ スコア {score}/{max_score}\n"
        f"全チェック通過。実弾移行を検討してください。\n"
        f"確認: python3 stock_shadow_weekly.py --dry-run"
    )
    try:
        ok, msg = post_ntfy(
            ntfy_url,
            "実弾準備完了 READY_FOR_LIVE",
            body,
            level=LEVEL_CRITICAL,
            tags="rocket,shadow_readiness",
            state_path=NOTIFY_STATE,
            event_code="shadow_readiness_achieved",
        )
        print(f"[weekly] READY_FOR_LIVE ntfy {msg}")
    except Exception as exc:
        print(f"[weekly] readiness ntfy error: {exc}", file=sys.stderr)


def _save_state_field(key: str, value: Any) -> None:
    """Write a single key to STATE_FILE without touching other fields."""
    state = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    state[key] = value
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Send weekly shadow trading summary")
    ap.add_argument("--days", type=int, default=7, help="Window in days (default: 7)")
    ap.add_argument("--dry-run", action="store_true", help="Print summary, do not send")
    ap.add_argument("--no-history", action="store_true", help="Skip win rate history section")
    ap.add_argument("--no-readiness", action="store_true", help="Skip live readiness check section")
    args = ap.parse_args()

    state = _load_state()
    rows = _load_recent_trades(days=args.days)
    stats = compute_weekly_stats(rows, days=args.days)
    history = compute_winrate_history(weeks=4) if not args.no_history else None
    readiness = check_live_readiness(state, history or []) if not args.no_readiness else None
    summary = format_summary(state, stats, history=history, readiness=readiness)

    print(summary)
    print()
    send_notification(summary, dry_run=args.dry_run)

    # Y: notify once when readiness first reaches max score
    if readiness and not args.dry_run:
        if readiness["score"] == readiness["max_score"]:
            if not state.get("live_ready_notified_at"):
                _send_readiness_achieved_notify(readiness["score"], readiness["max_score"])
                _save_state_field("live_ready_notified_at", _now_jst_str())
                print(f"[weekly] live_ready_notified_at saved")
