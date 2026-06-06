from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping
import sys

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from keiba_predictor import get_default_feature_weights, predict_race, prepare_history_dataframe


@dataclass(frozen=True)
class EvalResult:
    roi: float
    hit_rate: float
    bets: int
    profit: float


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="競馬予想モデルの特徴量重みを回収率ベースで探索します")
    parser.add_argument("--history", required=True, help="正規化済み履歴CSV")
    parser.add_argument("--out", required=True, help="ベスト重みJSON出力先")
    parser.add_argument("--trials", type=int, default=40, help="探索回数")
    parser.add_argument("--val-races", type=int, default=30, help="検証レース数")
    parser.add_argument("--simulations", type=int, default=1500, help="1レース予測シミュレーション回数")
    parser.add_argument("--seed", type=int, default=42, help="乱数シード")
    return parser.parse_args()


def _pick_eval_races(history: pd.DataFrame, n_races: int) -> List[str]:
    race_ids = history["race_id"].astype(str).dropna().unique().tolist()
    race_ids = sorted(race_ids)
    if len(race_ids) <= 3:
        raise ValueError("履歴レース数が少なすぎます（最低4レース以上必要）")
    return race_ids[-min(n_races, len(race_ids) - 1) :]


def _evaluate(history: pd.DataFrame, eval_races: List[str], weights: Mapping[str, float], simulations: int, seed: int) -> EvalResult:
    bets = 0
    hits = 0
    profit = 0.0

    for idx, race_id in enumerate(eval_races):
        race_df = history[history["race_id"].astype(str) == race_id].copy()
        train_df = history[history["race_id"].astype(str) != race_id].copy()
        if race_df.empty or train_df.empty:
            continue

        first = race_df.iloc[0]
        weather = str(first.get("weather", "晴"))
        track_condition = str(first.get("track_condition", "良"))
        distance = float(first.get("distance", 1600.0))

        result = predict_race(
            history_df=train_df,
            entries_df=race_df,
            weather=weather,
            track_condition=track_condition,
            distance=distance,
            simulations=simulations,
            seed=seed + idx,
            budget=0,
            feature_weights=weights,
        )
        if result.horse_predictions.empty:
            continue

        top_horse = str(result.horse_predictions.iloc[0]["馬"])
        actual_rows = race_df[race_df["horse"].astype(str) == top_horse]
        if actual_rows.empty:
            continue

        bets += 1
        actual_finish = float(actual_rows.iloc[0].get("finish", np.nan))
        odds = float(actual_rows.iloc[0].get("odds", np.nan))

        if actual_finish == 1:
            hits += 1
            if np.isfinite(odds) and odds > 1.0:
                profit += odds - 1.0
        else:
            profit -= 1.0

    if bets == 0:
        return EvalResult(roi=-1.0, hit_rate=0.0, bets=0, profit=0.0)

    roi = profit / bets
    hit_rate = hits / bets
    return EvalResult(roi=roi, hit_rate=hit_rate, bets=bets, profit=profit)


def _sample_weights(rng: np.random.Generator, base: Mapping[str, float]) -> Dict[str, float]:
    weights = {k: float(v) for k, v in base.items()}
    tune_keys = [
        "weather_place",
        "track_place",
        "distance_fit",
        "form_score",
        "condition_score",
        "paddock_score",
        "weight_diff_score",
        "odds_shift_score",
        "market_score",
    ]
    for key in tune_keys:
        scale = float(np.exp(rng.normal(0.0, 0.28)))
        weights[key] = max(0.05, min(3.5, weights[key] * scale))
    return weights


def main() -> None:
    args = _parse_args()

    history_raw = pd.read_csv(Path(args.history))
    history = prepare_history_dataframe(history_raw)
    eval_races = _pick_eval_races(history, n_races=args.val_races)

    rng = np.random.default_rng(args.seed)
    base_weights = get_default_feature_weights()

    best_weights = dict(base_weights)
    best_eval = _evaluate(history, eval_races, best_weights, args.simulations, args.seed)

    for trial in range(1, int(args.trials) + 1):
        candidate = _sample_weights(rng, base_weights)
        result = _evaluate(history, eval_races, candidate, args.simulations, args.seed + trial * 100)

        if (result.roi > best_eval.roi) or (
            np.isclose(result.roi, best_eval.roi) and result.hit_rate > best_eval.hit_rate
        ):
            best_eval = result
            best_weights = candidate

    output = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "history_rows": int(len(history)),
        "eval_races": eval_races,
        "trials": int(args.trials),
        "simulations": int(args.simulations),
        "best_eval": {
            "roi": float(best_eval.roi),
            "hit_rate": float(best_eval.hit_rate),
            "bets": int(best_eval.bets),
            "profit": float(best_eval.profit),
        },
        "base_weights": base_weights,
        "best_weights": best_weights,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"history_rows={len(history)}")
    print(f"eval_races={len(eval_races)}")
    print(f"best_roi={best_eval.roi:.4f}")
    print(f"best_hit_rate={best_eval.hit_rate:.4f}")
    print(f"out={out_path}")


if __name__ == "__main__":
    main()
