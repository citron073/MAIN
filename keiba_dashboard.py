from __future__ import annotations

import json
from typing import Dict

import pandas as pd
import streamlit as st

from keiba_predictor import (
    PredictionResult,
    TRACK_OPTIONS,
    WEATHER_OPTIONS,
    export_template_csv,
    generate_sample_entries,
    generate_sample_history,
    predict_race,
)

st.set_page_config(
    page_title="競馬予想アプリ MVP",
    page_icon="🏇",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _inject_style() -> None:
    st.markdown(
        """
<style>
:root {
  --k-bg-top: #f7f2e7;
  --k-bg-bottom: #efe7d2;
  --k-card-bg: rgba(255, 255, 255, 0.8);
  --k-card-border: rgba(90, 74, 39, 0.24);
  --k-text-main: #2b2216;
  --k-text-sub: #5d4d33;
  --k-accent: #2f7d32;
  --k-accent-soft: #dbf2dc;
}
.stApp {
  background: radial-gradient(1000px 440px at 0% -10%, rgba(236, 224, 197, 0.75), transparent 58%),
    radial-gradient(940px 420px at 100% -8%, rgba(176, 217, 184, 0.55), transparent 52%),
    linear-gradient(180deg, var(--k-bg-top) 0%, var(--k-bg-bottom) 100%);
  color: var(--k-text-main);
  font-family: "Hiragino Sans", "Yu Gothic", "Meiryo", sans-serif;
}
section.main > div.block-container {
  padding-top: 1rem;
  padding-bottom: 1.4rem;
}
h1, h2, h3 {
  color: var(--k-text-main);
  letter-spacing: 0.01em;
}
p, label, span {
  color: var(--k-text-sub);
}
div[data-testid="stMetric"] {
  border: 1px solid var(--k-card-border);
  border-radius: 0.95rem;
  background: var(--k-card-bg);
  box-shadow: 0 6px 20px rgba(60, 48, 25, 0.09);
}
div.stButton > button {
  background: linear-gradient(180deg, #2f7d32 0%, #236529 100%);
  color: #f8fff8;
  border: 1px solid #1f5723;
  border-radius: 0.8rem;
  font-weight: 700;
}
div[data-testid="stSidebar"] > div:first-child {
  background: linear-gradient(180deg, rgba(255, 252, 243, 0.94) 0%, rgba(242, 234, 211, 0.94) 100%);
  border-right: 1px solid var(--k-card-border);
}
</style>
""",
        unsafe_allow_html=True,
    )


def _to_csv_download(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def _format_probability_tables(result: PredictionResult) -> Dict[str, pd.DataFrame]:
    formatted: Dict[str, pd.DataFrame] = {}
    for name, table in result.bet_recommendations.items():
        if table.empty:
            formatted[name] = table
            continue
        out = table.copy()
        for col in ("的中確率",):
            if col in out.columns:
                out[col] = out[col].map(lambda x: f"{x:.2%}")
        for col in ("推奨度",):
            if col in out.columns:
                out[col] = out[col].map(lambda x: f"{x:.2f}")
        for col in ("理論オッズ", "単勝オッズ", "複勝オッズ"):
            if col in out.columns:
                out[col] = out[col].map(
                    lambda x: "-" if pd.isna(x) else ("∞" if float(x) > 9999 else f"{float(x):.2f}")
                )
        for col in ("単勝期待値", "複勝期待値"):
            if col in out.columns:
                out[col] = out[col].map(lambda x: "-" if pd.isna(x) else f"{float(x):+.2f}")
        formatted[name] = out
    return formatted


def _render_schema_help() -> None:
    with st.expander("CSVフォーマット（履歴/出走馬）"):
        st.markdown(
            """
- 履歴CSV 必須カラム: `race_id, horse, jockey, trainer, weather, track_condition, distance, finish`
- 履歴CSV 任意カラム: `odds, place_odds, gate, form_score, condition_score`
- 出走馬CSV 必須カラム: `horse, jockey, trainer`
- 出走馬CSV 任意カラム: `odds, place_odds, gate, form_score, condition_score, weight_diff, paddock_score, odds_shift, weather, track_condition, distance`
- `form_score` と `condition_score` は 0-100 を想定（高いほど好調）
- `paddock_score` は 0-100、`weight_diff` は当日馬体重増減(kg)、`odds_shift` は直前オッズ差（マイナスで人気上昇）
"""
        )


_inject_style()

st.title("競馬予想アプリ MVP")
st.caption("過去成績 + 天気 + 馬場状態 + 調子スコア から、買い目を確率ベースで提案します")

with st.sidebar:
    st.subheader("予想条件")
    weather = st.selectbox("天気", WEATHER_OPTIONS, index=0)
    track_condition = st.selectbox("馬場状態", TRACK_OPTIONS, index=0)
    distance = st.number_input("距離 (m)", min_value=1000, max_value=3600, value=1600, step=100)
    simulations = st.slider("シミュレーション回数", min_value=2000, max_value=50000, value=15000, step=1000)
    seed = st.number_input("乱数シード", min_value=1, max_value=99999, value=42, step=1)
    budget = st.number_input("予算 (円)", min_value=0, max_value=500000, value=10000, step=500)
    unit = st.number_input("最小購入単位 (円)", min_value=100, max_value=5000, value=100, step=100)
    weight_json = st.file_uploader("重みJSON（任意）", type=["json"], key="feature_weights")

    st.divider()
    use_sample = st.toggle("サンプルデータを使う", value=True)

    template_history, template_entries = export_template_csv()
    st.download_button(
        "履歴CSVテンプレートを保存",
        data=_to_csv_download(template_history.head(120)),
        file_name="keiba_history_template.csv",
        mime="text/csv",
    )
    st.download_button(
        "出走馬CSVテンプレートを保存",
        data=_to_csv_download(template_entries),
        file_name="keiba_entries_template.csv",
        mime="text/csv",
    )

col_left, col_right = st.columns([1.05, 1.0], gap="large")

history_df: pd.DataFrame
entries_df: pd.DataFrame

with col_left:
    st.subheader("1) 過去成績データ")
    if use_sample:
        sample_races = st.slider("サンプル履歴レース数", min_value=80, max_value=600, value=280, step=20)
        history_df = generate_sample_history(seed=int(seed), n_races=int(sample_races))
        st.info("サンプル履歴を生成しています。実データがある場合はトグルをOFFにしてCSVを読み込んでください。")
    else:
        uploaded_history = st.file_uploader("履歴CSVをアップロード", type=["csv"], key="history")
        if uploaded_history is None:
            st.warning("履歴CSVをアップロードしてください")
            st.stop()
        history_df = pd.read_csv(uploaded_history)

    st.dataframe(history_df.head(20), width="stretch")
    st.caption(f"履歴件数: {len(history_df):,} 行")

with col_right:
    st.subheader("2) 出走馬データ")
    if use_sample:
        field_size = st.slider("出走頭数", min_value=8, max_value=18, value=12, step=1)
        entries_df = generate_sample_entries(
            history_df,
            weather=weather,
            track_condition=track_condition,
            distance=int(distance),
            field_size=int(field_size),
            seed=int(seed) + 1,
        )
    else:
        uploaded_entries = st.file_uploader("出走馬CSVをアップロード", type=["csv"], key="entries")
        if uploaded_entries is None:
            st.warning("出走馬CSVをアップロードしてください")
            st.stop()
        entries_df = pd.read_csv(uploaded_entries)

    st.caption(
        "`form_score` / `condition_score` / `paddock_score` / `weight_diff` / `odds_shift` を編集すると直前情報を反映できます"
    )
    entries_df = st.data_editor(
        entries_df,
        width="stretch",
        num_rows="dynamic",
        height=430,
        key="entries_editor",
    )

_render_schema_help()

run_predict = st.button("予想を実行", type="primary")
if not run_predict:
    st.stop()

feature_weights = None
if weight_json is not None:
    try:
        payload = json.loads(weight_json.read().decode("utf-8"))
        if isinstance(payload, dict) and "best_weights" in payload and isinstance(payload["best_weights"], dict):
            feature_weights = payload["best_weights"]
        elif isinstance(payload, dict):
            feature_weights = payload
        else:
            raise ValueError("JSON形式が不正です")
        st.caption("重みJSONを適用して予想します")
    except Exception as exc:
        st.error(f"重みJSONの読み込みに失敗しました: {exc}")
        st.stop()

try:
    result = predict_race(
        history_df=history_df,
        entries_df=entries_df,
        weather=weather,
        track_condition=track_condition,
        distance=float(distance),
        simulations=int(simulations),
        seed=int(seed),
        budget=float(budget),
        bet_units=int(unit),
        feature_weights=feature_weights,
    )
except Exception as exc:
    st.error(f"予想処理でエラーが発生しました: {exc}")
    st.stop()

st.success("予想が完了しました")

summary_col1, summary_col2, summary_col3 = st.columns(3)
top_horse = result.horse_predictions.iloc[0]
summary_col1.metric("本命候補", str(top_horse["馬"]))
summary_col2.metric("勝率", f"{float(top_horse['勝率']):.2%}")
summary_col3.metric("複勝率", f"{float(top_horse['複勝率']):.2%}")

st.subheader("馬ごとの予測")
view_horse = result.horse_predictions.copy()
for col in ("勝率", "複勝率", "horse_win_rate", "horse_place_rate", "weather_fit", "track_fit", "distance_fit"):
    if col in view_horse.columns:
        view_horse[col] = view_horse[col].map(lambda x: f"{float(x):.2%}")
for col in ("form_factor", "condition_factor", "market_factor"):
    if col in view_horse.columns:
        view_horse[col] = view_horse[col].map(lambda x: f"{float(x):.2f}")
for col in ("paddock_factor", "weight_diff_factor", "odds_shift_factor"):
    if col in view_horse.columns:
        view_horse[col] = view_horse[col].map(lambda x: f"{float(x):.2f}")
for col in ("理論単勝オッズ", "単勝オッズ", "複勝オッズ"):
    if col in view_horse.columns:
        view_horse[col] = view_horse[col].map(lambda x: "-" if pd.isna(x) else f"{float(x):.2f}")
for col in ("単勝期待値", "複勝期待値"):
    if col in view_horse.columns:
        view_horse[col] = view_horse[col].map(lambda x: "-" if pd.isna(x) else f"{float(x):+.2f}")

st.dataframe(view_horse, width="stretch", height=380)

chart_df = result.horse_predictions[["馬", "勝率", "複勝率"]].set_index("馬")
st.bar_chart(chart_df)

st.subheader("買い目提案")
formatted_tables = _format_probability_tables(result)
for bet_type, table in formatted_tables.items():
    st.markdown(f"### {bet_type}")
    if table.empty:
        st.caption("出走頭数が少ないため、この券種は算出対象外です。")
        continue
    st.dataframe(table, width="stretch")

st.subheader("予算配分案")
if result.budget_plan.empty:
    st.caption("予算配分案を作成できませんでした。推奨度が十分な買い目がない可能性があります。")
else:
    st.dataframe(result.budget_plan, width="stretch")

st.info(
    "このMVPは確率モデルによる支援ツールです。最終判断はオッズ変動・直前気配・馬体重などの最新情報と合わせて行ってください。"
)
