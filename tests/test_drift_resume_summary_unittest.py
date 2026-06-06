from __future__ import annotations

import unittest

from tools.drift_resume_summary import build_drift_resume_snapshot, translate_drift_reason_ja


class DriftResumeSummaryTest(unittest.TestCase):
    def test_translate_reason_recent_closed(self) -> None:
        self.assertEqual(translate_drift_reason_ja("recent_closed<6 (2)"), "直近約定が不足 2/6")

    def test_build_snapshot_prefers_recent_sample_gap(self) -> None:
        snap = build_drift_resume_snapshot(
            {
                "status": "INSUFFICIENT",
                "recent_metrics": {"closed_n": 2},
                "baseline_metrics": {"closed_n": 20},
                "gate": {
                    "min_recent_closed": 6,
                    "min_baseline_closed": 20,
                    "resume_require_consecutive_normal": 4,
                    "resume_canary_runs": 2,
                },
                "normal_streak": 0,
                "canary_streak": 0,
                "resume_ready": False,
                "reasons": ["recent_closed<6 (2)"],
            }
        )
        self.assertEqual(snap["phase"], "recent_samples")
        self.assertEqual(snap["summary"], "復帰まで約定あと4件")
        self.assertIn("直近約定が不足 2/6", snap["detail"])

    def test_build_snapshot_uses_canary_when_ready(self) -> None:
        snap = build_drift_resume_snapshot(
            {
                "status": "NORMAL",
                "recent_metrics": {"closed_n": 8},
                "gate": {
                    "min_recent_closed": 6,
                    "resume_require_consecutive_normal": 4,
                    "resume_canary_runs": 2,
                },
                "normal_streak": 4,
                "canary_streak": 1,
                "resume_ready": True,
                "canary_ready": False,
                "canary_active": True,
            }
        )
        self.assertEqual(snap["phase"], "canary_active")
        self.assertEqual(snap["summary"], "カナリア完了まであと1回")


if __name__ == "__main__":
    unittest.main()
