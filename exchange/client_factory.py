from __future__ import annotations

from typing import Any

from exchange.bitflyer_private import BitflyerPrivateClient


def normalize_exchange_name(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if not s:
        return "bitflyer"
    if s in ("bitflyer", "bit_flyer", "bf"):
        return "bitflyer"
    if s in ("binance", "bn"):
        return "binance"
    return s


def build_private_client(
    *,
    exchange_name: Any,
    api_key: str,
    api_secret: str,
    bitflyer_base_url: str = "https://api.bitflyer.com",
) -> Any:
    ex = normalize_exchange_name(exchange_name)
    if ex == "bitflyer":
        return BitflyerPrivateClient(
            api_key=api_key,
            api_secret=api_secret,
            base_url=bitflyer_base_url,
        )
    if ex == "binance":
        raise NotImplementedError("exchange_name=binance is not implemented yet")
    raise ValueError(f"unsupported exchange_name: {ex}")
