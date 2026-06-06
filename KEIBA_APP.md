# 競馬予想アプリ MVP

`keiba_dashboard.py` は、過去レース結果から馬・騎手・調教師・天気・馬場状態の傾向を集計し、
モンテカルロで各券種の的中確率を推定する Streamlit アプリです。

## 起動
```bash
cd ~/trading_bot/trading_bot/MAIN
python3 -m streamlit run keiba_dashboard.py
```

`Local URL: http://localhost:8501` が出たら起動成功です。  
停止するまでターミナルは開いたままにしてください（`Ctrl+C` で停止）。

## 起動しないように見える時
- ブラウザで `http://localhost:8501` を直接開く
- 既にポート使用中なら `--server.port 8502` で起動する
- エラーが出る場合はそのままターミナルログを確認する（`Ctrl+C` しない）

## 入力
- 履歴CSV（必須カラム）
  - `race_id, horse, jockey, trainer, weather, track_condition, distance, finish`
- 出走馬CSV（必須カラム）
  - `horse, jockey, trainer`
- 任意カラム
  - `odds, place_odds, gate, form_score, condition_score, weight_diff, paddock_score, odds_shift`

`form_score` / `condition_score` は 0-100 で高いほど好調として扱います。
`paddock_score` は 0-100、`weight_diff` は馬体重増減(kg)、`odds_shift` は直前オッズ差（マイナスが人気上昇）です。

## 実データCSVの整形（JRA/NAR向け）
列名が異なるCSVでも `tools/normalize_keiba_csv.py` で変換できます。

```bash
# 履歴
python3 tools/normalize_keiba_csv.py \
  --mode history \
  --in ./data/jra_history_raw.csv \
  --out ./data/jra_history_normalized.csv

# 出走馬
python3 tools/normalize_keiba_csv.py \
  --mode entries \
  --in ./data/jra_entries_raw.csv \
  --out ./data/jra_entries_normalized.csv \
  --default-weather 晴 \
  --default-track 良 \
  --default-distance 1600
```

## 週次チューニング（回収率ベース）
```bash
python3 tools/tune_keiba_feature_weights.py \
  --history ./data/jra_history_normalized.csv \
  --out ./data/keiba_best_weights.json \
  --trials 40 \
  --val-races 30 \
  --simulations 1500
```

生成した `keiba_best_weights.json` は、アプリのサイドバー `重みJSON（任意）` で読み込めます。

## 出力
- 馬ごとの `勝率` / `複勝率`
- 単勝・複勝・馬連・ワイド・馬単・三連複・三連単の買い目候補
- 予算配分案（推奨度重み）

## 注意
- あくまで確率モデルの補助ツールです。
- 実運用では直前オッズ、馬体重、パドック、馬場傾向の最新情報と併用してください。
