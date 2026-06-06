from __future__ import annotations

from typing import Dict, List, Optional

from ibkr_adapter import IBKRAdapter, _clean_number


class IBKRPaperAdapter(IBKRAdapter):
    """Paper-trading adapter that extends the read-only IBKR adapter with order APIs.

    Intended caller:
    - ibkr_bot.py

    Keep this import surface narrow so read-only utilities do not accidentally
    gain order-capable access.
    """

    def place_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        order_type: str = "MKT",
        limit_price: Optional[float] = None,
        exchange: str = "SMART",
        currency: str = "USD",
        tif: str = "DAY",
    ) -> Dict[str, object]:
        if self.readonly:
            raise RuntimeError("Cannot place orders in readonly mode. Use readonly=False for paper trading.")
        self._require_connected()
        contract = self._ib_mod.Stock(str(symbol).upper(), exchange, currency)
        qualified = self._ib.qualifyContracts(contract)
        if qualified:
            contract = qualified[0]
        action_up = str(action).upper()
        qty_int = max(1, int(quantity))
        otype = str(order_type).upper()
        if otype == "LMT" and limit_price is not None:
            order = self._ib_mod.LimitOrder(action_up, qty_int, round(float(limit_price), 4))
        else:
            order = self._ib_mod.MarketOrder(action_up, qty_int)
        order.tif = tif
        trade = self._ib.placeOrder(contract, order)
        self._ib.sleep(1.5)
        return {
            "order_id": trade.order.orderId,
            "perm_id": trade.order.permId,
            "symbol": str(symbol).upper(),
            "action": action_up,
            "quantity": qty_int,
            "order_type": otype,
            "limit_price": limit_price,
            "tif": tif,
            "status": trade.orderStatus.status,
            "filled": trade.orderStatus.filled,
            "remaining": trade.orderStatus.remaining,
            "avg_fill_price": _clean_number(trade.orderStatus.avgFillPrice),
        }

    def get_open_orders(self) -> List[Dict[str, object]]:
        self._require_connected()
        self._ib.reqAllOpenOrders()
        self._ib.sleep(0.5)
        result: List[Dict[str, object]] = []
        done = {"Filled", "Cancelled", "Inactive"}
        for trade in self._ib.trades():
            if str(trade.orderStatus.status or "").strip() in done:
                continue
            c = trade.contract
            o = trade.order
            s = trade.orderStatus
            result.append({
                "order_id": o.orderId,
                "perm_id": o.permId,
                "symbol": getattr(c, "symbol", ""),
                "sec_type": getattr(c, "secType", ""),
                "action": o.action,
                "quantity": o.totalQuantity,
                "order_type": o.orderType,
                "limit_price": _clean_number(o.lmtPrice) if o.orderType == "LMT" else None,
                "status": s.status,
                "filled": s.filled,
                "remaining": s.remaining,
            })
        return result

    def get_trades(self) -> List[Dict[str, object]]:
        self._require_connected()
        result: List[Dict[str, object]] = []
        for fill in self._ib.fills():
            c = fill.contract
            ex = fill.execution
            result.append({
                "order_id": ex.orderId,
                "perm_id": ex.permId,
                "exec_id": ex.execId,
                "symbol": getattr(c, "symbol", ""),
                "sec_type": getattr(c, "secType", ""),
                "side": ex.side,
                "shares": ex.shares,
                "price": _clean_number(ex.price),
                "time": str(ex.time or ""),
                "exchange": ex.exchange,
                "account": ex.acctNumber,
            })
        return result

    def cancel_order(self, order_id: int) -> Dict[str, object]:
        self._require_connected()
        for trade in self._ib.trades():
            if trade.order.orderId == int(order_id):
                self._ib.cancelOrder(trade.order)
                self._ib.sleep(0.5)
                return {"cancelled": True, "order_id": int(order_id), "status": trade.orderStatus.status}
        return {"cancelled": False, "order_id": int(order_id), "reason": "order_not_found"}
