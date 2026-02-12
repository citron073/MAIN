
# ============================================================
# bot.py 完全網羅最終版
# ・PAPER_EXIT保証
# ・AI学習ログ自動出力
# ・最低数量保証
# ・将来実弾移行前提項目追加
# ============================================================

# --- 既存コードは省略 ---
# ※あなたの提示した完全版をベースに
# 以下のみ追加・修正ポイント

# ============================================================
# 最低数量保証
# ============================================================
MIN_LOT_DEFAULT = 0.001

def apply_lot_guard(cfg):
    min_lot = float(cfg.get("min_lot", MIN_LOT_DEFAULT))
    lot = float(cfg.get("lot", MIN_LOT_DEFAULT))
    return max(min_lot, lot)

# ============================================================
# AI学習ログ
# ============================================================
def append_ai_training_log(row: dict):
    try:
        path = MAIN_DIR / "ai_training_log.csv"
        path.parent.mkdir(exist_ok=True)
        import csv
        exists = path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()))
            if not exists:
                w.writeheader()
            w.writerow(row)
    except Exception as e:
        print("[WARN] ai_training_log:", e)

# ============================================================
# PAPER_EXIT保証
# ============================================================
def ensure_exit_logged(now, open_pos, outcome, hit_ltp, log_trade):
    pos_id0 = open_pos.get("pos_id")
    result_name = f"PAPER_EXIT_{outcome}" if outcome else "PAPER_EXIT_UNKNOWN"

    log_trade({
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "result": result_name,
        "side": open_pos.get("side"),
        "price": open_pos.get("entry_price"),
        "size": open_pos.get("size"),
        "ltp": hit_ltp,
        "pos_id": pos_id0,
        "note": f"auto_exit outcome={outcome}",
    })

    append_ai_training_log({
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "pos_id": pos_id0,
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
        "best_fav": open_pos.get("best_fav"),
        "extend_count": open_pos.get("extend_count"),
        "outcome": outcome,
    })

# ============================================================
# 実弾移行準備項目追加
# ============================================================
def enrich_open_pos_metrics(open_pos, spread_pct, volatility, ma_slope):
    open_pos["entry_spread_pct"] = spread_pct
    open_pos["entry_volatility_pct"] = volatility
    open_pos["entry_ma_slope"] = ma_slope
    try:
        tp = float(open_pos["tp_price"])
        sl = float(open_pos["sl_price"])
        entry = float(open_pos["entry_price"])
        risk = abs(entry - sl) / entry * 100
        reward = abs(tp - entry) / entry * 100
        open_pos["risk_pct"] = risk
        open_pos["rr_ratio"] = reward / risk if risk != 0 else None
    except:
        pass

print("[INFO] bot.py upgraded to full coverage version")
