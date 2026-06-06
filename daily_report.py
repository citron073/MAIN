# ============================================================
# Project Ouroboros v1
# daily_report.py
# SPEC_OUROBOROS_DAILY_REPORT_V1 完全準拠版
# ============================================================

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from collections import Counter, defaultdict
from statistics import mean

SPEC_VERSION = "SPEC_OUROBOROS_DAILY_REPORT_V1"
AI_SCORE_RE = re.compile(r"\bscore=([0-9]*\.?[0-9]+)\b")

# ============================================================
# ユーティリティ
# ============================================================

def parse_time(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except:
        return None

def to_float(x):
    try:
        return float(x)
    except:
        return None

def pct_round(x):
    return round(x, 1)

def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

# ============================================================
# result分類
# ============================================================

def classify_result(r):
    if r == "PAPER":
        return "PAPER"
    if r.startswith("OBSERVE"):
        return "OBSERVE"
    if r.startswith("SKIP"):
        return "SKIP"
    if r == "HOLD_OPEN_POS":
        return "HOLD"
    if r.startswith("PAPER_EXIT_"):
        return "EXIT"
    if r.startswith("ERROR"):
        return "ERROR"
    return "UNKNOWN"

# compatibility alias (some legacy callers reference _classify_result)
_classify_result = classify_result

# ============================================================
# MAE/MFE 推定（fee未加味）
# ============================================================

def compute_mae_mfe(rows, entry_row, exit_row):
    side = entry_row.get("side", "")
    entry_price = to_float(entry_row.get("price"))
    if entry_price is None:
        return None

    t0 = parse_time(entry_row.get("time"))
    t1 = parse_time(exit_row.get("time"))
    if not t0 or not t1:
        return None

    ltps = []
    for r in rows:
        t = parse_time(r.get("time"))
        if not t:
            continue
        if t0 <= t <= t1:
            l = to_float(r.get("ltp"))
            if l is not None:
                ltps.append(l)

    if not ltps:
        return None

    hi = max(ltps)
    lo = min(ltps)

    if side == "BUY":
        mfe = (hi - entry_price) / entry_price * 100
        mae = (lo - entry_price) / entry_price * 100
    elif side == "SELL":
        mfe = (entry_price - lo) / entry_price * 100
        mae = (entry_price - hi) / entry_price * 100
    else:
        return None

    ret = (to_float(exit_row.get("price")) - entry_price) / entry_price * 100
    if side == "SELL":
        ret = -ret

    return mae, mfe, ret


def _infer_ai_from_rows(rows_for_pid):
    """
    Infer AI metadata from note text.
    Returns:
      (score: float|None, passed: bool|None)
    """
    score = None
    passed = None
    for r in reversed(rows_for_pid):
        note = str(r.get("note") or "")
        if score is None:
            m = AI_SCORE_RE.search(note)
            if m:
                try:
                    score = float(m.group(1))
                except Exception:
                    score = None
        low = note.lower()
        if passed is None:
            if ("ai_allow(" in low) or ("veto_sim=allow" in low):
                passed = True
            elif ("ai_block(" in low) or ("gate_sim=block" in low) or ("ai_block" in low):
                passed = False
        if score is not None and passed is not None:
            break
    return score, passed

# ============================================================
# メイン処理
# ============================================================


def hour_from_time(s: str):
    """
    return: 0-23 (int) or None
    accept formats like:
      - "YYYY-MM-DD HH:MM:SS"
      - "YYYY-MM-DD HH:MM"
      - ISO "YYYY-MM-DDTHH:MM:SS"
    """
    try:
        t = (s or "").strip()
        if not t:
            return None
        t = t.replace("T", " ")
        # fast-path: split by space
        if " " in t:
            hhmmss = t.split(" ", 1)[1].strip()
            if len(hhmmss) >= 2 and hhmmss[:2].isdigit():
                h = int(hhmmss[:2])
                return h if 0 <= h <= 23 else None
        # fallback parse
        from datetime import datetime
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                dt = datetime.strptime(t, fmt)
                return dt.hour
            except Exception:
                pass
        return None
    except Exception:
        return None

# compatibility alias
_hour_from_time = hour_from_time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("day8", help="YYYYMMDD")
    ap.add_argument("--out-dir", default="daily_report_out")
    args = ap.parse_args()

    day8 = args.day8
    logs_dir = Path(__file__).parent.parent / "logs"
    log_path = logs_dir / f"trade_log_{day8}.csv"

    if not log_path.exists():
        print("log not found")
        return

    rows = read_csv(log_path)

    issues = []
    required_cols = [
        "time","result","ltp","best_bid","best_ask",
        "spread_pct","limit_pct","trend","signal","note","pos_id"
    ]

    for c in required_cols:
        if c not in rows[0]:
            issues.append({
                "severity":"ERROR",
                "code":"MISSING_REQUIRED_COLUMN",
                "pos_id":None,
                "message":f"missing column {c}",
                "evidence":{}
            })

    rows_used = []
    rows_dropped = 0

    for r in rows:
        if not parse_time(r.get("time")):
            rows_dropped += 1
            issues.append({
                "severity":"WARN",
                "code":"BAD_TIME_PARSE",
                "pos_id":None,
                "message":"time parse failed",
                "evidence":{"time":r.get("time")}
            })
            continue
        rows_used.append(r)

    # --------------------------------------------------------
    # result集計
    # --------------------------------------------------------
    result_counter = Counter()
    class_counter = Counter()

    for r in rows_used:
        res = r.get("result","")
        result_counter[res]+=1
        class_counter[classify_result(res)]+=1

    paper_n = class_counter["PAPER"]
    observe_n = class_counter["OBSERVE"]

    denom = paper_n + observe_n
    paper_rate = pct_round((paper_n/denom*100) if denom>0 else 0.0)

    # --------------------------------------------------------
    # spread統計
    # --------------------------------------------------------
    spreads = [to_float(r.get("spread_pct")) for r in rows_used if to_float(r.get("spread_pct")) is not None]
    limit_vals = [to_float(r.get("limit_pct")) for r in rows_used if to_float(r.get("limit_pct")) is not None]
    limit_pct = limit_vals[0] if limit_vals else 0

    spread_over = [s for s in spreads if limit_pct and s>limit_pct]
    spread_block = {
        "limit_pct":limit_pct,
        "avg_pct":mean(spreads) if spreads else 0,
        "p50_pct":sorted(spreads)[len(spreads)//2] if spreads else 0,
        "p90_pct":sorted(spreads)[int(len(spreads)*0.9)] if spreads else 0,
        "p95_pct":sorted(spreads)[int(len(spreads)*0.95)] if spreads else 0,
        "max_pct":max(spreads) if spreads else 0,
        "over_limit_n":len(spread_over),
        "over_limit_pct":pct_round(len(spread_over)/len(spreads)*100) if spreads else 0
    }

    # --------------------------------------------------------
    # pos_id監査
    # --------------------------------------------------------
    by_pid = defaultdict(list)
    for r in rows_used:
        pid = r.get("pos_id") or ""
        if not pid and r.get("result")=="PAPER":
            issues.append({
                "severity":"ERROR",
                "code":"POS_ID_MISSING_ON_PAPER",
                "pos_id":None,
                "message":"PAPER without pos_id",
                "evidence":r
            })
        if pid:
            by_pid[pid].append(r)

    exit_integrity = {
        "paper_pos_ids":0,
        "exit_pos_ids":0,
        "closed_pos_ids":0,
        "open_pos_ids":0,
        "missing_exit_pos_ids":[],
        "duplicate_exit_pos_ids":[],
        "unknown_exit_result_rows":0
    }

    mae_mfe_per = {}
    per_pos = {}
    mae_list=[]
    mfe_list=[]
    ret_list=[]

    for pid, rs in by_pid.items():
        rs_sorted = sorted(rs, key=lambda x: x.get("time", ""))
        entry = next((x for x in rs_sorted if x.get("result")=="PAPER"), None)
        exits = [x for x in rs_sorted if x.get("result","").startswith("PAPER_EXIT_")]

        if entry:
            exit_integrity["paper_pos_ids"]+=1

        if exits:
            exit_integrity["exit_pos_ids"]+=1
            if len(exits)>1:
                exit_integrity["duplicate_exit_pos_ids"].append(pid)
            # keep newest exit for per_pos / mae_mfe view
            exit_row = exits[-1]
        else:
            exit_row=None

        mae_val = None
        mfe_val = None
        ret_val = None

        if entry and exit_row:
            exit_integrity["closed_pos_ids"]+=1
            mm = compute_mae_mfe(rows_used, entry, exit_row)
            if mm:
                mae_val,mfe_val,ret_val = mm
                mae_list.append(mae_val)
                mfe_list.append(mfe_val)
                ret_list.append(ret_val)
                mae_mfe_per[pid]={
                    "side":entry.get("side"),
                    "entry_price":entry.get("price"),
                    "exit_price":exit_row.get("price"),
                    "status":"CLOSED",
                    "mae_pct":mae_val,
                    "mfe_pct":mfe_val,
                    "ret_pct_est":ret_val,
                    "exit_type":exit_row.get("result").replace("PAPER_EXIT_",""),
                    "notes":"推定（fee未加味）"
                }
        elif entry and not exit_row:
            exit_integrity["open_pos_ids"]+=1
            exit_integrity["missing_exit_pos_ids"].append(pid)

        status = "UNKNOWN"
        if entry and exit_row:
            status = "CLOSED"
        elif entry and not exit_row:
            status = "OPEN"

        entry_price = to_float(entry.get("price")) if entry else None
        exit_ltp = to_float(exit_row.get("ltp")) if exit_row else None
        ai_score, ai_pass = _infer_ai_from_rows(rs_sorted)

        per_pos[pid] = {
            "status": status,
            "entry": {
                "time": entry.get("time") if entry else None,
                "side": entry.get("side") if entry else None,
                "price": entry_price,
            },
            "exit": {
                "time": exit_row.get("time") if exit_row else None,
                "result": exit_row.get("result") if exit_row else None,
                "ltp": exit_ltp,
            },
            "ai": {
                "score": ai_score,
                "pass": ai_pass,
            },
            "mae": mae_val,
            "mfe": mfe_val,
            "ret_pct_est": ret_val,
            "notes": "推定（fee未加味）",
        }

    # --------------------------------------------------------
    # JSON生成
    # --------------------------------------------------------

    # =========================
    # by_side / by_hour blocks
    # =========================
    def _exit_type(res: str) -> str:
        r = (res or "").strip()
        if r == "PAPER_EXIT_TP": return "TP"
        if r == "PAPER_EXIT_SL": return "SL"
        if r == "PAPER_EXIT_TIMEOUT": return "TIMEOUT"
        if r == "PAPER_EXIT_PARTIAL_TP": return "PARTIAL_TP"
        if r == "PAPER_EXIT_EOD": return "EOD"
        if r == "PAPER_EXIT_PRENEWS": return "PRENEWS"
        if r.startswith("PAPER_EXIT_"): return "UNKNOWN_EXIT"
        return ""

    def _paper_rate(paper_n: int, observe_n: int) -> float:
        denom = paper_n + observe_n
        if denom <= 0:
            return 0.0
        return round((paper_n / denom) * 100.0, 1)

    def _mean(xs):
        xs2 = [x for x in xs if x is not None]
        if not xs2:
            return 0.0
        return sum(xs2) / len(xs2)

    # ---------- by_side ----------
    by_side_block = {
        "BUY":  {"paper_n":0,"observe_n":0,"skip_n":0,"hold_n":0,"exit_n":0,"error_n":0,
                 "paper_rate_pct":0.0,"tp_n":0,"sl_n":0,"timeout_n":0,"eod_n":0,"prenews_n":0,"partial_tp_n":0},
        "SELL": {"paper_n":0,"observe_n":0,"skip_n":0,"hold_n":0,"exit_n":0,"error_n":0,
                 "paper_rate_pct":0.0,"tp_n":0,"sl_n":0,"timeout_n":0,"eod_n":0,"prenews_n":0,"partial_tp_n":0},
        "UNKNOWN":{"paper_n":0,"observe_n":0,"skip_n":0,"hold_n":0,"exit_n":0,"error_n":0,
                   "paper_rate_pct":0.0,"tp_n":0,"sl_n":0,"timeout_n":0,"eod_n":0,"prenews_n":0,"partial_tp_n":0}
    }

    for r in rows_used:
        side = (r.get("side") or "").strip().upper()
        if side not in ("BUY","SELL"):
            side = "UNKNOWN"
        cls = classify_result(r.get("result",""))
        if cls == "PAPER":
            by_side_block[side]["paper_n"] += 1
        elif cls == "OBSERVE":
            by_side_block[side]["observe_n"] += 1
        elif cls == "SKIP":
            by_side_block[side]["skip_n"] += 1
        elif cls == "HOLD":
            by_side_block[side]["hold_n"] += 1
        elif cls == "EXIT":
            by_side_block[side]["exit_n"] += 1
            et = _exit_type(r.get("result",""))
            if et == "TP": by_side_block[side]["tp_n"] += 1
            elif et == "SL": by_side_block[side]["sl_n"] += 1
            elif et == "TIMEOUT": by_side_block[side]["timeout_n"] += 1
            elif et == "EOD": by_side_block[side]["eod_n"] += 1
            elif et == "PRENEWS": by_side_block[side]["prenews_n"] += 1
            elif et == "PARTIAL_TP": by_side_block[side]["partial_tp_n"] += 1
        elif cls == "ERROR":
            by_side_block[side]["error_n"] += 1

    for k in ("BUY","SELL","UNKNOWN"):
        by_side_block[k]["paper_rate_pct"] = _paper_rate(by_side_block[k]["paper_n"], by_side_block[k]["observe_n"])

    # ---------- by_hour ----------
    by_hour_block = {str(h): {"paper_n":0,"observe_n":0,"skip_n":0,"hold_n":0,"exit_n":0,"error_n":0,
                              "paper_rate_pct":0.0,"spread_avg_pct":0.0,
                              "tp_n":0,"sl_n":0,"timeout_n":0,"eod_n":0,"prenews_n":0,"partial_tp_n":0}
                     for h in range(24)}
    spread_by_hour = {str(h): [] for h in range(24)}

    for r in rows_used:
        h = hour_from_time(r.get("time",""))
        if h is None or not (0 <= h <= 23):
            continue
        hk = str(h)
        cls = classify_result(r.get("result",""))
        if cls == "PAPER":
            by_hour_block[hk]["paper_n"] += 1
        elif cls == "OBSERVE":
            by_hour_block[hk]["observe_n"] += 1
        elif cls == "SKIP":
            by_hour_block[hk]["skip_n"] += 1
        elif cls == "HOLD":
            by_hour_block[hk]["hold_n"] += 1
        elif cls == "EXIT":
            by_hour_block[hk]["exit_n"] += 1
            et = _exit_type(r.get("result",""))
            if et == "TP": by_hour_block[hk]["tp_n"] += 1
            elif et == "SL": by_hour_block[hk]["sl_n"] += 1
            elif et == "TIMEOUT": by_hour_block[hk]["timeout_n"] += 1
            elif et == "EOD": by_hour_block[hk]["eod_n"] += 1
            elif et == "PRENEWS": by_hour_block[hk]["prenews_n"] += 1
            elif et == "PARTIAL_TP": by_hour_block[hk]["partial_tp_n"] += 1
        elif cls == "ERROR":
            by_hour_block[hk]["error_n"] += 1

        sp = to_float(r.get("spread_pct"))
        if sp is not None:
            spread_by_hour[hk].append(sp)

    for hk in by_hour_block.keys():
        by_hour_block[hk]["paper_rate_pct"] = _paper_rate(by_hour_block[hk]["paper_n"], by_hour_block[hk]["observe_n"])
        by_hour_block[hk]["spread_avg_pct"] = round(_mean(spread_by_hour[hk]), 6)

    # --------------------------------------------------------
    # DD (Drawdown) metrics — computed from per_pos ret_pct_est
    # Note: ret_pct_est is price-based approximation, not confirmed P&L
    # --------------------------------------------------------
    def _compute_drawdown_block(per_pos_dict):
        closed = [
            v for v in per_pos_dict.values()
            if v.get("status") == "CLOSED" and v.get("ret_pct_est") is not None
        ]
        # Sort by exit time so equity curve is chronological
        closed.sort(key=lambda x: x["exit"].get("time") or "")
        rets = [v["ret_pct_est"] for v in closed]
        n = len(rets)
        if n == 0:
            return {
                "n_closed": 0,
                "source": "per_pos_ret_pct_est",
                "note": "決済済みポジションなし — DD算出不可",
                "daily_max_drawdown_amount": None,
                "daily_max_drawdown_pct": None,
                "daily_equity_peak": None,
                "daily_equity_trough": None,
                "dd_recovery_minutes": None,
                "dd_recovery_count": 0,
                "max_consecutive_loss": 0,
                "loss_streak_drawdown": None,
                "recovery_factor": None,
                "profit_factor": None,
                "expectancy_per_trade": None,
            }
        # Build equity curve
        equity, peaks = [], []
        cum = peak = 0.0
        for r in rets:
            cum += r
            equity.append(cum)
            if cum > peak:
                peak = cum
            peaks.append(peak)
        # Max DD
        dds = [eq - pk for eq, pk in zip(equity, peaks)]
        max_dd = min(dds)
        max_dd_idx = dds.index(max_dd)
        peak_at_max_dd = peaks[max_dd_idx]
        max_dd_pct = (max_dd / abs(peak_at_max_dd)) if peak_at_max_dd != 0 else None
        # Recovery time (minutes) — use exit times
        dd_recovery_minutes = None
        if max_dd < 0 and max_dd_idx < n - 1:
            t_dd_str = closed[max_dd_idx]["exit"].get("time") or ""
            for i in range(max_dd_idx + 1, n):
                if equity[i] >= peak_at_max_dd:
                    t_rec_str = closed[i]["exit"].get("time") or ""
                    try:
                        t_dd_dt = datetime.strptime(t_dd_str, "%Y-%m-%d %H:%M:%S")
                        t_rec_dt = datetime.strptime(t_rec_str, "%Y-%m-%d %H:%M:%S")
                        dd_recovery_minutes = round((t_rec_dt - t_dd_dt).total_seconds() / 60, 1)
                    except Exception:
                        pass
                    break
        # DD recovery count
        dd_recovery_count = 0
        in_dd = False
        peak_run = 0.0
        for eq in equity:
            if eq > peak_run:
                if in_dd:
                    dd_recovery_count += 1
                    in_dd = False
                peak_run = eq
            elif eq < peak_run:
                in_dd = True
        # Consecutive loss
        max_consec = cur_consec = 0
        streak_dd = max_streak_dd = 0.0
        for r in rets:
            if r < 0:
                cur_consec += 1
                streak_dd += r
                if cur_consec > max_consec:
                    max_consec = cur_consec
                    max_streak_dd = streak_dd
            else:
                cur_consec = 0
                streak_dd = 0.0
        # PF / RF / expectancy
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r < 0]
        net = sum(rets)
        pf = sum(wins) / abs(sum(losses)) if losses else None
        rf = net / abs(max_dd) if max_dd < 0 else None
        exp = net / n if n > 0 else None
        return {
            "n_closed": n,
            "source": "per_pos_ret_pct_est",
            "note": "fee/spread未加味推定値。確定P&Lは dd_report.py を参照",
            "daily_max_drawdown_amount": round(max_dd, 4),
            "daily_max_drawdown_pct": round(max_dd_pct, 4) if max_dd_pct is not None else None,
            "daily_equity_peak": round(max(equity), 4),
            "daily_equity_trough": round(min(equity), 4),
            "dd_recovery_minutes": dd_recovery_minutes,
            "dd_recovery_count": dd_recovery_count,
            "max_consecutive_loss": max_consec,
            "loss_streak_drawdown": round(max_streak_dd, 4),
            "recovery_factor": round(rf, 3) if rf is not None else None,
            "profit_factor": round(pf, 3) if pf is not None else None,
            "expectancy_per_trade": round(exp, 4) if exp is not None else None,
        }

    drawdown_block = _compute_drawdown_block(per_pos)

    payload={
        "meta":{
            "spec":SPEC_VERSION,
            "generated_at_jst":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "target_day8":day8,
            "log_path":str(log_path),
            "rows_total":len(rows),
            "rows_used":len(rows_used),
            "rows_dropped":rows_dropped,
            "notes":""
        },
        "daily":{
            "paper_n":paper_n,
            "observe_n":observe_n,
            "skip_n":class_counter["SKIP"],
            "hold_n":class_counter["HOLD"],
            "exit_n":class_counter["EXIT"],
            "error_n":class_counter["ERROR"],
            "paper_rate_pct":paper_rate,
            "exit_tp_n":result_counter["PAPER_EXIT_TP"],
            "exit_sl_n":result_counter["PAPER_EXIT_SL"],
            "exit_timeout_n":result_counter["PAPER_EXIT_TIMEOUT"],
            "exit_partial_tp_n":result_counter["PAPER_EXIT_PARTIAL_TP"],
            "exit_eod_n":result_counter["PAPER_EXIT_EOD"],
            "exit_prenews_n":result_counter["PAPER_EXIT_PRENEWS"],
            "spread_over_limit_n":spread_block["over_limit_n"],
            "spread_over_limit_pct":spread_block["over_limit_pct"]
        },
        "by_side": by_side_block,
        "by_result":dict(result_counter),
        "by_hour": by_hour_block,
        "trends":Counter(r.get("trend","UNKNOWN") for r in rows_used),
        "signals":Counter(r.get("signal","NONE") for r in rows_used),
        "spread":spread_block,
        "per_pos":per_pos,
        "exit_integrity":exit_integrity,
        "mae_mfe":{
            "per_pos":mae_mfe_per,
            "summary":{
                "closed_n":len(mae_list),
                "mae_avg_pct":mean(mae_list) if mae_list else 0,
                "mfe_avg_pct":mean(mfe_list) if mfe_list else 0,
                "ret_avg_pct_est":mean(ret_list) if ret_list else 0
            }
        },
        "drawdown": drawdown_block,
        "issues":issues
    }

    out_dir=Path(args.out_dir)
    out_dir.mkdir(parents=True,exist_ok=True)
    out_path=out_dir/f"daily_report_{day8}.json"
    out_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

    print(f"[WRITE] {out_path}")

if __name__=="__main__":
    main()
