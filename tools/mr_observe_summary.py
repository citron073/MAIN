from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LOGS_DIR = ROOT_DIR.parent / "logs" / "instances" / "mr_observe"


def _note_value(note: str, key: str) -> str:
    m = re.search(rf"\b{re.escape(key)}=([^\s]+)\b", str(note or ""))
    return m.group(1) if m else ""


def _read_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _mr_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    return [r for r in rows if str(r.get("result", "")).startswith("OBSERVE_MR")]


def _mr_paper_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for r in rows:
        if str(r.get("result", "")) != "PAPER":
            continue
        note = str(r.get("note", "") or "")
        if _note_value(note, "mr_paper") == "1" or _note_value(note, "strategy") == "MR":
            out.append(r)
    return out


_PAPER_EXIT_TIMEOUT_RESULTS = frozenset({"PAPER_EXIT_TIMEOUT", "PAPER_EXIT_EOD", "PAPER_EXIT_PRENEWS"})


def _mr_paper_exit_breakdown(rows: Iterable[Dict[str, str]], pos_ids: set) -> Dict[str, Any]:
    """Count PAPER_EXIT_* rows whose pos_id matches an MR PAPER entry.

    Groups: tp (PAPER_EXIT_TP), sl (PAPER_EXIT_SL),
            timeout (TIMEOUT/EOD/PRENEWS), other.
    Uses the pos_id CSV column — no note parsing needed.
    """
    tp_n = sl_n = timeout_n = other_n = 0
    for r in rows:
        result = str(r.get("result", ""))
        if not result.startswith("PAPER_EXIT"):
            continue
        pid = str(r.get("pos_id", "") or "")
        if not pid or pid not in pos_ids:
            continue
        if result == "PAPER_EXIT_TP":
            tp_n += 1
        elif result == "PAPER_EXIT_SL":
            sl_n += 1
        elif result in _PAPER_EXIT_TIMEOUT_RESULTS:
            timeout_n += 1
        else:
            other_n += 1
    total = tp_n + sl_n + timeout_n + other_n
    return {
        "tp_n": tp_n,
        "sl_n": sl_n,
        "timeout_n": timeout_n,
        "other_n": other_n,
        "total_n": total,
        "wr_pct": round(tp_n / total * 100.0, 1) if total > 0 else 0.0,
    }


def _tail_preview(rows: List[Dict[str, str]], tail: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows[-max(0, int(tail)):]:
        note = str(r.get("note", "") or "")
        out.append(
            {
                "time": r.get("time", ""),
                "result": r.get("result", ""),
                "trend": r.get("trend", ""),
                "signal": r.get("signal", ""),
                "mr_rank": _note_value(note, "mr_rank"),
                "mr_score": _note_value(note, "mr_score"),
                "mr_level_type": _note_value(note, "mr_level_type"),
                "mr_reclaim": _note_value(note, "mr_reclaim"),
                "note": note[:260],
            }
        )
    return out


def build_summary(rows: List[Dict[str, str]], *, day8: str, tail: int = 8) -> Dict[str, Any]:
    result_counts = Counter(r.get("result", "") for r in rows)
    mr_rows = _mr_rows(rows)
    mr_paper_rows = _mr_paper_rows(rows)
    rank_counts = Counter()
    level_type_counts = Counter()
    reclaim_counts = Counter()
    score_counts = Counter()
    rank_result_counts = Counter()
    rank_signal_counts = Counter()
    rank_level_type_counts = Counter()
    rank_reclaim_counts = Counter()
    rank_hour_counts = Counter()
    paper_rank_counts = Counter()
    paper_rank_signal_counts = Counter()
    paper_rank_hour_counts = Counter()
    for r in mr_rows:
        note = str(r.get("note", "") or "")
        rank = _note_value(note, "mr_rank")
        level_type = _note_value(note, "mr_level_type")
        reclaim = _note_value(note, "mr_reclaim")
        score = _note_value(note, "mr_score")
        if rank:
            rank_counts[rank] += 1
            rank_result_counts[f"{rank}:{r.get('result', '')}"] += 1
            rank_signal_counts[f"{rank}:{r.get('signal', '')}"] += 1
            if level_type:
                rank_level_type_counts[f"{rank}:{level_type}"] += 1
            if reclaim:
                rank_reclaim_counts[f"{rank}:{reclaim}"] += 1
            hour = str(r.get("time", "") or "")[11:13]
            if hour.isdigit():
                rank_hour_counts[f"{rank}:{hour}"] += 1
        if level_type:
            level_type_counts[level_type] += 1
        if reclaim:
            reclaim_counts[reclaim] += 1
        if score:
            score_counts[score] += 1
    for r in mr_paper_rows:
        note = str(r.get("note", "") or "")
        rank = _note_value(note, "mr_rank") or _note_value(note, "mr_paper_rank")
        if rank:
            paper_rank_counts[rank] += 1
            paper_rank_signal_counts[f"{rank}:{r.get('signal', '')}"] += 1
            hour = str(r.get("time", "") or "")[11:13]
            if hour.isdigit():
                paper_rank_hour_counts[f"{rank}:{hour}"] += 1
    mr_paper_pos_ids = {str(r.get("pos_id", "") or "") for r in mr_paper_rows}
    mr_paper_exit_breakdown = _mr_paper_exit_breakdown(rows, mr_paper_pos_ids)
    return {
        "day8": day8,
        "rows_total": len(rows),
        "results": dict(result_counts),
        "mr_rows_total": len(mr_rows),
        "mr_paper_entries_total": len(mr_paper_rows),
        "mr_results": dict(Counter(r.get("result", "") for r in mr_rows)),
        "mr_rank_counts": dict(rank_counts),
        "mr_score_counts": dict(score_counts),
        "mr_level_type_counts": dict(level_type_counts),
        "mr_reclaim_counts": dict(reclaim_counts),
        "mr_rank_result_counts": dict(rank_result_counts),
        "mr_rank_signal_counts": dict(rank_signal_counts),
        "mr_rank_level_type_counts": dict(rank_level_type_counts),
        "mr_rank_reclaim_counts": dict(rank_reclaim_counts),
        "mr_rank_hour_counts": dict(rank_hour_counts),
        "mr_paper_rank_counts": dict(paper_rank_counts),
        "mr_paper_rank_signal_counts": dict(paper_rank_signal_counts),
        "mr_paper_rank_hour_counts": dict(paper_rank_hour_counts),
        "mr_paper_exit_breakdown": mr_paper_exit_breakdown,
        "mr_rank_a_trigger_n": int(rank_result_counts.get("A:OBSERVE_MR_TRIGGER") or 0),
        "mr_rank_a_reclaim_n": int(rank_reclaim_counts.get("A:1") or 0),
        "tail_preview": _tail_preview(rows, tail),
    }


def resolve_log_path(logs_dir: Path, day8: Optional[str]) -> Path:
    if day8:
        return logs_dir / f"trade_log_{day8}.csv"
    paths = sorted(logs_dir.glob("trade_log_*.csv"))
    return paths[-1] if paths else logs_dir / "trade_log_.csv"


def resolve_log_paths(logs_dir: Path, day8: Optional[str], lookback_days: int) -> List[Path]:
    if day8:
        return [logs_dir / f"trade_log_{day8}.csv"]
    paths = sorted(logs_dir.glob("trade_log_*.csv"))
    if int(lookback_days) > 0:
        return paths[-int(lookback_days):]
    return paths


def build_multi_day_summary(
    day_summaries: List[Dict[str, Any]],
    *,
    min_days: int = 3,
    min_rank_a: int = 10,
    min_rank_a_trigger: int = 0,
) -> Dict[str, Any]:
    totals: Dict[str, Any] = {
        "days": [s.get("day8", "") for s in day_summaries],
        "active_days": sum(1 for s in day_summaries if int(s.get("mr_rows_total") or 0) > 0),
        "rows_total": sum(int(s.get("rows_total") or 0) for s in day_summaries),
        "mr_rows_total": sum(int(s.get("mr_rows_total") or 0) for s in day_summaries),
        "mr_paper_entries_total": sum(int(s.get("mr_paper_entries_total") or 0) for s in day_summaries),
        "mr_trigger_n": sum(int((s.get("mr_results") or {}).get("OBSERVE_MR_TRIGGER") or 0) for s in day_summaries),
        "mr_rank_a_trigger_n": sum(int(s.get("mr_rank_a_trigger_n") or 0) for s in day_summaries),
        "mr_rank_a_reclaim_n": sum(int(s.get("mr_rank_a_reclaim_n") or 0) for s in day_summaries),
        "mr_rank_counts": {},
        "mr_score_counts": {},
        "mr_level_type_counts": {},
        "mr_reclaim_counts": {},
        "mr_rank_result_counts": {},
        "mr_rank_signal_counts": {},
        "mr_rank_level_type_counts": {},
        "mr_rank_reclaim_counts": {},
        "mr_rank_hour_counts": {},
        "mr_paper_rank_counts": {},
        "mr_paper_rank_signal_counts": {},
        "mr_paper_rank_hour_counts": {},
        "mr_paper_exit_breakdown": {"tp_n": 0, "sl_n": 0, "timeout_n": 0, "other_n": 0, "total_n": 0, "wr_pct": 0.0},
    }
    for key in (
        "mr_rank_counts",
        "mr_score_counts",
        "mr_level_type_counts",
        "mr_reclaim_counts",
        "mr_rank_result_counts",
        "mr_rank_signal_counts",
        "mr_rank_level_type_counts",
        "mr_rank_reclaim_counts",
        "mr_rank_hour_counts",
        "mr_paper_rank_counts",
        "mr_paper_rank_signal_counts",
        "mr_paper_rank_hour_counts",
    ):
        counter: Counter[str] = Counter()
        for summary in day_summaries:
            counter.update(summary.get(key) or {})
        totals[key] = dict(counter)
    bd = totals["mr_paper_exit_breakdown"]
    for k in ("tp_n", "sl_n", "timeout_n", "other_n", "total_n"):
        bd[k] = sum(int((s.get("mr_paper_exit_breakdown") or {}).get(k) or 0) for s in day_summaries)
    bd["wr_pct"] = round(bd["tp_n"] / bd["total_n"] * 100.0, 1) if bd["total_n"] > 0 else 0.0
    rank_a_n = int((totals.get("mr_rank_counts") or {}).get("A") or 0)
    mr_rows_total = int(totals.get("mr_rows_total") or 0)
    totals["rank_a_share_pct"] = round((rank_a_n / mr_rows_total * 100.0) if mr_rows_total > 0 else 0.0, 4)
    totals["trigger_share_pct"] = round((int(totals.get("mr_trigger_n") or 0) / mr_rows_total * 100.0) if mr_rows_total > 0 else 0.0, 4)
    reasons: List[str] = []
    if int(totals["active_days"]) < int(min_days):
        reasons.append(f"active_days<{int(min_days)} ({totals['active_days']})")
    if rank_a_n < int(min_rank_a):
        reasons.append(f"mr_rank_a_n<{int(min_rank_a)} ({rank_a_n})")
    if int(min_rank_a_trigger) > 0 and int(totals.get("mr_rank_a_trigger_n") or 0) < int(min_rank_a_trigger):
        reasons.append(f"mr_rank_a_trigger_n<{int(min_rank_a_trigger)} ({int(totals.get('mr_rank_a_trigger_n') or 0)})")
    decision = "PAPER_CANDIDATE" if not reasons else "WAIT"
    if not reasons:
        reasons.append("MR rank A samples are enough for A-only PAPER review; human approval required")
    totals["decision"] = decision
    totals["reasons"] = reasons
    totals["thresholds"] = {
        "min_days": int(min_days),
        "min_rank_a": int(min_rank_a),
        "min_rank_a_trigger": int(min_rank_a_trigger),
    }
    return totals


def format_text(summary: Dict[str, Any]) -> str:
    return "\n".join(
        [
            f"day={summary['day8']}",
            f"rows_total={summary['rows_total']}",
            f"mr_rows_total={summary['mr_rows_total']}",
            f"mr_paper_entries_total={summary.get('mr_paper_entries_total', 0)}",
            f"results={json.dumps(summary['results'], ensure_ascii=False, sort_keys=True)}",
            f"mr_results={json.dumps(summary['mr_results'], ensure_ascii=False, sort_keys=True)}",
            f"mr_rank_counts={json.dumps(summary['mr_rank_counts'], ensure_ascii=False, sort_keys=True)}",
            f"mr_rank_a_trigger_n={int(summary.get('mr_rank_a_trigger_n') or 0)} mr_rank_a_reclaim_n={int(summary.get('mr_rank_a_reclaim_n') or 0)}",
            f"mr_level_type_counts={json.dumps(summary['mr_level_type_counts'], ensure_ascii=False, sort_keys=True)}",
            f"mr_reclaim_counts={json.dumps(summary['mr_reclaim_counts'], ensure_ascii=False, sort_keys=True)}",
            f"mr_rank_signal_counts={json.dumps(summary.get('mr_rank_signal_counts') or {}, ensure_ascii=False, sort_keys=True)}",
            f"mr_rank_hour_counts={json.dumps(summary.get('mr_rank_hour_counts') or {}, ensure_ascii=False, sort_keys=True)}",
            f"mr_paper_rank_counts={json.dumps(summary.get('mr_paper_rank_counts') or {}, ensure_ascii=False, sort_keys=True)}",
            f"mr_paper_exit_breakdown={json.dumps(summary.get('mr_paper_exit_breakdown') or {}, ensure_ascii=False, sort_keys=True)}",
        ]
    )


def format_multi_text(summary: Dict[str, Any]) -> str:
    return "\n".join(
        [
            f"mr_paper_candidate={summary['decision']} days={','.join(str(x) for x in summary['days'])}",
            f"reason={'; '.join(str(x) for x in summary['reasons'])}",
            f"active_days={summary['active_days']} rows_total={summary['rows_total']} mr_rows_total={summary['mr_rows_total']}",
            f"mr_paper_entries_total={summary.get('mr_paper_entries_total', 0)}",
            f"mr_trigger_n={summary['mr_trigger_n']} trigger_share_pct={summary['trigger_share_pct']:.1f}",
            f"mr_rank_counts={json.dumps(summary['mr_rank_counts'], ensure_ascii=False, sort_keys=True)} rank_a_share_pct={summary['rank_a_share_pct']:.1f}",
            f"mr_rank_a_trigger_n={int(summary.get('mr_rank_a_trigger_n') or 0)} mr_rank_a_reclaim_n={int(summary.get('mr_rank_a_reclaim_n') or 0)}",
            f"mr_level_type_counts={json.dumps(summary['mr_level_type_counts'], ensure_ascii=False, sort_keys=True)}",
            f"mr_reclaim_counts={json.dumps(summary['mr_reclaim_counts'], ensure_ascii=False, sort_keys=True)}",
            f"mr_rank_signal_counts={json.dumps(summary.get('mr_rank_signal_counts') or {}, ensure_ascii=False, sort_keys=True)}",
            f"mr_rank_hour_counts={json.dumps(summary.get('mr_rank_hour_counts') or {}, ensure_ascii=False, sort_keys=True)}",
            f"mr_paper_rank_counts={json.dumps(summary.get('mr_paper_rank_counts') or {}, ensure_ascii=False, sort_keys=True)}",
            f"mr_paper_exits={json.dumps(summary.get('mr_paper_exit_breakdown') or {}, ensure_ascii=False, sort_keys=True)}",
        ]
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Summarize MR observe logs")
    p.add_argument("--logs-dir", default=str(DEFAULT_LOGS_DIR))
    p.add_argument("--day8", default="")
    p.add_argument("--lookback-days", type=int, default=1)
    p.add_argument("--multi-day", action="store_true")
    p.add_argument("--min-days", type=int, default=3)
    p.add_argument("--min-rank-a", type=int, default=10)
    p.add_argument("--min-rank-a-trigger", type=int, default=0)
    p.add_argument("--tail", type=int, default=8)
    p.add_argument("--print-json", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logs_dir = Path(str(args.logs_dir)).expanduser()
    if args.multi_day:
        paths = resolve_log_paths(logs_dir, args.day8 or None, int(args.lookback_days))
        summaries: List[Dict[str, Any]] = []
        for path in paths:
            day8 = re.search(r"trade_log_(\d{8})\.csv$", path.name)
            summaries.append(build_summary(_read_rows(path), day8=day8.group(1) if day8 else "", tail=0))
        summary = build_multi_day_summary(
            summaries,
            min_days=int(args.min_days),
            min_rank_a=int(args.min_rank_a),
            min_rank_a_trigger=int(args.min_rank_a_trigger),
        )
        if args.print_json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print(format_multi_text(summary))
        return 0
    log_path = resolve_log_path(logs_dir, args.day8 or None)
    day8 = re.search(r"trade_log_(\d{8})\.csv$", log_path.name)
    rows = _read_rows(log_path)
    summary = build_summary(rows, day8=day8.group(1) if day8 else "", tail=args.tail)
    if args.print_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_text(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
