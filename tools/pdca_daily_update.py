#!/usr/bin/env python3
"""PDCA Daily Update — 日次自律評価エンジン

毎日実行し、PDCAログのHOLDエントリーに当日のDD指標スナップショットを追記する。
ルールベースで自動判断ヒント（auto_decision_hint）を生成し、ntfy通知を送る。

Usage:
    python3 tools/pdca_daily_update.py
    python3 tools/pdca_daily_update.py --day8 20260510
    python3 tools/pdca_daily_update.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports"
PDCA_LOG_PATH = REPORTS_DIR / "pdca_log.json"
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"

# ── 自動判断ヒントのしきい値 ──────────────────────────────────────────────────
MIN_TRADES_FOR_EVALUATION = 10     # これ以下はINSUFFICIENT_DATA
REVIEW_DUE_DAYS = 14               # start_dateからこれ以上経過でREVIEW_DUE
PF_CONTINUE_THRESHOLD = 1.05       # PF がこれ以上なら CONTINUE_CANDIDATE
PF_ROLLBACK_THRESHOLD = 0.85       # PF がこれ以下なら ROLLBACK_CANDIDATE
DD_ROLLBACK_WORSEN_PCT = 1.0       # 最大DDが最初のスナップショットから1.0%pt悪化でROLLBACK
SNAPSHOT_WINDOW_FOR_TREND = 3      # トレンド判定に使うスナップショット数


def _now_jst() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


def _today8() -> str:
    return _now_jst().strftime("%Y%m%d")


def _read_toml_val(path: Path, key: str) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(key):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _ntfy_post(url: str, bearer: str, body: str, title: str, priority: str = "default") -> bool:
    if not url:
        return False
    try:
        headers: Dict[str, str] = {
            "Content-Type": "text/plain; charset=utf-8",
            "Title": title,
            "Tags": "bar_chart,robot",
            "Priority": priority,
        }
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        req = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5.0) as r:
            return r.status < 300
    except Exception:
        return False


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _run_dd_report(day8: Optional[str], *, dry_run: bool) -> Tuple[bool, Dict[str, Any]]:
    """Run dd_report.py and return (success, metrics_dict)."""
    if dry_run:
        print(f"[DRYRUN] would run dd_report.py {'--all-time' if day8 is None else day8}")
        return True, {}
    cmd = [
        sys.executable,
        str(ROOT / "tools" / "dd_report.py"),
    ]
    if day8:
        cmd.append(day8)
    else:
        cmd.append("--all-time")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30.0, cwd=str(ROOT)
        )
        if proc.returncode != 0:
            print(f"[WARN] dd_report.py rc={proc.returncode}: {proc.stderr.strip()[:200]}")
    except Exception as exc:
        print(f"[WARN] dd_report.py subprocess failed: {exc}")
    # Read the saved JSON regardless of subprocess result
    suffix = day8 if day8 else "all-time"
    json_path = REPORTS_DIR / f"dd_report_{suffix}.json"
    data = _load_json(json_path)
    if not isinstance(data, dict):
        return False, {}
    metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    return True, metrics


def _build_snapshot(day8: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "checked_at": _now_jst().strftime("%Y-%m-%d %H:%M:%S"),
        "day8": day8,
        "n_trades": metrics.get("n_trades"),
        "daily_max_drawdown_amount": metrics.get("daily_max_drawdown_amount"),
        "profit_factor": metrics.get("profit_factor"),
        "recovery_factor": metrics.get("recovery_factor"),
        "expectancy_per_trade_pct": metrics.get("expectancy_per_trade_pct"),
        "dd_recovery_minutes": metrics.get("dd_recovery_minutes"),
    }


def _evaluate_hint(entry: Dict[str, Any], snapshot: Dict[str, Any]) -> Tuple[str, str]:
    """Return (auto_decision_hint, reason)."""
    n = snapshot.get("n_trades") or 0
    if n < MIN_TRADES_FOR_EVALUATION:
        return "INSUFFICIENT_DATA", f"取引件数不足 (N={n}, 必要最低={MIN_TRADES_FOR_EVALUATION})"

    # Check REVIEW_DUE
    start_date_str = str(entry.get("start_date") or "")
    review_due = False
    if start_date_str:
        try:
            start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
            days_elapsed = (datetime.now() - start_dt).days
            if days_elapsed >= REVIEW_DUE_DAYS:
                review_due = True
        except ValueError:
            pass

    # Gather history from result list
    result_list: List[Dict[str, Any]] = []
    existing = entry.get("result")
    if isinstance(existing, list):
        result_list = [r for r in existing if isinstance(r, dict)]

    pf_now = snapshot.get("profit_factor")
    dd_now = snapshot.get("daily_max_drawdown_amount")

    # ROLLBACK: PF below threshold
    if pf_now is not None and pf_now < PF_ROLLBACK_THRESHOLD:
        return "ROLLBACK_CANDIDATE", f"PF={pf_now:.2f} < 閾値{PF_ROLLBACK_THRESHOLD}"

    # ROLLBACK: DD worsened from first snapshot
    if result_list and dd_now is not None:
        first_snap = next(
            (r for r in result_list if r.get("daily_max_drawdown_amount") is not None), None
        )
        if first_snap is not None:
            first_dd = first_snap["daily_max_drawdown_amount"]
            if (first_dd is not None and dd_now < first_dd - DD_ROLLBACK_WORSEN_PCT):
                return "ROLLBACK_CANDIDATE", (
                    f"最大DD悪化: {first_dd:.3f} → {dd_now:.3f} "
                    f"(悪化量 {dd_now - first_dd:.3f}%pt)"
                )

    # CONTINUE: PF above threshold, sustained
    recent_snaps = (result_list + [snapshot])[-SNAPSHOT_WINDOW_FOR_TREND:]
    recent_pfs = [
        s["profit_factor"]
        for s in recent_snaps
        if s.get("profit_factor") is not None
    ]
    if len(recent_pfs) >= SNAPSHOT_WINDOW_FOR_TREND and all(
        pf >= PF_CONTINUE_THRESHOLD for pf in recent_pfs
    ):
        return "CONTINUE_CANDIDATE", (
            f"直近{SNAPSHOT_WINDOW_FOR_TREND}日間 PF≥{PF_CONTINUE_THRESHOLD} "
            f"({', '.join(f'{p:.2f}' for p in recent_pfs)})"
        )

    if review_due:
        return "REVIEW_DUE", f"開始から{REVIEW_DUE_DAYS}日以上経過 — 手動レビュー推奨"

    return "HOLD", "評価継続中"


def run_pdca_daily_update(
    day8: str,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Core update logic. Returns summary dict."""
    print(f"[pdca_daily] day8={day8} dry_run={dry_run}")

    # 1. Run dd_report for today and all-time
    ok_today, metrics_today = _run_dd_report(day8, dry_run=dry_run)
    ok_alltime, metrics_alltime = _run_dd_report(None, dry_run=dry_run)

    # Use all-time for PDCA snapshot (most stable signal)
    metrics = metrics_alltime if metrics_alltime else metrics_today

    # 2. Load PDCA log
    entries_raw = _load_json(PDCA_LOG_PATH)
    if not isinstance(entries_raw, list):
        print(f"[WARN] pdca_log.json not found or invalid: {PDCA_LOG_PATH}")
        return {"error": "pdca_log_not_found", "day8": day8}

    entries: List[Dict[str, Any]] = list(entries_raw)
    snapshot = _build_snapshot(day8, metrics)

    # 3. Update each HOLD entry
    updated_ids: List[str] = []
    hints: List[Dict[str, Any]] = []

    for entry in entries:
        if entry.get("decision") != "HOLD":
            continue
        hyp_id = str(entry.get("hypothesis_id", "?"))

        hint, reason = _evaluate_hint(entry, snapshot)
        entry["auto_decision_hint"] = hint
        entry["auto_decision_reason"] = reason
        entry["auto_decision_updated_at"] = snapshot["checked_at"]

        existing = entry.get("result")
        if isinstance(existing, list):
            entry["result"] = existing + [snapshot]
        else:
            entry["result"] = [snapshot]

        updated_ids.append(hyp_id)
        hints.append({"hypothesis_id": hyp_id, "hint": hint, "reason": reason})
        print(f"[pdca_daily] {hyp_id}: hint={hint} — {reason}")

    # 4. Save pdca_log.json
    if updated_ids:
        if dry_run:
            print(f"[DRYRUN] would update pdca_log.json: {updated_ids}")
        else:
            PDCA_LOG_PATH.write_text(
                json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"[pdca_daily] pdca_log.json updated: {updated_ids}")

    # 5. Build summary report
    summary = {
        "generated_at": snapshot["checked_at"],
        "day8": day8,
        "metrics_source": "all-time" if metrics_alltime else "today",
        "snapshot": snapshot,
        "updated_entries": updated_ids,
        "hints": hints,
        "dry_run": dry_run,
    }

    # 6. Save daily summary JSON
    summary_path = REPORTS_DIR / f"pdca_daily_{day8}.json"
    if dry_run:
        print(f"[DRYRUN] would save {summary_path}")
    else:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"[pdca_daily] saved {summary_path}")

    return summary


def _format_ntfy_body(summary: Dict[str, Any]) -> str:
    snap = summary.get("snapshot", {})
    hints = summary.get("hints", [])
    n = snap.get("n_trades")
    dd = snap.get("daily_max_drawdown_amount")
    pf = snap.get("profit_factor")
    rf = snap.get("recovery_factor")
    exp = snap.get("expectancy_per_trade_pct")

    n_str = str(n) if n is not None else "-"
    dd_str = f"{dd:.3f}%pt" if dd is not None else "-"
    pf_str = f"{pf:.2f}" if pf is not None else "-"
    rf_str = f"{rf:.2f}" if rf is not None else "-"
    exp_str = f"{exp:.4f}%pt" if exp is not None else "-"

    lines = [
        f"日付: {summary.get('day8','-')}",
        f"N={n_str} / 最大DD={dd_str} / PF={pf_str} / RF={rf_str}",
        f"期待値={exp_str}",
        "",
    ]
    if hints:
        lines.append("--- PDCAヒント ---")
        for h in hints:
            lines.append(f"{h['hypothesis_id']}: [{h['hint']}] {h['reason']}")
    else:
        lines.append("（更新対象のHOLDエントリーなし）")

    return "\n".join(lines)


def _needs_high_priority(hints: List[Dict[str, Any]]) -> bool:
    urgent = {"ROLLBACK_CANDIDATE", "REVIEW_DUE"}
    return any(h.get("hint") in urgent for h in hints)


def main() -> int:
    ap = argparse.ArgumentParser(description="PDCA日次自律評価エンジン")
    ap.add_argument("--day8", default=None, help="YYYYMMDD (default: today JST)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-notify", action="store_true", help="ntfy通知をスキップ")
    args = ap.parse_args()

    day8 = args.day8 or _today8()

    summary = run_pdca_daily_update(day8, dry_run=bool(args.dry_run))

    if "error" in summary:
        print(f"[FAIL] {summary['error']}")
        return 1

    # Send ntfy
    if not args.no_notify:
        ntfy_url = _read_toml_val(SECRETS_PATH, "ntfy_topic_url")
        ntfy_bearer = _read_toml_val(SECRETS_PATH, "ntfy_bearer_token")
        body = _format_ntfy_body(summary)
        title = f"Ouroboros PDCA日次レポート ({day8})"
        hints = summary.get("hints", [])
        priority = "high" if _needs_high_priority(hints) else "default"
        if args.dry_run:
            print(f"[DRYRUN] ntfy: title={title} priority={priority}\n{body}")
        else:
            ok = _ntfy_post(ntfy_url, ntfy_bearer, body, title, priority)
            print(f"[pdca_daily] ntfy {'sent' if ok else 'failed/disabled'} priority={priority}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
