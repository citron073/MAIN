from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DAY8_RE = re.compile(r"^\d{8}$")
LOG_NAME_RE = re.compile(r"trade_log_(\d{8})\.csv$")
DR_NAME_RE = re.compile(r"daily_report_(\d{8})\.json$")
WR_NAME_RE = re.compile(r"weekly_report_(\d{8})_(\d{8})\.json$")

@dataclass
class Issue:
    severity: str  # "ERROR" | "WARN"
    code: str
    message: str
    path: str = ""

def _err(issues: List[Issue], code: str, message: str, path: str = "") -> None:
    issues.append(Issue("ERROR", code, message, path))

def _warn(issues: List[Issue], code: str, message: str, path: str = "") -> None:
    issues.append(Issue("WARN", code, message, path))

def _load_json(path: Path, issues: List[Issue]) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        _err(issues, "E_FILE_NOT_FOUND", f"file not found: {path}", str(path))
    except json.JSONDecodeError as e:
        _err(issues, "E_JSON_DECODE", f"json decode error: {e}", str(path))
    except Exception as e:
        _err(issues, "E_JSON_READ", f"json read error: {e}", str(path))
    return None

def _read_csv_header(path: Path, issues: List[Issue]) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                _err(issues, "E_CSV_EMPTY", "csv header missing/empty", str(path))
                return None
            return [h.strip() for h in header]
    except FileNotFoundError:
        _err(issues, "E_FILE_NOT_FOUND", f"file not found: {path}", str(path))
    except Exception as e:
        _err(issues, "E_CSV_READ", f"csv read error: {e}", str(path))
    return None

def _require_keys(obj: Dict[str, Any], keys: List[str], issues: List[Issue], code: str, ctx: str, path: str) -> None:
    for k in keys:
        if k not in obj:
            _err(issues, code, f"missing key '{k}' in {ctx}", path)

def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def _check_control_csv(main_dir: Path, contracts: Dict[str, Any], issues: List[Issue]) -> None:
    p = main_dir / "CONTROL.csv"
    header = _read_csv_header(p, issues)
    if header is None:
        return
    req = contracts["control_csv"]["required_columns"]
    # CONTROL is strict 2-col key,value
    if [h.lower() for h in header[:2]] != req:
        _err(issues, "E_CONTROL_HEADER", f"CONTROL.csv header must be {req} but got {header}", str(p))

def _find_logs_dir(main_dir: Path) -> Optional[Path]:
    # dashboard.py がやってるのに近い探索（MAIN/logs or ../logs）
    cands = [
        (main_dir / "logs").resolve(),
        (main_dir / "../logs").resolve(),
    ]
    for d in cands:
        if d.exists() and d.is_dir():
            return d
    return None

def _check_trade_log_csv(main_dir: Path, day8: str, contracts: Dict[str, Any], issues: List[Issue]) -> Optional[Path]:
    logs_dir = _find_logs_dir(main_dir)
    if logs_dir is None:
        _err(issues, "E_LOGS_DIR", "logs directory not found (tried ./logs and ../logs)", str(main_dir))
        return None

    p = logs_dir / f"trade_log_{day8}.csv"
    header = _read_csv_header(p, issues)
    if header is None:
        return None

    req = contracts["trade_log_csv"]["required_columns"]
    missing = [c for c in req if c not in header]
    if missing:
        _err(issues, "E_TRADE_LOG_COLUMNS", f"trade_log missing columns: {missing}", str(p))
    return p

def _check_daily_report_json(main_dir: Path, day8: str, contracts: Dict[str, Any], issues: List[Issue]) -> Optional[Path]:
    out_dir = main_dir / "daily_report_out"
    p = out_dir / f"daily_report_{day8}.json"
    d = _load_json(p, issues)
    if d is None:
        return None

    # top keys
    _require_keys(d, contracts["daily_report_json"]["required_top_keys"], issues, "E_DR_TOPKEY", "daily_report json top", str(p))

    if "meta" in d and isinstance(d["meta"], dict):
        _require_keys(d["meta"], contracts["daily_report_json"]["meta_required_keys"], issues, "E_DR_METAKEY", "meta", str(p))
    else:
        _err(issues, "E_DR_META_TYPE", "meta must be dict", str(p))

    if "daily" in d and isinstance(d["daily"], dict):
        _require_keys(d["daily"], contracts["daily_report_json"]["daily_required_keys"], issues, "E_DR_DAILYKEY", "daily", str(p))
        # paper_rate_pct should be number
        if "paper_rate_pct" in d["daily"] and not _is_number(d["daily"]["paper_rate_pct"]):
            _err(issues, "E_DR_DAILY_TYPE", "daily.paper_rate_pct must be number", str(p))
    else:
        _err(issues, "E_DR_DAILY_TYPE", "daily must be dict", str(p))

    # by_side
    sides = contracts["daily_report_json"]["by_side_required_sides"]
    bs_req = contracts["daily_report_json"]["by_side_required_keys"]
    if "by_side" in d:
        if not isinstance(d["by_side"], dict):
            _err(issues, "E_DR_BYSIDE_TYPE", "by_side must be dict", str(p))
        else:
            for s in sides:
                if s not in d["by_side"]:
                    _err(issues, "E_DR_BYSIDE_MISS", f"by_side missing side '{s}'", str(p))
                    continue
                if not isinstance(d["by_side"][s], dict):
                    _err(issues, "E_DR_BYSIDE_TYPE", f"by_side.{s} must be dict", str(p))
                    continue
                _require_keys(d["by_side"][s], bs_req, issues, "E_DR_BYSIDE_KEYS", f"by_side.{s}", str(p))

    # by_hour
    hours = contracts["daily_report_json"]["by_hour_hours"]
    bh_req = contracts["daily_report_json"]["by_hour_required_hour_keys"]
    if "by_hour" in d:
        if not isinstance(d["by_hour"], dict):
            _err(issues, "E_DR_BYHOUR_TYPE", "by_hour must be dict", str(p))
        else:
            for hk in hours:
                if hk not in d["by_hour"]:
                    _warn(issues, "W_DR_BYHOUR_MISS", f"by_hour missing hour '{hk}' (ok if no rows)", str(p))
                    continue
                if not isinstance(d["by_hour"][hk], dict):
                    _err(issues, "E_DR_BYHOUR_TYPE", f"by_hour.{hk} must be dict", str(p))
                    continue
                _require_keys(d["by_hour"][hk], bh_req, issues, "E_DR_BYHOUR_KEYS", f"by_hour.{hk}", str(p))

    return p

def _check_audit_json(main_dir: Path, day8: str, contracts: Dict[str, Any], issues: List[Issue]) -> Optional[Path]:
    out_dir = main_dir / "audit_out"
    jpath = out_dir / f"audit_{day8}.json"
    d = _load_json(jpath, issues)
    if d is None:
        return None

    aud = contracts.get("audit_json")
    if not isinstance(aud, dict):
        _err(issues, "E_AUD_CONTRACT_MISSING", "audit_json contract missing in SPEC_CONTRACTS_V1.json", str(jpath))
        return jpath

    req_top = aud.get("required_top_keys", [])
    _require_keys(d, req_top, issues, "E_AUD_TOPKEY", "audit json top", str(jpath))

    if isinstance(d.get("summary"), dict):
        _require_keys(d["summary"], aud.get("summary_required_keys", []), issues, "E_AUD_SUMMARYKEY", "summary", str(jpath))
    else:
        _err(issues, "E_AUD_SUMMARY_TYPE", "summary must be dict", str(jpath))

    if "issues" in d:
        if not isinstance(d["issues"], list):
            _err(issues, "E_AUD_ISSUES_TYPE", "issues must be list", str(jpath))
        else:
            allowed = set(aud.get("severity_allowed", ["INFO","WARN","ERROR","FATAL"]))
            for i, it in enumerate(d["issues"], start=1):
                if not isinstance(it, dict):
                    _err(issues, "E_AUD_ISSUE_ITEM_TYPE", f"issues[{i}] must be dict", str(jpath))
                    continue
                _require_keys(it, aud.get("issue_required_keys", []), issues, "E_AUD_ISSUE_KEYS", f"issues[{i}]", str(jpath))
                sev = (it.get("severity") or "").strip()
                if sev and sev not in allowed:
                    _err(issues, "E_AUD_SEVERITY", f"invalid severity in issues[{i}]: {sev}", str(jpath))

    return jpath


def _find_weekly_report_covering_day(main_dir: Path, day8: str) -> Optional[Path]:
    out_dir = main_dir / "weekly_report_out"
    if not out_dir.exists() or not out_dir.is_dir():
        return None

    cands: List[Tuple[str, str, Path]] = []
    for p in out_dir.glob("weekly_report_*.json"):
        m = WR_NAME_RE.fullmatch(p.name)
        if not m:
            continue
        start8, end8 = m.group(1), m.group(2)
        if start8 <= day8 <= end8:
            cands.append((start8, end8, p))
    if not cands:
        return None

    # Prefer the smallest covering range first, then latest end8.
    cands.sort(key=lambda x: ((int(x[1]) - int(x[0])), x[1], x[0]))
    return cands[0][2]


def _check_weekly_report_json(main_dir: Path, day8: str, contracts: Dict[str, Any], issues: List[Issue]) -> Optional[Path]:
    wr = contracts.get("weekly_report_json")
    if not isinstance(wr, dict):
        return None

    p = _find_weekly_report_covering_day(main_dir, day8)
    if p is None:
        return None

    d = _load_json(p, issues)
    if d is None:
        return p

    _require_keys(d, wr.get("required_top_keys", []), issues, "E_WR_TOPKEY", "weekly_report json top", str(p))

    meta = d.get("meta")
    if isinstance(meta, dict):
        _require_keys(meta, wr.get("meta_required_keys", []), issues, "E_WR_METAKEY", "meta", str(p))
    else:
        _err(issues, "E_WR_META_TYPE", "meta must be dict", str(p))

    rng = d.get("range")
    if isinstance(rng, dict):
        _require_keys(rng, wr.get("range_required_keys", []), issues, "E_WR_RANGEKEY", "range", str(p))
        s8 = (rng.get("start8") or "").strip()
        e8 = (rng.get("end8") or "").strip()
        if DAY8_RE.match(s8) and DAY8_RE.match(e8) and s8 > e8:
            _err(issues, "E_WR_RANGE_ORDER", f"range start8>end8: {s8}>{e8}", str(p))
        days = rng.get("days")
        if not isinstance(days, list):
            _err(issues, "E_WR_RANGE_DAYS_TYPE", "range.days must be list", str(p))
    else:
        _err(issues, "E_WR_RANGE_TYPE", "range must be dict", str(p))

    weekly = d.get("weekly")
    if isinstance(weekly, dict):
        _require_keys(weekly, wr.get("weekly_required_keys", []), issues, "E_WR_WEEKLYKEY", "weekly", str(p))
    else:
        _err(issues, "E_WR_WEEKLY_TYPE", "weekly must be dict", str(p))

    weekly_review = d.get("weekly_review")
    if isinstance(weekly_review, dict):
        _require_keys(
            weekly_review,
            wr.get("weekly_review_required_keys", []),
            issues,
            "E_WR_REVIEWKEY",
            "weekly_review",
            str(p),
        )
    else:
        _err(issues, "E_WR_REVIEW_TYPE", "weekly_review must be dict", str(p))

    ai_feedback = d.get("ai_feedback")
    if isinstance(ai_feedback, dict):
        _require_keys(
            ai_feedback,
            wr.get("ai_feedback_required_keys", []),
            issues,
            "E_WR_AIFBKEY",
            "ai_feedback",
            str(p),
        )
    else:
        _err(issues, "E_WR_AIFB_TYPE", "ai_feedback must be dict", str(p))

    by_side = d.get("by_side")
    if isinstance(by_side, dict):
        for s in wr.get("by_side_required_sides", []):
            if s not in by_side:
                _err(issues, "E_WR_BYSIDE_MISS", f"by_side missing side '{s}'", str(p))
    else:
        _err(issues, "E_WR_BYSIDE_TYPE", "by_side must be dict", str(p))

    by_hour = d.get("by_hour")
    if isinstance(by_hour, dict):
        for h in wr.get("by_hour_hours", []):
            if h not in by_hour:
                _err(issues, "E_WR_BYHOUR_MISS", f"by_hour missing hour '{h}'", str(p))
    else:
        _err(issues, "E_WR_BYHOUR_TYPE", "by_hour must be dict", str(p))

    integ = d.get("weekly_exit_integrity")
    if isinstance(integ, dict):
        _require_keys(
            integ,
            wr.get("weekly_exit_integrity_required_keys", []),
            issues,
            "E_WR_INTEGKEY",
            "weekly_exit_integrity",
            str(p),
        )
    else:
        _err(issues, "E_WR_INTEG_TYPE", "weekly_exit_integrity must be dict", str(p))

    it = d.get("issues")
    if isinstance(it, list):
        allowed = set(wr.get("severity_allowed", ["INFO", "WARN", "ERROR", "FATAL"]))
        req_keys = wr.get("issue_required_keys", [])
        for i, x in enumerate(it, start=1):
            if not isinstance(x, dict):
                _err(issues, "E_WR_ISSUE_ITEM_TYPE", f"issues[{i}] must be dict", str(p))
                continue
            _require_keys(x, req_keys, issues, "E_WR_ISSUE_KEYS", f"issues[{i}]", str(p))
            sev = (x.get("severity") or "").strip()
            if sev and sev not in allowed:
                _err(issues, "E_WR_SEVERITY", f"invalid severity in issues[{i}]: {sev}", str(p))
    else:
        _err(issues, "E_WR_ISSUES_TYPE", "issues must be list", str(p))

    return p


def _print_report(issues: List[Issue]) -> None:
    if not issues:
        print("[OK] spec_check: no issues")
        return
    # stable ordering: ERROR first
    issues_sorted = sorted(issues, key=lambda x: (0 if x.severity == "ERROR" else 1, x.code, x.path, x.message))
    for it in issues_sorted:
        p = f" ({it.path})" if it.path else ""
        print(f"[{it.severity}] {it.code}: {it.message}{p}")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("day8", help="YYYYMMDD")
    ap.add_argument("--contracts", default="SPEC_CONTRACTS_V1.json", help="contracts json path (default: SPEC_CONTRACTS_V1.json)")
    ap.add_argument("--strict", action="store_true", help="treat WARN as failure")
    args = ap.parse_args()

    day8 = (args.day8 or "").strip()
    if not DAY8_RE.match(day8):
        print("[ERROR] day8 must be YYYYMMDD")
        sys.exit(2)

    main_dir = Path(__file__).resolve().parent
    issues: List[Issue] = []

    contracts_path = (main_dir / args.contracts).resolve() if not Path(args.contracts).is_absolute() else Path(args.contracts)
    contracts = _load_json(contracts_path, issues)
    if contracts is None:
        _print_report(issues)
        sys.exit(2)

    _check_control_csv(main_dir, contracts, issues)
    _check_trade_log_csv(main_dir, day8, contracts, issues)
    _check_daily_report_json(main_dir, day8, contracts, issues)


    _check_audit_json(main_dir, day8, contracts, issues)
    _check_weekly_report_json(main_dir, day8, contracts, issues)
    _print_report(issues)

    has_err = any(i.severity == "ERROR" for i in issues)
    has_warn = any(i.severity == "WARN" for i in issues)
    if has_err or (args.strict and has_warn):
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
