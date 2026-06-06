from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import signal_scanner_outcome as mod


class SignalScannerOutcomeTest(unittest.TestCase):
    def test_build_feedback_payload_requires_min_samples_for_fx_priority(self) -> None:
        rows = [
            {"symbol": "USDJPY", "market_type": "FX", "signal": "BUY", "outcome": "HIT_TP", "pnl_pct": "1.2"},
            {"symbol": "USDJPY", "market_type": "FX", "signal": "BUY", "outcome": "HIT_TP", "pnl_pct": "1.1"},
            {"symbol": "USDJPY", "market_type": "FX", "signal": "BUY", "outcome": "HIT_TP", "pnl_pct": "0.9"},
            {"symbol": "AAPL", "market_type": "STOCK", "signal": "BUY", "outcome": "HIT_SL", "pnl_pct": "-0.8"},
            {"symbol": "AAPL", "market_type": "STOCK", "signal": "BUY", "outcome": "HIT_SL", "pnl_pct": "-1.1"},
            {"symbol": "AAPL", "market_type": "STOCK", "signal": "BUY", "outcome": "HIT_TP", "pnl_pct": "0.7"},
        ]
        payload = mod.build_feedback_payload(rows)
        self.assertEqual(payload["by_symbol"]["USDJPY"]["closed_count"], 3)
        self.assertEqual(payload["by_side"]["BUY"]["closed_count"], 6)
        self.assertEqual(payload["by_market_type"]["FX"]["closed_count"], 3)
        self.assertEqual(payload["fx_priority"]["preferred_market"], "NEUTRAL")
        self.assertEqual(payload["fx_priority"]["score_adjustment"], 0)
        self.assertEqual(payload["fx_priority"]["min_closed_required"], 5)

    def test_build_feedback_payload_promotes_fx_priority_after_min_samples(self) -> None:
        rows = [
            {"symbol": "USDJPY", "market_type": "FX", "signal": "BUY", "outcome": "HIT_TP", "pnl_pct": "1.2"},
            {"symbol": "EURUSD", "market_type": "FX", "signal": "BUY", "outcome": "HIT_TP", "pnl_pct": "1.0"},
            {"symbol": "GBPJPY", "market_type": "FX", "signal": "SELL", "outcome": "HIT_TP", "pnl_pct": "0.7"},
            {"symbol": "EURJPY", "market_type": "FX", "signal": "BUY", "outcome": "HIT_TP", "pnl_pct": "0.8"},
            {"symbol": "GBPUSD", "market_type": "FX", "signal": "SELL", "outcome": "HIT_SL", "pnl_pct": "-0.3"},
            {"symbol": "AAPL", "market_type": "STOCK", "signal": "BUY", "outcome": "HIT_SL", "pnl_pct": "-0.8"},
            {"symbol": "NVDA", "market_type": "STOCK", "signal": "BUY", "outcome": "HIT_SL", "pnl_pct": "-1.1"},
            {"symbol": "TSLA", "market_type": "STOCK", "signal": "BUY", "outcome": "HIT_TP", "pnl_pct": "0.7"},
            {"symbol": "AMZN", "market_type": "STOCK", "signal": "SELL", "outcome": "HIT_SL", "pnl_pct": "-0.5"},
            {"symbol": "META", "market_type": "STOCK", "signal": "SELL", "outcome": "HIT_SL", "pnl_pct": "-0.4"},
        ]
        payload = mod.build_feedback_payload(rows)
        self.assertEqual(payload["fx_priority"]["preferred_market"], "FX")
        self.assertEqual(payload["fx_priority"]["score_adjustment"], 5)
        self.assertEqual(payload["fx_priority"]["min_closed_required"], 5)

    def test_save_feedback_json_writes_expected_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            rows = [
                {"symbol": "EURUSD", "market_type": "FX", "signal": "SELL", "outcome": "HIT_TP", "pnl_pct": "1.0"},
                {"symbol": "EURUSD", "market_type": "FX", "signal": "SELL", "outcome": "HIT_SL", "pnl_pct": "-0.5"},
            ]
            with mock.patch.object(mod, "FEEDBACK_JSON", tmpdir / "signal_scanner_feedback_latest.json"), \
                 mock.patch.object(mod, "_now_jst_str", return_value="2026-05-08 19:00:00"):
                mod.save_feedback_json(rows)
            payload = json.loads((tmpdir / "signal_scanner_feedback_latest.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["generated_at_jst"], "2026-05-08 19:00:00")
            self.assertIn("by_symbol", payload)
            self.assertIn("EURUSD", payload["by_symbol"])


if __name__ == "__main__":
    unittest.main()
