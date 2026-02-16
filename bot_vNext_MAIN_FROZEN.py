# ============================================================
# bot.py vNext 完全統合版（メイン確定・置換用）
# PAPER運用 + AI + 学習CSV完全対応 + 将来実弾移行準備
# ============================================================
# 目的：
#   - 既存挙動（NEWSブロック / OBSERVE_ONLY / 日次上限 / 13時禁止 / スプレッドSKIP / ONE_POSITION_ONLY）を維持
#   - BUY/SELL 分離TP（BUY=0.155%, SELL=0.18%）
#   - SL共通（変更しやすい）
#   - SELLだけ fast MA 乖離フィルタ（基準=fast MA）
#   - open_pos の TP/SL/TIMEOUT 判定をbot側で実施
#   - TIMEOUTの扱いを「IGNORE/EXTEND/PARTIAL」から選べる（best_fav / extend_countを保存・ログnoteに残す）
#   - ログは必ず ../logs/trade_log_YYYYMMDD.csv に集約
#   - SMAは state に保持（ltp_history）→ 毎回 signal を確実に出す
#   - pos_id を厳格発行し、PAPER/PAPER_EXIT/HOLD note に強制埋め込み＆CSV列(pos_id)にも強制
#   - auto_tune結果を安全反映（現状は WIN のみ上書き可能）＋ 不適用理由ログ
#   - 日次ROLLBACK：前日成績悪化なら tune_override.enabled を自動OFF
#   - v3-A対応：botが読み込んだCONTROLを state.json の _control_snapshot に保存（毎回）
#   - ★A案：15:59:30以降 open_pos があれば強制クローズ（PAPER_EXIT_EOD）
#
# 追加（AI統合）：
#   - Dashboard が編集する ai_model.json を bot が読み、ON/OFF・モード・閾値・適用ポイントを切替
#   - AIは安全装置より弱い（NEWS/時間外/ティッカー不完全/スプレッド等のHard Blockが最優先）
#   - AIモードは内部的に SCORE_ONLY / VETO / GATE へ正規化（ai_model.jsonは OFF/ADVISORY/FILTER/DECISION）
#   - entry/extend など適用ポイントを ai_model.json の decision_points で切替可能
#
# 起動（例：1分おきなどで定期実行）
#   cd /Users/tani/trading_bot/trading_bot/MAIN
#   python3 bot.py
# ============================================================

import json
import csv
import re
import math
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from urllib.request import urlopen
from collections import deque
from typing import Optional, Tuple, Dict, Any, List

# =========================
# パス（Dashboardと合わせる）
# =========================
MAIN_DIR = Path(__file__).resolve().parent
STATE_FILE = MAIN_DIR / "state.json"
NEWS_BLOCK_FILE = MAIN_DIR / "news_block.csv"
CONTROL_CSV_FILE = MAIN_DIR / "CONTROL.csv"
AI_TRAINING_LOG_FILE = MAIN_DIR / "ai_training_log.csv"  # AI学習ログ（必ずここに作る）
TUNE_OVERRIDE_FILE = MAIN_DIR / "tune_override.json"
AI_MODEL_JSON_FILE = MAIN_DIR / "ai_model.json"  # Dashboardが編集するAI設定（無くてもOK）

# =========================
# pos_id 仕様（daily_report strict に合わせる）
# strict: pos_id=YYYYMMDD-HHMMSS-AAA-999  （TAGは英字）
# =========================
POS_ID_TAG_MAXLEN = 10
_POS_ID_STRICT_RE = re.compile(r"\bpos_id=([0-9]{8}-[0-9]{6}-[A-Z]+-\d{3})\b")


def _norm_tag(tag: str) -> str:
    t = (tag or "").strip().upper()
    t = re.sub(r"[^A-Z]", "", t)  # 英字だけ（strict死活）
    t = t[:POS_ID_TAG_MAXLEN] if t else "NA"
    return t


def make_pos_id(dt: datetime, tag: str, seq: int) -> str:
    """pos_id=YYYYMMDD-HHMMSS-TAG-999 を生成する唯一の関数"""
    ymd_hms = dt.strftime("%Y%m%d-%H%M%S")
    tag_u = _norm_tag(tag)
    s = int(seq)
    if s < 0:
        s = 0
    return f"{ymd_hms}-{tag_u}-{s:03d}"


def embed_pos_id(note: Optional[str], pos_id: Optional[str]) -> str:
    """
    note へ pos_id=... を埋め込む唯一の関数
    - 既に厳格pos_idがあれば置換
    - pos_id= という語があるが厳格でない場合も、最初の1箇所を置換
    - 無ければ末尾に追記
    """
    base = (note or "").strip()
    if not pos_id:
        return base

    if _POS_ID_STRICT_RE.search(base):
        return _POS_ID_STRICT_RE.sub(f"pos_id={pos_id}", base)

    if "pos_id=" in base:
        parts = base.split("pos_id=", 1)
        left = parts[0].rstrip()
        right = parts[1].lstrip()
        if " " in right:
            _old, tail = right.split(" ", 1)
            tail = tail.strip()
            return f"{left} pos_id={pos_id} {tail}".strip()
        else:
            return f"{left} pos_id={pos_id}".strip()

    return (base + f" pos_id={pos_id}").strip()


# =========================
# 定数（デフォルト：CONTROLで上書き可）
# =========================
BASE_URL = "https://api.bitflyer.com"
PRODUCT = "BTC_JPY"

# 稼働時間（JST想定）
START_HOUR = 10
END_HOUR = 16  # 16は含めない（10:00-15:59）

# ★EOD 余裕あり（A案）
EOD_CUTOFF = dtime(15, 59, 30)  # 15:59:30（JST）
EOD_RESULT = "PAPER_EXIT_EOD"

# 時間帯フィルタ（PAPER禁止）
NO_PAPER_HOURS_DEFAULT = [13]  # 13時台はPAPERを出さない

# スプレッド閾値（0.05%）
SPREAD_LIMIT_PCT_DEFAULT = 0.0005  # 0.05%

# TP/SL/WIN（PAPER運用用）
BUY_TP_PCT_DEFAULT = 0.155      # %
SELL_TP_PCT_DEFAULT = 0.180     # %
SL_PCT_DEFAULT = -0.220         # %（SLは負）
WIN_MIN_DEFAULT = 120           # 分（TIMEOUTの基準）
ONE_POSITION_ONLY_DEFAULT = True

# TIMEOUTの扱い（最重要）
# 3択： "IGNORE" / "EXTEND" / "PARTIAL"
TIMEOUT_MODE_DEFAULT = "IGNORE"

# 延長ルール（TIMEOUT_MODE="EXTEND"の時だけ有効）
MAX_EXTEND_COUNT_DEFAULT = 1
EXTEND_MIN_DEFAULT = 30
EXTEND_MIN_BESTFAV_PCT_DEFAULT = 0.08

# 部分利確ルール（TIMEOUT_MODE="PARTIAL"の時だけ有効）
PARTIAL_TP_TRIGGER_PCT_DEFAULT = 0.10
PARTIAL_TP_LABEL = "PAPER_EXIT_PARTIAL_TP"

# SELL fast MA 乖離フィルタ（%）
SELL_FAST_MA_DISTANCE_PCT_DEFAULT = 0.10

# 日次PAPER上限（新規PAPERのみカウント）
MAX_TRADES_PER_DAY_DEFAULT = 50

# 取引枚数（PAPERなのでログ用）
LOT_DEFAULT = 0.001

# A運用：条件が揃ってもPAPERせず観測のみ
OBSERVE_ONLY_DEFAULT = False

# SMA（state保持）
FAST_N_DEFAULT = 5
SLOW_N_DEFAULT = 20
MAX_LTP_HISTORY_DEFAULT = 200

# tuning
TUNE_APPLY_MODE = "WIN_ONLY"

# 安全装置（推奨ON）
SAFETY_HARD_BLOCK_DEFAULT = True

# ログ列（固定：Dashboard v3-C が読む前提のまま維持）
# ★修正：ai_score 列を追加（あなたの方針/要件）
LOG_FIELDS = [
    "time",
    "result",
    "side",
    "price",
    "size",
    "ltp",
    "best_bid",
    "best_ask",
    "spread_pct",
    "limit_pct",
    "ma_fast",
    "ma_slow",
    "trend",
    "signal",
    "pos_id",
    "note",
    "ai_score",
]

# =========================
# AI（ai_model.json）デフォルト（Dashboard側と整合）
# =========================
AI_DEFAULT: Dict[str, Any] = {
    "ai_enabled": False,
    "ai_mode": "ADVISORY",  # OFF / ADVISORY / FILTER / DECISION
    "ai_weight": 0.30,
    "decision_points": {"entry": True, "exit": False, "extend": True, "skip": True},
    "confidence_threshold": {"entry": 0.65, "extend": 0.60},
    "ai_veto": {"enabled": True, "min_confidence": 0.80},
    "features": {"use_ma": True, "use_trend": True, "use_spread": True, "use_time": True, "use_recent_winrate": False},
    "model_info": {
        "type": "rule_assisted_ai",
        "version": "v1",
        "trained_on": "paper_logs_only",
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
    },
    "logging": {"log_ai_decision": True, "log_ai_score": True, "log_ai_reason": True},
}

# AI学習ログ（固定スキーマ）
AI_TRAINING_LOG_FIELDS = [
    "time",
    "pos_id",
    "phase",  # ENTRY/EXIT/HOLD etc
    "side",
    "entry_price",
    "exit_price",
    "tp_price",
    "sl_price",
    "ma_fast",
    "ma_slow",
    "trend",
    "signal",
    "ai_score",
    "ai_note",
    "best_fav",
    "extend_count",
    "outcome",
    # 学習用（ENTRYで確実ログ）
    "units",
    "spread_entry",
    "ma_gap",
    "ma_slope",
    "vol",
    "hour",
]


# =========================
# ユーティリティ
# =========================
def now_str(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M:%S")


def safe_int(x, default: int) -> int:
    try:
        return int(str(x).strip())
    except Exception:
        return default


def safe_float(x, default: float) -> float:
    try:
        return float(str(x).strip())
    except Exception:
        return default


def safe_bool(x, default: bool) -> bool:
    if x is None:
        return default
    s = str(x).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def safe_str(x, default: str = "") -> str:
    try:
        s = str(x).strip()
        return s if s != "" else default
    except Exception:
        return default


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def sigmoid(x: float) -> float:
    # 数値安定化
    if x >= 60:
        return 1.0
    if x <= -60:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def is_after_eod_cutoff(now: datetime) -> bool:
    # now はJST想定（このプロジェクトのログ時刻と合わせる）
    return now.time() >= EOD_CUTOFF


def _deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    # dst に src を上書き（辞書は再帰）
    out = dict(dst)
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# =========================
# AI設定（ai_model.json）
# =========================
def read_ai_model_json(path: Path) -> Dict[str, Any]:
    """
    ai_model.json を読む（無ければデフォルト）
    - 互換のため default と deep merge する
    """
    if not path.exists():
        return dict(AI_DEFAULT)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return dict(AI_DEFAULT)
        return _deep_merge(AI_DEFAULT, raw)
    except Exception:
        return dict(AI_DEFAULT)


def normalize_ai_mode(ai_mode: str) -> str:
    """
    ai_model.json: OFF/ADVISORY/FILTER/DECISION
    bot内部:       SCORE_ONLY/VETO/GATE
    """
    m = (ai_mode or "").strip().upper()
    if m == "OFF":
        return "OFF"
    if m == "ADVISORY":
        return "SCORE_ONLY"
    if m == "FILTER":
        return "VETO"
    if m == "DECISION":
        return "GATE"
    if m in ("SCORE_ONLY", "VETO", "GATE"):
        return m
    return "SCORE_ONLY"


# =========================
# CONTROL（Dashboard→bot）
# =========================
def load_control_csv(path: Path) -> Dict[str, str]:
    """CONTROL.csv（key,value）を読む"""
    if not path.exists():
        return {}
    try:
        out: Dict[str, str] = {}
        with open(path, newline="", encoding="utf-8") as f:
            r = csv.reader(f)
            for row in r:
                if not row or len(row) < 2:
                    continue
                k = str(row[0]).strip()
                v = str(row[1]).strip()
                if k.lower() == "key" and v.lower() == "value":
                    continue
                if not k:
                    continue
                out[k] = v
        return out
    except Exception:
        return {}


def save_control_snapshot_for_audit(state: dict, cfg: dict, control_path: Path, ai_cfg: dict, ai_path: Path):
    """botが読み込んだCONTROLとAI設定を state.json に保存（Dashboard突合用）"""
    try:
        state["_control_snapshot"] = {
            "saved_at_jst": now_str(datetime.now()),
            "control_path": str(control_path),
            "ai_model_path": str(ai_path),
            "control": dict(cfg),
            "ai_model": dict(ai_cfg),
        }
        save_state(state)
    except Exception:
        pass


def parse_no_paper_hours(v: str, default: list) -> list:
    """ "13" / "13,14" / "[13]" などを許容して list[int] にする """
    if v is None:
        return default
    s = str(v).strip()
    if not s:
        return default
    s = s.replace("[", "").replace("]", "")
    parts = [p.strip() for p in s.split(",") if p.strip() != ""]
    hours = []
    for p in parts:
        try:
            hours.append(int(p))
        except Exception:
            pass
    return hours if hours else default


def build_runtime_config(control: Dict[str, str], ai_model: Dict[str, Any]) -> Dict[str, Any]:
    """
    CONTROL（core）＋ ai_model.json（AI）を安全に反映してランタイム設定を作る
    """
    cfg: Dict[str, Any] = {}

    # core
    cfg["today_on"] = safe_bool(control.get("today_on"), True)
    cfg["trade_enabled"] = safe_bool(control.get("trade_enabled"), True)  # 0なら新規PAPERは出さない（観測）
    cfg["paper_mode"] = safe_bool(control.get("paper_mode"), True)
    cfg["observe_only"] = safe_bool(control.get("observe_only"), OBSERVE_ONLY_DEFAULT)

    cfg["tp_buy_pct"] = safe_float(control.get("tp_buy_pct"), BUY_TP_PCT_DEFAULT)
    cfg["tp_sell_pct"] = safe_float(control.get("tp_sell_pct"), SELL_TP_PCT_DEFAULT)
    cfg["sl_pct"] = safe_float(control.get("sl_pct"), SL_PCT_DEFAULT)
    cfg["win_min"] = safe_int(control.get("win_min"), WIN_MIN_DEFAULT)

    cfg["timeout_mode"] = (control.get("timeout_mode") or TIMEOUT_MODE_DEFAULT).strip().upper()
    if cfg["timeout_mode"] not in ("IGNORE", "EXTEND", "PARTIAL"):
        cfg["timeout_mode"] = TIMEOUT_MODE_DEFAULT

    cfg["spread_limit_pct"] = safe_float(control.get("spread_limit_pct"), SPREAD_LIMIT_PCT_DEFAULT)
    cfg["max_trades_per_day"] = safe_int(control.get("max_trades_per_day"), MAX_TRADES_PER_DAY_DEFAULT)

    cfg["one_position_only"] = safe_bool(control.get("one_position_only"), ONE_POSITION_ONLY_DEFAULT)
    cfg["no_paper_hours"] = parse_no_paper_hours(control.get("no_paper_hours"), NO_PAPER_HOURS_DEFAULT)

    cfg["sell_fast_ma_distance_pct"] = safe_float(control.get("sell_fast_ma_distance_pct"), SELL_FAST_MA_DISTANCE_PCT_DEFAULT)

    cfg["fast_n"] = safe_int(control.get("fast_n"), FAST_N_DEFAULT)
    cfg["slow_n"] = safe_int(control.get("slow_n"), SLOW_N_DEFAULT)
    cfg["max_ltp_history"] = safe_int(control.get("max_ltp_history"), MAX_LTP_HISTORY_DEFAULT)

    cfg["lot"] = safe_float(control.get("lot"), LOT_DEFAULT)

    # EXTEND/PARTIAL
    cfg["max_extend_count"] = safe_int(control.get("max_extend_count"), MAX_EXTEND_COUNT_DEFAULT)
    cfg["extend_min"] = safe_int(control.get("extend_min"), EXTEND_MIN_DEFAULT)
    cfg["extend_min_bestfav_pct"] = safe_float(control.get("extend_min_bestfav_pct"), EXTEND_MIN_BESTFAV_PCT_DEFAULT)
    cfg["partial_tp_trigger_pct"] = safe_float(control.get("partial_tp_trigger_pct"), PARTIAL_TP_TRIGGER_PCT_DEFAULT)

    # Safety
    cfg["safety_hard_block"] = safe_bool(control.get("safety_hard_block"), SAFETY_HARD_BLOCK_DEFAULT)

    # -------------------------
    # AI (ai_model.json)
    # -------------------------
    cfg["ai_model_enabled"] = bool(ai_model.get("ai_enabled", False))
    cfg["ai_model_mode_raw"] = str(ai_model.get("ai_mode", "ADVISORY"))
    cfg["ai_mode"] = normalize_ai_mode(cfg["ai_model_mode_raw"])
    cfg["ai_weight"] = clamp(safe_float(ai_model.get("ai_weight", 0.30), 0.30), 0.0, 1.0)

    dp = ai_model.get("decision_points", {}) if isinstance(ai_model.get("decision_points"), dict) else {}
    cfg["ai_dp_entry"] = bool(dp.get("entry", True))
    cfg["ai_dp_exit"] = bool(dp.get("exit", False))
    cfg["ai_dp_extend"] = bool(dp.get("extend", True))
    cfg["ai_dp_skip"] = bool(dp.get("skip", True))

    th = ai_model.get("confidence_threshold", {}) if isinstance(ai_model.get("confidence_threshold"), dict) else {}
    cfg["ai_th_entry"] = clamp(safe_float(th.get("entry", 0.65), 0.65), 0.0, 1.0)
    cfg["ai_th_extend"] = clamp(safe_float(th.get("extend", 0.60), 0.60), 0.0, 1.0)

    veto = ai_model.get("ai_veto", {}) if isinstance(ai_model.get("ai_veto"), dict) else {}
    cfg["ai_veto_enabled"] = bool(veto.get("enabled", True))
    cfg["ai_veto_min_conf"] = clamp(safe_float(veto.get("min_confidence", 0.80), 0.80), 0.0, 1.0)

    feats = ai_model.get("features", {}) if isinstance(ai_model.get("features"), dict) else {}
    cfg["ai_use_ma"] = bool(feats.get("use_ma", True))
    cfg["ai_use_trend"] = bool(feats.get("use_trend", True))
    cfg["ai_use_spread"] = bool(feats.get("use_spread", True))
    cfg["ai_use_time"] = bool(feats.get("use_time", True))
    cfg["ai_use_recent_winrate"] = bool(feats.get("use_recent_winrate", False))

    lg = ai_model.get("logging", {}) if isinstance(ai_model.get("logging"), dict) else {}
    cfg["ai_log_decision"] = bool(lg.get("log_ai_decision", True))
    cfg["ai_log_score"] = bool(lg.get("log_ai_score", True))
    cfg["ai_log_reason"] = bool(lg.get("log_ai_reason", True))

    # CONTROL で緊急上書き（任意）
    if "ai_enabled" in control:
        cfg["ai_model_enabled"] = safe_bool(control.get("ai_enabled"), cfg["ai_model_enabled"])
    if "ai_mode" in control:
        cfg["ai_mode"] = normalize_ai_mode(control.get("ai_mode"))
    if "ai_threshold" in control:
        cfg["ai_th_entry"] = clamp(safe_float(control.get("ai_threshold"), cfg["ai_th_entry"]), 0.0, 1.0)
    cfg["ai_debug"] = safe_bool(control.get("ai_debug"), False) if ("ai_debug" in control) else False

    return cfg


# =========================
# 公開API（urllib）
# =========================
def get_ticker(product_code: str = PRODUCT) -> dict:
    url = f"{BASE_URL}/v1/ticker?product_code={product_code}"
    with urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


# =========================
# state管理
# =========================
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_open_pos(state: dict) -> Optional[dict]:
    op = state.get("_open_pos")
    return op if isinstance(op, dict) else None


def set_open_pos(state: dict, pos: dict) -> None:
    state["_open_pos"] = pos
    save_state(state)


def clear_open_pos(state: dict) -> None:
    state.pop("_open_pos", None)
    save_state(state)


def trades_today(state: dict, today_str: str) -> int:
    return int(state.get(today_str, 0))


def increment_trades_today(state: dict, today_str: str) -> None:
    state[today_str] = trades_today(state, today_str) + 1
    save_state(state)


# =========================
# ログ
# =========================
def logs_dir_path() -> Path:
    return MAIN_DIR.parent / "logs"


def today_log_path(now: datetime) -> Path:
    logs_dir = logs_dir_path()
    logs_dir.mkdir(parents=True, exist_ok=True)
    day = now.strftime("%Y%m%d")
    return logs_dir / f"trade_log_{day}.csv"


def write_log(csv_path: Path, row: dict) -> None:
    file_exists = csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        # 欠損列を埋める（厳格）
        out = {k: row.get(k, "") for k in LOG_FIELDS}
        writer.writerow(out)


def make_log_trade(csv_path: Path, state: dict):
    """
    ログは必ず log_trade(row) を通す。
    - row["pos_id"] が空なら open_pos から拾う
    - note に pos_id=... を強制埋め込み
    - time が無ければ自動で入れる
    """
    def log_trade(row: dict) -> None:
        row = dict(row)

        if not row.get("time"):
            row["time"] = now_str(datetime.now())

        # pos_id 決定（row優先 → open_pos）
        pos_id = (row.get("pos_id") or "").strip()
        if not pos_id:
            op = get_open_pos(state) or {}
            pos_id = (op.get("pos_id") or "").strip()

        row["pos_id"] = pos_id or ""
        row["note"] = embed_pos_id(row.get("note"), pos_id or None)

        # ai_score は open_pos から拾えるなら拾う（ログ列を常に埋める）
        if row.get("ai_score", "") == "":
            op = get_open_pos(state) or {}
            if "ai_score" in op and op.get("ai_score") is not None:
                row["ai_score"] = op.get("ai_score")

        write_log(csv_path, row)

    return log_trade


# =========================
# 時間判定
# =========================
def is_trading_time(now: datetime) -> bool:
    return START_HOUR <= now.hour < END_HOUR


# =========================
# ニュースブロック
# =========================
def load_news_blocks() -> list:
    blocks = []
    if not NEWS_BLOCK_FILE.exists():
        return blocks
    try:
        with open(NEWS_BLOCK_FILE, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                d = (row.get("date") or "").strip()
                tf = (row.get("time_from") or "").strip()
                tt = (row.get("time_to") or "").strip()
                label = (row.get("label") or "").strip()
                if not (tf and tt and label):
                    continue
                blocks.append({"date": d, "time_from": tf, "time_to": tt, "label": label})
    except Exception:
        return []
    return blocks


def hhmm_to_minutes(s: str) -> int:
    h = int(s[0:2])
    m = int(s[3:5])
    return h * 60 + m


def is_news_block_time(now: datetime, blocks: list) -> Tuple[bool, str]:
    now_date = now.strftime("%Y-%m-%d")
    now_min = now.hour * 60 + now.minute
    for b in blocks:
        if b["date"] and b["date"] != now_date:
            continue
        a = hhmm_to_minutes(b["time_from"])
        z = hhmm_to_minutes(b["time_to"])
        if a <= now_min <= z:
            return True, b["label"]
    return False, ""


# =========================
# TP/SL 価格計算（BUY/SELL両対応 + TP分離）
# =========================
def calc_tp_sl_prices(side: str, entry_price: float, tp_pct: float, sl_pct: float) -> Tuple[float, float]:
    tp = tp_pct / 100.0
    sl = sl_pct / 100.0
    side = (side or "BUY").upper()
    if side == "BUY":
        tp_price = entry_price * (1.0 + tp)
        sl_price = entry_price * (1.0 + sl)
    else:
        tp_price = entry_price * (1.0 - tp)
        sl_price = entry_price * (1.0 - sl)  # slは負→上方向
    return tp_price, sl_price


# =========================
# SMA（state保持で毎回確定）
# =========================
def calc_ma_from_state(state: dict, ltp: float, fast_n: int, slow_n: int, max_hist: int):
    hist = deque(state.get("ltp_history", []), maxlen=max_hist)
    try:
        hist.append(float(ltp))
    except Exception:
        return None, None, "UNKNOWN", "NONE"

    state["ltp_history"] = list(hist)
    state["_last_ltp"] = float(ltp)

    def sma(values, n):
        if len(values) < n:
            return None
        v = list(values)[-n:]
        return sum(v) / n

    fast = sma(hist, fast_n)
    slow = sma(hist, slow_n)

    if fast is None or slow is None:
        return None, None, "UNKNOWN", "NONE"

    trend = "UP" if fast > slow else "DOWN" if fast < slow else "FLAT"
    signal = "BUY_CANDIDATE" if trend == "UP" else "SELL_CANDIDATE" if trend == "DOWN" else "NONE"
    return round(fast, 2), round(slow, 2), trend, signal


def ma_distance_pct(price: Optional[float], ma: Optional[float]) -> Optional[float]:
    if price is None or ma is None or ma == 0:
        return None
    return abs(price - ma) / ma * 100.0


def calc_ma_slope_from_history(state: dict, n: int = 5) -> Optional[float]:
    """
    fast MA の“傾き”の簡易尺度（%/step）
    """
    hist = state.get("ltp_history", [])
    if not isinstance(hist, list) or len(hist) < max(n, 3):
        return None
    try:
        tail = [float(x) for x in hist[-n:]]
    except Exception:
        return None
    a = tail[0]
    z = tail[-1]
    if a == 0:
        return None
    return ((z - a) / a) * 100.0 / max(1, (n - 1))


def calc_volatility_from_history(state: dict, n: int = 20) -> Optional[float]:
    """
    価格のブレ（標準偏差/平均）を % でざっくり算出（簡易ボラ）
    """
    hist = state.get("ltp_history", [])
    if not isinstance(hist, list) or len(hist) < max(n, 5):
        return None
    try:
        tail = [float(x) for x in hist[-n:]]
    except Exception:
        return None
    m = sum(tail) / len(tail)
    if m == 0:
        return None
    var = sum((x - m) ** 2 for x in tail) / len(tail)
    sd = math.sqrt(var)
    return (sd / m) * 100.0


# =========================
# best_fav（有利方向への最大伸び）
# =========================
def calc_best_fav_pct(side: str, entry: float, ltp: float) -> Optional[float]:
    if not entry or not ltp:
        return None
    side = (side or "BUY").upper()
    if side == "BUY":
        return (ltp - entry) / entry * 100.0
    else:
        return (entry - ltp) / entry * 100.0


# =========================
# AI（ローカル推論アダプタ）
# =========================
class AIAdapter:
    def build_features(
        self,
        *,
        cfg: dict,
        state: dict,
        now: datetime,
        side: str,
        ltp: float,
        best_bid: float,
        best_ask: float,
        spread_pct: float,
        ma_fast: Optional[float],
        ma_slow: Optional[float],
        trend: str,
        signal: str,
        blocked_news: bool,
    ) -> Dict[str, Any]:
        feats: Dict[str, Any] = {}
        feats["spread_pct"] = None if spread_pct is None else spread_pct * 100.0
        feats["trend"] = trend
        feats["signal"] = signal
        feats["side"] = side

        if ma_fast is not None and ma_slow is not None and ma_slow != 0:
            feats["ma_gap_pct"] = abs(ma_fast - ma_slow) / ma_slow * 100.0
        else:
            feats["ma_gap_pct"] = None

        feats["ma_slope_pct_per_step"] = calc_ma_slope_from_history(state, n=cfg.get("fast_n", FAST_N_DEFAULT))
        feats["volatility_pct"] = calc_volatility_from_history(state, n=max(20, cfg.get("slow_n", SLOW_N_DEFAULT)))
        feats["news_blocked"] = bool(blocked_news)
        feats["hour"] = now.hour
        return feats

    def score(self, feats: Dict[str, Any], cfg: dict) -> Tuple[float, Dict[str, Any]]:
        comps = {}
        x = 0.0

        sp = feats.get("spread_pct")
        if cfg.get("ai_use_spread", True) and sp is not None:
            comps["spread"] = clamp((0.06 - sp) * 20.0, -2.0, 2.0)
            x += comps["spread"]

        if cfg.get("ai_use_trend", True):
            tr = feats.get("trend")
            side = feats.get("side")
            if side == "BUY" and tr == "UP":
                comps["trend"] = 0.8
            elif side == "SELL" and tr == "DOWN":
                comps["trend"] = 0.8
            elif tr == "FLAT":
                comps["trend"] = -0.4
            else:
                comps["trend"] = -0.7
            x += comps["trend"]

        mg = feats.get("ma_gap_pct")
        if cfg.get("ai_use_ma", True) and mg is not None:
            if mg < 0.02:
                comps["ma_gap"] = -0.9
            elif mg < 0.08:
                comps["ma_gap"] = 0.4
            elif mg < 0.25:
                comps["ma_gap"] = 0.7
            else:
                comps["ma_gap"] = -0.4
            x += comps["ma_gap"]

        ms = feats.get("ma_slope_pct_per_step")
        if cfg.get("ai_use_ma", True) and ms is not None:
            side = feats.get("side")
            if side == "BUY":
                comps["ma_slope"] = clamp(ms * 8.0, -1.2, 1.2)
            else:
                comps["ma_slope"] = clamp((-ms) * 8.0, -1.2, 1.2)
            x += comps["ma_slope"]

        vol = feats.get("volatility_pct")
        if cfg.get("ai_use_ma", True) and vol is not None:
            if vol < 0.05:
                comps["volatility"] = 0.2
            elif vol < 0.25:
                comps["volatility"] = 0.0
            else:
                comps["volatility"] = -0.6
            x += comps["volatility"]

        if cfg.get("ai_use_time", True):
            hr = feats.get("hour")
            if isinstance(hr, int):
                if hr in (START_HOUR, END_HOUR - 1):
                    comps["hour"] = -0.15
                    x += comps["hour"]

        if feats.get("news_blocked"):
            comps["news"] = -2.0
            x += comps["news"]

        score = sigmoid(x)
        return score, comps

    def decide_entry(self, score: float, cfg: dict) -> Tuple[bool, str]:
        mode = (cfg.get("ai_mode") or "SCORE_ONLY").upper()
        th = float(cfg.get("ai_th_entry", 0.65))
        veto_min = float(cfg.get("ai_veto_min_conf", 0.80))

        if mode == "OFF":
            return True, "ai_off"
        if mode == "SCORE_ONLY":
            return True, f"ai_score_only score={score:.3f}"
        if mode == "VETO":
            veto_low = clamp(1.0 - veto_min, 0.0, 1.0)
            if score <= veto_low:
                return False, f"ai_veto score={score:.3f} <= low={veto_low:.3f}"
            return True, f"ai_pass(VETO) score={score:.3f}"
        if mode == "GATE":
            if score >= th:
                return True, f"ai_allow(GATE) score={score:.3f} >= th={th:.3f}"
            return False, f"ai_block(GATE) score={score:.3f} < th={th:.3f}"
        return True, f"ai_unknown_mode={mode}"

    def decide_extend(self, score: float, cfg: dict) -> Tuple[bool, str]:
        th = float(cfg.get("ai_th_extend", 0.60))
        mode = (cfg.get("ai_mode") or "SCORE_ONLY").upper()

        if mode in ("OFF",):
            return True, "ai_off"
        if mode in ("SCORE_ONLY", "VETO"):
            veto_min = float(cfg.get("ai_veto_min_conf", 0.80))
            veto_low = clamp(1.0 - veto_min, 0.0, 1.0)
            if score <= veto_low:
                return False, f"ai_veto_extend score={score:.3f} <= low={veto_low:.3f}"
            return True, f"ai_pass_extend score={score:.3f}"
        if score >= th:
            return True, f"ai_allow_extend score={score:.3f} >= th={th:.3f}"
        return False, f"ai_block_extend score={score:.3f} < th={th:.3f}"


# =========================
# AI学習ログ出力
# =========================
def ensure_ai_training_log_header() -> None:
    try:
        p = AI_TRAINING_LOG_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            try:
                if p.stat().st_size > 0:
                    return
            except Exception:
                pass
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=AI_TRAINING_LOG_FIELDS)
            w.writeheader()
    except Exception as e:
        print("[WARN] ensure_ai_training_log_header failed:", e)


def append_ai_training_log(row: dict) -> None:
    """
    AI学習用CSVに1行追記（固定スキーマ）
    """
    ensure_ai_training_log_header()
    out = {k: row.get(k, "") for k in AI_TRAINING_LOG_FIELDS}
    with open(AI_TRAINING_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=AI_TRAINING_LOG_FIELDS)
        w.writerow(out)


# =========================
# tune override（WINのみ）
# =========================
def load_tune_override_raw() -> Dict[str, Any]:
    if not TUNE_OVERRIDE_FILE.exists():
        return {}
    try:
        d = json.loads(TUNE_OVERRIDE_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _in_bounds(v: int, lo: int, hi: int) -> bool:
    try:
        return lo <= int(v) <= hi
    except Exception:
        return False


def apply_tune_override_win_only(state: dict, now: datetime, win_default: int, force_recheck: bool = False) -> Tuple[int, str]:
    day_key = now.strftime("%Y-%m-%d")

    if (not force_recheck) and state.get("_tune_day") == day_key and isinstance(state.get("_tune_win_min"), int):
        return int(state["_tune_win_min"]), ""

    win_used = win_default
    cfg = load_tune_override_raw()
    if not cfg:
        state["_tune_day"] = day_key
        state["_tune_win_min"] = int(win_used)
        save_state(state)
        return win_used, ""

    meta = cfg.get("meta") or {}
    src = meta.get("source", "tune_override.json")
    min_required = int(meta.get("min_paper_required", 0) or 0)
    paper_n_hint = int(meta.get("paper_n_hint", 0) or 0)
    disabled_reason = str(meta.get("disabled_reason", "") or "")

    enabled = bool(cfg.get("enabled", False))
    scope = (cfg.get("apply_scope") or "PAPER_ONLY").upper()

    if scope != "PAPER_ONLY":
        state["_tune_day"] = day_key
        state["_tune_win_min"] = int(win_used)
        save_state(state)
        return win_used, f"tune_seen=1 tune_enabled=0 reason=bad_scope scope={scope} source={src}"

    if not enabled:
        if not disabled_reason:
            if min_required > 0 and paper_n_hint < min_required:
                disabled_reason = f"paper_n={paper_n_hint} < min_required={min_required}"
            else:
                disabled_reason = "disabled"
        state["_tune_day"] = day_key
        state["_tune_win_min"] = int(win_used)
        save_state(state)
        return win_used, f"tune_seen=1 tune_enabled=0 reason={disabled_reason} source={src}"

    override = cfg.get("override") or {}
    if not isinstance(override, dict) or "win_min" not in override:
        state["_tune_day"] = day_key
        state["_tune_win_min"] = int(win_used)
        save_state(state)
        return win_used, f"tune_seen=1 tune_enabled=0 reason=no_win_min source={src}"

    bounds = cfg.get("bounds") or {}
    if not isinstance(bounds, dict):
        bounds = {}
    b = bounds.get("win_min") or [30, 180]
    try:
        lo, hi = int(b[0]), int(b[1])
    except Exception:
        lo, hi = 30, 180

    win_new = override.get("win_min")
    if not _in_bounds(win_new, lo, hi):
        state["_tune_day"] = day_key
        state["_tune_win_min"] = int(win_used)
        save_state(state)
        return win_used, f"tune_seen=1 tune_enabled=0 reason=out_of_bounds win={win_new} bounds=({lo},{hi}) source={src}"

    apply_once = bool(cfg.get("apply_once_per_day", True))
    last_day = state.get("_tune_last_applied_day", "")

    if (not force_recheck) and apply_once and last_day == day_key:
        if state.get("_tune_day") == day_key and isinstance(state.get("_tune_win_min"), int):
            return int(state["_tune_win_min"]), ""
        state["_tune_day"] = day_key
        state["_tune_win_min"] = int(win_used)
        save_state(state)
        return win_used, f"tune_seen=1 tune_enabled=1 tune_applied=0 reason=already_applied_today source={src}"

    win_used = int(win_new)
    state["_tune_last_applied_day"] = day_key
    state["_tune_day"] = day_key
    state["_tune_win_min"] = int(win_used)
    save_state(state)

    return win_used, f"tune_seen=1 tune_enabled=1 tune_applied=1 WIN_MIN:{win_default}->{win_used} source={src}"


# =========================
# 日次ROLLBACK
# =========================
def _read_trade_log_for_day(day8: str) -> Optional[Path]:
    p = logs_dir_path() / f"trade_log_{day8}.csv"
    return p if p.exists() else None


def _count_exit_outcomes(csv_path: Path) -> Dict[str, int]:
    c = {"TP": 0, "SL": 0, "TIMEOUT": 0, "PARTIAL_TP": 0, "EOD": 0, "EXITS": 0}
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            res = (row.get("result") or "").strip()
            if res == "PAPER_EXIT_TP":
                c["TP"] += 1
            elif res == "PAPER_EXIT_SL":
                c["SL"] += 1
            elif res == "PAPER_EXIT_TIMEOUT":
                c["TIMEOUT"] += 1
            elif res == PARTIAL_TP_LABEL:
                c["PARTIAL_TP"] += 1
            elif res == EOD_RESULT:
                c["EOD"] += 1
    c["EXITS"] = c["TP"] + c["SL"] + c["TIMEOUT"] + c["PARTIAL_TP"] + c["EOD"]
    return c


def _pct(n: int, d: int) -> float:
    if d <= 0:
        return 0.0
    return (n / d) * 100.0


def should_rollback_by_abs(exit_counts: Dict[str, int], rb: Dict[str, Any]) -> Tuple[bool, str]:
    exits = int(exit_counts.get("EXITS", 0))
    min_exits = int(rb.get("min_exits_required", 20))
    if exits < min_exits:
        return False, f"exits={exits} < min_exits_required={min_exits}"

    tp_rate = _pct(exit_counts.get("TP", 0), exits)
    sl_rate = _pct(exit_counts.get("SL", 0), exits)
    timeout_rate = _pct(exit_counts.get("TIMEOUT", 0), exits)

    tp_min = float(rb.get("tp_rate_min", 25.0))
    sl_max = float(rb.get("sl_rate_max", 15.0))
    timeout_max = float(rb.get("timeout_rate_max", 80.0))

    if tp_rate < tp_min:
        return True, f"tp_rate={tp_rate:.1f}% < tp_rate_min={tp_min:.1f}% (exits={exits})"
    if sl_rate > sl_max:
        return True, f"sl_rate={sl_rate:.1f}% > sl_rate_max={sl_max:.1f}% (exits={exits})"
    if timeout_rate > timeout_max:
        return True, f"timeout_rate={timeout_rate:.1f}% > timeout_rate_max={timeout_max:.1f}% (exits={exits})"

    return False, f"OK tp={tp_rate:.1f}% sl={sl_rate:.1f}% timeout={timeout_rate:.1f}% (exits={exits})"


def try_daily_rollback(state: dict, now: datetime) -> Tuple[bool, str]:
    day_key = now.strftime("%Y-%m-%d")
    if state.get("_rollback_checked_day") == day_key:
        return False, "already_checked_today"

    state["_rollback_checked_day"] = day_key
    save_state(state)

    raw_cfg = load_tune_override_raw()
    rb = raw_cfg.get("rollback") if isinstance(raw_cfg.get("rollback"), dict) else {}
    if not rb or not bool(rb.get("enabled", False)):
        return False, "rollback_disabled"

    if not bool(raw_cfg.get("enabled", False)):
        return False, "tune_not_enabled"

    prev_day8 = (now - timedelta(days=1)).strftime("%Y%m%d")
    p = _read_trade_log_for_day(prev_day8)
    if not p:
        return False, f"no_trade_log_for_prev_day={prev_day8}"

    counts = _count_exit_outcomes(p)

    mode = (rb.get("mode") or "ABS").upper()
    if mode != "ABS":
        return False, f"unsupported_mode={mode}"

    hit, reason = should_rollback_by_abs(counts, rb)
    if not hit:
        return False, f"no_rollback: {reason}"

    raw_cfg["enabled"] = False
    meta = raw_cfg.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        raw_cfg["meta"] = meta
    meta["disabled_reason"] = f"rollback: {reason}"
    meta["rolled_back_at"] = now_str(now)

    try:
        TUNE_OVERRIDE_FILE.write_text(json.dumps(raw_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return True, f"ROLLED_BACK: {reason}"
    except Exception as e:
        return False, f"rollback_write_failed: {e}"


# =========================
# pos_id 連番（1日内でリセット）
# =========================
def next_pos_seq(state: dict, day8: str) -> int:
    key = f"_pos_seq_{day8}"
    n = int(state.get(key, 0)) + 1
    state[key] = n
    save_state(state)
    return n


# =========================
# PAPER注文（表示だけ）
# =========================
def paper_order(product: str, side: str, size: float, price: float) -> None:
    print("\n=== PAPER ORDER ===")
    print(f"time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"product: {product}")
    print(f"side: {side}")
    print(f"size: {size}")
    print(f"price: {price}")
    print("※ 実注文はしていません")
    print("===================")


# =========================
# EOD 強制クローズ
# =========================
def force_close_eod_if_needed(
    now: datetime,
    state: dict,
    cfg: dict,
    log_trade,
    best_bid: Optional[float],
    best_ask: Optional[float],
    ltp: Optional[float],
    spread_pct_now: Optional[float],
) -> bool:
    open_pos = get_open_pos(state)
    if not open_pos:
        return False

    if not is_after_eod_cutoff(now) and now.hour < END_HOUR:
        return False

    try:
        entry_price = float(open_pos.get("entry_price"))
    except Exception:
        entry_price = None

    hit_ltp = ltp if (ltp is not None) else (entry_price if entry_price is not None else "")

    note = (
        f"EOD_FORCE_CLOSE cutoff={EOD_CUTOFF.strftime('%H:%M:%S')} "
        f"entry={open_pos.get('entry_time_jst','')} exp={open_pos.get('expiry_time_jst','')}"
    )

    pos_tune_note = (open_pos.get("tune_note") or "").strip()
    if pos_tune_note:
        note += f" {pos_tune_note}"

    ai_note = (open_pos.get("ai_note") or "").strip()
    if ai_note:
        note += f" {ai_note}"

    pos_id0 = (open_pos.get("pos_id") or "").strip()

    log_trade({
        "time": now_str(now),
        "result": EOD_RESULT,
        "side": open_pos.get("side"),
        "price": open_pos.get("entry_price"),
        "size": open_pos.get("size", cfg.get("lot", LOT_DEFAULT)),
        "ltp": hit_ltp,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_pct": "" if spread_pct_now is None else round(spread_pct_now * 100, 4),
        "limit_pct": round(cfg.get("spread_limit_pct", SPREAD_LIMIT_PCT_DEFAULT) * 100, 4),
        "ma_fast": open_pos.get("ma_fast"),
        "ma_slow": open_pos.get("ma_slow"),
        "trend": open_pos.get("trend", "UNKNOWN"),
        "signal": open_pos.get("signal", "NONE"),
        "pos_id": pos_id0,
        "note": note,
        "ai_score": open_pos.get("ai_score", ""),
    })

    print(f"[EOD] FORCE CLOSE: pos_id={pos_id0} ltp={hit_ltp}")
    clear_open_pos(state)
    return True


# =========================
# メイン
# =========================
def main():
    now = datetime.now()
    ensure_ai_training_log_header()
    csv_path = today_log_path(now)
    news_blocks = load_news_blocks()

    print("[INFO] start:", now_str(now))

    state = load_state()

    # CONTROL / AI
    control_raw = load_control_csv(CONTROL_CSV_FILE)
    ai_model = read_ai_model_json(AI_MODEL_JSON_FILE)
    cfg = build_runtime_config(control_raw, ai_model)

    # 監査スナップショット（v3-A）
    save_control_snapshot_for_audit(state, cfg, CONTROL_CSV_FILE, ai_model, AI_MODEL_JSON_FILE)

    # ログ入口
    log_trade = make_log_trade(csv_path, state)

    # AI adapter
    ai = AIAdapter()

    # ===== ticker（EOD/OPEN判定にも使う）=====
    try:
        ticker = get_ticker(PRODUCT)
        best_bid = ticker.get("best_bid")
        best_ask = ticker.get("best_ask")
        ltp = ticker.get("ltp")
    except Exception:
        best_bid = best_ask = ltp = None

    spread_pct_now = None
    if best_bid is not None and best_ask is not None and ltp:
        try:
            spread_pct_now = (best_ask - best_bid) / ltp
        except Exception:
            spread_pct_now = None

    # ===== A案：EOD強制クローズ（稼働時間外でも先に処理）=====
    if force_close_eod_if_needed(
        now=now,
        state=state,
        cfg=cfg,
        log_trade=log_trade,
        best_bid=best_bid,
        best_ask=best_ask,
        ltp=ltp,
        spread_pct_now=spread_pct_now,
    ):
        return

    # ① 稼働時間外（Hard Block）
    if not is_trading_time(now):
        log_trade({
            "time": now_str(now),
            "result": "SKIP_OUT_OF_TIME",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": "" if spread_pct_now is None else round(spread_pct_now * 100, 4),
            "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
            "note": "",
            "ai_score": "",
        })
        print("[SKIP] 稼働時間外")
        return

    # today_on OFF
    if not cfg["today_on"]:
        log_trade({
            "time": now_str(now),
            "result": "SKIP_TODAY_OFF",
            "note": "today_on=0",
            "ai_score": "",
        })
        print("[SKIP] today_on=0")
        return

    # ===== 日次ROLLBACK =====
    rolled, rb_msg = try_daily_rollback(state, now)
    if rolled:
        print(f"[ROLLBACK] {rb_msg}")

    # ===== tuning override (WIN only) =====
    win_used, tune_note = apply_tune_override_win_only(state, now, cfg["win_min"], force_recheck=True)

    # ② NEWSブロック（Hard Block）
    blocked, label = is_news_block_time(now, news_blocks)
    if blocked:
        ma_fast = ma_slow = None
        trend = "UNKNOWN"
        signal = "NONE"
        if ltp is not None:
            try:
                ma_fast, ma_slow, trend, signal = calc_ma_from_state(
                    state, ltp, cfg["fast_n"], cfg["slow_n"], cfg["max_ltp_history"]
                )
                save_state(state)
            except Exception:
                pass

        note = label
        if tune_note:
            note = f"{note} {tune_note}".strip()

        log_trade({
            "time": now_str(now),
            "result": "SKIP_NEWS",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": "" if spread_pct_now is None else round(spread_pct_now * 100, 4),
            "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": note,
            "ai_score": "",
        })
        print(f"[SKIP] news block: {label}")
        return

    # ③ ticker不完全（Hard Block）
    if best_bid is None or best_ask is None or ltp is None:
        log_trade({
            "time": now_str(now),
            "result": "SKIP_TICKER_INCOMPLETE",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": "",
            "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
            "ma_fast": "",
            "ma_slow": "",
            "trend": "UNKNOWN",
            "signal": "NONE",
            "note": tune_note or "",
            "ai_score": "",
        })
        print("[SKIP] ticker不完全")
        return

    # ★MAは1回だけ（ltp_history二重追加防止）
    ma_fast, ma_slow, trend, signal = calc_ma_from_state(
        state, ltp, cfg["fast_n"], cfg["slow_n"], cfg["max_ltp_history"]
    )
    save_state(state)

    # =========================
    # 0) open_pos があれば先に決済判定（TP/SL/TIMEOUT）
    # =========================
    open_pos = get_open_pos(state)
    if open_pos:
        side0 = (open_pos.get("side") or "BUY").upper()
        pos_id0 = (open_pos.get("pos_id") or "").strip()

        try:
            entry_price = float(open_pos.get("entry_price"))
            tp_price = float(open_pos.get("tp_price"))
            sl_price = float(open_pos.get("sl_price"))
            expiry = datetime.strptime(open_pos.get("expiry_time_jst"), "%Y-%m-%d %H:%M:%S")
        except Exception:
            log_trade({
                "time": now_str(now),
                "result": "ERROR_OPEN_POS_BROKEN",
                "ltp": ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": "" if spread_pct_now is None else round(spread_pct_now * 100, 4),
                "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
                "ma_fast": "" if ma_fast is None else ma_fast,
                "ma_slow": "" if ma_slow is None else ma_slow,
                "trend": trend,
                "signal": signal,
                "pos_id": pos_id0,
                "note": "open_pos invalid -> cleared",
                "ai_score": open_pos.get("ai_score", ""),
            })
            print("[ERROR] open_pos broken -> cleared")
            clear_open_pos(state)
            return

        bf = calc_best_fav_pct(side0, entry_price, ltp)
        best_fav = open_pos.get("best_fav", None)
        if bf is not None:
            best_fav = bf if best_fav is None else max(float(best_fav), bf)
            open_pos["best_fav"] = round(best_fav, 6)

        extend_count = int(open_pos.get("extend_count", 0))
        outcome = None
        hit_ltp = None

        # TP/SL
        if side0 == "BUY":
            if ltp >= tp_price:
                outcome = "TP"
                hit_ltp = ltp
            elif ltp <= sl_price:
                outcome = "SL"
                hit_ltp = ltp
        else:
            if ltp <= tp_price:
                outcome = "TP"
                hit_ltp = ltp
            elif ltp >= sl_price:
                outcome = "SL"
                hit_ltp = ltp

        # TIMEOUT
        if outcome is None and now >= expiry:
            timeout_mode = (open_pos.get("timeout_mode") or cfg["timeout_mode"]).upper()

            # ---- AI（extendに効かせる場合）----
            ai_score_ext = None
            ai_note_ext = ""
            ok_ai_ext = True
            why_ai_ext = ""

            ai_is_on = bool(cfg.get("ai_model_enabled", False)) and (cfg.get("ai_mode", "OFF") != "OFF")
            ai_apply_extend = bool(cfg.get("ai_dp_extend", True))

            if ai_is_on and ai_apply_extend:
                feats = ai.build_features(
                    cfg=cfg,
                    state=state,
                    now=now,
                    side=side0,
                    ltp=float(ltp),
                    best_bid=float(best_bid),
                    best_ask=float(best_ask),
                    spread_pct=float(spread_pct_now) if spread_pct_now is not None else 0.0,
                    ma_fast=ma_fast,
                    ma_slow=ma_slow,
                    trend=trend,
                    signal=signal,
                    blocked_news=False,
                )
                s, comps = ai.score(feats, cfg)
                ai_score_ext = float(s)
                ok_ai_ext, why_ai_ext = ai.decide_extend(ai_score_ext, cfg)
                if cfg.get("ai_debug", False):
                    ai_note_ext = f"AI_EXT score={ai_score_ext:.3f} why={why_ai_ext} comps={json.dumps(comps, ensure_ascii=False)}"
                else:
                    ai_note_ext = f"AI_EXT score={ai_score_ext:.3f} why={why_ai_ext}"
            # -------------------------------

            if timeout_mode == "EXTEND":
                max_ext = int(open_pos.get("max_extend_count", cfg["max_extend_count"]))
                ext_min = int(open_pos.get("extend_min", cfg["extend_min"]))
                ext_need = float(open_pos.get("extend_min_bestfav_pct", cfg["extend_min_bestfav_pct"]))

                can_extend = (extend_count < max_ext) and (best_fav is not None) and (float(best_fav) >= ext_need)

                # AIで延長を止める（安全）
                if can_extend and ai_is_on and ai_apply_extend and (ai_score_ext is not None):
                    if not ok_ai_ext:
                        can_extend = False
                        open_pos["ai_note"] = (open_pos.get("ai_note") or "").strip()
                        if ai_note_ext:
                            open_pos["ai_note"] = (open_pos["ai_note"] + " " + ai_note_ext).strip()
                        open_pos["ai_score"] = ai_score_ext

                if can_extend:
                    new_expiry_dt = expiry + timedelta(minutes=ext_min)
                    new_expiry = new_expiry_dt.strftime("%Y-%m-%d %H:%M:%S")
                    open_pos["expiry_time_jst"] = new_expiry
                    open_pos["extend_count"] = extend_count + 1

                    if ai_score_ext is not None:
                        open_pos["ai_score"] = ai_score_ext
                        open_pos["ai_note"] = (open_pos.get("ai_note") or "").strip()
                        if ai_note_ext:
                            open_pos["ai_note"] = (open_pos["ai_note"] + " " + ai_note_ext).strip()

                    set_open_pos(state, open_pos)

                    note = (
                        f"EXTENDED exp={new_expiry} best_fav={open_pos.get('best_fav')} "
                        f"extend_count={open_pos.get('extend_count')}"
                    )
                    pos_tune_note = (open_pos.get("tune_note") or "").strip()
                    if pos_tune_note:
                        note += f" {pos_tune_note}"
                    elif tune_note:
                        note += f" {tune_note}"
                    if ai_note_ext:
                        note += f" {ai_note_ext}"

                    log_trade({
                        "time": now_str(now),
                        "result": "HOLD_OPEN_POS",
                        "side": open_pos.get("side"),
                        "price": open_pos.get("entry_price"),
                        "size": open_pos.get("size", cfg["lot"]),
                        "ltp": ltp,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "spread_pct": "" if spread_pct_now is None else round(spread_pct_now * 100, 4),
                        "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
                        "ma_fast": open_pos.get("ma_fast"),
                        "ma_slow": open_pos.get("ma_slow"),
                        "trend": open_pos.get("trend", "UNKNOWN"),
                        "signal": open_pos.get("signal", "NONE"),
                        "pos_id": pos_id0,
                        "note": note,
                        "ai_score": open_pos.get("ai_score", ""),
                    })
                    print(f"[INFO] TIMEOUT->EXTEND ({ext_min}m) new_exp={new_expiry} best_fav={open_pos.get('best_fav')}")
                    return
                else:
                    outcome = "TIMEOUT"
                    hit_ltp = ltp

            elif timeout_mode == "PARTIAL":
                trig = float(open_pos.get("partial_tp_trigger_pct", cfg["partial_tp_trigger_pct"]))
                if best_fav is not None and float(best_fav) >= trig:
                    outcome = "PARTIAL_TP"
                    hit_ltp = ltp
                else:
                    outcome = "TIMEOUT"
                    hit_ltp = ltp
            else:
                outcome = "TIMEOUT"
                hit_ltp = ltp

        # 決済ログ
        if outcome:
            pos_tune_note = (open_pos.get("tune_note") or "").strip()
            pos_ai_note = (open_pos.get("ai_note") or "").strip()

            note = (
                f"entry={open_pos.get('entry_time_jst')} "
                f"tp={open_pos.get('tp_price')} sl={open_pos.get('sl_price')} exp={open_pos.get('expiry_time_jst')} "
                f"best_fav={open_pos.get('best_fav','')} extend_count={open_pos.get('extend_count',0)} hit_ltp={hit_ltp}"
            )
            if pos_tune_note:
                note += f" {pos_tune_note}"
            elif tune_note:
                note += f" {tune_note}"
            if pos_ai_note:
                note += f" {pos_ai_note}"

            result_name = PARTIAL_TP_LABEL if outcome == "PARTIAL_TP" else f"PAPER_EXIT_{outcome}"

            # AI training log（EXIT）
            append_ai_training_log({
                "time": now_str(now),
                "pos_id": pos_id0,
                "phase": "EXIT",
                "side": open_pos.get("side"),
                "entry_price": open_pos.get("entry_price"),
                "exit_price": hit_ltp,
                "tp_price": open_pos.get("tp_price"),
                "sl_price": open_pos.get("sl_price"),
                "ma_fast": open_pos.get("ma_fast"),
                "ma_slow": open_pos.get("ma_slow"),
                "trend": open_pos.get("trend"),
                "signal": open_pos.get("signal"),
                "ai_score": open_pos.get("ai_score"),
                "ai_note": open_pos.get("ai_note"),
                "best_fav": open_pos.get("best_fav"),
                "extend_count": open_pos.get("extend_count"),
                "outcome": outcome,
                "units": open_pos.get("units", ""),
                "spread_entry": open_pos.get("spread_entry", ""),
                "ma_gap": open_pos.get("ma_gap", ""),
                "ma_slope": open_pos.get("ma_slope", ""),
                "vol": open_pos.get("vol", ""),
                "hour": open_pos.get("hour", ""),
            })

            log_trade({
                "time": now_str(now),
                "result": result_name,
                "side": open_pos.get("side"),
                "price": open_pos.get("entry_price"),
                "size": open_pos.get("size", cfg["lot"]),
                "ltp": hit_ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": round(spread_pct_now * 100, 4) if spread_pct_now is not None else "",
                "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
                "ma_fast": open_pos.get("ma_fast"),
                "ma_slow": open_pos.get("ma_slow"),
                "trend": open_pos.get("trend", "UNKNOWN"),
                "signal": open_pos.get("signal", "NONE"),
                "pos_id": pos_id0,
                "note": note,
                "ai_score": open_pos.get("ai_score", ""),
            })

            print(f"[PAPER_EXIT] {outcome} ltp={hit_ltp} pos_id={pos_id0}")
            clear_open_pos(state)
            return

        # 未決済（ONE_POSITION_ONLYなら新規しない）
        if cfg["one_position_only"]:
            set_open_pos(state, open_pos)

            pos_tune_note = (open_pos.get("tune_note") or "").strip()
            pos_ai_note = (open_pos.get("ai_note") or "").strip()

            note = (
                f"open_pos (exp={open_pos.get('expiry_time_jst')}) "
                f"best_fav={open_pos.get('best_fav','')} extend_count={open_pos.get('extend_count',0)}"
            )
            if pos_tune_note:
                note += f" {pos_tune_note}"
            elif tune_note:
                note += f" {tune_note}"
            if pos_ai_note:
                note += f" {pos_ai_note}"

            log_trade({
                "time": now_str(now),
                "result": "HOLD_OPEN_POS",
                "side": open_pos.get("side"),
                "price": open_pos.get("entry_price"),
                "size": open_pos.get("size", cfg["lot"]),
                "ltp": ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": "" if spread_pct_now is None else round(spread_pct_now * 100, 4),
                "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
                "ma_fast": open_pos.get("ma_fast"),
                "ma_slow": open_pos.get("ma_slow"),
                "trend": open_pos.get("trend", "UNKNOWN"),
                "signal": open_pos.get("signal", "NONE"),
                "pos_id": pos_id0,
                "note": note,
                "ai_score": open_pos.get("ai_score", ""),
            })
            print("[INFO] HOLD_OPEN_POS: open_pos継続中（新規なし）")
            return

    # =========================
    # ここから新規判定
    # =========================

    # trade_enabled=0 は「候補があってもPAPERしない」扱い
    if not cfg["trade_enabled"]:
        note = "trade_enabled=0"
        if tune_note:
            note += f" {tune_note}"
        log_trade({
            "time": now_str(now),
            "result": "OBSERVE_TRADE_DISABLED",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": "" if spread_pct_now is None else round(spread_pct_now * 100, 4),
            "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": note,
            "ai_score": "",
        })
        print("[INFO] trade_enabled=0（新規PAPERなし）")
        return

    # ④ スプレッド判定（Hard Block）
    if spread_pct_now is None or spread_pct_now >= cfg["spread_limit_pct"]:
        log_trade({
            "time": now_str(now),
            "result": "SKIP_SPREAD",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": "" if spread_pct_now is None else round(spread_pct_now * 100, 4),
            "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": tune_note or "",
            "ai_score": "",
        })
        print(f"[SKIP] spreadが広い: {(spread_pct_now*100):.4f}%" if spread_pct_now is not None else "[SKIP] spread_pct計算不可")
        return

    # ⑤ signal=NONE なら観測ログ
    if signal == "NONE":
        log_trade({
            "time": now_str(now),
            "result": "OBSERVE_NO_SIGNAL",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": round(spread_pct_now * 100, 4),
            "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": tune_note or "",
            "ai_score": "",
        })
        print("[INFO] OBSERVE_NO_SIGNAL: 候補なし（記録のみ）")
        return

    # ⑥ 1日回数制限（新規PAPERのみ制限）
    today_str = now.strftime("%Y-%m-%d")
    if trades_today(state, today_str) >= cfg["max_trades_per_day"]:
        log_trade({
            "time": now_str(now),
            "result": "SKIP_DAILY_LIMIT",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": round(spread_pct_now * 100, 4),
            "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": tune_note or "",
            "ai_score": "",
        })
        print("[SKIP] 本日の上限に達しています")
        return

    # ⑦ OBSERVE_ONLY（候補ありでも注文しない）
    if cfg["observe_only"]:
        log_trade({
            "time": now_str(now),
            "result": "OBSERVE_OK",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": round(spread_pct_now * 100, 4),
            "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": tune_note or "",
            "ai_score": "",
        })
        print("[INFO] OBSERVE_ONLY: 記録のみ（注文なし）")
        return

    # 時間帯フィルタ（PAPER禁止）
    if now.hour in cfg["no_paper_hours"]:
        note = "no_paper_hour"
        if tune_note:
            note += f" {tune_note}"
        log_trade({
            "time": now_str(now),
            "result": "OBSERVE_TIME_BLOCK",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": round(spread_pct_now * 100, 4),
            "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": note,
            "ai_score": "",
        })
        print("[INFO] OBSERVE_TIME_BLOCK: PAPER禁止時間帯")
        return

    # SELL fast MA 乖離フィルタ
    if signal == "SELL_CANDIDATE":
        dist = ma_distance_pct(ltp, ma_fast)
        if dist is None or dist < cfg["sell_fast_ma_distance_pct"]:
            note = f"fast_ma_dist={'' if dist is None else round(dist,4)}% < {cfg['sell_fast_ma_distance_pct']}%"
            if tune_note:
                note += f" {tune_note}"
            log_trade({
                "time": now_str(now),
                "result": "OBSERVE_SELL_FAST_MA_NEAR",
                "ltp": ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": round(spread_pct_now * 100, 4),
                "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
                "ma_fast": "" if ma_fast is None else ma_fast,
                "ma_slow": "" if ma_slow is None else ma_slow,
                "trend": trend,
                "signal": signal,
                "note": note,
                "ai_score": "",
            })
            print(f"[INFO] OBSERVE_SELL_FAST_MA_NEAR: dist={dist}")
            return

    # =========================
    # AI判定（entry）
    # =========================
    side = "BUY" if signal == "BUY_CANDIDATE" else "SELL"

    ai_score = None
    ai_note = ""
    ok_ai = True
    why_ai = ""

    ai_is_on = bool(cfg.get("ai_model_enabled", False)) and (cfg.get("ai_mode", "OFF") != "OFF")
    ai_apply_entry = bool(cfg.get("ai_dp_entry", True))

    if ai_is_on and ai_apply_entry:
        feats = ai.build_features(
            cfg=cfg,
            state=state,
            now=now,
            side=side,
            ltp=float(ltp),
            best_bid=float(best_bid),
            best_ask=float(best_ask),
            spread_pct=float(spread_pct_now) if spread_pct_now is not None else 0.0,
            ma_fast=ma_fast,
            ma_slow=ma_slow,
            trend=trend,
            signal=signal,
            blocked_news=False,
        )
        s, comps = ai.score(feats, cfg)
        ai_score = float(s)
        ok_ai, why_ai = ai.decide_entry(ai_score, cfg)

        if cfg.get("ai_debug", False):
            ai_note = f"AI score={ai_score:.3f} why={why_ai} comps={json.dumps(comps, ensure_ascii=False)}"
        else:
            ai_note = f"AI score={ai_score:.3f} why={why_ai}"

        if not ok_ai:
            note = f"AI_BLOCK {ai_note}".strip()
            if tune_note:
                note += f" {tune_note}"
            log_trade({
                "time": now_str(now),
                "result": "OBSERVE_AI_BLOCK",
                "ltp": ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": round(spread_pct_now * 100, 4),
                "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
                "ma_fast": "" if ma_fast is None else ma_fast,
                "ma_slow": "" if ma_slow is None else ma_slow,
                "trend": trend,
                "signal": signal,
                "note": note,
                "ai_score": ai_score,
            })
            print("[INFO] AI_BLOCK: 新規PAPER見送り")
            return

    # --- 学習向け：ENTRY特徴量（必ず算出） ---
    units = int(round(float(cfg["lot"]) / 0.001))  # 0.001を1単位
    spread_entry = (spread_pct_now * 100.0) if (spread_pct_now is not None) else None

    ma_gap = None
    if ma_fast is not None and ma_slow is not None and ma_slow != 0:
        ma_gap = abs(ma_fast - ma_slow) / ma_slow * 100.0

    ma_slope = calc_ma_slope_from_history(state, n=cfg.get("fast_n", FAST_N_DEFAULT))
    vol = calc_volatility_from_history(state, n=max(20, cfg.get("slow_n", SLOW_N_DEFAULT)))
    hour = now.hour

    # ⑨ 新規 PAPER
    entry_price = best_bid if side == "BUY" else best_ask
    tp_pct = cfg["tp_buy_pct"] if side == "BUY" else cfg["tp_sell_pct"]
    tp_price, sl_price = calc_tp_sl_prices(side, entry_price, tp_pct, cfg["sl_pct"])
    expiry_time = (now + timedelta(minutes=win_used)).strftime("%Y-%m-%d %H:%M:%S")

    day8 = now.strftime("%Y%m%d")
    seq = next_pos_seq(state, day8)
    pos_id = make_pos_id(now, tag=side, seq=seq)

    paper_order(PRODUCT, side, cfg["lot"], entry_price)

    # open_pos を先に確定（この時点で log_trade が pos_id を拾える）
    set_open_pos(state, {
        "pos_id": pos_id,
        "entry_time_jst": now_str(now),
        "side": side,
        "entry_price": float(entry_price),
        "tp_price": round(tp_price, 1),
        "sl_price": round(sl_price, 1),
        "expiry_time_jst": expiry_time,
        "trend": trend,
        "signal": signal,
        "ma_fast": ma_fast,
        "ma_slow": ma_slow,
        "tp_pct": tp_pct,
        "sl_pct": cfg["sl_pct"],
        "best_fav": 0.0,
        "extend_count": 0,
        "tune_note": tune_note or "",
        "win_used": int(win_used),
        "timeout_mode": cfg["timeout_mode"],
        "max_extend_count": cfg["max_extend_count"],
        "extend_min": cfg["extend_min"],
        "extend_min_bestfav_pct": cfg["extend_min_bestfav_pct"],
        "partial_tp_trigger_pct": cfg["partial_tp_trigger_pct"],
        "size": float(cfg["lot"]),
        "ai_score": ai_score,
        "ai_note": ai_note,
        # 学習用（ENTRYで確実に入る）
        "units": units,
        "spread_entry": "" if spread_entry is None else round(spread_entry, 6),
        "ma_gap": "" if ma_gap is None else round(ma_gap, 6),
        "ma_slope": "" if ma_slope is None else round(ma_slope, 6),
        "vol": "" if vol is None else round(vol, 6),
        "hour": hour,
    })

    # ENTRY学習ログ（ENTRYで確実に残す）
    append_ai_training_log({
        "time": now_str(now),
        "pos_id": pos_id,
        "phase": "ENTRY",
        "side": side,
        "entry_price": float(entry_price),
        "exit_price": "",
        "tp_price": round(tp_price, 1),
        "sl_price": round(sl_price, 1),
        "ma_fast": ma_fast,
        "ma_slow": ma_slow,
        "trend": trend,
        "signal": signal,
        "ai_score": ai_score,
        "ai_note": ai_note,
        "best_fav": 0.0,
        "extend_count": 0,
        "outcome": "",
        "units": units,
        "spread_entry": "" if spread_entry is None else round(spread_entry, 6),
        "ma_gap": "" if ma_gap is None else round(ma_gap, 6),
        "ma_slope": "" if ma_slope is None else round(ma_slope, 6),
        "vol": "" if vol is None else round(vol, 6),
        "hour": hour,
    })

    note = (
        f"tp={tp_price:.1f} sl={sl_price:.1f} "
        f"win_used={win_used}m exp={expiry_time} "
        f"tp_pct={tp_pct} sl_pct={cfg['sl_pct']} timeout_mode={cfg['timeout_mode']}"
        f" units={units}"
        f" sp_entry={'' if spread_entry is None else round(spread_entry,6)}"
        f" ma_gap={'' if ma_gap is None else round(ma_gap,6)}"
        f" ma_slope={'' if ma_slope is None else round(ma_slope,6)}"
        f" vol={'' if vol is None else round(vol,6)}"
        f" hour={hour}"
    )
    if tune_note:
        note += f" {tune_note}"
    if ai_note:
        note += f" {ai_note}"

    log_trade({
        "time": now_str(now),
        "result": "PAPER",
        "side": side,
        "price": entry_price,
        "size": cfg["lot"],
        "ltp": ltp,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_pct": round(spread_pct_now * 100, 4),
        "limit_pct": round(cfg["spread_limit_pct"] * 100, 4),
        "ma_fast": "" if ma_fast is None else ma_fast,
        "ma_slow": "" if ma_slow is None else ma_slow,
        "trend": trend,
        "signal": signal,
        "pos_id": pos_id,
        "note": note,
        "ai_score": "" if ai_score is None else ai_score,
    })

    increment_trades_today(state, today_str)


if __name__ == "__main__":
    main()
