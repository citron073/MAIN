from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple


class IBKRDependencyError(RuntimeError):
    """Raised when the optional IBKR client dependency is unavailable."""


def _load_ib_insync() -> Any:
    try:
        import ib_insync  # type: ignore
    except ImportError as exc:
        raise IBKRDependencyError(
            "ib_insync is required for IBKR connectivity. Install it with: python3 -m pip install ib_insync"
        ) from exc
    return ib_insync


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return int(str(raw).strip())


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return float(str(raw).strip())


def _clean_number(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except Exception:
        return None
    if f != f:
        return None
    return f


def _split_fx_pair(pair: str) -> Tuple[str, str]:
    s = str(pair or "").strip().upper().replace("/", "").replace(".", "").replace("_", "")
    if len(s) != 6:
        raise ValueError(f"FX pair must be 6 letters like USDJPY, got: {pair!r}")
    return s[:3], s[3:]


# reqMarketDataType values: 1=live, 2=frozen, 3=delayed, 4=delayed_frozen
_MDT_MAP: Dict[str, int] = {"live": 1, "frozen": 2, "delayed": 3, "delayed_frozen": 4}


@dataclass
class IBKRAdapter:
    """Small, read-only IBKR adapter for connection checks and market-data snapshots.

    Allowed callers:
    - test_ibkr_connection.py
    - daily_ops / watch / dashboard support tools
    - ibkr_paper_adapter.py as the base class for paper-order extension

    This class should not be used as an order-capable adapter.
    """

    host: str = field(default_factory=lambda: os.getenv("IBKR_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("IBKR_PORT", 7497))
    client_id: int = field(default_factory=lambda: _env_int("IBKR_CLIENT_ID", 17))
    timeout_sec: float = field(default_factory=lambda: _env_float("IBKR_TIMEOUT_SEC", 8.0))
    readonly: bool = True
    market_data_type: str = "delayed"
    _ib: Any = field(default=None, init=False, repr=False)
    _ib_mod: Any = field(default=None, init=False, repr=False)

    def connect(self) -> bool:
        self._ib_mod = _load_ib_insync()
        self._ib = self._ib_mod.IB()
        self._ib.connect(
            self.host,
            self.port,
            clientId=self.client_id,
            timeout=self.timeout_sec,
            readonly=self.readonly,
        )
        if self.is_connected():
            mdt = _MDT_MAP.get(str(self.market_data_type).lower(), 3)
            self._ib.reqMarketDataType(mdt)
        return self.is_connected()

    def disconnect(self) -> None:
        if self._ib is not None and self._ib.isConnected():
            self._ib.disconnect()

    def is_connected(self) -> bool:
        return bool(self._ib is not None and self._ib.isConnected())

    def get_account_summary(self) -> Dict[str, Dict[str, str]]:
        self._require_connected()
        rows = self._ib.accountSummary()
        summary: Dict[str, Dict[str, str]] = {}
        for row in rows:
            account = str(getattr(row, "account", "") or "")
            tag = str(getattr(row, "tag", "") or "")
            if not account or not tag:
                continue
            summary.setdefault(account, {})[tag] = str(getattr(row, "value", "") or "")
        return summary

    def get_stock_snapshot(self, symbol: str, exchange: str = "SMART", currency: str = "USD") -> Dict[str, Any]:
        self._require_connected()
        contract = self._ib_mod.Stock(str(symbol).upper(), exchange, currency)
        qualified = self._ib.qualifyContracts(contract)
        if qualified:
            contract = qualified[0]
        return self._snapshot(contract, instrument="stock", symbol=str(symbol).upper())

    def get_stock_snapshots(
        self,
        symbols: Iterable[str],
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> Dict[str, Dict[str, Any]]:
        snapshots: Dict[str, Dict[str, Any]] = {}
        for symbol in symbols:
            normalized = str(symbol or "").strip().upper()
            if not normalized:
                continue
            try:
                snapshots[normalized] = self.get_stock_snapshot(normalized, exchange=exchange, currency=currency)
            except Exception as exc:
                snapshots[normalized] = {
                    "instrument": "stock",
                    "symbol": normalized,
                    "market_data_status": "ERROR",
                    "price_available": False,
                    "error_message": f"{type(exc).__name__}: {exc}",
                }
        return snapshots

    def get_fx_snapshot(self, pair: str = "USDJPY") -> Dict[str, Any]:
        self._require_connected()
        base, quote = _split_fx_pair(pair)
        contract = self._ib_mod.Forex(f"{base}{quote}")
        qualified = self._ib.qualifyContracts(contract)
        if qualified:
            contract = qualified[0]
        return self._snapshot(contract, instrument="fx", symbol=f"{base}{quote}")

    def get_positions(self) -> List[Dict[str, Any]]:
        self._require_connected()
        positions: List[Dict[str, Any]] = []
        for pos in self._ib.positions():
            contract = getattr(pos, "contract", None)
            positions.append(
                {
                    "account": str(getattr(pos, "account", "") or ""),
                    "position": _clean_number(getattr(pos, "position", None)),
                    "avg_cost": _clean_number(getattr(pos, "avgCost", None)),
                    "contract": {
                        "con_id": getattr(contract, "conId", None),
                        "symbol": getattr(contract, "symbol", ""),
                        "sec_type": getattr(contract, "secType", ""),
                        "exchange": getattr(contract, "exchange", ""),
                        "currency": getattr(contract, "currency", ""),
                    },
                }
            )
        return positions

    def get_historical_bars(
        self,
        symbol: str,
        bar_size: str = "1 min",
        duration: str = "1 D",
        what_to_show: str = "TRADES",
        use_rth: bool = True,
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> List[Dict[str, Any]]:
        """Request historical OHLCV bars for a stock symbol."""
        self._require_connected()
        contract = self._ib_mod.Stock(str(symbol).upper(), exchange, currency)
        qualified = self._ib.qualifyContracts(contract)
        if qualified:
            contract = qualified[0]
        bars = self._ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow=what_to_show,
            useRTH=use_rth,
            formatDate=1,
            keepUpToDate=False,
        )
        return [
            {
                "time": str(getattr(b, "date", "")),
                "open": float(getattr(b, "open", 0.0)),
                "high": float(getattr(b, "high", 0.0)),
                "low": float(getattr(b, "low", 0.0)),
                "close": float(getattr(b, "close", 0.0)),
                "volume": int(getattr(b, "volume", 0)),
            }
            for b in (bars or [])
        ]

    def _require_connected(self) -> None:
        if not self.is_connected():
            raise RuntimeError("IBKR adapter is not connected. Call connect() first.")

    def _snapshot(self, contract: Any, *, instrument: str, symbol: str) -> Dict[str, Any]:
        # Explicitly request delayed data before each snapshot to ensure TWS honours it
        mdt_int = _MDT_MAP.get(str(self.market_data_type).lower(), 3)
        self._ib.reqMarketDataType(mdt_int)

        ticker = self._ib.reqMktData(contract, "", True, False)
        deadline = time.monotonic() + self.timeout_sec
        while time.monotonic() < deadline:
            self._ib.sleep(0.2)
            if any(
                _clean_number(v) is not None
                for v in (
                    getattr(ticker, "last", None),
                    getattr(ticker, "bid", None),
                    getattr(ticker, "ask", None),
                    getattr(ticker, "close", None),
                    getattr(ticker, "marketPrice", lambda: None)(),
                )
            ):
                break
        self._ib.cancelMktData(contract)

        # IBKR returns -1.0 as a sentinel meaning "no data available"
        def _price(v: Any) -> Optional[float]:
            f = _clean_number(v)
            return None if (f is None or f == -1.0) else f

        bid = _price(getattr(ticker, "bid", None))
        ask = _price(getattr(ticker, "ask", None))
        last = _price(getattr(ticker, "last", None))
        close = _price(getattr(ticker, "close", None))
        market_price = _price(getattr(ticker, "marketPrice", lambda: None)())

        # Require a strictly positive price to count as tradable (rules out 0.0 and negatives)
        has_tradable = any(v is not None and v > 0 for v in (bid, ask, last, market_price))
        has_close = close is not None and close > 0

        mdt = str(self.market_data_type).lower()
        if has_tradable:
            mds = "LIVE_OK" if mdt == "live" else "DELAYED_OK"
        elif has_close:
            mds = "BID_ASK_UNAVAILABLE"
        else:
            mds = "NO_SUBSCRIPTION_OR_DELAYED_ONLY"

        reference_only = not has_tradable and has_close
        price_available = has_tradable
        reference_price = close if reference_only else None

        return {
            "instrument": instrument,
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "last": last,
            "close": close,
            "market_price": market_price,
            "market_data_status": mds,
            "price_available": price_available,
            "reference_only": reference_only,
            "reference_price": reference_price,
            "error_message": None,
            "time": str(getattr(ticker, "time", "") or ""),
            "contract": {
                "con_id": getattr(contract, "conId", None),
                "symbol": getattr(contract, "symbol", ""),
                "sec_type": getattr(contract, "secType", ""),
                "exchange": getattr(contract, "exchange", ""),
                "currency": getattr(contract, "currency", ""),
            },
        }


def enrich_positions_pnl(
    positions: List[Dict[str, Any]],
    stock_snapshots: Dict[str, Dict[str, Any]],
    fx_rate: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Add unrealized P&L calculation to each position using snapshot prices.

    Adds: unrealized_pnl_calc, unrealized_pnl_calc_jpy, pnl_calc_status, pnl_current_price.
    If fx_rate (e.g. USDJPY market_price) is provided, unrealized_pnl_calc_jpy is filled for USD positions.
    pnl_calc_status values: OK | REFERENCE_ONLY | PRICE_UNAVAILABLE | NO_SNAPSHOT
    """
    result: List[Dict[str, Any]] = []
    for p in positions:
        pos = dict(p)
        sym = str(((p.get("contract") or {}).get("symbol")) or "").upper()
        currency = str(((p.get("contract") or {}).get("currency")) or "").upper()
        qty = _clean_number(p.get("position"))
        avg = _clean_number(p.get("avg_cost"))
        snap = stock_snapshots.get(sym)
        if snap is not None and qty is not None and avg is not None:
            price_avail = snap.get("price_available", False)
            ref_only = snap.get("reference_only", False)
            if price_avail:
                current = (
                    _clean_number(snap.get("market_price"))
                    or _clean_number(snap.get("last"))
                    or _clean_number(snap.get("bid"))
                )
                pnl_status = "OK"
            elif ref_only:
                current = _clean_number(snap.get("reference_price") or snap.get("close"))
                pnl_status = "REFERENCE_ONLY"
            else:
                current = None
                pnl_status = "PRICE_UNAVAILABLE"
            if current is not None:
                pnl_usd = round((current - avg) * qty, 2)
                pos["unrealized_pnl_calc"] = pnl_usd
                if fx_rate is not None and currency == "USD":
                    pos["unrealized_pnl_calc_jpy"] = round(pnl_usd * fx_rate, 0)
                else:
                    pos["unrealized_pnl_calc_jpy"] = None
            else:
                pos["unrealized_pnl_calc"] = None
                pos["unrealized_pnl_calc_jpy"] = None
            pos["pnl_calc_status"] = pnl_status
            pos["pnl_current_price"] = current
        else:
            pos["unrealized_pnl_calc"] = None
            pos["unrealized_pnl_calc_jpy"] = None
            pos["pnl_calc_status"] = "NO_SNAPSHOT"
            pos["pnl_current_price"] = None
        result.append(pos)
    return result


_DEFAULT_ADAPTER = IBKRAdapter()


def connect() -> bool:
    return _DEFAULT_ADAPTER.connect()


def disconnect() -> None:
    _DEFAULT_ADAPTER.disconnect()


def is_connected() -> bool:
    return _DEFAULT_ADAPTER.is_connected()


def get_account_summary() -> Dict[str, Dict[str, str]]:
    return _DEFAULT_ADAPTER.get_account_summary()


def get_stock_snapshot(symbol: str, exchange: str = "SMART", currency: str = "USD") -> Dict[str, Any]:
    return _DEFAULT_ADAPTER.get_stock_snapshot(symbol=symbol, exchange=exchange, currency=currency)


def get_stock_snapshots(symbols: Iterable[str], exchange: str = "SMART", currency: str = "USD") -> Dict[str, Dict[str, Any]]:
    return _DEFAULT_ADAPTER.get_stock_snapshots(symbols=symbols, exchange=exchange, currency=currency)


def get_fx_snapshot(pair: str = "USDJPY") -> Dict[str, Any]:
    return _DEFAULT_ADAPTER.get_fx_snapshot(pair=pair)


def get_positions() -> List[Dict[str, Any]]:
    return _DEFAULT_ADAPTER.get_positions()


def place_order(
    symbol: str,
    action: str,
    quantity: int,
    order_type: str = "MKT",
    limit_price: Optional[float] = None,
    exchange: str = "SMART",
    currency: str = "USD",
    tif: str = "DAY",
) -> Dict[str, Any]:
    raise NotImplementedError(
        "Order placement is intentionally split out of ibkr_adapter.py. "
        "Use ibkr_paper_adapter.IBKRPaperAdapter for paper trading order flows."
    )


def get_open_orders() -> List[Dict[str, Any]]:
    raise NotImplementedError(
        "Open-order access is intentionally split out of ibkr_adapter.py. "
        "Use ibkr_paper_adapter.IBKRPaperAdapter for paper trading order flows."
    )


def get_trades() -> List[Dict[str, Any]]:
    raise NotImplementedError(
        "Trade/fill access is intentionally split out of ibkr_adapter.py. "
        "Use ibkr_paper_adapter.IBKRPaperAdapter for paper trading order flows."
    )


def cancel_order(order_id: int) -> Dict[str, Any]:
    raise NotImplementedError(
        "Order cancellation is intentionally split out of ibkr_adapter.py. "
        "Use ibkr_paper_adapter.IBKRPaperAdapter for paper trading order flows."
    )


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Read-only IBKR Paper Trading connection smoke test.")
    parser.add_argument("--host", default=os.getenv("IBKR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=_env_int("IBKR_PORT", 7497))
    parser.add_argument("--client-id", type=int, default=_env_int("IBKR_CLIENT_ID", 17))
    parser.add_argument("--stock", default="", help="Optional comma-separated stock symbols, e.g. AAPL,MSFT,NVDA")
    parser.add_argument("--fx", default="", help="Optional FX pair snapshot, e.g. USDJPY")
    args = parser.parse_args()

    adapter = IBKRAdapter(host=args.host, port=args.port, client_id=args.client_id)
    try:
        adapter.connect()
        payload: Dict[str, Any] = {
            "connected": adapter.is_connected(),
            "host": args.host,
            "port": args.port,
            "client_id": args.client_id,
            "account_summary": adapter.get_account_summary(),
        }
        if args.stock:
            symbols = [s.strip().upper() for s in args.stock.split(",") if s.strip()]
            payload["stock_snapshots"] = adapter.get_stock_snapshots(symbols)
        if args.fx:
            payload["fx_snapshot"] = adapter.get_fx_snapshot(args.fx)
        payload["positions"] = adapter.get_positions()
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    finally:
        adapter.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
