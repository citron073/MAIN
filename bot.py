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
import subprocess
import time
import atexit
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import urlopen

from exchange.bitflyer_private import BitflyerPrivateClient, summarize_order
from tools.keychain_secret import read_pair

# -------------------------
# Paths (MAIN)
# -------------------------
MAIN_DIR = Path(__file__).resolve().parent
STATE_FILE = MAIN_DIR / "state.json"
CONTROL_CSV_FILE = MAIN_DIR / "CONTROL.csv"
AI_MODEL_JSON_FILE = MAIN_DIR / "ai_model.json"
NEWS_BLOCK_FILE = MAIN_DIR / "news_block.csv"
RUN_LOCK_DIR = MAIN_DIR / ".run_lock"

# logs are in ../logs (contract)
LOGS_DIR = MAIN_DIR.parent / "logs"

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
# Log contract (MUST MATCH SPEC order)
# -------------------------
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
    "note",
    "pos_id",
]
# -------------------------
# Result allowed (contract)
# -------------------------
RESULT_ALLOWED = {
    "PAPER",
    "HOLD_OPEN_POS",
    "OBSERVE_NO_SIGNAL",
    "OBSERVE_OK",
    "OBSERVE_TIME_BLOCK",
    "OBSERVE_SELL_FAST_MA_NEAR",
    "OBSERVE_TRADE_DISABLED",
    "OBSERVE_AI_BLOCK",
    "SKIP_OUT_OF_TIME",
    "SKIP_TODAY_OFF",
    "SKIP_NEWS",
    "SKIP_SPREAD",
    "SKIP_DAILY_LIMIT",
    "SKIP_TICKER_INCOMPLETE",
    "PAPER_EXIT_TP",
    "PAPER_EXIT_SL",
    "PAPER_EXIT_TIMEOUT",
    "PAPER_EXIT_PARTIAL_TP",
    "PAPER_EXIT_EOD",
    "ERROR_OPEN_POS_BROKEN",
}

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

SELL_FAST_MA_DISTANCE_PCT_DEFAULT = 0.10  # % (distance from fast MA; if too near -> observe)

ONE_POSITION_ONLY_DEFAULT = True

TIMEOUT_MODE_DEFAULT = "IGNORE"   # IGNORE / EXTEND / PARTIAL
MAX_EXTEND_COUNT_DEFAULT = 1
EXTEND_MIN_DEFAULT = 30
EXTEND_MIN_BESTFAV_PCT_DEFAULT = 0.08
PARTIAL_TP_TRIGGER_PCT_DEFAULT = 0.10

OBSERVE_ONLY_DEFAULT = False

SAFETY_HARD_BLOCK_DEFAULT = True

LIVE_ENABLED_DEFAULT = False
ROLLOUT_MODE_DEFAULT = "AUTO"
STAGE_PAPER_DAYS_DEFAULT = 3
STAGE_CANARY_DAYS_DEFAULT = 3
CANARY_LOT_DEFAULT = 0.001
DAILY_LOSS_LIMIT_PCT_DEFAULT = -1.0
LIMIT_ORDER_TIMEOUT_SEC_DEFAULT = 30
LIMIT_PRICE_OFFSET_TICKS_DEFAULT = 0
PRODUCT_CODE_DEFAULT = PRODUCT
MARKET_TYPE_DEFAULT = "SPOT"
KEYCHAIN_SERVICE_DEFAULT = "ouroboros.bitflyer"
KEYCHAIN_ACCOUNT_KEY_DEFAULT = "api_key"
KEYCHAIN_ACCOUNT_SECRET_DEFAULT = "api_secret"
TICK_SIZE_DEFAULT = 1.0
PARTIAL_REMAIN_EPS = 1e-8

AI_TRAIN_LOG_FILE = LOGS_DIR / "ai_training_log.csv"
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
    "extend_count",
    "exec_mode",
    "stage",
]
AI_TRAIN_EXIT_RESULTS = {
    "PAPER_EXIT_TP",
    "PAPER_EXIT_SL",
    "PAPER_EXIT_TIMEOUT",
    "PAPER_EXIT_EOD",
}
AI_SCORE_IN_NOTE_RE = re.compile(r"\bAI(?:_EXT)?\s*score=([0-9]*\.?[0-9]+)\b", re.IGNORECASE)
TRADE_LOG_NAME_RE = re.compile(r"^trade_log_(\d{8})\.csv$")
AI_AUTOTUNE_THRESHOLD_GRID = [round(x, 2) for x in (0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85)]
AI_AUTOTUNE_LOOKBACK_DAYS_DEFAULT = 45
AI_AUTOTUNE_MIN_IMPROVE = 0.005
_AI_TRAIN_HEADER_READY = False

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
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
        "use_recent_winrate": False,
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

    # strategy
    tp_buy_pct: float = TP_BUY_PCT_DEFAULT
    tp_sell_pct: float = TP_SELL_PCT_DEFAULT
    sl_pct: float = SL_PCT_DEFAULT
    win_min: int = WIN_MIN_DEFAULT

    # filters
    spread_limit_pct: float = SPREAD_LIMIT_PCT_DEFAULT
    max_trades_per_day: int = MAX_TRADES_PER_DAY_DEFAULT
    no_paper_hours: List[int] = None
    sell_fast_ma_distance_pct: float = SELL_FAST_MA_DISTANCE_PCT_DEFAULT
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

    # live execution
    rollout_mode: str = ROLLOUT_MODE_DEFAULT
    stage_paper_days: int = STAGE_PAPER_DAYS_DEFAULT
    stage_canary_days: int = STAGE_CANARY_DAYS_DEFAULT
    daily_loss_limit_pct: float = DAILY_LOSS_LIMIT_PCT_DEFAULT
    limit_order_timeout_sec: int = LIMIT_ORDER_TIMEOUT_SEC_DEFAULT
    limit_price_offset_ticks: int = LIMIT_PRICE_OFFSET_TICKS_DEFAULT
    product_code: str = PRODUCT_CODE_DEFAULT
    market_type: str = MARKET_TYPE_DEFAULT
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
    if not s:
        return default
    s = s.replace("[", "").replace("]", "")
    hours: List[int] = []
    for p in [x.strip() for x in s.split(",") if x.strip()]:
        try:
            hours.append(int(p))
        except Exception:
            pass
    return hours if hours else default


def build_runtime_config(control: Dict[str, str], ai_model: Dict[str, Any]) -> Cfg:
    cfg = Cfg()

    # core (CONTROL)
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

    cfg.sell_fast_ma_distance_pct = _safe_float(control.get("sell_fast_ma_distance_pct"), SELL_FAST_MA_DISTANCE_PCT_DEFAULT)
    cfg.one_position_only = _safe_bool(control.get("one_position_only"), ONE_POSITION_ONLY_DEFAULT)

    cfg.fast_n = _safe_int(control.get("fast_n"), FAST_N_DEFAULT)
    cfg.slow_n = _safe_int(control.get("slow_n"), SLOW_N_DEFAULT)
    cfg.max_ltp_history = _safe_int(control.get("max_ltp_history"), MAX_LTP_HISTORY_DEFAULT)

    cfg.lot = _safe_float(control.get("lot"), LOT_DEFAULT)
    cfg.canary_lot = _safe_float(control.get("canary_lot"), CANARY_LOT_DEFAULT)
    cfg.safety_hard_block = _safe_bool(control.get("safety_hard_block"), SAFETY_HARD_BLOCK_DEFAULT)

    # timeout controls
    tm = (control.get("timeout_mode") or TIMEOUT_MODE_DEFAULT).strip().upper()
    cfg.timeout_mode = tm if tm in ("IGNORE", "EXTEND", "PARTIAL") else TIMEOUT_MODE_DEFAULT
    cfg.max_extend_count = _safe_int(control.get("max_extend_count"), MAX_EXTEND_COUNT_DEFAULT)
    cfg.extend_min = _safe_int(control.get("extend_min"), EXTEND_MIN_DEFAULT)
    cfg.extend_min_bestfav_pct = _safe_float(control.get("extend_min_bestfav_pct"), EXTEND_MIN_BESTFAV_PCT_DEFAULT)
    cfg.partial_tp_trigger_pct = _safe_float(control.get("partial_tp_trigger_pct"), PARTIAL_TP_TRIGGER_PCT_DEFAULT)

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

    # emergency overrides in CONTROL (optional, for ops)
    if "ai_enabled" in control:
        cfg.ai_enabled = _safe_bool(control.get("ai_enabled"), cfg.ai_enabled)
    if "ai_mode" in control:
        cfg.ai_mode = normalize_ai_mode(control.get("ai_mode"))

    # live execution controls
    cfg.rollout_mode = _safe_str(control.get("rollout_mode"), ROLLOUT_MODE_DEFAULT).upper()
    cfg.stage_paper_days = max(0, _safe_int(control.get("stage_paper_days"), STAGE_PAPER_DAYS_DEFAULT))
    cfg.stage_canary_days = max(0, _safe_int(control.get("stage_canary_days"), STAGE_CANARY_DAYS_DEFAULT))
    cfg.daily_loss_limit_pct = _safe_float(control.get("daily_loss_limit_pct"), DAILY_LOSS_LIMIT_PCT_DEFAULT)
    cfg.limit_order_timeout_sec = max(5, _safe_int(control.get("limit_order_timeout_sec"), LIMIT_ORDER_TIMEOUT_SEC_DEFAULT))
    cfg.limit_price_offset_ticks = max(0, _safe_int(control.get("limit_price_offset_ticks"), LIMIT_PRICE_OFFSET_TICKS_DEFAULT))
    cfg.product_code = _safe_str(control.get("product_code"), PRODUCT_CODE_DEFAULT)
    cfg.market_type = _safe_str(control.get("market_type"), MARKET_TYPE_DEFAULT).upper()
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
            "extend_count": op.get("extend_count", "") if same_pos else "",
            "exec_mode": exec_mode,
            "stage": stage,
        }
    )

    _ensure_ai_training_log_ready(AI_TRAIN_LOG_FILE)
    with open(AI_TRAIN_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=AI_TRAIN_FIELDS, extrasaction="ignore")
        w.writerow(out_row)
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


def log_trade_factory(csv_path: Path, state: Dict[str, Any]):
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

        # embed pos_id into note
        r["note"] = embed_pos_id(r.get("note"), pos_id if pos_id else None)

        # fill missing fields as empty (do not break csv)
        for k in LOG_FIELDS:
            if k not in r:
                r[k] = ""

        _write_row(csv_path, r)
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


def calc_trendline_slope_pct_per_step(state: Dict[str, Any], n: int) -> Optional[float]:
    hist = state.get("ltp_history", [])
    if not isinstance(hist, list) or len(hist) < max(n, 5):
        return None
    try:
        tail = [float(x) for x in hist[-n:]]
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


def calc_channel_position(state: Dict[str, Any], n: int) -> Optional[float]:
    hist = state.get("ltp_history", [])
    if not isinstance(hist, list) or len(hist) < max(n, 5):
        return None
    try:
        tail = [float(x) for x in hist[-n:]]
    except Exception:
        return None
    hi = max(tail)
    lo = min(tail)
    width = hi - lo
    if width <= 0:
        return None
    pos = (tail[-1] - lo) / width
    return _clamp(pos, 0.0, 1.0)


def calc_channel_width_pct(state: Dict[str, Any], n: int) -> Optional[float]:
    hist = state.get("ltp_history", [])
    if not isinstance(hist, list) or len(hist) < max(n, 5):
        return None
    try:
        tail = [float(x) for x in hist[-n:]]
    except Exception:
        return None
    hi = max(tail)
    lo = min(tail)
    mid = (hi + lo) / 2.0
    if mid == 0:
        return None
    return ((hi - lo) / mid) * 100.0


def ma_distance_pct(price: float, ma: Optional[float]) -> Optional[float]:
    if ma is None:
        return None
    if float(ma) == 0:
        return None
    return abs(float(price) - float(ma)) / float(ma) * 100.0


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


def _opposite_side(side: str) -> str:
    return "SELL" if (side or "").upper() == "BUY" else "BUY"


def _load_live_client(cfg: Cfg) -> BitflyerPrivateClient:
    api_key, api_secret = read_pair(
        service=cfg.keychain_service,
        account_key=cfg.keychain_account_key,
        account_secret=cfg.keychain_account_secret,
    )
    return BitflyerPrivateClient(api_key=api_key, api_secret=api_secret, base_url=BASE_URL)


def run_live_limit_cycle(
    client: BitflyerPrivateClient,
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
    client: Optional[BitflyerPrivateClient],
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
            start = float(client.get_jpy_balance())
            state["_risk_day"] = day
            state["_risk_day_start_jpy"] = start
            state["_risk_realized_jpy"] = 0.0
            state["_risk_realized_pct"] = 0.0
            state["_risk_stop"] = False
            state.pop("_risk_last_error", None)
            save_state(state)
            return False, "risk_reset"

        start = float(state.get("_risk_day_start_jpy", 0.0) or 0.0)
        cur = float(client.get_jpy_balance())
        pnl = cur - start
        pct = (pnl / start * 100.0) if start > 0 else 0.0
        stop = pct <= float(cfg.daily_loss_limit_pct)
        state["_risk_realized_jpy"] = float(round(pnl, 6))
        state["_risk_realized_pct"] = float(round(pct, 6))
        state["_risk_stop"] = bool(stop)
        state.pop("_risk_last_error", None)
        save_state(state)
        note = f"risk_pnl_pct={pct:.6f} limit={cfg.daily_loss_limit_pct:.6f}"
        return bool(stop), note
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

        # time: small caution at edges
        if cfg.ai_use_time:
            hr = int(feats.get("hour", 0))
            if hr in (cfg.start_hour, cfg.end_hour - 1):
                comps["hour"] = -0.15
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
def _iter_recent_trade_log_paths(now: datetime, lookback_days: int) -> List[Path]:
    out: List[Path] = []
    cutoff_date = (now - timedelta(days=max(1, lookback_days) + 2)).date()
    for p in sorted(LOGS_DIR.glob("trade_log_*.csv")):
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


def _collect_ai_samples_from_training_log(now: datetime, lookback_days: int) -> List[Dict[str, Any]]:
    if not AI_TRAIN_LOG_FILE.exists():
        return []
    cutoff = now - timedelta(days=max(1, lookback_days))
    out: List[Dict[str, Any]] = []
    try:
        with open(AI_TRAIN_LOG_FILE, newline="", encoding="utf-8") as f:
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
                    }
                )
    except Exception:
        return []
    return out


def _collect_ai_samples_from_trade_logs(now: datetime, lookback_days: int) -> List[Dict[str, Any]]:
    cutoff = now - timedelta(days=max(1, lookback_days))
    entries: Dict[str, Dict[str, Any]] = {}
    exits: Dict[str, Dict[str, Any]] = {}

    for p in _iter_recent_trade_log_paths(now, lookback_days):
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
            }
        )
    return out


def _eval_loss_small_profit_large(samples: List[Dict[str, Any]], threshold: float) -> Dict[str, Any]:
    picked = [r for r in samples if _to_float_or_none(r.get("ai_score")) is not None and float(r["ai_score"]) >= threshold]
    rets = [float(r["ret_pct"]) for r in picked if _to_float_or_none(r.get("ret_pct")) is not None]

    if not rets:
        return {
            "n": 0,
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

    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss_abs = abs(sum(losses) / len(losses)) if losses else 0.0
    rr = (avg_win / avg_loss_abs) if avg_loss_abs > 0 else (5.0 if wins else 0.0)
    sum_win = sum(wins)
    sum_loss_abs = abs(sum(losses))
    pf = (sum_win / sum_loss_abs) if sum_loss_abs > 0 else (8.0 if sum_win > 0 else 0.0)
    expectancy = sum(rets) / len(rets)
    loss_rate_pct = (len(losses) / len(rets)) * 100.0

    rr_c = _clamp(rr, 0.0, 5.0)
    pf_c = _clamp(pf, 0.0, 8.0)
    metric = expectancy + 0.08 * (rr_c - 1.0) + 0.04 * (pf_c - 1.0) - 0.002 * loss_rate_pct

    return {
        "n": len(rets),
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


def maybe_run_daily_ai_autotune(
    *,
    state: Dict[str, Any],
    control_raw: Dict[str, str],
    ai_model: Dict[str, Any],
    now: datetime,
) -> Dict[str, Any]:
    if not _safe_bool(control_raw.get("ai_auto_train_enabled"), True):
        return ai_model

    today = now.strftime("%Y-%m-%d")
    if _safe_str(state.get("_ai_auto_train_day"), "") == today:
        return ai_model

    lookback_days = max(7, _safe_int(control_raw.get("ai_auto_lookback_days"), AI_AUTOTUNE_LOOKBACK_DAYS_DEFAULT))
    min_samples = max(20, _safe_int(control_raw.get("tune_min_samples"), 20))
    min_winloss_each = max(1, _safe_int(control_raw.get("tune_min_samples_band"), 5))

    source = "ai_training_log"
    samples = _collect_ai_samples_from_training_log(now, lookback_days)
    if len(samples) < min_samples:
        source = "trade_logs"
        samples = _collect_ai_samples_from_trade_logs(now, lookback_days)

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

    base = _eval_loss_small_profit_large(samples, current_th)
    best = {"th": current_th, **base}

    thresholds = sorted(set(AI_AUTOTUNE_THRESHOLD_GRID + [round(current_th, 2)]))
    for th in thresholds:
        ev = _eval_loss_small_profit_large(samples, th)
        if ev["n"] < min_samples:
            continue
        if ev["wins"] < min_winloss_each or ev["losses"] < min_winloss_each:
            continue
        if ev["metric"] > best["metric"]:
            best = {"th": th, **ev}

    applied = False
    improve = float(best["metric"]) - float(base["metric"])
    if (
        best["th"] != current_th
        and best["n"] >= min_samples
        and best["wins"] >= min_winloss_each
        and best["losses"] >= min_winloss_each
        and improve >= AI_AUTOTUNE_MIN_IMPROVE
    ):
        conf_dst = ai_model.get("confidence_threshold")
        if not isinstance(conf_dst, dict):
            conf_dst = {}
            ai_model["confidence_threshold"] = conf_dst
        conf_dst["entry"] = float(best["th"])
        g = ai_model.get("global")
        if not isinstance(g, dict):
            g = {}
            ai_model["global"] = g
        g["threshold"] = float(best["th"])
        applied = True

    model_info = ai_model.get("model_info")
    if not isinstance(model_info, dict):
        model_info = {}
        ai_model["model_info"] = model_info
    model_info["last_updated"] = today if applied else _safe_str(model_info.get("last_updated"), today)
    model_info["auto_updated_by"] = "bot.daily_ai_autotune"
    model_info["objective"] = "loss_small_profit_large"
    model_info["auto_train_last_day"] = today
    model_info["auto_train_source"] = source
    model_info["auto_train_rows"] = len(samples)
    model_info["auto_train_base_th"] = round(current_th, 4)
    model_info["auto_train_best_th"] = round(float(best["th"]), 4)
    model_info["auto_train_base_metric"] = round(float(base["metric"]), 6)
    model_info["auto_train_best_metric"] = round(float(best["metric"]), 6)
    model_info["auto_train_improve"] = round(float(improve), 6)
    model_info["auto_train_applied"] = bool(applied)

    if applied:
        write_ai_model_json(AI_MODEL_JSON_FILE, ai_model)

    state["_ai_auto_train_day"] = today
    state["_ai_auto_train"] = {
        "ran_at_jst": _now_str(now),
        "source": source,
        "rows": len(samples),
        "min_samples": min_samples,
        "min_winloss_each": min_winloss_each,
        "current_th": round(current_th, 6),
        "best_th": round(float(best["th"]), 6),
        "current_metric": round(float(base["metric"]), 6),
        "best_metric": round(float(best["metric"]), 6),
        "improve": round(float(improve), 6),
        "applied": applied,
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
    live_client: Optional[BitflyerPrivateClient] = None
    live_note_prefix = f"exec={'LIVE' if exec_live else 'PAPER'} stage={effective_stage}"
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
    log_trade = log_trade_factory(csv_path, state)
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
    save_state(state)

    # (13) NEWS block (entry prohibited)
    news_blocks = load_news_blocks(NEWS_BLOCK_FILE)
    blocked, label = is_news_block_time(now, news_blocks)
    if blocked:
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
            "note": f"NEWS {label}".strip(),
            "pos_id": "",
        })
        return

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
                eod_px = compute_limit_price(eod_exit_side, best_bid, best_ask, cfg.limit_price_offset_ticks)
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

        best_fav_now = calc_best_fav_pct(side0, entry_price, float(ltp))
        prev_best_fav = open_pos.get("best_fav", 0.0)
        try:
            prev_best_fav_f = float(prev_best_fav)
        except Exception:
            prev_best_fav_f = 0.0
        if best_fav_now is not None:
            open_pos["best_fav"] = round(max(prev_best_fav_f, float(best_fav_now)), 6)

        outcome: Optional[str] = None

        # TP/SL
        if side0 == "BUY":
            if float(ltp) >= tp_price:
                outcome = "PAPER_EXIT_TP"
            elif float(ltp) <= sl_price:
                outcome = "PAPER_EXIT_SL"
        else:
            if float(ltp) <= tp_price:
                outcome = "PAPER_EXIT_TP"
            elif float(ltp) >= sl_price:
                outcome = "PAPER_EXIT_SL"

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
            note = f"entry={open_pos.get('entry_time_jst')} exp={open_pos.get('expiry_time_jst')} best_fav={open_pos.get('best_fav')} extend_count={open_pos.get('extend_count',0)}"
            note = _append_note(note, f"exec={open_pos.get('exec_mode', 'PAPER')} stage={open_pos.get('effective_stage', effective_stage)}")

            op_exec = _safe_str(open_pos.get("exec_mode"), "PAPER").upper()
            if op_exec == "LIVE":
                exit_side = _opposite_side(side0)
                size_now = _safe_float(open_pos.get("size"), cfg.lot)
                px = compute_limit_price(exit_side, best_bid, best_ask, cfg.limit_price_offset_ticks)
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
            "note": _append_note("safety_hard_block=1", live_note_prefix),
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
            "note": _append_note(_append_note("risk_stop=1", risk_note), live_note_prefix),
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
            "note": _append_note("trade_enabled=0", live_note_prefix),
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
            "note": "spread_block",
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
            "note": "",
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
            "note": "no_paper_hour",
            "pos_id": "",
        })
        return

    # (15g) SELL fast MA near filter => observe
    if signal == "SELL_CANDIDATE":
        dist = ma_distance_pct(float(ltp), ma_fast)
        if dist is None or dist < cfg.sell_fast_ma_distance_pct:
            log_trade({
                "time": _now_str(now),
                "result": "OBSERVE_SELL_FAST_MA_NEAR",
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
                "note": f"fast_ma_dist={'' if dist is None else round(dist,6)}",
                "pos_id": "",
            })
            return

    # (15h) observe_only => OBSERVE_OK
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
            "note": "observe_only=1",
            "pos_id": "",
        })
        return

    # (15i) AI entry decision (block => OBSERVE_OK + note "AI_BLOCK ...")
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

    # (15j) pos_id issuance + open_pos save
    order_size = effective_lot(cfg, effective_stage) if exec_live else float(cfg.lot)
    entry_price = float(best_bid) if side == "BUY" else float(best_ask)
    entry_order_note = ""
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

    tp_pct = cfg.tp_buy_pct if side == "BUY" else cfg.tp_sell_pct
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
        "hour": int(now.hour),

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

    # (15k) PAPER log
    note = (
        f"tp={round(tp_price,1)} sl={round(sl_price,1)} win_used={int(cfg.win_min)}m "
        f"exp={expiry_time} tp_pct={tp_pct} sl_pct={cfg.sl_pct} timeout_mode={cfg.timeout_mode}"
    )
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

    # (15l) daily counter
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
