from __future__ import annotations

import unittest

from tools import time_block_review as mod


class TimeBlockReviewTest(unittest.TestCase):
    def test_build_review_groups_reasons_by_hour(self) -> None:
        rows = [
            {"time": "2026-04-14 13:00:00", "result": "OBSERVE_TIME_BLOCK", "signal": "BUY_CANDIDATE", "note": "no_paper_hour"},
            {"time": "2026-04-14 13:05:00", "result": "OBSERVE_TIME_BLOCK", "signal": "SELL_CANDIDATE", "note": "no_paper_hour"},
            {"time": "2026-04-14 16:00:00", "result": "OBSERVE_TIME_BLOCK", "signal": "SELL_CANDIDATE", "note": "eod_entry_window cutoff=15:59:30"},
            {"time": "2026-04-14 10:00:00", "result": "PAPER", "signal": "BUY_CANDIDATE", "note": ""},
        ]
        review = mod.build_review(rows, day8="20260414", control={"no_paper_hours": "13", "start_hour": "10", "end_hour": "17"})
        self.assertEqual(review["time_block_n"], 3)
        self.assertEqual(review["time_block_by_hour"], {"13": 2, "16": 1})
        self.assertEqual(review["time_block_by_reason"]["no_paper_hour"], 2)
        self.assertEqual(review["time_block_by_reason"]["eod_entry_window"], 1)
        self.assertIn("no_paper_hours=13", review["suggestion"])


if __name__ == "__main__":
    unittest.main()
