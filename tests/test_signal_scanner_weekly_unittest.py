from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import signal_scanner_weekly as mod


class SignalScannerWeeklyTest(unittest.TestCase):
    def test_feedback_adjustment_prefers_fx_and_strong_symbol(self) -> None:
        feedback = {
            "by_symbol": {
                "USDJPY": {"closed_count": 4, "win_rate_pct": 75.0},
            },
            "by_side": {
                "BUY": {"closed_count": 7, "win_rate_pct": 57.0},
            },
            "fx_priority": {
                "preferred_market": "FX",
                "score_adjustment": 5,
            },
        }
        delta, reason = mod._feedback_adjustment("USDJPY", "FX", "BUY", feedback)
        self.assertEqual(delta, 15)
        self.assertIn("symbol:+8", reason)
        self.assertIn("side:+4", reason)
        self.assertIn("market:+5", reason)
        self.assertIn("WR=75.0%", reason)
        self.assertIn("pref=FX", reason)

    def test_feedback_summary_exposes_fx_priority_for_dashboard(self) -> None:
        feedback = {
            "closed_count": 8,
            "fx_priority": {
                "preferred_market": "FX",
                "reason": "FX WR 62.0% > STOCK WR 48.0%",
                "score_adjustment": 5,
                "min_closed_required": 5,
            },
        }
        summary = mod._feedback_summary(feedback)
        self.assertEqual(summary["closed_count"], 8)
        self.assertEqual(summary["preferred_market"], "FX")
        self.assertEqual(summary["min_closed_required"], 5)
        self.assertEqual(summary["score_adjustment"], 5)

    def test_analyze_adds_signal_only_contract_fields(self) -> None:
        ohlcv = {
            "closes": [100.0 + i * 0.2 for i in range(30)],
            "highs": [100.3 + i * 0.2 for i in range(30)],
            "lows": [99.7 + i * 0.2 for i in range(30)],
            "volumes": [1000.0 + i * 10 for i in range(30)],
            "n": 30,
        }
        with mock.patch.object(mod, "fetch_ohlcv", return_value=ohlcv), \
             mock.patch.object(
                 mod,
                 "compute_indicators",
                 return_value={
                     "ma5": 106.0,
                     "ma20": 104.0,
                     "rsi14": 58.0,
                     "atr14": 0.8,
                     "price": 106.5,
                     "prev_close": 106.2,
                 },
             ), \
             mock.patch.object(mod, "_check_daily_alignment", return_value=True):
            result = mod.analyze("USDJPY", "FX", "USDJPY=X", None, 155.0, interval="1h")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["result"], "OBSERVE_OK")
        self.assertEqual(result["mode"], "SIGNAL_ONLY")
        self.assertEqual(result["direction_candidate"], result["signal"])
        self.assertEqual(result["invalidation_price"], result["sl_price"])
        self.assertEqual(result["target_price"], result["tp_price"])
        self.assertEqual(result["max_loss_estimate"], result["risk_per_trade_jpy"])
        self.assertIn("SIGNAL_ONLY_CANDIDATE", result["note"])
        self.assertIn("market=FX", result["note"])
        self.assertIn("symbol=USDJPY", result["note"])
        self.assertIn("side=BUY", result["note"])
        self.assertEqual(result["signal_reason"], result["reason"])

    def test_save_results_marks_observe_no_signal_and_writes_csv_header(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            with mock.patch.object(mod, "REVIEW_OUT", tmpdir), \
                 mock.patch.object(mod, "_day8", return_value="20260508"), \
                 mock.patch.object(mod, "_now_jst_str", return_value="2026-05-08 18:30:00"):
                mod.save_results([], [], "OBSERVE_NO_SIGNAL\n候補なし")

            payload = json.loads((tmpdir / "signal_weekly_20260508.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["result"], "OBSERVE_NO_SIGNAL")
            self.assertEqual(payload["candidate_count"], 0)
            self.assertEqual(payload["goal_reference_pct"], 10.0)
            self.assertEqual(payload["max_weekly_loss_jpy"], 5000)
            self.assertIn("feedback_summary", payload)
            self.assertEqual(payload["feedback_summary"]["preferred_market"], "NEUTRAL")

            csv_path = tmpdir / "signal_weekly_20260508.csv"
            with csv_path.open(encoding="utf-8") as f:
                rows = list(csv.reader(f))
            self.assertGreaterEqual(len(rows), 1)
            self.assertIn("direction_candidate", rows[0])
            self.assertIn("signal_reason", rows[0])
            self.assertIn("note", rows[0])


if __name__ == "__main__":
    unittest.main()
