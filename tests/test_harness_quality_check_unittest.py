from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import harness_quality_check as mod


def _write_harness_docs(root: Path, *, spec: str) -> None:
    base = root / "docs" / "ai_harness"
    base.mkdir(parents=True, exist_ok=True)
    (base / "current_spec.md").write_text(spec, encoding="utf-8")
    (base / "WORKFLOW.md").write_text("# Workflow\n", encoding="utf-8")
    (base / "work_items.json").write_text('{"version": 1, "items": []}\n', encoding="utf-8")
    (base / "constraints.md").write_text("# Harness Constraints\n", encoding="utf-8")
    (base / "definition-of-done.md").write_text("# Definition Of Done\n", encoding="utf-8")
    (base / "review_rubric.md").write_text("# Review Rubric\n", encoding="utf-8")
    (base / "ouroboros_quality_gate.md").write_text(
        "\n".join(
            [
                "# Ouroboros Quality Gate",
                "## 0. 共通ゲート",
                "## 1. 実装前契約",
                "## 2. Shadow / Observe 昇格条件",
                "## 3. Widget / UI 評価基準",
                "## 4. LLM / 日次反省 評価基準",
                "## 5. Review Checklist",
            ]
        ),
        encoding="utf-8",
    )


class HarnessQualityCheckTest(unittest.TestCase):
    def test_ready_spec_passes_contract_check(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_harness_docs(
                root,
                spec="""# Current Feature Spec

Status: READY

## Goal

- Add a local-only report.

## Pre-Implementation Contract

- Allowed Files: tools/example.py, tests/test_example.py
- Runtime Impact: local-only
- Data Contract: no CSV/result changes
- Safety Gate: report-only
- Validation: fast
- Rollback: delete the local report command
""",
            )
            result = mod.run_quality_check(root)
            self.assertTrue(result["ok"], result)

    def test_draft_spec_can_be_warning_when_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_harness_docs(
                root,
                spec="""# Current Feature Spec

Status: DRAFT

## Goal

- ここに今回作るものを1つだけ書く。

## Pre-Implementation Contract

- Allowed Files:
- Runtime Impact: local-only / widget-only / shadow-only / report-only / VM deploy / main-live
- Data Contract:
- Safety Gate: observe / shadow / paper-canary / main-canary / UI-only / LLM-only
- Validation: fast / trade / all-tests
- Rollback:
""",
            )
            result = mod.run_quality_check(root, allow_draft=True)
            self.assertTrue(result["ok"], result)
            self.assertGreater(result["warn_count"], 0)
            self.assertTrue(
                any("Allowed Files" in item["message"] and "Data Contract" in item["message"] for item in result["items"]),
                result,
            )

    def test_ready_spec_with_placeholder_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_harness_docs(
                root,
                spec="""# Current Feature Spec

Status: READY

## Goal

- ここに今回作るものを1つだけ書く。

## Pre-Implementation Contract

- Allowed Files:
- Runtime Impact: local-only / widget-only / shadow-only / report-only / VM deploy / main-live
- Data Contract:
- Safety Gate: observe / shadow / paper-canary / main-canary / UI-only / LLM-only
- Validation: fast / trade / all-tests
- Rollback:
""",
            )
            result = mod.run_quality_check(root)
            self.assertFalse(result["ok"], result)
            self.assertGreater(result["error_count"], 0)


if __name__ == "__main__":
    unittest.main()
