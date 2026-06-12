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


def _simulate_exit_trailing(bars, entry_idx, side, entry, sl_pct, ch_n, max_hold):
    """タートル式トレーリング出口: 初期ハードSL(ATR由来)と、Nバー逆側極値のトレーリングチャネルの
    タイトな方をストップとして追従。TPキャップなし=勝ちを伸ばす。outcome in {TRAIL,SL,TIMEOUT}"""
    sl_frac = sl_pct / 100.0  # 負
    hard = entry * (1 + sl_frac) if side == "BUY" else entry * (1 - sl_frac)
    mae = 0.0
    mfe = 0.0
    end = min(entry_idx + max_hold, len(bars) - 1)
    for j in range(entry_idx + 1, end + 1):
        b = bars[j]
        prior = bars[max(0, j - ch_n): j]
        if side == "BUY":
            ch = min(p["low"] for p in prior)
            stop = max(hard, ch)
            fav = (b["high"] - entry) / entry * 100
            adv = (b["low"] - entry) / entry * 100
        else:
            ch = max(p["high"] for p in prior)
            stop = min(hard, ch)
            fav = (entry - b["low"]) / entry * 100
            adv = (entry - b["high"]) / entry * 100
        mfe = max(mfe, fav)
        mae = min(mae, adv)
        if side == "BUY" and b["low"] <= stop:
            px = b["open"] if b["open"] < stop else stop  # 窓開けはopen約定(保守)
            return ("TRAIL" if stop > hard else "SL"), round((px - entry) / entry * 100, 4), j - entry_idx, mae, mfe
        if side == "SELL" and b["high"] >= stop:
            px = b["open"] if b["open"] > stop else stop
            return ("TRAIL" if stop < hard else "SL"), round((entry - px) / entry * 100, 4), j - entry_idx, mae, mfe
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


def _risk_stats(trades, key):
    """時系列順の等ウェイト%累積でリスク指標を計測: 最大DD(%pt)・最大連敗・最長アンダーウォーター期間(取引数)"""
    seq = sorted(trades, key=lambda t: t["time"])
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    streak = 0
    max_streak = 0
    uw = 0
    max_uw = 0
    for t in seq:
        r = t[key]["ret"]
        cum += r
        if cum > peak:
            peak = cum
            uw = 0
        else:
            uw += 1
            max_uw = max(max_uw, uw)
        max_dd = max(max_dd, peak - cum)
        if r <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return {"max_dd": max_dd, "max_streak": max_streak, "max_uw": max_uw}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/us_stocks")
    ap.add_argument("--bar-min", type=int, default=5)
    ap.add_argument("--strategy", choices=["sma", "donchian"], default="sma",
                    help="エントリー信号: sma=SMAクロス(既定) / donchian=ドンチャン・ブレイクアウト(タートルズ型)")
    ap.add_argument("--donchian-n", type=int, default=20,
                    help="ドンチャン: 直近Nバーの高値/安値ブレイクでエントリー(タートルズは日足20)")
    ap.add_argument("--fast", type=int, default=5)
    ap.add_argument("--slow", type=int, default=20)
    ap.add_argument("--fixed-sl", type=float, default=0.5, help="正の絶対値%")
    ap.add_argument("--fixed-tp", type=float, default=1.0)
    ap.add_argument("--sl-mult", type=float, default=1.5, help="ATR%×この倍率=B案SL幅")
    ap.add_argument("--rr", type=float, default=2.0, help="B案のR:R(TP=SL×rr)")
    ap.add_argument("--max-hold", type=int, default=36)
    ap.add_argument("--min-atr-pct", type=float, default=0.0, help="ATR%下限フィルタ")
    ap.add_argument("--trend-ma", type=int, default=0,
                    help="上位足トレンド整合フィルタ: NバーMAに対しBUY=close>MA&MA上昇/SELL=close<MA&MA下降 のみ(0=無効)")
    ap.add_argument("--entry-hour-from", type=int, default=-1,
                    help="エントリーを許可する時刻下限(データのタイムスタンプ時。-1=無効)")
    ap.add_argument("--entry-hour-to", type=int, default=-1,
                    help="エントリーを許可する時刻上限(この時を含む。-1=無効)")
    ap.add_argument("--date-from", default="", help="この日付(YYYY-MM-DD)以降のバーのみ")
    ap.add_argument("--date-to", default="", help="この日付(YYYY-MM-DD)以前のバーのみ")
    ap.add_argument("--exit-channel-n", type=int, default=0,
                    help="トレーリング出口(タートル式): 直近Nバー逆側ブレイクで決済。>0でB案レグのTPを廃止しトレーリング+初期ATR-SLに置換")
    ap.add_argument("--cost-rt-pct", type=float, default=0.0,
                    help="往復コスト%%(スプレッド+手数料+スリッページ合算)。全トレードのretから控除しネット成績を出す")
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
        # 窓を計算に必要な分だけに限定(全履歴スライスはO(n^2)で52万本級が終わらない)
        lookback = max(args.slow + 2, args.trend_ma + 1, 60)
        i = args.slow + 1
        while i < len(bars) - 1:
            if args.entry_hour_from >= 0 and args.entry_hour_to >= 0:
                hh = int(bars[i]["time"][11:13])
                if not (args.entry_hour_from <= hh <= args.entry_hour_to):
                    i += 1
                    continue
            window = bars[max(0, i - lookback): i + 1]
            if args.strategy == "donchian":
                # ドンチャン: 現バーcloseが直近Nバー(現バー除く)の高値超え=BUY/安値割れ=SELL
                n = args.donchian_n
                if i < n + 1:
                    i += 1
                    continue
                prior = bars[i - n: i]
                ch_hi = max(b["high"] for b in prior)
                ch_lo = min(b["low"] for b in prior)
                c = bars[i]["close"]
                sig = "BUY" if c > ch_hi else ("SELL" if c < ch_lo else None)
            else:
                sig = ib._compute_sma_signal(window, args.fast, args.slow)
            if sig not in ("BUY", "SELL"):
                i += 1
                continue
            # 上位足トレンド整合フィルタ(P2 regime候補): 長期MA方向に逆らうシグナルを除外
            if args.trend_ma > 0:
                closes = [b["close"] for b in window]
                if len(closes) < args.trend_ma + 1:
                    i += 1
                    continue
                ma_now = sum(closes[-args.trend_ma:]) / args.trend_ma
                ma_prev = sum(closes[-args.trend_ma - 1:-1]) / args.trend_ma
                px = closes[-1]
                up = px > ma_now and ma_now > ma_prev
                dn = px < ma_now and ma_now < ma_prev
                if (sig == "BUY" and not up) or (sig == "SELL" and not dn):
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
            if args.exit_channel_n > 0:
                a_out, a_ret, a_hold, a_mae, a_mfe = _simulate_exit_trailing(
                    bars, i, sig, entry, -b_sl, args.exit_channel_n, args.max_hold)
            else:
                a_out, a_ret, a_hold, a_mae, a_mfe = _simulate_exit(
                    bars, i, sig, entry, -b_sl, b_tp, args.max_hold)
            if f_ret <= 0 and a_ret > 0:
                saved_by_atr += 1
            trades.append({
                "sym": sym, "side": sig, "time": bars[i]["time"], "atr_pct": round(atr_pct, 3),
                "fixed": {"out": f_out, "ret": round(f_ret - args.cost_rt_pct, 4)},
                "atr": {"out": a_out, "ret": round(a_ret - args.cost_rt_pct, 4), "sl": round(b_sl, 3), "tp": round(b_tp, 3)},
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
    strat = f"Donchian{args.donchian_n}" if args.strategy == "donchian" else f"SMA{args.fast}/{args.slow}"
    print(f"設定: {strat}  現行SL-{args.fixed_sl}/TP+{args.fixed_tp}  往復コスト={args.cost_rt_pct}%  "
          f"B案 SL=ATR%×{args.sl_mult}(min-{args.fixed_sl}) TP=SL×{args.rr}  max_hold={args.max_hold}")
    print("-" * 64)
    if fs and as_:
        print(f"{'構成':<8}{'件数':>6}{'勝率%':>9}{'期待値%/trade':>15}{'累計%':>10}")
        print(f"{'現行固定':<8}{fs['n']:>6}{fs['wr']:>9.1f}{fs['exp']:>15.4f}{fs['total']:>10.2f}")
        print(f"{'B案ATR':<8}{as_['n']:>6}{as_['wr']:>9.1f}{as_['exp']:>15.4f}{as_['total']:>10.2f}")
        rk = _risk_stats(trades, "atr")
        print(f"リスク(B案): 最大DD={rk['max_dd']:.2f}%pt  最大連敗={rk['max_streak']}  最長停滞={rk['max_uw']}取引")
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
