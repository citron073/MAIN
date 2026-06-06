from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import bot


class RuntimeVersionTest(unittest.TestCase):
    def test_runtime_versions_are_declared(self) -> None:
        self.assertRegex(bot.OUROBOROS_BOT_VERSION, r"^\d{4}\.\d{2}\.\d{2}\.\d+$")
        self.assertEqual(bot.OUROBOROS_FEATURE_SCHEMA_VERSION, "ohlc-chart-pattern-quality-market-phase-transition-near-tp-aiba-phase-fallback-mfe-mae-fib-elliott-v1")

    def test_calc_adverse_pct_tracks_negative_favorable_move(self) -> None:
        self.assertAlmostEqual(float(bot.calc_adverse_pct("BUY", 100.0, 99.0) or 0.0), 1.0, places=6)
        self.assertAlmostEqual(float(bot.calc_adverse_pct("SELL", 100.0, 101.0) or 0.0), 1.0, places=6)
        self.assertAlmostEqual(float(bot.calc_adverse_pct("BUY", 100.0, 101.0) or 0.0), 0.0, places=6)


class DummyClient:
    def __init__(
        self,
        executed_size: float,
        average_price: float = 0.0,
        state: str = "COMPLETED",
        collateral_jpy: float = 0.0,
    ) -> None:
        self.executed_size = executed_size
        self.average_price = average_price
        self.state = state
        self.collateral_jpy = collateral_jpy
        self.oid = "JRF_TEST"
        self.cancel_called = False

    def send_child_order(self, **_: object) -> str:
        return self.oid

    def get_child_orders(self, **_: object):
        return [
            {
                "child_order_state": self.state,
                "executed_size": self.executed_size,
                "average_price": self.average_price,
            }
        ]

    def cancel_child_order(self, **_: object) -> bool:
        self.cancel_called = True
        return True

    def get_collateral_jpy(self) -> float:
        return float(self.collateral_jpy)


class LiveLogicTest(unittest.TestCase):
    def test_result_allowed_contains_mr_observe_results(self) -> None:
        self.assertIn("OBSERVE_MR", bot.RESULT_ALLOWED)
        self.assertIn("OBSERVE_MR_FILTER_NG", bot.RESULT_ALLOWED)
        self.assertIn("OBSERVE_MR_TRIGGER", bot.RESULT_ALLOWED)
        self.assertIn("OBSERVE_PHASE_B", bot.RESULT_ALLOWED)

    def test_build_runtime_config_reads_entry_safety_knobs(self) -> None:
        cfg = bot.build_runtime_config(
            {
                "buy_fast_ma_distance_pct": "0.12",
                "sell_fast_ma_distance_pct": "0.15",
                "trend_flip_cooldown_min": "15",
                "htf15_context_enabled": "1",
                "htf60_context_enabled": "1",
                "htf_context_lookback_n": "9",
                "htf_bias_slope_pct": "0.03",
                "htf60_countertrend_penalty": "0.22",
                "htf15_60_conflict_penalty": "0.28",
                "ma_cross_feature_enabled": "1",
                "ma_cross_recent_lookback_n": "7",
                "ma_cross_min_gap_pct": "0.03",
                "ma_cross_slow_slope_min_pct": "0.01",
                "ma_cross_price_filter_enabled": "1",
                "ma_cross_ai_boost": "0.21",
                "ma_cross_ai_penalty": "0.19",
                "tech_indicators_enabled": "1",
                "rsi_n": "12",
                "rsi_low": "28",
                "rsi_high": "72",
                "bb_n": "18",
                "bb_k": "2.5",
                "atr_n": "11",
                "atr_low_pct": "0.03",
                "atr_high_pct": "0.30",
                "trend_power_lookback_n": "16",
                "trend_power_strong_er": "0.55",
                "tech_ai_boost": "0.17",
                "tech_ai_penalty": "0.23",
                "chart_pattern_enabled": "1",
                "ohlc_timeframe_min": "5",
                "ohlc_max_bars": "180",
                "chart_pattern_min_bar_ticks": "2",
                "chart_pattern_quality_lookback_bars": "6",
                "swing_lookback": "2",
                "double_top_peak_tolerance_pct": "0.31",
                "double_bottom_trough_tolerance_pct": "0.32",
                "shoulder_tolerance_pct": "0.52",
                "head_min_excess_pct": "0.33",
                "neckline_break_confirm_bars": "1",
                "pattern_ai_boost": "0.18",
                "pattern_ai_penalty": "0.24",
                "market_phase_enabled": "1",
                "market_phase_block_b_enabled": "1",
                "market_phase_lookback_n": "18",
                "market_phase_flat_slope_pct": "0.02",
                "market_phase_flat_gap_pct": "0.04",
                "market_phase_range_max_width_pct": "0.35",
                "market_phase_ai_boost": "0.16",
                "market_phase_ai_penalty": "0.27",
                "aiba_style_enabled": "1",
                "aiba_style_ai_enabled": "1",
                "aiba_ma_short_n": "5",
                "aiba_ma_mid_n": "20",
                "aiba_ma_long_n": "60",
                "aiba_slope_min_pct": "0.01",
                "aiba_nine_rule_alert_n": "9",
                "aiba_try_fail_lookback_n": "12",
                "aiba_try_fail_min_count": "2",
                "aiba_style_ai_boost": "0.11",
                "aiba_style_ai_penalty": "0.13",
                "ai_use_htf_context": "1",
                "ai_use_ma_cross": "1",
                "ai_use_technical_indicators": "1",
                "ai_use_chart_patterns": "1",
                "ai_use_market_phase": "1",
                "ai_use_aiba_style": "1",
                "canary_tp_scale": "0.70",
                "weak_progress_exit_enabled": "1",
                "weak_progress_exit_min_hold_min": "30",
                "weak_progress_exit_max_best_fav_pct": "0.05",
                "progress_reversal_exit_enabled": "1",
                "progress_reversal_exit_min_hold_min": "20",
                "progress_reversal_exit_min_best_fav_pct": "0.08",
                "progress_reversal_exit_max_current_fav_pct": "0.03",
                "near_tp_giveback_exit_enabled": "1",
                "near_tp_giveback_exit_min_hold_min": "5",
                "near_tp_giveback_exit_trigger_ratio": "0.85",
                "near_tp_giveback_exit_min_giveback_pct": "0.04",
                "near_tp_giveback_exit_max_current_fav_pct": "0.06",
                "no_follow_through_exit_enabled": "1",
                "no_follow_through_exit_min_hold_min": "5",
                "no_follow_through_exit_max_best_fav_pct": "0.01",
                "no_follow_through_exit_max_current_fav_pct": "0.00",
            },
            {},
        )
        self.assertAlmostEqual(cfg.buy_fast_ma_distance_pct, 0.12, places=9)
        self.assertAlmostEqual(cfg.sell_fast_ma_distance_pct, 0.15, places=9)
        self.assertEqual(cfg.trend_flip_cooldown_min, 15)
        self.assertTrue(cfg.htf15_context_enabled)
        self.assertTrue(cfg.htf60_context_enabled)
        self.assertEqual(cfg.htf_context_lookback_n, 9)
        self.assertAlmostEqual(cfg.htf_bias_slope_pct, 0.03, places=9)
        self.assertAlmostEqual(cfg.htf60_countertrend_penalty, 0.22, places=9)
        self.assertAlmostEqual(cfg.htf15_60_conflict_penalty, 0.28, places=9)
        self.assertTrue(cfg.ma_cross_feature_enabled)
        self.assertEqual(cfg.ma_cross_recent_lookback_n, 7)
        self.assertAlmostEqual(cfg.ma_cross_min_gap_pct, 0.03, places=9)
        self.assertAlmostEqual(cfg.ma_cross_slow_slope_min_pct, 0.01, places=9)
        self.assertTrue(cfg.ma_cross_price_filter_enabled)
        self.assertAlmostEqual(cfg.ma_cross_ai_boost, 0.21, places=9)
        self.assertAlmostEqual(cfg.ma_cross_ai_penalty, 0.19, places=9)
        self.assertTrue(cfg.tech_indicators_enabled)
        self.assertEqual(cfg.rsi_n, 12)
        self.assertAlmostEqual(cfg.rsi_low, 28.0, places=9)
        self.assertAlmostEqual(cfg.rsi_high, 72.0, places=9)
        self.assertEqual(cfg.bb_n, 18)
        self.assertAlmostEqual(cfg.bb_k, 2.5, places=9)
        self.assertEqual(cfg.atr_n, 11)
        self.assertAlmostEqual(cfg.atr_low_pct, 0.03, places=9)
        self.assertAlmostEqual(cfg.atr_high_pct, 0.30, places=9)
        self.assertEqual(cfg.trend_power_lookback_n, 16)
        self.assertAlmostEqual(cfg.trend_power_strong_er, 0.55, places=9)
        self.assertAlmostEqual(cfg.tech_ai_boost, 0.17, places=9)
        self.assertAlmostEqual(cfg.tech_ai_penalty, 0.23, places=9)
        self.assertTrue(cfg.chart_pattern_enabled)
        self.assertEqual(cfg.ohlc_timeframe_min, 5)
        self.assertEqual(cfg.ohlc_max_bars, 180)
        self.assertEqual(cfg.chart_pattern_min_bar_ticks, 2)
        self.assertEqual(cfg.chart_pattern_quality_lookback_bars, 6)
        self.assertEqual(cfg.swing_lookback, 2)
        self.assertAlmostEqual(cfg.double_top_peak_tolerance_pct, 0.31, places=9)
        self.assertAlmostEqual(cfg.double_bottom_trough_tolerance_pct, 0.32, places=9)
        self.assertAlmostEqual(cfg.shoulder_tolerance_pct, 0.52, places=9)
        self.assertAlmostEqual(cfg.head_min_excess_pct, 0.33, places=9)
        self.assertEqual(cfg.neckline_break_confirm_bars, 1)
        self.assertAlmostEqual(cfg.pattern_ai_boost, 0.18, places=9)
        self.assertAlmostEqual(cfg.pattern_ai_penalty, 0.24, places=9)
        self.assertTrue(cfg.market_phase_enabled)
        self.assertTrue(cfg.market_phase_block_b_enabled)
        self.assertEqual(cfg.market_phase_lookback_n, 18)
        self.assertAlmostEqual(cfg.market_phase_flat_slope_pct, 0.02, places=9)
        self.assertAlmostEqual(cfg.market_phase_flat_gap_pct, 0.04, places=9)
        self.assertAlmostEqual(cfg.market_phase_range_max_width_pct, 0.35, places=9)
        self.assertAlmostEqual(cfg.market_phase_ai_boost, 0.16, places=9)
        self.assertAlmostEqual(cfg.market_phase_ai_penalty, 0.27, places=9)
        self.assertTrue(cfg.aiba_style_enabled)
        self.assertTrue(cfg.aiba_style_ai_enabled)
        self.assertEqual(cfg.aiba_ma_short_n, 5)
        self.assertEqual(cfg.aiba_ma_mid_n, 20)
        self.assertEqual(cfg.aiba_ma_long_n, 60)
        self.assertAlmostEqual(cfg.aiba_slope_min_pct, 0.01, places=9)
        self.assertEqual(cfg.aiba_nine_rule_alert_n, 9)
        self.assertEqual(cfg.aiba_try_fail_lookback_n, 12)
        self.assertEqual(cfg.aiba_try_fail_min_count, 2)
        self.assertAlmostEqual(cfg.aiba_style_ai_boost, 0.11, places=9)
        self.assertAlmostEqual(cfg.aiba_style_ai_penalty, 0.13, places=9)
        self.assertTrue(cfg.ai_use_htf_context)
        self.assertTrue(cfg.ai_use_ma_cross)
        self.assertTrue(cfg.ai_use_technical_indicators)
        self.assertTrue(cfg.ai_use_chart_patterns)
        self.assertTrue(cfg.ai_use_market_phase)
        self.assertTrue(cfg.ai_use_aiba_style)
        self.assertAlmostEqual(cfg.canary_tp_scale, 0.70, places=9)
        self.assertTrue(cfg.weak_progress_exit_enabled)
        self.assertEqual(cfg.weak_progress_exit_min_hold_min, 30)
        self.assertAlmostEqual(cfg.weak_progress_exit_max_best_fav_pct, 0.05, places=9)
        self.assertTrue(cfg.progress_reversal_exit_enabled)
        self.assertEqual(cfg.progress_reversal_exit_min_hold_min, 20)
        self.assertAlmostEqual(cfg.progress_reversal_exit_min_best_fav_pct, 0.08, places=9)
        self.assertAlmostEqual(cfg.progress_reversal_exit_max_current_fav_pct, 0.03, places=9)
        self.assertTrue(cfg.near_tp_giveback_exit_enabled)
        self.assertEqual(cfg.near_tp_giveback_exit_min_hold_min, 5)
        self.assertAlmostEqual(cfg.near_tp_giveback_exit_trigger_ratio, 0.85, places=9)
        self.assertAlmostEqual(cfg.near_tp_giveback_exit_min_giveback_pct, 0.04, places=9)
        self.assertAlmostEqual(cfg.near_tp_giveback_exit_max_current_fav_pct, 0.06, places=9)
        self.assertTrue(cfg.no_follow_through_exit_enabled)
        self.assertEqual(cfg.no_follow_through_exit_min_hold_min, 5)
        self.assertAlmostEqual(cfg.no_follow_through_exit_max_best_fav_pct, 0.01, places=9)
        self.assertAlmostEqual(cfg.no_follow_through_exit_max_current_fav_pct, 0.00, places=9)

    def test_market_phase_snapshot_classifies_a_b_c_and_breaks(self) -> None:
        cfg = bot.Cfg(
            market_phase_lookback_n=20,
            market_phase_flat_slope_pct=0.01,
            market_phase_flat_gap_pct=0.05,
            market_phase_range_max_width_pct=0.40,
        )

        up_state = {"ltp_history": [100.0 + i for i in range(40)]}
        up_candles = [
            {"start": "2026-04-17 10:00:00", "open": 137.0, "high": 138.0, "low": 136.0, "close": 137.5, "ticks": 3},
            {"start": "2026-04-17 10:05:00", "open": 138.0, "high": 140.0, "low": 137.8, "close": 139.0, "ticks": 3},
        ]
        up = bot.calc_market_phase_snapshot(up_state, up_candles, price=139.0, cfg=cfg)
        self.assertEqual(up["phase"], "C")
        self.assertTrue(up["up_break"])
        self.assertEqual(up["momentum"], "UP_BREAK")
        self.assertIn("phase=C", bot.format_market_phase_note(up))

        down_state = {"ltp_history": [140.0 - i for i in range(40)]}
        down_candles = [
            {"start": "2026-04-17 10:00:00", "open": 103.0, "high": 104.0, "low": 102.0, "close": 102.5, "ticks": 3},
            {"start": "2026-04-17 10:05:00", "open": 102.0, "high": 102.2, "low": 100.0, "close": 101.0, "ticks": 3},
        ]
        down = bot.calc_market_phase_snapshot(down_state, down_candles, price=101.0, cfg=cfg)
        self.assertEqual(down["phase"], "A")
        self.assertTrue(down["down_break"])
        self.assertEqual(down["momentum"], "DOWN_BREAK")

        flat_state = {"ltp_history": [100.0, 100.1, 99.95, 100.05, 99.9] * 8}
        flat = bot.calc_market_phase_snapshot(flat_state, [], price=100.0, cfg=cfg)
        self.assertEqual(flat["phase"], "B")
        self.assertEqual(flat["phase_reason"], "MA_FLAT")

    def test_market_phase_uses_ohlc_fallback_when_ma_is_unclear(self) -> None:
        cfg = bot.Cfg(
            market_phase_lookback_n=20,
            market_phase_flat_slope_pct=0.01,
            market_phase_flat_gap_pct=0.05,
            market_phase_range_max_width_pct=0.40,
        )
        candles = [
            {"start": f"2026-04-17 10:{i:02d}:00", "open": 100.0 + i * 0.12, "high": 100.1 + i * 0.12, "low": 99.9 + i * 0.12, "close": 100.0 + i * 0.12, "ticks": 1}
            for i in range(8)
        ]
        snap = bot.calc_market_phase_snapshot({"ltp_history": []}, candles, price=100.84, cfg=cfg)

        self.assertEqual(snap["phase"], "C")
        self.assertEqual(snap["phase_reason"], "OHLC_UP_SOFT")
        self.assertIn("phase=C", bot.format_market_phase_note(snap))

    def test_market_phase_transition_state_records_only_real_phase_change(self) -> None:
        state = {}
        now = datetime(2026, 4, 17, 10, 0, 0)
        note0 = bot.update_market_phase_transition_state(
            state,
            {"phase": "B", "phase_reason": "MA_FLAT", "momentum": "none"},
            now,
        )
        self.assertEqual(note0, "")
        self.assertEqual(state["_market_phase"]["phase"], "B")

        note1 = bot.update_market_phase_transition_state(
            state,
            {"phase": "C", "phase_reason": "MA_UP", "momentum": "UP_BREAK"},
            now + timedelta(minutes=5),
        )
        self.assertIn("phase_transition=B->C", note1)
        self.assertEqual(state["_market_phase"]["transition"], "B->C")
        self.assertEqual(state["_market_phase"]["previous_phase"], "B")

    def test_ai_score_uses_market_phase_as_small_context(self) -> None:
        cfg = bot.Cfg()
        cfg.ai_use_spread = False
        cfg.ai_use_trend = False
        cfg.ai_use_ma = False
        cfg.ai_use_time = False
        cfg.ai_use_trendline = False
        cfg.ai_use_channel = False
        cfg.ai_use_htf_context = False
        cfg.ai_use_ma_cross = False
        cfg.ai_use_technical_indicators = False
        cfg.ai_use_chart_patterns = False
        cfg.ai_use_market_phase = True
        cfg.market_phase_enabled = True

        _, buy_comps = bot.AIAdapter().score(
            {"side": "BUY", "market_phase": "C", "market_phase_up_break": True},
            cfg,
        )
        self.assertGreater(float(buy_comps["market_phase"]), 0.0)

        _, sell_comps = bot.AIAdapter().score(
            {"side": "SELL", "market_phase": "C", "market_phase_up_break": True},
            cfg,
        )
        self.assertLess(float(sell_comps["market_phase"]), 0.0)

    def test_aiba_style_snapshot_detects_phase1_labels(self) -> None:
        cfg = bot.Cfg(
            aiba_ma_short_n=3,
            aiba_ma_mid_n=5,
            aiba_ma_long_n=8,
            aiba_nine_rule_alert_n=1,
            aiba_try_fail_min_count=2,
            aiba_try_fail_lookback_n=5,
        )
        up = bot.calc_aiba_style_snapshot(
            {"ltp_history": [10, 10, 10, 10, 10, 10, 10, 10, 14]},
            [],
            price=14.0,
            cfg=cfg,
        )
        self.assertEqual(up["cross_type"], "KUCHIBASHI")
        self.assertEqual(up["ppp_flag"], "PPP")
        self.assertEqual(up["trend"], "UP")
        self.assertTrue(up["nine_rule_alert"])
        self.assertIn("aiba_cross=KUCHIBASHI", bot.format_aiba_style_note(up))

        down = bot.calc_aiba_style_snapshot(
            {"ltp_history": [14, 14, 14, 14, 14, 14, 14, 14, 10]},
            [
                {"start": "2026-04-18 10:00:00", "open": 14, "high": 15, "low": 13, "close": 14, "ticks": 2},
                {"start": "2026-04-18 10:05:00", "open": 13, "high": 14, "low": 12, "close": 13, "ticks": 2},
                {"start": "2026-04-18 10:10:00", "open": 12, "high": 13, "low": 11, "close": 12, "ticks": 2},
            ],
            price=10.0,
            cfg=cfg,
        )
        self.assertEqual(down["cross_type"], "REV_KUCHIBASHI")
        self.assertEqual(down["ppp_flag"], "REV_PPP")
        self.assertTrue(down["try_fail_flag"])
        self.assertEqual(down["try_fail_count"], 2)

    def test_ai_score_uses_aiba_style_only_when_enabled(self) -> None:
        cfg = bot.Cfg(
            ai_use_spread=False,
            ai_use_trend=False,
            ai_use_ma=False,
            ai_use_time=False,
            ai_use_trendline=False,
            ai_use_channel=False,
            ai_use_htf_context=False,
            ai_use_ma_cross=False,
            ai_use_technical_indicators=False,
            ai_use_chart_patterns=False,
            ai_use_market_phase=False,
            ai_use_aiba_style=True,
            aiba_style_enabled=True,
            aiba_style_ai_enabled=True,
            aiba_style_ai_boost=0.20,
            aiba_style_ai_penalty=0.25,
        )
        buy_score, buy_comps = bot.AIAdapter().score(
            {"side": "BUY", "aiba_aligned": True, "aiba_counter": False, "aiba_nine_rule_alert": False},
            cfg,
        )
        sell_score, sell_comps = bot.AIAdapter().score(
            {"side": "BUY", "aiba_aligned": False, "aiba_counter": True, "aiba_nine_rule_alert": True},
            cfg,
        )
        self.assertGreater(buy_score, sell_score)
        self.assertGreater(buy_comps["aiba_style"], 0.0)
        self.assertLess(sell_comps["aiba_style"], 0.0)

    def test_build_runtime_config_reads_mr_knobs(self) -> None:
        cfg = bot.build_runtime_config(
            {
                "mr_observe_enabled": "1",
                "mr_bar_min": "5",
                "mr_level_lookback_n": "32",
                "mr_spike_lookback_n": "10",
                "mr_spike_min_move_pct": "0.25",
                "mr_touch_tolerance_pct": "0.12",
                "mr_ma_cross_lookback_n": "18",
                "mr_range_max_ma_slope_pct": "0.10",
                "mr_range_max_ma_gap_pct": "0.20",
                "mr_stop_min_distance_pct": "1.3",
                "mr_paper_enabled": "1",
                "mr_paper_min_rank": "A",
                "mr_paper_require_trigger": "1",
                "mr_paper_require_reclaim": "1",
            },
            {},
        )
        self.assertTrue(cfg.mr_observe_enabled)
        self.assertEqual(cfg.mr_bar_min, 5)
        self.assertEqual(cfg.mr_level_lookback_n, 32)
        self.assertEqual(cfg.mr_spike_lookback_n, 10)
        self.assertAlmostEqual(cfg.mr_spike_min_move_pct, 0.25, places=9)
        self.assertAlmostEqual(cfg.mr_touch_tolerance_pct, 0.12, places=9)
        self.assertEqual(cfg.mr_ma_cross_lookback_n, 18)
        self.assertAlmostEqual(cfg.mr_range_max_ma_slope_pct, 0.10, places=9)
        self.assertAlmostEqual(cfg.mr_range_max_ma_gap_pct, 0.20, places=9)
        self.assertAlmostEqual(cfg.mr_stop_min_distance_pct, 1.3, places=9)
        self.assertTrue(cfg.mr_paper_enabled)
        self.assertEqual(cfg.mr_paper_min_rank, "A")
        self.assertTrue(cfg.mr_paper_require_trigger)
        self.assertTrue(cfg.mr_paper_require_reclaim)

    def test_build_runtime_config_reads_mr_paper_alias(self) -> None:
        cfg = bot.build_runtime_config(
            {
                "observe_mr_paper_enabled": "1",
                "mr_paper_min_rank": "B",
                "mr_paper_require_trigger": "0",
                "mr_paper_require_reclaim": "0",
            },
            {},
        )
        self.assertTrue(cfg.mr_paper_enabled)
        self.assertEqual(cfg.mr_paper_min_rank, "B")
        self.assertFalse(cfg.mr_paper_require_trigger)
        self.assertFalse(cfg.mr_paper_require_reclaim)

    def test_resolve_mr_paper_promotion_allows_a_trigger_reclaim(self) -> None:
        cfg = bot.Cfg(
            mr_paper_enabled=True,
            mr_paper_min_rank="A",
            mr_paper_require_trigger=True,
            mr_paper_require_reclaim=True,
        )
        ok, note = bot.resolve_mr_paper_promotion(
            "OBSERVE_MR_TRIGGER",
            "strategy=MR mr_score=4 mr_rank=A mr_reclaim=1",
            cfg,
        )
        self.assertTrue(ok)
        self.assertIn("mr_paper=1", note)
        self.assertIn("mr_paper_rank=A", note)

    def test_resolve_mr_paper_promotion_blocks_b_rank_when_min_a(self) -> None:
        cfg = bot.Cfg(
            mr_paper_enabled=True,
            mr_paper_min_rank="A",
            mr_paper_require_trigger=True,
            mr_paper_require_reclaim=True,
        )
        ok, note = bot.resolve_mr_paper_promotion(
            "OBSERVE_MR_TRIGGER",
            "strategy=MR mr_score=3 mr_rank=B mr_reclaim=1",
            cfg,
        )
        self.assertFalse(ok)
        self.assertIn("mr_paper_rank_ng", note)

    def test_resolve_mr_observe_emits_trigger_for_support_reclaim(self) -> None:
        cfg = bot.Cfg(
            observe_only=True,
            mr_observe_enabled=True,
            htf15_context_enabled=True,
            htf60_context_enabled=True,
            mr_bar_min=5,
            mr_level_lookback_n=8,
            mr_spike_lookback_n=5,
            mr_spike_min_move_pct=0.5,
            mr_touch_tolerance_pct=0.12,
            mr_ma_cross_lookback_n=8,
            mr_range_max_ma_slope_pct=0.20,
            mr_range_max_ma_gap_pct=0.30,
        )
        state = {
            "ltp_history": [100.00, 99.98, 100.02, 99.99, 100.01, 99.30, 99.97, 100.15, 100.20],
        }
        result, note = bot.resolve_mr_observe("BUY_CANDIDATE", state, 100.20, 100.05, 100.00, cfg)
        self.assertEqual(result, "OBSERVE_MR_TRIGGER")
        self.assertIn("strategy=MR", note)
        self.assertIn("mr_rank=B", note)
        self.assertIn("mr_score=3", note)
        self.assertIn("mr_reclaim=1", note)
        self.assertIn("mr_level_type=support", note)
        self.assertIn("mr_htf15_bias=", note)
        self.assertIn("mr_htf60_bias=", note)

    def test_resolve_mr_observe_emits_filter_ng_for_trend_like_move(self) -> None:
        cfg = bot.Cfg(
            observe_only=True,
            mr_observe_enabled=True,
            mr_bar_min=5,
            mr_level_lookback_n=8,
            mr_spike_lookback_n=5,
            mr_spike_min_move_pct=0.5,
            mr_touch_tolerance_pct=0.12,
            mr_ma_cross_lookback_n=8,
            mr_range_max_ma_slope_pct=0.05,
            mr_range_max_ma_gap_pct=0.05,
        )
        state = {
            "ltp_history": [100.00, 100.20, 100.40, 100.60, 100.80, 101.00, 101.20, 101.40, 101.60],
        }
        result, note = bot.resolve_mr_observe("BUY_CANDIDATE", state, 101.60, 101.30, 100.80, cfg)
        self.assertEqual(result, "OBSERVE_MR_FILTER_NG")
        self.assertIn("strategy=MR", note)
        self.assertIn("mr_market_regime=trend", note)
        self.assertIn("mr_rank=C", note)

    def test_calc_htf_context_detects_up_and_range_bias(self) -> None:
        state_up = {"ltp_history": [100.0 + (i * 0.2) for i in range(36)]}
        htf15 = bot.calc_htf_context(state_up, group_n=3, lookback_n=8, bias_slope_pct=0.02)
        self.assertEqual(htf15["bias"], "UP")
        self.assertIsNotNone(htf15["trendline_slope_pct_per_step"])
        self.assertIsNotNone(htf15["channel_pos"])

        state_range = {"ltp_history": [100.0, 100.2, 100.0, 100.2, 100.0, 100.2] * 6}
        htf_range = bot.calc_htf_context(state_range, group_n=3, lookback_n=8, bias_slope_pct=0.02)
        self.assertIn(htf_range["bias"], ("RANGE", "NA"))

    def test_calc_ma_cross_snapshot_detects_golden_and_dead(self) -> None:
        golden = bot.calc_ma_cross_snapshot(
            {"ltp_history": [10, 10, 10, 10, 10, 10, 12]},
            fast_n=3,
            slow_n=5,
            price=12,
            recent_lookback_n=3,
            min_gap_pct=0.01,
            slow_slope_min_pct=0.0,
        )
        self.assertEqual(golden["cross_type"], "golden")
        self.assertEqual(golden["recent_cross_type"], "golden")
        self.assertEqual(golden["recent_cross_age_bars"], 0)
        self.assertTrue(golden["strong"])
        self.assertIn("gc_recent=golden", bot.format_ma_cross_note(golden))

        dead = bot.calc_ma_cross_snapshot(
            {"ltp_history": [12, 12, 12, 12, 12, 12, 10]},
            fast_n=3,
            slow_n=5,
            price=10,
            recent_lookback_n=3,
            min_gap_pct=0.01,
            slow_slope_min_pct=0.0,
        )
        self.assertEqual(dead["cross_type"], "dead")
        self.assertEqual(dead["recent_cross_type"], "dead")
        self.assertTrue(dead["strong"])

    def test_calc_technical_indicator_snapshot_detects_zones(self) -> None:
        cfg = bot.Cfg(
            rsi_n=5,
            bb_n=5,
            bb_k=2.0,
            atr_n=5,
            atr_low_pct=0.02,
            atr_high_pct=0.15,
            trend_power_lookback_n=6,
            trend_power_strong_er=0.50,
        )
        state = {"ltp_history": [100, 100, 100, 100, 100, 99, 98, 97, 96, 95]}
        snap = bot.calc_technical_indicator_snapshot(state, price=95.0, cfg=cfg)
        self.assertEqual(snap["rsi_zone"], "oversold")
        self.assertIn(snap["bb_zone"], ("lower", "break_lower"))
        self.assertEqual(snap["atr_regime"], "high")
        self.assertEqual(snap["trend_power_regime"], "strong")
        note = bot.format_technical_indicator_note(snap)
        self.assertIn("ti_rsi_zone=oversold", note)
        self.assertIn("ti_atr_regime=high", note)

    def test_update_ohlc_state_builds_5m_candles(self) -> None:
        state: dict = {}
        cfg = bot.Cfg(ohlc_timeframe_min=5, ohlc_max_bars=10)
        bars1 = bot.update_ohlc_state(
            state,
            now=datetime(2026, 4, 17, 10, 1, 0),
            price=100.0,
            timeframe_min=cfg.ohlc_timeframe_min,
            max_bars=cfg.ohlc_max_bars,
        )
        bars2 = bot.update_ohlc_state(
            state,
            now=datetime(2026, 4, 17, 10, 3, 0),
            price=102.0,
            timeframe_min=cfg.ohlc_timeframe_min,
            max_bars=cfg.ohlc_max_bars,
        )
        bars3 = bot.update_ohlc_state(
            state,
            now=datetime(2026, 4, 17, 10, 5, 0),
            price=101.0,
            timeframe_min=cfg.ohlc_timeframe_min,
            max_bars=cfg.ohlc_max_bars,
        )
        self.assertEqual(len(bars1), 1)
        self.assertEqual(float(bars2[-1]["open"]), 100.0)
        self.assertEqual(float(bars2[-1]["high"]), 102.0)
        self.assertEqual(int(bars2[-1]["ticks"]), 2)
        self.assertEqual(len(state["ohlc_history"]), 1)
        self.assertEqual(len(bars3), 2)
        self.assertEqual(str(bars3[-1]["timestamp"]), "2026-04-17 10:05:00")
        self.assertEqual(int(bars3[-1]["ticks"]), 1)

    def test_calc_chart_pattern_snapshot_detects_confirmed_double_top_and_bottom(self) -> None:
        cfg = bot.Cfg(
            swing_lookback=1,
            double_top_peak_tolerance_pct=0.50,
            double_bottom_trough_tolerance_pct=0.50,
            neckline_break_confirm_bars=1,
            chart_pattern_min_bar_ticks=1,
            chart_pattern_quality_lookback_bars=6,
        )
        top_bars = [
            {"timestamp": f"t{i}", "open": v, "high": h, "low": l, "close": c}
            for i, (v, h, l, c) in enumerate([
                (100, 101, 99, 100),
                (101, 102, 100, 101),
                (102, 103, 101, 102),
                (103, 104, 102, 103),
                (104, 105, 103, 104),
                (104, 106, 103, 105),
                (103, 104, 100, 101),
                (101, 102, 98, 99),
                (100, 103, 99, 102),
                (103, 105.8, 102, 104),
                (101, 102, 97, 97.5),
                (97, 98, 95, 96),
            ])
        ]
        snap_top = bot.calc_chart_pattern_snapshot(top_bars, cfg)
        self.assertEqual(snap_top["pattern_name"], "DOUBLE_TOP")
        self.assertEqual(snap_top["pattern_stage"], "CONFIRMED")
        self.assertEqual(snap_top["pattern_bias"], "SELL")
        self.assertTrue(snap_top["pattern_confirmed"])
        self.assertEqual(snap_top["pattern_quality"], "OK")
        self.assertIn("cp_name=DOUBLE_TOP", bot.format_chart_pattern_note(snap_top))

        bottom_bars = [
            {"timestamp": f"b{i}", "open": v, "high": h, "low": l, "close": c}
            for i, (v, h, l, c) in enumerate([
                (106, 107, 105, 106),
                (105, 106, 104, 105),
                (104, 105, 103, 104),
                (103, 104, 102, 103),
                (102, 103, 100, 101),
                (101, 102, 99, 100),
                (100, 104, 100, 103),
                (103, 105, 101, 104),
                (102, 103, 100, 101),
                (101, 102, 99.2, 100),
                (104, 106, 103, 105),
                (106, 108, 105, 107),
            ])
        ]
        snap_bottom = bot.calc_chart_pattern_snapshot(bottom_bars, cfg)
        self.assertEqual(snap_bottom["pattern_name"], "DOUBLE_BOTTOM")
        self.assertEqual(snap_bottom["pattern_stage"], "CONFIRMED")
        self.assertEqual(snap_bottom["pattern_bias"], "BUY")

    def test_chart_pattern_quality_blocks_ai_weight_for_thin_candles(self) -> None:
        cfg = bot.Cfg(
            swing_lookback=1,
            double_top_peak_tolerance_pct=0.50,
            chart_pattern_min_bar_ticks=2,
            chart_pattern_quality_lookback_bars=6,
            neckline_break_confirm_bars=1,
        )
        thin_bars = [
            {"timestamp": f"t{i}", "open": v, "high": h, "low": l, "close": c, "ticks": 1}
            for i, (v, h, l, c) in enumerate([
                (100, 101, 99, 100),
                (101, 102, 100, 101),
                (102, 103, 101, 102),
                (103, 104, 102, 103),
                (104, 105, 103, 104),
                (104, 106, 103, 105),
                (103, 104, 100, 101),
                (101, 102, 98, 99),
                (100, 103, 99, 102),
                (103, 105.8, 102, 104),
                (101, 102, 97, 97.5),
                (97, 98, 95, 96),
            ])
        ]
        snap = bot.calc_chart_pattern_snapshot(thin_bars, cfg)
        self.assertEqual(snap["pattern_name"], "DOUBLE_TOP")
        self.assertEqual(snap["pattern_quality"], "THIN")
        self.assertIn("cp_quality=THIN", bot.format_chart_pattern_note(snap))

    def test_ai_score_uses_confirmed_chart_pattern_as_light_gate(self) -> None:
        cfg = bot.Cfg(ai_use_chart_patterns=True, chart_pattern_enabled=True, pattern_ai_boost=0.20, pattern_ai_penalty=0.25)
        ai = bot.AIAdapter()
        base = {
            "side": "BUY",
            "trend": "UP",
            "hour": 11,
            "news_blocked": False,
            "spread_pct": 0.05,
            "ma_gap_pct": 0.06,
            "ma_slope_pct_per_step": 0.02,
            "volatility_pct": 0.12,
            "trendline_slope_pct_per_step": 0.01,
            "channel_pos": 0.50,
            "channel_width_pct": 0.20,
        }
        aligned = dict(base, pattern_aligned=True, pattern_counter=False)
        counter = dict(base, pattern_aligned=False, pattern_counter=True)
        aligned_score, aligned_comps = ai.score(aligned, cfg)
        counter_score, counter_comps = ai.score(counter, cfg)
        self.assertGreater(aligned_score, counter_score)
        self.assertGreater(aligned_comps["chart_pattern"], 0)
        self.assertLess(counter_comps["chart_pattern"], 0)

    def test_ai_build_features_includes_htf_context_when_enabled(self) -> None:
        cfg = bot.Cfg(
            htf15_context_enabled=True,
            htf60_context_enabled=True,
            htf_context_lookback_n=8,
            htf_bias_slope_pct=0.02,
            ma_cross_feature_enabled=True,
            tech_indicators_enabled=True,
            chart_pattern_enabled=True,
        )
        state = {"ltp_history": [100.0 for _ in range(20)] + [101.2] + [101.4 + (i * 0.15) for i in range(100)]}
        feats = bot.AIAdapter().build_features(
            cfg=cfg,
            state=state,
            now=datetime(2026, 4, 9, 10, 0, 0),
            side="BUY",
            ltp=118.0,
            spread_pct=0.0002,
            ma_fast=117.0,
            ma_slow=115.0,
            trend="UP",
            blocked_news=False,
        )
        self.assertIn("htf15_bias", feats)
        self.assertIn("htf60_bias", feats)
        self.assertEqual(feats["htf15_bias"], "UP")
        self.assertEqual(feats["htf60_bias"], "UP")
        self.assertIn("ma_cross_recent_type", feats)
        self.assertIn("ma_cross_note", feats)
        self.assertIn("ti_rsi_zone", feats)
        self.assertIn("ti_bb_zone", feats)
        self.assertIn("ti_note", feats)
        self.assertIn("pattern_name", feats)
        self.assertIn("pattern_note", feats)

    def test_ai_score_penalizes_htf15_60_conflict(self) -> None:
        cfg = bot.Cfg(ai_use_htf_context=True)
        ai = bot.AIAdapter()
        base = {
            "side": "BUY",
            "trend": "UP",
            "hour": 14,
            "news_blocked": False,
            "spread_pct": 0.05,
            "ma_gap_pct": 0.04,
            "ma_slope_pct_per_step": 0.015,
            "volatility_pct": 0.20,
            "trendline_slope_pct_per_step": 0.015,
            "channel_pos": 0.58,
            "channel_width_pct": 0.20,
            "htf15_bias": "UP",
            "htf15_trendline_slope_pct_per_step": 0.008,
            "htf15_channel_pos": 0.55,
            "htf15_channel_width_pct": 0.18,
            "htf60_bias": "UP",
        }
        aligned_score, aligned_comps = ai.score(dict(base), cfg)
        conflict = dict(base)
        conflict["htf60_bias"] = "DOWN"
        conflict_score, conflict_comps = ai.score(conflict, cfg)
        self.assertGreater(aligned_score, conflict_score)
        self.assertIn("htf60_countertrend", conflict_comps)
        self.assertIn("htf15_60_conflict", conflict_comps)
        self.assertLess(conflict_score, 0.85)
        self.assertNotIn("htf15_60_conflict", aligned_comps)

    def test_ai_score_rewards_aligned_recent_ma_cross(self) -> None:
        cfg = bot.Cfg(ai_use_ma_cross=True, ma_cross_recent_lookback_n=6)
        ai = bot.AIAdapter()
        base = {
            "side": "BUY",
            "trend": "UP",
            "hour": 11,
            "news_blocked": False,
            "spread_pct": 0.05,
            "ma_gap_pct": 0.06,
            "ma_slope_pct_per_step": 0.02,
            "volatility_pct": 0.12,
            "trendline_slope_pct_per_step": 0.01,
            "channel_pos": 0.50,
            "channel_width_pct": 0.20,
        }
        aligned = dict(base)
        aligned.update({
            "ma_cross_recent_type": "golden",
            "ma_cross_recent_age_bars": 0,
            "ma_cross_recent_aligned": True,
            "ma_cross_recent_counter": False,
            "ma_cross_strong": True,
        })
        counter = dict(base)
        counter.update({
            "ma_cross_recent_type": "dead",
            "ma_cross_recent_age_bars": 0,
            "ma_cross_recent_aligned": False,
            "ma_cross_recent_counter": True,
            "ma_cross_strong": True,
        })
        aligned_score, aligned_comps = ai.score(aligned, cfg)
        counter_score, counter_comps = ai.score(counter, cfg)
        self.assertGreater(aligned_score, counter_score)
        self.assertGreater(aligned_comps["ma_cross"], 0)
        self.assertLess(counter_comps["ma_cross"], 0)

    def test_ai_score_uses_technical_indicators_as_light_gate(self) -> None:
        cfg = bot.Cfg(
            ai_use_technical_indicators=True,
            tech_indicators_enabled=True,
            tech_ai_boost=0.20,
            tech_ai_penalty=0.30,
        )
        ai = bot.AIAdapter()
        base = {
            "side": "BUY",
            "trend": "UP",
            "hour": 11,
            "news_blocked": False,
            "spread_pct": 0.05,
            "ma_gap_pct": 0.06,
            "ma_slope_pct_per_step": 0.02,
            "volatility_pct": 0.12,
            "trendline_slope_pct_per_step": 0.01,
            "channel_pos": 0.50,
            "channel_width_pct": 0.20,
        }
        favorable = dict(base)
        favorable.update({
            "ti_rsi": 55.0,
            "ti_atr_regime": "normal",
            "ti_trend_power_regime": "strong",
            "ti_pullback_favorable": True,
            "ti_overheat_risk": False,
        })
        risky = dict(base)
        risky.update({
            "ti_rsi": 82.0,
            "ti_atr_regime": "high",
            "ti_trend_power_regime": "weak",
            "ti_pullback_favorable": False,
            "ti_overheat_risk": True,
        })
        favorable_score, favorable_comps = ai.score(favorable, cfg)
        risky_score, risky_comps = ai.score(risky, cfg)
        self.assertGreater(favorable_score, risky_score)
        self.assertGreater(favorable_comps["technical"], 0)
        self.assertLess(risky_comps["technical"], 0)

    def test_compute_limit_price_buy_sell(self) -> None:
        self.assertEqual(bot.compute_limit_price("BUY", 100.0, 101.0, 0), 100.0)
        self.assertEqual(bot.compute_limit_price("SELL", 100.0, 101.0, 0), 101.0)
        self.assertEqual(bot.compute_limit_price("BUY", 100.0, 101.0, 2), 102.0)
        self.assertEqual(bot.compute_limit_price("SELL", 100.0, 101.0, 2), 99.0)

    def test_compute_exit_limit_price_buy_sell(self) -> None:
        self.assertEqual(bot.compute_exit_limit_price("BUY", 100.0, 101.0, 0), 101.0)
        self.assertEqual(bot.compute_exit_limit_price("SELL", 100.0, 101.0, 0), 100.0)
        self.assertEqual(bot.compute_exit_limit_price("BUY", 100.0, 101.0, 2), 103.0)
        self.assertEqual(bot.compute_exit_limit_price("SELL", 100.0, 101.0, 2), 98.0)

    def test_resolve_fast_ma_observe_handles_buy_and_sell(self) -> None:
        cfg = bot.Cfg(
            buy_fast_ma_distance_pct=0.10,
            sell_fast_ma_distance_pct=0.10,
        )
        result_buy, note_buy = bot.resolve_fast_ma_observe("BUY_CANDIDATE", 100.02, 100.00, cfg)
        self.assertEqual(result_buy, "OBSERVE_BUY_FAST_MA_NEAR")
        self.assertIn("fast_ma_dist=", note_buy)

        result_sell, note_sell = bot.resolve_fast_ma_observe("SELL_CANDIDATE", 99.98, 100.00, cfg)
        self.assertEqual(result_sell, "OBSERVE_SELL_FAST_MA_NEAR")
        self.assertIn("fast_ma_dist=", note_sell)

        result_ok, note_ok = bot.resolve_fast_ma_observe("BUY_CANDIDATE", 101.00, 100.00, cfg)
        self.assertEqual(result_ok, "")
        self.assertEqual(note_ok, "")

    def test_buy_fast_ma_observe_tightened_threshold_blocks_april_2_pattern(self) -> None:
        cfg = bot.Cfg(
            buy_fast_ma_distance_pct=0.12,
            sell_fast_ma_distance_pct=0.10,
        )
        result_near, note_near = bot.resolve_fast_ma_observe("BUY_CANDIDATE", 10651982.0, 10639327.2, cfg)
        self.assertEqual(result_near, "OBSERVE_BUY_FAST_MA_NEAR")
        self.assertIn("0.118944", note_near)

        result_far, note_far = bot.resolve_fast_ma_observe("BUY_CANDIDATE", 10679751.0, 10659667.8, cfg)
        self.assertEqual(result_far, "")
        self.assertEqual(note_far, "")

    def test_trend_flip_cooldown_blocks_recent_reversal(self) -> None:
        cfg = bot.Cfg(trend_flip_cooldown_min=10)
        now = datetime(2026, 3, 29, 10, 8, 0)
        state = {
            "_trend_flip_time_jst": "2026-03-29 10:03:00",
            "_trend_flip_from": "DOWN",
            "_trend_flip_to": "UP",
        }
        blocked, note = bot.get_trend_flip_cooldown_status(
            state,
            cfg,
            now,
            "UP",
            "BUY_CANDIDATE",
        )
        self.assertTrue(blocked)
        self.assertIn("DOWN->UP", note)
        self.assertIn("remain_min=", note)

    def test_calc_trend_efficiency_ratio_detects_clean_vs_choppy_moves(self) -> None:
        clean = bot.calc_trend_efficiency_ratio({"ltp_history": [100.0, 101.0, 102.0, 103.0, 104.0]}, 5)
        choppy = bot.calc_trend_efficiency_ratio({"ltp_history": [100.0, 102.0, 100.0, 102.0, 100.0]}, 5)
        self.assertIsNotNone(clean)
        self.assertIsNotNone(choppy)
        self.assertGreater(float(clean), 0.9)
        self.assertLess(float(choppy), 0.4)

    def test_resolve_progress_reversal_exit_status_blocks_progressed_then_retraced_trade(self) -> None:
        cfg = bot.Cfg(
            progress_reversal_exit_enabled=True,
            progress_reversal_exit_only_paper=True,
            progress_reversal_exit_min_hold_min=20,
            progress_reversal_exit_min_best_fav_pct=0.08,
            progress_reversal_exit_max_current_fav_pct=0.03,
        )
        hit, note = bot.resolve_progress_reversal_exit_status(
            {"exec_mode": "PAPER", "best_fav": 0.14},
            25.0,
            0.01,
            cfg,
        )
        self.assertTrue(hit)
        self.assertIn("exit_tech=PROGRESS_REVERSAL", note)
        self.assertIn("best_fav=0.140000", note)
        self.assertIn("current_fav=0.010000", note)

        hit2, note2 = bot.resolve_progress_reversal_exit_status(
            {"exec_mode": "PAPER", "best_fav": 0.14},
            25.0,
            0.05,
            cfg,
        )
        self.assertFalse(hit2)
        self.assertEqual(note2, "")

    def test_resolve_no_follow_through_exit_status_blocks_zero_progress_trade(self) -> None:
        cfg = bot.Cfg(
            no_follow_through_exit_enabled=True,
            no_follow_through_exit_only_paper=True,
            no_follow_through_exit_min_hold_min=5,
            no_follow_through_exit_max_best_fav_pct=0.01,
            no_follow_through_exit_max_current_fav_pct=0.0,
        )
        hit, note = bot.resolve_no_follow_through_exit_status(
            {"exec_mode": "PAPER", "best_fav": 0.0},
            5.0,
            -0.02,
            cfg,
        )
        self.assertTrue(hit)
        self.assertIn("exit_tech=NO_FOLLOW_THROUGH", note)
        self.assertIn("best_fav=0.000000", note)

        hit2, note2 = bot.resolve_no_follow_through_exit_status(
            {"exec_mode": "PAPER", "best_fav": 0.02},
            5.0,
            -0.01,
            cfg,
        )
        self.assertFalse(hit2)
        self.assertEqual(note2, "")

    def test_resolve_near_tp_giveback_exit_status_blocks_tp_near_miss(self) -> None:
        cfg = bot.Cfg(
            near_tp_giveback_exit_enabled=True,
            near_tp_giveback_exit_only_paper=True,
            near_tp_giveback_exit_min_hold_min=5,
            near_tp_giveback_exit_trigger_ratio=0.85,
            near_tp_giveback_exit_min_giveback_pct=0.04,
            near_tp_giveback_exit_max_current_fav_pct=0.06,
        )
        hit, note = bot.resolve_near_tp_giveback_exit_status(
            {"exec_mode": "PAPER", "best_fav": 0.113594, "tp_pct": 0.1235},
            75.0,
            0.055,
            cfg,
        )
        self.assertTrue(hit)
        self.assertIn("exit_tech=NEAR_TP_GIVEBACK", note)
        self.assertIn("trigger_ratio=0.850000", note)

        hit2, note2 = bot.resolve_near_tp_giveback_exit_status(
            {"exec_mode": "PAPER", "best_fav": 0.08, "tp_pct": 0.1235},
            75.0,
            0.055,
            cfg,
        )
        self.assertFalse(hit2)
        self.assertEqual(note2, "")

    def test_resolve_trend_strength_observe_blocks_weak_shadow_entry(self) -> None:
        cfg = bot.Cfg(
            trend_strength_filter_enabled=True,
            trend_strength_lookback_n=5,
            trend_strength_min_er=0.28,
        )
        state = {"ltp_history": [100.0, 102.0, 100.0, 102.0, 100.0]}
        result, note = bot.resolve_trend_strength_observe("BUY_CANDIDATE", state, cfg)
        self.assertEqual(result, "OBSERVE_TREND_STRENGTH_WEAK")
        self.assertIn("trend_er=", note)
        self.assertIn("min_er=", note)

    def test_resolve_trend_strength_observe_allows_clean_trend(self) -> None:
        cfg = bot.Cfg(
            trend_strength_filter_enabled=True,
            trend_strength_lookback_n=5,
            trend_strength_min_er=0.28,
        )
        state = {"ltp_history": [100.0, 101.0, 102.0, 103.0, 104.0]}
        result, note = bot.resolve_trend_strength_observe("BUY_CANDIDATE", state, cfg)
        self.assertEqual(result, "")
        self.assertEqual(note, "")

    def test_resolve_weak_progress_exit_status_blocks_flat_timeout_candidate(self) -> None:
        cfg = bot.Cfg(
            weak_progress_exit_enabled=True,
            weak_progress_exit_only_paper=True,
            weak_progress_exit_min_hold_min=30,
            weak_progress_exit_max_best_fav_pct=0.05,
        )
        open_pos = {
            "exec_mode": "PAPER",
            "best_fav": 0.041505,
        }
        blocked, note = bot.resolve_weak_progress_exit_status(open_pos, 40.0, cfg)
        self.assertTrue(blocked)
        self.assertIn("WEAK_PROGRESS", note)
        self.assertIn("best_fav=0.041505", note)

    def test_resolve_weak_progress_exit_status_allows_stronger_progress(self) -> None:
        cfg = bot.Cfg(
            weak_progress_exit_enabled=True,
            weak_progress_exit_only_paper=True,
            weak_progress_exit_min_hold_min=30,
            weak_progress_exit_max_best_fav_pct=0.05,
        )
        open_pos = {
            "exec_mode": "PAPER",
            "best_fav": 0.124992,
        }
        blocked, note = bot.resolve_weak_progress_exit_status(open_pos, 40.0, cfg)
        self.assertFalse(blocked)
        self.assertEqual(note, "")

    def test_resolve_entry_news_block_status_blocks_upcoming_lunch(self) -> None:
        cfg = bot.Cfg(win_min=120, news_entry_block_ahead_min=60)
        blocks = [{"date": "2026-04-01", "time_from": "13:00", "time_to": "13:30", "label": "LUNCH"}]
        blocked, note = bot.resolve_entry_news_block_status(datetime(2026, 4, 1, 12, 8, 0), blocks, cfg)
        self.assertTrue(blocked)
        self.assertIn("NEWS_AHEAD", note)
        self.assertIn("LUNCH", note)

    def test_resolve_entry_news_block_status_allows_far_block(self) -> None:
        cfg = bot.Cfg(win_min=120, news_entry_block_ahead_min=60)
        blocks = [{"date": "2026-04-01", "time_from": "13:00", "time_to": "13:30", "label": "LUNCH"}]
        blocked, note = bot.resolve_entry_news_block_status(datetime(2026, 4, 1, 10, 30, 0), blocks, cfg)
        self.assertFalse(blocked)
        self.assertEqual(note, "")

    def test_resolve_pre_news_exit_status_blocks_active_or_imminent_news(self) -> None:
        cfg = bot.Cfg(pre_news_exit_buffer_min=10, pre_news_exit_min_hold_min=5)
        blocks = [{"date": "2026-04-01", "time_from": "13:00", "time_to": "13:30", "label": "LUNCH"}]

        imminent, imminent_note = bot.resolve_pre_news_exit_status(
            datetime(2026, 4, 1, 12, 55, 0),
            blocks,
            20.0,
            cfg,
        )
        self.assertTrue(imminent)
        self.assertIn("NEWS_AHEAD_EXIT", imminent_note)

        active, active_note = bot.resolve_pre_news_exit_status(
            datetime(2026, 4, 1, 13, 5, 0),
            blocks,
            20.0,
            cfg,
        )
        self.assertTrue(active)
        self.assertIn("NEWS_ACTIVE_EXIT", active_note)

    def test_resolve_pre_news_exit_status_respects_min_hold(self) -> None:
        cfg = bot.Cfg(pre_news_exit_buffer_min=10, pre_news_exit_min_hold_min=5)
        blocks = [{"date": "2026-04-01", "time_from": "13:00", "time_to": "13:30", "label": "LUNCH"}]
        blocked, note = bot.resolve_pre_news_exit_status(
            datetime(2026, 4, 1, 12, 55, 0),
            blocks,
            2.0,
            cfg,
        )
        self.assertFalse(blocked)
        self.assertEqual(note, "")

    def test_resolve_eod_entry_block_status_blocks_late_entry(self) -> None:
        cfg = bot.Cfg(end_hour=17)
        blocked, note = bot.resolve_eod_entry_block_status(datetime(2026, 4, 3, 16, 39, 0), cfg)
        self.assertTrue(blocked)
        self.assertIn("eod_entry_window", note)

    def test_resolve_eod_entry_block_status_allows_earlier_trade(self) -> None:
        cfg = bot.Cfg(end_hour=17)
        blocked, note = bot.resolve_eod_entry_block_status(datetime(2026, 4, 3, 15, 30, 0), cfg)
        self.assertFalse(blocked)
        self.assertEqual(note, "")

    def test_resolve_entry_tp_pct_uses_canary_scale(self) -> None:
        cfg = bot.Cfg(tp_buy_pct=0.19, tp_sell_pct=0.19, canary_tp_scale=0.65)
        self.assertAlmostEqual(bot.resolve_entry_tp_pct(cfg, "BUY", "CANARY"), 0.1235, places=9)
        self.assertAlmostEqual(bot.resolve_entry_tp_pct(cfg, "BUY", "LIVE"), 0.19, places=9)

    def test_resolve_effective_stage_auto(self) -> None:
        cfg = bot.Cfg(paper_mode=False, live_enabled=True, stage_paper_days=3, stage_canary_days=3)
        state = {"_rollout_start_day": (datetime.now().date() - timedelta(days=4)).strftime("%Y-%m-%d")}
        stage = bot.resolve_effective_stage(cfg, state, datetime.now())
        self.assertEqual(stage, "CANARY")
        self.assertEqual(state["_effective_stage"], "CANARY")

    def test_paper_mode_forces_paper_stage(self) -> None:
        cfg = bot.Cfg(paper_mode=True, live_enabled=True)
        state: dict = {}
        stage = bot.resolve_effective_stage(cfg, state, datetime.now())
        self.assertEqual(stage, "PAPER")
        self.assertFalse(bot.should_execute_live(cfg, stage))

    def test_run_live_limit_cycle_filled(self) -> None:
        cfg = bot.Cfg(limit_order_timeout_sec=1, product_code="BTC_JPY")
        client = DummyClient(executed_size=0.01, average_price=10000000.0, state="COMPLETED")
        out = bot.run_live_limit_cycle(client, cfg=cfg, side="BUY", size=0.01, price=10000000.0)
        self.assertEqual(out.status, "FILLED")
        self.assertEqual(out.filled_size, 0.01)
        self.assertEqual(out.acceptance_id, "JRF_TEST")

    def test_run_live_limit_cycle_unfilled(self) -> None:
        cfg = bot.Cfg(limit_order_timeout_sec=0, product_code="BTC_JPY")
        client = DummyClient(executed_size=0.0, average_price=0.0, state="ACTIVE")
        out = bot.run_live_limit_cycle(client, cfg=cfg, side="BUY", size=0.01, price=10000000.0)
        self.assertIn(out.status, ("NONE", "PARTIAL"))
        self.assertTrue(client.cancel_called)

    def test_adjust_live_entry_size_spot_passthrough(self) -> None:
        cfg = bot.Cfg(market_type="SPOT", lot=0.01)
        client = DummyClient(executed_size=0.0, collateral_jpy=100000.0)
        size, note = bot.adjust_live_entry_size(client, cfg, desired_size=0.01, ref_price=10000000.0)
        self.assertAlmostEqual(size, 0.01, places=9)
        self.assertEqual(note, "")

    def test_adjust_live_entry_size_fx_capped(self) -> None:
        cfg = bot.Cfg(market_type="FX", fx_leverage=2.0, fx_collateral_use_ratio=0.5, lot=0.1)
        client = DummyClient(executed_size=0.0, collateral_jpy=100000.0)
        # cap_size = 100000 * 2.0 * 0.5 / 10,000,000 = 0.01
        size, note = bot.adjust_live_entry_size(client, cfg, desired_size=0.1, ref_price=10000000.0)
        self.assertAlmostEqual(size, 0.01, places=9)
        self.assertIn("fx_size_capped", note)

    def test_detect_sma_crossover_exit_buy_cross_down(self) -> None:
        state = {"ltp_history": [100.0, 102.0, 104.0, 103.0, 99.0]}
        hit, reason, f_now, s_now, f_prev, s_prev = bot.detect_sma_crossover_exit(
            state=state,
            side="BUY",
            fast_n=2,
            slow_n=3,
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "SMA_CROSS_DOWN")
        self.assertIsNotNone(f_now)
        self.assertIsNotNone(s_now)
        self.assertIsNotNone(f_prev)
        self.assertIsNotNone(s_prev)

    def test_detect_sma_crossover_exit_sell_cross_up(self) -> None:
        state = {"ltp_history": [104.0, 102.0, 100.0, 101.0, 105.0]}
        hit, reason, _, _, _, _ = bot.detect_sma_crossover_exit(
            state=state,
            side="SELL",
            fast_n=2,
            slow_n=3,
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "SMA_CROSS_UP")

    def test_detect_sma_crossover_exit_not_enough_history(self) -> None:
        state = {"ltp_history": [100.0, 101.0, 102.0]}
        hit, reason, _, _, _, _ = bot.detect_sma_crossover_exit(
            state=state,
            side="BUY",
            fast_n=3,
            slow_n=4,
        )
        self.assertFalse(hit)
        self.assertEqual(reason, "")

    def test_loss_streak_guard_triggers_after_n_losses(self) -> None:
        cfg = bot.Cfg(streak_stop_enabled=True, streak_stop_max_losses=2)
        now = datetime.now()
        state: dict = {}
        row1 = {
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "result": "PAPER_EXIT_SL",
            "side": "BUY",
            "price": 100.0,
            "ltp": 99.0,
        }
        row2 = {
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "result": "PAPER_EXIT_TIMEOUT",
            "side": "BUY",
            "price": 100.0,
            "ltp": 98.0,
        }
        with patch.object(bot, "save_state", lambda _s: None):
            bot._update_loss_streak_from_exit_row(state, cfg, row1)
            self.assertEqual(state.get("_streak_consecutive_losses"), 1)
            self.assertFalse(bool(state.get("_streak_stop", False)))

            bot._update_loss_streak_from_exit_row(state, cfg, row2)
            self.assertEqual(state.get("_streak_consecutive_losses"), 2)
            self.assertTrue(bool(state.get("_streak_stop", False)))

            stop, note = bot.get_loss_streak_guard_status(state, cfg, now)
            self.assertTrue(stop)
            self.assertIn("streak_losses=2", note)

    def test_loss_streak_resets_on_win_and_new_day(self) -> None:
        cfg = bot.Cfg(streak_stop_enabled=True, streak_stop_max_losses=2)
        now = datetime.now()
        prev_day = (now.date() - timedelta(days=1)).strftime("%Y-%m-%d")
        state = {
            "_streak_day": prev_day,
            "_streak_consecutive_losses": 3,
            "_streak_stop": True,
        }
        win_row = {
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "result": "PAPER_EXIT_TP",
            "side": "BUY",
            "price": 100.0,
            "ltp": 101.0,
        }
        with patch.object(bot, "save_state", lambda _s: None):
            stop0, _ = bot.get_loss_streak_guard_status(state, cfg, now)
            self.assertFalse(stop0)
            self.assertEqual(state.get("_streak_consecutive_losses"), 0)

            bot._update_loss_streak_from_exit_row(state, cfg, win_row)
            self.assertEqual(state.get("_streak_consecutive_losses"), 0)
            self.assertFalse(bool(state.get("_streak_stop", False)))


class ControlAutoSyncTest(unittest.TestCase):
    def test_sync_allowed_control_updates_updates_allowlist_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            control = base / "CONTROL.csv"
            control.write_text(
                "key,value\n"
                "ai_threshold,0.55\n"
                "ai_veto_threshold,0.30\n"
                "exchange_name,bitflyer\n",
                encoding="utf-8",
            )
            log_path = base / ".streamlit" / "dashboard_change_log.jsonl"
            backup_dir = base / "backups"
            ok, msg, changed = bot.sync_allowed_control_updates(
                control_path=control,
                updates={
                    "ai_threshold": "0.66",
                    "exchange_name": "binance",
                },
                reason="unit_test",
                run_at=datetime(2026, 3, 2, 12, 0, 0),
                backup_dir=backup_dir,
                log_path=log_path,
            )
            self.assertTrue(ok, msg)
            self.assertEqual(changed, ["ai_threshold"])

            got = bot.load_control_csv(control)
            self.assertEqual(got.get("ai_threshold"), "0.66")
            self.assertEqual(got.get("exchange_name"), "bitflyer")

            self.assertTrue(log_path.exists())
            rows = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertGreaterEqual(len(rows), 1)
            self.assertIn("ai_threshold", rows[-1].get("changed_keys", []))
            self.assertIn("unit_test", str(rows[-1].get("summary", "")))

    def test_sync_allowed_control_updates_rolls_back_on_write_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            control = base / "CONTROL.csv"
            control.write_text(
                "key,value\n"
                "ai_threshold,0.55\n"
                "exchange_name,bitflyer\n",
                encoding="utf-8",
            )
            with patch.object(bot, "_write_control_kv_csv_atomic", side_effect=RuntimeError("write_failed")):
                ok, msg, changed = bot.sync_allowed_control_updates(
                    control_path=control,
                    updates={"ai_threshold": "0.72"},
                    reason="unit_test_rollback",
                    run_at=datetime(2026, 3, 2, 12, 30, 0),
                    backup_dir=base / "backups",
                    log_path=base / ".streamlit" / "dashboard_change_log.jsonl",
                )
            self.assertFalse(ok)
            self.assertIn("control sync failed", msg)
            self.assertEqual(changed, ["ai_threshold"])

            got = bot.load_control_csv(control)
            self.assertEqual(got.get("ai_threshold"), "0.55")
            self.assertEqual(got.get("exchange_name"), "bitflyer")


if __name__ == "__main__":
    unittest.main()
