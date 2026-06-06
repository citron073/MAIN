from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from tools import trade_system_review as mod


def _write_log(logs_dir: Path, day8: str, trades: list[tuple[str, float, float, str, str]]) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    with (logs_dir / f"trade_log_{day8}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "time",
                "result",
                "side",
                "price",
                "size",
                "ltp",
                "best_bid",
                "best_ask",
                "spread_pct",
                "limit_pct",
                "ma_fast",
                "ma_slow",
                "trend",
                "signal",
                "note",
                "pos_id",
            ]
        )
        for i, (side, entry, exit_price, result, note) in enumerate(trades, start=1):
            pos_id = f"{day8}-{i}"
            w.writerow(
                [
                    f"{day8[:4]}-{day8[4:6]}-{day8[6:]} 10:{i:02d}:00",
                    "PAPER",
                    side,
                    entry,
                    1,
                    entry,
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    note,
                    pos_id,
                ]
            )
            w.writerow(
                [
                    f"{day8[:4]}-{day8[4:6]}-{day8[6:]} 10:{i+20:02d}:00",
                    result,
                    side,
                    "",
                    1,
                    exit_price,
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    pos_id,
                ]
            )


def _write_control(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "value"])
        w.writerow(["trade_enabled", "0"])
        w.writerow(["paper_mode", "0"])
        w.writerow(["live_enabled", "1"])
        w.writerow(["aiba_style_enabled", "1"])
        w.writerow(["aiba_style_ai_enabled", "0"])


class TradeSystemReviewTest(unittest.TestCase):
    def test_build_review_summarizes_logs_features_and_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            main_logs = root / "logs"
            shadow_logs = root / "logs" / "instances" / "shadow"
            report_out = root / "daily_report_out"
            report_out.mkdir()
            control = root / "CONTROL.csv"
            _write_control(control)
            ai_model = root / "ai_model.json"
            ai_model.write_text('{"ai_enabled": false, "ai_mode": "ADVISORY"}\n', encoding="utf-8")

            _write_log(
                main_logs,
                "20260401",
                [
                    ("BUY", 100.0, 101.0, "PAPER_EXIT_TP", "aiba_ppp=PPP aiba_9=1 phase=C cp_quality=OK"),
                    ("SELL", 100.0, 102.0, "PAPER_EXIT_SL", "aiba_try_fail=1 phase=B"),
                ],
            )
            _write_log(
                shadow_logs,
                "20260401",
                [("BUY", 100.0, 99.0, "PAPER_EXIT_SL", "aiba_ppp=PPP")],
            )

            review = mod.build_review(
                main_logs_dir=main_logs,
                shadow_logs_dir=shadow_logs,
                report_out_dir=report_out,
                control_path=control,
                ai_model_path=ai_model,
                lookback_days=90,
            )

        self.assertEqual(review["main"]["closed_n"], 2)
        self.assertEqual(review["main"]["win_n"], 1)
        self.assertEqual(review["shadow"]["closed_n"], 1)
        self.assertTrue(review["safety"]["local_only"])
        self.assertFalse(review["safety"]["writes_control"])
        self.assertIn("比較対象システムA/B/C: 未指定", review["missing_info"])
        self.assertEqual(review["effective_config"]["values"]["trade_enabled"], False)
        self.assertEqual(review["effective_config"]["values"]["aiba_style_enabled"], True)
        labels = {row["label"] for row in review["main"]["feature_outcomes_top"]}
        self.assertIn("aiba_ppp=PPP", labels)
        self.assertIn("aiba_try_fail=1", labels)
        presence = {row["label"]: row["count"] for row in review["main"]["feature_presence_top"]}
        self.assertEqual(presence["aiba_ppp=PPP"], 1)
        self.assertEqual(presence["phase=C"], 1)
        self.assertTrue(any("trade_enabled is false" in x for x in review["risk_flags"]))

    def test_format_markdown_contains_core_sections(self) -> None:
        review = {
            "generated_at": "2026-04-18 10:00:00",
            "scope": {"days": ["20260401"], "source_mode": "local", "snapshot_dir": ""},
            "effective_config": {
                "bot_version": "v",
                "feature_schema": "schema",
                "values": {"trade_enabled": False},
            },
            "main": {"closed_n": 1, "win_rate_pct": 100.0, "pnl_jpy_sum": 1, "profit_factor_jpy": 8, "sl_rate_pct": 0, "timeout_rate_pct": 0, "feature_outcomes_top": []},
            "shadow": {"closed_n": 0, "win_rate_pct": 0, "pnl_jpy_sum": 0, "profit_factor_jpy": 0, "sl_rate_pct": 0, "timeout_rate_pct": 0},
            "risk_flags": ["flag"],
            "missing_info": ["missing"],
            "hypotheses": [{"hypothesis": "h", "validation": "v"}],
        }
        text = mod.format_markdown(review)
        self.assertIn("# Trade System Review", text)
        self.assertIn("## Effective Config", text)
        self.assertIn("## Hypotheses", text)

    def test_build_review_can_read_vm_snapshot_layout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            snapshot = Path(td) / "snapshot"
            main_dir = snapshot / "MAIN"
            logs_dir = snapshot / "logs"
            shadow_logs = logs_dir / "instances" / "shadow"
            report_out = main_dir / "daily_report_out"
            main_dir.mkdir(parents=True)
            report_out.mkdir(parents=True)
            _write_control(main_dir / "CONTROL.csv")
            (main_dir / "ai_model.json").write_text('{"ai_enabled": true, "ai_mode": "GATE"}\n', encoding="utf-8")
            report_out.joinpath("daily_reflection_20260402.json").write_text("{}\n", encoding="utf-8")
            _write_log(
                logs_dir,
                "20260402",
                [("BUY", 100.0, 103.0, "PAPER_EXIT_TP", "aiba_kuchibashi=1 phase=C")],
            )
            _write_log(
                shadow_logs,
                "20260402",
                [("SELL", 100.0, 101.0, "PAPER_EXIT_SL", "aiba_rev_ppp=1 phase=A")],
            )

            review = mod.build_review(snapshot_dir=snapshot, lookback_days=90)

        self.assertEqual(review["scope"]["source_mode"], "vm_snapshot")
        self.assertEqual(review["scope"]["snapshot_dir"], str(snapshot))
        self.assertTrue(str(review["scope"]["main_logs_dir"]).endswith("/snapshot/logs"))
        self.assertEqual(review["main"]["closed_n"], 1)
        self.assertEqual(review["shadow"]["closed_n"], 1)
        self.assertFalse(any("VM snapshot directory" in x for x in review["missing_info"]))
        self.assertEqual(review["effective_config"]["values"]["ai_enabled"], True)
        text = mod.format_markdown(review)
        self.assertIn("source_mode: vm_snapshot", text)
        self.assertIn("snapshot_dir:", text)


if __name__ == "__main__":
    unittest.main()
