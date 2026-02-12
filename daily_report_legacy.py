# MAIN/daily_report.py
# ============================================================
# 完全網羅版（trade_logだけで監査＆集計＋pos_id MAE/MFE再計算＋outcome(v2)統合）
#
# 追加（完全版）:
#  - Dashboard CONTROL.csv で ON/OFF 切替（フィルタ/相関/MAE_MFE出力/WARN dump/AI等）
#  - 日跨ぎ完全突合（前日ENTRY→当日EXITを自動補完、または逆も補完）
#  - crossday / pos_id WARN_DUMP（①c警告時のダンプ）
#  - LOOSE pos_id 分布要約（pos_idがnoteに無い/崩れている場合の検知）
#  - MAE/MFE × outcome × hour 相関の言語化
#  - AIスコア（ローカル特徴量→スコア）を pos_id単位で算出・集計（ON/OFF）
#  - 監査JSON出力（Dashboard Positions用）
#
# 使い方:
#   python3 daily_report.py 20260210 --out-dir ./daily_report_out
#   python3 daily_report.py 20260201-20260210 --out-dir ./daily_report_out
#   python3 daily_report.py /path/to/trade_log_20260210.csv
#
# 標準ライブラリのみ
# ============================================================

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from collections import Counter, defaultdict, deque
from typing import Dict, Any, List, Optional, Tuple


# =====================
# デフォルト設定（CONTROLで上書き可）
# =====================
# 時間フィルタ
FILTER_ENABLED_DEFAULT = True
FILTER_START_HOUR_DEFAULT = 10
FILTER_END_HOUR_DEFAULT = 16

# 履歴表示
SHOW_HISTORY_DEFAULT = True
HISTORY_MAX_DAYS_DEFAULT = 30

# crossday（突合補完）
CROSSDAY_BACK_DEFAULT = 1
CROSSDAY_FORWARD_DEFAULT = 1

# SMA補完（表示/相関の一貫性用）
FAST_N_DEFAULT = 5
SLOW_N_DEFAULT = 20
LTP_BUFFER_MAX_DEFAULT = 2000

# MAE/MFE
WRITE_MAE_MFE_FILES_DEFAULT = True
SHOW_MAE_MFE_TOP_N_DEFAULT = 10
SHOW_MAE_MFE_WORST_N_DEFAULT = 10

# WARN dump
WARN_DUMP_ENABLED_DEFAULT = True
WARN_DUMP_SHOW_PREV_DAY_DEFAULT = True
WARN_DUMP_POSID_ENABLED_DEFAULT = True
WARN_DUMP_POSID_INCLUDE_LTP_DEFAULT = False

# LOOSE pos
LOOSE_POS_ENABLED_DEFAULT = True

# 相関
CORR_ENABLED_DEFAULT = True
CORR_MIN_N_DEFAULT = 3
CORR_SHOW_TOP_DEFAULT = 5

# AI（ローカル推論）
AI_ENABLED_DEFAULT = False
AI_DEBUG_DEFAULT = False
AI_FEATURES_DEFAULT = "spread,ma_gap,ma_slope,volatility,timeout_mode"

# 結果ラベル
RESULT_OBSERVE_PREFIX = "OBSERVE"
RESULT_SKIP_SPREAD = "SKIP_SPREAD"
RESULT_SKIP_NEWS = "SKIP_NEWS"
RESULT_PAPER = "PAPER"
RESULT_PAPER_EXIT_PREFIX = "PAPER_EXIT"

OUTCOME_KEYS = ["TP", "SL", "TIMEOUT", "NO_DATA", "PARTIAL_TP", "UNKNOWN", "EOD"]


# =====================
# ユーティリティ
# =====================
def eprint(*a):
    print(*a, file=sys.stderr)


def read_control_csv(path: Path) -> Dict[str, str]:
    """
    CONTROL.csv（key,value）を読む
    - bot側と同じ形式を想定
    - 無ければ {}
    """
    if not path.exists():
        return {}
    try:
        out = {}
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


def safe_bool(v, default: bool) -> bool:
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def safe_int(v, default: int) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return default


def safe_float(v, default: float) -> float:
    try:
        return float(str(v).strip())
    except Exception:
        return default


def safe_str(v, default: str = "") -> str:
    try:
        s = str(v).strip()
        return s if s != "" else default
    except Exception:
        return default


def parse_csv_words(v: str, default: str) -> List[str]:
    s = safe_str(v, default)
    s = s.replace("[", "").replace("]", "")
    parts = [p.strip() for p in s.split(",") if p.strip() != ""]
    return parts


def get_main_dir() -> Path:
    return Path(__file__).resolve().parent


def get_logs_dir():
    here = get_main_dir()
    for p in [
        here.parent / "logs",
        here / "logs",
        Path("../logs").resolve(),
        Path("./logs").resolve(),
    ]:
        if p.exists() and any(p.glob("trade_log_*.csv")):
            return p
    return here.parent / "logs"


def read_rows(p: Path) -> List[Dict[str, str]]:
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(p: Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def to_float(x):
    try:
        return float(x)
    except Exception:
        return None


def parse_time(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def hour_from_time(s: str) -> Optional[int]:
    try:
        return int(s[11:13])
    except Exception:
        return None


def in_filter(h: int, start_h: int, end_h: int) -> bool:
    return start_h <= h < end_h


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def sigmoid(x: float) -> float:
    if x >= 60:
        return 1.0
    if x <= -60:
        return 0.0
    import math
    return 1.0 / (1.0 + math.exp(-x))


# =====================
# token / range / day list
# =====================
def parse_token(token: str) -> Tuple[Optional[str], Optional[str]]:
    """
    token:
      - YYYYMMDD
      - YYYYMMDD-YYYYMMDD
    """
    t = safe_str(token, "")
    if re.fullmatch(r"\d{8}", t):
        return t, t
    m = re.fullmatch(r"(\d{8})-(\d{8})", t)
    if m:
        a, b = m.group(1), m.group(2)
        return (a, b) if a <= b else (b, a)
    return None, None


def list_log_days(logs_dir: Path) -> List[str]:
    out = []
    for p in logs_dir.glob("trade_log_*.csv"):
        m = re.search(r"trade_log_(\d{8})\.csv", p.name)
        if m:
            out.append(m.group(1))
    return sorted(set(out))


def pick_days_in_range(all_days: List[str], start8: str, end8: str) -> List[str]:
    return [d for d in all_days if start8 <= d <= end8]


def compute_report_key(target_days: List[str]) -> str:
    ds = sorted(set([d for d in target_days if re.fullmatch(r"\d{8}", d)]))
    if not ds:
        return "daily_report_unknown"
    if len(ds) == 1:
        return f"daily_report_{ds[0]}"
    return f"daily_report_{ds[0]}_{ds[-1]}"


# =====================
# SMA 補完（表示用）
# =====================
def backfill_ma(rows: List[Dict[str, str]], fast_n: int, slow_n: int, buf_max: int) -> List[Dict[str, str]]:
    buf = deque(maxlen=buf_max)
    out = []
    for r0 in rows:
        r = dict(r0)
        ltp = to_float(r.get("ltp"))
        if ltp is None:
            out.append(r)
            continue

        buf.append(ltp)

        # すでに入っているなら尊重
        if r.get("ma_fast") and r.get("ma_slow"):
            out.append(r)
            continue

        if len(buf) < slow_n:
            r["trend"] = r.get("trend") or "UNKNOWN"
            r["signal"] = r.get("signal") or "NONE"
            out.append(r)
            continue

        fast = sum(list(buf)[-fast_n:]) / fast_n
        slow = sum(list(buf)[-slow_n:]) / slow_n
        r["ma_fast"] = f"{fast:.2f}"
        r["ma_slow"] = f"{slow:.2f}"

        if fast > slow:
            r["trend"] = "UP"
            r["signal"] = "BUY_CANDIDATE"
        elif fast < slow:
            r["trend"] = "DOWN"
            r["signal"] = "SELL_CANDIDATE"
        else:
            r["trend"] = "FLAT"
            r["signal"] = "NONE"

        out.append(r)
    return out


# =====================
# pos_id 抽出（strict / loose）
# =====================
_STRICT_PID_RE = re.compile(r"\bpos_id=([0-9]{8}-[0-9]{6}-[A-Z]+-\d{3})\b")
_LOOSE_PID_RE = re.compile(r"(pos[_\s-]*id|pid)\s*[:=]\s*([A-Za-z0-9._-]{4,64})", re.I)


def extract_pos_id_strict(note: str) -> Optional[str]:
    if not note:
        return None
    m = _STRICT_PID_RE.search(note)
    return m.group(1) if m else None


def extract_pos_id_any(note: str) -> Optional[str]:
    if not note:
        return None
    s = extract_pos_id_strict(note)
    if s:
        return s
    m = _LOOSE_PID_RE.search(note)
    return m.group(2) if m else None


def is_strict_pid(pid: str) -> bool:
    if not pid:
        return False
    return bool(_STRICT_PID_RE.search("pos_id=" + pid))


# =====================
# outcome(v2) 推定
# =====================
def outcome_from_result(result: str) -> str:
    r = (result or "").strip()
    if r == "PAPER_EXIT_TP":
        return "TP"
    if r == "PAPER_EXIT_SL":
        return "SL"
    if r == "PAPER_EXIT_TIMEOUT":
        return "TIMEOUT"
    if r == "PAPER_EXIT_PARTIAL_TP":
        return "PARTIAL_TP"
    if r == "PAPER_EXIT_EOD":
        return "EOD"
    if r.startswith("PAPER_EXIT"):
        return "UNKNOWN"
    return "NO_DATA"


# =====================
# 日跨ぎ突合（前後ファイルを集める）
# =====================
def collect_files_for_days(logs_dir: Path, days: List[str]) -> List[Path]:
    out = []
    seen = set()
    for d in days:
        p = logs_dir / f"trade_log_{d}.csv"
        if p.exists():
            s = str(p.resolve())
            if s not in seen:
                out.append(p)
                seen.add(s)
    return out


def expand_days_with_cross(all_days: List[str], target_days: List[str], back: int, forward: int) -> List[str]:
    if not target_days:
        return []
    idx = {d: i for i, d in enumerate(all_days)}
    ds = sorted(set(target_days))
    i0 = idx.get(ds[0], 0)
    i1 = idx.get(ds[-1], len(all_days) - 1)
    j0 = max(0, i0 - max(0, back))
    j1 = min(len(all_days) - 1, i1 + max(0, forward))
    return all_days[j0:j1 + 1]


def load_rows_crossday(files: List[Path]) -> List[Dict[str, str]]:
    rows = []
    for p in files:
        try:
            rs = read_rows(p)
            day_m = re.search(r"trade_log_(\d{8})\.csv", p.name)
            d8 = day_m.group(1) if day_m else ""
            for r in rs:
                r["_day8"] = d8
            rows.extend(rs)
        except Exception as e:
            eprint(f"[WARN] read failed: {p} err={e}")

    def key(r):
        t = parse_time(r.get("time", ""))
        return t or datetime.min

    rows.sort(key=key)
    return rows


# =====================
# MAE / MFE（pos_id区間のltpで再計算）
# =====================
def compute_mae_mfe(rows_pid_sorted: List[Dict[str, str]], entry: Dict[str, str], exit_: Dict[str, str]) -> Optional[Tuple[float, float, int]]:
    side = (entry.get("side") or "").strip().upper()
    entry_price = to_float(entry.get("price"))
    if not entry_price:
        return None

    t0 = parse_time(entry.get("time", ""))
    t1 = parse_time(exit_.get("time", ""))
    if not t0 or not t1 or t1 < t0:
        return None

    ltps = []
    for r in rows_pid_sorted:
        t = parse_time(r.get("time", ""))
        if t and t0 <= t <= t1:
            l = to_float(r.get("ltp"))
            if l is not None:
                ltps.append(l)

    if not ltps:
        return None

    hi, lo = max(ltps), min(ltps)
    if side == "BUY":
        mfe = (hi - entry_price) / entry_price * 100.0
        mae = (lo - entry_price) / entry_price * 100.0
    elif side == "SELL":
        mfe = (entry_price - lo) / entry_price * 100.0
        mae = (entry_price - hi) / entry_price * 100.0
    else:
        return None

    return (mae, mfe, len(ltps))


# =====================
# AI（ローカル推論）：pos_idの品質スコア
# =====================
def ai_features_for_pid(
    *,
    rows_pid: List[Dict[str, str]],
    entry: Dict[str, str],
    exit_: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    feats: Dict[str, Any] = {}

    sp = to_float(entry.get("spread_pct"))
    feats["spread_pct"] = sp

    mf = to_float(entry.get("ma_fast"))
    ms = to_float(entry.get("ma_slow"))
    if mf is not None and ms is not None and ms != 0:
        feats["ma_gap_pct"] = abs(mf - ms) / ms * 100.0
    else:
        feats["ma_gap_pct"] = None

    if exit_:
        mf2 = to_float(exit_.get("ma_fast"))
    else:
        mf2 = None

    if mf is not None and mf2 is not None and mf != 0:
        feats["ma_slope_pct"] = (mf2 - mf) / mf * 100.0
    else:
        feats["ma_slope_pct"] = None

    t0 = parse_time(entry.get("time", ""))
    t1 = parse_time(exit_.get("time", "")) if exit_ else None
    ltps = []
    for r in rows_pid:
        t = parse_time(r.get("time", ""))
        if not t:
            continue
        if t0 and t1:
            if not (t0 <= t <= t1):
                continue
        l = to_float(r.get("ltp"))
        if l is not None:
            ltps.append(l)

    if len(ltps) >= 5:
        avg = sum(ltps) / len(ltps)
        if avg != 0:
            import math
            var = sum((x - avg) ** 2 for x in ltps) / len(ltps)
            sd = math.sqrt(var)
            feats["volatility_pct"] = (sd / avg) * 100.0
        else:
            feats["volatility_pct"] = None
    else:
        feats["volatility_pct"] = None

    note = safe_str(entry.get("note"), "")
    m = re.search(r"timeout_mode=([A-Z]+)", note)
    feats["timeout_mode"] = m.group(1) if m else ""

    return feats


def ai_score(feats: Dict[str, Any], use_features: List[str]) -> Tuple[float, Dict[str, float]]:
    use = set([x.strip().lower() for x in use_features if x.strip() != ""])
    x = 0.0
    comps: Dict[str, float] = {}

    sp = feats.get("spread_pct")
    if "spread" in use and sp is not None:
        comps["spread"] = clamp((0.06 - sp) * 18.0, -2.0, 2.0)
        x += comps["spread"]

    mg = feats.get("ma_gap_pct")
    if "ma_gap" in use and mg is not None:
        if mg < 0.02:
            comps["ma_gap"] = -0.9
        elif mg < 0.08:
            comps["ma_gap"] = 0.3
        elif mg < 0.30:
            comps["ma_gap"] = 0.7
        else:
            comps["ma_gap"] = -0.4
        x += comps["ma_gap"]

    ms = feats.get("ma_slope_pct")
    if "ma_slope" in use and ms is not None:
        comps["ma_slope"] = clamp(ms * 4.0, -1.2, 1.2)
        x += comps["ma_slope"]

    vol = feats.get("volatility_pct")
    if "volatility" in use and vol is not None:
        if vol < 0.06:
            comps["volatility"] = 0.2
        elif vol < 0.25:
            comps["volatility"] = 0.0
        else:
            comps["volatility"] = -0.6
        x += comps["volatility"]

    tm = safe_str(feats.get("timeout_mode", ""), "")
    if "timeout_mode" in use and tm:
        if tm == "IGNORE":
            comps["timeout_mode"] = 0.1
        elif tm == "PARTIAL":
            comps["timeout_mode"] = 0.0
        elif tm == "EXTEND":
            comps["timeout_mode"] = -0.2
        else:
            comps["timeout_mode"] = 0.0
        x += comps["timeout_mode"]

    s = sigmoid(x)
    return s, comps


# =====================
# 相関（MAE/MFE/outcome/hour）
# =====================
def bucket_hour(h: Optional[int]) -> str:
    if h is None:
        return "H??"
    return f"H{h:02d}"


def corr_summarize(values: List[Tuple[str, float]], show_top: int) -> List[str]:
    if not values:
        return []
    values_sorted = sorted(values, key=lambda x: x[1], reverse=True)
    top = values_sorted[:show_top]
    bot = list(reversed(values_sorted[-show_top:])) if len(values_sorted) > show_top else []
    out = []
    if top:
        out.append("TOP:")
        for k, v in top:
            out.append(f"  {k}: {v:.3f}")
    if bot:
        out.append("WORST:")
        for k, v in bot:
            out.append(f"  {k}: {v:.3f}")
    return out


# =====================
# WARN DUMP（①c想定：突合不整合、pos_id欠損等）
# =====================
def warn_dump_pos(rows_all: List[Dict[str, str]], msg: str, include_ltp: bool, limit: int = 40) -> None:
    print("\n[WARN_DUMP] " + msg)
    c = 0
    for r in rows_all[-200:]:
        if c >= limit:
            break
        line = f"{r.get('time','')} {r.get('result','')} side={r.get('side','')} price={r.get('price','')} pid={r.get('pos_id','')}"
        note = safe_str(r.get("note", ""), "")
        pid_note = extract_pos_id_any(note) or ""
        if pid_note:
            line += f" note_pid={pid_note}"
        if include_ltp:
            line += f" ltp={r.get('ltp','')}"
        if note:
            line += f" note={note[:120]}"
        print(line)
        c += 1


# =====================
# メイン
# =====================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("token_or_csv", nargs="?", default=None, help="YYYYMMDD / YYYYMMDD-YYYYMMDD / trade_log_YYYYMMDD.csv path (省略時は最新日)")
    ap.add_argument("--out-dir", type=str, default=None, help="監査JSONの出力先（省略時 MAIN/daily_report_out）")
    ap.add_argument("--sl", type=float, default=-0.23, help="互換用（現状は表示のみ）")
    ap.add_argument("--win", type=int, default=120, help="互換用（現状は表示のみ）")
    ap.add_argument("--control", type=str, default=None, help="CONTROL.csv (省略時はMAIN/CONTROL.csv を探す)")
    ap.add_argument("--crossday_back", type=int, default=None, help="日跨ぎ突合の過去日数（CONTROL優先、未設定ならデフォ）")
    ap.add_argument("--crossday_forward", type=int, default=None, help="日跨ぎ突合の未来日数（CONTROL優先、未設定ならデフォ）")
    ap.add_argument("--print-summary", action="store_true", help="ターミナルに要約を多めに出す")
    args = ap.parse_args()

    logs = get_logs_dir()
    all_days = list_log_days(logs)
    if not all_days:
        print("trade_log not found")
        return

    # CONTROL 読み込み（任意）
    if args.control:
        control_path = Path(args.control)
    else:
        here = get_main_dir()
        candidates = [
            here / "CONTROL.csv",
            here.parent / "MAIN" / "CONTROL.csv",
            here.parent / "CONTROL.csv",
        ]
        control_path = next((p for p in candidates if p.exists()), Path("CONTROL.csv"))

    control = read_control_csv(control_path) if control_path.exists() else {}

    # 設定反映（CONTROL優先）
    FILTER_ENABLED = safe_bool(control.get("report_filter_enabled"), FILTER_ENABLED_DEFAULT)
    FILTER_START_HOUR = safe_int(control.get("report_filter_start_hour"), FILTER_START_HOUR_DEFAULT)
    FILTER_END_HOUR = safe_int(control.get("report_filter_end_hour"), FILTER_END_HOUR_DEFAULT)

    SHOW_HISTORY = safe_bool(control.get("report_show_history"), SHOW_HISTORY_DEFAULT)
    HISTORY_MAX_DAYS = safe_int(control.get("report_history_max_days"), HISTORY_MAX_DAYS_DEFAULT)

    FAST_N = safe_int(control.get("fast_n"), FAST_N_DEFAULT)
    SLOW_N = safe_int(control.get("slow_n"), SLOW_N_DEFAULT)
    LTP_BUFFER_MAX = safe_int(control.get("report_ltp_buffer_max"), LTP_BUFFER_MAX_DEFAULT)

    WRITE_MAE_MFE_FILES = safe_bool(control.get("report_write_mae_mfe_files"), WRITE_MAE_MFE_FILES_DEFAULT)
    SHOW_MAE_MFE_TOP_N = safe_int(control.get("report_show_mae_mfe_top_n"), SHOW_MAE_MFE_TOP_N_DEFAULT)
    SHOW_MAE_MFE_WORST_N = safe_int(control.get("report_show_mae_mfe_worst_n"), SHOW_MAE_MFE_WORST_N_DEFAULT)

    WARN_DUMP_ENABLED = safe_bool(control.get("report_warn_dump_enabled"), WARN_DUMP_ENABLED_DEFAULT)
    WARN_DUMP_POSID_ENABLED = safe_bool(control.get("report_warn_dump_posid_enabled"), WARN_DUMP_POSID_ENABLED_DEFAULT)
    WARN_DUMP_POSID_INCLUDE_LTP = safe_bool(control.get("report_warn_dump_posid_include_ltp"), WARN_DUMP_POSID_INCLUDE_LTP_DEFAULT)

    LOOSE_POS_ENABLED = safe_bool(control.get("report_loose_pos_enabled"), LOOSE_POS_ENABLED_DEFAULT)

    CORR_ENABLED = safe_bool(control.get("report_corr_enabled"), CORR_ENABLED_DEFAULT)
    CORR_MIN_N = safe_int(control.get("report_corr_min_n"), CORR_MIN_N_DEFAULT)
    CORR_SHOW_TOP = safe_int(control.get("report_corr_show_top"), CORR_SHOW_TOP_DEFAULT)

    AI_ENABLED = safe_bool(control.get("report_ai_enabled"), AI_ENABLED_DEFAULT)
    AI_DEBUG = safe_bool(control.get("report_ai_debug"), AI_DEBUG_DEFAULT)
    AI_FEATURES = parse_csv_words(control.get("report_ai_features"), AI_FEATURES_DEFAULT)

    # crossday（引数があれば引数優先、なければCONTROL、なければデフォ）
    cd_back = args.crossday_back if args.crossday_back is not None else safe_int(control.get("report_crossday_back"), CROSSDAY_BACK_DEFAULT)
    cd_fwd = args.crossday_forward if args.crossday_forward is not None else safe_int(control.get("report_crossday_forward"), CROSSDAY_FORWARD_DEFAULT)

    # out-dir
    out_dir = Path(args.out_dir) if args.out_dir else (get_main_dir() / "daily_report_out")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 対象の決定（token or path）
    token = None
    csv_path = None
    target_days: List[str] = []

    if args.token_or_csv:
        p = Path(args.token_or_csv)
        if p.exists() and p.is_file() and p.name.startswith("trade_log_") and p.name.endswith(".csv"):
            csv_path = p
            m = re.search(r"trade_log_(\d{8})\.csv", p.name)
            if m:
                token = m.group(1)
        else:
            token = args.token_or_csv
    else:
        token = all_days[-1]

    # token 解析
    if token:
        s8, e8 = parse_token(token)
        if not s8:
            print(f"invalid token: {token}")
            return
        target_days = pick_days_in_range(all_days, s8, e8)
        if not target_days:
            print(f"no files in range: {s8}-{e8}")
            return
    else:
        # path only (date取れない) → 最新日扱いで進める
        target_days = [all_days[-1]]

    # crossday拡張日
    load_days = expand_days_with_cross(all_days, target_days, cd_back, cd_fwd)
    files = collect_files_for_days(logs, load_days)
    rows_raw_cross = load_rows_crossday(files)

    # SMA補完（クロスデイ全体で補完）
    rows_all = backfill_ma(rows_raw_cross, FAST_N, SLOW_N, LTP_BUFFER_MAX)

    # 集計対象（target_daysの行）
    target_set = set(target_days)

    def is_target_row(r: Dict[str, str]) -> bool:
        return safe_str(r.get("_day8"), "") in target_set

    rows_target_all = [r for r in rows_all if is_target_row(r)]

    # 時間フィルタ（集計用）
    rows = []
    for r in rows_target_all:
        if not FILTER_ENABLED:
            rows.append(r)
            continue
        h = hour_from_time(r.get("time", ""))
        if h is None:
            continue
        if in_filter(h, FILTER_START_HOUR, FILTER_END_HOUR):
            rows.append(r)

    # ===== 集計（resultカウント）=====
    result_cnt = Counter((r.get("result") or "") for r in rows)
    paper = result_cnt.get(RESULT_PAPER, 0)
    observe = sum(v for k, v in result_cnt.items() if k.startswith(RESULT_OBSERVE_PREFIX))
    paper_rate = paper / max(1, paper + observe) * 100.0

    # ===== pos_id grouping（rows_all で束ねる：crossday補完の根）=====
    by_pid: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    missing_pid_rows = 0
    loose_pid_cnt = Counter()

    for r in rows_all:
        pid_col = safe_str(r.get("pos_id"), "")
        pid_note = extract_pos_id_any(safe_str(r.get("note"), ""))
        pid = pid_col or pid_note
        if pid:
            by_pid[pid].append(r)
            if not is_strict_pid(pid):
                loose_pid_cnt[pid] += 1
        else:
            missing_pid_rows += 1

    # pidごとに entry/exit を拾う（crossday補完）
    warn_flags = []
    mae_mfe_list = []
    ai_list = []

    # 監査JSON用 per_pos
    per_pos: Dict[str, Any] = {}
    issues: List[str] = []

    for pid, rs in by_pid.items():
        rs_sorted = sorted(rs, key=lambda x: parse_time(x.get("time", "")) or datetime.min)

        entry = next((r for r in rs_sorted if (r.get("result") or "") == RESULT_PAPER), None)
        exit_ = next((r for r in rs_sorted if (r.get("result") or "").startswith(RESULT_PAPER_EXIT_PREFIX)), None)

        if entry is None or exit_ is None:
            warn_flags.append((pid, "MISSING_ENTRY" if entry is None else "MISSING_EXIT"))

        outcome = outcome_from_result(exit_.get("result")) if exit_ else "NO_DATA"

        # status（監査）
        if entry and exit_:
            status = "CLOSED"
        elif entry and not exit_:
            status = "OPEN"
        elif (not entry) and exit_:
            status = "ERROR"
            issues.append(f"ERROR pos_id={pid} EXIT without ENTRY")
        else:
            status = "UNKNOWN"

        entry_t = parse_time(entry.get("time", "")) if entry else None
        exit_t = parse_time(exit_.get("time", "")) if exit_ else None
        dur_min = None
        if entry_t and exit_t and exit_t >= entry_t:
            dur_min = int((exit_t - entry_t).total_seconds() // 60)

        # MAE/MFE
        if entry and exit_:
            mm = compute_mae_mfe(rs_sorted, entry, exit_)
            if mm:
                mae, mfe, nltp = mm
                mae_mfe_list.append((pid, mae, mfe, nltp, outcome, hour_from_time(entry.get("time", ""))))
        # AI（任意）
        if AI_ENABLED and entry:
            feats = ai_features_for_pid(rows_pid=rs_sorted, entry=entry, exit_=exit_)
            s, comps = ai_score(feats, AI_FEATURES)
            ai_list.append((pid, s, feats, comps, outcome))

        # per_pos（Dashboard用）
        per_pos[pid] = {
            "status": status,
            "outcome": outcome,
            "duration_min": dur_min if dur_min is not None else "",
            "entry": None if not entry else {
                "time": safe_str(entry.get("time"), ""),
                "side": safe_str(entry.get("side"), ""),
                "price": safe_str(entry.get("price"), ""),
                "ltp": safe_str(entry.get("ltp"), ""),
                "result": safe_str(entry.get("result"), ""),
                "note": safe_str(entry.get("note"), ""),
                "_day8": safe_str(entry.get("_day8"), ""),
            },
            "exit": None if not exit_ else {
                "time": safe_str(exit_.get("time"), ""),
                "side": safe_str(exit_.get("side"), ""),
                "price": safe_str(exit_.get("price"), ""),
                "ltp": safe_str(exit_.get("ltp"), ""),
                "result": safe_str(exit_.get("result"), ""),
                "note": safe_str(exit_.get("note"), ""),
                "_day8": safe_str(exit_.get("_day8"), ""),
            },
        }

    # ===== issues / warnings =====
    if missing_pid_rows > 0:
        issues.append(f"WARN pid_missing_rows={missing_pid_rows} (pos_id column and note pid not found)")

    if warn_flags:
        cnt = Counter(flag for _, flag in warn_flags)
        issues.append(f"WARN pos_id_missing_entry_or_exit={dict(cnt)}")

    # ===== 画面出力（stdout） =====
    print(f"\n=== DAILY REPORT {compute_report_key(target_days)} ===")
    if control:
        print(f"[CONTROL] loaded: {control_path}")
    print(f"[RANGE] target_days={target_days}  load_days={load_days} (crossday back={cd_back} fwd={cd_fwd})")
    print(f"[FILTER] enabled={FILTER_ENABLED} {FILTER_START_HOUR:02d}-{FILTER_END_HOUR:02d}")
    print(f"PAPER={paper} OBSERVE={observe} RATE={paper_rate:.1f}%")
    print("result_counts:", dict(result_cnt))
    print("\n--- pos_id audit ---")
    print(f"pos_groups={len(by_pid)} missing_pid_rows={missing_pid_rows}")

    if LOOSE_POS_ENABLED and loose_pid_cnt:
        loose_n = sum(loose_pid_cnt.values())
        top_loose = loose_pid_cnt.most_common(5)
        print(f"LOOSE_pos_id_rows={loose_n} top={top_loose}")

    if warn_flags:
        cnt = Counter(flag for _, flag in warn_flags)
        print("WARN flags:", dict(cnt))
        if WARN_DUMP_ENABLED and WARN_DUMP_POSID_ENABLED:
            warn_dump_pos(rows_all, msg=f"pos_id mismatch dump (flags={dict(cnt)})", include_ltp=WARN_DUMP_POSID_INCLUDE_LTP)

    # ===== MAE/MFE 集計 =====
    if mae_mfe_list:
        maes = [x[1] for x in mae_mfe_list]
        mfes = [x[2] for x in mae_mfe_list]
        avg_mae = sum(maes) / len(maes)
        avg_mfe = sum(mfes) / len(mfes)
        print("\n--- MAE/MFE summary ---")
        print(f"pos={len(mae_mfe_list)} avg_MAE={avg_mae:.3f}% avg_MFE={avg_mfe:.3f}%")

        best_mfe = sorted(mae_mfe_list, key=lambda x: x[2], reverse=True)[:SHOW_MAE_MFE_TOP_N]
        worst_mae = sorted(mae_mfe_list, key=lambda x: x[1])[:SHOW_MAE_MFE_WORST_N]

        print(f"\nTOP MFE (n={min(SHOW_MAE_MFE_TOP_N, len(best_mfe))})")
        for pid, mae, mfe, nltp, outc, eh in best_mfe:
            print(f"  {pid} outcome={outc} entry_hour={eh} MAE={mae:.3f}% MFE={mfe:.3f}% nltp={nltp}")

        print(f"\nWORST MAE (n={min(SHOW_MAE_MFE_WORST_N, len(worst_mae))})")
        for pid, mae, mfe, nltp, outc, eh in worst_mae:
            print(f"  {pid} outcome={outc} entry_hour={eh} MAE={mae:.3f}% MFE={mfe:.3f}% nltp={nltp}")

        if WRITE_MAE_MFE_FILES:
            out_rep = logs / "reports"
            out_rep.mkdir(parents=True, exist_ok=True)
            day_tag = compute_report_key(target_days).replace("daily_report_", "")
            mae_path = out_rep / f"mae_mfe_{day_tag}.csv"
            fieldnames = ["pid", "outcome", "entry_hour", "mae_pct", "mfe_pct", "nltp"]
            rows_out = []
            for pid, mae, mfe, nltp, outc, eh in mae_mfe_list:
                rows_out.append({
                    "pid": pid,
                    "outcome": outc,
                    "entry_hour": eh if eh is not None else "",
                    "mae_pct": f"{mae:.6f}",
                    "mfe_pct": f"{mfe:.6f}",
                    "nltp": nltp,
                })
            write_rows(mae_path, fieldnames, rows_out)
            print(f"\n[WRITE] {mae_path}")
    else:
        print("\n--- MAE/MFE summary ---")
        print("no MAE/MFE data (need both PAPER and PAPER_EXIT with ltp samples)")

    # ===== AI 集計 =====
    if AI_ENABLED:
        print("\n--- AI summary ---")
        if not ai_list:
            print("no AI data (need PAPER entries)")
        else:
            scores = [x[1] for x in ai_list]
            avg_s = sum(scores) / len(scores)
            print(f"ai_pos={len(ai_list)} avg_score={avg_s:.3f} features={AI_FEATURES}")

            by_out = defaultdict(list)
            for pid, sc, feats, comps, outc in ai_list:
                by_out[outc].append(sc)
            for outc in OUTCOME_KEYS:
                if outc in by_out:
                    xs = by_out[outc]
                    print(f"  outcome={outc} n={len(xs)} avg_score={sum(xs)/len(xs):.3f}")

            top = sorted(ai_list, key=lambda x: x[1], reverse=True)[:5]
            bot = sorted(ai_list, key=lambda x: x[1])[:5]
            if AI_DEBUG:
                print("\nAI TOP examples:")
                for pid, sc, feats, comps, outc in top:
                    print(f"  {pid} out={outc} score={sc:.3f} feats={json.dumps(feats, ensure_ascii=False)} comps={json.dumps(comps, ensure_ascii=False)}")
                print("\nAI LOW examples:")
                for pid, sc, feats, comps, outc in bot:
                    print(f"  {pid} out={outc} score={sc:.3f} feats={json.dumps(feats, ensure_ascii=False)} comps={json.dumps(comps, ensure_ascii=False)}")
            else:
                print("  (set report_ai_debug=1 to print feature details)")

            if WRITE_MAE_MFE_FILES:
                out_rep = logs / "reports"
                out_rep.mkdir(parents=True, exist_ok=True)
                day_tag = compute_report_key(target_days).replace("daily_report_", "")
                ai_path = out_rep / f"ai_score_{day_tag}.csv"
                fieldnames = ["pid", "outcome", "ai_score", "spread_pct", "ma_gap_pct", "ma_slope_pct", "volatility_pct", "timeout_mode"]
                rows_out = []
                for pid, sc, feats, comps, outc in ai_list:
                    rows_out.append({
                        "pid": pid,
                        "outcome": outc,
                        "ai_score": f"{sc:.6f}",
                        "spread_pct": "" if feats.get("spread_pct") is None else f"{feats.get('spread_pct'):.6f}",
                        "ma_gap_pct": "" if feats.get("ma_gap_pct") is None else f"{feats.get('ma_gap_pct'):.6f}",
                        "ma_slope_pct": "" if feats.get("ma_slope_pct") is None else f"{feats.get('ma_slope_pct'):.6f}",
                        "volatility_pct": "" if feats.get("volatility_pct") is None else f"{feats.get('volatility_pct'):.6f}",
                        "timeout_mode": safe_str(feats.get("timeout_mode"), ""),
                    })
                write_rows(ai_path, fieldnames, rows_out)
                print(f"[WRITE] {ai_path}")

    # ===== 相関（MAE/MFE × outcome × hour）=====
    if CORR_ENABLED and mae_mfe_list:
        print("\n--- CORRELATION (MAE/MFE × outcome × hour) ---")
        by_out = defaultdict(list)
        by_hour = defaultdict(list)
        by_out_hour = defaultdict(list)

        for pid, mae, mfe, nltp, outc, eh in mae_mfe_list:
            by_out[outc].append((mae, mfe))
            by_hour[bucket_hour(eh)].append((mae, mfe))
            by_out_hour[(outc, bucket_hour(eh))].append((mae, mfe))

        def avg_pair(pairs):
            if not pairs:
                return None
            maes = [x[0] for x in pairs]
            mfes = [x[1] for x in pairs]
            return (sum(maes)/len(maes), sum(mfes)/len(mfes))

        out_lines = []
        for outc, pairs in by_out.items():
            if len(pairs) < CORR_MIN_N:
                continue
            a = avg_pair(pairs)
            if a:
                out_lines.append((f"outcome={outc}(n={len(pairs)})", a[1]))
        for line in corr_summarize(out_lines, CORR_SHOW_TOP):
            print(line)

        hour_lines = []
        for hkey, pairs in by_hour.items():
            if len(pairs) < CORR_MIN_N:
                continue
            a = avg_pair(pairs)
            if a:
                hour_lines.append((f"{hkey}(n={len(pairs)})", a[1]))
        if hour_lines:
            print("\n[MFE by hour buckets]")
            for line in corr_summarize(hour_lines, CORR_SHOW_TOP):
                print(line)

        comb_lines = []
        for (outc, hkey), pairs in by_out_hour.items():
            if len(pairs) < CORR_MIN_N:
                continue
            a = avg_pair(pairs)
            if a:
                comb_lines.append((f"{outc}@{hkey}(n={len(pairs)})", a[1]))
        if comb_lines:
            print("\n[MFE by outcome@hour]")
            for line in corr_summarize(comb_lines, CORR_SHOW_TOP):
                print(line)

        if hour_lines:
            hour_lines_sorted = sorted(hour_lines, key=lambda x: x[1], reverse=True)
            best_h, best_v = hour_lines_sorted[0]
            worst_h, worst_v = hour_lines_sorted[-1]
            print("\n[INSIGHT]")
            print(f"- MFEが高い傾向: {best_h} (avg_MFE={best_v:.3f})")
            print(f"- MFEが低い傾向: {worst_h} (avg_MFE={worst_v:.3f})")

    # ===== 履歴（直近N日）=====
    if SHOW_HISTORY:
        files_hist = sorted(logs.glob("trade_log_*.csv"))[-HISTORY_MAX_DAYS:]
        if files_hist:
            print(f"\n--- HISTORY (last {len(files_hist)} files) ---")
            for p in files_hist:
                try:
                    rs = read_rows(p)
                    cnt = Counter(r.get("result", "") for r in rs)
                    paper_h = cnt.get("PAPER", 0)
                    exits_h = sum(v for k, v in cnt.items() if k.startswith("PAPER_EXIT"))
                    obs_h = sum(v for k, v in cnt.items() if k.startswith("OBSERVE"))
                    print(f"{p.name}: PAPER={paper_h} EXIT={exits_h} OBS={obs_h}")
                except Exception:
                    continue

    # ===== 監査JSON出力（Dashboard用）=====
    key = compute_report_key(target_days)
    audit_path = out_dir / f"{key}.json"

    payload = {
        "version": "v3-E-full",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "logs_dir": str(logs),
        "control_path": str(control_path) if control_path else "",
        "target_days": target_days,
        "load_days": load_days,
        "filter": {
            "enabled": FILTER_ENABLED,
            "start_hour": FILTER_START_HOUR,
            "end_hour": FILTER_END_HOUR,
        },
        "result_counts_target_filtered": dict(result_cnt),
        "paper": paper,
        "observe": observe,
        "paper_rate": paper_rate,
        "pid_groups": len(by_pid),
        "pid_missing_rows": missing_pid_rows,
        "loose_pos_id_rows": int(sum(loose_pid_cnt.values())) if loose_pid_cnt else 0,
        "loose_pos_top5": loose_pid_cnt.most_common(5) if loose_pid_cnt else [],
        "issues": issues,
        "per_pos": per_pos,
        "features": {
            "mae_mfe": bool(mae_mfe_list),
            "ai_enabled": AI_ENABLED,
            "corr_enabled": CORR_ENABLED,
            "warn_dump_enabled": WARN_DUMP_ENABLED,
        }
    }

    audit_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Dashboardの実行結果欄で見えるように必ず出す
    print(f"\n[WRITE] {audit_path}")
    if args.print_summary:
        print(f"[OK] daily_report done ({key})")


if __name__ == "__main__":
    main()
