#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ouroboros_contract import RESULT_ALLOWED, TRADE_LOG_REQUIRED_FIELDS as REQUIRED_COLUMNS


MAIN_DIR = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = MAIN_DIR / "weekly_report_out"
DAY8_RE = re.compile(r"^\d{8}$")
RANGE_RE = re.compile(r"^(\d{8})-(\d{8})$")
POS_ID_RE = re.compile(r"^\d{8}-\d{6}-(BUY|SELL)-\d{3}$")
ENCODINGS = ("utf-8-sig", "utf-8", "cp932")
POS_ID_LIST_LIMIT = 2000
ISSUE_LIMIT_PER_CODE = 100

WEEKDAY_MAP = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
    "SAT": 5,
    "SUN": 6,
}
WEEKDAY_NAME_BY_NUM = {
    0: "MON",
    1: "TUE",
    2: "WED",
    3: "THU",
    4: "FRI",
    5: "SAT",
    6: "SUN",
}


def _issue(
    issues: List[Dict[str, Any]],
    counters: Dict[str, int],
    *,
    code: str,
    severity: str,
    message: str,
    context: Optional[Dict[str, Any]] = None,
    limited: bool = True,
) -> None:
    if limited:
        counters[code] = counters.get(code, 0) + 1
        if counters[code] > ISSUE_LIMIT_PER_CODE:
            if counters[code] == ISSUE_LIMIT_PER_CODE + 1:
                issues.append(
                    {
                        "code": f"{code}_TRUNCATED",
                        "severity": "WARN",
                        "message": f"{code} exceeded {ISSUE_LIMIT_PER_CODE} entries; further issues are omitted.",
                        "context": {"code": code, "limit": ISSUE_LIMIT_PER_CODE},
                    }
                )
            return
    issues.append(
        {
            "code": code,
            "severity": severity,
            "message": message,
            "context": context or {},
        }
    )


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


def _parse_day8(s: str) -> date:
    if not DAY8_RE.match(s):
        raise ValueError(f"invalid day8: {s}")
    return datetime.strptime(s, "%Y%m%d").date()


def _day8(d: date) -> str:
    return d.strftime("%Y%m%d")


def _iter_days(start_d: date, end_d: date) -> List[str]:
    out: List[str] = []
    cur = start_d
    while cur <= end_d:
        out.append(_day8(cur))
        cur += timedelta(days=1)
    return out


def _resolve_range(
    target: Optional[str],
    start: Optional[str],
    end: Optional[str],
    week_start: str,
) -> Tuple[str, str, List[str]]:
    ws = WEEKDAY_MAP[week_start]

    if target and RANGE_RE.match(target):
        m = RANGE_RE.match(target)
        assert m is not None
        d0 = _parse_day8(m.group(1))
        d1 = _parse_day8(m.group(2))
    elif start or end:
        if not start or not end:
            raise ValueError("--start and --end must be used together")
        d0 = _parse_day8(start)
        d1 = _parse_day8(end)
    elif target:
        d = _parse_day8(target)
        delta = (d.weekday() - ws) % 7
        d0 = d - timedelta(days=delta)
        d1 = d0 + timedelta(days=6)
    else:
        raise ValueError("missing input: set day8/range or --start/--end")

    if d0 > d1:
        raise ValueError("start day is after end day")

    days = _iter_days(d0, d1)
    return _day8(d0), _day8(d1), days


def _resolve_logs_dir(logs_dir_arg: Optional[str]) -> Path:
    if logs_dir_arg:
        d = Path(logs_dir_arg).expanduser().resolve()
        if not d.exists() or not d.is_dir():
            raise ValueError(f"--logs-dir not found: {d}")
        return d

    cands = [(MAIN_DIR / "logs").resolve(), (MAIN_DIR / "../logs").resolve()]
    for d in cands:
        if d.exists() and d.is_dir():
            return d
    raise ValueError("logs directory not found (tried ./logs and ../logs)")


def _new_bucket() -> Dict[str, Any]:
    return {
        "rows_total": 0,
        "rows_used": 0,
        "paper_n": 0,
        "exit_n": 0,
        "observe_n": 0,
        "skip_n": 0,
        "hold_n": 0,
        "error_n": 0,
        "exit_tp_n": 0,
        "exit_sl_n": 0,
        "exit_timeout_n": 0,
        "exit_partial_tp_n": 0,
        "exit_eod_n": 0,
        "spread_over_limit_n": 0,
        "_spreads": [],
    }


def _classify_result(result: str) -> str:
    if result == "PAPER":
        return "paper"
    if result.startswith("PAPER_EXIT_"):
        return "exit"
    if result.startswith("OBSERVE_"):
        return "observe"
    if result.startswith("SKIP_"):
        return "skip"
    if result == "HOLD_OPEN_POS":
        return "hold"
    return "other"


def _update_bucket(bucket: Dict[str, Any], result: str, spread: Optional[float], limit_pct: Optional[float]) -> None:
    kind = _classify_result(result)
    if kind == "paper":
        bucket["paper_n"] += 1
    elif kind == "exit":
        bucket["exit_n"] += 1
        if result == "PAPER_EXIT_TP":
            bucket["exit_tp_n"] += 1
        elif result == "PAPER_EXIT_SL":
            bucket["exit_sl_n"] += 1
        elif result == "PAPER_EXIT_TIMEOUT":
            bucket["exit_timeout_n"] += 1
        elif result == "PAPER_EXIT_PARTIAL_TP":
            bucket["exit_partial_tp_n"] += 1
        elif result == "PAPER_EXIT_EOD":
            bucket["exit_eod_n"] += 1
        elif result == "PAPER_EXIT_PRENEWS":
            bucket["exit_eod_n"] += 1
    elif kind == "observe":
        bucket["observe_n"] += 1
    elif kind == "skip":
        bucket["skip_n"] += 1
    elif kind == "hold":
        bucket["hold_n"] += 1

    if spread is not None:
        bucket["_spreads"].append(spread)
        if limit_pct is not None and spread > limit_pct:
            bucket["spread_over_limit_n"] += 1


def _p90(vals: List[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    idx = max(0, int(round((len(s) - 1) * 0.9)))
    return float(s[idx])


def _pct(n: int, d: int) -> float:
    if d <= 0:
        return 0.0
    return float(n) / float(d) * 100.0


def _finalize_bucket(bucket: Dict[str, Any]) -> Dict[str, Any]:
    spreads = list(bucket.get("_spreads", []))
    out = {k: v for k, v in bucket.items() if k != "_spreads"}
    out["paper_rate_pct"] = round(_pct(out["paper_n"], out["paper_n"] + out["observe_n"]), 4)
    out["exit_rate_pct"] = round(_pct(out["exit_n"], out["paper_n"]), 4)
    if spreads:
        out["spread_avg_pct"] = round(sum(spreads) / len(spreads), 6)
        out["spread_p90_pct"] = round(_p90(spreads), 6)
        out["spread_max_pct"] = round(max(spreads), 6)
    else:
        out["spread_avg_pct"] = 0.0
        out["spread_p90_pct"] = 0.0
        out["spread_max_pct"] = 0.0
    return out


def _side_key(side: Any) -> str:
    s = str(side or "").strip().upper()
    if s in ("BUY", "SELL"):
        return s
    return "UNKNOWN"


def _parse_time_jst(v: Any) -> Optional[datetime]:
    s = str(v or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _calc_ret_pct(side: str, entry_price: Optional[float], exit_price: Optional[float]) -> Optional[float]:
    if entry_price is None or exit_price is None or entry_price == 0:
        return None
    s = str(side or "").strip().upper()
    if s == "SELL":
        return (entry_price - exit_price) / entry_price * 100.0
    return (exit_price - entry_price) / entry_price * 100.0


def _read_csv_rows(path: Path) -> Tuple[List[Dict[str, Any]], List[str], Optional[str], Optional[str]]:
    for enc in ENCODINGS:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                fields = [x.strip() for x in (reader.fieldnames or [])]
                rows = [dict(r) for r in reader]
                return rows, fields, enc, None
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return [], [], enc, str(e)
    return [], [], None, "decode_failed"


def _apply_cap(sorted_ids: List[str], issues: List[Dict[str, Any]], issue_counts: Dict[str, int], name: str) -> List[str]:
    if len(sorted_ids) <= POS_ID_LIST_LIMIT:
        return sorted_ids
    _issue(
        issues,
        issue_counts,
        code="W_POS_ID_LIST_TRUNCATED",
        severity="WARN",
        message=f"{name} truncated to {POS_ID_LIST_LIMIT} entries",
        context={"name": name, "original_size": len(sorted_ids), "limit": POS_ID_LIST_LIMIT},
        limited=False,
    )
    return sorted_ids[:POS_ID_LIST_LIMIT]


def _new_ret_bucket() -> Dict[str, Any]:
    return {
        "closed_n": 0,
        "win_n": 0,
        "loss_n": 0,
        "ret_sum_pct": 0.0,
        "gross_profit_pct": 0.0,
        "gross_loss_pct": 0.0,
    }


def _update_ret_bucket(bucket: Dict[str, Any], ret_pct: float) -> None:
    bucket["closed_n"] += 1
    bucket["ret_sum_pct"] += float(ret_pct)
    if ret_pct > 0:
        bucket["win_n"] += 1
        bucket["gross_profit_pct"] += float(ret_pct)
    elif ret_pct < 0:
        bucket["loss_n"] += 1
        bucket["gross_loss_pct"] += float(ret_pct)


def _finalize_ret_bucket(bucket: Dict[str, Any]) -> Dict[str, Any]:
    closed_n = int(bucket.get("closed_n", 0))
    win_n = int(bucket.get("win_n", 0))
    gross_profit_pct = float(bucket.get("gross_profit_pct", 0.0))
    gross_loss_pct = float(bucket.get("gross_loss_pct", 0.0))
    abs_loss = abs(gross_loss_pct)
    return {
        "closed_n": closed_n,
        "win_n": win_n,
        "loss_n": int(bucket.get("loss_n", 0)),
        "win_rate_pct": round((float(win_n) / float(closed_n) * 100.0) if closed_n > 0 else 0.0, 4),
        "ret_sum_pct": round(float(bucket.get("ret_sum_pct", 0.0)), 6),
        "avg_ret_pct": round((float(bucket.get("ret_sum_pct", 0.0)) / float(closed_n)) if closed_n > 0 else 0.0, 6),
        "gross_profit_pct": round(gross_profit_pct, 6),
        "gross_loss_pct": round(gross_loss_pct, 6),
        "profit_factor": round((gross_profit_pct / abs_loss) if abs_loss > 0 else (8.0 if gross_profit_pct > 0 else 0.0), 6),
    }


def _hours_csv(hours: List[int]) -> str:
    return ",".join(str(int(h)) for h in sorted({int(x) for x in hours if 0 <= int(x) <= 23}))


def run_weekly_report(args: argparse.Namespace) -> Tuple[int, Path, Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    issue_counts: Dict[str, int] = {}

    start8, end8, days = _resolve_range(args.target, args.start, args.end, args.week_start)
    logs_dir = _resolve_logs_dir(args.logs_dir)

    out_dir = Path(args.out_dir).expanduser()
    if not out_dir.is_absolute():
        out_dir = (MAIN_DIR / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"weekly_report_{start8}_{end8}.json"

    weekly = _new_bucket()
    by_day = {d: _new_bucket() for d in days}
    by_side = {"BUY": _new_bucket(), "SELL": _new_bucket(), "UNKNOWN": _new_bucket()}
    by_hour = {str(h): _new_bucket() for h in range(24)}

    day_count = 0
    internal_error_n = 0
    paper_pos_ids: set[str] = set()
    exit_pos_ids: set[str] = set()
    paper_by_pos: Dict[str, Dict[str, Any]] = {}
    exit_by_pos: Dict[str, Dict[str, Any]] = {}

    for day8 in days:
        log_path = logs_dir / f"trade_log_{day8}.csv"
        if not log_path.exists():
            continue
        day_count += 1

        rows, fields, encoding, read_error = _read_csv_rows(log_path)
        if read_error is not None:
            _issue(
                issues,
                issue_counts,
                code="E_LOG_READ",
                severity="ERROR",
                message=f"failed to read log file: {read_error}",
                context={"file": str(log_path), "day8": day8, "encoding": encoding},
                limited=False,
            )
            internal_error_n += 1
            continue

        missing = [c for c in REQUIRED_COLUMNS if c not in fields]
        if missing:
            _issue(
                issues,
                issue_counts,
                code="E_LOG_MISSING_COLUMNS",
                severity="ERROR",
                message=f"missing required columns: {missing}",
                context={"file": str(log_path), "day8": day8, "missing": missing},
                limited=False,
            )

        for row_idx, row in enumerate(rows, start=2):
            try:
                weekly["rows_total"] += 1
                by_day[day8]["rows_total"] += 1

                result = str(row.get("result") or "").strip()
                side = _side_key(row.get("side"))
                pos_id = str(row.get("pos_id") or "").strip()

                if result and result not in RESULT_ALLOWED:
                    _issue(
                        issues,
                        issue_counts,
                        code="W_RESULT_UNKNOWN",
                        severity="WARN",
                        message=f"unknown result '{result}'",
                        context={"file": str(log_path), "day8": day8, "row": row_idx, "result": result},
                    )

                if result == "PAPER":
                    if not pos_id:
                        _issue(
                            issues,
                            issue_counts,
                            code="W_POS_ID_MISSING",
                            severity="WARN",
                            message="PAPER row has empty pos_id",
                            context={"file": str(log_path), "day8": day8, "row": row_idx, "result": result},
                        )
                    else:
                        paper_pos_ids.add(pos_id)
                        if not POS_ID_RE.match(pos_id):
                            _issue(
                                issues,
                                issue_counts,
                                code="W_POS_ID_FORMAT",
                                severity="WARN",
                                message=f"pos_id format mismatch: {pos_id}",
                                context={"file": str(log_path), "day8": day8, "row": row_idx, "pos_id": pos_id},
                            )

                if result.startswith("PAPER_EXIT_"):
                    if not pos_id:
                        _issue(
                            issues,
                            issue_counts,
                            code="W_POS_ID_MISSING",
                            severity="WARN",
                            message="EXIT row has empty pos_id",
                            context={"file": str(log_path), "day8": day8, "row": row_idx, "result": result},
                        )
                    else:
                        exit_pos_ids.add(pos_id)
                        if not POS_ID_RE.match(pos_id):
                            _issue(
                                issues,
                                issue_counts,
                                code="W_POS_ID_FORMAT",
                                severity="WARN",
                                message=f"pos_id format mismatch: {pos_id}",
                                context={"file": str(log_path), "day8": day8, "row": row_idx, "pos_id": pos_id},
                            )

                dt = _parse_time_jst(row.get("time"))
                if dt is None:
                    _issue(
                        issues,
                        issue_counts,
                        code="W_TIME_PARSE",
                        severity="WARN",
                        message="failed to parse time; row excluded",
                        context={"file": str(log_path), "day8": day8, "row": row_idx, "time": row.get("time")},
                    )
                    continue

                weekly["rows_used"] += 1
                by_day[day8]["rows_used"] += 1

                # Store position lifecycle (after time parse) for weekly review.
                if result == "PAPER" and pos_id:
                    if pos_id not in paper_by_pos:
                        paper_by_pos[pos_id] = {
                            "dt": dt,
                            "side": side,
                            "entry_price": _safe_float(row.get("price")),
                        }
                elif result.startswith("PAPER_EXIT_") and pos_id:
                    prev_x = exit_by_pos.get(pos_id)
                    if (not prev_x) or (isinstance(prev_x.get("dt"), datetime) and dt >= prev_x["dt"]):
                        exit_by_pos[pos_id] = {
                            "dt": dt,
                            "result": result,
                            "exit_price": _safe_float(row.get("ltp")) or _safe_float(row.get("price")),
                        }

                spread = _safe_float(row.get("spread_pct"))
                if str(row.get("spread_pct") or "").strip() != "" and spread is None:
                    _issue(
                        issues,
                        issue_counts,
                        code="W_NON_NUMERIC",
                        severity="WARN",
                        message="spread_pct is non-numeric",
                        context={"file": str(log_path), "day8": day8, "row": row_idx, "field": "spread_pct"},
                    )
                limit_pct = _safe_float(row.get("limit_pct"))
                if str(row.get("limit_pct") or "").strip() != "" and limit_pct is None:
                    _issue(
                        issues,
                        issue_counts,
                        code="W_NON_NUMERIC",
                        severity="WARN",
                        message="limit_pct is non-numeric",
                        context={"file": str(log_path), "day8": day8, "row": row_idx, "field": "limit_pct"},
                    )

                _update_bucket(weekly, result, spread, limit_pct)
                _update_bucket(by_day[day8], result, spread, limit_pct)
                _update_bucket(by_side[side], result, spread, limit_pct)
                _update_bucket(by_hour[str(dt.hour)], result, spread, limit_pct)
            except Exception as e:
                internal_error_n += 1
                _issue(
                    issues,
                    issue_counts,
                    code="E_ROW_PROCESS",
                    severity="ERROR",
                    message=f"row process failed: {e}",
                    context={"file": str(log_path), "day8": day8, "row": row_idx},
                )

    if day_count == 0:
        _issue(
            issues,
            issue_counts,
            code="E_LOG_NOT_FOUND",
            severity="ERROR",
            message="no trade_log files found for the selected range",
            context={"start8": start8, "end8": end8, "logs_dir": str(logs_dir)},
            limited=False,
        )

    weekly_final = _finalize_bucket(weekly)
    weekly_final["day_count"] = day_count
    weekly_final["error_n"] = internal_error_n

    by_day_final = {d: _finalize_bucket(by_day[d]) for d in days}

    by_side_final: Dict[str, Dict[str, Any]] = {}
    for k in ("BUY", "SELL", "UNKNOWN"):
        b = _finalize_bucket(by_side[k])
        by_side_final[k] = {
            "paper_n": b["paper_n"],
            "exit_n": b["exit_n"],
            "observe_n": b["observe_n"],
            "skip_n": b["skip_n"],
            "hold_n": b["hold_n"],
            "paper_rate_pct": b["paper_rate_pct"],
            "exit_rate_pct": b["exit_rate_pct"],
            "exit_breakdown": {
                "tp_n": b["exit_tp_n"],
                "sl_n": b["exit_sl_n"],
                "timeout_n": b["exit_timeout_n"],
                "partial_tp_n": b["exit_partial_tp_n"],
                "eod_n": b["exit_eod_n"],
            },
        }

    by_hour_final: Dict[str, Dict[str, Any]] = {}
    for h in [str(i) for i in range(24)]:
        b = _finalize_bucket(by_hour[h])
        by_hour_final[h] = {
            "paper_n": b["paper_n"],
            "observe_n": b["observe_n"],
            "exit_n": b["exit_n"],
            "hold_n": b["hold_n"],
            "paper_rate_pct": b["paper_rate_pct"],
            "spread_avg_pct": b["spread_avg_pct"],
        }

    paper_sorted = sorted(paper_pos_ids)
    exit_sorted = sorted(exit_pos_ids)
    missing_exit = sorted(paper_pos_ids - exit_pos_ids)
    exit_without_paper = sorted(exit_pos_ids - paper_pos_ids)

    # ---------- weekly review / AI feedback ----------
    closed_rows: List[Dict[str, Any]] = []
    hold_min_sum = 0.0
    for pos_id in sorted(paper_pos_ids & exit_pos_ids):
        p = paper_by_pos.get(pos_id)
        x = exit_by_pos.get(pos_id)
        if not p or not x:
            continue
        p_dt = p.get("dt")
        x_dt = x.get("dt")
        if not isinstance(p_dt, datetime) or not isinstance(x_dt, datetime):
            continue
        side = str(p.get("side", "BUY")).upper()
        ret_pct = _calc_ret_pct(side, _safe_float(p.get("entry_price")), _safe_float(x.get("exit_price")))
        if ret_pct is None:
            continue
        hold_min = max(0.0, (x_dt - p_dt).total_seconds() / 60.0)
        hold_min_sum += hold_min
        closed_rows.append(
            {
                "pos_id": pos_id,
                "entry_dt": p_dt,
                "exit_dt": x_dt,
                "exit_hour": x_dt.hour,
                "exit_weekday": x_dt.weekday(),
                "ret_pct": float(ret_pct),
                "result": str(x.get("result", "")),
            }
        )

    ret_week = _new_ret_bucket()
    ret_by_weekday = {name: _new_ret_bucket() for name in WEEKDAY_NAME_BY_NUM.values()}
    ret_by_hour = {str(h): _new_ret_bucket() for h in range(24)}
    exit_reason_counts = {"TP": 0, "SL": 0, "TIMEOUT": 0, "PARTIAL_TP": 0, "EOD": 0, "PRENEWS": 0, "OTHER": 0}
    for r in closed_rows:
        rp = float(r["ret_pct"])
        _update_ret_bucket(ret_week, rp)
        wk_name = WEEKDAY_NAME_BY_NUM.get(int(r["exit_weekday"]), "MON")
        _update_ret_bucket(ret_by_weekday[wk_name], rp)
        _update_ret_bucket(ret_by_hour[str(int(r["exit_hour"]))], rp)

        res = str(r.get("result", ""))
        if res == "PAPER_EXIT_TP":
            exit_reason_counts["TP"] += 1
        elif res == "PAPER_EXIT_SL":
            exit_reason_counts["SL"] += 1
        elif res == "PAPER_EXIT_TIMEOUT":
            exit_reason_counts["TIMEOUT"] += 1
        elif res == "PAPER_EXIT_PARTIAL_TP":
            exit_reason_counts["PARTIAL_TP"] += 1
        elif res == "PAPER_EXIT_EOD":
            exit_reason_counts["EOD"] += 1
        elif res == "PAPER_EXIT_PRENEWS":
            exit_reason_counts["PRENEWS"] += 1
        else:
            exit_reason_counts["OTHER"] += 1

    ret_week_final = _finalize_ret_bucket(ret_week)
    closed_n = int(ret_week_final["closed_n"])
    weekly_review = {
        "closed_n": closed_n,
        "win_n": int(ret_week_final["win_n"]),
        "loss_n": int(ret_week_final["loss_n"]),
        "win_rate_pct": float(ret_week_final["win_rate_pct"]),
        "ret_sum_pct": float(ret_week_final["ret_sum_pct"]),
        "avg_ret_pct": float(ret_week_final["avg_ret_pct"]),
        "gross_profit_pct": float(ret_week_final["gross_profit_pct"]),
        "gross_loss_pct": float(ret_week_final["gross_loss_pct"]),
        "profit_factor": float(ret_week_final["profit_factor"]),
        "avg_hold_min": round((hold_min_sum / float(closed_n)) if closed_n > 0 else 0.0, 4),
        "exit_reason_breakdown": dict(exit_reason_counts),
        "by_weekday": {k: _finalize_ret_bucket(v) for k, v in ret_by_weekday.items()},
        "by_hour": {k: _finalize_ret_bucket(v) for k, v in ret_by_hour.items()},
    }

    min_hour_samples = max(3, min(10, closed_n // 8 if closed_n > 0 else 3))
    good_hours_rank: List[Tuple[int, float, float]] = []
    bad_hours_rank: List[Tuple[int, float, float]] = []
    for h in range(24):
        hb = weekly_review["by_hour"][str(h)]
        n = int(hb.get("closed_n", 0))
        if n < min_hour_samples:
            continue
        avg_ret = float(hb.get("avg_ret_pct", 0.0))
        win_rate = float(hb.get("win_rate_pct", 0.0))
        if avg_ret > 0 and win_rate >= 50.0:
            good_hours_rank.append((h, avg_ret, win_rate))
        if avg_ret < 0 and win_rate <= 45.0:
            bad_hours_rank.append((h, avg_ret, win_rate))
    good_hours_rank.sort(key=lambda x: (x[1], x[2]), reverse=True)
    bad_hours_rank.sort(key=lambda x: (x[1], x[2]))
    good_hours = [x[0] for x in good_hours_rank[:8]]
    bad_hours = [x[0] for x in bad_hours_rank[:8]]

    ai_feedback = {
        "min_hour_samples": int(min_hour_samples),
        "good_hours": list(good_hours),
        "bad_hours": list(bad_hours),
        "good_hours_reason": "avg_ret_pct>0 and win_rate>=50%",
        "bad_hours_reason": "avg_ret_pct<0 and win_rate<=45%",
        "suggested_control_updates": {
            "ai_train_weekly_feedback_enabled": "1",
            "ai_train_weekly_good_hours": _hours_csv(good_hours),
            "ai_train_weekly_bad_hours": _hours_csv(bad_hours),
            "ai_train_weekly_good_hour_boost": "1.20",
            "ai_train_weekly_bad_hour_penalty": "0.70",
        },
        "summary": (
            f"closed={closed_n}, good_hours={_hours_csv(good_hours) or '-'}, "
            f"bad_hours={_hours_csv(bad_hours) or '-'}"
        ),
    }

    report = {
        "meta": {
            "spec": "OUROBOROS_WEEKLY_REPORT_V1",
            "generated_at_jst": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "trade_log",
            "tool": "weekly_report.py",
            "version": "v1",
        },
        "range": {
            "start8": start8,
            "end8": end8,
            "days": days,
        },
        "weekly": weekly_final,
        "by_day": by_day_final,
        "by_side": by_side_final,
        "by_hour": by_hour_final,
        "weekly_review": weekly_review,
        "ai_feedback": ai_feedback,
        "weekly_exit_integrity": {
            "paper_pos_ids": _apply_cap(paper_sorted, issues, issue_counts, "paper_pos_ids"),
            "exit_pos_ids": _apply_cap(exit_sorted, issues, issue_counts, "exit_pos_ids"),
            "missing_exit_pos_ids": _apply_cap(missing_exit, issues, issue_counts, "missing_exit_pos_ids"),
            "exit_without_paper_pos_ids": _apply_cap(exit_without_paper, issues, issue_counts, "exit_without_paper_pos_ids"),
        },
        "issues": issues,
    }

    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        shown = out_path.relative_to(MAIN_DIR)
    except Exception:
        shown = out_path
    print(f"[WRITE] {shown}")

    has_error = any(str(i.get("severity", "")).upper() in ("ERROR", "FATAL") for i in issues)
    has_warn = any(str(i.get("severity", "")).upper() == "WARN" for i in issues)
    rc = 1 if (has_error or (args.strict and has_warn)) else 0
    return rc, out_path, report


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate weekly report JSON from trade_log CSV files.")
    ap.add_argument("target", nargs="?", help="day8 (YYYYMMDD) or range (YYYYMMDD-YYYYMMDD)")
    ap.add_argument("--start", default=None, help="range start day8 (YYYYMMDD)")
    ap.add_argument("--end", default=None, help="range end day8 (YYYYMMDD)")
    ap.add_argument("--out-dir", default="weekly_report_out", help="output directory (default: weekly_report_out)")
    ap.add_argument("--logs-dir", default=None, help="trade_log directory override")
    ap.add_argument(
        "--week-start",
        default="MON",
        choices=list(WEEKDAY_MAP.keys()),
        help="week start weekday for day8 mode (default: MON)",
    )
    ap.add_argument("--strict", action="store_true", help="treat WARN as failure (exit code=1)")
    args = ap.parse_args()

    try:
        rc, _, _ = run_weekly_report(args)
    except ValueError as e:
        print(f"[ERROR] {e}")
        sys.exit(2)
    except Exception as e:
        print(f"[ERROR] fatal: {e}")
        sys.exit(2)
    sys.exit(rc)


if __name__ == "__main__":
    main()
