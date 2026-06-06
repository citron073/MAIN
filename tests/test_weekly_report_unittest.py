from __future__ import annotations

import argparse
import csv
import tempfile
import unittest
from pathlib import Path

import weekly_report


class WeeklyReportTest(unittest.TestCase):
    def _write_log(self, p: Path, rows: list[dict[str, str]]) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=weekly_report.REQUIRED_COLUMNS)
            w.writeheader()
            for r in rows:
                w.writerow(r)

    def test_weekly_review_and_ai_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logs = root / "logs"
            out_dir = root / "weekly_out"

            d1 = [
                {
                    "time": "2026-03-02 10:00:00",
                    "result": "PAPER",
                    "side": "BUY",
                    "price": "100",
                    "size": "0.001",
                    "ltp": "100",
                    "best_bid": "100",
                    "best_ask": "101",
                    "spread_pct": "0.01",
                    "limit_pct": "0.05",
                    "ma_fast": "100",
                    "ma_slow": "99",
                    "trend": "UP",
                    "signal": "BUY_CANDIDATE",
                    "note": "",
                    "pos_id": "20260302-100000-BUY-001",
                },
                {
                    "time": "2026-03-02 10:25:00",
                    "result": "PAPER_EXIT_TP",
                    "side": "BUY",
                    "price": "100",
                    "size": "0.001",
                    "ltp": "101",
                    "best_bid": "101",
                    "best_ask": "102",
                    "spread_pct": "0.01",
                    "limit_pct": "0.05",
                    "ma_fast": "101",
                    "ma_slow": "100",
                    "trend": "UP",
                    "signal": "NONE",
                    "note": "",
                    "pos_id": "20260302-100000-BUY-001",
                },
                {
                    "time": "2026-03-02 12:00:00",
                    "result": "PAPER",
                    "side": "BUY",
                    "price": "100",
                    "size": "0.001",
                    "ltp": "100",
                    "best_bid": "100",
                    "best_ask": "101",
                    "spread_pct": "0.02",
                    "limit_pct": "0.05",
                    "ma_fast": "100",
                    "ma_slow": "99",
                    "trend": "UP",
                    "signal": "BUY_CANDIDATE",
                    "note": "",
                    "pos_id": "20260302-120000-BUY-001",
                },
                {
                    "time": "2026-03-02 12:20:00",
                    "result": "PAPER_EXIT_SL",
                    "side": "BUY",
                    "price": "100",
                    "size": "0.001",
                    "ltp": "99",
                    "best_bid": "99",
                    "best_ask": "100",
                    "spread_pct": "0.02",
                    "limit_pct": "0.05",
                    "ma_fast": "99",
                    "ma_slow": "100",
                    "trend": "DOWN",
                    "signal": "NONE",
                    "note": "",
                    "pos_id": "20260302-120000-BUY-001",
                },
            ]
            d2 = [
                {
                    "time": "2026-03-03 14:00:00",
                    "result": "PAPER",
                    "side": "BUY",
                    "price": "100",
                    "size": "0.001",
                    "ltp": "100",
                    "best_bid": "100",
                    "best_ask": "101",
                    "spread_pct": "0.01",
                    "limit_pct": "0.05",
                    "ma_fast": "100",
                    "ma_slow": "99",
                    "trend": "UP",
                    "signal": "BUY_CANDIDATE",
                    "note": "",
                    "pos_id": "20260303-140000-BUY-001",
                },
                {
                    "time": "2026-03-03 14:20:00",
                    "result": "PAPER_EXIT_TP",
                    "side": "BUY",
                    "price": "100",
                    "size": "0.001",
                    "ltp": "102",
                    "best_bid": "102",
                    "best_ask": "103",
                    "spread_pct": "0.01",
                    "limit_pct": "0.05",
                    "ma_fast": "102",
                    "ma_slow": "100",
                    "trend": "UP",
                    "signal": "NONE",
                    "note": "",
                    "pos_id": "20260303-140000-BUY-001",
                },
            ]
            self._write_log(logs / "trade_log_20260302.csv", d1)
            self._write_log(logs / "trade_log_20260303.csv", d2)

            args = argparse.Namespace(
                target="20260302-20260308",
                start=None,
                end=None,
                out_dir=str(out_dir),
                logs_dir=str(logs),
                week_start="MON",
                strict=False,
            )
            rc, path, report = weekly_report.run_weekly_report(args)
            self.assertEqual(rc, 0)
            self.assertTrue(path.exists())
            self.assertIn("weekly_review", report)
            self.assertIn("ai_feedback", report)
            wr = report["weekly_review"]
            af = report["ai_feedback"]
            self.assertEqual(int(wr.get("closed_n", 0)), 3)
            self.assertIn("by_weekday", wr)
            self.assertIn("by_hour", wr)
            self.assertIn("suggested_control_updates", af)
            self.assertIn("ai_train_weekly_feedback_enabled", af.get("suggested_control_updates", {}))

    def test_prenews_exit_is_counted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logs = root / "logs"
            out_dir = root / "weekly_out"

            rows = [
                {
                    "time": "2026-04-01 12:00:00",
                    "result": "PAPER",
                    "side": "SELL",
                    "price": "100",
                    "size": "0.001",
                    "ltp": "100",
                    "best_bid": "100",
                    "best_ask": "101",
                    "spread_pct": "0.01",
                    "limit_pct": "0.05",
                    "ma_fast": "99",
                    "ma_slow": "100",
                    "trend": "DOWN",
                    "signal": "SELL_CANDIDATE",
                    "note": "",
                    "pos_id": "20260401-120000-SELL-001",
                },
                {
                    "time": "2026-04-01 12:55:00",
                    "result": "PAPER_EXIT_PRENEWS",
                    "side": "SELL",
                    "price": "100",
                    "size": "0.001",
                    "ltp": "100",
                    "best_bid": "100",
                    "best_ask": "101",
                    "spread_pct": "0.01",
                    "limit_pct": "0.05",
                    "ma_fast": "99",
                    "ma_slow": "100",
                    "trend": "DOWN",
                    "signal": "NONE",
                    "note": "NEWS_AHEAD_EXIT LUNCH remain_min=5",
                    "pos_id": "20260401-120000-SELL-001",
                },
            ]
            self._write_log(logs / "trade_log_20260401.csv", rows)

            args = argparse.Namespace(
                target="20260401-20260406",
                start=None,
                end=None,
                out_dir=str(out_dir),
                logs_dir=str(logs),
                week_start="MON",
                strict=False,
            )
            rc, _, report = weekly_report.run_weekly_report(args)
            self.assertEqual(rc, 0)
            self.assertEqual(report["weekly_review"]["exit_reason_breakdown"]["PRENEWS"], 1)


if __name__ == "__main__":
    unittest.main()
