import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from tools import trade_log_zero_day_review as mod


class TradeLogZeroDayReviewTest(unittest.TestCase):
    def _write_control(self, path: Path, rows: list[tuple[str, str]]) -> None:
        text = "\n".join([f"{k},{v}" for k, v in rows]) + "\n"
        path.write_text(text, encoding="utf-8")

    def test_build_report_marks_market_time_window(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logs_dir = root / "logs"
            logs_dir.mkdir()
            control_path = root / "CONTROL.csv"
            self._write_control(
                control_path,
                [("start_hour", "10"), ("end_hour", "17"), ("today_on", "1"), ("trade_enabled", "1")],
            )
            now = datetime(2026, 5, 8, 8, 0, 0)
            with mock.patch.object(mod, "_now_jst_naive", return_value=now):
                report = mod.build_report("20260508", logs_dir, control_path)
        self.assertEqual(report["classification"]["category"], "market_time_window")

    def test_build_report_marks_today_off(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logs_dir = root / "logs"
            logs_dir.mkdir()
            control_path = root / "CONTROL.csv"
            self._write_control(
                control_path,
                [("start_hour", "10"), ("end_hour", "17"), ("today_on", "0"), ("trade_enabled", "1")],
            )
            now = datetime(2026, 5, 8, 11, 0, 0)
            with mock.patch.object(mod, "_now_jst_naive", return_value=now):
                report = mod.build_report("20260508", logs_dir, control_path)
        self.assertEqual(report["classification"]["category"], "today_off")
        self.assertEqual(report["classification"]["label"], "today_on=0")

    def test_build_report_marks_main_bot_not_running(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logs_dir = root / "logs"
            logs_dir.mkdir()
            control_path = root / "CONTROL.csv"
            self._write_control(
                control_path,
                [("start_hour", "10"), ("end_hour", "17"), ("today_on", "1"), ("trade_enabled", "1")],
            )
            now = datetime(2026, 5, 8, 11, 0, 0)
            with mock.patch.object(mod, "_now_jst_naive", return_value=now):
                report = mod.build_report("20260508", logs_dir, control_path)
        self.assertEqual(report["classification"]["category"], "main_bot_not_running")
        self.assertFalse(report["main_runtime"]["runner_alive"])

    def test_build_report_marks_no_entries_yet_when_runner_is_alive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logs_dir = root / "logs"
            logs_dir.mkdir()
            control_path = root / "CONTROL.csv"
            run_lock_dir = root / ".run_lock"
            run_lock_dir.mkdir()
            (run_lock_dir / "lockinfo.txt").write_text(f"pid={os.getpid()}\n", encoding="utf-8")
            self._write_control(
                control_path,
                [("start_hour", "10"), ("end_hour", "17"), ("today_on", "1"), ("trade_enabled", "1")],
            )
            now = datetime(2026, 5, 8, 11, 0, 0)
            with mock.patch.object(mod, "_now_jst_naive", return_value=now):
                report = mod.build_report("20260508", logs_dir, control_path, run_lock_dir=run_lock_dir)
        self.assertEqual(report["classification"]["category"], "no_entries_yet")
        self.assertTrue(report["classification"]["evidence"]["runner_alive"])


if __name__ == "__main__":
    unittest.main()
