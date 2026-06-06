# ============================================================
# [FROZEN ARCHIVE - 2026-04-22]
# このファイルは参照・削除禁止の凍結アーカイブです。
# 現行の売買ロジックは MAIN/bot.py を使用してください。
# 目的: vNext-STRUCTURE (AI完全一元化) の実装実験スナップショット。
#       MAIN への昇格前に凍結。mainとの差分比較・リバートの際に参照する。
# ============================================================
# Trading Bot vNext-STRUCTURE
# AI完全一元化版
# ============================================================

import os
import json
import csv
import time
import atexit
import signal
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

# ============================================================
# PATH
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR.parent / "logs"
CONTROL_PATH = BASE_DIR / "CONTROL.csv"
AI_MODEL_PATH = BASE_DIR / "ai_model.json"
STATE_PATH = BASE_DIR / "state.json"
RUN_LOCK_DIR = BASE_DIR / ".run_lock"

# ============================================================
# LOCK
# ============================================================

def acquire_run_lock():
    """二重起動防止ロック。
    - .run_lock が残っていても、PIDが死んでいれば自動回復
    """
    import os, time

    # 既存ロックがある場合：pidを見て生存判定
    if RUN_LOCK_DIR.exists():
        pid = None
        info = RUN_LOCK_DIR / "lockinfo.txt"
        if info.exists():
            try:
                txt = info.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r"pid\s*=\s*(\d+)", txt)
                if m:
                    pid = int(m.group(1))
            except Exception:
                pid = None

        if pid is not None:
            try:
                os.kill(pid, 0)  # 生存チェック（権限エラー以外は存在する扱い）
                print("[SKIP] already running (run lock exists)")
                return False
            except PermissionError:
                print("[SKIP] already running (run lock exists)")
                return False
            except ProcessLookupError:
                # PIDが死んでる → ロック掃除して続行
                try:
                    for f in RUN_LOCK_DIR.iterdir():
                        try: f.unlink()
                        except Exception: pass
                    RUN_LOCK_DIR.rmdir()
                except Exception:
                    pass
            except Exception:
                # 不明なエラーは安全側でスキップ
                print("[SKIP] already running (run lock exists)")
                return False
        else:
            # pidが取れないロックは古い可能性 → 掃除して続行
            try:
                for f in RUN_LOCK_DIR.iterdir():
                    try: f.unlink()
                    except Exception: pass
                RUN_LOCK_DIR.rmdir()
            except Exception:
                pass

    RUN_LOCK_DIR.mkdir(exist_ok=True)
    with open(RUN_LOCK_DIR / "lockinfo.txt", "w", encoding="utf-8") as f:
        f.write(f"pid={os.getpid()}\n")
        f.write(f"start={datetime.datetime.now().isoformat()}\n")
    return True



# ============================================================
# CONTROL LOAD
# ============================================================

def load_control() -> Dict[str, str]:
    if not CONTROL_PATH.exists():
        raise RuntimeError("CONTROL.csv not found")

    out = {}
    with open(CONTROL_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out[row["key"]] = row["value"]
    return out


# ============================================================
# AI MODEL LOAD
# ============================================================

def load_ai_model() -> Dict[str, Any]:
    """Return AI runtime config normalized for ai_decision().

    Priority:
      CONTROL.csv ai_* (dashboard) > ai_model.json > safe defaults

    Returns:
      {
        "enabled": bool,
        "mode": "OFF"|"SCORE_ONLY"|"VETO"|"GATE",
        "threshold_gate": float,
        "threshold_veto": float,
      }
    """
    model: Dict[str, Any] = {
        "enabled": False,
        "mode": "OFF",
        "threshold_gate": 0.55,
        "threshold_veto": 0.30,
    }

    # 1) ai_model.json (tolerant parse)
    try:
        p = AI_MODEL_PATH
        if hasattr(p, "exists") and p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                # accept several possible shapes
                if "enabled" in raw:
                    model["enabled"] = bool(raw.get("enabled"))
                # raw may contain ai_enabled / ai_mode like your current dict
                if "ai_enabled" in raw and "enabled" not in raw:
                    model["enabled"] = bool(raw.get("ai_enabled"))
                if "mode" in raw:
                    model["mode"] = str(raw.get("mode") or "OFF").upper()
                elif "ai_mode" in raw:
                    # ADVISORY/FILTER/DECISION -> OFF/SCORE_ONLY/VETO/GATE
                    m = str(raw.get("ai_mode") or "OFF").upper()
                    mapping = {"OFF":"OFF","ADVISORY":"SCORE_ONLY","SCORE_ONLY":"SCORE_ONLY","FILTER":"VETO","VETO":"VETO","DECISION":"GATE","GATE":"GATE"}
                    model["mode"] = mapping.get(m, "OFF")

                # thresholds
                for k_src, k_dst in [
                    ("threshold_gate", "threshold_gate"),
                    ("threshold_veto", "threshold_veto"),
                    ("ai_threshold", "threshold_gate"),
                    ("ai_veto_threshold", "threshold_veto"),
                ]:
                    if k_src in raw:
                        try:
                            model[k_dst] = float(raw.get(k_src) or model[k_dst])
                        except Exception:
                            pass
    except Exception:
        pass

    # 2) CONTROL overrides (dashboard keys)
    try:
        c = load_control()
        ai_on = (c.get("ai_model_enabled", "") or "").strip()
        if ai_on == "":
            ai_on = (c.get("ai_enabled", "0") or "0").strip()
        model["enabled"] = (ai_on == "1")

        cmode = str(c.get("ai_mode", model.get("mode", "OFF")) or "OFF").strip().upper()
        if cmode not in ("OFF", "SCORE_ONLY", "VETO", "GATE"):
            cmode = "OFF"
        model["mode"] = cmode

        if "ai_threshold" in c:
            try:
                model["threshold_gate"] = float(c.get("ai_threshold") or model["threshold_gate"])
            except Exception:
                pass
        if "ai_veto_threshold" in c:
            try:
                model["threshold_veto"] = float(c.get("ai_veto_threshold") or model["threshold_veto"])
            except Exception:
                pass
    except Exception:
        pass

    return model



# ============================================================
# STATE LOAD/SAVE
# ============================================================

def load_state():
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except:
        return {}

def save_state(state: Dict[str, Any]):
    STATE_PATH.write_text(json.dumps(state, indent=2))


# ============================================================
# AI DECISION
# ============================================================

def ai_decision(score: float, model: Dict[str, Any]) -> bool:
    if not model.get("enabled", False):
        return True

    mode = model.get("mode", "OFF")

    if mode == "OFF":
        return True

    if mode == "SCORE_ONLY":
        return True

    if mode == "VETO":
        return score >= model.get("threshold_veto", 0.30)

    if mode == "GATE":
        return score >= model.get("threshold_gate", 0.55)

    return True


# ============================================================
# ORPHAN HANDLING
# ============================================================

def handle_orphan(control: Dict[str, str]):
    mode = control.get("orphan_mode", "STOP").upper()

    if mode == "AUTO_CLEAR":
        print("[ORPHAN] AUTO_CLEAR mode")
        return "CLEAR"
    else:
        print("[ORPHAN] STOP mode")
        return "STOP"


# ============================================================
# FEE HANDLING
# ============================================================

def compute_fee_pct(fee, entry_price, control):
    if control.get("fee_unit", "ABS") == "ABS":
        return (fee / entry_price) * 100
    return fee


# ============================================================
# LOG WRITE
# ============================================================

def write_log(row: Dict[str, Any]):
    LOGS_DIR.mkdir(exist_ok=True)
    fname = LOGS_DIR / f"trade_log_{datetime.now().strftime('%Y%m%d')}.csv"
    file_exists = fname.exists()

    with open(fname, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


# ============================================================
# MAIN
# ============================================================

def main():

    print("[INFO] start:", datetime.now())

    if not acquire_run_lock():
        return

    control = load_control()
    ai_model = load_ai_model()
    state = load_state()

    # 稼働判定
    if control.get("today_on") != "1":
        print("[SKIP] today_off")
        return

    if control.get("trade_enabled") != "1":
        print("[SKIP] trade_disabled")
        return

    if control.get("safety_hard_block") == "1":
        print("[SKIP] safety_hard_block ON")
        return

    # ===== ここに価格取得 / MA計算 / 環境認識 =====
    score = 0.62  # ← 仮（将来AIAdapter）

    if not ai_decision(score, ai_model):
        print("[AI] blocked")
        write_log({
            "time": datetime.now(),
            "result": "AI_BLOCKED",
            "ai_score": score,
        })
        return

    # ===== 仮エントリー =====
    print("[ENTRY] simulated")
    write_log({
        "time": datetime.now(),
        "result": "PAPER",
        "ai_score": score,
    })


if __name__ == "__main__":
    main()
