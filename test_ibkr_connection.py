from __future__ import annotations

import csv
import json
import socket
import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ibkr_adapter import IBKRAdapter, IBKRDependencyError, enrich_positions_pnl


ROOT = Path(__file__).resolve().parent
DEFAULT_STOCK_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "QQQ", "SPY"]
DEFAULT_CLIENT_ID_CANDIDATES = "1,17,101"


def _read_ibkr_port_from_control() -> int:
    """Read ibkr_port from IBKR_CONTROL.csv, falling back to 7497 if not found."""
    control_path = ROOT / "IBKR_CONTROL.csv"
    try:
        for row in csv.DictReader(open(control_path, encoding="utf-8-sig")):
            k = str(row.get("key", "") or "").strip()
            if k == "ibkr_port":
                return int(str(row.get("value", "7497")).strip())
    except Exception:
        pass
    return 7497


def _now_jst_naive() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


def _write_success_log(payload: Dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    day8 = _now_jst_naive().strftime("%Y%m%d")
    path = out_dir / f"ibkr_connection_{day8}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
    path.write_text(text, encoding="utf-8")
    (out_dir / "ibkr_connection_latest.json").write_text(text, encoding="utf-8")
    return path


def _write_failure_log(payload: Dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    day8 = _now_jst_naive().strftime("%Y%m%d")
    path = out_dir / f"ibkr_connection_error_{day8}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
    path.write_text(text, encoding="utf-8")
    (out_dir / "ibkr_connection_error_latest.json").write_text(text, encoding="utf-8")
    return path


def _probe_tcp_port(host: str, port: int, timeout_sec: float = 1.0) -> Dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return {"host": host, "port": port, "open": True, "error": ""}
    except OSError as exc:
        return {
            "host": host,
            "port": port,
            "open": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _ibkr_timeout_checklist(host: str, port: int, client_id: int) -> List[str]:
    return [
        "IB Gateway が Paper Trading でログイン済みか確認（TWSより常駐向き）",
        f"API Socket Port が {port} で、127.0.0.1 から接続許可されているか確認",
        "Enable ActiveX and Socket Clients がONか確認",
        "Read-Only API がONか確認",
        f"同じ clientId={client_id} を他プロセスが使用していないか確認",
        "API接続ダイアログが出ている場合は承認",
        "必要なら IB Gateway を再起動して再実行",
        f"再実行: python3 test_ibkr_connection.py --host {host} --port {port} --client-id {client_id} --stocks AAPL,MSFT,NVDA,TSLA,QQQ,SPY --fx USDJPY",
    ]


def _parse_client_id_candidates(raw: str, primary: int) -> List[int]:
    out: List[int] = []
    for value in [str(primary), *str(raw or "").split(",")]:
        value = value.strip()
        if not value:
            continue
        try:
            client_id = int(value)
        except ValueError:
            continue
        if client_id not in out:
            out.append(client_id)
    return out


def _diagnose_client_ids(
    host: str,
    port: int,
    client_ids: List[int],
    market_data_type: str,
    timeout_sec: float,
    *,
    skip_client_id: int | None = None,
) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    first_ok: int | None = None
    for client_id in client_ids:
        if skip_client_id is not None and client_id == skip_client_id:
            continue
        adapter = IBKRAdapter(
            host=host,
            port=port,
            client_id=client_id,
            market_data_type=market_data_type,
            timeout_sec=timeout_sec,
        )
        try:
            connected = bool(adapter.connect())
            attempts.append(
                {
                    "client_id": client_id,
                    "connected": connected,
                    "diagnosis": "OK" if connected else "connect returned false",
                    "detail": "",
                }
            )
            if connected and first_ok is None:
                first_ok = client_id
        except Exception as exc:
            attempts.append(
                {
                    "client_id": client_id,
                    "connected": False,
                    "diagnosis": _diagnose_connect_error(exc, host, port),
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )
        finally:
            adapter.disconnect()
    recommendation = (
        f"clientId={first_ok} で接続可能です。IBKR_CLIENT_ID={first_ok} を検討してください。"
        if first_ok is not None
        else "候補clientIdでも接続できません。IB Gateway側のAPI許可・Read-Only・接続承認を確認してください。"
    )
    return {
        "candidates": client_ids,
        "attempts": attempts,
        "first_ok_client_id": first_ok,
        "recommendation": recommendation,
    }


def _diagnose_connect_error(exc: Exception, host: str, port: int) -> str:
    if isinstance(exc, IBKRDependencyError):
        return "ib_insync が未インストールです。python3 -m pip install ib_insync を実行してください。"
    if isinstance(exc, ConnectionRefusedError):
        return f"{host}:{port} が待ち受けていません。IB Gateway Paperを起動し、API Socket Port 7497 と Read-Only API を確認してください。"
    if isinstance(exc, PermissionError):
        return "ローカル接続が実行環境に拒否されました。Codexの承認付き実行、または通常のターミナルから再実行してください。"
    if (
        isinstance(exc, TimeoutError)
        or type(exc).__name__ == "TimeoutError"
        or "timed out" in str(exc).lower()
    ):
        return f"{host}:{port} は開いている可能性がありますが、IBKR API応答がタイムアウトしました。IB Gateway側のAPI許可・Read-Only・clientId競合を確認してください。"
    if isinstance(exc, socket.timeout):
        return f"{host}:{port} への接続がタイムアウトしました。IB GatewayのAPI設定と許可IPを確認してください。"
    return f"{type(exc).__name__}: {exc}"


def main():
    ap = argparse.ArgumentParser(description="Read-only IBKR Paper Trading communication test.")
    _default_port = int(os.getenv("IBKR_PORT", "0")) or _read_ibkr_port_from_control()
    ap.add_argument("--host", default=os.getenv("IBKR_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=_default_port)
    ap.add_argument("--client-id", type=int, default=int(os.getenv("IBKR_CLIENT_ID", "1")))
    ap.add_argument("--client-id-candidates", default=os.getenv("IBKR_CLIENT_ID_CANDIDATES", DEFAULT_CLIENT_ID_CANDIDATES),
                    help="Comma-separated read-only clientIds to try after a connection failure.")
    ap.add_argument("--diagnostic-timeout-sec", type=float, default=float(os.getenv("IBKR_DIAGNOSTIC_TIMEOUT_SEC", "6.0")))
    ap.add_argument("--skip-client-id-diagnostics", action="store_true",
                    help="Do not try alternative read-only clientIds after a connection failure.")
    ap.add_argument("--stocks", default=",".join(DEFAULT_STOCK_SYMBOLS), help="Comma-separated symbols.")
    ap.add_argument("--fx", default="USDJPY")
    ap.add_argument("--market-data-type", default="delayed",
                    choices=["live", "frozen", "delayed", "delayed_frozen"],
                    help="IBKR market data type (default: delayed)")
    ap.add_argument("--out-dir", default=str(ROOT / "review_out"))
    args = ap.parse_args()

    host = args.host
    port = args.port
    client_id = args.client_id
    mdt = args.market_data_type
    symbols: List[str] = [s.strip().upper() for s in args.stocks.split(",") if s.strip()]
    adapter = IBKRAdapter(host=host, port=port, client_id=client_id, market_data_type=mdt)
    port_status = _probe_tcp_port(host, port)

    # Connection failure is a hard stop — everything else is best-effort
    try:
        adapter.connect()
    except Exception as exc:
        diagnosis = _diagnose_connect_error(exc, host, port)
        checklist = _ibkr_timeout_checklist(host, port, client_id)
        client_id_diagnostics = {"attempts": [], "recommendation": "skipped"}
        if not args.skip_client_id_diagnostics and port_status.get("open"):
            client_ids = _parse_client_id_candidates(args.client_id_candidates, client_id)
            client_id_diagnostics = _diagnose_client_ids(
                host,
                port,
                client_ids,
                mdt,
                args.diagnostic_timeout_sec,
                skip_client_id=client_id,
            )
        payload = {
            "generated_at_jst": _now_jst_naive().strftime("%Y-%m-%d %H:%M:%S"),
            "host": host,
            "port": port,
            "client_id": client_id,
            "connected": False,
            "readonly": True,
            "market_data_mode": mdt,
            "stage": "connect",
            "diagnosis": diagnosis,
            "detail": f"{type(exc).__name__}: {exc}",
            "port_status": port_status,
            "client_id_diagnostics": client_id_diagnostics,
            "checklist": checklist,
        }
        out_path = _write_failure_log(payload, Path(args.out_dir))
        print("IBKR connection test failed")
        print("diagnosis:", diagnosis)
        print("port_status:", "OPEN" if port_status.get("open") else "CLOSED", port_status.get("error", ""))
        if client_id_diagnostics.get("attempts"):
            print("client_id_diagnostics:")
            for item in client_id_diagnostics["attempts"]:
                print(
                    "- clientId={client_id} connected={connected} diagnosis={diagnosis}".format(
                        **item
                    )
                )
            print("client_id_recommendation:", client_id_diagnostics.get("recommendation", ""))
        print("checklist:")
        for item in checklist:
            print("-", item)
        print("detail:", f"{type(exc).__name__}: {exc}")
        print("saved_error:", out_path)
        adapter.disconnect()
        return 1

    print("connected:", adapter.is_connected())
    errors: List[str] = []

    try:
        account_summary = adapter.get_account_summary()
        print("account_summary: OK")
    except Exception as exc:
        account_summary = {}
        errors.append(f"account_summary: {type(exc).__name__}: {exc}")
        print(f"account_summary: ERROR — {exc}")

    try:
        stock_snapshots = adapter.get_stock_snapshots(symbols)
        for sym, snap in stock_snapshots.items():
            mds = snap.get("market_data_status", "?")
            print(f"  {sym}: {mds}")
    except Exception as exc:
        stock_snapshots = {}
        errors.append(f"stock_snapshots: {type(exc).__name__}: {exc}")
        print(f"stock_snapshots: ERROR — {exc}")

    try:
        fx_snapshot = adapter.get_fx_snapshot(args.fx)
        mds = fx_snapshot.get("market_data_status", "?")
        close = fx_snapshot.get("close")
        print(f"fx_snapshot_{args.fx}: {mds}  close={close}")
    except Exception as exc:
        fx_snapshot = {"instrument": "fx", "symbol": args.fx,
                       "market_data_status": "ERROR", "price_available": False,
                       "error_message": f"{type(exc).__name__}: {exc}"}
        errors.append(f"fx_snapshot_{args.fx}: {type(exc).__name__}: {exc}")
        print(f"fx_snapshot_{args.fx}: ERROR — {exc}")

    try:
        positions = adapter.get_positions()
        print(f"positions: {len(positions)} item(s)")
    except Exception as exc:
        positions = []
        errors.append(f"positions: {type(exc).__name__}: {exc}")
        print(f"positions: ERROR — {exc}")

    adapter.disconnect()
    print("disconnected")

    _fx_mp = fx_snapshot.get("market_price") or fx_snapshot.get("last") or fx_snapshot.get("bid") or fx_snapshot.get("reference_price") or fx_snapshot.get("close")
    try:
        _fx_rate: Optional[float] = float(_fx_mp) if _fx_mp is not None and float(_fx_mp) > 0 else None
    except (TypeError, ValueError):
        _fx_rate = None
    positions = enrich_positions_pnl(positions, stock_snapshots, fx_rate=_fx_rate)

    payload = {
        "generated_at_jst": _now_jst_naive().strftime("%Y-%m-%d %H:%M:%S"),
        "host": host,
        "port": port,
        "client_id": client_id,
        "connected": True,
        "readonly": True,
        "market_data_mode": mdt,
        "account_summary": account_summary,
        "stock_symbols": symbols,
        "stock_snapshots": stock_snapshots,
        "stock_snapshot_AAPL": stock_snapshots.get("AAPL"),
        "fx_pair": args.fx,
        "fx_snapshot_USDJPY": fx_snapshot,
        "positions": positions,
        "errors": errors,
    }
    out_path = _write_success_log(payload, Path(args.out_dir))
    print("saved:", out_path)
    if errors:
        print(f"注意: {len(errors)} 件の部分エラーあり（接続・口座情報は正常保存済み）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
