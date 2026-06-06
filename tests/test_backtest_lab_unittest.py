from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from tools import backtest_lab as mod


def _sample_candles() -> list[dict]:
    start = datetime(2026, 4, 1, 9, 0, 0)
    rows: list[dict] = []
    price = 100.0
    for i in range(30):
        price += 0.12
        rows.append(
            {
                "start": (start + timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M:%S"),
                "open": price - 0.04,
                "high": price + 0.10,
                "low": price - 0.08,
                "close": price,
                "ticks": 3,
            }
        )
    return rows


class BacktestLabTest(unittest.TestCase):
    def test_build_ohlc_from_trade_log_prices(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "trade_log_20260401.csv"
            with log.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["time", "result", "ltp", "note"])
                w.writerow(["2026-04-01 09:00:00", "OBSERVE", "100", ""])
                w.writerow(["2026-04-01 09:01:00", "OBSERVE", "101", ""])
                w.writerow(["2026-04-01 09:05:00", "OBSERVE", "102", ""])

            points = mod.read_price_points([log])
            candles = mod.build_ohlc(points, timeframe_min=5)

        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[0]["open"], 100.0)
        self.assertEqual(candles[0]["high"], 101.0)
        self.assertEqual(candles[0]["close"], 101.0)
        self.assertEqual(candles[1]["close"], 102.0)

    def test_phase_follow_backtest_opens_and_summarizes(self) -> None:
        params = mod.BacktestParams(
            strategy="phase_follow",
            timeframe_min=5,
            fast_n=3,
            slow_n=8,
            tp_pct=0.10,
            sl_pct=0.20,
            max_hold_bars=6,
        )
        result = mod.run_backtest(_sample_candles(), params)

        self.assertGreater(result["metrics"]["trade_n"], 0)
        self.assertGreaterEqual(result["metrics"]["win_rate_pct"], 0.0)
        self.assertIn("trades", result)
        self.assertIn("candles", result)

    def test_ma_cross_signal_detects_golden_cross(self) -> None:
        candles = []
        start = datetime(2026, 4, 1, 9, 0, 0)
        prices = [100, 100, 100, 100, 100, 90, 90, 90, 120]
        for i, price in enumerate(prices):
            candles.append(
                {
                    "start": (start + timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M:%S"),
                    "open": float(price),
                    "high": float(price) + 0.1,
                    "low": float(price) - 0.1,
                    "close": float(price),
                    "ticks": 3,
                }
            )

        side, note = mod.build_signal(candles, mod.BacktestParams(strategy="ma_cross", fast_n=3, slow_n=6))

        self.assertEqual(side, "BUY")
        self.assertIn("golden", note)


if __name__ == "__main__":
    unittest.main()
