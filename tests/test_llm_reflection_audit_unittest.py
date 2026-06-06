from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import llm_reflection_audit as mod


class LlmReflectionAuditTest(unittest.TestCase):
    def test_build_audit_accepts_valid_reflection_with_llm_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td)
            (report_dir / "daily_reflection_20260401.json").write_text(
                json.dumps(
                    {
                        "range": {"day8": "20260401"},
                        "reflection": {
                            "win_notes": ["TPが多い"],
                            "loss_notes": ["SLは少ない"],
                            "next_day_actions": ["現設定維持"],
                            "suggested_control_updates": {},
                            "llm_feedback": {
                                "used": True,
                                "reason": "ok",
                                "summary": "勝因: TP優勢。敗因: なし。翌日: 現設定維持。",
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            audit = mod.build_audit(report_dir)
            self.assertTrue(audit["ok"], audit)
            self.assertEqual(audit["llm_used_count"], 1)

    def test_build_audit_rejects_missing_reflection_block(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td)
            (report_dir / "daily_reflection_20260401.json").write_text(
                json.dumps({"range": {"day8": "20260401"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            audit = mod.build_audit(report_dir)
            self.assertFalse(audit["ok"], audit)
            self.assertGreater(audit["error_count"], 0)


if __name__ == "__main__":
    unittest.main()

