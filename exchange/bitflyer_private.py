from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class BitflyerAPIError(RuntimeError):
    pass


class BitflyerPrivateClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        base_url: str = "https://api.bitflyer.com",
        timeout: int = 10,
    ) -> None:
        self.api_key = str(api_key).strip()
        self.api_secret = str(api_secret).strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = int(timeout)
        if not self.api_key or not self.api_secret:
            raise BitflyerAPIError("api_key/api_secret is empty")

    def _sign(self, timestamp: str, method: str, path: str, body: str) -> str:
        payload = f"{timestamp}{method.upper()}{path}{body}"
        return hmac.new(self.api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, Any]] = None,
    ) -> Any:
        q = f"?{urlencode(query)}" if query else ""
        url_path = f"{path}{q}"
        url = f"{self.base_url}{url_path}"
        body = json.dumps(payload, separators=(",", ":")) if payload is not None else ""
        # Match the official sample format (Date.now) with unix time in milliseconds.
        ts = str(int(time.time() * 1000))
        sign = self._sign(ts, method, url_path, body)
        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-SIGN": sign,
            "Content-Type": "application/json",
        }
        req = Request(url, data=body.encode("utf-8") if body else None, method=method.upper(), headers=headers)
        try:
            with urlopen(req, timeout=self.timeout) as r:
                raw = r.read().decode("utf-8")
        except HTTPError as e:
            try:
                err_raw = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_raw = ""
            detail = err_raw.strip() or str(e)
            raise BitflyerAPIError(f"HTTP {e.code}: {detail}") from e
        except Exception as e:
            raise BitflyerAPIError(str(e)) from e
        try:
            return json.loads(raw)
        except Exception:
            raise BitflyerAPIError(f"invalid json response: {raw[:300]}")

    def get_permissions(self) -> List[str]:
        resp = self._request("GET", "/v1/me/getpermissions")
        if isinstance(resp, list):
            return [str(x) for x in resp]
        raise BitflyerAPIError(f"get_permissions failed: {resp}")

    def send_child_order(
        self,
        *,
        product_code: str,
        side: str,
        size: float,
        child_order_type: str = "LIMIT",
        price: Optional[float] = None,
        minute_to_expire: int = 43200,
        time_in_force: str = "GTC",
    ) -> str:
        order_type = str(child_order_type).upper()
        payload: Dict[str, Any] = {
            "product_code": product_code,
            "child_order_type": order_type,
            "side": str(side).upper(),
            "size": float(size),
            "minute_to_expire": int(minute_to_expire),
            "time_in_force": str(time_in_force).upper(),
        }
        if order_type == "LIMIT":
            if price is None:
                raise BitflyerAPIError("price is required for LIMIT order")
            payload["price"] = float(price)
        resp = self._request("POST", "/v1/me/sendchildorder", payload=payload)
        oid = (resp or {}).get("child_order_acceptance_id")
        if not oid:
            raise BitflyerAPIError(f"send_child_order failed: {resp}")
        return str(oid)

    def get_child_orders(
        self,
        *,
        product_code: str,
        child_order_acceptance_id: Optional[str] = None,
        count: int = 20,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"product_code": product_code, "count": int(count)}
        if child_order_acceptance_id:
            query["child_order_acceptance_id"] = child_order_acceptance_id
        resp = self._request("GET", "/v1/me/getchildorders", query=query)
        if isinstance(resp, list):
            return [x for x in resp if isinstance(x, dict)]
        raise BitflyerAPIError(f"get_child_orders failed: {resp}")

    def cancel_child_order(self, *, product_code: str, child_order_acceptance_id: str) -> bool:
        payload = {
            "product_code": product_code,
            "child_order_acceptance_id": child_order_acceptance_id,
        }
        self._request("POST", "/v1/me/cancelchildorder", payload=payload)
        return True

    def get_balance(self) -> List[Dict[str, Any]]:
        resp = self._request("GET", "/v1/me/getbalance")
        if isinstance(resp, list):
            return [x for x in resp if isinstance(x, dict)]
        raise BitflyerAPIError(f"get_balance failed: {resp}")

    def get_jpy_balance(self) -> float:
        bal = self.get_balance()
        for row in bal:
            if str(row.get("currency_code", "")).upper() != "JPY":
                continue
            amt = row.get("amount")
            try:
                return float(amt)
            except Exception:
                continue
        raise BitflyerAPIError("JPY balance not found")


def summarize_order(orders: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not orders:
        return {"state": "UNKNOWN", "executed_size": 0.0, "average_price": None}
    o = orders[0]
    state = str(o.get("child_order_state", "UNKNOWN"))
    executed_size = 0.0
    average_price = None
    try:
        executed_size = float(o.get("executed_size") or 0.0)
    except Exception:
        executed_size = 0.0
    try:
        average_price = float(o.get("average_price")) if o.get("average_price") is not None else None
    except Exception:
        average_price = None
    return {"state": state, "executed_size": executed_size, "average_price": average_price}
