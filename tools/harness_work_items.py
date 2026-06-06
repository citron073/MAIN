#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set


ROOT_DIR = Path(__file__).resolve().parents[1]
WORK_ITEMS_PATH = Path("docs/ai_harness/work_items.json")
WORKFLOW_PATH = Path("docs/ai_harness/WORKFLOW.md")
CURRENT_SPEC_PATH = Path("docs/ai_harness/current_spec.md")
HISTORY_PATH = Path(".harness/work_item_history.jsonl")
VALIDATE_LOG_PATH = Path(".harness/last_validate.log")

ALLOWED_STATUSES = {
    "BACKLOG",
    "READY",
    "IN_PROGRESS",
    "HUMAN_REVIEW",
    "DONE",
    "BLOCKED",
    "ABANDONED",
}
ACTIVE_STATUSES = {"READY", "IN_PROGRESS", "HUMAN_REVIEW"}
ALLOWED_RUNTIME_IMPACTS = {
    "local-only",
    "widget-only",
    "shadow-only",
    "report-only",
    "VM deploy",
    "main-live",
}
ALLOWED_SAFETY_GATES = {
    "observe",
    "shadow",
    "paper-canary",
    "main-canary",
    "UI-only",
    "LLM-only",
    "report-only",
}
ALLOWED_VALIDATIONS = {"fast", "trade", "all-tests", "manual"}
REQUIRED_FIELDS = (
    "id",
    "title",
    "status",
    "objective",
    "allowed_files",
    "runtime_impact",
    "safety_gate",
    "validation",
    "proof",
    "rollback",
)


@dataclass(frozen=True)
class WorkItemCheck:
    level: str
    code: str
    message: str

    def as_dict(self) -> Dict[str, str]:
        return {"level": self.level, "code": self.code, "message": self.message}


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_history(root: Path, *, action: str, item: Dict[str, Any], before: Optional[Dict[str, Any]] = None) -> None:
    history_path = Path(root) / HISTORY_PATH
    history_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "id": item.get("id"),
        "title": item.get("title"),
        "status": item.get("status"),
        "before_status": (before or {}).get("status"),
        "runtime_impact": item.get("runtime_impact"),
        "safety_gate": item.get("safety_gate"),
        "validation": item.get("validation"),
    }
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _items_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = payload.get("items", [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _as_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _item_by_id(items: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for item in items:
        item_id = str(item.get("id", "")).strip()
        if item_id:
            out[item_id] = item
    return out


def _status(item: Dict[str, Any]) -> str:
    return str(item.get("status", "")).strip().upper()


def _is_done(item: Dict[str, Any]) -> bool:
    return _status(item) in {"DONE", "ABANDONED"}


def _blocked_by_open(item: Dict[str, Any], by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    blocked: List[str] = []
    for dep in _as_str_list(item.get("blocked_by")):
        dep_item = by_id.get(dep)
        if dep_item is None or not _is_done(dep_item):
            blocked.append(dep)
    return blocked


def _section(text: str, heading: str) -> str:
    pattern = rf"(?ms)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)"
    m = re.search(pattern, text)
    return m.group(1).strip() if m else ""


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s.lstrip("# ").strip()
    return "Spec work item"


def _first_bullet(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("-"):
            return s.lstrip("- ").strip()
    return ""


def _contract_values(spec_text: str) -> Dict[str, str]:
    block = _section(spec_text, "Pre-Implementation Contract")
    values: Dict[str, str] = {}
    for field in ("Allowed Files", "Runtime Impact", "Safety Gate", "Validation", "Rollback"):
        m = re.search(rf"(?m)^-[ \t]*{re.escape(field)}:[ \t]*(.*)$", block)
        values[field] = (m.group(1).strip() if m else "")
    return values


def _split_allowed_files(value: str) -> List[str]:
    out: List[str] = []
    for part in str(value or "").split(","):
        s = part.strip()
        if s:
            out.append(s)
    return out


def _normalize_choice(value: str, allowed: Set[str], fallback: str) -> str:
    s = str(value or "").strip()
    if s in allowed:
        return s
    return fallback


def _validation_satisfied(root: Path, validation: str) -> bool:
    mode = str(validation or "").strip()
    if mode == "manual":
        return True
    if mode not in {"fast", "trade", "all-tests"}:
        return False
    log_path = Path(root) / VALIDATE_LOG_PATH
    if not log_path.exists():
        return False
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    if "[harness] OK" not in text:
        return False
    found = re.findall(r"(?m)^\[harness\] mode=([A-Za-z0-9_-]+)\s*$", text)
    if not found:
        return False
    last_mode = found[-1]
    if mode == "fast":
        return last_mode in {"fast", "trade", "all-tests"}
    if mode == "trade":
        return last_mode in {"trade", "all-tests"}
    return last_mode == "all-tests"


def _assert_can_mark_done(root: Path, item: Dict[str, Any], *, force: bool = False) -> None:
    if force:
        return
    runtime_impact = str(item.get("runtime_impact", "")).strip()
    if runtime_impact in {"main-live", "VM deploy"}:
        raise PermissionError(f"{item.get('id')} requires explicit --force before DONE because runtime_impact={runtime_impact}")
    validation = str(item.get("validation", "")).strip() or "manual"
    if not _validation_satisfied(root, validation):
        raise RuntimeError(f"{item.get('id')} cannot move to DONE: latest validation log does not satisfy validation={validation}")


def work_item_from_spec(spec_text: str, *, item_id: str, status: str = "BACKLOG", title: str = "") -> Dict[str, Any]:
    contract = _contract_values(spec_text)
    goal = _first_bullet(_section(spec_text, "Goal")) or _first_heading(spec_text)
    validation = _normalize_choice(contract.get("Validation", ""), ALLOWED_VALIDATIONS, "manual")
    runtime_impact = _normalize_choice(contract.get("Runtime Impact", ""), ALLOWED_RUNTIME_IMPACTS, "local-only")
    safety_gate = _normalize_choice(contract.get("Safety Gate", ""), ALLOWED_SAFETY_GATES, "report-only")
    return {
        "id": str(item_id).strip(),
        "title": str(title or _first_heading(spec_text)).strip(),
        "status": str(status or "BACKLOG").strip().upper(),
        "objective": goal,
        "allowed_files": _split_allowed_files(contract.get("Allowed Files", "")) or [str(CURRENT_SPEC_PATH)],
        "runtime_impact": runtime_impact,
        "safety_gate": safety_gate,
        "validation": validation,
        "blocked_by": [],
        "proof": f"{validation} validation and human review",
        "rollback": contract.get("Rollback", "").strip() or "revert the files changed by this work item",
    }


def add_work_item_from_spec(
    root: Path = ROOT_DIR,
    *,
    item_id: str,
    status: str = "BACKLOG",
    title: str = "",
    replace: bool = False,
) -> Dict[str, Any]:
    root = Path(root)
    items_path = root / WORK_ITEMS_PATH
    spec_path = root / CURRENT_SPEC_PATH
    if not spec_path.exists():
        raise FileNotFoundError(f"missing spec: {CURRENT_SPEC_PATH}")
    payload = _read_json(items_path) if items_path.exists() else {"version": 1, "items": []}
    items = _items_from_payload(payload)
    item = work_item_from_spec(spec_path.read_text(encoding="utf-8"), item_id=item_id, status=status, title=title)
    existing_idx = next((idx for idx, cur in enumerate(items) if str(cur.get("id", "")).strip() == item["id"]), None)
    if existing_idx is not None and not replace:
        raise ValueError(f"work item already exists: {item['id']} (pass --replace to update)")
    if existing_idx is None:
        items.append(item)
        action = "add_from_spec"
        before = None
    else:
        before = dict(items[existing_idx])
        items[existing_idx] = item
        action = "replace_from_spec"
    payload["version"] = int(payload.get("version") or 1)
    payload["updated_at"] = date.today().isoformat()
    payload["items"] = items
    _write_json(items_path, payload)
    _append_history(root, action=action, item=item, before=before)
    return item


def set_work_item_status(
    root: Path = ROOT_DIR,
    *,
    item_id: str,
    status: str,
    force: bool = False,
) -> Dict[str, Any]:
    root = Path(root)
    items_path = root / WORK_ITEMS_PATH
    if not items_path.exists():
        raise FileNotFoundError(f"missing work item ledger: {WORK_ITEMS_PATH}")
    next_status = str(status or "").strip().upper()
    if next_status not in ALLOWED_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_STATUSES))
        raise ValueError(f"invalid status: {next_status}; allowed: {allowed}")
    payload = _read_json(items_path)
    items = _items_from_payload(payload)
    target_id = str(item_id or "").strip()
    for item in items:
        if str(item.get("id", "")).strip() == target_id:
            if next_status == "DONE":
                check_result = check_work_items(root)
                if not check_result.get("ok"):
                    raise RuntimeError(f"{target_id} cannot move to DONE: work item ledger has errors")
                _assert_can_mark_done(root, item, force=force)
            before = dict(item)
            item["status"] = next_status
            payload["updated_at"] = date.today().isoformat()
            payload["items"] = items
            _write_json(items_path, payload)
            _append_history(root, action="set_status", item=item, before=before)
            return item
    raise KeyError(f"unknown work item id: {target_id}")


def check_work_items(root: Path = ROOT_DIR) -> Dict[str, Any]:
    root = Path(root)
    items_path = root / WORK_ITEMS_PATH
    workflow_path = root / WORKFLOW_PATH
    checks: List[WorkItemCheck] = []

    if not workflow_path.exists():
        checks.append(WorkItemCheck("ERROR", "missing_workflow", f"required workflow doc missing: {WORKFLOW_PATH}"))
    if not items_path.exists():
        checks.append(WorkItemCheck("ERROR", "missing_work_items", f"required work item ledger missing: {WORK_ITEMS_PATH}"))
        return _result([], checks)

    try:
        payload = _read_json(items_path)
    except Exception as e:
        checks.append(WorkItemCheck("ERROR", "invalid_json", f"{WORK_ITEMS_PATH} is not valid JSON: {e}"))
        return _result([], checks)

    items = _items_from_payload(payload)
    if not isinstance(payload.get("items", []), list):
        checks.append(WorkItemCheck("ERROR", "items_not_list", f"{WORK_ITEMS_PATH} must contain an items list"))

    seen: Set[str] = set()
    by_id = _item_by_id(items)
    for idx, item in enumerate(items):
        item_id = str(item.get("id", "")).strip()
        label = item_id or f"items[{idx}]"

        for field in REQUIRED_FIELDS:
            value = item.get(field)
            if value in (None, "", []):
                checks.append(WorkItemCheck("ERROR", "missing_field", f"{label} missing required field: {field}"))

        if item_id:
            if item_id in seen:
                checks.append(WorkItemCheck("ERROR", "duplicate_id", f"duplicate work item id: {item_id}"))
            seen.add(item_id)

        status = _status(item)
        if status and status not in ALLOWED_STATUSES:
            checks.append(WorkItemCheck("ERROR", "invalid_status", f"{label} has invalid status: {status}"))

        runtime_impact = str(item.get("runtime_impact", "")).strip()
        if runtime_impact and runtime_impact not in ALLOWED_RUNTIME_IMPACTS:
            checks.append(WorkItemCheck("ERROR", "invalid_runtime_impact", f"{label} has invalid runtime_impact: {runtime_impact}"))

        safety_gate = str(item.get("safety_gate", "")).strip()
        if safety_gate and safety_gate not in ALLOWED_SAFETY_GATES:
            checks.append(WorkItemCheck("ERROR", "invalid_safety_gate", f"{label} has invalid safety_gate: {safety_gate}"))

        validation = str(item.get("validation", "")).strip()
        if validation and validation not in ALLOWED_VALIDATIONS:
            checks.append(WorkItemCheck("ERROR", "invalid_validation", f"{label} has invalid validation: {validation}"))

        if str(item.get("runtime_impact", "")).strip() == "main-live":
            checks.append(WorkItemCheck("WARN", "main_live_item", f"{label} touches main-live; require explicit human approval"))

        for dep in _as_str_list(item.get("blocked_by")):
            if dep not in by_id:
                checks.append(WorkItemCheck("ERROR", "unknown_dependency", f"{label} blocked_by unknown id: {dep}"))

        if status == "READY":
            open_deps = _blocked_by_open(item, by_id)
            if open_deps:
                checks.append(WorkItemCheck("WARN", "ready_but_blocked", f"{label} is READY but has open dependencies: {', '.join(open_deps)}"))

    return _result(items, checks)


def ready_items(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = _item_by_id(items)
    out: List[Dict[str, Any]] = []
    for item in items:
        if _status(item) == "READY" and not _blocked_by_open(item, by_id):
            out.append(item)
    return out


def _result(items: Sequence[Dict[str, Any]], checks: Sequence[WorkItemCheck]) -> Dict[str, Any]:
    errors = [c for c in checks if c.level == "ERROR"]
    warnings = [c for c in checks if c.level == "WARN"]
    active_count = sum(1 for item in items if _status(item) in ACTIVE_STATUSES)
    return {
        "ok": not errors,
        "items_total": len(items),
        "active_count": active_count,
        "ready_count": len(ready_items(items)),
        "error_count": len(errors),
        "warn_count": len(warnings),
        "items": list(items),
        "ready_items": ready_items(items),
        "checks": [c.as_dict() for c in checks],
    }


def format_text(result: Dict[str, Any], *, show_items: bool = False) -> str:
    lines = [
        "harness_work_items="
        f"{'OK' if result.get('ok') else 'NG'} "
        f"items={result.get('items_total')} active={result.get('active_count')} "
        f"ready={result.get('ready_count')} errors={result.get('error_count')} warnings={result.get('warn_count')}"
    ]
    for check in result.get("checks", []):
        lines.append(f"[{check.get('level')}] {check.get('code')}: {check.get('message')}")
    if show_items:
        for item in result.get("ready_items", []):
            lines.append(f"[READY] {item.get('id')} {item.get('title')} validation={item.get('validation')}")
    return "\n".join(lines)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check the local Symphony-style AI harness work item ledger.")
    p.add_argument("--root", default=str(ROOT_DIR))
    p.add_argument("--print-json", action="store_true")
    p.add_argument("--show-items", action="store_true", help="Print runnable READY items.")
    p.add_argument("--history-path", action="store_true", help="Print the work item history JSONL path.")
    p.add_argument("--add-from-spec", default="", help="Create or update a work item from docs/ai_harness/current_spec.md using this id.")
    p.add_argument("--set-status", default="", help="Update an existing work item status by id.")
    p.add_argument("--status", default="BACKLOG", help="Status to use with --add-from-spec.")
    p.add_argument("--title", default="", help="Optional title override for --add-from-spec.")
    p.add_argument("--replace", action="store_true", help="Replace an existing work item with the same id.")
    p.add_argument("--force", action="store_true", help="Bypass DONE guard for explicitly approved VM deploy/main-live/manual cases.")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    if args.add_from_spec:
        try:
            item = add_work_item_from_spec(
                Path(args.root),
                item_id=str(args.add_from_spec),
                status=str(args.status),
                title=str(args.title),
                replace=bool(args.replace),
            )
        except Exception as e:
            print(f"[ERROR] {e}")
            return 1
        if args.print_json:
            print(json.dumps({"added": item}, ensure_ascii=False, indent=2))
        else:
            print(f"[OK] work item {item['id']} status={item['status']} title={item['title']}")
        return 0
    if args.set_status:
        try:
            item = set_work_item_status(Path(args.root), item_id=str(args.set_status), status=str(args.status), force=bool(args.force))
        except Exception as e:
            print(f"[ERROR] {e}")
            return 1
        if args.print_json:
            print(json.dumps({"updated": item}, ensure_ascii=False, indent=2))
        else:
            print(f"[OK] work item {item['id']} status={item['status']} title={item.get('title')}")
        return 0
    if args.history_path:
        print(str((Path(args.root) / HISTORY_PATH).resolve()))
        return 0
    result = check_work_items(Path(args.root))
    if args.print_json:
        print(json.dumps({k: v for k, v in result.items() if k != "items"}, ensure_ascii=False, indent=2))
    else:
        print(format_text(result, show_items=bool(args.show_items)))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
