#!/usr/bin/env python3
"""
Stock ML Trainer — logistic regression on shadow/backtest CSV data.

Reads backtest_*.csv files (which have pnl_usd per trade), pairs BUY→SELL,
extracts entry-time features, trains a logistic regression via gradient
descent, and saves the model to review_out/stock_ml_model.json.

The model is used by stock_shadow_bot.py --ml-filter to add a probability
score gate before entering positions.

Features (at BUY time):
  x0 = sma_ratio   : sma5 / sma20        (> 1.0 = bullish momentum)
  x1 = rsi_norm    : rsi14 / 100         (0..1)
  x2 = vol_ratio   : vol / avg20_vol     (> 1.0 = above-average volume)
  x3 = price_dev   : (price-sma20)/sma20 (% deviation from mean)
  x4 = prev_return : bar-over-bar return (momentum)

Label:
  y = 1 if exit pnl_usd > 0, else 0

Usage:
    python3 stock_ml_train.py                       # train from all backtest CSVs
    python3 stock_ml_train.py --min-prob 0.55       # threshold used for --ml-filter
    python3 stock_ml_train.py --eval                # evaluate on training data
    python3 stock_ml_train.py --predict 1.025 58.0  # predict: sma_ratio rsi14
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
REVIEW_OUT = ROOT / "review_out"
MODEL_FILE = REVIEW_OUT / "stock_ml_model.json"

FEATURE_NAMES = ["sma_ratio", "rsi_norm", "vol_ratio", "price_dev", "prev_return"]


# ── Data loading ──────────────────────────────────────────────────────────────

def load_backtest_csvs() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for f in sorted(REVIEW_OUT.glob("backtest_*.csv")):
        try:
            with f.open(encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    rows.append(dict(row))
        except Exception as exc:
            print(f"  [!] {f.name}: {exc}", file=sys.stderr)
    return rows


def load_outcome_samples() -> Tuple[List[List[float]], List[int]]:
    """AK: Load signal_scanner_outcomes.csv as additional training samples.
    For each HIT_TP/HIT_SL row, looks up the original signal_weekly_*.json
    to extract sma5/sma20/rsi14 features compatible with extract_samples().
    Rows without indicator data are skipped.
    Returns (X, y) — same feature format as extract_samples().
    """
    outcomes_csv = REVIEW_OUT / "signal_scanner_outcomes.csv"
    if not outcomes_csv.exists():
        return [], []

    # Build an index of signal_weekly_*.json: {date8: {symbol: candidate_dict}}
    weekly_index: Dict[str, Dict[str, Dict]] = {}
    for jf in sorted(REVIEW_OUT.glob("signal_weekly_????????.json")):
        date8 = jf.stem.replace("signal_weekly_", "")
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            weekly_index[date8] = {
                c["symbol"]: c for c in data.get("candidates", []) if "symbol" in c
            }
        except Exception:
            pass

    X: List[List[float]] = []
    y: List[int] = []

    try:
        with outcomes_csv.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                outcome = row.get("outcome", "")
                if outcome not in ("HIT_TP", "HIT_SL"):
                    continue
                symbol = row.get("symbol", "")
                scanned_at = row.get("scanned_at_jst", "")
                date8 = scanned_at[:10].replace("-", "") if scanned_at else ""

                # Lookup original indicators from signal_weekly JSON
                cand = weekly_index.get(date8, {}).get(symbol)
                if cand is None:
                    continue
                try:
                    sma5 = float(cand.get("ma_fast") or cand.get("sma5") or 0)
                    sma20 = float(cand.get("ma_slow") or cand.get("sma20") or 0)
                    rsi14 = float(cand.get("rsi14") or 50.0)
                except (ValueError, TypeError):
                    continue
                if sma20 == 0:
                    continue
                sma_ratio = sma5 / sma20
                rsi_norm = rsi14 / 100.0
                X.append([sma_ratio, rsi_norm, 1.0, 0.0, 0.0])
                y.append(1 if outcome == "HIT_TP" else 0)
    except Exception as exc:
        print(f"  [!] outcome CSV load error: {exc}", file=sys.stderr)

    return X, y


def extract_samples(rows: List[Dict[str, str]]) -> Tuple[List[List[float]], List[int]]:
    """
    Pair BUY → SELL for each symbol in chronological order.
    Features extracted from BUY row; label from SELL pnl_usd.
    Old CSVs without vol_ratio/price_dev/prev_return get defaults (1.0, 0.0, 0.0).
    """
    from collections import defaultdict
    by_symbol: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for r in rows:
        by_symbol[r.get("symbol", "")].append(r)

    X: List[List[float]] = []
    y: List[int] = []

    for sym, sym_rows in by_symbol.items():
        pending_buy: Optional[Dict[str, str]] = None
        for r in sym_rows:
            action = r.get("action", "")
            if action == "BUY":
                pending_buy = r
            elif action == "SELL" and pending_buy is not None:
                try:
                    sma5 = float(pending_buy["sma5"])
                    sma20 = float(pending_buy["sma20"])
                    rsi14 = float(pending_buy["rsi14"])
                    pnl = float(r.get("pnl_usd", 0))
                except (KeyError, ValueError):
                    pending_buy = None
                    continue
                if sma20 == 0:
                    pending_buy = None
                    continue

                # New features — fall back to neutral defaults for old CSVs
                try:
                    vr = float(pending_buy.get("vol_ratio") or 1.0)
                except (ValueError, TypeError):
                    vr = 1.0
                try:
                    pd_ = float(pending_buy.get("price_dev") or 0.0)
                except (ValueError, TypeError):
                    pd_ = 0.0
                try:
                    pr = float(pending_buy.get("prev_return") or 0.0)
                except (ValueError, TypeError):
                    pr = 0.0

                sma_ratio = sma5 / sma20
                rsi_norm = rsi14 / 100.0
                X.append([sma_ratio, rsi_norm, vr, pd_, pr])
                y.append(1 if pnl > 0 else 0)
                pending_buy = None

    return X, y


# ── Numpy-free logistic regression ────────────────────────────────────────────

def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _dot(w: List[float], x: List[float]) -> float:
    return sum(wi * xi for wi, xi in zip(w, x))


def train_logistic(
    X: List[List[float]],
    y: List[int],
    lr: float = 0.1,
    epochs: int = 500,
    l2: float = 0.01,
) -> Tuple[List[float], float]:
    """Gradient descent logistic regression. Returns (weights, bias)."""
    n_feat = len(X[0]) if X else len(FEATURE_NAMES)
    n = len(X)
    w = [0.0] * n_feat
    b = 0.0

    for epoch in range(epochs):
        dw = [0.0] * n_feat
        db = 0.0
        loss = 0.0
        for xi, yi in zip(X, y):
            z = _dot(w, xi) + b
            p = _sigmoid(z)
            err = p - yi
            for j in range(n_feat):
                dw[j] += err * xi[j]
            db += err
            p_clip = max(min(p, 1 - 1e-9), 1e-9)
            loss += -(yi * math.log(p_clip) + (1 - yi) * math.log(1 - p_clip))

        for j in range(n_feat):
            w[j] -= lr * (dw[j] / n + l2 * w[j])
        b -= lr * (db / n)

        if (epoch + 1) % 100 == 0:
            avg_loss = loss / n
            print(f"  epoch {epoch+1:4d}  loss={avg_loss:.4f}")

    return w, b


def predict_proba(w: List[float], b: float, x: List[float]) -> float:
    return _sigmoid(_dot(w, x) + b)


def evaluate(w: List[float], b: float, X: List[List[float]], y: List[int]) -> None:
    correct = 0
    tp = fp = tn = fn = 0
    for xi, yi in zip(X, y):
        p = predict_proba(w, b, xi)
        pred = 1 if p >= 0.5 else 0
        if pred == yi:
            correct += 1
        if pred == 1 and yi == 1:
            tp += 1
        elif pred == 1 and yi == 0:
            fp += 1
        elif pred == 0 and yi == 1:
            fn += 1
        else:
            tn += 1
    n = len(y)
    acc = correct / n if n else 0
    pos_rate = sum(y) / n if n else 0
    print(f"\n  Samples : {n}  (positive rate: {pos_rate:.1%})")
    print(f"  Accuracy: {acc:.1%}  ({correct}/{n})")
    print(f"  TP={tp}  FP={fp}  TN={tn}  FN={fn}")
    if tp + fp > 0:
        prec = tp / (tp + fp)
        print(f"  Precision: {prec:.1%}")
    if tp + fn > 0:
        rec = tp / (tp + fn)
        print(f"  Recall   : {rec:.1%}")


# ── Save / Load ───────────────────────────────────────────────────────────────

def save_model(w: List[float], b: float, meta: Dict[str, Any]) -> None:
    REVIEW_OUT.mkdir(parents=True, exist_ok=True)
    obj = {
        "weights": w,
        "bias": b,
        "features": FEATURE_NAMES,
        "label": "exit_profitable",
        "meta": meta,
    }
    MODEL_FILE.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    print(f"\n[ml] model saved → {MODEL_FILE}")


def load_model() -> Optional[Dict[str, Any]]:
    if not MODEL_FILE.exists():
        return None
    try:
        return json.loads(MODEL_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from datetime import datetime, timedelta

    def _now_jst() -> str:
        return (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")

    ap = argparse.ArgumentParser(description="Train logistic regression on backtest CSV data")
    ap.add_argument("--eval", action="store_true", help="Evaluate model on training data")
    ap.add_argument("--predict", nargs=2, type=float, metavar=("SMA_RATIO", "RSI14"),
                    help="Quick predict: sma_ratio rsi14 (vol_ratio/price_dev/prev_return default to 1/0/0)")
    ap.add_argument("--min-prob", type=float, default=0.55,
                    help="Min probability threshold for --ml-filter in shadow bot (default: 0.55)")
    ap.add_argument("--lr", type=float, default=0.1, help="Learning rate")
    ap.add_argument("--epochs", type=int, default=500, help="Training epochs")
    ap.add_argument("--l2", type=float, default=0.01, help="L2 regularisation")
    ap.add_argument("--include-outcomes", action="store_true",
                    help="AK: also include signal_scanner_outcomes.csv as training data")
    args = ap.parse_args()

    if args.predict:
        model = load_model()
        if model is None:
            print("[ml] No model found. Run without --predict first.", file=sys.stderr)
            sys.exit(1)
        sma_ratio, rsi14 = args.predict
        x = [sma_ratio, rsi14 / 100.0, 1.0, 0.0, 0.0]  # defaults for new features
        # truncate/pad to match model feature count
        n = len(model.get("weights", x))
        x = (x + [0.0] * n)[:n]
        prob = predict_proba(model["weights"], model["bias"], x)
        feats = model.get("features", FEATURE_NAMES)
        print(f"[ml] features={feats}")
        print(f"[ml] sma_ratio={sma_ratio:.4f}  rsi14={rsi14:.1f}  →  P(profit)={prob:.1%}")
        sys.exit(0)

    rows = load_backtest_csvs()
    if not rows:
        print(f"[ml] No backtest CSV found in {REVIEW_OUT}. Run --backtest first.", file=sys.stderr)
        sys.exit(1)

    X, y = extract_samples(rows)

    # AK: optionally include signal_scanner_outcomes.csv as additional training data
    if args.include_outcomes:
        Xo, yo = load_outcome_samples()
        if Xo:
            X += Xo
            y += yo
            print(f"[ml] Outcomes CSV: added {len(Xo)} samples (wins={sum(yo)}, losses={len(yo)-sum(yo)})")
        else:
            print("[ml] Outcomes CSV: no usable samples found (need HIT_TP/HIT_SL with indicator data)")

    if len(X) < 5:
        print(f"[ml] Only {len(X)} samples — need more backtest data. Run with --backtest-days 60.", file=sys.stderr)
        sys.exit(1)

    pos = sum(y)
    print(f"[ml] Training on {len(X)} samples  (wins={pos}, losses={len(y)-pos})")
    print(f"[ml] features={FEATURE_NAMES}")
    print(f"[ml] lr={args.lr}  epochs={args.epochs}  l2={args.l2}\n")

    w, b = train_logistic(X, y, lr=args.lr, epochs=args.epochs, l2=args.l2)

    if args.eval:
        evaluate(w, b, X, y)

    save_model(w, b, {
        "n_samples": len(X),
        "n_wins": pos,
        "min_prob_threshold": args.min_prob,
        "trained_at_jst": _now_jst(),
        "features": FEATURE_NAMES,
    })

    print(f"\n[ml] weights={[round(wi, 4) for wi in w]}  bias={round(b, 4)}")
    print(f"[ml] Use with: python3 stock_shadow_bot.py --ml-filter --ml-min-prob {args.min_prob}")
