# ============================================================
# Project Ouroboros v1 — audit.py (Integrity Audit + Safe Repair)
# ============================================================
# 目的：
# - SPEC固定のログ整合を自動監査
# - 可能な範囲で「安全な自己修復」を実施（stateの修復を中心、ログは原則改変しない）
#
# 監査対象：
# - logs/trade_log_YYYYMMDD.csv（必須カラム / result / pos_id / PAPER-EXIT整合）
# - MAIN/state.json（open_pos整合）
#
# 出力：
# - audit_out/audit_YYYYMMDD.json（1日）
# - audit_out/audit_YYYYMMDD_YYYYMMDD.json（範囲）
# ============================================================

import argparse
import csv
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

MAIN_DIR = Path(__file__).resolve().parent
LOG_DIR = MAIN_DIR.parent / "logs"
AUDIT_OUT_DIR_DEFAULT = MAIN_DIR / "audit_out"
STATE_FILE = MAIN_DIR / "state.json"

# SPEC fixed
LOG_FIELDS = [
    "time","result","side","price","size",
    "ltp","best_bid","best_ask",
    "spread_pct","limit_pct",
    "ma_fast","ma_slow","trend","signal",
    "note","pos_id",
]
RESULT_ALLOWED = {
    "PAPER",
    "OBSERVE_OK",
    "OBSERVE_NO_SIGNAL",
    "SKIP_SPREAD",
    "SKIP_NEWS",
    "SKIP_DAILY_LIMIT",
    # New results emitted by MAIN/bot.py - accept them in audit
    "SKIP_OUT_OF_TIME",
    "SKIP_TICKER_INCOMPLETE",
    "OBSERVE_AI_BLOCK",
    # Additional historic/observed result names
    "SKIP_ALREADY_RUNNING",
    "SKIP_COOLDOWN",
    "OBSERVE_TIME_BLOCK",
    "OBSERVE_SELL_FAST_MA_NEAR",
    "AI_BLOCKED",
    "SKIP_ORPHAN_DETECTED",
    "MANUAL_CLEAR_OPEN_POS",
    "PAPER_ENTRY",
    "PAPER_EXIT_TP",
    "PAPER_EXIT_SL",
    "PAPER_EXIT_TIMEOUT",
    "PAPER_EXIT_PARTIAL_TP",
    "PAPER_EXIT_EOD",
    "HOLD_OPEN_POS"
}
POS_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-(BUY|SELL)-\d{3}$")

# -------------------------
# helpers
# -------------------------
def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def load_rows(day8: str) -> List[dict]:
    p = LOG_DIR / f"trade_log_{day8}.csv"
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return [row for row in r]

def day8_to_date(day8: str) -> datetime:
    return datetime.strptime(day8, "%Y%m%d")

def iter_days(start8: str, end8: str) -> List[str]:
    a = day8_to_date(start8)
    z = day8_to_date(end8)
    days = []
    cur = a
    while cur <= z:
        days.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return days

def issue(code: str, severity: str, message: str, context: Optional[dict] = None) -> dict:
    return {
        "code": code,
        "severity": severity,  # INFO/WARN/ERROR/FATAL
        "message": message,
        "context": context or {},
    }

# -------------------------
# audit checks
# -------------------------
def audit_rows(rows: List[dict]) -> Tuple[dict, List[dict]]:
    issues: List[dict] = []

    # header / columns
    if rows:
        # DictReader doesn't keep original header reliably; validate by checking keys presence across first row
        missing = [c for c in LOG_FIELDS if c not in rows[0]]
        if missing:
            issues.append(issue(
                "LOG_MISSING_COLUMNS", "FATAL",
                f"Missing required columns: {missing}",
                {"missing": missing},
            ))

    # per-row checks
    pos_events: Dict[str, dict] = {}
    paper_pos: set = set()
    exit_pos: set = set()

    res_count: Dict[str, int] = {}
    for i, r in enumerate(rows, start=1):
        res = (r.get("result") or "").strip()
        res_count[res] = res_count.get(res, 0) + 1

        if res and res not in RESULT_ALLOWED:
            issues.append(issue(
                "RESULT_UNKNOWN", "ERROR",
                f"Unknown result '{res}' at row {i}",
                {"row": i, "result": res},
            ))

        pos_id = (r.get("pos_id") or "").strip()
        if res == "PAPER":
            if not pos_id:
                issues.append(issue(
                    "PAPER_MISSING_POS_ID", "FATAL",
                    f"PAPER missing pos_id at row {i}",
                    {"row": i},
                ))
            elif not POS_ID_RE.match(pos_id):
                issues.append(issue(
                    "POS_ID_FORMAT_INVALID", "ERROR",
                    f"Invalid pos_id format at row {i}: {pos_id}",
                    {"row": i, "pos_id": pos_id},
                ))
            if pos_id:
                paper_pos.add(pos_id)

        if res.startswith("PAPER_EXIT_"):
            if not pos_id:
                issues.append(issue(
                    "EXIT_MISSING_POS_ID", "ERROR",
                    f"EXIT missing pos_id at row {i} result={res}",
                    {"row": i, "result": res},
                ))
            elif not POS_ID_RE.match(pos_id):
                issues.append(issue(
                    "POS_ID_FORMAT_INVALID", "ERROR",
                    f"Invalid pos_id format at row {i}: {pos_id}",
                    {"row": i, "pos_id": pos_id},
                ))
            if pos_id:
                exit_pos.add(pos_id)

        if pos_id:
            s = pos_events.setdefault(pos_id, {"events": 0, "paper": 0, "exits": 0, "last_result": ""})
            s["events"] += 1
            s["last_result"] = res
            if res == "PAPER":
                s["paper"] += 1
            if res.startswith("PAPER_EXIT_"):
                s["exits"] += 1

    # cross checks pos_id
    for pid, s in pos_events.items():
        if s["paper"] > 1:
            issues.append(issue(
                "POS_ID_DUP_PAPER", "ERROR",
                f"pos_id has multiple PAPER events: {pid}",
                {"pos_id": pid, "paper_n": s["paper"]},
            ))
        if s["exits"] > 1:
            issues.append(issue(
                "POS_ID_MULTI_EXIT", "ERROR",
                f"pos_id has multiple EXIT events: {pid}",
                {"pos_id": pid, "exit_n": s["exits"]},
            ))
        if s["exits"] >= 1 and s["paper"] == 0:
            issues.append(issue(
                "EXIT_WITHOUT_PAPER", "ERROR",
                f"EXIT exists but PAPER not found for pos_id: {pid}",
                {"pos_id": pid, "last_result": s["last_result"]},
            ))

    # summary
    summary = {
        "rows": len(rows),
        "result_counts": res_count,
        "pos_id_count": len(pos_events),
        "paper_pos_n": len(paper_pos),
        "exit_pos_n": len(exit_pos),
        "paper_without_exit_n": len(paper_pos - exit_pos),
        "exit_without_paper_n": len(exit_pos - paper_pos),
    }
    return summary, issues

def audit_state_against_logs(state: dict, paper_pos: set, exit_pos: set) -> List[dict]:
    issues: List[dict] = []
    op = state.get("_open_pos")
    if not op:
        return issues

    if not isinstance(op, dict):
        issues.append(issue(
            "STATE_OPEN_POS_INVALID", "ERROR",
            "_open_pos exists but is not a dict",
            {"type": str(type(op))},
        ))
        return issues

    pid = str(op.get("pos_id") or "").strip()
    if not pid:
        issues.append(issue(
            "STATE_OPEN_POS_MISSING_POS_ID", "ERROR",
            "_open_pos missing pos_id",
            {"open_pos_keys": list(op.keys())},
        ))
        return issues

    if not POS_ID_RE.match(pid):
        issues.append(issue(
            "STATE_OPEN_POS_POS_ID_INVALID", "ERROR",
            f"_open_pos pos_id invalid format: {pid}",
            {"pos_id": pid},
        ))

    if pid in exit_pos:
        issues.append(issue(
            "STATE_OPEN_POS_ALREADY_EXITED", "FATAL",
            "state shows open_pos but logs already contain an EXIT for this pos_id",
            {"pos_id": pid},
        ))

    if pid not in paper_pos:
        issues.append(issue(
            "STATE_OPEN_POS_NO_PAPER_LOG", "WARN",
            "state has open_pos but PAPER log not found (may be log loss or manual edit)",
            {"pos_id": pid},
        ))

    return issues

# -------------------------
# safe repair
# -------------------------
def repair_state_if_needed(state: dict, issues: List[dict]) -> Tuple[dict, List[dict]]:
    """
    安全な自己修復：
    - FATALの state open_pos 不整合は open_pos を退避して消す
    - ログは変更しない（監査の信頼性を壊すため）
    """
    repaired = []
    fatal_codes = {i["code"] for i in issues if i["severity"] == "FATAL"}
    if not fatal_codes:
        return state, repaired

    op = state.get("_open_pos")
    if op:
        state.setdefault("_repair_history", [])
        state["_repair_history"].append({
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": "quarantine_open_pos",
            "open_pos": op,
            "fatal_codes": sorted(list(fatal_codes)),
        })
        state.pop("_open_pos", None)
        repaired.append(issue(
            "REPAIR_QUARANTINE_OPEN_POS", "WARN",
            "Quarantined _open_pos due to FATAL inconsistencies (logs not modified).",
            {"fatal_codes": sorted(list(fatal_codes))},
        ))
    return state, repaired

# -------------------------
# main
# -------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", help="YYYYMMDD", default=None)
    ap.add_argument("--start", help="YYYYMMDD", default=None)
    ap.add_argument("--end", help="YYYYMMDD", default=None)
    ap.add_argument("--out-dir", default=str(AUDIT_OUT_DIR_DEFAULT))
    ap.add_argument("--fix-state", action="store_true", help="apply safe repair to state.json (no log edits)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.day:
        days = [args.day]
        out_name = f"audit_{args.day}.json"
    else:
        if not (args.start and args.end):
            raise SystemExit("Specify --day or (--start and --end).")
        days = iter_days(args.start, args.end)
        out_name = f"audit_{args.start}_{args.end}.json"

    all_rows = []
    for d in days:
        all_rows.extend(load_rows(d))

    summary, issues = audit_rows(all_rows)

    # derive paper_pos/exit_pos sets for state audit
    paper_pos = set()
    exit_pos = set()
    for r in all_rows:
        res = (r.get("result") or "").strip()
        pid = (r.get("pos_id") or "").strip()
        if res == "PAPER" and pid:
            paper_pos.add(pid)
        if res.startswith("PAPER_EXIT_") and pid:
            exit_pos.add(pid)

    state = load_state()
    state_issues = audit_state_against_logs(state, paper_pos, exit_pos)
    issues.extend(state_issues)

    repaired = []
    if args.fix_state:
        state2, repaired = repair_state_if_needed(state, issues)
        if repaired:
            save_state(state2)
            issues.extend(repaired)

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "days": days,
        "summary": summary,
        "issues": issues,
        "fix_state_applied": bool(args.fix_state),
    }

    out_path = out_dir / out_name
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # stdout brief
    print("[audit]")
    print(" days:", ",".join(days))
    print(" rows:", summary["rows"])
    print(" issues:", len(issues))
    sev = {"FATAL":0,"ERROR":0,"WARN":0,"INFO":0}
    for it in issues:
        sev[it["severity"]] = sev.get(it["severity"],0)+1
    print(" severity:", sev)
    print(" out:", str(out_path))

if __name__ == "__main__":
    main()
