#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REFLECTION_DIR = ROOT_DIR / "daily_report_out"
SECRET_VALUE_RE = re.compile(r"(sk-[A-Za-z0-9_-]{12,}|xox[baprs]-[A-Za-z0-9-]{12,}|[A-Za-z0-9+/=]{48,})")


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _day8_from_report(path: Path, report: Dict[str, Any]) -> str:
    rng = report.get("range") if isinstance(report.get("range"), dict) else {}
    day8 = str(rng.get("day8", "") or "").strip()
    if day8:
        return day8
    m = re.match(r"daily_reflection_(\d{8})\.json$", path.name)
    return m.group(1) if m else ""


def _llm_feedback(report: Dict[str, Any]) -> Dict[str, Any]:
    top = report.get("daily_reflection_llm_feedback")
    if isinstance(top, dict):
        return top
    reflection = report.get("reflection") if isinstance(report.get("reflection"), dict) else {}
    nested = reflection.get("llm_feedback") if isinstance(reflection, dict) else None
    return nested if isinstance(nested, dict) else {}


def _secret_like_values(obj: Any) -> List[str]:
    hits: List[str] = []
    if isinstance(obj, dict):
        for value in obj.values():
            hits.extend(_secret_like_values(value))
        return hits
    if isinstance(obj, list):
        for value in obj:
            hits.extend(_secret_like_values(value))
        return hits
    if isinstance(obj, str):
        if SECRET_VALUE_RE.search(obj):
            hits.append(obj[:12] + "...")
    return hits


def audit_file(path: Path) -> Dict[str, Any]:
    report = _load_json(path)
    items: List[Dict[str, str]] = []
    if not report:
        return {
            "path": str(path),
            "day8": "",
            "ok": False,
            "items": [{"level": "ERROR", "code": "invalid_json", "message": "invalid or empty JSON"}],
        }

    day8 = _day8_from_report(path, report)
    reflection = report.get("reflection") if isinstance(report.get("reflection"), dict) else {}
    feedback = _llm_feedback(report)
    if not day8:
        items.append({"level": "ERROR", "code": "missing_day8", "message": "range.day8 missing"})
    if not reflection:
        items.append({"level": "ERROR", "code": "missing_reflection", "message": "reflection block missing"})
    for key in ("win_notes", "loss_notes", "next_day_actions"):
        if key not in reflection:
            items.append({"level": "WARN", "code": "missing_reflection_field", "message": f"reflection.{key} missing"})
    if "suggested_control_updates" in reflection and not isinstance(reflection.get("suggested_control_updates"), dict):
        items.append({"level": "ERROR", "code": "bad_suggested_updates", "message": "suggested_control_updates must be an object"})
    if feedback:
        if not str(feedback.get("reason", "") or "").strip():
            items.append({"level": "WARN", "code": "missing_llm_reason", "message": "llm feedback reason missing"})
        if bool(feedback.get("used")) and not str(feedback.get("summary", "") or "").strip():
            items.append({"level": "ERROR", "code": "missing_llm_summary", "message": "llm used but summary missing"})
    else:
        items.append({"level": "WARN", "code": "missing_llm_feedback", "message": "llm feedback block missing; fallback reflection may still be valid"})
    secret_hits = _secret_like_values(report)
    if secret_hits:
        items.append({"level": "ERROR", "code": "secret_like_value", "message": "report contains secret-like values"})

    return {
        "path": str(path),
        "day8": day8,
        "ok": not any(item["level"] == "ERROR" for item in items),
        "llm_used": bool(feedback.get("used")) if feedback else False,
        "llm_reason": str(feedback.get("reason", "") or "") if feedback else "",
        "items": items,
    }


def build_audit(reflection_dir: Path = DEFAULT_REFLECTION_DIR, *, limit: int = 14) -> Dict[str, Any]:
    files = sorted(reflection_dir.glob("daily_reflection_*.json")) if reflection_dir.exists() else []
    if limit > 0:
        files = files[-int(limit):]
    reports = [audit_file(path) for path in files]
    day_counts = Counter(str(r.get("day8") or "") for r in reports if str(r.get("day8") or ""))
    duplicate_days = sorted(day for day, n in day_counts.items() if n > 1)
    items: List[Dict[str, str]] = []
    if not files:
        items.append({"level": "WARN", "code": "no_reflections", "message": f"no daily_reflection_*.json in {reflection_dir}"})
    for day8 in duplicate_days:
        items.append({"level": "ERROR", "code": "duplicate_day", "message": f"duplicate reflection day: {day8}"})
    error_count = sum(1 for r in reports for item in r.get("items", []) if item.get("level") == "ERROR") + sum(
        1 for item in items if item.get("level") == "ERROR"
    )
    warn_count = sum(1 for r in reports for item in r.get("items", []) if item.get("level") == "WARN") + sum(
        1 for item in items if item.get("level") == "WARN"
    )
    return {
        "ok": error_count == 0,
        "reflection_dir": str(reflection_dir),
        "file_count": len(files),
        "error_count": error_count,
        "warn_count": warn_count,
        "llm_used_count": sum(1 for r in reports if r.get("llm_used")),
        "duplicate_days": duplicate_days,
        "items": items,
        "reports": reports,
    }


def format_text(audit: Dict[str, Any]) -> str:
    lines = [
        f"llm_reflection_audit={'OK' if audit.get('ok') else 'NG'} files={audit.get('file_count')} "
        f"llm_used={audit.get('llm_used_count')} errors={audit.get('error_count')} warnings={audit.get('warn_count')}"
    ]
    for item in audit.get("items", []):
        lines.append(f"[{item.get('level')}] {item.get('code')}: {item.get('message')}")
    for report in audit.get("reports", []):
        label = f"{report.get('day8') or '-'} {Path(str(report.get('path'))).name}"
        if not report.get("items"):
            lines.append(f"[OK] {label} llm_used={report.get('llm_used')} reason={report.get('llm_reason') or '-'}")
            continue
        for item in report.get("items", []):
            lines.append(f"[{item.get('level')}] {label}: {item.get('code')} {item.get('message')}")
    return "\n".join(lines)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit daily reflection JSON reports and LLM fallback metadata.")
    p.add_argument("--reflection-dir", default=str(DEFAULT_REFLECTION_DIR))
    p.add_argument("--limit", type=int, default=14)
    p.add_argument("--print-json", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    audit = build_audit(Path(args.reflection_dir).expanduser(), limit=int(args.limit))
    if args.print_json:
        print(json.dumps(audit, ensure_ascii=False, indent=2))
    else:
        print(format_text(audit))
    return 0 if audit.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
