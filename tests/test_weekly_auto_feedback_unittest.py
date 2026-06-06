from __future__ import annotations

import unittest
from datetime import date

from tools.weekly_auto_feedback import (
    _apply_control_updates_to_rows,
    _build_shadow_weekly_review,
    _build_weekly_llm_prompt,
    _resolve_auto_range,
)


class WeeklyAutoFeedbackTest(unittest.TestCase):
    def test_resolve_previous_week_range(self) -> None:
        start8, end8 = _resolve_auto_range("previous-week", date(2026, 3, 9))  # Monday
        self.assertEqual(start8, "20260302")
        self.assertEqual(end8, "20260308")

    def test_apply_control_updates_to_rows(self) -> None:
        rows = [
            ["paper_mode", "0"],
            ["ai_train_weekly_good_hours", "10,11"],
        ]
        updates = {
            "ai_train_weekly_good_hours": "14,15",
            "ai_train_weekly_bad_hours": "11,12",
        }
        out_rows, changed = _apply_control_updates_to_rows(rows, updates)
        self.assertEqual(out_rows[1][1], "14,15")
        self.assertTrue(any(r and r[0] == "ai_train_weekly_bad_hours" for r in out_rows))
        self.assertEqual(changed["ai_train_weekly_good_hours"]["before"], "10,11")
        self.assertEqual(changed["ai_train_weekly_good_hours"]["after"], "14,15")

    def test_build_weekly_llm_prompt_contains_guidance(self) -> None:
        prompt = _build_weekly_llm_prompt(
            report={
                "range": {"start8": "20260323", "end8": "20260329"},
                "weekly_review": {
                    "closed_n": 6,
                    "win_rate_pct": 33.3,
                    "profit_factor": 0.91,
                    "avg_ret_pct": -0.02,
                    "ret_sum_pct": -0.12,
                },
                "ai_feedback": {
                    "good_hours": [10],
                    "bad_hours": [11, 12],
                },
            },
            suggested={"ai_train_weekly_bad_hours": "11,12"},
            control_changed={"ai_train_weekly_bad_hours": {"before": "11", "after": "11,12"}},
            drift_status="INSUFFICIENT",
            shadow_weekly_review={
                "available": True,
                "decision": "保留",
                "reason": "shadow PF差=+0.0100, avg_ret差=+0.0020",
                "pattern_hint": "entry品質不足",
                "pattern_reason": "late_entry 差が +3",
                "main": {"closed_n": 12, "profit_factor": 0.91, "avg_ret_pct": -0.02},
                "shadow": {"closed_n": 12, "profit_factor": 0.92, "avg_ret_pct": -0.018},
                "delta": {"profit_factor": 0.01, "avg_ret_pct": 0.002, "ret_sum_pct": 0.01},
            },
        )
        self.assertIn("closed_n<10", prompt)
        self.assertIn("suggested_count: 1", prompt)
        self.assertIn("changed_count: 1", prompt)
        self.assertIn("drift_status: INSUFFICIENT", prompt)
        self.assertIn("shadow_weekly_decision: 保留", prompt)
        self.assertIn("shadow_weekly_delta: PF差=+0.0100", prompt)
        self.assertIn("shadow_pattern_hint: entry品質不足", prompt)

    def test_build_shadow_weekly_review_promote_candidate(self) -> None:
        review = _build_shadow_weekly_review(
            main_report={
                "weekly_review": {
                    "closed_n": 18,
                    "profit_factor": 0.95,
                    "avg_ret_pct": 0.01,
                    "win_rate_pct": 48.0,
                    "ret_sum_pct": 0.12,
                }
            },
            shadow_report={
                "weekly_review": {
                    "closed_n": 18,
                    "profit_factor": 1.08,
                    "avg_ret_pct": 0.02,
                    "win_rate_pct": 55.0,
                    "ret_sum_pct": 0.24,
                }
            },
            main_pattern_summary={
                "loss_patterns": {"reversal": 2, "weak_follow_through": 2, "late_entry": 3, "other": 0},
                "opportunity_patterns": {"entry_unfilled": 2, "exit_unfilled": 1, "news_avoidance": 4, "time_block": 2, "spread_block": 0},
            },
            shadow_pattern_summary={
                "loss_patterns": {"reversal": 1, "weak_follow_through": 1, "late_entry": 1, "other": 0},
                "opportunity_patterns": {"entry_unfilled": 1, "exit_unfilled": 0, "news_avoidance": 4, "time_block": 2, "spread_block": 0},
            },
        )
        self.assertTrue(review["available"])
        self.assertEqual(review["decision"], "昇格候補")
        self.assertEqual(review["pattern_hint"], "昇格阻害小")

    def test_build_shadow_weekly_review_rollback_candidate(self) -> None:
        review = _build_shadow_weekly_review(
            main_report={
                "weekly_review": {
                    "closed_n": 18,
                    "profit_factor": 1.02,
                    "avg_ret_pct": 0.01,
                    "win_rate_pct": 51.0,
                    "ret_sum_pct": 0.18,
                }
            },
            shadow_report={
                "weekly_review": {
                    "closed_n": 18,
                    "profit_factor": 0.82,
                    "avg_ret_pct": -0.01,
                    "win_rate_pct": 43.0,
                    "ret_sum_pct": -0.05,
                }
            },
            main_pattern_summary={
                "loss_patterns": {"reversal": 1, "weak_follow_through": 1, "late_entry": 1, "other": 0},
                "opportunity_patterns": {"entry_unfilled": 0, "exit_unfilled": 0, "news_avoidance": 2, "time_block": 1, "spread_block": 0},
            },
            shadow_pattern_summary={
                "loss_patterns": {"reversal": 1, "weak_follow_through": 1, "late_entry": 4, "other": 0},
                "opportunity_patterns": {"entry_unfilled": 3, "exit_unfilled": 2, "news_avoidance": 2, "time_block": 1, "spread_block": 0},
            },
        )
        self.assertTrue(review["available"])
        self.assertEqual(review["decision"], "差し戻し")
        self.assertEqual(review["pattern_hint"], "執行品質不足")


if __name__ == "__main__":
    unittest.main()
