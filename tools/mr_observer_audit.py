#!/usr/bin/env python3
"""MR Observer audit report.

Audits why mr_observe_enabled=0 and whether re-enabling makes sense.
Reads mr_observe sidecar logs if available.

Usage:
  python3 tools/mr_observer_audit.py [--logs-dir PATH] [--days N]
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT.parent / "logs"
MR_LOGS_DIR = LOGS_DIR / "instances" / "mr_observe"
CONTROL_CSV = ROOT / "CONTROL.csv"

TODAY8 = datetime.now().strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_control() -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not CONTROL_CSV.exists():
        return out
    with CONTROL_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            k = str(row.get("key", "")).strip()
            v = str(row.get("value", "")).strip()
            if k:
                out[k] = v
    return out


def _read_mr_logs(days: int) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if not MR_LOGS_DIR.exists():
        return rows
    today = datetime.now().date()
    for i in range(days):
        d = today - timedelta(days=i)
        log = MR_LOGS_DIR / f"trade_log_{d.strftime('%Y%m%d')}.csv"
        if not log.exists():
            continue
        try:
            with log.open(encoding="utf-8", errors="replace") as f:
                rows.extend(csv.DictReader(f))
        except Exception:
            pass
    return rows


def _note_val(note: str, key: str) -> str:
    import re
    m = re.search(rf"\b{re.escape(key)}=([^\s]+)", str(note or ""))
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyse(days: int = 30) -> Dict[str, Any]:
    ctrl = _read_control()
    mr_rows = _read_mr_logs(days)

    # config state
    config_state = {
        "mr_observe_enabled": ctrl.get("mr_observe_enabled", "not_set"),
        "mr_paper_enabled": ctrl.get("mr_paper_enabled", ctrl.get("observe_mr_paper_enabled", "not_set")),
        "mr_paper_min_rank": ctrl.get("mr_paper_min_rank", "A(default)"),
        "mr_paper_require_trigger": ctrl.get("mr_paper_require_trigger", "1(default)"),
        "mr_paper_require_reclaim": ctrl.get("mr_paper_require_reclaim", "1(default)"),
        "mr_spike_min_move_pct": ctrl.get("mr_spike_min_move_pct", "0.18(default)"),
        "mr_touch_tolerance_pct": ctrl.get("mr_touch_tolerance_pct", "0.08(default)"),
        "mr_range_max_ma_slope_pct": ctrl.get("mr_range_max_ma_slope_pct", "0.08(default)"),
        "mr_range_max_ma_gap_pct": ctrl.get("mr_range_max_ma_gap_pct", "0.18(default)"),
        "mr_stop_min_distance_pct": ctrl.get("mr_stop_min_distance_pct", "1.0(default)"),
    }

    # sidecar log stats
    sidecar_available = MR_LOGS_DIR.exists()
    sidecar_total = len(mr_rows)
    result_counts: Counter = Counter()
    rank_counts: Counter = Counter()
    paper_entries = 0
    paper_exits_tp = paper_exits_sl = paper_exits_other = 0

    for r in mr_rows:
        result = str(r.get("result", ""))
        result_counts[result] += 1
        note = str(r.get("note", ""))
        rank = _note_val(note, "mr_rank")
        if rank:
            rank_counts[rank] += 1
        if result == "PAPER":
            if _note_val(note, "strategy") == "MR" or _note_val(note, "mr_paper") == "1":
                paper_entries += 1
        if result == "PAPER_EXIT_TP":
            paper_exits_tp += 1
        elif result == "PAPER_EXIT_SL":
            paper_exits_sl += 1
        elif result.startswith("PAPER_EXIT_"):
            paper_exits_other += 1

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lookback_days": days,
        "config_state": config_state,
        "architecture_notes": {
            "entry_guard_line": "bot.py:7536 — `if cfg.observe_only and cfg.mr_observe_enabled`",
            "volume_score_hardcoded": True,
            "volume_score_reason": "bitFlyer tick feed does not include volume; always 1 (free point)",
            "max_possible_score": 4,
            "rank_A_requires": "score>=4 (spike + volume=1 + range_regime + structure>=2touches)",
        },
        "sidecar": {
            "available": sidecar_available,
            "log_dir": str(MR_LOGS_DIR),
            "total_rows": sidecar_total,
            "result_counts": dict(result_counts.most_common(10)),
            "rank_counts": dict(rank_counts),
            "paper_entries": paper_entries,
            "paper_exits_tp": paper_exits_tp,
            "paper_exits_sl": paper_exits_sl,
            "paper_exits_other": paper_exits_other,
        },
        "recommendation": "A",
        "recommendation_detail": (
            "OFF維持。mr_observe_enabled は observe_only=True 専用ガードに守られており、"
            "メインbot（observe_only=False）では CONTROL.csv で1にしても一切発動しない。"
            "再有効化するなら observe_only サイドカーとして別インスタンスで起動する既存設計を使うべき。"
            "コードを変更してメインエントリーフィルターとして組み込む場合は別途改修が必要。"
        ),
    }


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------

def format_report(data: Dict[str, Any]) -> str:
    cfg = data["config_state"]
    arch = data["architecture_notes"]
    sc = data["sidecar"]
    rec = data["recommendation"]
    rec_detail = data["recommendation_detail"]

    lines = [
        f"# MR Observer 監査レポート ({data['generated_at']})",
        "",
        "## 1. 現在の設定値",
        "",
    ]
    for k, v in cfg.items():
        lines.append(f"  - `{k}` = `{v}`")

    lines += [
        "",
        "## 2. アーキテクチャ上の重要事実",
        "",
        f"  - エントリーガード: `{arch['entry_guard_line']}`",
        "  - **MR Observer は `observe_only=True` 専用サブシステム**",
        "    - メインbot（LIVE/PAPER）は `observe_only=False` で動作するため、",
        "      CONTROL.csv で `mr_observe_enabled=1` にしても**一切発動しない**",
        "    - 設計上、sidecar インスタンス（start_mr_observe.sh）から起動する想定",
        "",
        "  - volume_score はハードコード 1（常に加算）",
        f"    - 理由: {arch['volume_score_reason']}",
        f"    - 最大スコア = {arch['max_possible_score']}",
        f"    - Rank A 条件: {arch['rank_A_requires']}",
        "",
        "## 3. ERフィルターとの関係",
        "",
        "  - ER（Efficiency Ratio）フィルターはトレンドの「強さ」を測る",
        "  - MR Observer はS/R水準への「スパイク＋リクレイム」パターンを検出する",
        "  - **測定軸が完全に異なる**ため、両方同時に使っても干渉しない",
        "  - ただしMRはメインエントリーへのフィルターではなく別戦略なので、",
        "    ERとの「組み合わせ効果」は現行設計では生じない",
        "",
        "## 4. 再有効化した場合のメリット・リスク",
        "",
        "  ### メリット",
        "  - S/R水準でのスパイク回帰戦略として、SMAクロス戦略とは異なる",
        "    エッジを持つ可能性がある",
        "  - Rank A（全条件一致）かつ reclaim 確認後エントリーなので、",
        "    理論上の勝率は高い",
        "",
        "  ### リスク",
        "  - mr_stop_min_distance_pct=1.0% は現行SL(-0.14%)の約7倍のストップ幅",
        "    → MR 戦略のリスクは既存TP/SLより大きい",
        "  - volume_score=1 固定は scoring の歪みを生む",
        "  - S/R水準の検出アルゴリズム（touch_tolerance_pct=0.08%）は",
        "    BTC-FXの高volatilityで誤検出の可能性がある",
        "",
    ]

    # Sidecar stats
    lines += [
        "## 5. Sidecar ログ統計（過去{}日）".format(data["lookback_days"]),
        "",
        f"  - Sidecar ログディレクトリ: `{sc['log_dir']}`",
        f"  - データ存在: {'あり' if sc['available'] else 'なし（未起動 or ログなし）'}",
    ]
    if sc["total_rows"] > 0:
        lines.append(f"  - 総行数: {sc['total_rows']:,}")
        lines.append("  - result 分布:")
        for r, n in sc["result_counts"].items():
            lines.append(f"    - {r}: {n}")
        lines.append("  - MR rank 分布:")
        for r, n in sorted(sc["rank_counts"].items()):
            lines.append(f"    - Rank {r}: {n}")
        if sc["paper_entries"] > 0:
            tp, sl, ot = sc["paper_exits_tp"], sc["paper_exits_sl"], sc["paper_exits_other"]
            tot_ex = tp + sl + ot
            wr = f"{tp/tot_ex*100:.0f}%" if tot_ex > 0 else "N/A"
            lines += [
                f"  - MRエントリー: {sc['paper_entries']}件",
                f"  - EXIT内訳: TP={tp} SL={sl} その他={ot}  WR={wr}",
            ]
    else:
        lines.append("  - ログなし（Sidecar 未起動、またはデータ期間外）")

    lines += [
        "",
        "## 6. 推奨アクション",
        "",
        f"  **{rec}: OFF維持**",
        "",
        f"  {rec_detail}",
        "",
        "  ### 将来的に使う場合の手順",
        "  1. `start_mr_observe.sh` で observe_only サイドカーを起動",
        "  2. `logs/instances/mr_observe/` にデータが蓄積されるのを確認",
        "  3. `tools/mr_observe_summary.py` でランク別成績を確認",
        "  4. Rank A の WR が十分高ければ `mr_paper_enabled=1` で",
        "     サイドカー内でのペーパートレードを有効化",
        "  5. メインbot へのフィルター組み込みは別途コード改修が必要",
        "",
        "  ### メインbot フィルターとして使う場合（別途改修が必要）",
        "  - `resolve_mr_observe` の呼び出しを observe_only ガードから切り出す",
        "  - FILTER_NG の場合にエントリーをブロックするロジックを追加",
        "  - 影響範囲が大きいため、慎重に設計してから実施すること",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--output-dir", default=str(ROOT / "reports"))
    p.add_argument("--print-only", action="store_true")
    args = p.parse_args()

    data = analyse(days=args.days)
    report_md = format_report(data)
    print(report_md)

    if not args.print_only:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(exist_ok=True)
        md_path = out_dir / f"mr_observer_audit_{TODAY8}.md"
        json_path = out_dir / f"mr_observer_audit_{TODAY8}.json"
        md_path.write_text(report_md, encoding="utf-8")
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[saved] {md_path}")
        print(f"[saved] {json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
