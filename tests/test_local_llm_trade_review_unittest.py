from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import local_llm_trade_review as mod


class LocalLlmTradeReviewTest(unittest.TestCase):
    def _write_main_log(self, logs_dir: Path) -> None:
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "trade_log_20260414.csv").write_text(
            "\n".join(
                [
                    "time,result,side,price,size,ltp,pos_id,signal,note",
                    "2026-04-14 10:00:00,PAPER,BUY,100,1,,P1,BUY_CANDIDATE,",
                    "2026-04-14 10:05:00,PAPER_EXIT_TP,BUY,100,1,103,P1,BUY_CANDIDATE,",
                    "2026-04-14 14:00:00,OBSERVE_TIME_BLOCK,,,,,,SELL_CANDIDATE,no_paper_hour",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def _write_mr_log(self, mr_dir: Path) -> None:
        mr_dir.mkdir(parents=True, exist_ok=True)
        (mr_dir / "trade_log_20260414.csv").write_text(
            "\n".join(
                [
                    "time,result,signal,note",
                    "2026-04-14 10:00:00,OBSERVE_MR_TRIGGER,BUY_CANDIDATE,strategy=MR mr_rank=A mr_score=4 mr_level_type=support mr_reclaim=1",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def test_resolve_paths_from_snapshot(self) -> None:
        paths = mod.resolve_paths_from_snapshot(Path("/tmp/snap"))
        self.assertEqual(paths["logs_dir"], Path("/tmp/snap/logs"))
        self.assertEqual(paths["control_path"], Path("/tmp/snap/MAIN/CONTROL.csv"))

    def test_extract_json_object_accepts_fenced_json(self) -> None:
        parsed = mod.extract_json_object('```json\n{"summary_ja":"ok","confidence":"low"}\n```')
        self.assertEqual(parsed["summary_ja"], "ok")

    def test_llm_acceptance_requires_safe_json_shape(self) -> None:
        self.assertTrue(
            mod._llm_advisory_is_accepted(
                {
                    "summary_ja": "保留",
                    "next_safe_steps": ["observe継続"],
                    "control_proposals": [{"key": "x", "apply": False}],
                }
            )
        )
        self.assertFalse(mod._llm_advisory_is_accepted({"summary": {"text": "bad"}, "next_safe_steps": ["x"]}))
        self.assertFalse(
            mod._llm_advisory_is_accepted(
                {"summary_ja": "bad", "next_safe_steps": ["observe/shadow/PAPER前提の安全手順"]}
            )
        )
        self.assertFalse(
            mod._llm_advisory_is_accepted(
                {"summary_ja": "bad", "next_safe_steps": ["x"], "control_proposals": [{"key": "x", "apply": True}]}
            )
        )
        self.assertFalse(
            mod._llm_advisory_is_accepted(
                {"summary_ja": "TPを含む決済はNG。", "next_safe_steps": ["shadow継続"]}
            )
        )

    def test_select_ollama_attempt_models_filters_missing_models(self) -> None:
        models = mod.select_ollama_attempt_models(
            "qwen2.5:3b",
            ["qwen2.5:0.5b", "llama3.2:1b"],
            ["qwen2.5:0.5b", "missing:7b"],
        )
        self.assertEqual(models, ["qwen2.5:0.5b", "llama3.2:1b"])

    def test_build_report_is_proposal_only_without_llm(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logs_dir = root / "logs"
            shadow_dir = root / "logs" / "instances" / "shadow"
            mr_dir = root / "logs" / "instances" / "mr_observe"
            reflection_dir = root / "MAIN" / "daily_report_out"
            reflection_dir.mkdir(parents=True)
            control_path = root / "MAIN" / "CONTROL.csv"
            control_path.parent.mkdir(parents=True, exist_ok=True)
            control_path.write_text("key,value\nno_paper_hours,14\ntrade_enabled,1\n", encoding="utf-8")
            self._write_main_log(logs_dir)
            self._write_main_log(shadow_dir)
            self._write_mr_log(mr_dir)
            (reflection_dir / "daily_reflection_20260414.json").write_text(
                json.dumps({"reflection": {"goal_achieved": False, "next_day_actions": ["観察継続"]}}, ensure_ascii=False),
                encoding="utf-8",
            )

            report = mod.build_report(
                main_logs_dir=logs_dir,
                shadow_logs_dir=shadow_dir,
                mr_logs_dir=mr_dir,
                reflection_dir=reflection_dir,
                control_path=control_path,
                day8="20260414",
                llm_mode="off",
            )

        self.assertTrue(report["safety"]["proposal_only"])
        self.assertFalse(report["safety"]["writes_vm"])
        self.assertFalse(report["safety"]["writes_control"])
        self.assertEqual(report["llm_feedback"]["reason"], "llm_mode=off")
        self.assertIn("ローカルLLMは助言のみ", report["rule_based_recommendations"]["summary_ja"])

    def test_format_markdown_ignores_unaccepted_llm_output(self) -> None:
        text = mod.format_markdown(
            {
                "evidence": {"day8": "20260414"},
                "rule_based_recommendations": {"summary_ja": "rule", "next_safe_steps": [], "paper_experiments": []},
                "llm_feedback": {
                    "used": True,
                    "accepted": False,
                    "reason": "ok_unaccepted",
                    "model": "qwen2.5:0.5b",
                    "raw_text": '{"summary":"bad"}',
                    "parsed_json": {"summary": "bad"},
                },
            }
        )
        self.assertIn("accepted: False", text)
        self.assertIn("ignored: LLM output was not accepted", text)
        self.assertNotIn('{"summary":"bad"}', text)


if __name__ == "__main__":
    unittest.main()
