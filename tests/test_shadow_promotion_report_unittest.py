from __future__ import annotations

import csv
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Iterable, Tuple

from tools import shadow_promotion_report as mod


Trade = Tuple[str, float, float, str]


def _write_log(logs_dir: Path, day8: str, trades: Iterable[Trade]) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"trade_log_{day8}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
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
        for idx, (side, entry, exit_price, result) in enumerate(trades, start=1):
            pos_id = f"{day8}-{idx}"
            w.writerow([f"{day8[:4]}-{day8[4:6]}-{day8[6:]} 10:{idx:02d}:00", "PAPER", side, entry, 1, entry, "", "", "", "", "", "", "", "", "", pos_id])
            w.writerow(
                [
                    f"{day8[:4]}-{day8[4:6]}-{day8[6:]} 10:{idx+10:02d}:00",
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
                    "exit_tech=NO_FOLLOW_THROUGH" if result == "PAPER_EXIT_TIMEOUT" else "",
                    pos_id,
                ]
            )


def _append_mr_row(logs_dir: Path, day8: str, *, rank: str) -> None:
    path = logs_dir / f"trade_log_{day8}.csv"
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                f"{day8[:4]}-{day8[4:6]}-{day8[6:]} 11:59:00",
                "OBSERVE_MR_TRIGGER",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                f"strategy=MR mr_rank={rank} mr_score=4",
                "",
            ]
        )


def _write_feature_log(logs_dir: Path, day8: str) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"trade_log_{day8}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "result", "side", "price", "size", "ltp", "pos_id", "note"])
        w.writerow(
            [
                f"{day8[:4]}-{day8[4:6]}-{day8[6:]} 10:00:00",
                "PAPER",
                "BUY",
                "100",
                "1",
                "100",
                "p1",
                "phase=C aiba_cross=KUCHIBASHI aiba_ppp=PPP",
            ]
        )
        w.writerow(
            [
                f"{day8[:4]}-{day8[4:6]}-{day8[6:]} 10:05:00",
                "PAPER_EXIT_TP",
                "BUY",
                "",
                "1",
                "101",
                "p1",
                "exit_tech=NEAR_TP_GIVEBACK",
            ]
        )
        w.writerow(
            [
                f"{day8[:4]}-{day8[4:6]}-{day8[6:]} 10:10:00",
                "PAPER",
                "BUY",
                "100",
                "1",
                "100",
                "p2",
                "phase=B aiba_try_fail=1",
            ]
        )
        w.writerow(
            [
                f"{day8[:4]}-{day8[4:6]}-{day8[6:]} 10:15:00",
                "PAPER_EXIT_SL",
                "BUY",
                "",
                "1",
                "99",
                "p2",
                "",
            ]
        )


class ShadowPromotionReportTest(unittest.TestCase):
    def test_build_report_ok_when_shadow_has_enough_good_samples(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            main_logs = root / "logs"
            shadow_logs = root / "logs" / "instances" / "shadow"
            for day8 in ("20260401", "20260402", "20260403"):
                _write_log(main_logs, day8, [("BUY", 100.0, 100.2, "PAPER_EXIT_TP")])
                _write_log(shadow_logs, day8, [("BUY", 100.0, 101.0, "PAPER_EXIT_TP")] * 4)

            report = mod.build_report(
                main_logs_dir=main_logs,
                shadow_logs_dir=shadow_logs,
                lookback_days=3,
                min_days=3,
                min_closed=10,
            )
            self.assertEqual(report["decision"], "OK")
            self.assertEqual(report["shadow"]["closed_n"], 12)
            self.assertGreater(report["shadow"]["pnl_jpy_sum"], 0)
            self.assertEqual(report["shadow"]["tp_rate_pct"], 100.0)

    def test_build_report_ng_when_shadow_has_enough_bad_samples(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            main_logs = root / "logs"
            shadow_logs = root / "logs" / "instances" / "shadow"
            for day8 in ("20260401", "20260402", "20260403"):
                _write_log(shadow_logs, day8, [("BUY", 100.0, 99.0, "PAPER_EXIT_SL")] * 4)

            report = mod.build_report(
                main_logs_dir=main_logs,
                shadow_logs_dir=shadow_logs,
                lookback_days=3,
                min_days=3,
                min_closed=10,
            )
            self.assertEqual(report["decision"], "NG")
            self.assertLess(report["shadow"]["pnl_jpy_sum"], 0)

    def test_main_returns_zero_for_ng_report_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shadow_logs = root / "logs" / "instances" / "shadow"
            for day8 in ("20260401", "20260402", "20260403"):
                _write_log(shadow_logs, day8, [("BUY", 100.0, 99.0, "PAPER_EXIT_SL")] * 4)

            with redirect_stdout(io.StringIO()):
                rc = mod.main(
                    [
                        "--main-logs-dir",
                        str(root / "logs"),
                        "--shadow-logs-dir",
                        str(shadow_logs),
                        "--lookback-days",
                        "3",
                    ]
                )
            self.assertEqual(rc, 0)

            with redirect_stdout(io.StringIO()):
                rc_fail = mod.main(
                    [
                        "--main-logs-dir",
                        str(root / "logs"),
                        "--shadow-logs-dir",
                        str(shadow_logs),
                        "--lookback-days",
                        "3",
                        "--fail-on-ng",
                    ]
                )
            self.assertEqual(rc_fail, 1)

    def test_mr_rank_threshold_can_hold_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shadow_logs = root / "logs" / "instances" / "shadow"
            for day8 in ("20260401", "20260402", "20260403"):
                _write_log(shadow_logs, day8, [("BUY", 100.0, 101.0, "PAPER_EXIT_TP")] * 4)
                _append_mr_row(shadow_logs, day8, rank="A")

            report_ok = mod.build_report(
                main_logs_dir=root / "logs",
                shadow_logs_dir=shadow_logs,
                lookback_days=3,
                min_days=3,
                min_closed=10,
                min_mr_rank_a=3,
            )
            self.assertEqual(report_ok["decision"], "OK")
            self.assertEqual(report_ok["shadow"]["mr_rank_a_n"], 3)

            report_wait = mod.build_report(
                main_logs_dir=root / "logs",
                shadow_logs_dir=shadow_logs,
                lookback_days=3,
                min_days=3,
                min_closed=10,
                min_mr_rank_a=4,
            )
            self.assertEqual(report_wait["decision"], "WAIT")
            self.assertTrue(any("mr_rank_a_n<4" in x for x in report_wait["reasons"]))

    def test_feature_gate_review_is_report_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shadow_logs = root / "logs" / "instances" / "shadow"
            _write_feature_log(shadow_logs, "20260401")

            report = mod.build_report(
                main_logs_dir=root / "logs",
                shadow_logs_dir=shadow_logs,
                days=["20260401"],
                min_days=1,
                min_closed=1,
            )

        gate = report["feature_gate_review"]
        self.assertEqual(gate["status"], "REPORT_ONLY")
        self.assertEqual(gate["decision_impact"], "none")
        self.assertEqual(gate["exit_tech"]["near_tp_giveback_exit_n"], 1)
        self.assertTrue(any(row["label"] == "C" for row in gate["phase_top"]))
        self.assertTrue(any(row["label"] == "aiba_cross=KUCHIBASHI" for row in gate["aiba_top"]))
        text = mod.format_text(report)
        self.assertIn("feature_gate=REPORT_ONLY", text)
        self.assertIn("near_tp:1", text)


if __name__ == "__main__":
    unittest.main()
