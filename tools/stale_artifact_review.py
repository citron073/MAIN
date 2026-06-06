#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
REVIEW_OUT = ROOT / "review_out"


def _now_jst() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


def _now_jst_str() -> str:
    return _now_jst().strftime("%Y-%m-%d %H:%M:%S")


def _safe_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _age_hours(path: Path) -> float:
    return max(0.0, (_now_jst().timestamp() - path.stat().st_mtime) / 3600.0)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


@dataclass
class ArtifactReview:
    path: str
    age_hours: float
    status: str
    reason: str
    suggested_action: str
    matched_paths: Optional[List[str]] = None

    def as_dict(self) -> Dict[str, Any]:
        payload = {
            "path": self.path,
            "age_hours": round(self.age_hours, 1),
            "status": self.status,
            "reason": self.reason,
            "suggested_action": self.suggested_action,
        }
        if self.matched_paths:
            payload["matched_paths"] = list(self.matched_paths)
        return payload


def _review_named_file(path: Path, *, stale_after_hours: float, suggested_action: str) -> Optional[ArtifactReview]:
    if not path.exists():
        return None
    age = _age_hours(path)
    status = "STALE" if age >= stale_after_hours else "FRESH"
    reason = f"age={age:.1f}h threshold={stale_after_hours:.1f}h"
    return ArtifactReview(_display_path(path), age, status, reason, suggested_action)


def build_review(review_out: Path = REVIEW_OUT) -> Dict[str, Any]:
    items: List[ArtifactReview] = []

    for name, hours, action in [
        ("stock_shadow_state.json", 24.0, "dashboardでは停止中/履歴扱いにし、再開しない限り現行表示対象から外す"),
        ("signal_scanner_latest.json", 24.0, "daily/weekly scanner更新が止まっていないか確認し、古い場合は stale badge を維持"),
        ("ibkr_vm_sync_status.json", 12.0, "ssh_error が続くなら自動同期より手動同期を正運用に寄せる"),
    ]:
        reviewed = _review_named_file(review_out / name, stale_after_hours=hours, suggested_action=action)
        if reviewed:
            items.append(reviewed)

    old_reviews = sorted(review_out.glob("trade_system_review_20260418_*"))
    if old_reviews:
        ages = [_age_hours(p) for p in old_reviews]
        items.append(
            ArtifactReview(
                path="review_out/trade_system_review_20260418_*",
                age_hours=max(ages),
                status="ARCHIVE_CANDIDATE",
                reason=f"legacy review bundle count={len(old_reviews)}",
                suggested_action="archive/ へ移動候補。現行 dashboard の主表示対象からは外す",
                matched_paths=[_display_path(p) for p in old_reviews],
            )
        )

    scanner = _safe_json(review_out / "signal_scanner_latest.json")
    if scanner:
        generated = str(scanner.get("generated_at_jst") or "")
        result = str(scanner.get("result") or "")
        items.append(
            ArtifactReview(
                path="review_out/signal_scanner_latest.json:payload",
                age_hours=_age_hours(review_out / "signal_scanner_latest.json"),
                status="INFO",
                reason=f"generated_at_jst={generated or '-'} result={result or '-'}",
                suggested_action="daily timer と weekly timer の両方で更新されているかを見る",
            )
        )

    stale_n = sum(1 for item in items if item.status in {"STALE", "ARCHIVE_CANDIDATE"})
    archive_candidates: List[str] = []
    for item in items:
        if item.status != "ARCHIVE_CANDIDATE":
            continue
        if item.matched_paths:
            archive_candidates.extend(item.matched_paths)
        else:
            archive_candidates.append(item.path)
    return {
        "generated_at_jst": _now_jst_str(),
        "review_out": str(review_out),
        "stale_count": stale_n,
        "archive_candidates": archive_candidates,
        "items": [item.as_dict() for item in items],
    }


def write_outputs(payload: Dict[str, Any], review_out: Path = REVIEW_OUT) -> Dict[str, str]:
    review_out.mkdir(parents=True, exist_ok=True)
    day8 = _now_jst().strftime("%Y%m%d")
    json_path = review_out / f"stale_artifact_review_{day8}.json"
    latest_path = review_out / "stale_artifact_review_latest.json"
    md_path = review_out / f"stale_artifact_review_{day8}.md"

    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    json_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")

    lines = [
        f"# Stale Artifact Review {day8}",
        "",
        f"- generated_at_jst: {payload.get('generated_at_jst', '-')}",
        f"- stale_count: {payload.get('stale_count', 0)}",
        "",
    ]
    for item in payload.get("items", []):
        lines.extend([
            f"## {item.get('path')}",
            f"- status: {item.get('status')}",
            f"- age_hours: {item.get('age_hours')}",
            f"- reason: {item.get('reason')}",
            f"- suggested_action: {item.get('suggested_action')}",
            "",
        ])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "json": str(json_path),
        "latest": str(latest_path),
        "md": str(md_path),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Review stale operational artifacts without deleting anything.")
    ap.add_argument("--review-out", default=str(REVIEW_OUT))
    ap.add_argument("--print-json", action="store_true")
    args = ap.parse_args()

    payload = build_review(Path(args.review_out))
    paths = write_outputs(payload, Path(args.review_out))
    if args.print_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "stale_artifact_review=OK stale={stale} latest={latest}".format(
                stale=payload.get("stale_count", 0),
                latest=paths["latest"],
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
