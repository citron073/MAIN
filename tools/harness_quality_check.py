#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
SPEC_PATH = Path("docs/ai_harness/current_spec.md")
QUALITY_GATE_PATH = Path("docs/ai_harness/ouroboros_quality_gate.md")
REQUIRED_DOCS = (
    SPEC_PATH,
    Path("docs/ai_harness/WORKFLOW.md"),
    Path("docs/ai_harness/work_items.json"),
    Path("docs/ai_harness/constraints.md"),
    QUALITY_GATE_PATH,
    Path("docs/ai_harness/definition-of-done.md"),
    Path("docs/ai_harness/review_rubric.md"),
)
REQUIRED_GATE_HEADINGS = (
    "## 0. 共通ゲート",
    "## 1. 実装前契約",
    "## 2. Shadow / Observe 昇格条件",
    "## 3. Widget / UI 評価基準",
    "## 4. LLM / 日次反省 評価基準",
    "## 5. Review Checklist",
)
CONTRACT_FIELDS = (
    "Allowed Files",
    "Runtime Impact",
    "Data Contract",
    "Safety Gate",
    "Validation",
    "Rollback",
)
CHOICE_FIELDS = {"Runtime Impact", "Safety Gate", "Validation"}
PLACEHOLDER_TOKENS = ("ここに", "書く", "local-only /", "observe /", "fast /", "今回やらないこと")


@dataclass(frozen=True)
class CheckItem:
    level: str
    code: str
    message: str

    def as_dict(self) -> Dict[str, str]:
        return {"level": self.level, "code": self.code, "message": self.message}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _status_from_spec(text: str) -> str:
    m = re.search(r"(?m)^Status:\s*([A-Za-z0-9_-]+)\s*$", text)
    return (m.group(1).strip().upper() if m else "")


def _section(text: str, heading: str) -> str:
    pattern = rf"(?ms)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)"
    m = re.search(pattern, text)
    return m.group(1).strip() if m else ""


def _contract_values(spec_text: str) -> Dict[str, str]:
    block = _section(spec_text, "Pre-Implementation Contract")
    values: Dict[str, str] = {}
    for field in CONTRACT_FIELDS:
        m = re.search(rf"(?m)^-[ \t]*{re.escape(field)}:[ \t]*(.*)$", block)
        values[field] = (m.group(1).strip() if m else "")
    return values


def _looks_placeholder(value: str, *, field: Optional[str] = None) -> bool:
    s = str(value or "").strip()
    if not s:
        return True
    if field in CHOICE_FIELDS and " / " in s:
        return True
    return any(tok in s for tok in PLACEHOLDER_TOKENS)


def _goal_is_ready(spec_text: str) -> bool:
    block = _section(spec_text, "Goal")
    if not block:
        return False
    if any(tok in block for tok in PLACEHOLDER_TOKENS):
        return False
    return any(line.strip().startswith("-") and line.strip().strip("- ").strip() for line in block.splitlines())


def run_quality_check(root: Path = ROOT_DIR, *, allow_draft: bool = False) -> Dict[str, Any]:
    root = Path(root)
    items: List[CheckItem] = []

    for rel in REQUIRED_DOCS:
        if not (root / rel).exists():
            items.append(CheckItem("ERROR", "missing_doc", f"required doc missing: {rel}"))

    spec_text = ""
    gate_text = ""
    if (root / SPEC_PATH).exists():
        spec_text = _read_text(root / SPEC_PATH)
    if (root / QUALITY_GATE_PATH).exists():
        gate_text = _read_text(root / QUALITY_GATE_PATH)

    status = _status_from_spec(spec_text)
    if not status:
        items.append(CheckItem("ERROR", "missing_status", f"{SPEC_PATH} has no Status line"))
    elif status != "READY":
        level = "WARN" if allow_draft else "ERROR"
        items.append(CheckItem(level, "spec_not_ready", f"{SPEC_PATH} Status is {status}; mark READY before implementation"))

    for heading in REQUIRED_GATE_HEADINGS:
        if heading not in gate_text:
            items.append(CheckItem("ERROR", "missing_gate_heading", f"{QUALITY_GATE_PATH} missing heading: {heading}"))

    contract = _contract_values(spec_text)
    if status == "READY":
        if not _goal_is_ready(spec_text):
            items.append(CheckItem("ERROR", "goal_placeholder", "Goal is empty or still looks like a placeholder"))
        for field, value in contract.items():
            if _looks_placeholder(value, field=field):
                items.append(CheckItem("ERROR", "contract_incomplete", f"Pre-Implementation Contract field is incomplete: {field}"))
    elif allow_draft:
        missing = [field for field, value in contract.items() if not value]
        if missing:
            items.append(CheckItem("WARN", "contract_draft", f"draft contract has empty fields: {', '.join(missing)}"))

    error_count = sum(1 for item in items if item.level == "ERROR")
    warn_count = sum(1 for item in items if item.level == "WARN")
    return {
        "ok": error_count == 0,
        "status": status or "-",
        "error_count": error_count,
        "warn_count": warn_count,
        "items": [item.as_dict() for item in items],
    }


def format_text(result: Dict[str, Any]) -> str:
    lines = [
        f"harness_quality={ 'OK' if result.get('ok') else 'NG' } status={result.get('status')} "
        f"errors={result.get('error_count')} warnings={result.get('warn_count')}"
    ]
    for item in result.get("items", []):
        lines.append(f"[{item.get('level')}] {item.get('code')}: {item.get('message')}")
    return "\n".join(lines)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check Ouroboros lightweight AI harness docs before implementation.")
    p.add_argument("--root", default=str(ROOT_DIR))
    p.add_argument("--allow-draft", action="store_true", help="Treat DRAFT spec as warning instead of error.")
    p.add_argument("--print-json", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    result = run_quality_check(Path(args.root), allow_draft=bool(args.allow_draft))
    if args.print_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_text(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
