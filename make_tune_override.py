#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
make_tune_override.py

目的:
  - ../logs/auto_tune_v1_YYYYMMDD_TOP10.csv の「1位(先頭行)」から win_min を読み取る
  - MAIN/tune_override.json を、既存フォーマットを壊さず安全に更新する
  - 基本は WIN_MIN のみ反映（bot.py 側も WIN だけ利用する前提）

使い方:
  # 指定日
  python3 make_tune_override.py --day 20260131

  # 最新のTOP10を自動検出
  python3 make_tune_override.py

  # 生成だけして中身確認（ファイルは書かない）
  python3 make_tune_override.py --day 20260131 --dry_run

  # min_paper_required を上書き
  python3 make_tune_override.py --day 20260131 --min_paper_required 30

  # PAPER件数が少なくても強制的に enabled=true（テスト用・非推奨）
  python3 make_tune_override.py --day 20260131 --force_enable
"""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List


# ===== 定数 =====
TIME_FMT = "%Y-%m-%d %H:%M:%S"
WIN_MIN_DEFAULT = 120


# ===== util =====
def now_str() -> str:
    return datetime.now().strftime(TIME_FMT)


def to_int(x) -> Optional[int]:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s == "":
            return None
        return int(float(s))  # "60.0" 等も許可
    except Exception:
        return None


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )


def get_logs_dir() -> Path:
    # MAIN/ から見て ../logs
    here = Path(__file__).resolve().parent
    return here.parent / "logs"


# ===== TOP10 CSV =====
def pick_top10_csv(logs_dir: Path, day: Optional[str]) -> Path:
    if day:
        p = logs_dir / f"auto_tune_v1_{day}_TOP10.csv"
        if not p.exists():
            raise FileNotFoundError(f"{p} が見つかりません")
        return p

    files = sorted(logs_dir.glob("auto_tune_v1_*_TOP10.csv"))
    if not files:
        raise FileNotFoundError("logs/auto_tune_v1_*_TOP10.csv が見つかりません")
    return files[-1]


def read_first_row(csv_path: Path) -> Tuple[Dict[str, str], List[str]]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        first = next(reader, None)
        if not first:
            raise ValueError(f"{csv_path} は空です")
        return first, (reader.fieldnames or [])


# ===== 抽出 =====
def extract_win_from_top1(top1: Dict[str, str]) -> int:
    candidates = ["win_min", "win", "window_min", "window", "WIN_MIN", "WIN"]
    for k in candidates:
        if k in top1:
            v = to_int(top1.get(k))
            if v is not None:
                return v

    for k, v in top1.items():
        if "win" in (k or "").lower():
            vv = to_int(v)
            if vv is not None:
                return vv

    raise ValueError("TOP10の1位行から win_min を特定できません")


def extract_paper_count_hint(top1: Dict[str, str]) -> Optional[int]:
    candidates = ["papers", "paper", "paper_n", "n_paper", "count", "n", "N"]
    for k in candidates:
        if k in top1:
            v = to_int(top1.get(k))
            if v is not None:
                return v

    for k, v in top1.items():
        if "paper" in (k or "").lower():
            vv = to_int(v)
            if vv is not None:
                return vv
    return None


def clamp_in_bounds(v: int, bounds: Tuple[int, int]) -> Optional[int]:
    lo, hi = bounds
    if v < lo or v > hi:
        return None
    return v


# ===== schema =====
def ensure_schema(base: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(base) if isinstance(base, dict) else {}

    d.setdefault("enabled", False)
    d.setdefault("apply_scope", "PAPER_ONLY")
    d.setdefault("apply_once_per_day", True)
    d.setdefault("max_change_per_day", 1)

    d.setdefault("bounds", {})
    if not isinstance(d["bounds"], dict):
        d["bounds"] = {}
    d["bounds"].setdefault("win_min", [30, 180])

    d.setdefault("override", {})
    if not isinstance(d["override"], dict):
        d["override"] = {}
    d["override"].setdefault("win_min", WIN_MIN_DEFAULT)

    d.setdefault("meta", {})
    if not isinstance(d["meta"], dict):
        d["meta"] = {}
    d["meta"].setdefault("source", "")
    d["meta"].setdefault("generated_at", "")
    d["meta"].setdefault("min_paper_required", 30)
    d["meta"].setdefault("note", "")
    d["meta"].setdefault("paper_n_hint", 0)
    d["meta"].setdefault("disabled_reason", "")

    d.setdefault("rollback", {})
    if not isinstance(d["rollback"], dict):
        d["rollback"] = {}
    d["rollback"].setdefault("enabled", True)
    d["rollback"].setdefault("mode", "ABS")
    d["rollback"].setdefault("min_exits_required", 20)
    d["rollback"].setdefault("tp_rate_min", 25.0)
    d["rollback"].setdefault("sl_rate_max", 15.0)
    d["rollback"].setdefault("timeout_rate_max", 80.0)

    return d


# ===== main =====
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None)
    ap.add_argument("--top10_path", default=None)
    ap.add_argument("--out", default=None)

    ap.add_argument("--min_paper_required", type=int, default=None)
    ap.add_argument("--note", default=None)
    ap.add_argument("--force_enable", action="store_true")
    ap.add_argument("--dry_run", action="store_true")

    args = ap.parse_args()

    logs_dir = get_logs_dir()
    top10_csv = Path(args.top10_path) if args.top10_path else pick_top10_csv(logs_dir, args.day)
    top1, fieldnames = read_first_row(top10_csv)

    out_path = Path(args.out) if args.out else (Path(__file__).resolve().parent / "tune_override.json")

    current = load_json(out_path)
    cfg = ensure_schema(current)

    b = cfg.get("bounds", {}).get("win_min", [30, 180])
    try:
        bounds = (int(b[0]), int(b[1]))
    except Exception:
        bounds = (30, 180)

    win = extract_win_from_top1(top1)
    win_ok = clamp_in_bounds(win, bounds)
    if win_ok is None:
        raise ValueError(f"win_min={win} が bounds={bounds} の範囲外")

    paper_n = extract_paper_count_hint(top1)

    cfg["meta"]["source"] = top10_csv.name
    cfg["meta"]["generated_at"] = now_str()

    if args.min_paper_required is not None:
        cfg["meta"]["min_paper_required"] = int(args.min_paper_required)

    if args.note is not None:
        cfg["meta"]["note"] = args.note

    cfg["override"]["win_min"] = int(win_ok)

    min_req = int(cfg["meta"].get("min_paper_required", 30))

    if args.force_enable:
        cfg["enabled"] = True
        cfg["meta"]["paper_n_hint"] = int(paper_n or 0)
        cfg["meta"]["disabled_reason"] = ""
    else:
        if paper_n is None:
            cfg["enabled"] = False
            cfg["meta"]["paper_n_hint"] = 0
            cfg["meta"]["disabled_reason"] = "paper_n unknown"
        elif paper_n >= min_req:
            cfg["enabled"] = True
            cfg["meta"]["paper_n_hint"] = int(paper_n)
            cfg["meta"]["disabled_reason"] = ""
        else:
            cfg["enabled"] = False
            cfg["meta"]["paper_n_hint"] = int(paper_n)
            cfg["meta"]["disabled_reason"] = f"paper_n={paper_n} < min_required={min_req}"

    cfg["apply_scope"] = "PAPER_ONLY"

    print(f"[INFO] top10: {top10_csv}")
    print(f"[INFO] top1 columns: {fieldnames}")
    print(f"[INFO] extracted win_min: {win_ok} bounds={bounds}")
    print(f"[INFO] paper_n_hint: {paper_n} min_required={min_req}")
    print(f"[INFO] enabled: {cfg['enabled']}")
    print(f"[INFO] out: {out_path}")

    if args.dry_run:
        print("\n--- tune_override.json (preview) ---")
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        return

    save_json(out_path, cfg)
    print("[OK] saved")


if __name__ == "__main__":
    main()
