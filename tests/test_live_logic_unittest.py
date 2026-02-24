from __future__ import annotations

import unittest
from datetime import datetime, timedelta

import bot


class DummyClient:
    def __init__(self, executed_size: float, average_price: float = 0.0, state: str = "COMPLETED") -> None:
        self.executed_size = executed_size
        self.average_price = average_price
        self.state = state
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


class LiveLogicTest(unittest.TestCase):
    def test_compute_limit_price_buy_sell(self) -> None:
        self.assertEqual(bot.compute_limit_price("BUY", 100.0, 101.0, 0), 100.0)
        self.assertEqual(bot.compute_limit_price("SELL", 100.0, 101.0, 0), 101.0)
        self.assertEqual(bot.compute_limit_price("BUY", 100.0, 101.0, 2), 102.0)
        self.assertEqual(bot.compute_limit_price("SELL", 100.0, 101.0, 2), 99.0)

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


if __name__ == "__main__":
    unittest.main()
