from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tools.trade_event_notifier import (
    _accumulate_daily_trade_exit,
    _build_daily_goal_summary_block,
    _build_daily_reflection,
    _build_daily_reflection_llm_prompt,
    _build_daily_reflection_report,
    _build_daily_trade_review,
    _build_daily_trade_review_with_snapshot_fallback,
    _build_trade_event,
    _build_daily_goal_report,
    _calc_trade_metrics,
    _cooldown_mark_sent,
    _cooldown_remaining_sec,
    _current_daily_snapshot,
    _daily_review_text_block,
    _evaluate_trade_quality,
    _evaluate_daily_reflection_auto_apply,
    _evaluate_vs_expectancy,
    _generate_daily_reflection_llm_feedback,
    _classify_loss_trade_pattern,
    _is_low_quality_llm_summary,
    _ollama_attempt_model_order,
    _merge_hours_csv,
    _normalize_notification_event_code,
    _notification_level_for_event,
    _record_trade_enabled_auto_disabled,
    _pick_daily_goal_report_day,
    _snapshot_freshness,
    _send_event,
    _state_change_event_key,
)


class TradeEventNotifierTest(unittest.TestCase):
    def test_calc_trade_metrics_buy(self) -> None:
        m = _calc_trade_metrics(side="BUY", entry_price=100.0, exit_price=101.0, size=0.1)
        self.assertAlmostEqual(float(m["ret_pct"]), 1.0, places=6)
        self.assertAlmostEqual(float(m["pnl_jpy"]), 0.1, places=6)

    def test_calc_trade_metrics_sell(self) -> None:
        m = _calc_trade_metrics(side="SELL", entry_price=100.0, exit_price=99.0, size=0.1)
        self.assertAlmostEqual(float(m["ret_pct"]), 1.0, places=6)
        self.assertAlmostEqual(float(m["pnl_jpy"]), 0.1, places=6)

    def test_evaluate_trade_quality(self) -> None:
        q1, _ = _evaluate_trade_quality("PAPER_EXIT_TP", 0.2)
        q2, _ = _evaluate_trade_quality("PAPER_EXIT_SL", -0.2)
        q3, _ = _evaluate_trade_quality("PAPER_EXIT_TIMEOUT", None)
        self.assertEqual(q1, "GOOD")
        self.assertEqual(q2, "BAD")
        self.assertEqual(q3, "NEUTRAL")

    def test_evaluate_vs_expectancy(self) -> None:
        v1, d1 = _evaluate_vs_expectancy(0.4, 0.1)
        v2, d2 = _evaluate_vs_expectancy(-0.3, 0.0)
        self.assertEqual(v1, "ABOVE")
        self.assertEqual(v2, "BELOW")
        self.assertGreater(d1, 0)
        self.assertLess(d2, 0)

    def test_build_trade_exit_event_contains_evaluation(self) -> None:
        row = {
            "result": "PAPER_EXIT_TP",
            "time": "2026-03-10 12:00:00",
            "side": "BUY",
            "price": "100",
            "ltp": "101",
            "size": "0.1",
            "pos_id": "20260310-120000-BUY-001",
            "note": "exec=LIVE",
        }
        ev = _build_trade_event(row, "host1", expectancy_ref_pct=0.2)
        self.assertIsNotNone(ev)
        title, text, payload = ev  # type: ignore[misc]
        self.assertIn("[GOOD]", title)
        self.assertIn("評価=GOOD", text)
        self.assertIn("期待値比較=ABOVE", text)
        self.assertIn("判定コメント=", text)
        self.assertAlmostEqual(float(payload["ret_pct"]), 1.0, places=6)
        self.assertEqual(payload["evaluation"], "GOOD")
        self.assertEqual(payload["vs_expectancy"], "ABOVE")
        self.assertIn("利確", str(payload.get("evaluation_comment_ja", "")))

    def test_cooldown_remaining_and_mark(self) -> None:
        cursor = {}
        rem0 = _cooldown_remaining_sec(cursor, "dashboard_state_changed", 180, now_ts=1000.0)
        self.assertEqual(rem0, 0.0)

        _cooldown_mark_sent(cursor, "dashboard_state_changed", now_ts=1000.0)
        rem1 = _cooldown_remaining_sec(cursor, "dashboard_state_changed", 180, now_ts=1050.0)
        rem2 = _cooldown_remaining_sec(cursor, "dashboard_state_changed", 180, now_ts=1200.0)
        self.assertGreater(rem1, 0.0)
        self.assertEqual(rem2, 0.0)

    def test_state_change_cooldown_keys_are_directional(self) -> None:
        cursor = {}
        key_off = _state_change_event_key("runner_state_changed", False)
        key_on = _state_change_event_key("runner_state_changed", True)
        self.assertNotEqual(key_off, key_on)

        _cooldown_mark_sent(cursor, key_off, now_ts=1000.0)
        rem_off = _cooldown_remaining_sec(cursor, key_off, 180, now_ts=1050.0)
        rem_on = _cooldown_remaining_sec(cursor, key_on, 180, now_ts=1050.0)

        self.assertGreater(rem_off, 0.0)
        self.assertEqual(rem_on, 0.0)

    def test_accumulate_daily_trade_exit_tracks_jpy_and_count(self) -> None:
        cursor = {}

        s1 = _accumulate_daily_trade_exit(
            cursor,
            {"time": "2026-03-18 10:00:00", "ret_pct": 0.5, "pnl_jpy": 40.0},
            now_dt=datetime(2026, 3, 18, 10, 5, 0),
        )
        s2 = _accumulate_daily_trade_exit(
            cursor,
            {"time": "2026-03-18 11:00:00", "ret_pct": -0.2, "pnl_jpy": 70.0},
            now_dt=datetime(2026, 3, 18, 11, 5, 0),
        )

        self.assertEqual(s1["day8"], "20260318")
        self.assertEqual(s2["day8"], "20260318")
        self.assertAlmostEqual(float(cursor["daily_ret_pct_sum"]), 0.3, places=6)
        self.assertAlmostEqual(float(cursor["daily_pnl_jpy_sum"]), 110.0, places=6)
        self.assertEqual(int(cursor["daily_closed_count"]), 2)

    def test_record_trade_enabled_auto_disabled_keeps_reason_context(self) -> None:
        cursor = {}
        _record_trade_enabled_auto_disabled(
            cursor,
            day8="20260319",
            ts="2026-03-19 12:20:15",
            reason="daily_loss_breach",
            payload={"exec_mode": "LIVE", "pos_id": "P1"},
        )
        self.assertEqual(cursor["daily_trade_disabled_day8"], "20260319")
        self.assertEqual(cursor["trade_enabled_disabled_reason"], "daily_loss_breach")
        self.assertEqual(cursor["trade_enabled_disabled_at"], "2026-03-19 12:20:15")
        self.assertEqual(cursor["trade_enabled_disabled_exec_mode"], "LIVE")
        self.assertEqual(cursor["trade_enabled_disabled_pos_id"], "P1")

    def test_current_daily_snapshot_returns_zero_for_stale_day(self) -> None:
        cursor = {
            "daily_day8": "20260317",
            "daily_ret_pct_sum": 1.2,
            "daily_pnl_jpy_sum": 300.0,
            "daily_closed_count": 5,
        }

        snap = _current_daily_snapshot(cursor, now_dt=datetime(2026, 3, 18, 9, 0, 0))

        self.assertEqual(snap["day8"], "20260318")
        self.assertEqual(float(snap["daily_ret_pct_sum"]), 0.0)
        self.assertEqual(float(snap["daily_pnl_jpy_sum"]), 0.0)
        self.assertEqual(int(snap["daily_closed_count"]), 0)

    def test_build_daily_goal_report_contains_achieved_status(self) -> None:
        title, text, payload = _build_daily_goal_report(
            report_dt=datetime(2026, 3, 18, 23, 0, 0),
            host="host1",
            day8="20260318",
            goal_jpy=100.0,
            daily_pnl_jpy_sum=123.4,
            daily_ret_pct_sum=0.55,
            daily_closed_count=3,
        )

        self.assertEqual(title, "Ouroboros Daily Report [ACHIEVED]")
        self.assertTrue(title.isascii())
        self.assertTrue(text.startswith("Ouroboros 終業レポート [達成]\n"))
        self.assertIn("【目標】", text)
        self.assertIn("1日目標(JPY)=100.00", text)
        self.assertIn("当日実現損益(JPY)=123.40", text)
        self.assertIn("目標判定=達成", text)
        self.assertEqual(payload["notification_title"], "Ouroboros Daily Report [ACHIEVED]")
        self.assertEqual(payload["notification_title_ja"], "Ouroboros 終業レポート [達成]")
        self.assertIn("終業判定=trade_time 終了", _build_daily_goal_report(
            report_dt=datetime(2026, 3, 18, 23, 0, 0),
            host="host1",
            day8="20260318",
            goal_jpy=100.0,
            daily_pnl_jpy_sum=123.4,
            daily_ret_pct_sum=0.55,
            daily_closed_count=3,
            close_reason="out_of_time",
        )[1])
        self.assertIn("終業判定=21時定時締め", _build_daily_goal_report(
            report_dt=datetime(2026, 3, 18, 21, 0, 0),
            host="host1",
            day8="20260318",
            goal_jpy=100.0,
            daily_pnl_jpy_sum=123.4,
            daily_ret_pct_sum=0.55,
            daily_closed_count=3,
            close_reason="scheduled_close",
        )[1])
        self.assertTrue(bool(payload["goal_achieved"]))
        self.assertAlmostEqual(float(payload["goal_delta_jpy"]), 23.4, places=6)

    def test_send_event_marks_daily_goal_report_high_priority(self) -> None:
        seen = {}

        def fake_post(url, body, headers):
            seen["url"] = url
            seen["body"] = body
            seen["headers"] = headers
            return True, "http=200"

        with patch("tools.trade_event_notifier._http_post", side_effect=fake_post):
            ok, msg = _send_event(
                title="Ouroboros Daily Report [MISSED]",
                text="Ouroboros 終業レポート [未達]\n本文テスト",
                payload={"event": "daily_goal_report"},
                sec={"ntfy_topic_url": "https://ntfy.example/topic", "trade_notify_enabled": True},
                dry_run=False,
            )

        self.assertTrue(ok)
        self.assertEqual(msg, "ntfy:http=200")
        self.assertEqual(seen["headers"]["Title"], "Ouroboros Daily Report [MISSED]")
        self.assertEqual(seen["headers"]["Priority"], "high")
        self.assertTrue(str(seen["headers"]["Tags"]).startswith("info"))
        self.assertIn("Ouroboros 終業レポート".encode("utf-8"), seen["body"])

    def test_notification_event_code_and_level_are_normalized(self) -> None:
        self.assertEqual(_normalize_notification_event_code("Trade Enabled Reenabled"), "trade_enabled_reenabled")
        self.assertEqual(_notification_level_for_event("daily_goal_report"), "INFO")
        self.assertEqual(_notification_level_for_event("dd_alert"), "CRITICAL")
        self.assertEqual(_notification_level_for_event("drift_state_changed"), "WARN")

    def test_pick_daily_goal_report_day_uses_handled_day8_to_avoid_repeat(self) -> None:
        day8, reason = _pick_daily_goal_report_day(
            today8="20260404",
            sent_day8="",
            handled_day8="20260403",
            sent_day8s=[],
            now_hour=9,
            report_hour=21,
            runner_now=True,
            runner_seen_day8="20260403",
            cursor_day8="20260403",
            current_day_review={"ended_out_of_time": False},
            cursor_day_review={"has_runtime_activity": True, "closed_n": 1},
        )
        self.assertEqual(day8, "")
        self.assertEqual(reason, "")

    def test_pick_daily_goal_report_day_waits_until_scheduled_hour(self) -> None:
        day8, reason = _pick_daily_goal_report_day(
            today8="20260415",
            sent_day8="",
            handled_day8="",
            sent_day8s=[],
            now_hour=20,
            report_hour=21,
            runner_now=False,
            runner_seen_day8="20260415",
            cursor_day8="20260415",
            current_day_review={"ended_out_of_time": True, "has_runtime_activity": True, "closed_n": 2},
            cursor_day_review={"has_runtime_activity": True, "closed_n": 2},
        )
        self.assertEqual(day8, "")
        self.assertEqual(reason, "")

    def test_pick_daily_goal_report_day_uses_scheduled_hour_for_current_day(self) -> None:
        day8, reason = _pick_daily_goal_report_day(
            today8="20260415",
            sent_day8="",
            handled_day8="",
            sent_day8s=[],
            now_hour=21,
            report_hour=21,
            runner_now=True,
            runner_seen_day8="20260415",
            cursor_day8="20260415",
            current_day_review={"ended_out_of_time": False, "has_runtime_activity": False, "closed_n": 0},
            cursor_day_review={"has_runtime_activity": False, "closed_n": 0},
        )
        self.assertEqual(day8, "20260415")
        self.assertEqual(reason, "scheduled_close")

    def test_pick_daily_goal_report_day_uses_done_history_to_avoid_repeat(self) -> None:
        day8, reason = _pick_daily_goal_report_day(
            today8="20260415",
            sent_day8="20260415",
            handled_day8="20260415",
            sent_day8s=["20260414", "20260415"],
            now_hour=22,
            report_hour=21,
            runner_now=True,
            runner_seen_day8="20260415",
            cursor_day8="20260414",
            current_day_review={"ended_out_of_time": False, "has_runtime_activity": False, "closed_n": 0},
            cursor_day_review={"has_runtime_activity": True, "closed_n": 1},
        )
        self.assertEqual(day8, "")
        self.assertEqual(reason, "")

    def test_merge_hours_csv(self) -> None:
        self.assertEqual(_merge_hours_csv("12,15", [11, 15, 9]), "9,11,12,15")

    def test_build_daily_trade_review_from_log(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            log = d / "trade_log_20260318.csv"
            log.write_text(
                "\n".join(
                    [
                        "time,result,side,price,size,ltp,pos_id,note",
                        "2026-03-18 10:00:00,PAPER,BUY,100,2,,P1,\"gc_recent=golden gc_strong=1 ti_rsi_zone=neutral ti_bb_zone=mid ti_atr_regime=normal ti_trend_power_regime=strong cp_name=DOUBLE_BOTTOM cp_stage=CONFIRMED cp_bias=BUY cp_confirmed=1 cp_quality=OK phase=C phase_reason=MA_UP phase_momentum=UP_BREAK phase_transition=B->C up_break=1 aiba_trend=UP aiba_cross=KUCHIBASHI aiba_ppp=PPP aiba_9=1\"",
                        "2026-03-18 10:10:00,PAPER_EXIT_TP,BUY,100,2,105,P1,",
                        "2026-03-18 11:00:00,PAPER,SELL,100,3,,P2,\"gc_recent=dead ti_rsi_zone=overbought ti_bb_zone=upper ti_atr_regime=high ti_trend_power_regime=weak phase=B phase_reason=MA_FLAT aiba_trend=DOWN aiba_ppp=REV_PPP aiba_try_fail=1\"",
                        "2026-03-18 11:05:00,PAPER_EXIT_SL,SELL,100,3,102,P2,",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            review = _build_daily_trade_review(d, "20260318")

        self.assertEqual(int(review["closed_n"]), 2)
        self.assertEqual(int(review["win_n"]), 1)
        self.assertEqual(int(review["loss_n"]), 1)
        self.assertAlmostEqual(float(review["pnl_jpy_sum"]), 4.0, places=6)
        self.assertEqual(int(review["exit_reason_breakdown"]["TP"]), 1)
        self.assertEqual(int(review["exit_reason_breakdown"]["SL"]), 1)
        self.assertEqual(list(review["good_hours"]), [10])
        self.assertEqual(list(review["bad_hours"]), [11])
        self.assertEqual(int(review["row_n"]), 4)
        self.assertEqual(int(review["active_row_n"]), 4)
        self.assertFalse(bool(review["ended_out_of_time"]))
        feature_outcomes = review["technical_feature_outcomes"]
        self.assertEqual(int(feature_outcomes["gc_recent=golden"]["n"]), 1)
        self.assertEqual(int(feature_outcomes["gc_strong=1"]["TP"]), 1)
        self.assertEqual(int(feature_outcomes["rsi=overbought"]["SL"]), 1)
        self.assertEqual(int(feature_outcomes["atr=high"]["loss_n"]), 1)
        self.assertEqual(int(feature_outcomes["pattern=DOUBLE_BOTTOM"]["TP"]), 1)
        self.assertEqual(int(feature_outcomes["pattern_confirmed=1"]["win_n"]), 1)
        self.assertEqual(int(feature_outcomes["pattern_quality=OK"]["win_n"]), 1)
        self.assertEqual(int(feature_outcomes["phase=C"]["TP"]), 1)
        self.assertEqual(int(feature_outcomes["phase_transition=B->C"]["TP"]), 1)
        self.assertEqual(int(feature_outcomes["phase=B"]["SL"]), 1)
        self.assertEqual(int(feature_outcomes["phase_momentum=UP_BREAK"]["win_n"]), 1)
        self.assertEqual(int(feature_outcomes["up_break=1"]["n"]), 1)
        self.assertEqual(int(feature_outcomes["aiba_cross=KUCHIBASHI"]["TP"]), 1)
        self.assertEqual(int(feature_outcomes["aiba_ppp=REV_PPP"]["SL"]), 1)
        self.assertEqual(int(feature_outcomes["aiba_9=1"]["win_n"]), 1)
        self.assertEqual(int(feature_outcomes["aiba_try_fail=1"]["loss_n"]), 1)
        phase_outcomes = review["market_phase_outcomes"]
        self.assertEqual(int(phase_outcomes["C"]["TP"]), 1)
        self.assertEqual(int(phase_outcomes["C"]["momentum_n"]), 1)
        self.assertEqual(int(phase_outcomes["B"]["SL"]), 1)
        self.assertAlmostEqual(float(phase_outcomes["B"]["pnl_jpy_sum"]), -6.0, places=6)
        self.assertEqual(int(review["market_phase_transition_n"]), 1)
        self.assertEqual(int(review["market_phase_transition_counts"]["B->C"]), 1)
        self.assertEqual(review["latest_market_phase_transition"], "B->C")

    def test_daily_trade_review_prefers_vm_snapshot_when_primary_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            primary_logs = root / "local_logs"
            snapshot_root = root / "snapshot"
            snapshot_logs = snapshot_root / "logs"
            primary_logs.mkdir(parents=True)
            snapshot_logs.mkdir(parents=True)
            (primary_logs / "trade_log_20260418.csv").write_text(
                "time,result,side,price,size,ltp,pos_id,note\n",
                encoding="utf-8",
            )
            (snapshot_logs / "trade_log_20260418.csv").write_text(
                "\n".join(
                    [
                        "time,result,side,price,size,ltp,pos_id,note",
                        "2026-04-18 10:00:00,OBSERVE_TIME_BLOCK,,,,,,eod_entry_window",
                        "2026-04-18 10:05:00,SKIP_NEWS,,,,,,news",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            review, chosen = _build_daily_trade_review_with_snapshot_fallback(
                primary_logs_dir=primary_logs,
                day8="20260418",
                snapshot_dir=snapshot_root,
                enabled=True,
            )

        self.assertEqual(chosen, snapshot_logs)
        self.assertEqual(review["report_log_source"], "vm_snapshot")
        self.assertEqual(int(review["row_n"]), 2)
        self.assertEqual(int(review["observe_time_block_n"]), 1)

    def test_snapshot_freshness_parses_timestamped_snapshot_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "20260418_210000"
            logs = root / "logs"
            logs.mkdir(parents=True)

            fresh = _snapshot_freshness(
                snapshot_dir=root,
                logs_dir=logs,
                now_dt=datetime(2026, 4, 18, 22, 0, 0),
                stale_after_min=240,
            )
            stale = _snapshot_freshness(
                snapshot_dir=root,
                logs_dir=logs,
                now_dt=datetime(2026, 4, 19, 2, 0, 0),
                stale_after_min=240,
            )

        self.assertEqual(fresh["report_snapshot_name"], "20260418_210000")
        self.assertEqual(fresh["report_snapshot_freshness"], "OK")
        self.assertEqual(fresh["report_snapshot_age_min"], 60)
        self.assertEqual(stale["report_snapshot_freshness"], "STALE")

    def test_build_daily_trade_review_counts_new_entry_guards(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            log = d / "trade_log_20260318.csv"
            log.write_text(
                "\n".join(
                    [
                        "time,result,side,price,size,ltp,pos_id,note",
                        "2026-03-18 10:00:00,OBSERVE_AI_BLOCK,,,,,,AI_BLOCK AI score=0.820 htf60_countertrend=1 htf15_60_conflict=1",
                        "2026-03-18 10:05:00,OBSERVE_BUY_FAST_MA_NEAR,,,,,,,",
                        "2026-03-18 10:10:00,OBSERVE_SELL_FAST_MA_NEAR,,,,,,,",
                        "2026-03-18 10:15:00,OBSERVE_TREND_FLIP_COOLDOWN,,,,,,,",
                        "2026-03-18 10:20:00,OBSERVE_TREND_STRENGTH_WEAK,,,,,,,",
                        "2026-03-18 10:25:00,OBSERVE_PHASE_B,,,,,,,phase=B phase_reason=MA_FLAT",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            review = _build_daily_trade_review(d, "20260318")

        self.assertEqual(int(review["observe_ai_block_n"]), 1)
        self.assertEqual(int(review["observe_ai_block_htf60_countertrend_n"]), 1)
        self.assertEqual(int(review["observe_ai_block_htf15_60_conflict_n"]), 1)
        self.assertEqual(int(review["observe_buy_fast_ma_near_n"]), 1)
        self.assertEqual(int(review["observe_sell_fast_ma_near_n"]), 1)
        self.assertEqual(int(review["observe_trend_flip_cooldown_n"]), 1)
        self.assertEqual(int(review["observe_trend_strength_weak_n"]), 1)
        self.assertEqual(int(review["observe_phase_b_n"]), 1)

    def test_build_daily_trade_review_tracks_opportunity_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            log = d / "trade_log_20260318.csv"
            log.write_text(
                "\n".join(
                    [
                        "time,result,side,price,size,ltp,pos_id,note",
                        "2026-03-18 10:00:00,OBSERVE_OK,,,,,,entry_unfilled order_id=abc filled=0.00000000",
                        "2026-03-18 10:05:00,HOLD_OPEN_POS,BUY,100,1,101,P1,exit_unfilled order_id=def filled=0.00000000",
                        "2026-03-18 10:10:00,SKIP_NEWS,,,,,,NEWS_AHEAD LUNCH",
                        "2026-03-18 10:15:00,OBSERVE_TIME_BLOCK,,,,,,eod_entry_window cutoff=15:59:30",
                        "2026-03-18 10:20:00,SKIP_SPREAD,,,,,,",
                        "2026-03-18 10:25:00,PAPER,BUY,100,1,,P2,",
                        "2026-03-18 10:35:00,PAPER_EXIT_PRENEWS,BUY,100,1,100.1,P2,",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            review = _build_daily_trade_review(d, "20260318")

        self.assertEqual(int(review["entry_unfilled_n"]), 1)
        self.assertEqual(int(review["exit_unfilled_n"]), 1)
        self.assertEqual(int(review["skip_news_n"]), 1)
        self.assertEqual(int(review["observe_time_block_n"]), 1)
        self.assertEqual(int(review["skip_spread_n"]), 1)
        self.assertEqual(int(review["exit_reason_breakdown"]["PRENEWS"]), 1)
        self.assertEqual(int(review["opportunity_pattern_breakdown"]["news_avoidance"]), 2)
        self.assertEqual(str(review["dominant_opportunity_pattern_label_ja"]), "時間帯回避")

    def test_build_daily_trade_review_marks_out_of_time_end(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            log = d / "trade_log_20260318.csv"
            log.write_text(
                "\n".join(
                    [
                        "time,result,side,price,size,ltp,pos_id,note",
                        "2026-03-18 10:00:00,SKIP_AI_GATE,,,,,,,,",
                        "2026-03-18 15:35:00,SKIP_OUT_OF_TIME,,,,,,,,",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            review = _build_daily_trade_review(d, "20260318")

        self.assertTrue(bool(review["has_runtime_activity"]))
        self.assertTrue(bool(review["ended_out_of_time"]))
        self.assertEqual(str(review["last_result"]), "SKIP_OUT_OF_TIME")

    def test_classify_loss_trade_pattern_variants(self) -> None:
        self.assertEqual(
            _classify_loss_trade_pattern(result="PAPER_EXIT_SL", ret_pct=-0.1, hold_min=25.0, best_fav_pct=0.12)[0],
            "reversal",
        )
        self.assertEqual(
            _classify_loss_trade_pattern(result="PAPER_EXIT_TIMEOUT", ret_pct=-0.03, hold_min=35.0, best_fav_pct=0.02)[0],
            "weak_follow_through",
        )
        self.assertEqual(
            _classify_loss_trade_pattern(result="PAPER_EXIT_SL", ret_pct=-0.08, hold_min=5.0, best_fav_pct=0.0)[0],
            "late_entry",
        )

    def test_build_daily_trade_review_tracks_loss_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            log = d / "trade_log_20260318.csv"
            log.write_text(
                "\n".join(
                    [
                        "time,result,side,price,size,ltp,pos_id,note",
                        "2026-03-18 10:00:00,PAPER,BUY,100,1,,P1,",
                        "2026-03-18 10:25:00,PAPER_EXIT_SL,BUY,100,1,99,P1,entry=2026-03-18_10:00:00 best_fav=0.120000 extend_count=0",
                        "2026-03-18 11:00:00,PAPER,BUY,100,1,,P2,",
                        "2026-03-18 11:30:00,PAPER_EXIT_TIMEOUT,BUY,100,1,99.8,P2,entry=2026-03-18_11:00:00 best_fav=0.020000 extend_count=0",
                        "2026-03-18 12:00:00,PAPER,SELL,100,1,,P3,",
                        "2026-03-18 12:05:00,PAPER_EXIT_SL,SELL,100,1,101.5,P3,entry=2026-03-18_12:00:00 best_fav=0.000000 extend_count=0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            review = _build_daily_trade_review(d, "20260318")

        self.assertEqual(int(review["loss_pattern_breakdown"]["reversal"]), 1)
        self.assertEqual(int(review["loss_pattern_breakdown"]["weak_follow_through"]), 1)
        self.assertEqual(int(review["loss_pattern_breakdown"]["late_entry"]), 1)
        self.assertEqual(str(review["dominant_loss_pattern_key"]), "reversal")
        self.assertEqual(str(review["worst_trade"]["loss_pattern_label_ja"]), "entry遅れ")

    def test_build_daily_trade_review_counts_progress_timeout_separately(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            log = d / "trade_log_20260318.csv"
            log.write_text(
                "\n".join(
                    [
                        "time,result,side,price,size,ltp,pos_id,note",
                        "2026-03-18 10:00:00,PAPER,BUY,100,1,,P1,",
                        "2026-03-18 10:40:00,PAPER_EXIT_TIMEOUT,BUY,100,1,100.1,P1,entry=2026-03-18_10:00:00 best_fav=0.120000 extend_count=0 exit_tech=SMA_CROSS_DOWN",
                        "2026-03-18 11:00:00,PAPER,BUY,100,1,,P2,",
                        "2026-03-18 11:40:00,PAPER_EXIT_TIMEOUT,BUY,100,1,99.9,P2,entry=2026-03-18_11:00:00 best_fav=0.020000 extend_count=0 exit_tech=WEAK_PROGRESS",
                        "2026-03-18 12:00:00,PAPER,BUY,100,1,,P3,",
                        "2026-03-18 12:05:00,PAPER_EXIT_TIMEOUT,BUY,100,1,99.8,P3,entry=2026-03-18_12:00:00 best_fav=0.000000 extend_count=0 exit_tech=NO_FOLLOW_THROUGH",
                        "2026-03-18 13:00:00,PAPER,BUY,100,1,,P4,",
                        "2026-03-18 13:20:00,PAPER_EXIT_TIMEOUT,BUY,100,1,100.05,P4,entry=2026-03-18_13:00:00 best_fav=0.113594 extend_count=0 exit_tech=NEAR_TP_GIVEBACK",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            review = _build_daily_trade_review(d, "20260318")

        self.assertEqual(int(review["exit_reason_breakdown"]["TIMEOUT"]), 4)
        self.assertEqual(int(review["weak_progress_exit_n"]), 1)
        self.assertEqual(int(review["no_follow_through_exit_n"]), 1)
        self.assertEqual(int(review["near_tp_giveback_exit_n"]), 1)
        self.assertEqual(int(review["progress_timeout_n"]), 1)

    def test_build_daily_trade_review_counts_progress_reversal_separately(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            log = d / "trade_log_20260318.csv"
            log.write_text(
                "\n".join(
                    [
                        "time,result,side,price,size,ltp,pos_id,note",
                        "2026-03-18 10:00:00,PAPER,BUY,100,1,,P1,",
                        "2026-03-18 10:25:00,PAPER_EXIT_TIMEOUT,BUY,100,1,100.0,P1,entry=2026-03-18_10:00:00 best_fav=0.140000 extend_count=0 exit_tech=PROGRESS_REVERSAL",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            review = _build_daily_trade_review(d, "20260318")

        self.assertEqual(int(review["exit_reason_breakdown"]["TIMEOUT"]), 1)
        self.assertEqual(int(review["progress_reversal_exit_n"]), 1)
        self.assertEqual(int(review["progress_timeout_n"]), 0)

    def test_build_daily_trade_review_tracks_mfe_mae_and_giveback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            log = d / "trade_log_20260318.csv"
            log.write_text(
                "\n".join(
                    [
                        "time,result,side,price,size,ltp,pos_id,note",
                        "2026-03-18 10:00:00,PAPER,BUY,100,1,,P1,phase=C aiba_ppp=PPP",
                        "2026-03-18 10:20:00,PAPER_EXIT_TIMEOUT,BUY,100,1,100.05,P1,entry=2026-03-18_10:00:00 best_fav=0.120000 max_adv=0.030000 current_fav=0.050000",
                        "2026-03-18 11:00:00,PAPER,BUY,100,1,,P2,phase=C aiba_ppp=PPP",
                        "2026-03-18 11:20:00,PAPER_EXIT_SL,BUY,100,1,99,P2,entry=2026-03-18_11:00:00 best_fav=0.200000 max_adv=1.000000 current_fav=-1.000000",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            review = _build_daily_trade_review(d, "20260318")

        self.assertEqual(int(review["closed_n"]), 2)
        self.assertEqual(int(review["progress_reached_n"]), 2)
        self.assertAlmostEqual(float(review["avg_mfe_pct"]), 0.16, places=6)
        self.assertAlmostEqual(float(review["avg_mae_proxy_pct"]), 0.515, places=6)
        self.assertAlmostEqual(float(review["avg_giveback_pct"]), 0.635, places=6)
        self.assertAlmostEqual(float(review["best_trade"]["mfe_pct"]), 0.12, places=6)
        feature = review["technical_feature_outcomes"]["aiba_ppp=PPP"]
        self.assertAlmostEqual(float(feature["avg_mfe_pct"]), 0.16, places=6)
        self.assertAlmostEqual(float(feature["avg_mae_proxy_pct"]), 0.515, places=6)
        self.assertAlmostEqual(float(feature["avg_giveback_pct"]), 0.635, places=6)
        phase = review["market_phase_outcomes"]["C"]
        self.assertAlmostEqual(float(phase["avg_giveback_pct"]), 0.635, places=6)

    def test_pick_daily_goal_report_day_prefers_rollover_for_unsent_previous_day(self) -> None:
        day8, reason = _pick_daily_goal_report_day(
            today8="20260319",
            sent_day8="",
            handled_day8="",
            sent_day8s=[],
            now_hour=9,
            report_hour=21,
            runner_now=True,
            runner_seen_day8="20260319",
            cursor_day8="20260318",
            current_day_review={"ended_out_of_time": False},
            cursor_day_review={"has_runtime_activity": True, "closed_n": 0},
        )
        self.assertEqual(day8, "20260318")
        self.assertEqual(reason, "day_rollover")

    def test_pick_daily_goal_report_day_uses_out_of_time_for_current_day(self) -> None:
        day8, reason = _pick_daily_goal_report_day(
            today8="20260319",
            sent_day8="",
            handled_day8="",
            sent_day8s=[],
            now_hour=21,
            report_hour=21,
            runner_now=True,
            runner_seen_day8="20260319",
            cursor_day8="20260319",
            current_day_review={"ended_out_of_time": True},
            cursor_day_review={"has_runtime_activity": True, "closed_n": 1},
        )
        self.assertEqual(day8, "20260319")
        self.assertEqual(reason, "scheduled_close")

    def test_build_daily_reflection_suggests_tighter_controls(self) -> None:
        reflection = _build_daily_reflection(
            daily_review={
                "closed_n": 3,
                "win_rate_pct": 33.3,
                "pnl_jpy_sum": -120.0,
                "exit_reason_breakdown": {"TP": 1, "SL": 2, "TIMEOUT": 0, "PARTIAL_TP": 0, "EOD": 0},
                "loss_pattern_breakdown": {"reversal": 2, "weak_follow_through": 0, "late_entry": 1, "other": 0},
                "dominant_loss_pattern_key": "reversal",
                "dominant_loss_pattern_label_ja": "反転巻き込み",
                "opportunity_pattern_breakdown": {"entry_unfilled": 1, "exit_unfilled": 0, "news_avoidance": 2, "time_block": 0, "spread_block": 0},
                "dominant_opportunity_pattern_key": "news_avoidance",
                "dominant_opportunity_pattern_label_ja": "時間帯回避",
                "good_hours": [],
                "bad_hours": [11],
            },
            state_obj={"_risk_stop": True, "_streak_stop": True, "_drift_watch": {"status": "INSUFFICIENT"}},
            control_values={
                "streak_stop_enabled": "0",
                "streak_stop_max_losses": "3",
                "daily_loss_limit_pct": "-1.0",
                "ai_train_weekly_bad_hours": "",
                "no_paper_hours": "",
            },
            goal_jpy=100.0,
            shadow_review={
                "available": True,
                "closed_n": 5,
                "weak_progress_exit_n": 1,
                "prev_weak_progress_exit_n": 0,
                "weak_progress_exit_delta": 1,
                "observe_trend_strength_weak_n": 3,
                "prev_observe_trend_strength_weak_n": 1,
                "observe_trend_strength_weak_delta": 2,
                "timeout_n": 1,
                "prev_timeout_n": 4,
                "timeout_delta": -3,
            },
        )

        self.assertTrue("streak_stop_enabled" in reflection["suggested_control_updates"])
        self.assertEqual(reflection["suggested_control_updates"]["streak_stop_max_losses"], "2")
        self.assertEqual(reflection["suggested_control_updates"]["daily_loss_limit_pct"], "-0.50")
        self.assertEqual(reflection["suggested_control_updates"]["no_paper_hours"], "11")
        self.assertGreaterEqual(len(reflection["loss_notes"]), 1)
        self.assertEqual(reflection["sample_confidence"], "medium")
        self.assertEqual(reflection["resume_outlook_summary"], "復帰まで約定あと1件")
        self.assertIn("guard_counts", reflection)
        self.assertEqual(reflection["shadow_filter_hint"], "維持寄り")
        self.assertEqual(reflection["shadow_htf_hint"], "現状維持")
        self.assertEqual(reflection["shadow_exit_hint"], "維持寄り")
        self.assertEqual(reflection["dominant_loss_pattern_label_ja"], "反転巻き込み")
        self.assertEqual(reflection["dominant_opportunity_pattern_label_ja"], "時間帯回避")

    def test_build_daily_reflection_keeps_changes_minimal_on_low_sample_day(self) -> None:
        reflection = _build_daily_reflection(
            daily_review={
                "closed_n": 1,
                "active_row_n": 1,
                "win_rate_pct": 0.0,
                "avg_ret_pct": -0.1,
                "profit_factor_jpy": 0.0,
                "pnl_jpy_sum": -5.0,
                "exit_reason_breakdown": {"TP": 0, "SL": 1, "TIMEOUT": 0, "PARTIAL_TP": 0, "EOD": 0},
                "loss_pattern_breakdown": {"reversal": 0, "weak_follow_through": 0, "late_entry": 1, "other": 0},
                "dominant_loss_pattern_key": "late_entry",
                "dominant_loss_pattern_label_ja": "entry遅れ",
                "opportunity_pattern_breakdown": {"entry_unfilled": 1, "exit_unfilled": 0, "news_avoidance": 0, "time_block": 0, "spread_block": 0},
                "dominant_opportunity_pattern_key": "entry_unfilled",
                "dominant_opportunity_pattern_label_ja": "entry約定失敗",
                "good_hours": [],
                "bad_hours": [11],
                "worst_trade": {"pnl_jpy": -5.0},
            },
            state_obj={"_risk_stop": False, "_streak_stop": False, "_drift_watch": {"status": "NORMAL"}},
            control_values={
                "streak_stop_enabled": "0",
                "streak_stop_max_losses": "3",
                "daily_loss_limit_pct": "-1.0",
                "ai_train_weekly_bad_hours": "",
                "no_paper_hours": "",
            },
            goal_jpy=100.0,
            shadow_review={"available": True, "closed_n": 1, "observe_trend_strength_weak_n": 0, "timeout_n": 0},
        )

        self.assertEqual(reflection["sample_confidence"], "low")
        self.assertEqual(reflection["suggested_control_updates"], {})
        self.assertIn("サンプル信頼度が低い", " / ".join(reflection["next_day_actions"]))
        self.assertEqual(reflection["resume_outlook_summary"], "通常運転")
        self.assertEqual(reflection["shadow_filter_hint"], "評価保留")
        self.assertEqual(reflection["shadow_htf_hint"], "評価保留")
        self.assertEqual(reflection["shadow_exit_hint"], "評価保留")
        self.assertEqual(reflection["dominant_loss_pattern_label_ja"], "entry遅れ")
        self.assertEqual(reflection["dominant_opportunity_pattern_label_ja"], "entry約定失敗")

    def test_build_daily_reflection_report_contains_sections(self) -> None:
        report = _build_daily_reflection_report(
            report_dt=datetime(2026, 3, 18, 23, 0, 0),
            host="host1",
            day8="20260318",
            goal_jpy=100.0,
            daily_review={"closed_n": 2},
            reflection={"goal_achieved": True, "win_notes": ["ok"], "loss_notes": [], "next_day_actions": [], "suggested_control_updates": {}},
            shadow_review={"available": True, "closed_n": 5, "pnl_jpy_sum": 12.0, "exit_technical_n": 2, "weak_progress_exit_n": 1, "observe_trend_strength_weak_n": 3, "timeout_n": 1},
        )
        self.assertEqual(report["meta"]["spec"], "OUROBOROS_DAILY_REFLECTION_V1")
        self.assertEqual(report["range"]["day8"], "20260318")
        self.assertTrue(bool(report["goal"]["achieved"]))
        self.assertEqual(int(report["shadow_review"]["closed_n"]), 5)

    def test_build_daily_goal_summary_block_contains_quick_view(self) -> None:
        text = _build_daily_goal_summary_block(
            goal_jpy=100.0,
            daily_review={
                "pnl_jpy_sum": 12.3,
                "ret_sum_pct": 0.2,
                "closed_n": 2,
            },
            reflection={
                "sample_confidence": "medium",
                "drift_status": "INSUFFICIENT",
                "resume_outlook_summary": "復帰まで約定あと2件",
            },
            auto_apply={
                "enabled": True,
                "applied": False,
                "reason": "sample_confidence<high",
            },
            shadow_review={
                "available": True,
                "closed_n": 7,
                "win_rate_pct": 57.1,
                "pnl_jpy_sum": 18.0,
                "exit_technical_n": 2,
                "prev_exit_technical_n": 0,
                "exit_technical_delta": 2,
                "weak_progress_exit_n": 1,
                "prev_weak_progress_exit_n": 0,
                "weak_progress_exit_delta": 1,
                "progress_reversal_exit_n": 1,
                "prev_progress_reversal_exit_n": 0,
                "progress_reversal_exit_delta": 1,
                "observe_trend_strength_weak_n": 3,
                "prev_observe_trend_strength_weak_n": 1,
                "observe_trend_strength_weak_delta": 2,
                "plain_timeout_n": 0,
                "prev_plain_timeout_n": 3,
                "timeout_n": 1,
                "prev_timeout_n": 4,
                "timeout_delta": -3,
            },
        )
        self.assertIn("【要約】", text)
        self.assertIn("判定=未達", text)
        self.assertIn("信頼度=中", text)
        self.assertIn("自動承認=未適用(sample_confidence<high)", text)
        self.assertIn("shadow=+18.00JPY / close=7 / win=57.1% / tech=2 / weak=1 / pr=1 / ntp=0 / pto=0 / nf=0 / trend=3 / htf60=0 / conflict=0 / timeout=0", text)
        self.assertIn("shadow注目=技術的exit 2件 (前日比 +2)", text)
        self.assertIn("shadow注目=WEAK_PROGRESS 1件 (前日比 +1)", text)
        self.assertIn("shadow注目=進行戻しexit 1件 (前日比 +1)", text)
        self.assertIn("shadow比較=trend弱 3件 (+2) / weak 1件 (+1) / 進行戻しexit 1件 (+1) / TP寸前戻しexit 0件 (+0) / 進行後TIMEOUT 0件 (+0) / 初動なしexit 0件 (+0) / HTF60逆風 0件 (+0) / 15/60ねじれ 0件 (+0) / TIMEOUT 0件 (-3)", text)
        self.assertIn("shadow判定=進行戻しexit は出たが進行後TIMEOUT 改善は薄い。閾値は観察寄り", text)

    def test_daily_review_text_block_contains_compact_sections(self) -> None:
        text = _daily_review_text_block(
            {
                "closed_n": 3,
                "active_row_n": 8,
                "row_n": 10,
                "skip_out_of_time_n": 1,
                "last_time": "2026-03-18 15:35:00",
                "last_result": "SKIP_OUT_OF_TIME",
                "win_rate_pct": 66.7,
                "profit_factor_jpy": 1.8,
                "avg_ret_pct": 0.05,
                "pnl_jpy_sum": 123.0,
                "good_hours": [10],
                "bad_hours": [13],
                "best_trade": {"result": "PAPER_EXIT_TP", "pnl_jpy": 50.0, "ret_pct": 0.3},
                "worst_trade": {"result": "PAPER_EXIT_SL", "pnl_jpy": -20.0, "ret_pct": -0.1},
            },
            {
                "sample_confidence": "medium",
                "drift_status": "NORMAL",
                "loss_pattern_breakdown": {"reversal": 1, "weak_follow_through": 2, "late_entry": 0, "other": 0},
                "dominant_loss_pattern_label_ja": "伸び不足",
                "opportunity_pattern_breakdown": {"entry_unfilled": 1, "exit_unfilled": 1, "news_avoidance": 3, "time_block": 2, "spread_block": 0},
                "dominant_opportunity_pattern_label_ja": "時間帯回避",
                "guard_counts": {
                    "ai_block": 2,
                    "ai_block_htf60_countertrend": 1,
                    "ai_block_htf15_60_conflict": 2,
                    "buy_fast_ma_near": 1,
                    "trend_flip_cooldown": 3,
                    "trend_strength_weak": 2,
                },
                "risk_stop": False,
                "streak_stop": True,
            },
            {
                "available": True,
                "closed_n": 9,
                "win_rate_pct": 55.5,
                "pnl_jpy_sum": 44.0,
                "exit_technical_n": 1,
                "weak_progress_exit_n": 1,
                "progress_reversal_exit_n": 1,
                "no_follow_through_exit_n": 1,
                "observe_trend_strength_weak_n": 2,
                "plain_timeout_n": 2,
                "timeout_n": 3,
            },
        )
        self.assertIn("【日次レビュー】", text)
        self.assertIn("成績=信頼度中", text)
        self.assertIn("稼働=active=8", text)
        self.assertIn("guard(ai/buy_near/flip/trend/htf60/conflict)=2/1/3/2/1/2", text)
        self.assertIn("環境=drift=NORMAL", text)
        self.assertIn("復帰=復帰OK", text)
        self.assertIn("負け型=反転=1/伸び=2/遅れ=0 / dominant=伸び不足", text)
        self.assertIn("機会損失=entry失敗=1/exit失敗=1/news=3/time=2/spread=0 / dominant=時間帯回避", text)
        self.assertIn("代表取引=best=PAPER_EXIT_TP", text)
        self.assertIn("影運用=close=9 / win=55.5% / pnl=+44.00JPY / exit_tech=1 / weak_progress=1 / progress_reversal=1 / near_tp=0 / no_follow=1 / trend_weak=2 / htf60_block=0 / conflict_block=0 / timeout=2", text)

    def test_evaluate_daily_reflection_auto_apply_allows_safe_keys(self) -> None:
        result = _evaluate_daily_reflection_auto_apply(
            reflection={
                "sample_confidence": "high",
                "suggested_control_updates": {
                    "ai_train_weekly_bad_hours": "13",
                    "no_paper_hours": "13",
                },
            },
            sec={
                "trade_notify_daily_reflection_auto_apply_enabled": True,
                "trade_notify_daily_reflection_auto_apply_keys": "ai_train_weekly_bad_hours,no_paper_hours",
                "trade_notify_daily_reflection_auto_apply_min_confidence": "medium",
                "trade_notify_daily_reflection_auto_apply_max_changes": 2,
            },
        )
        self.assertTrue(bool(result["eligible"]))
        self.assertEqual(sorted(result["updates"].keys()), ["ai_train_weekly_bad_hours", "no_paper_hours"])

    def test_evaluate_daily_reflection_auto_apply_blocks_low_confidence_and_disallowed(self) -> None:
        result = _evaluate_daily_reflection_auto_apply(
            reflection={
                "sample_confidence": "low",
                "suggested_control_updates": {
                    "daily_loss_limit_pct": "-0.50",
                    "no_paper_hours": "13",
                },
            },
            sec={
                "trade_notify_daily_reflection_auto_apply_enabled": True,
                "trade_notify_daily_reflection_auto_apply_keys": "no_paper_hours",
                "trade_notify_daily_reflection_auto_apply_min_confidence": "high",
                "trade_notify_daily_reflection_auto_apply_max_changes": 2,
            },
        )
        self.assertFalse(bool(result["eligible"]))
        self.assertEqual(result["updates"], {"no_paper_hours": "13"})
        self.assertIn("daily_loss_limit_pct", list(result["blocked_keys"]))

    def test_build_daily_reflection_llm_prompt_contains_metrics(self) -> None:
        prompt = _build_daily_reflection_llm_prompt(
            day8="20260318",
            goal_jpy=100.0,
            daily_review={
                "closed_n": 2,
                "win_rate_pct": 50.0,
                "ret_sum_pct": 0.2,
                "avg_ret_pct": 0.1,
                "pnl_jpy_sum": 12.3,
                "profit_factor_jpy": 1.2,
                "exit_reason_breakdown": {"TP": 1, "SL": 1, "TIMEOUT": 0, "EOD": 0},
                "good_hours": [10],
                "bad_hours": [11],
            },
            reflection={
                "drift_status": "NORMAL",
                "risk_stop": False,
                "streak_stop": False,
                "loss_pattern_breakdown": {"reversal": 1, "weak_follow_through": 0, "late_entry": 1, "other": 0},
                "dominant_loss_pattern_label_ja": "反転巻き込み",
                "opportunity_pattern_breakdown": {"entry_unfilled": 1, "exit_unfilled": 2, "news_avoidance": 3, "time_block": 0, "spread_block": 0},
                "dominant_opportunity_pattern_label_ja": "時間帯回避",
                "shadow_filter_hint": "維持寄り",
                "shadow_filter_reason": "trend弱 3件 (+2) / TIMEOUT 1件 (-3)",
                "shadow_htf_hint": "現状維持",
                "shadow_htf_reason": "HTF60逆風 0件 (+0) / 15/60ねじれ 0件 (+0) / TIMEOUT 1件 (-3)",
                "shadow_exit_hint": "維持寄り",
                "shadow_exit_reason": "PROGRESS_REVERSAL 1件 (+1) / 進行後TIMEOUT 0件 (+0)",
                "guard_counts": {
                    "ai_block": 2,
                    "ai_block_htf60_countertrend": 1,
                    "ai_block_htf15_60_conflict": 2,
                    "buy_fast_ma_near": 1,
                    "trend_flip_cooldown": 3,
                    "trend_strength_weak": 2,
                },
                "suggested_control_updates": {"streak_stop_enabled": "1"},
            },
            shadow_review={
                "closed_n": 7,
                "exit_technical_n": 2,
                "weak_progress_exit_n": 1,
                "progress_reversal_exit_n": 1,
                "progress_timeout_n": 0,
                "no_follow_through_exit_n": 1,
                "observe_trend_strength_weak_n": 3,
                "timeout_n": 1,
            },
        )
        self.assertIn("日付: 20260318", prompt)
        self.assertIn("goal_jpy: 100.00", prompt)
        self.assertIn("streak_stop_enabled=1", prompt)
        self.assertIn("sample_confidence:", prompt)
        self.assertIn("dominant_loss_pattern_label_ja: 反転巻き込み", prompt)
        self.assertIn("dominant_opportunity_pattern_label_ja: 時間帯回避", prompt)
        self.assertIn("ai_block_n:", prompt)
        self.assertIn("ai_block_htf60_countertrend_n: 1", prompt)
        self.assertIn("ai_block_htf15_60_conflict_n: 2", prompt)
        self.assertIn("closed_n<=1", prompt)
        self.assertIn("shadow_filter_hint: 維持寄り", prompt)
        self.assertIn("shadow_htf_hint: 現状維持", prompt)
        self.assertIn("shadow_exit_hint: 維持寄り", prompt)
        self.assertIn("shadow_weak_progress_n: 1", prompt)
        self.assertIn("shadow_progress_reversal_n: 1", prompt)
        self.assertIn("shadow_progress_timeout_n: 0", prompt)
        self.assertIn("shadow_no_follow_through_n: 1", prompt)
        self.assertIn("shadow_timeout_n: 1", prompt)

    def test_generate_daily_reflection_llm_feedback_off_mode(self) -> None:
        feedback = _generate_daily_reflection_llm_feedback(
            day8="20260318",
            goal_jpy=100.0,
            daily_review={"closed_n": 1, "exit_reason_breakdown": {}},
            reflection={
                "win_notes": [],
                "loss_notes": [],
                "next_day_actions": [],
                "suggested_control_updates": {},
                "shadow_filter_hint": "評価保留",
                "shadow_filter_reason": "",
                "shadow_htf_hint": "評価保留",
                "shadow_htf_reason": "",
                "shadow_exit_hint": "評価保留",
                "shadow_exit_reason": "",
            },
            shadow_review={"available": False},
            sec={"trade_notify_daily_reflection_llm_mode": "off"},
        )
        self.assertFalse(bool(feedback["used"]))
        self.assertEqual(feedback["reason"], "llm_mode=off")

    def test_generate_daily_reflection_llm_feedback_openai_missing_key_is_safe(self) -> None:
        feedback = _generate_daily_reflection_llm_feedback(
            day8="20260318",
            goal_jpy=100.0,
            daily_review={"closed_n": 1, "exit_reason_breakdown": {}},
            reflection={
                "win_notes": [],
                "loss_notes": [],
                "next_day_actions": [],
                "suggested_control_updates": {},
                "shadow_filter_hint": "評価保留",
                "shadow_filter_reason": "",
                "shadow_htf_hint": "評価保留",
                "shadow_htf_reason": "",
                "shadow_exit_hint": "評価保留",
                "shadow_exit_reason": "",
            },
            shadow_review={"available": False},
            sec={
                "trade_notify_daily_reflection_llm_mode": "openai",
                "trade_notify_daily_reflection_openai_api_key_env": "OUROBOROS_TEST_MISSING_OPENAI_KEY",
            },
        )
        self.assertFalse(bool(feedback["used"]))
        self.assertEqual(feedback["provider"], "openai")
        self.assertEqual(feedback["reason"], "openai_failed")
        self.assertIn("OUROBOROS_TEST_MISSING_OPENAI_KEY", feedback["error"])

    def test_ollama_attempt_model_order_tries_smaller_generate_model_after_requested(self) -> None:
        order = _ollama_attempt_model_order(
            requested_model="qwen2.5:1.5b",
            installed_models=["nomic-embed-text:latest", "qwen2.5:1.5b", "qwen2.5:0.5b"],
            fallback_models=["qwen2.5:0.5b"],
            auto_mode=True,
        )
        self.assertEqual(order[:2], ["qwen2.5:1.5b", "qwen2.5:0.5b"])
        self.assertNotIn("nomic-embed-text:latest", order)

    def test_generate_daily_reflection_llm_feedback_falls_back_to_smaller_ollama_model(self) -> None:
        good_summary = (
            "総評: pnl_jpy=12.30 で goal_jpy=100.00 は未達だが、closed_n=2 の確認はできた。\n"
            "勝因: win_rate_pct=50.0 と TP=1 があり、good_hours=10 の反応が残った。\n"
            "敗因: SL=1 と bad_hours=11 があり、drift=NORMAL でも伸びに課題がある。\n"
            "翌日: suggested=0 件として、closed_n=2 以上とshadowの継続確認を優先する。"
        )
        with patch("tools.trade_event_notifier._ollama_list_models", return_value=["qwen2.5:1.5b", "qwen2.5:0.5b"]), patch(
            "tools.trade_event_notifier._run_ollama_summary",
            side_effect=[TimeoutError("slow model"), good_summary],
        ):
            feedback = _generate_daily_reflection_llm_feedback(
                day8="20260318",
                goal_jpy=100.0,
                daily_review={"closed_n": 2, "pnl_jpy_sum": 12.3, "win_rate_pct": 50.0, "exit_reason_breakdown": {"TP": 1, "SL": 1}},
                reflection={
                    "win_notes": ["TPあり"],
                    "loss_notes": ["目標未達"],
                    "next_day_actions": ["継続確認"],
                    "suggested_control_updates": {},
                    "drift_status": "NORMAL",
                    "shadow_filter_hint": "維持寄り",
                    "shadow_htf_hint": "維持寄り",
                    "shadow_exit_hint": "維持寄り",
                },
                shadow_review={"available": False},
                sec={
                    "trade_notify_daily_reflection_llm_mode": "auto",
                    "trade_notify_daily_reflection_ollama_model": "qwen2.5:1.5b",
                    "trade_notify_daily_reflection_ollama_attempt_timeout_sec": 3,
                },
            )
        self.assertTrue(bool(feedback["used"]))
        self.assertEqual(feedback["model"], "qwen2.5:0.5b")
        self.assertEqual(feedback["attempted_models"][:2], ["qwen2.5:1.5b", "qwen2.5:0.5b"])
        self.assertIn("qwen2.5:1.5b", feedback["attempt_errors"])

    def test_generate_daily_reflection_llm_feedback_uses_rule_fallback_when_ollama_fails(self) -> None:
        with patch("tools.trade_event_notifier._ollama_list_models", return_value=["qwen2.5:1.5b"]), patch(
            "tools.trade_event_notifier._run_ollama_summary",
            side_effect=TimeoutError("timeout"),
        ):
            feedback = _generate_daily_reflection_llm_feedback(
                day8="20260318",
                goal_jpy=100.0,
                daily_review={"closed_n": 1, "pnl_jpy_sum": -10.0, "win_rate_pct": 0.0, "exit_reason_breakdown": {"TP": 0, "SL": 1}},
                reflection={
                    "win_notes": [],
                    "loss_notes": ["SL=1"],
                    "next_day_actions": ["慎重運用"],
                    "suggested_control_updates": {},
                    "drift_status": "INSUFFICIENT",
                    "shadow_filter_hint": "評価保留",
                    "shadow_htf_hint": "評価保留",
                    "shadow_exit_hint": "評価保留",
                },
                shadow_review={"available": False},
                sec={"trade_notify_daily_reflection_llm_mode": "auto"},
            )
        self.assertFalse(bool(feedback["used"]))
        self.assertTrue(bool(feedback["fallback_used"]))
        self.assertIn("総評:", feedback["summary"])
        self.assertEqual(feedback["reason"], "generate_failed_fallback")

    def test_is_low_quality_llm_summary_rejects_repeated_numeric_lines(self) -> None:
        text = (
            "総評: 66.70%\n"
            "勝因: 66.70%\n"
            "敗因: 33.30%\n"
            "翌日: 3\n"
            "\n"
            "総評: 66.70%\n"
            "勝因: 66.70%\n"
            "敗因: 33.30%\n"
            "翌日: 3\n"
        )
        self.assertTrue(_is_low_quality_llm_summary(text))

    def test_is_low_quality_llm_summary_accepts_structured_four_lines(self) -> None:
        text = (
            "総評: pnl_jpy=123.00 で goal_jpy=100.00 を上回り、closed_n=3 でも崩れは小さい。\n"
            "勝因: win_rate_pct=66.7 と TP=2 が優勢で、good_hours=10 時の寄与が残った。\n"
            "敗因: SL=1 が残り、bad_hours=13 時は avg_ret_pct が弱く再現性に課題がある。\n"
            "翌日: suggested=1 件として ai_train_weekly_good_hours=10 を維持し、closed_n=3 以上を継続確認する。"
        )
        self.assertFalse(_is_low_quality_llm_summary(text))


if __name__ == "__main__":
    unittest.main()
