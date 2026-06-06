#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from exchange.bitflyer_private import BitflyerPrivateClient
from tools.keychain_secret import read_pair_with_source, secret_provider


MAIN_DIR = ROOT
CONTROL_CSV = MAIN_DIR / "CONTROL.csv"


def print_secret_setup_hint(service: str, account_key: str, account_secret: str) -> None:
    provider = secret_provider()
    print(f"[HINT] secret provider={provider}")
    print("[HINT] You can use either Keychain(macOS) or ENV(cloud/Linux).")
    print("[HINT] ENV example:")
    print("  export OUROBOROS_SECRET_PROVIDER=ENV")
    print("  export OUROBOROS_BITFLYER_API_KEY='<BITFLYER_API_KEY>'")
    print("  export OUROBOROS_BITFLYER_API_SECRET='<BITFLYER_API_SECRET>'")
    if account_key:
        print(f"  # optional custom env var name for key: {account_key}")
    if account_secret:
        print(f"  # optional custom env var name for secret: {account_secret}")

    if sys.platform == "darwin":
        print("[HINT] macOS Keychain setup:")
        print(
            f"  security add-generic-password -U -s '{service}' -a '{account_key}' -w '<BITFLYER_API_KEY>'"
        )
        print(
            f"  security add-generic-password -U -s '{service}' -a '{account_secret}' -w '<BITFLYER_API_SECRET>'"
        )
        print("[HINT] Verify:")
        print(f"  security find-generic-password -s '{service}' -a '{account_key}' -w")
        print(f"  security find-generic-password -s '{service}' -a '{account_secret}' -w")


def load_control(path: Path) -> dict:
    out: dict = {}
    if not path.exists():
        return out
    import csv

    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            k = str(row[0]).strip()
            v = str(row[1]).strip()
            if not k or k.lower() == "key":
                continue
            out[k] = v
    return out


def get_public_ticker(product_code: str) -> dict:
    url = f"https://api.bitflyer.com/v1/ticker?product_code={product_code}"
    with urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="LIVE preflight check for bitFlyer")
    ap.add_argument("--product", default=None, help="product code (default from CONTROL.product_code or BTC_JPY)")
    args = ap.parse_args()

    ctrl = load_control(CONTROL_CSV)
    exchange_name = str(ctrl.get("exchange_name") or "bitflyer").strip().lower()
    product = args.product or ctrl.get("product_code") or "BTC_JPY"
    market_type = str(ctrl.get("market_type", "SPOT") or "SPOT").strip().upper()
    service = ctrl.get("keychain_service", "ouroboros.bitflyer")
    account_key = ctrl.get("keychain_account_key", "api_key")
    account_secret = ctrl.get("keychain_account_secret", "api_secret")

    print(f"[CHECK] exchange_name={exchange_name}")
    print(f"[CHECK] product_code={product}")
    print(f"[CHECK] market_type={market_type}")
    print(f"[CHECK] secret_provider={secret_provider()} (env OUROBOROS_SECRET_PROVIDER)")
    print(f"[CHECK] keychain service={service} account_key={account_key} account_secret={account_secret}")

    if exchange_name != "bitflyer":
        print(f"[FAIL] exchange_name={exchange_name} is not implemented in this preflight (bitflyer only).")
        return 5

    try:
        k, s, src = read_pair_with_source(service=service, account_key=account_key, account_secret=account_secret)
        print(f"[OK] secret read source={src}")
    except Exception as e:
        print(f"[FAIL] secret read failed: {e}")
        print_secret_setup_hint(service=service, account_key=account_key, account_secret=account_secret)
        return 2

    try:
        client = BitflyerPrivateClient(api_key=k, api_secret=s)
        perms = client.get_permissions()
        print(f"[OK] auth/getpermissions {perms}")
        required = {"sendchildorder", "cancelchildorder", "getchildorders"}
        if market_type in ("FX", "CFD", "LIGHTNING"):
            required.add("getcollateral")
        else:
            required.add("getbalance")
        # API returns full paths (e.g. /v1/me/sendchildorder). Normalize for stable checks.
        perm_raw = {str(x).strip() for x in perms}
        perm_norm = {p.rsplit("/", 1)[-1] for p in perm_raw if p}
        missing = sorted([x for x in required if x not in perm_norm and f"/v1/me/{x}" not in perm_raw])
        if missing:
            print(f"[WARN] missing permissions: {missing}")
        if market_type in ("FX", "CFD", "LIGHTNING"):
            cfd_jpy = client.get_collateral_jpy()
            print(f"[OK] auth/getcollateral collateral={cfd_jpy}")
        else:
            jpy = client.get_jpy_balance()
            print(f"[OK] auth/getbalance JPY={jpy}")
    except Exception as e:
        print(f"[FAIL] private api failed: {e}")
        print("[HINT] Check API key status/permissions and IP restriction on bitFlyer API settings.")
        return 3

    try:
        t = get_public_ticker(product)
        ltp = t.get("ltp")
        bid = t.get("best_bid")
        ask = t.get("best_ask")
        if ltp is None or bid is None or ask is None:
            raise RuntimeError(f"incomplete ticker: {t}")
        print(f"[OK] public ticker ltp={ltp} bid={bid} ask={ask}")
    except Exception as e:
        print(f"[FAIL] public ticker failed: {e}")
        return 4

    print("[OK] preflight completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
