#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

try:
    from tools import stale_artifact_review as stale_review
except ModuleNotFoundError:  # pragma: no cover - script execution path from MAIN/
    import stale_artifact_review as stale_review  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
REVIEW_OUT = stale_review.REVIEW_OUT


def _now_jst() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


def _now_jst_str() -> str:
    return _now_jst().strftime("%Y-%m-%d %H:%M:%S")


def _safe_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def build_archive_plan(review_out: Path = REVIEW_OUT) -> Dict[str, Any]:
    latest_path = review_out / "stale_artifact_review_latest.json"
    payload = _safe_json(latest_path) if latest_path.exists() else {}
    if not payload:
        payload = stale_review.build_review(review_out)
        stale_review.write_outputs(payload, review_out)

    rel_candidates = [str(p) for p in payload.get("archive_candidates") or []]
    src_paths = [ROOT / rel for rel in rel_candidates if rel]
    existing = [p for p in src_paths if p.exists()]

    return {
        "generated_at_jst": _now_jst_str(),
        "review_path": _display_path(latest_path),
        "archive_dir": _display_path(review_out / "archive"),
        "candidate_count": len(existing),
        "candidates": [_display_path(p) for p in existing],
        "dry_run": True,
        "terminal_only": True,
        "apply_command": "python3 tools/archive_stale_artifacts.py --apply",
    }


def _render_plan_markdown(plan: Dict[str, Any]) -> str:
    lines = [
        "# Archive Stale Artifacts Plan",
        "",
        f"- generated_at_jst: {plan.get('generated_at_jst', '-')}",
        f"- dry_run: {plan.get('dry_run', True)}",
        f"- terminal_only: {plan.get('terminal_only', True)}",
        f"- review_path: {plan.get('review_path', '-')}",
        f"- archive_dir: {plan.get('archive_dir', '-')}",
        f"- candidate_count: {plan.get('candidate_count', 0)}",
        f"- apply_command: {plan.get('apply_command', '-')}",
        "",
        "## Candidates",
    ]
    candidates = list(plan.get("candidates") or [])
    if candidates:
        lines.extend(f"- {item}" for item in candidates)
    else:
        lines.append("- none")
    moved = list(plan.get("moved") or [])
    if moved:
        lines.extend(["", "## Moved"])
        lines.extend(f"- {item}" for item in moved)
    return "\n".join(lines) + "\n"


def write_plan(plan: Dict[str, Any], review_out: Path = REVIEW_OUT) -> Dict[str, str]:
    review_out.mkdir(parents=True, exist_ok=True)
    day8 = _now_jst().strftime("%Y%m%d")
    json_path = review_out / f"archive_stale_artifacts_plan_{day8}.json"
    latest_path = review_out / "archive_stale_artifacts_plan_latest.json"
    md_path = review_out / f"archive_stale_artifacts_plan_{day8}.md"
    md_latest_path = review_out / "archive_stale_artifacts_plan_latest.md"

    text = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    md_text = _render_plan_markdown(plan)
    json_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    md_latest_path.write_text(md_text, encoding="utf-8")
    return {"json": str(json_path), "latest": str(latest_path), "md": str(md_path), "md_latest": str(md_latest_path)}


def apply_archive(plan: Dict[str, Any], review_out: Path = REVIEW_OUT) -> Dict[str, Any]:
    stamp = _now_jst().strftime("%Y%m%d_%H%M%S")
    archive_root = review_out / "archive" / f"legacy_review_{stamp}"
    archive_root.mkdir(parents=True, exist_ok=True)

    moved: List[str] = []
    for rel in plan.get("candidates") or []:
        src = ROOT / rel
        if not src.exists():
            continue
        dst = archive_root / src.name
        shutil.move(str(src), str(dst))
        moved.append(_display_path(dst))

    applied = dict(plan)
    applied["dry_run"] = False
    applied["terminal_only"] = True
    applied["applied_at_jst"] = _now_jst_str()
    applied["archive_dir"] = _display_path(archive_root)
    applied["moved"] = moved
    return applied


def main() -> int:
    ap = argparse.ArgumentParser(description="Plan or apply archive moves for stale legacy review artifacts.")
    ap.add_argument("--review-out", default=str(REVIEW_OUT))
    ap.add_argument("--apply", action="store_true", help="Actually move archive candidates into review_out/archive/")
    ap.add_argument("--print-json", action="store_true")
    args = ap.parse_args()

    review_out = Path(args.review_out)
    plan = build_archive_plan(review_out)
    payload = apply_archive(plan, review_out) if args.apply else plan
    paths = write_plan(payload, review_out)

    if args.print_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        mode = "APPLY" if args.apply else "DRY_RUN"
        print(
            "archive_stale_artifacts={mode} candidates={count} latest={latest}".format(
                mode=mode,
                count=payload.get("candidate_count", 0),
                latest=paths["latest"],
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
