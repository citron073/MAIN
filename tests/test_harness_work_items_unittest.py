from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from tools import harness_work_items as mod


def _write_ledger(root: Path, text: str) -> None:
    base = root / "docs" / "ai_harness"
    base.mkdir(parents=True, exist_ok=True)
    (base / "WORKFLOW.md").write_text("# Workflow\n", encoding="utf-8")
    (base / "work_items.json").write_text(text, encoding="utf-8")


def _write_validate_log(root: Path, mode: str = "fast") -> None:
    h = root / ".harness"
    h.mkdir(parents=True, exist_ok=True)
    (h / "last_validate.log").write_text(f"[harness] mode={mode}\n[harness] OK\n", encoding="utf-8")


class HarnessWorkItemsTest(unittest.TestCase):
    def test_valid_ready_item_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_ledger(
                root,
                """{
  "version": 1,
  "items": [
    {
      "id": "TEST-001",
      "title": "Add report-only check",
      "status": "READY",
      "objective": "Produce a local-only report.",
      "allowed_files": ["tools/example.py", "tests/test_example.py"],
      "runtime_impact": "report-only",
      "safety_gate": "report-only",
      "validation": "fast",
      "blocked_by": [],
      "proof": "fast validation log",
      "rollback": "revert the report-only files"
    }
  ]
}
""",
            )
            result = mod.check_work_items(root)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["ready_count"], 1)

    def test_unknown_dependency_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_ledger(
                root,
                """{
  "version": 1,
  "items": [
    {
      "id": "TEST-002",
      "title": "Blocked task",
      "status": "READY",
      "objective": "Wait for another task.",
      "allowed_files": ["docs/example.md"],
      "runtime_impact": "local-only",
      "safety_gate": "report-only",
      "validation": "manual",
      "blocked_by": ["MISSING-001"],
      "proof": "manual review",
      "rollback": "none"
    }
  ]
}
""",
            )
            result = mod.check_work_items(root)
            self.assertFalse(result["ok"], result)
            self.assertTrue(any(c["code"] == "unknown_dependency" for c in result["checks"]), result)

    def test_main_live_item_warns_but_does_not_fail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_ledger(
                root,
                """{
  "version": 1,
  "items": [
    {
      "id": "TEST-003",
      "title": "Main canary proposal",
      "status": "BACKLOG",
      "objective": "Document a future main-live change.",
      "allowed_files": ["CONTROL.csv"],
      "runtime_impact": "main-live",
      "safety_gate": "main-canary",
      "validation": "trade",
      "blocked_by": [],
      "proof": "trade validation plus approval",
      "rollback": "disable changed control flag"
    }
  ]
}
""",
            )
            result = mod.check_work_items(root)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["warn_count"], 1)

    def test_add_from_spec_creates_item(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_ledger(root, '{"version": 1, "items": []}\n')
            (root / "docs" / "ai_harness" / "current_spec.md").write_text(
                """# Widget Polish

Status: READY

## Goal

- Make the medium widget easier to read.

## Pre-Implementation Contract

- Allowed Files: widget/scriptable/OuroborosWidget.local.js, tests/test_widget_status_unittest.py
- Runtime Impact: widget-only
- Data Contract: no CSV changes
- Safety Gate: UI-only
- Validation: trade
- Rollback: revert widget script changes
""",
                encoding="utf-8",
            )
            item = mod.add_work_item_from_spec(root, item_id="WIDGET-001", status="READY")
            self.assertEqual(item["id"], "WIDGET-001")
            self.assertEqual(item["title"], "Widget Polish")
            self.assertEqual(item["runtime_impact"], "widget-only")
            self.assertEqual(item["safety_gate"], "UI-only")
            self.assertEqual(item["validation"], "trade")
            result = mod.check_work_items(root)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["ready_count"], 1)
            history_path = root / ".harness" / "work_item_history.jsonl"
            self.assertTrue(history_path.exists())
            event = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(event["action"], "add_from_spec")
            self.assertEqual(event["id"], "WIDGET-001")

    def test_set_status_updates_existing_item(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_ledger(
                root,
                """{
  "version": 1,
  "items": [
    {
      "id": "TEST-004",
      "title": "Move status",
      "status": "BACKLOG",
      "objective": "Verify status update.",
      "allowed_files": ["docs/example.md"],
      "runtime_impact": "local-only",
      "safety_gate": "report-only",
      "validation": "manual",
      "blocked_by": [],
      "proof": "manual review",
      "rollback": "set status back"
    }
  ]
}
""",
            )
            _write_validate_log(root, "fast")
            item = mod.set_work_item_status(root, item_id="TEST-004", status="DONE")
            self.assertEqual(item["status"], "DONE")
            result = mod.check_work_items(root)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["active_count"], 0)
            history_path = root / ".harness" / "work_item_history.jsonl"
            event = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(event["action"], "set_status")
            self.assertEqual(event["before_status"], "BACKLOG")
            self.assertEqual(event["status"], "DONE")

    def test_done_requires_matching_validation_log(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_ledger(
                root,
                """{
  "version": 1,
  "items": [
    {
      "id": "TEST-005",
      "title": "Needs trade",
      "status": "HUMAN_REVIEW",
      "objective": "Verify done guard.",
      "allowed_files": ["docs/example.md"],
      "runtime_impact": "local-only",
      "safety_gate": "report-only",
      "validation": "trade",
      "blocked_by": [],
      "proof": "trade validation",
      "rollback": "set status back"
    }
  ]
}
""",
            )
            _write_validate_log(root, "fast")
            with self.assertRaises(RuntimeError):
                mod.set_work_item_status(root, item_id="TEST-005", status="DONE")
            _write_validate_log(root, "trade")
            item = mod.set_work_item_status(root, item_id="TEST-005", status="DONE")
            self.assertEqual(item["status"], "DONE")

    def test_done_blocks_main_live_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_ledger(
                root,
                """{
  "version": 1,
  "items": [
    {
      "id": "TEST-006",
      "title": "Main live",
      "status": "HUMAN_REVIEW",
      "objective": "Verify main-live guard.",
      "allowed_files": ["CONTROL.csv"],
      "runtime_impact": "main-live",
      "safety_gate": "main-canary",
      "validation": "trade",
      "blocked_by": [],
      "proof": "trade validation plus approval",
      "rollback": "set status back"
    }
  ]
}
""",
            )
            _write_validate_log(root, "trade")
            with self.assertRaises(PermissionError):
                mod.set_work_item_status(root, item_id="TEST-006", status="DONE")
            item = mod.set_work_item_status(root, item_id="TEST-006", status="DONE", force=True)
            self.assertEqual(item["status"], "DONE")


if __name__ == "__main__":
    unittest.main()
