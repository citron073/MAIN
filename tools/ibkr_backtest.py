#!/usr/bin/env python3
"""米株デイトレ・バックテスト: SMAクロス・シグナル上で「固定SL」と「ATRベースSL」を比較し、
B案(ATR-SL/P1対策)が有効かを検証する。bot の実関数(_compute_sma_signal/_compute_atr)を流用。

各エントリーを2構成でシミュレートして勝率・期待値・MAE/MFEを比較:
  - 現行  : 固定SL=-0.5% / 固定TP=+1.0%
  - B案   : SL=-(ATR%×sl_mult) / TP=+(ATR%×sl_mult×rr)  ← R:R維持。ATRがノイズより広い分だけ早狩り回避

最重要指標: 「現行SLで損切りされたが、B案SLなら生存(=同区間でTP到達 or タイムアウトでプラス)した数」。

Usage:
    python3 tools/ibkr_backtest.py [--data-dir data/us_stocks] [--bar-min 5] \
        [--fast 5] [--slow 20] [--fixed-sl 0.5] [--fixed-tp 1.0] \
        [--sl-mult 1.5] [--rr 2.0] [--max-hold 36] [--verbose]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import ibkr_bot as ib  # 実bot関数を流用(parity)


def _load_bars(path: Path):
    out = []
    for r in csv.DictReader(path.open()):
        try:
            out.append({
                "time": r["time"],
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
                "volume": float(r.get("volume") or 0),
            })
        except (ValueError, KeyError):
            continue
    return out


def _simulate_exit(bars, entry_idx, side, entry, sl_pct, tp_pct, max_hold):
    """entry_idx で約定後、SL/TP/タイムアウトのどれで出るかを bar の high/low で判定。
    返り値: (outcome, ret_pct, bars_held, mae_pct, mfe_pct)  outcome in {TP,SL,TIMEOUT}"""
    sl_frac = sl_pct / 100.0   # 負
    tp_frac = tp_pct / 100.0   # 正
    if side == "BUY":
        sl_px = entry * (1 + sl_frac)
        tp_px = entry * (1 + tp_frac)
    else:  # SELL(ショート)
        sl_px = entry * (1 - sl_frac)   # sl_frac負→上側
        tp_px = entry * (1 - tp_frac)   # 下側
    mae = 0.0
    mfe = 0.0
    end = min(entry_idx + max_hold, len(bars) - 1)
    for j in range(entry_idx + 1, end + 1):
        b = bars[j]
        if side == "BUY":
            fav = (b["high"] - entry) / entry * 100
            adv = (b["low"] - entry) / entry * 100
        else:
            fav = (entry - b["low"]) / entry * 100
            adv = (entry - b["high"]) / entry * 100
        mfe = max(mfe, fav)
        mae = min(mae, adv)
        # 同バーでSL/TP両touchはSL優先(保守)
        if side == "BUY":
            hit_sl = b["low"] <= sl_px
            hit_tp = b["high"] >= tp_px
        else:
            hit_sl = b["high"] >= sl_px
            hit_tp = b["low"] <= tp_px
        if hit_sl:
            return "SL", sl_pct, j - entry_idx, mae, mfe
        if hit_tp:
            return "TP", tp_pct, j - entry_idx, mae, mfe
    # タイムアウト: 最終bar close で決済
    last = bars[end]["close"]
    ret = (last - entry) / entry * 100 if side == "BUY" else (entry - last) / entry * 100
    return "TIMEOUT", round(ret, 4), end - entry_idx, mae, mfe


def _stats(trades, key):
    rets = [t[key]["ret"] for t in trades]
    wins = [r for r in rets if r > 0]
    n = len(rets)
    if n == 0:
        return None
    wr = len(wins) / n * 100
    exp = mean(rets)
    return {"n": n, "wr": wr, "exp": exp, "total": sum(rets)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/us_stocks")
    ap.add_argument("--bar-min", type=int, default=5)
    ap.add_argument("--fast", type=int, default=5)
    ap.add_argument("--slow", type=int, default=20)
    ap.add_argument("--fixed-sl", type=float, default=0.5, help="正の絶対値%")
    ap.add_argument("--fixed-tp", type=float, default=1.0)
    ap.add_argument("--sl-mult", type=float, default=1.5, help="ATR%×この倍率=B案SL幅")
    ap.add_argument("--rr", type=float, default=2.0, help="B案のR:R(TP=SL×rr)")
    ap.add_argument("--max-hold", type=int, default=36)
    ap.add_argument("--min-atr-pct", type=float, default=0.0, help="ATR%下限フィルタ")
    ap.add_argument("--date-from", default="", help="この日付(YYYY-MM-DD)以降のバーのみ")
    ap.add_argument("--date-to", default="", help="この日付(YYYY-MM-DD)以前のバーのみ")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    data_dir = ROOT / args.data_dir
    files = sorted(data_dir.glob("*.csv"))
    if not files:
        print(f"[bt] データ無し: {data_dir} (先に ibkr_fetch_history.py を実行)")
        return 1

    trades = []      # 各エントリーを両構成でシミュレート
    saved_by_atr = 0  # 現行SL負け→B案で非負け に転じた数
    for fp in files:
        sym = fp.stem.split("_")[0]
        bars = _load_bars(fp)
        if args.date_from or args.date_to:
            bars = [b for b in bars
                    if (not args.date_from or b["time"][:10] >= args.date_from)
                    and (not args.date_to or b["time"][:10] <= args.date_to)]
        if len(bars) < args.slow + 5:
            continue
        i = args.slow + 1
        while i < len(bars) - 1:
            window = bars[: i + 1]
            sig = ib._compute_sma_signal(window, args.fast, args.slow)
            if sig not in ("BUY", "SELL"):
                i += 1
                continue
            atr = ib._compute_atr(window, 14)
            entry = bars[i]["close"]
            if not atr or entry <= 0:
                i += 1
                continue
            atr_pct = atr / entry * 100
            if atr_pct < args.min_atr_pct:
                i += 1
                continue
            # 現行構成
            f_out, f_ret, f_hold, f_mae, f_mfe = _simulate_exit(
                bars, i, sig, entry, -args.fixed_sl, args.fixed_tp, args.max_hold)
            # B案構成(ATR-SL/R:R維持TP)
            b_sl = max(args.fixed_sl, args.sl_mult * atr_pct)  # 固定より狭くしない(only-widen)
            b_tp = b_sl * args.rr
            a_out, a_ret, a_hold, a_mae, a_mfe = _simulate_exit(
                bars, i, sig, entry, -b_sl, b_tp, args.max_hold)
            if f_ret <= 0 and a_ret > 0:
                saved_by_atr += 1
            trades.append({
                "sym": sym, "side": sig, "atr_pct": round(atr_pct, 3),
                "fixed": {"out": f_out, "ret": f_ret},
                "atr": {"out": a_out, "ret": a_ret, "sl": round(b_sl, 3), "tp": round(b_tp, 3)},
            })
            if args.verbose:
                print(f"{sym} {sig} atr%={atr_pct:.2f} | 現行 {f_out} {f_ret:+.3f}% | "
                      f"B案 {a_out} {a_ret:+.3f}% (SL-{b_sl:.2f}/TP+{b_tp:.2f})")
            # 同一トレードの多重計上を避け、保有期間ぶん進める
            i += max(f_hold, a_hold, 1)

    fs = _stats(trades, "fixed")
    as_ = _stats(trades, "atr")
    side_n = {"BUY": 0, "SELL": 0}
    for t in trades:
        side_n[t["side"]] = side_n.get(t["side"], 0) + 1

    print("=" * 64)
    print(f"米株バックテスト結果  銘柄={len(files)}  エントリー={len(trades)}  "
          f"(BUY={side_n['BUY']} SELL={side_n['SELL']})  足={args.bar_min}分")
    print(f"設定: SMA{args.fast}/{args.slow}  現行SL-{args.fixed_sl}/TP+{args.fixed_tp}  "
          f"B案 SL=ATR%×{args.sl_mult}(min-{args.fixed_sl}) TP=SL×{args.rr}  max_hold={args.max_hold}")
    print("-" * 64)
    if fs and as_:
        print(f"{'構成':<8}{'件数':>6}{'勝率%':>9}{'期待値%/trade':>15}{'累計%':>10}")
        print(f"{'現行固定':<8}{fs['n']:>6}{fs['wr']:>9.1f}{fs['exp']:>15.4f}{fs['total']:>10.2f}")
        print(f"{'B案ATR':<8}{as_['n']:>6}{as_['wr']:>9.1f}{as_['exp']:>15.4f}{as_['total']:>10.2f}")
        print("-" * 64)
        print(f"★ 現行SLで損切り→B案SLなら非負けに転じたトレード: {saved_by_atr}件 "
              f"({saved_by_atr/len(trades)*100:.1f}%)" if trades else "")
        d_exp = as_["exp"] - fs["exp"]
        print(f"★ 期待値の差(B案−現行): {d_exp:+.4f}%/trade  "
              f"→ {'B案が優位' if d_exp > 0 else 'B案は優位でない'}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
