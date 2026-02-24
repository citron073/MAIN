from __future__ import annotations

import unittest

import bot


class AILearningTest(unittest.TestCase):
    def test_trendline_slope_positive_negative(self) -> None:
        up_state = {"ltp_history": [100.0 + i for i in range(30)]}
        down_state = {"ltp_history": [130.0 - i for i in range(30)]}
        up = bot.calc_trendline_slope_pct_per_step(up_state, n=20)
        down = bot.calc_trendline_slope_pct_per_step(down_state, n=20)
        self.assertIsNotNone(up)
        self.assertIsNotNone(down)
        assert up is not None
        assert down is not None
        self.assertGreater(up, 0.0)
        self.assertLess(down, 0.0)

    def test_channel_position_and_width(self) -> None:
        state = {"ltp_history": [100.0, 102.0, 101.0, 104.0, 106.0, 107.0, 108.0, 109.0, 110.0, 111.0]}
        pos = bot.calc_channel_position(state, n=8)
        width = bot.calc_channel_width_pct(state, n=8)
        self.assertIsNotNone(pos)
        self.assertIsNotNone(width)
        assert pos is not None
        assert width is not None
        self.assertGreaterEqual(pos, 0.0)
        self.assertLessEqual(pos, 1.0)
        self.assertGreater(width, 0.0)

    def test_loss_small_profit_large_metric(self) -> None:
        samples = [
            {"ai_score": 0.55, "ret_pct": -0.30},
            {"ai_score": 0.58, "ret_pct": -0.20},
            {"ai_score": 0.62, "ret_pct": 0.15},
            {"ai_score": 0.68, "ret_pct": 0.25},
            {"ai_score": 0.72, "ret_pct": 0.40},
            {"ai_score": 0.78, "ret_pct": 0.35},
        ]
        loose = bot._eval_loss_small_profit_large(samples, 0.55)
        strict = bot._eval_loss_small_profit_large(samples, 0.68)
        self.assertGreater(loose["n"], strict["n"])
        self.assertGreater(strict["rr"], loose["rr"])


if __name__ == "__main__":
    unittest.main()
