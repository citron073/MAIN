from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tools.morning_start_guard import evaluate_morning_start, run_morning_start_guard


class MorningStartGuardTest(unittest.TestCase):
    def _write_control(self, path: Path, rows: dict[str, str]) -> None:
        lines = ["key,value"]
        for k, v in rows.items():
            lines.append(f"{k},{v}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_evaluate_blocks_when_drift_is_insufficient(self) -> None:
        decision = evaluate_morning_start(
            {
                "paper_mode": "0",
                "live_enabled": "1",
                "today_on": "1",
                "trade_enabled": "0",
                "start_hour": "10",
                "end_hour": "17",
            },
            {
                "_risk_stop": False,
                "_streak_stop": False,
                "_drift_watch": {
                    "status": "INSUFFICIENT",
                    "resume_ready": False,
                    "trade_paused_by_drift": False,
                    "risk_tightened_by_drift": False,
                    "recent_metrics": {"closed_n": 0},
                    "gate": {"min_recent_closed": 6, "min_baseline_closed": 25},
                    "baseline_metrics": {"closed_n": 32},
                },
            },
            now=datetime(2026, 3, 21, 9, 50, 0),
            auto_enable_trade_enabled=True,
            allow_deep_sample_recovery_on_drift_insufficient=False,
        )
        self.assertEqual(decision["status"], "blocked")
        self.assertIn("drift=INSUFFICIENT", decision["block_reasons"])
        self.assertEqual(decision["resume_outlook"]["summary"], "復帰まで約定あと6件")

    def test_evaluate_allows_sample_recovery_after_previous_day_auto_disable(self) -> None:
        decision = evaluate_morning_start(
            {
                "paper_mode": "0",
                "live_enabled": "1",
                "today_on": "1",
                "trade_enabled": "0",
                "start_hour": "10",
                "end_hour": "17",
            },
            {
                "_risk_stop": False,
                "_streak_stop": False,
                "_drift_watch": {
                    "status": "INSUFFICIENT",
                    "resume_ready": False,
                    "trade_paused_by_drift": False,
                    "risk_tightened_by_drift": False,
                },
            },
            {
                "daily_trade_disabled_day8": "20260319",
                "trade_enabled_disabled_reason": "daily_loss_breach",
                "trade_enabled_disabled_at": "2026-03-19 12:20:15",
            },
            now=datetime(2026, 3, 20, 9, 50, 0),
            auto_enable_trade_enabled=True,
            allow_sample_recovery_on_drift_insufficient=True,
        )
        self.assertEqual(decision["status"], "ready")
        self.assertTrue(decision["sample_recovery_mode"])
        self.assertEqual(decision["sample_recovery_reason"], "previous_day_daily_loss_breach")
        self.assertEqual(decision["updates"]["trade_enabled"], "1")
        self.assertTrue(decision["effective_live_candidate"])

    def test_evaluate_allows_near_threshold_sample_recovery_without_auto_disable(self) -> None:
        decision = evaluate_morning_start(
            {
                "paper_mode": "0",
                "live_enabled": "1",
                "today_on": "1",
                "trade_enabled": "0",
                "start_hour": "10",
                "end_hour": "17",
            },
            {
                "_risk_stop": False,
                "_streak_stop": False,
                "_drift_watch": {
                    "status": "INSUFFICIENT",
                    "resume_ready": False,
                    "trade_paused_by_drift": False,
                    "risk_tightened_by_drift": False,
                    "recent_metrics": {"closed_n": 2},
                    "gate": {"min_recent_closed": 6, "min_baseline_closed": 25},
                    "baseline_metrics": {"closed_n": 32},
                },
            },
            {},
            now=datetime(2026, 3, 31, 9, 50, 0),
            auto_enable_trade_enabled=True,
            allow_sample_recovery_on_drift_insufficient=True,
            sample_recovery_max_remaining_samples=4,
        )
        self.assertEqual(decision["status"], "ready")
        self.assertTrue(decision["sample_recovery_mode"])
        self.assertEqual(decision["sample_recovery_reason"], "low_sample_shortage")
        self.assertEqual(decision["resume_outlook"]["summary"], "復帰まで約定あと4件")
        self.assertEqual(decision["updates"]["trade_enabled"], "1")

    def test_evaluate_blocks_when_sample_shortage_is_too_large(self) -> None:
        decision = evaluate_morning_start(
            {
                "paper_mode": "0",
                "live_enabled": "1",
                "today_on": "1",
                "trade_enabled": "0",
                "start_hour": "10",
                "end_hour": "17",
            },
            {
                "_risk_stop": False,
                "_streak_stop": False,
                "_drift_watch": {
                    "status": "INSUFFICIENT",
                    "resume_ready": False,
                    "trade_paused_by_drift": False,
                    "risk_tightened_by_drift": False,
                    "recent_metrics": {"closed_n": 0},
                    "gate": {"min_recent_closed": 6, "min_baseline_closed": 25},
                    "baseline_metrics": {"closed_n": 32},
                },
            },
            {},
            now=datetime(2026, 4, 1, 9, 50, 0),
            auto_enable_trade_enabled=True,
            allow_sample_recovery_on_drift_insufficient=True,
            sample_recovery_max_remaining_samples=4,
            allow_deep_sample_recovery_on_drift_insufficient=False,
        )
        self.assertEqual(decision["status"], "blocked")
        self.assertIn("drift=INSUFFICIENT", decision["block_reasons"])
        self.assertFalse(decision["sample_recovery_mode"])

    def test_evaluate_allows_deep_sample_recovery_with_tightened_risk(self) -> None:
        decision = evaluate_morning_start(
            {
                "paper_mode": "0",
                "live_enabled": "1",
                "today_on": "1",
                "trade_enabled": "0",
                "observe_only": "0",
                "safety_hard_block": "0",
                "daily_loss_limit_pct": "-1.0",
                "streak_stop_enabled": "0",
                "streak_stop_max_losses": "3",
                "start_hour": "10",
                "end_hour": "17",
            },
            {
                "_risk_stop": False,
                "_streak_stop": False,
                "_drift_watch": {
                    "status": "INSUFFICIENT",
                    "resume_ready": False,
                    "trade_paused_by_drift": False,
                    "risk_tightened_by_drift": False,
                    "recent_metrics": {"closed_n": 0},
                    "gate": {"min_recent_closed": 6, "min_baseline_closed": 25},
                    "baseline_metrics": {"closed_n": 32},
                },
            },
            {},
            now=datetime(2026, 4, 1, 9, 50, 0),
            auto_enable_trade_enabled=True,
            allow_sample_recovery_on_drift_insufficient=True,
            sample_recovery_max_remaining_samples=4,
            allow_deep_sample_recovery_on_drift_insufficient=True,
            deep_sample_recovery_max_remaining_samples=6,
            deep_recovery_daily_loss_limit_pct=-0.30,
            deep_recovery_streak_max_losses=2,
        )
        self.assertEqual(decision["status"], "ready")
        self.assertTrue(decision["sample_recovery_mode"])
        self.assertEqual(decision["sample_recovery_reason"], "deep_sample_shortage")
        self.assertEqual(decision["updates"]["trade_enabled"], "1")
        self.assertEqual(decision["updates"]["daily_loss_limit_pct"], "-0.3")
        self.assertEqual(decision["updates"]["streak_stop_enabled"], "1")
        self.assertEqual(decision["updates"]["streak_stop_max_losses"], "2")

    def test_evaluate_prepares_auto_enable_updates(self) -> None:
        decision = evaluate_morning_start(
            {
                "paper_mode": "0",
                "live_enabled": "1",
                "today_on": "0",
                "trade_enabled": "0",
                "start_hour": "10",
                "end_hour": "17",
            },
            {
                "_risk_stop": False,
                "_streak_stop": False,
                "_drift_watch": {"status": "NORMAL", "resume_ready": True, "canary_ready": True},
            },
            now=datetime(2026, 3, 21, 9, 50, 0),
            auto_enable_today_on=True,
            auto_enable_trade_enabled=True,
        )
        self.assertEqual(decision["status"], "ready")
        self.assertEqual(decision["updates"]["today_on"], "1")
        self.assertEqual(decision["updates"]["trade_enabled"], "1")
        self.assertTrue(decision["effective_live_candidate"])

    def test_run_guard_updates_control_when_ready(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            control_path = root / "CONTROL.csv"
            state_path = root / "state.json"
            secrets_path = root / ".streamlit" / "secrets.toml"
            cursor_path = root / ".streamlit" / "morning_start_guard.json"

            secrets_path.parent.mkdir(parents=True, exist_ok=True)
            secrets_path.write_text("[dashboard_security]\nmorning_start_notify_enabled = false\n", encoding="utf-8")
            self._write_control(
                control_path,
                {
                    "paper_mode": "0",
                    "live_enabled": "1",
                    "today_on": "0",
                    "trade_enabled": "0",
                    "start_hour": "10",
                    "end_hour": "17",
                    "observe_only": "0",
                    "safety_hard_block": "0",
                },
            )
            state_path.write_text(
                json.dumps(
                    {
                        "_risk_stop": False,
                        "_streak_stop": False,
                        "_drift_watch": {"status": "NORMAL", "resume_ready": True, "canary_ready": True},
                    }
                ),
                encoding="utf-8",
            )

            args = argparse.Namespace(
                main_dir=str(root),
                control_path=str(control_path),
                state_path=str(state_path),
                secrets_path=str(secrets_path),
                cursor_path=str(cursor_path),
                run_lock_dir=str(root / ".run_lock"),
                bot_service="",
                window_before_min=20,
                grace_after_min=5,
                auto_enable_today_on=True,
                auto_enable_trade=True,
                allow_drift_warn=False,
                start_bot_service=False,
                notify=False,
                dry_run=False,
                print_json=False,
                trade_event_cursor_path=str(root / ".streamlit" / "trade_event_cursor.json"),
            )

            with patch("tools.morning_start_guard.datetime") as dt_mock:
                dt_mock.now.return_value = datetime(2026, 3, 21, 9, 50, 0)
                dt_mock.side_effect = lambda *a, **k: datetime(*a, **k)
                with patch("tools.morning_start_guard._run_live_preflight", return_value=(True, "ok")):
                    rc = run_morning_start_guard(args)

            self.assertEqual(rc, 0)
            text = control_path.read_text(encoding="utf-8")
            self.assertIn("today_on,1", text)
            self.assertIn("trade_enabled,1", text)
            cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
            self.assertEqual(cursor["last_result"], "ready")
            self.assertEqual(cursor["last_summary"]["resume_outlook"]["summary"], "復帰OK")

    def test_run_guard_skips_outside_window(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            control_path = root / "CONTROL.csv"
            state_path = root / "state.json"
            secrets_path = root / ".streamlit" / "secrets.toml"
            cursor_path = root / ".streamlit" / "morning_start_guard.json"
            secrets_path.parent.mkdir(parents=True, exist_ok=True)
            secrets_path.write_text("", encoding="utf-8")
            self._write_control(
                control_path,
                {
                    "paper_mode": "0",
                    "live_enabled": "1",
                    "today_on": "0",
                    "trade_enabled": "0",
                    "start_hour": "10",
                    "end_hour": "17",
                },
            )
            state_path.write_text(json.dumps({"_drift_watch": {"status": "NORMAL"}}), encoding="utf-8")

            args = argparse.Namespace(
                main_dir=str(root),
                control_path=str(control_path),
                state_path=str(state_path),
                secrets_path=str(secrets_path),
                cursor_path=str(cursor_path),
                run_lock_dir=str(root / ".run_lock"),
                bot_service="",
                window_before_min=20,
                grace_after_min=5,
                auto_enable_today_on=True,
                auto_enable_trade=True,
                allow_drift_warn=False,
                start_bot_service=False,
                notify=False,
                dry_run=False,
                print_json=False,
                trade_event_cursor_path=str(root / ".streamlit" / "trade_event_cursor.json"),
            )

            with patch("tools.morning_start_guard.datetime") as dt_mock:
                dt_mock.now.return_value = datetime(2026, 3, 21, 8, 0, 0)
                dt_mock.side_effect = lambda *a, **k: datetime(*a, **k)
                rc = run_morning_start_guard(args)

            self.assertEqual(rc, 0)
            text = control_path.read_text(encoding="utf-8")
            self.assertIn("today_on,0", text)
            self.assertIn("trade_enabled,0", text)


if __name__ == "__main__":
    unittest.main()
