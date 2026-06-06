# MAIN/create_ai_dataset.py
# ============================================================
# trade_log_YYYYMMDD.csv を pos_id 単位で集約し、
# ai_train_dataset_YYYYMMDD.csv を ../logs に出力する
# ============================================================

import csv
import re
from pathlib import Path
from datetime import datetime

MAIN_DIR = Path(__file__).resolve().parent
LOGS_DIR = MAIN_DIR.parent / "logs"

TRADE_LOG_RE = re.compile(r"^trade_log_(\d{8})\.csv$")
AI_DATASET_NAME = "ai_train_dataset_{day8}.csv"

# bot.py の note に刻まれる可能性があるキー（保険）
NOTE_KV_RE = re.compile(r"(\b[a-zA-Z_]+)=([0-9]+(?:\.[0-9]+)?)")

EXIT_RESULTS = {
    "PAPER_EXIT_TP": "TP",
    "PAPER_EXIT_SL": "SL",
    "PAPER_EXIT_TIMEOUT": "TIMEOUT",
    "PAPER_EXIT_EOD": "EOD",
    "PAPER_EXIT_PRENEWS": "PRENEWS",
    "PAPER_EXIT_PARTIAL_TP": "PARTIAL_TP",  # 念のため
    "PAPER_EXIT_PARTIAL_TP_LABEL": "PARTIAL_TP",  # 互換用（未使用なら無視）
    "PAPER_EXIT_PARTIAL_TP": "PARTIAL_TP",
    "PAPER_EXIT_PARTIAL_TP ": "PARTIAL_TP",
}

# ここの列は「後で増やしてOK」。まずは学習に必要な最小核。
OUT_FIELDS = [
    "pos_id",
    "entry_time",
    "exit_time",
    "hold_min",
    "side",
    "entry_price",
    "exit_ltp",
    "size",
    "units",
    "tp_price",
    "sl_price",
    "tp_pct",
    "sl_pct",
    "win_used",
    "timeout_mode",
    "extend_count",
    "best_fav_pct",
    "spread_pct_entry",
    "ma_fast_entry",
    "ma_slow_entry",
    "trend_entry",
    "signal_entry",
    "ma_gap_pct_entry",
    "ma_slope_pct_per_step_entry",
    "volatility_pct_entry",
    "hour_entry",
    "ai_score_entry",
    "ai_mode",
    "outcome",
    "is_win",
    "pnl_like_pct",
]

def safe_float(x, default=None):
    try:
        if x is None:
            return default
        s = str(x).strip()
        if s == "":
            return default
        return float(s)
    except Exception:
        return default

def safe_int(x, default=None):
    try:
        if x is None:
            return default
        s = str(x).strip()
        if s == "":
            return default
        return int(float(s))
    except Exception:
        return default

def parse_time(s):
    # bot.py の now_str: "%Y-%m-%d %H:%M:%S"
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None

def note_kv(note: str) -> dict:
    """
    note の中に "key=123.45" があれば抜く（units/sp_entry/ma_gap/ma_slope/vol 等の保険）
    """
    d = {}
    if not note:
        return d
    for m in NOTE_KV_RE.finditer(note):
        k = m.group(1)
        v = m.group(2)
        d[k] = v
    return d

def calc_units(size: float) -> int:
    # 0.001 を 1 unit とする
    if size is None:
        return 0
    return int(round(float(size) / 0.001))

def pnl_like_pct(side: str, entry: float, exit_ltp: float):
    """
    PAPERのため厳密PNLではなく「価格変化率」を暫定で学習ラベルとして残す
    BUY : (exit-entry)/entry *100
    SELL: (entry-exit)/entry *100
    """
    if entry is None or exit_ltp is None or entry == 0:
        return None
    side = (side or "").upper()
    if side == "SELL":
        return (entry - exit_ltp) / entry * 100.0
    return (exit_ltp - entry) / entry * 100.0

def is_win_from_outcome(outcome: str):
    """
    TIMEOUTの勝ち判定は思想次第でブレやすいので 0/1 にせず空欄にするのが安全。
    """
    if outcome == "TP":
        return 1
    if outcome == "SL":
        return 0
    if outcome == "PARTIAL_TP":
        return 1
    # TIMEOUT/EOD は一旦「不明」に寄せる
    return ""

def read_trade_log(csv_path: Path) -> list:
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return [row for row in r]

def build_dataset_for_day(day8: str, rows: list) -> list:
    """
    rows: trade_log_YYYYMMDD.csv の全行
    pos_id ごとに ENTRY(PAPER) と EXIT(PAPER_EXIT_*) をマージして 1行にする
    """
    # pos_id -> entry_row/exit_row
    entry = {}
    exit_ = {}

    for row in rows:
        pos_id = (row.get("pos_id") or "").strip()
        if not pos_id:
            continue

        res = (row.get("result") or "").strip()

        # ENTRY
        if res == "PAPER":
            # 同pos_idで複数PAPERがあるのは基本ない想定。あれば最初優先。
            entry.setdefault(pos_id, row)
            continue

        # EXIT（PAPER_EXIT_* / PARTIAL / EOD）
        if res.startswith("PAPER_EXIT_"):
            # 1pos_idで複数EXITがあれば最後を採用（後勝ち）
            exit_[pos_id] = row
            continue

        # PARTIALのラベル互換（あなたの bot.py は PARTIAL_TP_LABEL を使う）
        if res == "PAPER_EXIT_PARTIAL_TP":
            exit_[pos_id] = row
            continue

        # EOD_RESULT は bot.py で "PAPER_EXIT_EOD" を使う想定だが、念のため
        if res == "PAPER_EXIT_EOD":
            exit_[pos_id] = row
            continue

    dataset = []
    for pos_id, e in entry.items():
        x = exit_.get(pos_id)

        entry_time = (e.get("time") or "").strip()
        exit_time = (x.get("time") or "").strip() if x else ""

        dt_e = parse_time(entry_time)
        dt_x = parse_time(exit_time) if exit_time else None
        hold_min = ""
        if dt_e and dt_x:
            hold_min = int(round((dt_x - dt_e).total_seconds() / 60.0))

        side = (e.get("side") or "").strip().upper()
        entry_price = safe_float(e.get("price"))
        exit_ltp = safe_float(x.get("ltp")) if x else None
        size = safe_float(e.get("size"))
        units = calc_units(size)

        ma_fast = safe_float(e.get("ma_fast"))
        ma_slow = safe_float(e.get("ma_slow"))
        spread_pct_entry = safe_float(e.get("spread_pct"))  # 既に % 表記で入ってる（bot.pyが*100してる）
        trend = (e.get("trend") or "").strip()
        signal = (e.get("signal") or "").strip()

        # note保険
        kv = note_kv((e.get("note") or ""))
        # units が note にあれば優先
        if "units" in kv:
            u2 = safe_int(kv.get("units"))
            if u2 is not None:
                units = u2
        # spread保険（sp_entry）
        if spread_pct_entry is None and "sp_entry" in kv:
            spread_pct_entry = safe_float(kv.get("sp_entry"))

        # MA gap（ENTRY行から計算できる）
        ma_gap = None
        if ma_fast is not None and ma_slow is not None and ma_slow != 0:
            ma_gap = abs(ma_fast - ma_slow) / ma_slow * 100.0
        # note保険
        if "ma_gap" in kv:
            ma_gap = safe_float(kv.get("ma_gap"), ma_gap)

        ma_slope = safe_float(kv.get("ma_slope")) if "ma_slope" in kv else None
        vol = safe_float(kv.get("vol")) if "vol" in kv else None

        hour_entry = dt_e.hour if dt_e else ""

        # AI（ENTRY noteから抜けるならそれも可）
        ai_score = None
        ai_mode = ""
        note_text = (e.get("note") or "")
        m = re.search(r"\bAI score=([0-9]+\.[0-9]+)", note_text)
        if m:
            ai_score = safe_float(m.group(1))
        # modeは state/設定に依存するので、noteに刻んでないなら空でOK（不明）
        # （将来 bot.py 側で ai_mode を note に入れるならここで抜ける）

        # outcome
        outcome = ""
        if x:
            resx = (x.get("result") or "").strip()
            outcome = resx.replace("PAPER_EXIT_", "")
            # PARTIALはラベルが揺れる可能性があるので吸収
            if "PARTIAL" in outcome:
                outcome = "PARTIAL_TP"
            if outcome not in ("TP", "SL", "TIMEOUT", "EOD", "PARTIAL_TP"):
                # 未知はそのまま残す（不明扱い）
                pass

        win_used = ""
        timeout_mode = ""
        tp_price = ""
        sl_price = ""
        tp_pct = ""
        sl_pct = ""
        extend_count = ""
        best_fav_pct = ""

        # EXIT note から取れるものもあるが、現状は state にある情報をログに書いてない場合が多いので
        # "不明"として空欄でOK。必要なら bot.py で EXIT時も書き込む改善を後で入れる。
        # ただし、bot.py の EXITログnoteには "best_fav=... extend_count=..." が入ってるので拾う。
        if x:
            kvx = note_kv((x.get("note") or ""))
            if "extend_count" in kvx:
                extend_count = safe_int(kvx.get("extend_count"), "")
            if "best_fav" in kvx:
                best_fav_pct = safe_float(kvx.get("best_fav"), "")
            # tp/sl は "tp=... sl=..." がある形式なので簡易抽出
            mtp = re.search(r"\btp=([0-9]+(?:\.[0-9]+)?)", (x.get("note") or ""))
            msl = re.search(r"\bsl=([0-9]+(?:\.[0-9]+)?)", (x.get("note") or ""))
            if mtp:
                tp_price = safe_float(mtp.group(1), "")
            if msl:
                sl_price = safe_float(msl.group(1), "")

        # pnl_like
        pl = pnl_like_pct(side, entry_price, exit_ltp) if x else None

        row_out = {k: "" for k in OUT_FIELDS}
        row_out.update({
            "pos_id": pos_id,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "hold_min": hold_min,
            "side": side,
            "entry_price": entry_price if entry_price is not None else "",
            "exit_ltp": exit_ltp if exit_ltp is not None else "",
            "size": size if size is not None else "",
            "units": units,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
            "win_used": win_used,
            "timeout_mode": timeout_mode,
            "extend_count": extend_count,
            "best_fav_pct": best_fav_pct,
            "spread_pct_entry": spread_pct_entry if spread_pct_entry is not None else "",
            "ma_fast_entry": ma_fast if ma_fast is not None else "",
            "ma_slow_entry": ma_slow if ma_slow is not None else "",
            "trend_entry": trend,
            "signal_entry": signal,
            "ma_gap_pct_entry": round(ma_gap, 6) if ma_gap is not None else "",
            "ma_slope_pct_per_step_entry": ma_slope if ma_slope is not None else "",
            "volatility_pct_entry": vol if vol is not None else "",
            "hour_entry": hour_entry,
            "ai_score_entry": ai_score if ai_score is not None else "",
            "ai_mode": ai_mode,
            "outcome": outcome,
            "is_win": is_win_from_outcome(outcome) if outcome else "",
            "pnl_like_pct": round(pl, 6) if pl is not None else "",
        })
        dataset.append(row_out)

    return dataset

def write_dataset(day8: str, dataset: list):
    out_path = LOGS_DIR / AI_DATASET_NAME.format(day8=day8)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        w.writeheader()
        for row in dataset:
            w.writerow(row)
    print(f"[OK] wrote: {out_path} rows={len(dataset)}")

def main():
    if not LOGS_DIR.exists():
        print(f"[WARN] logs dir not found: {LOGS_DIR}")
        return

    trade_logs = []
    for p in sorted(LOGS_DIR.iterdir()):
        m = TRADE_LOG_RE.match(p.name)
        if not m:
            continue
        day8 = m.group(1)
        trade_logs.append((day8, p))

    if not trade_logs:
        print("[WARN] no trade_log_YYYYMMDD.csv found.")
        return

    for day8, csv_path in trade_logs:
        rows = read_trade_log(csv_path)
        ds = build_dataset_for_day(day8, rows)
        write_dataset(day8, ds)

if __name__ == "__main__":
    main()
