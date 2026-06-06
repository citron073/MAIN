#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from exchange.bitflyer_private import BitflyerAPIError, BitflyerPrivateClient  # noqa: E402
from tools.keychain_secret import read_pair_with_source, secret_provider  # noqa: E402


CONTROL_CSV = ROOT / "CONTROL.csv"


def load_control(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            k = str(row[0]).strip()
            v = str(row[1]).strip()
            if not k or k.lower() == "key":
                continue
            out[k] = v
    return out


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(str(x).strip())
    except Exception:
        return float(default)


def get_public_ticker(product_code: str) -> Dict[str, Any]:
    url = f"https://api.bitflyer.com/v1/ticker?product_code={product_code}"
    with urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def calc_marketable_limit(side: str, best_bid: float, best_ask: float, slippage_bps: float) -> int:
    bps = max(1.0, float(slippage_bps))
    side_u = str(side).upper()
    if side_u == "BUY":
        px = best_ask * (1.0 + bps / 10000.0)
        return int(math.ceil(px))
    px = best_bid * (1.0 - bps / 10000.0)
    return int(max(1, math.floor(px)))


def opposite_side(side: str) -> str:
    return "SELL" if str(side).upper() == "BUY" else "BUY"


def summarize_orders(orders: List[Dict[str, Any]]) -> Tuple[float, Optional[float], str]:
    if not orders:
        return 0.0, None, "UNKNOWN"
    o = orders[0]
    filled = safe_float(o.get("executed_size"), 0.0)
    avg = o.get("average_price")
    avg_f = safe_float(avg, 0.0) if avg is not None else None
    state = str(o.get("child_order_state", "UNKNOWN"))
    return filled, avg_f, state


def wait_order_result(
    client: BitflyerPrivateClient,
    *,
    product_code: str,
    acceptance_id: str,
    timeout_sec: float,
    poll_sec: float,
) -> Tuple[float, Optional[float], str]:
    end_ts = time.time() + max(1.0, float(timeout_sec))
    latest_filled = 0.0
    latest_avg: Optional[float] = None
    latest_state = "UNKNOWN"
    while time.time() < end_ts:
        orders = client.get_child_orders(
            product_code=product_code,
            child_order_acceptance_id=acceptance_id,
            count=1,
        )
        filled, avg, state = summarize_orders(orders)
        latest_filled, latest_avg, latest_state = filled, avg, state
        if state in ("COMPLETED", "CANCELED", "EXPIRED", "REJECTED"):
            break
        time.sleep(max(0.2, float(poll_sec)))
    return latest_filled, latest_avg, latest_state


def net_position_btc(client: BitflyerPrivateClient, product_code: str) -> float:
    rows = client.get_positions(product_code=product_code)
    net = 0.0
    for r in rows:
        side = str(r.get("side", "")).upper()
        sz = safe_float(r.get("size"), 0.0)
        if side == "BUY":
            net += sz
        elif side == "SELL":
            net -= sz
    return net


def main() -> int:
    ap = argparse.ArgumentParser(description="Live smoke test: small round-trip by LIMIT IOC on bitFlyer")
    ap.add_argument("--execute", action="store_true", help="actually place real orders")
    ap.add_argument("--product", default=None)
    ap.add_argument("--size", type=float, default=None, help="BTC size (default: canary_lot or 0.001)")
    ap.add_argument("--entry-side", choices=["BUY", "SELL"], default="BUY")
    ap.add_argument("--slippage-bps", type=float, default=5.0, help="marketable limit buffer in bps")
    ap.add_argument("--timeout-sec", type=float, default=20.0)
    ap.add_argument("--poll-sec", type=float, default=1.0)
    ap.add_argument("--allow-open-position", action="store_true")
    args = ap.parse_args()

    ctrl = load_control(CONTROL_CSV)
    product = str(args.product or ctrl.get("product_code") or "FX_BTC_JPY").strip()
    market_type = str(ctrl.get("market_type", "FX") or "FX").strip().upper()
    service = str(ctrl.get("keychain_service", "ouroboros.bitflyer")).strip()
    account_key = str(ctrl.get("keychain_account_key", "api_key")).strip()
    account_secret = str(ctrl.get("keychain_account_secret", "api_secret")).strip()
    size_default = safe_float(ctrl.get("canary_lot"), 0.001)
    if size_default <= 0:
        size_default = 0.001
    size = float(args.size if args.size is not None else size_default)
    fx_leverage = max(0.1, safe_float(ctrl.get("fx_leverage"), 1.0))

    print(f"[CHECK] market_type={market_type} product={product}")
    print(f"[CHECK] size={size:.6f} entry_side={args.entry_side} slippage_bps={args.slippage_bps}")
    print("[CHECK] mode=LIVE real order smoke test")
    print(f"[CHECK] secret_provider={secret_provider()} (env OUROBOROS_SECRET_PROVIDER)")
    print(f"[CHECK] keychain service={service} account_key={account_key} account_secret={account_secret}")

    k, s, src = read_pair_with_source(service=service, account_key=account_key, account_secret=account_secret)
    print(f"[OK] secret read source={src}")
    client = BitflyerPrivateClient(api_key=k, api_secret=s)

    if not args.allow_open_position and market_type in ("FX", "CFD", "LIGHTNING"):
        net0 = net_position_btc(client, product)
        print(f"[CHECK] net_position_before={net0:.8f} BTC")
        if abs(net0) > 1e-10:
            print("[ABORT] open position exists. close it first, or re-run with --allow-open-position.")
            return 4

    t0 = get_public_ticker(product)
    bid0 = safe_float(t0.get("best_bid"), 0.0)
    ask0 = safe_float(t0.get("best_ask"), 0.0)
    if bid0 <= 0 or ask0 <= 0:
        print(f"[ABORT] invalid ticker: {t0}")
        return 5

    side_entry = str(args.entry_side).upper()
    px_entry = calc_marketable_limit(side_entry, bid0, ask0, args.slippage_bps)
    side_exit = opposite_side(side_entry)

    if market_type in ("FX", "CFD", "LIGHTNING"):
        collateral = client.get_collateral_jpy()
        est_required = (float(px_entry) * float(size)) / float(fx_leverage)
        print(
            f"[CHECK] collateral={collateral:.2f} est_required={est_required:.2f} "
            f"(fx_leverage={fx_leverage:.2f})"
        )
        if collateral + 1e-9 < est_required:
            short = est_required - collateral
            msg = (
                f"estimated collateral is insufficient by about {short:.2f} JPY "
                f"for size={size:.6f}."
            )
            if args.execute:
                print(f"[ABORT] {msg}")
                print("[HINT] 入金するか size を下げてください（ただし最小発注数量制約あり）。")
                return 11
            print(f"[WARN] {msg}")

    plan = {
        "product": product,
        "size": size,
        "entry_side": side_entry,
        "entry_limit_price": px_entry,
        "exit_side": side_exit,
        "time_in_force": "IOC",
        "timeout_sec": args.timeout_sec,
    }
    print("[PLAN]", json.dumps(plan, ensure_ascii=False))

    if not args.execute:
        print("[DRYRUN] no real orders sent. add --execute to run.")
        return 0

    def _print_order_error(prefix: str, err: Exception) -> None:
        msg = str(err)
        print(f"[FAIL] {prefix} rejected: {msg}")
        lmsg = msg.lower()
        if "minimum order size" in lmsg:
            print("[HINT] lot/canary_lot を最小数量以上に設定してください。")
        if "margin amount is insufficient" in lmsg:
            print("[HINT] 証拠金不足です。入金するか、レバレッジ/銘柄/数量設定を見直してください。")

    # ENTRY
    print("[LIVE] sending ENTRY...")
    try:
        entry_oid = client.send_child_order(
            product_code=product,
            side=side_entry,
            size=size,
            child_order_type="LIMIT",
            price=px_entry,
            minute_to_expire=1,
            time_in_force="IOC",
        )
    except BitflyerAPIError as e:
        _print_order_error("ENTRY", e)
        return 8
    e_filled, e_avg, e_state = wait_order_result(
        client,
        product_code=product,
        acceptance_id=entry_oid,
        timeout_sec=args.timeout_sec,
        poll_sec=args.poll_sec,
    )
    print(f"[LIVE] ENTRY oid={entry_oid} state={e_state} filled={e_filled:.8f} avg={e_avg}")
    if e_filled <= 0:
        print("[ABORT] entry not filled. stop here.")
        return 6

    # EXIT
    t1 = get_public_ticker(product)
    bid1 = safe_float(t1.get("best_bid"), bid0)
    ask1 = safe_float(t1.get("best_ask"), ask0)
    px_exit = calc_marketable_limit(side_exit, bid1, ask1, args.slippage_bps)

    print("[LIVE] sending EXIT...")
    try:
        exit_oid = client.send_child_order(
            product_code=product,
            side=side_exit,
            size=e_filled,
            child_order_type="LIMIT",
            price=px_exit,
            minute_to_expire=1,
            time_in_force="IOC",
        )
    except BitflyerAPIError as e:
        _print_order_error("EXIT", e)
        return 9
    x_filled, x_avg, x_state = wait_order_result(
        client,
        product_code=product,
        acceptance_id=exit_oid,
        timeout_sec=args.timeout_sec,
        poll_sec=args.poll_sec,
    )
    print(f"[LIVE] EXIT oid={exit_oid} state={x_state} filled={x_filled:.8f} avg={x_avg}")

    rem = max(0.0, e_filled - x_filled)
    if rem > 1e-10:
        # one emergency close retry with more aggressive limit
        t2 = get_public_ticker(product)
        bid2 = safe_float(t2.get("best_bid"), bid1)
        ask2 = safe_float(t2.get("best_ask"), ask1)
        px_retry = calc_marketable_limit(side_exit, bid2, ask2, max(20.0, args.slippage_bps))
        print(f"[LIVE] EXIT retry rem={rem:.8f} px={px_retry}")
        try:
            retry_oid = client.send_child_order(
                product_code=product,
                side=side_exit,
                size=rem,
                child_order_type="LIMIT",
                price=px_retry,
                minute_to_expire=1,
                time_in_force="IOC",
            )
        except BitflyerAPIError as e:
            _print_order_error("EXIT retry", e)
            return 10
        r_filled, r_avg, r_state = wait_order_result(
            client,
            product_code=product,
            acceptance_id=retry_oid,
            timeout_sec=args.timeout_sec,
            poll_sec=args.poll_sec,
        )
        print(f"[LIVE] EXIT retry oid={retry_oid} state={r_state} filled={r_filled:.8f} avg={r_avg}")
        x_filled += r_filled
        if x_avg is None and r_avg is not None:
            x_avg = r_avg
        rem = max(0.0, e_filled - x_filled)

    side_sign = 1.0 if side_entry == "BUY" else -1.0
    pnl_jpy = None
    if e_avg is not None and x_avg is not None:
        pnl_jpy = (float(x_avg) - float(e_avg)) * float(e_filled) * side_sign

    net_after = None
    if market_type in ("FX", "CFD", "LIGHTNING"):
        net_after = net_position_btc(client, product)

    print(
        "[RESULT]",
        json.dumps(
            {
                "entry_filled": round(e_filled, 8),
                "entry_avg": e_avg,
                "exit_filled": round(x_filled, 8),
                "exit_avg": x_avg,
                "remaining_size": round(rem, 8),
                "pnl_jpy_est": None if pnl_jpy is None else round(float(pnl_jpy), 2),
                "net_position_after": None if net_after is None else round(float(net_after), 8),
                "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
        ),
    )

    if rem > 1e-10:
        print("[WARN] remaining position exists. check positions immediately.")
        return 7
    print("[OK] round-trip smoke test completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
