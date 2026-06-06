from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tools.widget_status import (
    _content_type_for_path,
    _resolve_widget_react_path,
    _status_page_html,
    _widget_home_page_html,
    _widget_home_manifest,
    _widget_home_service_worker,
    build_widget_status,
    format_status_text,
    format_swiftbar,
    _widget_app_icon_svg,
    _widget_app_manifest,
    _widget_app_service_worker,
)
from yt_tool_version import TOOL_VERSION


class WidgetStatusTest(unittest.TestCase):
    def _write_control(self, path: Path, rows: dict[str, str]) -> None:
        lines = ["key,value"]
        for k, v in rows.items():
            lines.append(f"{k},{v}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_build_widget_status_warns_when_trade_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            main_dir = Path(tmp)
            day8 = datetime.now().strftime("%Y%m%d")
            day_label = datetime.now().strftime("%Y-%m-%d")
            self._write_control(
                main_dir / "CONTROL.csv",
                {
                    "trade_enabled": "0",
                    "today_on": "1",
                    "live_enabled": "1",
                    "paper_mode": "0",
                    "ai_auto_train_enabled": "1",
                    "ai_gate_enabled": "1",
                    "daily_loss_limit_pct": "-1.0",
                    "rollout_mode": "CANARY",
                },
            )
            state = {
                "_effective_stage": "CANARY",
                "_risk_stop": False,
                "_streak_stop": False,
                "_streak_consecutive_losses": 0,
                "_drift_watch": {
                    "status": "INSUFFICIENT",
                    "updated_at": "2026-03-15 10:00:00",
                    "recent_metrics": {"closed_n": 3},
                    "gate": {
                        "min_recent_closed": 8,
                        "resume_require_consecutive_normal": 4,
                        "resume_canary_runs": 2,
                    },
                    "normal_streak": 1,
                    "canary_streak": 0,
                    "resume_ready": False,
                    "reasons": ["recent_closed<8 (3)"],
                },
            }
            (main_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

            status = build_widget_status(main_dir)

            self.assertEqual(status["status_level"], "WARN")
            self.assertFalse(status["trade_enabled"])
            self.assertEqual(status["drift"]["remaining_samples"], 5)
            self.assertEqual(status["drift"]["resume_outlook"]["summary"], "復帰まで約定あと5件")
            self.assertIn("trade_enabled=0", status["warnings"])

    def test_build_widget_status_detects_alive_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            main_dir = Path(tmp)
            self._write_control(
                main_dir / "CONTROL.csv",
                {
                    "trade_enabled": "1",
                    "today_on": "1",
                    "live_enabled": "1",
                    "paper_mode": "0",
                    "ai_auto_train_enabled": "1",
                    "ai_gate_enabled": "1",
                    "daily_loss_limit_pct": "-1.0",
                    "rollout_mode": "LIVE",
                },
            )
            state = {
                "_effective_stage": "LIVE",
                "_risk_stop": False,
                "_streak_stop": False,
                "_drift_watch": {
                    "status": "NORMAL",
                    "updated_at": "2026-03-15 10:00:00",
                    "recent_metrics": {"closed_n": 8},
                    "gate": {
                        "min_recent_closed": 8,
                        "resume_require_consecutive_normal": 4,
                        "resume_canary_runs": 2,
                    },
                    "normal_streak": 4,
                    "canary_streak": 2,
                    "resume_ready": True,
                    "canary_ready": True,
                },
            }
            (main_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
            lock_dir = main_dir / ".run_lock"
            lock_dir.mkdir(parents=True, exist_ok=True)
            (lock_dir / "lockinfo.txt").write_text(f"pid={os.getpid()}\n", encoding="utf-8")

            status = build_widget_status(main_dir)

            self.assertEqual(status["status_level"], "OK")
            self.assertTrue(status["runner_alive"])
            self.assertEqual(status["drift"]["remaining_samples"], 0)
            self.assertTrue(status["drift"]["resume_ready"])
            self.assertEqual(status["drift"]["resume_outlook"]["summary"], "復帰OK")

    def test_widget_app_manifest_embeds_tokenized_start_url(self) -> None:
        manifest = _widget_app_manifest("token-123")
        self.assertEqual(manifest["name"], "Ouroboros Widget")
        self.assertIn("/widget-app?token=token-123&source=pwa", manifest["start_url"])

    def test_widget_app_service_worker_embeds_tokenized_shell_urls(self) -> None:
        sw = _widget_app_service_worker("token-123")
        self.assertIn('/widget-app?token=token-123', sw)
        self.assertIn('/widget-status.json?token=token-123', sw)
        self.assertIn("OFFLINE_STATUS", sw)
        self.assertIn('"X-Ouroboros-Offline": "1"', sw)

    def test_widget_app_icon_svg_contains_ouroboros_branding(self) -> None:
        svg = _widget_app_icon_svg()
        self.assertIn("<svg", svg)
        self.assertIn("FF6B3B", svg)
        self.assertIn("Ouroboros Widget", svg)

    def test_widget_app_html_includes_app_nav(self) -> None:
        html = _status_page_html("token-123", app_mode=True)
        self.assertIn(">Overview<", html)
        self.assertIn("/daily-reflection?token=token-123", html)
        self.assertIn(">Dashboard<", html)
        self.assertIn("bottomnav", html)
        self.assertIn("Reflection Snapshot", html)
        self.assertIn("ios-statusbar", html)
        self.assertIn("dynamic-island", html)
        self.assertIn("Home Widgets", html)
        self.assertIn("home-indicator", html)

    def test_widget_home_manifest_embeds_tokenized_start_url(self) -> None:
        manifest = _widget_home_manifest("token-123")
        self.assertEqual(manifest["name"], "Ouroboros Home")
        self.assertIn("/widget-home?token=token-123&source=pwa", manifest["start_url"])

    def test_widget_home_service_worker_embeds_tokenized_shell_urls(self) -> None:
        sw = _widget_home_service_worker("token-123")
        self.assertIn('/widget-home?token=token-123', sw)
        self.assertIn('/widget-status.json?token=token-123', sw)
        self.assertIn("OFFLINE_STATUS", sw)

    def test_widget_home_html_uses_zip_inspired_home_screen(self) -> None:
        html = _widget_home_page_html("token-123")
        self.assertIn("Ouroboros Home", html)
        self.assertIn("class=\"island\"", html)
        self.assertIn("class=\"dock\"", html)
        self.assertIn("/widget-status.json", html)
        self.assertIn("/widget-home-manifest.json", html)
        self.assertIn("/widget-app?token=token-123", html)

    def test_widget_home_native_shell_hides_web_chrome(self) -> None:
        html = _widget_home_page_html("token-123", native_shell=True)
        self.assertIn('body class="native-shell"', html)
        self.assertIn("body.native-shell .statusbar", html)
        self.assertIn("body.native-shell .dock", html)
        self.assertIn('if (!document.body.classList.contains("native-shell"))', html)

    def test_widget_react_zip_assets_are_servable(self) -> None:
        index_path = _resolve_widget_react_path("/widget-react/index.html")
        app_path = _resolve_widget_react_path("/widget-react/portfolio-widget/app.jsx")
        live_path = _resolve_widget_react_path("/widget-react/portfolio-widget/ouroboros-live.jsx")
        self.assertIsNotNone(index_path)
        self.assertIsNotNone(app_path)
        self.assertIsNotNone(live_path)
        self.assertEqual(_content_type_for_path(Path("app.jsx")), "application/javascript; charset=utf-8")
        index_html = index_path.read_text(encoding="utf-8")
        self.assertIn("ポートフォリオ・ウィジェット", index_html)
        self.assertIn("portfolio-widget/ouroboros-live.jsx", index_html)
        self.assertIn("portfolio-widget/app.jsx", index_html)
        live_js = live_path.read_text(encoding="utf-8")
        self.assertIn("OUROBOROS_LIVE", live_js)
        self.assertIn("widget-status.json", live_js)
        app_js = app_path.read_text(encoding="utf-8")
        self.assertIn("sceneFromQuery", app_js)
        self.assertIn("queryFlag", app_js)
        self.assertIn("nativeEmbed", app_js)
        self.assertIn("OuroborosOverviewScene", app_js)
        self.assertIn("OuroborosReflectionScene", app_js)
        self.assertIn("OverviewDonutHero", app_js)
        self.assertIn("AccountStackCard", app_js)
        self.assertNotIn("WidgetLabCard", app_js)
        self.assertIn("ShadowDeskCard", app_js)
        self.assertIn("LockWidgetGallery", app_js)
        self.assertIn("standby", app_js)

    def test_build_widget_status_includes_goal_and_balance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            main_dir = Path(tmp)
            day8 = datetime.now().strftime("%Y%m%d")
            day_label = datetime.now().strftime("%Y-%m-%d")
            self._write_control(
                main_dir / "CONTROL.csv",
                {
                    "trade_enabled": "1",
                    "today_on": "1",
                    "live_enabled": "1",
                    "paper_mode": "0",
                    "exchange_name": "bitflyer",
                    "market_type": "SPOT",
                    "rollout_mode": "LIVE",
                },
            )
            (main_dir / "state.json").write_text(
                json.dumps(
                    {
                        "_effective_stage": "LIVE",
                        "_drift_watch": {"status": "NORMAL", "recent_metrics": {"closed_n": 6}, "gate": {"min_recent_closed": 6}},
                        "_market_phase": {
                            "phase": "C",
                            "previous_phase": "B",
                            "transition": "B->C",
                            "phase_reason": "MA_UP",
                            "momentum": "UP_BREAK",
                            "changed_at_jst": f"{day_label} 10:05:00",
                            "updated_at_jst": f"{day_label} 10:05:00",
                        },
                        "_weekly_auto_feedback": {
                            "updated_at": f"{day_label} 19:00:00",
                            "shadow_weekly_review": {
                                "available": True,
                                "decision": "保留",
                                "reason": "shadow PF差=+0.0100",
                                "pattern_hint": "entry品質不足",
                                "pattern_reason": "late_entry 差が +3",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            logs_dir = main_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (logs_dir / f"trade_log_{day8}.csv").write_text(
                "\n".join(
                    [
                        "time,result,pos_id,side,price,size,ltp",
                        f"{day_label} 09:00:00,PAPER,p1,BUY,100,2,100",
                        f"{day_label} 09:05:00,PAPER_EXIT_TP,p1,BUY,100,2,110",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            shadow_logs_dir = logs_dir / "instances" / "shadow"
            shadow_logs_dir.mkdir(parents=True, exist_ok=True)
            (shadow_logs_dir / f"trade_log_{day8}.csv").write_text(
                "\n".join(
                    [
                        "time,result,pos_id,side,price,size,ltp,note",
                        f"{day_label} 08:00:00,PAPER,s1,SELL,100,1,100",
                        f"{day_label} 08:02:00,OBSERVE_TREND_STRENGTH_WEAK,,,,,,,",
                        f"{day_label} 08:03:00,OBSERVE_AI_BLOCK,,,,,,AI_BLOCK AI score=0.820 htf60_countertrend=1 htf15_60_conflict=1",
                        f"{day_label} 08:05:00,PAPER_EXIT_SL,s1,SELL,100,1,110,exit_tech=SMA_CROSS_UP",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            report_dir = main_dir / "daily_report_out"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / f"daily_reflection_{day8}.json").write_text(
                json.dumps(
                    {
                        "meta": {"generated_at_jst": f"{day_label} 18:00:00"},
                        "goal": {"achieved": False},
                        "range": {"day8": day8},
                        "reflection": {
                            "sample_confidence": "high",
                            "next_day_actions": ["悪い時間帯は外す"],
                            "win_notes": ["朝の反発は素直"],
                            "loss_notes": ["逆張りが重い"],
                            "shadow_filter_hint": "維持寄り",
                            "shadow_htf_hint": "観察寄り",
                            "shadow_exit_hint": "観察寄り",
                        },
                        "approval": {"status": "pending", "changed_keys": []},
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "tools.widget_status._load_account_balance_snapshot",
                return_value={
                    "available": True,
                    "jpy": 123456.0,
                    "kind": "balance",
                    "label": "残高",
                    "source": "test",
                    "error": "",
                    "updated_at": "2026-03-20 09:10:00",
                },
            ):
                status = build_widget_status(main_dir)

            self.assertEqual(status["goal"]["goal_jpy"], 100.0)
            self.assertAlmostEqual(float(status["goal"]["pnl_jpy"]), 20.0, places=6)
            self.assertAlmostEqual(float(status["goal"]["remaining_jpy"]), 80.0, places=6)
            self.assertFalse(status["goal"]["achieved"])
            self.assertTrue(status["balance"]["available"])
            self.assertAlmostEqual(float(status["balance"]["jpy"]), 123456.0, places=6)
            self.assertTrue(status["latest_trade"]["available"])
            self.assertEqual(status["latest_trade"]["kind"], "EXIT")
            self.assertEqual(status["latest_trade"]["reason"], "TP")
            self.assertAlmostEqual(float(status["latest_trade"]["pnl_jpy"]), 20.0, places=6)
            self.assertIn(status["freshness"]["status"], {"OK", "WARN"})
            self.assertTrue(status["weekly"]["available"])
            self.assertAlmostEqual(float(status["weekly"]["pnl_jpy_sum"]), 20.0, places=6)
            self.assertEqual(status["weekly"]["shadow_decision"], "保留")
            self.assertEqual(status["weekly"]["pattern_hint"], "entry品質不足")
            self.assertTrue(status["shadow_day"]["available"])
            self.assertEqual(int(status["shadow_day"]["closed_n"]), 1)
            self.assertAlmostEqual(float(status["shadow_day"]["pnl_jpy_sum"]), -10.0, places=6)
            self.assertEqual(int(status["shadow_day"]["exit_technical_n"]), 1)
            self.assertEqual(int(status["shadow_day"]["weak_progress_exit_n"]), 0)
            self.assertEqual(int(status["shadow_day"]["progress_reversal_exit_n"]), 0)
            self.assertEqual(int(status["shadow_day"]["progress_timeout_n"]), 0)
            self.assertEqual(int(status["shadow_day"]["no_follow_through_exit_n"]), 0)
            self.assertEqual(int(status["shadow_day"]["plain_timeout_n"]), 0)
            self.assertEqual(int(status["shadow_day"]["observe_trend_strength_weak_n"]), 1)
            self.assertEqual(int(status["shadow_day"]["observe_ai_block_htf60_countertrend_n"]), 1)
            self.assertEqual(int(status["shadow_day"]["observe_ai_block_htf15_60_conflict_n"]), 1)
            self.assertEqual(int(status["shadow_day"]["timeout_n"]), 0)
            self.assertTrue(status["latest_reflection"]["available"])
            self.assertEqual(status["latest_reflection"]["day8"], day8)
            self.assertEqual(status["versions"]["dashboard"], "v1.1.9")
            self.assertEqual(status["versions"]["widget_status_server"], "OuroborosWidget/1.0")
            self.assertEqual(status["versions"]["bot_logic"], "2026.05.21.1")
            self.assertEqual(status["versions"]["feature_schema"], "ohlc-chart-pattern-quality-market-phase-transition-near-tp-aiba-phase-fallback-mfe-mae-fib-elliott-v1")
            self.assertEqual(status["versions"]["yt_tool"], f"v{TOOL_VERSION}")
            self.assertEqual(status["versions"]["mr_observe_phase"], "phase1.5-a-rank-paper")
            self.assertEqual(status["market_phase"]["phase"], "C")
            self.assertEqual(status["market_phase"]["transition"], "B->C")
            self.assertIn("bot:2026.05.21.1", format_status_text(status))
            self.assertIn("market_phase=C transition=B->C", format_status_text(status))
            self.assertIn("dashboard:v1.1.9", format_status_text(status))
            self.assertEqual(status["latest_reflection"]["next_actions"][0], "悪い時間帯は外す")
            self.assertEqual(status["latest_reflection"]["shadow_filter_hint"], "維持寄り")
            self.assertEqual(status["latest_reflection"]["shadow_htf_hint"], "観察寄り")
            self.assertEqual(status["latest_reflection"]["shadow_exit_hint"], "観察寄り")

    def test_text_and_swiftbar_formats_include_key_fields(self) -> None:
        status = {
            "status_level": "WARN",
            "headline": "CANARY / trade OFF / drift INSUFFICIENT",
            "mode_label": "LIVE",
            "risk_stop": False,
            "streak_stop": False,
            "runner_alive": False,
            "ai_auto_train_enabled": True,
            "trade_enabled": False,
            "daily_loss_limit_pct": -1.0,
            "generated_at": "2026-03-15 12:00:00",
            "warnings": ["trade_enabled=0"],
            "source": {"state_mtime": "2026-03-15 11:59:00"},
            "goal": {
                "day8": "20260315",
                "goal_jpy": 100.0,
                "pnl_jpy": 40.0,
                "remaining_jpy": 60.0,
                "achieved": False,
            },
            "balance": {
                "available": True,
                "jpy": 120000.0,
                "label": "残高",
            },
            "freshness": {
                "status": "WARN",
                "reference": "state",
                "age_text": "12分前",
                "summary": "state更新 12分前",
            },
            "latest_trade": {
                "available": True,
                "kind": "EXIT",
                "reason": "TP",
                "pnl_jpy": 40.0,
                "age_text": "5分前",
            },
            "weekly": {
                "available": True,
                "pnl_jpy_sum": 55.0,
                "win_rate_pct": 66.6,
                "closed_n": 3,
                "start_day8": "20260317",
                "shadow_decision": "保留",
                "pattern_hint": "entry品質不足",
            },
            "shadow_day": {
                "available": True,
                "day8": "20260315",
                "pnl_jpy_sum": -12.0,
                "win_rate_pct": 33.3,
                "closed_n": 3,
                "exit_technical_n": 2,
                "weak_progress_exit_n": 1,
                "progress_reversal_exit_n": 1,
                "near_tp_giveback_exit_n": 1,
                "progress_timeout_n": 1,
                "no_follow_through_exit_n": 1,
                "plain_timeout_n": 0,
                "observe_trend_strength_weak_n": 4,
                "observe_ai_block_htf60_countertrend_n": 2,
                "observe_ai_block_htf15_60_conflict_n": 1,
                "timeout_n": 1,
            },
            "latest_reflection": {
                "available": True,
                "day8": "20260319",
                "goal_achieved": False,
                "next_actions": ["悪い時間帯は外す"],
                "shadow_filter_hint": "維持寄り",
                "shadow_htf_hint": "観察寄り",
                "shadow_exit_hint": "観察寄り",
            },
            "market_phase": {
                "phase": "A",
                "transition": "C->A",
                "phase_reason": "MA_DOWN",
                "momentum": "DOWN_BREAK",
                "changed_at_jst": "2026-03-15 10:30:00",
            },
            "drift": {
                "status": "INSUFFICIENT",
                "closed_n": 3,
                "min_recent_closed": 8,
                "remaining_samples": 5,
                "resume_ready": False,
                "canary_streak": 0,
                "canary_required": 2,
                "updated_at": "2026-03-15 11:59:00",
                "resume_outlook": {
                    "summary": "復帰まで約定あと5件",
                    "detail": "直近 3/8 / 通常 0/4 / カナリア 0/2",
                },
            },
        }

        text = format_status_text(status)
        bar = format_swiftbar(status)

        self.assertIn("drift=INSUFFICIENT", text)
        self.assertIn("trade_enabled=0", text)
        self.assertIn("goal=day:20260315", text)
        self.assertIn("resume_outlook=復帰まで約定あと5件", text)
        self.assertIn("progress_reversal:1", text)
        self.assertIn("near_tp:1", text)
        self.assertIn("progress_timeout:1", text)
        self.assertIn("no_follow:1", text)
        self.assertIn("balance=残高:120,000", text)
        self.assertIn("freshness=WARN", text)
        self.assertIn("latest_trade=EXIT TP", text)
        self.assertIn("market_phase=A transition=C->A", text)
        self.assertIn("weekly=pnl_jpy:55", text)
        self.assertIn("hint:保留 / entry品質不足", text)
        self.assertIn("shadow=day:20260315", text)
        self.assertIn("tech:2", text)
        self.assertIn("weak:1", text)
        self.assertIn("progress_reversal:1", text)
        self.assertIn("trend:4", text)
        self.assertIn("htf60:2", text)
        self.assertIn("conflict:1", text)
        self.assertIn("timeout:0", text)
        self.assertIn("reflection=day:20260319 achieved:OFF adjust:filter 維持寄り / htf 観察寄り / exit 観察寄り", text)
        self.assertIn("OB WARN", bar)
        self.assertIn("Drift Remain: 5", bar)
        self.assertIn("Resume Outlook: 復帰まで約定あと5件", bar)
        self.assertIn("Market Phase: A / C->A / DOWN_BREAK", bar)
        self.assertIn("Daily Goal: 40 / 100", bar)
        self.assertIn("Freshness: WARN / 12分前", bar)
        self.assertIn("Latest Trade: TP 40", bar)
        self.assertIn("Week: 55 / 66.6% / 保留 / entry品質不足", bar)
        self.assertIn("tech 2", bar)
        self.assertIn("weak 1", bar)
        self.assertIn("ntp 1", bar)
        self.assertIn("trend 4", bar)
        self.assertIn("htf60 2", bar)
        self.assertIn("conflict 1", bar)
        self.assertIn("timeout 0", bar)
        self.assertIn("Reflection: 20260319 / filter 維持寄り / htf 観察寄り / exit 観察寄り", bar)
        self.assertIn("weekly", json.dumps(status))


if __name__ == "__main__":
    unittest.main()
