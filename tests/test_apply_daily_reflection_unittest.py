from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from tools.apply_daily_reflection import apply_daily_reflection_report, run_apply_daily_reflection


class ApplyDailyReflectionTest(unittest.TestCase):
    def test_preview_only_keeps_files_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report_dir = root / "daily_report_out"
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path = report_dir / "daily_reflection_20260318.json"
            control_path = root / "CONTROL.csv"
            state_path = root / "state.json"

            report_path.write_text(
                json.dumps(
                    {
                        "range": {"day8": "20260318"},
                        "goal": {"achieved": False},
                        "reflection": {"suggested_control_updates": {"streak_stop_enabled": "1"}},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            control_path.write_text("key,value\nstreak_stop_enabled,0\n", encoding="utf-8")
            state_path.write_text("{}\n", encoding="utf-8")

            rc = run_apply_daily_reflection(
                argparse.Namespace(
                    target="20260318",
                    daily_report_out_dir=str(report_dir),
                    control_path=str(control_path),
                    state_path=str(state_path),
                    print_suggested=False,
                    apply_control=False,
                    approver="tester",
                    dry_run=False,
                )
            )

            self.assertEqual(rc, 0)
            self.assertIn("streak_stop_enabled,0", control_path.read_text(encoding="utf-8"))
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue("approval" not in report or report["approval"].get("status", "pending") == "pending")

    def test_apply_control_updates_control_report_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report_dir = root / "daily_report_out"
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path = report_dir / "daily_reflection_20260318.json"
            control_path = root / "CONTROL.csv"
            state_path = root / "state.json"

            report_path.write_text(
                json.dumps(
                    {
                        "range": {"day8": "20260318"},
                        "goal": {"achieved": False},
                        "reflection": {
                            "suggested_control_updates": {
                                "streak_stop_enabled": "1",
                                "daily_loss_limit_pct": "-0.50",
                            }
                        },
                        "approval": {"status": "pending"},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            control_path.write_text("key,value\nstreak_stop_enabled,0\ndaily_loss_limit_pct,-1.0\n", encoding="utf-8")
            state_path.write_text("{}\n", encoding="utf-8")

            rc = run_apply_daily_reflection(
                argparse.Namespace(
                    target="20260318",
                    daily_report_out_dir=str(report_dir),
                    control_path=str(control_path),
                    state_path=str(state_path),
                    print_suggested=False,
                    apply_control=True,
                    approver="tester",
                    dry_run=False,
                )
            )

            self.assertEqual(rc, 0)
            ctrl = control_path.read_text(encoding="utf-8")
            self.assertIn("streak_stop_enabled,1", ctrl)
            self.assertIn("daily_loss_limit_pct,-0.50", ctrl)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["approval"]["status"], "approved")
            self.assertEqual(report["approval"]["approved_by"], "tester")
            self.assertEqual(report["applied_control_updates"]["streak_stop_enabled"]["before"], "0")

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["_daily_reflection_apply"]["day8"], "20260318")
            self.assertEqual(state["_daily_reflection_apply"]["approved_by"], "tester")

    def test_apply_daily_reflection_report_supports_auto_approved_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report_dir = root / "daily_report_out"
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path = report_dir / "daily_reflection_20260318.json"
            control_path = root / "CONTROL.csv"
            state_path = root / "state.json"

            report_path.write_text(
                json.dumps(
                    {
                        "range": {"day8": "20260318"},
                        "goal": {"achieved": False},
                        "reflection": {"suggested_control_updates": {"no_paper_hours": "13"}},
                        "approval": {"status": "pending"},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            control_path.write_text("key,value\nno_paper_hours,\n", encoding="utf-8")
            state_path.write_text("{}\n", encoding="utf-8")

            result = apply_daily_reflection_report(
                reflection_path=report_path,
                control_path=control_path,
                state_path=state_path,
                approver="notifier_auto",
                dry_run=False,
                override_updates={"no_paper_hours": "13"},
                approval_status="auto_approved",
                approval_mode="auto",
                approval_note="eligible",
            )

            self.assertEqual(result["approval"]["status"], "auto_approved")
            self.assertEqual(result["approval"]["mode"], "auto")
            self.assertIn("no_paper_hours,13", control_path.read_text(encoding="utf-8"))
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["approval"]["status"], "auto_approved")
            self.assertEqual(report["approval"]["note"], "eligible")


if __name__ == "__main__":
    unittest.main()
