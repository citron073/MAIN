# ============================================================
# Trading Bot Dashboard — Project Ouroboros v1 (SPEC-Compliant)
#
# SPEC:
# - CONTROL.csv (key,value) editing UI
# - Preserve unknown keys (never delete)
# - daily_report / audit execution buttons
# - Audit JSON visualization (priority)
# - pos_id-centric view (status from JSON MUST NOT be rejudged)
# - issues: include pos_id text; buttons jump to search
# - ret_pct estimate: (exit-entry)/entry ; SELL sign inversion; fee not included; always label as "推定"
#
# Run:
#   python3 -m streamlit run dashboard.py
# ============================================================

from __future__ import annotations

import csv
import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import re
import signal
import socket
import ipaddress
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from ouroboros_contract import TRADE_LOG_FIELDS
try:
    import plotly.express as px
    import plotly.graph_objects as go

    HAS_PLOTLY = True
except Exception:
    HAS_PLOTLY = False

# =========================
# App version
# =========================
APP_NAME = "Project Ouroboros"
APP_VERSION = "v1.1.9"
APP_DISPLAY_VERSION = f"{APP_NAME} {APP_VERSION}"

# =========================
# Page Config
# =========================
st.set_page_config(
    page_title=f"Trading Bot Dashboard ({APP_DISPLAY_VERSION})",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================
# i18n (minimal)
# =========================
I18N = {
    "ja": {
        "app_title": "Trading Bot Dashboard",
        "subtitle": f"{APP_DISPLAY_VERSION} — 管理・監査パネル",
        "tab_home": "🏠 ホーム",
        "tab_settings": "⚙️ 設定",
        "tab_analytics": "📊 分析",
        "tab_backtest": "🔬 バックテスト",
        "tab_history": "📝 履歴",
        "tab_pos": "🔍 監査",
        "tab_guide": "📚 ガイド",
        "tab_tools": "🛠 ツール",
        "tab_ops": "🚀 オペレーション",
        "tab_shadow": "🧪 シャドウ",
        "tab_ibkr": "📈 IBKR",
        "save_success": "設定を保存しました！",
        "save_error": "保存に失敗しました。",
        "loading": "読み込み中...",
        "audit_json_priority": "監査JSONが存在するため、これを最優先で表示しています（Dashboard側でstatus再判定しません）。",
        "fallback_mode": "監査JSONが無いので、ログから推定した結果を表示しています（推定）。",
    }
}

TAB_ORDER_DEFAULT_KEYS = [
    "home",
    "settings",
    "analytics",
    "backtest",
    "history",
    "pos",
    "guide",
    "tools",
    "ops",
    "shadow",
    "ibkr",
]

TAB_I18N_KEY_BY_ID = {
    "home": "tab_home",
    "settings": "tab_settings",
    "analytics": "tab_analytics",
    "backtest": "tab_backtest",
    "history": "tab_history",
    "pos": "tab_pos",
    "guide": "tab_guide",
    "tools": "tab_tools",
    "ops": "tab_ops",
    "shadow": "tab_shadow",
    "ibkr": "tab_ibkr",
}


def T(key: str) -> str:
    lang = st.session_state.get("lang", "ja")
    return I18N.get(lang, I18N["ja"]).get(key, key)


def _inject_tabs_mouse_friendly_css(density: str = "standard") -> None:
    st.markdown(
        """
<style>
/* Global visual design */
:root {
  --ob-font-ui: "Avenir Next", "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP", "Segoe UI", sans-serif;
  --ob-page-bg: radial-gradient(1200px 500px at 0% -10%, rgba(2, 132, 199, 0.12), transparent 45%),
    radial-gradient(900px 420px at 100% -20%, rgba(20, 184, 166, 0.10), transparent 45%),
    linear-gradient(180deg, #f7fafc 0%, #eef4f9 100%);
  --ob-card-bg: rgba(255, 255, 255, 0.78);
  --ob-card-soft-bg: rgba(255, 255, 255, 0.62);
  --ob-card-border: rgba(100, 116, 139, 0.28);
  --ob-card-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
  --ob-text-main: #0f172a;
  --ob-text-muted: #475569;
  --ob-sidebar-bg: linear-gradient(180deg, rgba(248, 252, 255, 0.96) 0%, rgba(239, 246, 252, 0.96) 100%);
  --ob-btn-bg: linear-gradient(180deg, #ffffff 0%, #f2f7fc 100%);
  --ob-btn-border: rgba(100, 116, 139, 0.35);
  --ob-btn-text: #0f172a;
  --ob-btn-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}
html[data-theme="dark"],
body[data-theme="dark"] {
  --ob-page-bg: radial-gradient(1200px 550px at 0% -10%, rgba(34, 211, 238, 0.10), transparent 48%),
    radial-gradient(900px 420px at 100% -20%, rgba(16, 185, 129, 0.08), transparent 45%),
    linear-gradient(180deg, #020617 0%, #0b1220 100%);
  --ob-card-bg: rgba(15, 23, 42, 0.78);
  --ob-card-soft-bg: rgba(15, 23, 42, 0.62);
  --ob-card-border: rgba(100, 116, 139, 0.42);
  --ob-card-shadow: 0 12px 28px rgba(2, 6, 23, 0.45);
  --ob-text-main: #e2e8f0;
  --ob-text-muted: #94a3b8;
  --ob-sidebar-bg: linear-gradient(180deg, rgba(2, 6, 23, 0.98) 0%, rgba(15, 23, 42, 0.98) 100%);
  --ob-btn-bg: linear-gradient(180deg, #0f172a 0%, #111827 100%);
  --ob-btn-border: rgba(100, 116, 139, 0.55);
  --ob-btn-text: #e2e8f0;
  --ob-btn-shadow: 0 1px 2px rgba(2, 6, 23, 0.55);
}
@media (prefers-color-scheme: dark) {
  :root {
    --ob-page-bg: radial-gradient(1200px 550px at 0% -10%, rgba(34, 211, 238, 0.10), transparent 48%),
      radial-gradient(900px 420px at 100% -20%, rgba(16, 185, 129, 0.08), transparent 45%),
      linear-gradient(180deg, #020617 0%, #0b1220 100%);
    --ob-card-bg: rgba(15, 23, 42, 0.78);
    --ob-card-soft-bg: rgba(15, 23, 42, 0.62);
    --ob-card-border: rgba(100, 116, 139, 0.42);
    --ob-card-shadow: 0 12px 28px rgba(2, 6, 23, 0.45);
    --ob-text-main: #e2e8f0;
    --ob-text-muted: #94a3b8;
    --ob-sidebar-bg: linear-gradient(180deg, rgba(2, 6, 23, 0.98) 0%, rgba(15, 23, 42, 0.98) 100%);
    --ob-btn-bg: linear-gradient(180deg, #0f172a 0%, #111827 100%);
    --ob-btn-border: rgba(100, 116, 139, 0.55);
    --ob-btn-text: #e2e8f0;
    --ob-btn-shadow: 0 1px 2px rgba(2, 6, 23, 0.55);
  }
}
.stApp, div[data-testid="stAppViewContainer"] {
  background: var(--ob-page-bg);
  color: var(--ob-text-main);
  font-family: var(--ob-font-ui);
}
section.main > div.block-container {
  padding-top: 1.05rem;
  padding-bottom: 1.5rem;
}
section[data-testid="stSidebar"] > div:first-child {
  background: var(--ob-sidebar-bg);
  border-right: 1px solid var(--ob-card-border);
}
h1, h2, h3, h4 {
  letter-spacing: 0.01em;
}
p, span, label, div[data-testid="stCaptionContainer"] {
  color: var(--ob-text-muted);
}
div[data-testid="stMetric"] {
  background: var(--ob-card-bg);
  border: 1px solid var(--ob-card-border);
  border-radius: 0.95rem;
  padding: 0.58rem 0.72rem;
  box-shadow: var(--ob-card-shadow);
}
div[data-testid="stMetricValue"] {
  font-weight: 800;
}
div.stButton > button {
  border-radius: 0.78rem;
  border: 1px solid var(--ob-btn-border);
  background: var(--ob-btn-bg);
  color: var(--ob-btn-text);
  box-shadow: var(--ob-btn-shadow);
  font-weight: 700;
  transition: transform 0.11s ease, box-shadow 0.11s ease;
}
div.stButton > button:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 14px rgba(2, 132, 199, 0.18);
}
details[data-testid="stExpander"] {
  border: 1px solid var(--ob-card-border);
  border-radius: 0.95rem;
  background: var(--ob-card-soft-bg);
  overflow: hidden;
}
details[data-testid="stExpander"] > summary {
  background: transparent;
}
div[data-testid="stDataFrame"],
div[data-testid="stCodeBlock"] {
  border: 1px solid var(--ob-card-border);
  border-radius: 0.9rem;
  overflow: hidden;
}

/* Tabs: easier mouse operation + card-like visual treatment */
div[data-testid="stTabs"] {
  --ob-tab-bg: linear-gradient(180deg, #f7fafc 0%, #eef3f8 100%);
  --ob-tab-border: #cdd8e5;
  --ob-tab-text: #1f2937;
  --ob-tab-hover-bg: #ffffff;
  --ob-tab-active-bg: linear-gradient(135deg, #0f766e 0%, #0284c7 100%);
  --ob-tab-active-text: #ffffff;
  --ob-tab-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
  --ob-tab-hover-shadow: 0 3px 10px rgba(2, 132, 199, 0.18);
  --ob-tab-active-border: #0b6b7b;
  --ob-tab-active-shadow: 0 4px 12px rgba(15, 118, 110, 0.25);
  --ob-tablist-border: #dbe5ef;
  --ob-tablist-bg: linear-gradient(180deg, #f9fbfd 0%, #f2f6fa 100%);
}
html[data-theme="dark"] div[data-testid="stTabs"],
body[data-theme="dark"] div[data-testid="stTabs"] {
  --ob-tab-bg: linear-gradient(180deg, #111827 0%, #0b1220 100%);
  --ob-tab-border: #334155;
  --ob-tab-text: #e5edf7;
  --ob-tab-hover-bg: linear-gradient(180deg, #182235 0%, #111a2b 100%);
  --ob-tab-active-bg: linear-gradient(135deg, #06b6d4 0%, #0ea5e9 45%, #14b8a6 100%);
  --ob-tab-active-text: #ffffff;
  --ob-tab-shadow: 0 2px 5px rgba(2, 6, 23, 0.55);
  --ob-tab-hover-shadow: 0 4px 12px rgba(56, 189, 248, 0.32);
  --ob-tab-active-border: #22d3ee;
  --ob-tab-active-shadow: 0 6px 14px rgba(34, 211, 238, 0.35);
  --ob-tablist-border: #334155;
  --ob-tablist-bg: linear-gradient(180deg, #0a0f1a 0%, #0b1220 100%);
}
@media (prefers-color-scheme: dark) {
  div[data-testid="stTabs"] {
    --ob-tab-bg: linear-gradient(180deg, #111827 0%, #0b1220 100%);
    --ob-tab-border: #334155;
    --ob-tab-text: #e5edf7;
    --ob-tab-hover-bg: linear-gradient(180deg, #182235 0%, #111a2b 100%);
    --ob-tab-active-bg: linear-gradient(135deg, #06b6d4 0%, #0ea5e9 45%, #14b8a6 100%);
    --ob-tab-active-text: #ffffff;
    --ob-tab-shadow: 0 2px 5px rgba(2, 6, 23, 0.55);
    --ob-tab-hover-shadow: 0 4px 12px rgba(56, 189, 248, 0.32);
    --ob-tab-active-border: #22d3ee;
    --ob-tab-active-shadow: 0 6px 14px rgba(34, 211, 238, 0.35);
    --ob-tablist-border: #334155;
    --ob-tablist-bg: linear-gradient(180deg, #0a0f1a 0%, #0b1220 100%);
  }
}
div[data-testid="stTabs"] div[role="tablist"] {
  overflow-x: auto;
  overflow-y: visible;
  flex-wrap: nowrap;
  gap: 0.35rem;
  padding: 0.35rem 0.25rem 0.4rem 0.25rem;
  border: 1px solid var(--ob-tablist-border);
  border-radius: 0.95rem;
  background: var(--ob-tablist-bg);
  scrollbar-width: thin;
  -webkit-overflow-scrolling: touch;
}
div[data-testid="stTabs"] button[role="tab"] {
  flex: 0 0 auto;
  min-height: 2.25rem;
  padding: 0.42rem 0.88rem;
  border: 1px solid var(--ob-tab-border) !important;
  border-radius: 999px;
  background: var(--ob-tab-bg) !important;
  color: var(--ob-tab-text) !important;
  font-weight: 700;
  letter-spacing: 0.01em;
  box-shadow: var(--ob-tab-shadow);
  transition: transform 0.12s ease, box-shadow 0.12s ease, background 0.12s ease;
}
div[data-testid="stTabs"] button[role="tab"]:hover {
  background: var(--ob-tab-hover-bg) !important;
  transform: translateY(-1px);
  box-shadow: var(--ob-tab-hover-shadow);
}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
  background: var(--ob-tab-active-bg) !important;
  color: var(--ob-tab-active-text) !important;
  border-color: var(--ob-tab-active-border) !important;
  box-shadow: var(--ob-tab-active-shadow);
}
div[data-testid="stTabs"] button[role="tab"]:focus-visible {
  outline: 2px solid #0ea5e9 !important;
  outline-offset: 2px;
}
@media (max-width: 900px) {
  div[data-testid="stTabs"] button[role="tab"] {
    min-height: 2.05rem;
    padding: 0.34rem 0.72rem;
    font-size: 0.86rem;
  }
}
</style>
""",
        unsafe_allow_html=True,
    )
    mode = str(density or "standard").strip().lower()
    if mode not in {"compact", "standard", "relaxed"}:
        mode = "standard"

    if mode == "compact":
        st.markdown(
            """
<style>
section.main > div.block-container {
  padding-top: 0.62rem;
  padding-bottom: 0.95rem;
}
div[data-testid="stMetric"] {
  padding: 0.42rem 0.56rem;
}
div.stButton > button {
  min-height: 2.06rem;
  padding: 0.20rem 0.56rem;
}
details[data-testid="stExpander"] > summary {
  padding-top: 0.06rem;
  padding-bottom: 0.06rem;
}
</style>
""",
            unsafe_allow_html=True,
        )
    elif mode == "relaxed":
        st.markdown(
            """
<style>
section.main > div.block-container {
  padding-top: 1.25rem;
  padding-bottom: 1.95rem;
}
div[data-testid="stMetric"] {
  padding: 0.74rem 0.90rem;
}
div.stButton > button {
  min-height: 2.40rem;
  padding: 0.34rem 0.78rem;
}
details[data-testid="stExpander"] > summary {
  padding-top: 0.14rem;
  padding-bottom: 0.14rem;
}
</style>
""",
            unsafe_allow_html=True,
        )

def _inject_trading_flair_css() -> None:
    st.markdown(
        """
<style>
.ob-global-strip {
  border: 1px solid rgba(56, 189, 248, 0.24);
  border-radius: 16px;
  padding: 10px 12px 11px 12px;
  margin: 0.05rem 0 0.65rem 0;
  background:
    radial-gradient(120% 140% at 8% -35%, rgba(6, 182, 212, 0.16), transparent 46%),
    radial-gradient(120% 120% at 100% -30%, rgba(16, 185, 129, 0.10), transparent 50%),
    linear-gradient(145deg, rgba(2, 6, 23, 0.95) 0%, rgba(9, 16, 35, 0.95) 100%);
  box-shadow: 0 8px 18px rgba(2, 6, 23, 0.22);
}
.ob-global-strip-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.42rem;
}
.ob-global-strip-title {
  color: #f8fafc;
  font-size: 0.86rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.ob-global-strip-time {
  color: #94a3b8;
  font-size: 0.72rem;
}
.ob-global-strip-pills {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.36rem;
  margin-bottom: 0.5rem;
}
.ob-pill {
  border-radius: 999px;
  padding: 0.15rem 0.55rem;
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.03em;
  border: 1px solid transparent;
}
.ob-pill.is-normal {
  color: #052e16;
  background: linear-gradient(180deg, #bbf7d0 0%, #4ade80 100%);
}
.ob-pill.is-alert {
  color: #4c0519;
  background: linear-gradient(180deg, #fecdd3 0%, #fb7185 100%);
}
.ob-pill.is-wait {
  color: #422006;
  background: linear-gradient(180deg, #fde68a 0%, #fbbf24 100%);
}
.ob-pill.is-on {
  color: #082f49;
  border-color: rgba(56, 189, 248, 0.65);
  background: linear-gradient(180deg, #bae6fd 0%, #7dd3fc 100%);
}
.ob-pill.is-off {
  color: #e2e8f0;
  border-color: rgba(148, 163, 184, 0.45);
  background: rgba(15, 23, 42, 0.75);
}
.ob-global-tape {
  overflow: hidden;
  border: 1px solid rgba(100, 116, 139, 0.32);
  border-radius: 10px;
  background: rgba(2, 6, 23, 0.56);
  margin-bottom: 0.52rem;
}
.ob-global-tape-track {
  color: #cbd5e1;
  font-family: "SF Mono", "Menlo", "Consolas", "Monaco", monospace;
  font-size: 0.72rem;
  white-space: nowrap;
  padding: 0.34rem 0.52rem;
  display: inline-block;
  min-width: 100%;
  animation: obGlobalTapeMove 26s linear infinite;
}
@keyframes obGlobalTapeMove {
  0% { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}
.ob-global-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.42rem;
}
.ob-global-kpi {
  border: 1px solid rgba(100, 116, 139, 0.32);
  border-radius: 10px;
  background: rgba(2, 6, 23, 0.46);
  padding: 0.35rem 0.5rem 0.38rem 0.5rem;
}
.ob-global-kpi-label {
  color: #93c5fd;
  font-size: 0.66rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.ob-global-kpi-value {
  color: #f8fafc;
  font-size: 0.9rem;
  font-weight: 780;
}
.ob-global-kpi-value.is-positive {
  color: #86efac;
}
.ob-global-kpi-value.is-negative {
  color: #fda4af;
}

.ob-exec-tape {
  overflow: hidden;
  border: 1px solid rgba(56, 189, 248, 0.24);
  border-radius: 11px;
  background: rgba(2, 6, 23, 0.64);
  margin: 0.22rem 0 0.54rem 0;
}
.ob-exec-tape-track {
  color: #e2e8f0;
  font-family: "SF Mono", "Menlo", "Consolas", "Monaco", monospace;
  font-size: 0.71rem;
  white-space: nowrap;
  padding: 0.34rem 0.52rem;
  display: inline-block;
  min-width: 100%;
  animation: obExecTapeMove 40s linear infinite;
}
@keyframes obExecTapeMove {
  0% { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}
.ob-drift-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.48rem;
  margin: 0.2rem 0 0.55rem 0;
}
.ob-drift-step {
  border: 1px solid rgba(100, 116, 139, 0.35);
  border-radius: 10px;
  padding: 0.44rem 0.56rem 0.5rem 0.56rem;
  background: rgba(2, 6, 23, 0.44);
}
.ob-drift-step.is-done {
  border-color: rgba(74, 222, 128, 0.55);
  box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.22) inset;
}
.ob-drift-step.is-active {
  border-color: rgba(56, 189, 248, 0.45);
  box-shadow: 0 0 0 1px rgba(14, 165, 233, 0.14) inset;
}
.ob-drift-step.is-pending {
  opacity: 0.86;
}
.ob-drift-step-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.3rem;
}
.ob-drift-step-name {
  color: #e2e8f0;
  font-size: 0.76rem;
  font-weight: 800;
}
.ob-drift-step-value {
  color: #93c5fd;
  font-size: 0.72rem;
  font-weight: 700;
}
.ob-drift-bar {
  width: 100%;
  height: 6px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.9);
  border: 1px solid rgba(100, 116, 139, 0.32);
  overflow: hidden;
}
.ob-drift-bar > span {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #0ea5e9 0%, #14b8a6 100%);
}

.ob-market-hero {
  border: 1px solid rgba(56, 189, 248, 0.35);
  border-radius: 16px;
  padding: 14px 14px 12px 14px;
  margin: 0.18rem 0 0.7rem 0;
  background:
    radial-gradient(120% 120% at 8% -20%, rgba(34, 211, 238, 0.20), transparent 45%),
    radial-gradient(120% 120% at 100% -30%, rgba(16, 185, 129, 0.16), transparent 48%),
    linear-gradient(140deg, rgba(15, 23, 42, 0.95) 0%, rgba(2, 6, 23, 0.96) 100%);
  box-shadow: 0 10px 28px rgba(2, 6, 23, 0.26);
}
.ob-market-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  margin-bottom: 0.6rem;
}
.ob-market-title {
  color: #e2e8f0;
  font-size: 0.92rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.ob-market-subtitle {
  color: #94a3b8;
  font-size: 0.76rem;
  margin-left: 0.48rem;
}
.ob-market-badge {
  border-radius: 999px;
  padding: 0.22rem 0.62rem;
  font-size: 0.74rem;
  font-weight: 800;
  letter-spacing: 0.03em;
}
.ob-market-badge.is-normal {
  color: #022c22;
  background: linear-gradient(180deg, #86efac 0%, #4ade80 100%);
}
.ob-market-badge.is-alert {
  color: #450a0a;
  background: linear-gradient(180deg, #fda4af 0%, #fb7185 100%);
}
.ob-market-badge.is-wait {
  color: #422006;
  background: linear-gradient(180deg, #fde68a 0%, #fbbf24 100%);
}
.ob-market-ticker {
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.25);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.42);
  margin-bottom: 0.62rem;
}
.ob-market-ticker-track {
  color: #cbd5e1;
  font-family: "SF Mono", "Menlo", "Consolas", "Monaco", monospace;
  font-size: 0.76rem;
  white-space: nowrap;
  padding: 0.38rem 0.52rem;
  display: inline-block;
  min-width: 100%;
  animation: obTickerMove 22s linear infinite;
}
@keyframes obTickerMove {
  0% { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}
.ob-market-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.5rem;
}
.ob-market-card {
  border: 1px solid rgba(100, 116, 139, 0.35);
  border-radius: 11px;
  background: rgba(2, 6, 23, 0.45);
  padding: 0.44rem 0.58rem 0.48rem 0.58rem;
}
.ob-market-card-label {
  color: #93c5fd;
  font-size: 0.69rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin-bottom: 0.18rem;
}
.ob-market-card-value {
  color: #f8fafc;
  font-size: 0.92rem;
  font-weight: 700;
}
.ob-market-card-note {
  color: #94a3b8;
  font-size: 0.72rem;
  margin-top: 0.12rem;
}
@media (max-width: 920px) {
  .ob-global-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .ob-drift-grid {
    grid-template-columns: 1fr;
  }
  .ob-market-grid {
    grid-template-columns: 1fr;
  }
  .ob-exec-tape-track {
    animation-duration: 52s;
  }
  .ob-global-tape-track {
    animation-duration: 33s;
  }
  .ob-market-ticker-track {
    animation-duration: 30s;
  }
}
</style>
""",
        unsafe_allow_html=True,
    )


def _render_home_market_hero(ctrl_now: Dict[str, str], state_obj: Dict[str, Any], lock_info: Dict[str, Any]) -> None:
    drift_obj = state_obj.get("_drift_watch", {}) if isinstance(state_obj.get("_drift_watch"), dict) else {}
    gate_obj = drift_obj.get("gate", {}) if isinstance(drift_obj.get("gate"), dict) else {}
    drift_status = str(drift_obj.get("status", "UNKNOWN") or "UNKNOWN").upper()
    drift_status_ja = {
        "NORMAL": "正常",
        "ALERT": "警戒",
        "INSUFFICIENT": "判定保留",
        "UNKNOWN": "不明",
    }.get(drift_status, drift_status)
    badge_cls = {
        "NORMAL": "is-normal",
        "ALERT": "is-alert",
    }.get(drift_status, "is-wait")

    mode = "PAPER" if bval_str(ctrl_now.get("paper_mode")) else "LIVE"
    trade_enabled = "ON" if bval_str(ctrl_now.get("trade_enabled", "1")) else "OFF"
    auto_train = "ON" if bval_str(ctrl_now.get("ai_auto_train_enabled", "1")) else "OFF"
    risk_stop = "ON" if bval_str(state_obj.get("_risk_stop", "0")) else "OFF"
    streak_stop = "ON" if bval_str(state_obj.get("_streak_stop", "0")) else "OFF"
    lock_state = "ロック中" if bool(lock_info.get("locked")) else "解放"
    normal_streak = max(0, _safe_int(drift_obj.get("normal_streak", 0), 0))
    need_normals = max(1, _safe_int(gate_obj.get("resume_require_consecutive_normal", 1), 1))
    resume_ready = "復帰可" if bool(drift_obj.get("resume_ready")) else "様子見"
    updated_at = str(drift_obj.get("updated_at", "-") or "-")

    ticker_items = [
        f"モード {mode}",
        f"取引 {trade_enabled}",
        f"自動学習 {auto_train}",
        f"ドリフト {drift_status_ja}",
        f"復帰判定 {resume_ready}",
        f"実行ロック {lock_state}",
        f"リスク停止 {risk_stop}",
        f"連敗停止 {streak_stop}",
    ]
    ticker_text = "  ◆  ".join(ticker_items)
    ticker_html = html.escape(ticker_text)

    st.markdown(
        f"""
<div class="ob-market-hero">
  <div class="ob-market-head">
    <div>
      <span class="ob-market-title">マーケット・パルス</span>
      <span class="ob-market-subtitle">運用モニター</span>
    </div>
    <div class="ob-market-badge {badge_cls}">{html.escape(drift_status_ja)}</div>
  </div>
  <div class="ob-market-ticker">
    <div class="ob-market-ticker-track">{ticker_html}&nbsp;&nbsp;◆&nbsp;&nbsp;{ticker_html}</div>
  </div>
  <div class="ob-market-grid">
    <div class="ob-market-card">
      <div class="ob-market-card-label">執行状態</div>
      <div class="ob-market-card-value">{html.escape(mode)} / 取引 {html.escape(trade_enabled)}</div>
      <div class="ob-market-card-note">自動学習={html.escape(auto_train)} · ロック={html.escape(lock_state)}</div>
    </div>
    <div class="ob-market-card">
      <div class="ob-market-card-label">リスク体制</div>
      <div class="ob-market-card-value">リスク停止 {html.escape(risk_stop)} · 連敗停止 {html.escape(streak_stop)}</div>
      <div class="ob-market-card-note">連敗カウント={_safe_int(state_obj.get("_streak_consecutive_losses", 0), 0)}</div>
    </div>
    <div class="ob-market-card">
      <div class="ob-market-card-label">復帰ゲート</div>
      <div class="ob-market-card-value">{normal_streak}/{need_normals} 連続正常 · {html.escape(resume_ready)}</div>
      <div class="ob-market-card-note">更新時刻={html.escape(updated_at)}</div>
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_global_trade_strip(ctrl_now: Dict[str, str], state_obj: Dict[str, Any], lock_info: Dict[str, Any]) -> None:
    drift_obj = state_obj.get("_drift_watch", {}) if isinstance(state_obj.get("_drift_watch"), dict) else {}
    gate_obj = drift_obj.get("gate", {}) if isinstance(drift_obj.get("gate"), dict) else {}
    recent_obj = drift_obj.get("recent_metrics", {}) if isinstance(drift_obj.get("recent_metrics"), dict) else {}
    drift_status = str(drift_obj.get("status", "UNKNOWN") or "UNKNOWN").upper()
    status_text = {
        "NORMAL": "ドリフト正常",
        "ALERT": "ドリフト警戒",
        "INSUFFICIENT": "ドリフト判定保留",
        "UNKNOWN": "ドリフト不明",
    }.get(drift_status, f"ドリフト {drift_status}")
    status_class = {
        "NORMAL": "is-normal",
        "ALERT": "is-alert",
    }.get(drift_status, "is-wait")

    trade_enabled = bval_str(ctrl_now.get("trade_enabled", "1"))
    auto_train_enabled = bval_str(ctrl_now.get("ai_auto_train_enabled", "1"))
    paper_mode = bval_str(ctrl_now.get("paper_mode"))
    lock_active = bool(lock_info.get("locked"))

    pf = safe_float(recent_obj.get("profit_factor"))
    wr = safe_float(recent_obj.get("win_rate_pct"))
    avg_ret = safe_float(recent_obj.get("avg_ret_pct"))
    closed_n = max(0, _safe_int(recent_obj.get("closed_n", 0), 0))
    min_recent = max(1, _safe_int(gate_obj.get("min_recent_closed", 1), 1))

    normal_streak = max(0, _safe_int(drift_obj.get("normal_streak", 0), 0))
    need_normals = max(1, _safe_int(gate_obj.get("resume_require_consecutive_normal", 1), 1))
    resume_ready = bool(drift_obj.get("resume_ready"))
    updated_at = str(drift_obj.get("updated_at", "-") or "-")
    no_paper = _format_hours_for_status(ctrl_now.get("no_paper_hours", ""))

    pf_text = "-" if pf is None else f"{pf:.2f}"
    wr_text = "-" if wr is None else f"{wr:.2f}%"
    avg_text = "-" if avg_ret is None else f"{avg_ret:+.3f}%"
    pf_class = " is-positive" if pf is not None and pf >= 1.0 else (" is-negative" if pf is not None else "")
    avg_class = " is-positive" if avg_ret is not None and avg_ret >= 0.0 else (" is-negative" if avg_ret is not None else "")

    tape_items = [
        f"モード {'PAPER' if paper_mode else 'LIVE'}",
        f"取引 {'ON' if trade_enabled else 'OFF'}",
        f"自動学習 {'ON' if auto_train_enabled else 'OFF'}",
        status_text,
        f"直近決済 {closed_n}/{min_recent}",
        f"連続NORMAL {normal_streak}/{need_normals}",
        f"復帰 {'準備OK' if resume_ready else '保留'}",
        f"ロック {'ON' if lock_active else 'OFF'}",
        f"停止時間 {no_paper}",
    ]
    tape_text = "  |  ".join(tape_items)
    tape_html = html.escape(tape_text)

    st.markdown(
        f"""
<div class="ob-global-strip">
  <div class="ob-global-strip-head">
    <div class="ob-global-strip-title">ライブ・トレーディングデスク</div>
    <div class="ob-global-strip-time">drift更新: {html.escape(updated_at)}</div>
  </div>
  <div class="ob-global-strip-pills">
    <span class="ob-pill {status_class}">{html.escape(status_text)}</span>
    <span class="ob-pill {'is-on' if trade_enabled else 'is-off'}">取引 {'ON' if trade_enabled else 'OFF'}</span>
    <span class="ob-pill {'is-on' if auto_train_enabled else 'is-off'}">自動学習 {'ON' if auto_train_enabled else 'OFF'}</span>
    <span class="ob-pill {'is-on' if lock_active else 'is-off'}">実行ロック {'ON' if lock_active else 'OFF'}</span>
  </div>
  <div class="ob-global-tape">
    <div class="ob-global-tape-track">{tape_html}&nbsp;&nbsp;|&nbsp;&nbsp;{tape_html}</div>
  </div>
  <div class="ob-global-kpis">
    <div class="ob-global-kpi">
      <div class="ob-global-kpi-label">直近 PF</div>
      <div class="ob-global-kpi-value{pf_class}">{html.escape(pf_text)}</div>
    </div>
    <div class="ob-global-kpi">
      <div class="ob-global-kpi-label">勝率</div>
      <div class="ob-global-kpi-value">{html.escape(wr_text)}</div>
    </div>
    <div class="ob-global-kpi">
      <div class="ob-global-kpi-label">平均リターン</div>
      <div class="ob-global-kpi-value{avg_class}">{html.escape(avg_text)}</div>
    </div>
    <div class="ob-global-kpi">
      <div class="ob-global-kpi-label">サンプル</div>
      <div class="ob-global-kpi-value">{closed_n}/{min_recent}</div>
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _recent_log_days(logs_dir: Optional[Path], max_days: int = 3) -> List[str]:
    if not logs_dir:
        return []
    days = list_log_days(logs_dir)
    keep = max(1, int(max_days))
    return days[:keep]


def _build_execution_event_rows(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    out: List[Dict[str, Any]] = []
    for r in rows:
        td = pd.to_datetime(str(r.get("time", "")).strip(), errors="coerce")
        if pd.isna(td):
            continue
        result_raw = str(r.get("result", "")).strip()
        result = result_raw.upper()
        note = str(r.get("note", "")).strip()
        note_upper = note.upper()
        if result == "PAPER":
            event = "新規"
        elif result.startswith("PAPER_EXIT"):
            event = "決済"
        elif "MANUAL_FORCE_EXIT" in note_upper:
            event = "強制決済"
        else:
            continue

        exec_mode = _extract_note_kv(note, "exec").strip().upper()
        if exec_mode not in {"LIVE", "PAPER"}:
            if "EXEC=LIVE" in note_upper:
                exec_mode = "LIVE"
            elif "EXEC=PAPER" in note_upper:
                exec_mode = "PAPER"
            else:
                exec_mode = "-"

        out.append(
            {
                "time_dt": td,
                "event": event,
                "result": result_raw,
                "mode": exec_mode,
                "side": str(r.get("side", "")).strip().upper() or "-",
                "pos_id": str(r.get("pos_id", "")).strip(),
                "size": safe_float(r.get("size")),
                "ltp": safe_float(r.get("ltp")),
                "spread_pct": safe_float(r.get("spread_pct")),
                "note": note,
            }
        )
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out).sort_values("time_dt", ascending=False).reset_index(drop=True)
    df["time_short"] = pd.to_datetime(df["time_dt"], errors="coerce").dt.strftime("%m/%d %H:%M:%S")
    return df


def _render_execution_tape(rows: List[Dict[str, Any]], *, max_rows: int = 12) -> None:
    ev = _build_execution_event_rows(rows)
    if ev.empty:
        st.info("約定テープ: まだイベントがありません。")
        return

    clip = ev.head(max(6, int(max_rows))).copy()
    ticker_parts: List[str] = []
    for _, r in clip.iterrows():
        pid = str(r.get("pos_id", "") or "")
        pid_s = pid[:10] + "…" if len(pid) > 10 else pid
        ltp_txt = _fmt_float(safe_float(r.get("ltp")), 1)
        sz_txt = _fmt_float(safe_float(r.get("size")), 4)
        ticker_parts.append(
            f"{r.get('time_short', '-')} {r.get('event', '-')} {r.get('side', '-')} {r.get('mode', '-')} "
            f"pos={pid_s or '-'} size={sz_txt} ltp={ltp_txt}"
        )
    ticker_text = "  ◆  ".join(ticker_parts)
    ticker_html = html.escape(ticker_text)
    st.markdown(
        f"""
<div class="ob-exec-tape">
  <div class="ob-exec-tape-track">{ticker_html}&nbsp;&nbsp;◆&nbsp;&nbsp;{ticker_html}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    show_df = clip.copy()
    show_df["pos_id"] = show_df["pos_id"].astype(str).apply(lambda x: x[:12] + "…" if len(x) > 12 else x)
    show_df["size"] = pd.to_numeric(show_df["size"], errors="coerce").round(4)
    show_df["ltp"] = pd.to_numeric(show_df["ltp"], errors="coerce").round(1)
    show_df["spread_pct"] = pd.to_numeric(show_df["spread_pct"], errors="coerce").round(3)
    st.dataframe(
        show_df[["time_short", "event", "mode", "side", "pos_id", "size", "ltp", "spread_pct", "result"]]
        .rename(
            columns={
                "time_short": "時刻",
                "event": "イベント",
                "mode": "執行",
                "side": "方向",
                "pos_id": "pos_id",
                "size": "size",
                "ltp": "ltp",
                "spread_pct": "スプレッド(%)",
                "result": "結果",
            }
        ),
        width="stretch",
        hide_index=True,
    )


def _build_session_hourly_ladder(df_pos: pd.DataFrame, day8: str) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame]:
    if df_pos is None or df_pos.empty:
        return pd.DataFrame(), {}, pd.DataFrame()
    d = df_pos.copy()
    d["time_dt"] = pd.to_datetime(d.get("time_dt"), errors="coerce")
    d["ret_pct_est"] = pd.to_numeric(d.get("ret_pct_est"), errors="coerce")
    d["pnl_est"] = pd.to_numeric(d.get("pnl_est"), errors="coerce")
    d = d[d["status"].astype(str).str.upper() == "CLOSED"].copy()
    d = d.dropna(subset=["time_dt", "ret_pct_est"])
    if d.empty:
        return pd.DataFrame(), {}, pd.DataFrame()

    d["day8"] = d["time_dt"].dt.strftime("%Y%m%d")
    if re.fullmatch(r"\d{8}", str(day8 or "")):
        d = d[d["day8"] == str(day8)].copy()
    if d.empty:
        return pd.DataFrame(), {}, pd.DataFrame()

    d["hour"] = d["time_dt"].dt.hour
    hourly = (
        d.groupby("hour", dropna=False)
        .agg(
            trades=("pos_id", "count"),
            win_rate_pct=("ret_pct_est", lambda x: float((pd.to_numeric(x, errors="coerce") > 0).mean() * 100.0) if len(x) else 0.0),
            ret_pct_sum=("ret_pct_est", lambda x: float(pd.to_numeric(x, errors="coerce").fillna(0.0).sum())),
            pnl_est_sum=("pnl_est", lambda x: float(pd.to_numeric(x, errors="coerce").fillna(0.0).sum())),
        )
        .reset_index()
        .sort_values("hour")
        .reset_index(drop=True)
    )
    hourly["hour_label"] = hourly["hour"].astype(int).astype(str).str.zfill(2) + ":00"
    hourly["cum_pnl_est"] = hourly["pnl_est_sum"].cumsum()

    metrics = {
        "closed_n": int(len(d)),
        "win_rate_pct": float((d["ret_pct_est"] > 0).mean() * 100.0) if len(d) else 0.0,
        "ret_sum_pct": float(d["ret_pct_est"].sum()) if len(d) else 0.0,
        "pnl_sum": float(d["pnl_est"].fillna(0.0).sum()) if len(d) else 0.0,
        "loss_n": int((d["ret_pct_est"] < 0).sum()) if len(d) else 0,
    }
    return hourly, metrics, d


def _render_session_ladder_and_risk_budget(
    *,
    hourly: pd.DataFrame,
    metrics: Dict[str, Any],
    ctrl_now: Dict[str, str],
    state_obj: Dict[str, Any],
) -> None:
    if not metrics:
        st.info("セッション損益ラダー: この日の決済済みトレードがまだありません。")
        return

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("決済件数", int(metrics.get("closed_n", 0)))
    with m2:
        st.metric("勝率", f"{float(metrics.get('win_rate_pct', 0.0)):.2f}%")
    with m3:
        st.metric("ret_sum(推定)", f"{float(metrics.get('ret_sum_pct', 0.0)):+.3f}%")
    with m4:
        st.metric("PnL(推定)", f"{float(metrics.get('pnl_sum', 0.0)):+,.4f}")

    if not hourly.empty:
        if HAS_PLOTLY:
            fig = go.Figure()
            colors = np.where(pd.to_numeric(hourly["pnl_est_sum"], errors="coerce").fillna(0.0) >= 0, "#22c55e", "#ef4444")
            fig.add_trace(
                go.Bar(
                    x=hourly["hour_label"],
                    y=hourly["pnl_est_sum"],
                    name="hourly pnl_est",
                    marker_color=colors,
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=hourly["hour_label"],
                    y=hourly["cum_pnl_est"],
                    mode="lines+markers",
                    name="cum pnl_est",
                    line=dict(color="#38bdf8", width=2),
                    yaxis="y2",
                )
            )
            fig.update_layout(
                title="セッション損益ラダー（時間帯別 + 累積）",
                xaxis_title="時間帯",
                yaxis_title="時間帯PnL(推定)",
                yaxis2=dict(title="累積PnL(推定)", overlaying="y", side="right", showgrid=False),
                legend=dict(orientation="h"),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=10, r=10, t=48, b=10),
            )
            st.plotly_chart(fig, width="stretch")
        else:
            line = hourly.set_index("hour_label")[["cum_pnl_est"]].copy()
            line.columns = ["cum pnl_est"]
            st.line_chart(line)

    daily_loss_limit = safe_float(ctrl_now.get("daily_loss_limit_pct"))
    realized_ret = float(metrics.get("ret_sum_pct", 0.0))
    risk_stop_on = bval_str(state_obj.get("_risk_stop", "0"))
    if daily_loss_limit is None or daily_loss_limit >= 0:
        st.warning("リスク予算ゲージ: `daily_loss_limit_pct` が未設定または不正です（負値が必要）。")
        return

    budget_abs = abs(float(daily_loss_limit))
    realized_loss_abs = abs(min(0.0, realized_ret))
    used_pct = (realized_loss_abs / budget_abs * 100.0) if budget_abs > 1e-12 else 0.0
    remaining_pct = budget_abs - realized_loss_abs

    g1, g2 = st.columns([2, 1])
    with g1:
        if HAS_PLOTLY:
            axis_max = max(120.0, min(300.0, max(used_pct * 1.15, 120.0)))
            fig_g = go.Figure(
                go.Indicator(
                    mode="gauge+number",
                    value=float(used_pct),
                    number={"suffix": "%"},
                    title={"text": "損失予算の消費率"},
                    gauge={
                        "axis": {"range": [0, axis_max]},
                        "bar": {"color": "#ef4444" if used_pct >= 100.0 else "#22c55e"},
                        "steps": [
                            {"range": [0, 70], "color": "rgba(34,197,94,0.20)"},
                            {"range": [70, 100], "color": "rgba(250,204,21,0.22)"},
                            {"range": [100, axis_max], "color": "rgba(239,68,68,0.24)"},
                        ],
                        "threshold": {"line": {"color": "#f59e0b", "width": 3}, "value": 100},
                    },
                )
            )
            fig_g.update_layout(margin=dict(l=10, r=10, t=40, b=10), paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_g, width="stretch")
        else:
            st.progress(max(0.0, min(1.0, float(used_pct / 100.0))))
            st.caption(f"消費率={used_pct:.1f}%")
    with g2:
        st.metric("日次損失上限(%)", f"{daily_loss_limit:.3f}%")
        st.metric("損失使用量(%)", f"{realized_loss_abs:.3f}%")
        st.metric("残り予算(%)", f"{remaining_pct:+.3f}%")
        st.metric("risk_stop", "ON" if risk_stop_on else "OFF")


def _render_drift_recovery_timeline(state_obj: Dict[str, Any]) -> None:
    drift_obj = state_obj.get("_drift_watch", {}) if isinstance(state_obj.get("_drift_watch"), dict) else {}
    if not drift_obj:
        st.info("ドリフト復帰タイムライン: データがまだありません。")
        return

    gate = drift_obj.get("gate", {}) if isinstance(drift_obj.get("gate"), dict) else {}
    recent = drift_obj.get("recent_metrics", {}) if isinstance(drift_obj.get("recent_metrics"), dict) else {}

    closed_n = max(0, _safe_int(recent.get("closed_n", 0), 0))
    min_recent = max(1, _safe_int(gate.get("min_recent_closed", 1), 1))
    normal_streak = max(0, _safe_int(drift_obj.get("normal_streak", 0), 0))
    need_normals = max(1, _safe_int(gate.get("resume_require_consecutive_normal", 1), 1))
    canary_streak = max(0, _safe_int(drift_obj.get("canary_streak", 0), 0))
    need_canary = max(0, _safe_int(gate.get("resume_canary_runs", 0), 0))
    resume_ready = bool(drift_obj.get("resume_ready"))
    canary_ready = bool(drift_obj.get("canary_ready"))
    status = str(drift_obj.get("status", "-")).upper()

    canary_target = need_canary if need_canary > 0 else 1
    canary_cur = canary_streak if need_canary > 0 else 1
    canary_done = canary_cur >= canary_target
    resume_done = bool(resume_ready and (need_canary <= 0 or canary_ready))

    steps = [
        {"name": "サンプルゲート", "cur": closed_n, "target": min_recent, "done": closed_n >= min_recent},
        {"name": "連続NORMAL", "cur": normal_streak, "target": need_normals, "done": normal_streak >= need_normals},
        {"name": "カナリー実行", "cur": canary_cur, "target": canary_target, "done": canary_done},
        {"name": "自動復帰", "cur": 1 if resume_done else 0, "target": 1, "done": resume_done},
    ]

    cards: List[str] = []
    for s in steps:
        cur = int(max(0, _safe_int(s.get("cur"), 0)))
        tgt = int(max(1, _safe_int(s.get("target"), 1)))
        pct = max(0, min(100, int(round(cur / float(tgt) * 100.0))))
        if bool(s.get("done")):
            cls = "is-done"
            state_txt = "完了"
        elif cur > 0:
            cls = "is-active"
            state_txt = "進行中"
        else:
            cls = "is-pending"
            state_txt = "待機"
        cards.append(
            f"""
<div class="ob-drift-step {cls}">
  <div class="ob-drift-step-head">
    <div class="ob-drift-step-name">{html.escape(str(s.get('name', '-')))}</div>
    <div class="ob-drift-step-value">{cur}/{tgt} · {state_txt}</div>
  </div>
  <div class="ob-drift-bar"><span style="width:{pct}%"></span></div>
</div>
"""
        )
    st.markdown(f"<div class='ob-drift-grid'>{''.join(cards)}</div>", unsafe_allow_html=True)
    st.caption(
        "status={} / resume_ready={} / canary_ready={} / insufficient_streak={} / relax_count={} / risk_tightened_by_drift={}".format(
            status,
            "ON" if resume_ready else "OFF",
            "ON" if canary_ready else "OFF",
            _safe_int(drift_obj.get("insufficient_streak", 0), 0),
            _safe_int(drift_obj.get("insufficient_relax_count", 0), 0),
            "ON" if bval_str(drift_obj.get("risk_tightened_by_drift", False)) else "OFF",
        )
    )


def _render_incident_replay(rows: List[Dict[str, Any]], df_pos: pd.DataFrame) -> None:
    if df_pos is None or df_pos.empty:
        st.info("インシデント再現: 対象データがありません。")
        return

    d = df_pos.copy()
    d["ret_pct_est"] = pd.to_numeric(d.get("ret_pct_est"), errors="coerce")
    d["pnl_est"] = pd.to_numeric(d.get("pnl_est"), errors="coerce")
    d["time_dt"] = pd.to_datetime(d.get("time_dt"), errors="coerce")
    d = d[(d["status"].astype(str).str.upper() == "CLOSED") & (d["ret_pct_est"] < 0)].copy()
    if d.empty:
        st.info("インシデント再現: 直近の負けトレードがまだありません。")
        return

    d = d.sort_values("time_dt", ascending=False).drop_duplicates(subset=["pos_id"], keep="first").head(40)
    if d.empty:
        st.info("インシデント再現: 対象の `pos_id` が見つかりません。")
        return

    d["label"] = d.apply(
        lambda x: (
            f"{pd.to_datetime(x.get('time_dt'), errors='coerce').strftime('%m/%d %H:%M') if not pd.isna(pd.to_datetime(x.get('time_dt'), errors='coerce')) else '-'}"
            f" | {str(x.get('pos_id', '-'))}"
            f" | 損益率={float(x.get('ret_pct_est', 0.0)):+.3f}%"
            f" | 損益={float(x.get('pnl_est', 0.0)):+.4f}"
            f" | {str(x.get('trend', '-'))}/{str(x.get('signal', '-'))}"
        ),
        axis=1,
    )

    pid_options = d["pos_id"].astype(str).tolist()
    label_map = {str(r["pos_id"]): str(r["label"]) for _, r in d.iterrows()}
    selected_pid = st.selectbox(
        "負けトレードを選択",
        pid_options,
        format_func=lambda x: label_map.get(str(x), str(x)),
        key="home_incident_replay_pid",
    )

    row = d[d["pos_id"].astype(str) == str(selected_pid)].head(1)
    if row.empty:
        return
    sel = row.iloc[0]

    i1, i2, i3, i4 = st.columns(4)
    with i1:
        st.metric("ret(推定)", f"{float(sel.get('ret_pct_est', 0.0)):+.3f}%")
    with i2:
        st.metric("pnl(推定)", f"{float(sel.get('pnl_est', 0.0)):+,.4f}")
    with i3:
        st.metric("trend/signal", f"{str(sel.get('trend', '-'))}/{str(sel.get('signal', '-'))}")
    with i4:
        st.metric("決済結果", str(sel.get("exit_result", "-")))

    key_suffix = hashlib.sha1(str(selected_pid).encode("utf-8")).hexdigest()[:8]
    b1, b2 = st.columns(2)
    with b1:
        if st.button("🧩 pos_idタブで開く", width="stretch", key=f"home_incident_jump_pos_{key_suffix}"):
            st.session_state["pos_search"] = str(selected_pid)
            st.session_state["_sidebar_tab_jump_key"] = "pos"
            st.rerun()
    with b2:
        if st.button("📝 履歴タブで開く", width="stretch", key=f"home_incident_jump_hist_{key_suffix}"):
            st.session_state["history_keyword"] = str(selected_pid)
            st.session_state["_sidebar_tab_jump_key"] = "history"
            st.rerun()

    rr = [r for r in rows if str(r.get("pos_id", "")).strip() == str(selected_pid)]
    rr = sorted(rr, key=lambda x: str(x.get("time", "")))
    if not rr:
        st.caption("この `pos_id` のrawログが見つかりません。")
        return

    rep_rows: List[Dict[str, Any]] = []
    for r in rr:
        rep_rows.append(
            {
                "time": str(r.get("time", "")),
                "result": str(r.get("result", "")),
                "side": str(r.get("side", "")),
                "price": safe_float(r.get("price")),
                "ltp": safe_float(r.get("ltp")),
                "size": safe_float(r.get("size")),
                "spread_pct": safe_float(r.get("spread_pct")),
                "note": _shorten_for_log(r.get("note", ""), 120),
            }
        )
    rdf = pd.DataFrame(rep_rows)
    for col, nd in [("price", 1), ("ltp", 1), ("size", 4), ("spread_pct", 3)]:
        if col in rdf.columns:
            rdf[col] = pd.to_numeric(rdf[col], errors="coerce").round(nd)
    st.dataframe(rdf, width="stretch", hide_index=True)


def _activate_tab_via_js(tab_index: int) -> None:
    idx = max(0, int(tab_index))
    components.html(
        f"""
<script>
const target = {idx};
let tried = 0;
function jumpTab() {{
  const doc = window.parent && window.parent.document ? window.parent.document : document;
  const tabs = doc.querySelectorAll('div[data-testid="stTabs"] button[role="tab"]');
  if (tabs && tabs.length > target) {{
    tabs[target].scrollIntoView({{behavior: "smooth", block: "nearest", inline: "center"}});
    tabs[target].click();
    return;
  }}
  tried += 1;
  if (tried < 25) {{
    setTimeout(jumpTab, 120);
  }}
}}
setTimeout(jumpTab, 80);
</script>
""",
        height=0,
    )


# =========================
# Paths
# =========================
def get_main_dir() -> Path:
    return Path(__file__).resolve().parent


def ui_config_path(main_dir: Path) -> Path:
    return main_dir / ".streamlit" / "dashboard_ui.json"


def dashboard_change_log_path(main_dir: Path) -> Path:
    return main_dir / ".streamlit" / "dashboard_change_log.jsonl"


def dashboard_change_state_path(main_dir: Path) -> Path:
    return main_dir / ".streamlit" / "dashboard_change_state.json"


def dashboard_login_audit_path(main_dir: Path) -> Path:
    return main_dir / ".streamlit" / "dashboard_login_audit.jsonl"


def _append_dashboard_change_log(main_dir: Path, row: Dict[str, Any]) -> Tuple[bool, str]:
    p = dashboard_change_log_path(main_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True, str(p)
    except Exception as e:
        return False, str(e)


def _read_dashboard_change_log(main_dir: Path, max_rows: int = 200) -> List[Dict[str, Any]]:
    p = dashboard_change_log_path(main_dir)
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    for ln in lines[-max(1, int(max_rows)) :]:
        s = str(ln).strip()
        if not s:
            continue
        try:
            x = json.loads(s)
        except Exception:
            continue
        if isinstance(x, dict):
            out.append(x)
    out.reverse()
    return out


def _append_login_audit_log(main_dir: Path, row: Dict[str, Any]) -> Tuple[bool, str]:
    p = dashboard_login_audit_path(main_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        try:
            os.chmod(p, 0o600)
        except Exception:
            pass
        return True, str(p)
    except Exception as e:
        return False, str(e)


def _read_login_audit_log(main_dir: Path, max_rows: int = 300) -> List[Dict[str, Any]]:
    p = dashboard_login_audit_path(main_dir)
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    for ln in lines[-max(1, int(max_rows)) :]:
        s = str(ln).strip()
        if not s:
            continue
        try:
            x = json.loads(s)
        except Exception:
            continue
        if isinstance(x, dict):
            out.append(x)
    out.reverse()
    return out


@st.cache_data(show_spinner=False, ttl=15)
def _git_snapshot(main_dir: Path) -> Dict[str, Any]:
    out = {"branch": "-", "commit": "-", "dirty_files": 0, "dirty_sig": "clean"}
    try:
        p1 = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=main_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4,
        )
        if p1.returncode == 0:
            out["branch"] = str((p1.stdout or "").strip() or "-")
    except Exception:
        pass
    try:
        p2 = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=main_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4,
        )
        if p2.returncode == 0:
            out["commit"] = str((p2.stdout or "").strip() or "-")
    except Exception:
        pass
    try:
        p3 = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=main_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4,
        )
        if p3.returncode == 0:
            dirty_lines = [x for x in (p3.stdout or "").splitlines() if x.strip()]
            out["dirty_files"] = int(len(dirty_lines))
            sig_src = "\n".join(dirty_lines).encode("utf-8", errors="ignore")
            out["dirty_sig"] = hashlib.sha256(sig_src).hexdigest()[:12] if dirty_lines else "clean"
    except Exception:
        pass
    return out


def _auto_record_version_or_commit(main_dir: Path) -> None:
    st_path = dashboard_change_state_path(main_dir)
    st_data = _read_json_dict(st_path, default={})
    git_now = _git_snapshot(main_dir)
    cur_version = str(APP_VERSION)
    cur_commit = str(git_now.get("commit", "-"))
    cur_dirty_sig = str(git_now.get("dirty_sig", "clean"))
    last_version = str(st_data.get("last_version", ""))
    last_commit = str(st_data.get("last_commit", ""))
    last_dirty_sig = str(st_data.get("last_dirty_sig", ""))

    if cur_version == last_version and cur_commit == last_commit and cur_dirty_sig == last_dirty_sig:
        return

    if cur_version != last_version:
        change_type = "AUTO_VERSION"
    elif cur_commit != last_commit:
        change_type = "AUTO_COMMIT"
    else:
        change_type = "AUTO_DIRTY"

    row = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": cur_version,
        "type": change_type,
        "author": "system",
        "summary": (
            f"auto snapshot: version={cur_version} commit={cur_commit} "
            f"dirty={int(git_now.get('dirty_files', 0))} sig={cur_dirty_sig}"
        ),
        "files": [],
        "git_branch": str(git_now.get("branch", "-")),
        "git_commit": cur_commit,
        "git_dirty_files": int(git_now.get("dirty_files", 0)),
        "git_dirty_sig": cur_dirty_sig,
    }
    _append_dashboard_change_log(main_dir, row)
    _write_json_dict(
        st_path,
        {
            "last_version": cur_version,
            "last_commit": cur_commit,
            "last_dirty_sig": cur_dirty_sig,
            "last_dirty_files": int(git_now.get("dirty_files", 0)),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


def find_logs_dir(main_dir: Path) -> Optional[Path]:
    cands = [
        main_dir / "logs",
        main_dir.parent / "logs",
        Path("./logs").resolve(),
        Path("../logs").resolve(),
    ]
    for p in cands:
        try:
            if p.exists() and any(p.glob("trade_log_*.csv")):
                return p
        except Exception:
            pass
    return None


def find_control_csv(main_dir: Path) -> Path:
    cands = [
        main_dir / "CONTROL.csv",
        main_dir.parent / "CONTROL.csv",
        main_dir / "control" / "CONTROL.csv",
    ]
    for p in cands:
        if p.exists():
            return p
    return main_dir / "CONTROL.csv"


def find_state_json(main_dir: Path) -> Path:
    return main_dir / "state.json"


def daily_report_out_dir(main_dir: Path) -> Path:
    return main_dir / "daily_report_out"


def run_lock_dir(main_dir: Path) -> Path:
    return main_dir / ".run_lock"


# =========================
# Dashboard Auth
# =========================
AUTH_SESSION_KEY = "_dashboard_auth"
AUTH_NOTIFY_SENT_KEY = "_dashboard_auth_notify_sent"
AUTH_LOCAL_TOKEN_COOKIE_KEY = "ob_dash_auth"
AUTH_LEGACY_QUERY_TOKEN_KEY = "auth_token"
AUTH_LOCAL_TOKEN_MAX_ENTRIES = 128
AUTH_DEFAULT: Dict[str, Any] = {
    "enabled": True,
    "mode": "AUTO",  # LOCAL / OIDC / AUTO
    "oidc_provider": "apple",
    "session_timeout_min": 30,
    "max_failures": 5,
    "lock_minutes": 10,
    "remember_local_login": True,
    "allow_breakglass_in_auto": True,
    "breakglass_daily_limit": 3,
    "users": [],
}


def auth_config_path(main_dir: Path) -> Path:
    return main_dir / ".streamlit" / "dashboard_auth.json"


def auth_lock_path(main_dir: Path) -> Path:
    return main_dir / ".streamlit" / "dashboard_auth_lock.json"


def auth_tokens_path(main_dir: Path) -> Path:
    return main_dir / ".streamlit" / "dashboard_auth_tokens.json"


def auth_breakglass_path(main_dir: Path) -> Path:
    return main_dir / ".streamlit" / "dashboard_auth_breakglass.json"


def _auth_safe_int(v: Any, default: int) -> int:
    try:
        return int(float(str(v).strip()))
    except Exception:
        return default


def _auth_safe_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "on", "y"}:
        return True
    if s in {"0", "false", "no", "off", "n"}:
        return False
    return default


def _auth_mode_norm(v: Any) -> str:
    s = str(v or "").strip().upper()
    if s in {"LOCAL", "OIDC", "AUTO"}:
        return s
    if s in {"APPLE", "APPLE_OIDC"}:
        return "OIDC"
    return "AUTO"


def _read_json_dict(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = dict(default or {})
    if not path.exists():
        return base
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            base.update(data)
    except Exception:
        return base
    return base


def _write_json_dict(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _load_auth_config(main_dir: Path) -> Dict[str, Any]:
    cfg = _read_json_dict(auth_config_path(main_dir), AUTH_DEFAULT)
    users = cfg.get("users")
    if not isinstance(users, list):
        users = []
    cfg["users"] = [u for u in users if isinstance(u, dict)]
    cfg["enabled"] = _auth_safe_bool(cfg.get("enabled", True), True)
    cfg["mode"] = _auth_mode_norm(cfg.get("mode", "AUTO"))
    cfg["oidc_provider"] = str(cfg.get("oidc_provider", "apple") or "apple").strip()
    cfg["session_timeout_min"] = max(5, _auth_safe_int(cfg.get("session_timeout_min", 30), 30))
    cfg["max_failures"] = max(1, _auth_safe_int(cfg.get("max_failures", 5), 5))
    cfg["lock_minutes"] = max(1, _auth_safe_int(cfg.get("lock_minutes", 10), 10))
    cfg["remember_local_login"] = _auth_safe_bool(cfg.get("remember_local_login", True), True)
    cfg["allow_breakglass_in_auto"] = _auth_safe_bool(cfg.get("allow_breakglass_in_auto", True), True)
    cfg["breakglass_daily_limit"] = max(1, _auth_safe_int(cfg.get("breakglass_daily_limit", 3), 3))
    return cfg


def _load_auth_lock(main_dir: Path) -> Dict[str, Any]:
    return _read_json_dict(
        auth_lock_path(main_dir),
        {"failed_count": 0, "lock_until": 0.0, "last_failed_at": ""},
    )


def _save_auth_lock(main_dir: Path, lock: Dict[str, Any]) -> None:
    _write_json_dict(auth_lock_path(main_dir), lock)


def _clear_auth_lock(main_dir: Path) -> None:
    _save_auth_lock(main_dir, {"failed_count": 0, "lock_until": 0.0, "last_failed_at": ""})


def _auth_token_hash(raw_token: str) -> str:
    return hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()


def _auth_client_fingerprint() -> str:
    ua = ""
    xff = ""
    rip = ""
    try:
        headers = getattr(st.context, "headers", {})
        if hasattr(headers, "get"):
            ua = str(headers.get("user-agent", "") or headers.get("User-Agent", "")).strip()
            xff = str(headers.get("x-forwarded-for", "") or headers.get("X-Forwarded-For", "")).strip()
            rip = str(headers.get("x-real-ip", "") or headers.get("X-Real-Ip", "")).strip()
    except Exception:
        pass
    src = f"{ua}|{xff}|{rip}"
    if not src.strip():
        return ""
    return hashlib.sha256(src.encode("utf-8")).hexdigest()


def _auth_cookie_get() -> str:
    # Prefer Streamlit cookie context.
    try:
        cookies = getattr(st.context, "cookies", {})
        if hasattr(cookies, "get"):
            raw = cookies.get(AUTH_LOCAL_TOKEN_COOKIE_KEY, "")
            s = str(raw or "").strip()
            if s:
                return urllib.parse.unquote(s)
    except Exception:
        pass

    # Fallback: parse Cookie header.
    try:
        headers = getattr(st.context, "headers", {})
        cookie_hdr = ""
        if hasattr(headers, "get"):
            cookie_hdr = str(headers.get("cookie", "") or headers.get("Cookie", "")).strip()
        if not cookie_hdr:
            return ""
        for seg in cookie_hdr.split(";"):
            kv = seg.strip()
            if not kv or "=" not in kv:
                continue
            k, v = kv.split("=", 1)
            if k.strip() == AUTH_LOCAL_TOKEN_COOKIE_KEY:
                return urllib.parse.unquote(str(v or "").strip())
    except Exception:
        pass
    return ""


def _auth_is_https_request() -> bool:
    try:
        headers = getattr(st.context, "headers", {})
        if hasattr(headers, "get"):
            proto = str(headers.get("x-forwarded-proto", "") or headers.get("X-Forwarded-Proto", "")).strip().lower()
            if proto:
                return proto.startswith("https")
            fproto = str(headers.get("x-scheme", "") or headers.get("X-Scheme", "")).strip().lower()
            if fproto:
                return fproto.startswith("https")
            referer = str(headers.get("referer", "") or headers.get("Referer", "")).strip().lower()
            if referer.startswith("https://"):
                return True
    except Exception:
        pass
    return False


def _auth_cookie_set(token: str, max_age_sec: int) -> None:
    s = str(token or "").strip()
    if not s:
        return
    max_age = max(60, int(max_age_sec))
    secure_attr = "; Secure" if _auth_is_https_request() else ""
    enc = urllib.parse.quote(s, safe="")
    js = f"""
<script>
(function() {{
  var name = {json.dumps(AUTH_LOCAL_TOKEN_COOKIE_KEY)};
  var val = {json.dumps(enc)};
  var maxAge = {int(max_age)};
  document.cookie = name + "=" + val + "; Path=/; Max-Age=" + maxAge + "; SameSite=Strict{secure_attr}";
}})();
</script>
""".strip()
    try:
        components.html(js, height=0)
    except Exception:
        pass


def _auth_cookie_clear() -> None:
    secure_attr = "; Secure" if _auth_is_https_request() else ""
    js = f"""
<script>
(function() {{
  var name = {json.dumps(AUTH_LOCAL_TOKEN_COOKIE_KEY)};
  document.cookie = name + "=; Path=/; Max-Age=0; SameSite=Strict{secure_attr}";
}})();
</script>
""".strip()
    try:
        components.html(js, height=0)
    except Exception:
        pass


def _auth_cleanup_legacy_query_token() -> None:
    try:
        qp = st.query_params
        if AUTH_LEGACY_QUERY_TOKEN_KEY in qp:
            del qp[AUTH_LEGACY_QUERY_TOKEN_KEY]
    except Exception:
        pass


def _auth_load_tokens(main_dir: Path) -> List[Dict[str, Any]]:
    obj = _read_json_dict(auth_tokens_path(main_dir), {"tokens": []})
    toks = obj.get("tokens")
    if not isinstance(toks, list):
        return []
    return [x for x in toks if isinstance(x, dict)]


def _auth_save_tokens(main_dir: Path, tokens: List[Dict[str, Any]]) -> None:
    _write_json_dict(auth_tokens_path(main_dir), {"tokens": tokens})


def _auth_prune_tokens(tokens: List[Dict[str, Any]], now_ts: float) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for x in tokens:
        try:
            h = str(x.get("token_hash", "")).strip()
            exp = float(x.get("expires_at", 0.0) or 0.0)
        except Exception:
            continue
        if not h or exp <= now_ts:
            continue
        out.append(dict(x))
    out.sort(key=lambda z: float(z.get("last_seen", 0.0) or 0.0), reverse=True)
    return out[:AUTH_LOCAL_TOKEN_MAX_ENTRIES]


def _auth_issue_local_token(main_dir: Path, sess: Dict[str, Any], now_ts: float, ttl_sec: int) -> str:
    token = secrets.token_urlsafe(32)
    tokens = _auth_prune_tokens(_auth_load_tokens(main_dir), now_ts)
    tokens.append(
        {
            "token_hash": _auth_token_hash(token),
            "username": str(sess.get("username", "")).strip(),
            "email": str(sess.get("email", "")).strip(),
            "auth_type": str(sess.get("auth_type", "LOCAL")).strip() or "LOCAL",
            "fingerprint": _auth_client_fingerprint(),
            "issued_at": now_ts,
            "last_seen": now_ts,
            "expires_at": now_ts + max(60, int(ttl_sec)),
        }
    )
    _auth_save_tokens(main_dir, _auth_prune_tokens(tokens, now_ts))
    return token


def _auth_touch_local_token(main_dir: Path, token: str, now_ts: float, ttl_sec: int) -> bool:
    raw = str(token or "").strip()
    if not raw:
        return False
    h = _auth_token_hash(raw)
    cur_fp = _auth_client_fingerprint()
    tokens = _auth_prune_tokens(_auth_load_tokens(main_dir), now_ts)
    changed = False
    for x in tokens:
        if str(x.get("token_hash", "")).strip() != h:
            continue
        saved_fp = str(x.get("fingerprint", "")).strip()
        if saved_fp and cur_fp and saved_fp != cur_fp:
            return False
        x["last_seen"] = now_ts
        x["expires_at"] = now_ts + max(60, int(ttl_sec))
        changed = True
        break
    if changed:
        _auth_save_tokens(main_dir, _auth_prune_tokens(tokens, now_ts))
    return changed


def _auth_revoke_local_token(main_dir: Path, token: str, now_ts: Optional[float] = None) -> None:
    raw = str(token or "").strip()
    if not raw:
        return
    tnow = float(now_ts if now_ts is not None else time.time())
    h = _auth_token_hash(raw)
    tokens = _auth_prune_tokens(_auth_load_tokens(main_dir), tnow)
    tokens = [x for x in tokens if str(x.get("token_hash", "")).strip() != h]
    _auth_save_tokens(main_dir, tokens)


def _auth_restore_local_token(main_dir: Path, raw_token: str, now_ts: float, ttl_sec: int) -> Optional[Dict[str, Any]]:
    raw = str(raw_token or "").strip()
    if not raw:
        return None
    h = _auth_token_hash(raw)
    cur_fp = _auth_client_fingerprint()
    tokens = _auth_prune_tokens(_auth_load_tokens(main_dir), now_ts)
    found: Optional[Dict[str, Any]] = None
    new_tokens: List[Dict[str, Any]] = []
    for x in tokens:
        if str(x.get("token_hash", "")).strip() == h:
            found = dict(x)
            continue
        new_tokens.append(dict(x))
    if not found:
        _auth_save_tokens(main_dir, new_tokens)
        return None
    saved_fp = str(found.get("fingerprint", "")).strip()
    if saved_fp and cur_fp and saved_fp != cur_fp:
        _auth_save_tokens(main_dir, new_tokens)
        return None
    found["last_seen"] = now_ts
    found["expires_at"] = now_ts + max(60, int(ttl_sec))
    new_tokens.append(found)
    _auth_save_tokens(main_dir, _auth_prune_tokens(new_tokens, now_ts))
    return {
        "ok": True,
        "username": str(found.get("username", "")).strip() or "local-user",
        "email": str(found.get("email", "")).strip(),
        "auth_type": str(found.get("auth_type", "LOCAL")).strip() or "LOCAL",
        "login_at": float(found.get("issued_at", now_ts) or now_ts),
        "last_seen": now_ts,
    }


def _st_secrets_get(path: List[str], default: Any = None) -> Any:
    try:
        cur: Any = st.secrets
        for p in path:
            try:
                cur = cur[p]
            except Exception:
                return default
        return cur
    except Exception:
        return default


def _dashboard_security_dict() -> Dict[str, Any]:
    sec = _st_secrets_get(["dashboard_security"], {})
    try:
        return dict(sec)
    except Exception:
        return {}


def _dashboard_branding_dict() -> Dict[str, Any]:
    sec = _st_secrets_get(["dashboard_branding"], {})
    try:
        return dict(sec)
    except Exception:
        return {}


def _image_mime_from_path(p: Path) -> str:
    ext = p.suffix.lower()
    if ext == ".png":
        return "image/png"
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".webp":
        return "image/webp"
    if ext == ".ico":
        return "image/x-icon"
    if ext == ".svg":
        return "image/svg+xml"
    return "application/octet-stream"


def _resolve_apple_touch_icon_href(main_dir: Path) -> str:
    brand = _dashboard_branding_dict()
    url = str(
        brand.get("apple_touch_icon_url", brand.get("icon_url", ""))
    ).strip()
    if url:
        return url

    raw_path = str(
        brand.get("apple_touch_icon_path", brand.get("icon_path", ""))
    ).strip()
    candidates: List[Path] = []
    if raw_path:
        p = Path(raw_path)
        candidates.append(p if p.is_absolute() else (main_dir / p))
    else:
        candidates.extend(
            [
                main_dir / ".streamlit" / "assets" / "apple-touch-icon.png",
                main_dir / ".streamlit" / "assets" / "dashboard_icon.png",
                main_dir / ".streamlit" / "assets" / "icon.png",
            ]
        )

    for p in candidates:
        try:
            if not p.exists() or not p.is_file():
                continue
            b = p.read_bytes()
            if not b:
                continue
            mime = _image_mime_from_path(p)
            b64 = base64.b64encode(b).decode("ascii")
            return f"data:{mime};base64,{b64}"
        except Exception:
            continue
    return ""


def _inject_mobile_app_icon(main_dir: Path) -> None:
    href = _resolve_apple_touch_icon_href(main_dir)
    if not href:
        return
    brand = _dashboard_branding_dict()
    app_title = str(brand.get("apple_mobile_web_app_title", APP_NAME)).strip() or APP_NAME
    href_js = json.dumps(href, ensure_ascii=False)
    title_js = json.dumps(app_title, ensure_ascii=False)
    components.html(
        f"""
<script>
const doc = (window.parent && window.parent.document) ? window.parent.document : document;
const head = doc.head || doc.getElementsByTagName("head")[0];
const iconHref = {href_js};
const appTitle = {title_js};
if (head && iconHref) {{
  function setLink(rel, href, sizes) {{
    let el = head.querySelector(`link[rel="${{rel}}"]`);
    if (!el) {{
      el = doc.createElement("link");
      el.setAttribute("rel", rel);
      head.appendChild(el);
    }}
    el.setAttribute("href", href);
    if (sizes) {{
      el.setAttribute("sizes", sizes);
    }}
  }}
  function setMeta(name, content) {{
    let el = head.querySelector(`meta[name="${{name}}"]`);
    if (!el) {{
      el = doc.createElement("meta");
      el.setAttribute("name", name);
      head.appendChild(el);
    }}
    el.setAttribute("content", content);
  }}
  setLink("apple-touch-icon", iconHref, "180x180");
  setLink("icon", iconHref, null);
  setMeta("apple-mobile-web-app-capable", "yes");
  setMeta("apple-mobile-web-app-title", appTitle);
}}
</script>
""",
        height=0,
    )


def _parse_security_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        out: List[str] = []
        for x in v:
            s = str(x).strip()
            if s:
                out.append(s)
        return out
    s0 = str(v).strip()
    if not s0:
        return []
    # Accept JSON style list string.
    if s0.startswith("[") and s0.endswith("]"):
        try:
            j = json.loads(s0)
            if isinstance(j, list):
                return [str(x).strip() for x in j if str(x).strip()]
        except Exception:
            pass
    arr = re.split(r"[,\n;]", s0)
    return [str(x).strip() for x in arr if str(x).strip()]


def _auth_oidc_allowlist_decision(email: str) -> Tuple[bool, str]:
    sec_d = _dashboard_security_dict()
    allowed_emails = {
        str(x).strip().lower()
        for x in _parse_security_list(sec_d.get("allowed_emails", sec_d.get("oidc_allowed_emails", [])))
        if str(x).strip()
    }
    allowed_domains = {
        str(x).strip().lower().lstrip("@")
        for x in _parse_security_list(sec_d.get("allowed_email_domains", sec_d.get("oidc_allowed_domains", [])))
        if str(x).strip()
    }
    if not allowed_emails and not allowed_domains:
        return True, "allow_all"

    email_l = str(email or "").strip().lower()
    if not email_l:
        return False, "email_missing"
    if email_l in allowed_emails:
        return True, "email_match"
    if "@" in email_l:
        dom = email_l.rsplit("@", 1)[-1]
        if dom in allowed_domains:
            return True, "domain_match"
    return False, "allowlist_miss"


def _auth_request_meta() -> Dict[str, str]:
    ua = ""
    xff = ""
    rip = ""
    ip = ""
    try:
        headers = getattr(st.context, "headers", {})
        if hasattr(headers, "get"):
            ua = str(headers.get("user-agent", "") or headers.get("User-Agent", "")).strip()
            xff = str(headers.get("x-forwarded-for", "") or headers.get("X-Forwarded-For", "")).strip()
            rip = str(headers.get("x-real-ip", "") or headers.get("X-Real-Ip", "")).strip()
    except Exception:
        pass
    if xff:
        ip = str(xff.split(",")[0]).strip()
    if not ip:
        ip = rip
    ua_hash = hashlib.sha256(ua.encode("utf-8")).hexdigest() if ua else ""
    return {
        "host": socket.gethostname(),
        "ip": str(ip or "").strip(),
        "x_forwarded_for": xff,
        "x_real_ip": rip,
        "user_agent_sha256": ua_hash,
        "client_fingerprint": _auth_client_fingerprint(),
    }


def _append_login_audit_event(
    *,
    main_dir: Path,
    event: str,
    ok: bool,
    username: str,
    email: str,
    auth_type: str,
    provider: str = "",
    reason: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    row: Dict[str, Any] = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": str(event or "").strip(),
        "ok": bool(ok),
        "username": str(username or "").strip(),
        "email": str(email or "").strip(),
        "auth_type": str(auth_type or "").strip(),
        "provider": str(provider or "").strip(),
        "reason": str(reason or "").strip(),
    }
    row.update(_auth_request_meta())
    if isinstance(extra, dict) and extra:
        for k, v in extra.items():
            if k in row:
                continue
            row[str(k)] = v
    _append_login_audit_log(main_dir, row)


def _auth_is_effective_value(v: Any) -> bool:
    s = str(v or "").strip()
    if not s:
        return False
    up = s.upper()
    if "<" in s or ">" in s:
        return False
    if "SET_YOUR_" in up or "YOUR_" in up:
        return False
    return True


def _auth_redirect_uri_valid(uri: str, forbid_ip_or_localhost: bool = False) -> bool:
    s = str(uri or "").strip()
    if not s:
        return False
    try:
        u = urllib.parse.urlparse(s)
    except Exception:
        return False
    if str(u.scheme).lower() != "https":
        return False
    if not u.netloc:
        return False
    if u.fragment:
        return False
    host = str(u.hostname or "").strip().lower()
    if not host:
        return False
    if forbid_ip_or_localhost:
        if host in {"localhost", "127.0.0.1", "::1"}:
            return False
        try:
            ipaddress.ip_address(host)
            return False
        except Exception:
            pass
    return True


def _auth_has_authlib() -> bool:
    try:
        import authlib  # noqa: F401

        return True
    except Exception:
        return False


def _auth_oidc_provider_configured(provider: str) -> bool:
    if not hasattr(st, "login"):
        return False
    redirect_uri = str(_st_secrets_get(["auth", "redirect_uri"], "") or "")
    provider_lc = str(provider or "").strip().lower()
    # Apple OIDC requirement: redirect_uri must be HTTPS + domain name (not IP/localhost).
    has_redirect = _auth_is_effective_value(redirect_uri) and _auth_redirect_uri_valid(
        redirect_uri,
        forbid_ip_or_localhost=(provider_lc == "apple"),
    )
    has_cookie = _auth_is_effective_value(_st_secrets_get(["auth", "cookie_secret"], ""))
    if not (has_redirect and has_cookie):
        return False
    p = str(provider or "").strip()
    if p:
        has_client_id = _auth_is_effective_value(_st_secrets_get(["auth", p, "client_id"], ""))
        has_client_secret = _auth_is_effective_value(_st_secrets_get(["auth", p, "client_secret"], ""))
        has_meta = _auth_is_effective_value(_st_secrets_get(["auth", p, "server_metadata_url"], ""))
        return has_client_id and has_client_secret and has_meta
    has_client_id = _auth_is_effective_value(_st_secrets_get(["auth", "client_id"], ""))
    has_client_secret = _auth_is_effective_value(_st_secrets_get(["auth", "client_secret"], ""))
    has_meta = _auth_is_effective_value(_st_secrets_get(["auth", "server_metadata_url"], ""))
    return has_client_id and has_client_secret and has_meta


def _auth_oidc_ready_providers(primary_provider: str) -> List[str]:
    order: List[str] = []
    seen: set[str] = set()
    cands = [str(primary_provider or "").strip().lower(), "google", "apple"]
    for p in cands:
        if not p or p in seen:
            continue
        seen.add(p)
        try:
            if _auth_oidc_provider_configured(p):
                order.append(p)
        except Exception:
            continue
    return order


def _auth_provider_label(provider: str) -> str:
    p = str(provider or "").strip().lower()
    if p == "google":
        return "Googleでログイン"
    if p == "apple":
        return "Appleでログイン"
    return f"{provider}でログイン"


def _auth_provider_metadata_url(provider: str) -> str:
    p = str(provider or "").strip().lower()
    if p == "google":
        return "https://accounts.google.com/.well-known/openid-configuration"
    if p == "apple":
        return "https://appleid.apple.com/.well-known/openid-configuration"
    return "https://accounts.google.com/.well-known/openid-configuration"


def _auth_oidc_is_logged_in() -> bool:
    if not hasattr(st, "user"):
        return False
    try:
        return bool(getattr(st.user, "is_logged_in"))
    except Exception:
        try:
            return bool(st.user.get("is_logged_in", False))
        except Exception:
            return False


def _auth_oidc_user_identity() -> Tuple[str, str]:
    if not hasattr(st, "user"):
        return "", ""

    def _pick(keys: List[str]) -> str:
        for k in keys:
            try:
                v = st.user[k]
            except Exception:
                try:
                    v = getattr(st.user, k)
                except Exception:
                    v = None
            if v is None:
                continue
            s = str(v).strip()
            if s:
                return s
        return ""

    email = _pick(["email"])
    name = _pick(["name", "preferred_username", "email", "sub"])
    return name, email


def _http_post(url: str, body: bytes, headers: Dict[str, str], timeout_sec: float = 2.0) -> Tuple[bool, str]:
    safe_headers: Dict[str, str] = {}
    for k, v in (headers or {}).items():
        try:
            sv = str(v)
        except Exception:
            continue
        try:
            sv.encode("latin-1")
            safe_headers[str(k)] = sv
        except Exception:
            # HTTP header values must be latin-1 compatible.
            continue
    req = urllib.request.Request(url=url, data=body, headers=safe_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            code = int(getattr(resp, "status", 200))
            if 200 <= code < 300:
                return True, f"http={code}"
            return False, f"http={code}"
    except urllib.error.HTTPError as e:
        return False, f"http={e.code}"
    except Exception as e:
        return False, str(e)


def _latin1_safe_header_value(value: str, fallback: str) -> str:
    s = str(value or "").strip()
    if not s:
        return str(fallback)
    try:
        s.encode("latin-1")
        return s
    except Exception:
        s_ascii = s.encode("ascii", errors="ignore").decode("ascii").strip()
        if s_ascii:
            return s_ascii
        return str(fallback)


def _send_security_notification(
    *,
    enabled: bool,
    title: str,
    text: str,
    payload: Dict[str, Any],
    tags: str = "lock",
) -> Tuple[bool, str]:
    if not enabled:
        return True, "disabled"

    sec = _st_secrets_get(["dashboard_security"], {})
    try:
        sec_d = dict(sec)
    except Exception:
        sec_d = {}

    webhook_url = str(sec_d.get("login_notify_webhook_url", "")).strip()
    webhook_bearer = str(sec_d.get("login_notify_bearer_token", "")).strip()
    ntfy_topic_url = str(sec_d.get("ntfy_topic_url", "")).strip()
    ntfy_bearer = str(sec_d.get("ntfy_bearer_token", "")).strip()
    results: List[Tuple[bool, str, str]] = []

    if ntfy_topic_url:
        h = {
            "Content-Type": "text/plain; charset=utf-8",
            "Title": _latin1_safe_header_value(title, "Ouroboros Security Notification"),
            "Tags": tags,
        }
        if ntfy_bearer:
            h["Authorization"] = f"Bearer {ntfy_bearer}"
        ok, msg = _http_post(ntfy_topic_url, text.encode("utf-8"), h, timeout_sec=2.0)
        results.append((ok, "ntfy", msg))

    if webhook_url:
        h = {"Content-Type": "application/json; charset=utf-8"}
        if webhook_bearer:
            h["Authorization"] = f"Bearer {webhook_bearer}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        ok, msg = _http_post(webhook_url, body, h, timeout_sec=2.0)
        results.append((ok, "webhook", msg))

    if not results:
        return True, "no_target"

    ok_all = all(x[0] for x in results)
    detail = ", ".join([f"{name}:{msg}" for _, name, msg in results])
    return ok_all, detail


def _send_login_notification(user: str, email: str, auth_type: str) -> Tuple[bool, str]:
    sec = _st_secrets_get(["dashboard_security"], {})
    try:
        sec_d = dict(sec)
    except Exception:
        sec_d = {}

    webhook_url = str(sec_d.get("login_notify_webhook_url", "")).strip()
    ntfy_topic_url = str(sec_d.get("ntfy_topic_url", "")).strip()
    enabled_default = bool(webhook_url or ntfy_topic_url)
    enabled = _auth_safe_bool(sec_d.get("login_notify_enabled", enabled_default), enabled_default)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    host = socket.gethostname()
    title = "Ouroboros ダッシュボード ログイン"
    text = (
        f"{title}\n"
        f"時刻={ts}\n"
        f"ユーザー={user}\n"
        f"メール={email or '-'}\n"
        f"認証={auth_type}\n"
        f"ホスト={host}"
    )
    payload = {
        "event": "dashboard_login",
        "time": ts,
        "user": user,
        "email": email,
        "auth_type": auth_type,
        "host": host,
    }
    return _send_security_notification(
        enabled=enabled,
        title=title,
        text=text,
        payload=payload,
        tags="lock",
    )


def _send_login_failure_notification(
    *,
    username: str,
    reason: str,
    failed_count: int,
    lock_until: float,
) -> Tuple[bool, str]:
    sec = _st_secrets_get(["dashboard_security"], {})
    try:
        sec_d = dict(sec)
    except Exception:
        sec_d = {}

    webhook_url = str(sec_d.get("login_notify_webhook_url", "")).strip()
    ntfy_topic_url = str(sec_d.get("ntfy_topic_url", "")).strip()
    enabled_default = bool(webhook_url or ntfy_topic_url)
    login_enabled = _auth_safe_bool(sec_d.get("login_notify_enabled", enabled_default), enabled_default)
    enabled = _auth_safe_bool(sec_d.get("auth_fail_notify_enabled", login_enabled), login_enabled)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    host = socket.gethostname()
    lock_until_str = "-"
    if lock_until and lock_until > time.time():
        lock_until_str = datetime.fromtimestamp(lock_until).strftime("%Y-%m-%d %H:%M:%S")
    title = "Ouroboros ダッシュボード ログイン失敗"
    text = (
        f"{title}\n"
        f"時刻={ts}\n"
        f"ユーザー={username or '-'}\n"
        f"理由={reason}\n"
        f"失敗回数={int(failed_count)}\n"
        f"ロック解除予定={lock_until_str}\n"
        f"ホスト={host}"
    )
    payload = {
        "event": "dashboard_login_failed",
        "time": ts,
        "user": username or "",
        "reason": reason,
        "failed_count": int(failed_count),
        "lock_until": lock_until_str,
        "host": host,
    }
    return _send_security_notification(
        enabled=enabled,
        title=title,
        text=text,
        payload=payload,
        tags="warning,lock",
    )


def _maybe_send_login_notification(main_dir: Path, user: str, email: str, auth_type: str) -> None:
    sig = f"{auth_type}:{user}:{email}"
    if st.session_state.get(AUTH_NOTIFY_SENT_KEY) == sig:
        return
    provider = ""
    at = str(auth_type or "").strip()
    if ":" in at:
        provider = at.split(":", 1)[1].strip()
    elif at.upper().startswith("LOCAL"):
        provider = "local"
    _append_login_audit_event(
        main_dir=main_dir,
        event="login_success",
        ok=True,
        username=user,
        email=email,
        auth_type=auth_type,
        provider=provider,
        reason="",
    )
    ok, msg = _send_login_notification(user=user, email=email, auth_type=auth_type)
    st.session_state[AUTH_NOTIFY_SENT_KEY] = sig
    st.session_state["_dashboard_login_notify_status"] = {
        "ok": bool(ok),
        "message": str(msg),
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _load_breakglass_state(main_dir: Path) -> Dict[str, Any]:
    return _read_json_dict(auth_breakglass_path(main_dir), {"day": "", "count": 0})


def _save_breakglass_state(main_dir: Path, state: Dict[str, Any]) -> None:
    _write_json_dict(auth_breakglass_path(main_dir), state)


def _breakglass_usage_today(main_dir: Path) -> int:
    stt = _load_breakglass_state(main_dir)
    today = datetime.now().strftime("%Y-%m-%d")
    if str(stt.get("day", "")).strip() != today:
        return 0
    return max(0, _auth_safe_int(stt.get("count", 0), 0))


def _breakglass_consume(main_dir: Path) -> int:
    stt = _load_breakglass_state(main_dir)
    today = datetime.now().strftime("%Y-%m-%d")
    cur = 0
    if str(stt.get("day", "")).strip() == today:
        cur = max(0, _auth_safe_int(stt.get("count", 0), 0))
    new_count = cur + 1
    _save_breakglass_state(main_dir, {"day": today, "count": new_count})
    return new_count


def _pbkdf2_hash(password: str, salt_b64: str, iterations: int) -> str:
    salt = base64.b64decode(str(salt_b64).encode("ascii"))
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        max(100_000, int(iterations)),
    )
    return base64.b64encode(dk).decode("ascii")


def _verify_dashboard_password(password: str, user: Dict[str, Any]) -> bool:
    try:
        stored = str(user.get("password_hash", ""))
        salt = str(user.get("salt", ""))
        iters = _auth_safe_int(user.get("iterations", 310_000), 310_000)
        if not stored or not salt:
            return False
        calc = _pbkdf2_hash(password, salt, iters)
        return hmac.compare_digest(calc, stored)
    except Exception:
        return False


def _render_auth_setup_block(main_dir: Path) -> None:
    st.title("🔐 Dashboard Login Required")
    st.error("ダッシュボードはログイン必須です。初期ユーザーを作成してください。")
    cmd = f"cd {main_dir} && python3 tools/create_dashboard_user.py --username admin"
    st.code(cmd)
    st.info("作成後にページを再読み込みしてください。OIDC（Google/Apple）を使う場合は下の設定例も参照してください。")
    st.markdown("**OIDC設定例 (`MAIN/.streamlit/secrets.toml`)**")
    st.code(
        """
[auth]
redirect_uri = "https://<YOUR_HOST>:8501/oauth2callback"
cookie_secret = "<RANDOM_32+_BYTES>"

[auth.google]
client_id = "<GOOGLE_CLIENT_ID>"
client_secret = "<GOOGLE_CLIENT_SECRET>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

[auth.apple]
client_id = "<APPLE_SERVICE_ID>"
client_secret = "<APPLE_CLIENT_SECRET_JWT>"
server_metadata_url = "https://appleid.apple.com/.well-known/openid-configuration"

[dashboard_security]
login_notify_enabled = true
auth_fail_notify_enabled = true
trade_notify_enabled = true
allowed_emails = ["owner@example.com"]
allowed_email_domains = ["example.com"]
ntfy_topic_url = "https://ntfy.sh/<YOUR_PRIVATE_TOPIC>"

[dashboard_branding]
apple_touch_icon_path = ".streamlit/assets/apple-touch-icon.png"
# apple_touch_icon_url = "https://<YOUR_STATIC_HOST>/apple-touch-icon.png"
apple_mobile_web_app_title = "Project Ouroboros"
""".strip(),
        language="toml",
    )
    st.caption("許可リストを設定すると、OIDCログインでも指定ユーザー以外をブロックできます。")
    st.stop()


def _render_oidc_setup_block(main_dir: Path, provider: str) -> None:
    p = provider or "default"
    p_lc = str(provider or "").strip().lower()
    meta_url = _auth_provider_metadata_url(p_lc or "google")
    st.title("🔐 Dashboard Login Required")
    st.error(f"OIDC設定が未完了です。provider={p}")
    if not _auth_has_authlib():
        st.warning("Authlib が未インストールです。`pip install streamlit[auth]` を実行してください。")
    st.markdown("`MAIN/.streamlit/secrets.toml` に以下を設定してください。")
    if p_lc == "apple":
        st.warning("AppleのOIDCでは `redirect_uri` は `https` + ドメイン必須です（IP/localhost不可）。")
    elif p_lc == "google":
        st.info("GoogleのOIDCでは Google Cloud Console の Redirect URI と `redirect_uri` を完全一致させてください。")
    if provider:
        provider_block = f"""[auth.{provider}]
client_id = "<CLIENT_ID>"
client_secret = "<CLIENT_SECRET>"
server_metadata_url = "{meta_url}"
"""
    else:
        provider_block = """client_id = "<CLIENT_ID>"
client_secret = "<CLIENT_SECRET>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
"""
    st.code(
        f"""
[auth]
redirect_uri = "https://<YOUR_HOST>:8501/oauth2callback"
cookie_secret = "<RANDOM_32+_BYTES>"
{provider_block}

[dashboard_security]
login_notify_enabled = true
auth_fail_notify_enabled = true
trade_notify_enabled = true
allowed_emails = ["owner@example.com"]
allowed_email_domains = ["example.com"]
ntfy_topic_url = "https://ntfy.sh/<YOUR_PRIVATE_TOPIC>"

[dashboard_branding]
apple_touch_icon_path = ".streamlit/assets/apple-touch-icon.png"
# apple_touch_icon_url = "https://<YOUR_STATIC_HOST>/apple-touch-icon.png"
apple_mobile_web_app_title = "Project Ouroboros"
""".strip(),
        language="toml",
    )
    st.caption("OIDC許可リストを設定しない場合、設定済みOIDCアカウントなら誰でもログイン可能です。")
    st.caption("設定後にダッシュボードを再読み込みしてください。")
    st.caption(f"緊急時のみ: `DASHBOARD_AUTH_DISABLE=1` で一時バイパス可能（ローカル復旧用途）。")
    st.stop()


def _require_local_dashboard_auth(
    main_dir: Path,
    cfg: Dict[str, Any],
    now_ts: float,
    *,
    show_header: bool = True,
    form_key: str = "dashboard_login_form",
    breakglass_mode: bool = False,
    breakglass_limit: int = 0,
) -> None:
    users = cfg.get("users", [])
    if not users:
        _render_auth_setup_block(main_dir)

    lock = _load_auth_lock(main_dir)
    lock_until = float(lock.get("lock_until", 0.0) or 0.0)
    if now_ts < lock_until:
        remain = int(lock_until - now_ts)
        st.title("🔐 Dashboard Login")
        st.error(f"ログイン失敗が続いたため一時ロック中です。{remain} 秒後に再試行してください。")
        st.stop()

    if show_header:
        st.title("🔐 Dashboard Login")
        st.caption("ダッシュボード閲覧には認証が必要です。")
    else:
        st.markdown("**ローカルユーザーでログイン（フォールバック）**")
    if breakglass_mode:
        limit = max(1, int(breakglass_limit))
        used = _breakglass_usage_today(main_dir)
        remain = max(0, limit - used)
        if remain <= 0:
            st.error("本日の breakglass ローカルログイン上限に達しています。OIDCログインを使用してください。")
            st.caption(f"breakglass daily limit={limit} / used={used}")
            st.stop()
        st.caption(f"breakglass daily limit={limit} / remaining={remain}")

    remember_default = bool(cfg.get("remember_local_login", True))
    with st.form(form_key, clear_on_submit=False):
        in_user = st.text_input("username", value="", max_chars=64)
        in_pass = st.text_input("password", value="", type="password")
        remember_local = st.checkbox("この端末でログイン状態を維持", value=remember_default)
        login_submit = st.form_submit_button("ログイン", width="stretch")

    if login_submit:
        hit = None
        user_norm = str(in_user).strip()
        for u in users:
            if str(u.get("username", "")).strip() == user_norm:
                hit = u
                break

        ok = bool(hit) and _verify_dashboard_password(in_pass, hit or {})
        if ok:
            auth_type = "LOCAL_BREAKGLASS" if breakglass_mode else "LOCAL"
            st.session_state[AUTH_SESSION_KEY] = {
                "ok": True,
                "username": user_norm,
                "email": "",
                "auth_type": auth_type,
                "login_at": now_ts,
                "last_seen": now_ts,
            }
            _clear_auth_lock(main_dir)
            if breakglass_mode:
                _breakglass_consume(main_dir)
            _maybe_send_login_notification(main_dir=main_dir, user=user_norm, email="", auth_type=auth_type)
            if remember_local:
                try:
                    tok = _auth_issue_local_token(
                        main_dir=main_dir,
                        sess=st.session_state[AUTH_SESSION_KEY],
                        now_ts=now_ts,
                        ttl_sec=int(cfg["session_timeout_min"]) * 60,
                    )
                    _auth_cookie_set(tok, int(cfg["session_timeout_min"]) * 60)
                except Exception:
                    pass
            else:
                try:
                    old_tok = _auth_cookie_get()
                    _auth_revoke_local_token(main_dir, old_tok, now_ts=now_ts)
                    _auth_cookie_clear()
                except Exception:
                    pass
            st.success("ログインしました。")
            st.rerun()
        else:
            failed = _auth_safe_int(lock.get("failed_count", 0), 0) + 1
            max_fail = int(cfg["max_failures"])
            lock_minutes = int(cfg["lock_minutes"])
            new_lock = {
                "failed_count": failed,
                "lock_until": 0.0,
                "last_failed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            if failed >= max_fail:
                new_lock["failed_count"] = 0
                new_lock["lock_until"] = now_ts + lock_minutes * 60
                st.error(f"ログイン失敗が上限に達しました。{lock_minutes} 分ロックします。")
            else:
                left = max_fail - failed
                st.error(f"ログインに失敗しました。残り {left} 回でロックされます。")
            _save_auth_lock(main_dir, new_lock)
            fail_reason = "lockout" if float(new_lock.get("lock_until", 0.0) or 0.0) > now_ts else "invalid_credentials"
            _append_login_audit_event(
                main_dir=main_dir,
                event="login_failed",
                ok=False,
                username=user_norm,
                email="",
                auth_type=("LOCAL_BREAKGLASS" if breakglass_mode else "LOCAL"),
                provider="local",
                reason=fail_reason,
                extra={
                    "failed_count": int(failed),
                    "lock_until": float(new_lock.get("lock_until", 0.0) or 0.0),
                },
            )
            n_ok, n_msg = _send_login_failure_notification(
                username=user_norm,
                reason=fail_reason,
                failed_count=failed,
                lock_until=float(new_lock.get("lock_until", 0.0) or 0.0),
            )
            st.session_state["_dashboard_login_notify_status"] = {
                "ok": bool(n_ok),
                "message": str(n_msg),
                "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

    st.stop()


def require_dashboard_auth(main_dir: Path) -> None:
    # emergency bypass for local recovery
    if bval_str(os.getenv("DASHBOARD_AUTH_DISABLE", "0")):
        return

    cfg = _load_auth_config(main_dir)
    if not cfg.get("enabled", True):
        return

    _auth_cleanup_legacy_query_token()

    mode = _auth_mode_norm(cfg.get("mode", "AUTO"))
    provider = str(cfg.get("oidc_provider", "apple")).strip()
    timeout_sec = int(cfg["session_timeout_min"]) * 60
    allow_breakglass_in_auto = bool(cfg.get("allow_breakglass_in_auto", True))
    breakglass_daily_limit = max(1, int(cfg.get("breakglass_daily_limit", 3)))
    now_ts = time.time()
    sess = st.session_state.get(AUTH_SESSION_KEY)
    if isinstance(sess, dict) and sess.get("ok"):
        last_seen = float(sess.get("last_seen", now_ts))
        if now_ts - last_seen <= timeout_sec:
            sess["last_seen"] = now_ts
            st.session_state[AUTH_SESSION_KEY] = sess
            if str(sess.get("auth_type", "")).upper().startswith("LOCAL"):
                try:
                    tok = _auth_cookie_get()
                    if tok and _auth_touch_local_token(main_dir, tok, now_ts, timeout_sec):
                        _auth_cookie_set(tok, timeout_sec)
                    elif bool(cfg.get("remember_local_login", True)):
                        ntok = _auth_issue_local_token(main_dir, sess, now_ts, timeout_sec)
                        _auth_cookie_set(ntok, timeout_sec)
                except Exception:
                    pass
            return
        old_type = str(sess.get("auth_type", "")).upper()
        st.session_state.pop(AUTH_SESSION_KEY, None)
        st.session_state.pop(AUTH_NOTIFY_SENT_KEY, None)
        if old_type.startswith("LOCAL"):
            try:
                tok = _auth_cookie_get()
                _auth_revoke_local_token(main_dir, tok, now_ts=now_ts)
                _auth_cookie_clear()
            except Exception:
                pass
        if old_type.startswith("OIDC") and hasattr(st, "logout"):
            try:
                st.logout()
            except Exception:
                pass

    if mode in {"AUTO", "LOCAL"}:
        try:
            cookie_tok = _auth_cookie_get()
            restored = _auth_restore_local_token(main_dir, raw_token=cookie_tok, now_ts=now_ts, ttl_sec=timeout_sec)
        except Exception:
            cookie_tok = ""
            restored = None
        if restored:
            st.session_state[AUTH_SESSION_KEY] = restored
            try:
                _auth_cookie_set(cookie_tok, timeout_sec)
            except Exception:
                pass
            return
        if cookie_tok:
            try:
                _auth_revoke_local_token(main_dir, cookie_tok, now_ts=now_ts)
                _auth_cookie_clear()
            except Exception:
                pass

    oidc_ready_list: List[str] = []
    if _auth_has_authlib():
        oidc_ready_list = _auth_oidc_ready_providers(provider)
    oidc_ready = bool(oidc_ready_list)
    active_provider = provider if str(provider).strip().lower() in oidc_ready_list else (oidc_ready_list[0] if oidc_ready_list else provider)

    if mode in {"AUTO", "OIDC"}:
        if oidc_ready and _auth_oidc_is_logged_in():
            name, email = _auth_oidc_user_identity()
            user_label = name or email or "oidc-user"
            auth_type = f"OIDC:{active_provider or 'default'}"
            allow_ok, allow_reason = _auth_oidc_allowlist_decision(email)
            if not allow_ok:
                _append_login_audit_event(
                    main_dir=main_dir,
                    event="login_denied",
                    ok=False,
                    username=user_label,
                    email=email,
                    auth_type=auth_type,
                    provider=active_provider or "",
                    reason=f"oidc_allowlist:{allow_reason}",
                )
                n_ok, n_msg = _send_login_failure_notification(
                    username=user_label,
                    reason=f"oidc_allowlist:{allow_reason}",
                    failed_count=0,
                    lock_until=0.0,
                )
                st.session_state["_dashboard_login_notify_status"] = {
                    "ok": bool(n_ok),
                    "message": str(n_msg),
                    "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                if hasattr(st, "logout"):
                    try:
                        st.logout()
                    except Exception:
                        pass
                st.error("このOIDCアカウントは許可リスト外です。管理者に連絡してください。")
                st.stop()
            st.session_state[AUTH_SESSION_KEY] = {
                "ok": True,
                "username": user_label,
                "email": email,
                "auth_type": auth_type,
                "login_at": now_ts,
                "last_seen": now_ts,
            }
            _maybe_send_login_notification(main_dir=main_dir, user=user_label, email=email, auth_type=auth_type)
            return
        if oidc_ready:
            st.title("🔐 Dashboard Login")
            st.caption("OIDC（Google/Apple）を優先してください。ローカルIDは緊急時のみ利用します。")
            cols = st.columns(len(oidc_ready_list))
            for i, pv in enumerate(oidc_ready_list):
                with cols[i]:
                    if st.button(
                        _auth_provider_label(pv),
                        type="primary" if i == 0 else "secondary",
                        width="stretch",
                        key=f"oidc_login_{pv}",
                    ):
                        try:
                            st.login(pv)
                        except Exception as e:
                            st.error(f"OIDCログイン開始に失敗: {e}")
            if mode == "OIDC":
                st.info("ログイン完了後にこの画面へ戻ります。")
                st.stop()
            st.info("通常運用はOIDC推奨です。ローカルIDは breakglass 用です。")
            if allow_breakglass_in_auto:
                show_breakglass = st.toggle(
                    "緊急時のみ: ローカルログイン（breakglass）を表示",
                    value=False,
                    key="auth_show_local_breakglass",
                )
                if show_breakglass:
                    _require_local_dashboard_auth(
                        main_dir=main_dir,
                        cfg=cfg,
                        now_ts=now_ts,
                        show_header=False,
                        form_key="dashboard_login_form_local_fallback",
                        breakglass_mode=True,
                        breakglass_limit=breakglass_daily_limit,
                    )
                    return
            else:
                st.caption("ローカルbreakglassログインは無効化されています（dashboard_auth.json: allow_breakglass_in_auto=false）。")
            st.stop()
        if mode == "OIDC":
            _render_oidc_setup_block(main_dir, provider)
        # mode=AUTO falls through to local when OIDC is not ready

    _require_local_dashboard_auth(main_dir=main_dir, cfg=cfg, now_ts=now_ts)


# =========================
# CONTROL (SPEC)
# =========================
DEFAULTS: Dict[str, str] = {
    # switches
    "today_on": "1",
    "trade_enabled": "1",
    "paper_mode": "1",
    "observe_only": "0",
    "live_enabled": "0",
    "exchange_name": "bitflyer",
    "start_hour": "10",
    "end_hour": "16",
    "no_paper_hours": "13",
    "one_position_only": "1",
    "safety_hard_block": "1",
    "rollout_mode": "AUTO",
    "stage_paper_days": "3",
    "stage_canary_days": "3",
    "canary_lot": "0.001",
    "daily_loss_limit_pct": "-2.0",
    "streak_stop_enabled": "0",
    "streak_stop_max_losses": "3",
    "limit_order_timeout_sec": "30",
    "limit_price_offset_ticks": "0",
    "product_code": "FX_BTC_JPY",
    "market_type": "FX",
    "fx_leverage": "1.0",
    "fx_collateral_use_ratio": "0.90",
    "keychain_service": "ouroboros.bitflyer",
    "keychain_account_key": "api_key",
    "keychain_account_secret": "api_secret",
    # risk/params
    "tp_buy_pct": "0.155",
    "tp_sell_pct": "0.180",
    "sl_pct": "-0.220",
    "win_min": "120",
    "timeout_mode": "IGNORE",
    "spread_limit_pct": "0.0005",
    "max_trades_per_day": "50",
    "lot": "0.001",
    # MA params
    "fast_n": "5",
    "slow_n": "20",
    "max_ltp_history": "200",
    # partial/extend
    "max_extend_count": "1",
    "extend_min": "30",
    "extend_min_bestfav_pct": "0.08",
    "partial_tp_trigger_pct": "0.10",
    "exit_technical_enabled": "0",
    "exit_technical_only_paper": "1",
    "exit_sma_fast_n": "5",
    "exit_sma_slow_n": "20",
    "exit_technical_min_hold_min": "5",
    # AI toggles (compat)
    "ai_model_enabled": "0",
    "ai_enabled": "0",
    "ai_mode": "OFF",
    "ai_threshold": "0.55",
    "ai_veto_threshold": "0.30",
    "ai_auto_train_enabled": "1",
    "ai_auto_control_sync_enabled": "1",
    "ai_auto_lookback_days": "45",
    "ai_train_live_only": "0",
    "ai_train_live_boost": "1.00",
    "ai_train_include_shadow": "0",
    "ai_train_shadow_boost": "0.20",
    "ai_train_include_backtest": "0",
    "ai_train_backtest_boost": "0.30",
    "ai_train_backtest_path": "../logs/backtest/ai_training_log_backtest.csv",
    "ai_train_backtest_gate_enabled": "1",
    "ai_train_backtest_gate_min_samples": "300",
    "ai_train_backtest_gate_expectancy_min": "0.000",
    "ai_train_backtest_gate_pf_min": "1.00",
    "ai_train_backtest_max_rows": "3000",
    "ai_train_recent_halflife_days": "14",
    "ai_train_weekly_feedback_enabled": "0",
    "ai_train_weekly_good_hours": "",
    "ai_train_weekly_bad_hours": "",
    "ai_train_weekly_good_hour_boost": "1.20",
    "ai_train_weekly_bad_hour_penalty": "0.70",
    "ai_lot_lock_enabled": "1",
    "ai_lot_lock_min_samples": "120",
    "ai_lot_lock_max_lot": "0.001",
    "ai_monthly_reval_enabled": "1",
    "ai_monthly_reval_lookback_days": "120",
    "ai_monthly_reval_min_samples": "300",
    "ai_monthly_reval_pf_min": "1.00",
    "ai_monthly_reval_expectancy_min": "0.000",
    "ai_monthly_reval_min_improve": "0.000",
    "ai_gate_enabled": "1",
    "ai_gate_min_samples": "30",
    "ai_gate_expectancy_min": "0.0",
    "ai_gate_pf_min": "1.05",
    "ai_auto_rollback_enabled": "1",
    "ai_auto_rollback_lookback_days": "14",
    "ai_auto_rollback_pf_floor": "0.95",
    "ai_auto_rollback_expectancy_floor": "-0.01",
    "ai_features": "spread,trend,ma_gap,ma_slope,volatility",
    "ai_debug": "0",
    "ai_dp_entry": "1",
    "ai_dp_extend": "1",
    "ai_dp_exit": "1",
}

BOOL_TRUE = ("1", "true", "yes", "on", "y", "t")
BOOL_FALSE = ("0", "false", "no", "off", "n", "f")

def bval_str(v: Any) -> bool:
    return str(v or "0").strip().lower() in BOOL_TRUE


def _read_text_try(path: Path, encs: Iterable[str]) -> Optional[str]:
    for enc in encs:
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return None


def _tail_text(path: Path, lines: int = 80, max_bytes: int = 200_000) -> str:
    n = max(1, int(lines))
    lim = max(4_096, int(max_bytes))
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = int(f.tell())
            read_size = min(size, lim)
            f.seek(max(0, size - read_size), os.SEEK_SET)
            chunk = f.read(read_size).decode("utf-8", errors="ignore")
        rows = chunk.splitlines()
        return "\n".join(rows[-n:])
    except Exception:
        return ""


def read_control_kv_csv(path: Path) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """
    SPEC: key,value. Preserve unknown keys.
    If missing: start with DEFAULTS.
    """
    meta = {"path": str(path), "exists": path.exists(), "mtime": None}
    out: Dict[str, str] = {}
    if path.exists():
        try:
            meta["mtime"] = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            txt = _read_text_try(path, ["utf-8", "utf-8-sig", "cp932"])
            if not txt:
                raise ValueError("cannot read text")
            rows = list(csv.reader(txt.splitlines()))
            for r in rows:
                if len(r) < 2:
                    continue
                k = str(r[0]).strip()
                if not k or k.lower() == "key":
                    continue
                out[k] = str(r[1]).strip()
        except Exception:
            out = {}

    # Apply defaults without deleting unknown keys
    for k, v in DEFAULTS.items():
        out.setdefault(k, v)

    # AI compat: keep both ai_enabled and ai_model_enabled aligned on write; read: if either is ON, treat as ON
    if bval_str(out.get("ai_enabled", "0")) and not bval_str(out.get("ai_model_enabled", "0")):
        out["ai_model_enabled"] = "1"
    if bval_str(out.get("ai_model_enabled", "0")) and not bval_str(out.get("ai_enabled", "0")):
        out["ai_enabled"] = "1"

    return out, meta


def write_control_kv_csv(path: Path, d: Dict[str, str]) -> Tuple[bool, str]:
    """
    SPEC: unknown keys MUST be preserved. We write all keys (sorted).
    Also keep ai_enabled and ai_model_enabled aligned.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        # Align AI toggles
        ai_on = bval_str(d.get("ai_model_enabled", d.get("ai_enabled", "0")))
        d["ai_model_enabled"] = "1" if ai_on else "0"
        d["ai_enabled"] = "1" if ai_on else "0"

        rows = [["key", "value"]] + [[k, str(d.get(k, ""))] for k in sorted(d.keys())]
        tmp = path.with_suffix(path.suffix + ".tmp")
        # create parent dir
        path.parent.mkdir(parents=True, exist_ok=True)
        # write to tmp first
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        # create a timestamped backup of existing file (SPEC: .bak); keep latest 10 only
        try:
            if path.exists():
                from datetime import datetime as _dt
                import shutil

                bak = path.with_name(path.name + f".bak_{_dt.utcnow().strftime('%Y%m%dT%H%M%SZ')}")
                shutil.copy(path, bak)
                bak_files = sorted(path.parent.glob(path.name + ".bak_*"))
                for old in bak_files[:-10]:
                    try:
                        old.unlink()
                    except Exception:
                        pass
        except Exception:
            # non-fatal: continue to replace
            pass
        tmp.replace(path)
        return True, str(path)
    except Exception as e:
        return False, str(e)


# =========================
# Logs / JSON
# =========================
LOG_NAME_RE = re.compile(r"trade_log_(\d{8})\.csv$")
REPORT_JSON_RE = re.compile(r"^daily_report_(\d{8})(?:_(\d{8}))?\.json$")


def dir_cache_token(path: Path) -> str:
    try:
        stt = path.stat()
        return f"{stt.st_mtime_ns}:{stt.st_size}"
    except Exception:
        return "missing"


@st.cache_data(show_spinner=False)
def _list_log_days_cached(logs_dir: Path, cache_token: str = "") -> List[str]:
    _ = cache_token
    if not logs_dir.exists():
        return []
    days: List[str] = []
    for p in logs_dir.glob("trade_log_*.csv"):
        m = LOG_NAME_RE.search(p.name)
        if m:
            days.append(m.group(1))
    return sorted(set(days), reverse=True)


def list_log_days(logs_dir: Optional[Path]) -> List[str]:
    if not logs_dir or not logs_dir.exists():
        return []
    return _list_log_days_cached(logs_dir, dir_cache_token(logs_dir))


@st.cache_data(show_spinner=False)
def _read_csv_dict_rows_cached(path: Path, cache_token: str = "") -> List[Dict[str, Any]]:
    _ = cache_token
    txt = _read_text_try(path, ["utf-8", "utf-8-sig", "cp932"])
    if not txt:
        return []
    try:
        return list(csv.DictReader(txt.splitlines()))
    except Exception:
        return []


def _read_csv_dict_rows(path: Path) -> List[Dict[str, Any]]:
    return _read_csv_dict_rows_cached(path, file_cache_token(path))


@st.cache_data(show_spinner=False)
def _count_csv_data_rows(path: Path, cache_token: str = "") -> int:
    _ = cache_token
    if not path.exists():
        return 0
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            r = csv.reader(f)
            header = next(r, None)
            if not header:
                return 0
            return sum(1 for _ in r)
    except Exception:
        return 0


def _count_ai_training_log_rows(main_dir: Path) -> int:
    p = main_dir.parent / "logs" / "ai_training_log.csv"
    return _count_csv_data_rows(p, file_cache_token(p))


@st.cache_data(show_spinner=False)
def read_trade_log_df(csv_path: Path, cache_token: str = "") -> pd.DataFrame:
    # cache_token carries file mtime/size so cache invalidates when the log file changes.
    _ = cache_token
    for enc in ("utf-8", "utf-8-sig", "cp932"):
        try:
            df = pd.read_csv(csv_path, encoding=enc)
            if "time" in df.columns:
                df["time_dt"] = pd.to_datetime(df["time"], errors="coerce")
                df["hour"] = df["time_dt"].dt.hour
            return df
        except Exception:
            continue
    return pd.DataFrame()


def file_cache_token(path: Path) -> str:
    try:
        stt = path.stat()
        return f"{stt.st_mtime_ns}:{stt.st_size}"
    except Exception:
        return "missing"


def safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s == "" or s.lower() in ("none", "nan"):
            return None
        return float(s)
    except Exception:
        return None


def _fmt_jpy(v: Optional[float]) -> str:
    if v is None:
        return "-"
    return f"¥ {v:,.0f}"


def _fmt_float(v: Optional[float], nd: int = 3) -> str:
    if v is None:
        return "-"
    return f"{v:,.{nd}f}"


def fetch_live_funds_snapshot(ctrl: Dict[str, str]) -> Tuple[bool, Dict[str, Any], str]:
    """
    Read balance/collateral from bitFlyer private API using Keychain credentials.
    Returns: (ok, snapshot, message)
    """
    try:
        from exchange.bitflyer_private import BitflyerPrivateClient
        from tools.keychain_secret import read_pair
    except Exception as e:
        return False, {}, f"import failed: {e}"

    service = str(ctrl.get("keychain_service", DEFAULTS["keychain_service"])).strip()
    account_key = str(ctrl.get("keychain_account_key", DEFAULTS["keychain_account_key"])).strip()
    account_secret = str(ctrl.get("keychain_account_secret", DEFAULTS["keychain_account_secret"])).strip()
    exchange_name = str(ctrl.get("exchange_name", DEFAULTS.get("exchange_name", "bitflyer"))).strip().lower()
    market_type = str(ctrl.get("market_type", DEFAULTS["market_type"])).strip().upper()
    product_code = str(ctrl.get("product_code", DEFAULTS["product_code"])).strip()

    if exchange_name != "bitflyer":
        return False, {}, f"exchange_name={exchange_name} は未実装です（現状は bitflyer のみ対応）"

    try:
        api_key, api_secret = read_pair(service=service, account_key=account_key, account_secret=account_secret)
    except Exception as e:
        return False, {}, f"keychain read failed: {e}"

    try:
        client = BitflyerPrivateClient(api_key=api_key, api_secret=api_secret)
        snap: Dict[str, Any] = {
            "market_type": market_type,
            "product_code": product_code,
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        if market_type in ("FX", "CFD", "LIGHTNING"):
            row = client.get_collateral()
            collateral = (
                safe_float(row.get("collateral"))
                or safe_float(row.get("collateral_amount"))
                or safe_float(row.get("available_collateral"))
            )
            open_pnl = safe_float(row.get("open_position_pnl"))
            require_col = safe_float(row.get("require_collateral"))
            keep_rate = safe_float(row.get("keep_rate"))
            lev = safe_float(ctrl.get("fx_leverage")) or safe_float(DEFAULTS.get("fx_leverage")) or 1.0
            use_ratio = safe_float(ctrl.get("fx_collateral_use_ratio")) or safe_float(DEFAULTS.get("fx_collateral_use_ratio")) or 1.0
            cap_notional = None if collateral is None else float(collateral) * float(lev) * float(use_ratio)

            snap.update(
                {
                    "collateral_jpy": collateral,
                    "open_position_pnl": open_pnl,
                    "require_collateral": require_col,
                    "keep_rate": keep_rate,
                    "fx_leverage": float(lev),
                    "fx_collateral_use_ratio": float(use_ratio),
                    "cap_notional_jpy": cap_notional,
                }
            )
        else:
            balances = client.get_balance()
            by_ccy: Dict[str, Dict[str, Optional[float]]] = {}
            for r in balances:
                ccy = str(r.get("currency_code", "")).upper().strip()
                if not ccy:
                    continue
                by_ccy[ccy] = {
                    "amount": safe_float(r.get("amount")),
                    "available": safe_float(r.get("available")),
                }
            snap.update(
                {
                    "balances": by_ccy,
                    "jpy_amount": (by_ccy.get("JPY") or {}).get("amount"),
                    "jpy_available": (by_ccy.get("JPY") or {}).get("available"),
                    "btc_amount": (by_ccy.get("BTC") or {}).get("amount"),
                    "btc_available": (by_ccy.get("BTC") or {}).get("available"),
                }
            )
        return True, snap, "ok"
    except Exception as e:
        return False, {}, str(e)


def _build_live_client(ctrl: Dict[str, str]):
    from exchange.bitflyer_private import BitflyerPrivateClient
    from tools.keychain_secret import read_pair

    exchange_name = str(ctrl.get("exchange_name", DEFAULTS.get("exchange_name", "bitflyer"))).strip().lower()
    if exchange_name != "bitflyer":
        raise RuntimeError(f"exchange_name={exchange_name} は未実装です（現状は bitflyer のみ対応）")

    service = str(ctrl.get("keychain_service", DEFAULTS["keychain_service"])).strip()
    account_key = str(ctrl.get("keychain_account_key", DEFAULTS["keychain_account_key"])).strip()
    account_secret = str(ctrl.get("keychain_account_secret", DEFAULTS["keychain_account_secret"])).strip()
    api_key, api_secret = read_pair(service=service, account_key=account_key, account_secret=account_secret)
    return BitflyerPrivateClient(api_key=api_key, api_secret=api_secret)


def _fetch_public_ticker(product_code: str) -> Dict[str, Any]:
    url = f"https://api.bitflyer.com/v1/ticker?product_code={urllib.parse.quote(product_code)}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _wait_child_order_result(client: Any, product_code: str, acceptance_id: str, timeout_sec: int = 20) -> Tuple[float, Optional[float], str]:
    end_ts = time.time() + max(2, int(timeout_sec))
    last_filled = 0.0
    last_avg: Optional[float] = None
    last_state = "UNKNOWN"
    while time.time() < end_ts:
        try:
            rows = client.get_child_orders(
                product_code=product_code,
                child_order_acceptance_id=acceptance_id,
                count=1,
            )
            if rows:
                row = rows[0]
                last_state = str(row.get("child_order_state", last_state))
                f = safe_float(row.get("executed_size"))
                if f is not None:
                    last_filled = float(f)
                a = safe_float(row.get("average_price"))
                if a is not None:
                    last_avg = float(a)
                if last_state in ("COMPLETED", "CANCELED", "EXPIRED", "REJECTED"):
                    break
        except Exception:
            pass
        time.sleep(1.0)
    return last_filled, last_avg, last_state


def _fx_net_position(client: Any, product_code: str) -> Tuple[float, float, float]:
    rows = client.get_positions(product_code=product_code)
    buy_total = 0.0
    sell_total = 0.0
    for row in rows:
        side = str(row.get("side", "")).upper()
        sz = safe_float(row.get("size")) or 0.0
        if side == "BUY":
            buy_total += float(sz)
        elif side == "SELL":
            sell_total += float(sz)
    return buy_total - sell_total, buy_total, sell_total


def fetch_live_position_snapshot(ctrl: Dict[str, str]) -> Tuple[bool, Dict[str, Any], str]:
    market_type = str(ctrl.get("market_type", DEFAULTS["market_type"])).strip().upper()
    product_code = str(ctrl.get("product_code", DEFAULTS["product_code"])).strip()
    if market_type not in ("FX", "CFD", "LIGHTNING"):
        return False, {}, f"market_type={market_type} は対象外です（FX/CFD/LIGHTNINGのみ）。"
    if not product_code:
        return False, {}, "product_code が空です。"
    try:
        client = _build_live_client(ctrl)
        net, buy_total, sell_total = _fx_net_position(client, product_code)
        return True, {
            "market_type": market_type,
            "product_code": product_code,
            "net_position_btc": float(net),
            "buy_total_btc": float(buy_total),
            "sell_total_btc": float(sell_total),
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, "ok"
    except Exception as e:
        return False, {}, str(e)


def _today_trade_log_path(main_dir: Path, logs_dir: Optional[Path]) -> Path:
    p = logs_dir or find_logs_dir(main_dir) or (main_dir.parent / "logs")
    p.mkdir(parents=True, exist_ok=True)
    return p / f"trade_log_{datetime.now().strftime('%Y%m%d')}.csv"


def _append_trade_log_row(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    out = {k: row.get(k, "") for k in TRADE_LOG_FIELDS}
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_LOG_FIELDS, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerow(out)


def force_exit_live_position(
    *,
    main_dir: Path,
    ctrl: Dict[str, str],
    state_path: Path,
    logs_dir: Optional[Path],
) -> Tuple[bool, str]:
    market_type = str(ctrl.get("market_type", DEFAULTS["market_type"])).strip().upper()
    product_code = str(ctrl.get("product_code", DEFAULTS["product_code"])).strip()
    if market_type not in ("FX", "CFD", "LIGHTNING"):
        return False, f"強制エグジット対象外です: market_type={market_type}"
    if not product_code:
        return False, "product_code が空です。"

    try:
        client = _build_live_client(ctrl)
    except Exception as e:
        return False, f"live client 初期化失敗: {e}"

    state_obj = load_json(state_path) if state_path.exists() else {}
    if not isinstance(state_obj, dict):
        state_obj = {}
    op = state_obj.get("_open_pos") if isinstance(state_obj.get("_open_pos"), dict) else None
    op_is_live = bool(op) and str((op or {}).get("exec_mode", "")).strip().upper() == "LIVE"
    now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _record_force_exit_event(event: Dict[str, Any]) -> None:
        hist = state_obj.get("_manual_force_exit_history")
        if not isinstance(hist, list):
            hist = []
        hist.append(event)
        if len(hist) > 200:
            hist = hist[-100:]
        state_obj["_manual_force_exit_history"] = hist
        state_obj["_manual_force_exit_last"] = event
        _write_json_dict(state_path, state_obj)

    try:
        net_before, _, _ = _fx_net_position(client, product_code)
    except Exception as e:
        _record_force_exit_event(
            {
                "time": now_s,
                "status": "POSITION_FETCH_ERROR",
                "product_code": product_code,
                "error": str(e),
            }
        )
        return False, f"現在ポジション取得失敗: {e}"

    eps = 1e-10
    if abs(net_before) <= eps:
        # exchange side has no position. clear stale state open_pos if present.
        if op and op_is_live:
            state_obj.pop("_open_pos", None)
            state_obj.pop("_pending_entry", None)
            state_obj.pop("_pending_exit", None)
            _record_force_exit_event(
                {
                    "time": now_s,
                    "status": "NO_POSITION_STATE_CLEARED",
                    "product_code": product_code,
                    "net_before": 0.0,
                    "net_after": 0.0,
                    "filled": 0.0,
                    "order_ids": "",
                }
            )
            return True, "取引所ポジションは0でした。state上の open_pos をクリアしました。"
        if op and not op_is_live:
            _record_force_exit_event(
                {
                    "time": now_s,
                    "status": "NO_POSITION_STATE_KEEP",
                    "product_code": product_code,
                    "net_before": 0.0,
                    "net_after": 0.0,
                    "filled": 0.0,
                    "order_ids": "",
                }
            )
            return True, "取引所ポジションは0です。state上の open_pos は LIVE ではないため変更していません。"
        _record_force_exit_event(
            {
                "time": now_s,
                "status": "NO_POSITION",
                "product_code": product_code,
                "net_before": 0.0,
                "net_after": 0.0,
                "filled": 0.0,
                "order_ids": "",
            }
        )
        return True, "取引所ポジションは0です（クローズ済み）。"

    close_side = "SELL" if net_before > 0 else "BUY"
    close_size = abs(float(net_before))
    order_ids: List[str] = []
    total_filled = 0.0
    last_avg: Optional[float] = None

    try:
        oid = client.send_child_order(
            product_code=product_code,
            side=close_side,
            size=close_size,
            child_order_type="MARKET",
            minute_to_expire=1,
            time_in_force="GTC",
        )
        order_ids.append(str(oid))
        filled, avg, _ = _wait_child_order_result(client, product_code, str(oid), timeout_sec=20)
        total_filled += max(0.0, float(filled))
        if avg is not None:
            last_avg = float(avg)
    except Exception as e:
        _record_force_exit_event(
            {
                "time": now_s,
                "status": "SEND_ERROR",
                "product_code": product_code,
                "close_side": close_side,
                "net_before": round(float(net_before), 8),
                "error": str(e),
            }
        )
        return False, f"強制エグジット注文失敗: {e}"

    # one retry for remaining amount, if any
    try:
        net_after_1, _, _ = _fx_net_position(client, product_code)
    except Exception:
        net_after_1 = net_before - total_filled if net_before > 0 else net_before + total_filled
    remaining = abs(float(net_after_1))
    if remaining > 1e-6:
        try:
            oid2 = client.send_child_order(
                product_code=product_code,
                side=close_side,
                size=remaining,
                child_order_type="MARKET",
                minute_to_expire=1,
                time_in_force="GTC",
            )
            order_ids.append(str(oid2))
            filled2, avg2, _ = _wait_child_order_result(client, product_code, str(oid2), timeout_sec=20)
            total_filled += max(0.0, float(filled2))
            if avg2 is not None:
                last_avg = float(avg2)
        except Exception:
            pass

    buy_after = sell_after = 0.0
    try:
        net_after, buy_after, sell_after = _fx_net_position(client, product_code)
    except Exception as e:
        _record_force_exit_event(
            {
                "time": now_s,
                "status": "VERIFY_ERROR",
                "product_code": product_code,
                "close_side": close_side,
                "net_before": round(float(net_before), 8),
                "filled": round(float(total_filled), 8),
                "order_ids": ",".join(order_ids),
                "error": str(e),
            }
        )
        return False, f"クローズ後ポジション確認失敗: {e}"

    # write state and a contract-safe log row for traceability.
    state_obj.pop("_pending_entry", None)
    state_obj.pop("_pending_exit", None)
    if abs(float(net_after)) <= 1e-6 and (op_is_live or not op):
        state_obj.pop("_open_pos", None)
    _record_force_exit_event(
        {
            "time": now_s,
            "status": "OK" if abs(float(net_after)) <= 1e-6 else "REMAIN",
            "product_code": product_code,
            "close_side": close_side,
            "net_before": round(float(net_before), 8),
            "net_after": round(float(net_after), 8),
            "filled": round(float(total_filled), 8),
            "order_ids": ",".join(order_ids),
        }
    )

    bid = ask = ltp = None
    try:
        tick = _fetch_public_ticker(product_code)
        bid = safe_float(tick.get("best_bid"))
        ask = safe_float(tick.get("best_ask"))
        ltp = safe_float(tick.get("ltp"))
    except Exception:
        pass

    note_parts = [
        "MANUAL_FORCE_EXIT",
        f"exec=LIVE",
        f"product={product_code}",
        f"close_side={close_side}",
        f"net_before={float(net_before):.8f}",
        f"net_after={float(net_after):.8f}",
        f"filled={float(total_filled):.8f}",
        f"order_id={','.join(order_ids)}",
    ]
    if op and op_is_live:
        stage = str(op.get("effective_stage", "")).strip()
        if stage:
            note_parts.append(f"stage={stage}")
    note = " ".join(x for x in note_parts if x)

    row = {
        "time": now_s,
        "result": "PAPER_EXIT_TIMEOUT" if (op and op_is_live) else "OBSERVE_OK",
        "side": str((op or {}).get("side", "BUY")).upper() if (op and op_is_live) else "",
        "price": safe_float((op or {}).get("entry_price")) if (op and op_is_live) else "",
        "size": safe_float((op or {}).get("size")) if (op and op_is_live) else round(float(abs(net_before)), 8),
        "ltp": (last_avg if last_avg is not None else ltp) if (last_avg is not None or ltp is not None) else "",
        "best_bid": bid if bid is not None else "",
        "best_ask": ask if ask is not None else "",
        "spread_pct": ((float(ask) - float(bid)) / float(bid) * 100.0) if (bid and ask and bid > 0) else "",
        "limit_pct": "",
        "ma_fast": (op or {}).get("ma_fast", "") if (op and op_is_live) else "",
        "ma_slow": (op or {}).get("ma_slow", "") if (op and op_is_live) else "",
        "trend": (op or {}).get("trend", "") if (op and op_is_live) else "",
        "signal": (op or {}).get("signal", "") if (op and op_is_live) else "",
        "note": note,
        "pos_id": (op or {}).get("pos_id", "") if (op and op_is_live) else "",
    }
    try:
        _append_trade_log_row(_today_trade_log_path(main_dir, logs_dir), row)
    except Exception:
        pass

    if abs(float(net_after)) <= 1e-6:
        return True, (
            f"強制エグジット完了: side={close_side} size={close_size:.8f} "
            f"filled={total_filled:.8f} net_after={net_after:.8f}"
        )
    return False, (
        f"強制エグジット後も残ポジがあります: net_after={net_after:.8f} "
        f"(buy={buy_after:.8f}, sell={sell_after:.8f})"
    )


def compute_ret_pct(entry_price: Optional[float], exit_price: Optional[float], side: str) -> Optional[float]:
    if entry_price is None or exit_price is None:
        return None
    if entry_price == 0:
        return None
    r = (exit_price - entry_price) / entry_price
    if str(side).upper() == "SELL":
        r = -r
    return r * 100.0


@st.cache_data(show_spinner=False)
def _collect_json_reports_cached(out_dir: Path, cache_token: str = "") -> List[Path]:
    _ = cache_token
    if not out_dir.exists():
        return []
    cands: List[Path] = []
    for p in out_dir.glob("daily_report_*.json"):
        if REPORT_JSON_RE.search(p.name):
            cands.append(p)
    cands.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
    return cands


def collect_json_reports(out_dir: Path) -> List[Path]:
    if not out_dir.exists():
        return []
    return _collect_json_reports_cached(out_dir, dir_cache_token(out_dir))


@st.cache_data(show_spinner=False)
def _load_json_cached(path: Path, cache_token: str = "") -> Optional[Dict[str, Any]]:
    _ = cache_token
    try:
        txt = path.read_text(encoding="utf-8")
        return json.loads(txt)
    except Exception:
        # try utf-8-sig
        try:
            txt = path.read_text(encoding="utf-8-sig")
            return json.loads(txt)
        except Exception:
            return None


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    return _load_json_cached(path, file_cache_token(path))


def normalize_daily_report_json(j: Dict[str, Any]) -> Dict[str, Any]:
    # Ensure required top-level keys with defaults per SPEC
    if not isinstance(j, dict):
        return {}
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    additions: List[str] = []

    def sset(d: Dict[str, Any], key: str, val: Any, path: str):
        if key not in d:
            additions.append(path)
        d.setdefault(key, val)

    # meta
    if "meta" not in j:
        additions.append("meta")
        j["meta"] = {}
    meta = j["meta"]
    sset(meta, "spec", "UNKNOWN", "meta.spec")
    # generated_at_jst: if missing, insert now
    if "generated_at_jst" not in meta:
        additions.append("meta.generated_at_jst")
        meta["generated_at_jst"] = now
    sset(meta, "target_day8", meta.get("target_day8", "00000000"), "meta.target_day8")
    sset(meta, "rows_total", meta.get("rows_total", 0), "meta.rows_total")
    sset(meta, "rows_used", meta.get("rows_used", 0), "meta.rows_used")

    # daily
    if "daily" not in j:
        additions.append("daily")
        j["daily"] = {}
    daily = j["daily"]
    for k in ("paper_n", "observe_n", "skip_n", "hold_n", "exit_n", "error_n", "paper_rate_pct"):
        if k not in daily:
            additions.append(f"daily.{k}")
        daily.setdefault(k, 0)

    # by_side
    if "by_side" not in j:
        additions.append("by_side")
        j["by_side"] = {}
    bs = j["by_side"]
    for side in ("BUY", "SELL", "UNKNOWN"):
        if side not in bs:
            additions.append(f"by_side.{side}")
            bs[side] = {}
        for k in ("paper_n", "observe_n", "skip_n", "hold_n", "exit_n", "paper_rate_pct", "tp_n", "sl_n", "timeout_n", "partial_tp_n", "eod_n"):
            if k not in bs[side]:
                additions.append(f"by_side.{side}.{k}")
            bs[side].setdefault(k, 0)

    # by_hour
    if "by_hour" not in j:
        additions.append("by_hour")
        j["by_hour"] = {}
    bh = j["by_hour"]
    for h in range(24):
        hh = str(h)
        if hh not in bh:
            additions.append(f"by_hour.{hh}")
            bh[hh] = {}
        for k in ("paper_n", "observe_n", "hold_n", "exit_n", "paper_rate_pct", "spread_avg_pct"):
            if k not in bh[hh]:
                additions.append(f"by_hour.{hh}.{k}")
            bh[hh].setdefault(k, 0)

    # spread
    if "spread" not in j:
        additions.append("spread")
        j["spread"] = {}
    sp = j["spread"]
    for k in ("avg_pct", "p90_pct", "max_pct", "over_limit_n"):
        if k not in sp:
            additions.append(f"spread.{k}")
        sp.setdefault(k, 0)

    # exit_integrity
    if "exit_integrity" not in j:
        additions.append("exit_integrity")
        j["exit_integrity"] = {}
    ei = j["exit_integrity"]
    for k in ("paper_pos_ids", "exit_pos_ids", "open_pos_ids", "missing_exit_pos_ids"):
        if k not in ei:
            additions.append(f"exit_integrity.{k}")
        ei.setdefault(k, [])

    # mae_mfe
    if "mae_mfe" not in j:
        additions.append("mae_mfe")
        j["mae_mfe"] = {}
    mm = j["mae_mfe"]
    if "per_pos" not in mm:
        additions.append("mae_mfe.per_pos")
    mm.setdefault("per_pos", {})
    if "summary" not in mm:
        additions.append("mae_mfe.summary")
    mm.setdefault("summary", {})

    # issues normalization
    orig_issues = j.get("issues", None)
    norm_issues = []
    if orig_issues is None:
        additions.append("issues")
    if isinstance(orig_issues, list):
        for it in orig_issues:
            if isinstance(it, dict):
                norm_issues.append(it)
            else:
                s = str(it)
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, dict):
                        norm_issues.append(parsed)
                        additions.append("issues.parsed_dict")
                        continue
                except Exception:
                    pass
                norm_issues.append(s)
    else:
        # if issues is a single object/string, normalize to list
        additions.append("issues.normalized_to_list")
        s = str(orig_issues)
        try:
            parsed = json.loads(s)
            if isinstance(parsed, dict):
                norm_issues.append(parsed)
            else:
                norm_issues.append(s)
        except Exception:
            norm_issues.append(s)
    j["issues"] = norm_issues

    # attach metadata about what was added
    if additions:
        j.setdefault("_normalized", {})
        j["_normalized"]["added_keys"] = additions

    return j


def dig_first(d: Dict[str, Any], keys: List[str], default=None):
    """
    SPEC note: If key names change, add here for compatibility.
    """
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        if k in cur:
            cur = cur[k]
        else:
            return default
    return cur


# =========================
# pos_id model
# =========================
@dataclass
class PosView:
    pos_id: str
    status: str  # OPEN/CLOSED/UNKNOWN/ERROR
    entry_time: Optional[str]
    entry_side: Optional[str]
    entry_price: Optional[float]
    exit_time: Optional[str]
    exit_result: Optional[str]
    exit_ltp: Optional[float]
    ret_pct_est: Optional[float]  # estimate
    ai_score: Optional[float]
    ai_pass: Optional[bool]
    mae: Optional[float]
    mfe: Optional[float]
    source: str  # "JSON" or "LOG_FALLBACK"
    notes: str = ""


# =========================
# From JSON (priority)
# =========================
def posviews_from_audit_json(j: Dict[str, Any]) -> Tuple[List[PosView], List[str]]:
    issues: List[str] = []
    per_pos = dig_first(j, ["per_pos"], default={})
    if not isinstance(per_pos, dict):
        per_pos = {}

    issues_raw = dig_first(j, ["issues"], default=[])
    if isinstance(issues_raw, list):
        for x in issues_raw:
            try:
                issues.append(str(x))
            except Exception:
                pass

    out: List[PosView] = []
    for pid, obj in per_pos.items():
        if not isinstance(obj, dict):
            continue

        status = str(obj.get("status", "UNKNOWN"))
        if status not in ("OPEN", "CLOSED", "UNKNOWN", "ERROR"):
            status = "UNKNOWN"

        entry = obj.get("entry", {}) if isinstance(obj.get("entry", {}), dict) else {}
        exit_ = obj.get("exit", {}) if isinstance(obj.get("exit", {}), dict) else {}
        ai = obj.get("ai", {}) if isinstance(obj.get("ai", {}), dict) else {}

        entry_time = entry.get("time")
        entry_side = entry.get("side")
        entry_price = safe_float(entry.get("price"))

        exit_time = exit_.get("time")
        exit_result = exit_.get("result")
        exit_ltp = safe_float(exit_.get("ltp"))

        # ret_pct is estimate (fee not included)
        ret_pct = compute_ret_pct(entry_price, exit_ltp, str(entry_side or ""))

        ai_score = safe_float(ai.get("score"))
        ai_pass = ai.get("pass")
        if isinstance(ai_pass, str):
            ai_pass = ai_pass.strip().lower() in BOOL_TRUE
        elif not isinstance(ai_pass, bool):
            ai_pass = None

        mae = safe_float(obj.get("mae"))
        mfe = safe_float(obj.get("mfe"))

        out.append(
            PosView(
                pos_id=str(pid),
                status=status,
                entry_time=str(entry_time) if entry_time is not None else None,
                entry_side=str(entry_side) if entry_side is not None else None,
                entry_price=entry_price,
                exit_time=str(exit_time) if exit_time is not None else None,
                exit_result=str(exit_result) if exit_result is not None else None,
                exit_ltp=exit_ltp,
                ret_pct_est=ret_pct,
                ai_score=ai_score,
                ai_pass=ai_pass,
                mae=mae,
                mfe=mfe,
                source="JSON",
                notes="（推定）ret_pctはfee未加味",
            )
        )

    # stable ordering: open first, then recent-ish (entry_time string sort)
    def _key(p: PosView):
        st_rank = {"OPEN": 0, "UNKNOWN": 1, "ERROR": 2, "CLOSED": 3}.get(p.status, 9)
        t = p.entry_time or ""
        return (st_rank, t)

    out.sort(key=_key)
    return out, issues


# =========================
# From LOG fallback
# =========================
def posviews_from_logs(rows: List[Dict[str, Any]]) -> Tuple[List[PosView], List[str]]:
    """
    Fallback rule (SPEC):
    - If no JSON, infer from logs.
    - This is "推定" (estimate).
    """
    issues: List[str] = []
    by_pid: Dict[str, List[Dict[str, Any]]] = {}

    for r in rows:
        pid = str(r.get("pos_id", "")).strip()
        if not pid:
            continue
        by_pid.setdefault(pid, []).append(r)

    out: List[PosView] = []

    for pid, rr in by_pid.items():
        # sort by time string if present
        rr_sorted = sorted(rr, key=lambda x: str(x.get("time", "")))

        # Entry: first PAPER with side BUY/SELL
        entry_row = None
        for r in rr_sorted:
            if str(r.get("result", "")).strip() == "PAPER":
                entry_row = r
                break

        # Exit: last PAPER_EXIT_* row
        exit_row = None
        for r in rr_sorted:
            if str(r.get("result", "")).startswith("PAPER_EXIT"):
                exit_row = r
        # status inference
        if entry_row and exit_row:
            status = "CLOSED"
        elif entry_row and not exit_row:
            status = "OPEN"
        else:
            status = "UNKNOWN"

        entry_time = str(entry_row.get("time")) if entry_row else None
        entry_side = str(entry_row.get("side")) if entry_row else None
        entry_price = safe_float(entry_row.get("price")) if entry_row else None

        exit_time = str(exit_row.get("time")) if exit_row else None
        exit_result = str(exit_row.get("result")) if exit_row else None
        exit_ltp = safe_float(exit_row.get("ltp")) if exit_row else None

        ret_pct = compute_ret_pct(entry_price, exit_ltp, str(entry_side or ""))

        # optional ai_score (if present on rows; pick from entry if present else latest)
        ai_score = None
        for cand in [entry_row, exit_row] + rr_sorted[::-1]:
            if not cand:
                continue
            if "ai_score" in cand:
                ai_score = safe_float(cand.get("ai_score"))
                if ai_score is not None:
                    break

        notes = "（推定）ログからOPEN/CLOSEDを推定 / ret_pctはfee未加味"

        if status == "UNKNOWN":
            issues.append(f"WARN pos_id={pid} entry/exitが特定できず（推定不能）")

        out.append(
            PosView(
                pos_id=pid,
                status=status,
                entry_time=entry_time,
                entry_side=entry_side,
                entry_price=entry_price,
                exit_time=exit_time,
                exit_result=exit_result,
                exit_ltp=exit_ltp,
                ret_pct_est=ret_pct,
                ai_score=ai_score,
                ai_pass=None,
                mae=None,
                mfe=None,
                source="LOG_FALLBACK",
                notes=notes,
            )
        )

    # sort: open first, then pid
    def _key(p: PosView):
        st_rank = {"OPEN": 0, "UNKNOWN": 1, "ERROR": 2, "CLOSED": 3}.get(p.status, 9)
        return (st_rank, p.pos_id)

    out.sort(key=_key)
    return out, issues


def build_position_metrics_from_logs(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Build one row per pos_id from raw log rows for analytics visualization.
    pnl_est is estimated from entry/exit and size (fee not included).
    """
    by_pid: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        pid = str(r.get("pos_id", "")).strip()
        if not pid:
            continue
        by_pid.setdefault(pid, []).append(r)

    out_rows: List[Dict[str, Any]] = []
    for pid, rr in by_pid.items():
        rr_sorted = sorted(rr, key=lambda x: str(x.get("time", "")))
        entry_row = None
        for r in rr_sorted:
            if str(r.get("result", "")).strip() == "PAPER":
                entry_row = r
                break
        exit_row = None
        for r in rr_sorted:
            if str(r.get("result", "")).startswith("PAPER_EXIT"):
                exit_row = r

        if entry_row and exit_row:
            status = "CLOSED"
        elif entry_row and not exit_row:
            status = "OPEN"
        else:
            status = "UNKNOWN"

        side = str(entry_row.get("side")) if entry_row else ""
        entry_price = safe_float(entry_row.get("price")) if entry_row else None
        size = safe_float(entry_row.get("size")) if entry_row else None
        exit_ltp = safe_float(exit_row.get("ltp")) if exit_row else None
        ret_pct = compute_ret_pct(entry_price, exit_ltp, side)
        trend = str(entry_row.get("trend", "")).strip().upper() if entry_row else "UNKNOWN"
        signal = str(entry_row.get("signal", "")).strip().upper() if entry_row else "NONE"
        exit_result = str(exit_row.get("result", "")).strip() if exit_row else ""

        # Execution mode inference:
        # - LIVE paths keep result contract as PAPER/PAPER_EXIT_*, so infer from note metadata.
        # - If not present, default to PAPER (backward compatibility for old logs).
        entry_note = str(entry_row.get("note", "")).strip() if entry_row else ""
        exit_note = str(exit_row.get("note", "")).strip() if exit_row else ""
        exec_mode = "PAPER"
        for n in (exit_note, entry_note):
            v = _extract_note_kv(n, "exec").strip().upper()
            if v in ("LIVE", "PAPER"):
                exec_mode = v
                break
            if "exec=LIVE" in n:
                exec_mode = "LIVE"
                break
            if "exec=PAPER" in n:
                exec_mode = "PAPER"
                break

        pnl_est = None
        if entry_price is not None and exit_ltp is not None and size is not None:
            sign = -1.0 if str(side).upper() == "SELL" else 1.0
            pnl_est = (exit_ltp - entry_price) * size * sign

        out_rows.append(
            {
                "pos_id": pid,
                "status": status,
                "side": side,
                "entry_time": str(entry_row.get("time")) if entry_row else None,
                "exit_time": str(exit_row.get("time")) if exit_row else None,
                "entry_price": entry_price,
                "exit_ltp": exit_ltp,
                "size": size,
                "exec_mode": exec_mode,
                "trend": trend if trend else "UNKNOWN",
                "signal": signal if signal else "NONE",
                "exit_result": exit_result,
                "entry_note": entry_note,
                "exit_note": exit_note,
                "ret_pct_est": ret_pct,
                "pnl_est": pnl_est,
            }
        )

    if not out_rows:
        return pd.DataFrame()

    df = pd.DataFrame(out_rows)
    df["entry_time_dt"] = pd.to_datetime(df["entry_time"], errors="coerce")
    df["exit_time_dt"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df["time_dt"] = df["exit_time_dt"].fillna(df["entry_time_dt"])
    df["entry_hour"] = df["entry_time_dt"].dt.hour
    df["exit_hour"] = df["exit_time_dt"].dt.hour
    df = df.sort_values(["time_dt", "pos_id"], ascending=[True, True]).reset_index(drop=True)
    return df


def calc_max_drawdown(series: pd.Series) -> float:
    if series is None or len(series) == 0:
        return 0.0
    s = pd.to_numeric(series, errors="coerce").fillna(0.0)
    run_max = s.cummax()
    dd = s - run_max
    return float(dd.min()) if len(dd) else 0.0


def calc_max_losing_streak(pnl_series: pd.Series) -> int:
    if pnl_series is None or len(pnl_series) == 0:
        return 0
    s = pd.to_numeric(pnl_series, errors="coerce")
    cur = 0
    best = 0
    for v in s:
        if pd.isna(v):
            continue
        if float(v) < 0:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return int(best)


def build_hourly_summary(df_closed: pd.DataFrame) -> pd.DataFrame:
    if df_closed is None or df_closed.empty:
        return pd.DataFrame()
    d = df_closed.copy()
    d["hour"] = pd.to_datetime(d["time_dt"], errors="coerce").dt.hour
    d = d.dropna(subset=["hour"]).copy()
    if d.empty:
        return pd.DataFrame()
    out = (
        d.groupby("hour", dropna=False)
        .agg(
            trades=("pos_id", "count"),
            win_rate_pct=("ret_pct_est", lambda x: float((x > 0).mean() * 100.0) if len(x) else 0.0),
            ret_pct_sum=("ret_pct_est", "sum"),
            pnl_est_sum=("pnl_est", "sum"),
            avg_pnl_est=("pnl_est", "mean"),
        )
        .reset_index()
        .sort_values("hour")
    )
    out["hour_label"] = out["hour"].astype(int).astype(str).str.zfill(2) + ":00"
    return out


def build_repeated_loss_patterns(df_closed: pd.DataFrame, min_losses: int = 2) -> pd.DataFrame:
    if df_closed is None or df_closed.empty:
        return pd.DataFrame()
    d = df_closed.copy()
    d["ret_pct_est"] = pd.to_numeric(d.get("ret_pct_est"), errors="coerce")
    d["pnl_est"] = pd.to_numeric(d.get("pnl_est"), errors="coerce")
    d = d[d["ret_pct_est"] < 0].copy()
    if d.empty:
        return pd.DataFrame()

    defaults: Dict[str, str] = {
        "side": "UNKNOWN",
        "trend": "UNKNOWN",
        "signal": "NONE",
        "exit_result": "UNKNOWN",
        "exec_mode": "PAPER",
    }
    for col, default in defaults.items():
        if col not in d.columns:
            d[col] = default
        d[col] = d[col].astype(str).str.strip().replace({"": default})
        d.loc[d[col].isna(), col] = default
        d[col] = d[col].str.upper()

    if "entry_hour" not in d.columns:
        d["entry_hour"] = pd.to_datetime(d.get("entry_time_dt"), errors="coerce").dt.hour
    d["entry_hour"] = pd.to_numeric(d["entry_hour"], errors="coerce").fillna(-1).astype(int)
    d["entry_hour_label"] = np.where(
        d["entry_hour"] >= 0,
        d["entry_hour"].astype(str).str.zfill(2),
        "--",
    )

    grouped = (
        d.groupby(
            ["side", "trend", "signal", "entry_hour", "entry_hour_label", "exit_result", "exec_mode"],
            dropna=False,
        )
        .agg(
            loss_n=("pos_id", "count"),
            loss_ret_sum_pct=("ret_pct_est", "sum"),
            avg_loss_ret_pct=("ret_pct_est", "mean"),
            avg_loss_pnl_est=("pnl_est", "mean"),
            last_seen=("time_dt", "max"),
        )
        .reset_index()
    )
    if grouped.empty:
        return grouped

    grouped["loss_share_pct"] = grouped["loss_n"] / float(len(d)) * 100.0
    grouped = grouped[grouped["loss_n"] >= max(1, int(min_losses))].copy()
    grouped = grouped.sort_values(
        ["loss_n", "loss_ret_sum_pct", "last_seen"],
        ascending=[False, True, False],
    ).reset_index(drop=True)
    grouped["pattern"] = (
        grouped["side"]
        + " / "
        + grouped["trend"]
        + " / "
        + grouped["signal"]
        + " / "
        + grouped["entry_hour_label"]
        + "h / "
        + grouped["exit_result"]
        + " / "
        + grouped["exec_mode"]
    )
    return grouped


def build_trade_timeline_frames(rows: List[Dict[str, Any]]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Build timeline data for charting.
    - price_df: chronological price points (ltp/bid/ask)
    - event_df: PAPER ENTRY / PAPER_EXIT markers with side and pos_id
    """
    price_rows: List[Dict[str, Any]] = []
    event_rows: List[Dict[str, Any]] = []

    for r in rows:
        t = str(r.get("time", "")).strip()
        if not t:
            continue
        td = pd.to_datetime(t, errors="coerce")
        if pd.isna(td):
            continue

        ltp = safe_float(r.get("ltp"))
        bid = safe_float(r.get("best_bid"))
        ask = safe_float(r.get("best_ask"))
        if ltp is not None or bid is not None or ask is not None:
            price_rows.append({"time_dt": td, "ltp": ltp, "best_bid": bid, "best_ask": ask})

        result = str(r.get("result", "")).strip()
        if result == "PAPER" or result.startswith("PAPER_EXIT"):
            side = str(r.get("side", "")).strip().upper()
            pos_id = str(r.get("pos_id", "")).strip()
            px = safe_float(r.get("price"))
            ev_price = ltp if ltp is not None else px
            if ev_price is None:
                continue

            if result == "PAPER":
                event_kind = "ENTRY_BUY" if side == "BUY" else "ENTRY_SELL"
                event_label = "ENTRY BUY" if side == "BUY" else "ENTRY SELL"
            else:
                event_kind = "EXIT"
                event_label = result

            event_rows.append(
                {
                    "time_dt": td,
                    "event_kind": event_kind,
                    "event_label": event_label,
                    "side": side,
                    "pos_id": pos_id,
                    "price_plot": ev_price,
                    "price": px,
                    "ltp": ltp,
                    "size": safe_float(r.get("size")),
                    "result": result,
                }
            )

    price_df = pd.DataFrame(price_rows)
    if not price_df.empty:
        price_df = price_df.sort_values("time_dt").reset_index(drop=True)
        price_df = price_df.drop_duplicates(subset=["time_dt"], keep="last")

    event_df = pd.DataFrame(event_rows)
    if not event_df.empty:
        event_df = event_df.sort_values("time_dt").reset_index(drop=True)

    return price_df, event_df


def build_ohlc_from_price_df(price_df: pd.DataFrame, *, interval_rule: str, price_col: str = "ltp") -> pd.DataFrame:
    if price_df.empty or price_col not in price_df.columns or "time_dt" not in price_df.columns:
        return pd.DataFrame()
    d = price_df[["time_dt", price_col]].copy()
    d[price_col] = pd.to_numeric(d[price_col], errors="coerce")
    d["time_dt"] = pd.to_datetime(d["time_dt"], errors="coerce")
    d = d.dropna(subset=["time_dt", price_col])
    if d.empty:
        return pd.DataFrame()
    d = d.sort_values("time_dt").drop_duplicates(subset=["time_dt"], keep="last")
    ohlc = d.set_index("time_dt")[price_col].resample(interval_rule).ohlc().dropna()
    if ohlc.empty:
        return pd.DataFrame()
    out = ohlc.reset_index()
    out.columns = ["time_dt", "open", "high", "low", "close"]
    return out


def render_backtest_lab_tab(main_dir: Path, logs_dir: Optional[Path]) -> None:
    st.subheader("🔬 検証ラボ（過去チャート・ロジック実験）")
    st.caption(
        "過去の trade_log の ltp から疑似OHLCを作り、ロジック候補を読み取り専用で検証します。"
        "実弾発注・CONTROL変更・VM操作は行いません。"
    )
    try:
        from tools import backtest_lab
    except Exception as e:
        st.error(f"backtest_lab の読み込みに失敗しました: {e}")
        return

    if not logs_dir or not logs_dir.exists():
        st.warning("logs ディレクトリが見つかりません。")
        return

    days = list_log_days(logs_dir)
    if not days:
        st.warning("trade_log_YYYYMMDD.csv が見つかりません。")
        return

    st.markdown("### 1. データと戦略")
    c1, c2, c3 = st.columns([1.3, 1, 1])
    with c1:
        selected_days = st.multiselect(
            "検証する日付",
            days,
            default=days[: min(5, len(days))],
            key="backtest_days",
            help="複数日を選ぶと連結して検証します。上に出る日付ほど新しいログです。",
        )
    with c2:
        strategy = st.selectbox(
            "戦略",
            ["phase_follow", "ma_cross", "chart_pattern", "aiba_style", "combo_phase_pattern"],
            format_func=lambda x: {
                "phase_follow": "A/B/C局面フォロー",
                "ma_cross": "MAクロス",
                "chart_pattern": "チャートパターン確定",
                "aiba_style": "相場流ラベル",
                "combo_phase_pattern": "局面 + パターン一致",
            }.get(str(x), str(x)),
            key="backtest_strategy",
        )
    with c3:
        timeframe_min = st.number_input("足幅（分）", min_value=1, max_value=60, value=5, step=1, key="backtest_timeframe")

    st.markdown("### 2. パラメータ")
    p1, p2, p3, p4, p5 = st.columns(5)
    with p1:
        fast_n = st.number_input("fast MA", min_value=2, max_value=100, value=5, step=1, key="backtest_fast_n")
    with p2:
        slow_n = st.number_input("slow MA", min_value=3, max_value=240, value=20, step=1, key="backtest_slow_n")
    with p3:
        tp_pct = st.number_input("TP %", min_value=0.01, max_value=5.0, value=0.15, step=0.01, key="backtest_tp_pct")
    with p4:
        sl_pct = st.number_input("SL %", min_value=0.01, max_value=5.0, value=0.12, step=0.01, key="backtest_sl_pct")
    with p5:
        max_hold_bars = st.number_input("最大保有本数", min_value=1, max_value=200, value=12, step=1, key="backtest_max_hold")

    o1, o2 = st.columns(2)
    with o1:
        require_break = st.checkbox("局面フォローは高値/安値ブレイク必須", value=False, key="backtest_require_break")
    with o2:
        require_quality_ok = st.checkbox("チャートパターンは cp_quality=OK のみ", value=True, key="backtest_quality_ok")

    run = st.button("▶ シミュレーション実行", type="primary", width="stretch", key="backtest_run")
    if not run:
        st.info("日付とパラメータを選んで `シミュレーション実行` を押してください。")
        return
    if not selected_days:
        st.warning("検証する日付を1つ以上選んでください。")
        return

    params = backtest_lab.BacktestParams(
        strategy=str(strategy),
        timeframe_min=int(timeframe_min),
        fast_n=int(fast_n),
        slow_n=max(int(slow_n), int(fast_n) + 1),
        tp_pct=float(tp_pct),
        sl_pct=float(sl_pct),
        max_hold_bars=int(max_hold_bars),
        require_break=bool(require_break),
        require_quality_ok=bool(require_quality_ok),
    )
    with st.spinner("過去チャートを再構築して検証中..."):
        result = backtest_lab.build_from_logs(logs_dir, selected_days, params)

    source = result.get("source", {}) if isinstance(result.get("source"), dict) else {}
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), dict) else {}
    candles = result.get("candles", []) if isinstance(result.get("candles"), list) else []
    trades = result.get("trades", []) if isinstance(result.get("trades"), list) else []
    events = result.get("events", []) if isinstance(result.get("events"), list) else []

    st.markdown("### 3. 結果")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("trades", int(metrics.get("trade_n", 0) or 0))
    m2.metric("勝率", f"{float(metrics.get('win_rate_pct', 0.0) or 0.0):.1f}%")
    m3.metric("合計ret", f"{float(metrics.get('ret_sum_pct', 0.0) or 0.0):+.3f}%")
    m4.metric("平均ret", f"{float(metrics.get('avg_ret_pct', 0.0) or 0.0):+.4f}%")
    m5.metric("PF", f"{float(metrics.get('profit_factor', 0.0) or 0.0):.2f}")
    st.caption(
        f"price_points={source.get('price_points', 0)} / candles={source.get('candle_n', 0)} / "
        "手数料・スリッページ未加味。結果は検証用の推定です。"
    )

    if candles:
        candle_df = pd.DataFrame(candles)
        candle_df["time_dt"] = pd.to_datetime(candle_df["start"], errors="coerce")
        if HAS_PLOTLY and not candle_df.empty:
            fig = go.Figure()
            fig.add_trace(
                go.Candlestick(
                    x=candle_df["time_dt"],
                    open=candle_df["open"],
                    high=candle_df["high"],
                    low=candle_df["low"],
                    close=candle_df["close"],
                    name="OHLC",
                    increasing_line_color="#0f766e",
                    decreasing_line_color="#dc2626",
                )
            )
            ev_df = pd.DataFrame(events)
            if not ev_df.empty:
                ev_df["time_dt"] = pd.to_datetime(ev_df["time"], errors="coerce")
                entries = ev_df[ev_df["event"] == "ENTRY"]
                exits = ev_df[ev_df["event"].astype(str).str.startswith("EXIT")]
                if not entries.empty:
                    fig.add_trace(
                        go.Scatter(
                            x=entries["time_dt"],
                            y=entries["price"],
                            mode="markers",
                            marker=dict(size=9, color="#0284c7", symbol="triangle-up"),
                            name="ENTRY",
                            text=entries.get("note"),
                        )
                    )
                if not exits.empty:
                    fig.add_trace(
                        go.Scatter(
                            x=exits["time_dt"],
                            y=exits["price"],
                            mode="markers",
                            marker=dict(size=9, color="#f97316", symbol="x"),
                            name="EXIT",
                            text=exits.get("event"),
                        )
                    )
            fig.update_layout(
                height=520,
                margin=dict(l=10, r=10, t=25, b=10),
                xaxis_rangeslider_visible=False,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig, width="stretch", config=_plotly_interactive_config())
        else:
            st.line_chart(candle_df.set_index("time_dt")["close"])

    tdf = pd.DataFrame(trades)
    if tdf.empty:
        st.warning("この条件では仮想トレードが発生しませんでした。条件を緩めるか、日付を増やしてください。")
    else:
        st.markdown("### 4. 仮想トレード一覧")
        st.dataframe(tdf, width="stretch", height=360)
        st.download_button(
            "CSVダウンロード",
            tdf.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"backtest_lab_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            width="stretch",
        )

    with st.expander("使える戦略の意味", expanded=False):
        st.markdown(
            """
- `A/B/C局面フォロー`: `phase=C` でBUY、`phase=A` でSELL。ブレイク必須にもできます。
- `MAクロス`: fast/slow SMAのゴールデン/デッドクロスで売買。
- `チャートパターン確定`: DOUBLE_TOP/DOUBLE_BOTTOM等の確定方向で売買。
- `相場流ラベル`: くちばし/逆くちばし、PPP/逆PPP、トライ届かずを売買候補化。
- `局面 + パターン一致`: A/B/C局面とチャートパターン方向が一致した時だけ売買。
"""
        )


def _to_jst_naive(ts_like: Any) -> pd.Timestamp:
    ts = pd.to_datetime(ts_like, errors="coerce", utc=True)
    if pd.isna(ts):
        return pd.NaT  # type: ignore[return-value]
    try:
        return ts.tz_convert("Asia/Tokyo").tz_localize(None)
    except Exception:
        try:
            return ts.tz_localize(None)
        except Exception:
            return pd.NaT  # type: ignore[return-value]


@st.cache_data(show_spinner=False, ttl=5)
def fetch_public_executions_df(
    product_code: str,
    count: int = 500,
    lookback_hours: int = 0,
    max_pages: int = 1,
) -> pd.DataFrame:
    page_count = max(10, min(int(count), 500))
    max_pages_n = max(1, min(int(max_pages), 200))
    lookback_h = max(0, int(lookback_hours))

    cutoff: Optional[pd.Timestamp] = None
    if lookback_h > 0:
        cutoff = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None) - pd.Timedelta(hours=lookback_h)

    out_rows: List[Dict[str, Any]] = []
    before_id: Optional[int] = None

    for _ in range(max_pages_n):
        params: Dict[str, Any] = {"product_code": product_code, "count": page_count}
        if before_id is not None:
            params["before"] = int(before_id)
        q = urllib.parse.urlencode(params)
        url = f"https://api.bitflyer.com/v1/executions?{q}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as r:
            rows = json.loads(r.read().decode("utf-8"))

        if not isinstance(rows, list) or not rows:
            break

        oldest_td: Optional[pd.Timestamp] = None
        last_row_id: Optional[int] = None
        for r in rows:
            if not isinstance(r, dict):
                continue
            td = _to_jst_naive(r.get("exec_date"))
            if pd.isna(td):
                continue
            px = safe_float(r.get("price"))
            sz = safe_float(r.get("size"))
            ex_id_raw = r.get("id")
            ex_id: Optional[int] = None
            try:
                if ex_id_raw is not None and str(ex_id_raw).strip() != "":
                    ex_id = int(str(ex_id_raw).strip())
            except Exception:
                ex_id = None
            if px is None:
                continue
            out_rows.append(
                {
                    "time_dt": td,
                    "price": float(px),
                    "size": float(sz or 0.0),
                    "side": str(r.get("side", "")).upper(),
                    "exec_id": int(ex_id) if ex_id is not None else np.nan,
                }
            )
            if oldest_td is None or td < oldest_td:
                oldest_td = td
            if ex_id is not None:
                last_row_id = int(ex_id)

        if lookback_h <= 0:
            break
        if oldest_td is not None and cutoff is not None and oldest_td <= cutoff:
            break
        if last_row_id is None:
            break
        before_id = last_row_id

    if not out_rows:
        return pd.DataFrame()

    df = pd.DataFrame(out_rows)
    if "exec_id" in df.columns:
        df = df.drop_duplicates(subset=["exec_id"], keep="last")
    df = df.sort_values("time_dt").reset_index(drop=True)
    if cutoff is not None:
        df = df[df["time_dt"] >= cutoff].reset_index(drop=True)
    return df


def executions_to_price_df(exec_df: pd.DataFrame) -> pd.DataFrame:
    if exec_df.empty:
        return pd.DataFrame()
    d = exec_df[["time_dt", "price"]].copy()
    d = d.rename(columns={"price": "ltp"})
    d["best_bid"] = np.nan
    d["best_ask"] = np.nan
    return d


def _plotly_interactive_config() -> Dict[str, Any]:
    return {
        "scrollZoom": True,
        "displaylogo": False,
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    }


def _enable_time_price_pan_zoom(fig: Any, *, with_rangeslider: bool = True, y_title: str = "価格") -> None:
    fig.update_xaxes(
        title="時刻",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        rangeslider=dict(visible=with_rangeslider, thickness=0.07),
    )
    fig.update_yaxes(
        title=y_title,
        showspikes=True,
        spikemode="across",
        fixedrange=False,
    )
    fig.update_layout(
        dragmode="pan",
        hovermode="x unified",
    )


def _day8_from_time_str(ts: Optional[str]) -> str:
    s = str(ts or "").strip()
    if not s:
        return ""
    td = pd.to_datetime(s, errors="coerce")
    if pd.isna(td):
        return ""
    return str(td.strftime("%Y%m%d"))


def _normalize_day_list(days: List[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for d in days:
        day = str(d or "").strip()
        if not re.fullmatch(r"\d{8}", day):
            continue
        if day in seen:
            continue
        seen.add(day)
        out.append(day)
    return out


@st.cache_data(show_spinner=False)
def _read_trade_rows_for_days_cached(logs_dir: Path, day_token: str, dir_token: str = "") -> List[Dict[str, Any]]:
    _ = dir_token
    rows: List[Dict[str, Any]] = []
    days = [x.strip() for x in str(day_token or "").split(",") if x.strip()]
    for day in days:
        p = logs_dir / f"trade_log_{day}.csv"
        if p.exists():
            rows.extend(_read_csv_dict_rows(p))
    return rows


def _read_trade_rows_for_days(logs_dir: Optional[Path], days: List[str]) -> List[Dict[str, Any]]:
    if not logs_dir:
        return []
    norm_days = _normalize_day_list(days)
    if not norm_days:
        return []
    day_token = ",".join(norm_days)
    return _read_trade_rows_for_days_cached(logs_dir, day_token, dir_cache_token(logs_dir))


@st.cache_data(show_spinner=False)
def _analytics_dataset_cached(
    logs_dir: Path, day_token: str, dir_token: str = ""
) -> Tuple[List[Dict[str, Any]], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    _ = dir_token
    rows = _read_trade_rows_for_days_cached(logs_dir, day_token, dir_token)
    df_pos = build_position_metrics_from_logs(rows)
    price_df, event_df = build_trade_timeline_frames(rows)
    return rows, df_pos, price_df, event_df


def _analytics_dataset_for_days(
    logs_dir: Optional[Path], days: List[str]
) -> Tuple[List[Dict[str, Any]], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not logs_dir:
        return [], pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    norm_days = sorted(_normalize_day_list(days))
    if not norm_days:
        return [], pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    day_token = ",".join(norm_days)
    rows, df_pos, price_df, event_df = _analytics_dataset_cached(
        logs_dir, day_token, dir_cache_token(logs_dir)
    )
    return list(rows), df_pos.copy(), price_df.copy(), event_df.copy()


def _calc_tp_sl_prices(side: str, entry_price: float, tp_pct: float, sl_pct: float) -> Tuple[float, float]:
    tp = float(tp_pct) / 100.0
    sl = float(sl_pct) / 100.0
    s = str(side or "").upper()
    e = float(entry_price)
    if s == "BUY":
        return e * (1.0 + tp), e * (1.0 + sl)
    return e * (1.0 - tp), e * (1.0 - sl)  # sl_pct negative => SELL時はentryより上


def _parse_tp_sl_from_note(note: Any) -> Tuple[Optional[float], Optional[float]]:
    s = str(note or "").strip()
    if not s:
        return None, None
    m_tp = re.search(r"(?:^|\s)tp=([-+]?[0-9]+(?:\.[0-9]+)?)", s)
    m_sl = re.search(r"(?:^|\s)sl=([-+]?[0-9]+(?:\.[0-9]+)?)", s)
    tp = safe_float(m_tp.group(1)) if m_tp else None
    sl = safe_float(m_sl.group(1)) if m_sl else None
    return tp, sl


def _extract_note_kv(note: Any, key: str) -> str:
    s = str(note or "").strip()
    if not s:
        return ""
    m = re.search(rf"(?:^|\s){re.escape(key)}=([^\s]+)", s)
    if not m:
        return ""
    return str(m.group(1) or "").strip()


def infer_tp_sl_for_pos(
    *,
    rows: List[Dict[str, Any]],
    pos_id: str,
    entry_side: Optional[str],
    entry_price: Optional[float],
    ctrl: Dict[str, str],
) -> Tuple[Optional[float], Optional[float], str]:
    pid = str(pos_id or "").strip()
    if pid and rows:
        ent_rows = [
            r
            for r in rows
            if str(r.get("pos_id", "")).strip() == pid
            and str(r.get("result", "")).strip() == "PAPER"
        ]
        if ent_rows:
            ent_rows = sorted(ent_rows, key=lambda r: str(r.get("time", "")))
            tp_n, sl_n = _parse_tp_sl_from_note(ent_rows[0].get("note"))
            if tp_n is not None and sl_n is not None:
                return float(tp_n), float(sl_n), "entry_note"

    side = str(entry_side or "").upper()
    ep = safe_float(entry_price)
    if side in {"BUY", "SELL"} and ep is not None:
        tp_pct = safe_float(ctrl.get("tp_buy_pct" if side == "BUY" else "tp_sell_pct"))
        sl_pct = safe_float(ctrl.get("sl_pct"))
        if tp_pct is not None and sl_pct is not None:
            tp_c, sl_c = _calc_tp_sl_prices(side=side, entry_price=float(ep), tp_pct=float(tp_pct), sl_pct=float(sl_pct))
            return float(tp_c), float(sl_c), "control_estimate"

    return None, None, "none"


# =========================
# UI helpers
# =========================
def ui_status_banner(ctrl: Dict[str, str], lock_info: Dict[str, Any]):
    safety = bval_str(ctrl.get("safety_hard_block", "0"))
    today = bval_str(ctrl.get("today_on", "0"))
    trade_enabled = bval_str(ctrl.get("trade_enabled", "0"))
    paper = bval_str(ctrl.get("paper_mode", "0"))
    observe = bval_str(ctrl.get("observe_only", "0"))
    is_running = bool(lock_info.get("alive", False))
    lock_exists = bool(lock_info.get("exists", False))

    if safety:
        st.error("🛑 **SAFETY BLOCK** — 全動作ブロック中（設定タブで解除）")
        return
    if not today:
        st.warning("💤 **停止中** — today_on=0（本日稼働OFF）")
        return
    if not trade_enabled:
        st.info("⏸ **待機中** — trade_enabled=0（売買ロジックOFF）")
        return
    if not is_running:
        if lock_exists:
            st.warning("⚠️ **プロセス停止中** — .run_lock は存在するが pid が生きていません（前回停止残骸の可能性）")
        else:
            st.info("⏸ **bot停止中** — ダッシュボードのみ稼働中です。`ホーム` タブの `bot起動` で開始できます。")
        return

    if observe:
        st.info("👀 **観測のみ** — observe_only=1（発注なし）")
    elif paper:
        st.success("🧪 **PAPERモード** — 架空売買（推奨）")
    else:
        st.success("🚀 **LIVEモード** — 実弾運用（注意）")


def ui_manual_tab(
    ctrl: Dict[str, str],
    state_obj: Dict[str, Any],
    logs_dir: Optional[Path],
    out_dir: Path,
    main_dir: Path,
    control_path: Path,
    actor: str = "unknown",
):
    st.markdown("## 📚 マニュアル・ガイド（運用手順）")
    st.caption("目的: 迷わず操作できるように、日次運用・LIVE移行・トラブル対応をこの画面で確認できます。")

    log_ok = bool(logs_dir and logs_dir.exists())
    report_ok = bool(collect_json_reports(out_dir))
    run_alive = bool(_lock_info(get_main_dir()).get("alive"))
    open_pos = bool((state_obj or {}).get("_open_pos"))

    with st.expander("🚦 現在の運用チェック（自動判定）", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("CONTROL設定", _badge(True))
        c2.metric("logs存在", _badge(log_ok))
        c3.metric("bot稼働", _badge(run_alive, "RUNNING", "STOPPED"))
        c4.metric("監査JSON", _badge(report_ok, "READY", "MISSING"))
        st.write(f"- open_pos: {_badge(open_pos, 'あり', 'なし')}")
        st.write(f"- モード: {'PAPER' if bval_str(ctrl.get('paper_mode')) else 'LIVE候補'} / live_enabled={ctrl.get('live_enabled', '0')}")

    with st.expander("🧪 手順ナビ（この画面で操作）", expanded=True):
        st.caption("運用状態に応じて、必要な操作をこのタブ内で完結できます。")
        errs, warns = _validate_control_values(ctrl)
        if errs:
            st.error("設定エラーがあります。先に `Bot設定` で修正してください。")
            for e in errs:
                st.write(f"- {e}")
        elif warns:
            st.warning("注意点があります。")
            for w in warns[:4]:
                st.write(f"- {w}")
        else:
            st.success("設定チェックは正常です。")

        nav_actions = _suggest_next_actions(
            ctrl=ctrl,
            state_obj=state_obj,
            lock_info=_lock_info(main_dir),
            logs_dir=logs_dir,
            out_dir=out_dir,
        )
        st.markdown("**次にやること（自動提案）**")
        for i, a in enumerate(nav_actions, 1):
            st.write(f"{i}. {a}")

        s1, s2, s3 = st.columns(3)
        with s1:
            if st.button("🧪 safe_paper 適用", width="stretch", key="guide_profile_safe"):
                ok, msg = _apply_control_profile(
                    main_dir,
                    control_path,
                    ctrl,
                    "safe_paper",
                    author=actor,
                    reason="guide:safe_paper",
                )
                if ok:
                    st.success("safe_paper を適用しました。")
                    st.rerun()
                else:
                    st.error(f"適用失敗: {msg}")
        with s2:
            if st.button("🚀 live_canary 適用", width="stretch", key="guide_profile_canary"):
                ok, msg = _apply_control_profile(
                    main_dir,
                    control_path,
                    ctrl,
                    "live_canary",
                    author=actor,
                    reason="guide:live_canary",
                )
                if ok:
                    st.success("live_canary を適用しました。")
                    st.rerun()
                else:
                    st.error(f"適用失敗: {msg}")
        with s3:
            if st.button("🛑 緊急停止", width="stretch", key="guide_profile_stop"):
                ok, msg = _apply_control_profile(
                    main_dir,
                    control_path,
                    ctrl,
                    "emergency_stop",
                    author=actor,
                    reason="guide:emergency_stop",
                )
                if ok:
                    st.success("緊急停止プリセットを適用しました。")
                    st.rerun()
                else:
                    st.error(f"適用失敗: {msg}")

        a1, a2, a3 = st.columns(3)
        with a1:
            if st.button("🔐 live_preflight 実行", width="stretch", key="guide_run_preflight"):
                p = main_dir / "tools" / "live_preflight.py"
                if p.exists():
                    _run_action_block("live_preflight", [sys.executable, str(p)], main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        with a2:
            if st.button("✅ run_check.sh 実行", width="stretch", key="guide_run_check"):
                p = main_dir / "run_check.sh"
                if p.exists():
                    days = list_log_days(logs_dir) if logs_dir else []
                    cmd = ["bash", str(p)]
                    if days:
                        cmd.append(days[0])
                    _run_action_block("run_check.sh", cmd, main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        with a3:
            if st.button("🧪 ci_check 実行", width="stretch", key="guide_run_ci"):
                p = main_dir / "ci_check.py"
                if p.exists():
                    days = list_log_days(logs_dir) if logs_dir else []
                    cmd = [sys.executable, str(p)]
                    if days:
                        cmd.append(days[0])
                    _run_action_block("ci_check", cmd, main_dir)
                else:
                    st.error(f"見つかりません: {p}")

    with st.expander("🧭 タブ別の使い分け", expanded=False):
        st.markdown(
            """
- `ホーム`: 現在状態、現在時刻ローソク足、bot起動/停止（2段階ガード）、強制エグジット履歴、クイック実行
- `Bot設定`: CONTROLの更新（最重要）
- `成績・分析`: daily_report/audit実行とグラフ確認
- `トレード履歴`: 生ログ確認、原因追跡
- `pos_id・監査`: OPEN/CLOSED整合とissue確認
- `ログイン/セキュリティ`: OIDC（Google/Apple）主体ログインと通知
- `ツール`: preflight/ci_check/run_checkの実行
- `iPhone表示`: HTTPS推奨（`tools/start_dashboard_https.sh`）で「ホーム画面に追加」利用
- `自動復旧`: `tools/install_dashboard_launchagent.sh` で dashboard+ngrok 常駐化
"""
        )

    with st.expander("🔰 はじめて使う手順（PAPER開始）", expanded=False):
        st.markdown(
            """
1. `Bot設定` で `paper_mode=1`, `live_enabled=0`, `safety_hard_block=0` を確認
2. `ホーム` で `live_preflight` / `run_check.sh` を実行（警告がないことを確認）
3. `ホーム` の `bot起動 (1/2→2/2)` で実行開始
4. 最新ログで `SKIP/OBSERVE/PAPER` が増えることを確認
5. `成績・分析` で `daily_report` と `audit` を実行
6. `pos_id・監査` で OPEN/CLOSED と issues を確認
7. 問題が無い日を連続で作ってから LIVEへ進む
"""
        )

    with st.expander("🚀 LIVE移行手順（段階導入）", expanded=False):
        st.markdown(
            """
1. `ツール` で `live_preflight` を実行し、Keychain/API接続を確認
2. `Bot設定` で `paper_mode=0`, `live_enabled=1`, `rollout_mode=CANARY` を設定
3. `canary_lot`, `daily_loss_limit_pct`, `limit_order_timeout_sec` を小さめで開始
4. `ホーム` で `effective_stage` と `risk_stop` を毎日確認
5. 安定後に `rollout_mode=AUTO` または `LIVE` へ移行
6. 稼働中に停止する場合は `停止時に未決済LIVEポジを強制エグジット` をONにして停止
"""
        )

    with st.expander("🔁 自動復旧（dashboard + ngrok）", expanded=False):
        st.markdown(
            """
1. 常駐化: `./tools/install_dashboard_launchagent.sh`
2. 状態確認: `launchctl print gui/$(id -u)/com.ouroboros.dashboard.ngrok`
3. 停止/解除: `./tools/uninstall_dashboard_launchagent.sh`
4. ログ確認: `MAIN/ci_logs/launchd_dashboard_out.log`, `MAIN/ci_logs/launchd_dashboard_err.log`
5. 取引通知の常駐化: `./tools/install_trade_notifier_launchagent.sh`
6. 通知停止/解除: `./tools/uninstall_trade_notifier_launchagent.sh`
"""
        )

    with st.expander("🔐 OIDCログイン（Google/Apple）+ ログイン通知", expanded=False):
        st.markdown(
            """
1. `pip install streamlit[auth]` を実行（Authlibを含む）
2. `MAIN/.streamlit/secrets.toml` に `[auth]` と `[auth.google]` または `[auth.apple]` を設定
3. `redirect_uri` は必ず `https://<ホスト>:8501/oauth2callback` にする
4. 通知は `[dashboard_security]` で `ntfy_topic_url` または `login_notify_webhook_url` を設定
5. 認証モードは `MAIN/.streamlit/dashboard_auth.json` で `mode=OIDC`（OIDC主体）または `AUTO`
6. iPhone Safari から HTTPS URL で開き、Google/Appleログインを確認
7. 他人のログイン防止のため `allowed_emails` または `allowed_email_domains` を必ず設定
8. ホーム画面アイコン固定は `[dashboard_branding] apple_touch_icon_path`（または `apple_touch_icon_url`）を設定
9. ログイン履歴は `ツール` タブの `ログイン監査履歴` または `.streamlit/dashboard_login_audit.jsonl` で確認
"""
        )
        st.code(
            """
[auth]
redirect_uri = "https://<YOUR_HOST>:8501/oauth2callback"
cookie_secret = "<RANDOM_32+_BYTES>"

[auth.google]
client_id = "<GOOGLE_CLIENT_ID>"
client_secret = "<GOOGLE_CLIENT_SECRET>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

[auth.apple]
client_id = "<APPLE_SERVICE_ID>"
client_secret = "<APPLE_CLIENT_SECRET_JWT>"
server_metadata_url = "https://appleid.apple.com/.well-known/openid-configuration"

[dashboard_security]
login_notify_enabled = true
auth_fail_notify_enabled = true
trade_notify_enabled = true
allowed_emails = ["owner@example.com"]
allowed_email_domains = ["example.com"]
ntfy_topic_url = "https://ntfy.sh/<PRIVATE_TOPIC>"

[dashboard_branding]
apple_touch_icon_path = ".streamlit/assets/apple-touch-icon.png"
# apple_touch_icon_url = "https://<YOUR_STATIC_HOST>/apple-touch-icon.png"
apple_mobile_web_app_title = "Project Ouroboros"
""".strip(),
            language="toml",
        )

    with st.expander("🧩 pos_id・監査(JSON) の読み方", expanded=False):
        st.markdown(
            """
- 監査JSONがある場合はJSONを最優先表示（Dashboardで再判定しない）
- JSONが無い場合のみログから推定表示
- `ret_pct` は推定（fee未加味、SELL符号反転）
- `issues` に pos_id があればボタンでジャンプして詳細確認
"""
        )

    with st.expander("📈 チャートの読み方（Entry/Exit・損益）", expanded=False):
        st.markdown(
            """
- `成績・分析` の `ローソク足 + ENTRY/EXIT` で売買ポイントを確認できます
- `ホーム` の `リアルタイム相場（現在時刻）` は現在のローソク足確認に使えます
- `pos_id・監査` の詳細にある `決済タイミングチャート` で個別トレードのENTRY/EXITを拡大確認できます
- 緑▲: BUYエントリー、赤▼: SELLエントリー、黄✕: EXIT
- `決済タイミングチャート` では TP(緑点線) / SL(橙点線) を重ねて確認できます
- チャートは `マウスホイール=ズーム` / `ドラッグ=パン` / `レンジスライダー=時間軸移動` に対応
- `累積PnL(推定)` は pos_id 単位の概算（fee未加味）
- `総利益` / `総損失` / `Payoff` / `Profit Factor` で損小利大の傾向を確認
- 要因分析は `Top 利益トレード` / `Top 損失トレード` から `pos_id・監査` へ掘り下げ
"""
        )

    with st.expander("🤖 AI学習の見方", expanded=False):
        st.markdown(
            """
- `ホーム` の `AI学習ステータス` に日次自動更新の結果が表示されます
- `last_day` が当日で更新されていれば、その日は学習判定を実行済みです
- `threshold` が変わった日は、損小利大指標の改善が確認され自動適用されています
- `lot_lock` はサンプル不足時のLIVEロット据え置き状態を表示します
- `monthly_reval` は月次しきい値再評価（PF/Expectancyゲート付き）の実行結果を表示します
- `成績・分析` の `同じ負け方分析` で、`trend/signal/時間帯` の損失偏りを確認できます
- `反省学習設定をCONTROLへ反映` で、損失集中時間帯を `ai_train_weekly_bad_hours` へ即時反映できます
- 自動更新を止める場合は `Bot設定` の `ai_auto_train_enabled=0` にします
"""
        )

    with st.expander("🧠 週次AI改善（反映前後比較）の使い方", expanded=False):
        st.markdown(
            """
1. `成績・分析` タブで対象日を選び、`weekly_report 実行` を押す
2. 同タブの `週次レビュー` で `AI学習提案` を確認する
3. `🧠 AI学習設定へ提案を反映` を押す（この時点の学習状態を自動保存）
4. 次回のAI自動学習後、`🧪 週次提案の反映前後比較` の `before/after/delta` が更新される
5. 判定の見方:
   - `UP`: 改善
   - `DOWN`: 悪化
   - `SAME`: 変化なし
   - `REF`: 参照値（改善/悪化判定対象外）
6. 上段カード（current_metric / best_metric / backtest_pf / backtest_expectancy）で全体傾向を確認する
7. 意図しない結果なら、`比較スナップショットをクリア` して再検証サイクルを開始する

運用ポイント:
- 反映直後は `比較待機中` が正常（まだ after が未更新）
- 同日の再学習前に何度も反映すると比較基準が上書きされるため、1サイクル1回を推奨
- `train_backtest_gate_pass` が `DOWN` の場合は、まず backtest 側のPF/expectancy悪化を確認してからLIVE反映する
"""
        )

    with st.expander("🚑 トラブルシュート集", expanded=False):
        st.markdown(
            """
- `logs が空`: botが起動しているか、`today_on` と `trade_enabled` を確認
- `ログイン画面から進めない`: `python3 tools/create_dashboard_user.py --username admin` でユーザー作成
- `更新するとログインに戻る`: ローカルログイン時に `この端末でログイン状態を維持` をONにして再ログイン
- `更新でログイン保持されない`: ブラウザのCookieブロック設定を解除し、HTTPS URL で開いて再ログイン
- `OIDCログインできない`: `pip install streamlit[auth]`、`secrets.toml` の `[auth.google]/[auth.apple]`、`redirect_uri` を確認
- `OIDCで拒否される`: `dashboard_security.allowed_emails / allowed_email_domains` の許可リストを確認
- `ログイン通知が来ない`: `[dashboard_security] ntfy_topic_url` か `login_notify_webhook_url` が設定されているか確認
- `誰がログインしたか見たい`: `ツール` タブの `ログイン監査履歴` を開く（保存先: `.streamlit/dashboard_login_audit.jsonl`）
- `起動できない`: `ホーム` の2段階ガードで `1/2 準備` → `2/2 実行` の順に押す
- `監査JSONが無い`: `成績・分析` タブで `daily_report` 実行
- `risk_stop=ON`: 日次損失ガード発動。翌日リセットまたは設定を見直し
- `LIVEで発注されない`: `live_preflight`、`paper_mode/live_enabled/safety_hard_block`、`market_type/product_code` を確認
- `iPhoneで接続できない`: `tools/start_dashboard_https.sh` で起動し、`https://<ホストIP>:8501` へアクセス（同一Wi-Fi）
- `Googleログインが通らない`: `redirect_uri` を HTTPSドメインにし、Google OAuth設定と完全一致させる（IP不可）
- `ngrok運用`: `tools/start_dashboard_ngrok.sh` で公開URLを取得し、`redirect_uri` とGoogle設定を同じURLへ更新
- `breakglassが使えない`: `dashboard_auth.json` の `allow_breakglass_in_auto` と `breakglass_daily_limit` を確認
- `HTTPS-Only で止まる`: HTTPではなく HTTPS URL を直接開く（`https://<ホストIP>:8501`）
- `OPENが閉じない`: `PAPER_EXIT_*` ログ有無、issues内容、state.jsonのopen_posを確認
- `停止後にポジションが残る`: `ホーム` の `強制エグジット（LIVE）` を `1/2→2/2` で実行
- `とにかく全部止めたい`: `ホーム` の `緊急停止 + 強制エグジット` を `1/2→2/2` で実行（hard_block=1まで自動）
- `通知が来ない`: `tools/trade_event_notifier.py --dry-run` を実行して `dashboard_security` の設定を確認
"""
        )

    with st.expander("📘 用語ミニ辞典", expanded=False):
        st.markdown(
            """
- `PAPER`: 仮想約定（実弾なし）
- `CANARY`: 少額LIVEの確認段階
- `effective_stage`: 実効ステージ（PAPER/CANARY/LIVE）
- `risk_stop`: 日次損失ガードによる新規停止フラグ
- `HOLD_OPEN_POS`: 保有継続ログ
"""
        )


def _lock_info(main_dir: Path) -> Dict[str, Any]:
    lock_dir = run_lock_dir(main_dir)
    return _lock_info_by_dir(lock_dir)


def _lock_info_by_dir(lock_dir: Path) -> Dict[str, Any]:
    info = {"exists": False, "alive": False, "pid": None, "state": ""}
    if not lock_dir.exists():
        return info
    info["exists"] = True
    try:
        txt_path = lock_dir / "lockinfo.txt"
        if not txt_path.exists():
            return info
        txt = txt_path.read_text(encoding="utf-8", errors="ignore")
        pid = None
        for line in txt.splitlines():
            if line.startswith("pid="):
                try:
                    pid = int(line.split("=", 1)[1].strip())
                except Exception:
                    pid = None
        info["pid"] = pid
        if pid:
            alive, st = _pid_is_alive(pid)
            info["alive"] = bool(alive)
            info["state"] = st
    except Exception:
        pass
    return info


def _clear_stale_run_lock(main_dir: Path) -> Tuple[bool, str]:
    return _clear_stale_lock_dir(run_lock_dir(main_dir), lock_label=".run_lock")


def _clear_stale_lock_dir(lock_dir: Path, lock_label: str = ".run_lock") -> Tuple[bool, str]:
    info = _lock_info_by_dir(lock_dir)
    if bool(info.get("alive")):
        return False, f"{lock_label} 実行中のため削除しません (pid={info.get('pid')})"
    if not lock_dir.exists():
        return True, f"{lock_label} は存在しません。"
    try:
        for p in lock_dir.iterdir():
            try:
                p.unlink()
            except Exception:
                pass
        lock_dir.rmdir()
        return True, f"stale {lock_label} をクリアしました。"
    except Exception as e:
        return False, f"{lock_label} クリア失敗: {e}"


def _pid_state(pid: int) -> str:
    try:
        p = subprocess.run(
            ["ps", "-p", str(int(pid)), "-o", "stat="],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if p.returncode != 0:
            return ""
        return str((p.stdout or "").strip()).upper()
    except Exception:
        return ""


def _pid_is_alive(pid: int) -> Tuple[bool, str]:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False, ""
    except PermissionError:
        return True, ""
    except Exception:
        return False, ""
    st = _pid_state(pid)
    if st.startswith("Z"):
        return False, st
    return True, st


def _run_subprocess(cmd: List[str], cwd: Path) -> Tuple[int, str]:
    """
    Run and capture output for UI.
    """
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return p.returncode, p.stdout[-4000:]  # limit
    except Exception as e:
        return 999, f"ERROR: {e}"


def _badge(ok: bool, ok_text: str = "OK", ng_text: str = "NG") -> str:
    return f"✅ {ok_text}" if ok else f"❌ {ng_text}"


def _ops_checks_path(main_dir: Path) -> Path:
    return main_dir / ".ops_checks.json"


def _read_ops_checks(main_dir: Path) -> Dict[str, Any]:
    p = _ops_checks_path(main_dir)
    if not p.exists():
        return {}
    return _read_json_dict(p, default={})


def _write_ops_checks(main_dir: Path, data: Dict[str, Any]) -> None:
    _write_json_dict(_ops_checks_path(main_dir), data)


def _record_ops_check(main_dir: Path, title: str, cmd: List[str], rc: int) -> None:
    now_ts = float(time.time())
    rec = {
        "title": str(title),
        "rc": int(rc),
        "ok": bool(int(rc) == 0),
        "updated_ts": now_ts,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cmd": " ".join([str(x) for x in cmd])[:800],
    }
    data = _read_ops_checks(main_dir)
    data[str(title)] = rec
    _write_ops_checks(main_dir, data)

    sess = st.session_state.get("_ops_checks")
    if not isinstance(sess, dict):
        sess = {}
    sess[str(title)] = rec
    st.session_state["_ops_checks"] = sess


def _get_ops_check(main_dir: Path, title: str) -> Dict[str, Any]:
    file_rec = _read_ops_checks(main_dir).get(str(title))
    sess_rec = {}
    sess = st.session_state.get("_ops_checks")
    if isinstance(sess, dict):
        x = sess.get(str(title))
        if isinstance(x, dict):
            sess_rec = x

    if not isinstance(file_rec, dict):
        file_rec = {}
    ts_file = safe_float(file_rec.get("updated_ts")) or 0.0
    ts_sess = safe_float(sess_rec.get("updated_ts")) or 0.0
    return sess_rec if ts_sess >= ts_file else file_rec


def _ops_check_fresh_ok(main_dir: Path, titles: List[str], max_age_min: int) -> Tuple[bool, str]:
    now = float(time.time())
    max_age_sec = max(1, int(max_age_min)) * 60
    best: Dict[str, Any] = {}
    best_title = ""
    best_ts = 0.0
    for t in titles:
        rec = _get_ops_check(main_dir, t)
        if not isinstance(rec, dict) or not rec:
            continue
        ts = safe_float(rec.get("updated_ts")) or 0.0
        if ts > best_ts:
            best = rec
            best_ts = ts
            best_title = str(t)

    if not best:
        return False, f"{'/'.join(titles)} の実行履歴がありません。"

    rc_val = safe_float(best.get("rc"))
    if rc_val is None:
        return False, f"{best_title} の実行結果(rc)を読めません。"
    if int(rc_val) != 0:
        return False, f"{best_title} の直近実行が失敗しています（rc={best.get('rc')}）。"

    age_sec = now - (safe_float(best.get("updated_ts")) or 0.0)
    if age_sec > max_age_sec:
        return False, f"{best_title} の成功が古いです（約 {int(age_sec // 60)} 分前）。"

    return True, f"{best_title} 成功（{best.get('updated_at', '-')})"


def _run_action_block(title: str, cmd: List[str], cwd: Path):
    st.markdown(f"**{title}**")
    st.code(" ".join(cmd))
    rc, out = _run_subprocess(cmd, cwd=cwd)
    st.code(out)
    _record_ops_check(cwd, title=title, cmd=cmd, rc=rc)
    if rc == 0:
        st.success("完了")
    else:
        st.error(f"失敗 rc={rc}")


def _build_profile_control(base_ctrl: Dict[str, str], profile_name: str) -> Tuple[Optional[Dict[str, str]], str]:
    upd = dict(base_ctrl)
    if profile_name == "safe_paper":
        upd["today_on"] = "1"
        upd["trade_enabled"] = "1"
        upd["paper_mode"] = "1"
        upd["live_enabled"] = "0"
        upd["observe_only"] = "0"
        upd["safety_hard_block"] = "0"
        upd["rollout_mode"] = "AUTO"
    elif profile_name == "live_canary":
        upd["today_on"] = "1"
        upd["trade_enabled"] = "1"
        upd["paper_mode"] = "0"
        upd["live_enabled"] = "1"
        upd["observe_only"] = "0"
        upd["safety_hard_block"] = "0"
        upd["rollout_mode"] = "CANARY"
    elif profile_name == "emergency_stop":
        upd["safety_hard_block"] = "1"
    else:
        return None, f"unknown profile: {profile_name}"
    return upd, ""


def _apply_control_profile(
    main_dir: Path,
    control_path: Path,
    base_ctrl: Dict[str, str],
    profile_name: str,
    *,
    author: str = "unknown",
    reason: str = "",
) -> Tuple[bool, str]:
    upd, emsg = _build_profile_control(base_ctrl, profile_name)
    if upd is None:
        return False, emsg
    reason_text = str(reason).strip() or f"profile:{profile_name}"
    return write_control_kv_csv_with_log(
        main_dir=main_dir,
        path=control_path,
        before_ctrl=base_ctrl,
        after_ctrl=upd,
        author=author,
        reason=reason_text,
    )


def _normalize_control_for_diff(ctrl: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if isinstance(ctrl, dict):
        for k, v in ctrl.items():
            out[str(k)] = str(v)
    ai_on = bval_str(out.get("ai_model_enabled", out.get("ai_enabled", "0")))
    out["ai_model_enabled"] = "1" if ai_on else "0"
    out["ai_enabled"] = "1" if ai_on else "0"
    return out


def _shorten_for_log(v: Any, max_len: int = 60) -> str:
    s = str(v)
    if len(s) <= max_len:
        return s
    return s[: max(0, max_len - 3)] + "..."


def _control_changed_items(before_ctrl: Dict[str, Any], after_ctrl: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    b = _normalize_control_for_diff(before_ctrl)
    a = _normalize_control_for_diff(after_ctrl)
    keys = sorted(set(b.keys()) | set(a.keys()))
    out: List[Tuple[str, str, str]] = []
    for k in keys:
        bv = str(b.get(k, ""))
        av = str(a.get(k, ""))
        if bv != av:
            out.append((k, bv, av))
    return out


def _append_control_change_log(
    main_dir: Path,
    before_ctrl: Dict[str, Any],
    after_ctrl: Dict[str, Any],
    *,
    author: str = "unknown",
    reason: str = "control_update",
) -> Tuple[bool, str]:
    changed = _control_changed_items(before_ctrl, after_ctrl)
    if not changed:
        return True, "no diff"

    git_now = _git_snapshot(main_dir)
    changed_keys = [k for k, _, _ in changed]
    preview = [{"key": k, "before": _shorten_for_log(b), "after": _shorten_for_log(a)} for k, b, a in changed[:30]]
    row = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": APP_VERSION,
        "type": "CONFIG",
        "author": str(author or "unknown"),
        "summary": f"{reason}: {len(changed_keys)} keys changed",
        "files": ["MAIN/CONTROL.csv"],
        "git_branch": str(git_now.get("branch", "-")),
        "git_commit": str(git_now.get("commit", "-")),
        "git_dirty_files": int(git_now.get("dirty_files", 0)),
        "reason": str(reason),
        "changed_keys": changed_keys,
        "diff_preview": preview,
    }
    return _append_dashboard_change_log(main_dir, row)


def _notify_control_change_ntfy(
    main_dir: Path,
    before_ctrl: Dict[str, Any],
    after_ctrl: Dict[str, Any],
    *,
    author: str = "unknown",
    reason: str = "control_update",
) -> None:
    """Fire-and-forget ntfy notification when CONTROL.csv changes."""
    try:
        changed = _control_changed_items(before_ctrl, after_ctrl)
        if not changed:
            return
        sec_path = main_dir / ".streamlit" / "secrets.toml"
        ntfy_url = ""
        ntfy_bearer = ""
        if sec_path.exists():
            for line in sec_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("ntfy_topic_url"):
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if v and v != "***MASKED***":
                        ntfy_url = v
                elif line.startswith("ntfy_bearer_token"):
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if v and v != "***MASKED***":
                        ntfy_bearer = v
        if not ntfy_url:
            return
        diff_parts = [f"{k}:{_shorten_for_log(b)}→{_shorten_for_log(a)}" for k, b, a in changed[:5]]
        body_lines = [
            f"⚙️ CONTROL変更 ({author})",
            f"理由: {reason}",
            "  " + "  ".join(diff_parts),
            f"at: {datetime.now().strftime('%m/%d %H:%M')}",
        ]
        body = "\n".join(body_lines)
        h: Dict[str, str] = {
            "Content-Type": "text/plain; charset=utf-8",
            "Title": "Ouroboros CONTROL変更",
            "Tags": "gear",
            "Priority": "low",
        }
        if ntfy_bearer:
            h["Authorization"] = f"Bearer {ntfy_bearer}"
        _http_post(ntfy_url, body.encode("utf-8"), h, timeout_sec=2.0)
    except Exception:
        pass


def _try_signal_bot_reload(main_dir: Path) -> Tuple[bool, str]:
    """Send SIGUSR1 to the bot runner to interrupt its sleep and reload CONTROL immediately."""
    import signal as _sig
    lock_info = main_dir / ".run_lock" / "lockinfo.txt"
    if not lock_info.exists():
        return False, "run_lock not found (bot not running?)"
    try:
        txt = lock_info.read_text(encoding="utf-8", errors="ignore")
        pid = None
        for line in txt.splitlines():
            if line.startswith("pid="):
                pid = int(line.split("=", 1)[1].strip())
                break
        if pid is None:
            return False, "pid not in lockinfo"
        os.kill(pid, _sig.SIGUSR1)
        return True, f"SIGUSR1 → pid={pid}"
    except (ProcessLookupError, PermissionError) as e:
        return False, f"signal failed: {e}"
    except Exception as e:
        return False, f"error: {e}"


def write_control_kv_csv_with_log(
    main_dir: Path,
    path: Path,
    before_ctrl: Dict[str, Any],
    after_ctrl: Dict[str, Any],
    *,
    author: str = "unknown",
    reason: str = "control_update",
) -> Tuple[bool, str]:
    ok, msg = write_control_kv_csv(path, {str(k): str(v) for k, v in dict(after_ctrl).items()})
    if not ok:
        return False, msg
    ok_log, msg_log = _append_control_change_log(
        main_dir=main_dir,
        before_ctrl=before_ctrl,
        after_ctrl=after_ctrl,
        author=author,
        reason=reason,
    )
    if not ok_log:
        rb_ok, rb_msg = write_control_kv_csv(path, {str(k): str(v) for k, v in dict(before_ctrl).items()})
        if rb_ok:
            return False, f"change_log_write_failed: {msg_log} (CONTROLをロールバックしました)"
        return False, f"change_log_write_failed: {msg_log} / rollback_failed: {rb_msg}"
    # P1: If safety_hard_block just activated, signal bot to reload CONTROL immediately
    before_shb = str(before_ctrl.get("safety_hard_block", "0")).strip()
    after_shb = str(after_ctrl.get("safety_hard_block", "0")).strip()
    if after_shb == "1" and before_shb != "1":
        sig_ok, sig_detail = _try_signal_bot_reload(main_dir)
        if sig_ok:
            msg = msg + f" ／ bot即時通知: {sig_detail}"
        else:
            msg = msg + f" ／ bot通知スキップ: {sig_detail}"
    # Fire-and-forget ntfy notification for CONTROL changes
    _notify_control_change_ntfy(main_dir, before_ctrl, after_ctrl, author=author, reason=reason)
    return True, msg


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(str(v).strip()))
    except Exception:
        return default


def _parse_hour_csv_set(v: Any) -> set[int]:
    s = str(v or "").strip()
    if not s:
        return set()
    out: set[int] = set()
    for tok in s.replace("[", "").replace("]", "").split(","):
        t = tok.strip()
        if not t:
            continue
        try:
            h = int(float(t))
        except Exception:
            continue
        if 0 <= h <= 23:
            out.add(int(h))
    return out


def _format_hours_for_status(v: Any) -> str:
    hs = sorted(_parse_hour_csv_set(v))
    if not hs:
        return "-"
    return ",".join(str(int(x)) for x in hs)


def _validate_control_values(ctrl: Dict[str, str]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warns: List[str] = []

    today_on = bval_str(ctrl.get("today_on", "0"))
    trade_enabled = bval_str(ctrl.get("trade_enabled", "0"))
    paper_mode = bval_str(ctrl.get("paper_mode", "1"))
    live_enabled = bval_str(ctrl.get("live_enabled", "0"))
    exchange_name = str(ctrl.get("exchange_name", "bitflyer")).strip().lower()
    observe_only = bval_str(ctrl.get("observe_only", "0"))
    safety = bval_str(ctrl.get("safety_hard_block", "0"))

    tp_buy_pct = safe_float(ctrl.get("tp_buy_pct"))
    tp_sell_pct = safe_float(ctrl.get("tp_sell_pct"))
    sl_pct = safe_float(ctrl.get("sl_pct"))
    win_min = safe_float(ctrl.get("win_min"))
    spread_limit_pct = safe_float(ctrl.get("spread_limit_pct"))
    lot = safe_float(ctrl.get("lot"))
    canary_lot = safe_float(ctrl.get("canary_lot"))
    fx_leverage = safe_float(ctrl.get("fx_leverage"))
    fx_collateral_use_ratio = safe_float(ctrl.get("fx_collateral_use_ratio"))
    daily_loss = safe_float(ctrl.get("daily_loss_limit_pct"))
    streak_stop_enabled = bval_str(ctrl.get("streak_stop_enabled", "0"))
    streak_stop_max_losses = _safe_int(ctrl.get("streak_stop_max_losses", "3"), 3)
    timeout_sec = _safe_int(ctrl.get("limit_order_timeout_sec", "30"), 30)
    stage_paper_days = _safe_int(ctrl.get("stage_paper_days", "3"), 3)
    stage_canary_days = _safe_int(ctrl.get("stage_canary_days", "3"), 3)
    ai_auto_lookback_days = _safe_int(ctrl.get("ai_auto_lookback_days", "45"), 45)
    ai_auto_train_enabled = bval_str(ctrl.get("ai_auto_train_enabled", "1"))
    ai_train_live_only = bval_str(ctrl.get("ai_train_live_only", "0"))
    ai_train_live_boost = safe_float(ctrl.get("ai_train_live_boost"))
    ai_train_include_shadow = bval_str(ctrl.get("ai_train_include_shadow", "0"))
    ai_train_shadow_boost = safe_float(ctrl.get("ai_train_shadow_boost"))
    ai_train_include_backtest = bval_str(ctrl.get("ai_train_include_backtest", "0"))
    ai_train_backtest_boost = safe_float(ctrl.get("ai_train_backtest_boost"))
    ai_train_backtest_path = str(ctrl.get("ai_train_backtest_path", "")).strip()
    ai_train_backtest_gate_enabled = bval_str(ctrl.get("ai_train_backtest_gate_enabled", "1"))
    ai_train_backtest_gate_min_samples = _safe_int(ctrl.get("ai_train_backtest_gate_min_samples", "300"), 300)
    ai_train_backtest_gate_expectancy_min = safe_float(ctrl.get("ai_train_backtest_gate_expectancy_min"))
    ai_train_backtest_gate_pf_min = safe_float(ctrl.get("ai_train_backtest_gate_pf_min"))
    ai_train_backtest_max_rows = _safe_int(ctrl.get("ai_train_backtest_max_rows", "3000"), 3000)
    ai_train_recent_halflife_days = _safe_int(ctrl.get("ai_train_recent_halflife_days", "14"), 14)
    ai_train_weekly_feedback_enabled = bval_str(ctrl.get("ai_train_weekly_feedback_enabled", "0"))
    ai_train_weekly_good_hours_raw = str(ctrl.get("ai_train_weekly_good_hours", "")).strip()
    ai_train_weekly_bad_hours_raw = str(ctrl.get("ai_train_weekly_bad_hours", "")).strip()
    ai_train_weekly_good_hours = _parse_hour_csv_set(ai_train_weekly_good_hours_raw)
    ai_train_weekly_bad_hours = _parse_hour_csv_set(ai_train_weekly_bad_hours_raw)
    ai_train_weekly_good_hour_boost = safe_float(ctrl.get("ai_train_weekly_good_hour_boost"))
    ai_train_weekly_bad_hour_penalty = safe_float(ctrl.get("ai_train_weekly_bad_hour_penalty"))
    ai_lot_lock_enabled = bval_str(ctrl.get("ai_lot_lock_enabled", "1"))
    ai_lot_lock_min_samples = _safe_int(ctrl.get("ai_lot_lock_min_samples", "120"), 120)
    ai_lot_lock_max_lot = safe_float(ctrl.get("ai_lot_lock_max_lot"))
    ai_monthly_reval_enabled = bval_str(ctrl.get("ai_monthly_reval_enabled", "1"))
    ai_monthly_reval_lookback_days = _safe_int(ctrl.get("ai_monthly_reval_lookback_days", "120"), 120)
    ai_monthly_reval_min_samples = _safe_int(ctrl.get("ai_monthly_reval_min_samples", "300"), 300)
    ai_monthly_reval_pf_min = safe_float(ctrl.get("ai_monthly_reval_pf_min"))
    ai_monthly_reval_expectancy_min = safe_float(ctrl.get("ai_monthly_reval_expectancy_min"))
    ai_monthly_reval_min_improve = safe_float(ctrl.get("ai_monthly_reval_min_improve"))
    ai_gate_enabled = bval_str(ctrl.get("ai_gate_enabled", "1"))
    ai_gate_min_samples = _safe_int(ctrl.get("ai_gate_min_samples", "30"), 30)
    ai_gate_expectancy_min = safe_float(ctrl.get("ai_gate_expectancy_min"))
    ai_gate_pf_min = safe_float(ctrl.get("ai_gate_pf_min"))
    ai_auto_rollback_enabled = bval_str(ctrl.get("ai_auto_rollback_enabled", "1"))
    ai_auto_rollback_lookback_days = _safe_int(ctrl.get("ai_auto_rollback_lookback_days", "14"), 14)
    ai_auto_rollback_pf_floor = safe_float(ctrl.get("ai_auto_rollback_pf_floor"))
    ai_auto_rollback_expectancy_floor = safe_float(ctrl.get("ai_auto_rollback_expectancy_floor"))
    exit_tech_enabled = bval_str(ctrl.get("exit_technical_enabled", "0"))
    exit_tech_only_paper = bval_str(ctrl.get("exit_technical_only_paper", "1"))
    exit_sma_fast_n = _safe_int(ctrl.get("exit_sma_fast_n", "5"), 5)
    exit_sma_slow_n = _safe_int(ctrl.get("exit_sma_slow_n", "20"), 20)
    exit_tech_min_hold = _safe_int(ctrl.get("exit_technical_min_hold_min", "5"), 5)

    if tp_buy_pct is None or tp_buy_pct <= 0:
        errors.append("`tp_buy_pct` は 0 より大きい数値で指定してください（例: 0.190）。")
    if tp_sell_pct is None or tp_sell_pct <= 0:
        errors.append("`tp_sell_pct` は 0 より大きい数値で指定してください（例: 0.190）。")
    if sl_pct is None or sl_pct >= 0:
        errors.append("`sl_pct` は負値で指定してください（例: -0.140）。")
    if win_min is None or win_min < 0:
        errors.append("`win_min` は 0 以上の数値で指定してください（例: 120）。")
    if spread_limit_pct is None or spread_limit_pct < 0:
        errors.append("`spread_limit_pct` は 0 以上の数値で指定してください（例: 0.0005）。")
    if lot is None or lot <= 0:
        errors.append("`lot` は 0 より大きい値が必要です。")
    if canary_lot is None or canary_lot <= 0:
        errors.append("`canary_lot` は 0 より大きい値が必要です。")
    if fx_leverage is None or fx_leverage <= 0:
        errors.append("`fx_leverage` は 0 より大きい値が必要です。")
    if fx_collateral_use_ratio is None or fx_collateral_use_ratio <= 0 or fx_collateral_use_ratio > 1:
        errors.append("`fx_collateral_use_ratio` は 0 より大きく 1 以下で指定してください。")
    if daily_loss is None:
        errors.append("`daily_loss_limit_pct` は数値で指定してください（例: -1.0）。")
    elif daily_loss >= 0:
        errors.append("`daily_loss_limit_pct` は負値で指定してください（例: -1.0）。")
    if streak_stop_max_losses < 1:
        errors.append("`streak_stop_max_losses` は 1 以上で指定してください。")
    if timeout_sec < 5:
        errors.append("`limit_order_timeout_sec` は 5秒以上で指定してください。")
    if stage_paper_days < 0 or stage_canary_days < 0:
        errors.append("`stage_paper_days` / `stage_canary_days` は 0 以上が必要です。")
    if exchange_name not in ("bitflyer", "binance"):
        errors.append("`exchange_name` は bitflyer / binance のいずれかを指定してください。")
    if ai_auto_lookback_days < 7:
        errors.append("`ai_auto_lookback_days` は 7 以上で指定してください。")
    if ai_train_live_boost is None or ai_train_live_boost < 1.0 or ai_train_live_boost > 3.0:
        errors.append("`ai_train_live_boost` は 1.0〜3.0 で指定してください。")
    if ai_train_shadow_boost is None or ai_train_shadow_boost < 0.1 or ai_train_shadow_boost > 3.0:
        errors.append("`ai_train_shadow_boost` は 0.1〜3.0 で指定してください。")
    if ai_train_backtest_boost is None or ai_train_backtest_boost < 0.05 or ai_train_backtest_boost > 3.0:
        errors.append("`ai_train_backtest_boost` は 0.05〜3.0 で指定してください。")
    if ai_train_include_backtest and not ai_train_backtest_path:
        errors.append("`ai_train_include_backtest=1` の場合は `ai_train_backtest_path` を指定してください。")
    if ai_train_backtest_gate_min_samples < 20:
        errors.append("`ai_train_backtest_gate_min_samples` は 20 以上で指定してください。")
    if ai_train_backtest_gate_expectancy_min is None:
        errors.append("`ai_train_backtest_gate_expectancy_min` は数値で指定してください。")
    if ai_train_backtest_gate_pf_min is None or ai_train_backtest_gate_pf_min <= 0:
        errors.append("`ai_train_backtest_gate_pf_min` は 0 より大きい数値で指定してください。")
    if ai_train_backtest_max_rows < 0:
        errors.append("`ai_train_backtest_max_rows` は 0 以上で指定してください。")
    if ai_train_recent_halflife_days < 1:
        errors.append("`ai_train_recent_halflife_days` は 1 以上で指定してください。")
    if ai_train_weekly_good_hour_boost is None or ai_train_weekly_good_hour_boost < 1.0 or ai_train_weekly_good_hour_boost > 3.0:
        errors.append("`ai_train_weekly_good_hour_boost` は 1.0〜3.0 で指定してください。")
    if ai_train_weekly_bad_hour_penalty is None or ai_train_weekly_bad_hour_penalty < 0.1 or ai_train_weekly_bad_hour_penalty > 1.0:
        errors.append("`ai_train_weekly_bad_hour_penalty` は 0.1〜1.0 で指定してください。")
    if ai_train_weekly_good_hours_raw and not ai_train_weekly_good_hours:
        errors.append("`ai_train_weekly_good_hours` は 0〜23 のカンマ区切りで指定してください（例: 10,11,14）。")
    if ai_train_weekly_bad_hours_raw and not ai_train_weekly_bad_hours:
        errors.append("`ai_train_weekly_bad_hours` は 0〜23 のカンマ区切りで指定してください（例: 12,13,15）。")
    if ai_lot_lock_min_samples < 1:
        errors.append("`ai_lot_lock_min_samples` は 1 以上で指定してください。")
    if ai_lot_lock_max_lot is None or ai_lot_lock_max_lot <= 0:
        errors.append("`ai_lot_lock_max_lot` は 0 より大きい値で指定してください。")
    if ai_monthly_reval_lookback_days < 30:
        errors.append("`ai_monthly_reval_lookback_days` は 30 以上で指定してください。")
    if ai_monthly_reval_min_samples < 50:
        errors.append("`ai_monthly_reval_min_samples` は 50 以上で指定してください。")
    if ai_monthly_reval_pf_min is None or ai_monthly_reval_pf_min <= 0:
        errors.append("`ai_monthly_reval_pf_min` は 0 より大きい数値で指定してください。")
    if ai_monthly_reval_expectancy_min is None:
        errors.append("`ai_monthly_reval_expectancy_min` は数値で指定してください。")
    if ai_monthly_reval_min_improve is None or ai_monthly_reval_min_improve < 0:
        errors.append("`ai_monthly_reval_min_improve` は 0 以上で指定してください。")
    if ai_gate_min_samples < 10:
        errors.append("`ai_gate_min_samples` は 10 以上で指定してください。")
    if ai_gate_expectancy_min is None:
        errors.append("`ai_gate_expectancy_min` は数値で指定してください。")
    if ai_gate_pf_min is None or ai_gate_pf_min <= 0:
        errors.append("`ai_gate_pf_min` は 0 より大きい数値で指定してください。")
    if ai_auto_rollback_lookback_days < 7:
        errors.append("`ai_auto_rollback_lookback_days` は 7 以上で指定してください。")
    if ai_auto_rollback_pf_floor is None or ai_auto_rollback_pf_floor <= 0:
        errors.append("`ai_auto_rollback_pf_floor` は 0 より大きい数値で指定してください。")
    if ai_auto_rollback_expectancy_floor is None:
        errors.append("`ai_auto_rollback_expectancy_floor` は数値で指定してください。")
    if exit_sma_fast_n < 2:
        errors.append("`exit_sma_fast_n` は 2 以上で指定してください。")
    if exit_sma_slow_n <= exit_sma_fast_n:
        errors.append("`exit_sma_slow_n` は `exit_sma_fast_n` より大きくしてください。")
    if exit_tech_min_hold < 0:
        errors.append("`exit_technical_min_hold_min` は 0 以上で指定してください。")

    if safety:
        warns.append("`safety_hard_block=1` のため、新規発注は停止します。")
    if not today_on:
        warns.append("`today_on=0` のため、本日稼働しません。")
    if not trade_enabled:
        warns.append("`trade_enabled=0` のため、売買ロジックは無効です。")
    if observe_only:
        warns.append("`observe_only=1` のため、発注は行いません。")
    if (not paper_mode) and (not live_enabled):
        warns.append("`paper_mode=0` かつ `live_enabled=0` です。実行しても売買しません。")
    if paper_mode and live_enabled:
        warns.append("`paper_mode=1` のため、`live_enabled=1` でも実行はPAPERになります。")
    if exchange_name == "binance":
        warns.append("`exchange_name=binance` は将来移行用の準備状態です（LIVE実行は未実装）。")
    if not ai_auto_train_enabled:
        warns.append("`ai_auto_train_enabled=0` のため、AIしきい値の日次自動更新は停止します。")
    if ai_train_live_only:
        warns.append("`ai_train_live_only=1` のため、AI学習はLIVE実行データのみを使用します。")
    if ai_train_include_shadow:
        warns.append("`ai_train_include_shadow=1` のため、Shadow学習データを重み付きで利用します。")
    if ai_train_include_backtest:
        warns.append("`ai_train_include_backtest=1` のため、過去OHLCVから生成した仮想学習データを補助的に利用します。")
    if ai_train_include_backtest and ai_train_backtest_gate_enabled:
        warns.append("`ai_train_backtest_gate_enabled=1` のため、BACKTEST成績が基準未達なら自動で学習から除外します。")
    if ai_train_live_only and ai_train_include_shadow:
        warns.append("`ai_train_live_only=1` では Shadow(PAPER) データは学習対象外です。")
    if ai_train_live_only and ai_train_include_backtest:
        warns.append("`ai_train_live_only=1` では BACKTEST データは学習対象外です。")
    if ai_train_weekly_feedback_enabled:
        warns.append("`ai_train_weekly_feedback_enabled=1` のため、時間帯別の重み補正をAI学習に適用します。")
        if not ai_train_weekly_good_hours and not ai_train_weekly_bad_hours:
            warns.append("週次フィードバックがONですが、good/bad時間帯が未設定です。")
    if ai_lot_lock_enabled:
        warns.append(
            f"`ai_lot_lock_enabled=1` のため、samples<{ai_lot_lock_min_samples} の間は `ai_lot_lock_max_lot` を上限にLIVEロットを据え置きます。"
        )
        if lot is not None and ai_lot_lock_max_lot is not None and ai_lot_lock_max_lot >= lot:
            warns.append("`ai_lot_lock_max_lot >= lot` のため、ロット据え置きガードの効果は限定的です。")
    if ai_monthly_reval_enabled:
        warns.append(
            f"`ai_monthly_reval_enabled=1` のため、月次でしきい値再評価を実施します（lookback={ai_monthly_reval_lookback_days}d）。"
        )
    if not ai_gate_enabled:
        warns.append("`ai_gate_enabled=0` のため、AI昇格ゲート（PF/Expectancy）が無効です。")
    if not ai_auto_rollback_enabled:
        warns.append("`ai_auto_rollback_enabled=0` のため、悪化時の自動ロールバックは動きません。")
    if exit_tech_enabled:
        warns.append("`exit_technical_enabled=1` です。テクニカルEXITを有効化しています。")
    if exit_tech_enabled and (not exit_tech_only_paper):
        warns.append("`exit_technical_only_paper=0` です。LIVE経路にもテクニカルEXITが適用されます。")
    if streak_stop_enabled:
        warns.append("`streak_stop_enabled=1` です。連敗数が閾値に達すると当日の新規ENTRYを停止します。")

    product_code = str(ctrl.get("product_code", "BTC_JPY")).strip()
    market_type = str(ctrl.get("market_type", "SPOT")).strip().upper()
    if market_type == "SPOT":
        if product_code != "BTC_JPY":
            warns.append(f"`market_type=SPOT` ですが `product_code={product_code}` です。通常は BTC_JPY を使います。")
    elif market_type in ("FX", "CFD", "LIGHTNING"):
        if not product_code.startswith("FX_"):
            warns.append(f"`market_type={market_type}` ですが `product_code={product_code}` です。通常は FX_BTC_JPY を使います。")
        if fx_leverage is not None and fx_leverage > LIVE_START_MAX_FX_LEVERAGE:
            errors.append(
                f"`fx_leverage` は {LIVE_START_MAX_FX_LEVERAGE:.2f} 以下で指定してください（bitFlyer個人口座の上限準拠）。"
            )
        elif fx_leverage is not None and fx_leverage > LIVE_START_WARN_FX_LEVERAGE:
            warns.append("`fx_leverage` が高めです。安全開始は 1.00 推奨です。")
    else:
        warns.append(f"`market_type={market_type}` は独自設定です。product_code と API権限を再確認してください。")

    if (not paper_mode) and live_enabled:
        if exchange_name != "bitflyer":
            errors.append(
                f"LIVE時は `exchange_name=bitflyer` が必要です（現状は {exchange_name} 未実装）。"
            )
        if not str(ctrl.get("keychain_service", "")).strip():
            errors.append("LIVE時は `keychain_service` が必須です。")
        if not str(ctrl.get("keychain_account_key", "")).strip():
            errors.append("LIVE時は `keychain_account_key` が必須です。")
        if not str(ctrl.get("keychain_account_secret", "")).strip():
            errors.append("LIVE時は `keychain_account_secret` が必須です。")

    return errors, warns


LIVE_START_PREFLIGHT_MAX_AGE_MIN = 12 * 60
LIVE_START_RUNCHECK_MAX_AGE_MIN = 12 * 60
LIVE_START_WARN_FX_LEVERAGE = 1.0
LIVE_START_MAX_FX_LEVERAGE = 2.0


def _dedup_texts(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for x in items:
        s = str(x or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _is_live_trade_candidate(ctrl: Dict[str, str]) -> bool:
    today_on = bval_str(ctrl.get("today_on", "0"))
    trade_enabled = bval_str(ctrl.get("trade_enabled", "0"))
    paper_mode = bval_str(ctrl.get("paper_mode", "1"))
    live_enabled = bval_str(ctrl.get("live_enabled", "0"))
    observe_only = bval_str(ctrl.get("observe_only", "0"))
    safety = bval_str(ctrl.get("safety_hard_block", "0"))
    return bool(today_on and trade_enabled and (not paper_mode) and live_enabled and (not observe_only) and (not safety))


def _live_start_gate(main_dir: Path, ctrl: Dict[str, str]) -> Tuple[List[str], List[str], bool]:
    errs, warns = _validate_control_values(ctrl)
    live_candidate = _is_live_trade_candidate(ctrl)
    if not live_candidate:
        return _dedup_texts(errs), _dedup_texts(warns), False

    market_type = str(ctrl.get("market_type", "SPOT")).strip().upper()
    rollout_mode = str(ctrl.get("rollout_mode", "AUTO")).strip().upper()
    timeout_sec = _safe_int(ctrl.get("limit_order_timeout_sec", "30"), 30)
    fx_leverage = safe_float(ctrl.get("fx_leverage"))
    daily_loss = safe_float(ctrl.get("daily_loss_limit_pct"))
    lot = safe_float(ctrl.get("lot"))
    canary_lot = safe_float(ctrl.get("canary_lot"))

    if market_type in ("FX", "CFD", "LIGHTNING") and fx_leverage is not None:
        if fx_leverage > LIVE_START_MAX_FX_LEVERAGE:
            errs.append(
                f"LIVE起動ガード: `fx_leverage={fx_leverage:.2f}` は上限 {LIVE_START_MAX_FX_LEVERAGE:.2f} を超えています。"
            )
        elif fx_leverage > LIVE_START_WARN_FX_LEVERAGE:
            warns.append(
                f"LIVE起動ガード: `fx_leverage={fx_leverage:.2f}` です。安全開始は 1.00 推奨です。"
            )

    if timeout_sec < 10 or timeout_sec > 180:
        errs.append("LIVE起動ガード: `limit_order_timeout_sec` は 10〜180 秒の範囲を推奨します。")

    if daily_loss is not None and daily_loss < -5.0:
        errs.append(
            "LIVE起動ガード: `daily_loss_limit_pct` が緩すぎます（-5.0%未満）。まずは -1.0% 付近を推奨します。"
        )

    if lot is not None and canary_lot is not None and canary_lot > lot:
        errs.append("LIVE起動ガード: `canary_lot` は `lot` 以下にしてください。")

    if rollout_mode == "LIVE":
        warns.append("LIVE起動ガード: `rollout_mode=LIVE` です。CANARY/AUTO での段階導入を推奨します。")

    ok_pf, msg_pf = _ops_check_fresh_ok(main_dir, ["live_preflight"], LIVE_START_PREFLIGHT_MAX_AGE_MIN)
    if not ok_pf:
        errs.append(f"LIVE起動ガード: {msg_pf} 先に `live_preflight` を実行してください。")
    else:
        warns.append(f"preflight: {msg_pf}")

    ok_rc, msg_rc = _ops_check_fresh_ok(
        main_dir, ["run_check.sh", "run_check"], LIVE_START_RUNCHECK_MAX_AGE_MIN
    )
    if not ok_rc:
        errs.append(f"LIVE起動ガード: {msg_rc} 先に `run_check.sh` を実行してください。")
    else:
        warns.append(f"run_check: {msg_rc}")

    return _dedup_texts(errs), _dedup_texts(warns), True


def _suggest_next_actions(
    ctrl: Dict[str, str],
    state_obj: Dict[str, Any],
    lock_info: Dict[str, Any],
    logs_dir: Optional[Path],
    out_dir: Path,
) -> List[str]:
    actions: List[str] = []

    if bval_str(ctrl.get("safety_hard_block", "0")):
        actions.append("緊急停止中です。運用再開するなら `Bot設定` の `safety_hard_block` を OFF にしてください。")
    if not bool(lock_info.get("alive")):
        actions.append("botが停止中です。`ホーム` の `bot起動` で安全起動を実行してください。")
    if not logs_dir:
        actions.append("logs が見つかりません。起動後に `trade_log_YYYYMMDD.csv` が生成されるか確認してください。")
    if not collect_json_reports(out_dir):
        actions.append("監査JSONが未生成です。`成績・分析` で `daily_report` を実行してください。")
    if bval_str(state_obj.get("_risk_stop", "0")):
        actions.append("`risk_stop=ON` です。日次損失ガード発動中のため、新規ENTRYは停止します。")
    if bval_str(state_obj.get("_streak_stop", "0")):
        actions.append("`streak_stop=ON` です。連敗ストップ発動中のため、新規ENTRYは停止します。")
    if not bval_str(ctrl.get("ai_auto_train_enabled", "1")):
        actions.append("AI日次自動チューニングがOFFです。必要なら `ai_auto_train_enabled=1` にしてください。")

    paper_mode = bval_str(ctrl.get("paper_mode", "1"))
    live_enabled = bval_str(ctrl.get("live_enabled", "0"))
    if (not paper_mode) and live_enabled:
        ok_pf, _ = _ops_check_fresh_ok(main_dir=out_dir.parent, titles=["live_preflight"], max_age_min=LIVE_START_PREFLIGHT_MAX_AGE_MIN)
        ok_rc, _ = _ops_check_fresh_ok(main_dir=out_dir.parent, titles=["run_check.sh", "run_check"], max_age_min=LIVE_START_RUNCHECK_MAX_AGE_MIN)
        if not ok_pf:
            actions.append("LIVE起動前に `live_preflight` を実行し、成功ログを更新してください。")
        if not ok_rc:
            actions.append("LIVE起動前に `run_check.sh` を実行し、成功ログを更新してください。")
        if state_obj.get("_live_client_error"):
            actions.append("LIVEクライアントエラーがあります。`ツール` で `live_preflight` を実行して接続を確認してください。")
        else:
            actions.append("LIVE候補です。`live_preflight` と `run_check.sh` を毎日実行してから継続運用してください。")
    else:
        actions.append("まずは安全運用として `safe_paper` プリセットでPAPER運転し、監査が安定してからLIVEへ進んでください。")

    dedup: List[str] = []
    seen = set()
    for a in actions:
        if a in seen:
            continue
        seen.add(a)
        dedup.append(a)
    return dedup[:6]


def _start_runner(
    main_dir: Path,
    interval_sec: int = 300,
    print_tick: bool = False,
    allow_live: bool = False,
) -> Tuple[bool, str]:
    lock = _lock_info(main_dir)
    if lock.get("alive"):
        return False, f"既に起動中です (pid={lock.get('pid')})"

    safe_start = main_dir / "tools" / "safe_start_bot.sh"
    if safe_start.exists():
        cmd = [str(safe_start), "--interval", str(max(30, int(interval_sec)))]
        if print_tick:
            cmd.append("--print-tick")
        if allow_live:
            cmd.append("--allow-live")
        rc, out = _run_subprocess(cmd, cwd=main_dir)
        if rc == 0:
            chk = _lock_info(main_dir)
            if chk.get("alive"):
                return True, f"起動しました (pid={chk.get('pid')})"
            return True, "起動を受け付けました（lock確認待ち）。"
        msg = (out or "").strip()
        if not msg:
            msg = f"safe_start_bot.sh failed rc={rc}"
        return False, msg

    run_py = main_dir / "run.py"
    if not run_py.exists():
        return False, f"run.py が見つかりません: {run_py}"

    log_path = main_dir / "run.log"
    cmd_fallback = [sys.executable, str(run_py), "--interval", str(max(30, int(interval_sec)))]
    if print_tick:
        cmd_fallback.append("--print-tick")

    try:
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(f"\n[dashboard] start request at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            lf.flush()
            subprocess.Popen(
                cmd_fallback,
                cwd=str(main_dir),
                stdout=lf,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
    except Exception as e:
        return False, f"起動失敗: {e}"

    deadline = time.time() + 4.0
    while time.time() < deadline:
        chk = _lock_info(main_dir)
        if chk.get("alive"):
            return True, f"起動しました (pid={chk.get('pid')})"
        time.sleep(0.2)
    return True, "起動コマンドを送信しました（lock確認待ち）。"


def _stop_runner(main_dir: Path) -> Tuple[bool, str]:
    safe_stop = main_dir / "tools" / "safe_stop_bot.sh"
    if safe_stop.exists():
        rc, out = _run_subprocess([str(safe_stop)], cwd=main_dir)
        msg = (out or "").strip()
        if rc == 0:
            return True, msg or "停止しました。"
        # Keep legacy fallback to avoid getting stuck on stop.

    lock = _lock_info(main_dir)
    pid = lock.get("pid")
    if not pid:
        return False, ".run_lock の pid が見つかりません。"
    try:
        pid_i = int(pid)
    except Exception:
        return False, f"pid が不正です: {pid}"

    alive0, st0 = _pid_is_alive(pid_i)
    if not alive0:
        if str(st0).startswith("Z"):
            return True, f"既に停止済みです（zombie state={st0}）。親プロセスの回収待ちです。"
        return True, "既に停止済みです。"

    plan = [
        (signal.SIGINT, "SIGINT", 6.0),
        (signal.SIGTERM, "SIGTERM", 4.0),
        (signal.SIGKILL, "SIGKILL", 2.0),
    ]
    for sig, name, wait_sec in plan:
        try:
            os.kill(pid_i, sig)
        except ProcessLookupError:
            return True, f"停止しました（{name}送信時に既に終了）。"
        except Exception as e:
            if name == "SIGKILL":
                return False, f"停止失敗: {e}"
            continue

        deadline = time.time() + float(wait_sec)
        while time.time() < deadline:
            alive_now, _ = _pid_is_alive(pid_i)
            if not alive_now:
                return True, f"停止しました（{name}）。"
            time.sleep(0.2)

    return False, f"停止要求を送信しましたが、pid={pid_i} がまだ生存しています。手動確認してください。"


def _guard_key(action: str) -> str:
    return f"_confirm_guard_until_{action}"


def _clear_guard(action: str) -> None:
    st.session_state.pop(_guard_key(action), None)


def _clear_all_guards() -> None:
    _clear_guard("runner_start")
    _clear_guard("runner_stop")
    _clear_guard("shadow_runner_start")
    _clear_guard("shadow_runner_stop")
    _clear_guard("force_exit")
    _clear_guard("panic_stop")
    _clear_guard("one_tap_safe_start")
    _clear_guard("one_tap_canary_start")
    _clear_guard("one_tap_eod_close")


def _arm_guard(action: str, ttl_sec: int = 0) -> None:
    _clear_all_guards()
    ttl = int(ttl_sec)
    if ttl <= 0:
        st.session_state[_guard_key(action)] = {"armed": True, "expires_at": None}
        return
    st.session_state[_guard_key(action)] = {"armed": True, "expires_at": time.time() + max(3, ttl)}


def _guard_status(action: str) -> Tuple[bool, int, bool]:
    k = _guard_key(action)
    raw = st.session_state.get(k)
    if raw is None:
        return False, 0, False
    # Backward-compat for old sessions storing float timestamp
    if isinstance(raw, (int, float)):
        try:
            remain = int(float(raw) - time.time())
        except Exception:
            _clear_guard(action)
            return False, 0, False
        if remain <= 0:
            _clear_guard(action)
            return False, 0, False
        return True, remain, True

    if not isinstance(raw, dict):
        _clear_guard(action)
        return False, 0, False
    if not bool(raw.get("armed", False)):
        _clear_guard(action)
        return False, 0, False

    expires_at = raw.get("expires_at")
    if expires_at in (None, "", 0):
        return True, 0, False
    try:
        remain = int(float(expires_at) - time.time())
    except Exception:
        _clear_guard(action)
        return False, 0, False
    if remain <= 0:
        _clear_guard(action)
        return False, 0, False
    return True, remain, True


GUARD_TTL_START_DEFAULT = 0
GUARD_TTL_STOP_DEFAULT = 0


def _pick_days_token(days: List[str]) -> Optional[str]:
    if not days:
        return None
    if len(days) == 1:
        return days[0]
    # days list is likely newest-first; token expects oldest_newest in many tools,
    # but user may pass either; here: oldest-newest for clarity
    d_sorted = sorted(days)
    return f"{d_sorted[0]}-{d_sorted[-1]}"


def _heavy_render_gate(
    *,
    section_key: str,
    render_token: str,
    perf_mode: str,
    info_text: str,
    run_label: str,
    stop_label: str = "停止",
) -> bool:
    if str(perf_mode or "normal").lower() != "lite":
        return True

    token = str(render_token or "")
    token_hash = hashlib.sha1(token.encode("utf-8")).hexdigest()[:10]
    state_key = f"_heavy_render_gate_{section_key}"
    raw = st.session_state.get(state_key)
    enabled = (
        isinstance(raw, dict)
        and bool(raw.get("enabled"))
        and str(raw.get("token", "")) == token
    )

    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        st.info(info_text)
    with c2:
        if st.button(run_label, width="stretch", key=f"{state_key}_run_{token_hash}"):
            st.session_state[state_key] = {
                "enabled": True,
                "token": token,
            }
            st.rerun()
    with c3:
        if enabled and st.button(stop_label, width="stretch", key=f"{state_key}_stop_{token_hash}"):
            st.session_state.pop(state_key, None)
            st.rerun()

    return enabled


def _day8_to_date(day8: str) -> Optional[datetime]:
    try:
        return datetime.strptime(str(day8), "%Y%m%d")
    except Exception:
        return None


def _select_days_by_period(days: List[str], period_key: str) -> List[str]:
    if not days:
        return []
    dts = []
    for d in days:
        dt = _day8_to_date(d)
        if dt is not None:
            dts.append((d, dt))
    if not dts:
        return []
    dts = sorted(dts, key=lambda x: x[1])  # old -> new
    anchor = dts[-1][1]

    if period_key == "last_7d":
        start, end = anchor - timedelta(days=6), anchor
    elif period_key == "prev_7d":
        start, end = anchor - timedelta(days=13), anchor - timedelta(days=7)
    elif period_key == "last_30d":
        start, end = anchor - timedelta(days=29), anchor
    elif period_key == "prev_30d":
        start, end = anchor - timedelta(days=59), anchor - timedelta(days=30)
    elif period_key == "last_365d":
        start, end = anchor - timedelta(days=364), anchor
    elif period_key == "prev_365d":
        start, end = anchor - timedelta(days=729), anchor - timedelta(days=365)
    else:
        return []

    pick = [d for d, dt in dts if start <= dt <= end]
    return sorted(pick, reverse=True)


def _format_pct(x: Optional[float]) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    return f"{x:.3f}%"


def _safe_str(x: Any) -> str:
    try:
        return str(x)
    except Exception:
        return ""


WEEKLY_AI_COMPARE_STATE_KEY = "_weekly_ai_feedback_compare"


def _ai_compare_extract(ai_auto: Any) -> Dict[str, Any]:
    src = ai_auto if isinstance(ai_auto, dict) else {}
    keys = [
        "rows",
        "current_th",
        "best_th",
        "current_metric",
        "best_metric",
        "improve",
        "gate_pass_best",
        "backtest_gate_eval_pf",
        "backtest_gate_eval_expectancy",
        "train_backtest_gate_pass",
        "train_backtest_gate_reason",
    ]
    out: Dict[str, Any] = {}
    for k in keys:
        out[k] = src.get(k)
    return out


def _ai_compare_to_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _extract_pos_ids_from_issues(issues: List[str]) -> List[str]:
    # pos_id format: YYYYMMDD-HHMMSS-(BUY|SELL)-NNN
    pat = re.compile(r"(\d{8}-\d{6}-(?:BUY|SELL)-\d{3})")
    found: List[str] = []
    for s in issues:
        for m in pat.finditer(_safe_str(s)):
            found.append(m.group(1))
    # unique preserve order
    seen = set()
    out = []
    for x in found:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


# =========================
# Home Execution Section Fragment (auto-refresh every 60s)
# =========================
@st.fragment(run_every=60)
def _render_home_execution_section(
    logs_dir: Optional[Path], control_path: Path, state_path: Path
) -> None:
    ctrl, _ = read_control_kv_csv(control_path)
    state: Dict[str, Any] = load_json(state_path) if state_path.exists() else {}
    if not isinstance(state, dict):
        state = {}

    st.markdown("### ⚡ 約定テープ")
    st.caption("直近イベントをテープ表示し、同じ画面でセッション損益と再現分析につなげます。")
    home_days = _recent_log_days(logs_dir, max_days=7)
    rows_recent: List[Dict[str, Any]] = []
    rows_session: List[Dict[str, Any]] = []
    df_pos_recent = pd.DataFrame()
    df_pos_session = pd.DataFrame()
    if home_days:
        session_day = st.selectbox(
            "セッション日（Ladder / Replay）",
            home_days,
            index=0,
            key="home_session_day",
        )
        home_recent_days = home_days[:3]
        rows_recent, df_pos_recent, _, _ = _analytics_dataset_for_days(logs_dir, home_recent_days)
        rows_session, df_pos_session, _, _ = _analytics_dataset_for_days(logs_dir, [session_day])
        _render_execution_tape(rows_recent if rows_recent else rows_session, max_rows=14)

        st.markdown("### 📈 セッション損益ラダー + リスク予算")
        hourly_ladder, ladder_metrics, _ = _build_session_hourly_ladder(df_pos_session, session_day)
        _render_session_ladder_and_risk_budget(
            hourly=hourly_ladder,
            metrics=ladder_metrics,
            ctrl_now=ctrl,
            state_obj=state,
        )

        st.markdown("### 🎬 ワンクリック再現（負けトレード）")
        replay_df = (
            df_pos_session
            if (isinstance(df_pos_session, pd.DataFrame) and not df_pos_session.empty)
            else df_pos_recent
        )
        replay_rows = rows_recent if rows_recent else rows_session
        _render_incident_replay(replay_rows, replay_df)
    else:
        st.info("`logs/trade_log_YYYYMMDD.csv` がまだ無いため、約定テープ / 損益ラダー / 再現表示は待機中です。")

    st.markdown("### 🛡 ドリフト復帰タイムライン")
    _render_drift_recovery_timeline(state)


# =========================
# Home Live Status Fragment (auto-refresh every 30s)
# =========================
@st.fragment(run_every=30)
def _render_home_live_status(control_path: Path, state_path: Path) -> None:
    ctrl, _ = read_control_kv_csv(control_path)
    state: Dict[str, Any] = load_json(state_path) if state_path.exists() else {}
    if not isinstance(state, dict):
        state = {}

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("本日運転", "ON" if bval_str(ctrl.get("today_on")) else "OFF")
    with c2:
        st.metric("運転モード", "PAPER" if bval_str(ctrl.get("paper_mode")) else "LIVE")
    with c3:
        st.metric("監視のみ", "ON" if bval_str(ctrl.get("observe_only")) else "OFF")
    with c4:
        st.metric("安全ブロック", "ON" if bval_str(ctrl.get("safety_hard_block")) else "OFF")

    c5, c6, c7, c8, c9 = st.columns(5)
    with c5:
        st.metric("LIVE許可", "ON" if bval_str(ctrl.get("live_enabled")) else "OFF")
    with c6:
        st.metric("実効ステージ", str(state.get("_effective_stage", "-")))
    with c7:
        st.metric("リスク停止", "ON" if bval_str(state.get("_risk_stop", "0")) else "OFF")
    with c8:
        st.metric("AI自動学習", "ON" if bval_str(ctrl.get("ai_auto_train_enabled", "1")) else "OFF")
    with c9:
        st.metric("連敗停止", "ON" if bval_str(state.get("_streak_stop", "0")) else "OFF")
    st.caption(f"AI最終学習日: {state.get('_ai_auto_train_day', '-')}")
    st.caption(
        "連敗カウント: {}/{}（有効={}）".format(
            _safe_int(state.get("_streak_consecutive_losses", 0), 0),
            max(1, _safe_int(ctrl.get("streak_stop_max_losses", "3"), 3)),
            "ON" if bval_str(ctrl.get("streak_stop_enabled", "0")) else "OFF",
        )
    )

    drift_obj = state.get("_drift_watch", {}) if isinstance(state.get("_drift_watch"), dict) else {}
    if drift_obj:
        gate_obj = drift_obj.get("gate", {}) if isinstance(drift_obj.get("gate"), dict) else {}
        recent_obj = drift_obj.get("recent_metrics", {}) if isinstance(drift_obj.get("recent_metrics"), dict) else {}
        drift_status = str(drift_obj.get("status", "-") or "-").upper()
        closed_n = max(0, _safe_int(recent_obj.get("closed_n", 0), 0))
        min_recent_closed = max(1, _safe_int(gate_obj.get("min_recent_closed", 1), 1))
        remain_samples = max(0, min_recent_closed - closed_n)
        normal_streak = max(0, _safe_int(drift_obj.get("normal_streak", 0), 0))
        need_normals = max(1, _safe_int(gate_obj.get("resume_require_consecutive_normal", 1), 1))
        canary_streak = max(0, _safe_int(drift_obj.get("canary_streak", 0), 0))
        need_canary = max(0, _safe_int(gate_obj.get("resume_canary_runs", 0), 0))
        resume_ready = bool(drift_obj.get("resume_ready"))
        canary_active = bool(drift_obj.get("canary_active"))

        st.markdown("### 🛡 Drift復帰カウンタ")
        d1, d2, d3, d4, d5, d6 = st.columns(6)
        with d1:
            st.metric("ドリフト状態", drift_status)
        with d2:
            st.metric("決済件数", f"{closed_n}/{min_recent_closed}")
        with d3:
            st.metric("判定まで残り", str(remain_samples))
        with d4:
            st.metric("連続NORMAL", f"{normal_streak}/{need_normals}")
        with d5:
            st.metric("復帰準備", "ON" if resume_ready else "OFF")
        with d6:
            if need_canary > 0:
                st.metric("カナリー", f"{canary_streak}/{need_canary}")
            else:
                st.metric("カナリー", "OFF")
        st.caption(
            "drift更新時刻: {} / 理由: {} / canary有効: {}".format(
                drift_obj.get("updated_at", "-"),
                "; ".join([str(x) for x in (drift_obj.get("reasons") or [])]) or "-",
                "ON" if canary_active else "OFF",
            )
        )


# =========================
# Main
# =========================
def main():
    if "lang" not in st.session_state:
        st.session_state["lang"] = "ja"
    if "pos_search" not in st.session_state:
        st.session_state["pos_search"] = ""

    main_dir = get_main_dir()
    _inject_mobile_app_icon(main_dir)
    _auto_record_version_or_commit(main_dir)
    require_dashboard_auth(main_dir)
    auth_sess = st.session_state.get(AUTH_SESSION_KEY, {})
    if isinstance(auth_sess, dict):
        change_actor = str(auth_sess.get("username") or auth_sess.get("email") or "unknown")
    else:
        change_actor = "unknown"
    logs_dir = find_logs_dir(main_dir)
    control_path = find_control_csv(main_dir)
    state_path = find_state_json(main_dir)
    out_dir = daily_report_out_dir(main_dir)

    ctrl_now, ctrl_meta = read_control_kv_csv(control_path)
    lock_info = _lock_info(main_dir)
    state_now = load_json(state_path) if state_path.exists() else {}
    if not isinstance(state_now, dict):
        state_now = {}
    ai_train_log_total = _count_ai_training_log_rows(main_dir)
    ui_cfg_path = ui_config_path(main_dir)
    saved_ui_cfg = _read_json_dict(ui_cfg_path, default={})
    default_tab_order = list(TAB_ORDER_DEFAULT_KEYS)
    density_keys = ("ui_density", "density")
    perf_mode_keys = ("perf_mode", "performance_mode")

    def _normalize_tab_order(raw: Any) -> List[str]:
        out: List[str] = []
        if isinstance(raw, list):
            for x in raw:
                k = str(x).strip()
                if k in default_tab_order and k not in out:
                    out.append(k)
        for k in default_tab_order:
            if k not in out:
                out.append(k)
        return out

    def _normalize_ui_density(raw: Any) -> str:
        v = str(raw or "standard").strip().lower()
        if v in {"compact", "standard", "relaxed"}:
            return v
        return "standard"

    def _normalize_perf_mode(raw: Any) -> str:
        v = str(raw or "normal").strip().lower()
        if v in {"normal", "lite"}:
            return v
        return "normal"

    if "_tab_order_keys" not in st.session_state:
        st.session_state["_tab_order_keys"] = _normalize_tab_order(saved_ui_cfg.get("tab_order"))
    else:
        st.session_state["_tab_order_keys"] = _normalize_tab_order(st.session_state.get("_tab_order_keys"))

    if "_ui_density" not in st.session_state:
        raw_density = None
        for k in density_keys:
            if k in saved_ui_cfg:
                raw_density = saved_ui_cfg.get(k)
                break
        st.session_state["_ui_density"] = _normalize_ui_density(raw_density)
    else:
        st.session_state["_ui_density"] = _normalize_ui_density(st.session_state.get("_ui_density"))

    if "_dashboard_perf_mode" not in st.session_state:
        raw_perf_mode = None
        for k in perf_mode_keys:
            if k in saved_ui_cfg:
                raw_perf_mode = saved_ui_cfg.get(k)
                break
        st.session_state["_dashboard_perf_mode"] = _normalize_perf_mode(raw_perf_mode)
    else:
        st.session_state["_dashboard_perf_mode"] = _normalize_perf_mode(st.session_state.get("_dashboard_perf_mode"))

    def _tab_name(tab_id: str) -> str:
        return T(TAB_I18N_KEY_BY_ID.get(tab_id, tab_id))

    def _persist_ui_config(
        tab_order: Optional[List[str]] = None,
        ui_density: Optional[str] = None,
        perf_mode: Optional[str] = None,
    ) -> None:
        tab_order_now = _normalize_tab_order(tab_order if tab_order is not None else st.session_state.get("_tab_order_keys"))
        density_now = _normalize_ui_density(ui_density if ui_density is not None else st.session_state.get("_ui_density"))
        perf_mode_now = _normalize_perf_mode(
            perf_mode if perf_mode is not None else st.session_state.get("_dashboard_perf_mode")
        )
        _write_json_dict(
            ui_cfg_path,
            {
                "tab_order": [str(x) for x in tab_order_now],
                "ui_density": density_now,
                "perf_mode": perf_mode_now,
            },
        )

    def _persist_tab_order(keys: List[str]) -> None:
        _persist_ui_config(tab_order=keys)

    def _persist_ui_density(v: str) -> None:
        _persist_ui_config(ui_density=v)

    def _persist_perf_mode(v: str) -> None:
        _persist_ui_config(perf_mode=v)

    # Sidebar
    with st.sidebar:
        st.header(T("app_title"))
        st.caption(T("subtitle"))
        auth_user = str(auth_sess.get("username", "-")) if isinstance(auth_sess, dict) else "-"
        auth_type = str(auth_sess.get("auth_type", "LOCAL")) if isinstance(auth_sess, dict) else "LOCAL"
        st.success(f"ログイン中: {auth_user}")
        st.caption(f"auth: {auth_type}")
        sec_cfg_sidebar = _dashboard_security_dict()
        al_emails = _parse_security_list(sec_cfg_sidebar.get("allowed_emails", sec_cfg_sidebar.get("oidc_allowed_emails", [])))
        al_domains = _parse_security_list(sec_cfg_sidebar.get("allowed_email_domains", sec_cfg_sidebar.get("oidc_allowed_domains", [])))
        st.caption(
            "oidc_allowlist: {} (emails={} / domains={})".format(
                "ON" if (al_emails or al_domains) else "OFF",
                len(al_emails),
                len(al_domains),
            )
        )
        if str(auth_type).upper().startswith("LOCAL"):
            cfg_auth = _load_auth_config(main_dir)
            used_bg = _breakglass_usage_today(main_dir)
            lim_bg = max(1, int(cfg_auth.get("breakglass_daily_limit", 3)))
            st.caption(f"breakglass(today): {used_bg}/{lim_bg}")
        nst = st.session_state.get("_dashboard_login_notify_status", {})
        if isinstance(nst, dict) and nst:
            if nst.get("ok", True):
                st.caption(f"login notify: OK ({nst.get('at', '-')})")
            else:
                st.warning(f"login notify: NG ({nst.get('message', '-')})")
        if st.button("🔓 ログアウト", width="stretch"):
            try:
                tok = _auth_cookie_get()
                _auth_revoke_local_token(main_dir, tok)
                _auth_cookie_clear()
            except Exception:
                pass
            st.session_state.pop(AUTH_SESSION_KEY, None)
            st.session_state.pop(AUTH_NOTIFY_SENT_KEY, None)
            is_oidc = str(auth_type).upper().startswith("OIDC")
            if is_oidc and hasattr(st, "logout"):
                try:
                    st.logout()
                except Exception:
                    pass
            st.rerun()
        st.divider()

        st.write("**Paths**")
        st.code(
            f"MAIN: {main_dir}\n"
            f"CONTROL: {control_path}\n"
            f"LOGS: {str(logs_dir) if logs_dir else 'NOT FOUND'}\n"
            f"REPORT_OUT: {out_dir}"
        )
        st.divider()

        st.write("**Quick**")
        if st.button("🔄 再読み込み"):
            try:
                st.cache_data.clear()
            except Exception:
                pass
            st.rerun()

        with st.expander("使い方メモ", expanded=False):
            st.markdown(
                """
- まず `Bot設定` でモード確認
- `ホーム` で稼働状態と直近ログ確認
- `成績・分析` で daily_report/audit 実行
- `ツール` で preflight / ci_check 実行
"""
            )

        st.divider()
        st.write("**AI学習ステータス**")
        ai_auto_sidebar = state_now.get("_ai_auto_train", {}) if isinstance(state_now.get("_ai_auto_train"), dict) else {}
        ai_lookback_days = _safe_int(ctrl_now.get("ai_auto_lookback_days", "45"), 45)
        st.caption(
            "auto_train={} / last_day={}".format(
                "ON" if bval_str(ctrl_now.get("ai_auto_train_enabled", "1")) else "OFF",
                str(state_now.get("_ai_auto_train_day", "-")),
            )
        )
        if ai_auto_sidebar:
            st.caption(
                "used_rows={} / log_total={} (lookback={}d)".format(
                    ai_auto_sidebar.get("rows", "-"),
                    ai_train_log_total,
                    ai_lookback_days,
                )
            )
            st.caption(
                "th={}→{} applied={} live_only={} live_boost={} shadow={} shadow_boost={} backtest={} backtest_boost={} bt_gate={} gate={} rb={} hl={}d".format(
                    ai_auto_sidebar.get("current_th", "-"),
                    ai_auto_sidebar.get("best_th", "-"),
                    ai_auto_sidebar.get("applied", False),
                    ai_auto_sidebar.get("train_live_only", "-"),
                    ai_auto_sidebar.get("train_live_boost", "-"),
                    ai_auto_sidebar.get("train_include_shadow", "-"),
                    ai_auto_sidebar.get("train_shadow_boost", "-"),
                    ai_auto_sidebar.get("train_include_backtest", "-"),
                    ai_auto_sidebar.get("train_backtest_boost", "-"),
                    ai_auto_sidebar.get("train_backtest_gate_pass", "-"),
                    ai_auto_sidebar.get("gate_enabled", "-"),
                    ai_auto_sidebar.get("rollback_enabled", "-"),
                    ai_auto_sidebar.get("train_recent_halflife_days", "-"),
                )
            )
            st.caption(
                "weekly_feedback={} good_hours={} bad_hours={} good_boost={} bad_penalty={}".format(
                    ai_auto_sidebar.get("train_weekly_feedback_enabled", "-"),
                    ai_auto_sidebar.get("train_weekly_good_hours", "-"),
                    ai_auto_sidebar.get("train_weekly_bad_hours", "-"),
                    ai_auto_sidebar.get("train_weekly_good_hour_boost", "-"),
                    ai_auto_sidebar.get("train_weekly_bad_hour_penalty", "-"),
                )
            )
            bt_pass_raw = ai_auto_sidebar.get("train_backtest_gate_pass", None)
            bt_reason = str(ai_auto_sidebar.get("train_backtest_gate_reason", "-"))
            bt_n = ai_auto_sidebar.get("backtest_gate_eval_n", "-")
            bt_pf = ai_auto_sidebar.get("backtest_gate_eval_pf", "-")
            bt_exp = ai_auto_sidebar.get("backtest_gate_eval_expectancy", "-")
            if isinstance(bt_pass_raw, bool):
                bt_badge = ":green[PASS]" if bt_pass_raw else ":red[BLOCK]"
            else:
                bt_badge = ":gray[N/A]"
            st.markdown(
                f"BACKTEST gate: {bt_badge}  "
                f"(reason={bt_reason}, n={bt_n}, pf={bt_pf}, exp={bt_exp})"
            )
        else:
            st.caption(f"log_total={ai_train_log_total} / 履歴なし（bot起動後に日次1回実行）")

        st.write("**Language**")
        st.session_state["lang"] = st.selectbox("lang", ["ja"], index=0)

        st.write("**表示密度**")
        density_options = ["compact", "standard", "relaxed"]
        density_labels = {
            "compact": "コンパクト",
            "standard": "標準",
            "relaxed": "ゆったり",
        }
        density_now = _normalize_ui_density(st.session_state.get("_ui_density"))
        density_pick = st.selectbox(
            "表示密度",
            density_options,
            index=density_options.index(density_now),
            format_func=lambda x: density_labels.get(str(x), str(x)),
            key="sidebar_ui_density_pick",
        )
        if density_pick != density_now:
            st.session_state["_ui_density"] = _normalize_ui_density(density_pick)
            _persist_ui_density(density_pick)
            st.rerun()

        st.write("**パフォーマンス**")
        perf_mode_options = ["normal", "lite"]
        perf_mode_labels = {
            "normal": "標準（すべて描画）",
            "lite": "軽量（重い分析は手動実行）",
        }
        perf_mode_now = _normalize_perf_mode(st.session_state.get("_dashboard_perf_mode"))
        perf_mode_pick = st.selectbox(
            "描画モード",
            perf_mode_options,
            index=perf_mode_options.index(perf_mode_now),
            format_func=lambda x: perf_mode_labels.get(str(x), str(x)),
            key="sidebar_perf_mode_pick",
            help="軽量モードでは Analytics / pos_id タブの重い描画をボタン押下時のみ実行します。",
        )
        if perf_mode_pick != perf_mode_now:
            st.session_state["_dashboard_perf_mode"] = _normalize_perf_mode(perf_mode_pick)
            _persist_perf_mode(perf_mode_pick)
            st.rerun()

        tab_order_keys = list(st.session_state.get("_tab_order_keys", default_tab_order))
        st.write("**タブ順**")
        st.caption("よく使うタブを上に移動できます（設定は保存されます）。")
        reorder_target = st.selectbox(
            "並び替え対象",
            tab_order_keys,
            index=0,
            format_func=_tab_name,
            key="sidebar_tab_reorder_target",
        )
        rr1, rr2, rr3 = st.columns(3)
        with rr1:
            if st.button("⬆ 上へ", width="stretch", key="sidebar_tab_move_up"):
                idx = tab_order_keys.index(reorder_target)
                if idx > 0:
                    tab_order_keys[idx - 1], tab_order_keys[idx] = tab_order_keys[idx], tab_order_keys[idx - 1]
                    st.session_state["_tab_order_keys"] = tab_order_keys
                    _persist_tab_order(tab_order_keys)
                    st.rerun()
        with rr2:
            if st.button("⬇ 下へ", width="stretch", key="sidebar_tab_move_down"):
                idx = tab_order_keys.index(reorder_target)
                if idx < len(tab_order_keys) - 1:
                    tab_order_keys[idx + 1], tab_order_keys[idx] = tab_order_keys[idx], tab_order_keys[idx + 1]
                    st.session_state["_tab_order_keys"] = tab_order_keys
                    _persist_tab_order(tab_order_keys)
                    st.rerun()
        with rr3:
            if st.button("↺ 標準", width="stretch", key="sidebar_tab_move_reset"):
                st.session_state["_tab_order_keys"] = list(default_tab_order)
                _persist_tab_order(list(default_tab_order))
                st.rerun()

        st.write("**タブ移動**")
        st.caption("タブはマウス操作しやすい表示にしてあります。必要ならここから直接ジャンプできます。")
        jump_target = st.selectbox(
            "移動先",
            tab_order_keys,
            index=0,
            format_func=_tab_name,
            key="sidebar_tab_jump_target",
        )
        if st.button("➡ タブへ移動", width="stretch", key="sidebar_tab_jump_btn"):
            st.session_state["_sidebar_tab_jump_key"] = str(jump_target)
            st.rerun()

    perf_mode = _normalize_perf_mode(st.session_state.get("_dashboard_perf_mode"))

    # Header
    ui_status_banner(ctrl_now, lock_info)
    # P3: Preflight staleness banner — show when LIVE-mode bot is running with stale preflight
    if _is_live_trade_candidate(ctrl_now) or str(ctrl_now.get("rollout_mode", "")).upper() == "LIVE":
        _pf_ok, _pf_msg = _ops_check_fresh_ok(main_dir, ["live_preflight"], LIVE_START_PREFLIGHT_MAX_AGE_MIN)
        if not _pf_ok:
            st.warning(f"⚠️ **live_preflight が古い**: {_pf_msg}　→　`ツール` タブで実行してください。")
    _inject_tabs_mouse_friendly_css(st.session_state.get("_ui_density", "standard"))
    _inject_trading_flair_css()
    _render_global_trade_strip(ctrl_now, state_now, lock_info)

    tab_order_keys = _normalize_tab_order(st.session_state.get("_tab_order_keys"))
    tab_labels = [_tab_name(k) for k in tab_order_keys]
    tabs = st.tabs(tab_labels)
    tab_index = {k: i for i, k in enumerate(tab_order_keys)}
    jump_key_raw = st.session_state.pop("_sidebar_tab_jump_key", None)
    if jump_key_raw is not None:
        try:
            jkey = str(jump_key_raw)
            if jkey in tab_index:
                _activate_tab_via_js(int(tab_index[jkey]))
        except Exception:
            pass

    # =========================================================
    # TAB: Home
    # =========================================================
    with tabs[tab_index["home"]]:
        st.subheader("現在の稼働状況")
        st.caption("AI学習ステータスはこのタブ中段と左サイドバーに表示しています。")
        state_obj: Dict[str, Any] = dict(state_now)
        _render_home_market_hero(ctrl_now, state_obj, lock_info)

        _render_home_live_status(control_path, state_path)

        _render_home_execution_section(logs_dir, control_path, state_path)

        # DD ウィジェット
        try:
            _reports_dir = main_dir / "reports"
            _today8_dd = datetime.now().strftime("%Y%m%d")
            _dd_path = _reports_dir / f"dd_report_{_today8_dd}.json"
            if not _dd_path.exists():
                _dd_path = _reports_dir / "dd_report_all-time.json"
            _dd_data: Dict[str, Any] = {}
            if _dd_path.exists():
                try:
                    _dd_data = json.loads(_dd_path.read_text(encoding="utf-8"))
                except Exception:
                    _dd_data = {}
            _dd_metrics = _dd_data.get("metrics") if isinstance(_dd_data.get("metrics"), dict) else {}
            _dd_label = f"DD レポート ({_dd_data.get('target_day8', '-')})" if _dd_data else "DD レポート（ファイルなし）"
            with st.expander(_dd_label, expanded=False):
                if not _dd_data:
                    st.info("dd_report が見つかりません。`python3 tools/dd_report.py YYYYMMDD` を実行してください。")
                else:
                    _dd_n = _dd_metrics.get("n_trades")
                    _dd_amount = _dd_metrics.get("daily_max_drawdown_amount")
                    _dd_pf = _dd_metrics.get("profit_factor")
                    _dd_rf = _dd_metrics.get("recovery_factor")
                    _dd_exp = _dd_metrics.get("expectancy_per_trade_pct")
                    _dd_rec = _dd_metrics.get("dd_recovery_minutes")
                    _ddc1, _ddc2, _ddc3, _ddc4 = st.columns(4)
                    with _ddc1:
                        st.metric("最大DD", f"{_dd_amount:.3f}%pt" if _dd_amount is not None else "算出不可")
                    with _ddc2:
                        st.metric("Profit Factor", f"{_dd_pf:.2f}" if _dd_pf is not None else "-")
                    with _ddc3:
                        st.metric("Recovery Factor", f"{_dd_rf:.2f}" if _dd_rf is not None else "-")
                    with _ddc4:
                        st.metric("期待値/trade", f"{_dd_exp:.4f}%pt" if _dd_exp is not None else "-")
                    _dd_rec_str = f"{_dd_rec:.0f}分" if _dd_rec is not None else "未回復"
                    st.caption(
                        f"N={_dd_n} / DD回復: {_dd_rec_str} / "
                        f"生成: {_dd_data.get('generated_at', '-')} / ソース: {_dd_path.name}"
                    )
        except Exception as _dd_widget_exc:
            st.caption(f"DD ウィジェット読み込みエラー: {_dd_widget_exc}")

        st.markdown("### 💴 資金サマリー（bitFlyer）")
        st.caption("安全保管済みAPIキー（Keychain/ENV）で残高/証拠金を照会します（キー値は表示しません）。")
        f1, f2, f3 = st.columns([1, 1, 3])
        with f1:
            funds_refresh = st.button("🔄 資金更新", width="stretch", key="home_funds_refresh")
        with f2:
            if st.button("🧹 表示クリア", width="stretch", key="home_funds_clear"):
                st.session_state.pop("_home_funds_snapshot", None)
                st.rerun()
        with f3:
            st.caption("FXは証拠金、SPOTは通貨残高を表示。")

        if funds_refresh:
            ok_f, snap_f, msg_f = fetch_live_funds_snapshot(ctrl_now)
            st.session_state["_home_funds_snapshot"] = {"ok": ok_f, "snap": snap_f, "msg": msg_f}

        funds_box = st.session_state.get("_home_funds_snapshot")
        if isinstance(funds_box, dict) and funds_box:
            if not bool(funds_box.get("ok")):
                st.error(f"資金取得に失敗: {funds_box.get('msg', 'unknown')}")
            else:
                snap = funds_box.get("snap", {}) if isinstance(funds_box.get("snap"), dict) else {}
                st.caption(
                    "取得時刻: {} / market_type={} / product={}".format(
                        snap.get("fetched_at", "-"),
                        snap.get("market_type", "-"),
                        snap.get("product_code", "-"),
                    )
                )
                mt = str(snap.get("market_type", "")).upper()
                if mt in ("FX", "CFD", "LIGHTNING"):
                    fc1, fc2, fc3, fc4 = st.columns(4)
                    with fc1:
                        st.metric("証拠金", _fmt_jpy(safe_float(snap.get("collateral_jpy"))))
                    with fc2:
                        st.metric("含み損益", _fmt_jpy(safe_float(snap.get("open_position_pnl"))))
                    with fc3:
                        st.metric("必要証拠金", _fmt_jpy(safe_float(snap.get("require_collateral"))))
                    with fc4:
                        keep_rate = safe_float(snap.get("keep_rate"))
                        st.metric("維持率", "-" if keep_rate is None else f"{keep_rate:.2f}")

                    cap = safe_float(snap.get("cap_notional_jpy"))
                    lev = safe_float(snap.get("fx_leverage"))
                    ratio = safe_float(snap.get("fx_collateral_use_ratio"))
                    st.caption(
                        "発注上限目安(notional): {} （leverage={} / use_ratio={}）".format(
                            _fmt_jpy(cap),
                            _fmt_float(lev, 2),
                            _fmt_float(ratio, 2),
                        )
                    )
                else:
                    sc1, sc2, sc3, sc4 = st.columns(4)
                    with sc1:
                        st.metric("JPY 残高", _fmt_jpy(safe_float(snap.get("jpy_amount"))))
                    with sc2:
                        st.metric("JPY 利用可能", _fmt_jpy(safe_float(snap.get("jpy_available"))))
                    with sc3:
                        st.metric("BTC 残高", _fmt_float(safe_float(snap.get("btc_amount")), 6))
                    with sc4:
                        st.metric("BTC 利用可能", _fmt_float(safe_float(snap.get("btc_available")), 6))
        else:
            st.info("`資金更新` を押すと、現在の資金情報を表示します。")

        st.markdown("### 🕒 リアルタイム相場（現在時刻）")
        st.caption("bitFlyer public executions をページング取得し、ローソク足を生成します（上昇=赤 / 下降=青）。")
        rt_cols = st.columns([2, 1, 1, 1, 1])
        with rt_cols[0]:
            rt_product = st.text_input(
                "product_code (リアルタイム)",
                value=str(ctrl_now.get("product_code", "FX_BTC_JPY")),
                key="home_rt_product_code",
            ).strip() or str(ctrl_now.get("product_code", "FX_BTC_JPY")).strip()
        with rt_cols[1]:
            rt_tf_label = st.selectbox(
                "足種",
                ["1分", "3分", "5分", "15分", "30分", "1時間"],
                index=2,
                key="home_rt_candle_tf",
            )
        with rt_cols[2]:
            rt_count = st.number_input(
                "1ページ件数(executions)",
                min_value=100,
                max_value=500,
                value=500,
                step=100,
                key="home_rt_count",
            )
        with rt_cols[3]:
            rt_window_label = st.selectbox(
                "表示期間",
                ["最新500件", "1時間", "3時間", "6時間", "12時間", "24時間"],
                index=4,
                key="home_rt_window",
            )
        with rt_cols[4]:
            rt_refresh = st.button("🔄 チャート更新", width="stretch", key="home_rt_refresh")

        rt_window_cfg: Dict[str, Tuple[int, int]] = {
            "最新500件": (0, 1),
            "1時間": (1, 20),
            "3時間": (3, 40),
            "6時間": (6, 70),
            "12時間": (12, 120),
            "24時間": (24, 200),
        }
        rt_lookback_h, rt_max_pages = rt_window_cfg.get(str(rt_window_label), (12, 120))
        with st.expander("テクニカル表示（SMA/EMA）", expanded=False):
            ind1, ind2, ind3, ind4 = st.columns([1, 2, 1, 2])
            with ind1:
                rt_show_sma = st.toggle("SMA表示", value=True, key="home_rt_show_sma")
            with ind2:
                rt_sma_periods = st.multiselect(
                    "SMA期間",
                    options=[5, 10, 20, 50, 100, 200],
                    default=[20, 50],
                    key="home_rt_sma_periods",
                ) if rt_show_sma else []
            with ind3:
                rt_show_ema = st.toggle("EMA表示", value=False, key="home_rt_show_ema")
            with ind4:
                rt_ema_periods = st.multiselect(
                    "EMA期間",
                    options=[5, 10, 20, 50, 100, 200],
                    default=[20],
                    key="home_rt_ema_periods",
                ) if rt_show_ema else []

        if rt_refresh or ("_home_rt_exec_df" not in st.session_state):
            try:
                rt_df = fetch_public_executions_df(
                    rt_product,
                    int(rt_count),
                    lookback_hours=int(rt_lookback_h),
                    max_pages=int(rt_max_pages),
                )
                range_start = ""
                range_end = ""
                covered_min = 0.0
                if isinstance(rt_df, pd.DataFrame) and (not rt_df.empty):
                    t0 = pd.to_datetime(rt_df["time_dt"], errors="coerce").min()
                    t1 = pd.to_datetime(rt_df["time_dt"], errors="coerce").max()
                    if (not pd.isna(t0)) and (not pd.isna(t1)):
                        range_start = str(pd.Timestamp(t0).strftime("%Y-%m-%d %H:%M:%S"))
                        range_end = str(pd.Timestamp(t1).strftime("%Y-%m-%d %H:%M:%S"))
                        covered_min = max(0.0, float((t1 - t0).total_seconds() / 60.0))
                st.session_state["_home_rt_exec_df"] = rt_df
                st.session_state["_home_rt_meta"] = {
                    "product_code": rt_product,
                    "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "rows": int(len(rt_df)),
                    "window_label": str(rt_window_label),
                    "page_size": int(rt_count),
                    "max_pages": int(rt_max_pages),
                    "lookback_hours": int(rt_lookback_h),
                    "range_start": range_start,
                    "range_end": range_end,
                    "covered_min": covered_min,
                }
            except Exception as e:
                st.session_state["_home_rt_exec_df"] = pd.DataFrame()
                st.session_state["_home_rt_meta"] = {
                    "product_code": rt_product,
                    "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "rows": 0,
                    "window_label": str(rt_window_label),
                    "page_size": int(rt_count),
                    "max_pages": int(rt_max_pages),
                    "lookback_hours": int(rt_lookback_h),
                    "error": str(e),
                }

        rt_meta = st.session_state.get("_home_rt_meta", {})
        rt_df = st.session_state.get("_home_rt_exec_df", pd.DataFrame())
        if isinstance(rt_meta, dict) and rt_meta:
            st.caption(
                "取得時刻: {} / product={} / rows={} / window={} / page_size={} / max_pages={}".format(
                    rt_meta.get("fetched_at", "-"),
                    rt_meta.get("product_code", "-"),
                    rt_meta.get("rows", "-"),
                    rt_meta.get("window_label", "-"),
                    rt_meta.get("page_size", "-"),
                    rt_meta.get("max_pages", "-"),
                )
            )
            if rt_meta.get("range_start") and rt_meta.get("range_end"):
                st.caption(f"データ範囲: {rt_meta.get('range_start')} ～ {rt_meta.get('range_end')}")
                lb_h = safe_float(rt_meta.get("lookback_hours"))
                cv_m = safe_float(rt_meta.get("covered_min"))
                if lb_h and lb_h > 0 and cv_m is not None and cv_m < (lb_h * 60.0 * 0.7):
                    st.warning(
                        "指定期間に対して取得できた実データ幅が短いです。"
                        " `1ページ件数` を500にし、必要なら足種を短くして確認してください。"
                    )
            if rt_meta.get("error"):
                st.error(f"取得エラー: {rt_meta.get('error')}")

        if isinstance(rt_df, pd.DataFrame) and (not rt_df.empty):
            rt_price_df = executions_to_price_df(rt_df)
            rt_rule = {"1分": "1min", "3分": "3min", "5分": "5min", "15分": "15min", "30分": "30min", "1時間": "1h"}.get(rt_tf_label, "5min")
            rt_ohlc = build_ohlc_from_price_df(rt_price_df, interval_rule=rt_rule, price_col="ltp")
            if rt_ohlc.empty:
                st.info("ローソク足データが不足しています。更新して再確認してください。")
            elif not HAS_PLOTLY:
                rt_line = rt_price_df.set_index("time_dt")[["ltp"]].copy()
                rt_line.columns = [f"LTP ({rt_product})"]
                st.line_chart(rt_line)
            else:
                vol = (
                    rt_df.set_index("time_dt")["size"]
                    .resample(rt_rule)
                    .sum()
                    .rename("volume")
                    .reset_index()
                )
                rt_chart = rt_ohlc.merge(vol, how="left", on="time_dt")
                rt_chart["volume"] = rt_chart["volume"].fillna(0.0)

                fig_rt = go.Figure()
                fig_rt.add_trace(
                    go.Candlestick(
                        x=rt_chart["time_dt"],
                        open=rt_chart["open"],
                        high=rt_chart["high"],
                        low=rt_chart["low"],
                        close=rt_chart["close"],
                        name=f"{rt_product} {rt_tf_label}",
                        increasing_line_color="#d62728",   # 上昇=赤
                        decreasing_line_color="#1f77b4",   # 下降=青
                        increasing_fillcolor="rgba(214,39,40,0.35)",
                        decreasing_fillcolor="rgba(31,119,180,0.35)",
                    )
                )
                fig_rt.add_trace(
                    go.Bar(
                        x=rt_chart["time_dt"],
                        y=rt_chart["volume"],
                        name="出来高",
                        marker_color="rgba(120,120,120,0.35)",
                        yaxis="y2",
                    )
                )

                sma_colors = ["#FFD166", "#06D6A0", "#118AB2", "#EF476F", "#8AC926", "#FF9F1C"]
                for idx, p in enumerate(sorted([int(x) for x in (rt_sma_periods or []) if int(x) > 1])):
                    if len(rt_chart) < p:
                        continue
                    col = f"sma_{p}"
                    rt_chart[col] = rt_chart["close"].rolling(window=p, min_periods=p).mean()
                    fig_rt.add_trace(
                        go.Scatter(
                            x=rt_chart["time_dt"],
                            y=rt_chart[col],
                            mode="lines",
                            name=f"SMA{p}",
                            line=dict(color=sma_colors[idx % len(sma_colors)], width=1.4),
                        )
                    )

                ema_colors = ["#FF6B6B", "#4D96FF", "#6BCB77", "#C77DFF", "#F4A261", "#9B5DE5"]
                for idx, p in enumerate(sorted([int(x) for x in (rt_ema_periods or []) if int(x) > 1])):
                    col = f"ema_{p}"
                    rt_chart[col] = rt_chart["close"].ewm(span=p, adjust=False, min_periods=p).mean()
                    fig_rt.add_trace(
                        go.Scatter(
                            x=rt_chart["time_dt"],
                            y=rt_chart[col],
                            mode="lines",
                            name=f"EMA{p}",
                            line=dict(color=ema_colors[idx % len(ema_colors)], width=1.2, dash="dot"),
                        )
                    )

                fig_rt.update_layout(
                    title=f"リアルタイム ローソク足 ({rt_product} / {rt_tf_label})",
                    yaxis=dict(title="価格", domain=[0.25, 1.0]),
                    yaxis2=dict(title="出来高", domain=[0.0, 0.2], showgrid=False),
                    legend=dict(orientation="h"),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=10, r=10, t=48, b=10),
                    dragmode="pan",
                    hovermode="x unified",
                )
                fig_rt.update_xaxes(
                    title="時刻",
                    showspikes=True,
                    spikemode="across",
                    spikesnap="cursor",
                    rangeslider=dict(visible=True, thickness=0.07),
                )
                fig_rt.update_yaxes(showspikes=True, spikemode="across", fixedrange=False)
                st.plotly_chart(fig_rt, width="stretch", config=_plotly_interactive_config())
                last_close = safe_float(rt_chart["close"].iloc[-1]) if len(rt_chart) else None
                st.caption(f"最新終値: {_fmt_float(last_close, 1)}")
        else:
            st.info("`チャート更新` を押すと、現在時刻のローソク足を表示します。")

        st.markdown("### 🤖 AI学習ステータス")
        ai_auto = state_obj.get("_ai_auto_train", {}) if isinstance(state_obj.get("_ai_auto_train"), dict) else {}
        ai_lookback_days = _safe_int(ctrl_now.get("ai_auto_lookback_days", "45"), 45)
        wf_enabled = ai_auto.get("train_weekly_feedback_enabled")
        if wf_enabled is None:
            wf_enabled = bval_str(
                ctrl_now.get(
                    "ai_train_weekly_feedback_enabled",
                    DEFAULTS["ai_train_weekly_feedback_enabled"],
                )
            )
        wf_good_hours = ai_auto.get(
            "train_weekly_good_hours",
            ctrl_now.get("ai_train_weekly_good_hours", DEFAULTS["ai_train_weekly_good_hours"]),
        )
        wf_bad_hours = ai_auto.get(
            "train_weekly_bad_hours",
            ctrl_now.get("ai_train_weekly_bad_hours", DEFAULTS["ai_train_weekly_bad_hours"]),
        )
        wf_good_boost = ai_auto.get(
            "train_weekly_good_hour_boost",
            ctrl_now.get(
                "ai_train_weekly_good_hour_boost",
                DEFAULTS["ai_train_weekly_good_hour_boost"],
            ),
        )
        wf_bad_penalty = ai_auto.get(
            "train_weekly_bad_hour_penalty",
            ctrl_now.get(
                "ai_train_weekly_bad_hour_penalty",
                DEFAULTS["ai_train_weekly_bad_hour_penalty"],
            ),
        )
        mr_enabled = ai_auto.get(
            "monthly_reval_enabled",
            bval_str(ctrl_now.get("ai_monthly_reval_enabled", DEFAULTS["ai_monthly_reval_enabled"])),
        )
        mr_lookback = ai_auto.get(
            "monthly_reval_lookback_days",
            ctrl_now.get("ai_monthly_reval_lookback_days", DEFAULTS["ai_monthly_reval_lookback_days"]),
        )
        wf_enabled_disp = "ON" if bval_str(wf_enabled) else "OFF"
        mr_enabled_disp = "ON" if bval_str(mr_enabled) else "OFF"
        ai_status_missing_keys = []
        for req_k in ("train_weekly_feedback_enabled", "monthly_reval_enabled"):
            if ai_auto and req_k not in ai_auto:
                ai_status_missing_keys.append(req_k)
        ai1, ai2, ai3, ai4, ai5 = st.columns(5)
        with ai1:
            st.metric("auto_train_enabled", "ON" if bval_str(ctrl_now.get("ai_auto_train_enabled", "1")) else "OFF")
        with ai2:
            st.metric("last_day", str(state_obj.get("_ai_auto_train_day", "-")))
        with ai3:
            st.metric("samples_used", str(ai_auto.get("rows", "-")))
        with ai4:
            st.metric("training_log_total", f"{ai_train_log_total}")
        with ai5:
            st.metric("threshold", f"{ai_auto.get('current_th', '-') } → {ai_auto.get('best_th', '-')}")
        if ai_auto:
            st.caption(
                "auto_train: source={} improve={} applied={} gate_pass={} shadow_rows={} backtest_rows={} bt_gate_pass={} bt_gate_reason={} rollback={} lookback={}d".format(
                    ai_auto.get("source", "-"),
                    ai_auto.get("improve", "-"),
                    ai_auto.get("applied", False),
                    ai_auto.get("gate_pass_best", "-"),
                    ai_auto.get("rows_shadow_raw", "-"),
                    ai_auto.get("rows_backtest_raw", "-"),
                    ai_auto.get("train_backtest_gate_pass", "-"),
                    ai_auto.get("train_backtest_gate_reason", "-"),
                    ai_auto.get("rollback_applied", "-"),
                    ai_lookback_days,
                )
            )
            st.caption(
                "weekly_feedback: enabled={} good_hours={} bad_hours={} good_boost={} bad_penalty={}".format(
                    wf_enabled_disp,
                    _format_hours_for_status(wf_good_hours),
                    _format_hours_for_status(wf_bad_hours),
                    wf_good_boost,
                    wf_bad_penalty,
                )
            )
            st.caption(
                "lot_lock: enabled={} min_samples={} max_lot={}".format(
                    ai_auto.get("ai_lot_lock_enabled", ctrl_now.get("ai_lot_lock_enabled", "-")),
                    ai_auto.get("ai_lot_lock_min_samples", ctrl_now.get("ai_lot_lock_min_samples", "-")),
                    ai_auto.get("ai_lot_lock_max_lot", ctrl_now.get("ai_lot_lock_max_lot", "-")),
                )
            )
            bt_pass_raw = ai_auto.get("train_backtest_gate_pass", None)
            bt_reason = str(ai_auto.get("train_backtest_gate_reason", "-"))
            bt_n = ai_auto.get("backtest_gate_eval_n", "-")
            bt_pf = ai_auto.get("backtest_gate_eval_pf", "-")
            bt_exp = ai_auto.get("backtest_gate_eval_expectancy", "-")
            if isinstance(bt_pass_raw, bool):
                bt_badge = ":green[PASS]" if bt_pass_raw else ":red[BLOCK]"
            else:
                bt_badge = ":gray[N/A]"
            st.markdown(
                f"BACKTEST gate: {bt_badge}  "
                f"(reason={bt_reason}, n={bt_n}, pf={bt_pf}, exp={bt_exp})"
            )
            if str(bt_reason) == "not_requested":
                st.caption(
                    "BACKTEST学習が未要求です。`ai_train_include_backtest=1` を有効化すると、過去検証データを日次学習ゲートに利用できます。"
                )
            st.caption(
                "monthly_reval: enabled={} ran={} applied={} reason={} month={} n={} pf={} exp={} lookback={}d".format(
                    mr_enabled_disp,
                    ai_auto.get("monthly_reval_ran", "-"),
                    ai_auto.get("monthly_reval_applied", "-"),
                    ai_auto.get("monthly_reval_reason", "-"),
                    ai_auto.get("monthly_reval_month", "-"),
                    ai_auto.get("monthly_reval_eval_n", "-"),
                    ai_auto.get("monthly_reval_eval_pf", "-"),
                    ai_auto.get("monthly_reval_eval_expectancy", "-"),
                    mr_lookback,
                )
            )
            if ai_status_missing_keys:
                st.caption(
                    "ℹ️ 学習stateに新キーが不足しているため、一部はCONTROL設定の値を表示しています。"
                )
        else:
            st.caption(f"まだAI自動学習の実行履歴がありません（lookback={ai_lookback_days}d / log_total={ai_train_log_total}）。")

        st.markdown("### 🧾 強制エグジット履歴")
        fe_last = state_obj.get("_manual_force_exit_last")
        fe_hist_raw = state_obj.get("_manual_force_exit_history")
        fe_hist = fe_hist_raw if isinstance(fe_hist_raw, list) else []

        p1, p2, p3 = st.columns([1, 1, 2])
        with p1:
            if st.button("🔎 LIVE残ポジ確認", width="stretch", key="home_live_pos_refresh"):
                ok_p, snap_p, msg_p = fetch_live_position_snapshot(ctrl_now)
                st.session_state["_home_live_pos_snapshot"] = {"ok": ok_p, "snap": snap_p, "msg": msg_p}
        with p2:
            if st.button("🧹 残ポジ表示クリア", width="stretch", key="home_live_pos_clear"):
                st.session_state.pop("_home_live_pos_snapshot", None)
                st.rerun()
        with p3:
            st.caption("取引所側ポジション(net/buy/sell)を確認します。stateのopen_posと食い違いがないか監視用です。")

        if st.button("🧹 強制エグジット履歴クリア", width="stretch", key="home_force_exit_hist_clear"):
            cur = load_json(state_path) if state_path.exists() else {}
            if not isinstance(cur, dict):
                cur = {}
            cur.pop("_manual_force_exit_last", None)
            cur.pop("_manual_force_exit_history", None)
            _write_json_dict(state_path, cur)
            st.success("強制エグジット履歴をクリアしました。")
            st.rerun()

        pos_box = st.session_state.get("_home_live_pos_snapshot")
        if isinstance(pos_box, dict) and pos_box:
            if not bool(pos_box.get("ok")):
                st.error(f"LIVE残ポジ確認失敗: {pos_box.get('msg', 'unknown')}")
            else:
                snap = pos_box.get("snap", {}) if isinstance(pos_box.get("snap"), dict) else {}
                st.caption(
                    "取得時刻: {} / market_type={} / product={}".format(
                        snap.get("fetched_at", "-"),
                        snap.get("market_type", "-"),
                        snap.get("product_code", "-"),
                    )
                )
                pc1, pc2, pc3 = st.columns(3)
                with pc1:
                    st.metric("net_position(BTC)", _fmt_float(safe_float(snap.get("net_position_btc")), 8))
                with pc2:
                    st.metric("buy_total(BTC)", _fmt_float(safe_float(snap.get("buy_total_btc")), 8))
                with pc3:
                    st.metric("sell_total(BTC)", _fmt_float(safe_float(snap.get("sell_total_btc")), 8))

        if isinstance(fe_last, dict) and fe_last:
            fe_status = str(fe_last.get("status", "-"))
            if fe_status in ("OK", "NO_POSITION", "NO_POSITION_STATE_CLEARED", "NO_POSITION_STATE_KEEP"):
                st.success(f"last status: {fe_status}")
            elif fe_status in ("REMAIN", "SEND_ERROR", "VERIFY_ERROR", "POSITION_FETCH_ERROR"):
                st.error(f"last status: {fe_status}")
            else:
                st.warning(f"last status: {fe_status}")

            f1, f2, f3, f4 = st.columns(4)
            with f1:
                st.metric("last_time", str(fe_last.get("time", "-")))
            with f2:
                st.metric("product", str(fe_last.get("product_code", "-")))
            with f3:
                st.metric("net_before", _fmt_float(safe_float(fe_last.get("net_before")), 8))
            with f4:
                st.metric("net_after", _fmt_float(safe_float(fe_last.get("net_after")), 8))
            st.caption(
                "close_side={} filled={} order_ids={}".format(
                    fe_last.get("close_side", "-"),
                    _fmt_float(safe_float(fe_last.get("filled")), 8),
                    fe_last.get("order_ids", "-"),
                )
            )
            if fe_last.get("error"):
                st.caption(f"error: {fe_last.get('error')}")
        else:
            st.info("強制エグジット履歴はまだありません。")

        if fe_hist:
            hist_rows: List[Dict[str, Any]] = []
            for x in list(reversed(fe_hist[-20:])):
                if not isinstance(x, dict):
                    continue
                hist_rows.append(
                    {
                        "time": x.get("time", ""),
                        "status": x.get("status", ""),
                        "product": x.get("product_code", ""),
                        "close_side": x.get("close_side", ""),
                        "net_before": x.get("net_before", ""),
                        "net_after": x.get("net_after", ""),
                        "filled": x.get("filled", ""),
                        "order_ids": x.get("order_ids", ""),
                    }
                )
            if hist_rows:
                st.dataframe(pd.DataFrame(hist_rows), width="stretch", hide_index=True)

        st.divider()
        st.markdown("### 🚀 実行・緊急操作")
        st.info("起動/停止・強制エグジット・クイック実行は `🚀 実行・緊急操作` タブに移動しました。")
        st.caption("`🧪 Shadow起動/停止` はタブ列の一番右にあります。")
        next_steps = _suggest_next_actions(
            ctrl=ctrl_now,
            state_obj=state_obj,
            lock_info=lock_info,
            logs_dir=logs_dir,
            out_dir=out_dir,
        )
        if next_steps:
            st.caption("次の推奨アクション（上位3件）")
            for i, step in enumerate(next_steps[:3], 1):
                st.write(f"{i}. {step}")

        # ----- 価格アラート (Price Alerts) -----
        with st.expander("🔔 価格アラート (BTC/JPY)", expanded=False):
            st.caption("設定した価格水準を最終取引価格が超えた場合にダッシュボード上で警告を表示します。")
            pa_col1, pa_col2, pa_col3 = st.columns([2, 1, 1])
            with pa_col1:
                pa_price = st.number_input(
                    "価格水準 (JPY)",
                    min_value=0.0,
                    value=float(st.session_state.get("_pa_price", 0.0) or 0.0),
                    step=10000.0,
                    format="%.0f",
                    key="pa_price_input",
                )
            with pa_col2:
                pa_dir = st.selectbox("方向", ["以上 (↑)", "以下 (↓)"], key="pa_dir_sel")
            with pa_col3:
                st.write("")
                if st.button("✅ セット", key="pa_set_btn"):
                    if pa_price > 0:
                        st.session_state["_pa_price"] = float(pa_price)
                        st.session_state["_pa_dir"] = "above" if "以上" in pa_dir else "below"
                        st.session_state["_pa_fired"] = False
                        st.success(f"アラート設定: ¥{int(pa_price):,} {'以上' if '以上' in pa_dir else '以下'}")
                if st.button("🗑 クリア", key="pa_clear_btn"):
                    for k in ("_pa_price", "_pa_dir", "_pa_fired"):
                        st.session_state.pop(k, None)
                    st.rerun()

            pa_set = st.session_state.get("_pa_price")
            if pa_set and pa_set > 0:
                # Check against latest trade entry price
                lt_price = None
                try:
                    _s = load_json(state_path) or {}
                    _op = _s.get("_open_pos") or {}
                    if isinstance(_op, dict):
                        lt_price = safe_float(_op.get("entry_price"))
                    if lt_price is None:
                        # fallback: last ltp from state
                        lt_price = safe_float(_s.get("_last_ltp"))
                except Exception:
                    pass
                pa_dir_set = st.session_state.get("_pa_dir", "above")
                fired = st.session_state.get("_pa_fired", False)
                if lt_price is not None:
                    triggered = (pa_dir_set == "above" and lt_price >= pa_set) or \
                                (pa_dir_set == "below" and lt_price <= pa_set)
                    if triggered and not fired:
                        st.session_state["_pa_fired"] = True
                        st.error(f"🔔 価格アラート発動: BTC ¥{int(lt_price):,} {'≥' if pa_dir_set=='above' else '≤'} ¥{int(pa_set):,}")
                    elif triggered:
                        st.warning(f"🔔 アラート済: BTC ¥{int(lt_price):,} {'≥' if pa_dir_set=='above' else '≤'} ¥{int(pa_set):,}")
                    else:
                        st.info(f"監視中: 設定 ¥{int(pa_set):,} {'以上' if pa_dir_set=='above' else '以下'} / 現在 ¥{int(lt_price):,}")
                else:
                    st.info(f"監視中: 設定 ¥{int(pa_set):,} {'以上' if pa_dir_set=='above' else '以下'} (LTP 取得待ち)")

        # スタンドアロンダッシュボードへのリンク
        with st.expander("🌐 スタンドアロン マーケットダッシュボード", expanded=False):
            st.caption("ブラウザ単体で動作する Bloomberg スタイルのダッシュボードです（Streamlit 不要）。")
            st.markdown(
                "**`MAIN/tools/market_dashboard.html`** を任意のブラウザで開いてください。\n\n"
                "接続設定（⚙）で以下を入力:\n"
                "- URL: `http://<VM_IP>:8787`\n"
                "- Token: widget server のトークン（secrets.toml の `widget_status_token` または起動引数）\n\n"
                "**機能**: リアルタイム状態・週次P&L・価格アラート（ブラウザ通知）・30秒自動更新"
            )

    # =========================================================
    # TAB: Ops
    # =========================================================
    with tabs[tab_index["ops"]]:
        st.subheader("実行・緊急操作")
        st.caption("起動/停止、強制エグジット、クイック実行をこのタブに集約しています。")

        state_obj = dict(state_now)

        st.markdown("### 🗺 運用フロー（推奨順）")
        st.markdown(
            """
1. `Bot設定` でモードと安全スイッチ確認（`paper_mode/live_enabled/safety_hard_block`）
2. `クイック実行` で `live_preflight` と `run_check.sh` を実行
3. `bot 起動/停止` で安全起動を実行
4. `直近ログ` と `effective_stage/risk_stop` を監視
5. `成績・分析` で `daily_report` と `audit` を更新
6. 停止時は `強制エグジット履歴` と `LIVE残ポジ確認` で `net_after=0` を確認
"""
        )

        st.divider()
        st.markdown("### 🧭 次にやること（自動提案）")
        for i, step in enumerate(
            _suggest_next_actions(
                ctrl=ctrl_now,
                state_obj=state_obj,
                lock_info=lock_info,
                logs_dir=logs_dir,
                out_dir=out_dir,
            ),
            1,
        ):
            st.write(f"{i}. {step}")

        st.divider()
        st.markdown("### ⚡ ワンタップ運用")
        st.caption("朝の安全起動、CANARY起動、EODクローズを2段階ガードで実行します。")
        otp_cfg1, otp_cfg2 = st.columns(2)
        with otp_cfg1:
            one_tap_interval = st.number_input(
                "ワンタップ起動 interval (秒)",
                min_value=30,
                max_value=3600,
                value=300,
                step=30,
                key="home_onetap_interval_sec",
            )
        with otp_cfg2:
            one_tap_print = st.toggle(
                "ワンタップ起動で tickログを出力",
                value=False,
                key="home_onetap_print_tick",
            )

        ot1, ot2, ot3 = st.columns(3)
        with ot1:
            ot_safe_armed, ot_safe_left, ot_safe_timed = _guard_status("one_tap_safe_start")
            if not ot_safe_armed:
                if st.button("🌅 朝の安全起動 (1/2 準備)", width="stretch"):
                    _arm_guard("one_tap_safe_start", ttl_sec=45)
                    st.warning("朝の安全起動の準備を有効化しました。45秒以内に `2/2 実行` を押してください。")
                    st.rerun()
            else:
                if ot_safe_timed:
                    st.warning(f"確認待ち: 残り {ot_safe_left} 秒")
                else:
                    st.warning("確認待ち")
                if st.button("🌅 朝の安全起動 (2/2 実行)", width="stretch", type="primary"):
                    _clear_guard("one_tap_safe_start")
                    ok_prof, msg_prof = _apply_control_profile(
                        main_dir,
                        control_path,
                        ctrl_now,
                        "safe_paper",
                        author=change_actor,
                        reason="ops:one_tap_safe_paper",
                    )
                    if not ok_prof:
                        st.error(f"safe_paper適用失敗: {msg_prof}")
                    else:
                        ok_run, msg_run = _start_runner(
                            main_dir,
                            interval_sec=int(one_tap_interval),
                            print_tick=bool(one_tap_print),
                            allow_live=False,
                        )
                        if ok_run:
                            st.success(f"safe_paper + 起動完了: {msg_run}")
                            st.rerun()
                        else:
                            st.error(f"起動失敗: {msg_run}")

        with ot2:
            ot_canary_armed, ot_canary_left, ot_canary_timed = _guard_status("one_tap_canary_start")
            if not ot_canary_armed:
                if st.button("🧪 CANARY起動 (1/2 準備)", width="stretch"):
                    _arm_guard("one_tap_canary_start", ttl_sec=45)
                    st.warning("CANARY起動の準備を有効化しました。45秒以内に `2/2 実行` を押してください。")
                    st.rerun()
            else:
                if ot_canary_timed:
                    st.warning(f"確認待ち: 残り {ot_canary_left} 秒")
                else:
                    st.warning("確認待ち")
                if st.button("🧪 CANARY起動 (2/2 実行)", width="stretch", type="primary"):
                    _clear_guard("one_tap_canary_start")
                    canary_ctrl, emsg = _build_profile_control(ctrl_now, "live_canary")
                    if canary_ctrl is None:
                        st.error(f"live_canary適用前チェック失敗: {emsg}")
                    else:
                        gate_errs, gate_warns, _ = _live_start_gate(main_dir, canary_ctrl)
                        if gate_errs:
                            st.error("CANARY起動を中止しました。起動前セーフティゲートを満たしていません。")
                            for x in gate_errs:
                                st.write(f"- {x}")
                        else:
                            ok_prof, msg_prof = _apply_control_profile(
                                main_dir,
                                control_path,
                                ctrl_now,
                                "live_canary",
                                author=change_actor,
                                reason="ops:one_tap_live_canary",
                            )
                            if not ok_prof:
                                st.error(f"live_canary適用失敗: {msg_prof}")
                            else:
                                if gate_warns:
                                    st.warning("注意事項があります。")
                                    for x in gate_warns[:4]:
                                        st.write(f"- {x}")
                                ok_run, msg_run = _start_runner(
                                    main_dir,
                                    interval_sec=int(one_tap_interval),
                                    print_tick=bool(one_tap_print),
                                    allow_live=True,
                                )
                                if ok_run:
                                    st.success(f"live_canary + 起動完了: {msg_run}")
                                    st.rerun()
                                else:
                                    st.error(f"起動失敗: {msg_run}")

        with ot3:
            ot_eod_armed, ot_eod_left, ot_eod_timed = _guard_status("one_tap_eod_close")
            if not ot_eod_armed:
                if st.button("🌙 EODクローズ (1/2 準備)", width="stretch"):
                    _arm_guard("one_tap_eod_close", ttl_sec=45)
                    st.warning("EODクローズの準備を有効化しました。45秒以内に `2/2 実行` を押してください。")
                    st.rerun()
            else:
                if ot_eod_timed:
                    st.warning(f"確認待ち: 残り {ot_eod_left} 秒")
                else:
                    st.warning("確認待ち")
                if st.button("🌙 EODクローズ (2/2 実行)", width="stretch", type="primary"):
                    _clear_guard("one_tap_eod_close")
                    ok_stop, msg_stop = _stop_runner(main_dir)
                    if ok_stop:
                        st.success(f"bot停止: {msg_stop}")
                    else:
                        st.warning(f"bot停止: {msg_stop}")
                    ok_fx, msg_fx = force_exit_live_position(
                        main_dir=main_dir,
                        ctrl=ctrl_now,
                        state_path=state_path,
                        logs_dir=logs_dir,
                    )
                    if ok_fx:
                        st.success(f"強制エグジット: {msg_fx}")
                    else:
                        st.warning(f"強制エグジット: {msg_fx}")
                    upd = dict(ctrl_now)
                    upd["today_on"] = "0"
                    upd["safety_hard_block"] = "1"
                    okw, msgw = write_control_kv_csv_with_log(
                        main_dir=main_dir,
                        path=control_path,
                        before_ctrl=ctrl_now,
                        after_ctrl=upd,
                        author=change_actor,
                        reason="ops:one_tap_eod_close",
                    )
                    if okw:
                        st.success("today_on=0 / safety_hard_block=1 を適用しました。")
                    else:
                        st.error(f"CONTROL更新失敗: {msgw}")
                    st.rerun()

        st.divider()
        st.markdown("### 🎮 bot 起動/停止")
        st.caption("誤操作防止のため2段階ガードです。`1/2 準備` の後に `2/2 実行` を押してください。")
        is_running = bool(lock_info.get("alive"))
        start_gate_errs, start_gate_warns, start_gate_live = _live_start_gate(main_dir, ctrl_now)
        start_blocked = bool(start_gate_errs)
        with st.expander("🛡 起動前セーフティゲート", expanded=start_blocked):
            if start_gate_live:
                st.caption("LIVE売買条件のため、preflight/run_checkとリスク上限をチェックしています。")
            else:
                st.caption("現在はLIVE売買条件ではないため、基本チェックのみです。")
            if start_gate_errs:
                st.error("起動ブロック中: 先に以下を解消してください。")
                for x in start_gate_errs:
                    st.write(f"- {x}")
            else:
                st.success("起動前チェックは通過しています。")
            if start_gate_warns:
                st.warning("注意事項")
                for x in start_gate_warns[:6]:
                    st.write(f"- {x}")
            sg1, sg2 = st.columns(2)
            with sg1:
                if st.button("🔐 live_preflight 実行（ゲート更新）", width="stretch", key="home_startgate_preflight"):
                    preflight_py = main_dir / "tools" / "live_preflight.py"
                    if preflight_py.exists():
                        _run_action_block("live_preflight", [sys.executable, str(preflight_py)], main_dir)
                        st.rerun()
                    else:
                        st.error(f"見つかりません: {preflight_py}")
            with sg2:
                if st.button("✅ run_check.sh 実行（ゲート更新）", width="stretch", key="home_startgate_runcheck"):
                    run_check_sh = main_dir / "run_check.sh"
                    if run_check_sh.exists():
                        _run_action_block("run_check.sh", ["bash", str(run_check_sh)], main_dir)
                        st.rerun()
                    else:
                        st.error(f"見つかりません: {run_check_sh}")
        if is_running:
            _clear_guard("runner_start")
        else:
            _clear_guard("runner_stop")
        r1, r2, r3 = st.columns([2, 1, 1])
        with r1:
            run_interval = st.number_input(
                "run.py interval (秒)",
                min_value=30,
                max_value=3600,
                value=300,
                step=30,
                key="home_run_interval_sec",
            )
            run_print_tick = st.toggle("tickログを出力 (--print-tick)", value=False, key="home_run_print_tick")
            stop_with_force_exit = st.toggle(
                "停止時に未決済LIVEポジを強制エグジット",
                value=True,
                key="home_stop_force_exit",
            )
            gcfg1, gcfg2 = st.columns(2)
            with gcfg1:
                guard_ttl_start = st.number_input(
                    "起動確認秒数 (0=無期限)",
                    min_value=0,
                    max_value=300,
                    value=GUARD_TTL_START_DEFAULT,
                    step=1,
                    key="home_guard_ttl_start",
                )
            with gcfg2:
                guard_ttl_stop = st.number_input(
                    "停止確認秒数 (0=無期限)",
                    min_value=0,
                    max_value=300,
                    value=GUARD_TTL_STOP_DEFAULT,
                    step=1,
                    key="home_guard_ttl_stop",
                )
        with r2:
            start_armed, start_left, start_timed = _guard_status("runner_start")
            if not start_armed:
                if st.button("▶ bot起動 (1/2 準備)", width="stretch", disabled=(is_running or start_blocked)):
                    _arm_guard("runner_start", ttl_sec=int(guard_ttl_start))
                    if int(guard_ttl_start) > 0:
                        st.warning(f"起動準備を有効化しました。{int(guard_ttl_start)}秒以内に `2/2 実行` を押してください。")
                    else:
                        st.warning("起動準備を有効化しました。`2/2 実行` を押してください（無期限待機）。")
                    st.rerun()
            else:
                if start_timed:
                    st.warning(f"起動確認待ち（2/2 実行）: 残り {start_left} 秒")
                    st.caption("※ 秒表示は画面操作時に更新されます。")
                else:
                    st.warning("起動確認待ち（2/2 実行）")
                if st.button("▶ bot起動 (2/2 実行)", type="primary", width="stretch", disabled=(is_running or start_blocked)):
                    _clear_guard("runner_start")
                    gate_errs_now, gate_warns_now, _ = _live_start_gate(main_dir, ctrl_now)
                    if gate_errs_now:
                        st.error("起動を中止しました。起動前セーフティゲートを満たしていません。")
                        for x in gate_errs_now:
                            st.write(f"- {x}")
                    else:
                        if gate_warns_now:
                            st.warning("注意事項があります。")
                            for x in gate_warns_now[:4]:
                                st.write(f"- {x}")
                        ok, msg = _start_runner(
                            main_dir,
                            interval_sec=int(run_interval),
                            print_tick=bool(run_print_tick),
                            allow_live=bool(start_gate_live),
                        )
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.warning(msg)
        with r3:
            stop_armed, stop_left, stop_timed = _guard_status("runner_stop")
            if not stop_armed:
                if st.button("■ bot停止 (1/2 準備)", width="stretch", disabled=(not is_running)):
                    _arm_guard("runner_stop", ttl_sec=int(guard_ttl_stop))
                    if int(guard_ttl_stop) > 0:
                        st.warning(f"停止準備を有効化しました。{int(guard_ttl_stop)}秒以内に `2/2 実行` を押してください。")
                    else:
                        st.warning("停止準備を有効化しました。`2/2 実行` を押してください（無期限待機）。")
                    st.rerun()
            else:
                if stop_timed:
                    st.warning(f"停止確認待ち（2/2 実行）: 残り {stop_left} 秒")
                    st.caption("※ 秒表示は画面操作時に更新されます。")
                else:
                    st.warning("停止確認待ち（2/2 実行）")
                if st.button("■ bot停止 (2/2 実行)", width="stretch", disabled=(not is_running)):
                    _clear_guard("runner_stop")
                    ok, msg = _stop_runner(main_dir)
                    if ok:
                        st.success(msg)
                        if bool(stop_with_force_exit):
                            ok_fx, msg_fx = force_exit_live_position(
                                main_dir=main_dir,
                                ctrl=ctrl_now,
                                state_path=state_path,
                                logs_dir=logs_dir,
                            )
                            if ok_fx:
                                st.success(f"強制エグジット: {msg_fx}")
                            else:
                                st.error(f"強制エグジット失敗: {msg_fx}")
                        st.rerun()
                    else:
                        st.error(msg)

        g1, g2, g3 = st.columns([1, 1, 2])
        with g1:
            if st.button("確認状態を解除", width="stretch"):
                _clear_all_guards()
                st.rerun()
        with g2:
            if st.button("stale .run_lock クリア", width="stretch"):
                ok_cl, msg_cl = _clear_stale_run_lock(main_dir)
                if ok_cl:
                    st.success(msg_cl)
                else:
                    st.warning(msg_cl)
                st.rerun()
        with g3:
            st.caption(
                "lock status: alive={} pid={} state={}".format(
                    bool(lock_info.get("alive")),
                    lock_info.get("pid"),
                    lock_info.get("state") or "-",
                )
            )

        st.markdown("### 🧨 強制エグジット（LIVE）")
        st.caption("未決済LIVEポジションを即時クローズします。2段階ガードです。bot停止中でも実行できます。")
        fx1, fx2 = st.columns(2)
        force_armed, force_left, force_timed = _guard_status("force_exit")
        with fx1:
            if not force_armed:
                if st.button("🧨 強制エグジット (1/2 準備)", width="stretch"):
                    _arm_guard("force_exit", ttl_sec=45)
                    st.warning("強制エグジット準備を有効化しました。45秒以内に `2/2 実行` を押してください。")
                    st.rerun()
            else:
                if force_timed:
                    st.warning(f"強制エグジット確認待ち（2/2 実行）: 残り {force_left} 秒")
                else:
                    st.warning("強制エグジット確認待ち（2/2 実行）")
        with fx2:
            if st.button("🧨 強制エグジット (2/2 実行)", width="stretch", type="primary", disabled=(not force_armed)):
                _clear_guard("force_exit")
                ok_fx, msg_fx = force_exit_live_position(
                    main_dir=main_dir,
                    ctrl=ctrl_now,
                    state_path=state_path,
                    logs_dir=logs_dir,
                )
                if ok_fx:
                    st.success(msg_fx)
                else:
                    st.error(msg_fx)
                st.rerun()

        st.markdown("### 🚨 緊急停止 + 強制エグジット")
        st.caption("bot停止・強制エグジット・safety_hard_block=1 を一括実行します。")
        px1, px2 = st.columns(2)
        panic_armed, panic_left, panic_timed = _guard_status("panic_stop")
        with px1:
            if not panic_armed:
                if st.button("🚨 一括停止 (1/2 準備)", width="stretch"):
                    _arm_guard("panic_stop", ttl_sec=45)
                    st.warning("一括停止の準備を有効化しました。45秒以内に `2/2 実行` を押してください。")
                    st.rerun()
            else:
                if panic_timed:
                    st.warning(f"一括停止確認待ち（2/2 実行）: 残り {panic_left} 秒")
                else:
                    st.warning("一括停止確認待ち（2/2 実行）")
        with px2:
            if st.button("🚨 一括停止 (2/2 実行)", width="stretch", type="primary", disabled=(not panic_armed)):
                _clear_guard("panic_stop")
                ok_stop, msg_stop = _stop_runner(main_dir)
                if ok_stop:
                    st.success(f"bot停止: {msg_stop}")
                else:
                    st.warning(f"bot停止: {msg_stop}")
                ok_fx, msg_fx = force_exit_live_position(
                    main_dir=main_dir,
                    ctrl=ctrl_now,
                    state_path=state_path,
                    logs_dir=logs_dir,
                )
                if ok_fx:
                    st.success(f"強制エグジット: {msg_fx}")
                else:
                    st.error(f"強制エグジット失敗: {msg_fx}")

                # Emergency operation: enforce hard block after panic action.
                upd = dict(ctrl_now)
                upd["safety_hard_block"] = "1"
                okw, msgw = write_control_kv_csv_with_log(
                    main_dir=main_dir,
                    path=control_path,
                    before_ctrl=ctrl_now,
                    after_ctrl=upd,
                    author=change_actor,
                    reason="ops:panic_stop",
                )
                if okw:
                    st.success("safety_hard_block=1 を適用しました。")
                else:
                    st.error(f"safety_hard_block 更新失敗: {msgw}")
                st.rerun()

        st.divider()
        st.markdown("### ⚡ クイック実行（ダッシュボード内で完結）")
        st.caption("推奨順: `live_preflight` → `run_check.sh` → `daily_report`。必要に応じて `ci_check` を追加実行。")
        days_for_quick = list_log_days(logs_dir) if logs_dir else []
        q1, q2, q3, q4 = st.columns(4)
        with q1:
            if st.button("🔐 live_preflight 実行", width="stretch"):
                preflight_py = main_dir / "tools" / "live_preflight.py"
                if preflight_py.exists():
                    _run_action_block("live_preflight", [sys.executable, str(preflight_py)], main_dir)
                else:
                    st.error(f"見つかりません: {preflight_py}")
        with q2:
            if st.button("🧪 ci_check 実行", width="stretch"):
                ci_py = main_dir / "ci_check.py"
                if not ci_py.exists():
                    st.error("ci_check.py が見つかりません。")
                else:
                    day_arg = days_for_quick[0] if days_for_quick else ""
                    cmd = [sys.executable, str(ci_py)]
                    if day_arg:
                        cmd.append(day_arg)
                    _run_action_block("ci_check", cmd, main_dir)
        with q3:
            if st.button("✅ run_check.sh 実行", width="stretch"):
                run_sh = main_dir / "run_check.sh"
                if not run_sh.exists():
                    st.error("run_check.sh が見つかりません。")
                else:
                    day_arg = days_for_quick[0] if days_for_quick else ""
                    cmd = ["bash", str(run_sh)]
                    if day_arg:
                        cmd.append(day_arg)
                    _run_action_block("run_check.sh", cmd, main_dir)
        with q4:
            if st.button("📊 daily_report(最新日)", width="stretch"):
                daily_py = main_dir / "daily_report.py"
                if not daily_py.exists():
                    st.error("daily_report.py が見つかりません。")
                elif not days_for_quick:
                    st.error("対象ログ日が見つかりません。")
                else:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    cmd = [sys.executable, str(daily_py), days_for_quick[0], "--out-dir", str(out_dir)]
                    _run_action_block("daily_report", cmd, main_dir)

        st.divider()
        st.markdown("### 🔔 直近ログ（最新5件）")

        if not logs_dir:
            st.warning("logs/ が見つかりません。")
        else:
            days = list_log_days(logs_dir)
            if not days:
                st.warning("trade_log_YYYYMMDD.csv が見つかりません。")
            else:
                latest_day = days[0]
                p = logs_dir / f"trade_log_{latest_day}.csv"
                df = read_trade_log_df(p, file_cache_token(p))
                if df.empty:
                    st.info("ログは空です。")
                else:
                    cols = [c for c in ["time", "result", "side", "price", "ltp", "spread_pct", "signal", "pos_id", "note"] if c in df.columns]
                    st.dataframe(df[cols].tail(5).iloc[::-1], width="stretch")

        st.divider()
        st.markdown("### ✅ 監査JSON（daily_report_out）")
        rep_files = collect_json_reports(out_dir)
        if rep_files:
            st.success(f"監査JSONあり：{len(rep_files)} 件（最新: {rep_files[0].name}）")
        else:
            st.info("監査JSONはまだありません（daily_report を実行してください）。")

    # =========================================================
    # TAB: Settings (CONTROL)
    # =========================================================
    with tabs[tab_index["settings"]]:
        st.subheader("Bot設定 (CONTROL.csv)")
        st.caption("SPEC: key,value / 未知キー保持 / DEFAULTS外も保存維持")
        st.info("まずはプリセットで状態を切り替え、必要に応じて下の詳細項目を調整する運用がおすすめです。")

        with st.expander("CONTROLメタ情報", expanded=False):
            st.json(ctrl_meta)

        cur_errors, cur_warns = _validate_control_values(ctrl_now)
        with st.expander("🔎 設定の整合性チェック", expanded=bool(cur_errors)):
            if cur_errors:
                st.error("修正必須の項目があります。")
                for x in cur_errors:
                    st.write(f"- {x}")
            else:
                st.success("必須エラーはありません。")
            if cur_warns:
                st.warning("注意事項")
                for x in cur_warns:
                    st.write(f"- {x}")

        st.markdown("### 🎛 クイックプリセット")
        p1, p2, p3 = st.columns(3)
        with p1:
            if st.button("🧪 安全PAPER", width="stretch"):
                ok, msg = _apply_control_profile(
                    main_dir,
                    control_path,
                    ctrl_now,
                    "safe_paper",
                    author=change_actor,
                    reason="settings:quick_safe_paper",
                )
                if ok:
                    st.success("安全PAPERプリセットを適用しました。")
                    st.rerun()
                else:
                    st.error(f"適用失敗: {msg}")
        with p2:
            if st.button("🚀 LIVE-CANARY", width="stretch"):
                ok, msg = _apply_control_profile(
                    main_dir,
                    control_path,
                    ctrl_now,
                    "live_canary",
                    author=change_actor,
                    reason="settings:quick_live_canary",
                )
                if ok:
                    st.success("LIVE-CANARYプリセットを適用しました。")
                    st.rerun()
                else:
                    st.error(f"適用失敗: {msg}")
        with p3:
            if st.button("🛑 緊急停止", width="stretch"):
                ok, msg = _apply_control_profile(
                    main_dir,
                    control_path,
                    ctrl_now,
                    "emergency_stop",
                    author=change_actor,
                    reason="settings:quick_emergency_stop",
                )
                if ok:
                    st.success("緊急停止プリセットを適用しました。")
                    st.rerun()
                else:
                    st.error(f"適用失敗: {msg}")

        # Grouping
        with st.form("control_form"):
            st.markdown("### 🚦 基本スイッチ")
            st.caption("today_on/trade_enabled/safety_hard_block の3つが最優先。挙動が分からない時はここを最初に確認します。")
            a1, a2, a3, a4, a5 = st.columns(5)
            with a1:
                f_today = st.toggle("today_on", value=bval_str(ctrl_now.get("today_on")))
            with a2:
                f_trade = st.toggle("trade_enabled", value=bval_str(ctrl_now.get("trade_enabled")))
            with a3:
                f_paper = st.toggle("paper_mode", value=bval_str(ctrl_now.get("paper_mode")))
            with a4:
                f_live = st.toggle("live_enabled", value=bval_str(ctrl_now.get("live_enabled")))
            with a5:
                f_safety = st.toggle("safety_hard_block", value=bval_str(ctrl_now.get("safety_hard_block")))
            f_observe = st.toggle("observe_only", value=bval_str(ctrl_now.get("observe_only")))

            st.markdown("### 💰 リスク/利確/損切")
            st.caption("ここは売買ロジックの中心パラメータです。大きく変える場合はPAPERで先に確認してください。")
            b1, b2, b3, b4, b5 = st.columns(5)
            with b1:
                f_tp_buy = st.text_input("tp_buy_pct", value=ctrl_now.get("tp_buy_pct", DEFAULTS["tp_buy_pct"]))
            with b2:
                f_tp_sell = st.text_input("tp_sell_pct", value=ctrl_now.get("tp_sell_pct", DEFAULTS["tp_sell_pct"]))
            with b3:
                f_sl = st.text_input("sl_pct", value=ctrl_now.get("sl_pct", DEFAULTS["sl_pct"]))
            with b4:
                f_lot = st.text_input("lot", value=ctrl_now.get("lot", DEFAULTS["lot"]))
            with b5:
                f_win = st.text_input("win_min", value=ctrl_now.get("win_min", DEFAULTS["win_min"]))

            st.markdown("### 🧯 制限/品質フィルタ")
            st.caption("spread上限・日次回数・timeoutモードなど、過剰取引を防ぐ設定です。")
            c1, c2, c3 = st.columns(3)
            with c1:
                f_spread = st.text_input("spread_limit_pct", value=ctrl_now.get("spread_limit_pct", DEFAULTS["spread_limit_pct"]))
            with c2:
                f_max_trades = st.number_input("max_trades_per_day", value=int(float(ctrl_now.get("max_trades_per_day", DEFAULTS["max_trades_per_day"]))), step=1)
            with c3:
                f_timeout_mode = st.selectbox("timeout_mode", ["IGNORE", "EXTEND", "PARTIAL"], index=["IGNORE", "EXTEND", "PARTIAL"].index(ctrl_now.get("timeout_mode", "IGNORE")))
            st.caption("PAPER限定のテクニカルEXIT（SMAクロス）を有効化できます。resultは既存契約維持で note に理由を残します。")
            c4, c5, c6, c7, c8 = st.columns(5)
            with c4:
                f_exit_tech = st.toggle(
                    "exit_technical_enabled",
                    value=bval_str(ctrl_now.get("exit_technical_enabled", DEFAULTS["exit_technical_enabled"])),
                )
            with c5:
                f_exit_tech_only_paper = st.toggle(
                    "exit_technical_only_paper",
                    value=bval_str(ctrl_now.get("exit_technical_only_paper", DEFAULTS["exit_technical_only_paper"])),
                )
            with c6:
                f_exit_sma_fast_n = st.number_input(
                    "exit_sma_fast_n",
                    value=int(float(ctrl_now.get("exit_sma_fast_n", DEFAULTS["exit_sma_fast_n"]))),
                    step=1,
                    min_value=2,
                    max_value=500,
                )
            with c7:
                f_exit_sma_slow_n = st.number_input(
                    "exit_sma_slow_n",
                    value=int(float(ctrl_now.get("exit_sma_slow_n", DEFAULTS["exit_sma_slow_n"]))),
                    step=1,
                    min_value=3,
                    max_value=1000,
                )
            with c8:
                f_exit_tech_min_hold = st.number_input(
                    "exit_technical_min_hold_min",
                    value=int(float(ctrl_now.get("exit_technical_min_hold_min", DEFAULTS["exit_technical_min_hold_min"]))),
                    step=1,
                    min_value=0,
                    max_value=1440,
                )

            st.markdown("### 🤖 AI（表示・互換維持）")
            st.caption("AI設定は bot 側で最終判定されます。ここではCONTROL値のみ編集します。")
            d1, d2, d3, d4 = st.columns(4)
            with d1:
                f_ai_enabled = st.toggle("ai_model_enabled (ai_enabledと同期)", value=bval_str(ctrl_now.get("ai_model_enabled")))
            with d2:
                f_ai_mode = st.selectbox("ai_mode", ["OFF", "SCORE_ONLY", "VETO", "GATE"], index=["OFF", "SCORE_ONLY", "VETO", "GATE"].index(ctrl_now.get("ai_mode", "OFF")))
            with d3:
                f_ai_th = st.text_input("ai_threshold", value=ctrl_now.get("ai_threshold", DEFAULTS["ai_threshold"]))
            with d4:
                f_ai_veto = st.text_input("ai_veto_threshold", value=ctrl_now.get("ai_veto_threshold", DEFAULTS["ai_veto_threshold"]))
            d5, d6, d6b = st.columns(3)
            with d5:
                f_ai_auto_train = st.toggle("ai_auto_train_enabled", value=bval_str(ctrl_now.get("ai_auto_train_enabled", DEFAULTS["ai_auto_train_enabled"])))
            with d6:
                f_ai_lookback_days = st.number_input(
                    "ai_auto_lookback_days",
                    min_value=7,
                    max_value=365,
                    value=int(float(ctrl_now.get("ai_auto_lookback_days", DEFAULTS["ai_auto_lookback_days"]))),
                    step=1,
                )
            with d6b:
                f_ai_auto_control_sync = st.toggle(
                    "ai_auto_control_sync_enabled",
                    value=bval_str(
                        ctrl_now.get(
                            "ai_auto_control_sync_enabled",
                            DEFAULTS["ai_auto_control_sync_enabled"],
                        )
                    ),
                )
            d7, d8, d9 = st.columns(3)
            with d7:
                f_ai_train_live_only = st.toggle(
                    "ai_train_live_only",
                    value=bval_str(ctrl_now.get("ai_train_live_only", DEFAULTS["ai_train_live_only"])),
                )
            with d8:
                f_ai_train_live_boost = st.number_input(
                    "ai_train_live_boost",
                    min_value=1.0,
                    max_value=3.0,
                    value=float(ctrl_now.get("ai_train_live_boost", DEFAULTS["ai_train_live_boost"])),
                    step=0.1,
                    format="%.2f",
                )
            with d9:
                f_ai_train_recent_halflife_days = st.number_input(
                    "ai_train_recent_halflife_days",
                    min_value=1,
                    max_value=180,
                    value=int(float(ctrl_now.get("ai_train_recent_halflife_days", DEFAULTS["ai_train_recent_halflife_days"]))),
                    step=1,
                )
            d10, d11 = st.columns(2)
            with d10:
                f_ai_train_include_shadow = st.toggle(
                    "ai_train_include_shadow",
                    value=bval_str(ctrl_now.get("ai_train_include_shadow", DEFAULTS["ai_train_include_shadow"])),
                )
            with d11:
                f_ai_train_shadow_boost = st.number_input(
                    "ai_train_shadow_boost",
                    min_value=0.1,
                    max_value=3.0,
                    value=float(ctrl_now.get("ai_train_shadow_boost", DEFAULTS["ai_train_shadow_boost"])),
                    step=0.1,
                    format="%.2f",
                )
            d11b, d11c = st.columns(2)
            with d11b:
                f_ai_train_include_backtest = st.toggle(
                    "ai_train_include_backtest",
                    value=bval_str(ctrl_now.get("ai_train_include_backtest", DEFAULTS["ai_train_include_backtest"])),
                )
            with d11c:
                f_ai_train_backtest_boost = st.number_input(
                    "ai_train_backtest_boost",
                    min_value=0.05,
                    max_value=3.0,
                    value=float(ctrl_now.get("ai_train_backtest_boost", DEFAULTS["ai_train_backtest_boost"])),
                    step=0.05,
                    format="%.2f",
                )
            f_ai_train_backtest_path = st.text_input(
                "ai_train_backtest_path",
                value=ctrl_now.get("ai_train_backtest_path", DEFAULTS["ai_train_backtest_path"]),
            )
            d11d, d11e, d11f = st.columns(3)
            with d11d:
                f_ai_train_backtest_gate_enabled = st.toggle(
                    "ai_train_backtest_gate_enabled",
                    value=bval_str(
                        ctrl_now.get(
                            "ai_train_backtest_gate_enabled",
                            DEFAULTS["ai_train_backtest_gate_enabled"],
                        )
                    ),
                )
            with d11e:
                f_ai_train_backtest_gate_min_samples = st.number_input(
                    "ai_train_backtest_gate_min_samples",
                    min_value=20,
                    max_value=50000,
                    value=int(
                        float(
                            ctrl_now.get(
                                "ai_train_backtest_gate_min_samples",
                                DEFAULTS["ai_train_backtest_gate_min_samples"],
                            )
                        )
                    ),
                    step=10,
                )
            with d11f:
                f_ai_train_backtest_max_rows = st.number_input(
                    "ai_train_backtest_max_rows",
                    min_value=0,
                    max_value=200000,
                    value=int(
                        float(
                            ctrl_now.get(
                                "ai_train_backtest_max_rows",
                                DEFAULTS["ai_train_backtest_max_rows"],
                            )
                        )
                    ),
                    step=100,
                )
            d11g, d11h = st.columns(2)
            with d11g:
                f_ai_train_backtest_gate_expectancy_min = st.number_input(
                    "ai_train_backtest_gate_expectancy_min",
                    min_value=-5.0,
                    max_value=5.0,
                    value=float(
                        ctrl_now.get(
                            "ai_train_backtest_gate_expectancy_min",
                            DEFAULTS["ai_train_backtest_gate_expectancy_min"],
                        )
                    ),
                    step=0.01,
                    format="%.3f",
                )
            with d11h:
                f_ai_train_backtest_gate_pf_min = st.number_input(
                    "ai_train_backtest_gate_pf_min",
                    min_value=0.1,
                    max_value=5.0,
                    value=float(
                        ctrl_now.get(
                            "ai_train_backtest_gate_pf_min",
                            DEFAULTS["ai_train_backtest_gate_pf_min"],
                        )
                    ),
                    step=0.05,
                    format="%.2f",
                )
            st.markdown("#### 🗓️ 週次フィードバック（時間帯重み）")
            d11i, d11j = st.columns(2)
            with d11i:
                f_ai_train_weekly_feedback_enabled = st.toggle(
                    "ai_train_weekly_feedback_enabled",
                    value=bval_str(
                        ctrl_now.get(
                            "ai_train_weekly_feedback_enabled",
                            DEFAULTS["ai_train_weekly_feedback_enabled"],
                        )
                    ),
                )
            with d11j:
                f_ai_train_weekly_good_hour_boost = st.number_input(
                    "ai_train_weekly_good_hour_boost",
                    min_value=1.0,
                    max_value=3.0,
                    value=float(
                        ctrl_now.get(
                            "ai_train_weekly_good_hour_boost",
                            DEFAULTS["ai_train_weekly_good_hour_boost"],
                        )
                    ),
                    step=0.05,
                    format="%.2f",
                )
            d11m, d11n = st.columns(2)
            with d11m:
                f_ai_train_weekly_bad_hour_penalty = st.number_input(
                    "ai_train_weekly_bad_hour_penalty",
                    min_value=0.1,
                    max_value=1.0,
                    value=float(
                        ctrl_now.get(
                            "ai_train_weekly_bad_hour_penalty",
                            DEFAULTS["ai_train_weekly_bad_hour_penalty"],
                        )
                    ),
                    step=0.05,
                    format="%.2f",
                )
            with d11n:
                st.caption("good時間帯は重み↑、bad時間帯は重み↓で日次AI学習を補正します。")
            d11k, d11l = st.columns(2)
            with d11k:
                f_ai_train_weekly_good_hours = st.text_input(
                    "ai_train_weekly_good_hours",
                    value=ctrl_now.get(
                        "ai_train_weekly_good_hours",
                        DEFAULTS["ai_train_weekly_good_hours"],
                    ),
                    help="例: 10,11,14",
                )
            with d11l:
                f_ai_train_weekly_bad_hours = st.text_input(
                    "ai_train_weekly_bad_hours",
                    value=ctrl_now.get(
                        "ai_train_weekly_bad_hours",
                        DEFAULTS["ai_train_weekly_bad_hours"],
                    ),
                    help="例: 12,13,15",
                )
            st.markdown("#### 🧯 LIVEロット据え置きガード（サンプル不足時）")
            d11o, d11p, d11q = st.columns(3)
            with d11o:
                f_ai_lot_lock_enabled = st.toggle(
                    "ai_lot_lock_enabled",
                    value=bval_str(ctrl_now.get("ai_lot_lock_enabled", DEFAULTS["ai_lot_lock_enabled"])),
                )
            with d11p:
                f_ai_lot_lock_min_samples = st.number_input(
                    "ai_lot_lock_min_samples",
                    min_value=1,
                    max_value=50000,
                    value=int(float(ctrl_now.get("ai_lot_lock_min_samples", DEFAULTS["ai_lot_lock_min_samples"]))),
                    step=10,
                )
            with d11q:
                f_ai_lot_lock_max_lot = st.text_input(
                    "ai_lot_lock_max_lot",
                    value=ctrl_now.get("ai_lot_lock_max_lot", DEFAULTS["ai_lot_lock_max_lot"]),
                    help="例: 0.001（rowsが最小サンプル未満の間はこのlotを上限に固定）",
                )

            st.markdown("#### 🗓️ 月次しきい値再評価")
            d11r, d11s, d11t = st.columns(3)
            with d11r:
                f_ai_monthly_reval_enabled = st.toggle(
                    "ai_monthly_reval_enabled",
                    value=bval_str(ctrl_now.get("ai_monthly_reval_enabled", DEFAULTS["ai_monthly_reval_enabled"])),
                )
            with d11s:
                f_ai_monthly_reval_lookback_days = st.number_input(
                    "ai_monthly_reval_lookback_days",
                    min_value=30,
                    max_value=3650,
                    value=int(float(ctrl_now.get("ai_monthly_reval_lookback_days", DEFAULTS["ai_monthly_reval_lookback_days"]))),
                    step=10,
                )
            with d11t:
                f_ai_monthly_reval_min_samples = st.number_input(
                    "ai_monthly_reval_min_samples",
                    min_value=50,
                    max_value=50000,
                    value=int(float(ctrl_now.get("ai_monthly_reval_min_samples", DEFAULTS["ai_monthly_reval_min_samples"]))),
                    step=50,
                )
            d11u, d11v, d11w = st.columns(3)
            with d11u:
                f_ai_monthly_reval_pf_min = st.number_input(
                    "ai_monthly_reval_pf_min",
                    min_value=0.1,
                    max_value=5.0,
                    value=float(ctrl_now.get("ai_monthly_reval_pf_min", DEFAULTS["ai_monthly_reval_pf_min"])),
                    step=0.05,
                    format="%.2f",
                )
            with d11v:
                f_ai_monthly_reval_expectancy_min = st.number_input(
                    "ai_monthly_reval_expectancy_min",
                    min_value=-5.0,
                    max_value=5.0,
                    value=float(
                        ctrl_now.get("ai_monthly_reval_expectancy_min", DEFAULTS["ai_monthly_reval_expectancy_min"])
                    ),
                    step=0.01,
                    format="%.3f",
                )
            with d11w:
                f_ai_monthly_reval_min_improve = st.number_input(
                    "ai_monthly_reval_min_improve",
                    min_value=0.0,
                    max_value=5.0,
                    value=float(ctrl_now.get("ai_monthly_reval_min_improve", DEFAULTS["ai_monthly_reval_min_improve"])),
                    step=0.001,
                    format="%.3f",
                )
            d12, d13, d14, d15 = st.columns(4)
            with d12:
                f_ai_gate_enabled = st.toggle(
                    "ai_gate_enabled",
                    value=bval_str(ctrl_now.get("ai_gate_enabled", DEFAULTS["ai_gate_enabled"])),
                )
            with d13:
                f_ai_gate_min_samples = st.number_input(
                    "ai_gate_min_samples",
                    min_value=10,
                    max_value=2000,
                    value=int(float(ctrl_now.get("ai_gate_min_samples", DEFAULTS["ai_gate_min_samples"]))),
                    step=5,
                )
            with d14:
                f_ai_gate_expectancy_min = st.number_input(
                    "ai_gate_expectancy_min",
                    min_value=-5.0,
                    max_value=5.0,
                    value=float(ctrl_now.get("ai_gate_expectancy_min", DEFAULTS["ai_gate_expectancy_min"])),
                    step=0.01,
                    format="%.3f",
                )
            with d15:
                f_ai_gate_pf_min = st.number_input(
                    "ai_gate_pf_min",
                    min_value=0.1,
                    max_value=5.0,
                    value=float(ctrl_now.get("ai_gate_pf_min", DEFAULTS["ai_gate_pf_min"])),
                    step=0.05,
                    format="%.2f",
                )
            d16, d17, d18, d19 = st.columns(4)
            with d16:
                f_ai_auto_rollback_enabled = st.toggle(
                    "ai_auto_rollback_enabled",
                    value=bval_str(ctrl_now.get("ai_auto_rollback_enabled", DEFAULTS["ai_auto_rollback_enabled"])),
                )
            with d17:
                f_ai_auto_rollback_lookback_days = st.number_input(
                    "ai_auto_rollback_lookback_days",
                    min_value=7,
                    max_value=365,
                    value=int(float(ctrl_now.get("ai_auto_rollback_lookback_days", DEFAULTS["ai_auto_rollback_lookback_days"]))),
                    step=1,
                )
            with d18:
                f_ai_auto_rollback_pf_floor = st.number_input(
                    "ai_auto_rollback_pf_floor",
                    min_value=0.1,
                    max_value=5.0,
                    value=float(ctrl_now.get("ai_auto_rollback_pf_floor", DEFAULTS["ai_auto_rollback_pf_floor"])),
                    step=0.05,
                    format="%.2f",
                )
            with d19:
                f_ai_auto_rollback_expectancy_floor = st.number_input(
                    "ai_auto_rollback_expectancy_floor",
                    min_value=-5.0,
                    max_value=5.0,
                    value=float(ctrl_now.get("ai_auto_rollback_expectancy_floor", DEFAULTS["ai_auto_rollback_expectancy_floor"])),
                    step=0.01,
                    format="%.3f",
                )
            st.caption("ai_auto_train_enabled=1 で bot 起動時に日次1回だけ閾値自動更新を試行します。Shadowは boost 0.5〜0.8、BACKTESTは 0.2〜0.4 + backtest_gate_enabled=1 から開始が安全です。")

            st.markdown("### 🚀 LIVE設定")
            st.caption("SPOTは BTC_JPY、Lightning/CFDは FX_BTC_JPY を基本に、paper_mode=0 + live_enabled=1 で段階導入してください。")
            e1, e2, e3, e4, e5 = st.columns(5)
            rollout_vals = ["AUTO", "PAPER", "CANARY", "LIVE"]
            rollout_now = ctrl_now.get("rollout_mode", "AUTO")
            with e1:
                f_rollout = st.selectbox("rollout_mode", rollout_vals, index=rollout_vals.index(rollout_now) if rollout_now in rollout_vals else 0)
            with e2:
                f_stage_paper_days = st.number_input("stage_paper_days", value=int(float(ctrl_now.get("stage_paper_days", DEFAULTS["stage_paper_days"]))), step=1, min_value=0)
            with e3:
                f_stage_canary_days = st.number_input("stage_canary_days", value=int(float(ctrl_now.get("stage_canary_days", DEFAULTS["stage_canary_days"]))), step=1, min_value=0)
            with e4:
                f_canary_lot = st.text_input("canary_lot", value=ctrl_now.get("canary_lot", DEFAULTS["canary_lot"]))
            with e5:
                f_exchange_name = st.selectbox(
                    "exchange_name",
                    ["bitflyer", "binance"],
                    index=0 if str(ctrl_now.get("exchange_name", DEFAULTS["exchange_name"])).strip().lower() != "binance" else 1,
                )

            mt_for_lev = str(ctrl_now.get("market_type", "SPOT")).strip().upper()
            fx_lev_ui_max = LIVE_START_MAX_FX_LEVERAGE if mt_for_lev in ("FX", "CFD", "LIGHTNING") else 20.0
            f1, f2, f3, f4, f5, f6 = st.columns(6)
            with f1:
                f_daily_loss = st.text_input("daily_loss_limit_pct", value=ctrl_now.get("daily_loss_limit_pct", DEFAULTS["daily_loss_limit_pct"]))
            with f2:
                f_timeout_sec = st.number_input("limit_order_timeout_sec", value=int(float(ctrl_now.get("limit_order_timeout_sec", DEFAULTS["limit_order_timeout_sec"]))), step=1, min_value=5)
            with f3:
                f_offset_ticks = st.number_input("limit_price_offset_ticks", value=int(float(ctrl_now.get("limit_price_offset_ticks", DEFAULTS["limit_price_offset_ticks"]))), step=1, min_value=0)
            with f4:
                f_fx_leverage = st.number_input(
                    "fx_leverage",
                    value=float(ctrl_now.get("fx_leverage", DEFAULTS["fx_leverage"])),
                    step=0.1,
                    min_value=0.1,
                    max_value=float(fx_lev_ui_max),
                    format="%.2f",
                )
            with f5:
                f_market_type = st.selectbox("market_type", ["SPOT", "FX", "OTHER"], index=["SPOT", "FX", "OTHER"].index(ctrl_now.get("market_type", "SPOT")) if ctrl_now.get("market_type", "SPOT") in ["SPOT", "FX", "OTHER"] else 0)
            with f6:
                f_streak_stop_enabled = st.toggle(
                    "streak_stop_enabled",
                    value=bval_str(ctrl_now.get("streak_stop_enabled", DEFAULTS["streak_stop_enabled"])),
                )
            if mt_for_lev in ("FX", "CFD", "LIGHTNING"):
                st.caption(f"bitFlyer個人口座の上限準拠: FXレバレッジは {LIVE_START_MAX_FX_LEVERAGE:.2f} 以下で運用してください。")

            g1, g2, g3, g4 = st.columns(4)
            with g1:
                f_product_code = st.text_input("product_code", value=ctrl_now.get("product_code", DEFAULTS["product_code"]))
            with g2:
                f_fx_collateral_ratio = st.number_input(
                    "fx_collateral_use_ratio",
                    value=float(ctrl_now.get("fx_collateral_use_ratio", DEFAULTS["fx_collateral_use_ratio"])),
                    step=0.05,
                    min_value=0.05,
                    max_value=1.0,
                    format="%.2f",
                )
            with g3:
                f_keychain_service = st.text_input("keychain_service", value=ctrl_now.get("keychain_service", DEFAULTS["keychain_service"]))
            with g4:
                f_streak_stop_max_losses = st.number_input(
                    "streak_stop_max_losses",
                    value=int(float(ctrl_now.get("streak_stop_max_losses", DEFAULTS["streak_stop_max_losses"]))),
                    step=1,
                    min_value=1,
                    max_value=50,
                )

            h1, h2 = st.columns(2)
            with h1:
                f_keychain_key = st.text_input("keychain_account_key", value=ctrl_now.get("keychain_account_key", DEFAULTS["keychain_account_key"]))
            with h2:
                f_keychain_secret = st.text_input("keychain_account_secret", value=ctrl_now.get("keychain_account_secret", DEFAULTS["keychain_account_secret"]))

            # Extra keys view/edit
            st.markdown("### 🧩 extra（DEFAULTS外のキー）")
            extra_keys = sorted([k for k in ctrl_now.keys() if k not in DEFAULTS])
            st.caption("SPEC: 未知キーは消さない。ここで編集した内容も保存されます。")
            extra_json = {k: ctrl_now.get(k, "") for k in extra_keys}
            extra_text = st.text_area(
                "extra (JSON形式で編集可)",
                value=json.dumps(extra_json, ensure_ascii=False, indent=2),
                height=220,
            )

            submitted = st.form_submit_button("💾 保存", width="stretch")
            if submitted:
                upd = dict(ctrl_now)  # preserve unknown keys
                upd["today_on"] = "1" if f_today else "0"
                upd["trade_enabled"] = "1" if f_trade else "0"
                upd["paper_mode"] = "1" if f_paper else "0"
                upd["live_enabled"] = "1" if f_live else "0"
                upd["safety_hard_block"] = "1" if f_safety else "0"
                upd["observe_only"] = "1" if f_observe else "0"

                upd["tp_buy_pct"] = str(f_tp_buy).strip()
                upd["tp_sell_pct"] = str(f_tp_sell).strip()
                upd["sl_pct"] = str(f_sl).strip()
                upd["lot"] = str(f_lot).strip()
                upd["win_min"] = str(f_win).strip()

                upd["spread_limit_pct"] = str(f_spread).strip()
                upd["max_trades_per_day"] = str(int(f_max_trades))
                upd["timeout_mode"] = str(f_timeout_mode).strip()
                upd["exit_technical_enabled"] = "1" if f_exit_tech else "0"
                upd["exit_technical_only_paper"] = "1" if f_exit_tech_only_paper else "0"
                upd["exit_sma_fast_n"] = str(int(f_exit_sma_fast_n))
                upd["exit_sma_slow_n"] = str(int(f_exit_sma_slow_n))
                upd["exit_technical_min_hold_min"] = str(int(f_exit_tech_min_hold))

                upd["ai_model_enabled"] = "1" if f_ai_enabled else "0"
                upd["ai_mode"] = str(f_ai_mode).strip()
                upd["ai_threshold"] = str(f_ai_th).strip()
                upd["ai_veto_threshold"] = str(f_ai_veto).strip()
                upd["ai_auto_train_enabled"] = "1" if f_ai_auto_train else "0"
                upd["ai_auto_control_sync_enabled"] = "1" if f_ai_auto_control_sync else "0"
                upd["ai_auto_lookback_days"] = str(int(f_ai_lookback_days))
                upd["ai_train_live_only"] = "1" if f_ai_train_live_only else "0"
                upd["ai_train_live_boost"] = f"{float(f_ai_train_live_boost):.2f}"
                upd["ai_train_include_shadow"] = "1" if f_ai_train_include_shadow else "0"
                upd["ai_train_shadow_boost"] = f"{float(f_ai_train_shadow_boost):.2f}"
                upd["ai_train_include_backtest"] = "1" if f_ai_train_include_backtest else "0"
                upd["ai_train_backtest_boost"] = f"{float(f_ai_train_backtest_boost):.2f}"
                upd["ai_train_backtest_path"] = str(f_ai_train_backtest_path).strip()
                upd["ai_train_backtest_gate_enabled"] = "1" if f_ai_train_backtest_gate_enabled else "0"
                upd["ai_train_backtest_gate_min_samples"] = str(int(f_ai_train_backtest_gate_min_samples))
                upd["ai_train_backtest_gate_expectancy_min"] = f"{float(f_ai_train_backtest_gate_expectancy_min):.3f}"
                upd["ai_train_backtest_gate_pf_min"] = f"{float(f_ai_train_backtest_gate_pf_min):.2f}"
                upd["ai_train_backtest_max_rows"] = str(int(f_ai_train_backtest_max_rows))
                upd["ai_train_recent_halflife_days"] = str(int(f_ai_train_recent_halflife_days))
                upd["ai_train_weekly_feedback_enabled"] = "1" if f_ai_train_weekly_feedback_enabled else "0"
                upd["ai_train_weekly_good_hours"] = str(f_ai_train_weekly_good_hours).strip()
                upd["ai_train_weekly_bad_hours"] = str(f_ai_train_weekly_bad_hours).strip()
                upd["ai_train_weekly_good_hour_boost"] = f"{float(f_ai_train_weekly_good_hour_boost):.2f}"
                upd["ai_train_weekly_bad_hour_penalty"] = f"{float(f_ai_train_weekly_bad_hour_penalty):.2f}"
                upd["ai_lot_lock_enabled"] = "1" if f_ai_lot_lock_enabled else "0"
                upd["ai_lot_lock_min_samples"] = str(int(f_ai_lot_lock_min_samples))
                upd["ai_lot_lock_max_lot"] = str(f_ai_lot_lock_max_lot).strip()
                upd["ai_monthly_reval_enabled"] = "1" if f_ai_monthly_reval_enabled else "0"
                upd["ai_monthly_reval_lookback_days"] = str(int(f_ai_monthly_reval_lookback_days))
                upd["ai_monthly_reval_min_samples"] = str(int(f_ai_monthly_reval_min_samples))
                upd["ai_monthly_reval_pf_min"] = f"{float(f_ai_monthly_reval_pf_min):.2f}"
                upd["ai_monthly_reval_expectancy_min"] = f"{float(f_ai_monthly_reval_expectancy_min):.3f}"
                upd["ai_monthly_reval_min_improve"] = f"{float(f_ai_monthly_reval_min_improve):.3f}"
                upd["ai_gate_enabled"] = "1" if f_ai_gate_enabled else "0"
                upd["ai_gate_min_samples"] = str(int(f_ai_gate_min_samples))
                upd["ai_gate_expectancy_min"] = f"{float(f_ai_gate_expectancy_min):.3f}"
                upd["ai_gate_pf_min"] = f"{float(f_ai_gate_pf_min):.2f}"
                upd["ai_auto_rollback_enabled"] = "1" if f_ai_auto_rollback_enabled else "0"
                upd["ai_auto_rollback_lookback_days"] = str(int(f_ai_auto_rollback_lookback_days))
                upd["ai_auto_rollback_pf_floor"] = f"{float(f_ai_auto_rollback_pf_floor):.2f}"
                upd["ai_auto_rollback_expectancy_floor"] = f"{float(f_ai_auto_rollback_expectancy_floor):.3f}"

                upd["rollout_mode"] = str(f_rollout).strip()
                upd["exchange_name"] = str(f_exchange_name).strip().lower()
                upd["stage_paper_days"] = str(int(f_stage_paper_days))
                upd["stage_canary_days"] = str(int(f_stage_canary_days))
                upd["canary_lot"] = str(f_canary_lot).strip()
                upd["daily_loss_limit_pct"] = str(f_daily_loss).strip()
                upd["streak_stop_enabled"] = "1" if f_streak_stop_enabled else "0"
                upd["streak_stop_max_losses"] = str(int(f_streak_stop_max_losses))
                upd["limit_order_timeout_sec"] = str(int(f_timeout_sec))
                upd["limit_price_offset_ticks"] = str(int(f_offset_ticks))
                upd["fx_leverage"] = f"{float(f_fx_leverage):.2f}"
                upd["fx_collateral_use_ratio"] = f"{float(f_fx_collateral_ratio):.2f}"
                upd["product_code"] = str(f_product_code).strip()
                upd["market_type"] = str(f_market_type).strip()
                upd["keychain_service"] = str(f_keychain_service).strip()
                upd["keychain_account_key"] = str(f_keychain_key).strip()
                upd["keychain_account_secret"] = str(f_keychain_secret).strip()

                # merge extra edits
                try:
                    parsed = json.loads(extra_text) if extra_text.strip() else {}
                    if isinstance(parsed, dict):
                        for k, v in parsed.items():
                            if k in DEFAULTS:
                                continue
                            upd[str(k)] = str(v)
                except Exception:
                    st.error("extraのJSONが壊れています（保存を中止しました）。")
                    st.stop()

                # S-2: Re-read CONTROL.csv just before writing to avoid overwriting
                # bot's auto-tuned values (e.g. ai_threshold by daily_ai_autotune).
                # Apply only the keys the user actually changed vs. the form baseline.
                try:
                    fresh_ctrl, _ = read_control_kv_csv(control_path)
                    user_changed_keys = {
                        k for k in upd if str(ctrl_now.get(k, "")) != str(upd.get(k, ""))
                    }
                    merged = dict(fresh_ctrl)
                    for k in user_changed_keys:
                        merged[k] = upd[k]
                    for k, v in upd.items():
                        if k not in merged:
                            merged[k] = v
                    upd = merged
                except Exception:
                    pass  # non-fatal: proceed with upd as-is

                val_errors, val_warns = _validate_control_values(upd)
                if val_errors:
                    st.error("保存を中止しました。修正必須の項目があります。")
                    for x in val_errors:
                        st.write(f"- {x}")
                    st.stop()

                ok, msg = write_control_kv_csv_with_log(
                    main_dir=main_dir,
                    path=control_path,
                    before_ctrl=ctrl_now,
                    after_ctrl=upd,
                    author=change_actor,
                    reason="settings:form_save",
                )
                if ok:
                    st.success(T("save_success"))
                    changed_cnt = len(_control_changed_items(ctrl_now, upd))
                    if changed_cnt > 0:
                        st.caption(f"変更履歴へ自動記録: {changed_cnt} 件")
                    else:
                        st.caption("差分なし（変更履歴への追記はスキップ）")
                    if val_warns:
                        st.warning("保存しましたが、注意事項があります。")
                        for x in val_warns[:6]:
                            st.write(f"- {x}")
                    time.sleep(0.8)
                    st.rerun()
                else:
                    st.error(f"{T('save_error')}: {msg}")

        # --- CONTROL.csv 変更履歴 ---
        st.markdown("---")
        st.markdown("### 📋 CONTROL変更履歴（直近20件）")
        _chg_log = _read_dashboard_change_log(main_dir, max_rows=300)
        _config_changes = [e for e in _chg_log if e.get("type") == "CONFIG"][:20]
        if not _config_changes:
            st.caption("変更履歴がありません。")
        else:
            for _entry in _config_changes:
                _ts = str(_entry.get("ts", "-"))
                _author = str(_entry.get("author", "-"))
                _summary = str(_entry.get("summary", "-"))
                _keys = ", ".join(_entry.get("changed_keys") or [])
                _preview = _entry.get("diff_preview") or []
                _label = f"{_ts}  |  {_author}  |  {_summary}"
                with st.expander(_label, expanded=False):
                    if _keys:
                        st.caption(f"変更キー: {_keys}")
                    if _preview and isinstance(_preview, list):
                        try:
                            df_diff = pd.DataFrame(_preview)
                            if not df_diff.empty:
                                st.dataframe(df_diff, hide_index=True)
                        except Exception:
                            st.json(_preview)

    # =========================================================
    # TAB: Analytics (buttons only; spec says dashboard has no bot logic)
    # =========================================================
    with tabs[tab_index["analytics"]]:
        st.subheader("成績・分析（生成は daily_report が正）")
        st.caption("手順: 1) 対象日選択 → 2) daily_report/audit実行 → 3) 下の可視化確認。")

        if not logs_dir:
            st.warning("logs/ が見つかりません。")
        else:
            days = list_log_days(logs_dir)
            period_options: List[Tuple[str, str]] = [
                ("manual", "手動"),
                ("last_7d", "直近1週間（7日）"),
                ("prev_7d", "前週（その前7日）"),
                ("last_30d", "直近1か月（30日）"),
                ("prev_30d", "前月（その前30日）"),
                ("last_365d", "直近1年（365日）"),
                ("prev_365d", "前年（その前365日）"),
            ]
            period_label_to_key = {label: key for key, label in period_options}
            period_labels = [label for _, label in period_options]

            pick_state_key = "analytics_pick_days"
            preset_state_key = "analytics_period_preset"
            if pick_state_key not in st.session_state:
                st.session_state[pick_state_key] = days[: min(3, len(days))]
            # drop stale days when logs rotate
            st.session_state[pick_state_key] = [d for d in st.session_state[pick_state_key] if d in days]
            if (not st.session_state[pick_state_key]) and days:
                st.session_state[pick_state_key] = days[: min(3, len(days))]

            pf1, pf2, pf3 = st.columns([2, 1, 1])
            with pf1:
                selected_period_label = st.selectbox(
                    "期間プリセット",
                    period_labels,
                    index=0,
                    key=preset_state_key,
                    help="手動選択に加えて、直近/前週/前月/前年をワンタップで適用できます。",
                )
            with pf2:
                if st.button("プリセット適用", width="stretch"):
                    pkey = period_label_to_key.get(selected_period_label, "manual")
                    if pkey != "manual":
                        preset_days = _select_days_by_period(days, pkey)
                        if preset_days:
                            st.session_state[pick_state_key] = preset_days
                        else:
                            st.warning("この期間に該当するログ日がありません。")
            with pf3:
                if st.button("最新3日に戻す", width="stretch"):
                    st.session_state[pick_state_key] = days[: min(3, len(days))]

            pick = st.multiselect(
                "対象日(YYYYMMDD)",
                days,
                default=st.session_state[pick_state_key],
                key=pick_state_key,
            )
            if pick:
                pick_sorted = sorted(pick)
                st.caption(f"選択期間: {pick_sorted[0]} 〜 {pick_sorted[-1]}（{len(pick)}日）")
            token = _pick_days_token(pick)
            wr_start8 = min(pick) if pick else ""
            wr_end8 = max(pick) if pick else ""
            weekly_out_dir = main_dir / "weekly_report_out"
            weekly_json_path = (
                weekly_out_dir / f"weekly_report_{wr_start8}_{wr_end8}.json"
                if (wr_start8 and wr_end8)
                else None
            )

            cols = st.columns(5)
            with cols[0]:
                if st.button("▶ daily_report 実行（監査JSON生成）", type="primary", width="stretch"):
                    daily_py = main_dir / "daily_report.py"
                    if not daily_py.exists():
                        st.error("daily_report.py が見つかりません。")
                    elif not token:
                        st.error("対象日を選択してください。")
                    else:
                        out_dir.mkdir(parents=True, exist_ok=True)
                        cmd = [sys.executable, str(daily_py), token, "--out-dir", str(out_dir)]
                        rc, out = _run_subprocess(cmd, cwd=main_dir)
                        st.code(" ".join(cmd))
                        st.code(out)
                        if rc == 0:
                            st.success("完了（JSONを生成しました）。pos_id・監査(JSON)タブへ。")
                        else:
                            st.error(f"失敗 rc={rc}")

            with cols[1]:
                if st.button("▶ audit 実行（存在する場合）", width="stretch"):
                    audit_py = main_dir / "audit.py"
                    if not audit_py.exists():
                        st.error("audit.py が見つかりません（未導入ならOK）。")
                    elif not token:
                        st.error("対象日を選択してください。")
                    else:
                        # audit.py expects --day or --start/--end flags; token is like "YYYYMMDD" or "YYYYMMDD-YYYYMMDD"
                        if isinstance(token, str) and "-" in token:
                            start, end = token.split("-", 1)
                            cmd = [sys.executable, str(audit_py), "--start", start, "--end", end, "--out-dir", str(out_dir)]
                        else:
                            cmd = [sys.executable, str(audit_py), "--day", token, "--out-dir", str(out_dir)]
                        rc, out = _run_subprocess(cmd, cwd=main_dir)
                        st.code(" ".join(cmd))
                        st.code(out)
                        if rc == 0:
                            st.success("完了。pos_id・監査(JSON)タブへ。")
                        else:
                            st.error(f"失敗 rc={rc}")
            with cols[2]:
                if st.button("▶ ci_check 実行", width="stretch"):
                    ci_py = main_dir / "ci_check.py"
                    if not ci_py.exists():
                        st.error("ci_check.py が見つかりません。")
                    else:
                        day_arg = days[0] if days else ""
                        cmd = [sys.executable, str(ci_py)]
                        if day_arg:
                            cmd.append(day_arg)
                        rc, out = _run_subprocess(cmd, cwd=main_dir)
                        st.code(" ".join(cmd))
                        st.code(out)
                        if rc == 0:
                            st.success("完了。")
                        else:
                            st.error(f"失敗 rc={rc}")
            with cols[3]:
                if st.button("▶ live_preflight 実行", width="stretch"):
                    preflight_py = main_dir / "tools" / "live_preflight.py"
                    if not preflight_py.exists():
                        st.error("tools/live_preflight.py が見つかりません。")
                    else:
                        cmd = [sys.executable, str(preflight_py)]
                        rc, out = _run_subprocess(cmd, cwd=main_dir)
                        st.code(" ".join(cmd))
                        st.code(out)
                        if rc == 0:
                            st.success("完了。")
                        else:
                            st.error(f"失敗 rc={rc}")
            with cols[4]:
                if st.button("▶ weekly_report 実行", width="stretch"):
                    wr_py = main_dir / "weekly_report.py"
                    if not wr_py.exists():
                        st.error("weekly_report.py が見つかりません。")
                    elif not token:
                        st.error("対象日を選択してください。")
                    else:
                        weekly_out_dir.mkdir(parents=True, exist_ok=True)
                        cmd = [sys.executable, str(wr_py), token, "--out-dir", str(weekly_out_dir)]
                        rc, out = _run_subprocess(cmd, cwd=main_dir)
                        st.code(" ".join(cmd))
                        st.code(out)
                        if rc == 0:
                            st.success("完了（週次レビューJSONを生成しました）。")
                        else:
                            st.error(f"失敗 rc={rc}")

            st.divider()
            st.markdown("### 📈 可視化（ログ由来の推定）")
            st.caption("entry/exit の位置、累積推移、勝敗内訳をこのタブ内で確認できます（すべて推定・fee未加味）。")
            with st.expander("📘 成績タブの見方（運用ガイド）", expanded=False):
                st.markdown(
                    """
1. `ローソク足 + ENTRY/EXIT` で「どこで入ってどこで出たか」を確認
2. `期間プリセット`（直近1週間/前週/直近1か月/前月/直近1年/前年）で比較したい区間を選択
3. `累積損益カーブ` で右肩下がりが続いていないか確認
4. `損益内訳` で `総利益` と `総損失`、`Payoff` を確認
5. `日次サマリー` で日ごとの崩れを確認
6. 具体的な要因は `トレード履歴` / `pos_id・監査` で深掘り
"""
                )
            pick_for_render = list(pick)
            if perf_mode == "lite" and pick_for_render:
                analytics_render_key = ",".join(_normalize_day_list(sorted(pick_for_render)))
                analytics_render_token = (
                    f"{analytics_render_key}|{dir_cache_token(logs_dir)}"
                    if logs_dir
                    else analytics_render_key
                )
                can_render_heavy = _heavy_render_gate(
                    section_key="analytics",
                    render_token=analytics_render_token,
                    perf_mode=perf_mode,
                    info_text="軽量モード: 重い可視化は手動実行です。",
                    run_label="可視化を実行",
                )
                if not can_render_heavy:
                    pick_for_render = []

            if not pick_for_render:
                if pick and perf_mode == "lite":
                    st.caption("対象日は選択済みです。軽量モードのため、上の「可視化を実行」を押すまで重い描画をスキップしています。")
                else:
                    st.info("可視化するには対象日を1日以上選択してください。")
            else:
                raw_rows, df_pos, price_df, event_df = _analytics_dataset_for_days(
                    logs_dir, pick_for_render
                )
                if df_pos.empty:
                    st.info("可視化対象の pos_id データがありません。")
                else:
                    df_closed = df_pos[(df_pos["status"] == "CLOSED") & (df_pos["ret_pct_est"].notna())].copy()
                    if "time_dt" in df_closed.columns:
                        df_closed["time_dt"] = pd.to_datetime(df_closed["time_dt"], errors="coerce")
                        df_closed = df_closed.sort_values("time_dt")
                    ret_s_for_curve = pd.to_numeric(df_closed.get("ret_pct_est"), errors="coerce").fillna(0.0)
                    pnl_s_for_curve = pd.to_numeric(df_closed.get("pnl_est"), errors="coerce").fillna(0.0)
                    df_closed["cum_ret_pct"] = ret_s_for_curve.cumsum()
                    df_closed["cum_pnl_est"] = pnl_s_for_curve.cumsum()
                    def _perf_metrics_from_closed(xdf: pd.DataFrame) -> Dict[str, float]:
                        if xdf is None or xdf.empty:
                            return {
                                "closed": 0,
                                "wins": 0,
                                "losses": 0,
                                "win_rate": 0.0,
                                "ret_sum": 0.0,
                                "pnl_sum": 0.0,
                                "gross_profit": 0.0,
                                "gross_loss": 0.0,
                                "pf": 0.0,
                                "payoff": 0.0,
                                "expectancy": 0.0,
                                "mdd_pnl": 0.0,
                                "mdd_ret": 0.0,
                                "max_ls": 0,
                            }
                        ret_s = pd.to_numeric(xdf.get("ret_pct_est"), errors="coerce").fillna(0.0)
                        pnl_s = pd.to_numeric(xdf.get("pnl_est"), errors="coerce").fillna(0.0)
                        wins_x = int((ret_s > 0).sum())
                        losses_x = int((ret_s < 0).sum())
                        total_x = int(len(xdf))
                        gp_x = float(pnl_s[pnl_s > 0].sum()) if total_x > 0 else 0.0
                        gl_x = float(pnl_s[pnl_s < 0].sum()) if total_x > 0 else 0.0
                        avg_win_x = float(pnl_s[pnl_s > 0].mean()) if wins_x > 0 else 0.0
                        avg_loss_abs_x = abs(float(pnl_s[pnl_s < 0].mean())) if losses_x > 0 else 0.0
                        cum_pnl_x = pnl_s.cumsum()
                        cum_ret_x = ret_s.cumsum()
                        return {
                            "closed": total_x,
                            "wins": wins_x,
                            "losses": losses_x,
                            "win_rate": (wins_x / total_x * 100.0) if total_x > 0 else 0.0,
                            "ret_sum": float(ret_s.sum()) if total_x > 0 else 0.0,
                            "pnl_sum": float(pnl_s.sum()) if total_x > 0 else 0.0,
                            "gross_profit": gp_x,
                            "gross_loss": gl_x,
                            "pf": (gp_x / abs(gl_x)) if gl_x < 0 else 0.0,
                            "payoff": (avg_win_x / avg_loss_abs_x) if avg_loss_abs_x > 0 else 0.0,
                            "expectancy": (float(pnl_s.sum()) / float(total_x)) if total_x > 0 else 0.0,
                            "mdd_pnl": calc_max_drawdown(cum_pnl_x),
                            "mdd_ret": calc_max_drawdown(cum_ret_x),
                            "max_ls": calc_max_losing_streak(pnl_s),
                        }

                    perf_all = _perf_metrics_from_closed(df_closed)
                    mode_df = df_closed.copy()
                    if "exec_mode" not in mode_df.columns:
                        mode_df["exec_mode"] = "PAPER"
                    mode_df["exec_mode"] = mode_df["exec_mode"].astype(str).str.upper().replace({"": "PAPER"})
                    mode_df.loc[~mode_df["exec_mode"].isin(["PAPER", "LIVE"]), "exec_mode"] = "PAPER"
                    wins = int(perf_all["wins"])
                    losses = int(perf_all["losses"])
                    total = int(perf_all["closed"])
                    win_rate = float(perf_all["win_rate"])
                    total_ret = float(perf_all["ret_sum"])
                    total_pnl = float(perf_all["pnl_sum"])
                    gross_profit = float(perf_all["gross_profit"])
                    gross_loss = float(perf_all["gross_loss"])
                    payoff = float(perf_all["payoff"])
                    pf = float(perf_all["pf"])
                    expectancy = float(perf_all["expectancy"])
                    mdd_pnl = float(perf_all["mdd_pnl"])
                    mdd_ret = float(perf_all["mdd_ret"])
                    max_losing_streak = int(perf_all["max_ls"])

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("クローズ数", f"{total}")
                    m2.metric("勝率", f"{win_rate:.1f}%")
                    m3.metric("累積ret_pct(推定)", f"{total_ret:.3f}%")
                    m4.metric("累積PnL(推定)", f"{total_pnl:,.4f}")
                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric("総利益(推定)", f"{gross_profit:,.4f}")
                    k2.metric("総損失(推定)", f"{gross_loss:,.4f}")
                    k3.metric("Payoff", f"{payoff:.3f}")
                    k4.metric("Profit Factor", f"{pf:.3f}")
                    q1, q2, q3, q4 = st.columns(4)
                    q1.metric("Expectancy(推定)", f"{expectancy:,.4f}")
                    q2.metric("Max Drawdown(PnL)", f"{mdd_pnl:,.4f}")
                    q3.metric("Max Drawdown(ret_pct)", f"{mdd_ret:,.3f}%")
                    q4.metric("最大連敗", f"{max_losing_streak}")

                    st.markdown("### 🗓️ 週次レビュー（weekly_report）")
                    if weekly_json_path and weekly_json_path.exists():
                        wr_obj = load_json(weekly_json_path)
                        if isinstance(wr_obj, dict):
                            wr = wr_obj.get("weekly_review", {}) if isinstance(wr_obj.get("weekly_review"), dict) else {}
                            af = wr_obj.get("ai_feedback", {}) if isinstance(wr_obj.get("ai_feedback"), dict) else {}
                            if wr:
                                wr1, wr2, wr3, wr4, wr5 = st.columns(5)
                                wr1.metric("週クローズ", str(wr.get("closed_n", 0)))
                                wr2.metric("週勝率", f"{safe_float(wr.get('win_rate_pct')) or 0.0:.1f}%")
                                wr3.metric("週累積ret", f"{safe_float(wr.get('ret_sum_pct')) or 0.0:.3f}%")
                                wr4.metric("週PF", f"{safe_float(wr.get('profit_factor')) or 0.0:.3f}")
                                wr5.metric("平均保有(分)", f"{safe_float(wr.get('avg_hold_min')) or 0.0:.1f}")

                                c_wd, c_hr = st.columns(2)
                                by_wd = wr.get("by_weekday", {}) if isinstance(wr.get("by_weekday"), dict) else {}
                                by_hr = wr.get("by_hour", {}) if isinstance(wr.get("by_hour"), dict) else {}
                                with c_wd:
                                    wd_rows: List[Dict[str, Any]] = []
                                    for k in ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]:
                                        v = by_wd.get(k, {}) if isinstance(by_wd.get(k), dict) else {}
                                        wd_rows.append(
                                            {
                                                "weekday": k,
                                                "closed_n": int(v.get("closed_n", 0)),
                                                "win_rate_pct": round(safe_float(v.get("win_rate_pct")) or 0.0, 3),
                                                "avg_ret_pct": round(safe_float(v.get("avg_ret_pct")) or 0.0, 6),
                                            }
                                        )
                                    st.dataframe(pd.DataFrame(wd_rows), width="stretch", hide_index=True)
                                with c_hr:
                                    hr_rows: List[Dict[str, Any]] = []
                                    for h in range(24):
                                        v = by_hr.get(str(h), {}) if isinstance(by_hr.get(str(h)), dict) else {}
                                        hr_rows.append(
                                            {
                                                "hour": str(h).zfill(2),
                                                "closed_n": int(v.get("closed_n", 0)),
                                                "win_rate_pct": round(safe_float(v.get("win_rate_pct")) or 0.0, 3),
                                                "avg_ret_pct": round(safe_float(v.get("avg_ret_pct")) or 0.0, 6),
                                            }
                                        )
                                    hr_df = pd.DataFrame(hr_rows).sort_values("hour")
                                    st.dataframe(hr_df, width="stretch", hide_index=True)

                            if af:
                                st.caption(f"AI学習提案: {str(af.get('summary', '-'))}")
                                sug = af.get("suggested_control_updates", {}) if isinstance(af.get("suggested_control_updates"), dict) else {}
                                if sug:
                                    st.code(json.dumps(sug, ensure_ascii=False, indent=2))
                                    apply_key = f"analytics_apply_weekly_ai_{wr_start8}_{wr_end8}"
                                    if st.button("🧠 AI学習設定へ提案を反映", key=apply_key, width="stretch"):
                                        cur_ctrl, _ = read_control_kv_csv(control_path)
                                        upd_ctrl = dict(cur_ctrl)
                                        for k, v in sug.items():
                                            upd_ctrl[str(k)] = str(v)
                                        before_state_obj = load_json(state_path) if state_path.exists() else {}
                                        if not isinstance(before_state_obj, dict):
                                            before_state_obj = {}
                                        compare_snapshot = {
                                            "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                            "range_start8": _safe_str(wr_start8),
                                            "range_end8": _safe_str(wr_end8),
                                            "summary": _safe_str(af.get("summary", "")),
                                            "suggested_control_updates": {str(k): str(v) for k, v in sug.items()},
                                            "before_last_day": _safe_str(before_state_obj.get("_ai_auto_train_day", "")),
                                            "before_ai_auto": _ai_compare_extract(before_state_obj.get("_ai_auto_train")),
                                        }
                                        _val_errs, _ = _validate_control_values(upd_ctrl)
                                        if _val_errs:
                                            st.error("AI提案値に不正な値が含まれています。反映をスキップしました。")
                                            for _e in _val_errs[:5]:
                                                st.write(f"- {_e}")
                                            st.stop()
                                        ok, msg = write_control_kv_csv_with_log(
                                            main_dir=main_dir,
                                            path=control_path,
                                            before_ctrl=cur_ctrl,
                                            after_ctrl=upd_ctrl,
                                            author=change_actor,
                                            reason="analytics:apply_weekly_ai_feedback",
                                        )
                                        if ok:
                                            compare_msg = ""
                                            try:
                                                cur_state_obj = load_json(state_path) if state_path.exists() else {}
                                                if not isinstance(cur_state_obj, dict):
                                                    cur_state_obj = {}
                                                cur_state_obj[WEEKLY_AI_COMPARE_STATE_KEY] = compare_snapshot
                                                _write_json_dict(state_path, cur_state_obj)
                                            except Exception as e:
                                                compare_msg = f"（比較スナップショット保存失敗: {e}）"
                                            st.success("週次AI提案をCONTROLへ反映しました。")
                                            if compare_msg:
                                                st.warning(compare_msg)
                                            st.rerun()
                                        else:
                                            st.error(f"反映に失敗: {msg}")
                        else:
                            st.info("weekly_report JSONの読み込みに失敗しました。")
                    else:
                        st.caption("週次レビューJSONが未生成です。上の `weekly_report 実行` で作成してください。")

                    st.markdown("### 🧪 週次提案の反映前後比較")
                    compare_state = load_json(state_path) if state_path.exists() else {}
                    if not isinstance(compare_state, dict):
                        compare_state = {}
                    compare_obj = compare_state.get(WEEKLY_AI_COMPARE_STATE_KEY) if isinstance(compare_state.get(WEEKLY_AI_COMPARE_STATE_KEY), dict) else {}
                    if compare_obj:
                        before_ai = compare_obj.get("before_ai_auto", {}) if isinstance(compare_obj.get("before_ai_auto"), dict) else {}
                        before_day = _safe_str(compare_obj.get("before_last_day", ""))
                        after_ai = _ai_compare_extract(compare_state.get("_ai_auto_train"))
                        after_day = _safe_str(compare_state.get("_ai_auto_train_day", ""))
                        has_after = bool(after_day) and after_day != before_day

                        st.caption(
                            f"適用時刻: {_safe_str(compare_obj.get('applied_at', '-'))} / "
                            f"対象週: {_safe_str(compare_obj.get('range_start8', '-'))}〜{_safe_str(compare_obj.get('range_end8', '-'))} / "
                            f"status: {'更新済み' if has_after else '比較待機中'}"
                        )
                        st.caption(f"提案概要: {_safe_str(compare_obj.get('summary', '-'))}")

                        tracked_metric_keys = [
                            ("current_metric", "current_metric"),
                            ("best_metric", "best_metric"),
                            ("backtest_gate_eval_pf", "backtest_pf"),
                            ("backtest_gate_eval_expectancy", "backtest_expectancy"),
                        ]
                        improve_cnt = 0
                        worsen_cnt = 0
                        same_cnt = 0
                        if has_after:
                            card_cols = st.columns(4)
                            for i, (k, label) in enumerate(tracked_metric_keys):
                                b_num = _ai_compare_to_float(before_ai.get(k))
                                a_num = _ai_compare_to_float(after_ai.get(k))
                                delta_txt = "n/a"
                                if b_num is not None and a_num is not None:
                                    d = a_num - b_num
                                    delta_txt = f"{d:+.6f}"
                                    if d > 0:
                                        improve_cnt += 1
                                    elif d < 0:
                                        worsen_cnt += 1
                                    else:
                                        same_cnt += 1
                                card_cols[i].metric(label, _safe_str(after_ai.get(k, "-")), delta_txt)
                            if improve_cnt > worsen_cnt:
                                st.success(f"改善傾向: 改善={improve_cnt} / 悪化={worsen_cnt} / 同等={same_cnt}")
                            elif worsen_cnt > improve_cnt:
                                st.error(f"悪化傾向: 改善={improve_cnt} / 悪化={worsen_cnt} / 同等={same_cnt}")
                            else:
                                st.info(f"横ばい: 改善={improve_cnt} / 悪化={worsen_cnt} / 同等={same_cnt}")

                        def _cmp_status_for_metric(metric_key: str, delta_val: Any) -> str:
                            positive_better = {
                                "current_metric",
                                "best_metric",
                                "improve",
                                "backtest_gate_eval_pf",
                                "backtest_gate_eval_expectancy",
                            }
                            if metric_key not in positive_better:
                                return "REF"
                            d_num = _ai_compare_to_float(delta_val)
                            if d_num is None:
                                return "-"
                            if d_num > 0:
                                return "UP"
                            if d_num < 0:
                                return "DOWN"
                            return "SAME"

                        def _cmp_status_for_bool(before_v: Any, after_v: Any) -> str:
                            def _to_bool(v: Any) -> Optional[bool]:
                                s = str(v).strip().lower()
                                if s in BOOL_TRUE:
                                    return True
                                if s in BOOL_FALSE:
                                    return False
                                return None

                            b = _to_bool(before_v)
                            a = _to_bool(after_v)
                            if b is None or a is None:
                                return "-"
                            if (not b) and a:
                                return "UP"
                            if b and (not a):
                                return "DOWN"
                            return "SAME"

                        metric_rows: List[Dict[str, Any]] = []
                        metric_defs = [
                            ("rows", "used_rows"),
                            ("current_th", "current_th"),
                            ("best_th", "best_th"),
                            ("current_metric", "current_metric"),
                            ("best_metric", "best_metric"),
                            ("improve", "improve"),
                            ("backtest_gate_eval_pf", "backtest_pf"),
                            ("backtest_gate_eval_expectancy", "backtest_expectancy"),
                        ]
                        for key, label in metric_defs:
                            b = before_ai.get(key)
                            a = after_ai.get(key)
                            b_num = _ai_compare_to_float(b)
                            a_num = _ai_compare_to_float(a)
                            delta: Any = "-"
                            if b_num is not None and a_num is not None:
                                delta = round(a_num - b_num, 6)
                            metric_rows.append(
                                {
                                    "metric": label,
                                    "before": b,
                                    "after": a,
                                    "delta": delta,
                                    "status": _cmp_status_for_metric(key, delta),
                                }
                            )
                        metric_rows.append(
                            {
                                "metric": "train_backtest_gate_pass",
                                "before": before_ai.get("train_backtest_gate_pass"),
                                "after": after_ai.get("train_backtest_gate_pass"),
                                "delta": "-",
                                "status": _cmp_status_for_bool(
                                    before_ai.get("train_backtest_gate_pass"),
                                    after_ai.get("train_backtest_gate_pass"),
                                ),
                            }
                        )
                        metric_rows.append(
                            {
                                "metric": "train_backtest_gate_reason",
                                "before": before_ai.get("train_backtest_gate_reason"),
                                "after": after_ai.get("train_backtest_gate_reason"),
                                "delta": "-",
                                "status": "CHANGED"
                                if _safe_str(before_ai.get("train_backtest_gate_reason")) != _safe_str(after_ai.get("train_backtest_gate_reason"))
                                else "SAME",
                            }
                        )
                        st.dataframe(pd.DataFrame(metric_rows), width="stretch", hide_index=True)
                        if not has_after:
                            st.info("まだ新しいAI自動学習が走っていません。次回学習後に after/delta が更新されます。")

                        clear_cmp_key = f"analytics_clear_weekly_ai_compare_{_safe_str(compare_obj.get('applied_at', ''))}"
                        if st.button("比較スナップショットをクリア", key=clear_cmp_key, width="stretch"):
                            cur_state_obj = load_json(state_path) if state_path.exists() else {}
                            if not isinstance(cur_state_obj, dict):
                                cur_state_obj = {}
                            cur_state_obj.pop(WEEKLY_AI_COMPARE_STATE_KEY, None)
                            _write_json_dict(state_path, cur_state_obj)
                            st.success("比較スナップショットを削除しました。")
                            st.rerun()
                    else:
                        st.caption("比較対象は未作成です。`AI学習設定へ提案を反映` を実行するとここに前後比較が表示されます。")

                    compare_pairs = {
                        "last_7d": ("prev_7d", "前週（その前7日）"),
                        "last_30d": ("prev_30d", "前月（その前30日）"),
                        "last_365d": ("prev_365d", "前年（その前365日）"),
                    }
                    selected_period_key = period_label_to_key.get(selected_period_label, "manual")
                    if selected_period_key in compare_pairs:
                        prev_key, prev_label = compare_pairs[selected_period_key]
                        prev_days = _select_days_by_period(days, prev_key)
                        if prev_days:
                            _, prev_pos, _, _ = _analytics_dataset_for_days(logs_dir, prev_days)
                            if not prev_pos.empty:
                                prev_closed = prev_pos[
                                    (prev_pos["status"] == "CLOSED") & (prev_pos["ret_pct_est"].notna())
                                ].copy()
                                perf_prev = _perf_metrics_from_closed(prev_closed)
                                st.markdown(f"### 🔁 期間比較（{selected_period_label} vs {prev_label}）")
                                st.caption(
                                    f"現在期間: {len(pick_for_render)}日 / 比較期間: {len(prev_days)}日"
                                )
                                pnl_prev = float(perf_prev.get("pnl_sum", 0.0))
                                pnl_curr = float(perf_all.get("pnl_sum", 0.0))
                                if abs(pnl_prev) > 1e-12:
                                    pnl_improve_pct = ((pnl_curr - pnl_prev) / abs(pnl_prev)) * 100.0
                                    pnl_improve_label = f"{pnl_improve_pct:+.1f}%"
                                else:
                                    pnl_improve_pct = None
                                    pnl_improve_label = "n/a"

                                cmp1, cmp2, cmp3, cmp4 = st.columns(4)
                                cmp1.metric(
                                    "累積PnL(推定)",
                                    f"{perf_all['pnl_sum']:,.4f}",
                                    delta=f"{(perf_all['pnl_sum'] - perf_prev['pnl_sum']):+,.4f}",
                                )
                                cmp2.metric(
                                    "勝率",
                                    f"{perf_all['win_rate']:.1f}%",
                                    delta=f"{(perf_all['win_rate'] - perf_prev['win_rate']):+.1f} pt",
                                )
                                cmp3.metric(
                                    "Profit Factor",
                                    f"{perf_all['pf']:.3f}",
                                    delta=f"{(perf_all['pf'] - perf_prev['pf']):+.3f}",
                                )
                                cmp4.metric(
                                    "Expectancy(推定)",
                                    f"{perf_all['expectancy']:,.4f}",
                                    delta=f"{(perf_all['expectancy'] - perf_prev['expectancy']):+,.4f}",
                                )
                                cmp5, cmp6, cmp7, cmp8 = st.columns(4)
                                cmp5.metric(
                                    "PnL改善率(前期間比)",
                                    pnl_improve_label,
                                )
                                cmp6.metric(
                                    "Max Drawdown(PnL)",
                                    f"{perf_all['mdd_pnl']:,.4f}",
                                    delta=f"{(perf_all['mdd_pnl'] - perf_prev['mdd_pnl']):+,.4f}",
                                )
                                cmp7.metric(
                                    "Max Drawdown(ret_pct)",
                                    f"{perf_all['mdd_ret']:,.3f}%",
                                    delta=f"{(perf_all['mdd_ret'] - perf_prev['mdd_ret']):+,.3f}%",
                                )
                                cmp8.metric(
                                    "最大連敗",
                                    f"{int(perf_all['max_ls'])}",
                                    delta=f"{(int(perf_all['max_ls']) - int(perf_prev['max_ls'])):+d}",
                                )

                                prev_mode_df = prev_closed.copy()
                                if "exec_mode" not in prev_mode_df.columns:
                                    prev_mode_df["exec_mode"] = "PAPER"
                                prev_mode_df["exec_mode"] = (
                                    prev_mode_df["exec_mode"].astype(str).str.upper().replace({"": "PAPER"})
                                )
                                prev_mode_df.loc[
                                    ~prev_mode_df["exec_mode"].isin(["PAPER", "LIVE"]),
                                    "exec_mode",
                                ] = "PAPER"

                                st.markdown(f"#### 🧩 実行モード別 期間比較（vs {prev_label}）")
                                mode_cmp_map: Dict[str, Tuple[Dict[str, float], Dict[str, float]]] = {}
                                for mode_key in ("PAPER", "LIVE"):
                                    cur_mode = mode_df[mode_df["exec_mode"] == mode_key].copy()
                                    prev_mode = prev_mode_df[prev_mode_df["exec_mode"] == mode_key].copy()
                                    mode_cmp_map[mode_key] = (
                                        _perf_metrics_from_closed(cur_mode),
                                        _perf_metrics_from_closed(prev_mode),
                                    )
                                mcmp1, mcmp2 = st.columns(2)
                                for mcol, mode_key in ((mcmp1, "PAPER"), (mcmp2, "LIVE")):
                                    with mcol:
                                        cur_m, prev_m = mode_cmp_map.get(
                                            mode_key,
                                            (_perf_metrics_from_closed(pd.DataFrame()), _perf_metrics_from_closed(pd.DataFrame())),
                                        )
                                        st.markdown(f"**{mode_key}**")
                                        mc1, mc2, mc3 = st.columns(3)
                                        mc1.metric(
                                            "クローズ",
                                            f"{int(cur_m['closed'])}",
                                            delta=f"{(int(cur_m['closed']) - int(prev_m['closed'])):+d}",
                                        )
                                        mc2.metric(
                                            "勝率",
                                            f"{cur_m['win_rate']:.1f}%",
                                            delta=f"{(cur_m['win_rate'] - prev_m['win_rate']):+.1f} pt",
                                        )
                                        mc3.metric(
                                            "累積PnL",
                                            f"{cur_m['pnl_sum']:,.4f}",
                                            delta=f"{(cur_m['pnl_sum'] - prev_m['pnl_sum']):+,.4f}",
                                        )
                                        md1, md2, md3 = st.columns(3)
                                        md1.metric(
                                            "PF",
                                            f"{cur_m['pf']:.3f}",
                                            delta=f"{(cur_m['pf'] - prev_m['pf']):+.3f}",
                                        )
                                        md2.metric(
                                            "Expectancy",
                                            f"{cur_m['expectancy']:,.4f}",
                                            delta=f"{(cur_m['expectancy'] - prev_m['expectancy']):+,.4f}",
                                        )
                                        md3.metric(
                                            "MaxDD(PnL)",
                                            f"{cur_m['mdd_pnl']:,.4f}",
                                            delta=f"{(cur_m['mdd_pnl'] - prev_m['mdd_pnl']):+,.4f}",
                                        )
                                        if int(cur_m["closed"]) < 10 or int(prev_m["closed"]) < 10:
                                            st.caption("※ どちらかの期間でサンプルが少ないため、比較のブレが大きい可能性があります。")

                                if HAS_PLOTLY:
                                    st.markdown("#### 📊 期間比較チャート")
                                    chart_rows = [
                                        {
                                            "mode": "ALL",
                                            "period": "Current",
                                            "pnl": float(perf_all["pnl_sum"]),
                                            "win_rate": float(perf_all["win_rate"]),
                                            "pf": float(perf_all["pf"]),
                                            "expectancy": float(perf_all["expectancy"]),
                                            "mdd_pnl": float(perf_all["mdd_pnl"]),
                                        },
                                        {
                                            "mode": "ALL",
                                            "period": "Previous",
                                            "pnl": float(perf_prev["pnl_sum"]),
                                            "win_rate": float(perf_prev["win_rate"]),
                                            "pf": float(perf_prev["pf"]),
                                            "expectancy": float(perf_prev["expectancy"]),
                                            "mdd_pnl": float(perf_prev["mdd_pnl"]),
                                        },
                                    ]
                                    for mode_key in ("PAPER", "LIVE"):
                                        cur_m, prev_m = mode_cmp_map.get(
                                            mode_key,
                                            (_perf_metrics_from_closed(pd.DataFrame()), _perf_metrics_from_closed(pd.DataFrame())),
                                        )
                                        chart_rows.append(
                                            {
                                                "mode": mode_key,
                                                "period": "Current",
                                                "pnl": float(cur_m["pnl_sum"]),
                                                "win_rate": float(cur_m["win_rate"]),
                                                "pf": float(cur_m["pf"]),
                                                "expectancy": float(cur_m["expectancy"]),
                                                "mdd_pnl": float(cur_m["mdd_pnl"]),
                                            }
                                        )
                                        chart_rows.append(
                                            {
                                                "mode": mode_key,
                                                "period": "Previous",
                                                "pnl": float(prev_m["pnl_sum"]),
                                                "win_rate": float(prev_m["win_rate"]),
                                                "pf": float(prev_m["pf"]),
                                                "expectancy": float(prev_m["expectancy"]),
                                                "mdd_pnl": float(prev_m["mdd_pnl"]),
                                            }
                                        )

                                    cmp_chart_df = pd.DataFrame(chart_rows)
                                    cmp_metric_map = {
                                        "累積PnL(推定)": "pnl",
                                        "勝率(%)": "win_rate",
                                        "Profit Factor": "pf",
                                        "Expectancy": "expectancy",
                                        "MaxDD(PnL)": "mdd_pnl",
                                    }
                                    cmp_metric_label = st.selectbox(
                                        "比較チャート指標",
                                        list(cmp_metric_map.keys()),
                                        index=0,
                                        key="analytics_compare_chart_metric",
                                    )
                                    cmp_metric_col = cmp_metric_map.get(cmp_metric_label, "pnl")
                                    cmp_chart_df["mode_label"] = cmp_chart_df["mode"].map(
                                        {"ALL": "全体", "PAPER": "PAPER", "LIVE": "LIVE"}
                                    )
                                    cmp_mode_order = ["全体", "PAPER", "LIVE"]
                                    show_diff_line = st.toggle(
                                        "差分線（Current - Previous）を重ねる",
                                        value=True,
                                        key="analytics_compare_chart_show_diff",
                                    )
                                    fig_cmp = px.bar(
                                        cmp_chart_df,
                                        x="mode_label",
                                        y=cmp_metric_col,
                                        color="period",
                                        barmode="group",
                                        category_orders={
                                            "mode_label": cmp_mode_order,
                                            "period": ["Current", "Previous"],
                                        },
                                        color_discrete_map={"Current": "#00CC96", "Previous": "#636EFA"},
                                        title=f"{cmp_metric_label}（Current vs Previous）",
                                    )
                                    if show_diff_line:
                                        cur_df = (
                                            cmp_chart_df[cmp_chart_df["period"] == "Current"][["mode_label", cmp_metric_col]]
                                            .rename(columns={cmp_metric_col: "current"})
                                        )
                                        prev_df = (
                                            cmp_chart_df[cmp_chart_df["period"] == "Previous"][["mode_label", cmp_metric_col]]
                                            .rename(columns={cmp_metric_col: "previous"})
                                        )
                                        diff_df = pd.merge(cur_df, prev_df, on="mode_label", how="outer")
                                        diff_df["current"] = pd.to_numeric(diff_df["current"], errors="coerce").fillna(0.0)
                                        diff_df["previous"] = pd.to_numeric(diff_df["previous"], errors="coerce").fillna(0.0)
                                        diff_df["diff"] = diff_df["current"] - diff_df["previous"]
                                        diff_df["mode_label"] = pd.Categorical(
                                            diff_df["mode_label"],
                                            categories=cmp_mode_order,
                                            ordered=True,
                                        )
                                        diff_df = diff_df.sort_values("mode_label")
                                        # Improvement color rule:
                                        # positive diff = improved (green), negative diff = worsened (red).
                                        fig_cmp.add_trace(
                                            go.Scatter(
                                                x=diff_df["mode_label"],
                                                y=diff_df["diff"],
                                                mode="lines",
                                                name="Diff(Current-Previous)",
                                                line=dict(color="#94A3B8", width=2, dash="dot"),
                                                yaxis="y2",
                                                hovertemplate="Diff<br>%{x}<br>%{y:.6f}<extra></extra>",
                                            )
                                        )
                                        pos_df = diff_df[diff_df["diff"] > 0]
                                        neg_df = diff_df[diff_df["diff"] < 0]
                                        flat_df = diff_df[diff_df["diff"] == 0]
                                        if not pos_df.empty:
                                            fig_cmp.add_trace(
                                                go.Scatter(
                                                    x=pos_df["mode_label"],
                                                    y=pos_df["diff"],
                                                    mode="markers+text",
                                                    name="Diff 改善(+)",
                                                    marker=dict(color="#00CC96", size=9),
                                                    text=[f"{v:+.3f}" for v in pos_df["diff"].tolist()],
                                                    textposition="top center",
                                                    yaxis="y2",
                                                    hovertemplate="Diff(+)<br>%{x}<br>%{y:.6f}<extra></extra>",
                                                )
                                            )
                                        if not neg_df.empty:
                                            fig_cmp.add_trace(
                                                go.Scatter(
                                                    x=neg_df["mode_label"],
                                                    y=neg_df["diff"],
                                                    mode="markers+text",
                                                    name="Diff 悪化(-)",
                                                    marker=dict(color="#EF553B", size=9),
                                                    text=[f"{v:+.3f}" for v in neg_df["diff"].tolist()],
                                                    textposition="bottom center",
                                                    yaxis="y2",
                                                    hovertemplate="Diff(-)<br>%{x}<br>%{y:.6f}<extra></extra>",
                                                )
                                            )
                                        if not flat_df.empty:
                                            fig_cmp.add_trace(
                                                go.Scatter(
                                                    x=flat_df["mode_label"],
                                                    y=flat_df["diff"],
                                                    mode="markers+text",
                                                    name="Diff 変化なし",
                                                    marker=dict(color="#94A3B8", size=8),
                                                    text=["±0.000" for _ in range(len(flat_df))],
                                                    textposition="top center",
                                                    yaxis="y2",
                                                    hovertemplate="Diff(0)<br>%{x}<br>%{y:.6f}<extra></extra>",
                                                )
                                            )
                                    fig_cmp.update_layout(
                                        xaxis_title="区分",
                                        yaxis_title=cmp_metric_label,
                                        yaxis2=dict(
                                            title="差分",
                                            overlaying="y",
                                            side="right",
                                            showgrid=False,
                                            zeroline=True,
                                            zerolinecolor="rgba(245,158,11,0.4)",
                                        ),
                                        plot_bgcolor="rgba(0,0,0,0)",
                                        paper_bgcolor="rgba(0,0,0,0)",
                                        margin=dict(l=10, r=10, t=48, b=10),
                                    )
                                    st.plotly_chart(fig_cmp, width="stretch")
                            else:
                                st.info(f"比較対象（{prev_label}）にCLOSEDデータがありません。")
                        else:
                            st.info(f"比較対象（{prev_label}）の日次ログが不足しています。")

                    st.markdown("### 🧩 実行モード別（PAPER / LIVE）")

                    md1, md2 = st.columns(2)
                    for col, mode_key in ((md1, "PAPER"), (md2, "LIVE")):
                        with col:
                            sub = mode_df[mode_df["exec_mode"] == mode_key].copy()
                            m = _perf_metrics_from_closed(sub)
                            st.markdown(f"**{mode_key}**")
                            c1, c2, c3 = st.columns(3)
                            c1.metric("クローズ", f"{int(m['closed'])}")
                            c2.metric("勝率", f"{m['win_rate']:.1f}%")
                            c3.metric("累積PnL", f"{m['pnl_sum']:,.4f}")
                            d1, d2, d3 = st.columns(3)
                            d1.metric("PF", f"{m['pf']:.3f}")
                            d2.metric("Payoff", f"{m['payoff']:.3f}")
                            d3.metric("Expectancy", f"{m['expectancy']:,.4f}")
                            st.caption(f"最大連敗: {int(m['max_ls'])}")
                            if int(m["closed"]) < 10:
                                st.caption("※ サンプルが少ないため、数値のブレが大きい可能性があります。")

                    st.markdown("### 🧠 テクニカルEXIT集計（exit_tech）")
                    tech_rows: List[Dict[str, Any]] = []
                    for rr in raw_rows:
                        if not isinstance(rr, dict):
                            continue
                        res_x = str(rr.get("result", "")).strip()
                        if not res_x.startswith("PAPER_EXIT"):
                            continue
                        note_x = str(rr.get("note", "")).strip()
                        reason_x = _extract_note_kv(note_x, "exit_tech")
                        if not reason_x:
                            continue
                        tech_rows.append(
                            {
                                "time_dt": pd.to_datetime(rr.get("time"), errors="coerce"),
                                "pos_id": str(rr.get("pos_id", "")).strip(),
                                "side": str(rr.get("side", "")).strip().upper(),
                                "result": res_x,
                                "reason": reason_x,
                                "fast_n": _extract_note_kv(note_x, "exit_sma_fast_n"),
                                "slow_n": _extract_note_kv(note_x, "exit_sma_slow_n"),
                            }
                        )

                    tech_df = pd.DataFrame(tech_rows)
                    if tech_df.empty:
                        st.info("`exit_tech=` が付いたEXITログはまだありません。")
                    else:
                        if "time_dt" in tech_df.columns:
                            tech_df = tech_df.sort_values("time_dt")
                        if "pos_id" in tech_df.columns:
                            tech_df = tech_df.drop_duplicates(subset=["pos_id"], keep="last")

                        merge_cols = [c for c in ["pos_id", "ret_pct_est", "pnl_est"] if c in df_closed.columns]
                        if "pos_id" in merge_cols:
                            perf_df = df_closed[merge_cols].copy()
                            tech_df = tech_df.merge(perf_df, how="left", on="pos_id")
                        else:
                            tech_df["ret_pct_est"] = np.nan
                            tech_df["pnl_est"] = np.nan

                        tn = int(len(tech_df))
                        t_win = int((pd.to_numeric(tech_df["ret_pct_est"], errors="coerce") > 0).sum())
                        t_win_rate = (float(t_win) / float(tn) * 100.0) if tn > 0 else 0.0
                        t_ret_sum = float(pd.to_numeric(tech_df["ret_pct_est"], errors="coerce").fillna(0.0).sum())
                        t_pnl_sum = float(pd.to_numeric(tech_df["pnl_est"], errors="coerce").fillna(0.0).sum())

                        t1, t2, t3, t4 = st.columns(4)
                        t1.metric("Tech EXIT数", f"{tn}")
                        t2.metric("Tech 勝率(推定)", f"{t_win_rate:.1f}%")
                        t3.metric("Tech 累積ret_pct(推定)", f"{t_ret_sum:.3f}%")
                        t4.metric("Tech 累積PnL(推定)", f"{t_pnl_sum:,.4f}")

                        reason_sum = (
                            tech_df.groupby("reason", dropna=False)
                            .agg(
                                exits=("pos_id", "count"),
                                win_rate_pct=("ret_pct_est", lambda x: float((pd.to_numeric(x, errors="coerce") > 0).mean() * 100.0) if len(x) else 0.0),
                                ret_pct_sum=("ret_pct_est", lambda x: float(pd.to_numeric(x, errors="coerce").fillna(0.0).sum())),
                                pnl_est_sum=("pnl_est", lambda x: float(pd.to_numeric(x, errors="coerce").fillna(0.0).sum())),
                            )
                            .reset_index()
                            .sort_values(["exits", "reason"], ascending=[False, True])
                        )
                        st.dataframe(reason_sum, width="stretch", hide_index=True)

                        if HAS_PLOTLY and (not reason_sum.empty):
                            fig_tech = px.bar(
                                reason_sum,
                                x="reason",
                                y="exits",
                                color="pnl_est_sum",
                                color_continuous_scale="RdYlGn",
                                title="テクニカルEXIT 理由別件数",
                            )
                            fig_tech.update_layout(
                                xaxis_title="exit_tech",
                                yaxis_title="件数",
                                plot_bgcolor="rgba(0,0,0,0)",
                                paper_bgcolor="rgba(0,0,0,0)",
                                margin=dict(l=10, r=10, t=48, b=10),
                            )
                            st.plotly_chart(fig_tech, width="stretch")

                    if total == 0:
                        st.warning("CLOSEDポジションが無いため、損益チャートを描画できません。")
                    elif not HAS_PLOTLY:
                        st.warning("Plotly未導入のため簡易チャートを表示します。`pip install plotly` を追加すると高機能表示になります。")
                        line_src = df_closed.set_index("time_dt")[["cum_ret_pct"]].copy()
                        line_src.columns = ["累積ret_pct(推定)"]
                        st.line_chart(line_src)
                        bar_src = df_closed.set_index("time_dt")[["ret_pct_est"]].copy()
                        bar_src.columns = ["ret_pct(推定)"]
                        st.bar_chart(bar_src)
                    else:
                        st.markdown("#### 🧭 ローソク足 + ENTRY/EXIT（どこで売買したか）")
                        ctf1, ctf2 = st.columns([1, 1])
                        with ctf1:
                            candle_tf_label = st.selectbox(
                                "足種",
                                ["1分", "3分", "5分", "15分"],
                                index=2,
                                key="analytics_candle_tf",
                            )
                        with ctf2:
                            show_bidask = st.toggle("best_bid / best_ask も表示", value=False, key="analytics_show_bidask")

                        if price_df.empty:
                            st.info("価格系列（ltp）が不足しているため、価格チャートを表示できません。")
                        else:
                            candle_rule = {"1分": "1min", "3分": "3min", "5分": "5min", "15分": "15min"}.get(candle_tf_label, "5min")
                            ohlc_df = build_ohlc_from_price_df(price_df, interval_rule=candle_rule, price_col="ltp")
                            fig_price = go.Figure()

                            if not ohlc_df.empty:
                                fig_price.add_trace(
                                    go.Candlestick(
                                        x=ohlc_df["time_dt"],
                                        open=ohlc_df["open"],
                                        high=ohlc_df["high"],
                                        low=ohlc_df["low"],
                                        close=ohlc_df["close"],
                                        name=f"LTP {candle_tf_label}",
                                        increasing_line_color="#d62728",   # 上昇=赤
                                        decreasing_line_color="#1f77b4",   # 下降=青
                                        increasing_fillcolor="rgba(214,39,40,0.35)",
                                        decreasing_fillcolor="rgba(31,119,180,0.35)",
                                    )
                                )
                            else:
                                fig_price.add_trace(
                                    go.Scatter(
                                        x=price_df["time_dt"],
                                        y=price_df["ltp"],
                                        mode="lines",
                                        name="LTP",
                                        line=dict(color="#1f77b4", width=2),
                                    )
                                )

                            if show_bidask:
                                if "best_bid" in price_df.columns:
                                    fig_price.add_trace(
                                        go.Scatter(
                                            x=price_df["time_dt"],
                                            y=price_df["best_bid"],
                                            mode="lines",
                                            name="best_bid",
                                            line=dict(color="#2ca02c", width=1, dash="dot"),
                                            opacity=0.8,
                                        )
                                    )
                                if "best_ask" in price_df.columns:
                                    fig_price.add_trace(
                                        go.Scatter(
                                            x=price_df["time_dt"],
                                            y=price_df["best_ask"],
                                            mode="lines",
                                            name="best_ask",
                                            line=dict(color="#d62728", width=1, dash="dot"),
                                            opacity=0.8,
                                        )
                                    )

                            if not event_df.empty:
                                eb = event_df[event_df["event_kind"] == "ENTRY_BUY"]
                                es = event_df[event_df["event_kind"] == "ENTRY_SELL"]
                                ex = event_df[event_df["event_kind"] == "EXIT"]
                                if not eb.empty:
                                    fig_price.add_trace(
                                        go.Scatter(
                                            x=eb["time_dt"],
                                            y=eb["price_plot"],
                                            mode="markers",
                                            name="ENTRY BUY",
                                            marker=dict(color="#00CC96", symbol="triangle-up", size=11),
                                            text=eb["pos_id"],
                                            hovertemplate="ENTRY BUY<br>%{x}<br>price=%{y}<br>pos_id=%{text}<extra></extra>",
                                        )
                                    )
                                if not es.empty:
                                    fig_price.add_trace(
                                        go.Scatter(
                                            x=es["time_dt"],
                                            y=es["price_plot"],
                                            mode="markers",
                                            name="ENTRY SELL",
                                            marker=dict(color="#EF553B", symbol="triangle-down", size=11),
                                            text=es["pos_id"],
                                            hovertemplate="ENTRY SELL<br>%{x}<br>price=%{y}<br>pos_id=%{text}<extra></extra>",
                                        )
                                    )
                                if not ex.empty:
                                    fig_price.add_trace(
                                        go.Scatter(
                                            x=ex["time_dt"],
                                            y=ex["price_plot"],
                                            mode="markers",
                                            name="EXIT",
                                            marker=dict(color="#FFB000", symbol="x", size=11),
                                            text=ex["pos_id"],
                                            hovertemplate="EXIT<br>%{x}<br>price=%{y}<br>pos_id=%{text}<extra></extra>",
                                        )
                                    )

                            fig_price.update_layout(
                                title=f"ローソク足と売買ポイント（推定 / {candle_tf_label}）",
                                plot_bgcolor="rgba(0,0,0,0)",
                                paper_bgcolor="rgba(0,0,0,0)",
                                margin=dict(l=10, r=10, t=48, b=10),
                                legend=dict(orientation="h"),
                            )
                            _enable_time_price_pan_zoom(fig_price, with_rangeslider=True, y_title="価格")
                            st.plotly_chart(fig_price, width="stretch", config=_plotly_interactive_config())
                            st.caption("ローソク: 上昇=赤 / 下降=青 | ENTRY BUY=緑▲ / ENTRY SELL=赤▼ / EXIT=黄✕")

                        fig_top_col, fig_pie_col = st.columns([2, 1])
                        with fig_top_col:
                            fig_line = go.Figure()
                            fig_line.add_trace(
                                go.Scatter(
                                    x=df_closed["time_dt"],
                                    y=df_closed["cum_ret_pct"],
                                    mode="lines+markers",
                                    name="累積ret_pct(推定)",
                                    line=dict(color="#00CC96", width=3),
                                    fill="tozeroy",
                                    fillcolor="rgba(0,204,150,0.12)",
                                )
                            )
                            fig_line.update_layout(
                                title="累積損益カーブ（ret_pct推定）",
                                xaxis_title="時刻",
                                yaxis_title="累積ret_pct(%)",
                                plot_bgcolor="rgba(0,0,0,0)",
                                paper_bgcolor="rgba(0,0,0,0)",
                                margin=dict(l=10, r=10, t=48, b=10),
                            )
                            st.plotly_chart(fig_line, width="stretch")

                        with fig_pie_col:
                            pie_df = pd.DataFrame({"結果": ["Win", "Loss"], "回数": [wins, losses]})
                            fig_pie = px.pie(
                                pie_df,
                                values="回数",
                                names="結果",
                                hole=0.45,
                                color="結果",
                                color_discrete_map={"Win": "#00CC96", "Loss": "#EF553B"},
                                title="勝敗比率",
                            )
                            st.plotly_chart(fig_pie, width="stretch")

                        df_closed["pl_type"] = np.where(df_closed["ret_pct_est"] >= 0, "Profit", "Loss")
                        fig_bar = px.bar(
                            df_closed,
                            x="time_dt",
                            y="ret_pct_est",
                            color="pl_type",
                            color_discrete_map={"Profit": "#00CC96", "Loss": "#EF553B"},
                            title="各トレード損益（ret_pct推定）",
                        )
                        fig_bar.update_layout(
                            xaxis_title="時刻",
                            yaxis_title="ret_pct(%)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            paper_bgcolor="rgba(0,0,0,0)",
                            margin=dict(l=10, r=10, t=48, b=10),
                        )
                        st.plotly_chart(fig_bar, width="stretch")

                    st.markdown("### 🏆 勝ち負け内訳（推定）")
                    if total > 0:
                        rank_df = df_closed.copy()
                        rank_df = rank_df.sort_values("pnl_est", ascending=False)
                        r1, r2 = st.columns(2)
                        with r1:
                            st.markdown("**Top 利益トレード**")
                            st.dataframe(
                                rank_df[["pos_id", "side", "entry_time", "exit_time", "pnl_est", "ret_pct_est"]].head(5),
                                width="stretch",
                            )
                        with r2:
                            st.markdown("**Top 損失トレード**")
                            st.dataframe(
                                rank_df[["pos_id", "side", "entry_time", "exit_time", "pnl_est", "ret_pct_est"]]
                                .tail(5)
                                .sort_values("pnl_est", ascending=True),
                                width="stretch",
                            )

                    st.markdown("### 📅 日次損益サマリー（推定・fee未加味）")
                    daily = df_closed.copy()
                    daily["day"] = daily["time_dt"].dt.strftime("%Y-%m-%d")
                    daily["_ret"] = pd.to_numeric(daily.get("ret_pct_est"), errors="coerce")
                    daily["_pnl"] = pd.to_numeric(daily.get("pnl_est"), errors="coerce")
                    daily_sum = (
                        daily.groupby("day", dropna=False)
                        .agg(
                            取引数=("pos_id", "count"),
                            勝=("_ret", lambda x: int((x > 0).sum())),
                            負=("_ret", lambda x: int((x < 0).sum())),
                            勝率=("_ret", lambda x: float((x > 0).mean() * 100.0) if len(x) else 0.0),
                            収益率合計=("_ret", lambda x: float(x.fillna(0.0).sum())),
                            損益合計=("_pnl", lambda x: float(x.fillna(0.0).sum())),
                        )
                        .reset_index()
                        .rename(columns={"day": "日付"})
                    )
                    daily_sum["累積損益"] = daily_sum["損益合計"].cumsum()
                    # Total row
                    _total_trades = int(daily_sum["取引数"].sum())
                    _total_wins = int(daily_sum["勝"].sum())
                    _total_losses = int(daily_sum["負"].sum())
                    _total_wr = float(_total_wins / _total_trades * 100.0) if _total_trades > 0 else 0.0
                    _total_ret = float(daily_sum["収益率合計"].sum())
                    _total_pnl = float(daily_sum["損益合計"].sum())
                    _total_row = pd.DataFrame([{
                        "日付": "📊 合計",
                        "取引数": _total_trades,
                        "勝": _total_wins,
                        "負": _total_losses,
                        "勝率": _total_wr,
                        "収益率合計": _total_ret,
                        "損益合計": _total_pnl,
                        "累積損益": _total_pnl,
                    }])
                    daily_display = pd.concat([daily_sum, _total_row], ignore_index=True)
                    st.dataframe(
                        daily_display,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "勝率": st.column_config.NumberColumn("勝率(%)", format="%.1f"),
                            "収益率合計": st.column_config.NumberColumn("収益率合計(%)", format="%.3f"),
                            "損益合計": st.column_config.NumberColumn("損益(推定)", format="%.4f"),
                            "累積損益": st.column_config.NumberColumn("累積損益(推定)", format="%.4f"),
                        },
                    )

                    st.markdown("### 🕒 時間帯損益サマリー（推定）")
                    hourly_sum = build_hourly_summary(df_closed)
                    if hourly_sum.empty:
                        st.info("時間帯サマリーを作成できるデータが不足しています。")
                    else:
                        _hourly_display = hourly_sum[["hour_label", "trades", "win_rate_pct", "ret_pct_sum", "pnl_est_sum", "avg_pnl_est"]].copy()
                        _hourly_display = _hourly_display.rename(columns={
                            "hour_label": "時間帯",
                            "trades": "取引数",
                            "win_rate_pct": "勝率(%)",
                            "ret_pct_sum": "収益率合計(%)",
                            "pnl_est_sum": "損益合計(推定)",
                            "avg_pnl_est": "平均損益(推定)",
                        })
                        st.dataframe(
                            _hourly_display,
                            width="stretch",
                            hide_index=True,
                            column_config={
                                "勝率(%)": st.column_config.NumberColumn(format="%.1f"),
                                "収益率合計(%)": st.column_config.NumberColumn(format="%.3f"),
                                "損益合計(推定)": st.column_config.NumberColumn(format="%.4f"),
                                "平均損益(推定)": st.column_config.NumberColumn(format="%.4f"),
                            },
                        )
                        if HAS_PLOTLY:
                            fig_hour = go.Figure()
                            fig_hour.add_trace(
                                go.Bar(
                                    x=hourly_sum["hour_label"],
                                    y=hourly_sum["pnl_est_sum"],
                                    name="pnl_est_sum",
                                    marker_color=np.where(hourly_sum["pnl_est_sum"] >= 0, "#00CC96", "#EF553B"),
                                )
                            )
                            fig_hour.update_layout(
                                title="時間帯別 PnL（推定）",
                                xaxis_title="時間帯",
                                yaxis_title="PnL(推定)",
                                plot_bgcolor="rgba(0,0,0,0)",
                                paper_bgcolor="rgba(0,0,0,0)",
                                margin=dict(l=10, r=10, t=48, b=10),
                            )
                            st.plotly_chart(fig_hour, width="stretch")

                    st.markdown("### 🔍 同じ負け方分析（trend / signal / 時間帯）")
                    lp1, lp2 = st.columns([1, 1])
                    with lp1:
                        loss_pattern_min = st.number_input(
                            "同一パターン最小件数",
                            min_value=1,
                            max_value=20,
                            value=2,
                            step=1,
                            key="analytics_loss_pattern_min_n",
                        )
                    with lp2:
                        loss_pattern_exec_mode = st.selectbox(
                            "対象モード",
                            ["ALL", "LIVE", "PAPER"],
                            index=0,
                            key="analytics_loss_pattern_exec_mode",
                        )

                    loss_src = df_closed.copy()
                    if "exec_mode" in loss_src.columns and loss_pattern_exec_mode in ("LIVE", "PAPER"):
                        loss_src = loss_src[loss_src["exec_mode"].astype(str).str.upper() == loss_pattern_exec_mode].copy()

                    ts_src = loss_src.copy()
                    if not ts_src.empty:
                        ts_src["ret_pct_est"] = pd.to_numeric(ts_src.get("ret_pct_est"), errors="coerce")
                        ts_src["pnl_est"] = pd.to_numeric(ts_src.get("pnl_est"), errors="coerce")
                        for c, default in [("trend", "UNKNOWN"), ("signal", "NONE")]:
                            if c not in ts_src.columns:
                                ts_src[c] = default
                            ts_src[c] = ts_src[c].astype(str).str.strip().replace({"": default}).str.upper()
                        trend_signal_df = (
                            ts_src.groupby(["trend", "signal"], dropna=False)
                            .agg(
                                closed_n=("pos_id", "count"),
                                loss_n=("ret_pct_est", lambda x: int((pd.to_numeric(x, errors="coerce") < 0).sum())),
                                win_rate_pct=(
                                    "ret_pct_est",
                                    lambda x: float((pd.to_numeric(x, errors="coerce") > 0).mean() * 100.0) if len(x) else 0.0,
                                ),
                                ret_pct_sum=("ret_pct_est", lambda x: float(pd.to_numeric(x, errors="coerce").fillna(0.0).sum())),
                                pnl_est_sum=("pnl_est", lambda x: float(pd.to_numeric(x, errors="coerce").fillna(0.0).sum())),
                            )
                            .reset_index()
                        )
                        trend_signal_df["loss_rate_pct"] = np.where(
                            trend_signal_df["closed_n"] > 0,
                            trend_signal_df["loss_n"] / trend_signal_df["closed_n"] * 100.0,
                            0.0,
                        )
                        trend_signal_df = trend_signal_df.sort_values(
                            ["loss_rate_pct", "closed_n", "ret_pct_sum"],
                            ascending=[False, False, True],
                        ).reset_index(drop=True)
                        st.caption("トレンド/シグナル別の勝率と損失集中を確認し、同じ負け方の偏りを把握します。")
                        st.dataframe(
                            trend_signal_df[
                                [
                                    "trend",
                                    "signal",
                                    "closed_n",
                                    "loss_n",
                                    "loss_rate_pct",
                                    "win_rate_pct",
                                    "ret_pct_sum",
                                    "pnl_est_sum",
                                ]
                            ],
                            width="stretch",
                            hide_index=True,
                        )

                    pattern_df = build_repeated_loss_patterns(loss_src, min_losses=int(loss_pattern_min))
                    if pattern_df.empty:
                        st.info("同一パターンの損失はまだ抽出されていません（件数不足または損失なし）。")
                    else:
                        st.dataframe(
                            pattern_df[
                                [
                                    "pattern",
                                    "loss_n",
                                    "loss_share_pct",
                                    "loss_ret_sum_pct",
                                    "avg_loss_ret_pct",
                                    "avg_loss_pnl_est",
                                    "last_seen",
                                ]
                            ],
                            width="stretch",
                            hide_index=True,
                        )
                        if HAS_PLOTLY:
                            fig_lp = px.bar(
                                pattern_df.head(15).iloc[::-1],
                                x="loss_n",
                                y="pattern",
                                orientation="h",
                                color="avg_loss_ret_pct",
                                color_continuous_scale="RdYlGn",
                                title="損失が繰り返されているパターン（上位15）",
                            )
                            fig_lp.update_layout(
                                xaxis_title="loss件数",
                                yaxis_title="pattern",
                                plot_bgcolor="rgba(0,0,0,0)",
                                paper_bgcolor="rgba(0,0,0,0)",
                                margin=dict(l=10, r=10, t=48, b=10),
                            )
                            st.plotly_chart(fig_lp, width="stretch")

                        bad_hours_rank = (
                            pattern_df[pattern_df["entry_hour"] >= 0]
                            .groupby("entry_hour", dropna=False)
                            .agg(loss_n=("loss_n", "sum"), loss_ret_sum_pct=("loss_ret_sum_pct", "sum"))
                            .reset_index()
                            .sort_values(["loss_n", "loss_ret_sum_pct"], ascending=[False, True])
                        )
                        if (
                            isinstance(hourly_sum, pd.DataFrame)
                            and (not hourly_sum.empty)
                            and {"trades", "pnl_est_sum", "win_rate_pct", "hour"}.issubset(set(hourly_sum.columns))
                        ):
                            good_hours_rank = (
                                hourly_sum[hourly_sum["trades"] >= 3]
                                .sort_values(["pnl_est_sum", "win_rate_pct"], ascending=[False, False])
                                .head(6)
                            )
                        else:
                            good_hours_rank = pd.DataFrame()
                        bad_hours = [int(x) for x in bad_hours_rank["entry_hour"].head(6).tolist()]
                        good_hours = [int(x) for x in good_hours_rank["hour"].head(6).tolist()] if "hour" in good_hours_rank.columns else []
                        if bad_hours:
                            suggest_ctrl = {
                                "ai_train_weekly_feedback_enabled": "1",
                                "ai_train_weekly_bad_hours": ",".join(str(int(h)) for h in sorted(set(bad_hours))),
                                "ai_train_weekly_good_hours": ",".join(str(int(h)) for h in sorted(set(good_hours))),
                            }
                            st.caption("反省学習の即時提案（同じ負け方を時間帯補正へ反映）")
                            st.code(json.dumps(suggest_ctrl, ensure_ascii=False, indent=2))
                            if st.button("🧠 反省学習設定をCONTROLへ反映", key="analytics_apply_loss_pattern_feedback", width="stretch"):
                                cur_ctrl, _ = read_control_kv_csv(control_path)
                                upd_ctrl = dict(cur_ctrl)
                                for k, v in suggest_ctrl.items():
                                    upd_ctrl[str(k)] = str(v)
                                _val_errs, _ = _validate_control_values(upd_ctrl)
                                if _val_errs:
                                    st.error("反省学習の提案値に不正な値が含まれています。反映をスキップしました。")
                                    for _e in _val_errs[:5]:
                                        st.write(f"- {_e}")
                                    st.stop()
                                ok, msg = write_control_kv_csv_with_log(
                                    main_dir=main_dir,
                                    path=control_path,
                                    before_ctrl=cur_ctrl,
                                    after_ctrl=upd_ctrl,
                                    author=change_actor,
                                    reason="analytics:apply_loss_pattern_feedback",
                                )
                                if ok:
                                    st.success("反省学習設定をCONTROLへ反映しました。次回AI学習サイクルで適用されます。")
                                    st.rerun()
                                else:
                                    st.error(f"反映に失敗: {msg}")

                    with st.expander("詳細データ（pos_idごとの推定）", expanded=False):
                        show_cols = [
                            c
                            for c in [
                                "pos_id",
                                "status",
                                "side",
                                "entry_time",
                                "exit_time",
                                "entry_price",
                                "exit_ltp",
                                "size",
                                "ret_pct_est",
                                "pnl_est",
                            ]
                            if c in df_pos.columns
                        ]
                        st.dataframe(df_pos[show_cols], width="stretch")
                        csv_bytes = df_pos[show_cols].to_csv(index=False).encode("utf-8-sig")
                        st.download_button(
                            "CSVダウンロード（pos_id推定データ）",
                            data=csv_bytes,
                            file_name=f"dashboard_pos_est_{token}.csv",
                            mime="text/csv",
                            width="stretch",
                        )

                    st.caption("※ すべて推定値（fee未加味）。最終的な正は daily_report / audit 出力を参照してください。")

        st.divider()
        st.caption("Dashboardは“表示と操作”に徹する。判断・集計ロジックは bot / daily_report が正（SPEC）。")

    # =========================================================
    # TAB: History
    # =========================================================
    with tabs[tab_index["history"]]:
        st.subheader("トレード履歴（raw）")
        st.caption("原因調査しやすいように、result・キーワード・件数で絞り込めます。")
        if not logs_dir:
            st.warning("logs/ が見つかりません。")
        else:
            days = list_log_days(logs_dir)
            if not days:
                st.warning("trade_log がありません。")
            else:
                sel = st.selectbox("日付", days, index=0)
                p = logs_dir / f"trade_log_{sel}.csv"
                df = read_trade_log_df(p, file_cache_token(p))
                if df.empty:
                    st.info("空です。")
                else:
                    f1, f2, f3, f4 = st.columns(4)
                    with f1:
                        results = sorted({str(x) for x in df.get("result", pd.Series(dtype=str)).dropna().tolist()}) if "result" in df.columns else []
                        selected_results = st.multiselect("result絞り込み", results, default=[])
                    with f2:
                        keyword = st.text_input("キーワード検索(note/pos_id)", key="history_keyword")
                    with f3:
                        desc = st.toggle("新しい順", value=True)
                    with f4:
                        max_rows_upper = max(10, int(len(df)))
                        max_rows_default = min(300, max_rows_upper)
                        max_rows = st.number_input(
                            "表示件数",
                            min_value=10,
                            max_value=max_rows_upper,
                            value=max_rows_default,
                            step=10,
                        )

                    dff = df.copy()
                    if selected_results and "result" in dff.columns:
                        dff = dff[dff["result"].astype(str).isin(selected_results)]
                    if keyword:
                        kw = str(keyword).strip()
                        cols_for_kw = [c for c in ["note", "pos_id", "result", "side"] if c in dff.columns]
                        if cols_for_kw:
                            mask = False
                            for c in cols_for_kw:
                                mask = mask | dff[c].astype(str).str.contains(kw, na=False)
                            dff = dff[mask]

                    if "time_dt" in dff.columns:
                        dff = dff.sort_values("time_dt", ascending=not desc)
                    else:
                        dff = dff.iloc[::-1] if desc else dff
                    dff = dff.head(int(max_rows))

                    s1, s2, s3 = st.columns(3)
                    s1.metric("表示行数", len(dff))
                    s2.metric("PAPER", int((dff["result"] == "PAPER").sum()) if "result" in dff.columns else 0)
                    s3.metric("EXIT", int(dff["result"].astype(str).str.startswith("PAPER_EXIT").sum()) if "result" in dff.columns else 0)

                    cols = [c for c in ["time", "pos_id", "result", "side", "price", "ltp", "spread_pct", "trend", "signal", "note"] if c in df.columns]
                    st.dataframe(dff[cols], width="stretch")

    # =========================================================
    # TAB: pos_id / Audit(JSON) — SPEC Core
    # =========================================================
    with tabs[tab_index["pos"]]:
        st.subheader("pos_id・監査(JSON)（SPEC中核）")
        st.caption("まずは監査JSON優先で確認し、必要時のみログ推定へ切り替えてください。")

        rep_files = collect_json_reports(out_dir)
        use_json = False
        selected_json: Optional[Path] = None
        audit_obj: Optional[Dict[str, Any]] = None

        left, right = st.columns([2, 1])
        with left:
            if rep_files:
                use_json = st.toggle("監査JSONを使う（最優先）", value=True)
                if use_json:
                    selected_json = st.selectbox("JSONファイル", rep_files, format_func=lambda p: p.name)
            else:
                st.info("daily_report_out に JSON がありません。ログから推定表示します。")

        with right:
            st.text_input("pos_id 検索", key="pos_search")

        # load
        posviews: List[PosView] = []
        issues: List[str] = []
        mode_label = ""

        if use_json and selected_json:
            audit_obj = load_json(selected_json)
            if not audit_obj:
                st.error("JSONが読めません（壊れている/形式不一致）。ログ推定に切り替えてください。")
            else:
                st.info(T("audit_json_priority"))
                # normalize JSON to meet SPEC contracts (fill missing keys, normalize issues)
                try:
                    audit_obj = normalize_daily_report_json(audit_obj)
                except Exception:
                    pass
                posviews, issues = posviews_from_audit_json(audit_obj)
                mode_label = f"JSON: {selected_json.name}"
                # Some daily_report variants don't emit top-level per_pos.
                # In that case, supplement pos_id table from the corresponding raw log day.
                if not posviews and logs_dir:
                    day8 = str(dig_first(audit_obj, ["meta", "target_day8"], default="")).strip()
                    cand_days: List[str] = []
                    if re.fullmatch(r"\d{8}", day8):
                        cand_days.append(day8)
                    if not cand_days:
                        cand_days = list_log_days(logs_dir)[:1]
                    rows: List[Dict[str, Any]] = _read_trade_rows_for_days(logs_dir, cand_days)
                    if rows:
                        pv_fb, issues_fb = posviews_from_logs(rows)
                        if pv_fb:
                            st.warning("JSONに per_pos が無いため、pos_id一覧はログ推定で補完表示しています。")
                            posviews = pv_fb
                            for it in issues_fb:
                                if it not in issues:
                                    issues.append(it)
                            mode_label = f"JSON: {selected_json.name} + LOG_FALLBACK: {','.join(cand_days)}"
        else:
            # fallback
            if not logs_dir:
                st.warning("logs/ が見つかりません。")
            else:
                # choose days to load
                days = list_log_days(logs_dir)
                pick = st.multiselect("推定対象日（ログ）", days, default=days[:7], help="JSONが無い時のみ使う推定。")
                rows: List[Dict[str, Any]] = _read_trade_rows_for_days(logs_dir, pick)
                st.warning(T("fallback_mode"))
                posviews, issues = posviews_from_logs(rows)
                mode_label = f"LOG_FALLBACK: {len(pick)} day(s)"

        st.caption(f"表示モード: {mode_label}")

        # Filter by search
        q = (st.session_state.get("pos_search") or "").strip()
        if q:
            posviews = [p for p in posviews if q in p.pos_id]

        # Summary
        st.divider()
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("TOTAL", len(posviews))
        s2.metric("OPEN", sum(1 for p in posviews if p.status == "OPEN"))
        s3.metric("CLOSED", sum(1 for p in posviews if p.status == "CLOSED"))
        s4.metric("UNKNOWN/ERROR", sum(1 for p in posviews if p.status in ("UNKNOWN", "ERROR")))

        # Table
        st.markdown("### 🧩 pos_id 一覧")
        table_rows = []
        for p in posviews:
            table_rows.append(
                {
                    "pos_id": p.pos_id,
                    "status": p.status,
                    "entry_time": p.entry_time or "-",
                    "side": p.entry_side or "-",
                    "entry_price": p.entry_price if p.entry_price is not None else np.nan,
                    "exit_time": p.exit_time or "-",
                    "exit_result": p.exit_result or "-",
                    "exit_ltp": p.exit_ltp if p.exit_ltp is not None else np.nan,
                    "ret_pct(推定)": p.ret_pct_est if p.ret_pct_est is not None else np.nan,
                    "ai_score": p.ai_score if p.ai_score is not None else np.nan,
                    "mae": p.mae if p.mae is not None else np.nan,
                    "mfe": p.mfe if p.mfe is not None else np.nan,
                    "source": p.source,
                }
            )
        dfp = pd.DataFrame(table_rows)
        if not dfp.empty:
            st.dataframe(dfp, width="stretch")
        else:
            st.info("表示対象がありません。")

        st.info("⚠️ ret_pct は **推定**（fee未加味）。SELLは符号反転。")

        # Detail viewer
        st.divider()
        st.markdown("### 🔎 詳細")
        if posviews:
            sel_pid = st.selectbox("pos_id", [p.pos_id for p in posviews], index=0)
            p = next((x for x in posviews if x.pos_id == sel_pid), None)
            if p:
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Entry**")
                    st.json(
                        {
                            "time": p.entry_time,
                            "side": p.entry_side,
                            "price": p.entry_price,
                        }
                    )
                with c2:
                    st.markdown("**Exit**")
                    st.json(
                        {
                            "time": p.exit_time,
                            "result": p.exit_result,
                            "ltp": p.exit_ltp,
                        }
                    )

                st.markdown("**Status**")
                st.code(f"{p.status}  (source={p.source})")

                st.markdown("**Estimate (fee未加味)**")
                st.code(f"ret_pct = {_format_pct(p.ret_pct_est)}  /  note: {p.notes}")

                st.markdown("**決済タイミングチャート（ローソク足）**")
                pos_chart_run = True
                if perf_mode == "lite" and HAS_PLOTLY and logs_dir:
                    pos_chart_token = (
                        f"{sel_pid}|{mode_label}|{dir_cache_token(logs_dir)}"
                        if logs_dir
                        else f"{sel_pid}|{mode_label}"
                    )
                    pos_chart_run = _heavy_render_gate(
                        section_key="pos_detail_chart",
                        render_token=pos_chart_token,
                        perf_mode=perf_mode,
                        info_text="軽量モード: 詳細チャートは手動実行です。",
                        run_label="チャートを実行",
                    )

                if not pos_chart_run:
                    st.caption("軽量モードのため、重い詳細チャートをスキップしています。")
                elif not HAS_PLOTLY:
                    st.info("Plotly未導入のため、決済チャートは表示できません。`pip install plotly` を実行してください。")
                elif not logs_dir:
                    st.info("logs/ が見つからないため、決済チャートを表示できません。")
                else:
                    dc1, dc2, dc3 = st.columns([1, 1, 1])
                    with dc1:
                        pos_tf_label = st.selectbox(
                            "足種",
                            ["1分", "3分", "5分", "15分"],
                            index=2,
                            key=f"pos_detail_tf_{sel_pid}",
                        )
                    with dc2:
                        pos_window_min = st.selectbox(
                            "ENTRY/EXITの前後レンジ(分)",
                            [30, 60, 120, 240, 480],
                            index=2,
                            key=f"pos_detail_window_{sel_pid}",
                        )
                    with dc3:
                        pos_show_all = st.toggle(
                            "他posのイベントも重ねる",
                            value=False,
                            key=f"pos_detail_show_all_{sel_pid}",
                        )

                    day_hints: List[str] = []
                    for ts_hint in [p.entry_time, p.exit_time]:
                        d8 = _day8_from_time_str(ts_hint)
                        if d8:
                            day_hints.append(d8)
                    if use_json and selected_json:
                        m_day = re.search(r"(20\d{6})", selected_json.name)
                        if m_day:
                            day_hints.append(m_day.group(1))
                    if not day_hints:
                        day_hints = list_log_days(logs_dir)[:3]

                    detail_rows = _read_trade_rows_for_days(logs_dir, day_hints[:5])
                    if not detail_rows:
                        st.info("該当日のログが不足しているため、決済チャートを表示できません。")
                    else:
                        tp_price_line, sl_price_line, tp_sl_src = infer_tp_sl_for_pos(
                            rows=detail_rows,
                            pos_id=sel_pid,
                            entry_side=p.entry_side,
                            entry_price=p.entry_price,
                            ctrl=ctrl_now,
                        )
                        price_detail_df, event_detail_df = build_trade_timeline_frames(detail_rows)
                        if price_detail_df.empty:
                            st.info("価格系列が不足しているため、決済チャートを表示できません。")
                        else:
                            pos_event_df = pd.DataFrame()
                            if isinstance(event_detail_df, pd.DataFrame) and (not event_detail_df.empty) and ("pos_id" in event_detail_df.columns):
                                pos_event_df = event_detail_df[event_detail_df["pos_id"].astype(str) == str(sel_pid)].copy()

                            if pos_event_df.empty:
                                synth_events: List[Dict[str, Any]] = []
                                et = pd.to_datetime(p.entry_time, errors="coerce")
                                xt = pd.to_datetime(p.exit_time, errors="coerce")
                                if not pd.isna(et) and (p.entry_price is not None):
                                    s = str(p.entry_side or "").upper()
                                    synth_events.append(
                                        {
                                            "time_dt": et,
                                            "event_kind": "ENTRY_BUY" if s == "BUY" else "ENTRY_SELL",
                                            "pos_id": sel_pid,
                                            "price_plot": float(p.entry_price),
                                        }
                                    )
                                if not pd.isna(xt) and (p.exit_ltp is not None):
                                    synth_events.append(
                                        {
                                            "time_dt": xt,
                                            "event_kind": "EXIT",
                                            "pos_id": sel_pid,
                                            "price_plot": float(p.exit_ltp),
                                        }
                                    )
                                if synth_events:
                                    pos_event_df = pd.DataFrame(synth_events)

                            if not pos_event_df.empty:
                                anchor_start = pd.to_datetime(pos_event_df["time_dt"], errors="coerce").min()
                                anchor_end = pd.to_datetime(pos_event_df["time_dt"], errors="coerce").max()
                            else:
                                anchor_start = pd.to_datetime(p.entry_time, errors="coerce")
                                anchor_end = pd.to_datetime(p.exit_time, errors="coerce")
                                if pd.isna(anchor_start):
                                    anchor_start = pd.to_datetime(price_detail_df["time_dt"], errors="coerce").max()
                                if pd.isna(anchor_end):
                                    anchor_end = anchor_start

                            pad = pd.Timedelta(minutes=int(pos_window_min))
                            window_start = anchor_start - pad
                            window_end = anchor_end + pad
                            price_view = price_detail_df[
                                (price_detail_df["time_dt"] >= window_start)
                                & (price_detail_df["time_dt"] <= window_end)
                            ].copy()
                            if price_view.empty:
                                price_view = price_detail_df.tail(500).copy()

                            event_view = event_detail_df.copy() if isinstance(event_detail_df, pd.DataFrame) else pd.DataFrame()
                            if not event_view.empty:
                                event_view = event_view[
                                    (event_view["time_dt"] >= window_start)
                                    & (event_view["time_dt"] <= window_end)
                                ].copy()
                                if not pos_show_all:
                                    event_view = event_view[event_view["pos_id"].astype(str) == str(sel_pid)].copy()
                            if event_view.empty and not pos_event_df.empty:
                                event_view = pos_event_df.copy()

                            pos_rule = {"1分": "1min", "3分": "3min", "5分": "5min", "15分": "15min"}.get(pos_tf_label, "5min")
                            pos_ohlc_df = build_ohlc_from_price_df(price_view, interval_rule=pos_rule, price_col="ltp")

                            fig_pos = go.Figure()
                            if not pos_ohlc_df.empty:
                                fig_pos.add_trace(
                                    go.Candlestick(
                                        x=pos_ohlc_df["time_dt"],
                                        open=pos_ohlc_df["open"],
                                        high=pos_ohlc_df["high"],
                                        low=pos_ohlc_df["low"],
                                        close=pos_ohlc_df["close"],
                                        name=f"LTP {pos_tf_label}",
                                        increasing_line_color="#d62728",
                                        decreasing_line_color="#1f77b4",
                                        increasing_fillcolor="rgba(214,39,40,0.35)",
                                        decreasing_fillcolor="rgba(31,119,180,0.35)",
                                    )
                                )
                            else:
                                fig_pos.add_trace(
                                    go.Scatter(
                                        x=price_view["time_dt"],
                                        y=price_view["ltp"],
                                        mode="lines",
                                        name="LTP",
                                        line=dict(color="#1f77b4", width=2),
                                    )
                                )

                            if tp_price_line is not None:
                                fig_pos.add_hline(
                                    y=float(tp_price_line),
                                    line=dict(color="#00CC96", width=1.6, dash="dot"),
                                    annotation_text=f"TP {_fmt_float(tp_price_line, 1)}",
                                    annotation_position="top left",
                                )
                            if sl_price_line is not None:
                                fig_pos.add_hline(
                                    y=float(sl_price_line),
                                    line=dict(color="#FF7F0E", width=1.6, dash="dot"),
                                    annotation_text=f"SL {_fmt_float(sl_price_line, 1)}",
                                    annotation_position="bottom left",
                                )

                            if not event_view.empty:
                                vb = event_view[event_view["event_kind"] == "ENTRY_BUY"]
                                vs = event_view[event_view["event_kind"] == "ENTRY_SELL"]
                                vx = event_view[event_view["event_kind"] == "EXIT"]
                                if not vb.empty:
                                    fig_pos.add_trace(
                                        go.Scatter(
                                            x=vb["time_dt"],
                                            y=vb["price_plot"],
                                            mode="markers",
                                            name="ENTRY BUY",
                                            marker=dict(color="#00CC96", symbol="triangle-up", size=11),
                                            text=vb.get("pos_id"),
                                            hovertemplate="ENTRY BUY<br>%{x}<br>price=%{y}<br>pos_id=%{text}<extra></extra>",
                                        )
                                    )
                                if not vs.empty:
                                    fig_pos.add_trace(
                                        go.Scatter(
                                            x=vs["time_dt"],
                                            y=vs["price_plot"],
                                            mode="markers",
                                            name="ENTRY SELL",
                                            marker=dict(color="#EF553B", symbol="triangle-down", size=11),
                                            text=vs.get("pos_id"),
                                            hovertemplate="ENTRY SELL<br>%{x}<br>price=%{y}<br>pos_id=%{text}<extra></extra>",
                                        )
                                    )
                                if not vx.empty:
                                    fig_pos.add_trace(
                                        go.Scatter(
                                            x=vx["time_dt"],
                                            y=vx["price_plot"],
                                            mode="markers",
                                            name="EXIT",
                                            marker=dict(color="#FFB000", symbol="x", size=11),
                                            text=vx.get("pos_id"),
                                            hovertemplate="EXIT<br>%{x}<br>price=%{y}<br>pos_id=%{text}<extra></extra>",
                                        )
                                    )

                            fig_pos.update_layout(
                                title=f"pos_id={sel_pid} / 決済タイミング（{pos_tf_label}）",
                                plot_bgcolor="rgba(0,0,0,0)",
                                paper_bgcolor="rgba(0,0,0,0)",
                                margin=dict(l=10, r=10, t=48, b=10),
                                legend=dict(orientation="h"),
                            )
                            _enable_time_price_pan_zoom(fig_pos, with_rangeslider=True, y_title="価格")
                            st.plotly_chart(fig_pos, width="stretch", config=_plotly_interactive_config())
                            src_text = "entry note" if tp_sl_src == "entry_note" else ("control estimate" if tp_sl_src == "control_estimate" else "unavailable")
                            st.caption(
                                "操作: マウスホイールでズーム / ドラッグでパン / 下のレンジスライダーで時間軸移動"
                                f" | TP/SL source={src_text}"
                            )

                if p.ai_score is not None or p.ai_pass is not None:
                    st.markdown("**AI**")
                    st.json({"score": p.ai_score, "pass": p.ai_pass})

                if p.mae is not None or p.mfe is not None:
                    st.markdown("**MAE/MFE**")
                    st.json({"mae": p.mae, "mfe": p.mfe})

        # issues
        st.divider()
        st.markdown("### 🚨 issues（pos_idジャンプ）")
        if not issues:
            st.success("issues はありません。")
        else:
            pos_in_issues = _extract_pos_ids_from_issues(issues)
            if pos_in_issues:
                st.caption("pos_id抽出 → ボタンで検索欄へ反映（ジャンプ）")
                btn_cols = st.columns(min(4, max(1, len(pos_in_issues))))
                for i, pid in enumerate(pos_in_issues):
                    with btn_cols[i % len(btn_cols)]:
                        if st.button(f"🔎 {pid}", width="stretch"):
                            st.session_state["pos_search"] = pid
                            st.rerun()

            st.markdown("**raw issues**")
            for it in issues:
                # If issue is a dict with severity, code, pos_id, message -> colorize
                if isinstance(it, dict):
                    sev = str(it.get("severity", "INFO")).upper()
                    code = it.get("code")
                    pid = it.get("pos_id")
                    msg = it.get("message") or it.get("msg") or ""
                    line = f"[{sev}]"
                    if code:
                        line += f" {code}"
                    if pid:
                        line += f" pos_id={pid}"
                    if msg:
                        line += f" — {msg}"
                    if sev in ("FATAL", "ERROR"):
                        st.error(line)
                    elif sev in ("WARN", "WARNING"):
                        st.warning(line)
                    else:
                        st.info(line)
                else:
                    st.write(f"- {it}")

    # =========================================================
    # TAB: Guide
    # =========================================================
    with tabs[tab_index["guide"]]:
        ui_manual_tab(ctrl_now, state_now, logs_dir, out_dir, main_dir, control_path, actor=change_actor)

    # =========================================================
    # TAB: Tools
    # =========================================================
    with tabs[tab_index["tools"]]:
        st.subheader("ツール・メンテナンス")
        st.caption("CLIに戻らず運用確認できるように、主要コマンドをここから実行できます。")

        st.markdown("### 🧾 バージョン・変更履歴")
        st.caption("手動で変更内容を記録します（軽量なJSONL追記のみ。動作負荷はごく小さいです）。")
        git_now = _git_snapshot(main_dir)
        v1, v2, v3, v4 = st.columns(4)
        with v1:
            st.metric("バージョン", APP_VERSION)
        with v2:
            st.metric("Gitブランチ", str(git_now.get("branch", "-")))
        with v3:
            st.metric("Gitコミット", str(git_now.get("commit", "-")))
        with v4:
            st.metric("未コミット変更", f"{int(git_now.get('dirty_files', 0))}")

        c_auth = st.session_state.get(AUTH_SESSION_KEY, {})
        change_author_default = "unknown"
        if isinstance(c_auth, dict):
            change_author_default = str(c_auth.get("username") or c_auth.get("email") or "unknown")

        lg1, lg2, lg3 = st.columns([2, 1, 1])
        with lg1:
            log_version = st.text_input("記録バージョン", value=APP_VERSION, key="tools_change_log_version")
        with lg2:
            log_type = st.selectbox(
                "種別",
                ["CODE", "CONFIG", "UI", "RISK", "INFRA", "DOC", "OTHER"],
                index=0,
                key="tools_change_log_type",
            )
        with lg3:
            log_author = st.text_input("記録者", value=change_author_default, key="tools_change_log_author")

        log_summary = st.text_area(
            "変更内容（必須）",
            value="",
            height=90,
            key="tools_change_log_summary",
            placeholder="例: Shadowの時間制約を24hへ拡張、PAPER/LIVE別成績カードを追加",
        )
        log_files = st.text_input(
            "関連ファイル（任意 / カンマ区切り）",
            value="",
            key="tools_change_log_files",
            placeholder="例: MAIN/dashboard.py, MAIN/bot.py",
        )
        lb1, lb2, lb3 = st.columns(3)
        with lb1:
            if st.button("📝 変更を記録", width="stretch", key="tools_change_log_append"):
                msg = str(log_summary).strip()
                if not msg:
                    st.error("変更内容を入力してください。")
                else:
                    files_arr = [x.strip() for x in str(log_files).split(",") if x.strip()]
                    row = {
                        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "version": str(log_version).strip() or APP_VERSION,
                        "type": str(log_type).strip().upper(),
                        "author": str(log_author).strip() or "unknown",
                        "summary": msg,
                        "files": files_arr,
                        "git_branch": str(git_now.get("branch", "-")),
                        "git_commit": str(git_now.get("commit", "-")),
                        "git_dirty_files": int(git_now.get("dirty_files", 0)),
                    }
                    ok_log, msg_log = _append_dashboard_change_log(main_dir, row)
                    if ok_log:
                        st.success(f"記録しました: {msg_log}")
                        st.rerun()
                    else:
                        st.error(f"記録失敗: {msg_log}")
        with lb2:
            if st.button("🔄 Git状態で記録", width="stretch", key="tools_change_log_gitquick"):
                row = {
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "version": APP_VERSION,
                    "type": "CODE",
                    "author": str(log_author).strip() or "unknown",
                    "summary": "Git状態スナップショット",
                    "files": [],
                    "git_branch": str(git_now.get("branch", "-")),
                    "git_commit": str(git_now.get("commit", "-")),
                    "git_dirty_files": int(git_now.get("dirty_files", 0)),
                }
                ok_log, msg_log = _append_dashboard_change_log(main_dir, row)
                if ok_log:
                    st.success(f"記録しました: {msg_log}")
                    st.rerun()
                else:
                    st.error(f"記録失敗: {msg_log}")
        with lb3:
            if st.button("🧹 履歴表示を再読込", width="stretch", key="tools_change_log_reload"):
                st.rerun()

        hist = _read_dashboard_change_log(main_dir, max_rows=200)
        if hist:
            df_hist = pd.DataFrame(hist)
            show_cols = [c for c in ["ts", "version", "type", "author", "summary", "files", "git_branch", "git_commit", "git_dirty_files"] if c in df_hist.columns]
            st.dataframe(df_hist[show_cols], width="stretch", hide_index=True)
        else:
            st.info("変更履歴はまだありません。")

        st.divider()
        st.markdown("### 🔐 ログイン監査履歴（誰が・いつ・どこから）")
        sec_cfg = _dashboard_security_dict()
        allowed_emails_cfg = _parse_security_list(sec_cfg.get("allowed_emails", sec_cfg.get("oidc_allowed_emails", [])))
        allowed_domains_cfg = _parse_security_list(sec_cfg.get("allowed_email_domains", sec_cfg.get("oidc_allowed_domains", [])))
        sa1, sa2, sa3, sa4 = st.columns(4)
        with sa1:
            st.metric("許可メール数", len(allowed_emails_cfg))
        with sa2:
            st.metric("許可ドメイン数", len(allowed_domains_cfg))
        with sa3:
            st.metric("OIDC制限", "ON" if (allowed_emails_cfg or allowed_domains_cfg) else "OFF")
        with sa4:
            st.metric("監査ログ保存先", str(dashboard_login_audit_path(main_dir).name))

        st.caption("推奨: `dashboard_security.allowed_emails` または `allowed_email_domains` を設定して、OIDC許可リストを有効化します。")

        lf1, lf2, lf3 = st.columns([1, 1, 1])
        with lf1:
            login_hist_rows = st.number_input(
                "表示件数",
                min_value=20,
                max_value=2000,
                value=200,
                step=20,
                key="tools_login_hist_rows",
            )
        with lf2:
            login_hist_filter = st.selectbox(
                "結果フィルタ",
                ["ALL", "SUCCESS_ONLY", "FAILED_ONLY"],
                index=0,
                key="tools_login_hist_filter",
            )
        with lf3:
            if st.button("ログイン履歴を再読込", width="stretch", key="tools_login_hist_reload"):
                st.rerun()

        login_hist = _read_login_audit_log(main_dir, max_rows=int(login_hist_rows))
        if login_hist_filter == "SUCCESS_ONLY":
            login_hist = [x for x in login_hist if bool(x.get("ok"))]
        elif login_hist_filter == "FAILED_ONLY":
            login_hist = [x for x in login_hist if not bool(x.get("ok"))]

        if login_hist:
            df_login_hist = pd.DataFrame(login_hist)
            login_cols = [
                c
                for c in [
                    "ts",
                    "event",
                    "ok",
                    "username",
                    "email",
                    "auth_type",
                    "provider",
                    "reason",
                    "ip",
                    "host",
                ]
                if c in df_login_hist.columns
            ]
            st.dataframe(df_login_hist[login_cols], width="stretch", hide_index=True)
            csv_login = df_login_hist.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "ログイン履歴CSVを保存",
                data=csv_login,
                file_name=f"dashboard_login_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                width="content",
                key="tools_login_hist_download",
            )
        else:
            st.info("ログイン監査履歴はまだありません。")

        st.divider()
        st.markdown("### 📡 ops_checks ステータス")
        st.caption("直近の live_preflight / run_check.sh / state_backup 実行結果を表示します。")
        _oc_data = _read_ops_checks(main_dir)
        _oc_keys = [
            ("live_preflight", LIVE_START_PREFLIGHT_MAX_AGE_MIN),
            ("run_check.sh", LIVE_START_RUNCHECK_MAX_AGE_MIN),
            ("run_check", LIVE_START_RUNCHECK_MAX_AGE_MIN),
            ("ci_check", LIVE_START_RUNCHECK_MAX_AGE_MIN),
            ("state_backup", 26 * 60),
        ]
        _oc_shown: set = set()
        _oc_cols = st.columns(4)
        _oc_col_idx = 0
        for _oc_title, _oc_max_age in _oc_keys:
            if _oc_title in _oc_shown:
                continue
            _oc_rec = _oc_data.get(_oc_title, {})
            if not isinstance(_oc_rec, dict):
                _oc_rec = {}
            if not _oc_rec:
                continue
            _oc_shown.add(_oc_title)
            _oc_ok, _oc_msg = _ops_check_fresh_ok(main_dir, [_oc_title], _oc_max_age)
            _oc_at = str(_oc_rec.get("updated_at", "-"))
            _oc_age_min = int((time.time() - float(_oc_rec.get("updated_ts", time.time()))) / 60)
            _oc_label = "✅ OK" if _oc_ok else "⚠️ 古い"
            if _oc_col_idx < 4:
                with _oc_cols[_oc_col_idx]:
                    st.metric(_oc_title, _oc_label, f"{_oc_age_min}分前")
                    st.caption(_oc_at)
                _oc_col_idx += 1
        if not _oc_shown:
            st.caption("まだ実行履歴がありません。下の `live_preflight` ボタンで実行してください。")
        # R2: alert if state backup found corrupt JSON
        _corrupt_rec = _oc_data.get("state_backup_corrupt", {})
        if isinstance(_corrupt_rec, dict) and _corrupt_rec.get("ok") is False:
            st.error(
                f"🔴 **state backup 破損検出**: `{_corrupt_rec.get('file', '?')}` が無効な JSON のためバックアップをスキップしました"
                f" ({_corrupt_rec.get('updated_at', '-')})"
            )

        st.divider()
        # R3: Audit report viewer
        st.markdown("### 📋 最新監査レポート (audit_out/)")
        _audit_out_dir = main_dir / "audit_out"
        _audit_files_daily = sorted(_audit_out_dir.glob("audit_????????.json"), reverse=True) if _audit_out_dir.exists() else []
        if _audit_files_daily:
            _latest_audit = _audit_files_daily[0]
            try:
                _ar = json.loads(_latest_audit.read_text(encoding="utf-8"))
                _ar_day = _latest_audit.stem.replace("audit_", "")
                _ar_summary = _ar.get("summary", {})
                _ar_issues = _ar.get("issues", [])
                _ar_sev = {"FATAL": 0, "ERROR": 0, "WARN": 0, "INFO": 0}
                for _i in _ar_issues:
                    _s = _i.get("severity", "INFO")
                    _ar_sev[_s] = _ar_sev.get(_s, 0) + 1
                _ar_label = "🔴 FATAL" if _ar_sev["FATAL"] else ("🟠 ERROR" if _ar_sev["ERROR"] else ("🟡 WARN" if _ar_sev["WARN"] else "✅ クリーン"))
                st.caption(f"ファイル: `{_latest_audit.name}` 　生成: {_ar.get('generated_at', '-')}")
                _arc1, _arc2, _arc3, _arc4 = st.columns(4)
                _arc1.metric("ステータス", _ar_label)
                _arc2.metric("rows", _ar_summary.get("rows", 0))
                _arc3.metric("issues", len(_ar_issues))
                _arc4.metric("open pos (log)", _ar_summary.get("paper_without_exit_n", 0))
                if _ar_issues:
                    with st.expander(f"issues 一覧 ({len(_ar_issues)}件)", expanded=bool(_ar_sev["FATAL"] or _ar_sev["ERROR"])):
                        for _i in _ar_issues:
                            _sev = _i.get("severity", "INFO")
                            _icon = {"FATAL": "🔴", "ERROR": "🟠", "WARN": "🟡", "INFO": "ℹ️"}.get(_sev, "•")
                            st.markdown(f"{_icon} **[{_sev}]** `{_i.get('code','')}` — {_i.get('message','')}")
            except Exception:
                st.caption(f"監査ファイルを読み込めません: {_latest_audit.name}")
        else:
            st.caption("まだ監査ファイルがありません。`audit.py` を実行してください。")

        st.divider()
        st.markdown("### 🛠 メンテ実行")
        t1, t2, t3, t4 = st.columns(4)
        with t1:
            if st.button("live_preflight", width="stretch"):
                p = main_dir / "tools" / "live_preflight.py"
                if p.exists():
                    _run_action_block("live_preflight", [sys.executable, str(p)], main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        with t2:
            if st.button("ci_check", width="stretch"):
                p = main_dir / "ci_check.py"
                if p.exists():
                    days = list_log_days(logs_dir) if logs_dir else []
                    cmd = [sys.executable, str(p)]
                    if days:
                        cmd.append(days[0])
                    _run_action_block("ci_check", cmd, main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        with t3:
            if st.button("run_check.sh", width="stretch"):
                p = main_dir / "run_check.sh"
                if p.exists():
                    days = list_log_days(logs_dir) if logs_dir else []
                    cmd = ["bash", str(p)]
                    if days:
                        cmd.append(days[0])
                    _run_action_block("run_check.sh", cmd, main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        with t4:
            if st.button("spec_check(strict)", width="stretch"):
                p = main_dir / "spec_check.py"
                days = list_log_days(logs_dir) if logs_dir else []
                if p.exists() and days:
                    _run_action_block("spec_check --strict", [sys.executable, str(p), days[0], "--strict"], main_dir)
                elif not days:
                    st.error("対象ログ日が見つかりません。")
                else:
                    st.error(f"見つかりません: {p}")

        st.divider()
        st.markdown("### 🔁 自動復旧（launchd）")
        st.caption("dashboard + ngrok の常駐再起動を launchd で管理します。")
        ld1, ld2, ld3 = st.columns(3)
        with ld1:
            if st.button("install dashboard launchagent", width="stretch"):
                p = main_dir / "tools" / "install_dashboard_launchagent.sh"
                if p.exists():
                    _run_action_block("install_dashboard_launchagent", ["bash", str(p)], main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        with ld2:
            if st.button("uninstall dashboard launchagent", width="stretch"):
                p = main_dir / "tools" / "uninstall_dashboard_launchagent.sh"
                if p.exists():
                    _run_action_block("uninstall_dashboard_launchagent", ["bash", str(p)], main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        with ld3:
            if st.button("launchagent status", width="stretch"):
                label = "com.ouroboros.dashboard.ngrok"
                cmd = ["launchctl", "print", f"gui/{os.getuid()}/{label}"]
                _run_action_block("launchctl status", cmd, main_dir)
        st.caption("ログ: `MAIN/ci_logs/launchd_dashboard_out.log`, `MAIN/ci_logs/launchd_dashboard_err.log`")

        st.divider()
        st.markdown("### 🔔 取引通知（ntfy/webhook）")
        st.caption("`dashboard_security` の設定を使って、ENTRY/EXIT・risk_stop・runner状態変化を通知します。")
        n1, n2, n3 = st.columns(3)
        with n1:
            notify_bootstrap_send = st.toggle(
                "初回に既存ログも通知",
                value=False,
                key="tools_notify_bootstrap_send",
            )
        with n2:
            if st.button("trade_event_notifier dry-run", width="stretch"):
                p = main_dir / "tools" / "trade_event_notifier.py"
                if p.exists():
                    cmd = [sys.executable, str(p), "--dry-run"]
                    if notify_bootstrap_send:
                        cmd.append("--bootstrap-send")
                    _run_action_block("trade_event_notifier(dry-run)", cmd, main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        with n3:
            if st.button("trade_event_notifier 実行", width="stretch"):
                p = main_dir / "tools" / "trade_event_notifier.py"
                if p.exists():
                    cmd = [sys.executable, str(p)]
                    if notify_bootstrap_send:
                        cmd.append("--bootstrap-send")
                    _run_action_block("trade_event_notifier", cmd, main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        n4, n5, n6 = st.columns(3)
        with n4:
            if st.button("install notifier launchagent", width="stretch"):
                p = main_dir / "tools" / "install_trade_notifier_launchagent.sh"
                if p.exists():
                    cmd = ["bash", str(p)]
                    if notify_bootstrap_send:
                        cmd.append("--bootstrap-send")
                    _run_action_block("install_trade_notifier_launchagent", cmd, main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        with n5:
            if st.button("uninstall notifier launchagent", width="stretch"):
                p = main_dir / "tools" / "uninstall_trade_notifier_launchagent.sh"
                if p.exists():
                    _run_action_block("uninstall_trade_notifier_launchagent", ["bash", str(p)], main_dir)
                else:
                    st.error(f"見つかりません: {p}")
        with n6:
            if st.button("notifier launchagent status", width="stretch"):
                label = "com.ouroboros.trade.notifier"
                cmd = ["launchctl", "print", f"gui/{os.getuid()}/{label}"]
                _run_action_block("launchctl notifier status", cmd, main_dir)
        st.caption("ログ: `MAIN/ci_logs/launchd_trade_notifier_out.log`, `MAIN/ci_logs/launchd_trade_notifier_err.log`")

        st.divider()
        st.markdown("### 🧪 生成済みレポート一覧")
        rep_files = collect_json_reports(out_dir)
        if rep_files:
            st.dataframe(pd.DataFrame({"file": [p.name for p in rep_files[:50]]}), width="stretch")
        else:
            st.info("JSONなし")

        st.divider()
        st.markdown("### 🧷 state.json（存在すれば表示）")
        if state_path.exists():
            try:
                st.json(load_json(state_path) or {})
            except Exception:
                st.warning("state.json を読めません。")
        else:
            st.info("state.json はありません（未作成でもOK）。")

        st.markdown("### 🧯 環境情報")
        st.code(
            f"Python: {sys.version}\n"
            f"MAIN: {get_main_dir()}\n"
            f"CONTROL: {control_path}\n"
            f"LOGS: {str(logs_dir) if logs_dir else 'NOT FOUND'}\n"
            f"REPORT_OUT: {out_dir}"
        )

    # =========================================================
    # TAB: Shadow
    # =========================================================
    with tabs[tab_index["shadow"]]:
        st.subheader("Shadow 起動/停止")
        st.caption("本番run.pyとは分離した PAPER専用インスタンスを管理します（検証用・24h回転向け）。")

        shadow_lock_dir = main_dir / ".run_lock_shadow"
        shadow_control_path = main_dir / "CONTROL_shadow.csv"
        shadow_state_path = main_dir / "state_shadow.json"
        shadow_run_log = main_dir / "run_shadow.log"
        shadow_logs_dir = main_dir.parent / "logs" / "instances" / "shadow"
        shadow_start_sh = main_dir / "tools" / "start_shadow_paper.sh"
        shadow_stop_sh = main_dir / "tools" / "stop_shadow_paper.sh"

        shadow_lock = _lock_info_by_dir(shadow_lock_dir)
        shadow_running = bool(shadow_lock.get("alive"))

        s1, s2, s3, s4 = st.columns(4)
        with s1:
            st.metric("shadow_runner", "RUNNING" if shadow_running else "STOPPED")
        with s2:
            st.metric("shadow_pid", str(shadow_lock.get("pid") or "-"))
        with s3:
            st.metric("CONTROL_shadow", "OK" if shadow_control_path.exists() else "MISSING")
        with s4:
            st.metric("state_shadow", "OK" if shadow_state_path.exists() else "MISSING")

        st.caption(
            "lock status: exists={} alive={} pid={} state={}".format(
                bool(shadow_lock.get("exists")),
                bool(shadow_lock.get("alive")),
                shadow_lock.get("pid"),
                shadow_lock.get("state") or "-",
            )
        )

        st.divider()
        st.markdown("### 🎛 Shadow 実行コントロール")
        c1, c2 = st.columns([2, 1])
        with c1:
            shadow_interval = st.number_input(
                "shadow interval (秒)",
                min_value=30,
                max_value=3600,
                value=300,
                step=30,
                key="shadow_interval_sec",
            )
            shadow_guard_ttl = st.number_input(
                "shadow 起動/停止の確認秒数 (0=無期限)",
                min_value=0,
                max_value=300,
                value=45,
                step=1,
                key="shadow_guard_ttl",
            )
        with c2:
            if st.button("stale .run_lock_shadow クリア", width="stretch", key="shadow_clear_stale_lock"):
                ok_cl, msg_cl = _clear_stale_lock_dir(shadow_lock_dir, lock_label=".run_lock_shadow")
                if ok_cl:
                    st.success(msg_cl)
                else:
                    st.warning(msg_cl)
                st.rerun()

        if shadow_running:
            _clear_guard("shadow_runner_start")
        else:
            _clear_guard("shadow_runner_stop")

        act1, act2, act3 = st.columns(3)
        with act1:
            start_armed, start_left, start_timed = _guard_status("shadow_runner_start")
            if not start_armed:
                if st.button(
                    "▶ Shadow起動 (1/2 準備)",
                    width="stretch",
                    key="shadow_start_prepare",
                    disabled=shadow_running,
                ):
                    _arm_guard("shadow_runner_start", ttl_sec=int(shadow_guard_ttl))
                    if int(shadow_guard_ttl) > 0:
                        st.warning(f"Shadow起動準備を有効化しました。{int(shadow_guard_ttl)}秒以内に `2/2 実行` を押してください。")
                    else:
                        st.warning("Shadow起動準備を有効化しました。`2/2 実行` を押してください（無期限待機）。")
                    st.rerun()
            else:
                if start_timed:
                    st.warning(f"Shadow起動確認待ち（2/2 実行）: 残り {start_left} 秒")
                else:
                    st.warning("Shadow起動確認待ち（2/2 実行）")
                if st.button(
                    "▶ Shadow起動 (2/2 実行)",
                    width="stretch",
                    type="primary",
                    key="shadow_start_execute",
                    disabled=shadow_running,
                ):
                    _clear_guard("shadow_runner_start")
                    if not shadow_start_sh.exists():
                        st.error(f"見つかりません: {shadow_start_sh}")
                    else:
                        _run_action_block(
                            "start_shadow_paper.sh",
                            ["bash", str(shadow_start_sh), str(int(shadow_interval))],
                            main_dir,
                        )
                        st.rerun()

        with act2:
            stop_armed, stop_left, stop_timed = _guard_status("shadow_runner_stop")
            if not stop_armed:
                if st.button(
                    "■ Shadow停止 (1/2 準備)",
                    width="stretch",
                    key="shadow_stop_prepare",
                    disabled=(not shadow_running),
                ):
                    _arm_guard("shadow_runner_stop", ttl_sec=int(shadow_guard_ttl))
                    if int(shadow_guard_ttl) > 0:
                        st.warning(f"Shadow停止準備を有効化しました。{int(shadow_guard_ttl)}秒以内に `2/2 実行` を押してください。")
                    else:
                        st.warning("Shadow停止準備を有効化しました。`2/2 実行` を押してください（無期限待機）。")
                    st.rerun()
            else:
                if stop_timed:
                    st.warning(f"Shadow停止確認待ち（2/2 実行）: 残り {stop_left} 秒")
                else:
                    st.warning("Shadow停止確認待ち（2/2 実行）")
                if st.button(
                    "■ Shadow停止 (2/2 実行)",
                    width="stretch",
                    key="shadow_stop_execute",
                    disabled=(not shadow_running),
                ):
                    _clear_guard("shadow_runner_stop")
                    if not shadow_stop_sh.exists():
                        st.error(f"見つかりません: {shadow_stop_sh}")
                    else:
                        _run_action_block("stop_shadow_paper.sh", ["bash", str(shadow_stop_sh)], main_dir)
                        st.rerun()

        with act3:
            if st.button("確認状態を解除", width="stretch", key="shadow_clear_guard"):
                _clear_guard("shadow_runner_start")
                _clear_guard("shadow_runner_stop")
                st.rerun()
            st.caption("Shadowは `OUROBOROS_INSTANCE=shadow` で別CONTROL・別state・別lockを使用します。")

        st.divider()
        st.markdown("### 🧾 Shadow ログ")
        l1, l2 = st.columns([1, 1])
        with l1:
            shadow_log_lines = st.number_input(
                "run_shadow.log 表示行数",
                min_value=20,
                max_value=400,
                value=80,
                step=20,
                key="shadow_run_log_lines",
            )
        with l2:
            if st.button("🔄 Shadowログ再読込", width="stretch", key="shadow_log_reload"):
                st.rerun()

        if shadow_run_log.exists():
            try:
                mtime = datetime.fromtimestamp(shadow_run_log.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                mtime = "-"
            st.caption(f"run log: {shadow_run_log} / updated: {mtime}")
            txt = _tail_text(shadow_run_log, lines=int(shadow_log_lines))
            if txt.strip():
                st.code(txt)
            else:
                st.info("run_shadow.log は空です。")
        else:
            st.info(f"run_shadow.log がありません: {shadow_run_log}")

        st.divider()
        st.markdown("### 📈 Shadow トレードログ（最新日）")
        shadow_days = list_log_days(shadow_logs_dir)
        if not shadow_days:
            st.info(f"Shadow trade_log が見つかりません: {shadow_logs_dir}")
        else:
            shadow_day = st.selectbox("対象日(YYYYMMDD)", shadow_days, index=0, key="shadow_log_day")
            shadow_csv = shadow_logs_dir / f"trade_log_{shadow_day}.csv"
            if not shadow_csv.exists():
                st.warning(f"ログが見つかりません: {shadow_csv}")
            else:
                sh_df = read_trade_log_df(shadow_csv, file_cache_token(shadow_csv))
                if sh_df.empty:
                    st.info("Shadowログは空です。")
                else:
                    st.caption(f"rows={len(sh_df)} / file={shadow_csv.name}")
                    cols = [c for c in TRADE_LOG_FIELDS if c in sh_df.columns]
                    st.dataframe(sh_df[cols].tail(20).iloc[::-1], width="stretch")


    # =========================================================
    # TAB: IBKR US株
    # =========================================================
    with tabs[tab_index["ibkr"]]:
        st.subheader("📈 IBKR — US株 自動売買")
        st.caption("IB Gateway の接続状態・ポジション・パフォーマンス・取引履歴を表示します。")

        ibkr_main_dir = main_dir
        ibkr_review_out = ibkr_main_dir / "review_out"
        ibkr_control_path = ibkr_main_dir / "IBKR_CONTROL.csv"
        ibkr_state_path = ibkr_main_dir / "ibkr_state.json"
        ibkr_logs_dir = ibkr_main_dir.parent / "logs"

        # ── 接続スナップショット ──────────────────────────────────────────
        st.markdown("### 🔌 IB Gateway 接続状態")
        today_str = datetime.now().strftime("%Y%m%d")
        snap_path = ibkr_review_out / f"ibkr_connection_{today_str}.json"

        col_snap1, col_snap2 = st.columns([3, 1])
        with col_snap2:
            if st.button("🔄 スナップショット再読込", key="ibkr_snap_reload"):
                st.rerun()

        if snap_path.exists():
            try:
                snap_data = json.loads(snap_path.read_text("utf-8"))
            except Exception:
                snap_data = {}
            gen_at = snap_data.get("generated_at_jst", "-")
            connected_ok = snap_data.get("connected", False)
            with col_snap1:
                if connected_ok:
                    st.success(f"✅ 接続OK  (更新: {gen_at}  port: {snap_data.get('port', 7497)})")
                else:
                    st.error(f"❌ 未接続  (最終確認: {gen_at})")

            # 口座サマリー
            acct_summary = snap_data.get("account_summary", {})
            acct_vals = acct_summary.get("All") or (list(acct_summary.values())[0] if acct_summary else {})
            acct_du = next(
                (v for k, v in acct_summary.items() if k.startswith("D")), {}
            )
            if acct_du:
                st.markdown("#### 口座サマリー")
                m1, m2, m3, m4 = st.columns(4)
                def _ibkr_fmt_usd(v: Any) -> str:
                    try:
                        return f"${float(v):,.0f}"
                    except Exception:
                        return str(v or "-")
                with m1:
                    st.metric("純資産 (NetLiq)", _ibkr_fmt_usd(acct_du.get("NetLiquidation")))
                with m2:
                    st.metric("余力 (AvailFunds)", _ibkr_fmt_usd(acct_du.get("AvailableFunds")))
                with m3:
                    st.metric("含み損益", _ibkr_fmt_usd(acct_vals.get("UnrealizedPnL") if acct_vals else None))
                with m4:
                    st.metric("実現損益", _ibkr_fmt_usd(acct_vals.get("RealizedPnL") if acct_vals else None))

            # ポジション
            positions = snap_data.get("positions", [])
            st.markdown("#### ポジション")
            if not positions:
                st.info("オープンポジションなし")
            else:
                pos_rows = []
                for p in positions:
                    c = p.get("contract", {})
                    pos_rows.append({
                        "銘柄": c.get("symbol", "-"),
                        "数量": p.get("position", "-"),
                        "平均取得単価": f"${float(p.get('avg_cost', 0)):.2f}" if p.get("avg_cost") else "-",
                        "現在値": f"${float(p.get('pnl_current_price', 0)):.2f}" if p.get("pnl_current_price") else "-",
                        "含み損益(USD)": f"${float(p.get('unrealized_pnl_calc', 0)):+.2f}" if p.get("unrealized_pnl_calc") is not None else "-",
                        "含み損益(JPY)": f"¥{float(p.get('unrealized_pnl_calc_jpy', 0)):+,.0f}" if p.get("unrealized_pnl_calc_jpy") is not None else "-",
                        "ステータス": p.get("pnl_calc_status", "-"),
                    })
                st.dataframe(pos_rows, width="stretch")

            # 株価スナップショット
            stock_snaps = snap_data.get("stock_snapshots", {})
            if stock_snaps:
                st.markdown("#### 株価スナップショット (遅延)")
                price_rows = []
                for sym, s in stock_snaps.items():
                    price_rows.append({
                        "銘柄": sym,
                        "bid": f"${s.get('bid') or '-'}",
                        "ask": f"${s.get('ask') or '-'}",
                        "last": f"${s.get('last') or '-'}",
                        "close": f"${s.get('close') or '-'}",
                        "status": s.get("market_data_status", "-"),
                    })
                st.dataframe(price_rows, width="stretch")
        else:
            with col_snap1:
                st.warning(f"スナップショットファイルが見つかりません: {snap_path.name}")
            st.caption("smoke test (ouroboros-ibkr-readonly-smoke.timer) が未実行の可能性があります。")

        st.divider()

        # ── Bot状態 ───────────────────────────────────────────────────────
        st.markdown("### 🤖 IBKR Bot 状態")
        if ibkr_state_path.exists():
            try:
                ibkr_state = json.loads(ibkr_state_path.read_text("utf-8"))
            except Exception:
                ibkr_state = {}
            s1, s2, s3 = st.columns(3)
            with s1:
                day_pnl = ibkr_state.get("daily_realized_pnl_usd", 0.0)
                st.metric("当日実現P&L", f"${float(day_pnl):+.2f}")
            with s2:
                st.metric("当日取引数", str(ibkr_state.get("daily_trade_count", 0)))
            with s3:
                st.metric("集計日", str(ibkr_state.get("last_trade_day", "-")))

            open_pos = ibkr_state.get("open_pos")
            if open_pos and open_pos.get("bot_managed"):
                st.markdown("**オープンポジション (Bot管理)**")
                op1, op2, op3, op4 = st.columns(4)
                with op1:
                    st.metric("銘柄", open_pos.get("symbol", "-"))
                with op2:
                    st.metric("方向", open_pos.get("side", "-"))
                with op3:
                    st.metric("取得単価", f"${float(open_pos.get('entry_price', 0)):.2f}")
                with op4:
                    st.metric("TP/SL", f"+{open_pos.get('tp_pct', '-')}% / {open_pos.get('sl_pct', '-')}%")
                st.caption(f"pos_id={open_pos.get('pos_id', '-')}  entry={open_pos.get('entry_time', '-')}")
            else:
                st.info("Botが管理するオープンポジションはありません。")
        else:
            st.info("ibkr_state.json がまだ存在しません（Bot未起動）。")

        st.divider()

        # ── 取引ログ ──────────────────────────────────────────────────────
        st.markdown("### 📝 IBKR 取引ログ")
        ibkr_log_files = sorted(ibkr_logs_dir.glob("ibkr_trade_log_*.csv"), reverse=True)
        if not ibkr_log_files:
            st.info("ibkr_trade_log_*.csv がまだありません（取引未発生）。")
        else:
            ibkr_log_days = [f.stem.replace("ibkr_trade_log_", "") for f in ibkr_log_files]
            sel_day = st.selectbox("対象日 (YYYYMMDD)", ibkr_log_days, index=0, key="ibkr_log_day_sel")
            ibkr_csv = ibkr_logs_dir / f"ibkr_trade_log_{sel_day}.csv"
            if ibkr_csv.exists():
                try:
                    ibkr_df = read_trade_log_df(ibkr_csv, file_cache_token(ibkr_csv))
                    if ibkr_df.empty:
                        st.info("ログは空です。")
                    else:
                        st.caption(f"rows={len(ibkr_df)} / {ibkr_csv.name}")
                        disp_cols = [c for c in LOG_FIELDS_ORDER if c in ibkr_df.columns] if "LOG_FIELDS_ORDER" in dir() else list(ibkr_df.columns)
                        st.dataframe(ibkr_df.tail(30).iloc[::-1], width="stretch")
                except Exception as e:
                    st.warning(f"ログ読み込みエラー: {e}")

        st.divider()

        # ── パフォーマンスチャート ────────────────────────────────────────
        st.markdown("### 📊 パフォーマンス")
        all_ibkr_logs = sorted(ibkr_logs_dir.glob("ibkr_trade_log_*.csv"))
        if all_ibkr_logs:
            _ibkr_rows = []
            for _lf in all_ibkr_logs:
                try:
                    import csv as _csv_perf
                    with open(_lf, encoding="utf-8") as _fh:
                        for _row in _csv_perf.DictReader(_fh):
                            _res = _row.get("result", "")
                            if "EXIT" in _res or _res in ("LIVE", "PAPER"):
                                _ibkr_rows.append(_row)
                except Exception:
                    pass

            if _ibkr_rows:
                import pandas as _pd_ibkr
                _df_p = _pd_ibkr.DataFrame(_ibkr_rows)
                _df_p["time"] = _pd_ibkr.to_datetime(_df_p["time"], errors="coerce")
                _df_p["price"] = _pd_ibkr.to_numeric(_df_p["price"], errors="coerce")

                # 成績サマリー
                _exits = _df_p[_df_p["result"].str.contains("EXIT", na=False)].copy()
                _tp_n = _exits["result"].str.contains("TP").sum()
                _sl_n = _exits["result"].str.contains("SL").sum()
                _to_n = _exits["result"].str.contains("TIMEOUT|STALE").sum()
                _total_exits = len(_exits)
                _wr = _tp_n / _total_exits * 100 if _total_exits > 0 else 0.0

                pc1, pc2, pc3, pc4, pc5 = st.columns(5)
                with pc1:
                    st.metric("総取引数", _total_exits)
                with pc2:
                    st.metric("TP", int(_tp_n))
                with pc3:
                    st.metric("SL", int(_sl_n))
                with pc4:
                    st.metric("TIMEOUT", int(_to_n))
                with pc5:
                    _wr_delta = None
                    st.metric("勝率", f"{_wr:.1f}%")

                # 取引結果の内訳チャート（横棒）
                if _total_exits > 0:
                    import plotly.graph_objects as _go_ibkr
                    _bar_fig = _go_ibkr.Figure(data=[
                        _go_ibkr.Bar(
                            x=[int(_tp_n), int(_sl_n), int(_to_n)],
                            y=["TP", "SL", "TIMEOUT"],
                            orientation="h",
                            marker_color=["#2ecc71", "#e74c3c", "#f39c12"],
                            text=[int(_tp_n), int(_sl_n), int(_to_n)],
                            textposition="auto",
                        )
                    ])
                    _bar_fig.update_layout(
                        height=180,
                        margin=dict(l=10, r=10, t=10, b=10),
                        xaxis_title="件数",
                        showlegend=False,
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#cccccc"),
                    )
                    st.plotly_chart(_bar_fig, use_container_width=True)

                # 日次P&Lチャート（エントリーベースで推定）
                _entry_rows = _df_p[_df_p["result"].isin(["LIVE", "PAPER"])].copy()
                _exit_rows = _exits.copy()
                if not _exit_rows.empty and "note" in _exit_rows.columns:
                    # entry_priceをnoteから抽出してP&L計算
                    def _parse_entry_price(note: str) -> float:
                        import re as _re
                        m = _re.search(r"entry_price=([\d.]+)", str(note))
                        return float(m.group(1)) if m else 0.0

                    def _parse_pnl_pct(note: str) -> float:
                        import re as _re
                        m = _re.search(r"current_fav=([-\d.]+)", str(note))
                        return float(m.group(1)) if m else 0.0

                    _exit_rows["pnl_pct"] = _exit_rows["note"].apply(_parse_pnl_pct)
                    _exit_rows["entry_price_"] = _exit_rows["note"].apply(_parse_entry_price)
                    _exit_rows["pnl_usd"] = _exit_rows.apply(
                        lambda r: r["pnl_pct"] / 100 * r["entry_price_"] if r["entry_price_"] > 0 else 0.0,
                        axis=1
                    )
                    _exit_rows["date"] = _exit_rows["time"].dt.date
                    _daily_pnl = _exit_rows.groupby("date")["pnl_usd"].sum().reset_index()
                    _daily_pnl["cumulative"] = _daily_pnl["pnl_usd"].cumsum()

                    if not _daily_pnl.empty:
                        _pnl_fig = _go_ibkr.Figure()
                        _pnl_fig.add_trace(_go_ibkr.Bar(
                            x=_daily_pnl["date"].astype(str),
                            y=_daily_pnl["pnl_usd"],
                            name="日次P&L",
                            marker_color=[
                                "#2ecc71" if v >= 0 else "#e74c3c"
                                for v in _daily_pnl["pnl_usd"]
                            ],
                        ))
                        _pnl_fig.add_trace(_go_ibkr.Scatter(
                            x=_daily_pnl["date"].astype(str),
                            y=_daily_pnl["cumulative"],
                            name="累計P&L",
                            mode="lines+markers",
                            line=dict(color="#3498db", width=2),
                            yaxis="y2",
                        ))
                        _pnl_fig.update_layout(
                            height=280,
                            margin=dict(l=10, r=10, t=30, b=10),
                            title="日次・累計 P&L (USD)",
                            yaxis=dict(title="日次 P&L ($)", tickprefix="$"),
                            yaxis2=dict(
                                title="累計 P&L ($)",
                                overlaying="y",
                                side="right",
                                tickprefix="$",
                            ),
                            legend=dict(orientation="h", y=1.1),
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            font=dict(color="#cccccc"),
                        )
                        st.plotly_chart(_pnl_fig, use_container_width=True)
            else:
                st.info("取引終了データなし（まだ取引が完結していません）。")
        else:
            st.info("取引ログがまだありません。")

        st.divider()

        # ── IBKR_CONTROL.csv 表示 ─────────────────────────────────────────
        st.markdown("### ⚙️ IBKR_CONTROL.csv 設定")
        if ibkr_control_path.exists():
            try:
                import csv as _csv_mod
                ibkr_ctrl_rows = list(_csv_mod.DictReader(open(ibkr_control_path, encoding="utf-8-sig")))
                ibkr_ctrl_df = [{"key": r.get("key",""), "value": r.get("value","")} for r in ibkr_ctrl_rows]
                st.dataframe(ibkr_ctrl_df, width="stretch")
            except Exception as e:
                st.warning(f"設定読み込みエラー: {e}")
            st.caption(f"編集: `MAIN/IBKR_CONTROL.csv`  (Bot は1分ごとに再読み込みします)")
        else:
            st.warning("IBKR_CONTROL.csv が見つかりません。")

        st.divider()

        # ── IBKRサブエージェント ────────────────────────────────────────────
        st.markdown("### 🤖 IBKRサブエージェント")
        st.caption("Mac上で稼働するIBKR専用LaunchAgent群（VM監視・LLM分析）の状態を表示します。")

        _ibkr_local_llm = ibkr_main_dir / ".local_llm" / "ibkr"
        _ibkr_gw_state_path = ibkr_review_out / "ibkr_gateway_watch_state.json"
        _ibkr_vm_sync_path = ibkr_review_out / "ibkr_vm_sync_status.json"

        _ibkr_ag_defs = [
            {
                "label": "ibkr_snapshot (vm_sync)",
                "launchd": "com.ouroboros.ibkr_snapshot",
                "schedule": "5分ごと（JST 22:00–07:00）",
                "role": "VMからibkr_state・取引ログをSSH同期",
                "status_path": _ibkr_vm_sync_path,
                "status_key": "vm_sync",
            },
            {
                "label": "ibkr_gateway_watch",
                "launchd": "com.ouroboros.ibkr.gateway.watch",
                "schedule": "5分ごと（常時）",
                "role": "VM botサービス死活監視・ntfy通知",
                "status_path": _ibkr_gw_state_path,
                "status_key": "gateway_watch",
            },
            {
                "label": "ibkr_prebrief",
                "launchd": "com.ouroboros.ibkr.prebrief",
                "schedule": "毎日 22:15 JST（Sessionプリブリーフ）",
                "role": "LLMによる取引ログ分析・当日バイアス予測",
                "status_path": None,
                "status_key": None,
            },
            {
                "label": "ibkr_review",
                "launchd": "com.ouroboros.ibkr.review",
                "schedule": "毎日 07:05 JST（Session終了後）",
                "role": "LLMによるSession振り返り・改善点抽出",
                "status_path": None,
                "status_key": None,
            },
        ]

        _ibkr_ag_rows = []
        for _ag in _ibkr_ag_defs:
            _ag_status = "-"
            _ag_at = "-"
            if _ag["status_path"] and Path(_ag["status_path"]).exists():
                try:
                    _ag_data = json.loads(Path(_ag["status_path"]).read_text("utf-8"))
                    if _ag["status_key"] == "gateway_watch":
                        _ag_ok = _ag_data.get("last_status_ok")
                        _ag_status = "✅ OK" if _ag_ok else ("⚠️ WARN" if _ag_ok is False else "-")
                        _ag_at = str(_ag_data.get("last_checked_at_jst", "-"))
                    elif _ag["status_key"] == "vm_sync":
                        _vm_svc = _ag_data.get("bot_service", "-")
                        _ag_status = "✅ active" if _vm_svc == "active" else f"⚠️ {_vm_svc}"
                        _ag_at = str(_ag_data.get("updated_at", "-"))
                except Exception:
                    pass
            _ibkr_ag_rows.append({
                "エージェント": _ag["label"],
                "スケジュール": _ag["schedule"],
                "役割": _ag["role"],
                "最終状態": _ag_status,
                "最終確認": _ag_at,
            })
        st.dataframe(_ibkr_ag_rows, width="stretch")

        _ibkr_gw_col, _ibkr_vs_col = st.columns(2)
        with _ibkr_gw_col:
            st.markdown("**Gateway Watch 状態**")
            if _ibkr_gw_state_path.exists():
                try:
                    _gw = json.loads(_ibkr_gw_state_path.read_text("utf-8"))
                    _gw_ok = _gw.get("last_status_ok")
                    if _gw_ok:
                        st.success(f"✅ Bot OK  (確認: {_gw.get('last_checked_at_jst', '-')})")
                    else:
                        st.error(f"⚠️ {_gw.get('last_reason', '?')}  (確認: {_gw.get('last_checked_at_jst', '-')})")
                    st.caption(f"issue_key={_gw.get('last_issue_key','-')}  ntfy={_gw.get('last_ntfy_result','-')}")
                except Exception:
                    st.warning("gateway_watch_state.json 読み込みエラー")
            else:
                st.info("gateway_watch_state.json なし")
        with _ibkr_vs_col:
            st.markdown("**VM Sync 状態**")
            if _ibkr_vm_sync_path.exists():
                try:
                    _vs = json.loads(_ibkr_vm_sync_path.read_text("utf-8"))
                    _vs_svc = _vs.get("bot_service", "-")
                    if _vs_svc == "active":
                        st.success(f"✅ bot_service=active  (同期: {_vs.get('updated_at', '-')})")
                    else:
                        st.warning(f"⚠️ bot_service={_vs_svc}  (同期: {_vs.get('updated_at', '-')})")
                    st.caption(f"同期ログ数: {len(_vs.get('log_files', []))}")
                except Exception:
                    st.warning("ibkr_vm_sync_status.json 読み込みエラー")
            else:
                st.info("ibkr_vm_sync_status.json なし")

        _pb_dir = _ibkr_local_llm / "prebrief"
        _pb_latest = _pb_dir / "prebrief_latest.json"
        _pb_src = _pb_latest if _pb_latest.exists() else (
            next(iter(sorted(_pb_dir.glob("prebrief_*.json"), reverse=True)), None)
            if _pb_dir.exists() else None
        )
        st.markdown("**最新プリブリーフ (22:15 JST)**")
        if _pb_src:
            try:
                _pb = json.loads(_pb_src.read_text("utf-8"))
                st.caption(f"生成: {_pb.get('generated_at', '-')}  取引数: {_pb.get('trade_count', 0)}  モデル: {_pb.get('model', '-')}")
                _pb_text = _pb.get("llm_text", "")
                if _pb_text and not _pb_text.startswith("[LLM"):
                    st.info(_pb_text)
                else:
                    st.caption(f"LLMテキスト: {_pb_text or '(なし)'}")
            except Exception:
                st.warning("prebrief JSON 読み込みエラー")
        else:
            st.caption("プリブリーフなし（22:15 JST 実行待ちまたは取引データ不足）")

        _rv_dir = _ibkr_local_llm / "review"
        _rv_latest = _rv_dir / "review_latest.json"
        _rv_src = _rv_latest if _rv_latest.exists() else (
            next(iter(sorted(_rv_dir.glob("review_*.json"), reverse=True)), None)
            if _rv_dir.exists() else None
        )
        st.markdown("**最新セッションレビュー (07:05 JST)**")
        if _rv_src:
            try:
                _rv = json.loads(_rv_src.read_text("utf-8"))
                _rv_sum = _rv.get("summary", {})
                _rv_n = _rv_sum.get("n", 0)
                _rv_wr = float(_rv_sum.get("wr", 0.0))
                _rv_pnl = float(_rv_sum.get("total_pnl_usd", 0.0))
                st.caption(f"生成: {_rv.get('generated_at', '-')}  取引: {_rv_n}件  WR: {_rv_wr:.1%}  P&L: ${_rv_pnl:+.2f}")
                _rv_text = _rv.get("llm_text", "")
                if _rv_text and not _rv_text.startswith("["):
                    st.info(_rv_text)
                else:
                    st.caption(f"LLMテキスト: {_rv_text or '(なし)'}")
            except Exception:
                st.warning("review JSON 読み込みエラー")
        else:
            st.caption("レビューなし（07:05 JST 実行待ちまたは取引データ不足）")

        with st.expander("📄 エージェントログ（最新10行）", expanded=False):
            _ibkr_log_map = {
                "gateway_watch (out)": ibkr_review_out / "ibkr_gateway_watch.launchagent.out.log",
                "vm_sync (out)": ibkr_review_out / "ibkr_snapshot_launchd.out.log",
                "prebrief (out)": ibkr_main_dir / "ci_logs" / "ibkr_prebrief_out.log",
                "review (out)": ibkr_main_dir / "ci_logs" / "ibkr_review_out.log",
            }
            for _log_name, _log_path in _ibkr_log_map.items():
                if _log_path.exists():
                    _log_lines = _log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    st.markdown(f"**{_log_name}**")
                    st.code("\n".join(_log_lines[-10:]) if _log_lines else "(空)", language=None)


if __name__ == "__main__":
    main()
