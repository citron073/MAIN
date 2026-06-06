from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from tools import mr_observe_summary as mod


class MrObserveSummaryTest(unittest.TestCase):
    def test_build_summary_counts_mr_fields(self) -> None:
        rows = [
            {
                "time": "2026-04-09 10:00:00",
                "result": "OBSERVE_MR",
                "trend": "UP",
                "signal": "BUY_CANDIDATE",
                "note": "strategy=MR mr_score=3 mr_rank=B mr_level_type=support mr_reclaim=0",
            },
            {
                "time": "2026-04-09 10:05:00",
                "result": "OBSERVE_MR_TRIGGER",
                "trend": "DOWN",
                "signal": "SELL_CANDIDATE",
                "note": "strategy=MR mr_score=4 mr_rank=A mr_level_type=resistance mr_reclaim=1",
            },
            {
                "time": "2026-04-09 10:10:00",
                "result": "OBSERVE_NO_SIGNAL",
                "trend": "UNKNOWN",
                "signal": "NONE",
                "note": "",
            },
            {
                "time": "2026-04-09 10:15:00",
                "result": "PAPER",
                "trend": "DOWN",
                "signal": "SELL_CANDIDATE",
                "note": "mr_paper=1 strategy=MR mr_rank=A mr_score=4 mr_reclaim=1",
            },
        ]
        summary = mod.build_summary(rows, day8="20260409", tail=3)
        self.assertEqual(summary["rows_total"], 4)
        self.assertEqual(summary["mr_rows_total"], 2)
        self.assertEqual(summary["mr_paper_entries_total"], 1)
        self.assertEqual(summary["mr_results"]["OBSERVE_MR"], 1)
        self.assertEqual(summary["mr_results"]["OBSERVE_MR_TRIGGER"], 1)
        self.assertEqual(summary["mr_rank_counts"]["A"], 1)
        self.assertEqual(summary["mr_rank_counts"]["B"], 1)
        self.assertEqual(summary["mr_rank_a_trigger_n"], 1)
        self.assertEqual(summary["mr_rank_a_reclaim_n"], 1)
        self.assertEqual(summary["mr_level_type_counts"]["support"], 1)
        self.assertEqual(summary["mr_level_type_counts"]["resistance"], 1)
        self.assertEqual(summary["mr_reclaim_counts"]["1"], 1)
        self.assertEqual(summary["mr_paper_rank_counts"]["A"], 1)

    def test_resolve_log_path_picks_latest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            for day8 in ("20260408", "20260409"):
                path = base / f"trade_log_{day8}.csv"
                with path.open("w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["time", "result", "note"])
                    w.writerow(["2026-04-09 00:00:00", "OBSERVE_NO_SIGNAL", ""])
            resolved = mod.resolve_log_path(base, None)
            self.assertEqual(resolved.name, "trade_log_20260409.csv")

    def test_build_multi_day_summary_flags_a_rank_paper_candidate(self) -> None:
        summaries = [
            mod.build_summary(
                [
                    {
                        "time": "2026-04-09 10:00:00",
                        "result": "OBSERVE_MR_TRIGGER",
                        "trend": "UP",
                        "signal": "BUY_CANDIDATE",
                        "note": "strategy=MR mr_score=4 mr_rank=A mr_level_type=support mr_reclaim=1",
                    },
                    {
                        "time": "2026-04-09 10:05:00",
                        "result": "OBSERVE_MR",
                        "trend": "UP",
                        "signal": "BUY_CANDIDATE",
                        "note": "strategy=MR mr_score=3 mr_rank=B mr_level_type=support mr_reclaim=1",
                    },
                ],
                day8=day8,
            )
            for day8 in ("20260409", "20260410", "20260411")
        ]
        multi = mod.build_multi_day_summary(summaries, min_days=3, min_rank_a=3)
        self.assertEqual(multi["decision"], "PAPER_CANDIDATE")
        self.assertEqual(multi["mr_rank_counts"]["A"], 3)
        self.assertEqual(multi["mr_rank_a_trigger_n"], 3)
        self.assertEqual(multi["active_days"], 3)

    def test_build_multi_day_summary_waits_for_more_a_rank_samples(self) -> None:
        summaries = [
            mod.build_summary(
                [
                    {
                        "time": "2026-04-09 10:00:00",
                        "result": "OBSERVE_MR",
                        "trend": "UP",
                        "signal": "BUY_CANDIDATE",
                        "note": "strategy=MR mr_score=3 mr_rank=B mr_level_type=support mr_reclaim=1",
                    }
                ],
                day8="20260409",
            )
        ]
        multi = mod.build_multi_day_summary(summaries, min_days=3, min_rank_a=3)
        self.assertEqual(multi["decision"], "WAIT")
        self.assertTrue(any("active_days<3" in x for x in multi["reasons"]))
        self.assertTrue(any("mr_rank_a_n<3" in x for x in multi["reasons"]))


if __name__ == "__main__":
    unittest.main()
