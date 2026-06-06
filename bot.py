# ============================================================
# Project Ouroboros v1 — bot.py (MAIN)
# SPEC: SPEC_OUROBOROS_V1.md 準拠（固定契約）
# ============================================================
# - PAPER運用（実弾なし）
# - ログ契約固定（trade_log_YYYYMMDD.csv）
# - pos_id厳格発行（YYYYMMDD-HHMMSS-(BUY|SELL)-NNN）
# - state.json安全運用（破損時も継続）
# - self-heal（当日ログの壊れ行/旧形式を退避）
# - open_pos 管理（TP/SL/TIMEOUT/PARTIAL/EXTEND/EOD）
# - AI（ai_model.json）deep-merge + mode正規化 + entry/extend介入
#
# NOTE: 本botは標準出力へprintしない（SPEC準拠）
# ============================================================

import csv
import json
import math
import os
import re
import shutil
import subprocess
import time
import atexit
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.request import urlopen

from exchange.bitflyer_private import summarize_order
from exchange.client_factory import build_private_client, normalize_exchange_name
from ouroboros_contract import (
    OUROBOROS_BOT_VERSION,
    OUROBOROS_FEATURE_SCHEMA_VERSION,
    RESULT_ALLOWED,
    TRADE_LOG_FIELDS as LOG_FIELDS,
)
from tools.keychain_secret import read_pair

# -------------------------
# Paths (MAIN)
# -------------------------
MAIN_DIR = Path(__file__).resolve().parent

def _normalize_instance_name(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if not s:
        return "main"
    s = re.sub(r"[^a-z0-9_-]+", "_", s).strip("_")
    return s or "main"


def _resolve_runtime_paths(instance_name: str) -> Tuple[Path, Path, Path, Path, Path, Path]:
    is_main = (instance_name == "main")
    state_default = MAIN_DIR / ("state.json" if is_main else f"state_{instance_name}.json")
    control_default = MAIN_DIR / ("CONTROL.csv" if is_main else f"CONTROL_{instance_name}.csv")
    ai_model_default = MAIN_DIR / ("ai_model.json" if is_main else f"ai_model_{instance_name}.json")
    news_default = MAIN_DIR / "news_block.csv"
    run_lock_default = MAIN_DIR / (".run_lock" if is_main else f".run_lock_{instance_name}")
    logs_default = (MAIN_DIR.parent / "logs") if is_main else (MAIN_DIR.parent / "logs" / "instances" / instance_name)

    def _env_path(name: str, fallback: Path) -> Path:
        raw = str(os.getenv(name, "") or "").strip()
        if not raw:
            return fallback
        p = Path(raw)
        if not p.is_absolute():
            p = MAIN_DIR / p
        return p

    return (
        _env_path("OUROBOROS_STATE_PATH", state_default),
        _env_path("OUROBOROS_CONTROL_PATH", control_default),
        _env_path("OUROBOROS_AI_MODEL_PATH", ai_model_default),
        _env_path("OUROBOROS_NEWS_BLOCK_PATH", news_default),
        _env_path("OUROBOROS_RUN_LOCK_PATH", run_lock_default),
        _env_path("OUROBOROS_LOGS_DIR", logs_default),
    )


INSTANCE_NAME = _normalize_instance_name(os.getenv("OUROBOROS_INSTANCE", "main"))
STATE_FILE, CONTROL_CSV_FILE, AI_MODEL_JSON_FILE, NEWS_BLOCK_FILE, RUN_LOCK_DIR, LOGS_DIR = _resolve_runtime_paths(INSTANCE_NAME)

# -------------------------
# Market (bitFlyer public API)
# -------------------------
BASE_URL = "https://api.bitflyer.com"
PRODUCT = "BTC_JPY"

# -------------------------
# Time / session (JST assumed, system local time)
# -------------------------
START_HOUR_DEFAULT = 10
END_HOUR_DEFAULT = 16   # 16 not included; normal trade window: [10:00, 15:59]
EOD_CUTOFF = dtime(15, 59, 30)

# -------------------------
# Defaults (can be overridden by CONTROL / ai_model.json)
# -------------------------
TP_BUY_PCT_DEFAULT = 0.155       # %
TP_SELL_PCT_DEFAULT = 0.180      # %
SL_PCT_DEFAULT = -0.220          # % (negative)
WIN_MIN_DEFAULT = 120            # minutes

SPREAD_LIMIT_PCT_DEFAULT = 0.0005  # 0.05% (ratio)
MAX_TRADES_PER_DAY_DEFAULT = 50
LOT_DEFAULT = 0.001

FAST_N_DEFAULT = 5
SLOW_N_DEFAULT = 20
MAX_LTP_HISTORY_DEFAULT = 200

NO_PAPER_HOURS_DEFAULT = [13]

BUY_FAST_MA_DISTANCE_PCT_DEFAULT = 0.12   # % (distance from fast MA; if too near -> observe)
SELL_FAST_MA_DISTANCE_PCT_DEFAULT = 0.10  # % (distance from fast MA; if too near -> observe)
TREND_FLIP_COOLDOWN_MIN_DEFAULT = 10      # minutes after UP/DOWN flip before allowing fresh entry
TREND_STRENGTH_FILTER_ENABLED_DEFAULT = False
TREND_STRENGTH_LOOKBACK_N_DEFAULT = 20
TREND_STRENGTH_MIN_ER_DEFAULT = 0.28
HTF15_CONTEXT_ENABLED_DEFAULT = False
HTF60_CONTEXT_ENABLED_DEFAULT = False
HTF_CONTEXT_LOOKBACK_N_DEFAULT = 8
HTF_BIAS_SLOPE_PCT_DEFAULT = 0.02
HTF60_COUNTERTREND_PENALTY_DEFAULT = 0.20
HTF15_60_CONFLICT_PENALTY_DEFAULT = 0.25
MA_CROSS_FEATURE_ENABLED_DEFAULT = True
MA_CROSS_RECENT_LOOKBACK_N_DEFAULT = 6
MA_CROSS_MIN_GAP_PCT_DEFAULT = 0.02
MA_CROSS_SLOW_SLOPE_MIN_PCT_DEFAULT = 0.0
MA_CROSS_PRICE_FILTER_ENABLED_DEFAULT = True
MA_CROSS_AI_BOOST_DEFAULT = 0.18
MA_CROSS_AI_PENALTY_DEFAULT = 0.16
TECH_INDICATORS_ENABLED_DEFAULT = True
RSI_N_DEFAULT = 14
RSI_LOW_DEFAULT = 30.0
RSI_HIGH_DEFAULT = 70.0
BB_N_DEFAULT = 20
BB_K_DEFAULT = 2.0
BW_WALK_MIN_COUNT_DEFAULT = 3        # ±2σ連続評価回数でバンドウォーク判定
BB_SQUEEZE_THRESHOLD_PCT_DEFAULT = 0.80  # bb_width_pct < この値でスクイーズ判定
ATR_N_DEFAULT = 14
ATR_LOW_PCT_DEFAULT = 0.04
ATR_HIGH_PCT_DEFAULT = 0.22
TREND_POWER_LOOKBACK_N_DEFAULT = 20
TREND_POWER_STRONG_ER_DEFAULT = 0.45
TECH_AI_BOOST_DEFAULT = 0.14
TECH_AI_PENALTY_DEFAULT = 0.18
CHART_PATTERN_ENABLED_DEFAULT = True
OHLC_TIMEFRAME_MIN_DEFAULT = 5
OHLC_MAX_BARS_DEFAULT = 200
CHART_PATTERN_MIN_BAR_TICKS_DEFAULT = 2
CHART_PATTERN_QUALITY_LOOKBACK_BARS_DEFAULT = 12
SWING_LOOKBACK_DEFAULT = 2
DOUBLE_TOP_PEAK_TOLERANCE_PCT_DEFAULT = 0.30
DOUBLE_BOTTOM_TROUGH_TOLERANCE_PCT_DEFAULT = 0.30
SHOULDER_TOLERANCE_PCT_DEFAULT = 0.50
HEAD_MIN_EXCESS_PCT_DEFAULT = 0.30
NECKLINE_BREAK_CONFIRM_BARS_DEFAULT = 1
PATTERN_AI_BOOST_DEFAULT = 0.16
PATTERN_AI_PENALTY_DEFAULT = 0.20
MARKET_PHASE_ENABLED_DEFAULT = True
MARKET_PHASE_BLOCK_B_ENABLED_DEFAULT = False
MARKET_PHASE_LOOKBACK_N_DEFAULT = 20
MARKET_PHASE_FLAT_SLOPE_PCT_DEFAULT = 0.01
MARKET_PHASE_FLAT_GAP_PCT_DEFAULT = 0.05
MARKET_PHASE_RANGE_MAX_WIDTH_PCT_DEFAULT = 0.40
MARKET_PHASE_AI_BOOST_DEFAULT = 0.18
MARKET_PHASE_AI_PENALTY_DEFAULT = 0.22
AIBA_STYLE_ENABLED_DEFAULT = True
AIBA_STYLE_AI_ENABLED_DEFAULT = False
AIBA_MA_SHORT_N_DEFAULT = 5
AIBA_MA_MID_N_DEFAULT = 20
AIBA_MA_LONG_N_DEFAULT = 60
AIBA_SLOPE_MIN_PCT_DEFAULT = 0.0
AIBA_NINE_RULE_ALERT_N_DEFAULT = 9
AIBA_TRY_FAIL_LOOKBACK_N_DEFAULT = 12
AIBA_TRY_FAIL_MIN_COUNT_DEFAULT = 2
AIBA_STYLE_AI_BOOST_DEFAULT = 0.10
AIBA_STYLE_AI_PENALTY_DEFAULT = 0.12
# Elliott Wave Fibonacci retracement gate
FIB_RETRACEMENT_ENABLED_DEFAULT = True
FIB_GOLDEN_ZONE_BOOST_DEFAULT = 0.18     # +logit when price is in 38.2-61.8% pullback zone (wave 3 candidate)
FIB_REVERSAL_PENALTY_DEFAULT = 0.15      # -logit when > 78.6% retrace (trend failure / wave 5 exhaustion)
FIB_MIN_SWING_RANGE_PCT_DEFAULT = 0.20   # ignore swings smaller than 0.20% (noise guard)
FIB_AIBA_COMBO_BOOST_DEFAULT = 0.08     # extra +logit when GOLDEN zone AND aiba_aligned both true
CANARY_TP_SCALE_DEFAULT = 0.65            # shrink TP only during CANARY to bank quicker samples
NEWS_ENTRY_BLOCK_AHEAD_MIN_DEFAULT = 60   # skip new entries if a news/lunch block starts within this horizon
PRE_NEWS_EXIT_BUFFER_MIN_DEFAULT = 10     # flatten open position before an upcoming news/lunch block
PRE_NEWS_EXIT_MIN_HOLD_MIN_DEFAULT = 5    # avoid immediate churn right after entry
MR_OBSERVE_ENABLED_DEFAULT = False
MR_BAR_MIN_DEFAULT = 5
MR_LEVEL_LOOKBACK_N_DEFAULT = 24
MR_SPIKE_LOOKBACK_N_DEFAULT = 12
MR_SPIKE_MIN_MOVE_PCT_DEFAULT = 0.18
MR_TOUCH_TOLERANCE_PCT_DEFAULT = 0.08
MR_MA_CROSS_LOOKBACK_N_DEFAULT = 16
MR_RANGE_MAX_MA_SLOPE_PCT_DEFAULT = 0.08
MR_RANGE_MAX_MA_GAP_PCT_DEFAULT = 0.18
MR_STOP_MIN_DISTANCE_PCT_DEFAULT = 1.0
MR_PAPER_ENABLED_DEFAULT = False
MR_PAPER_MIN_RANK_DEFAULT = "A"
MR_PAPER_REQUIRE_TRIGGER_DEFAULT = True
MR_PAPER_REQUIRE_RECLAIM_DEFAULT = True

ONE_POSITION_ONLY_DEFAULT = True

TIMEOUT_MODE_DEFAULT = "IGNORE"   # IGNORE / EXTEND / PARTIAL
MAX_EXTEND_COUNT_DEFAULT = 1
EXTEND_MIN_DEFAULT = 30
EXTEND_MIN_BESTFAV_PCT_DEFAULT = 0.08
PARTIAL_TP_TRIGGER_PCT_DEFAULT = 0.10
EXIT_TECHNICAL_ENABLED_DEFAULT = False
EXIT_TECHNICAL_ONLY_PAPER_DEFAULT = True
EXIT_SMA_FAST_N_DEFAULT = 5
EXIT_SMA_SLOW_N_DEFAULT = 20
EXIT_TECHNICAL_MIN_HOLD_MIN_DEFAULT = 5
WEAK_PROGRESS_EXIT_ENABLED_DEFAULT = False
WEAK_PROGRESS_EXIT_ONLY_PAPER_DEFAULT = True
WEAK_PROGRESS_EXIT_MIN_HOLD_MIN_DEFAULT = 30
WEAK_PROGRESS_EXIT_MAX_BESTFAV_PCT_DEFAULT = 0.05
PROGRESS_REVERSAL_EXIT_ENABLED_DEFAULT = False
PROGRESS_REVERSAL_EXIT_ONLY_PAPER_DEFAULT = True
PROGRESS_REVERSAL_EXIT_MIN_HOLD_MIN_DEFAULT = 20
PROGRESS_REVERSAL_EXIT_MIN_BESTFAV_PCT_DEFAULT = 0.08
PROGRESS_REVERSAL_EXIT_MAX_CURRENT_FAV_PCT_DEFAULT = 0.03
NEAR_TP_GIVEBACK_EXIT_ENABLED_DEFAULT = False
NEAR_TP_GIVEBACK_EXIT_ONLY_PAPER_DEFAULT = True
NEAR_TP_GIVEBACK_EXIT_MIN_HOLD_MIN_DEFAULT = 5
NEAR_TP_GIVEBACK_EXIT_TRIGGER_RATIO_DEFAULT = 0.85
NEAR_TP_GIVEBACK_EXIT_MIN_GIVEBACK_PCT_DEFAULT = 0.04
NEAR_TP_GIVEBACK_EXIT_MAX_CURRENT_FAV_PCT_DEFAULT = 0.06
NO_FOLLOW_THROUGH_EXIT_ENABLED_DEFAULT = False
NO_FOLLOW_THROUGH_EXIT_ONLY_PAPER_DEFAULT = True
NO_FOLLOW_THROUGH_EXIT_MIN_HOLD_MIN_DEFAULT = 5
NO_FOLLOW_THROUGH_EXIT_MAX_BESTFAV_PCT_DEFAULT = 0.01
NO_FOLLOW_THROUGH_EXIT_MAX_CURRENT_FAV_PCT_DEFAULT = 0.00

TP_TRAIL_ENABLED_DEFAULT = False
TP_TRAIL_GIVEBACK_PCT_DEFAULT = 0.08
TP_TRAIL_MAX_MIN_DEFAULT = 20

EARLY_ADVERSE_EXIT_ENABLED_DEFAULT = False
EARLY_ADVERSE_EXIT_ONLY_PAPER_DEFAULT = False
EARLY_ADVERSE_EXIT_MIN_HOLD_MIN_DEFAULT = 1.5
EARLY_ADVERSE_EXIT_LOSS_PCT_DEFAULT = -0.020
EARLY_ADVERSE_EXIT_MAX_FAV_PCT_DEFAULT = 0.010

OBSERVE_ONLY_DEFAULT = False

SAFETY_HARD_BLOCK_DEFAULT = True

LIVE_ENABLED_DEFAULT = False
ROLLOUT_MODE_DEFAULT = "AUTO"
STAGE_PAPER_DAYS_DEFAULT = 3
STAGE_CANARY_DAYS_DEFAULT = 3
CANARY_LOT_DEFAULT = 0.001
DAILY_LOSS_LIMIT_PCT_DEFAULT = -1.0
DAILY_PROFIT_STOP_PCT_DEFAULT = 0.0
VOL_LOT_SCALE_ENABLED_DEFAULT = False
VOL_LOT_SCALE_HIGH_RATIO_DEFAULT = 0.5
VOL_LOT_SCALE_THRESHOLD_PCT_DEFAULT = 0.015
STREAK_STOP_ENABLED_DEFAULT = False
STREAK_STOP_MAX_LOSSES_DEFAULT = 3
LIMIT_ORDER_TIMEOUT_SEC_DEFAULT = 30
LIMIT_PRICE_OFFSET_TICKS_DEFAULT = 0
PRODUCT_CODE_DEFAULT = PRODUCT
MARKET_TYPE_DEFAULT = "SPOT"
FX_LEVERAGE_DEFAULT = 2.0
FX_COLLATERAL_USE_RATIO_DEFAULT = 0.90
EXCHANGE_NAME_DEFAULT = "bitflyer"
KEYCHAIN_SERVICE_DEFAULT = "ouroboros.bitflyer"
KEYCHAIN_ACCOUNT_KEY_DEFAULT = "api_key"
KEYCHAIN_ACCOUNT_SECRET_DEFAULT = "api_secret"
TICK_SIZE_DEFAULT = 1.0
PARTIAL_REMAIN_EPS = 1e-8

AI_TRAIN_LOG_FILE = LOGS_DIR / "ai_training_log.csv"
SHADOW_LOGS_DIR = MAIN_DIR.parent / "logs" / "instances" / "shadow"
SHADOW_AI_TRAIN_LOG_FILE = SHADOW_LOGS_DIR / "ai_training_log.csv"
BACKTEST_LOGS_DIR = MAIN_DIR.parent / "logs" / "backtest"
BACKTEST_AI_TRAIN_LOG_FILE = BACKTEST_LOGS_DIR / "ai_training_log_backtest.csv"
AI_TRAIN_FIELDS = [
    "time",
    "pos_id",
    "side",
    "entry_time",
    "exit_time",
    "hold_min",
    "entry_price",
    "exit_price",
    "ret_pct",
    "outcome",
    "result",
    "ai_score",
    "ai_score_extend",
    "spread_entry_pct",
    "ma_gap_pct",
    "ma_slope_pct_per_step",
    "volatility_pct",
    "trendline_slope_pct_per_step",
    "channel_pos",
    "channel_width_pct",
    "trend",
    "signal",
    "best_fav",
    "max_adv",
    "extend_count",
    "exec_mode",
    "stage",
    "is_shadow",
    "fib_zone",
    "fib_wave3_candidate",
    "aiba_aligned",
]
AI_TRAIN_EXIT_RESULTS = {
    "PAPER_EXIT_TP",
    "PAPER_EXIT_SL",
    "PAPER_EXIT_TIMEOUT",
    "PAPER_EXIT_EOD",
    "PAPER_EXIT_PRENEWS",
    "PAPER_EXIT_EARLY_ADVERSE",
}
AI_SCORE_IN_NOTE_RE = re.compile(r"\bAI(?:_EXT)?\s*score=([0-9]*\.?[0-9]+)\b", re.IGNORECASE)
TRADE_LOG_NAME_RE = re.compile(r"^trade_log_(\d{8})\.csv$")
AI_AUTOTUNE_THRESHOLD_GRID = [round(x, 2) for x in (0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85)]
AI_AUTOTUNE_LOOKBACK_DAYS_DEFAULT = 45
AI_AUTOTUNE_MIN_IMPROVE = 0.005
AI_TRAIN_LIVE_ONLY_DEFAULT = False
AI_TRAIN_LIVE_BOOST_DEFAULT = 1.0
AI_TRAIN_INCLUDE_SHADOW_DEFAULT = False
AI_TRAIN_SHADOW_BOOST_DEFAULT = 0.7
AI_TRAIN_INCLUDE_BACKTEST_DEFAULT = False
AI_TRAIN_BACKTEST_BOOST_DEFAULT = 0.30
AI_TRAIN_BACKTEST_GATE_ENABLED_DEFAULT = True
AI_TRAIN_BACKTEST_GATE_MIN_SAMPLES_DEFAULT = 300
AI_TRAIN_BACKTEST_GATE_EXPECTANCY_MIN_DEFAULT = 0.0
AI_TRAIN_BACKTEST_GATE_PF_MIN_DEFAULT = 1.0
AI_TRAIN_BACKTEST_MAX_ROWS_DEFAULT = 3000
AI_TRAIN_RECENT_HALFLIFE_DAYS_DEFAULT = 14
AI_TRAIN_WEEKLY_FEEDBACK_ENABLED_DEFAULT = False
AI_TRAIN_WEEKLY_GOOD_HOURS_DEFAULT = ""
AI_TRAIN_WEEKLY_BAD_HOURS_DEFAULT = ""
AI_TRAIN_WEEKLY_GOOD_HOUR_BOOST_DEFAULT = 1.20
AI_TRAIN_WEEKLY_BAD_HOUR_PENALTY_DEFAULT = 0.70
AI_TRAIN_GATE_ENABLED_DEFAULT = True
AI_TRAIN_GATE_MIN_SAMPLES_DEFAULT = 30
AI_TRAIN_GATE_EXPECTANCY_MIN_DEFAULT = 0.0
AI_TRAIN_GATE_PF_MIN_DEFAULT = 1.05
AI_AUTO_ROLLBACK_ENABLED_DEFAULT = True
AI_AUTO_ROLLBACK_LOOKBACK_DAYS_DEFAULT = 14
AI_AUTO_ROLLBACK_PF_FLOOR_DEFAULT = 0.95
AI_AUTO_ROLLBACK_EXPECTANCY_FLOOR_DEFAULT = -0.01
AI_AUTO_CONTROL_SYNC_ENABLED_DEFAULT = True
AI_LOT_LOCK_ENABLED_DEFAULT = True
AI_LOT_LOCK_MIN_SAMPLES_DEFAULT = 120
AI_LOT_LOCK_MAX_LOT_DEFAULT = CANARY_LOT_DEFAULT
AI_MONTHLY_REVAL_ENABLED_DEFAULT = True
AI_MONTHLY_REVAL_LOOKBACK_DAYS_DEFAULT = 120
AI_MONTHLY_REVAL_MIN_SAMPLES_DEFAULT = 300
AI_MONTHLY_REVAL_PF_MIN_DEFAULT = 1.00
AI_MONTHLY_REVAL_EXPECTANCY_MIN_DEFAULT = 0.0
AI_MONTHLY_REVAL_MIN_IMPROVE_DEFAULT = 0.0
_AI_TRAIN_HEADER_READY = False
CONTROL_AUTO_SYNC_ALLOWED_KEYS = {"ai_threshold", "ai_veto_threshold"}
CONTROL_AUTO_SYNC_LOG_FILE = MAIN_DIR / ".streamlit" / "dashboard_change_log.jsonl"
CONTROL_AUTO_SYNC_BACKUP_DIR = MAIN_DIR / "backups" / "control_autosync"

# -------------------------
# pos_id contract
# -------------------------
_POS_ID_RE = re.compile(r"\bpos_id=([0-9]{8}-[0-9]{6}-(BUY|SELL)-\d{3})\b")
_RUN_LOCK_HELD = False


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


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False
    st = _pid_state(pid)
    if st.startswith("Z"):
        return False
    return True


def _release_run_lock() -> None:
    global _RUN_LOCK_HELD
    try:
        if RUN_LOCK_DIR.exists():
            for f in RUN_LOCK_DIR.iterdir():
                try:
                    f.unlink()
                except Exception:
                    pass
            try:
                RUN_LOCK_DIR.rmdir()
            except Exception:
                pass
    except Exception:
        pass
    _RUN_LOCK_HELD = False


def ensure_run_lock() -> bool:
    """
    Process-level run lock so dashboard can inspect .run_lock/lockinfo.txt.
    Safe for run.py loop: lock is held until process exits.
    """
    global _RUN_LOCK_HELD
    if _RUN_LOCK_HELD:
        return True

    # stale lock handling
    if RUN_LOCK_DIR.exists():
        pid = None
        try:
            info = RUN_LOCK_DIR / "lockinfo.txt"
            if info.exists():
                txt = info.read_text(encoding="utf-8", errors="ignore")
                for line in txt.splitlines():
                    if line.startswith("pid="):
                        pid = int(line.split("=", 1)[1].strip())
                        break
        except Exception:
            pid = None

        if pid and _pid_is_alive(pid):
            return False

        _release_run_lock()

    try:
        RUN_LOCK_DIR.mkdir(parents=True, exist_ok=True)
        info = RUN_LOCK_DIR / "lockinfo.txt"
        now = _now_str(datetime.now())
        info.write_text(f"pid={os.getpid()}\nstarted_at={now}\n", encoding="utf-8")
        _RUN_LOCK_HELD = True
        atexit.register(_release_run_lock)
        return True
    except Exception:
        return False


def _now_str(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _safe_int(x: Any, default: int) -> int:
    try:
        return int(str(x).strip())
    except Exception:
        return default


def _safe_float(x: Any, default: float) -> float:
    try:
        return float(str(x).strip())
    except Exception:
        return default


def _safe_bool(x: Any, default: bool) -> bool:
    if x is None:
        return default
    s = str(x).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def _safe_str(x: Any, default: str = "") -> str:
    if x is None:
        return default
    try:
        s = str(x).strip()
        return s if s else default
    except Exception:
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _sigmoid(x: float) -> float:
    if x >= 60:
        return 1.0
    if x <= -60:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _to_float_or_none(x: Any) -> Optional[float]:
    try:
        s = str(x).strip()
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def _parse_trade_dt(s: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(str(s), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _extract_note_value(note: Any, key: str) -> str:
    text = _safe_str(note, "")
    if not text:
        return ""
    m = re.search(rf"\b{re.escape(key)}=([^\s]+)", text)
    if not m:
        return ""
    return _safe_str(m.group(1), "")


def _extract_ai_score_from_note(note: Any) -> Optional[float]:
    text = _safe_str(note, "")
    if not text:
        return None
    m = AI_SCORE_IN_NOTE_RE.search(text)
    if not m:
        return None
    return _to_float_or_none(m.group(1))


def _calc_ret_pct(side: str, entry_price: Optional[float], exit_price: Optional[float]) -> Optional[float]:
    if entry_price is None or exit_price is None:
        return None
    if entry_price == 0:
        return None
    s = _safe_str(side, "BUY").upper()
    if s == "SELL":
        return (entry_price - exit_price) / entry_price * 100.0
    return (exit_price - entry_price) / entry_price * 100.0


def make_pos_id(dt: datetime, side: str, seq: int) -> str:
    side_u = (side or "").strip().upper()
    side_u = "BUY" if side_u == "BUY" else "SELL"
    ymd_hms = dt.strftime("%Y%m%d-%H%M%S")
    s = seq if seq >= 0 else 0
    return f"{ymd_hms}-{side_u}-{s:03d}"


def embed_pos_id(note: Optional[str], pos_id: Optional[str]) -> str:
    base = (note or "").strip()
    # normalize pos_id input: treat empty or literal 'None' as missing
    if pos_id is None:
        pid = None
    else:
        try:
            pid = str(pos_id).strip()
        except Exception:
            pid = None
        if not pid or pid.lower() == "none":
            pid = None

    # if pid missing, remove any accidental 'pos_id=None' occurrences and return
    if not pid:
        base = re.sub(r"\bpos_id=None\b,?", "", base).strip()
        return base

    # safe insertion/replace of a valid pos_id
    if _POS_ID_RE.search(base):
        return _POS_ID_RE.sub(f"pos_id={pid}", base)
    if "pos_id=" in base:
        left, right = base.split("pos_id=", 1)
        left = left.rstrip()
        right = right.lstrip()
        if " " in right:
            _, tail = right.split(" ", 1)
            return f"{left} pos_id={pid} {tail.strip()}".strip()
        return f"{left} pos_id={pid}".strip()
    return (base + f" pos_id={pid}").strip()


# -------------------------
# I/O: state
# -------------------------
def load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_state(state: Dict[str, Any]) -> None:
    text = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(STATE_FILE)  # atomic on POSIX (rename syscall)


def get_open_pos(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    op = state.get("_open_pos")
    return op if isinstance(op, dict) else None


def set_open_pos(state: Dict[str, Any], op: Dict[str, Any]) -> None:
    state["_open_pos"] = op
    save_state(state)


def clear_open_pos(state: Dict[str, Any]) -> None:
    state.pop("_open_pos", None)
    save_state(state)


def trades_today(state: Dict[str, Any], day_key: str) -> int:
    try:
        return int(state.get(day_key, 0))
    except Exception:
        return 0


def inc_trades_today(state: Dict[str, Any], day_key: str) -> None:
    state[day_key] = trades_today(state, day_key) + 1
    save_state(state)


def next_pos_seq(state: Dict[str, Any], day8: str) -> int:
    k = f"_pos_seq_{day8}"
    n = int(state.get(k, 0) or 0) + 1
    state[k] = n
    save_state(state)
    return n


# -------------------------
# I/O: CONTROL
# -------------------------
def load_control_csv(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    out: Dict[str, str] = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            r = csv.reader(f)
            for row in r:
                if not row or len(row) < 2:
                    continue
                k = str(row[0]).strip()
                v = str(row[1]).strip()
                if not k:
                    continue
                if k.lower() == "key" and v.lower() == "value":
                    continue
                out[k] = v
    except Exception:
        return {}
    return out


def _fmt_control_float(v: float) -> str:
    s = f"{float(v):.6f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _shorten_for_log(v: Any, max_len: int = 60) -> str:
    s = str(v)
    if len(s) <= max_len:
        return s
    return s[: max(0, max_len - 3)] + "..."


def _control_changed_items(before_ctrl: Dict[str, Any], after_ctrl: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    b = {str(k): str(v) for k, v in dict(before_ctrl or {}).items()}
    a = {str(k): str(v) for k, v in dict(after_ctrl or {}).items()}
    keys = sorted(set(b.keys()) | set(a.keys()))
    out: List[Tuple[str, str, str]] = []
    for k in keys:
        bv = str(b.get(k, ""))
        av = str(a.get(k, ""))
        if bv != av:
            out.append((k, bv, av))
    return out


def _read_control_key_order(path: Path) -> List[str]:
    out: List[str] = []
    seen: set = set()
    if not path.exists():
        return out
    try:
        with open(path, newline="", encoding="utf-8") as f:
            r = csv.reader(f)
            for row in r:
                if not row or len(row) < 2:
                    continue
                k = str(row[0]).strip()
                v = str(row[1]).strip()
                if not k:
                    continue
                if k.lower() == "key" and v.lower() == "value":
                    continue
                if k in seen:
                    continue
                out.append(k)
                seen.add(k)
    except Exception:
        return []
    return out


def _write_control_kv_csv_atomic(path: Path, ctrl: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    key_order = _read_control_key_order(path)
    known = set(key_order)
    for k in sorted(ctrl.keys()):
        if k not in known:
            key_order.append(k)
            known.add(k)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{int(time.time() * 1000)}")
    try:
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["key", "value"])
            for k in key_order:
                w.writerow([k, str(ctrl.get(k, ""))])
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def _append_control_change_log_from_bot(
    *,
    control_path: Path,
    before_ctrl: Dict[str, Any],
    after_ctrl: Dict[str, Any],
    reason: str,
    run_at: Optional[datetime] = None,
    log_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    changed = _control_changed_items(before_ctrl, after_ctrl)
    if not changed:
        return True, "no diff"
    p = log_path or CONTROL_AUTO_SYNC_LOG_FILE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        changed_keys = [k for k, _, _ in changed]
        preview = [
            {"key": k, "before": _shorten_for_log(b), "after": _shorten_for_log(a)}
            for k, b, a in changed[:30]
        ]
        now = run_at or datetime.now()
        row = {
            "ts": _now_str(now),
            "version": "bot.auto_control_sync.v1",
            "type": "CONFIG",
            "author": "bot.daily_ai_autotune",
            "summary": f"{reason}: {len(changed_keys)} keys changed",
            "files": [f"MAIN/{control_path.name}"],
            "reason": str(reason),
            "changed_keys": changed_keys,
            "diff_preview": preview,
            "source": "bot",
        }
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return True, "ok"
    except Exception as e:
        return False, str(e)


def sync_allowed_control_updates(
    *,
    control_path: Path,
    updates: Dict[str, Any],
    reason: str,
    run_at: Optional[datetime] = None,
    backup_dir: Optional[Path] = None,
    log_path: Optional[Path] = None,
) -> Tuple[bool, str, List[str]]:
    if not isinstance(updates, dict) or not updates:
        return True, "no updates", []

    allowed_updates: Dict[str, str] = {}
    for raw_k, raw_v in updates.items():
        k = str(raw_k).strip()
        if k not in CONTROL_AUTO_SYNC_ALLOWED_KEYS:
            continue
        allowed_updates[k] = str(raw_v).strip()
    if not allowed_updates:
        return True, "no allowed keys", []

    before_ctrl = load_control_csv(control_path)
    after_ctrl = dict(before_ctrl)
    changed_keys: List[str] = []
    for k, v in allowed_updates.items():
        bv = str(before_ctrl.get(k, ""))
        if bv != v:
            after_ctrl[k] = v
            changed_keys.append(k)
    if not changed_keys:
        return True, "no diff", []

    now = run_at or datetime.now()
    bd = backup_dir or CONTROL_AUTO_SYNC_BACKUP_DIR
    bd.mkdir(parents=True, exist_ok=True)
    backup = bd / f"{control_path.name}.{now.strftime('%Y%m%d_%H%M%S')}.{os.getpid()}.bak"
    had_original = control_path.exists()

    try:
        if had_original:
            shutil.copy2(control_path, backup)
        else:
            backup.write_text("", encoding="utf-8")
        _write_control_kv_csv_atomic(control_path, after_ctrl)
    except Exception as e:
        try:
            if had_original and backup.exists():
                shutil.copy2(backup, control_path)
            elif (not had_original) and control_path.exists():
                control_path.unlink()
        except Exception:
            pass
        return False, f"control sync failed: {e}", changed_keys

    ok_log, msg_log = _append_control_change_log_from_bot(
        control_path=control_path,
        before_ctrl=before_ctrl,
        after_ctrl=after_ctrl,
        reason=reason,
        run_at=now,
        log_path=log_path,
    )
    if ok_log:
        return True, "ok", changed_keys
    return True, f"ok (log_warn={msg_log})", changed_keys


# -------------------------
# I/O: AI model (deep-merge)
# -------------------------
AI_DEFAULT: Dict[str, Any] = {
    "ai_enabled": False,
    "ai_mode": "ADVISORY",  # OFF / ADVISORY / FILTER / DECISION
    "ai_weight": 0.30,
    "decision_points": {"entry": True, "exit": False, "extend": True, "skip": True},
    "confidence_threshold": {"entry": 0.65, "extend": 0.60},
    "ai_veto": {"enabled": True, "min_confidence": 0.80},
    "features": {
        "use_ma": True,
        "use_trend": True,
        "use_spread": True,
        "use_time": True,
        "use_trendline": True,
        "use_channel": True,
        "use_htf_context": False,
        "use_recent_winrate": False,
        "use_aiba_style": True,
    },
    "model_info": {
        "type": "rule_scoring",
        "version": "v1",
        "trained_on": "",
        "last_updated": "",
    },
    "logging": {"log_ai_decision": True, "log_ai_score": True, "log_ai_reason": True},
}


def _deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(dst)
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def read_ai_model_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return dict(AI_DEFAULT)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return dict(AI_DEFAULT)
        merged = _deep_merge(AI_DEFAULT, raw)
        # backward compatibility: old model used global.threshold only.
        g = raw.get("global")
        if isinstance(g, dict):
            legacy_th = _to_float_or_none(g.get("threshold"))
            conf_raw = raw.get("confidence_threshold")
            has_entry = isinstance(conf_raw, dict) and ("entry" in conf_raw)
            if legacy_th is not None and not has_entry:
                c = merged.get("confidence_threshold")
                if not isinstance(c, dict):
                    c = {}
                    merged["confidence_threshold"] = c
                c["entry"] = _clamp(float(legacy_th), 0.0, 1.0)
        return merged
    except Exception:
        return dict(AI_DEFAULT)


def write_ai_model_json(path: Path, model: Dict[str, Any]) -> None:
    path.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_ai_mode(mode_raw: str) -> str:
    m = (mode_raw or "").strip().upper()
    # file values: OFF/ADVISORY/FILTER/DECISION
    if m == "OFF":
        return "OFF"
    if m == "ADVISORY":
        return "SCORE_ONLY"
    if m == "FILTER":
        return "VETO"
    if m == "DECISION":
        return "GATE"
    # accept internal values
    if m in ("SCORE_ONLY", "VETO", "GATE"):
        return m
    return "SCORE_ONLY"


# -------------------------
# Runtime config
# -------------------------
@dataclass
class Cfg:
    # session
    start_hour: int = START_HOUR_DEFAULT
    end_hour: int = END_HOUR_DEFAULT

    # switches
    today_on: bool = True
    trade_enabled: bool = True
    paper_mode: bool = True
    observe_only: bool = OBSERVE_ONLY_DEFAULT
    live_enabled: bool = LIVE_ENABLED_DEFAULT

    # sizing
    lot: float = LOT_DEFAULT
    canary_lot: float = CANARY_LOT_DEFAULT
    ai_lot_lock_enabled: bool = AI_LOT_LOCK_ENABLED_DEFAULT
    ai_lot_lock_min_samples: int = AI_LOT_LOCK_MIN_SAMPLES_DEFAULT
    ai_lot_lock_max_lot: float = AI_LOT_LOCK_MAX_LOT_DEFAULT

    # strategy
    tp_buy_pct: float = TP_BUY_PCT_DEFAULT
    tp_sell_pct: float = TP_SELL_PCT_DEFAULT
    sl_pct: float = SL_PCT_DEFAULT
    win_min: int = WIN_MIN_DEFAULT

    # filters
    spread_limit_pct: float = SPREAD_LIMIT_PCT_DEFAULT
    max_trades_per_day: int = MAX_TRADES_PER_DAY_DEFAULT
    no_paper_hours: List[int] = None
    buy_fast_ma_distance_pct: float = BUY_FAST_MA_DISTANCE_PCT_DEFAULT
    sell_fast_ma_distance_pct: float = SELL_FAST_MA_DISTANCE_PCT_DEFAULT
    trend_flip_cooldown_min: int = TREND_FLIP_COOLDOWN_MIN_DEFAULT
    trend_strength_filter_enabled: bool = TREND_STRENGTH_FILTER_ENABLED_DEFAULT
    trend_strength_lookback_n: int = TREND_STRENGTH_LOOKBACK_N_DEFAULT
    trend_strength_min_er: float = TREND_STRENGTH_MIN_ER_DEFAULT
    htf15_context_enabled: bool = HTF15_CONTEXT_ENABLED_DEFAULT
    htf60_context_enabled: bool = HTF60_CONTEXT_ENABLED_DEFAULT
    htf_context_lookback_n: int = HTF_CONTEXT_LOOKBACK_N_DEFAULT
    htf_bias_slope_pct: float = HTF_BIAS_SLOPE_PCT_DEFAULT
    htf60_countertrend_penalty: float = HTF60_COUNTERTREND_PENALTY_DEFAULT
    htf15_60_conflict_penalty: float = HTF15_60_CONFLICT_PENALTY_DEFAULT
    ma_cross_feature_enabled: bool = MA_CROSS_FEATURE_ENABLED_DEFAULT
    ma_cross_recent_lookback_n: int = MA_CROSS_RECENT_LOOKBACK_N_DEFAULT
    ma_cross_min_gap_pct: float = MA_CROSS_MIN_GAP_PCT_DEFAULT
    ma_cross_slow_slope_min_pct: float = MA_CROSS_SLOW_SLOPE_MIN_PCT_DEFAULT
    ma_cross_price_filter_enabled: bool = MA_CROSS_PRICE_FILTER_ENABLED_DEFAULT
    ma_cross_ai_boost: float = MA_CROSS_AI_BOOST_DEFAULT
    ma_cross_ai_penalty: float = MA_CROSS_AI_PENALTY_DEFAULT
    tech_indicators_enabled: bool = TECH_INDICATORS_ENABLED_DEFAULT
    rsi_n: int = RSI_N_DEFAULT
    rsi_low: float = RSI_LOW_DEFAULT
    rsi_high: float = RSI_HIGH_DEFAULT
    bb_n: int = BB_N_DEFAULT
    bb_k: float = BB_K_DEFAULT
    bw_walk_min_count: int = BW_WALK_MIN_COUNT_DEFAULT
    bb_squeeze_threshold_pct: float = BB_SQUEEZE_THRESHOLD_PCT_DEFAULT
    atr_n: int = ATR_N_DEFAULT
    atr_low_pct: float = ATR_LOW_PCT_DEFAULT
    atr_high_pct: float = ATR_HIGH_PCT_DEFAULT
    trend_power_lookback_n: int = TREND_POWER_LOOKBACK_N_DEFAULT
    trend_power_strong_er: float = TREND_POWER_STRONG_ER_DEFAULT
    tech_ai_boost: float = TECH_AI_BOOST_DEFAULT
    tech_ai_penalty: float = TECH_AI_PENALTY_DEFAULT
    chart_pattern_enabled: bool = CHART_PATTERN_ENABLED_DEFAULT
    ohlc_timeframe_min: int = OHLC_TIMEFRAME_MIN_DEFAULT
    ohlc_max_bars: int = OHLC_MAX_BARS_DEFAULT
    chart_pattern_min_bar_ticks: int = CHART_PATTERN_MIN_BAR_TICKS_DEFAULT
    chart_pattern_quality_lookback_bars: int = CHART_PATTERN_QUALITY_LOOKBACK_BARS_DEFAULT
    swing_lookback: int = SWING_LOOKBACK_DEFAULT
    double_top_peak_tolerance_pct: float = DOUBLE_TOP_PEAK_TOLERANCE_PCT_DEFAULT
    double_bottom_trough_tolerance_pct: float = DOUBLE_BOTTOM_TROUGH_TOLERANCE_PCT_DEFAULT
    shoulder_tolerance_pct: float = SHOULDER_TOLERANCE_PCT_DEFAULT
    head_min_excess_pct: float = HEAD_MIN_EXCESS_PCT_DEFAULT
    neckline_break_confirm_bars: int = NECKLINE_BREAK_CONFIRM_BARS_DEFAULT
    pattern_ai_boost: float = PATTERN_AI_BOOST_DEFAULT
    pattern_ai_penalty: float = PATTERN_AI_PENALTY_DEFAULT
    market_phase_enabled: bool = MARKET_PHASE_ENABLED_DEFAULT
    market_phase_block_b_enabled: bool = MARKET_PHASE_BLOCK_B_ENABLED_DEFAULT
    market_phase_lookback_n: int = MARKET_PHASE_LOOKBACK_N_DEFAULT
    market_phase_flat_slope_pct: float = MARKET_PHASE_FLAT_SLOPE_PCT_DEFAULT
    market_phase_flat_gap_pct: float = MARKET_PHASE_FLAT_GAP_PCT_DEFAULT
    market_phase_range_max_width_pct: float = MARKET_PHASE_RANGE_MAX_WIDTH_PCT_DEFAULT
    market_phase_ai_boost: float = MARKET_PHASE_AI_BOOST_DEFAULT
    market_phase_ai_penalty: float = MARKET_PHASE_AI_PENALTY_DEFAULT
    aiba_style_enabled: bool = AIBA_STYLE_ENABLED_DEFAULT
    aiba_style_ai_enabled: bool = AIBA_STYLE_AI_ENABLED_DEFAULT
    aiba_ma_short_n: int = AIBA_MA_SHORT_N_DEFAULT
    aiba_ma_mid_n: int = AIBA_MA_MID_N_DEFAULT
    aiba_ma_long_n: int = AIBA_MA_LONG_N_DEFAULT
    aiba_slope_min_pct: float = AIBA_SLOPE_MIN_PCT_DEFAULT
    aiba_nine_rule_alert_n: int = AIBA_NINE_RULE_ALERT_N_DEFAULT
    aiba_try_fail_lookback_n: int = AIBA_TRY_FAIL_LOOKBACK_N_DEFAULT
    aiba_try_fail_min_count: int = AIBA_TRY_FAIL_MIN_COUNT_DEFAULT
    aiba_style_ai_boost: float = AIBA_STYLE_AI_BOOST_DEFAULT
    aiba_style_ai_penalty: float = AIBA_STYLE_AI_PENALTY_DEFAULT
    news_entry_block_ahead_min: int = NEWS_ENTRY_BLOCK_AHEAD_MIN_DEFAULT
    pre_news_exit_buffer_min: int = PRE_NEWS_EXIT_BUFFER_MIN_DEFAULT
    pre_news_exit_min_hold_min: int = PRE_NEWS_EXIT_MIN_HOLD_MIN_DEFAULT
    mr_observe_enabled: bool = MR_OBSERVE_ENABLED_DEFAULT
    mr_bar_min: int = MR_BAR_MIN_DEFAULT
    mr_level_lookback_n: int = MR_LEVEL_LOOKBACK_N_DEFAULT
    mr_spike_lookback_n: int = MR_SPIKE_LOOKBACK_N_DEFAULT
    mr_spike_min_move_pct: float = MR_SPIKE_MIN_MOVE_PCT_DEFAULT
    mr_touch_tolerance_pct: float = MR_TOUCH_TOLERANCE_PCT_DEFAULT
    mr_ma_cross_lookback_n: int = MR_MA_CROSS_LOOKBACK_N_DEFAULT
    mr_range_max_ma_slope_pct: float = MR_RANGE_MAX_MA_SLOPE_PCT_DEFAULT
    mr_range_max_ma_gap_pct: float = MR_RANGE_MAX_MA_GAP_PCT_DEFAULT
    mr_stop_min_distance_pct: float = MR_STOP_MIN_DISTANCE_PCT_DEFAULT
    mr_paper_enabled: bool = MR_PAPER_ENABLED_DEFAULT
    mr_paper_min_rank: str = MR_PAPER_MIN_RANK_DEFAULT
    mr_paper_require_trigger: bool = MR_PAPER_REQUIRE_TRIGGER_DEFAULT
    mr_paper_require_reclaim: bool = MR_PAPER_REQUIRE_RECLAIM_DEFAULT
    one_position_only: bool = ONE_POSITION_ONLY_DEFAULT
    safety_hard_block: bool = SAFETY_HARD_BLOCK_DEFAULT

    # MA
    fast_n: int = FAST_N_DEFAULT
    slow_n: int = SLOW_N_DEFAULT
    max_ltp_history: int = MAX_LTP_HISTORY_DEFAULT

    # timeout
    timeout_mode: str = TIMEOUT_MODE_DEFAULT
    max_extend_count: int = MAX_EXTEND_COUNT_DEFAULT
    extend_min: int = EXTEND_MIN_DEFAULT
    extend_min_bestfav_pct: float = EXTEND_MIN_BESTFAV_PCT_DEFAULT
    partial_tp_trigger_pct: float = PARTIAL_TP_TRIGGER_PCT_DEFAULT
    exit_technical_enabled: bool = EXIT_TECHNICAL_ENABLED_DEFAULT
    exit_technical_only_paper: bool = EXIT_TECHNICAL_ONLY_PAPER_DEFAULT
    exit_sma_fast_n: int = EXIT_SMA_FAST_N_DEFAULT
    exit_sma_slow_n: int = EXIT_SMA_SLOW_N_DEFAULT
    exit_technical_min_hold_min: int = EXIT_TECHNICAL_MIN_HOLD_MIN_DEFAULT
    weak_progress_exit_enabled: bool = WEAK_PROGRESS_EXIT_ENABLED_DEFAULT
    weak_progress_exit_only_paper: bool = WEAK_PROGRESS_EXIT_ONLY_PAPER_DEFAULT
    weak_progress_exit_min_hold_min: int = WEAK_PROGRESS_EXIT_MIN_HOLD_MIN_DEFAULT
    weak_progress_exit_max_best_fav_pct: float = WEAK_PROGRESS_EXIT_MAX_BESTFAV_PCT_DEFAULT
    progress_reversal_exit_enabled: bool = PROGRESS_REVERSAL_EXIT_ENABLED_DEFAULT
    progress_reversal_exit_only_paper: bool = PROGRESS_REVERSAL_EXIT_ONLY_PAPER_DEFAULT
    progress_reversal_exit_min_hold_min: int = PROGRESS_REVERSAL_EXIT_MIN_HOLD_MIN_DEFAULT
    progress_reversal_exit_min_best_fav_pct: float = PROGRESS_REVERSAL_EXIT_MIN_BESTFAV_PCT_DEFAULT
    progress_reversal_exit_max_current_fav_pct: float = PROGRESS_REVERSAL_EXIT_MAX_CURRENT_FAV_PCT_DEFAULT
    near_tp_giveback_exit_enabled: bool = NEAR_TP_GIVEBACK_EXIT_ENABLED_DEFAULT
    near_tp_giveback_exit_only_paper: bool = NEAR_TP_GIVEBACK_EXIT_ONLY_PAPER_DEFAULT
    near_tp_giveback_exit_min_hold_min: int = NEAR_TP_GIVEBACK_EXIT_MIN_HOLD_MIN_DEFAULT
    near_tp_giveback_exit_trigger_ratio: float = NEAR_TP_GIVEBACK_EXIT_TRIGGER_RATIO_DEFAULT
    near_tp_giveback_exit_min_giveback_pct: float = NEAR_TP_GIVEBACK_EXIT_MIN_GIVEBACK_PCT_DEFAULT
    near_tp_giveback_exit_max_current_fav_pct: float = NEAR_TP_GIVEBACK_EXIT_MAX_CURRENT_FAV_PCT_DEFAULT
    no_follow_through_exit_enabled: bool = NO_FOLLOW_THROUGH_EXIT_ENABLED_DEFAULT
    no_follow_through_exit_only_paper: bool = NO_FOLLOW_THROUGH_EXIT_ONLY_PAPER_DEFAULT
    no_follow_through_exit_min_hold_min: int = NO_FOLLOW_THROUGH_EXIT_MIN_HOLD_MIN_DEFAULT
    no_follow_through_exit_max_best_fav_pct: float = NO_FOLLOW_THROUGH_EXIT_MAX_BESTFAV_PCT_DEFAULT
    no_follow_through_exit_max_current_fav_pct: float = NO_FOLLOW_THROUGH_EXIT_MAX_CURRENT_FAV_PCT_DEFAULT
    tp_trail_enabled: bool = TP_TRAIL_ENABLED_DEFAULT
    tp_trail_giveback_pct: float = TP_TRAIL_GIVEBACK_PCT_DEFAULT
    tp_trail_max_min: float = TP_TRAIL_MAX_MIN_DEFAULT
    early_adverse_exit_enabled: bool = EARLY_ADVERSE_EXIT_ENABLED_DEFAULT
    early_adverse_exit_only_paper: bool = EARLY_ADVERSE_EXIT_ONLY_PAPER_DEFAULT
    early_adverse_exit_min_hold_min: float = EARLY_ADVERSE_EXIT_MIN_HOLD_MIN_DEFAULT
    early_adverse_exit_loss_pct: float = EARLY_ADVERSE_EXIT_LOSS_PCT_DEFAULT
    early_adverse_exit_max_fav_pct: float = EARLY_ADVERSE_EXIT_MAX_FAV_PCT_DEFAULT

    # AI
    ai_enabled: bool = False
    ai_mode: str = "OFF"
    ai_dp_entry: bool = True
    ai_dp_extend: bool = True
    ai_th_entry: float = 0.65
    ai_th_extend: float = 0.60
    ai_veto_enabled: bool = True
    ai_veto_min_conf: float = 0.80
    ai_use_ma: bool = True
    ai_use_trend: bool = True
    ai_use_spread: bool = True
    ai_use_time: bool = True
    ai_use_trendline: bool = True
    ai_use_channel: bool = True
    ai_use_htf_context: bool = False
    ai_use_ma_cross: bool = True
    ai_use_technical_indicators: bool = True
    ai_use_chart_patterns: bool = True
    ai_use_market_phase: bool = True
    ai_use_aiba_style: bool = True
    fib_retracement_enabled: bool = FIB_RETRACEMENT_ENABLED_DEFAULT
    fib_golden_zone_boost: float = FIB_GOLDEN_ZONE_BOOST_DEFAULT
    fib_reversal_penalty: float = FIB_REVERSAL_PENALTY_DEFAULT
    fib_min_swing_range_pct: float = FIB_MIN_SWING_RANGE_PCT_DEFAULT
    fib_aiba_combo_boost: float = FIB_AIBA_COMBO_BOOST_DEFAULT
    # per-hour score adjustments (CONTROL: ai_score_good_hours / ai_score_bad_hours)
    ai_score_good_hours: object = None   # Optional[Set[int]]
    ai_score_bad_hours: object = None    # Optional[Set[int]]
    ai_time_good_hour_boost: float = 0.10
    ai_time_bad_hour_penalty: float = 0.10

    # live execution
    rollout_mode: str = ROLLOUT_MODE_DEFAULT
    stage_paper_days: int = STAGE_PAPER_DAYS_DEFAULT
    stage_canary_days: int = STAGE_CANARY_DAYS_DEFAULT
    canary_tp_scale: float = CANARY_TP_SCALE_DEFAULT
    daily_loss_limit_pct: float = DAILY_LOSS_LIMIT_PCT_DEFAULT
    daily_profit_stop_pct: float = DAILY_PROFIT_STOP_PCT_DEFAULT
    vol_lot_scale_enabled: bool = VOL_LOT_SCALE_ENABLED_DEFAULT
    vol_lot_scale_high_ratio: float = VOL_LOT_SCALE_HIGH_RATIO_DEFAULT
    vol_lot_scale_threshold_pct: float = VOL_LOT_SCALE_THRESHOLD_PCT_DEFAULT
    streak_stop_enabled: bool = STREAK_STOP_ENABLED_DEFAULT
    streak_stop_max_losses: int = STREAK_STOP_MAX_LOSSES_DEFAULT
    limit_order_timeout_sec: int = LIMIT_ORDER_TIMEOUT_SEC_DEFAULT
    limit_price_offset_ticks: int = LIMIT_PRICE_OFFSET_TICKS_DEFAULT
    product_code: str = PRODUCT_CODE_DEFAULT
    market_type: str = MARKET_TYPE_DEFAULT
    fx_leverage: float = FX_LEVERAGE_DEFAULT
    fx_collateral_use_ratio: float = FX_COLLATERAL_USE_RATIO_DEFAULT
    exchange_name: str = EXCHANGE_NAME_DEFAULT
    keychain_service: str = KEYCHAIN_SERVICE_DEFAULT
    keychain_account_key: str = KEYCHAIN_ACCOUNT_KEY_DEFAULT
    keychain_account_secret: str = KEYCHAIN_ACCOUNT_SECRET_DEFAULT

    def __post_init__(self):
        if self.no_paper_hours is None:
            self.no_paper_hours = list(NO_PAPER_HOURS_DEFAULT)


def parse_no_paper_hours(v: Any, default: List[int]) -> List[int]:
    if v is None:
        return default
    s = str(v).strip()
    # Explicit blank/none means "no blocked hours".
    if not s:
        return []
    if s.lower() in ("none", "null", "off", "[]", "-"):
        return []
    s = s.replace("[", "").replace("]", "")
    hours: List[int] = []
    for p in [x.strip() for x in s.split(",") if x.strip()]:
        try:
            h = int(p)
            if 0 <= h <= 23:
                hours.append(h)
        except Exception:
            pass
    if not hours:
        return default
    return sorted(set(hours))


def resolve_eod_entry_block_status(now: datetime, cfg: Cfg) -> Tuple[bool, str]:
    if now.time() >= EOD_CUTOFF and now.hour < int(cfg.end_hour):
        return True, f"eod_entry_window cutoff={EOD_CUTOFF.strftime('%H:%M:%S')}"
    return False, ""


def build_runtime_config(control: Dict[str, str], ai_model: Dict[str, Any]) -> Cfg:
    cfg = Cfg()

    # core (CONTROL)
    start_hour_raw = _safe_int(control.get("start_hour"), START_HOUR_DEFAULT)
    end_hour_raw = _safe_int(control.get("end_hour"), END_HOUR_DEFAULT)
    cfg.start_hour = max(0, min(23, start_hour_raw))
    cfg.end_hour = max(1, min(24, end_hour_raw))
    if cfg.end_hour <= cfg.start_hour:
        cfg.end_hour = min(24, cfg.start_hour + 1)

    cfg.today_on = _safe_bool(control.get("today_on"), True)
    cfg.trade_enabled = _safe_bool(control.get("trade_enabled"), True)
    cfg.paper_mode = _safe_bool(control.get("paper_mode"), True)
    cfg.observe_only = _safe_bool(control.get("observe_only"), OBSERVE_ONLY_DEFAULT)
    cfg.live_enabled = _safe_bool(control.get("live_enabled"), LIVE_ENABLED_DEFAULT)

    cfg.tp_buy_pct = _safe_float(control.get("tp_buy_pct"), TP_BUY_PCT_DEFAULT)
    cfg.tp_sell_pct = _safe_float(control.get("tp_sell_pct"), TP_SELL_PCT_DEFAULT)
    cfg.sl_pct = _safe_float(control.get("sl_pct"), SL_PCT_DEFAULT)
    cfg.win_min = _safe_int(control.get("win_min"), WIN_MIN_DEFAULT)

    cfg.spread_limit_pct = _safe_float(control.get("spread_limit_pct"), SPREAD_LIMIT_PCT_DEFAULT)
    cfg.max_trades_per_day = _safe_int(control.get("max_trades_per_day"), MAX_TRADES_PER_DAY_DEFAULT)
    cfg.no_paper_hours = parse_no_paper_hours(control.get("no_paper_hours"), NO_PAPER_HOURS_DEFAULT)

    cfg.buy_fast_ma_distance_pct = max(
        0.0,
        _safe_float(control.get("buy_fast_ma_distance_pct"), BUY_FAST_MA_DISTANCE_PCT_DEFAULT),
    )
    cfg.sell_fast_ma_distance_pct = _safe_float(control.get("sell_fast_ma_distance_pct"), SELL_FAST_MA_DISTANCE_PCT_DEFAULT)
    cfg.trend_flip_cooldown_min = max(
        0,
        _safe_int(control.get("trend_flip_cooldown_min"), TREND_FLIP_COOLDOWN_MIN_DEFAULT),
    )
    cfg.trend_strength_filter_enabled = _safe_bool(
        control.get("trend_strength_filter_enabled"),
        TREND_STRENGTH_FILTER_ENABLED_DEFAULT,
    )
    cfg.trend_strength_lookback_n = max(
        5,
        _safe_int(control.get("trend_strength_lookback_n"), TREND_STRENGTH_LOOKBACK_N_DEFAULT),
    )
    cfg.trend_strength_min_er = _clamp(
        _safe_float(control.get("trend_strength_min_er"), TREND_STRENGTH_MIN_ER_DEFAULT),
        0.0,
        1.0,
    )
    cfg.htf15_context_enabled = _safe_bool(
        control.get("htf15_context_enabled"),
        HTF15_CONTEXT_ENABLED_DEFAULT,
    )
    cfg.htf60_context_enabled = _safe_bool(
        control.get("htf60_context_enabled"),
        HTF60_CONTEXT_ENABLED_DEFAULT,
    )
    cfg.htf_context_lookback_n = max(
        4,
        _safe_int(control.get("htf_context_lookback_n"), HTF_CONTEXT_LOOKBACK_N_DEFAULT),
    )
    cfg.htf_bias_slope_pct = max(
        0.0,
        _safe_float(control.get("htf_bias_slope_pct"), HTF_BIAS_SLOPE_PCT_DEFAULT),
    )
    cfg.htf60_countertrend_penalty = max(
        0.0,
        _safe_float(control.get("htf60_countertrend_penalty"), HTF60_COUNTERTREND_PENALTY_DEFAULT),
    )
    cfg.htf15_60_conflict_penalty = max(
        0.0,
        _safe_float(control.get("htf15_60_conflict_penalty"), HTF15_60_CONFLICT_PENALTY_DEFAULT),
    )
    cfg.ma_cross_feature_enabled = _safe_bool(
        control.get("ma_cross_feature_enabled"),
        MA_CROSS_FEATURE_ENABLED_DEFAULT,
    )
    cfg.ma_cross_recent_lookback_n = max(
        1,
        _safe_int(control.get("ma_cross_recent_lookback_n"), MA_CROSS_RECENT_LOOKBACK_N_DEFAULT),
    )
    cfg.ma_cross_min_gap_pct = max(
        0.0,
        _safe_float(control.get("ma_cross_min_gap_pct"), MA_CROSS_MIN_GAP_PCT_DEFAULT),
    )
    cfg.ma_cross_slow_slope_min_pct = max(
        0.0,
        _safe_float(control.get("ma_cross_slow_slope_min_pct"), MA_CROSS_SLOW_SLOPE_MIN_PCT_DEFAULT),
    )
    cfg.ma_cross_price_filter_enabled = _safe_bool(
        control.get("ma_cross_price_filter_enabled"),
        MA_CROSS_PRICE_FILTER_ENABLED_DEFAULT,
    )
    cfg.ma_cross_ai_boost = max(
        0.0,
        _safe_float(control.get("ma_cross_ai_boost"), MA_CROSS_AI_BOOST_DEFAULT),
    )
    cfg.ma_cross_ai_penalty = max(
        0.0,
        _safe_float(control.get("ma_cross_ai_penalty"), MA_CROSS_AI_PENALTY_DEFAULT),
    )
    cfg.tech_indicators_enabled = _safe_bool(
        control.get("tech_indicators_enabled"),
        TECH_INDICATORS_ENABLED_DEFAULT,
    )
    cfg.rsi_n = max(3, _safe_int(control.get("rsi_n"), RSI_N_DEFAULT))
    cfg.rsi_low = _clamp(_safe_float(control.get("rsi_low"), RSI_LOW_DEFAULT), 1.0, 49.0)
    cfg.rsi_high = _clamp(_safe_float(control.get("rsi_high"), RSI_HIGH_DEFAULT), 51.0, 99.0)
    if cfg.rsi_high <= cfg.rsi_low:
        cfg.rsi_high = min(99.0, cfg.rsi_low + 20.0)
    cfg.bb_n = max(5, _safe_int(control.get("bb_n"), BB_N_DEFAULT))
    cfg.bb_k = max(0.5, _safe_float(control.get("bb_k"), BB_K_DEFAULT))
    cfg.bw_walk_min_count = max(1, _safe_int(control.get("bw_walk_min_count"), BW_WALK_MIN_COUNT_DEFAULT))
    cfg.bb_squeeze_threshold_pct = _clamp(
        _safe_float(control.get("bb_squeeze_threshold_pct"), BB_SQUEEZE_THRESHOLD_PCT_DEFAULT),
        0.1, 5.0,
    )
    cfg.atr_n = max(3, _safe_int(control.get("atr_n"), ATR_N_DEFAULT))
    cfg.atr_low_pct = max(0.0, _safe_float(control.get("atr_low_pct"), ATR_LOW_PCT_DEFAULT))
    cfg.atr_high_pct = max(cfg.atr_low_pct, _safe_float(control.get("atr_high_pct"), ATR_HIGH_PCT_DEFAULT))
    cfg.trend_power_lookback_n = max(
        5,
        _safe_int(control.get("trend_power_lookback_n"), TREND_POWER_LOOKBACK_N_DEFAULT),
    )
    cfg.trend_power_strong_er = _clamp(
        _safe_float(control.get("trend_power_strong_er"), TREND_POWER_STRONG_ER_DEFAULT),
        0.0,
        1.0,
    )
    cfg.tech_ai_boost = max(0.0, _safe_float(control.get("tech_ai_boost"), TECH_AI_BOOST_DEFAULT))
    cfg.tech_ai_penalty = max(0.0, _safe_float(control.get("tech_ai_penalty"), TECH_AI_PENALTY_DEFAULT))
    cfg.chart_pattern_enabled = _safe_bool(
        control.get("chart_pattern_enabled"),
        CHART_PATTERN_ENABLED_DEFAULT,
    )
    cfg.ohlc_timeframe_min = max(1, _safe_int(control.get("ohlc_timeframe_min"), OHLC_TIMEFRAME_MIN_DEFAULT))
    cfg.ohlc_max_bars = max(50, _safe_int(control.get("ohlc_max_bars"), OHLC_MAX_BARS_DEFAULT))
    cfg.chart_pattern_min_bar_ticks = max(
        1,
        _safe_int(control.get("chart_pattern_min_bar_ticks"), CHART_PATTERN_MIN_BAR_TICKS_DEFAULT),
    )
    cfg.chart_pattern_quality_lookback_bars = max(
        3,
        _safe_int(
            control.get("chart_pattern_quality_lookback_bars"),
            CHART_PATTERN_QUALITY_LOOKBACK_BARS_DEFAULT,
        ),
    )
    cfg.swing_lookback = max(1, _safe_int(control.get("swing_lookback"), SWING_LOOKBACK_DEFAULT))
    cfg.double_top_peak_tolerance_pct = max(
        0.01,
        _safe_float(control.get("double_top_peak_tolerance_pct"), DOUBLE_TOP_PEAK_TOLERANCE_PCT_DEFAULT),
    )
    cfg.double_bottom_trough_tolerance_pct = max(
        0.01,
        _safe_float(control.get("double_bottom_trough_tolerance_pct"), DOUBLE_BOTTOM_TROUGH_TOLERANCE_PCT_DEFAULT),
    )
    cfg.shoulder_tolerance_pct = max(
        0.01,
        _safe_float(control.get("shoulder_tolerance_pct"), SHOULDER_TOLERANCE_PCT_DEFAULT),
    )
    cfg.head_min_excess_pct = max(
        0.01,
        _safe_float(control.get("head_min_excess_pct"), HEAD_MIN_EXCESS_PCT_DEFAULT),
    )
    cfg.neckline_break_confirm_bars = max(
        1,
        _safe_int(control.get("neckline_break_confirm_bars"), NECKLINE_BREAK_CONFIRM_BARS_DEFAULT),
    )
    cfg.pattern_ai_boost = max(0.0, _safe_float(control.get("pattern_ai_boost"), PATTERN_AI_BOOST_DEFAULT))
    cfg.pattern_ai_penalty = max(0.0, _safe_float(control.get("pattern_ai_penalty"), PATTERN_AI_PENALTY_DEFAULT))
    cfg.market_phase_enabled = _safe_bool(
        control.get("market_phase_enabled"),
        MARKET_PHASE_ENABLED_DEFAULT,
    )
    cfg.market_phase_block_b_enabled = _safe_bool(
        control.get("market_phase_block_b_enabled"),
        MARKET_PHASE_BLOCK_B_ENABLED_DEFAULT,
    )
    cfg.market_phase_lookback_n = max(
        5,
        _safe_int(control.get("market_phase_lookback_n"), MARKET_PHASE_LOOKBACK_N_DEFAULT),
    )
    cfg.market_phase_flat_slope_pct = max(
        0.0,
        _safe_float(control.get("market_phase_flat_slope_pct"), MARKET_PHASE_FLAT_SLOPE_PCT_DEFAULT),
    )
    cfg.market_phase_flat_gap_pct = max(
        0.0,
        _safe_float(control.get("market_phase_flat_gap_pct"), MARKET_PHASE_FLAT_GAP_PCT_DEFAULT),
    )
    cfg.market_phase_range_max_width_pct = max(
        0.0,
        _safe_float(control.get("market_phase_range_max_width_pct"), MARKET_PHASE_RANGE_MAX_WIDTH_PCT_DEFAULT),
    )
    cfg.market_phase_ai_boost = max(
        0.0,
        _safe_float(control.get("market_phase_ai_boost"), MARKET_PHASE_AI_BOOST_DEFAULT),
    )
    cfg.market_phase_ai_penalty = max(
        0.0,
        _safe_float(control.get("market_phase_ai_penalty"), MARKET_PHASE_AI_PENALTY_DEFAULT),
    )
    cfg.aiba_style_enabled = _safe_bool(
        control.get("aiba_style_enabled"),
        AIBA_STYLE_ENABLED_DEFAULT,
    )
    cfg.aiba_style_ai_enabled = _safe_bool(
        control.get("aiba_style_ai_enabled"),
        AIBA_STYLE_AI_ENABLED_DEFAULT,
    )
    cfg.aiba_ma_short_n = max(
        2,
        _safe_int(control.get("aiba_ma_short_n"), AIBA_MA_SHORT_N_DEFAULT),
    )
    cfg.aiba_ma_mid_n = max(
        cfg.aiba_ma_short_n + 1,
        _safe_int(control.get("aiba_ma_mid_n"), AIBA_MA_MID_N_DEFAULT),
    )
    cfg.aiba_ma_long_n = max(
        cfg.aiba_ma_mid_n + 1,
        _safe_int(control.get("aiba_ma_long_n"), AIBA_MA_LONG_N_DEFAULT),
    )
    cfg.aiba_slope_min_pct = max(
        0.0,
        _safe_float(control.get("aiba_slope_min_pct"), AIBA_SLOPE_MIN_PCT_DEFAULT),
    )
    cfg.aiba_nine_rule_alert_n = max(
        2,
        _safe_int(control.get("aiba_nine_rule_alert_n"), AIBA_NINE_RULE_ALERT_N_DEFAULT),
    )
    cfg.aiba_try_fail_lookback_n = max(
        3,
        _safe_int(control.get("aiba_try_fail_lookback_n"), AIBA_TRY_FAIL_LOOKBACK_N_DEFAULT),
    )
    cfg.aiba_try_fail_min_count = max(
        1,
        _safe_int(control.get("aiba_try_fail_min_count"), AIBA_TRY_FAIL_MIN_COUNT_DEFAULT),
    )
    cfg.aiba_style_ai_boost = max(
        0.0,
        _safe_float(control.get("aiba_style_ai_boost"), AIBA_STYLE_AI_BOOST_DEFAULT),
    )
    cfg.aiba_style_ai_penalty = max(
        0.0,
        _safe_float(control.get("aiba_style_ai_penalty"), AIBA_STYLE_AI_PENALTY_DEFAULT),
    )
    cfg.fib_retracement_enabled = _safe_bool(
        control.get("fib_retracement_enabled"), FIB_RETRACEMENT_ENABLED_DEFAULT
    )
    cfg.fib_golden_zone_boost = max(
        0.0, _safe_float(control.get("fib_golden_zone_boost"), FIB_GOLDEN_ZONE_BOOST_DEFAULT)
    )
    cfg.fib_reversal_penalty = max(
        0.0, _safe_float(control.get("fib_reversal_penalty"), FIB_REVERSAL_PENALTY_DEFAULT)
    )
    cfg.fib_min_swing_range_pct = max(
        0.0, _safe_float(control.get("fib_min_swing_range_pct"), FIB_MIN_SWING_RANGE_PCT_DEFAULT)
    )
    cfg.fib_aiba_combo_boost = max(
        0.0, _safe_float(control.get("fib_aiba_combo_boost"), FIB_AIBA_COMBO_BOOST_DEFAULT)
    )
    cfg.news_entry_block_ahead_min = max(
        0,
        _safe_int(control.get("news_entry_block_ahead_min"), NEWS_ENTRY_BLOCK_AHEAD_MIN_DEFAULT),
    )
    cfg.pre_news_exit_buffer_min = max(
        0,
        _safe_int(control.get("pre_news_exit_buffer_min"), PRE_NEWS_EXIT_BUFFER_MIN_DEFAULT),
    )
    cfg.pre_news_exit_min_hold_min = max(
        0,
        _safe_int(control.get("pre_news_exit_min_hold_min"), PRE_NEWS_EXIT_MIN_HOLD_MIN_DEFAULT),
    )
    cfg.mr_observe_enabled = _safe_bool(
        control.get("mr_observe_enabled"),
        MR_OBSERVE_ENABLED_DEFAULT,
    )
    cfg.mr_bar_min = max(
        1,
        _safe_int(control.get("mr_bar_min"), MR_BAR_MIN_DEFAULT),
    )
    cfg.mr_level_lookback_n = max(
        8,
        _safe_int(control.get("mr_level_lookback_n"), MR_LEVEL_LOOKBACK_N_DEFAULT),
    )
    cfg.mr_spike_lookback_n = max(
        4,
        _safe_int(control.get("mr_spike_lookback_n"), MR_SPIKE_LOOKBACK_N_DEFAULT),
    )
    cfg.mr_spike_min_move_pct = max(
        0.01,
        _safe_float(control.get("mr_spike_min_move_pct"), MR_SPIKE_MIN_MOVE_PCT_DEFAULT),
    )
    cfg.mr_touch_tolerance_pct = max(
        0.01,
        _safe_float(control.get("mr_touch_tolerance_pct"), MR_TOUCH_TOLERANCE_PCT_DEFAULT),
    )
    cfg.mr_ma_cross_lookback_n = max(
        6,
        _safe_int(control.get("mr_ma_cross_lookback_n"), MR_MA_CROSS_LOOKBACK_N_DEFAULT),
    )
    cfg.mr_range_max_ma_slope_pct = max(
        0.0,
        _safe_float(control.get("mr_range_max_ma_slope_pct"), MR_RANGE_MAX_MA_SLOPE_PCT_DEFAULT),
    )
    cfg.mr_range_max_ma_gap_pct = max(
        0.0,
        _safe_float(control.get("mr_range_max_ma_gap_pct"), MR_RANGE_MAX_MA_GAP_PCT_DEFAULT),
    )
    cfg.mr_stop_min_distance_pct = max(
        0.1,
        _safe_float(control.get("mr_stop_min_distance_pct"), MR_STOP_MIN_DISTANCE_PCT_DEFAULT),
    )
    mr_paper_enabled_raw = control.get("mr_paper_enabled")
    if mr_paper_enabled_raw is None:
        # Backward/user-facing alias used in operation notes.
        mr_paper_enabled_raw = control.get("observe_mr_paper_enabled")
    cfg.mr_paper_enabled = _safe_bool(
        mr_paper_enabled_raw,
        MR_PAPER_ENABLED_DEFAULT,
    )
    mr_paper_min_rank = _safe_str(control.get("mr_paper_min_rank"), MR_PAPER_MIN_RANK_DEFAULT).upper()
    cfg.mr_paper_min_rank = mr_paper_min_rank if mr_paper_min_rank in ("A", "B", "C") else MR_PAPER_MIN_RANK_DEFAULT
    cfg.mr_paper_require_trigger = _safe_bool(
        control.get("mr_paper_require_trigger"),
        MR_PAPER_REQUIRE_TRIGGER_DEFAULT,
    )
    cfg.mr_paper_require_reclaim = _safe_bool(
        control.get("mr_paper_require_reclaim"),
        MR_PAPER_REQUIRE_RECLAIM_DEFAULT,
    )
    cfg.one_position_only = _safe_bool(control.get("one_position_only"), ONE_POSITION_ONLY_DEFAULT)

    cfg.fast_n = _safe_int(control.get("fast_n"), FAST_N_DEFAULT)
    cfg.slow_n = _safe_int(control.get("slow_n"), SLOW_N_DEFAULT)
    cfg.max_ltp_history = _safe_int(control.get("max_ltp_history"), MAX_LTP_HISTORY_DEFAULT)

    cfg.lot = _safe_float(control.get("lot"), LOT_DEFAULT)
    cfg.canary_lot = _safe_float(control.get("canary_lot"), CANARY_LOT_DEFAULT)
    cfg.ai_lot_lock_enabled = _safe_bool(
        control.get("ai_lot_lock_enabled"),
        AI_LOT_LOCK_ENABLED_DEFAULT,
    )
    cfg.ai_lot_lock_min_samples = max(
        1,
        _safe_int(control.get("ai_lot_lock_min_samples"), AI_LOT_LOCK_MIN_SAMPLES_DEFAULT),
    )
    cfg.ai_lot_lock_max_lot = max(
        0.0,
        _safe_float(control.get("ai_lot_lock_max_lot"), AI_LOT_LOCK_MAX_LOT_DEFAULT),
    )
    cfg.safety_hard_block = _safe_bool(control.get("safety_hard_block"), SAFETY_HARD_BLOCK_DEFAULT)

    # timeout controls
    tm = (control.get("timeout_mode") or TIMEOUT_MODE_DEFAULT).strip().upper()
    cfg.timeout_mode = tm if tm in ("IGNORE", "EXTEND", "PARTIAL") else TIMEOUT_MODE_DEFAULT
    cfg.max_extend_count = _safe_int(control.get("max_extend_count"), MAX_EXTEND_COUNT_DEFAULT)
    cfg.extend_min = _safe_int(control.get("extend_min"), EXTEND_MIN_DEFAULT)
    cfg.extend_min_bestfav_pct = _safe_float(control.get("extend_min_bestfav_pct"), EXTEND_MIN_BESTFAV_PCT_DEFAULT)
    cfg.partial_tp_trigger_pct = _safe_float(control.get("partial_tp_trigger_pct"), PARTIAL_TP_TRIGGER_PCT_DEFAULT)
    cfg.exit_technical_enabled = _safe_bool(control.get("exit_technical_enabled"), EXIT_TECHNICAL_ENABLED_DEFAULT)
    cfg.exit_technical_only_paper = _safe_bool(control.get("exit_technical_only_paper"), EXIT_TECHNICAL_ONLY_PAPER_DEFAULT)
    cfg.exit_sma_fast_n = max(2, _safe_int(control.get("exit_sma_fast_n"), EXIT_SMA_FAST_N_DEFAULT))
    cfg.exit_sma_slow_n = max(
        cfg.exit_sma_fast_n + 1,
        _safe_int(control.get("exit_sma_slow_n"), EXIT_SMA_SLOW_N_DEFAULT),
    )
    cfg.exit_technical_min_hold_min = max(
        0,
        _safe_int(control.get("exit_technical_min_hold_min"), EXIT_TECHNICAL_MIN_HOLD_MIN_DEFAULT),
    )
    cfg.weak_progress_exit_enabled = _safe_bool(
        control.get("weak_progress_exit_enabled"),
        WEAK_PROGRESS_EXIT_ENABLED_DEFAULT,
    )
    cfg.weak_progress_exit_only_paper = _safe_bool(
        control.get("weak_progress_exit_only_paper"),
        WEAK_PROGRESS_EXIT_ONLY_PAPER_DEFAULT,
    )
    cfg.weak_progress_exit_min_hold_min = max(
        0,
        _safe_int(control.get("weak_progress_exit_min_hold_min"), WEAK_PROGRESS_EXIT_MIN_HOLD_MIN_DEFAULT),
    )
    cfg.weak_progress_exit_max_best_fav_pct = max(
        0.0,
        _safe_float(control.get("weak_progress_exit_max_best_fav_pct"), WEAK_PROGRESS_EXIT_MAX_BESTFAV_PCT_DEFAULT),
    )
    cfg.progress_reversal_exit_enabled = _safe_bool(
        control.get("progress_reversal_exit_enabled"),
        PROGRESS_REVERSAL_EXIT_ENABLED_DEFAULT,
    )
    cfg.progress_reversal_exit_only_paper = _safe_bool(
        control.get("progress_reversal_exit_only_paper"),
        PROGRESS_REVERSAL_EXIT_ONLY_PAPER_DEFAULT,
    )
    cfg.progress_reversal_exit_min_hold_min = max(
        0,
        _safe_int(control.get("progress_reversal_exit_min_hold_min"), PROGRESS_REVERSAL_EXIT_MIN_HOLD_MIN_DEFAULT),
    )
    cfg.progress_reversal_exit_min_best_fav_pct = max(
        0.0,
        _safe_float(
            control.get("progress_reversal_exit_min_best_fav_pct"),
            PROGRESS_REVERSAL_EXIT_MIN_BESTFAV_PCT_DEFAULT,
        ),
    )
    cfg.progress_reversal_exit_max_current_fav_pct = max(
        0.0,
        _safe_float(
            control.get("progress_reversal_exit_max_current_fav_pct"),
            PROGRESS_REVERSAL_EXIT_MAX_CURRENT_FAV_PCT_DEFAULT,
        ),
    )
    cfg.near_tp_giveback_exit_enabled = _safe_bool(
        control.get("near_tp_giveback_exit_enabled"),
        NEAR_TP_GIVEBACK_EXIT_ENABLED_DEFAULT,
    )
    cfg.near_tp_giveback_exit_only_paper = _safe_bool(
        control.get("near_tp_giveback_exit_only_paper"),
        NEAR_TP_GIVEBACK_EXIT_ONLY_PAPER_DEFAULT,
    )
    cfg.near_tp_giveback_exit_min_hold_min = max(
        0,
        _safe_int(control.get("near_tp_giveback_exit_min_hold_min"), NEAR_TP_GIVEBACK_EXIT_MIN_HOLD_MIN_DEFAULT),
    )
    cfg.near_tp_giveback_exit_trigger_ratio = max(
        0.01,
        _safe_float(control.get("near_tp_giveback_exit_trigger_ratio"), NEAR_TP_GIVEBACK_EXIT_TRIGGER_RATIO_DEFAULT),
    )
    cfg.near_tp_giveback_exit_min_giveback_pct = max(
        0.0,
        _safe_float(control.get("near_tp_giveback_exit_min_giveback_pct"), NEAR_TP_GIVEBACK_EXIT_MIN_GIVEBACK_PCT_DEFAULT),
    )
    cfg.near_tp_giveback_exit_max_current_fav_pct = max(
        0.0,
        _safe_float(control.get("near_tp_giveback_exit_max_current_fav_pct"), NEAR_TP_GIVEBACK_EXIT_MAX_CURRENT_FAV_PCT_DEFAULT),
    )
    cfg.no_follow_through_exit_enabled = _safe_bool(
        control.get("no_follow_through_exit_enabled"),
        NO_FOLLOW_THROUGH_EXIT_ENABLED_DEFAULT,
    )
    cfg.no_follow_through_exit_only_paper = _safe_bool(
        control.get("no_follow_through_exit_only_paper"),
        NO_FOLLOW_THROUGH_EXIT_ONLY_PAPER_DEFAULT,
    )
    cfg.no_follow_through_exit_min_hold_min = max(
        0,
        _safe_int(control.get("no_follow_through_exit_min_hold_min"), NO_FOLLOW_THROUGH_EXIT_MIN_HOLD_MIN_DEFAULT),
    )
    cfg.no_follow_through_exit_max_best_fav_pct = max(
        0.0,
        _safe_float(
            control.get("no_follow_through_exit_max_best_fav_pct"),
            NO_FOLLOW_THROUGH_EXIT_MAX_BESTFAV_PCT_DEFAULT,
        ),
    )
    cfg.no_follow_through_exit_max_current_fav_pct = max(
        0.0,
        _safe_float(
            control.get("no_follow_through_exit_max_current_fav_pct"),
            NO_FOLLOW_THROUGH_EXIT_MAX_CURRENT_FAV_PCT_DEFAULT,
        ),
    )
    cfg.early_adverse_exit_enabled = _safe_bool(
        control.get("early_adverse_exit_enabled"),
        EARLY_ADVERSE_EXIT_ENABLED_DEFAULT,
    )
    cfg.early_adverse_exit_only_paper = _safe_bool(
        control.get("early_adverse_exit_only_paper"),
        EARLY_ADVERSE_EXIT_ONLY_PAPER_DEFAULT,
    )
    cfg.early_adverse_exit_min_hold_min = max(
        0.0,
        _safe_float(control.get("early_adverse_exit_min_hold_min"), EARLY_ADVERSE_EXIT_MIN_HOLD_MIN_DEFAULT),
    )
    cfg.early_adverse_exit_loss_pct = min(
        0.0,
        _safe_float(control.get("early_adverse_exit_loss_pct"), EARLY_ADVERSE_EXIT_LOSS_PCT_DEFAULT),
    )
    cfg.early_adverse_exit_max_fav_pct = max(
        0.0,
        _safe_float(control.get("early_adverse_exit_max_fav_pct"), EARLY_ADVERSE_EXIT_MAX_FAV_PCT_DEFAULT),
    )
    cfg.tp_trail_enabled = _safe_bool(
        control.get("tp_trail_enabled"),
        TP_TRAIL_ENABLED_DEFAULT,
    )
    cfg.tp_trail_giveback_pct = max(
        0.01,
        _safe_float(control.get("tp_trail_giveback_pct"), TP_TRAIL_GIVEBACK_PCT_DEFAULT),
    )
    cfg.tp_trail_max_min = max(
        1.0,
        _safe_float(control.get("tp_trail_max_min"), TP_TRAIL_MAX_MIN_DEFAULT),
    )

    # AI (ai_model.json)
    cfg.ai_enabled = bool(ai_model.get("ai_enabled", False))
    cfg.ai_mode = normalize_ai_mode(str(ai_model.get("ai_mode", "ADVISORY")))

    dp = ai_model.get("decision_points", {}) if isinstance(ai_model.get("decision_points"), dict) else {}
    cfg.ai_dp_entry = bool(dp.get("entry", True))
    cfg.ai_dp_extend = bool(dp.get("extend", True))

    th = ai_model.get("confidence_threshold", {}) if isinstance(ai_model.get("confidence_threshold"), dict) else {}
    cfg.ai_th_entry = _clamp(_safe_float(th.get("entry"), 0.65), 0.0, 1.0)
    cfg.ai_th_extend = _clamp(_safe_float(th.get("extend"), 0.60), 0.0, 1.0)

    veto = ai_model.get("ai_veto", {}) if isinstance(ai_model.get("ai_veto"), dict) else {}
    cfg.ai_veto_enabled = bool(veto.get("enabled", True))
    cfg.ai_veto_min_conf = _clamp(_safe_float(veto.get("min_confidence"), 0.80), 0.0, 1.0)

    feats = ai_model.get("features", {}) if isinstance(ai_model.get("features"), dict) else {}
    cfg.ai_use_ma = bool(feats.get("use_ma", True))
    cfg.ai_use_trend = bool(feats.get("use_trend", True))
    cfg.ai_use_spread = bool(feats.get("use_spread", True))
    cfg.ai_use_time = bool(feats.get("use_time", True))
    cfg.ai_use_trendline = bool(feats.get("use_trendline", True))
    cfg.ai_use_channel = bool(feats.get("use_channel", True))
    cfg.ai_use_htf_context = bool(feats.get("use_htf_context", False))
    cfg.ai_use_aiba_style = bool(feats.get("use_aiba_style", True))

    # emergency overrides in CONTROL (optional, for ops)
    if "ai_enabled" in control:
        cfg.ai_enabled = _safe_bool(control.get("ai_enabled"), cfg.ai_enabled)
    if "ai_mode" in control:
        cfg.ai_mode = normalize_ai_mode(control.get("ai_mode"))
    if "ai_use_htf_context" in control:
        cfg.ai_use_htf_context = _safe_bool(control.get("ai_use_htf_context"), cfg.ai_use_htf_context)
    if "ai_use_ma_cross" in control:
        cfg.ai_use_ma_cross = _safe_bool(control.get("ai_use_ma_cross"), cfg.ai_use_ma_cross)
    if "ai_use_technical_indicators" in control:
        cfg.ai_use_technical_indicators = _safe_bool(
            control.get("ai_use_technical_indicators"),
            cfg.ai_use_technical_indicators,
        )
    if "ai_use_chart_patterns" in control:
        cfg.ai_use_chart_patterns = _safe_bool(control.get("ai_use_chart_patterns"), cfg.ai_use_chart_patterns)
    if "ai_use_market_phase" in control:
        cfg.ai_use_market_phase = _safe_bool(control.get("ai_use_market_phase"), cfg.ai_use_market_phase)
    if "ai_use_aiba_style" in control:
        cfg.ai_use_aiba_style = _safe_bool(control.get("ai_use_aiba_style"), cfg.ai_use_aiba_style)

    # per-hour score boost / penalty (W2)
    _gh_src = control.get("ai_score_good_hours") or control.get("ai_train_weekly_good_hours")
    _bh_src = control.get("ai_score_bad_hours") or control.get("ai_train_weekly_bad_hours")
    if _gh_src:
        _gh: set = set()
        for _t in str(_gh_src).split(","):
            try: _gh.add(int(_t.strip()))
            except ValueError: pass
        if _gh: cfg.ai_score_good_hours = _gh
    if _bh_src:
        _bh: set = set()
        for _t in str(_bh_src).split(","):
            try: _bh.add(int(_t.strip()))
            except ValueError: pass
        if _bh: cfg.ai_score_bad_hours = _bh
    if "ai_time_good_hour_boost" in control:
        cfg.ai_time_good_hour_boost = _clamp(
            _safe_float(control.get("ai_time_good_hour_boost"), 0.10), 0.0, 0.30)
    if "ai_time_bad_hour_penalty" in control:
        cfg.ai_time_bad_hour_penalty = _clamp(
            _safe_float(control.get("ai_time_bad_hour_penalty"), 0.10), 0.0, 0.30)

    # live execution controls
    cfg.rollout_mode = _safe_str(control.get("rollout_mode"), ROLLOUT_MODE_DEFAULT).upper()
    cfg.stage_paper_days = max(0, _safe_int(control.get("stage_paper_days"), STAGE_PAPER_DAYS_DEFAULT))
    cfg.stage_canary_days = max(0, _safe_int(control.get("stage_canary_days"), STAGE_CANARY_DAYS_DEFAULT))
    cfg.canary_tp_scale = _clamp(
        _safe_float(control.get("canary_tp_scale"), CANARY_TP_SCALE_DEFAULT),
        0.10,
        1.0,
    )
    cfg.daily_loss_limit_pct = _safe_float(control.get("daily_loss_limit_pct"), DAILY_LOSS_LIMIT_PCT_DEFAULT)
    cfg.daily_profit_stop_pct = _safe_float(control.get("daily_profit_stop_pct"), DAILY_PROFIT_STOP_PCT_DEFAULT)
    cfg.vol_lot_scale_enabled = _safe_bool(control.get("vol_lot_scale_enabled"), VOL_LOT_SCALE_ENABLED_DEFAULT)
    cfg.vol_lot_scale_high_ratio = _clamp(
        _safe_float(control.get("vol_lot_scale_high_ratio"), VOL_LOT_SCALE_HIGH_RATIO_DEFAULT), 0.1, 1.0
    )
    cfg.vol_lot_scale_threshold_pct = max(
        0.001, _safe_float(control.get("vol_lot_scale_threshold_pct"), VOL_LOT_SCALE_THRESHOLD_PCT_DEFAULT)
    )
    cfg.streak_stop_enabled = _safe_bool(control.get("streak_stop_enabled"), STREAK_STOP_ENABLED_DEFAULT)
    cfg.streak_stop_max_losses = max(
        1,
        _safe_int(control.get("streak_stop_max_losses"), STREAK_STOP_MAX_LOSSES_DEFAULT),
    )
    cfg.limit_order_timeout_sec = max(5, _safe_int(control.get("limit_order_timeout_sec"), LIMIT_ORDER_TIMEOUT_SEC_DEFAULT))
    cfg.limit_price_offset_ticks = max(0, _safe_int(control.get("limit_price_offset_ticks"), LIMIT_PRICE_OFFSET_TICKS_DEFAULT))
    cfg.product_code = _safe_str(control.get("product_code"), PRODUCT_CODE_DEFAULT)
    cfg.market_type = _safe_str(control.get("market_type"), MARKET_TYPE_DEFAULT).upper()
    cfg.fx_leverage = max(0.1, _safe_float(control.get("fx_leverage"), FX_LEVERAGE_DEFAULT))
    cfg.fx_collateral_use_ratio = _clamp(
        _safe_float(control.get("fx_collateral_use_ratio"), FX_COLLATERAL_USE_RATIO_DEFAULT),
        0.05,
        1.0,
    )
    cfg.exchange_name = normalize_exchange_name(control.get("exchange_name", EXCHANGE_NAME_DEFAULT))
    cfg.keychain_service = _safe_str(control.get("keychain_service"), KEYCHAIN_SERVICE_DEFAULT)
    cfg.keychain_account_key = _safe_str(control.get("keychain_account_key"), KEYCHAIN_ACCOUNT_KEY_DEFAULT)
    cfg.keychain_account_secret = _safe_str(control.get("keychain_account_secret"), KEYCHAIN_ACCOUNT_SECRET_DEFAULT)

    return cfg


# -------------------------
# Control snapshot (for audit/dashboard)
# -------------------------
def save_control_snapshot_for_audit(
    state: Dict[str, Any],
    cfg: Cfg,
    control_path: Path,
    ai_model: Dict[str, Any],
    ai_path: Path,
    now: datetime,
) -> None:
    try:
        state["_control_snapshot"] = {
            "saved_at_jst": _now_str(now),
            "control_path": str(control_path),
            "ai_model_path": str(ai_path),
            "control": dict(load_control_csv(control_path)),
            "ai_model": dict(ai_model),
        }
        save_state(state)
    except Exception:
        pass


# -------------------------
# AI training log (1 trade => 1 row)
# -------------------------
def _ensure_ai_training_log_ready(path: Path) -> None:
    global _AI_TRAIN_HEADER_READY
    if _AI_TRAIN_HEADER_READY and path.exists():
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    expected = ",".join(AI_TRAIN_FIELDS)
    header_ok = False

    if path.exists():
        try:
            with open(path, "r", encoding="utf-8", newline="") as f:
                first = f.readline().strip()
            header_ok = (first == expected)
        except Exception:
            header_ok = False
    else:
        header_ok = False

    if path.exists() and not header_ok:
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        bak = path.with_name(f"{path.stem}.legacy_{ts}{path.suffix}")
        try:
            path.rename(bak)
        except Exception:
            pass

    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(AI_TRAIN_FIELDS)

    _AI_TRAIN_HEADER_READY = True


def _ai_logged_ids(state: Dict[str, Any]) -> List[str]:
    v = state.get("_ai_train_logged_pos_ids")
    if isinstance(v, list):
        return [_safe_str(x, "") for x in v if _safe_str(x, "")]
    return []


def _has_ai_logged_pos(state: Dict[str, Any], pos_id: str) -> bool:
    if not pos_id:
        return False
    return pos_id in _ai_logged_ids(state)


def _mark_ai_logged_pos(state: Dict[str, Any], pos_id: str) -> None:
    if not pos_id:
        return
    ids = _ai_logged_ids(state)
    if pos_id in ids:
        return
    ids.append(pos_id)
    if len(ids) > 5000:
        ids = ids[-3000:]
    state["_ai_train_logged_pos_ids"] = ids
    save_state(state)


def _append_ai_training_trade_from_exit_row(state: Dict[str, Any], row: Dict[str, Any]) -> None:
    result = _safe_str(row.get("result"), "")
    if result not in AI_TRAIN_EXIT_RESULTS:
        return

    pos_id = _safe_str(row.get("pos_id"), "")
    if not pos_id or _has_ai_logged_pos(state, pos_id):
        return

    op = get_open_pos(state) or {}
    op_pid = _safe_str(op.get("pos_id"), "")
    same_pos = (op_pid == pos_id)

    side = _safe_str(row.get("side"), _safe_str(op.get("side"), "BUY")).upper()
    entry_price = _to_float_or_none(row.get("price"))
    exit_price = _to_float_or_none(row.get("ltp"))
    if entry_price is None and same_pos:
        entry_price = _to_float_or_none(op.get("entry_price"))
    if exit_price is None:
        exit_price = _to_float_or_none(row.get("price"))

    entry_time = _safe_str(op.get("entry_time_jst"), "") if same_pos else ""
    exit_time = _safe_str(row.get("time"), "")
    hold_min: Any = ""
    dt_e = _parse_trade_dt(entry_time) if entry_time else None
    dt_x = _parse_trade_dt(exit_time) if exit_time else None
    if dt_e and dt_x:
        hold_min = int(round((dt_x - dt_e).total_seconds() / 60.0))

    ai_score_entry = _to_float_or_none(op.get("ai_score")) if same_pos else None
    if ai_score_entry is None:
        ai_score_entry = _extract_ai_score_from_note(op.get("ai_note")) if same_pos else None
    if ai_score_entry is None:
        ai_score_entry = _extract_ai_score_from_note(row.get("note"))

    ai_score_extend = _to_float_or_none(op.get("ai_score_extend")) if same_pos else None
    ret_pct = _calc_ret_pct(side, entry_price, exit_price)
    outcome = result.replace("PAPER_EXIT_", "")
    exec_mode = _extract_note_value(row.get("note"), "exec") or _safe_str(op.get("exec_mode"), "")
    stage = _extract_note_value(row.get("note"), "stage") or _safe_str(op.get("effective_stage"), "")

    out_row: Dict[str, Any] = {k: "" for k in AI_TRAIN_FIELDS}
    out_row.update(
        {
            "time": exit_time,
            "pos_id": pos_id,
            "side": side,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "hold_min": hold_min,
            "entry_price": entry_price if entry_price is not None else "",
            "exit_price": exit_price if exit_price is not None else "",
            "ret_pct": round(ret_pct, 6) if ret_pct is not None else "",
            "outcome": outcome,
            "result": result,
            "ai_score": round(ai_score_entry, 6) if ai_score_entry is not None else "",
            "ai_score_extend": round(ai_score_extend, 6) if ai_score_extend is not None else "",
            "spread_entry_pct": op.get("spread_entry_pct", "") if same_pos else "",
            "ma_gap_pct": op.get("ma_gap_pct", "") if same_pos else "",
            "ma_slope_pct_per_step": op.get("ma_slope_pct_per_step", "") if same_pos else "",
            "volatility_pct": op.get("volatility_pct", "") if same_pos else "",
            "trendline_slope_pct_per_step": op.get("trendline_slope_pct_per_step", "") if same_pos else "",
            "channel_pos": op.get("channel_pos", "") if same_pos else "",
            "channel_width_pct": op.get("channel_width_pct", "") if same_pos else "",
            "trend": _safe_str(op.get("trend"), _safe_str(row.get("trend"), "")) if same_pos else _safe_str(row.get("trend"), ""),
            "signal": _safe_str(op.get("signal"), _safe_str(row.get("signal"), "")) if same_pos else _safe_str(row.get("signal"), ""),
            "best_fav": op.get("best_fav", "") if same_pos else "",
            "max_adv": op.get("max_adv", "") if same_pos else "",
            "extend_count": op.get("extend_count", "") if same_pos else "",
            "exec_mode": exec_mode,
            "stage": stage,
            "is_shadow": 1 if INSTANCE_NAME != "main" else 0,
            "fib_zone": _safe_str(op.get("fib_zone"), "") if same_pos else "",
            "fib_wave3_candidate": op.get("fib_wave3_candidate", "") if same_pos else "",
            "aiba_aligned": op.get("aiba_aligned", "") if same_pos else "",
        }
    )

    _ensure_ai_training_log_ready(AI_TRAIN_LOG_FILE)
    with open(AI_TRAIN_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=AI_TRAIN_FIELDS, extrasaction="ignore")
        w.writerow(out_row)
        f.flush()
        os.fsync(f.fileno())
    _mark_ai_logged_pos(state, pos_id)


# -------------------------
# Log: path + writer
# -------------------------
def today_log_path(now: datetime) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    day8 = now.strftime("%Y%m%d")
    return LOGS_DIR / f"trade_log_{day8}.csv"


def _write_row(csv_path: Path, row: Dict[str, Any]) -> None:
    file_exists = csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
        if not file_exists:
            w.writeheader()
        w.writerow(row)
        f.flush()
        os.fsync(f.fileno())


def _update_loss_streak_from_exit_row(state: Dict[str, Any], cfg: Cfg, row: Dict[str, Any]) -> None:
    """
    Update consecutive-loss streak on EXIT rows and apply day-level stop flag.
    """
    result = _safe_str(row.get("result"), "")
    if not result.startswith("PAPER_EXIT_"):
        return

    dt = _parse_trade_dt(row.get("time")) or datetime.now()
    day = dt.strftime("%Y-%m-%d")
    changed = False

    if _safe_str(state.get("_streak_day"), "") != day:
        state["_streak_day"] = day
        state["_streak_consecutive_losses"] = 0
        state["_streak_stop"] = False
        state["_streak_last_ret_pct"] = None
        changed = True

    side = _safe_str(row.get("side"), "").upper()
    entry_price = _to_float_or_none(row.get("price"))
    exit_price = _to_float_or_none(row.get("ltp"))
    ret_pct = _calc_ret_pct(side, entry_price, exit_price)
    if ret_pct is None:
        if changed:
            save_state(state)
        return

    losses = max(0, _safe_int(state.get("_streak_consecutive_losses"), 0))
    losses = losses + 1 if float(ret_pct) < 0.0 else 0
    max_losses = max(1, int(cfg.streak_stop_max_losses))
    stop = bool(cfg.streak_stop_enabled and losses >= max_losses)

    if _safe_int(state.get("_streak_consecutive_losses"), 0) != losses:
        state["_streak_consecutive_losses"] = int(losses)
        changed = True
    if bool(state.get("_streak_stop", False)) != stop:
        state["_streak_stop"] = bool(stop)
        changed = True
    prev_ret = _to_float_or_none(state.get("_streak_last_ret_pct"))
    if prev_ret is None or abs(prev_ret - float(ret_pct)) > 1e-12:
        state["_streak_last_ret_pct"] = float(round(float(ret_pct), 8))
        changed = True

    if changed:
        save_state(state)


def get_loss_streak_guard_status(state: Dict[str, Any], cfg: Cfg, now: datetime) -> Tuple[bool, str]:
    day = now.strftime("%Y-%m-%d")
    changed = False

    if _safe_str(state.get("_streak_day"), "") != day:
        state["_streak_day"] = day
        state["_streak_consecutive_losses"] = 0
        state["_streak_stop"] = False
        state["_streak_last_ret_pct"] = None
        changed = True

    losses = max(0, _safe_int(state.get("_streak_consecutive_losses"), 0))
    max_losses = max(1, int(cfg.streak_stop_max_losses))
    stop = bool(cfg.streak_stop_enabled and losses >= max_losses)
    if bool(state.get("_streak_stop", False)) != stop:
        state["_streak_stop"] = bool(stop)
        changed = True

    if changed:
        save_state(state)

    note = f"streak_losses={losses} max_losses={max_losses} enabled={1 if cfg.streak_stop_enabled else 0}"
    return stop, note


def log_trade_factory(csv_path: Path, state: Dict[str, Any], cfg: Optional[Cfg] = None):
    def log_trade(row: Dict[str, Any]) -> None:
        r = dict(row)

        if not r.get("time"):
            r["time"] = _now_str(datetime.now())

        # normalize result to allowed set
        res = _safe_str(r.get("result"), "")
        if res not in RESULT_ALLOWED:
            # contract: never emit unknown result; fallback to OBSERVE_OK
            note0 = _safe_str(r.get("note"), "")
            note0 = (f"RESULT_NORMALIZED from={res} " + note0).strip()
            r["result"] = "OBSERVE_OK"
            r["note"] = note0

        # pos_id: row -> open_pos -> ""
        pos_id = _safe_str(r.get("pos_id"), "")
        if not pos_id:
            op = get_open_pos(state) or {}
            pos_id = _safe_str(op.get("pos_id"), "")
        r["pos_id"] = pos_id
        r["is_shadow"] = 1 if INSTANCE_NAME != "main" else 0

        # embed pos_id into note
        r["note"] = embed_pos_id(r.get("note"), pos_id if pos_id else None)

        # fill missing fields as empty (do not break csv)
        for k in LOG_FIELDS:
            if k not in r:
                r[k] = ""

        _write_row(csv_path, r)
        if cfg is not None:
            try:
                _update_loss_streak_from_exit_row(state, cfg, r)
            except Exception:
                pass
        try:
            _append_ai_training_trade_from_exit_row(state, r)
        except Exception:
            pass

    return log_trade


# -------------------------
# self-heal contract
# -------------------------
def self_heal_today_log(csv_path: Path, state: Dict[str, Any], now: datetime) -> None:
    """
    If:
      - file missing -> create header
      - header mismatch OR any row has different column count -> self-heal:
          - backup original .bak_selfheal_HHMMSS
          - rebuild main csv with header + only OK rows
          - append bad rows into trade_log_YYYYMMDD_LEGACY_ROWS.csv
    Evidence saved to state._self_heal_last when heal occurs (best effort).
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # missing -> create header and return
    if not csv_path.exists():
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(LOG_FIELDS)
        return

    # read raw lines
    try:
        lines = csv_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return

    if not lines:
        # empty file -> write header
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(LOG_FIELDS)
        return

    # quick parse by csv.reader (preserve raw rows)
    bad_rows: List[List[str]] = []
    ok_rows: List[List[str]] = []

    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return

    header = rows[0] if rows else []
    header_ok = (header == LOG_FIELDS)

    for i, row in enumerate(rows[1:], start=2):
        if len(row) != len(LOG_FIELDS):
            bad_rows.append(row)
            continue
        ok_rows.append(row)

    if header_ok and not bad_rows:
        return  # no heal needed

    # heal
    try:
        hhmmss = now.strftime("%H%M%S")
        bak = csv_path.with_suffix(csv_path.suffix + f".bak_selfheal_{hhmmss}")
        # backup
        bak.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")

        # write rebuilt main
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(LOG_FIELDS)
            for row in ok_rows:
                w.writerow(row)

        # write legacy rows
        legacy_path = csv_path.parent / (csv_path.stem + "_LEGACY_ROWS.csv")
        with open(legacy_path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            # store: original_row (as-is)
            for row in bad_rows:
                w.writerow(row)
            f.flush()
            os.fsync(f.fileno())

        # evidence
        state["_self_heal_last"] = {
            "healed_at_jst": _now_str(now),
            "csv": str(csv_path),
            "backup": str(bak),
            "legacy": str(legacy_path),
            "header_ok_before": header_ok,
            "bad_rows_n": len(bad_rows),
            "ok_rows_n": len(ok_rows),
        }
        save_state(state)
    except Exception:
        return


# -------------------------
# News blocks
# -------------------------
def load_news_blocks(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    blocks: List[Dict[str, str]] = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                d = _safe_str(row.get("date"), "")
                tf = _safe_str(row.get("time_from"), "")
                tt = _safe_str(row.get("time_to"), "")
                label = _safe_str(row.get("label"), "")
                if not tf or not tt or not label:
                    continue
                blocks.append({"date": d, "time_from": tf, "time_to": tt, "label": label})
    except Exception:
        return []
    return blocks


def _hhmm_to_min(s: str) -> Optional[int]:
    s = s.strip()
    if len(s) < 5 or s[2] != ":":
        return None
    try:
        h = int(s[0:2])
        m = int(s[3:5])
        return h * 60 + m
    except Exception:
        return None


def is_news_block_time(now: datetime, blocks: List[Dict[str, str]]) -> Tuple[bool, str]:
    now_date = now.strftime("%Y-%m-%d")
    now_min = now.hour * 60 + now.minute
    for b in blocks:
        if b.get("date") and b["date"] != now_date:
            continue
        a = _hhmm_to_min(b.get("time_from", ""))  # inclusive
        z = _hhmm_to_min(b.get("time_to", ""))    # inclusive
        if a is None or z is None:
            continue
        if a <= now_min <= z:
            return True, b.get("label", "")
    return False, ""


def find_next_news_block(now: datetime, blocks: List[Dict[str, str]], lookahead_min: int) -> Optional[Dict[str, Any]]:
    horizon_min = max(0, int(lookahead_min))
    best: Optional[Dict[str, Any]] = None
    for b in blocks:
        raw_date = _safe_str(b.get("date"), "")
        if raw_date:
            try:
                target_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except Exception:
                continue
        else:
            target_date = now.date()
        a = _hhmm_to_min(b.get("time_from", ""))
        z = _hhmm_to_min(b.get("time_to", ""))
        if a is None or z is None:
            continue
        start_dt = datetime.combine(target_date, dtime(hour=a // 60, minute=a % 60))
        end_dt = datetime.combine(target_date, dtime(hour=z // 60, minute=z % 60))
        if end_dt < start_dt:
            continue
        if now > end_dt:
            continue
        blocked = start_dt <= now <= end_dt
        minutes_until_start = max(0, int((start_dt - now).total_seconds() // 60))
        minutes_until_end = max(0, int((end_dt - now).total_seconds() // 60))
        if not blocked and minutes_until_start > horizon_min:
            continue
        cand = {
            "label": _safe_str(b.get("label"), ""),
            "start_dt": start_dt,
            "end_dt": end_dt,
            "blocked": blocked,
            "minutes_until_start": minutes_until_start,
            "minutes_until_end": minutes_until_end,
        }
        if best is None:
            best = cand
            continue
        cur_key = (0 if cand["blocked"] else 1, cand["minutes_until_start"], cand["minutes_until_end"])
        best_key = (0 if best["blocked"] else 1, best["minutes_until_start"], best["minutes_until_end"])
        if cur_key < best_key:
            best = cand
    return best


def resolve_entry_news_block_status(now: datetime, blocks: List[Dict[str, str]], cfg: Cfg) -> Tuple[bool, str]:
    blocked, label = is_news_block_time(now, blocks)
    if blocked:
        return True, f"NEWS {label}".strip()
    horizon = min(max(0, int(cfg.win_min)), max(0, int(cfg.news_entry_block_ahead_min)))
    if horizon <= 0:
        return False, ""
    nxt = find_next_news_block(now, blocks, horizon)
    if not nxt or bool(nxt.get("blocked")):
        return False, ""
    remain_min = max(0, int(nxt.get("minutes_until_start", 0)))
    label = _safe_str(nxt.get("label"), "")
    return True, f"NEWS_AHEAD {label} remain_min={remain_min} horizon_min={horizon}".strip()


def resolve_pre_news_exit_status(
    now: datetime,
    blocks: List[Dict[str, str]],
    hold_min: Optional[float],
    cfg: Cfg,
) -> Tuple[bool, str]:
    buffer_min = max(0, int(cfg.pre_news_exit_buffer_min))
    if buffer_min <= 0:
        return False, ""
    nxt = find_next_news_block(now, blocks, buffer_min)
    if not nxt:
        return False, ""
    if hold_min is not None and hold_min < float(max(0, int(cfg.pre_news_exit_min_hold_min))):
        return False, ""
    label = _safe_str(nxt.get("label"), "")
    if bool(nxt.get("blocked")):
        return True, f"NEWS_ACTIVE_EXIT {label} remain_end_min={int(nxt.get('minutes_until_end', 0))}".strip()
    return True, f"NEWS_AHEAD_EXIT {label} remain_min={int(nxt.get('minutes_until_start', 0))}".strip()


# -------------------------
# Market data
# -------------------------
def get_ticker(product_code: str = PRODUCT) -> Dict[str, Any]:
    url = f"{BASE_URL}/v1/ticker?product_code={product_code}"
    with urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def calc_spread_pct(best_bid: Optional[float], best_ask: Optional[float], ltp: Optional[float]) -> Optional[float]:
    if best_bid is None or best_ask is None or ltp is None:
        return None
    try:
        if float(ltp) == 0:
            return None
        return (float(best_ask) - float(best_bid)) / float(ltp)
    except Exception:
        return None


# -------------------------
# MA + derived features
# -------------------------
def calc_ma_update_state(
    state: Dict[str, Any],
    ltp: float,
    fast_n: int,
    slow_n: int,
    max_hist: int,
) -> Tuple[Optional[float], Optional[float], str, str]:
    hist = state.get("ltp_history", [])
    if not isinstance(hist, list):
        hist = []
    try:
        hist = [float(x) for x in hist][-max_hist:]
    except Exception:
        hist = []
    try:
        hist.append(float(ltp))
    except Exception:
        return None, None, "UNKNOWN", "NONE"

    if len(hist) > max_hist:
        hist = hist[-max_hist:]

    state["ltp_history"] = hist
    state["_last_ltp"] = float(ltp)

    def sma(vals: List[float], n: int) -> Optional[float]:
        if len(vals) < n:
            return None
        v = vals[-n:]
        return sum(v) / n

    fast = sma(hist, fast_n)
    slow = sma(hist, slow_n)

    if fast is None or slow is None:
        return None, None, "UNKNOWN", "NONE"

    trend = "UP" if fast > slow else "DOWN" if fast < slow else "FLAT"
    signal = "BUY_CANDIDATE" if trend == "UP" else "SELL_CANDIDATE" if trend == "DOWN" else "NONE"
    return round(fast, 2), round(slow, 2), trend, signal


def _sma_at(vals: List[float], end_idx: int, n: int) -> Optional[float]:
    nn = int(n)
    if nn <= 1 or end_idx < nn or end_idx > len(vals):
        return None
    window = vals[end_idx - nn:end_idx]
    if len(window) != nn:
        return None
    return sum(window) / float(nn)


def _ma_cross_type_from_values(
    fast_prev: Optional[float],
    slow_prev: Optional[float],
    fast_now: Optional[float],
    slow_now: Optional[float],
) -> str:
    if None in (fast_prev, slow_prev, fast_now, slow_now):
        return "none"
    if float(fast_prev) <= float(slow_prev) and float(fast_now) > float(slow_now):
        return "golden"
    if float(fast_prev) >= float(slow_prev) and float(fast_now) < float(slow_now):
        return "dead"
    return "none"


def calc_ma_cross_snapshot(
    state: Dict[str, Any],
    *,
    fast_n: int,
    slow_n: int,
    price: Optional[float] = None,
    recent_lookback_n: int = MA_CROSS_RECENT_LOOKBACK_N_DEFAULT,
    min_gap_pct: float = MA_CROSS_MIN_GAP_PCT_DEFAULT,
    slow_slope_min_pct: float = MA_CROSS_SLOW_SLOPE_MIN_PCT_DEFAULT,
    price_filter_enabled: bool = MA_CROSS_PRICE_FILTER_ENABLED_DEFAULT,
) -> Dict[str, Any]:
    hist = _get_ltp_tail(state, 0)
    fast = max(2, int(fast_n))
    slow = max(fast + 1, int(slow_n))
    need = slow + 1
    if len(hist) < need:
        return {
            "cross_type": "none",
            "recent_cross_type": "none",
            "recent_cross_age_bars": None,
            "trend": "UNKNOWN",
            "ma_gap_pct": None,
            "slow_slope_pct": None,
            "price_position": "NA",
            "gap_ok": False,
            "slope_ok": False,
            "price_ok": False,
            "strong": False,
        }

    fast_now = _sma_at(hist, len(hist), fast)
    slow_now = _sma_at(hist, len(hist), slow)
    fast_prev = _sma_at(hist, len(hist) - 1, fast)
    slow_prev = _sma_at(hist, len(hist) - 1, slow)
    cross_type = _ma_cross_type_from_values(fast_prev, slow_prev, fast_now, slow_now)
    trend = "UNKNOWN"
    if fast_now is not None and slow_now is not None:
        trend = "UP" if float(fast_now) > float(slow_now) else "DOWN" if float(fast_now) < float(slow_now) else "FLAT"

    gap_pct = None
    if slow_now is not None and float(slow_now) != 0.0 and fast_now is not None:
        gap_pct = abs(float(fast_now) - float(slow_now)) / abs(float(slow_now)) * 100.0

    slow_slope_pct = None
    if slow_prev is not None and slow_now is not None and float(slow_prev) != 0.0:
        slow_slope_pct = (float(slow_now) - float(slow_prev)) / abs(float(slow_prev)) * 100.0

    price_position = "NA"
    if price is not None and slow_now is not None:
        p = float(price)
        price_position = "above" if p > float(slow_now) else "below" if p < float(slow_now) else "at"

    recent_type = "none"
    recent_age = None
    lookback = max(1, int(recent_lookback_n))
    start_end = max(need, len(hist) - lookback + 1)
    for end_idx in range(start_end, len(hist) + 1):
        f_now = _sma_at(hist, end_idx, fast)
        s_now = _sma_at(hist, end_idx, slow)
        f_prev = _sma_at(hist, end_idx - 1, fast)
        s_prev = _sma_at(hist, end_idx - 1, slow)
        ct = _ma_cross_type_from_values(f_prev, s_prev, f_now, s_now)
        if ct != "none":
            recent_type = ct
            recent_age = len(hist) - end_idx

    min_gap = max(0.0, float(min_gap_pct))
    min_slope = max(0.0, float(slow_slope_min_pct))
    gap_ok = bool(gap_pct is not None and float(gap_pct) >= min_gap)
    if recent_type == "golden":
        slope_ok = bool(slow_slope_pct is not None and float(slow_slope_pct) >= min_slope)
        price_ok = (not bool(price_filter_enabled)) or price_position in ("above", "at")
    elif recent_type == "dead":
        slope_ok = bool(slow_slope_pct is not None and float(slow_slope_pct) <= -min_slope)
        price_ok = (not bool(price_filter_enabled)) or price_position in ("below", "at")
    else:
        slope_ok = False
        price_ok = False
    strong = bool(recent_type != "none" and gap_ok and slope_ok and price_ok)

    return {
        "cross_type": cross_type,
        "recent_cross_type": recent_type,
        "recent_cross_age_bars": recent_age,
        "trend": trend,
        "ma_gap_pct": gap_pct,
        "slow_slope_pct": slow_slope_pct,
        "price_position": price_position,
        "gap_ok": bool(gap_ok),
        "slope_ok": bool(slope_ok),
        "price_ok": bool(price_ok),
        "strong": bool(strong),
    }


def format_ma_cross_note(snapshot: Dict[str, Any], prefix: str = "gc") -> str:
    if not isinstance(snapshot, dict) or not snapshot:
        return ""
    recent = _safe_str(snapshot.get("recent_cross_type"), "none")
    current = _safe_str(snapshot.get("cross_type"), "none")
    if recent == "none" and current == "none":
        return ""
    age = snapshot.get("recent_cross_age_bars")
    gap = snapshot.get("ma_gap_pct")
    slope = snapshot.get("slow_slope_pct")
    parts = [
        f"{prefix}_type={current}",
        f"{prefix}_recent={recent}",
        f"{prefix}_age={'' if age is None else int(age)}",
        f"{prefix}_gap={'' if gap is None else round(float(gap), 6)}",
        f"{prefix}_slow_slope={'' if slope is None else round(float(slope), 6)}",
        f"{prefix}_price={_safe_str(snapshot.get('price_position'), 'NA')}",
        f"{prefix}_strong={1 if bool(snapshot.get('strong')) else 0}",
    ]
    return " ".join(parts)


def calc_rsi_from_series(series: List[float], n: int) -> Optional[float]:
    nn = max(2, int(n))
    if not isinstance(series, list) or len(series) < nn + 1:
        return None
    try:
        tail = [float(x) for x in series[-(nn + 1):]]
    except Exception:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, len(tail)):
        diff = float(tail[i]) - float(tail[i - 1])
        if diff > 0:
            gains += diff
        elif diff < 0:
            losses += abs(diff)
    avg_gain = gains / float(nn)
    avg_loss = losses / float(nn)
    if avg_loss <= 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calc_bollinger_snapshot_from_series(series: List[float], *, n: int, k: float, price: Optional[float] = None) -> Dict[str, Any]:
    nn = max(5, int(n))
    if not isinstance(series, list) or len(series) < nn:
        return {"available": False, "pos": None, "width_pct": None, "zone": "NA", "breakout": "none"}
    try:
        tail = [float(x) for x in series[-nn:]]
    except Exception:
        return {"available": False, "pos": None, "width_pct": None, "zone": "NA", "breakout": "none"}
    mid = sum(tail) / float(len(tail))
    if mid == 0:
        return {"available": False, "pos": None, "width_pct": None, "zone": "NA", "breakout": "none"}
    var = sum((x - mid) ** 2 for x in tail) / float(len(tail))
    std = math.sqrt(max(0.0, var))
    kk = max(0.5, float(k))
    upper = mid + kk * std
    lower = mid - kk * std
    width = upper - lower
    px = float(price) if price is not None else float(tail[-1])
    pos = None if width <= 0 else (px - lower) / width
    width_pct = abs(width) / abs(mid) * 100.0
    breakout = "upper" if px > upper else "lower" if px < lower else "none"
    if pos is None:
        zone = "NA"
    elif breakout == "upper":
        zone = "break_upper"
    elif breakout == "lower":
        zone = "break_lower"
    elif float(pos) <= 0.20:
        zone = "lower"
    elif float(pos) >= 0.80:
        zone = "upper"
    else:
        zone = "mid"
    return {
        "available": True,
        "mid": mid,
        "upper": upper,
        "lower": lower,
        "pos": pos,
        "width_pct": width_pct,
        "zone": zone,
        "breakout": breakout,
    }


def calc_atr_like_pct_from_series(series: List[float], n: int) -> Optional[float]:
    nn = max(2, int(n))
    if not isinstance(series, list) or len(series) < nn + 1:
        return None
    try:
        tail = [float(x) for x in series[-(nn + 1):]]
    except Exception:
        return None
    moves: List[float] = []
    for i in range(1, len(tail)):
        prev = float(tail[i - 1])
        cur = float(tail[i])
        if prev == 0:
            continue
        moves.append(abs(cur - prev) / abs(prev) * 100.0)
    if not moves:
        return None
    return sum(moves) / float(len(moves))


def update_band_walk_state(state: Dict[str, Any], bb_zone: str, *, min_count: int) -> Dict[str, Any]:
    """±2σ バンドウォーク連続カウンターを更新し、スナップショットを返す。

    bb_zone が "upper"/"break_upper" → buy_n++, sell_n=0
    bb_zone が "lower"/"break_lower" → sell_n++, buy_n=0
    それ以外 (mid/NA) → 両方リセット
    """
    zone = _safe_str(bb_zone, "NA").lower()
    if zone in ("upper", "break_upper"):
        buy_n = int(state.get("_bw_buy_n", 0)) + 1
        sell_n = 0
    elif zone in ("lower", "break_lower"):
        buy_n = 0
        sell_n = int(state.get("_bw_sell_n", 0)) + 1
    else:
        buy_n = 0
        sell_n = 0
    state["_bw_buy_n"] = buy_n
    state["_bw_sell_n"] = sell_n
    active_buy = buy_n >= max(1, int(min_count))
    active_sell = sell_n >= max(1, int(min_count))
    active = "buy" if active_buy else ("sell" if active_sell else "none")
    return {
        "bw_buy_n": buy_n,
        "bw_sell_n": sell_n,
        "bw_active_buy": active_buy,
        "bw_active_sell": active_sell,
        "bw_active": active,
    }


def detect_harami_pattern(bars: List[Dict[str, Any]], *, body_ratio_min: float = 0.40) -> Dict[str, Any]:
    """陽の陰はらみ / 陰の陽はらみ を OHLC バーから検出する。

    陽の陰はらみ (yo_no_in_harami):
        前足=大陽線 (close > open, body/range >= body_ratio_min)
        当足=陰線  (close < open)
        当足の実体が前足の実体に包含される
    陰の陽はらみ (yin_no_yo_harami): 逆パターン（下降トレンドでの反転）
    """
    if len(bars) < 2:
        return {"pattern": "none", "bias": "NEUTRAL"}
    prev = bars[-2]
    curr = bars[-1]
    try:
        p_open = float(prev["open"])
        p_close = float(prev["close"])
        p_high = float(prev["high"])
        p_low = float(prev["low"])
        c_open = float(curr["open"])
        c_close = float(curr["close"])
    except (KeyError, TypeError, ValueError):
        return {"pattern": "none", "bias": "NEUTRAL"}
    p_range = p_high - p_low
    if p_range <= 0:
        return {"pattern": "none", "bias": "NEUTRAL"}
    p_body = abs(p_close - p_open)
    if p_body / p_range < body_ratio_min:
        return {"pattern": "none", "bias": "NEUTRAL"}
    p_body_top = max(p_open, p_close)
    p_body_bot = min(p_open, p_close)
    c_body_top = max(c_open, c_close)
    c_body_bot = min(c_open, c_close)
    if c_body_top > p_body_top or c_body_bot < p_body_bot:
        return {"pattern": "none", "bias": "NEUTRAL"}
    if p_close > p_open and c_close < c_open:
        return {"pattern": "yo_no_in_harami", "bias": "BEARISH"}
    if p_close < p_open and c_close > c_open:
        return {"pattern": "yin_no_yo_harami", "bias": "BULLISH"}
    return {"pattern": "none", "bias": "NEUTRAL"}


def _fetch_crypto_fear_greed(state: Dict[str, Any]) -> Dict[str, Any]:
    """Crypto Fear & Greed Index を alternative.me API から取得（日次キャッシュ）。

    score: 0-100 (Extreme Fear=0-24, Fear=25-49, Neutral=50-74, Greed=75-89, Extreme Greed=90-100)
    API は日次更新（JST 09:00 頃）。同日は state キャッシュを使用しネットワーク呼び出しを省く。
    """
    today8 = datetime.now().strftime("%Y%m%d")
    if str(state.get("_cfg_fetched_day", "")) == today8 and "_cfg_score" in state:
        score = int(state["_cfg_score"])
        return {
            "score": score,
            "class": _safe_str(state.get("_cfg_class"), "NA"),
            "extreme_fear": score <= 24,
            "extreme_greed": score >= 76,
        }
    try:
        import json as _json
        with urlopen("https://api.alternative.me/fng/?limit=1", timeout=5) as _r:
            _data = _json.loads(_r.read().decode("utf-8"))
        _entry = _data["data"][0]
        score = int(_entry["value"])
        cfg_class = str(_entry.get("value_classification", "NA"))
        state["_cfg_score"] = score
        state["_cfg_class"] = cfg_class
        state["_cfg_fetched_day"] = today8
        return {"score": score, "class": cfg_class, "extreme_fear": score <= 24, "extreme_greed": score >= 76}
    except Exception:
        if "_cfg_score" in state:
            score = int(state["_cfg_score"])
            return {
                "score": score,
                "class": _safe_str(state.get("_cfg_class"), "NA"),
                "extreme_fear": score <= 24,
                "extreme_greed": score >= 76,
            }
        return {"score": -1, "class": "NA", "extreme_fear": False, "extreme_greed": False}


def calc_technical_indicator_snapshot(
    state: Dict[str, Any],
    *,
    price: Optional[float],
    cfg: Cfg,
) -> Dict[str, Any]:
    hist = _get_ltp_tail(state, 0)
    rsi = calc_rsi_from_series(hist, int(cfg.rsi_n))
    if rsi is None:
        rsi_zone = "NA"
    elif float(rsi) <= float(cfg.rsi_low):
        rsi_zone = "oversold"
    elif float(rsi) >= float(cfg.rsi_high):
        rsi_zone = "overbought"
    else:
        rsi_zone = "neutral"

    bb = calc_bollinger_snapshot_from_series(hist, n=int(cfg.bb_n), k=float(cfg.bb_k), price=price)

    atr_pct = calc_atr_like_pct_from_series(hist, int(cfg.atr_n))
    if atr_pct is None:
        atr_regime = "NA"
    elif float(atr_pct) <= float(cfg.atr_low_pct):
        atr_regime = "low"
    elif float(atr_pct) >= float(cfg.atr_high_pct):
        atr_regime = "high"
    else:
        atr_regime = "normal"

    trend_power = calc_trend_efficiency_ratio(state, int(cfg.trend_power_lookback_n))
    if trend_power is None:
        trend_power_regime = "NA"
    elif float(trend_power) >= float(cfg.trend_power_strong_er):
        trend_power_regime = "strong"
    elif float(trend_power) <= max(0.10, float(cfg.trend_power_strong_er) * 0.55):
        trend_power_regime = "weak"
    else:
        trend_power_regime = "normal"

    bb_width_pct = bb.get("width_pct")
    bb_squeeze_active = (
        bb_width_pct is not None
        and float(bb_width_pct) < float(cfg.bb_squeeze_threshold_pct)
    )
    return {
        "rsi": rsi,
        "rsi_zone": rsi_zone,
        "bb_pos": bb.get("pos"),
        "bb_width_pct": bb_width_pct,
        "bb_zone": bb.get("zone", "NA"),
        "bb_breakout": bb.get("breakout", "none"),
        "bb_squeeze_active": bb_squeeze_active,
        "atr_pct": atr_pct,
        "atr_regime": atr_regime,
        "trend_power": trend_power,
        "trend_power_regime": trend_power_regime,
    }


def format_technical_indicator_note(snapshot: Dict[str, Any], prefix: str = "ti") -> str:
    if not isinstance(snapshot, dict) or not snapshot:
        return ""
    rsi = snapshot.get("rsi")
    bb_pos = snapshot.get("bb_pos")
    bb_width = snapshot.get("bb_width_pct")
    atr = snapshot.get("atr_pct")
    trend_power = snapshot.get("trend_power")
    bw_buy_n = snapshot.get("bw_buy_n", 0)
    bw_sell_n = snapshot.get("bw_sell_n", 0)
    parts = [
        f"{prefix}_rsi={'' if rsi is None else round(float(rsi), 4)}",
        f"{prefix}_rsi_zone={_safe_str(snapshot.get('rsi_zone'), 'NA')}",
        f"{prefix}_bb_pos={'' if bb_pos is None else round(float(bb_pos), 6)}",
        f"{prefix}_bb_width={'' if bb_width is None else round(float(bb_width), 6)}",
        f"{prefix}_bb_zone={_safe_str(snapshot.get('bb_zone'), 'NA')}",
        f"{prefix}_bb_break={_safe_str(snapshot.get('bb_breakout'), 'none')}",
        f"{prefix}_bb_squeeze={1 if bool(snapshot.get('bb_squeeze_active')) else 0}",
        f"{prefix}_atr={'' if atr is None else round(float(atr), 6)}",
        f"{prefix}_atr_regime={_safe_str(snapshot.get('atr_regime'), 'NA')}",
        f"{prefix}_trend_power={'' if trend_power is None else round(float(trend_power), 6)}",
        f"{prefix}_trend_power_regime={_safe_str(snapshot.get('trend_power_regime'), 'NA')}",
        f"{prefix}_bw_buy_n={int(bw_buy_n)}",
        f"{prefix}_bw_sell_n={int(bw_sell_n)}",
        f"{prefix}_bw_active={_safe_str(snapshot.get('bw_active'), 'none')}",
    ]
    return " ".join(parts)


def _market_phase_break_fields(
    *,
    bars: List[Dict[str, Any]],
    hist: List[float],
) -> Dict[str, Any]:
    previous_high = None
    previous_low = None
    current_high = None
    current_low = None
    if len(bars) >= 2:
        prev = bars[-2]
        cur = bars[-1]
        previous_high = float(prev["high"])
        previous_low = float(prev["low"])
        current_high = float(cur["high"])
        current_low = float(cur["low"])
    elif len(hist) >= 2:
        previous_high = float(hist[-2])
        previous_low = float(hist[-2])
        current_high = float(hist[-1])
        current_low = float(hist[-1])

    up_break = bool(current_high is not None and previous_high is not None and float(current_high) > float(previous_high))
    down_break = bool(current_low is not None and previous_low is not None and float(current_low) < float(previous_low))
    return {
        "previous_high": previous_high,
        "previous_low": previous_low,
        "current_high": current_high,
        "current_low": current_low,
        "up_break": up_break,
        "down_break": down_break,
    }


def _market_phase_candle_fallback(
    bars: List[Dict[str, Any]],
    *,
    price: Optional[float],
    cfg: Cfg,
    break_fields: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    normalized = [_normalize_ohlc_bar(x) for x in list(bars or []) if isinstance(x, dict)]
    normalized = [x for x in normalized if x]
    if len(normalized) < 3:
        return None

    lookback = max(5, int(cfg.market_phase_lookback_n))
    recent = normalized[-min(len(normalized), lookback):]
    if len(recent) < 3:
        return None

    swings = extract_swing_points(recent, min(2, max(1, len(recent) // 4)))
    swing_trend = classify_swing_trend(swings)
    closes = [float(x["close"]) for x in recent]
    highs = [float(x["high"]) for x in recent]
    lows = [float(x["low"]) for x in recent]
    first = closes[0]
    last = closes[-1]
    close_delta_pct = ((last - first) / abs(first) * 100.0) if first != 0.0 else 0.0
    lo = min(lows)
    hi = max(highs)
    mid = (hi + lo) / 2.0
    range_width_pct = ((hi - lo) / abs(mid) * 100.0) if mid != 0.0 else None
    avg_close = sum(closes) / float(len(closes))
    px = float(price) if price is not None else last
    price_position = "above_recent_avg" if px > avg_close else "below_recent_avg" if px < avg_close else "at_recent_avg"
    delta_threshold = max(
        0.03,
        float(cfg.market_phase_flat_gap_pct) * 1.5,
        float(cfg.market_phase_flat_slope_pct) * max(4.0, min(float(len(recent)), float(lookback)) / 2.0),
    )

    phase = "UNKNOWN"
    reason = "NO_CLEAR_PHASE"
    if swing_trend == "UP_TREND":
        phase = "C"
        reason = "SWING_UP"
    elif swing_trend == "DOWN_TREND":
        phase = "A"
        reason = "SWING_DOWN"
    elif close_delta_pct >= delta_threshold:
        phase = "C"
        reason = "OHLC_UP_SOFT"
    elif close_delta_pct <= -delta_threshold:
        phase = "A"
        reason = "OHLC_DOWN_SOFT"
    elif range_width_pct is not None and float(range_width_pct) <= float(cfg.market_phase_range_max_width_pct):
        phase = "B"
        reason = "OHLC_FLAT"
    else:
        return None

    up_break = bool(break_fields.get("up_break"))
    down_break = bool(break_fields.get("down_break"))
    if phase == "C" and up_break:
        momentum = "UP_BREAK"
    elif phase == "A" and down_break:
        momentum = "DOWN_BREAK"
    elif up_break:
        momentum = "UP_BREAK_RAW"
    elif down_break:
        momentum = "DOWN_BREAK_RAW"
    else:
        momentum = "none"

    return {
        "phase": phase,
        "phase_reason": reason,
        "ma_slope_pct": None,
        "ma_gap_pct": None,
        "range_width_pct": range_width_pct,
        "price_position": price_position,
        "previous_high": break_fields.get("previous_high"),
        "previous_low": break_fields.get("previous_low"),
        "current_high": break_fields.get("current_high"),
        "current_low": break_fields.get("current_low"),
        "up_break": up_break,
        "down_break": down_break,
        "momentum": momentum,
    }


def calc_market_phase_snapshot(
    state: Dict[str, Any],
    candles: Optional[List[Dict[str, Any]]],
    *,
    price: Optional[float],
    cfg: Cfg,
) -> Dict[str, Any]:
    hist = _get_ltp_tail(state, 0)
    bars = [_normalize_ohlc_bar(x) for x in list(candles or []) if isinstance(x, dict)]
    bars = [x for x in bars if x is not None]
    break_fields = _market_phase_break_fields(bars=bars, hist=hist)
    fallback = _market_phase_candle_fallback(bars, price=price, cfg=cfg, break_fields=break_fields)
    lookback = max(5, int(cfg.market_phase_lookback_n))
    fast_n = max(2, min(int(cfg.fast_n), lookback))
    slow_n = max(fast_n + 1, min(int(cfg.slow_n), max(fast_n + 1, lookback)))
    if len(hist) < slow_n + 1:
        if fallback is not None:
            return fallback
        return {
            "phase": "UNKNOWN",
            "phase_reason": "NO_CLEAR_PHASE",
            "ma_slope_pct": None,
            "ma_gap_pct": None,
            "range_width_pct": None,
            "price_position": "NA",
            "previous_high": break_fields.get("previous_high"),
            "previous_low": break_fields.get("previous_low"),
            "current_high": break_fields.get("current_high"),
            "current_low": break_fields.get("current_low"),
            "up_break": bool(break_fields.get("up_break")),
            "down_break": bool(break_fields.get("down_break")),
            "momentum": "none",
        }

    fast_now = _sma_at(hist, len(hist), fast_n)
    slow_now = _sma_at(hist, len(hist), slow_n)
    slow_prev = _sma_at(hist, len(hist) - 1, slow_n)
    if fast_now is None or slow_now is None or slow_prev is None:
        if fallback is not None:
            return fallback
        return {
            "phase": "UNKNOWN",
            "phase_reason": "NO_CLEAR_PHASE",
            "ma_slope_pct": None,
            "ma_gap_pct": None,
            "range_width_pct": None,
            "price_position": "NA",
            "previous_high": break_fields.get("previous_high"),
            "previous_low": break_fields.get("previous_low"),
            "current_high": break_fields.get("current_high"),
            "current_low": break_fields.get("current_low"),
            "up_break": bool(break_fields.get("up_break")),
            "down_break": bool(break_fields.get("down_break")),
            "momentum": "none",
        }

    ma_gap_pct = 0.0
    if float(slow_now) != 0.0:
        ma_gap_pct = (float(fast_now) - float(slow_now)) / abs(float(slow_now)) * 100.0
    ma_slope_pct = 0.0
    if float(slow_prev) != 0.0:
        ma_slope_pct = (float(slow_now) - float(slow_prev)) / abs(float(slow_prev)) * 100.0

    tail = hist[-lookback:]
    range_width_pct = None
    if tail:
        lo = min(float(x) for x in tail)
        hi = max(float(x) for x in tail)
        mid = (hi + lo) / 2.0
        if mid != 0:
            range_width_pct = (hi - lo) / abs(mid) * 100.0

    px = float(price) if price is not None else float(hist[-1])
    price_position = "above_fast" if px > float(fast_now) else "below_fast" if px < float(fast_now) else "at_fast"

    flat_slope = abs(float(ma_slope_pct)) <= float(cfg.market_phase_flat_slope_pct)
    flat_gap = abs(float(ma_gap_pct)) <= float(cfg.market_phase_flat_gap_pct)
    flat_range = (
        range_width_pct is not None
        and float(range_width_pct) <= float(cfg.market_phase_range_max_width_pct)
    )
    if flat_slope and flat_gap and flat_range:
        phase = "B"
        reason = "MA_FLAT"
    elif float(ma_slope_pct) > float(cfg.market_phase_flat_slope_pct) and float(fast_now) > float(slow_now) and px >= float(fast_now):
        phase = "C"
        reason = "MA_UP"
    elif float(ma_slope_pct) < -float(cfg.market_phase_flat_slope_pct) and float(fast_now) < float(slow_now) and px <= float(fast_now):
        phase = "A"
        reason = "MA_DOWN"
    elif float(fast_now) > float(slow_now):
        phase = "C"
        reason = "MA_UP_SOFT"
    elif float(fast_now) < float(slow_now):
        phase = "A"
        reason = "MA_DOWN_SOFT"
    else:
        phase = "UNKNOWN"
        reason = "NO_CLEAR_PHASE"

    if phase == "UNKNOWN" and fallback is not None:
        phase = str(fallback.get("phase", phase))
        reason = str(fallback.get("phase_reason", reason))
        price_position = str(fallback.get("price_position", price_position))
        if fallback.get("range_width_pct") is not None:
            range_width_pct = fallback.get("range_width_pct")

    previous_high = break_fields.get("previous_high")
    previous_low = break_fields.get("previous_low")
    current_high = break_fields.get("current_high")
    current_low = break_fields.get("current_low")
    up_break = bool(break_fields.get("up_break"))
    down_break = bool(break_fields.get("down_break"))
    if phase == "C" and up_break:
        momentum = "UP_BREAK"
    elif phase == "A" and down_break:
        momentum = "DOWN_BREAK"
    elif up_break:
        momentum = "UP_BREAK_RAW"
    elif down_break:
        momentum = "DOWN_BREAK_RAW"
    else:
        momentum = "none"

    return {
        "phase": phase,
        "phase_reason": reason,
        "ma_slope_pct": ma_slope_pct,
        "ma_gap_pct": ma_gap_pct,
        "range_width_pct": range_width_pct,
        "price_position": price_position,
        "previous_high": previous_high,
        "previous_low": previous_low,
        "current_high": current_high,
        "current_low": current_low,
        "up_break": up_break,
        "down_break": down_break,
        "momentum": momentum,
    }


def format_market_phase_note(snapshot: Dict[str, Any], prefix: str = "phase") -> str:
    if not isinstance(snapshot, dict) or not snapshot:
        return ""
    phase = _safe_str(snapshot.get("phase"), "UNKNOWN")
    if phase == "UNKNOWN" and _safe_str(snapshot.get("phase_reason"), "") == "":
        return ""
    prev_high = snapshot.get("previous_high")
    prev_low = snapshot.get("previous_low")
    slope = snapshot.get("ma_slope_pct")
    gap = snapshot.get("ma_gap_pct")
    width = snapshot.get("range_width_pct")
    return " ".join([
        f"{prefix}={phase}",
        f"{prefix}_reason={_safe_str(snapshot.get('phase_reason'), 'NO_CLEAR_PHASE')}",
        f"{prefix}_slope={'' if slope is None else round(float(slope), 6)}",
        f"{prefix}_gap={'' if gap is None else round(float(gap), 6)}",
        f"{prefix}_range={'' if width is None else round(float(width), 6)}",
        f"{prefix}_price={_safe_str(snapshot.get('price_position'), 'NA')}",
        f"prev_high={'' if prev_high is None else round(float(prev_high), 2)}",
        f"prev_low={'' if prev_low is None else round(float(prev_low), 2)}",
        f"up_break={1 if bool(snapshot.get('up_break')) else 0}",
        f"down_break={1 if bool(snapshot.get('down_break')) else 0}",
        f"{prefix}_momentum={_safe_str(snapshot.get('momentum'), 'none')}",
    ])


def update_market_phase_transition_state(
    state: Dict[str, Any],
    snapshot: Dict[str, Any],
    now: datetime,
) -> str:
    if not isinstance(state, dict) or not isinstance(snapshot, dict):
        return ""
    phase = _safe_str(snapshot.get("phase"), "UNKNOWN").upper()
    if phase not in {"A", "B", "C"}:
        return ""

    prev_obj = state.get("_market_phase", {})
    if not isinstance(prev_obj, dict):
        prev_obj = {}
    prev_phase = _safe_str(prev_obj.get("phase"), "").upper()
    ts = _now_str(now)
    compact_ts = ts.replace(" ", "_")

    state["_market_phase"] = {
        "phase": phase,
        "phase_reason": _safe_str(snapshot.get("phase_reason"), ""),
        "momentum": _safe_str(snapshot.get("momentum"), "none"),
        "previous_phase": prev_phase if prev_phase in {"A", "B", "C"} else "",
        "transition": _safe_str(prev_obj.get("transition"), ""),
        "changed_at_jst": _safe_str(prev_obj.get("changed_at_jst"), ""),
        "updated_at_jst": ts,
    }
    if prev_phase not in {"A", "B", "C"} or prev_phase == phase:
        return ""

    transition = f"{prev_phase}->{phase}"
    state["_market_phase"].update({
        "transition": transition,
        "changed_at_jst": ts,
    })
    return " ".join([
        f"phase_transition={transition}",
        f"phase_prev={prev_phase}",
        f"phase_changed_at={compact_ts}",
    ])


def _aiba_try_fail_count_from_bars(candles: Optional[List[Dict[str, Any]]], lookback_n: int) -> int:
    bars = [_normalize_ohlc_bar(x) for x in list(candles or []) if isinstance(x, dict)]
    bars = [x for x in bars if x is not None]
    if len(bars) < 3:
        return 0
    tail = bars[-max(3, int(lookback_n)):]
    count = 0
    # "トライ届かず"を安全に数値化するため、直近から「高値未更新 + 終値下落」が
    # 連続している回数を数える。発注条件ではなく、弱含みの観測ラベルとして使う。
    for i in range(len(tail) - 1, 0, -1):
        cur = tail[i]
        prev = tail[i - 1]
        if float(cur["high"]) < float(prev["high"]) and float(cur["close"]) < float(prev["close"]):
            count += 1
        else:
            break
    return int(count)


def calc_aiba_style_snapshot(
    state: Dict[str, Any],
    candles: Optional[List[Dict[str, Any]]],
    *,
    price: Optional[float],
    cfg: Cfg,
) -> Dict[str, Any]:
    hist = _get_ltp_tail(state, 0)
    short_n = max(2, int(cfg.aiba_ma_short_n))
    mid_n = max(short_n + 1, int(cfg.aiba_ma_mid_n))
    long_n = max(mid_n + 1, int(cfg.aiba_ma_long_n))
    need = long_n + 1
    if len(hist) < need:
        return {
            "available": False,
            "trend": "UNKNOWN",
            "cross_type": "NONE",
            "ppp_flag": "NONE",
            "nine_rule_count": 0,
            "nine_rule_alert": False,
            "try_fail_flag": False,
            "try_fail_count": 0,
        }

    ma_short = _sma_at(hist, len(hist), short_n)
    ma_mid = _sma_at(hist, len(hist), mid_n)
    ma_long = _sma_at(hist, len(hist), long_n)
    ma_short_prev = _sma_at(hist, len(hist) - 1, short_n)
    ma_mid_prev = _sma_at(hist, len(hist) - 1, mid_n)
    ma_long_prev = _sma_at(hist, len(hist) - 1, long_n)
    if None in (ma_short, ma_mid, ma_long, ma_short_prev, ma_mid_prev, ma_long_prev):
        return {
            "available": False,
            "trend": "UNKNOWN",
            "cross_type": "NONE",
            "ppp_flag": "NONE",
            "nine_rule_count": 0,
            "nine_rule_alert": False,
            "try_fail_flag": False,
            "try_fail_count": 0,
        }

    def _slope(now_v: float, prev_v: float) -> float:
        return 0.0 if float(prev_v) == 0.0 else (float(now_v) - float(prev_v)) / abs(float(prev_v)) * 100.0

    short_slope = _slope(float(ma_short), float(ma_short_prev))
    mid_slope = _slope(float(ma_mid), float(ma_mid_prev))
    long_slope = _slope(float(ma_long), float(ma_long_prev))
    slope_min = float(cfg.aiba_slope_min_pct)

    if float(ma_short) > float(ma_mid) > float(ma_long) and short_slope >= slope_min and mid_slope >= slope_min:
        trend = "UP"
    elif float(ma_short) < float(ma_mid) < float(ma_long) and short_slope <= -slope_min and mid_slope <= -slope_min:
        trend = "DOWN"
    else:
        trend = "NEUTRAL"

    raw_cross = _ma_cross_type_from_values(ma_short_prev, ma_mid_prev, ma_short, ma_mid)
    if raw_cross == "golden" and short_slope >= slope_min and mid_slope >= slope_min:
        cross_type = "KUCHIBASHI"
    elif raw_cross == "dead" and short_slope <= -slope_min and mid_slope <= -slope_min:
        cross_type = "REV_KUCHIBASHI"
    else:
        cross_type = "NONE"

    px = float(price) if price is not None else float(hist[-1])
    if float(ma_short) > float(ma_mid) > float(ma_long) and px > float(ma_short):
        ppp_flag = "PPP"
    elif float(ma_short) < float(ma_mid) < float(ma_long) and px < float(ma_short):
        ppp_flag = "REV_PPP"
    else:
        ppp_flag = "NONE"

    run_count = 0
    for end_idx in range(len(hist), need - 1, -1):
        s = _sma_at(hist, end_idx, short_n)
        m = _sma_at(hist, end_idx, mid_n)
        l = _sma_at(hist, end_idx, long_n)
        if None in (s, m, l):
            break
        if trend == "UP" and float(s) > float(m) > float(l):
            run_count += 1
        elif trend == "DOWN" and float(s) < float(m) < float(l):
            run_count += 1
        else:
            break
    if trend == "NEUTRAL":
        run_count = 0

    try_fail_count = _aiba_try_fail_count_from_bars(candles, int(cfg.aiba_try_fail_lookback_n))
    try_fail_flag = bool(try_fail_count >= int(cfg.aiba_try_fail_min_count))
    nine_alert = bool(run_count >= int(cfg.aiba_nine_rule_alert_n))

    return {
        "available": True,
        "ma_short": ma_short,
        "ma_mid": ma_mid,
        "ma_long": ma_long,
        "ma_short_slope_pct": short_slope,
        "ma_mid_slope_pct": mid_slope,
        "ma_long_slope_pct": long_slope,
        "trend": trend,
        "cross_type": cross_type,
        "ppp_flag": ppp_flag,
        "nine_rule_count": int(run_count),
        "nine_rule_alert": bool(nine_alert),
        "try_fail_flag": bool(try_fail_flag),
        "try_fail_count": int(try_fail_count),
    }


def format_aiba_style_note(snapshot: Dict[str, Any], prefix: str = "aiba") -> str:
    if not isinstance(snapshot, dict) or not snapshot:
        return ""
    trend = _safe_str(snapshot.get("trend"), "UNKNOWN")
    cross = _safe_str(snapshot.get("cross_type"), "NONE")
    ppp = _safe_str(snapshot.get("ppp_flag"), "NONE")
    if trend == "UNKNOWN" and cross == "NONE" and ppp == "NONE":
        return ""
    ma_short = snapshot.get("ma_short")
    ma_mid = snapshot.get("ma_mid")
    ma_long = snapshot.get("ma_long")
    short_slope = snapshot.get("ma_short_slope_pct")
    mid_slope = snapshot.get("ma_mid_slope_pct")
    long_slope = snapshot.get("ma_long_slope_pct")
    return " ".join([
        f"{prefix}_trend={trend}",
        f"{prefix}_cross={cross}",
        f"{prefix}_ppp={ppp}",
        f"{prefix}_ma5={'' if ma_short is None else round(float(ma_short), 2)}",
        f"{prefix}_ma20={'' if ma_mid is None else round(float(ma_mid), 2)}",
        f"{prefix}_ma_long={'' if ma_long is None else round(float(ma_long), 2)}",
        f"{prefix}_ma5_slope={'' if short_slope is None else round(float(short_slope), 6)}",
        f"{prefix}_ma20_slope={'' if mid_slope is None else round(float(mid_slope), 6)}",
        f"{prefix}_ma_long_slope={'' if long_slope is None else round(float(long_slope), 6)}",
        f"{prefix}_run={int(_safe_int(snapshot.get('nine_rule_count'), 0))}",
        f"{prefix}_9={1 if bool(snapshot.get('nine_rule_alert')) else 0}",
        f"{prefix}_try_fail={1 if bool(snapshot.get('try_fail_flag')) else 0}",
        f"{prefix}_try_fail_count={int(_safe_int(snapshot.get('try_fail_count'), 0))}",
    ])


def _floor_time_to_bucket(now: datetime, timeframe_min: int) -> datetime:
    tf = max(1, int(timeframe_min))
    minute = (int(now.minute) // tf) * tf
    return now.replace(minute=minute, second=0, microsecond=0)


def _normalize_ohlc_bar(bar: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        ts = _safe_str(bar.get("timestamp"), "")
        o = float(bar.get("open"))
        h = float(bar.get("high"))
        l = float(bar.get("low"))
        c = float(bar.get("close"))
        ticks = max(1, _safe_int(bar.get("ticks"), 1))
    except Exception:
        return None
    if h < l:
        h, l = l, h
    return {
        "timestamp": ts,
        "open": o,
        "high": max(h, o, c),
        "low": min(l, o, c),
        "close": c,
        "ticks": ticks,
    }


def update_ohlc_state(
    state: Dict[str, Any],
    *,
    now: datetime,
    price: float,
    timeframe_min: int,
    max_bars: int,
) -> List[Dict[str, Any]]:
    """Build lightweight OHLC bars from ticker ltp without changing external data sources."""
    bucket = _floor_time_to_bucket(now, timeframe_min)
    bucket_s = _now_str(bucket)
    px = float(price)
    cur = state.get("_ohlc_current")
    if not isinstance(cur, dict) or _safe_str(cur.get("timestamp"), "") != bucket_s:
        prev = _normalize_ohlc_bar(cur) if isinstance(cur, dict) else None
        hist_raw = state.get("ohlc_history")
        hist: List[Dict[str, Any]] = []
        if isinstance(hist_raw, list):
            for item in hist_raw:
                if isinstance(item, dict):
                    norm = _normalize_ohlc_bar(item)
                    if norm:
                        hist.append(norm)
        if prev:
            if not hist or _safe_str(hist[-1].get("timestamp"), "") != _safe_str(prev.get("timestamp"), ""):
                hist.append(prev)
            else:
                hist[-1] = prev
        state["ohlc_history"] = hist[-max(1, int(max_bars)):]
        state["_ohlc_current"] = {
            "timestamp": bucket_s,
            "open": px,
            "high": px,
            "low": px,
            "close": px,
            "ticks": 1,
            "last_update_jst": _now_str(now),
        }
    else:
        cur_open = _safe_float(cur.get("open"), px)
        cur_high = max(_safe_float(cur.get("high"), px), px)
        cur_low = min(_safe_float(cur.get("low"), px), px)
        cur_ticks = max(0, _safe_int(cur.get("ticks"), 0))
        state["_ohlc_current"] = {
            "timestamp": bucket_s,
            "open": cur_open,
            "high": cur_high,
            "low": cur_low,
            "close": px,
            "ticks": cur_ticks + 1,
            "last_update_jst": _now_str(now),
        }
    return get_ohlc_bars(state, include_current=True, max_bars=max_bars)


def get_ohlc_bars(
    state: Dict[str, Any],
    *,
    include_current: bool = True,
    max_bars: int = OHLC_MAX_BARS_DEFAULT,
) -> List[Dict[str, Any]]:
    bars: List[Dict[str, Any]] = []
    hist = state.get("ohlc_history")
    if isinstance(hist, list):
        for item in hist:
            if isinstance(item, dict):
                norm = _normalize_ohlc_bar(item)
                if norm:
                    bars.append(norm)
    if include_current:
        cur = state.get("_ohlc_current")
        if isinstance(cur, dict):
            norm = _normalize_ohlc_bar(cur)
            if norm:
                if bars and _safe_str(bars[-1].get("timestamp"), "") == _safe_str(norm.get("timestamp"), ""):
                    bars[-1] = norm
                else:
                    bars.append(norm)
    return bars[-max(1, int(max_bars)):]


def extract_swing_points(candles: List[Dict[str, Any]], lookback: int = SWING_LOOKBACK_DEFAULT) -> Dict[str, List[Dict[str, Any]]]:
    n = max(1, int(lookback))
    highs: List[Dict[str, Any]] = []
    lows: List[Dict[str, Any]] = []
    if not isinstance(candles, list) or len(candles) < (n * 2 + 1):
        return {"highs": highs, "lows": lows}
    for i in range(n, len(candles) - n):
        try:
            h = float(candles[i].get("high"))
            l = float(candles[i].get("low"))
            left = candles[i - n:i]
            right = candles[i + 1:i + n + 1]
            around_high = [float(x.get("high")) for x in (left + right)]
            around_low = [float(x.get("low")) for x in (left + right)]
        except Exception:
            continue
        if around_high and h > max(around_high):
            highs.append({"index": i, "price": h, "timestamp": _safe_str(candles[i].get("timestamp"), "")})
        if around_low and l < min(around_low):
            lows.append({"index": i, "price": l, "timestamp": _safe_str(candles[i].get("timestamp"), "")})
    return {"highs": highs, "lows": lows}


def classify_swing_trend(swings: Dict[str, List[Dict[str, Any]]]) -> str:
    highs = list(swings.get("highs") or [])
    lows = list(swings.get("lows") or [])
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL"
    h1, h2 = float(highs[-2]["price"]), float(highs[-1]["price"])
    l1, l2 = float(lows[-2]["price"]), float(lows[-1]["price"])
    if h2 > h1 and l2 > l1:
        return "UP_TREND"
    if h2 < h1 and l2 < l1:
        return "DOWN_TREND"
    return "NEUTRAL"


def calc_fibonacci_retracement_snapshot(
    swings: Dict[str, List[Dict[str, Any]]],
    price: float,
    side: str,
    min_swing_range_pct: float = FIB_MIN_SWING_RANGE_PCT_DEFAULT,
) -> Dict[str, Any]:
    """Elliott Wave Fibonacci gate.
    Wave 2 pullbacks land in 38.2-61.8% of wave 1 (golden zone).
    Price inside golden zone = wave 3 candidate (highest-probability impulse entry).
    depth = how far price has pulled back from the in-trend extreme.
    BUY: depth = (swing_high - price) / range  (0=at high, 1=at low)
    SELL: depth = (price - swing_low) / range  (0=at low, 1=at high)
    """
    result: Dict[str, Any] = {
        "fib_retrace_pct": None,
        "fib_zone": "NA",
        "fib_in_golden_zone": False,
        "fib_wave3_candidate": False,
        "fib_swing_range_pct": None,
    }
    highs = list(swings.get("highs") or [])
    lows = list(swings.get("lows") or [])
    if not highs or not lows or price <= 0:
        return result
    try:
        sh = float(highs[-1]["price"])
        sl = float(lows[-1]["price"])
        move = sh - sl
        if move <= 0 or sl <= 0:
            return result
        swing_range_pct = move / price * 100.0
        result["fib_swing_range_pct"] = round(swing_range_pct, 3)
        if swing_range_pct < min_swing_range_pct:
            return result
        depth = ((sh - price) / move) if side == "BUY" else ((price - sl) / move)
        depth = max(0.0, min(1.0, depth))
        result["fib_retrace_pct"] = round(depth * 100, 1)
        if depth < 0.236:
            result["fib_zone"] = "CONTINUATION"
        elif depth < 0.382:
            result["fib_zone"] = "SHALLOW"
        elif depth <= 0.618:
            result["fib_zone"] = "GOLDEN"
        elif depth <= 0.786:
            result["fib_zone"] = "DEEP"
        else:
            result["fib_zone"] = "REVERSAL"
        in_golden = 0.382 <= depth <= 0.618
        result["fib_in_golden_zone"] = in_golden
        result["fib_wave3_candidate"] = in_golden
    except Exception:
        pass
    return result


def calc_ohlc_quality(
    candles: List[Dict[str, Any]],
    *,
    min_ticks: int,
    lookback_bars: int,
) -> Dict[str, Any]:
    bars = [_normalize_ohlc_bar(x) for x in list(candles or []) if isinstance(x, dict)]
    bars = [x for x in bars if x]
    if not bars:
        return {"quality": "NA", "avg_ticks": 0.0, "low_tick_bars": 0, "bars_checked": 0}
    n = min(len(bars), max(1, int(lookback_bars)))
    tail = bars[-n:]
    min_t = max(1, int(min_ticks))
    ticks = [max(1, int(_safe_int(x.get("ticks"), 1))) for x in tail]
    low_tick_bars = sum(1 for x in ticks if x < min_t)
    avg_ticks = sum(ticks) / float(len(ticks))
    if len(tail) < max(3, int(lookback_bars) // 2):
        quality = "NA"
    elif low_tick_bars > 0:
        quality = "THIN"
    else:
        quality = "OK"
    return {
        "quality": quality,
        "avg_ticks": avg_ticks,
        "low_tick_bars": int(low_tick_bars),
        "bars_checked": int(len(tail)),
    }


def _pct_diff(a: float, b: float) -> float:
    denom = (abs(float(a)) + abs(float(b))) / 2.0
    if denom <= 0:
        return 0.0
    return abs(float(a) - float(b)) / denom * 100.0


def _confirm_close_break(candles: List[Dict[str, Any]], neckline: float, direction: str, bars: int) -> bool:
    n = max(1, int(bars))
    if len(candles) < n:
        return False
    closes: List[float] = []
    try:
        closes = [float(x.get("close")) for x in candles[-n:]]
    except Exception:
        return False
    if direction == "below":
        return all(c < float(neckline) for c in closes)
    if direction == "above":
        return all(c > float(neckline) for c in closes)
    return False


def _pattern_payload(
    *,
    name: str,
    stage: str,
    bias: str,
    neckline: Optional[float],
    trend: str,
    confirmed: bool,
    swing_highs: List[Dict[str, Any]],
    swing_lows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "pattern_name": name,
        "pattern_stage": stage,
        "pattern_bias": bias,
        "neckline": neckline,
        "pattern_trend": trend,
        "pattern_confirmed": bool(confirmed),
        "pattern_quality": "NA",
        "pattern_avg_ticks": 0.0,
        "pattern_low_tick_bars": 0,
        "pattern_bars_checked": 0,
        "swing_high_1": swing_highs[-2]["price"] if len(swing_highs) >= 2 else None,
        "swing_high_2": swing_highs[-1]["price"] if len(swing_highs) >= 1 else None,
        "swing_low_1": swing_lows[-2]["price"] if len(swing_lows) >= 2 else None,
        "swing_low_2": swing_lows[-1]["price"] if len(swing_lows) >= 1 else None,
    }


def calc_chart_pattern_snapshot(candles: List[Dict[str, Any]], cfg: Cfg) -> Dict[str, Any]:
    bars = [_normalize_ohlc_bar(x) for x in list(candles or []) if isinstance(x, dict)]
    bars = [x for x in bars if x]
    swings = extract_swing_points(bars, int(cfg.swing_lookback))
    highs = list(swings.get("highs") or [])
    lows = list(swings.get("lows") or [])
    trend = classify_swing_trend(swings)
    quality = calc_ohlc_quality(
        bars,
        min_ticks=int(cfg.chart_pattern_min_bar_ticks),
        lookback_bars=int(cfg.chart_pattern_quality_lookback_bars),
    )
    empty = _pattern_payload(
        name="NONE",
        stage="NONE",
        bias="NEUTRAL",
        neckline=None,
        trend=trend,
        confirmed=False,
        swing_highs=highs,
        swing_lows=lows,
    )
    empty.update({
        "pattern_quality": quality.get("quality", "NA"),
        "pattern_avg_ticks": quality.get("avg_ticks", 0.0),
        "pattern_low_tick_bars": quality.get("low_tick_bars", 0),
        "pattern_bars_checked": quality.get("bars_checked", 0),
    })
    if len(bars) < 12:
        return empty

    candidates: List[Dict[str, Any]] = []

    if len(highs) >= 2:
        h1, h2 = highs[-2], highs[-1]
        if int(h2["index"]) > int(h1["index"]) + 1:
            between = bars[int(h1["index"]) + 1:int(h2["index"])]
            if between:
                neckline = min(float(x["low"]) for x in between)
                tol = float(cfg.double_top_peak_tolerance_pct)
                if _pct_diff(float(h1["price"]), float(h2["price"])) <= tol:
                    confirmed = _confirm_close_break(bars, neckline, "below", int(cfg.neckline_break_confirm_bars))
                    candidates.append(_pattern_payload(
                        name="DOUBLE_TOP",
                        stage="CONFIRMED" if confirmed else "CANDIDATE",
                        bias="SELL",
                        neckline=neckline,
                        trend=trend,
                        confirmed=confirmed,
                        swing_highs=[h1, h2],
                        swing_lows=lows,
                    ))

    if len(lows) >= 2:
        l1, l2 = lows[-2], lows[-1]
        if int(l2["index"]) > int(l1["index"]) + 1:
            between = bars[int(l1["index"]) + 1:int(l2["index"])]
            if between:
                neckline = max(float(x["high"]) for x in between)
                tol = float(cfg.double_bottom_trough_tolerance_pct)
                if _pct_diff(float(l1["price"]), float(l2["price"])) <= tol:
                    confirmed = _confirm_close_break(bars, neckline, "above", int(cfg.neckline_break_confirm_bars))
                    candidates.append(_pattern_payload(
                        name="DOUBLE_BOTTOM",
                        stage="CONFIRMED" if confirmed else "CANDIDATE",
                        bias="BUY",
                        neckline=neckline,
                        trend=trend,
                        confirmed=confirmed,
                        swing_highs=highs,
                        swing_lows=[l1, l2],
                    ))

    if len(highs) >= 3:
        left, head, right = highs[-3], highs[-2], highs[-1]
        left_p = float(left["price"])
        head_p = float(head["price"])
        right_p = float(right["price"])
        shoulders_close = _pct_diff(left_p, right_p) <= float(cfg.shoulder_tolerance_pct)
        head_excess = (
            _pct_diff(head_p, max(left_p, right_p)) >= float(cfg.head_min_excess_pct)
            and head_p > left_p
            and head_p > right_p
        )
        if shoulders_close and head_excess:
            seg1 = bars[int(left["index"]) + 1:int(head["index"])]
            seg2 = bars[int(head["index"]) + 1:int(right["index"])]
            if seg1 and seg2:
                neck1 = min(float(x["low"]) for x in seg1)
                neck2 = min(float(x["low"]) for x in seg2)
                neckline = (neck1 + neck2) / 2.0
                confirmed = _confirm_close_break(bars, neckline, "below", int(cfg.neckline_break_confirm_bars))
                candidates.append(_pattern_payload(
                    name="HEAD_AND_SHOULDERS",
                    stage="CONFIRMED" if confirmed else "CANDIDATE",
                    bias="SELL",
                    neckline=neckline,
                    trend=trend,
                    confirmed=confirmed,
                    swing_highs=[left, head, right],
                    swing_lows=lows,
                ))

    if not candidates:
        return empty

    candidates.sort(key=lambda x: (1 if x.get("pattern_confirmed") else 0, 1 if x.get("pattern_name") == "HEAD_AND_SHOULDERS" else 0), reverse=True)
    out = candidates[0]
    out.update({
        "pattern_quality": quality.get("quality", "NA"),
        "pattern_avg_ticks": quality.get("avg_ticks", 0.0),
        "pattern_low_tick_bars": quality.get("low_tick_bars", 0),
        "pattern_bars_checked": quality.get("bars_checked", 0),
    })
    return out


def format_chart_pattern_note(snapshot: Dict[str, Any], prefix: str = "cp") -> str:
    if not isinstance(snapshot, dict) or not snapshot:
        return ""
    name = _safe_str(snapshot.get("pattern_name"), "NONE")
    stage = _safe_str(snapshot.get("pattern_stage"), "NONE")
    if name == "NONE" and stage == "NONE":
        return ""
    neckline = snapshot.get("neckline")
    return " ".join([
        f"{prefix}_name={name}",
        f"{prefix}_stage={stage}",
        f"{prefix}_bias={_safe_str(snapshot.get('pattern_bias'), 'NEUTRAL')}",
        f"{prefix}_confirmed={1 if bool(snapshot.get('pattern_confirmed')) else 0}",
        f"{prefix}_trend={_safe_str(snapshot.get('pattern_trend'), 'NEUTRAL')}",
        f"{prefix}_neckline={'' if neckline is None else round(float(neckline), 2)}",
        f"{prefix}_quality={_safe_str(snapshot.get('pattern_quality'), 'NA')}",
        f"{prefix}_avg_ticks={round(float(snapshot.get('pattern_avg_ticks') or 0.0), 2)}",
    ])


def update_trend_transition_state(state: Dict[str, Any], trend: str, now: datetime) -> None:
    trend_now = _safe_str(trend, "").upper()
    if trend_now not in ("UP", "DOWN", "FLAT"):
        return
    trend_prev = _safe_str(state.get("_trend_last"), "").upper()
    if trend_prev and trend_prev != trend_now:
        state["_trend_flip_time_jst"] = _now_str(now)
        state["_trend_flip_from"] = trend_prev
        state["_trend_flip_to"] = trend_now
    state["_trend_last"] = trend_now


def get_trend_flip_cooldown_status(
    state: Dict[str, Any],
    cfg: Cfg,
    now: datetime,
    trend: str,
    signal: str,
) -> Tuple[bool, str]:
    if signal not in ("BUY_CANDIDATE", "SELL_CANDIDATE"):
        return False, ""
    cooldown_min = max(0, int(cfg.trend_flip_cooldown_min))
    if cooldown_min <= 0:
        return False, ""
    trend_now = _safe_str(trend, "").upper()
    if trend_now not in ("UP", "DOWN"):
        return False, ""
    flip_to = _safe_str(state.get("_trend_flip_to"), "").upper()
    if flip_to != trend_now:
        return False, ""
    flip_from = _safe_str(state.get("_trend_flip_from"), "").upper()
    flip_time_raw = _safe_str(state.get("_trend_flip_time_jst"), "")
    if not flip_time_raw:
        return False, ""
    try:
        flip_time = datetime.strptime(flip_time_raw, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return False, ""
    elapsed_min = max(0.0, (now - flip_time).total_seconds() / 60.0)
    if elapsed_min >= cooldown_min:
        return False, ""
    remain_min = max(1, int(math.ceil(float(cooldown_min) - elapsed_min)))
    note = (
        f"trend_flip={flip_from or '?'}->{flip_to} "
        f"age_min={round(elapsed_min, 1)} remain_min={remain_min}"
    )
    return True, note


def _sma_last(vals: List[float], n: int) -> Optional[float]:
    if n <= 1 or len(vals) < n:
        return None
    tail = vals[-n:]
    return sum(tail) / n


def detect_sma_crossover_exit(
    *,
    state: Dict[str, Any],
    side: str,
    fast_n: int,
    slow_n: int,
) -> Tuple[bool, str, Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Return:
      (should_exit, reason, fast_now, slow_now, fast_prev, slow_prev)

    BUY open position -> exit on bearish crossover (fast drops below slow).
    SELL open position -> exit on bullish crossover (fast rises above slow).
    """
    hist_raw = state.get("ltp_history", [])
    if not isinstance(hist_raw, list):
        return False, "", None, None, None, None

    try:
        hist = [float(x) for x in hist_raw]
    except Exception:
        return False, "", None, None, None, None

    need = max(int(fast_n), int(slow_n))
    if need <= 1 or len(hist) < (need + 1):
        return False, "", None, None, None, None

    fast_now = _sma_last(hist, int(fast_n))
    slow_now = _sma_last(hist, int(slow_n))
    prev_hist = hist[:-1]
    fast_prev = _sma_last(prev_hist, int(fast_n))
    slow_prev = _sma_last(prev_hist, int(slow_n))
    if None in (fast_now, slow_now, fast_prev, slow_prev):
        return False, "", fast_now, slow_now, fast_prev, slow_prev

    s = _safe_str(side, "BUY").upper()
    if s == "BUY":
        cross_down = (float(fast_prev) >= float(slow_prev)) and (float(fast_now) < float(slow_now))
        if cross_down:
            return True, "SMA_CROSS_DOWN", fast_now, slow_now, fast_prev, slow_prev
        return False, "", fast_now, slow_now, fast_prev, slow_prev

    cross_up = (float(fast_prev) <= float(slow_prev)) and (float(fast_now) > float(slow_now))
    if cross_up:
        return True, "SMA_CROSS_UP", fast_now, slow_now, fast_prev, slow_prev
    return False, "", fast_now, slow_now, fast_prev, slow_prev


def calc_ma_gap_pct(ma_fast: Optional[float], ma_slow: Optional[float]) -> Optional[float]:
    if ma_fast is None or ma_slow is None:
        return None
    if float(ma_slow) == 0:
        return None
    return abs(float(ma_fast) - float(ma_slow)) / float(ma_slow) * 100.0


def calc_ma_slope_pct_per_step(state: Dict[str, Any], n: int) -> Optional[float]:
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


def calc_volatility_pct(state: Dict[str, Any], n: int) -> Optional[float]:
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


def calc_trendline_slope_pct_per_step_from_series(series: List[float], n: int) -> Optional[float]:
    if not isinstance(series, list) or len(series) < max(n, 5):
        return None
    try:
        tail = [float(x) for x in series[-n:]]
    except Exception:
        return None

    m = len(tail)
    if m < 3:
        return None
    x_mean = (m - 1) / 2.0
    y_mean = sum(tail) / float(m)
    if y_mean == 0:
        return None

    denom = sum((i - x_mean) ** 2 for i in range(m))
    if denom == 0:
        return None
    numer = sum((i - x_mean) * (tail[i] - y_mean) for i in range(m))
    slope = numer / denom
    return (slope / y_mean) * 100.0


def calc_trendline_slope_pct_per_step(state: Dict[str, Any], n: int) -> Optional[float]:
    hist = state.get("ltp_history", [])
    if not isinstance(hist, list):
        return None
    return calc_trendline_slope_pct_per_step_from_series(hist, n)


def calc_channel_position_from_series(series: List[float], n: int) -> Optional[float]:
    if not isinstance(series, list) or len(series) < max(n, 5):
        return None
    try:
        tail = [float(x) for x in series[-n:]]
    except Exception:
        return None
    hi = max(tail)
    lo = min(tail)
    width = hi - lo
    if width <= 0:
        return None
    pos = (tail[-1] - lo) / width
    return _clamp(pos, 0.0, 1.0)


def calc_channel_position(state: Dict[str, Any], n: int) -> Optional[float]:
    hist = state.get("ltp_history", [])
    if not isinstance(hist, list):
        return None
    return calc_channel_position_from_series(hist, n)


def calc_channel_width_pct_from_series(series: List[float], n: int) -> Optional[float]:
    if not isinstance(series, list) or len(series) < max(n, 5):
        return None
    try:
        tail = [float(x) for x in series[-n:]]
    except Exception:
        return None
    hi = max(tail)
    lo = min(tail)
    mid = (hi + lo) / 2.0
    if mid == 0:
        return None
    return ((hi - lo) / mid) * 100.0


def calc_channel_width_pct(state: Dict[str, Any], n: int) -> Optional[float]:
    hist = state.get("ltp_history", [])
    if not isinstance(hist, list):
        return None
    return calc_channel_width_pct_from_series(hist, n)


def ma_distance_pct(price: float, ma: Optional[float]) -> Optional[float]:
    if ma is None:
        return None
    if float(ma) == 0:
        return None
    return abs(float(price) - float(ma)) / float(ma) * 100.0


def resolve_fast_ma_observe(signal: str, price: float, ma_fast: Optional[float], cfg: Cfg) -> Tuple[str, str]:
    dist = ma_distance_pct(price, ma_fast)
    if signal == "BUY_CANDIDATE":
        if dist is None or dist < float(cfg.buy_fast_ma_distance_pct):
            return "OBSERVE_BUY_FAST_MA_NEAR", f"fast_ma_dist={'' if dist is None else round(dist, 6)}"
    if signal == "SELL_CANDIDATE":
        if dist is None or dist < float(cfg.sell_fast_ma_distance_pct):
            return "OBSERVE_SELL_FAST_MA_NEAR", f"fast_ma_dist={'' if dist is None else round(dist, 6)}"
    return "", ""


def calc_trend_efficiency_ratio(state: Dict[str, Any], n: int) -> Optional[float]:
    hist = state.get("ltp_history", [])
    if not isinstance(hist, list) or len(hist) < max(3, int(n)):
        return None
    try:
        tail = [float(x) for x in hist[-int(n):]]
    except Exception:
        return None
    if len(tail) < 3:
        return None
    gross = 0.0
    for i in range(1, len(tail)):
        gross += abs(float(tail[i]) - float(tail[i - 1]))
    if gross <= 0.0:
        return 0.0
    net = abs(float(tail[-1]) - float(tail[0]))
    return net / gross


def resolve_trend_strength_observe(
    signal: str,
    state: Dict[str, Any],
    cfg: Cfg,
) -> Tuple[str, str]:
    if not bool(cfg.trend_strength_filter_enabled):
        return "", ""
    if signal not in ("BUY_CANDIDATE", "SELL_CANDIDATE"):
        return "", ""
    er = calc_trend_efficiency_ratio(state, int(cfg.trend_strength_lookback_n))
    if er is None:
        return "", ""
    if float(er) < float(cfg.trend_strength_min_er):
        return (
            "OBSERVE_TREND_STRENGTH_WEAK",
            f"trend_er={round(float(er), 4)} min_er={round(float(cfg.trend_strength_min_er), 4)} "
            f"lookback_n={int(cfg.trend_strength_lookback_n)}",
        )
    return "", ""


def _get_ltp_tail(state: Dict[str, Any], n: int) -> List[float]:
    hist = state.get("ltp_history", [])
    if not isinstance(hist, list):
        return []
    try:
        vals = [float(x) for x in hist]
    except Exception:
        return []
    if n <= 0:
        return vals
    return vals[-int(n):]


def build_grouped_close_series(state: Dict[str, Any], group_n: int) -> List[float]:
    base = _get_ltp_tail(state, 0)
    g = max(1, int(group_n))
    if g <= 1:
        return base
    total_groups = len(base) // g
    if total_groups <= 0:
        return []
    start = len(base) - (total_groups * g)
    grouped: List[float] = []
    for idx in range(start, len(base), g):
        window = base[idx: idx + g]
        if len(window) != g:
            continue
        grouped.append(float(window[-1]))
    return grouped


def calc_htf_context(
    state: Dict[str, Any],
    *,
    group_n: int,
    lookback_n: int,
    bias_slope_pct: float,
) -> Dict[str, Any]:
    grouped = build_grouped_close_series(state, group_n)
    slope = calc_trendline_slope_pct_per_step_from_series(grouped, max(4, int(lookback_n)))
    channel_pos = calc_channel_position_from_series(grouped, max(4, int(lookback_n)))
    channel_width = calc_channel_width_pct_from_series(grouped, max(4, int(lookback_n)))
    if slope is None:
        bias = "NA"
    elif float(slope) >= float(bias_slope_pct):
        bias = "UP"
    elif float(slope) <= -float(bias_slope_pct):
        bias = "DOWN"
    else:
        bias = "RANGE"
    return {
        "group_n": int(group_n),
        "bars": len(grouped),
        "bias": bias,
        "trendline_slope_pct_per_step": slope,
        "channel_pos": channel_pos,
        "channel_width_pct": channel_width,
    }


def calc_mr_ma_cross_count(state: Dict[str, Any], slow_n: int, lookback_n: int) -> int:
    hist = _get_ltp_tail(state, int(lookback_n) + int(slow_n) + 2)
    if len(hist) < int(slow_n) + 2:
        return 0
    prev_sign = 0
    cross_count = 0
    for idx in range(int(slow_n), len(hist)):
        ma_val = sum(hist[idx - int(slow_n):idx]) / float(int(slow_n))
        diff = hist[idx] - ma_val
        sign = 1 if diff > 0 else -1 if diff < 0 else 0
        if sign == 0:
            continue
        if prev_sign and sign != prev_sign:
            cross_count += 1
        prev_sign = sign
    return cross_count


def calc_mr_level_snapshot(
    signal: str,
    state: Dict[str, Any],
    cfg: Cfg,
) -> Dict[str, Any]:
    prices = _get_ltp_tail(state, int(cfg.mr_level_lookback_n) + 1)
    if len(prices) < max(6, int(cfg.mr_level_lookback_n) // 2):
        return {
            "level_price": None,
            "level_type": "support" if signal == "BUY_CANDIDATE" else "resistance",
            "touch_count": 0,
            "age_min": None,
        }
    prices = prices[:-1]
    tol_pct = max(0.0001, float(cfg.mr_touch_tolerance_pct))
    side = "BUY" if signal == "BUY_CANDIDATE" else "SELL"
    best: Optional[Tuple[int, int, float, int]] = None
    best_price: Optional[float] = None
    latest_touch_idx = -1
    for idx, candidate in enumerate(prices):
        if candidate <= 0:
            continue
        touches = [
            j for j, x in enumerate(prices)
            if abs(float(x) - float(candidate)) / float(candidate) * 100.0 <= tol_pct
        ]
        touch_count = len(touches)
        if touch_count <= 0:
            continue
        recent_idx = max(touches)
        if side == "BUY":
            key = (touch_count, recent_idx, -float(candidate), -idx)
        else:
            key = (touch_count, recent_idx, float(candidate), -idx)
        if best is None or key > best:
            best = key
            best_price = float(candidate)
            latest_touch_idx = recent_idx
    if best_price is None:
        return {
            "level_price": None,
            "level_type": "support" if side == "BUY" else "resistance",
            "touch_count": 0,
            "age_min": None,
        }
    age_bars = max(0, (len(prices) - 1) - latest_touch_idx)
    return {
        "level_price": float(best_price),
        "level_type": "support" if side == "BUY" else "resistance",
        "touch_count": int(best[0]) if best is not None else 0,
        "age_min": int(age_bars * max(1, int(cfg.mr_bar_min))),
    }


def resolve_mr_observe(signal: str, state: Dict[str, Any], ltp: float, ma_fast: Optional[float], ma_slow: Optional[float], cfg: Cfg) -> Tuple[str, str]:
    if not bool(cfg.mr_observe_enabled):
        return "", ""
    if signal not in ("BUY_CANDIDATE", "SELL_CANDIDATE"):
        return "", ""

    htf15 = calc_htf_context(
        state,
        group_n=3,
        lookback_n=cfg.htf_context_lookback_n,
        bias_slope_pct=cfg.htf_bias_slope_pct,
    ) if bool(cfg.htf15_context_enabled) else {}
    htf60 = calc_htf_context(
        state,
        group_n=12,
        lookback_n=cfg.htf_context_lookback_n,
        bias_slope_pct=cfg.htf_bias_slope_pct,
    ) if bool(cfg.htf60_context_enabled) else {}

    level = calc_mr_level_snapshot(signal, state, cfg)
    level_price = _float_or_none(level.get("level_price"))
    level_type = _safe_str(level.get("level_type"), "support" if signal == "BUY_CANDIDATE" else "resistance")
    touch_count = max(0, _safe_int(level.get("touch_count"), 0))
    age_min = _safe_int(level.get("age_min"), 0)
    hist = _get_ltp_tail(state, max(int(cfg.mr_level_lookback_n), int(cfg.mr_spike_lookback_n)) + 1)
    if level_price is None or len(hist) < max(6, int(cfg.mr_spike_lookback_n)):
        note = (
            "strategy=MR "
            "mr_score=0 mr_rank=C mr_spike=0 mr_volume_state=NA mr_volume_score=1 "
            "mr_ma=0 mr_structure=0 mr_reclaim=0 "
            "mr_reason=insufficient_history"
        )
        if htf15:
            note = f"{note} mr_htf15_bias={_safe_str(htf15.get('bias'), 'NA')}"
        if htf60:
            note = f"{note} mr_htf60_bias={_safe_str(htf60.get('bias'), 'NA')}"
        return "OBSERVE_MR_FILTER_NG", note

    current = float(ltp)
    spike_tail = hist[-int(cfg.mr_spike_lookback_n):]
    spike_min_move_pct = float(cfg.mr_spike_min_move_pct)
    touch_tol_pct = float(cfg.mr_touch_tolerance_pct)
    ma_gap = calc_ma_gap_pct(ma_fast, ma_slow)
    ma_slope = calc_ma_slope_pct_per_step(state, n=max(int(cfg.mr_ma_cross_lookback_n), int(cfg.slow_n)))
    ma_cross_count = calc_mr_ma_cross_count(state, max(int(cfg.slow_n), 3), int(cfg.mr_ma_cross_lookback_n))
    market_regime = "trend"
    if (
        ma_gap is not None
        and ma_slope is not None
        and abs(float(ma_slope)) <= float(cfg.mr_range_max_ma_slope_pct)
        and float(ma_gap) <= float(cfg.mr_range_max_ma_gap_pct)
        and ma_cross_count >= 1
    ):
        market_regime = "range"

    if signal == "BUY_CANDIDATE":
        spike_extreme = min(spike_tail)
        is_spike = spike_extreme <= level_price * (1.0 - spike_min_move_pct / 100.0)
        reclaim_close = current >= level_price * (1.0 + touch_tol_pct / 100.0)
        stop_price = float(min(spike_tail))
    else:
        spike_extreme = max(spike_tail)
        is_spike = spike_extreme >= level_price * (1.0 + spike_min_move_pct / 100.0)
        reclaim_close = current <= level_price * (1.0 - touch_tol_pct / 100.0)
        stop_price = float(max(spike_tail))

    stop_distance_pct = 0.0
    if current > 0:
        stop_distance_pct = abs(float(current) - float(stop_price)) / float(current) * 100.0
    stop_distance_pct = max(float(cfg.mr_stop_min_distance_pct), float(stop_distance_pct))

    spike_score = 1 if is_spike else 0
    volume_state = "NA"
    volume_score = 1
    ma_score = 1 if market_regime == "range" else 0
    structure_score = 1 if touch_count >= 2 else 0
    reclaim_score = 1 if reclaim_close else 0
    total_score = spike_score + volume_score + ma_score + structure_score
    setup_rank = "A" if total_score >= 4 else "B" if total_score == 3 else "C"

    result = "OBSERVE_MR_FILTER_NG"
    if reclaim_score and total_score >= 3:
        result = "OBSERVE_MR_TRIGGER"
    elif total_score >= 3:
        result = "OBSERVE_MR"

    note_parts = [
        "strategy=MR",
        f"mr_score={int(total_score)}",
        f"mr_rank={setup_rank}",
        f"mr_spike={spike_score}",
        f"mr_spike_score={spike_score}",
        f"mr_volume_state={volume_state}",
        f"mr_volume_score={volume_score}",
        f"mr_ma={ma_score}",
        f"mr_ma_cross_count={int(ma_cross_count)}",
        f"mr_ma_slope={'' if ma_slope is None else round(float(ma_slope), 6)}",
        f"mr_market_regime={market_regime}",
        f"mr_structure={structure_score}",
        f"mr_structure_score={structure_score}",
        f"mr_left_structure={1 if touch_count >= 2 else 0}",
        f"mr_reclaim={reclaim_score}",
        f"mr_reclaim_close={reclaim_score}",
        f"mr_level_price={round(float(level_price), 6)}",
        f"mr_level_type={level_type}",
        f"mr_level_touch_count={touch_count}",
        f"mr_level_age_min={age_min}",
        f"mr_trigger_price={round(float(current), 6)}",
        f"mr_stop_price={round(float(stop_price), 6)}",
        f"mr_stop_pct={round(float(stop_distance_pct), 6)}",
        "mr_tp_r=1.0",
    ]
    if htf15:
        note_parts.extend([
            f"mr_htf15_bias={_safe_str(htf15.get('bias'), 'NA')}",
            f"mr_htf15_trendline={'' if htf15.get('trendline_slope_pct_per_step') is None else round(float(htf15.get('trendline_slope_pct_per_step')), 6)}",
            f"mr_htf15_channel_pos={'' if htf15.get('channel_pos') is None else round(float(htf15.get('channel_pos')), 6)}",
        ])
    if htf60:
        note_parts.extend([
            f"mr_htf60_bias={_safe_str(htf60.get('bias'), 'NA')}",
        ])
    return result, " ".join(note_parts)


def resolve_mr_paper_promotion(mr_result: str, mr_note: str, cfg: Cfg) -> Tuple[bool, str]:
    if not bool(cfg.mr_paper_enabled):
        return False, "mr_paper_disabled"

    result = _safe_str(mr_result, "")
    if bool(cfg.mr_paper_require_trigger) and result != "OBSERVE_MR_TRIGGER":
        return False, f"mr_paper_need_trigger result={result or 'NONE'}"

    rank_order = {"C": 1, "B": 2, "A": 3}
    rank = _extract_note_value(mr_note, "mr_rank").upper()
    min_rank = _safe_str(cfg.mr_paper_min_rank, MR_PAPER_MIN_RANK_DEFAULT).upper()
    if min_rank not in rank_order:
        min_rank = MR_PAPER_MIN_RANK_DEFAULT
    if rank_order.get(rank, 0) < rank_order[min_rank]:
        return False, f"mr_paper_rank_ng rank={rank or 'NA'} min={min_rank}"

    reclaim = _extract_note_value(mr_note, "mr_reclaim")
    if bool(cfg.mr_paper_require_reclaim) and reclaim != "1":
        return False, f"mr_paper_reclaim_ng reclaim={reclaim or 'NA'}"

    return True, f"mr_paper=1 mr_paper_rank={rank} mr_paper_source={result}"


def resolve_entry_tp_pct(cfg: Cfg, side: str, effective_stage: str) -> float:
    base = float(cfg.tp_buy_pct if _safe_str(side, "BUY").upper() == "BUY" else cfg.tp_sell_pct)
    if _safe_str(effective_stage, "").upper() == "CANARY":
        return base * float(cfg.canary_tp_scale)
    return base


# -------------------------
# TP/SL and best_fav
# -------------------------
def calc_tp_sl_prices(side: str, entry_price: float, tp_pct: float, sl_pct: float) -> Tuple[float, float]:
    tp = tp_pct / 100.0
    sl = sl_pct / 100.0
    s = (side or "BUY").upper()
    if s == "BUY":
        tp_price = entry_price * (1.0 + tp)
        sl_price = entry_price * (1.0 + sl)
    else:
        tp_price = entry_price * (1.0 - tp)
        sl_price = entry_price * (1.0 - sl)  # sl_pct negative => sl_price above entry
    return tp_price, sl_price


def calc_best_fav_pct(side: str, entry: float, ltp: float) -> Optional[float]:
    try:
        entry_f = float(entry)
        ltp_f = float(ltp)
        if entry_f == 0:
            return None
    except Exception:
        return None
    s = (side or "BUY").upper()
    if s == "BUY":
        return (ltp_f - entry_f) / entry_f * 100.0
    return (entry_f - ltp_f) / entry_f * 100.0


def calc_adverse_pct(side: str, entry: float, ltp: float) -> Optional[float]:
    fav = calc_best_fav_pct(side, entry, ltp)
    if fav is None:
        return None
    return max(0.0, -float(fav))


def resolve_weak_progress_exit_status(open_pos: Dict[str, Any], hold_min_val: Optional[float], cfg: "Cfg") -> Tuple[bool, str]:
    if not bool(cfg.weak_progress_exit_enabled):
        return False, ""
    op_exec_mode = _safe_str(open_pos.get("exec_mode"), "PAPER").upper()
    if bool(cfg.weak_progress_exit_only_paper) and op_exec_mode != "PAPER":
        return False, ""
    if hold_min_val is None or hold_min_val < float(max(0, int(cfg.weak_progress_exit_min_hold_min))):
        return False, ""
    try:
        best_fav = float(open_pos.get("best_fav", 0.0) or 0.0)
    except Exception:
        best_fav = 0.0
    max_best_fav = float(max(0.0, float(cfg.weak_progress_exit_max_best_fav_pct)))
    if best_fav > max_best_fav:
        return False, ""
    note = (
        f"exit_tech=WEAK_PROGRESS hold_min={hold_min_val:.1f} "
        f"best_fav={best_fav:.6f} min_hold={int(cfg.weak_progress_exit_min_hold_min)} "
        f"max_best_fav={max_best_fav:.6f}"
    )
    return True, note


def resolve_progress_reversal_exit_status(
    open_pos: Dict[str, Any],
    hold_min_val: Optional[float],
    current_fav_pct: Optional[float],
    cfg: "Cfg",
) -> Tuple[bool, str]:
    if not bool(cfg.progress_reversal_exit_enabled):
        return False, ""
    op_exec_mode = _safe_str(open_pos.get("exec_mode"), "PAPER").upper()
    if bool(cfg.progress_reversal_exit_only_paper) and op_exec_mode != "PAPER":
        return False, ""
    if hold_min_val is None or hold_min_val < float(max(0, int(cfg.progress_reversal_exit_min_hold_min))):
        return False, ""
    if current_fav_pct is None:
        return False, ""
    try:
        best_fav = float(open_pos.get("best_fav", 0.0) or 0.0)
    except Exception:
        best_fav = 0.0
    try:
        current_fav = float(current_fav_pct)
    except Exception:
        return False, ""
    min_best_fav = float(max(0.0, float(cfg.progress_reversal_exit_min_best_fav_pct)))
    max_current_fav = float(max(0.0, float(cfg.progress_reversal_exit_max_current_fav_pct)))
    if best_fav < min_best_fav:
        return False, ""
    if current_fav > max_current_fav:
        return False, ""
    note = (
        f"exit_tech=PROGRESS_REVERSAL hold_min={hold_min_val:.1f} "
        f"best_fav={best_fav:.6f} current_fav={current_fav:.6f} "
        f"min_hold={int(cfg.progress_reversal_exit_min_hold_min)} "
        f"min_best_fav={min_best_fav:.6f} max_current_fav={max_current_fav:.6f}"
    )
    return True, note


def resolve_near_tp_giveback_exit_status(
    open_pos: Dict[str, Any],
    hold_min_val: Optional[float],
    current_fav_pct: Optional[float],
    cfg: "Cfg",
) -> Tuple[bool, str]:
    if not bool(cfg.near_tp_giveback_exit_enabled):
        return False, ""
    op_exec_mode = _safe_str(open_pos.get("exec_mode"), "PAPER").upper()
    if bool(cfg.near_tp_giveback_exit_only_paper) and op_exec_mode != "PAPER":
        return False, ""
    if hold_min_val is None or hold_min_val < float(max(0, int(cfg.near_tp_giveback_exit_min_hold_min))):
        return False, ""
    if current_fav_pct is None:
        return False, ""
    try:
        best_fav = float(open_pos.get("best_fav", 0.0) or 0.0)
        current_fav = float(current_fav_pct)
    except Exception:
        return False, ""

    tp_pct_raw = _safe_float(open_pos.get("tp_pct"), None)
    if tp_pct_raw is None:
        try:
            entry = float(open_pos.get("entry_price", 0.0) or 0.0)
            tp_price = float(open_pos.get("tp_price", 0.0) or 0.0)
            if entry != 0.0:
                tp_pct_raw = abs(tp_price - entry) / abs(entry) * 100.0
        except Exception:
            tp_pct_raw = None
    tp_pct = float(tp_pct_raw or 0.0)
    if tp_pct <= 0.0:
        return False, ""

    trigger_ratio = float(max(0.01, float(cfg.near_tp_giveback_exit_trigger_ratio)))
    trigger_best_fav = tp_pct * trigger_ratio
    min_giveback = float(max(0.0, float(cfg.near_tp_giveback_exit_min_giveback_pct)))
    max_current_fav = float(max(0.0, float(cfg.near_tp_giveback_exit_max_current_fav_pct)))
    giveback = best_fav - current_fav
    if best_fav < trigger_best_fav:
        return False, ""
    if giveback < min_giveback:
        return False, ""
    if current_fav > max_current_fav:
        return False, ""
    note = (
        f"exit_tech=NEAR_TP_GIVEBACK hold_min={hold_min_val:.1f} "
        f"best_fav={best_fav:.6f} current_fav={current_fav:.6f} giveback={giveback:.6f} "
        f"tp_pct={tp_pct:.6f} trigger_ratio={trigger_ratio:.6f} "
        f"trigger_best_fav={trigger_best_fav:.6f} min_giveback={min_giveback:.6f} "
        f"max_current_fav={max_current_fav:.6f}"
    )
    return True, note


def resolve_no_follow_through_exit_status(
    open_pos: Dict[str, Any],
    hold_min_val: Optional[float],
    current_fav_pct: Optional[float],
    cfg: "Cfg",
) -> Tuple[bool, str]:
    if not bool(cfg.no_follow_through_exit_enabled):
        return False, ""
    op_exec_mode = _safe_str(open_pos.get("exec_mode"), "PAPER").upper()
    if bool(cfg.no_follow_through_exit_only_paper) and op_exec_mode != "PAPER":
        return False, ""
    if hold_min_val is None or hold_min_val < float(max(0, int(cfg.no_follow_through_exit_min_hold_min))):
        return False, ""
    if current_fav_pct is None:
        return False, ""
    try:
        best_fav = float(open_pos.get("best_fav", 0.0) or 0.0)
    except Exception:
        best_fav = 0.0
    try:
        current_fav = float(current_fav_pct)
    except Exception:
        return False, ""
    max_best_fav = float(max(0.0, float(cfg.no_follow_through_exit_max_best_fav_pct)))
    max_current_fav = float(max(0.0, float(cfg.no_follow_through_exit_max_current_fav_pct)))
    if best_fav > max_best_fav:
        return False, ""
    if current_fav > max_current_fav:
        return False, ""
    note = (
        f"exit_tech=NO_FOLLOW_THROUGH hold_min={hold_min_val:.1f} "
        f"best_fav={best_fav:.6f} current_fav={current_fav:.6f} "
        f"min_hold={int(cfg.no_follow_through_exit_min_hold_min)} "
        f"max_best_fav={max_best_fav:.6f} max_current_fav={max_current_fav:.6f}"
    )
    return True, note


def resolve_early_adverse_exit_status(
    open_pos: Dict[str, Any],
    hold_min_val: Optional[float],
    current_fav_pct: Optional[float],
    cfg: "Cfg",
) -> Tuple[bool, str]:
    """Exit when price moved sharply against us with no meaningful recovery.

    Targets the 'clean loss' pattern: entry → immediate adverse move → SL,
    where none of the other smart exits trigger because best_fav never built up.
    """
    if not bool(cfg.early_adverse_exit_enabled):
        return False, ""
    op_exec_mode = _safe_str(open_pos.get("exec_mode"), "PAPER").upper()
    if bool(cfg.early_adverse_exit_only_paper) and op_exec_mode != "PAPER":
        return False, ""
    if hold_min_val is None or hold_min_val < float(cfg.early_adverse_exit_min_hold_min):
        return False, ""
    if current_fav_pct is None:
        return False, ""
    try:
        best_fav = float(open_pos.get("best_fav", 0.0) or 0.0)
        current_fav = float(current_fav_pct)
    except Exception:
        return False, ""
    loss_threshold = float(min(0.0, float(cfg.early_adverse_exit_loss_pct)))
    max_fav_threshold = float(max(0.0, float(cfg.early_adverse_exit_max_fav_pct)))
    if current_fav > loss_threshold:
        return False, ""
    if best_fav > max_fav_threshold:
        return False, ""
    note = (
        f"exit_tech=EARLY_ADVERSE hold_min={hold_min_val:.1f} "
        f"best_fav={best_fav:.6f} current_fav={current_fav:.6f} "
        f"min_hold={cfg.early_adverse_exit_min_hold_min:.1f} "
        f"loss_pct={loss_threshold:.6f} max_fav={max_fav_threshold:.6f}"
    )
    return True, note


@dataclass
class LiveOrderCycle:
    status: str  # FILLED / PARTIAL / NONE / ERROR
    acceptance_id: str = ""
    ordered_size: float = 0.0
    filled_size: float = 0.0
    average_price: Optional[float] = None
    note: str = ""


def _append_note(note: str, extra: str) -> str:
    a = (note or "").strip()
    b = (extra or "").strip()
    if not b:
        return a
    return f"{a} {b}".strip() if a else b


def _float_or_none(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def resolve_effective_stage(cfg: Cfg, state: Dict[str, Any], now: datetime) -> str:
    """
    paper_mode=1 keeps PAPER execution behavior.
    live path is enabled only when paper_mode=0 and live_enabled=1.
    """
    if cfg.paper_mode or not cfg.live_enabled:
        state["_effective_stage"] = "PAPER"
        save_state(state)
        return "PAPER"

    today = now.date()
    start_day = str(state.get("_rollout_start_day", "")).strip()
    if not start_day:
        start_day = today.strftime("%Y-%m-%d")
        state["_rollout_start_day"] = start_day

    stage = "PAPER"
    mode = (cfg.rollout_mode or "AUTO").upper()
    if mode in ("PAPER", "CANARY", "LIVE"):
        stage = mode
    else:
        try:
            d0 = datetime.strptime(start_day, "%Y-%m-%d").date()
        except Exception:
            d0 = today
            state["_rollout_start_day"] = today.strftime("%Y-%m-%d")
        days = max(0, (today - d0).days)
        if days < int(cfg.stage_paper_days):
            stage = "PAPER"
        elif days < int(cfg.stage_paper_days + cfg.stage_canary_days):
            stage = "CANARY"
        else:
            stage = "LIVE"

    state["_effective_stage"] = stage
    save_state(state)
    return stage


def should_execute_live(cfg: Cfg, stage: str) -> bool:
    if cfg.paper_mode:
        return False
    if not cfg.live_enabled:
        return False
    return stage in ("CANARY", "LIVE")


def effective_lot(cfg: Cfg, stage: str) -> float:
    if stage == "CANARY":
        return max(float(cfg.canary_lot), 0.0)
    return max(float(cfg.lot), 0.0)


def _ai_train_rows_from_state(state: Dict[str, Any]) -> int:
    auto = state.get("_ai_auto_train")
    if isinstance(auto, dict):
        return max(0, _safe_int(auto.get("rows"), 0))
    return 0


def apply_ai_lot_lock(cfg: Cfg, state: Dict[str, Any], desired_size: float) -> Tuple[float, str]:
    size = max(float(desired_size), 0.0)
    if size <= PARTIAL_REMAIN_EPS:
        return 0.0, "size<=0"
    if not bool(cfg.ai_lot_lock_enabled):
        return size, ""

    rows = _ai_train_rows_from_state(state)
    min_samples = max(1, int(cfg.ai_lot_lock_min_samples))
    if rows >= min_samples:
        return size, ""

    cap = max(0.0, float(cfg.ai_lot_lock_max_lot))
    if cap <= PARTIAL_REMAIN_EPS:
        return size, f"ai_lot_lock rows={rows}<{min_samples} cap_disabled"
    if size > cap:
        return cap, f"ai_lot_lock rows={rows}<{min_samples} cap={cap:.8f}"
    return size, f"ai_lot_lock rows={rows}<{min_samples} keep={size:.8f}"


def apply_vol_lot_scale(cfg: "Cfg", volatility_pct: Optional[float], desired_size: float) -> Tuple[float, str]:
    size = max(float(desired_size), 0.0)
    if not bool(cfg.vol_lot_scale_enabled):
        return size, ""
    if volatility_pct is None:
        return size, ""
    threshold = float(max(0.001, float(cfg.vol_lot_scale_threshold_pct)))
    vol = float(volatility_pct)
    if vol < threshold:
        return size, ""
    ratio = _clamp(float(cfg.vol_lot_scale_high_ratio), 0.1, 1.0)
    scaled = max(round(size * ratio, 8), 0.001)
    return scaled, f"vol_lot_scaled vol={vol:.4f}>={threshold:.4f} ratio={ratio:.2f} {size:.8f}->{scaled:.8f}"


def _is_fx_market(cfg: Cfg) -> bool:
    mt = _safe_str(cfg.market_type, MARKET_TYPE_DEFAULT).upper()
    return mt in ("FX", "CFD", "LIGHTNING")


def _get_risk_base_jpy(client: Any, cfg: Cfg) -> Tuple[float, str]:
    if _is_fx_market(cfg):
        return float(client.get_collateral_jpy()), "collateral"
    return float(client.get_jpy_balance()), "balance"


def adjust_live_entry_size(
    client: Optional[Any],
    cfg: Cfg,
    desired_size: float,
    ref_price: float,
) -> Tuple[float, str]:
    """
    FX時は「証拠金 × leverage × 使用率」から上限サイズを算出してENTRY数量を制限する。
    SPOT時は desired_size をそのまま返す。
    """
    size = max(float(desired_size), 0.0)
    if size <= PARTIAL_REMAIN_EPS:
        return 0.0, "size<=0"
    if not _is_fx_market(cfg):
        return size, ""
    if client is None:
        return size, "fx_collateral_unavailable"
    try:
        px = float(ref_price)
        if px <= 0:
            return 0.0, "fx_ref_price_invalid"
        collateral = float(client.get_collateral_jpy())
        lev = max(0.1, float(cfg.fx_leverage))
        use_ratio = _clamp(float(cfg.fx_collateral_use_ratio), 0.05, 1.0)
        cap_notional = collateral * lev * use_ratio
        cap_size = cap_notional / px
        capped_size = max(min(size, cap_size), 0.0)
        # Enforce minimum lot: FX_BTC_JPY requires >= 0.001 BTC per order.
        # When collateral is insufficient, return 0.0 so the caller skips the order
        # gracefully instead of sending an invalid size that causes HTTP 400 (-104).
        FX_MIN_LOT = 0.001
        if 0 < capped_size < FX_MIN_LOT:
            return 0.0, (
                f"fx_below_min_lot capped={capped_size:.8f} "
                f"min_lot={FX_MIN_LOT} collateral={collateral:.2f} "
                f"need_jpy={FX_MIN_LOT * px / use_ratio:.0f}"
            )
        if capped_size + PARTIAL_REMAIN_EPS < size:
            note = (
                f"fx_size_capped collateral={collateral:.2f} "
                f"lev={lev:.2f} ratio={use_ratio:.2f} cap={capped_size:.8f}"
            )
            return capped_size, note
        return size, f"fx_cap_ok collateral={collateral:.2f} lev={lev:.2f} ratio={use_ratio:.2f}"
    except Exception as e:
        return size, f"fx_cap_error:{e}"


def compute_limit_price(side: str, best_bid: Any, best_ask: Any, offset_ticks: int) -> Optional[float]:
    bid = _float_or_none(best_bid)
    ask = _float_or_none(best_ask)
    if bid is None or ask is None:
        return None
    off = max(int(offset_ticks), 0) * TICK_SIZE_DEFAULT
    s = (side or "").upper()
    if s == "BUY":
        price = bid + off
    else:
        price = ask - off
    if price <= 0:
        return None
    return float(round(price, 1))


def compute_exit_limit_price(side: str, best_bid: Any, best_ask: Any, offset_ticks: int) -> Optional[float]:
    bid = _float_or_none(best_bid)
    ask = _float_or_none(best_ask)
    if bid is None or ask is None:
        return None
    off = max(int(offset_ticks), 0) * TICK_SIZE_DEFAULT
    s = (side or "").upper()
    if s == "BUY":
        price = ask + off
    else:
        price = bid - off
    if price <= 0:
        return None
    return float(round(price, 1))


def _opposite_side(side: str) -> str:
    return "SELL" if (side or "").upper() == "BUY" else "BUY"


def _load_live_client(cfg: Cfg) -> Any:
    api_key, api_secret = read_pair(
        service=cfg.keychain_service,
        account_key=cfg.keychain_account_key,
        account_secret=cfg.keychain_account_secret,
    )
    return build_private_client(
        exchange_name=cfg.exchange_name,
        api_key=api_key,
        api_secret=api_secret,
        bitflyer_base_url=BASE_URL,
    )


def _cancel_orphan_orders_on_startup(
    state: Dict[str, Any],
    cfg: "Cfg",
    client: Any,
    now: datetime,
) -> None:
    """Cancel any ACTIVE exchange orders that are not tracked in state._open_pos.

    Runs at the top of every bot invocation (each invocation is a fresh process).
    All errors are silently swallowed so this never blocks the main loop.
    """
    try:
        orders = client.get_child_orders(product_code=cfg.product_code, count=20)
    except Exception:
        return

    op = get_open_pos(state)
    tracked_id: str = str(op.get("acceptance_id") or "") if op else ""

    cancelled: list = []
    for order in orders:
        if str(order.get("child_order_state", "")) != "ACTIVE":
            continue
        oid = str(order.get("child_order_acceptance_id") or "")
        if not oid or oid == tracked_id:
            continue
        try:
            client.cancel_child_order(
                product_code=cfg.product_code,
                child_order_acceptance_id=oid,
            )
            cancelled.append({
                "at": now.strftime("%Y-%m-%d %H:%M:%S"),
                "oid": oid,
                "side": order.get("side"),
                "size": order.get("size"),
            })
        except Exception:
            pass

    if cancelled:
        hist = state.setdefault("_orphan_cancel_history", [])
        hist.extend(cancelled)
        # keep last 50 entries only
        state["_orphan_cancel_history"] = hist[-50:]
        save_state(state)


def run_live_limit_cycle(
    client: Any,
    *,
    cfg: Cfg,
    side: str,
    size: float,
    price: float,
) -> LiveOrderCycle:
    if size <= PARTIAL_REMAIN_EPS:
        return LiveOrderCycle(status="ERROR", note="size<=0")
    try:
        oid = client.send_child_order(
            product_code=cfg.product_code,
            side=side,
            size=size,
            child_order_type="LIMIT",
            price=price,
            minute_to_expire=max(1, int(cfg.limit_order_timeout_sec // 60) + 1),
            time_in_force="GTC",
        )
    except Exception as e:
        return LiveOrderCycle(status="ERROR", note=f"send_failed:{e}")

    end_ts = time.time() + float(cfg.limit_order_timeout_sec)
    last_state = "UNKNOWN"
    last_filled = 0.0
    last_avg = None
    while time.time() < end_ts:
        try:
            orders = client.get_child_orders(product_code=cfg.product_code, child_order_acceptance_id=oid, count=1)
            sm = summarize_order(orders)
            last_state = str(sm.get("state", "UNKNOWN"))
            last_filled = float(sm.get("executed_size", 0.0) or 0.0)
            last_avg = _float_or_none(sm.get("average_price"))
            if last_filled >= size - PARTIAL_REMAIN_EPS:
                return LiveOrderCycle(
                    status="FILLED",
                    acceptance_id=oid,
                    ordered_size=size,
                    filled_size=last_filled,
                    average_price=last_avg,
                    note=f"state={last_state}",
                )
            if last_state in ("COMPLETED", "CANCELED", "EXPIRED", "REJECTED"):
                break
        except Exception:
            pass
        time.sleep(2.0)

    try:
        client.cancel_child_order(product_code=cfg.product_code, child_order_acceptance_id=oid)
    except Exception:
        pass

    try:
        orders = client.get_child_orders(product_code=cfg.product_code, child_order_acceptance_id=oid, count=1)
        sm = summarize_order(orders)
        last_state = str(sm.get("state", last_state))
        last_filled = float(sm.get("executed_size", last_filled) or 0.0)
        last_avg = _float_or_none(sm.get("average_price"))
    except Exception:
        pass

    status = "PARTIAL" if last_filled > PARTIAL_REMAIN_EPS else "NONE"
    return LiveOrderCycle(
        status=status,
        acceptance_id=oid,
        ordered_size=size,
        filled_size=last_filled,
        average_price=last_avg,
        note=f"state={last_state}",
    )


def update_daily_risk_guard(
    state: Dict[str, Any],
    cfg: Cfg,
    client: Optional[Any],
    now: datetime,
) -> Tuple[bool, str]:
    """
    Returns: (risk_stop, note)
    """
    if client is None:
        state["_risk_stop"] = False
        save_state(state)
        return False, "client_unavailable"

    day = now.strftime("%Y-%m-%d")
    risk_day = str(state.get("_risk_day", ""))
    try:
        if risk_day != day or ("_risk_day_start_jpy" not in state):
            start, base_type = _get_risk_base_jpy(client, cfg)
            state["_risk_day"] = day
            state["_risk_day_start_jpy"] = start
            state["_risk_base_type"] = base_type
            state["_risk_realized_jpy"] = 0.0
            state["_risk_realized_pct"] = 0.0
            state["_risk_stop"] = False
            state.pop("_risk_last_error", None)
            save_state(state)
            return False, "risk_reset"

        start = float(state.get("_risk_day_start_jpy", 0.0) or 0.0)
        cur, base_type = _get_risk_base_jpy(client, cfg)
        pnl = cur - start
        pct = (pnl / start * 100.0) if start > 0 else 0.0
        stop = pct <= float(cfg.daily_loss_limit_pct)
        profit_stop = (float(cfg.daily_profit_stop_pct) > 0.0) and (pct >= float(cfg.daily_profit_stop_pct))
        state["_risk_base_type"] = base_type
        state["_risk_realized_jpy"] = float(round(pnl, 6))
        state["_risk_realized_pct"] = float(round(pct, 6))
        state["_risk_stop"] = bool(stop or profit_stop)
        state.pop("_risk_last_error", None)
        save_state(state)
        note = (
            f"risk_base={base_type} risk_pnl_pct={pct:.6f} "
            f"loss_limit={cfg.daily_loss_limit_pct:.6f} profit_limit={cfg.daily_profit_stop_pct:.6f}"
        )
        return bool(stop or profit_stop), note
    except Exception as e:
        state["_risk_last_error"] = str(e)
        save_state(state)
        return False, f"risk_error:{e}"


# -------------------------
# AI Adapter (simple local rule-scoring)
# -------------------------
class AIAdapter:
    def build_features(
        self,
        *,
        cfg: Cfg,
        state: Dict[str, Any],
        now: datetime,
        side: str,
        ltp: float,
        spread_pct: Optional[float],
        ma_fast: Optional[float],
        ma_slow: Optional[float],
        trend: str,
        blocked_news: bool,
    ) -> Dict[str, Any]:
        feats: Dict[str, Any] = {}
        feats["side"] = side
        feats["trend"] = trend
        feats["hour"] = now.hour
        feats["news_blocked"] = bool(blocked_news)

        feats["spread_pct"] = (spread_pct * 100.0) if (spread_pct is not None) else None
        feats["ma_gap_pct"] = calc_ma_gap_pct(ma_fast, ma_slow)
        feats["ma_slope_pct_per_step"] = calc_ma_slope_pct_per_step(state, n=cfg.fast_n)
        feats["volatility_pct"] = calc_volatility_pct(state, n=max(20, cfg.slow_n))
        feats["trendline_slope_pct_per_step"] = calc_trendline_slope_pct_per_step(state, n=max(20, cfg.slow_n))
        feats["channel_pos"] = calc_channel_position(state, n=max(20, cfg.slow_n))
        feats["channel_width_pct"] = calc_channel_width_pct(state, n=max(20, cfg.slow_n))
        if bool(cfg.ma_cross_feature_enabled):
            ma_cross = calc_ma_cross_snapshot(
                state,
                fast_n=cfg.fast_n,
                slow_n=cfg.slow_n,
                price=float(ltp),
                recent_lookback_n=cfg.ma_cross_recent_lookback_n,
                min_gap_pct=cfg.ma_cross_min_gap_pct,
                slow_slope_min_pct=cfg.ma_cross_slow_slope_min_pct,
                price_filter_enabled=cfg.ma_cross_price_filter_enabled,
            )
            feats["ma_cross_type"] = ma_cross.get("cross_type")
            feats["ma_cross_recent_type"] = ma_cross.get("recent_cross_type")
            feats["ma_cross_recent_age_bars"] = ma_cross.get("recent_cross_age_bars")
            feats["ma_cross_gap_pct"] = ma_cross.get("ma_gap_pct")
            feats["ma_cross_slow_slope_pct"] = ma_cross.get("slow_slope_pct")
            feats["ma_cross_price_position"] = ma_cross.get("price_position")
            feats["ma_cross_strong"] = bool(ma_cross.get("strong"))
            feats["ma_cross_note"] = format_ma_cross_note(ma_cross)
            recent_type = _safe_str(ma_cross.get("recent_cross_type"), "none").lower()
            feats["ma_cross_recent_aligned"] = (
                (side == "BUY" and recent_type == "golden")
                or (side == "SELL" and recent_type == "dead")
            )
            feats["ma_cross_recent_counter"] = (
                (side == "BUY" and recent_type == "dead")
                or (side == "SELL" and recent_type == "golden")
            )
        if bool(cfg.tech_indicators_enabled):
            ti = calc_technical_indicator_snapshot(state, price=float(ltp), cfg=cfg)
            feats["ti_rsi"] = ti.get("rsi")
            feats["ti_rsi_zone"] = ti.get("rsi_zone")
            feats["ti_bb_pos"] = ti.get("bb_pos")
            feats["ti_bb_width_pct"] = ti.get("bb_width_pct")
            feats["ti_bb_zone"] = ti.get("bb_zone")
            feats["ti_bb_breakout"] = ti.get("bb_breakout")
            feats["ti_atr_pct"] = ti.get("atr_pct")
            feats["ti_atr_regime"] = ti.get("atr_regime")
            feats["ti_trend_power"] = ti.get("trend_power")
            feats["ti_trend_power_regime"] = ti.get("trend_power_regime")
            feats["ti_note"] = format_technical_indicator_note(ti)
            rsi_zone = _safe_str(ti.get("rsi_zone"), "NA").lower()
            bb_zone = _safe_str(ti.get("bb_zone"), "NA").lower()
            feats["ti_overheat_risk"] = (
                (side == "BUY" and (rsi_zone == "overbought" or bb_zone in ("upper", "break_upper")))
                or (side == "SELL" and (rsi_zone == "oversold" or bb_zone in ("lower", "break_lower")))
            )
            feats["ti_pullback_favorable"] = (
                (side == "BUY" and bb_zone in ("lower", "mid"))
                or (side == "SELL" and bb_zone in ("upper", "mid"))
            )
            feats["ti_bb_squeeze_active"] = bool(ti.get("bb_squeeze_active"))
            # Band walk: read from state (updated once per cycle before entry eval)
            bw_buy_n = int(state.get("_bw_buy_n", 0))
            bw_sell_n = int(state.get("_bw_sell_n", 0))
            min_bw = max(1, int(cfg.bw_walk_min_count))
            feats["ti_bw_buy_n"] = bw_buy_n
            feats["ti_bw_sell_n"] = bw_sell_n
            feats["ti_bw_active_aligned"] = (
                (side == "BUY" and bw_buy_n >= min_bw)
                or (side == "SELL" and bw_sell_n >= min_bw)
            )
            feats["ti_bw_active_counter"] = (
                (side == "BUY" and bw_sell_n >= min_bw)
                or (side == "SELL" and bw_buy_n >= min_bw)
            )
            # Crypto Fear & Greed: state キャッシュから読む（メインループで更新済み）
            _cfg_score_raw = state.get("_cfg_score")
            _cfg_score_int = int(_cfg_score_raw) if _cfg_score_raw is not None else -1
            feats["ti_cfg_score"] = _cfg_score_int if _cfg_score_int >= 0 else None
            feats["ti_cfg_extreme_fear"] = bool(_cfg_score_int >= 0 and _cfg_score_int <= 24)
            feats["ti_cfg_extreme_greed"] = bool(_cfg_score_int >= 0 and _cfg_score_int >= 76)
        if bool(cfg.chart_pattern_enabled):
            cp_bars = get_ohlc_bars(state, include_current=True, max_bars=cfg.ohlc_max_bars)
            cp = calc_chart_pattern_snapshot(cp_bars, cfg)
            feats["pattern_name"] = cp.get("pattern_name")
            feats["pattern_stage"] = cp.get("pattern_stage")
            feats["pattern_bias"] = cp.get("pattern_bias")
            feats["pattern_confirmed"] = bool(cp.get("pattern_confirmed"))
            feats["pattern_trend"] = cp.get("pattern_trend")
            feats["pattern_neckline"] = cp.get("neckline")
            feats["pattern_quality"] = cp.get("pattern_quality")
            feats["pattern_avg_ticks"] = cp.get("pattern_avg_ticks")
            feats["pattern_note"] = format_chart_pattern_note(cp)
            bias = _safe_str(cp.get("pattern_bias"), "NEUTRAL").upper()
            quality_ok = _safe_str(cp.get("pattern_quality"), "NA").upper() == "OK"
            feats["pattern_aligned"] = (
                bool(cp.get("pattern_confirmed"))
                and quality_ok
                and ((side == "BUY" and bias == "BUY") or (side == "SELL" and bias == "SELL"))
            )
            feats["pattern_counter"] = (
                bool(cp.get("pattern_confirmed"))
                and quality_ok
                and ((side == "BUY" and bias == "SELL") or (side == "SELL" and bias == "BUY"))
            )
        if bool(cfg.market_phase_enabled):
            phase = calc_market_phase_snapshot(
                state,
                get_ohlc_bars(state, include_current=True, max_bars=max(cfg.ohlc_max_bars, cfg.market_phase_lookback_n)),
                price=float(ltp),
                cfg=cfg,
            )
            feats["market_phase"] = phase.get("phase")
            feats["market_phase_reason"] = phase.get("phase_reason")
            feats["market_phase_slope_pct"] = phase.get("ma_slope_pct")
            feats["market_phase_gap_pct"] = phase.get("ma_gap_pct")
            feats["market_phase_range_width_pct"] = phase.get("range_width_pct")
            feats["market_phase_up_break"] = bool(phase.get("up_break"))
            feats["market_phase_down_break"] = bool(phase.get("down_break"))
            feats["market_phase_momentum"] = phase.get("momentum")
            feats["market_phase_note"] = format_market_phase_note(phase)
        if bool(cfg.aiba_style_enabled):
            aiba = calc_aiba_style_snapshot(
                state,
                get_ohlc_bars(state, include_current=True, max_bars=max(cfg.ohlc_max_bars, cfg.aiba_try_fail_lookback_n)),
                price=float(ltp),
                cfg=cfg,
            )
            feats["aiba_trend"] = aiba.get("trend")
            feats["aiba_cross"] = aiba.get("cross_type")
            feats["aiba_ppp"] = aiba.get("ppp_flag")
            feats["aiba_nine_rule_count"] = aiba.get("nine_rule_count")
            feats["aiba_nine_rule_alert"] = bool(aiba.get("nine_rule_alert"))
            feats["aiba_try_fail"] = bool(aiba.get("try_fail_flag"))
            feats["aiba_try_fail_count"] = aiba.get("try_fail_count")
            feats["aiba_note"] = format_aiba_style_note(aiba)
            feats["aiba_aligned"] = (
                (side == "BUY" and (_safe_str(aiba.get("ppp_flag"), "").upper() == "PPP" or _safe_str(aiba.get("cross_type"), "").upper() == "KUCHIBASHI"))
                or (side == "SELL" and (_safe_str(aiba.get("ppp_flag"), "").upper() == "REV_PPP" or _safe_str(aiba.get("cross_type"), "").upper() == "REV_KUCHIBASHI" or bool(aiba.get("try_fail_flag"))))
            )
            feats["aiba_counter"] = (
                (side == "BUY" and (_safe_str(aiba.get("ppp_flag"), "").upper() == "REV_PPP" or _safe_str(aiba.get("cross_type"), "").upper() == "REV_KUCHIBASHI" or bool(aiba.get("try_fail_flag"))))
                or (side == "SELL" and (_safe_str(aiba.get("ppp_flag"), "").upper() == "PPP" or _safe_str(aiba.get("cross_type"), "").upper() == "KUCHIBASHI"))
            )
        if bool(cfg.fib_retracement_enabled):
            fib_bars = get_ohlc_bars(state, include_current=True, max_bars=cfg.ohlc_max_bars)
            fib_swings = extract_swing_points(fib_bars, int(cfg.swing_lookback))
            fib = calc_fibonacci_retracement_snapshot(
                fib_swings,
                float(ltp),
                side,
                min_swing_range_pct=float(cfg.fib_min_swing_range_pct),
            )
            feats["fib_retrace_pct"] = fib.get("fib_retrace_pct")
            feats["fib_zone"] = fib.get("fib_zone")
            feats["fib_in_golden_zone"] = bool(fib.get("fib_in_golden_zone"))
            feats["fib_wave3_candidate"] = bool(fib.get("fib_wave3_candidate"))
            feats["fib_swing_range_pct"] = fib.get("fib_swing_range_pct")
        if cfg.htf15_context_enabled:
            htf15 = calc_htf_context(
                state,
                group_n=3,
                lookback_n=cfg.htf_context_lookback_n,
                bias_slope_pct=cfg.htf_bias_slope_pct,
            )
            feats["htf15_bias"] = htf15.get("bias", "NA")
            feats["htf15_trendline_slope_pct_per_step"] = htf15.get("trendline_slope_pct_per_step")
            feats["htf15_channel_pos"] = htf15.get("channel_pos")
            feats["htf15_channel_width_pct"] = htf15.get("channel_width_pct")
        if cfg.htf60_context_enabled:
            htf60 = calc_htf_context(
                state,
                group_n=12,
                lookback_n=cfg.htf_context_lookback_n,
                bias_slope_pct=cfg.htf_bias_slope_pct,
            )
            feats["htf60_bias"] = htf60.get("bias", "NA")
        return feats

    def score(self, feats: Dict[str, Any], cfg: Cfg) -> Tuple[float, Dict[str, float]]:
        comps: Dict[str, float] = {}
        x = 0.0

        # spread: narrower better
        if cfg.ai_use_spread and feats.get("spread_pct") is not None:
            sp = float(feats["spread_pct"])
            # around 0.06% as neutral pivot
            comps["spread"] = _clamp((0.06 - sp) * 20.0, -2.0, 2.0)
            x += comps["spread"]

        # trend: align with side
        if cfg.ai_use_trend:
            tr = str(feats.get("trend", "UNKNOWN"))
            side = str(feats.get("side", "BUY"))
            if side == "BUY" and tr == "UP":
                comps["trend"] = 0.8
            elif side == "SELL" and tr == "DOWN":
                comps["trend"] = 0.8
            elif tr == "FLAT":
                comps["trend"] = -0.4
            else:
                comps["trend"] = -0.7
            x += comps["trend"]

        # MA gap: too tiny => noise; moderate => ok; too large => risky
        if cfg.ai_use_ma and feats.get("ma_gap_pct") is not None:
            mg = float(feats["ma_gap_pct"])
            if mg < 0.02:
                comps["ma_gap"] = -0.9
            elif mg < 0.08:
                comps["ma_gap"] = 0.4
            elif mg < 0.25:
                comps["ma_gap"] = 0.7
            else:
                comps["ma_gap"] = -0.4
            x += comps["ma_gap"]

        # slope: direction strength
        if cfg.ai_use_ma and feats.get("ma_slope_pct_per_step") is not None:
            ms = float(feats["ma_slope_pct_per_step"])
            side = str(feats.get("side", "BUY"))
            comps["ma_slope"] = _clamp((ms * 8.0) if side == "BUY" else (-ms * 8.0), -1.2, 1.2)
            x += comps["ma_slope"]

        # volatility: too high => penalty
        if cfg.ai_use_ma and feats.get("volatility_pct") is not None:
            vol = float(feats["volatility_pct"])
            if vol < 0.05:
                comps["volatility"] = 0.2
            elif vol < 0.25:
                comps["volatility"] = 0.0
            else:
                comps["volatility"] = -0.6
            x += comps["volatility"]

        if cfg.ai_use_ma and bool(cfg.ai_use_ma_cross):
            age_raw = feats.get("ma_cross_recent_age_bars")
            lookback = max(1.0, float(cfg.ma_cross_recent_lookback_n))
            freshness = 0.0
            if age_raw is not None:
                freshness = _clamp(1.0 - (float(age_raw) / lookback), 0.0, 1.0)
            if bool(feats.get("ma_cross_recent_aligned")):
                raw = float(cfg.ma_cross_ai_boost) * max(0.25, freshness)
                if bool(feats.get("ma_cross_strong")):
                    raw += float(cfg.ma_cross_ai_boost) * 0.50
                comps["ma_cross"] = _clamp(raw, 0.0, 0.8)
                x += comps["ma_cross"]
            elif bool(feats.get("ma_cross_recent_counter")):
                raw = -float(cfg.ma_cross_ai_penalty) * max(0.35, freshness)
                comps["ma_cross"] = _clamp(raw, -0.8, 0.0)
                x += comps["ma_cross"]

        if bool(cfg.ai_use_technical_indicators) and bool(cfg.tech_indicators_enabled):
            side = str(feats.get("side", "BUY"))
            trend = str(feats.get("trend", "UNKNOWN")).upper()
            tech = 0.0
            if bool(feats.get("ti_overheat_risk")):
                tech -= float(cfg.tech_ai_penalty)
            elif bool(feats.get("ti_pullback_favorable")):
                tech += float(cfg.tech_ai_boost) * 0.45

            rsi = feats.get("ti_rsi")
            if rsi is not None:
                rv = float(rsi)
                if side == "BUY":
                    if rv >= float(cfg.rsi_high):
                        tech -= float(cfg.tech_ai_penalty) * 0.50
                    elif 45.0 <= rv <= min(68.0, float(cfg.rsi_high)):
                        tech += float(cfg.tech_ai_boost) * 0.35
                    elif rv <= float(cfg.rsi_low):
                        tech += float(cfg.tech_ai_boost) * 0.20
                else:
                    if rv <= float(cfg.rsi_low):
                        tech -= float(cfg.tech_ai_penalty) * 0.50
                    elif max(32.0, float(cfg.rsi_low)) <= rv <= 55.0:
                        tech += float(cfg.tech_ai_boost) * 0.35
                    elif rv >= float(cfg.rsi_high):
                        tech += float(cfg.tech_ai_boost) * 0.20

            atr_regime = _safe_str(feats.get("ti_atr_regime"), "NA").lower()
            if atr_regime == "high":
                tech -= float(cfg.tech_ai_penalty) * 0.60
            elif atr_regime == "low":
                tech -= float(cfg.tech_ai_penalty) * 0.20
            elif atr_regime == "normal":
                tech += float(cfg.tech_ai_boost) * 0.20

            trend_power_regime = _safe_str(feats.get("ti_trend_power_regime"), "NA").lower()
            trend_aligned = (side == "BUY" and trend == "UP") or (side == "SELL" and trend == "DOWN")
            if trend_power_regime == "strong" and trend_aligned:
                tech += float(cfg.tech_ai_boost) * 0.45
            elif trend_power_regime == "weak":
                tech -= float(cfg.tech_ai_penalty) * 0.35

            if abs(tech) > 0.0:
                comps["technical"] = _clamp(tech, -0.9, 0.7)
                x += comps["technical"]

        if bool(cfg.ai_use_chart_patterns) and bool(cfg.chart_pattern_enabled):
            if bool(feats.get("pattern_aligned")):
                comps["chart_pattern"] = _clamp(float(cfg.pattern_ai_boost), 0.0, 0.7)
                x += comps["chart_pattern"]
            elif bool(feats.get("pattern_counter")):
                comps["chart_pattern"] = _clamp(-float(cfg.pattern_ai_penalty), -0.8, 0.0)
                x += comps["chart_pattern"]

        if bool(cfg.ai_use_market_phase) and bool(cfg.market_phase_enabled):
            side = str(feats.get("side", "BUY")).upper()
            phase = _safe_str(feats.get("market_phase"), "UNKNOWN").upper()
            phase_score = 0.0
            if side == "BUY" and phase == "C":
                phase_score += float(cfg.market_phase_ai_boost)
            elif side == "SELL" and phase == "A":
                phase_score += float(cfg.market_phase_ai_boost)
            elif phase == "B":
                phase_score -= float(cfg.market_phase_ai_penalty) * 0.70
            elif side == "BUY" and phase == "A":
                phase_score -= float(cfg.market_phase_ai_penalty)
            elif side == "SELL" and phase == "C":
                phase_score -= float(cfg.market_phase_ai_penalty)

            if side == "BUY" and bool(feats.get("market_phase_up_break")):
                phase_score += float(cfg.market_phase_ai_boost) * 0.50
            elif side == "SELL" and bool(feats.get("market_phase_down_break")):
                phase_score += float(cfg.market_phase_ai_boost) * 0.50
            elif side == "BUY" and bool(feats.get("market_phase_down_break")):
                phase_score -= float(cfg.market_phase_ai_penalty) * 0.40
            elif side == "SELL" and bool(feats.get("market_phase_up_break")):
                phase_score -= float(cfg.market_phase_ai_penalty) * 0.40

            if abs(phase_score) > 0.0:
                comps["market_phase"] = _clamp(phase_score, -0.7, 0.55)
                x += comps["market_phase"]

        if bool(cfg.ai_use_aiba_style) and bool(cfg.aiba_style_enabled) and bool(cfg.aiba_style_ai_enabled):
            aiba_score = 0.0
            if bool(feats.get("aiba_aligned")):
                aiba_score += float(cfg.aiba_style_ai_boost)
            if bool(feats.get("aiba_counter")):
                aiba_score -= float(cfg.aiba_style_ai_penalty)
            if bool(feats.get("aiba_nine_rule_alert")):
                aiba_score -= float(cfg.aiba_style_ai_penalty) * 0.35
            if abs(aiba_score) > 0.0:
                comps["aiba_style"] = _clamp(aiba_score, -0.55, 0.35)
                x += comps["aiba_style"]

        # Elliott Wave Fibonacci: boost when in golden zone (wave 3 candidate), penalise reversal zone
        if bool(cfg.fib_retracement_enabled):
            fib_score = 0.0
            if bool(feats.get("fib_wave3_candidate")):
                fib_score += float(cfg.fib_golden_zone_boost)
            elif _safe_str(feats.get("fib_zone"), "NA") == "REVERSAL":
                fib_score -= float(cfg.fib_reversal_penalty)
            if abs(fib_score) > 0.0:
                comps["fib"] = _clamp(fib_score, -0.5, 0.35)
                x += comps["fib"]

        # Fib × AIBA combo: extra boost when golden zone AND aiba_aligned both true
        if (
            bool(cfg.fib_retracement_enabled)
            and bool(cfg.ai_use_aiba_style)
            and bool(cfg.aiba_style_enabled)
            and bool(cfg.aiba_style_ai_enabled)
            and bool(feats.get("fib_wave3_candidate"))
            and bool(feats.get("aiba_aligned"))
            and float(cfg.fib_aiba_combo_boost) > 0.0
        ):
            comps["fib_aiba_combo"] = float(cfg.fib_aiba_combo_boost)
            x += comps["fib_aiba_combo"]

        # time: good/bad hour adj takes priority over edge penalty (W2)
        if cfg.ai_use_time:
            hr = int(feats.get("hour", 0))
            _time_adj = 0.0
            if cfg.ai_score_good_hours and hr in cfg.ai_score_good_hours:
                _time_adj = float(cfg.ai_time_good_hour_boost)
            elif cfg.ai_score_bad_hours and hr in cfg.ai_score_bad_hours:
                _time_adj = -float(cfg.ai_time_bad_hour_penalty)
            elif hr in (cfg.start_hour, cfg.end_hour - 1):
                _time_adj = -0.15
            if _time_adj != 0.0:
                comps["hour"] = _time_adj
                x += comps["hour"]

        # trendline slope: align with side (positive slope for BUY, negative for SELL)
        if cfg.ai_use_trendline and feats.get("trendline_slope_pct_per_step") is not None:
            ts = float(feats["trendline_slope_pct_per_step"])
            side = str(feats.get("side", "BUY"))
            raw = (ts * 6.0) if side == "BUY" else (-ts * 6.0)
            comps["trendline"] = _clamp(raw, -1.2, 1.2)
            x += comps["trendline"]

        # channel: prefer BUY from lower half / SELL from upper half for better R:R
        if cfg.ai_use_channel and feats.get("channel_pos") is not None:
            cp = float(feats["channel_pos"])
            side = str(feats.get("side", "BUY"))
            raw = (0.60 - cp) * 1.6 if side == "BUY" else (cp - 0.40) * 1.6
            cw = feats.get("channel_width_pct")
            if cw is not None:
                cwf = float(cw)
                if cwf < 0.08:
                    raw -= 0.20
                elif cwf > 1.20:
                    raw -= 0.10
            comps["channel"] = _clamp(raw, -1.0, 1.0)
            x += comps["channel"]

        if cfg.ai_use_htf_context:
            side = str(feats.get("side", "BUY"))
            htf15_bias = _safe_str(feats.get("htf15_bias"), "NA").upper()
            htf60_bias = _safe_str(feats.get("htf60_bias"), "NA").upper()
            for prefix, bias_weight in (("htf15", 0.45), ("htf60", 0.70)):
                bias = _safe_str(feats.get(f"{prefix}_bias"), "NA").upper()
                if not bias or bias == "NA":
                    continue
                if side == "BUY" and bias == "UP":
                    comps[f"{prefix}_bias"] = bias_weight
                elif side == "SELL" and bias == "DOWN":
                    comps[f"{prefix}_bias"] = bias_weight
                elif bias == "RANGE":
                    comps[f"{prefix}_bias"] = -0.10 if prefix == "htf15" else -0.15
                else:
                    comps[f"{prefix}_bias"] = -bias_weight
                x += comps[f"{prefix}_bias"]

            slope15 = feats.get("htf15_trendline_slope_pct_per_step")
            if slope15 is not None:
                raw = float(slope15) * 3.5 if side == "BUY" else (-float(slope15) * 3.5)
                comps["htf15_trendline"] = _clamp(raw, -0.9, 0.9)
                x += comps["htf15_trendline"]

            cp15 = feats.get("htf15_channel_pos")
            if cp15 is not None:
                raw = (0.62 - float(cp15)) * 0.45 if side == "BUY" else (float(cp15) - 0.38) * 0.45
                cw15 = feats.get("htf15_channel_width_pct")
                if cw15 is not None and float(cw15) < 0.10:
                    raw -= 0.08
                comps["htf15_channel"] = _clamp(raw, -0.5, 0.5)
                x += comps["htf15_channel"]

            htf60_countertrend = (
                (side == "BUY" and htf60_bias == "DOWN")
                or (side == "SELL" and htf60_bias == "UP")
            )
            if htf60_countertrend:
                comps["htf60_countertrend"] = -float(cfg.htf60_countertrend_penalty)
                x += comps["htf60_countertrend"]

            htf15_aligned = (
                (side == "BUY" and htf15_bias == "UP")
                or (side == "SELL" and htf15_bias == "DOWN")
            )
            if htf15_aligned and htf60_countertrend:
                comps["htf15_60_conflict"] = -float(cfg.htf15_60_conflict_penalty)
                x += comps["htf15_60_conflict"]

        # Fib golden zone × good hour combo: wave 3 candidate during proven high-WR hour
        if bool(cfg.fib_retracement_enabled) and cfg.ai_use_time:
            hr = int(feats.get("hour", 0))
            if (bool(feats.get("fib_wave3_candidate"))
                    and cfg.ai_score_good_hours
                    and hr in cfg.ai_score_good_hours):
                comps["fib_time_combo"] = 0.10
                x += 0.10

        # news penalty (should be hard-block anyway)
        if feats.get("news_blocked"):
            comps["news"] = -2.0
            x += comps["news"]

        s = _sigmoid(x)
        return s, comps

    def decide_entry(self, score: float, cfg: Cfg) -> Tuple[bool, str]:
        mode = (cfg.ai_mode or "OFF").upper()
        if mode == "OFF":
            return True, "ai_off"
        if mode == "SCORE_ONLY":
            return True, f"ai_score_only score={score:.3f}"
        if mode == "VETO":
            # low-score veto threshold derived from min_conf (kept compatible)
            veto_low = _clamp(1.0 - cfg.ai_veto_min_conf, 0.0, 1.0)
            if score <= veto_low:
                return False, f"ai_veto score={score:.3f} <= low={veto_low:.3f}"
            return True, f"ai_pass(VETO) score={score:.3f}"
        if mode == "GATE":
            if score >= cfg.ai_th_entry:
                return True, f"ai_allow(GATE) score={score:.3f} >= th={cfg.ai_th_entry:.3f}"
            return False, f"ai_block(GATE) score={score:.3f} < th={cfg.ai_th_entry:.3f}"
        return True, f"ai_unknown_mode={mode}"

    def decide_extend(self, score: float, cfg: Cfg) -> Tuple[bool, str]:
        mode = (cfg.ai_mode or "OFF").upper()
        if mode == "OFF":
            return True, "ai_off"
        if mode in ("SCORE_ONLY", "VETO"):
            veto_low = _clamp(1.0 - cfg.ai_veto_min_conf, 0.0, 1.0)
            if score <= veto_low:
                return False, f"ai_veto_extend score={score:.3f} <= low={veto_low:.3f}"
            return True, f"ai_pass_extend score={score:.3f}"
        # GATE: require >= threshold to extend
        if score >= cfg.ai_th_extend:
            return True, f"ai_allow_extend score={score:.3f} >= th={cfg.ai_th_extend:.3f}"
        return False, f"ai_block_extend score={score:.3f} < th={cfg.ai_th_extend:.3f}"


# -------------------------
# AI auto-tune (daily)
# -------------------------
def _iter_recent_trade_log_paths_from_dir(logs_dir: Path, now: datetime, lookback_days: int) -> List[Path]:
    out: List[Path] = []
    cutoff_date = (now - timedelta(days=max(1, lookback_days) + 2)).date()
    if not logs_dir.exists():
        return out
    for p in sorted(logs_dir.glob("trade_log_*.csv")):
        m = TRADE_LOG_NAME_RE.match(p.name)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y%m%d").date()
        except Exception:
            continue
        if d >= cutoff_date:
            out.append(p)
    return out


def _collect_ai_samples_from_training_log_file(
    path: Path,
    now: datetime,
    lookback_days: int,
    *,
    sample_source: str = "main",
) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    cutoff = now - timedelta(days=max(1, lookback_days))
    out: List[Dict[str, Any]] = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                t = _parse_trade_dt(row.get("time"))
                if not t or t < cutoff:
                    continue
                ai_score = _to_float_or_none(row.get("ai_score"))
                side = _safe_str(row.get("side"), "")
                entry = _to_float_or_none(row.get("entry_price"))
                exitp = _to_float_or_none(row.get("exit_price"))
                ret_pct = _to_float_or_none(row.get("ret_pct"))
                if ret_pct is None:
                    ret_pct = _calc_ret_pct(side, entry, exitp)
                if ai_score is None or ret_pct is None:
                    continue
                out.append(
                    {
                        "time": t,
                        "pos_id": _safe_str(row.get("pos_id"), ""),
                        "ai_score": float(ai_score),
                        "ret_pct": float(ret_pct),
                        "outcome": _safe_str(row.get("outcome"), ""),
                        "exec_mode": _safe_str(row.get("exec_mode"), "PAPER").upper(),
                        "sample_source": _safe_str(sample_source, "main"),
                    }
                )
    except Exception:
        return []
    return out


def _collect_ai_samples_from_training_log(now: datetime, lookback_days: int) -> List[Dict[str, Any]]:
    return _collect_ai_samples_from_training_log_file(
        AI_TRAIN_LOG_FILE,
        now,
        lookback_days,
        sample_source=("shadow" if INSTANCE_NAME == "shadow" else "main"),
    )


def _collect_ai_samples_from_trade_logs_dir(
    logs_dir: Path,
    now: datetime,
    lookback_days: int,
    *,
    sample_source: str = "main",
) -> List[Dict[str, Any]]:
    cutoff = now - timedelta(days=max(1, lookback_days))
    entries: Dict[str, Dict[str, Any]] = {}
    exits: Dict[str, Dict[str, Any]] = {}

    for p in _iter_recent_trade_log_paths_from_dir(logs_dir, now, lookback_days):
        try:
            with open(p, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    pos_id = _safe_str(row.get("pos_id"), "")
                    if not pos_id:
                        continue
                    res = _safe_str(row.get("result"), "")
                    if res == "PAPER":
                        if pos_id not in entries:
                            entries[pos_id] = row
                        continue
                    if res in AI_TRAIN_EXIT_RESULTS:
                        exits[pos_id] = row
        except Exception:
            continue

    out: List[Dict[str, Any]] = []
    for pos_id, e in entries.items():
        x = exits.get(pos_id)
        if not x:
            continue
        t = _parse_trade_dt(x.get("time"))
        if not t or t < cutoff:
            continue

        side = _safe_str(e.get("side"), _safe_str(x.get("side"), "BUY")).upper()
        entry_price = _to_float_or_none(e.get("price"))
        exit_price = _to_float_or_none(x.get("ltp"))
        if exit_price is None:
            exit_price = _to_float_or_none(x.get("price"))
        ret_pct = _calc_ret_pct(side, entry_price, exit_price)
        if ret_pct is None:
            continue

        ai_score = _to_float_or_none(e.get("ai_score"))
        if ai_score is None:
            ai_score = _extract_ai_score_from_note(e.get("note"))
        if ai_score is None:
            ai_score = _extract_ai_score_from_note(x.get("note"))
        if ai_score is None:
            continue

        out.append(
            {
                "time": t,
                "pos_id": pos_id,
                "ai_score": float(ai_score),
                "ret_pct": float(ret_pct),
                "outcome": _safe_str(x.get("result"), "").replace("PAPER_EXIT_", ""),
                "exec_mode": _extract_note_value(x.get("note"), "exec").upper() or "PAPER",
                "sample_source": _safe_str(sample_source, "main"),
            }
        )
    return out


def _collect_ai_samples_from_trade_logs(now: datetime, lookback_days: int) -> List[Dict[str, Any]]:
    return _collect_ai_samples_from_trade_logs_dir(
        LOGS_DIR,
        now,
        lookback_days,
        sample_source=("shadow" if INSTANCE_NAME == "shadow" else "main"),
    )


def _parse_hours_csv_set(v: Any) -> Set[int]:
    s = str(v or "").strip()
    if not s:
        return set()
    out: Set[int] = set()
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


def _apply_ai_sample_weighting(
    now: datetime,
    samples: List[Dict[str, Any]],
    *,
    live_only: bool,
    live_boost: float,
    shadow_boost: float = 1.0,
    backtest_boost: float = 1.0,
    recent_halflife_days: int,
    weekly_feedback_enabled: bool = False,
    weekly_good_hours: Optional[Set[int]] = None,
    weekly_bad_hours: Optional[Set[int]] = None,
    weekly_good_hour_boost: float = 1.0,
    weekly_bad_hour_penalty: float = 1.0,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    hl = max(1, int(recent_halflife_days))
    boost = _clamp(float(live_boost), 1.0, 3.0)
    sh_boost = _clamp(float(shadow_boost), 0.1, 3.0)
    bt_boost = _clamp(float(backtest_boost), 0.05, 3.0)
    good_hours = set(weekly_good_hours or set())
    bad_hours = set(weekly_bad_hours or set())
    good_boost = _clamp(float(weekly_good_hour_boost), 1.0, 3.0)
    bad_penalty = _clamp(float(weekly_bad_hour_penalty), 0.1, 1.0)
    for s in samples:
        if not isinstance(s, dict):
            continue
        t = s.get("time")
        if not isinstance(t, datetime):
            continue
        mode = _safe_str(s.get("exec_mode"), "PAPER").upper()
        if live_only and mode != "LIVE":
            continue
        sample_source = _safe_str(s.get("sample_source"), "main").lower()
        age_days = max(0.0, float((now - t).total_seconds()) / 86400.0)
        recency_w = math.pow(0.5, age_days / float(hl))
        mode_w = boost if mode == "LIVE" else 1.0
        src_w = 1.0
        if sample_source == "shadow":
            src_w = sh_boost
        elif sample_source == "backtest":
            src_w = bt_boost
        if sample_source == "shadow" and mode == "LIVE":
            # Shadow instance should be paper-only, but keep behavior deterministic.
            src_w = max(0.1, src_w * 0.8)
        hour_w = 1.0
        if weekly_feedback_enabled:
            hh = int(t.hour)
            if hh in good_hours:
                hour_w *= good_boost
            if hh in bad_hours:
                hour_w *= bad_penalty
        w = max(0.001, recency_w * mode_w * src_w * hour_w)
        d = dict(s)
        d["w"] = float(w)
        out.append(d)
    return out


def _eval_loss_small_profit_large(samples: List[Dict[str, Any]], threshold: float) -> Dict[str, Any]:
    picked: List[Dict[str, Any]] = []
    for r in samples:
        if _to_float_or_none(r.get("ai_score")) is None:
            continue
        if float(r["ai_score"]) < threshold:
            continue
        if _to_float_or_none(r.get("ret_pct")) is None:
            continue
        picked.append(r)

    rets = [float(r["ret_pct"]) for r in picked]
    ws = [max(0.001, _safe_float(r.get("w"), 1.0)) for r in picked]
    total_w = sum(ws)

    if not rets or total_w <= 0:
        return {
            "n": 0,
            "n_eff": 0.0,
            "wins": 0,
            "losses": 0,
            "neutrals": 0,
            "expectancy": -999.0,
            "avg_win": 0.0,
            "avg_loss_abs": 0.0,
            "rr": 0.0,
            "profit_factor": 0.0,
            "loss_rate_pct": 0.0,
            "metric": -999.0,
        }

    wins = [x for x in rets if x > 0]
    losses = [x for x in rets if x < 0]
    neutrals = [x for x in rets if x == 0]

    w_win = [w for x, w in zip(rets, ws) if x > 0]
    w_loss = [w for x, w in zip(rets, ws) if x < 0]
    win_rets = [x for x in rets if x > 0]
    loss_rets = [x for x in rets if x < 0]

    avg_win = (sum(x * w for x, w in zip(win_rets, w_win)) / sum(w_win)) if w_win else 0.0
    avg_loss_abs = abs(sum(x * w for x, w in zip(loss_rets, w_loss)) / sum(w_loss)) if w_loss else 0.0
    rr = (avg_win / avg_loss_abs) if avg_loss_abs > 0 else (5.0 if wins else 0.0)
    sum_win = sum(max(0.0, x) * w for x, w in zip(rets, ws))
    sum_loss_abs = abs(sum(min(0.0, x) * w for x, w in zip(rets, ws)))
    pf = (sum_win / sum_loss_abs) if sum_loss_abs > 0 else (8.0 if sum_win > 0 else 0.0)
    expectancy = sum(x * w for x, w in zip(rets, ws)) / total_w
    loss_w = sum(w for x, w in zip(rets, ws) if x < 0)
    loss_rate_pct = (loss_w / total_w) * 100.0

    rr_c = _clamp(rr, 0.0, 5.0)
    pf_c = _clamp(pf, 0.0, 8.0)
    metric = expectancy + 0.08 * (rr_c - 1.0) + 0.04 * (pf_c - 1.0) - 0.002 * loss_rate_pct

    return {
        "n": len(rets),
        "n_eff": float(total_w),
        "wins": len(wins),
        "losses": len(losses),
        "neutrals": len(neutrals),
        "expectancy": float(expectancy),
        "avg_win": float(avg_win),
        "avg_loss_abs": float(avg_loss_abs),
        "rr": float(rr),
        "profit_factor": float(pf),
        "loss_rate_pct": float(loss_rate_pct),
        "metric": float(metric),
    }


def _set_ai_entry_threshold(ai_model: Dict[str, Any], threshold: float) -> float:
    th = _clamp(float(threshold), 0.0, 1.0)
    conf_dst = ai_model.get("confidence_threshold")
    if not isinstance(conf_dst, dict):
        conf_dst = {}
        ai_model["confidence_threshold"] = conf_dst
    conf_dst["entry"] = float(th)
    g = ai_model.get("global")
    if not isinstance(g, dict):
        g = {}
        ai_model["global"] = g
    g["threshold"] = float(th)
    return float(th)


def _sample_source_counts(samples: List[Dict[str, Any]]) -> Dict[str, int]:
    out = {"main": 0, "shadow": 0, "backtest": 0, "other": 0}
    for s in samples:
        src = _safe_str((s or {}).get("sample_source"), "main").lower()
        if src == "main":
            out["main"] += 1
        elif src == "shadow":
            out["shadow"] += 1
        elif src == "backtest":
            out["backtest"] += 1
        else:
            out["other"] += 1
    return out


def maybe_run_daily_ai_autotune(
    *,
    state: Dict[str, Any],
    control_raw: Dict[str, str],
    ai_model: Dict[str, Any],
    now: datetime,
    control_path: Optional[Path] = None,
) -> Dict[str, Any]:
    if not _safe_bool(control_raw.get("ai_auto_train_enabled"), True):
        return ai_model

    today = now.strftime("%Y-%m-%d")
    if _safe_str(state.get("_ai_auto_train_day"), "") == today:
        return ai_model

    lookback_days = max(7, _safe_int(control_raw.get("ai_auto_lookback_days"), AI_AUTOTUNE_LOOKBACK_DAYS_DEFAULT))
    min_samples = max(20, _safe_int(control_raw.get("tune_min_samples"), 20))
    min_winloss_each = max(1, _safe_int(control_raw.get("tune_min_samples_band"), 5))
    train_live_only = _safe_bool(control_raw.get("ai_train_live_only"), AI_TRAIN_LIVE_ONLY_DEFAULT)
    train_live_boost = _clamp(
        _safe_float(control_raw.get("ai_train_live_boost"), AI_TRAIN_LIVE_BOOST_DEFAULT),
        1.0,
        3.0,
    )
    train_include_shadow = _safe_bool(
        control_raw.get("ai_train_include_shadow"),
        AI_TRAIN_INCLUDE_SHADOW_DEFAULT,
    )
    train_shadow_boost = _clamp(
        _safe_float(control_raw.get("ai_train_shadow_boost"), AI_TRAIN_SHADOW_BOOST_DEFAULT),
        0.1,
        3.0,
    )
    train_include_backtest = _safe_bool(
        control_raw.get("ai_train_include_backtest"),
        AI_TRAIN_INCLUDE_BACKTEST_DEFAULT,
    )
    train_backtest_boost = _clamp(
        _safe_float(control_raw.get("ai_train_backtest_boost"), AI_TRAIN_BACKTEST_BOOST_DEFAULT),
        0.05,
        3.0,
    )
    backtest_path_raw = _safe_str(
        control_raw.get("ai_train_backtest_path"),
        str(BACKTEST_AI_TRAIN_LOG_FILE),
    )
    backtest_path = Path(backtest_path_raw) if backtest_path_raw else BACKTEST_AI_TRAIN_LOG_FILE
    if not backtest_path.is_absolute():
        backtest_path = (MAIN_DIR / backtest_path).resolve()
    train_backtest_gate_enabled = _safe_bool(
        control_raw.get("ai_train_backtest_gate_enabled"),
        AI_TRAIN_BACKTEST_GATE_ENABLED_DEFAULT,
    )
    train_backtest_gate_min_samples = max(
        20,
        _safe_int(
            control_raw.get("ai_train_backtest_gate_min_samples"),
            AI_TRAIN_BACKTEST_GATE_MIN_SAMPLES_DEFAULT,
        ),
    )
    train_backtest_gate_expectancy_min = _safe_float(
        control_raw.get("ai_train_backtest_gate_expectancy_min"),
        AI_TRAIN_BACKTEST_GATE_EXPECTANCY_MIN_DEFAULT,
    )
    train_backtest_gate_pf_min = _safe_float(
        control_raw.get("ai_train_backtest_gate_pf_min"),
        AI_TRAIN_BACKTEST_GATE_PF_MIN_DEFAULT,
    )
    train_backtest_max_rows = max(
        0,
        _safe_int(
            control_raw.get("ai_train_backtest_max_rows"),
            AI_TRAIN_BACKTEST_MAX_ROWS_DEFAULT,
        ),
    )

    current_th = 0.65
    conf = ai_model.get("confidence_threshold")
    if isinstance(conf, dict):
        current_th = _clamp(_safe_float(conf.get("entry"), 0.65), 0.0, 1.0)
    else:
        g = ai_model.get("global")
        if isinstance(g, dict):
            legacy_th = _to_float_or_none(g.get("threshold"))
            if legacy_th is not None:
                current_th = _clamp(float(legacy_th), 0.0, 1.0)

    train_recent_halflife_days = max(
        1,
        _safe_int(
            control_raw.get("ai_train_recent_halflife_days"),
            AI_TRAIN_RECENT_HALFLIFE_DAYS_DEFAULT,
        ),
    )
    train_weekly_feedback_enabled = _safe_bool(
        control_raw.get("ai_train_weekly_feedback_enabled"),
        AI_TRAIN_WEEKLY_FEEDBACK_ENABLED_DEFAULT,
    )
    train_weekly_good_hours = _parse_hours_csv_set(
        control_raw.get("ai_train_weekly_good_hours", AI_TRAIN_WEEKLY_GOOD_HOURS_DEFAULT)
    )
    train_weekly_bad_hours = _parse_hours_csv_set(
        control_raw.get("ai_train_weekly_bad_hours", AI_TRAIN_WEEKLY_BAD_HOURS_DEFAULT)
    )
    train_weekly_good_hour_boost = _clamp(
        _safe_float(control_raw.get("ai_train_weekly_good_hour_boost"), AI_TRAIN_WEEKLY_GOOD_HOUR_BOOST_DEFAULT),
        1.0,
        3.0,
    )
    train_weekly_bad_hour_penalty = _clamp(
        _safe_float(
            control_raw.get("ai_train_weekly_bad_hour_penalty"),
            AI_TRAIN_WEEKLY_BAD_HOUR_PENALTY_DEFAULT,
        ),
        0.1,
        1.0,
    )
    gate_enabled = _safe_bool(control_raw.get("ai_gate_enabled"), AI_TRAIN_GATE_ENABLED_DEFAULT)
    gate_min_samples = max(
        10,
        _safe_int(control_raw.get("ai_gate_min_samples"), AI_TRAIN_GATE_MIN_SAMPLES_DEFAULT),
    )
    gate_expectancy_min = _safe_float(
        control_raw.get("ai_gate_expectancy_min"),
        AI_TRAIN_GATE_EXPECTANCY_MIN_DEFAULT,
    )
    gate_pf_min = _safe_float(control_raw.get("ai_gate_pf_min"), AI_TRAIN_GATE_PF_MIN_DEFAULT)
    rollback_enabled = _safe_bool(
        control_raw.get("ai_auto_rollback_enabled"),
        AI_AUTO_ROLLBACK_ENABLED_DEFAULT,
    )
    rollback_lookback_days = max(
        7,
        _safe_int(
            control_raw.get("ai_auto_rollback_lookback_days"),
            AI_AUTO_ROLLBACK_LOOKBACK_DAYS_DEFAULT,
        ),
    )
    rollback_pf_floor = _safe_float(
        control_raw.get("ai_auto_rollback_pf_floor"),
        AI_AUTO_ROLLBACK_PF_FLOOR_DEFAULT,
    )
    rollback_expectancy_floor = _safe_float(
        control_raw.get("ai_auto_rollback_expectancy_floor"),
        AI_AUTO_ROLLBACK_EXPECTANCY_FLOOR_DEFAULT,
    )
    auto_control_sync_enabled = _safe_bool(
        control_raw.get("ai_auto_control_sync_enabled"),
        AI_AUTO_CONTROL_SYNC_ENABLED_DEFAULT,
    )
    monthly_reval_enabled = _safe_bool(
        control_raw.get("ai_monthly_reval_enabled"),
        AI_MONTHLY_REVAL_ENABLED_DEFAULT,
    )
    monthly_reval_lookback_days = max(
        30,
        _safe_int(
            control_raw.get("ai_monthly_reval_lookback_days"),
            AI_MONTHLY_REVAL_LOOKBACK_DAYS_DEFAULT,
        ),
    )
    monthly_reval_min_samples = max(
        50,
        _safe_int(
            control_raw.get("ai_monthly_reval_min_samples"),
            AI_MONTHLY_REVAL_MIN_SAMPLES_DEFAULT,
        ),
    )
    monthly_reval_pf_min = _safe_float(
        control_raw.get("ai_monthly_reval_pf_min"),
        AI_MONTHLY_REVAL_PF_MIN_DEFAULT,
    )
    monthly_reval_expectancy_min = _safe_float(
        control_raw.get("ai_monthly_reval_expectancy_min"),
        AI_MONTHLY_REVAL_EXPECTANCY_MIN_DEFAULT,
    )
    monthly_reval_min_improve = max(
        0.0,
        _safe_float(
            control_raw.get("ai_monthly_reval_min_improve"),
            AI_MONTHLY_REVAL_MIN_IMPROVE_DEFAULT,
        ),
    )
    ai_lot_lock_enabled = _safe_bool(
        control_raw.get("ai_lot_lock_enabled"),
        AI_LOT_LOCK_ENABLED_DEFAULT,
    )
    ai_lot_lock_min_samples = max(
        1,
        _safe_int(
            control_raw.get("ai_lot_lock_min_samples"),
            AI_LOT_LOCK_MIN_SAMPLES_DEFAULT,
        ),
    )
    ai_lot_lock_max_lot = max(
        0.0,
        _safe_float(
            control_raw.get("ai_lot_lock_max_lot"),
            AI_LOT_LOCK_MAX_LOT_DEFAULT,
        ),
    )

    source = "ai_training_log"
    samples = _collect_ai_samples_from_training_log(now, lookback_days)
    shadow_train_rows = 0
    backtest_train_rows = 0
    backtest_rows_candidate = 0
    backtest_gate_pass = False
    backtest_gate_reason = "not_requested"
    backtest_gate_eval: Dict[str, Any] = {}
    if len(samples) < min_samples:
        source = "trade_logs"
        samples = _collect_ai_samples_from_trade_logs(now, lookback_days)
    if train_include_shadow:
        # Only add shadow samples when current instance is not shadow itself.
        add_shadow = SHADOW_LOGS_DIR.resolve() != LOGS_DIR.resolve()
        if add_shadow:
            shadow_samples = _collect_ai_samples_from_training_log_file(
                SHADOW_AI_TRAIN_LOG_FILE,
                now,
                lookback_days,
                sample_source="shadow",
            )
            if not shadow_samples:
                shadow_samples = _collect_ai_samples_from_trade_logs_dir(
                    SHADOW_LOGS_DIR,
                    now,
                    lookback_days,
                    sample_source="shadow",
                )
            if shadow_samples:
                shadow_train_rows = len(shadow_samples)
                samples.extend(shadow_samples)
                source = source + "+shadow"
    if train_include_backtest:
        backtest_samples = _collect_ai_samples_from_training_log_file(
            backtest_path,
            now,
            lookback_days,
            sample_source="backtest",
        )
        backtest_rows_candidate = len(backtest_samples)
        if train_backtest_max_rows > 0 and len(backtest_samples) > train_backtest_max_rows:
            backtest_samples = sorted(backtest_samples, key=lambda x: x.get("time", datetime.min))[-train_backtest_max_rows:]
        if train_live_only:
            backtest_gate_pass = False
            backtest_gate_reason = "train_live_only"
        elif not backtest_samples:
            backtest_gate_pass = False
            backtest_gate_reason = "no_samples"
        elif not train_backtest_gate_enabled:
            backtest_gate_pass = True
            backtest_gate_reason = "gate_disabled"
        else:
            bt_weighted = _apply_ai_sample_weighting(
                now,
                backtest_samples,
                live_only=False,
                live_boost=train_live_boost,
                shadow_boost=train_shadow_boost,
                backtest_boost=train_backtest_boost,
                recent_halflife_days=train_recent_halflife_days,
                weekly_feedback_enabled=train_weekly_feedback_enabled,
                weekly_good_hours=train_weekly_good_hours,
                weekly_bad_hours=train_weekly_bad_hours,
                weekly_good_hour_boost=train_weekly_good_hour_boost,
                weekly_bad_hour_penalty=train_weekly_bad_hour_penalty,
            )
            backtest_gate_eval = _eval_loss_small_profit_large(bt_weighted, current_th)
            backtest_gate_pass = (
                backtest_gate_eval.get("n", 0) >= train_backtest_gate_min_samples
                and float(backtest_gate_eval.get("profit_factor", 0.0)) >= float(train_backtest_gate_pf_min)
                and float(backtest_gate_eval.get("expectancy", -999.0)) >= float(train_backtest_gate_expectancy_min)
            )
            backtest_gate_reason = "pass" if backtest_gate_pass else "gate_fail"
        if backtest_samples:
            if backtest_gate_pass:
                backtest_train_rows = len(backtest_samples)
                samples.extend(backtest_samples)
                source = source + "+backtest"
    samples_raw_n = len(samples)
    source_counts_raw = _sample_source_counts(samples)
    samples = _apply_ai_sample_weighting(
        now,
        samples,
        live_only=train_live_only,
        live_boost=train_live_boost,
        shadow_boost=train_shadow_boost,
        backtest_boost=train_backtest_boost,
        recent_halflife_days=train_recent_halflife_days,
        weekly_feedback_enabled=train_weekly_feedback_enabled,
        weekly_good_hours=train_weekly_good_hours,
        weekly_bad_hours=train_weekly_bad_hours,
        weekly_good_hour_boost=train_weekly_good_hour_boost,
        weekly_bad_hour_penalty=train_weekly_bad_hour_penalty,
    )
    source_counts_weighted = _sample_source_counts(samples)

    base = _eval_loss_small_profit_large(samples, current_th)
    best = {"th": current_th, **base}
    gate_pass_best = (
        best["n"] >= gate_min_samples
        and float(best["profit_factor"]) >= float(gate_pf_min)
        and float(best["expectancy"]) >= float(gate_expectancy_min)
    )

    thresholds = sorted(set(AI_AUTOTUNE_THRESHOLD_GRID + [round(current_th, 2)]))
    for th in thresholds:
        ev = _eval_loss_small_profit_large(samples, th)
        if ev["n"] < min_samples:
            continue
        if ev["wins"] < min_winloss_each or ev["losses"] < min_winloss_each:
            continue
        if ev["metric"] > best["metric"]:
            best = {"th": th, **ev}
            gate_pass_best = (
                ev["n"] >= gate_min_samples
                and float(ev["profit_factor"]) >= float(gate_pf_min)
                and float(ev["expectancy"]) >= float(gate_expectancy_min)
            )

    applied = False
    improve = float(best["metric"]) - float(base["metric"])
    if (
        best["th"] != current_th
        and best["n"] >= min_samples
        and best["wins"] >= min_winloss_each
        and best["losses"] >= min_winloss_each
        and improve >= AI_AUTOTUNE_MIN_IMPROVE
        and ((not gate_enabled) or gate_pass_best)
    ):
        prev_th = float(current_th)
        _set_ai_entry_threshold(ai_model, float(best["th"]))
        applied = True
        state["_ai_prev_threshold"] = round(prev_th, 6)
        state["_ai_current_threshold"] = round(float(best["th"]), 6)
        state["_ai_threshold_last_change_day"] = today
        state["_ai_threshold_last_change_reason"] = "autotune_apply"
        state["_ai_threshold_last_change_improve"] = round(float(improve), 6)

    rollback_applied = False
    rollback_from = None
    rollback_to = None
    rollback_eval: Dict[str, Any] = {}
    if (
        rollback_enabled
        and (not applied)
        and _safe_str(state.get("_ai_rollback_day"), "") != today
    ):
        rb_samples = _collect_ai_samples_from_training_log(now, rollback_lookback_days)
        if len(rb_samples) < max(min_samples, gate_min_samples):
            rb_samples = _collect_ai_samples_from_trade_logs(now, rollback_lookback_days)
        if train_include_shadow:
            add_shadow = SHADOW_LOGS_DIR.resolve() != LOGS_DIR.resolve()
            if add_shadow:
                rb_shadow = _collect_ai_samples_from_training_log_file(
                    SHADOW_AI_TRAIN_LOG_FILE,
                    now,
                    rollback_lookback_days,
                    sample_source="shadow",
                )
                if not rb_shadow:
                    rb_shadow = _collect_ai_samples_from_trade_logs_dir(
                        SHADOW_LOGS_DIR,
                        now,
                        rollback_lookback_days,
                        sample_source="shadow",
                    )
                rb_samples.extend(rb_shadow)
        if train_include_backtest and backtest_train_rows > 0:
            rb_backtest = _collect_ai_samples_from_training_log_file(
                backtest_path,
                now,
                rollback_lookback_days,
                sample_source="backtest",
            )
            rb_samples.extend(rb_backtest)
        rb_samples = _apply_ai_sample_weighting(
            now,
            rb_samples,
            live_only=train_live_only,
            live_boost=train_live_boost,
            shadow_boost=train_shadow_boost,
            backtest_boost=train_backtest_boost,
            recent_halflife_days=train_recent_halflife_days,
            weekly_feedback_enabled=train_weekly_feedback_enabled,
            weekly_good_hours=train_weekly_good_hours,
            weekly_bad_hours=train_weekly_bad_hours,
            weekly_good_hour_boost=train_weekly_good_hour_boost,
            weekly_bad_hour_penalty=train_weekly_bad_hour_penalty,
        )
        active_th = current_th
        rollback_eval = _eval_loss_small_profit_large(rb_samples, active_th)
        rb_prev = _to_float_or_none(state.get("_ai_prev_threshold"))
        rollback_trigger = (
            rollback_eval.get("n", 0) >= max(gate_min_samples, 20)
            and (
                float(rollback_eval.get("profit_factor", 0.0)) < float(rollback_pf_floor)
                or float(rollback_eval.get("expectancy", -999.0)) < float(rollback_expectancy_floor)
            )
        )
        if rollback_trigger and rb_prev is not None and abs(float(rb_prev) - float(active_th)) > 1e-9:
            rollback_from = float(active_th)
            rollback_to = _set_ai_entry_threshold(ai_model, float(rb_prev))
            rollback_applied = True
            state["_ai_rollback_day"] = today
            state["_ai_rollback_reason"] = "metric_floor"
            state["_ai_rollback_eval"] = {
                "n": int(rollback_eval.get("n", 0)),
                "pf": round(float(rollback_eval.get("profit_factor", 0.0)), 6),
                "expectancy": round(float(rollback_eval.get("expectancy", 0.0)), 6),
                "pf_floor": round(float(rollback_pf_floor), 6),
                "expectancy_floor": round(float(rollback_expectancy_floor), 6),
            }
            state["_ai_current_threshold"] = round(float(rollback_to), 6)
            state["_ai_threshold_last_change_day"] = today
            state["_ai_threshold_last_change_reason"] = "auto_rollback"

    monthly_reval_ran = False
    monthly_reval_applied = False
    monthly_reval_reason = "disabled"
    monthly_reval_from = None
    monthly_reval_to = None
    monthly_reval_eval: Dict[str, Any] = {}
    monthly_reval_best: Dict[str, Any] = {}
    month_key = now.strftime("%Y-%m")
    if monthly_reval_enabled:
        last_month = _safe_str(state.get("_ai_monthly_reval_month"), "")
        if last_month == month_key:
            monthly_reval_reason = "already_ran"
        else:
            monthly_reval_ran = True
            active_th = current_th
            conf_now = ai_model.get("confidence_threshold")
            if isinstance(conf_now, dict):
                active_th = _clamp(_safe_float(conf_now.get("entry"), active_th), 0.0, 1.0)
            else:
                g_now = ai_model.get("global")
                if isinstance(g_now, dict):
                    legacy_th_now = _to_float_or_none(g_now.get("threshold"))
                    if legacy_th_now is not None:
                        active_th = _clamp(float(legacy_th_now), 0.0, 1.0)

            m_samples = _collect_ai_samples_from_training_log(now, monthly_reval_lookback_days)
            if len(m_samples) < monthly_reval_min_samples:
                m_samples = _collect_ai_samples_from_trade_logs(now, monthly_reval_lookback_days)
            if train_include_shadow:
                add_shadow = SHADOW_LOGS_DIR.resolve() != LOGS_DIR.resolve()
                if add_shadow:
                    m_shadow = _collect_ai_samples_from_training_log_file(
                        SHADOW_AI_TRAIN_LOG_FILE,
                        now,
                        monthly_reval_lookback_days,
                        sample_source="shadow",
                    )
                    if not m_shadow:
                        m_shadow = _collect_ai_samples_from_trade_logs_dir(
                            SHADOW_LOGS_DIR,
                            now,
                            monthly_reval_lookback_days,
                            sample_source="shadow",
                        )
                    m_samples.extend(m_shadow)
            if train_include_backtest:
                m_backtest = _collect_ai_samples_from_training_log_file(
                    backtest_path,
                    now,
                    monthly_reval_lookback_days,
                    sample_source="backtest",
                )
                if train_backtest_max_rows > 0 and len(m_backtest) > train_backtest_max_rows:
                    m_backtest = sorted(m_backtest, key=lambda x: x.get("time", datetime.min))[-train_backtest_max_rows:]
                m_samples.extend(m_backtest)

            m_samples = _apply_ai_sample_weighting(
                now,
                m_samples,
                live_only=train_live_only,
                live_boost=train_live_boost,
                shadow_boost=train_shadow_boost,
                backtest_boost=train_backtest_boost,
                recent_halflife_days=train_recent_halflife_days,
                weekly_feedback_enabled=train_weekly_feedback_enabled,
                weekly_good_hours=train_weekly_good_hours,
                weekly_bad_hours=train_weekly_bad_hours,
                weekly_good_hour_boost=train_weekly_good_hour_boost,
                weekly_bad_hour_penalty=train_weekly_bad_hour_penalty,
            )

            base_m = _eval_loss_small_profit_large(m_samples, active_th)
            monthly_reval_eval = {
                "n": int(base_m.get("n", 0)),
                "profit_factor": round(float(base_m.get("profit_factor", 0.0)), 6),
                "expectancy": round(float(base_m.get("expectancy", 0.0)), 6),
                "metric": round(float(base_m.get("metric", 0.0)), 6),
            }
            monthly_reval_best = {
                "th": float(active_th),
                "n": int(base_m.get("n", 0)),
                "profit_factor": float(base_m.get("profit_factor", 0.0)),
                "expectancy": float(base_m.get("expectancy", 0.0)),
                "metric": float(base_m.get("metric", 0.0)),
            }
            pass_best = (
                monthly_reval_best["n"] >= monthly_reval_min_samples
                and monthly_reval_best["profit_factor"] >= float(monthly_reval_pf_min)
                and monthly_reval_best["expectancy"] >= float(monthly_reval_expectancy_min)
            )
            thresholds_m = sorted(set(AI_AUTOTUNE_THRESHOLD_GRID + [round(active_th, 2)]))
            for th in thresholds_m:
                ev = _eval_loss_small_profit_large(m_samples, th)
                n_m = int(ev.get("n", 0))
                pf_m = float(ev.get("profit_factor", 0.0))
                ex_m = float(ev.get("expectancy", 0.0))
                mt_m = float(ev.get("metric", 0.0))
                if n_m < monthly_reval_min_samples:
                    continue
                if pf_m < float(monthly_reval_pf_min):
                    continue
                if ex_m < float(monthly_reval_expectancy_min):
                    continue
                if (not pass_best) or (mt_m > float(monthly_reval_best.get("metric", -999.0))):
                    monthly_reval_best = {
                        "th": float(th),
                        "n": n_m,
                        "profit_factor": pf_m,
                        "expectancy": ex_m,
                        "metric": mt_m,
                    }
                    pass_best = True

            if not pass_best:
                monthly_reval_reason = "gate_fail"
            else:
                improve_m = float(monthly_reval_best["metric"]) - float(base_m.get("metric", 0.0))
                if (
                    abs(float(monthly_reval_best["th"]) - float(active_th)) > 1e-9
                    and improve_m >= float(monthly_reval_min_improve)
                ):
                    monthly_reval_from = float(active_th)
                    monthly_reval_to = _set_ai_entry_threshold(ai_model, float(monthly_reval_best["th"]))
                    monthly_reval_applied = True
                    monthly_reval_reason = "applied"
                    state["_ai_current_threshold"] = round(float(monthly_reval_to), 6)
                    state["_ai_threshold_last_change_day"] = today
                    state["_ai_threshold_last_change_reason"] = "monthly_reval_apply"
                    state["_ai_threshold_last_change_improve"] = round(float(improve_m), 6)
                else:
                    monthly_reval_reason = "keep_current"

            state["_ai_monthly_reval_month"] = month_key
            state["_ai_monthly_reval"] = {
                "ran_at_jst": _now_str(now),
                "lookback_days": int(monthly_reval_lookback_days),
                "min_samples": int(monthly_reval_min_samples),
                "pf_min": float(monthly_reval_pf_min),
                "expectancy_min": float(monthly_reval_expectancy_min),
                "min_improve": float(monthly_reval_min_improve),
                "reason": str(monthly_reval_reason),
                "applied": bool(monthly_reval_applied),
                "from_th": (round(float(monthly_reval_from), 6) if monthly_reval_from is not None else None),
                "to_th": (round(float(monthly_reval_to), 6) if monthly_reval_to is not None else None),
                "eval": monthly_reval_eval,
                "best": {
                    "th": round(float(monthly_reval_best.get("th", active_th)), 6),
                    "n": int(monthly_reval_best.get("n", 0)),
                    "pf": round(float(monthly_reval_best.get("profit_factor", 0.0)), 6),
                    "expectancy": round(float(monthly_reval_best.get("expectancy", 0.0)), 6),
                    "metric": round(float(monthly_reval_best.get("metric", 0.0)), 6),
                },
            }

    model_info = ai_model.get("model_info")
    if not isinstance(model_info, dict):
        model_info = {}
        ai_model["model_info"] = model_info
    model_info["last_updated"] = today if (applied or rollback_applied or monthly_reval_applied) else _safe_str(model_info.get("last_updated"), today)
    model_info["auto_updated_by"] = "bot.daily_ai_autotune"
    model_info["objective"] = "loss_small_profit_large"
    model_info["auto_train_last_day"] = today
    model_info["auto_train_source"] = source
    model_info["auto_train_rows"] = len(samples)
    model_info["auto_train_rows_raw"] = int(samples_raw_n)
    model_info["auto_train_rows_main_raw"] = int(source_counts_raw.get("main", 0))
    model_info["auto_train_rows_shadow_raw"] = int(source_counts_raw.get("shadow", 0))
    model_info["auto_train_rows_backtest_raw"] = int(source_counts_raw.get("backtest", 0))
    model_info["auto_train_live_only"] = bool(train_live_only)
    model_info["auto_train_live_boost"] = float(train_live_boost)
    model_info["auto_train_include_shadow"] = bool(train_include_shadow)
    model_info["auto_train_shadow_boost"] = float(train_shadow_boost)
    model_info["auto_train_include_backtest"] = bool(train_include_backtest)
    model_info["auto_train_backtest_boost"] = float(train_backtest_boost)
    model_info["auto_train_backtest_path"] = str(backtest_path)
    model_info["auto_train_backtest_rows_candidate"] = int(backtest_rows_candidate)
    model_info["auto_train_backtest_rows_used"] = int(backtest_train_rows)
    model_info["auto_train_backtest_gate_enabled"] = bool(train_backtest_gate_enabled)
    model_info["auto_train_backtest_gate_pass"] = bool(backtest_gate_pass)
    model_info["auto_train_backtest_gate_reason"] = str(backtest_gate_reason)
    model_info["auto_train_backtest_gate_min_samples"] = int(train_backtest_gate_min_samples)
    model_info["auto_train_backtest_gate_expectancy_min"] = float(train_backtest_gate_expectancy_min)
    model_info["auto_train_backtest_gate_pf_min"] = float(train_backtest_gate_pf_min)
    model_info["auto_train_backtest_max_rows"] = int(train_backtest_max_rows)
    if backtest_gate_eval:
        model_info["auto_train_backtest_gate_n"] = int(backtest_gate_eval.get("n", 0))
        model_info["auto_train_backtest_gate_pf"] = round(float(backtest_gate_eval.get("profit_factor", 0.0)), 6)
        model_info["auto_train_backtest_gate_expectancy"] = round(float(backtest_gate_eval.get("expectancy", 0.0)), 6)
    model_info["auto_train_recent_halflife_days"] = int(train_recent_halflife_days)
    model_info["auto_train_weekly_feedback_enabled"] = bool(train_weekly_feedback_enabled)
    model_info["auto_train_weekly_good_hours"] = sorted(int(x) for x in train_weekly_good_hours)
    model_info["auto_train_weekly_bad_hours"] = sorted(int(x) for x in train_weekly_bad_hours)
    model_info["auto_train_weekly_good_hour_boost"] = float(train_weekly_good_hour_boost)
    model_info["auto_train_weekly_bad_hour_penalty"] = float(train_weekly_bad_hour_penalty)
    model_info["auto_train_gate_enabled"] = bool(gate_enabled)
    model_info["auto_train_gate_min_samples"] = int(gate_min_samples)
    model_info["auto_train_gate_expectancy_min"] = float(gate_expectancy_min)
    model_info["auto_train_gate_pf_min"] = float(gate_pf_min)
    model_info["auto_train_base_th"] = round(current_th, 4)
    model_info["auto_train_best_th"] = round(float(best["th"]), 4)
    model_info["auto_train_base_metric"] = round(float(base["metric"]), 6)
    model_info["auto_train_best_metric"] = round(float(best["metric"]), 6)
    model_info["auto_train_improve"] = round(float(improve), 6)
    model_info["auto_train_applied"] = bool(applied)
    model_info["auto_train_gate_pass_best"] = bool(gate_pass_best)
    model_info["auto_rollback_enabled"] = bool(rollback_enabled)
    model_info["auto_rollback_applied"] = bool(rollback_applied)
    model_info["auto_rollback_from_th"] = (round(float(rollback_from), 6) if rollback_from is not None else None)
    model_info["auto_rollback_to_th"] = (round(float(rollback_to), 6) if rollback_to is not None else None)
    if rollback_eval:
        model_info["auto_rollback_eval_n"] = int(rollback_eval.get("n", 0))
        model_info["auto_rollback_eval_pf"] = round(float(rollback_eval.get("profit_factor", 0.0)), 6)
        model_info["auto_rollback_eval_expectancy"] = round(float(rollback_eval.get("expectancy", 0.0)), 6)
    model_info["auto_monthly_reval_enabled"] = bool(monthly_reval_enabled)
    model_info["auto_monthly_reval_ran"] = bool(monthly_reval_ran)
    model_info["auto_monthly_reval_applied"] = bool(monthly_reval_applied)
    model_info["auto_monthly_reval_reason"] = str(monthly_reval_reason)
    model_info["auto_monthly_reval_month"] = str(month_key)
    model_info["auto_monthly_reval_lookback_days"] = int(monthly_reval_lookback_days)
    model_info["auto_monthly_reval_min_samples"] = int(monthly_reval_min_samples)
    model_info["auto_monthly_reval_pf_min"] = float(monthly_reval_pf_min)
    model_info["auto_monthly_reval_expectancy_min"] = float(monthly_reval_expectancy_min)
    model_info["auto_monthly_reval_min_improve"] = float(monthly_reval_min_improve)
    model_info["auto_monthly_reval_from_th"] = (round(float(monthly_reval_from), 6) if monthly_reval_from is not None else None)
    model_info["auto_monthly_reval_to_th"] = (round(float(monthly_reval_to), 6) if monthly_reval_to is not None else None)
    if monthly_reval_eval:
        model_info["auto_monthly_reval_eval_n"] = int(monthly_reval_eval.get("n", 0))
        model_info["auto_monthly_reval_eval_pf"] = round(float(monthly_reval_eval.get("profit_factor", 0.0)), 6)
        model_info["auto_monthly_reval_eval_expectancy"] = round(float(monthly_reval_eval.get("expectancy", 0.0)), 6)
    model_info["ai_lot_lock_enabled"] = bool(ai_lot_lock_enabled)
    model_info["ai_lot_lock_min_samples"] = int(ai_lot_lock_min_samples)
    model_info["ai_lot_lock_max_lot"] = float(ai_lot_lock_max_lot)

    control_sync_ok: Optional[bool] = None
    control_sync_msg = ""
    control_sync_keys: List[str] = []
    if (applied or rollback_applied or monthly_reval_applied) and auto_control_sync_enabled:
        conf_now = ai_model.get("confidence_threshold")
        conf_entry = None
        if isinstance(conf_now, dict):
            conf_entry = _to_float_or_none(conf_now.get("entry"))
        veto_now = ai_model.get("ai_veto")
        veto_min = None
        if isinstance(veto_now, dict):
            veto_min = _to_float_or_none(veto_now.get("min_confidence"))
        control_updates: Dict[str, str] = {}
        if conf_entry is not None:
            control_updates["ai_threshold"] = _fmt_control_float(float(conf_entry))
        if veto_min is not None:
            control_updates["ai_veto_threshold"] = _fmt_control_float(float(veto_min))
        control_sync_ok, control_sync_msg, control_sync_keys = sync_allowed_control_updates(
            control_path=(control_path or CONTROL_CSV_FILE),
            updates=control_updates,
            reason=(
                "ai_autotune_apply"
                if applied
                else ("ai_autotune_rollback" if rollback_applied else "ai_monthly_reval_apply")
            ),
            run_at=now,
        )
        if control_sync_ok:
            state.pop("_ai_auto_control_sync_error", None)
        else:
            state["_ai_auto_control_sync_error"] = str(control_sync_msg)
    elif applied or rollback_applied or monthly_reval_applied:
        control_sync_ok = False
        control_sync_msg = "disabled"

    model_info["auto_control_sync_enabled"] = bool(auto_control_sync_enabled)
    model_info["auto_control_sync_ok"] = control_sync_ok
    model_info["auto_control_sync_msg"] = str(control_sync_msg)
    model_info["auto_control_sync_changed_keys"] = list(control_sync_keys)

    if applied or rollback_applied or monthly_reval_applied:
        write_ai_model_json(AI_MODEL_JSON_FILE, ai_model)

    state["_ai_auto_train_day"] = today
    state["_ai_auto_train"] = {
        "ran_at_jst": _now_str(now),
        "source": source,
        "rows": len(samples),
        "rows_raw": int(samples_raw_n),
        "rows_main_raw": int(source_counts_raw.get("main", 0)),
        "rows_shadow_raw": int(source_counts_raw.get("shadow", 0)),
        "rows_backtest_raw": int(source_counts_raw.get("backtest", 0)),
        "rows_main_weighted": int(source_counts_weighted.get("main", 0)),
        "rows_shadow_weighted": int(source_counts_weighted.get("shadow", 0)),
        "rows_backtest_weighted": int(source_counts_weighted.get("backtest", 0)),
        "min_samples": min_samples,
        "min_winloss_each": min_winloss_each,
        "train_live_only": bool(train_live_only),
        "train_live_boost": float(train_live_boost),
        "train_include_shadow": bool(train_include_shadow),
        "train_shadow_boost": float(train_shadow_boost),
        "train_include_backtest": bool(train_include_backtest),
        "train_backtest_boost": float(train_backtest_boost),
        "train_backtest_path": str(backtest_path),
        "train_backtest_rows_candidate": int(backtest_rows_candidate),
        "train_backtest_rows_used": int(backtest_train_rows),
        "train_backtest_gate_enabled": bool(train_backtest_gate_enabled),
        "train_backtest_gate_pass": bool(backtest_gate_pass),
        "train_backtest_gate_reason": str(backtest_gate_reason),
        "train_backtest_gate_min_samples": int(train_backtest_gate_min_samples),
        "train_backtest_gate_expectancy_min": float(train_backtest_gate_expectancy_min),
        "train_backtest_gate_pf_min": float(train_backtest_gate_pf_min),
        "train_backtest_max_rows": int(train_backtest_max_rows),
        "train_recent_halflife_days": int(train_recent_halflife_days),
        "train_weekly_feedback_enabled": bool(train_weekly_feedback_enabled),
        "train_weekly_good_hours": sorted(int(x) for x in train_weekly_good_hours),
        "train_weekly_bad_hours": sorted(int(x) for x in train_weekly_bad_hours),
        "train_weekly_good_hour_boost": float(train_weekly_good_hour_boost),
        "train_weekly_bad_hour_penalty": float(train_weekly_bad_hour_penalty),
        "gate_enabled": bool(gate_enabled),
        "gate_min_samples": int(gate_min_samples),
        "gate_expectancy_min": float(gate_expectancy_min),
        "gate_pf_min": float(gate_pf_min),
        "gate_pass_best": bool(gate_pass_best),
        "current_th": round(current_th, 6),
        "best_th": round(float(best["th"]), 6),
        "current_metric": round(float(base["metric"]), 6),
        "best_metric": round(float(best["metric"]), 6),
        "improve": round(float(improve), 6),
        "applied": applied,
        "rollback_enabled": bool(rollback_enabled),
        "rollback_applied": bool(rollback_applied),
        "rollback_from_th": (round(float(rollback_from), 6) if rollback_from is not None else None),
        "rollback_to_th": (round(float(rollback_to), 6) if rollback_to is not None else None),
        "rollback_eval_n": int(rollback_eval.get("n", 0)) if rollback_eval else 0,
        "rollback_eval_pf": round(float(rollback_eval.get("profit_factor", 0.0)), 6) if rollback_eval else None,
        "rollback_eval_expectancy": round(float(rollback_eval.get("expectancy", 0.0)), 6) if rollback_eval else None,
        "rollback_pf_floor": float(rollback_pf_floor),
        "rollback_expectancy_floor": float(rollback_expectancy_floor),
        "shadow_rows_added": int(shadow_train_rows),
        "backtest_rows_added": int(backtest_train_rows),
        "backtest_gate_eval_n": int(backtest_gate_eval.get("n", 0)) if backtest_gate_eval else 0,
        "backtest_gate_eval_pf": round(float(backtest_gate_eval.get("profit_factor", 0.0)), 6) if backtest_gate_eval else None,
        "backtest_gate_eval_expectancy": round(float(backtest_gate_eval.get("expectancy", 0.0)), 6) if backtest_gate_eval else None,
        "auto_control_sync_enabled": bool(auto_control_sync_enabled),
        "auto_control_sync_ok": control_sync_ok,
        "auto_control_sync_msg": str(control_sync_msg),
        "auto_control_sync_changed_keys": list(control_sync_keys),
        "monthly_reval_enabled": bool(monthly_reval_enabled),
        "monthly_reval_ran": bool(monthly_reval_ran),
        "monthly_reval_applied": bool(monthly_reval_applied),
        "monthly_reval_reason": str(monthly_reval_reason),
        "monthly_reval_month": str(month_key),
        "monthly_reval_lookback_days": int(monthly_reval_lookback_days),
        "monthly_reval_min_samples": int(monthly_reval_min_samples),
        "monthly_reval_pf_min": float(monthly_reval_pf_min),
        "monthly_reval_expectancy_min": float(monthly_reval_expectancy_min),
        "monthly_reval_min_improve": float(monthly_reval_min_improve),
        "monthly_reval_from_th": (round(float(monthly_reval_from), 6) if monthly_reval_from is not None else None),
        "monthly_reval_to_th": (round(float(monthly_reval_to), 6) if monthly_reval_to is not None else None),
        "monthly_reval_eval_n": int(monthly_reval_eval.get("n", 0)) if monthly_reval_eval else 0,
        "monthly_reval_eval_pf": round(float(monthly_reval_eval.get("profit_factor", 0.0)), 6) if monthly_reval_eval else None,
        "monthly_reval_eval_expectancy": round(float(monthly_reval_eval.get("expectancy", 0.0)), 6) if monthly_reval_eval else None,
        "ai_lot_lock_enabled": bool(ai_lot_lock_enabled),
        "ai_lot_lock_min_samples": int(ai_lot_lock_min_samples),
        "ai_lot_lock_max_lot": float(ai_lot_lock_max_lot),
    }
    save_state(state)
    return ai_model


# -------------------------
# open_pos validation helpers
# -------------------------
def _parse_dt_jst(s: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(str(s), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def validate_open_pos(op: Dict[str, Any]) -> bool:
    required = ["pos_id", "entry_time_jst", "side", "entry_price", "tp_price", "sl_price", "expiry_time_jst"]
    for k in required:
        if k not in op:
            return False
    if not _safe_str(op.get("pos_id"), ""):
        return False
    if _parse_dt_jst(op.get("entry_time_jst")) is None:
        return False
    if _parse_dt_jst(op.get("expiry_time_jst")) is None:
        return False
    side = _safe_str(op.get("side"), "").upper()
    if side not in ("BUY", "SELL"):
        return False
    try:
        float(op.get("entry_price"))
        float(op.get("tp_price"))
        float(op.get("sl_price"))
    except Exception:
        return False
    return True


# -------------------------
# Execution flow (SPEC order)
# -------------------------
def main() -> None:
    if not ensure_run_lock():
        return

    # (0) now
    now = datetime.now()

    # (1) state
    state = load_state()

    # (2) control
    control_raw = load_control_csv(CONTROL_CSV_FILE)
    try:
        _ensure_ai_training_log_ready(AI_TRAIN_LOG_FILE)
    except Exception:
        pass

    # (3) ai_model.json
    ai_model = read_ai_model_json(AI_MODEL_JSON_FILE)
    ai_model = maybe_run_daily_ai_autotune(
        state=state,
        control_raw=control_raw,
        ai_model=ai_model,
        now=now,
    )

    # (4) runtime cfg
    cfg = build_runtime_config(control_raw, ai_model)
    effective_stage = resolve_effective_stage(cfg, state, now)
    exec_live = should_execute_live(cfg, effective_stage)
    live_client: Optional[Any] = None
    live_note_prefix = (
        f"exec={'LIVE' if exec_live else 'PAPER'} "
        f"instance={INSTANCE_NAME} exchange={cfg.exchange_name} "
        f"stage={effective_stage} market={cfg.market_type} product={cfg.product_code}"
    )
    if _is_fx_market(cfg):
        live_note_prefix = _append_note(
            live_note_prefix,
            f"fx_lev={cfg.fx_leverage:.2f} fx_ratio={cfg.fx_collateral_use_ratio:.2f}",
        )
    risk_stop = False
    risk_note = ""
    if exec_live:
        try:
            live_client = _load_live_client(cfg)
        except Exception as e:
            exec_live = False
            state["_live_client_error"] = str(e)
            save_state(state)
            live_note_prefix = _append_note(live_note_prefix, "client=unavailable")
        if exec_live and live_client is not None:
            _cancel_orphan_orders_on_startup(state, cfg, live_client, now)
        risk_stop, risk_note = update_daily_risk_guard(state, cfg, live_client, now)
    else:
        state["_risk_stop"] = False
        save_state(state)

    # (5) control snapshot (best effort)
    save_control_snapshot_for_audit(state, cfg, CONTROL_CSV_FILE, ai_model, AI_MODEL_JSON_FILE, now)

    # (6) csv path
    csv_path = today_log_path(now)

    # (7) self-heal
    self_heal_today_log(csv_path, state, now)

    # logger (after heal)
    log_trade = log_trade_factory(csv_path, state, cfg)
    # MINROW: open_pos exists & today log has 0 rows -> write 1 HOLD row (audit guard)
    ensure_today_has_min_row_if_open_pos(now, state, csv_path, log_trade)
# [MOVED_BY_PATCH]     ensure_today_has_min_row_if_open_pos(now, state, csv_path, log_trade)

    # (8) trading time (EOD exception)
    op0 = get_open_pos(state)
    is_eod_window = (now.time() >= EOD_CUTOFF) or (now.hour >= cfg.end_hour)
    in_trade_time = (cfg.start_hour <= now.hour < cfg.end_hour)
    if (not in_trade_time) and (not is_eod_window):
        # SPEC: out of time => log SKIP_OUT_OF_TIME and return
        try:
            log_trade({
                "time": _now_str(now),
                "result": "SKIP_OUT_OF_TIME",
                "side": "",
                "price": "",
                "size": "",
                "ltp": "",
                "best_bid": "",
                "best_ask": "",
                "spread_pct": "",
                "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": "",
                "ma_slow": "",
                "trend": "UNKNOWN",
                "signal": "NONE",
                "note": "out_of_trade_time",
                "pos_id": "",
            })
        except Exception:
            pass
        return

    # (9) ticker
    try:
        t = get_ticker(cfg.product_code)
    except Exception:
        # SPEC: ticker fetch failure must be logged as SKIP_TICKER_INCOMPLETE
        try:
            log_trade({
                "time": _now_str(now),
                "result": "SKIP_TICKER_INCOMPLETE",
                "side": "",
                "price": "",
                "size": "",
                "ltp": "",
                "best_bid": "",
                "best_ask": "",
                "spread_pct": "",
                "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": "",
                "ma_slow": "",
                "trend": "UNKNOWN",
                "signal": "NONE",
                "note": "ticker_fetch_failed",
                "pos_id": "",
            })
        except Exception:
            pass
        return

    # (10) extract
    best_bid = t.get("best_bid")
    best_ask = t.get("best_ask")
    ltp = t.get("ltp")

    # (11) spread
    spread_pct = calc_spread_pct(best_bid, best_ask, ltp)

    # (12) MA update -> save state
    if ltp is None:
        # ticker incomplete
        log_trade({
            "time": _now_str(now),
            "result": "SKIP_TICKER_INCOMPLETE",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
            "limit_pct": round(cfg.spread_limit_pct * 100, 6),
            "ma_fast": "",
            "ma_slow": "",
            "trend": "UNKNOWN",
            "signal": "NONE",
            "note": "ticker_incomplete",
            "pos_id": "",
        })
        return

    ma_fast, ma_slow, trend, signal = calc_ma_update_state(state, float(ltp), cfg.fast_n, cfg.slow_n, cfg.max_ltp_history)
    ohlc_bars = update_ohlc_state(
        state,
        now=now,
        price=float(ltp),
        timeframe_min=cfg.ohlc_timeframe_min,
        max_bars=cfg.ohlc_max_bars,
    ) if (bool(cfg.chart_pattern_enabled) or bool(cfg.market_phase_enabled) or bool(cfg.aiba_style_enabled)) else []
    update_trend_transition_state(state, trend, now)
    ma_cross_snapshot = calc_ma_cross_snapshot(
        state,
        fast_n=cfg.fast_n,
        slow_n=cfg.slow_n,
        price=float(ltp),
        recent_lookback_n=cfg.ma_cross_recent_lookback_n,
        min_gap_pct=cfg.ma_cross_min_gap_pct,
        slow_slope_min_pct=cfg.ma_cross_slow_slope_min_pct,
        price_filter_enabled=cfg.ma_cross_price_filter_enabled,
    ) if bool(cfg.ma_cross_feature_enabled) else {}
    ma_cross_note = format_ma_cross_note(ma_cross_snapshot)
    tech_snapshot = calc_technical_indicator_snapshot(
        state,
        price=float(ltp),
        cfg=cfg,
    ) if bool(cfg.tech_indicators_enabled) else {}
    # Band walk state: update once per cycle, merge into tech_snapshot for note
    if bool(cfg.tech_indicators_enabled):
        _bw_snap = update_band_walk_state(
            state,
            _safe_str(tech_snapshot.get("bb_zone"), "NA"),
            min_count=cfg.bw_walk_min_count,
        )
        tech_snapshot.update(_bw_snap)
    tech_note = format_technical_indicator_note(tech_snapshot)
    # Harami candle pattern detection (OHLC bars required)
    harami_snap = detect_harami_pattern(ohlc_bars) if len(ohlc_bars) >= 2 else {"pattern": "none", "bias": "NEUTRAL"}
    harami_note = (
        f"harami_pat={harami_snap['pattern']} harami_bias={harami_snap['bias']}"
        if harami_snap.get("pattern") != "none"
        else ""
    )
    # Crypto Fear & Greed Index: 日次マクロセンチメント（alternative.me/fng）
    cfg_snap = _fetch_crypto_fear_greed(state)
    cfg_note = (
        f"cfg_score={cfg_snap['score']} cfg_class={cfg_snap['class']}"
        if cfg_snap["score"] >= 0 else ""
    )
    pattern_snapshot = calc_chart_pattern_snapshot(ohlc_bars, cfg) if bool(cfg.chart_pattern_enabled) else {}
    pattern_note = format_chart_pattern_note(pattern_snapshot)
    market_phase_snapshot = calc_market_phase_snapshot(
        state,
        ohlc_bars,
        price=float(ltp),
        cfg=cfg,
    ) if bool(cfg.market_phase_enabled) else {}
    market_phase_note = format_market_phase_note(market_phase_snapshot)
    market_phase_transition_note = update_market_phase_transition_state(
        state,
        market_phase_snapshot,
        now,
    ) if bool(cfg.market_phase_enabled) else ""
    aiba_style_snapshot = calc_aiba_style_snapshot(
        state,
        ohlc_bars,
        price=float(ltp),
        cfg=cfg,
    ) if bool(cfg.aiba_style_enabled) else {}
    aiba_style_note = format_aiba_style_note(aiba_style_snapshot)
    feature_note = _append_note(
        _append_note(
            _append_note(
                _append_note(
                    _append_note(_append_note(ma_cross_note, tech_note), pattern_note),
                    market_phase_note,
                ),
                market_phase_transition_note,
            ),
            _append_note(_append_note(aiba_style_note, harami_note), cfg_note),
        ),
        "",
    )
    save_state(state)

    news_blocks = load_news_blocks(NEWS_BLOCK_FILE)

    # (14) open_pos EXIT management
    open_pos = get_open_pos(state)
    if open_pos:
        # validate broken -> ERROR + clear
        if not validate_open_pos(open_pos):
            log_trade({
                "time": _now_str(now),
                "result": "ERROR_OPEN_POS_BROKEN",
                "side": _safe_str(open_pos.get("side"), ""),
                "price": _safe_str(open_pos.get("entry_price"), ""),
                "size": _safe_str(open_pos.get("size"), ""),
                "ltp": ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
                "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": _safe_str(open_pos.get("ma_fast"), ""),
                "ma_slow": _safe_str(open_pos.get("ma_slow"), ""),
                "trend": _safe_str(open_pos.get("trend"), "UNKNOWN"),
                "signal": _safe_str(open_pos.get("signal"), "NONE"),
                "note": "open_pos_invalid -> cleared",
                "pos_id": _safe_str(open_pos.get("pos_id"), ""),
            })
            clear_open_pos(state)
            return

        # (14a) EOD force close (highest priority when open_pos exists)
        if is_eod_window:
            op_exec = _safe_str(open_pos.get("exec_mode"), "PAPER").upper()
            if op_exec == "LIVE":
                eod_side = _safe_str(open_pos.get("side"), "BUY").upper()
                eod_exit_side = _opposite_side(eod_side)
                eod_size = _safe_float(open_pos.get("size"), cfg.lot)
                eod_px = compute_exit_limit_price(eod_exit_side, best_bid, best_ask, cfg.limit_price_offset_ticks)
                if live_client is None or eod_px is None:
                    set_open_pos(state, open_pos)
                    log_trade({
                        "time": _now_str(now),
                        "result": "HOLD_OPEN_POS",
                        "side": _safe_str(open_pos.get("side"), ""),
                        "price": _safe_str(open_pos.get("entry_price"), ""),
                        "size": _safe_str(open_pos.get("size"), cfg.lot),
                        "ltp": ltp,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
                        "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                        "ma_fast": _safe_str(open_pos.get("ma_fast"), ""),
                        "ma_slow": _safe_str(open_pos.get("ma_slow"), ""),
                        "trend": _safe_str(open_pos.get("trend"), "UNKNOWN"),
                        "signal": _safe_str(open_pos.get("signal"), "NONE"),
                        "note": "EOD_LIVE_EXIT_UNAVAILABLE",
                        "pos_id": _safe_str(open_pos.get("pos_id"), ""),
                    })
                    return

                cycle = run_live_limit_cycle(client=live_client, cfg=cfg, side=eod_exit_side, size=eod_size, price=eod_px)
                state["_pending_exit"] = {
                    "at_jst": _now_str(now),
                    "pos_id": _safe_str(open_pos.get("pos_id"), ""),
                    "side": eod_exit_side,
                    "size": eod_size,
                    "price": eod_px,
                    "status": cycle.status,
                    "acceptance_id": cycle.acceptance_id,
                    "filled_size": cycle.filled_size,
                    "result": "PAPER_EXIT_EOD",
                }
                save_state(state)
                filled = float(cycle.filled_size)
                remain = max(0.0, eod_size - filled)
                if cycle.status in ("FILLED", "PARTIAL") and remain <= PARTIAL_REMAIN_EPS:
                    note_eod = f"EOD_FORCE_CLOSE cutoff={EOD_CUTOFF.strftime('%H:%M:%S')}"
                    note_eod = _append_note(note_eod, f"exec=LIVE stage={open_pos.get('effective_stage', effective_stage)}")
                    note_eod = _append_note(note_eod, f"order_id={cycle.acceptance_id} filled={cycle.filled_size:.8f}")
                    note_eod = _append_note(note_eod, cycle.note)
                    log_trade({
                        "time": _now_str(now),
                        "result": "PAPER_EXIT_EOD",
                        "side": _safe_str(open_pos.get("side"), ""),
                        "price": _safe_str(open_pos.get("entry_price"), ""),
                        "size": _safe_str(open_pos.get("size"), cfg.lot),
                        "ltp": ltp,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
                        "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                        "ma_fast": _safe_str(open_pos.get("ma_fast"), ""),
                        "ma_slow": _safe_str(open_pos.get("ma_slow"), ""),
                        "trend": _safe_str(open_pos.get("trend"), "UNKNOWN"),
                        "signal": _safe_str(open_pos.get("signal"), "NONE"),
                        "note": note_eod,
                        "pos_id": _safe_str(open_pos.get("pos_id"), ""),
                    })
                    clear_open_pos(state)
                    return

                if cycle.status in ("FILLED", "PARTIAL") and remain > PARTIAL_REMAIN_EPS:
                    open_pos["size"] = float(round(remain, 8))
                    set_open_pos(state, open_pos)
                    log_trade({
                        "time": _now_str(now),
                        "result": "HOLD_OPEN_POS",
                        "side": _safe_str(open_pos.get("side"), ""),
                        "price": _safe_str(open_pos.get("entry_price"), ""),
                        "size": _safe_str(open_pos.get("size"), cfg.lot),
                        "ltp": ltp,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
                        "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                        "ma_fast": _safe_str(open_pos.get("ma_fast"), ""),
                        "ma_slow": _safe_str(open_pos.get("ma_slow"), ""),
                        "trend": _safe_str(open_pos.get("trend"), "UNKNOWN"),
                        "signal": _safe_str(open_pos.get("signal"), "NONE"),
                        "note": _append_note("EOD_PARTIAL_REMAIN", f"order_id={cycle.acceptance_id} remain={remain:.8f}"),
                        "pos_id": _safe_str(open_pos.get("pos_id"), ""),
                    })
                    return

                set_open_pos(state, open_pos)
                log_trade({
                    "time": _now_str(now),
                    "result": "HOLD_OPEN_POS",
                    "side": _safe_str(open_pos.get("side"), ""),
                    "price": _safe_str(open_pos.get("entry_price"), ""),
                    "size": _safe_str(open_pos.get("size"), cfg.lot),
                    "ltp": ltp,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
                    "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                    "ma_fast": _safe_str(open_pos.get("ma_fast"), ""),
                    "ma_slow": _safe_str(open_pos.get("ma_slow"), ""),
                    "trend": _safe_str(open_pos.get("trend"), "UNKNOWN"),
                    "signal": _safe_str(open_pos.get("signal"), "NONE"),
                    "note": _append_note("EOD_EXIT_UNFILLED", f"order_id={cycle.acceptance_id}"),
                    "pos_id": _safe_str(open_pos.get("pos_id"), ""),
                })
                return

            log_trade({
                "time": _now_str(now),
                "result": "PAPER_EXIT_EOD",
                "side": _safe_str(open_pos.get("side"), ""),
                "price": _safe_str(open_pos.get("entry_price"), ""),
                "size": _safe_str(open_pos.get("size"), cfg.lot),
                "ltp": ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
                "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": _safe_str(open_pos.get("ma_fast"), ""),
                "ma_slow": _safe_str(open_pos.get("ma_slow"), ""),
                "trend": _safe_str(open_pos.get("trend"), "UNKNOWN"),
                "signal": _safe_str(open_pos.get("signal"), "NONE"),
                "note": _append_note(f"EOD_FORCE_CLOSE cutoff={EOD_CUTOFF.strftime('%H:%M:%S')}", live_note_prefix),
                "pos_id": _safe_str(open_pos.get("pos_id"), ""),
            })
            clear_open_pos(state)
            return

        # (14b) TP/SL/TIMEOUT/PARTIAL/EXTEND
        side0 = _safe_str(open_pos.get("side"), "BUY").upper()
        pos_id0 = _safe_str(open_pos.get("pos_id"), "")

        entry_price = float(open_pos["entry_price"])
        tp_price = float(open_pos["tp_price"])
        sl_price = float(open_pos["sl_price"])
        expiry_dt = _parse_dt_jst(open_pos["expiry_time_jst"]) or now
        entry_dt = _parse_dt_jst(open_pos.get("entry_time_jst"))
        hold_min_val: Optional[float] = None
        if entry_dt is not None:
            hold_min_val = max(0.0, float((now - entry_dt).total_seconds()) / 60.0)

        best_fav_now = calc_best_fav_pct(side0, entry_price, float(ltp))
        prev_best_fav = open_pos.get("best_fav", 0.0)
        try:
            prev_best_fav_f = float(prev_best_fav)
        except Exception:
            prev_best_fav_f = 0.0
        if best_fav_now is not None:
            open_pos["best_fav"] = round(max(prev_best_fav_f, float(best_fav_now)), 6)
            prev_max_adv = _safe_float(open_pos.get("max_adv"), 0.0)
            open_pos["max_adv"] = round(max(float(prev_max_adv), max(0.0, -float(best_fav_now))), 6)

        outcome: Optional[str] = None
        tech_exit_note = ""

        # Keep hard TP/SL labels authoritative.
        # tp_trail: stay past TP while trend continues; exit on giveback or timeout.
        def _resolve_tp_trail(pos):
            if not cfg.tp_trail_enabled:
                return True
            if not pos.get("_tp_trail_active"):
                pos["_tp_trail_active"] = True
                pos["_tp_trail_hit_jst"] = _now_str(now)
            _peak = float(pos.get("best_fav") or 0.0)
            _curr = float(best_fav_now or 0.0)
            if _peak - _curr >= cfg.tp_trail_giveback_pct:
                return True
            _hit = pos.get("_tp_trail_hit_jst")
            if _hit:
                try:
                    _age = (now - datetime.strptime(_hit, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60.0
                    if _age >= cfg.tp_trail_max_min:
                        return True
                except Exception:
                    return True
            return False

        if side0 == "BUY":
            if float(ltp) >= tp_price:
                if _resolve_tp_trail(open_pos):
                    outcome = "PAPER_EXIT_TP"
            elif float(ltp) <= sl_price:
                outcome = "PAPER_EXIT_SL"
        else:
            if float(ltp) <= tp_price:
                if _resolve_tp_trail(open_pos):
                    outcome = "PAPER_EXIT_TP"
            elif float(ltp) >= sl_price:
                outcome = "PAPER_EXIT_SL"

        # Refresh _fib_last every ~5 min during position hold (light fib re-eval for dashboard)
        if bool(cfg.fib_retracement_enabled):
            _fib_last_ts = _safe_str(state.get("_fib_last", {}).get("updated_at_jst"), "")
            _fib_stale = True
            if _fib_last_ts:
                try:
                    _fib_age_min = (now - datetime.strptime(_fib_last_ts, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60.0
                    _fib_stale = _fib_age_min >= 5.0
                except ValueError:
                    pass
            if _fib_stale:
                _fib_bars = get_ohlc_bars(state, include_current=True, max_bars=cfg.ohlc_max_bars)
                _fib_swings = extract_swing_points(_fib_bars, int(cfg.swing_lookback))
                _fib_snap = calc_fibonacci_retracement_snapshot(
                    _fib_swings, float(ltp), side0,
                    min_swing_range_pct=float(cfg.fib_min_swing_range_pct),
                )
                _fz = _safe_str(_fib_snap.get("fib_zone"), "NA")
                if _fz != "NA":
                    state["_fib_last"] = {
                        "zone": _fz,
                        "wave3_candidate": bool(_fib_snap.get("fib_wave3_candidate")),
                        "retrace_pct": _fib_snap.get("fib_retrace_pct"),
                        "swing_range_pct": _fib_snap.get("fib_swing_range_pct"),
                        "side": side0,
                        "updated_at_jst": _now_str(now),
                    }

        if outcome is None:
            early_adv_exit, early_adv_note = resolve_early_adverse_exit_status(
                open_pos,
                hold_min_val,
                best_fav_now,
                cfg,
            )
            if early_adv_exit:
                outcome = "PAPER_EXIT_EARLY_ADVERSE"
                tech_exit_note = _append_note(tech_exit_note, early_adv_note)

        if outcome is None:
            no_follow_exit, no_follow_note = resolve_no_follow_through_exit_status(
                open_pos,
                hold_min_val,
                best_fav_now,
                cfg,
            )
            if no_follow_exit:
                outcome = "PAPER_EXIT_TIMEOUT"
                tech_exit_note = _append_note(tech_exit_note, no_follow_note)

        if outcome is None:
            near_tp_exit, near_tp_note = resolve_near_tp_giveback_exit_status(
                open_pos,
                hold_min_val,
                best_fav_now,
                cfg,
            )
            if near_tp_exit:
                outcome = "PAPER_EXIT_TIMEOUT"
                tech_exit_note = _append_note(tech_exit_note, near_tp_note)

        if outcome is None:
            reversal_exit, reversal_exit_note = resolve_progress_reversal_exit_status(
                open_pos,
                hold_min_val,
                best_fav_now,
                cfg,
            )
            if reversal_exit:
                outcome = "PAPER_EXIT_TIMEOUT"
                tech_exit_note = _append_note(tech_exit_note, reversal_exit_note)

        # TECHNICAL EXIT (result契約は維持し、noteで理由を記録)
        if outcome is None and bool(cfg.exit_technical_enabled):
            op_exec_mode = _safe_str(open_pos.get("exec_mode"), "PAPER").upper()
            allow_tech_exit = (not bool(cfg.exit_technical_only_paper)) or (op_exec_mode == "PAPER")
            if allow_tech_exit:
                need_hold_min = max(0, int(cfg.exit_technical_min_hold_min))
                if hold_min_val is None or hold_min_val >= float(need_hold_min):
                    hit, reason, f_now, s_now, f_prev, s_prev = detect_sma_crossover_exit(
                        state=state,
                        side=side0,
                        fast_n=int(cfg.exit_sma_fast_n),
                        slow_n=int(cfg.exit_sma_slow_n),
                    )
                    if hit:
                        # 既存result契約を維持するため TIMEOUT 系を流用する
                        outcome = "PAPER_EXIT_TIMEOUT"
                        hold_s = "-" if hold_min_val is None else f"{hold_min_val:.1f}"
                        tech_exit_note = (
                            f"exit_tech={reason} "
                            f"exit_sma_fast_n={cfg.exit_sma_fast_n} "
                            f"exit_sma_slow_n={cfg.exit_sma_slow_n} "
                            f"sma_fast={float(f_now):.2f} sma_slow={float(s_now):.2f} "
                            f"sma_fast_prev={float(f_prev):.2f} sma_slow_prev={float(s_prev):.2f} "
                            f"hold_min={hold_s}"
                        )

        if outcome is None:
            pre_news_exit, pre_news_note = resolve_pre_news_exit_status(now, news_blocks, hold_min_val, cfg)
            if pre_news_exit:
                outcome = "PAPER_EXIT_PRENEWS"
                tech_exit_note = _append_note(tech_exit_note, pre_news_note)

        if outcome is None:
            weak_exit, weak_exit_note = resolve_weak_progress_exit_status(open_pos, hold_min_val, cfg)
            if weak_exit:
                outcome = "PAPER_EXIT_TIMEOUT"
                tech_exit_note = _append_note(tech_exit_note, weak_exit_note)

        # TIMEOUT family
        if outcome is None and now >= expiry_dt:
            timeout_mode = _safe_str(open_pos.get("timeout_mode"), cfg.timeout_mode).upper()
            if timeout_mode not in ("IGNORE", "EXTEND", "PARTIAL"):
                timeout_mode = cfg.timeout_mode

            if timeout_mode == "PARTIAL":
                trig = float(open_pos.get("partial_tp_trigger_pct", cfg.partial_tp_trigger_pct))
                bf = float(open_pos.get("best_fav", 0.0) or 0.0)
                outcome = "PAPER_EXIT_PARTIAL_TP" if bf >= trig else "PAPER_EXIT_TIMEOUT"

            elif timeout_mode == "EXTEND":
                extend_count = int(open_pos.get("extend_count", 0) or 0)
                max_ext = int(open_pos.get("max_extend_count", cfg.max_extend_count))
                ext_min = int(open_pos.get("extend_min", cfg.extend_min))
                need = float(open_pos.get("extend_min_bestfav_pct", cfg.extend_min_bestfav_pct))
                bf = float(open_pos.get("best_fav", 0.0) or 0.0)

                can_extend = (extend_count < max_ext) and (bf >= need)

                # AI extend gate (optional)
                ai_score_ext = None
                ai_note_ext = None
                if can_extend and cfg.ai_enabled and cfg.ai_dp_extend and cfg.ai_mode != "OFF":
                    ai = AIAdapter()
                    feats = ai.build_features(
                        cfg=cfg,
                        state=state,
                        now=now,
                        side=side0,
                        ltp=float(ltp),
                        spread_pct=spread_pct,
                        ma_fast=ma_fast,
                        ma_slow=ma_slow,
                        trend=trend,
                        blocked_news=False,
                    )
                    s, _ = ai.score(feats, cfg)
                    ok_ai, why_ai = ai.decide_extend(s, cfg)
                    ai_score_ext = float(s)
                    ai_note_ext = f"AI_EXT {why_ai}"
                    open_pos["ai_score_extend"] = ai_score_ext
                    open_pos["ai_note_extend"] = ai_note_ext
                    if not ok_ai:
                        can_extend = False
                    # update fib snapshot so dashboard shows live zone during position hold
                    _fib_zone_ext = _safe_str(feats.get("fib_zone"), "NA")
                    if _fib_zone_ext != "NA":
                        state["_fib_last"] = {
                            "zone": _fib_zone_ext,
                            "wave3_candidate": bool(feats.get("fib_wave3_candidate")),
                            "retrace_pct": feats.get("fib_retrace_pct"),
                            "swing_range_pct": feats.get("fib_swing_range_pct"),
                            "side": side0,
                            "updated_at_jst": _now_str(now),
                        }

                if can_extend:
                    new_expiry = (expiry_dt + timedelta(minutes=ext_min)).strftime("%Y-%m-%d %H:%M:%S")
                    open_pos["expiry_time_jst"] = new_expiry
                    open_pos["extend_count"] = extend_count + 1

                    # keep open_pos updated
                    set_open_pos(state, open_pos)

                    # log HOLD_OPEN_POS
                    note = f"EXTENDED exp={new_expiry} best_fav={open_pos.get('best_fav')} extend_count={open_pos.get('extend_count')}"
                    if ai_note_ext:
                        note = (note + " " + ai_note_ext).strip()

                    log_trade({
                        "time": _now_str(now),
                        "result": "HOLD_OPEN_POS",
                        "side": side0,
                        "price": entry_price,
                        "size": _safe_str(open_pos.get("size"), cfg.lot),
                        "ltp": ltp,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
                        "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                        "ma_fast": _safe_str(open_pos.get("ma_fast"), ""),
                        "ma_slow": _safe_str(open_pos.get("ma_slow"), ""),
                        "trend": _safe_str(open_pos.get("trend"), "UNKNOWN"),
                        "signal": _safe_str(open_pos.get("signal"), "NONE"),
                        "note": note,
                        "pos_id": pos_id0,
                    })
                    return

                outcome = "PAPER_EXIT_TIMEOUT"

            else:
                outcome = "PAPER_EXIT_TIMEOUT"

        # if exit decided -> log + clear
        if outcome:
            note = (
                f"entry={open_pos.get('entry_time_jst')} exp={open_pos.get('expiry_time_jst')} "
                f"best_fav={open_pos.get('best_fav')} max_adv={open_pos.get('max_adv', 0.0)} "
                f"current_fav={(round(float(best_fav_now), 6) if best_fav_now is not None else '')} "
                f"extend_count={open_pos.get('extend_count',0)}"
            )
            note = _append_note(note, f"exec={open_pos.get('exec_mode', 'PAPER')} stage={open_pos.get('effective_stage', effective_stage)}")
            note = _append_note(note, tech_exit_note)

            op_exec = _safe_str(open_pos.get("exec_mode"), "PAPER").upper()
            if op_exec == "LIVE":
                exit_side = _opposite_side(side0)
                size_now = _safe_float(open_pos.get("size"), cfg.lot)
                px = compute_exit_limit_price(exit_side, best_bid, best_ask, cfg.limit_price_offset_ticks)
                if live_client is None or px is None:
                    set_open_pos(state, open_pos)
                    note_hold = _append_note(note, "live_exit_unavailable")
                    log_trade({
                        "time": _now_str(now),
                        "result": "HOLD_OPEN_POS",
                        "side": side0,
                        "price": entry_price,
                        "size": _safe_str(open_pos.get("size"), cfg.lot),
                        "ltp": ltp,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
                        "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                        "ma_fast": _safe_str(open_pos.get("ma_fast"), ""),
                        "ma_slow": _safe_str(open_pos.get("ma_slow"), ""),
                        "trend": _safe_str(open_pos.get("trend"), "UNKNOWN"),
                        "signal": _safe_str(open_pos.get("signal"), "NONE"),
                        "note": note_hold,
                        "pos_id": pos_id0,
                    })
                    return

                cycle = run_live_limit_cycle(client=live_client, cfg=cfg, side=exit_side, size=size_now, price=px)
                state["_pending_exit"] = {
                    "at_jst": _now_str(now),
                    "pos_id": pos_id0,
                    "side": exit_side,
                    "size": size_now,
                    "price": px,
                    "status": cycle.status,
                    "acceptance_id": cycle.acceptance_id,
                    "filled_size": cycle.filled_size,
                    "result": outcome,
                }
                save_state(state)

                if cycle.status in ("ERROR", "NONE"):
                    set_open_pos(state, open_pos)
                    note_hold = _append_note(note, f"exit_unfilled order_id={cycle.acceptance_id} filled={cycle.filled_size:.8f}")
                    note_hold = _append_note(note_hold, cycle.note)
                    log_trade({
                        "time": _now_str(now),
                        "result": "HOLD_OPEN_POS",
                        "side": side0,
                        "price": entry_price,
                        "size": _safe_str(open_pos.get("size"), cfg.lot),
                        "ltp": ltp,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
                        "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                        "ma_fast": _safe_str(open_pos.get("ma_fast"), ""),
                        "ma_slow": _safe_str(open_pos.get("ma_slow"), ""),
                        "trend": _safe_str(open_pos.get("trend"), "UNKNOWN"),
                        "signal": _safe_str(open_pos.get("signal"), "NONE"),
                        "note": note_hold,
                        "pos_id": pos_id0,
                    })
                    return

                filled = float(cycle.filled_size)
                remaining = max(0.0, size_now - filled)
                if remaining > PARTIAL_REMAIN_EPS:
                    open_pos["size"] = float(round(remaining, 8))
                    set_open_pos(state, open_pos)
                    note_hold = _append_note(note, f"exit_partial order_id={cycle.acceptance_id} filled={filled:.8f} remain={remaining:.8f}")
                    note_hold = _append_note(note_hold, cycle.note)
                    log_trade({
                        "time": _now_str(now),
                        "result": "HOLD_OPEN_POS",
                        "side": side0,
                        "price": entry_price,
                        "size": _safe_str(open_pos.get("size"), cfg.lot),
                        "ltp": ltp,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
                        "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                        "ma_fast": _safe_str(open_pos.get("ma_fast"), ""),
                        "ma_slow": _safe_str(open_pos.get("ma_slow"), ""),
                        "trend": _safe_str(open_pos.get("trend"), "UNKNOWN"),
                        "signal": _safe_str(open_pos.get("signal"), "NONE"),
                        "note": note_hold,
                        "pos_id": pos_id0,
                    })
                    return

                note = _append_note(note, f"order_id={cycle.acceptance_id} filled={cycle.filled_size:.8f}")
                note = _append_note(note, cycle.note)

            log_trade({
                "time": _now_str(now),
                "result": outcome,
                "side": side0,
                "price": entry_price,
                "size": _safe_str(open_pos.get("size"), cfg.lot),
                "ltp": ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
                "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": _safe_str(open_pos.get("ma_fast"), ""),
                "ma_slow": _safe_str(open_pos.get("ma_slow"), ""),
                "trend": _safe_str(open_pos.get("trend"), "UNKNOWN"),
                "signal": _safe_str(open_pos.get("signal"), "NONE"),
                "note": note,
                "pos_id": pos_id0,
            })
            clear_open_pos(state)
            return

        # still holding
        set_open_pos(state, open_pos)
        if cfg.one_position_only:
            log_trade({
                "time": _now_str(now),
                "result": "HOLD_OPEN_POS",
                "side": side0,
                "price": entry_price,
                "size": _safe_str(open_pos.get("size"), cfg.lot),
                "ltp": ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
                "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": _safe_str(open_pos.get("ma_fast"), ""),
                "ma_slow": _safe_str(open_pos.get("ma_slow"), ""),
                "trend": _safe_str(open_pos.get("trend"), "UNKNOWN"),
                "signal": _safe_str(open_pos.get("signal"), "NONE"),
                "note": f"OPEN exp={open_pos.get('expiry_time_jst')} best_fav={open_pos.get('best_fav')} extend_count={open_pos.get('extend_count',0)}",
                "pos_id": pos_id0,
            })
            return

    # (15) No open_pos: ENTRY flow (must be within trade window)
    if not in_trade_time:
        # eod window with no open_pos => do nothing
        return

    eod_entry_blocked, eod_entry_note = resolve_eod_entry_block_status(now, cfg)
    if eod_entry_blocked:
        log_trade({
            "time": _now_str(now),
            "result": "OBSERVE_TIME_BLOCK",
            "side": "",
            "price": "",
            "size": "",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
            "limit_pct": round(cfg.spread_limit_pct * 100, 6),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": _append_note(eod_entry_note, feature_note),
            "pos_id": "",
        })
        return

    # (15a) today_on
    if not cfg.today_on:
        return  # SPEC: safe return

    # safety hard block (new entries blocked)
    if cfg.safety_hard_block:
        log_trade({
            "time": _now_str(now),
            "result": "OBSERVE_TRADE_DISABLED",
            "side": "",
            "price": "",
            "size": "",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
            "limit_pct": round(cfg.spread_limit_pct * 100, 6),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": _append_note(_append_note("safety_hard_block=1", live_note_prefix), feature_note),
            "pos_id": "",
        })
        return

    if exec_live and risk_stop:
        log_trade({
            "time": _now_str(now),
            "result": "OBSERVE_TRADE_DISABLED",
            "side": "",
            "price": "",
            "size": "",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
            "limit_pct": round(cfg.spread_limit_pct * 100, 6),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": _append_note(_append_note(_append_note("risk_stop=1", risk_note), live_note_prefix), feature_note),
            "pos_id": "",
        })
        return

    # (15b) trade_enabled => if false -> observe_only path
    if not cfg.trade_enabled:
        log_trade({
            "time": _now_str(now),
            "result": "OBSERVE_TRADE_DISABLED",
            "side": "",
            "price": "",
            "size": "",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
            "limit_pct": round(cfg.spread_limit_pct * 100, 6),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": _append_note(_append_note("trade_enabled=0", live_note_prefix), feature_note),
            "pos_id": "",
        })
        return

    # (15b-2) NEWS/LUNCH guard for new entries only
    news_blocked_for_entry, news_entry_note = resolve_entry_news_block_status(now, news_blocks, cfg)
    if news_blocked_for_entry:
        log_trade({
            "time": _now_str(now),
            "result": "SKIP_NEWS",
            "side": "",
            "price": "",
            "size": "",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
            "limit_pct": round(cfg.spread_limit_pct * 100, 6),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": _append_note(news_entry_note, feature_note),
            "pos_id": "",
        })
        return

    # (15c) spread limit
    if spread_pct is None or spread_pct >= cfg.spread_limit_pct:
        log_trade({
            "time": _now_str(now),
            "result": "SKIP_SPREAD",
            "side": "",
            "price": "",
            "size": "",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
            "limit_pct": round(cfg.spread_limit_pct * 100, 6),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": _append_note("spread_block", feature_note),
            "pos_id": "",
        })
        return

    # (15d) signal NONE => OBSERVE_NO_SIGNAL (must remain as denominator)
    if signal == "NONE":
        log_trade({
            "time": _now_str(now),
            "result": "OBSERVE_NO_SIGNAL",
            "side": "",
            "price": "",
            "size": "",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": "" if spread_pct is None else round(spread_pct * 100, 6),
            "limit_pct": round(cfg.spread_limit_pct * 100, 6),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": feature_note,
            "pos_id": "",
        })
        return

    # (15e) daily limit
    day_key = now.strftime("%Y-%m-%d")
    if trades_today(state, day_key) >= cfg.max_trades_per_day:
        log_trade({
            "time": _now_str(now),
            "result": "SKIP_DAILY_LIMIT",
            "side": "",
            "price": "",
            "size": "",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": round(spread_pct * 100, 6),
            "limit_pct": round(cfg.spread_limit_pct * 100, 6),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": "",
            "pos_id": "",
        })
        return

    # (15e-2) consecutive losing streak stop (optional)
    streak_stop, streak_note = get_loss_streak_guard_status(state, cfg, now)
    if streak_stop:
        # Fib golden zone exception: override streak stop when last fib evaluation shows GOLDEN
        _fib_exc = False
        if bool(cfg.fib_retracement_enabled):
            _fib_snap_st = state.get("_fib_last") or {}
            _fib_zone_st = _safe_str(_fib_snap_st.get("zone"), "NA")
            _fib_upd_st = _safe_str(_fib_snap_st.get("updated_at_jst"), "")
            _fib_fresh = False
            if _fib_upd_st:
                try:
                    _fib_age = (now - datetime.strptime(_fib_upd_st, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60.0
                    _fib_fresh = _fib_age <= 10.0
                except ValueError:
                    pass
            if _fib_zone_st == "GOLDEN" and _fib_fresh:
                _fib_exc = True
                streak_note = _append_note(streak_note, "fib_golden_exception=1")
        if not _fib_exc:
            log_trade({
                "time": _now_str(now),
                "result": "SKIP_DAILY_LIMIT",
                "side": "",
                "price": "",
                "size": "",
                "ltp": ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": round(spread_pct * 100, 6),
                "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": "" if ma_fast is None else ma_fast,
                "ma_slow": "" if ma_slow is None else ma_slow,
                "trend": trend,
                "signal": signal,
                "note": _append_note("loss_streak_stop=1", streak_note),
                "pos_id": "",
            })
            return

    # (15f) no_paper_hours => OBSERVE_OK
    if now.hour in cfg.no_paper_hours:
        log_trade({
            "time": _now_str(now),
            "result": "OBSERVE_TIME_BLOCK",
            "side": "",
            "price": "",
            "size": "",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": round(spread_pct * 100, 6),
            "limit_pct": round(cfg.spread_limit_pct * 100, 6),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": _append_note("no_paper_hour", feature_note),
            "pos_id": "",
        })
        return

    # (15f-2) dedicated observe-only MR layer
    if cfg.observe_only and cfg.mr_observe_enabled:
        mr_result, mr_note = resolve_mr_observe(signal, state, float(ltp), ma_fast, ma_slow, cfg)
        if mr_result:
            mr_note_full = _append_note(mr_note, feature_note)
            mr_paper_ok, mr_paper_note = resolve_mr_paper_promotion(mr_result, mr_note, cfg)
            if mr_paper_ok:
                side = "BUY" if signal == "BUY_CANDIDATE" else "SELL"
                entry_price = float(best_bid) if side == "BUY" else float(best_ask)
                order_size = max(float(cfg.lot), 0.0)
                tp_pct = resolve_entry_tp_pct(cfg, side, effective_stage)
                tp_price, sl_price = calc_tp_sl_prices(side, entry_price, tp_pct, cfg.sl_pct)
                expiry_time = (now + timedelta(minutes=int(cfg.win_min))).strftime("%Y-%m-%d %H:%M:%S")

                day8 = now.strftime("%Y%m%d")
                seq = next_pos_seq(state, day8)
                pos_id = make_pos_id(now, side=side, seq=seq)
                open_pos_new: Dict[str, Any] = {
                    "pos_id": pos_id,
                    "entry_time_jst": _now_str(now),
                    "side": side,
                    "entry_price": float(entry_price),
                    "tp_price": float(round(tp_price, 1)),
                    "sl_price": float(round(sl_price, 1)),
                    "expiry_time_jst": expiry_time,
                    "trend": trend,
                    "signal": signal,
                    "ma_fast": ma_fast,
                    "ma_slow": ma_slow,
                    "tp_pct": float(tp_pct),
                    "sl_pct": float(cfg.sl_pct),
                    "timeout_mode": _safe_str(cfg.timeout_mode, TIMEOUT_MODE_DEFAULT),
                    "max_extend_count": int(cfg.max_extend_count),
                    "extend_min": int(cfg.extend_min),
                    "extend_min_bestfav_pct": float(cfg.extend_min_bestfav_pct),
                    "partial_tp_trigger_pct": float(cfg.partial_tp_trigger_pct),
                    "size": float(order_size),
                    "best_fav": 0.0,
                    "max_adv": 0.0,
                    "extend_count": 0,
                    "tune_note": "strategy=MR",
                    "win_used": int(cfg.win_min),
                    "entry_strategy": "MR",
                    "mr_rank": _extract_note_value(mr_note, "mr_rank"),
                    "mr_score": _extract_note_value(mr_note, "mr_score"),
                    "mr_reclaim": _extract_note_value(mr_note, "mr_reclaim"),
                    "exec_mode": "PAPER",
                    "effective_stage": effective_stage,
                    "order_id_entry": "",
                    "ai_score_extend": None,
                    "ai_note_extend": None,
                }
                set_open_pos(state, open_pos_new)

                paper_note = (
                    f"tp={round(tp_price,1)} sl={round(sl_price,1)} win_used={int(cfg.win_min)}m "
                    f"exp={expiry_time} tp_pct={tp_pct} sl_pct={cfg.sl_pct} timeout_mode={cfg.timeout_mode}"
                )
                paper_note = _append_note(paper_note, mr_paper_note)
                paper_note = _append_note(paper_note, mr_note_full)
                paper_note = _append_note(paper_note, live_note_prefix)
                log_trade({
                    "time": _now_str(now),
                    "result": "PAPER",
                    "side": side,
                    "price": entry_price,
                    "size": float(order_size),
                    "ltp": ltp,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread_pct": round(spread_pct * 100, 6),
                    "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                    "ma_fast": "" if ma_fast is None else ma_fast,
                    "ma_slow": "" if ma_slow is None else ma_slow,
                    "trend": trend,
                    "signal": signal,
                    "note": paper_note,
                    "pos_id": pos_id,
                })
                inc_trades_today(state, day_key)
                return

            log_trade({
                "time": _now_str(now),
                "result": mr_result,
                "side": "",
                "price": "",
                "size": "",
                "ltp": ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": round(spread_pct * 100, 6),
                "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": "" if ma_fast is None else ma_fast,
                "ma_slow": "" if ma_slow is None else ma_slow,
                "trend": trend,
                "signal": signal,
                "note": mr_note_full,
                "pos_id": "",
            })
            return

    # (15f-3) optional A/B/C phase guard: avoid range-like B phase entries.
    if bool(cfg.market_phase_block_b_enabled) and _safe_str(market_phase_snapshot.get("phase"), "").upper() == "B":
        log_trade({
            "time": _now_str(now),
            "result": "OBSERVE_PHASE_B",
            "side": "",
            "price": "",
            "size": "",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": round(spread_pct * 100, 6),
            "limit_pct": round(cfg.spread_limit_pct * 100, 6),
            "ma_fast": "" if ma_fast is None else ma_fast,
            "ma_slow": "" if ma_slow is None else ma_slow,
            "trend": trend,
            "signal": signal,
            "note": _append_note("phase_b_entry_block=1", feature_note),
            "pos_id": "",
        })
        return

    # (15g) fast MA near filter => observe
    fast_ma_observe_result, fast_ma_observe_note = resolve_fast_ma_observe(signal, float(ltp), ma_fast, cfg)
    if fast_ma_observe_result:
        log_trade({
            "time": _now_str(now),
            "result": fast_ma_observe_result,
            "side": "",
            "price": "",
            "size": "",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": round(spread_pct * 100, 6),
            "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": "" if ma_fast is None else ma_fast,
                "ma_slow": "" if ma_slow is None else ma_slow,
                "trend": trend,
                "signal": signal,
                "note": _append_note(fast_ma_observe_note, feature_note),
                "pos_id": "",
            })
        return

    # (15h) trend flip cooldown => observe
    trend_flip_blocked, trend_flip_note = get_trend_flip_cooldown_status(state, cfg, now, trend, signal)
    if trend_flip_blocked:
        log_trade({
            "time": _now_str(now),
            "result": "OBSERVE_TREND_FLIP_COOLDOWN",
            "side": "",
            "price": "",
            "size": "",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": round(spread_pct * 100, 6),
            "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": "" if ma_fast is None else ma_fast,
                "ma_slow": "" if ma_slow is None else ma_slow,
                "trend": trend,
                "signal": signal,
                "note": _append_note(trend_flip_note, feature_note),
                "pos_id": "",
            })
        return

    # (15i) trend strength filter => observe
    trend_strength_observe_result, trend_strength_observe_note = resolve_trend_strength_observe(signal, state, cfg)
    if trend_strength_observe_result:
        log_trade({
            "time": _now_str(now),
            "result": trend_strength_observe_result,
            "side": "",
            "price": "",
            "size": "",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": round(spread_pct * 100, 6),
            "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": "" if ma_fast is None else ma_fast,
                "ma_slow": "" if ma_slow is None else ma_slow,
                "trend": trend,
                "signal": signal,
                "note": _append_note(trend_strength_observe_note, feature_note),
                "pos_id": "",
            })
        return

    # (15j) observe_only => OBSERVE_OK
    if cfg.observe_only:
        log_trade({
            "time": _now_str(now),
            "result": "OBSERVE_OK",
            "side": "",
            "price": "",
            "size": "",
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": round(spread_pct * 100, 6),
            "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": "" if ma_fast is None else ma_fast,
                "ma_slow": "" if ma_slow is None else ma_slow,
                "trend": trend,
                "signal": signal,
                "note": _append_note("observe_only=1", feature_note),
                "pos_id": "",
            })
        return

    # (15k) AI entry decision (block => OBSERVE_OK + note "AI_BLOCK ...")
    side = "BUY" if signal == "BUY_CANDIDATE" else "SELL"
    ai_score = ""
    ai_note = ""
    if cfg.ai_enabled and cfg.ai_dp_entry and cfg.ai_mode != "OFF":
        ai = AIAdapter()
        feats = ai.build_features(
            cfg=cfg,
            state=state,
            now=now,
            side=side,
            ltp=float(ltp),
            spread_pct=spread_pct,
            ma_fast=ma_fast,
            ma_slow=ma_slow,
            trend=trend,
            blocked_news=False,
        )
        s, comps = ai.score(feats, cfg)
        ok_ai, why_ai = ai.decide_entry(s, cfg)
        ai_score = f"{float(s):.6f}"
        ai_note = f"AI score={float(s):.3f} {why_ai}"
        # add sim tags (contract wants these in note if possible)
        gate_sim = "ALLOW" if float(s) >= cfg.ai_th_entry else "BLOCK"
        veto_low = _clamp(1.0 - cfg.ai_veto_min_conf, 0.0, 1.0)
        veto_sim = "BLOCK" if float(s) <= veto_low else "ALLOW"
        ai_note = f"{ai_note} GATE_SIM={gate_sim} VETO_SIM={veto_sim}"
        if "htf60_countertrend" in comps:
            ai_note = f"{ai_note} htf60_countertrend=1"
        if "htf15_60_conflict" in comps:
            ai_note = f"{ai_note} htf15_60_conflict=1"
        feat_cross_note = _safe_str(feats.get("ma_cross_note"), "")
        if feat_cross_note:
            ai_note = f"{ai_note} {feat_cross_note}".strip()
        feat_tech_note = _safe_str(feats.get("ti_note"), "")
        if feat_tech_note:
            ai_note = f"{ai_note} {feat_tech_note}".strip()
        feat_pattern_note = _safe_str(feats.get("pattern_note"), "")
        if feat_pattern_note:
            ai_note = f"{ai_note} {feat_pattern_note}".strip()
        feat_phase_note = _safe_str(feats.get("market_phase_note"), "")
        if feat_phase_note:
            ai_note = f"{ai_note} {feat_phase_note}".strip()
        feat_aiba_note = _safe_str(feats.get("aiba_note"), "")
        if feat_aiba_note:
            ai_note = f"{ai_note} {feat_aiba_note}".strip()
        if "ma_cross" in comps:
            ai_note = f"{ai_note} ma_cross_comp={round(float(comps['ma_cross']), 6)}"
        if "technical" in comps:
            ai_note = f"{ai_note} technical_comp={round(float(comps['technical']), 6)}"
        if "chart_pattern" in comps:
            ai_note = f"{ai_note} chart_pattern_comp={round(float(comps['chart_pattern']), 6)}"
        if "market_phase" in comps:
            ai_note = f"{ai_note} market_phase_comp={round(float(comps['market_phase']), 6)}"
        if "aiba_style" in comps:
            ai_note = f"{ai_note} aiba_style_comp={round(float(comps['aiba_style']), 6)}"
        if "fib" in comps:
            ai_note = f"{ai_note} fib_comp={round(float(comps['fib']), 6)}"
        if "fib_aiba_combo" in comps:
            ai_note = f"{ai_note} fib_aiba_combo_comp={round(float(comps['fib_aiba_combo']), 6)}"
        # save fib snapshot for dashboard display
        fib_zone_now = _safe_str(feats.get("fib_zone"), "NA")
        if fib_zone_now != "NA":
            state["_fib_last"] = {
                "zone": fib_zone_now,
                "wave3_candidate": bool(feats.get("fib_wave3_candidate")),
                "retrace_pct": feats.get("fib_retrace_pct"),
                "swing_range_pct": feats.get("fib_swing_range_pct"),
                "side": side,
                "updated_at_jst": _now_str(now),
            }

        if not ok_ai:
            log_trade({
                "time": _now_str(now),
                "result": "OBSERVE_AI_BLOCK",
                "side": "",
                "price": "",
                "size": "",
                "ltp": ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": round(spread_pct * 100, 6),
                "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": "" if ma_fast is None else ma_fast,
                "ma_slow": "" if ma_slow is None else ma_slow,
                "trend": trend,
                "signal": signal,
                "note": ("AI_BLOCK " + ai_note).strip(),
                "pos_id": "",
            })
            return

        # Hard gates — block even when AI score passes (5/15-16 loss analysis)
        def _hard_block(reason: str) -> None:
            log_trade({"time": _now_str(now), "result": "OBSERVE_AI_BLOCK",
                       "side": "", "price": "", "size": "",
                       "ltp": ltp, "best_bid": best_bid, "best_ask": best_ask,
                       "spread_pct": round(spread_pct * 100, 6),
                       "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                       "ma_fast": "" if ma_fast is None else ma_fast,
                       "ma_slow": "" if ma_slow is None else ma_slow,
                       "trend": trend, "signal": signal,
                       "note": reason, "pos_id": ""})

        # (A) Confirmed chart pattern that contradicts entry direction
        _pat_bias      = _safe_str(feats.get("pattern_bias"), "NEUTRAL").upper()
        _pat_name      = _safe_str(feats.get("pattern_name"), "").upper()
        _pat_confirmed = bool(feats.get("pattern_confirmed"))
        if _pat_confirmed and (
            (_pat_bias == "SELL" and side == "BUY") or
            (_pat_bias == "BUY"  and side == "SELL")
        ):
            _hard_block(f"CP_COUNTER_BLOCK {_pat_name} cp_bias={_pat_bias} side={side} {ai_note}".strip())
            return

        # (B) Technical composite score strongly negative — overall technicals oppose entry
        _tech_comp = float(comps.get("technical", 0.0))
        if _tech_comp < -0.10:
            _hard_block(f"TECH_COMP_BLOCK technical_comp={round(_tech_comp, 3)} th=-0.10 {ai_note}".strip())
            return

        # (C) Too many failed-try accumulations — market repeatedly rejecting direction
        _try_fail_cnt = int(_safe_int(feats.get("aiba_try_fail_count"), 0))
        if _try_fail_cnt >= 3:
            _hard_block(f"TRY_FAIL_BLOCK count={_try_fail_cnt} th=3 {ai_note}".strip())
            return

    # (15l) pos_id issuance + open_pos save
    order_size = effective_lot(cfg, effective_stage) if exec_live else float(cfg.lot)
    entry_price = float(best_bid) if side == "BUY" else float(best_ask)
    entry_order_note = ""
    if exec_live:
        order_size, ai_lot_note = apply_ai_lot_lock(cfg, state, order_size)
        if ai_lot_note:
            entry_order_note = _append_note(entry_order_note, ai_lot_note)
        vol_pct = feats.get("volatility_pct") if feats else None
        order_size, vol_lot_note = apply_vol_lot_scale(cfg, vol_pct, order_size)
        if vol_lot_note:
            entry_order_note = _append_note(entry_order_note, vol_lot_note)
    if exec_live:
        limit_px = compute_limit_price(side, best_bid, best_ask, cfg.limit_price_offset_ticks)
        if limit_px is None:
            log_trade({
                "time": _now_str(now),
                "result": "OBSERVE_OK",
                "side": "",
                "price": "",
                "size": "",
                "ltp": ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": round(spread_pct * 100, 6),
                "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": "" if ma_fast is None else ma_fast,
                "ma_slow": "" if ma_slow is None else ma_slow,
                "trend": trend,
                "signal": signal,
                "note": _append_note("live_limit_price_unavailable", live_note_prefix),
                "pos_id": "",
            })
            return

        order_size, fx_size_note = adjust_live_entry_size(
            live_client,
            cfg,
            order_size,
            float(limit_px),
        )
        if fx_size_note:
            entry_order_note = _append_note(entry_order_note, fx_size_note)
        if order_size <= PARTIAL_REMAIN_EPS:
            log_trade({
                "time": _now_str(now),
                "result": "OBSERVE_OK",
                "side": "",
                "price": "",
                "size": "",
                "ltp": ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": round(spread_pct * 100, 6),
                "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": "" if ma_fast is None else ma_fast,
                "ma_slow": "" if ma_slow is None else ma_slow,
                "trend": trend,
                "signal": signal,
                "note": _append_note("entry_size_zero_after_fx_cap", _append_note(live_note_prefix, fx_size_note)),
                "pos_id": "",
            })
            return

        cycle = run_live_limit_cycle(client=live_client, cfg=cfg, side=side, size=order_size, price=limit_px)
        state["_pending_entry"] = {
            "at_jst": _now_str(now),
            "side": side,
            "size": order_size,
            "price": limit_px,
            "status": cycle.status,
            "acceptance_id": cycle.acceptance_id,
            "filled_size": cycle.filled_size,
        }
        save_state(state)
        if cycle.status in ("ERROR", "NONE"):
            note0 = _append_note("entry_unfilled", live_note_prefix)
            note0 = _append_note(note0, f"order_id={cycle.acceptance_id}")
            note0 = _append_note(note0, f"filled={cycle.filled_size:.8f}")
            note0 = _append_note(note0, cycle.note)
            log_trade({
                "time": _now_str(now),
                "result": "OBSERVE_OK",
                "side": "",
                "price": "",
                "size": "",
                "ltp": ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": round(spread_pct * 100, 6),
                "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": "" if ma_fast is None else ma_fast,
                "ma_slow": "" if ma_slow is None else ma_slow,
                "trend": trend,
                "signal": signal,
                "note": note0,
                "pos_id": "",
            })
            return

        filled = float(cycle.filled_size)
        if filled <= PARTIAL_REMAIN_EPS:
            log_trade({
                "time": _now_str(now),
                "result": "OBSERVE_OK",
                "side": "",
                "price": "",
                "size": "",
                "ltp": ltp,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": round(spread_pct * 100, 6),
                "limit_pct": round(cfg.spread_limit_pct * 100, 6),
                "ma_fast": "" if ma_fast is None else ma_fast,
                "ma_slow": "" if ma_slow is None else ma_slow,
                "trend": trend,
                "signal": signal,
                "note": _append_note("entry_filled_zero", live_note_prefix),
                "pos_id": "",
            })
            return
        order_size = filled
        entry_price = float(cycle.average_price) if cycle.average_price is not None else float(limit_px)
        entry_order_note = _append_note(
            _append_note(f"order_id={cycle.acceptance_id}", f"filled={cycle.filled_size:.8f}"),
            cycle.note,
        )

    tp_pct = resolve_entry_tp_pct(cfg, side, effective_stage)
    tp_price, sl_price = calc_tp_sl_prices(side, entry_price, tp_pct, cfg.sl_pct)
    expiry_time = (now + timedelta(minutes=int(cfg.win_min))).strftime("%Y-%m-%d %H:%M:%S")

    day8 = now.strftime("%Y%m%d")
    seq = next_pos_seq(state, day8)
    pos_id = make_pos_id(now, side=side, seq=seq)

    # learning/audit features for open_pos
    spread_entry_pct = (spread_pct * 100.0) if spread_pct is not None else ""
    ma_gap = calc_ma_gap_pct(ma_fast, ma_slow)
    ma_slope = calc_ma_slope_pct_per_step(state, n=cfg.fast_n)
    vol = calc_volatility_pct(state, n=max(20, cfg.slow_n))
    trendline_slope = calc_trendline_slope_pct_per_step(state, n=max(20, cfg.slow_n))
    channel_pos = calc_channel_position(state, n=max(20, cfg.slow_n))
    channel_width = calc_channel_width_pct(state, n=max(20, cfg.slow_n))
    htf15 = calc_htf_context(
        state,
        group_n=3,
        lookback_n=cfg.htf_context_lookback_n,
        bias_slope_pct=cfg.htf_bias_slope_pct,
    ) if bool(cfg.htf15_context_enabled) else {}
    htf60 = calc_htf_context(
        state,
        group_n=12,
        lookback_n=cfg.htf_context_lookback_n,
        bias_slope_pct=cfg.htf_bias_slope_pct,
    ) if bool(cfg.htf60_context_enabled) else {}
    ma_cross_entry = ma_cross_snapshot if bool(cfg.ma_cross_feature_enabled) else {}
    tech_entry = tech_snapshot if bool(cfg.tech_indicators_enabled) else {}
    pattern_entry = pattern_snapshot if bool(cfg.chart_pattern_enabled) else {}
    phase_entry = market_phase_snapshot if bool(cfg.market_phase_enabled) else {}
    aiba_entry = aiba_style_snapshot if bool(cfg.aiba_style_enabled) else {}

    open_pos_new: Dict[str, Any] = {
        # identity
        "pos_id": pos_id,
        "entry_time_jst": _now_str(now),
        "side": side,

        # prices
        "entry_price": float(entry_price),
        "tp_price": float(round(tp_price, 1)),
        "sl_price": float(round(sl_price, 1)),
        "expiry_time_jst": expiry_time,

        # context
        "trend": trend,
        "signal": signal,
        "ma_fast": ma_fast,
        "ma_slow": ma_slow,

        # config snapshot
        "tp_pct": float(tp_pct),
        "sl_pct": float(cfg.sl_pct),
        "timeout_mode": _safe_str(cfg.timeout_mode, TIMEOUT_MODE_DEFAULT),
        "max_extend_count": int(cfg.max_extend_count),
        "extend_min": int(cfg.extend_min),
        "extend_min_bestfav_pct": float(cfg.extend_min_bestfav_pct),
        "partial_tp_trigger_pct": float(cfg.partial_tp_trigger_pct),
        "size": float(order_size),

        # performance
        "best_fav": 0.0,
        "max_adv": 0.0,
        "extend_count": 0,

        # notes reserve
        "tune_note": "",
        "win_used": int(cfg.win_min),

        # learning/audit features
        "spread_entry_pct": spread_entry_pct,
        "ma_gap_pct": "" if ma_gap is None else float(round(ma_gap, 6)),
        "ma_slope_pct_per_step": "" if ma_slope is None else float(round(ma_slope, 8)),
        "volatility_pct": "" if vol is None else float(round(vol, 8)),
        "trendline_slope_pct_per_step": "" if trendline_slope is None else float(round(trendline_slope, 8)),
        "channel_pos": "" if channel_pos is None else float(round(channel_pos, 8)),
        "channel_width_pct": "" if channel_width is None else float(round(channel_width, 8)),
        "ma_cross_type": _safe_str(ma_cross_entry.get("cross_type"), ""),
        "ma_cross_recent_type": _safe_str(ma_cross_entry.get("recent_cross_type"), ""),
        "ma_cross_recent_age_bars": "" if ma_cross_entry.get("recent_cross_age_bars") is None else int(ma_cross_entry.get("recent_cross_age_bars")),
        "ma_cross_strong": bool(ma_cross_entry.get("strong", False)),
        "ma_cross_gap_pct": "" if ma_cross_entry.get("ma_gap_pct") is None else float(round(float(ma_cross_entry.get("ma_gap_pct")), 8)),
        "ma_cross_slow_slope_pct": "" if ma_cross_entry.get("slow_slope_pct") is None else float(round(float(ma_cross_entry.get("slow_slope_pct")), 8)),
        "ma_cross_price_position": _safe_str(ma_cross_entry.get("price_position"), ""),
        "ti_rsi": "" if tech_entry.get("rsi") is None else float(round(float(tech_entry.get("rsi")), 6)),
        "ti_rsi_zone": _safe_str(tech_entry.get("rsi_zone"), ""),
        "ti_bb_pos": "" if tech_entry.get("bb_pos") is None else float(round(float(tech_entry.get("bb_pos")), 8)),
        "ti_bb_width_pct": "" if tech_entry.get("bb_width_pct") is None else float(round(float(tech_entry.get("bb_width_pct")), 8)),
        "ti_bb_zone": _safe_str(tech_entry.get("bb_zone"), ""),
        "ti_bb_break": _safe_str(tech_entry.get("bb_breakout"), ""),
        "ti_atr_pct": "" if tech_entry.get("atr_pct") is None else float(round(float(tech_entry.get("atr_pct")), 8)),
        "ti_atr_regime": _safe_str(tech_entry.get("atr_regime"), ""),
        "ti_trend_power": "" if tech_entry.get("trend_power") is None else float(round(float(tech_entry.get("trend_power")), 8)),
        "ti_trend_power_regime": _safe_str(tech_entry.get("trend_power_regime"), ""),
        "pattern_name": _safe_str(pattern_entry.get("pattern_name"), ""),
        "pattern_stage": _safe_str(pattern_entry.get("pattern_stage"), ""),
        "pattern_bias": _safe_str(pattern_entry.get("pattern_bias"), ""),
        "pattern_confirmed": bool(pattern_entry.get("pattern_confirmed", False)),
        "pattern_neckline": "" if pattern_entry.get("neckline") is None else float(round(float(pattern_entry.get("neckline")), 2)),
        "pattern_trend": _safe_str(pattern_entry.get("pattern_trend"), ""),
        "pattern_quality": _safe_str(pattern_entry.get("pattern_quality"), ""),
        "pattern_avg_ticks": "" if pattern_entry.get("pattern_avg_ticks") is None else float(round(float(pattern_entry.get("pattern_avg_ticks")), 4)),
        "pattern_swing_high_1": "" if pattern_entry.get("swing_high_1") is None else float(round(float(pattern_entry.get("swing_high_1")), 2)),
        "pattern_swing_high_2": "" if pattern_entry.get("swing_high_2") is None else float(round(float(pattern_entry.get("swing_high_2")), 2)),
        "pattern_swing_low_1": "" if pattern_entry.get("swing_low_1") is None else float(round(float(pattern_entry.get("swing_low_1")), 2)),
        "pattern_swing_low_2": "" if pattern_entry.get("swing_low_2") is None else float(round(float(pattern_entry.get("swing_low_2")), 2)),
        "market_phase": _safe_str(phase_entry.get("phase"), ""),
        "market_phase_reason": _safe_str(phase_entry.get("phase_reason"), ""),
        "market_phase_slope_pct": "" if phase_entry.get("ma_slope_pct") is None else float(round(float(phase_entry.get("ma_slope_pct")), 8)),
        "market_phase_gap_pct": "" if phase_entry.get("ma_gap_pct") is None else float(round(float(phase_entry.get("ma_gap_pct")), 8)),
        "market_phase_range_width_pct": "" if phase_entry.get("range_width_pct") is None else float(round(float(phase_entry.get("range_width_pct")), 8)),
        "market_phase_prev_high": "" if phase_entry.get("previous_high") is None else float(round(float(phase_entry.get("previous_high")), 2)),
        "market_phase_prev_low": "" if phase_entry.get("previous_low") is None else float(round(float(phase_entry.get("previous_low")), 2)),
        "market_phase_up_break": bool(phase_entry.get("up_break", False)),
        "market_phase_down_break": bool(phase_entry.get("down_break", False)),
        "market_phase_momentum": _safe_str(phase_entry.get("momentum"), ""),
        "aiba_trend": _safe_str(aiba_entry.get("trend"), ""),
        "aiba_cross": _safe_str(aiba_entry.get("cross_type"), ""),
        "aiba_ppp": _safe_str(aiba_entry.get("ppp_flag"), ""),
        "aiba_ma5": "" if aiba_entry.get("ma_short") is None else float(round(float(aiba_entry.get("ma_short")), 2)),
        "aiba_ma20": "" if aiba_entry.get("ma_mid") is None else float(round(float(aiba_entry.get("ma_mid")), 2)),
        "aiba_ma_long": "" if aiba_entry.get("ma_long") is None else float(round(float(aiba_entry.get("ma_long")), 2)),
        "aiba_ma5_slope": "" if aiba_entry.get("ma_short_slope_pct") is None else float(round(float(aiba_entry.get("ma_short_slope_pct")), 8)),
        "aiba_ma20_slope": "" if aiba_entry.get("ma_mid_slope_pct") is None else float(round(float(aiba_entry.get("ma_mid_slope_pct")), 8)),
        "aiba_ma_long_slope": "" if aiba_entry.get("ma_long_slope_pct") is None else float(round(float(aiba_entry.get("ma_long_slope_pct")), 8)),
        "aiba_nine_rule_count": int(_safe_int(aiba_entry.get("nine_rule_count"), 0)),
        "aiba_nine_rule_alert": bool(aiba_entry.get("nine_rule_alert", False)),
        "aiba_try_fail": bool(aiba_entry.get("try_fail_flag", False)),
        "aiba_try_fail_count": int(_safe_int(aiba_entry.get("try_fail_count"), 0)),
        "htf15_bias": _safe_str(htf15.get("bias"), "") if htf15 else "",
        "htf15_trendline_slope_pct_per_step": "" if not htf15 or htf15.get("trendline_slope_pct_per_step") is None else float(round(float(htf15.get("trendline_slope_pct_per_step")), 8)),
        "htf15_channel_pos": "" if not htf15 or htf15.get("channel_pos") is None else float(round(float(htf15.get("channel_pos")), 8)),
        "htf15_channel_width_pct": "" if not htf15 or htf15.get("channel_width_pct") is None else float(round(float(htf15.get("channel_width_pct")), 8)),
        "htf60_bias": _safe_str(htf60.get("bias"), "") if htf60 else "",
        "htf60_trendline_slope_pct_per_step": "" if not htf60 or htf60.get("trendline_slope_pct_per_step") is None else float(round(float(htf60.get("trendline_slope_pct_per_step")), 8)),
        "htf60_channel_pos": "" if not htf60 or htf60.get("channel_pos") is None else float(round(float(htf60.get("channel_pos")), 8)),
        "htf60_channel_width_pct": "" if not htf60 or htf60.get("channel_width_pct") is None else float(round(float(htf60.get("channel_width_pct")), 8)),
        "hour": int(now.hour),

        # Fib/AIBA features at entry (for AI training log segmentation)
        "fib_zone": _safe_str(feats.get("fib_zone"), "") if feats else _safe_str(state.get("_fib_last", {}).get("zone"), ""),
        "fib_wave3_candidate": bool(feats.get("fib_wave3_candidate")) if feats else bool(state.get("_fib_last", {}).get("wave3_candidate", False)),
        "aiba_aligned": bool(feats.get("aiba_aligned")) if feats else False,

        # AI meta
        "ai_enabled": bool(cfg.ai_enabled),
        "ai_mode": str(cfg.ai_mode),
        "ai_score": (float(ai_score) if ai_score != "" else None),
        "ai_note": ai_note,

        # execution meta
        "exec_mode": "LIVE" if exec_live else "PAPER",
        "effective_stage": effective_stage,
        "order_id_entry": state.get("_pending_entry", {}).get("acceptance_id", ""),

        # extend memo
        "ai_score_extend": None,
        "ai_note_extend": None,
    }

    set_open_pos(state, open_pos_new)

    # (15m) PAPER log
    note = (
        f"tp={round(tp_price,1)} sl={round(sl_price,1)} win_used={int(cfg.win_min)}m "
        f"exp={expiry_time} tp_pct={tp_pct} sl_pct={cfg.sl_pct} timeout_mode={cfg.timeout_mode}"
    )
    if effective_stage == "CANARY" and float(cfg.canary_tp_scale) < 1.0:
        note = _append_note(note, f"canary_tp_scale={cfg.canary_tp_scale}")
    if htf15:
        note = _append_note(note, f"htf15_bias={_safe_str(htf15.get('bias'), 'NA')}")
    if htf60:
        note = _append_note(note, f"htf60_bias={_safe_str(htf60.get('bias'), 'NA')}")
    if not ai_note:
        note = _append_note(note, feature_note)
    if ai_note:
        note = (note + " " + ai_note).strip()
    note = _append_note(note, live_note_prefix)
    note = _append_note(note, entry_order_note)

    log_trade({
        "time": _now_str(now),
        "result": "PAPER",
        "side": side,
        "price": entry_price,
        "size": float(order_size),
        "ltp": ltp,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_pct": round(spread_pct * 100, 6) if spread_pct is not None else "",
        "limit_pct": round(cfg.spread_limit_pct * 100, 6),
        "ma_fast": "" if ma_fast is None else ma_fast,
        "ma_slow": "" if ma_slow is None else ma_slow,
        "trend": trend,
        "signal": signal,
        "note": note,
        "pos_id": pos_id,
    })

    # (15n) daily counter
    inc_trades_today(state, day_key)

# ------------------------------------------------------------
# compat shim: make_log_trade(csv_path)
# - 旧スニペット/検証コード互換用
# - state依存を持たない軽量 logger を返す
# ------------------------------------------------------------
def make_log_trade(csv_path: Path):
    """
    returns: log_trade(row: dict) -> None
    - LOG_FIELDS の順序で書く
    - header が無ければ作る
    - note に pos_id=... を埋め込む（embed_pos_id がある前提）
    """
    def _write_header_if_needed():
        if csv_path.exists() and csv_path.stat().st_size > 0:
            return
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
            w.writeheader()

    def log_trade(row: dict) -> None:
        _write_header_if_needed()
        r = dict(row or {})
        if not r.get("time"):
            r["time"] = now_str(datetime.now())

        pos_id = (r.get("pos_id") or "").strip()
        r["pos_id"] = pos_id

        try:
            r["note"] = embed_pos_id(r.get("note"), pos_id or None)
        except Exception:
            r["note"] = (r.get("note") or "")

        out = {k: r.get(k, "") for k in LOG_FIELDS}

        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
            w.writerow(out)
            f.flush()
            os.fsync(f.fileno())

    return log_trade

# ------------------------------------------------------------
# MINROW: when state has open_pos but today's log is empty,
# write one HOLD_OPEN_POS row to prevent audit WARN.
# ------------------------------------------------------------
def ensure_today_has_min_row_if_open_pos(now, state, csv_path, log_trade):
    """
    self-heal guard:
    - state に open_pos があるのに当日ログがヘッダのみ/0行の場合、最低1行を書いて audit を壊さない。
    - さらに、当日ログ内に open_pos.pos_id の PAPER が存在しない場合、state から "復元PAPER" を1回だけ書く。
      （NOTEに RECONSTRUCTED_FROM_STATE を付与して識別可能にする）
    """
    op = state.get("_open_pos")
    if not isinstance(op, dict) or not op.get("pos_id"):
        return

    # 当日ログが無い/ヘッダのみなら「0行」とみなす
    zero_rows = True
    if csv_path.exists() and csv_path.stat().st_size > 0:
        try:
            import csv
            with open(csv_path, newline="", encoding="utf-8") as f:
                r = csv.DictReader(f)
                for _ in r:
                    zero_rows = False
                    break
        except Exception:
            # 読めない場合はここでは触らない（別self-healへ委譲）
            return

    day_key = now.strftime("%Y-%m-%d")

    # 0行なら最低1行（HOLD）を書く（当日1回のみ）
    if zero_rows:
        if state.get("_minrow_written_day") != day_key:
            state["_minrow_written_day"] = day_key
            try:
                save_state(state)
            except Exception:
                pass

            note = "MINROW_OPEN_POS_PRESENT"
            log_trade({
                "time": _now_str(now),
                "result": "HOLD_OPEN_POS",
                "side": op.get("side", ""),
                "price": op.get("entry_price", ""),
                "size": op.get("size", ""),
                "ltp": state.get("_last_ltp", ""),
                "best_bid": "",
                "best_ask": "",
                "spread_pct": op.get("spread_entry_pct", ""),
                "limit_pct": "",
                "ma_fast": op.get("ma_fast", ""),
                "ma_slow": op.get("ma_slow", ""),
                "trend": op.get("trend", "UNKNOWN"),
                "signal": op.get("signal", "NONE"),
                "note": note,
                "pos_id": op.get("pos_id", ""),
            })

    # open_pos の pos_id に対応する PAPER が当日ログに無いなら、stateから復元PAPERを1回だけ書く
    # ※ audit の WARN(STATE_OPEN_POS_NO_PAPER_LOG) を確実に消すための self-heal
    try:
        import csv
        pos_id = str(op.get("pos_id", "")).strip()
        if not pos_id:
            return

        found_paper = False
        if csv_path.exists() and csv_path.stat().st_size > 0:
            with open(csv_path, newline="", encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    if (row.get("result") or "").strip() == "PAPER" and (row.get("pos_id") or "").strip() == pos_id:
                        found_paper = True
                        break

        if (not found_paper) and (state.get("_recon_paper_written_day") != day_key):
            state["_recon_paper_written_day"] = day_key
            try:
                save_state(state)
            except Exception:
                pass

            note = f"RECONSTRUCTED_FROM_STATE entry_time={op.get('entry_time_jst','')}"
            log_trade({
                "time": _now_str(now),
                "result": "PAPER",
                "side": op.get("side", ""),
                "price": op.get("entry_price", ""),
                "size": op.get("size", ""),
                "ltp": state.get("_last_ltp", ""),
                "best_bid": "",
                "best_ask": "",
                "spread_pct": op.get("spread_entry_pct", ""),
                "limit_pct": "",
                "ma_fast": op.get("ma_fast", ""),
                "ma_slow": op.get("ma_slow", ""),
                "trend": op.get("trend", "UNKNOWN"),
                "signal": op.get("signal", "NONE"),
                "note": note,
                "pos_id": pos_id,
            })
    except Exception:
        return

if __name__ == "__main__":
    main()
